#!/usr/bin/env python
"""READ-ONLY inventory reader for PoGo live IL2CPP state.

Walks the InventoryCache dictionary (one dict holds the whole bag) and emits:
  - key-case histogram (so you see which oneof cases are present)
  - full item id -> count map  (case==2: ItemProto Item@+0x10 / Count@+0x14)   [CONFIRMED live]
  - per-family candy + XL      (case==10: PokemonFamilyProto Candy@+0x14 / XlCandy@+0x20) [CONFIRMED]
  - per-family MEGA ENERGY     (MegaEvolutionResources RepeatedField @ +0x18) -- the per-element
                                energy offset is the ONE unknown; this DUMPS the element class +
                                reflected fields + raw bytes + candidate ints so one run locks it. [DEVICE]
  - currencies stardust/coins  (IapService.get_Stardusts/get_Coins/get_PurchasedCoins) [stardust CONFIRMED]
  - a labelled WATCH subset (raid passes, rare candy, mega-energy families)

WRITES NOTHING. Writes _read_inventory_out.json only if --json given.

InventoryCache/IapService may be multi-instance; pick_singleton returns the FIRST hit for these
(no tuned probe). The script reports all liveness hits and picks the InventoryCache whose dict
walk yields the most entries (the _pick_real_bag idiom).

GOTCHA: family id == BASE species dex number. Mega Charizard energy is under family 4 (Charmander),
Mega Gyarados under 129 (Magikarp), Mega Mewtwo under 150. Do NOT query 6/94/130.

Usage:
    python read_inventory.py
    python read_inventory.py --json _read_inventory_out.json
    python read_inventory.py --mega-family 150   # focus the mega-energy element dump on a family
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
import pogo_il2cpp as pg  # noqa: E402

JSON_OUT = sys.argv[sys.argv.index('--json') + 1] if '--json' in sys.argv else None
MEGA_FAMILY = int(sys.argv[sys.argv.index('--mega-family') + 1]) if '--mega-family' in sys.argv else None

# item ids worth labelling in the watch subset (names from inventory_subsystem_recon.md;
# numeric ids are [DEVICE]-soft except where confirmed). 1150 = OtherEvolutionStoneA (confirmed).
WATCH_LABELS = {
    1: 'PokeBall', 2: 'GreatBall', 3: 'UltraBall', 4: 'MasterBall',
    101: 'Potion', 102: 'SuperPotion', 103: 'HyperPotion', 104: 'MaxPotion',
    201: 'Revive', 202: 'MaxRevive', 301: 'LuckyEgg', 401: 'IncenseOrdinary',
    501: 'TroyDisk', 602: 'XlRareCandy?', 705: 'RareCandy?', 1150: 'OtherEvolutionStoneA',
    1201: 'RemoteRaidPass?', 1202: 'PremiumRaidPass?', 1301: 'StarPiece',
}

READER_JS = r"""
var PROTO_IMAGE=null, OGC=null, CGN=null, CGF=null, FGN=null, FGO=null, FGTy=null, TGN=null;
function _proto(){ if(PROTO_IMAGE) return; _ensureInit();
  var il=Process.findModuleByName('libil2cpp.so'); function nf(n,r,a){ return new NativeFunction(il.getExportByName(n),r,a); }
  OGC=nf('il2cpp_object_get_class','pointer',['pointer']); CGN=nf('il2cpp_class_get_name','pointer',['pointer']);
  CGF=nf('il2cpp_class_get_fields','pointer',['pointer','pointer']); FGN=nf('il2cpp_field_get_name','pointer',['pointer']);
  FGO=nf('il2cpp_field_get_offset','uint32',['pointer']); FGTy=nf('il2cpp_field_get_type','pointer',['pointer']);
  TGN=nf('il2cpp_type_get_name','pointer',['pointer']);
  var sp=Memory.alloc(4); var asms=IL2.dGA(IL2.dG(),sp); var na=sp.readS32();
  for(var a=0;a<na;a++){ var im=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());
    if(IL2.iGN(im).readCString()==='holo-protos.dll'){ PROTO_IMAGE=im; break; } } }
function clsName(o){ try{ if(!o||o.isNull()) return null; return CGN(OGC(o)).readCString(); }catch(e){ return null; } }
function inv0(instPtr,name){ _proto(); if(!instPtr||instPtr.isNull()) return {ok:false};
  var m=cMN(OGC(instPtr),name,0); if(!m||m.isNull()) return {ok:false};
  try{ var ex=Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0)); var r=rI(m,instPtr,ptr(0),ex); return {ok:true,ret:r}; }catch(e){ return {ok:false,err:e.toString()}; } }
function box32(p){ try{ if(!p||p.isNull()) return null; return p.add(0x10).readS32(); }catch(e){ return null; } }

// get the backing dictionary from InventoryCache.GetCurrentItems()
function getDict(invAddr){
  var inv=ptr(invAddr);
  var m=cMN(IL2.cFN(GAME_IMAGE, Memory.allocUtf8String('Niantic.Holoholo.Collections'), Memory.allocUtf8String('InventoryCache')),'GetCurrentItems',0);
  if(!m||m.isNull()) return null;
  var ex=Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
  var coll=rI(m,inv,ptr(0),ex); if(coll.isNull()) return null;
  return coll.add(0x10).readPointer();   // _dictionary @ +0x10
}

// quick count for picking the real InventoryCache
rpc.exports.dictCount = function(invAddr){
  _proto(); try{ var dict=getDict(invAddr); if(!dict||dict.isNull()) return {ok:false,why:'no dict'};
    var entries=dict.add(0x18).readPointer(); if(entries.isNull()) return {ok:false,why:'no entries'};
    return {ok:true, n: entries.add(0x18).readS32()}; }catch(e){ return {ok:false, err:e.toString()}; }
};

rpc.exports.readInventory = function(invAddr, megaFamily){
  _proto();
  var dict=getDict(invAddr); if(!dict||dict.isNull()) return {error:'null dict'};
  var entries=dict.add(0x18).readPointer(); var count=entries.add(0x18).readS32();
  var caseHist={}, items={}, families={}, megaDump=null, samples={};
  for(var i=0;i<count;i++){
    var e=entries.add(0x20).add(i*0x18);   // entry array begins at entries+0x20, stride 0x18
    var hash=e.add(0x0).readS32(); if(hash<0) continue;
    var key=e.add(0x8).readPointer(); var val=e.add(0x10).readPointer();
    if(key.isNull()||val.isNull()) continue;
    var kcase=key.add(0x18).readS32();
    caseHist[kcase]=(caseHist[kcase]||0)+1;
    if(kcase===2){ // ITEM
      var vi=inv0(val,'get_Item'); if(vi.ok&&vi.ret&&!vi.ret.isNull()){
        var id=vi.ret.add(0x10).readS32(); var ct=vi.ret.add(0x14).readS32(); items[id]=ct; }
    } else if(kcase===10){ // POKEMON FAMILY (candy/xl/mega energy)
      var vf=inv0(val,'get_PokemonFamily'); if(vf.ok&&vf.ret&&!vf.ret.isNull()){ var fp=vf.ret;
        var fam=fp.add(0x10).readS32(); var candy=fp.add(0x14).readS32(); var xl=fp.add(0x20).readS32();
        var rec={candy:candy, xl:xl, megaEnergy:[]};
        // MegaEvolutionResources RepeatedField @ +0x18
        try{ var rf=fp.add(0x18).readPointer(); if(rf&&!rf.isNull()){ var arr=rf.add(0x10).readPointer(); var mc=rf.add(0x18).readS32();
          if(arr&&!arr.isNull()&&mc>0&&mc<50){ for(var m2=0;m2<mc;m2++){ var el=arr.add(0x20).add(m2*8).readPointer(); if(el.isNull()) continue;
            // try getters first (likely absent), then candidate raw ints
            var teId=inv0(el,'get_TemporaryEvolutionId'); var amt=inv0(el,'get_Amount');
            var maxe=inv0(el,'get_MaxEnergyCount');
            var em={tempEvoId: teId.ok?box32(teId.ret):null,
                    amount: amt.ok?box32(amt.ret):(maxe.ok?box32(maxe.ret):null),
                    raw:{}};
            [0x10,0x14,0x18,0x1c,0x20].forEach(function(o){ try{ em.raw['i@'+o.toString(16)]=el.add(o).readS32(); }catch(e){} });
            rec.megaEnergy.push(em);
            // one-time deep dump (class + reflected fields + bytes) for offset locking
            if(!megaDump && (megaFamily===0 || fam===megaFamily)){ megaDump={family:fam, elemCls:clsName(el), fields:[], bytes:''};
              var fcls=OGC(el); var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
              while((f=CGF(fcls,it)) && !f.isNull()){ try{ megaDump.fields.push({name:FGN(f).readCString(), off:FGO(f), type:TGN(FGTy(f)).readCString()}); }catch(e){} }
              try{ var bb=el.readByteArray(0x40); megaDump.bytes=Array.prototype.map.call(new Uint8Array(bb),function(b){return ('0'+b.toString(16)).slice(-2);}).join(' '); }catch(e){}
            }
          } } } }catch(e){ rec.megaErr=e.toString(); }
        families[fam]=rec; }
    } else { // sample one value of each other case for later decode
      if(!samples[kcase]){ var sc={cls:clsName(val), bytes:''}; try{ var bb=val.readByteArray(0x30);
        sc.bytes=Array.prototype.map.call(new Uint8Array(bb),function(b){return ('0'+b.toString(16)).slice(-2);}).join(' '); }catch(e){} samples[kcase]=sc; }
    }
  }
  return {entryCount:count, caseHist:caseHist, items:items, families:families, megaDump:megaDump, otherCaseSamples:samples};
};

// currencies via IapService
rpc.exports.readCurrencies = function(iapAddr){
  _proto(); var p=ptr(iapAddr); var out={};
  var cls=IL2.cFN(GAME_IMAGE, Memory.allocUtf8String('Niantic.Holoholo.Storefront'), Memory.allocUtf8String('IapService'));
  ['get_Stardusts','get_Coins','get_PurchasedCoins'].forEach(function(nm){
    try{ var m=cMN(cls,nm,0); if(!m||m.isNull()){ out[nm]=null; return; }
      var ex=Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0)); var r=rI(m,p,ptr(0),ex);
      out[nm]= (r&&!r.isNull()) ? r.add(0x10).readS32() : null; }catch(e){ out[nm]='err:'+e.toString(); }
  });
  return out;
};
"""


def _pick_real_inventory(sess, sc, ns, cls):
    """Return the InventoryCache instance with the largest dict; report all hits."""
    probe = pg.get_script_with_helpers(sess)
    try:
        r = probe.exports_sync.find_singleton(ns, cls)
    finally:
        probe.unload()
    if 'err' in r:
        return None, []
    hits = r.get('hits', [])
    best, best_n = None, -1
    for h in hits:
        try:
            d = sc.exports_sync.dict_count(h)
            n = d.get('n', -1) if d.get('ok') else -1
            if n > best_n:
                best, best_n = h, n
        except Exception:
            pass
    return best, hits


def main():
    print('[*] connecting...')
    sess, pid = pg.get_session()
    print(f'[*] attached pid={pid}')
    sc = pg.get_script_with_helpers(sess, READER_JS)

    inv, inv_hits = _pick_real_inventory(sess, sc, 'Niantic.Holoholo.Collections', 'InventoryCache')
    print(f'[*] InventoryCache liveness hits: {inv_hits}; chosen: {inv}')
    if not inv:
        print('[!] no usable InventoryCache instance.')
        sc.unload()
        sess.detach()
        sys.exit(1)

    res = sc.exports_sync.read_inventory(inv, MEGA_FAMILY if MEGA_FAMILY is not None else 0)

    # currencies (first IapService hit)
    curr = None
    iprobe = pg.get_script_with_helpers(sess)
    try:
        ir = iprobe.exports_sync.find_singleton('Niantic.Holoholo.Storefront', 'IapService')
        ihits = ir.get('hits', []) if 'err' not in ir else []
    finally:
        iprobe.unload()
    if ihits:
        curr = sc.exports_sync.read_currencies(ihits[0])

    sc.unload()
    sess.detach()

    if 'error' in res:
        print('[!]', res['error'])
        sys.exit(1)

    print(f"\n=== INVENTORY ({res['entryCount']} dict entries) ===")
    print('\n--- key-case histogram (oneof TypeCase) ---')
    for k in sorted(res['caseHist'], key=lambda x: int(x)):
        tag = {'2': 'Item', '4': 'PlayerStats', '5': 'PlayerCurrency', '10': 'PokemonFamily'}.get(str(k), '?')
        print(f'  case {k:>3} ({tag}): {res["caseHist"][k]}')

    items = {int(k): v for k, v in res['items'].items()}
    print(f'\n--- ITEMS ({len(items)}) [id -> count] ---')
    for iid in sorted(items):
        lbl = WATCH_LABELS.get(iid, '')
        print(f'  {iid:>5}  x{items[iid]:<6} {lbl}')

    print('\n--- WATCH subset (passes / candy / stones) ---')
    for iid in sorted(items):
        if iid in WATCH_LABELS:
            print(f'  {WATCH_LABELS[iid]:24s} id={iid} x{items[iid]}')

    fams = {int(k): v for k, v in res['families'].items()}
    print(f'\n--- FAMILIES candy/XL/mega ({len(fams)}) ---')
    for fam in sorted(fams):
        r = fams[fam]
        meflag = ''
        if r.get('megaEnergy'):
            meflag = '  MEGA_ENERGY=' + json.dumps(r['megaEnergy'])
        print(f'  fam {fam:>4}  candy={r["candy"]:<6} xl={r["xl"]:<6}{meflag}')

    if res.get('megaDump'):
        print('\n--- MEGA ENERGY element dump (LOCK THE OFFSET HERE) [DEVICE] ---')
        md = res['megaDump']
        print(f"  family={md['family']}  elemCls={md['elemCls']}")
        print('  reflected fields (name @ offset : type):')
        for f in md.get('fields', []):
            print(f"    {f['name']:28s} @{hex(f['off'])}  {f['type']}")
        print(f"  first-element bytes[0x40]: {md.get('bytes')}")
        print('  -> the energy quantity is one of the int@ candidates printed in megaEnergy.raw above;')
        print('     match it to the in-game Mega Energy number for this family to lock the offset.')

    if res.get('otherCaseSamples'):
        print('\n--- other-case value samples (RaidTickets/Incubators/EventPasses/...) [DEVICE] ---')
        for k, s in res['otherCaseSamples'].items():
            print(f'  case {k}: cls={s.get("cls")} bytes={s.get("bytes")}')

    if curr:
        print('\n--- CURRENCIES (IapService) ---')
        print(f'  Stardust:      {curr.get("get_Stardusts")}')
        print(f'  Coins:         {curr.get("get_Coins")}')
        print(f'  PurchasedCoins:{curr.get("get_PurchasedCoins")}')

    if JSON_OUT:
        with open(JSON_OUT, 'w', encoding='utf-8') as fh:
            json.dump({'inventory': res, 'currencies': curr}, fh, indent=2)
        print(f'\n[*] wrote {JSON_OUT}')
    print('\n[NOTE] item enum numeric ids + the mega-energy element offset are [DEVICE]-flagged. '
          'Lock the mega offset from the element dump, then it is permanent for this binary.')


if __name__ == '__main__':
    main()
