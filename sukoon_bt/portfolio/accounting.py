"""Accounting helpers — currency rounding and percentage math.

Kept as standalone helpers so the Portfolio class stays focused on
booking semantics. Spec §10 doesn't mandate fixed-point arithmetic
yet; stay in float64 and clamp residual rounding noise where it
matters (Holding.remove_units already does this).
"""

from __future__ import annotations

import math


def round_currency(amount: float, decimals: int = 2) -> float:
    return round(amount, decimals)


def is_close(a: float, b: float, tol: float = 1e-9) -> bool:
    return math.isclose(a, b, abs_tol=tol)


__all__ = ["is_close", "round_currency"]
