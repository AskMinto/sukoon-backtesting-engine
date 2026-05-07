"""HTML reporter tests."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from sukoon_bt.analytics.drawdown import max_drawdown
from sukoon_bt.analytics.metrics import compute_performance
from sukoon_bt.data.models import PortfolioSnapshot, Transaction, TransactionType
from sukoon_bt.reporting.html import write_run_html


def _series(start: date, days: int) -> list[PortfolioSnapshot]:
    snaps = []
    v = 100_000.0
    peak = v
    for i in range(days):
        v *= 1 + (0.001 if i % 5 != 0 else -0.005)
        peak = max(peak, v)
        snaps.append(
            PortfolioSnapshot(
                date=start + timedelta(days=i),
                portfolio_value=v,
                cash=0,
                holdings_value=v,
                drawdown=min(v / peak - 1.0, 0.0),
            )
        )
    return snaps


def test_html_report_writes_with_charts(tmp_path: Path) -> None:
    snaps = _series(date(2024, 1, 1), 60)
    perf = compute_performance(snaps)
    dd = max_drawdown(snaps)
    txs = [
        Transaction(
            id="tx-00000001",
            date=date(2024, 1, 1),
            fund_id="120503",
            transaction_type=TransactionType.BUY,
            units=10.0,
            nav=50.0,
            amount=500.0,
            taxes=15.0,
        )
    ]
    out = tmp_path / "report.html"
    write_run_html(
        out,
        config={"name": "Test"},
        config_hash="cafef00dcafef00d",
        engine_version="0.0.1",
        performance=perf,
        drawdown=dd,
        snapshots=snaps,
        transactions=txs,
    )
    body = out.read_text()
    # Title and metrics rendered.
    assert "<title>Test — sukoon-bt</title>" in body
    assert "CAGR" in body
    assert "Max drawdown" in body
    # Both SVG charts emitted.
    assert body.count("<svg") == 2
    # Transaction table rendered.
    assert "tx-00000001" in body
    assert "120503" in body
    # Config hash visible.
    assert "cafef00dcafef00d" in body


def test_empty_transactions_table(tmp_path: Path) -> None:
    snaps = _series(date(2024, 1, 1), 5)
    perf = compute_performance(snaps)
    dd = max_drawdown(snaps)
    out = tmp_path / "r.html"
    write_run_html(
        out,
        config={"name": "Empty"},
        config_hash="abc",
        engine_version="0.0.1",
        performance=perf,
        drawdown=dd,
        snapshots=snaps,
        transactions=[],
    )
    body = out.read_text()
    assert "No transactions." in body


def test_xss_safety(tmp_path: Path) -> None:
    snaps = _series(date(2024, 1, 1), 5)
    perf = compute_performance(snaps)
    dd = max_drawdown(snaps)
    out = tmp_path / "r.html"
    write_run_html(
        out,
        config={"name": "<script>alert(1)</script>"},
        config_hash="abc",
        engine_version="0.0.1",
        performance=perf,
        drawdown=dd,
        snapshots=snaps,
        transactions=[],
    )
    body = out.read_text()
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
