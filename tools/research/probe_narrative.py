#!/usr/bin/env python3
"""Generate a machine probe narrative from saved samples (no LLM). Usage: probe_narrative.py <provider>"""
import json, os, sys, glob, re
S=os.environ.get('U3_SCRATCH', os.path.expanduser('~/.u3-scratch'))
p=sys.argv[1]; d=f'{S}/samples/{p}'; out=[f'# {p} live probe narrative (machine-generated from saved samples)\n',
 'Each row: sample name, HTTP status (from saved headers), body size, rate-limit/related headers, and a structural summary of the JSON body (top-level type, keys, list lengths, first-item keys). Raw bodies are in the samples directory. Entries marked non-200 include the error body.\n']
def summarize(obj, depth=0):
    if isinstance(obj, dict):
        ks=list(obj.keys()); s=f'object keys[{len(ks)}]={ks[:25]}'
        if depth<1:
            for k in ks[:6]:
                v=obj[k]
                if isinstance(v,(dict,list)): s+=f'; {k}: '+summarize(v,depth+1)
        return s
    if isinstance(obj, list):
        s=f'list[{len(obj)}]'
        if obj and isinstance(obj[0],dict): s+=f' item0 keys={list(obj[0].keys())[:30]}'
        elif obj: s+=f' item0={str(obj[0])[:80]}'
        return s
    return f'{type(obj).__name__}={str(obj)[:60]}'
log=f'{d}/_probe_log.tsv'
if os.path.exists(log):
    out.append('\n## Probe log (name, request, status, latency, size, server, structure)\n```\n'+open(log).read()+'\n```\n')
out.append('\n## Sample-by-sample structure\n')
for f in sorted(glob.glob(f'{d}/*.json')):
    name=os.path.basename(f)[:-5]; h=f[:-5]+'.headers'; status='?'; rl=''
    if os.path.exists(h):
        ht=open(h,errors='ignore').read(); m=re.search(r'HTTP/\S+ (\d{3})',ht); status=m.group(1) if m else '?'
        rl=' '.join(l.strip() for l in ht.splitlines() if re.match(r'(?i)(x-ratelimit|ratelimit|retry-after|x-request|cf-ray|content-encoding)',l))
    try:
        txt=open(f,errors='ignore').read(); obj=json.loads(txt) if txt.strip() else None; summ=summarize(obj) if obj is not None else 'empty'
    except Exception as e:
        txt=open(f,errors='ignore').read(); summ=f'non-JSON ({type(e).__name__}) head={txt[:120]!r}'
    size=os.path.getsize(f)
    line=f'- **{name}** — status {status}, {size} B; {rl}; {summ}'
    if status not in ('200','?'): line+=f'\n  error body: `{txt[:300].strip()}`'
    out.append(line+'\n')
for f in sorted(glob.glob(f'{d}/*.jsonl'))+sorted(glob.glob(f'{d}/*.txt')):
    lines=open(f,errors='ignore').read().splitlines(); types={}
    for l in lines[:5000]:
        try: o=json.loads(l); k=f"{o.get('channel','?')}/{o.get('type', o.get('event','?'))}"; types[k]=types.get(k,0)+1
        except Exception: types['non-json']=types.get('non-json',0)+1
    out.append(f'- **{os.path.basename(f)}** — {len(lines)} lines; message types: {types}; first line: `{lines[0][:400] if lines else ""}`\n')
open(f'{S}/research/probes/{p}.md','w').write(''.join(out)); print(p, len(out), 'entries ->', f'{S}/research/probes/{p}.md')
