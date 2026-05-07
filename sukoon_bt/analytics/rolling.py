"""Rolling-window metrics — spec §14.

All rolling functions take a snapshot list and a window size in trading
days, returning a polars DataFrame keyed by date with one column per
metric. Windows of length < window are emitted as nulls so downstream
charts can plot continuous lines.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date

import polars as pl

from sukoon_bt.analytics.metrics import TRADING_DAYS_PER_YEAR
from sukoon_bt.data.models import PortfolioSnapshot


def _values(snapshots: Iterable[PortfolioSnapshot]) -> tuple[list[date], list[float]]:
    dates: list[date] = []
    values: list[float] = []
    for s in snapshots:
        dates.append(s.date)
        values.append(s.portfolio_value)
    return dates, values


def rolling_returns(
    snapshots: list[PortfolioSnapshot],
    window: int,
) -> pl.DataFrame:
    """Return ``portfolio[t] / portfolio[t-window] - 1`` per day."""
    if window < 1:
        raise ValueError("window must be >= 1")
    dates, values = _values(snapshots)
    out: list[float | None] = []
    for i, _ in enumerate(values):
        if i < window:
            out.append(None)
        else:
            prev = values[i - window]
            out.append(values[i] / prev - 1.0 if prev > 0 else None)
    return pl.DataFrame({"date": dates, "rolling_return": out}).with_columns(
        pl.col("date").cast(pl.Date)
    )


def rolling_cagr(
    snapshots: list[PortfolioSnapshot],
    window_days: int,
) -> pl.DataFrame:
    """Annualise rolling_returns to a CAGR using calendar days in the window."""
    df = rolling_returns(snapshots, window_days)
    years = window_days / 365.25 if window_days > 0 else 0.0
    if years <= 0:
        return df.with_columns(pl.lit(None).alias("rolling_cagr"))
    cagr_col = df["rolling_return"].map_elements(
        lambda r: ((1 + r) ** (1 / years) - 1) if r is not None else None,
        return_dtype=pl.Float64,
    )
    return df.with_columns(cagr_col.alias("rolling_cagr"))


def rolling_sharpe(
    snapshots: list[PortfolioSnapshot],
    window: int,
    risk_free_rate: float = 0.0,
) -> pl.DataFrame:
    """Daily-return Sharpe over a rolling window (annualised)."""
    if window < 2:
        raise ValueError("Sharpe window must be >= 2")
    dates, values = _values(snapshots)
    out: list[float | None] = []
    rf_daily = risk_free_rate / TRADING_DAYS_PER_YEAR
    for i in range(len(values)):
        if i < window:
            out.append(None)
            continue
        # Returns from i-window+1 .. i (window observations including today's return).
        slice_returns = []
        for j in range(i - window + 1, i + 1):
            prev = values[j - 1]
            if prev > 0:
                slice_returns.append(values[j] / prev - 1.0)
        if len(slice_returns) < 2:
            out.append(None)
            continue
        mean = sum(slice_returns) / len(slice_returns)
        var = sum((r - mean) ** 2 for r in slice_returns) / max(len(slice_returns) - 1, 1)
        vol = math.sqrt(var)
        if vol == 0:
            out.append(0.0)
        else:
            out.append(((mean - rf_daily) / vol) * math.sqrt(TRADING_DAYS_PER_YEAR))
    return pl.DataFrame({"date": dates, "rolling_sharpe": out}).with_columns(
        pl.col("date").cast(pl.Date)
    )


def rolling_drawdown(snapshots: list[PortfolioSnapshot]) -> pl.DataFrame:
    """Per-day drawdown from running peak — equivalent to snapshot.drawdown."""
    dates, values = _values(snapshots)
    peak = -math.inf
    out: list[float] = []
    for v in values:
        peak = max(peak, v)
        out.append(v / peak - 1.0 if peak > 0 else 0.0)
    return pl.DataFrame({"date": dates, "rolling_drawdown": out}).with_columns(
        pl.col("date").cast(pl.Date)
    )


__all__ = ["rolling_cagr", "rolling_drawdown", "rolling_returns", "rolling_sharpe"]
