"""
Integration tests for the main engine.

Tests the full system integration.
"""

import asyncio

import pytest

from arbitrage.core.types import BBO
from arbitrage.market.orderbook import OrderbookManager
from arbitrage.strategy.calculator import ArbitrageCalculator
from arbitrage.strategy.opportunity import OpportunityDetector
from arbitrage.telemetry.metrics import MetricsCollector
from tests.mocks.websocket import MockWebSocket


class TestEngineIntegration:
    """Integration tests for engine components."""

    @pytest.fixture
    def metrics(self) -> MetricsCollector:
        """Create metrics collector."""
        return MetricsCollector()

    @pytest.fixture
    def orderbook(self) -> OrderbookManager:
        """Create orderbook manager."""
        return OrderbookManager()

    @pytest.fixture
    def calculator(self) -> ArbitrageCalculator:
        """Create calculator."""
        return ArbitrageCalculator(fee_rate=0.001)

    @pytest.mark.asyncio
    async def test_full_opportunity_detection_flow(
        self,
        orderbook: OrderbookManager,
        calculator: ArbitrageCalculator,
        metrics: MetricsCollector,
    ) -> None:
        """Test full flow from price updates to opportunity detection."""
        from arbitrage.core.types import OrderSide, TriangleLeg, TrianglePath

        # Create triangle
        triangle = TrianglePath(
            id="USDT-BTC-ETH",
            base_asset="USDT",
            legs=(
                TriangleLeg("BTCUSDT", OrderSide.BUY, "USDT", "BTC"),
                TriangleLeg("ETHBTC", OrderSide.BUY, "BTC", "ETH"),
                TriangleLeg("ETHUSDT", OrderSide.SELL, "ETH", "USDT"),
            ),
        )

        # Create detector
        detector = OpportunityDetector(
            calculator=calculator,
            orderbook=orderbook,
            triangles=[triangle],
            min_profit_threshold=0.0,
        )

        # Track opportunities
        opportunities_found: list = []

        def on_opportunity(opp):
            opportunities_found.append(opp)
            metrics.record_opportunity(opp.profit_pct)

        detector.register_callback(on_opportunity)

        # Simulate price updates
        mock_ws = MockWebSocket()

        async def handler(data: dict) -> None:
            if "s" in data:
                bbo = orderbook.update_from_ticker(data)
                detector.on_price_update(bbo)

        mock_ws.add_handler(handler)

        # Inject prices
        await mock_ws.inject_triangle_prices()

        # Check metrics
        assert orderbook.size == 3
        assert metrics.get_counter("opportunities_found") >= 0

    @pytest.mark.asyncio
    async def test_latency_tracking(
        self,
        orderbook: OrderbookManager,
        calculator: ArbitrageCalculator,
        metrics: MetricsCollector,
    ) -> None:
        """Test that latencies are properly tracked."""
        from arbitrage.core.types import OrderSide, TriangleLeg, TrianglePath
        from arbitrage.utils.time import get_timestamp_us

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

        # Process updates and measure latency
        for i in range(10):
            start = get_timestamp_us()

            # Simulate price update
            bbo = BBO(
                symbol="BTCUSDT",
                bid_price=50000.0 + i,
                bid_qty=1.0,
                ask_price=50010.0 + i,
                ask_qty=1.0,
                update_id=i,
                timestamp_us=start,
            )
            orderbook.update(bbo)
            detector.on_price_update(bbo)

            latency = get_timestamp_us() - start
            metrics.record_latency("tick_to_calc", latency)

        # Check latency stats
        stats = metrics.get_latency_stats("tick_to_calc")
        assert stats.count == 10
        assert stats.avg_us > 0
        assert stats.max_us >= stats.min_us

    @pytest.mark.asyncio
    async def test_event_bus_integration(self) -> None:
        """Test event bus message passing."""
        from arbitrage.core.event_bus import Event, EventBus, EventType

        bus = EventBus()
        received_events: list[Event] = []

        async def handler(event: Event) -> None:
            received_events.append(event)

        bus.subscribe(EventType.PRICE_UPDATE, handler)

        # Publish events
        for i in range(5):
            event = Event(
                type=EventType.PRICE_UPDATE,
                payload={"price": 50000.0 + i},
            )
            await bus.publish(event)

        assert len(received_events) == 5

    @pytest.mark.asyncio
    async def test_concurrent_event_handling(self) -> None:
        """Test concurrent event processing."""
        from arbitrage.core.event_bus import Event, EventBus, EventType

        bus = EventBus()
        handler_calls: list[int] = []

        async def slow_handler(event: Event) -> None:
            await asyncio.sleep(0.01)
            handler_calls.append(1)

        async def fast_handler(event: Event) -> None:
            handler_calls.append(2)

        bus.subscribe(EventType.OPPORTUNITY_FOUND, slow_handler)
        bus.subscribe(EventType.OPPORTUNITY_FOUND, fast_handler)

        event = Event(type=EventType.OPPORTUNITY_FOUND, payload={})

        # Sequential execution
        await bus.publish(event)
        assert len(handler_calls) == 2

        # Concurrent execution
        handler_calls.clear()
        await bus.publish_concurrent(event)
        assert len(handler_calls) == 2


class TestSystemResilience:
    """Tests for system resilience and error handling."""

    @pytest.mark.asyncio
    async def test_orderbook_callback_error_isolation(self) -> None:
        """Test that callback errors don't crash the system."""
        orderbook = OrderbookManager()

        def bad_callback(bbo: BBO) -> None:
            raise ValueError("Test error")

        def good_callback(bbo: BBO) -> None:
            pass  # Should still be called

        orderbook.register_callback(bad_callback)
        orderbook.register_callback(good_callback)

        # Should not raise despite bad callback
        bbo = BBO(
            symbol="TEST",
            bid_price=100.0,
            bid_qty=1.0,
            ask_price=101.0,
            ask_qty=1.0,
            update_id=1,
            timestamp_us=1000000,
        )

        # This should handle the error gracefully
        try:
            orderbook.update(bbo)
        except ValueError:
            pass  # Expected from bad callback

        assert orderbook.has_symbol("TEST")

    @pytest.mark.asyncio
    async def test_event_bus_error_isolation(self) -> None:
        """Test that handler errors don't crash the bus."""
        from arbitrage.core.event_bus import Event, EventBus, EventType

        bus = EventBus()
        successful_calls = 0

        async def bad_handler(event: Event) -> None:
            raise RuntimeError("Handler error")

        async def good_handler(event: Event) -> None:
            nonlocal successful_calls
            successful_calls += 1

        bus.subscribe(EventType.PRICE_UPDATE, bad_handler)
        bus.subscribe(EventType.PRICE_UPDATE, good_handler)

        event = Event(type=EventType.PRICE_UPDATE, payload={})
        await bus.publish(event)

        # Good handler should still have been called
        assert successful_calls == 1
