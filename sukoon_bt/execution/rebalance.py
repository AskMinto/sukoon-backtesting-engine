"""Rebalance reconciliation — spec §11.

Pure function: given current holdings, target weights, available cash,
market prices, and constraints, produce a deterministic ordered list of
TradeInstructions. The engine applies them via Portfolio.buy/sell.

Constraints (Phase 2):
  * minimum trade size — skip slices smaller than this rupee amount
  * tolerance — skip funds already within this fraction of target
  * exit-load lookup hook — placeholder; real rules ship in Phase 3

Tax-aware optimisation (e.g. preferring lots beyond LTCG holding period
when selling) is also Phase 3.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from sukoon_bt.data.models import TransactionType
from sukoon_bt.portfolio.holdings import HoldingsBook

Action = Literal["BUY", "SELL"]


@dataclass(frozen=True, slots=True)
class TradeInstruction:
    """A single trade the engine will book through Portfolio."""

    fund_id: str
    action: Action
    nav: float
    # For BUY: rupee amount to spend. For SELL: number of units to sell.
    amount: float
    units: float
    transaction_type: TransactionType


@dataclass(frozen=True, slots=True)
class RebalanceConstraints:
    min_trade_amount: float = 100.0  # ₹ — skip slices smaller than this
    tolerance: float = 0.0  # fraction; e.g. 0.005 = 0.5% drift tolerance
    # Hook for future exit-load awareness; called as
    #   exit_load(fund_id, units, holding_period_days) -> rupee penalty
    exit_load_fn: Callable[[str, float, int], float] | None = None


def plan_rebalance(
    *,
    holdings: HoldingsBook,
    targets: Mapping[str, float],
    cash: float,
    navs: Mapping[str, float],
    constraints: RebalanceConstraints,
) -> list[TradeInstruction]:
    """Return the trade list to move ``holdings + cash`` toward ``targets``.

    Sells precede buys so freed cash funds the buys. Funds already within
    the per-fund tolerance band are skipped entirely. Slices smaller than
    ``min_trade_amount`` are dropped to avoid noisy micro-rebalances.
    """
    portfolio_value = cash + sum(
        holdings.get(fid).market_value(navs.get(fid))
        for fid in (set(holdings.rows) | set(targets))
        if navs.get(fid) is not None
    )
    if portfolio_value <= 0:
        return []

    # Build (fund_id, current_value, target_value, drift) rows for every
    # fund that's either currently held or in the target set.
    rows: list[tuple[str, float, float, float]] = []
    for fid in set(holdings.rows) | set(targets):
        nav = navs.get(fid)
        if nav is None or nav <= 0:
            continue
        current = holdings.get(fid).market_value(nav)
        target = targets.get(fid, 0.0) * portfolio_value
        delta = target - current
        rows.append((fid, current, target, delta))

    sells: list[TradeInstruction] = []
    buys: list[TradeInstruction] = []

    for fid, _current, _target, delta in rows:
        nav = navs[fid]
        # Tolerance band — skip if drift below tolerance fraction of portfolio.
        if abs(delta) < constraints.tolerance * portfolio_value:
            continue
        # Min trade amount filter.
        if abs(delta) < constraints.min_trade_amount:
            continue
        if delta < 0:
            units_to_sell = min(-delta / nav, holdings.units(fid))
            if units_to_sell * nav < constraints.min_trade_amount:
                continue
            sells.append(
                TradeInstruction(
                    fund_id=fid,
                    action="SELL",
                    nav=nav,
                    amount=units_to_sell * nav,
                    units=units_to_sell,
                    transaction_type=TransactionType.SELL,
                )
            )
        else:
            buys.append(
                TradeInstruction(
                    fund_id=fid,
                    action="BUY",
                    nav=nav,
                    amount=delta,
                    units=delta / nav,
                    transaction_type=TransactionType.BUY,
                )
            )

    sells.sort(key=lambda t: t.fund_id)
    buys.sort(key=lambda t: t.fund_id)

    # Cap aggregate buys to (cash + sell_proceeds) so we never overspend.
    sell_proceeds = sum(t.amount for t in sells)
    available = cash + sell_proceeds
    capped: list[TradeInstruction] = []
    for t in buys:
        if available <= constraints.min_trade_amount:
            break
        amount = min(t.amount, available)
        if amount < constraints.min_trade_amount:
            continue
        capped.append(
            TradeInstruction(
                fund_id=t.fund_id,
                action="BUY",
                nav=t.nav,
                amount=amount,
                units=amount / t.nav,
                transaction_type=TransactionType.BUY,
            )
        )
        available -= amount

    return [*sells, *capped]


__all__ = ["Action", "RebalanceConstraints", "TradeInstruction", "plan_rebalance"]
