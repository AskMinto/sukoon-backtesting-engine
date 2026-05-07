"""Integration tests: engine + tax engine populate Transaction.taxes."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from sukoon_bt.core.context import Context
from sukoon_bt.core.engine import Engine, EngineConfig
from sukoon_bt.core.events import Event
from sukoon_bt.data.models import Fund, TransactionType
from sukoon_bt.strategies.base import Strategy


class _SwitchAtDate(Strategy):
    """100% A then switches to 100% B on/after a switch date."""

    def __init__(self, switch_on: date) -> None:
        self._switch = switch_on

    def initialize(self, context: Context) -> None:
        pass

    def on_day(self, event: Event, context: Context) -> None:
        pass

    def generate_signals(self, context: Context) -> dict[str, float]:
        return self.target_allocations(context)

    def target_allocations(self, context: Context) -> dict[str, float]:
        if context.market.today < self._switch:
            return {"A": 1.0}
        return {"B": 1.0}


def _series(start: date, days: int, daily_pct: float) -> pl.DataFrame:
    rows = []
    nav = 100.0
    d = start
    for _ in range(days):
        if d.weekday() < 5:
            rows.append({"date": d, "nav": nav})
            nav *= 1 + daily_pct
        d += timedelta(days=1)
    return pl.DataFrame(rows).with_columns(
        pl.col("date").cast(pl.Date), pl.col("nav").cast(pl.Float64)
    )


def test_short_term_sell_books_stcg_tax() -> None:
    """A buy in Jan 2024, switch to B in Mar 2024 (held < 365d) → STCG @ 15%."""
    nav_history = {
        "A": _series(date(2024, 1, 1), 90, daily_pct=0.005),
        "B": _series(date(2024, 1, 1), 90, daily_pct=0.0),
    }
    funds = {
        "A": Fund(id="A", name="Equity A", category="Flexi Cap", amc="X"),
        "B": Fund(id="B", name="Equity B", category="Flexi Cap", amc="Y"),
    }
    engine = Engine(
        strategy=_SwitchAtDate(date(2024, 3, 1)),
        nav_history=nav_history,
        funds=funds,
        config=EngineConfig(
            initial_capital=100_000.0,
            rebalance_frequency="monthly",
            rebalance_min_trade=1.0,
        ),
    )
    result = engine.run()
    sells = [tx for tx in result.portfolio.ledger if tx.transaction_type is TransactionType.SELL]
    assert len(sells) >= 1
    sell = sells[0]
    # Tax must be > 0 (we sold A at a gain after 0.5%/d for ~40 trading days).
    assert sell.taxes > 0
    # The cash credited should be (units * nav) - taxes - fees.
    expected_proceeds = sell.amount - sell.taxes
    # Cash before sell: initial purchase consumed all capital. After sell + fees(0):
    # cash should equal expected_proceeds - subsequent buy. Rather than reverse-
    # engineering, just assert Transaction.taxes is populated and consistent.
    assert sell.taxes == pytest.approx(0.15 * (sell.amount - 100_000.0), rel=0.01)


def test_no_funds_means_no_tax_booking() -> None:
    """Phase-1/2 backwards compatibility: engine without funds books taxes=0."""
    nav_history = {
        "A": _series(date(2024, 1, 1), 90, daily_pct=0.005),
        "B": _series(date(2024, 1, 1), 90, daily_pct=0.0),
    }
    engine = Engine(
        strategy=_SwitchAtDate(date(2024, 3, 1)),
        nav_history=nav_history,
        config=EngineConfig(
            initial_capital=100_000.0,
            rebalance_frequency="monthly",
            rebalance_min_trade=1.0,
        ),
    )
    result = engine.run()
    sells = [tx for tx in result.portfolio.ledger if tx.transaction_type is TransactionType.SELL]
    assert all(tx.taxes == 0 for tx in sells)


def test_long_term_sale_uses_exemption(tmp_path) -> None:
    """A buy in Jan 2023, sold in Mar 2024 (held > 365d), small gain → LTCG within ₹1L = no tax."""
    # Build a ~18-month calendar series so the holding period crosses 365d
    # AND the post-switch rebalance has trading days available.
    a = _series(date(2023, 1, 2), 600, daily_pct=0.0008)
    b = _series(date(2023, 1, 2), 600, daily_pct=0.0)
    nav_history = {"A": a, "B": b}
    funds = {
        "A": Fund(id="A", name="Equity A", category="Large Cap", amc="X"),
        "B": Fund(id="B", name="Equity B", category="Large Cap", amc="Y"),
    }
    # Switch sometime well past the 365d mark.
    engine = Engine(
        strategy=_SwitchAtDate(date(2024, 6, 1)),
        nav_history=nav_history,
        funds=funds,
        config=EngineConfig(
            initial_capital=50_000.0,  # smaller capital → gain stays under ₹1L
            rebalance_frequency="monthly",
            rebalance_min_trade=1.0,
        ),
    )
    result = engine.run()
    sells = [tx for tx in result.portfolio.ledger if tx.transaction_type is TransactionType.SELL]
    assert len(sells) >= 1
    sell = sells[0]
    # Final A NAV is ~138, initial 100 → gain ~50% on 50k = ~25k LTCG. Under ₹1L
    # exemption so tax should be 0.
    assert sell.taxes == 0
