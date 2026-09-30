"""PROMISE AUDIT -- "make sure you dont make me evolve pokemon for no reason" (user 2026-09-17).

Every Evolve Once / Evolve Twice / Evolve Gated label is a promise: evolve this one and the evolved copy is kept -- an
engine promise, a shiny upgrade and a showcase pick alike (2026-09-29, the fold: one table, evolve_advice.json, whose
targets are trusted as promises.json's were). A PvP comb-up alone is listed, not simulated: the sandbox cannot re-rank.
This audit PROVES it instead of trusting the engine's own bookkeeping: in a SANDBOX copy of the bag it evolves EVERY
labelled mon at once (the hardest case -- any subset faces fewer arrivals), gives each its target species, form and
evolved CP, reruns the real, unmodified keep_policy there, and fails if any evolved copy lands in the pile. A line
that splits (random or chosen branch) is simulated once per branch, all such mons landing in the same branch.
It also classifies WHY each evolution is worth it at its target: new stage (no plain copy yet), open slot, or beats a
weaker copy.

SANDBOX ONLY (regress_pvp_keepers.build_sandbox / run_engine): the live db is read through a mode=ro URI, every engine
output path is repointed into a temp tree. No phone, no tags. Exit 1 on any broken promise.
"""
import collections, json, math, os, sqlite3, sys, tempfile, shutil
ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts')); sys.path.insert(0, ROOT)
import regress_pvp_keepers as rpk
import evolvable_forms, keep_config, size_line
from pvp_iv_rule import pvid
from costume_forms import is_costume_form
from cpm_table import cpm_list

CPM = cpm_list()


def main():
    # THE ADVICE TABLE (2026-09-29, the fold): every Evolve Once / Twice / Gated copy with its target(s) and producer, as
    # build_tagsets recorded it (granular_tags.evolve_advice). Trusted for the targets as promises.json was; the members
    # are the tag files the phone gets.
    import granular_tags
    try:
        adv = {format(int(u, 16), '016x'): e
               for u, e in json.load(open(granular_tags.EVOLVE_ADVICE, encoding='utf-8')).items()}
    except (OSError, ValueError) as e:
        print('  *** evolve_advice.json unreadable (%s) -- no promise can be simulated' % e)
        print('VERDICT: PROMISES UNCHECKED -- do not sync')
        return 1
    gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
    BS = {p['speciesId']: p for p in gm['pokemon']}
    enum = {int(k): v for k, v in json.load(open('form_enum.json', encoding='utf-8')).items()}
    by_norm = {evolvable_forms._norm(v): k for k, v in enum.items()}
    live = sqlite3.connect('file:pokemon.db?mode=ro', uri=True); live.row_factory = sqlite3.Row
    rows = {r['uid_hex']: __import__('keep_config').row_dict(r) for r in live.execute('SELECT * FROM pokemon WHERE in_bag=1')}
    pile_now = set(open(os.path.join('system', 'analysis', 'tagsets', '6_Transfer.txt')).read().split())
    ident = {}                                         # speciesId -> (species_name, pokemon_id, form) of a real plain row
    for r in rows.values():
        sid = pvid(r['species_name'], r['form'] or 0)
        if sid not in ident and not is_costume_form(r['form']) and not is_costume_form(r['fresh_form']):
            ident[sid] = (r['species_name'], r['pokemon_id'], r['form'] or 0)

    def identity(t):
        if t in ident:
            return ident[t]
        p = BS.get(t) or {}
        name = (p.get('speciesName') or '').split(' (')[0]
        for key in (evolvable_forms._norm(t), evolvable_forms._norm(t) + 'NORMAL'):
            f = by_norm.get(key)
            if f is not None and name and pvid(name, f) == t:
                return (name, p.get('dex'), f)
        return None

    def evolved_cp(r, t):
        b = (BS.get(t) or {}).get('baseStats') or {}
        lvl = r['level'] or 0
        i = int(round((lvl - 1) * 2))
        if not b or not (0 <= i < len(CPM)):
            return r['cp']
        c = CPM[i]
        return max(10, math.floor((b['atk'] + r['iv_atk']) * math.sqrt(b['def'] + r['iv_def'])
                                  * math.sqrt(b['hp'] + r['iv_sta']) * c * c / 10))

    # EVERY COUNT TAG IS A PROMISE (2026-09-29, the fold): an engine promise, a shiny upgrade and a showcase pick are
    # simulated alike (a shiny or XXL copy moved to its target stays kept, or the label is broken); a PvP comb-up alone is
    # not -- the sandbox keeps its pre-evolution ranks -- and is listed below.
    todo, src_of, cu_unsim = {}, {}, []
    unsim, broken, reasons_at = [], [], collections.Counter()
    for _t in (granular_tags.EVOLVE_ONCE, granular_tags.EVOLVE_TWICE, granular_tags.EVOLVE_GATED):
        _p = os.path.join('system', 'analysis', 'tagsets', granular_tags.filename(_t))
        for u in (open(_p).read().split() if os.path.exists(_p) else []):
            if u not in rows or u in src_of:
                continue                                   # released mid-sync / already seen
            r, e = rows[u], adv.get(u) or {}
            nm = '%s %d%% [%s]' % (r['species_name'], (r['iv_total'] or 0) * 100 // 45, _t)
            src_of[u] = e.get('source')
            if not e.get('targets'):
                broken.append(nm + ': no evolve advice behind it (evolve_advice.json names no target)')
            elif u in pile_now:
                broken.append(nm + ': an evolve promise on a mon tagged for Transfer')
            elif e.get('source') == 'combup':
                cu_unsim.append('%s %d%% -> %s' % (r['species_name'], (r['iv_total'] or 0) * 100 // 45, '/'.join(e['targets'])))
            else:
                todo[u] = list(e['targets'])
    # the engine's CURRENT reasons for each mon -- `reasons` below is the SANDBOX result, i.e. what the copy is
    # kept as AFTER the simulated evolution, which cannot answer "would this be released if it did not evolve".
    try:
        now_reasons = {k: set(v) for k, v in json.load(
            open(os.path.join('system', 'analysis', 'policy_reasons.json'), encoding='utf-8')).items()
            if isinstance(v, list)}
    except Exception:
        now_reasons = {}
    # (2026-09-26) fused components hold no ladder slot: a Reshiram/Zekrom held inside a Kyurem is not in the engine's
    # `rows`, so it is never promised, and it cannot be evolved while fused. A promise on one is BROKEN, never simulated.
    _fused_promised = sorted(u for u in todo if keep_config.is_fused_component(rows[u]))
    for u in _fused_promised:
        broken.append('%s %d%% -> %s: promised while FUSED (held inside a Kyurem; cannot evolve, holds no ladder slot)'
                      % (rows[u]['species_name'], (rows[u]['iv_total'] or 0) * 100 // 45, '/'.join(todo[u])))
        del todo[u]
    branches = max((len(t) for t in todo.values()), default=1)
    for b in range(branches):
        sandbox = tempfile.mkdtemp(prefix='promise_audit_')
        try:
            sb_db = rpk.build_sandbox(sandbox)
            con = sqlite3.connect(sb_db)
            moved = {}
            for u, targets in todo.items():
                r = rows[u]
                t = targets[min(b, len(targets) - 1)]
                idt = identity(t)
                # THE FORM THE GAME SAYS THIS COPY BECOMES (2026-09-24): identity(t) is one form per speciesId -- the
                # first Florges seen -- so every colour's promise was moved into that ONE pool (Yellow), and a Yellow
                # 73% was "culled after evolving" by a White 91%, a Red 91% and a Blue 96% that can never be Yellow.
                # Same lesson as the 2026-09-20 stage_key fix below, one loop earlier: a stage is (speciesId, FORM).
                if idt is not None:
                    _tf = evolvable_forms.target_form(r['fresh_form'] or r['form'], t, pvid(r['species_name'], r['form'] or 0), r['gender'])
                    _fid = by_norm.get(evolvable_forms._norm(_tf)) if _tf else None
                    if _fid is not None and pvid(idt[0], _fid) == t:
                        idt = (idt[0], idt[1], _fid)
                if idt is None or is_costume_form(r['form']) or is_costume_form(r['fresh_form']) or pvid(*idt[0:1], idt[2]) != t:
                    if b == 0:
                        unsim.append('%s %d%% -> %s' % (r['species_name'], (r['iv_total'] or 0) * 100 // 45, t))
                    continue
                con.execute('UPDATE pokemon SET species_name=?, pokemon_id=?, form=?, fresh_form=?, cp=? WHERE uid_hex=?',
                            (idt[0], idt[1], idt[2], idt[2], evolved_cp(r, t), u))
                # ...AND THE SIZE (2026-09-26): the scale carries over (size_line.project, the engine's XXL projection).
                # An XXL Happiny moved to Chansey at its Happiny height scored as a small Chansey and was "culled".
                _sz = size_line.project(r, t)
                if _sz and _sz[1] is not None:
                    con.execute('UPDATE pokemon SET height_m=?, weight_kg=? WHERE uid_hex=?', (_sz[0], _sz[1], u))
                moved[u] = t
            con.commit(); con.close()
            pile, reasons, out, err = rpk.run_engine(sandbox, sb_db)
            if err:
                print('engine aborted in the sandbox (branch %d): %s' % (b, err)); return 2
            for u, t in moved.items():
                if u in pile:
                    r = rows[u]
                    broken.append('%s %d%% -> %s: culled after evolving (branch %d)' % (r['species_name'], (r['iv_total'] or 0) * 100 // 45, t, b))
                elif reasons.get(u) and set(reasons[u]) <= {'pvp_best_gl', 'pvp_best_ul', 'pvp_best_ml'}:
                    # kept ONLY as Best GL/UL (rule 15d, 2026-09-23): the promised slot was not earned, and the moved
                    # row still carries its PRE-evolution gl/ul ranks, which the sandbox cannot trust -- not a pass.
                    r = rows[u]
                    broken.append('%s %d%% -> %s: kept only as Best GL/UL on pre-evolution ranks (branch %d)'
                                  % (r['species_name'], (r['iv_total'] or 0) * 100 // 45, t, b))
                elif b == 0:
                    reasons_at[','.join(sorted(reasons.get(u, [])))] += 1
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

    # WHY EACH EVOLUTION IS WORTH IT, judged on the LIVE bag at its first target.
    # OCCUPANCY IS THE ENGINE'S (2026-09-17): a stage's plain slots = its PER-STAGE cap -- a MIDDLE stage (can still
    # evolve AND something evolves into it) holds plain_line_preevo, a base or final stage holds plain_line -- minus
    # the slots a non-hundo shiny or cosmetic takes in the merged top-cap (keep_policy._eff_cap), and a trophy
    # (hundo / nundo while rule 8 is on) never eats one. Hand-copying the FINAL cap here called a lawful Dewott
    # promise pointless while the engine correctly had it replacing the weakest of a FULL middle stage: the
    # capped-vs-keep-all bug class, one file further out.
    import keep_policy as _kp
    _seen = {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']}
    _is_pre, _term_sp, _dist_sp, _sp2dex, _allreach = _kp.build_evo_graph(gm, _seen, with_all=True)
    _has_parent = {x for _ts in _allreach.values() for x in _ts}
    _nundo_on = keep_config.rule_enabled('nundo')

    def _plainish(r):                                       # keep_policy._truly_plain, minus shiny/shadow
        return (not r['fresh_shiny'] and r['fresh_alignment'] != 1 and not (r['fresh_costume'] or 0)
                and not (r['fresh_natural_art_bg'] or 0)
                and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
                and not evolvable_forms.max_axis(r['fresh_bread_mode'])
                and not is_costume_form(r['fresh_form']) and not is_costume_form(r['form']))

    # A STAGE IS A (speciesId, FORM), NOT A speciesId (2026-09-20). pvpoke calls every Florges colour 'florges'
    # and both Gastrodon seas 'gastrodon', so pooling by speciesId judged a FloetteRed against the Yellow and Blue
    # Florges hundos and called its evolution pointless -- it would be the first RED Florges in the bag. Every
    # bucket is filled twice: once under the bare speciesId and once under its own form, and the promise is judged
    # against the form the GAME says that specimen becomes. Falls back to the speciesId pool whenever any held copy
    # of that stage has no readable form name, so a form-0 species behaves exactly as before.
    stage_plain = collections.defaultdict(list)             # (iv, cp) of the plain copies HOLDING a slot
    stage_special = collections.defaultdict(list)           # (iv, cp) of the specials that take plain slots
    best_any = collections.defaultdict(lambda: -1)          # best plain copy per stage INCLUDING hundos
    form_names = collections.defaultdict(list)              # speciesId -> the form name of every held copy
    # THE KEY SHAPE MUST BE stage_key()'s (H08, 2026-09-29): (speciesId, form, GENDER). The fill below used the 2-tuple
    # (speciesId, form) after stage_key() gained the gender (2026-09-23), so every read missed and the worth-it test
    # saw an EMPTY stage for every promise -- "new stage" -- whatever the bag held there. The gender of a HELD copy is
    # its own look at its own stage: evolvable_forms.gender_key(its dex, its gender).
    _DEX_OF0 = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
    for r in rows.values():
        if r['uid_hex'] in pile_now or r['uid_hex'] in todo:
            continue
        if keep_config.is_fused_component(r):               # (2026-09-26) fused components hold no ladder slot
            continue
        s_ = pvid(r['species_name'], r['form'] or 0); _iv = r['iv_total'] or 0
        _fn = evolvable_forms.canon_form(s_, evolvable_forms.form_name(r['form'] or r['fresh_form']))
        form_names[s_].append(_fn)
        _g0 = evolvable_forms.gender_key(_DEX_OF0.get(s_) or r['pokemon_id'], r['gender'])
        _keys = [(s_, '', _g0)] + ([(s_, _fn, _g0)] if _fn else [])
        if not _plainish(r):
            if r['fresh_alignment'] != 1 and _iv != 45:     # non-hundo shiny / cosmetic: displaces by IV
                for _k in _keys:
                    stage_special[_k].append((_iv, r['cp'] or 0))
            continue
        for _k in _keys:
            # ONE POPULATION FOR BOTH TESTS (2026-09-20). best_any used to include hundos and nundos while
            # stage_plain deliberately excludes them (they are SLOT-EXEMPT: a trophy never consumes a plain
            # slot). So a hundo could veto an evolution that genuinely improves the plain ladder -- an 80%
            # Loudred replacing the 71% Exploud in a full 82/82/71 top-3 was called pointless, while the engine
            # correctly read it as "replaces a weaker kept copy". The bar is what HOLDS a slot, nothing else.
            if _iv != 45 and not (_nundo_on and r['is_zero'] and r['pokemon_id']):
                stage_plain[_k].append((_iv, r['cp'] or 0))
                best_any[_k] = max(best_any[_k], _iv)

    _DEX_OF = {p['speciesId']: p.get('dex') for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
    def stage_key(t, r):
        """The bucket this promise really lands in: the target's own form when the game names one AND every held
        copy of that stage has a readable form, else the whole speciesId."""
        tf = evolvable_forms.canon_form(t, evolvable_forms.target_form(
            r['fresh_form'] or r['form'], t, pvid(r['species_name'], r['form'] or 0), r['gender']))
        names = form_names.get(t) or []
        g = evolvable_forms.gender_key(_DEX_OF.get(t) or 0, r['gender'])     # GENDER IS A LOOK (2026-09-23)
        if tf and names and all(names):
            return (t, tf, g)
        return (t, '', g)

    def stage_cap(t, pool, key=None):
        """keep_policy._stage_cap + _eff_cap: the plain slots left once the specials take theirs."""
        cap = evolvable_forms.ladder_cap(keep_config.cap('plain_line_preevo') if (_is_pre.get(t) and t in _has_parent)
                                         else keep_config.cap('plain_line'),
                                         _DEX_OF.get(t), key[2] if key is not None else 0)   # 2 per gender, dimorphic (2026-09-25)
        sp = stage_special.get(key if key is not None else (t, ''))
        if not sp:
            return cap
        merged = sorted([(iv, cp, 0) for iv, cp in sp] + [(iv, cp, 1) for iv, cp in pool],
                        key=lambda x: (-x[0], -x[1], x[2]))[:cap]     # tie -> the special wins the slot
        return sum(1 for x in merged if x[2] == 1)

    # KEPT ANYWAY AT ITS OWN STAGE, re-derived from the bag (H08, 2026-09-29) -- never from policy_reasons.json. LAW
    # "Worth it": filling a spare slot under a better copy is a reason only for a copy "kept for nothing else, whose
    # alternative is release". A promised copy inside its OWN stage's plain top-cap stays there as stock if it does not
    # evolve, so its alternative is NOT release -- but the engine marks that stock 'variant_floor' only AFTER the copy
    # fails to move up, so a promised stock copy's policy_reasons read "evolve_1 and nothing else" and passed as a
    # rescue (9 live labels, 2026-09-29: two 93% Farfetch'd under a 98% Sirfetch'd ...). The own-stage ladder here is
    # the engine's plain ladder, before any promotion: every plain, slot-holding copy of (speciesId, form, gender) --
    # pile and promised copies included -- the non-hundo shinies and cosmetics of that stage displacing them by IV
    # (special wins ties), the stage cap (middle = plain_line_preevo when a copy there can evolve, else plain_line; 2
    # per gender where the look differs), the collection floor (under it only the stage's best stays).
    _graph = (_is_pre, _term_sp, _dist_sp, _sp2dex, _allreach)
    _FLOOR_IV = keep_config.collection_floor_iv()
    _own_plain, _own_spec, _own_step = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(bool)
    # ...AND THE COLLAPSE (R-A review, 2026-09-29): keep_policy's dominance pass DELETES a true plain kept by nothing but its
    # slot when a KEPT copy of its own stage with a collectible attribute (shiny, background, card, costume, Max, shadow)
    # has a higher IV -- a trophy never dominates. That copy's alternative IS release, and the engine judges its evolution
    # as a RESCUE (keep_policy._collapsing, the 2026-09-23 Minccino), so stock-ness must not call it "kept anyway".
    def _rich(r):
        return bool(r['fresh_shiny'] or (r['fresh_natural_art_bg'] or 0)
                    or (r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0)) or (r['fresh_costume'] or 0)
                    or is_costume_form(r['fresh_form']) or is_costume_form(r['form'])
                    or evolvable_forms.max_axis(r['fresh_bread_mode']) or r['fresh_alignment'] == 1)
    _key_of, _own_dom = {}, collections.defaultdict(list)
    for r in rows.values():
        if keep_config.is_fused_component(r):
            continue
        s_ = pvid(r['species_name'], r['form'] or 0); _iv = r['iv_total'] or 0
        _k0 = (s_, evolvable_forms.canon_form(s_, evolvable_forms.form_name(r['form'] or r['fresh_form'])),
               evolvable_forms.gender_key(_DEX_OF0.get(s_) or r['pokemon_id'], r['gender']))
        _key_of[r['uid_hex']] = _k0
        if (r['uid_hex'] in now_reasons and _iv != 45 and not (_nundo_on and r['is_zero'] and r['pokemon_id'])
                and _rich(r)):
            _own_dom[_k0].append(_iv)                       # a KEPT richer copy: the collapse's dominator
        if not r['fresh_shiny'] and r['fresh_alignment'] != 1:
            _own_step[_k0] = _own_step[_k0] or _kp.evo_can(r, _graph)
        if _plainish(r) and not r['fresh_shiny'] and r['fresh_alignment'] != 1:
            if _iv != 45 and not (_nundo_on and r['is_zero'] and r['pokemon_id']):
                _own_plain[_k0].append(r)
        elif _iv != 45 and (r['fresh_shiny'] or r['fresh_alignment'] != 1):
            _own_spec[_k0].append((_iv, r['cp'] or 0))
    _OWN_STOCK = set()
    for _k0, _pl in _own_plain.items():
        _c0 = evolvable_forms.ladder_cap(keep_config.cap('plain_line_preevo')
                                         if (_own_step[_k0] and _is_pre.get(_k0[0]) and _k0[0] in _has_parent)
                                         else keep_config.cap('plain_line'), _DEX_OF0.get(_k0[0]), _k0[2])
        _m0 = sorted([(a, b, 0) for a, b in _own_spec.get(_k0, ())] + [((x['iv_total'] or 0), (x['cp'] or 0), 1) for x in _pl],
                     key=lambda t: (-t[0], -t[1], t[2]))[:_c0]
        _srt0 = [x for i, x in enumerate(sorted(_pl, key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0), x['uid_hex'])))
                 if i == 0 or (x['iv_total'] or 0) >= _FLOOR_IV]
        _OWN_STOCK |= {x['uid_hex'] for x in _srt0[:sum(1 for t in _m0 if t[2] == 1)]}
    # another keep reason the copy already had (a Best ML, a PvP rank ...) also makes it "kept anyway"; 'variant_floor'
    # is not one here -- on a promised or held copy beyond its stage cap it is the hold itself.
    _collapsed = lambda u: (u in _key_of and not _rich(rows[u])
                            and any(v > (rows[u]['iv_total'] or 0) for v in _own_dom.get(_key_of[u], ())))
    _kept_anyway = lambda u: ((u in _OWN_STOCK and not _collapsed(u))
                              or bool(set(now_reasons.get(u, ())) - {'evolve_1', 'evolve_2', 'variant_floor'}))
    # THE SHINY LADDER'S SPOTS, from the bag (H08, 2026-09-29): every kept shiny AT each stage (the pile and the copies
    # promised away excluded), its PLAIN ones apart (no background, card, costume, Max or shadow) for the plain sub-cap.
    def _sh_collectible(r):
        return bool((r['fresh_natural_art_bg'] or 0) or (r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0))
                    or (r['fresh_costume'] or 0) or is_costume_form(r['fresh_form']) or is_costume_form(r['form'])
                    or evolvable_forms.max_axis(r['fresh_bread_mode']) or r['fresh_alignment'] == 1)
    _sh_at, _shp_at = collections.defaultdict(list), collections.defaultdict(list)
    for r in rows.values():
        if r['fresh_shiny'] and r['uid_hex'] not in pile_now and r['uid_hex'] not in todo and not keep_config.is_fused_component(r):
            _s0 = pvid(r['species_name'], r['form'] or 0)
            # PER SPECIES + FORM (LAW bucket 4; keep_policy's shiny groups are (pokemon_id, form)), 2026-09-30: pooled by
            # pvid alone, pvpoke's one 'florges' held all five colours, so a Yellow Floette's shiny upgrade to the bag's
            # first shiny Yellow Florges read "no spot" against White ones. Filed like the plain buckets: bare + form.
            _fs = evolvable_forms.canon_form(_s0, evolvable_forms.form_name(r['form'] or r['fresh_form']))
            for _k in {(_s0, ''), (_s0, _fs)}:
                _sh_at[_k].append(r['iv_total'] or 0)
                if not _sh_collectible(r):
                    _shp_at[_k].append(r['iv_total'] or 0)

    def _sh_key(t, r):
        """The shiny bucket a promise lands in: stage_key()'s target form (the colour the game names), no gender."""
        return stage_key(t, r)[:2]

    def _shiny_earns(r, t):
        """LAW: an open spot under the stage's shiny cap, or it beats the weakest of a full top-N; a PLAIN shiny must
        also clear the plain sub-cap, and under the shiny floor it takes no plain spot unless the stage has none."""
        iv, dex = (r['iv_total'] or 0), _DEX_OF0.get(t)
        cap = keep_config.species_cap('shiny', dex, keep_config.cap('shiny'))
        h = sorted(_sh_at.get(_sh_key(t, r), []), reverse=True)
        if cap <= 0 or not (len(h) < cap or iv > h[cap - 1]):
            return False
        if _sh_collectible(r):
            return True
        hp = sorted(_shp_at.get(_sh_key(t, r), []), reverse=True)
        if iv < keep_config.shiny_floor_iv() and hp:
            return False
        pcap = cap if keep_config.species_cap('shiny', dex, None) is not None else min(cap, keep_config.cap('shiny_plain'))
        return pcap > 0 and (len(hp) < pcap or iv > hp[pcap - 1])
    why = collections.Counter(); no_reason = []
    for u, targets in sorted(todo.items(), key=lambda kv: (-(rows[kv[0]]['iv_total'] or 0), -(rows[kv[0]]['cp'] or 0), kv[0])):
        if src_of.get(u) == 'shiny':                         # a shiny upgrade, whatever its count tag (2026-09-29)
            _bad_t = [t for t in targets if not _shiny_earns(rows[u], t)]   # DERIVED (H08), no longer asserted
            if _bad_t:
                no_reason.append('%s %d%% -> %s: a shiny upgrade that earns no shiny spot there (the shiny cap is full of '
                                 'better copies)' % (rows[u]['species_name'], (rows[u]['iv_total'] or 0) * 100 // 45,
                                                    '/'.join(_bad_t)))
            else:
                why['shiny: an open or better shiny spot at the next stage'] += 1
            for t in targets:                                  # it takes that spot: the next shiny promise competes with it
                for _k in {(t, ''), _sh_key(t, rows[u])}:
                    _sh_at[_k].append(rows[u]['iv_total'] or 0)
                    if not _sh_collectible(rows[u]):
                        _shp_at[_k].append(rows[u]['iv_total'] or 0)
            continue
        if src_of.get(u) == 'size':                          # a showcase pick, whatever its count tag (2026-09-29)
            why['size: a bigger showcase entry at that stage'] += 1; continue
        if rows[u]['fresh_has_location_card']:
            why['special background moving to a stage that lacks or wants that card'] += 1; continue
        t = targets[0]; ivv = rows[u]['iv_total'] or 0; cpv = rows[u]['cp'] or 0
        tk = stage_key(t, rows[u])
        held = stage_plain.get(tk, [])
        cap = stage_cap(t, list(held) + [(ivv, cpv)], tk)   # the engine judges the pool WITH the arriving copy
        if best_any[tk] < 0:
            why['new stage: no plain copy there yet'] += 1
        elif ivv > best_any[tk]:
            why['new best at that stage'] += 1
        elif len(held) >= cap:
            _drop = sorted(list(held) + [(ivv, cpv)], key=lambda x: (-x[0], -x[1]))[cap:]
            if _drop and ivv > max(_iv for _iv, _cp in _drop):
                why['replaces a weaker kept copy'] += 1
            else:                                            # equal IV: it only out-CPs the copy it pushes out
                no_reason.append('%s %d%% -> %s: only out-CPs an equally good %d%% copy already there'
                                 % (rows[u]['species_name'], ivv * 100 // 45, t, ivv * 100 // 45))
        elif not _kept_anyway(u):                            # re-derived above (H08), never the engine's reasons
            # FILLING A SPARE SLOT IS WORTH IT WHEN THE ALTERNATIVE IS A RELEASE (user 2026-09-20: "im surprised
            # you ask to transfer maschiff instead of evolve it" -> "that means this is happening to every
            # pokemon"). The engine keeps this copy for the evolution and nothing else, so its two outcomes are
            # "occupy a slot the law says you may hold" and "gone forever". Spending candy beats the latter.
            # A copy kept for some OTHER reason is still refused below: that one really would burn candy for
            # nothing, which is the 2026-09-17 rule this does not touch.
            why['rescues a surplus copy into an open slot instead of releasing it'] += 1
        else:
            no_reason.append('%s %d%% -> %s: fills a spare slot under a %d%% copy (and it is kept anyway)'
                             % (rows[u]['species_name'], ivv * 100 // 45, t, best_any[tk] * 100 // 45))
        best_any[tk] = max(best_any[tk], ivv)                # promises stack in IV order, like the engine
        stage_plain[tk].append((ivv, cpv))
    _by = collections.Counter(src_of.get(u) for u in todo)
    print('promises simulated: %d (engine %d, shiny %d, size %d) across %d branch run(s)'
          % (len(todo) - len(unsim), _by['promise'], _by['shiny'], _by['size'], branches))
    print('why each is worth it: ' + '; '.join('%s %d' % kv for kv in why.most_common()))
    print('kept after evolving as: ' + '; '.join('%s %d' % kv for kv in reasons_at.most_common(6)))
    if unsim:
        print('not simulated (identity unknown / costume form): %d -- %s' % (len(unsim), ', '.join(unsim[:8])))
    if cu_unsim:
        print('not simulated (a PvP comb-up -- the sandbox cannot re-rank): %d -- %s' % (len(cu_unsim), ', '.join(cu_unsim[:8])))
    for x in broken:
        print('  *** ' + x)
    for x in no_reason:
        print('  *** NO REASON: ' + x)
    bad = broken + no_reason
    print('VERDICT: %s' % ('ALL PROMISES HOLD -- every labelled evolution stays kept and adds something' if not bad
                           else '%d PROMISE(S) BROKEN OR POINTLESS -- do not sync' % len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
