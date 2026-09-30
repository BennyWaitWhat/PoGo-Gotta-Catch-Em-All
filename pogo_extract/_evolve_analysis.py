"""PROTOTYPE (read-only): LINE-LEVEL cap. Pool every PLAIN specimen of a line (all evo stages,
same form-region) into its TERMINAL's cap, keep top-3 by IV. Pre-evo winners -> EVOLVE; terminal
winners -> KEEP; losers -> TRANSFER. 98+89 Bulba should displace 78+81 Venusaur."""
import json, sqlite3
from collections import defaultdict

gm = json.load(open('pvpoke_gamemaster.json'))
by_sp = {p['speciesId']: p for p in gm['pokemon']}
sp_to_dex = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
dex_to_sp = {}
for p in gm['pokemon']:
    sid, d = p['speciesId'], p.get('dex')
    if not d or any(x in sid for x in ('_shadow', '_mega', '_xl')): continue
    if d not in dex_to_sp or '_' not in sid: dex_to_sp[d] = sid
def direct(sid): return ((by_sp.get(sid, {}).get('family', {})) or {}).get('evolutions', []) or []
def terminals(sid, seen=None):
    if seen is None: seen = set()
    evos = direct(sid)
    if not evos:
        d = sp_to_dex.get(sid); return {d} if d else set()
    out = set()
    for e in evos:
        if e in seen: continue
        seen.add(e); out |= terminals(e, seen)
    return out
is_preevo, term_of = {}, {}
for d, sid in dex_to_sp.items():
    is_preevo[d] = bool(direct(sid)); term_of[d] = terminals(sid)

GENDER_TERMINALS = {
    415: {1: set(), 2: {416}}, 757: {1: set(), 2: {758}},
    361: {1: {362}, 2: {478, 362}}, 281: {1: {475, 282}, 2: {282}},
    280: {1: {475, 282}, 2: {282}}, 412: {1: {414}, 2: {413}},
}
def reach(pid, g):
    gt = GENDER_TERMINALS.get(pid)
    if gt is not None: return gt.get(g, term_of.get(pid, set()))
    return term_of.get(pid, set()) if is_preevo.get(pid) else set()

c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row
rows = c.execute("""SELECT uid_hex,pokemon_id,species_name,form,form_region,iv_total,cp,gender,
    fresh_shiny,fresh_alignment,fresh_costume,special_bg_id,natural_art_background,
    costume_decoration_id,fresh_bread_mode FROM pokemon WHERE in_bag=1""").fetchall()
def plain(r):
    return (not r['fresh_shiny'] and r['fresh_alignment'] != 1 and not (r['fresh_costume'] or 0)
            and not (r['special_bg_id'] or 0) and not (r['natural_art_background'] or 0)
            and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
            and not (r['fresh_bread_mode'] or 0))

LINE_CAP = 3
pool = defaultdict(list)
for r in rows:
    if not plain(r): continue
    region = r['form_region'] or 'kantonian'
    terms = reach(r['pokemon_id'], r['gender'])
    if terms:
        for t in terms: pool[(t, region)].append(r)
    else:
        pool[(r['pokemon_id'], region)].append(r)

decision = {}   # uid -> KEEP / EVOLVE
for (term, region), lst in pool.items():
    cap = 1 if is_preevo.get(term) else LINE_CAP
    for r in sorted(lst, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))[:cap]:
        ev = bool(reach(r['pokemon_id'], r['gender']))
        decision[r['uid_hex']] = 'EVOLVE' if ev else 'KEEP'

plain_rows = [r for r in rows if plain(r)]
ev_n = sum(1 for v in decision.values() if v == 'EVOLVE')
keep_n = sum(1 for v in decision.values() if v == 'KEEP')
free_n = len(plain_rows) - len(decision)
print(f"PLAIN specimens: {len(plain_rows)}  ->  KEEP(terminal) {keep_n}  EVOLVE {ev_n}  FREED {free_n}")
print("(specials shiny/hundo/PvP/legendary/cosmetic still protected separately -- real freed will be lower)\n")

def show_line(termpid, name):
    sub = defaultdict(list)
    for r in rows:
        if not plain(r): continue
        for t in reach(r['pokemon_id'], r['gender']) or {r['pokemon_id']}:
            if t == termpid: sub[r['form_region'] or 'kantonian'].append(r)
    print(f"=== {name} line (terminal {termpid}) ===")
    for region, lst in sub.items():
        print(f"  region {region}:")
        for r in sorted(lst, key=lambda r: -(r['iv_total'] or 0)):
            g = {1: 'M', 2: 'F', 3: '-'}.get(r['gender'], '?')
            d = decision.get(r['uid_hex'], 'transfer')
            print(f"    {r['species_name']:<11} iv={r['iv_total']:>2} {g} cp={r['cp']:<5} -> {d}")

show_line(3, 'Bulbasaur')
show_line(416, 'Combee/Vespiquen')
show_line(149, 'Dratini/Dragonite')
