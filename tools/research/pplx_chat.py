#!/usr/bin/env python3
"""Perplexity chat helper (OpenAI-compatible). Usage: pplx_chat.py --model sonar-pro|sonar-reasoning-pro|sonar-deep-research --user prompt.md --out out.json [--max-tokens N]
Writes JSON {model, content, citations, search_results, usage, elapsed_s}; prints content. Key from PERPLEXITY_API_KEY."""
import argparse, json, os, sys, time, urllib.request, urllib.error

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--model', default='sonar-pro'); ap.add_argument('--user', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--system'); ap.add_argument('--max-tokens', type=int, default=8000); ap.add_argument('--timeout', type=int, default=1800); ap.add_argument('--recency')
    a = ap.parse_args()
    key = ''.join(os.environ.get('PERPLEXITY_API_KEY', '').split())
    msgs = ([{'role': 'system', 'content': open(a.system).read()}] if a.system else []) + [{'role': 'user', 'content': open(a.user, encoding='utf-8').read()}]
    body = {'model': a.model, 'messages': msgs, 'max_tokens': a.max_tokens, 'return_related_questions': False}
    if a.recency: body['search_recency_filter'] = a.recency
    req = urllib.request.Request('https://api.perplexity.ai/chat/completions', data=json.dumps(body).encode(), headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    t0 = time.time(); resp = None; err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=a.timeout) as r: resp = json.load(r); break
        except urllib.error.HTTPError as e:
            err = f'HTTP {e.code}: {e.read()[:500].decode(errors="ignore")}'
            if e.code in (400, 401, 403): break
        except Exception as e: err = f'{type(e).__name__}: {e}'
        time.sleep(10 * (attempt + 1))
    if resp is None:
        json.dump({'model': a.model, 'error': err}, open(a.out, 'w')); print('ERROR', err, file=sys.stderr); sys.exit(1)
    msg = resp['choices'][0]['message']; content = msg.get('content') or ''
    out = {'model': a.model, 'content': content, 'citations': resp.get('citations'), 'search_results': resp.get('search_results'), 'usage': resp.get('usage'), 'elapsed_s': round(time.time() - t0, 1)}
    json.dump(out, open(a.out, 'w'), indent=1)
    cites = resp.get('citations') or []
    sys.stdout.write(content + ('\n\nSources:\n' + '\n'.join(f'[{i+1}] {c}' for i, c in enumerate(cites)) if cites else ''))
    print(f"\n[{a.model} usage={out['usage']} elapsed={out['elapsed_s']}s citations={len(cites)}]", file=sys.stderr)

if __name__ == '__main__': main()
