"""verify_kanto_cull.py -- INDEPENDENT verification of the 80-agent Kanto cull plan.

The Kanto cleanup workflow wrote system/analysis/kanto_cull_plan.json (287 {uid,species,reason}).
Those picks came from LLM agents -- the same class of thing that produced false-positives earlier
this session (Eevee dex_only, Pikachu stale-event). The cull list feeds the ONE irreversible output,
so before ANY of it is presented as "approve this" it gets re-verified from scratch here.

Two independent lenses, neither trusting the agents:
  (A) RAW-COLUMN keep-axis re-derivation -- reuse preflight_transfer._keeper_reasons (hundo/nundo/
      lucky/legendary/best_buddy/traded/legacy/event/mighty/adventure_effect/pvp_spread/dex_only/
      gl|ul rank<=5-viable) + cap-aware shiny(top-20)/costume(top-4)/XXL(top-2h+1w) + LIVE gym read.
  (B) keep_policy's OWN keep map (policy_reasons.json) -- the hardened engine. If it KEEPS a uid the
      agents want to cull, that's a conflict.

Each cull uid lands in exactly one verdict:
  ALARM_SACRED   -- earns an UNCONDITIONAL keep axis (A) or policy keeps it for a sacred reason.
                    The agents were WRONG. Pull it OUT. (exit 1)
  ALARM_WITHINCAP-- a shiny/costume/XXL that is INSIDE its cap (a real keeper, not excess). Pull OUT.
  BEYOND_POLICY  -- no sacred axis, but keep_policy KEEPS it for a cap/curation reason
                    (variant_floor=top-3 plain / dex_only / pvp_rank / evolve). Culling it is MORE
                    aggressive than the standing rules -> needs the user's explicit sign-off.
  GYM_LOCKED     -- live-deployed; can't be transferred anyway (reported, safe).
  STALE          -- uid no longer in_bag / not in DB (can't verify; exclude from action).
  ALIGNED        -- keep_policy ALSO transfers it AND no sacred axis. Safe, uncontroversial cull.

Prints a full report + writes system/analysis/kanto_cull_verify.json with the per-uid verdicts.
Frida is serial -- run ALONE.
"""
import os, sys, json, sqlite3
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import preflight_transfer as pf   # reuse the VALIDATED helpers (keeper derivation, caps, live gym read)

DB = os.path.join(ROOT, 'pokemon.db')
PLAN = os.path.join(ROOT, 'system', 'analysis', 'kanto_cull_plan.json')
POLICY = os.path.join(ROOT, 'system', 'analysis', 'policy_reasons.json')
OUT = os.path.join(ROOT, 'system', 'analysis', 'kanto_cull_verify.json')

# keep_policy reasons split by KIND. Sacred = unconditional keep-all / special; if policy keeps a
# cull-target for ANY of these, the agents are wrong. Cap = top-N curation; culling past it is the
# user's call (BEYOND_POLICY), not an automatic alarm.
SACRED_REASONS = {'hundo', 'nundo', 'lucky', 'origin', 'legacy', 'location_card',
                  'mighty', 'adventure_effect', 'rarity', 'protected', 'shadow_best', 'pvp_spread',
                  'gl_iv', 'ul_iv', 'pvp_rank'}   # best_buddy retired 2026-06-07
CAP_REASONS = {'variant_floor', 'shiny', 'xxl', 'dex_only_copy',
               'evolve_1', 'evolve_2', 'evolve_3'}


def main():
    plan = json.load(open(PLAN, encoding='utf-8'))
    cull_uids = [e['uid'] for e in plan]
    cull_sp = {e['uid']: e.get('species', '?') for e in plan}
    cull_reason = {e['uid']: e.get('reason', '') for e in plan}
    n_dupe = len(cull_uids) - len(set(cull_uids))
    cull_uids = list(dict.fromkeys(cull_uids))           # dedupe, keep order

    policy = {}
    if os.path.exists(POLICY):
        policy = json.load(open(POLICY, encoding='utf-8'))   # uid -> [reasons]

    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    bag = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
    bagmap = {r['uid_hex']: r for r in bag}

    # ---- cap contexts over the WHOLE bag (a cap is judged against every copy, not the cull subset) ----
    dex_counts = defaultdict(int)
    for r in bag:
        dex_counts[r['pokemon_id']] += 1

    shiny_groups = defaultdict(list)
    for r in bag:
        if r['fresh_shiny']:
            shiny_groups[(r['pokemon_id'], r['form'] or 0)].append(r)
    shiny_kept = set()
    for lst in shiny_groups.values():
        for r in sorted(lst, key=pf._ivkey)[:pf.SHINY_CAP]:
            shiny_kept.add(r['uid_hex'])

    cos_groups = defaultdict(list)
    for r in bag:
        if pf._is_cosmetic(r):
            cos_groups[pf._cosmetic_variant_key(r)].append(r)
    cosmetic_kept = set()
    for key, lst in cos_groups.items():
        cap = pf.DMAX_CAP if key[-1] == 1 else pf.GMAX_CAP if key[-1] == 2 else pf.COSMETIC_CAP
        for r in sorted(lst, key=pf._ivkey)[:cap]:
            cosmetic_kept.add(r['uid_hex'])

    xxl_kept, xxl_groups = pf._xxl_kept_uids(bag)

    # gamemaster / legacy / event-legacy tagsets (fresh)
    BS, gm_ok = {}, False
    try:
        gm = json.load(open(pf.GAMEMASTER, encoding='utf-8'))
        BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
        gm_ok = True
    except Exception as e:
        print("WARN gamemaster load failed (%s) -- PvP-rank axis OVER-PROTECTS." % e)
    legacy_set = set()
    try:
        legacy_set = {e['uid_hex'] for e in json.load(open(pf.LEGACY_JSON, encoding='utf-8'))}
    except Exception as e:
        print("WARN legacy_accurate.json load failed (%s)." % e)

    def _load_ts(fn):
        try:
            with open(os.path.join(ROOT, 'system', 'analysis', 'tagsets', fn), encoding='utf-8') as f:
                return {ln.strip() for ln in f if ln.strip()}
        except FileNotFoundError:
            return set()
    event_txt = _load_ts('Event.txt')
    legacy_txt = _load_ts('Legacy_Moves.txt')
    transfer_txt = _load_ts('6_Transfer.txt') or _load_ts('Transfer.txt')

    # ---- LIVE deployment ----
    deployed, deploy_err = set(), None
    try:
        deployed = pf.live_deployed_uids()
    except Exception as e:
        deploy_err = e

    verdicts = {}          # uid -> dict
    buckets = defaultdict(list)

    for u in cull_uids:
        r = bagmap.get(u)
        if r is None:
            buckets['STALE'].append((u, '%s -- not in_bag / not in DB' % cull_sp.get(u)))
            verdicts[u] = {'verdict': 'STALE', 'species': cull_sp.get(u)}
            continue

        sp = r['species_name']
        preasons = policy.get(u, [])
        psacred = sorted(set(preasons) & SACRED_REASONS)
        pcap = sorted(set(preasons) & CAP_REASONS)

        unconditional = pf._keeper_reasons(r, BS, legacy_set, gm_ok, dex_counts, event_txt, legacy_txt)
        is_shiny = bool(r['fresh_shiny'])
        is_cos = pf._is_cosmetic(r)
        is_xxl = pf._is_xxl(r)
        within = []
        if is_shiny and u in shiny_kept:
            within.append('shiny(within top-%d)' % pf.SHINY_CAP)
        if is_cos and u in cosmetic_kept:
            within.append('costume(within top-%d)' % pf.COSMETIC_CAP)
        if is_xxl and u in xxl_kept:
            within.append('xxl(within showcase)')

        gym = u in deployed
        rec = {'species': sp, 'iv': r['iv_total'], 'ivspread': '%s/%s/%s' % (r['iv_atk'], r['iv_def'], r['iv_sta']),
               'policy_sacred': psacred, 'policy_cap': pcap, 'raw_axes': unconditional,
               'within_cap': within, 'gym': gym, 'in_policy_transfer': u in transfer_txt}

        # ---- verdict (priority order) ----
        if unconditional or psacred:
            v = 'ALARM_SACRED'
            buckets[v].append((u, '%s -- raw=[%s] policy_sacred=[%s]'
                               % (sp, ', '.join(unconditional), ', '.join(psacred))))
        elif within:
            v = 'ALARM_WITHINCAP'
            buckets[v].append((u, '%s -- %s' % (sp, ', '.join(within))))
        elif gym:
            v = 'GYM_LOCKED'
            buckets[v].append((u, '%s (deployed -> game blocks transfer; safe)' % sp))
        elif pcap:
            v = 'BEYOND_POLICY'
            buckets[v].append((u, '%s -- keep_policy keeps as [%s]; cull is beyond standing rules'
                               % (sp, ', '.join(pcap))))
        elif u in transfer_txt:
            v = 'ALIGNED'
            buckets[v].append((u, sp))
        else:
            # not kept by policy for any reason we mapped, but also not in the Transfer file -> odd.
            v = 'ALIGNED_UNLISTED'
            buckets[v].append((u, '%s -- not policy-kept, not in Transfer.txt (verify)' % sp))
        rec['verdict'] = v
        verdicts[u] = rec

    # ---- report ----
    print("=" * 80)
    print("KANTO CULL VERIFICATION -- %d uids (%d dupes removed)" % (len(cull_uids), n_dupe))
    print("PvP viability: %s | gamemaster=%s | legacy_set=%d" % (pf._VIABILITY_NOTE, gm_ok, len(legacy_set)))
    if deploy_err:
        print("!! LIVE DEPLOYMENT FAILED: %s -- gym-locked cannot be cleared; re-run with Frida." % deploy_err)
    else:
        print("Live deployment: %d in gyms; %d of those are in the cull plan." % (len(deployed), len(deployed & set(cull_uids))))
    print("-" * 80)
    order = ['ALIGNED', 'BEYOND_POLICY', 'GYM_LOCKED', 'STALE', 'ALIGNED_UNLISTED',
             'ALARM_WITHINCAP', 'ALARM_SACRED']
    for cls in order:
        print("  %-18s %4d" % (cls, len(buckets.get(cls, []))))
    print("-" * 80)

    for cls in ['ALARM_SACRED', 'ALARM_WITHINCAP', 'BEYOND_POLICY', 'GYM_LOCKED', 'STALE', 'ALIGNED_UNLISTED']:
        if buckets.get(cls):
            print("\n### %s (%d):" % (cls, len(buckets[cls])))
            for u, lbl in buckets[cls]:
                print("    %s  %s" % (u, lbl))

    json.dump(verdicts, open(OUT, 'w', encoding='utf-8'), indent=1)
    print("\nwrote %s" % os.path.relpath(OUT, ROOT))

    alarms = len(buckets.get('ALARM_SACRED', [])) + len(buckets.get('ALARM_WITHINCAP', []))
    if alarms:
        print("\n!! VERIFY FAIL: %d agent cull-pick(s) are real keepers -> exclude before any action." % alarms)
        sys.exit(1)
    print("\nVERIFY: no sacred keeper in the cull plan. BEYOND_POLICY picks still need explicit user OK.")


if __name__ == '__main__':
    main()
