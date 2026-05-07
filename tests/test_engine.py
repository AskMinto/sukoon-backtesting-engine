"""Engine smoke tests with a synthetic NAV series and a stub strategy."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from sukoon_bt.core.context import Context
from sukoon_bt.core.engine import Engine, EngineConfig
from sukoon_bt.core.events import Event
from sukoon_bt.strategies.base import Strategy


class _FixedTargetStrategy(Strategy):
    """Holds 100% of one fund; rebalances at every REBALANCE event."""

    def __init__(self, fund_id: str) -> None:
        self._fund_id = fund_id

    def initialize(self, context: Context) -> None:
        pass

    def on_day(self, event: Event, context: Context) -> None:
        pass

    def generate_signals(self, context: Context) -> dict[str, float]:
        return {self._fund_id: 1.0}

    def target_allocations(self, context: Context) -> dict[str, float]:
        return {self._fund_id: 1.0}


def _linear_nav_history(start: date, days: int, nav0: float, daily_pct: float) -> pl.DataFrame:
    rows = []
    nav = nav0
    d = start
    for _ in range(days):
        if d.weekday() < 5:  # weekdays only
            rows.append({"date": d, "nav": nav})
            nav *= 1 + daily_pct
        d += timedelta(days=1)
    return pl.DataFrame(rows).with_columns(pl.col("date").cast(pl.Date), pl.col("nav").cast(pl.Float64))


class TestEngine:
    def test_buy_and_hold_via_monthly_rebalance_invests_capital(self) -> None:
        nav = _linear_nav_history(date(2024, 1, 1), days=90, nav0=100.0, daily_pct=0.001)
        engine = Engine(
            strategy=_FixedTargetStrategy("X"),
            nav_history={"X": nav},
            config=EngineConfig(initial_capital=100_000.0, rebalance_frequency="monthly"),
        )
        result = engine.run()

        # Cash should be near-zero after first rebalance buys ~100% of capital.
        assert result.portfolio.cash < 100.0
        # Holdings present in fund X.
        assert result.portfolio.holdings.units("X") > 0
        # Portfolio value grew (we used positive daily drift).
        final = result.portfolio.snapshots[-1]
        assert final.portfolio_value > 100_000.0
        # Snapshots one per trading day.
        assert len(result.portfolio.snapshots) == nav.height

    def test_no_rebalance_means_no_trades(self) -> None:
        nav = _linear_nav_history(date(2024, 1, 1), days=30, nav0=100.0, daily_pct=0.0)
        engine = Engine(
            strategy=_FixedTargetStrategy("X"),
            nav_history={"X": nav},
            config=EngineConfig(initial_capital=100_000.0, rebalance_frequency="never"),
        )
        result = engine.run()
        assert len(result.portfolio.ledger) == 0
        assert result.portfolio.cash == 100_000.0
        # Snapshots still produced; portfolio value == cash.
        assert result.portfolio.snapshots[-1].portfolio_value == pytest.approx(100_000.0)

    def test_sip_invests_each_month(self) -> None:
        nav = _linear_nav_history(date(2024, 1, 1), days=90, nav0=100.0, daily_pct=0.0)
        engine = Engine(
            strategy=_FixedTargetStrategy("X"),
            nav_history={"X": nav},
            config=EngineConfig(
                initial_capital=0.0,
                sip_amount=10_000.0,
                sip_day=5,
                rebalance_frequency="never",
            ),
        )
        result = engine.run()
        sips = [tx for tx in result.portfolio.ledger if tx.transaction_type.value == "SIP"]
        # Three SIPs across Jan/Feb/Mar (target day 5 falls on a weekday in all 3).
        assert len(sips) == 3
        for tx in sips:
            assert tx.amount == pytest.approx(10_000.0)

    def test_empty_nav_history_raises(self) -> None:
        with pytest.raises(ValueError):
            Engine(
                strategy=_FixedTargetStrategy("X"),
                nav_history={},
                config=EngineConfig(initial_capital=100_000.0),
            )
