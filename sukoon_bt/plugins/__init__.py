"""Plugin registry — spec §17.

Third parties can ship strategies and metrics as installable Python
packages and register them via the ``sukoon_bt`` entry-point group::

    # In your plugin's pyproject.toml
    [project.entry-points."sukoon_bt"]
    my_strategies = "my_pkg.plugin"

    # In my_pkg/plugin.py
    from sukoon_bt.plugins import hookimpl
    from sukoon_bt.strategies.base import Strategy

    class MyStrategy(Strategy):
        ...

    @hookimpl
    def register_strategies():
        return {"my_strategy": MyStrategy}

The CLI (``backtest._build_strategy``) checks the plugin registry
for any signal.type it doesn't recognise built-in.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable
from typing import Any

import pluggy

PROJECT_NAME = "sukoon_bt"
hookspec = pluggy.HookspecMarker(PROJECT_NAME)
hookimpl = pluggy.HookimplMarker(PROJECT_NAME)


class _Specs:
    """Hook specifications plugins implement."""

    @hookspec  # type: ignore[misc]
    def register_strategies(self) -> dict[str, type]:
        """Return ``{signal_type: StrategyClass}`` for new YAML-selectable strategies."""

    @hookspec  # type: ignore[misc]
    def register_metrics(self) -> dict[str, Callable[..., Any]]:
        """Return ``{metric_name: callable}`` for additional report metrics."""


_manager: pluggy.PluginManager | None = None


def get_manager() -> pluggy.PluginManager:
    """Return the singleton pluggy manager, lazily created."""
    global _manager
    if _manager is None:
        m = pluggy.PluginManager(PROJECT_NAME)
        m.add_hookspecs(_Specs)
        _load_entrypoints(m)
        _manager = m
    return _manager


def _load_entrypoints(manager: pluggy.PluginManager) -> None:
    try:
        eps = importlib.metadata.entry_points(group=PROJECT_NAME)
    except TypeError:
        # Python <3.10 fallback (we require 3.12 but be defensive).
        eps = importlib.metadata.entry_points().get(PROJECT_NAME, [])  # type: ignore[union-attr,assignment]
    for ep in eps:
        try:
            module = ep.load()
        except Exception:
            # A misbehaving plugin should not crash the CLI.
            continue
        manager.register(module, name=ep.name)


def collect_strategies() -> dict[str, type]:
    """Aggregate registered strategy classes from all plugins."""
    manager = get_manager()
    out: dict[str, type] = {}
    for mapping in manager.hook.register_strategies():
        if isinstance(mapping, dict):
            out.update(mapping)
    return out


def collect_metrics() -> dict[str, Callable[..., Any]]:
    """Aggregate registered metric callables from all plugins."""
    manager = get_manager()
    out: dict[str, Callable[..., Any]] = {}
    for mapping in manager.hook.register_metrics():
        if isinstance(mapping, dict):
            out.update(mapping)
    return out


def reset_for_tests() -> None:
    """Drop the cached plugin manager — tests use this to isolate state."""
    global _manager
    _manager = None


__all__ = [
    "PROJECT_NAME",
    "collect_metrics",
    "collect_strategies",
    "get_manager",
    "hookimpl",
    "hookspec",
    "reset_for_tests",
]
