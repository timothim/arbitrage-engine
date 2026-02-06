"""
Token bucket rate limiter for API requests.

Implements a thread-safe, async-compatible rate limiter to prevent
exceeding Binance API rate limits.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Final

from arbitrage.utils.time import get_timestamp_ms


# Default rate limits (conservative)
DEFAULT_REQUESTS_PER_SECOND: Final[int] = 10
DEFAULT_ORDERS_PER_SECOND: Final[int] = 5


@dataclass
class TokenBucket:
    """
    Token bucket implementation for rate limiting.

    Tokens are added at a constant rate up to a maximum capacity.
    Each request consumes one or more tokens.
    """

    capacity: int
    refill_rate: float  # tokens per second
    tokens: float = field(init=False)
    last_refill: int = field(init=False)  # milliseconds
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize with full bucket."""
        self.tokens = float(self.capacity)
        self.last_refill = get_timestamp_ms()

    def _refill(self) -> None:
        """Add tokens based on elapsed time."""
        now = get_timestamp_ms()
        elapsed_seconds = (now - self.last_refill) / 1000.0

        # Add tokens for elapsed time
        self.tokens = min(
            self.capacity,
            self.tokens + (elapsed_seconds * self.refill_rate),
        )
        self.last_refill = now

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens, waiting if necessary.

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            True if tokens were acquired.
        """
        async with self._lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            # Calculate wait time
            tokens_needed = tokens - self.tokens
            wait_seconds = tokens_needed / self.refill_rate

            # Wait and then acquire
            await asyncio.sleep(wait_seconds)
            self._refill()
            self.tokens -= tokens
            return True

    async def try_acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens without waiting.

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            True if tokens were acquired, False if not enough available.
        """
        async with self._lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class RateLimiter:
    """
    Multi-bucket rate limiter for Binance API.

    Manages separate rate limits for:
    - General requests (weight-based)
    - Order requests (count-based)
    """

    def __init__(
        self,
        requests_per_second: int = DEFAULT_REQUESTS_PER_SECOND,
        orders_per_second: int = DEFAULT_ORDERS_PER_SECOND,
        request_weight_per_minute: int = 1200,
    ) -> None:
        """
        Initialize rate limiter with specified limits.

        Args:
            requests_per_second: Maximum general requests per second.
            orders_per_second: Maximum order requests per second.
            request_weight_per_minute: Maximum request weight per minute.
        """
        # Per-second buckets (burst capacity = 2x rate)
        self._request_bucket = TokenBucket(
            capacity=requests_per_second * 2,
            refill_rate=float(requests_per_second),
        )
        self._order_bucket = TokenBucket(
            capacity=orders_per_second * 2,
            refill_rate=float(orders_per_second),
        )

        # Per-minute weight bucket
        self._weight_bucket = TokenBucket(
            capacity=request_weight_per_minute,
            refill_rate=request_weight_per_minute / 60.0,
        )

    async def acquire_request(self, weight: int = 1) -> None:
        """
        Acquire permission for a general API request.

        Args:
            weight: Request weight (varies by endpoint).
        """
        await asyncio.gather(
            self._request_bucket.acquire(1),
            self._weight_bucket.acquire(weight),
        )

    async def acquire_order(self, weight: int = 1) -> None:
        """
        Acquire permission for an order request.

        Args:
            weight: Request weight.
        """
        await asyncio.gather(
            self._order_bucket.acquire(1),
            self._weight_bucket.acquire(weight),
        )

    async def try_acquire_request(self, weight: int = 1) -> bool:
        """
        Try to acquire request permission without waiting.

        Args:
            weight: Request weight.

        Returns:
            True if permission granted.
        """
        request_ok = await self._request_bucket.try_acquire(1)
        if not request_ok:
            return False

        weight_ok = await self._weight_bucket.try_acquire(weight)
        if not weight_ok:
            # Refund the request token
            self._request_bucket.tokens += 1
            return False

        return True

    async def try_acquire_order(self, weight: int = 1) -> bool:
        """
        Try to acquire order permission without waiting.

        Args:
            weight: Request weight.

        Returns:
            True if permission granted.
        """
        order_ok = await self._order_bucket.try_acquire(1)
        if not order_ok:
            return False

        weight_ok = await self._weight_bucket.try_acquire(weight)
        if not weight_ok:
            # Refund the order token
            self._order_bucket.tokens += 1
            return False

        return True

    @property
    def available_requests(self) -> float:
        """Get approximate number of available request tokens."""
        return min(self._request_bucket.tokens, self._weight_bucket.tokens)

    @property
    def available_orders(self) -> float:
        """Get approximate number of available order tokens."""
        return min(self._order_bucket.tokens, self._weight_bucket.tokens)
