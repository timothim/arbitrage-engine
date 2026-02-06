"""
Triangle path discovery using graph analysis.

Uses NetworkX for initial graph construction and path finding,
then converts to optimized data structures for runtime.
"""

import logging
from typing import Any

import networkx as nx

from arbitrage.core.types import OrderSide, TriangleLeg, TrianglePath
from arbitrage.market.symbols import SymbolManager


logger = logging.getLogger(__name__)


class TriangleDiscovery:
    """
    Discovers valid triangular arbitrage paths.

    Uses a directed graph where:
    - Nodes are assets (BTC, ETH, USDT, etc.)
    - Edges are trading pairs with direction

    Finds all cycles of length 3 starting from the base asset.
    """

    def __init__(self, symbol_manager: SymbolManager) -> None:
        """
        Initialize triangle discovery.

        Args:
            symbol_manager: Manager with loaded symbol data.
        """
        self._symbol_manager = symbol_manager
        self._graph: nx.DiGraph = nx.DiGraph()
        self._triangles: list[TrianglePath] = []

    def build_graph(self) -> int:
        """
        Build directed graph from available trading pairs.

        Returns:
            Number of edges (trading pairs) added.
        """
        self._graph.clear()

        for symbol, info in self._symbol_manager.get_all().items():
            base = info.base_asset
            quote = info.quote_asset

            # Add bidirectional edges
            # Edge from quote -> base (buying base with quote)
            self._graph.add_edge(quote, base, symbol=symbol, side=OrderSide.BUY)
            # Edge from base -> quote (selling base for quote)
            self._graph.add_edge(base, quote, symbol=symbol, side=OrderSide.SELL)

        logger.info(
            f"Built graph with {self._graph.number_of_nodes()} assets, "
            f"{self._graph.number_of_edges()} edges"
        )

        return int(self._graph.number_of_edges())

    def find_triangles(
        self,
        base_asset: str = "USDT",
        max_triangles: int = 100,
    ) -> list[TrianglePath]:
        """
        Find all triangular paths from base asset.

        A triangle is: base -> A -> B -> base

        Args:
            base_asset: Starting/ending asset for cycles.
            max_triangles: Maximum triangles to return.

        Returns:
            List of TrianglePath objects.
        """
        if base_asset not in self._graph:
            logger.warning(f"Base asset {base_asset} not in graph")
            return []

        triangles: list[TrianglePath] = []
        seen_paths: set[frozenset[str]] = set()

        # Get all neighbors of base
        for first_hop in self._graph.neighbors(base_asset):
            if first_hop == base_asset:
                continue

            # Get all neighbors of first hop (excluding base)
            for second_hop in self._graph.neighbors(first_hop):
                if second_hop == base_asset or second_hop == first_hop:
                    continue

                # Check if we can return to base
                if not self._graph.has_edge(second_hop, base_asset):
                    continue

                # Create unique identifier for this triangle
                path_set = frozenset([first_hop, second_hop])
                if path_set in seen_paths:
                    continue
                seen_paths.add(path_set)

                # Build triangle
                triangle = self._build_triangle(
                    base_asset, first_hop, second_hop
                )
                if triangle:
                    triangles.append(triangle)

                    if len(triangles) >= max_triangles:
                        break

            if len(triangles) >= max_triangles:
                break

        self._triangles = triangles
        logger.info(f"Found {len(triangles)} triangular paths from {base_asset}")

        return triangles

    def _build_triangle(
        self,
        base: str,
        mid1: str,
        mid2: str,
    ) -> TrianglePath | None:
        """
        Build a TrianglePath from three assets.

        Args:
            base: Base asset (start and end).
            mid1: First intermediate asset.
            mid2: Second intermediate asset.

        Returns:
            TrianglePath or None if invalid.
        """
        try:
            # Get edge data
            edge1 = self._graph.edges[base, mid1]
            edge2 = self._graph.edges[mid1, mid2]
            edge3 = self._graph.edges[mid2, base]

            # Create legs
            leg1 = TriangleLeg(
                symbol=edge1["symbol"],
                side=edge1["side"],
                from_asset=base,
                to_asset=mid1,
            )
            leg2 = TriangleLeg(
                symbol=edge2["symbol"],
                side=edge2["side"],
                from_asset=mid1,
                to_asset=mid2,
            )
            leg3 = TriangleLeg(
                symbol=edge3["symbol"],
                side=edge3["side"],
                from_asset=mid2,
                to_asset=base,
            )

            # Create unique ID
            triangle_id = f"{base}-{mid1}-{mid2}"

            return TrianglePath(
                id=triangle_id,
                base_asset=base,
                legs=(leg1, leg2, leg3),
            )

        except KeyError as e:
            logger.debug(f"Missing edge for triangle {base}-{mid1}-{mid2}: {e}")
            return None

    def get_triangles(self) -> list[TrianglePath]:
        """Get discovered triangles."""
        return self._triangles

    def get_triangles_for_symbol(self, symbol: str) -> list[TrianglePath]:
        """
        Get triangles containing a specific symbol.

        Args:
            symbol: Trading symbol to filter by.

        Returns:
            Triangles containing the symbol.
        """
        return [t for t in self._triangles if symbol in t.symbols]

    def get_all_symbols(self) -> set[str]:
        """Get all symbols involved in triangles."""
        symbols: set[str] = set()
        for triangle in self._triangles:
            symbols.update(triangle.symbols)
        return symbols

    def get_assets(self) -> set[str]:
        """Get all assets in the graph."""
        return set(self._graph.nodes())

    @property
    def graph(self) -> nx.DiGraph:
        """Get the underlying NetworkX graph."""
        return self._graph

    def visualize(self, output_path: str | None = None) -> None:
        """
        Generate a visualization of the graph.

        Args:
            output_path: Path to save image (requires matplotlib).
        """
        try:
            import matplotlib.pyplot as plt

            plt.figure(figsize=(12, 8))
            pos = nx.spring_layout(self._graph, k=2, iterations=50)
            nx.draw(
                self._graph,
                pos,
                with_labels=True,
                node_color="lightblue",
                node_size=500,
                font_size=8,
                arrows=True,
            )

            if output_path:
                plt.savefig(output_path, dpi=150, bbox_inches="tight")
                logger.info(f"Saved graph visualization to {output_path}")
            else:
                plt.show()

            plt.close()

        except ImportError:
            logger.warning("matplotlib not installed, cannot visualize graph")

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        """
        Convert triangles to serializable format.

        Returns:
            Dict with triangle data.
        """
        return {
            "triangles": [
                {
                    "id": t.id,
                    "base_asset": t.base_asset,
                    "legs": [
                        {
                            "symbol": leg.symbol,
                            "side": leg.side.value,
                            "from": leg.from_asset,
                            "to": leg.to_asset,
                        }
                        for leg in t.legs
                    ],
                }
                for t in self._triangles
            ]
        }
