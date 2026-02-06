"""
Unit tests for TriangleDiscovery.

Tests graph construction and triangle path discovery.
"""

import pytest

from arbitrage.core.types import OrderSide, SymbolInfo
from arbitrage.market.symbols import SymbolManager
from arbitrage.strategy.graph import TriangleDiscovery


class TestTriangleDiscovery:
    """Tests for TriangleDiscovery."""

    @pytest.fixture
    def symbol_manager_extended(self) -> SymbolManager:
        """Symbol manager with more pairs for testing."""
        manager = SymbolManager()

        symbols = [
            SymbolInfo("BTCUSDT", "BTC", "USDT", 2, 6, 10.0, 0.00001, 9000.0, 0.00001, 0.01),
            SymbolInfo("ETHUSDT", "ETH", "USDT", 2, 5, 10.0, 0.0001, 9000.0, 0.0001, 0.01),
            SymbolInfo("ETHBTC", "ETH", "BTC", 6, 5, 0.0001, 0.0001, 9000.0, 0.0001, 0.000001),
            SymbolInfo("BNBUSDT", "BNB", "USDT", 2, 4, 10.0, 0.01, 9000.0, 0.01, 0.01),
            SymbolInfo("BNBBTC", "BNB", "BTC", 6, 4, 0.0001, 0.01, 9000.0, 0.01, 0.000001),
            SymbolInfo("BNBETH", "BNB", "ETH", 6, 4, 0.001, 0.01, 9000.0, 0.01, 0.000001),
        ]

        for s in symbols:
            manager._add_symbol(s)

        return manager

    def test_build_graph(self, symbol_manager: SymbolManager) -> None:
        """Test graph construction from symbols."""
        discovery = TriangleDiscovery(symbol_manager)
        edge_count = discovery.build_graph()

        # 3 symbols * 2 directions = 6 edges
        assert edge_count == 6
        assert discovery.graph.number_of_nodes() == 3  # BTC, ETH, USDT

    def test_find_triangles_basic(self, symbol_manager: SymbolManager) -> None:
        """Test basic triangle discovery."""
        discovery = TriangleDiscovery(symbol_manager)
        discovery.build_graph()

        triangles = discovery.find_triangles(base_asset="USDT", max_triangles=10)

        # Should find at least one triangle: USDT -> BTC -> ETH -> USDT
        assert len(triangles) >= 1

        # Verify triangle structure
        triangle = triangles[0]
        assert triangle.base_asset == "USDT"
        assert len(triangle.legs) == 3
        assert len(triangle.symbols) == 3

    def test_find_triangles_extended(self, symbol_manager_extended: SymbolManager) -> None:
        """Test triangle discovery with more symbols."""
        discovery = TriangleDiscovery(symbol_manager_extended)
        discovery.build_graph()

        triangles = discovery.find_triangles(base_asset="USDT", max_triangles=100)

        # Should find multiple triangles with BNB, ETH, BTC
        assert len(triangles) >= 2

        # Verify all triangles start and end at USDT
        for triangle in triangles:
            assert triangle.base_asset == "USDT"
            assert triangle.legs[0].from_asset == "USDT"
            assert triangle.legs[2].to_asset == "USDT"

    def test_triangle_uniqueness(self, symbol_manager_extended: SymbolManager) -> None:
        """Test that discovered triangles are unique."""
        discovery = TriangleDiscovery(symbol_manager_extended)
        discovery.build_graph()

        triangles = discovery.find_triangles(base_asset="USDT", max_triangles=100)

        # Check for duplicate IDs
        ids = [t.id for t in triangles]
        assert len(ids) == len(set(ids)), "Duplicate triangle IDs found"

    def test_triangle_leg_continuity(self, symbol_manager: SymbolManager) -> None:
        """Test that triangle legs form a continuous path."""
        discovery = TriangleDiscovery(symbol_manager)
        discovery.build_graph()

        triangles = discovery.find_triangles(base_asset="USDT")

        for triangle in triangles:
            legs = triangle.legs

            # Leg 1 ends where Leg 2 starts
            assert legs[0].to_asset == legs[1].from_asset

            # Leg 2 ends where Leg 3 starts
            assert legs[1].to_asset == legs[2].from_asset

            # Leg 3 ends at base (start of Leg 1)
            assert legs[2].to_asset == legs[0].from_asset

    def test_max_triangles_limit(self, symbol_manager_extended: SymbolManager) -> None:
        """Test that max_triangles limit is respected."""
        discovery = TriangleDiscovery(symbol_manager_extended)
        discovery.build_graph()

        triangles = discovery.find_triangles(base_asset="USDT", max_triangles=1)

        assert len(triangles) <= 1

    def test_nonexistent_base_asset(self, symbol_manager: SymbolManager) -> None:
        """Test behavior with nonexistent base asset."""
        discovery = TriangleDiscovery(symbol_manager)
        discovery.build_graph()

        triangles = discovery.find_triangles(base_asset="XYZ")

        assert len(triangles) == 0

    def test_get_all_symbols(self, symbol_manager: SymbolManager) -> None:
        """Test getting all symbols from discovered triangles."""
        discovery = TriangleDiscovery(symbol_manager)
        discovery.build_graph()
        discovery.find_triangles(base_asset="USDT")

        symbols = discovery.get_all_symbols()

        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols
        assert "ETHBTC" in symbols

    def test_get_triangles_for_symbol(self, symbol_manager_extended: SymbolManager) -> None:
        """Test filtering triangles by symbol."""
        discovery = TriangleDiscovery(symbol_manager_extended)
        discovery.build_graph()
        discovery.find_triangles(base_asset="USDT")

        btc_triangles = discovery.get_triangles_for_symbol("BTCUSDT")

        # All returned triangles should contain BTCUSDT
        for triangle in btc_triangles:
            assert "BTCUSDT" in triangle.symbols

    def test_to_dict_serialization(self, symbol_manager: SymbolManager) -> None:
        """Test serialization to dict."""
        discovery = TriangleDiscovery(symbol_manager)
        discovery.build_graph()
        discovery.find_triangles(base_asset="USDT")

        result = discovery.to_dict()

        assert "triangles" in result
        assert len(result["triangles"]) > 0

        triangle_data = result["triangles"][0]
        assert "id" in triangle_data
        assert "base_asset" in triangle_data
        assert "legs" in triangle_data
        assert len(triangle_data["legs"]) == 3


class TestTrianglePath:
    """Tests for TrianglePath dataclass."""

    def test_triangle_path_creation(self, triangle_usdt_btc_eth) -> None:
        """Test TrianglePath creation."""
        assert triangle_usdt_btc_eth.id == "USDT-BTC-ETH"
        assert triangle_usdt_btc_eth.base_asset == "USDT"
        assert len(triangle_usdt_btc_eth.legs) == 3

    def test_triangle_symbols_computed(self, triangle_usdt_btc_eth) -> None:
        """Test that symbols frozenset is computed."""
        expected = frozenset(["BTCUSDT", "ETHBTC", "ETHUSDT"])
        assert triangle_usdt_btc_eth.symbols == expected

    def test_triangle_hashable(self, triangle_usdt_btc_eth) -> None:
        """Test that TrianglePath is hashable."""
        # Should be able to use in sets/dicts
        triangle_set = {triangle_usdt_btc_eth}
        assert len(triangle_set) == 1

    def test_triangle_equality(self) -> None:
        """Test TrianglePath equality."""
        from arbitrage.core.types import TriangleLeg, TrianglePath

        legs = (
            TriangleLeg("BTCUSDT", OrderSide.BUY, "USDT", "BTC"),
            TriangleLeg("ETHBTC", OrderSide.BUY, "BTC", "ETH"),
            TriangleLeg("ETHUSDT", OrderSide.SELL, "ETH", "USDT"),
        )

        path1 = TrianglePath(id="test", base_asset="USDT", legs=legs)
        path2 = TrianglePath(id="test", base_asset="USDT", legs=legs)
        path3 = TrianglePath(id="different", base_asset="USDT", legs=legs)

        assert path1 == path2
        assert path1 != path3
