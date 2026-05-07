"""Analytics + reporting tests."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import orjson
import pytest

from sukoon_bt.analytics.drawdown import max_drawdown
from sukoon_bt.analytics.metrics import compute_performance
from sukoon_bt.data.models import PortfolioSnapshot, Transaction, TransactionType
from sukoon_bt.reporting.csv import write_snapshots_csv, write_transactions_csv
from sukoon_bt.reporting.json import write_run_json


def _series(start: date, days: int, daily_return: float, initial: float = 100_000.0) -> list[PortfolioSnapshot]:
    snaps: list[PortfolioSnapshot] = []
    value = initial
    peak = initial
    for i in range(days):
        d = start + timedelta(days=i)
        value *= 1 + daily_return
        peak = max(peak, value)
        dd = value / peak - 1.0
        snaps.append(
            PortfolioSnapshot(
                date=d,
                portfolio_value=value,
                cash=0.0,
                holdings_value=value,
                drawdown=min(dd, 0.0),
            )
        )
    return snaps


class TestMetrics:
    def test_cagr_on_one_year_constant_growth(self) -> None:
        # ~365 days at +0.05% daily ≈ ~20% absolute return.
        snaps = _series(date(2024, 1, 1), 366, daily_return=0.0005)
        m = compute_performance(snaps)
        assert m.absolute_return > 0
        assert m.cagr > 0
        assert m.annualized_volatility == pytest.approx(0.0, abs=1e-6)
        # Constant return → Sharpe is technically undefined (vol=0); we report 0.
        assert m.sharpe == 0.0

    def test_requires_two_snapshots(self) -> None:
        with pytest.raises(ValueError):
            compute_performance(_series(date(2024, 1, 1), 1, 0.0))

    def test_zero_return_series_has_zero_cagr(self) -> None:
        snaps = _series(date(2024, 1, 1), 100, daily_return=0.0)
        m = compute_performance(snaps)
        assert m.cagr == pytest.approx(0.0, abs=1e-9)
        assert m.absolute_return == pytest.approx(0.0, abs=1e-9)


class TestDrawdown:
    def test_pure_growth_has_zero_drawdown(self) -> None:
        snaps = _series(date(2024, 1, 1), 50, daily_return=0.001)
        stats = max_drawdown(snaps)
        assert stats.max_drawdown == 0.0

    def test_detects_pull_back(self) -> None:
        # Build a series that rises then falls.
        d = date(2024, 1, 1)
        snaps = []
        for i, v in enumerate([100, 110, 120, 90, 95, 100]):
            snaps.append(
                PortfolioSnapshot(
                    date=d + timedelta(days=i),
                    portfolio_value=v,
                    cash=0.0,
                    holdings_value=v,
                    drawdown=min(v / max(snaps[-1].portfolio_value if snaps else v, v) - 1.0, 0.0),
                )
            )
        stats = max_drawdown(snaps)
        # Peak 120 on day 3, trough 90 on day 4 → -25%.
        assert stats.max_drawdown == pytest.approx(-0.25)
        assert stats.peak_date == date(2024, 1, 3)
        assert stats.trough_date == date(2024, 1, 4)

    def test_empty_series(self) -> None:
        stats = max_drawdown([])
        assert stats.max_drawdown == 0.0


class TestReporting:
    def test_csv_writes_with_header_when_empty(self, tmp_path: Path) -> None:
        write_transactions_csv(tmp_path / "tx.csv", [])
        assert (tmp_path / "tx.csv").read_text().startswith("id,date")
        write_snapshots_csv(tmp_path / "snap.csv", [])
        assert (tmp_path / "snap.csv").read_text().startswith("date,portfolio_value")

    def test_csv_round_trip(self, tmp_path: Path) -> None:
        snaps = _series(date(2024, 1, 1), 5, daily_return=0.001)
        write_snapshots_csv(tmp_path / "snap.csv", snaps)
        text = (tmp_path / "snap.csv").read_text().splitlines()
        assert len(text) == 6  # 1 header + 5 rows

        tx = [
            Transaction(
                id="tx-00000001",
                date=date(2024, 1, 1),
                fund_id="120503",
                transaction_type=TransactionType.BUY,
                units=10.0,
                nav=50.0,
                amount=500.0,
            )
        ]
        write_transactions_csv(tmp_path / "tx.csv", tx)
        lines = (tmp_path / "tx.csv").read_text().splitlines()
        assert "BUY" in lines[1]

    def test_json_run_serialises_dataclasses_and_models(self, tmp_path: Path) -> None:
        snaps = _series(date(2024, 1, 1), 10, daily_return=0.001)
        perf = compute_performance(snaps)
        dd = max_drawdown(snaps)
        write_run_json(
            tmp_path / "run.json",
            config={"name": "test"},
            config_hash="deadbeef",
            engine_version="0.0.1",
            performance=perf,
            drawdown=dd,
            snapshots=snaps,
            transactions=[],
        )
        payload = orjson.loads((tmp_path / "run.json").read_bytes())
        assert payload["config_hash"] == "deadbeef"
        assert payload["engine_version"] == "0.0.1"
        assert "performance" in payload
        assert payload["performance"]["start_date"] == "2024-01-01"
        assert isinstance(payload["snapshots"], list)
        assert payload["snapshots"][0]["date"] == "2024-01-01"
