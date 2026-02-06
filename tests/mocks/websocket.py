"""
Mock WebSocket for testing.

Provides a controllable WebSocket mock for testing
market data handling without network connections.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from arbitrage.core.types import BookTickerData
from arbitrage.utils.time import get_timestamp_us


class MockWebSocket:
    """
    Mock WebSocket for testing.

    Allows injecting market data updates programmatically.
    """

    def __init__(self) -> None:
        """Initialize mock WebSocket."""
        self._handlers: list[Callable[[dict[str, Any]], Coroutine[Any, Any, None]]] = []
        self._running = False
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def add_handler(self, handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]) -> None:
        """Add a message handler."""
        self._handlers.append(handler)

    def remove_handler(
        self, handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """Remove a message handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    async def inject_message(self, data: dict[str, Any]) -> None:
        """
        Inject a message to be processed by handlers.

        Args:
            data: Message data to inject.
        """
        for handler in self._handlers:
            await handler(data)

    async def inject_book_ticker(
        self,
        symbol: str,
        bid_price: float,
        bid_qty: float,
        ask_price: float,
        ask_qty: float,
    ) -> None:
        """
        Inject a bookTicker update.

        Args:
            symbol: Trading symbol.
            bid_price: Best bid price.
            bid_qty: Best bid quantity.
            ask_price: Best ask price.
            ask_qty: Best ask quantity.
        """
        data: BookTickerData = {
            "s": symbol,
            "b": str(bid_price),
            "B": str(bid_qty),
            "a": str(ask_price),
            "A": str(ask_qty),
            "u": get_timestamp_us() // 1000,
        }
        await self.inject_message(data)

    async def inject_triangle_prices(
        self,
        btcusdt_bid: float = 50000.0,
        btcusdt_ask: float = 50010.0,
        ethusdt_bid: float = 3000.0,
        ethusdt_ask: float = 3001.0,
        ethbtc_bid: float = 0.06,
        ethbtc_ask: float = 0.060012,
    ) -> None:
        """
        Inject a complete set of triangle prices.

        Useful for setting up test scenarios.
        """
        await self.inject_book_ticker("BTCUSDT", btcusdt_bid, 1.0, btcusdt_ask, 1.0)
        await self.inject_book_ticker("ETHUSDT", ethusdt_bid, 10.0, ethusdt_ask, 10.0)
        await self.inject_book_ticker("ETHBTC", ethbtc_bid, 50.0, ethbtc_ask, 50.0)

    async def inject_profitable_opportunity(self) -> None:
        """
        Inject prices that create a profitable arbitrage opportunity.

        Sets up prices with a ~0.1% profit opportunity.
        """
        # These prices create a small profit opportunity
        # USDT -> BTC: buy at 50000
        # BTC -> ETH: buy at 0.059 (getting more ETH per BTC)
        # ETH -> USDT: sell at 3000
        # Return: (1/50000) * (1/0.059) * 3000 = 1.0169 (1.69% gross)
        await self.inject_book_ticker("BTCUSDT", 49990.0, 1.0, 50000.0, 1.0)
        await self.inject_book_ticker("ETHBTC", 0.0589, 50.0, 0.059, 50.0)
        await self.inject_book_ticker("ETHUSDT", 3000.0, 10.0, 3001.0, 10.0)

    async def inject_unprofitable_opportunity(self) -> None:
        """
        Inject prices that create an unprofitable scenario.

        Sets up prices with negative return.
        """
        await self.inject_book_ticker("BTCUSDT", 49990.0, 1.0, 50000.0, 1.0)
        await self.inject_book_ticker("ETHBTC", 0.0609, 50.0, 0.061, 50.0)
        await self.inject_book_ticker("ETHUSDT", 2990.0, 10.0, 2991.0, 10.0)

    def subscribe_book_tickers(self, symbols: list[str]) -> None:
        """Mock subscribe (no-op for testing)."""
        pass

    async def start(self) -> None:
        """Mock start."""
        self._running = True

    async def stop(self) -> None:
        """Mock stop."""
        self._running = False

    async def wait_connected(self, timeout: float = 30.0) -> bool:
        """Mock wait_connected - always returns True."""
        return True

    @property
    def is_running(self) -> bool:
        """Check if mock is running."""
        return self._running

    @property
    def connection_count(self) -> int:
        """Mock connection count."""
        return 1

    def all_connected(self) -> bool:
        """Mock all_connected."""
        return self._running


class MockWebSocketServer:
    """
    Mock WebSocket server for integration testing.

    Simulates a server that can send messages at controlled intervals.
    """

    def __init__(self, client: MockWebSocket) -> None:
        """Initialize mock server."""
        self._client = client
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start_price_feed(
        self,
        interval_ms: int = 100,
        symbols: list[str] | None = None,
    ) -> None:
        """
        Start sending price updates at regular intervals.

        Args:
            interval_ms: Interval between updates.
            symbols: Symbols to update.
        """
        symbols = symbols or ["BTCUSDT", "ETHUSDT", "ETHBTC"]
        self._running = True

        async def feed_loop() -> None:
            base_prices = {
                "BTCUSDT": 50000.0,
                "ETHUSDT": 3000.0,
                "ETHBTC": 0.06,
            }

            while self._running:
                for symbol in symbols:
                    base = base_prices.get(symbol, 100.0)
                    # Add small random variation
                    import random

                    variation = random.uniform(-0.001, 0.001)
                    bid = base * (1 + variation)
                    ask = bid * 1.0002  # 0.02% spread

                    await self._client.inject_book_ticker(
                        symbol=symbol,
                        bid_price=bid,
                        bid_qty=random.uniform(0.5, 5.0),
                        ask_price=ask,
                        ask_qty=random.uniform(0.5, 5.0),
                    )

                await asyncio.sleep(interval_ms / 1000)

        self._task = asyncio.create_task(feed_loop())

    async def stop(self) -> None:
        """Stop the price feed."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
