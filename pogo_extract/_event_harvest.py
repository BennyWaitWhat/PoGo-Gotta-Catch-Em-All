"""READ-ONLY: generic proto harvester. For each live event proto, walk its object slots
(0x10..0xC0). For each slot: if it points to a System.String -> read it; if to a *Proto ->
recurse 1 level; also interpret raw 8-byte slots as candidate epoch-ms timestamps (plausible
range) and 4-byte ints. Bypasses obfuscated getters/descriptors entirely. Targets the protos
that carry today's event identity: EventSectionProto + its children, DailyBonusProto,
GenericClientEvent-ish, ContestScheduleProto entries, AppliedBonus*."""
import sys, os, time, json, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402

TARGETS = ["EventSectionProto", "EventBannerSectionProto", "CurrentEventsSectionProto",
           "UpcomingEventsSectionProto", "DailyBonusProto", "ContestScheduleProto",
           "AppliedBonusesProto", "AppliedBonusProto", "EventSettingsProto", "EventInfoProto",
           "WeatherBonusProto", "PromotionalBannerProto"]

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),
  OGC:b("il2cpp_object_get_class","pointer",["pointer"]),rcInit:b("il2cpp_runtime_class_init","void",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"]),alloc:b("il2cpp_alloc","pointer",["size_t"]),free:b("il2cpp_free","void",["pointer"]),strLen:b("il2cpp_string_length","int",["pointer"]),strChars:b("il2cpp_string_chars","pointer",["pointer"]),
  livenessAlloc:b("il2cpp_unity_liveness_allocate_struct","pointer",["pointer","int","pointer","pointer","pointer"]),livenessFromStatics:b("il2cpp_unity_liveness_calculation_from_statics","void",["pointer"]),livenessFinalize:b("il2cpp_unity_liveness_finalize","void",["pointer"]),livenessFreeStruct:b("il2cpp_unity_liveness_free_struct","void",["pointer"]),stopWorld:b("il2cpp_stop_gc_world","void",[]),startWorld:b("il2cpp_start_gc_world","void",[])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function classInProtos(cls){var h=H_();var im=img("holo-protos.dll");if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function liveness(klass){var h=H_();try{if(h.rcInit)h.rcInit(klass);}catch(e){}var hits=[];var onObjects=new NativeCallback(function(objects,count,userData){for(var i=0;i<count;i++){hits.push(objects.add(i*Process.pointerSize).readPointer().toString());}},'void',['pointer','int','pointer']);var realloc=new NativeCallback(function(handle,size,userData){if(!handle.isNull()&&size.compare(0)===0){h.free(handle);return ptr(0);}return h.alloc(size);},'pointer',['pointer','size_t','pointer']);try{if(h.stopWorld)h.stopWorld();var st=h.livenessAlloc(klass,0,onObjects,ptr(0),realloc);h.livenessFromStatics(st);if(h.livenessFinalize)h.livenessFinalize(st);if(h.startWorld)h.startWorld();if(h.livenessFreeStruct)h.livenessFreeStruct(st);}catch(e){if(h.startWorld){try{h.startWorld();}catch(e2){}}return {err:"threw "+e};}return {hits:hits};}
rpc.exports.live=function(cls){var k=classInProtos(cls);if(!k)return {err:"nf"};return liveness(k);};

// Is ptr a plausible il2cpp object? (points into a mapped range, class ptr readable + has a name)
function clsNameOf(p){var h=H_();try{if(!p||p.isNull())return null;var k=p.readPointer();if(!k||k.isNull())return null;var nmp=h.CGN(k);if(!nmp||nmp.isNull())return null;var s=nmp.readCString();if(!s||s.length===0||s.length>64)return null;for(var i=0;i<s.length;i++){var c=s.charCodeAt(i);if(c<0x20||c>0x7e)return null;}return s;}catch(e){return null;}}
function readStr(p){var h=H_();try{var len=h.strLen(p);if(len<0||len>2000)return null;var cp=h.strChars(p);if(!cp||cp.isNull())return null;var s=cp.readUtf16String(len);return s;}catch(e){return null;}}
function looksTs(v){ // epoch ms between 2020-01-01 and 2030-01-01
 try{var lo=Int64("1577836800000"),hi=Int64("1893456000000");return v.compare(lo)>=0&&v.compare(hi)<=0;}catch(e){return false;}}

// Harvest one object: scan slots 0x10..0xC8, classify.
function harvest(instStr,depth){var h=H_();var inst=ptr(instStr);var out={cls:clsNameOf(inst),slots:{}};
 for(var off=0x10;off<=0xC8;off+=8){ var slotName="+0x"+off.toString(16); var info={};
  var p; try{p=inst.add(off).readPointer();}catch(e){continue;} if(!p||p.isNull()){continue;}
  // candidate string object?
  var cn=clsNameOf(p);
  if(cn==="String"){ var s=readStr(p); if(s!==null&&s.length){info.str=s;} }
  else if(cn&&cn.indexOf("Proto")>=0){ info.child=cn; if(depth>0){info.sub=harvest(p.toString(),depth-1);} }
  else if(cn&&(cn.indexOf("RepeatedField")>=0)){ info.repeated=cn; /* dump element ptrs by reading backing array */
    try{var arr=p.add(0x10).readPointer();var cnt=p.add(0x18).readS32();info.count=cnt;var els=[];for(var j=0;j<cnt&&j<10;j++){var ep=arr.add(0x20+j*8).readPointer();var ec=clsNameOf(ep);if(ec==="String"){els.push({s:readStr(ep)});}else if(ec&&ec.indexOf("Proto")>=0){els.push(depth>0?{c:ec,h:harvest(ep.toString(),depth-1)}:{c:ec});}else{els.push({raw:ep.toString(),c:ec});}}info.elems=els;}catch(e){info.repErr=String(e);}
  }
  else if(cn){ info.obj=cn; }
  else {
   // not a pointer to an object: interpret raw 8 bytes as int64 (timestamp?) and low 4 bytes as int32
   try{var v64=inst.add(off).readS64(); if(looksTs(v64)){info.tsMs=v64.toString();} else {var v32=inst.add(off).readS32(); if(v32!==0&&v32>-2000000000&&v32<2000000000)info.i32=v32;} }catch(e){}
  }
  if(Object.keys(info).length){out.slots[slotName]=info;}
 }
 return out;
}
rpc.exports.harvest=function(instStr,depth){return harvest(instStr,depth);};
"""


def has_signal(h):
    try:
        for k, v in h.get("slots", {}).items():
            if "str" in v or "child" in v or "tsMs" in v or "repeated" in v:
                return True
    except Exception:
        pass
    return False


def main():
    out = {"ok": False, "events": {}}
    last_err = None
    for attempt in range(4):
        sess = None
        try:
            sess, pid = pg.get_session()
            sc = pg.get_script_with_helpers(sess, JS)
            for cls in TARGETS:
                r = sc.exports_sync.live(cls)
                hits = r.get("hits", []) if isinstance(r, dict) else []
                kept = []
                for hp in hits[:12]:
                    h = sc.exports_sync.harvest(hp, 2)
                    if isinstance(h, dict) and has_signal(h):
                        kept.append(h)
                out["events"][cls] = {"n": len(hits), "populated": kept[:8]}
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
