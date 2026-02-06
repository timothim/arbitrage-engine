"""
Symbol management and filtering.

Handles loading, filtering, and managing trading symbol metadata
from the exchange.
"""

from collections.abc import Iterable

from arbitrage.config.constants import (
    EXCLUDED_SYMBOLS,
    SUPPORTED_QUOTE_ASSETS,
)
from arbitrage.core.types import SymbolInfo
from arbitrage.exchange.models import ExchangeInfo, SymbolData


class SymbolManager:
    """
    Manages trading symbol metadata.

    Responsibilities:
    - Loading symbol info from exchange
    - Filtering by trading status, volume, quote asset
    - Providing quick lookups for trading operations
    """

    __slots__ = ("_symbols", "_by_base", "_by_quote", "_pairs")

    def __init__(self) -> None:
        """Initialize empty symbol manager."""
        self._symbols: dict[str, SymbolInfo] = {}
        self._by_base: dict[str, list[str]] = {}
        self._by_quote: dict[str, list[str]] = {}
        self._pairs: set[tuple[str, str]] = set()

    def load_from_exchange_info(
        self,
        exchange_info: ExchangeInfo,
        quote_assets: Iterable[str] | None = None,
    ) -> int:
        """
        Load and filter symbols from exchange info.

        Args:
            exchange_info: Exchange info response.
            quote_assets: Quote assets to include (default: SUPPORTED_QUOTE_ASSETS).

        Returns:
            Number of symbols loaded.
        """
        quote_assets_set = set(quote_assets) if quote_assets else SUPPORTED_QUOTE_ASSETS

        for symbol_data in exchange_info.symbols:
            # Skip non-trading symbols
            if symbol_data.status != "TRADING":
                continue

            # Skip excluded symbols
            if symbol_data.symbol in EXCLUDED_SYMBOLS:
                continue

            # Filter by quote asset
            if symbol_data.quote_asset not in quote_assets_set:
                continue

            # Convert to internal format
            symbol_info = self._convert_symbol_data(symbol_data)
            if symbol_info:
                self._add_symbol(symbol_info)

        return len(self._symbols)

    def _convert_symbol_data(self, data: SymbolData) -> SymbolInfo | None:
        """
        Convert exchange symbol data to internal SymbolInfo.

        Args:
            data: Raw symbol data from exchange.

        Returns:
            SymbolInfo or None if invalid.
        """
        # Get filters
        price_filter = data.get_filter("PRICE_FILTER")
        lot_filter = data.get_filter("LOT_SIZE")
        notional_filter = data.get_filter("NOTIONAL") or data.get_filter("MIN_NOTIONAL")

        # Extract values with defaults
        tick_size = (
            float(price_filter.tick_size) if price_filter and price_filter.tick_size else 0.00000001
        )
        step_size = (
            float(lot_filter.step_size) if lot_filter and lot_filter.step_size else 0.00000001
        )
        min_qty = float(lot_filter.min_qty) if lot_filter and lot_filter.min_qty else 0.0
        max_qty = float(lot_filter.max_qty) if lot_filter and lot_filter.max_qty else float("inf")
        min_notional = (
            float(notional_filter.min_notional)
            if notional_filter and notional_filter.min_notional
            else 0.0
        )

        # Calculate precision from step sizes
        price_precision = self._precision_from_step(tick_size)
        quantity_precision = self._precision_from_step(step_size)

        return SymbolInfo(
            symbol=data.symbol,
            base_asset=data.base_asset,
            quote_asset=data.quote_asset,
            price_precision=price_precision,
            quantity_precision=quantity_precision,
            min_notional=min_notional,
            min_qty=min_qty,
            max_qty=max_qty,
            step_size=step_size,
            tick_size=tick_size,
            status=data.status,
        )

    @staticmethod
    def _precision_from_step(step: float) -> int:
        """Calculate decimal precision from step size."""
        if step >= 1:
            return 0
        precision = 0
        while step < 1 and precision < 10:
            step *= 10
            precision += 1
        return precision

    def _add_symbol(self, info: SymbolInfo) -> None:
        """Add symbol to internal indexes."""
        self._symbols[info.symbol] = info

        # Index by base asset
        if info.base_asset not in self._by_base:
            self._by_base[info.base_asset] = []
        self._by_base[info.base_asset].append(info.symbol)

        # Index by quote asset
        if info.quote_asset not in self._by_quote:
            self._by_quote[info.quote_asset] = []
        self._by_quote[info.quote_asset].append(info.symbol)

        # Store pair
        self._pairs.add((info.base_asset, info.quote_asset))

    def get(self, symbol: str) -> SymbolInfo | None:
        """
        Get symbol info by symbol name.

        Args:
            symbol: Trading symbol (e.g., "BTCUSDT").

        Returns:
            SymbolInfo or None.
        """
        return self._symbols.get(symbol)

    def get_all(self) -> dict[str, SymbolInfo]:
        """Get all symbols."""
        return dict(self._symbols)

    def get_symbols_by_base(self, base_asset: str) -> list[str]:
        """
        Get all symbols with a given base asset.

        Args:
            base_asset: Base asset (e.g., "BTC").

        Returns:
            List of symbol names.
        """
        return self._by_base.get(base_asset, [])

    def get_symbols_by_quote(self, quote_asset: str) -> list[str]:
        """
        Get all symbols with a given quote asset.

        Args:
            quote_asset: Quote asset (e.g., "USDT").

        Returns:
            List of symbol names.
        """
        return self._by_quote.get(quote_asset, [])

    def find_symbol(self, base: str, quote: str) -> str | None:
        """
        Find symbol name for a base/quote pair.

        Args:
            base: Base asset.
            quote: Quote asset.

        Returns:
            Symbol name or None.
        """
        symbol = f"{base}{quote}"
        return symbol if symbol in self._symbols else None

    def has_pair(self, base: str, quote: str) -> bool:
        """
        Check if a trading pair exists.

        Args:
            base: Base asset.
            quote: Quote asset.

        Returns:
            True if pair exists.
        """
        return (base, quote) in self._pairs

    def get_all_bases(self) -> set[str]:
        """Get all base assets."""
        return set(self._by_base.keys())

    def get_all_quotes(self) -> set[str]:
        """Get all quote assets."""
        return set(self._by_quote.keys())

    def get_tradeable_symbols(self) -> list[str]:
        """Get all tradeable symbol names."""
        return list(self._symbols.keys())

    @property
    def count(self) -> int:
        """Get number of loaded symbols."""
        return len(self._symbols)

    def __contains__(self, symbol: str) -> bool:
        """Check if symbol exists."""
        return symbol in self._symbols

    def __len__(self) -> int:
        """Get number of symbols."""
        return len(self._symbols)
