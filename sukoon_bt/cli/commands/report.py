"""``sukoon-bt report`` — pretty-print a saved run JSON."""

from __future__ import annotations

from pathlib import Path

import orjson
import typer
from rich.console import Console
from rich.table import Table

console = Console()


def run(
    results: Path = typer.Argument(  # noqa: B008
        ..., exists=True, readable=True, help="Path to run JSON."
    ),
) -> None:
    """Render a saved run.json as a rich-formatted summary."""
    payload = orjson.loads(results.read_bytes())
    perf = payload.get("performance", {})
    dd = payload.get("drawdown", {})

    summary = Table(title=payload.get("config", {}).get("name", "sukoon-bt run"))
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")

    summary.add_row("Engine version", str(payload.get("engine_version", "?")))
    summary.add_row("Config hash", str(payload.get("config_hash", "?")))
    summary.add_row("Period", f"{perf.get('start_date', '?')} → {perf.get('end_date', '?')}")
    summary.add_row("Initial value", _money(perf.get("initial_value")))
    summary.add_row("Final value", _money(perf.get("final_value")))
    summary.add_row("Absolute return", _pct(perf.get("absolute_return")))
    summary.add_row("CAGR", _pct(perf.get("cagr")))
    summary.add_row("Annualised vol", _pct(perf.get("annualized_volatility")))
    summary.add_row("Sharpe", _num(perf.get("sharpe")))
    summary.add_row("Sortino", _num(perf.get("sortino")))
    if perf.get("xirr") is not None:
        summary.add_row("XIRR", _pct(perf.get("xirr")))
    summary.add_row("Max drawdown", _pct(dd.get("max_drawdown")))
    if dd.get("peak_date") and dd.get("trough_date"):
        summary.add_row(
            "DD window", f"{dd['peak_date']} → {dd['trough_date']}"
        )
    summary.add_row("Transactions", str(len(payload.get("transactions", []))))
    summary.add_row("Snapshots", str(len(payload.get("snapshots", []))))

    console.print(summary)


def _money(v: float | None) -> str:
    return f"₹{v:,.2f}" if isinstance(v, (int, float)) else "?"


def _pct(v: float | None) -> str:
    return f"{v * 100:.2f}%" if isinstance(v, (int, float)) else "?"


def _num(v: float | None) -> str:
    return f"{v:.3f}" if isinstance(v, (int, float)) else "?"


__all__ = ["run"]
