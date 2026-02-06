"""
Opportunity detection and management.

Provides real-time scanning for profitable arbitrage opportunities
based on current market data.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from arbitrage.core.types import BBO, Opportunity, TrianglePath
from arbitrage.market.orderbook import OrderbookManager
from arbitrage.strategy.calculator import ArbitrageCalculator
from arbitrage.utils.time import get_timestamp_us


logger = logging.getLogger(__name__)


# Type alias for opportunity callbacks
OpportunityCallback = Callable[[Opportunity], None]


@dataclass
class OpportunityStats:
    """Statistics for opportunity detection."""

    total_scans: int = 0
    opportunities_found: int = 0
    opportunities_profitable: int = 0
    opportunities_executed: int = 0
    best_profit_pct: float = 0.0
    worst_profit_pct: float = 0.0
    avg_profit_pct: float = 0.0
    _profit_sum: float = field(default=0.0, repr=False)

    def record_opportunity(self, profit_pct: float, executed: bool = False) -> None:
        """Record an opportunity."""
        self.opportunities_found += 1

        if profit_pct > 0:
            self.opportunities_profitable += 1
            self._profit_sum += profit_pct
            self.avg_profit_pct = self._profit_sum / self.opportunities_profitable

        if profit_pct > self.best_profit_pct:
            self.best_profit_pct = profit_pct

        if profit_pct < self.worst_profit_pct or self.worst_profit_pct == 0:
            self.worst_profit_pct = profit_pct

        if executed:
            self.opportunities_executed += 1


class OpportunityDetector:
    """
    Detects arbitrage opportunities from market data.

    Features:
    - Event-driven scanning on price updates
    - Pre-computed triangle paths for O(1) lookup
    - Configurable profit thresholds
    - Callback-based notification
    """

    def __init__(
        self,
        calculator: ArbitrageCalculator,
        orderbook: OrderbookManager,
        triangles: list[TrianglePath],
        min_profit_threshold: float = 0.0005,
        max_opportunities_per_scan: int = 10,
    ) -> None:
        """
        Initialize opportunity detector.

        Args:
            calculator: Arbitrage calculator instance.
            orderbook: Orderbook manager for price data.
            triangles: Pre-computed triangle paths.
            min_profit_threshold: Minimum profit % to consider.
            max_opportunities_per_scan: Max opportunities to return per scan.
        """
        self._calculator = calculator
        self._orderbook = orderbook
        self._triangles = triangles
        self._min_profit_threshold = min_profit_threshold
        self._max_opportunities = max_opportunities_per_scan

        # Index triangles by symbol for efficient lookup
        self._triangles_by_symbol: dict[str, list[TrianglePath]] = {}
        self._build_symbol_index()

        # Callbacks and stats
        self._callbacks: list[OpportunityCallback] = []
        self._stats = OpportunityStats()

        # Cooldown tracking to prevent spam
        self._last_opportunity_time: dict[str, int] = {}
        self._cooldown_us = 100_000  # 100ms cooldown per triangle

    def _build_symbol_index(self) -> None:
        """Build index of triangles by symbol."""
        for triangle in self._triangles:
            for symbol in triangle.symbols:
                if symbol not in self._triangles_by_symbol:
                    self._triangles_by_symbol[symbol] = []
                self._triangles_by_symbol[symbol].append(triangle)

    def register_callback(self, callback: OpportunityCallback) -> None:
        """Register callback for opportunity notifications."""
        self._callbacks.append(callback)

    def unregister_callback(self, callback: OpportunityCallback) -> None:
        """Unregister a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify_callbacks(self, opportunity: Opportunity) -> None:
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback(opportunity)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def on_price_update(self, bbo: BBO) -> list[Opportunity]:
        """
        Handle price update and check for opportunities.

        This is the hot path - optimized for minimal latency.

        Args:
            bbo: Updated BBO data.

        Returns:
            List of detected opportunities.
        """
        self._stats.total_scans += 1

        # Get triangles affected by this symbol
        triangles = self._triangles_by_symbol.get(bbo.symbol, [])
        if not triangles:
            return []

        timestamp = get_timestamp_us()
        opportunities: list[Opportunity] = []

        for triangle in triangles:
            # Check cooldown
            last_time = self._last_opportunity_time.get(triangle.id, 0)
            if timestamp - last_time < self._cooldown_us:
                continue

            # Check if we have all prices
            if not self._orderbook.has_all_symbols(triangle.symbols):
                continue

            # Calculate opportunity
            opportunity = self._calculator.calculate_opportunity(
                triangle, self._orderbook
            )

            if opportunity and opportunity.profit_pct >= self._min_profit_threshold * 100:
                opportunities.append(opportunity)
                self._stats.record_opportunity(opportunity.profit_pct)
                self._last_opportunity_time[triangle.id] = timestamp

                # Notify callbacks
                self._notify_callbacks(opportunity)

                if len(opportunities) >= self._max_opportunities:
                    break

        # Sort by profit (descending)
        opportunities.sort(key=lambda x: x.profit_pct, reverse=True)

        return opportunities

    def scan_all(self) -> list[Opportunity]:
        """
        Scan all triangles for opportunities.

        More expensive than event-driven scanning.
        Use for initial state or periodic full scans.

        Returns:
            List of all profitable opportunities.
        """
        self._stats.total_scans += 1
        opportunities: list[Opportunity] = []

        for triangle in self._triangles:
            # Check if we have all prices
            if not self._orderbook.has_all_symbols(triangle.symbols):
                continue

            # Calculate opportunity
            opportunity = self._calculator.calculate_opportunity(
                triangle, self._orderbook
            )

            if opportunity and opportunity.profit_pct >= self._min_profit_threshold * 100:
                opportunities.append(opportunity)
                self._stats.record_opportunity(opportunity.profit_pct)

        # Sort by profit (descending)
        opportunities.sort(key=lambda x: x.profit_pct, reverse=True)

        return opportunities[:self._max_opportunities]

    def get_best_opportunity(self) -> Opportunity | None:
        """
        Get the single best opportunity.

        Returns:
            Best opportunity or None.
        """
        opportunities = self.scan_all()
        return opportunities[0] if opportunities else None

    @property
    def stats(self) -> OpportunityStats:
        """Get detection statistics."""
        return self._stats

    @property
    def triangle_count(self) -> int:
        """Get number of monitored triangles."""
        return len(self._triangles)

    def set_min_profit_threshold(self, threshold: float) -> None:
        """Update minimum profit threshold."""
        self._min_profit_threshold = threshold

    def reset_stats(self) -> None:
        """Reset detection statistics."""
        self._stats = OpportunityStats()
        self._last_opportunity_time.clear()
