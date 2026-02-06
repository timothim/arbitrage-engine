# Crypto Arbitrage Engine

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

A real-time cryptocurrency arbitrage detection engine with a live web dashboard. Connects to 5 exchanges via WebSocket, detects triangular and cross-exchange price inefficiencies, and displays everything in a dark-themed monitoring interface.

**No API keys required** — the dashboard runs on public market data.

---

## Quick Start

```bash
git clone https://github.com/timothim/arbitrage-engine.git
cd arbitrage-engine
pip install poetry && poetry install
make demo
```

Open **http://localhost:8000** — click **Start** to begin.

---

## What It Does

The engine detects two types of arbitrage opportunities in real-time:

### Triangular Arbitrage

Finds price discrepancies across three trading pairs on a single exchange. For example, if converting USDT -> BTC -> ETH -> USDT yields more than 1 USDT after fees, that's a triangular opportunity.

```
USDT ──buy──> BTC ──buy──> ETH ──sell──> USDT
  $1000         0.01025 BTC    0.2896 ETH    $1001.12  (+0.112%)
```

### Cross-Exchange Arbitrage

Compares prices of the same asset across 5 exchanges simultaneously. If BTC is cheaper on Binance than on Kraken, that's a cross-exchange opportunity.

| Exchange | BTC/USDT Bid | BTC/USDT Ask |
|----------|-------------|-------------|
| Binance  | $97,480     | $97,485     |
| Kraken   | $97,520     | $97,530     |
| **Spread** | | **+$35 (0.036%)** |

---

## Dashboard

The web dashboard at `localhost:8000` has 4 modes:

| Mode | Data Source | Description |
|------|-----------|-------------|
| **Triangular (Sim)** | Simulated | Fake price feed showing frequent triangular opportunities |
| **Cross-Exchange (Sim)** | Simulated | Fake multi-exchange data to demonstrate the concept |
| **Cross-Exchange (Live)** | Real-time | Live WebSocket feeds from Binance, Kraken, Coinbase, OKX, Bybit |
| **Triangular (Live)** | Real-time | Live Binance bookTicker stream for triangle detection |

The **"How It Works"** page (`/how-it-works`) provides a full technical breakdown of the architecture, algorithms, and code.

---

## Architecture

```
src/arbitrage/
├── config/             # Pydantic settings, trading constants
├── core/               # Engine orchestrator, event bus, type definitions
├── market/             # WebSocket manager, O(1) orderbook cache, symbol filtering
├── strategy/           # Triangle graph discovery, profit calculator
├── execution/          # Order dispatcher, HMAC signer, risk manager, recovery
├── exchange/           # Binance REST client, rate limiter
├── dashboard/          # FastAPI server, live feeds, multi-exchange WebSocket
├── telemetry/          # Async logger, latency metrics, CLI reporter
└── utils/              # Microsecond timestamps, decimal precision helpers
```

### Data Flow

```
Exchange WebSocket ──> Price Normalization ──> Orderbook Cache (O(1) lookup)
                                                       │
                                          ┌────────────┴────────────┐
                                          │                         │
                                  Triangle Scanner          Cross-Exchange Scanner
                                          │                         │
                                          └────────────┬────────────┘
                                                       │
                                               Opportunity Event
                                                       │
                                            WebSocket ──> Browser
```

### Key Design Decisions

- **Event-driven**: Calculations trigger only when relevant prices update, not on a polling loop
- **O(1) lookups**: Orderbook stored as a flat `dict[str, BBO]` for instant price access
- **Pre-computed paths**: Triangle paths discovered at startup using NetworkX graph analysis
- **Concurrent connections**: Each exchange runs in its own asyncio task with independent reconnection
- **Non-blocking I/O**: All network operations are async — the event loop never blocks

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Runtime | Python 3.11+ | Native async/await, type hints, performance |
| Event Loop | uvloop | 2-4x faster than standard asyncio |
| Web Framework | FastAPI | Async WebSocket support, zero overhead |
| HTTP Client | aiohttp | Async WebSocket connections to exchanges |
| JSON | orjson | 10x faster parsing (Rust-based) |
| Validation | Pydantic | Type-safe settings with env var loading |
| Graph Analysis | NetworkX | Triangle path discovery in directed graphs |

---

## Project Structure

```
arbitrage-engine/
├── src/arbitrage/          # Main application
│   ├── config/             # Settings and constants
│   ├── core/               # Engine, event bus, types
│   ├── market/             # WebSocket, orderbook, symbols
│   ├── strategy/           # Graph, calculator, opportunity model
│   ├── execution/          # Executor, risk, recovery, signer
│   ├── exchange/           # Binance REST client, models
│   ├── dashboard/          # Web dashboard (FastAPI + WebSocket)
│   ├── telemetry/          # Logger, metrics, reporter
│   └── utils/              # Time, math utilities
├── tests/
│   ├── unit/               # Unit tests (calculator, graph, orderbook, etc.)
│   ├── integration/        # Integration tests (WebSocket, engine)
│   └── mocks/              # Mock exchange & WebSocket implementations
├── scripts/                # Utility scripts (discovery, benchmarking)
├── docker/                 # Dockerfile & docker-compose
└── .github/workflows/      # CI/CD pipelines
```

---

## Configuration

Copy `.env.example` to `.env` for full trading mode:

```env
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
DRY_RUN=true
USE_TESTNET=true
```

| Setting | Default | Description |
|---------|---------|-------------|
| `DRY_RUN` | `true` | Simulate trades without placing orders |
| `USE_TESTNET` | `false` | Use Binance testnet API |
| `FEE_RATE` | `0.001` | Trading fee per leg (0.1%) |
| `MIN_PROFIT_THRESHOLD` | `0.0005` | Minimum profit to trigger (0.05%) |
| `MAX_POSITION_PCT` | `0.20` | Max 20% of balance per trade |
| `DAILY_LOSS_LIMIT` | `50.0` | Maximum daily loss in USDT |

The dashboard (`make demo`) requires **no configuration** — it uses public WebSocket APIs.

---

## Development

```bash
make dev          # Install all dependencies (including dev)
make lint         # Run ruff linter
make typecheck    # Run mypy type checker
make test         # Run test suite
make coverage     # Run tests with coverage report
make demo         # Launch the web dashboard
```

### Docker

```bash
make docker-build         # Build image
make docker-run           # Run container
make docker-compose-up    # Run with docker-compose
```

---

## How It Works (Detailed)

Run the dashboard and visit **localhost:8000/how-it-works** for an in-depth technical walkthrough covering:

- Triangular arbitrage math and formulas
- Cross-exchange detection algorithms
- WebSocket message formats per exchange
- Real-time dashboard communication protocol
- Performance optimization techniques

---

## Disclaimer

This software is for **educational and research purposes only**. Cryptocurrency trading carries substantial risk. Always test with `DRY_RUN=true` first. Past performance does not guarantee future results.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
