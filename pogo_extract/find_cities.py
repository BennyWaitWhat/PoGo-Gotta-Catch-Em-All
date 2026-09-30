"""READ-ONLY: brute-force the templateId offset on BOTH QuestsProto lists
(+0x10 active, +0x20 the 78-entry container) to find completed City challenges
and any Mega Mewtwo / Expert / choice research. No writes."""
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
print('capturing QuestService...')
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
rpc.exports = { scan: function(addr){
  var inst=ptr(addr);
  var il=Process.findModuleByName('libil2cpp.so');var A={};il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return new NativeFunction(A[n],r,a);}
  var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),cMN=b('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']),rI=b('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
  var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;for(var a=0;a<na;a++){var i=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(i).readCString()==='holo-game.dll'){gi=i;break;}}
  var qs=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestService'));
  function rdStr(p){try{if(p.isNull())return '';var len=p.add(0x10).readS32();if(len<=0||len>120)return '';var c=[];for(var i=0;i<len;i++){var ch=p.add(0x14+i*2).readU16();if(ch<32||ch>126)return '';c.push(String.fromCharCode(ch));}return c.join('');}catch(e){return '';}}
  function tidOf(qp){ // brute-force: find a templateId-looking string at a pointer field
    var offs=[0x40,0x10,0x18,0x20,0x28,0x30,0x38,0x48,0x50,0x58,0x60];
    for(var k=0;k<offs.length;k++){try{var p=qp.add(offs[k]).readPointer();var s=rdStr(p);if(s.length>=5&&s.indexOf('_')>=0&&/^[A-Za-z0-9_]+$/.test(s))return {t:s,o:offs[k]};}catch(e){}}
    return null;
  }
  var getProto=cMN(qs,Memory.allocUtf8String('get_QuestsProto'),0);
  var ex=Memory.alloc(Process.pointerSize);ex.writePointer(ptr(0));
  var po=rI(getProto,inst,ptr(0),ex); if(po.isNull())return {error:'null'};
  var res={};
  [0x10,0x20].forEach(function(field){
    try{
      var rf=po.add(field).readPointer(); if(rf.isNull())return;
      var cnt=rf.add(0x18).readS32(); var arr=rf.add(0x10).readPointer(); if(arr.isNull()||cnt<=0||cnt>3000)return;
      var items=[];
      for(var i=0;i<Math.min(cnt,200);i++){
        var qp=arr.add(0x20).add(i*8).readPointer(); if(qp.isNull())continue;
        var r=tidOf(qp); if(!r)continue;
        var st=-1,pr=-1; try{st=qp.add(0x58).readS32();pr=qp.add(0x48).readS32();}catch(e){}
        items.push({tid:r.t, st:st, pr:pr});
      }
      res['+0x'+field.toString(16)]={count:cnt, items:items};
    }catch(e){res['+0x'+field.toString(16)]={err:String(e)};}
  });
  return res;
}};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.scan(inst)
sess.detach()
STAT = {0: 'inact', 1: 'active', 2: 'COMPLETE', 3: 'claimed', -1: '?'}
for field, info in r.items():
    if 'err' in info:
        print(f"\n{field}: ERR {info['err']}"); continue
    items = info.get('items', [])
    print(f"\n=== QuestsProto {field} : {info['count']} entries, {len(items)} tids decoded ===")
    # GO Fest / city / mewtwo / expert ones first
    key = [x for x in items if any(k in x['tid'].upper() for k in ['IRL_CITY', 'GOFEST', 'GO_FEST', 'MEWTWO', 'EXPERT', 'CHALLENGE', 'CITY', 'DISTRICT', 'TOKYO'])]
    print(f"  -- GO Fest / City / Mewtwo ({len(key)}):")
    for x in key:
        print(f"     [{STAT.get(x['st'], x['st'])}] {x['pr']}  {x['tid']}")
    if field == '+0x20':
        print(f"  -- all {len(items)} tids:")
        for x in items:
            print(f"     [{STAT.get(x['st'], x['st'])}] {x['tid']}")
