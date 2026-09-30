"""Walk the live inventory Dictionary, categorize key types, and read:
 - candy per family (key.PokemonFamilyId -> value.PokemonFamily.Candy)
 - locate currency items (stardust / gimmighoul coins)
READ ONLY.

Inventory path:
  InventoryCache.GetCurrentItems() -> ValueCollection._dictionary @ +0x10
  Dictionary<HoloInventoryKeyProto, ClientInventoryItem<K,V>>
"""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

JS = r"""
function imgByName(name){_ensureInit();var sp=Memory.alloc(4);var asms=IL2.dGA(IL2.dG(),sp);var na=sp.readS32();
  for(var a=0;a<na;a++){var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());if(IL2.iGN(img).readCString()===name)return img;}return null;}
function gmCls(ns,name){var i=imgByName('holo-game.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
function protoCls(ns,name){var i=imgByName('holo-protos.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
var _oGC=null,_cGNm=null;
function _ii(){_ensureInit();if(_oGC)return;var il=Process.findModuleByName('libil2cpp.so');var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _oGC=b('il2cpp_object_get_class','pointer',['pointer']);
  _cGNm=b('il2cpp_class_get_name','pointer',['pointer']);}
function objCls(o){_ii();if(o.isNull())return 'null';try{return _cGNm(_oGC(o)).readCString();}catch(e){return '?';}}

function getDict(invAddr) {
    var k = gmCls('Niantic.Holoholo.Collections', 'InventoryCache');
    var m = cMN(k, 'GetCurrentItems', 0);
    var coll = rI(m, ptr(invAddr), ptr(0), null);
    if (coll.isNull()) return null;
    return coll.add(0x10).readPointer(); // ValueCollection._dictionary
}

// Walk a standard IL2CPP Dictionary<TKey(ref), TValue(ref)>.
// Dictionary fields (IL2CPP, 64-bit):
//   buckets @ 0x10, entries @ 0x18, count @ 0x28 (count includes free-list),
//   _count actual stored varies; we iterate entries[0..count) and skip hashCode<0.
// Entry struct {int hashCode; int next; TKey key; TValue value} stride 0x18, key@0x8, value@0x10.
function walkDict(dict, cb) {
    var entries = dict.add(0x18).readPointer();
    if (entries.isNull()) return 0;
    // Entry[] managed array length lives in the array header @ +0x18 (verified: 8419).
    var count = entries.add(0x18).readS32();
    if (count <= 0 || count > 500000) return 0;
    var arrBase = entries.add(0x20); // managed array data start
    var stride = 0x18;               // {int hash; int next; ref key; ref value} = 24 bytes (verified)
    var n = 0;
    for (var i = 0; i < count; i++) {
        var e = arrBase.add(i * stride);
        var hash = e.readS32();
        if (hash < 0) continue;       // empty/free slot
        var key = e.add(0x8).readPointer();
        var val = e.add(0x10).readPointer();
        if (key.isNull()) continue;
        cb(key, val);
        n++;
    }
    return n;
}

// HoloInventoryKeyProto accessors via methods (robust vs offset guessing for oneof):
function keyTypeCase(key) {
    var k = protoCls('Holoholo.Rpc', 'HoloInventoryKeyProto');
    var m = cMN(k, 'get_TypeCase', 0);
    try { var r = rI(m, key, ptr(0), null); return r.toInt32(); } catch(e){ return -999; }
}
function keyHasFamily(key) {
    var k = protoCls('Holoholo.Rpc', 'HoloInventoryKeyProto');
    var m = cMN(k, 'get_HasPokemonFamilyId', 0);
    try { var r = rI(m, key, ptr(0), null); return !!(r.toInt32()&0xff); } catch(e){ return false; }
}
function keyFamilyId(key) {
    var k = protoCls('Holoholo.Rpc', 'HoloInventoryKeyProto');
    var m = cMN(k, 'get_PokemonFamilyId', 0);
    try { var r = rI(m, key, ptr(0), null); return r.toInt32(); } catch(e){ return -1; }
}

// ClientInventoryItem<K,V>: holds Key and Data(value HoloInventoryItemProto).
// We'll read its fields generically by finding the HoloInventoryItemProto pointer inside it.
// Simpler: the dictionary VALUE is ClientInventoryItem; it has a field of type HoloInventoryItemProto.
// Probe candidate offsets to find a pointer whose class is HoloInventoryItemProto.
function findInvItem(clientItem) {
    if (clientItem.isNull()) return ptr(0);
    for (var off = 0x10; off <= 0x30; off += 0x8) {
        try {
            var p = clientItem.add(off).readPointer();
            if (!p.isNull() && objCls(p) === 'HoloInventoryItemProto') return p;
        } catch(e){}
    }
    return ptr(0);
}

// HoloInventoryItemProto.get_PokemonFamily() -> PokemonFamilyProto; .Candy @ +20
function itemFamilyCandy(item) {
    var k = protoCls('Holoholo.Rpc', 'HoloInventoryItemProto');
    var m = cMN(k, 'get_PokemonFamily', 0);
    try {
        var fam = rI(m, item, ptr(0), null);
        if (fam.isNull()) return null;
        return {famId: fam.add(16).readS32(), candy: fam.add(20).readS32(), xlCandy: fam.add(32).readS32()};
    } catch(e){ return null; }
}

rpc.exports.candy = function(invAddr, wantFamilies) {
    var dict = getDict(invAddr);
    if (!dict || dict.isNull()) return {err:'no dict'};
    var want = {}; for (var i=0;i<wantFamilies.length;i++) want[wantFamilies[i]]=true;
    var found = {};
    var total = 0;
    walkDict(dict, function(key, val){
        total++;
        if (keyHasFamily(key)) {
            var fid = keyFamilyId(key);
            if (want[fid]) {
                var item = findInvItem(val);
                var fc = item.isNull() ? null : itemFamilyCandy(item);
                found[fid] = fc;
            }
        }
    });
    return {ok:true, totalEntries: total, families: found};
};

// Categorize all key type-cases present (to locate stardust / gimmighoul coin storage).
rpc.exports.keycensus = function(invAddr) {
    var dict = getDict(invAddr);
    if (!dict || dict.isNull()) return {err:'no dict'};
    var census = {};
    var total = 0;
    walkDict(dict, function(key, val){
        total++;
        var tc = keyTypeCase(key);
        census[tc] = (census[tc]||0) + 1;
    });
    return {ok:true, total: total, census: census};
};
"""

# Family ids: Blipbug family = 824 (HoloPokemonFamilyId.FAMILY_BLIPBUG), Pawniard family = 624, Gimmighoul family = 999
WANT = [824, 624, 999]

def main():
    for attempt in range(10):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, JS)
            sc.exports_sync.init()
            inv = pg.find_singleton(sess, 'Niantic.Holoholo.Collections', 'InventoryCache')
            print(f"InventoryCache @ {inv}")
            census = sc.exports_sync.keycensus(inv)
            print(f"key census: total={census.get('total')} byTypeCase={census.get('census')}")
            cr = sc.exports_sync.candy(inv, WANT)
            print(f"\ncandy result: totalEntries={cr.get('totalEntries')}")
            print(f"families: {json.dumps(cr.get('families'), indent=2)}")
            json.dump({'census': census, 'candy': cr}, open('_walk_inventory_out.json','w'), indent=2)
            print("\nwrote _walk_inventory_out.json")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()
