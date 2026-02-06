"""
FastAPI server for the arbitrage dashboard.

Supports triangular arbitrage, cross-exchange arbitrage (simulated and live).
"""

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from arbitrage.dashboard.live_feed import LiveDataFeed
from arbitrage.dashboard.multi_exchange_feed import MultiExchangeFeed


logger = logging.getLogger(__name__)

# Global state
live_feed: LiveDataFeed | None = None
multi_exchange_feed: MultiExchangeFeed | None = None
simulation_task: asyncio.Task[None] | None = None
connected_clients: list[WebSocket] = []
current_mode: str = "triangular"
is_running: bool = False


@dataclass
class SimulationState:
    prices: dict[str, dict[str, Any]] = field(default_factory=dict)
    ticks: int = 0
    opportunities: int = 0


sim_state = SimulationState()

# Triangular arbitrage config
TRI_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "ETHBTC",
    "BNBBTC",
    "BNBETH",
    "SOLUSDT",
    "SOLBTC",
    "XRPUSDT",
    "XRPBTC",
]

TRI_BASE_PRICES = {
    "BTCUSDT": 97500.0,
    "ETHUSDT": 3450.0,
    "BNBUSDT": 680.0,
    "ETHBTC": 0.0354,
    "BNBBTC": 0.0070,
    "BNBETH": 0.197,
    "SOLUSDT": 195.0,
    "SOLBTC": 0.0020,
    "XRPUSDT": 2.45,
    "XRPBTC": 0.0000251,
}

TRI_PATHS = [
    ("USDT → BTC → ETH → USDT", ["BTCUSDT", "ETHBTC", "ETHUSDT"]),
    ("USDT → BTC → BNB → USDT", ["BTCUSDT", "BNBBTC", "BNBUSDT"]),
    ("USDT → ETH → BNB → USDT", ["ETHUSDT", "BNBETH", "BNBUSDT"]),
    ("USDT → BTC → SOL → USDT", ["BTCUSDT", "SOLBTC", "SOLUSDT"]),
]

# Cross-exchange simulation config
CROSS_SIM_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "AVAX/USDT",
]
CROSS_SIM_PRICES = {
    "BTC/USDT": 97500.0,
    "ETH/USDT": 3450.0,
    "SOL/USDT": 195.0,
    "XRP/USDT": 2.45,
    "DOGE/USDT": 0.32,
    "ADA/USDT": 0.95,
    "AVAX/USDT": 38.0,
}
SIM_EXCHANGES = ["Binance", "Kraken", "Coinbase", "OKX", "Bybit"]


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    global live_feed, multi_exchange_feed
    live_feed = LiveDataFeed(fee_rate=0.001, min_profit_threshold=-0.5)
    live_feed.add_event_callback(broadcast_event)
    multi_exchange_feed = MultiExchangeFeed()
    multi_exchange_feed.add_callback(broadcast_event)
    yield
    if live_feed and live_feed.state.running:
        await live_feed.stop()
    if multi_exchange_feed and multi_exchange_feed.state.running:
        await multi_exchange_feed.stop()
    if simulation_task:
        simulation_task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="Arbitrage Engine", version="1.0.0", lifespan=lifespan)
    app.get("/", response_class=HTMLResponse)(get_dashboard)
    app.get("/how-it-works", response_class=HTMLResponse)(get_docs)
    app.post("/api/start")(start_bot)
    app.post("/api/stop")(stop_bot)
    app.post("/api/mode")(set_mode)
    app.get("/api/status")(get_status)
    app.websocket("/ws")(websocket_endpoint)
    return app


async def broadcast_event(event_type: str, data: dict[str, Any]) -> None:
    if not connected_clients:
        return
    import orjson

    message = orjson.dumps({"type": event_type, "data": data}).decode()
    disconnected = []
    for client in connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        if client in connected_clients:
            connected_clients.remove(client)


async def run_triangular_simulation() -> None:
    prices = {s: TRI_BASE_PRICES[s] for s in TRI_SYMBOLS}
    opp_counter = 0

    while is_running:
        for symbol in TRI_SYMBOLS:
            base = TRI_BASE_PRICES[symbol]
            prices[symbol] += random.gauss(0, base * 0.0001)
            prices[symbol] = max(base * 0.95, min(base * 1.05, prices[symbol]))
            spread = prices[symbol] * 0.0002
            sim_state.ticks += 1

            await broadcast_event(
                "price",
                {
                    "symbol": symbol,
                    "bid": prices[symbol] - spread / 2,
                    "ask": prices[symbol] + spread / 2,
                },
            )

        opp_counter += 1
        if opp_counter >= 12:
            opp_counter = 0
            path_name, symbols = random.choice(TRI_PATHS)
            profit = (
                random.uniform(0.02, 0.18) if random.random() < 0.4 else random.uniform(-0.25, 0.0)
            )
            sim_state.opportunities += 1

            await broadcast_event(
                "opportunity",
                {
                    "type": "triangular",
                    "path": path_name,
                    "profit_pct": profit,
                    "details": f"via {' → '.join(symbols)}",
                },
            )

        await asyncio.sleep(0.1)


async def run_cross_exchange_simulation() -> None:
    exchange_prices = {
        ex: {s: CROSS_SIM_PRICES[s] for s in CROSS_SIM_SYMBOLS} for ex in SIM_EXCHANGES
    }
    opp_counter = 0

    while is_running:
        for symbol in CROSS_SIM_SYMBOLS:
            base = CROSS_SIM_PRICES[symbol]
            for exchange in SIM_EXCHANGES:
                exchange_prices[exchange][symbol] += random.gauss(0, base * 0.00012)
                exchange_prices[exchange][symbol] = max(
                    base * 0.97, min(base * 1.03, exchange_prices[exchange][symbol])
                )

            sim_state.ticks += 1

            for exchange in SIM_EXCHANGES:
                price = exchange_prices[exchange][symbol]
                spread = price * 0.0003
                await broadcast_event(
                    "price",
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "bid": price - spread / 2,
                        "ask": price + spread / 2,
                    },
                )

        opp_counter += 1
        if opp_counter >= 8:
            opp_counter = 0
            symbol = random.choice(CROSS_SIM_SYMBOLS)
            ex_prices = [(ex, exchange_prices[ex][symbol]) for ex in SIM_EXCHANGES]
            ex_prices.sort(key=lambda x: x[1])
            low_ex, low_price = ex_prices[0]
            high_ex, high_price = ex_prices[-1]

            if random.random() < 0.35:
                profit = random.uniform(0.05, 0.22)
            else:
                profit = ((high_price - low_price) / low_price) * 100 - 0.15

            sim_state.opportunities += 1
            await broadcast_event(
                "opportunity",
                {
                    "type": "cross_exchange",
                    "path": symbol,
                    "profit_pct": profit,
                    "details": f"Buy {low_ex} → Sell {high_ex}",
                },
            )

        await asyncio.sleep(0.06)


async def get_dashboard() -> HTMLResponse:
    return HTMLResponse(content=DASHBOARD_HTML)


async def get_docs() -> HTMLResponse:
    return HTMLResponse(content=DOCS_HTML)


async def start_bot() -> dict[str, Any]:
    global is_running, simulation_task

    if is_running:
        return {"status": "already_running"}

    is_running = True
    sim_state.ticks = 0
    sim_state.opportunities = 0

    if current_mode == "triangular":
        simulation_task = asyncio.create_task(run_triangular_simulation())
    elif current_mode == "cross_sim":
        simulation_task = asyncio.create_task(run_cross_exchange_simulation())
    elif current_mode == "cross_live":
        if multi_exchange_feed:
            await multi_exchange_feed.start()
    elif current_mode == "live":
        if live_feed:
            await live_feed.start()

    await broadcast_event("status", {"running": True, "mode": current_mode})
    return {"status": "started", "mode": current_mode}


async def stop_bot() -> dict[str, Any]:
    global is_running, simulation_task

    if not is_running:
        return {"status": "not_running"}

    is_running = False

    if current_mode in ["triangular", "cross_sim"] and simulation_task:
        simulation_task.cancel()
        simulation_task = None
    elif current_mode == "cross_live" and multi_exchange_feed:
        await multi_exchange_feed.stop()
    elif current_mode == "live" and live_feed:
        await live_feed.stop()

    await broadcast_event("status", {"running": False, "mode": current_mode})
    return {"status": "stopped"}


async def set_mode(mode: str = "triangular") -> dict[str, Any]:
    global current_mode

    if mode not in ["triangular", "cross_sim", "cross_live", "live"]:
        return {"error": "Invalid mode"}

    if is_running:
        await stop_bot()

    current_mode = mode
    await broadcast_event("mode", {"mode": mode})
    return {"mode": mode}


async def get_status() -> dict[str, Any]:
    return {
        "running": is_running,
        "mode": current_mode,
        "ticks": sim_state.ticks,
        "opportunities": sim_state.opportunities,
    }


async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    connected_clients.append(websocket)

    import orjson

    await websocket.send_text(
        orjson.dumps(
            {"type": "init", "data": {"running": is_running, "mode": current_mode}}
        ).decode()
    )

    try:
        while True:
            data = await websocket.receive_text()
            msg = orjson.loads(data)
            if msg.get("action") == "start":
                await start_bot()
            elif msg.get("action") == "stop":
                await stop_bot()
            elif msg.get("action") == "setMode":
                await set_mode(msg.get("mode", "triangular"))
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arbitrage Engine</title>
    <style>
        :root {
            --bg: #09090b; --bg2: #18181b; --bg3: #27272a;
            --border: #3f3f46; --text: #fafafa; --text2: #a1a1aa; --text3: #71717a;
            --accent: #3b82f6; --green: #22c55e; --red: #ef4444; --yellow: #eab308;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Inter", sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
        .app { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }

        .info { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; padding: 20px 24px; margin-bottom: 28px; }
        .info h2 { font-size: 15px; font-weight: 600; margin-bottom: 10px; }
        .info p { font-size: 13px; color: var(--text2); line-height: 1.8; margin-bottom: 6px; }
        .info strong { color: var(--text); }
        .info .tag { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; margin-left: 4px; }
        .info .sim { background: rgba(234,179,8,0.2); color: var(--yellow); }
        .info .live { background: rgba(34,197,94,0.2); color: var(--green); }

        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 16px; }
        .logo { display: flex; align-items: center; gap: 12px; }
        .logo-icon { width: 36px; height: 36px; background: linear-gradient(135deg, var(--accent), #8b5cf6); border-radius: 10px; }
        .logo-text { font-size: 20px; font-weight: 600; }
        .docs-link { font-size: 13px; color: var(--accent); text-decoration: none; margin-left: 16px; padding: 6px 12px; background: rgba(59,130,246,0.1); border-radius: 6px; }
        .docs-link:hover { background: rgba(59,130,246,0.2); }
        .header-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

        .status { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 6px; font-size: 13px; font-weight: 500; }
        .status.off { background: rgba(239,68,68,0.1); color: var(--red); }
        .status.on { background: rgba(34,197,94,0.1); color: var(--green); }
        .status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
        .status.on .status-dot { animation: pulse 2s infinite; }
        @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }

        .tabs { display: flex; gap: 4px; background: var(--bg2); padding: 4px; border-radius: 8px; border: 1px solid var(--border); flex-wrap: wrap; }
        .tab { padding: 8px 12px; border: none; border-radius: 6px; font-size: 11px; font-weight: 500; cursor: pointer; background: transparent; color: var(--text2); transition: all 0.15s; white-space: nowrap; }
        .tab.active { background: var(--accent); color: white; }
        .tab:not(.active):hover { background: var(--bg3); color: var(--text); }

        .controls { display: flex; gap: 12px; margin-bottom: 20px; }
        .btn { padding: 10px 20px; border: none; border-radius: 8px; font-size: 14px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
        .btn-start { background: var(--green); color: white; }
        .btn-start:hover { background: #16a34a; }
        .btn-start:disabled { background: var(--bg3); color: var(--text3); cursor: not-allowed; }
        .btn-stop { background: var(--bg3); color: var(--text); border: 1px solid var(--border); }
        .btn-stop:hover { background: var(--border); }
        .btn-stop:disabled { color: var(--text3); cursor: not-allowed; }

        .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
        .stat { background: var(--bg2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
        .stat-label { font-size: 11px; color: var(--text3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
        .stat-value { font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; }

        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        @media (max-width: 800px) { .grid { grid-template-columns: 1fr; } .stats { grid-template-columns: 1fr 1fr; } }

        .card { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
        .card-header { padding: 14px 18px; border-bottom: 1px solid var(--border); font-size: 12px; font-weight: 500; color: var(--text2); text-transform: uppercase; letter-spacing: 0.05em; }
        .card-body { max-height: 400px; overflow-y: auto; }

        .row { display: flex; justify-content: space-between; align-items: center; padding: 10px 18px; border-bottom: 1px solid var(--border); font-size: 13px; font-variant-numeric: tabular-nums; }
        .row:last-child { border-bottom: none; }
        .row-label { font-weight: 500; }
        .row-values { display: flex; gap: 16px; }
        .bid { color: var(--green); }
        .ask { color: var(--red); }

        .ex-group { padding: 12px 18px; border-bottom: 1px solid var(--border); }
        .ex-group:last-child { border-bottom: none; }
        .ex-symbol { font-weight: 600; margin-bottom: 8px; font-size: 14px; }
        .ex-row { display: flex; justify-content: space-between; font-size: 12px; color: var(--text2); padding: 4px 0; }
        .ex-name { min-width: 70px; }

        .opp { display: flex; align-items: center; padding: 10px 18px; border-bottom: 1px solid var(--border); font-size: 13px; }
        .opp:last-child { border-bottom: none; }
        .opp.profit { background: rgba(34,197,94,0.05); }
        .opp.loss { background: rgba(113,113,122,0.05); }
        .opp-time { color: var(--text3); font-variant-numeric: tabular-nums; margin-right: 10px; font-size: 11px; }
        .opp-path { color: var(--accent); font-weight: 500; }
        .opp-detail { color: var(--text3); font-size: 11px; margin-left: 8px; flex: 1; }
        .opp-profit { font-weight: 600; }
        .opp-profit.pos { color: var(--green); }
        .opp-profit.neg { color: var(--text3); }

        .empty { padding: 40px; text-align: center; color: var(--text3); font-size: 13px; }

        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
    </style>
</head>
<body>
    <div class="app">
        <div class="info">
            <h2>Arbitrage Detection Engine</h2>
            <p><strong>Triangular</strong> <span class="tag sim">Simulated</span> — Price inefficiencies across three pairs on one exchange (USDT → BTC → ETH → USDT).</p>
            <p><strong>Cross-Exchange (Sim)</strong> <span class="tag sim">Simulated</span> — Fake data comparing prices across 5 exchanges to demonstrate the concept.</p>
            <p><strong>Cross-Exchange (Live)</strong> <span class="tag live">Real Data</span> — Real-time prices from Binance, Kraken, Coinbase, OKX & Bybit via WebSocket.</p>
            <p><strong>Triangular (Live)</strong> <span class="tag live">Real Data</span> — Real Binance prices for triangular arbitrage detection.</p>
        </div>

        <header class="header">
            <div class="logo">
                <div class="logo-icon"></div>
                <span class="logo-text">Arbitrage Engine</span>
                <a href="/how-it-works" class="docs-link">How It Works →</a>
            </div>
            <div class="header-right">
                <div class="tabs">
                    <button class="tab active" id="tab1" onclick="setMode('triangular')">Triangular (Sim)</button>
                    <button class="tab" id="tab2" onclick="setMode('cross_sim')">Cross-Exchange (Sim)</button>
                    <button class="tab" id="tab3" onclick="setMode('cross_live')">Cross-Exchange (Live)</button>
                    <button class="tab" id="tab4" onclick="setMode('live')">Triangular (Live)</button>
                </div>
                <div class="status off" id="status">
                    <span class="status-dot"></span>
                    <span id="statusText">Stopped</span>
                </div>
            </div>
        </header>

        <div class="controls">
            <button class="btn btn-start" id="startBtn" onclick="startBot()">Start</button>
            <button class="btn btn-stop" id="stopBtn" onclick="stopBot()" disabled>Stop</button>
        </div>

        <div class="stats">
            <div class="stat"><div class="stat-label">Ticks</div><div class="stat-value" id="ticks">0</div></div>
            <div class="stat"><div class="stat-label">Opportunities</div><div class="stat-value" id="opps">0</div></div>
            <div class="stat"><div class="stat-label">Symbols</div><div class="stat-value" id="symbols">0</div></div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="card-header">Prices</div>
                <div class="card-body" id="prices"><div class="empty">Start the bot to see prices</div></div>
            </div>
            <div class="card">
                <div class="card-header">Opportunities</div>
                <div class="card-body" id="log"><div class="empty">Start the bot to detect opportunities</div></div>
            </div>
        </div>
    </div>

    <script>
        let ws, prices = {}, logs = [], mode = 'triangular', running = false, ticks = 0, opps = 0;
        const MODES = ['triangular', 'cross_sim', 'cross_live', 'live'];

        function connect() {
            const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${proto}//${location.host}/ws`);
            ws.onopen = () => console.log('Connected');
            ws.onclose = () => setTimeout(connect, 2000);
            ws.onmessage = e => handle(JSON.parse(e.data));
        }

        function handle(msg) {
            if (msg.type === 'init') {
                mode = msg.data.mode;
                updateTabs();
                updateStatus(msg.data.running);
            } else if (msg.type === 'status') {
                updateStatus(msg.data.running);
            } else if (msg.type === 'mode') {
                mode = msg.data.mode;
                updateTabs();
                reset();
            } else if (msg.type === 'price') {
                const key = msg.data.exchange ? `${msg.data.symbol}@${msg.data.exchange}` : msg.data.symbol;
                prices[key] = msg.data;
                ticks++;
                document.getElementById('ticks').textContent = ticks.toLocaleString();
                document.getElementById('symbols').textContent = new Set(Object.values(prices).map(p => p.symbol)).size;
                renderPrices();
            } else if (msg.type === 'opportunity') {
                opps++;
                document.getElementById('opps').textContent = opps.toLocaleString();
                addOpp(msg.data);
            } else if (msg.type === 'connection') {
                console.log(`${msg.data.exchange}: ${msg.data.connected ? 'connected' : 'disconnected'}`);
            }
        }

        function reset() {
            ticks = 0; opps = 0; prices = {}; logs = [];
            document.getElementById('ticks').textContent = '0';
            document.getElementById('opps').textContent = '0';
            document.getElementById('symbols').textContent = '0';
            renderPrices(); renderLogs();
        }

        function updateStatus(r) {
            running = r;
            document.getElementById('status').className = r ? 'status on' : 'status off';
            document.getElementById('statusText').textContent = r ? 'Running' : 'Stopped';
            document.getElementById('startBtn').disabled = r;
            document.getElementById('stopBtn').disabled = !r;
        }

        function updateTabs() {
            MODES.forEach((m, i) => {
                document.getElementById('tab' + (i+1)).className = mode === m ? 'tab active' : 'tab';
            });
        }

        function startBot() { ws?.send(JSON.stringify({action:'start'})); }
        function stopBot() { ws?.send(JSON.stringify({action:'stop'})); }
        function setMode(m) { if (m !== mode) ws?.send(JSON.stringify({action:'setMode',mode:m})); }

        function renderPrices() {
            const c = document.getElementById('prices');
            const entries = Object.entries(prices).sort((a,b) => a[0].localeCompare(b[0]));
            if (!entries.length) { c.innerHTML = '<div class="empty">Start the bot to see prices</div>'; return; }

            const isCross = mode === 'cross_sim' || mode === 'cross_live';
            if (isCross) {
                const bySymbol = {};
                entries.forEach(([k, v]) => {
                    if (!bySymbol[v.symbol]) bySymbol[v.symbol] = [];
                    bySymbol[v.symbol].push(v);
                });
                c.innerHTML = Object.entries(bySymbol).sort((a,b) => a[0].localeCompare(b[0])).map(([sym, exs]) => `
                    <div class="ex-group">
                        <div class="ex-symbol">${sym}</div>
                        ${exs.sort((a,b) => a.exchange.localeCompare(b.exchange)).map(e => `
                            <div class="ex-row">
                                <span class="ex-name">${e.exchange}</span>
                                <span><span class="bid">${fmt(e.bid)}</span> / <span class="ask">${fmt(e.ask)}</span></span>
                            </div>
                        `).join('')}
                    </div>
                `).join('');
            } else {
                c.innerHTML = entries.map(([k, v]) => `
                    <div class="row">
                        <span class="row-label">${v.symbol}</span>
                        <div class="row-values">
                            <span class="bid">${fmt(v.bid)}</span>
                            <span class="ask">${fmt(v.ask)}</span>
                        </div>
                    </div>
                `).join('');
            }
        }

        function fmt(p) {
            if (p >= 1000) return p.toFixed(2);
            if (p >= 1) return p.toFixed(4);
            if (p >= 0.01) return p.toFixed(5);
            return p.toFixed(8);
        }

        function addOpp(d) {
            const time = new Date().toLocaleTimeString('en-US', {hour12:false});
            logs.unshift({time, path: d.path, profit: d.profit_pct, details: d.details || ''});
            if (logs.length > 50) logs.pop();
            renderLogs();
        }

        function renderLogs() {
            const c = document.getElementById('log');
            if (!logs.length) { c.innerHTML = '<div class="empty">Start the bot to detect opportunities</div>'; return; }
            c.innerHTML = logs.map(l => {
                const cls = l.profit > 0 ? 'profit' : 'loss';
                const pcls = l.profit > 0 ? 'pos' : 'neg';
                const sign = l.profit > 0 ? '+' : '';
                return `<div class="opp ${cls}">
                    <span class="opp-time">${l.time}</span>
                    <span class="opp-path">${l.path}</span>
                    <span class="opp-detail">${l.details}</span>
                    <span class="opp-profit ${pcls}">${sign}${l.profit.toFixed(3)}%</span>
                </div>`;
            }).join('');
        }

        connect();
    </script>
</body>
</html>"""


DOCS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>How It Works - Arbitrage Engine</title>
    <style>
        :root {
            --bg: #09090b; --bg2: #18181b; --bg3: #27272a;
            --border: #3f3f46; --text: #fafafa; --text2: #a1a1aa; --text3: #71717a;
            --accent: #3b82f6; --green: #22c55e; --red: #ef4444; --yellow: #eab308;
            --purple: #a855f7; --cyan: #06b6d4;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Inter", sans-serif; background: var(--bg); color: var(--text); line-height: 1.7; }

        .nav { position: fixed; top: 0; left: 0; right: 0; background: rgba(9,9,11,0.9); backdrop-filter: blur(12px); border-bottom: 1px solid var(--border); z-index: 100; }
        .nav-inner { max-width: 900px; margin: 0 auto; padding: 14px 24px; display: flex; justify-content: space-between; align-items: center; }
        .nav-logo { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--text); font-weight: 600; font-size: 15px; }
        .nav-logo-icon { width: 28px; height: 28px; background: linear-gradient(135deg, var(--accent), var(--purple)); border-radius: 8px; }
        .nav-link { color: var(--accent); text-decoration: none; font-size: 14px; font-weight: 500; }
        .nav-link:hover { text-decoration: underline; }

        .hero { padding: 120px 24px 60px; text-align: center; border-bottom: 1px solid var(--border); }
        .hero h1 { font-size: 42px; font-weight: 700; margin-bottom: 16px; background: linear-gradient(135deg, var(--text), var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .hero p { font-size: 18px; color: var(--text2); max-width: 600px; margin: 0 auto; }

        .content { max-width: 900px; margin: 0 auto; padding: 60px 24px 100px; }

        .section { margin-bottom: 60px; }
        .section h2 { font-size: 28px; font-weight: 600; margin-bottom: 24px; display: flex; align-items: center; gap: 12px; }
        .section h2::before { content: ''; width: 4px; height: 28px; background: var(--accent); border-radius: 2px; }
        .section h3 { font-size: 18px; font-weight: 600; margin: 32px 0 16px; color: var(--text); }
        .section p { color: var(--text2); margin-bottom: 16px; font-size: 15px; }
        .section ul, .section ol { color: var(--text2); margin: 16px 0 16px 24px; font-size: 15px; }
        .section li { margin-bottom: 8px; }
        .section strong { color: var(--text); }

        .card { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin: 24px 0; }
        .card-title { font-size: 14px; font-weight: 600; color: var(--accent); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.05em; }

        .diagram { background: var(--bg3); border-radius: 12px; padding: 32px; margin: 24px 0; text-align: center; font-family: ui-monospace, "SF Mono", monospace; }
        .diagram-title { font-size: 12px; color: var(--text3); margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.1em; }
        .diagram-content { font-size: 14px; color: var(--cyan); line-height: 2; }
        .diagram-arrow { color: var(--yellow); }

        .formula { background: linear-gradient(135deg, rgba(59,130,246,0.1), rgba(168,85,247,0.1)); border: 1px solid rgba(59,130,246,0.3); border-radius: 12px; padding: 24px; margin: 24px 0; font-family: ui-monospace, "SF Mono", monospace; }
        .formula-label { font-size: 11px; color: var(--accent); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.1em; }
        .formula-content { font-size: 15px; color: var(--text); line-height: 2.2; }
        .formula-var { color: var(--cyan); }
        .formula-op { color: var(--yellow); }

        code { background: var(--bg3); padding: 2px 8px; border-radius: 4px; font-family: ui-monospace, "SF Mono", monospace; font-size: 13px; color: var(--cyan); }

        pre { background: var(--bg3); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin: 20px 0; overflow-x: auto; font-family: ui-monospace, "SF Mono", monospace; font-size: 13px; line-height: 1.6; }
        pre code { background: none; padding: 0; }
        .code-comment { color: var(--text3); }
        .code-keyword { color: var(--purple); }
        .code-string { color: var(--green); }
        .code-number { color: var(--yellow); }
        .code-func { color: var(--cyan); }

        .tech-stack { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 24px 0; }
        .tech-item { background: var(--bg2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
        .tech-name { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
        .tech-desc { font-size: 13px; color: var(--text3); }

        .file-tree { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin: 24px 0; font-family: ui-monospace, "SF Mono", monospace; font-size: 13px; }
        .file-tree-line { color: var(--text3); line-height: 1.8; }
        .file-tree-dir { color: var(--accent); }
        .file-tree-file { color: var(--text2); }
        .file-tree-desc { color: var(--text3); font-size: 11px; margin-left: 8px; }

        .highlight { background: rgba(59,130,246,0.15); border-left: 3px solid var(--accent); padding: 16px 20px; margin: 24px 0; border-radius: 0 8px 8px 0; }
        .highlight p { margin: 0; color: var(--text); }

        .exchanges { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 24px 0; }
        .exchange { background: var(--bg2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; text-align: center; }
        .exchange-name { font-weight: 600; font-size: 14px; }
        .exchange-proto { font-size: 11px; color: var(--text3); margin-top: 4px; }
        @media (max-width: 700px) { .exchanges { grid-template-columns: repeat(2, 1fr); } }

        .toc { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin: 40px 0; }
        .toc-title { font-size: 14px; font-weight: 600; margin-bottom: 16px; color: var(--text); }
        .toc-list { list-style: none; margin: 0; padding: 0; }
        .toc-list li { margin: 8px 0; }
        .toc-list a { color: var(--accent); text-decoration: none; font-size: 14px; }
        .toc-list a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <nav class="nav">
        <div class="nav-inner">
            <a href="/" class="nav-logo">
                <div class="nav-logo-icon"></div>
                Arbitrage Engine
            </a>
            <a href="/" class="nav-link">← Back to Dashboard</a>
        </div>
    </nav>

    <div class="hero">
        <h1>How It Works</h1>
        <p>A deep dive into the technical architecture of the arbitrage detection engine — from WebSocket connections to opportunity detection algorithms.</p>
    </div>

    <div class="content">
        <div class="toc">
            <div class="toc-title">Table of Contents</div>
            <ol class="toc-list">
                <li><a href="#overview">1. Project Overview</a></li>
                <li><a href="#triangular">2. Triangular Arbitrage</a></li>
                <li><a href="#cross-exchange">3. Cross-Exchange Arbitrage</a></li>
                <li><a href="#architecture">4. Code Architecture</a></li>
                <li><a href="#websockets">5. WebSocket Connections</a></li>
                <li><a href="#detection">6. Opportunity Detection</a></li>
                <li><a href="#realtime">7. Real-Time Dashboard</a></li>
                <li><a href="#stack">8. Tech Stack</a></li>
            </ol>
        </div>

        <section class="section" id="overview">
            <h2>Project Overview</h2>
            <p>This arbitrage detection engine is a <strong>high-frequency trading research tool</strong> built to identify price inefficiencies across cryptocurrency markets. It demonstrates two types of arbitrage strategies:</p>
            <ul>
                <li><strong>Triangular Arbitrage</strong> — Exploiting price discrepancies between three trading pairs on a single exchange</li>
                <li><strong>Cross-Exchange Arbitrage</strong> — Profiting from price differences of the same asset across multiple exchanges</li>
            </ul>
            <p>The engine connects to <strong>real exchange WebSocket APIs</strong> to receive live market data, processes thousands of price updates per second, and identifies profitable opportunities in real-time.</p>

            <div class="highlight">
                <p><strong>Note:</strong> This is a detection and monitoring tool for educational purposes. Actual execution of trades requires API keys, proper risk management, and consideration of trading fees, slippage, and withdrawal times.</p>
            </div>
        </section>

        <section class="section" id="triangular">
            <h2>Triangular Arbitrage</h2>
            <p>Triangular arbitrage exploits pricing inefficiencies between <strong>three related trading pairs</strong> on a single exchange. The idea is to start with one currency, trade through two others, and end up with more of the original currency than you started with.</p>

            <h3>How It Works</h3>
            <div class="diagram">
                <div class="diagram-title">Example: USDT → BTC → ETH → USDT</div>
                <div class="diagram-content">
                    Start: <span class="formula-var">1000 USDT</span><br><br>
                    Step 1: Buy BTC with USDT <span class="diagram-arrow">→</span> <span class="formula-var">0.01025 BTC</span> (at $97,560)<br>
                    Step 2: Buy ETH with BTC <span class="diagram-arrow">→</span> <span class="formula-var">0.2896 ETH</span> (at 0.0354 ETH/BTC)<br>
                    Step 3: Sell ETH for USDT <span class="diagram-arrow">→</span> <span class="formula-var">1001.12 USDT</span> (at $3,456)<br><br>
                    Profit: <span style="color: var(--green);">+$1.12 (0.112%)</span>
                </div>
            </div>

            <h3>The Mathematics</h3>
            <p>For a triangle path A → B → C → A, we calculate the <strong>gross return</strong> based on whether we're buying or selling at each leg:</p>

            <div class="formula">
                <div class="formula-label">Profit Calculation Formula</div>
                <div class="formula-content">
                    <span class="formula-var">gross_return</span> <span class="formula-op">=</span> (1 / <span class="formula-var">ask₁</span>) <span class="formula-op">×</span> (1 / <span class="formula-var">ask₂</span>) <span class="formula-op">×</span> <span class="formula-var">bid₃</span><br>
                    <span class="formula-var">net_return</span> <span class="formula-op">=</span> <span class="formula-var">gross_return</span> <span class="formula-op">×</span> (1 - <span class="formula-var">fee</span>)<sup>3</sup><br>
                    <span class="formula-var">profit_pct</span> <span class="formula-op">=</span> (<span class="formula-var">net_return</span> - 1) <span class="formula-op">×</span> 100
                </div>
            </div>

            <p>The formula accounts for:</p>
            <ul>
                <li><strong>Ask prices</strong> (what you pay when buying)</li>
                <li><strong>Bid prices</strong> (what you receive when selling)</li>
                <li><strong>Trading fees</strong> applied at each leg (typically 0.1% per trade on Binance)</li>
            </ul>

            <h3>Implementation in Code</h3>
            <pre><code><span class="code-comment"># From strategy/calculator.py</span>
<span class="code-keyword">def</span> <span class="code-func">calculate</span>(self, path: TrianglePath, orderbook: OrderbookManager) -> CalcResult:
    amount = <span class="code-number">1.0</span>  <span class="code-comment"># Start with 1 unit</span>

    <span class="code-keyword">for</span> leg <span class="code-keyword">in</span> path.legs:
        bbo = orderbook.get(leg.symbol)  <span class="code-comment"># Get best bid/offer</span>

        <span class="code-keyword">if</span> leg.side == OrderSide.BUY:
            price = bbo.ask_price  <span class="code-comment"># Pay the ask when buying</span>
            amount = (amount / price) * (<span class="code-number">1</span> - self.fee_rate)
        <span class="code-keyword">else</span>:
            price = bbo.bid_price  <span class="code-comment"># Receive the bid when selling</span>
            amount = (amount * price) * (<span class="code-number">1</span> - self.fee_rate)

    <span class="code-keyword">return</span> CalcResult(net_return=amount)</code></pre>
        </section>

        <section class="section" id="cross-exchange">
            <h2>Cross-Exchange Arbitrage</h2>
            <p>Cross-exchange arbitrage exploits price differences for the <strong>same asset across different exchanges</strong>. If Bitcoin is trading at $97,500 on Binance but $97,600 on Kraken, you could theoretically buy on Binance and sell on Kraken for a $100 profit.</p>

            <h3>Connected Exchanges</h3>
            <div class="exchanges">
                <div class="exchange">
                    <div class="exchange-name">Binance</div>
                    <div class="exchange-proto">WebSocket</div>
                </div>
                <div class="exchange">
                    <div class="exchange-name">Kraken</div>
                    <div class="exchange-proto">WebSocket</div>
                </div>
                <div class="exchange">
                    <div class="exchange-name">Coinbase</div>
                    <div class="exchange-proto">WebSocket</div>
                </div>
                <div class="exchange">
                    <div class="exchange-name">OKX</div>
                    <div class="exchange-proto">WebSocket</div>
                </div>
                <div class="exchange">
                    <div class="exchange-name">Bybit</div>
                    <div class="exchange-proto">WebSocket</div>
                </div>
            </div>

            <h3>How It Works</h3>
            <div class="diagram">
                <div class="diagram-title">Cross-Exchange Opportunity Detection</div>
                <div class="diagram-content">
                    BTC/USDT Prices:<br><br>
                    Binance: <span class="formula-var">$97,480</span> bid / <span class="formula-var">$97,485</span> ask<br>
                    Kraken: <span class="formula-var">$97,520</span> bid / <span class="formula-var">$97,530</span> ask<br>
                    Coinbase: <span class="formula-var">$97,495</span> bid / <span class="formula-var">$97,500</span> ask<br><br>
                    <span class="diagram-arrow">→</span> Best Ask (buy): Binance @ $97,485<br>
                    <span class="diagram-arrow">→</span> Best Bid (sell): Kraken @ $97,520<br><br>
                    Spread: <span style="color: var(--green);">+$35 (0.036%)</span>
                </div>
            </div>

            <div class="formula">
                <div class="formula-label">Cross-Exchange Profit Formula</div>
                <div class="formula-content">
                    <span class="formula-var">profit_pct</span> <span class="formula-op">=</span> ((<span class="formula-var">best_bid</span> - <span class="formula-var">best_ask</span>) / <span class="formula-var">best_ask</span>) <span class="formula-op">×</span> 100
                </div>
            </div>

            <div class="card">
                <div class="card-title">Real-World Considerations</div>
                <p style="color: var(--text2); margin: 0;">In practice, cross-exchange arbitrage must account for:</p>
                <ul style="margin-top: 12px;">
                    <li>Trading fees on both exchanges (~0.1% each)</li>
                    <li>Withdrawal fees and transfer times</li>
                    <li>Slippage (price movement during execution)</li>
                    <li>Capital requirements (funds on multiple exchanges)</li>
                </ul>
            </div>
        </section>

        <section class="section" id="architecture">
            <h2>Code Architecture</h2>
            <p>The project follows a <strong>modular, layered architecture</strong> designed for maintainability and performance. Each module has a single responsibility and communicates through well-defined interfaces.</p>

            <div class="file-tree">
                <div class="file-tree-line"><span class="file-tree-dir">src/arbitrage/</span></div>
                <div class="file-tree-line">├── <span class="file-tree-dir">config/</span> <span class="file-tree-desc"># Settings & constants</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">settings.py</span> <span class="file-tree-desc"># Pydantic settings with env vars</span></div>
                <div class="file-tree-line">│   └── <span class="file-tree-file">constants.py</span> <span class="file-tree-desc"># Fee rates, limits, thresholds</span></div>
                <div class="file-tree-line">├── <span class="file-tree-dir">core/</span> <span class="file-tree-desc"># Core engine & types</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">engine.py</span> <span class="file-tree-desc"># Main orchestrator</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">event_bus.py</span> <span class="file-tree-desc"># Internal pub/sub system</span></div>
                <div class="file-tree-line">│   └── <span class="file-tree-file">types.py</span> <span class="file-tree-desc"># TypedDicts, dataclasses</span></div>
                <div class="file-tree-line">├── <span class="file-tree-dir">market/</span> <span class="file-tree-desc"># Market data handling</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">websocket.py</span> <span class="file-tree-desc"># WebSocket connection manager</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">orderbook.py</span> <span class="file-tree-desc"># O(1) BBO cache</span></div>
                <div class="file-tree-line">│   └── <span class="file-tree-file">symbols.py</span> <span class="file-tree-desc"># Symbol filtering & metadata</span></div>
                <div class="file-tree-line">├── <span class="file-tree-dir">strategy/</span> <span class="file-tree-desc"># Arbitrage logic</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">graph.py</span> <span class="file-tree-desc"># Triangle path discovery</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">calculator.py</span> <span class="file-tree-desc"># Profit calculation engine</span></div>
                <div class="file-tree-line">│   └── <span class="file-tree-file">opportunity.py</span> <span class="file-tree-desc"># Opportunity data structures</span></div>
                <div class="file-tree-line">├── <span class="file-tree-dir">execution/</span> <span class="file-tree-desc"># Order execution</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">executor.py</span> <span class="file-tree-desc"># Async order dispatcher</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">signer.py</span> <span class="file-tree-desc"># HMAC-SHA256 request signing</span></div>
                <div class="file-tree-line">│   └── <span class="file-tree-file">risk.py</span> <span class="file-tree-desc"># Position limits & guards</span></div>
                <div class="file-tree-line">├── <span class="file-tree-dir">dashboard/</span> <span class="file-tree-desc"># Web interface</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">server.py</span> <span class="file-tree-desc"># FastAPI server & WebSocket</span></div>
                <div class="file-tree-line">│   ├── <span class="file-tree-file">live_feed.py</span> <span class="file-tree-desc"># Binance live data feed</span></div>
                <div class="file-tree-line">│   └── <span class="file-tree-file">multi_exchange_feed.py</span> <span class="file-tree-desc"># Multi-exchange feed</span></div>
                <div class="file-tree-line">└── <span class="file-tree-dir">telemetry/</span> <span class="file-tree-desc"># Monitoring & logging</span></div>
                <div class="file-tree-line">    ├── <span class="file-tree-file">metrics.py</span> <span class="file-tree-desc"># Latency tracking</span></div>
                <div class="file-tree-line">    └── <span class="file-tree-file">reporter.py</span> <span class="file-tree-desc"># CLI stats reporter</span></div>
            </div>
        </section>

        <section class="section" id="websockets">
            <h2>WebSocket Connections</h2>
            <p>The engine maintains <strong>persistent WebSocket connections</strong> to exchange APIs for real-time price updates. Each exchange has its own message format, so we normalize the data into a common structure.</p>

            <h3>Exchange WebSocket URLs</h3>
            <pre><code><span class="code-comment"># Binance - Combined stream for multiple symbols</span>
wss://stream.binance.com:9443/stream?streams=btcusdt@bookTicker/ethusdt@bookTicker

<span class="code-comment"># Kraken - Ticker subscription</span>
wss://ws.kraken.com

<span class="code-comment"># Coinbase - Product ticker channel</span>
wss://ws-feed.exchange.coinbase.com

<span class="code-comment"># OKX - Public ticker channel</span>
wss://ws.okx.com:8443/ws/v5/public

<span class="code-comment"># Bybit - Spot tickers</span>
wss://stream.bybit.com/v5/public/spot</code></pre>

            <h3>Message Handling</h3>
            <p>Each exchange sends data in a different format. Here's how we handle Binance's bookTicker messages:</p>

            <pre><code><span class="code-comment"># Binance bookTicker message format</span>
{
    <span class="code-string">"s"</span>: <span class="code-string">"BTCUSDT"</span>,     <span class="code-comment"># Symbol</span>
    <span class="code-string">"b"</span>: <span class="code-string">"97485.20"</span>,   <span class="code-comment"># Best bid price</span>
    <span class="code-string">"B"</span>: <span class="code-string">"2.5"</span>,        <span class="code-comment"># Best bid quantity</span>
    <span class="code-string">"a"</span>: <span class="code-string">"97485.50"</span>,   <span class="code-comment"># Best ask price</span>
    <span class="code-string">"A"</span>: <span class="code-string">"1.2"</span>         <span class="code-comment"># Best ask quantity</span>
}

<span class="code-comment"># We normalize to our BBO (Best Bid/Offer) structure</span>
@dataclass
<span class="code-keyword">class</span> <span class="code-func">BBO</span>:
    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    timestamp_us: int</code></pre>

            <h3>Reconnection Logic</h3>
            <p>WebSocket connections can drop due to network issues or exchange maintenance. The engine implements <strong>automatic reconnection</strong> with exponential backoff:</p>

            <pre><code><span class="code-keyword">async def</span> <span class="code-func">_run_binance</span>(self):
    <span class="code-keyword">while</span> self._state.running:
        <span class="code-keyword">try</span>:
            <span class="code-keyword">async with</span> session.ws_connect(url, heartbeat=<span class="code-number">30</span>) <span class="code-keyword">as</span> ws:
                <span class="code-keyword">async for</span> msg <span class="code-keyword">in</span> ws:
                    <span class="code-keyword">await</span> self._handle_message(msg)
        <span class="code-keyword">except</span> Exception:
            <span class="code-keyword">if</span> self._state.running:
                <span class="code-keyword">await</span> asyncio.sleep(<span class="code-number">3</span>)  <span class="code-comment"># Reconnect delay</span></code></pre>
        </section>

        <section class="section" id="detection">
            <h2>Opportunity Detection</h2>
            <p>The core of the engine is the <strong>opportunity detection loop</strong>. Every time a price updates, we check if any arbitrage opportunities have emerged.</p>

            <h3>Triangular Detection Flow</h3>
            <ol>
                <li>Receive price update for symbol (e.g., BTCUSDT)</li>
                <li>Find all triangle paths that include this symbol</li>
                <li>For each path, check if we have prices for all 3 legs</li>
                <li>Calculate potential profit using the formula</li>
                <li>If profit > threshold, emit opportunity event</li>
            </ol>

            <pre><code><span class="code-keyword">async def</span> <span class="code-func">_check_opportunities</span>(self, updated_symbol: str):
    <span class="code-keyword">for</span> triangle <span class="code-keyword">in</span> self._triangles:
        <span class="code-keyword">if</span> updated_symbol <span class="code-keyword">not in</span> triangle.symbols:
            <span class="code-keyword">continue</span>

        <span class="code-comment"># Get all prices for this triangle</span>
        prices = {}
        <span class="code-keyword">for</span> leg <span class="code-keyword">in</span> triangle.legs:
            bbo = self._orderbook.get(leg.symbol)
            <span class="code-keyword">if not</span> bbo:
                <span class="code-keyword">break</span>
            prices[leg.symbol] = bbo.ask_price <span class="code-keyword">if</span> leg.side == BUY <span class="code-keyword">else</span> bbo.bid_price

        <span class="code-comment"># Calculate and emit if profitable</span>
        result = self._calculator.calculate(triangle, self._orderbook)
        profit_pct = (result.net_return - <span class="code-number">1</span>) * <span class="code-number">100</span>

        <span class="code-keyword">if</span> profit_pct > self._min_profit_threshold:
            <span class="code-keyword">await</span> self._emit(<span class="code-string">"opportunity"</span>, {...})</code></pre>

            <h3>Cross-Exchange Detection</h3>
            <p>For cross-exchange arbitrage, we compare the <strong>best bid across all exchanges</strong> with the <strong>best ask across all exchanges</strong>:</p>

            <pre><code><span class="code-keyword">async def</span> <span class="code-func">_check_opportunities</span>(self):
    <span class="code-keyword">for</span> symbol, exchanges <span class="code-keyword">in</span> self._state.prices.items():
        <span class="code-comment"># Find best bid (highest) and best ask (lowest)</span>
        best_bid, best_bid_ex = <span class="code-keyword">max</span>(
            ((p[<span class="code-string">"bid"</span>], ex) <span class="code-keyword">for</span> ex, p <span class="code-keyword">in</span> exchanges.items()),
            key=<span class="code-keyword">lambda</span> x: x[<span class="code-number">0</span>]
        )
        best_ask, best_ask_ex = <span class="code-keyword">min</span>(
            ((p[<span class="code-string">"ask"</span>], ex) <span class="code-keyword">for</span> ex, p <span class="code-keyword">in</span> exchanges.items()),
            key=<span class="code-keyword">lambda</span> x: x[<span class="code-number">0</span>]
        )

        <span class="code-comment"># Calculate profit: buy at best_ask, sell at best_bid</span>
        profit_pct = ((best_bid - best_ask) / best_ask) * <span class="code-number">100</span></code></pre>
        </section>

        <section class="section" id="realtime">
            <h2>Real-Time Dashboard</h2>
            <p>The dashboard uses <strong>WebSockets for bidirectional communication</strong> between the server and browser. This enables instant updates without polling.</p>

            <h3>Server → Client Events</h3>
            <ul>
                <li><code>price</code> — New price update from an exchange</li>
                <li><code>opportunity</code> — Detected arbitrage opportunity</li>
                <li><code>connection</code> — Exchange connection status change</li>
                <li><code>status</code> — Bot running state change</li>
            </ul>

            <h3>Client → Server Commands</h3>
            <ul>
                <li><code>start</code> — Start the detection engine</li>
                <li><code>stop</code> — Stop the detection engine</li>
                <li><code>setMode</code> — Switch between arbitrage modes</li>
            </ul>

            <pre><code><span class="code-comment"># FastAPI WebSocket endpoint</span>
@app.websocket(<span class="code-string">"/ws"</span>)
<span class="code-keyword">async def</span> <span class="code-func">websocket_endpoint</span>(websocket: WebSocket):
    <span class="code-keyword">await</span> websocket.accept()
    connected_clients.append(websocket)

    <span class="code-keyword">try</span>:
        <span class="code-keyword">while True</span>:
            data = <span class="code-keyword">await</span> websocket.receive_text()
            msg = orjson.loads(data)

            <span class="code-keyword">if</span> msg[<span class="code-string">"action"</span>] == <span class="code-string">"start"</span>:
                <span class="code-keyword">await</span> start_bot()
            <span class="code-keyword">elif</span> msg[<span class="code-string">"action"</span>] == <span class="code-string">"stop"</span>:
                <span class="code-keyword">await</span> stop_bot()
    <span class="code-keyword">finally</span>:
        connected_clients.remove(websocket)</code></pre>
        </section>

        <section class="section" id="stack">
            <h2>Tech Stack</h2>
            <div class="tech-stack">
                <div class="tech-item">
                    <div class="tech-name">Python 3.11+</div>
                    <div class="tech-desc">Modern async/await, type hints, performance improvements</div>
                </div>
                <div class="tech-item">
                    <div class="tech-name">FastAPI</div>
                    <div class="tech-desc">High-performance async web framework with WebSocket support</div>
                </div>
                <div class="tech-item">
                    <div class="tech-name">aiohttp</div>
                    <div class="tech-desc">Async HTTP client for WebSocket connections to exchanges</div>
                </div>
                <div class="tech-item">
                    <div class="tech-name">orjson</div>
                    <div class="tech-desc">Fast JSON parsing — 10x faster than standard library</div>
                </div>
                <div class="tech-item">
                    <div class="tech-name">uvloop</div>
                    <div class="tech-desc">High-performance event loop — 2-4x faster than asyncio</div>
                </div>
                <div class="tech-item">
                    <div class="tech-name">Pydantic</div>
                    <div class="tech-desc">Data validation and settings management with type safety</div>
                </div>
                <div class="tech-item">
                    <div class="tech-name">NetworkX</div>
                    <div class="tech-desc">Graph library for discovering triangle arbitrage paths</div>
                </div>
                <div class="tech-item">
                    <div class="tech-name">Poetry</div>
                    <div class="tech-desc">Modern dependency management and packaging</div>
                </div>
            </div>

            <h3>Performance Optimizations</h3>
            <ul>
                <li><strong>O(1) orderbook lookups</strong> — Prices stored in a flat dictionary for instant access</li>
                <li><strong>Pre-computed triangle paths</strong> — Paths discovered at startup, not during detection</li>
                <li><strong>Slots dataclasses</strong> — 30% memory reduction with <code>@dataclass(slots=True)</code></li>
                <li><strong>Connection reuse</strong> — Single aiohttp session per exchange</li>
                <li><strong>Float arithmetic</strong> — Using floats over Decimal for 10x calculation speed (precision validated)</li>
            </ul>
        </section>

        <div class="card" style="margin-top: 60px;">
            <div class="card-title">Want to see it in action?</div>
            <p style="color: var(--text2); margin: 0;">
                <a href="/" style="color: var(--accent);">Go to the dashboard</a> and start the engine to see real-time arbitrage detection. Try both simulated and live modes to understand how the system works.
            </p>
        </div>
    </div>
</body>
</html>"""


app = create_app()


def main() -> None:
    import uvicorn

    print(
        """
╔═══════════════════════════════════════════════════════════════╗
║              ARBITRAGE ENGINE - DASHBOARD                     ║
╚═══════════════════════════════════════════════════════════════╝

Dashboard: http://localhost:8000
Press Ctrl+C to stop.
    """
    )
    uvicorn.run(
        "arbitrage.dashboard.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
