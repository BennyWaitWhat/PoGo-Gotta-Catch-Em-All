"""keep_policy.py -- the finalized keep policy (system/KEEP_POLICY.md) as ONE engine.

Purpose-or-trim: a mon is KEPT if it earns any purpose below, else it goes in the
TRANSFER pile (-> the '6 Transfer' review tag; human transfers in-game). IV (total)
is the strength metric everywhere; CP only gates GL/UL reachability.

DB-only, no device. Writes the TRANSFER set to system/analysis/tagsets/6_Transfer.txt
and a per-mon reason map to system/analysis/policy_reasons.json, and prints the
breakdown (totals, per-rule, newly-trimmed vs cull_v9, top transfer species).
"""
import sqlite3, json, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import keep_config   # single source of truth for every tunable cap/roster (dashboard-editable)
from pvp_iv_rule import plays
from pvp_iv_rule import (qualifies as pvp_iv_qualifies, pvid, GL_CAP, UL_CAP, ML_CAP, maxcp as pvp_maxcp,
                         READY_RANK, VIABILITY_MARGIN, usable_best)
import costume_forms
from costume_forms import is_costume_form
import evolvable_forms                                  # per-FORM evolvability from the real game master (2026-09-16)
import pattern_pools   # pattern-pooled lines (Scatterbug/Spewpa/Vivillon): ONE plain cap per pattern across the whole line (user 2026-09-08)
# enum_ok()/LOAD_ERROR are the 2026-09-02 fail-loud hooks. getattr fallbacks so an older costume_forms.py
# (or a partial revert) degrades to "assume the enum is fine" -- the pre-guard behaviour -- instead of
# raising AttributeError at import and taking the whole engine down.
def costume_forms_enum_ok():
    fn = getattr(costume_forms, 'enum_ok', None)
    return fn() if fn else bool(getattr(costume_forms, 'FORM_ENUM', None))
def costume_forms_load_error():
    return getattr(costume_forms, 'LOAD_ERROR', None)
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS  # authoritative roster (NULL-column-proof)
DB = os.path.join(ROOT, 'pokemon.db')
TD = os.path.join(ROOT, 'system', 'analysis', 'tagsets'); os.makedirs(TD, exist_ok=True)

def _ae_ids_live():
    """Adventure-Effect roster = keep_config hand list UNION the species derived from the GAME'S OWN registry.

    User 2026-09-08: the roster "should be scanned every time". pogo_pipeline reads
    AdventureEffectService.adventureEffects in-walk -> system/analysis/ae_registry_live.json;
    system/scripts/derive_ae_roster.py turns it into system/analysis/ae_roster_derived.json. On 2026-09-08 the
    live registry held 11 effects vs the hand list's 9 (Mega Mewtwo X/Y were new). UNION ONLY: this can add
    protection, never remove it, so a stale or missing derived file degrades to the hand list -- fail-soft.
    """
    ids = set(keep_config.ae_pids())
    try:
        import json as _j, time as _t
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'analysis', 'ae_roster_derived.json')
        if os.path.exists(_p) and (_t.time() - os.path.getmtime(_p)) < 14 * 86400:
            _d = _j.load(open(_p, encoding='utf-8'))
            extra = {int(x) for x in _d.get('species', [])} - ids
            if extra:
                print('[adventure_effect] live registry adds %s to the configured roster %s' % (sorted(extra), sorted(ids)))
            ids |= {int(x) for x in _d.get('species', [])}
    except Exception as _e:                                   # fail-soft: hand list only
        print('[adventure_effect] derived roster unreadable (%s) -- using keep_config list only' % _e)
    return ids


AE_IDS = _ae_ids_live()                          # adventure-effect roster: keep_config UNION live game registry (2026-09-08)


def _ae_sids_live():
    """FORM-level Adventure-Effect roster: the PvPoke speciesIds whose movepool carries a live-registry effect move
    (derive_ae_roster.py schema 2, 'species_ids'). The in-game filter counts FORMS (Origin Dialga, Crowned Zacian...),
    not species -- an Altered Dialga has no effect (user 2026-09-09: "if it doesnt have the adventure effect, i dont
    want it tagged"). None when the derived file is missing/stale/too old -> rule 8 falls back to the SPECIES list,
    which over-protects (safe direction). Never empty-and-trusted: an empty set also falls back."""
    try:
        import json as _j, time as _t
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'analysis', 'ae_roster_derived.json')
        if os.path.exists(_p) and (_t.time() - os.path.getmtime(_p)) < 14 * 86400:
            _d = _j.load(open(_p, encoding='utf-8'))
            sids = set((_d.get('species_ids') or {}).keys())
            if sids:
                return sids
    except Exception as _e:
        print('[adventure_effect] form-level roster unreadable (%s) -- species list only' % _e)
    return None


AE_SIDS = _ae_sids_live()                        # FORM-level roster -- now only the FALLBACK (see AE_MOVES), 2026-09-09
# PER-MON Adventure Effect (2026-09-23): the game grants it to a Pokemon that KNOWS the effect's move; the form alone
# (every Origin Dialga) tagged 38 mons of which 19 knew it. None -> registry unreadable -> the form/species fallback.
import ae_moves as _ae_moves
AE_MOVES = _ae_moves.move_ids()
PROTECTED_KEEP_ALL = keep_config.protected_pids()  # pids FULLY exempt from every cull cap -- Pichu (keep_config.json). Add a pid for any "leave them alone" species.
GL_FLOOR, UL_FLOOR = keep_config.pvp('gl_floor'), keep_config.pvp('ul_floor')
# (removed 2026-06-03, AST-verified unused & imported by nothing: GENDER_EVO/MALE_DEADEND superseded by
#  GENDER_TERMINALS; PVP_RANK/CPM50/maxcp/parse_chain -> PvP maxcp+rank live in pvp_iv_rule.py.)


def topn(rows, n, bg_first=False):
    # uid as final tiebreak: stat-identical dupes otherwise fall to SQLite rowid order, which a recrawl
    # can reshuffle -- the irreversible Transfer membership must be reproducible run-to-run (audit F25).
    # COLLECTION FLOOR (user 2026-09-24 "thats the floor now"): every capped collection ladder that ranks by IV --
    # plain, costume / Max variants, legendary top-N, legacy fill, location cards, the card comb-up, the evolve
    # surplus list -- drops a copy under keep_config.collection_floor_iv (25%) unless it is the ladder's best.
    # keep_config.floor_top is the ONE implementation, shared with audit_cull / _lawcheck / preflight_transfer.
    # bg_first (2026-09-24): a COSTUME ladder puts its background copies first (costume_forms.backgrounds_first).
    _s = sorted(rows, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0), r['uid_hex']))
    return keep_config.floor_top(costume_forms.backgrounds_first(_s) if bg_first else _s)[:n]


# Field separator for db_content_sha256(). chr(0x1f) = ASCII UNIT SEPARATOR: repr() escapes every
# control character, so this byte can never occur inside a rendered value and the join is
# unambiguous. Written as chr() rather than an escape so the source carries no literal control
# byte and no editor/heredoc can silently change what the separator IS.
_DBHASH_SEP = chr(0x1f)


def db_content_sha256(src):
    """CONTENT hash of the pokemon-table snapshot a pile was computed from -- THE one definition.

    Producer: keep_policy (stamped into system/analysis/pile_provenance.json as 'db_content_sha256').
    Consumer: audit_invariants.py, staleness family. Producer and consumer MUST derive the SAME digest
    for the same snapshot or the check inverts into a permanent false alarm, so this is ONE shared
    function -- import it, do not re-derive it:   from keep_policy import db_content_sha256
    (Same pattern, and same reason, as keep_config.fingerprint() for config_sha256.)

    WHY: provenance identified the database by db_mtime/db_size alone. Those are FILESYSTEM facts, not
    content facts. pokemon.db runs in WAL mode, so the main file is rewritten by a CHECKPOINT -- which
    fires whenever the last connection closes on a non-empty WAL, i.e. routinely, several times an hour
    with the dashboard and the autocull daemon both polling -- and its mtime moves without one
    pile-relevant value changing. MEASURED 2026-09-03 on a copy of the live bag: a write that changed
    ZERO values moved mtime 1788410388.116460 -> 1788410390.192748 with the size byte-identical, so a
    mtime/size consumer calls a perfectly current pile STALE. Size fails the other way too -- an
    in-place UPDATE leaves it identical, so it cannot see a real change (same run: one cp value +1 left
    the size at 19402752). Neither is a statement about the ROWS. This is: in that same run the digest
    held across the no-op write and moved only for the single real value.

    ALGORITHM -- canonical; any independent implementation must reproduce it EXACTLY:
      rows    : every row of `SELECT * FROM pokemon WHERE in_bag=1` -- precisely the set this engine
                judges, so the hash covers the pile's real dependency and nothing else
      order   : rows ascending by uid_hex
      columns : every ENGINE-INPUT column, sorted by NAME -- never SELECT *'s positional order, which
                a harmless schema migration reshuffles without changing one value. Pipeline OUTPUT
                columns are excluded (see _OUTPUT_COLS below): they are written downstream of the
                stamp and are not inputs to any keep decision
      value   : repr(v) of the raw sqlite value (None / int / float / str / bytes). repr escapes every
                control character, so the separator below can never occur INSIDE a rendered value
      join    : all values of all rows, flattened, joined by chr(0x1f), the ASCII UNIT SEPARATOR
      digest  : sha256 of that string, encoded utf-8
    Deliberately NOT included: file mtime, file size, row count, and any column-name header -- content
    only, so the digest is identical across processes, machines and WAL checkpoints for identical rows.

    `src` is either an open sqlite3.Connection (the SELECT is run on it) or an already-fetched list of
    sqlite3.Row / dict. keep_policy passes its OWN `rows` -- the literal snapshot that produced the
    pile -- so the stamp can never describe a different read than the one the engine actually judged.
    """
    import hashlib
    if hasattr(src, 'execute'):                      # a live connection: read the same set the engine reads
        _cur = src.execute("SELECT * FROM pokemon WHERE in_bag=1")
        _cols = [d[0] for d in _cur.description]
        recs = [dict(zip(_cols, tuple(t))) for t in _cur.fetchall()]
    else:
        recs = [keep_config.row_dict(r) for r in src]
    # EXCLUDE PIPELINE OUTPUT COLUMNS. The hash must cover the engine's INPUTS -- the bag facts the
    # keep decision is derived from -- and nothing the pipeline itself writes downstream of the
    # stamp. auth_tag_names is the tag MIRROR: set_db_tags_from_files writes it during SYNC, which
    # runs AFTER keep_policy stamps provenance, so including it made every SUCCESSFUL sync
    # invalidate the stamp it had just passed. MEASURED 2026-09-06 against the pre-sync snapshot:
    # the daemon's 23:50 cull synced, and the very next audit BLOCKed with a content mismatch whose
    # ENTIRE cause was auth_tag_names on 4,614 rows -- same 5,747 mons, 0 added, 0 removed, not one
    # bag fact changed. keep_policy reads this column ZERO times, so it cannot alter a decision.
    # This is the WAL/mtime lesson one level in: a gate that fires on the pipeline's own legitimate
    # write is noise, and a noisy gate on an IRREVERSIBLE output is worse than no gate, because it
    # trains everyone to wave it through. Add a column here ONLY if the engine never reads it AND
    # the sanctioned pipeline writes it after the stamp; anything else belongs in the digest.
    # NOTE: changing this set changes the digest -- re-run keep_policy to re-stamp, or the stored
    # stamp (computed under the old set) mismatches and reads as staleness.
    _OUTPUT_COLS = {'auth_tag_names'}
    cols = sorted(k for k in recs[0].keys() if k not in _OUTPUT_COLS) if recs else []
    parts = []
    for rec in sorted(recs, key=lambda d: d['uid_hex']):
        for k in cols:
            parts.append(repr(rec[k]))
    return hashlib.sha256(_DBHASH_SEP.join(parts).encode('utf-8')).hexdigest()


# EVOLUTIONS THAT NEED AN ITEM OR A SPECIAL CONDITION IN GO (Sinnoh/Unova Stone, King's Rock, Metal Coat, Sun Stone,
# lures, hearts, walking, ...): not a candy evolve. ONE list, shared with refresh_evolve_shiny (which skips them
# outright). The plain comb-up promises such a target ONLY when the source has no candy target at all -- 2026-09-13:
# two Poliwhirls were promised Politoed slots under "Evolve Next", the user evolved them by candy into Poliwrath,
# both fodder. Scyther -> Scizor (no candy alternative) is still promised: the evolve button itself names the item.
ITEM_GATED_TARGETS = {'espeon','umbreon',   # buddy walk + day/night + task (game master), not a candy tap
'weavile','overqwil','kingambit','pangoro','lickilicky','kingdra',
'pawmot','sneasler','honchkrow','magnezone','mamoswine','togekiss','gliscor',
'electivire','magmortar','roserade','rhyperior','tangrowth','yanmega','ambipom','gallade',
'froslass','dusknoir','porygon_z','porygon2','probopass','politoed','slowking','steelix',
'scizor','milotic','huntail','gorebyss',    # Clamperl is a RANDOM tap -- the label cannot name the branch
'bellossom','sunflora','whimsicott','lilligant',
'eelektross','chandelure','annihilape','kleavor','ursaluna','wyrdeer','basculegion',
'leafeon','glaceon','sylveon','runerigus','cursola','mr_rime','florges','alcremie'}
# REMOVED 2026-09-17 ("Fix everything"), each checked against the game master's own branch: floette (Flabebe -> Floette
# is 25 candy, no item, colour preserved -- Florges above it IS quest-gated and stays), accelgor and escavalier
# (200 candy; `noCandyCostViaTrade` is a DISCOUNT when traded, not a trade requirement). Gating them suppressed 16
# real shiny upgrades for no reason the game enforces.
# ... UNION the game master's own answer (user 2026-09-17 "Fix everything"): the hand list above held 57 names while
# the game gates 135, and every miss is a wrong instruction -- a costume Minccino was told nothing about the Unova
# Stone it needs because 'cinccino' was absent. The hand list stays as a floor: a name the game master expresses
# some other way (Eevee's buddy branches) must never silently stop being gated.
ITEM_GATED_TARGETS |= evolvable_forms.gated_targets()


def released_pids():
    """Every species seen in any account's dex or bag (released_pids.json at the project root); empty when absent."""
    try:
        return set(json.load(open(os.path.join(ROOT, 'released_pids.json'))))
    except (OSError, ValueError):
        return set()


def build_evo_graph(gm, seen_pids, with_all=False):
    """FORM-AWARE evolution graph keyed by speciesId so REGIONAL families resolve their OWN
    evolutions (Galarian Zigzagoon->Linoone->Obstagoon; Hisuian Sneasel->Sneasler, NOT Weavile).
    The old dex-keyed version picked one base speciesId per dex, so every regional pre-evo routed
    through the base form's family (wrong/empty terminal). A 'family' evolution counts ONLY if:
      (1) the TARGET is in the live dex (seen_pids) -- pvpoke lists evolutions PoGo hasn't enabled
          (Duraludon->Archaludon; user 2026-06-02 'Duraludon doesnt evolve'), AND
      (2) the target's baseStats-sum is NOT strictly LOWER than the source's -- drops the
          gamemaster's REVERSED edge (Sinistcha BST590 -> its baby Poltchageist BST350; study
          2026-06-03), AND the target speciesId actually exists (drops the 'lycranroc_dusk' typo).
    Returns speciesId-keyed {sid: can-evolve?} + {sid: reachable terminal DEX/pids} + {sid: steps-
    remaining} + sp_to_dex. reach() resolves a specimen's speciesId via pvid(name, form)."""
    by_sp = {p['speciesId']: p for p in gm['pokemon']}
    sp_to_dex = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
    # RELEASED = seen in ANY account's dex or bag (2026-09-26): a second account's young dex (799) lacked Stoutland,
    # Dusknoir, Pawmot, Obstagoon, so Herdier / Dusclops / Pawmo / Linoone read as the END of their lines -- no Stop
    # tag, and 'Evolve Next' rode along onto a stage that evolves again (the Tympole trap). released_pids.json is the
    # union, grown by every dex walk (pogo_pipeline.step_read_dex). Never shrinks a gate: only adds species.
    seen_pids = set(seen_pids) | released_pids()

    def _bst(sid):
        b = (by_sp.get(sid, {}) or {}).get('baseStats', {}) or {}
        return b.get('atk', 0) + b.get('def', 0) + b.get('hp', 0)

    EVO_FIX = {'poltchageist': ['sinistcha'],          # gamemaster has this REVERSED (only sinistcha->poltchageist)
               'doublade': ['aegislash_shield']}       # Aegislash Shield BST 524 < Doublade 547 -> the BST gate wrongly
    #                                                     drops it; curated EVO_FIX edges bypass that gate (below). 2026-06-04

    # PvPoke edges that do NOT exist in Pokemon GO (main-series regional evolutions). GO's Cubone evolves into
    # Kanto Marowak only; Alolan Marowak comes from raids/eggs. Measured 2026-09-13: this is the only edge in the
    # whole game master from a non-regional source into a regional target. Without it a plain or shiny Cubone
    # could be promised an Alolan Marowak slot it can never fill.
    EVO_DROP = {'cubone': {'marowak_alolan'}}
    def direct(sid):
        fixed = EVO_FIX.get(sid, [])
        evos = (((by_sp.get(sid, {}).get('family', {})) or {}).get('evolutions', []) or []) + fixed
        return [e for e in evos
                if sp_to_dex.get(e) in seen_pids               # PoGo-availability gate: target encountered
                and e not in EVO_DROP.get(sid, ())             # GO-impossible edge (see EVO_DROP)
                and e in by_sp and (e in fixed or _bst(e) >= _bst(sid))]   # curated EVO_FIX edges bypass the BST-monotonic gate

    def terminals(sid, seen=None):
        if seen is None: seen = set()
        evos = direct(sid)
        if not evos:
            d = sp_to_dex.get(sid)
            return {d} if d else set()
        out = set()
        for e in evos:
            if e in seen: continue
            seen.add(e)
            out |= terminals(e, seen)
        return out

    def distance(sid, depth=0):          # evolutions REMAINING from sid to its terminal (PoGo max 2)
        if depth > 6:
            return 0
        evos = direct(sid)
        return 1 + max((distance(e, depth + 1) for e in evos), default=-1) if evos else 0

    def all_stages(sid, seen=None):
        """EVERY later stage as a speciesId (middle AND final), not just terminals -- so the comb-up can
        also fill/upgrade middle evolutions (user 2026-07-26 'comb up to top 2 middle stage evos').
        speciesId, NOT dex: 'rapidash' and 'rapidash_galarian' share dex 78, so a dex-keyed comb-up
        judged a Galarian Ponyta against the user's KANTONIAN Rapidash and wrongly released it."""
        if seen is None:
            seen = set()
        out = set()
        for e in direct(sid):
            out.add(e)
            if e not in seen:
                seen.add(e)
                out |= all_stages(e, seen)
        return out

    is_pre, term, dist = {}, {}, {}
    for sid in by_sp:
        is_pre[sid] = bool(direct(sid))
        term[sid] = terminals(sid)
        dist[sid] = distance(sid)
    if with_all:
        # opt-in 5th value so the existing 4-tuple callers (refresh_evolve_shiny, deep_audit) keep working
        return is_pre, term, dist, sp_to_dex, {sid: all_stages(sid) for sid in by_sp}
    return is_pre, term, dist, sp_to_dex


# ---- WHICH LATER STAGES CAN THIS SPECIMEN BECOME? -- module level, ONE answer (2026-09-23) ------------------------
# main()'s reach / _can_evo / _gender_split_targets delegate here, and so does the PvP usability rule (15d, shadow
# rule 2, the own-stage evolve block): refresh_evolve_shiny and sync_evolve_size import pvp_later_stages() rather
# than re-deriving it. `graph` is build_evo_graph(gm, seen, with_all=True)'s 5-tuple. FORM, COSTUME and GENDER lock;
# item / candy cost never does (a stage he cannot afford today is still a stage the specimen can become).
def evo_reach(r, graph):
    """Reachable terminal DEX ids (FORM + gender aware); empty = can't evolve. A gender-locked species with an
    UNKNOWN gender is NOT evolvable -- don't guess (a NULL-gender male Combee must NEVER be tagged evolve)."""
    is_pre_sp, term_sp = graph[0], graph[1]
    gt = evolvable_forms.GENDER_TERMINALS.get(r['pokemon_id'])
    if gt is not None:
        return gt.get(r['gender'], set())
    sid = pvid(r['species_name'], r['form'] or 0)          # THIS form's speciesId -> its OWN regional family terminals
    return term_sp.get(sid, set()) if is_pre_sp.get(sid) else set()


def evo_can(r, graph):
    """The FORM decides too (2026-09-16): the real game master has no evolution branch for e.g. PSYDUCK_SWIM_2025 while
    8 of 97 costume forms do evolve -- evolvable_forms reads that distinction; None = no entry -> graph only."""
    return bool(evo_reach(r, graph)) and evolvable_forms.row_can_evolve(r) is not False


def evo_gender_split(r, targets, graph):
    """Split a later-stage target set into (reachable-by-THIS-specimen, blocked-by-gender) -- see main()'s
    _gender_split_targets for the history. Only targets PROVABLY on the other gender's branch are blocked."""
    term_sp, sp_to_dex = graph[1], graph[3]
    gt = evolvable_forms.GENDER_TERMINALS.get(r['pokemon_id'])
    if gt is None:
        return set(targets), set()
    legal = gt.get(r['gender'], set())                  # terminal DEX ids reachable for this gender
    other = set().union(*gt.values()) if gt else set()  # terminal DEX ids of ANY gender
    blocked = set()
    for t in targets:
        d = sp_to_dex.get(t)
        if d in legal or (term_sp.get(t, set()) & legal):
            continue                                    # legal terminal, or a middle stage leading to one
        if d in other or (term_sp.get(t, set()) & other):
            blocked.add(t)                              # provably the OTHER gender's branch
    return set(targets) - blocked, blocked


def pvp_later_stages(r, graph):
    """Every LATER stage (speciesId) THIS specimen can actually become: the ONE evolution graph's later stages of its
    own form, minus the other gender's branch, nothing at all when its form / costume / gender cannot evolve; each
    gendered branch also under the form it really lands in (a female Lechonk -> oinkologne_female). Multi-step and
    branching lines come whole from the graph (Eevee, Gloom, Poliwhirl, Kirlia, Wurmple, Slowpoke, Clamperl ...).
    pvp_iv_rule.usable_best() intersects this with the stages rank_cache ranked (its own form/costume/gender gates),
    so a stage counts only when BOTH say the specimen can become it (Duraludon / Girafarig: the ranker's chain lists
    Archaludon / Farigiraf, the game master gives neither species an evolution -- not reachable)."""
    if not evo_can(r, graph):
        return set()
    own = pvid(r['species_name'], r['form'] or 0)
    tg, _blocked = evo_gender_split(r, graph[4].get(own, set()), graph)
    return tg | {evolvable_forms.gendered_target(own, r['gender'], t) for t in tg}


def main():
    # ---- INPUT GATE (2026-09-02) ------------------------------------------------------------------
    # THE PILE IS THE ONE IRREVERSIBLE OUTPUT, so every input that decides it must be PRESENT, not
    # merely defaulted. Each of the four inputs below used to degrade SILENTLY into a plausible-looking
    # but different policy. Measured on the live bag 2026-09-02 by simulating each failure:
    #   * form_enum.json missing  -> costume_forms._MAX_KNOWN_FORM collapses to 0, so the "unknown form
    #     is a costume" guard fires on EVERY non-zero form, the plain pool empties, the plain-line cap
    #     and the whole evolve comb-up stop running: +62 mons INTO the pile, 22 out. Silent.
    #   * keep_config.json missing/corrupt -> the shipped DEFAULTS are a DIFFERENT policy from the live
    #     file (cosmetic 4 vs 3, gigantamax 6 vs 8, shiny 20 vs 10, rarity 12 vs 8, shadow 1 vs 2,
    #     viability_margin 100 vs 0, per_species_caps empty vs three overrides): +3 in, 4 out. Silent.
    #   * pokedex_hundos_live.json missing -> the old `except: _seen_pids = set()` made EVERY evolution
    #     unavailable, so nothing could be comb-up-rescued: +108 INTO the pile. Silent.
    #   * legacy_accurate.json empty -> rule 6 protects nothing; legacy moves cannot be re-rolled
    #     without an Elite TM, so this one is unrecoverable by definition.
    # An input we cannot read is missing data, and missing data means PROTECTED -- here that means
    # producing NO pile at all rather than a confidently wrong one. Cheap to recover from (fix the
    # input, re-run); the failure it replaces is not.
    if not costume_forms_enum_ok():
        raise SystemExit("ABORT keep_policy: form_enum.json did not load (%s). Every form would be judged "
                         "an unknown-and-therefore-costume, which empties the plain pool and disables the "
                         "evolve comb-up. Re-dump it with system/scripts/game_read/classify_all_forms.py."
                         % (costume_forms_load_error() or 'unknown reason'))
    # THE GAME-MASTER COSTUME LAYER DEGRADES, IT DOES NOT ABORT (2026-09-30, costume option 5): with the game master unreadable the last
    # cached flags stand in (nothing shrinks); with neither, the name rule alone decides and the forms only the game flags (e.g. Armored
    # Mewtwo, Gimmighoul Coin A1) read plain again. Say so: full_audit echoes every [WARN] line of the recrawl job's log (keep_policy is its
    # recompute step); audit_gamemaster warns too, but an audit's WARN lines stay in its own log on a passing cull.
    if getattr(costume_forms, 'GM_SOURCE', 'game_master') != 'game_master':
        print('[WARN] costume game-master layer is %s: %s' % (costume_forms.GM_SOURCE, getattr(costume_forms, 'GM_NOTE', None)), flush=True)
    _kc_loaded = getattr(keep_config, 'file_loaded', lambda: True)()   # getattr: an older keep_config.py degrades to the pre-guard behaviour
    if not _kc_loaded:
        raise SystemExit("ABORT keep_policy: keep_config.json did not load (%s). The shipped defaults are a "
                         "DIFFERENT policy from your saved caps, so the pile would not be the one your config "
                         "describes. Fix or restore keep_config.json."
                         % getattr(keep_config, 'LOAD_ERROR', 'unknown reason'))
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
    # Provenance content hash, taken HERE -- on the same connection, from the very row objects this run
    # judges -- not later from a re-read. A second read could land on the other side of a daemon write
    # and stamp a snapshot that never produced this pile, which is the exact lie the stamp exists to
    # prevent. sqlite3.Row objects are immutable snapshots, so this digest describes `rows` for the
    # whole run. See db_content_sha256() above for the canonical algorithm.
    _db_content_sha = db_content_sha256(rows)
    gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
    BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
    legacy = {e['uid_hex'] for e in json.load(open(os.path.join(ROOT, 'legacy_accurate.json'), encoding='utf-8'))}
    if rows and not legacy:
        raise SystemExit("ABORT keep_policy: legacy_accurate.json is EMPTY -- rule 6 (keep legacy-move mons) "
                         "would protect nobody and legacy moves cannot be re-rolled without an Elite TM. "
                         "Re-run the legacy build before culling.")
    # PoGo evolution AVAILABILITY: a gamemaster evolution counts only if its TARGET is in the live
    # dex (encountered in-game) -- the family tree lists evolutions PoGo hasn't enabled
    # (Duraludon->Archaludon, Girafarig->Farigiraf, ...). pokedex_hundos_live.json = the dex walk.
    try:
        _seen_pids = {e['pid'] for e in json.load(open(os.path.join(ROOT, 'pokedex_hundos_live.json')))['entries']}
    except Exception as _de:
        raise SystemExit("ABORT keep_policy: could not read pokedex_hundos_live.json (%s). With no live dex "
                         "EVERY evolution is treated as unavailable, so no pre-evo can be comb-up-rescued and "
                         "108 extra mons land in the irreversible pile. Re-run the dex walk "
                         "(read_pokedex_hundos.py) before culling." % _de)
    if not _seen_pids:
        raise SystemExit("ABORT keep_policy: pokedex_hundos_live.json has NO entries -- same effect as a "
                         "missing dex (every evolution unavailable, no comb-up rescue). Re-run the dex walk.")
    is_pre_sp, term_sp, dist_sp, sp_to_dex, allreach_sp = build_evo_graph(gm, _seen_pids, with_all=True)   # speciesId-keyed (FORM-AWARE)
    _EVO_GRAPH = (is_pre_sp, term_sp, dist_sp, sp_to_dex, allreach_sp)   # for the module-level reach gates (2026-09-23)
    def _sid(r):                          # the specimen's OWN gamemaster speciesId (regional-aware, via FORM_OVERRIDES)
        return pvid(r['species_name'], r['form'] or 0)

    keep = defaultdict(set)            # uid -> {reasons}
    def mark(uid, why): keep[uid].add(why)

    # ---- 0. DATA-COMPLETENESS GATE (2026-09-02) ---------------------------------------------------
    # STANDING RULE: never cull on incomplete data -- any NULL protection input is PROTECTED.
    # Every axis below reads its column as `col or 0`, which makes a NULL (a row the fresh rescan never
    # reached) indistinguishable from a genuine "not special": the mon is judged PLAIN, ranked at the
    # bottom of every cap, and dropped. That is silent under-protection aimed squarely at the rows we
    # know LEAST about, and it is the same shape as the two bugs that started this review (a garbage
    # column read as truth, and a stale form enum read as "not a costume"). Measured on the live bag
    # 2026-09-02: 26 in-bag rows carry a NULL fresh_natural_art_bg / fresh_loc_card_enum and 8 of them
    # were sitting in the irreversible pile.
    # A row that cannot be judged is KEPT and says so ('data_incomplete'), which is also a hard (non-
    # _SOFT) reason, so such a row can never be dominance-collapsed on attributes it was never scanned
    # for either. Self-limiting: the worse the scan, the more the engine keeps -- it can only shrink
    # the pile. Re-run the fresh rescan to clear the flag.
    _PROT_COLS = ('fresh_shiny', 'fresh_alignment', 'fresh_costume', 'fresh_form', 'fresh_bread_mode',
                  'fresh_natural_art_bg', 'fresh_has_location_card', 'fresh_loc_card_enum',
                  'fresh_is_strong', 'costume_decoration_id', 'iv_total', 'pokemon_size_category',
                  'is_zero', 'is_component')
    _have = set(rows[0].keys()) if rows else set(_PROT_COLS)
    _missing_cols = [k for k in _PROT_COLS if k not in _have]
    if _missing_cols:
        # A protection column vanished from the schema: the engine would read every mon as "not
        # special" on that axis and could not tell. Refuse rather than emit an irreversible pile.
        raise SystemExit("ABORT keep_policy: protection column(s) missing from pokemon.db schema -- "
                         f"{_missing_cols}. Re-run the crawl/migration; refusing to build a Transfer pile.")
    _incomplete_n = 0
    for r in rows:
        if any(r[k] is None for k in _PROT_COLS):
            mark(r['uid_hex'], 'data_incomplete')
            _incomplete_n += 1
    if _incomplete_n:
        print(f"[GUARD] {_incomplete_n}/{len(rows)} in-bag mons have a NULL protection input -> kept as "
              f"'data_incomplete' (never transferred on incomplete data). Re-run the fresh rescan to clear.",
              flush=True)

    # ---- FUSION COMPONENTS HOLD NO LADDER SLOT (user 2026-09-26: "i think 2 are currently fused. So don't count those
    # in the ladder.") --------------------------------------------------------------------------------------------
    # A Reshiram / Zekrom fused into a White / Black Kyurem is HELD inside it: hidden from the bag list and not releasable
    # while fused. It was taking real slots -- Best ML, Variant #1, the legacy top-6 -- that pushed a visible 73% Fusion
    # Flare Reshiram into the pile. Out of EVERY competition below (it is simply not in `rows`) and kept as 'fused'. The
    # flag is PokemonProto.isComponent_, re-read every walk; unfused, it is an ordinary bag mon again next pass. The
    # Kyurem itself (isFusion_) is a visible mon of its own form and competes as usual.
    _fused = [r for r in rows if keep_config.is_fused_component(r)]
    for r in _fused:
        mark(r['uid_hex'], 'fused')
    rows = [r for r in rows if not keep_config.is_fused_component(r)]
    if _fused:
        print(f"[FUSED] {len(_fused)} fusion component(s) kept and out of every ladder: "
              f"{sorted(r['species_name'] for r in _fused)}", flush=True)

    shadows = [r for r in rows if r['fresh_alignment'] == 1]
    shinies = [r for r in rows if r['fresh_shiny']]
    plain = [r for r in rows if r['fresh_alignment'] != 1 and not r['fresh_shiny']]  # variant-floor pool
    _plain_ids = {r['uid_hex'] for r in plain}

    # FORM NORMALIZATION: the proto stores some plain mons with form=0 (unset) and
    # others with the explicit "normal" form id (e.g. Bulbasaur 0 vs 163, Combee 0 vs
    # 1715). Collapse form-0 -> the species' canonical base form so a plain mon is ONE
    # variant, not two (otherwise EVERY (pid,form) cap below is silently doubled). Only
    # maps when the species has EXACTLY ONE base-REGION (kantonian/normal/null) non-zero
    # form, so regional forms (Alolan/Galarian/Hisuian/Paldean) and genuine same-region
    # multi-forms (Lycanroc Midday/Midnight/Dusk, Rotom appliances) are left untouched.
    # Used by EVERY (pid,form) keyed rule via cf(r). (user 2026-06-02: "account for each
    # and every form".)
    from collections import Counter as _Counter
    _REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
    def _is_regional_code(nm, f):                 # a regional form code (e.g. Alolan Raichu) can carry a NULL/blank
        return any(x in pvid(nm, f) for x in _REGSUF)   # form_region and masquerade as base-region -> NEVER let it be the
        #                                                 base form (else Kantonian Raichu collapses onto it). 2026-06-04
    _basecnt = defaultdict(_Counter)
    for r in rows:
        _f = r['form'] or 0
        _reg = (r['form_region'] or '').strip().lower()
        # A COSTUME IS NEVER A BASE FORM -- the exclusion on the next line was APPLIED 2026-09-23 (user: "fix them all"); this block said
        # "NOT-DONE, DELIBERATELY (2026-09-02)" until 2026-09-30, when it was checked against the code and the live bag. Why the exclusion
        # matters: a costume form id that votes makes the vote non-unanimous, so base_form is DROPPED for that species, cf() stops folding
        # form-0 onto the canonical base form, and the species holds TWO plain groups (cf=0 and cf=<Normal>) = DOUBLE the plain cap (on
        # 2026-09-02 a costume was even elected: Bewear 760 -> 3021 BewearWildarea2025). Re-run 2026-09-30 over the live bag: no costume id
        # is left in the vote; without the exclusion 17 species would lose their base_form (the Charmander line, Caterpie, Pikachu, Psyduck,
        # Lapras, Ditto, Mewtwo, Sudowoodo, Umbreon, Slowking, Delibird, Charjabug, Bewear, Falinks, Gimmighoul). Mewtwo and Gimmighoul are
        # there because the game's isCostume flag now makes Armored Mewtwo / Gimmighoul Coin A1 costumes (costume_forms): each GAINS a
        # base_form (135 / 2998) and no form-0 copy exists to fold. audit_cull.py and audit_tags_membership.py carry the same exclusion.
        if _f != 0 and _reg in ('', 'normal', 'kantonian', 'none', 'null') and not _is_regional_code(r['species_name'], _f) \
                and not is_costume_form(_f):          # APPLIED 2026-09-23 (user: "fix them all"): a costume is never a base form
            _basecnt[r['pokemon_id']][_f] += 1
    base_form = {pid: cnt.most_common(1)[0][0] for pid, cnt in _basecnt.items() if len(cnt) == 1}
    def cf(r):
        _f = r['form'] or 0
        return base_form.get(r['pokemon_id'], _f) if _f == 0 else _f

    # EVOLUTION-AWARE LINE CAP helpers. For a handful of families gender decides the terminal (or
    # blocks evolution) -- the gamemaster family graph can't express that, so hardcode them.
    GENDER_TERMINALS = evolvable_forms.GENDER_TERMINALS   # ONE definition, shared with the rank labels (2026-09-17)
    def reach(r):                            # reachable terminal pids (FORM + gender aware); empty = can't evolve
        return evo_reach(r, _EVO_GRAPH)         # module level since 2026-09-23 -- the PvP usability rule asks it too
    def _can_evo(r):
        return evo_can(r, _EVO_GRAPH)           # the FORM decides too (2026-09-16) -- see evo_can
    def _gender_split_targets(r, targets):
        """Split a comb-up target set into (reachable-by-THIS-specimen, blocked-by-gender). 2026-09-02.

        reach()/_evo_ok() are gender-aware (GENDER_TERMINALS); the comb-up target set built from
        allreach_sp is NOT, so a specimen could be held to fill -- and, worse, COMMIT the stage bar of
        -- a stage its gender can never reach. Live bag 2026-09-02: 5 such commits, incl. two female
        Ralts held for GALLADE (male-only), a female Burmy held for MOTHIM and two male Burmy held for
        WORMADAM. Every one of those raised the bar on a stage the mon cannot fill, so the next real
        candidate for that slot was judged against a phantom occupant and could be dropped.

        Only targets PROVABLY on the other gender's branch are blocked: a target whose dex is a
        terminal of some OTHER gender and is neither a legal terminal for this one nor a MIDDLE stage
        that still leads to one (a male Ralts must keep 'kirlia' as a target -- it is on the way to
        both Gallade and Gardevoir). Species with no gender rule are untouched.
        Module level since 2026-09-23 (evo_gender_split) -- the PvP usability rule asks the same question.
        """
        return evo_gender_split(r, targets, _EVO_GRAPH)
    def _cosf_id(r):
        """The form-ENCODED costume id for this row, else 0. ONE definition (2026-09-02).

        The same test was hand-copied at four sites (_truly_plain, _scollect, _domattr, the legacy
        specials guard) -- and "one axis modelled in N places" is the failure class that has cost
        this collection real keepers. It also now falls back to the crawl's `form` when fresh_form
        does not name a costume: fresh_form is a rescan column, and a NULL / never-rescanned one must
        NOT make a form-encoded costume look PLAIN. Missing data is PROTECTED, and a costume judged
        plain is exactly how 7 Pikachu costumes reached the irreversible pile. Zero rows have a NULL
        fresh_form today (measured 2026-09-02), so this is a guard, not a behaviour change.
        """
        for f in (r['fresh_form'], r['form']):
            if is_costume_form(f):
                return f or 0
        return 0
    def _truly_plain(r):                     # no cosmetic/Dynamax axis (shiny/shadow already excluded upstream)
        # fresh_natural_art_bg, NOT natural_art_background: the non-fresh column holds garbage on real rows
        # (7 in-bag mons incl. a shiny Gmax Lapras whose phantom 'bg' bit dominance-collapsed its sibling; audit F1)
    # special_bg_id RETIRED 2026-09-02: PokemonProto has NO background field (proto_layout.json, 96 fields).
    # Every stored value is garbage from a retired offset guess -- 1 on 64 rows, plus 65536/256/119/65,
    # i.e. power-of-two read artifacts, and only 7 of the 76 non-zero rows even hold a location card. It has
    # NO writer anywhere in the tree and 39.8% of the bag has never had it read at all. Reading it invented
    # phantom "background" variants that split cap groups and polluted the dominance identity set -- the same
    # failure class as the natural_art_background bug (audit F1). The REAL cosmetic backgrounds are covered by
    # fresh_natural_art_bg (measured 2026-09-02: zero non-zero rows bag-wide) and the location-card axis.
        return (not (r['fresh_costume'] or 0)
                and not (r['fresh_natural_art_bg'] or 0)
                and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
                and not evolvable_forms.max_axis(r['fresh_bread_mode'])   # every Max mode (evolvable_forms.BREAD_MODES) is a real collectible axis -- own bundle, NOT plain (user 2026-06-04)
                and not _cosf_id(r))   # form-ENCODED costumes (LaprasCostume2020, CaterpieGofest2026 ...) carry fresh_costume=0 but ARE cosmetics -> route to the rule-1a cosmetic cap + Event, NEVER the plain cull (user 2026-06-04)

    # 1. variant floor: top-N per DISTINCT COSMETIC VARIANT (caps from keep_config.json: cosmetic 4, Dynamax 3, Gmax 6).
    # The variant key includes EVERY cosmetic axis -- costume, special/event
    # background, art background, decoration, dynamax-mode -- so a mon that is
    # distinct by ANY of them is its own collectible and keeps its own top-N,
    # never collapsed into a plain-dupe group and culled (user 2026-05-30: "per
    # distinct event/etc" -- don't throw variants away). Location-background mons
    # are already fully kept by the location_card rule (#13). Gmax (bread==2) cap from keep_config.
    # 1a. NON-PLAIN variants (costume / event-bg / art / decoration / Dynamax / Gigantamax) ->
    # per-(species,variant) cap: catch-state collectibles kept on their own axis. Gmax(bread==2)=
    # caps from keep_config.json (cosmetic 4, Dynamax 3, Gmax 6). (Plain is handled by the line cap in 1b.)
    def _vkey(r):
        # fresh_natural_art_bg (F1, see _truly_plain); deco TEXT '0' normalized to 0 like _truly_plain/_domattr
        # (string '0' was truthy here, keying deco-'0' mons as a spuriously distinct variant; audit F24)
        _deco = r['costume_decoration_id'] if (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0') else 0
        return (r['pokemon_id'], cf(r), r['fresh_costume'] or 0, 0,   # slot 4 was special_bg_id (retired -- garbage column)
                r['fresh_natural_art_bg'] or 0, _deco,
                r['fresh_bread_mode'] or 0)   # every Max mode is its own bundle (evolvable_forms.BREAD_MODES)
    # AN UNCONDITIONALLY-KEPT TROPHY NEVER CONSUMES A CAPPED SLOT (2026-07-25). Rule 4 keeps every hundo
    # and rule 8 keeps every nundo regardless, so letting either also occupy a floor slot silently shrank
    # the user's real cap by one (Turtonator: "top 3" plains yielded only 2 ordinary dupes). The exemption
    # already existed for the DISPLACING pools; it was missing from the floor pools themselves.
    # NUNDO is conditional on its switchable keep-all being ON -- with rules.nundo OFF a nundo is not
    # unconditionally kept, so it must compete for a slot like any other plain.
    _nundo_on = keep_config.rule_enabled('nundo')
    def _slot_exempt(r):
        if (r['iv_total'] or 0) == 45:
            return True                                  # hundo -- always kept by rule 4
        return bool(_nundo_on and r['is_zero'] and r['pokemon_id'])   # nundo -- kept by rule 8 when ON
    vg = defaultdict(list)
    for r in plain:
        if _truly_plain(r):
            continue
        if _slot_exempt(r):
            continue
        vg[_vkey(r)].append(r)
    # SHINY DISPLACES THE VARIANT FLOOR (user 2026-06-08; extends the plain-floor shiny rule of #1b to COSMETIC
    # variants): a non-hundo shiny of the SAME variant OCCUPIES a slot by IV, so the plain cap = the plain slots
    # LEFT in the merged top-cap. A plain pushed out loses 'variant_floor' and falls to Transfer IF that was its
    # ONLY keep reason -- a displaced variant with another axis (legacy / origin / location_card / hundo) still
    # stays. Shiny WINS IV ties here (user approved transferring the tied-IV 89% Wailmer over its same-IV shiny).
    # Hundo shinies exempt (kept by rule 4, never consume a slot).
    _shvar = defaultdict(list)
    for _sr in shinies:
        if (_sr['iv_total'] or 0) != 45 and not _truly_plain(_sr):
            _shvar[_vkey(_sr)].append(((_sr['iv_total'] or 0), (_sr['cp'] or 0)))
    def _var_eff_cap(key, cap, pool):
        sh = _shvar.get(key)
        if not sh:
            return cap
        merged = sorted([(iv, cp, 0) for iv, cp in sh]                                # shiny -> tag 0
                        + [((r['iv_total'] or 0), (r['cp'] or 0), 1) for r in pool],  # plain -> tag 1
                        key=lambda x: (-x[0], -x[1], x[2]))[:cap]                     # tie -> shiny(0) first
        return sum(1 for x in merged if x[2] == 1)                                    # plain slots remaining
    _env_cc_raw = os.environ.get('COSMETIC_CAP')
    _env_cc = None
    if _env_cc_raw is not None and str(_env_cc_raw).strip() != '':
        try:
            _env_cc = int(str(_env_cc_raw).strip())        # a junk COSMETIC_CAP used to ValueError mid-run
        except ValueError:                                 # (after the input gate, before any output) --
            _env_cc = None                                 # ignore it and keep the config's cap instead.
            print(f"[WARN] COSMETIC_CAP={_env_cc_raw!r} is not an integer -- IGNORED, using keep_config cosmetic cap {keep_config.cap('cosmetic')}", flush=True)
        else:
            if _env_cc < 0:
                print(f"[WARN] COSMETIC_CAP={_env_cc} is negative -- IGNORED, using keep_config cosmetic cap {keep_config.cap('cosmetic')}", flush=True)
                _env_cc = None
    if _env_cc is not None and _env_cc != keep_config.cap('cosmetic'):
        print(f"[WARN] COSMETIC_CAP={_env_cc} env override ACTIVE -- engine cosmetic cap differs from keep_config.json ({keep_config.cap('cosmetic')}); dashboard display will NOT match the cull (audit F15)", flush=True)
    for key, lst in vg.items():
        _ax = evolvable_forms.max_axis(key[-1])
        if _ax == 'dynamax':       _vc, _vcat = keep_config.cap('dynamax'), 'dynamax'
        elif _ax == 'gigantamax':  _vc, _vcat = keep_config.cap('gigantamax'), 'gigantamax'
        else:               _vc, _vcat = (_env_cc if _env_cc is not None else keep_config.cap('cosmetic')), 'cosmetic'
        if _vcat == 'cosmetic':
            _vc = evolvable_forms.costume_cap(key[0], key[2], _vc)   # middle-stage costumes keep 1 (2026-09-25)
        cap = keep_config.species_cap(_vcat, key[0], _vc)   # per-species override (Curation Studio) else global cap (Dynamax/Gmax/cosmetic; COSMETIC_CAP env still overrides the global)
        cap = _var_eff_cap(key, cap, lst)   # shiny variants occupy slots by IV, displacing same-variant plains (user 2026-06-08)
        for r in topn(lst, cap, bg_first=True):   # backgrounds first (user 2026-09-24)
            mark(r['uid_hex'], 'variant_floor')

    # 1b. PLAIN PER-(STAGE,FORM) CAP -- the heart of the collection. The cap is applied to EACH distinct
    # (species, form), NOT pooled across the evolutionary line (user 2026-06-03: "the cap is for each
    # stage/form"). A 3-stage line keeps the top-3 of its base, its middle, AND its final INDEPENDENTLY
    # -- all 3 of your Arboliva stay even when you also hold hundo Smoliv. Each collectible form (Unown
    # letter, Spinda pattern, Lycanroc cloak, regional form) is naturally its own (pid,cf) cap, so the old
    # FORM_COLLECTIBLE / line-pool machinery (and its branched double-pooling) is gone. Gender splits the
    # cap ONLY for the gender-evolvers so a rare female Combee keeps her own top-3, never crowded by males.
    # ONE EXCEPTION -- PATTERN-POOLED LINES (user 2026-09-08 "Fix Scatterbug so there's the top 3 of each
    # region type only for its whole evo line"): for keep_config.pattern_line_pools (Scatterbug/Spewpa/Vivillon)
    # the pattern SURVIVES evolution and IS the collectible, so all three stages of one pattern share ONE
    # LINE_CAP pool (Jungle Scatterbugs + Jungle Spewpa + Jungle Vivillon = 3 slots). See pattern_pools.py.
    LINE_CAP = keep_config.cap('plain_line')                 # FINAL stages
    PREEVO_CAP = keep_config.cap('plain_line_preevo')        # stages that can still evolve (user 2026-07-26:
    #   "for non final stages you can keep the cap at 2 instead of 3") -- a pre-evo is a stepping stone, so it
    #   gets a tighter plain floor; the evolve comb-up still rescues any pre-evo that would improve a terminal.
    # Unown special (user 2026-06-06 "just this once -- Unown shinies take up the top-3 slots, unless hundo"):
    # a non-hundo shiny Unown OCCUPIES a top-3 plain slot rather than being kept on top of it, so a letter's
    # plain cap drops by its non-hundo-shiny count (shinies still kept by rule 3; hundos kept by rule 4, exempt).
    _unown_shiny = _Counter((r['pokemon_id'], cf(r)) for r in shinies
                            if r['pokemon_id'] == 201 and (r['iv_total'] or 0) != 45)
    def _line_cap(key):
        return max(0, LINE_CAP - _unown_shiny.get((key[0], key[1]), 0)) if key[0] == 201 else LINE_CAP
    # SHINY DISPLACES THE PLAIN FLOOR (user 2026-06-07; generalizes the Unown carve-out to EVERY species,
    # IV-conditional): a non-hundo shiny whose IV ranks it into the (pid,cf) MERGED top-3 OCCUPIES a plain
    # floor slot instead of sitting on top of it, so the plain cap = the plain slots LEFT in that merged
    # top-3. A plain pushed out loses 'variant_floor'; if that was its ONLY keep reason it falls to Transfer
    # (user: "as long as the variant-floor slot is ONLY tagged for that reason, it can go regardless of
    # protection"). Hundos exempt (kept on their own, never consume a slot). Unown keeps its count-based carve-out.
    # ...AND COSMETIC VARIANTS DISPLACE IT TOO (user 2026-06-08 "any variant any shiny ... can take up a plain
    # pokemon's spot"): the displacing pool is now EVERY non-hundo SPECIAL of (pid,cf) -- shiny OR cosmetic
    # variant (costume / special-bg / art / deco / Dynamax / Gmax) -- each occupying a plain-floor slot by IV.
    # Specials WIN IV ties (consistent with the variant-floor rule). A plain pushed out and not rescued by the
    # evolve comb-up -> Transfer. Hundos exempt (rule 4, no slot). Shadow stays its own axis (NOT a displacer).
    # gender-split for gender-evolvers (audit F7): the displacing specials pool must use the SAME key as
    # _stage_key, else a male shiny eats a female Combee's plain-floor slot (her line is the one that evolves).
    def _gterm(r):
        # GENDER IS A LOOK (2026-09-23): gender-locked evolvers AND the 102 visibly dimorphic species (gender_variants.json,
        # e.g. the dark female Hippowdon) each get a ladder per gender -- evolvable_forms.gender_key is the ONE answer.
        return evolvable_forms.gender_key(r['pokemon_id'], r['gender'])
    # THE stage key. (pid, cf, gender) for every ordinary line; for a PATTERN-POOLED line (pattern_pools /
    # keep_config.pattern_line_pools) it is (('pool', line), pattern, 0) so all stages of one pattern share a
    # pool. _stage_rep, _special_iv_grp and stage_pool ALL go through this one function -- the displacing
    # specials and the plain pool can never be keyed differently (the F7 lesson). pool_key() returns None
    # for an unknown / unnamed form, and that row falls back to the per-(species, form) rule (safe: fewer
    # merges can only keep MORE).
    def _pkey(r):
        return pattern_pools.pool_key(r['pokemon_id'], r['species_name'], r['form'] or 0, r['gender'])
    def _stage_key(r):
        return _pkey(r) or (r['pokemon_id'], cf(r), _gterm(r))   # gender component shared with _special_iv_grp (F7)
    # one representative row per stage key, so the cap can ask "can THIS stage evolve?"
    # PREFER AN EVOLVABLE REP (2026-09-22): a locked costume shares its stage key with the ordinary copies, and
    # first-seen used to win -- a costume-82 Floragato made Floragato read as a FINAL stage (cap 3), so a 91%
    # Sprigatito was promised a slot that audit_promises (middle cap 2) correctly called pointless. Gate failed.
    _stage_rep = {}
    for _r in plain:
        _key = _stage_key(_r)
        _old = _stage_rep.get(_key)
        if _old is None or (not _can_evo(_old) and _can_evo(_r)):
            _stage_rep[_key] = _r
    # MIDDLE STAGES ONLY get the tighter cap (user 2026-09-13: "middle evos can be capped at 2. Only 3 of the
    # first and final evos can remain at 3"). A middle stage = can still evolve AND something evolves into it.
    # Base stages (Bulbasaur) and finals (Venusaur) keep LINE_CAP; a 2-stage line has no middle at all.
    _has_parent_sp = {t for _ts in allreach_sp.values() for t in _ts}     # every sid some other sid evolves into
    def _is_middle_sid(sid):
        return bool(is_pre_sp.get(sid)) and sid in _has_parent_sp
    def _stage_cap(key):
        """PREEVO_CAP only for a MIDDLE stage (2026-09-13), else LINE_CAP. A PATTERN POOL spans the whole line,
        so it is always LINE_CAP -- the line's slots, not a stepping-stone's (user 2026-09-08)."""
        if pattern_pools.is_pool_key(key):
            return LINE_CAP
        _g = key[2] if len(key) > 2 else 0               # per-gender ladders of dimorphic species cap lower (2026-09-25)
        if key[0] == 'sid':                              # virtual key: a stage with no row of that kind in the bag
            return evolvable_forms.ladder_cap(PREEVO_CAP if _is_middle_sid(key[1]) else LINE_CAP, sp_to_dex.get(key[1]), _g)
        _rep = _stage_rep.get((key[0], key[1], _g))
        return evolvable_forms.ladder_cap(PREEVO_CAP if (_rep is not None and _can_evo(_rep) and _is_middle_sid(_sid(_rep)))
                                          else LINE_CAP, key[0], _g)
    _special_iv_grp = defaultdict(list)
    for _sr in shinies:                                  # non-hundo shinies
        if (_sr['iv_total'] or 0) != 45:
            _special_iv_grp[_stage_key(_sr)].append(((_sr['iv_total'] or 0), (_sr['cp'] or 0)))
    for _vr in plain:                                    # non-hundo COSMETIC variants (plain pool already excludes shiny+shadow)
        if not _truly_plain(_vr) and (_vr['iv_total'] or 0) != 45:
            _special_iv_grp[_stage_key(_vr)].append(((_vr['iv_total'] or 0), (_vr['cp'] or 0)))
    def _eff_cap(key, pool):
        if key[0] == 201:
            return _line_cap(key)                        # Unown: existing count-based carve-out
        _cap = _stage_cap(key)                           # 3 for finals, 2 for still-evolvable stages
        sp = _special_iv_grp.get((key[0], key[1], key[2] if len(key) > 2 else 0))
        if not sp:
            return _cap
        merged = sorted([(iv, cp, 0) for iv, cp in sp]                                    # special -> tag 0
                        + [((r['iv_total'] or 0), (r['cp'] or 0), 1) for r in pool],      # plain   -> tag 1
                        key=lambda x: (-x[0], -x[1], x[2]))[:_cap]                         # tie -> special(0) wins
        return sum(1 for x in merged if x[2] == 1)       # plain slots remaining in the merged top-cap
    stage_pool = defaultdict(list)
    for r in plain:
        if _truly_plain(r) and not _slot_exempt(r):
            stage_pool[_stage_key(r)].append(r)   # hundo/nundo EXEMPT: unconditionally kept, so they
            #                                       never eat a plain slot (see _slot_exempt above)
    # EVOLVE is a SEPARATE advisory label on the kept SURPLUS pre-evos -- it never changes KEEP/TRANSFER
    # (a mon tagged Evolve is already kept; nothing it would replace gets transferred -- user, 2026-06-03).
    # Interpretation A + redundancy rule: the #1 (highest-IV) of each stage stays AT-stage; only a surplus
    # (2nd+) copy is promoted, and only if evolving it FILLS an empty final or BEATS your best final (once a
    # promotion is committed the bar rises, so no redundant 2nd final). NEVER promote a hundo(45)/nundo(0)
    # trophy, a RARE_PID legendary/mythical, or a regional form (form-aware evo graph is Pass 2 -- don't
    # emit a wrong regional terminal e.g. Hisuian Sneasel->Weavile). Split by evolutions-remaining: 1 / 2.
    def _evo_ok(r):
        iv = r['iv_total'] or 0          # reach() is now FORM-AWARE -> regional pre-evos resolve their OWN
        if _pkey(r):
            return False                 # PATTERN-POOLED line: its pool already spans every stage, so evolving
            #                              never changes its rank -- no comb-up in, no comb-up out (2026-09-08)
        if r['pokemon_id'] in keep_config.protected_pids():
            return False                 # PROTECTED = keep EVERY copy as it is; never advise evolving one (2026-09-16:
            #                              two protected Pichus were told to evolve and both Pikachus were culled)
        return _can_evo(r) and iv not in (0, 45) and r['pokemon_id'] not in RARE_PIDS   # terminal; no regional gate needed
    evo_cands = []   # stage top-3 surplus -> evolve, OR fall back to at-stage stock if redundant
    _pinned = set()   # uid: a middle stage's resident, pinned when a sibling moves up -- never promoted this pass (2026-09-13)
    evo_extra = []   # BEYOND the stage cap -> comb-up candidates: KEPT only if evolving FILLS/BEATS a terminal,
    #                  else Transfer (user 2026-06-08 "are all the transferred considered for upgrading the evo
    #                  line?" -- now YES: every evolvable transfer candidate is comb-up-checked, not just stage top-3).
    for _key, lst in stage_pool.items():
        _pool = [r for r in lst if (r['iv_total'] or 0) != 45] if _key[0] == 201 else lst  # Unown: hundos exempt (rule 4 keeps them, no slot)
        _ranked = topn(_pool, _eff_cap(_key, _pool))             # top-3 of THIS stage/form (minus shiny-occupied slots)
        _ranked_uids = {r['uid_hex'] for r in _ranked}
        for i, r in enumerate(_ranked):
            if i >= 1 and _evo_ok(r):
                evo_cands.append(r)                             # surplus copy -> maybe evolve (decided below)
            elif i == 0 and _evo_ok(r) and _is_middle_sid(_sid(r)) and len(_pool) >= 2:
                evo_cands.append(r)                             # a MIDDLE stage's best competes in IV order too; the
                #                                                 first promotion out of the stage pins a resident
            else:
                mark(r['uid_hex'], 'variant_floor')             # #1-of-stage / hundo / nundo / rare -> at-stage
        for r in _pool:                                          # everything BEYOND the stage cap
            if r['uid_hex'] not in _ranked_uids and _evo_ok(r):
                evo_extra.append(r)                             # comb-up-only: kept iff it improves a terminal, else Transfer
    _stock_uids = {x['uid_hex'] for x in evo_cands}   # within the stage cap: kept anyway as stock -> never a RESCUE (H08)
    # CANDY (user 2026-09-17: "read candy always so you can get better recommending stuff and improving my collection").
    # Every Evolve label is a promise the user can act on NOW. Candy is spent best-first: Evolve Shiny targets first,
    # then the pooled-line advisory below, then the comb-up in IV order. A copy is held beyond its stage cap only for an
    # evolution its family can afford; a stock copy inside the cap keeps its floor slot either way. A split line or an
    # Evolve Twice costs its most expensive path. candy.json older than 2 h (walk failed) -> candy is ignored entirely.
    # THE WALK BEING JUDGED decides freshness, not the wall clock (2026-09-29, research A13-2).
    _walk = max((str(r['last_scanned']) for r in rows if r['last_scanned']), default=None)
    _candy_left = evolvable_forms.candy_now(walk=_walk)
    _items_left = evolvable_forms.items_now(walk=_walk)   # evolution stones etc., from the same walk (2026-09-17)
    _item_short = {}                                  # uid -> the ITEM_* it waits on, for the report
    _candy_short = []
    _earned_unpaid = set()      # earned a slot at a later stage but cannot pay the candy/item today -> HOLD, never release
    _unpaid_committed = set()   # ...and that hold COMMITS its slot once (2026-09-29, research A01-1): the next copy must beat it
    _collapsing = set()         # uids the dominance collapse is about to RELEASE: for them 'evolve into an open slot' is the
    #                             rescue, whatever keep reason they still carry at that moment (2026-09-23, Minccino 87%)
    _promises = {}                                                 # uid -> promised stage(s), for audit_promises (2026-09-17)
    def _cost(r, ts):
        cs = [evolvable_forms.path_cost(_sid(r), t, allreach_sp) for t in ts]
        return None if (not cs or any(c is None for c in cs)) else max(cs)
    def _need_items(r, ts):
        """{ITEM_*: how many} the promise costs -- the most demanding branch, as _cost takes the dearest path."""
        need = {}
        for t in ts:
            for k, v in evolvable_forms.path_items(_sid(r), t, allreach_sp).items():
                need[k] = max(need.get(k, 0), v)
        return need
    def _afford(r, ts):
        # THE STONE COUNTS TOO (user 2026-09-17: "it can evolve, i just dont have the stone to do it"). An evolution
        # the bag cannot pay for today is not advice, it is a chore he cannot do -- hold it like a candy-short one and
        # name the item in the report. Items unread (stale walk) -> _items_left is None -> candy alone decides.
        # UNKNOWN IS NOT AFFORDABLE (2026-09-29, research A13-2): an unread count HOLDS the copy (kept, no Evolve label,
        # its slot committed) instead of promising what the bag may not have -- unknown data is never a chore or fodder.
        if _items_left is None and _need_items(r, ts):
            return False
        if _items_left is not None:
            for k, n in _need_items(r, ts).items():
                if _items_left.get(evolvable_forms._item_key(k), 0) < n:
                    return False
        if _candy_left is None:
            return False
        c, f = _cost(r, ts), evolvable_forms.family(_sid(r))
        return c is None or f is None or _candy_left.get(f, 0) >= c
    def _spend(r, ts):
        c, f = _cost(r, ts), evolvable_forms.family(_sid(r))
        if _candy_left is not None and c is not None and f is not None:
            _candy_left[f] = _candy_left.get(f, 0) - c
        if _items_left is not None:                       # one stone, one promise
            for k, n in _need_items(r, ts).items():
                _k = evolvable_forms._item_key(k)
                _items_left[_k] = _items_left.get(_k, 0) - n
    def _short(r, ts):
        """Remember WHY a promise was withheld: a missing stone reads very differently from missing candy."""
        for k, n in _need_items(r, ts).items():
            if _items_left is not None and _items_left.get(evolvable_forms._item_key(k), 0) < n:
                _item_short[r['uid_hex']] = k
                return
        _candy_short.append(r)
    # POOLED-LINE EVOLVE ADVISORY (2026-09-08). A pattern pool spans every stage, so the comb-up below never
    # sees it. The Evolve label still has a job: when a pattern has NO final-stage copy in the bag at all
    # (no Jungle Vivillon), the best kept pre-evo of that pattern is the route to one. LABEL ONLY -- the mon
    # is already kept and nothing else moves. Never the LAST copy of its own (species, form) (evolving it
    # would empty that form -- the dex_only intent) and never a trophy (exempt from the pool anyway).
    _pool_rows = defaultdict(list)
    for r in rows:
        _pk = _pkey(r)
        if _pk:
            _pool_rows[_pk].append(r)
    _form_cnt = _Counter((r['pokemon_id'], r['form'] or 0) for r in rows)
    for _pk, _members in _pool_rows.items():
        if keep_config.line_pool_all() and _pk[0] != ('pool', pattern_pools.roster().get(_members[0]['pokemon_id'])):
            continue   # EVERY-LINE pools (2026-09-26): evolving never wins a slot in a pool that spans the line --
            #            no ladder evolve advice at all (PvP / shiny / size labels are separate and stay)
        if any(not is_pre_sp.get(_sid(m)) for m in _members):
            continue                                              # the pattern already has a final -> nothing to advise
        _cands_p = [m for m in _members if 'variant_floor' in keep.get(m['uid_hex'], ())
                    and _form_cnt[(m['pokemon_id'], m['form'] or 0)] >= 2
                    and _can_evo(m) and (m['iv_total'] or 0) not in (0, 45)]
        if not _cands_p:
            continue
        _best = min(_cands_p, key=lambda m: (-(m['iv_total'] or 0), -(m['cp'] or 0), m['uid_hex']))   # same order as topn
        _fins_p = sorted(t for t in allreach_sp.get(_sid(_best), ()) if not is_pre_sp.get(t))
        if not _afford(_best, _fins_p):
            _candy_short.append(_best)
            continue                                              # not affordable now: it keeps its floor slot, no label
        _spend(_best, _fins_p)
        _promises[_best['uid_hex']] = list(_fins_p)
        keep[_best['uid_hex']].discard('variant_floor')
        mark(_best['uid_hex'], f"evolve_{dist_sp.get(_sid(_best), 1) or 1}")   # same literal shape as the comb-up's mark (audit I1 reads 'evolve_<n>')
    # identity-aware like _scollect (audit F6): same concrete costume/background ids required for dominance.
    # Lives ABOVE the comb-up bar because the bar must know the dominators (2026-09-13, below).
    def _domattr(r):
        s = set()
        if r['fresh_shiny']: s.add(('shiny', 1))
        # ('sbg', ...) REMOVED -- special_bg_id is a garbage column (see _truly_plain note)
        if (r['fresh_natural_art_bg'] or 0): s.add(('abg', r['fresh_natural_art_bg']))           # fresh_ col -- F1
        if r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0): s.add(('loc', r['fresh_loc_card_enum']))
        if (r['fresh_costume'] or 0): s.add(('cos', r['fresh_costume']))
        elif _cosf_id(r): s.add(('cosf', _cosf_id(r)))
        _ax = evolvable_forms.max_axis(r['fresh_bread_mode'])
        if _ax: s.add(('gmax' if _ax == 'gigantamax' else 'dmax', 1))
        if r['fresh_alignment'] == 1: s.add(('shadow', 1))
        return frozenset(s)

    # ONE MODEL FOR "WOULD THIS COPY BE KEPT AT THAT STAGE?" (2026-09-13). Five times today an Evolve label promised
    # a slot the cull then refused, each time because the label used a hand-written bar (plain IVs only; then
    # specials; then dominators; then card commits ...) that drifted from the real rule. Now the label SIMULATES:
    # a virtual copy of the candidate is dropped into the target stage's real pool (plus the copies already
    # promised to it) and judged by the very same rule-1b ranking (_eff_cap + topn) and the very same dominance
    # test the cull applies to real rows. The user's words: "a sure fire way to organize this". Comb-up runs just
    # before the dominance pass, so every keep axis is already marked when kept dominators are looked up.
    _all_by_key = defaultdict(list)                       # (pid, cf, gterm) -> EVERY row of that stage in the bag
    for _r in rows:
        if not _pkey(_r):
            _all_by_key[(_r['pokemon_id'], cf(_r), _gterm(_r))].append(_r)
    _key_of_sid = {}                                      # speciesId -> {gterm: stage key of the PLAIN form}
    # A speciesId spans many stage keys when the species has form-encoded costumes (Pikachu: 46 forms, one plain
    # pool at form 598). The evolved copy lands in the PLAIN form, so the key must be the non-costume one with the
    # real plain pool -- "last key wins" judged two Pichus against a costume-form key with no dominators and both
    # evolved Pikachus were collapsed on arrival (2026-09-16).
    def _key_rank(k):
        return (0 if is_costume_form(k[1]) else 1, len(stage_pool.get(k, ())), len(_all_by_key.get(k, ())))
    _name_of_sid = {}                                     # speciesId -> a bag species_name (the oracle's probe row)
    for _k, _lst in _all_by_key.items():
        _name_of_sid.setdefault(_sid(_lst[0]), _lst[0]['species_name'])
        _d = _key_of_sid.setdefault(_sid(_lst[0]), {})
        if _d.get(_k[2]) is None or _key_rank(_k) > _key_rank(_d[_k[2]]):
            _d[_k[2]] = _k
    # ONE speciesId CAN COVER TWO PLAIN FORMS, AND THE EVOLVED COPY KEEPS ITS OWN (2026-09-20).
    # _key_of_sid holds a single key per (speciesId, gender terminal), so Shellos/Gastrodon -- West and East, both
    # plain, both 'gastrodon' to pvpoke -- collapsed to whichever form had the bigger pool. A WEST Shellos was then
    # measured against the EAST Gastrodon pool and "earned" a slot by displacing an East copy it can never become,
    # while the West pool it really joins already held a hundo. audit_promises caught the resulting advice as
    # pointless and blocked the sync. The game names the exact target form (SHELLOS_WEST_SEA -> GASTRODON_WEST_SEA),
    # so ask it -- but only where the collapse is actually ambiguous, so every single-form species is untouched.
    _keys_of_sid = defaultdict(lambda: defaultdict(list))  # speciesId -> gterm -> [every stage key seen]
    _key_of_formname = {}                                 # (norm form name, gterm) -> stage key
    _named_sid = defaultdict(list)                        # speciesId -> the form name of every key held there
    for _k, _lst in _all_by_key.items():
        _keys_of_sid[_sid(_lst[0])][_k[2]].append(_k)
        _fns = {evolvable_forms.canon_form(_sid(_lst[0]), evolvable_forms.form_name(_f))
                for _f in {_k[1]} | {(_r['form'] or 0) for _r in _lst}}
        _named_sid[_sid(_lst[0])].append(next((x for x in sorted(_fns) if x), ''))
        for _fn in _fns:
            if _fn:
                _key_of_formname.setdefault((_fn, _k[2]), _k)
    _committed = defaultdict(list)                        # stage key -> virtual evolved copies already promised there
    def _tkey(t, r):
        # the TARGET decides the gender component (2026-09-23): a Natu (one look) becoming a Xatu (two looks) lands on the
        # Xatu ladder of ITS gender; a female Combee becoming a Vespiquen (one look) lands on the single Vespiquen ladder.
        _ks = _key_of_sid.get(t, {})
        _g = evolvable_forms.gender_key(sp_to_dex.get(t), r['gender']) if sp_to_dex.get(t) else _gterm(r)
        # index, not .get: r may be a sqlite3.Row. src_sid + gender let the game answer for a form-0 specimen
        # (a Litleo reads Unset) and for a gendered branch (a male Litleo only ever becomes PYROAR_NORMAL).
        # canon_form on BOTH sides or they miss each other: the game's Pikachu branch carries no `form` field, so
        # the target read back as the bare 'RAICHU', matched no bag key, and the stage looked EMPTY -- a 60%
        # Pikachu then "earned" a Raichu slot an equal copy already held (2026-09-20). '' means "the base form",
        # which the speciesId path below already resolves correctly.
        _tf = evolvable_forms.canon_form(t, evolvable_forms.target_form(
            r['fresh_form'] or r['form'], t, _sid(r), r['gender']))
        if _tf:
            # gterm fallback EXACTLY as the speciesId path below: the stage's copies may be filed under gender
            # terminal 0 while the pre-evo carries one. Without it, a female Ralts looked up GARDEVOIRNORMAL at
            # gterm 2, missed the real Gardevoir pool, read the stage as EMPTY and a 68% "earned" a slot that a
            # 100% already holds -- audit_promises caught it as "culled after evolving" (2026-09-20).
            _fk = _key_of_formname.get((_tf, _g)) or _key_of_formname.get((_tf, 0))
            if _fk:
                return _fk
            # the game named a form we hold NO copy of, at ANY gender terminal -> the stage really is empty for
            # this lineage (a FloetteRed with only Yellow/Blue Florges held). Every copy of that speciesId must
            # carry a readable form name first, or a form-0 species would read as empty and over-promise.
            if all(_named_sid.get(t, ())) and _tf not in {k[0] for k in _key_of_formname}:
                return ('sid', t, _g, _tf)                # ONE virtual stage PER FORM (H08, 2026-09-29): the five Florges
                #                                           colours no copy of which is held used to share three slots
        return _ks.get(_g) or _ks.get(0) or ('sid', t, _g)   # ('sid', ...) = nothing of that stage in the bag yet
    def _virtual(r):
        v = dict(r); v['uid_hex'] = r['uid_hex'] + '~evo'   # same IV, CP and collectible attributes; new identity
        return v
    def _earns_slot(t, r):
        """Would the EVOLVED copy of r be kept at stage t right now? Same ranking, same dominance test as the cull."""
        key = _tkey(t, r); v = _virtual(r)
        # A SURPLUS CARD COPY is judged against the target's card slots first (rule 13's own cap): the special
        # background travels with it, and a stage that lacks that card gains a collectible (2026-09-16).
        _card = v['fresh_loc_card_enum'] if v['fresh_has_location_card'] == 1 else 0
        if _card:
            if key[0] == 'sid':
                return True                                   # nothing of that stage in the bag: the card slot is free
            _grp = [a for a in _all_by_key.get(key, []) + _committed.get(key, [])
                    if a['fresh_has_location_card'] == 1 and a['fresh_loc_card_enum'] == _card and not _slot_exempt(a)
                    and not costume_forms.card_folds_into_costume(a)]   # a costume copy holds no card slot (2026-09-24)
            _n = keep_config.species_cap('location_card', key[0], keep_config.cap('location_card'))
            if v['uid_hex'] in {x['uid_hex'] for x in topn(_grp + [v], _n)}:
                _best_c = max([(a['iv_total'] or 0) for a in _all_by_key.get(key, []) + _committed.get(key, [])
                               if a['fresh_has_location_card'] == 1 and a['fresh_loc_card_enum'] == _card
                               and not costume_forms.card_folds_into_costume(a)] + [-1])
                if len(_grp) >= _n or (v['iv_total'] or 0) > _best_c:
                    return True                           # a new card at that stage, a new best, or it replaces a weaker one
        pool = list(stage_pool.get(key, ())) + _committed.get(key, []) + [v]
        _n = _eff_cap(key, pool)
        _in = {x['uid_hex'] for x in topn(pool, _n)}
        if v['uid_hex'] not in _in:
            return False                                  # no plain slot: beyond the cap or displaced by a special
        # WORTH IT (user 2026-09-17 "make sure you dont make me evolve pokemon for no reason"): the evolved copy must
        # ADD something -- the first plain copy of that stage, a new best (a hundo there counts), or it pushes a weaker
        # copy out of a full top-N. Filling an open 2nd/3rd slot beneath better copies spends candy for nothing.
        # the ladder is measured by copies that HOLD a slot. A hundo never does (slot-exempt trophy), so it can no
        # longer make a stage "complete" and freeze its plain ladder (user 2026-09-23: "I keep hundos. They don't
        # count as a Variant 1" + "Always comb up").
        _best = max([(a['iv_total'] or 0) for a in _all_by_key.get(key, []) if a['uid_hex'] in _plain_ids
                     and _truly_plain(a) and not _slot_exempt(a)]
                    + [(c['iv_total'] or 0) for c in _committed.get(key, [])] + [-1])
        # ...UNLESS THE ALTERNATIVE IS RELEASING IT (user 2026-09-20: "im surprised you ask to transfer maschiff
        # instead of evolve it"). The rule above exists so a mon you are KEEPING anyway is not sent to burn candy
        # for a slot beneath better copies. A surplus pre-evo with no other keep reason is not in that position:
        # its two outcomes are "evolve into a slot the law says you may hold" and "gone forever". One Mabosstiff
        # and a cap of 3 means two empty slots, and a 13/14/10 Maschiff filling one beats releasing it.
        # ... and a copy the COLLAPSE is about to delete still carries its soft 'variant_floor' here, so it read as
        # "kept anyway" and was refused the open slot, then released (2026-09-23: the only plain Minccino 87%,
        # collapsed under a 98% costume copy while Cinccino had an open slot -- _evocheck caught it, sync blocked).
        # ... and NOT a within-cap STOCK copy (H08, 2026-09-29): its 'variant_floor' is marked only after it fails to move
        # up, so here it carried no reason and read as "kept for nothing else" -- 9 stock copies (two 93% Farfetch'd under
        # a 98% Sirfetch'd ...) were told to evolve into spare slots and 16 more held spare slots. Its alternative is
        # staying as stock, never release. _evocheck / audit_promises re-derive the same fact from the bag.
        _rescue = r['uid_hex'] in _collapsing or (r['uid_hex'] not in _stock_uids
                                                  and not ((keep.get(r['uid_hex']) or set()) - {'evolve_1', 'evolve_2'}))
        if len(pool) - 1 < _n and (v['iv_total'] or 0) <= _best and not _rescue:
            return False
        # A FULL stage must be IMPROVED, not reshuffled (2026-09-17): with every slot taken, an arrival whose IV
        # EQUALS the copy it pushes out only out-ranks it on the CP tie-break, so the evolution costs candy AND a
        # copy and leaves the ladder exactly where it was. _evocheck.improves has always been strict (`i > bar`).
        _drop = [x for x in pool if x['uid_hex'] != v['uid_hex'] and x['uid_hex'] not in _in]
        if _drop and max((x['iv_total'] or 0) for x in _drop) >= (v['iv_total'] or 0):
            return False
        mv, ivv = _domattr(v), (v['iv_total'] or 0)
        promised = {c['uid_hex'] for c in _committed.get(key, ())}
        for a in _all_by_key.get(key, []) + _committed.get(key, []):
            if a['uid_hex'] == v['uid_hex'] or _slot_exempt(a):
                continue                                  # a trophy never dominates
            if a['uid_hex'] not in keep and a['uid_hex'] not in promised:
                continue                                  # a transferred mon is never a dominator; a promised copy is kept
            ma = _domattr(a)
            if ma != mv and (ma | mv) == ma and (a['iv_total'] or 0) > ivv:
                return False                              # would be collapsed on arrival (dominance pass, same test)
        return True
    def _commit(t, r):
        _committed[_tkey(t, r)].append(_virtual(r))       # raise the bar: the next candidate competes with this one
    def _direct_children(p):
        ch = allreach_sp.get(p, set())
        return {c for c in ch if not any(c in allreach_sp.get(s, ()) for s in ch if s != c)}
    def _promisable(ts, src):
        """An item-gated target is skipped only when a CANDY sibling branch leaves the same parent stage (Politoed
        beside Poliwrath, Gallade beside Gardevoir, Bellossom beside Vileplume ...): "Evolve Next" cannot say which
        branch, and candy takes the wrong one. A linear chain whose last step needs an item (Piloswine -> Mamoswine,
        Roselia -> Roserade, Ursaring -> Ursaluna) stays promisable -- no wrong branch exists."""
        out = []
        for t in ts:
            if t in ITEM_GATED_TARGETS:
                parents = [p for p in ({src} | allreach_sp.get(src, set())) if t in _direct_children(p)]
                if any(c not in ITEM_GATED_TARGETS for p in parents for c in _direct_children(p) if c != t):
                    continue
            out.append(t)
        return out
    # THE LABEL NAMES THE PROMISED STAGE (2026-09-13). "Evolve Next" = evolve ONCE, the engine reserved a slot at the
    # very next stage; "Evolve Twice" = evolve TWICE, the slot is at the final. It used to print the evolutions
    # REMAINING (dist_sp), so a Gible the engine had committed to a GABITE slot still read "Evolve Twice"; the user
    # evolved 50 such base mons once, culled in between, and 9 fresh middle-stage copies fell to the pile. Steps are
    # derived from allreach_sp (exact for PoGo's <= 3-stage lines): t is a direct evolution of sid unless some
    # other reachable stage of sid reaches t itself.
    def _steps(sid, t):
        return 2 if any(t in allreach_sp.get(s, ()) for s in allreach_sp.get(sid, ()) if s != t) else 1
    def _promise_targets(r, tg):
        """The stage(s) a promise for r commits to, or [] when none holds. ONE rule for every promise site.
        A line that splits into more than one promisable final -- a random tap (Wurmple, Toxel, Eevee's candy trio)
        or a choice by evolution task / item the label cannot name (Charcadet, Galarian Slowpoke) -- is
        promised only when EVERY final has room, and commits to all of them (2026-09-17: five Charcadets were
        promised with Armarouge and Ceruledge both empty; five unguided evolutions can land 4 + 1)."""
        fin = {t for t in tg if not is_pre_sp.get(t)}
        fins = _promisable(sorted(fin), _sid(r))
        if len(fins) > 1:
            # ponytail: Tyrogue is IV-determined in GO but is treated as a split (conservative); middles of a split
            # line are never promised. Resolve per-mon branches here if either starts costing real slots.
            if all(_earns_slot(t, r) for t in fins):
                if _afford(r, fins):
                    return fins
                _short(r, fins)
                _earned_unpaid.add(r['uid_hex'])
                if r['uid_hex'] not in _unpaid_committed:   # AN UNPAID HOLD FILLS ITS SLOT (2026-09-29): without this every
                    for _rt in fins:                        # surplus copy held for the SAME open slot (6 Panpour, 6 Murkrow)
                        _commit(_rt, r)
                    _unpaid_committed.add(r['uid_hex'])
            return []
        earned = False
        for t in _promisable(sorted(fin) + sorted(tg - fin), _sid(r)):
            if _earns_slot(t, r):
                earned = True
                if _afford(r, [t]):                       # a final it cannot afford may still leave a cheaper middle
                    return [t]
        if earned:
            _short(r, _promisable(sorted(fin) + sorted(tg - fin), _sid(r)))
            # EARNED A SLOT, CANNOT PAY FOR IT TODAY. Affordability decides whether to ADVISE the evolution
            # (user 2026-09-17: "it can evolve, i just dont have the stone to do it" -- do not hand him a chore
            # he cannot do). It must NOT decide whether the mon LIVES: being 39 candy short is temporary and a
            # release is forever. A 13/14/10 Maschiff with two empty Mabosstiff slots was transferred for exactly
            # this (user 2026-09-20: "im surprised you ask to transfer maschiff instead of evolve it").
            _earned_unpaid.add(r['uid_hex'])
            if r['uid_hex'] not in _unpaid_committed:       # commit the FIRST slot it earns, like a paid promise (2026-09-29)
                _rt1 = next((t for t in _promisable(sorted(fin) + sorted(tg - fin), _sid(r)) if _earns_slot(t, r)), None)
                if _rt1 is not None:
                    _commit(_rt1, r)
                _unpaid_committed.add(r['uid_hex'])
        return []
    # 2. shadow: per (pid,form) keep the BEST by IV, the BEST by GL rank, AND the
    # BEST by UL rank (up to 3 distinct specimens). User 2026-05-30: open 2nd/3rd
    # slots so the top PvP shadow is kept even when it isn't the highest-IV one
    # (a 0/15/15 shadow ranks GL #1 but isn't the IV leader). Shadow ranks are the
    # shadow-CP-corrected gl_rank/ul_rank.
    # 2026-09-23 (user: "For shadows, only keep the top iv one, the best gl, the best ul, comb up" + "top iv is
    # implied to be top ml"): a shadow is a PvP asset and nothing else, so it is judged exactly like rule 15d --
    # per PvP IDENTITY (species + battle form; a shadow Unown A and Z share one), a stage that can reach the league
    # cap first, then rank, then uid (a total order: the old _best_by followed SQLite row order, so a recrawl could
    # flip a tie). ML has no cap to reach, so its order is simply ml_rank then uid. keep_config cap('shadow') is the
    # number of ML bests kept (1). At most 3 shadows per identity, fewer when one wins more than one league.
    # USABLE ONLY (user 2026-09-23: "Best GL/UL must be able to enter the league" + "evolve cps need to be figured out
    # completely"): the best GL / UL shadow is judged on _pvp_usable() below, exactly like rule 15d.
    def _best_by(lst, key):                  # still used by the legendary rule's best GL/UL (rarity, below)
        cand = [r for r in lst if r[key] is not None]
        return min(cand, key=lambda r: r[key]) if cand else None
    # THE COPY'S USABLE RANK (2026-09-23) -- shared by shadow rule 2, rule 15d and the own-stage evolve block below.
    # (viable_first, rank, stage) of the best stage this specimen can REACH (pvp_later_stages: form, costume, gender;
    # never candy or items) and ENTER (pvp_iv_rule.fits: its CP there at its TRUE level is inside the cap -- CP only
    # goes up, evolving keeps the level). None = no stage it can use in that league -> it can never be that league's
    # Best. Memoised: rows never change during a run.
    _pvp_usable_memo = {}
    def _pvp_usable(r, lg):
        _k = (r['uid_hex'], lg)
        if _k not in _pvp_usable_memo:
            _pvp_usable_memo[_k] = usable_best(r, lg, GL_CAP if lg == 'gl' else UL_CAP, BS,
                                               later=pvp_later_stages(r, _EVO_GRAPH))
        return _pvp_usable_memo[_k]
    def _pvp_usable_winner(lst, lg):
        """min over the copies that CAN use `lg` of (reaches the cap first, usable rank, uid_hex) -- a total order."""
        cand = [(u, r) for r in lst for u in (_pvp_usable(r, lg),) if u is not None]
        return min(cand, key=lambda x: (x[0][0], x[0][1], x[1]['uid_hex']))[1] if cand else None
    _shr = lambda r, k: r[k] if k in r.keys() else None
    # SHADOW RANK FLOOR (user 2026-09-24: "the cut is to be on the top 50% of the gl, ml, ul stuff"): a shadow is kept as
    # the best ML / GL / UL shadow only if that rank is <= keep_config pvp.shadow_rank_floor (the cut-off place of the
    # 4,096 spreads; GL/UL judged on the USABLE rank). A species whose best shadow ranks below it keeps no
    # shadow for that league. Mirrored in audit_cull and _lawcheck.
    _SRF = keep_config.pvp('shadow_rank_floor')
    sg = defaultdict(list)
    for r in shadows: sg[_sid(r)].append(r)
    for lst in sg.values():
        _ml = sorted((r for r in lst if _shr(r, 'ml_rank') is not None and r['ml_rank'] <= _SRF), key=lambda r: (r['ml_rank'], r['uid_hex']))
        for _sr in _ml[:keep_config.cap('shadow')]:
            mark(_sr['uid_hex'], 'shadow_best')                  # the best Master League shadow (inside the floor)
        for lg in keep_config.shadow_leagues():               # UL only since 2026-09-26 ("remove the gl shadows")
            _w = _pvp_usable_winner(lst, lg)
            if _w is not None and _pvp_usable(_w, lg)[1] <= _SRF:
                mark(_w['uid_hex'], 'shadow_best')               # the best Great / Ultra League shadow that can ENTER it, inside the floor

    # 3. shiny: top-20 by IV per (species, form) -- GYM-SPAM CAP (user 2026-06-05: "I place a single
    # shiny across all gyms; gym limit is 20, so trim all down to 20, keep highest IVs"). This OVERRIDES
    # the old 2026-05-29 "shinies off-limits / keep ALL" rule, by the user's explicit decision. Special
    # shinies (hundo/lucky/costume/dex-only) beyond the 20 are still kept by their OWN rule, so this only
    # transfers pure-shiny dupes past the 20th-highest-IV.
    # SHINY DOMINANCE-COLLAPSE (user 2026-06-08 "a shiny with a background can take the spot of another shiny
    # with no background and higher IV ... variants that collapse into each other into something better"): a
    # shiny is NOT kept on the shiny axis if a RICHER shiny of the same (pid,cf) -- one whose collectible set
    # (background / costume / Dmax / Gmax / shadow) is a STRICT SUPERSET of this one's -- exists at STRICTLY
    # higher IV. The richer copy subsumes it. The dominated shiny falls to Transfer ONLY if it has no other keep
    # axis (a shiny also kept by variant_floor/hundo/pvp/etc. keeps THAT axis). Hundo shinies never collapse.
    # IDENTITY-AWARE collectible signature (audit F6): a frozenset of (class, concrete id) pairs instead of
    # one bit per class. A superset now requires the SAME costume / SAME background plus >=1 extra attribute,
    # so two DIFFERENT costumes (or backgrounds) can never collapse into each other -- each is its own
    # collectible. The (ma|mb)==ma and ma!=mb proper-superset comparisons below work unchanged on frozensets.
    def _scollect(r):
        s = set()
        # ('sbg', ...) REMOVED -- special_bg_id is a garbage column (see _truly_plain note)
        if (r['fresh_natural_art_bg'] or 0): s.add(('abg', r['fresh_natural_art_bg']))           # fresh_ col -- F1
        if r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0): s.add(('loc', r['fresh_loc_card_enum']))
        if (r['fresh_costume'] or 0): s.add(('cos', r['fresh_costume']))
        elif _cosf_id(r): s.add(('cosf', _cosf_id(r)))                  # form-encoded costume (fresh_form, else `form`)
        _ax = evolvable_forms.max_axis(r['fresh_bread_mode'])
        if _ax: s.add(('gmax' if _ax == 'gigantamax' else 'dmax', 1))
        if r['fresh_alignment'] == 1: s.add(('shadow', 1))
        return frozenset(s)
    # COLLAPSE GOES UP, NOT DOWN (user 2026-06-10 "the other shinies shouldnt get booted... theyre only to
    # collapse up not down"): a richer shiny OUTRANKS within the capped top-N -- it takes a slot -- but it
    # does NOT delete every poorer shiny beneath it. The 2026-06-08 _dominated_shiny pass (richer strict-
    # superset + higher IV => poorer shiny dropped even WITHIN cap) is REVERSED: it mass-booted 6 shiny
    # Blisseys under one 80% shiny-Dmax. Shinies now live and die by the shiny cap alone; richness wins
    # the ORDERING when the cap is contested (dominators sort above their dominated at equal IV tier).
    shg = defaultdict(list)
    for r in shinies:
        shg[(r['pokemon_id'], cf(r))].append(r)
    def _shiny_rank(r):
        # richer-first at the margin: attr count breaks IV ties so a contested last slot goes to the
        # richer copy (the surviving intent of "a shiny with a background can take the spot")
        return (-(r['iv_total'] or 0), -len(_scollect(r)), -(r['cp'] or 0), r['uid_hex'])
    # PLAIN SHINIES TOP 3, SPECIALS AS BEFORE (user 2026-09-23: "Shiny plain forms can be brought to 3. the special
    # ones can stay at 6."): the group still keeps at most cap('shiny') in the same richer-first order, but only the
    # best cap('shiny_plain') PLAIN shinies (empty _scollect: no background / card / costume / Max / shadow) are
    # eligible. A species with its own per_species_caps.shiny exception (Gyarados) is an explicit "keep more", so its
    # plains share the whole exception. Mirrored in audit_cull, _lawcheck, preflight_transfer, refresh_evolve_shiny.
    for key, lst in shg.items():
        _tot = keep_config.species_cap('shiny', key[0], keep_config.cap('shiny'))
        _pl = _tot if keep_config.species_cap('shiny', key[0], None) is not None else min(_tot, keep_config.cap('shiny_plain'))
        _ranked = sorted(lst, key=_shiny_rank)
        # SHINY FLOOR (user 2026-09-24 "only the absolute shitty ones"): a plain shiny under keep_config.shiny_floor_iv
        # takes no plain slot -- unless it is the group's best shiny, which always stays (a form never loses its last
        # shiny). Specials are untouched. Mirrored in audit_cull, _lawcheck, preflight_transfer, refresh_evolve_shiny.
        _sfl = keep_config.shiny_floor_iv()
        _first = _ranked[0]['uid_hex'] if _ranked else None
        _plains = [x for x in _ranked if not _scollect(x)]
        _first_pl = _plains[0]['uid_hex'] if _plains else None   # the best PLAIN shiny stays too: a plain and a Max shiny are different variants
        _plain_ok = {x['uid_hex'] for x in [x for x in _plains
                                             if (x['iv_total'] or 0) >= _sfl or x['uid_hex'] in (_first, _first_pl)][:_pl]}
        for r in [x for x in _ranked if _scollect(x) or x['uid_hex'] in _plain_ok][:_tot]:
            mark(r['uid_hex'], 'shiny')

    # 4. hundo (all)
    for r in rows:
        if (r['iv_total'] or 0) == 45: mark(r['uid_hex'], 'hundo')

    # 5. rarity: top-12 by IV per (species, form, VARIANT) for legendaries/mythicals/
    # UB/paradox -- variant = shadow x bread-mode, so normal / shadow / Dynamax /
    # Gigantamax each keep their OWN top-12. EXCEPTION: Mewtwo (pid 150) keeps ALL
    # non-shiny copies -- no cap (user 2026-05-31: "just Mewtwo" -- exempt ONLY Mewtwo
    # from the transfer cap; every OTHER legendary still caps at top-12). Shinies are
    # EXCLUDED here (kept in full by the shiny rule, so they never eat a slot).
    # Roster-matched (references RARE_PIDS) so a NULL is_legendary column can't hide one.
    rg = defaultdict(list)        # (a) top-12 by IV, per (species,form,variant) -- NON-shiny, unchanged
    rgpf = defaultdict(list)      # (b) best GL/UL rank, per (species,form), for battle -- NON-shiny, unchanged
    # (c) THE SHINY EXEMPTION IS ONLY VALID WHILE THE SHINY RULE ACTUALLY KEEPS IT (2026-09-02).
    # The comment above says shinies are excluded because they are "kept in full by the shiny rule" -- but
    # rule 3 is a CAP (top-20 by IV per (pid,cf); 10 in the live config, with per-species overrides), not a
    # keep-all. A shiny legendary past that cap was SKIPPED here and DROPPED there, so the one axis that
    # exists to protect legendaries never saw it and nothing else did either. That is the "capped axis
    # modelled as keep-all" class this review exists to remove. Demonstrated by forcing the shiny cap to 1:
    # 16 shiny legendaries -- a shiny Mewtwo, Lugia, Rayquaza, Suicune, Zapdos, Regirock -- fell straight
    # into the irreversible pile with ZERO rarity protection.
    # Deliberately NOT merged into rg: a cap-dropped shiny must never DISPLACE a non-shiny out of the
    # rarity top-N (that would make this fix pile-additive -- verified: it evicted a plain Rayquaza). It
    # gets its OWN group under the SAME cap instead, so this is purely additive, and still a CAP rather
    # than a new keep-all. rgpf (best GL/UL) stays non-shiny, exactly as before.
    _rg_shiny = defaultdict(list)
    for r in rows:
        # 2026-09-08: the four is_legendary/is_mythical/is_ultra_beast/is_paradox columns were RETIRED as
        # engine inputs. They had no writer since a one-off migration; measured on the live bag every
        # flagged row was already on the RARE_PIDS roster (0 rows would lose protection) while 197
        # roster mons carried NULL/0 flags -- the roster was already the only thing protecting them.
        if not (r['pokemon_id'] in RARE_PIDS):
            continue
        _vk = (r['pokemon_id'], cf(r), 1 if r['fresh_alignment'] == 1 else 0, r['fresh_bread_mode'] or 0)
        if r['fresh_shiny']:
            if 'shiny' not in keep.get(r['uid_hex'], ()):   # rule 3 marks BEFORE this loop, so this reads
                _rg_shiny[_vk].append(r)                    # "the shiny cap dropped it"
            continue                                        # kept by rule 3 -> exempt, exactly as before
        rg[_vk].append(r)
        rgpf[(r['pokemon_id'], cf(r))].append(r)
    for key, lst in list(_rg_shiny.items()) + list(rg.items()):
        # LEAGUE LADDERS (Mewtwo, user 2026-09-26): top-N per league + every special / legacy / >90% copy, instead of
        # the plain top-N. keep_config.rarity_ladder_keep is the one implementation (audit_cull calls it too).
        _lad = keep_config.rarity_ladder(key[0])
        if _lad:
            _kk = keep_config.rarity_ladder_keep(lst, legacy, _lad)
            for r in lst:
                if r['uid_hex'] in _kk: mark(r['uid_hex'], 'rarity')
            continue
        n = len(lst) if key[0] in keep_config.rarity_keep_all() else keep_config.species_cap('rarity', key[0], keep_config.cap('rarity'))
        if key[2] == 1 and key[0] not in keep_config.rarity_keep_all():   # SHADOW legendaries (2026-09-29: "keep it at 3")
            n = min(n, keep_config.species_cap('rarity_shadow', key[0], keep_config.cap('rarity_shadow')))  # rarity_keep_all=keep ALL; else per-species override (Curation Studio) or global top-rarity
        for r in topn(lst, n): mark(r['uid_hex'], 'rarity')
    # 3-STAR FLOOR (user 2026-09-13: "weird to transfer a 91% [Necrozma]" -> "a 3-star legendary is never fodder
    # just because you have more" -> "ok"). Any roster legendary/mythical/UB/paradox at or above
    # keep_config.rarity_floor_iv (37/45 = the in-game 3-star line) is kept regardless of the top-N count, in
    # every variant group, shiny-cap overflow included. Mirrored in audit_cull (layer: rarity) and _spotdata.
    _rfloor = keep_config.rarity_floor_iv()
    for lst in list(rg.values()) + list(_rg_shiny.values()):
        for r in lst:
            if (r['iv_total'] or 0) >= _rfloor:
                mark(r['uid_hex'], 'rarity')
    # (b) the legendary rule's own "best GL + best UL per (species,form)" (2026-05-30) is GONE (user 2026-09-23, "ok do
    # it"): rule 15d keeps the best GL, UL and ML copy of EVERY species by PvP identity, legendaries included, and
    # rule 2 does the same for shadows. Two rules doing one job drift apart; this one was the older copy.

    # 6. legacy: KEEP ALL legacy-move mons (user 2026-06-05: "none of the transfer should have legacy
    # moves"; legacy can't be re-rolled without an Elite TM) -- EXCEPT per-species caps in LEGACY_SPECIES_CAP.
    # A capped species keeps: specials (shiny/shadow/costume/hundo) + best GL-rank + best UL-rank spread, then
    # fills to the cap with highest-IV plain; the rest get NO legacy reason -> Transfer (user 2026-06-06:
    # "reduce Absol to 26, keep highest IV, defer to plain first, keep the best gl/ul"). build_tagsets' Transfer
    # filter then drops the cut copies from the Legacy Moves tag automatically.
    LEGACY_SPECIES_CAP = keep_config.legacy_caps()    # per-species legacy caps from keep_config.json (Absol 359 -> 10)
    LEGACY_DEFAULT = keep_config.legacy_default_cap()  # global cap for legacy species NOT individually listed; None = keep-all
    def _legcap(pid): return LEGACY_SPECIES_CAP.get(pid, LEGACY_DEFAULT)   # per-species override, else the global default
    _lcap = defaultdict(list)
    for r in rows:
        if r['uid_hex'] not in legacy:
            continue
        if _legcap(r['pokemon_id']) is not None:
            _lcap[r['pokemon_id']].append(r)
        else:
            mark(r['uid_hex'], 'legacy')       # uncapped species: keep EVERY legacy specimen
    for _pid, _lst in _lcap.items():
        _ks = set()
        for r in _lst:                          # protect specials -- NEVER cut a shiny/shadow/costume/hundo
            if (r['fresh_shiny'] or r['fresh_alignment'] == 1 or (r['fresh_costume'] or 0)
                    or _cosf_id(r) or (r['iv_total'] or 0) == 45):
                _ks.add(r['uid_hex'])
        for _key in ('gl_rank', 'ul_rank'):     # + the best GL-rank and best UL-rank specimen
            _b = _best_by(_lst, _key)
            if _b: _ks.add(_b['uid_hex'])
        for r in topn([r for r in _lst if r['uid_hex'] not in _ks],
                      max(0, _legcap(_pid) - len(_ks))):   # fill to cap with highest-IV (plain cut first)
            _ks.add(r['uid_hex'])
        for _u in _ks:
            mark(_u, 'legacy')

    # 7. xxl: top-2 by SHOWCASE SCORE per (pid,cf), XXL only (user 2026-06-08: "top 2 for showcase scores,
    # I only care about XXL ones"). Niantic's score = height*0.80 + weight*0.15 + IV*0.05 (+flat XXL bonus,
    # constant within the group so it drops out of the ranking); height dominates, weight is correlated with
    # it, and there is NO separate weight-only showcase. Normalized by the group's max h/w (monotonic, so the
    # top-2 is exact). REPLACES the old top-2-height + top-1-weight (3-mon) split-proxy.
    # SHOWCASE (user 2026-09-23: "I want XXL tags to go to the 2 highest showcase scores. not just XXL" + "just per
    # species regardless of costume and other cosmetics"): per PvP IDENTITY (_sid: species + battle form -- Alolan /
    # Galarian are different Pokemon with their own size templates; costumes, hats, cards, backgrounds and Unown
    # letters fold together), the top cap('xxl') by the GAME'S showcase POINTS (size_line.showcase_points: the
    # per-species size bounds, 800/150/50, +178 XXL), XXL BADGE ONLY (user, same day: "they should only be tagged if
    # they're actually XXL though" -- an XXL always outscores a non-XXL of its species, so this is the top-2 overall
    # wherever an XXL exists, and nothing where none does). Tag 'XXL'. Re-derived every cull; full_audit diffs it
    # against the previous pass. Mirrored in build_tagsets, preflight_transfer, audit_cull, audit_tags_membership,
    # audit_tag_truth, _spotdata, studio_data.
    import size_line as _slx
    _SC_MIN = keep_config.showcase_weights()['min_points']
    # EVOLUTION COUNTS (user 2026-09-24): points = the best of the own stage and every later stage this copy can become
    # (size_line.best_points over the engine's own graph -- the reach Best GL/UL uses; the mirrors build the same graph).
    _xl = lambda x: pvp_later_stages(x, _EVO_GRAPH)
    # ONE SELECTION (2026-09-29): size_line.xxl_keepers -- the top species_cap('xxl') per species + battle form by these
    # points (>= min_points), and ONLY during an XXL TRIM (caps.xxl_per_type > 0; user: "a one time thing, that will be
    # done sometimes when i say") also the top-N per TYPE. Every mirror calls the same function; audit_cull re-derives.
    for _u in _slx.xxl_keepers(rows, _xl):
        mark(_u, 'xxl')


    # 7b. XXS smallest-trophy axis (audit improvement, 2026 size badges/Showcases) -- OFF BY DEFAULT
    # (rules.xxs=false in keep_config), so behavior is unchanged until the user flips the knob. When on:
    # top-N per (species,form) among size_category==1, smallest height then weight, IV tiebreak.
    if keep_config.rule_enabled('xxs'):
        sg2 = defaultdict(list)
        for r in rows:
            if (r['pokemon_size_category'] or 0) == 1: sg2[(r['pokemon_id'], cf(r))].append(r)
        for key, lst in sg2.items():
            for r in sorted(lst, key=lambda x: ((x['height_m'] or 9e9), (x['weight_kg'] or 9e9), -(x['iv_total'] or 0), x['uid_hex']))[:keep_config.species_cap('xxs', key[0], keep_config.cap('xxs'))]:
                mark(r['uid_hex'], 'xxs')

    # 8-13. keep-all purposes. The switchable axes (nundo/adventure_effect/mighty/location_card/dex_only)
    # honor the keep_config 'rules' toggles (default ALL ON = unchanged behavior). protected/origin are NOT switchable.
    _R = {k: keep_config.rule_enabled(k) for k in ('nundo', 'adventure_effect', 'mighty', 'location_card', 'dex_only')}
    import trophy_pick
    _NUNDO_KEEP = trophy_pick.pick_nundos(rows)   # user 2026-09-17: one nundo per look, most exotic catch place first
    _OO = keep_config.origin_owners()
    for r in rows:
        # 2026-09-07: the adventure_effects_left column term was DROPPED. That column is a mis-identified
        # proto field (offset 0x1F0 is markedRemoteTradable_, a bool read as i32 by a 2026-05-05 one-off);
        # PokemonProto has no per-mon Adventure-Effect charge -- the mechanic is player-level. The roster
        # in keep_config governs. Verified pile-neutral: every off-roster mon it touched carries another
        # keep reason. preflight_transfer.py keeps the column as a superset guard (over-protects, costs 0).
        # FORM-level (2026-09-09): only the form that HAS the effect is an Adventure-Effect keeper; a base-form
        # copy of the same species is an ordinary legendary and falls under the rarity cap like any other.
        # PER MON (2026-09-23, user: "look at each pokemon that actually has it"): it knows an Adventure-Effect move.
        # Only when the live registry cannot be read does it fall back to the form / species roster (over-protects).
        if AE_MOVES is not None:
            _ae_hit = bool(_ae_moves.known(r, AE_MOVES))
        else:
            _ae_hit = (_sid(r) in AE_SIDS) if AE_SIDS is not None else (r['pokemon_id'] in AE_IDS)
        if _ae_hit and _R['adventure_effect']: mark(r['uid_hex'], 'adventure_effect')
        if r['is_zero'] and r['pokemon_id'] and _R['nundo'] and r['uid_hex'] in _NUNDO_KEEP: mark(r['uid_hex'], 'nundo')   # one per look (2026-09-17)
        # best_buddy keep-reason REMOVED 2026-06-07 (user "nuke best buddy ... my best buddies are goats anyway").
        if (r['is_traded'] == 1 or r['is_traded_flag_v2'] == 1 or r['is_lucky'] == 1) and \
           (r['original_owner_name'] or '').strip().lower() in _OO: mark(r['uid_hex'], 'origin')
        if r['fresh_is_strong'] == 1 and _R['mighty']: mark(r['uid_hex'], 'mighty')
        # location_card is now CAPPED -- see the grouped pass right after this loop
        if r['pokemon_id'] in PROTECTED_KEEP_ALL: mark(r['uid_hex'], 'protected')      # user "leave them alone" (Pichu) -- keep every copy, no cap
        if (r['is_favorite_v2'] or 0) == 1: mark(r['uid_hex'], 'favorite')   # user 2026-09-17 "keep em": a starred mon is never culled

    # 13b. LOCATION CARD -- CAPPED, top-N per (species, form, CARD TYPE) (user 2026-09-02 "top 6 per
    # species per card"). Was keep-ALL: all 304 holders kept unconditionally, 161 of them by this axis
    # alone at 22%-93% IV, so a 22% Pikachu with a card outranked nothing and was still safe forever.
    # The per-CARD grain is the collection-correct one (each card is a distinct place/event collectible)
    # and only became computable after the 2026-09-02 deep rescan filled fresh_loc_card_enum -- 203 of
    # the 304 holders previously carried an UNKNOWN card id, and capping them per-card then would have
    # lumped all 203 into one fake group and culled genuinely different cards as if they were dupes.
    # A holder whose enum is STILL unknown is left UNCAPPED (unknown data means protected, never fodder).
    if _R['location_card']:
        _lcg = defaultdict(list)
        _lc_cap = keep_config.cap('location_card')
        for r in rows:
            if r['fresh_has_location_card'] != 1:
                continue
            _enum = r['fresh_loc_card_enum'] or 0
            if not _enum:
                mark(r['uid_hex'], 'location_card')      # unknown card -> uncapped, protected
                continue
            if costume_forms.card_folds_into_costume(r):
                continue      # costume + background = ONE ladder (user 2026-09-24): the costume's top-N (rule 1a) holds it
            _lcg[(r['pokemon_id'], cf(r), _enum)].append(r)
        for (_lc_pid, _lc_cf, _lc_enum), _lst in _lcg.items():
            # PER-SPECIES CAP (2026-09-03). This axis read the GLOBAL cap ONCE, outside the loop, and
            # applied that flat number to every group -- the ONLY capped axis in this engine that did
            # not consult keep_config.species_cap(). keep_config.py:362 has whitelisted 'location_card'
            # as a per-species category since the Studio shipped, so the dashboard/Studio could save an
            # override at any moment and the engine would silently ignore it: a user who raised
            # location_card for a species to KEEP more of them would instead watch the extras land in
            # the irreversible Transfer pile. Same failure CLASS as the capped-vs-keep-all defect that
            # has now recurred 10+ times in this engine (shiny, cosmetic, xxl, xxs, rarity, dynamax,
            # gigantamax, shadow, legacy, plain-line ... and now location_card): a cap resolved ONCE at
            # the wrong scope instead of per-group. Rule of thumb for the next axis anyone adds -- if
            # it caps, it resolves its cap INSIDE the group loop via species_cap(axis, pid, global).
            # The group key already carries the pid, so this is the whole fix. Behaviour with an EMPTY
            # per_species_caps.location_card is byte-identical to before (species_cap falls back to
            # the global cap), which is why the live 80-uid pile does not move.
            _cap = keep_config.species_cap('location_card', _lc_pid, _lc_cap)
            # trophies are kept unconditionally elsewhere and must never consume a capped slot
            _pool = [r for r in _lst if not _slot_exempt(r)]
            for r in topn(_pool, _cap):
                mark(r['uid_hex'], 'location_card')
            for r in _lst:
                if _slot_exempt(r):
                    mark(r['uid_hex'], 'location_card')

    # 14. dex completeness: the only copy of a (pid,form) (switchable via keep_config 'rules.dex_only')
    if _R['dex_only']:
        dg = defaultdict(list)
        for r in rows:   # every-line pools (2026-09-26): "the only copy" is per POOL -- a line's lone copy stays (even
            #              under the IV floor); the only Ivysaur of a line that keeps others may go
            dg[(_pkey(r) if keep_config.line_pool_all() else None) or (r['pokemon_id'], cf(r))].append(r)
        for lst in dg.values():
            if len(lst) == 1: mark(lst[0]['uid_hex'], 'dex_only_copy')

    # (gender-locked evolutions AND evolve-candidates are now handled INSIDE the plain line cap 1b:
    # a female Combee competes for the Vespiquen slots and is tagged 'evolve' if it wins one; the
    # whole line is pooled by IV so the best pre-evos claim cap slots and displace weak terminals.)

    # 15. PvP IV keep -- shared rule (pvp_iv_rule.qualifies, also drives the
    # 1 GL/UL IV tags). Low-attack only; READY evolved mons (rank<=5 AND under the
    # league CP cap 1500/2500 so they can actually ENTER the league) + perfect-bulk
    # pre-evo BUILD-TARGETS (def>=14 & sta>=14); cuts mediocre pre-evos (Tentacool
    # 0/11/12), under-cap hundos, AND over-cap mons (a cp2494 Gardevoir is UL, not GL).
    for r in rows:
        if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'],
                            r['iv_sta'], r['gl_stage'], r['gl_rank'], GL_FLOOR, BS, r['cp'], GL_CAP, row=r):
            mark(r['uid_hex'], 'gl_iv')
        if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'],
                            r['iv_sta'], r['ul_stage'], r['ul_rank'], UL_FLOOR, BS, r['cp'], UL_CAP, row=r):
            mark(r['uid_hex'], 'ul_iv')
    # PvP-perfect 0/15/15 spread kept outright (user-named), regardless of rank/CP.
    _trophy = keep_config.pvp_spread_keep()
    for r in rows:
        if (r['iv_atk'], r['iv_def'], r['iv_sta']) in _trophy:
            mark(r['uid_hex'], 'pvp_spread')

    # 15b. PvP RANK SAFETY NET (user 2026-06-05: "check every single iv rank for their league" -- after a
    # 0/13/11 GL#1 Mareep was culled on IV magnitude and released). GUARANTEE: ANY mon that is
    # top-READY_RANK for a CP-VIABLE evolved league form (GL or UL) is KEPT, period -- never transferred on
    # IV total/bulk. Superset of gl_iv/ul_iv: ALSO catches a rank-perfect spread currently OVER its league
    # cap (can't enter now, but still an elite build you won't lose). GL + UL only -- Little League (cap 500)
    # would protect ~every tiny common and gut the cull. This is the rule that would have saved the Mareep.
    def _viable(stage, cap):
        return bool(stage) and pvp_maxcp(stage, BS) > cap + VIABILITY_MARGIN

    def _pvp_asset(r):
        # ONLY A COPY THAT CAN PLAY (user 2026-09-30: "Why would I keep any GL and UL pokemon that cant participate?
        # powering up is fine, but if its impossible in its best form for pvp, then wtf"). pvp_iv_rule.plays(): a
        # top-READY_RANK stage in the chain that reaches the cap AND that this copy fits under -- now at its own
        # stage, or after evolving at its true level (fits(); unknown data => fits, so missing data never strips
        # protection). Until 2026-09-30 this was CP-blind: gating it was tried 2026-09-19 and sent 9 real spreads to
        # the pile, because it was then their ONLY PvP protection; the usable-only Best GL/UL rule (15d) and this
        # per-stage sweep came after. On the 12:19 walk this gate changed 0 keeps (the 4 over-cap top-5 copies were
        # all kept for a league they CAN play).
        return plays(r, 'gl', GL_CAP, BS) is not None or plays(r, 'ul', UL_CAP, BS) is not None
    for r in rows:
        if _pvp_asset(r):
            mark(r['uid_hex'], 'pvp_rank')

    # 15c. RANK-DATA GUARD (2026-09-02) -- the missing half of the Mareep lesson.
    # Rules 15/15a/15b all begin `rank is not None`, so a mon whose ranks were never computed silently
    # gets NO PvP protection at all -- the same outcome as a mon that genuinely ranks badly, from data
    # that simply is not there. That is the difference between "we checked and it isn't a keeper" and
    # "we never checked", and only the first one may put a mon in an irreversible pile.
    # PER-ROW: both ranks NULL -> unknown -> PROTECTED. One in-bag row today, the Enamorus Therian whose
    # form (2803) is missing from form_overrides_complete.py so pvid() cannot resolve it -- a real data
    # bug that happens to be masked by its legendary status. If that same gap ever lands on a common
    # species, this is what stops it from being released.
    # SYSTEMIC: if a FIFTH of the bag has no ranks, the rank pipeline (rank_cache.py / compute_all_ranks)
    # did not really run, and every PvP protection in this engine is vacuous. Refuse the pile outright --
    # per-row protection would silently turn into "keep almost everything", which hides the breakage.
    _norank = [r for r in rows if r['gl_rank'] is None and r['ul_rank'] is None]
    if rows and len(_norank) * 5 > len(rows):
        raise SystemExit("ABORT keep_policy: %d/%d in-bag mons have NO gl_rank AND NO ul_rank -- the rank "
                         "pipeline did not run, so every PvP keep rule (15/15b) is silently vacuous. Re-run "
                         "the rank build before culling." % (len(_norank), len(rows)))
    for r in _norank:
        mark(r['uid_hex'], 'rank_unknown')
    if _norank:
        print(f"[GUARD] {len(_norank)} mon(s) have no GL/UL rank -> kept as 'rank_unknown' (never judged "
              f"on PvP data that was never computed).", flush=True)

    # 15d. BEST OF ITS KIND (user 2026-09-23: "plus best GL and best UL -- should be for each species, not just
    # legendaries. And no card or form matters" -> "1+3"). The best Great League copy and the best Ultra League copy
    # of every PvP IDENTITY among NON-shadow copies: shadows keep rule 2's own best GL/UL, and `!= 1` lets purified
    # and NULL-alignment copies compete. Every form, card, background, costume and shiny competes.
    # USABLE ONLY (user 2026-09-23: "Usable only -- Best GL/UL must be able to enter the league" + "evolve cps need to
    # be figured out completely"). A copy competes in GL / UL only with a stage it can both REACH and ENTER
    # (_pvp_usable above): its own stage on its real CP, or a later stage its form, costume and gender can become on
    # its CP there at its TRUE level. The old key read gl_rank/gl_stage -- the best rank across every stage, CP-blind --
    # so a hundo Centiskorch at CP 3301 and a Houndstone at CP 1777 were "Best GL" while the best copies that can play
    # Great League sat in the pile, and a Thwackey was Best GL for a Rillaboom it would be over 1500 as.
    # Best = min over the copies with a usable stage of (that stage can reach the cap first, the usable rank, uid_hex):
    # a TOTAL order, so a recrawl can never flip a tie (never _best_by -- that follows SQLite rowid order). A copy with
    # no usable stage cannot be Best GL/UL; an identity with no usable copy has no Best GL/UL. Master League has no
    # cap: its key is unchanged (viable ml_stage first, ml_rank, uid_hex). Two reasons, so the Best GL / Best UL tags
    # and the own-stage evolve block can read which league a copy won. min(), never a [:1] slice (audit_invariants
    # I1.4). Re-derived independently (selection) in audit_cull, _lawcheck, _spotdata, audit_tags_membership and
    # preflight_transfer; they share only pvp_iv_rule's CP/level helper (fits / true_level).
    def _pvp_best_winners():
        won = defaultdict(set)
        groups = defaultdict(list)
        for r in rows:
            if r['fresh_alignment'] == 1:
                continue
            # PvP IDENTITY (user 2026-09-23: "for PVP, cosmetics don't matter. just the species it is whether ...
            # normal or galarian or alola"). pvid() already gives a form its own id exactly when it battles
            # differently; Unown letters, colours, costume forms, hats, cards and backgrounds all share one.
            groups[_sid(r)].append(r)
        _v = lambda r, k: r[k] if k in r.keys() else None     # ml_* exists only once rank_cache has run
        # BEST RANK FLOOR (user 2026-09-24 "Top 20% then?"): the identity's best is kept only while that rank is inside
        # keep_config pvp.best_rank_floor (a place of the 4,096 spreads); a species whose best copy ranks below it keeps
        # no Best GL/UL/ML. Mirrored in audit_cull, _lawcheck, preflight_transfer, audit_tags_membership, _spotdata.
        _BRF = keep_config.pvp('best_rank_floor')
        for lst in groups.values():
            for lg in ('gl', 'ul'):
                b = _pvp_usable_winner(lst, lg)
                if b is not None and (_pvp_usable(b, lg)[1] <= _BRF or b['pokemon_id'] in RARE_PIDS):   # legendaries: no rank floor (user 2026-09-24)
                    won[b['uid_hex']].add(lg.upper())
            cand = [r for r in lst if _v(r, 'ml_rank') is not None and (r['ml_rank'] <= _BRF or r['pokemon_id'] in RARE_PIDS)]
            if cand:
                b = min(cand, key=lambda r: (0 if _viable(r['ml_stage'], ML_CAP) else 1, r['ml_rank'], r['uid_hex']))
                won[b['uid_hex']].add('ML')
        return won
    _PVP_BEST = _pvp_best_winners()
    for _u, _lgs in _PVP_BEST.items():
        if 'GL' in _lgs:
            mark(_u, 'pvp_best_gl')
        if 'UL' in _lgs:
            mark(_u, 'pvp_best_ul')
        if 'ML' in _lgs:
            mark(_u, 'pvp_best_ml')

    # 15e. PvP COMB-UP (user 2026-09-24: "im basically asking for the scan to be expanded to everyone so all ul and gl get
    # combed up" + "I don't want to waste time catching pokemon just to lose opportunities"). 15d keeps ONE copy per
    # identity -- on a branching / multi-stage line the copy that would make your best Jolteon, Glaceon or Honchkrow
    # rode on luck. For every GL / UL target stage, the copy that would beat the best you own THERE after evolving
    # (and still fit the league) is kept -- one copy per target, never a copy evolving would destroy (own-stage best,
    # top-5 spread, legacy move, last copy / only shiny of its form, protected). ONE definition: pvp_combup.pick,
    # called with this engine's own graph; preflight_transfer, audit_cull, _lawcheck, audit_tags_membership and
    # audit_tag_truth call it on the same files. Tags 'Evo Best GL' / 'Evo Best UL'.
    import pvp_combup
    _CU = pvp_combup.pick(rows, lambda r: pvp_later_stages(r, _EVO_GRAPH), BS, keep_config.pvp('best_rank_floor'),
                          RARE_PIDS, legacy, keep_config.protected_pids())
    for _u in _CU['gl']:
        mark(_u, 'pvp_combup_gl')                  # literal reasons: audit_invariants reads the mark() sites
    for _u in _CU['ul']:
        mark(_u, 'pvp_combup_ul')

    # ---- SEED-BAR ORACLE EXPORT (for the on-catch pre-filter) --------------------------------
    # Snapshot each stage's bar BEFORE any comb-up promotion, with the ONE model: the smallest IV at which a
    # plain copy (max CP, so it wins every tie) would earn a slot at that stage and survive the dominance
    # pass, minus one; None if any IV earns one. Promotions only raise bars, so a pre-promotion bar is a
    # provable LOWER BOUND on the bar any future candidate faces: iv <= seed_bar[t] for EVERY reachable stage
    # t => can never be rescued by comb-up. Stale is safe in the only direction that matters (new catches
    # raise bars; only a release lowers one, which is why the consumer re-reads after every release).
    try:
        import json as _json, os as _os, time as _time
        def _probe_row(t):
            _ks = _key_of_sid.get(t, {}); _k = _ks.get(0) or (next(iter(_ks.values())) if _ks else None)
            _f = (_k[1] if _k and _k[0] != 'sid' else 0) or 0        # the stage's canonical (plain) form
            # species_name: _tkey -> _sid(r) reads it -- without it every export since 2026-09-20 died on KeyError
            # 'species_name' and fodder_oracle.json stayed frozen at that date (H06-3, fixed 2026-09-29)
            return {'uid_hex': '~probe', 'iv_total': 0, 'cp': 10 ** 9, 'is_zero': 0, 'gender': 0,
                    'species_name': _name_of_sid.get(t, ''),
                    'pokemon_id': (_k[0] if _k and _k[0] != 'sid' else 0), 'form': _f, 'fresh_form': _f,
                    'fresh_shiny': 0, 'fresh_natural_art_bg': 0, 'fresh_has_location_card': 0, 'fresh_loc_card_enum': 0,
                    'fresh_costume': 0, 'fresh_bread_mode': 0, 'fresh_alignment': 0, 'costume_decoration_id': 0}
        def _seed_bar(t):
            _p = _probe_row(t); lo, hi = 0, 45                        # smallest iv in [0, 45) that earns a slot
            while lo < hi:
                mid = (lo + hi) // 2; _p['iv_total'] = mid
                if _earns_slot(t, _p):
                    hi = mid
                else:
                    lo = mid + 1
            return None if lo == 0 else lo - 1
        _seed = {str(_t): _seed_bar(_t) for _t in _key_of_sid}
        _orc = {
            'generated': _time.strftime('%Y-%m-%d %H:%M:%S'),
            'note': 'SEED bars, pre-promotion. iv <= bar for ALL reachable stages => provably fodder.',
            'preevo_cap': PREEVO_CAP, 'line_cap': LINE_CAP,
            # pattern-pooled lines have NO speciesId bar (their cap is per pattern across the line, see
            # pattern_pools.py); a consumer must treat a missing bar as "unknown -> not fodder".
            'pattern_pooled_pids': pattern_pools.pooled_pids(),
            'seed_bar': _seed,
            'reach': {str(k): sorted(v) for k, v in allreach_sp.items()},
            'is_pre': {str(k): bool(v) for k, v in is_pre_sp.items()},
        }
        _op = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                            _os.pardir, 'analysis', 'fodder_oracle.json')
        with open(_os.path.normpath(_op), 'w', encoding='utf-8') as _fh:
            _json.dump(_orc, _fh)
    except Exception as _oe:
        print('oracle export skipped:', _oe)
    # comb-up: strongest candidate fills/upgrades each terminal first (one merged IV-sorted pass over BOTH the
    # stage top-3 surplus AND the beyond-cap extras). Fallback differs: a stage-stock surplus stays at-stage if
    # redundant; a beyond-cap extra that doesn't improve any terminal gets NO mark -> Transfer.
    # EVOLVE SHINY FIRST (user 2026-09-17 "shiny ladder like plains" -> "yes"): its targets spend candy before the plain
    # comb-up, and a shiny past the shiny cap is HELD when evolving it earns a shiny spot at the next stage -- the same
    # climb a plain copy gets. Fails loud: build_tagsets computes the same list and would fail anyway.
    import refresh_evolve_shiny as _res
    _sp = {}
    _si = {}                                                      # stones the shiny ladder spends first
    _shiny_gated = {}                                             # shiny upgrades that need more than candy (2026-09-17)
    _shiny_held = {}                                              # earned a shiny spot, cannot take it today (H08)
    for _u in _res.compute_target(why={u: set(v) for u, v in keep.items()}, spent=_sp, gated=_shiny_gated, db=DB, walk=_walk,
                                  items_spent=_si, held=_shiny_held):
        mark(_u, 'shiny_ladder')
    for _u in _shiny_held:           # LAW: "A shiny past the shiny cap is held (reason shiny_ladder) when it earns such a spot"
        mark(_u, 'shiny_ladder')     # -- candy short or gated today is temporary, a release is not (H08, 2026-09-29)
    if _candy_left is not None:
        for _f, _n in _sp.items():
            _candy_left[_f] = _candy_left.get(_f, 0) - _n
    if _items_left is not None:                                   # the shiny ladder spends stones first, like candy
        for _k, _n in _si.items():
            _items_left[_k] = _items_left.get(_k, 0) - _n
    _cands = [(r, True) for r in evo_cands] + [(r, False) for r in evo_extra]
    for r, _is_stock in sorted(_cands, key=lambda x: (-(x[0]['iv_total'] or 0), -(x[0]['cp'] or 0), x[0]['uid_hex'])):  # full tiebreak -> deterministic order
        _riv = r['iv_total'] or 0
        _done = False
        if r['uid_hex'] in _pinned:
            continue                                            # this stage's resident -- stays (already marked)
        # A COPY KEPT AS A COLLECTIBLE IS NEVER ADVISED TO EVOLVE (user 2026-09-16: four of six card-19 Charmanders,
        # all within the card cap, were told to evolve -- "is that because I already have 3 to spare?" No). Evolving
        # consumes the copy at THIS stage: a special background or XXL showcase copy leaves the stage, legacy moves
        # reroll away, the last copy of a form is gone, an own-stage PvP asset stops being that asset. Only SURPLUS
        # copies climb. (keep is complete here: the loop runs after every axis.)
        _kr = keep.get(r['uid_hex'], set())
        # ... and a Best GL / Best UL copy whose winning rank is at its OWN stage (user 2026-09-23: "only if its best
        # rank is at a later stage"). Mirrored in audit_labels, refresh_evolve_shiny and sync_evolve_size.
        # The winning stage is the USABLE one (_pvp_usable, 2026-09-23): a Best copy that wins as itself is an
        # own-stage asset; one that wins as a later stage it can reach AND enter may evolve to it. A Best copy with no
        # usable stage cannot happen (it could not have won) -- read as own-stage, the side that never consumes it.
        _ubg = _pvp_usable(r, 'gl') if 'pvp_best_gl' in _kr else None
        _ubu = _pvp_usable(r, 'ul') if 'pvp_best_ul' in _kr else None
        _own_pvp = ((r['gl_stage'] == _sid(r) and r['gl_rank'] is not None and r['gl_rank'] <= READY_RANK and _viable(r['gl_stage'], GL_CAP))
                    or (r['ul_stage'] == _sid(r) and r['ul_rank'] is not None and r['ul_rank'] <= READY_RANK and _viable(r['ul_stage'], UL_CAP))
                    or ('pvp_best_gl' in _kr and (_ubg is None or _ubg[2] == _sid(r)))
                    or ('pvp_best_ul' in _kr and (_ubu is None or _ubu[2] == _sid(r))))
        if (_kr & {'location_card', 'xxl', 'legacy', 'dex_only_copy', 'mighty', 'protected'}) or _own_pvp:
            if _is_stock:
                mark(r['uid_hex'], 'variant_floor')             # stays at-stage stock, as before
            continue
        _tg, _tg_blocked = _gender_split_targets(r, allreach_sp.get(_sid(r), set()))   # ALL later stages, as speciesIds
        _fin = {t for t in _tg if not is_pre_sp.get(t)}          # finals (highest value -- try these first)
        _mid = _tg - _fin                                        # middle stages
        def _pin_resident(r=r):
            """First promotion out of a MIDDLE stage: the best copy NOT moving up becomes its resident."""
            _k = _stage_key(r)
            if not _is_middle_sid(_sid(r)) or any(x['uid_hex'] in _pinned for x in stage_pool.get(_k, ())):
                return
            for _x in topn(stage_pool.get(_k, []), len(stage_pool.get(_k, []))):
                if _x['uid_hex'] != r['uid_hex'] and not any(v.startswith('evolve_') for v in keep.get(_x['uid_hex'], ())):
                    mark(_x['uid_hex'], 'variant_floor'); _pinned.add(_x['uid_hex']); return
        _pt = _promise_targets(r, _tg)                           # deterministic (sorted); split lines need every final
        if _pt:
            _spend(r, _pt)                                      # candy, best-first (2026-09-17)
            _promises[r['uid_hex']] = list(_pt)
            mark(r['uid_hex'], f"evolve_{_steps(_sid(r), _pt[0])}")   # steps to the PROMISED stage (2026-09-13)
            for t in _pt:
                _commit(t, r)                                   # raise the bar(s): no redundant promotions
            _pin_resident(); _done = True
        if not _done and r['uid_hex'] in _earned_unpaid:
            # IT EARNED A SLOT AND CANNOT PAY FOR IT TODAY. Same shape as the phantom-rescue case below: kept as
            # at-stage stock, NOT advised to evolve (a chore he cannot do) and NOT allowed to commit a bar it has
            # not filled. Candy is temporary, a release is not (user 2026-09-20: "im surprised you ask to transfer
            # maschiff instead of evolve it" -- 11 candy short of its second Mabosstiff, two slots standing empty).
            mark(r['uid_hex'], 'variant_floor')
            if r['uid_hex'] in _unpaid_committed:
                # A COMMITTED HOLD IS A PROMOTION TOO (H09-5, 2026-09-29): it holds its later-stage slot for every bar
                # after it, so -- exactly like a paid promotion -- the best copy NOT moving up stays as the MIDDLE
                # stage's resident. Without this the resident competed for the same stage and committed a second
                # hold, and the copies a paid pass promotes were piled: with candy.json unread the 05:20 bag's pile
                # grew 2 -> 6 (Floette 73%, Pawmo 91%, Primeape 89% / 84%) -- unknown data deciding a release.
                _pin_resident()
            _done = True
        if not _done and _tg_blocked and any(_earns_slot(t, r) for t in sorted(_tg_blocked)):
            # It only "improved" a stage its GENDER cannot reach. Removing that phantom rescue must not
            # push a mon into the IRREVERSIBLE pile, so keep it as at-stage stock instead -- kept, but
            # NOT advised to evolve and NOT allowed to commit a bar it can never actually fill.
            mark(r['uid_hex'], 'variant_floor')
            _done = True
        if not _done and _is_stock:
            mark(r['uid_hex'], 'variant_floor')                 # stage top-3 surplus -> keep at-stage stock
        # a beyond-cap extra that improves nothing -> no mark -> Transfer (correctly considered, then released)

    # NO BACKFILL (user 2026-09-13 "Are you truly listening to me when I say Comb up?"): a stage holds the best N you
    # own, promised or not; a copy enters only by beating one of them. The middle stage's best copy competes in IV
    # order above; the first promotion out of a middle stage pins the best remaining copy as resident (_pinned).
    # ---- UNIVERSAL DOMINANCE COLLAPSE (user 2026-06-09 "they only take up slots") --------------------------
    # A mon kept ONLY by collection-copy axes (variant_floor / shiny) is REDUNDANT if a strictly-richer sibling
    # of the same (pid,cf) exists at strictly-higher IV -- "richer" = a STRICT SUPERSET of its special attributes
    # {shiny, background, costume, Dynamax, Gigantamax, shadow}. The richer copy is just a better version of it
    # (a 98% Dmax Blissey covers a 93% plain Blissey; a Dmax-shiny covers a pure shiny). Drop the redundant one
    # -> Transfer. Hundos AND any unconditional axis (legacy/origin/pvp/location_card/rarity/xxl/mighty/...) are
    # NEVER collapsed. Matches the lattice plain < dmax = shiny < dmax+shiny: dmax & shiny don't erase each other
    # (incomparable sets), but the combined higher-IV copy erases both.
    # 'shiny' REMOVED from the soft set (user 2026-06-10 "collapse up not down"): a mon the shiny axis
    # keeps is never collapse-dropped -- richer copies outrank shinies in CAP contests, they don't erase
    # them. Plains/variant-floor-only mons still collapse upward into any strictly richer sibling.
    _SOFT = {'variant_floor'}
    _domgrp = defaultdict(list)          # _domattr is defined above the comb-up bar: the bar needs the dominators too
    for r in rows:
        # gender-split for gender-evolvers (audit F7): a rare FEMALE Combee/Salandit/Burmy plain must never
        # be dominance-collapsed by a MALE special -- the female is the evolutionary keeper.
        _domgrp[(r['pokemon_id'], cf(r), _gterm(r))].append(r)
    for _k, _lst in _domgrp.items():
        for _b in _lst:
            if (_b['iv_total'] or 0) == 45:
                continue                                          # hundo trophy -- never collapses
            if _domattr(_b):
                continue   # carries ANY collectible attribute (Gmax/Dmax/shiny/costume/bg/shadow) -> never a
                #            collapse victim; specials are limited by their own caps ONLY. Only attribute-empty
                #            TRUE PLAINS collapse upward (user 2026-06-10 "Same with gmax" after "collapse up
                #            not down" -- a loc-card 89% Gmax was deleting its plain-Gmax 87% siblings).
            _rb = keep.get(_b['uid_hex'])
            if not _rb or (_rb - _SOFT):
                continue                                          # not kept, or kept by a real axis -> leave it
            _mb, _ib = _domattr(_b), (_b['iv_total'] or 0)
            for _a in _lst:
                if _a['uid_hex'] == _b['uid_hex']:
                    continue
                if _a['uid_hex'] not in keep:
                    continue   # A TRANSFERRED MON IS NEVER A DOMINATOR (2026-09-02). The whole premise of the
                    #            collapse is "the richer copy is just a better version of this one, so you still
                    #            OWN the collectible" -- which is false if the richer copy is itself in the pile.
                    #            Nothing here required the dominator to be KEPT, so a shiny past the shiny cap or
                    #            a costume past the cosmetic cap could delete the user's only plain copy and then
                    #            be released alongside it: the species leaves the collection entirely. _lawcheck
                    #            already models the rule this way; the engine did not. No cascade risk -- a victim
                    #            must have an EMPTY _domattr and a dominator a NON-empty one (disjoint sets), so a
                    #            dominator can never itself be collapsed and this test is order-independent.
                    #            Rescue-only: it can only ever REMOVE a collapse, never add one.
                if _slot_exempt(_a):
                    continue   # A TROPHY IS NEVER A DOMINATOR (2026-07-25). A hundo/nundo is kept for BEING
                    #            a trophy, not as a collection copy of its variant -- so it must not erase the
                    #            user's only ordinary copy either. Same principle as _slot_exempt in the floor
                    #            pools: owning a trophy must never cost you a normal one. Found via Seismitoad
                    #            (2 owned: a 100% WITH a background deleted the ONLY plain) -- the Turtonator
                    #            complaint in a second disguise. Rescue-only: this can never add to the pile.
                _ma = _domattr(_a)
                if _ma != _mb and (_ma | _mb) == _ma and (_a['iv_total'] or 0) > _ib:   # _a strict superset + higher IV
                    # COMB-UP BEFORE COLLAPSE (2026-08-17): a plain that is redundant AT ITS OWN STAGE may still be
                    # the best candidate for a LATER stage. The comb-up pass above only sees mons BEYOND the stage
                    # cap; a #1-of-stage plain that is then collapsed here was never comb-up-checked. Found via a
                    # 93% Wailmer: collapsed into a 98% Dmax Wailmer, yet evolved it beats the kept 91% Wailord
                    # (user rule 2026-06-08: "every evolvable transfer candidate is comb-up-checked"). Same test
                    # and same bar-raising commit as the comb-up pass; RESCUE-ONLY -- can never add to the pile.
                    if _evo_ok(_b):
                        _collapsing.add(_b['uid_hex'])       # its alternative is the pile: judge the slot as a rescue
                        _tg, _tg_blk = _gender_split_targets(_b, allreach_sp.get(_sid(_b), set()))
                        if _tg_blk and any(_earns_slot(t, _b) for t in sorted(_tg_blk)):
                            break   # would only have been rescued by a gender-unreachable stage -- don't
                            #         collapse it either (rescue-only: never adds to the pile)
                        _pt = _promise_targets(_b, _tg)
                        if _pt:
                            _spend(_b, _pt)
                            _promises[_b['uid_hex']] = list(_pt)
                            del keep[_b['uid_hex']]                # drop the soft at-stage reason ...
                            mark(_b['uid_hex'], f"evolve_{_steps(_sid(_b), _pt[0])}")   # ... hold it to EVOLVE
                            for t in _pt:
                                _commit(t, _b)
                            break
                        if _b['uid_hex'] in _earned_unpaid:
                            # EARNED A LATER-STAGE SLOT, CANNOT PAY TODAY -> HOLD, exactly as the comb-up loop does
                            # (2026-09-23). This path only ever deleted: a plain Litwick 24% made redundant by a 33%
                            # shiny Litwick earned an open Chandelure slot, was one Unova Stone short, and went to
                            # the pile -- the HOLD rule lived in the main loop and never reached here.
                            break                                  # keep its at-stage reason; no Evolve label
                    del keep[_b['uid_hex']]                        # redundant -> falls to Transfer
                    break

    # POOLED COMB-UP (every-line pools; user 2026-09-26 "Just remember we have to comb up"). A line keeps its 2 best
    # plain copies at ANY stage; a kept pre-evo is advised to evolve when that would give the line a better copy of its
    # final than any it already keeps (or its first) -- the better copy climbs, the weaker finals already went to the
    # pile. Never a pointless evolve (a pre-evo under a better final stays put), never before a branch (Eevee: which
    # final?), never out of its pool (a Paldean Wooper -> Clodsire changes look), never a collectible / trophy / own-stage
    # PvP asset (the same exclusions the per-stage comb-up uses), and only when the family can pay for it.
    if keep_config.line_pool_all():
        _REGS = ('_alolan', '_galarian', '_hisuian', '_paldean')
        _pbar = {}                                            # target -> best IV already promised there (raise the bar)
        for _pk, _members in sorted(_pool_rows.items(), key=lambda kv: str(kv[0])):
            if not str(_pk[0][1]).startswith('line:'):
                continue                                          # a Vivillon pattern pool keeps its own advisory
            _kept = [m for m in _members if m['uid_hex'] in keep]
            for r in sorted(_kept, key=lambda m: (-(m['iv_total'] or 0), -(m['cp'] or 0), m['uid_hex'])):
                _kr = keep.get(r['uid_hex'], set())
                if 'variant_floor' not in _kr or any(x.startswith('evolve_') for x in _kr):
                    continue
                if not _can_evo(r) or (r['iv_total'] or 0) in (0, 45) or r['pokemon_id'] in keep_config.protected_pids():
                    continue
                _ubg = _pvp_usable(r, 'gl') if 'pvp_best_gl' in _kr else None
                _ubu = _pvp_usable(r, 'ul') if 'pvp_best_ul' in _kr else None
                if ((_kr & {'location_card', 'xxl', 'legacy', 'mighty', 'protected', 'dex_only_copy'})
                        or (r['gl_stage'] == _sid(r) and (r['gl_rank'] or 99) <= READY_RANK and _viable(r['gl_stage'], GL_CAP))
                        or (r['ul_stage'] == _sid(r) and (r['ul_rank'] or 99) <= READY_RANK and _viable(r['ul_stage'], UL_CAP))
                        or ('pvp_best_gl' in _kr and (_ubg is None or _ubg[2] == _sid(r)))
                        or ('pvp_best_ul' in _kr and (_ubu is None or _ubu[2] == _sid(r)))):
                    continue
                _fins = sorted(t for t in allreach_sp.get(_sid(r), ()) if not is_pre_sp.get(t)
                               and pattern_pools.line_root(t) == _pk[0][1][len('line:'):])
                if len(_fins) != 1:
                    continue                                      # a branch ahead, or no final in this line
                _t = _fins[0]
                if _pk[1] != 'Normal' and not _t.endswith(_REGS):
                    continue                                      # a regional look whose final is not regional: leaves the pool
                _best_fin = max(((m['iv_total'] or 0) for m in rows if _sid(m) == _t and m['uid_hex'] in keep), default=None)
                _best_fin = max(x for x in (_best_fin, _pbar.get(_t)) if x is not None) if (_best_fin is not None or _t in _pbar) else None
                if _best_fin is not None and (r['iv_total'] or 0) <= _best_fin:
                    continue                                      # the line already keeps a final this good: pointless
                if not _afford(r, [_t]):
                    _candy_short.append(r)
                    continue
                _spend(r, [_t])
                _promises[r['uid_hex']] = [_t]
                _pbar[_t] = max(_pbar.get(_t, 0), r['iv_total'] or 0)
                mark(r['uid_hex'], f"evolve_{_steps(_sid(r), _t)}")
    try:                                                          # held back for candy -> ladder report (2026-09-17)
        _cs = {r['uid_hex']: r for r in _candy_short if not any(x.startswith('evolve_') for x in keep.get(r['uid_hex'], ()))}
        json.dump([{'uid': u, 'species': r['species_name'], 'iv': r['iv_total'], 'family': evolvable_forms.family(_sid(r)),
                    'candy_left': (_candy_left or {}).get(evolvable_forms.family(_sid(r)))} for u, r in _cs.items()],
                  open(os.path.join(ROOT, 'system', 'analysis', 'candy_short.json'), 'w'))
        json.dump({u: t for u, t in _promises.items() if any(x.startswith('evolve_') for x in keep.get(u, ()))},
                  open(os.path.join(ROOT, 'system', 'analysis', 'promises.json'), 'w'))
        # THE UNPAID HOLDS THAT COMMIT A SLOT (2026-09-29): _evocheck replays them as earmarked copies, or it would read
        # their later-stage slots as open and call every piled surplus copy an upgrade.
        json.dump(sorted(u for u in _unpaid_committed if u in keep),
                  open(os.path.join(ROOT, 'system', 'analysis', 'unpaid_holds.json'), 'w'))
        _by_uid = {r['uid_hex']: r for r in rows}                  # held for an ITEM he does not hold (2026-09-17)
        json.dump([{'uid': u, 'species': _by_uid[u]['species_name'], 'iv': _by_uid[u]['iv_total'],
                    'item': it, 'item_name': evolvable_forms.item_name(it),
                    'have': (_items_left or {}).get(evolvable_forms._item_key(it), 0)}
                   for u, it in _item_short.items()
                   if u in _by_uid and not any(x.startswith('evolve_') for x in keep.get(u, ()))],
                  open(os.path.join(ROOT, 'system', 'analysis', 'item_short.json'), 'w'))
        json.dump(list(_shiny_gated.values()),
                  open(os.path.join(ROOT, 'system', 'analysis', 'shiny_gated.json'), 'w'))
    except Exception as _e:
        print('candy_short export skipped:', _e)
    # PvP COMB-UP LABELS (user 2026-09-24: "yes" -- split them like the regular comb-ups). Every 15e pick stays KEPT;
    # only its LABEL follows what he can do today, from the SAME candy / item budget the Evolve labels just drew on (two
    # labels never count the same candy): 'now' -> Evo Best GL / UL; 'gated' (the game gates the stage: a task, a buddy
    # walk, a time of day, or an item he holds) -> Evo Best Gated; 'hold' (short on candy, or the item is missing) -> no
    # evolve tag until he can. Best rank first. Read by build_tagsets and the audits; missing -> labels as before.
    _cul_path = os.path.join(ROOT, 'system', 'analysis', 'pvp_combup_labels.json')
    try:
        if os.path.exists(_cul_path):
            os.remove(_cul_path)                                   # never let a stale file label this pass
        _rowby = {r['uid_hex']: r for r in rows}
        _cul = {}
        for _rk, _lg, _u, _st in sorted((rk, lg, u, st) for lg in ('gl', 'ul') for u, (st, rk, _o) in _CU[lg].items()):
            if _u in _cul:                                       # one evolution serves both leagues: one decision
                _cul[_u]['leagues'].append(_lg)
                continue
            _r = _rowby[_u]
            _gate = evolvable_forms.gate_reason(_st)
            if _afford(_r, [_st]):
                _spend(_r, [_st])
                _status, _why = ('gated', ', '.join(_gate)) if _gate else ('now', '')
            else:
                _it = [k for k, n in _need_items(_r, [_st]).items()
                       if _items_left is not None and _items_left.get(evolvable_forms._item_key(k), 0) < n]
                _status = 'hold'
                _why = ('needs ' + ', '.join(evolvable_forms.item_name(k) for k in _it)) if _it else 'short on candy'
            _cul[_u] = {'leagues': [_lg], 'target': _st, 'rank': _rk, 'status': _status, 'why': _why}
        json.dump(_cul, open(_cul_path, 'w'), indent=0)
    except Exception as _e:
        print('pvp comb-up labels skipped:', _e)
    # ---- KEEP / TRANSFER ----
    allu = {r['uid_hex'] for r in rows}
    keepu = set(keep)
    transu = allu - keepu
    name = {r['uid_hex']: r['species_name'] for r in rows}
    cull = {r['uid_hex']: r['cull_decision_v9'] for r in rows}

    # HARD INVARIANT TRIPWIRE (user 2026-06-05): a top-READY_RANK CP-viable PvP spread must NEVER be in the
    # Transfer pile. Rule 15b keeps them all, so this can only fire if that rule is ever broken -- in which
    # case ABORT rather than emit a pile that could get a keeper released (the exact Mareep failure mode).
    rowmap = {r['uid_hex']: r for r in rows}
    # Same test rule 15b keeps by -- _pvp_asset() -- or the tripwire fires on mons the rule deliberately does not
    # keep and the cull can never finish (it did exactly that on the cp1914 Magmar, 2026-09-19).
    leak = [u for u in transu if _pvp_asset(rowmap[u])]
    if leak:
        ex = [(rowmap[u]['species_name'], rowmap[u]['gl_rank'], rowmap[u]['ul_rank']) for u in leak[:10]]
        raise SystemExit(f"ABORT keep_policy: {len(leak)} rank<=READY_RANK viable PvP spread(s) leaked into Transfer -- {ex}")
    # rule 15d's own tripwire: the SAME function the rule used, recomputed on the final bag (2026-09-23) -- so it
    # judges the USABLE-ONLY winners (GL/UL) exactly as the rule did; it can never disagree with the rule by design.
    _pbw = _pvp_best_winners()
    _pbleak = [u for u in transu if u in _pbw]
    if _pbleak:
        raise SystemExit(f"ABORT keep_policy: {len(_pbleak)} Best GL/UL/ML copy(ies) leaked into Transfer -- "
                         f"{[rowmap[u]['species_name'] for u in _pbleak[:10]]}")

    # Keeper tripwire (user 2026-06-06): a HUNDO (iv 45) or NUNDO (iv 0) is kept by its own keep-all rule and
    # must NEVER reach Transfer -- presence = a rule regression -> ABORT. Costumes are capped per-costume by
    # rule 1a (COSMETIC_CAP, top-4), so excess costumes in Transfer is EXPECTED and is NOT flagged here.
    def _kpr(r):
        if (r['iv_total'] or 0) == 45: return 'HUNDO'
        if (r['iv_total'] or 0) == 0 and keep_config.rule_enabled('nundo') and r['uid_hex'] in _NUNDO_KEEP:
            return 'NUNDO'   # the CHOSEN nundo of its look must never leak; its duplicates may (one per look, 2026-09-17)
        return None
    kleak = [(u, _kpr(rowmap[u])) for u in transu if _kpr(rowmap[u])]
    if kleak:
        raise SystemExit(f"ABORT keep_policy: {len(kleak)} protected mon(s) leaked into Transfer -- "
                         f"{[(rowmap[u]['species_name'], why) for u, why in kleak[:10]]}")

    # ATOMIC writes (tmp + os.replace): readers (dashboard snapshot, api_search, studio_data) poll these
    # files continuously; a truncate-then-write window let them catch a torn/empty file -> kept=0 flash +
    # nonsense diffs. os.replace is atomic on the same filesystem, so a reader sees the whole old or whole
    # new file, never a partial one (audit F24). Same content/format as before -- pure durability change.
    _pile_path = os.path.join(TD, '6_Transfer.txt')
    with open(_pile_path + '.tmp', 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(transu)))
    os.replace(_pile_path + '.tmp', _pile_path)
    _pol_path = os.path.join(ROOT, 'system', 'analysis', 'policy_reasons.json')
    with open(_pol_path + '.tmp', 'w') as _prf:
        # sort_keys: `keep` is populated in set-iteration order, so the SAME reason map used to serialize
        # with a different key order every run (PYTHONHASHSEED) -- every poll looked like a change to the
        # readers that diff this file. Content was always identical; now the bytes are too.
        json.dump({u: sorted(rs) for u, rs in keep.items()}, _prf, indent=0, sort_keys=True)
    os.replace(_pol_path + '.tmp', _pol_path)

    # ---- PILE PROVENANCE STAMP (2026-09-02) -------------------------------------------------------
    # WRITER SIDE of the cross-package stale-pile check. The pile on disk is just a list of uids: nothing
    # in it records WHICH config or WHICH database produced it, so an edited cap (or a fresh recrawl)
    # leaves a pile that still looks current to every consumer. Live state when this was written:
    # keep_config.json 01:59 > policy_reasons.json 01:58 > 6_Transfer.txt 01:39 -- the on-disk pile
    # PREDATED the config, and `full_audit --audits-only` was reporting a shadow-cap FAILURE purely from
    # that skew. This stamp is the fact those consumers need.
    #
    # CONTRACT -- system/analysis/pile_provenance.json, consumed by preflight_transfer (PKG-GATE),
    # full_audit / the four audits (PKG-AUDITS) and the dashboard's pile_stale badge (PKG-INFRA):
    #   schema           int   -- bump if any key below changes meaning
    #   config_sha256    str   -- keep_config.fingerprint(): sha256 of the merged config, '_note' excluded
    #   pile_sha256      str   -- sha256 of the pile file's exact bytes (catches a torn/half-written pair)
    #   pile_count       int   -- uids in the pile
    #   db_path/db_mtime/db_size/in_bag  -- the pokemon.db this pile was computed from
    #   db_content_sha256 str -- keep_policy.db_content_sha256(): sha256 of the CONTENT of every in_bag=1
    #                            row (all columns, rows by uid_hex, columns by sorted NAME, values
    #                            repr()'d, joined by chr(0x1f)). Computed from the SAME connection and the
    #                            SAME row objects the engine judged, so it cannot describe a different
    #                            snapshot than the one that produced this pile. db_mtime/db_size STAY
    #                            (older provenance files have no content hash and consumers fall back
    #                            to them), but they are the WEAK signal: a WAL checkpoint rewrites the
    #                            db file, so mtime moves when no row did (measured: a zero-value write
    #                            bumped mtime with size unchanged). Prefer this key.
    #   form_enum        obj   -- costume_forms.enum_stamp(): path/mtime/entries/max_known_form + gm_layer (2026-09-30: which rung
    #                            of the game-master costume ladder answered: game_master | stale_cache | none, and the flag counts)
    #   engine_sha256    str   -- _engine_sha() below: the keep code AND the files that decide costumes; audit_cull.py recomputes it
    #   generated        str   -- local time, human-readable only; NEVER compare piles by timestamp
    # A consumer is stale iff its own recompute of config_sha256 differs, the pile file's hash differs,
    # or the db mtime/size/in_bag differ. A MISSING stamp must be treated as STALE, never as "fine":
    # keep_policy aborts before writing anything when an input is bad, which deliberately leaves the
    # previous pile on disk with the previous (now mismatching) stamp.
    try:
        import hashlib as _hl

        def _engine_sha():
            """sha256 over the modules that decide the pile, in a fixed order. Missing file -> None, which
            downstream reads as 'cannot say', never as 'matches'. cpm_table.py (every CP and viability),
            form_overrides_complete.py (pvid -> which base stats and which PvP identity) and pvpoke_gamemaster.json
            (base stats, evolution edges, viability) decide the pile as surely as the code does (added 2026-09-23);
            so do costume_forms.py, form_enum.json and gamemaster_pokeminers.json, which decide what a COSTUME is (added
            2026-09-30: a classifier, enum or game-master change moves the costume ladders, yet an old pile still read as
            fresh to `full_audit.py --audits-only`); audit_cull.py recomputes this exact list and order."""
            _h = _hl.sha256()
            for _rel in ('system/scripts/keep_policy.py', 'system/scripts/build_tagsets.py',
                         'pvp_iv_rule.py', 'evolvable_forms.py', 'system/scripts/rank_cache.py',
                         'cpm_table.py', 'form_overrides_complete.py', 'pvpoke_gamemaster.json', 'size_line.py',
                         'costume_forms.py', 'form_enum.json', 'gamemaster_pokeminers.json'):
                try:
                    _h.update(open(os.path.join(ROOT, _rel), 'rb').read())
                except OSError:
                    return None
            return _h.hexdigest()

        _pile_bytes = open(_pile_path, 'rb').read()
        try:
            _dbst = os.stat(DB)
            _dbm, _dbs = _dbst.st_mtime, _dbst.st_size
        except OSError:
            _dbm = _dbs = None
        _prov = {
            'schema': 1,
            'generated': __import__('time').strftime('%Y-%m-%d %H:%M:%S'),
            'config_sha256': getattr(keep_config, 'fingerprint', lambda: None)(),
            'pile_sha256': _hl.sha256(_pile_bytes).hexdigest(),
            'pile_count': len(transu),
            'db_path': DB, 'db_mtime': _dbm, 'db_size': _dbs, 'in_bag': len(allu) + len(_fused),
            'db_content_sha256': _db_content_sha,   # content, not filesystem metadata -- see the contract above
            'form_enum': getattr(costume_forms, 'enum_stamp', lambda: None)(),
            # THE ENGINE ITSELF (2026-09-20). Every other field pins an INPUT -- the config, the bag, the form
            # enum -- so a consumer could prove the pile was built from the same data. Nothing pinned the CODE
            # that turned that data into a pile. Edit a keep rule, then run `full_audit.py --audits-only`, and
            # the audits happily re-derive the OLD pile with the NEW engine and report all-green: the one
            # combination that is guaranteed to disagree is the one nothing checked. (--audits-only does not
            # rebuild the pile, which is exactly why it must be able to tell that the pile is a version behind.)
            'engine_sha256': _engine_sha(),
        }
        _prov_path = os.path.join(ROOT, 'system', 'analysis', 'pile_provenance.json')
        with open(_prov_path + '.tmp', 'w', encoding='utf-8') as _pf:
            json.dump(_prov, _pf, indent=1, sort_keys=True)
        os.replace(_prov_path + '.tmp', _prov_path)
    except Exception as _pe:
        # Never let stamping break the run -- but say so, because a missing stamp reads as STALE downstream.
        print('[WARN] pile provenance stamp NOT written (%s) -- consumers will treat the pile as stale' % _pe,
              flush=True)

    print(f"in_bag={len(allu) + len(_fused)}  KEEP={len(keepu)}  TRANSFER={len(transu)}"
          + (f"  (fused {len(_fused)})" if _fused else ""))
    rc = defaultdict(int)
    for rs in keep.values():
        for why in rs: rc[why] += 1
    print("per-rule protects:", dict(sorted(rc.items(), key=lambda x: -x[1])))
    newly_trim = [u for u in transu if cull.get(u) == 'KEEP']
    newly_keep = [u for u in keepu if cull.get(u) == 'TRANSFER']
    print(f"newly_trimmed (was cull KEEP): {len(newly_trim)}   newly_kept (was cull TRANSFER): {len(newly_keep)}")
    sp = defaultdict(int)
    for u in transu: sp[name.get(u, '?')] += 1
    # name tiebreak: `transu` is a SET, so ties used to be ordered by string-hash (PYTHONHASHSEED) and the
    # printed list shuffled between two runs of an IDENTICAL pile -- which reads as "the pile changed".
    print("top transfer species:", dict(sorted(sp.items(), key=lambda x: (-x[1], x[0]))[:15]))


if __name__ == '__main__':
    main()
