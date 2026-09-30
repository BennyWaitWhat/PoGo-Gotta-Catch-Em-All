"""READ-ONLY: liveness over holo-protos.dll classes (resolved from that image directly,
since the preamble's cFN only binds holo-game.dll). For each live proto instance, call
ToString() (protobuf text dump) to reveal event names / featured pokemon / start-end times."""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402

CANDIDATES = [
    "GetBonusesOutProto", "AppliedBonusesProto", "AppliedBonusProto", "EventInfoProto",
    "ContestScheduleProto", "CurrentEventsSectionProto", "UpcomingEventsSectionProto",
    "EventSectionProto", "EventBannerSectionProto", "EventSettingsProto",
    "PromotionalBannerProto", "DailyBonusProto", "WeatherBonusProto",
    "EventPassStateProto", "EventPassesStateProto", "GymEventProto",
]

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),
  OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),rcInit:b("il2cpp_runtime_class_init","void",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"]),
  alloc:b("il2cpp_alloc","pointer",["size_t"]),free:b("il2cpp_free","void",["pointer"]),
  strChars:b("il2cpp_string_chars","pointer",["pointer"]),strLen:b("il2cpp_string_length","int",["pointer"]),
  livenessAlloc:b("il2cpp_unity_liveness_allocate_struct","pointer",["pointer","int","pointer","pointer","pointer"]),livenessFromStatics:b("il2cpp_unity_liveness_calculation_from_statics","void",["pointer"]),livenessFinalize:b("il2cpp_unity_liveness_finalize","void",["pointer"]),livenessFreeStruct:b("il2cpp_unity_liveness_free_struct","void",["pointer"]),stopWorld:b("il2cpp_stop_gc_world","void",[]),startWorld:b("il2cpp_start_gc_world","void",[])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function classInProtos(cls){var h=H_();var im=img("holo-protos.dll");if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function readIl2Str(s){var h=H_();if(!s||s.isNull())return null;try{var len=h.strLen(s);var cp=h.strChars(s);if(!cp||cp.isNull())return null;return cp.readUtf16String(len);}catch(e){try{return s.add(0x14).readUtf16String();}catch(e2){return null;}}}
function liveness(klass){var h=H_();if(!h.livenessAlloc||!h.livenessFromStatics)return {err:"no liveness api"};try{if(h.rcInit)h.rcInit(klass);}catch(e){}var hits=[];var onObjects=new NativeCallback(function(objects,count,userData){for(var i=0;i<count;i++){hits.push(objects.add(i*Process.pointerSize).readPointer().toString());}},'void',['pointer','int','pointer']);var realloc=new NativeCallback(function(handle,size,userData){if(!handle.isNull()&&size.compare(0)===0){h.free(handle);return ptr(0);}return h.alloc(size);},'pointer',['pointer','size_t','pointer']);try{if(h.stopWorld)h.stopWorld();var st=h.livenessAlloc(klass,0,onObjects,ptr(0),realloc);h.livenessFromStatics(st);if(h.livenessFinalize)h.livenessFinalize(st);if(h.startWorld)h.startWorld();if(h.livenessFreeStruct)h.livenessFreeStruct(st);}catch(e){if(h.startWorld){try{h.startWorld();}catch(e2){}}return {err:"threw "+e};}return {hits:hits};}
rpc.exports.liveProtos=function(cls){var k=classInProtos(cls);if(!k)return {err:"class not found in holo-protos.dll"};return liveness(k);};
rpc.exports.protoToString=function(instStr){var h=H_();try{var inst=ptr(instStr);var k=h.OGC(inst);var m=h.cMN(k,Memory.allocUtf8String("ToString"),0);if(!m||m.isNull())return {err:"no ToString"};var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,inst,ptr(0),exc);if(!exc.readPointer().isNull())return {err:"exc"};return {s:readIl2Str(r)};}catch(e){return {err:String(e)};}};
"""


def main():
    out = {"ok": False, "live": {}}
    last_err = None
    for attempt in range(4):
        sess = None
        try:
            sess, pid = pg.get_session()
            sc = pg.get_script_with_helpers(sess, JS)
            for cls in CANDIDATES:
                try:
                    r = sc.exports_sync.live_protos(cls)
                except Exception as e:
                    out["live"][cls] = {"err": str(e)[:80]}
                    continue
                if isinstance(r, dict) and "err" in r:
                    out["live"][cls] = {"err": r["err"][:80]}
                    continue
                hits = r.get("hits", []) if isinstance(r, dict) else []
                entry = {"n": len(hits), "dumps": []}
                for h in hits[:8]:
                    try:
                        ts = sc.exports_sync.proto_to_string(h)
                        s = ts.get("s") if isinstance(ts, dict) else None
                        if s and s.strip() and s.strip() not in ("{ }", "{}"):
                            entry["dumps"].append(s[:5000])
                    except Exception:
                        pass
                out["live"][cls] = entry
            out["pid"] = pid
            out["ok"] = True
            print(json.dumps(out, ensure_ascii=False, indent=1))
            sess.detach()
            return
        except Exception as e:
            last_err = str(e)[:200]
            try:
                sess.detach()
            except Exception:
                pass
            time.sleep(3)
    out["error"] = last_err
    print(json.dumps(out))


main()
