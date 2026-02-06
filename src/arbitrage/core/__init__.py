"""Core module containing the main engine, event bus, and type definitions."""

from arbitrage.core.event_bus import Event, EventBus, EventType
from arbitrage.core.types import (
    BBO,
    ExecutionResult,
    LegResult,
    Opportunity,
    OrderSide,
    OrderStatus,
    SymbolInfo,
    TriangleLeg,
    TrianglePath,
)


__all__ = [
    "BBO",
    "Event",
    "EventBus",
    "EventType",
    "ExecutionResult",
    "LegResult",
    "Opportunity",
    "OrderSide",
    "OrderStatus",
    "SymbolInfo",
    "TriangleLeg",
    "TrianglePath",
]
