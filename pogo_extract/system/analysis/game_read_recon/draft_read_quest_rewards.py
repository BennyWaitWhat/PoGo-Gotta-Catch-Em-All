"""DRAFT (device-validation) READ-ONLY reader for QUEST REWARDS + POKEMON-ENCOUNTER
rewards. Built statically from _metadata_strings.txt recon; offsets/getter-names
flagged [DEVICE] in quest_rewards_encounter_recon.md must be confirmed on first run.

What it does, all via il2cpp_runtime_invoke (offset-independent) + the proven
QuestsProto offsets:
  1. captures a QuestService instance (same hook the existing scripts use)
  2. for each active QuestProto: gets its reward RepeatedField (tries get_QuestRewards
     then get_Rewards) and decodes every QuestRewardProto:
        - PokemonEncounter -> species + form/costume/gender/shiny + shinyProb + featured
        - MegaResource/TempEvoResource -> pid + TemporaryEvolutionId(MEGA_X/_Y) + amount
        - Item/Stardust/Candy/Exp/Pokemon/Egg/LevelCap...
  3. emits a per-reward "probe" block on the FIRST quest so the lead can lock the
     RewardOneofCase int map + boxed-payload offset.

WRITES NOTHING. Static-analysis lead: this is the device-validation artifact, not a
finished tool. Run on the phone the lead designates (single serial collision rule).

Usage:
    python draft_read_quest_rewards.py            # decode active quests' rewards
    python draft_read_quest_rewards.py --probe    # extra raw probing on quest #0
"""
import sys, time, json, subprocess
import frida

ADB = '100.98.158.56:5555'
PROBE = '--probe' in sys.argv

def _pid():
    return int(subprocess.check_output(
        ['adb', '-s', ADB, 'shell', 'pidof com.nianticlabs.pokemongo']).decode().strip())

pid = _pid()
print('PID', pid)
d = frida.get_device_manager().add_remote_device('127.0.0.1:27047')
sess = d.attach(pid)

# ---- 1) capture a QuestService instance (proven hook) ----
HOOK = r"""
var qInst=null;
function init(){
  var il=Process.findModuleByName('libil2cpp.so');var A={};il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return new NativeFunction(A[n],r,a);}
  var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),cGM=b('il2cpp_class_get_methods','pointer',['pointer','pointer']),tA=b('il2cpp_thread_attach','pointer',['pointer']);tA(dG());
  var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;
  for(var a=0;a<na;a++){var i=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(i).readCString()==='holo-game.dll'){gi=i;break;}}
  var cls=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestService'));
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
  while((m=cGM(cls,it))&&!m.isNull()){try{var ad=m.readPointer();if(ad.isNull())continue;Interceptor.attach(ad,{onEnter:function(ar){if(!qInst)qInst=ar[0].toString();}});}catch(e){}}
}
rpc.exports={setup:function(){init();return{ok:1};},get:function(){return{q:qInst};}};
"""
hs = sess.create_script(HOOK); hs.on('message', lambda m, dd: None); hs.load(); hs.exports_sync.setup()
print('capturing QuestService (be on map/Research screen)...')
inst = None
for _ in range(45):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('q'):
        inst = g['q']; break
hs.unload()
if not inst:
    print('NO_INSTANCE'); sess.detach(); sys.exit(1)
print('QuestService inst', inst)

# ---- 2) reward reader ----
JS = r"""
var IL=null, GI=null, HPR=null;
function init(){
  if(IL) return;
  var il=Process.findModuleByName('libil2cpp.so');var A={};il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return A[n]?new NativeFunction(A[n],r,a):null;}
  IL={
    dG:b('il2cpp_domain_get','pointer',[]),
    dGA:b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),
    aGI:b('il2cpp_assembly_get_image','pointer',['pointer']),
    iGN:b('il2cpp_image_get_name','pointer',['pointer']),
    cFN:b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),
    cMN:b('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']),
    cGM:b('il2cpp_class_get_methods','pointer',['pointer','pointer']),
    mGN:b('il2cpp_method_get_name','pointer',['pointer']),
    mGPC:b('il2cpp_method_get_param_count','uint32',['pointer']),
    oGC:b('il2cpp_object_get_class','pointer',['pointer']),
    cGNa:b('il2cpp_class_get_name','pointer',['pointer']),
    rI:b('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']),
    tA:b('il2cpp_thread_attach','pointer',['pointer'])
  };
  IL.tA(IL.dG());
  var sp=Memory.alloc(4),asms=IL.dGA(IL.dG(),sp),na=sp.readS32();
  for(var a=0;a<na;a++){var i=IL.aGI(asms.add(a*Process.pointerSize).readPointer());var n=IL.iGN(i).readCString();if(n==='holo-game.dll')GI=i;if(n==='holo-protos.dll')HPR=i;}
}
function rdStr(p){if(p.isNull())return '';var len=p.add(0x10).readS32();if(len<=0||len>2000)return '';var c=[];for(var i=0;i<len;i++){var ch=p.add(0x14+i*2).readU16();if(ch===0)break;c.push(String.fromCharCode(ch));}return c.join('');}
function clsName(o){try{if(o.isNull())return null;return IL.cGNa(IL.oGC(o)).readCString();}catch(e){return null;}}
function cls(img,ns,nm){return IL.cFN(img,Memory.allocUtf8String(ns),Memory.allocUtf8String(nm));}
// invoke 0-arg getter by name on instance; returns ptr or NULL
function inv0(klass,name,instPtr){
  var m=IL.cMN(klass,Memory.allocUtf8String(name),0);
  if(!m||m.isNull())return {ok:false};
  var ex=Memory.alloc(Process.pointerSize);ex.writePointer(ptr(0));
  try{var r=IL.rI(m,instPtr,ptr(0),ex);return {ok:true,ret:r};}catch(e){return {ok:false,err:e.toString()};}
}
// boxed primitive payload @+0x10 (enum/int/bool) ; null-safe
function boxI32(p){try{if(!p||p.isNull())return null;return p.add(0x10).readS32();}catch(e){return null;}}
function boxF32(p){try{if(!p||p.isNull())return null;return p.add(0x10).readFloat();}catch(e){return null;}}

// list zero-arg+param-count for methods matching substrs on a class (recon helper)
function listMethods(klass, subs){
  var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
  while((m=IL.cGM(klass,it))&&!m.isNull()){try{var nm=IL.mGN(m).readCString();if(!nm)continue;var lo=nm.toLowerCase();for(var s=0;s<subs.length;s++){if(lo.indexOf(subs[s])>=0){out.push(nm+'/'+IL.mGPC(m));break;}}}catch(e){}}
  return out.sort();
}

// RepeatedField<T> -> array of element ptrs (proven layout)
function rfElems(rf, cap){
  var out=[];if(!rf||rf.isNull())return out;
  var cnt=rf.add(0x18).readS32();var arr=rf.add(0x10).readPointer();
  if(arr.isNull()||cnt<=0||cnt>5000)return out;
  for(var i=0;i<Math.min(cnt,cap||200);i++){var e=arr.add(0x20).add(i*8).readPointer();out.push(e);}
  return out;
}

function decodeReward(qrCls, encClsRef, tevoWrapRef, rp, probe){
  init();
  var rec={cls:clsName(rp)};
  // oneof discriminator (int) for logging
  var rc=inv0(qrCls,'get_RewardCase',rp);
  if(rc.ok && rc.ret && !rc.ret.isNull()) rec.rewardCaseInt=boxI32(rc.ret);
  // PokemonEncounter
  var pe=inv0(qrCls,'get_PokemonEncounter',rp);
  if(pe.ok && pe.ret && !pe.ret.isNull()){
    var enc=pe.ret; var ec=clsName(enc);
    rec.type='POKEMON_ENCOUNTER'; rec.encCls=ec;
    var encCls=IL.oGC(enc);  // invoke getters against the encounter's own runtime class
    var idr=inv0(encCls,'get_PokemonId',enc); if(idr.ok) rec.pokemonId=boxI32(idr.ret);
    var dr=inv0(encCls,'get_PokemonDisplay',enc);
    if(dr.ok && dr.ret && !dr.ret.isNull()){
      var disp=dr.ret; var dc=IL.oGC(disp);
      var f=inv0(dc,'get_Form',disp); if(f.ok) rec.form=boxI32(f.ret);
      var c=inv0(dc,'get_Costume',disp); if(c.ok) rec.costume=boxI32(c.ret);
      var g=inv0(dc,'get_Gender',disp); if(g.ok) rec.gender=boxI32(g.ret);
      var s=inv0(dc,'get_Shiny',disp); if(s.ok) rec.shiny=boxI32(s.ret);
      var al=inv0(dc,'get_Alignment',disp); if(al.ok) rec.alignment=boxI32(al.ret);
    }
    var sp=inv0(encCls,'get_ShinyProbability',enc); if(sp.ok) rec.shinyProb=boxF32(sp.ret);
    var ft=inv0(encCls,'get_IsFeaturedPokemon',enc); if(ft.ok) rec.featured=boxI32(ft.ret);
    return rec;
  }
  // MegaResource / TempEvoResource -> mega energy
  var mr=inv0(qrCls,'get_MegaResource',rp); if(!(mr.ok&&mr.ret&&!mr.ret.isNull())) mr=inv0(qrCls,'get_TempEvoResource',rp);
  if(mr.ok && mr.ret && !mr.ret.isNull()){
    rec.type='MEGA_ENERGY'; var wrap=mr.ret; var wc=IL.oGC(wrap); rec.wrapCls=clsName(wrap);
    // find the inner TemporaryEvolutionResourceProto: probe likely getter names
    var inner=null;
    var names=['get_TempEvoResource','get_Resource','get_TemporaryEvolutionResource','get_MegaResource'];
    for(var n=0;n<names.length;n++){var t=inv0(wc,names[n],wrap);if(t.ok&&t.ret&&!t.ret.isNull()){inner=t.ret;rec.innerGetter=names[n];break;}}
    var src=inner||wrap; var sc=IL.oGC(src);
    var pidm=inv0(sc,'get_PokemonId',src); if(pidm.ok) rec.pokemonId=boxI32(pidm.ret);
    var tev=inv0(sc,'get_TemporaryEvolutionId',src); if(tev.ok) rec.tempEvoId=boxI32(tev.ret);
    var amt=inv0(sc,'get_Amount',src); if(!(amt.ok&&amt.ret&&!amt.ret.isNull())) amt=inv0(sc,'get_MaxEnergyCount',src);
    if(amt.ok) rec.amount=boxI32(amt.ret);
    return rec;
  }
  // Item
  var it=inv0(qrCls,'get_Item',rp);
  if(it.ok && it.ret && !it.ret.isNull()){
    rec.type='ITEM'; var ic=IL.oGC(it.ret);
    var im=inv0(ic,'get_Item',it.ret); if(im.ok) rec.item=boxI32(im.ret);
    var am=inv0(ic,'get_Amount',it.ret); if(am.ok) rec.amount=boxI32(am.ret);
    return rec;
  }
  // Candy
  var ca=inv0(qrCls,'get_Candy',rp); if(!(ca.ok&&ca.ret&&!ca.ret.isNull())) ca=inv0(qrCls,'get_PokemonCandy',rp);
  if(ca.ok && ca.ret && !ca.ret.isNull()){
    rec.type='CANDY'; var cc=IL.oGC(ca.ret);
    var cp=inv0(cc,'get_PokemonId',ca.ret); if(cp.ok) rec.pokemonId=boxI32(cp.ret);
    var cam=inv0(cc,'get_Amount',ca.ret); if(cam.ok) rec.amount=boxI32(cam.ret);
    return rec;
  }
  // Direct Pokemon grant
  var pk=inv0(qrCls,'get_Pokemon',rp);
  if(pk.ok && pk.ret && !pk.ret.isNull()){ rec.type='POKEMON'; rec.pokeProtoCls=clsName(pk.ret); return rec; }
  // Egg
  var eg=inv0(qrCls,'get_PokemonEgg',rp);
  if(eg.ok && eg.ret && !eg.ret.isNull()){ rec.type='EGG'; return rec; }
  // int32 oneof fields (boxed payload @+0x10)
  var sd=inv0(qrCls,'get_Stardust',rp); var sdv=sd.ok?boxI32(sd.ret):null; if(sdv){ rec.type='STARDUST'; rec.amount=sdv; return rec; }
  var xp=inv0(qrCls,'get_Exp',rp);      var xpv=xp.ok?boxI32(xp.ret):null; if(xpv){ rec.type='EXP'; rec.amount=xpv; return rec; }
  var lc=inv0(qrCls,'get_LevelCap',rp); var lcv=lc.ok?boxI32(lc.ret):null; if(lcv){ rec.type='LEVEL_CAP'; rec.amount=lcv; return rec; }
  var fp=inv0(qrCls,'get_FriendshipPoints',rp); var fpv=fp.ok?boxI32(fp.ret):null; if(fpv){ rec.type='FRIENDSHIP'; rec.amount=fpv; return rec; }
  rec.type='UNKNOWN'; return rec;
}

rpc.exports = {
  recon: function(addr){
    init();
    var qsCls = cls(GI,'Niantic.Holoholo.Quests','QuestService');
    var rpcCls = cls(GI,'Niantic.Holoholo.Quests','QuestRpcService');
    return {
      questServiceMethods: listMethods(qsCls,['reward','display','encounter','description','quests','goal']),
      questRpcServiceFound: (rpcCls && !rpcCls.isNull()),
      questRpcServiceMethods: (rpcCls && !rpcCls.isNull()) ? listMethods(rpcCls,['reward','encounter','quest']) : []
    };
  },
  read: function(addr, doProbe){
    init();
    var inst=ptr(addr);
    var qsCls = cls(GI,'Niantic.Holoholo.Quests','QuestService');
    var qrCls = cls(HPR,'Holoholo.Rpc','QuestRewardProto');
    var qpCls = cls(HPR,'Holoholo.Rpc','QuestProto');
    // get_QuestsProto -> active RepeatedField<QuestProto> @+0x10 (proven)
    var gp=inv0(qsCls,'get_QuestsProto',inst);
    if(!(gp.ok&&gp.ret&&!gp.ret.isNull())) return {error:'no QuestsProto'};
    var po=gp.ret;
    var quests=rfElems(po.add(0x10).readPointer(), 60);
    var out=[]; var rewardGetterUsed=null; var probeBlock=null;
    for(var i=0;i<quests.length;i++){
      var qp=quests[i]; if(qp.isNull())continue;
      var tid=rdStr(qp.add(0x40).readPointer());
      var st=qp.add(0x58).readS32(); var pr=qp.add(0x48).readS32();
      // rewards RF: try get_QuestRewards then get_Rewards on the QuestProto
      var rRf=null;
      var a=inv0(qpCls,'get_QuestRewards',qp);
      if(a.ok&&a.ret&&!a.ret.isNull()){rRf=a.ret;rewardGetterUsed='get_QuestRewards';}
      else{var bb=inv0(qpCls,'get_Rewards',qp);if(bb.ok&&bb.ret&&!bb.ret.isNull()){rRf=bb.ret;rewardGetterUsed='get_Rewards';}}
      var rewards=[];
      if(rRf){var rps=rfElems(rRf,40);for(var r=0;r<rps.length;r++){if(!rps[r].isNull())rewards.push(decodeReward(qrCls,null,null,rps[r],false));}}
      out.push({tid:tid,status:st,progress:pr,rewards:rewards});
      // probe block: dump raw oneof getters on the FIRST reward of the FIRST quest w/ rewards
      if(doProbe && !probeBlock && rRf){
        var rps2=rfElems(rRf,1);
        if(rps2.length && !rps2[0].isNull()){
          var rp0=rps2[0]; var pb={rewardCls:clsName(rp0)};
          var getters=['get_RewardCase','get_PokemonEncounter','get_MegaResource','get_TempEvoResource','get_Item','get_Stardust','get_Candy','get_PokemonCandy','get_Exp','get_Pokemon','get_PokemonEgg','get_LevelCap','get_LootTable','get_FriendshipPoints'];
          pb.getters={};
          for(var k=0;k<getters.length;k++){var rr=inv0(qrCls,getters[k],rp0);pb.getters[getters[k]]=(rr.ok&&rr.ret&&!rr.ret.isNull())?('ptr cls='+clsName(rr.ret)+' boxI32='+boxI32(rr.ret)):'null';}
          probeBlock=pb;
        }
      }
    }
    return {rewardGetterUsed:rewardGetterUsed, questCount:quests.length, quests:out, probe:probeBlock};
  }
};
"""
sc = sess.create_script(JS); sc.on('message', lambda m, dd: print('JS', m)); sc.load()

print('\n=== QuestService / QuestRpcService reward-method recon ===')
print(json.dumps(sc.exports_sync.recon(inst), indent=2))

print('\n=== reading rewards ===')
res = sc.exports_sync.read(inst, PROBE)
sess.detach()
if 'error' in res:
    print('ERROR', res['error']); sys.exit(1)

print('rewardGetterUsed:', res.get('rewardGetterUsed'))
if res.get('probe'):
    print('\n--- PROBE (raw oneof getters on quest#0 reward#0) ---')
    print(json.dumps(res['probe'], indent=2))

TEVO = {0: 'UNSET', 1: 'MEGA', 2: 'MEGA_X', 3: 'MEGA_Y', 4: 'PRIMAL'}  # [DEVICE] confirm
STAT = {0: 'inactive', 1: 'active', 2: 'COMPLETE', 3: 'claimed'}
print(f"\n=== {res['questCount']} active quests ===")
for q in res['quests']:
    if not q['rewards']:
        continue
    print(f"\n[{STAT.get(q['status'], q['status'])}] {q['progress']}  {q['tid']}")
    for rw in q['rewards']:
        t = rw.get('type')
        if t == 'POKEMON_ENCOUNTER':
            extra = []
            if rw.get('form'): extra.append(f"form={rw['form']}")
            if rw.get('shiny'): extra.append('SHINY')
            if rw.get('shinyProb') not in (None, 0): extra.append(f"shinyP={rw['shinyProb']}")
            if rw.get('featured'): extra.append('FEATURED')
            print(f"    ENCOUNTER pid={rw.get('pokemonId')} {' '.join(extra)}")
        elif t == 'MEGA_ENERGY':
            print(f"    MEGA_ENERGY pid={rw.get('pokemonId')} tevo={TEVO.get(rw.get('tempEvoId'), rw.get('tempEvoId'))} amt={rw.get('amount')} (innerGetter={rw.get('innerGetter')})")
        else:
            print(f"    {t} {json.dumps({k: v for k, v in rw.items() if k not in ('cls', 'type', 'encCls', 'wrapCls')})}")
print('\nNOTE: TEMP_EVOLUTION ordinals + getter names are [DEVICE]-flagged; verify against the PROBE block.')
