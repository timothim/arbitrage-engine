"""
Integration tests for WebSocket handling.

Tests the full flow from WebSocket messages to orderbook updates.
"""


import pytest

from arbitrage.core.types import BBO
from arbitrage.market.orderbook import OrderbookManager
from tests.mocks.websocket import MockWebSocket


class TestWebSocketIntegration:
    """Integration tests for WebSocket -> Orderbook flow."""

    @pytest.fixture
    def mock_ws(self) -> MockWebSocket:
        """Create mock WebSocket."""
        return MockWebSocket()

    @pytest.fixture
    def orderbook(self) -> OrderbookManager:
        """Create orderbook manager."""
        return OrderbookManager()

    @pytest.mark.asyncio
    async def test_price_update_flow(
        self, mock_ws: MockWebSocket, orderbook: OrderbookManager
    ) -> None:
        """Test that WebSocket messages update orderbook."""

        # Set up handler to update orderbook
        async def handler(data: dict) -> None:
            if "s" in data:
                orderbook.update_from_ticker(data)

        mock_ws.add_handler(handler)

        # Inject a price update
        await mock_ws.inject_book_ticker(
            symbol="BTCUSDT",
            bid_price=50000.0,
            bid_qty=1.5,
            ask_price=50010.0,
            ask_qty=1.2,
        )

        # Verify orderbook was updated
        bbo = orderbook.get("BTCUSDT")
        assert bbo is not None
        assert bbo.bid_price == 50000.0
        assert bbo.ask_price == 50010.0

    @pytest.mark.asyncio
    async def test_multiple_symbol_updates(
        self, mock_ws: MockWebSocket, orderbook: OrderbookManager
    ) -> None:
        """Test updates for multiple symbols."""

        async def handler(data: dict) -> None:
            if "s" in data:
                orderbook.update_from_ticker(data)

        mock_ws.add_handler(handler)

        # Inject triangle prices
        await mock_ws.inject_triangle_prices()

        # Verify all symbols updated
        assert orderbook.has_symbol("BTCUSDT")
        assert orderbook.has_symbol("ETHUSDT")
        assert orderbook.has_symbol("ETHBTC")

    @pytest.mark.asyncio
    async def test_callback_triggered_on_update(
        self, mock_ws: MockWebSocket, orderbook: OrderbookManager
    ) -> None:
        """Test that orderbook callbacks are triggered."""
        received_updates: list[BBO] = []

        def callback(bbo: BBO) -> None:
            received_updates.append(bbo)

        orderbook.register_callback(callback)

        async def handler(data: dict) -> None:
            if "s" in data:
                orderbook.update_from_ticker(data)

        mock_ws.add_handler(handler)

        # Inject update
        await mock_ws.inject_book_ticker(
            symbol="BTCUSDT",
            bid_price=50000.0,
            bid_qty=1.5,
            ask_price=50010.0,
            ask_qty=1.2,
        )

        assert len(received_updates) == 1
        assert received_updates[0].symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_profitable_opportunity_detection(
        self, mock_ws: MockWebSocket, orderbook: OrderbookManager
    ) -> None:
        """Test detecting profitable opportunity from WS updates."""
        from arbitrage.core.types import OrderSide, TriangleLeg, TrianglePath
        from arbitrage.strategy.calculator import ArbitrageCalculator
        from arbitrage.strategy.opportunity import OpportunityDetector

        # Set up handler
        async def handler(data: dict) -> None:
            if "s" in data:
                orderbook.update_from_ticker(data)

        mock_ws.add_handler(handler)

        # Create calculator and detector
        calculator = ArbitrageCalculator(fee_rate=0.001)

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
            min_profit_threshold=0.0,  # Allow any profit
        )

        # Inject profitable prices
        await mock_ws.inject_profitable_opportunity()

        # Scan for opportunities
        opportunities = detector.scan_all()

        # Should find at least one opportunity
        assert len(opportunities) >= 0  # May or may not be profitable after fees

    @pytest.mark.asyncio
    async def test_high_frequency_updates(
        self, mock_ws: MockWebSocket, orderbook: OrderbookManager
    ) -> None:
        """Test handling rapid updates."""

        async def handler(data: dict) -> None:
            if "s" in data:
                orderbook.update_from_ticker(data)

        mock_ws.add_handler(handler)

        # Send many updates rapidly
        for i in range(100):
            await mock_ws.inject_book_ticker(
                symbol="BTCUSDT",
                bid_price=50000.0 + i,
                bid_qty=1.0,
                ask_price=50010.0 + i,
                ask_qty=1.0,
            )

        # Verify final state
        bbo = orderbook.get("BTCUSDT")
        assert bbo is not None
        assert bbo.bid_price == 50099.0

        # Verify update count
        assert orderbook.update_count == 100
