"""
Simulation engine that runs the full arbitrage system with fake data.

Provides a complete demo experience without requiring real API keys.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from arbitrage.core.types import BBO, Opportunity, OrderSide, TriangleLeg, TrianglePath
from arbitrage.market.orderbook import OrderbookManager
from arbitrage.simulation.market import MarketSimulator
from arbitrage.strategy.calculator import ArbitrageCalculator
from arbitrage.strategy.opportunity import OpportunityDetector
from arbitrage.telemetry.metrics import MetricsCollector
from arbitrage.utils.time import get_timestamp_us


logger = logging.getLogger(__name__)


@dataclass
class SimulationStats:
    """Statistics from simulation run."""

    ticks_processed: int = 0
    opportunities_found: int = 0
    opportunities_profitable: int = 0
    simulated_executions: int = 0
    total_simulated_profit: float = 0.0
    best_opportunity_pct: float = 0.0


class SimulationEngine:
    """
    Runs complete arbitrage simulation for demo purposes.

    Combines:
    - Market simulator for fake price data
    - Real orderbook and strategy components
    - Simulated execution
    """

    # Pre-defined triangles for demo
    DEMO_TRIANGLES = [
        ("USDT", "BTC", "ETH", "BTCUSDT", "ETHBTC", "ETHUSDT"),
        ("USDT", "BTC", "BNB", "BTCUSDT", "BNBBTC", "BNBUSDT"),
        ("USDT", "BTC", "SOL", "BTCUSDT", "SOLBTC", "SOLUSDT"),
        ("USDT", "ETH", "BNB", "ETHUSDT", "BNBETH", "BNBUSDT"),
        ("USDT", "ETH", "LINK", "ETHUSDT", "LINKETH", "LINKUSDT"),
        ("USDT", "BTC", "XRP", "BTCUSDT", "XRPBTC", "XRPUSDT"),
        ("USDT", "BTC", "ADA", "BTCUSDT", "ADABTC", "ADAUSDT"),
        ("USDT", "ETH", "SOL", "ETHUSDT", "SOLETH", "SOLUSDT"),
    ]

    def __init__(
        self,
        tick_interval_ms: int = 100,
        opportunity_frequency: float = 0.03,
        min_profit_threshold: float = 0.0001,
        fee_rate: float = 0.001,
        simulated_balance: float = 10000.0,
    ) -> None:
        """
        Initialize simulation engine.

        Args:
            tick_interval_ms: Price update interval.
            opportunity_frequency: How often to create opportunities.
            min_profit_threshold: Minimum profit to report.
            fee_rate: Simulated fee rate.
            simulated_balance: Starting balance for simulation.
        """
        self._tick_interval_ms = tick_interval_ms
        self._min_profit_threshold = min_profit_threshold
        self._fee_rate = fee_rate
        self._simulated_balance = simulated_balance

        # Components
        self._simulator = MarketSimulator(
            tick_interval_ms=tick_interval_ms,
            opportunity_frequency=opportunity_frequency,
        )
        self._orderbook = OrderbookManager()
        self._calculator = ArbitrageCalculator(fee_rate=fee_rate)
        self._metrics = MetricsCollector()

        # Build triangles
        self._triangles = self._build_triangles()

        # Detector
        self._detector = OpportunityDetector(
            calculator=self._calculator,
            orderbook=self._orderbook,
            triangles=self._triangles,
            min_profit_threshold=min_profit_threshold,
        )

        # State
        self._running = False
        self._stats = SimulationStats()
        self._event_callbacks: list[Callable[[dict[str, Any]], Coroutine[Any, Any, None]]] = []

    def _build_triangles(self) -> list[TrianglePath]:
        """Build triangle paths from configuration."""
        triangles = []
        simulator_symbols = set(self._simulator.get_symbols())

        for base, mid1, mid2, sym1, sym2, sym3 in self.DEMO_TRIANGLES:
            # Check if all symbols are available
            if not all(s in simulator_symbols for s in [sym1, sym2, sym3]):
                continue

            triangle = TrianglePath(
                id=f"{base}-{mid1}-{mid2}",
                base_asset=base,
                legs=(
                    TriangleLeg(sym1, OrderSide.BUY, base, mid1),
                    TriangleLeg(sym2, OrderSide.BUY, mid1, mid2),
                    TriangleLeg(sym3, OrderSide.SELL, mid2, base),
                ),
            )
            triangles.append(triangle)

        return triangles

    def add_event_callback(
        self,
        callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """Add callback for simulation events (for dashboard)."""
        self._event_callbacks.append(callback)

    async def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit event to all callbacks."""
        event = {
            "type": event_type,
            "timestamp": get_timestamp_us(),
            "data": data,
        }
        for callback in self._event_callbacks:
            try:
                await callback(event)
            except Exception as e:
                logger.debug(f"Event callback error: {e}")

    async def _on_price_update(self, bbo: BBO) -> None:
        """Handle price update from simulator."""
        start_time = get_timestamp_us()

        # Update orderbook
        self._orderbook.update(bbo)
        self._stats.ticks_processed += 1

        # Emit price event
        await self._emit_event(
            "price",
            {
                "symbol": bbo.symbol,
                "bid": bbo.bid_price,
                "ask": bbo.ask_price,
                "spread_pct": bbo.spread_pct * 100,
            },
        )

        # Check for opportunities
        opportunities = self._detector.on_price_update(bbo)

        # Record latency
        latency = get_timestamp_us() - start_time
        self._metrics.record_latency("tick_to_calc", latency)

        # Process opportunities
        for opp in opportunities:
            self._stats.opportunities_found += 1
            self._metrics.record_opportunity(opp.profit_pct)

            if opp.profit_pct > self._stats.best_opportunity_pct:
                self._stats.best_opportunity_pct = opp.profit_pct

            if opp.is_profitable:
                self._stats.opportunities_profitable += 1
                await self._simulate_execution(opp)

    async def _simulate_execution(self, opportunity: Opportunity) -> None:
        """Simulate executing an opportunity."""
        # Calculate simulated trade size
        max_size = min(
            opportunity.max_trade_qty,
            self._simulated_balance * 0.1,  # Max 10% per trade
        )

        if max_size < 10:  # Minimum $10 trade
            return

        # Simulate execution
        self._stats.simulated_executions += 1
        simulated_profit = max_size * (opportunity.net_return - 1)
        self._stats.total_simulated_profit += simulated_profit
        self._simulated_balance += simulated_profit

        self._metrics.record_execution(
            success=True,
            profit=simulated_profit,
            commission=max_size * self._fee_rate * 3,
        )

        # Emit execution event
        await self._emit_event(
            "execution",
            {
                "triangle": opportunity.path.id,
                "profit_pct": opportunity.profit_pct,
                "profit_usd": simulated_profit,
                "size": max_size,
                "prices": opportunity.prices,
            },
        )

        logger.info(
            f"Simulated execution: {opportunity.path.id} "
            f"profit={simulated_profit:.4f} USDT ({opportunity.profit_pct:.4f}%)"
        )

    async def run(self) -> None:
        """Run the simulation."""
        self._running = True
        logger.info(f"Starting simulation with {len(self._triangles)} triangles")

        # Register price callback
        self._simulator.add_callback(self._on_price_update)

        # Start simulator
        sim_task = await self._simulator.start()

        # Emit status events periodically
        while self._running:
            await self._emit_event(
                "status",
                {
                    "ticks": self._stats.ticks_processed,
                    "opportunities_found": self._stats.opportunities_found,
                    "opportunities_profitable": self._stats.opportunities_profitable,
                    "executions": self._stats.simulated_executions,
                    "total_profit": self._stats.total_simulated_profit,
                    "balance": self._simulated_balance,
                    "best_profit_pct": self._stats.best_opportunity_pct,
                    "triangles": len(self._triangles),
                    "symbols": len(self._simulator.get_symbols()),
                },
            )
            await asyncio.sleep(1)

        sim_task.cancel()

    def stop(self) -> None:
        """Stop the simulation."""
        self._running = False
        self._simulator.stop()

    @property
    def stats(self) -> SimulationStats:
        """Get simulation statistics."""
        return self._stats

    @property
    def metrics(self) -> MetricsCollector:
        """Get metrics collector."""
        return self._metrics

    @property
    def triangles(self) -> list[TrianglePath]:
        """Get configured triangles."""
        return self._triangles

    @property
    def orderbook(self) -> OrderbookManager:
        """Get orderbook manager."""
        return self._orderbook

    @property
    def balance(self) -> float:
        """Get current simulated balance."""
        return self._simulated_balance
