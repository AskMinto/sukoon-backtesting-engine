"""``sukoon-bt optimize`` — grid search over strategy parameters.

Spec §18 V1: grid search / parameter sweeps. Each run reuses the cached
NAV history so cost is dominated by the engine, not the network.

Usage::

    sukoon-bt optimize strategy.yaml \\
        --param signal.params.lookback_days=30,60,90,180 \\
        --param signal.params.top_n=2,3,5 \\
        --output out/sweep \\
        --rank cagr
"""

from __future__ import annotations

import asyncio
import copy
import itertools
from datetime import date
from pathlib import Path
from typing import Any

import orjson
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

VALID_RANK_KEYS = ("cagr", "sharpe", "sortino", "absolute_return", "xirr")


def run(
    config: Path = typer.Argument(  # noqa: B008
        ..., exists=True, readable=True, help="Base strategy YAML to sweep."
    ),
    param: list[str] = typer.Option(  # noqa: B008
        [],
        "--param",
        "-p",
        help="key=v1,v2,v3 — dotted path through the YAML, e.g. "
        "signal.params.lookback_days=30,60,90.",
    ),
    output_dir: Path = typer.Option(  # noqa: B008
        Path("out/sweep"), "--output", "-o", help="Directory for sweep outputs."
    ),
    rank: str = typer.Option(
        "cagr",
        "--rank",
        help=f"Metric to rank by ({', '.join(VALID_RANK_KEYS)}).",
    ),
    offline: bool = typer.Option(
        False, "--offline", help="Use only cached data; do not hit the network."
    ),
) -> None:
    """Run a grid-search backtest sweep over the parameters listed in --param."""
    if rank not in VALID_RANK_KEYS:
        raise typer.BadParameter(
            f"--rank must be one of {VALID_RANK_KEYS}, got {rank!r}"
        )
    base_cfg = yaml.safe_load(config.read_text())
    if not isinstance(base_cfg, dict):
        raise typer.BadParameter("base strategy YAML must be a mapping")

    grid = _parse_param_grid(param)
    if not grid:
        raise typer.BadParameter("at least one --param key=v1,v2,... is required")

    output_dir.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run_sweep(base_cfg, grid, output_dir, rank, offline))


def _parse_param_grid(params: list[str]) -> dict[str, list[Any]]:
    grid: dict[str, list[Any]] = {}
    for spec in params:
        if "=" not in spec:
            raise typer.BadParameter(f"--param '{spec}' must be in form key=v1,v2,...")
        key, raw_values = spec.split("=", 1)
        values: list[Any] = []
        for v in raw_values.split(","):
            v = v.strip()
            if not v:
                continue
            values.append(_coerce(v))
        if not values:
            raise typer.BadParameter(f"--param '{spec}' has no values")
        grid[key.strip()] = values
    return grid


def _coerce(s: str) -> Any:
    """Coerce a CLI string to int/float/bool/str; YAML cast keeps semantics simple."""
    try:
        return yaml.safe_load(s)
    except yaml.YAMLError:
        return s


def _set_dotted(cfg: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur: Any = cfg
    for k in parts[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]
    cur[parts[-1]] = value


async def _run_sweep(
    base_cfg: dict[str, Any],
    grid: dict[str, list[Any]],
    output_dir: Path,
    rank: str,
    offline: bool,
) -> None:
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    console.print(
        f"[cyan]Sweep:[/cyan] {len(combos)} combos across {len(keys)} parameter(s)"
    )

    period_start = _as_date(base_cfg["period"]["start"])
    period_end = _as_date(base_cfg["period"]["end"])

    # Resolve universe and prefetch NAV history once — every combo reuses it.
    funds: dict[str, object] = {}
    nav_history: dict[str, pl.DataFrame] = {}
    with CacheBundle() as cache:
        async with SukoonDataClient() as client:
            repo = FundRepository(client=client, cache=cache, offline=offline)
            fund_ids = await _resolve_universe(base_cfg, repo)
            for fid in fund_ids:
                nav_history[fid] = await repo.nav(fid, period_start, period_end)
                try:
                    funds[fid] = await repo.fund(fid)
                except Exception:
                    pass

    rows: list[dict[str, Any]] = []
    for combo in combos:
        cfg = copy.deepcopy(base_cfg)
        for k, v in zip(keys, combo, strict=True):
            _set_dotted(cfg, k, v)
        try:
            metrics = _run_one(cfg, fund_ids, nav_history, funds)
        except Exception as e:
            console.print(
                f"[red]combo {dict(zip(keys, combo, strict=True))} failed:[/red] {e}"
            )
            continue
        row = {**dict(zip(keys, combo, strict=True)), **metrics}
        rows.append(row)

    if not rows:
        console.print("[red]No combos completed successfully.[/red]")
        raise typer.Exit(code=1)

    leaderboard = pl.DataFrame(rows).sort(rank, descending=True)
    csv_path = output_dir / "leaderboard.csv"
    json_path = output_dir / "leaderboard.json"
    leaderboard.write_csv(csv_path)
    json_path.write_bytes(orjson.dumps(rows, option=orjson.OPT_INDENT_2))

    table = Table(title=f"Sweep leaderboard (rank by {rank})")
    for col in leaderboard.columns:
        table.add_column(col)
    for row in leaderboard.head(10).iter_rows(named=True):
        table.add_row(*[_fmt(row[c]) for c in leaderboard.columns])
    console.print(table)
    console.print(f"[green]Wrote[/green] {csv_path} and {json_path}")


def _run_one(
    cfg: dict[str, Any],
    fund_ids: list[str],
    nav_history: dict[str, pl.DataFrame],
    funds: dict[str, object],
) -> dict[str, Any]:
    initial_capital = float(cfg["capital"]["initial"])
    sip_amount = float(cfg["capital"].get("sip", 0.0))
    rebalance_cfg = cfg.get("rebalance", {}) or {}
    rebalance_frequency = str(rebalance_cfg.get("frequency", "never"))
    rebalance_threshold = float(rebalance_cfg.get("threshold", 0.0))

    strategy = _build_strategy(cfg, fund_ids)
    engine = Engine(
        strategy=strategy,
        nav_history=nav_history,
        funds=funds or None,  # type: ignore[arg-type]
        config=EngineConfig(
            initial_capital=initial_capital,
            sip_amount=sip_amount,
            rebalance_frequency=rebalance_frequency,
            rebalance_threshold=rebalance_threshold,
        ),
    )
    result = engine.run()
    snaps = result.portfolio.snapshots
    if len(snaps) < 2:
        raise ValueError("engine produced fewer than 2 snapshots")
    cashflows = [
        (snaps[0].date, -float(initial_capital)),
        (snaps[-1].date, snaps[-1].portfolio_value),
    ]
    perf = compute_performance(snaps, cashflows=cashflows)
    dd = max_drawdown(snaps)
    return {
        "config_hash": hash_config(cfg),
        "engine_version": __version__,
        "final_value": perf.final_value,
        "absolute_return": perf.absolute_return,
        "cagr": perf.cagr,
        "sharpe": perf.sharpe,
        "sortino": perf.sortino,
        "max_drawdown": dd.max_drawdown,
        "xirr": perf.xirr if perf.xirr is not None else float("nan"),
        "transactions": len(result.portfolio.ledger),
    }


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4f}" if abs(v) > 0.001 else f"{v:.6f}"
    return str(v)


__all__ = ["run"]
