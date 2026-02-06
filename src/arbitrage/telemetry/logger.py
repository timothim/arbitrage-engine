"""
Async queue-based logging system.

Provides non-blocking logging to prevent I/O operations
from affecting trading latency.
"""

import logging
import sys
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from queue import Queue

from arbitrage.config.constants import LOG_DATE_FORMAT, LOG_FORMAT, MAX_LOG_QUEUE_SIZE


class MicrosecondFormatter(logging.Formatter):
    """Formatter with microsecond precision timestamps."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Format time with microseconds."""
        from datetime import datetime

        ct = datetime.fromtimestamp(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime(LOG_DATE_FORMAT)

        return f"{s}.{int(record.msecs * 1000):06d}"


class AsyncLogger:
    """
    Async-friendly logger with queue-based output.

    All logging calls are non-blocking - messages are queued
    and written by a background thread.
    """

    def __init__(
        self,
        name: str,
        level: int = logging.INFO,
        log_file: Path | None = None,
    ) -> None:
        """
        Initialize async logger.

        Args:
            name: Logger name.
            level: Logging level.
            log_file: Optional file path for logging.
        """
        self._name = name
        self._level = level
        self._log_file = log_file
        self._queue: Queue[logging.LogRecord] = Queue(maxsize=MAX_LOG_QUEUE_SIZE)
        self._listener: QueueListener | None = None
        self._logger = logging.getLogger(name)

    def start(self) -> None:
        """Start the async logging system."""
        # Create formatter
        formatter = MicrosecondFormatter(LOG_FORMAT, LOG_DATE_FORMAT)

        # Create handlers
        handlers: list[logging.Handler] = []

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(self._level)
        handlers.append(console_handler)

        # File handler (if configured)
        if self._log_file:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(self._log_file)
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)  # Log everything to file
            handlers.append(file_handler)

        # Set up queue handler for non-blocking logging
        queue_handler = QueueHandler(self._queue)
        self._logger.addHandler(queue_handler)
        self._logger.setLevel(self._level)

        # Start queue listener
        self._listener = QueueListener(
            self._queue,
            *handlers,
            respect_handler_level=True,
        )
        self._listener.start()

    def stop(self) -> None:
        """Stop the async logging system."""
        if self._listener:
            self._listener.stop()
            self._listener = None

    @property
    def logger(self) -> logging.Logger:
        """Get the underlying logger."""
        return self._logger

    def debug(self, msg: str, *args: object) -> None:
        """Log debug message."""
        self._logger.debug(msg, *args)

    def info(self, msg: str, *args: object) -> None:
        """Log info message."""
        self._logger.info(msg, *args)

    def warning(self, msg: str, *args: object) -> None:
        """Log warning message."""
        self._logger.warning(msg, *args)

    def error(self, msg: str, *args: object) -> None:
        """Log error message."""
        self._logger.error(msg, *args)

    def critical(self, msg: str, *args: object) -> None:
        """Log critical message."""
        self._logger.critical(msg, *args)

    def __enter__(self) -> "AsyncLogger":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.stop()


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
) -> AsyncLogger:
    """
    Set up application-wide logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        log_file: Optional log file path.

    Returns:
        Configured AsyncLogger instance.
    """
    # Convert string level to int
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create and start async logger
    async_logger = AsyncLogger(
        name="arbitrage",
        level=numeric_level,
        log_file=log_file,
    )
    async_logger.start()

    # Suppress noisy third-party loggers
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return async_logger


class LatencyLogger:
    """
    Specialized logger for latency measurements.

    Buffers latency measurements and logs aggregated stats
    periodically to reduce log volume.
    """

    def __init__(
        self,
        name: str,
        buffer_size: int = 100,
        log_interval_seconds: float = 5.0,
    ) -> None:
        """
        Initialize latency logger.

        Args:
            name: Logger name.
            buffer_size: Number of measurements to buffer.
            log_interval_seconds: Interval between log outputs.
        """
        self._name = name
        self._buffer_size = buffer_size
        self._log_interval = log_interval_seconds
        self._logger = logging.getLogger(name)

        self._measurements: dict[str, list[int]] = {}
        self._last_log_time = 0.0

    def record(self, category: str, latency_us: int) -> None:
        """
        Record a latency measurement.

        Args:
            category: Measurement category.
            latency_us: Latency in microseconds.
        """
        if category not in self._measurements:
            self._measurements[category] = []

        self._measurements[category].append(latency_us)

        # Trim buffer
        if len(self._measurements[category]) > self._buffer_size:
            self._measurements[category] = self._measurements[category][-self._buffer_size :]

    def get_stats(self, category: str) -> dict[str, float]:
        """
        Get statistics for a category.

        Returns:
            Dict with min, max, avg, p50, p99.
        """
        measurements = self._measurements.get(category, [])
        if not measurements:
            return {"min": 0, "max": 0, "avg": 0, "p50": 0, "p99": 0}

        sorted_m = sorted(measurements)
        n = len(sorted_m)

        return {
            "min": sorted_m[0],
            "max": sorted_m[-1],
            "avg": sum(sorted_m) / n,
            "p50": sorted_m[n // 2],
            "p99": sorted_m[int(n * 0.99)] if n > 1 else sorted_m[-1],
        }

    def log_stats(self) -> None:
        """Log aggregated statistics for all categories."""
        for category, measurements in self._measurements.items():
            if not measurements:
                continue

            stats = self.get_stats(category)
            self._logger.info(
                f"Latency [{category}]: "
                f"min={stats['min']}μs, "
                f"avg={stats['avg']:.0f}μs, "
                f"p99={stats['p99']}μs, "
                f"max={stats['max']}μs"
            )

    def clear(self) -> None:
        """Clear all measurements."""
        self._measurements.clear()
