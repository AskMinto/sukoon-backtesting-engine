"""Portfolio engine tests — spec §10."""

from __future__ import annotations

from datetime import date

import pytest

from sukoon_bt.data.models import TransactionType
from sukoon_bt.portfolio.portfolio import Portfolio
from sukoon_bt.tax.lots import TaxLotBook


class TestPortfolioBookings:
    def test_buy_decreases_cash_and_creates_holding_and_lot(self) -> None:
        p = Portfolio.with_initial_capital(100_000.0)
        tx = p.buy(on=date(2024, 1, 1), fund_id="120503", amount=10_000.0, nav=50.0)

        assert p.cash == pytest.approx(90_000.0)
        h = p.holdings.get("120503")
        assert h.units == pytest.approx(200.0)
        assert h.cost_basis == pytest.approx(10_000.0)
        assert h.avg_nav == pytest.approx(50.0)
        assert tx.transaction_type is TransactionType.BUY
        assert tx.units == pytest.approx(200.0)
        assert len(p.lots.open_lots("120503")) == 1
        assert p.lots.total_open_units("120503") == pytest.approx(200.0)
        assert len(p.ledger) == 1

    def test_sip_kind_is_recorded_and_creates_lot(self) -> None:
        p = Portfolio.with_initial_capital(100_000.0)
        tx = p.buy(
            on=date(2024, 1, 1),
            fund_id="120503",
            amount=5_000.0,
            nav=50.0,
            kind=TransactionType.SIP,
        )
        assert tx.transaction_type is TransactionType.SIP
        assert len(p.lots.open_lots("120503")) == 1

    def test_buy_rejects_zero_or_negative_amount(self) -> None:
        p = Portfolio.with_initial_capital(100.0)
        with pytest.raises(ValueError):
            p.buy(on=date(2024, 1, 1), fund_id="x", amount=0.0, nav=10.0)

    def test_buy_rejects_when_insufficient_cash(self) -> None:
        p = Portfolio.with_initial_capital(100.0)
        with pytest.raises(ValueError):
            p.buy(on=date(2024, 1, 1), fund_id="x", amount=200.0, nav=10.0)

    def test_sell_consumes_fifo_lots_and_credits_cash(self) -> None:
        p = Portfolio.with_initial_capital(100_000.0)
        p.buy(on=date(2023, 1, 1), fund_id="120503", amount=5_000.0, nav=50.0)  # 100 units
        p.buy(on=date(2024, 1, 1), fund_id="120503", amount=6_000.0, nav=60.0)  # 100 units

        # Sell 150 @ 70 → consumes all 100 of lot1 and 50 of lot2.
        tx, consumed = p.sell(
            on=date(2024, 6, 1), fund_id="120503", units=150.0, nav=70.0
        )

        assert tx.transaction_type is TransactionType.SELL
        assert tx.units == pytest.approx(-150.0)
        assert len(consumed) == 2
        assert consumed[0].purchase_date == date(2023, 1, 1)
        assert consumed[0].units_consumed == pytest.approx(100.0)
        assert consumed[1].purchase_date == date(2024, 1, 1)
        assert consumed[1].units_consumed == pytest.approx(50.0)
        # Cash: 100k - 5k - 6k + 150*70 = 99,500
        assert p.cash == pytest.approx(99_500.0)
        # Remaining 50 units in lot2:
        assert p.lots.total_open_units("120503") == pytest.approx(50.0)

    def test_sell_rejects_oversell(self) -> None:
        p = Portfolio.with_initial_capital(100_000.0)
        p.buy(on=date(2023, 1, 1), fund_id="120503", amount=5_000.0, nav=50.0)
        with pytest.raises(ValueError):
            p.sell(on=date(2024, 1, 1), fund_id="120503", units=200.0, nav=70.0)


class TestSnapshot:
    def test_snapshot_marks_to_market_and_tracks_drawdown(self) -> None:
        p = Portfolio.with_initial_capital(10_000.0)
        p.buy(on=date(2024, 1, 1), fund_id="x", amount=10_000.0, nav=100.0)  # 100 units

        s1 = p.snapshot(date(2024, 1, 1), {"x": 100.0})
        assert s1.portfolio_value == pytest.approx(10_000.0)
        assert s1.drawdown == 0.0

        s2 = p.snapshot(date(2024, 1, 2), {"x": 110.0})
        assert s2.portfolio_value == pytest.approx(11_000.0)
        assert s2.drawdown == 0.0  # New peak; no DD.

        s3 = p.snapshot(date(2024, 1, 3), {"x": 99.0})
        assert s3.portfolio_value == pytest.approx(9_900.0)
        assert s3.drawdown == pytest.approx(9_900.0 / 11_000.0 - 1.0)
        assert s3.drawdown < 0


class TestTaxLotBookDirect:
    def test_consume_more_than_held_raises(self) -> None:
        book = TaxLotBook()
        book.add("x", 10.0, 100.0, date(2024, 1, 1))
        with pytest.raises(ValueError):
            book.consume_fifo("x", 20.0, 110.0, date(2024, 6, 1))

    def test_consumed_lot_pnl(self) -> None:
        book = TaxLotBook()
        book.add("x", 10.0, 100.0, date(2024, 1, 1))
        consumed = book.consume_fifo("x", 4.0, 130.0, date(2024, 6, 1))
        slice_ = consumed[0]
        assert slice_.cost_basis == pytest.approx(400.0)
        assert slice_.proceeds == pytest.approx(520.0)
        assert slice_.realized_pnl == pytest.approx(120.0)
        assert slice_.holding_period_days == 152
