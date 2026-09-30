"""Read PoGo's authoritative HoloPokemonClass per species from live PokemonSettingsProto."""
import frida, json, time, sys
sys.path.insert(0, '.')
import pogo_il2cpp as pg

EXTRA = r'''
function cFNany(ns, cls){
  _ensureInit();
  var sp=Memory.alloc(4);
  var asms=IL2.dGA(IL2.dG(), sp);
  var na=sp.readS32();
  for(var a=0;a<na;a++){
    var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());
    var k=IL2.cFN(img, Memory.allocUtf8String(ns), Memory.allocUtf8String(cls));
    if(k && !k.isNull()) return k;
  }
  return ptr(0);
}
rpc.exports.pokemonClasses = function(){
  _ensureInit();
  var k=cFNany('Holoholo.Rpc','PokemonSettingsProto');
  if(!k || k.isNull()) return {err:'class not found in any image'};
  var r=liveness_find_instances(k);
  if(r.err) return r;
  var out=[];
  r.hits.forEach(function(h){
    try{ var p=ptr(h); out.push([p.add(16).readS32(), p.add(92).readS32(), p.add(156).readS32()]); }catch(e){}
  });
  return out;
};
'''

def run():
    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, EXTRA)
    r = sc.exports_sync.pokemon_classes()
    sess.detach()
    return r

for a in range(6):
    try:
        r = run(); break
    except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
            frida.ServerNotRunningError, RuntimeError) as e:
        print('retry', a, type(e).__name__, e); time.sleep(4); r = None

if not isinstance(r, list):
    print('FAILED:', r); sys.exit(1)
from collections import Counter
# id -> class (max class value across forms; legendary/mythic/ultra are nonzero)
idclass = {}
for idv, cls, form in r:
    idclass[idv] = max(idclass.get(idv, 0), cls)
print('settings instances:', len(r), 'distinct ids:', len(idclass))
print('class value distribution:', dict(Counter(idclass.values())))
json.dump(idclass, open('official_class.json', 'w'))
print('wrote official_class.json')
