"""Definitive freshness check: walk the LIVE bag and reconcile against the
DB's in_bag=1 set. Tells us whether the ~13h-old DB still matches reality.

  live_only : present in game now but DB not flagged in_bag (missed catches / stale)
  db_only   : DB says in_bag=1 but NOT in live bag (transferred since last scan)
"""
import sqlite3, sys
import pogo_il2cpp as pg
sys.stdout.reconfigure(encoding='utf-8')


def main():
    conn = sqlite3.connect('pokemon.db')
    db_inbag = {r[0] for r in conn.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1")}

    sess, pid = pg.get_session()
    print(f'pid={pid}')
    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        live = pg.walk_bag_protos(sess, bag)   # {uid_dec: proto}
    finally:
        sess.detach()

    live_hex = {f'{int(u):016x}' for u in live.keys()}
    print(f'live bag size      : {len(live_hex)}')
    print(f'DB in_bag=1 size   : {len(db_inbag)}')

    live_only = live_hex - db_inbag
    db_only = db_inbag - live_hex
    print(f'\nlive_only (in game, DB stale): {len(live_only)}')
    for u in list(live_only)[:25]:
        print(f'   {u}')
    print(f'\ndb_only (DB in_bag but transferred): {len(db_only)}')
    for u in list(db_only)[:25]:
        r = conn.execute("SELECT species_name,cp,iv_total,auth_tag_names FROM pokemon WHERE uid_hex=?", (u,)).fetchone()
        print(f'   {u}  {r}')

    overlap = len(live_hex & db_inbag)
    print(f'\noverlap: {overlap}')
    if not live_only and not db_only:
        print('DB in_bag set EXACTLY matches the live bag — data is current.')
    else:
        pct = 100.0 * overlap / max(1, len(live_hex | db_inbag))
        print(f'agreement: {pct:.2f}%  ({len(live_only)} new, {len(db_only)} gone)')
    conn.close()


if __name__ == '__main__':
    main()
