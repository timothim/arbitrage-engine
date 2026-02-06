"""
Main arbitrage engine orchestrator.

Coordinates all system components and manages the
trading lifecycle.
"""

import asyncio
import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from arbitrage.config.settings import Settings
from arbitrage.core.event_bus import EventBus
from arbitrage.core.types import BBO, Opportunity
from arbitrage.exchange.client import BinanceClient
from arbitrage.execution.executor import ExecutorConfig, TriangleExecutor
from arbitrage.execution.recovery import PositionRecovery
from arbitrage.execution.risk import RiskLimits, RiskManager
from arbitrage.market.orderbook import OrderbookManager
from arbitrage.market.symbols import SymbolManager
from arbitrage.market.websocket import WebSocketManager
from arbitrage.strategy.calculator import ArbitrageCalculator
from arbitrage.strategy.graph import TriangleDiscovery
from arbitrage.strategy.opportunity import OpportunityDetector
from arbitrage.telemetry.logger import AsyncLogger, setup_logging
from arbitrage.telemetry.metrics import MetricsCollector
from arbitrage.telemetry.reporter import CLIReporter
from arbitrage.utils.time import get_timestamp_us


logger = logging.getLogger(__name__)


class ArbitrageEngine:
    """
    Main trading engine orchestrator.

    Manages the complete lifecycle of:
    - Exchange connectivity
    - Market data ingestion
    - Opportunity detection
    - Trade execution
    - Risk management
    - Telemetry and reporting
    """

    def __init__(self, settings: Settings) -> None:
        """
        Initialize the engine.

        Args:
            settings: Application settings.
        """
        self._settings = settings
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Core components (initialized in setup)
        self._client: BinanceClient | None = None
        self._websocket: WebSocketManager | None = None
        self._orderbook: OrderbookManager | None = None
        self._symbol_manager: SymbolManager | None = None
        self._discovery: TriangleDiscovery | None = None
        self._calculator: ArbitrageCalculator | None = None
        self._detector: OpportunityDetector | None = None
        self._executor: TriangleExecutor | None = None
        self._risk_manager: RiskManager | None = None
        self._recovery: PositionRecovery | None = None

        # Infrastructure
        self._event_bus = EventBus()
        self._metrics = MetricsCollector()
        self._reporter: CLIReporter | None = None
        self._async_logger: AsyncLogger | None = None

        # State
        self._balance = 0.0
        self._triangles: list[Any] = []

    async def setup(self) -> None:
        """Initialize all components."""
        logger.info("Initializing arbitrage engine...")

        # Set up logging
        self._async_logger = setup_logging(
            level=self._settings.log_level,
        )

        # Create exchange client
        self._client = BinanceClient(
            api_key=self._settings.binance_api_key.get_secret_value(),
            api_secret=self._settings.binance_api_secret.get_secret_value(),
            use_testnet=self._settings.use_testnet,
        )

        # Load exchange info and symbols
        logger.info("Loading exchange information...")
        exchange_info = await self._client.get_exchange_info()

        self._symbol_manager = SymbolManager()
        symbol_count = self._symbol_manager.load_from_exchange_info(exchange_info)
        logger.info(f"Loaded {symbol_count} tradeable symbols")

        # Discover triangles
        logger.info("Discovering arbitrage triangles...")
        self._discovery = TriangleDiscovery(self._symbol_manager)
        self._discovery.build_graph()
        self._triangles = self._discovery.find_triangles(
            base_asset=self._settings.base_currency,
            max_triangles=self._settings.max_triangles,
        )
        logger.info(f"Found {len(self._triangles)} valid triangles")

        # Get symbols for WebSocket subscription
        ws_symbols = list(self._discovery.get_all_symbols())
        logger.info(f"Subscribing to {len(ws_symbols)} symbol streams")

        # Initialize orderbook
        self._orderbook = OrderbookManager()
        self._orderbook.register_callback(self._on_price_update)

        # Initialize WebSocket manager
        self._websocket = WebSocketManager(use_testnet=self._settings.use_testnet)
        self._websocket.subscribe_book_tickers(ws_symbols)
        self._websocket.add_handler(self._on_ws_message)

        # Initialize calculator and detector
        self._calculator = ArbitrageCalculator(
            fee_rate=self._settings.fee_rate,
            slippage_buffer=self._settings.slippage_buffer,
        )

        self._detector = OpportunityDetector(
            calculator=self._calculator,
            orderbook=self._orderbook,
            triangles=self._triangles,
            min_profit_threshold=self._settings.min_profit_threshold,
        )
        self._detector.register_callback(self._on_opportunity)

        # Initialize risk management
        self._risk_manager = RiskManager(
            limits=RiskLimits(
                max_position_pct=self._settings.max_position_pct,
                daily_loss_limit=self._settings.daily_loss_limit,
                max_hold_time_ms=self._settings.max_hold_time_ms,
            ),
        )

        # Initialize recovery handler
        self._recovery = PositionRecovery(
            client=self._client,
            symbol_manager=self._symbol_manager,
            base_currency=self._settings.base_currency,
        )

        # Initialize executor
        self._executor = TriangleExecutor(
            client=self._client,
            symbol_manager=self._symbol_manager,
            risk_manager=self._risk_manager,
            recovery=self._recovery,
            config=ExecutorConfig(
                dry_run=self._settings.dry_run,
                slippage_buffer=self._settings.slippage_buffer,
            ),
        )

        # Initialize reporter
        self._reporter = CLIReporter(
            metrics=self._metrics,
            dry_run=self._settings.dry_run,
        )
        self._reporter.set_state(
            triangle_count=len(self._triangles),
            stream_count=len(ws_symbols),
        )

        # Get initial balance
        try:
            self._balance = await self._client.get_balance(self._settings.base_currency)
            self._risk_manager.update_balance(self._balance)
            self._reporter.set_state(balance=self._balance)
            logger.info(f"Initial balance: {self._balance} {self._settings.base_currency}")
        except Exception as e:
            logger.warning(f"Could not fetch balance: {e}")

        logger.info("Engine initialization complete")

    async def _on_ws_message(self, data: dict[str, Any]) -> None:
        """Handle incoming WebSocket message."""
        # Parse and update orderbook
        if "s" in data:  # bookTicker format
            from arbitrage.core.types import BookTickerData

            ticker_data: BookTickerData = {
                "s": data["s"],
                "b": data["b"],
                "B": data["B"],
                "a": data["a"],
                "A": data["A"],
                "u": data.get("u", 0),
            }
            self._orderbook.update_from_ticker(ticker_data)  # type: ignore

    def _on_price_update(self, bbo: BBO) -> None:
        """Handle price update from orderbook."""
        start_time = get_timestamp_us()

        # Check for opportunities
        opportunities = self._detector.on_price_update(bbo)  # type: ignore

        # Record latency
        latency = get_timestamp_us() - start_time
        self._metrics.record_latency("tick_to_calc", latency)

        # Track opportunities found
        self._metrics.increment_counter("price_updates")
        if opportunities:
            self._metrics.increment_counter("opportunities_found", len(opportunities))

    def _on_opportunity(self, opportunity: Opportunity) -> None:
        """Handle detected opportunity."""
        self._metrics.record_opportunity(opportunity.profit_pct)

        logger.debug(
            f"Opportunity: {opportunity.path.id} "
            f"profit={opportunity.profit_pct:.4f}% "
            f"size={opportunity.max_trade_qty:.4f}"
        )

        # Queue for execution if profitable
        if opportunity.is_profitable:
            asyncio.create_task(self._execute_opportunity(opportunity))

    async def _execute_opportunity(self, opportunity: Opportunity) -> None:
        """Execute an opportunity."""
        if not self._executor or not self._risk_manager:
            return

        if not self._risk_manager.is_trading_allowed:
            return

        start_time = get_timestamp_us()

        result = await self._executor.execute(opportunity)

        # Record metrics
        exec_latency = get_timestamp_us() - start_time
        self._metrics.record_latency("calc_to_order", exec_latency)
        self._metrics.record_execution(
            success=result.is_success,
            profit=result.total_profit,
            commission=result.total_commission,
        )

        if result.is_success:
            logger.info(
                f"Execution success: {opportunity.path.id} "
                f"profit={result.total_profit:.6f} "
                f"latency={exec_latency}μs"
            )
        else:
            logger.warning(
                f"Execution failed: {opportunity.path.id} " f"reason={result.error_message}"
            )

    async def run(self) -> None:
        """Run the main trading loop."""
        self._running = True

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_shutdown)

        try:
            logger.info("Starting trading engine...")

            # Start WebSocket connections
            await self._websocket.start()  # type: ignore

            # Wait for connections
            logger.info("Waiting for WebSocket connections...")
            connected = await self._websocket.wait_connected(timeout=30.0)  # type: ignore

            if not connected:
                logger.error("Failed to establish all WebSocket connections")
                return

            logger.info("All connections established, starting trading loop")

            # Start reporter
            if self._reporter:
                self._reporter.start(interval=1.0)

            # Main loop - just wait for shutdown
            await self._shutdown_event.wait()

        except Exception as e:
            logger.error(f"Engine error: {e}")
            raise

        finally:
            await self.shutdown()

    def _handle_shutdown(self) -> None:
        """Handle shutdown signal."""
        logger.info("Shutdown signal received")
        self._running = False
        self._shutdown_event.set()

    async def shutdown(self) -> None:
        """Gracefully shut down the engine."""
        logger.info("Shutting down engine...")

        self._running = False

        # Stop reporter
        if self._reporter:
            self._reporter.stop()
            self._reporter.print_summary()

        # Stop WebSocket connections
        if self._websocket:
            await self._websocket.stop()

        # Close exchange client
        if self._client:
            await self._client.close()

        # Stop async logger
        if self._async_logger:
            self._async_logger.stop()

        logger.info("Engine shutdown complete")

    @property
    def is_running(self) -> bool:
        """Check if engine is running."""
        return self._running

    @property
    def metrics(self) -> MetricsCollector:
        """Get metrics collector."""
        return self._metrics


@asynccontextmanager
async def create_engine(settings: Settings) -> AsyncIterator[ArbitrageEngine]:
    """
    Create and manage engine lifecycle.

    Usage:
        async with create_engine(settings) as engine:
            await engine.run()
    """
    engine = ArbitrageEngine(settings)

    try:
        await engine.setup()
        yield engine
    finally:
        await engine.shutdown()
