"""Live account snapshot via IL2CPP introspection (account_snapshot.js engine).
Self-healing attach. Dumps account_snapshot_raw.json (all multi-interpreted reads)
+ account_snapshot.json (clean) + ACCOUNT_REPORT.md. Frida = single slot."""
import frida, json, time, sqlite3, sys
sys.path.insert(0, '.')
import pogo_il2cpp as pg

EXTRA_JS = open('account_snapshot.js', 'r', encoding='utf-8').read()

# (facet, ns, cls): singleton services to introspect
SERVICES = [
    ('player',  'Niantic.Holoholo',            'PlayerService'),
    ('iap',     'Niantic.Holoholo.Storefront',  'IapService'),
    ('itembag', 'Niantic.Holoholo.Internal',    'ItemBagImpl'),
    ('buddy',   'Niantic.Holoholo.Buddy',       'BuddyPokemonService'),
    ('buddystats','Niantic.Holoholo.Buddy',     'BuddyStatsService'),
    ('friends', 'Niantic.Holoholo.Social',      'FriendsRpcService'),
]
# 0-arg getters per (ns,cls). Value 'proto' => follow ptr + read fields of given proto class.
GETTERS = {
    ('Niantic.Holoholo','PlayerService'): [
        ('get_PlayerName', 'str'), ('get_PlayerStats', ('Holoholo.Rpc','PlayerStatsProto')),
        ('get_LevelProgress', ('Niantic.Holoholo','PlayerService+PlayerLevelProgress')),
    ],
    ('Niantic.Holoholo.Storefront','IapService'): [
        ('get_Coins','i32'), ('get_PurchasedCoins','i32'), ('get_Stardusts','i64'),
    ],
    ('Niantic.Holoholo.Internal','ItemBagImpl'): [('get_MaxItems','i32')],
    ('Niantic.Holoholo.Buddy','BuddyPokemonService'): [('get_BuddyLevel','i32')],
    ('Niantic.Holoholo.Social','FriendsRpcService'): [('get_MaxFriends','i32')],
}
# (ns,cls, method, [int args]) for 1-int-arg calls
ITEM_IDS = [1,2,3,101,102,103,104,201,202,301,401,501,701,703,705,706,708,902,1101,1102,1103,1104,1105,1106,1107,1150,1301,1302,1303,1404,1405,1406]
CANDY_FAMILY_FROM_DB = True  # call GetCandyCountForPokemonFamily for distinct pokemon_id in bag

def pick(multi, kind):
    if not isinstance(multi, dict): return multi
    if 'err' in multi: return multi
    if kind == 'str': return multi.get('str') or multi.get('ptr')
    return multi.get(kind, multi)

def run():
    raw = {}
    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, EXTRA_JS)
    print(f'[attach pid={pid}] engine loaded')
    inst = {}
    for facet, ns, cls in SERVICES:
        try:
            r = sc.exports_sync.find_all(ns, cls)
            hits = r.get('hits', []) if isinstance(r, dict) else []
            raw.setdefault(facet, {})['_find'] = r
            if hits:
                inst[(ns, cls)] = hits[0]
                print(f'  {facet:11s} {cls:24s} hits={len(hits)} inst={hits[0]}')
            else:
                print(f'  {facet:11s} {cls:24s} NO HITS ({r})')
        except Exception as e:
            print(f'  {facet:11s} {cls:24s} ERR {e}'); raw.setdefault(facet, {})['_find_err'] = str(e)

    # 0-arg getters
    for (ns, cls), getters in GETTERS.items():
        ip = inst.get((ns, cls))
        if not ip: continue
        for name, kind in getters:
            try:
                m = sc.exports_sync.call_getter(ns, cls, name, ip)
                raw.setdefault(_facet_of(ns, cls), {})[name] = m
                if isinstance(kind, tuple) and isinstance(m, dict) and m.get('ptr'):
                    pns, pcls = kind
                    fields = sc.exports_sync.read_fields_at(m['ptr'], pns, pcls)
                    raw.setdefault(_facet_of(ns, cls), {})[name + '_fields'] = fields
                    print(f'    {name} -> proto {pcls} ({len(fields) if isinstance(fields,dict) else fields} fields)')
                else:
                    print(f'    {name} = {pick(m, kind if isinstance(kind,str) else "ptr")}')
            except Exception as e:
                print(f'    {name} ERR {e}')

    # ItemBagImpl int-arg: item counts
    ib = inst.get(('Niantic.Holoholo.Internal', 'ItemBagImpl'))
    if ib:
        items = {}
        for iid in ITEM_IDS:
            try:
                m = sc.exports_sync.call_int_arg('Niantic.Holoholo.Internal', 'ItemBagImpl', 'GetItemCount', ib, iid)
                c = m.get('i32') if isinstance(m, dict) else None
                if c: items[iid] = c
            except Exception: pass
        raw.setdefault('itembag', {})['items'] = items
        print(f'    items with count>0: {len(items)}  (gimmighoul 1150={items.get(1150)})')
        # candy per family
        if CANDY_FAMILY_FROM_DB:
            try:
                cur = sqlite3.connect('pokemon.db').cursor()
                fams = sorted({r[0] for r in cur.execute('SELECT DISTINCT pokemon_id FROM pokemon WHERE in_bag=1') if r[0]})
            except Exception: fams = []
            candy = {}
            for fid in fams:
                try:
                    m = sc.exports_sync.call_int_arg('Niantic.Holoholo.Internal', 'ItemBagImpl', 'GetCandyCountForPokemonFamily', ib, fid)
                    c = m.get('i32') if isinstance(m, dict) else None
                    if c: candy[fid] = c
                except Exception: pass
            raw.setdefault('itembag', {})['candy'] = candy
            print(f'    candy families with count>0: {len(candy)}')

    sess.detach()
    json.dump(raw, open('account_snapshot_raw.json', 'w'), indent=1, default=str)
    print('wrote account_snapshot_raw.json')
    return raw

def _facet_of(ns, cls):
    for f, n, c in SERVICES:
        if n == ns and c == cls: return f
    return cls

if __name__ == '__main__':
    for attempt in range(6):
        try:
            run(); break
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f'[retry {attempt+1}] {type(e).__name__}: {e}'); time.sleep(4)
