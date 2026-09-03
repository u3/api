#!/usr/bin/env python3
"""Capture OddsPapi v5 WebSocket for N seconds per channel set; writes samples/oddspapi/ws_<label>.jsonl (key never written)."""
import asyncio, json, os, sys, time, websockets
S=''+os.environ.get('U3_SCRATCH', os.path.expanduser('~/.u3-scratch'))+'/samples/oddspapi'
KEY=''.join(os.environ['ODDSPAPI_API_KEY'].split())
async def cap(label, login, secs, maxn=2000):
    n=0; t0=time.time(); path=f'{S}/ws_{label}.jsonl'
    with open(path,'w') as f:
        try:
            async with websockets.connect('wss://v5.oddspapi.io/ws', proxy=True, open_timeout=20, max_size=8*1024*1024) as ws:
                await ws.send(json.dumps({'type':'login','apiKey':KEY, **login}))
                while time.time()-t0<secs and n<maxn:
                    try: msg=await asyncio.wait_for(ws.recv(), 10)
                    except asyncio.TimeoutError: continue
                    s=msg if isinstance(msg,str) else '{"binary_len":%d}'%len(msg)
                    f.write(s.replace(KEY,'***')+'\n'); n+=1
        except Exception as e:
            f.write(json.dumps({'capture_error':f'{type(e).__name__}: {e}'})+'\n')
    print(label, n, 'msgs in', round(time.time()-t0,1),'s')
async def main():
    await cap('login_all', {}, 20, 40)
    await cap('odds_bb_sc', {'channels':['odds'],'sportIds':[10,11,13]}, 60)
    await cap('odds_pinnacle_poly', {'channels':['odds'],'bookmakers':['pinnacle','polymarket','kalshi','draftkings','fanduel']}, 60)
    await cap('fixtures_scores_clocks', {'channels':['fixtures','scores','clocks']}, 45)
    await cap('bookmakers_futures', {'channels':['bookmakers','bookmakersFutures','futures']}, 45)
    await cap('misc_channels', {'channels':['events','injuries','lineups','stats','currencies']}, 45)
    await cap('zstd_odds', {'channels':['odds'],'sportIds':[10],'receiveType':'zstd'}, 20, 200)
asyncio.run(main())
