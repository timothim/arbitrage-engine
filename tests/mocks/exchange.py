"""
Mock Binance exchange client for testing.

Provides a fully mocked exchange client that simulates
Binance API responses without network calls.
"""

from typing import Any
from unittest.mock import MagicMock

from arbitrage.core.types import OrderSide
from arbitrage.exchange.models import (
    AccountInfo,
    Balance,
    ExchangeInfo,
    OrderResponse,
    ServerTime,
)


class MockBinanceClient:
    """
    Mock Binance client for testing.

    Simulates exchange responses with configurable behavior.
    """

    def __init__(
        self,
        initial_balances: dict[str, float] | None = None,
        fill_orders: bool = True,
        latency_ms: int = 0,
    ) -> None:
        """
        Initialize mock client.

        Args:
            initial_balances: Starting balances by asset.
            fill_orders: Whether orders should fill successfully.
            latency_ms: Simulated latency in milliseconds.
        """
        self._balances = initial_balances or {"USDT": 1000.0, "BTC": 0.0, "ETH": 0.0}
        self._fill_orders = fill_orders
        self._latency_ms = latency_ms
        self._order_id = 0
        self._orders: list[dict[str, Any]] = []

    async def get_server_time(self) -> ServerTime:
        """Mock server time."""
        return ServerTime(server_time=1704067200000)

    async def get_exchange_info(self) -> ExchangeInfo:
        """Mock exchange info."""
        return ExchangeInfo(
            timezone="UTC",
            server_time=1704067200000,
            rate_limits=[],
            symbols=[],
        )

    async def get_account(self) -> AccountInfo:
        """Mock account info."""
        balances = [
            Balance(asset=asset, free=str(amount), locked="0")
            for asset, amount in self._balances.items()
        ]
        return AccountInfo(
            maker_commission=10,
            taker_commission=10,
            can_trade=True,
            can_withdraw=True,
            can_deposit=True,
            balances=balances,
        )

    async def get_balance(self, asset: str) -> float:
        """Mock balance lookup."""
        return self._balances.get(asset, 0.0)

    async def place_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
    ) -> OrderResponse:
        """Mock market order placement."""
        return await self._place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=None,
            order_type="MARKET",
        )

    async def place_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        time_in_force: str = "IOC",
    ) -> OrderResponse:
        """Mock limit order placement."""
        return await self._place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type="LIMIT",
        )

    async def _place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float | None,
        order_type: str,
    ) -> OrderResponse:
        """Internal order placement logic."""
        self._order_id += 1

        # Simulate price if not provided
        if price is None:
            price = self._get_mock_price(symbol)

        # Record order
        order = {
            "symbol": symbol,
            "side": side.value,
            "quantity": quantity,
            "price": price,
            "type": order_type,
            "order_id": self._order_id,
        }
        self._orders.append(order)

        # Determine fill status
        status = "FILLED" if self._fill_orders else "EXPIRED"
        executed_qty = quantity if self._fill_orders else 0.0

        # Update balances if filled
        if self._fill_orders:
            self._update_balances(symbol, side, quantity, price)

        return OrderResponse(
            symbol=symbol,
            order_id=self._order_id,
            client_order_id=f"mock_{self._order_id}",
            transact_time=1704067200000,
            price=str(price),
            orig_qty=str(quantity),
            executed_qty=str(executed_qty),
            cummulative_quote_qty=str(executed_qty * price),
            status=status,
            type=order_type,
            side=side.value,
            fills=[
                {
                    "price": str(price),
                    "qty": str(executed_qty),
                    "commission": str(executed_qty * price * 0.001),
                    "commissionAsset": "BNB",
                }
            ]
            if self._fill_orders
            else [],
        )

    def _get_mock_price(self, symbol: str) -> float:
        """Get mock price for a symbol."""
        prices = {
            "BTCUSDT": 50000.0,
            "ETHUSDT": 3000.0,
            "ETHBTC": 0.06,
        }
        return prices.get(symbol, 100.0)

    def _update_balances(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
    ) -> None:
        """Update balances after a trade."""
        # Parse symbol (simplified - assumes 3-4 char assets)
        base = symbol[:3] if len(symbol) <= 7 else symbol[:4]
        quote = symbol[3:] if len(symbol) <= 7 else symbol[4:]

        if base == "ETH" and quote == "USDT":
            base, quote = "ETH", "USDT"
        elif base == "BTC" and quote == "USDT":
            base, quote = "BTC", "USDT"
        elif base == "ETH" and quote == "BTC":
            base, quote = "ETH", "BTC"

        notional = quantity * price

        if side == OrderSide.BUY:
            # Buying base, selling quote
            self._balances[base] = self._balances.get(base, 0) + quantity
            self._balances[quote] = self._balances.get(quote, 0) - notional
        else:
            # Selling base, buying quote
            self._balances[base] = self._balances.get(base, 0) - quantity
            self._balances[quote] = self._balances.get(quote, 0) + notional

    async def cancel_order(self, symbol: str, order_id: int) -> MagicMock:
        """Mock order cancellation."""
        return MagicMock(
            symbol=symbol,
            order_id=order_id,
            status="CANCELED",
        )

    async def close(self) -> None:
        """Mock close."""
        pass

    async def __aenter__(self) -> "MockBinanceClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Async context manager exit."""
        await self.close()

    @property
    def orders(self) -> list[dict[str, Any]]:
        """Get all placed orders."""
        return self._orders

    @property
    def balances(self) -> dict[str, float]:
        """Get current balances."""
        return self._balances
