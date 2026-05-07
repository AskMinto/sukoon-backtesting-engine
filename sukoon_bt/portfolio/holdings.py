"""Per-fund holdings tracker — spec §10."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Holding:
    """Aggregate position in a single fund.

    Mutable: BUY/SIP increase units and update the cost basis (running
    average); SELL/SWP decrease units and add to realised PnL.
    """

    fund_id: str
    units: float = 0.0
    cost_basis: float = 0.0  # total purchase amount for currently-held units
    realized_pnl: float = 0.0
    last_nav: float = 0.0

    @property
    def avg_nav(self) -> float:
        return self.cost_basis / self.units if self.units > 0 else 0.0

    def market_value(self, nav: float | None = None) -> float:
        return self.units * (nav if nav is not None else self.last_nav)

    def unrealized_pnl(self, nav: float | None = None) -> float:
        return self.market_value(nav) - self.cost_basis

    def add_units(self, units: float, nav: float) -> None:
        if units <= 0:
            raise ValueError("add_units requires positive units")
        self.cost_basis += units * nav
        self.units += units
        self.last_nav = nav

    def remove_units(self, units: float, nav: float) -> float:
        """Sell ``units`` at ``nav``; returns realised PnL on the sold slice."""
        if units <= 0:
            raise ValueError("remove_units requires positive units")
        if units > self.units + 1e-9:
            raise ValueError(
                f"cannot sell {units} units of {self.fund_id}; only {self.units} held"
            )
        avg = self.avg_nav
        cost_removed = units * avg
        proceeds = units * nav
        realized = proceeds - cost_removed
        self.cost_basis -= cost_removed
        self.units -= units
        if self.units < 1e-12:
            # Clamp residual rounding noise so subsequent comparisons are clean.
            self.units = 0.0
            self.cost_basis = 0.0
        self.realized_pnl += realized
        self.last_nav = nav
        return realized


@dataclass(slots=True)
class HoldingsBook:
    """Collection of Holding rows, keyed by fund_id."""

    rows: dict[str, Holding] = field(default_factory=dict)

    def get(self, fund_id: str) -> Holding:
        return self.rows.setdefault(fund_id, Holding(fund_id=fund_id))

    def units(self, fund_id: str) -> float:
        return self.rows[fund_id].units if fund_id in self.rows else 0.0

    def market_value(self, navs: dict[str, float]) -> float:
        return sum(h.market_value(navs.get(h.fund_id)) for h in self.rows.values())

    def update_navs(self, navs: dict[str, float]) -> None:
        for fund_id, nav in navs.items():
            if fund_id in self.rows:
                self.rows[fund_id].last_nav = nav

    def __iter__(self):
        return iter(self.rows.values())


__all__ = ["Holding", "HoldingsBook"]
