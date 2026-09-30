"""read_inventory.py -- DRAFT read-only inventory dumper for PoGo IL2CPP.

Dumps the live inventory the player bag reads from:
  * per-item counts (balls/berries/passes/rare candy/etc.) -- item_id -> count
  * Remote/Premium raid passes (item ids) + RaidTickets oneof case
  * per-family candy + XL candy
  * per-family MEGA ENERGY (PokemonFamilyProto.MegaEvolutionResources[])
  * Stardust / PokeCoins (IapService getters)

STATIC-VALIDATED facts baked in (sources in
system/analysis/game_read_recon/inventory_subsystem_recon.md):
  InventoryCache.GetCurrentItems()      -> ValueCollection, _dictionary @ +0x10
  Dictionary<HoloInventoryKeyProto, ClientInventoryItem>
     entries @ +0x18 ; array-len @ entries+0x18 ; entry stride 0x18
     entry = {int hash; int next; ref key; ref value}  key@+0x8 value@+0x10
  HoloInventoryKeyProto:  payload @ +0x10 , TypeOneofCase (int) @ +0x18
  HoloInventoryItemProto: payload @ +0x10 , TypeOneofCase (int) @ +0x18
  ItemProto:            Item enum @ +0x10 , Count @ +0x14 , Unseen @ +0x18   (CONFIRMED live: item1150 count=2731)
  PokemonFamilyProto:   FamilyId @ +0x10 , Candy @ +0x14 ,
                        MegaEvolutionResources RepeatedField @ +0x18 , XlCandy @ +0x20   (CONFIRMED live candy/xl)
  RepeatedField<T>:     items-array @ +0x10 , count @ +0x18 , element[i] @ array+0x20+i*8 (ref) / +i*stride (value)

DEVICE-VALIDATION-NEEDED (flagged inline with VALIDATE:):
  * TemporaryEvolutionResourceProto element layout (mega energy amount field offset) -- NOT in any static dump.
    We dump raw element bytes + reflect field offsets at runtime so the lead can confirm.
  * ItemBagImpl.GetItemCount / GetCandyCountForPokemonFamily / GetXlCandyCountForPokemonFamily method path
    (cleaner than the dict walk; method *names* confirmed in metadata, invocation unproven).
  * IapService.get_Coins / get_PurchasedCoins (get_Stardusts confirmed working elsewhere).
  * The Key TypeOneofCase numeric constants (Item=2, PlayerStats=4, PlayerCurrency=5, PokemonFamilyId=10)
    are from prior *working* runs; re-asserted by the key-census dump.

READ ONLY. No writes, no tag ops. Single attach, single dict walk.
"""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

# --------------------------------------------------------------------------
# Targets. CRITICAL: a PoGo family id is the dex number of the family's BASE
# species, NOT the mega form. e.g. Mega Charizard energy lives under family 4
# (Charmander), Mega Gengar under 92 (Gastly), Mega Beedrill under 13 (Weedle).
# These ids were extracted from the live HoloPokemonFamilyId enum
# (proto_layout.json: VNNNNFamily<BaseSpecies>) -- label = mega form for clarity.
# Edit freely. (Slowbro/Blastoise share fam 7/79 with their line's other megas.)
# --------------------------------------------------------------------------
MEGA_ENERGY_FAMILIES = {
    4: 'Charizard (Charmander fam)', 7: 'Blastoise (Squirtle fam)',
    13: 'Beedrill (Weedle fam)', 16: 'Pidgeot (Pidgey fam)',
    63: 'Alakazam (Abra fam)', 79: 'Slowbro (Slowpoke fam)',
    92: 'Gengar (Gastly fam)', 95: 'Steelix (Onix fam)',
    115: 'Kangaskhan', 123: 'Scizor (Scyther fam)', 127: 'Pinsir',
    129: 'Gyarados (Magikarp fam)', 142: 'Aerodactyl', 150: 'Mewtwo',
    179: 'Ampharos (Mareep fam)', 214: 'Heracross',
    228: 'Houndoom (Houndour fam)', 246: 'Tyranitar (Larvitar fam)',
    252: 'Sceptile (Treecko fam)', 255: 'Blaziken (Torchic fam)',
    258: 'Swampert (Mudkip fam)', 280: 'Gardevoir/Gallade (Ralts fam)',
    302: 'Sableye', 303: 'Mawile', 304: 'Aggron (Aron fam)',
    307: 'Medicham (Meditite fam)', 309: 'Manectric (Electrike fam)',
    318: 'Sharpedo (Carvanha fam)', 322: 'Camerupt (Numel fam)',
    333: 'Altaria (Swablu fam)', 353: 'Banette (Shuppet fam)',
    359: 'Absol', 361: 'Glalie (Snorunt fam)', 371: 'Salamence (Bagon fam)',
    374: 'Metagross (Beldum fam)', 380: 'Latias', 381: 'Latios',
    384: 'Rayquaza', 427: 'Lopunny (Buneary fam)', 443: 'Garchomp (Gible fam)',
    448: 'Lucario (Riolu fam)', 459: 'Abomasnow (Snover fam)',
}

# Item ids of interest. From metadata + prior live census. Names per IL2CPP enum.
# (full enum census is dumped too; this is just the labelled subset.)
WATCH_ITEMS = {
    1: 'PokeBall', 2: 'GreatBall', 3: 'UltraBall', 4: 'MasterBall',
    101: 'Potion', 102: 'SuperPotion', 103: 'HyperPotion', 104: 'MaxPotion',
    201: 'Revive', 202: 'MaxRevive',
    301: 'LuckyEgg', 401: 'IncenseOrdinary', 501: 'TroyDisk',
    701: 'RazzBerry', 703: 'NanabBerry', 705: 'PinapBerry', 706: 'GoldenRazzBerry',
    708: 'GoldenPinapBerry', 709: 'GoldenNanabBerry',
    902: 'RareCandy',          # VALIDATE: confirm 902 == RareCandy on device (see notes)
    1101: 'SunStone', 1102: 'KingsRock', 1103: 'MetalCoat', 1104: 'DragonScale',
    1106: 'UpGrade',
    1201: 'FastTM', 1202: 'ChargedTM', 1203: 'ChargedTMRare', 1204: 'FastTMRare',
    1301: 'Incubator', 1302: 'IncubatorSuper',
    1402: 'StarPiece', 1404: 'PremiumRaidTicket',     # VALIDATE numeric ids
    1408: 'RemoteRaidTicket', 1410: 'XlRareCandy',     # VALIDATE numeric ids
    1150: 'OtherEvolutionStoneA',                      # CONFIRMED live (count 2731)
}

JS = r"""
function imgByName(name){_ensureInit();var sp=Memory.alloc(4);var asms=IL2.dGA(IL2.dG(),sp);var na=sp.readS32();
  for(var a=0;a<na;a++){var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());if(IL2.iGN(img).readCString()===name)return img;}return null;}
function gmCls(ns,name){var i=imgByName('holo-game.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
function protoCls(ns,name){var i=imgByName('holo-protos.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}

var _oGC=null,_cGNm=null,_cGF=null,_fGN=null,_fGO=null,_fGT=null,_tGN=null,_fGV=null;
function _ii(){_ensureInit();if(_oGC)return;var il=Process.findModuleByName('libil2cpp.so');var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _oGC=b('il2cpp_object_get_class','pointer',['pointer']);_cGNm=b('il2cpp_class_get_name','pointer',['pointer']);
  _cGF=b('il2cpp_class_get_fields','pointer',['pointer','pointer']);_fGN=b('il2cpp_field_get_name','pointer',['pointer']);
  _fGO=b('il2cpp_field_get_offset','uint32',['pointer']);_fGT=b('il2cpp_field_get_type','pointer',['pointer']);
  _tGN=b('il2cpp_type_get_name','pointer',['pointer']);_fGV=b('il2cpp_field_static_get_value','void',['pointer','pointer']);}
function objCls(o){_ii();if(o.isNull())return 'null';try{return _cGNm(_oGC(o)).readCString();}catch(e){return '?';}}
function dFields(o){_ii();if(o.isNull())return [];var k=_oGC(o);var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=_cGF(k,it))&&!f.isNull()){var n=_fGN(f).readCString();var of=_fGO(f);var t='';try{var tt=_fGT(f);if(tt&&!tt.isNull())t=_tGN(tt).readCString();}catch(e){}out.push({name:n,offset:of,type:t});}return out;}
function hexBytes(p,n){try{var bs=p.readByteArray(n);var u8=new Uint8Array(bs);var s='';for(var i=0;i<u8.length;i++)s+=('0'+u8[i].toString(16)).slice(-2);return s;}catch(e){return null;}}

// ---- inventory dictionary ----
function getDict(invAddr){var k=gmCls('Niantic.Holoholo.Collections','InventoryCache');var m=cMN(k,'GetCurrentItems',0);
  var coll=rI(m,ptr(invAddr),ptr(0),null);if(coll.isNull())return null;return coll.add(0x10).readPointer();}
function walk(dict,cb){var en=dict.add(0x18).readPointer();if(en.isNull())return 0;var c=en.add(0x18).readS32();
  if(c<=0||c>500000)return 0;var base=en.add(0x20);var n=0;
  for(var i=0;i<c;i++){var e=base.add(i*0x18);if(e.readS32()<0)continue;var key=e.add(8).readPointer();var val=e.add(0x10).readPointer();
    if(key.isNull())continue;if(cb(key,val,i)===false)return n;n++;}return n;}

// Resolve the inner HoloInventoryItemProto from the ClientInventoryItem wrapper.
// Wrapper holds serverState (+0x10) / clientPrediction (+0x18) ClientItemModel; the proto sits a few words in.
function resolveItem(ci){
  for(var base=0x10;base<=0x18;base+=8){var model=ci.add(base).readPointer();if(model.isNull())continue;
    if(objCls(model)==='HoloInventoryItemProto')return model;                 // direct
    for(var o=0x10;o<=0x40;o+=8){try{var p=model.add(o).readPointer();if(!p.isNull()&&objCls(p)==='HoloInventoryItemProto')return p;}catch(e){}}}
  return ptr(0);
}

// ---- key census: type-case histogram (confirms case constants are stable) ----
rpc.exports.keyCensus = function(invAddr){
  var dict=getDict(invAddr);if(!dict||dict.isNull())return{err:'no dict'};
  var census={};var total=0;
  walk(dict,function(key,val){total++;var tc=key.add(0x18).readS32();census[tc]=(census[tc]||0)+1;});
  return {ok:true,total:total,census:census};
};

// ---- items: case==2, value.get_Item -> ItemProto(+0x10 Item, +0x14 Count) ----
rpc.exports.items = function(invAddr, itemCase){
  var dict=getDict(invAddr);if(!dict||dict.isNull())return{err:'no dict'};
  var keyCls=protoCls('Holoholo.Rpc','HoloInventoryKeyProto');
  var itemCls=protoCls('Holoholo.Rpc','HoloInventoryItemProto');
  var getItemKey=cMN(keyCls,'get_Item',0);   // -> Item enum (boxed)
  var getItemVal=cMN(itemCls,'get_Item',0);   // -> ItemProto
  var out={};
  walk(dict,function(key,val){
    if(key.add(0x18).readS32()!==itemCase)return true;
    var itemEnum=null;try{var r=rI(getItemKey,key,ptr(0),null);if(!r.isNull())itemEnum=r.add(0x10).readS32();}catch(e){}
    if(itemEnum===null)return true;
    var item=resolveItem(val);if(item.isNull()){out[itemEnum]=null;return true;}
    var ip;try{ip=rI(getItemVal,item,ptr(0),null);}catch(e){out[itemEnum]={err:'getItem threw'};return true;}
    if(ip.isNull()){out[itemEnum]={err:'null'};return true;}
    out[itemEnum]={count: ip.add(0x14).readS32(), unseen: ip.add(0x18).readS32()};
    return true;
  });
  return {ok:true, items:out};
};

// ---- candy + MEGA ENERGY: case==familyCase, value.get_PokemonFamily -> PokemonFamilyProto ----
// PokemonFamilyProto: FamilyId@+0x10 Candy@+0x14 MegaEvolutionResources(RepeatedField)@+0x18 XlCandy@+0x20
rpc.exports.familyResources = function(invAddr, familyCase, wantFamilies, dumpMegaRaw){
  var dict=getDict(invAddr);if(!dict||dict.isNull())return{err:'no dict'};
  var keyCls=protoCls('Holoholo.Rpc','HoloInventoryKeyProto');
  var itemCls=protoCls('Holoholo.Rpc','HoloInventoryItemProto');
  var getFamKey=cMN(keyCls,'get_PokemonFamilyId',0);   // -> int (boxed)
  var getFamVal=cMN(itemCls,'get_PokemonFamily',0);     // -> PokemonFamilyProto
  var want={};for(var i=0;i<wantFamilies.length;i++)want[wantFamilies[i]]=true;
  var wantAll=(wantFamilies.length===0);
  var out={};var megaSample=null;
  walk(dict,function(key,val){
    if(key.add(0x18).readS32()!==familyCase)return true;
    var fid=null;try{var r=rI(getFamKey,key,ptr(0),null);if(!r.isNull())fid=r.add(0x10).readS32();}catch(e){}
    if(fid===null)return true;
    if(!wantAll && !want[fid])return true;
    var item=resolveItem(val);if(item.isNull()){out[fid]={err:'no item'};return true;}
    var fam;try{fam=rI(getFamVal,item,ptr(0),null);}catch(e){out[fid]={err:'fam threw'};return true;}
    if(fam.isNull()){out[fid]={err:'null fam'};return true;}
    var rec={candy: fam.add(0x14).readS32(), xlCandy: fam.add(0x20).readS32(), megaEnergy:{}};
    // MegaEvolutionResources RepeatedField @ +0x18: items-array @ +0x10, count @ +0x18
    try{
      var rf=fam.add(0x18).readPointer();
      if(!rf.isNull()){
        var cnt=rf.add(0x18).readS32();
        var arr=rf.add(0x10).readPointer();
        if(cnt>0 && cnt<40 && !arr.isNull()){
          for(var j=0;j<cnt;j++){
            var el=arr.add(0x20+j*8).readPointer();    // RepeatedField of *message* = ref array
            if(el.isNull())continue;
            // VALIDATE: TemporaryEvolutionResourceProto layout unknown. Best-guess fields:
            //   +0x10 TemporaryEvolutionId (int enum), +0x14 / +0x18 energy counts.
            // We expose several candidate offsets + raw bytes + reflected fields for the lead.
            var tmpEvoId = el.add(0x10).readS32();
            rec.megaEnergy[tmpEvoId] = {
              w10: el.add(0x10).readS32(), w14: el.add(0x14).readS32(),
              w18: el.add(0x18).readS32(), w1c: el.add(0x1c).readS32(),
              w20: el.add(0x20).readS32()
            };
            if(dumpMegaRaw && megaSample===null){
              megaSample={cls:objCls(el), fields:dFields(el), bytes:hexBytes(el,0x40)};
            }
          }
        }
      }
    }catch(e){ rec.megaErr=e.toString(); }
    out[fid]=rec;
    return true;
  });
  return {ok:true, families:out, megaSample:megaSample};
};

// ---- a generic oneof-case probe for raid tickets / egg incubators / event passes ----
// case-driven: dumps raw value-proto bytes + class so the lead can decode passes/tickets.
rpc.exports.probeCase = function(invAddr, caseNum, label){
  var dict=getDict(invAddr);var res=[];var seen=0;
  walk(dict,function(key,val){
    if(key.add(0x18).readS32()!==caseNum)return true;
    seen++;
    if(res.length<6){
      var item=resolveItem(val);
      res.push({keyCls:objCls(key), itemCls:item.isNull()?null:objCls(item),
                itemBytes:item.isNull()?null:hexBytes(item,0x40)});
    }
    return true;
  });
  return {ok:true, label:label, caseNum:caseNum, seen:seen, samples:res};
};

// ---- stardust / pokecoins via IapService getters (singleton picked python-side) ----
rpc.exports.currency = function(iapAddr){
  var k=gmCls('Niantic.Holoholo.Storefront','IapService');
  var out={};
  ['get_Stardusts','get_Coins','get_PurchasedCoins'].forEach(function(nm){
    var m=cMN(k,nm,0);if(!m||m.isNull()){out[nm]='no method';return;}
    try{var r=rI(m,ptr(iapAddr),ptr(0),null);out[nm]=r.isNull()?null:r.add(0x10).readS32();}
    catch(e){out[nm]='threw';}
  });
  return out;
};

// ---- ItemBagImpl method path (cleaner; VALIDATE) ----
// GetItemCount(itemId)->int ; GetCandyCountForPokemonFamily(fid)->int ; GetXlCandyCountForPokemonFamily(fid)->int
rpc.exports.itemBagCounts = function(bagAddr, itemIds, familyIds){
  var k=gmCls('Niantic.Holoholo.Internal','ItemBagImpl');
  if(!k||k.isNull())return{err:'no ItemBagImpl class'};
  var gic=cMN(k,'GetItemCount',1);
  var gcc=cMN(k,'GetCandyCountForPokemonFamily',1);
  var gxc=cMN(k,'GetXlCandyCountForPokemonFamily',1);
  function call1(m,intArg){
    if(!m||m.isNull())return 'no-method';
    var b=Memory.alloc(4);b.writeS32(intArg);var a=Memory.alloc(Process.pointerSize);a.writePointer(b);
    try{var r=rI(m,ptr(bagAddr),a,null);return r.isNull()?null:r.add(0x10).readS32();}catch(e){return 'threw';}
  }
  var items={},candy={},xl={};
  for(var i=0;i<itemIds.length;i++)items[itemIds[i]]=call1(gic,itemIds[i]);
  for(var j=0;j<familyIds.length;j++){candy[familyIds[j]]=call1(gcc,familyIds[j]);xl[familyIds[j]]=call1(gxc,familyIds[j]);}
  return {ok:true, items:items, candy:candy, xlCandy:xl};
};
"""

# Live-validated 2026-09-17 on 0.427.0 (field names are PascalCase here: ItemProto.Item, TemporaryEvolutionResourceProto
# .TemporaryEvolutionId@0x10 / EnergyCount@0x14): enum names, class fields, player stats. Used by pogo_pipeline.step_read_candy.
INVENTORY_EXTRA_JS = r'''
var _EN=null;
function _enInit(){ if(_EN) return; _ensureInit(); var il=Process.findModuleByName('libil2cpp.so');
  function nf(n,r,a){return new NativeFunction(il.getExportByName(n),r,a);}
  _EN={CGF:nf('il2cpp_class_get_fields','pointer',['pointer','pointer']), FGN:nf('il2cpp_field_get_name','pointer',['pointer']),
       FGFlags:nf('il2cpp_field_get_flags','int',['pointer']), FSGV:nf('il2cpp_field_static_get_value','void',['pointer','pointer']),
       FGT:nf('il2cpp_field_get_type','pointer',['pointer']), CFT:nf('il2cpp_class_from_type','pointer',['pointer']),
       TGN:nf('il2cpp_type_get_name','pointer',['pointer']), FGO:nf('il2cpp_field_get_offset','uint32',['pointer'])}; }
function _lits(cls){ var out={}; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=_EN.CGF(cls,it))&&!f.isNull()){ try{ var fl=_EN.FGFlags(f); if((fl&0x10)&&(fl&0x40)){ var nm=_EN.FGN(f).readCString(); if(nm!=='value__'){ var b=Memory.alloc(8); b.writeU64(0); _EN.FSGV(f,b); out[b.readS32()]=nm; } } }catch(e){} } return out; }
function _fieldEnum(ns, clsName, fieldName){ _enInit(); var c=protoCls(ns, clsName); if(!c||c.isNull()) return {err:'no class '+clsName};
  var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=_EN.CGF(c,it))&&!f.isNull()){ var nm=_EN.FGN(f).readCString(); if(nm===fieldName){ var t=_EN.FGT(f); return {type:_EN.TGN(t).readCString(), map:_lits(_EN.CFT(t))}; } }
  return {err:'no field '+fieldName}; }
rpc.exports.itemEnum = function(){ return _fieldEnum('Holoholo.Rpc','ItemProto','item_'); };
rpc.exports.tempEvoEnum = function(){ return _fieldEnum('Holoholo.Rpc','TemporaryEvolutionResourceProto','temporaryEvolutionId_'); };
rpc.exports.classFields = function(ns, clsName){ _enInit(); var c=protoCls(ns, clsName); if(!c||c.isNull()) return {err:'no class'};
  var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=_EN.CGF(c,it))&&!f.isNull()){ var fl=_EN.FGFlags(f); if(fl&0x10) continue; out.push({name:_EN.FGN(f).readCString(), off:_EN.FGO(f), type:_EN.TGN(_EN.FGT(f)).readCString()}); }
  return out; };
rpc.exports.playerStats = function(invAddr, statsCase){
  var dict=getDict(invAddr); if(!dict||dict.isNull()) return {err:'no dict'};
  var itemCls=protoCls('Holoholo.Rpc','HoloInventoryItemProto'); var getPS=cMN(itemCls,'get_PlayerStats',0); var res=null;
  walk(dict,function(key,val){ if(key.add(0x18).readS32()!==statsCase) return true; var item=resolveItem(val); if(item.isNull()) return true;
    var ps=rI(getPS,item,ptr(0),null); if(ps.isNull()) return true; res=ps.toString(); return false; });
  return {addr:res}; };
rpc.exports.readInts = function(addr, offs){ var p=ptr(addr); var o={}; offs.forEach(function(x){ try{ o[x[0]] = x[1]==='System.Int64' ? p.add(x[2]).readS64().toString() : (x[1]==='System.Single' ? p.add(x[2]).readFloat() : p.add(x[2]).readS32()); }catch(e){ o[x[0]]='err'; } }); return o; };

rpc.exports.enumOfField = function(ns, clsName, fieldName){ return _fieldEnum(ns, clsName, fieldName); };
'''

# HoloInventoryKeyProto.TypeOneofCase numeric constants. From prior *working* runs.
# (protobuf oneof case == field number in HoloInventoryKeyProto.)
CASE_ITEM = 2
CASE_PLAYER_STATS = 4
CASE_PLAYER_CURRENCY = 5
CASE_POKEMON_FAMILY = 10   # PokemonFamilyId -> candy + mega energy


def main():
    out = {}
    for attempt in range(8):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, JS)
            sc.exports_sync.init()

            inv = pg.find_singleton(sess, 'Niantic.Holoholo.Collections', 'InventoryCache')
            print(f"InventoryCache @ {inv}")

            census = sc.exports_sync.key_census(inv)
            print(f"key census: total={census.get('total')} caseHistogram={census.get('census')}")
            out['keyCensus'] = census

            it = sc.exports_sync.items(inv, CASE_ITEM)
            items = it.get('items', {})
            print(f"\nITEMS ({len(items)} distinct ids):")
            for iid in sorted(items, key=lambda x: int(x)):
                nm = WATCH_ITEMS.get(int(iid), '')
                c = items[iid]
                cval = c.get('count') if isinstance(c, dict) else c
                flag = ' <<' if int(iid) in WATCH_ITEMS else ''
                print(f"   {iid:>5} {nm:<22} count={cval}{flag}")
            out['items'] = items

            fam_ids = list(MEGA_ENERGY_FAMILIES.keys())
            fr = sc.exports_sync.family_resources(inv, CASE_POKEMON_FAMILY, fam_ids, True)
            print(f"\nCANDY + MEGA ENERGY (requested {len(fam_ids)} families):")
            for fid, rec in sorted(fr.get('families', {}).items(), key=lambda kv: int(kv[0])):
                nm = MEGA_ENERGY_FAMILIES.get(int(fid), f'family{fid}')
                if isinstance(rec, dict) and 'candy' in rec:
                    me = rec.get('megaEnergy', {})
                    print(f"   {nm:<14}(fam {fid}): candy={rec['candy']} xl={rec['xlCandy']} megaRes={me}")
                else:
                    print(f"   {nm:<14}(fam {fid}): {rec}")
            out['familyResources'] = fr
            if fr.get('megaSample'):
                print("\n*** TemporaryEvolutionResourceProto SAMPLE (VALIDATE energy field) ***")
                print(json.dumps(fr['megaSample'], indent=2))

            # Raid tickets / egg incubators / event passes: probe their oneof cases.
            # NOTE: these case numbers (3,6,7,...) are guesses from accessor ordering; the
            # census above tells you which non-{2,4,5,10} cases are actually present.
            for cnum, lab in [(3, 'RaidTickets?'), (6, 'EggIncubators?'),
                              (7, 'InventoryUpgrades?'), (14, 'EventPasses?')]:
                pr = sc.exports_sync.probe_case(inv, cnum, lab)
                if pr.get('seen'):
                    print(f"\nCASE {cnum} ({lab}): seen={pr['seen']}")
                    out.setdefault('caseProbes', {})[cnum] = pr

            # Stardust / coins via IapService.
            try:
                iap = pg.find_singleton(sess, 'Niantic.Holoholo.Storefront', 'IapService')
                cur = sc.exports_sync.currency(iap)
                print(f"\nCURRENCY (IapService @ {iap}): {cur}")
                out['currency'] = cur
            except Exception as e:
                print(f"\nIapService read failed: {e}")

            # ItemBagImpl method path (VALIDATE) -- compare vs dict walk.
            try:
                bag = pg.find_singleton(sess, 'Niantic.Holoholo.Internal', 'ItemBagImpl')
                ibc = sc.exports_sync.item_bag_counts(bag, list(WATCH_ITEMS.keys()), fam_ids)
                print(f"\nItemBagImpl @ {bag} method-path counts (cross-check):")
                print(f"   items={ibc.get('items')}")
                print(f"   candy={ibc.get('candy')}")
                print(f"   xl={ibc.get('xlCandy')}")
                out['itemBagImpl'] = ibc
            except Exception as e:
                print(f"\nItemBagImpl path failed (expected if class/methods differ): {e}")

            json.dump(out, open('_read_inventory_out.json', 'w'), indent=2)
            print("\nwrote _read_inventory_out.json")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)


if __name__ == '__main__':
    main()
