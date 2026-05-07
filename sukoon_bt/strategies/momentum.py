"""Momentum strategy — spec §15 (signal.type: momentum).

Ranks the universe by trailing total return over a configurable lookback
window and equal-weights the top N funds. Re-ranks at every REBALANCE
event the engine emits (the strategy doesn't drive cadence — that's the
engine's job per spec §3).

Funds without enough lookback history are skipped from ranking. If fewer
than ``top_n`` funds have history, the strategy still equal-weights the
ones that do (so a 3-fund universe with top_n=5 holds 100% of all 3).
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl

from sukoon_bt.core.context import Context
from sukoon_bt.core.events import Event
from sukoon_bt.strategies.base import Strategy


class Momentum(Strategy):
    """Top-N lookback-momentum strategy."""

    def __init__(
        self,
        universe: list[str],
        *,
        lookback_days: int,
        top_n: int,
    ) -> None:
        if not universe:
            raise ValueError("Momentum requires a non-empty universe")
        if lookback_days < 1:
            raise ValueError("lookback_days must be >= 1")
        if top_n < 1:
            raise ValueError("top_n must be >= 1")
        self._universe = list(universe)
        self._lookback_days = lookback_days
        self._top_n = top_n
        self._latest_targets: dict[str, float] = {}

    def initialize(self, context: Context) -> None:  # noqa: ARG002
        self._latest_targets = {}

    def on_day(self, event: Event, context: Context) -> None:  # noqa: ARG002
        # Re-ranking happens lazily inside target_allocations(), so on_day
        # is a no-op here. Kept for symmetry with the Strategy ABC.
        return None

    def generate_signals(self, context: Context) -> dict[str, float]:
        return self._rank(context)

    def target_allocations(self, context: Context) -> dict[str, float]:
        signals = self._rank(context)
        if not signals:
            self._latest_targets = {}
            return {}
        # Top-N selection.
        ordered = sorted(signals.items(), key=lambda kv: kv[1], reverse=True)
        selected = [fid for fid, _ in ordered[: self._top_n]]
        if not selected:
            self._latest_targets = {}
            return {}
        weight = 1.0 / len(selected)
        self._latest_targets = {fid: weight for fid in selected}
        return dict(self._latest_targets)

    # ----- internals ----------------------------------------------------

    def _rank(self, context: Context) -> dict[str, float]:
        """Map fund_id → trailing-window return. Funds missing data are dropped."""
        today = context.market.today
        lookback_start = today - timedelta(days=self._lookback_days)
        out: dict[str, float] = {}
        for fid in self._universe:
            df = context.market.nav_history.get(fid)
            if df is None or df.is_empty():
                continue
            ret = _trailing_return(df, lookback_start, today)
            if ret is not None:
                out[fid] = ret
        return out


def _trailing_return(df: pl.DataFrame, start, end) -> float | None:
    """Return ``nav[end] / nav[start_or_first_after] - 1`` or None."""
    # Latest NAV up to and including ``end``.
    end_df = df.filter(pl.col("date") <= end)
    if end_df.is_empty():
        return None
    end_nav = float(end_df["nav"][-1])
    # First NAV on or after ``start``.
    start_df = df.filter(pl.col("date") >= start)
    if start_df.is_empty():
        return None
    start_nav = float(start_df["nav"][0])
    if start_nav <= 0:
        return None
    return end_nav / start_nav - 1.0


__all__ = ["Momentum"]
