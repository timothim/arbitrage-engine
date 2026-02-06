"""
Metrics collection for performance monitoring.

Tracks latencies, counters, and trading statistics
with efficient in-memory storage.
"""

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class LatencyStats:
    """Aggregated latency statistics."""

    min_us: int = 0
    max_us: int = 0
    avg_us: float = 0.0
    p50_us: int = 0
    p95_us: int = 0
    p99_us: int = 0
    count: int = 0


@dataclass
class TradingStats:
    """Trading performance statistics."""

    opportunities_found: int = 0
    opportunities_profitable: int = 0
    opportunities_executed: int = 0
    executions_successful: int = 0
    executions_failed: int = 0
    total_profit: float = 0.0
    total_commission: float = 0.0
    best_profit_pct: float = 0.0

    @property
    def net_profit(self) -> float:
        """Calculate net profit after commissions."""
        return self.total_profit - self.total_commission

    @property
    def execution_success_rate(self) -> float:
        """Calculate execution success rate."""
        total = self.executions_successful + self.executions_failed
        return self.executions_successful / total if total > 0 else 0.0


class MetricsCollector:
    """
    Collects and aggregates performance metrics.

    Features:
    - Rolling window latency tracking
    - Counter-based event tracking
    - P&L accumulation
    - Thread-safe operations
    """

    def __init__(
        self,
        latency_window_size: int = 1000,
    ) -> None:
        """
        Initialize metrics collector.

        Args:
            latency_window_size: Number of samples to keep for latency stats.
        """
        self._window_size = latency_window_size
        self._latencies: dict[str, deque[int]] = {}
        self._counters: dict[str, int] = {}
        self._trading_stats = TradingStats()
        self._start_time = time.time()

    def record_latency(self, name: str, latency_us: int) -> None:
        """
        Record a latency measurement.

        Args:
            name: Metric name (e.g., "tick_to_calc", "order_to_fill").
            latency_us: Latency in microseconds.
        """
        if name not in self._latencies:
            self._latencies[name] = deque(maxlen=self._window_size)

        self._latencies[name].append(latency_us)

    def increment_counter(self, name: str, value: int = 1) -> None:
        """
        Increment a counter.

        Args:
            name: Counter name.
            value: Amount to increment.
        """
        self._counters[name] = self._counters.get(name, 0) + value

    def get_counter(self, name: str) -> int:
        """Get counter value."""
        return self._counters.get(name, 0)

    def record_opportunity(self, profit_pct: float, executed: bool = False) -> None:
        """
        Record an opportunity detection.

        Args:
            profit_pct: Profit percentage.
            executed: Whether opportunity was executed.
        """
        self._trading_stats.opportunities_found += 1

        if profit_pct > 0:
            self._trading_stats.opportunities_profitable += 1

        if profit_pct > self._trading_stats.best_profit_pct:
            self._trading_stats.best_profit_pct = profit_pct

        if executed:
            self._trading_stats.opportunities_executed += 1

    def record_execution(self, success: bool, profit: float, commission: float) -> None:
        """
        Record an execution result.

        Args:
            success: Whether execution succeeded.
            profit: Profit/loss amount.
            commission: Commission paid.
        """
        if success:
            self._trading_stats.executions_successful += 1
        else:
            self._trading_stats.executions_failed += 1

        self._trading_stats.total_profit += profit
        self._trading_stats.total_commission += commission

    def record_profit(self, amount: float) -> None:
        """Record a profit amount."""
        self._trading_stats.total_profit += amount

    def get_latency_stats(self, name: str) -> LatencyStats:
        """
        Get latency statistics for a metric.

        Args:
            name: Metric name.

        Returns:
            LatencyStats with aggregated values.
        """
        samples = self._latencies.get(name)
        if not samples or len(samples) == 0:
            return LatencyStats()

        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        return LatencyStats(
            min_us=sorted_samples[0],
            max_us=sorted_samples[-1],
            avg_us=sum(sorted_samples) / n,
            p50_us=sorted_samples[n // 2],
            p95_us=sorted_samples[int(n * 0.95)],
            p99_us=sorted_samples[int(n * 0.99)] if n > 1 else sorted_samples[-1],
            count=n,
        )

    def get_all_latency_stats(self) -> dict[str, LatencyStats]:
        """Get latency stats for all metrics."""
        return {name: self.get_latency_stats(name) for name in self._latencies}

    @property
    def trading_stats(self) -> TradingStats:
        """Get trading statistics."""
        return self._trading_stats

    @property
    def uptime_seconds(self) -> float:
        """Get uptime in seconds."""
        return time.time() - self._start_time

    def get_rates(self) -> dict[str, float]:
        """
        Calculate per-minute rates for counters.

        Returns:
            Dict of counter -> rate per minute.
        """
        minutes = self.uptime_seconds / 60
        if minutes == 0:
            return {}

        return {
            f"{name}_per_min": count / minutes
            for name, count in self._counters.items()
        }

    def to_dict(self) -> dict[str, object]:
        """
        Export all metrics as a dict.

        Returns:
            Dict representation of all metrics.
        """
        return {
            "uptime_seconds": self.uptime_seconds,
            "counters": dict(self._counters),
            "latencies": {
                name: {
                    "min": stats.min_us,
                    "max": stats.max_us,
                    "avg": stats.avg_us,
                    "p50": stats.p50_us,
                    "p99": stats.p99_us,
                    "count": stats.count,
                }
                for name, stats in self.get_all_latency_stats().items()
            },
            "trading": {
                "opportunities_found": self._trading_stats.opportunities_found,
                "opportunities_profitable": self._trading_stats.opportunities_profitable,
                "opportunities_executed": self._trading_stats.opportunities_executed,
                "executions_successful": self._trading_stats.executions_successful,
                "executions_failed": self._trading_stats.executions_failed,
                "total_profit": self._trading_stats.total_profit,
                "total_commission": self._trading_stats.total_commission,
                "net_profit": self._trading_stats.net_profit,
            },
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self._latencies.clear()
        self._counters.clear()
        self._trading_stats = TradingStats()
        self._start_time = time.time()


class SlidingWindowCounter:
    """
    Counter with sliding time window.

    Tracks counts over a rolling time period.
    """

    def __init__(self, window_seconds: float = 60.0) -> None:
        """
        Initialize sliding window counter.

        Args:
            window_seconds: Size of the time window.
        """
        self._window_seconds = window_seconds
        self._events: deque[float] = deque()

    def increment(self) -> None:
        """Record an event at current time."""
        now = time.time()
        self._events.append(now)
        self._prune(now)

    def _prune(self, now: float) -> None:
        """Remove events outside the window."""
        cutoff = now - self._window_seconds
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    def count(self) -> int:
        """Get count of events in window."""
        self._prune(time.time())
        return len(self._events)

    def rate_per_second(self) -> float:
        """Get rate per second."""
        return self.count() / self._window_seconds
