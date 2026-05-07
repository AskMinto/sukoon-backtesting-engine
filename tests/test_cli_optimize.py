"""Optimisation CLI tests — grid search."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import orjson
import polars as pl
import pytest
from typer.testing import CliRunner

from sukoon_bt.cli.app import app
from sukoon_bt.cli.commands.optimize import _coerce, _parse_param_grid, _set_dotted
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


class TestParamGrid:
    def test_simple(self) -> None:
        grid = _parse_param_grid(["lookback=30,60,90"])
        assert grid == {"lookback": [30, 60, 90]}

    def test_multiple_keys(self) -> None:
        grid = _parse_param_grid(["a=1,2", "b=x,y,z"])
        assert grid == {"a": [1, 2], "b": ["x", "y", "z"]}

    def test_floats_and_strings(self) -> None:
        grid = _parse_param_grid(["thresh=0.05,0.10"])
        assert grid == {"thresh": [0.05, 0.10]}

    def test_missing_equals_rejected(self) -> None:
        with pytest.raises(Exception):
            _parse_param_grid(["lookback"])


class TestCoerce:
    @pytest.mark.parametrize("s,expected", [("30", 30), ("0.5", 0.5), ("true", True), ("hello", "hello")])
    def test_types(self, s: str, expected: object) -> None:
        assert _coerce(s) == expected


class TestSetDotted:
    def test_creates_nested_path(self) -> None:
        cfg: dict = {}
        _set_dotted(cfg, "signal.params.lookback_days", 90)
        assert cfg == {"signal": {"params": {"lookback_days": 90}}}

    def test_overwrites_existing(self) -> None:
        cfg = {"signal": {"params": {"lookback_days": 30}}}
        _set_dotted(cfg, "signal.params.lookback_days", 90)
        assert cfg["signal"]["params"]["lookback_days"] == 90


class TestEndToEndSweep:
    def test_grid_search(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cache_root = tmp_path / "cache"
        bundle = CacheBundle(cache_root)
        df = _fixture_nav(date(2024, 1, 1), 90)
        bundle.nav.put("X", df, date(2024, 1, 1), date(2024, 3, 31))
        bundle.close()
        monkeypatch.setattr(
            "sukoon_bt.cli.commands.optimize.CacheBundle",
            lambda: CacheBundle(cache_root),
        )
        monkeypatch.setenv("MINTO_API_URL", "http://127.0.0.1:1")

        cfg = tmp_path / "base.yaml"
        cfg.write_text(
            """\
name: Sweep test
capital: { initial: 100000, sip: 0 }
universe: { funds: ["X"] }
allocation: { method: equal_weight }
rebalance: { frequency: monthly }
period: { start: 2024-01-02, end: 2024-03-29 }
""",
        )
        out = tmp_path / "sweep"
        result = CliRunner().invoke(
            app,
            [
                "optimize",
                str(cfg),
                "--param",
                "rebalance.threshold=0.0,0.05",
                "--param",
                "capital.initial=50000,100000",
                "--offline",
                "-o",
                str(out),
                "--rank",
                "cagr",
            ],
        )
        if result.exit_code != 0:
            print(result.stdout)
            if result.exception:
                raise result.exception
        assert result.exit_code == 0
        assert (out / "leaderboard.csv").exists()
        assert (out / "leaderboard.json").exists()
        rows = orjson.loads((out / "leaderboard.json").read_bytes())
        # 2 thresholds × 2 capitals = 4 combos.
        assert len(rows) == 4
        # Each row has the swept keys and the metrics.
        assert {"rebalance.threshold", "capital.initial", "cagr", "config_hash"}.issubset(
            rows[0].keys()
        )
