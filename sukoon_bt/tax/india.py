"""Indian capital-gains tax rules — spec §13.

Equity funds:
  STCG (holding period < 365 days): 15%
  LTCG (≥ 365 days): 10% with ₹1 lakh exemption *per fiscal year*

Debt funds:
  Pre-2023 (purchase before 2023-04-01):
    STCG (< 1095 days): slab rate (caller-provided)
    LTCG (≥ 1095 days): 20% with indexation (we apply 20% flat unless
      caller provides an indexation factor)
  Post-2023 (purchase on/after 2023-04-01):
    All gains taxed at slab rate; long-term concession removed.

A fund's category drives which rule set applies. spec §13 says debt
logic must be configurable, so the caller passes in slab_rate and the
optional indexation_factor. Equity rules are constants because they
haven't changed in the relevant window for backtesting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final

from sukoon_bt.tax.lots import ConsumedLot

EQUITY_STCG_RATE: Final[float] = 0.15
EQUITY_LTCG_RATE: Final[float] = 0.10
EQUITY_LTCG_EXEMPTION_PER_FY: Final[float] = 100_000.0
EQUITY_LTCG_HOLDING_DAYS: Final[int] = 365

DEBT_LTCG_HOLDING_DAYS_PRE_2023: Final[int] = 1095  # 3 years
DEBT_LTCG_RATE_PRE_2023: Final[float] = 0.20
DEBT_RULE_CHANGE_DATE: Final[date] = date(2023, 4, 1)


class FundTaxClass(StrEnum):
    """Tax classification of the underlying fund."""

    EQUITY = "EQUITY"
    DEBT = "DEBT"


def classify(category: str) -> FundTaxClass:
    """Map a SEBI category string onto the relevant tax class.

    Treats anything explicitly debt-like as DEBT; everything else
    (equity, hybrid-aggressive, ELSS, sectoral, ETF/index) defaults
    to EQUITY for capital-gains purposes. Hybrid-conservative is a
    grey area in the real world; the conservative default here is
    EQUITY because most long-term investors use those funds in an
    equity-oriented basket. Plugins / future configuration can
    override this.
    """
    cat = category.lower()
    debt_markers = (
        "debt",
        "bond",
        "gilt",
        "liquid",
        "ultra short",
        "money market",
        "credit risk",
        "banking & psu",
        "floating rate",
        "duration",
        "overnight",
    )
    return FundTaxClass.DEBT if any(m in cat for m in debt_markers) else FundTaxClass.EQUITY


@dataclass(frozen=True, slots=True)
class TaxComputation:
    """Per-sale tax breakdown."""

    short_term_gain: float
    long_term_gain: float
    short_term_tax: float
    long_term_tax: float

    @property
    def total_tax(self) -> float:
        return self.short_term_tax + self.long_term_tax

    @property
    def total_gain(self) -> float:
        return self.short_term_gain + self.long_term_gain


@dataclass(slots=True)
class FYExemptionTracker:
    """Tracks the cumulative LTCG already used against the equity exemption.

    Indian fiscal year runs Apr 1 → Mar 31. Reset across fiscal years
    happens automatically via the keying.
    """

    used: dict[int, float]  # fiscal_year_start_year -> ₹ used

    def __init__(self) -> None:
        self.used = {}

    @staticmethod
    def fiscal_year(d: date) -> int:
        return d.year if d.month >= 4 else d.year - 1

    def remaining(self, on: date) -> float:
        fy = self.fiscal_year(on)
        return max(0.0, EQUITY_LTCG_EXEMPTION_PER_FY - self.used.get(fy, 0.0))

    def consume(self, on: date, amount: float) -> float:
        """Apply ``amount`` against the FY exemption; return the actually-consumed slice."""
        fy = self.fiscal_year(on)
        rem = self.remaining(on)
        used = min(rem, max(amount, 0.0))
        self.used[fy] = self.used.get(fy, 0.0) + used
        return used


def compute_tax(
    consumed: list[ConsumedLot],
    *,
    tax_class: FundTaxClass,
    exemption: FYExemptionTracker | None = None,
    debt_slab_rate: float = 0.30,
    debt_indexation_factor: float = 1.0,
) -> TaxComputation:
    """Compute STCG + LTCG tax on a sale that consumed the given lots.

    For equity, the LTCG bucket is offset by any unused FY-level
    exemption (call ``exemption.consume(...)`` to mark usage so the
    next call in the same FY sees the reduced cap).

    For debt, ``debt_indexation_factor`` lets callers reduce LTCG
    cost basis (factor > 1 increases cost basis, lowering gains).
    Pre-2023 debt LTCG taxes at 20% on the indexed gain; post-2023
    rules (purchase on/after 2023-04-01) tax all gains at slab rate.
    """
    if tax_class is FundTaxClass.EQUITY:
        return _equity_tax(consumed, exemption)
    return _debt_tax(
        consumed,
        slab_rate=debt_slab_rate,
        indexation_factor=debt_indexation_factor,
    )


def _equity_tax(
    consumed: list[ConsumedLot],
    exemption: FYExemptionTracker | None,
) -> TaxComputation:
    short_gain = 0.0
    long_gain = 0.0
    sale_dates: list[date] = []
    for lot in consumed:
        if lot.holding_period_days >= EQUITY_LTCG_HOLDING_DAYS:
            long_gain += lot.realized_pnl
        else:
            short_gain += lot.realized_pnl
        sale_dates.append(lot.sale_date)

    short_tax = max(short_gain, 0.0) * EQUITY_STCG_RATE
    taxable_ltcg = max(long_gain, 0.0)
    if exemption is not None and sale_dates:
        used = exemption.consume(max(sale_dates), taxable_ltcg)
        taxable_ltcg -= used
    long_tax = taxable_ltcg * EQUITY_LTCG_RATE
    return TaxComputation(
        short_term_gain=short_gain,
        long_term_gain=long_gain,
        short_term_tax=short_tax,
        long_term_tax=long_tax,
    )


def _debt_tax(
    consumed: list[ConsumedLot],
    *,
    slab_rate: float,
    indexation_factor: float,
) -> TaxComputation:
    short_gain = 0.0
    long_gain = 0.0
    long_tax = 0.0
    short_tax = 0.0
    for lot in consumed:
        post_2023 = lot.purchase_date >= DEBT_RULE_CHANGE_DATE
        if post_2023:
            # All gains slab-taxed irrespective of holding period.
            short_gain += lot.realized_pnl
            short_tax += max(lot.realized_pnl, 0.0) * slab_rate
            continue
        if lot.holding_period_days >= DEBT_LTCG_HOLDING_DAYS_PRE_2023:
            indexed_cost = lot.cost_basis * indexation_factor
            indexed_gain = lot.proceeds - indexed_cost
            long_gain += indexed_gain
            long_tax += max(indexed_gain, 0.0) * DEBT_LTCG_RATE_PRE_2023
        else:
            short_gain += lot.realized_pnl
            short_tax += max(lot.realized_pnl, 0.0) * slab_rate
    return TaxComputation(
        short_term_gain=short_gain,
        long_term_gain=long_gain,
        short_term_tax=short_tax,
        long_term_tax=long_tax,
    )


__all__ = [
    "DEBT_LTCG_HOLDING_DAYS_PRE_2023",
    "DEBT_LTCG_RATE_PRE_2023",
    "DEBT_RULE_CHANGE_DATE",
    "EQUITY_LTCG_EXEMPTION_PER_FY",
    "EQUITY_LTCG_HOLDING_DAYS",
    "EQUITY_LTCG_RATE",
    "EQUITY_STCG_RATE",
    "FYExemptionTracker",
    "FundTaxClass",
    "TaxComputation",
    "classify",
    "compute_tax",
]
