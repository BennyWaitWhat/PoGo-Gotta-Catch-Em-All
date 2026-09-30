"""UL rule: ul_rank<=10 AND species' final-evo max CP (L50, perfect IV) > 2425, top 2/species.
Computes final_form_max_cp from gamemaster for any in_bag NULL, then reconciles UL tag."""
import frida, sys, time, sqlite3, math
from collections import defaultdict
sys.path.insert(0,'.')
import pogo_il2cpp as pg, pogo_pipeline as pl
import json

CPM_L50 = 0.84029999
gm = json.load(open('pvpoke_gamemaster.json'))
by_sid = {p['speciesId']: p for p in gm['pokemon']}
by_dex = {}
for p in gm['pokemon']:
    d = p.get('dex')
    if d and '_shadow' not in p['speciesId'] and d not in by_dex:
        by_dex[d] = p

def max_cp(p):
    bs = p.get('baseStats', {})
    a = bs.get('atk',0)+15; d = bs.get('def',0)+15; s = bs.get('hp',0)+15
    cp = (a * (d**0.5) * (s**0.5) * (CPM_L50**2)) / 10.0
    return max(10, int(math.floor(cp)))

def terminal_max_cp(sid, seen=None):
    """Max CP across this species and all its terminal evolutions."""
    if seen is None: seen=set()
    p = by_sid.get(sid)
    if not p: return 0
    best = max_cp(p)
    for ev in p.get('family',{}).get('evolutions',[]) or []:
        if ev not in seen:
            seen.add(ev); best = max(best, terminal_max_cp(ev, seen))
    return best

# validation
g = by_dex.get(282)  # Gardevoir
print(f"validate Gardevoir final-line max CP (expect ~2800): {terminal_max_cp('ralts') if 'ralts' in by_sid else 'n/a'}")

c = sqlite3.connect('pokemon.db'); cur = c.cursor()
# fill NULL final_form_max_cp for in_bag
nulls = cur.execute("SELECT uid_hex, pokemon_id FROM pokemon WHERE in_bag=1 AND final_form_max_cp IS NULL").fetchall()
filled=0
for uh, pid in nulls:
    base = by_dex.get(pid)
    if not base: continue
    mc = terminal_max_cp(base['speciesId'])
    if mc>0:
        cur.execute("UPDATE pokemon SET final_form_max_cp=? WHERE uid_hex=?", (mc, uh)); filled+=1
c.commit()
print(f"filled final_form_max_cp for {filled}/{len(nulls)} NULL in_bag")

# UL target: ul_rank<=10 AND final_form_max_cp>2425, top 2 per species
rows = cur.execute("SELECT uid_hex, pokemon_id, ul_rank, ul_pct, final_form_max_cp FROM pokemon WHERE in_bag=1 AND ul_rank IS NOT NULL AND ul_rank<=10 AND final_form_max_cp IS NOT NULL AND final_form_max_cp>2425").fetchall()
bypid=defaultdict(list)
for r in rows: bypid[r[1]].append(r)
target=set()
for pid,l in bypid.items():
    l.sort(key=lambda x:(x[2], -(x[3] or 0)))
    for r in l[:2]: target.add(r[0])
def has(a,n): return a and n in [t for t in a.split(';') if t]
allr=cur.execute("SELECT uid_hex, auth_tag_names FROM pokemon WHERE in_bag=1").fetchall()
server={uh for uh,a in allr if has(a,'UL')}
to_add=target-server; to_remove=server-target
print(f"UL target={len(target)} server={len(server)} add={len(to_add)} remove={len(to_remove)}")

def us(uh):
    u=int(cur.execute('SELECT uid FROM pokemon WHERE uid_hex=?',(uh,)).fetchone()[0]); return str(u if u>=0 else u+2**64)

for attempt in range(10):
    try:
        sess,pid=pg.get_session(); s=pl.step_singletons(sess); SVC=s['svc']; BAG=s['bag']
        allu=list(to_add|to_remove)
        found=pg.find_protos_for_uids(sess, BAG, [us(u) for u in allu])
        bt=sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read()); bt.on('message',lambda m,d:None); bt.load(); bt.exports_sync.init_status()
        ft=bt.exports_sync.find_tag_id_by_name(SVC,'UL')
        addp=[found[us(u)] for u in to_add if us(u) in found]
        if addp:
            bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], addp[:1]); time.sleep(0.6)
            for i in range(0,len(addp),60): bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], addp[i:i+60]); time.sleep(0.3)
        rem=[found[us(u)] for u in to_remove if us(u) in found]
        if rem:
            try: bt.exports_sync.bulk_untag_one(SVC, rem[0], ft['tagProtoAddr']); time.sleep(0.5)  # warm-up
            except: pass
            for p in rem:
                try: bt.exports_sync.bulk_untag_one(SVC, p, ft['tagProtoAddr'])
                except: pass
                time.sleep(0.2)
        time.sleep(1.5)
        chk=bt.exports_sync.get_pokemon_for_tag(SVC, ft['idx'])
        print(f"server UL now={chk.get('dump',{}).get('+0x18_listish',{}).get('count')} (target {len(target)})")
        sess.detach(); break
    except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError, frida.ServerNotRunningError, RuntimeError) as e:
        print(f"[retry {attempt+1}] {type(e).__name__}"); time.sleep(4)
