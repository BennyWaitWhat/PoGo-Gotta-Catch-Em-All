"""Self-healing tag driver. Survives PoGo PID drift / session death by reconnecting
and resuming from server-confirmed state. Idempotent.

Usage: python robust_tag.py
  - Ensures 'Legacy' tag exists, tags all legacy_accurate.json members
  - Pulls legacy + regional_pull_uids.json members out of REVIEW
Every operation re-verifies against live server state, so re-running is safe.
"""
import frida, json, sqlite3, subprocess, sys, time
sys.stdout.reconfigure(line_buffering=True)

ADB = '100.98.158.56:5555'
DOM = 'holo-game.dll'

def adb(*args):
    return subprocess.run(['adb','-s',ADB,*args], capture_output=True, text=True)

def connect():
    subprocess.run(['adb','connect',ADB], capture_output=True)
    adb('forward','tcp:27047','tcp:27047')
    pid = int(adb('shell','pidof com.nianticlabs.pokemongo').stdout.strip())
    dev = frida.get_device_manager().add_remote_device('127.0.0.1:27047')
    return dev.attach(pid), pid

# JS that finds svc+bag via liveness and does all tag ops in-process (one script, fewer round-trips)
DRIVER_JS = open('bulk_tag.js','r',encoding='utf-8').read()

SCAN_JS = r"""
rpc.exports.scanSvcBag = function() {
  var il2cpp=Process.findModuleByName("libil2cpp.so");
  var exp={}; il2cpp.enumerateExports().forEach(function(e){ if(e.name.indexOf("il2cpp_")===0) exp[e.name]=e.address; });
  function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
  var dG=bind("il2cpp_domain_get","pointer",[]),dGA=bind("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]);
  var aGI=bind("il2cpp_assembly_get_image","pointer",["pointer"]),iGN=bind("il2cpp_image_get_name","pointer",["pointer"]);
  var cFN=bind("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cGM=bind("il2cpp_class_get_methods","pointer",["pointer","pointer"]);
  var mGN=bind("il2cpp_method_get_name","pointer",["pointer"]),cMN=bind("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]);
  var rI=bind("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]);
  var tA=bind("il2cpp_thread_attach","pointer",["pointer"]); tA(dG());
  var lvA=bind("il2cpp_unity_liveness_allocate_struct","pointer",["pointer","int","pointer","pointer","pointer"]);
  var lvC=bind("il2cpp_unity_liveness_calculation_from_statics","void",["pointer"]);
  var lvF=bind("il2cpp_unity_liveness_finalize","void",["pointer"]),lvFr=bind("il2cpp_unity_liveness_free_struct","void",["pointer"]);
  var al=bind("il2cpp_alloc","pointer",["size_t"]),fr=bind("il2cpp_free","void",["pointer"]);
  var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32(); var gi=null;
  for(var a=0;a<na;a++){var i=aGI(asms.add(a*8).readPointer()); if(iGN(i).readCString()==="holo-game.dll"){gi=i;break;}}
  function instances(ns,cn){
    var cls=cFN(gi,Memory.allocUtf8String(ns),Memory.allocUtf8String(cn));
    var hits=[]; var onO=new NativeCallback(function(arr,c,u){for(var i=0;i<c;i++)hits.push(arr.add(i*8).readPointer().toString());},"void",["pointer","int","pointer"]);
    var re=new NativeCallback(function(h,s,u){if(!h.isNull()&&s.compare(0)===0){fr(h);return ptr(0);}return al(s);},"pointer",["pointer","size_t","pointer"]);
    var st=lvA(cls,0,onO,ptr(0),re); lvC(st); lvF(st); lvFr(st); return {cls:cls, hits:hits};
  }
  // svc: pick one with >=13 tags
  var sv=instances("Niantic.Holoholo.Tagging","TaggingRpcService");
  var iter=Memory.alloc(8); iter.writePointer(ptr(0)); var m,gnt=null;
  while((m=cGM(sv.cls,iter))&&!m.isNull()){if(mGN(m).readCString()==="get_NumberOfTags")gnt=m;}
  var svc=null,sn=0;
  for(var i=0;i<sv.hits.length;i++){try{var ex=Memory.alloc(8);ex.writePointer(ptr(0));var rr=rI(gnt,ptr(sv.hits[i]),ptr(0),ex);if(ex.readPointer().isNull()){var n=rr.add(0x10).readS32();if(n>sn){sn=n;svc=sv.hits[i];}}}catch(e){}}
  // bag: pick one whose AllPokemon list count is largest
  var bg=instances("Niantic.Holoholo.Internal","PokemonBagImpl");
  var ga=cMN(bg.cls,Memory.allocUtf8String("get_AllPokemon"),0);
  var bag=null,bn=0;
  for(var i=0;i<bg.hits.length;i++){try{var ex=Memory.alloc(8);ex.writePointer(ptr(0));var v=rI(ga,ptr(bg.hits[i]),ptr(0),ex);if(ex.readPointer().isNull()){var lhm=v.add(0x10).readPointer();var list=lhm.add(0x18).readPointer();var n=list.add(0x18).readS32();if(n>bn){bn=n;bag=bg.hits[i];}}}catch(e){}}
  return {svc:svc, svcTags:sn, bag:bag, bagCount:bn};
};
rpc.exports.findProtos = function(bag, uids) {
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
};
"""

def new_script(sess):
    sc = sess.create_script(DRIVER_JS + "\n" + SCAN_JS)
    sc.load()
    sc.exports_sync.init_status()
    return sc

def uid_to_str(u):
    u = int(u); return str(u if u >= 0 else u + 2**64)

c = sqlite3.connect('pokemon.db').cursor()
legacy = json.load(open('legacy_accurate.json'))
legacy_uids = [it['uid_hex'] for it in legacy]
regional_pull = json.load(open('regional_pull_uids.json'))
uid_hex_to_dec = {}
for uh in set(legacy_uids) | set(regional_pull):
    row = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    if row: uid_hex_to_dec[uh] = uid_to_str(row[0])

def run():
    attempt = 0
    while attempt < 12:
        attempt += 1
        try:
            sess, pid = connect()
            print(f"[attempt {attempt}] attached PID={pid}")
            sc = new_script(sess)
            sb = sc.exports_sync.scan_svc_bag()
            SVC, BAG = sb['svc'], sb['bag']
            print(f"  svc={SVC} ({sb['svcTags']} tags) bag={BAG} ({sb['bagCount']})")
            if not SVC or not BAG: raise RuntimeError("svc/bag not found")

            # ensure Legacy tag
            ft = sc.exports_sync.find_tag_id_by_name(SVC, 'Legacy')
            if not ft.get('ok'):
                sc.exports_sync.add_tag_on_instance(SVC, 'Legacy', 5); time.sleep(1.5)
                ft = sc.exports_sync.find_tag_id_by_name(SVC, 'Legacy')
            print(f"  Legacy idx={ft.get('idx')}")

            # resolve protos for all needed uids
            dec_list = list(uid_hex_to_dec.values())
            fr = sc.exports_sync.find_protos(BAG, dec_list)
            found = fr['found']  # dec -> proto
            print(f"  resolved {len(found)}/{len(dec_list)} protos")

            # which legacy are NOT yet tagged Legacy (server-confirmed via auth_tag_names is stale; just tag all, idempotent)
            leg_protos = [found[uid_hex_to_dec[uh]] for uh in legacy_uids if uid_hex_to_dec.get(uh) in found]
            sc.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], leg_protos[:1]); time.sleep(0.6)  # warm-up
            built = 0
            for i in range(0, len(leg_protos), 30):
                rr = sc.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], leg_protos[i:i+30])
                built += rr.get('built', 0); time.sleep(0.25)
            chk = sc.exports_sync.get_pokemon_for_tag(SVC, ft['idx'])
            leg_count = chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')
            print(f"  Legacy tagged built={built}, server count={leg_count}")

            # pull legacy + regional from REVIEW
            ftr = sc.exports_sync.find_tag_id_by_name(SVC, 'REVIEW')
            pull = set(legacy_uids) | set(regional_pull)
            pulled = 0
            for uh in pull:
                dec = uid_hex_to_dec.get(uh)
                if dec not in found: continue
                try:
                    rr = sc.exports_sync.bulk_untag_one(SVC, found[dec], ftr['tagProtoAddr'])
                    if rr.get('ok'): pulled += 1
                except: pass
            chk2 = sc.exports_sync.get_pokemon_for_tag(SVC, ftr['idx'])
            rev_count = chk2.get('dump',{}).get('+0x18_listish',{}).get('count','?')
            print(f"  pulled from REVIEW attempts done, server REVIEW count={rev_count}")
            print(f"DONE. Legacy={leg_count} REVIEW={rev_count}")
            sess.detach()
            return True
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError, frida.ServerNotRunningError, RuntimeError) as e:
            print(f"  [attempt {attempt}] disconnect: {type(e).__name__}: {e}; reconnecting...")
            time.sleep(4)
    print("FAILED after retries")
    return False

run()
