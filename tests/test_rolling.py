"""Rolling-metrics tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from sukoon_bt.analytics.rolling import (
    rolling_cagr,
    rolling_drawdown,
    rolling_returns,
    rolling_sharpe,
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
        snaps.append(
            PortfolioSnapshot(
                date=d,
                portfolio_value=value,
                cash=0.0,
                holdings_value=value,
                drawdown=min(value / peak - 1.0, 0.0),
            )
        )
    return snaps


class TestRollingReturns:
    def test_first_window_is_null(self) -> None:
        snaps = _series(date(2024, 1, 1), 30, daily_return=0.001)
        df = rolling_returns(snaps, window=10)
        assert df["rolling_return"][:10].to_list() == [None] * 10
        assert df["rolling_return"][10] is not None

    def test_constant_return(self) -> None:
        snaps = _series(date(2024, 1, 1), 30, daily_return=0.001)
        df = rolling_returns(snaps, window=5)
        # 5-day window with daily 0.1% drift: (1.001)^5 - 1 ≈ 0.005010
        assert df["rolling_return"][5] == pytest.approx((1.001) ** 5 - 1, rel=1e-9)

    def test_zero_window_rejected(self) -> None:
        with pytest.raises(ValueError):
            rolling_returns(_series(date(2024, 1, 1), 5, 0.0), window=0)


class TestRollingCAGR:
    def test_window_too_small_returns_nulls(self) -> None:
        snaps = _series(date(2024, 1, 1), 30, daily_return=0.001)
        df = rolling_cagr(snaps, window_days=10)
        assert df.columns == ["date", "rolling_return", "rolling_cagr"]
        # First 10 entries are null in rolling_return → None in rolling_cagr too.
        assert df["rolling_cagr"][:10].to_list() == [None] * 10


class TestRollingSharpe:
    def test_constant_drift_yields_zero(self) -> None:
        snaps = _series(date(2024, 1, 1), 60, daily_return=0.001)
        df = rolling_sharpe(snaps, window=20)
        # Constant-drift series has zero variance → Sharpe = 0 by our convention.
        valid = df["rolling_sharpe"].drop_nulls().to_list()
        assert all(v == 0.0 for v in valid)

    def test_short_window_rejected(self) -> None:
        with pytest.raises(ValueError):
            rolling_sharpe(_series(date(2024, 1, 1), 5, 0.0), window=1)


class TestRollingDrawdown:
    def test_pure_growth_zero_drawdown(self) -> None:
        snaps = _series(date(2024, 1, 1), 30, daily_return=0.001)
        df = rolling_drawdown(snaps)
        assert all(v == 0.0 for v in df["rolling_drawdown"].to_list())

    def test_pull_back_recorded(self) -> None:
        d = date(2024, 1, 1)
        snaps = []
        for i, v in enumerate([100, 110, 90, 95, 120]):
            snaps.append(
                PortfolioSnapshot(
                    date=d + timedelta(days=i),
                    portfolio_value=v,
                    cash=0,
                    holdings_value=v,
                    drawdown=0.0,  # not used by rolling_drawdown
                )
            )
        df = rolling_drawdown(snaps)
        # Day 2: peak 110, value 90 → -18.18%
        assert df["rolling_drawdown"][2] == pytest.approx(90 / 110 - 1.0)
        # Day 4: new peak 120, dd 0
        assert df["rolling_drawdown"][4] == 0.0
