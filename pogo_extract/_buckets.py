"""Collection bucket system (DRY-RUN classifier). Proposes a layered keep
taxonomy and classifies every in-bag mon. No server writes. Prints bucket
counts + trade-fodder breakdown + lucky-trade targets.

Tiers (a mon is KEEP if it lands in ANY keep bucket):
  T1 Collection-locked: shiny, hundo, nundo, legendary/mythical/UB/paradox,
     lucky, best-buddy, background, costume, purified, dynamax, gigantamax,
     XXL/XXS (top per species), adventure-effect species
  T2 Battle: PvP-perfect (gl/ul_rank=1), PvP meta tags, strongest shadows
     (top3/species), mega-best (top per mega species)
  T3 Reserve: top-3 by CP per (species,form) among the not-yet-kept
  -> else TRADE fodder, split into: trade-to-evolve / lucky-candidate / transfer
"""
import sqlite3, sys, time
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

# Free trade-evolution pre-stages (evolve cost -> 0 after a trade)
TRADE_EVO = {64:'Kadabra→Alakazam',67:'Machoke→Machamp',75:'Graveler→Golem',
             93:'Haunter→Gengar',525:'Boldore→Gigalith',533:'Gurdurr→Conkeldurr',
             588:'Karrablast→Escavalier',616:'Shelmet→Accelgor',708:'Phantump→Trevenant',
             710:'Pumpkaboo→Gourgeist'}
LUCKY_CUTOFF_MS = 1546300800000  # 2019-01-01: caught before this = high lucky odds

c = sqlite3.connect('pokemon.db')
cur = c.execute("""SELECT uid_hex,pokemon_id,species_name,form,cp,level,iv_total,is_zero,
    fresh_shiny,is_lucky,is_legendary,is_mythical,is_ultra_beast,is_paradox,
    was_best_buddy_badge,fresh_has_location_card,fresh_alignment,fresh_bread_mode,
    fresh_costume,pokemon_size_category,can_mega_evolve,gl_rank,ul_rank,
    adventure_effects_left,creation_time_ms,
    (';'||COALESCE(auth_tag_names,'')||';') AS tags
    FROM pokemon WHERE in_bag=1""")
rows = cur.fetchall()
C = {name:i for i,name in enumerate([d[0] for d in cur.description])}
def g(r,k): return r[C[k]]

# Precompute: top-3 CP per (species,form); top-3 shadow per species; XXL/XXS top-2 per species; mega-best per species
by_form=defaultdict(list); by_sp_shadow=defaultdict(list); by_sp_mega=defaultdict(list)
xxl=defaultdict(list); xxs=defaultdict(list)
for r in rows:
    key=(g(r,'pokemon_id'),g(r,'form') or 0)
    by_form[key].append(r)
    if g(r,'fresh_alignment')==1: by_sp_shadow[g(r,'pokemon_id')].append(r)
    if g(r,'can_mega_evolve')==1: by_sp_mega[g(r,'pokemon_id')].append(r)
    if g(r,'pokemon_size_category')==5: xxl[key].append(r)
    if g(r,'pokemon_size_category')==1: xxs[key].append(r)
def topN(lst,n,keyf=lambda r:g(r,'cp')): return set(id(r) for r in sorted(lst,key=keyf,reverse=True)[:n])
top3form={k:topN(v,3) for k,v in by_form.items()}
top3shadow={k:topN(v,3) for k,v in by_sp_shadow.items()}
megabest={k:topN(v,1) for k,v in by_sp_mega.items()}
xxlkeep={k:topN(v,2) for k,v in xxl.items()}; xxskeep={k:topN(v,2) for k,v in xxs.items()}

buckets=defaultdict(list)   # bucket name -> [uid]
keep=set(); reasons=defaultdict(list)
def mark(r,b):
    buckets[b].append(g(r,'uid_hex')); keep.add(g(r,'uid_hex')); reasons[g(r,'uid_hex')].append(b)

for r in rows:
    pid=g(r,'pokemon_id'); key=(pid,g(r,'form') or 0); rid=id(r)
    # T1 collection
    if g(r,'fresh_shiny')==1: mark(r,'Shiny')
    if g(r,'iv_total')==45: mark(r,'Hundo')
    if g(r,'is_zero')==1 and pid!=0: mark(r,'Nundo')
    if any(g(r,k)==1 for k in ('is_legendary','is_mythical','is_ultra_beast','is_paradox')): mark(r,'Legendary/Mythical/UB')
    if g(r,'is_lucky')==1: mark(r,'Lucky')
    if g(r,'was_best_buddy_badge')==1: mark(r,'BestBuddy')
    if g(r,'fresh_has_location_card')==1: mark(r,'Background')
    if (g(r,'fresh_costume') or 0)!=0: mark(r,'Costume')
    if g(r,'fresh_alignment')==2: mark(r,'Purified')
    if g(r,'fresh_bread_mode')==2: mark(r,'Gigantamax')
    elif g(r,'fresh_bread_mode')==1: mark(r,'Dynamax')
    if (g(r,'adventure_effects_left') or 0)>0: mark(r,'AdventureEffect')
    if rid in xxlkeep.get(key,()): mark(r,'XXL(top2)')
    if rid in xxskeep.get(key,()): mark(r,'XXS(top2)')
    # T2 battle
    if g(r,'gl_rank')==1 or g(r,'ul_rank')==1: mark(r,'PvP-perfect(rank1)')
    if ';GL Top 10;' in g(r,'tags') or ';UL Top 10;' in g(r,'tags'): mark(r,'PvP-meta')
    if g(r,'fresh_alignment')==1 and rid in top3shadow.get(pid,()): mark(r,'Shadow(top3)')
    if rid in megabest.get(pid,()): mark(r,'Mega-best')

# T3 reserve: top-3 per form among NOT-yet-kept
for key,lst in by_form.items():
    remaining=[r for r in lst if g(r,'uid_hex') not in keep]
    for r in sorted(remaining,key=lambda r:g(r,'cp'),reverse=True)[:3]:
        mark(r,'Reserve(top3/form)')

# Trade fodder = not kept
fodder=[r for r in rows if g(r,'uid_hex') not in keep]
# Trade-to-evolve = ANY in-bag in a free-trade-evo species (kept or not)
trade_evo_all=[r for r in rows if g(r,'pokemon_id') in TRADE_EVO]
transfer=fodder

print('='*70)
print(f'BUCKET SYSTEM — {len(rows)} in-bag mons')
print('='*70)
print(f'\nKEEP total: {len(keep)}    TRADE/TRANSFER fodder: {len(fodder)}')
print('\n--- Keep buckets (mons may be in several) ---')
for b in ['Shiny','Hundo','Nundo','Legendary/Mythical/UB','Lucky','BestBuddy','Background',
          'Costume','Purified','Gigantamax','Dynamax','AdventureEffect','XXL(top2)','XXS(top2)',
          'PvP-perfect(rank1)','PvP-meta','Shadow(top3)','Mega-best','Reserve(top3/form)']:
    print(f'  {b:<22} {len(buckets.get(b,[])):>5}')
import datetime
def dt(ms): return datetime.datetime.fromtimestamp(ms/1000, datetime.UTC).date()

print(f'\n--- Pure transfer fodder (not in any keep bucket): {len(transfer)} ---')
for r in sorted(transfer,key=lambda r:g(r,'cp')):
    print(f'  {g(r,"species_name"):<16} cp={g(r,"cp"):>4} iv={g(r,"iv_total")} L{g(r,"level")}  {dt(g(r,"creation_time_ms")) if g(r,"creation_time_ms") else "?"}')

print(f'\n--- TRADE-TO-EVOLVE (free 0-candy evolution after a trade): {len(trade_evo_all)} total ---')
te=defaultdict(list)
for r in trade_evo_all: te[g(r,'pokemon_id')].append(r)
for pid,lst in sorted(te.items()):
    best=max(lst,key=lambda r:g(r,'iv_total'))
    print(f'  {TRADE_EVO[pid]:<22} x{len(lst):<3} best iv={g(best,"iv_total")} cp={g(best,"cp")}  (trade any to evolve free)')

print('\n--- LUCKY-TRADE STRATEGY ---')
old=[r for r in rows if (g(r,'creation_time_ms') or 0)>0 and g(r,'is_lucky')!=1]
old.sort(key=lambda r:g(r,'creation_time_ms'))
print('  Oldest non-lucky mons (best lucky ODDS as the "old side" of a trade):')
for r in old[:10]:
    print(f'    {dt(g(r,"creation_time_ms"))}  {g(r,"species_name"):<15} cp={g(r,"cp"):>4} iv={g(r,"iv_total")}')
leg=[r for r in rows if any(g(r,k)==1 for k in ('is_legendary','is_mythical')) and g(r,'is_lucky')!=1]
leg.sort(key=lambda r:g(r,'creation_time_ms') or 9e18)
print('  Non-lucky legendaries worth lucky-trading (half stardust to max, 12/12/12 floor):')
for r in leg[:10]:
    print(f'    {dt(g(r,"creation_time_ms"))}  {g(r,"species_name"):<15} cp={g(r,"cp"):>4} iv={g(r,"iv_total")} L{g(r,"level")}')
c.close()
