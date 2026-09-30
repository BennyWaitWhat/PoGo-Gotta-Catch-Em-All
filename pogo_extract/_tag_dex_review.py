"""Refresh 3 dex-completion review tags with refined criteria.

v2 of the original (bug-fixes after user feedback that "many were questionable"):

Bug fixes:
  - GENDER filter for female-only evolutions: skip male specimens for
    Combee→Vespiquen (#416), Salandit→Salazzle (#758).
  - REGION-LOCKED EVOLUTIONS: a Kantonian-form shadow Sneasel can ONLY
    reach Weavile (461), not Sneasler (903). Same for Yamask (Cofagrigus
    only, not Runerigus from Kanto). Hisuian/Galarian-only targets excluded
    when specimen is wrong region. Form determined from form_enum.json.
  - PURIFY investment filter: exclude shadows with gl_rank<=15, ul_rank<=15,
    or level>=30 — these are PVP-meta and/or stardust-invested keepers.
    Among remaining per species, still pick lowest IV.
  - AUTO-UNTAG stale: any pokemon currently tagged but no longer in the
    desired set (e.g., evolved Pikachu→Raichu inheriting "1. Shiny Evos"
    when shiny Raichu medal is now filled).

Tags (unchanged from v1):
  1. Shiny Evos     1 per Q1 species (best-IV shiny, gender/region OK)
  2. Shadow Evos    1 per Q3 species (best-IV shadow, region OK)
  3. Purify         1 per Q-purify species (lowest-IV combat-non-keeper)
"""
import argparse, json, os, re, shutil, sqlite3, sys, time
from collections import defaultdict

import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
DEX = os.path.join(HERE, 'dex_deep_full.json')
GM = os.path.join(HERE, 'pvpoke_gamemaster.json')
FORM_ENUM = os.path.join(HERE, 'form_enum.json')
BULK_TAG_JS = os.path.join(HERE, 'bulk_tag.js')

# Tag config (unchanged)
TAGS = [
    {'name': '1. Shiny Evos',  'color': 5, 'kind': 'shiny_evo'},
    {'name': '2. Shadow Evos', 'color': 4, 'kind': 'shadow_evo'},
    {'name': '3. Purify',      'color': 3, 'kind': 'purify'},
]

# Targets that require a specific regional variant in the source line.
# A target IS reachable from any source that produces it in pvpoke's family.evolutions —
# this map filters OUT cases where the specimen's form CAN'T reach the target.
REGION_LOCKED_TARGETS = {
    900: 'hisuian',   # Kleavor (Hisuian Scyther only)
    901: 'hisuian',   # Ursaluna (Hisuian Teddiursa/Ursaring only)
    902: 'hisuian',   # Basculegion (White-Striped Basculin only)
    903: 'hisuian',   # Sneasler (Hisuian Sneasel/Weavile only)
    904: 'hisuian',   # Overqwil (Hisuian Qwilfish only)
    862: 'galarian',  # Obstagoon (Galarian Linoone/Zigzagoon only)
    864: 'galarian',  # Cursola (Galarian Corsola only)
    865: 'galarian',  # Sirfetch'd (Galarian Farfetch'd only)
    866: 'galarian',  # Mr. Rime (Galarian Mr. Mime only)
    867: 'galarian',  # Runerigus (Galarian Yamask only)
}

# Female-only evolutions: target_pid → required gender (2=FEMALE)
GENDER_LOCKED_TARGETS = {
    416: 2,  # Vespiquen needs FEMALE Combee (415)
    758: 2,  # Salazzle needs FEMALE Salandit (757)
}

# Trade-only evolutions in PoGo as of 2026 — impossible to perform on shadow
# (shadows cannot be traded). For shiny/normal these are still doable (with a
# willing friend) so we don't filter them; only shadows lose access.
TRADE_ONLY_TARGETS_FROM_SHADOW = {
    526,  # Boldore → Gigalith
    534,  # Gurdurr → Conkeldurr
    589,  # Karrablast → Escavalier (special trade w/ Shelmet)
    617,  # Shelmet → Accelgor   (special trade w/ Karrablast)
}

# Purify investment filter
PURIFY_MAX_LEVEL = 30      # level<30 to be a purify candidate
PURIFY_MAX_PVP_RANK = 15   # gl_rank/ul_rank > 15 (or NULL) to be a purify candidate


def detect_region_from_form_name(form_name):
    if not form_name: return 'kantonian'
    if 'Hisuian' in form_name: return 'hisuian'
    if 'WhiteStriped' in form_name: return 'hisuian'  # Basculin White-Striped → Basculegion line
    if 'Galarian' in form_name: return 'galarian'
    if 'Alola' in form_name: return 'alolan'
    if 'Paldean' in form_name or 'PaldeaCombat' in form_name: return 'paldean'
    return 'kantonian'


def has_cat(entry, cat):
    return any(c['cat'] == cat and c['acq'] for c in entry.get('cats', []))


def build_pid_data():
    """Returns (pid_to_name, pid_to_targets)."""
    gm = json.load(open(GM, 'r', encoding='utf-8'))
    sid_to_dex = {}
    for x in gm['pokemon']:
        sid = x.get('speciesId'); d = x.get('dex')
        if sid is None or d is None: continue
        sid_to_dex[sid] = d
    pid_to_name = {}
    for x in gm['pokemon']:
        sid = x.get('speciesId', ''); d = x.get('dex'); nm = x.get('speciesName', '') or ''
        if d is None or '_shadow' in sid: continue
        if '(' not in nm and d not in pid_to_name:
            pid_to_name[d] = nm
    for x in gm['pokemon']:
        sid = x.get('speciesId', ''); d = x.get('dex'); nm = x.get('speciesName', '') or ''
        if d is None or '_shadow' in sid or d in pid_to_name: continue
        clean = re.sub(r'\s*\([^)]*\)\s*', '', nm).strip()
        if clean: pid_to_name[d] = clean
    pid_to_targets = defaultdict(set)
    for x in gm['pokemon']:
        sid = x.get('speciesId', '')
        if '_shadow' in sid: continue
        src = x.get('dex')
        if src is None: continue
        for ev in (x.get('family') or {}).get('evolutions') or []:
            tgt = sid_to_dex.get(ev)
            if tgt is not None and tgt != src:
                pid_to_targets[src].add(tgt)
    return pid_to_name, dict(pid_to_targets)


def reachable_targets(pid, pid_to_targets):
    seen = set(); stack = [pid]
    while stack:
        cur = stack.pop()
        for tgt in pid_to_targets.get(cur, ()):
            if tgt in seen: continue
            seen.add(tgt); stack.append(tgt)
    return seen


def reachable_for_specimen(pid, specimen_region, specimen_gender, pid_to_targets, is_shadow=False):
    """Reachable evolution targets, filtered by region-, gender-, and shadow-trade rules."""
    targets = reachable_targets(pid, pid_to_targets)
    out = set()
    excluded = []
    for tgt in targets:
        req_region = REGION_LOCKED_TARGETS.get(tgt)
        if req_region and req_region != specimen_region:
            excluded.append((tgt, f'needs {req_region}, specimen is {specimen_region}'))
            continue
        req_gender = GENDER_LOCKED_TARGETS.get(tgt)
        if req_gender and specimen_gender != req_gender:
            g = {1:'male',2:'female',3:'genderless',0:'unset',None:'unknown'}.get(specimen_gender, str(specimen_gender))
            excluded.append((tgt, f'needs female, specimen is {g}'))
            continue
        if is_shadow and tgt in TRADE_ONLY_TARGETS_FROM_SHADOW:
            excluded.append((tgt, f'requires trade-evolution; shadows cannot be traded'))
            continue
        out.add(tgt)
    return out, excluded


def compute_plan():
    dex = json.load(open(DEX, 'r', encoding='utf-8'))
    all_entries = {e['pid']: e for e in dex['All']}
    pid_to_name, pid_to_targets = build_pid_data()
    form_enum = json.load(open(FORM_ENUM, 'r', encoding='utf-8')) if os.path.exists(FORM_ENUM) else {}

    shiny_have  = {p for p, e in all_entries.items() if has_cat(e, 11)}
    shadow_have = {p for p, e in all_entries.items() if has_cat(e, 15)}
    purified_have = {p for p, e in all_entries.items() if has_cat(e, 16)}

    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    shiny_bag = conn.execute(
        "SELECT uid_hex, pokemon_id, species_name, form, cp, iv_total, gender, auth_tag_names "
        "FROM pokemon WHERE in_bag=1 AND fresh_shiny=1"
    ).fetchall()
    shadow_bag = conn.execute(
        "SELECT uid_hex, pokemon_id, species_name, form, cp, iv_total, gender, level, "
        "       gl_rank, ul_rank, auth_tag_names "
        "FROM pokemon WHERE in_bag=1 AND fresh_alignment=1"
    ).fetchall()
    conn.close()

    # ---- Shiny Evo ----
    by_pid_shiny = defaultdict(list)
    for r in shiny_bag: by_pid_shiny[r['pokemon_id']].append(r)
    shiny_plan = []
    shiny_skipped = []  # (pid, name, reason) — species we couldn't tag and why
    for src_pid in sorted(by_pid_shiny):
        owners = by_pid_shiny[src_pid]
        # Sort: best IV / CP first
        owners_sorted = sorted(owners, key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        # Try each owner in best-IV order; pick the first one with at least one reachable missing target
        chose = None; choice_targets = None; choice_excluded = None
        for owner in owners_sorted:
            region = detect_region_from_form_name(form_enum.get(str(owner['form']), '') if owner['form'] else '')
            targets, excluded = reachable_for_specimen(src_pid, region, owner['gender'], pid_to_targets)
            missing = sorted(t for t in targets if t not in shiny_have)
            if missing:
                chose = owner; choice_targets = missing; choice_excluded = excluded
                break
        if not chose:
            # All owners blocked or no missing targets remain — record reason
            if owners_sorted:
                owner = owners_sorted[0]
                region = detect_region_from_form_name(form_enum.get(str(owner['form']), '') if owner['form'] else '')
                t, exc = reachable_for_specimen(src_pid, region, owner['gender'], pid_to_targets)
                missing_unfiltered = sorted(rr for rr in reachable_targets(src_pid, pid_to_targets) if rr not in shiny_have)
                if missing_unfiltered and not t:
                    shiny_skipped.append((src_pid, pid_to_name.get(src_pid, f'pid{src_pid}'),
                                          f'all evolution paths blocked: {exc}'))
            continue
        shiny_plan.append({
            'uid_hex': chose['uid_hex'],
            'pid': src_pid,
            'name': pid_to_name.get(src_pid, f'pid{src_pid}'),
            'cp': chose['cp'], 'iv': chose['iv_total'],
            'gender': chose['gender'], 'form': chose['form'],
            'missing_targets': choice_targets,
            'excluded_targets': choice_excluded,
            'existing_tags': chose['auth_tag_names'] or '',
            'owner_count': len(owners),
        })

    # ---- Shadow Evo ----
    by_pid_shadow = defaultdict(list)
    for r in shadow_bag: by_pid_shadow[r['pokemon_id']].append(r)
    shadow_plan = []
    shadow_skipped = []
    for src_pid in sorted(by_pid_shadow):
        owners = by_pid_shadow[src_pid]
        owners_sorted = sorted(owners, key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        chose = None; choice_targets = None; choice_excluded = None
        for owner in owners_sorted:
            # Shadows are universally Kantonian (TGR doesn't drop regional variants)
            region = 'kantonian'
            targets, excluded = reachable_for_specimen(src_pid, region, owner['gender'], pid_to_targets, is_shadow=True)
            missing = sorted(t for t in targets if t not in shadow_have)
            if missing:
                chose = owner; choice_targets = missing; choice_excluded = excluded
                break
        if not chose:
            if owners_sorted:
                missing_unfiltered = sorted(rr for rr in reachable_targets(src_pid, pid_to_targets) if rr not in shadow_have)
                if missing_unfiltered:
                    shadow_skipped.append((src_pid, pid_to_name.get(src_pid, f'pid{src_pid}'),
                                            f'all reachable targets are region/gender-locked away'))
            continue
        shadow_plan.append({
            'uid_hex': chose['uid_hex'],
            'pid': src_pid,
            'name': pid_to_name.get(src_pid, f'pid{src_pid}'),
            'cp': chose['cp'], 'iv': chose['iv_total'],
            'level': chose['level'], 'gender': chose['gender'],
            'missing_targets': choice_targets,
            'excluded_targets': choice_excluded,
            'existing_tags': chose['auth_tag_names'] or '',
            'owner_count': len(owners),
        })

    # ---- Purify ----
    shadow_evo_uids = {x['uid_hex'] for x in shadow_plan}
    purify_eligible_pids = shadow_have - purified_have
    purify_plan = []
    purify_kept_for_combat = []  # species where all candidates are combat-keepers
    purify_kept_for_evo = []     # species where the only shadow is in shadow_evo
    for src_pid in sorted(purify_eligible_pids):
        owners = by_pid_shadow.get(src_pid, [])
        if not owners: continue
        # 1) Remove anything in shadow_evo (can't both evolve AND purify the same specimen)
        not_in_evo = [o for o in owners if o['uid_hex'] not in shadow_evo_uids]
        if not not_in_evo:
            purify_kept_for_evo.append((src_pid, pid_to_name.get(src_pid, f'pid{src_pid}'),
                                        f'only shadow in bag is in Shadow Evos'))
            continue
        # 2) Filter to purify-eligible (NOT combat keeper)
        def is_combat_keeper(o):
            lvl = o['level'] or 0
            gl  = o['gl_rank']
            ul  = o['ul_rank']
            if lvl >= PURIFY_MAX_LEVEL: return True
            if gl is not None and gl <= PURIFY_MAX_PVP_RANK: return True
            if ul is not None and ul <= PURIFY_MAX_PVP_RANK: return True
            return False
        candidates = [o for o in not_in_evo if not is_combat_keeper(o)]
        if not candidates:
            purify_kept_for_combat.append((src_pid, pid_to_name.get(src_pid, f'pid{src_pid}'),
                                           f'all {len(not_in_evo)} shadow(s) are combat keepers (lvl>={PURIFY_MAX_LEVEL} or PVP rank<={PURIFY_MAX_PVP_RANK})'))
            continue
        # 3) Among candidates, pick lowest IV (then lowest CP)
        candidates.sort(key=lambda x: ((x['iv_total'] or 0), (x['cp'] or 0)))
        chose = candidates[0]
        purify_plan.append({
            'uid_hex': chose['uid_hex'],
            'pid': src_pid,
            'name': pid_to_name.get(src_pid, f'pid{src_pid}'),
            'cp': chose['cp'], 'iv': chose['iv_total'],
            'level': chose['level'],
            'gl_rank': chose['gl_rank'], 'ul_rank': chose['ul_rank'],
            'existing_tags': chose['auth_tag_names'] or '',
            'shadow_count_in_bag': len(owners),
            'candidates_count': len(candidates),
        })

    return {
        'shiny': shiny_plan, 'shiny_skipped': shiny_skipped,
        'shadow': shadow_plan, 'shadow_skipped': shadow_skipped,
        'purify': purify_plan,
        'purify_kept_for_combat': purify_kept_for_combat,
        'purify_kept_for_evo': purify_kept_for_evo,
    }


def compute_diff(plan):
    """For each tag, compute desired_uids and currently_tagged_uids, then add/remove."""
    desired = {
        '1. Shiny Evos':  {x['uid_hex'] for x in plan['shiny']},
        '2. Shadow Evos': {x['uid_hex'] for x in plan['shadow']},
        '3. Purify':      {x['uid_hex'] for x in plan['purify']},
    }
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    current = {}
    for tag in desired:
        rows = conn.execute(
            "SELECT uid_hex, auth_tag_names FROM pokemon WHERE in_bag=1 AND auth_tag_names LIKE ?",
            ('%' + tag + '%',)
        ).fetchall()
        current[tag] = {uh for uh, txt in rows if tag in (txt or '').split(';')}
    conn.close()
    diff = {}
    for tag in desired:
        diff[tag] = {
            'to_tag': sorted(desired[tag] - current[tag]),
            'to_untag': sorted(current[tag] - desired[tag]),
            'desired': desired[tag],
            'current': current[tag],
        }
    return diff


def _uid_dec(uid_hex):
    return str(int(uid_hex, 16))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    plan = compute_plan()
    diff = compute_diff(plan)

    print('=== Refined plan ===\n')
    # Show what would be in each tag
    for cfg in TAGS:
        name = cfg['name']
        d = diff[name]
        target_list = plan['shiny'] if cfg['kind'] == 'shiny_evo' else \
                      plan['shadow'] if cfg['kind'] == 'shadow_evo' else plan['purify']
        print(f"\n--- {name} ---  desired={len(d['desired'])} current={len(d['current'])} "
              f"+{len(d['to_tag'])} -{len(d['to_untag'])}")
        # show entries to ADD
        if d['to_tag']:
            print(f"  ADD ({len(d['to_tag'])}):")
            for x in target_list:
                if x['uid_hex'] in d['to_tag']:
                    extra = ''
                    if 'missing_targets' in x:
                        extra = ' -> ' + ','.join(f'#{t}' for t in x['missing_targets'])
                    print(f"    + {x['uid_hex']} #{x['pid']:4d} {x['name']:14s} iv={x['iv']:2d} cp={x['cp']:>4}{extra}")
        if d['to_untag']:
            print(f"  REMOVE ({len(d['to_untag'])}):")
            conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
            for uid in d['to_untag']:
                r = conn.execute(
                    "SELECT pokemon_id, species_name, cp, iv_total, fresh_shiny, fresh_alignment "
                    "FROM pokemon WHERE uid_hex=?", (uid,)).fetchone()
                if r:
                    sh = 'S' if r[4] else ' '; sd = 'D' if r[5]==1 else ' '
                    print(f"    - {uid} #{r[0]:4d} {r[1]:14s} cp={r[2]:>4} iv={r[3]:2d} {sh}{sd}")
                else:
                    print(f"    - {uid} (not in DB)")
            conn.close()

    # show what got filtered out (interesting for "questionable" complaint)
    print("\n--- Filter explanations (why some entries were dropped) ---")
    if plan['shiny_skipped']:
        print(f"  Shiny Evos skipped: {len(plan['shiny_skipped'])}")
        for pid, nm, reason in plan['shiny_skipped'][:10]:
            print(f"    #{pid} {nm}: {reason}")
    if plan['shadow_skipped']:
        print(f"  Shadow Evos skipped: {len(plan['shadow_skipped'])}")
        for pid, nm, reason in plan['shadow_skipped'][:10]:
            print(f"    #{pid} {nm}: {reason}")
    if plan['purify_kept_for_evo']:
        print(f"  Purify deferred to Shadow Evos: {len(plan['purify_kept_for_evo'])}")
        for pid, nm, reason in plan['purify_kept_for_evo'][:10]:
            print(f"    #{pid} {nm}: {reason}")
    if plan['purify_kept_for_combat']:
        print(f"  Purify kept for combat (all candidates are PVP/level keepers): {len(plan['purify_kept_for_combat'])}")
        for pid, nm, reason in plan['purify_kept_for_combat'][:30]:
            print(f"    #{pid} {nm}: {reason}")

    if args.dry_run:
        print('\n(--dry-run; no server writes)')
        return

    # Collect ALL UIDs that need protos (for adds AND untags)
    all_uids_dec = set()
    for tag in diff:
        for uh in diff[tag]['to_tag']:    all_uids_dec.add(_uid_dec(uh))
        for uh in diff[tag]['to_untag']:  all_uids_dec.add(_uid_dec(uh))
    if not all_uids_dec:
        print('\nNothing to change.')
        return

    # Snapshot DB
    stamp = time.strftime('%Y-%m-%d_%H%M%S')
    snap = os.path.join(HERE, '.db_snapshots', f'pokemon.db.{stamp}.pre_refined_tags.bak')
    os.makedirs(os.path.dirname(snap), exist_ok=True)
    shutil.copy2(DB, snap)
    print(f'\nSnapshot: {snap}')

    # ---- Frida session ----
    print(f'\n=== Attaching to PoGo ===')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')

    try:
        # PokemonBagImpl + TaggingRpcService liveness sometimes returns 2 instances
        # (the real one + a stale proxy). Probe each and pick the working one.
        # Bag: walk get_AllPokemon, take >100 entries.
        # Svc: call get_NumberOfTags, take 0<n<200.
        helper = pg.get_script_with_helpers(sess)
        try:
            r = helper.exports_sync.find_singleton('Niantic.Holoholo.Internal', 'PokemonBagImpl')
            bag_hits = r.get('hits', [])
            if len(bag_hits) == 1:
                bag = bag_hits[0]
            else:
                best, best_n = None, -1
                for c in bag_hits:
                    try:
                        n = len(helper.exports_sync.bag_walk(c))
                        print(f'  bag candidate {c}: {n} entries')
                        if n > best_n: best, best_n = c, n
                    except Exception as e:
                        print(f'  bag candidate {c}: walk failed ({e})')
                if best_n < 100:
                    raise RuntimeError(f'No PokemonBagImpl with >100 entries (best={best_n})')
                bag = best
        finally:
            helper.unload()

        # Probe svc via get_NumberOfTags
        SVC_PROBE_JS = r"""
        rpc.exports.probeNumberOfTags = function(addr) {
            _ensureInit();
            var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
            var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
            var m, gnt = null;
            while ((m = IL2.cGM(svcCls, iter)) && !m.isNull()) {
                if (IL2.mGN(m).readCString() === 'get_NumberOfTags') { gnt = m; break; }
            }
            try {
                var ret = rI(gnt, ptr(addr), ptr(0), null);
                var n = ret.add(0x10).readS32();
                return {ok:true, n: n};
            } catch(e) { return {ok:false, err: e.toString()}; }
        };
        """
        helper2 = pg.get_script_with_helpers(sess, SVC_PROBE_JS)
        try:
            r = helper2.exports_sync.find_singleton('Niantic.Holoholo.Tagging', 'TaggingRpcService')
            svc_hits = r.get('hits', [])
            if len(svc_hits) == 1:
                svc = svc_hits[0]
            else:
                best, best_n = None, -1
                for c in svc_hits:
                    try:
                        pr = helper2.exports_sync.probe_number_of_tags(c)
                        n = pr.get('n', -1) if pr.get('ok') else -1
                        print(f'  svc candidate {c}: NumberOfTags={n}')
                        if 0 < n < 200 and n > best_n: best, best_n = c, n
                    except Exception as e:
                        print(f'  svc candidate {c}: probe failed ({e})')
                if best is None:
                    raise RuntimeError(f'No TaggingRpcService with plausible NumberOfTags')
                svc = best
        finally:
            helper2.unload()
        print(f'  bag @ {bag}\n  svc @ {svc}')
        proto_map = pg.find_protos_for_uids(sess, bag, sorted(all_uids_dec))
        print(f'  bag-walk resolved {len(proto_map)}/{len(all_uids_dec)} protos')
        bt = sess.create_script(open(BULK_TAG_JS, encoding='utf-8').read())
        bt.on('message', lambda m, d: None)
        bt.load()
        bt.exports_sync.init_status()

        # Find existing tag protos (tags already exist; we just need their addresses)
        tag_protos = {}
        for cfg in TAGS:
            ftid = bt.exports_sync.find_tag_id_by_name(svc, cfg['name'])
            if ftid.get('ok'):
                tag_protos[cfg['name']] = ftid['tagProtoAddr']
                print(f"  tagProto {cfg['name']!r} @ {ftid['tagProtoAddr']}")
            else:
                print(f"  ! tag {cfg['name']!r} not found: {ftid}")

        # Apply changes per tag
        applied_tag = {n: [] for n in tag_protos}
        applied_untag = {n: [] for n in tag_protos}
        for name in tag_protos:
            tagproto = tag_protos[name]
            d = diff[name]

            # Untag stale
            if d['to_untag']:
                print(f"\n=== {name}: untagging {len(d['to_untag'])} stale ===")
                for uh in d['to_untag']:
                    pp = proto_map.get(_uid_dec(uh))
                    if pp is None:
                        print(f"  SKIP {uh}: no proto resolved (likely transferred/evolved out)")
                        continue
                    res = bt.exports_sync.bulk_untag_one(svc, pp, tagproto)
                    if res.get('ok'):
                        applied_untag[name].append(uh)
                    else:
                        print(f"  ! {uh}: {res}")
                    time.sleep(0.3)
                print(f"  untagged: {len(applied_untag[name])}/{len(d['to_untag'])}")

            # Tag new
            if d['to_tag']:
                uids_ord = list(d['to_tag'])
                protos = [proto_map.get(_uid_dec(uh)) for uh in uids_ord]
                pairs = [(u, p) for u, p in zip(uids_ord, protos) if p is not None]
                valid_uids = [u for u,_ in pairs]
                valid_protos = [p for _,p in pairs]
                if valid_protos:
                    print(f"\n=== {name}: tagging {len(valid_protos)} ===")
                    BATCH = 100
                    i = 0
                    while i < len(valid_protos):
                        cu = valid_uids[i:i+BATCH]
                        cp = valid_protos[i:i+BATCH]
                        r = bt.exports_sync.bulk_tag_many(svc, tagproto, cp)
                        if r.get('ok') and r.get('built', 0) == len(cp):
                            applied_tag[name].extend(cu)
                            print(f"  ok {i}-{i+len(cp)} built={r.get('built')}")
                        else:
                            print(f"  ! batch {i}: {r}")
                        i += BATCH
                        if i < len(valid_protos): time.sleep(0.6)

        bt.unload()
    finally:
        sess.detach()

    # Mirror to DB
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    for name in tag_protos:
        for uh in applied_tag[name]:
            cur = c.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
            tags = [t for t in (cur[0] or '').split(';') if t]
            if name not in tags: tags.append(name)
            c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?", (';'.join(tags), uh))
        for uh in applied_untag[name]:
            cur = c.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
            tags = [t for t in (cur[0] or '').split(';') if t and t != name]
            c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                      (';'.join(tags) if tags else None, uh))
    conn.commit()
    conn.close()

    # Summary
    print(f'\n=== Summary ===')
    for name in tag_protos:
        nt = len(applied_tag[name]); nu = len(applied_untag[name])
        print(f"  {name:<16}  +{nt}  -{nu}")


if __name__ == '__main__':
    main()
