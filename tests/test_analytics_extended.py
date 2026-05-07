"""Phase-2 analytics tests: Sortino, alpha/beta, IR, XIRR."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from sukoon_bt.analytics.metrics import (
    TRADING_DAYS_PER_YEAR,
    compute_benchmark_metrics,
    compute_performance,
    xirr,
)
from sukoon_bt.data.models import PortfolioSnapshot


def _series(start: date, days: int, daily_return: float, initial: float = 100_000.0) -> list[PortfolioSnapshot]:
    snaps: list[PortfolioSnapshot] = []
    value = initial
    peak = initial
    for i in range(days):
        d = start + timedelta(days=i)
        value *= 1 + daily_return
        peak = max(peak, value)
        dd = value / peak - 1.0
        snaps.append(
            PortfolioSnapshot(
                date=d,
                portfolio_value=value,
                cash=0.0,
                holdings_value=value,
                drawdown=min(dd, 0.0),
            )
        )
    return snaps


class TestSortino:
    def test_pure_growth_has_infinite_or_zero_downside_volatility(self) -> None:
        snaps = _series(date(2024, 1, 1), 60, daily_return=0.001)
        m = compute_performance(snaps)
        # All daily returns positive → no downside → Sortino reported as 0
        # (we deliberately don't return inf to avoid JSON-serialisation pain).
        assert m.sortino == 0.0

    def test_sortino_higher_than_sharpe_when_downside_quiet(self) -> None:
        # Constant +0.1% daily then a single small drop and recovery — downside
        # vol < total vol → Sortino > Sharpe.
        d = date(2024, 1, 1)
        snaps: list[PortfolioSnapshot] = []
        v = 100_000.0
        peak = v
        returns = [0.001] * 50 + [-0.0005] + [0.001] * 10
        for i, r in enumerate(returns):
            v *= 1 + r
            peak = max(peak, v)
            snaps.append(
                PortfolioSnapshot(
                    date=d + timedelta(days=i),
                    portfolio_value=v,
                    cash=0,
                    holdings_value=v,
                    drawdown=min(v / peak - 1, 0),
                )
            )
        m = compute_performance(snaps)
        # Both should be positive; Sortino should exceed Sharpe.
        assert m.sortino > m.sharpe > 0


class TestBenchmarkMetrics:
    def test_zero_alpha_when_portfolio_equals_benchmark(self) -> None:
        rs = [0.001, -0.002, 0.003, 0.0, -0.001, 0.002] * 10
        bm = compute_benchmark_metrics(rs, rs)
        assert bm.beta == pytest.approx(1.0)
        assert bm.alpha == pytest.approx(0.0, abs=1e-12)
        assert bm.tracking_error == 0.0
        assert bm.information_ratio == 0.0

    def test_beta_two_when_portfolio_amplifies_benchmark(self) -> None:
        bm_returns = [0.01, -0.02, 0.005, -0.005, 0.015, 0.0] * 8
        # 2x leverage exact replication → beta = 2, alpha = 0.
        port = [2 * r for r in bm_returns]
        m = compute_benchmark_metrics(port, bm_returns)
        assert m.beta == pytest.approx(2.0)
        assert m.alpha == pytest.approx(0.0, abs=1e-12)

    def test_information_ratio_positive_for_outperformance(self) -> None:
        bm = [0.0005] * 100
        port = [r + 0.0002 for r in bm]
        # Different tracking pattern: random tiny noise to create non-zero TE.
        port = [r + 0.0001 * ((-1) ** i) for i, r in enumerate(port)]
        m = compute_benchmark_metrics(port, bm)
        assert m.information_ratio > 0
        assert m.tracking_error > 0

    def test_misaligned_lengths_rejected(self) -> None:
        with pytest.raises(ValueError):
            compute_benchmark_metrics([0.01, 0.02], [0.01])

    def test_too_short_rejected(self) -> None:
        with pytest.raises(ValueError):
            compute_benchmark_metrics([0.01], [0.01])


class TestXIRR:
    def test_round_trip_one_year_10_pct(self) -> None:
        flows = [(date(2024, 1, 1), -100.0), (date(2025, 1, 1), 110.0)]
        rate = xirr(flows)
        # ~10% annualised, allowing for the 366-day leap year scaling.
        assert rate == pytest.approx(0.0996, abs=0.01)

    def test_xirr_via_compute_performance(self) -> None:
        snaps = _series(date(2024, 1, 1), 252, daily_return=0.0005)
        cf = [
            (snaps[0].date, -snaps[0].portfolio_value),
            (snaps[-1].date, snaps[-1].portfolio_value),
        ]
        m = compute_performance(snaps, cashflows=cf)
        assert m.xirr is not None
        # XIRR should be in the same ballpark as CAGR for a one-shot capital deployment.
        assert math.isclose(m.xirr, m.cagr, rel_tol=0.05)

    def test_requires_mixed_signs(self) -> None:
        with pytest.raises(ValueError):
            xirr([(date(2024, 1, 1), 100.0), (date(2025, 1, 1), 110.0)])

    def test_missing_cashflows_returns_none(self) -> None:
        snaps = _series(date(2024, 1, 1), 30, daily_return=0.001)
        m = compute_performance(snaps)
        assert m.xirr is None


class TestSharpeStillCorrect:
    """Regress the Sharpe we already had so the Phase-2 changes didn't break it."""

    def test_sharpe_with_risk_free(self) -> None:
        snaps = _series(date(2024, 1, 1), 252, daily_return=0.0005)
        # Constant return → Sharpe is reported as 0 (vol=0 by construction).
        m = compute_performance(snaps, risk_free_rate=0.04)
        assert m.sharpe == 0.0
        assert TRADING_DAYS_PER_YEAR == 252
