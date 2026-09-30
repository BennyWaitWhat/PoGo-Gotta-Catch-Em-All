"""doctor.py -- read-only health check for the PoGo curation toolkit.

Reports:
  1. DB file age + live-vs-DB bag freshness (offline, no Frida unless available)
  2. Server tags vs registry.json vs DB counts (drift detection)
  3. deep_profiles.json freshness + purpose coverage
  4. Known data-quality flags (phantom CanMega, Trade+COLLECTION, dup hundos)

Prints a PASS / WARN / FAIL summary per section and exits with:
  0 = all PASS
  1 = at least one WARN (no FAIL)
  2 = at least one FAIL

No writes to DB, no Frida tag mutations, no side effects.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
import os
import sqlite3
import time
from collections import defaultdict

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)

DB_PATH = os.path.join(_PROJECT_ROOT, 'pokemon.db')
REGISTRY_PATH = os.path.join(_PROJECT_ROOT, 'system', 'tags', 'registry.json')
DEEP_PROFILES_PATH = os.path.join(_PROJECT_ROOT, 'system', 'analysis', 'deep_profiles.json')
LEGACY_PATH = os.path.join(_PROJECT_ROOT, 'legacy_accurate.json')


def _fmt_age(seconds):
    """Human-readable age string."""
    if seconds < 0:
        return '(future mtime?)'
    if seconds < 60:
        return f'{seconds:.0f}s'
    if seconds < 3600:
        return f'{seconds / 60:.1f}m'
    if seconds < 86400:
        return f'{seconds / 3600:.1f}h'
    return f'{seconds / 86400:.1f}d'


def _file_age(path):
    """Return (age_seconds, mtime) or (None, None) if missing."""
    if not os.path.isfile(path):
        return None, None
    mt = os.path.getmtime(path)
    return time.time() - mt, mt


def _load_json(path):
    """Load JSON or return None on any error."""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


# ===== Section helpers =====================================================

def section_db_freshness(conn):
    """Section 1: DB file age + bag UID set sizes."""
    issues = []
    age_s, mtime = _file_age(DB_PATH)
    if age_s is None:
        return 'FAIL', ['pokemon.db not found']

    age_str = _fmt_age(age_s)
    mtime_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))
    print(f'  DB file age      : {age_str} ({mtime_str})')

    if age_s > 86400:
        issues.append(f'DB is {age_str} old (>24h)')

    row = conn.execute(
        "SELECT COUNT(*) FROM pokemon WHERE in_bag = 1"
    ).fetchone()
    in_bag = row[0] if row else 0
    total = conn.execute("SELECT COUNT(*) FROM pokemon").fetchone()[0]
    print(f'  DB rows          : {total} total, {in_bag} in_bag')

    if in_bag == 0:
        issues.append('in_bag count is 0 -- DB may be empty or stale')

    # Check for NULL cull decisions on in_bag rows
    null_cull = conn.execute(
        "SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v9 IS NULL"
    ).fetchone()[0]
    if null_cull > 0:
        issues.append(f'{null_cull} in_bag rows have NULL cull_decision_v9')

    # Try Frida freshness (graceful degrade)
    frida_status = _try_frida_freshness(conn)
    if frida_status is not None:
        for line in frida_status.get('lines', []):
            print(f'  {line}')
        issues.extend(frida_status.get('issues', []))
    else:
        print('  Frida freshness  : skipped (device/frida unavailable)')

    if not issues:
        return 'PASS', []
    severity = 'FAIL' if any('0 in_bag' in i or 'not found' in i for i in issues) else 'WARN'
    return severity, issues


def _try_frida_freshness(conn):
    """Attempt a Frida bag-walk to compare live vs DB UIDs. Returns dict or None."""
    try:
        from system.scripts import _frida_safe as fs
    except Exception:
        try:
            import _frida_safe as fs
        except Exception:
            return None

    try:
        sess, pid = fs.session(retries=2, backoff=1)
    except Exception:
        return None

    lines = []
    issues = []
    try:
        bag_addr = fs.pick(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        import pogo_il2cpp as pg
        live_map = pg.walk_bag_protos(sess, bag_addr)
        live_uids = {f'{int(u) & 0xFFFFFFFFFFFFFFFF:016x}' for u in live_map}
    except Exception as exc:
        lines.append(f'Frida freshness  : attach ok (PID {pid}) but bag walk failed: {exc}')
        try:
            sess.detach()
        except Exception:
            pass
        return {'lines': lines, 'issues': []}
    finally:
        try:
            sess.detach()
        except Exception:
            pass

    db_uids = {r[0] for r in conn.execute(
        "SELECT uid_hex FROM pokemon WHERE in_bag = 1"
    )}
    live_only = live_uids - db_uids
    db_only = db_uids - live_uids
    total_union = len(live_uids | db_uids)
    agreement = 100.0 * len(live_uids & db_uids) / max(1, total_union)

    lines.append(f'Live bag          : {len(live_uids)} (PID {pid})')
    lines.append(f'Bag agreement     : {agreement:.1f}% ({len(live_only)} new, {len(db_only)} gone)')

    if live_only or db_only:
        issues.append(
            f'Bag drift: {len(live_only)} new catches, {len(db_only)} gone '
            f'-> run pogo_pipeline.py'
        )
    return {'lines': lines, 'issues': issues}


def section_tags_vs_registry(conn):
    """Section 2: registry.json vs DB auth_tag_names counts."""
    issues = []
    registry = _load_json(REGISTRY_PATH)
    if registry is None:
        return 'FAIL', ['registry.json not found or unparseable']

    tags = registry.get('tags', [])
    if not tags:
        return 'FAIL', ['registry.json has no tags array']

    # Build DB tag counts from auth_tag_names
    db_tag_counts = defaultdict(int)
    rows = conn.execute(
        "SELECT auth_tag_names FROM pokemon WHERE in_bag = 1 AND auth_tag_names IS NOT NULL AND auth_tag_names != ''"
    ).fetchall()
    for (raw,) in rows:
        for t in raw.split(';'):
            t = t.strip()
            if t:
                db_tag_counts[t] += 1

    registry_names = {t['name'] for t in tags}
    db_names = set(db_tag_counts.keys())

    # Tags in DB but not in registry
    extra_in_db = db_names - registry_names - {'CLAUDE_TX'}
    if extra_in_db:
        issues.append(f'Tags in DB but not in registry: {", ".join(sorted(extra_in_db))}')

    # Tags in registry but not in DB
    missing_from_db = registry_names - db_names
    if missing_from_db:
        issues.append(f'Tags in registry but 0 DB members: {", ".join(sorted(missing_from_db))}')

    # Count drift
    drift_tags = []
    print(f'  {"Tag":<20s} {"Registry":>8s} {"DB":>8s} {"Delta":>8s}')
    print(f'  {"-"*20} {"-"*8} {"-"*8} {"-"*8}')
    for t in tags:
        name = t['name']
        reg_count = t.get('count', '?')
        db_count = db_tag_counts.get(name, 0)
        if isinstance(reg_count, int):
            delta = db_count - reg_count
            delta_str = f'{delta:+d}' if delta != 0 else '='
            if abs(delta) > 5:
                drift_tags.append(f'{name}: registry={reg_count} db={db_count} ({delta:+d})')
        else:
            delta_str = '?'
        print(f'  {name:<20s} {str(reg_count):>8s} {db_count:>8d} {delta_str:>8s}')

    if drift_tags:
        issues.append(f'{len(drift_tags)} tag(s) with >5 count drift vs registry')

    if not issues:
        return 'PASS', []
    return 'WARN', issues


def section_deep_profiles(conn):
    """Section 3: deep_profiles.json freshness + purpose coverage."""
    issues = []
    age_s, mtime = _file_age(DEEP_PROFILES_PATH)
    if age_s is None:
        return 'WARN', ['deep_profiles.json not found']

    age_str = _fmt_age(age_s)
    mtime_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))
    print(f'  Profiles age     : {age_str} ({mtime_str})')

    if age_s > 172800:
        issues.append(f'deep_profiles.json is {age_str} old (>48h)')

    profiles = _load_json(DEEP_PROFILES_PATH)
    if profiles is None:
        return 'FAIL', ['deep_profiles.json unparseable']

    # Count in_bag from DB
    in_bag_count = conn.execute(
        "SELECT COUNT(*) FROM pokemon WHERE in_bag = 1"
    ).fetchone()[0]
    print(f'  Profiles count   : {len(profiles)} (DB in_bag: {in_bag_count})')

    if len(profiles) != in_bag_count:
        diff = in_bag_count - len(profiles)
        issues.append(f'Profile count mismatch: {len(profiles)} profiles vs {in_bag_count} in_bag ({diff:+d})')

    # Purpose coverage
    no_purpose = [p for p in profiles if not p.get('purpose')]
    purposes = defaultdict(int)
    for p in profiles:
        purposes[p.get('purpose', '(none)')] += 1

    print(f'  Purposes         : {dict(purposes)}')
    if no_purpose:
        issues.append(f'{len(no_purpose)} profile(s) have no purpose assigned')

    if not issues:
        return 'PASS', []
    severity = 'FAIL' if any('unparseable' in i for i in issues) else 'WARN'
    return severity, issues


def section_data_quality(conn):
    """Section 4: known data-quality flags."""
    issues = []

    # 4a. Phantom CanMega: can_mega_evolve=1 but species has no released mega
    #     We check against MEGA_EVOLUTION_IDS from references.py
    try:
        from references import MEGA_EVOLUTION_IDS
    except ImportError:
        MEGA_EVOLUTION_IDS = None

    if MEGA_EVOLUTION_IDS is not None:
        mega_ids_csv = ','.join(str(x) for x in sorted(MEGA_EVOLUTION_IDS))
        phantom_megas = conn.execute(
            f"SELECT COUNT(*) FROM pokemon WHERE in_bag=1 "
            f"AND COALESCE(can_mega_evolve,0)=1 "
            f"AND pokemon_id NOT IN ({mega_ids_csv})"
        ).fetchone()[0]
        if phantom_megas > 0:
            # Get a few species names
            samples = conn.execute(
                f"SELECT DISTINCT species_name FROM pokemon WHERE in_bag=1 "
                f"AND COALESCE(can_mega_evolve,0)=1 "
                f"AND pokemon_id NOT IN ({mega_ids_csv}) LIMIT 5"
            ).fetchall()
            sample_names = ', '.join(r[0] for r in samples if r[0])
            issues.append(f'Phantom CanMega: {phantom_megas} mons have can_mega_evolve=1 '
                          f'but species not in MEGA_EVOLUTION_IDS [{sample_names}]')
            print(f'  Phantom CanMega  : {phantom_megas} ({sample_names})')
        else:
            print(f'  Phantom CanMega  : 0 (clean)')
    else:
        print(f'  Phantom CanMega  : skipped (references.py not importable)')

    # 4b. Trade-tagged but purpose=COLLECTION (from deep_profiles)
    profiles = _load_json(DEEP_PROFILES_PATH)
    trade_collection = 0
    if profiles:
        for p in profiles:
            tags = p.get('tags', [])
            purpose = p.get('purpose', '')
            # Check for any tag containing "Trade" (the 6 Trade tag)
            has_trade = any('Trade' in t for t in tags)
            if has_trade and purpose == 'COLLECTION':
                trade_collection += 1
        if trade_collection > 0:
            issues.append(f'{trade_collection} mon(s) tagged Trade but purpose=COLLECTION')
            print(f'  Trade+COLLECTION : {trade_collection}')
        else:
            print(f'  Trade+COLLECTION : 0 (clean)')
    else:
        print(f'  Trade+COLLECTION : skipped (no profiles)')

    # 4c. Duplicate hundos: same pokemon_id with iv_total=45, in_bag=1, count > 1
    dup_hundos = conn.execute(
        "SELECT pokemon_id, species_name, COUNT(*) AS cnt "
        "FROM pokemon WHERE in_bag=1 AND iv_total=45 "
        "GROUP BY pokemon_id HAVING cnt > 1 "
        "ORDER BY cnt DESC"
    ).fetchall()
    if dup_hundos:
        total_dups = sum(r[2] - 1 for r in dup_hundos)
        top3 = ', '.join(f'{r[1]}x{r[2]}' for r in dup_hundos[:3])
        issues.append(f'{total_dups} duplicate hundo(s) across {len(dup_hundos)} species [{top3}]')
        print(f'  Duplicate hundos : {total_dups} extra across {len(dup_hundos)} species ({top3})')
    else:
        print(f'  Duplicate hundos : 0 (clean)')

    # 4d. NULL rank protection gap: in_bag=1 with NULL gl_rank or ul_rank
    null_ranks = conn.execute(
        "SELECT COUNT(*) FROM pokemon WHERE in_bag=1 "
        "AND (gl_rank IS NULL OR ul_rank IS NULL)"
    ).fetchone()[0]
    if null_ranks > 0:
        issues.append(f'{null_ranks} in_bag rows have NULL gl_rank or ul_rank '
                      f'(run compute_all_ranks.py)')
        print(f'  NULL rank gap    : {null_ranks}')
    else:
        print(f'  NULL rank gap    : 0 (clean)')

    # 4e. legacy_accurate.json freshness
    leg_age, leg_mt = _file_age(LEGACY_PATH)
    if leg_age is None:
        issues.append('legacy_accurate.json not found')
        print(f'  Legacy file      : MISSING')
    else:
        print(f'  Legacy file      : {_fmt_age(leg_age)} old')
        if leg_age > 172800:
            issues.append(f'legacy_accurate.json is {_fmt_age(leg_age)} old (>48h)')

    if not issues:
        return 'PASS', []
    # Phantom CanMega and NULL ranks are warnings; missing files are failures
    severity = 'FAIL' if any('not found' in i and 'legacy' in i.lower() for i in issues) else 'WARN'
    return severity, issues


# ===== Main ================================================================

def main():
    if not os.path.isfile(DB_PATH):
        print(f'FAIL: pokemon.db not found at {DB_PATH}')
        return 2

    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row

    sections = [
        ('DB Freshness', section_db_freshness),
        ('Tags vs Registry', section_tags_vs_registry),
        ('Deep Profiles', section_deep_profiles),
        ('Data Quality', section_data_quality),
    ]

    results = {}
    for name, fn in sections:
        print(f'\n=== {name} ===')
        try:
            verdict, issues = fn(conn)
        except Exception as exc:
            verdict, issues = 'FAIL', [f'exception: {exc}']
        results[name] = (verdict, issues)
        for iss in issues:
            print(f'  >> {iss}')
        print(f'  [{verdict}]')

    conn.close()

    # Summary
    verdicts = [v for v, _ in results.values()]
    worst = 'FAIL' if 'FAIL' in verdicts else 'WARN' if 'WARN' in verdicts else 'PASS'
    print(f'\n--- SUMMARY: {worst} ---')
    for name, (v, issues) in results.items():
        tag = v
        detail = f' ({len(issues)} issue{"s" if len(issues) != 1 else ""})' if issues else ''
        print(f'  {name:<20s} [{tag}]{detail}')

    return {'PASS': 0, 'WARN': 1, 'FAIL': 2}[worst]


if __name__ == '__main__':
    sys.exit(main())
