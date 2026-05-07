"""``sukoon-bt init`` — scaffold a starter strategy YAML."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()

TEMPLATES = {
    "buy_and_hold": """\
name: Buy and Hold

capital:
  initial: 100000
  sip: 0

universe:
  funds:
    - "120503"  # Parag Parikh Flexi Cap

allocation:
  method: equal_weight

rebalance:
  frequency: never

benchmark:
  id: "NIFTY 500"

period:
  start: 2018-01-01
  end: 2024-12-31
""",
    "momentum": """\
name: Top-3 Flexi-Cap Momentum

capital:
  initial: 100000
  sip: 10000

universe:
  category: "Flexi Cap"
  limit: 30

signal:
  type: momentum
  params:
    lookback_days: 180
    top_n: 3

allocation:
  method: equal_weight

rebalance:
  frequency: monthly
  threshold: 0.10

benchmark:
  id: "NIFTY 500"

period:
  start: 2018-01-01
  end: 2024-12-31
""",
}


def run(
    template: str = typer.Argument(
        "buy_and_hold", help="Template name (buy_and_hold | momentum)"
    ),
    output: Path = typer.Option(  # noqa: B008
        Path("strategy.yaml"), "--output", "-o", help="Output YAML path."
    ),
) -> None:
    """Write a starter strategy YAML to disk."""
    if template not in TEMPLATES:
        console.print(
            f"[red]Unknown template '{template}'.[/red] Available: "
            + ", ".join(TEMPLATES.keys())
        )
        raise typer.Exit(code=2)
    if output.exists():
        console.print(f"[yellow]Refusing to overwrite existing file:[/yellow] {output}")
        raise typer.Exit(code=1)
    output.write_text(TEMPLATES[template])
    console.print(f"[green]Wrote[/green] {output} ({template} template)")


__all__ = ["run"]
