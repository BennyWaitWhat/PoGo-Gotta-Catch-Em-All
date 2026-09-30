"""Find transfer/review candidates whose evolution would fill a dex gap (species not yet caught).
Reads live PokedexImpl via liveness API, builds evolution reachability from gamemaster."""
import frida, json, sqlite3, sys, time
sys.path.insert(0,'.')
import pogo_il2cpp as pg, pogo_pipeline as pl

# 1. Evolution reachability: pid -> set of pids reachable by evolving
gm = json.load(open('pvpoke_gamemaster.json'))
by_species = {p['speciesId']: p for p in gm['pokemon']}
sp_to_dex = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
def reachable_dex(species_id, seen=None):
    if seen is None: seen=set()
    p = by_species.get(species_id)
    if not p: return set()
    out=set()
    for ev in p.get('family',{}).get('evolutions',[]) or []:
        d = sp_to_dex.get(ev)
        if d: out.add(d)
        if ev not in seen:
            seen.add(ev); out |= reachable_dex(ev, seen)
    return out
# pid -> reachable target dexes (use base species form; map by dex)
dex_to_species = {}
for p in gm['pokemon']:
    d=p.get('dex')
    if d and d not in dex_to_species and '_shadow' not in p['speciesId']:
        dex_to_species[d]=p['speciesId']
pid_reach = {}
for d, sid in dex_to_species.items():
    pid_reach[d] = reachable_dex(sid)

# 2. Live dex caught set
sess, pid = pg.get_session()
dexaddr = pl.step_singletons(sess)['dex']
js = r"""
rpc.exports.caught = function(addr) {
  var inst=ptr(addr); var dict=inst.add(0x10).readPointer(); var entries=dict.add(0x18).readPointer();
  var maxLen=entries.add(0x18).readS32(); var data=entries.add(0x20); var out=[];
  for(var i=0;i<maxLen;i++){var ep=data.add(i*24); if(ep.readS32()<0)continue; var pidv=ep.add(8).readS32();
    var proto=ep.add(16).readPointer(); if(proto.isNull())continue;
    var times=proto.add(0x18).readS32(); out.push([pidv, times]); }
  return out;
};
"""
sc = pg.get_script_with_helpers(sess, js)
caught_rows = sc.exports_sync.caught(dexaddr)
caught_dex = set(p for p,t in caught_rows if t>0)
seen_dex = set(p for p,t in caught_rows)
print(f"dex: {len(caught_dex)} caught, {len(seen_dex)} seen")
sess.detach()

# 3. Cross-ref transfer + review candidates
c = sqlite3.connect('pokemon.db').cursor()
rows = c.execute("""SELECT uid_hex, species_name, pokemon_id, form, iv_total, cull_decision_v9, auth_tag_names
  FROM pokemon WHERE in_bag=1 AND (cull_decision_v9='TRANSFER' OR auth_tag_names LIKE '%REVIEW%')""").fetchall()
gap_protect = []
for uh, sp, pidv, form, iv, dec, tags in rows:
    targets = pid_reach.get(pidv, set())
    missing = [t for t in targets if t not in caught_dex]
    if missing:
        gap_protect.append((uh, sp, pidv, iv, dec, 'REVIEW' if tags and 'REVIEW' in tags else 'CLAUDE_TX', missing))
print(f"\nCandidates whose evolution fills a DEX GAP (should protect): {len(gap_protect)}")
for uh, sp, pidv, iv, dec, where, missing in sorted(gap_protect, key=lambda x:x[1]):
    miss_names = [dex_to_species.get(m, str(m)) for m in missing]
    print(f"  {sp:14s} iv={iv} [{where}] -> can evolve to UNCAUGHT: {miss_names}")
json.dump([g[0] for g in gap_protect], open('evo_gap_uids.json','w'))
print("\nSaved evo_gap_uids.json")
