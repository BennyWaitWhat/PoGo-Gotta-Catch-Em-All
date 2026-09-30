"""Print current egg status: held, km walked, ETA to hatch at current pace.

Pace estimate uses the highest-km buddy in pokemon.db as a proxy for how fast
the user normally walks per real-world day. Falls back to 0 if no buddy data.
"""
import sqlite3
import time
from collections import Counter

PACE_KM_PER_DAY = 5.0  # conservative default if we can't infer it


def _infer_pace(conn: sqlite3.Connection) -> tuple[float, str]:
    """Best-effort: km/day inferred from the top buddy's km divided by how
    long ago they were caught. Not perfect (buddy walking isn't linear) but
    gives a usable order-of-magnitude.
    """
    row = conn.execute(
        "SELECT species_name, buddy_km_walked, creation_time_ms "
        "FROM pokemon WHERE buddy_km_walked > 0 AND creation_time_ms > 0 "
        "ORDER BY buddy_km_walked DESC LIMIT 1"
    ).fetchone()
    if not row:
        return PACE_KM_PER_DAY, 'default (no buddy data)'
    species, km, created_ms = row
    age_days = (time.time() * 1000 - created_ms) / (1000 * 60 * 60 * 24)
    if age_days < 1:
        return PACE_KM_PER_DAY, f'{species} too new for pace inference'
    pace = km / age_days
    return pace, f'inferred from {species}: {km:.1f} km over {age_days:.0f} days'


def main(db_path: str = 'pokemon.db') -> None:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT uid_hex, egg_km_walked_target, egg_km_walked_start, "
        "incubator_id, first_seen_ms FROM eggs "
        "WHERE in_bag=1 AND is_hatched=0 ORDER BY egg_km_walked_target, uid_hex"
    ).fetchall()

    if not rows:
        print("No eggs currently held.")
        conn.close()
        return

    pace, pace_note = _infer_pace(conn)

    print(f"Eggs held: {len(rows)}")
    print(f"Pace assumption: {pace:.2f} km/day ({pace_note})")
    print()

    target_dist = Counter()
    in_incubator = 0
    print(f"{'uid_hex':<18} {'target':>7} {'walked':>7} {'remain':>7} "
          f"{'incub':<6} ETA")
    print('-' * 70)
    for uid_hex, target, start, incub, first_seen_ms in rows:
        target = target or 0.0
        start = start or 0.0
        # km_walked_start is the cumulative km the egg has banked from prior
        # incubation; assume "remaining" = target - start.
        remaining = max(0.0, target - start)
        target_dist[target] += 1
        incub_str = 'YES' if incub else '-'
        if incub:
            in_incubator += 1
        if pace > 0:
            eta_days = remaining / pace
            if eta_days < 1:
                eta = f'{eta_days*24:.1f}h'
            else:
                eta = f'{eta_days:.1f}d'
        else:
            eta = '?'
        if not incub:
            eta = f'{eta} (idle)'
        print(f"{uid_hex:<18} {target:>6.1f}k {start:>6.2f}k "
              f"{remaining:>6.2f}k {incub_str:<6} {eta}")

    print()
    print("Distribution by target km:")
    for km, n in sorted(target_dist.items()):
        print(f"  {km:>5.1f} km: {n} egg(s)")
    print(f"In incubators: {in_incubator}/{len(rows)}")

    conn.close()


if __name__ == '__main__':
    main()
