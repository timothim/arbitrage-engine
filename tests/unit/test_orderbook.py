"""
Unit tests for OrderbookManager.

Tests BBO caching, updates, and callbacks.
"""

import pytest

from arbitrage.core.types import BBO
from arbitrage.market.orderbook import OrderbookManager
from arbitrage.utils.time import get_timestamp_us


class TestOrderbookManager:
    """Tests for OrderbookManager."""

    def test_initialization(self) -> None:
        """Test empty initialization."""
        manager = OrderbookManager()

        assert manager.size == 0
        assert manager.update_count == 0

    def test_update_bbo(self, orderbook_manager: OrderbookManager, bbo_btcusdt: BBO) -> None:
        """Test updating BBO data."""
        orderbook_manager.update(bbo_btcusdt)

        assert orderbook_manager.size == 1
        assert orderbook_manager.update_count == 1
        assert orderbook_manager.has_symbol("BTCUSDT")

    def test_get_bbo(self, orderbook_manager: OrderbookManager, bbo_btcusdt: BBO) -> None:
        """Test retrieving BBO data."""
        orderbook_manager.update(bbo_btcusdt)

        result = orderbook_manager.get("BTCUSDT")

        assert result is not None
        assert result.symbol == "BTCUSDT"
        assert result.bid_price == bbo_btcusdt.bid_price
        assert result.ask_price == bbo_btcusdt.ask_price

    def test_get_nonexistent(self, orderbook_manager: OrderbookManager) -> None:
        """Test getting non-existent symbol."""
        result = orderbook_manager.get("NONEXISTENT")

        assert result is None

    def test_get_many(
        self,
        orderbook_manager: OrderbookManager,
        bbo_btcusdt: BBO,
        bbo_ethusdt: BBO,
    ) -> None:
        """Test getting multiple BBOs."""
        orderbook_manager.update(bbo_btcusdt)
        orderbook_manager.update(bbo_ethusdt)

        result = orderbook_manager.get_many(["BTCUSDT", "ETHUSDT", "NONEXISTENT"])

        assert len(result) == 2
        assert "BTCUSDT" in result
        assert "ETHUSDT" in result
        assert "NONEXISTENT" not in result

    def test_has_all_symbols(self, orderbook_manager_populated: OrderbookManager) -> None:
        """Test checking for all symbols."""
        symbols = frozenset(["BTCUSDT", "ETHUSDT", "ETHBTC"])

        assert orderbook_manager_populated.has_all_symbols(symbols)
        assert not orderbook_manager_populated.has_all_symbols(
            frozenset(["BTCUSDT", "NONEXISTENT"])
        )

    def test_callback_registration(self, orderbook_manager: OrderbookManager) -> None:
        """Test callback registration and invocation."""
        received: list[BBO] = []

        def callback(bbo: BBO) -> None:
            received.append(bbo)

        orderbook_manager.register_callback(callback)

        bbo = BBO(
            symbol="TEST",
            bid_price=100.0,
            bid_qty=1.0,
            ask_price=101.0,
            ask_qty=1.0,
            update_id=1,
            timestamp_us=get_timestamp_us(),
        )
        orderbook_manager.update(bbo)

        assert len(received) == 1
        assert received[0].symbol == "TEST"

    def test_callback_unregistration(self, orderbook_manager: OrderbookManager) -> None:
        """Test callback unregistration."""
        received: list[BBO] = []

        def callback(bbo: BBO) -> None:
            received.append(bbo)

        orderbook_manager.register_callback(callback)
        orderbook_manager.unregister_callback(callback)

        bbo = BBO(
            symbol="TEST",
            bid_price=100.0,
            bid_qty=1.0,
            ask_price=101.0,
            ask_qty=1.0,
            update_id=1,
            timestamp_us=get_timestamp_us(),
        )
        orderbook_manager.update(bbo)

        assert len(received) == 0

    def test_update_from_ticker(self, orderbook_manager: OrderbookManager) -> None:
        """Test updating from WebSocket ticker data."""
        ticker_data = {
            "s": "BTCUSDT",
            "b": "50000.00",
            "B": "1.5",
            "a": "50010.00",
            "A": "1.2",
            "u": 12345,
        }

        bbo = orderbook_manager.update_from_ticker(ticker_data)

        assert bbo.symbol == "BTCUSDT"
        assert bbo.bid_price == 50000.0
        assert bbo.ask_price == 50010.0
        assert orderbook_manager.has_symbol("BTCUSDT")

    def test_get_prices_for_triangle(self, orderbook_manager_populated: OrderbookManager) -> None:
        """Test getting prices for triangle symbols."""
        symbols = ("BTCUSDT", "ETHBTC", "ETHUSDT")

        result = orderbook_manager_populated.get_prices_for_triangle(symbols)

        assert result is not None
        assert len(result) == 3
        # Each entry should be (bid, ask) tuple
        for bid, ask in result:
            assert bid > 0
            assert ask > 0
            assert ask >= bid

    def test_get_prices_for_triangle_missing(
        self, orderbook_manager: OrderbookManager, bbo_btcusdt: BBO
    ) -> None:
        """Test getting prices when some symbols are missing."""
        orderbook_manager.update(bbo_btcusdt)
        symbols = ("BTCUSDT", "ETHBTC", "ETHUSDT")

        result = orderbook_manager.get_prices_for_triangle(symbols)

        assert result is None

    def test_get_quantities_for_triangle(
        self, orderbook_manager_populated: OrderbookManager
    ) -> None:
        """Test getting quantities for triangle."""
        symbols = ("BTCUSDT", "ETHBTC", "ETHUSDT")

        result = orderbook_manager_populated.get_quantities_for_triangle(symbols)

        assert result is not None
        assert len(result) == 3
        for qty in result:
            assert qty > 0

    def test_clear(self, orderbook_manager_populated: OrderbookManager) -> None:
        """Test clearing all data."""
        orderbook_manager_populated.clear()

        assert orderbook_manager_populated.size == 0
        assert orderbook_manager_populated.get("BTCUSDT") is None

    def test_remove(self, orderbook_manager: OrderbookManager, bbo_btcusdt: BBO) -> None:
        """Test removing a specific symbol."""
        orderbook_manager.update(bbo_btcusdt)
        orderbook_manager.remove("BTCUSDT")

        assert not orderbook_manager.has_symbol("BTCUSDT")

    def test_get_all(self, orderbook_manager_populated: OrderbookManager) -> None:
        """Test getting all data."""
        all_data = orderbook_manager_populated.get_all()

        assert len(all_data) == 3
        assert "BTCUSDT" in all_data
        assert "ETHUSDT" in all_data
        assert "ETHBTC" in all_data

    def test_get_symbols(self, orderbook_manager_populated: OrderbookManager) -> None:
        """Test getting all symbol names."""
        symbols = orderbook_manager_populated.get_symbols()

        assert isinstance(symbols, frozenset)
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols
        assert "ETHBTC" in symbols

    def test_to_dict(self, orderbook_manager_populated: OrderbookManager) -> None:
        """Test serialization to dict."""
        result = orderbook_manager_populated.to_dict()

        assert "BTCUSDT" in result
        assert "bid_price" in result["BTCUSDT"]
        assert "ask_price" in result["BTCUSDT"]


class TestBBO:
    """Tests for BBO dataclass."""

    def test_bbo_creation(self) -> None:
        """Test BBO creation."""
        bbo = BBO(
            symbol="BTCUSDT",
            bid_price=50000.0,
            bid_qty=1.5,
            ask_price=50010.0,
            ask_qty=1.2,
            update_id=12345,
            timestamp_us=get_timestamp_us(),
        )

        assert bbo.symbol == "BTCUSDT"
        assert bbo.bid_price == 50000.0
        assert bbo.ask_price == 50010.0

    def test_bbo_spread(self) -> None:
        """Test spread calculation."""
        bbo = BBO(
            symbol="BTCUSDT",
            bid_price=50000.0,
            bid_qty=1.5,
            ask_price=50010.0,
            ask_qty=1.2,
            update_id=12345,
            timestamp_us=get_timestamp_us(),
        )

        assert bbo.spread == 10.0

    def test_bbo_spread_pct(self) -> None:
        """Test spread percentage calculation."""
        bbo = BBO(
            symbol="BTCUSDT",
            bid_price=50000.0,
            bid_qty=1.5,
            ask_price=50010.0,
            ask_qty=1.2,
            update_id=12345,
            timestamp_us=get_timestamp_us(),
        )

        # Spread = 10, mid = 50005, spread_pct = 10/50005 ≈ 0.0002
        assert bbo.spread_pct == pytest.approx(0.0002, rel=0.01)

    def test_bbo_immutable(self) -> None:
        """Test that BBO is frozen (immutable)."""
        bbo = BBO(
            symbol="BTCUSDT",
            bid_price=50000.0,
            bid_qty=1.5,
            ask_price=50010.0,
            ask_qty=1.2,
            update_id=12345,
            timestamp_us=get_timestamp_us(),
        )

        with pytest.raises(AttributeError):
            bbo.bid_price = 60000.0  # type: ignore

    def test_bbo_hashable(self) -> None:
        """Test that BBO is hashable."""
        bbo = BBO(
            symbol="BTCUSDT",
            bid_price=50000.0,
            bid_qty=1.5,
            ask_price=50010.0,
            ask_qty=1.2,
            update_id=12345,
            timestamp_us=get_timestamp_us(),
        )

        # Should be able to use in sets
        bbo_set = {bbo}
        assert len(bbo_set) == 1
