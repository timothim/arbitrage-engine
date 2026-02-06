"""
Async Binance REST API client.

Optimized for low-latency trading with:
- Connection pooling and keep-alive
- Fast JSON parsing with orjson
- Integrated rate limiting
- Automatic request signing
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiohttp
import orjson

from arbitrage.config.constants import (
    BINANCE_REST_TESTNET_URL,
    BINANCE_REST_URL,
    ENDPOINT_ACCOUNT,
    ENDPOINT_BOOK_TICKER,
    ENDPOINT_EXCHANGE_INFO,
    ENDPOINT_ORDER,
    ENDPOINT_SERVER_TIME,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
    SIDE_BUY,
    SIDE_SELL,
    TIF_IOC,
)
from arbitrage.core.types import OrderSide
from arbitrage.exchange.models import (
    AccountInfo,
    CancelOrderResponse,
    ExchangeInfo,
    OrderResponse,
    ServerTime,
)
from arbitrage.exchange.rate_limiter import RateLimiter
from arbitrage.execution.signer import RequestSigner
from arbitrage.utils.time import get_timestamp_ms


class BinanceClientError(Exception):
    """Base exception for Binance client errors."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class BinanceAPIError(BinanceClientError):
    """Exception for Binance API errors."""

    pass


class BinanceClient:
    """
    Async Binance REST API client.

    Features:
    - Single session with connection pooling
    - Keep-alive for reduced latency
    - orjson for fast JSON parsing
    - Integrated rate limiting
    - Automatic request signing
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        use_testnet: bool = False,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        """
        Initialize the Binance client.

        Args:
            api_key: Binance API key.
            api_secret: Binance API secret.
            use_testnet: Whether to use testnet endpoints.
            rate_limiter: Optional rate limiter instance.
        """
        self._api_key = api_key
        self._signer = RequestSigner(api_secret)
        self._base_url = BINANCE_REST_TESTNET_URL if use_testnet else BINANCE_REST_URL
        self._rate_limiter = rate_limiter or RateLimiter()
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            # Optimized connector settings
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=50,
                keepalive_timeout=30,
                enable_cleanup_closed=True,
                force_close=False,
            )

            # Default headers
            headers = {
                "X-MBX-APIKEY": self._api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            }

            # Custom JSON serializer using orjson
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers=headers,
                json_serialize=lambda x: orjson.dumps(x).decode(),
            )

        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    @asynccontextmanager
    async def _request_context(self) -> AsyncIterator[aiohttp.ClientSession]:
        """Context manager for making requests."""
        session = await self._get_session()
        try:
            yield session
        except aiohttp.ClientError as e:
            raise BinanceClientError(f"Network error: {e}") from e

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        weight: int = 1,
    ) -> dict[str, Any]:
        """
        Make an API request.

        Args:
            method: HTTP method (GET, POST, DELETE).
            endpoint: API endpoint.
            params: Request parameters.
            signed: Whether request requires signature.
            weight: Request weight for rate limiting.

        Returns:
            Parsed JSON response.

        Raises:
            BinanceAPIError: On API error response.
            BinanceClientError: On network or other errors.
        """
        # Rate limiting
        if endpoint == ENDPOINT_ORDER:
            await self._rate_limiter.acquire_order(weight)
        else:
            await self._rate_limiter.acquire_request(weight)

        # Build URL and params
        url = f"{self._base_url}{endpoint}"
        params = params or {}

        # Sign if required
        if signed:
            params = self._signer.create_signed_params(params)

        async with self._request_context() as session:
            if method == "GET":
                async with session.get(url, params=params) as response:
                    return await self._handle_response(response)
            elif method == "POST":
                async with session.post(url, data=params) as response:
                    return await self._handle_response(response)
            elif method == "DELETE":
                async with session.delete(url, params=params) as response:
                    return await self._handle_response(response)
            else:
                raise BinanceClientError(f"Unsupported method: {method}")

    async def _handle_response(self, response: aiohttp.ClientResponse) -> dict[str, Any]:
        """Parse and validate response."""
        # Parse JSON with orjson
        text = await response.text()

        try:
            data = orjson.loads(text)
        except orjson.JSONDecodeError as e:
            raise BinanceClientError(f"Invalid JSON response: {e}") from e

        # Check for API errors
        if response.status >= 400:
            code = data.get("code", response.status)
            msg = data.get("msg", text)
            raise BinanceAPIError(f"API error {code}: {msg}", code=code)

        return data  # type: ignore[no-any-return]

    # =========================================================================
    # Public Endpoints
    # =========================================================================

    async def get_server_time(self) -> ServerTime:
        """Get server time for clock sync."""
        data = await self._request("GET", ENDPOINT_SERVER_TIME, weight=1)
        return ServerTime.model_validate(data)

    async def get_exchange_info(self) -> ExchangeInfo:
        """
        Get exchange trading rules and symbol information.

        Note: This is a heavy request (weight=10), cache the result.
        """
        data = await self._request("GET", ENDPOINT_EXCHANGE_INFO, weight=10)
        return ExchangeInfo.model_validate(data)

    async def get_book_ticker(self, symbol: str | None = None) -> dict[str, Any]:
        """
        Get best bid/ask prices.

        Args:
            symbol: Specific symbol, or None for all symbols.

        Returns:
            Book ticker data.
        """
        params = {"symbol": symbol} if symbol else {}
        return await self._request("GET", ENDPOINT_BOOK_TICKER, params, weight=1)

    # =========================================================================
    # Account Endpoints (Signed)
    # =========================================================================

    async def get_account(self) -> AccountInfo:
        """Get account information including balances."""
        data = await self._request("GET", ENDPOINT_ACCOUNT, signed=True, weight=10)
        return AccountInfo.model_validate(data)

    async def get_balance(self, asset: str) -> float:
        """
        Get available balance for a specific asset.

        Args:
            asset: Asset symbol (e.g., "USDT").

        Returns:
            Available balance.
        """
        account = await self.get_account()
        return account.get_balance(asset)

    # =========================================================================
    # Order Endpoints (Signed)
    # =========================================================================

    async def place_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
    ) -> OrderResponse:
        """
        Place a market order.

        Args:
            symbol: Trading symbol.
            side: Order side (BUY/SELL).
            quantity: Order quantity.

        Returns:
            Order response.
        """
        params = {
            "symbol": symbol,
            "side": SIDE_BUY if side == OrderSide.BUY else SIDE_SELL,
            "type": ORDER_TYPE_MARKET,
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
        }

        data = await self._request("POST", ENDPOINT_ORDER, params, signed=True, weight=1)
        return OrderResponse.model_validate(data)

    async def place_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        time_in_force: str = TIF_IOC,
    ) -> OrderResponse:
        """
        Place a limit order.

        Args:
            symbol: Trading symbol.
            side: Order side (BUY/SELL).
            quantity: Order quantity.
            price: Limit price.
            time_in_force: Order time in force.

        Returns:
            Order response.
        """
        params = {
            "symbol": symbol,
            "side": SIDE_BUY if side == OrderSide.BUY else SIDE_SELL,
            "type": ORDER_TYPE_LIMIT,
            "timeInForce": time_in_force,
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
            "price": f"{price:.8f}".rstrip("0").rstrip("."),
        }

        data = await self._request("POST", ENDPOINT_ORDER, params, signed=True, weight=1)
        return OrderResponse.model_validate(data)

    async def cancel_order(
        self,
        symbol: str,
        order_id: int,
    ) -> CancelOrderResponse:
        """
        Cancel an existing order.

        Args:
            symbol: Trading symbol.
            order_id: Order ID to cancel.

        Returns:
            Cancel response.
        """
        params = {
            "symbol": symbol,
            "orderId": order_id,
        }

        data = await self._request("DELETE", ENDPOINT_ORDER, params, signed=True, weight=1)
        return CancelOrderResponse.model_validate(data)

    # =========================================================================
    # Batch Operations
    # =========================================================================

    async def place_orders_concurrent(
        self,
        orders: list[dict[str, Any]],
    ) -> list[OrderResponse | BaseException]:
        """
        Place multiple orders concurrently.

        Args:
            orders: List of order parameters.

        Returns:
            List of responses or exceptions.
        """
        tasks = []
        for order in orders:
            side = OrderSide(order["side"])
            if order.get("price"):
                task = self.place_limit_order(
                    symbol=order["symbol"],
                    side=side,
                    quantity=order["quantity"],
                    price=order["price"],
                )
            else:
                task = self.place_market_order(
                    symbol=order["symbol"],
                    side=side,
                    quantity=order["quantity"],
                )
            tasks.append(task)

        return await asyncio.gather(*tasks, return_exceptions=True)

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def sync_time(self) -> int:
        """
        Get time difference with server.

        Returns:
            Time difference in milliseconds (local - server).
        """
        local_before = get_timestamp_ms()
        server_time = await self.get_server_time()
        local_after = get_timestamp_ms()

        # Estimate one-way latency
        round_trip = local_after - local_before
        estimated_server_time = server_time.server_time + (round_trip // 2)

        return local_after - estimated_server_time

    async def __aenter__(self) -> "BinanceClient":
        """Async context manager entry."""
        await self._get_session()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Async context manager exit."""
        await self.close()
