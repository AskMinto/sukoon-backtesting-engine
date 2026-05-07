"""End-to-end backtest CLI test.

Pre-populates the local cache with synthetic NAV data so the backtest
runs in offline mode without hitting the network.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import orjson
import polars as pl
import pytest
from typer.testing import CliRunner

from sukoon_bt.cli.app import app
from sukoon_bt.data.cache import CacheBundle


def _fixture_nav(start: date, days: int, daily_pct: float = 0.0005) -> pl.DataFrame:
    rows = []
    nav = 100.0
    d = start
    for _ in range(days):
        if d.weekday() < 5:
            rows.append({"date": d, "nav": nav})
            nav *= 1 + daily_pct
        d += timedelta(days=1)
    return pl.DataFrame(rows).with_columns(
        pl.col("date").cast(pl.Date), pl.col("nav").cast(pl.Float64)
    )


@pytest.fixture
def cached_run_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seed a cache with a known fund and point CacheBundle at it."""
    cache_root = tmp_path / "cache"
    bundle = CacheBundle(cache_root)
    df = _fixture_nav(date(2024, 1, 1), 90)
    bundle.nav.put("120503", df, date(2024, 1, 1), date(2024, 3, 31))
    bundle.close()

    # Force CacheBundle() to read this directory by patching default_cache_dir.
    monkeypatch.setattr(
        "sukoon_bt.cli.commands.backtest.CacheBundle",
        lambda: CacheBundle(cache_root),
    )
    # Also stop the network from being hit even by accident.
    monkeypatch.setenv("MINTO_API_URL", "http://127.0.0.1:1")
    return tmp_path


def test_end_to_end_offline_backtest(cached_run_env: Path) -> None:
    cfg = cached_run_env / "strategy.yaml"
    cfg.write_text(
        """\
name: Test BNH

capital:
  initial: 100000
  sip: 0

universe:
  funds:
    - "120503"

allocation:
  method: equal_weight

rebalance:
  frequency: monthly

benchmark:
  id: "NIFTY 500"

period:
  start: 2024-01-01
  end: 2024-03-31
""",
    )
    out_dir = cached_run_env / "out"

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["backtest", str(cfg), "--offline", "-o", str(out_dir)],
    )
    if result.exit_code != 0:
        # Surface stderr/stdout to the test log for easier triage.
        print(result.stdout)
        if result.exception:
            raise result.exception
    assert result.exit_code == 0

    # Outputs created.
    assert (out_dir / "run.json").exists()
    assert (out_dir / "snapshots.csv").exists()
    assert (out_dir / "transactions.csv").exists()

    payload = orjson.loads((out_dir / "run.json").read_bytes())
    assert payload["engine_version"]
    assert payload["config_hash"]
    assert payload["config"]["name"] == "Test BNH"
    assert len(payload["snapshots"]) > 0
    # Monthly rebalance against rising NAV → at least one BUY tx.
    assert len(payload["transactions"]) >= 1


def test_deterministic_run_produces_same_hash(cached_run_env: Path) -> None:
    cfg = cached_run_env / "strategy.yaml"
    cfg.write_text(
        """\
name: Det Test
capital: { initial: 100000, sip: 0 }
universe: { funds: ["120503"] }
allocation: { method: equal_weight }
rebalance: { frequency: monthly }
benchmark: { id: "NIFTY 500" }
period: { start: 2024-01-01, end: 2024-03-31 }
""",
    )
    runner = CliRunner()
    out1 = cached_run_env / "out1"
    out2 = cached_run_env / "out2"
    r1 = runner.invoke(app, ["backtest", str(cfg), "--offline", "-o", str(out1)])
    r2 = runner.invoke(app, ["backtest", str(cfg), "--offline", "-o", str(out2)])
    assert r1.exit_code == 0
    assert r2.exit_code == 0
    h1 = orjson.loads((out1 / "run.json").read_bytes())["config_hash"]
    h2 = orjson.loads((out2 / "run.json").read_bytes())["config_hash"]
    assert h1 == h2

    # Same input → same final portfolio value too.
    p1 = orjson.loads((out1 / "run.json").read_bytes())["performance"]
    p2 = orjson.loads((out2 / "run.json").read_bytes())["performance"]
    assert p1["final_value"] == p2["final_value"]


def test_missing_section_in_yaml_fails(tmp_path: Path) -> None:
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("name: x\n")
    runner = CliRunner()
    result = runner.invoke(app, ["backtest", str(cfg)])
    assert result.exit_code != 0
