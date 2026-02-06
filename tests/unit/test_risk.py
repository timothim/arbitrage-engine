"""
Unit tests for RiskManager.

Tests risk checks, position limits, and trading halts.
"""

from datetime import date

import pytest

from arbitrage.core.types import Opportunity, OrderSide, TriangleLeg, TrianglePath
from arbitrage.execution.risk import RiskLimits, RiskManager, RiskState
from arbitrage.utils.time import get_timestamp_us


class TestRiskLimits:
    """Tests for RiskLimits dataclass."""

    def test_default_limits(self) -> None:
        """Test default limit values."""
        limits = RiskLimits()

        assert limits.max_position_pct == 0.20
        assert limits.max_trade_size == 1000.0
        assert limits.min_trade_size == 10.0
        assert limits.daily_loss_limit == 50.0
        assert limits.max_daily_trades == 1000
        assert limits.max_concurrent_positions == 1

    def test_custom_limits(self) -> None:
        """Test custom limit values."""
        limits = RiskLimits(
            max_position_pct=0.10,
            max_trade_size=500.0,
            daily_loss_limit=100.0,
        )

        assert limits.max_position_pct == 0.10
        assert limits.max_trade_size == 500.0
        assert limits.daily_loss_limit == 100.0


class TestRiskState:
    """Tests for RiskState dataclass."""

    def test_default_state(self) -> None:
        """Test default state values."""
        state = RiskState()

        assert state.daily_pnl == 0.0
        assert state.daily_trades == 0
        assert state.open_positions == 0
        assert state.is_halted is False

    def test_reset_daily(self) -> None:
        """Test daily reset."""
        state = RiskState(
            daily_pnl=-25.0,
            daily_trades=50,
            is_halted=True,
            halt_reason="Daily loss limit reached",
        )

        state.reset_daily()

        assert state.daily_pnl == 0.0
        assert state.daily_trades == 0
        assert state.is_halted is False
        assert state.halt_reason == ""


class TestRiskManager:
    """Tests for RiskManager."""

    @pytest.fixture
    def risk_manager(self) -> RiskManager:
        """Create a risk manager with test limits."""
        limits = RiskLimits(
            max_position_pct=0.20,
            max_trade_size=100.0,
            min_trade_size=10.0,
            daily_loss_limit=50.0,
            max_daily_trades=100,
            max_concurrent_positions=2,
            min_time_between_trades_ms=100,
        )
        manager = RiskManager(limits=limits, initial_balance=1000.0)
        return manager

    @pytest.fixture
    def opportunity(self) -> Opportunity:
        """Create a test opportunity."""
        path = TrianglePath(
            id="test",
            base_asset="USDT",
            legs=(
                TriangleLeg("BTCUSDT", OrderSide.BUY, "USDT", "BTC"),
                TriangleLeg("ETHBTC", OrderSide.BUY, "BTC", "ETH"),
                TriangleLeg("ETHUSDT", OrderSide.SELL, "ETH", "USDT"),
            ),
        )
        return Opportunity(
            path=path,
            profit_pct=0.1,
            gross_return=1.001,
            net_return=1.0007,
            prices=(50000.0, 0.06, 3000.0),
            quantities=(1.0, 50.0, 10.0),
            max_trade_qty=100.0,
            timestamp_us=get_timestamp_us(),
        )

    def test_check_trade_passes(self, risk_manager: RiskManager, opportunity: Opportunity) -> None:
        """Test that valid trade passes checks."""
        result = risk_manager.check_trade(opportunity, trade_size=50.0)

        assert result.passed
        assert result.adjusted_size is not None
        assert result.adjusted_size == 50.0

    def test_check_trade_size_adjustment(
        self, risk_manager: RiskManager, opportunity: Opportunity
    ) -> None:
        """Test that oversized trade is adjusted."""
        # Request size larger than max
        result = risk_manager.check_trade(opportunity, trade_size=500.0)

        assert result.passed
        # Should be capped at min(100.0, 1000 * 0.20) = 100.0
        assert result.adjusted_size == 100.0

    def test_check_trade_too_small(
        self, risk_manager: RiskManager, opportunity: Opportunity
    ) -> None:
        """Test that too-small trade is rejected."""
        result = risk_manager.check_trade(opportunity, trade_size=5.0)

        assert not result.passed
        assert "limits" in result.reason.lower()

    def test_check_trade_when_halted(
        self, risk_manager: RiskManager, opportunity: Opportunity
    ) -> None:
        """Test that trades are rejected when halted."""
        risk_manager.force_halt("Test halt")

        result = risk_manager.check_trade(opportunity, trade_size=50.0)

        assert not result.passed
        assert "halted" in result.reason.lower()

    def test_check_trade_daily_loss_limit(
        self, risk_manager: RiskManager, opportunity: Opportunity
    ) -> None:
        """Test daily loss limit enforcement."""
        # Simulate losses
        risk_manager._state.daily_pnl = -50.0

        result = risk_manager.check_trade(opportunity, trade_size=50.0)

        assert not result.passed
        assert "loss limit" in result.reason.lower()

    def test_check_trade_max_positions(
        self, risk_manager: RiskManager, opportunity: Opportunity
    ) -> None:
        """Test max concurrent positions."""
        # Simulate max positions open
        risk_manager._state.open_positions = 2

        result = risk_manager.check_trade(opportunity, trade_size=50.0)

        assert not result.passed
        assert "position" in result.reason.lower()

    def test_check_trade_cooldown(
        self, risk_manager: RiskManager, opportunity: Opportunity
    ) -> None:
        """Test trade cooldown enforcement."""
        from arbitrage.utils.time import get_timestamp_ms

        # Set last trade time to now
        risk_manager._state.last_trade_time_ms = get_timestamp_ms()

        result = risk_manager.check_trade(opportunity, trade_size=50.0)

        assert not result.passed
        assert "cooldown" in result.reason.lower()

    def test_record_trade_complete(self, risk_manager: RiskManager) -> None:
        """Test recording completed trade."""
        risk_manager.record_trade_start()
        risk_manager.record_trade_complete(pnl=5.0)

        assert risk_manager.state.daily_trades == 1
        assert risk_manager.state.daily_pnl == 5.0
        assert risk_manager.state.open_positions == 0

    def test_record_trade_triggers_halt(self, risk_manager: RiskManager) -> None:
        """Test that large loss triggers halt."""
        risk_manager.record_trade_start()
        risk_manager.record_trade_complete(pnl=-50.0)

        assert risk_manager.state.is_halted
        assert "loss limit" in risk_manager.state.halt_reason.lower()

    def test_record_trade_failed(self, risk_manager: RiskManager) -> None:
        """Test recording failed trade."""
        risk_manager.record_trade_start()
        assert risk_manager.state.open_positions == 1

        risk_manager.record_trade_failed()
        assert risk_manager.state.open_positions == 0

    def test_resume_trading(self, risk_manager: RiskManager) -> None:
        """Test resuming trading after halt."""
        risk_manager.force_halt("Test")
        assert risk_manager.state.is_halted

        success = risk_manager.resume()
        assert success
        assert not risk_manager.state.is_halted

    def test_resume_blocked_by_loss_limit(self, risk_manager: RiskManager) -> None:
        """Test that resume fails if loss limit still breached."""
        risk_manager._state.daily_pnl = -60.0
        risk_manager.force_halt("Loss")

        success = risk_manager.resume()
        assert not success
        assert risk_manager.state.is_halted

    def test_update_balance(self, risk_manager: RiskManager) -> None:
        """Test balance update."""
        risk_manager.update_balance(2000.0)

        max_size = risk_manager.get_max_trade_size()
        # min(100.0, 2000 * 0.20) = 100.0 (limited by max_trade_size)
        assert max_size == 100.0

    def test_get_max_trade_size(self, risk_manager: RiskManager) -> None:
        """Test max trade size calculation."""
        max_size = risk_manager.get_max_trade_size()

        # min(100.0, 1000 * 0.20) = 100.0
        assert max_size == 100.0

    def test_daily_reset_on_new_day(
        self, risk_manager: RiskManager, opportunity: Opportunity
    ) -> None:
        """Test that daily counters reset on new day."""
        risk_manager._state.daily_trades = 50
        risk_manager._state.daily_pnl = -25.0
        risk_manager._state.current_date = date(2020, 1, 1)

        # Check trade should trigger daily reset
        risk_manager.check_trade(opportunity, trade_size=50.0)

        assert risk_manager.state.daily_trades == 0
        assert risk_manager.state.daily_pnl == 0.0

    def test_to_dict(self, risk_manager: RiskManager) -> None:
        """Test serialization to dict."""
        result = risk_manager.to_dict()

        assert "daily_pnl" in result
        assert "daily_trades" in result
        assert "open_positions" in result
        assert "is_halted" in result
        assert "balance" in result
        assert "max_trade_size" in result
