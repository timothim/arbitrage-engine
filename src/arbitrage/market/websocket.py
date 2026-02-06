"""
WebSocket manager for real-time market data.

Manages multiple WebSocket connections to Binance with:
- Auto-reconnection with exponential backoff
- Heartbeat monitoring
- Efficient message routing
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from enum import Enum, auto
from typing import Any

import aiohttp
import orjson

from arbitrage.config.constants import (
    BINANCE_WS_TESTNET_URL,
    BINANCE_WS_URL,
    MAX_RECONNECT_DELAY,
    MAX_STREAMS_PER_CONNECTION,
    MIN_RECONNECT_DELAY,
    RECONNECT_MULTIPLIER,
    WS_CLOSE_TIMEOUT,
    WS_MAX_MESSAGE_SIZE,
    WS_PING_INTERVAL,
    WS_PING_TIMEOUT,
)


logger = logging.getLogger(__name__)


# Type aliases
MessageHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class ConnectionState(Enum):
    """WebSocket connection state."""

    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    RECONNECTING = auto()
    CLOSED = auto()


class WebSocketConnection:
    """
    Single WebSocket connection manager.

    Handles connection lifecycle, reconnection, and message routing
    for a set of streams.
    """

    def __init__(
        self,
        base_url: str,
        streams: list[str],
        message_handler: MessageHandler,
        connection_id: int = 0,
    ) -> None:
        """
        Initialize WebSocket connection.

        Args:
            base_url: Base WebSocket URL.
            streams: List of stream names to subscribe.
            message_handler: Async callback for messages.
            connection_id: Identifier for logging.
        """
        self._base_url = base_url
        self._streams = streams
        self._message_handler = message_handler
        self._connection_id = connection_id

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._state = ConnectionState.DISCONNECTED
        self._reconnect_delay = MIN_RECONNECT_DELAY
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._message_count = 0

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state

    @property
    def message_count(self) -> int:
        """Get total messages received."""
        return self._message_count

    def _build_url(self) -> str:
        """Build combined stream URL."""
        streams_param = "/".join(self._streams)
        return f"{self._base_url}/stream?streams={streams_param}"

    async def connect(self) -> bool:
        """
        Establish WebSocket connection.

        Returns:
            True if connected successfully.
        """
        if self._state == ConnectionState.CONNECTED:
            return True

        self._state = ConnectionState.CONNECTING

        try:
            # Create session if needed
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()

            url = self._build_url()
            logger.info(f"[WS-{self._connection_id}] Connecting to {len(self._streams)} streams")

            self._ws = await self._session.ws_connect(
                url,
                heartbeat=WS_PING_INTERVAL,
                receive_timeout=WS_PING_TIMEOUT,
                max_msg_size=WS_MAX_MESSAGE_SIZE,
            )

            self._state = ConnectionState.CONNECTED
            self._reconnect_delay = MIN_RECONNECT_DELAY
            logger.info(f"[WS-{self._connection_id}] Connected successfully")
            return True

        except Exception as e:
            logger.error(f"[WS-{self._connection_id}] Connection failed: {e}")
            self._state = ConnectionState.DISCONNECTED
            return False

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        self._state = ConnectionState.CLOSED

        if self._ws and not self._ws.closed:
            await self._ws.close()

        if self._session and not self._session.closed:
            await self._session.close()

        self._ws = None
        self._session = None

    async def _reconnect(self) -> None:
        """Attempt reconnection with exponential backoff."""
        self._state = ConnectionState.RECONNECTING

        while self._running and self._state != ConnectionState.CONNECTED:
            logger.info(f"[WS-{self._connection_id}] Reconnecting in {self._reconnect_delay:.1f}s")
            await asyncio.sleep(self._reconnect_delay)

            if await self.connect():
                break

            # Exponential backoff
            self._reconnect_delay = min(
                self._reconnect_delay * RECONNECT_MULTIPLIER,
                MAX_RECONNECT_DELAY,
            )

    async def _handle_message(self, msg: aiohttp.WSMessage) -> bool:
        """
        Process a WebSocket message.

        Args:
            msg: WebSocket message.

        Returns:
            False if connection should be closed.
        """
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = orjson.loads(msg.data)
                self._message_count += 1

                # Binance combined stream format: {"stream": "...", "data": {...}}
                if "data" in data:
                    await self._message_handler(data["data"])
                else:
                    await self._message_handler(data)

            except orjson.JSONDecodeError as e:
                logger.warning(f"[WS-{self._connection_id}] Invalid JSON: {e}")

        elif msg.type == aiohttp.WSMsgType.ERROR:
            logger.error(f"[WS-{self._connection_id}] Error: {msg.data}")
            return False

        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
            logger.warning(f"[WS-{self._connection_id}] Connection closed")
            return False

        return True

    async def run(self) -> None:
        """Main message loop with auto-reconnection."""
        self._running = True

        while self._running:
            # Ensure connected
            if self._state != ConnectionState.CONNECTED:
                if not await self.connect():
                    await self._reconnect()
                    continue

            # Message loop
            try:
                if self._ws is None:
                    await self._reconnect()
                    continue

                async for msg in self._ws:
                    if not self._running:
                        break

                    if not await self._handle_message(msg):
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WS-{self._connection_id}] Error in message loop: {e}")

            # Connection lost, attempt reconnect
            if self._running:
                self._state = ConnectionState.DISCONNECTED
                await self._reconnect()

    def start(self) -> asyncio.Task[None]:
        """Start the message loop as a task."""
        self._task = asyncio.create_task(self.run())
        return self._task

    async def stop(self) -> None:
        """Stop the message loop and disconnect."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=WS_CLOSE_TIMEOUT)
            except (TimeoutError, asyncio.CancelledError):
                pass

        await self.disconnect()


class WebSocketManager:
    """
    Manages multiple WebSocket connections for market data.

    Handles stream distribution across connections and provides
    a unified interface for subscribing to market data.
    """

    def __init__(
        self,
        use_testnet: bool = False,
        max_streams_per_connection: int = MAX_STREAMS_PER_CONNECTION,
    ) -> None:
        """
        Initialize WebSocket manager.

        Args:
            use_testnet: Use testnet endpoints.
            max_streams_per_connection: Max streams per WS connection.
        """
        self._base_url = BINANCE_WS_TESTNET_URL if use_testnet else BINANCE_WS_URL
        self._max_streams = max_streams_per_connection
        self._connections: list[WebSocketConnection] = []
        self._message_handlers: list[MessageHandler] = []
        self._running = False

    def add_handler(self, handler: MessageHandler) -> None:
        """
        Add a message handler.

        Args:
            handler: Async callback for messages.
        """
        self._message_handlers.append(handler)

    def remove_handler(self, handler: MessageHandler) -> None:
        """Remove a message handler."""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)

    async def _dispatch_message(self, data: dict[str, Any]) -> None:
        """Dispatch message to all handlers."""
        for handler in self._message_handlers:
            try:
                await handler(data)
            except Exception as e:
                logger.error(f"Handler error: {e}")

    def subscribe_book_tickers(self, symbols: list[str]) -> None:
        """
        Subscribe to bookTicker streams for symbols.

        Args:
            symbols: List of trading symbols.
        """
        # Build stream names
        streams = [f"{s.lower()}@bookTicker" for s in symbols]

        # Split into connection groups
        for i in range(0, len(streams), self._max_streams):
            group = streams[i : i + self._max_streams]
            conn = WebSocketConnection(
                base_url=self._base_url,
                streams=group,
                message_handler=self._dispatch_message,
                connection_id=len(self._connections),
            )
            self._connections.append(conn)

        logger.info(f"Created {len(self._connections)} connections for {len(symbols)} symbols")

    async def start(self) -> None:
        """Start all WebSocket connections."""
        self._running = True

        for conn in self._connections:
            conn.start()

        logger.info(f"Started {len(self._connections)} WebSocket connections")

    async def stop(self) -> None:
        """Stop all WebSocket connections."""
        self._running = False

        await asyncio.gather(
            *[conn.stop() for conn in self._connections],
            return_exceptions=True,
        )

        self._connections.clear()
        logger.info("All WebSocket connections stopped")

    @property
    def is_running(self) -> bool:
        """Check if manager is running."""
        return self._running

    @property
    def connection_count(self) -> int:
        """Get number of connections."""
        return len(self._connections)

    @property
    def total_message_count(self) -> int:
        """Get total messages across all connections."""
        return sum(c.message_count for c in self._connections)

    def get_connection_states(self) -> list[ConnectionState]:
        """Get state of all connections."""
        return [c.state for c in self._connections]

    def all_connected(self) -> bool:
        """Check if all connections are established."""
        return all(c.state == ConnectionState.CONNECTED for c in self._connections)

    async def wait_connected(self, timeout: float = 30.0) -> bool:
        """
        Wait for all connections to be established.

        Args:
            timeout: Maximum wait time in seconds.

        Returns:
            True if all connected within timeout.
        """
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            if self.all_connected():
                return True
            await asyncio.sleep(0.1)

        return False

    async def __aenter__(self) -> "WebSocketManager":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Async context manager exit."""
        await self.stop()
