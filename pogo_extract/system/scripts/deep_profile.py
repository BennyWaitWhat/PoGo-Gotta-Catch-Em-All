"""DEEP per-specimen profiler. For EVERY in-bag mon, derive its full story:
identity, combat, PvP viability per league, current-vs-ideal moves + TM type,
and every actionable nuance (evolve-to-meta, lucky-trade, trade-evolve, power-up,
purify, transfer, collection significance). Deterministic over fresh DB +
PVPoke gamemaster/rankings. Writes system/analysis/deep_profiles.json and prints
a digest. Run AFTER pogo_pipeline.py (always re-crawl first).
"""
import sqlite3, json, re, os, sys, datetime
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))   # pogo_extract/
DB = os.path.join(ROOT, 'pokemon.db')
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
os.chdir(ROOT)                                   # cull_v9 reads gamemaster/legacy json relative to cwd
import cull_v9, keep_engine                      # the unified keep-reason engine + purpose mapping
def J(name): return json.load(open(os.path.join(ROOT, name), encoding='utf-8'))

MOVES = {int(k): v for k, v in J('move_id_to_name.json').items()}
FC = J('form_category.json')
gm = J('_gm_pvpoke.json')
POOL = {p['speciesId']: {'fast': set(p.get('fastMoves', [])), 'charged': set(p.get('chargedMoves', [])),
                         'elite': set(p.get('eliteMoves', [])), 'score_tags': p.get('tags', [])} for p in gm['pokemon']}
SPDEX = {p['speciesId']: p.get('dex') for p in gm['pokemon']}   # speciesId -> National Dex #
REC = {'GL': {e['speciesId']: (e.get('moveset'), e.get('score')) for e in J('_gl1500.json')},
       'UL': {e['speciesId']: (e.get('moveset'), e.get('score')) for e in J('_ul2500.json')}}
TRADE_EVO = {64:'Alakazam',67:'Machamp',75:'Golem',93:'Gengar',525:'Gigalith',533:'Conkeldurr',
             588:'Escavalier',616:'Accelgor',708:'Trevenant',710:'Gourgeist'}
LUCKY_OLD_MS = 1546300800000  # 2019-01-01

def mv(mid): return (MOVES.get(mid,'') or '').replace('_FAST','') if mid else None
def nm(x): return re.sub(r'[^A-Z0-9]','',(x or '').upper())
def form_name(pid, form):
    return (FC.get(f'{pid}_{form or 0}') or {}).get('form_name','')
def chain_rank(chain, species_id):
    if not chain: return None
    for seg in chain.split(';'):
        sid,_,rest = seg.partition(':')
        if sid==species_id:
            try: return int(rest.split('(')[0])
            except: return None
    return None
def tm_class(spid, move):
    p=POOL.get(spid)
    if not p: return '?'
    if move in p['elite']: return 'ELITE'
    if move in p['fast'] or move in p['charged']: return 'normal'
    return 'NA'

c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
cur = c.execute("""SELECT uid_hex,pokemon_id,species_name,form,gender,cp,level,iv_atk,iv_def,iv_sta,iv_total,
 is_zero,fresh_shiny,is_lucky,is_legendary,is_mythical,is_ultra_beast,is_paradox,was_best_buddy_badge,
 fresh_has_location_card,fresh_alignment,fresh_bread_mode,fresh_costume,pokemon_size_category,can_mega_evolve,
 gl_rank,ul_rank,ll_rank,gl_stage,ul_stage,gl_chain_ranks,ul_chain_ranks,adventure_effects_left,
 creation_time_ms,hatched_from_egg,is_traded,is_traded_flag_v2,original_owner_name,move1,move2,move3,
 auth_tag_names,weather_boost,buddy_km_walked,has_mega_evolved,marked_remote_tradable,
 mega_Level,mega_Points,bread_mode,fresh_bread_count,bread_max_level
 FROM pokemon WHERE in_bag=1""")
COL={n:i for i,n in enumerate([d[0] for d in cur.description])}
rows=cur.fetchall(); c.close()
def g(r,k): return r[COL[k]]

# nuance pre-pass + cost helpers
from collections import Counter as _Ctr, defaultdict as _dd
_spcount=_Ctr((g(r,'pokemon_id'), g(r,'form') or 0) for r in rows)   # for OnlyOne / dupes
_mega=_dd(list)
for _r in rows:
    if g(_r,'can_mega_evolve')==1: _mega[g(_r,'pokemon_id')].append(_r)
megabest={pid:set(id(x) for x in sorted(lst,key=lambda r:g(r,'cp'),reverse=True)[:1]) for pid,lst in _mega.items()}
_XL={50.0:0,49.5:20,49.0:40,48.5:57,48.0:74,47.5:91,47.0:108,46.5:123,46.0:138,45.5:153,
     45.0:168,44.5:181,44.0:194,43.5:207,43.0:220,42.5:232,42.0:244,41.5:256,41.0:268,40.5:279,40.0:290}
def _xl(lv): return 0 if lv>=50 else (_XL.get(max(lv,40.0),290) if lv>=40 else 296)
def _dust(lv): return 0 if lv>=50 else int((50.0-lv)*2*(17000 if lv>=40 else 14000))
KEEP_FLAGS={'Legendary','Mythical','UltraBeast','Paradox','BestBuddy','Background','HUNDO','NUNDO',
            'Shadow','Purified','Costume','XXL','Gigantamax','Dynamax','SHUNDO','ShinyShadow'}

profiles=[]
for r in rows:
    pid=g(r,'pokemon_id'); form=g(r,'form') or 0
    fa=g(r,'fresh_alignment'); shadow=(fa==1)
    align='Shadow' if fa==1 else 'Purified' if fa==2 else 'Normal'
    cur_moves=[mv(g(r,'move1')),mv(g(r,'move2')),mv(g(r,'move3'))]
    cur_set={nm(x) for x in cur_moves if x}
    # PvP viability: best chain rank per league + whether species is in rankings (meta)
    p={'uid':g(r,'uid_hex'),'species':g(r,'species_name'),'form_name':form_name(pid,form),
       'align':align,'gender':{1:'M',2:'F',3:'-'}.get(g(r,'gender'),'?'),
       'shiny':bool(g(r,'fresh_shiny')),'lucky':bool(g(r,'is_lucky')),
       'iv':f"{g(r,'iv_atk')}/{g(r,'iv_def')}/{g(r,'iv_sta')}",'ivt':g(r,'iv_total'),
       'level':g(r,'level'),'cp':g(r,'cp'),'moves':[x for x in cur_moves if x],
       'tags':[t for t in (g(r,'auth_tag_names') or '').split(';') if t],'flags':[],'opps':[]}
    # collection flags
    for k,lab in [('is_legendary','Legendary'),('is_mythical','Mythical'),('is_ultra_beast','UltraBeast'),
                  ('is_paradox','Paradox'),('was_best_buddy_badge','BestBuddy'),('fresh_has_location_card','Background')]:
        if g(r,k)==1: p['flags'].append(lab)
    if g(r,'iv_total')==45: p['flags'].append('HUNDO')
    if g(r,'is_zero')==1 and pid!=0: p['flags'].append('NUNDO')
    if shadow: p['flags'].append('Shadow')
    if fa==2: p['flags'].append('Purified')
    if (g(r,'fresh_costume') or 0)!=0: p['flags'].append('Costume')
    if g(r,'pokemon_size_category')==5: p['flags'].append('XXL')
    if g(r,'fresh_bread_mode')==2: p['flags'].append('Gigantamax')
    elif g(r,'fresh_bread_mode')==1: p['flags'].append('Dynamax')
    _bml=g(r,'bread_max_level') or 0          # highest Max/GMax move level (breadMoves_)
    if _bml: p['max_move_level']=_bml; p['flags'].append(f"MaxMoveL{_bml}")
    if g(r,'hatched_from_egg')==1: p['flags'].append('Hatched')
    if g(r,'is_traded')==1 or g(r,'is_traded_flag_v2')==1:
        oo=g(r,'original_owner_name'); p['flags'].append(f"Traded{('<'+oo) if oo else ''}")
    if p['shiny'] and g(r,'iv_total')==45: p['flags'].append('SHUNDO')
    if p['shiny'] and shadow: p['flags'].append('ShinyShadow')
    if _spcount[(pid,form)]==1: p['flags'].append('OnlyOne')
    if g(r,'marked_remote_tradable')==1: p['flags'].append('RemoteTradable')
    if g(r,'has_mega_evolved')==1: p['flags'].append('MegaBuilt')
    if (g(r,'buddy_km_walked') or 0)>0 and 'BestBuddy' not in p['flags']: p['flags'].append('WasBuddy')
    if g(r,'mega_Level'): p['flags'].append(f"MegaL{g(r,'mega_Level')}"); p['mega_points']=g(r,'mega_Points')
    if (g(r,'adventure_effects_left') or 0)>0: p['flags'].append('AdventureEffect'); p['ae_left']=g(r,'adventure_effects_left')
    if id(r) in megabest.get(pid,()): p['flags'].append('MegaBest')
    # best league by lowest chain rank among GL/UL (rank already chain-aware)
    glr,ulr=g(r,'gl_rank'),g(r,'ul_rank')
    best_lg,best_rank=None,None
    for lg,rk in [('GL',glr),('UL',ulr)]:
        if rk is not None and (best_rank is None or rk<best_rank): best_lg,best_rank=lg,rk
    p['gl_rank'],p['ul_rank']=glr,ulr
    p['pvp']=None
    if best_lg and best_rank is not None and best_rank<=50:
        stage=g(r,'gl_stage') if best_lg=='GL' else g(r,'ul_stage')
        ms,score=REC[best_lg].get(stage,(None,None))
        viable = score is not None and score>=80   # PVPoke meta-relevant species
        p['pvp']={'league':best_lg,'rank':best_rank,'species_id':stage,'meta':viable}
        if ms:
            miss=[(m,tm_class(stage,m)) for m in ms if nm(m) not in cur_set]
            if miss: p['pvp']['need_moves']=[f"{m}[{cl}]" for m,cl in miss]
            if shadow and any(nm(x)=='FRUSTRATION' for x in cur_moves if x): p['pvp'].setdefault('need_moves',[]).append('clear FRUSTRATION[ELITE]')
        # evolve-to-meta: a REAL evolution (different National Dex #), not a form
        # variant (Hisuian/Galarian/Castform-weather share the current dex).
        stage_dex = SPDEX.get(stage)
        if stage and stage_dex and stage_dex != pid:
            p['opps'].append(f"evolve→{stage} (best {best_lg})")
            p['pvp']['evolve_to'] = stage
    # opportunities (trade-for-evos intentionally excluded — user has the candy)
    lv=g(r,'level')
    if (glr==1 or ulr==1 or g(r,'iv_total')==45) and lv<50:
        p['opps'].append(f"power-up->L50 ({_xl(lv)}XL/{_dust(lv)//1000}k dust)")
    if shadow:
        p['opps'].append('purify option (gains Return, ~10% cheaper to max)')
    if (g(r,'is_legendary')==1 or g(r,'is_mythical')==1) and g(r,'is_lucky')!=1:
        p['opps'].append('lucky-trade (half dust to max)')
    if g(r,'can_mega_evolve')==1 and 'CanMega' not in p['flags']: p['flags'].append('CanMega')
    special = any(f in KEEP_FLAGS for f in p['flags'])
    p['fodder']= (not p['tags']) and (not p['pvp']) and (not special) and ('OnlyOne' not in p['flags'])
    if p['fodder']: p['opps'].append('safe to transfer (duplicate, no value)')
    profiles.append(p)

# ---- assign PURPOSE via the unified keep-engine (SINGLE SOURCE OF TRUTH) ----
# Purpose is now a VIEW of cull_v9's keep-reason registry (mapped by keep_engine),
# so it can never drift from the cull decision or the tag rules again. This
# replaced three parallel purpose/keep implementations that disagreed on ~197 mons
# (shadow, best-buddy column, species top-N sort, Reserve-tag sync) on 2026-05-28.
_cc = sqlite3.connect(DB); _cc.row_factory = sqlite3.Row
_crows, _cctx = cull_v9._load_rows_and_ctx(_cc.cursor())
UID_REASONS = {r['uid_hex']: cull_v9.is_protected(r, _cctx) for r in _crows}
_cc.close()
for p in profiles:
    reasons = UID_REASONS.get(p['uid'], [])
    p['keep_reasons'] = reasons                                    # the "why kept" audit trail
    p['purpose'] = keep_engine.classify_purpose(reasons, p['ivt'])

# ---- agent-audit corrections: now a VALIDATION SET, not overrides -----------
# The 40-agent audit (purpose_corrections.json, 2026-05-28) PATCHED the old
# hand-written purpose logic. That logic is gone, replaced by the unified engine
# which fixes those bugs at the source. Applying the corrections as per-mon
# overrides would reintroduce purpose<->cull drift (the exact thing unification
# kills), so we DON'T override. Instead we cross-check: how many past judgments
# does the engine already satisfy? The rest are engine-tuning candidates. The
# file is preserved for that mining; nothing is silently lost.
_corr_path=os.path.join(ROOT,'system','analysis','purpose_corrections.json')
if os.path.exists(_corr_path):
    _by_uid={p['uid']:p for p in profiles}
    _match=_diff=_gone=0; _diffs=[]
    for _c in json.load(open(_corr_path,encoding='utf-8')):
        _p=_by_uid.get(_c['uid'])
        if not _p: _gone+=1; continue
        if _p['purpose']==_c['to']: _match+=1
        else: _diff+=1; _diffs.append((_c.get('species'),_c['to'],_p['purpose']))
    tot=_match+_diff
    print(f"Audit cross-check: engine matches {_match}/{tot} past judgments "
          f"({100*_match//max(tot,1)}%); {_diff} differ -> engine-tuning candidates, {_gone} uid gone.")
    json.dump([{'species':s,'audit_to':a,'engine':e} for s,a,e in _diffs],
              open(os.path.join(ROOT,'system','analysis','engine_tuning_candidates.json'),'w'),indent=1)

os.makedirs(os.path.join(ROOT,'system','analysis'),exist_ok=True)
json.dump(profiles,open(os.path.join(ROOT,'system','analysis','deep_profiles.json'),'w'),indent=1)
from collections import Counter as _PC
_pc=_PC(p['purpose'] for p in profiles)
print('\nPURPOSE (every mon has one):', dict(_pc), '  total',sum(_pc.values()))

# ---- digest ----
def dt(ms): return datetime.datetime.fromtimestamp(ms/1000,datetime.UTC).date() if ms else None
print(f"DEEP PROFILE — {len(profiles)} in-bag mons\n")
pvp=[p for p in profiles if p['pvp']]
meta=[p for p in pvp if p['pvp'].get('meta')]
print(f"PvP-ranked (best chain-rank ≤50): {len(pvp)}  | of meta-relevant species: {len(meta)}")
print(f"  needing a move change: {sum(1 for p in pvp if p['pvp'].get('need_moves'))}")
pu=[p for p in profiles if any('power-up' in o for o in p['opps'])]
ev=[p for p in profiles if any(o.startswith('evolve→') for o in p['opps'])]
pf=[p for p in profiles if any('purify' in o for o in p['opps'])]
lt=[p for p in profiles if any('lucky-trade' in o for o in p['opps'])]
fd=[p for p in profiles if p['fodder']]
print(f"\nOpportunities: power-up {len(pu)} | evolve-to-meta {len(ev)} | purify {len(pf)} | lucky-trade {len(lt)} | fodder {len(fd)}")
print(f"Nuances: only-of-species {sum('OnlyOne' in p['flags'] for p in profiles)} | shundo {sum('SHUNDO' in p['flags'] for p in profiles)} | "
      f"shiny-shadow {sum('ShinyShadow' in p['flags'] for p in profiles)} | remote-tradable {sum('RemoteTradable' in p['flags'] for p in profiles)} | "
      f"can-mega {sum('CanMega' in p['flags'] for p in profiles)}")
print(f"\nCollection: shiny {sum(p['shiny'] for p in profiles)} | hundo {sum('HUNDO' in p['flags'] for p in profiles)} | "
      f"shadow {sum('Shadow' in p['flags'] for p in profiles)} | legendary {sum('Legendary' in p['flags'] for p in profiles)} | "
      f"lucky {sum(p['lucky'] for p in profiles)} | costume {sum('Costume' in p['flags'] for p in profiles)}")
print("\nTop power-up priorities (hundo/rank-1 not maxed):")
for p in sorted(pu,key=lambda x:(-x['ivt'],x['level']))[:12]:
    print(f"  {p['species']:<16} {p['align'][:4]:<4} {p['iv']}({p['ivt']}) L{p['level']} cp{p['cp']}  {';'.join(p['opps'])}")
print("\nEvolve-to-meta gems:")
for p in sorted(ev,key=lambda x:x['pvp']['rank'])[:10]:
    print(f"  {p['species']:<14} {p['iv']} rank {p['pvp']['rank']} {p['pvp']['league']}  -> {[o for o in p['opps'] if o.startswith('evolve')][0]}")
print(f"\nWrote system/analysis/deep_profiles.json ({len(profiles)} profiles).")
