"""READ-ONLY: read LIVE MapSettingsProto.PokemonVisibleRange / EncounterRangeMeters
from PoGo memory. Pokemod's SpawnBooster module forces both to 140 (vs ~40 default);
reading them confirms whether the range boost is active right now. Reflects the proto
for field offsets, heap-scans for instances, reads the values."""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var F=null;
function init(){ if(F)return F; var il=Process.findModuleByName('libil2cpp.so'); var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  F={dG:b('il2cpp_domain_get','pointer',[]),dGA:b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),
     aGI:b('il2cpp_assembly_get_image','pointer',['pointer']),iGN:b('il2cpp_image_get_name','pointer',['pointer']),
     cFN:b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),
     cGF:b('il2cpp_class_get_fields','pointer',['pointer','pointer']),fGN:b('il2cpp_field_get_name','pointer',['pointer']),
     fGT:b('il2cpp_field_get_type','pointer',['pointer']),fGO:b('il2cpp_field_get_offset','uint32',['pointer']),
     tGN:b('il2cpp_type_get_name','pointer',['pointer']),tA:b('il2cpp_thread_attach','pointer',['pointer'])};
  F.tA(F.dG());
  return F;
}
function protoImg(){var f=init();var sp=Memory.alloc(4);var asms=f.dGA(f.dG(),sp);var n=sp.readS32();
  for(var i=0;i<n;i++){var img=f.aGI(asms.add(i*Process.pointerSize).readPointer());if(f.iGN(img).readCString()==='holo-protos.dll')return img;}return null;}
function klassPattern(k){var bytes=[];var t=k;for(var i=0;i<8;i++){var v=t.and(0xff).toInt32();bytes.push((v<16?'0':'')+v.toString(16));t=t.shr(8);}return bytes.join(' ');}

rpc.exports.go=function(){
  var f=init(); var img=protoImg(); if(!img)return{err:'no holo-protos'};
  var k=f.cFN(img,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('MapSettingsProto'));
  if(!k||k.isNull())return{err:'no MapSettingsProto class'};
  // reflect fields
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var fld;var fields=[];var visOff=-1,encOff=-1,visT='',encT='';
  while((fld=f.cGF(k,it))&&!fld.isNull()){try{var nm=f.fGN(fld).readCString();var off=f.fGO(fld);var ty=f.tGN(f.fGT(fld)).readCString();
    fields.push(nm+'@0x'+off.toString(16)+':'+ty);var lo=nm.toLowerCase();
    if(lo.indexOf('visiblerange')>=0||lo.indexOf('visible_range')>=0||lo==='pokemonvisiblerange_'){visOff=off;visT=ty;}
    if(lo.indexOf('encounterrange')>=0||lo.indexOf('encounter_range')>=0){encOff=off;encT=ty;}
  }catch(e){}}
  // heap scan for instances
  var pat=klassPattern(k);var matches=[];
  Process.enumerateRanges('rw-').forEach(function(r){if(r.file||r.size<4096||r.size>64*1024*1024)return;
    try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length&&matches.length<200;i++)matches.push(hs[i].address);}catch(e){}});
  function rd(p,off,ty){try{if(off<0)return null;if(ty==='System.Single')return p.add(off).readFloat();if(ty==='System.Double')return p.add(off).readDouble();if(ty.indexOf('Int')>=0)return p.add(off).readS32();return p.add(off).readFloat();}catch(e){return null;}}
  var samples=[];var seen={};
  for(var i=0;i<matches.length;i++){var p=matches[i];var v=rd(p,visOff,visT);var en=rd(p,encOff,encT);
    if(v===null&&en===null)continue;var key=String(v)+'|'+String(en);if(seen[key])continue;seen[key]=true;samples.push({addr:p.toString(),visible:v,encounter:en});}
  return {cls:'MapSettingsProto', visOff:'0x'+(visOff>=0?visOff.toString(16):'?')+':'+visT, encOff:'0x'+(encOff>=0?encOff.toString(16):'?')+':'+encT, matches:matches.length, samples:samples, fields:fields};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        r = sc.exports_sync.go()
        sess.detach()
        if r.get("err"):
            print("ERR:", r["err"]); return
        print("PokemonVisibleRange field:", r["visOff"])
        print("EncounterRangeMeters field:", r["encOff"])
        print("instances scanned:", r["matches"])
        print("\n=== distinct (visible, encounter) range values found live ===")
        for s in r["samples"][:30]:
            print(f"  visible={s['visible']}  encounter={s['encounter']}   @{s['addr']}")
        print("\nall MapSettingsProto fields:")
        for x in r["fields"]:
            print("  ", x)
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()
