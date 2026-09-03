from __future__ import annotations

import pytest

from u3ingest.canonical.models import Quote
from u3ingest.pricing.board import Board
from u3ingest.pricing.consensus import ConsensusConfig, FairValue, fair_value
from u3ingest.pricing.devig import additive, multiplicative, power, shin


def test_devig_even_two_way():
    prices = [1.91, 1.91]
    assert multiplicative(prices) == [0.5, 0.5]
    assert additive(prices) == [0.5, 0.5]


def test_devig_three_way_sums_to_one():
    prices = [1.50, 2.80, 6.00]
    for probs in (multiplicative(prices), additive(prices), power(prices), shin(prices)):
        assert abs(sum(probs) - 1.0) < 1e-9


def test_power_and_shin_reduce_longshot_vs_multiplicative():
    prices = [1.30, 5.20, 15.0]
    mult = multiplicative(prices)
    assert power(prices)[2] < mult[2]
    assert shin(prices)[2] < mult[2]


def test_consensus_weight_renormalization_on_drop():
    cfg = ConsensusConfig(weights={"a": 0.6, "b": 0.2, "c": 0.2}, min_providers=2)
    out = fair_value({"a": [2.0, 2.0], "b": [2.0, 2.0]}, cfg)
    assert out is not None
    assert out.weights == pytest.approx({"a": 0.75, "b": 0.25})


def test_consensus_gating_and_hysteresis():
    cfg = ConsensusConfig(weights={"a": 1.0, "b": 1.0}, mandatory={"a"}, min_providers=2, publish_min_diff_pct=1.0)
    assert fair_value({"b": [2.0, 2.0]}, cfg) is None
    assert fair_value({"a": [2.0, 2.0]}, cfg) is None

    old = FairValue(probabilities=[0.50, 0.50], books=["a", "b"], weights={"a": 0.5, "b": 0.5}, per_book_probs={})
    new_small = FairValue(probabilities=[0.505, 0.495], books=["a", "b"], weights={"a": 0.5, "b": 0.5}, per_book_probs={})
    new_big = FairValue(probabilities=[0.52, 0.48], books=["a", "b"], weights={"a": 0.5, "b": 0.5}, per_book_probs={})
    assert not new_small.changed_enough(old, cfg)
    assert new_big.changed_enough(old, cfg)


def _q(book: str, selection: str, price_dec: float, recv_ns: int) -> Quote:
    return Quote(
        recv_ns=recv_ns,
        provider="test",
        book_id=book,
        provider_book=book,
        fixture_id="fx1",
        provider_fixture_id="fx1",
        market="moneyline",
        period="full",
        selection=selection,
        line=None,
        price_dec=price_dec,
        price_us=None,
        is_main=True,
        active=True,
        limit_max=None,
        source_ts_ms=None,
        gateway_ts_ms=None,
        provider_market="moneyline",
        provider_selection=selection,
        provider_odd_id=f"{book}:{selection}",
    )


def test_board_grouping_and_positive_ev_edge(monkeypatch):
    board = Board(max_age_ms=1_000)
    now_ns = 10_000_000_000
    monkeypatch.setattr("u3ingest.pricing.board.time.time_ns", lambda: now_ns)

    board.ingest(_q("sharp", "home", 2.0, now_ns - 100_000_000))
    board.ingest(_q("sharp", "away", 2.0, now_ns - 100_000_000))
    board.ingest(_q("soft", "home", 2.2, now_ns - 2_500_000_000))
    board.ingest(_q("soft", "away", 1.7, now_ns - 2_500_000_000))

    mp = board.market_prices("fx1", "moneyline", "full", None)
    assert mp == {"sharp": [2.0, 2.0], "soft": [2.2, 1.7]}

    cfg = ConsensusConfig(weights={"sharp": 0.7, "soft": 0.3}, min_providers=2)
    edges = board.edges("fx1", "moneyline", "full", None, cfg)
    home_soft = next(e for e in edges if e.book_id == "soft" and e.outcome == "home")
    assert home_soft.expected_value > 0
    assert home_soft.stale
