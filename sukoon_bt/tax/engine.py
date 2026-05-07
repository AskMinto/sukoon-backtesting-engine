"""Tax engine — spec §12, §13.

Composable wrapper around the per-jurisdiction rules in
``sukoon_bt.tax.india`` (and future jurisdictions). The engine is the
ONLY place capital-gains tax gets computed; strategies must never embed
tax logic (spec §28 anti-pattern).
"""

from __future__ import annotations

from collections.abc import Callable

from sukoon_bt.data.models import Fund
from sukoon_bt.tax.india import (
    FYExemptionTracker,
    FundTaxClass,
    TaxComputation,
    classify,
    compute_tax,
)
from sukoon_bt.tax.lots import ConsumedLot

# Type for a per-fund tax classifier override; defaults to the SEBI-
# category heuristic in india.classify(), but plugins can pass a
# callable that consults a static map or a remote service.
TaxClassifier = Callable[[Fund], FundTaxClass]


class TaxEngine:
    """Stateful tax engine (holds the FY exemption tracker)."""

    def __init__(
        self,
        *,
        classifier: TaxClassifier | None = None,
        debt_slab_rate: float = 0.30,
        debt_indexation_factor: float = 1.0,
    ) -> None:
        self._classifier = classifier or _default_classifier
        self._debt_slab_rate = debt_slab_rate
        self._debt_indexation = debt_indexation_factor
        self._equity_exemption = FYExemptionTracker()

    def calculate_tax(self, consumed: list[ConsumedLot], fund: Fund) -> TaxComputation:
        """Compute the tax due on a single sale of ``fund``."""
        if not consumed:
            return TaxComputation(
                short_term_gain=0.0,
                long_term_gain=0.0,
                short_term_tax=0.0,
                long_term_tax=0.0,
            )
        cls = self._classifier(fund)
        return compute_tax(
            consumed,
            tax_class=cls,
            exemption=self._equity_exemption if cls is FundTaxClass.EQUITY else None,
            debt_slab_rate=self._debt_slab_rate,
            debt_indexation_factor=self._debt_indexation,
        )


def _default_classifier(fund: Fund) -> FundTaxClass:
    return classify(fund.category)


__all__ = ["TaxClassifier", "TaxEngine"]
