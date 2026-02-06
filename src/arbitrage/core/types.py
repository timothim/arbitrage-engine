"""
Type definitions for the arbitrage engine.

This module contains all dataclasses, enums, TypedDicts, and Protocol
definitions used throughout the application. Using slots=True for
memory efficiency and faster attribute access.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Protocol, TypedDict


# =============================================================================
# Enums
# =============================================================================


class OrderSide(str, Enum):
    """Order side enumeration."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Order execution status."""

    PENDING = "PENDING"
    SENT = "SENT"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class ExecutionStatus(str, Enum):
    """Triangle execution status."""

    SUCCESS = auto()
    PARTIAL = auto()
    FAILED = auto()
    RECOVERED = auto()


# =============================================================================
# Market Data Types
# =============================================================================


@dataclass(slots=True, frozen=True)
class BBO:
    """
    Best Bid and Offer (top of book) data.

    Frozen for immutability and hashability.
    Uses slots for 30% memory reduction.
    """

    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    update_id: int
    timestamp_us: int

    @property
    def spread(self) -> float:
        """Calculate bid-ask spread."""
        return self.ask_price - self.bid_price

    @property
    def spread_pct(self) -> float:
        """Calculate bid-ask spread as percentage of mid price."""
        mid = (self.bid_price + self.ask_price) / 2
        return self.spread / mid if mid > 0 else 0.0


@dataclass(slots=True)
class SymbolInfo:
    """
    Trading symbol metadata from exchange.

    Contains precision rules and trading limits.
    """

    symbol: str
    base_asset: str
    quote_asset: str
    price_precision: int
    quantity_precision: int
    min_notional: float
    min_qty: float
    max_qty: float
    step_size: float
    tick_size: float
    status: str = "TRADING"

    def round_price(self, price: float) -> float:
        """Round price to valid tick size."""
        if self.tick_size <= 0:
            return round(price, self.price_precision)
        return round(price / self.tick_size) * self.tick_size

    def round_quantity(self, qty: float) -> float:
        """Round quantity to valid step size."""
        if self.step_size <= 0:
            return round(qty, self.quantity_precision)
        return round(qty / self.step_size) * self.step_size

    def is_valid_quantity(self, qty: float) -> bool:
        """Check if quantity meets symbol constraints."""
        return self.min_qty <= qty <= self.max_qty


# =============================================================================
# Triangle Types
# =============================================================================


@dataclass(slots=True, frozen=True)
class TriangleLeg:
    """
    Single leg of a triangular arbitrage path.

    Each leg represents one trade in the triangle.
    """

    symbol: str
    side: OrderSide
    from_asset: str
    to_asset: str

    def __repr__(self) -> str:
        return f"{self.from_asset}->{self.to_asset}({self.symbol}:{self.side.value})"


@dataclass(slots=True)
class TrianglePath:
    """
    Complete triangular arbitrage path.

    Consists of exactly 3 legs forming a cycle.
    Pre-computed at startup for O(1) lookup during trading.
    """

    id: str
    base_asset: str
    legs: tuple[TriangleLeg, TriangleLeg, TriangleLeg]
    symbols: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        """Compute derived fields after initialization."""
        object.__setattr__(
            self, "symbols", frozenset(leg.symbol for leg in self.legs)
        )

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TrianglePath):
            return NotImplemented
        return self.id == other.id


# =============================================================================
# Opportunity Types
# =============================================================================


@dataclass(slots=True)
class Opportunity:
    """
    Detected arbitrage opportunity.

    Contains all information needed to execute the triangle.
    """

    path: TrianglePath
    profit_pct: float
    gross_return: float
    net_return: float
    prices: tuple[float, float, float]
    quantities: tuple[float, float, float]
    max_trade_qty: float
    timestamp_us: int

    @property
    def is_profitable(self) -> bool:
        """Check if opportunity is profitable after fees."""
        return self.net_return > 1.0


# =============================================================================
# Execution Types
# =============================================================================


@dataclass(slots=True)
class LegResult:
    """Result of executing a single leg."""

    leg: TriangleLeg
    status: OrderStatus
    order_id: str | None = None
    filled_qty: float = 0.0
    filled_price: float = 0.0
    commission: float = 0.0
    commission_asset: str = ""
    error_message: str = ""
    latency_us: int = 0

    @property
    def is_filled(self) -> bool:
        """Check if leg was fully filled."""
        return self.status == OrderStatus.FILLED


@dataclass(slots=True)
class ExecutionResult:
    """Result of executing a complete triangle."""

    opportunity: Opportunity
    status: ExecutionStatus
    legs: tuple[LegResult, LegResult, LegResult]
    total_profit: float = 0.0
    total_commission: float = 0.0
    start_timestamp_us: int = 0
    end_timestamp_us: int = 0
    error_message: str = ""

    @property
    def total_latency_us(self) -> int:
        """Calculate total execution latency."""
        return self.end_timestamp_us - self.start_timestamp_us

    @property
    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status == ExecutionStatus.SUCCESS


# =============================================================================
# TypedDicts for API Responses
# =============================================================================


class BookTickerData(TypedDict):
    """Binance bookTicker WebSocket message."""

    s: str  # Symbol
    b: str  # Best bid price
    B: str  # Best bid qty
    a: str  # Best ask price
    A: str  # Best ask qty
    u: int  # Update ID


class OrderResponseData(TypedDict, total=False):
    """Binance order response."""

    symbol: str
    orderId: int
    clientOrderId: str
    transactTime: int
    price: str
    origQty: str
    executedQty: str
    cummulativeQuoteQty: str
    status: str
    type: str
    side: str
    fills: list[dict[str, str]]


class AccountBalanceData(TypedDict):
    """Single balance entry in account info."""

    asset: str
    free: str
    locked: str


# =============================================================================
# Protocols (Interfaces)
# =============================================================================


class OrderbookCache(Protocol):
    """Protocol for orderbook cache implementations."""

    def get(self, symbol: str) -> BBO | None:
        """Get BBO for a symbol."""
        ...

    def update(self, bbo: BBO) -> None:
        """Update BBO for a symbol."""
        ...

    def get_symbols(self) -> frozenset[str]:
        """Get all cached symbols."""
        ...


class ExchangeClient(Protocol):
    """Protocol for exchange client implementations."""

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float | None = None,
    ) -> OrderResponseData:
        """Place an order on the exchange."""
        ...

    async def get_account_balance(self, asset: str) -> float:
        """Get available balance for an asset."""
        ...

    async def cancel_order(self, symbol: str, order_id: int) -> bool:
        """Cancel an existing order."""
        ...


class MetricsCollector(Protocol):
    """Protocol for metrics collection."""

    def record_latency(self, name: str, latency_us: int) -> None:
        """Record a latency measurement."""
        ...

    def increment_counter(self, name: str, value: int = 1) -> None:
        """Increment a counter."""
        ...

    def record_profit(self, amount: float) -> None:
        """Record profit/loss."""
        ...
