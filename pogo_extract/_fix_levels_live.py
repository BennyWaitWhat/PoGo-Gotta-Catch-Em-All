"""Recompute `level` for every in-bag specimen from the LIVE proto using the
corrected total CPM (cp_multiplier@0x7c + additional_cpm@0xac). Fixes the level
regression introduced when the full-update wrote level from base-cpm only.
Reuses pogo_pipeline.PIPELINE_JS + the fixed parse_pokemon. Updates level only.
"""
import sqlite3, time, sys
import pogo_pipeline as P
import pogo_il2cpp as pg
sys.stdout.reconfigure(encoding='utf-8')

def main():
    sess, pid = pg.get_session()
    print(f'pid={pid}')
    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        script = pg.get_script_with_helpers(sess, P.PIPELINE_JS)
        t0 = time.time()
        entries = script.exports_sync.pipeline_walk(bag)
        print(f'walked {len(entries)} in {time.time()-t0:.1f}s')
        script.unload()
    finally:
        sess.detach()

    conn = sqlite3.connect('pokemon.db'); cur = conn.cursor()
    changed = 0; checked = 0
    samples = []
    for rec in entries:
        p = P.parse_pokemon(rec, {})
        if not p:
            continue
        checked += 1
        old = cur.execute("SELECT level, species_name, cp FROM pokemon WHERE uid_hex=?",
                          (p['uid_hex'],)).fetchone()
        if old and abs((old[0] or 0) - p['level']) > 0.01:
            changed += 1
            if old[2] and old[2] >= 3000 and len(samples) < 12:
                samples.append((old[1], old[2], old[0], p['level']))
        cur.execute("UPDATE pokemon SET level=? WHERE uid_hex=?", (p['level'], p['uid_hex']))
    conn.commit()
    print(f'checked {checked}, level changed for {changed}')
    print('Sample high-CP corrections (species, cp, old_level -> new_level):')
    for s in samples:
        print(f'   {s[0]:<16} cp={s[1]:>4}  L{s[2]} -> L{s[3]}')
    # sanity: any in-bag with cp>=3000 but level<30 now? (should be ~none)
    bad = cur.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cp>=3000 AND level<30").fetchone()[0]
    print(f'in-bag cp>=3000 but level<30 (should be ~0): {bad}')
    conn.close()

if __name__ == '__main__':
    main()
