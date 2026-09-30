"""READ-ONLY: scan QuestsProto+0x20 (QuestPokemonEncounterProto list, ~91 entries)
for a pending Mewtwo (pid 150) encounter -- especially one tied to the GO Fest city
CHOICE research -- and whether it's still unclaimed. Reflects the proto fields to
locate pokemon_id / questId / captured-claimed flags. Writes nothing."""
import sys, time, subprocess
import frida

ADB = '100.98.158.56:5555'
pid = int(subprocess.check_output(['adb', '-s', ADB, 'shell', 'pidof com.nianticlabs.pokemongo']).decode().strip())
print('PID', pid)
d = frida.get_device_manager().add_remote_device('127.0.0.1:27047')
sess = d.attach(pid)

hook_js = r"""
var qInst=null;
function init(){var il=Process.findModuleByName('libil2cpp.so');var A={};il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
function b(n,r,a){return new NativeFunction(A[n],r,a);}
var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),cGM=b('il2cpp_class_get_methods','pointer',['pointer','pointer']),tA=b('il2cpp_thread_attach','pointer',['pointer']);tA(dG());
var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;for(var a=0;a<na;a++){var i=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(i).readCString()==='holo-game.dll'){gi=i;break;}}
var cls=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestService'));
var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=cGM(cls,it))&&!m.isNull()){try{var ad=m.readPointer();if(ad.isNull())continue;Interceptor.attach(ad,{onEnter:function(ar){if(!qInst)qInst=ar[0].toString();}});}catch(e){}}}
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
rpc.exports.scan = function(addr){
  var inst=ptr(addr);
  var il=Process.findModuleByName('libil2cpp.so');var A={};il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return new NativeFunction(A[n],r,a);}
  var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),cMN=b('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']),rI=b('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']),OGC=b('il2cpp_object_get_class','pointer',['pointer']),CGN=b('il2cpp_class_get_name','pointer',['pointer']),CGF=b('il2cpp_class_get_fields','pointer',['pointer','pointer']),FGN=b('il2cpp_field_get_name','pointer',['pointer']),FGO=b('il2cpp_field_get_offset','uint32',['pointer']);
  var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;for(var a=0;a<na;a++){var i=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(i).readCString()==='holo-game.dll'){gi=i;break;}}
  var qs=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestService'));
  function rdStr(p){try{if(!p||p.isNull())return '';var len=p.add(0x10).readS32();if(len<=0||len>200)return '';var c=[];for(var i=0;i<len;i++){var ch=p.add(0x14+i*2).readU16();if(ch<32||ch>126)return '';c.push(String.fromCharCode(ch));}return c.join('');}catch(e){return '';}}
  var getP=cMN(qs,Memory.allocUtf8String('get_QuestsProto'),0);
  var ex=Memory.alloc(Process.pointerSize);ex.writePointer(ptr(0));
  var po=rI(getP,inst,ptr(0),ex); if(po.isNull())return{error:'null proto'};
  var rf=po.add(0x20).readPointer(); if(rf.isNull())return{error:'no +0x20'};
  var cnt=rf.add(0x18).readS32(); var arr=rf.add(0x10).readPointer();
  if(arr.isNull()||cnt<=0)return{error:'empty list cnt='+cnt};
  var e0=arr.add(0x20).readPointer(); var cls=OGC(e0);
  // reflect Pokemon proto (Pokemon@0x18) to find its pokemon-id field offset
  var pidOff=-1, pclsName='';
  try{ var p0=e0.add(0x18).readPointer(); if(!p0.isNull()){ var pc=OGC(p0); pclsName=CGN(pc).readCString();
    var pit=Memory.alloc(Process.pointerSize);pit.writePointer(ptr(0));var pf;
    while((pf=CGF(pc,pit))&&!pf.isNull()){ try{ var pn=FGN(pf).readCString();
      if(pn==='PokemonId'||pn==='pokemonId_'||pn.toLowerCase()==='pokemonid'){ pidOff=FGO(pf); break; } }catch(e){} } } }catch(e){}
  var out=[];
  for(var i=0;i<cnt;i++){
    var e=arr.add(0x20).add(i*8).readPointer(); if(e.isNull())continue;
    var rec={};
    rec.QuestId=rdStr(e.add(0x10).readPointer());
    rec.EncType=e.add(0x20).readS32();
    rec.OverwrittenOnFlee=e.add(0x34).readS32();
    try{ var pk=e.add(0x18).readPointer(); rec.pid=(pidOff>=0 && !pk.isNull())? pk.add(pidOff).readS32() : null; }catch(er){ rec.pid=null; }
    out.push(rec);
  }
  return {cls:CGN(cls).readCString(), pokemonClass:pclsName, pidOff:('0x'+(pidOff>=0?pidOff.toString(16):'?')), count:cnt, entries:out};
};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.scan(inst)
sess.detach()
if 'error' in r:
    print('ERROR:', r['error']); sys.exit(1)
from collections import Counter
print('\nencounter class:', r['cls'], ' | pokemon proto:', r.get('pokemonClass'), ' | pid offset:', r.get('pidOff'))
ents = r['entries']
print(f'{len(ents)} encounter entries')
pids = Counter(e.get('pid') for e in ents)
print('species (pid) histogram:', dict(sorted((k, v) for k, v in pids.items() if k)))
mewtwo = [e for e in ents if e.get('pid') == 150]
city = [e for e in ents if any(k in (e.get('QuestId') or '').upper() for k in ['IRL_CITY', 'CHOICE', 'FULL4', 'MEWTWO'])]
print(f'\n=== MEWTWO (pid 150) encounters pending: {len(mewtwo)} ===')
for e in mewtwo:
    print('  ', e)
print(f'\n=== city-choice / IRL_CITY encounters pending: {len(city)} ===')
for e in city:
    print('  ', e)
print('\n=== sample (first 5) ===')
for e in ents[:5]:
    print('  ', e)
print('\nVERDICT:', 'A pending Mewtwo encounter EXISTS -> still catchable!' if mewtwo else 'NO pending Mewtwo encounter in the active list -> the City Choice encounter is not sitting claimable here.')
