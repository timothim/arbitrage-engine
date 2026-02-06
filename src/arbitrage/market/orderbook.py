"""
Order book management with O(1) BBO access.

Maintains a real-time cache of best bid/offer data for all
subscribed symbols, optimized for ultra-fast lookups.
"""

from collections.abc import Callable
from typing import Any

from arbitrage.core.types import BBO, BookTickerData
from arbitrage.utils.time import get_timestamp_us


# Type alias for update callbacks
UpdateCallback = Callable[[BBO], None]


class OrderbookManager:
    """
    Manages order book data with O(1) access time.

    Features:
    - Dict-based storage for instant symbol lookup
    - Thread-safe for async operations
    - Callback support for downstream processing
    - Memory-efficient with frozen BBO dataclasses
    """

    __slots__ = ("_cache", "_callbacks", "_update_count")

    def __init__(self) -> None:
        """Initialize empty orderbook cache."""
        self._cache: dict[str, BBO] = {}
        self._callbacks: list[UpdateCallback] = []
        self._update_count: int = 0

    def register_callback(self, callback: UpdateCallback) -> None:
        """
        Register a callback for BBO updates.

        Args:
            callback: Function to call with new BBO data.
        """
        self._callbacks.append(callback)

    def unregister_callback(self, callback: UpdateCallback) -> None:
        """
        Unregister a callback.

        Args:
            callback: Previously registered callback.
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def update_from_ticker(self, data: BookTickerData) -> BBO:
        """
        Update cache from WebSocket bookTicker message.

        Args:
            data: Raw bookTicker data from WebSocket.

        Returns:
            The created/updated BBO object.
        """
        bbo = BBO(
            symbol=data["s"],
            bid_price=float(data["b"]),
            bid_qty=float(data["B"]),
            ask_price=float(data["a"]),
            ask_qty=float(data["A"]),
            update_id=data["u"],
            timestamp_us=get_timestamp_us(),
        )

        self._cache[bbo.symbol] = bbo
        self._update_count += 1

        # Notify callbacks
        for callback in self._callbacks:
            callback(bbo)

        return bbo

    def update(self, bbo: BBO) -> None:
        """
        Update cache with a BBO object.

        Args:
            bbo: BBO data to store.
        """
        self._cache[bbo.symbol] = bbo
        self._update_count += 1

        # Notify callbacks
        for callback in self._callbacks:
            callback(bbo)

    def get(self, symbol: str) -> BBO | None:
        """
        Get BBO for a symbol.

        O(1) lookup time.

        Args:
            symbol: Trading symbol.

        Returns:
            BBO data or None if not found.
        """
        return self._cache.get(symbol)

    def get_many(self, symbols: list[str]) -> dict[str, BBO]:
        """
        Get BBO for multiple symbols.

        Args:
            symbols: List of trading symbols.

        Returns:
            Dict of symbol -> BBO for found symbols.
        """
        return {s: self._cache[s] for s in symbols if s in self._cache}

    def get_all(self) -> dict[str, BBO]:
        """
        Get all cached BBO data.

        Returns:
            Copy of the internal cache.
        """
        return dict(self._cache)

    def get_symbols(self) -> frozenset[str]:
        """
        Get all cached symbols.

        Returns:
            Frozen set of symbol names.
        """
        return frozenset(self._cache.keys())

    def has_symbol(self, symbol: str) -> bool:
        """
        Check if a symbol is in the cache.

        Args:
            symbol: Symbol to check.

        Returns:
            True if symbol has BBO data.
        """
        return symbol in self._cache

    def has_all_symbols(self, symbols: frozenset[str]) -> bool:
        """
        Check if all specified symbols are cached.

        Args:
            symbols: Set of symbols to check.

        Returns:
            True if all symbols have BBO data.
        """
        return symbols.issubset(self._cache.keys())

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()

    def remove(self, symbol: str) -> None:
        """
        Remove a symbol from the cache.

        Args:
            symbol: Symbol to remove.
        """
        self._cache.pop(symbol, None)

    @property
    def size(self) -> int:
        """Get number of cached symbols."""
        return len(self._cache)

    @property
    def update_count(self) -> int:
        """Get total number of updates received."""
        return self._update_count

    def get_prices_for_triangle(
        self,
        symbols: tuple[str, str, str],
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None:
        """
        Get bid/ask prices for a triangle's symbols.

        Optimized for the hot path - minimal overhead.

        Args:
            symbols: Tuple of three symbol names.

        Returns:
            Tuple of ((bid, ask), (bid, ask), (bid, ask)) or None if any missing.
        """
        cache = self._cache  # Local reference for speed

        bbo1 = cache.get(symbols[0])
        if bbo1 is None:
            return None

        bbo2 = cache.get(symbols[1])
        if bbo2 is None:
            return None

        bbo3 = cache.get(symbols[2])
        if bbo3 is None:
            return None

        return (
            (bbo1.bid_price, bbo1.ask_price),
            (bbo2.bid_price, bbo2.ask_price),
            (bbo3.bid_price, bbo3.ask_price),
        )

    def get_quantities_for_triangle(
        self,
        symbols: tuple[str, str, str],
    ) -> tuple[float, float, float] | None:
        """
        Get available quantities for a triangle's symbols.

        Args:
            symbols: Tuple of three symbol names.

        Returns:
            Tuple of quantities or None if any missing.
        """
        cache = self._cache

        bbo1 = cache.get(symbols[0])
        if bbo1 is None:
            return None

        bbo2 = cache.get(symbols[1])
        if bbo2 is None:
            return None

        bbo3 = cache.get(symbols[2])
        if bbo3 is None:
            return None

        # Return quantities based on expected order flow
        # Leg 1: Buy (use ask qty), Leg 2: Buy (use ask qty), Leg 3: Sell (use bid qty)
        return (bbo1.ask_qty, bbo2.ask_qty, bbo3.bid_qty)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """
        Convert cache to serializable dict.

        Returns:
            Dict representation of all BBO data.
        """
        return {
            symbol: {
                "bid_price": bbo.bid_price,
                "bid_qty": bbo.bid_qty,
                "ask_price": bbo.ask_price,
                "ask_qty": bbo.ask_qty,
                "update_id": bbo.update_id,
                "timestamp_us": bbo.timestamp_us,
            }
            for symbol, bbo in self._cache.items()
        }
