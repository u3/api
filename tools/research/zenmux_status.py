#!/usr/bin/env python3
"""Print ZenMux subscription quota + PAYG balance using the Management API key, and the local ledger totals."""
import json, os, sys, urllib.request
mk = ''.join(os.environ.get('ZENMUX_PLATFORM_API', '').split())
def get(p):
    r = urllib.request.Request(f'https://zenmux.ai/api/v1/management/{p}', headers={'Authorization': f'Bearer {mk}'})
    return json.load(urllib.request.urlopen(r, timeout=20))['data']
s = get('subscription/detail'); b = get('payg/balance')
q5, q7 = s['quota_5_hour'], s['quota_7_day']
print(f"plan={s['plan']['tier']} status={s['account_status']} usd/flow={s['effective_usd_per_flow']}")
print(f"5h : {q5['used_flows']:.1f}/{q5['max_flows']} flows used (${q5['used_value_usd']:.2f}/${q5['max_value_usd']:.2f}), {q5['remaining_flows']:.1f} left, resets {q5['resets_at']}")
print(f"7d : {q7['used_flows']:.1f}/{q7['max_flows']} flows used (${q7['used_value_usd']:.2f}/${q7['max_value_usd']:.2f}), {q7['remaining_flows']:.1f} left, resets {q7['resets_at']}")
print(f"PAYG balance: ${b['total_credits']:.2f}")
led = ''+os.environ.get('U3_SCRATCH', os.path.expanduser('~/.u3-scratch'))+'/plan/zenmux_ledger.jsonl'
if os.path.exists(led):
    rows = [json.loads(l) for l in open(led) if l.strip()]
    cost = sum((r.get('cost_usd') or 0) for r in rows); fl = sum((r.get('flows_used') or 0) for r in rows)
    print(f"ledger: {len(rows)} calls, ${cost:.3f} PAYG-equivalent, {fl:.1f} flows; errors={sum(1 for r in rows if r.get('error'))}")
    for r in rows[-8:]:
        print(f"  {r['ts'][11:19]} {r.get('label','')[:28]:28} {r['model']:32} cost=${(r.get('cost_usd') or 0):.3f} flows={(r.get('flows_used') or 0):.1f} {('ERR '+r['error'][:60]) if r.get('error') else ''}")
