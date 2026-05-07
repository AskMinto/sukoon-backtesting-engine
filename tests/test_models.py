"""Validation invariants for core data models — spec §6."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from sukoon_bt.data.models import (
    Fund,
    NAVPoint,
    PortfolioSnapshot,
    TaxLot,
    Transaction,
    TransactionType,
)


class TestFund:
    def test_minimal_fund_is_frozen(self) -> None:
        f = Fund(id="120503", name="Parag Parikh Flexi Cap", category="Flexi Cap", amc="PPFAS")
        with pytest.raises(ValidationError):
            f.id = "999"  # type: ignore[misc]

    @pytest.mark.parametrize("ratio", [-0.01, 1.5])
    def test_expense_ratio_bounded(self, ratio: float) -> None:
        with pytest.raises(ValidationError):
            Fund(
                id="x",
                name="x",
                category="x",
                amc="x",
                expense_ratio=ratio,
            )


class TestNAVPoint:
    def test_positive_nav_required(self) -> None:
        with pytest.raises(ValidationError):
            NAVPoint(date=date(2024, 1, 1), nav=0.0)
        with pytest.raises(ValidationError):
            NAVPoint(date=date(2024, 1, 1), nav=-1.0)

    def test_valid(self) -> None:
        p = NAVPoint(date=date(2024, 1, 1), nav=100.5)
        assert p.nav == 100.5


class TestTransaction:
    def _kwargs(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "id": "tx-1",
            "date": date(2024, 1, 1),
            "fund_id": "120503",
            "transaction_type": TransactionType.BUY,
            "units": 10.0,
            "nav": 50.0,
            "amount": 500.0,
        }
        base.update(overrides)
        return base

    def test_zero_units_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Transaction(**self._kwargs(units=0.0))

    def test_negative_fees_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Transaction(**self._kwargs(fees=-1.0))

    def test_sell_with_negative_units_allowed(self) -> None:
        # Spec §10 allows SELL bookings to use negative units to signal direction.
        tx = Transaction(**self._kwargs(transaction_type=TransactionType.SELL, units=-5.0))
        assert tx.transaction_type is TransactionType.SELL
        assert tx.units == -5.0

    def test_transaction_type_is_strenum(self) -> None:
        tx = Transaction(**self._kwargs(transaction_type="BUY"))
        assert tx.transaction_type is TransactionType.BUY


class TestTaxLot:
    def test_cost_basis(self) -> None:
        lot = TaxLot(
            purchase_date=date(2023, 1, 1),
            units_remaining=12.5,
            purchase_nav=80.0,
            fund_id="120503",
        )
        assert lot.cost_basis == pytest.approx(1000.0)

    def test_negative_units_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaxLot(
                purchase_date=date(2023, 1, 1),
                units_remaining=-1.0,
                purchase_nav=80.0,
                fund_id="120503",
            )


class TestSnapshot:
    def test_drawdown_must_be_non_positive(self) -> None:
        # Drawdown is defined as a non-positive number (0 = at peak, negative = below peak).
        with pytest.raises(ValidationError):
            PortfolioSnapshot(
                date=date(2024, 1, 1),
                portfolio_value=100.0,
                cash=10.0,
                holdings_value=90.0,
                drawdown=0.05,
            )

    def test_at_peak(self) -> None:
        snap = PortfolioSnapshot(
            date=date(2024, 1, 1),
            portfolio_value=100.0,
            cash=10.0,
            holdings_value=90.0,
            drawdown=0.0,
        )
        assert snap.drawdown == 0.0
