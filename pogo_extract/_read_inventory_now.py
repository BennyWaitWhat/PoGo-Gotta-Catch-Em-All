"""READ-ONLY inventory snapshot alongside the running catcher.
Reuses catch_loop_fast.py's findItemBag()+count() JS verbatim. Adds box count via
PokemonBagImpl.get_PokemonOnlyCount. Retries transient frida errors up to 4x.
Prints a single JSON line."""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402

# JS lifted verbatim from catch_loop_fast.py (findItemBag + count) + a box-count export.
JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
rpc.exports.findItemBag=function(){var h=H_();var imgs=["holo-game.dll","holo-protos.dll"];for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(/^I[A-Z]/.test(nm))continue;var m=h.cMN(k,Memory.allocUtf8String("GetItemCount"),1);if(m&&!m.isNull())return {ns:h.CGNS(k).readCString(),cls:nm};}catch(e){}}}return null;};
rpc.exports.count=function(ibStr,item){var h=H_();var ib=ptr(ibStr);var m=h.cMN(h.OGC(ib),Memory.allocUtf8String("GetItemCount"),1);if(!m||m.isNull())return -1;var arg=Memory.alloc(4);arg.writeS32(item);var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,ib,args,exc);if(!exc.readPointer().isNull())return -2;if(ret.isNull())return -3;try{return ret.add(0x10).readS32();}catch(e){return -4;}};
rpc.exports.nsOf=function(cls){var h=H_();var imgs=["holo-game.dll","holo-protos.dll"];for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.boxCount=function(inst){var h=H_();var m=h.cMN(h.OGC(ptr(inst)),Memory.allocUtf8String("get_PokemonOnlyCount"),0);if(!m||m.isNull())return -1;var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,ptr(inst),ptr(0),exc);if(!exc.readPointer().isNull())return -2;if(ret.isNull())return -3;try{return ret.add(0x10).readS32();}catch(e){return -4;}};
"""

ITEMS = {"pokeBalls":1,"greatBalls":2,"ultraBalls":3,"razz":701,"pinap":705,"goldenRazz":706}


def main():
    out = {"ok": False}
    last_err = None
    for attempt in range(4):
        sess = None
        try:
            sess, pid = pg.get_session()
            finder = pg.get_script_with_helpers(sess)   # liveness API (find_singleton)
            sc = pg.get_script_with_helpers(sess, JS)

            # --- item bag ---
            info = sc.exports_sync.find_item_bag()
            ib = None
            if info:
                r = finder.exports_sync.find_singleton(info["ns"], info["cls"])
                hits = r.get("hits", []) if isinstance(r, dict) else []
                ib = next((h for h in hits if sc.exports_sync.count(h, 1) >= 0), None)
            out["itemBagClass"] = info
            counts = {}
            if ib:
                for k, iid in ITEMS.items():
                    counts[k] = sc.exports_sync.count(ib, iid)
            out["counts"] = counts

            # --- box / PokemonOnlyCount via PokemonBagImpl ---
            box = -1
            box_method = None
            try:
                bag = pg.pick_singleton(sess, "Niantic.Holoholo.Internal", "PokemonBagImpl")
                box = sc.exports_sync.box_count(bag)
                box_method = "PokemonBagImpl.get_PokemonOnlyCount@" + str(bag)
            except Exception as e:
                box_method = "pick_singleton(PokemonBagImpl) failed: " + str(e)[:80]
            out["box"] = box
            out["boxMethod"] = box_method
            out["pid"] = pid
            out["ok"] = True
            print(json.dumps(out))
            sess.detach()
            return
        except Exception as e:
            last_err = str(e)[:160]
            try:
                sess.detach()
            except Exception:
                pass
            time.sleep(3)
    out["error"] = last_err
    print(json.dumps(out))


main()
