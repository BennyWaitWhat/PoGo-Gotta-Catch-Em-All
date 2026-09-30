"""RECON (READ-ONLY): drill into GMO map cells and read every fort the server
serves -- position + Enabled/Closed/Visited/Type/Cooldown -- to see whether
spinnable stops actually exist at your spot. Pure read."""
import sys, os, time, math
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

# your last-known player position (from the spin recon)
PLAT, PLNG = 41.89181, -87.59935

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
function fieldsOf(k){ var h=H_(); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f; while((f=h.cGF(k,it))&&!f.isNull()){ try{ out.push({n:h.fGN(f).readCString(), o:h.fGO(f)}); }catch(e){} } return out; }
function rep(self, off){ try{ var rf=self.add(off).readPointer(); if(rf.isNull())return null; var cnt=rf.add(0x18).readS32(); var arr=rf.add(0x10).readPointer(); if(cnt<0||cnt>100000||arr.isNull())return null; return {cnt:cnt, arr:arr}; }catch(e){ return null; } }
function elem(r, i){ return r.arr.add(0x20 + i*8).readPointer(); }

var LOG=[]; function L(s){ LOG.push(s); }
rpc.exports.drain=function(){ var o=LOG; LOG=[]; return o; };

rpc.exports.install=function(){ var h=H_(); var gk=findClass("GetMapObjectsOutProto"); if(!gk) return "no GMO";
 var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; var hk=0;
 while((m=h.cGM(gk,it))&&!m.isNull()){ try{ if(h.mGN(m).readCString()!=="MergeFrom")continue; var code=m.readPointer(); if(!code||code.isNull())continue;
   Interceptor.attach(code,{ onEnter:function(a){ this.s=a[0]; }, onLeave:function(){ try{ var self=this.s; if(!self||self.isNull())return;
     var cells=rep(self,0x10); if(!cells||cells.cnt===0)return;
     // identify the fort field in a cell by element class containing "Fort"
     var c0=elem(cells,0); if(!c0||c0.isNull())return; var cellCls=h.OGC(c0); var cf=fieldsOf(cellCls);
     var fortOff=null, fortElem=null, summary=[];
     for(var i=0;i<cf.length;i++){ var r=rep(c0,cf[i].o); if(r&&r.cnt>0){ var e0=elem(r,0); var ec=""; try{ ec=h.CGN(h.OGC(e0)).readCString(); }catch(e){} summary.push(cf[i].n+"="+r.cnt+"("+ec+")"); if(ec.indexOf("Fort")>=0 && fortOff===null){ fortOff=cf[i].o; fortElem=ec; } } }
     L("cell["+cellCls?"":""+"] sample fields: "+summary.join(", "));
     if(fortOff===null){ L("NO FORT FIELD FOUND in cells"); return; }
     // sum forts across all cells + read each fort
     var total=0, en=0, cl=0, lines=[];
     for(var ci=0; ci<cells.cnt; ci++){ var cell=elem(cells,ci); if(!cell||cell.isNull())continue; var fr=rep(cell,fortOff); if(!fr||fr.cnt===0)continue;
       for(var fi=0; fi<fr.cnt; fi++){ var ft=elem(fr,fi); if(!ft||ft.isNull())continue; total++;
         try{ var lat=ft.add(0x20).readDouble(), lng=ft.add(0x28).readDouble(); var enabled=ft.add(0x3c).readU8(); var closed=ft.add(0x88).readU8(); var ftype=ft.add(0x40).readS32(); var visited=ft.add(0xa0).readU8(); var cd=ft.add(0x68).readS64().toString();
           if(enabled)en++; if(closed)cl++;
           if(lines.length<25) lines.push(lat.toFixed(6)+","+lng.toFixed(6)+" en="+enabled+" cl="+closed+" type="+ftype+" vis="+visited+" cdMs="+cd);
         }catch(e){}
       } }
     L("FORTS served by server: total="+total+" enabled="+en+" closed="+cl+" (elem="+fortElem+")");
     for(var li=0; li<lines.length; li++) L("  fort: "+lines[li]);
   }catch(e){ L("err "+e); } } }); hk++; }catch(e){} }
 return "hooked "+hk; };
"""


def hav(a1, o1, a2, o2):
    R = 6371000
    p1 = math.radians(a1); p2 = math.radians(a2)
    dp = math.radians(a2-a1); dl = math.radians(o2-o1)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(min(1, math.sqrt(x)))


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = sess.create_script(JS)
    sc.load()
    print("install:", sc.exports_sync.install(), flush=True)
    print(f">>> watching 50s for a cell-bearing GMO (player ref {PLAT},{PLNG}) <<<", flush=True)
    t0 = time.time()
    got = False
    while time.time() - t0 < 50:
        time.sleep(3)
        for line in (sc.exports_sync.drain() or []):
            if line.startswith("  fort: "):
                try:
                    body = line.split("fort: ")[1]
                    coord = body.split(" ")[0]
                    la, lo = float(coord.split(",")[0]), float(coord.split(",")[1])
                    d = hav(PLAT, PLNG, la, lo)
                    print(f"  fort @ {d:6.0f} m  | {body}", flush=True)
                except Exception:
                    print("  ", line, flush=True)
            else:
                print("  ", line, flush=True)
                if "FORTS served" in line:
                    got = True
        if got and time.time() - t0 > 20:
            break
    try:
        sc.unload(); sess.detach()
    except Exception:
        pass


main()
