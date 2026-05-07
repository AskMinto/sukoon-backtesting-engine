# sukoon-bt

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](.python-version)

Event-driven mutual fund backtesting CLI for the [Sukoon data API](https://github.com/AskMinto/sukoon-mcp).

> **Status:** Phase 2 (deliverables 1–4 of [the spec](docs/SPEC.md)) — working CLI, MCP/REST data layer with cache, deterministic buy-and-hold + momentum backtests, full risk analytics (Sortino, alpha/beta/IR, XIRR, rolling metrics), constraint-aware rebalancing (calendar + drift threshold + min trade size + tolerance), pluggy-based strategy plugins, category-based universe selection. Phase 3 (taxes + optimisation + HTML reporting) ships next.

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
# 1. Scaffold a strategy YAML.
sukoon-bt init buy_and_hold -o strategy.yaml

# 2. Run the backtest. Outputs CSV + JSON to ./out/.
sukoon-bt backtest strategy.yaml

# 3. Re-render the saved JSON as a rich-formatted summary.
sukoon-bt report out/run.json
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

Two runs of the same config against the same data produce a byte-identical `config_hash` and identical numerical outputs (spec §22 determinism).

## Architecture

See [`docs/SPEC.md`](docs/SPEC.md) for the full engineering specification. Section numbers in commit messages and PRs (e.g. "spec §10") refer to that document.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Tests are required (`pytest -q`). At least one approving review is required before merge; admins can self-merge once tests pass.

## License

[MIT](LICENSE)
