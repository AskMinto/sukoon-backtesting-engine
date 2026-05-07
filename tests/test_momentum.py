"""Momentum strategy tests."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from sukoon_bt.core.context import Context, MarketState
from sukoon_bt.portfolio.portfolio import Portfolio
from sukoon_bt.strategies.momentum import Momentum


def _nav(start: date, days: int, daily_pct: float) -> pl.DataFrame:
    rows = []
    nav = 100.0
    d = start
    for _ in range(days):
        rows.append({"date": d, "nav": nav})
        nav *= 1 + daily_pct
        d += timedelta(days=1)
    return pl.DataFrame(rows).with_columns(
        pl.col("date").cast(pl.Date), pl.col("nav").cast(pl.Float64)
    )


def _ctx(today: date, history: dict[str, pl.DataFrame]) -> Context:
    return Context(
        market=MarketState(today=today, navs={}, nav_history=history),
        portfolio=Portfolio.with_initial_capital(100_000.0),
        initial_capital=100_000.0,
    )


class TestMomentumConstructor:
    def test_empty_universe_rejected(self) -> None:
        with pytest.raises(ValueError):
            Momentum([], lookback_days=30, top_n=1)

    def test_zero_lookback_rejected(self) -> None:
        with pytest.raises(ValueError):
            Momentum(["A"], lookback_days=0, top_n=1)

    def test_zero_top_n_rejected(self) -> None:
        with pytest.raises(ValueError):
            Momentum(["A"], lookback_days=30, top_n=0)


class TestRanking:
    def test_top_n_selects_winners_equal_weight(self) -> None:
        # A: +0.2%/d, B: +0.1%/d, C: -0.05%/d. Over 60d, A > B > C.
        history = {
            "A": _nav(date(2024, 1, 1), 60, 0.002),
            "B": _nav(date(2024, 1, 1), 60, 0.001),
            "C": _nav(date(2024, 1, 1), 60, -0.0005),
        }
        strat = Momentum(["A", "B", "C"], lookback_days=30, top_n=2)
        targets = strat.target_allocations(_ctx(date(2024, 2, 28), history))
        assert set(targets) == {"A", "B"}
        assert all(w == pytest.approx(0.5) for w in targets.values())

    def test_top_n_larger_than_universe_holds_all(self) -> None:
        history = {
            "A": _nav(date(2024, 1, 1), 30, 0.001),
            "B": _nav(date(2024, 1, 1), 30, 0.002),
        }
        strat = Momentum(["A", "B"], lookback_days=15, top_n=5)
        targets = strat.target_allocations(_ctx(date(2024, 1, 30), history))
        assert set(targets) == {"A", "B"}
        assert all(w == pytest.approx(0.5) for w in targets.values())

    def test_funds_without_history_are_skipped(self) -> None:
        history = {
            "A": _nav(date(2024, 1, 1), 30, 0.001),
            # B is in universe but has empty history.
            "B": pl.DataFrame(schema={"date": pl.Date, "nav": pl.Float64}),
        }
        strat = Momentum(["A", "B"], lookback_days=15, top_n=2)
        targets = strat.target_allocations(_ctx(date(2024, 1, 30), history))
        assert set(targets) == {"A"}

    def test_rerank_changes_holdings(self) -> None:
        # First half of period A leads; second half B leads.
        d = date(2024, 1, 1)
        # Build A: +0.5% for 60d then -0.5% for 60d.
        a_rows = []
        nav = 100.0
        for i in range(120):
            a_rows.append({"date": d + timedelta(days=i), "nav": nav})
            nav *= 1 + (0.005 if i < 60 else -0.005)
        # Build B: -0.5% for 60d then +0.5% for 60d.
        b_rows = []
        nav = 100.0
        for i in range(120):
            b_rows.append({"date": d + timedelta(days=i), "nav": nav})
            nav *= 1 + (-0.005 if i < 60 else 0.005)
        history = {
            "A": pl.DataFrame(a_rows).with_columns(pl.col("date").cast(pl.Date), pl.col("nav").cast(pl.Float64)),
            "B": pl.DataFrame(b_rows).with_columns(pl.col("date").cast(pl.Date), pl.col("nav").cast(pl.Float64)),
        }
        strat = Momentum(["A", "B"], lookback_days=30, top_n=1)

        # Day 50: A still in its leading phase.
        early = strat.target_allocations(_ctx(d + timedelta(days=50), history))
        assert set(early) == {"A"}

        # Day 110: lookback (last 30 days) covers B's leading phase.
        late = strat.target_allocations(_ctx(d + timedelta(days=110), history))
        assert set(late) == {"B"}

    def test_signals_match_rank_order(self) -> None:
        history = {
            "A": _nav(date(2024, 1, 1), 30, 0.001),
            "B": _nav(date(2024, 1, 1), 30, 0.002),
        }
        strat = Momentum(["A", "B"], lookback_days=15, top_n=2)
        sig = strat.generate_signals(_ctx(date(2024, 1, 30), history))
        # B should rank higher than A.
        assert sig["B"] > sig["A"]
