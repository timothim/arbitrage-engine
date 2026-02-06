"""
High-precision time utilities.

Provides microsecond-precision timestamps for latency measurement
and trading operations.
"""

import time
from datetime import UTC, datetime


def get_timestamp_us() -> int:
    """
    Get current timestamp in microseconds.

    Uses time.time_ns() for maximum precision, then converts to microseconds.
    This is faster than datetime operations.

    Returns:
        Current Unix timestamp in microseconds.
    """
    return time.time_ns() // 1000


def get_timestamp_ms() -> int:
    """
    Get current timestamp in milliseconds.

    Used for Binance API which expects millisecond timestamps.

    Returns:
        Current Unix timestamp in milliseconds.
    """
    return time.time_ns() // 1_000_000


def us_to_ms(timestamp_us: int) -> int:
    """
    Convert microseconds to milliseconds.

    Args:
        timestamp_us: Timestamp in microseconds.

    Returns:
        Timestamp in milliseconds.
    """
    return timestamp_us // 1000


def format_timestamp_us(timestamp_us: int, include_date: bool = False) -> str:
    """
    Format microsecond timestamp for logging.

    Args:
        timestamp_us: Timestamp in microseconds.
        include_date: Whether to include the date portion.

    Returns:
        Formatted timestamp string with microsecond precision.

    Example:
        >>> format_timestamp_us(1704067200123456)
        '12:00:00.123456'
        >>> format_timestamp_us(1704067200123456, include_date=True)
        '2024-01-01 12:00:00.123456'
    """
    seconds = timestamp_us // 1_000_000
    microseconds = timestamp_us % 1_000_000

    dt = datetime.fromtimestamp(seconds, tz=UTC)

    if include_date:
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{microseconds:06d}"
    return f"{dt.strftime('%H:%M:%S')}.{microseconds:06d}"


def measure_latency_us(start_us: int) -> int:
    """
    Calculate latency from a start timestamp.

    Args:
        start_us: Start timestamp in microseconds.

    Returns:
        Elapsed time in microseconds.
    """
    return get_timestamp_us() - start_us


class LatencyTimer:
    """
    Context manager for measuring operation latency.

    Example:
        >>> with LatencyTimer() as timer:
        ...     do_something()
        >>> print(f"Latency: {timer.latency_us}μs")
    """

    __slots__ = ("start_us", "end_us", "latency_us")

    def __init__(self) -> None:
        self.start_us: int = 0
        self.end_us: int = 0
        self.latency_us: int = 0

    def __enter__(self) -> "LatencyTimer":
        self.start_us = get_timestamp_us()
        return self

    def __exit__(self, *args: object) -> None:
        self.end_us = get_timestamp_us()
        self.latency_us = self.end_us - self.start_us


def format_duration_us(duration_us: int) -> str:
    """
    Format a duration in microseconds for human-readable display.

    Args:
        duration_us: Duration in microseconds.

    Returns:
        Formatted duration string.

    Examples:
        >>> format_duration_us(500)
        '500μs'
        >>> format_duration_us(1500)
        '1.50ms'
        >>> format_duration_us(1500000)
        '1.50s'
    """
    if duration_us < 1000:
        return f"{duration_us}μs"
    elif duration_us < 1_000_000:
        return f"{duration_us / 1000:.2f}ms"
    else:
        return f"{duration_us / 1_000_000:.2f}s"
