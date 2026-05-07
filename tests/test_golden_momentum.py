"""Golden momentum test against fixed multi-fund NAV fixtures.

Fixtures:
  * MOM-A: +0.3%/d for 60 days, then -0.2%/d for 60 days. Loud first-half
    leader, sharp second-half loser.
  * MOM-B: +0.1%/d constant.
  * MOM-C: +0.05%/d constant.

A momentum(30, top_n=1) strategy should:
  * On day ~40: hold MOM-A (strongest 30d window).
  * On day ~100 (well into A's downturn): hold MOM-B (A's 30d return is
    deeply negative, B is steadily positive).

The full backtest (monthly rebalance) should rotate from A to B during
the regime change and end up holding B.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from sukoon_bt.core.context import Context, MarketState
from sukoon_bt.core.engine import Engine, EngineConfig
from sukoon_bt.portfolio.portfolio import Portfolio
from sukoon_bt.strategies.momentum import Momentum

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> pl.DataFrame:
    return pl.read_parquet(FIXTURES / f"golden_nav_MOM-{name}.parquet")


def _ctx(today: date, history: dict[str, pl.DataFrame]) -> Context:
    return Context(
        market=MarketState(today=today, navs={}, nav_history=history),
        portfolio=Portfolio.with_initial_capital(0),
        initial_capital=0.0,
    )


@pytest.fixture
def history() -> dict[str, pl.DataFrame]:
    return {
        "MOM-A": _load("A"),
        "MOM-B": _load("B"),
        "MOM-C": _load("C"),
    }


class TestRanking:
    def test_picks_a_during_first_half(self, history: dict[str, pl.DataFrame]) -> None:
        strat = Momentum(["MOM-A", "MOM-B", "MOM-C"], lookback_days=30, top_n=1)
        # Around day 40 — A has been the strongest for the past 30 days.
        targets = strat.target_allocations(_ctx(date(2024, 2, 26), history))
        assert set(targets) == {"MOM-A"}

    def test_picks_b_during_a_downturn(self, history: dict[str, pl.DataFrame]) -> None:
        strat = Momentum(["MOM-A", "MOM-B", "MOM-C"], lookback_days=30, top_n=1)
        # Day ~100 — A's 30d window is now in its declining phase, B keeps rising.
        targets = strat.target_allocations(_ctx(date(2024, 5, 18), history))
        assert set(targets) == {"MOM-B"}


class TestEndToEndMomentum:
    def test_engine_rotates_a_to_b_and_holds_b(self, history: dict[str, pl.DataFrame]) -> None:
        engine = Engine(
            strategy=Momentum(["MOM-A", "MOM-B", "MOM-C"], lookback_days=30, top_n=1),
            nav_history=history,
            config=EngineConfig(
                initial_capital=100_000.0,
                rebalance_frequency="monthly",
                rebalance_min_trade=1.0,
            ),
        )
        result = engine.run()

        # Must have at least one BUY and one SELL — the rotation.
        types = [tx.transaction_type.value for tx in result.portfolio.ledger]
        assert "BUY" in types
        assert "SELL" in types

        # Final holdings: most weight in MOM-B (winner of late period).
        nav_b_last = float(_load("B")["nav"][-1])
        nav_a_last = float(_load("A")["nav"][-1])
        nav_c_last = float(_load("C")["nav"][-1])
        b_value = result.portfolio.holdings.get("MOM-B").market_value(nav_b_last)
        a_value = result.portfolio.holdings.get("MOM-A").market_value(nav_a_last)
        c_value = result.portfolio.holdings.get("MOM-C").market_value(nav_c_last)
        # B dominates by end of run.
        assert b_value > a_value
        assert b_value > c_value

    def test_deterministic_replay(self, history: dict[str, pl.DataFrame]) -> None:
        def run_once() -> tuple[float, int]:
            engine = Engine(
                strategy=Momentum(["MOM-A", "MOM-B", "MOM-C"], lookback_days=30, top_n=1),
                nav_history=history,
                config=EngineConfig(initial_capital=100_000.0, rebalance_frequency="monthly", rebalance_min_trade=1.0),
            )
            r = engine.run()
            return (
                r.portfolio.snapshots[-1].portfolio_value,
                len(r.portfolio.ledger),
            )

        a = run_once()
        b = run_once()
        assert a == b
