"""READ-ONLY: reflect QuestProto time fields and read them per active quest, then
compare to the phone's real (JST) clock to flag any FUTURE-scheduled reward/availability
— i.e., test whether the missing Mega Mewtwo is a timeline/scheduled-delivery thing."""
import sys, time, subprocess, datetime
import frida

ADB = '100.98.158.56:5555'
pid = int(subprocess.check_output(['adb', '-s', ADB, 'shell', 'pidof com.nianticlabs.pokemongo']).decode().strip())
# phone's real clock (JST-set device) in epoch ms
dev_ms = int(subprocess.check_output(['adb', '-s', ADB, 'shell', 'date +%s%3N']).decode().strip())
dev_dt_utc = datetime.datetime.utcfromtimestamp(dev_ms / 1000)
print(f'PID {pid}   phone clock (epoch ms) = {dev_ms}   = {dev_dt_utc} UTC  = {dev_dt_utc + datetime.timedelta(hours=9)} JST')

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
rpc.exports.ts = function(addr){
  var inst=ptr(addr);
  var il=Process.findModuleByName('libil2cpp.so');var A={};il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return new NativeFunction(A[n],r,a);}
  var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),cMN=b('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']),rI=b('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']),OGC=b('il2cpp_object_get_class','pointer',['pointer']),CGN=b('il2cpp_class_get_name','pointer',['pointer']),CGF=b('il2cpp_class_get_fields','pointer',['pointer','pointer']),FGN=b('il2cpp_field_get_name','pointer',['pointer']),FGO=b('il2cpp_field_get_offset','uint32',['pointer']);
  var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;for(var a=0;a<na;a++){var i=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(i).readCString()==='holo-game.dll'){gi=i;break;}}
  var qs=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestService'));
  function rdStr(p){try{if(!p||p.isNull())return '';var len=p.add(0x10).readS32();if(len<=0||len>200)return '';var c=[];for(var i=0;i<len;i++){var ch=p.add(0x14+i*2).readU16();if(ch<32||ch>126)return '';c.push(String.fromCharCode(ch));}return c.join('');}catch(e){return '';}}
  var getP=cMN(qs,Memory.allocUtf8String('get_QuestsProto'),0);
  var ex=Memory.alloc(Process.pointerSize);ex.writePointer(ptr(0));
  var po=rI(getP,inst,ptr(0),ex); if(po.isNull())return{error:'null'};
  var rf=po.add(0x10).readPointer(); var cnt=rf.add(0x18).readS32(); var arr=rf.add(0x10).readPointer();
  var e0=arr.add(0x20).readPointer(); var cls=OGC(e0);
  // reflect ALL fields; keep time-named ones
  var allF=[], timeF=[]; var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=CGF(cls,it))&&!f.isNull()){try{var nm=FGN(f).readCString();var off=FGO(f);allF.push(nm+'@0x'+off.toString(16));
    var lo=nm.toLowerCase(); if(lo.indexOf('time')>=0||lo.indexOf('date')>=0||lo.indexOf('expir')>=0||lo.indexOf('_ms')>=0||lo.indexOf('startms')>=0||lo.endsWith('ms')||lo.indexOf('schedule')>=0||lo.indexOf('avail')>=0||lo.indexOf('claim')>=0) timeF.push({nm:nm,off:off});
  }catch(e){}}
  var out=[];
  for(var i=0;i<cnt;i++){
    var e=arr.add(0x20).add(i*8).readPointer(); if(e.isNull())continue;
    var rec={tid:rdStr(e.add(0x40).readPointer()), status:e.add(0x58).readS32(), ts:{}};
    for(var k=0;k<timeF.length;k++){ try{ rec.ts[timeF[k].nm]=e.add(timeF[k].off).readS64().toString(); }catch(er){} }
    out.push(rec);
  }
  return {cls:CGN(cls).readCString(), allFields:allF, timeFields:timeF.map(function(x){return x.nm+'@0x'+x.off.toString(16);}), quests:out};
};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.ts(inst)
sess.detach()
if 'error' in r:
    print('ERR', r['error']); sys.exit(1)
print('\nquest class:', r['cls'])
print('time-ish fields:', r['timeFields'])


def fmt(ms):
    try:
        ms = int(ms)
    except Exception:
        return None
    if 1_400_000_000_000 <= ms <= 2_000_000_000_000:           # plausible epoch ms (2014-2033)
        dt = datetime.datetime.utcfromtimestamp(ms / 1000)
        jst = dt + datetime.timedelta(hours=9)
        fut = ' <<<< FUTURE' if ms > dev_ms else ''
        return f'{jst:%Y-%m-%d %H:%M} JST{fut}'
    if 1_400_000_000 <= ms <= 2_000_000_000:                    # epoch seconds
        dt = datetime.datetime.utcfromtimestamp(ms)
        jst = dt + datetime.timedelta(hours=9)
        fut = ' <<<< FUTURE' if ms * 1000 > dev_ms else ''
        return f'{jst:%Y-%m-%d %H:%M} JST{fut}'
    return None


print('\n=== per-quest timestamps (non-trivial only) ===')
for q in r['quests']:
    tss = {k: fmt(v) for k, v in q['ts'].items()}
    tss = {k: v for k, v in tss.items() if v}
    gofest = 'GOFEST' in q['tid'].upper() or 'IRL_CITY' in q['tid'].upper()
    if tss or gofest:
        mark = '  [GOFEST]' if gofest else ''
        print(f"\n[{q['status']}] {q['tid']}{mark}")
        for k, v in tss.items():
            print(f'    {k} = {v}')
