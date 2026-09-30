"""One-pass probe: enumerate getters + dump object fields for each service/proto."""
import frida, json, time, sys
sys.path.insert(0, '.')
import pogo_il2cpp as pg
EXTRA_JS = open('account_snapshot.js', encoding='utf-8').read()

SERVICES = [
    ('player','Niantic.Holoholo','PlayerService'),
    ('iap','Niantic.Holoholo.Storefront','IapService'),
    ('itembag','Niantic.Holoholo.Internal','ItemBagImpl'),
    ('buddy','Niantic.Holoholo.Buddy','BuddyPokemonService'),
    ('buddystats','Niantic.Holoholo.Buddy','BuddyStatsService'),
    ('friends','Niantic.Holoholo.Social','FriendsRpcService'),
]
def run():
    out={}
    sess,pid=pg.get_session(); sc=pg.get_script_with_helpers(sess, EXTRA_JS)
    print('attach',pid)
    for facet,ns,cls in SERVICES:
        d={}
        r=sc.exports_sync.find_all(ns,cls); hits=r.get('hits',[]) if isinstance(r,dict) else []
        d['hits']=hits
        ms=sc.exports_sync.enum_methods(ns,cls)
        d['getters']=[m for m in ms if isinstance(m,dict) and m.get('name','').startswith('get_')] if isinstance(ms,list) else ms
        # read fields of each hit (object-class based)
        d['hit_fields']=[]
        for h in hits[:2]:
            d['hit_fields'].append(sc.exports_sync.read_obj_fields(h))
        out[facet]=d
        print(f'{facet}: hits={len(hits)} getters={len(d["getters"]) if isinstance(d["getters"],list) else d["getters"]}')
    # follow player protos
    pl=out['player']['hits']
    if pl:
        ip=pl[0]
        for g in ['get_PlayerStats','get_LevelProgress','get_PlayerProto','get_PlayerDay','get_CachedPlayerInfo']:
            m=sc.exports_sync.call_getter('Niantic.Holoholo','PlayerService',g,ip)
            if isinstance(m,dict) and m.get('ptr'):
                out.setdefault('player_protos',{})[g]=sc.exports_sync.read_obj_fields(m['ptr'])
                print(f'  {g} -> {out["player_protos"][g].get("className") if isinstance(out["player_protos"][g],dict) else "?"}')
    # buddy proto
    bs=out['buddystats']['hits']
    if bs:
        m=sc.exports_sync.call_getter('Niantic.Holoholo.Buddy','BuddyStatsService','get_BuddyStats',bs[0])
        if isinstance(m,dict) and m.get('ptr'): out['buddystats_proto']=sc.exports_sync.read_obj_fields(m['ptr'])
    bp=out['buddy']['hits']
    if bp:
        m=sc.exports_sync.call_getter('Niantic.Holoholo.Buddy','BuddyPokemonService','get_BuddyPokemon',bp[0])
        if isinstance(m,dict) and m.get('ptr'): out['buddy_proto']=sc.exports_sync.read_obj_fields(m['ptr'])
    sess.detach()
    json.dump(out, open('_probe_out.json','w'), indent=1, default=str)
    print('wrote _probe_out.json')

for a in range(6):
    try: run(); break
    except (frida.InvalidOperationError,frida.TransportError,frida.ProcessNotFoundError,frida.ServerNotRunningError,RuntimeError) as e:
        print('retry',a,type(e).__name__,e); time.sleep(4)
