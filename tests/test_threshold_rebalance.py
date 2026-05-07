"""Threshold rebalance — spec §10."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from sukoon_bt.core.context import Context
from sukoon_bt.core.engine import Engine, EngineConfig
from sukoon_bt.core.events import Event
from sukoon_bt.strategies.base import Strategy


class _FixedTwoFundStrategy(Strategy):
    def __init__(self, weights: dict[str, float]) -> None:
        self._w = weights

    def initialize(self, context: Context) -> None:
        pass

    def on_day(self, event: Event, context: Context) -> None:
        pass

    def generate_signals(self, context: Context) -> dict[str, float]:
        return dict(self._w)

    def target_allocations(self, context: Context) -> dict[str, float]:
        return dict(self._w)


def _nav_history(start: date, days: int, *, a_drift: float, b_drift: float) -> dict[str, pl.DataFrame]:
    rows_a = []
    rows_b = []
    nav_a = 100.0
    nav_b = 100.0
    d = start
    for _ in range(days):
        if d.weekday() < 5:
            rows_a.append({"date": d, "nav": nav_a})
            rows_b.append({"date": d, "nav": nav_b})
            nav_a *= 1 + a_drift
            nav_b *= 1 + b_drift
        d += timedelta(days=1)
    return {
        "A": pl.DataFrame(rows_a).with_columns(pl.col("date").cast(pl.Date), pl.col("nav").cast(pl.Float64)),
        "B": pl.DataFrame(rows_b).with_columns(pl.col("date").cast(pl.Date), pl.col("nav").cast(pl.Float64)),
    }


def test_threshold_triggers_rebalance_when_drift_exceeds() -> None:
    """A drifts up sharply; threshold rebalance brings it back."""
    nav = _nav_history(date(2024, 1, 1), days=120, a_drift=0.005, b_drift=-0.002)
    engine = Engine(
        strategy=_FixedTwoFundStrategy({"A": 0.5, "B": 0.5}),
        nav_history=nav,
        config=EngineConfig(
            initial_capital=100_000.0,
            rebalance_frequency="yearly",  # set initial weights once
            rebalance_threshold=0.05,
        ),
    )
    result = engine.run()
    # The drift triggers more than 1 rebalance via threshold (over and above
    # the single yearly rebalance at start).
    rebal_buys = [
        tx for tx in result.portfolio.ledger if tx.transaction_type.value == "BUY"
    ]
    rebal_sells = [
        tx for tx in result.portfolio.ledger if tx.transaction_type.value == "SELL"
    ]
    # At least one SELL must have happened — that's the threshold rebalance
    # selling A back into B.
    assert len(rebal_sells) >= 1
    assert len(rebal_buys) >= 2  # initial double-buy + threshold-triggered rebuy of B


def test_threshold_zero_disables() -> None:
    nav = _nav_history(date(2024, 1, 1), days=60, a_drift=0.005, b_drift=-0.002)
    engine = Engine(
        strategy=_FixedTwoFundStrategy({"A": 0.5, "B": 0.5}),
        nav_history=nav,
        config=EngineConfig(
            initial_capital=100_000.0,
            rebalance_frequency="yearly",
            rebalance_threshold=0.0,  # disabled
        ),
    )
    result = engine.run()
    sells = [tx for tx in result.portfolio.ledger if tx.transaction_type.value == "SELL"]
    assert sells == []  # no threshold → no rebalance even though A drifted up
