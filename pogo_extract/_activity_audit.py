import sqlite3, json, datetime, os

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
os.makedirs('agent_outputs', exist_ok=True)

conn = sqlite3.connect(os.path.join(BASE, 'pokemon.db'))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

NOW_MS = int(datetime.datetime.now().timestamp() * 1000)
MAX_VALID_MS = 2000000000000  # ~2033, anything beyond is bogus

cur.execute(
    "SELECT MAX(creation_time_ms) FROM pokemon "
    "WHERE creation_time_ms IS NOT NULL AND creation_time_ms > 0 AND creation_time_ms < ?",
    (MAX_VALID_MS,),
)
latest_ms = cur.fetchone()[0]
latest_dt = datetime.datetime.fromtimestamp(latest_ms / 1000.0)
db_age_days = (NOW_MS - latest_ms) / 86400000.0

ref_ms = latest_ms
ref_iso = latest_dt.isoformat()
now_iso = datetime.datetime.fromtimestamp(NOW_MS / 1000.0).isoformat()

DAY_MS = 86400000
w24h = ref_ms - 1 * DAY_MS
w7d = ref_ms - 7 * DAY_MS
w30d = ref_ms - 30 * DAY_MS

cur.execute(
    "SELECT COUNT(*) FROM pokemon WHERE creation_time_ms > 0 AND creation_time_ms < ?",
    (MAX_VALID_MS,),
)
total_captures = cur.fetchone()[0]


def count_in_window(start_ms, end_ms):
    cur.execute(
        "SELECT COUNT(*) FROM pokemon WHERE creation_time_ms BETWEEN ? AND ?",
        (start_ms, end_ms),
    )
    return cur.fetchone()[0]


windows = {
    'last_24h': {'start_ms': w24h, 'end_ms': ref_ms, 'count': count_in_window(w24h, ref_ms)},
    'last_7d':  {'start_ms': w7d,  'end_ms': ref_ms, 'count': count_in_window(w7d,  ref_ms)},
    'last_30d': {'start_ms': w30d, 'end_ms': ref_ms, 'count': count_in_window(w30d, ref_ms)},
}
for v in windows.values():
    v['start_iso'] = datetime.datetime.fromtimestamp(v['start_ms'] / 1000.0).isoformat()
    v['end_iso']   = datetime.datetime.fromtimestamp(v['end_ms']   / 1000.0).isoformat()


def pokeball_breakdown(start_ms=None, end_ms=None):
    if start_ms is not None and end_ms is not None:
        cur.execute(
            "SELECT COALESCE(pokeball, -1), COALESCE(pokeball_name, 'UNKNOWN'), COUNT(*) "
            "FROM pokemon WHERE creation_time_ms BETWEEN ? AND ? "
            "GROUP BY pokeball, pokeball_name ORDER BY 3 DESC",
            (start_ms, end_ms),
        )
    else:
        cur.execute(
            "SELECT COALESCE(pokeball, -1), COALESCE(pokeball_name, 'UNKNOWN'), COUNT(*) "
            "FROM pokemon WHERE creation_time_ms > 0 AND creation_time_ms < ? "
            "GROUP BY pokeball, pokeball_name ORDER BY 3 DESC",
            (MAX_VALID_MS,),
        )
    return [{'pokeball': r[0], 'pokeball_name': r[1], 'count': r[2]} for r in cur.fetchall()]


pokeball = {
    'overall':  pokeball_breakdown(),
    'last_24h': pokeball_breakdown(w24h, ref_ms),
    'last_7d':  pokeball_breakdown(w7d,  ref_ms),
    'last_30d': pokeball_breakdown(w30d, ref_ms),
}


def from_fort_stats(start_ms=None, end_ms=None):
    if start_ms is not None and end_ms is not None:
        cur.execute(
            "SELECT COALESCE(from_fort, 0), COUNT(*) FROM pokemon "
            "WHERE creation_time_ms BETWEEN ? AND ? GROUP BY 1",
            (start_ms, end_ms),
        )
    else:
        cur.execute(
            "SELECT COALESCE(from_fort, 0), COUNT(*) FROM pokemon "
            "WHERE creation_time_ms > 0 AND creation_time_ms < ? GROUP BY 1",
            (MAX_VALID_MS,),
        )
    rows = cur.fetchall()
    out = {'from_fort': 0, 'wild_or_other': 0}
    for ff, c in rows:
        if ff == 1:
            out['from_fort'] = c
        else:
            out['wild_or_other'] += c
    out['total'] = out['from_fort'] + out['wild_or_other']
    out['from_fort_pct'] = round(100.0 * out['from_fort'] / out['total'], 2) if out['total'] else 0.0
    return out


fort_stats = {
    'overall':  from_fort_stats(),
    'last_24h': from_fort_stats(w24h, ref_ms),
    'last_7d':  from_fort_stats(w7d,  ref_ms),
    'last_30d': from_fort_stats(w30d, ref_ms),
}

cur.execute(
    "SELECT deployed_fort_id, COUNT(*) FROM pokemon "
    "WHERE from_fort=1 AND deployed_fort_id IS NOT NULL AND deployed_fort_id <> '' "
    "GROUP BY deployed_fort_id ORDER BY 2 DESC LIMIT 20"
)
top_fort_ids = [{'fort_id': r[0], 'count': r[1]} for r in cur.fetchall()]


def weather_stats(start_ms=None, end_ms=None):
    if start_ms is not None and end_ms is not None:
        cur.execute(
            "SELECT COALESCE(weather_boosted, 0), COUNT(*) FROM pokemon "
            "WHERE creation_time_ms BETWEEN ? AND ? GROUP BY 1",
            (start_ms, end_ms),
        )
    else:
        cur.execute(
            "SELECT COALESCE(weather_boosted, 0), COUNT(*) FROM pokemon "
            "WHERE creation_time_ms > 0 AND creation_time_ms < ? GROUP BY 1",
            (MAX_VALID_MS,),
        )
    rows = cur.fetchall()
    out = {'boosted': 0, 'not_boosted': 0}
    for wb, c in rows:
        if wb and wb != 0:
            out['boosted'] += c
        else:
            out['not_boosted'] += c
    out['total'] = out['boosted'] + out['not_boosted']
    out['boosted_pct'] = round(100.0 * out['boosted'] / out['total'], 2) if out['total'] else 0.0
    return out


weather_summary = {
    'overall':  weather_stats(),
    'last_24h': weather_stats(w24h, ref_ms),
    'last_7d':  weather_stats(w7d,  ref_ms),
    'last_30d': weather_stats(w30d, ref_ms),
}


def weather_name_breakdown(start_ms=None, end_ms=None):
    if start_ms is not None and end_ms is not None:
        cur.execute(
            "SELECT COALESCE(weather_name, 'UNKNOWN'), COUNT(*) FROM pokemon "
            "WHERE creation_time_ms BETWEEN ? AND ? "
            "AND weather_boosted IS NOT NULL AND weather_boosted <> 0 "
            "GROUP BY 1 ORDER BY 2 DESC",
            (start_ms, end_ms),
        )
    else:
        cur.execute(
            "SELECT COALESCE(weather_name, 'UNKNOWN'), COUNT(*) FROM pokemon "
            "WHERE creation_time_ms > 0 AND creation_time_ms < ? "
            "AND weather_boosted IS NOT NULL AND weather_boosted <> 0 "
            "GROUP BY 1 ORDER BY 2 DESC",
            (MAX_VALID_MS,),
        )
    return [{'weather_name': r[0], 'count': r[1]} for r in cur.fetchall()]


weather_name_summary = {
    'overall':  weather_name_breakdown(),
    'last_7d':  weather_name_breakdown(w7d, ref_ms),
    'last_30d': weather_name_breakdown(w30d, ref_ms),
}

cur.execute(
    "SELECT DATE(creation_time_ms/1000, 'unixepoch'), COUNT(*) FROM pokemon "
    "WHERE creation_time_ms BETWEEN ? AND ? GROUP BY 1 ORDER BY 1",
    (w30d, ref_ms),
)
daily_counts = [{'date': r[0], 'count': r[1]} for r in cur.fetchall()]


def special_counts(start_ms, end_ms):
    out = {}
    cur.execute(
        "SELECT COUNT(*) FROM pokemon WHERE creation_time_ms BETWEEN ? AND ? AND is_shiny=1",
        (start_ms, end_ms),
    )
    out['shiny'] = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM pokemon WHERE creation_time_ms BETWEEN ? AND ? AND is_hundo=1",
        (start_ms, end_ms),
    )
    out['hundo'] = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM pokemon WHERE creation_time_ms BETWEEN ? AND ? AND is_lucky=1",
        (start_ms, end_ms),
    )
    out['lucky'] = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM pokemon WHERE creation_time_ms BETWEEN ? AND ? AND is_hatched_from_egg=1",
        (start_ms, end_ms),
    )
    out['from_egg'] = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM pokemon WHERE creation_time_ms BETWEEN ? AND ? AND is_traded=1",
        (start_ms, end_ms),
    )
    out['traded'] = cur.fetchone()[0]
    return out


specials = {
    'last_24h': special_counts(w24h, ref_ms),
    'last_7d':  special_counts(w7d,  ref_ms),
    'last_30d': special_counts(w30d, ref_ms),
}

cur.execute(
    "SELECT COALESCE(origin_detail_name, 'UNKNOWN'), COUNT(*) FROM pokemon "
    "WHERE creation_time_ms BETWEEN ? AND ? GROUP BY 1 ORDER BY 2 DESC",
    (w30d, ref_ms),
)
origin_detail_30d = [{'origin_detail_name': r[0], 'count': r[1]} for r in cur.fetchall()]

cur.execute(
    "SELECT uid_hex, species_name, creation_time_ms FROM pokemon WHERE creation_time_ms >= ?",
    (MAX_VALID_MS,),
)
bogus = [{'uid_hex': r[0], 'species_name': r[1], 'creation_time_ms': r[2]} for r in cur.fetchall()]

result = {
    'metadata': {
        'generated_at': now_iso,
        'now_ms': NOW_MS,
        'db_snapshot_latest_capture_iso': ref_iso,
        'db_snapshot_latest_capture_ms': ref_ms,
        'db_age_days_from_now': round(db_age_days, 2),
        'reference_for_windows': 'latest_capture in DB (windows anchored to most recent capture, not wall-clock now, since DB snapshot is older than 24h)',
        'total_captures_in_db': total_captures,
        'excluded_records_with_invalid_creation_time_ms': bogus,
    },
    'capture_counts_by_window': windows,
    'pokeball_breakdown': pokeball,
    'from_fort_captures': fort_stats,
    'top_fort_ids_overall': top_fort_ids,
    'weather_boosted': weather_summary,
    'weather_name_breakdown_boosted_only': weather_name_summary,
    'daily_capture_counts_last_30d': daily_counts,
    'special_captures_by_window': specials,
    'origin_detail_breakdown_last_30d': origin_detail_30d,
}

with open('agent_outputs/activity_audit.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print('OK', 'agent_outputs/activity_audit.json')
print('latest_capture:', ref_iso, 'db_age_days:', round(db_age_days, 2))
print('total:', total_captures)
print('w24h:', windows['last_24h']['count'], 'w7d:', windows['last_7d']['count'], 'w30d:', windows['last_30d']['count'])
print('pokeball_overall_top5:', pokeball['overall'][:5])
print('fort_30d:', fort_stats['last_30d'])
print('weather_30d:', weather_summary['last_30d'])
print('specials_30d:', specials['last_30d'])
print('origin_detail_30d_top5:', origin_detail_30d[:5])
print('daily_counts:', daily_counts)
