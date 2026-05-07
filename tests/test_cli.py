"""CLI command tests via typer's CliRunner."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sukoon_bt import __version__
from sukoon_bt.cli.app import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_when_no_args() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage" in result.stdout
    assert "backtest" in result.stdout
    assert "init" in result.stdout
    assert "report" in result.stdout


def test_init_writes_buy_and_hold_template(tmp_path: Path) -> None:
    out = tmp_path / "strategy.yaml"
    result = runner.invoke(app, ["init", "buy_and_hold", "-o", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    text = out.read_text()
    assert "name: Buy and Hold" in text
    assert "120503" in text


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "strategy.yaml"
    out.write_text("# existing")
    result = runner.invoke(app, ["init", "buy_and_hold", "-o", str(out)])
    assert result.exit_code == 1


def test_init_unknown_template(tmp_path: Path) -> None:
    out = tmp_path / "x.yaml"
    result = runner.invoke(app, ["init", "no_such_template", "-o", str(out)])
    assert result.exit_code == 2


def test_backtest_stub_invokes(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("name: stub\n")
    result = runner.invoke(app, ["backtest", str(cfg)])
    assert result.exit_code == 0
