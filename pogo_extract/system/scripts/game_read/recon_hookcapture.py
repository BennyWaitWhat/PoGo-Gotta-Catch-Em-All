"""RECON (READ-ONLY): can we find the 4 catcher singletons via METHOD HOOKS (capture `this`) instead of the
crash-prone GC liveness walk? Hooks one method on each of MapPlaceDirectoryService / MapAvatar / ItemBag /
IapService and reports which get captured passively during normal map play. This decides the on-device fix."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function findItemBag(){var h=H_();var imgs=["holo-game.dll","holo-protos.dll"];for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(/^I[A-Z]/.test(nm))continue;var m=h.cMN(k,Memory.allocUtf8String("GetItemCount"),1);if(m&&!m.isNull())return k;}catch(e){}}}return null;}
var CAP={};
rpc.exports.caps=function(){return CAP;};
function hook(label,k,meth,argc){var h=H_();if(!k){CAP[label]="NO CLASS";return;}var m=h.cMN(k,Memory.allocUtf8String(meth),argc);if(!m||m.isNull()){CAP[label]="NO METHOD";return;}var code=m.readPointer();if(!code||code.isNull()){CAP[label]="NO CODE";return;}CAP[label]={n:0,ptr:null};Interceptor.attach(code,{onEnter:function(a){try{var c=CAP[label];c.n++;if(!c.ptr)c.ptr=a[0].toString();}catch(e){}}});}
rpc.exports.install=function(){var h=H_();
 hook("MapPlaceDirectoryService", findClass("holo-game.dll","MapPlaceDirectoryService"), "get_AllPokemon", 0);
 hook("MapAvatar", findClass("holo-game.dll","MapAvatar"), "get_Location", 0);
 hook("ItemBag", findItemBag(), "GetItemCount", 1);
 hook("IapService", findClass("holo-game.dll","IapService"), "get_Stardusts", 0);
 return Object.keys(CAP);
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        print("install:", sc.exports_sync.install(), flush=True)
        print("watching ~45s of normal map play (catcher stopped) — which objects get captured?\n", flush=True)
        t0 = time.time()
        while time.time() - t0 < 45:
            time.sleep(5)
            caps = sc.exports_sync.caps() or {}
            line = []
            for k in ["MapPlaceDirectoryService", "MapAvatar", "ItemBag", "IapService"]:
                v = caps.get(k)
                if isinstance(v, dict):
                    line.append(f"{k}={'CAPTURED x'+str(v.get('n')) if v.get('ptr') else 'hooked,0 calls'}")
                else:
                    line.append(f"{k}={v}")
            print("  " + " | ".join(line), flush=True)
        print("\n=== FINAL ===", flush=True)
        caps = sc.exports_sync.caps() or {}
        for k in ["MapPlaceDirectoryService", "MapAvatar", "ItemBag", "IapService"]:
            v = caps.get(k)
            if isinstance(v, dict) and v.get("ptr"):
                print(f"  {k}: CAPTURED ({v.get('n')} calls) ptr={v.get('ptr')}  -> hook-capture VIABLE", flush=True)
            elif isinstance(v, dict):
                print(f"  {k}: hooked but 0 game calls -> NOT passively capturable, needs another route", flush=True)
            else:
                print(f"  {k}: {v}", flush=True)
    finally:
        try:
            sc.unload()
        except Exception:
            pass
        try:
            sess.detach()
        except Exception:
            pass


main()
