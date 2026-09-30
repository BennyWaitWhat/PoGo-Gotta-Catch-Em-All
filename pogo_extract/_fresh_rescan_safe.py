"""SAFE full-bag deep rescan, split into ONE-ATTACH scan + a purely local load.

Based on the code-reading agent's _fresh_rescan_safe.py. Same JS, same offsets,
same 19 columns. Changes vs the shipped run_fresh_poll.py + parse_fresh.py:

  1. Attaches to the REAL PoGo pid via pogo_il2cpp (adb connect + forward + pidof
     + the pure-adb cold-start gate). run_fresh_poll.py attaches to
     d.enumerate_processes()[0].pid -- an arbitrary process.
  2. Never blanks a column. parse_fresh.py NULLs 18 columns across the WHOLE
     table before refilling, so a short scan silently destroys good data.
     This only UPDATEs rows it actually read.
  3. Floor guard on TRUE BAG COVERAGE (in_bag rows matched with usable
     displayBytes), not len(results) -- the heap scan also returns protos from
     encounters / trade previews / RPC responses that are not in the bag, so
     len(results) overstates coverage.
  4. Snapshots the DB before writing.
  5. Two phases so the whole job costs exactly ONE frida attach:
       --scan   attach once, heap scan, floor guard, write fresh_poll.json
       --load   NO phone contact at all; read fresh_poll.json -> pokemon.db

Usage (from the pogo_extract dir):
    python _fresh_rescan_safe.py --scan
    python _fresh_rescan_safe.py --load
"""
import argparse, json, os, sqlite3, struct, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.environ.get('POGO_EXTRACT_DIR', HERE)
sys.path.insert(0, PROJ)

DB = os.path.join(PROJ, 'pokemon.db')
JS = os.path.join(PROJ, 'fresh_poll.js')
JSON_OUT = os.path.join(PROJ, 'fresh_poll.json')
FLOOR_FRACTION = 0.95            # matched in_bag rows must be >=95% of in_bag


def i32(bs, o):
    return struct.unpack_from('<i', bs, o)[0] if o + 4 <= len(bs) else 0


def byte(bs, o):
    return bs[o] if o < len(bs) else 0


def bag_index(conn):
    """uid_hex -> 1 for every in-bag row."""
    return {r[0] for r in conn.execute('SELECT uid_hex FROM pokemon WHERE in_bag=1')}


# --- proto validity gate -------------------------------------------------
# The heap scan matches on the PokemonProto klass pointer and dedups "prefer
# first", so it can return a STALE or FREED proto whose pokemonDisplay_ pointer
# now aims at reused memory. Observed in this scan: 8 in-bag rows whose
# displayBytes decode as UTF-16 C# strings ("/UI/StyleShopIco...",
# "Packages/com.n...") or raw heap pointers. Writing those would have flipped a
# real shiny Snorunt and a shiny Victreebel to shiny=0 and stripped Gmax off a
# Rillaboom. Two independent checks, both must pass:
#   1. STRUCTURAL - every decoded field inside its observed enum domain.
#   2. CORROBORATION - the 8 columns pogo_pipeline.py maintains on every
#      recrawl (already current, 0 NULLs) must match. Shiny is immutable in
#      PoGo, so a 1->0 disagreement is proof the proto is wrong, not the row.
# A row failing either check is SKIPPED - its existing values are kept.
BOUNDS = {'form': (0, 20000), 'costume': (0, 2000), 'alignment': (0, 10),
          'bread_mode': (0, 20), 'badge': (0, 100), 'temp_evo': (0, 100),
          'nat_art_type': (0, 2000), 'nat_art_bg': (0, 2000),
          'day_night': (0, 100), 'loc_enum': (0, 20000)}

# the 8 recrawl-maintained columns, in decode order
TRUST_COLS = ['fresh_form', 'fresh_costume', 'fresh_shiny', 'fresh_alignment',
              'fresh_bread_mode', 'fresh_is_strong', 'fresh_pokemon_badge',
              'fresh_current_temp_evolution']


def decode(rec):
    """displayBytes/locBytes -> the 18 values, or None if structurally invalid."""
    b = rec.get('displayBytes')
    if not b:
        return None
    bs = bytes.fromhex(b)
    loc_enum = 0
    lb = rec.get('locBytes')
    if lb:
        loc_enum = i32(bytes.fromhex(lb), 0x10)   # LocationCardDisplayProto.LocationCard @0x10
    v = dict(costume=i32(bs, 0x10), form=i32(bs, 0x1c), alignment=i32(bs, 0x24),
             badge=i32(bs, 0x28), temp_evo=i32(bs, 0x2c),
             has_mega=1 if rec.get('megaBytes') else 0,
             has_loc=1 if rec.get('locBytes') else 0, loc_enum=loc_enum,
             bread_mode=i32(bs, 0x60), is_strong=byte(bs, 0x64),
             nat_art_type=i32(bs, 0x70), nat_art_bg=i32(bs, 0x74),
             nat_art_full=byte(bs, 0x78), day_night=i32(bs, 0x7c),
             shiny=byte(bs, 0x18))
    # 1. structural
    for k, (lo, hi) in BOUNDS.items():
        if not lo <= v[k] <= hi:
            return None
    for k in ('shiny', 'is_strong', 'nat_art_full'):
        if v[k] not in (0, 1):
            return None
    return v


def corroborated(v, trusted):
    """v must agree with every non-NULL recrawl-maintained column."""
    order = ['form', 'costume', 'shiny', 'alignment', 'bread_mode',
             'is_strong', 'badge', 'temp_evo']
    return all(o is None or int(o) == int(v[k]) for o, k in zip(trusted, order))


def coverage(results, bag):
    """TRUE bag coverage: in_bag rows the scan found, and how many are usable."""
    matched, usable = set(), set()
    for uid_str, rec in results.items():
        uh = f'{int(uid_str) & 0xFFFFFFFFFFFFFFFF:016x}'
        if uh in bag:
            matched.add(uh)
            if rec.get('displayBytes'):
                usable.add(uh)
    return matched, usable


def do_scan(args):
    import pogo_il2cpp as pg
    conn = sqlite3.connect(DB)
    bag = bag_index(conn)
    conn.close()

    print('gate: waiting for PoGo to be attach-safe (pure adb, attaches nothing)...')
    pid = pg.wait_ready_to_attach(timeout_s=240)
    print(f'  pid {pid} ready')

    print('attach #1 (the only one)...')
    sess, pid = pg.get_session()
    try:
        script = sess.create_script(open(JS, 'r', encoding='utf-8').read())
        script.load()
        st = script.exports_sync.init_status()
        print(f'  init: {st}')
        if not st.get('ready'):
            raise RuntimeError(f'fresh_poll.js init failed: {st.get("err")}')
        t0 = time.time()
        r = script.exports_sync.fresh_poll_all()      # <- the ONE heap scan
        print(f'  heap scan done in {time.time() - t0:.1f}s')
        script.unload()
    finally:
        sess.detach()
        print('  detached')

    if not r.get('ok'):
        raise RuntimeError(f'fresh_poll_all failed: {r.get("err")}')

    results = r['results']
    matched, usable = coverage(results, bag)
    r['_coverage'] = {'in_bag': len(bag), 'results': len(results),
                      'matched': len(matched), 'usable': len(usable)}
    print(f'  stats: {json.dumps(r["stats"])}')
    print(f'  protos returned      : {len(results)}')
    print(f'  in_bag rows matched  : {len(matched)} / {len(bag)} '
          f'({len(matched) / len(bag):.1%})')
    print(f'  ...with displayBytes : {len(usable)} / {len(bag)} '
          f'({len(usable) / len(bag):.1%})')

    floor = int(len(bag) * args.floor)
    if len(usable) < floor:
        print(f'ABORT: usable coverage {len(usable)} < floor {floor} '
              f'({args.floor:.0%} of {len(bag)}). Partial heap scan -- writing NOTHING.')
        return 2

    tmp = JSON_OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(r, f)
    os.replace(tmp, JSON_OUT)
    print(f'wrote {JSON_OUT} ({len(results)} protos)')
    print('scan phase done. Nothing written to pokemon.db yet -- run --load next.')
    return 0


def do_load(args):
    """No phone contact whatsoever."""
    import db_safety
    with open(JSON_OUT) as f:
        data = json.load(f)
    results = data['results']

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    bag = bag_index(conn)
    matched, usable = coverage(results, bag)
    print(f'load: {len(results)} protos in json; '
          f'{len(matched)}/{len(bag)} in_bag matched, {len(usable)} usable')

    floor = int(len(bag) * args.floor)
    if len(usable) < floor:
        print(f'ABORT: usable coverage {len(usable)} < floor {floor}. Not touching the DB.')
        return 2

    snap = db_safety.snapshot('before_fresh_rescan', DB)
    print(f'snapshot: {snap}')

    trust = {r[0]: r[1:] for r in
             c.execute(f'SELECT uid_hex,{",".join(TRUST_COLS)} FROM pokemon')}

    seen = updated = no_display = unknown = 0
    bad_struct, bad_corrob = [], []
    for uid_str, rec in results.items():
        seen += 1
        u = int(uid_str)
        uid_hex = f'{u & 0xFFFFFFFFFFFFFFFF:016x}'
        if uid_hex not in trust:
            unknown += 1
            continue
        if not rec.get('displayBytes'):
            # No display proto -> DO NOT blank the cosmetic columns (parse_fresh did).
            c.execute('UPDATE pokemon SET fresh_in_heap=1 WHERE uid_hex=?', (uid_hex,))
            no_display += 1
            continue
        v = decode(rec)
        if v is None:
            bad_struct.append(uid_hex)
            continue
        if not corroborated(v, trust[uid_hex]):
            bad_corrob.append(uid_hex)
            continue
        c.execute("""UPDATE pokemon SET
            fresh_in_heap=1,
            fresh_costume=?, fresh_form=?, fresh_alignment=?, fresh_pokemon_badge=?,
            fresh_current_temp_evolution=?, fresh_has_mega_level=?, fresh_has_location_card=?,
            fresh_loc_card_enum=?, fresh_bread_mode=?, fresh_is_strong=?,
            fresh_natural_art_type=?, fresh_natural_art_bg=?, fresh_natural_art_full=?,
            fresh_day_night=?, fresh_shiny=?,
            fresh_tag_count=?, fresh_tag_ids=?, fresh_bread_count=?
            WHERE uid_hex=?""",
            (v['costume'], v['form'], v['alignment'], v['badge'], v['temp_evo'],
             v['has_mega'], v['has_loc'], v['loc_enum'], v['bread_mode'], v['is_strong'],
             v['nat_art_type'], v['nat_art_bg'], v['nat_art_full'], v['day_night'], v['shiny'],
             rec.get('tagCount', 0), ';'.join(rec.get('tagIds', [])), rec.get('breadCount', 0),
             uid_hex))
        updated += 1
    conn.commit()
    print(f'seen={seen} updated={updated} no_display={no_display} not_in_db={unknown}')
    print(f'REJECTED (kept existing values): structural={len(bad_struct)} '
          f'uncorroborated={len(bad_corrob)}')
    for uh in bad_struct + bad_corrob:
        r = c.execute('SELECT species_name,in_bag FROM pokemon WHERE uid_hex=?', (uh,)).fetchone()
        print(f'    skipped {uh} {r[0]} (in_bag={r[1]})')
    conn.close()
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', action='store_true', help='ONE attach: heap scan -> fresh_poll.json')
    ap.add_argument('--load', action='store_true', help='local only: fresh_poll.json -> pokemon.db')
    ap.add_argument('--floor', type=float, default=FLOOR_FRACTION)
    args = ap.parse_args()
    if args.scan == args.load:
        ap.error('pick exactly one of --scan / --load')
    return do_scan(args) if args.scan else do_load(args)


if __name__ == '__main__':
    raise SystemExit(main())
