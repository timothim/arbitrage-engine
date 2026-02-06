"""
Multi-exchange real-time price feed.

Connects to public WebSocket APIs from multiple exchanges.
No API keys required.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import orjson


logger = logging.getLogger(__name__)


# Symbol mappings per exchange (they use different formats)
SYMBOL_MAPPINGS = {
    "binance": {
        "BTC/USDT": "btcusdt", "ETH/USDT": "ethusdt", "SOL/USDT": "solusdt",
        "XRP/USDT": "xrpusdt", "BNB/USDT": "bnbusdt", "DOGE/USDT": "dogeusdt",
        "ADA/USDT": "adausdt", "AVAX/USDT": "avaxusdt",
    },
    "kraken": {
        "BTC/USDT": "XBT/USDT", "ETH/USDT": "ETH/USDT", "SOL/USDT": "SOL/USDT",
        "XRP/USDT": "XRP/USDT", "DOGE/USDT": "DOGE/USDT", "ADA/USDT": "ADA/USDT",
        "AVAX/USDT": "AVAX/USDT",
    },
    "coinbase": {
        "BTC/USDT": "BTC-USDT", "ETH/USDT": "ETH-USDT", "SOL/USDT": "SOL-USDT",
        "XRP/USDT": "XRP-USDT", "DOGE/USDT": "DOGE-USDT", "ADA/USDT": "ADA-USDT",
        "AVAX/USDT": "AVAX-USDT",
    },
    "okx": {
        "BTC/USDT": "BTC-USDT", "ETH/USDT": "ETH-USDT", "SOL/USDT": "SOL-USDT",
        "XRP/USDT": "XRP-USDT", "DOGE/USDT": "DOGE-USDT", "ADA/USDT": "ADA-USDT",
        "AVAX/USDT": "AVAX-USDT",
    },
    "bybit": {
        "BTC/USDT": "BTCUSDT", "ETH/USDT": "ETHUSDT", "SOL/USDT": "SOLUSDT",
        "XRP/USDT": "XRPUSDT", "DOGE/USDT": "DOGEUSDT", "ADA/USDT": "ADAUSDT",
        "AVAX/USDT": "AVAXUSDT",
    },
}

COMMON_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT",
]


@dataclass
class MultiExchangeState:
    """State for multi-exchange feed."""
    running: bool = False
    # symbol -> exchange -> {bid, ask}
    prices: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    ticks: int = 0
    opportunities: int = 0


class MultiExchangeFeed:
    """
    Connects to multiple exchange WebSockets for real-time price comparison.
    """

    def __init__(self) -> None:
        self._state = MultiExchangeState()
        self._tasks: list[asyncio.Task[None]] = []
        self._sessions: list[aiohttp.ClientSession] = []
        self._callbacks: list[Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]] = []

    def add_callback(self, cb: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]) -> None:
        self._callbacks.append(cb)

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        for cb in self._callbacks:
            try:
                await cb(event_type, data)
            except Exception as e:
                logger.debug(f"Callback error: {e}")

    async def start(self) -> None:
        """Start all exchange feeds."""
        if self._state.running:
            return

        self._state.running = True
        self._state.prices = {sym: {} for sym in COMMON_SYMBOLS}
        self._state.ticks = 0
        self._state.opportunities = 0

        # Start each exchange feed
        self._tasks = [
            asyncio.create_task(self._run_binance()),
            asyncio.create_task(self._run_kraken()),
            asyncio.create_task(self._run_okx()),
            asyncio.create_task(self._run_bybit()),
            asyncio.create_task(self._run_coinbase()),
            asyncio.create_task(self._check_opportunities()),
        ]

        logger.info("Multi-exchange feed started")

    async def stop(self) -> None:
        """Stop all feeds."""
        self._state.running = False

        for task in self._tasks:
            task.cancel()

        for session in self._sessions:
            await session.close()

        self._tasks = []
        self._sessions = []
        logger.info("Multi-exchange feed stopped")

    async def _update_price(self, exchange: str, symbol: str, bid: float, ask: float) -> None:
        """Update price and emit event."""
        if symbol not in self._state.prices:
            self._state.prices[symbol] = {}

        self._state.prices[symbol][exchange] = {"bid": bid, "ask": ask}
        self._state.ticks += 1

        await self._emit("price", {
            "symbol": symbol,
            "exchange": exchange,
            "bid": bid,
            "ask": ask,
        })

    async def _check_opportunities(self) -> None:
        """Periodically check for cross-exchange opportunities."""
        while self._state.running:
            await asyncio.sleep(0.5)

            for symbol, exchanges in self._state.prices.items():
                if len(exchanges) < 2:
                    continue

                # Find best bid and ask across exchanges
                best_bid = None
                best_bid_ex = None
                best_ask = None
                best_ask_ex = None

                for ex, prices in exchanges.items():
                    bid = prices.get("bid", 0)
                    ask = prices.get("ask", 0)

                    if bid > 0 and (best_bid is None or bid > best_bid):
                        best_bid = bid
                        best_bid_ex = ex

                    if ask > 0 and (best_ask is None or ask < best_ask):
                        best_ask = ask
                        best_ask_ex = ex

                if best_bid and best_ask and best_bid_ex != best_ask_ex:
                    # Calculate profit: buy at best_ask, sell at best_bid
                    profit_pct = ((best_bid - best_ask) / best_ask) * 100

                    # Only emit if there's a meaningful spread (positive or negative)
                    if abs(profit_pct) > 0.01:
                        self._state.opportunities += 1
                        await self._emit("opportunity", {
                            "type": "cross_exchange",
                            "path": symbol,
                            "profit_pct": profit_pct,
                            "details": f"Buy {best_ask_ex} ${best_ask:.2f} → Sell {best_bid_ex} ${best_bid:.2f}",
                        })

    async def _run_binance(self) -> None:
        """Connect to Binance WebSocket."""
        symbols = list(SYMBOL_MAPPINGS["binance"].values())
        streams = "/".join([f"{s}@bookTicker" for s in symbols])
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"

        while self._state.running:
            try:
                session = aiohttp.ClientSession()
                self._sessions.append(session)

                async with session.ws_connect(url, heartbeat=30) as ws:
                    await self._emit("connection", {"exchange": "Binance", "connected": True})

                    async for msg in ws:
                        if not self._state.running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = orjson.loads(msg.data)
                            if "data" in data:
                                ticker = data["data"]
                                raw_symbol = ticker.get("s", "").upper()

                                # Reverse lookup symbol
                                for std_sym, ex_sym in SYMBOL_MAPPINGS["binance"].items():
                                    if ex_sym.upper() == raw_symbol:
                                        bid = float(ticker.get("b", 0))
                                        ask = float(ticker.get("a", 0))
                                        if bid > 0 and ask > 0:
                                            await self._update_price("Binance", std_sym, bid, ask)
                                        break

            except Exception as e:
                logger.debug(f"Binance error: {e}")
                await self._emit("connection", {"exchange": "Binance", "connected": False})

            if self._state.running:
                await asyncio.sleep(3)

    async def _run_kraken(self) -> None:
        """Connect to Kraken WebSocket."""
        url = "wss://ws.kraken.com"

        while self._state.running:
            try:
                session = aiohttp.ClientSession()
                self._sessions.append(session)

                async with session.ws_connect(url, heartbeat=30) as ws:
                    # Subscribe to ticker
                    pairs = [SYMBOL_MAPPINGS["kraken"].get(s) for s in COMMON_SYMBOLS if s in SYMBOL_MAPPINGS["kraken"]]
                    pairs = [p for p in pairs if p]

                    subscribe_msg = {
                        "event": "subscribe",
                        "pair": pairs,
                        "subscription": {"name": "ticker"}
                    }
                    await ws.send_str(orjson.dumps(subscribe_msg).decode())
                    await self._emit("connection", {"exchange": "Kraken", "connected": True})

                    async for msg in ws:
                        if not self._state.running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = orjson.loads(msg.data)

                            # Kraken sends arrays for ticker data
                            if isinstance(data, list) and len(data) >= 4:
                                ticker_data = data[1]
                                pair = data[3]

                                if isinstance(ticker_data, dict) and "b" in ticker_data and "a" in ticker_data:
                                    bid = float(ticker_data["b"][0])
                                    ask = float(ticker_data["a"][0])

                                    # Reverse lookup
                                    for std_sym, ex_sym in SYMBOL_MAPPINGS["kraken"].items():
                                        if ex_sym == pair:
                                            if bid > 0 and ask > 0:
                                                await self._update_price("Kraken", std_sym, bid, ask)
                                            break

            except Exception as e:
                logger.debug(f"Kraken error: {e}")
                await self._emit("connection", {"exchange": "Kraken", "connected": False})

            if self._state.running:
                await asyncio.sleep(3)

    async def _run_okx(self) -> None:
        """Connect to OKX WebSocket."""
        url = "wss://ws.okx.com:8443/ws/v5/public"

        while self._state.running:
            try:
                session = aiohttp.ClientSession()
                self._sessions.append(session)

                async with session.ws_connect(url, heartbeat=30) as ws:
                    # Subscribe to tickers
                    args = [{"channel": "tickers", "instId": SYMBOL_MAPPINGS["okx"].get(s)}
                            for s in COMMON_SYMBOLS if s in SYMBOL_MAPPINGS["okx"]]

                    subscribe_msg = {"op": "subscribe", "args": args}
                    await ws.send_str(orjson.dumps(subscribe_msg).decode())
                    await self._emit("connection", {"exchange": "OKX", "connected": True})

                    async for msg in ws:
                        if not self._state.running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = orjson.loads(msg.data)

                            if "data" in data and isinstance(data["data"], list):
                                for ticker in data["data"]:
                                    inst_id = ticker.get("instId", "")
                                    bid = float(ticker.get("bidPx", 0) or 0)
                                    ask = float(ticker.get("askPx", 0) or 0)

                                    for std_sym, ex_sym in SYMBOL_MAPPINGS["okx"].items():
                                        if ex_sym == inst_id:
                                            if bid > 0 and ask > 0:
                                                await self._update_price("OKX", std_sym, bid, ask)
                                            break

            except Exception as e:
                logger.debug(f"OKX error: {e}")
                await self._emit("connection", {"exchange": "OKX", "connected": False})

            if self._state.running:
                await asyncio.sleep(3)

    async def _run_bybit(self) -> None:
        """Connect to Bybit WebSocket."""
        url = "wss://stream.bybit.com/v5/public/spot"

        while self._state.running:
            try:
                session = aiohttp.ClientSession()
                self._sessions.append(session)

                async with session.ws_connect(url, heartbeat=30) as ws:
                    # Subscribe to tickers
                    symbols = [SYMBOL_MAPPINGS["bybit"].get(s) for s in COMMON_SYMBOLS if s in SYMBOL_MAPPINGS["bybit"]]
                    symbols = [s for s in symbols if s]

                    subscribe_msg = {
                        "op": "subscribe",
                        "args": [f"tickers.{s}" for s in symbols]
                    }
                    await ws.send_str(orjson.dumps(subscribe_msg).decode())
                    await self._emit("connection", {"exchange": "Bybit", "connected": True})

                    async for msg in ws:
                        if not self._state.running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = orjson.loads(msg.data)

                            if "data" in data and isinstance(data["data"], dict):
                                ticker = data["data"]
                                symbol = ticker.get("symbol", "")
                                bid = float(ticker.get("bid1Price", 0) or 0)
                                ask = float(ticker.get("ask1Price", 0) or 0)

                                for std_sym, ex_sym in SYMBOL_MAPPINGS["bybit"].items():
                                    if ex_sym == symbol:
                                        if bid > 0 and ask > 0:
                                            await self._update_price("Bybit", std_sym, bid, ask)
                                        break

            except Exception as e:
                logger.debug(f"Bybit error: {e}")
                await self._emit("connection", {"exchange": "Bybit", "connected": False})

            if self._state.running:
                await asyncio.sleep(3)

    async def _run_coinbase(self) -> None:
        """Connect to Coinbase WebSocket."""
        url = "wss://ws-feed.exchange.coinbase.com"

        while self._state.running:
            try:
                session = aiohttp.ClientSession()
                self._sessions.append(session)

                async with session.ws_connect(url, heartbeat=30) as ws:
                    products = [SYMBOL_MAPPINGS["coinbase"].get(s) for s in COMMON_SYMBOLS if s in SYMBOL_MAPPINGS["coinbase"]]
                    products = [p for p in products if p]

                    subscribe_msg = {
                        "type": "subscribe",
                        "product_ids": products,
                        "channels": ["ticker"]
                    }
                    await ws.send_str(orjson.dumps(subscribe_msg).decode())
                    await self._emit("connection", {"exchange": "Coinbase", "connected": True})

                    async for msg in ws:
                        if not self._state.running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = orjson.loads(msg.data)

                            if data.get("type") == "ticker":
                                product_id = data.get("product_id", "")
                                bid = float(data.get("best_bid", 0) or 0)
                                ask = float(data.get("best_ask", 0) or 0)

                                for std_sym, ex_sym in SYMBOL_MAPPINGS["coinbase"].items():
                                    if ex_sym == product_id:
                                        if bid > 0 and ask > 0:
                                            await self._update_price("Coinbase", std_sym, bid, ask)
                                        break

            except Exception as e:
                logger.debug(f"Coinbase error: {e}")
                await self._emit("connection", {"exchange": "Coinbase", "connected": False})

            if self._state.running:
                await asyncio.sleep(3)

    @property
    def state(self) -> MultiExchangeState:
        return self._state
