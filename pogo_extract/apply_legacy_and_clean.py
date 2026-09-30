"""One Frida session:
1. Create 'Legacy' tag, tag all accurate-legacy pokemon (legacy_accurate.json)
2. Pull legacy + 8 regional-variant conflicts out of REVIEW tag
Uses pogo_il2cpp liveness API for singletons + bulk_tag.js for tag ops.
"""
import frida, json, sqlite3, sys, time
sys.path.insert(0, '.')
import pogo_il2cpp as pg

sess, pid = pg.get_session()
print(f"PID: {pid}")

# Find correct svc via liveness + tag-count probe
js_scan = """
rpc.exports = { scan: function() {
  var il2cpp=Process.findModuleByName("libil2cpp.so");
  var exp={}; il2cpp.enumerateExports().forEach(function(e){ if(e.name.indexOf("il2cpp_")===0) exp[e.name]=e.address; });
  function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
  var dG=bind("il2cpp_domain_get","pointer",[]),dGA=bind("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]);
  var aGI=bind("il2cpp_assembly_get_image","pointer",["pointer"]),iGN=bind("il2cpp_image_get_name","pointer",["pointer"]);
  var cFN=bind("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cGM=bind("il2cpp_class_get_methods","pointer",["pointer","pointer"]);
  var mGN=bind("il2cpp_method_get_name","pointer",["pointer"]),rI=bind("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]);
  var tA=bind("il2cpp_thread_attach","pointer",["pointer"]); tA(dG());
  var lvA=bind("il2cpp_unity_liveness_allocate_struct","pointer",["pointer","int","pointer","pointer","pointer"]);
  var lvC=bind("il2cpp_unity_liveness_calculation_from_statics","void",["pointer"]);
  var lvF=bind("il2cpp_unity_liveness_finalize","void",["pointer"]),lvFr=bind("il2cpp_unity_liveness_free_struct","void",["pointer"]);
  var al=bind("il2cpp_alloc","pointer",["size_t"]),fr=bind("il2cpp_free","void",["pointer"]);
  var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32(); var gi=null;
  for(var a=0;a<na;a++){var i=aGI(asms.add(a*8).readPointer()); if(iGN(i).readCString()==="holo-game.dll"){gi=i;break;}}
  var cls=cFN(gi,Memory.allocUtf8String("Niantic.Holoholo.Tagging"),Memory.allocUtf8String("TaggingRpcService"));
  var hits=[]; var onO=new NativeCallback(function(arr,c,u){for(var i=0;i<c;i++)hits.push(arr.add(i*8).readPointer().toString());},"void",["pointer","int","pointer"]);
  var re=new NativeCallback(function(h,s,u){if(!h.isNull()&&s.compare(0)===0){fr(h);return ptr(0);}return al(s);},"pointer",["pointer","size_t","pointer"]);
  var st=lvA(cls,0,onO,ptr(0),re); lvC(st); lvF(st); lvFr(st);
  var iter=Memory.alloc(8); iter.writePointer(ptr(0)); var m,gnt=null;
  while((m=cGM(cls,iter))&&!m.isNull()){if(mGN(m).readCString()==="get_NumberOfTags")gnt=m;}
  var best=null,bn=0;
  for(var i=0;i<hits.length;i++){try{var ex=Memory.alloc(8);ex.writePointer(ptr(0));var rr=rI(gnt,ptr(hits[i]),ptr(0),ex);if(ex.readPointer().isNull()){var n=rr.add(0x10).readS32();if(n>bn){bn=n;best=hits[i];}}}catch(e){}}
  return {svc:best,n:bn};
}};
"""
sc = sess.create_script(js_scan); sc.load()
r = sc.exports_sync.scan()
SVC = r['svc']
print(f"svc={SVC} numTags={r['n']}")
sc.unload()

bulk = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
bulk.load(); bulk.exports_sync.init_status()

# Build proto map via bag walk (need bag instance)
try:
    BAG = pg.find_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
except Exception as e:
    print(f"find_singleton fallback: {e}")
    BAG = None
if not BAG:
    bjs = """
    rpc.exports = { bag: function() {
      var il2cpp=Process.findModuleByName("libil2cpp.so");
      var exp={}; il2cpp.enumerateExports().forEach(function(e){ if(e.name.indexOf("il2cpp_")===0) exp[e.name]=e.address; });
      function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
      var dG=bind("il2cpp_domain_get","pointer",[]),dGA=bind("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]);
      var aGI=bind("il2cpp_assembly_get_image","pointer",["pointer"]),iGN=bind("il2cpp_image_get_name","pointer",["pointer"]);
      var cFN=bind("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]);
      var cMN=bind("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI=bind("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]);
      var tA=bind("il2cpp_thread_attach","pointer",["pointer"]); tA(dG());
      var lvA=bind("il2cpp_unity_liveness_allocate_struct","pointer",["pointer","int","pointer","pointer","pointer"]);
      var lvC=bind("il2cpp_unity_liveness_calculation_from_statics","void",["pointer"]);
      var lvF=bind("il2cpp_unity_liveness_finalize","void",["pointer"]),lvFr=bind("il2cpp_unity_liveness_free_struct","void",["pointer"]);
      var al=bind("il2cpp_alloc","pointer",["size_t"]),fr=bind("il2cpp_free","void",["pointer"]);
      var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32(); var gi=null;
      for(var a=0;a<na;a++){var i=aGI(asms.add(a*8).readPointer()); if(iGN(i).readCString()==="holo-game.dll"){gi=i;break;}}
      var cls=cFN(gi,Memory.allocUtf8String("Niantic.Holoholo.Internal"),Memory.allocUtf8String("PokemonBagImpl"));
      var ga=cMN(cls,Memory.allocUtf8String("get_AllPokemon"),0);
      var hits=[]; var onO=new NativeCallback(function(arr,c,u){for(var i=0;i<c;i++)hits.push(arr.add(i*8).readPointer().toString());},"void",["pointer","int","pointer"]);
      var re=new NativeCallback(function(h,s,u){if(!h.isNull()&&s.compare(0)===0){fr(h);return ptr(0);}return al(s);},"pointer",["pointer","size_t","pointer"]);
      var st=lvA(cls,0,onO,ptr(0),re); lvC(st); lvF(st); lvFr(st);
      var best=null,bn=0;
      for(var i=0;i<hits.length;i++){try{var ex=Memory.alloc(8);ex.writePointer(ptr(0));var v=rI(ga,ptr(hits[i]),ptr(0),ex);if(ex.readPointer().isNull()){var lhm=v.add(0x10).readPointer();var list=lhm.add(0x18).readPointer();var n=list.add(0x18).readS32();if(n>bn){bn=n;best=hits[i];}}}catch(e){}}
      return {bag:best,n:bn};
    }};
    """
    bsc = sess.create_script(bjs); bsc.load()
    br = bsc.exports_sync.bag()
    BAG = br['bag']
    print(f"bag via liveness: {BAG} (count={br['n']})")
    bsc.unload()
print(f"bag={BAG}")

def uid_to_str(u):
    u = int(u); return str(u if u >= 0 else u + 2**64)

c = sqlite3.connect('pokemon.db').cursor()

# === 1. Legacy tag ===
legacy = json.load(open('legacy_accurate.json'))
legacy_uids = [it['uid_hex'] for it in legacy] if legacy and isinstance(legacy[0], dict) else legacy
print(f"\nLegacy pokemon to tag: {len(legacy_uids)}")

# Resolve protos for legacy + pulls
regional_pull = json.load(open('regional_pull_uids.json'))
all_needed = set(legacy_uids) | set(regional_pull)
uid_map = {}
for uh in all_needed:
    row = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    if row: uid_map[uid_to_str(row[0])] = uh

walk_js = """
rpc.exports = { findProtos: function(bag, uids) {
  var il2cpp=Process.findModuleByName("libil2cpp.so");
  var exp={}; il2cpp.enumerateExports().forEach(function(e){ if(e.name.indexOf("il2cpp_")===0) exp[e.name]=e.address; });
  function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
  var dG=bind("il2cpp_domain_get","pointer",[]),dGA=bind("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]);
  var aGI=bind("il2cpp_assembly_get_image","pointer",["pointer"]),iGN=bind("il2cpp_image_get_name","pointer",["pointer"]);
  var cFN=bind("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN=bind("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]);
  var rI=bind("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]);
  var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32(); var gi=null;
  for(var a=0;a<na;a++){var i=aGI(asms.add(a*8).readPointer()); if(iGN(i).readCString()==="holo-game.dll"){gi=i;break;}}
  var cls=cFN(gi,Memory.allocUtf8String("Niantic.Holoholo.Internal"),Memory.allocUtf8String("PokemonBagImpl"));
  var ga=cMN(cls,Memory.allocUtf8String("get_AllPokemon"),0);
  var ex=Memory.alloc(8); ex.writePointer(ptr(0)); var v=rI(ga,ptr(bag),ptr(0),ex);
  var lhm=v.add(0x10).readPointer(),list=lhm.add(0x18).readPointer(),head=list.add(0x10).readPointer(),cnt=list.add(0x18).readS32();
  var w={}; for(var i=0;i<uids.length;i++)w[uids[i]]=true; var f={}; var node=head,it=0;
  while(node&&!node.isNull()&&it<cnt+200){try{var k=node.add(0x28).readU64().toString(); if(w[k])f[k]=node.add(0x30).readPointer().toString(); var nx=node.add(0x18).readPointer(); if(nx.isNull()||nx.equals(head))break; node=nx;}catch(e){break;} it++;}
  return {found:f};
}};
"""
wk = sess.create_script(walk_js); wk.load()
res = wk.exports_sync.find_protos(BAG, list(uid_map.keys()))
found = res['found']
print(f"Resolved {len(found)}/{len(uid_map)} protos")

# Create Legacy tag only if missing (idempotent)
ftid_leg = bulk.exports_sync.find_tag_id_by_name(SVC, 'Legacy')
if not ftid_leg.get('ok'):
    addr = bulk.exports_sync.add_tag_on_instance(SVC, 'Legacy', 5)
    print(f"add Legacy tag: {addr}")
    time.sleep(1.5)
    ftid_leg = bulk.exports_sync.find_tag_id_by_name(SVC, 'Legacy')
print(f"Legacy tag: idx={ftid_leg.get('idx')}")

legacy_protos = [found[uid_to_str(c.execute('SELECT uid FROM pokemon WHERE uid_hex=?',(uh,)).fetchone()[0])]
                 for uh in legacy_uids
                 if uid_to_str(c.execute('SELECT uid FROM pokemon WHERE uid_hex=?',(uh,)).fetchone()[0]) in found]
print(f"Legacy protos to tag: {len(legacy_protos)}")
if ftid_leg.get('ok') and legacy_protos:
    bulk.exports_sync.bulk_tag_many(SVC, ftid_leg['tagProtoAddr'], legacy_protos[:1])  # warm-up
    time.sleep(0.8)
    built=0
    for i in range(0, len(legacy_protos), 30):
        ch = legacy_protos[i:i+30]
        rr = bulk.exports_sync.bulk_tag_many(SVC, ftid_leg['tagProtoAddr'], ch)
        built += rr.get('built',0); time.sleep(0.3)
    print(f"Legacy tagged: {built}")
    time.sleep(2)
    chk = bulk.exports_sync.get_pokemon_for_tag(SVC, ftid_leg['idx'])
    print(f"Server Legacy count: {chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')}")

# === 2. Pull legacy + regional from REVIEW ===
ftid_rev = bulk.exports_sync.find_tag_id_by_name(SVC, 'REVIEW')
print(f"\nREVIEW tag: idx={ftid_rev.get('idx')}")
pull_uids = set(legacy_uids) | set(regional_pull)
# Only pull ones actually in REVIEW
pull_in_review = [uh for uh in pull_uids if (lambda x: x and 'REVIEW' in (x[0] or ''))(c.execute('SELECT auth_tag_names FROM pokemon WHERE uid_hex=?',(uh,)).fetchone())]
print(f"To pull from REVIEW: {len(pull_in_review)}")
pulled=0
if ftid_rev.get('ok'):
    for uh in pull_in_review:
        us = uid_to_str(c.execute('SELECT uid FROM pokemon WHERE uid_hex=?',(uh,)).fetchone()[0])
        if us not in found: continue
        try:
            rr = bulk.exports_sync.bulk_untag_one(SVC, found[us], ftid_rev['tagProtoAddr'])
            if rr.get('ok'): pulled+=1
        except: pass
        time.sleep(0.25)
    print(f"Pulled from REVIEW: {pulled}")
    time.sleep(2)
    chk = bulk.exports_sync.get_pokemon_for_tag(SVC, ftid_rev['idx'])
    print(f"Server REVIEW count now: {chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')}")
sess.detach()
