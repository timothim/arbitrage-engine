"""
Position recovery for failed triangle executions.

Handles partial fills and leg failures by liquidating
unexpected positions back to base currency.
"""

import logging
from dataclasses import dataclass
from enum import Enum, auto

from arbitrage.core.types import ExecutionResult, ExecutionStatus, OrderSide, OrderStatus
from arbitrage.exchange.client import BinanceClient
from arbitrage.market.symbols import SymbolManager
from arbitrage.utils.time import LatencyTimer


logger = logging.getLogger(__name__)


class RecoveryAction(Enum):
    """Type of recovery action taken."""

    NONE = auto()
    LIQUIDATE = auto()
    CANCEL = auto()
    REVERSE = auto()


@dataclass
class RecoveryResult:
    """Result of a recovery operation."""

    action: RecoveryAction
    success: bool
    original_asset: str
    recovered_amount: float
    recovery_cost: float
    latency_us: int
    error_message: str = ""


class PositionRecovery:
    """
    Handles recovery from failed triangle executions.

    When a triangle partially executes, we may be left holding
    an intermediate asset. This class handles liquidating back
    to the base currency to minimize exposure time.
    """

    def __init__(
        self,
        client: BinanceClient,
        symbol_manager: SymbolManager,
        base_currency: str = "USDT",
    ) -> None:
        """
        Initialize recovery handler.

        Args:
            client: Exchange client for placing orders.
            symbol_manager: Symbol information.
            base_currency: Base currency to recover to.
        """
        self._client = client
        self._symbol_manager = symbol_manager
        self._base_currency = base_currency

    async def analyze_and_recover(
        self,
        execution_result: ExecutionResult,
    ) -> RecoveryResult | None:
        """
        Analyze execution result and recover if needed.

        Args:
            execution_result: Result from triangle execution.

        Returns:
            RecoveryResult if recovery was needed, None otherwise.
        """
        # Check if recovery is needed
        if execution_result.status == ExecutionStatus.SUCCESS:
            return None

        # Analyze which legs succeeded and what we're holding
        holdings = self._analyze_holdings(execution_result)

        if not holdings:
            logger.info("No recovery needed - no intermediate holdings")
            return None

        logger.warning(f"Recovery needed - holding: {holdings}")

        # Attempt to liquidate holdings
        return await self._liquidate_holdings(holdings)

    def _analyze_holdings(
        self,
        execution_result: ExecutionResult,
    ) -> dict[str, float]:
        """
        Analyze what assets we're holding after partial execution.

        Args:
            execution_result: Execution result to analyze.

        Returns:
            Dict of asset -> amount we're unexpectedly holding.
        """
        holdings: dict[str, float] = {}
        path = execution_result.opportunity.path

        for i, leg_result in enumerate(execution_result.legs):
            leg = path.legs[i]

            if leg_result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                filled_qty = leg_result.filled_qty

                if filled_qty > 0:
                    # Track what we received
                    if leg.side == OrderSide.BUY:
                        # Bought base asset
                        asset = leg.to_asset
                    else:
                        # Sold for quote asset
                        asset = leg.to_asset

                    # Only track if it's not the base currency
                    if asset != self._base_currency:
                        holdings[asset] = holdings.get(asset, 0) + filled_qty

        # Check subsequent legs to see if holdings were used
        for i, leg_result in enumerate(execution_result.legs):
            leg = path.legs[i]

            if leg_result.status == OrderStatus.FILLED:
                # This leg used up the holding from previous leg
                if leg.from_asset in holdings:
                    holdings[leg.from_asset] -= leg_result.filled_qty
                    if holdings[leg.from_asset] <= 0:
                        del holdings[leg.from_asset]

        return {k: v for k, v in holdings.items() if v > 0}

    async def _liquidate_holdings(
        self,
        holdings: dict[str, float],
    ) -> RecoveryResult:
        """
        Liquidate holdings back to base currency.

        Args:
            holdings: Assets and amounts to liquidate.

        Returns:
            RecoveryResult with outcome.
        """
        with LatencyTimer() as timer:
            total_recovered = 0.0
            total_cost = 0.0
            errors: list[str] = []

            for asset, amount in holdings.items():
                try:
                    result = await self._liquidate_asset(asset, amount)
                    if result:
                        total_recovered += result[0]
                        total_cost += result[1]
                except Exception as e:
                    errors.append(f"{asset}: {e}")
                    logger.error(f"Failed to liquidate {amount} {asset}: {e}")

        success = len(errors) == 0
        first_asset = next(iter(holdings.keys())) if holdings else ""

        return RecoveryResult(
            action=RecoveryAction.LIQUIDATE,
            success=success,
            original_asset=first_asset,
            recovered_amount=total_recovered,
            recovery_cost=total_cost,
            latency_us=timer.latency_us,
            error_message="; ".join(errors) if errors else "",
        )

    async def _liquidate_asset(
        self,
        asset: str,
        amount: float,
    ) -> tuple[float, float] | None:
        """
        Liquidate a single asset to base currency.

        Args:
            asset: Asset to liquidate.
            amount: Amount to liquidate.

        Returns:
            Tuple of (recovered_amount, cost) or None if failed.
        """
        # Find the trading pair
        symbol = self._symbol_manager.find_symbol(asset, self._base_currency)
        side = OrderSide.SELL

        if not symbol:
            # Try reverse pair
            symbol = self._symbol_manager.find_symbol(self._base_currency, asset)
            side = OrderSide.BUY

        if not symbol:
            logger.error(f"No trading pair found for {asset}/{self._base_currency}")
            return None

        # Get symbol info for quantity normalization
        symbol_info = self._symbol_manager.get(symbol)
        if not symbol_info:
            return None

        # Normalize quantity
        normalized_qty = symbol_info.round_quantity(amount)
        if normalized_qty < symbol_info.min_qty:
            logger.warning(f"Quantity {amount} too small to liquidate")
            return None

        # Place market order
        logger.info(f"Liquidating {normalized_qty} {asset} via {symbol} {side.value}")

        try:
            response = await self._client.place_market_order(
                symbol=symbol,
                side=side,
                quantity=normalized_qty,
            )

            if response.is_filled:
                recovered = float(response.cummulative_quote_qty)
                commission = response.total_commission
                logger.info(f"Liquidation complete: recovered {recovered} {self._base_currency}")
                return (recovered, commission)
            else:
                logger.warning(f"Liquidation order not filled: {response.status}")
                return None

        except Exception as e:
            logger.error(f"Liquidation order failed: {e}")
            raise

    async def emergency_liquidate_all(
        self,
        assets_to_keep: set[str] | None = None,
    ) -> list[RecoveryResult]:
        """
        Emergency liquidation of all non-base assets.

        Args:
            assets_to_keep: Assets to not liquidate.

        Returns:
            List of recovery results.
        """
        assets_to_keep = assets_to_keep or {self._base_currency}
        results: list[RecoveryResult] = []

        # Get current balances
        try:
            account = await self._client.get_account()
        except Exception as e:
            logger.error(f"Failed to get account for emergency liquidation: {e}")
            return results

        for balance in account.balances:
            if balance.asset in assets_to_keep:
                continue

            available = balance.available
            if available <= 0:
                continue

            # Attempt liquidation
            holdings = {balance.asset: available}
            result = await self._liquidate_holdings(holdings)
            results.append(result)

        return results
