"""Per-specimen classifier — every in-bag pokemon gets a row with every keep-axis
computed and a recommended decision. No hand-waving; each specimen is tailored.

Outputs:
  rescan_report/specimen_classification.csv  — one row per in-bag pokemon
  rescan_report/specimen_classification.md   — grouped summary by decision

Decisions:
  TRANSFER          — zero keep-axes + no dex-fill action available
  KEEP-meta         — high PVP rank (gl/ul/ll <=10) or current active best buddy
  KEEP-collector    — has hundo / shiny / shadow / legendary / mythical / UB / paradox /
                      mega-ever / Gmax form / Adventure-Effect species / costume /
                      location-card / Showcase Strong / XXL/XXS / lucky / nickname /
                      favorite / from special OT / Forever-Friends remote-tradable
  EVOLVE-shiny      — shiny in bag + reachable target with missing shiny medal
                      (gender/form/trade aware)
  EVOLVE-shadow     — shadow in bag + reachable target with missing shadow medal
                      (form/trade aware)
  PURIFY            — shadow with no Purified medal yet + not a combat keeper
                      (level<30, gl/ul rank>15)
  LUCKY-TRADE       — caught species without Lucky medal yet (trade once with a friend)
"""
import json, os, re, sqlite3
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
DEX = os.path.join(HERE, 'dex_deep_full.json')
GM = os.path.join(HERE, 'pvpoke_gamemaster.json')
FORM_ENUM = os.path.join(HERE, 'form_enum.json')
REPORT_DIR = os.path.join(HERE, 'rescan_report')

# Same evolution-feasibility rules as _tag_dex_review.py — kept in sync via copy
REGION_LOCKED_TARGETS = {
    900: 'hisuian', 901: 'hisuian', 902: 'hisuian', 903: 'hisuian', 904: 'hisuian',
    862: 'galarian', 864: 'galarian', 865: 'galarian', 866: 'galarian', 867: 'galarian',
}
GENDER_LOCKED_TARGETS = {416: 2, 758: 2}  # Vespiquen, Salazzle
TRADE_ONLY_TARGETS_FROM_SHADOW = {526, 534, 589, 617}  # Gigalith, Conkeldurr, Escavalier, Accelgor


def has_cat(entry, cat):
    return any(c['cat'] == cat and c['acq'] for c in entry.get('cats', []))


def build_pid_data():
    gm = json.load(open(GM, encoding='utf-8'))
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


def filter_targets(pid, region, gender, is_shadow, pid_to_targets):
    """Returns set of reachable targets actually achievable from this specimen."""
    out = set()
    for tgt in reachable_targets(pid, pid_to_targets):
        req_region = REGION_LOCKED_TARGETS.get(tgt)
        if req_region and req_region != region: continue
        req_gender = GENDER_LOCKED_TARGETS.get(tgt)
        if req_gender and gender != req_gender: continue
        if is_shadow and tgt in TRADE_ONLY_TARGETS_FROM_SHADOW: continue
        out.add(tgt)
    return out


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    dex = json.load(open(DEX, encoding='utf-8'))
    all_entries = {e['pid']: e for e in dex['All']}
    pid_to_name, pid_to_targets = build_pid_data()

    shiny_have = {p for p, e in all_entries.items() if has_cat(e, 11)}
    shadow_have = {p for p, e in all_entries.items() if has_cat(e, 15)}
    purified_have = {p for p, e in all_entries.items() if has_cat(e, 16)}
    lucky_have = {p for p, e in all_entries.items() if has_cat(e, 12)}

    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT uid_hex, pokemon_id, species_name, form, form_region, gender, "
        "       cp, level, iv_atk, iv_def, iv_sta, iv_total, "
        "       is_shiny, fresh_shiny, fresh_alignment, alignment_name, is_purified_flag, "
        "       is_lucky, is_best_buddy, was_best_buddy_badge, is_deployed, "
        "       is_three_star, is_four_star, is_zero, "
        "       is_legendary, is_mythical, is_ultra_beast, is_paradox, "
        "       can_mega_evolve, is_gigantamax_capable, is_adventure_effect_species, "
        "       fresh_pokemon_badge, fresh_costume, fresh_has_location_card, fresh_is_strong, "
        "       fresh_bread_mode, fresh_current_temp_evolution, fresh_has_mega_level, has_mega_evolved, "
        "       adventure_effects_left, pokemon_size_category, "
        "       gl_rank, ul_rank, ll_rank, "
        "       original_owner_name, nickname, favorite, marked_remote_tradable, "
        "       auth_tag_names, cull_decision_v9, cull_reason_v9 "
        "FROM pokemon WHERE in_bag=1 ORDER BY pokemon_id, iv_total DESC, cp DESC"
    ).fetchall()
    conn.close()

    # Group by (pid, alignment) → for "best of bucket" determination
    by_bucket = defaultdict(list)
    for r in rows:
        key = (r['pokemon_id'], r['fresh_alignment'] or 0, r['form'] or 0)
        by_bucket[key].append(r['uid_hex'])

    # Identify lucky trade candidates per species (one per species without lucky medal)
    lucky_target_pids = set(r['pokemon_id'] for r in rows) - lucky_have
    # Identify best non-lucky specimen per species (recommend for lucky-trade)
    best_for_lucky_trade = {}
    for r in rows:
        if r['is_lucky']: continue
        if r['pokemon_id'] not in lucky_target_pids: continue
        cur = best_for_lucky_trade.get(r['pokemon_id'])
        if cur is None or (r['iv_total'] or 0) > (cur['iv_total'] or 0):
            best_for_lucky_trade[r['pokemon_id']] = r

    # Per (pid, alignment) — identify the single best-IV shiny / shadow for evo
    best_shiny_per_pid = {}
    best_shadow_per_pid = {}
    for r in rows:
        if r['fresh_shiny']:
            cur = best_shiny_per_pid.get(r['pokemon_id'])
            if cur is None or (r['iv_total'] or 0) > (cur['iv_total'] or 0):
                best_shiny_per_pid[r['pokemon_id']] = r
        if (r['fresh_alignment'] or 0) == 1:
            cur = best_shadow_per_pid.get(r['pokemon_id'])
            if cur is None or (r['iv_total'] or 0) > (cur['iv_total'] or 0):
                best_shadow_per_pid[r['pokemon_id']] = r

    # Lowest-IV shadow per pid (purify candidate)
    lowest_shadow_per_pid = {}
    for r in rows:
        if (r['fresh_alignment'] or 0) != 1: continue
        cur = lowest_shadow_per_pid.get(r['pokemon_id'])
        if cur is None or (r['iv_total'] or 999) < (cur['iv_total'] or 999):
            lowest_shadow_per_pid[r['pokemon_id']] = r

    # ---- Classify per specimen ----
    classifications = []
    for r in rows:
        keep_axes = []
        actions = []

        pid = r['pokemon_id']; iv = r['iv_total'] or 0
        region = r['form_region'] or 'kantonian'
        gender = r['gender']
        is_shiny = bool(r['fresh_shiny'])
        is_shadow = (r['fresh_alignment'] or 0) == 1
        is_purified = (r['fresh_alignment'] or 0) == 2

        # KEEP AXES
        if r['is_four_star']: keep_axes.append('hundo')
        if r['is_zero']:      keep_axes.append('nundo')
        if is_shiny:           keep_axes.append('shiny')
        if r['is_lucky']:      keep_axes.append('lucky')
        if r['was_best_buddy_badge']: keep_axes.append('best_buddy_badge')
        if r['is_best_buddy'] and (r['cp'] or 0) > 100:
            # is_best_buddy is over-broad (additional_cpm); only meaningful for invested specimens
            keep_axes.append('best_buddy_cpm')
        if r['is_deployed']:   keep_axes.append('deployed_in_gym')
        if is_shadow:          keep_axes.append('shadow')
        if is_purified:        keep_axes.append('purified')
        if r['is_legendary']:  keep_axes.append('legendary')
        if r['is_mythical']:   keep_axes.append('mythical')
        if r['is_ultra_beast']:keep_axes.append('ultra_beast')
        if r['is_paradox']:    keep_axes.append('paradox')
        if r['fresh_has_location_card']: keep_axes.append('location_card')
        if r['fresh_costume']: keep_axes.append('costume')
        if r['fresh_is_strong']: keep_axes.append('showcase_strong')
        if r['fresh_bread_mode']: keep_axes.append('dynamax_form')
        if r['fresh_pokemon_badge'] and r['fresh_pokemon_badge'] != 0:
            keep_axes.append(f'badge_{r["fresh_pokemon_badge"]}')
        if r['fresh_current_temp_evolution']: keep_axes.append('mega_active')
        if r['fresh_has_mega_level']: keep_axes.append('has_mega_level')
        if r['has_mega_evolved']: keep_axes.append('mega_evolved_ever')
        if (r['adventure_effects_left'] or 0) > 0:
            keep_axes.append(f'adventure_effect_uses_{r["adventure_effects_left"]}')
        if (r['pokemon_size_category'] or 0) == 5: keep_axes.append('XXL')
        if (r['pokemon_size_category'] or 0) == 1: keep_axes.append('XXS')
        if r['gl_rank'] is not None and r['gl_rank'] <= 10:
            keep_axes.append(f'gl_top10_rank{r["gl_rank"]}')
        if r['ul_rank'] is not None and r['ul_rank'] <= 10:
            keep_axes.append(f'ul_top10_rank{r["ul_rank"]}')
        if r['ll_rank'] is not None and r['ll_rank'] <= 10:
            keep_axes.append(f'll_top10_rank{r["ll_rank"]}')
        if r['original_owner_name']:
            owner = r['original_owner_name'].lower()
            if owner in ('florandez', 'ethanmateovz'):
                keep_axes.append(f'OT_{owner}')
            else:
                keep_axes.append(f'OT_traded')
        if r['nickname']:    keep_axes.append('nicknamed')
        if r['favorite']:    keep_axes.append('favorite')
        if r['marked_remote_tradable']: keep_axes.append('FF_remote_tradable')
        # Top of (pid, alignment, form) bucket — best representative
        bucket_uids = by_bucket[(pid, r['fresh_alignment'] or 0, r['form'] or 0)]
        # Find rank in bucket by iv_total / cp
        ranked = sorted(bucket_uids,
                        key=lambda u: ((-(next(rr for rr in rows if rr['uid_hex']==u)['iv_total'] or 0),
                                        -(next(rr for rr in rows if rr['uid_hex']==u)['cp'] or 0))))
        try:
            bucket_rank = ranked.index(r['uid_hex']) + 1
        except ValueError:
            bucket_rank = -1
        if bucket_rank == 1:
            keep_axes.append('best_of_bucket')

        # ACTION ITEMS
        # Evolve for shiny dex
        if is_shiny and best_shiny_per_pid.get(pid, {}).get('uid_hex') == r['uid_hex'] if isinstance(best_shiny_per_pid.get(pid), dict) else False:
            pass  # placeholder — recompute below
        # Cleaner: evaluate evolve eligibility directly
        targets = filter_targets(pid, region, gender, is_shadow, pid_to_targets)
        missing_shiny_targets   = sorted(t for t in targets if t not in shiny_have)  if is_shiny  else []
        missing_shadow_targets  = sorted(t for t in targets if t not in shadow_have) if is_shadow else []
        if is_shiny and missing_shiny_targets:
            # Only the best shiny per pid gets the action
            if best_shiny_per_pid.get(pid) and best_shiny_per_pid[pid]['uid_hex'] == r['uid_hex']:
                actions.append('EVOLVE-shiny→' + ','.join(f'#{t}' for t in missing_shiny_targets))
        if is_shadow and missing_shadow_targets:
            if best_shadow_per_pid.get(pid) and best_shadow_per_pid[pid]['uid_hex'] == r['uid_hex']:
                actions.append('EVOLVE-shadow→' + ','.join(f'#{t}' for t in missing_shadow_targets))
        # Purify
        if is_shadow and pid in shadow_have and pid not in purified_have:
            # Only the lowest-IV shadow per pid AND not the evolve-pick AND not a combat keeper
            already_evo = best_shadow_per_pid.get(pid) and best_shadow_per_pid[pid]['uid_hex'] == r['uid_hex']
            lvl = r['level'] or 0
            gl = r['gl_rank']; ul = r['ul_rank']
            is_combat_keeper = (lvl >= 30) or (gl is not None and gl <= 15) or (ul is not None and ul <= 15)
            if (lowest_shadow_per_pid.get(pid) and
                lowest_shadow_per_pid[pid]['uid_hex'] == r['uid_hex'] and
                not already_evo and not is_combat_keeper):
                actions.append('PURIFY')
        # Lucky trade
        if (not r['is_lucky'] and pid in lucky_target_pids and
            best_for_lucky_trade.get(pid) and best_for_lucky_trade[pid]['uid_hex'] == r['uid_hex']):
            actions.append('TRADE-FOR-LUCKY')

        # DECISION — cull_v9.decision is authoritative for the KEEP/TRANSFER boundary
        # (bucket rules / shiny-chain / dex-gap protection live there). The classifier
        # adds finer granularity (meta vs collector) and surfaces ACTIONS.
        cull_dec = r['cull_decision_v9'] or 'KEEP'
        has_evolve_shiny = any(a.startswith('EVOLVE-shiny') for a in actions)
        has_evolve_shadow = any(a.startswith('EVOLVE-shadow') for a in actions)
        has_purify = 'PURIFY' in actions

        if cull_dec == 'TRANSFER':
            # Cull says transfer. Check if any action is still useful before final transfer.
            if has_evolve_shiny:    decision = 'EVOLVE-shiny'  # rare — would mean cull missed something
            elif has_evolve_shadow: decision = 'EVOLVE-shadow'
            elif has_purify:        decision = 'PURIFY'
            elif 'TRADE-FOR-LUCKY' in actions:
                decision = 'TRADE-FOR-LUCKY-THEN-TRANSFER'  # lucky-trade away, the lucky specimen is the keeper
            else:
                decision = 'TRANSFER'
        else:
            # Cull says keep. Surface meta vs collector + any actions.
            if has_evolve_shiny:    decision = 'EVOLVE-shiny'
            elif has_evolve_shadow: decision = 'EVOLVE-shadow'
            elif has_purify:        decision = 'PURIFY'
            elif any(a.startswith(('gl_top10','ul_top10','ll_top10')) for a in keep_axes):
                decision = 'KEEP-meta'
            elif 'best_buddy_cpm' in keep_axes:
                decision = 'KEEP-meta'
            else:
                decision = 'KEEP-collector'

        # Ambiguity: cases worth agent review
        ambiguous = 0
        if decision == 'TRANSFER':
            # Transfer set — always worth a verification pass (these get released)
            ambiguous = 1
        if decision == 'KEEP-collector' and len(keep_axes) == 1 and iv < 30 and not actions:
            ambiguous = 1
        if decision.startswith('EVOLVE') or decision == 'PURIFY':
            ambiguous = 1  # action specimens — confirm feasibility per specimen

        classifications.append({
            'uid_hex': r['uid_hex'],
            'pid': pid,
            'species': r['species_name'],
            'form': r['form'],
            'region': region,
            'gender': r['gender'],
            'iv': iv,
            'cp': r['cp'],
            'level': r['level'],
            'is_shiny': is_shiny,
            'alignment': r['alignment_name'],
            'keep_axes': keep_axes,
            'actions': actions,
            'decision': decision,
            'ambiguous': ambiguous,
            'cull_v9': r['cull_decision_v9'],
            'cull_reason_v9': r['cull_reason_v9'],
        })

    # Output
    out_csv = os.path.join(REPORT_DIR, 'specimen_classification.csv')
    with open(out_csv, 'w', encoding='utf-8') as f:
        f.write('uid_hex,pid,species,form,region,gender,iv,cp,level,is_shiny,alignment,'
                'keep_axes,actions,decision,ambiguous,cull_v9,cull_reason_v9\n')
        for x in classifications:
            row = [
                x['uid_hex'], str(x['pid']), x['species'], str(x['form']), x['region'],
                str(x['gender']), str(x['iv']), str(x['cp']), str(x['level']),
                '1' if x['is_shiny'] else '0', x['alignment'],
                '|'.join(x['keep_axes']),
                '|'.join(x['actions']),
                x['decision'],
                str(x['ambiguous']),
                x['cull_v9'] or '',
                (x['cull_reason_v9'] or '').replace(',', ';'),
            ]
            f.write(','.join(s.replace(',', ';') if s else '' for s in row) + '\n')
    print(f'Wrote {out_csv}')

    # Summary by decision
    from collections import Counter
    dec_counts = Counter(x['decision'] for x in classifications)
    print(f'\n=== Decision distribution ===')
    for d, n in sorted(dec_counts.items(), key=lambda kv: -kv[1]):
        amb = sum(1 for x in classifications if x['decision']==d and x['ambiguous'])
        print(f'  {d:18s} {n:>5}  (ambiguous: {amb})')

    print(f'\n=== Examples per decision (top 3 each) ===')
    for d, _ in sorted(dec_counts.items(), key=lambda kv: -kv[1]):
        ex = [x for x in classifications if x['decision'] == d][:3]
        for x in ex:
            print(f'  [{d:14s}] #{x["pid"]:4d} {x["species"]:14s} iv={x["iv"]:>2} cp={x["cp"]:>4} '
                  f'axes={x["keep_axes"][:5]} actions={x["actions"]}')


if __name__ == '__main__':
    main()
