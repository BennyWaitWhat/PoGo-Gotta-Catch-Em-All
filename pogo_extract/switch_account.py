"""python switch_account.py <name>  -- park the live data set (active_account.txt) in accounts/<active>/ and bring <name>'s
back (see account_guard.py). SQLite files are copied with the backup API (WAL-safe); nothing is deleted -- the parked
copy is overwritten only with the live one it replaces."""
import os, shutil, sqlite3, sys
import account_guard

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = ['pokemon.db', 'keep_config.json', 'system/analysis/ladder_history.json', 'system/analysis/last_report.json',
         'system/analysis/stop_tags.json', 'system/analysis/remote_trade_verified.json', 'system/analysis/empty_since.json',
         '.db_snapshots', 'system/analysis/retro_frozen_seen.json']
# THE WALK'S FAIL-SOFT OUTPUTS ARE PER TRAINER TOO (H10-8, 2026-09-29). A failed in-walk read keeps the previous file, so
# after a switch it would keep the OTHER trainer's Pokedex (evolution availability, hundo dex), candy, items, storage cap
# and egg count. They travel with the data set, and when the parked set has none they are REMOVED, never left foreign:
# missing candy = unknown (the engine holds), a missing Pokedex stops keep_policy until the next walk writes it.
WALK_FILES = ['pokedex_hundos_live.json', 'pokedex_hundos_live.prev.json', 'dex_caught.json', 'dex_caught_forms.json',
              'player_state.json', 'system/analysis/candy.json', 'system/analysis/inventory.json',
              'system/analysis/bag_count.json']
STATE += WALK_FILES


def _copy(src, dst):
    if os.path.isdir(src):
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    elif src.endswith('.db'):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        a, b = sqlite3.connect(src), sqlite3.connect(dst)
        a.backup(b); b.close(); a.close()
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def park(name):
    for rel in STATE:
        src = os.path.join(HERE, rel)
        if os.path.exists(src):
            _copy(src, os.path.join(HERE, 'accounts', name, rel))


def load(name):
    base = os.path.join(HERE, 'accounts', name)
    if not os.path.exists(os.path.join(base, 'pokemon.db')):
        sys.exit('no parked data set for %r (accounts/%s/pokemon.db)' % (name, name))
    for rel in STATE:
        src, dst = os.path.join(base, rel), os.path.join(HERE, rel)
        if not os.path.exists(src) and rel in WALK_FILES and os.path.exists(dst):
            os.remove(dst)                       # the other trainer's walk output: missing beats foreign (H10-8)
            continue
        if os.path.exists(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            elif os.path.exists(dst):
                os.remove(dst)
            for ext in ('-wal', '-shm'):
                if rel.endswith('.db') and os.path.exists(dst + ext):
                    os.remove(dst + ext)
            _copy(src, dst)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    want, cur = sys.argv[1].strip().lower(), account_guard.active()
    if cur == want:
        park(cur); print('%s is already live -- parked a fresh copy in accounts/%s/' % (cur, cur)); sys.exit(0)
    if cur:
        park(cur)
    load(want)
    open(account_guard.ACTIVE, 'w', encoding='utf-8').write(want)
    print('live data set: %s (parked %s)' % (want, cur))
