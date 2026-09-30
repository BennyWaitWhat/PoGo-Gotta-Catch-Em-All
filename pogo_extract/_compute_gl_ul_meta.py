#!/usr/bin/env python3
"""Compute protected uid_hex set for keep-rule gl_ul_meta.

Spec (verbatim from task):
- Strict PvP, NON-shadow only.
- GL meta universe = top-30 speciesId BY SCORE in _gl1500.json.
- For each meta species: the best (min rank) owned NON-shadow specimen via
  gl_chain_ranks (parse "form:rank(pct%)") whose rank<=5 AND that ranked form
  maxcp>=1400.
- maxCP(speciesId)@L50 = floor((atk+15)*sqrt(def+15)*sqrt(hp+15)*0.84029999^2/10),
  baseStats from pvpoke_gamemaster.json (pokemon[].baseStats); shadow forms use
  <speciesId>_shadow.
- Same for UL (_ul2500.json, ul_chain_ranks, rank<=5, maxcp>=2400).
- Union GL+UL.
"""
import json, sqlite3, re, math, os

BASE = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
DB   = os.path.join(BASE, "pokemon.db")
GM   = os.path.join(BASE, "pvpoke_gamemaster.json")
GL_J = os.path.join(BASE, "_gl1500.json")
UL_J = os.path.join(BASE, "_ul2500.json")
OUT  = os.path.join(BASE, "system", "analysis", "policy_sets", "gl_ul_meta.txt")

CPM50_SQ = 0.84029999 ** 2  # the 0.84029999^2 term per spec

# ---- baseStats + maxCP --------------------------------------------------
gm = json.load(open(GM, encoding="utf-8"))
BS = {p["speciesId"]: p["baseStats"] for p in gm["pokemon"]}

def maxcp(species_id):
    """L50 max CP per spec formula. Falls back to non-shadow base if a
    _shadow id is absent (raw stats are identical anyway)."""
    b = BS.get(species_id)
    if b is None and species_id.endswith("_shadow"):
        b = BS.get(species_id[:-7])
    if b is None:
        return None
    a, d, h = b["atk"], b["def"], b["hp"]
    return math.floor((a + 15) * math.sqrt(d + 15) * math.sqrt(h + 15) * CPM50_SQ / 10)

def strip_shadow(sid):
    return sid[:-7] if sid.endswith("_shadow") else sid

# ---- meta universes (top-30 BY SCORE) -----------------------------------
def top30(path):
    d = json.load(open(path, encoding="utf-8"))
    return [e["speciesId"] for e in sorted(d, key=lambda z: -z["score"])[:30]]

GL_META = top30(GL_J)
UL_META = top30(UL_J)

# ---- parse a chain_ranks string -> {form: (rank, pct)} ------------------
CR = re.compile(r"^([^:]+):(\d+)\(([\d.]+)%\)$")
def parse_chain(s):
    out = {}
    if not s:
        return out
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        m = CR.match(part)
        if not m:
            continue
        form, rank, pct = m.group(1), int(m.group(2)), float(m.group(3))
        out[form] = (rank, pct)
    return out

# ---- load owned NON-shadow specimens ------------------------------------
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT uid_hex, pokemon_id, form, fresh_alignment, iv_total, cp, level, "
    "gl_chain_ranks, ul_chain_ranks "
    "FROM pokemon WHERE in_bag=1 AND fresh_alignment != 1"
).fetchall()

def compute_league(meta, chain_col, cp_floor):
    """Return {meta_species: chosen_row} and a detail dict for sampling."""
    protected = {}   # meta_species -> (uid_hex, rank, deciding info)
    for ms in meta:
        key = strip_shadow(ms)            # chain forms are non-shadow speciesIds
        floor_ok_cache = {}
        candidates = []                   # (rank, -iv_total, -cp, uid_hex, info)
        for r in rows:
            chain = parse_chain(r[chain_col])
            if key not in chain:
                continue
            rank, pct = chain[key]
            if rank > 5:
                continue
            # CP-floor: the RANKED form must reach the league cap.
            mc = floor_ok_cache.get(key)
            if mc is None:
                mc = maxcp(key)
                floor_ok_cache[key] = mc
            if mc is None or mc < cp_floor:
                continue
            # tiebreak min rank, then IV, then CP (policy metric)
            candidates.append((rank, -(r["iv_total"] or 0), -(r["cp"] or 0),
                               r["uid_hex"],
                               {"rank": rank, "pct": pct, "maxcp": mc,
                                "iv": r["iv_total"], "cp": r["cp"],
                                "form_key": key}))
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
            best = candidates[0]
            protected[ms] = (best[3], best[4])
    return protected

gl = compute_league(GL_META, "gl_chain_ranks", 1400)
ul = compute_league(UL_META, "ul_chain_ranks", 2400)

# ---- union --------------------------------------------------------------
uid_to_reason = {}   # uid_hex -> list of (league, meta_species, info)
for league, res in (("GL", gl), ("UL", ul)):
    for ms, (uid, info) in res.items():
        uid_to_reason.setdefault(uid, []).append((league, ms, info))

uids = sorted(uid_to_reason.keys())

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    for u in uids:
        f.write(u + "\n")

# ---- diagnostics --------------------------------------------------------
print("GL meta universe (top30 by score):")
print("  " + ", ".join(GL_META))
print("UL meta universe (top30 by score):")
print("  " + ", ".join(UL_META))
print()
print(f"GL species with a protected specimen: {len(gl)}/30")
print(f"UL species with a protected specimen: {len(ul)}/30")
gl_no = [m for m in GL_META if m not in gl]
ul_no = [m for m in UL_META if m not in ul]
print("GL meta species with NO qualifying owned non-shadow specimen:")
print("  " + (", ".join(gl_no) if gl_no else "(none)"))
print("UL meta species with NO qualifying owned non-shadow specimen:")
print("  " + (", ".join(ul_no) if ul_no else "(none)"))
print()
print(f"UNION uid count: {len(uids)}")
print(f"  (GL contributes {len(gl)} uids, UL {len(ul)} uids; "
      f"overlap = {len(gl)+len(ul)-len(uids)})")
print()
print("=== Per-species detail (GL) ===")
for ms in GL_META:
    if ms in gl:
        uid, info = gl[ms]
        print(f"  {ms:30s} uid={uid} rank={info['rank']} maxcp(form={info['form_key']})={info['maxcp']} iv={info['iv']} cp={info['cp']}")
print("=== Per-species detail (UL) ===")
for ms in UL_META:
    if ms in ul:
        uid, info = ul[ms]
        print(f"  {ms:30s} uid={uid} rank={info['rank']} maxcp(form={info['form_key']})={info['maxcp']} iv={info['iv']} cp={info['cp']}")

# show any meta species that had specimens but failed ONLY the cp-floor (for notes)
print()
print("=== Diagnostics: meta species failing CP-floor despite owning a rank<=5 specimen ===")
for meta, chain_col, floor, label, res in [
        (GL_META, "gl_chain_ranks", 1400, "GL", gl),
        (UL_META, "ul_chain_ranks", 2400, "UL", ul)]:
    for ms in meta:
        if ms in res:
            continue
        key = strip_shadow(ms)
        mc = maxcp(key)
        # did any owned non-shadow specimen have rank<=5 for this form?
        had_rank = False
        for r in rows:
            ch = parse_chain(r[chain_col])
            if key in ch and ch[key][0] <= 5:
                had_rank = True
                break
        if had_rank and (mc is None or mc < floor):
            print(f"  {label} {ms:28s} maxcp(form={key})={mc} < {floor}  -> rank<=5 owned but CP-floor fails")
