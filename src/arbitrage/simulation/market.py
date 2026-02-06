"""
Market data simulator for demo mode.

Generates realistic price movements with occasional
arbitrage opportunities for demonstration purposes.
"""

import asyncio
import random
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from arbitrage.core.types import BBO
from arbitrage.utils.time import get_timestamp_us


@dataclass
class SimulatedSymbol:
    """Configuration for a simulated trading pair."""

    symbol: str
    base_asset: str
    quote_asset: str
    base_price: float
    volatility: float = 0.0002  # Price change per tick (0.02%)
    spread_pct: float = 0.0002  # Bid-ask spread (0.02%)
    current_price: float = field(init=False)

    def __post_init__(self) -> None:
        self.current_price = self.base_price


class MarketSimulator:
    """
    Simulates realistic market data for demo mode.

    Features:
    - Brownian motion price movements
    - Correlated price changes across related pairs
    - Occasional arbitrage opportunities (configurable)
    - Realistic bid-ask spreads
    """

    # Pre-configured symbols for USDT triangles
    DEFAULT_SYMBOLS = [
        SimulatedSymbol("BTCUSDT", "BTC", "USDT", 65000.0, 0.0003, 0.0001),
        SimulatedSymbol("ETHUSDT", "ETH", "USDT", 3500.0, 0.0004, 0.0001),
        SimulatedSymbol("ETHBTC", "ETH", "BTC", 0.0538, 0.0003, 0.0002),
        SimulatedSymbol("BNBUSDT", "BNB", "USDT", 580.0, 0.0004, 0.0002),
        SimulatedSymbol("BNBBTC", "BNB", "BTC", 0.00892, 0.0003, 0.0002),
        SimulatedSymbol("BNBETH", "BNB", "ETH", 0.166, 0.0003, 0.0003),
        SimulatedSymbol("SOLUSDT", "SOL", "USDT", 180.0, 0.0005, 0.0002),
        SimulatedSymbol("SOLBTC", "SOL", "BTC", 0.00277, 0.0004, 0.0003),
        SimulatedSymbol("SOLETH", "SOL", "ETH", 0.0514, 0.0004, 0.0003),
        SimulatedSymbol("XRPUSDT", "XRP", "USDT", 0.62, 0.0005, 0.0002),
        SimulatedSymbol("XRPBTC", "XRP", "BTC", 0.00000954, 0.0004, 0.0003),
        SimulatedSymbol("XRPETH", "XRP", "ETH", 0.000177, 0.0004, 0.0003),
        SimulatedSymbol("ADAUSDT", "ADA", "USDT", 0.65, 0.0005, 0.0002),
        SimulatedSymbol("ADABTC", "ADA", "BTC", 0.00001, 0.0004, 0.0003),
        SimulatedSymbol("ADAETH", "ADA", "ETH", 0.000186, 0.0004, 0.0003),
        SimulatedSymbol("DOGEUSDT", "DOGE", "USDT", 0.15, 0.0006, 0.0003),
        SimulatedSymbol("DOGEBTC", "DOGE", "BTC", 0.00000231, 0.0005, 0.0004),
        SimulatedSymbol("LINKUSDT", "LINK", "USDT", 18.5, 0.0005, 0.0002),
        SimulatedSymbol("LINKBTC", "LINK", "BTC", 0.000285, 0.0004, 0.0003),
        SimulatedSymbol("LINKETH", "LINK", "ETH", 0.00529, 0.0004, 0.0003),
    ]

    def __init__(
        self,
        symbols: list[SimulatedSymbol] | None = None,
        tick_interval_ms: int = 100,
        opportunity_frequency: float = 0.02,  # 2% chance per tick
        opportunity_profit_range: tuple[float, float] = (0.001, 0.005),  # 0.1% - 0.5%
    ) -> None:
        """
        Initialize market simulator.

        Args:
            symbols: Symbols to simulate (default: common USDT pairs).
            tick_interval_ms: Milliseconds between price updates.
            opportunity_frequency: Probability of creating an opportunity per tick.
            opportunity_profit_range: Min/max profit for artificial opportunities.
        """
        self._symbols = {s.symbol: s for s in (symbols or self.DEFAULT_SYMBOLS)}
        self._tick_interval_ms = tick_interval_ms
        self._opportunity_frequency = opportunity_frequency
        self._opportunity_profit_range = opportunity_profit_range

        self._running = False
        self._callbacks: list[Callable[[BBO], Coroutine[Any, Any, None]]] = []
        self._tick_count = 0
        self._opportunities_created = 0

    def add_callback(
        self, callback: Callable[[BBO], Coroutine[Any, Any, None]]
    ) -> None:
        """Add callback for price updates."""
        self._callbacks.append(callback)

    def remove_callback(
        self, callback: Callable[[BBO], Coroutine[Any, Any, None]]
    ) -> None:
        """Remove a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _generate_price_change(self, symbol: SimulatedSymbol) -> float:
        """Generate a random price change using geometric Brownian motion."""
        # Random walk with drift
        drift = 0.0  # No long-term drift
        random_shock = random.gauss(0, symbol.volatility)
        return symbol.current_price * (1 + drift + random_shock)

    def _create_bbo(self, symbol: SimulatedSymbol, price: float) -> BBO:
        """Create BBO from price."""
        spread = price * symbol.spread_pct
        half_spread = spread / 2

        # Add small random variation to spread
        spread_variation = random.uniform(0.8, 1.2)
        half_spread *= spread_variation

        bid_price = price - half_spread
        ask_price = price + half_spread

        # Random quantities
        base_qty = random.uniform(0.5, 5.0)
        qty_multiplier = symbol.base_price / 1000  # Scale by price

        return BBO(
            symbol=symbol.symbol,
            bid_price=round(bid_price, 8),
            bid_qty=round(base_qty / qty_multiplier, 6),
            ask_price=round(ask_price, 8),
            ask_qty=round(base_qty / qty_multiplier * random.uniform(0.8, 1.2), 6),
            update_id=self._tick_count,
            timestamp_us=get_timestamp_us(),
        )

    def _maybe_create_opportunity(self) -> None:
        """Occasionally misalign prices to create arbitrage opportunity."""
        if random.random() > self._opportunity_frequency:
            return

        # Pick a triangle: USDT -> X -> Y -> USDT
        triangles = [
            ("BTCUSDT", "ETHBTC", "ETHUSDT"),
            ("BTCUSDT", "BNBBTC", "BNBUSDT"),
            ("BTCUSDT", "SOLBTC", "SOLUSDT"),
            ("ETHUSDT", "BNBETH", "BNBUSDT"),
            ("ETHUSDT", "LINKETH", "LINKUSDT"),
        ]

        # Filter to triangles where we have all symbols
        valid_triangles = [
            t for t in triangles
            if all(s in self._symbols for s in t)
        ]

        if not valid_triangles:
            return

        triangle = random.choice(valid_triangles)
        profit_pct = random.uniform(*self._opportunity_profit_range)

        # Adjust the third leg to create opportunity
        # For USDT -> BTC -> ETH -> USDT:
        # Increase ETHUSDT bid slightly (we're selling ETH for more USDT)
        third_symbol = self._symbols.get(triangle[2])
        if third_symbol:
            adjustment = 1 + profit_pct + 0.003  # Add some buffer for fees
            third_symbol.current_price *= adjustment
            self._opportunities_created += 1

    async def _tick(self) -> None:
        """Execute one simulation tick."""
        self._tick_count += 1

        # Maybe create an opportunity
        self._maybe_create_opportunity()

        # Update all prices
        for symbol in self._symbols.values():
            new_price = self._generate_price_change(symbol)
            symbol.current_price = new_price

            bbo = self._create_bbo(symbol, new_price)

            # Notify callbacks
            for callback in self._callbacks:
                try:
                    await callback(bbo)
                except Exception:
                    pass  # Don't let callback errors stop simulation

        # Decay any artificial opportunities back to equilibrium
        self._decay_opportunities()

    def _decay_opportunities(self) -> None:
        """Slowly return prices to equilibrium."""
        for symbol in self._symbols.values():
            # Calculate "fair" price based on other pairs
            # This is simplified - just drift back toward base
            equilibrium_drift = (symbol.base_price - symbol.current_price) * 0.01
            symbol.current_price += equilibrium_drift

    async def run(self) -> None:
        """Run the simulation loop."""
        self._running = True

        while self._running:
            await self._tick()
            await asyncio.sleep(self._tick_interval_ms / 1000)

    def stop(self) -> None:
        """Stop the simulation."""
        self._running = False

    async def start(self) -> asyncio.Task[None]:
        """Start simulation as background task."""
        return asyncio.create_task(self.run())

    def get_symbols(self) -> list[str]:
        """Get all simulated symbol names."""
        return list(self._symbols.keys())

    def get_current_prices(self) -> dict[str, float]:
        """Get current prices for all symbols."""
        return {s.symbol: s.current_price for s in self._symbols.values()}

    @property
    def tick_count(self) -> int:
        """Get number of ticks processed."""
        return self._tick_count

    @property
    def opportunities_created(self) -> int:
        """Get number of artificial opportunities created."""
        return self._opportunities_created

    @property
    def is_running(self) -> bool:
        """Check if simulator is running."""
        return self._running
