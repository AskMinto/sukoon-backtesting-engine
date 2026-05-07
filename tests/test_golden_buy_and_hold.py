"""Golden buy-and-hold test against a fixed NAV fixture.

The fixture (``tests/fixtures/golden_nav_GOLD-001.parquet``) is 252
synthetic trading days at a deterministic 0.05% daily drift starting at
NAV 100.0. Closed-form expected values:

    final_nav  = 100.0 * 1.0005 ** 251     # 251 compounding steps
    final_value ≈ initial_capital * final_nav / 100.0

A monthly rebalance drives the engine to invest ~all initial capital
into fund GOLD-001 on the first trading day. Subsequent monthly
rebalances are no-ops (target weight is already 100%).

The test enforces the spec §22 determinism contract: same fixture +
same config → byte-identical numbers within float tolerance.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from sukoon_bt.core.engine import Engine, EngineConfig
from sukoon_bt.strategies.buy_and_hold import BuyAndHold

FIXTURE = Path(__file__).parent / "fixtures" / "golden_nav_GOLD-001.parquet"


def _load_fixture() -> pl.DataFrame:
    return pl.read_parquet(FIXTURE)


class TestGoldenBuyAndHold:
    def test_final_value_matches_closed_form(self) -> None:
        nav_df = _load_fixture()
        engine = Engine(
            strategy=BuyAndHold(["GOLD-001"]),
            nav_history={"GOLD-001": nav_df},
            config=EngineConfig(
                initial_capital=100_000.0,
                rebalance_frequency="monthly",
            ),
        )
        result = engine.run()
        snaps = result.portfolio.snapshots

        # Engine produced exactly one snapshot per trading day.
        assert len(snaps) == nav_df.height

        # First snapshot (day 0): all capital is still cash since the engine
        # rebalances at MARKET_OPEN before MARKET_CLOSE on the first day —
        # so portfolio_value should equal initial_capital.
        assert snaps[0].portfolio_value == pytest.approx(100_000.0, rel=1e-6)

        # Final NAV is 100 * 1.0005 ** 251 (251 compounding steps over
        # 252 emitted days). Since the engine bought on day 0 at NAV
        # 100 and the strategy is buy-and-hold, the final portfolio
        # value should track the NAV ratio almost exactly (modulo
        # residual cash from the integer-units approximation, which we
        # don't enforce — units are continuous floats here).
        first_nav = float(nav_df["nav"][0])
        final_nav = float(nav_df["nav"][-1])
        expected_final = 100_000.0 * final_nav / first_nav
        assert snaps[-1].portfolio_value == pytest.approx(expected_final, rel=1e-9)

    def test_no_negative_units_and_weights_sum_to_one(self) -> None:
        """Property test (spec §25): no negative balances; weights sum to 1."""
        nav_df = _load_fixture()
        engine = Engine(
            strategy=BuyAndHold(["GOLD-001"]),
            nav_history={"GOLD-001": nav_df},
            config=EngineConfig(initial_capital=100_000.0, rebalance_frequency="monthly"),
        )
        result = engine.run()
        for h in result.portfolio.holdings:
            assert h.units >= 0
            assert h.cost_basis >= 0
        for tx in result.portfolio.ledger:
            if tx.transaction_type.value in {"BUY", "SIP", "STP"}:
                assert tx.units > 0
            if tx.transaction_type.value in {"SELL", "SWP"}:
                assert tx.units < 0

        # Cash never goes negative.
        for s in result.portfolio.snapshots:
            assert s.cash >= -1e-6

        # BuyAndHold weights sum to exactly 1.0.
        weights = BuyAndHold(["A", "B", "C"]).target_allocations(None)  # type: ignore[arg-type]
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_deterministic_replay(self) -> None:
        """Two runs with the same fixture + config produce identical numbers."""
        nav_df = _load_fixture()

        def run_once() -> tuple[float, int, int]:
            engine = Engine(
                strategy=BuyAndHold(["GOLD-001"]),
                nav_history={"GOLD-001": nav_df},
                config=EngineConfig(
                    initial_capital=100_000.0, rebalance_frequency="monthly"
                ),
            )
            r = engine.run()
            return (
                r.portfolio.snapshots[-1].portfolio_value,
                len(r.portfolio.ledger),
                len(r.portfolio.snapshots),
            )

        a = run_once()
        b = run_once()
        assert a == b
