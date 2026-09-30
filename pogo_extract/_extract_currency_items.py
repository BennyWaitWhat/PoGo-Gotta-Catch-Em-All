"""Read: Gimmighoul Coin item (Item 1150) count, all Item-key counts of interest,
PlayerStats (to locate stardust), and re-extract Dottler(825)->Orbeetle evo branch.
READ ONLY."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

JS = r"""
function imgByName(name){_ensureInit();var sp=Memory.alloc(4);var asms=IL2.dGA(IL2.dG(),sp);var na=sp.readS32();
  for(var a=0;a<na;a++){var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());if(IL2.iGN(img).readCString()===name)return img;}return null;}
function gmCls(ns,name){var i=imgByName('holo-game.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
function protoCls(ns,name){var i=imgByName('holo-protos.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
var _oGC=null,_cGNm=null,_mGpc=null;
function _ii(){_ensureInit();if(_oGC)return;var il=Process.findModuleByName('libil2cpp.so');var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _oGC=b('il2cpp_object_get_class','pointer',['pointer']);_cGNm=b('il2cpp_class_get_name','pointer',['pointer']);
  _mGpc=b('il2cpp_method_get_param_count','uint32',['pointer']);}
function objCls(o){_ii();if(o.isNull())return 'null';try{return _cGNm(_oGC(o)).readCString();}catch(e){return '?';}}
function readStr(p){if(p.isNull())return '';var len=p.add(0x10).readS32();if(len<=0||len>400)return '';var s='';for(var i=0;i<len;i++)s+=String.fromCharCode(p.add(0x14+i*2).readU16());return s;}

function getDict(invAddr){var k=gmCls('Niantic.Holoholo.Collections','InventoryCache');var m=cMN(k,'GetCurrentItems',0);
  var coll=rI(m,ptr(invAddr),ptr(0),null);if(coll.isNull())return null;return coll.add(0x10).readPointer();}
function walk(dict,cb){var en=dict.add(0x18).readPointer();if(en.isNull())return 0;var c=en.add(0x18).readS32();
  var base=en.add(0x20);var n=0;for(var i=0;i<c;i++){var e=base.add(i*0x18);if(e.readS32()<0)continue;
    var key=e.add(8).readPointer();var val=e.add(0x10).readPointer();if(key.isNull())continue;if(cb(key,val,i)===false)return n;n++;}return n;}
function resolveItem(ci){for(var base=0x10;base<=0x18;base+=8){var model=ci.add(base).readPointer();if(model.isNull())continue;
  var gi=model.add(0x10).readPointer();if(!gi.isNull()&&objCls(gi)==='HoloInventoryItemProto')return gi;}return ptr(0);}
function unboxI32(boxptr){if(boxptr.isNull())return null;return boxptr.add(0x10).readS32();}

// Read all Item-keyed entries: key.get_Item -> Item enum; item.get_Item -> ItemProto.Count
rpc.exports.items = function(invAddr, wantItems){
    var dict=getDict(invAddr);if(!dict||dict.isNull())return{err:'no dict'};
    var keyCls=protoCls('Holoholo.Rpc','HoloInventoryKeyProto');
    var itemCls=protoCls('Holoholo.Rpc','HoloInventoryItemProto');
    var getItemKey=cMN(keyCls,'get_Item',0);          // returns Item enum (boxed)
    var getItemVal=cMN(itemCls,'get_Item',0);          // returns ItemProto
    var want={};for(var i=0;i<wantItems.length;i++)want[wantItems[i]]=true;
    var found={};var allItemKeys={};
    walk(dict,function(key,val){
        if(key.add(24).readS32()!==2)return true; // Item case = 2
        var itemEnum=null;try{var r=rI(getItemKey,key,ptr(0),null);itemEnum=unboxI32(r);}catch(e){}
        if(itemEnum===null)return true;
        allItemKeys[itemEnum]=(allItemKeys[itemEnum]||0)+1;
        if(!want[itemEnum])return true;
        var item=resolveItem(val);
        if(item.isNull()){found[itemEnum]={err:'no item'};return true;}
        var ip;try{ip=rI(getItemVal,item,ptr(0),null);}catch(e){found[itemEnum]={err:'threw'};return true;}
        if(ip.isNull()){found[itemEnum]={err:'null itemproto'};return true;}
        // ItemProto: Item enum @ +16, Count @ +20 (typical). Dump a few.
        found[itemEnum]={itemProtoCls:objCls(ip), w16:ip.add(16).readS32(), w20:ip.add(20).readS32(), w24:ip.add(24).readS32()};
        return true;
    });
    return {ok:true, wanted:found, allItemEnums:allItemKeys};
};

// PlayerStats full int dump (to find stardust)
rpc.exports.playerstats = function(invAddr){
    var dict=getDict(invAddr);var itemCls=protoCls('Holoholo.Rpc','HoloInventoryItemProto');
    var m=cMN(itemCls,'get_PlayerStats',0);var res=null;
    walk(dict,function(key,val){
        if(key.add(24).readS32()!==4)return true;
        var item=resolveItem(val);if(item.isNull()){res={err:'no item'};return false;}
        var st;try{st=rI(m,item,ptr(0),null);}catch(e){res={err:'threw '+e};return false;}
        if(st.isNull()){res={err:'null'};return false;}
        var w=[];for(var o=16;o<=440;o+=4){var v=st.add(o).readS32();w.push([o,v]);}
        res={ok:true,cls:objCls(st),level:st.add(16).readS32(),words:w};return false;
    });
    return res||{none:true};
};

// Re-read Dottler(825) evolution branch via GameMasterData
rpc.exports.dottlerEvo = function(gmAddr){
    var gmk=gmCls('','GameMasterData');var m=null;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var mm;
    while((mm=IL2.cGM(gmk,it))&&!mm.isNull()){if(IL2.mGN(mm).readCString()==='Get_PokemonSettings'){_ii();if((_mGpc?_mGpc(mm):-1)===1){m=mm;break;}}}
    if(!m)return{err:'no 1-arg'};
    var idBuf=Memory.alloc(4);idBuf.writeS32(825);var args=Memory.alloc(Process.pointerSize);args.writePointer(idBuf);
    var s;try{s=rI(m,ptr(gmAddr),args,null);}catch(e){return{err:'threw '+e};}
    if(s.isNull())return{found:false};
    var out={found:true,familyId:s.add(120).readS32(),candyToEvolve:s.add(124).readS32(),kmBuddy:s.add(128).readFloat()};
    var brRf=s.add(144).readPointer();var bc=brRf.isNull()?0:brRf.add(0x18).readS32();var arr=brRf.isNull()?null:brRf.add(0x10).readPointer();
    var branches=[];
    for(var b=0;b<bc&&b<20;b++){var br=arr.add(0x20+b*8).readPointer();if(br.isNull())continue;
        branches.push({evolution:br.add(16).readS32(),candyCost:br.add(24).readS32(),itemReq:br.add(20).readS32(),
          itemReqCost:br.add(92).readS32(),kmBuddyReq:br.add(28).readFloat(),mustBeBuddy:!!br.add(44).readU8(),
          lureReq:br.add(40).readS32(),tempEvo:br.add(56).readS32()});}
    out.branches=branches;return out;
};
"""

# Item enum: Gimmighoul Coin = 1150 (from evo branch itemReq). Also probe nearby + pokecoin-ish.
WANT_ITEMS = [1150, 1151, 1152]

def main():
    for attempt in range(8):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, JS)
            sc.exports_sync.init()
            inv = pg.find_singleton(sess, 'Niantic.Holoholo.Collections', 'InventoryCache')
            gm = pg.find_singleton(sess, '', 'GameMasterData')
            print(f"inv={inv} gm={gm}")

            de = sc.exports_sync.dottler_evo(gm)
            print("\n=== Dottler(825) -> evo branch ===")
            print(json.dumps(de, indent=2))

            it = sc.exports_sync.items(inv, WANT_ITEMS)
            print("\n=== Items (1150=GimmighoulCoin candidate) ===")
            print(f"wanted: {json.dumps(it.get('wanted'))}")
            # show all item enums sorted
            ae = it.get('allItemEnums', {})
            print(f"all item enum keys present (count={len(ae)}): {sorted(int(k) for k in ae.keys())}")

            ps = sc.exports_sync.playerstats(inv)
            print("\n=== PlayerStats (scan for stardust) ===")
            if ps.get('ok'):
                # print non-zero words
                nz = [(o,v) for o,v in ps['words'] if v != 0]
                print(f"level={ps['level']} nonzero_fields:")
                for o,v in nz:
                    print(f"   +{o}: {v}")
            else:
                print(ps)
            json.dump({'dottler':de,'items':it,'playerstats':ps}, open('_currency_items_out.json','w'), indent=2)
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()
