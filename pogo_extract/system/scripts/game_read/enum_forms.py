#!/usr/bin/env python
"""Dump the live PokemonDisplayProto.Form enum (id->name), then resolve the Tauros /
Rotom form IDs in the collection to DEFINITIVELY answer whether the GO Fest shiny
debuts (Aqua Paldean Tauros, Wash Rotom) are caught. READ-ONLY, no guessing."""
import sys, os, sqlite3
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r'''
var P=null, CGN,CGF,FGN,FGFlags,FSGV,CGNT,FGT,CFT,TGN;
function _p(){ if(CGN) return; _ensureInit(); var il=Process.findModuleByName('libil2cpp.so');
  function nf(n,r,a){return new NativeFunction(il.getExportByName(n),r,a);}
  CGN=nf('il2cpp_class_get_name','pointer',['pointer']);
  CGF=nf('il2cpp_class_get_fields','pointer',['pointer','pointer']);
  FGN=nf('il2cpp_field_get_name','pointer',['pointer']);
  FGFlags=nf('il2cpp_field_get_flags','int',['pointer']);
  FSGV=nf('il2cpp_field_static_get_value','void',['pointer','pointer']);
  CGNT=nf('il2cpp_class_get_nested_types','pointer',['pointer','pointer']);
  FGT=nf('il2cpp_field_get_type','pointer',['pointer']);
  CFT=nf('il2cpp_class_from_type','pointer',['pointer']);
  TGN=nf('il2cpp_type_get_name','pointer',['pointer']);
  var sp=Memory.alloc(4); var asms=IL2.dGA(IL2.dG(),sp); var na=sp.readS32();
  for(var a=0;a<na;a++){ var im=IL2.aGI(asms.add(a*Process.pointerSize).readPointer()); if(IL2.iGN(im).readCString()==='holo-protos.dll'){ P=im; break; } }
}
function dumpLits(cls){ var out={}; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=CGF(cls,it))&&!f.isNull()){ try{ var fl=FGFlags(f); if((fl&0x10)&&(fl&0x40)){ var nm=FGN(f).readCString(); if(nm!=='value__'){ var b=Memory.alloc(8); b.writeU64(0); FSGV(f,b); out[b.readS32()]=nm; } } }catch(e){} } return out; }

rpc.exports.dumpForm = function(){ _p(); if(!P) return {err:'no holo-protos'};
  var disp=IL2.cFN(P, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('PokemonDisplayProto'));
  if(!disp||disp.isNull()) return {err:'no PokemonDisplayProto class'};
  var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f, formType=null, fieldName=null, fields=[];
  while((f=CGF(disp,it))&&!f.isNull()){ try{ var nm=FGN(f).readCString(); fields.push(nm); var lo=nm.toLowerCase(); if(lo==='form_'||lo==='form'){ formType=FGT(f); fieldName=nm; } }catch(e){} }
  if(!formType){ var it2=Memory.alloc(Process.pointerSize); it2.writePointer(ptr(0)); var f2;
    while((f2=CGF(disp,it2))&&!f2.isNull()){ try{ var nm2=FGN(f2).readCString(); if(nm2.toLowerCase().indexOf('form')>=0){ formType=FGT(f2); fieldName=nm2; break; } }catch(e){} } }
  if(!formType) return {err:'no form field', fields:fields};
  var tn=TGN(formType).readCString();
  var formCls=CFT(formType); if(!formCls||formCls.isNull()) return {err:'no class from form type '+tn};
  var m=dumpLits(formCls);
  return {ok:true, typeName:tn, fieldName:fieldName, count:Object.keys(m).length, map:m};
};
'''


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print('[*] connecting...')
    sess, pid = pg.get_session()
    print('[*] attached', pid)
    sc = pg.get_script_with_helpers(sess, JS)
    r = sc.exports_sync.dump_form()
    sc.unload()
    sess.detach()
    if not r.get('ok'):
        print('[!] Form enum dump failed:', r.get('err'), '| nested types seen:', r.get('nested'))
        return
    fmap = {int(k): v for k, v in r['map'].items()}
    print(f"[*] Form enum: {r['count']} entries")

    c = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
    c.row_factory = sqlite3.Row
    cols = [x[1] for x in c.execute('PRAGMA table_info(pokemon)')]
    shinyc = 'is_shiny' if 'is_shiny' in cols else ('shiny' if 'shiny' in cols else None)

    for pid_, nm in {128: 'Tauros', 479: 'Rotom', 25: 'Pikachu', 10: 'Caterpie'}.items():
        print(f'\n=== {nm} ({pid_}) by form (name resolved from live enum) ===')
        q = (f"SELECT display_form f, COUNT(*) n, SUM(CASE WHEN {shinyc} THEN 1 ELSE 0 END) sh "
             f"FROM pokemon WHERE pokemon_id=? GROUP BY display_form ORDER BY n DESC")
        for row in c.execute(q, (pid_,)):
            fid = row['f']
            fname = fmap.get(fid, '??') if fid is not None else '(null/base)'
            print(f"   form={str(fid):>6} {fname:30s} count={row['n']:3d} shiny={row['sh'] or 0}")

    print('\n=== GO FEST SHINY-DEBUT VERDICT ===')
    for label, kw in [('Aqua Paldean Tauros', ('TAUROS', 'AQUA')),
                      ('Wash Rotom', ('ROTOM', 'WASH'))]:
        forms = [(i, n) for i, n in fmap.items() if all(k in n.upper() for k in kw)]
        if not forms:
            print(f'{label}: NO matching form in enum (kw={kw}) -> cannot resolve')
            continue
        for fid, fn in forms:
            row = c.execute(f"SELECT COUNT(*) n, SUM(CASE WHEN {shinyc} THEN 1 ELSE 0 END) sh "
                            f"FROM pokemon WHERE display_form=?", (fid,)).fetchone()
            have = row[0]
            shiny = row[1] or 0
            verdict = 'SHINY DEBUT CAUGHT' if shiny > 0 else ('have non-shiny' if have else 'NOT CAUGHT AT ALL')
            print(f'{label}  [{fn} = form {fid}]: have {have}, shiny {shiny}  -> {verdict}')


if __name__ == '__main__':
    main()
