"""RECON (READ-ONLY): verify the 'rolling spin rate-limit' explanation against the game internals.
Tests whether OUT_OF_RANGE is a disguised rate-limit or a genuine geometry/position rejection.
  (A) static: list EVERY field of FortSearchOutProto -> does any limit/quota/cooldown field exist,
      or is rate-limiting only expressible through Result=EXCEEDED_DAILY_LIMIT(5) ?
  (B) static: search ALL IL2CPP classes for RateLimit/Quota/Throttle/Limit -> is there a
      CLIENT-SIDE spin cap counter the game holds (which would prove a known, readable limit) ?
  (C) live: on the next spin, dump every NON-ZERO field of FortSearchOutProto -> a bare
      OUT_OF_RANGE (only result set, xp=0, cooldown=0) vs a daily-limit/cooldown/quota field set.
  (D) passive: PlayerStats.poke_stop_visits (lifetime stops spun) on inventory updates.
Pure read. No writes, no GPS injection."""
import sys, os, time, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so"); var e={};
 il.enumerateExports().forEach(function(x){ if(x.name.indexOf("il2cpp_")===0) e[x.name]=x.address; });
 function b(n,r,a){ return e[n]? new NativeFunction(e[n],r,a): null; }
 H={ dG:b("il2cpp_domain_get","pointer",[]), dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
     aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]), iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),
     iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]), CGN:b("il2cpp_class_get_name","pointer",["pointer"]),
     cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]), fGN:b("il2cpp_field_get_name","pointer",["pointer"]), fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),
     cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]), mGN:b("il2cpp_method_get_name","pointer",["pointer"]),
     OGC:b("il2cpp_object_get_class","pointer",["pointer"]), tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k); } } }
function findClass(name){ var h=H_(); var f=null; eachClass(function(k){ if(f)return; try{ if(h.CGN(k).readCString()===name) f=k; }catch(e){} }); return f; }
function fieldsList(k){ var h=H_(); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=h.cGF(k,it))&&!f.isNull()){ try{ out.push({n:h.fGN(f).readCString(), o:h.fGO(f)}); }catch(e){} } return out; }
function hookM(cls, fn){ var h=H_(); var k=findClass(cls); if(!k){ L("[no class] "+cls); return; } var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; while((m=h.cGM(k,it))&&!m.isNull()){ try{ if(h.mGN(m).readCString()!==fn[0])continue; var code=m.readPointer(); if(!code||code.isNull())continue; Interceptor.attach(code,{ onEnter:function(a){ this.s=a[0]; }, onLeave:function(){ try{ if(this.s&&!this.s.isNull()) fn[1](this.s); }catch(e){} } }); }catch(e){} } }

var LOG=[]; function L(s){ LOG.push(s); }
rpc.exports.drain=function(){ var o=LOG; LOG=[]; return o; };

// (A) static field list of a class
rpc.exports.fields=function(clsName){ var k=findClass(clsName); if(!k) return ["[no class] "+clsName];
  return fieldsList(k).map(function(x){ return x.n+" @0x"+x.o.toString(16); }); };

// (B) search classes by name substring -> "ClassName :: field,field,..."
rpc.exports.search=function(needle){ var h=H_(); var res=[]; var low=needle.toLowerCase();
  eachClass(function(k){ try{ var nm=h.CGN(k).readCString(); if(nm && nm.toLowerCase().indexOf(low)>=0){
    var fs=fieldsList(k).map(function(x){return x.n;});
    res.push(nm+"  ::  "+fs.join(", "));
  } }catch(e){} }); return res; };

var RES={0:"NO_RESULT",1:"SUCCESS",2:"OUT_OF_RANGE",3:"IN_COOLDOWN_PERIOD",4:"INVENTORY_FULL",5:"EXCEEDED_DAILY_LIMIT",6:"POI_INACCESSIBLE"};

rpc.exports.install=function(){ var h=H_();
 // (C) full response dump on spin: show result + every NON-ZERO field
 hookM("FortSearchOutProto",["MergeFrom", function(self){ try{
   var k=h.OGC(self); var nz=[];
   fieldsList(k).forEach(function(fld){ try{ var i32=self.add(fld.o).readS32(); var i64=self.add(fld.o).readS64();
     if(i32!==0 || i64.toString()!=="0"){ nz.push(fld.n+"@0x"+fld.o.toString(16)+"="+(i32!==0?i32:("ptr/L"+i64.toString()))); } }catch(e){} });
   var r=self.add(0x10).readS32();
   L("SPIN_OUT result="+r+"("+(RES[r]||"?")+")  |  NONZERO=["+nz.join("  ")+"]");
 }catch(e){ L("outerr "+e); } }]);
 // request distance
 hookM("FortSearchProto",["WriteTo", function(self){ try{
   var plat=self.add(0x18).readDouble(), plng=self.add(0x20).readDouble(), flat=self.add(0x28).readDouble(), flng=self.add(0x30).readDouble();
   var dlat=(plat-flat)*111000.0, dlng=(plng-flng)*111000.0*Math.cos(plat*Math.PI/180);
   L("SPIN_REQ player="+plat.toFixed(6)+","+plng.toFixed(6)+" fort="+flat.toFixed(6)+","+flng.toFixed(6)+" dist="+Math.sqrt(dlat*dlat+dlng*dlng).toFixed(1)+"m  (interaction radius ~80m)");
 }catch(e){} }]);
 // (D) PlayerStats -> spin/visit counts
 hookM("PlayerStats",["MergeFrom", function(self){ try{
   var k=h.OGC(self); var out=[];
   fieldsList(k).forEach(function(fld){ try{ if(/visit|stop|capture|km|spin|experience|level/i.test(fld.n)){ var i32=self.add(fld.o).readS32(); var i64=self.add(fld.o).readS64(); out.push(fld.n+"="+(i32!==0?i32:i64.toString())); } }catch(e){} });
   if(out.length) L("PLAYERSTATS "+out.join("  "));
 }catch(e){} }]);
 return "hooks installed (FortSearchOut/FortSearch/PlayerStats)"; };
"""


def main():
    t0 = time.time()
    printed_static = False
    while time.time() - t0 < 600:
        sc = None; sess = None
        try:
            sess, pid = pg.get_session()
            sc = sess.create_script(JS); sc.load()
            print(f"[{datetime.datetime.now():%H:%M:%S}] attached {pid}", flush=True)
            print("  install:", sc.exports_sync.install(), flush=True)
            if not printed_static:
                print("\n=== (A) FortSearchOutProto — EVERY field (is there any limit/quota/cooldown field?) ===", flush=True)
                for f in sc.exports_sync.fields("FortSearchOutProto"):
                    print("    ", f, flush=True)
                print("\n=== (B) CLIENT-SIDE classes matching RateLimit / Quota / Throttle / *Limit(fort|spin|stop|search|api|action) ===", flush=True)
                for needle in ("RateLimit", "Quota", "Throttle"):
                    for line in (sc.exports_sync.search(needle) or [])[:40]:
                        print(f"    [{needle}]", line, flush=True)
                for line in (sc.exports_sync.search("Limit") or []):
                    nm = line.split("  ::")[0].lower()
                    if any(t in nm for t in ("fort", "spin", "stop", "search", "api", "action", "map", "gym")):
                        print("    [Limit*]", line, flush=True)
                printed_static = True
            print("\n=== (C)/(D) WATCHING — please SPIN ONE FAILING STOP ONCE (catches keep PlayerStats fresh) ===", flush=True)
            while time.time() - t0 < 600:
                time.sleep(2)
                for line in (sc.exports_sync.drain() or []):
                    print("  ", line, flush=True)
        except Exception as e:
            try:
                sc.unload(); sess.detach()
            except Exception:
                pass
            print(f"  [{datetime.datetime.now():%H:%M:%S}] reconnect ({str(e)[:60]})", flush=True)
            time.sleep(5); continue


main()
