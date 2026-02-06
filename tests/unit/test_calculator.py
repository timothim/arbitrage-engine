"""
Unit tests for ArbitrageCalculator.

Tests profit calculation, fee handling, and opportunity detection.
"""

import pytest

from arbitrage.core.types import BBO, OrderSide, TriangleLeg, TrianglePath
from arbitrage.market.orderbook import OrderbookManager
from arbitrage.strategy.calculator import ArbitrageCalculator
from arbitrage.utils.time import get_timestamp_us


class TestArbitrageCalculator:
    """Tests for ArbitrageCalculator."""

    def test_initialization(self) -> None:
        """Test calculator initialization."""
        calc = ArbitrageCalculator(fee_rate=0.001, slippage_buffer=0.0001)

        assert calc.fee_rate == 0.001
        assert calc.total_fee_rate == pytest.approx(0.002997, rel=0.01)

    def test_fee_multiplier_calculation(self) -> None:
        """Test that fee multiplier is correctly computed."""
        calc = ArbitrageCalculator(fee_rate=0.001)

        # (1 - 0.001)^3 = 0.997002999
        expected = (1 - 0.001) ** 3
        assert calc._fee_multiplier == pytest.approx(expected, rel=0.0001)

    def test_calculate_opportunity_basic(
        self,
        calculator: ArbitrageCalculator,
        triangle_usdt_btc_eth: TrianglePath,
        orderbook_manager_populated: OrderbookManager,
    ) -> None:
        """Test basic opportunity calculation."""
        opportunity = calculator.calculate_opportunity(
            triangle_usdt_btc_eth, orderbook_manager_populated
        )

        assert opportunity is not None
        assert opportunity.path == triangle_usdt_btc_eth
        assert len(opportunity.prices) == 3
        assert len(opportunity.quantities) == 3

    def test_calculate_opportunity_missing_prices(
        self,
        calculator: ArbitrageCalculator,
        triangle_usdt_btc_eth: TrianglePath,
    ) -> None:
        """Test that None is returned when prices are missing."""
        empty_orderbook = OrderbookManager()

        opportunity = calculator.calculate_opportunity(
            triangle_usdt_btc_eth, empty_orderbook
        )

        assert opportunity is None

    def test_profitable_opportunity(
        self,
        calculator: ArbitrageCalculator,
        triangle_usdt_btc_eth: TrianglePath,
    ) -> None:
        """Test detection of profitable opportunity."""
        # Set up prices that create profit
        orderbook = OrderbookManager()

        # USDT -> BTC: buy at 50000
        orderbook.update(
            BBO(
                symbol="BTCUSDT",
                bid_price=49990.0,
                bid_qty=1.0,
                ask_price=50000.0,
                ask_qty=1.0,
                update_id=1,
                timestamp_us=get_timestamp_us(),
            )
        )

        # BTC -> ETH: buy at 0.059 (cheaper than market)
        orderbook.update(
            BBO(
                symbol="ETHBTC",
                bid_price=0.0589,
                bid_qty=50.0,
                ask_price=0.059,
                ask_qty=50.0,
                update_id=2,
                timestamp_us=get_timestamp_us(),
            )
        )

        # ETH -> USDT: sell at 3000
        orderbook.update(
            BBO(
                symbol="ETHUSDT",
                bid_price=3000.0,
                bid_qty=10.0,
                ask_price=3001.0,
                ask_qty=10.0,
                update_id=3,
                timestamp_us=get_timestamp_us(),
            )
        )

        opportunity = calculator.calculate_opportunity(triangle_usdt_btc_eth, orderbook)

        assert opportunity is not None
        # With these prices: (1/50000) * (1/0.059) * 3000 = 1.0169
        assert opportunity.gross_return > 1.0
        assert opportunity.is_profitable

    def test_unprofitable_opportunity(
        self,
        calculator: ArbitrageCalculator,
        triangle_usdt_btc_eth: TrianglePath,
    ) -> None:
        """Test detection of unprofitable opportunity."""
        orderbook = OrderbookManager()

        # Set up prices that result in loss
        orderbook.update(
            BBO(
                symbol="BTCUSDT",
                bid_price=49990.0,
                bid_qty=1.0,
                ask_price=50000.0,
                ask_qty=1.0,
                update_id=1,
                timestamp_us=get_timestamp_us(),
            )
        )

        orderbook.update(
            BBO(
                symbol="ETHBTC",
                bid_price=0.0609,
                bid_qty=50.0,
                ask_price=0.061,  # More expensive
                ask_qty=50.0,
                update_id=2,
                timestamp_us=get_timestamp_us(),
            )
        )

        orderbook.update(
            BBO(
                symbol="ETHUSDT",
                bid_price=2990.0,  # Lower sell price
                bid_qty=10.0,
                ask_price=2991.0,
                ask_qty=10.0,
                update_id=3,
                timestamp_us=get_timestamp_us(),
            )
        )

        opportunity = calculator.calculate_opportunity(triangle_usdt_btc_eth, orderbook)

        assert opportunity is not None
        assert opportunity.net_return < 1.0
        assert not opportunity.is_profitable

    def test_quick_check_profitable(
        self,
        calculator: ArbitrageCalculator,
        triangle_usdt_btc_eth: TrianglePath,
    ) -> None:
        """Test quick profitability check."""
        # Profitable prices
        prices = (
            (49990.0, 50000.0),  # BTCUSDT
            (0.0589, 0.059),  # ETHBTC
            (3000.0, 3001.0),  # ETHUSDT
        )

        result = calculator.quick_check(triangle_usdt_btc_eth, prices, min_profit_pct=0.0)

        # Should be profitable with these prices
        assert result is True

    def test_quick_check_unprofitable(
        self,
        calculator: ArbitrageCalculator,
        triangle_usdt_btc_eth: TrianglePath,
    ) -> None:
        """Test quick check with unprofitable prices."""
        # Unprofitable prices
        prices = (
            (49990.0, 50000.0),
            (0.0609, 0.061),
            (2990.0, 2991.0),
        )

        result = calculator.quick_check(triangle_usdt_btc_eth, prices, min_profit_pct=0.5)

        assert result is False

    def test_apply_slippage_buy(self, calculator: ArbitrageCalculator) -> None:
        """Test slippage application for buy orders."""
        price = 100.0
        adjusted = calculator.apply_slippage(price, OrderSide.BUY)

        # Buy should pay slightly more
        assert adjusted > price
        assert adjusted == pytest.approx(100.01, rel=0.001)

    def test_apply_slippage_sell(self, calculator: ArbitrageCalculator) -> None:
        """Test slippage application for sell orders."""
        price = 100.0
        adjusted = calculator.apply_slippage(price, OrderSide.SELL)

        # Sell should accept slightly less
        assert adjusted < price
        assert adjusted == pytest.approx(99.99, rel=0.001)

    def test_set_fee_rate(self, calculator: ArbitrageCalculator) -> None:
        """Test updating fee rate."""
        calculator.set_fee_rate(0.0005)

        assert calculator.fee_rate == 0.0005
        expected_multiplier = (1 - 0.0005) ** 3
        assert calculator._fee_multiplier == pytest.approx(expected_multiplier)


class TestGrossReturnCalculation:
    """Tests for gross return calculation with different leg combinations."""

    def test_buy_buy_sell_pattern(self) -> None:
        """Test BUY -> BUY -> SELL pattern."""
        calc = ArbitrageCalculator(fee_rate=0.0)

        # USDT -> BTC (BUY at 50000)
        # BTC -> ETH (BUY at 0.06)
        # ETH -> USDT (SELL at 3050)

        # Expected: (1/50000) * (1/0.06) * 3050 = 1.0167
        expected = (1 / 50000) * (1 / 0.06) * 3050

        result = calc._calculate_gross_return(
            OrderSide.BUY, 50000.0,
            OrderSide.BUY, 0.06,
            OrderSide.SELL, 3050.0,
        )

        assert result == pytest.approx(expected, rel=0.0001)

    def test_zero_price_handling(self) -> None:
        """Test that zero prices don't cause division errors."""
        orderbook = OrderbookManager()
        orderbook.update(
            BBO(
                symbol="BTCUSDT",
                bid_price=0.0,  # Zero price
                bid_qty=1.0,
                ask_price=0.0,
                ask_qty=1.0,
                update_id=1,
                timestamp_us=get_timestamp_us(),
            )
        )

        calc = ArbitrageCalculator()
        path = TrianglePath(
            id="test",
            base_asset="USDT",
            legs=(
                TriangleLeg("BTCUSDT", OrderSide.BUY, "USDT", "BTC"),
                TriangleLeg("ETHBTC", OrderSide.BUY, "BTC", "ETH"),
                TriangleLeg("ETHUSDT", OrderSide.SELL, "ETH", "USDT"),
            ),
        )

        # Should return None due to zero price
        result = calc.calculate_opportunity(path, orderbook)
        assert result is None
