"""READ-ONLY: for each candidate event proto/service class, run the liveness API to
count live instances. For proto hits, call ToString() (read-only, protobuf text dump)
and also enumerate Descriptor field names. Reports the richest live event data found."""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402

# (image, ns, cls) — protos live in holo-protos.dll. ns from the earlier scan.
CANDIDATES = [
    ("holo-protos.dll", "Holoholo.Rpc", "GetBonusesOutProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "AppliedBonusesProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "EventInfoProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "ContestScheduleProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "CurrentEventsSectionProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "UpcomingEventsSectionProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "EventSectionProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "EventBannerSectionProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "EventSettingsProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "EventInfoProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "PromotionalBannerProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "DailyBonusProto"),
    ("holo-protos.dll", "Holoholo.Rpc", "WeatherBonusProto"),
]

# extra_js: ToString() + Descriptor field-name enumeration, both read-only, against a live proto.
EXTRA = r"""
function pH(){ if(globalThis.__PH)return globalThis.__PH; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 var H={OGC:b("il2cpp_object_get_class","pointer",["pointer"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),strChars:b("il2cpp_string_chars","pointer",["pointer"]),strLen:b("il2cpp_string_length","int",["pointer"])};
 globalThis.__PH=H;return H;}
function readIl2Str(s){ if(!s||s.isNull())return null; var H=pH(); try{var len=H.strLen(s);var cp=H.strChars(s);if(!cp||cp.isNull())return null;return cp.readUtf16String(len);}catch(e){ try{return s.add(0x14).readUtf16String();}catch(e2){return null;} } }
rpc.exports.protoToString=function(instStr){ var H=pH(); try{var inst=ptr(instStr);var k=H.OGC(inst);var m=H.cMN(k,Memory.allocUtf8String("ToString"),0);if(!m||m.isNull())return {err:"no ToString"};var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=H.rI(m,inst,ptr(0),exc);if(!exc.readPointer().isNull())return {err:"exc"};return {s:readIl2Str(r)};}catch(e){return {err:String(e)};} };
rpc.exports.clsOf=function(instStr){ var H=pH(); try{return H.CGN(H.OGC(ptr(instStr))).readCString();}catch(e){return null;} };
"""


def main():
    out = {"ok": False, "live": {}}
    last_err = None
    for attempt in range(4):
        sess = None
        try:
            sess, pid = pg.get_session()
            finder = pg.get_script_with_helpers(sess)      # findSingleton/liveness
            sc = pg.get_script_with_helpers(sess, EXTRA)    # ToString helper
            seen_cls = set()
            for image, ns, cls in CANDIDATES:
                if cls in seen_cls:
                    continue
                seen_cls.add(cls)
                try:
                    r = finder.exports_sync.find_singleton(ns, cls)
                except Exception as e:
                    out["live"][cls] = {"err": str(e)[:80]}
                    continue
                if isinstance(r, dict) and "err" in r:
                    out["live"][cls] = {"err": r["err"][:80]}
                    continue
                hits = r.get("hits", []) if isinstance(r, dict) else []
                entry = {"n": len(hits), "dumps": []}
                # ToString a few hits (cap to keep attach short + output sane)
                for h in hits[:6]:
                    try:
                        ts = sc.exports_sync.proto_to_string(h)
                        s = ts.get("s") if isinstance(ts, dict) else None
                        if s and s.strip() and s.strip() not in ("{ }", "{}"):
                            entry["dumps"].append({"ptr": h, "str": s[:4000]})
                    except Exception:
                        pass
                out["live"][cls] = entry
            out["pid"] = pid
            out["ok"] = True
            print(json.dumps(out, ensure_ascii=False, indent=1))
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
