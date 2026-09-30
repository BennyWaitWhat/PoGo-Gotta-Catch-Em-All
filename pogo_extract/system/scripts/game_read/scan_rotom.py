#!/usr/bin/env python
"""Live-read the ACTUAL form_ + shiny_ on every Rotom / Tauros proto in the bag
(the DB left 12 Rotom with null form). Authoritative source = the live PokemonDisplayProto,
form mapped via the live Form enum. READ-ONLY."""
import sys, os, json
from collections import Counter
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r'''
var P=null,CGN,CGF,FGN,FGFlags,FSGV,FGT,CFT,TGN,FGO;
function _p(){ if(CGN) return; _ensureInit(); var il=Process.findModuleByName('libil2cpp.so');
  function nf(n,r,a){return new NativeFunction(il.getExportByName(n),r,a);}
  CGN=nf('il2cpp_class_get_name','pointer',['pointer']);
  CGF=nf('il2cpp_class_get_fields','pointer',['pointer','pointer']);
  FGN=nf('il2cpp_field_get_name','pointer',['pointer']);
  FGO=nf('il2cpp_field_get_offset','uint32',['pointer']);
  FGFlags=nf('il2cpp_field_get_flags','int',['pointer']);
  FSGV=nf('il2cpp_field_static_get_value','void',['pointer','pointer']);
  FGT=nf('il2cpp_field_get_type','pointer',['pointer']);
  CFT=nf('il2cpp_class_from_type','pointer',['pointer']);
  TGN=nf('il2cpp_type_get_name','pointer',['pointer']);
  var sp=Memory.alloc(4); var asms=IL2.dGA(IL2.dG(),sp); var na=sp.readS32();
  for(var a=0;a<na;a++){ var im=IL2.aGI(asms.add(a*Process.pointerSize).readPointer()); if(IL2.iGN(im).readCString()==='holo-protos.dll'){ P=im; break; } }
}
function dumpLits(cls){ var out={}; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=CGF(cls,it))&&!f.isNull()){ try{ var fl=FGFlags(f); if((fl&0x10)&&(fl&0x40)){ var nm=FGN(f).readCString(); if(nm!=='value__'){ var b=Memory.alloc(8); b.writeU64(0); FSGV(f,b); out[b.readS32()]=nm; } } }catch(e){} } return out; }

rpc.exports.setup = function(){ _p(); if(!P) return {err:'no protos'};
  var pp=IL2.cFN(P,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('PokemonProto'));
  var pdp=IL2.cFN(P,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('PokemonDisplayProto'));
  if(pp.isNull()||pdp.isNull()) return {err:'class not found'};
  var pidOff=-1, dispOff=-1; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=CGF(pp,it))&&!f.isNull()){ try{ var nm=FGN(f).readCString().toLowerCase(); if(nm==='pokemonid_'||nm==='pokemonid') pidOff=FGO(f); if(nm==='pokemondisplay_'||nm==='pokemondisplay') dispOff=FGO(f); }catch(e){} }
  var formOff=-1, shinyOff=-1, formType=null, pdpFields=[]; var it2=Memory.alloc(Process.pointerSize); it2.writePointer(ptr(0)); var f2;
  while((f2=CGF(pdp,it2))&&!f2.isNull()){ try{ var nm=FGN(f2).readCString(); pdpFields.push(nm); var lo=nm.toLowerCase(); if(lo==='form_'||lo==='form'){ formOff=FGO(f2); formType=FGT(f2);} if(lo==='shiny_'||lo==='shiny'){ shinyOff=FGO(f2);} }catch(e){} }
  var formMap = formType? dumpLits(CFT(formType)) : {};
  return {ok:true, pidOff:pidOff, dispOff:dispOff, formOff:formOff, shinyOff:shinyOff,
          pdpFields:pdpFields, formCount:Object.keys(formMap).length, formMap:formMap};
};

rpc.exports.scanPid = function(arrJson, pid, dispOff, pidOff, formOff, shinyOff){
  var arr=JSON.parse(arrJson); var out=[];
  for(var i=0;i<arr.length;i++){ var p=ptr(arr[i]);
    try{ if(p.add(pidOff).readS32()!==pid) continue;
      var d=p.add(dispOff).readPointer(); if(!d||d.isNull()){ out.push([null,null]); continue; }
      var form=(formOff>=0)?d.add(formOff).readS32():null;
      var shiny=(shinyOff>=0)?d.add(shinyOff).readU8():null;
      out.push([form,shiny]);
    }catch(e){}
  }
  return out;
};
'''


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print('[*] connecting...')
    sess, pid = pg.get_session()
    print('[*] attached', pid)
    sc = pg.get_script_with_helpers(sess, JS)
    s = sc.exports_sync.setup()
    if not s.get('ok'):
        print('[!] setup failed:', s)
        sc.unload(); sess.detach(); return
    fmap = {int(k): v for k, v in s['formMap'].items()}
    dispOff = s['dispOff'] if s['dispOff'] >= 0 else 0xd8
    pidOff = s['pidOff'] if s['pidOff'] >= 0 else 0x28
    formOff, shinyOff = s['formOff'], s['shinyOff']
    print(f"offsets: pid@{hex(pidOff)} disp@{hex(dispOff)} form@{hex(formOff)} shiny@{hex(shinyOff)}  formEnum={s['formCount']}")
    if formOff < 0 or shinyOff < 0:
        print('[!] PokemonDisplayProto fields:', s.get('pdpFields'))

    bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
    protos = list(pg.walk_bag_protos(sess, bag).values())

    for pid_, nm in {479: 'Rotom', 128: 'Tauros'}.items():
        res = sc.exports_sync.scan_pid(json.dumps(protos), pid_, dispOff, pidOff, formOff, shinyOff)
        agg = Counter()
        for form, shiny in res:
            fn = fmap.get(form, f'??({form})') if form is not None else '(null-display)'
            agg[(fn, form, bool(shiny))] += 1
        print(f'\n=== {nm} ({pid_}) — LIVE form_+shiny_ ({len(res)} mons) ===')
        for (fn, form, sh), c in sorted(agg.items(), key=lambda x: (-x[1])):
            star = '  <<< SHINY' if sh else ''
            print(f"   {fn:30s} form={str(form):>5} shiny={sh}  x{c}{star}")

    sc.unload(); sess.detach()


if __name__ == '__main__':
    main()
