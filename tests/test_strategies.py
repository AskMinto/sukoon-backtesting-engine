"""Buy-and-hold strategy tests."""

from __future__ import annotations

import pytest

from sukoon_bt.strategies.buy_and_hold import BuyAndHold


class _DummyContext:
    """Minimal Context-shaped stand-in (BuyAndHold doesn't read it)."""


class TestBuyAndHold:
    def test_equal_weight_default(self) -> None:
        s = BuyAndHold(["A", "B", "C"])
        weights = s.target_allocations(_DummyContext())  # type: ignore[arg-type]
        assert sorted(weights) == ["A", "B", "C"]
        assert all(w == pytest.approx(1 / 3) for w in weights.values())
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_custom_weights_normalised(self) -> None:
        s = BuyAndHold(["A", "B"], weights=[3.0, 1.0])
        weights = s.target_allocations(_DummyContext())  # type: ignore[arg-type]
        assert weights["A"] == pytest.approx(0.75)
        assert weights["B"] == pytest.approx(0.25)
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_empty_universe_rejected(self) -> None:
        with pytest.raises(ValueError):
            BuyAndHold([])

    def test_mismatched_weights_rejected(self) -> None:
        with pytest.raises(ValueError):
            BuyAndHold(["A", "B"], weights=[1.0])

    def test_negative_weight_rejected(self) -> None:
        with pytest.raises(ValueError):
            BuyAndHold(["A", "B"], weights=[1.0, -1.0])

    def test_zero_weights_rejected(self) -> None:
        with pytest.raises(ValueError):
            BuyAndHold(["A", "B"], weights=[0.0, 0.0])

    def test_signals_match_targets(self) -> None:
        s = BuyAndHold(["A"])
        ctx = _DummyContext()
        assert s.generate_signals(ctx) == s.target_allocations(ctx)  # type: ignore[arg-type]
