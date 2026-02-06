"""
Trading constants and configuration values.

This module contains all hardcoded values used throughout the arbitrage engine.
Values are organized by category for easy maintenance and auditing.
"""

from typing import Final


# =============================================================================
# Binance API Endpoints
# =============================================================================

BINANCE_REST_URL: Final[str] = "https://api.binance.com"
BINANCE_REST_TESTNET_URL: Final[str] = "https://testnet.binance.vision"

BINANCE_WS_URL: Final[str] = "wss://stream.binance.com:9443"
BINANCE_WS_TESTNET_URL: Final[str] = "wss://testnet.binance.vision"

# API Endpoints
ENDPOINT_EXCHANGE_INFO: Final[str] = "/api/v3/exchangeInfo"
ENDPOINT_ACCOUNT: Final[str] = "/api/v3/account"
ENDPOINT_ORDER: Final[str] = "/api/v3/order"
ENDPOINT_TICKER_PRICE: Final[str] = "/api/v3/ticker/price"
ENDPOINT_BOOK_TICKER: Final[str] = "/api/v3/ticker/bookTicker"
ENDPOINT_SERVER_TIME: Final[str] = "/api/v3/time"


# =============================================================================
# Trading Fees
# =============================================================================

# Default Binance spot trading fee (0.1%)
DEFAULT_FEE_RATE: Final[float] = 0.001

# VIP tier fee rates (for reference)
VIP0_FEE_RATE: Final[float] = 0.001
VIP1_FEE_RATE: Final[float] = 0.0009
VIP2_FEE_RATE: Final[float] = 0.0008

# Fee rate with BNB discount (25% off)
BNB_DISCOUNT_FEE_RATE: Final[float] = 0.00075


# =============================================================================
# Reconnection Strategy
# =============================================================================

MIN_RECONNECT_DELAY: Final[float] = 1.0  # seconds
MAX_RECONNECT_DELAY: Final[float] = 30.0  # seconds
RECONNECT_MULTIPLIER: Final[float] = 2.0


# =============================================================================
# Rate Limiting
# =============================================================================

# Binance rate limits
ORDERS_PER_SECOND: Final[int] = 10
ORDERS_PER_DAY: Final[int] = 200_000
REQUEST_WEIGHT_PER_MINUTE: Final[int] = 1200

# Safety margins (use 80% of limits)
SAFE_ORDERS_PER_SECOND: Final[int] = 8
SAFE_REQUEST_WEIGHT_PER_MINUTE: Final[int] = 960


# =============================================================================
# WebSocket Configuration
# =============================================================================

WS_PING_INTERVAL: Final[float] = 20.0  # seconds
WS_PING_TIMEOUT: Final[float] = 10.0  # seconds
WS_MAX_MESSAGE_SIZE: Final[int] = 10 * 1024 * 1024  # 10MB
WS_CLOSE_TIMEOUT: Final[float] = 5.0  # seconds

# Maximum streams per WebSocket connection (Binance limit: 1024)
MAX_STREAMS_PER_CONNECTION: Final[int] = 200


# =============================================================================
# Order Configuration
# =============================================================================

# Order types
ORDER_TYPE_LIMIT: Final[str] = "LIMIT"
ORDER_TYPE_MARKET: Final[str] = "MARKET"
ORDER_TYPE_LIMIT_MAKER: Final[str] = "LIMIT_MAKER"

# Time in force
TIF_GTC: Final[str] = "GTC"  # Good Till Cancel
TIF_IOC: Final[str] = "IOC"  # Immediate Or Cancel
TIF_FOK: Final[str] = "FOK"  # Fill Or Kill

# Order sides
SIDE_BUY: Final[str] = "BUY"
SIDE_SELL: Final[str] = "SELL"


# =============================================================================
# Precision & Formatting
# =============================================================================

# Maximum decimal places for different value types
PRICE_PRECISION: Final[int] = 8
QUANTITY_PRECISION: Final[int] = 8
PERCENTAGE_PRECISION: Final[int] = 4

# Timestamp precision
TIMESTAMP_PRECISION_MS: Final[int] = 3
TIMESTAMP_PRECISION_US: Final[int] = 6


# =============================================================================
# Trading Constraints
# =============================================================================

# Minimum profit threshold to execute (0.05%)
DEFAULT_MIN_PROFIT_THRESHOLD: Final[float] = 0.0005

# Maximum position size as percentage of balance (20%)
DEFAULT_MAX_POSITION_PCT: Final[float] = 0.20

# Slippage buffer for order prices (0.01%)
DEFAULT_SLIPPAGE_BUFFER: Final[float] = 0.0001

# Maximum time to hold a position (milliseconds)
DEFAULT_MAX_HOLD_TIME_MS: Final[int] = 5000

# Daily loss limit in base currency
DEFAULT_DAILY_LOSS_LIMIT: Final[float] = 50.0


# =============================================================================
# Symbol Filtering
# =============================================================================

# Minimum 24h volume in USDT to consider a symbol
MIN_VOLUME_USDT: Final[float] = 1_000_000.0

# Symbols to always exclude (delisted, problematic, etc.)
EXCLUDED_SYMBOLS: Final[frozenset[str]] = frozenset(
    {
        # Add problematic symbols here
    }
)

# Supported quote assets for triangular arbitrage
SUPPORTED_QUOTE_ASSETS: Final[frozenset[str]] = frozenset(
    {
        "USDT",
        "BTC",
        "ETH",
        "BNB",
    }
)


# =============================================================================
# Logging & Telemetry
# =============================================================================

LOG_FORMAT: Final[str] = "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

# Metrics reporting interval (seconds)
METRICS_REPORT_INTERVAL: Final[float] = 5.0

# Maximum log queue size
MAX_LOG_QUEUE_SIZE: Final[int] = 10_000
