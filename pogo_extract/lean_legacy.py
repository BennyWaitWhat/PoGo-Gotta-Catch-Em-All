"""Lean Legacy-tag + REVIEW-clean using bulk_tag.js's own fast proto index
(the proven path from pogo_pipeline). No liveness scan -> fast -> finishes before PoGo recycles.
Reconnects+resumes if the session dies. Idempotent."""
import frida, json, sqlite3, subprocess, sys, time, os
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, '.')
import pogo_il2cpp as pg
import pogo_pipeline as pl

c = sqlite3.connect('pokemon.db').cursor()
legacy = json.load(open('legacy_accurate.json'))
legacy_uids = [it['uid_hex'] for it in legacy]
regional_pull = json.load(open('regional_pull_uids.json'))

def signed_uid(uh):
    row = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    return int(row[0]) if row else None

def lowhigh(uid):
    low = uid & 0xFFFFFFFF; high = (uid >> 32) & 0xFFFFFFFF
    if low > 0x7FFFFFFF: low -= 0x100000000
    if high > 0x7FFFFFFF: high -= 0x100000000
    return low, high

def unsigned_str(uh):
    u = signed_uid(uh)
    if u is None: return None
    return str(u if u >= 0 else u + 2**64)

def attempt():
    sess, pid = pg.get_session()
    print(f"PID={pid}")
    s = pl.step_singletons(sess)
    SVC = s['svc']; BAG = s['bag']
    print(f"svc={SVC} bag={BAG}")

    # Resolve ALL needed protos via BAG WALK (sees all pokemon, not just materialized)
    all_uids = set(legacy_uids) | set(regional_pull)
    hex_to_us = {uh: unsigned_str(uh) for uh in all_uids}
    us_to_hex = {us: uh for uh, us in hex_to_us.items() if us}
    found_by_us = pg.find_protos_for_uids(sess, BAG, list(us_to_hex.keys()))
    proto_by_hex = {us_to_hex[us]: p for us, p in found_by_us.items() if us in us_to_hex}
    print(f"bag-walk resolved {len(proto_by_hex)}/{len(all_uids)} protos")

    bt = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
    bt.on('message', lambda m,d: None); bt.load(); bt.exports_sync.init_status()

    ft = bt.exports_sync.find_tag_id_by_name(SVC, 'Legacy')
    if not ft.get('ok'):
        bt.exports_sync.add_tag_on_instance(SVC, 'Legacy', 5); time.sleep(1.5)
        ft = bt.exports_sync.find_tag_id_by_name(SVC, 'Legacy')
    print(f"Legacy idx={ft.get('idx')}")

    leg_protos_map = {uh: proto_by_hex[uh] for uh in legacy_uids if uh in proto_by_hex}
    print(f"resolved legacy {len(leg_protos_map)}/{len(legacy_uids)}")

    # tag legacy in chunks of 100
    protos = list(leg_protos_map.values())
    bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], protos[:1]); time.sleep(0.6)
    built=0; i=0; delay=0.5
    while i < len(protos):
        chunk = protos[i:i+100]
        r = bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], chunk)
        if r.get('ok'): built += r.get('built',0); i += 100; delay=max(0.4, delay*0.7)
        else: delay=min(8, delay*2.5); time.sleep(delay)
        time.sleep(delay)
    chk = bt.exports_sync.get_pokemon_for_tag(SVC, ft['idx'])
    leg_count = chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')
    print(f"Legacy tagged built={built} server_count={leg_count}")

    # pull legacy + regional from REVIEW
    ftr = bt.exports_sync.find_tag_id_by_name(SVC, 'REVIEW')
    pull_uids = set(legacy_uids) | set(regional_pull)
    pull_map = {uh: proto_by_hex[uh] for uh in pull_uids if uh in proto_by_hex}
    pulled=0
    for uh, proto in pull_map.items():
        try:
            r = bt.exports_sync.bulk_untag_one(SVC, proto, ftr['tagProtoAddr'])
            if r.get('ok'): pulled+=1
        except: pass
        time.sleep(0.2)
    chk2 = bt.exports_sync.get_pokemon_for_tag(SVC, ftr['idx'])
    rev_count = chk2.get('dump',{}).get('+0x18_listish',{}).get('count','?')
    print(f"pulled~{pulled} from REVIEW, server REVIEW count={rev_count}")
    bt.unload(); sess.detach()
    return leg_count, rev_count

for a in range(10):
    try:
        lc, rc = attempt()
        print(f"\nDONE: Legacy={lc} REVIEW={rc}")
        break
    except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError, frida.ServerNotRunningError, RuntimeError) as e:
        print(f"[retry {a+1}] {type(e).__name__}: {e}")
        time.sleep(5)
