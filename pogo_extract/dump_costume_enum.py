"""Dump the PoGo Costume enum (PokemonDisplayProto.Costume / HoloPokemonCostume) to
costume_enum.json as {id: name} -- the field-costume id->name map the platform lacks.

Mirrors dump_form_enum.py's IL2CPP literal-field walk, but instead of guessing the class
name it SCANS every class for one named *costume* and picks the richest enum. Falls back to
il2cpp_class_from_name candidates if image class-enumeration isn't exported on this build.
"""
import frida, json, subprocess

adb_pid = int(subprocess.check_output(['adb', 'shell', 'pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = r"""
rpc.exports = {
  dump: function() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var addrs = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name]=e.address; });
    function B(n,r,a){ if(!addrs[n]) return null; try{ return new NativeFunction(addrs[n],r,a); }catch(e){ return null; } }
    var dG=B('il2cpp_domain_get','pointer',[]);
    var dGA=B('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    var aGI=B('il2cpp_assembly_get_image','pointer',['pointer']);
    var iGN=B('il2cpp_image_get_name','pointer',['pointer']);
    var iGCC=B('il2cpp_image_get_class_count','uint32',['pointer']);
    var iGC=B('il2cpp_image_get_class','pointer',['pointer','uint32']);
    var cFN=B('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    var cGN=B('il2cpp_class_get_name','pointer',['pointer']);
    var cGNS=B('il2cpp_class_get_namespace','pointer',['pointer']);
    var cGF=B('il2cpp_class_get_fields','pointer',['pointer','pointer']);
    var fGN=B('il2cpp_field_get_name','pointer',['pointer']);
    var fGF=B('il2cpp_field_get_flags','int',['pointer']);
    var fGSV=B('il2cpp_field_static_get_value','void',['pointer','pointer']);
    var tA=B('il2cpp_thread_attach','pointer',['pointer']);
    if(tA) tA(dG());

    function dumpEnum(cls){
      var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
      var f, res={};
      while((f=cGF(cls,iter)) && !f.isNull()){
        var flags=fGF(f);
        if((flags&0x10)===0) continue;   // STATIC
        if((flags&0x40)===0) continue;   // LITERAL (enum member)
        var vb=Memory.alloc(8); vb.writeS64(0);
        try{ fGSV(f,vb); res[vb.readS32()]=fGN(f).readCString(); }catch(e){}
      }
      return res;
    }

    var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32();
    var imgs=[];
    for(var ai=0; ai<na; ai++) imgs.push(aGI(asms.add(ai*Process.pointerSize).readPointer()));

    var found={};
    // primary: scan every class for a name containing "costume"
    if(iGCC && iGC){
      for(var i=0;i<imgs.length;i++){
        var cc=iGCC(imgs[i]);
        for(var ci=0; ci<cc; ci++){
          var cls=iGC(imgs[i],ci);
          if(!cls||cls.isNull()) continue;
          var nm; try{ nm=cGN(cls).readCString(); }catch(e){ continue; }
          if(!nm || nm.toLowerCase().indexOf('costume')<0) continue;
          var en=dumpEnum(cls);
          if(Object.keys(en).length>3){
            var ns=''; try{ ns=cGNS(cls).readCString()||''; }catch(e){}
            found[(ns?ns+'.':'')+nm]={count:Object.keys(en).length, enum:en};
          }
        }
      }
    }
    // fallback: named candidates
    if(Object.keys(found).length===0 && cFN){
      var cand=[['','PokemonCostume'],['Holoholo.Rpc','HoloPokemonCostume'],['','HoloPokemonCostume'],
                ['','Costume'],['','PokemonDisplayProto/Costume'],['Holoholo.Rpc','PokemonDisplayProto/Costume']];
      for(var ii=0; ii<imgs.length; ii++){
        for(var k=0;k<cand.length;k++){
          var cls2=cFN(imgs[ii], Memory.allocUtf8String(cand[k][0]), Memory.allocUtf8String(cand[k][1]));
          if(!cls2||cls2.isNull()) continue;
          var en2=dumpEnum(cls2);
          if(Object.keys(en2).length>3) found[cand[k][1]]={count:Object.keys(en2).length, enum:en2};
        }
      }
    }
    return found;
  }
};
"""

script = sess.create_script(js)
script.load()
r = script.exports_sync.dump()
sess.detach()

print('costume-named enum classes found:', {k: v['count'] for k, v in r.items()})
if not r:
    print('NONE FOUND -- costume enum class not located'); raise SystemExit(1)
best = max(r.items(), key=lambda kv: kv[1]['count'])
enum = {str(k): v for k, v in best[1]['enum'].items()}
print('USING: %s  (%d members)' % (best[0], best[1]['count']))
json.dump(enum, open('costume_enum.json', 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print('--- sample (first 30 by id) ---')
for v, name in sorted(enum.items(), key=lambda kv: int(kv[0]))[:30]:
    print('  %4s  %s' % (v, name))
print('wrote costume_enum.json (%d entries)' % len(enum))
