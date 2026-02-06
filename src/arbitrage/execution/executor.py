"""
Triangle execution engine.

Handles the atomic-like execution of triangular arbitrage
opportunities with concurrent order placement.
"""

import asyncio
import logging
from dataclasses import dataclass

from arbitrage.core.types import (
    ExecutionResult,
    ExecutionStatus,
    LegResult,
    Opportunity,
    OrderSide,
    OrderStatus,
    TriangleLeg,
)
from arbitrage.exchange.client import BinanceClient
from arbitrage.exchange.models import OrderResponse
from arbitrage.execution.recovery import PositionRecovery, RecoveryResult
from arbitrage.execution.risk import RiskManager
from arbitrage.market.symbols import SymbolManager
from arbitrage.utils.time import LatencyTimer, get_timestamp_us


logger = logging.getLogger(__name__)


@dataclass
class ExecutorConfig:
    """Executor configuration."""

    use_market_orders: bool = False  # Use market vs limit IOC
    slippage_buffer: float = 0.0001  # 0.01% price buffer
    order_timeout_ms: int = 5000  # Order timeout
    dry_run: bool = True  # Simulate orders


class TriangleExecutor:
    """
    Executes triangular arbitrage opportunities.

    Features:
    - Concurrent "fire-and-forget" order placement
    - Automatic position recovery on failures
    - Integrated risk management
    - Dry-run simulation mode
    """

    def __init__(
        self,
        client: BinanceClient,
        symbol_manager: SymbolManager,
        risk_manager: RiskManager,
        recovery: PositionRecovery,
        config: ExecutorConfig | None = None,
    ) -> None:
        """
        Initialize executor.

        Args:
            client: Exchange client.
            symbol_manager: Symbol information.
            risk_manager: Risk management.
            recovery: Position recovery handler.
            config: Executor configuration.
        """
        self._client = client
        self._symbol_manager = symbol_manager
        self._risk_manager = risk_manager
        self._recovery = recovery
        self._config = config or ExecutorConfig()

        # Statistics
        self._total_executions = 0
        self._successful_executions = 0
        self._failed_executions = 0

    async def execute(self, opportunity: Opportunity) -> ExecutionResult:
        """
        Execute a triangular arbitrage opportunity.

        Args:
            opportunity: Opportunity to execute.

        Returns:
            ExecutionResult with outcome.
        """
        start_time = get_timestamp_us()
        self._total_executions += 1

        # Pre-execution risk check
        trade_size = opportunity.max_trade_qty
        risk_check = self._risk_manager.check_trade(opportunity, trade_size)

        if not risk_check:
            return self._create_failed_result(
                opportunity,
                f"Risk check failed: {risk_check.reason}",
                start_time,
            )

        # Use adjusted size from risk check
        if risk_check.adjusted_size:
            trade_size = risk_check.adjusted_size

        # Record trade start
        self._risk_manager.record_trade_start()

        try:
            if self._config.dry_run:
                result = await self._execute_dry_run(opportunity, trade_size, start_time)
            else:
                result = await self._execute_live(opportunity, trade_size, start_time)

            # Record completion
            if result.is_success:
                self._successful_executions += 1
                self._risk_manager.record_trade_complete(result.total_profit)
            else:
                self._failed_executions += 1
                self._risk_manager.record_trade_failed()

                # Attempt recovery
                if result.status != ExecutionStatus.SUCCESS:
                    recovery_result = await self._recovery.analyze_and_recover(result)
                    if recovery_result:
                        self._log_recovery(recovery_result)

            return result

        except Exception as e:
            self._failed_executions += 1
            self._risk_manager.record_trade_failed()
            logger.error(f"Execution error: {e}")
            return self._create_failed_result(opportunity, str(e), start_time)

    async def _execute_live(
        self,
        opportunity: Opportunity,
        trade_size: float,
        start_time: int,
    ) -> ExecutionResult:
        """Execute live orders concurrently."""
        path = opportunity.path
        prices = opportunity.prices

        # Calculate quantities for each leg
        quantities = self._calculate_leg_quantities(opportunity, trade_size)

        # Build order tasks
        tasks = []
        for i, leg in enumerate(path.legs):
            price = prices[i] if not self._config.use_market_orders else None
            qty = quantities[i]

            if price:
                # Apply slippage buffer
                price = self._apply_slippage(price, leg.side)

            task = self._place_leg_order(leg, qty, price)
            tasks.append(task)

        # Fire all orders concurrently
        logger.info(f"Executing triangle {path.id} with size {trade_size:.4f}")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        leg_results = self._process_order_results(path.legs, results)
        end_time = get_timestamp_us()

        # Determine overall status
        status = self._determine_status(leg_results)

        # Calculate P&L
        total_profit, total_commission = self._calculate_pnl(leg_results)

        return ExecutionResult(
            opportunity=opportunity,
            status=status,
            legs=leg_results,
            total_profit=total_profit,
            total_commission=total_commission,
            start_timestamp_us=start_time,
            end_timestamp_us=end_time,
        )

    async def _execute_dry_run(
        self,
        opportunity: Opportunity,
        trade_size: float,
        start_time: int,
    ) -> ExecutionResult:
        """Simulate execution without placing real orders."""
        path = opportunity.path
        prices = opportunity.prices
        quantities = self._calculate_leg_quantities(opportunity, trade_size)

        # Simulate leg results
        leg_results: list[LegResult] = []
        for i, leg in enumerate(path.legs):
            # Simulate successful fill
            leg_result = LegResult(
                leg=leg,
                status=OrderStatus.FILLED,
                order_id=f"DRY_{i}_{start_time}",
                filled_qty=quantities[i],
                filled_price=prices[i],
                commission=quantities[i] * prices[i] * 0.001,  # 0.1% fee
                commission_asset="BNB",
                latency_us=500,  # Simulated latency
            )
            leg_results.append(leg_result)

        # Simulate network delay
        await asyncio.sleep(0.001)

        end_time = get_timestamp_us()

        # Calculate simulated P&L
        expected_profit = trade_size * (opportunity.net_return - 1.0)
        total_commission = sum(r.commission for r in leg_results)

        logger.info(
            f"[DRY RUN] Triangle {path.id}: "
            f"Size={trade_size:.4f}, Profit={expected_profit:.6f}, "
            f"Return={opportunity.profit_pct:.4f}%"
        )

        return ExecutionResult(
            opportunity=opportunity,
            status=ExecutionStatus.SUCCESS,
            legs=tuple(leg_results),  # type: ignore
            total_profit=expected_profit,
            total_commission=total_commission,
            start_timestamp_us=start_time,
            end_timestamp_us=end_time,
        )

    async def _place_leg_order(
        self,
        leg: TriangleLeg,
        quantity: float,
        price: float | None,
    ) -> OrderResponse | Exception:
        """Place a single leg order."""
        with LatencyTimer() as timer:
            try:
                # Get symbol info for quantity normalization
                symbol_info = self._symbol_manager.get(leg.symbol)
                if symbol_info:
                    quantity = symbol_info.round_quantity(quantity)
                    if price:
                        price = symbol_info.round_price(price)

                if price and not self._config.use_market_orders:
                    response = await self._client.place_limit_order(
                        symbol=leg.symbol,
                        side=leg.side,
                        quantity=quantity,
                        price=price,
                    )
                else:
                    response = await self._client.place_market_order(
                        symbol=leg.symbol,
                        side=leg.side,
                        quantity=quantity,
                    )

                logger.debug(
                    f"Leg {leg.symbol} {leg.side.value}: "
                    f"qty={quantity}, status={response.status}, "
                    f"latency={timer.latency_us}μs"
                )
                return response

            except Exception as e:
                logger.error(f"Order failed for {leg.symbol}: {e}")
                return e

    def _process_order_results(
        self,
        legs: tuple[TriangleLeg, TriangleLeg, TriangleLeg],
        results: list[OrderResponse | Exception | BaseException],
    ) -> tuple[LegResult, LegResult, LegResult]:
        """Convert order responses to LegResults."""
        leg_results: list[LegResult] = []

        for leg, result in zip(legs, results, strict=False):
            if isinstance(result, Exception):
                leg_result = LegResult(
                    leg=leg,
                    status=OrderStatus.FAILED,
                    error_message=str(result),
                )
            elif isinstance(result, OrderResponse):
                leg_result = LegResult(
                    leg=leg,
                    status=OrderStatus(result.status)
                    if result.status in [s.value for s in OrderStatus]
                    else OrderStatus.FAILED,
                    order_id=str(result.order_id),
                    filled_qty=result.executed_qty_float,
                    filled_price=result.avg_fill_price,
                    commission=result.total_commission,
                )
            else:
                leg_result = LegResult(
                    leg=leg,
                    status=OrderStatus.FAILED,
                    error_message="Unknown result type",
                )

            leg_results.append(leg_result)

        return tuple(leg_results)  # type: ignore

    def _determine_status(
        self,
        leg_results: tuple[LegResult, LegResult, LegResult],
    ) -> ExecutionStatus:
        """Determine overall execution status from leg results."""
        filled_count = sum(1 for r in leg_results if r.is_filled)

        if filled_count == 3:
            return ExecutionStatus.SUCCESS
        elif filled_count == 0:
            return ExecutionStatus.FAILED
        else:
            return ExecutionStatus.PARTIAL

    def _calculate_leg_quantities(
        self,
        opportunity: Opportunity,
        trade_size: float,
    ) -> tuple[float, float, float]:
        """Calculate quantities for each leg based on trade size."""
        prices = opportunity.prices
        path = opportunity.path

        # Start with trade_size in base currency
        # Calculate how much of each asset we need
        qty1 = trade_size / prices[0] if path.legs[0].side == OrderSide.BUY else trade_size
        qty2 = qty1 / prices[1] if path.legs[1].side == OrderSide.BUY else qty1 * prices[1]
        qty3 = qty2 * prices[2] if path.legs[2].side == OrderSide.SELL else qty2 / prices[2]

        return (qty1, qty2, qty3)

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        """Apply slippage buffer to price."""
        buffer = self._config.slippage_buffer
        if side == OrderSide.BUY:
            return price * (1 + buffer)
        else:
            return price * (1 - buffer)

    def _calculate_pnl(
        self,
        leg_results: tuple[LegResult, LegResult, LegResult],
    ) -> tuple[float, float]:
        """Calculate total P&L from leg results."""
        total_spent = 0.0
        total_received = 0.0
        total_commission = 0.0

        for result in leg_results:
            if result.is_filled:
                notional = result.filled_qty * result.filled_price
                if result.leg.side == OrderSide.BUY:
                    total_spent += notional
                else:
                    total_received += notional
                total_commission += result.commission

        profit = total_received - total_spent - total_commission
        return profit, total_commission

    def _create_failed_result(
        self,
        opportunity: Opportunity,
        error: str,
        start_time: int,
    ) -> ExecutionResult:
        """Create a failed execution result."""
        empty_legs = tuple(
            LegResult(leg=leg, status=OrderStatus.FAILED, error_message=error)
            for leg in opportunity.path.legs
        )

        return ExecutionResult(
            opportunity=opportunity,
            status=ExecutionStatus.FAILED,
            legs=empty_legs,  # type: ignore
            error_message=error,
            start_timestamp_us=start_time,
            end_timestamp_us=get_timestamp_us(),
        )

    def _log_recovery(self, recovery: RecoveryResult) -> None:
        """Log recovery result."""
        if recovery.success:
            logger.info(
                f"Recovery successful: recovered {recovery.recovered_amount:.4f}, "
                f"cost {recovery.recovery_cost:.4f}, latency {recovery.latency_us}μs"
            )
        else:
            logger.error(f"Recovery failed: {recovery.error_message}")

    @property
    def stats(self) -> dict[str, int]:
        """Get execution statistics."""
        return {
            "total": self._total_executions,
            "successful": self._successful_executions,
            "failed": self._failed_executions,
        }

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self._total_executions == 0:
            return 0.0
        return self._successful_executions / self._total_executions
