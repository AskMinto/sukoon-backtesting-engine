"""Performance + risk metrics — spec §14."""

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
    sortino: float
    xirr: float | None


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    """Strategy-vs-benchmark stats; all None when no benchmark series is supplied."""

    alpha: float
    beta: float
    information_ratio: float
    tracking_error: float


def compute_performance(
    snapshots: list[PortfolioSnapshot],
    risk_free_rate: float = 0.0,
    cashflows: list[tuple[date, float]] | None = None,
) -> PerformanceMetrics:
    """CAGR, return, vol, Sharpe, Sortino, and optional XIRR.

    ``cashflows`` is a list of (date, signed amount) where positive = inflow
    (deposit), negative = outflow (withdrawal). A typical buy-and-hold has
    one negative cashflow at start (initial capital), one positive at end
    (final value). If omitted XIRR is None.
    """
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
        rf_daily = risk_free_rate / TRADING_DAYS_PER_YEAR
        excess_daily = mean - rf_daily
        sharpe = (excess_daily / daily_vol) * math.sqrt(TRADING_DAYS_PER_YEAR) if daily_vol > 0 else 0.0
        # Sortino uses downside deviation (only returns below risk-free).
        downside = [min(r - rf_daily, 0.0) for r in daily_returns]
        downside_var = sum(d * d for d in downside) / len(downside)
        downside_vol = math.sqrt(downside_var)
        sortino = (excess_daily / downside_vol) * math.sqrt(TRADING_DAYS_PER_YEAR) if downside_vol > 0 else 0.0
    else:
        annualized_vol = 0.0
        sharpe = 0.0
        sortino = 0.0

    xirr_value: float | None
    if cashflows:
        try:
            xirr_value = xirr(cashflows)
        except (ValueError, ArithmeticError):
            xirr_value = None
    else:
        xirr_value = None

    return PerformanceMetrics(
        start_date=first.date,
        end_date=last.date,
        initial_value=initial,
        final_value=final,
        absolute_return=absolute_return,
        cagr=cagr,
        annualized_volatility=annualized_vol,
        sharpe=sharpe,
        sortino=sortino,
        xirr=xirr_value,
    )


def compute_benchmark_metrics(
    portfolio_returns: list[float],
    benchmark_returns: list[float],
) -> BenchmarkMetrics:
    """Alpha, beta, information ratio, tracking error.

    Both inputs must be the same length and aligned by date. Beta is
    cov(portfolio, benchmark) / var(benchmark). Alpha is the
    annualised intercept of portfolio_return = alpha + beta * benchmark_return.
    Tracking error is the annualised stdev of (portfolio - benchmark)
    daily returns. IR = mean(portfolio - benchmark) / tracking_error,
    annualised.
    """
    if len(portfolio_returns) != len(benchmark_returns):
        raise ValueError("portfolio and benchmark returns must align in length")
    if len(portfolio_returns) < 2:
        raise ValueError("need at least two return observations")

    n = len(portfolio_returns)
    mean_p = sum(portfolio_returns) / n
    mean_b = sum(benchmark_returns) / n
    var_b = sum((b - mean_b) ** 2 for b in benchmark_returns) / max(n - 1, 1)
    cov = sum((p - mean_p) * (b - mean_b) for p, b in zip(portfolio_returns, benchmark_returns, strict=True)) / max(n - 1, 1)
    beta = cov / var_b if var_b > 0 else 0.0
    # Daily alpha then annualise.
    daily_alpha = mean_p - beta * mean_b
    alpha = daily_alpha * TRADING_DAYS_PER_YEAR

    diffs = [p - b for p, b in zip(portfolio_returns, benchmark_returns, strict=True)]
    mean_diff = sum(diffs) / n
    var_diff = sum((d - mean_diff) ** 2 for d in diffs) / max(n - 1, 1)
    daily_te = math.sqrt(var_diff)
    tracking_error = daily_te * math.sqrt(TRADING_DAYS_PER_YEAR)
    info_ratio = (mean_diff / daily_te) * math.sqrt(TRADING_DAYS_PER_YEAR) if daily_te > 0 else 0.0

    return BenchmarkMetrics(
        alpha=alpha,
        beta=beta,
        information_ratio=info_ratio,
        tracking_error=tracking_error,
    )


def xirr(cashflows: list[tuple[date, float]], guess: float = 0.1, tol: float = 1e-7, max_iter: int = 200) -> float:
    """Internal rate of return for irregular cashflows (Newton's method).

    Convention matches Excel's XIRR: positive cashflow = received, negative
    = paid. For a backtest, pass negative on contribution dates and a single
    positive on the final-value date::

        xirr([(start, -capital), (end, final_value)])

    Raises ValueError if the series doesn't contain at least one positive
    and one negative value, or if Newton's method fails to converge.
    """
    if len(cashflows) < 2:
        raise ValueError("XIRR requires at least two cashflows")
    flows = sorted(cashflows, key=lambda x: x[0])
    if not (any(v > 0 for _, v in flows) and any(v < 0 for _, v in flows)):
        raise ValueError("XIRR requires at least one positive and one negative cashflow")

    t0 = flows[0][0]
    deltas = [(d - t0).days / 365.25 for d, _ in flows]
    values = [v for _, v in flows]

    def npv(rate: float) -> float:
        return sum(v / (1 + rate) ** t for v, t in zip(values, deltas, strict=True))

    def npv_prime(rate: float) -> float:
        return sum(-t * v / (1 + rate) ** (t + 1) for v, t in zip(values, deltas, strict=True))

    rate = guess
    for _ in range(max_iter):
        f = npv(rate)
        fp = npv_prime(rate)
        if abs(fp) < 1e-12:
            raise ArithmeticError("XIRR derivative collapsed; cannot converge")
        next_rate = rate - f / fp
        if next_rate <= -1.0:
            next_rate = (rate + (-1.0)) / 2 + 1e-9  # clamp to (-1, ∞)
        if abs(next_rate - rate) < tol:
            return next_rate
        rate = next_rate
    raise ArithmeticError("XIRR failed to converge")


def _daily_returns(snapshots: list[PortfolioSnapshot]) -> list[float]:
    out: list[float] = []
    prev = snapshots[0].portfolio_value
    for s in snapshots[1:]:
        if prev > 0:
            out.append(s.portfolio_value / prev - 1.0)
        prev = s.portfolio_value
    return out


__all__ = [
    "BenchmarkMetrics",
    "PerformanceMetrics",
    "TRADING_DAYS_PER_YEAR",
    "compute_benchmark_metrics",
    "compute_performance",
    "xirr",
]
