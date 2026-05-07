"""Buy-and-hold strategy.

Allocates equal weights across a fixed universe and never rotates.
Combine with ``rebalance_frequency: "never"`` to truly hold (the engine
will only invest the initial capital on the first REBALANCE event, so
configure at least one — typically a single rebalance at start, then
no further drift correction).

For a strict "invest once and never trade" run, set rebalance_frequency
to "yearly" (it'll fire once at start) or to "never" combined with a
SIP that uses these weights.
"""

from __future__ import annotations

from sukoon_bt.core.context import Context
from sukoon_bt.core.events import Event
from sukoon_bt.strategies.base import Strategy


class BuyAndHold(Strategy):
    """Equal-weight (or custom-weight) buy-and-hold over a fixed universe."""

    def __init__(self, fund_ids: list[str], weights: list[float] | None = None) -> None:
        if not fund_ids:
            raise ValueError("BuyAndHold requires at least one fund_id")
        if weights is None:
            weights = [1.0 / len(fund_ids)] * len(fund_ids)
        if len(weights) != len(fund_ids):
            raise ValueError("weights and fund_ids must have the same length")
        if any(w < 0 for w in weights):
            raise ValueError("weights must be non-negative")
        total = sum(weights)
        if total <= 0:
            raise ValueError("weights must sum to a positive value")
        # Normalise so the engine's reconciliation has clean targets.
        self._targets: dict[str, float] = {
            fid: w / total for fid, w in zip(fund_ids, weights, strict=True)
        }

    def initialize(self, context: Context) -> None:
        return None

    def on_day(self, event: Event, context: Context) -> None:
        return None

    def generate_signals(self, context: Context) -> dict[str, float]:
        return dict(self._targets)

    def target_allocations(self, context: Context) -> dict[str, float]:
        return dict(self._targets)


__all__ = ["BuyAndHold"]
