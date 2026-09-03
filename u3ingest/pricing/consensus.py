from __future__ import annotations

from dataclasses import dataclass, field

from . import devig


@dataclass(slots=True)
class ConsensusConfig:
    weights: dict[str, float]
    mandatory: set[str] = field(default_factory=set)
    min_providers: int = 2
    method: str = "multiplicative"
    publish_min_diff_pct: float = 0.0


@dataclass(slots=True)
class FairValue:
    probabilities: list[float]
    books: list[str]
    weights: dict[str, float]
    per_book_probs: dict[str, list[float]]

    def changed_enough(self, previous: FairValue | None, cfg: ConsensusConfig) -> bool:
        if previous is None:
            return True
        if len(previous.probabilities) != len(self.probabilities):
            return True
        thresh = cfg.publish_min_diff_pct / 100.0
        return any(abs(a - b) >= thresh for a, b in zip(self.probabilities, previous.probabilities, strict=True))


_METHODS = {
    "multiplicative": devig.multiplicative,
    "additive": devig.additive,
    "power": devig.power,
    "shin": devig.shin,
}


def fair_value(quotes_by_book: dict[str, list[float]], cfg: ConsensusConfig) -> FairValue | None:
    method = _METHODS.get(cfg.method)
    if method is None:
        raise ValueError(f"unknown devig method: {cfg.method}")

    per_book_probs: dict[str, list[float]] = {}
    n_outcomes: int | None = None

    for book, prices in quotes_by_book.items():
        try:
            probs = method(prices)
        except ValueError:
            continue
        if n_outcomes is None:
            n_outcomes = len(probs)
        if len(probs) != n_outcomes:
            continue
        per_book_probs[book] = probs

    present = set(per_book_probs)
    if not cfg.mandatory.issubset(present):
        return None
    if len(per_book_probs) < cfg.min_providers:
        return None

    raw_weights = {book: float(cfg.weights.get(book, 0.0)) for book in per_book_probs}
    raw_weights = {book: w for book, w in raw_weights.items() if w > 0.0}
    if len(raw_weights) < cfg.min_providers:
        return None

    wsum = sum(raw_weights.values())
    weights = {book: w / wsum for book, w in raw_weights.items()}

    n = len(next(iter(per_book_probs.values())))
    out = [0.0] * n
    for book, w in weights.items():
        probs = per_book_probs[book]
        for i, p in enumerate(probs):
            out[i] += w * p

    s = sum(out)
    probs = [x / s for x in out]
    books = sorted(weights)
    return FairValue(probabilities=probs, books=books, weights={b: weights[b] for b in books}, per_book_probs=per_book_probs)
