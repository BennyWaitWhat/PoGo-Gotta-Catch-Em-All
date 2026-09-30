"""Accurate legacy-move detector.

A Pokemon has a legacy move when it knows a move that is NOT part of its
current, normally-rollable movepool for its specific form. We define the
current movepool from pvpoke_gamemaster.json:

  rollable = (fastMoves U chargedMoves) - eliteMoves

`eliteMoves` are obtainable only via Elite TM (past Community Day / event
moves), i.e. legacy. So a move on a Pokemon is legacy if it is either:
  - in that form's eliteMoves, or
  - not in that form's (fastMoves U chargedMoves) at all.

RETURN and FRUSTRATION are never treated as legacy (shadow/purified artifacts).
move2/move3 == 0 (or NULL) are empty slots and skipped.

Reads pokemon.db read-only. Writes legacy_accurate.json.
"""
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "pokemon.db"
GM = ROOT / "pvpoke_gamemaster.json"
MOVE_MAP = ROOT / "move_id_to_name.json"
FORM_ENUM = ROOT / "form_enum.json"
OUT = ROOT / "legacy_accurate.json"

NEVER_LEGACY = {"RETURN", "FRUSTRATION"}

# The DB (IL2CPP enum) and pvpoke gamemaster spell some moves differently.
# Punctuation-only differences:
MOVE_ALIASES = {
    "FUTURESIGHT": "FUTURE_SIGHT",
    "PYROBALL": "PYRO_BALL",
}
# Multi-type move families: the DB names a single typed instance (e.g.
# HIDDEN_POWER, TECHNO_BLAST_WATER) while the gamemaster lists per-type variants
# (HIDDEN_POWER_FIRE, TECHNO_BLAST_DOUSE, ...). For legality we only care that
# the species can learn *some* variant, so we collapse both sides to the family
# prefix before comparing.
MOVE_FAMILIES = ("HIDDEN_POWER", "TECHNO_BLAST")


# Aegislash's Shield form prefixes its fast moves (AEGISLASH_CHARGE_AIR_SLASH);
# the DB and Blade form use the plain name. Strip the prefix to compare equal.
AEGISLASH_PREFIX = "AEGISLASH_CHARGE_"


def canon_move(name: str) -> str:
    """Canonicalize a move name so DB and gamemaster spellings compare equal."""
    name = MOVE_ALIASES.get(name, name)
    if name.startswith(AEGISLASH_PREFIX):
        name = name[len(AEGISLASH_PREFIX):]
    for fam in MOVE_FAMILIES:
        if name.startswith(fam):
            return fam
    return name

# form_enum CamelCase token -> gamemaster speciesId qualifier token.
# Only tokens that change the gamemaster key need an entry; unmapped tokens are
# treated as cosmetic and ignored (so e.g. Pikachu costumes fall back to base).
TOKEN_SYNONYMS = {
    "alola": "alolan",
    "alolan": "alolan",
    "galarian": "galarian",
    "hisuian": "hisuian",
    "paldea": "paldean",
    "paldean": "paldean",
    "pompom": "pom",
    "incarnate": "incarnate",
    "therian": "therian",
}

# Real movepool-changing form qualifiers in the gamemaster. A form_enum token is
# only used for matching if it maps into this vocabulary (built at runtime from
# the gamemaster); everything else is cosmetic and dropped.


def camel_tokens(name: str) -> list[str]:
    # split CamelCase / digit runs into lowercase tokens
    parts = re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|\d+", name)
    return [p.lower() for p in parts]


def _base_slug(entries):
    """The canonical species slug for a dex (form-less, shadow-less)."""
    cands = [e for e in entries if "(" not in e["speciesName"]] or entries
    cands = sorted(cands, key=lambda e: ("shadow" in e["speciesId"], len(e["speciesId"])))
    return cands[0]["speciesId"].replace("_shadow", "")


def load_gamemaster():
    gm = json.loads(GM.read_text(encoding="utf-8"))
    raw_by_dex: dict[int, list] = defaultdict(list)
    for x in gm["pokemon"]:
        raw_by_dex[x["dex"]].append(x)

    # index by dex -> list of (qualifier_token_set, is_shadow, entry)
    by_dex: dict[int, list] = defaultdict(list)
    gm_qualifier_vocab: set[str] = set()
    for dex, entries in raw_by_dex.items():
        base = _base_slug(entries).split("_")
        for x in entries:
            toks = x["speciesId"].split("_")
            if toks[: len(base)] == base:
                rest = toks[len(base):]
            else:
                rest = [t for t in toks if t not in base]
            is_shadow = "shadow" in rest
            quals = frozenset(t for t in rest if t != "shadow")
            gm_qualifier_vocab.update(quals)
            by_dex[dex].append((quals, is_shadow, x))
    return by_dex, gm_qualifier_vocab


def rollable_and_elite(entry):
    fast = {canon_move(m) for m in entry.get("fastMoves", [])}
    charged = {canon_move(m) for m in entry.get("chargedMoves", [])}
    elite = {canon_move(m) for m in entry.get("eliteMoves", [])}
    full = fast | charged
    rollable = full - elite
    return rollable, elite, full


def normalize_db_move(move_id, move_map):
    if move_id in (None, 0):
        return None
    name = move_map.get(str(move_id))
    if name is None:
        return ("__UNKNOWN__", move_id)
    if name.endswith("_FAST"):
        name = name[: -len("_FAST")]
    return name


def build_form_resolver(by_dex, form_enum):
    """Return fn(dex, form_int, species_name, is_shadow) -> matched gm entry or None."""

    def resolve(dex, form_int, species_name, is_shadow):
        candidates = by_dex.get(dex)
        if not candidates:
            return None, "no_dex_entry"
        if len(candidates) == 1:
            return candidates[0][2], "single"

        dex_quals_vocab = set()
        for q, _s, _e in candidates:
            dex_quals_vocab |= q

        form_name = form_enum.get(str(form_int), "")
        toks = camel_tokens(form_name)
        # strip species-name tokens (form_enum repeats the species, e.g.
        # "DialgaOrigin" -> drop "dialga"). Use the gamemaster speciesName tokens.
        gm_name = candidates[0][2]["speciesName"]
        sp_clean = re.sub(r"\(.*?\)", "", gm_name)
        sp_toks = set(camel_tokens(re.sub(r"[^A-Za-z0-9]", "", sp_clean)))
        sp_toks |= set(camel_tokens(re.sub(r"[^A-Za-z0-9]", "", species_name or "")))
        raw_quals = []
        for t in toks:
            if t in sp_toks:
                continue
            mapped = TOKEN_SYNONYMS.get(t, t)
            # only treat as a real qualifier if THIS dex actually uses it
            if mapped in dex_quals_vocab:
                raw_quals.append(mapped)
        want = frozenset(raw_quals)

        # Among candidates, prefer matching shadow dimension, then qual-set.
        shadow_pref = [c for c in candidates if c[1] == is_shadow] or candidates

        # 1) exact qualifier-set match
        for quals, shd, entry in shadow_pref:
            if quals == want:
                return entry, f"exact:{sorted(want)}"
        # 2) base (no qualifiers) entry - cosmetic forms fall here
        for quals, shd, entry in shadow_pref:
            if not quals:
                return entry, f"base(want={sorted(want)})"
        # 3) any entry whose qualifiers are a subset of want (best partial)
        best = None
        for quals, shd, entry in shadow_pref:
            if quals <= want and (best is None or len(quals) > len(best[0])):
                best = (quals, entry)
        if best:
            return best[1], f"subset:{sorted(best[0])}"
        # 4) give up -> first candidate (avoid crashing); flag it
        return shadow_pref[0][2], "fallback_first"

    return resolve


GM_CLIENT = ROOT / "gamemaster_pokeminers.json"


def _game_master_rollable(move_map, gm=None):
    """{pokedex number: every move the CLIENT game master lets some form of that species roll NORMALLY today
    (quickMoves + cinematicMoves only -- never eliteQuickMove / eliteCinematicMove / nonTmCinematicMoves)}.
    THE GAME OUTRANKS PVPOKE (2026-09-23): pvpoke still listed Body Slam as elite for Audino and Seed Flare for
    Shaymin while the client's own template rolls them from a plain TM, so 6 tagged "Legacy Moves" were untrue
    (audit_tag_truth). A pvpoke elite flag is dropped when the game says the move is ordinary now. Empty if the
    file is missing -> nothing is dropped.
    `gm` (2026-09-30, gm_guard): an ALREADY-PARSED template list to judge instead of the installed file, so a candidate
    client game master can be compared with the installed one before it is installed. None = the installed file,
    exactly as before (including 'missing -> {}'); the caller of a `gm` owns its validity."""
    if gm is None:
        if not GM_CLIENT.exists():
            return {}
        gm = json.loads(GM_CLIENT.read_text(encoding="utf-8"))
    names = {int(k): v for k, v in move_map.items()}
    pools = defaultdict(set)
    for t in gm:
        s = (t.get("data") or {}).get("pokemonSettings")
        m = re.match(r"V(\d{4})_POKEMON_", t.get("templateId", ""))
        if not s or not m:
            continue
        elite = set()
        for k in ("eliteQuickMove", "eliteCinematicMove"):
            for x in s.get(k) or []:
                n = names.get(x) if isinstance(x, int) else x
                if n:
                    elite.add(n)
        for k in ("quickMoves", "cinematicMoves"):
            for x in s.get(k) or []:
                n = names.get(x) if isinstance(x, int) else x
                if n and n not in elite:
                    pools[int(m.group(1))].add(n)
    return pools


def _game_master_pools(move_map, gm=None):
    """{pokedex number: every move ANY form of that species can roll normally}, from the client game master.
    Empty dict if the file is missing -- the pvpoke test above still stands alone then.
    `gm`: an already-parsed template list to judge instead of the installed file (see _game_master_rollable)."""
    if gm is None:
        if not GM_CLIENT.exists():
            return {}
        gm = json.loads(GM_CLIENT.read_text(encoding="utf-8"))
    names = {int(k): v for k, v in move_map.items()}
    pools = defaultdict(set)
    for t in gm:
        s = (t.get("data") or {}).get("pokemonSettings")
        m = re.match(r"V(\d{4})_POKEMON_", t.get("templateId", ""))
        if not s or not m:
            continue
        for k in ("quickMoves", "cinematicMoves", "nonTmCinematicMoves"):
            for x in s.get(k) or []:
                n = names.get(x) if isinstance(x, int) else x
                if n:
                    pools[int(m.group(1))].add(n)
    return pools


def main():
    move_map = json.loads(MOVE_MAP.read_text(encoding="utf-8"))
    form_enum = json.loads(FORM_ENUM.read_text(encoding="utf-8"))
    by_dex, _gm_vocab = load_gamemaster()
    resolve = build_form_resolver(by_dex, form_enum)

    # Union of every form's learnable pool per dex. Used only to suppress a
    # form-detection gap: if a move is off the matched form's pool but is a
    # normal move on a SIBLING form (e.g. a Paldean Tauros stored with form
    # Unset, or a costumed Galarian Corsola), it's a mis-identified form, not a
    # legacy move. Elite-move flags are never suppressed this way.
    dex_union_pool = {}
    for dex, cands in by_dex.items():
        u = set()
        for _q, _s, e in cands:
            _r, _el, full = rollable_and_elite(e)
            u |= full
        dex_union_pool[dex] = u

    # THE GAME'S OWN MOVEPOOL (2026-09-17, user "learn more about what the game has for info"). pvpoke's lists are a
    # third party's; the client game master is what the game enforces. Species-wide (every form's quickMoves +
    # cinematicMoves + nonTmCinematicMoves -- numeric ids named through move_id_to_name.json), so a form-change move
    # of a sibling form never reads as legacy. A move NO form of the species can roll today is special, whatever
    # pvpoke says: 30 in-bag mons were missed this way (Raichu Volt Tackle, Snorlax Psywave, Dialga Roar of Time,
    # Palkia Spacial Rend, Houndoom Incinerate, Grafaiai Foul Play, Maschiff/Mabosstiff Psychic Fangs, Smeargle's
    # sketched moves ...). UNION only: this can add protection, never remove it.
    gm_normal = _game_master_pools(move_map)
    gm_rollable = _game_master_rollable(move_map)     # the game's plain-TM pool: vetoes a stale pvpoke elite flag
    stale_elite = defaultdict(int)                   # pvpoke said elite, the game rolls it normally

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        """SELECT uid_hex, pokemon_id, species_name, move1, move2, move3,
                  form, iv_total, alignment
           FROM pokemon WHERE in_bag=1"""
    )
    rows = cur.fetchall()
    con.close()

    results = []
    unknown_moves = defaultdict(int)
    species_counts = defaultdict(int)
    match_reasons = defaultdict(int)
    form_mismatch_suppressed = defaultdict(int)
    game_only = defaultdict(int)                # moves only the real game master calls special
    no_movepool = 0
    unjudgeable_form = 0        # resolver gave up on the form -> protected, not skipped

    for uid_hex, pid, species, m1, m2, m3, form, ivt, alignment in rows:
        is_shadow = alignment in (1, 2)  # shadow or purified share base pool
        entry, reason = resolve(pid, form, species or "", is_shadow)
        match_reasons[reason.split(":")[0].split("(")[0]] += 1
        if entry is None:
            # NO MOVEPOOL AT ALL for this dex -> we CANNOT judge whether this mon's moves are
            # legacy. Unjudgeable must default to PROTECTED, not to "not legacy": silently
            # dropping it removed its only keep axis and put it in the irreversible Transfer
            # pile. Emit an explicit marker so keep_policy/build_tagsets keep it and the human
            # can see WHY it is flagged. (lockdown 2026-09-02)
            no_movepool += 1
            species_counts[species] += 1
            results.append({"uid_hex": uid_hex, "species_name": species,
                            "legacy_moves": ["UNKNOWN_FORM_POOL"], "iv_total": ivt})
            continue
        rollable, elite, full = rollable_and_elite(entry)

        # The form resolver GAVE UP and returned an arbitrary candidate ('fallback_first'), so the
        # movepool we are about to compare against is not this specimen's. Same rule as above:
        # unjudgeable -> PROTECTED. (0 live rows today; this is the guard, not a behaviour change.)
        if reason == "fallback_first":
            unjudgeable_form += 1
            species_counts[species] += 1
            results.append({"uid_hex": uid_hex, "species_name": species,
                            "legacy_moves": ["UNKNOWN_FORM_MATCH"], "iv_total": ivt})
            continue

        union = dex_union_pool.get(pid, full)
        legacy_moves = []
        for raw in (m1, m2, m3):
            nm = normalize_db_move(raw, move_map)
            if nm is None:
                continue
            if isinstance(nm, tuple):  # unknown id -- move_id_to_name.json is older than the game
                # A move we cannot NAME cannot be checked against the movepool. Treat it as
                # LEGACY (protected) instead of skipping it: skipping made the mon look
                # move-clean and a live Cramorant with move id 593 (map max id 497) landed in
                # the irreversible Transfer pile. Unknown data => PROTECTED. (lockdown 2026-09-02)
                unknown_moves[nm[1]] += 1
                legacy_moves.append(f"UNKNOWN_MOVE_{nm[1]}")
                continue
            if nm in NEVER_LEGACY:
                continue
            cm = canon_move(nm)
            _game_nm = move_map.get(str(raw)) if raw not in (None, 0) else None      # the GAME's spelling
            if cm in elite and gm_rollable.get(pid) and _game_nm in gm_rollable[pid]:
                stale_elite[species] += 1        # pvpoke's elite list lags: the client rolls this move from a TM now
                continue
            if cm in elite:
                legacy_moves.append(nm)  # elite-only: always legacy
            elif cm not in full:
                # off this form's pool. If it's a normal move on a sibling form,
                # the stored form is mis-identified - skip. Otherwise it's a real
                # off-pool (event) move.
                if cm not in union:
                    legacy_moves.append(nm)
                else:
                    form_mismatch_suppressed[species] += 1

        _pool = gm_normal.get(pid)
        if _pool:                                   # the game's own answer, added to pvpoke's (never replacing it)
            for raw in (m1, m2, m3):
                nm = normalize_db_move(raw, move_map)          # pvpoke spelling (no _FAST), for the output
                full_nm = move_map.get(str(raw)) if raw not in (None, 0) else None   # the GAME's spelling
                if nm is None or isinstance(nm, tuple) or not full_nm or nm in NEVER_LEGACY or nm in legacy_moves:
                    continue
                if full_nm not in _pool:
                    legacy_moves.append(nm)
                    game_only[species] += 1

        if legacy_moves:
            species_counts[species] += 1
            results.append(
                {
                    "uid_hex": uid_hex,
                    "species_name": species,
                    "legacy_moves": legacy_moves,
                    "iv_total": ivt,
                }
            )

    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    if stale_elite:
        print("pvpoke elite flags dropped because the client game master rolls the move normally: %s"
              % dict(stale_elite))

    # ---- report ----
    print(f"in_bag pokemon scanned : {len(rows)}")
    print(f"flagged with legacy    : {len(results)}")
    print(f"(old has_legacy_move count was 801)")
    print(f"rows with no movepool match: {no_movepool}"
          + ("  [PROTECTED as UNKNOWN_FORM_POOL -- movepool unjudgeable]" if no_movepool else ""))
    print(f"rows with fallback form match: {unjudgeable_form}"
          + ("  [PROTECTED as UNKNOWN_FORM_MATCH]" if unjudgeable_form else ""))
    print(f"match reasons          : {dict(match_reasons)}")
    if game_only:
        print(f"special per the GAME MASTER only (pvpoke called them normal): {dict(game_only)}")
    if form_mismatch_suppressed:
        print(f"form-mismatch moves suppressed (sibling-form moves): {dict(form_mismatch_suppressed)}")
    if unknown_moves:
        print(f"unknown move IDs (id->count): {dict(sorted(unknown_moves.items()))}")
        print("  ^ these ids are NOT in move_id_to_name.json (regenerate it). Every mon holding one is"
              " flagged UNKNOWN_MOVE_<id> = LEGACY so it can never reach the Transfer pile unjudged.")
    print("\nTop 20 species by legacy count:")
    for sp, n in sorted(species_counts.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {n:4d}  {sp}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
