"""normalize_forms.py -- DATA-LAYER fix for PoGo proto form-id DRIFT.

EVERY DISTINCT NONZERO `form` CODE IS A SEPARATE VARIANT -- it keeps its OWN per-(pid,cf)
bundle/cap in keep_policy. We NEVER merge two genuine nonzero forms, even when pvpoke
lists the species as single-form (user 2026-06-04: "every variant is supposed to be
bundled too"). An earlier version COLLAPSED "drift" codes (Lapras 322+2585, Caterpie
953+3346) to one canonical; that wrongly dumped the user's 2585 Lapras into the 322 cap
and transferred them. That collapse is GONE.

The ONLY normalization left is a form-0 FOLD: a bare form-0 (UNSET) on a NON-blocklisted
species that ALSO has a real nonzero base-region code maps to that species' most-common
nonzero code -- killing the "form-0 phantom bucket" (Tauros/Persian) WITHOUT touching any
genuine nonzero form. Regionals (Alolan/Galarian/...) and blocklisted collectibles
(Unown/Spinda/...) are never touched. Raw value preserved in `fresh_form`.

Usage:
  python system/scripts/normalize_forms.py            # DRY-RUN (report only)
  python system/scripts/normalize_forms.py --apply    # write the DB
  # or import apply_to_db(conn) as a pipeline post-walk step.
"""
import sqlite3, json, os, sys, argparse
from collections import defaultdict, Counter
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from form_overrides_complete import FORM_OVERRIDES
from costume_forms import classify as _form_class, FORM_ENUM as _FENUM   # live Form enum -> 'base'/'costume'/...
DB = os.path.join(ROOT, 'pokemon.db')
GM = os.path.join(ROOT, 'pvpoke_gamemaster.json')
BASE_REG = ('', 'normal', 'kantonian', 'none', 'null')
REGIONAL = ('alola', 'galar', 'hisui', 'paldea')

# Cosmetic-collectible-form species pvpoke does NOT enumerate (so gm_base==1) yet which
# carry REAL distinct collectible forms. NEVER collapse these. Over-inclusion = safe.
COLLECTIBLE_BLOCKLIST = {
    201,            # Unown letters
    327,            # Spinda patterns
    664, 665, 666,  # Scatterbug / Spewpa / Vivillon wing patterns
    669, 670, 671,  # Flabebe / Floette / Florges flower colors
    676,            # Furfrou trims
    585, 586,       # Deerling / Sawsbuck seasons
    422, 423,       # Shellos / Gastrodon East-West sea
    592, 593,       # Frillish / Jellicent gender forms
    668,            # Pyroar gender (mane)
    550,            # Basculin red / blue stripe
    982,            # Dudunsparce two / three segment
    744,            # Rockruff (Own Tempo event form)
    774,            # Minior cores
    854, 855,       # Sinistea / Polteageist authentic / phony
    869,            # Alcremie creams + sweets
    931,            # Squawkabilly plumage
    925,            # Maushold family of three / four
    875,            # Eiscue ice / noice
    877,            # Morpeko full / hangry
    1012, 1013,     # Poltchageist / Sinistcha
}


def load_gm_base_counts():
    gm = json.load(open(GM, encoding='utf-8'))
    base = defaultdict(set)
    for p in gm['pokemon']:
        d = p.get('dex'); sid = p['speciesId']
        if not d or '_shadow' in sid or '_mega' in sid or any(r in sid for r in REGIONAL):
            continue
        base[d].add(sid)
    return {d: len(s) for d, s in base.items()}


def analyze(conn):
    """-> (collapse_pids, fold_pids, canonical:{pid:form}, names:{pid:name}).

    ONLY species with >1 DISTINCT nonzero base-region code are touched -- a single nonzero
    code is already collapsed by keep_policy.cf()'s form-0 handling, so single-code species
    (Bulbasaur 0+163) are left ALONE. Of the multi-nonzero species:
      collapse = formless drift (gm_base==1, not collectible, no FORM_OVERRIDES code) -> fold ALL base codes
      fold     = the rest that ALSO carry a bare form-0 phantom (Tauros/Persian) -> fold ONLY form-0
    """
    gm_base = load_gm_base_counts()
    codes = defaultdict(Counter); names = {}
    for r in conn.execute("SELECT pokemon_id pid, species_name nm, form, form_region fr, "
                          "fresh_costume fc, special_bg_id bg, natural_art_background ab, fresh_bread_mode br "
                          "FROM pokemon").fetchall():
        names[r['pid']] = r['nm']
        reg = (r['fr'] or '').strip().lower()
        plain = not (r['fc'] or r['bg'] or r['ab'] or r['br'])
        if reg in BASE_REG and plain:
            codes[r['pid']][r['form'] or 0] += 1
    canonical = {}; collapse = set(); fold = set()
    for pid, cnt in codes.items():
        nz = sorted({f for f in cnt if f != 0})
        if len(nz) <= 1:                                          # cf() already handles form-0 here -> skip
            continue
        # form-0 folds into the species' NORMAL base code (per the live enum), NOT merely the most-common --
        # else a NORMAL form-0 mon folds into a COSTUME bundle when the costume is the most-common code
        # (Falinks 2870=Gofest, Caterpie 3346=Gofest). Fall back to most-common only if no <Species>Normal
        # code is present in the bag. (2026-06-04)
        _bases = [f for f in nz if _form_class(_FENUM.get(f)) == 'base']
        canonical[pid] = sorted(_bases or nz, key=lambda f: (-cnt[f], f))[0]
        # DISTINCT NONZERO CODES ARE SEPARATE VARIANTS -- each keeps its OWN (pid,cf) bundle/cap; we NEVER
        # merge two genuine nonzero forms (user 2026-06-04: "every variant is supposed to be bundled too" --
        # merging Lapras 322+2585 wrongly transferred his 2585 Lapras). The ONLY fold is a bare form-0 (UNSET)
        # -> the most-common real code, to kill the form-0 phantom bucket (Tauros/Persian).
        if 0 in cnt and pid not in COLLECTIBLE_BLOCKLIST:
            fold.add(pid)
    return collapse, fold, canonical, names


def _new_form(pid, form, form_region, collapse, fold, canonical):
    reg = (form_region or '').strip().lower()
    if reg not in BASE_REG:                       # a proper regional form (Alolan/Galarian/...) -> untouched
        return form
    canon = canonical.get(pid)
    if canon is None:
        return form
    if pid in collapse:                           # formless drift -> collapse ALL base codes to canonical
        return canon
    if pid in fold and (form or 0) == 0:          # form-0 phantom on a multi-form/regional species -> fold it
        return canon
    return form                                   # genuine nonzero form -> keep


def backfill_latlon_from_s2(conn, apply=True, verbose=True):
    """Recover catch lat/lon from the raw S2 cell where the proto's parsed coords were dropped.

    `captured_s2_cell` is the leaf S2 cell of the catch; some rows keep it but drop the derived
    lat/lon (and, for 11 location cards, the loc enum/date too). Decoding the cell via s2sphere
    recovers the coords -- VALIDATED to 0.0deg error against rows that DID parse coords. Derived
    + non-destructive: only fills rows where lat IS NULL. lat/lon is pure metadata (NOT a keep
    criterion), so this NEVER changes tag/keep decisions. (2026-06-05) """
    try:
        import s2sphere
    except ImportError:
        if verbose:
            print("backfill_latlon_from_s2: s2sphere not installed -- SKIPPED (pip install s2sphere)")
        return []
    rows = conn.execute("SELECT uid_hex, captured_s2_cell s2 FROM pokemon "
                        "WHERE lat IS NULL AND captured_s2_cell IS NOT NULL").fetchall()
    fills = []
    for r in rows:
        s2 = r['s2']
        cid = s2 if s2 >= 0 else s2 + (1 << 64)            # stored signed; S2 cell ids are uint64
        try:
            ll = s2sphere.CellId(cid).to_lat_lng()
            fills.append((ll.lat().degrees, ll.lng().degrees, r['uid_hex']))
        except Exception:
            pass
    if verbose:
        print(f"lat/lon backfill from S2 cell: {len(fills)} rows recovered")
    if apply and fills:
        conn.executemany("UPDATE pokemon SET lat=?, lon=? WHERE uid_hex=?", fills)
        conn.commit()
    return fills


def apply_to_db(conn, apply=True, verbose=True):
    """Normalize the `form` column in `conn`. Returns the change list. fresh_form is left raw."""
    collapse, fold, canonical, names = analyze(conn)
    if verbose:
        print(f"COLLAPSE (formless drift, fold ALL base codes): {len(collapse)}")
        for pid in sorted(collapse):
            print(f"  {names.get(pid, '?'):<13}({pid}) -> {canonical[pid]}")
        print(f"FOLD (form-0 phantom only): {len(fold)}")
        for pid in sorted(fold):
            print(f"  {names.get(pid, '?'):<13}({pid}) form-0 -> {canonical[pid]}")
    changes = []
    for r in conn.execute("SELECT uid_hex, pokemon_id pid, species_name nm, form, form_region fr FROM pokemon").fetchall():
        nf = _new_form(r['pid'], r['form'] or 0, r['fr'], collapse, fold, canonical)
        if nf != (r['form'] or 0):
            changes.append((r['uid_hex'], r['nm'], r['form'] or 0, nf))
    if verbose:
        print(f"\n{len(changes)} rows change form:")
        for (nm, old, new), n in sorted(Counter((c[1], c[2], c[3]) for c in changes).items()):
            print(f"  {nm:<13} {old} -> {new}  x{n}")
    if apply:
        cur = conn.cursor()
        cur.executemany("UPDATE pokemon SET form=? WHERE uid_hex=?", [(nf, uid) for uid, nm, old, nf in changes])
        conn.commit()
    # backfill form_region for regional-named forms (GeodudeAlola, TaurosPaldea, RaichuAlola ...) that the
    # proto walk left blank -- derive it from the live enum NAME so the column is HONEST. Cosmetic-correctness
    # only: the keep engine keys on the form CODE (cf + FORM_OVERRIDES + _is_regional_code), not form_region,
    # so bundling is unchanged (verified 0 base/regional cf collisions). (2026-06-04 "everything perfect")
    REGNAME = (('alola', 'alolan'), ('galar', 'galarian'), ('hisui', 'hisuian'), ('paldea', 'paldean'))
    regfix = []
    for r in conn.execute("SELECT uid_hex, fresh_form, form_region FROM pokemon").fetchall():
        nmf = (_FENUM.get(r['fresh_form'] or 0) or '').lower()
        want = next((tag for key, tag in REGNAME if key in nmf), None)
        if want and (r['form_region'] or '').strip().lower() != want:
            regfix.append((want, r['uid_hex']))
    if verbose:
        print(f"form_region backfill (regional name, blank/wrong region): {len(regfix)}")
    if apply and regfix:
        cur = conn.cursor()
        cur.executemany("UPDATE pokemon SET form_region=? WHERE uid_hex=?", regfix)
        conn.commit()
    # recover catch lat/lon from the raw S2 cell where the proto walk dropped the parsed coords
    # (the 'no-location' location cards + any mon missing coords; validated 0deg error). (2026-06-05)
    backfill_latlon_from_s2(conn, apply=apply, verbose=verbose)
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write the DB (default = dry-run report)')
    a = ap.parse_args()
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    changes = apply_to_db(conn, apply=a.apply)
    print(f"\n{'APPLIED' if a.apply else 'DRY-RUN'}: {len(changes)} form normalizations"
          f"{' (fresh_form preserved as raw)' if a.apply else ' (no write)'}")
    conn.close()


if __name__ == '__main__':
    main()
