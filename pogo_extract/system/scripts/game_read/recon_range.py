"""Measure whether the catcher's visible targets are actually in catch range: read the player's GPS
position + every visible WildMapPokemon's lat/lng, compute distances. READ-ONLY."""
import sys, os, math
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj){var h=H_();var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,ptr(0),exc);if(!exc.readPointer().isNull())return null;return r;}
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.latLngGetters=function(){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<50;i++){var k=h.iGC(im,i);if(k.isNull())continue;var cn;try{cn=h.CGN(k).readCString();}catch(e){continue;}var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGPC(m)!==0)continue;var rt=h.tGN(h.mGRT(m)).readCString();if(rt==="Niantic.LatLng"){var nm=h.mGN(m).readCString();if(/Player|Avatar|Map|Position|Location|Device|Gps|Current/i.test(cn+"."+nm))out.push(cn+"."+nm);}}catch(e){}}}return out;};
rpc.exports.readLl=function(inst,name){var h=H_();var m=mOf(h.OGC(ptr(inst)),name,0);if(!m)return null;var r=inv(m,ptr(inst));if(!r)return null;try{return {lat:r.add(0x10).readDouble(), lng:r.add(0x18).readDouble()};}catch(e){return null;}};
rpc.exports.wmpLoc=function(inst){var h=H_();var out={};function g(n){var m=mOf(h.OGC(ptr(inst)),n,0);return m?inv(m,ptr(inst)):null;}
 try{var r=g("get_PokemonId");out.dex=r?r.add(0x10).readS32():null;}catch(e){}
 try{var r=g("get_Cp");out.cp=r?r.add(0x10).readS32():null;}catch(e){}
 try{var r=g("get_VisibleOnMap");out.vis=r?!!r.add(0x10).readU8():null;}catch(e){}
 try{var r=g("get_Location");if(r){out.lat=r.add(0x10).readDouble();out.lng=r.add(0x18).readDouble();}}catch(e){}
 return out;};
"""


def hav(a, b):
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0]); dl = math.radians(b[1] - a[1])
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(min(1, math.sqrt(x)))


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, JS)
        try:
            # spawns
            spawns = []
            rw = finder.exports_sync.find_singleton("Niantic.Holoholo.Map", "WildMapPokemon")
            for h in (rw.get("hits", []) if isinstance(rw, dict) else []):
                if sc.exports_sync.cls_name(h) != "WildMapPokemon":
                    continue
                i = sc.exports_sync.wmp_loc(h)
                if i.get("lat") and i.get("vis"):
                    spawns.append(i)
            # player-position candidates
            cands = sc.exports_sync.lat_lng_getters()
            print("LatLng getter candidates:", cands)
            player = None
            for c in cands:
                cls, meth = c.split(".", 1)
                ns = sc.exports_sync.ns_of(cls)
                if not ns:
                    continue
                r = finder.exports_sync.find_singleton(ns, cls)
                for h in (r.get("hits", []) if isinstance(r, dict) else []):
                    if sc.exports_sync.cls_name(h) != cls:
                        continue
                    ll = sc.exports_sync.read_ll(h, meth)
                    if ll and ll.get("lat") and -90 < ll["lat"] < 90 and -180 < ll["lng"] < 180 and ll["lat"] != 0:
                        # plausible: spawns should be within a few km
                        if spawns:
                            d = min(hav((ll["lat"], ll["lng"]), (s["lat"], s["lng"])) for s in spawns)
                            if d < 5000:
                                print(f"PLAYER via {c} = {ll['lat']:.5f},{ll['lng']:.5f} (nearest spawn {d:.0f}m)")
                                if player is None:
                                    player = ll
            if not player:
                print("could not pin player position from candidates")
            print(f"\n{len(spawns)} visible spawns:")
            for s in sorted(spawns, key=lambda s: hav((player["lat"], player["lng"]), (s["lat"], s["lng"])) if player else 0):
                dist = hav((player["lat"], player["lng"]), (s["lat"], s["lng"])) if player else None
                print(f"  dex={s.get('dex')} cp={s.get('cp')} dist={f'{dist:.0f}m' if dist is not None else '?'}")
        finally:
            try: sc.unload(); finder.unload()
            except Exception: pass
    finally:
        try: sess.detach()
        except Exception: pass


main()
