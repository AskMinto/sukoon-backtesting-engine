# Contributing to sukoon-bt

## Development setup

```bash
git clone https://github.com/AskMinto/sukoon-backtesting-engine.git
cd sukoon-backtesting-engine
uv sync                    # or: pip install -e ".[dev]"
pytest                     # run the test suite
sukoon-bt --help           # confirm CLI loads
```

Python 3.12+ is required.

## Workflow

1. Branch off `main` (e.g. `feat/momentum-strategy`, `fix/cache-ttl`).
2. Commit incrementally — each commit should leave the tree in a working state.
3. Open a PR against `main`. The PR description should reference the spec section it implements.
4. CI must be green. At least one approving review is required before merge (repo admins can bypass when CI is green).

## Code style

- `ruff` for lint + format. Run `ruff check . && ruff format .` before pushing.
- Pydantic v2 for all data models. No `dict[str, Any]` payloads at module boundaries.
- Polars for internal computation (spec §21). Avoid per-row Python loops.
- Strategies emit signals only — they never call execution or accounting directly (spec §3).

## Testing

- Unit tests for pure logic (tax calculations, rebalance math, momentum ranking).
- Golden tests use fixed historical NAV fixtures committed under `tests/fixtures/`.
- Property tests must enforce invariants: no negative units, allocations sum to 1.

## Architecture reference

See [`docs/SPEC.md`](docs/SPEC.md) for the full engineering specification. Section numbers in commit messages and PR descriptions refer to that document.
