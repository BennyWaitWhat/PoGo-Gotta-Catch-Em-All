"""RECON (READ-ONLY): why can't PokeStops be spun? Reads account flags
(Warn/Banned/WasSuspended/WarnExpireMs from GetPlayerOutProto) and the live
PokeStop spin result (FortSearchOutProto.Result + CooldownComplete) by hooking
each proto's MergeFrom and reading the (public) field offsets directly. Pure read."""
import sys, os, time, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so"); var e={};
 il.enumerateExports().forEach(function(x){ if(x.name.indexOf("il2cpp_")===0) e[x.name]=x.address; });
 function b(n,r,a){ return e[n]? new NativeFunction(e[n],r,a): null; }
 H={ dG:b("il2cpp_domain_get","pointer",[]),
     dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
     aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),
     iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),
     iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),
     CGN:b("il2cpp_class_get_name","pointer",["pointer"]),
     cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),
     mGN:b("il2cpp_method_get_name","pointer",["pointer"]),
     mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),
     tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k); } } }
function findClass(name){ var h=H_(); var f=null; eachClass(function(k){ if(f)return; try{ if(h.CGN(k).readCString()===name) f=k; }catch(e){} }); return f; }

var LOG=[]; function L(s){ LOG.push(s); }
rpc.exports.drain=function(){ var o=LOG; LOG=[]; return o; };

function readField(self,r){
 if(r.size===1) return self.add(r.off).readU8();
 if(r.size===4) return self.add(r.off).readS32();
 return self.add(r.off).readS64().toString();
}
function hookMerge(cls, reads){
 var h=H_(); var k=findClass(cls); if(!k){ L("[noclass] "+cls); return; }
 var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var names=[]; var hooked=0;
 while(true){ var m=h.cGM(k,it); if(!m||m.isNull())break; var nm; try{ nm=h.mGN(m).readCString(); }catch(e){ continue; }
   names.push(nm);
   if(nm==="MergeFrom"){ var code=m.readPointer(); if(code&&!code.isNull()){
     (function(){ var rd=reads, cn=cls; Interceptor.attach(code,{ onEnter:function(a){ this.s=a[0]; },
       onLeave:function(){ try{ var self=this.s; if(!self||self.isNull())return; var p=[];
         for(var i=0;i<rd.length;i++){ p.push(rd[i].label+"="+readField(self,rd[i])); }
         L(cn+" || "+p.join("  ")); }catch(e){} } }); hooked++; })();
   } } }
 L("[methods "+cls+"] "+names.join(","));
 L("[hooked "+hooked+" MergeFrom on "+cls+"]");
}

rpc.exports.install=function(){ H_();
 hookMerge("FortSearchOutProto",[{off:0x10,size:4,label:"Result"},{off:0x30,size:4,label:"XpAwarded"},{off:0x38,size:8,label:"CooldownCompleteMs"}]);
 hookMerge("GetPlayerOutProto",[{off:0x20,size:1,label:"Banned"},{off:0x21,size:1,label:"Warn"},{off:0x22,size:1,label:"WasCreated"},{off:0x24,size:1,label:"WasSuspended"},{off:0x25,size:1,label:"SuspMsgAck"},{off:0x28,size:8,label:"WarnExpireMs"}]);
 return "installed";
};
"""

RESULT = {0: "NO_RESULT_SET", 1: "SUCCESS (got items)", 2: "OUT_OF_RANGE (too far)",
          3: "IN_COOLDOWN_PERIOD (soft-ban / spun too recently)", 4: "INVENTORY_FULL (bag full)",
          5: "EXCEEDED_DAILY_LIMIT (daily spin cap)", 6: "POI_INACCESSIBLE"}


def ms_to_str(ms):
    try:
        ms = int(ms)
        if ms <= 0:
            return "0 (none)"
        dt = datetime.datetime.fromtimestamp(ms / 1000.0)
        return f"{ms} ({dt:%Y-%m-%d %H:%M:%S} local)"
    except Exception:
        return str(ms)


def interpret(line):
    if line.startswith("FortSearchOutProto || "):
        kv = dict(p.split("=", 1) for p in line.split("|| ")[1].split("  "))
        r = int(kv.get("Result", -1))
        print(f"  >>> POKESTOP SPIN -> {RESULT.get(r, r)} | XP={kv.get('XpAwarded')} | cooldownComplete={ms_to_str(kv.get('CooldownCompleteMs',0))}", flush=True)
    elif line.startswith("GetPlayerOutProto || "):
        kv = dict(p.split("=", 1) for p in line.split("|| ")[1].split("  "))
        print("  >>> ACCOUNT FLAGS:", flush=True)
        print(f"        Warn (marked) = {kv.get('Warn')}   Banned = {kv.get('Banned')}   WasSuspended = {kv.get('WasSuspended')}", flush=True)
        print(f"        WarnExpireMs  = {ms_to_str(kv.get('WarnExpireMs',0))}", flush=True)
    else:
        print("  ", line, flush=True)


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = sess.create_script(JS)
    sc.load()
    print("install:", sc.exports_sync.install(), flush=True)
    print("\n>>> NOW: open your Trainer PROFILE (reads account flags), then SPIN A POKESTOP. Watching 240s. <<<\n", flush=True)
    t0 = time.time()
    while time.time() - t0 < 240:
        time.sleep(2)
        for line in (sc.exports_sync.drain() or []):
            interpret(line)
    try:
        sc.unload(); sess.detach()
    except Exception:
        pass


main()
