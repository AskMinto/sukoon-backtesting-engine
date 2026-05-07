"""Portfolio engine — spec §10.

Owns cash, holdings, the transaction ledger, the tax-lot book, and the
chronological list of daily snapshots. Transactions are booked through
``buy()`` / ``sell()`` so that holdings, ledger, lots, and cash all
move in lockstep — strategies must not mutate any of these directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sukoon_bt.data.models import (
    PortfolioSnapshot,
    Transaction,
    TransactionType,
)
from sukoon_bt.portfolio.holdings import HoldingsBook
from sukoon_bt.portfolio.transactions import TransactionLedger, make_id
from sukoon_bt.tax.lots import ConsumedLot, TaxLotBook


@dataclass(slots=True)
class Portfolio:
    """The single mutable container the engine drives."""

    cash: float
    holdings: HoldingsBook = field(default_factory=HoldingsBook)
    ledger: TransactionLedger = field(default_factory=TransactionLedger)
    lots: TaxLotBook = field(default_factory=TaxLotBook)
    snapshots: list[PortfolioSnapshot] = field(default_factory=list)
    _peak_value: float = 0.0
    _tx_seq: int = 0

    @classmethod
    def with_initial_capital(cls, amount: float) -> Portfolio:
        if amount < 0:
            raise ValueError("initial capital must be non-negative")
        return cls(cash=amount, _peak_value=amount)

    def buy(
        self,
        *,
        on: date,
        fund_id: str,
        amount: float,
        nav: float,
        kind: TransactionType = TransactionType.BUY,
        fees: float = 0.0,
    ) -> Transaction:
        """Spend ``amount`` (gross of fees) of cash to acquire units of ``fund_id``."""
        if kind not in {TransactionType.BUY, TransactionType.SIP, TransactionType.STP}:
            raise ValueError(f"buy() called with non-buy kind {kind!r}")
        if amount <= 0:
            raise ValueError("buy amount must be positive")
        if nav <= 0:
            raise ValueError("buy nav must be positive")
        net = amount - fees
        if net <= 0:
            raise ValueError("fees consume the entire buy amount")
        if net > self.cash + 1e-9:
            raise ValueError(f"insufficient cash: need {net}, have {self.cash}")
        units = net / nav
        self.cash -= amount
        self.holdings.get(fund_id).add_units(units, nav)
        self.lots.add(fund_id, units, nav, on)
        tx = Transaction(
            id=self._next_id(),
            date=on,
            fund_id=fund_id,
            transaction_type=kind,
            units=units,
            nav=nav,
            amount=amount,
            fees=fees,
        )
        self.ledger.append(tx)
        return tx

    def sell(
        self,
        *,
        on: date,
        fund_id: str,
        units: float,
        nav: float,
        kind: TransactionType = TransactionType.SELL,
        fees: float = 0.0,
        taxes: float = 0.0,
    ) -> tuple[Transaction, list[ConsumedLot]]:
        """Sell ``units`` of ``fund_id``; returns the booked tx and FIFO slices."""
        if kind not in {TransactionType.SELL, TransactionType.SWP}:
            raise ValueError(f"sell() called with non-sell kind {kind!r}")
        if units <= 0:
            raise ValueError("sell units must be positive")
        if nav <= 0:
            raise ValueError("sell nav must be positive")
        consumed = self.lots.consume_fifo(fund_id, units, nav, on)
        self.holdings.get(fund_id).remove_units(units, nav)
        proceeds = units * nav - fees - taxes
        self.cash += proceeds
        tx = Transaction(
            id=self._next_id(),
            date=on,
            fund_id=fund_id,
            transaction_type=kind,
            units=-units,
            nav=nav,
            amount=units * nav,
            fees=fees,
            taxes=taxes,
        )
        self.ledger.append(tx)
        return tx, consumed

    def snapshot(self, on: date, navs: dict[str, float]) -> PortfolioSnapshot:
        """Mark-to-market and append a daily snapshot."""
        self.holdings.update_navs(navs)
        holdings_value = self.holdings.market_value(navs)
        total = self.cash + holdings_value
        self._peak_value = max(self._peak_value, total)
        drawdown = (total / self._peak_value - 1.0) if self._peak_value > 0 else 0.0
        snap = PortfolioSnapshot(
            date=on,
            portfolio_value=total,
            cash=self.cash,
            holdings_value=holdings_value,
            drawdown=min(drawdown, 0.0),
        )
        self.snapshots.append(snap)
        return snap

    def total_value(self, navs: dict[str, float] | None = None) -> float:
        navs = navs or {}
        return self.cash + self.holdings.market_value(navs)

    def _next_id(self) -> str:
        self._tx_seq += 1
        return make_id(self._tx_seq)


__all__ = ["Portfolio"]
