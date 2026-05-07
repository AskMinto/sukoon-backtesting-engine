"""Self-contained single-file HTML reporter — spec §19.

Hand-rolled SVG charts (zero JS, zero external CDNs) so reports work
offline and are diff-friendly. The output is one HTML file with:

  * a metrics summary panel
  * portfolio_value over time (line chart)
  * drawdown over time (area chart)
  * a transactions table

Designers can replace the inline CSS without touching the data layer.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from sukoon_bt.analytics.drawdown import DrawdownStats
from sukoon_bt.analytics.metrics import PerformanceMetrics
from sukoon_bt.data.models import PortfolioSnapshot, Transaction


def write_run_html(
    path: Path,
    *,
    config: dict[str, Any],
    config_hash: str,
    engine_version: str,
    performance: PerformanceMetrics,
    drawdown: DrawdownStats,
    snapshots: list[PortfolioSnapshot],
    transactions: list[Transaction],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    html = _render_html(
        config=config,
        config_hash=config_hash,
        engine_version=engine_version,
        performance=performance,
        drawdown=drawdown,
        snapshots=snapshots,
        transactions=transactions,
    )
    path.write_text(html, encoding="utf-8")


def _render_html(
    *,
    config: dict[str, Any],
    config_hash: str,
    engine_version: str,
    performance: PerformanceMetrics,
    drawdown: DrawdownStats,
    snapshots: list[PortfolioSnapshot],
    transactions: list[Transaction],
) -> str:
    name = _esc(str(config.get("name", "sukoon-bt run")))
    pv_chart = _line_chart(
        snapshots,
        value_fn=lambda s: s.portfolio_value,
        title="Portfolio value (₹)",
        stroke="#1f77b4",
    )
    dd_chart = _line_chart(
        snapshots,
        value_fn=lambda s: s.drawdown * 100,
        title="Drawdown (%)",
        stroke="#d62728",
        fill="rgba(214,39,40,0.15)",
        zero_baseline=True,
    )
    metrics_html = _metrics_panel(performance, drawdown)
    tx_html = _transactions_table(transactions)
    cfg_html = _config_panel(config, config_hash, engine_version)
    return _TEMPLATE.format(
        title=name,
        metrics=metrics_html,
        pv_chart=pv_chart,
        dd_chart=dd_chart,
        config=cfg_html,
        transactions=tx_html,
    )


def _metrics_panel(perf: PerformanceMetrics, dd: DrawdownStats) -> str:
    rows = [
        ("Period", f"{perf.start_date} → {perf.end_date}"),
        ("Initial value", f"₹{perf.initial_value:,.2f}"),
        ("Final value", f"₹{perf.final_value:,.2f}"),
        ("Absolute return", f"{perf.absolute_return * 100:.2f}%"),
        ("CAGR", f"{perf.cagr * 100:.2f}%"),
        ("Annualised vol", f"{perf.annualized_volatility * 100:.2f}%"),
        ("Sharpe", f"{perf.sharpe:.3f}"),
        ("Sortino", f"{perf.sortino:.3f}"),
        ("XIRR", f"{perf.xirr * 100:.2f}%" if perf.xirr is not None else "—"),
        ("Max drawdown", f"{dd.max_drawdown * 100:.2f}%"),
    ]
    if dd.peak_date and dd.trough_date:
        rows.append(("DD window", f"{dd.peak_date} → {dd.trough_date}"))
    cells = "".join(
        f'<div class="metric"><div class="label">{_esc(label)}</div>'
        f'<div class="value">{_esc(value)}</div></div>'
        for label, value in rows
    )
    return f'<div class="metrics-grid">{cells}</div>'


def _config_panel(config: dict[str, Any], config_hash: str, engine_version: str) -> str:
    items = [
        ("Engine version", engine_version),
        ("Config hash", config_hash),
        ("Strategy", str(config.get("name", "?"))),
    ]
    rows = "".join(
        f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in items
    )
    return f'<table class="config-table">{rows}</table>'


def _transactions_table(transactions: Iterable[Transaction]) -> str:
    rows: list[str] = []
    for tx in list(transactions)[:200]:  # cap to keep HTML reasonable
        rows.append(
            "<tr>"
            f"<td>{_esc(tx.id)}</td>"
            f"<td>{_esc(tx.date.isoformat())}</td>"
            f"<td>{_esc(tx.fund_id)}</td>"
            f"<td>{_esc(tx.transaction_type.value)}</td>"
            f"<td>{tx.units:.4f}</td>"
            f"<td>{tx.nav:.4f}</td>"
            f"<td>₹{tx.amount:,.2f}</td>"
            f"<td>₹{tx.fees:,.2f}</td>"
            f"<td>₹{tx.taxes:,.2f}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="9">No transactions.</td></tr>'
    return (
        '<table class="tx-table">'
        "<thead><tr>"
        "<th>id</th><th>date</th><th>fund</th><th>type</th>"
        "<th>units</th><th>nav</th><th>amount</th><th>fees</th><th>taxes</th>"
        "</tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table>"
    )


def _line_chart(
    snapshots: list[PortfolioSnapshot],
    *,
    value_fn,
    title: str,
    stroke: str,
    fill: str | None = None,
    zero_baseline: bool = False,
) -> str:
    width = 880
    height = 280
    margin_left = 60
    margin_right = 20
    margin_top = 40
    margin_bottom = 40
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    if not snapshots:
        return f'<svg viewBox="0 0 {width} {height}"><text x="20" y="20">{_esc(title)}: no data</text></svg>'

    values = [value_fn(s) for s in snapshots]
    min_v = min(values + ([0.0] if zero_baseline else []))
    max_v = max(values + ([0.0] if zero_baseline else []))
    if max_v == min_v:
        max_v = min_v + 1.0
    n = len(snapshots)

    def x(i: int) -> float:
        return margin_left + (plot_w * i / max(n - 1, 1))

    def y(v: float) -> float:
        return margin_top + plot_h - (plot_h * (v - min_v) / (max_v - min_v))

    points = " ".join(f"{x(i):.2f},{y(v):.2f}" for i, v in enumerate(values))
    area = ""
    if fill:
        area = (
            '<polygon fill="{fill}" stroke="none" '
            'points="{first_x:.2f},{base:.2f} {pts} {last_x:.2f},{base:.2f}" />'
        ).format(
            fill=fill,
            first_x=x(0),
            last_x=x(n - 1),
            base=y(0.0) if zero_baseline else y(min_v),
            pts=points,
        )

    # Y-axis ticks (5 lines).
    ticks = ""
    for i in range(5):
        v = min_v + (max_v - min_v) * i / 4
        ty = y(v)
        ticks += (
            f'<line x1="{margin_left}" x2="{margin_left + plot_w}" '
            f'y1="{ty:.2f}" y2="{ty:.2f}" stroke="#eee"/>'
            f'<text x="{margin_left - 6}" y="{ty + 3:.2f}" '
            f'font-size="10" text-anchor="end" fill="#666">{_format_axis(v)}</text>'
        )
    # X-axis labels (start, mid, end).
    label_idxs = [0, n // 2, n - 1] if n >= 3 else list(range(n))
    x_labels = ""
    for i in label_idxs:
        x_labels += (
            f'<text x="{x(i):.2f}" y="{margin_top + plot_h + 14}" '
            f'font-size="10" text-anchor="middle" fill="#666">'
            f"{_esc(snapshots[i].date.isoformat())}</text>"
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart">'
        f'<text x="{margin_left}" y="20" font-size="14" fill="#222">{_esc(title)}</text>'
        f"{ticks}"
        f"{area}"
        f'<polyline fill="none" stroke="{stroke}" stroke-width="1.5" points="{points}"/>'
        f"{x_labels}"
        "</svg>"
    )


def _format_axis(v: float) -> str:
    if abs(v) >= 1_00_000:
        return f"₹{v / 100000:.1f}L"
    if abs(v) >= 1_000:
        return f"{v / 1000:.0f}k"
    if abs(v) >= 1:
        return f"{v:.2f}"
    return f"{v:.4f}"


def _esc(s: object) -> str:
    text = str(s)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _dataclass_to_dict(obj: Any) -> dict[str, Any]:
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"expected dataclass, got {type(obj).__name__}")


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title} — sukoon-bt</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         margin: 0; padding: 32px; color: #222; background: #fafafa; }}
  h1 {{ font-size: 22px; margin: 0 0 16px; }}
  h2 {{ font-size: 16px; margin: 28px 0 12px; color: #444; }}
  .panel {{ background: #fff; padding: 16px 20px; border: 1px solid #eee;
            border-radius: 6px; margin-bottom: 18px; }}
  .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                   gap: 12px; }}
  .metric .label {{ color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }}
  .metric .value {{ font-size: 18px; font-weight: 600; margin-top: 2px; }}
  .config-table {{ font-size: 12px; }}
  .config-table th {{ text-align: left; color: #888; font-weight: normal; padding-right: 12px; }}
  .tx-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  .tx-table th, .tx-table td {{ border-bottom: 1px solid #eee; padding: 6px 8px; text-align: left; }}
  .tx-table th {{ background: #f4f4f4; }}
  .chart {{ width: 100%; height: auto; max-width: 100%; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="panel">{config}</div>
<h2>Metrics</h2>
<div class="panel">{metrics}</div>
<h2>Charts</h2>
<div class="panel">{pv_chart}</div>
<div class="panel">{dd_chart}</div>
<h2>Transactions</h2>
<div class="panel">{transactions}</div>
</body>
</html>
"""


__all__ = ["write_run_html"]
