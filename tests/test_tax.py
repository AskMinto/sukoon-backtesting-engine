"""Tax engine tests — spec §13."""

from __future__ import annotations

from datetime import date

import pytest

from sukoon_bt.data.models import Fund
from sukoon_bt.tax.engine import TaxEngine
from sukoon_bt.tax.india import (
    DEBT_LTCG_RATE_PRE_2023,
    EQUITY_LTCG_EXEMPTION_PER_FY,
    EQUITY_LTCG_RATE,
    EQUITY_STCG_RATE,
    FundTaxClass,
    FYExemptionTracker,
    classify,
)
from sukoon_bt.tax.lots import ConsumedLot


def _lot(*, purchase: date, sale: date, units: float, buy_nav: float, sell_nav: float) -> ConsumedLot:
    return ConsumedLot(
        purchase_date=purchase,
        units_consumed=units,
        purchase_nav=buy_nav,
        sale_nav=sell_nav,
        sale_date=sale,
    )


@pytest.fixture
def equity_fund() -> Fund:
    return Fund(id="120503", name="PPFC", category="Flexi Cap", amc="PPFAS")


@pytest.fixture
def debt_fund() -> Fund:
    return Fund(id="999999", name="HDFC Liquid", category="Liquid", amc="HDFC")


class TestClassifier:
    @pytest.mark.parametrize(
        "category",
        ["Flexi Cap", "Large Cap", "Small Cap", "ELSS", "Multi Cap", "Hybrid"],
    )
    def test_equity_categories(self, category: str) -> None:
        assert classify(category) is FundTaxClass.EQUITY

    @pytest.mark.parametrize(
        "category",
        ["Liquid", "Overnight", "Banking & PSU Debt", "Gilt", "Corporate Bond",
         "Money Market", "Credit Risk", "Floating Rate", "Short Duration"],
    )
    def test_debt_categories(self, category: str) -> None:
        assert classify(category) is FundTaxClass.DEBT


class TestEquityTax:
    def test_stcg_at_15_percent(self, equity_fund: Fund) -> None:
        engine = TaxEngine()
        # Bought Jan, sold Jun (< 365 days) → STCG.
        consumed = [_lot(purchase=date(2024, 1, 1), sale=date(2024, 6, 1),
                         units=100, buy_nav=100, sell_nav=110)]
        comp = engine.calculate_tax(consumed, equity_fund)
        assert comp.short_term_gain == pytest.approx(1000.0)  # 100 units * (110-100)
        assert comp.short_term_tax == pytest.approx(1000.0 * EQUITY_STCG_RATE)
        assert comp.long_term_gain == 0
        assert comp.long_term_tax == 0

    def test_ltcg_offsets_against_exemption(self, equity_fund: Fund) -> None:
        engine = TaxEngine()
        # Sale 1 in FY24-25: 80,000 LTCG → fully exempted (under ₹1L).
        s1 = [_lot(purchase=date(2023, 5, 1), sale=date(2024, 6, 1),
                   units=100, buy_nav=100, sell_nav=180)]
        c1 = engine.calculate_tax(s1, equity_fund)
        assert c1.long_term_gain == pytest.approx(8000.0)
        assert c1.long_term_tax == 0  # under exemption

        # Sale 2 same FY: another ₹120,000 LTCG → 100k exempted gone, 28k taxable.
        s2 = [_lot(purchase=date(2023, 5, 1), sale=date(2024, 8, 1),
                   units=100, buy_nav=100, sell_nav=1300)]
        c2 = engine.calculate_tax(s2, equity_fund)
        # Gain: 100 * (1300-100) = 120,000. Used so far: 8,000. Remaining
        # exemption: 92,000. Taxable: 120,000 - 92,000 = 28,000 @ 10%.
        assert c2.long_term_gain == pytest.approx(120_000.0)
        assert c2.long_term_tax == pytest.approx(28_000.0 * EQUITY_LTCG_RATE)

    def test_ltcg_resets_across_fiscal_years(self, equity_fund: Fund) -> None:
        engine = TaxEngine()
        # FY1: use up the exemption.
        big = [_lot(purchase=date(2022, 1, 1), sale=date(2023, 6, 1),
                    units=100, buy_nav=100, sell_nav=2000)]
        c1 = engine.calculate_tax(big, equity_fund)
        # 100 * 1900 = 190,000 gain → 100k exempt → 90k @ 10% = 9,000
        assert c1.long_term_tax == pytest.approx(9_000.0)
        # FY2 (post Apr 1, 2024): exemption resets.
        big2 = [_lot(purchase=date(2023, 1, 1), sale=date(2024, 5, 1),
                     units=100, buy_nav=100, sell_nav=2000)]
        c2 = engine.calculate_tax(big2, equity_fund)
        assert c2.long_term_tax == pytest.approx(9_000.0)

    def test_loss_does_not_create_negative_tax(self, equity_fund: Fund) -> None:
        engine = TaxEngine()
        consumed = [_lot(purchase=date(2024, 1, 1), sale=date(2024, 6, 1),
                         units=100, buy_nav=100, sell_nav=80)]
        comp = engine.calculate_tax(consumed, equity_fund)
        assert comp.short_term_gain == pytest.approx(-2000.0)
        assert comp.short_term_tax == 0  # losses don't create tax owed


class TestDebtTax:
    def test_pre_2023_long_term_at_20_percent(self, debt_fund: Fund) -> None:
        engine = TaxEngine(debt_slab_rate=0.30)
        # Purchase 2020-01-01 (pre-2023), held > 3 years.
        consumed = [_lot(purchase=date(2020, 1, 1), sale=date(2024, 1, 2),
                         units=100, buy_nav=100, sell_nav=150)]
        comp = engine.calculate_tax(consumed, debt_fund)
        # No indexation (default factor 1.0). Gain 5,000 @ 20%.
        assert comp.long_term_gain == pytest.approx(5_000.0)
        assert comp.long_term_tax == pytest.approx(5_000.0 * DEBT_LTCG_RATE_PRE_2023)

    def test_indexation_lowers_taxable_gain(self, debt_fund: Fund) -> None:
        engine = TaxEngine(debt_indexation_factor=1.20)
        # Same lot but 1.20x indexation: cost rises 100→120, gain shrinks.
        consumed = [_lot(purchase=date(2020, 1, 1), sale=date(2024, 1, 2),
                         units=100, buy_nav=100, sell_nav=150)]
        comp = engine.calculate_tax(consumed, debt_fund)
        # Indexed cost: 100 * 1.20 = 120. Gain 100 * (150-120) = 3,000 @ 20%.
        assert comp.long_term_tax == pytest.approx(3_000.0 * DEBT_LTCG_RATE_PRE_2023)

    def test_post_2023_all_at_slab(self, debt_fund: Fund) -> None:
        engine = TaxEngine(debt_slab_rate=0.30)
        # Purchase 2023-04-15 (post change date), even held > 3 years → slab.
        consumed = [_lot(purchase=date(2023, 4, 15), sale=date(2027, 5, 1),
                         units=100, buy_nav=100, sell_nav=150)]
        comp = engine.calculate_tax(consumed, debt_fund)
        # All gain treated short-term-bucket; tax = 5,000 * 0.30.
        assert comp.short_term_tax == pytest.approx(5_000.0 * 0.30)
        assert comp.long_term_tax == 0


class TestExemptionTracker:
    def test_fiscal_year_calc(self) -> None:
        assert FYExemptionTracker.fiscal_year(date(2024, 3, 31)) == 2023
        assert FYExemptionTracker.fiscal_year(date(2024, 4, 1)) == 2024
        assert FYExemptionTracker.fiscal_year(date(2024, 12, 31)) == 2024

    def test_consume_caps_at_remaining(self) -> None:
        t = FYExemptionTracker()
        used = t.consume(date(2024, 6, 1), 70_000.0)
        assert used == pytest.approx(70_000.0)
        assert t.remaining(date(2024, 6, 1)) == pytest.approx(EQUITY_LTCG_EXEMPTION_PER_FY - 70_000.0)
        # Try to use more than remaining.
        used2 = t.consume(date(2024, 7, 1), 50_000.0)
        assert used2 == pytest.approx(30_000.0)
        assert t.remaining(date(2024, 7, 1)) == 0
