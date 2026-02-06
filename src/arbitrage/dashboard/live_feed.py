"""
Real-time Binance market data feed using public WebSocket.

No API keys required - uses public bookTicker stream.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import orjson

from arbitrage.core.types import BBO, OrderSide, TriangleLeg, TrianglePath
from arbitrage.market.orderbook import OrderbookManager
from arbitrage.strategy.calculator import ArbitrageCalculator
from arbitrage.utils.time import get_timestamp_us


logger = logging.getLogger(__name__)

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

# Top liquid triangles for demo
TRIANGLES_CONFIG = [
    ("USDT", "BTC", "ETH", "BTCUSDT", "ETHBTC", "ETHUSDT"),
    ("USDT", "BTC", "BNB", "BTCUSDT", "BNBBTC", "BNBUSDT"),
    ("USDT", "BTC", "SOL", "BTCUSDT", "SOLBTC", "SOLUSDT"),
    ("USDT", "BTC", "XRP", "BTCUSDT", "XRPBTC", "XRPUSDT"),
    ("USDT", "ETH", "BNB", "ETHUSDT", "BNBETH", "BNBUSDT"),
    ("USDT", "BTC", "DOGE", "BTCUSDT", "DOGEBTC", "DOGEUSDT"),
    ("USDT", "BTC", "ADA", "BTCUSDT", "ADABTC", "ADAUSDT"),
    ("USDT", "BTC", "AVAX", "BTCUSDT", "AVAXBTC", "AVAXUSDT"),
    ("USDT", "BTC", "LINK", "BTCUSDT", "LINKBTC", "LINKUSDT"),
    ("USDT", "BTC", "DOT", "BTCUSDT", "DOTBTC", "DOTUSDT"),
]


@dataclass
class OpportunityEvent:
    """Detected arbitrage opportunity."""

    triangle_id: str
    profit_pct: float
    prices: dict[str, float]
    timestamp: int
    legs: list[dict[str, Any]]


@dataclass
class LiveFeedState:
    """Current state of the live feed."""

    running: bool = False
    connected: bool = False
    ticks_received: int = 0
    opportunities_detected: int = 0
    last_opportunity: OpportunityEvent | None = None
    prices: dict[str, dict[str, float]] = field(default_factory=dict)


class LiveDataFeed:
    """
    Connects to Binance public WebSocket for real-time market data.
    Detects arbitrage opportunities in real-time.
    """

    def __init__(self, fee_rate: float = 0.001, min_profit_threshold: float = 0.0) -> None:
        self._fee_rate = fee_rate
        self._min_profit_threshold = min_profit_threshold

        self._orderbook = OrderbookManager()
        self._calculator = ArbitrageCalculator(fee_rate=fee_rate)
        self._triangles = self._build_triangles()

        self._state = LiveFeedState()
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._task: asyncio.Task[None] | None = None

        self._event_callbacks: list[Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]] = []

    def _build_triangles(self) -> list[TrianglePath]:
        """Build triangle paths."""
        triangles = []
        for base, mid1, mid2, sym1, sym2, sym3 in TRIANGLES_CONFIG:
            triangle = TrianglePath(
                id=f"{base}→{mid1}→{mid2}",
                base_asset=base,
                legs=(
                    TriangleLeg(sym1, OrderSide.BUY, base, mid1),
                    TriangleLeg(sym2, OrderSide.BUY, mid1, mid2),
                    TriangleLeg(sym3, OrderSide.SELL, mid2, base),
                ),
            )
            triangles.append(triangle)
        return triangles

    def _get_all_symbols(self) -> set[str]:
        """Get all symbols needed for triangles."""
        symbols = set()
        for triangle in self._triangles:
            for leg in triangle.legs:
                symbols.add(leg.symbol)
        return symbols

    def add_event_callback(
        self,
        callback: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """Add callback for events."""
        self._event_callbacks.append(callback)

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit event to all callbacks."""
        for callback in self._event_callbacks:
            try:
                await callback(event_type, data)
            except Exception as e:
                logger.debug(f"Callback error: {e}")

    async def start(self) -> None:
        """Start the live feed."""
        if self._state.running:
            return

        self._state.running = True
        self._task = asyncio.create_task(self._run())
        logger.info("Live feed started")

    async def stop(self) -> None:
        """Stop the live feed."""
        self._state.running = False

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._session:
            await self._session.close()
            self._session = None

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self._state.connected = False
        logger.info("Live feed stopped")

    async def _run(self) -> None:
        """Main loop - connect and process messages."""
        symbols = self._get_all_symbols()
        streams = [f"{s.lower()}@bookTicker" for s in symbols]
        combined_url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"

        while self._state.running:
            try:
                await self._connect_and_listen(combined_url)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self._state.connected = False
                await self._emit("connection", {"connected": False, "error": str(e)})

                if self._state.running:
                    await asyncio.sleep(3)  # Reconnect delay

    async def _connect_and_listen(self, url: str) -> None:
        """Connect to WebSocket and process messages."""
        self._session = aiohttp.ClientSession()

        try:
            async with self._session.ws_connect(url, heartbeat=30) as ws:
                self._ws = ws
                self._state.connected = True
                logger.info("Connected to Binance WebSocket")
                await self._emit("connection", {"connected": True})

                async for msg in ws:
                    if not self._state.running:
                        break

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(msg.data)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"WebSocket error: {ws.exception()}")
                        break

        finally:
            self._state.connected = False
            if self._session:
                await self._session.close()
                self._session = None

    async def _handle_message(self, data: str) -> None:
        """Process incoming WebSocket message."""
        try:
            msg = orjson.loads(data)

            # Combined stream format: {"stream": "...", "data": {...}}
            if "data" in msg:
                ticker = msg["data"]
            else:
                ticker = msg

            symbol = ticker.get("s")
            if not symbol:
                return

            bid_price = float(ticker.get("b", 0))
            ask_price = float(ticker.get("a", 0))
            bid_qty = float(ticker.get("B", 0))
            ask_qty = float(ticker.get("A", 0))

            if bid_price <= 0 or ask_price <= 0:
                return

            # Create BBO
            bbo = BBO(
                symbol=symbol,
                bid_price=bid_price,
                bid_qty=bid_qty,
                ask_price=ask_price,
                ask_qty=ask_qty,
                update_id=int(ticker.get("u", 0)),
                timestamp_us=get_timestamp_us(),
            )

            # Update orderbook
            self._orderbook.update(bbo)
            self._state.ticks_received += 1

            # Store price
            spread_pct = ((ask_price - bid_price) / bid_price) * 100
            self._state.prices[symbol] = {
                "bid": bid_price,
                "ask": ask_price,
                "spread": spread_pct,
            }

            # Emit price update
            await self._emit(
                "price",
                {
                    "symbol": symbol,
                    "bid": bid_price,
                    "ask": ask_price,
                    "spread": spread_pct,
                },
            )

            # Check triangles that use this symbol
            await self._check_opportunities(symbol)

        except Exception as e:
            logger.debug(f"Message handling error: {e}")

    async def _check_opportunities(self, updated_symbol: str) -> None:
        """Check for arbitrage opportunities."""
        for triangle in self._triangles:
            if updated_symbol not in triangle.symbols:
                continue

            # Get all prices for this triangle
            prices = {}
            complete = True

            for leg in triangle.legs:
                bbo = self._orderbook.get(leg.symbol)
                if not bbo:
                    complete = False
                    break

                if leg.side == OrderSide.BUY:
                    prices[leg.symbol] = bbo.ask_price
                else:
                    prices[leg.symbol] = bbo.bid_price

            if not complete:
                continue

            # Calculate profit
            result = self._calculator.calculate_opportunity(triangle, self._orderbook)
            if result is None:
                continue

            profit_pct = (result.net_return - 1) * 100

            # Emit opportunity if above threshold (show all for visibility)
            if profit_pct > self._min_profit_threshold:
                self._state.opportunities_detected += 1

                opp = OpportunityEvent(
                    triangle_id=triangle.id,
                    profit_pct=profit_pct,
                    prices=prices,
                    timestamp=get_timestamp_us(),
                    legs=[
                        {
                            "symbol": leg.symbol,
                            "side": leg.side.value,
                            "price": prices[leg.symbol],
                        }
                        for leg in triangle.legs
                    ],
                )
                self._state.last_opportunity = opp

                await self._emit(
                    "opportunity",
                    {
                        "triangle": triangle.id,
                        "profit_pct": profit_pct,
                        "profitable": profit_pct > 0,
                        "prices": prices,
                        "legs": opp.legs,
                        "timestamp": opp.timestamp,
                    },
                )

    @property
    def state(self) -> LiveFeedState:
        """Get current state."""
        return self._state

    @property
    def triangles(self) -> list[TrianglePath]:
        """Get configured triangles."""
        return self._triangles

    @property
    def orderbook(self) -> OrderbookManager:
        """Get orderbook manager."""
        return self._orderbook
