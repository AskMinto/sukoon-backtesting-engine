"""Strategy interface — spec §8.

Strategies emit signals and target weights only. The engine calls these
hooks at the right point in the daily pipeline (spec §9). Strategies
must NOT mutate the Portfolio directly — doing so would defeat
deterministic backtesting and tax-aware rebalancing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sukoon_bt.core.context import Context
    from sukoon_bt.core.events import Event


class Strategy(ABC):
    """Abstract base class every strategy implements."""

    @abstractmethod
    def initialize(self, context: "Context") -> None:
        """Called once with the first-day context before any events fire."""

    @abstractmethod
    def on_day(self, event: "Event", context: "Context") -> None:
        """Called on each MARKET_OPEN. Strategies may stash signals here."""

    @abstractmethod
    def generate_signals(self, context: "Context") -> dict[str, float]:
        """Optional helper invoked by target_allocations(); free-form."""

    @abstractmethod
    def target_allocations(self, context: "Context") -> dict[str, float]:
        """Return target weights ``{fund_id: weight}`` summing to ≤ 1.0.

        Weights remaining below 1.0 imply held cash. The engine reconciles
        target vs. current holdings into trade instructions.
        """


__all__ = ["Strategy"]
