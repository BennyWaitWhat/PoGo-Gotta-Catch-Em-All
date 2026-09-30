"""READ-ONLY: deep-read the Showcase/contest schedule. Harvest every ContestScheduleProto
fully (depth 4) capturing all strings, pokemon ids (int slots), and epoch-ms timestamps.
Also dump LocalTimeProto raw int slots to fix the y/m/d/h offsets. Find the contest whose
id contains today's epoch 1780362000000 and report its featured pokemon + window."""
import sys, os, time, json, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),
  OGC:b("il2cpp_object_get_class","pointer",["pointer"]),rcInit:b("il2cpp_runtime_class_init","void",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"]),alloc:b("il2cpp_alloc","pointer",["size_t"]),free:b("il2cpp_free","void",["pointer"]),strLen:b("il2cpp_string_length","int",["pointer"]),strChars:b("il2cpp_string_chars","pointer",["pointer"]),
  livenessAlloc:b("il2cpp_unity_liveness_allocate_struct","pointer",["pointer","int","pointer","pointer","pointer"]),livenessFromStatics:b("il2cpp_unity_liveness_calculation_from_statics","void",["pointer"]),livenessFinalize:b("il2cpp_unity_liveness_finalize","void",["pointer"]),livenessFreeStruct:b("il2cpp_unity_liveness_free_struct","void",["pointer"]),stopWorld:b("il2cpp_stop_gc_world","void",[]),startWorld:b("il2cpp_start_gc_world","void",[])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function classInProtos(cls){var h=H_();var im=img("holo-protos.dll");if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function liveness(klass){var h=H_();try{if(h.rcInit)h.rcInit(klass);}catch(e){}var hits=[];var onObjects=new NativeCallback(function(objects,count,userData){for(var i=0;i<count;i++){hits.push(objects.add(i*Process.pointerSize).readPointer().toString());}},'void',['pointer','int','pointer']);var realloc=new NativeCallback(function(handle,size,userData){if(!handle.isNull()&&size.compare(0)===0){h.free(handle);return ptr(0);}return h.alloc(size);},'pointer',['pointer','size_t','pointer']);try{if(h.stopWorld)h.stopWorld();var st=h.livenessAlloc(klass,0,onObjects,ptr(0),realloc);h.livenessFromStatics(st);if(h.livenessFinalize)h.livenessFinalize(st);if(h.startWorld)h.startWorld();if(h.livenessFreeStruct)h.livenessFreeStruct(st);}catch(e){if(h.startWorld){try{h.startWorld();}catch(e2){}}return {err:"threw "+e};}return {hits:hits};}
rpc.exports.live=function(cls){var k=classInProtos(cls);if(!k)return {err:"nf"};return liveness(k);};
function clsNameOf(p){var h=H_();try{if(!p||p.isNull())return null;var k=p.readPointer();if(!k||k.isNull())return null;var nmp=h.CGN(k);if(!nmp||nmp.isNull())return null;var s=nmp.readCString();if(!s||s.length===0||s.length>72)return null;for(var i=0;i<s.length;i++){var c=s.charCodeAt(i);if(c<0x20||c>0x7e)return null;}return s;}catch(e){return null;}}
function readStr(p){var h=H_();try{var len=h.strLen(p);if(len<0||len>4000)return null;var cp=h.strChars(p);if(!cp||cp.isNull())return null;return cp.readUtf16String(len);}catch(e){return null;}}
function looksTs(v){try{var lo=Int64("1700000000000"),hi=Int64("1900000000000");return v.compare(lo)>=0&&v.compare(hi)<=0;}catch(e){return false;}}
function harvest(inst,depth){var h=H_();var out={cls:clsNameOf(inst),slots:{}};
 for(var off=0x10;off<=0x110;off+=8){ var info={}; var p; try{p=inst.add(off).readPointer();}catch(e){continue;}
  if(p&&!p.isNull()){var cn=clsNameOf(p);
   if(cn==="String"){var s=readStr(p);if(s!==null&&s.length){info.str=s;}}
   else if(cn&&cn.indexOf("Proto")>=0){info.child=cn;if(depth>0)info.sub=harvest(p,depth-1);}
   else if(cn&&cn.indexOf("RepeatedField")>=0){try{var arr=p.add(0x10).readPointer();var cnt=p.add(0x18).readS32();info.repeated=cn;info.count=cnt;var els=[];for(var j=0;j<cnt&&j<16;j++){var ep=arr.add(0x20+j*8).readPointer();var ec=clsNameOf(ep);if(ec==="String"){els.push({s:readStr(ep)});}else if(ec&&ec.indexOf("Proto")>=0){els.push(depth>0?{c:ec,h:harvest(ep,depth-1)}:{c:ec});}else{els.push({raw:ep?ep.toString():null,c:ec});}}info.elems=els;}catch(e){info.repErr=String(e);}}
   else if(cn){info.obj=cn;}
  } else {
   try{var v64=inst.add(off).readS64();if(looksTs(v64)){info.tsMs=v64.toString();}else{var v32=inst.add(off).readS32();if(v32!==0)info.i32=v32;}}catch(e){}
  }
  if(Object.keys(info).length)out.slots["+0x"+off.toString(16)]=info;
 }
 return out;
}
rpc.exports.harvest=function(instStr,depth){return harvest(ptr(instStr),depth);};
// raw int dump for offset calibration
rpc.exports.ints=function(instStr){var inst=ptr(instStr);var o={};for(var off=0x10;off<=0x80;off+=4){try{o["+0x"+off.toString(16)]=inst.add(off).readS32();}catch(e){}}return o;};
rpc.exports.clsOf=function(instStr){return clsNameOf(ptr(instStr));};
"""


def main():
    out = {"ok": False}
    last_err = None
    for attempt in range(4):
        sess = None
        try:
            sess, pid = pg.get_session()
            sc = pg.get_script_with_helpers(sess, JS)
            # 1) all ContestScheduleProto, full harvest
            r = sc.exports_sync.live("ContestScheduleProto")
            hits = r.get("hits", []) if isinstance(r, dict) else []
            contests = []
            for hp in hits:
                h = sc.exports_sync.harvest(hp, 4)
                contests.append(h)
            out["contests"] = contests
            # 2) LocalTimeProto calibration: live a few, dump raw ints
            rl = sc.exports_sync.live("LocalTimeProto")
            lhits = rl.get("hits", []) if isinstance(rl, dict) else []
            cal = []
            for hp in lhits[:6]:
                cal.append({"ptr": hp, "ints": sc.exports_sync.ints(hp)})
            out["localtime_calib"] = cal
            out["pid"] = pid
            out["ok"] = True
            # write to a sidecar file too (large)
            with open(os.path.join(HERE, "_showcase_detail_out.json"), "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
            print(json.dumps({"ok": True, "n_contests": len(contests), "n_localtime": len(lhits),
                              "wrote": "_showcase_detail_out.json", "pid": pid}))
            sess.detach()
            return
        except Exception as e:
            last_err = str(e)[:200]
            try:
                sess.detach()
            except Exception:
                pass
            time.sleep(3)
    print(json.dumps({"ok": False, "error": last_err}))


main()
