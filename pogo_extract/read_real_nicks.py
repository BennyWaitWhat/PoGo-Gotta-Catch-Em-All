"""Read the REAL nickname via Holoholo.Rpc.PokemonProto::get_Nickname (resolved from
holo-protos.dll), vs offset 184 (what the crawl/extractor reads). Self-contained il2cpp
binding so it doesn't depend on the helper's game-image-only cFN.
Usage: python read_real_nicks.py [uid_hex ...]   (defaults to first 18 of fill_names.json)
"""
import sys, os, json, sqlite3, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'system', 'scripts'))
import pogo_il2cpp as pg

RAW_JS = r"""
var il2 = Process.findModuleByName('libil2cpp.so');
var exp = {}; il2.enumerateExports().forEach(function(e){ if(e.name.indexOf('il2cpp_')===0) exp[e.name]=e.address; });
function bind(n,r,a){ return exp[n] ? new NativeFunction(exp[n], r, a) : null; }
var dG=bind('il2cpp_domain_get','pointer',[]), dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
var aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']), iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
var cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
var cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']), mGN=bind('il2cpp_method_get_name','pointer',['pointer']);
var mGPC=bind('il2cpp_method_get_param_count','int',['pointer']);
var rInv=bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']), tA=bind('il2cpp_thread_attach','pointer',['pointer']);
var dom=dG(); tA(dom);
var sp=Memory.alloc(4); var asms=dGA(dom,sp); var na=sp.readS32();
var protoImg=null;
for(var i=0;i<na;i++){ var img=aGI(asms.add(i*Process.pointerSize).readPointer()); if(iGN(img).readCString()==='holo-protos.dll'){protoImg=img;break;} }
var pmCls = protoImg ? cFN(protoImg, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('PokemonProto')) : ptr(0);
var getNick=null;
if(pmCls && !pmCls.isNull()){ var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m;
  while((m=cGM(pmCls,it))&&!m.isNull()){ if(mGN(m).readCString()==='get_Nickname' && mGPC(m)===0){ getNick=m; break; } } }
function _readStr(s){ if(!s||s.isNull())return ''; try{var len=s.add(0x10).readS32(); if(len<0||len>200)return '<bad'+len+'>'; return s.add(0x14).readUtf16String(len);}catch(e){return '<err>';} }
function readReal(protoStr){ if(!getNick)return '<no get_Nickname method>';
  var exc=Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
  var s=rInv(getNick, ptr(protoStr), ptr(0), exc);
  if(!exc.readPointer().isNull())return '<exc>';
  return _readStr(s); }
function read184(protoStr){ try{ var np=ptr(protoStr).add(184).readPointer(); return _readStr(np);}catch(e){return '<err>';} }
rpc.exports.diag=function(){ return {protoImg: protoImg?protoImg.toString():null, pmCls: pmCls?pmCls.toString():null, getNick: getNick?getNick.toString():null}; };
rpc.exports.readReal=readReal;
rpc.exports.read184=read184;
"""

HERE = os.path.dirname(os.path.abspath(__file__))
c = sqlite3.connect(os.path.join(HERE, 'pokemon.db')); c.row_factory = sqlite3.Row
nm = {r['uid_hex']: r['species_name'] for r in c.execute('SELECT uid_hex,species_name FROM pokemon WHERE in_bag=1')}
uids = sys.argv[1:] or [u for u, _ in json.load(open(os.path.join(HERE, 'fill_names.json')))][:18]

sess, pid = pg.get_session()
print(f"attached pid={pid}; reading {len(uids)} mons")
bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
dec2hex = {str(int(u, 16)): u for u in uids}
protos = pg.find_protos_for_uids(sess, bag, list(dec2hex.keys()))
script = sess.create_script(RAW_JS)
script.on('message', lambda m, d: print('[JS]', m.get('description') or m.get('payload')) if m.get('type') == 'error' else None)
script.load()
print("diag:", script.exports_sync.diag())
print(f"resolved {len(protos)}/{len(uids)} protos\n")
print(f"{'species':<13} {'REAL get_Nickname':<22} {'offset184 (crawl read)'}")
print('-' * 70)
try:
    for dec, proto in protos.items():
        uh = dec2hex[dec]
        real = script.exports_sync.read_real(proto)
        ov = script.exports_sync.read184(proto)
        flag = '  <-- DIFFER' if real != ov else ''
        print(f"{nm.get(uh, '?'):<13} {repr(real):<22} {repr(ov)}{flag}")
finally:
    script.unload()
    sess.detach()
