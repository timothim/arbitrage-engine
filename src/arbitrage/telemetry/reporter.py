"""
CLI reporter for real-time status display.

Provides a terminal-based dashboard showing trading
performance and system health.
"""

import asyncio
import sys
from datetime import timedelta
from typing import TextIO

from arbitrage.telemetry.metrics import MetricsCollector


class CLIReporter:
    """
    Real-time CLI dashboard for monitoring.

    Displays a formatted status panel with:
    - System health
    - Latency metrics
    - Opportunity counts
    - P&L tracking
    """

    # Box drawing characters
    BOX_TL = "\u2554"  # ╔
    BOX_TR = "\u2557"  # ╗
    BOX_BL = "\u255a"  # ╚
    BOX_BR = "\u255d"  # ╝
    BOX_H = "\u2550"  # ═
    BOX_V = "\u2551"  # ║
    BOX_LT = "\u2560"  # ╠
    BOX_RT = "\u2563"  # ╣
    BOX_CT = "\u256c"  # ╬
    BOX_HT = "\u2566"  # ╦
    BOX_HB = "\u2569"  # ╩
    THIN_V = "\u2502"  # │

    def __init__(
        self,
        metrics: MetricsCollector,
        width: int = 64,
        output: TextIO | None = None,
        dry_run: bool = True,
    ) -> None:
        """
        Initialize CLI reporter.

        Args:
            metrics: Metrics collector instance.
            width: Dashboard width in characters.
            output: Output stream (default: stdout).
            dry_run: Whether running in dry-run mode.
        """
        self._metrics = metrics
        self._width = width
        self._output = output or sys.stdout
        self._dry_run = dry_run
        self._running = False
        self._task: asyncio.Task[None] | None = None

        # Additional state
        self._triangle_count = 0
        self._stream_count = 0
        self._balance = 0.0

    def set_state(
        self,
        triangle_count: int = 0,
        stream_count: int = 0,
        balance: float = 0.0,
    ) -> None:
        """Update display state."""
        self._triangle_count = triangle_count
        self._stream_count = stream_count
        self._balance = balance

    def _format_uptime(self, seconds: float) -> str:
        """Format uptime as HH:MM:SS."""
        td = timedelta(seconds=int(seconds))
        hours, remainder = divmod(int(td.total_seconds()), 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _format_number(self, n: int | float, width: int = 8) -> str:
        """Format number with thousand separators."""
        if isinstance(n, float):
            return f"{n:>{width},.2f}"
        return f"{n:>{width},}"

    def _center(self, text: str, width: int) -> str:
        """Center text within width."""
        return text.center(width)

    def _pad(self, text: str, width: int) -> str:
        """Pad text to width."""
        return text.ljust(width)[:width]

    def _line(self, left: str, content: str, right: str) -> str:
        """Create a line with borders."""
        inner_width = self._width - 2
        return f"{left}{self._pad(content, inner_width)}{right}"

    def _divider(self, left: str = BOX_LT, right: str = BOX_RT) -> str:
        """Create a horizontal divider."""
        return f"{left}{self.BOX_H * (self._width - 2)}{right}"

    def render(self) -> str:
        """
        Render the dashboard.

        Returns:
            Formatted dashboard string.
        """
        stats = self._metrics.trading_stats
        tick_latency = self._metrics.get_latency_stats("tick_to_calc")
        order_latency = self._metrics.get_latency_stats("calc_to_order")

        dry_run_text = "DRY_RUN: ON " if self._dry_run else "DRY_RUN: OFF"
        uptime = self._format_uptime(self._metrics.uptime_seconds)

        lines = []

        # Header
        lines.append(f"{self.BOX_TL}{self.BOX_H * (self._width - 2)}{self.BOX_TR}")
        header = f"  ARBITRAGE ENGINE v1.0.0 | BINANCE | {dry_run_text}"
        lines.append(self._line(self.BOX_V, header, self.BOX_V))
        lines.append(self._divider())

        # Status row
        status = f"  Uptime: {uptime}  |  Triangles: {self._triangle_count}  |  Streams: {self._stream_count}"
        lines.append(self._line(self.BOX_V, status, self.BOX_V))
        lines.append(self._divider())

        # Column headers
        col1 = "  LATENCY (μs)"
        col2 = "OPPORTUNITIES"
        col3 = "EXECUTION"
        header_line = f"  {col1:<17}{self.THIN_V}  {col2:<16}{self.THIN_V}  {col3:<16}"
        lines.append(self._line(self.BOX_V, header_line, self.BOX_V))

        # Data row 1
        tick_avg = f"{tick_latency.avg_us:.0f}" if tick_latency.count > 0 else "---"
        opp_found = self._format_number(stats.opportunities_found, 6).strip()
        exec_sent = self._format_number(stats.opportunities_executed, 6).strip()
        row1 = f"  Tick→Calc: {tick_avg:<6}{self.THIN_V}  Found: {opp_found:<9}{self.THIN_V}  Sent: {exec_sent:<10}"
        lines.append(self._line(self.BOX_V, row1, self.BOX_V))

        # Data row 2
        order_avg = f"{order_latency.avg_us:.0f}" if order_latency.count > 0 else "---"
        opp_profit = self._format_number(stats.opportunities_profitable, 6).strip()
        exec_success = self._format_number(stats.executions_successful, 6).strip()
        row2 = f"  Calc→Order: {order_avg:<5}{self.THIN_V}  Valid: {opp_profit:<9}{self.THIN_V}  Filled: {exec_success:<8}"
        lines.append(self._line(self.BOX_V, row2, self.BOX_V))

        # Data row 3
        total_avg = tick_latency.avg_us + order_latency.avg_us
        total_str = f"{total_avg:.0f}" if tick_latency.count > 0 else "---"
        opp_exec = self._format_number(stats.opportunities_executed, 6).strip()
        exec_failed = self._format_number(stats.executions_failed, 6).strip()
        row3 = f"  Total: {total_str:<10}{self.THIN_V}  Profitable: {opp_exec:<5}{self.THIN_V}  Failed: {exec_failed:<8}"
        lines.append(self._line(self.BOX_V, row3, self.BOX_V))

        lines.append(self._divider())

        # P&L row
        profit_sign = "+" if stats.net_profit >= 0 else ""
        pnl_str = f"P&L: {profit_sign}{stats.net_profit:.4f} USDT"
        balance_str = f"Balance: {self._balance:.2f} USDT"
        pnl_line = f"  {pnl_str}  |  {balance_str}"
        lines.append(self._line(self.BOX_V, pnl_line, self.BOX_V))

        # Footer
        lines.append(f"{self.BOX_BL}{self.BOX_H * (self._width - 2)}{self.BOX_BR}")

        return "\n".join(lines)

    def display(self) -> None:
        """Display the dashboard once."""
        # Clear screen and move cursor to top
        self._output.write("\033[2J\033[H")
        self._output.write(self.render())
        self._output.write("\n")
        self._output.flush()

    async def run(self, interval: float = 1.0) -> None:
        """
        Run continuous display updates.

        Args:
            interval: Update interval in seconds.
        """
        self._running = True

        while self._running:
            self.display()
            await asyncio.sleep(interval)

    def start(self, interval: float = 1.0) -> asyncio.Task[None]:
        """Start the reporter as a background task."""
        self._task = asyncio.create_task(self.run(interval))
        return self._task

    def stop(self) -> None:
        """Stop the reporter."""
        self._running = False
        if self._task:
            self._task.cancel()

    def print_summary(self) -> None:
        """Print a final summary."""
        stats = self._metrics.trading_stats
        uptime = self._format_uptime(self._metrics.uptime_seconds)

        print("\n" + "=" * 50)
        print("  SESSION SUMMARY")
        print("=" * 50)
        print(f"  Uptime: {uptime}")
        print(f"  Triangles monitored: {self._triangle_count}")
        print()
        print("  OPPORTUNITIES:")
        print(f"    Found:      {stats.opportunities_found:,}")
        print(f"    Profitable: {stats.opportunities_profitable:,}")
        print(f"    Executed:   {stats.opportunities_executed:,}")
        print()
        print("  EXECUTION:")
        print(f"    Successful: {stats.executions_successful:,}")
        print(f"    Failed:     {stats.executions_failed:,}")
        print(f"    Success rate: {stats.execution_success_rate:.1%}")
        print()
        print("  P&L:")
        print(f"    Gross profit:  {stats.total_profit:+.6f} USDT")
        print(f"    Commissions:   {stats.total_commission:.6f} USDT")
        print(f"    Net profit:    {stats.net_profit:+.6f} USDT")
        print("=" * 50)


class SimpleReporter:
    """
    Simpler text-based reporter for logging.

    Outputs periodic status updates as log messages.
    """

    def __init__(self, metrics: MetricsCollector) -> None:
        """Initialize simple reporter."""
        self._metrics = metrics

    def get_status_line(self) -> str:
        """Get a single-line status update."""
        stats = self._metrics.trading_stats
        tick = self._metrics.get_latency_stats("tick_to_calc")

        return (
            f"Opp: {stats.opportunities_found}/{stats.opportunities_profitable} | "
            f"Exec: {stats.executions_successful}/{stats.executions_failed} | "
            f"PnL: {stats.net_profit:+.4f} | "
            f"Latency: {tick.avg_us:.0f}μs"
        )
