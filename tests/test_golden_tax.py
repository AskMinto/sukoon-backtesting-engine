"""Golden tax test — closed-form expectations on a hand-built scenario.

Setup:
  * Buy 1,000 units of equity fund at NAV 100 on 2023-01-02 → cost 100,000.
  * Sell 600 units at NAV 150 on 2023-09-15 (held 256 days, < 365 → STCG).
      Gain = 600 * (150 - 100) = 30,000. STCG @ 15% = 4,500.
  * Sell remaining 400 units at NAV 200 on 2024-04-15 (held 469 days,
    ≥ 365 → LTCG; happens in FY24-25 — fresh exemption).
      Gain = 400 * (200 - 100) = 40,000. Under ₹1L exemption → tax 0.

Total expected tax over the lifetime: ₹4,500.
"""

from __future__ import annotations

from datetime import date

import pytest

from sukoon_bt.data.models import Fund
from sukoon_bt.tax.engine import TaxEngine
from sukoon_bt.tax.lots import TaxLotBook


@pytest.fixture
def equity_fund() -> Fund:
    return Fund(id="120503", name="Flexi", category="Flexi Cap", amc="X")


def test_golden_two_sales_stcg_then_ltcg(equity_fund: Fund) -> None:
    book = TaxLotBook()
    book.add("120503", units=1000.0, nav=100.0, purchase_date=date(2023, 1, 2))

    engine = TaxEngine()

    # Sale 1: 600 units @ 150 on 2023-09-15 → STCG.
    consumed_1 = book.consume_fifo(
        fund_id="120503", units=600.0, sale_nav=150.0, sale_date=date(2023, 9, 15)
    )
    comp_1 = engine.calculate_tax(consumed_1, equity_fund)
    assert comp_1.short_term_gain == pytest.approx(30_000.0)
    assert comp_1.long_term_gain == 0
    assert comp_1.short_term_tax == pytest.approx(4_500.0)
    assert comp_1.long_term_tax == 0

    # Sale 2: 400 units @ 200 on 2024-04-15 → LTCG, FY24-25 fresh ₹1L exemption.
    consumed_2 = book.consume_fifo(
        fund_id="120503", units=400.0, sale_nav=200.0, sale_date=date(2024, 4, 15)
    )
    comp_2 = engine.calculate_tax(consumed_2, equity_fund)
    assert comp_2.short_term_gain == 0
    assert comp_2.long_term_gain == pytest.approx(40_000.0)
    assert comp_2.short_term_tax == 0
    assert comp_2.long_term_tax == 0  # under exemption

    total_tax = comp_1.total_tax + comp_2.total_tax
    assert total_tax == pytest.approx(4_500.0)


def test_golden_replay(equity_fund: Fund) -> None:
    """Same scenario twice — must produce identical tax numbers."""

    def _run() -> tuple[float, float]:
        book = TaxLotBook()
        book.add("120503", 1000.0, 100.0, date(2023, 1, 2))
        engine = TaxEngine()
        c1 = book.consume_fifo("120503", 600.0, 150.0, date(2023, 9, 15))
        t1 = engine.calculate_tax(c1, equity_fund).total_tax
        c2 = book.consume_fifo("120503", 400.0, 200.0, date(2024, 4, 15))
        t2 = engine.calculate_tax(c2, equity_fund).total_tax
        return t1, t2

    a = _run()
    b = _run()
    assert a == b
