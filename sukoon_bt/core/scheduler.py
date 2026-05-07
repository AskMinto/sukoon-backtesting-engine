"""Event scheduler — turns a trading-day calendar into an ordered event stream.

Trading days are derived from observed NAV dates rather than a synthetic
calendar so the engine never advances on a day for which we have no data.

For each trading day d the scheduler emits, in order:

  MARKET_OPEN(d)
  SIP_TRIGGER(d)         — only on configured SIP day-of-month
  REBALANCE(d)           — on the *first* trading day on/after the period boundary
  MONTH_END(d)           — only on the last trading day of a calendar month
  QUARTER_END / YEAR_END — analogous
  MARKET_CLOSE(d)
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sukoon_bt.core.events import (
    CashflowEvent,
    Event,
    EventType,
    MarketEvent,
    RebalanceEvent,
)

RebalanceFrequency = Literal["never", "monthly", "quarterly", "yearly"]


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    sip_amount: float = 0.0
    sip_day: int | None = None  # 1..31; if None and sip_amount > 0, defaults to 1
    rebalance_frequency: RebalanceFrequency = "never"


def schedule(trading_days: Iterable[date], config: SchedulerConfig) -> Iterator[Event]:
    """Yield engine events in chronological / intra-day order.

    Each MARKET_OPEN/MARKET_CLOSE pair brackets a trading day; in between we
    emit cashflow + period-boundary events.
    """
    days = sorted(set(trading_days))
    if not days:
        return

    sip_target_day = (
        config.sip_day if config.sip_day is not None else (1 if config.sip_amount > 0 else None)
    )

    sip_emitted_for_month: tuple[int, int] | None = None
    last_rebalanced_period: tuple[int, int] | tuple[int] | None = None

    for i, d in enumerate(days):
        next_d = days[i + 1] if i + 1 < len(days) else None
        is_last_of_month = next_d is None or next_d.month != d.month
        is_last_of_quarter = is_last_of_month and d.month % 3 == 0
        is_last_of_year = is_last_of_month and d.month == 12

        yield MarketEvent(type=EventType.MARKET_OPEN, date=d)

        # SIP — fire on the first trading day on/after the target day-of-month.
        if (
            config.sip_amount > 0
            and sip_target_day is not None
            and (sip_emitted_for_month != (d.year, d.month))
            and d.day >= sip_target_day
        ):
            yield CashflowEvent(type=EventType.SIP_TRIGGER, date=d, amount=config.sip_amount)
            sip_emitted_for_month = (d.year, d.month)

        # Rebalance — fire on the first trading day of each period.
        period_key = _period_key(d, config.rebalance_frequency)
        if period_key is not None and period_key != last_rebalanced_period:
            yield RebalanceEvent(type=EventType.REBALANCE, date=d)
            last_rebalanced_period = period_key

        if is_last_of_month:
            yield MarketEvent(type=EventType.MONTH_END, date=d)
        if is_last_of_quarter:
            yield MarketEvent(type=EventType.QUARTER_END, date=d)
        if is_last_of_year:
            yield MarketEvent(type=EventType.YEAR_END, date=d)

        yield MarketEvent(type=EventType.MARKET_CLOSE, date=d)


def _period_key(
    d: date,
    freq: RebalanceFrequency,
) -> tuple[int, int] | tuple[int] | None:
    if freq == "monthly":
        return (d.year, d.month)
    if freq == "quarterly":
        return (d.year, (d.month - 1) // 3)
    if freq == "yearly":
        return (d.year,)
    return None


__all__ = ["RebalanceFrequency", "SchedulerConfig", "schedule"]
