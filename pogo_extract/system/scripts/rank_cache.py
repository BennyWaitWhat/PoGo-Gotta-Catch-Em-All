"""Faster, caching reimplementation of compute_all_ranks.py (GL/UL/LL IV-spread ranker).

Computes GL/UL/LL ranks for ALL in-bag pokemon and stores the best rank across the
evolution chain. Output is byte-identical to compute_all_ranks.py: same UPDATE columns,
same values (ll/gl/ul _rank, _pct, _stage, _chain_ranks).

==============================================================================
WHY THERE IS NO PER-MON SKIP (owner hard constraint, non-negotiable)
==============================================================================
compute_ranks() RE-READS and RE-EVALUATES EVERY in_bag=1 row on EVERY call. There is
deliberately NO diff/hash/skip column and NO incremental gating on the per-mon loop.
Two independent reasons make per-mon skipping unsafe:

  1. POWER-UP CP TIEBREAK. Powering up a mon changes its CP. Downstream keep/transfer
     logic uses CP as a tiebreak; a CP change can flip a keep<->transfer decision even
     when IVs (and therefore the rank itself) are unchanged. The ranker must re-emit a
     fresh row for every mon so the rest of the pipeline sees current state.
  2. GAME UPDATES. A game update can change base stats / forms / moves / evolution
     chains. A mon that was untouched in-game can still rank differently after such an
     update. Skipping it on a "unchanged" heuristic would silently serve stale ranks.

Speed therefore comes ONLY from caching the per-SPECIES, game-data-derived math -- the
4096-combo IV stat-product tables. Those tables are a PURE FUNCTION of base stats + the
CPM list + MAX_LEVEL_IDX, so they change ONLY when pvpoke_gamemaster.json (or the CPM
list / level cap) changes. Every mon is still looked up against the cached tables on
every run; nothing about a mon's evaluation is skipped.

==============================================================================
CHANGES vs compute_all_ranks.py (all behavior-preserving)
==============================================================================
  (1) Per-(speciesId, cap, shadow) sorted stat-product tables are pickled to
      rank_tables.pkl. The pickle is keyed/invalidated by a content hash of
      (pvpoke_gamemaster.json bytes + repr(CPM) + MAX_LEVEL_IDX). On a cache hit the
      tables are loaded instead of rebuilt; on a miss (or hash mismatch) they are
      rebuilt and re-pickled. Tables are stored lazily per requested key, exactly as
      the original ranking_cache populated them on demand.
  (2) find_max_idx replaces the ~99-level linear scan with a binary search. compute_cp
      is monotonically non-decreasing in CPM (CPM strictly increasing; CP is a product
      of increasing positive terms), so the largest index i in [0, MAX_LEVEL_IDX] with
      cp(CPM[i]) <= cap is found by bisection. Verified zero mismatches vs the linear
      scan over 983040 (species x 4096 IV x cap x shadow) cases.
  (3) sorted_sp.index(target_sp) is replaced by bisect_left on the negated (ascending)
      copy of the sorted-desc array. For a descending array with duplicate stat-products
      (~530 collisions per species are typical), .index() returns the LEFTMOST position
      of the value; bisect_left on the negated array reproduces that leftmost index
      exactly (verified zero mismatches, including the zero-stat-product sentinel).

compute_ranks(conn, gm=None) is exposed for programmatic use and processes ALL in_bag=1
rows every call. The __main__ block mirrors compute_all_ranks.py so this file is
drop-in: `python rank_cache.py` produces the same DB mutations and console output.
"""
import json, sqlite3, math, time, os, sys, pickle, hashlib, bisect, operator

# rank_cache.py lives in <project>/system/scripts/. compute_all_ranks.py reads its data
# files (pvpoke_gamemaster.json, pokemon.db, form_overrides_complete.py) relative to the
# CURRENT WORKING DIRECTORY, which is the project root. To stay drop-in we must resolve
# the SAME files. We anchor to the project root (three levels up) and put it on sys.path
# so `from form_overrides_complete import FORM_OVERRIDES` resolves identically, while
# still honoring an explicit cwd if the user runs from the project root.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, '..', '..'))


def _resolve(fname):
    """Resolve a data file: prefer one in the cwd (matches original behavior when run
    from the project root), else fall back to the project root next to compute_all_ranks.py."""
    if os.path.exists(fname):
        return fname
    cand = os.path.join(_PROJECT_ROOT, fname)
    if os.path.exists(cand):
        return cand
    return fname  # let the open() fail with the original-looking relative name


# Make form_overrides_complete importable regardless of cwd.
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from form_overrides_complete import FORM_OVERRIDES

# MAX_LEVEL_IDX + the CPM table + the league CP caps come from cpm_table.py, the SINGLE
# SOURCE OF TRUTH (defect D4: this file's CPM[98] and pvp_iv_rule.py's CPM50 were two
# different values for one number). cpm_list() hands back a MUTABLE COPY, so a caller that
# temporarily patches rank_cache.CPM (regress_pvp_keepers.py's D4 guard does exactly that,
# then restores it) cannot corrupt the canonical table for anything else in the process.
# DO NOT paste a literal table back in here -- import it.
from cpm_table import MAX_LEVEL_IDX, LL_CAP, GL_CAP, UL_CAP, ML_CAP, cpm_list
import evolvable_forms

CPM = cpm_list()

# Cache file lives next to this module (in system/scripts/), not in the project root, so
# it does not collide with the project's many top-level artifacts.
RANK_TABLES_PKL = os.path.join(_SCRIPT_DIR, 'rank_tables.pkl')

# FORM_OVERRIDES imported from form_overrides_complete.py (160 entries, all 1400 forms covered)


def to_pvpoke_id(species_name, form_code, costume=0):
    if (species_name, form_code) in FORM_OVERRIDES:
        return FORM_OVERRIDES[(species_name, form_code)]
    base = species_name.lower().replace(' ', '_').replace("'", '').replace('.', '').replace('-', '_').replace('é', 'e')
    return base


def compute_cp(ba, bd, bs, ia, idf, ista, cpm, shadow=False):
    # CP is shadow-INDEPENDENT: a shadow's CP equals its non-shadow CP at the same
    # level/IVs (the 1.2x/0.833x shadow boost is COMBAT-ONLY). The `shadow` arg is kept
    # for signature compat but must NOT touch CP -- applying it caps shadows at the wrong
    # level and wrecks high-attack shadow IV-ranks (verified vs PvPoke 2026-05-29:
    # 14/14/12 shadow Venusaur GL #3378 buggy -> #1048 fixed = PvPoke #1052).
    return max(10, int((ba+ia)*cpm * math.sqrt((bd+idf)*cpm) * math.sqrt((bs+ista)*cpm) / 10))


def stat_product(ba, bd, bs, ia, idf, ista, cpm, shadow=False):
    am = 1.2 if shadow else 1.0; dm = 5/6 if shadow else 1.0
    return (ba+ia)*cpm*am * (bd+idf)*cpm*dm * math.floor((bs+ista)*cpm)


def find_max_idx(ba, bd, bs, ia, idf, ista, cap, shadow=False):
    """Largest index i in [0, MAX_LEVEL_IDX] with compute_cp(CPM[i]) <= cap, else -1.

    Behavior-identical to the original descending linear scan:

        for i in range(MAX_LEVEL_IDX, -1, -1):
            if compute_cp(..., CPM[i], ...) <= cap: return i
        return -1

    compute_cp is monotonically non-decreasing in i (CPM strictly increasing; CP is a
    product of increasing positive terms), so we binary-search the True->False boundary
    of the predicate (cp <= cap) instead of scanning ~99 levels. Verified zero mismatches
    vs the linear scan over all species x 4096 IVs x {500,1500,2500} x {shadow,normal}.
    """
    # If even the lowest level already exceeds the cap, no level qualifies.
    if compute_cp(ba, bd, bs, ia, idf, ista, CPM[0], shadow) > cap:
        return -1
    lo, hi = 0, MAX_LEVEL_IDX
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if compute_cp(ba, bd, bs, ia, idf, ista, CPM[mid], shadow) <= cap:
            lo = mid
        else:
            hi = mid - 1
    return lo


def all_combos_sorted(ba, bd, bs, cap, shadow=False):
    """Return (sps, sorted_sp): the 4096 stat products in IV order and sorted desc."""
    sps = []
    for a in range(16):
        for de in range(16):
            for s in range(16):
                idx = find_max_idx(ba, bd, bs, a, de, s, cap, shadow)
                if idx >= 0:
                    cpm = CPM[idx] if idx <= MAX_LEVEL_IDX else CPM[MAX_LEVEL_IDX]
                    sps.append(stat_product(ba, bd, bs, a, de, s, cpm, shadow))
                else:
                    sps.append(0)
    sorted_sp = sorted(sps, reverse=True)
    return sps, sorted_sp


def _content_hash(gm_bytes):
    """Invalidation key: gamemaster bytes + the CPM list + MAX_LEVEL_IDX.

    The stat-product tables are a pure function of these three inputs, so any change to
    them must rebuild the cache. (gm_bytes are the exact on-disk pvpoke_gamemaster.json
    bytes; repr(CPM) and MAX_LEVEL_IDX capture the two constants the math also depends on.)
    """
    h = hashlib.sha256()
    h.update(b'rankmath-v2-shadow-cp-fix')   # BUMP on any change to the ranking MATH
    # ...and the math's own SOURCE (H02, 2026-09-29): a fix to these four functions invalidates the tables by itself;
    # a forgotten bump above no longer serves the old numbers to the pipeline AND to audit_rank_tags.
    import inspect
    for _fn in (compute_cp, stat_product, find_max_idx, all_combos_sorted):
        h.update(inspect.getsource(_fn).encode('utf-8'))
    h.update(gm_bytes)                         # (compute_cp/stat_product/find_max_idx) so
    h.update(repr(CPM).encode('utf-8'))        # stale cached tables can never survive a fix.
    h.update(str(MAX_LEVEL_IDX).encode('utf-8'))
    return h.hexdigest()


class RankTableCache:
    """Lazily-populated, disk-backed cache of per-(species_id, cap, shadow) tables.

    Mirrors the original module-level `ranking_cache` dict + `get_rankings()` semantics
    exactly: a key maps either to None (species not in gamemaster) or to (sps, sorted_sp,
    base_stats). The only addition is persistence: the in-memory dict is loaded from /
    saved to rank_tables.pkl, guarded by a content hash so stale tables are never used.

    compute_rank_for_iv bisects sorted_sp with a negating key, so a lookup stays O(log n) per mon.
    """

    def __init__(self, pokemon_db, content_hash, pkl_path=RANK_TABLES_PKL):
        self.pokemon_db = pokemon_db
        self.content_hash = content_hash
        self.pkl_path = pkl_path
        # tables: key -> None | (sps, sorted_sp, base_stats)
        self.tables = {}
        self._dirty = False
        self._load()

    def _load(self):
        if not os.path.exists(self.pkl_path):
            return
        try:
            with open(self.pkl_path, 'rb') as f:
                blob = pickle.load(f)
        except Exception:
            # Corrupt / unreadable cache -> rebuild from scratch.
            return
        if not isinstance(blob, dict) or blob.get('content_hash') != self.content_hash:
            # Gamemaster / CPM / level cap changed -> invalidate.
            return
        cached = blob.get('tables')
        if isinstance(cached, dict):
            self.tables = cached

    def save(self):
        if not self._dirty:
            return
        blob = {'content_hash': self.content_hash, 'tables': self.tables}
        tmp = self.pkl_path + '.tmp'
        with open(tmp, 'wb') as f:
            pickle.dump(blob, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, self.pkl_path)
        self._dirty = False

    def get(self, species_id, cap, shadow):
        key = (species_id, cap, shadow)
        if key in self.tables:
            return self.tables[key]
        p = self.pokemon_db.get(species_id)
        if not p:
            self.tables[key] = None
            self._dirty = True
            return None
        bs = p['baseStats']
        sps, sorted_sp = all_combos_sorted(bs['atk'], bs['def'], bs['hp'], cap, shadow)
        self.tables[key] = (sps, sorted_sp, bs)
        self._dirty = True
        return self.tables[key]


def compute_rank_for_iv(cache, species_id, ia, idf, ista, cap, shadow):
    """Identical result to the original compute_rank_for_iv, using cached tables + bisect.

    Returns None when the species is unknown or the target stat product is 0 (out of cap),
    else {'rank', 'pct', 'sp'} with rank = leftmost 1-based position in the desc array.
    """
    r = cache.get(species_id, cap, shadow)
    if r is None:
        return None
    sps, sorted_sp, bs = r
    iv_idx = ia*256 + idf*16 + ista
    target_sp = sps[iv_idx]
    if target_sp == 0:
        return None
    # Original: rank = sorted_sp.index(target_sp) + 1  (leftmost match, O(n))
    # Behavior-preserving O(log n): sorted_sp is descending, so under key=neg it is ascending and bisect_left finds the
    # leftmost -target_sp -- the same index the memoized negated copy gave, without building one per table (2026-10-29:
    # that copy was 1 s of every walk's rank step)
    rank = bisect.bisect_left(sorted_sp, -target_sp, key=operator.neg) + 1
    pct = target_sp / sorted_sp[0] * 100 if sorted_sp[0] else 0
    return {'rank': rank, 'pct': pct, 'sp': target_sp}


def _table(args):
    return all_combos_sorted(*args)


def prefill(cache, keys, workers=8):
    """Build every missing table of `keys` in worker processes: the same all_combos_sorted, so each one is exactly what
    get() would build on first use (2026-10-29: audit_rank_tags' ~360 fresh tables took ~7 s on one core)."""
    todo = [k for k in dict.fromkeys(keys) if k not in cache.tables and cache.pokemon_db.get(k[0])]
    if len(todo) < 2 * workers:
        return
    from concurrent.futures import ProcessPoolExecutor
    args = [(b['atk'], b['def'], b['hp'], cap, shadow)
            for sid, cap, shadow in todo for b in (cache.pokemon_db[sid]['baseStats'],)]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for k, (sps, sorted_sp) in zip(todo, ex.map(_table, args, chunksize=4)):
            cache.tables[k] = (sps, sorted_sp, cache.pokemon_db[k[0]]['baseStats'])
    cache._dirty = True



def _viability_margin():
    try:
        import keep_config
        return int(keep_config.pvp('viability_margin') or 0)
    except Exception:
        return 0


def _stage_viable(cache, species_id, cap, shadow):
    """True iff this stage can REACH the league cap: its 15/15/15 spread exceeds cap+margin before max level.

    2026-09-08: the chain's "best" rank used to be the lowest rank across ALL stages, viability-blind. A stage
    that never reaches the cap ranks its spreads by raw IV (a hundo is always #1 there), so a Dottler 15/15/15
    stored stage=dottler #1 (max CP 1,164) and MASKED its legitimate Orbeetle UL #3 (max CP 2,513) -- every
    consumer then saw a non-viable stage and gave the mon no PvP protection. Prefer viable stages."""
    r = cache.get(species_id, cap, shadow)
    if r is None:
        return False
    _sps, _sorted, bs = r                # bs is the gamemaster baseStats dict {'atk','def','hp'}
    ba, bd, bst = bs['atk'], bs['def'], bs['hp']
    idx = find_max_idx(ba, bd, bst, 15, 15, 15, cap + _viability_margin(), shadow)
    return idx < MAX_LEVEL_IDX          # the hundo breaches cap+margin before max level => species reaches the cap


def get_evolutions(pokemon_db, species_id, _seen=None):
    """The chain from `species_id` down, itself first.

    `_seen` is a CYCLE GUARD, not an optimisation (2026-09-20). The old `if evo not in chain` test only saw the
    chain being built at this level, so a mutual pair -- pvpoke records poltchageist's evolution backwards, as
    sinistcha -> poltchageist, and the game's real poltchageist -> sinistcha completes the loop -- recursed until
    the stack died and killed the pipeline before the cull ever ran. Bad upstream data must degrade, not crash."""
    p = pokemon_db.get(species_id)
    if not p:
        return [species_id]
    _seen = (_seen or set()) | {species_id}
    chain = [species_id]
    fam = p.get('family', {})
    for evo in fam.get('evolutions', []):
        if evo not in chain and evo not in _seen:
            chain.append(evo)
            for s in get_evolutions(pokemon_db, evo, _seen)[1:]:
                if s not in chain:
                    chain.append(s)
    return chain


def _reachable(pokemon_db, chain, form, fresh_form, pid, gender, costume=0):
    """The stages THIS specimen can actually reach -- chain[0] is its own stage, the rest are later ones.

    Ranking a mon as a stage it can never become invents a PvP asset out of nothing: a CaterpieGofest2026 was ranked
    Butterfree GL #3 and kept for it (2026-09-17). Four gates, all from the client game master via evolvable_forms:
      * a FORM with no evolution branch, or a *Noevolve COSTUME (Jan2020Noevolve Eevee ...) -> its own stage only;
      * a gender-locked family (GENDER_TERMINALS) -> only its own gender's branch (a male Snorunt never Froslass);
      * a gendered-FORM evolution -> that gender's form (female Lechonk -> oinkologne_female, its own stats);
      * a TARGET the game gives this form no branch to at all -- pvpoke hands every Scyther a Kleavor and every
        Cubone an Alolan Marowak, and 20 in-bag rows were ranking one of those dead stages, so a chain-best rank
        (and the PvP keep that reads it) could come from a pokemon the specimen can never become (2026-09-20).
        Checked per FORM, never per species: a plain Rockruff really cannot reach Lycanroc-Dusk, but the Dusk
        form can, and both are the speciesId 'rockruff'.
    """
    if len(chain) < 2:
        return chain
    if evolvable_forms.row_can_evolve({'form': form, 'fresh_form': fresh_form, 'fresh_costume': costume,
                                       'pokemon_id': pid}) is False:
        return chain[:1]
    src, out = chain[0], [chain[0]]
    for t in chain[1:]:
        if pid in evolvable_forms.GENDER_TERMINALS and \
                not evolvable_forms.gender_allows(pid, gender, (pokemon_db.get(t) or {}).get('dex')):
            continue
        if evolvable_forms.can_reach(fresh_form or form, t, src, gender) is False:
            continue                      # the game gives this form no branch there (None = cannot say = keep)
        g = evolvable_forms.gendered_target(src, gender, t)
        t = g if g in pokemon_db else t
        if t not in out:
            out.append(t)
    return out


def _ensure_columns(c, conn):
    """Add the rank columns if missing (identical set/order to compute_all_ranks.py)."""
    cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
    new_cols = [
        ('ll_rank', 'INTEGER'), ('ll_pct', 'REAL'), ('ll_stage', 'TEXT'), ('ll_chain_ranks', 'TEXT'),
        ('gl_rank', 'INTEGER'), ('gl_pct', 'REAL'), ('gl_stage', 'TEXT'), ('gl_chain_ranks', 'TEXT'),
        ('ul_rank', 'INTEGER'), ('ul_pct', 'REAL'), ('ul_stage', 'TEXT'), ('ul_chain_ranks', 'TEXT'),
        ('ml_rank', 'INTEGER'), ('ml_pct', 'REAL'), ('ml_stage', 'TEXT'), ('ml_chain_ranks', 'TEXT'),
    ]
    for col, typ in new_cols:
        if col not in cols:
            c.execute(f'ALTER TABLE pokemon ADD COLUMN {col} {typ}')
    conn.commit()


def compute_ranks(conn, gm=None, verbose=True):
    """Re-read and re-evaluate EVERY in_bag=1 mon, writing GL/UL/LL ranks.

    NO per-mon skip / diff / hash gating -- see the module docstring for why (power-up CP
    tiebreak + game updates). Speed comes solely from the disk-cached per-species stat
    tables (RankTableCache). Returns (done, unknown_species) like the original's tallies.

    `gm` may be a pre-loaded gamemaster dict; if None it is read from
    pvpoke_gamemaster.json (same file the original loads). The cache hashes the exact
    gamemaster bytes, so passing a dict that was loaded from a different file than the one
    on disk would mis-key the cache; callers that pass `gm` should pass the dict parsed
    from the same pvpoke_gamemaster.json on disk (the normal case).
    """
    gm_path = _resolve('pvpoke_gamemaster.json')
    with open(gm_path, 'rb') as f:
        gm_bytes = f.read()
    if gm is None:
        gm = json.loads(gm_bytes)
    pokemon_db = {p['speciesId']: p for p in gm['pokemon']}

    content_hash = _content_hash(gm_bytes)
    cache = RankTableCache(pokemon_db, content_hash)

    c = conn.cursor()
    _ensure_columns(c, conn)

    rows = c.execute("""SELECT uid_hex, species_name, pokemon_id, form, fresh_costume,
        iv_atk, iv_def, iv_sta, fresh_alignment, fresh_form, gender FROM pokemon WHERE in_bag=1""").fetchall()
    if verbose:
        print(f'Computing ranks for {len(rows)} pokemon...')

    unknown_species = set()
    done = 0
    t0 = time.time()
    for r in rows:
        uid_hex, sp, pid, form, costume, ia, idf, ista, align, fresh_form, gender = r
        shadow = (align == 1)
        sid = to_pvpoke_id(sp, form or 0, costume or 0)
        if sid not in pokemon_db:
            # STALE RANKS ON AN UNMAPPABLE FORM (cross-package reconciliation 2026-09-02).
            # This branch used to just `continue`, which LEAVES ANY PREVIOUSLY-COMPUTED RANKS IN
            # PLACE: after an evolution or a FORM_OVERRIDES change the row keeps ranks belonging to a
            # DIFFERENT form, and every downstream PvP decision is then made from stale numbers.
            # compute_all_ranks.py:143 was fixed the same day to NULL the 12 rank columns instead --
            # but pogo_pipeline.py:1058 runs THIS file, so the fixed one is the fallback and the
            # leaking one is the live path. One axis, two models, and the model that leaks is the one
            # that feeds the irreversible pile: exactly the class this review exists to remove.
            # (The header's "byte-identical to compute_all_ranks.py" claim stopped being true the
            # moment that fix landed on one side only; this restores it.)
            # SAFE DIRECTION -- unknown is PROTECTED, not unprotected: with both ranks NULL,
            # keep_policy rule 15c marks the row 'rank_unknown' and KEEPS it, and
            # preflight_transfer raises its 'pvp_unknown' axis. Leaving stale ranks is what silently
            # removes protection, by answering a question nobody actually computed.
            unknown_species.add(f'{sp} f={form}')
            c.execute("""UPDATE pokemon SET
                ll_rank=NULL, ll_pct=NULL, ll_stage=NULL, ll_chain_ranks=NULL,
                gl_rank=NULL, gl_pct=NULL, gl_stage=NULL, gl_chain_ranks=NULL,
                ul_rank=NULL, ul_pct=NULL, ul_stage=NULL, ul_chain_ranks=NULL,
                ml_rank=NULL, ml_pct=NULL, ml_stage=NULL, ml_chain_ranks=NULL
                WHERE uid_hex=?""", (uid_hex,))
            continue
        chain = _reachable(pokemon_db, get_evolutions(pokemon_db, sid), form, fresh_form, pid, gender, costume)

        # For each league, find the BEST (lowest rank) across all stages
        best_ll = None; best_gl = None; best_ul = None; best_ml = None
        ll_chain = []; gl_chain = []; ul_chain = []; ml_chain = []
        for stage_id in chain:
            ll = compute_rank_for_iv(cache, stage_id, ia, idf, ista, LL_CAP, shadow)
            gl = compute_rank_for_iv(cache, stage_id, ia, idf, ista, GL_CAP, shadow)
            ul = compute_rank_for_iv(cache, stage_id, ia, idf, ista, UL_CAP, shadow)
            ml = compute_rank_for_iv(cache, stage_id, ia, idf, ista, ML_CAP, shadow)   # no cap: level ceiling
            # VIABILITY-AWARE best (2026-09-08): a stage that can reach the cap always beats one that cannot;
            # among equals, the lowest rank wins. Falls back to the overall lowest when NO stage is viable, so
            # the rank-NULL guard (rule 15c) keeps its meaning and chain_ranks still lists every stage.
            def _better(cand, cur, cap):
                if cur is None:
                    return True
                cv, uv = cand['viable'], cur['viable']
                return (cv and not uv) or (cv == uv and cand['rank'] < cur['rank'])
            if ll:
                ll_chain.append(f"{stage_id}:{ll['rank']}({ll['pct']:.2f}%)")
                cand = {**ll, 'stage': stage_id, 'viable': _stage_viable(cache, stage_id, LL_CAP, shadow)}
                if _better(cand, best_ll, LL_CAP): best_ll = cand
            if gl:
                gl_chain.append(f"{stage_id}:{gl['rank']}({gl['pct']:.2f}%)")
                cand = {**gl, 'stage': stage_id, 'viable': _stage_viable(cache, stage_id, GL_CAP, shadow)}
                if _better(cand, best_gl, GL_CAP): best_gl = cand
            if ul:
                ul_chain.append(f"{stage_id}:{ul['rank']}({ul['pct']:.2f}%)")
                cand = {**ul, 'stage': stage_id, 'viable': _stage_viable(cache, stage_id, UL_CAP, shadow)}
                if _better(cand, best_ul, UL_CAP): best_ul = cand
            if ml:
                ml_chain.append(f"{stage_id}:{ml['rank']}({ml['pct']:.2f}%)")
                # viability is meaningless with no cap (every stage 'reaches' it), so it is uniform here and the
                # lowest rank decides -- the same order every consumer's (viable, rank, uid) key produces.
                cand = {**ml, 'stage': stage_id, 'viable': _stage_viable(cache, stage_id, ML_CAP, shadow)}
                if _better(cand, best_ml, ML_CAP): best_ml = cand

        c.execute("""UPDATE pokemon SET
            ll_rank=?, ll_pct=?, ll_stage=?, ll_chain_ranks=?,
            gl_rank=?, gl_pct=?, gl_stage=?, gl_chain_ranks=?,
            ul_rank=?, ul_pct=?, ul_stage=?, ul_chain_ranks=?,
            ml_rank=?, ml_pct=?, ml_stage=?, ml_chain_ranks=?
            WHERE uid_hex=?""",
            (best_ll['rank'] if best_ll else None,
             best_ll['pct']  if best_ll else None,
             best_ll['stage'] if best_ll else None,
             ';'.join(ll_chain) if ll_chain else None,
             best_gl['rank'] if best_gl else None,
             best_gl['pct']  if best_gl else None,
             best_gl['stage'] if best_gl else None,
             ';'.join(gl_chain) if gl_chain else None,
             best_ul['rank'] if best_ul else None,
             best_ul['pct']  if best_ul else None,
             best_ul['stage'] if best_ul else None,
             ';'.join(ul_chain) if ul_chain else None,
             best_ml['rank'] if best_ml else None,
             best_ml['pct']  if best_ml else None,
             best_ml['stage'] if best_ml else None,
             ';'.join(ml_chain) if ml_chain else None,
             uid_hex))
        done += 1
        if verbose and done % 500 == 0:
            elapsed = time.time() - t0
            print(f'  {done}/{len(rows)}  ({elapsed:.0f}s)')

    conn.commit()
    # Persist the per-species tables we built/loaded this run for the next invocation.
    cache.save()
    return done, unknown_species


def main():
    """Drop-in mirror of compute_all_ranks.py's __main__ (same output + DB mutations)."""
    db_path = _resolve('pokemon.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    done, unknown_species = compute_ranks(conn)

    print(f'\nDone. {done} ranked.')
    print(f'Unknown species (not in PvPoke): {len(unknown_species)}')
    for u in sorted(unknown_species)[:30]:
        print(f'  {u}')
    print(f'\nQuery: SELECT * FROM pokemon WHERE gl_rank IS NOT NULL ORDER BY gl_rank LIMIT 20')

    # Stats
    n_with_gl = c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND gl_rank IS NOT NULL').fetchone()[0]
    n_top10 = c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND gl_rank<=10').fetchone()[0]
    n_top100 = c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND gl_rank<=100').fetchone()[0]
    ul_top100 = c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND ul_rank<=100').fetchone()[0]
    print(f'\nWith GL rank: {n_with_gl}')
    print(f'GL rank <=10: {n_top10}')
    print(f'GL rank <=100: {n_top100}')
    print(f'UL rank <=100: {ul_top100}')


if __name__ == '__main__':
    main()
