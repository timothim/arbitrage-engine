#!/usr/bin/env python3
"""
Latency Benchmark Script.

Measures internal latencies for critical path operations.
"""

import asyncio
import statistics
import sys
from pathlib import Path

# Add src to path for direct execution
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from arbitrage.core.types import BBO, OrderSide, TriangleLeg, TrianglePath
from arbitrage.market.orderbook import OrderbookManager
from arbitrage.strategy.calculator import ArbitrageCalculator
from arbitrage.strategy.opportunity import OpportunityDetector
from arbitrage.utils.time import get_timestamp_us, format_duration_us


def benchmark_orderbook_update(iterations: int = 10000) -> dict[str, float]:
    """Benchmark orderbook update latency."""
    orderbook = OrderbookManager()
    latencies: list[int] = []

    for i in range(iterations):
        bbo = BBO(
            symbol="BTCUSDT",
            bid_price=50000.0 + (i % 100),
            bid_qty=1.0,
            ask_price=50010.0 + (i % 100),
            ask_qty=1.0,
            update_id=i,
            timestamp_us=get_timestamp_us(),
        )

        start = get_timestamp_us()
        orderbook.update(bbo)
        latencies.append(get_timestamp_us() - start)

    return {
        "min": min(latencies),
        "max": max(latencies),
        "avg": statistics.mean(latencies),
        "p50": statistics.median(latencies),
        "p99": sorted(latencies)[int(len(latencies) * 0.99)],
    }


def benchmark_opportunity_calculation(iterations: int = 10000) -> dict[str, float]:
    """Benchmark opportunity calculation latency."""
    calculator = ArbitrageCalculator(fee_rate=0.001)
    orderbook = OrderbookManager()

    # Set up orderbook
    orderbook.update(BBO("BTCUSDT", 50000.0, 1.0, 50010.0, 1.0, 1, get_timestamp_us()))
    orderbook.update(BBO("ETHBTC", 0.06, 50.0, 0.0601, 50.0, 2, get_timestamp_us()))
    orderbook.update(BBO("ETHUSDT", 3000.0, 10.0, 3001.0, 10.0, 3, get_timestamp_us()))

    triangle = TrianglePath(
        id="USDT-BTC-ETH",
        base_asset="USDT",
        legs=(
            TriangleLeg("BTCUSDT", OrderSide.BUY, "USDT", "BTC"),
            TriangleLeg("ETHBTC", OrderSide.BUY, "BTC", "ETH"),
            TriangleLeg("ETHUSDT", OrderSide.SELL, "ETH", "USDT"),
        ),
    )

    latencies: list[int] = []

    for _ in range(iterations):
        start = get_timestamp_us()
        calculator.calculate_opportunity(triangle, orderbook)
        latencies.append(get_timestamp_us() - start)

    return {
        "min": min(latencies),
        "max": max(latencies),
        "avg": statistics.mean(latencies),
        "p50": statistics.median(latencies),
        "p99": sorted(latencies)[int(len(latencies) * 0.99)],
    }


def benchmark_opportunity_detection(iterations: int = 1000) -> dict[str, float]:
    """Benchmark full opportunity detection cycle."""
    calculator = ArbitrageCalculator(fee_rate=0.001)
    orderbook = OrderbookManager()

    # Set up initial orderbook
    orderbook.update(BBO("BTCUSDT", 50000.0, 1.0, 50010.0, 1.0, 1, get_timestamp_us()))
    orderbook.update(BBO("ETHBTC", 0.06, 50.0, 0.0601, 50.0, 2, get_timestamp_us()))
    orderbook.update(BBO("ETHUSDT", 3000.0, 10.0, 3001.0, 10.0, 3, get_timestamp_us()))

    triangle = TrianglePath(
        id="USDT-BTC-ETH",
        base_asset="USDT",
        legs=(
            TriangleLeg("BTCUSDT", OrderSide.BUY, "USDT", "BTC"),
            TriangleLeg("ETHBTC", OrderSide.BUY, "BTC", "ETH"),
            TriangleLeg("ETHUSDT", OrderSide.SELL, "ETH", "USDT"),
        ),
    )

    detector = OpportunityDetector(
        calculator=calculator,
        orderbook=orderbook,
        triangles=[triangle],
        min_profit_threshold=0.0,
    )

    latencies: list[int] = []

    for i in range(iterations):
        bbo = BBO(
            symbol="BTCUSDT",
            bid_price=50000.0 + (i % 10),
            bid_qty=1.0,
            ask_price=50010.0 + (i % 10),
            ask_qty=1.0,
            update_id=i,
            timestamp_us=get_timestamp_us(),
        )
        orderbook.update(bbo)

        start = get_timestamp_us()
        detector.on_price_update(bbo)
        latencies.append(get_timestamp_us() - start)

    return {
        "min": min(latencies),
        "max": max(latencies),
        "avg": statistics.mean(latencies),
        "p50": statistics.median(latencies),
        "p99": sorted(latencies)[int(len(latencies) * 0.99)],
    }


def format_stats(stats: dict[str, float]) -> str:
    """Format stats for display."""
    return (
        f"min={format_duration_us(int(stats['min']))}, "
        f"avg={format_duration_us(int(stats['avg']))}, "
        f"p50={format_duration_us(int(stats['p50']))}, "
        f"p99={format_duration_us(int(stats['p99']))}, "
        f"max={format_duration_us(int(stats['max']))}"
    )


def main() -> int:
    """Run all benchmarks."""
    print("=" * 70)
    print("  LATENCY BENCHMARK")
    print("=" * 70)
    print()

    # Warm up
    print("Warming up...")
    benchmark_orderbook_update(100)
    benchmark_opportunity_calculation(100)
    benchmark_opportunity_detection(100)
    print()

    # Run benchmarks
    print("Running benchmarks...")
    print()

    print("1. Orderbook Update (10,000 iterations)")
    stats = benchmark_orderbook_update(10000)
    print(f"   {format_stats(stats)}")
    print()

    print("2. Opportunity Calculation (10,000 iterations)")
    stats = benchmark_opportunity_calculation(10000)
    print(f"   {format_stats(stats)}")
    print()

    print("3. Full Detection Cycle (1,000 iterations)")
    stats = benchmark_opportunity_detection(1000)
    print(f"   {format_stats(stats)}")
    print()

    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print()
    print("Target: Tick-to-Trade < 5ms (5000μs)")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
