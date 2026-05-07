"""Compare CLI tests."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from sukoon_bt.cli.app import app
from sukoon_bt.data.cache import CacheBundle


def _fixture_nav(start: date, days: int) -> pl.DataFrame:
    rows = []
    nav = 100.0
    d = start
    for _ in range(days):
        if d.weekday() < 5:
            rows.append({"date": d, "nav": nav})
            nav *= 1.001
        d += timedelta(days=1)
    return pl.DataFrame(rows).with_columns(
        pl.col("date").cast(pl.Date), pl.col("nav").cast(pl.Float64)
    )


def test_compare_two_strategies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_root = tmp_path / "cache"
    bundle = CacheBundle(cache_root)
    bundle.nav.put("X", _fixture_nav(date(2024, 1, 1), 90), date(2024, 1, 1), date(2024, 3, 31))
    bundle.close()
    monkeypatch.setattr(
        "sukoon_bt.cli.commands.compare.CacheBundle",
        lambda: CacheBundle(cache_root),
    )
    monkeypatch.setenv("MINTO_API_URL", "http://127.0.0.1:1")

    a = tmp_path / "a.yaml"
    a.write_text(
        """\
name: A
capital: { initial: 100000, sip: 0 }
universe: { funds: ["X"] }
allocation: { method: equal_weight }
rebalance: { frequency: monthly }
period: { start: 2024-01-02, end: 2024-03-29 }
""",
    )
    b = tmp_path / "b.yaml"
    b.write_text(
        """\
name: B
capital: { initial: 50000, sip: 0 }
universe: { funds: ["X"] }
allocation: { method: equal_weight }
rebalance: { frequency: never }
period: { start: 2024-01-02, end: 2024-03-29 }
""",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["compare", str(a), str(b), "--offline"])
    if result.exit_code != 0:
        print(result.stdout)
        if result.exception:
            raise result.exception
    assert result.exit_code == 0
    # Output should mention both strategy names and a Δ column.
    assert "A" in result.stdout
    assert "B" in result.stdout
    assert "CAGR" in result.stdout or "Cagr" in result.stdout


def test_compare_missing_section_rejected(tmp_path: Path) -> None:
    a = tmp_path / "ok.yaml"
    a.write_text(
        """\
name: A
capital: { initial: 100000 }
universe: { funds: ["X"] }
period: { start: 2024-01-01, end: 2024-03-31 }
""",
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: invalid\n")
    result = CliRunner().invoke(app, ["compare", str(a), str(bad)])
    assert result.exit_code != 0
