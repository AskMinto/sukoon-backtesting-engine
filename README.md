# sukoon-bt

Event-driven mutual fund backtesting CLI for the Sukoon data API.

> **Status:** early development. Phase 1 in progress — see [`docs/SPEC.md`](docs/SPEC.md) for the full engineering specification.

## What it does

`sukoon-bt` lets you research, simulate, and backtest mutual-fund strategies against 14,000+ Indian schemes (and 11 NIFTY TRI benchmarks) using daily NAV history from the [Sukoon data API](https://api.minto.app). Strategies are declared in YAML, executed by a deterministic event-driven engine, and reported as CSV/JSON/HTML.

## Quickstart

```bash
# Coming soon — see SPEC §16 for planned commands:
sukoon-bt init momentum            # scaffold a strategy YAML
sukoon-bt backtest strategy.yaml   # run a deterministic backtest
sukoon-bt compare a.yaml b.yaml    # head-to-head comparison
sukoon-bt optimize strategy.yaml   # parameter sweep / grid search
sukoon-bt report results.json      # render an HTML report
```

## Architecture

Strict separation between data, engine, strategy, portfolio, execution, tax, analytics, and reporting layers — every layer is independently pluggable via [`pluggy`](https://pluggy.readthedocs.io/). Strategies emit signals and target weights only; the engine controls execution.

See [`docs/SPEC.md`](docs/SPEC.md) for the full design.

## License

[MIT](LICENSE)
