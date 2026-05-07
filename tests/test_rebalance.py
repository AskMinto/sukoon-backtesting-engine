"""Rebalance-planner tests — spec §11."""

from __future__ import annotations

import pytest

from sukoon_bt.execution.rebalance import (
    RebalanceConstraints,
    TradeInstruction,
    plan_rebalance,
)
from sukoon_bt.portfolio.holdings import HoldingsBook


def _book(*positions: tuple[str, float, float]) -> HoldingsBook:
    """positions = (fund_id, units, last_nav)."""
    book = HoldingsBook()
    for fid, units, nav in positions:
        h = book.get(fid)
        h.add_units(units, nav)
    return book


class TestPlanRebalance:
    def test_no_holdings_buys_targets_proportionally(self) -> None:
        book = _book()
        navs = {"A": 100.0, "B": 200.0}
        plan = plan_rebalance(
            holdings=book,
            targets={"A": 0.6, "B": 0.4},
            cash=100_000.0,
            navs=navs,
            constraints=RebalanceConstraints(min_trade_amount=1.0, tolerance=0.0),
        )
        # Two BUYs in fund_id-sorted order (A, B).
        assert [t.fund_id for t in plan] == ["A", "B"]
        assert all(t.action == "BUY" for t in plan)
        assert plan[0].amount == pytest.approx(60_000.0)
        assert plan[1].amount == pytest.approx(40_000.0)

    def test_drift_above_tolerance_sells(self) -> None:
        book = _book(("A", 100.0, 100.0))  # 100*100 = 10,000
        navs = {"A": 110.0}  # MV = 11,000
        plan = plan_rebalance(
            holdings=book,
            targets={"A": 0.5},  # target = 0.5 * (11_000 + 9_000 cash) = 10_000
            cash=9_000.0,
            navs=navs,
            constraints=RebalanceConstraints(min_trade_amount=1.0, tolerance=0.0),
        )
        # Need to sell 1,000 / 110 ≈ 9.09 units.
        assert len(plan) == 1
        assert plan[0].action == "SELL"
        assert plan[0].fund_id == "A"
        assert plan[0].units == pytest.approx(1_000 / 110, rel=1e-9)

    def test_tolerance_skips_minor_drift(self) -> None:
        book = _book(("A", 100.0, 100.0))
        # MV = 10,500; portfolio = 20,500; target 50% = 10,250 → drift -250 (-1.2%).
        navs = {"A": 105.0}
        plan = plan_rebalance(
            holdings=book,
            targets={"A": 0.5},
            cash=10_000.0,
            navs=navs,
            constraints=RebalanceConstraints(min_trade_amount=1.0, tolerance=0.05),
        )
        # 1.2% drift below 5% tolerance → no trade.
        assert plan == []

    def test_min_trade_amount_drops_micro_slices(self) -> None:
        book = _book()
        plan = plan_rebalance(
            holdings=book,
            targets={"A": 1.0},
            cash=50.0,  # below min_trade_amount
            navs={"A": 10.0},
            constraints=RebalanceConstraints(min_trade_amount=100.0),
        )
        assert plan == []

    def test_buy_capped_to_available_cash_after_sells(self) -> None:
        book = _book(("A", 50.0, 100.0))  # 5,000 in A
        # Target: 100% B; need to sell A → 5k cash; buy B with all of it.
        plan = plan_rebalance(
            holdings=book,
            targets={"B": 1.0},
            cash=0.0,
            navs={"A": 100.0, "B": 50.0},
            constraints=RebalanceConstraints(min_trade_amount=1.0, tolerance=0.0),
        )
        assert [t.fund_id for t in plan] == ["A", "B"]
        sell, buy = plan
        assert sell.action == "SELL"
        assert sell.fund_id == "A"
        assert sell.amount == pytest.approx(5_000.0)
        assert buy.action == "BUY"
        assert buy.fund_id == "B"
        assert buy.amount == pytest.approx(5_000.0)

    def test_missing_nav_for_target_skips(self) -> None:
        plan = plan_rebalance(
            holdings=_book(),
            targets={"A": 1.0},
            cash=10_000.0,
            navs={},
            constraints=RebalanceConstraints(min_trade_amount=1.0),
        )
        assert plan == []

    def test_zero_portfolio_returns_empty(self) -> None:
        plan = plan_rebalance(
            holdings=_book(),
            targets={"A": 1.0},
            cash=0.0,
            navs={"A": 100.0},
            constraints=RebalanceConstraints(),
        )
        assert plan == []


class TestTradeInstruction:
    def test_immutable(self) -> None:
        t = TradeInstruction(
            fund_id="A", action="BUY", nav=100, amount=1000, units=10,
            transaction_type=__import__("sukoon_bt.data.models", fromlist=["TransactionType"]).TransactionType.BUY,
        )
        with pytest.raises(Exception):
            t.fund_id = "B"  # type: ignore[misc]
