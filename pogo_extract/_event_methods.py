"""READ-ONLY: dump method names (name/argc) for a list of candidate event classes
across both DLLs, so we can pick getters with start/end time + featured pokemon."""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402

TARGETS = [
    ("holo-game.dll", "CurrentEventEntry"),
    ("holo-game.dll", "HappeningNowEventEntry"),
    ("holo-game.dll", "TodaysEventsWidget"),
    ("holo-game.dll", "TodaysEventsBonusController"),
    ("holo-game.dll", "ActiveEventWidget"),
    ("holo-game.dll", "UpcomingEventsEntry"),
    ("holo-game.dll", "GameMasterDataService"),
    ("holo-protos.dll", "EventInfoProto"),
    ("holo-protos.dll", "GetBonusesOutProto"),
    ("holo-protos.dll", "AppliedBonusesProto"),
    ("holo-protos.dll", "AppliedBonusProto"),
    ("holo-protos.dll", "ContestScheduleProto"),
    ("holo-protos.dll", "EventSectionProto"),
    ("holo-protos.dll", "CurrentEventsSectionProto"),
    ("holo-protos.dll", "EventBannerSectionProto"),
    ("holo-protos.dll", "EventSettingsProto"),
]

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
rpc.exports.methods=function(imageName,cls){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;var nm;try{nm=h.CGN(k).readCString();}catch(e){continue;}if(nm!==cls)continue;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m,out=[];var guard=0;while((m=h.cGM(k,it))&&!m.isNull()&&guard++<500){try{out.push(h.mGN(m).readCString()+"/"+h.mGPC(m));}catch(e){}}return out;}return null;};
"""


def main():
    out = {"ok": False}
    last_err = None
    for attempt in range(4):
        sess = None
        try:
            sess, pid = pg.get_session()
            sc = pg.get_script_with_helpers(sess, JS)
            res = {}
            for image, cls in TARGETS:
                ms = sc.exports_sync.methods(image, cls)
                res[cls] = ms
            out["methods"] = res
            out["pid"] = pid
            out["ok"] = True
            print(json.dumps(out, indent=1))
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
