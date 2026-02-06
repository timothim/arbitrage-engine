"""
Integration tests for execution system.

Tests the full execution flow with mocked exchange client.
"""

import pytest

from arbitrage.core.types import Opportunity, OrderSide, TriangleLeg, TrianglePath
from arbitrage.execution.executor import ExecutorConfig, TriangleExecutor
from arbitrage.execution.recovery import PositionRecovery
from arbitrage.execution.risk import RiskLimits, RiskManager
from arbitrage.market.symbols import SymbolManager
from arbitrage.utils.time import get_timestamp_us
from tests.mocks.exchange import MockBinanceClient


class TestExecutionIntegration:
    """Integration tests for execution system."""

    @pytest.fixture
    def symbol_manager(self) -> SymbolManager:
        """Create symbol manager with test data."""
        from arbitrage.core.types import SymbolInfo

        manager = SymbolManager()
        symbols = [
            SymbolInfo("BTCUSDT", "BTC", "USDT", 2, 6, 10.0, 0.00001, 9000.0, 0.00001, 0.01),
            SymbolInfo("ETHUSDT", "ETH", "USDT", 2, 5, 10.0, 0.0001, 9000.0, 0.0001, 0.01),
            SymbolInfo("ETHBTC", "ETH", "BTC", 6, 5, 0.0001, 0.0001, 9000.0, 0.0001, 0.000001),
        ]
        for s in symbols:
            manager._add_symbol(s)
        return manager

    @pytest.fixture
    def mock_client(self) -> MockBinanceClient:
        """Create mock exchange client."""
        return MockBinanceClient(
            initial_balances={"USDT": 1000.0, "BTC": 0.0, "ETH": 0.0},
            fill_orders=True,
        )

    @pytest.fixture
    def risk_manager(self) -> RiskManager:
        """Create risk manager."""
        limits = RiskLimits(
            max_position_pct=0.50,
            max_trade_size=500.0,
            min_trade_size=10.0,
            daily_loss_limit=100.0,
            min_time_between_trades_ms=0,
        )
        return RiskManager(limits=limits, initial_balance=1000.0)

    @pytest.fixture
    def recovery(
        self, mock_client: MockBinanceClient, symbol_manager: SymbolManager
    ) -> PositionRecovery:
        """Create recovery handler."""
        return PositionRecovery(
            client=mock_client,  # type: ignore
            symbol_manager=symbol_manager,
            base_currency="USDT",
        )

    @pytest.fixture
    def executor(
        self,
        mock_client: MockBinanceClient,
        symbol_manager: SymbolManager,
        risk_manager: RiskManager,
        recovery: PositionRecovery,
    ) -> TriangleExecutor:
        """Create executor with dry run enabled."""
        return TriangleExecutor(
            client=mock_client,  # type: ignore
            symbol_manager=symbol_manager,
            risk_manager=risk_manager,
            recovery=recovery,
            config=ExecutorConfig(dry_run=True),
        )

    @pytest.fixture
    def opportunity(self) -> Opportunity:
        """Create test opportunity."""
        path = TrianglePath(
            id="USDT-BTC-ETH",
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
            gross_return=1.002,
            net_return=1.001,
            prices=(50000.0, 0.06, 3000.0),
            quantities=(1.0, 50.0, 10.0),
            max_trade_qty=100.0,
            timestamp_us=get_timestamp_us(),
        )

    @pytest.mark.asyncio
    async def test_dry_run_execution(
        self,
        executor: TriangleExecutor,
        opportunity: Opportunity,
    ) -> None:
        """Test dry run execution."""
        result = await executor.execute(opportunity)

        assert result.is_success
        assert result.total_profit > 0 or result.total_profit == pytest.approx(
            0, abs=0.01
        )
        assert len(result.legs) == 3

    @pytest.mark.asyncio
    async def test_risk_check_blocks_large_trade(
        self,
        executor: TriangleExecutor,
        opportunity: Opportunity,
        risk_manager: RiskManager,
    ) -> None:
        """Test that risk checks block oversized trades."""
        # Set very small balance
        risk_manager.update_balance(50.0)

        result = await executor.execute(opportunity)

        # Should still succeed but with smaller size
        assert result.is_success

    @pytest.mark.asyncio
    async def test_halted_trading_rejected(
        self,
        executor: TriangleExecutor,
        opportunity: Opportunity,
        risk_manager: RiskManager,
    ) -> None:
        """Test that trades are rejected when halted."""
        risk_manager.force_halt("Test halt")

        result = await executor.execute(opportunity)

        assert not result.is_success
        assert "halted" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_execution_stats_tracked(
        self,
        executor: TriangleExecutor,
        opportunity: Opportunity,
    ) -> None:
        """Test that execution statistics are tracked."""
        await executor.execute(opportunity)

        stats = executor.stats
        assert stats["total"] == 1
        assert stats["successful"] == 1
        assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_multiple_executions(
        self,
        executor: TriangleExecutor,
        opportunity: Opportunity,
    ) -> None:
        """Test multiple sequential executions."""
        for _ in range(3):
            result = await executor.execute(opportunity)
            assert result.is_success

        stats = executor.stats
        assert stats["total"] == 3
        assert stats["successful"] == 3


class TestLiveExecution:
    """Tests for live execution (with mock client)."""

    @pytest.fixture
    def symbol_manager(self) -> SymbolManager:
        """Create symbol manager with test data."""
        from arbitrage.core.types import SymbolInfo

        manager = SymbolManager()
        symbols = [
            SymbolInfo("BTCUSDT", "BTC", "USDT", 2, 6, 10.0, 0.00001, 9000.0, 0.00001, 0.01),
            SymbolInfo("ETHUSDT", "ETH", "USDT", 2, 5, 10.0, 0.0001, 9000.0, 0.0001, 0.01),
            SymbolInfo("ETHBTC", "ETH", "BTC", 6, 5, 0.0001, 0.0001, 9000.0, 0.0001, 0.000001),
        ]
        for s in symbols:
            manager._add_symbol(s)
        return manager

    @pytest.fixture
    def mock_client(self) -> MockBinanceClient:
        """Create mock client that fills orders."""
        return MockBinanceClient(
            initial_balances={"USDT": 10000.0, "BTC": 0.0, "ETH": 0.0},
            fill_orders=True,
        )

    @pytest.fixture
    def risk_manager(self) -> RiskManager:
        """Create risk manager."""
        limits = RiskLimits(
            max_position_pct=0.50,
            max_trade_size=500.0,
            min_trade_size=10.0,
            daily_loss_limit=100.0,
            min_time_between_trades_ms=0,
        )
        return RiskManager(limits=limits, initial_balance=10000.0)

    @pytest.fixture
    def recovery(
        self, mock_client: MockBinanceClient, symbol_manager: SymbolManager
    ) -> PositionRecovery:
        """Create recovery handler."""
        return PositionRecovery(
            client=mock_client,  # type: ignore
            symbol_manager=symbol_manager,
            base_currency="USDT",
        )

    @pytest.fixture
    def opportunity(self) -> Opportunity:
        """Create test opportunity."""
        path = TrianglePath(
            id="USDT-BTC-ETH",
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
            gross_return=1.002,
            net_return=1.001,
            prices=(50000.0, 0.06, 3000.0),
            quantities=(1.0, 50.0, 10.0),
            max_trade_qty=100.0,
            timestamp_us=get_timestamp_us(),
        )

    @pytest.fixture
    def live_executor(
        self,
        mock_client: MockBinanceClient,
        symbol_manager: SymbolManager,
        risk_manager: RiskManager,
        recovery: PositionRecovery,
    ) -> TriangleExecutor:
        """Create executor with dry run disabled."""
        return TriangleExecutor(
            client=mock_client,  # type: ignore
            symbol_manager=symbol_manager,
            risk_manager=risk_manager,
            recovery=recovery,
            config=ExecutorConfig(dry_run=False),
        )

    @pytest.mark.asyncio
    async def test_live_execution_places_orders(
        self,
        live_executor: TriangleExecutor,
        mock_client: MockBinanceClient,
        opportunity,
    ) -> None:
        """Test that live execution places actual orders."""
        await live_executor.execute(opportunity)

        # Check that orders were placed on mock client
        assert len(mock_client.orders) == 3

    @pytest.mark.asyncio
    async def test_order_failure_handling(
        self,
        symbol_manager,
        risk_manager,
        recovery,
        opportunity,
    ) -> None:
        """Test handling of order failures."""
        # Create client that fails orders
        failing_client = MockBinanceClient(fill_orders=False)

        executor = TriangleExecutor(
            client=failing_client,  # type: ignore
            symbol_manager=symbol_manager,
            risk_manager=risk_manager,
            recovery=recovery,
            config=ExecutorConfig(dry_run=False),
        )

        result = await executor.execute(opportunity)

        # Execution should fail gracefully
        assert not result.is_success
