"""``sukoon-bt backtest`` — load YAML, run engine, write reports."""

from __future__ import annotations

import asyncio
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
from sukoon_bt.core.engine import Engine, EngineConfig
from sukoon_bt.data.cache import CacheBundle
from sukoon_bt.data.client import SukoonDataClient
from sukoon_bt.data.repository import FundRepository
from sukoon_bt.reporting.csv import write_snapshots_csv, write_transactions_csv
from sukoon_bt.reporting.json import write_run_json
from sukoon_bt.strategies.buy_and_hold import BuyAndHold
from sukoon_bt.utils.hashing import hash_config

console = Console()


def run(
    config: Path = typer.Argument(  # noqa: B008
        ..., exists=True, readable=True, help="Path to strategy YAML."
    ),
    output_dir: Path = typer.Option(  # noqa: B008
        Path("out"), "--output", "-o", help="Directory for run outputs."
    ),
    offline: bool = typer.Option(
        False, "--offline", help="Use only cached data; do not hit the network."
    ),
) -> None:
    """Run a deterministic backtest from a YAML config."""
    cfg = _load_config(config)
    cfg_hash = hash_config(cfg)
    output_dir.mkdir(parents=True, exist_ok=True)

    asyncio.run(_run_async(cfg, cfg_hash, output_dir, offline))


async def _run_async(
    cfg: dict[str, Any], cfg_hash: str, output_dir: Path, offline: bool
) -> None:
    period_start = _as_date(cfg["period"]["start"])
    period_end = _as_date(cfg["period"]["end"])
    fund_ids = _resolve_universe(cfg)
    initial_capital = float(cfg["capital"]["initial"])
    sip_amount = float(cfg["capital"].get("sip", 0.0))
    rebalance_frequency = str(cfg.get("rebalance", {}).get("frequency", "never"))

    nav_history = await _load_nav_history(fund_ids, period_start, period_end, offline)
    if not nav_history or all(df.is_empty() for df in nav_history.values()):
        console.print(
            "[red]No NAV data available for the configured universe + period.[/red] "
            "Check fund ids, the date range, and (if offline) the cache."
        )
        raise typer.Exit(code=1)

    strategy = BuyAndHold(fund_ids=fund_ids)
    engine = Engine(
        strategy=strategy,
        nav_history=nav_history,
        config=EngineConfig(
            initial_capital=initial_capital,
            sip_amount=sip_amount,
            rebalance_frequency=rebalance_frequency,
        ),
    )
    result = engine.run()

    snaps = result.portfolio.snapshots
    if len(snaps) < 2:
        console.print("[red]Engine produced fewer than 2 snapshots; cannot compute metrics.[/red]")
        raise typer.Exit(code=1)
    cashflows = [
        (snaps[0].date, -float(initial_capital)),
        (snaps[-1].date, snaps[-1].portfolio_value),
    ]
    perf = compute_performance(snaps, cashflows=cashflows)
    dd = max_drawdown(snaps)

    write_run_json(
        output_dir / "run.json",
        config=cfg,
        config_hash=cfg_hash,
        engine_version=__version__,
        performance=perf,
        drawdown=dd,
        snapshots=snaps,
        transactions=list(result.portfolio.ledger),
    )
    write_transactions_csv(output_dir / "transactions.csv", list(result.portfolio.ledger))
    write_snapshots_csv(output_dir / "snapshots.csv", snaps)

    summary = Table(title=cfg.get("name", "sukoon-bt run"))
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Engine version", __version__)
    summary.add_row("Config hash", cfg_hash)
    summary.add_row("Period", f"{perf.start_date} → {perf.end_date}")
    summary.add_row("Initial value", f"₹{perf.initial_value:,.2f}")
    summary.add_row("Final value", f"₹{perf.final_value:,.2f}")
    summary.add_row("Absolute return", f"{perf.absolute_return * 100:.2f}%")
    summary.add_row("CAGR", f"{perf.cagr * 100:.2f}%")
    summary.add_row("Annualised vol", f"{perf.annualized_volatility * 100:.2f}%")
    summary.add_row("Sharpe", f"{perf.sharpe:.3f}")
    summary.add_row("Sortino", f"{perf.sortino:.3f}")
    if perf.xirr is not None:
        summary.add_row("XIRR", f"{perf.xirr * 100:.2f}%")
    summary.add_row("Max drawdown", f"{dd.max_drawdown * 100:.2f}%")
    summary.add_row("Transactions", str(len(result.portfolio.ledger)))
    summary.add_row("Snapshots", str(len(snaps)))
    summary.add_row("Outputs", str(output_dir.resolve()))
    console.print(summary)


def _load_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        raise typer.BadParameter("strategy YAML must be a mapping")
    for required in ("capital", "universe", "period"):
        if required not in payload:
            raise typer.BadParameter(f"strategy YAML missing required section '{required}'")
    return payload


def _resolve_universe(cfg: dict[str, Any]) -> list[str]:
    universe = cfg.get("universe", {})
    funds = universe.get("funds")
    if not funds:
        raise typer.BadParameter(
            "Phase 1 only supports an explicit universe.funds list. "
            "Category-based universes ship in Phase 2."
        )
    return [str(f) for f in funds]


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


async def _load_nav_history(
    fund_ids: list[str],
    start: date,
    end: date,
    offline: bool,
) -> dict[str, pl.DataFrame]:
    with CacheBundle() as cache:
        async with SukoonDataClient() as client:
            repo = FundRepository(client=client, cache=cache, offline=offline)
            out: dict[str, pl.DataFrame] = {}
            for fid in fund_ids:
                out[fid] = await repo.nav(fid, start, end)
            return out


__all__ = ["run"]
