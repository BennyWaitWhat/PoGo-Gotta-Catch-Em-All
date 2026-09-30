#!/usr/bin/env python
"""Comprehensive LIVE GO Fest Tokyo 2026 catch audit. Dumps the Form + Costume enums,
live-reads form_/costume_/shiny_ on every relevant species, and scores the exclusives
definitively (no DB, no guessing). READ-ONLY."""
import sys, os, json
from collections import Counter
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r'''
var P=null,CGN,CGF,FGN,FGFlags,FSGV,FGT,CFT,TGN,FGO;
function _p(){ if(CGN) return; _ensureInit(); var il=Process.findModuleByName('libil2cpp.so');
  function nf(n,r,a){return new NativeFunction(il.getExportByName(n),r,a);}
  CGN=nf('il2cpp_class_get_name','pointer',['pointer']); CGF=nf('il2cpp_class_get_fields','pointer',['pointer','pointer']);
  FGN=nf('il2cpp_field_get_name','pointer',['pointer']); FGO=nf('il2cpp_field_get_offset','uint32',['pointer']);
  FGFlags=nf('il2cpp_field_get_flags','int',['pointer']); FSGV=nf('il2cpp_field_static_get_value','void',['pointer','pointer']);
  FGT=nf('il2cpp_field_get_type','pointer',['pointer']); CFT=nf('il2cpp_class_from_type','pointer',['pointer']); TGN=nf('il2cpp_type_get_name','pointer',['pointer']);
  var sp=Memory.alloc(4); var asms=IL2.dGA(IL2.dG(),sp); var na=sp.readS32();
  for(var a=0;a<na;a++){ var im=IL2.aGI(asms.add(a*Process.pointerSize).readPointer()); if(IL2.iGN(im).readCString()==='holo-protos.dll'){ P=im; break; } }
}
function dumpLits(cls){ var out={}; if(!cls||cls.isNull()) return out; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=CGF(cls,it))&&!f.isNull()){ try{ var fl=FGFlags(f); if((fl&0x10)&&(fl&0x40)){ var nm=FGN(f).readCString(); if(nm!=='value__'){ var b=Memory.alloc(8); b.writeU64(0); FSGV(f,b); out[b.readS32()]=nm; } } }catch(e){} } return out; }
function fieldInfo(cls){ var out={}; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=CGF(cls,it))&&!f.isNull()){ try{ var fl=FGFlags(f); if(fl&0x10) continue; out[FGN(f).readCString()]={off:FGO(f), type:FGT(f)}; }catch(e){} } return out; }

rpc.exports.setup=function(){ _p(); if(!P) return {err:'no protos'};
  var pp=IL2.cFN(P,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('PokemonProto'));
  var pdp=IL2.cFN(P,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('PokemonDisplayProto'));
  if(pp.isNull()||pdp.isNull()) return {err:'class not found'};
  var pf=fieldInfo(pp), df=fieldInfo(pdp);
  function fo(fields,names){ for(var k in fields){ var lk=k.toLowerCase(); for(var i=0;i<names.length;i++) if(lk===names[i]) return fields[k]; } return null; }
  var pidF=fo(pf,['pokemonid_','pokemonid']), dispF=fo(pf,['pokemondisplay_','pokemondisplay']);
  var formF=fo(df,['form_','form']), shinyF=fo(df,['shiny_','shiny']), costF=fo(df,['costume_','costume']);
  return {ok:true, pidOff:pidF?pidF.off:0x28, dispOff:dispF?dispF.off:0xd8,
    formOff:formF?formF.off:-1, shinyOff:shinyF?shinyF.off:-1, costOff:costF?costF.off:-1,
    formMap: formF?dumpLits(CFT(formF.type)):{}, costMap: costF?dumpLits(CFT(costF.type)):{}};
};

rpc.exports.scan=function(arrJson, pidsJson, dispOff,pidOff,formOff,shinyOff,costOff){
  var arr=JSON.parse(arrJson); var pids=JSON.parse(pidsJson); var want={}; for(var i=0;i<pids.length;i++) want[pids[i]]=1; var out={};
  for(var i=0;i<arr.length;i++){ var p=ptr(arr[i]); try{ var pid=p.add(pidOff).readS32(); if(!want[pid]) continue;
    var d=p.add(dispOff).readPointer(); var form=null,shiny=null,cost=null;
    if(d&&!d.isNull()){ if(formOff>=0)form=d.add(formOff).readS32(); if(shinyOff>=0)shiny=d.add(shinyOff).readU8(); if(costOff>=0)cost=d.add(costOff).readS32(); }
    if(!out[pid])out[pid]=[]; out[pid].push([form,cost,shiny]);
  }catch(e){} } return out;
};
'''

PIDS = {25: 'Pikachu', 10: 'Caterpie', 479: 'Rotom', 128: 'Tauros', 764: 'Comfey', 807: 'Zeraora',
        144: 'Articuno', 245: 'Suicune', 150: 'Mewtwo'}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print('[*] connecting...')
    sess, pid = pg.get_session()
    print('[*] attached', pid)
    sc = pg.get_script_with_helpers(sess, JS)
    s = sc.exports_sync.setup()
    if not s.get('ok'):
        print('[!] setup failed:', s); sc.unload(); sess.detach(); return
    fmap = {int(k): v for k, v in s['formMap'].items()}
    cmap = {int(k): v for k, v in s['costMap'].items()}
    print(f"offsets pid@{hex(s['pidOff'])} disp@{hex(s['dispOff'])} form@{hex(s['formOff'])} "
          f"shiny@{hex(s['shinyOff'])} costume@{hex(s['costOff'])}  | forms={len(fmap)} costumes={len(cmap)}")

    print('\n=== Form/Costume enum entries relevant to GO Fest 2026 / Mystic / Tokyo ===')
    for label, m in [('FORM', fmap), ('COSTUME', cmap)]:
        hits = {i: n for i, n in m.items() if any(k in n.lower() for k in ('gofest2026', 'mystic', 'tokyo', 'gofest_2026'))}
        print(f'  {label}: {hits if hits else "(none matched)"}')

    bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
    protos = list(pg.walk_bag_protos(sess, bag).values())
    res = sc.exports_sync.scan(json.dumps(protos), json.dumps(list(PIDS)), s['dispOff'], s['pidOff'],
                               s['formOff'], s['shinyOff'], s['costOff'])
    sc.unload(); sess.detach()

    for pid_str, label in [(str(p), PIDS[p]) for p in PIDS]:
        rows = res.get(pid_str) or res.get(int(pid_str)) or []
        agg = Counter()
        for form, cost, shiny in rows:
            fn = fmap.get(form, f'?{form}') if form is not None else 'null'
            cn = cmap.get(cost, f'?{cost}') if cost not in (None, 0) else '-'
            agg[(fn, cn, bool(shiny))] += 1
        print(f'\n=== {label} ({pid_str}) — {len(rows)} mons (LIVE) ===')
        for (fn, cn, sh), c in sorted(agg.items(), key=lambda x: -x[1]):
            print(f"   form={fn:28s} costume={cn:22s} shiny={sh}  x{c}{'  <<<SHINY' if sh else ''}")


if __name__ == '__main__':
    main()
