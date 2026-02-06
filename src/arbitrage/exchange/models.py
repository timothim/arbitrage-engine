"""
Pydantic models for Binance API responses.

These models provide type-safe parsing of exchange responses
with automatic validation.
"""

from pydantic import BaseModel, Field


class SymbolFilter(BaseModel):
    """Symbol trading filter from exchange info."""

    filter_type: str = Field(alias="filterType")
    min_price: str | None = Field(default=None, alias="minPrice")
    max_price: str | None = Field(default=None, alias="maxPrice")
    tick_size: str | None = Field(default=None, alias="tickSize")
    min_qty: str | None = Field(default=None, alias="minQty")
    max_qty: str | None = Field(default=None, alias="maxQty")
    step_size: str | None = Field(default=None, alias="stepSize")
    min_notional: str | None = Field(default=None, alias="minNotional")

    model_config = {"populate_by_name": True}


class SymbolData(BaseModel):
    """Symbol information from exchange info."""

    symbol: str
    status: str
    base_asset: str = Field(alias="baseAsset")
    base_asset_precision: int = Field(alias="baseAssetPrecision")
    quote_asset: str = Field(alias="quoteAsset")
    quote_asset_precision: int = Field(alias="quoteAssetPrecision")
    quote_precision: int = Field(alias="quotePrecision")
    filters: list[SymbolFilter]
    permissions: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    def get_filter(self, filter_type: str) -> SymbolFilter | None:
        """Get a specific filter by type."""
        for f in self.filters:
            if f.filter_type == filter_type:
                return f
        return None


class RateLimitInfo(BaseModel):
    """Rate limit information from exchange."""

    rate_limit_type: str = Field(alias="rateLimitType")
    interval: str
    interval_num: int = Field(alias="intervalNum")
    limit: int

    model_config = {"populate_by_name": True}


class ExchangeInfo(BaseModel):
    """Exchange information response."""

    timezone: str
    server_time: int = Field(alias="serverTime")
    rate_limits: list[RateLimitInfo] = Field(alias="rateLimits")
    symbols: list[SymbolData]

    model_config = {"populate_by_name": True}


class Balance(BaseModel):
    """Account balance for a single asset."""

    asset: str
    free: str
    locked: str

    @property
    def available(self) -> float:
        """Get available (free) balance as float."""
        return float(self.free)

    @property
    def total(self) -> float:
        """Get total balance (free + locked) as float."""
        return float(self.free) + float(self.locked)


class AccountInfo(BaseModel):
    """Account information response."""

    maker_commission: int = Field(alias="makerCommission")
    taker_commission: int = Field(alias="takerCommission")
    can_trade: bool = Field(alias="canTrade")
    can_withdraw: bool = Field(alias="canWithdraw")
    can_deposit: bool = Field(alias="canDeposit")
    balances: list[Balance]

    model_config = {"populate_by_name": True}

    def get_balance(self, asset: str) -> float:
        """Get available balance for an asset."""
        for b in self.balances:
            if b.asset == asset:
                return b.available
        return 0.0


class OrderFill(BaseModel):
    """Single fill in an order response."""

    price: str
    qty: str
    commission: str
    commission_asset: str = Field(alias="commissionAsset")

    model_config = {"populate_by_name": True}

    @property
    def price_float(self) -> float:
        """Get price as float."""
        return float(self.price)

    @property
    def qty_float(self) -> float:
        """Get quantity as float."""
        return float(self.qty)

    @property
    def commission_float(self) -> float:
        """Get commission as float."""
        return float(self.commission)


class OrderResponse(BaseModel):
    """Order placement response."""

    symbol: str
    order_id: int = Field(alias="orderId")
    client_order_id: str = Field(alias="clientOrderId")
    transact_time: int = Field(alias="transactTime")
    price: str
    orig_qty: str = Field(alias="origQty")
    executed_qty: str = Field(alias="executedQty")
    cummulative_quote_qty: str = Field(alias="cummulativeQuoteQty")
    status: str
    type: str
    side: str
    fills: list[OrderFill] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @property
    def is_filled(self) -> bool:
        """Check if order is fully filled."""
        return self.status == "FILLED"

    @property
    def executed_qty_float(self) -> float:
        """Get executed quantity as float."""
        return float(self.executed_qty)

    @property
    def avg_fill_price(self) -> float:
        """Calculate average fill price."""
        if not self.fills:
            return float(self.price) if self.price else 0.0

        total_qty = sum(f.qty_float for f in self.fills)
        if total_qty == 0:
            return 0.0

        weighted_sum = sum(f.price_float * f.qty_float for f in self.fills)
        return weighted_sum / total_qty

    @property
    def total_commission(self) -> float:
        """Calculate total commission across all fills."""
        return sum(f.commission_float for f in self.fills)


class CancelOrderResponse(BaseModel):
    """Cancel order response."""

    symbol: str
    order_id: int = Field(alias="orderId")
    client_order_id: str = Field(alias="clientOrderId")
    status: str

    model_config = {"populate_by_name": True}


class ServerTime(BaseModel):
    """Server time response."""

    server_time: int = Field(alias="serverTime")

    model_config = {"populate_by_name": True}
