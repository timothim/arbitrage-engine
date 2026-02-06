"""
Application settings with environment variable support.

Uses Pydantic Settings for type-safe configuration with automatic
environment variable loading and validation.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from arbitrage.config.constants import (
    DEFAULT_DAILY_LOSS_LIMIT,
    DEFAULT_FEE_RATE,
    DEFAULT_MAX_HOLD_TIME_MS,
    DEFAULT_MAX_POSITION_PCT,
    DEFAULT_MIN_PROFIT_THRESHOLD,
    DEFAULT_SLIPPAGE_BUFFER,
)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables.
    Sensitive values use SecretStr for safe handling.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # Exchange Credentials
    # =========================================================================

    binance_api_key: SecretStr = Field(
        ...,
        description="Binance API key for authentication",
    )
    binance_api_secret: SecretStr = Field(
        ...,
        description="Binance API secret for signing requests",
    )

    # =========================================================================
    # Network Configuration
    # =========================================================================

    use_testnet: bool = Field(
        default=False,
        description="Use Binance testnet instead of production",
    )

    # =========================================================================
    # Trading Configuration
    # =========================================================================

    base_currency: Literal["USDT", "USDC", "BUSD"] = Field(
        default="USDT",
        description="Base currency for arbitrage cycles",
    )

    fee_rate: float = Field(
        default=DEFAULT_FEE_RATE,
        ge=0.0,
        le=0.01,
        description="Trading fee rate per leg (e.g., 0.001 = 0.1%)",
    )

    min_profit_threshold: float = Field(
        default=DEFAULT_MIN_PROFIT_THRESHOLD,
        ge=0.0,
        le=0.1,
        description="Minimum profit percentage to execute (e.g., 0.0005 = 0.05%)",
    )

    max_position_pct: float = Field(
        default=DEFAULT_MAX_POSITION_PCT,
        ge=0.01,
        le=1.0,
        description="Maximum position size as percentage of balance",
    )

    slippage_buffer: float = Field(
        default=DEFAULT_SLIPPAGE_BUFFER,
        ge=0.0,
        le=0.01,
        description="Price buffer for slippage protection",
    )

    # =========================================================================
    # Risk Management
    # =========================================================================

    daily_loss_limit: float = Field(
        default=DEFAULT_DAILY_LOSS_LIMIT,
        ge=0.0,
        description="Maximum daily loss in base currency before halting",
    )

    max_hold_time_ms: int = Field(
        default=DEFAULT_MAX_HOLD_TIME_MS,
        ge=1000,
        le=60000,
        description="Maximum time to hold a position in milliseconds",
    )

    max_concurrent_triangles: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Maximum number of triangles to execute concurrently",
    )

    # =========================================================================
    # Operation Mode
    # =========================================================================

    dry_run: bool = Field(
        default=True,
        description="Simulate trades without sending real orders",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging verbosity level",
    )

    # =========================================================================
    # Performance Tuning
    # =========================================================================

    use_uvloop: bool = Field(
        default=True,
        description="Use uvloop for improved async performance",
    )

    max_triangles: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Maximum number of triangles to monitor",
    )

    order_timeout_ms: int = Field(
        default=5000,
        ge=1000,
        le=30000,
        description="Timeout for order placement in milliseconds",
    )

    # =========================================================================
    # Validators
    # =========================================================================

    @field_validator("binance_api_key", "binance_api_secret", mode="after")
    @classmethod
    def validate_credentials(cls, v: SecretStr) -> SecretStr:
        """Ensure credentials are not empty."""
        if not v.get_secret_value():
            raise ValueError("Credential cannot be empty")
        return v

    @field_validator("min_profit_threshold", mode="after")
    @classmethod
    def validate_profit_threshold(cls, v: float) -> float:
        """Warn if profit threshold is very low."""
        if v < 0.0001:
            import warnings

            warnings.warn(
                f"Profit threshold {v} is very low, may result in losses after fees",
                stacklevel=2,
            )
        return v

    # =========================================================================
    # Computed Properties
    # =========================================================================

    @property
    def total_fee_rate(self) -> float:
        """Calculate total fee rate for a complete triangle (3 legs)."""
        return 1.0 - (1.0 - self.fee_rate) ** 3

    @property
    def effective_min_profit(self) -> float:
        """Calculate effective minimum profit after fees."""
        return self.min_profit_threshold + self.total_fee_rate


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses LRU cache to ensure settings are loaded only once.
    Clear cache with `get_settings.cache_clear()` if needed.
    """
    return Settings()  # type: ignore[call-arg, unused-ignore]
