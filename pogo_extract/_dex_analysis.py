"""Dex-completion analysis.

Joins:
  dex_deep_full.json     - per-region per-pid per-category dex flags
  pokemon.db             - current bag (read-only)
  pvpoke_gamemaster.json - evolution chains + pid↔name

Produces three answers:
  Q1  Shinies in bag that could be evolved to fill a Shiny dex gap
  Q2  Hundos missing from each regional dex (Kanto..Paldea)
  Q3  Shadows in bag that could be evolved to fill a Shadow dex gap

MapField key audit (2026-05-27) shows category status is species-level
('SHINY' / 'FOUR_STAR' / 'SHADOW' keys, not per-form). Regional variants
get their own regional-dict entry per pid, so per-form acquired tracking
lives in the *regional* dicts; the All dict is the species-level union.
Q2 uses regional dicts directly; Q1/Q3 use the All-dict species-level union
(shiny Eevee evolutions span multiple gens, so within-region eval would miss
Espeon→Johto and Leafeon→Sinnoh; species-level is the right grain).
"""
import json, os, sqlite3, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DEX = os.path.join(HERE, 'dex_deep_full.json')
DB  = os.path.join(HERE, 'pokemon.db')
GM  = os.path.join(HERE, 'pvpoke_gamemaster.json')
REPORT_DIR = os.path.join(HERE, 'rescan_report')
OUT = os.path.join(REPORT_DIR, 'dex_completion.md')

CAT_SHINY = 11
CAT_FOURSTAR = 14   # hundo
CAT_SHADOW = 15

REGIONS_ORDERED = ['Kanto', 'Johto', 'Hoenn', 'Sinnoh', 'Unova',
                   'Kalos', 'Alola', 'Galar', 'Paldea']


def has_cat(entry, cat):
    return any(c['cat'] == cat and c['acq'] for c in entry.get('cats', []))


def load_dex():
    return json.load(open(DEX, 'r', encoding='utf-8'))


def build_pid_data():
    """From pvpoke gamemaster: pid -> display name, pid -> set(target_pids).

    `family.evolutions` lists DIRECT next-stage speciesIds; we compute reachable
    via transitive closure later. We collapse all speciesId forms onto their
    parent dex pid (intentional — Q1/Q3 are species-level).
    """
    import re
    gm = json.load(open(GM, 'r', encoding='utf-8'))
    sid_to_dex = {}
    for x in gm['pokemon']:
        sid = x.get('speciesId')
        dex = x.get('dex')
        if sid is None or dex is None:
            continue
        sid_to_dex[sid] = dex

    # Two passes for pid->name: prefer entries with no parenthetical (clean base
    # name); fall back to stripping parenthetical from any non-shadow entry.
    # This covers pids whose every pvpoke entry is a form variant (Giratina,
    # Therian trio, Meowstic, Aegislash, Zygarde, Morpeko, Urshifu, etc.).
    pid_to_name = {}
    for x in gm['pokemon']:
        sid = x.get('speciesId', '')
        dex = x.get('dex')
        nm = x.get('speciesName', '') or ''
        if dex is None or '_shadow' in sid:
            continue
        if '(' not in nm and dex not in pid_to_name:
            pid_to_name[dex] = nm
    for x in gm['pokemon']:
        sid = x.get('speciesId', '')
        dex = x.get('dex')
        nm = x.get('speciesName', '') or ''
        if dex is None or '_shadow' in sid or dex in pid_to_name:
            continue
        clean = re.sub(r'\s*\([^)]*\)\s*', '', nm).strip()
        if clean:
            pid_to_name[dex] = clean

    pid_to_targets = defaultdict(set)
    for x in gm['pokemon']:
        sid = x.get('speciesId', '')
        if '_shadow' in sid:
            continue
        src = x.get('dex')
        if src is None:
            continue
        for ev in (x.get('family') or {}).get('evolutions') or []:
            tgt = sid_to_dex.get(ev)
            if tgt is not None and tgt != src:
                pid_to_targets[src].add(tgt)
    return pid_to_name, dict(pid_to_targets)


def reachable(pid, pid_to_targets):
    """Transitive evolution targets from pid."""
    seen = set()
    stack = [pid]
    while stack:
        cur = stack.pop()
        for tgt in pid_to_targets.get(cur, ()):
            if tgt in seen:
                continue
            seen.add(tgt)
            stack.append(tgt)
    return seen


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    dex = load_dex()
    all_entries = {e['pid']: e for e in dex.get('All', [])}
    pid_to_name, pid_to_targets = build_pid_data()

    # Species-level "ever acquired" sets from All dict.
    shiny_have  = {p for p, e in all_entries.items() if has_cat(e, CAT_SHINY)}
    hundo_have  = {p for p, e in all_entries.items() if has_cat(e, CAT_FOURSTAR)}
    shadow_have = {p for p, e in all_entries.items() if has_cat(e, CAT_SHADOW)}
    print(f"Lifetime totals (All dict, n={len(all_entries)}):")
    print(f"  Shiny: {len(shiny_have)}   Hundo: {len(hundo_have)}   Shadow: {len(shadow_have)}")

    # Bag
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    shiny_bag = conn.execute(
        "SELECT pokemon_id, species_name, form, cp, iv_total, uid_hex "
        "FROM pokemon WHERE in_bag=1 AND fresh_shiny=1"
    ).fetchall()
    shadow_bag = conn.execute(
        "SELECT pokemon_id, species_name, form, cp, iv_total, uid_hex "
        "FROM pokemon WHERE in_bag=1 AND fresh_alignment=1"
    ).fetchall()
    conn.close()
    print(f"Bag: shiny={len(shiny_bag)}  shadow={len(shadow_bag)}")

    # ---- Q1: Shiny evolve-to-fill ----
    q1 = []
    by_pid = defaultdict(list)
    for r in shiny_bag:
        by_pid[r['pokemon_id']].append(r)
    for src_pid in sorted(by_pid):
        owners = by_pid[src_pid]
        targets = reachable(src_pid, pid_to_targets)
        missing = sorted(t for t in targets if t not in shiny_have)
        if not missing:
            continue
        owners.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        q1.append({
            'src_pid': src_pid,
            'src_name': pid_to_name.get(src_pid, f'pid{src_pid}'),
            'count': len(owners),
            'best': owners[0],
            'missing': [(t, pid_to_name.get(t, f'pid{t}')) for t in missing],
        })

    # ---- Q2: Regional hundos missing ----
    q2 = {}
    q2_global = 0
    for region in REGIONS_ORDERED:
        entries = {e['pid']: e for e in dex.get(region, [])}
        missing = []
        for pid in sorted(entries):
            if not has_cat(entries[pid], CAT_FOURSTAR):
                missing.append((pid, pid_to_name.get(pid, f'pid{pid}')))
        q2[region] = missing
        q2_global += len(missing)

    # ---- Q3: Shadow evolve-to-fill ----
    q3 = []
    by_pid_s = defaultdict(list)
    for r in shadow_bag:
        by_pid_s[r['pokemon_id']].append(r)
    for src_pid in sorted(by_pid_s):
        owners = by_pid_s[src_pid]
        targets = reachable(src_pid, pid_to_targets)
        missing = sorted(t for t in targets if t not in shadow_have)
        if not missing:
            continue
        owners.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        q3.append({
            'src_pid': src_pid,
            'src_name': pid_to_name.get(src_pid, f'pid{src_pid}'),
            'count': len(owners),
            'best': owners[0],
            'missing': [(t, pid_to_name.get(t, f'pid{t}')) for t in missing],
        })

    # ---- write report ----
    L = []
    L.append('# Dex Completion Scan — 2026-05-27\n')
    L.append(f'Live PokedexImpl read: {sum(len(v) for v in dex.values())} (region, pid) entries.\n')
    L.append('**Lifetime totals (All dict):**\n')
    L.append(f'- Caught (any):  {len(all_entries)}')
    L.append(f'- Shiny ever:    {len(shiny_have)}')
    L.append(f'- Hundo ever:    {len(hundo_have)}')
    L.append(f'- Shadow ever:   {len(shadow_have)}')
    L.append('')

    L.append('## Q1 — Shinies you own that could fill a Shiny dex gap\n')
    if not q1:
        L.append('_None — every shiny you own already covers the Shiny dex for its evolution targets._\n')
    else:
        L.append(f'{len(q1)} owned-shiny species → at least one evolution target has no Shiny dex entry.\n')
        L.append('| Source (shiny owned) | Cnt | Best IV/CP | Missing shiny dex slots if you evolve |')
        L.append('|---|---:|---|---|')
        for x in q1:
            best = x['best']
            miss = ', '.join(f'`#{p}` {nm}' for p, nm in x['missing'])
            L.append(f"| `#{x['src_pid']}` {x['src_name']} | {x['count']} | "
                     f"{best['iv_total']}/45 cp{best['cp']} | {miss} |")
        L.append('')

    L.append('## Q2 — Hundos missing from each regional dex\n')
    L.append(f'{q2_global} regional hundo slots are unfilled across the 9 regional dexes.\n')
    for region in REGIONS_ORDERED:
        m = q2[region]
        total = len(dex.get(region, []))
        have = total - len(m)
        L.append(f'### {region} — {have}/{total} hundos collected, **{len(m)} missing**')
        if not m:
            L.append('_Region complete._')
        else:
            L.append('')
            L.append(', '.join(f'`#{p}` {nm}' for p, nm in m))
        L.append('')

    L.append('## Q3 — Shadows you own that could fill a Shadow dex gap\n')
    if not q3:
        L.append('_None — every shadow you own already covers the Shadow dex for its evolution targets._\n')
    else:
        L.append(f'{len(q3)} owned-shadow species → at least one evolution target has no Shadow dex entry.\n')
        L.append('| Source (shadow owned) | Cnt | Best IV/CP | Missing shadow dex slots if you evolve |')
        L.append('|---|---:|---|---|')
        for x in q3:
            best = x['best']
            miss = ', '.join(f'`#{p}` {nm}' for p, nm in x['missing'])
            L.append(f"| `#{x['src_pid']}` {x['src_name']} | {x['count']} | "
                     f"{best['iv_total']}/45 cp{best['cp']} | {miss} |")
        L.append('')

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))

    # Console summary
    print(f"\nWrote {OUT}")
    print(f"  Q1 (shiny evo gaps): {len(q1)} source species")
    for region in REGIONS_ORDERED:
        m = q2[region]; tot = len(dex.get(region, []))
        print(f"  Q2 {region:7s}: {tot-len(m):>3}/{tot} hundos collected, {len(m):>3} missing")
    print(f"  Q3 (shadow evo gaps): {len(q3)} source species")


if __name__ == '__main__':
    main()
