#!/usr/bin/env python3
"""Cross-provider join probe: fixtures OpticOdds<->OddsPapi (externalProviders.opticoddsId), SharpSports (oddsjamId==OpticOdds game_id, fallback team+time), bookmaker overlap."""
import json, os, re, time, urllib.request, urllib.parse, datetime as dt, unicodedata, collections
S=os.environ.get('U3_SCRATCH', os.path.expanduser('~/.u3-scratch')); OUT=f'{S}/samples/cross'
k=lambda n: ''.join(os.environ[n].split())
OO,OP=k('OPTICODDS_API_KEY'),k('ODDSPAPI_API_KEY'); SS=k('SHARPSPORTS_API_SECRET') if os.environ.get('SHARPSPORTS_API_SECRET') else k('SHARPSPORTS_API_KEY')
def get(url, headers=None, params=None):
    if params: url+=('&' if '?' in url else '?')+urllib.parse.urlencode(params, doseq=True)
    req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 (compatible; u3-ingest/0.1)','Accept':'application/json', **(headers or {})})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            body=e.read()[:200].decode(errors='ignore')
            if e.code==429: time.sleep(3); continue
            return {'_error':e.code,'body':body}
        except Exception as e: time.sleep(2); err=str(e)
    return {'_error':'net','body':err}
def oo(path, **p): p['key']=OO; return get('https://api.opticodds.com/api/v3'+path, params=p)
def op(path, **p): p['apiKey']=OP; return get('https://v5.oddspapi.io/en'+path, params=p)
def ss(path, **p): return get('https://api.sharpsports.io/v1'+path, headers={'Authorization':'Token '+SS}, params=p)
def norm(s):
    s=unicodedata.normalize('NFKD',s or '').encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(fc|sc|cf|afc|the)\b','',s); return re.sub(r'[^a-z0-9]','',s)
LEAGUES={'nba':('NBA',11,'nba'),'wnba':('WNBA',11,'wnba'),'nfl':('NFL',14,'nfl'),'mlb':('MLB',13,'mlb'),'nhl':('NHL',15,'nhl'),'mls':('MLS',10,'mls'),
 'england_-_premier_league':('EPL',10,'epl'),'ncaaf':('NCAAF',14,'ncaaf'),'ncaab':('NCAAB',11,'ncaab')}
now=dt.datetime.now(dt.timezone.utc); horizon=now+dt.timedelta(days=3)
rep=['# Cross-provider live join probe\n', f'Run at {now.isoformat()} — window now..+3d. Outputs in samples/cross/.\n']
# ---- OpticOdds fixtures per league ----
oo_fx={}
for lg in LEAGUES:
    rows=[]; page=1
    while True:
        r=oo('/fixtures', league=lg, start_date_after=now.strftime('%Y-%m-%dT%H:%M:%SZ'), start_date_before=horizon.strftime('%Y-%m-%dT%H:%M:%SZ'), page=page)
        if '_error' in r: rows.append(r); break
        rows+=r.get('data',[]); 
        if not r.get('has_more') and not (r.get('total_pages') and page<r['total_pages']): break
        page+=1
        if page>20: break
    oo_fx[lg]=[x for x in rows if isinstance(x,dict) and 'id' in x]; time.sleep(0.3)
json.dump(oo_fx, open(f'{OUT}/oo_fixtures.json','w'))
oo_by_id={f['id']:(lg,f) for lg,fs in oo_fx.items() for f in fs}
oo_by_gid={f.get('game_id'):(lg,f) for lg,fs in oo_fx.items() for f in fs}
rep.append('\n## OpticOdds fixtures in window\n'+'\n'.join(f'- {lg}: {len(fs)}' for lg,fs in oo_fx.items())+'\n')
# ---- OddsPapi fixtures: by sport with startTimeFrom ----
op_fx=[]; op_tours=op('/tournaments'); 
for sid in sorted({v[1] for v in LEAGUES.values()}):
    r=op('/fixtures', sportId=sid, startTimeFrom=int(now.timestamp()))
    if isinstance(r,list): op_fx+=r
    else: rep.append(f'- oddspapi /fixtures sportId={sid} error {r}\n')
    time.sleep(0.4)
json.dump(op_fx, open(f'{OUT}/op_fixtures.json','w'))
def st(f): 
    v=f.get('startTime'); 
    return dt.datetime.fromtimestamp(v, dt.timezone.utc) if isinstance(v,(int,float)) else None
op_win=[f for f in op_fx if st(f) and st(f)<=horizon]
ext_keys=collections.Counter(k for f in op_fx for k,v in (f.get('externalProviders') or {}).items() if v)
rep.append(f'\n## OddsPapi fixtures (sports {sorted({v[1] for v in LEAGUES.values()})}, startTimeFrom=now): total {len(op_fx)}, in +3d window {len(op_win)}\n')
rep.append(f'externalProviders non-null key counts (all fetched): {dict(ext_keys)}\n')
# join
matched=[]; op_only=[]
for f in op_win:
    oid=(f.get('externalProviders') or {}).get('opticoddsId')
    if oid and oid in oo_by_id: matched.append((oid,f['fixtureId']))
    else: op_only.append(f)
oo_matched_ids={m[0] for m in matched}
per_lg=collections.Counter(oo_by_id[m[0]][0] for m in matched)
rep.append('\n## Fixture join OpticOdds<->OddsPapi (externalProviders.opticoddsId == OpticOdds fixture id)\n')
rep.append('| league | opticodds fixtures | matched via opticoddsId | only in opticodds |\n|---|---|---|---|\n')
for lg,fs in oo_fx.items(): rep.append(f'| {lg} | {len(fs)} | {per_lg.get(lg,0)} | {len(fs)-per_lg.get(lg,0)} |\n')
tour_names={t.get('tournamentId'):t.get('tournamentName') for t in (op_tours if isinstance(op_tours,list) else [])}
rep.append(f'\nOddsPapi window fixtures with no opticoddsId match: {len(op_only)} (top tournaments: {collections.Counter(tour_names.get(f.get("tournamentId"), f.get("tournamentId")) for f in op_only).most_common(12)})\n')
# start-time agreement + orientation for matched
diffs=[]; rot=0
for oid,fid in matched:
    o=oo_by_id[oid][1]; p=next(f for f in op_win if f['fixtureId']==fid)
    try:
        ost=dt.datetime.fromisoformat(o['start_date'].replace('Z','+00:00')); diffs.append(abs((ost-st(p)).total_seconds()))
    except Exception: pass
    pn=[x.get('participantName') or x.get('name') for x in (p.get('participants') or [])] if isinstance(p.get('participants'),list) else list((p.get('participants') or {}).values())
    hn=norm((o.get('home_competitors') or [{}])[0].get('name'))
    if pn and isinstance(pn[0],dict): pn=[x.get('participantName') or x.get('name') for x in pn]
    if pn and hn and norm(str(pn[0]))!=hn: rot+=1
rep.append(f'start-time |delta| for matched: max {max(diffs) if diffs else "n/a"} s, >60s count {sum(d>60 for d in diffs)}; home/participant1 name mismatch count {rot} of {len(matched)} (participants field shape may differ; see samples)\n')
json.dump({'matched':matched,'op_only_ids':[f['fixtureId'] for f in op_only]}, open(f'{OUT}/fixture_join.json','w'))
if matched:
    _o=oo_by_id[matched[0][0]][1]; _p=next(f for f in op_win if f['fixtureId']==matched[0][1])
    rep.append('\nRaw matched pair sample — OpticOdds fixture: `'+json.dumps({k:_o.get(k) for k in ['id','game_id','start_date','home_team_display','away_team_display','home_rotation_number','away_rotation_number','status','sport','league','source_ids']})+'`\nOddsPapi fixture: `'+json.dumps(_p)[:1800]+'`\n')
# ---- SharpSports events ----
ss_ev={}
for lg,(ssn,_,_) in LEAGUES.items():
    tried=[]
    for variant in [dict(league=ssn, startTimeStart=now.strftime('%Y-%m-%dT%H:%M:%S'), startTimeEnd=horizon.strftime('%Y-%m-%dT%H:%M:%S')), dict(league=ssn, upcoming='true'), dict(league=ssn.lower(), upcoming='true'), dict(league=ssn)]:
        r=ss('/events', **variant); tried.append((variant, (len(r) if isinstance(r,list) else r)))
        if isinstance(r,list) and r: break
        time.sleep(0.4)
    ss_ev[lg]=r if isinstance(r,list) else []; rep.append(f'- sharpsports /events {lg} attempts: {tried}\n'); time.sleep(0.4)
json.dump(ss_ev, open(f'{OUT}/ss_events.json','w'))
rep.append('\n## SharpSports events join\n| league | ss events | oddsjamId filled | theOddsApiId filled | matched oddsjamId==OpticOdds game_id | matched by team+time (±15m) | unmatched |\n|---|---|---|---|---|---|---|\n')
ss_join={}
for lg,evs in ss_ev.items():
    evs=[e for e in evs if isinstance(e,dict) and 'id' in e]; m1=m2=0; um=[]
    idx={}
    for f in oo_fx[lg]:
        try: t=dt.datetime.fromisoformat(f['start_date'].replace('Z','+00:00'))
        except Exception: continue
        idx.setdefault((norm((f.get('home_competitors') or [{}])[0].get('name')), norm((f.get('away_competitors') or [{}])[0].get('name'))),[]).append((t,f['id']))
    for e in evs:
        oj=e.get('oddsjamId')
        if oj and oj in oo_by_gid: m1+=1; ss_join[e['id']]=oo_by_gid[oj][1]['id']; continue
        h=norm((e.get('contestantHome') or {}).get('fullName')); a=norm((e.get('contestantAway') or {}).get('fullName'))
        try: et=dt.datetime.fromisoformat(e['startTime'].replace('Z','+00:00'))
        except Exception: et=None
        if et and et.tzinfo is None: et=et.replace(tzinfo=dt.timezone.utc)
        cands=idx.get((h,a),[])+[x for kk,c in idx.items() if h and a and (h in kk[0] or kk[0] in h) and (a in kk[1] or kk[1] in a) for x in c]
        hit=[fid for t,fid in cands if et and abs((t-et).total_seconds())<=900]
        if hit: m2+=1; ss_join[e['id']]=hit[0]
        else: um.append(f"{e.get('name')} @ {e.get('startTime')} oddsjam={oj}")
    rep.append(f'| {lg} | {len(evs)} | {sum(1 for e in evs if e.get("oddsjamId"))} | {sum(1 for e in evs if e.get("theOddsApiId"))} | {m1} | {m2} | {len(um)} |\n')
    if um: rep.append('  unmatched sample: '+'; '.join(um[:5])+'\n')
json.dump(ss_join, open(f'{OUT}/ss_join.json','w'))
if any(ss_ev.values()):
    e0=next((e for evs in ss_ev.values() for e in evs if isinstance(e,dict) and 'id' in e),None)
    rep.append(f'\nSharpSports event sample keys: {list(e0.keys()) if e0 else None}; example oddsjamId={e0.get("oddsjamId") if e0 else None} vs OpticOdds game_id format e.g. {next(iter(oo_by_gid))}\n')
# ---- bookmakers ----
oob=oo('/sportsbooks'); opb=op('/bookmakers'); ssb=ss('/books')
oo_names={norm(b.get('name')):b.get('id') for b in oob.get('data',[])} if isinstance(oob,dict) else {}
op_names={norm(b.get('bookmakerName')):b.get('slug') for b in opb} if isinstance(opb,list) else {}
ss_names={norm(b.get('name')):b.get('abbr') for b in ssb} if isinstance(ssb,list) else {}
alias={'ps3838':'pinnacle','betmgmsportsbook':'betmgm','espnbet':'espnbet','draftkingssportsbook':'draftkings'}
def canon(n): return alias.get(n,n)
sets={'opticodds':{canon(n) for n in oo_names},'oddspapi':{canon(n) for n in op_names},'sharpsports':{canon(n) for n in ss_names}}
rep.append(f'\n## Bookmaker overlap (normalized names)\n- OpticOdds sportsbooks: {len(oo_names)}; OddsPapi bookmakers: {len(op_names)}; SharpSports books: {len(ss_names)}\n')
rep.append(f'- in all three: {sorted(sets["opticodds"]&sets["oddspapi"]&sets["sharpsports"])}\n- OpticOdds∩OddsPapi: {len(sets["opticodds"]&sets["oddspapi"])}; OpticOdds∩SharpSports: {sorted(sets["opticodds"]&sets["sharpsports"])}; OddsPapi∩SharpSports: {sorted(sets["oddspapi"]&sets["sharpsports"])}\n')
rep.append(f'- SharpSports books (name:abbr): {ss_names}\n- OpticOdds ids for key books: '+str({n:oo_names[n] for n in oo_names if any(x in n for x in ['pinnacle','ps3838','draftkings','fanduel','circa','kalshi','polymarket','betonline','bookmaker','novig','prophet','sporttrade','caesars','betmgm','fliff','underdog','prizepicks'])})+'\n')
rep.append(f'- OddsPapi slugs for key books: '+str({n:op_names[n] for n in op_names if any(x in n for x in ['pinnacle','draftkings','fanduel','circa','kalshi','polymarket','betonline','bookmaker','novig','prophet','sporttrade','caesars','betmgm','fliff','underdog','prizepicks','bet365'])})+'\n')
json.dump({'oo':oo_names,'op':op_names,'ss':ss_names}, open(f'{OUT}/books.json','w'))
# ---- side-by-side main markets on one matched fixture ----
if matched:
    oid,fid=matched[0]; lg,o=oo_by_id[oid]
    a=oo('/fixtures/odds', fixture_id=oid, sportsbook=['draftkings','fanduel','pinnacle','ps3838','kalshi'])
    b=op('/fixtures/odds', fixtureId=fid, bookmakers='draftkings,fanduel,pinnacle,kalshi')
    c=ss('/prices', eventId=next((k for k,v in ss_join.items() if v==oid),'')) if any(v==oid for v in ss_join.values()) else {'_note':'no sharpsports join for this fixture'}
    json.dump({'opticodds':a,'oddspapi':b,'sharpsports':c}, open(f'{OUT}/side_by_side.json','w'))
    def oo_ml(a):
        out=[]
        for fx in a.get('data',[]) if isinstance(a,dict) else []:
            for od in fx.get('odds',[]):
                if od.get('market') in ('Moneyline','Point Spread','Total Points','Run Line','Total Runs','Puck Line','Total Goals','Spread','Total') and od.get('is_main'): out.append((od.get('sportsbook'),od.get('market'),od.get('name'),od.get('price'),od.get('points'),od.get('timestamp')))
        return out[:24]
    rep.append(f'\n## Side-by-side sample: {o.get("home_team_display")} vs {o.get("away_team_display")} ({lg}) opticodds={oid} oddspapi={fid}\n')
    rep.append('OpticOdds main-line rows (book, market, name, price, points, ts): '+json.dumps(oo_ml(a))+'\n')
    if isinstance(b,dict):
        odds=b.get('odds') or {}; rows=[]
        for bk,quotes in odds.items():
            for qid,q in list(quotes.items())[:6]: rows.append((bk,qid,q.get('marketId'),q.get('price'),q.get('mainLine'),q.get('changedAt'),q.get('bookmakerChangedAt'),q.get('limit')))
        rep.append('OddsPapi rows (book, oddId, marketId, price, mainLine, changedAt, bookmakerChangedAt, limit): '+json.dumps(rows[:24])+'\n')
    else: rep.append(f'OddsPapi odds error: {b}\n')
    rep.append('SharpSports prices: '+json.dumps(c)[:1500]+'\n')
    # market names
    mk_oo=sorted({od.get('market') for fx in (a.get('data',[]) if isinstance(a,dict) else []) for od in fx.get('odds',[])})[:40]
    mk_op=op('/markets', sportId=LEAGUES[lg][1]); mk_op_names=[m.get('marketName') or m.get('name') for m in mk_op][:40] if isinstance(mk_op,list) else mk_op
    mk_ss=ss('/markets', league=LEAGUES[lg][0]); mk_ss_names=[m.get('name') for m in mk_ss][:40] if isinstance(mk_ss,list) else mk_ss
    rep.append(f'\n## Market naming samples ({lg})\n- OpticOdds: {mk_oo}\n- OddsPapi: {mk_op_names}\n- SharpSports: {mk_ss_names}\n')
open(f'{S}/research/probes/cross.md','w').write(''.join(rep)); print(''.join(rep)[:6000])
