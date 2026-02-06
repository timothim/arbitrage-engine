#!/usr/bin/env python3
"""
Triangle Discovery Script.

Discovers and displays all valid triangular arbitrage paths
from the exchange without actually trading.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for direct execution
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from arbitrage.config.settings import get_settings
from arbitrage.exchange.client import BinanceClient
from arbitrage.market.symbols import SymbolManager
from arbitrage.strategy.graph import TriangleDiscovery


async def main() -> int:
    """Discover and display triangles."""
    print("=" * 60)
    print("  TRIANGLE DISCOVERY")
    print("=" * 60)
    print()

    # Load settings
    try:
        settings = get_settings()
    except Exception as e:
        print(f"Error loading settings: {e}")
        print("Make sure .env file exists with API credentials")
        return 1

    # Create client
    async with BinanceClient(
        api_key=settings.binance_api_key.get_secret_value(),
        api_secret=settings.binance_api_secret.get_secret_value(),
        use_testnet=settings.use_testnet,
    ) as client:
        # Load exchange info
        print("Loading exchange information...")
        exchange_info = await client.get_exchange_info()

        # Load symbols
        symbol_manager = SymbolManager()
        count = symbol_manager.load_from_exchange_info(exchange_info)
        print(f"Loaded {count} tradeable symbols")
        print()

        # Discover triangles
        print(f"Discovering triangles from {settings.base_currency}...")
        discovery = TriangleDiscovery(symbol_manager)
        discovery.build_graph()

        triangles = discovery.find_triangles(
            base_asset=settings.base_currency,
            max_triangles=settings.max_triangles,
        )

        print(f"Found {len(triangles)} valid triangles")
        print()

        # Display triangles
        print("=" * 60)
        print("  DISCOVERED TRIANGLES")
        print("=" * 60)
        print()

        for i, triangle in enumerate(triangles, 1):
            legs_str = " -> ".join(
                f"{leg.from_asset}({leg.symbol}:{leg.side.value})"
                for leg in triangle.legs
            )
            print(f"{i:3}. {triangle.id}")
            print(f"     {legs_str} -> {triangle.base_asset}")
            print(f"     Symbols: {', '.join(sorted(triangle.symbols))}")
            print()

        # Summary
        print("=" * 60)
        print("  SUMMARY")
        print("=" * 60)
        print()

        all_symbols = discovery.get_all_symbols()
        print(f"Total triangles: {len(triangles)}")
        print(f"Unique symbols:  {len(all_symbols)}")
        print(f"Base currency:   {settings.base_currency}")
        print()

        # Export to JSON (optional)
        export_path = Path("triangles.json")
        import json
        with open(export_path, "w") as f:
            json.dump(discovery.to_dict(), f, indent=2)
        print(f"Exported to: {export_path}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
