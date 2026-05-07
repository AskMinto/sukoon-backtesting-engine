"""Core pydantic v2 models — spec §6.

All cross-module data crosses pydantic boundaries; raw dicts stay inside a
single module. NAV/benchmark time series stay in polars DataFrames.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransactionType(StrEnum):
    """Transaction kinds the portfolio engine recognises (spec §10)."""

    BUY = "BUY"
    SELL = "SELL"
    SIP = "SIP"
    SWP = "SWP"
    STP = "STP"
    DIVIDEND = "DIVIDEND"


_PositiveFloat = Annotated[float, Field(gt=0)]
_NonNegativeFloat = Annotated[float, Field(ge=0)]


class Fund(BaseModel):
    """A mutual fund as exposed by the Sukoon data API (spec §6)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    name: str
    category: str
    amc: str
    benchmark: str | None = None
    expense_ratio: float | None = Field(default=None, ge=0, le=1)


class NAVPoint(BaseModel):
    """A single NAV observation."""

    model_config = ConfigDict(frozen=True)

    date: date
    nav: _PositiveFloat


class Transaction(BaseModel):
    """A booked portfolio transaction (immutable once persisted)."""

    model_config = ConfigDict(frozen=True)

    id: str
    date: date
    fund_id: str
    transaction_type: TransactionType
    units: float
    nav: _PositiveFloat
    amount: float
    fees: _NonNegativeFloat = 0.0
    taxes: _NonNegativeFloat = 0.0

    @field_validator("units")
    @classmethod
    def _units_nonzero(cls, v: float) -> float:
        if v == 0:
            raise ValueError("transaction units must be non-zero")
        return v


class TaxLot(BaseModel):
    """An open tax lot (spec §12) — created on every BUY/SIP fill."""

    model_config = ConfigDict(frozen=False)

    purchase_date: date
    units_remaining: _NonNegativeFloat
    purchase_nav: _PositiveFloat
    fund_id: str

    @property
    def cost_basis(self) -> float:
        return self.units_remaining * self.purchase_nav


class PortfolioSnapshot(BaseModel):
    """A daily snapshot of portfolio state (spec §6, §10)."""

    model_config = ConfigDict(frozen=True)

    date: date
    portfolio_value: float
    cash: float
    holdings_value: float
    drawdown: float = Field(le=0)


__all__ = [
    "Fund",
    "NAVPoint",
    "PortfolioSnapshot",
    "TaxLot",
    "Transaction",
    "TransactionType",
]
