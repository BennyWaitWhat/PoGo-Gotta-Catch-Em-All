"""Which bag mons can evolve into a dex slot you're missing -- GENDER / FORM / REGION CORRECT.

The naive version (evolution graph only) listed impossible evolutions: a male Salandit for
Salazzle (female-only), a male Snorunt for Froslass, a Blue-Striped Basculin for Basculegion
(White-Striped only), a Hisuian Sneasel for Weavile (Hisuian goes to Sneasler). This tool
checks the mon's actual gender, form and region before claiming a target (user 2026-06-09
"did you even check the requirements").

  python evo_hundo_gap.py            -> bag HUNDOS whose evolution fills a missing-HUNDO dex slot
  python evo_hundo_gap.py --caught   -> ANY bag mon whose evolution fills an uncaught dex slot
  python evo_hundo_gap.py --pile     -> also flag sources sitting in the Transfer pile

Data: pokemon.db (bag), pokedex_hundos_live.json (lifetime dex: hundo flags + times),
pvpoke_gamemaster.json (evolution graph; shadow speciesIds excluded from naming/reach).
"""
import json, os, sqlite3, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))

MODE_CAUGHT = '--caught' in sys.argv
SHOW_PILE = '--pile' in sys.argv

# ---- evolution graph from the gamemaster (region-aware via speciesId suffixes) ----
gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
BS = {p['speciesId']: p for p in gm['pokemon']}
S2D = {p['speciesId']: p.get('dex') for p in gm['pokemon']}

def reach(sid, seen=None):
    """All dex numbers reachable by evolving speciesId sid (transitively)."""
    if seen is None:
        seen = set()
    p = BS.get(sid)
    if not p:
        return set()
    out = set()
    for ev in (p.get('family', {}).get('evolutions', []) or []):
        d = S2D.get(ev)
        if d:
            out.add(d)
        if ev not in seen:
            seen.add(ev)
            out |= reach(ev, seen)
    return out

D2S, NAME = {}, {}
for p in gm['pokemon']:
    d = p.get('dex')
    if d and d not in D2S and '_shadow' not in p['speciesId']:   # shadow ids pollute names (Grubbin (Shadow) bug 2026-06-09)
        D2S[d] = p['speciesId']
        NAME[d] = p['speciesName']

# ---- hard requirement gates the gamemaster graph does NOT encode ----
# (base_pid, target_dex) -> required gender (1=male, 2=female per PokemonDisplayProto)
GENDER_GATE = {
    (757, 758): 2,   # Salandit -> Salazzle: female only
    (361, 478): 2,   # Snorunt -> Froslass: female only
    (415, 416): 2,   # Combee -> Vespiquen: female only
    (412, 413): 2,   # Burmy -> Wormadam: female only
    (412, 414): 1,   # Burmy -> Mothim: male only
    (280, 475): 1,   # Ralts -> Gallade: male only (via Kirlia)
    (281, 475): 1,   # Kirlia -> Gallade: male only
}
REGION_SUFFIX = {'hisuian': '_hisuian', 'alolan': '_alolan', 'galarian': '_galarian', 'paldean': '_paldean'}

_FE = {}
try:
    _FE = json.load(open(os.path.join(ROOT, 'form_enum.json'), encoding='utf-8'))
except Exception:
    pass

def form_name(f):
    return _FE.get(str(f or 0), '')

def form_gate_ok(r, target_dex):
    """Form-conditional evolutions the speciesId suffix doesn't capture."""
    if r['pokemon_id'] == 550 and target_dex == 902:     # Basculin -> Basculegion: White-Striped only in the
        return 'White' in form_name(r['form'])           # main series; in GO the evo is DISABLED + 902 unreleased,
    return True                                          # so UNRELEASED_IN_POGO blocks it regardless (audit F5)

def sid_for(r):
    """Resolve a bag row to its regional speciesId so regional lines evolve into THEIR OWN family
    (a Hisuian Sneasel must reach Sneasler, never Weavile)."""
    base = D2S.get(r['pokemon_id'])
    if not base:
        return None
    suf = REGION_SUFFIX.get((r['form_region'] or '').strip().lower())
    if suf and (base + suf) in BS:
        return base + suf
    return base

# ---- dex state (lifetime, from the live PokedexImpl walk) ----
dx = json.load(open(os.path.join(ROOT, 'pokedex_hundos_live.json'), encoding='utf-8'))['entries']
HAVE_HUNDO = {e['pid'] for e in dx if e.get('hundo')}
CAUGHT = {e['pid'] for e in dx if e.get('times', 0) > 0}   # missing times = NOT caught, matching every other reader (audit F18)
missing = (lambda d: d not in CAUGHT) if MODE_CAUGHT else (lambda d: d not in HAVE_HUNDO)

# ---- target availability ----
# Final forms NOT in Pokemon GO yet -> evolving toward them is impossible. Curated + WEB-VERIFIED,
# because pvpoke's 'released' flag is unreliable for this: it marks Ditto, Drednaw, Type:Null,
# Eiscue and ~80 other in-game species as unreleased. So we never auto-filter on that flag --
# only this hand-checked set hard-excludes a target. Re-verify with a web check before adding.
UNRELEASED_IN_POGO = {
    981,   # Farigiraf -- verified not in PoGo 2026-06-09 (Girafarig 'will' evolve once it launches)
    902,   # Basculegion -- verified 2026-06-09: not released in GO, AND Niantic stated on-record at the
           # Feb 2024 Hisui launch that White-Striped Basculin would NOT be able to evolve (audit F5)
}
# Target IS in GO (raid/event-obtainable) but the EVOLUTION METHOD is not: the GAME_MASTER carries no
# evolution branch for the pre-evo (master-plan workflow 2026-06-09, GAME_MASTER ground truth -- the
# CLEAN list was over-claiming "evolve Scyther->Kleavor / Stantler->Wyrdeer"). Bank candy and wait.
EVOLUTION_METHOD_MISSING = {
    900: 'Kleavor is raid-only so far -- no Scyther evolution method in GO',
    899: 'Wyrdeer is event/raid-only so far -- no Stantler evolution method in GO',
}
import evolvable_forms

# ---- bag sources ----
con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
con.row_factory = sqlite3.Row
where = 'in_bag=1' if MODE_CAUGHT else 'in_bag=1 AND iv_total=45'
rows = con.execute(f'SELECT uid_hex,pokemon_id,species_name,form,fresh_form,form_region,gender,iv_total,'
                   f'fresh_costume,costume,fresh_shiny FROM pokemon WHERE {where}').fetchall()

pile = set()
pp = os.path.join(ROOT, 'system', 'analysis', 'tagsets', 'Transfer.txt')
if os.path.exists(pp):
    pile = set(open(pp).read().split())

def source_can_evolve(r):
    """Use the game's form/costume rules, including allowNoevolveEvolution exceptions."""
    allowed = evolvable_forms.row_can_evolve(r)
    # Unknown form data retains the existing species-graph fallback; only a known lock blocks it.
    if allowed is not False:
        return True, ''
    return False, 'form or costume cannot evolve'

clean, caution, blocked = {}, {}, {}   # key (species,region,gender) -> {'targets':set,'n':int,'piled':int,'why':str}

def add(bucket, r, targets, why=''):
    reg = (r['form_region'] or '').strip().lower()
    reg = '' if reg in ('', 'kantonian', 'normal', 'none', 'null') else reg
    key = (r['species_name'], reg, {1: 'M', 2: 'F'}.get(r['gender'], '?'))
    e = bucket.setdefault(key, {'targets': set(), 'n': 0, 'piled': 0, 'why': why})
    e['targets'] |= targets
    e['n'] += 1
    if why and not e['why']:
        e['why'] = why
    if r['uid_hex'] in pile:
        e['piled'] += 1

for r in rows:
    sid = sid_for(r)
    if not sid:
        continue
    targets = set()
    for t in reach(sid):
        if not missing(t):
            continue
        need = GENDER_GATE.get((r['pokemon_id'], t))
        if need is not None and r['gender'] != need:
            continue
        if not form_gate_ok(r, t):
            continue
        targets.add(t)
    if not targets:
        continue
    avail = {t for t in targets if t not in UNRELEASED_IN_POGO and t not in EVOLUTION_METHOD_MISSING}
    if not avail:                                   # every target unreleased OR method-missing in PoGo
        _why = next((EVOLUTION_METHOD_MISSING[t] for t in targets if t in EVOLUTION_METHOD_MISSING),
                    'target not in PoGo yet')
        add(blocked, r, targets, _why)
        continue
    ok, why = source_can_evolve(r)
    if not ok:                                      # costumed / Noevolve -> can't evolve
        add(blocked, r, avail, why)
        continue
    if r['fresh_shiny']:                            # evolvable, but you'd sacrifice a shiny
        add(caution, r, avail, 'SHINY -- evolving would consume your shiny')
        continue
    add(clean, r, avail)

label = 'UNCAUGHT species' if MODE_CAUGHT else 'missing HUNDO'
print(f'dex: {len(CAUGHT)} caught, {len(HAVE_HUNDO)} hundo | sources scanned: {len(rows)} '
      f'({"all bag" if MODE_CAUGHT else "bag hundos"})')

def show(title, bucket, show_why=False):
    print(f'\n{title} ({len(bucket)}):')
    if not bucket:
        print('  NONE'); return
    for (sp, reg, g), e in sorted(bucket.items()):
        tag = f' [{reg}]' if reg else ''
        tgts = ', '.join(NAME.get(t, f'#{t}') for t in sorted(e['targets']))
        note = f'   << {e["why"]}' if (show_why and e['why']) else ''
        pile_note = f'  !! {e["piled"]} IN TRANSFER PILE' if (SHOW_PILE and e['piled']) else ''
        print(f'  {sp+tag:<18} ({g} x{e["n"]}) -> {tgts}{pile_note}{note}')

show(f'CLEAN -- spare hundos to evolve into a {label} slot', clean)
show('CAUTION -- would sacrifice a shiny', caution, show_why=True)
show('BLOCKED -- cannot evolve / target unavailable', blocked, show_why=True)
