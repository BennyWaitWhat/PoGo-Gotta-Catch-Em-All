"""RECON (READ-ONLY): resolve the gmoForts=0 ambiguity that decides the vGP question.
The spincapture script only updates the fort count when n>0, so an EMPTY GMO and a
MISSING GMO both read as 0. Here the GMO hook logs EVERY fire: cell count, total forts,
enabled forts, and the nearest served fort's distance from the avatar. That distinguishes:
  - server serves forts (forts>0)  -> vGP has stuff to spin; its silence is a vGP-layer bug
  - server serves 0 forts (forts=0) -> nothing interactable; vGP silence + manual OUT_OF_RANGE
    are the SAME position-desync root cause
Still captures spins (manual vs SoftSfida/Wearable) + result. Pure read. No writes."""
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
function fieldsOf(o){ var h=H_(); var k=h.OGC(o); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f; while((f=h.cGF(k,it))&&!f.isNull()){ try{ out.push({n:h.fGN(f).readCString(), o:h.fGO(f)}); }catch(e){} } return out; }
function hookM(cls, fn){ var h=H_(); var k=findClass(cls); if(!k){ L("[no] "+cls); return; } var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; while((m=h.cGM(k,it))&&!m.isNull()){ try{ if(h.mGN(m).readCString()!==fn[0])continue; var code=m.readPointer(); if(!code||code.isNull())continue; Interceptor.attach(code,{ onEnter:function(a){ this.s=a[0]; }, onLeave:function(){ try{ if(this.s&&!this.s.isNull()) fn[1](this.s); }catch(e){} } }); }catch(e){} } }

var LOG=[]; function L(s){ LOG.push(s); }
rpc.exports.drain=function(){ var o=LOG; LOG=[]; return o; };
var GMO={}; var GMON=0; var LASTP=null; var LASTGMO="";

rpc.exports.install=function(){ var h=H_();
 // GMO: log EVERY fire (cells, forts, enabled, nearest-fort distance from avatar)
 hookM("GetMapObjectsOutProto",["MergeFrom", function(self){
   var cells=rep(self,0x10);
   if(!cells){ if(LASTGMO!=="nocells"){LASTGMO="nocells"; L("GMO <no cells field>");} return; }
   if(cells.cnt===0){ if(LASTGMO!=="c0"){LASTGMO="c0"; L("GMO cells=0 forts=0 enabled=0");} return; }
   var fortOff=null;
   for(var ci=0; ci<cells.cnt && fortOff===null; ci++){ var cell=elem(cells,ci); if(!cell||cell.isNull())continue;
     var cf=fieldsOf(cell);
     for(var i=0;i<cf.length;i++){ var r=rep(cell,cf[i].o); if(r&&r.cnt>0){ var e0=elem(r,0); var ec=""; try{ec=h.CGN(h.OGC(e0)).readCString();}catch(e){} if(ec.indexOf("Fort")>=0){ fortOff=cf[i].o; break; } } }
   }
   var n=0, en=0, fresh={}, sLat=0, sLng=0;
   if(fortOff!==null){
     for(var cj=0;cj<cells.cnt;cj++){ var cell2=elem(cells,cj); if(!cell2||cell2.isNull())continue; var fr=rep(cell2,fortOff); if(!fr||fr.cnt===0)continue;
       for(var fi=0;fi<fr.cnt;fi++){ var ft=elem(fr,fi); if(!ft||ft.isNull())continue; var id=readStr(ft.add(0x10).readPointer()); if(!id)continue;
         var enb=ft.add(0x3c).readU8(); var la=ft.add(0x20).readDouble(), lo=ft.add(0x28).readDouble();
         fresh[id]={lat:la,lng:lo,en:enb,cl:ft.add(0x88).readU8(),type:ft.add(0x40).readS32()}; if(n===0){sLat=la;sLng=lo;} n++; if(enb)en++; } }
   }
   if(n>0){ GMO=fresh; GMON=n; }
   var ds=""; if(n>0 && LASTP){ var dlat=(sLat-LASTP.lat)*111000.0, dlng=(sLng-LASTP.lng)*111000.0*Math.cos(sLat*Math.PI/180); ds=" nearFort="+sLat.toFixed(5)+","+sLng.toFixed(5)+" distFromAvatar="+Math.sqrt(dlat*dlat+dlng*dlng).toFixed(0)+"m"; }
   var summary="forts="+n+" enabled="+en; var key=summary+(LASTP?"|P":"");
   if(key!==LASTGMO){ LASTGMO=key; L("GMO cells="+cells.cnt+" "+summary+ds); }
 }]);
 // spin request: tapped fort id + hidden flags + positions
 hookM("FortSearchProto",["WriteTo", function(self){ try{
   var id=readStr(self.add(0x10).readPointer());
   var plat=self.add(0x18).readDouble(), plng=self.add(0x20).readDouble(), flat=self.add(0x28).readDouble(), flng=self.add(0x30).readDouble();
   LASTP={lat:plat,lng:plng};
   var elig=self.add(0x40).readU8(), wear=self.add(0x41).readU8(), sfida=self.add(0x42).readU8();
   var inGmo = (id && GMO[id]) ? "YES" : "NO";
   var src = (sfida? "GOPLUS(softSfida)" : (wear? "WEARABLE" : "MANUAL"));
   L("SPIN_REQ ["+src+"] id="+id+" inServerGMO="+inGmo+" (gmoForts="+GMON+") player="+plat.toFixed(6)+","+plng.toFixed(6)+" fort="+flat.toFixed(6)+","+flng.toFixed(6));
 }catch(e){ L("reqerr "+e); } }]);
 hookM("FortSearchOutProto",["MergeFrom", function(self){ try{ L("SPIN_RESULT="+self.add(0x10).readS32()); }catch(e){} }]);
 return "installed (logs every GMO + spin source)"; };
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
            print(">>> Watching GMO fort count + spins (manual vs Go Plus). <<<", flush=True)
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
