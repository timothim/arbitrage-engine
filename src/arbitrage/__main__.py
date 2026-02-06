"""
Entry point for the arbitrage engine.

Usage:
    python -m arbitrage
    arbitrage  # if installed via pip
"""

import asyncio
import sys


# Try to use uvloop for better performance
try:
    import uvloop

    uvloop.install()
    UVLOOP_ENABLED = True
except ImportError:
    UVLOOP_ENABLED = False


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 for success).
    """
    from arbitrage import __version__
    from arbitrage.config.settings import get_settings
    from arbitrage.core.engine import ArbitrageEngine

    # Print banner
    print(
        f"""
╔═══════════════════════════════════════════════════════════════╗
║     TRIANGULAR ARBITRAGE ENGINE v{__version__:<23}      ║
║                                                               ║
║     High-Frequency Trading Bot for Binance                    ║
╚═══════════════════════════════════════════════════════════════╝
    """
    )

    # Load settings
    try:
        settings = get_settings()
    except Exception as e:
        print(f"Configuration error: {e}")
        print("\nMake sure you have a .env file with:")
        print("  BINANCE_API_KEY=your_api_key")
        print("  BINANCE_API_SECRET=your_api_secret")
        return 1

    # Print configuration summary
    print("Configuration:")
    print(f"  Mode:           {'DRY RUN' if settings.dry_run else 'LIVE TRADING'}")
    print(f"  Exchange:       {'Testnet' if settings.use_testnet else 'Production'}")
    print(f"  Base currency:  {settings.base_currency}")
    print(f"  Fee rate:       {settings.fee_rate * 100:.3f}%")
    print(f"  Min profit:     {settings.min_profit_threshold * 100:.3f}%")
    print(f"  Max position:   {settings.max_position_pct * 100:.1f}%")
    print(f"  Max triangles:  {settings.max_triangles}")
    print(f"  uvloop:         {'Enabled' if UVLOOP_ENABLED else 'Disabled'}")
    print()

    if not settings.dry_run:
        print("⚠️  WARNING: Live trading mode enabled!")
        print("    Real orders will be placed on the exchange.")
        print()

    # Run the engine
    async def run_engine() -> int:
        engine = ArbitrageEngine(settings)

        try:
            await engine.setup()
            await engine.run()
            return 0

        except KeyboardInterrupt:
            print("\nInterrupted by user")
            return 0

        except Exception as e:
            print(f"\nFatal error: {e}")
            import traceback

            traceback.print_exc()
            return 1

        finally:
            await engine.shutdown()

    return asyncio.run(run_engine())


if __name__ == "__main__":
    sys.exit(main())
