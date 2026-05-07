"""Plugin registry tests."""

from __future__ import annotations

import pytest

from sukoon_bt.cli.commands.backtest import _build_strategy
from sukoon_bt.core.context import Context
from sukoon_bt.core.events import Event
from sukoon_bt.plugins import (
    collect_metrics,
    collect_strategies,
    get_manager,
    hookimpl,
    reset_for_tests,
)
from sukoon_bt.strategies.base import Strategy


class _FakeStrategy(Strategy):
    def __init__(self, universe: list[str], **_: object) -> None:
        self.universe = list(universe)

    def initialize(self, context: Context) -> None:
        pass

    def on_day(self, event: Event, context: Context) -> None:
        pass

    def generate_signals(self, context: Context) -> dict[str, float]:
        return {fid: 1.0 for fid in self.universe}

    def target_allocations(self, context: Context) -> dict[str, float]:
        weight = 1.0 / len(self.universe)
        return {fid: weight for fid in self.universe}


class _FakePlugin:
    @hookimpl
    def register_strategies(self) -> dict[str, type]:
        return {"fake_strategy": _FakeStrategy}

    @hookimpl
    def register_metrics(self) -> dict[str, object]:
        return {"fake_metric": lambda snapshots: 42.0}


@pytest.fixture
def registered_plugin():
    reset_for_tests()
    manager = get_manager()
    plugin = _FakePlugin()
    manager.register(plugin, name="fake")
    yield
    reset_for_tests()


def test_collect_strategies_returns_registered(registered_plugin) -> None:
    strats = collect_strategies()
    assert "fake_strategy" in strats
    assert strats["fake_strategy"] is _FakeStrategy


def test_collect_metrics_returns_registered(registered_plugin) -> None:
    metrics = collect_metrics()
    assert "fake_metric" in metrics
    assert metrics["fake_metric"](None) == 42.0


def test_dispatch_uses_plugin_strategy(registered_plugin) -> None:
    cfg = {"signal": {"type": "fake_strategy"}}
    s = _build_strategy(cfg, ["A", "B"])
    assert isinstance(s, _FakeStrategy)
    assert s.universe == ["A", "B"]


def test_dispatch_falls_back_to_unknown_error_when_no_plugin() -> None:
    reset_for_tests()
    cfg = {"signal": {"type": "no_such_strategy"}}
    with pytest.raises(Exception):
        _build_strategy(cfg, ["A"])


def test_no_plugins_no_strategies() -> None:
    reset_for_tests()
    assert collect_strategies() == {}
    assert collect_metrics() == {}
