"""De-vig helpers.

Given decimal prices :math:`d_i > 1`, implied probabilities are :math:`q_i = 1 / d_i`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from u3ingest.canonical.models import american_to_decimal as _american_to_decimal
from u3ingest.canonical.models import decimal_to_american as _decimal_to_american

_EPS = 1e-12


def _validate_prices(prices: Sequence[float]) -> list[float]:
    ps = [float(p) for p in prices]
    if not ps:
        raise ValueError("prices must be non-empty")
    if any(p <= 1.0 or not math.isfinite(p) for p in ps):
        raise ValueError("all prices must be finite decimal odds > 1")
    return ps


def implied(prices: Sequence[float]) -> list[float]:
    """Return implied probabilities :math:`q_i = 1 / d_i`."""
    ps = _validate_prices(prices)
    return [1.0 / p for p in ps]


def overround(prices: Sequence[float]) -> float:
    r"""Return market overround :math:`\sum_i q_i - 1`."""
    return sum(implied(prices)) - 1.0


def multiplicative(prices: Sequence[float]) -> list[float]:
    r"""Normalize implied probabilities: :math:`p_i = q_i / \sum_j q_j`."""
    q = implied(prices)
    s = sum(q)
    return [x / s for x in q]


def additive(prices: Sequence[float]) -> list[float]:
    r"""Equal-share subtraction: :math:`p_i \propto \max(\epsilon, q_i - m)` where :math:`m = (\sum q - 1)/n`."""
    q = implied(prices)
    margin_share = (sum(q) - 1.0) / len(q)
    adjusted = [max(_EPS, x - margin_share) for x in q]
    s = sum(adjusted)
    return [x / s for x in adjusted]


def power(prices: Sequence[float], *, tol: float = 1e-12, max_iter: int = 200) -> list[float]:
    r"""Power de-vig: find :math:`k` such that :math:`\sum_i q_i^k = 1`, then :math:`p_i = q_i^k`."""
    q = implied(prices)

    def f(k: float) -> float:
        return sum(x**k for x in q) - 1.0

    lo, hi = 0.0, 1.0
    while f(hi) > 0.0:
        hi *= 2.0
        if hi > 1e6:
            break

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        val = f(mid)
        if abs(val) < tol:
            lo = hi = mid
            break
        if val > 0.0:
            lo = mid
        else:
            hi = mid

    k = (lo + hi) / 2.0
    probs = [x**k for x in q]
    s = sum(probs)
    return [x / s for x in probs]


def shin(prices: Sequence[float], *, tol: float = 1e-12, max_iter: int = 200) -> list[float]:
    r"""Shin (1993) model.

    With implied probabilities :math:`q_i` and insider share :math:`z \in [0, 1)`,

    .. math::

       p_i(z) = \frac{\sqrt{z^2 + 4(1-z)\,q_i^2 / \sum_j q_j} - z}{2(1-z)}

    Solve :math:`\sum_i p_i(z) = 1` by bisection on :math:`z`.
    """
    q = implied(prices)
    qsum = sum(q)

    def probs_for(z: float) -> list[float]:
        denom = 2.0 * (1.0 - z)
        return [(math.sqrt(z * z + 4.0 * (1.0 - z) * (x * x) / qsum) - z) / denom for x in q]

    def f(z: float) -> float:
        return sum(probs_for(z)) - 1.0

    lo, hi = 0.0, 1.0 - 1e-12
    flo, fhi = f(lo), f(hi)
    if flo <= 0.0:
        probs = probs_for(lo)
    elif fhi >= 0.0:
        probs = multiplicative(prices)
    else:
        for _ in range(max_iter):
            mid = (lo + hi) / 2.0
            fm = f(mid)
            if abs(fm) < tol:
                lo = hi = mid
                break
            if fm > 0.0:
                lo = mid
            else:
                hi = mid
        probs = probs_for((lo + hi) / 2.0)

    s = sum(probs)
    return [x / s for x in probs]


def to_decimal(prob: float) -> float:
    """Convert probability to decimal odds: :math:`d = 1 / p`."""
    p = float(prob)
    if not (0.0 < p < 1.0):
        raise ValueError("probability must be in (0, 1)")
    return round(1.0 / p, 6)


def to_american(prob: float) -> int:
    """Convert probability to American odds via decimal odds."""
    out = decimal_to_american(to_decimal(prob))
    if out is None:
        raise ValueError("could not convert probability to American odds")
    return out


def american_to_decimal(a: float | int | None) -> float | None:
    """Convert American odds to decimal odds (same behavior as canonical models)."""
    return _american_to_decimal(a)


def decimal_to_american(d: float | None) -> int | None:
    """Convert decimal odds to American odds (same behavior as canonical models)."""
    return _decimal_to_american(d)
