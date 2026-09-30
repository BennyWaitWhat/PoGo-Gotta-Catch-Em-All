"""PHASE 2 v2: observe the WAINA device's ACTUAL ball usage. READ-ONLY.
Reads live ItemBag counts for Poke(1)/Great(2)/Ultra(3) before and after a catch window, and counts
catches via xek. Tells us which ball each catch actually consumed -> whether Ultra is button-tied.
User: do a batch of catches, INCLUDING deliberate button-presses, during the window."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

HOLD = 75

MY_JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
var catches=0;
rpc.exports.classNs=function(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.hookXek=function(){var h=H_();var PAM=h.cFN(img("holo-game.dll"),Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpActivityMonitor"));var m=PAM&&!PAM.isNull()?h.cMN(PAM,Memory.allocUtf8String("xek"),1):null;if(m&&!m.isNull()){var ad=m.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){catches++;}});return true;}}return false;};
rpc.exports.catches=function(){return catches;};
rpc.exports.count=function(ibStr,item){var h=H_();var ib=ptr(ibStr);var cls=h.OGC(ib);var m=h.cMN(cls,Memory.allocUtf8String("GetItemCount"),1);if(!m||m.isNull())return -1;var arg=Memory.alloc(4);arg.writeS32(item);var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,ib,args,exc);if(!exc.readPointer().isNull())return -2;if(ret.isNull())return -3;try{return ret.add(0x10).readS32();}catch(e){return -4;}};
"""

ITEMS = {1: "Poke", 2: "Great", 3: "Ultra"}


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, MY_JS)
        try:
            ns = sc.exports_sync.class_ns("holo-game.dll", "ItemBag") or "Niantic.Holoholo.Internal"
            r = finder.exports_sync.find_singleton(ns, "ItemBag")
            hits = r.get("hits", []) if isinstance(r, dict) else []
            ib = None
            for h in hits:
                if sc.exports_sync.count(h, 1) >= 0:
                    ib = h; break
            print(f"ItemBag ns={ns}, instance={ib}")
            if ib is None:
                print("could not read ItemBag counts (no good instance)"); return
            sc.exports_sync.hook_xek()
            before = {i: sc.exports_sync.count(ib, i) for i in ITEMS}
            print("balls BEFORE:", {ITEMS[i]: before[i] for i in ITEMS})
            print(f"\n*** Catch a batch for {HOLD}s — include deliberate BUTTON-PRESSES. ***")
            time.sleep(HOLD)
            after = {i: sc.exports_sync.count(ib, i) for i in ITEMS}
            cat = sc.exports_sync.catches()
            sess.detach()
            print("balls AFTER: ", {ITEMS[i]: after[i] for i in ITEMS})
            print(f"\ncatches (xek): {cat}")
            print("consumed:", {ITEMS[i]: before[i] - after[i] for i in ITEMS if before[i] >= 0 and after[i] >= 0})
            du = before[3] - after[3]; dp = before[1] - after[1]
            if du > 0 and dp == 0:
                print(">>> ULTRA used, Poke steady — WAINA throws Ultra. The earlier Poke must have been a non-button/auto catch.")
            elif dp > 0 and du == 0:
                print(">>> POKE used, Ultra steady — even your real WAINA throws Poke. The Ball=Ultra pref ISN'T driving it; something else (the button path?) is.")
            elif du > 0 and dp > 0:
                print(f">>> MIXED: {du} Ultra + {dp} Poke — button-presses vs auto likely explain the split. Tell me how many you button-pressed.")
        finally:
            try: sc.unload(); finder.unload()
            except Exception: pass
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()
