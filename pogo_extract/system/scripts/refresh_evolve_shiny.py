"""Refresh the 'Evolve Shiny' server tag to the CURRENT candy-evolvable shiny-upgrade set.

Recomputes which in-bag SHINY pre-evolutions would -- if evolved with CANDY ONLY
(no Sinnoh/Unova Stone or special-condition evos; those species are in SPECIAL) --
become the trainer's best (overall OR shiny) of the evolved form, then EXACT-SYNCS
the server tag to that set: adds newly-qualifying shinies, removes ones that no
longer qualify (e.g. just evolved to a terminal form). This is needed because PoGo
tags INHERIT through evolution -- without a recompute the tag accumulates stale
evolved forms (Baxcalibur, Chesnaught, ...). Writes Evolve_Shiny.txt + mirrors the DB
so set_db / reconcile stay consistent.

Usage:  python system/scripts/refresh_evolve_shiny.py [--dry-run]
"""
import sys, os, json, sqlite3
if hasattr(sys.stdout, 'reconfigure'):   # a sandboxed engine run redirects stdout to StringIO (2026-09-17)
    sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
os.chdir(ROOT)
from collections import defaultdict
from keep_policy import build_evo_graph, ITEM_GATED_TARGETS as SPECIAL   # ONE item/special-gated list (2026-09-13)
from keep_policy import pvp_later_stages                # the later stages a specimen can become (Best GL/UL, 2026-09-23)
import keep_config
import evolvable_forms                                  # a costume form the game master cannot evolve is never tagged (Psyduck Swim 2025, 2026-09-16)
from pvp_iv_rule import pvid, usable_best, GL_CAP, UL_CAP
import costume_names as cn
# pogo_il2cpp / tag_ops / reconcile_tags are imported inside main(): compute_target() must stay a light, device-free
# import -- keep_policy calls it, including inside sandboxed engine runs whose stdout is redirected (2026-09-17).

TD = os.path.join(ROOT, 'system', 'analysis', 'tagsets')
COLOR = 6

# Evolved forms reached ONLY via an item (Sinnoh/Unova Stone, etc.) or a special
# condition -- NOT candy. Exclude any pre-evo whose terminal is one of these.


def compute_target(why=None, spent=None, detail=None, gated=None, items_spent=None, db=None, walk=None, held=None):
    """why: reasons to use instead of policy_reasons.json (keep_policy passes its in-memory map); spent: dict to receive
    the candy each family spends on the returned targets (keep_policy reserves it before the plain comb-up). db: the
    database to read -- keep_policy passes its own DB, so a SANDBOXED engine run (regress_pvp_keepers, what-ifs) reads
    the sandbox copy; the import-time os.chdir(ROOT) used to point the relative 'pokemon.db' at the LIVE bag (2026-09-29)."""
    gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
    try:
        seen = {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']}
    except Exception:
        seen = set()
    is_pre, term, dist, sp_to_dex, allreach = build_evo_graph(gm, seen, with_all=True)   # the ONE evolution graph
    dex_to_sid = defaultdict(list)
    for p in gm['pokemon']:
        dex_to_sid[p.get('dex')].append(p['speciesId'])
    c = sqlite3.connect(db or 'pokemon.db'); c.row_factory = sqlite3.Row
    rows = c.execute("SELECT uid_hex u, species_name s, pokemon_id pid, form, iv_total iv, "
                     "is_shiny sh, can_evolve_estimated ce, fresh_costume fc, costume cos, fresh_alignment al, "
                     "gl_stage gs, ul_stage us, fresh_natural_art_bg abg, fresh_has_location_card hlc, "
                     "fresh_loc_card_enum lce, fresh_bread_mode bm, fresh_form ff, gender g "
                     "FROM pokemon WHERE in_bag=1 AND COALESCE(is_component,0)=0").fetchall()   # (2026-09-26) fused components hold no ladder slot
    # FULL rows for the Best GL / Best UL own-stage test (2026-09-23): the winning stage is the USABLE one -- CP at its
    # true level, chain ranks, gender and form all matter -- so the narrow projection above cannot answer it.
    _full = {x['uid_hex']: x for x in c.execute("SELECT * FROM pokemon WHERE in_bag=1 AND COALESCE(is_component,0)=0").fetchall()}
    c.close()
    if walk is None:
        # THE WALK, NOT THE CLOCK, FOR EVERY CALLER (2026-09-29, H04). Only keep_policy passed walk=. preflight_transfer's
        # Evolve Shiny keeper test, granular_tags (the Evolve tags), audit_tags_membership and _evocheck called this bare,
        # so candy.json / inventory.json were judged by their 2 h WALL-CLOCK age: the same pass re-judged 3 h after its
        # walk (a dashboard Sync, --skip-crawl, --audits-only) saw no candy, promised every shiny upgrade unpriced and
        # disagreed with the engine -- measured: a shiny Timburr the family could not pay for became an Evolve target and
        # 'tag membership' FAILED on the unchanged bag. The walk being judged is the one these rows came from.
        try:
            walk = max((str(x['last_scanned']) for x in _full.values() if x['last_scanned']), default=None)
        except (IndexError, KeyError):
            walk = None                                  # a DB without the column: the old wall-clock rule, as before
    _BSx = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
    _graph5 = (is_pre, term, dist, sp_to_dex, allreach)
    _later_sh = {u: set(pvp_later_stages(fr, _graph5)) for u, fr in _full.items() if fr['is_shiny']}   # per specimen

    def _best_at_own_stage(u, rs, own):
        """A Best GL / Best UL copy whose USABLE winning stage is its OWN stage (keep_policy's _own_pvp): never advised
        to evolve. The stage is pvp_iv_rule.usable_best over the stages pvp_later_stages says it can become -- the same
        call keep_policy's rule 15d makes. No full row, or no usable stage -> own stage (the side that never consumes)."""
        for lg, cap in (('gl', GL_CAP), ('ul', UL_CAP)):
            if 'pvp_best_' + lg in rs:
                fr = _full.get(u)
                ub = usable_best(fr, lg, cap, _BSx, later=pvp_later_stages(fr, _graph5)) if fr is not None else None
                if ub is None or ub[2] == own:
                    return True
        return False

    # can_evolve_estimated is species-level -- it doesn't know a *costume* variant is Noevolve.
    # A costume whose raw enum name carries 'Noevolve' has its evolve button greyed out in-game
    # (e.g. Horizons2025Noevolve Floragato), so it must never be tagged "evolve me" (2026-06-09).
    def _noevolve_costume(r):
        # ONE definition (2026-09-17): the game's own rule -- a *Noevolve costume is locked UNLESS the species'
        # allowNoevolveEvolution names it, and a locked FORM (Psyduck Swim 2025) is locked. This used to be a local
        # 'Noevolve in the name' test that wrongly locked the Jan 2020 / Spring 2020 Bulbasaur and Charmander lines.
        return evolvable_forms.row_can_evolve({'form': r['form'], 'fresh_form': None,
                                               'fresh_costume': r['fc'] or r['cos'] or 0,
                                               'pokemon_id': r['pid']}) is False
    try:
        _why = why if why is not None else {u: set(v) for u, v in json.load(open(os.path.join('system', 'analysis', 'policy_reasons.json'))).items()}
    except Exception:
        _why = {}
    _candy = evolvable_forms.candy_now(walk=walk)        # the judged walk's candy, spent best-first (2026-09-17/29)
    _items = evolvable_forms.items_now(walk=walk)        # the judged walk's evolution items: a stone in the bag is a real tap
    _COLLECTIBLE = {'location_card', 'legacy', 'xxl', 'dex_only_copy', 'mighty', 'protected', 'rarity',
                    'adventure_effect', 'hundo', 'nundo', 'shadow_best'}
    maxiv = defaultdict(int); maxsh = defaultdict(int)
    for r in rows:
        maxiv[r['pid']] = max(maxiv[r['pid']], r['iv'] or 0)
        if r['sh']:
            maxsh[r['pid']] = max(maxsh[r['pid']], r['iv'] or 0)
    # NEVER suggest evolving a shiny that would VACATE its stage (2026-06-10 incident: the tag told the
    # user to evolve their ONLY shiny of a pre-evo form -- evolving consumes it, so the stage's shiny was
    # lost from the collection). Rule: per (species, form), the BEST in-bag shiny is the stage's trophy
    # and is never tagged; only SURPLUS shinies (2nd+ of that stage) may qualify.
    # form-0 normalization (same idea as keep_policy cf()): a form-0 row folds into the species' single
    # unambiguous non-zero form, else stage keys split and one real stage gets TWO suggestions
    # (Smoliv x2 / Vanillite x2 in the first cut of this rule).
    _formcnt = defaultdict(set)
    for r in rows:
        if (r['form'] or 0) != 0:
            _formcnt[r['pid']].add(r['form'])
    def _nf(r):
        f = r['form'] or 0
        if f == 0 and len(_formcnt.get(r['pid'], ())) == 1:
            return next(iter(_formcnt[r['pid']]))
        return f
    # PER LOOK (user 2026-09-30: "you dont keep my only anything when evolving shinies. for example the costumed
    # whimsicott i evolved, not theres no costumed cottonee."): a 51% flower-crown shiny Cottonee was a "spare" because a
    # 78% plain shiny Cottonee was the stage's best, so evolving it left no crowned shiny Cottonee. The trophy is kept per
    # look: species + form + costume + the gender where the game draws the two differently (evolvable_forms.gender_key).
    def _look(r):
        return (r['pid'], _nf(r), r['fc'] or 0, evolvable_forms.gender_key(r['pid'], r['g']))   # fresh_costume: `costume` holds junk
    stage_best = {}
    for r in rows:
        if r['sh']:
            k = _look(r)
            b = stage_best.get(k)
            if b is None or ((r['iv'] or 0), r['u']) > ((b[0] or 0), b[1]):
                stage_best[k] = ((r['iv'] or 0), r['u'])
    # LINE-COVERAGE MODEL (user 2026-06-10, after the Rookidee incident: "WHAT THE FUCK DO YOU THINK
    # WERE DOING HERE"): the goal is ONE SHINY AT EVERY STAGE of every line -- coverage, not IV dupes.
    # Per stage: the best shiny is the stage trophy (never tagged); among the surplus, tag AT MOST ONE,
    # and only when the IMMEDIATE NEXT stage up needs it (zero shinies there, or this one strictly beats
    # its best). One suggestion per stage per sync -- chains advance one step at a time on later syncs,
    # so a stack of base shinies can never be funneled wholesale up the line again.
    nxt = {}                                     # speciesId -> immediate next-stage speciesIds
    for p in gm['pokemon']:
        # only edges the engine's graph accepts (its EVO_DROP / availability / BST gates): raw PvPoke lists
        # Cubone -> Alolan Marowak, which GO cannot do -- a 48% shiny Cubone was about to be tagged for it.
        evs = [e for e in ((p.get('family') or {}).get('evolutions') or []) if e in allreach.get(p['speciesId'], ())]
        if evs:
            nxt[p['speciesId']] = evs
    sid_to_pid = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
    shiny_count = defaultdict(int)               # pid -> in-bag shiny count (stage coverage)
    # IV UPGRADES (user 2026-09-13: "shinies should be combed up by IV......wtf"). Per TARGET speciesId (regional
    # forms are their own line): the shiny count and the best shiny IV. A surplus shiny is tagged when the next
    # stage has no shiny (coverage) OR it strictly beats that stage's best shiny (upgrade). The 2026-06-10
    # Corvisquire stacking (5 dupes) came from tagging every qualifying shiny at once; the guards are the
    # ONE-PER-STAGE rule below plus raising the target's bar on every tag -- not the absence of upgrades.
    # SHINY LADDER LIKE PLAINS (user 2026-09-17 "yes"): per target stage, the IVs of every shiny there, best first.
    # A spare earns a spot when that stage is under its shiny cap or it beats the weakest of the full top-N.
    sh_ivs = defaultdict(list)
    # PLAIN shinies (no bg / card / costume / Max / shadow) have their own sub-cap, cap('shiny_plain') (user 2026-09-23)
    from costume_forms import is_costume_form as _icf
    def _plain_sh(r):
        return not ((r['abg'] or 0) or (r['hlc'] and (r['lce'] or 0)) or (r['fc'] or 0) or _icf(r['ff']) or _icf(r['form'])
                    or evolvable_forms.max_axis(r['bm']) or r['al'] == 1)
    sh_ivs_pl = defaultdict(list)
    # PER SPECIES + FORM (LAW bucket 4; keep_policy's shiny groups are (pokemon_id, form)), 2026-09-30: one pvpoke id can
    # hold several plain forms (all five Florges colours), and pooling them hid real upgrades into an empty colour. Filed
    # bare + form like audit_promises; _skey() judges a spare on the form the game names for it at the next stage.
    _fname = lambda r: evolvable_forms.canon_form(pvid(r['s'], r['form'] or 0), evolvable_forms.form_name(r['form'] or r['ff']))
    form_names = defaultdict(list)                       # speciesId -> the form name of every held copy
    for r in rows:
        form_names[pvid(r['s'], r['form'] or 0)].append(_fname(r))
        if r['sh']:
            shiny_count[r['pid']] += 1
            for _k in {(pvid(r['s'], r['form'] or 0), ''), (pvid(r['s'], r['form'] or 0), _fname(r))}:
                sh_ivs[_k].append(r['iv'] or 0)
                if _plain_sh(r):
                    sh_ivs_pl[_k].append(r['iv'] or 0)
    for _v in list(sh_ivs.values()) + list(sh_ivs_pl.values()):
        _v.sort(reverse=True)

    def _skey(n, r):
        """The shiny bucket r lands in at stage n: the form the game names for it when every held copy of n has a
        readable form (audit_promises.stage_key's rule), else the whole speciesId."""
        fr = _full.get(r['u'])
        tf = evolvable_forms.canon_form(n, evolvable_forms.target_form(r['ff'] or r['form'], n, pvid(r['s'], r['form'] or 0),
                                                                      fr['gender'] if fr is not None else None))
        names = form_names.get(n) or []
        return (n, tf) if tf and names and all(names) else (n, '')

    def _take(n, r):
        """r takes its spot at stage n (a tag or a hold): the next spare must beat it -- filed bare + form, like the fill."""
        for _k in {(n, ''), _skey(n, r)}:
            sh_ivs[_k].append(r['iv'] or 0); sh_ivs[_k].sort(reverse=True)
            if _plain_sh(r):
                sh_ivs_pl[_k].append(r['iv'] or 0); sh_ivs_pl[_k].sort(reverse=True)
    by_stage = defaultdict(list)                 # (pid, form) -> surplus shiny candidates
    for r in rows:
        # EVOLVABILITY FROM THE ONE GRAPH, NOT A STALE COLUMN (H08, 2026-09-29): can_evolve_estimated has no writer since
        # 2026-05-05 and reads NULL on every later catch, which `!= 1` turned into "cannot evolve" for 752 shinies.
        if not r['sh'] or not _later_sh.get(r['u']):
            continue
        if _noevolve_costume(r) or r['pid'] in keep_config.protected_pids():
            continue
        if r['al'] == 1 or (_why.get(r['u'], set()) & _COLLECTIBLE):
            # LAW.md (2026-09-17): a shiny kept as a collectible or trophy (special background, legacy moves, XXL,
            # last copy, Mighty, legendary, Adventure Effect, hundo/nundo) or a shadow is never advised to evolve --
            # evolving consumes exactly what it is kept for. Only a plain surplus shiny climbs.
            continue                             # a PROTECTED species is never advised to evolve (2026-09-16)
        _rs, _own = _why.get(r['u'], set()), pvid(r['s'], r['form'] or 0)
        if _best_at_own_stage(r['u'], _rs, _own):
            continue   # a Best GL/UL copy whose USABLE winning stage is its OWN stage never evolves (2026-09-23; audit_labels)
        if stage_best.get(_look(r), (None, None))[1] == r['u']:
            continue   # the BEST (or only) shiny of its look at this stage -- never consumed by evolution (2026-06-10, per look 2026-09-30)
        sid = pvid(r['s'], r['form'] or 0)
        if not is_pre.get(sid):
            continue
        by_stage[(r['pid'], _nf(r))].append(r)
    target = set()
    for (pid, form), cands in by_stage.items():
        cands.sort(key=lambda r: (-(r['iv'] or 0), r['u']))
        for r in cands:                          # best spare first; EVERY spare that earns a shiny spot (2026-09-17)
            sid = pvid(r['s'], form)
            tagged = False
            ok = []
            _pending = None                  # a gated branch, kept aside in case no branch is takeable
            _fr = _full.get(r['u'])
            _branches = [x for x in nxt.get(sid, []) if sid_to_pid.get(x) and sid_to_pid.get(x) != pid
                         and x in _later_sh.get(r['u'], ())         # only a stage THIS specimen can become (H08)
                         # ... and one the GAME gives it (client game master, 2026-09-29): pvpoke hands every Scyther a
                         # Kleavor; PoGo does not, and audit_tag_truth (can_reach) called that 'Evolve Once' untrue
                         and (_fr is None or evolvable_forms.can_reach(_fr['fresh_form'] or _fr['form'], x, sid,
                                                                      _fr['gender']) is not False)]
            def _gated_sid(x):
                # THE GAME'S OWN GATE FIRST (2026-09-29): the client game master answers for every stage (gate_reason), and
                # audit_tag_truth judges 'Evolve Gated' by it. The hand list SPECIAL also held 8 stages the game does not
                # gate (mr_rime, cursola, kleavor, wyrdeer, basculegion, alcremie, huntail, gorebyss): two Galarian Mr.
                # Mime wore an untrue 'Evolve Gated' the moment the shiny ladder reached them. Random taps (Clamperl) are
                # handled by the split rule below; a form that cannot evolve is already out of _later_sh.
                g = evolvable_forms.gate_reason(x)
                if g is None:
                    g = evolvable_forms.gate_reason((dex_to_sid.get(sid_to_pid.get(x)) or [''])[0])
                if g is not None:
                    return bool(g)
                return x in SPECIAL or any(t in SPECIAL for t in dex_to_sid.get(sid_to_pid.get(x), []))
            for nsid in _branches:
                if not _gated_sid(nsid):
                    ok.append(nsid)
                    continue
                # NOT A PLAIN CANDY TAP. It is still a real upgrade, so decide honestly instead of dropping it
                # (user 2026-09-17 "Fix everything"): if the ONLY thing in the way is an ITEM that is in the bag
                # right now, and no candy sibling could steal the tap, it IS a one-tap upgrade -- tag it and spend
                # the item. Anything else (a stone he lacks, a buddy walk, a task, a lure, a random branch) is
                # RECORDED so the ladder report names what it needs, rather than vanishing without a word.
                _why = evolvable_forms.gate_reason(nsid) or evolvable_forms.gate_reason((dex_to_sid.get(sid_to_pid.get(nsid)) or [''])[0])
                _it = evolvable_forms.step_item(sid, nsid)
                _ambig = any(x != nsid and not _gated_sid(x) for x in _branches)
                _key = evolvable_forms._item_key(_it) if _it else None
                _payable = (_it is not None and _why == ['evolutionItemRequirement'] and not _ambig
                            and _items is not None and _items.get(_key, 0) >= 1)
                if _payable:
                    ok.append(nsid)
                    continue
                # A branch he cannot take is simply NOT ONE OF THE OUTCOMES of a plain tap, so it must not veto the
                # others: an Eevee whose Espeon branch needs a buddy walk still taps into Vaporeon/Jolteon/Flareon.
                # Remember it only in case NO branch is takeable, so the report can say what it needed.
                if _pending is None:
                    _have = (_items or {}).get(_key, 0) if _key else None
                    _pending = {'species': r['s'], 'iv': r['iv'], 'target': nsid, 'why': _why,
                                'item': evolvable_forms.item_name(_it) if _it else None, 'have': _have,
                                'need': evolvable_forms.gate_text(nsid, sid, have=_have)}   # the game's own words
            def need(n, iv=(r['iv'] or 0), pl=_plain_sh(r), row=r):
                pid = sid_to_pid.get(n)
                cap = keep_config.species_cap('shiny', pid, keep_config.cap('shiny'))
                k = _skey(n, row)
                h = sh_ivs.get(k, [])
                if cap <= 0 or not (len(h) < cap or iv > h[cap - 1]):
                    return False
                if not pl:
                    return True
                _K = keep_config.shiny_floor_keep()                     # ... or one of the stage's N best (2026-10-25: "at least keep 2")
                if iv < keep_config.shiny_floor_iv() and sh_ivs_pl.get(k) and len(h) >= _K and iv <= h[_K - 1]:   # shiny floor (2026-09-24): only a form's first PLAIN shiny may be that low
                    return False
                pcap = cap if keep_config.species_cap('shiny', pid, None) is not None else min(cap, keep_config.cap('shiny_plain'))
                hp = sh_ivs_pl.get(k, [])
                return pcap > 0 and (len(hp) < pcap or iv > hp[pcap - 1])   # a plain spare must clear the PLAIN bar too
            if not ok and gated is not None and _pending is not None and need(_pending['target']):
                gated[r['u']] = _pending         # nothing takeable at all -> the report names what it needs -- only when
                #                                  that stage has a shiny spot for it (a gated upgrade that earns nothing
                #                                  is no upgrade: a 62% shiny Qwilfish was told to go for a full Overqwil)
            # THE HOLD (H08, 2026-09-29). LAW: "A shiny past the shiny cap is held (reason shiny_ladder) when it earns such a
            # spot", and a copy that earns a slot it cannot take today is HELD, never released. Every branch gated today
            # (a buddy walk, a task, a stone he lacks) is not "no spot": the spare that would earn one on every branch it
            # can land on is held -- kept, no label (`held`: keep_policy marks it). Candy-short ones are held below.
            if not ok and _branches and all(need(n) for n in _branches):
                if held is not None:
                    held[r['u']] = list(_branches)
                # ... and the bar rises in EVERY caller (2026-09-29): build_tagsets and the audits call this without
                # `held`, so they skipped the append and told a 62% shiny Qwilfish to go for an Overqwil spot the 80%
                # and 76% holds ahead of it had already taken -- 'culled after evolving' in audit_promises.
                for _n in _branches:             # a HOLD takes its spot like a promise: the next spare must beat it
                    _take(_n, r)
            if ok and all(need(n) for n in ok):  # an open shiny spot OR beats the weakest; a SPLIT needs it on every branch
                fam = evolvable_forms.family(sid)    # (random tap / task choice the label cannot name, 2026-09-17)
                cost = max((evolvable_forms.step_cost(sid, n) or 0) for n in ok)
                # UNREAD CANDY IS NOT "CAN PAY" (LAW 2026-09-29: "an unread count HOLDS (no Evolve label)"; keep_policy._afford
                # already reads it so for every plain promise) -- the spare is HELD, never labelled on a count nobody read.
                if (_candy is None and fam is not None and cost) or \
                        (_candy is not None and fam is not None and _candy.get(fam, 0) < cost):
                    if held is not None:
                        held[r['u']] = list(ok)      # earned a spot, cannot pay today: HELD, never released (H08) --
                        for _n in ok:                # and it takes that spot (LAW 2026-09-29: an unpaid hold commits)
                            _take(_n, r)
                    continue                         # not affordable now: no tag (the next surplus may be, e.g. cheaper)
                if _candy is not None and fam is not None:
                    _candy[fam] = _candy.get(fam, 0) - cost
                if _items is not None:                       # one stone, one suggestion
                    for _n in ok:
                        _i2 = evolvable_forms.step_item(sid, _n)
                        if _i2:
                            _k2 = evolvable_forms._item_key(_i2)
                            _items[_k2] = _items.get(_k2, 0) - 1
                            if items_spent is not None:
                                items_spent[_k2] = items_spent.get(_k2, 0) + 1
                if spent is not None and fam is not None:
                    spent[fam] = spent.get(fam, 0) + cost
                target.add(r['u']); tagged = True
                if detail is not None:
                    detail[r['u']] = list(ok)             # the next stage(s) this shiny is promised (audit_promises)
                for n in ok:                          # the evolved shiny takes its spot: the next spare competes with it
                    _take(n, r)
    return target


def mirror_db(target):
    c = sqlite3.connect('pokemon.db')
    for uh, atn in c.execute("SELECT uid_hex,auth_tag_names FROM pokemon WHERE "
                             "(';'||COALESCE(auth_tag_names,'')||';') LIKE '%;Evolve Shiny;%'").fetchall():
        parts = [t for t in (atn or '').split(';') if t and t != 'Evolve Shiny']
        c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?", (';'.join(sorted(parts)), uh))
    for uh in target:
        row = c.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
        if row is None:
            continue
        parts = [t for t in (row[0] or '').split(';') if t]
        if 'Evolve Shiny' not in parts:
            parts.append('Evolve Shiny')
        c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?", (';'.join(sorted(parts)), uh))
    c.commit(); c.close()


def main():
    raise SystemExit("'Evolve Shiny' is RETIRED (2026-09-29): its picks are Evolve Once / Twice members via granular_tags.evolve_advice, "
                     'pushed by prune_tags with every other tag. compute_target() is still the rule; nothing to push from here.')
    import pogo_il2cpp as pg
    import tag_ops
    from reconcile_tags import ENUM_MEMBERS_JS
    dry = '--dry-run' in sys.argv[1:]
    target = compute_target()
    try:                                   # (2026-09-26) a copy on a 'Stop at <stage>' tag never gets Evolve Shiny back
        import granular_tags as _gt
        _stop = set(json.load(open(_gt.STOP_ASSIGN, encoding='utf-8')))
    except (OSError, ValueError) as _e:
        raise SystemExit('refresh_evolve_shiny: stop_assign.json unreadable (%s) -- refusing to push Evolve Shiny' % _e)
    target = {u: v for u, v in target.items() if u not in _stop} if isinstance(target, dict) else [u for u in target if u not in _stop]
    print(f"target candy-evolvable shiny upgrades (in-bag): {len(target)}")
    norm = lambda x: format(int(x, 16), 'x')
    target_n = {norm(u) for u in target}

    sess, pid = pg.get_session(); print(f"attached pid {pid}")
    try:
        if not dry:
            try:
                from ready_gate import ensure_ready_for_writes
                ensure_ready_for_writes(sess, pid)
            except Exception as e:
                print(f"[ready_gate] {e}")
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        bag_map = pg.walk_bag_protos(sess, bag)
        hex_to_proto = {format(int(d), 'x'): pp for d, pp in bag_map.items()}
        proto_to_hex = {pp: uh for uh, pp in hex_to_proto.items()}
        en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
        try:
            srv = {t['name']: t for t in en.exports_sync.enumerate_all_tag_members(svc)}
        finally:
            en.unload()
        cur = set()
        for pp in srv.get('Evolve Shiny', {}).get('members', []):
            uh = proto_to_hex.get(pp)
            if uh:
                cur.add(uh)
        add = target_n - cur
        remove = cur - target_n
        print(f"server Evolve Shiny={len(cur)}  target={len(target_n)}  ->  add {len(add)}, remove {len(remove)}")
        if dry:
            print("[dry-run] no writes"); return
        # write file only on a real run (so a dry-run can't desync file vs server)
        open(os.path.join(TD, 'Evolve_Shiny.txt'), 'w').write('\n'.join(sorted(target)))
        bt = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt)
            tp = tag_ops.create_tag(bt, svc, 'Evolve Shiny', COLOR)
            if add:
                protos = [hex_to_proto[u] for u in add if u in hex_to_proto]
                tag_ops.apply_members(bt, svc, tp, protos)
                print(f"added {len(protos)}/{len(add)}")
            ok = 0
            for u in sorted(remove):
                lp = hex_to_proto.get(u)
                if lp:
                    try:
                        if tag_ops.untag_one(bt, svc, lp, tp).get('ok'):
                            ok += 1
                    except Exception as e:
                        print(f"  untag {u}: {e}")
            if remove:
                print(f"removed {ok}/{len(remove)}")
        finally:
            bt.unload()
        mirror_db(target)
        print("DB mirrored")
    finally:
        sess.detach()


if __name__ == '__main__':
    main()
