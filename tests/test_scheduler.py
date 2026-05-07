"""Scheduler tests."""

from __future__ import annotations

from datetime import date

from sukoon_bt.core.events import EventType
from sukoon_bt.core.scheduler import SchedulerConfig, schedule


def _trading_days() -> list[date]:
    # Three months of synthetic weekday-ish dates: skip weekends.
    days: list[date] = []
    d = date(2024, 1, 1)
    while d <= date(2024, 3, 29):
        if d.weekday() < 5:
            days.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    return days


def test_market_open_close_per_day() -> None:
    days = _trading_days()
    events = list(schedule(days, SchedulerConfig()))
    opens = [e for e in events if e.type is EventType.MARKET_OPEN]
    closes = [e for e in events if e.type is EventType.MARKET_CLOSE]
    assert [e.date for e in opens] == days
    assert [e.date for e in closes] == days


def test_month_end_emitted_on_last_trading_day_of_month() -> None:
    days = _trading_days()
    events = list(schedule(days, SchedulerConfig()))
    month_ends = [e.date for e in events if e.type is EventType.MONTH_END]
    # Last trading day of Jan/Feb/Mar 2024 by weekday-only filter:
    assert month_ends == [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 29)]


def test_quarter_and_year_end() -> None:
    days = _trading_days()
    events = list(schedule(days, SchedulerConfig()))
    qends = [e.date for e in events if e.type is EventType.QUARTER_END]
    yends = [e.date for e in events if e.type is EventType.YEAR_END]
    # Mar is end of Q1 within our window. No year-end.
    assert qends == [date(2024, 3, 29)]
    assert yends == []


def test_sip_fires_once_per_month_on_first_trading_day_after_target() -> None:
    days = _trading_days()
    events = list(
        schedule(days, SchedulerConfig(sip_amount=10000.0, sip_day=5))
    )
    sips = [e for e in events if e.type is EventType.SIP_TRIGGER]
    # Day 5 of Jan 2024 is Friday → expect Jan 5; Feb 5 Mon → Feb 5; Mar 5 Tue → Mar 5.
    assert [(e.date, e.amount) for e in sips] == [
        (date(2024, 1, 5), 10000.0),
        (date(2024, 2, 5), 10000.0),
        (date(2024, 3, 5), 10000.0),
    ]


def test_monthly_rebalance_fires_on_first_trading_day_of_each_month() -> None:
    days = _trading_days()
    events = list(schedule(days, SchedulerConfig(rebalance_frequency="monthly")))
    rebal = [e.date for e in events if e.type is EventType.REBALANCE]
    assert rebal == [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]


def test_never_rebalance_emits_no_rebalance_events() -> None:
    days = _trading_days()
    events = list(schedule(days, SchedulerConfig(rebalance_frequency="never")))
    assert not [e for e in events if e.type is EventType.REBALANCE]


def test_empty_calendar_yields_nothing() -> None:
    assert list(schedule([], SchedulerConfig())) == []
