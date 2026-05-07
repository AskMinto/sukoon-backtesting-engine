"""sukoon-bt CLI entry point — spec §16."""

from __future__ import annotations

import typer

from sukoon_bt import __version__
from sukoon_bt.cli.commands import backtest as backtest_cmd
from sukoon_bt.cli.commands import init as init_cmd
from sukoon_bt.cli.commands import optimize as optimize_cmd
from sukoon_bt.cli.commands import report as report_cmd

app = typer.Typer(
    name="sukoon-bt",
    help="Event-driven mutual fund backtesting CLI for the Sukoon data API.",
    add_completion=False,
    invoke_without_command=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Print sukoon-bt version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    # If no subcommand and no eager flag fired, show help.
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


app.command("backtest")(backtest_cmd.run)
app.command("init")(init_cmd.run)
app.command("optimize")(optimize_cmd.run)
app.command("report")(report_cmd.run)


if __name__ == "__main__":
    app()
