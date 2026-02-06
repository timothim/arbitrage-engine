"""
HMAC-SHA256 request signing for Binance API.

Provides fast, secure request signing with pre-computation
optimizations to minimize latency during order placement.
"""

import hashlib
import hmac
from urllib.parse import urlencode

from arbitrage.utils.time import get_timestamp_ms


class RequestSigner:
    """
    Signs requests for Binance API authentication.

    Uses HMAC-SHA256 as required by Binance.
    Optimized for minimal latency during critical paths.
    """

    __slots__ = ("_secret_bytes",)

    def __init__(self, api_secret: str) -> None:
        """
        Initialize signer with API secret.

        Args:
            api_secret: Binance API secret key.
        """
        # Pre-encode secret for faster HMAC computation
        self._secret_bytes = api_secret.encode("utf-8")

    def sign(self, query_string: str) -> str:
        """
        Generate HMAC-SHA256 signature for a query string.

        Args:
            query_string: URL-encoded query parameters.

        Returns:
            Hexadecimal signature string.
        """
        return hmac.new(
            self._secret_bytes,
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def sign_params(self, params: dict[str, str | int | float]) -> str:
        """
        Sign request parameters and return complete query string.

        Automatically adds timestamp if not present.

        Args:
            params: Request parameters.

        Returns:
            Complete query string with signature.
        """
        # Add timestamp if not present
        if "timestamp" not in params:
            params["timestamp"] = get_timestamp_ms()

        # Build query string
        query_string = urlencode(params)

        # Generate signature
        signature = self.sign(query_string)

        # Return complete query string with signature
        return f"{query_string}&signature={signature}"

    def create_signed_params(
        self,
        params: dict[str, str | int | float],
    ) -> dict[str, str | int | float]:
        """
        Create a new params dict with timestamp and signature.

        Args:
            params: Original request parameters.

        Returns:
            New params dict including timestamp and signature.
        """
        # Create copy with timestamp
        signed_params = dict(params)
        if "timestamp" not in signed_params:
            signed_params["timestamp"] = get_timestamp_ms()

        # Build query string for signing
        query_string = urlencode(signed_params)

        # Add signature
        signed_params["signature"] = self.sign(query_string)

        return signed_params


class OrderSignatureCache:
    """
    Caches pre-computed order signature components.

    For ultra-low latency, pre-computes as much of the signature
    as possible before the order is needed.

    Note: Due to timestamp requirements, full pre-computation
    is not possible, but we can cache the static parts.
    """

    __slots__ = ("_signer", "_static_params")

    def __init__(self, signer: RequestSigner) -> None:
        """
        Initialize cache with a signer.

        Args:
            signer: RequestSigner instance.
        """
        self._signer = signer
        self._static_params: dict[str, dict[str, str]] = {}

    def precompute_order_base(
        self,
        symbol: str,
        side: str,
        order_type: str,
        time_in_force: str | None = None,
    ) -> str:
        """
        Pre-compute the static portion of an order's query string.

        Args:
            symbol: Trading symbol.
            side: Order side (BUY/SELL).
            order_type: Order type (LIMIT/MARKET).
            time_in_force: Time in force (GTC/IOC/FOK).

        Returns:
            Cache key for retrieval.
        """
        cache_key = f"{symbol}_{side}_{order_type}"

        params: dict[str, str] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        if time_in_force:
            params["timeInForce"] = time_in_force

        self._static_params[cache_key] = params
        return cache_key

    def get_signed_order_params(
        self,
        cache_key: str,
        quantity: float,
        price: float | None = None,
    ) -> dict[str, str | int | float]:
        """
        Get complete signed parameters for an order.

        Args:
            cache_key: Key from precompute_order_base.
            quantity: Order quantity.
            price: Order price (required for LIMIT orders).

        Returns:
            Complete signed parameters dict.

        Raises:
            KeyError: If cache_key not found.
        """
        # Get cached static params
        static = self._static_params[cache_key]

        # Build complete params
        params: dict[str, str | int | float] = dict(static)
        params["quantity"] = f"{quantity:.8f}".rstrip("0").rstrip(".")

        if price is not None:
            params["price"] = f"{price:.8f}".rstrip("0").rstrip(".")

        # Sign and return
        return self._signer.create_signed_params(params)
