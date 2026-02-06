"""
Risk management for arbitrage execution.

Provides pre-trade risk checks, position limits, and
daily loss tracking to protect against excessive losses.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from arbitrage.core.types import Opportunity
from arbitrage.utils.time import get_timestamp_ms


logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    """Current risk management state."""

    daily_pnl: float = 0.0
    daily_trades: int = 0
    open_positions: int = 0
    last_trade_time_ms: int = 0
    current_date: date = field(default_factory=date.today)
    is_halted: bool = False
    halt_reason: str = ""

    def reset_daily(self) -> None:
        """Reset daily counters."""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.current_date = date.today()
        if self.halt_reason.startswith("Daily"):
            self.is_halted = False
            self.halt_reason = ""


@dataclass
class RiskLimits:
    """Risk limit configuration."""

    max_position_pct: float = 0.20  # 20% of balance
    max_trade_size: float = 1000.0  # Max size in base currency
    min_trade_size: float = 10.0  # Min size in base currency
    daily_loss_limit: float = 50.0  # Max daily loss
    max_daily_trades: int = 1000  # Max trades per day
    max_concurrent_positions: int = 1  # Max open positions
    min_time_between_trades_ms: int = 100  # Cooldown between trades
    max_hold_time_ms: int = 5000  # Max time to hold position


class RiskCheckResult:
    """Result of a risk check."""

    __slots__ = ("passed", "reason", "adjusted_size")

    def __init__(
        self,
        passed: bool,
        reason: str = "",
        adjusted_size: float | None = None,
    ) -> None:
        self.passed = passed
        self.reason = reason
        self.adjusted_size = adjusted_size

    def __bool__(self) -> bool:
        return self.passed


class RiskManager:
    """
    Manages trading risk and position limits.

    Features:
    - Pre-trade risk validation
    - Position size limits
    - Daily loss tracking
    - Trade frequency limits
    - Automatic halt on limit breach
    """

    def __init__(
        self,
        limits: RiskLimits | None = None,
        initial_balance: float = 0.0,
    ) -> None:
        """
        Initialize risk manager.

        Args:
            limits: Risk limit configuration.
            initial_balance: Starting balance in base currency.
        """
        self._limits = limits or RiskLimits()
        self._state = RiskState()
        self._balance = initial_balance

    def update_balance(self, balance: float) -> None:
        """Update current balance."""
        self._balance = balance

    def check_trade(
        self,
        opportunity: Opportunity,
        trade_size: float,
    ) -> RiskCheckResult:
        """
        Perform pre-trade risk checks.

        Args:
            opportunity: Detected opportunity.
            trade_size: Proposed trade size in base currency.

        Returns:
            RiskCheckResult with pass/fail and reason.
        """
        # Check for daily reset
        if date.today() != self._state.current_date:
            self._state.reset_daily()

        # Check if trading is halted
        if self._state.is_halted:
            return RiskCheckResult(False, f"Trading halted: {self._state.halt_reason}")

        # Check daily loss limit
        if self._state.daily_pnl <= -self._limits.daily_loss_limit:
            self._halt("Daily loss limit reached")
            return RiskCheckResult(False, "Daily loss limit reached")

        # Check daily trade count
        if self._state.daily_trades >= self._limits.max_daily_trades:
            return RiskCheckResult(False, "Daily trade limit reached")

        # Check concurrent positions
        if self._state.open_positions >= self._limits.max_concurrent_positions:
            return RiskCheckResult(False, "Max concurrent positions reached")

        # Check trade cooldown
        now = get_timestamp_ms()
        time_since_last = now - self._state.last_trade_time_ms
        if time_since_last < self._limits.min_time_between_trades_ms:
            return RiskCheckResult(
                False,
                f"Cooldown: {self._limits.min_time_between_trades_ms - time_since_last}ms remaining",
            )

        # Validate and adjust trade size
        adjusted_size = self._validate_trade_size(trade_size)
        if adjusted_size is None:
            return RiskCheckResult(False, "Trade size outside limits")

        # Check minimum profit expectation
        expected_profit = adjusted_size * (opportunity.net_return - 1.0)
        if expected_profit < 0:
            return RiskCheckResult(False, "Negative expected profit")

        return RiskCheckResult(True, adjusted_size=adjusted_size)

    def _validate_trade_size(self, size: float) -> float | None:
        """
        Validate and adjust trade size to limits.

        Args:
            size: Proposed trade size.

        Returns:
            Adjusted size or None if invalid.
        """
        # Check minimum
        if size < self._limits.min_trade_size:
            return None

        # Apply maximum limits
        max_by_pct = self._balance * self._limits.max_position_pct
        max_size = min(self._limits.max_trade_size, max_by_pct)

        if size > max_size:
            size = max_size

        # Re-check minimum after adjustment
        if size < self._limits.min_trade_size:
            return None

        return size

    def record_trade_start(self) -> None:
        """Record that a trade has started."""
        self._state.open_positions += 1
        self._state.last_trade_time_ms = get_timestamp_ms()

    def record_trade_complete(self, pnl: float) -> None:
        """
        Record trade completion.

        Args:
            pnl: Profit/loss from the trade.
        """
        self._state.open_positions = max(0, self._state.open_positions - 1)
        self._state.daily_trades += 1
        self._state.daily_pnl += pnl

        # Check if we need to halt
        if self._state.daily_pnl <= -self._limits.daily_loss_limit:
            self._halt("Daily loss limit reached")

        logger.info(
            f"Trade complete: PnL={pnl:.4f}, Daily PnL={self._state.daily_pnl:.4f}, "
            f"Trades today={self._state.daily_trades}"
        )

    def record_trade_failed(self) -> None:
        """Record that a trade failed to execute."""
        self._state.open_positions = max(0, self._state.open_positions - 1)

    def _halt(self, reason: str) -> None:
        """Halt trading with reason."""
        self._state.is_halted = True
        self._state.halt_reason = reason
        logger.warning(f"Trading halted: {reason}")

    def resume(self) -> bool:
        """
        Resume trading if possible.

        Returns:
            True if trading resumed.
        """
        if self._state.daily_pnl <= -self._limits.daily_loss_limit:
            logger.warning("Cannot resume: daily loss limit still breached")
            return False

        self._state.is_halted = False
        self._state.halt_reason = ""
        logger.info("Trading resumed")
        return True

    def force_halt(self, reason: str) -> None:
        """Force trading halt."""
        self._halt(f"Manual: {reason}")

    @property
    def state(self) -> RiskState:
        """Get current risk state."""
        return self._state

    @property
    def limits(self) -> RiskLimits:
        """Get risk limits."""
        return self._limits

    @property
    def is_trading_allowed(self) -> bool:
        """Check if trading is currently allowed."""
        return not self._state.is_halted

    @property
    def available_capacity(self) -> int:
        """Get number of additional positions allowed."""
        return self._limits.max_concurrent_positions - self._state.open_positions

    def get_max_trade_size(self) -> float:
        """Get maximum allowed trade size."""
        max_by_pct = self._balance * self._limits.max_position_pct
        return min(self._limits.max_trade_size, max_by_pct)

    def to_dict(self) -> dict[str, float | int | bool | str]:
        """Convert state to dict for logging."""
        return {
            "daily_pnl": self._state.daily_pnl,
            "daily_trades": self._state.daily_trades,
            "open_positions": self._state.open_positions,
            "is_halted": self._state.is_halted,
            "halt_reason": self._state.halt_reason,
            "balance": self._balance,
            "max_trade_size": self.get_max_trade_size(),
        }
