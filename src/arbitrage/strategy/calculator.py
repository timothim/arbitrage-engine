"""
Arbitrage profit calculation engine.

Computes potential profit for triangular arbitrage paths
with fee adjustments and quantity constraints.
"""

import logging

from arbitrage.core.types import Opportunity, OrderSide, TrianglePath
from arbitrage.market.orderbook import OrderbookManager
from arbitrage.utils.time import get_timestamp_us


logger = logging.getLogger(__name__)


class ArbitrageCalculator:
    """
    Calculates arbitrage profits for triangle paths.

    Optimized for the hot path with minimal overhead:
    - Pre-computed fee multiplier
    - Direct float operations (no Decimal)
    - Inline calculations where possible
    """

    __slots__ = ("_fee_rate", "_fee_multiplier", "_slippage_buffer")

    def __init__(
        self,
        fee_rate: float = 0.001,
        slippage_buffer: float = 0.0001,
    ) -> None:
        """
        Initialize calculator.

        Args:
            fee_rate: Trading fee per leg (e.g., 0.001 = 0.1%).
            slippage_buffer: Price buffer for slippage protection.
        """
        self._fee_rate = fee_rate
        # Pre-compute fee multiplier for 3 legs
        self._fee_multiplier = (1.0 - fee_rate) ** 3
        self._slippage_buffer = slippage_buffer

    def calculate_opportunity(
        self,
        path: TrianglePath,
        orderbook: OrderbookManager,
    ) -> Opportunity | None:
        """
        Calculate arbitrage opportunity for a triangle path.

        Args:
            path: Triangle path to evaluate.
            orderbook: Current orderbook data.

        Returns:
            Opportunity if prices available, None otherwise.
        """
        timestamp = get_timestamp_us()

        # Get all BBOs
        leg1, leg2, leg3 = path.legs

        bbo1 = orderbook.get(leg1.symbol)
        bbo2 = orderbook.get(leg2.symbol)
        bbo3 = orderbook.get(leg3.symbol)

        if bbo1 is None or bbo2 is None or bbo3 is None:
            return None

        # Get prices based on order side
        # BUY uses ask price, SELL uses bid price
        price1 = bbo1.ask_price if leg1.side == OrderSide.BUY else bbo1.bid_price
        price2 = bbo2.ask_price if leg2.side == OrderSide.BUY else bbo2.bid_price
        price3 = bbo3.ask_price if leg3.side == OrderSide.BUY else bbo3.bid_price

        # Validate prices
        if price1 <= 0 or price2 <= 0 or price3 <= 0:
            return None

        # Calculate gross return
        # The formula depends on the direction of each leg
        gross_return = self._calculate_gross_return(
            leg1.side, price1,
            leg2.side, price2,
            leg3.side, price3,
        )

        # Apply fees
        net_return = gross_return * self._fee_multiplier

        # Calculate profit percentage
        profit_pct = (net_return - 1.0) * 100.0

        # Get quantities for size calculation
        qty1 = bbo1.ask_qty if leg1.side == OrderSide.BUY else bbo1.bid_qty
        qty2 = bbo2.ask_qty if leg2.side == OrderSide.BUY else bbo2.bid_qty
        qty3 = bbo3.ask_qty if leg3.side == OrderSide.BUY else bbo3.bid_qty

        # Calculate maximum trade quantity
        max_trade_qty = self._calculate_max_quantity(
            leg1.side, price1, qty1,
            leg2.side, price2, qty2,
            leg3.side, price3, qty3,
        )

        return Opportunity(
            path=path,
            profit_pct=profit_pct,
            gross_return=gross_return,
            net_return=net_return,
            prices=(price1, price2, price3),
            quantities=(qty1, qty2, qty3),
            max_trade_qty=max_trade_qty,
            timestamp_us=timestamp,
        )

    def _calculate_gross_return(
        self,
        side1: OrderSide, price1: float,
        side2: OrderSide, price2: float,
        side3: OrderSide, price3: float,
    ) -> float:
        """
        Calculate gross return for a triangle.

        The return depends on whether each leg is a buy or sell:
        - BUY: We spend quote to get base -> divide by price
        - SELL: We spend base to get quote -> multiply by price

        Starting with 1 unit of base currency, we trace through.
        """
        result = 1.0

        # Leg 1
        if side1 == OrderSide.BUY:
            result /= price1  # Buying: spend quote, get base
        else:
            result *= price1  # Selling: spend base, get quote

        # Leg 2
        if side2 == OrderSide.BUY:
            result /= price2
        else:
            result *= price2

        # Leg 3
        if side3 == OrderSide.BUY:
            result /= price3
        else:
            result *= price3

        return result

    def _calculate_max_quantity(
        self,
        side1: OrderSide, price1: float, qty1: float,
        side2: OrderSide, price2: float, qty2: float,
        side3: OrderSide, price3: float, qty3: float,
    ) -> float:
        """
        Calculate maximum trade size across all legs.

        Converts all quantities to base currency terms.
        """
        # Convert all to base currency equivalent
        max_from_leg1 = qty1 * price1 if side1 == OrderSide.BUY else qty1 * price1
        max_from_leg2 = qty2 * price2 * price1  # Approximate conversion
        max_from_leg3 = qty3 * price3 if side3 == OrderSide.SELL else qty3

        return min(max_from_leg1, max_from_leg2, max_from_leg3)

    def quick_check(
        self,
        path: TrianglePath,
        prices: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
        min_profit_pct: float = 0.0,
    ) -> bool:
        """
        Quickly check if a triangle might be profitable.

        Faster than full calculation for initial filtering.

        Args:
            path: Triangle path.
            prices: Tuple of (bid, ask) for each leg.
            min_profit_pct: Minimum profit percentage.

        Returns:
            True if potentially profitable.
        """
        leg1, leg2, leg3 = path.legs
        (bid1, ask1), (bid2, ask2), (bid3, ask3) = prices

        # Get appropriate prices
        p1 = ask1 if leg1.side == OrderSide.BUY else bid1
        p2 = ask2 if leg2.side == OrderSide.BUY else bid2
        p3 = ask3 if leg3.side == OrderSide.BUY else bid3

        if p1 <= 0 or p2 <= 0 or p3 <= 0:
            return False

        gross = self._calculate_gross_return(
            leg1.side, p1,
            leg2.side, p2,
            leg3.side, p3,
        )

        net = gross * self._fee_multiplier
        profit_pct = (net - 1.0) * 100.0

        return profit_pct >= min_profit_pct

    def apply_slippage(
        self,
        price: float,
        side: OrderSide,
    ) -> float:
        """
        Apply slippage buffer to a price.

        Args:
            price: Original price.
            side: Order side.

        Returns:
            Adjusted price.
        """
        if side == OrderSide.BUY:
            # Pay slightly more for buys
            return price * (1.0 + self._slippage_buffer)
        else:
            # Accept slightly less for sells
            return price * (1.0 - self._slippage_buffer)

    @property
    def fee_rate(self) -> float:
        """Get fee rate per leg."""
        return self._fee_rate

    @property
    def total_fee_rate(self) -> float:
        """Get total fee rate for 3 legs."""
        return 1.0 - self._fee_multiplier

    def set_fee_rate(self, fee_rate: float) -> None:
        """Update fee rate."""
        self._fee_rate = fee_rate
        self._fee_multiplier = (1.0 - fee_rate) ** 3
