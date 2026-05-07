"""Drawdown analytics — spec §14."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sukoon_bt.data.models import PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class DrawdownStats:
    max_drawdown: float  # most-negative value (e.g. -0.32 for a 32% peak-to-trough drop)
    peak_date: date | None
    trough_date: date | None


def max_drawdown(snapshots: list[PortfolioSnapshot]) -> DrawdownStats:
    """Compute the worst peak-to-trough drawdown across snapshots.

    Snapshots already carry a per-day drawdown field (computed by the
    Portfolio against its running peak), so this is the min over that
    series — but we additionally surface the peak/trough dates for
    reports.
    """
    if not snapshots:
        return DrawdownStats(max_drawdown=0.0, peak_date=None, trough_date=None)

    peak_value = snapshots[0].portfolio_value
    peak_date = snapshots[0].date
    worst = 0.0
    worst_peak: date | None = peak_date
    worst_trough: date | None = peak_date

    running_peak_value = peak_value
    running_peak_date = peak_date

    for s in snapshots:
        if s.portfolio_value > running_peak_value:
            running_peak_value = s.portfolio_value
            running_peak_date = s.date
        dd = (s.portfolio_value / running_peak_value - 1.0) if running_peak_value > 0 else 0.0
        if dd < worst:
            worst = dd
            worst_peak = running_peak_date
            worst_trough = s.date

    return DrawdownStats(max_drawdown=worst, peak_date=worst_peak, trough_date=worst_trough)


__all__ = ["DrawdownStats", "max_drawdown"]
