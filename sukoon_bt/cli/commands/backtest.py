"""``sukoon-bt backtest`` — placeholder; wired in C11."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()


def run(
    config: Path = typer.Argument(  # noqa: ARG001 — wired in C11
        ..., exists=True, readable=True, help="Path to strategy YAML."
    ),
    output_dir: Path = typer.Option(  # noqa: ARG001 — wired in C11
        Path("out"), "--output", "-o", help="Directory for run outputs."
    ),
    offline: bool = typer.Option(  # noqa: ARG001 — wired in C11
        False, "--offline", help="Use only cached data; do not hit the network."
    ),
) -> None:
    """Run a deterministic backtest from a YAML config."""
    console.print(
        "[yellow]backtest command stub[/yellow] — implementation lands in C11."
    )
    raise typer.Exit(code=0)


__all__ = ["run"]
