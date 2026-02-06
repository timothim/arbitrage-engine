"""
Mathematical utilities for trading calculations.

Provides precision-safe operations for price and quantity calculations,
handling the specific requirements of exchange trading systems.
"""

import math
from typing import Final


# Epsilon for floating point comparisons
EPSILON: Final[float] = 1e-10


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safely divide two numbers, returning default on division by zero.

    Args:
        numerator: The dividend.
        denominator: The divisor.
        default: Value to return if denominator is zero.

    Returns:
        Result of division or default value.
    """
    if abs(denominator) < EPSILON:
        return default
    return numerator / denominator


def round_tick(value: float, tick_size: float) -> float:
    """
    Round a price to the nearest tick size.

    Args:
        value: Price to round.
        tick_size: Minimum price increment (e.g., 0.01).

    Returns:
        Price rounded to nearest tick.

    Example:
        >>> round_tick(100.123, 0.01)
        100.12
        >>> round_tick(100.126, 0.01)
        100.13
    """
    if tick_size <= 0:
        return value
    return round(value / tick_size) * tick_size


def round_step(value: float, step_size: float) -> float:
    """
    Round a quantity to the nearest step size (floor).

    Uses floor to ensure we don't exceed available balance.

    Args:
        value: Quantity to round.
        step_size: Minimum quantity increment.

    Returns:
        Quantity rounded down to step.

    Example:
        >>> round_step(1.234567, 0.001)
        1.234
    """
    if step_size <= 0:
        return value
    return math.floor(value / step_size) * step_size


def normalize_quantity(
    qty: float,
    step_size: float,
    min_qty: float,
    max_qty: float,
) -> float | None:
    """
    Normalize a quantity to meet exchange requirements.

    Args:
        qty: Desired quantity.
        step_size: Minimum quantity increment.
        min_qty: Minimum allowed quantity.
        max_qty: Maximum allowed quantity.

    Returns:
        Normalized quantity or None if constraints cannot be met.
    """
    # Round to step size
    normalized = round_step(qty, step_size)

    # Check bounds
    if normalized < min_qty:
        return None
    if normalized > max_qty:
        return max_qty

    return normalized


def calculate_quantity_for_notional(
    notional: float,
    price: float,
    step_size: float,
    min_qty: float,
    max_qty: float,
) -> float | None:
    """
    Calculate the maximum quantity that can be bought with a given notional value.

    Args:
        notional: Amount in quote currency to spend.
        price: Price per unit.
        step_size: Minimum quantity increment.
        min_qty: Minimum allowed quantity.
        max_qty: Maximum allowed quantity.

    Returns:
        Maximum valid quantity or None if constraints cannot be met.
    """
    if price <= 0:
        return None

    raw_qty = notional / price
    return normalize_quantity(raw_qty, step_size, min_qty, max_qty)


def calculate_profit_rate(
    price_leg1_ask: float,
    price_leg2_ask: float,
    price_leg3_bid: float,
    fee_rate: float,
) -> tuple[float, float, float]:
    """
    Calculate profit rate for a triangular arbitrage opportunity.

    Formula for path: A -> B -> C -> A
    - Leg 1: Buy B with A (use ask price)
    - Leg 2: Buy C with B (use ask price)
    - Leg 3: Sell C for A (use bid price)

    Args:
        price_leg1_ask: Ask price for leg 1 (A/B pair).
        price_leg2_ask: Ask price for leg 2 (B/C pair).
        price_leg3_bid: Bid price for leg 3 (C/A pair).
        fee_rate: Trading fee rate per leg.

    Returns:
        Tuple of (gross_return, net_return, profit_pct).

    Example:
        >>> calculate_profit_rate(50000.0, 0.06, 3100.0, 0.001)
        (1.033..., 1.030..., 3.0...)
    """
    # Gross return (before fees)
    gross_return = (1.0 / price_leg1_ask) * (1.0 / price_leg2_ask) * price_leg3_bid

    # Net return (after 3 legs of fees)
    fee_multiplier = (1.0 - fee_rate) ** 3
    net_return = gross_return * fee_multiplier

    # Profit percentage
    profit_pct = (net_return - 1.0) * 100.0

    return gross_return, net_return, profit_pct


def calculate_max_trade_size(
    qty1: float,
    qty2: float,
    qty3: float,
    price1: float,
    price2: float,
    balance: float,
    max_position_pct: float,
) -> float:
    """
    Calculate the maximum trade size for a triangle.

    Considers:
    - Available liquidity at each leg
    - Available balance
    - Position size limits

    Args:
        qty1: Available quantity at leg 1.
        qty2: Available quantity at leg 2.
        qty3: Available quantity at leg 3.
        price1: Price at leg 1.
        price2: Price at leg 2.
        balance: Available balance in base currency.
        max_position_pct: Maximum position as percentage of balance.

    Returns:
        Maximum trade size in base currency.
    """
    # Maximum based on balance
    max_from_balance = balance * max_position_pct

    # Maximum based on leg 1 liquidity (buying with base currency)
    max_from_leg1 = qty1 * price1

    # Maximum based on leg 2 liquidity (converted to base currency)
    max_from_leg2 = qty2 * price2 * price1

    # Maximum based on leg 3 liquidity (already in terms of base currency)
    max_from_leg3 = qty3

    return min(max_from_balance, max_from_leg1, max_from_leg2, max_from_leg3)


def is_profitable(net_return: float, min_threshold: float = 0.0) -> bool:
    """
    Check if a trade opportunity is profitable.

    Args:
        net_return: Net return ratio (1.0 = break-even).
        min_threshold: Minimum profit threshold (e.g., 0.0005 = 0.05%).

    Returns:
        True if profitable above threshold.
    """
    return net_return > (1.0 + min_threshold)


def format_profit(profit_pct: float) -> str:
    """
    Format profit percentage for display.

    Args:
        profit_pct: Profit as percentage.

    Returns:
        Formatted string with color indicator.
    """
    sign = "+" if profit_pct >= 0 else ""
    return f"{sign}{profit_pct:.4f}%"
