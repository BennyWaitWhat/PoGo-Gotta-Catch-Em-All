"""RECON (READ-ONLY): the decisive capture. On a spin, reads the tapped fort's ID
+ the hidden request flags (IsFromSoftSfida / IsFromWearableDevice), and checks
whether that fort ID actually exists in the server's current GMO fort set (and at
what distance). Resolves: phantom/stale fort vs valid-fort-rejected. Pure read."""
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
function readStr(p){ try{ if(!p||p.isNull())return null; var len=p.add(0x10).readS32(); if(len<0||len>300)return null; return p.add(0x14).readUtf16String(len); }catch(e){ return null; } }
function rep(self, off){ try{ var rf=self.add(off).readPointer(); if(rf.isNull())return null; var cnt=rf.add(0x18).readS32(); var arr=rf.add(0x10).readPointer(); if(cnt<0||cnt>100000||arr.isNull())return null; return {cnt:cnt, arr:arr}; }catch(e){ return null; } }
function elem(r, i){ return r.arr.add(0x20 + i*8).readPointer(); }
function hookM(cls, fn){ var h=H_(); var k=findClass(cls); if(!k){ L("[no] "+cls); return; } var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; while((m=h.cGM(k,it))&&!m.isNull()){ try{ if(h.mGN(m).readCString()!==fn[0])continue; var code=m.readPointer(); if(!code||code.isNull())continue; Interceptor.attach(code,{ onEnter:function(a){ this.s=a[0]; }, onLeave:function(){ try{ if(this.s&&!this.s.isNull()) fn[1](this.s); }catch(e){} } }); }catch(e){} } }

var LOG=[]; function L(s){ LOG.push(s); }
rpc.exports.drain=function(){ var o=LOG; LOG=[]; return o; };
var GMO={};    // fortId -> {lat,lng,en,cl,type}
var GMON=0;

rpc.exports.install=function(){ var h=H_();
 // collect server forts (id + data) from GMO cells
 hookM("GetMapObjectsOutProto",["MergeFrom", function(self){ var cells=rep(self,0x10); if(!cells||cells.cnt===0)return;
   var c0=elem(cells,0); if(!c0||c0.isNull())return; var cf=fieldsOf(c0); var fortOff=null;
   for(var i=0;i<cf.length;i++){ var r=rep(c0,cf[i].o); if(r&&r.cnt>0){ var e0=elem(r,0); var ec=""; try{ec=h.CGN(h.OGC(e0)).readCString();}catch(e){} if(ec.indexOf("Fort")>=0){ fortOff=cf[i].o; break; } } }
   if(fortOff===null)return; var fresh={}; var n=0;
   for(var ci=0;ci<cells.cnt;ci++){ var cell=elem(cells,ci); if(!cell||cell.isNull())continue; var fr=rep(cell,fortOff); if(!fr||fr.cnt===0)continue;
     for(var fi=0;fi<fr.cnt;fi++){ var ft=elem(fr,fi); if(!ft||ft.isNull())continue; var id=readStr(ft.add(0x10).readPointer()); if(!id)continue;
       fresh[id]={lat:ft.add(0x20).readDouble(), lng:ft.add(0x28).readDouble(), en:ft.add(0x3c).readU8(), cl:ft.add(0x88).readU8(), type:ft.add(0x40).readS32()}; n++; } }
   if(n>0){ GMO=fresh; GMON=n; }
 }]);
 // capture the spin request: tapped fort id + hidden flags + positions
 hookM("FortSearchProto",["WriteTo", function(self){ try{
   var id=readStr(self.add(0x10).readPointer());
   var plat=self.add(0x18).readDouble(), plng=self.add(0x20).readDouble(), flat=self.add(0x28).readDouble(), flng=self.add(0x30).readDouble();
   var elig=self.add(0x40).readU8(), wear=self.add(0x41).readU8(), sfida=self.add(0x42).readU8();
   var inGmo = (id && GMO[id]) ? "YES" : "NO";
   var gd = (id && GMO[id]) ? (" gmoLat="+GMO[id].lat.toFixed(6)+" gmoLng="+GMO[id].lng.toFixed(6)+" en="+GMO[id].en+" cl="+GMO[id].cl) : "";
   L("SPIN_REQ id="+id+" | inServerGMO="+inGmo+" (gmoForts="+GMON+")"+gd+" | player="+plat.toFixed(6)+","+plng.toFixed(6)+" fort="+flat.toFixed(6)+","+flng.toFixed(6)+" | IsFromSoftSfida="+sfida+" IsFromWearable="+wear+" eligibleGeoQuest="+elig);
 }catch(e){ L("reqerr "+e); } }]);
 // result
 hookM("FortSearchOutProto",["MergeFrom", function(self){ try{ L("SPIN_RESULT="+self.add(0x10).readS32()); }catch(e){} }]);
 return "installed gmoForts="+GMON; };
function fieldsOf(o){ var h=H_(); var k=h.OGC(o); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f; while((f=h.cGF(k,it))&&!f.isNull()){ try{ out.push({n:h.fGN(f).readCString(), o:h.fGO(f)}); }catch(e){} } return out; }
"""

RESULT = {0: "NO_RESULT_SET", 1: "SUCCESS", 2: "OUT_OF_RANGE", 3: "IN_COOLDOWN_PERIOD",
          4: "INVENTORY_FULL", 5: "EXCEEDED_DAILY_LIMIT", 6: "POI_INACCESSIBLE"}


def main():
    t0 = time.time()
    while time.time() - t0 < 600:
        sc = None; sess = None
        try:
            sess, pid = pg.get_session()
            sc = sess.create_script(JS); sc.load()
            print(f"[{datetime.datetime.now():%H:%M:%S}] attached {pid}:", sc.exports_sync.install(), flush=True)
            print(">>> SPIN THE FAILING STOP ONCE. Watching. <<<", flush=True)
            while time.time() - t0 < 600:
                time.sleep(2)
                for line in (sc.exports_sync.drain() or []):
                    if line.startswith("SPIN_RESULT="):
                        v = int(line.split("=")[1]); print(f"  >>> RESULT: {RESULT.get(v, v)}", flush=True)
                    else:
                        print("  ", line, flush=True)
        except Exception as e:
            try:
                sc.unload(); sess.detach()
            except Exception:
                pass
            print(f"  [{datetime.datetime.now():%H:%M:%S}] reconnect ({str(e)[:50]})", flush=True)
            time.sleep(5); continue


main()
