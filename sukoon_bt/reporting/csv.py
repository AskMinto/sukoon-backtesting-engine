"""CSV reporters for transactions and snapshots — spec §19."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from sukoon_bt.data.models import PortfolioSnapshot, Transaction


def write_transactions_csv(path: Path, transactions: list[Transaction]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not transactions:
        path.write_text("id,date,fund_id,transaction_type,units,nav,amount,fees,taxes\n")
        return
    df = pl.DataFrame(
        {
            "id": [t.id for t in transactions],
            "date": [t.date for t in transactions],
            "fund_id": [t.fund_id for t in transactions],
            "transaction_type": [t.transaction_type.value for t in transactions],
            "units": [t.units for t in transactions],
            "nav": [t.nav for t in transactions],
            "amount": [t.amount for t in transactions],
            "fees": [t.fees for t in transactions],
            "taxes": [t.taxes for t in transactions],
        }
    )
    df.write_csv(path)


def write_snapshots_csv(path: Path, snapshots: list[PortfolioSnapshot]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not snapshots:
        path.write_text("date,portfolio_value,cash,holdings_value,drawdown\n")
        return
    df = pl.DataFrame(
        {
            "date": [s.date for s in snapshots],
            "portfolio_value": [s.portfolio_value for s in snapshots],
            "cash": [s.cash for s in snapshots],
            "holdings_value": [s.holdings_value for s in snapshots],
            "drawdown": [s.drawdown for s in snapshots],
        }
    )
    df.write_csv(path)


__all__ = ["write_snapshots_csv", "write_transactions_csv"]
