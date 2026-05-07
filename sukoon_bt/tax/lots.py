"""Tax-lot tracking — spec §12.

Tax lots are FIFO by default (matches Indian MF practice for capital
gains). Every BUY/SIP creates a new lot; every SELL/SWP consumes lots
oldest-first and emits "consumed slices" the tax engine can use to
calculate STCG/LTCG.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date

from sukoon_bt.data.models import TaxLot


@dataclass(frozen=True, slots=True)
class ConsumedLot:
    """A slice of an existing TaxLot consumed by a sell."""

    purchase_date: date
    units_consumed: float
    purchase_nav: float
    sale_nav: float
    sale_date: date

    @property
    def cost_basis(self) -> float:
        return self.units_consumed * self.purchase_nav

    @property
    def proceeds(self) -> float:
        return self.units_consumed * self.sale_nav

    @property
    def realized_pnl(self) -> float:
        return self.proceeds - self.cost_basis

    @property
    def holding_period_days(self) -> int:
        return (self.sale_date - self.purchase_date).days


class TaxLotBook:
    """FIFO queue of open TaxLots, keyed by fund_id."""

    def __init__(self) -> None:
        self._lots: dict[str, deque[TaxLot]] = defaultdict(deque)

    def add(self, fund_id: str, units: float, nav: float, purchase_date: date) -> TaxLot:
        lot = TaxLot(
            fund_id=fund_id,
            units_remaining=units,
            purchase_nav=nav,
            purchase_date=purchase_date,
        )
        self._lots[fund_id].append(lot)
        return lot

    def consume_fifo(
        self,
        fund_id: str,
        units: float,
        sale_nav: float,
        sale_date: date,
    ) -> list[ConsumedLot]:
        """Consume ``units`` from the oldest open lots; return the slices removed."""
        if units <= 0:
            raise ValueError("consume_fifo requires positive units")
        consumed: list[ConsumedLot] = []
        remaining = units
        queue = self._lots[fund_id]
        while remaining > 1e-12 and queue:
            lot = queue[0]
            take = min(remaining, lot.units_remaining)
            consumed.append(
                ConsumedLot(
                    purchase_date=lot.purchase_date,
                    units_consumed=take,
                    purchase_nav=lot.purchase_nav,
                    sale_nav=sale_nav,
                    sale_date=sale_date,
                )
            )
            lot.units_remaining -= take
            remaining -= take
            if lot.units_remaining <= 1e-12:
                queue.popleft()
        if remaining > 1e-9:
            raise ValueError(
                f"insufficient open lots for {fund_id}: {units} requested, "
                f"only {units - remaining} consumed"
            )
        return consumed

    def open_lots(self, fund_id: str) -> list[TaxLot]:
        return list(self._lots.get(fund_id, ()))

    def total_open_units(self, fund_id: str) -> float:
        return sum(l.units_remaining for l in self._lots.get(fund_id, ()))


__all__ = ["ConsumedLot", "TaxLotBook"]
