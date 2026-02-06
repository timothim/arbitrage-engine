"""
Pytest configuration and shared fixtures.

Provides reusable test fixtures for all test modules.
"""

import asyncio
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from arbitrage.core.types import BBO, OrderSide, SymbolInfo, TriangleLeg, TrianglePath
from arbitrage.market.orderbook import OrderbookManager
from arbitrage.market.symbols import SymbolManager
from arbitrage.strategy.calculator import ArbitrageCalculator
from arbitrage.utils.time import get_timestamp_us


# =============================================================================
# Event Loop Configuration
# =============================================================================


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Symbol Fixtures
# =============================================================================


@pytest.fixture
def symbol_info_btcusdt() -> SymbolInfo:
    """BTC/USDT symbol info."""
    return SymbolInfo(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        price_precision=2,
        quantity_precision=6,
        min_notional=10.0,
        min_qty=0.00001,
        max_qty=9000.0,
        step_size=0.00001,
        tick_size=0.01,
    )


@pytest.fixture
def symbol_info_ethusdt() -> SymbolInfo:
    """ETH/USDT symbol info."""
    return SymbolInfo(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        price_precision=2,
        quantity_precision=5,
        min_notional=10.0,
        min_qty=0.0001,
        max_qty=9000.0,
        step_size=0.0001,
        tick_size=0.01,
    )


@pytest.fixture
def symbol_info_ethbtc() -> SymbolInfo:
    """ETH/BTC symbol info."""
    return SymbolInfo(
        symbol="ETHBTC",
        base_asset="ETH",
        quote_asset="BTC",
        price_precision=6,
        quantity_precision=5,
        min_notional=0.0001,
        min_qty=0.0001,
        max_qty=9000.0,
        step_size=0.0001,
        tick_size=0.000001,
    )


# =============================================================================
# BBO Fixtures
# =============================================================================


@pytest.fixture
def bbo_btcusdt() -> BBO:
    """BTC/USDT BBO data."""
    return BBO(
        symbol="BTCUSDT",
        bid_price=50000.0,
        bid_qty=1.5,
        ask_price=50010.0,
        ask_qty=1.2,
        update_id=12345,
        timestamp_us=get_timestamp_us(),
    )


@pytest.fixture
def bbo_ethusdt() -> BBO:
    """ETH/USDT BBO data."""
    return BBO(
        symbol="ETHUSDT",
        bid_price=3000.0,
        bid_qty=10.0,
        ask_price=3001.0,
        ask_qty=8.0,
        update_id=12346,
        timestamp_us=get_timestamp_us(),
    )


@pytest.fixture
def bbo_ethbtc() -> BBO:
    """ETH/BTC BBO data."""
    return BBO(
        symbol="ETHBTC",
        bid_price=0.06,
        bid_qty=50.0,
        ask_price=0.060012,
        ask_qty=45.0,
        update_id=12347,
        timestamp_us=get_timestamp_us(),
    )


# =============================================================================
# Triangle Fixtures
# =============================================================================


@pytest.fixture
def triangle_usdt_btc_eth() -> TrianglePath:
    """USDT -> BTC -> ETH -> USDT triangle."""
    return TrianglePath(
        id="USDT-BTC-ETH",
        base_asset="USDT",
        legs=(
            TriangleLeg(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                from_asset="USDT",
                to_asset="BTC",
            ),
            TriangleLeg(
                symbol="ETHBTC",
                side=OrderSide.BUY,
                from_asset="BTC",
                to_asset="ETH",
            ),
            TriangleLeg(
                symbol="ETHUSDT",
                side=OrderSide.SELL,
                from_asset="ETH",
                to_asset="USDT",
            ),
        ),
    )


# =============================================================================
# Manager Fixtures
# =============================================================================


@pytest.fixture
def orderbook_manager() -> OrderbookManager:
    """Empty orderbook manager."""
    return OrderbookManager()


@pytest.fixture
def orderbook_manager_populated(
    orderbook_manager: OrderbookManager,
    bbo_btcusdt: BBO,
    bbo_ethusdt: BBO,
    bbo_ethbtc: BBO,
) -> OrderbookManager:
    """Orderbook manager with sample data."""
    orderbook_manager.update(bbo_btcusdt)
    orderbook_manager.update(bbo_ethusdt)
    orderbook_manager.update(bbo_ethbtc)
    return orderbook_manager


@pytest.fixture
def symbol_manager(
    symbol_info_btcusdt: SymbolInfo,
    symbol_info_ethusdt: SymbolInfo,
    symbol_info_ethbtc: SymbolInfo,
) -> SymbolManager:
    """Symbol manager with sample data."""
    manager = SymbolManager()
    manager._add_symbol(symbol_info_btcusdt)
    manager._add_symbol(symbol_info_ethusdt)
    manager._add_symbol(symbol_info_ethbtc)
    return manager


@pytest.fixture
def calculator() -> ArbitrageCalculator:
    """Arbitrage calculator with default settings."""
    return ArbitrageCalculator(fee_rate=0.001, slippage_buffer=0.0001)


# =============================================================================
# Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_binance_client() -> AsyncMock:
    """Mocked Binance client."""
    client = AsyncMock()

    # Default return values
    client.get_balance.return_value = 1000.0
    client.get_server_time.return_value = MagicMock(server_time=1704067200000)

    # Order placement
    client.place_market_order.return_value = MagicMock(
        symbol="BTCUSDT",
        order_id=12345,
        status="FILLED",
        executed_qty="0.001",
        cummulative_quote_qty="50.0",
        is_filled=True,
        executed_qty_float=0.001,
        avg_fill_price=50000.0,
        total_commission=0.05,
    )

    client.place_limit_order.return_value = MagicMock(
        symbol="BTCUSDT",
        order_id=12345,
        status="FILLED",
        executed_qty="0.001",
        cummulative_quote_qty="50.0",
        is_filled=True,
        executed_qty_float=0.001,
        avg_fill_price=50000.0,
        total_commission=0.05,
    )

    return client


@pytest.fixture
def mock_exchange_info() -> dict:
    """Mock exchange info response."""
    return {
        "timezone": "UTC",
        "serverTime": 1704067200000,
        "rateLimits": [
            {
                "rateLimitType": "REQUEST_WEIGHT",
                "interval": "MINUTE",
                "intervalNum": 1,
                "limit": 1200,
            }
        ],
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "baseAsset": "BTC",
                "baseAssetPrecision": 8,
                "quoteAsset": "USDT",
                "quoteAssetPrecision": 8,
                "quotePrecision": 8,
                "filters": [
                    {
                        "filterType": "PRICE_FILTER",
                        "minPrice": "0.01",
                        "maxPrice": "1000000.00",
                        "tickSize": "0.01",
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.00001",
                        "maxQty": "9000.00000",
                        "stepSize": "0.00001",
                    },
                    {
                        "filterType": "NOTIONAL",
                        "minNotional": "10.00000000",
                    },
                ],
                "permissions": ["SPOT"],
            },
            {
                "symbol": "ETHUSDT",
                "status": "TRADING",
                "baseAsset": "ETH",
                "baseAssetPrecision": 8,
                "quoteAsset": "USDT",
                "quoteAssetPrecision": 8,
                "quotePrecision": 8,
                "filters": [
                    {
                        "filterType": "PRICE_FILTER",
                        "tickSize": "0.01",
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.0001",
                        "maxQty": "9000.00",
                        "stepSize": "0.0001",
                    },
                ],
                "permissions": ["SPOT"],
            },
            {
                "symbol": "ETHBTC",
                "status": "TRADING",
                "baseAsset": "ETH",
                "baseAssetPrecision": 8,
                "quoteAsset": "BTC",
                "quoteAssetPrecision": 8,
                "quotePrecision": 8,
                "filters": [
                    {
                        "filterType": "PRICE_FILTER",
                        "tickSize": "0.000001",
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.0001",
                        "maxQty": "9000.00",
                        "stepSize": "0.0001",
                    },
                ],
                "permissions": ["SPOT"],
            },
        ],
    }


# =============================================================================
# Async Utilities
# =============================================================================


@pytest.fixture
def async_run():
    """Helper to run async functions in sync tests."""

    def _run(coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    return _run
