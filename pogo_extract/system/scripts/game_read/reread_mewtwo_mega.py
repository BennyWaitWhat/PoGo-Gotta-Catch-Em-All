"""TRIPLE-CHECK (fresh, live, reflection-based): walk the LIVE bag, find every
Mewtwo (pid 150), and reflect the proto to dump ALL mega / temporary-evolution
fields — including any X/Y-specific unlock the standard crawl columns would miss.
Also enumerates any TemporaryEvolution list. Definitively answers: is there a Mega
Mewtwo (X or Y) unlocked on ANY of your Mewtwo right now? READ-ONLY."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
import pogo_il2cpp as pg

sess, pid = pg.get_session()
print('attached pid', pid)
bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
bagmap = pg.walk_bag_protos(sess, bag)            # {uid_dec: proto_ptr}
protos = list(bagmap.values())
print('live bag protos:', len(protos))

JS = r"""
var H=null;
function helpers(){ if(H)return H; var il=Process.findModuleByName('libil2cpp.so');var A={};il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return new NativeFunction(A[n],r,a);}
  H={OGC:b('il2cpp_object_get_class','pointer',['pointer']),CGN:b('il2cpp_class_get_name','pointer',['pointer']),CGF:b('il2cpp_class_get_fields','pointer',['pointer','pointer']),FGN:b('il2cpp_field_get_name','pointer',['pointer']),FGO:b('il2cpp_field_get_offset','uint32',['pointer'])};
  return H; }
function fieldsOf(p){ var h=helpers(); var cls=h.OGC(p); var out=[]; var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=h.CGF(cls,it))&&!f.isNull()){try{out.push({nm:h.FGN(f).readCString(),off:h.CGN?h.FGO(f):0});}catch(e){}} return {cls:h.CGN(cls).readCString(), fields:out}; }

rpc.exports.reflect = function(s){ return fieldsOf(ptr(s)); };

rpc.exports.pidoff = function(s){ var r=fieldsOf(ptr(s)); for(var i=0;i<r.fields.length;i++){var n=r.fields[i].nm.toLowerCase(); if(n==='pokemonid'||n==='pokemonid_'){return r.fields[i].off;}} return -1; };

rpc.exports.pids = function(arrJson, off){ var arr=JSON.parse(arrJson); var out=[]; for(var i=0;i<arr.length;i++){ try{out.push(ptr(arr[i]).add(off).readS32());}catch(e){out.push(null);} } return out; };

// dump every mega/temp/evolution/bread-named field for one proto: int value + (if pointer to a RepeatedField) its count + first elems as int
rpc.exports.megadump = function(s){ var h=helpers(); var p=ptr(s); var cls=h.OGC(p); var rec={cls:h.CGN(cls).readCString(),f:{}};
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=h.CGF(cls,it))&&!f.isNull()){ try{ var nm=h.CGF?h.FGN(f).readCString():''; var off=h.FGO(f); var lo=nm.toLowerCase();
    if(lo.indexOf('mega')>=0||lo.indexOf('temp')>=0||lo.indexOf('evol')>=0||lo.indexOf('bread')>=0||lo.indexOf('candy')>=0){
      var iv=null,rf=null; try{iv=p.add(off).readS32();}catch(e){}
      try{ var pp=p.add(off).readPointer(); if(!pp.isNull()){ var cnt=pp.add(0x18).readS32(); if(cnt>=0&&cnt<50){ var sarr=pp.add(0x10).readPointer(); var el=[]; if(!sarr.isNull()) for(var j=0;j<Math.min(cnt,8);j++){ try{el.push(sarr.add(0x20).add(j*8).readPointer().toString());}catch(e){el.push('?');} } rf={count:cnt,elems:el}; } } }catch(e){}
      rec.f[nm+'@0x'+off.toString(16)]={int:iv, rf:rf};
    } }catch(e){} }
  return rec; };
"""
sc = sess.create_script(JS); sc.on('message', lambda m, d: None); sc.load()

poff = sc.exports_sync.pidoff(protos[0])
print('PokemonId field offset:', hex(poff) if poff >= 0 else 'NOT FOUND')
if poff < 0:
    print('reflect of proto[0]:', json.dumps(sc.exports_sync.reflect(protos[0]))[:1500]); sess.detach(); sys.exit(1)

allpids = sc.exports_sync.pids(json.dumps(protos), poff)
mewtwo_protos = [protos[i] for i, pv in enumerate(allpids) if pv == 150]
print(f'\nLIVE Mewtwo (pid 150) in bag: {len(mewtwo_protos)}')

print('\n=== full field list of a Mewtwo proto (to spot ANY mega/temp field) ===')
ref = sc.exports_sync.reflect(mewtwo_protos[0]) if mewtwo_protos else None
if ref:
    megaish = [f"{x['nm']}@0x{x['off']:x}" for x in ref['fields'] if any(k in x['nm'].lower() for k in ('mega', 'temp', 'evol', 'bread'))]
    print('  class:', ref['cls'])
    print('  mega/temp/evo fields present:', megaish)

print('\n=== per-Mewtwo mega/temp-evolution dump ===')
any_mega = False
for i, p in enumerate(mewtwo_protos):
    md = sc.exports_sync.megadump(p)
    nz = {k: v for k, v in md['f'].items() if (v.get('int') not in (None, 0)) or (v.get('rf') and v['rf'].get('count', 0) > 0)}
    flag = ''
    for k, v in nz.items():
        if v.get('rf') and v['rf'].get('count', 0) > 0 and ('temp' in k.lower() or 'mega' in k.lower() or 'evol' in k.lower()):
            any_mega = True; flag = '   <<<< HAS A TEMP/MEGA-EVOLUTION ENTRY'
    print(f'  Mewtwo#{i}: {nz}{flag}')
sess.detach()
print('\nTRIPLE-CHECK VERDICT:', 'A Mewtwo HAS a mega/temp-evolution unlock -> you DO have a Mega Mewtwo!' if any_mega else 'NO Mewtwo has any mega/temporary-evolution unlock -> confirmed: no Mega Mewtwo.')
