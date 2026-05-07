"""Transaction ledger and id factory."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from sukoon_bt.data.models import Transaction


@dataclass(slots=True)
class TransactionLedger:
    """Append-only list of booked Transactions."""

    rows: list[Transaction] = field(default_factory=list)

    def append(self, tx: Transaction) -> None:
        self.rows.append(tx)

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[Transaction]:
        return iter(self.rows)


def make_id(seq: int) -> str:
    return f"tx-{seq:08d}"


__all__ = ["TransactionLedger", "make_id"]
