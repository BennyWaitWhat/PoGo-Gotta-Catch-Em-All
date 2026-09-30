"""Move analysis for PvP-tagged sets. For each specimen: current moves vs the
PVPoke recommended moveset, which moves are missing, and whether each missing
move is reachable with a NORMAL TM or needs an ELITE TM (legacy/event) — from
the authoritative PVPoke gamemaster eliteMoves list. Plus Frustration flag for
shadows. Deterministic; scans every specimen in each set.
"""
import sqlite3, json, re, sys
sys.stdout.reconfigure(encoding='utf-8')

MOVES = {int(k): v for k, v in json.load(open('move_id_to_name.json')).items()}
gm = json.load(open('_gm_pvpoke.json', encoding='utf-8'))
GLr = json.load(open('_gl1500.json', encoding='utf-8'))
ULr = json.load(open('_ul2500.json', encoding='utf-8'))

POOL = {}
for p in gm['pokemon']:
    POOL[p['speciesId']] = {
        'fast': set(p.get('fastMoves', [])),
        'charged': set(p.get('chargedMoves', [])),
        'elite': set(p.get('eliteMoves', [])),
        'name': p['speciesName']}
REC = {'GL': {e['speciesId']: e.get('moveset') for e in GLr},
       'UL': {e['speciesId']: e.get('moveset') for e in ULr}}

def nm(x): return re.sub(r'[^A-Z0-9]', '', (x or '').upper())
def dbmove(mid):
    if not mid: return None
    return MOVES.get(mid, f'?{mid}').replace('_FAST', '')
def pretty(m): return (m or '').replace('_', ' ').title()

def classify(spid, mv):
    p = POOL.get(spid)
    if not p: return '?'
    if mv in p['elite']: return 'ELITE'
    if mv in p['fast'] or mv in p['charged']: return 'normal'
    return 'NA'   # not in pool (likely granted on evolution, or unavailable)

def recset(spid, league, shadow):
    r = REC[league]
    if shadow and f'{spid}_shadow' in r and r[f'{spid}_shadow']:
        return r[f'{spid}_shadow']
    return r.get(spid)

def analyze(spid, league, cur_ids, shadow):
    ms = recset(spid, league, shadow)
    if not ms: return None
    cur_names = [dbmove(m) for m in cur_ids if m]
    curN = {nm(x) for x in cur_names}
    needed = [(mv, classify(spid, mv)) for mv in ms if nm(mv) not in curN]
    frustrated = shadow and any(nm(x) == 'FRUSTRATION' for x in cur_names)
    return {'rec': ms, 'cur': cur_names, 'needed': needed, 'frustration': frustrated}

def line(label, spid, league, cur_ids, shadow, extra=''):
    a = analyze(spid, league, cur_ids, shadow)
    cur = ' / '.join(pretty(x) for x in [dbmove(m) for m in cur_ids if m]) or '(none)'
    if a is None:
        print(f'  {label:<26} cur: {cur}   [no PVPoke moveset for {spid}]"{extra}"'); return
    rec = ' / '.join(pretty(x) for x in a['rec'])
    if not a['needed'] and not a['frustration']:
        print(f'  {label:<26} ✅ moves OK   cur: {cur}')
    else:
        parts = []
        for mv, cl in a['needed']:
            tag = {'normal': 'normal TM', 'ELITE': '⚡ELITE TM', 'NA': 'on-evolve/NA'}.get(cl, cl)
            parts.append(f'{pretty(mv)} [{tag}]')
        fr = '  +remove FRUSTRATION (⚡ELITE TM / purify)' if a['frustration'] else ''
        print(f'  {label:<26} need: {", ".join(parts)}{fr}')
        print(f'  {"":<26} cur: {cur}  ->  ideal: {rec}')

conn = sqlite3.connect('pokemon.db')

# ---- GL Top 10 / UL Top 10 (meta picks) ----
GLtargets = [  # (label, meta_pvpokeid, uid_or_None looked up from plan)
 ('Lickilicky','lickilicky'),('Quagsire','quagsire'),('Quagsire Shadow','quagsire'),
 ('Feraligatr','feraligatr'),('Jellicent','jellicent'),('Tinkaton','tinkaton'),
 ('Corsola Galarian','corsola_galarian'),('Forretress','forretress'),
 ('Feraligatr Shadow','feraligatr'),('Altaria','altaria')]
ULtargets = [
 ('Jellicent','jellicent'),('Corviknight','corviknight'),('Lapras','lapras'),
 ('Lapras Shadow','lapras'),('Tinkaton','tinkaton'),('Empoleon','empoleon'),
 ('Moltres Galarian','moltres_galarian'),('Empoleon Shadow','empoleon'),
 ('Feraligatr Shadow','feraligatr'),('Malamar Shadow','malamar')]
plan = json.load(open('rescan_report/pvp_top10_plan.json'))

def run_top(targets, plist, league):
    print(f'\n================= {league} TOP 10 — move check =================')
    by = {e['label']: e for e in plist}
    for label, spid in targets:
        e = by.get(label)
        if not e or not e.get('uid'):
            print(f'  {label:<26} (not owned)'); continue
        r = conn.execute("SELECT move1,move2,move3,fresh_alignment,species_name FROM pokemon WHERE uid_hex=?",(e['uid'],)).fetchone()
        shadow = (r[3] == 1)
        evo = f"  (EVOLVE {e.get('how','')})" if e.get('status')=='evolve' else ''
        line(label, spid, league, (r[0],r[1],r[2]), shadow, evo)
        if evo: print(f'  {"":<26}{evo}')

run_top(GLtargets, plan['GL'], 'GL')
run_top(ULtargets, plan['UL'], 'UL')

# ---- GL tag (gl_rank=1 = 'tagged as #1') ----
print(f'\n================= GL tag (rank #1) — move check =================')
rows = conn.execute("""SELECT uid_hex,species_name,gl_stage,move1,move2,move3,fresh_alignment,iv_atk,iv_def,iv_sta
                       FROM pokemon WHERE in_bag=1 AND (';'||COALESCE(auth_tag_names,'')||';') LIKE '%;GL;%'
                       ORDER BY species_name""").fetchall()
groups = {'optimal': [], 'normalTM': [], 'eliteTM': [], 'nomoveset': []}
detail = []
for uid,sp,stage,m1,m2,m3,fa,a,d,s in rows:
    spid = stage   # pvpoke id of best GL stage
    res = analyze(spid, 'GL', (m1,m2,m3), fa==1)
    if res is None:
        groups['nomoveset'].append(sp); continue
    if not res['needed'] and not res['frustration']:
        groups['optimal'].append(sp)
    elif any(cl=='ELITE' for _,cl in res['needed']) or res['frustration']:
        groups['eliteTM'].append((sp,res)); detail.append((sp,uid,spid,res,'elite',f'{a}/{d}/{s}'))
    else:
        groups['normalTM'].append((sp,res)); detail.append((sp,uid,spid,res,'normal',f'{a}/{d}/{s}'))
print(f'  Total GL-tag specimens: {len(rows)}')
print(f'   ✅ already optimal moveset : {len(groups["optimal"])}')
print(f'   🔧 need NORMAL TM only     : {len(groups["normalTM"])}')
print(f'   ⚡ need ELITE TM/Frustration: {len(groups["eliteTM"])}')
print(f'   ?  no PVPoke moveset       : {len(groups["nomoveset"])}')
conn.close()

# write full detail
with open('rescan_report/gl_tag_moves.txt','w',encoding='utf-8') as f:
    for sp,uid,spid,res,cl,iv in sorted(detail):
        needed=', '.join(f'{pretty(mv)}[{c}]' for mv,c in res['needed'])
        fr=' +FRUSTRATION' if res['frustration'] else ''
        f.write(f'{sp:<16} {iv:<9} need: {needed}{fr}\n')
print('  full GL-tag detail -> rescan_report/gl_tag_moves.txt')
