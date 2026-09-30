"""Identify pre-evolutions worth evolving (vs transferring).

Sources:
  - pvpoke_gamemaster.json: family chains
  - pokemon.db: in-bag mons, iv_total, hundo flag
  - pokedex_hundos_live.json: which species already have a hundo dex entry
  - form_enum.json: integer form -> name suffix mapping

Output:
  agent_outputs/evolution_candidates.json
"""
import json
import sqlite3
import re
from collections import defaultdict

ROOT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract"
OUT = ROOT + r"\agent_outputs\evolution_candidates.json"

# Trade-evolve species in PoGo (no candy cost when traded; otherwise standard candy + special item).
# Speciesname -> note.
TRADE_EVOLVE_PIDS = {
    64: "Kadabra -> Alakazam (trade evolve)",
    67: "Machoke -> Machamp (trade evolve)",
    75: "Graveler -> Golem (trade evolve)",
    93: "Haunter -> Gengar (trade evolve)",
    95: "Onix -> Steelix (needs Metal Coat)",
    117: "Seadra -> Kingdra (needs Dragon Scale)",
    137: "Porygon -> Porygon2 (needs Up-Grade)",
    123: "Scyther -> Scizor (needs Metal Coat) or Kleavor (Black Augurite)",
    61: "Poliwhirl -> Politoed (needs King's Rock) branch",
    79: "Slowpoke -> Slowking (needs King's Rock) branch",
    233: "Porygon2 -> Porygon-Z (needs Dubious Disc)",
    112: "Rhydon -> Rhyperior (needs Sinnoh Stone)",
    125: "Electabuzz -> Electivire (needs Sinnoh Stone)",
    126: "Magmar -> Magmortar (needs Sinnoh Stone)",
    366: "Clamperl -> Huntail or Gorebyss (branch, needs item)",
    349: "Feebas -> Milotic (20 km walk)",
    215: "Sneasel -> Weavile (needs Sinnoh Stone) / Sneasler",
    361: "Snorunt -> Glalie or Froslass (branch, needs Sinnoh Stone for Froslass)",
    198: "Murkrow -> Honchkrow (needs Sinnoh Stone)",
    200: "Misdreavus -> Mismagius (needs Sinnoh Stone)",
    207: "Gligar -> Gliscor (needs Sinnoh Stone)",
    211: "Qwilfish -> Overqwil (Hisuian)",
    216: "Teddiursa -> Ursaring -> Ursaluna",
    439: "Mime Jr. -> Mr. Mime (or Mr. Rime via Galarian)",
    438: "Bonsly -> Sudowoodo",
    436: "Bronzor -> Bronzong",
    406: "Budew -> Roselia -> Roserade",
    315: "Roselia -> Roserade (needs Sinnoh Stone)",
    298: "Azurill -> Marill -> Azumarill",
    439: "Mime Jr. -> Mr. Mime",
    433: "Chingling -> Chimecho",
    532: "Timburr -> Gurdurr -> Conkeldurr",
    533: "Gurdurr -> Conkeldurr (trade evolve)",
    616: "Shelmet/Karrablast trade evolve",
    615: "Cryogonal direct",
    591: "Foongus -> Amoonguss",
    133: "Eevee -> branch (Sylveon, Espeon, Umbreon, Leafeon, Glaceon, etc.)",
    298: "Azurill branch eligible",
    374: "Beldum -> Metang -> Metagross",
    443: "Gible -> Gabite -> Garchomp",
    280: "Ralts -> Kirlia -> Gardevoir or Gallade (branch)",
    281: "Kirlia -> Gardevoir or Gallade (branch, needs Sinnoh Stone for Gallade)",
}

# Eevee branch detection: pid 133 (Eevee) is the key branch parent.
EEVEELUTIONS = {
    "Vaporeon", "Jolteon", "Flareon",
    "Espeon", "Umbreon",
    "Leafeon", "Glaceon",
    "Sylveon",
}

# Branch-evo parents from gamemaster (computed below)
def normalize(name):
    """Lowercase, strip non-alnum: 'Mr. Mime' -> 'mrmime'."""
    return re.sub(r'[^a-z0-9]', '', name.lower())

# ----------------------- load data -----------------------
with open(f"{ROOT}\\pvpoke_gamemaster.json") as f:
    gm = json.load(f)
with open(f"{ROOT}\\pokedex_hundos_live.json") as f:
    hundos = json.load(f)
with open(f"{ROOT}\\form_enum.json") as f:
    form_enum = json.load(f)

# Hundo dex set: set of pids that already have a hundo dex entry
hundo_pids = set(int(e['pid']) for e in hundos['entries'] if e.get('hundo'))

# Build species -> pokemon entry maps. Key by normalized speciesName.
# Some species names have spaces or punctuation - normalize.
gm_pokemon = gm['pokemon']

# Map base speciesId (without _shadow suffix and without form suffix) to dex number
# and to "final form" detection.
base_id_to_dex = {}
species_id_to_entry = {}
for p in gm_pokemon:
    sid = p['speciesId']
    species_id_to_entry[sid] = p
    base_id_to_dex.setdefault(sid, p['dex'])

# Helper: does this species have evolutions? (returns list)
def get_evolutions(speciesId):
    p = species_id_to_entry.get(speciesId)
    if not p:
        return []
    return p.get('family', {}).get('evolutions', [])

# Walk to final form: follow evolutions[0] repeatedly. For branches, mark all.
def final_form(speciesId, _depth=0):
    """Return list of final-form speciesIds reachable from this start."""
    if _depth > 5:
        return [speciesId]
    evos = get_evolutions(speciesId)
    if not evos:
        return [speciesId]
    result = []
    for e in evos:
        result.extend(final_form(e, _depth + 1))
    # dedupe preserving order
    seen = set(); out = []
    for r in result:
        if r not in seen:
            seen.add(r); out.append(r)
    return out

# Build name -> speciesId map. species names in db come in like "Bulbasaur".
# In pvpoke, speciesName "Bulbasaur" -> speciesId "bulbasaur".
# Regional forms in db are encoded in `form` integer, but species_name stays English base.
# We'll need a (db_species_name, form_int) -> speciesId resolver.

# Form integer name (e.g. 70 = 'GravelerAlola'). Mapping rules:
#   "<Species>Normal" -> base
#   "<Species>Alola" -> "<base>_alolan"
#   "<Species>Galarian" -> "<base>_galarian"
#   "<Species>Hisuian" -> "<base>_hisuian"
#   "<Species>Paldean*" -> "<base>_paldean_<...>"

# Quick map from normalized species name -> dex (for fallback)
norm_name_to_speciesId_base = {}
for p in gm_pokemon:
    sid = p['speciesId']
    if '_shadow' in sid:
        continue  # use non-shadow base; shadow handled by alignment column if needed
    # skip form variants for base mapping
    norm_name_to_speciesId_base.setdefault(normalize(p['speciesName'].split(' (')[0]), sid)

def resolve_species_id(db_species_name, form_int):
    """Return the pvpoke speciesId for a given db species name + form int."""
    form_name = form_enum.get(str(form_int), '')
    # First try the form-name based lookup
    if form_name and form_name != 'Unset':
        # e.g. GeodudeAlola -> geodude_alolan
        # Strip trailing region suffix
        for suffix, sid_suffix in [
            ('Alola', '_alolan'),
            ('Galarian', '_galarian'),
            ('Hisuian', '_hisuian'),
            ('PaldeanCombat', '_paldea_combat'),
            ('PaldeanBlaze', '_paldea_blaze'),
            ('PaldeanAqua', '_paldea_aqua'),
        ]:
            if form_name.endswith(suffix):
                base = form_name[:-len(suffix)]
                cand = normalize(base) + sid_suffix
                if cand in species_id_to_entry:
                    return cand
                # fallback to base
                cand2 = normalize(base)
                if cand2 in species_id_to_entry:
                    return cand2
        # Form like "GravelerNormal" -> just "graveler"
        if form_name.endswith('Normal'):
            base = form_name[:-len('Normal')]
            cand = normalize(base)
            if cand in species_id_to_entry:
                return cand
    # Fallback: use species name
    return norm_name_to_speciesId_base.get(normalize(db_species_name))

# ----------------------- read DB -----------------------
conn = sqlite3.connect(f"{ROOT}\\pokemon.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Pull only in-bag mons with iv_total >= 37, that have any evolution path
# Also exclude pokemon_id 0 (placeholder rows)
c.execute("""
    SELECT uid_hex, pokemon_id, species_name, form, iv_atk, iv_def, iv_sta,
           iv_total, iv_pct, cp, is_hundo, alignment, alignment_name,
           is_shiny, is_lucky, is_purified_flag,
           cull_decision_v9, cull_reason_v9, auth_tag_names, nickname, level
    FROM pokemon
    WHERE in_bag = 1
      AND iv_total >= 37
      AND pokemon_id > 0
""")
rows = [dict(r) for r in c.fetchall()]
print(f"Loaded {len(rows)} candidate rows (in_bag, iv_total>=37, pid>0)")

# ----------------------- categorize -----------------------
candidates = []
counts = defaultdict(int)
buckets = defaultdict(list)

# Track: per (final_form speciesId) - is this in user's hundo dex?
# hundo dex uses pid. So map final-form speciesId back to dex/pid.
def final_pids(speciesId):
    finals = final_form(speciesId)
    out = []
    for fsid in finals:
        fp = species_id_to_entry.get(fsid)
        if fp:
            out.append((fsid, fp['dex'], fp['speciesName']))
    return out

# For branch evolutions, we want to know if the user already has each branch as a hundo
# If user has, e.g., Vaporeon hundo (pid 134) but not Espeon (196), an Eevee hundo would unlock Espeon -> still valuable.
# But Eevee->any-branch only fills one slot, so report it as branch-evo opportunity rather than auto-unlock.

for row in rows:
    sid = resolve_species_id(row['species_name'], row['form'])
    if not sid:
        continue
    # Check shadow alignment - shadow uses _shadow speciesId variant for chain lookup
    is_shadow = (row['alignment'] == 2 or row['alignment_name'] == 'SHADOW')
    is_purified = bool(row['is_purified_flag']) or row['alignment_name'] == 'PURIFIED'
    chain_sid = sid + '_shadow' if (is_shadow and (sid + '_shadow') in species_id_to_entry) else sid

    evos = get_evolutions(chain_sid)
    if not evos:
        continue  # no evolution: skip (it's already final form, candidate for transfer if low IV)

    finals = final_pids(chain_sid)
    # Strip _shadow from final spinames for hundo-dex lookup (hundo dex uses pid)
    final_pid_list = []
    for fsid, fdex, fname in finals:
        final_pid_list.append((fsid, fdex, fname))

    iv = row['iv_total']
    is_hundo = bool(row['is_hundo'])

    # Categorize
    reasons = []
    final_pids_set = set(fd for _, fd, _ in final_pid_list)
    final_names = [fn for _, _, fn in final_pid_list]

    # 1) Hundo dex unlock: this is a hundo, and at least one final form is NOT yet in hundo dex
    if is_hundo:
        missing_finals = [f for f in final_pid_list if f[1] not in hundo_pids]
        if missing_finals:
            reasons.append("hundo_dex_unlock")
            counts['hundo_dex_unlock'] += 1

    # 2) Trade-evolve species: high value to evolve via partner trade (saves candy)
    if row['pokemon_id'] in TRADE_EVOLVE_PIDS:
        reasons.append("trade_evolve")
        counts['trade_evolve'] += 1

    # 3) Branch-evo: pre-evo has multiple final forms (Eevee, Tyrogue, Wurmple, etc.)
    if len(evos) > 1 or len(final_pid_list) > 1:
        # find which branch finals user is missing from hundo dex (only relevant if this is hundo)
        if is_hundo:
            missing_branches = [fn for fsid, fdex, fn in final_pid_list if fdex not in hundo_pids]
            if missing_branches:
                reasons.append("branch_evo_missing_hundo")
                counts['branch_evo_missing_hundo'] += 1
        else:
            reasons.append("branch_evo")
            counts['branch_evo'] += 1

    # 4) Fill top 3: non-hundo high IV (iv_total >= 42 but < 45) that could fill a slot
    # We don't have the user's "top 3 by species" snapshot here; flag iv 42-44 as potential top-3 candidates
    if not is_hundo and iv >= 42:
        reasons.append("fill_top_3")
        counts['fill_top_3'] += 1

    if not reasons:
        continue  # skip lukewarm pre-evos that aren't special

    cand = {
        "uid_hex": row['uid_hex'],
        "species_name": row['species_name'],
        "pokemon_id": row['pokemon_id'],
        "form": row['form'],
        "iv": iv,
        "iv_atk": row['iv_atk'],
        "iv_def": row['iv_def'],
        "iv_sta": row['iv_sta'],
        "iv_pct": row['iv_pct'],
        "cp": row['cp'],
        "level": row['level'],
        "is_hundo": is_hundo,
        "is_shadow": is_shadow,
        "is_purified": is_purified,
        "is_shiny": bool(row['is_shiny']),
        "is_lucky": bool(row['is_lucky']),
        "nickname": row['nickname'],
        "cull_v9": row['cull_decision_v9'],
        "cull_reason_v9": row['cull_reason_v9'],
        "auth_tags": row['auth_tag_names'],
        "would_evolve_to": final_names,
        "would_evolve_to_pids": sorted(final_pids_set),
        "speciesId_chain": chain_sid,
        "candy_required": None,  # not in gamemaster
        "trade_evolve_note": TRADE_EVOLVE_PIDS.get(row['pokemon_id']),
        "reason": reasons,
    }
    candidates.append(cand)

    # Bucket for breakdown
    primary = reasons[0]
    buckets[primary].append(cand)

# ----------------------- sort / output -----------------------
# Sort: hundos first, then by iv desc, then by pid
def sort_key(c):
    return (
        0 if c['is_hundo'] else (1 if c['iv'] >= 44 else 2),
        -c['iv'],
        c['pokemon_id'],
    )
candidates.sort(key=sort_key)

# Highlighted (top priority): hundo with missing final-form dex entry, or trade-evolve hundo, or branch-evo with missing dex hundo branch
highlighted = []
for c in candidates:
    if c['is_hundo'] and ("hundo_dex_unlock" in c['reason'] or "branch_evo_missing_hundo" in c['reason']):
        highlighted.append(c)
    elif c['is_hundo'] and "trade_evolve" in c['reason']:
        highlighted.append(c)

out = {
    "generated_at": "2026-05-20",
    "source_db": "pokemon.db",
    "source_gm": "pvpoke_gamemaster.json",
    "source_hundo_dex": "pokedex_hundos_live.json",
    "totals": {
        "total_candidates": len(candidates),
        "hundo_dex_unlock": counts['hundo_dex_unlock'],
        "trade_evolve": counts['trade_evolve'],
        "branch_evo_missing_hundo": counts['branch_evo_missing_hundo'],
        "branch_evo": counts['branch_evo'],
        "fill_top_3": counts['fill_top_3'],
        "highlighted_priority": len(highlighted),
    },
    "highlighted": highlighted,
    "candidates": candidates,
}

with open(OUT, 'w') as f:
    json.dump(out, f, indent=2)

print(f"\nWrote {OUT}")
print(f"Total candidates: {len(candidates)}")
print("Breakdown by primary reason:")
for k, v in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
    print(f"  {k}: {len(v)}")
print(f"\nHighlighted (priority): {len(highlighted)}")
# Show top 15 highlighted
print("\nTop highlighted:")
for c in highlighted[:15]:
    note = c.get('trade_evolve_note') or ''
    extras = []
    if c['is_shiny']: extras.append('shiny')
    if c['is_lucky']: extras.append('lucky')
    if c['is_shadow']: extras.append('shadow')
    extra = ' [' + ','.join(extras) + ']' if extras else ''
    print(f"  {c['uid_hex'][:12]} {c['species_name']:<20} pid={c['pokemon_id']:<4} IV={c['iv']}/45 CP={c['cp']} -> {','.join(c['would_evolve_to'])}{extra}  {','.join(c['reason'])}  {note}")
