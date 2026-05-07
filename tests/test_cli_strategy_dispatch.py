"""CLI dispatch tests: signal.type → Strategy class; universe.category → search_funds."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import orjson
import polars as pl
import pytest
from typer.testing import CliRunner

from sukoon_bt.cli.app import app
from sukoon_bt.cli.commands.backtest import _build_strategy, _resolve_universe
from sukoon_bt.data.cache import CacheBundle
from sukoon_bt.data.models import Fund
from sukoon_bt.strategies.buy_and_hold import BuyAndHold
from sukoon_bt.strategies.momentum import Momentum


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


class TestBuildStrategy:
    def test_default_is_buy_and_hold(self) -> None:
        s = _build_strategy({}, ["A", "B"])
        assert isinstance(s, BuyAndHold)

    def test_explicit_buy_and_hold(self) -> None:
        s = _build_strategy({"signal": {"type": "buy_and_hold"}}, ["A"])
        assert isinstance(s, BuyAndHold)

    def test_momentum_with_params(self) -> None:
        cfg = {"signal": {"type": "momentum", "params": {"lookback_days": 90, "top_n": 2}}}
        s = _build_strategy(cfg, ["A", "B", "C"])
        assert isinstance(s, Momentum)
        assert s._lookback_days == 90
        assert s._top_n == 2

    def test_unknown_signal_rejected(self) -> None:
        with pytest.raises(Exception):
            _build_strategy({"signal": {"type": "magic"}}, ["A"])


class TestResolveUniverse:
    @pytest.mark.asyncio
    async def test_explicit_funds_returned_directly(self) -> None:
        repo = AsyncMock()
        out = await _resolve_universe({"universe": {"funds": ["120503", "118989"]}}, repo)
        assert out == ["120503", "118989"]

    @pytest.mark.asyncio
    async def test_category_resolves_via_search_funds(self) -> None:
        repo = AsyncMock()
        repo._client = AsyncMock()
        repo._client.search_funds.return_value = [
            Fund(id="120503", name="PPFC", category="Flexi Cap", amc="PPFAS"),
            Fund(id="118989", name="HDFC FC", category="Flexi Cap", amc="HDFC"),
        ]
        out = await _resolve_universe(
            {"universe": {"category": "Flexi Cap", "limit": 25}}, repo
        )
        assert out == ["120503", "118989"]
        repo._client.search_funds.assert_awaited_once_with(category="Flexi Cap", page_size=25)

    @pytest.mark.asyncio
    async def test_empty_category_result_raises(self) -> None:
        repo = AsyncMock()
        repo._client = AsyncMock()
        repo._client.search_funds.return_value = []
        with pytest.raises(Exception):
            await _resolve_universe({"universe": {"category": "Nothing"}}, repo)

    @pytest.mark.asyncio
    async def test_neither_funds_nor_category_raises(self) -> None:
        repo = AsyncMock()
        with pytest.raises(Exception):
            await _resolve_universe({"universe": {}}, repo)


class TestEndToEndMomentum:
    def test_momentum_yaml_runs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cache_root = tmp_path / "cache"
        bundle = CacheBundle(cache_root)
        nav_a = _fixture_nav(date(2024, 1, 1), 90)
        nav_b = _fixture_nav(date(2024, 1, 1), 90)
        bundle.nav.put("A", nav_a, date(2024, 1, 1), date(2024, 3, 31))
        bundle.nav.put("B", nav_b, date(2024, 1, 1), date(2024, 3, 31))
        bundle.close()
        monkeypatch.setattr(
            "sukoon_bt.cli.commands.backtest.CacheBundle",
            lambda: CacheBundle(cache_root),
        )
        monkeypatch.setenv("MINTO_API_URL", "http://127.0.0.1:1")

        cfg = tmp_path / "mom.yaml"
        cfg.write_text(
            """\
name: Test Momentum
capital: { initial: 100000, sip: 0 }
universe:
  funds: ["A", "B"]
signal:
  type: momentum
  params:
    lookback_days: 30
    top_n: 1
allocation: { method: equal_weight }
rebalance: { frequency: monthly }
benchmark: { id: "NIFTY 500" }
period: { start: 2024-02-01, end: 2024-03-29 }
""",
        )
        result = CliRunner().invoke(
            app, ["backtest", str(cfg), "--offline", "-o", str(tmp_path / "out")]
        )
        if result.exit_code != 0:
            print(result.stdout)
            if result.exception:
                raise result.exception
        assert result.exit_code == 0
        payload = orjson.loads((tmp_path / "out" / "run.json").read_bytes())
        assert payload["config"]["signal"]["type"] == "momentum"
        # Universe size in summary — read indirectly via tx count > 0.
        assert len(payload["transactions"]) >= 1
