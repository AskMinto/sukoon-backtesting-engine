"""Event types — spec §20.

Strategies do not call into the engine; the engine emits events and
strategies react. Events are immutable dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class EventType(StrEnum):
    MARKET_OPEN = "MARKET_OPEN"
    MARKET_CLOSE = "MARKET_CLOSE"
    MONTH_END = "MONTH_END"
    QUARTER_END = "QUARTER_END"
    YEAR_END = "YEAR_END"
    REBALANCE = "REBALANCE"
    SIP_TRIGGER = "SIP_TRIGGER"
    SWP_TRIGGER = "SWP_TRIGGER"
    STP_TRIGGER = "STP_TRIGGER"


@dataclass(frozen=True, slots=True)
class Event:
    """Base event payload."""

    type: EventType
    date: date


@dataclass(frozen=True, slots=True)
class MarketEvent(Event):
    """Daily market tick (open/close)."""


@dataclass(frozen=True, slots=True)
class CashflowEvent(Event):
    """Recurring cashflow event (SIP/SWP/STP)."""

    amount: float


@dataclass(frozen=True, slots=True)
class RebalanceEvent(Event):
    """Periodic or threshold-driven rebalance trigger."""


__all__ = ["CashflowEvent", "Event", "EventType", "MarketEvent", "RebalanceEvent"]
