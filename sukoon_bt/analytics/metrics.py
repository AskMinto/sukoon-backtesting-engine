"""Performance + risk metrics — spec §14.

Phase 1 scope: CAGR, absolute return, annualised volatility, Sharpe.
Sortino / alpha / beta / IR / XIRR ship in Phase 2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from sukoon_bt.data.models import PortfolioSnapshot

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    start_date: date
    end_date: date
    initial_value: float
    final_value: float
    absolute_return: float
    cagr: float
    annualized_volatility: float
    sharpe: float


def compute_performance(
    snapshots: list[PortfolioSnapshot],
    risk_free_rate: float = 0.0,
) -> PerformanceMetrics:
    """Compute Phase 1 performance metrics from a snapshot series."""
    if len(snapshots) < 2:
        raise ValueError("need at least two snapshots to compute performance")
    first, last = snapshots[0], snapshots[-1]
    initial = first.portfolio_value
    final = last.portfolio_value
    if initial <= 0:
        raise ValueError("initial portfolio value must be positive")

    absolute_return = final / initial - 1.0

    days = (last.date - first.date).days
    years = days / 365.25 if days > 0 else 0.0
    cagr = (final / initial) ** (1 / years) - 1 if years > 0 else 0.0

    daily_returns = _daily_returns(snapshots)
    if daily_returns:
        mean = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean) ** 2 for r in daily_returns) / max(len(daily_returns) - 1, 1)
        daily_vol = math.sqrt(variance)
        annualized_vol = daily_vol * math.sqrt(TRADING_DAYS_PER_YEAR)
        excess_daily = mean - risk_free_rate / TRADING_DAYS_PER_YEAR
        sharpe = (excess_daily / daily_vol) * math.sqrt(TRADING_DAYS_PER_YEAR) if daily_vol > 0 else 0.0
    else:
        annualized_vol = 0.0
        sharpe = 0.0

    return PerformanceMetrics(
        start_date=first.date,
        end_date=last.date,
        initial_value=initial,
        final_value=final,
        absolute_return=absolute_return,
        cagr=cagr,
        annualized_volatility=annualized_vol,
        sharpe=sharpe,
    )


def _daily_returns(snapshots: list[PortfolioSnapshot]) -> list[float]:
    out: list[float] = []
    prev = snapshots[0].portfolio_value
    for s in snapshots[1:]:
        if prev > 0:
            out.append(s.portfolio_value / prev - 1.0)
        prev = s.portfolio_value
    return out


__all__ = ["PerformanceMetrics", "TRADING_DAYS_PER_YEAR", "compute_performance"]
