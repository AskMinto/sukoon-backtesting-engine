"""Backtest engine — spec §3, §9.

The engine is *the* component that controls execution. Strategies emit
target weights via ``target_allocations(context)``; the engine compares
those to current holdings and books the resulting buys/sells.

Pipeline per trading day (spec §9):

    Update market state
        ↓
    Apply SIP/SWP (cashflow events)
        ↓
    Run strategy.on_day()
        ↓
    On REBALANCE event → strategy.target_allocations()
        ↓
    Engine reconciles target vs. current → books trades via Portfolio
        ↓
    Snapshot at MARKET_CLOSE
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from sukoon_bt.core.context import Context, MarketState
from sukoon_bt.core.events import CashflowEvent, EventType, RebalanceEvent
from sukoon_bt.core.scheduler import SchedulerConfig, schedule
from sukoon_bt.data.models import TransactionType
from sukoon_bt.execution.rebalance import RebalanceConstraints, plan_rebalance
from sukoon_bt.portfolio.portfolio import Portfolio
from sukoon_bt.strategies.base import Strategy

# Minimum trade amount to avoid noisy micro-rebalances; spec §11 mentions
# "minimum transaction size" as a rebalance constraint.
MIN_TRADE_AMOUNT = 1.0


@dataclass(slots=True)
class EngineConfig:
    """Run-level configuration for the engine."""

    initial_capital: float
    sip_amount: float = 0.0
    sip_day: int | None = None
    rebalance_frequency: str = "never"  # "never" | "monthly" | "quarterly" | "yearly"
    rebalance_min_trade: float = 100.0
    rebalance_tolerance: float = 0.0
    # If > 0, the engine fires an additional REBALANCE on any MARKET_OPEN
    # where the absolute drift of *any* held fund vs. its target weight
    # exceeds this fraction. spec §10 "threshold rebalancing".
    rebalance_threshold: float = 0.0

    def to_scheduler(self) -> SchedulerConfig:
        return SchedulerConfig(
            sip_amount=self.sip_amount,
            sip_day=self.sip_day,
            rebalance_frequency=self.rebalance_frequency,  # type: ignore[arg-type]
        )

    def to_constraints(self) -> RebalanceConstraints:
        return RebalanceConstraints(
            min_trade_amount=self.rebalance_min_trade,
            tolerance=self.rebalance_tolerance,
        )


@dataclass(slots=True)
class EngineResult:
    portfolio: Portfolio
    trading_days: list[date]


class Engine:
    """Deterministic event-driven engine."""

    def __init__(
        self,
        *,
        strategy: Strategy,
        nav_history: dict[str, pl.DataFrame],
        config: EngineConfig,
    ) -> None:
        if not nav_history:
            raise ValueError("nav_history must not be empty")
        self._strategy = strategy
        self._nav_history = nav_history
        self._config = config
        self._portfolio = Portfolio.with_initial_capital(config.initial_capital)
        # NAV lookup: per fund_id -> {date: nav}
        self._nav_index: dict[str, dict[date, float]] = {
            fid: {row["date"]: row["nav"] for row in df.iter_rows(named=True)}
            for fid, df in nav_history.items()
        }
        # Trading-day calendar = union of all observed NAV dates.
        all_dates: set[date] = set()
        for idx in self._nav_index.values():
            all_dates.update(idx.keys())
        self._trading_days = sorted(all_dates)
        # Forward-filled NAV cache for snapshots (when a fund didn't trade today).
        self._last_nav: dict[str, float] = {}

    @property
    def portfolio(self) -> Portfolio:
        return self._portfolio

    def run(self) -> EngineResult:
        if not self._trading_days:
            raise ValueError("no trading days in NAV history")

        # initialize() lets the strategy stash universe info, lookups, etc.
        first_day = self._trading_days[0]
        self._strategy.initialize(self._build_context(first_day))

        for event in schedule(self._trading_days, self._config.to_scheduler()):
            d = event.date
            self._refresh_navs(d)
            ctx = self._build_context(d)

            if event.type is EventType.MARKET_OPEN:
                self._strategy.on_day(event, ctx)
                if self._config.rebalance_threshold > 0 and self._drift_exceeds_threshold(ctx):
                    self._rebalance_to(self._strategy.target_allocations(ctx), d)

            elif event.type is EventType.SIP_TRIGGER and isinstance(event, CashflowEvent):
                self._apply_sip(event)

            elif event.type is EventType.REBALANCE and isinstance(event, RebalanceEvent):
                self._rebalance_to(self._strategy.target_allocations(ctx), d)

            elif event.type is EventType.MARKET_CLOSE:
                self._portfolio.snapshot(d, dict(self._last_nav))

        return EngineResult(portfolio=self._portfolio, trading_days=self._trading_days)

    # ----- internals ----------------------------------------------------

    def _drift_exceeds_threshold(self, ctx: Context) -> bool:
        targets = self._strategy.target_allocations(ctx)
        if not targets:
            return False
        navs = self._last_nav
        portfolio_value = self._portfolio.total_value(navs)
        if portfolio_value <= 0:
            return False
        for fid, weight in targets.items():
            current = self._portfolio.holdings.get(fid).market_value(navs.get(fid))
            current_weight = current / portfolio_value
            if abs(current_weight - weight) >= self._config.rebalance_threshold:
                return True
        return False

    def _refresh_navs(self, d: date) -> None:
        for fid, idx in self._nav_index.items():
            nav = idx.get(d)
            if nav is not None:
                self._last_nav[fid] = nav

    def _build_context(self, d: date) -> Context:
        return Context(
            market=MarketState(today=d, navs=dict(self._last_nav), nav_history=self._nav_history),
            portfolio=self._portfolio,
            initial_capital=self._config.initial_capital,
        )

    def _apply_sip(self, event: CashflowEvent) -> None:
        # SIP cash is allocated using the strategy's current target weights.
        ctx = self._build_context(event.date)
        targets = self._strategy.target_allocations(ctx)
        if not targets:
            self._portfolio.cash += event.amount  # park in cash if no targets yet
            return
        self._portfolio.cash += event.amount
        self._invest_amount(event.amount, targets, event.date, kind=TransactionType.SIP)

    def _invest_amount(
        self,
        amount: float,
        targets: dict[str, float],
        on: date,
        *,
        kind: TransactionType,
    ) -> None:
        for fund_id, weight in targets.items():
            slice_amount = amount * weight
            if slice_amount < MIN_TRADE_AMOUNT:
                continue
            nav = self._last_nav.get(fund_id)
            if nav is None:
                continue
            self._portfolio.buy(
                on=on, fund_id=fund_id, amount=slice_amount, nav=nav, kind=kind
            )

    def _rebalance_to(self, targets: dict[str, float], on: date) -> None:
        if not targets:
            return
        navs = dict(self._last_nav)
        instructions = plan_rebalance(
            holdings=self._portfolio.holdings,
            targets=targets,
            cash=self._portfolio.cash,
            navs=navs,
            constraints=self._config.to_constraints(),
        )
        for trade in instructions:
            if trade.action == "SELL":
                self._portfolio.sell(
                    on=on, fund_id=trade.fund_id, units=trade.units, nav=trade.nav
                )
            else:
                self._portfolio.buy(
                    on=on,
                    fund_id=trade.fund_id,
                    amount=trade.amount,
                    nav=trade.nav,
                    kind=TransactionType.BUY,
                )


__all__ = ["Engine", "EngineConfig", "EngineResult"]
