# sukoon-bt

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](.python-version)

Event-driven mutual fund backtesting CLI for the [Sukoon data API](https://github.com/AskMinto/sukoon-mcp).

> **Status:** **MVP complete (Phases 1-3)** of [the spec](docs/SPEC.md) — buy-and-hold + momentum backtests; full risk analytics (Sortino, alpha/beta/IR, XIRR, rolling); constraint-aware rebalancing (calendar + drift threshold); Indian capital-gains tax engine (STCG/LTCG, equity vs debt, pre/post-2023 debt rules, FY exemption tracking); grid-search optimisation; head-to-head compare; single-file HTML reports.

## What it does

`sukoon-bt` lets you research, simulate, and backtest mutual-fund strategies against ~14,000 Indian schemes using daily NAV history. Strategies are declared in YAML, executed by a deterministic event-driven engine, and exported as CSV/JSON. Layers (data, engine, strategy, portfolio, execution, tax, analytics, reporting) are independently pluggable via [`pluggy`](https://pluggy.readthedocs.io/).

The architectural rule (spec §3): **strategies emit signals only — the engine controls execution.** This makes runs deterministic, tax-aware, and safe to parallelise for parameter sweeps.

## Install

```bash
git clone https://github.com/AskMinto/sukoon-backtesting-engine.git
cd sukoon-backtesting-engine
uv sync                       # or: pip install -e ".[dev]"
sukoon-bt --version
```

Python 3.12+ is required.

## Quickstart

```bash
# Scaffold a strategy YAML.
sukoon-bt init buy_and_hold -o strategy.yaml

# Run the backtest. Outputs run.json + snapshots.csv + transactions.csv + report.html to ./out/.
sukoon-bt backtest strategy.yaml

# Re-render the saved JSON as a rich-formatted summary.
sukoon-bt report out/run.json

# Head-to-head comparison.
sukoon-bt compare a.yaml b.yaml

# Grid-search parameter sweep — leaderboard CSV/JSON in ./out/sweep/.
sukoon-bt optimize momentum.yaml \
    --param signal.params.lookback_days=30,60,90,180 \
    --param signal.params.top_n=2,3,5 \
    --rank sharpe
```

Set `MINTO_API_URL` to point at a non-default Sukoon API instance (the default is `https://api.minto.app`). Pass `--offline` to force cache-only reads.

## Strategy YAML

Buy-and-hold (simplest):

```yaml
name: Buy and Hold

capital:
  initial: 100000
  sip: 0

universe:
  funds:
    - "120503"          # Parag Parikh Flexi Cap

rebalance:
  frequency: never      # never | monthly | quarterly | yearly

period:
  start: 2018-01-01
  end: 2024-12-31
```

Top-N momentum over a category-based universe with SIP and threshold rebalancing:

```yaml
name: Top-3 Flexi-Cap Momentum

capital:
  initial: 100000
  sip: 10000

universe:
  category: "Flexi Cap"
  limit: 30             # cap search-result count (default 50)

signal:
  type: momentum
  params:
    lookback_days: 180
    top_n: 3

rebalance:
  frequency: monthly
  threshold: 0.10       # also rebalance if any held weight drifts > 10%

benchmark:
  id: "NIFTY 500"

period:
  start: 2018-01-01
  end: 2024-12-31
```

Built-in `signal.type` values: `equal_weight` (default), `buy_and_hold`, `momentum`. Third-party strategies plug in via [`pluggy`](https://pluggy.readthedocs.io/) — see `sukoon_bt/plugins/__init__.py` for the entry-point contract.

## Outputs

Every run writes to `<output-dir>/`:

| File | Contents |
| --- | --- |
| `run.json` | Engine version, config + config hash (sha256), performance metrics, drawdown stats, snapshots, full transaction ledger. |
| `snapshots.csv` | Daily `{date, portfolio_value, cash, holdings_value, drawdown}`. |
| `transactions.csv` | Every booked `{id, date, fund_id, type, units, nav, amount, fees, taxes}`. |
| `report.html` | Self-contained HTML report with SVG charts (portfolio value, drawdown), metrics panel, and transactions table. Zero JS, opens offline. |

## Indian taxes

Sells are taxed automatically when fund metadata is available:

- **Equity** (Flexi Cap, Large Cap, ELSS, etc.): STCG 15% on holdings < 365 days; LTCG 10% on holdings ≥ 365 days with ₹1L exemption per fiscal year.
- **Debt** (Liquid, Gilt, Corporate Bond, etc.):
  - Pre-2023 lots (purchase < 2023-04-01): STCG at slab rate, LTCG 20% with optional indexation.
  - Post-2023 lots: all gains slab-taxed regardless of holding period.

Slab rate and indexation factor are configurable on the `TaxEngine`. The Indian fiscal year exemption is tracked across multiple sales in the same year automatically.

Two runs of the same config against the same data produce a byte-identical `config_hash` and identical numerical outputs (spec §22 determinism).

## Architecture

See [`docs/SPEC.md`](docs/SPEC.md) for the full engineering specification. Section numbers in commit messages and PRs (e.g. "spec §10") refer to that document.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Tests are required (`pytest -q`). At least one approving review is required before merge; admins can self-merge once tests pass.

## License

[MIT](LICENSE)
