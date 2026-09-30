#!/usr/bin/env python
"""TOTAL form audit -- no spot-checks, no guessing.

Dumps the live PokemonDisplayProto.Form enum (id->name) from the game's IL2CPP metadata,
then resolves + classifies EVERY distinct form code present in the bag. The form NAME is
ground truth from the game, so a costume reads as a costume, a regional as a regional, a
battle-form as a battle-form. Writes form_enum.json (full enum) + bag_form_resolution.json
(every bag form with its resolved name + current keep-treatment).

Built 2026-06-04 after the Lapras-2585 costume miss -- so we classify on the authoritative
enum instead of inferring from the raw form number.
"""
import sys, os, sqlite3, json
from collections import defaultdict
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

# keyword markers for the FIRST-PASS class (verify against the printed real name)
REGION = ('ALOLA', 'GALARIAN', 'GALAR', 'HISUIAN', 'HISUI', 'PALDEA')
# functional / natural-collectible forms that are NOT costumes
FUNC = ('NORMAL', 'ORIGIN', 'ALTERED', 'ATTACK', 'DEFENSE', 'SPEED', 'THERIAN', 'INCARNATE',
        'BLACK', 'WHITE', 'SUNNY', 'RAINY', 'SNOWY', 'HEAT', 'WASH', 'FROST', 'FAN', 'MOW',
        'SKY', 'LAND', 'SUNSHINE', 'OVERCAST', 'ZEN', 'STANDARD', 'BLADE', 'SHIELD', 'CROWNED',
        'HERO', 'SINGLE_STRIKE', 'RAPID_STRIKE', 'AMPED', 'LOW_KEY', 'FULL_BELLY', 'HANGRY',
        'ICE', 'NOICE', 'UNBOUND', 'CONFINED', 'MALE', 'FEMALE', 'PLANT', 'SANDY', 'TRASH',
        'EAST', 'WEST', 'SPRING', 'SUMMER', 'AUTUMN', 'WINTER', 'RED', 'BLUE', 'YELLOW',
        'ORANGE', 'GREEN', 'VIOLET', 'INDIGO', 'SMALL', 'AVERAGE', 'LARGE', 'SUPER', 'ARIA',
        'PIROUETTE', 'ORDINARY', 'RESOLUTE', 'SHOCK', 'BURN', 'CHILL', 'TWO_SEGMENT',
        'THREE_SEGMENT', 'FAMILY_OF', 'CURLY', 'DROOPY', 'STRETCHY', 'PLUMAGE', 'A', 'B',
        'EXCLAMATION', 'QUESTION', 'DUSK', 'MIDNIGHT', 'MIDDAY', 'GULPING', 'GORGING')
COSTUME_HINT = ('COSTUME', 'HAT', 'CAP', 'GLASSES', 'FLOWER_CROWN', 'HOLIDAY', 'WINTER_2',
                'SUMMER_2', 'FALL_2', 'SPRING_2', 'PARTY', 'FLYING', 'SURFING', 'LIBRE', 'POP_STAR',
                'ROCK_STAR', 'KARIYUSHI', 'WITCH', 'SANTA', 'SCARF', 'BALLOON', 'CONFETTI',
                'VISOR', 'BANDANA', 'TUXEDO', 'WEDDING', 'DETECTIVE', 'JUNGLE', 'ADVENTURE',
                'ANNIVERSARY', 'ANNIV', 'ASH', 'CROWN', 'FASHION', 'STARMOBILE')


def classify(name):
    if name is None:
        return 'base/null'
    u = name.upper()
    if any(r in u for r in REGION):
        return 'regional'
    if any(h in u for h in COSTUME_HINT) or any(ch.isdigit() for ch in u):  # dated/event = costume
        return 'COSTUME'
    if any(('_' + f) in ('_' + u) or u.endswith('_' + f) or u == f or ('_' + f + '_') in u for f in FUNC):
        return 'form'
    return 'UNKNOWN->verify'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print('[*] connecting to game...')
    sess, pid = pg.get_session()
    print('[*] attached', pid)
    sc = pg.get_script_with_helpers(sess, JS)
    r = sc.exports_sync.dump_form()
    sc.unload(); sess.detach()
    if not r.get('ok'):
        print('[!] enum dump FAILED:', r.get('err'), '| fields:', (r.get('fields') or [])[:20])
        return
    fmap = {int(k): v for k, v in r['map'].items()}
    json.dump(fmap, open(os.path.join(ROOT, 'form_enum.json'), 'w', encoding='utf-8'), indent=0, sort_keys=True)
    print(f"[*] Form enum: {len(fmap)} entries (field={r.get('fieldName')}) -> form_enum.json")

    c = sqlite3.connect(os.path.join(ROOT, 'pokemon.db')); c.row_factory = sqlite3.Row
    rows = c.execute(
        """SELECT pokemon_id pid, species_name s, COALESCE(fresh_form,form,0) f, COUNT(*) n,
                  SUM(CASE WHEN COALESCE(fresh_costume,0)=0 AND COALESCE(special_bg_id,0)=0
                            AND COALESCE(natural_art_background,0)=0 AND COALESCE(fresh_bread_mode,0)=0
                           THEN 1 ELSE 0 END) plain,
                  SUM(CASE WHEN auth_tag_names LIKE '%Event%' THEN 1 ELSE 0 END) ev
             FROM pokemon WHERE in_bag=1
            GROUP BY pokemon_id, COALESCE(fresh_form,form,0)""").fetchall()
    bysp = defaultdict(list); full = []
    for r2 in rows:
        nm = fmap.get(r2['f']) if r2['f'] else None
        cls = classify(nm)
        bysp[(r2['pid'], r2['s'])].append((r2['f'], nm, cls, r2['n'], r2['plain'], r2['ev']))
        full.append({'pid': r2['pid'], 'species': r2['s'], 'form': r2['f'], 'name': nm,
                     'class': cls, 'count': r2['n'], 'plain': r2['plain'], 'event_tagged': r2['ev']})
    json.dump(full, open(os.path.join(ROOT, 'bag_form_resolution.json'), 'w', encoding='utf-8'), indent=1)

    # THE GAP: a COSTUME form whose mons are treated as plain (no cosmetic field) and not Event-tagged
    print("\n=== COSTUME / UNKNOWN form codes treated as PLAIN (the tagging gap) ===")
    gap = 0
    for (pid_, s), forms in sorted(bysp.items()):
        for f, nm, cls, n, plain, ev in forms:
            if cls in ('COSTUME', 'UNKNOWN->verify') and plain > 0:
                print(f"   {s:14s} form={str(f):>5} {(nm or '?'):32s} {cls:14s} n={n} plain={plain} event={ev}")
                gap += plain
    print(f"   -> {gap} specimens are costume/unknown forms currently treated as PLAIN")

    print("\n=== EVERY species with >1 distinct form code (resolved from live enum) ===")
    for (pid_, s), forms in sorted(bysp.items()):
        if len(forms) > 1:
            print(f"{s} ({pid_}):")
            for f, nm, cls, n, plain, ev in sorted(forms):
                print(f"   form={str(f):>5}  {(nm or '(base/null)'):34s} [{cls:14s}] n={n:<3} plain={plain} event={ev}")


if __name__ == '__main__':
    main()
