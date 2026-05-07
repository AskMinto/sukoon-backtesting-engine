"""``sukoon-bt compare`` — head-to-head comparison of two strategy YAMLs."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import typer
import yaml
from rich.console import Console
from rich.table import Table

from sukoon_bt import __version__
from sukoon_bt.analytics.drawdown import max_drawdown
from sukoon_bt.analytics.metrics import compute_performance
from sukoon_bt.cli.commands.backtest import _build_strategy, _resolve_universe
from sukoon_bt.core.engine import Engine, EngineConfig
from sukoon_bt.data.cache import CacheBundle
from sukoon_bt.data.client import SukoonDataClient
from sukoon_bt.data.repository import FundRepository
from sukoon_bt.utils.hashing import hash_config

console = Console()


def run(
    a: Path = typer.Argument(  # noqa: B008
        ..., exists=True, readable=True, help="First strategy YAML."
    ),
    b: Path = typer.Argument(  # noqa: B008
        ..., exists=True, readable=True, help="Second strategy YAML."
    ),
    offline: bool = typer.Option(
        False, "--offline", help="Use only cached data; do not hit the network."
    ),
) -> None:
    """Run two strategies head-to-head and print a side-by-side metric table."""
    cfg_a = _load_yaml(a)
    cfg_b = _load_yaml(b)
    asyncio.run(_run(cfg_a, cfg_b, offline))


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        raise typer.BadParameter(f"{path}: strategy YAML must be a mapping")
    for required in ("capital", "universe", "period"):
        if required not in payload:
            raise typer.BadParameter(f"{path} missing required section '{required}'")
    return payload


async def _run(cfg_a: dict[str, Any], cfg_b: dict[str, Any], offline: bool) -> None:
    with CacheBundle() as cache:
        async with SukoonDataClient() as client:
            repo = FundRepository(client=client, cache=cache, offline=offline)
            metrics_a = await _backtest(cfg_a, repo)
            metrics_b = await _backtest(cfg_b, repo)

    table = Table(
        title=f"Compare: {cfg_a.get('name', 'A')} vs {cfg_b.get('name', 'B')}"
    )
    table.add_column("Metric", style="cyan")
    table.add_column(cfg_a.get("name", "A"), style="green")
    table.add_column(cfg_b.get("name", "B"), style="magenta")
    table.add_column("Δ (A - B)", style="yellow")
    for label, key, fmt in (
        ("Period", "period", _fmt_str),
        ("Engine version", "engine_version", _fmt_str),
        ("Config hash", "config_hash", _fmt_str),
        ("Initial value", "initial_value", _fmt_money),
        ("Final value", "final_value", _fmt_money),
        ("Absolute return", "absolute_return", _fmt_pct),
        ("CAGR", "cagr", _fmt_pct),
        ("Annualised vol", "annualized_volatility", _fmt_pct),
        ("Sharpe", "sharpe", _fmt_num),
        ("Sortino", "sortino", _fmt_num),
        ("XIRR", "xirr", _fmt_pct_or_dash),
        ("Max drawdown", "max_drawdown", _fmt_pct),
        ("Transactions", "transactions", _fmt_str),
    ):
        a_val = metrics_a.get(key)
        b_val = metrics_b.get(key)
        delta = _delta(a_val, b_val)
        table.add_row(label, fmt(a_val), fmt(b_val), delta)
    console.print(table)


async def _backtest(cfg: dict[str, Any], repo: FundRepository) -> dict[str, Any]:
    period_start = _as_date(cfg["period"]["start"])
    period_end = _as_date(cfg["period"]["end"])
    fund_ids = await _resolve_universe(cfg, repo)

    nav_history: dict[str, pl.DataFrame] = {}
    funds: dict[str, object] = {}
    for fid in fund_ids:
        nav_history[fid] = await repo.nav(fid, period_start, period_end)
        with contextlib.suppress(Exception):
            funds[fid] = await repo.fund(fid)

    initial_capital = float(cfg["capital"]["initial"])
    sip_amount = float(cfg["capital"].get("sip", 0.0))
    rebalance_cfg = cfg.get("rebalance", {}) or {}
    engine = Engine(
        strategy=_build_strategy(cfg, fund_ids),
        nav_history=nav_history,
        funds=funds or None,  # type: ignore[arg-type]
        config=EngineConfig(
            initial_capital=initial_capital,
            sip_amount=sip_amount,
            rebalance_frequency=str(rebalance_cfg.get("frequency", "never")),
            rebalance_threshold=float(rebalance_cfg.get("threshold", 0.0)),
        ),
    )
    result = engine.run()
    snaps = result.portfolio.snapshots
    if len(snaps) < 2:
        raise typer.Exit(code=1)
    cashflows = [
        (snaps[0].date, -float(initial_capital)),
        (snaps[-1].date, snaps[-1].portfolio_value),
    ]
    perf = compute_performance(snaps, cashflows=cashflows)
    dd = max_drawdown(snaps)
    return {
        "period": f"{perf.start_date} → {perf.end_date}",
        "engine_version": __version__,
        "config_hash": hash_config(cfg),
        "initial_value": perf.initial_value,
        "final_value": perf.final_value,
        "absolute_return": perf.absolute_return,
        "cagr": perf.cagr,
        "annualized_volatility": perf.annualized_volatility,
        "sharpe": perf.sharpe,
        "sortino": perf.sortino,
        "xirr": perf.xirr,
        "max_drawdown": dd.max_drawdown,
        "transactions": len(result.portfolio.ledger),
    }


def _delta(a: Any, b: Any) -> str:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        d = a - b
        if isinstance(a, int) and isinstance(b, int):
            return f"{d:+d}"
        if abs(d) > 0.01:
            return f"{d:+.4f}"
        return f"{d:+.6f}"
    return "—"


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _fmt_money(v: Any) -> str:
    return f"₹{v:,.2f}" if isinstance(v, (int, float)) else "?"


def _fmt_pct(v: Any) -> str:
    return f"{v * 100:.2f}%" if isinstance(v, (int, float)) else "?"


def _fmt_pct_or_dash(v: Any) -> str:
    return f"{v * 100:.2f}%" if isinstance(v, (int, float)) else "—"


def _fmt_num(v: Any) -> str:
    return f"{v:.3f}" if isinstance(v, (int, float)) else "?"


def _fmt_str(v: Any) -> str:
    return str(v) if v is not None else "?"


__all__ = ["run"]
