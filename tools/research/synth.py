#!/usr/bin/env python3
"""Build a synthesis prompt from reader notes + probe narrative and run it through ZenMux.
Usage: synth.py <provider|cross> --model anthropic/claude-opus-5 [--protocol anthropic] [--max-tokens 40000] [--dry]
Writes prompt to $S/plan/synth_<name>.prompt.md and the model output to /home/user/api/docs/research/<name>.md
"""
import argparse, glob, json, os, subprocess, sys
S = os.environ.get('U3_SCRATCH', os.path.expanduser('~/.u3-scratch'))
REPO = '/home/user/api'
CONTEXT = open(f'{S}/research/READER_INSTRUCTIONS.md').read().split('SCRATCHPAD')[0]
PREFIX = {'opticodds': 'oo-', 'oddspapi': 'op-', 'sharpsports': 'ss-'}

SPEC_INSTR = """You are the {provider} synthesis writer for an engineering team. Below are (A) exhaustive notes written by readers who read every page of the {provider} documentation, and (B) a live-probe narrative from running the real API with our trial key, plus (C) reader JSON summaries. Write THE definitive engineering spec for this provider, from which our ingestion code will be generated.
Required sections, in this order:
1. Product & access summary: what we have, observed entitlements (from the probe), auth, base URLs, rate limits with exact numbers, pagination, error formats.
2. Complete endpoint catalogue: a table per endpoint family (method, path, purpose, required/optional params with types and enums, pagination, rate limit, live status observed) — every endpoint in the docs, nothing omitted.
3. Data model & ID schemes: every entity with exact field names/types, ID formats with real examples, status/settlement enums, timestamp units and clock semantics.
4. Streaming: protocol, auth, subscribe/filter model, every message type with exact payload shape, ordering/cursor/resume/replay/heartbeat/close-code semantics, observed throughput, compression options.
5. Historical data: endpoints, depth/retention, granularity, observed limits.
6. Cross-provider identifiers present (every field that references another vendor, with examples).
7. Latency / freshness / staleness semantics: quote exact doc language and observed numbers; which fields to use for per-quote latency estimation.
8. Edge-relevant facts for arbitrage / market making (limits, order-book depth, sharp books, line origin, opening/closing, CLV, settlement timing, suspension flags, in-play latency).
9. Gotchas, doc-vs-live contradictions, and open questions (deduplicated from the notes; mark which were resolved by the probe).
10. Recommended ingestion strategy for this provider: which endpoints/channels, polling cadence within rate limits, backfill plan, what to store raw vs normalized, failure/resume handling.
Rules: be exhaustive and precise; prefer tables and exact field lists over prose; never invent fields — if unsure say so; keep real example IDs; length 1000-2500 lines is expected. Output ONLY the markdown document (no preamble)."""

CROSS_INSTR = """You are writing the cross-provider mapping and canonical data model document for an engineering team building a low-latency sports/prediction-market trading data platform. Inputs below: the three provider specs (OpticOdds v3, OddsPapi v5, SharpSports) and the cross-provider live join probe narrative.
Write docs/research/cross-provider-mapping.md covering, with tables and exact field names:
1. Identity resolution strategy: sports; leagues/tournaments; fixtures (primary: OddsPapi externalProviders.opticoddsId; secondary: rotation numbers, SharpSports oddsjamId == OpticOdds game_id, sportradar ids, betradar ids, team-name+start-time fuzzy match; theOddsApiId only as a foreign reference), teams/participants, players, sportsbooks/bookmakers (a normalized book registry table with each provider's slug/id side by side incl. exchanges and prediction markets), markets (a canonical market taxonomy: moneyline/spread/total/team total/period markets/player props/futures/prediction-market yes-no, with each provider's naming, line/points representation, player id representation, alternate-line handling), selections/outcomes (how each provider keys an outcome and the canonical outcome key).
2. Price semantics: decimal/american, lay/back/order-book depth, limits, is_main/mainLine, active/suspended/stale flags, timestamps and clocks per provider, and how to compute per-quote latency.
3. Recommended canonical schema (tables with columns and types) for: sports, leagues, fixtures, fixture_xref (provider ids), teams, players, books, book_xref, markets, market_xref, quotes (tick stream), quote_snapshots, order_book_levels, results/settlements, injuries, historical player/team stats, plus the raw archive layout (object storage path scheme) and ClickHouse table engine/ordering suggestions.
4. Mapping QA: coverage metrics to compute continuously, unmapped-entity queues, and resolution procedures.
5. Known gaps/ambiguities and how to resolve them operationally.
Output ONLY the markdown document."""


def gather(provider):
    parts = []
    for f in sorted(glob.glob(f'{S}/research/notes/{PREFIX[provider]}*.md')):
        parts.append(f'\n\n===== READER NOTES: {os.path.basename(f)} =====\n' + open(f, encoding='utf-8', errors='ignore').read())
    for p in sorted(glob.glob(f'{S}/research/probes/{provider}*.md')):
        parts.append(f'\n\n===== LIVE PROBE: {os.path.basename(p)} =====\n' + open(p, encoding='utf-8', errors='ignore').read()[:400000])
    for f in sorted(glob.glob(f'{S}/research/summaries/{PREFIX[provider]}*.json')) + [f'{S}/research/summaries/probe-{provider}.json']:
        if os.path.exists(f):
            parts.append(f'\n\n===== JSON SUMMARY: {os.path.basename(f)} =====\n' + open(f, encoding='utf-8', errors='ignore').read()[:60000])
    return ''.join(parts)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('name'); ap.add_argument('--model', default='anthropic/claude-opus-5')
    ap.add_argument('--protocol', default='anthropic'); ap.add_argument('--max-tokens', type=int, default=40000); ap.add_argument('--dry', action='store_true')
    ap.add_argument('--reasoning', default=None)
    a = ap.parse_args()
    if a.name == 'cross':
        body = ''.join(f'\n\n===== PROVIDER SPEC: {p} =====\n' + open(f'{REPO}/docs/research/{p}.md').read() for p in PREFIX)
        cp = f'{S}/research/probes/cross.md'
        body += '\n\n===== CROSS JOIN PROBE =====\n' + (open(cp).read() if os.path.exists(cp) else '(not available)')
        instr = CROSS_INSTR
    else:
        body = gather(a.name); instr = SPEC_INSTR.format(provider=a.name)
    prompt = CONTEXT + '\n\n' + instr + '\n\n' + body
    pp = f'{S}/plan/synth_{a.name}.prompt.md'; open(pp, 'w').write(prompt)
    print(f'prompt {len(prompt)} chars (~{len(prompt)//4} tokens) -> {pp}', file=sys.stderr)
    if a.dry:
        return
    os.makedirs(f'{REPO}/docs/research', exist_ok=True)
    out_md = f'{REPO}/docs/research/{a.name}.md'
    cmd = [sys.executable, f'{S}/tools/zenmux_chat.py', '--model', a.model, '--protocol', a.protocol, '--user', pp, '--out', f'{S}/plan/synth_{a.name}.json',
           '--max-tokens', str(a.max_tokens), '--timeout', '3000', '--label', f'synth_{a.name}', '--min-flows', '80']
    if a.reasoning:
        cmd += ['--reasoning', a.reasoning]
    with open(out_md, 'w') as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)
    print(r.stderr[-600:], file=sys.stderr)
    print(f'wrote {out_md} ({os.path.getsize(out_md)} bytes) rc={r.returncode}', file=sys.stderr)
    sys.exit(r.returncode)


if __name__ == '__main__':
    main()
