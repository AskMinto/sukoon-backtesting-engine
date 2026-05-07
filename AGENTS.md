# sukoon-bt — Agent Reference

Everything an AI coding agent needs to work on this repo without asking questions.

---

## What this is

`sukoon-bt` is an event-driven mutual-fund backtesting CLI for the [Sukoon data API](https://api.minto.app) (also known as the Minto data API — sister project at [`AskMinto/minto-data-api`](https://github.com/AskMinto/minto-data-api)). Strategies are declared in YAML, executed by a deterministic engine, and exported as CSV/JSON. Phase 1 (skeleton + buy-and-hold) is in `main`; Phase 2 (momentum + full analytics) and Phase 3 (taxes + optimisation + HTML reporting) are next.

The core architectural rule (spec §3): **strategies emit signals only — the engine controls execution.** Never break this. It's what keeps runs deterministic, tax-aware, and parallelisable.

---

## Repo layout

```
sukoon-backtesting-engine/
├── pyproject.toml          Python 3.12+, deps + dev extras + ruff/mypy/pytest config
├── README.md               User-facing quickstart
├── CONTRIBUTING.md         Branch workflow + style rules
├── AGENTS.md               This file
├── docs/SPEC.md            Section-numbered engineering spec (referenced as "spec §N")
├── examples/               Sample strategy YAMLs
├── tests/
│   ├── fixtures/*.parquet  Committed deterministic NAV fixtures (golden tests)
│   └── test_*.py           pytest modules — one per package
└── sukoon_bt/
    ├── cli/                typer + rich CLI: app.py + commands/{init,backtest,report}.py
    ├── core/               events.py, scheduler.py, engine.py, context.py
    ├── data/               models.py (pydantic v2), client.py (httpx async),
    │                       cache.py (parquet+diskcache), repository.py (facade)
    ├── portfolio/          portfolio.py, holdings.py, transactions.py, accounting.py
    ├── strategies/         base.py (Strategy ABC), buy_and_hold.py — momentum lands in Phase 2
    ├── execution/          broker.py, fills.py, rebalance.py — Phase 2 stubs
    ├── tax/                lots.py (active, FIFO), engine.py + india.py — Phase 3 stubs
    ├── analytics/          metrics.py (CAGR/Sharpe), drawdown.py, rolling.py — Phase 2 fills out
    ├── reporting/          json.py, csv.py, html.py — html ships in Phase 3
    ├── plugins/            pluggy registry — wiring lands in Phase 2
    └── utils/              logging.py (JSON-line), hashing.py, dates.py
```

---

## Tech stack (locked)

| Concern | Library | Why |
| --- | --- | --- |
| CLI | `typer` + `rich` | spec §4 |
| Validation | `pydantic` v2 | All cross-module data crosses pydantic boundaries |
| DataFrame | `polars` | Internal computation only — never `pandas` for new code (spec §21) |
| HTTP | `httpx` async + `tenacity` retries | spec §7 |
| Serialisation | `orjson` | Sorted-key serialisation for deterministic config hashes |
| Cache | `diskcache` + parquet | spec §7 |
| Plugins | `pluggy` | spec §17 |
| Tests | `pytest` + `pytest-asyncio` + `respx` | respx mocks the data client |

`pandas` is in `dependencies` only because the upstream spec mentioned it; do not introduce new pandas usage. Use polars.

---

## Architectural rules — never break these

1. **Strategies emit signals only.** Strategies never call `Portfolio.buy()`, `Portfolio.sell()`, or mutate cash. They implement the four `Strategy` ABC hooks (`initialize`, `on_day`, `generate_signals`, `target_allocations`) and that's it. The engine reconciles target weights to current holdings.
2. **Engine controls execution.** All bookings happen inside `Engine.run()`. If you find yourself adding side-effects elsewhere, you're doing it wrong.
3. **Cross-module data is pydantic.** Raw `dict[str, Any]` payloads stay inside one module (e.g. inside `data/client.py` until they're parsed into `Fund` / `NAVPoint`).
4. **No mutable global state.** Every dependency is passed in. The engine, repository, cache, and CLI are all explicit.
5. **Determinism (spec §22).** Every run JSON carries `engine_version` + 16-char sha256 `config_hash`. Two runs of the same config + same data must produce byte-identical numbers. The CLI test enforces this. Don't introduce wall-clock-dependent randomness; if you need RNG, seed it from the config hash.
6. **Fail fast (spec §24).** Invalid YAML, missing NAV, oversell, negative units → raise. No silent fallbacks.

---

## Data layer — how to talk to the API

The Sukoon API is the data source for everything. Endpoints (verified against `~/minto-data-api/mcp/src/`):

| Method | URL | Returns |
| --- | --- | --- |
| `GET /v1/funds/{scheme_code}/nav?from=&to=` | `[{nav_date, nav}]` |
| `GET /v1/funds/{scheme_code}` | `{scheme_code, scheme_name, amc_name, fund_type, ter, ...}` |
| `GET /v1/funds?q=&type=&amc=&page=&pageSize=` | `{funds, total, page, pageSize}` |
| `GET /v1/benchmarks/{url-encoded-name}?from=&to=` | `{index, data: [{tri_date, tri_value}]}` |

- Base URL: `MINTO_API_URL` env var (default `https://api.minto.app`).
- Auth: none.
- Date format: ISO `YYYY-MM-DD`.
- The TS MCP server lives in `~/minto-data-api/mcp/`; if a new tool exists there but isn't mapped in `data/client.py`, add the method.
- Always go through `FundRepository`, never raw `SukoonDataClient`. Repository handles caching + offline mode.

Universe: 14,247 MF schemes (numeric codes) + 57 SIF strategies (codes like `"SIF-23"`) + GIFT City funds. Benchmarks: 11 NIFTY TRI indices.

---

## Cache

`~/.sukoon_bt/cache/` (overridable per `CacheBundle` instance):
- `ts/nav/<scheme_code>.parquet` + diskcache index — 24h TTL.
- `ts/benchmark/<url-safe-name>.parquet` + diskcache index — 24h TTL.
- `metadata/` (diskcache) — 7d TTL for Fund objects.

When testing without the network: pre-seed `CacheBundle.nav.put(...)` and pass `offline=True` to `FundRepository`. See `tests/test_cli_backtest.py` for the pattern.

---

## Commit + branch workflow

- Branch off `main`. Names like `feat/momentum-strategy`, `fix/cache-ttl-clamp`.
- Commit incrementally — one logical change per commit; tree must be working + tests green at every commit.
- Commit body should reference spec sections (`spec §10`).
- Open a PR against `main`. Branch protection requires 1 review + (future) CI; admins bypass.
- PR template (`.github/pull_request_template.md`) requires Summary / Spec reference / Changes / Test plan.

Co-authoring footer (when committing as Claude):
```
Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## Tests

- All tests live in `tests/`, one module per package (`test_models.py`, `test_engine.py`, etc.).
- Run: `pytest -q` (with `.venv` activated, or `uv run pytest`).
- **Golden tests** use committed `tests/fixtures/*.parquet` files — never regenerate them. The `.gitignore` has `!tests/fixtures/*.parquet` to allow these specifically.
- **Property tests** (spec §25): no negative units, no negative cash, weights sum to 1.0. Add these for any new strategy.
- HTTP calls in tests must use `respx` to mock — never hit the real API in CI.

---

## Phase progression

Status as of `main`:

- **Phase 1 ✅** — Skeleton, MCP/REST integration with cache, deterministic buy-and-hold backtest, JSON+CSV reporting, golden tests.
- **Phase 2 ✅** — Momentum strategy (lookback + top-N), full rebalance constraints (min trade, tolerance band, threshold-driven drift rebalance), full analytics (Sortino, alpha/beta/IR/TE, XIRR, rolling CAGR/Sharpe/drawdown), pluggy plugin registry, category-based universe via `search_funds`.
- **Phase 3 ✅** — Indian tax engine (STCG/LTCG with FY exemption tracking, equity vs debt classification, pre/post-2023 debt rules with optional indexation), tax-on-sale wired into the engine + ledger, `sukoon-bt optimize` grid search, `sukoon-bt compare` head-to-head, single-file HTML reports with hand-rolled SVG charts.

The MVP (spec §29 Definition of Done) is complete. Future expansions per spec §30 — ETFs/stocks, live execution, AI-generated strategies, distributed backtesting, browser dashboard — go in new feature branches.

---

## Don'ts (spec §28)

- ❌ Tightly couple strategies to engine
- ❌ Use mutable global state
- ❌ Embed tax logic inside strategies (lives in `tax/`)
- ❌ Use `pandas` for new internal computation — use `polars`
- ❌ Store results only in memory — always write to `out/` artefacts
- ❌ Skip the `config_hash` stamp on outputs — determinism is a feature

---

## Useful one-liners

```bash
# Full test suite
pytest -q

# Lint
ruff check .

# Format
ruff format .

# CLI smoke
sukoon-bt --version && sukoon-bt --help

# End-to-end (needs network or pre-seeded cache)
sukoon-bt init buy_and_hold -o /tmp/x.yaml && sukoon-bt backtest /tmp/x.yaml -o /tmp/out
sukoon-bt report /tmp/out/run.json
```

---

## Sister projects

- [`AskMinto/minto-data-api`](https://github.com/AskMinto/minto-data-api) — the data source. Read its `AGENTS.md` and `MATH.md` for the metric formulas the analytics layer must match.
- [`AskMinto/sukoon-mcp`](https://github.com/AskMinto/sukoon-mcp) — public MCP wrapper around the same data API.
