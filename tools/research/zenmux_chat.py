#!/usr/bin/env python3
"""ZenMux helper using the two keys in tandem:
  - ZENMUX_API_KEY      (sk-ss-, Ultra Builder subscription) -> inference (OpenAI chat or Anthropic messages protocol)
  - ZENMUX_PLATFORM_API (sk-mg-, Management API key)          -> quota gate (5h/7d windows), cost/latency ledger via /management/generation

Usage: zenmux_chat.py --model openai/gpt-5.6-sol --user prompt.md --out out.json [--system sys.md] [--search low|medium|high]
       [--max-tokens 16000] [--reasoning low|medium|high|xhigh] [--protocol openai|anthropic] [--min-flows 60] [--rpm 10]
Writes JSON {model, content, annotations, usage, cost_usd, flows_used, elapsed_s, generation_id} to --out; prints content to stdout.
Ledger appended to $ZENMUX_LEDGER (default: <scratchpad>/plan/zenmux_ledger.jsonl).
"""
import argparse, fcntl, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

SCRATCH = os.environ.get('U3_SCRATCH', os.path.expanduser('~/.u3-scratch'))
MGMT = 'https://zenmux.ai/api/v1/management'


def key(name):
    return ''.join(os.environ.get(name, '').split())


def http(url, headers, body=None, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={**headers, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.load(r)


def mgmt(path):
    mk = key('ZENMUX_PLATFORM_API')
    if not mk:
        return None
    try:
        _, d = http(f'{MGMT}/{path}', {'Authorization': f'Bearer {mk}'}, timeout=20)
        return d.get('data') if d.get('success') else None
    except Exception as e:  # noqa
        print(f'[mgmt {path}] {type(e).__name__}: {e}', file=sys.stderr)
        return None


def quota_gate(min_flows, max_wait=3600):
    """Block until the 5h window has at least min_flows remaining (uses management key)."""
    waited = 0
    while True:
        d = mgmt('subscription/detail')
        if not d:
            return None
        q5, q7 = d.get('quota_5_hour', {}), d.get('quota_7_day', {})
        rem5, rem7 = q5.get('remaining_flows', 1e9), q7.get('remaining_flows', 1e9)
        if rem5 >= min_flows and rem7 >= min_flows:
            return d
        reset = q5.get('resets_at') if rem5 < min_flows else q7.get('resets_at')
        try:
            secs = (datetime.fromisoformat(reset.replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds()
        except Exception:  # noqa
            secs = 300
        secs = max(30, min(secs + 5, max_wait - waited))
        print(f'[quota] 5h remaining {rem5:.1f} / 7d remaining {rem7:.1f} flows < {min_flows}; waiting {secs:.0f}s for reset {reset}', file=sys.stderr)
        if waited >= max_wait:
            print('[quota] max wait exceeded; proceeding anyway', file=sys.stderr)
            return d
        time.sleep(secs); waited += secs


def rpm_throttle(rpm):
    """Cross-process token bucket: at most `rpm` request starts per rolling 60s (subscription plan is 10-15 RPM)."""
    path = os.path.join(SCRATCH, 'plan', '.zenmux_rpm.lock')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    while True:
        with open(path, 'a+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try:
                stamps = [float(x) for x in f.read().split() if x]
            except ValueError:
                stamps = []
            now = time.time()
            stamps = [s for s in stamps if now - s < 60]
            if len(stamps) < rpm:
                stamps.append(now)
                f.seek(0); f.truncate(); f.write(' '.join(f'{s:.3f}' for s in stamps))
                fcntl.flock(f, fcntl.LOCK_UN)
                return
            wait = 60 - (now - min(stamps)) + 0.5
            fcntl.flock(f, fcntl.LOCK_UN)
        time.sleep(max(1, wait))


def call_with_retries(url, headers, body, timeout, rpm):
    last_err = None
    for attempt in range(6):
        rpm_throttle(rpm)
        try:
            return http(url, headers, body, timeout)[1], None
        except urllib.error.HTTPError as e:
            txt = e.read()[:2000].decode(errors='ignore')
            last_err = f'HTTP {e.code}: {txt}'
            if e.code == 429:
                time.sleep(20 * (attempt + 1)); continue
            if e.code == 402 and 'quote_exceeded' in txt:
                quota_gate(1); continue
            if e.code in (500, 502, 520, 524):
                time.sleep(10 * (attempt + 1)); continue
            return None, last_err
        except Exception as e:  # noqa
            last_err = f'{type(e).__name__}: {e}'
            time.sleep(10 * (attempt + 1))
    return None, last_err


def ledger_write(rec):
    path = os.environ.get('ZENMUX_LEDGER', os.path.join(SCRATCH, 'plan', 'zenmux_ledger.jsonl'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.write(json.dumps(rec) + '\n'); fcntl.flock(f, fcntl.LOCK_UN)


def enrich(out, gen_id, flow_rate):
    """Fetch per-generation cost/latency via the management key."""
    if not gen_id:
        return out
    for _ in range(3):
        g = mgmt(f'generation?id={gen_id}')
        if g:
            rr = g.get('ratingResponses') or {}
            out['cost_usd'] = rr.get('originAmount')  # PAYG-equivalent value; subscription bills in Flows
            out['bill_usd'] = rr.get('billAmount')
            out['latency_ms'] = g.get('latency'); out['generation_time_ms'] = g.get('generationTime')
            out['native_tokens'] = g.get('nativeTokens')
            if flow_rate and rr.get('originAmount') is not None:
                out['flows_used'] = round(rr['originAmount'] / flow_rate, 3)
            return out
        time.sleep(2)
    return out


def run_openai(a, ik):
    msgs = []
    if a.system:
        msgs.append({'role': 'system', 'content': open(a.system, encoding='utf-8').read()})
    msgs.append({'role': 'user', 'content': open(a.user, encoding='utf-8').read()})
    body = {'model': a.model, 'messages': msgs, 'max_tokens': a.max_tokens}
    if a.search:
        body['web_search_options'] = {'search_context_size': a.search, 'user_location': {'type': 'approximate', 'country': 'US', 'timezone': 'America/New_York'}}
    if a.reasoning:
        body['reasoning'] = {'effort': a.reasoning}
    if a.temperature is not None:
        body['temperature'] = a.temperature
    resp, err = call_with_retries('https://zenmux.ai/api/v1/chat/completions', {'Authorization': f'Bearer {ik}'}, body, a.timeout, a.rpm)
    if resp is None:
        return None, err
    ch = (resp.get('choices') or [{}])[0]; msg = ch.get('message') or {}
    r = msg.get('reasoning') or msg.get('reasoning_content')
    return {'model': a.model, 'served_model': resp.get('model'), 'content': msg.get('content') or '',
            'reasoning': r[:20000] if isinstance(r, str) else None, 'annotations': msg.get('annotations'),
            'finish_reason': ch.get('finish_reason'), 'usage': resp.get('usage'), 'generation_id': resp.get('id')}, None


def run_anthropic(a, ik):
    body = {'model': a.model, 'max_tokens': a.max_tokens, 'messages': [{'role': 'user', 'content': open(a.user, encoding='utf-8').read()}]}
    if a.system:
        body['system'] = open(a.system, encoding='utf-8').read()
    if a.search:
        body['tools'] = [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': {'low': 5, 'medium': 10, 'high': 20}[a.search]}]
    if a.reasoning:
        body['thinking'] = {'type': 'enabled', 'budget_tokens': {'low': 2000, 'medium': 8000, 'high': 16000, 'xhigh': 32000}[a.reasoning]}
    resp, err = call_with_retries('https://zenmux.ai/api/anthropic/v1/messages', {'x-api-key': ik, 'Authorization': f'Bearer {ik}', 'anthropic-version': '2023-06-01'}, body, a.timeout, a.rpm)
    if resp is None:
        return None, err
    blocks = resp.get('content', [])
    text = ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
    cites = [c for b in blocks if b.get('type') == 'text' for c in (b.get('citations') or [])]
    searches = sum(1 for b in blocks if b.get('type') in ('server_tool_use', 'web_search_tool_result'))
    return {'model': a.model, 'served_model': resp.get('model'), 'content': text, 'annotations': cites[:200], 'searches': searches,
            'finish_reason': resp.get('stop_reason'), 'usage': resp.get('usage'), 'generation_id': resp.get('id')}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True); ap.add_argument('--system'); ap.add_argument('--user', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--search', choices=['low', 'medium', 'high']); ap.add_argument('--max-tokens', type=int, default=16000)
    ap.add_argument('--reasoning', choices=['low', 'medium', 'high', 'xhigh']); ap.add_argument('--temperature', type=float)
    ap.add_argument('--timeout', type=int, default=900); ap.add_argument('--protocol', default='openai', choices=['openai', 'anthropic'])
    ap.add_argument('--min-flows', type=float, default=60, help='block until the 5h/7d windows have this many Flows left')
    ap.add_argument('--rpm', type=int, default=10, help='cross-process request-start cap per minute (plan allows 10-15)')
    ap.add_argument('--label', default='')
    a = ap.parse_args()
    ik = key('ZENMUX_API_KEY')
    if not ik:
        print('ZENMUX_API_KEY missing', file=sys.stderr); sys.exit(2)
    q = quota_gate(a.min_flows)
    flow_rate = (q or {}).get('effective_usd_per_flow') or 0.03283
    t0 = time.time()
    out, err = (run_anthropic if a.protocol == 'anthropic' else run_openai)(a, ik)
    elapsed = round(time.time() - t0, 1)
    if out is None:
        json.dump({'model': a.model, 'error': err, 'elapsed_s': elapsed}, open(a.out, 'w'), indent=1)
        ledger_write({'ts': datetime.now(timezone.utc).isoformat(), 'label': a.label, 'model': a.model, 'error': err[:300], 'elapsed_s': elapsed})
        print(f'ERROR {a.model}: {err}', file=sys.stderr); sys.exit(1)
    out['elapsed_s'] = elapsed
    out = enrich(out, out.get('generation_id'), flow_rate)
    json.dump(out, open(a.out, 'w'), indent=1)
    ledger_write({'ts': datetime.now(timezone.utc).isoformat(), 'label': a.label or os.path.basename(a.out), 'model': a.model, 'protocol': a.protocol,
                  'search': a.search, 'finish': out.get('finish_reason'), 'usage': out.get('usage'), 'cost_usd': out.get('cost_usd'),
                  'flows_used': out.get('flows_used'), 'elapsed_s': elapsed, 'generation_id': out.get('generation_id'),
                  'quota5_remaining_before': (q or {}).get('quota_5_hour', {}).get('remaining_flows')})
    sys.stdout.write(out['content'])
    print(f"\n\n[{a.model} finish={out.get('finish_reason')} cost=${out.get('cost_usd')} flows={out.get('flows_used')} elapsed={elapsed}s]", file=sys.stderr)


if __name__ == '__main__':
    main()
