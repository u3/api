#!/usr/bin/env python3
"""Judge-panel planning via ZenMux: N independent planners (different angles) -> judges score -> Opus synthesizes docs/PLAN.md.
Usage: plan_panel.py [--stage planners|judges|synth|all]"""
import argparse, glob, json, os, re, subprocess, sys, concurrent.futures as cf
S=os.environ.get('U3_SCRATCH', os.path.expanduser('~/.u3-scratch')); REPO='/home/user/api'; P=f'{S}/plan'
def rd(p, n=None):
    t=open(p,encoding='utf-8',errors='ignore').read() if os.path.exists(p) else f'(missing {p})'
    return t[:n] if n else t
def sections(md, wanted):
    """Extract top-level '## N.' sections whose number is in wanted (spec docs)."""
    out=[]; cur=None
    for line in md.splitlines():
        m=re.match(r'^##\s+(\d+)[.)]?\s', line)
        if m: cur=int(m.group(1))
        if cur in wanted: out.append(line)
    return '\n'.join(out) if out else md[:60000]
def context():
    parts=[rd(f'{P}/brief.md'), '\n\n===== EXTERNAL RESEARCH: infrastructure (GPT-5.6, web-grounded) =====\n'+rd(f'{P}/r1_infra.gpt56t.md',30000),
      '\n\n===== EXTERNAL RESEARCH: methodology/edges (GPT-5.6) =====\n'+rd(f'{P}/r2_method.gpt56t.md',30000),
      '\n\n===== EXTERNAL RESEARCH: methodology/edges (Gemini 3.8) =====\n'+rd(f'{P}/r2_method.gemini38.md',30000),
      '\n\n===== EXTERNAL RESEARCH: methodology/edges (Claude Opus 5) =====\n'+rd(f'{P}/r2_method.opus5.md',30000),
      '\n\n===== EXTERNAL RESEARCH: vendor landscape (Gemini 3.8) =====\n'+rd(f'{P}/r3_vendors.gemini38.md',25000),
      '\n\n===== EXTERNAL RESEARCH: infrastructure (Perplexity sonar-pro, cited) =====\n'+rd(f'{P}/r1_infra.pplx.md',30000),
      '\n\n===== EXTERNAL RESEARCH: methodology/edges (Perplexity deep research, cited) =====\n'+rd(f'{P}/r2_method.pplx.md',40000),
      '\n\n===== EXTERNAL RESEARCH: vendor landscape (Perplexity sonar-pro, cited) =====\n'+rd(f'{P}/r3_vendors.pplx.md',25000)]
    for prov in ['opticodds','oddspapi','sharpsports']:
        parts.append(f'\n\n===== PROVIDER SPEC (from our docs+live probes): {prov} — sections 1,5,7,8,10 =====\n'+sections(rd(f'{REPO}/docs/research/{prov}.md'), {1,5,7,8,10})[:70000])
    parts.append('\n\n===== CROSS-PROVIDER MAPPING & CANONICAL MODEL =====\n'+rd(f'{REPO}/docs/research/cross-provider-mapping.md',90000))
    parts.append('\n\n===== LIVE JOIN PROBE RESULTS =====\n'+rd(f'{S}/research/probes/cross.md',20000))
    return ''.join(parts)
ANGLES={
 'latency_first': ('openai/gpt-5.6-terra','openai', 'You are a low-latency systems architect from an HFT shop. Optimize for speed of quote-to-decision, deterministic replay, and measurement; be concrete about process topology, languages, serialization, and where microseconds matter vs where they do not.'),
 'quant_edge_first': ('google/gemini-3.8-flash','openai', 'You are the head quant. Optimize for edge capture: which data must be captured at tick level for CLV/latency/steam research, which edges to pursue first with the feeds we have, and what ingestion must guarantee for those edges to be measurable and tradable.'),
 'ops_cost_first': ('deepseek/deepseek-v4-pro','openai', 'You are a pragmatic platform engineer with a $300 GCP credit, ClickHouse and Snowflake trials, and a two-person team. Optimize for something that runs 24/7 within budget, is observable, and does not lose data; call out what NOT to build yet.'),
 'risk_adversary': ('x-ai/grok-4.6','openai', 'You are a skeptical risk/compliance-aware trader who has been limited by books and burned by data outages. Stress-test assumptions: vendor ToS, account limits, data licensing, mapping errors, settlement mismatches, stale quotes, and the practical realities of the "questionably ethical" practices — plan the mitigations and the kill-switches.'),
}
PLANNER_TASK = """
Produce a complete integration & ingestion plan (markdown, 600-1200 lines) with these sections: 0) Executive summary; 1) Architecture (components, topology, languages/runtimes, message flow, exactly what runs where on GCP/ClickHouse/Snowflake/BigQuery and estimated monthly cost within trial credits); 2) Feed usage matrix (for every data class: primary provider, secondary/cross-check provider, endpoint/channel, cadence, rate-limit budget, storage target); 3) Canonical data model summary and mapping strategy incl. QA loops (reference the mapping doc; do not restate it fully); 4) Ingestion services spec (per connector: protocol, subscription/poll plan, resume/replay, backfill, raw archival, normalization, sinks, observability, failure modes); 5) Edge inventory prioritized (edge, mechanism, data needs, latency budget, expected size/capacity, risks, what ingestion must provide) — be concrete about sportsbook-vs-Kalshi/Polymarket arbitrage, slow-book latency arb, Pinnacle-anchored fair value, player props vs DFS pick'em, CLV capture; 6) Measurement & research loop (CLV, latency attribution, mapping coverage, data-quality SLOs); 7) Phased roadmap with deliverables (Phase 0 ingestion MVP this week → Phase 3 execution), explicit non-goals; 8) Risks & mitigations (vendor ToS, limits, licensing, outages, key rotation — note the OpticOdds queue endpoint echoes the API key); 9) Open questions for vendors. Ground every claim in the provider specs/probe results provided (cite section names); where the research reports disagree with our probes, trust the probes. Output ONLY markdown."""
JUDGE_TASK = """You are a judge. Below are {n} independent plans for the same brief (context included). Score each plan 1-10 on: feasibility within budget, latency/edge realism, correctness vs the provider specs (penalize claims contradicted by the specs/probes), completeness of the ingestion spec, and clarity of the phased roadmap. Then list, for each plan, its 5 strongest specific ideas worth keeping and its 3 biggest errors. Output JSON only: {{"scores": {{"<plan>": {{"feasibility":n,"edge_realism":n,"spec_correctness":n,"ingestion_completeness":n,"roadmap":n,"total":n}}}}, "keep": {{"<plan>": ["..."]}}, "errors": {{"<plan>": ["..."]}}, "winner": "<plan>"}}"""
SYNTH_TASK = """You are the CTO. Using the context, the {n} candidate plans, and the judges' scorecards, write the FINAL plan docs/PLAN.md: start from the winning plan's structure, graft the strongest ideas from the others, fix every error the judges flagged that is confirmed by the provider specs, and resolve contradictions in favour of the specs/probes. Keep the same 10 sections as the candidates (0-9) plus 10) Decision log (each major decision, alternatives considered, why). Be specific and implementable: name endpoints, channels, cadences, table names, cost numbers, and phase deliverables. 900-1600 lines. Output ONLY markdown."""
def call(model, protocol, prompt_path, out_json, max_tokens=24000, reasoning=None, label=''):
    cmd=[sys.executable, f'{S}/tools/zenmux_chat.py','--model',model,'--protocol',protocol,'--user',prompt_path,'--out',out_json,'--max-tokens',str(max_tokens),'--timeout','3000','--label',label,'--min-flows','40','--stream']
    if reasoning: cmd+=['--reasoning',reasoning]
    r=subprocess.run(cmd, capture_output=True, text=True); return r.stdout, r.stderr[-400:], r.returncode
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--stage',default='all'); a=ap.parse_args(); ctx=context()
    if a.stage in ('planners','all'):
        def run(item):
            name,(model,proto,persona)=item; pp=f'{P}/plan_{name}.prompt.md'
            open(pp,'w').write(persona+'\n'+PLANNER_TASK+'\n\n===== CONTEXT =====\n'+ctx)
            out,err,rc=call(model,proto,pp,f'{P}/plan_{name}.json',label=f'plan_{name}'); open(f'{P}/plan_{name}.md','w').write(out); return name,rc,len(out),err
        with cf.ThreadPoolExecutor(4) as ex:
            for r in ex.map(run, ANGLES.items()): print('planner',r[0],'rc',r[1],'chars',r[2],r[3][-200:],file=sys.stderr)
    plans={n:rd(f'{P}/plan_{n}.md') for n in ANGLES}; plans={k:v for k,v in plans.items() if len(v)>2000}
    if a.stage in ('judges','all'):
        body=JUDGE_TASK.format(n=len(plans))+'\n\n===== CONTEXT (abridged) =====\n'+ctx[:250000]+''.join(f'\n\n===== PLAN: {k} =====\n{v}' for k,v in plans.items())
        for jname,(model,proto) in {'judge_opus':('anthropic/claude-opus-5','anthropic'),'judge_gpt':('openai/gpt-5.6-terra','openai')}.items():
            pp=f'{P}/{jname}.prompt.md'; open(pp,'w').write(body); out,err,rc=call(model,proto,pp,f'{P}/{jname}.json',max_tokens=8000,label=jname); open(f'{P}/{jname}.md','w').write(out); print(jname,'rc',rc,err[-200:],file=sys.stderr)
    if a.stage in ('synth','all'):
        judges=''.join(f'\n\n===== JUDGE {j} =====\n'+rd(f'{P}/{j}.md') for j in ['judge_opus','judge_gpt'])
        body=SYNTH_TASK.format(n=len(plans))+'\n\n===== CONTEXT =====\n'+ctx+''.join(f'\n\n===== PLAN: {k} =====\n{v}' for k,v in plans.items())+judges
        pp=f'{P}/plan_final.prompt.md'; open(pp,'w').write(body); out,err,rc=call('anthropic/claude-opus-5','anthropic',pp,f'{P}/plan_final.json',max_tokens=32000,label='plan_final')
        if len(out)>5000: open(f'{REPO}/docs/PLAN.md','w').write(out); print('PLAN.md written',len(out),file=sys.stderr)
        else: print('synth failed',err,file=sys.stderr)
if __name__=='__main__': main()
