"""
Internal event bus for decoupled communication.

Provides publish/subscribe messaging between components
without tight coupling.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Generic, TypeVar


logger = logging.getLogger(__name__)


class EventType(Enum):
    """System event types."""

    # Market data events
    PRICE_UPDATE = auto()
    ORDERBOOK_UPDATE = auto()
    TRADE_UPDATE = auto()

    # Strategy events
    OPPORTUNITY_FOUND = auto()
    OPPORTUNITY_EXPIRED = auto()

    # Execution events
    ORDER_SENT = auto()
    ORDER_FILLED = auto()
    ORDER_FAILED = auto()
    EXECUTION_COMPLETE = auto()

    # System events
    CONNECTED = auto()
    DISCONNECTED = auto()
    ERROR = auto()
    SHUTDOWN = auto()


T = TypeVar("T")


@dataclass
class Event(Generic[T]):
    """Generic event with typed payload."""

    type: EventType
    payload: T
    timestamp_us: int = 0
    source: str = ""


# Type alias for event handlers
EventHandler = Callable[[Event[Any]], Awaitable[None]]
SyncEventHandler = Callable[[Event[Any]], None]


class EventBus:
    """
    Async-safe event bus for internal messaging.

    Features:
    - Type-safe publish/subscribe
    - Async and sync handler support
    - Priority-based handler ordering
    - Error isolation per handler
    """

    def __init__(self) -> None:
        """Initialize event bus."""
        self._handlers: dict[EventType, list[tuple[int, EventHandler]]] = defaultdict(list)
        self._sync_handlers: dict[EventType, list[tuple[int, SyncEventHandler]]] = defaultdict(list)
        self._paused = False

    def subscribe(
        self,
        event_type: EventType,
        handler: EventHandler,
        priority: int = 0,
    ) -> None:
        """
        Subscribe an async handler to an event type.

        Args:
            event_type: Event type to handle.
            handler: Async handler function.
            priority: Handler priority (higher = earlier execution).
        """
        self._handlers[event_type].append((priority, handler))
        # Sort by priority (descending)
        self._handlers[event_type].sort(key=lambda x: x[0], reverse=True)

    def subscribe_sync(
        self,
        event_type: EventType,
        handler: SyncEventHandler,
        priority: int = 0,
    ) -> None:
        """
        Subscribe a sync handler to an event type.

        Args:
            event_type: Event type to handle.
            handler: Sync handler function.
            priority: Handler priority.
        """
        self._sync_handlers[event_type].append((priority, handler))
        self._sync_handlers[event_type].sort(key=lambda x: x[0], reverse=True)

    def unsubscribe(
        self,
        event_type: EventType,
        handler: EventHandler | SyncEventHandler,
    ) -> bool:
        """
        Unsubscribe a handler.

        Args:
            event_type: Event type.
            handler: Handler to remove.

        Returns:
            True if handler was found and removed.
        """
        # Check async handlers
        for i, (_, ah) in enumerate(self._handlers[event_type]):
            if ah is handler:
                self._handlers[event_type].pop(i)
                return True

        # Check sync handlers
        for i, (_, sh) in enumerate(self._sync_handlers[event_type]):
            if sh is handler:
                self._sync_handlers[event_type].pop(i)
                return True

        return False

    async def publish(self, event: Event[Any]) -> None:
        """
        Publish an event to all subscribers.

        Args:
            event: Event to publish.
        """
        if self._paused:
            return

        # Run sync handlers first (they're typically faster)
        for _, sync_handler in self._sync_handlers[event.type]:
            try:
                sync_handler(event)
            except Exception as e:
                logger.error(f"Sync handler error for {event.type}: {e}")

        # Run async handlers
        for _, async_handler in self._handlers[event.type]:
            try:
                await async_handler(event)
            except Exception as e:
                logger.error(f"Async handler error for {event.type}: {e}")

    async def publish_concurrent(self, event: Event[Any]) -> None:
        """
        Publish event with concurrent async handler execution.

        Use when handler order doesn't matter and parallelism is preferred.
        """
        if self._paused:
            return

        # Run sync handlers first
        for _, sync_handler in self._sync_handlers[event.type]:
            try:
                sync_handler(event)
            except Exception as e:
                logger.error(f"Sync handler error for {event.type}: {e}")

        # Run async handlers concurrently
        tasks = []
        for _, async_handler in self._handlers[event.type]:
            tasks.append(self._safe_call(async_handler, event))

        if tasks:
            await asyncio.gather(*tasks)

    async def _safe_call(self, handler: EventHandler, event: Event[Any]) -> None:
        """Safely call a handler with error isolation."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Handler error for {event.type}: {e}")

    def publish_sync(self, event: Event[Any]) -> None:
        """
        Publish event synchronously (sync handlers only).

        Use for hot paths where async overhead is unacceptable.
        """
        if self._paused:
            return

        for _, handler in self._sync_handlers[event.type]:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Sync handler error for {event.type}: {e}")

    def pause(self) -> None:
        """Pause event delivery."""
        self._paused = True

    def resume(self) -> None:
        """Resume event delivery."""
        self._paused = False

    def clear(self, event_type: EventType | None = None) -> None:
        """
        Clear handlers.

        Args:
            event_type: Specific type to clear, or None for all.
        """
        if event_type:
            self._handlers[event_type].clear()
            self._sync_handlers[event_type].clear()
        else:
            self._handlers.clear()
            self._sync_handlers.clear()

    def handler_count(self, event_type: EventType) -> int:
        """Get number of handlers for an event type."""
        return len(self._handlers[event_type]) + len(self._sync_handlers[event_type])

    @property
    def is_paused(self) -> bool:
        """Check if event bus is paused."""
        return self._paused
