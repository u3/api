# Pricing

`u3ingest/pricing` converts bookmaker prices into consensus fair probabilities.

## De-vig methods

Given decimal odds `d_i`, implied probabilities are `q_i = 1 / d_i`.

- **Multiplicative**: `p_i = q_i / sum(q)`.
- **Additive**: subtract equal margin share `m = (sum(q)-1)/n`, clip, then renormalize.
- **Power**: find `k` such that `sum(q_i^k)=1`, then `p_i = q_i^k`.
- **Shin (1993)**: solve insider parameter `z` and compute `p_i(z)`; renormalize.

Helpers also provide decimal/American conversions consistent with canonical model utilities.

## Consensus and board

`consensus.fair_value(...)` de-vigs per book, applies provider weights (renormalized over currently available books),
and enforces mandatory-provider and minimum-provider gates.

`Board` keeps the latest active quote per `(fixture, market, period, line, selection, book)`, groups outcomes into canonical
order, builds per-book market prices, computes fair values, and emits per-book `Edge` rows with EV (`p * price - 1`) and stale flags.
