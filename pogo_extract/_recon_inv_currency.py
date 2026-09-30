"""RECON 5: locate the live inventory cache + currency holders.
Strategy:
 - Find IInventoryCache / InventoryCache instance(s) via liveness.
 - InventoryCache.GetCurrentItems() -> collection of ClientInventoryItem<HoloInventoryKeyProto, HoloInventoryItemProto>.
 - For candy: key.PokemonFamilyId set -> item.PokemonFamily.Candy.
 - For currencies (stardust, gimmighoul coins): scan for the player currency holder.
Also enumerate any class whose name contains 'Player' + ('Currency'|'Profile'|'Data') and 'Currency'/'Stardust'.
READ ONLY."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

JS = r"""
function imgByName(name){_ensureInit();var sp=Memory.alloc(4);var asms=IL2.dGA(IL2.dG(),sp);var na=sp.readS32();
  for(var a=0;a<na;a++){var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());if(IL2.iGN(img).readCString()===name)return img;}return null;}
function gmCls(ns,name){var i=imgByName('holo-game.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}

// liveness for a holo-game.dll class
rpc.exports.live = function(ns, name) {
    var k = gmCls(ns, name);
    if (k.isNull()) return {err:'no class '+ns+'.'+name};
    return liveness_find_instances(k);
};

// Try InventoryCache.GetCurrentItems and count candy/currency items.
// IInventoryCache.GetCurrentItems returns ICollection<ClientInventoryItem<HoloInventoryKeyProto,HoloInventoryItemProto>>.
rpc.exports.invprobe = function(addr) {
    var k = gmCls('Niantic.Holoholo.Collections', 'InventoryCache');
    // GetCurrentItems(0)
    var m = cMN(k, 'GetCurrentItems', 0);
    if (!m) return {err:'no GetCurrentItems'};
    var coll;
    try { coll = rI(m, ptr(addr), ptr(0), null); }
    catch(e){ return {err:'GetCurrentItems threw: '+e.toString()}; }
    if (coll.isNull()) return {err:'null collection'};
    // It's likely a Dictionary.ValueCollection or List. Try to read count at a few common offsets.
    var info = {coll: coll.toString()};
    try { info.off10 = coll.add(0x10).readS32(); } catch(e){}
    try { info.off18 = coll.add(0x18).readS32(); } catch(e){}
    try { info.off20 = coll.add(0x20).readS32(); } catch(e){}
    return {ok:true, info: info};
};
"""

KW_TARGETS = [
    ('Niantic.Holoholo.Collections', 'InventoryCache'),
    ('Niantic.Holoholo.Collections', 'IInventoryCache'),
]

def main():
    for attempt in range(8):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, JS)
            sc.exports_sync.init()
            for ns, name in KW_TARGETS:
                r = sc.exports_sync.live(ns, name)
                if r.get('err'):
                    print(f"{ns}.{name}: {r['err']}")
                    continue
                hits = r.get('hits', [])
                print(f"{ns}.{name}: {len(hits)} instance(s) -> {hits[:8]}")
                for h in hits[:8]:
                    try:
                        ip = sc.exports_sync.invprobe(h)
                        print(f"    {h}: {ip}")
                    except Exception as e:
                        print(f"    {h}: probe err {e}")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()
