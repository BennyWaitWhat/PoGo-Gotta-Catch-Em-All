"""READ-ONLY exploration of QuestService: list its quest-getter methods, and probe
the QuestsProto object for ALL repeated-field lists (active AND completed), so we
can find finished City challenges + the Mega Mewtwo choice research. No writes."""
import sys, time, json, subprocess
import frida

ADB = '100.98.158.56:5555'
pid = int(subprocess.check_output(['adb', '-s', ADB, 'shell', 'pidof com.nianticlabs.pokemongo']).decode().strip())
print('PID', pid)
d = frida.get_device_manager().add_remote_device('127.0.0.1:27047')
sess = d.attach(pid)

hook_js = r"""
var qInst=null;
function init(){
  var il=Process.findModuleByName('libil2cpp.so'); var A={}; il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return new NativeFunction(A[n],r,a);}
  var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),cGM=b('il2cpp_class_get_methods','pointer',['pointer','pointer']),tA=b('il2cpp_thread_attach','pointer',['pointer']); tA(dG());
  var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;
  for(var a=0;a<na;a++){var i=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(i).readCString()==='holo-game.dll'){gi=i;break;}}
  var cls=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestService'));
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
  while((m=cGM(cls,it))&&!m.isNull()){try{var ad=m.readPointer();if(ad.isNull())continue;Interceptor.attach(ad,{onEnter:function(ar){if(!qInst)qInst=ar[0].toString();}});}catch(e){}}
}
rpc.exports={setup:function(){init();return{ok:1};},get:function(){return{q:qInst};}};
"""
hs = sess.create_script(hook_js); hs.on('message', lambda m, dd: None); hs.load(); hs.exports_sync.setup()
print('capturing QuestService instance (be on map/Research)...')
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
rpc.exports = {
  explore: function(addr){
    var inst=ptr(addr);
    var il=Process.findModuleByName('libil2cpp.so'); var A={}; il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
    function b(n,r,a){return new NativeFunction(A[n],r,a);}
    var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),cGM=b('il2cpp_class_get_methods','pointer',['pointer','pointer']),mGN=b('il2cpp_method_get_name','pointer',['pointer']),mGPC=b('il2cpp_method_get_param_count','uint32',['pointer']),cMN=b('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']),rI=b('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
    var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;
    for(var a=0;a<na;a++){var i=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(i).readCString()==='holo-game.dll'){gi=i;break;}}
    var qs=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestService'));
    function rdStr(p){if(p.isNull())return '';var len=p.add(0x10).readS32();if(len<=0||len>1000)return '';var c=[];for(var i=0;i<len;i++){var ch=p.add(0x14+i*2).readU16();if(ch===0)break;c.push(String.fromCharCode(ch));}return c.join('');}
    // 1) list zero-arg getter method names
    var methods=[]; var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
    while((m=cGM(qs,it))&&!m.isNull()){try{var nm=mGN(m).readCString();if(nm&&(nm.indexOf('get_')===0||nm.toLowerCase().indexOf('quest')>=0||nm.toLowerCase().indexOf('complet')>=0||nm.toLowerCase().indexOf('challenge')>=0))methods.push(nm+'/'+mGPC(m));}catch(e){}}
    // 2) get_QuestsProto, then probe its object fields 0x10..0x60 for RepeatedField lists
    var getP=cMN(qs,Memory.allocUtf8String('get_QuestsProto'),0);
    var ex=Memory.alloc(Process.pointerSize);ex.writePointer(ptr(0));
    var po=rI(getP,inst,ptr(0),ex);
    var lists=[];
    if(!po.isNull()){
      for(var off=0x10; off<=0x60; off+=8){
        try{
          var rf=po.add(off).readPointer(); if(rf.isNull())continue;
          var cnt=rf.add(0x18).readS32(); var arr=rf.add(0x10).readPointer();
          if(cnt<=0||cnt>2000||arr.isNull())continue;
          var samp=[];
          for(var i=0;i<Math.min(cnt,60);i++){
            var qp=arr.add(0x20).add(i*8).readPointer(); if(qp.isNull())continue;
            var tid=rdStr(qp.add(0x40).readPointer());
            var st=qp.add(0x58).readS32(); var pr=qp.add(0x48).readS32();
            var tg=0; try{var g=qp.add(0x50).readPointer(); if(!g.isNull())tg=g.add(0x18).readS32();}catch(e){}
            if(tid) samp.push({tid:tid,st:st,pr:pr,tg:tg});
          }
          lists.push({off:'+0x'+off.toString(16), count:cnt, items:samp});
        }catch(e){}
      }
    }
    return {methods:methods, lists:lists};
  }
};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.explore(inst)
sess.detach()
print('\n=== QuestService getter methods ===')
print(', '.join(sorted(set(r.get('methods', [])))))
STAT = {0: 'inactive', 1: 'active', 2: 'COMPLETE', 3: 'claimed'}
for lst in r.get('lists', []):
    print(f"\n=== QuestsProto field {lst['off']} : {lst['count']} entries ===")
    for it in lst['items']:
        print(f"  [{STAT.get(it['st'], it['st'])}] {it['pr']}/{it['tg']}  {it['tid']}")
