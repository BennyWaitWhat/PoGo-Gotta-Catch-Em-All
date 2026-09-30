"""READ-ONLY: for every active quest, pull the human-readable DESCRIPTION
(QuestService.GetQuestDescription) and whether it rewards a Pokemon encounter
(GetPokemonEncounterForQuest). Answers 'what is the actual task / where is Mewtwo'."""
import sys, time, subprocess
import frida

ADB = '100.98.158.56:5555'
pid = int(subprocess.check_output(['adb', '-s', ADB, 'shell', 'pidof com.nianticlabs.pokemongo']).decode().strip())
print('PID', pid)
d = frida.get_device_manager().add_remote_device('127.0.0.1:27047')
sess = d.attach(pid)

hook_js = r"""
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
hs = sess.create_script(hook_js); hs.on('message', lambda m, dd: None); hs.load(); hs.exports_sync.setup()
print('capturing QuestService (be on map/Research)...')
inst = None
for i in range(45):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('q'):
        inst = g['q']; break
hs.unload()
if not inst:
    print('NO_INSTANCE'); sess.detach(); sys.exit(1)
print('inst', inst)

js = r"""
rpc.exports = { details: function(addr){
  var inst=ptr(addr);
  var il=Process.findModuleByName('libil2cpp.so');var A={};il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return new NativeFunction(A[n],r,a);}
  var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),cMN=b('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']),rI=b('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
  var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;
  for(var a=0;a<na;a++){var i=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(i).readCString()==='holo-game.dll'){gi=i;break;}}
  var qs=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestService'));
  function rdStr(p){if(p.isNull())return '';var len=p.add(0x10).readS32();if(len<=0||len>2000)return '';var c=[];for(var i=0;i<len;i++){var ch=p.add(0x14+i*2).readU16();if(ch===0)break;c.push(String.fromCharCode(ch));}return c.join('');}
  var getProto=cMN(qs,Memory.allocUtf8String('get_QuestsProto'),0);
  var getDesc=cMN(qs,Memory.allocUtf8String('GetQuestDescription'),1);
  var getEnc=cMN(qs,Memory.allocUtf8String('GetPokemonEncounterForQuest'),1);
  var ex=Memory.alloc(Process.pointerSize);ex.writePointer(ptr(0));
  var po=rI(getProto,inst,ptr(0),ex); if(po.isNull())return {error:'null proto'};
  var rf=po.add(0x10).readPointer(); var arr=rf.add(0x10).readPointer(); var cnt=rf.add(0x18).readS32();
  var out=[];
  for(var i=0;i<Math.min(cnt,40);i++){
    var qp=arr.add(0x20).add(i*8).readPointer(); if(qp.isNull())continue;
    var rec={tid:rdStr(qp.add(0x40).readPointer()), pr:qp.add(0x48).readS32(), st:qp.add(0x58).readS32(), tg:0, desc:'', poke:''};
    try{var g=qp.add(0x50).readPointer();if(!g.isNull())rec.tg=g.add(0x18).readS32();}catch(e){}
    if(getDesc){try{var a1=Memory.alloc(Process.pointerSize);a1.writePointer(qp);var e1=Memory.alloc(Process.pointerSize);e1.writePointer(ptr(0));var s=rI(getDesc,inst,a1,e1);if(!s.isNull())rec.desc=rdStr(s);}catch(e){rec.desc='<err>';}}
    if(getEnc){try{var a2=Memory.alloc(Process.pointerSize);a2.writePointer(qp);var e2=Memory.alloc(Process.pointerSize);e2.writePointer(ptr(0));var enc=rI(getEnc,inst,a2,e2);if(!enc.isNull()){rec.poke='POKEMON_REWARD pid='+enc.add(0x10).readS32();}}catch(e){rec.poke='<encErr>';}}
    out.push(rec);
  }
  return {count:cnt, quests:out};
}};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.details(inst)
sess.detach()
if 'error' in r:
    print('ERR', r['error']); sys.exit(1)
STAT = {0: 'inactive', 1: 'active', 2: 'COMPLETE', 3: 'claimed'}
print(f"\n=== {r['count']} quests ===")
for q in r['quests']:
    print(f"\n[{STAT.get(q['st'], q['st'])}] {q['pr']}/{q['tg']}  {q['tid']}")
    if q['desc']:
        print(f"    desc: {q['desc']}")
    if q['poke']:
        print(f"    *** {q['poke']} ***")
