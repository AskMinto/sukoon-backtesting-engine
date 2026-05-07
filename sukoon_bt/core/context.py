"""Per-day execution context handed to strategies.

Strategies receive an immutable view of market state (today's date and
NAVs by fund) plus a *read-only* handle to the portfolio. They emit
target weights and the engine handles the bookings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from sukoon_bt.portfolio.portfolio import Portfolio


@dataclass(slots=True)
class MarketState:
    """Today's market snapshot."""

    today: date
    navs: dict[str, float]  # fund_id -> NAV on ``today`` (or last known)
    nav_history: dict[str, pl.DataFrame]  # fund_id -> full history (date, nav)


@dataclass(slots=True)
class Context:
    """Bundle passed to strategy hooks (spec §8).

    The portfolio is included for read-only inspection (e.g. the strategy
    wants to see current units to compute drift). Mutation must go through
    target_allocations(); the engine does the bookings.
    """

    market: MarketState
    portfolio: Portfolio
    initial_capital: float


__all__ = ["Context", "MarketState"]
