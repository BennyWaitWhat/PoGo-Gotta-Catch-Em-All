"""Fingerprint which RPCs VGP3 actually dispatches (to learn how its server-side autocatch is driven).
Hooks EVERY typed RPC dispatcher nia::api::background::MakeProtobufAction<Req,Resp>(uint32 methodId, const Req&, cb)
in libholoholo.so -> logs the request TYPE + methodId on each dispatch. Plus xek catch marker + inventory.
READ-ONLY. Self-reconnecting. Works while stationary (any nearby spawn VGP3 catches drives it)."""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

OUT = os.path.join(ROOT, "system", "analysis", "pokemod", "rpc_types_capture.jsonl")
ITEM = {0: "?", 1: "POKE", 2: "GREAT", 3: "ULTRA", 4: "MASTER"}

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}

rpc.exports.findItemBag=function(){var h=H_();var imgs=["holo-game.dll","holo-protos.dll"];for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(/^I[A-Z]/.test(nm))continue;var m=h.cMN(k,Memory.allocUtf8String("GetItemCount"),1);if(m&&!m.isNull())return {ns:h.CGNS(k).readCString(),cls:nm};}catch(e){}}}return null;};
rpc.exports.count=function(ibStr,item){var h=H_();var ib=ptr(ibStr);var m=h.cMN(h.OGC(ib),Memory.allocUtf8String("GetItemCount"),1);if(!m||m.isNull())return -1;var arg=Memory.alloc(4);arg.writeS32(item);var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,ib,args,exc);if(!exc.readPointer().isNull())return -2;if(ret.isNull())return -3;try{return ret.add(0x10).readS32();}catch(e){return -4;}};

rpc.exports.hookCatch=function(){
 var h=H_();var st={};
 var PAM=h.cFN(img("holo-game.dll"),Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpActivityMonitor"));
 var mXek=PAM&&!PAM.isNull()?h.cMN(PAM,Memory.allocUtf8String("xek"),1):null;
 if(mXek&&!mXek.isNull()){var ad=mXek.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){try{send({k:'catch'});}catch(e){}}});st.xek=true;}}
 return st;
};

// extract the request type name from a MakeProtobufAction mangled symbol: ...MakeProtobufActionI<len><Name><len><Resp>...
function reqType(name){var key="MakeProtobufActionI";var i=name.indexOf(key);if(i<0)return null;i+=key.length;var j=i;while(j<name.length&&name.charCodeAt(j)>=48&&name.charCodeAt(j)<=57)j++;if(j===i)return name.substring(i,i+24);var len=parseInt(name.substring(i,j),10);if(!len||len>80)return name.substring(j,j+24);return name.substring(j,j+len);}

rpc.exports.hookDispatchers=function(){
 var mod=Process.findModuleByName("libholoholo.so");
 if(!mod)return {err:"no libholoholo"};
 var ex=mod.enumerateExports();
 var hooked=0,types={};
 var PFX="_ZN3nia3api10background18MakeProtobufActionI";
 for(var i=0;i<ex.length;i++){
  var n=ex[i].name;
  if(n.indexOf(PFX)!==0)continue;            // dispatcher functions only (not _ZTVZ/_ZZ/_ZNSt variants)
  var t=reqType(n);if(!t)continue;
  if(types[t])continue;                       // one hook per request type
  types[t]=true;
  (function(typeName){
    var last=0;
    try{Interceptor.attach(ex[i].address,{onEnter:function(a){try{var now=Date.now();if(now-last>1500){last=now;send({k:'rpc',t:typeName,mid:a[0].toInt32()});}}catch(e){}}});hooked++;}catch(e){}
  })(t);
 }
 return {hooked:hooked, distinctTypes:Object.keys(types).length};
};
"""


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    f = open(OUT, "a", encoding="utf-8")

    def emit(rec):
        rec["ts"] = time.strftime("%H:%M:%S")
        f.write(json.dumps(rec) + "\n"); f.flush()

    emit({"k": "session_start"})
    while True:
        try:
            sess, pid = pg.get_session()
            finder = pg.get_script_with_helpers(sess)
            sc = pg.get_script_with_helpers(sess, JS)

            def on_msg(m, d):
                if m.get("type") != "send":
                    return
                p = m.get("payload", {})
                k = p.get("k")
                if k == "rpc":
                    emit({"k": "rpc", "t": p.get("t"), "mid": p.get("mid")})
                elif k == "catch":
                    emit({"k": "catch"})
            sc.on("message", on_msg)

            info = sc.exports_sync.find_item_bag()
            ib = None
            if info:
                r = finder.exports_sync.find_singleton(info["ns"], info["cls"])
                for h in (r.get("hits", []) if isinstance(r, dict) else []):
                    if sc.exports_sync.count(h, 1) >= 0:
                        ib = h; break
            stc = sc.exports_sync.hook_catch()
            std = sc.exports_sync.hook_dispatchers()
            emit({"k": "attached", "pid": pid, "catch": stc, "dispatchers": std, "itembag": bool(ib)})
            last = None
            while True:
                time.sleep(3)
                if ib:
                    inv = {ITEM[i]: sc.exports_sync.count(ib, i) for i in (1, 2, 3)}
                    if inv != last:
                        emit({"k": "inv", **inv}); last = inv
        except Exception as e:
            emit({"k": "link_drop", "err": str(e)[:120]})
            time.sleep(3)


if __name__ == "__main__":
    main()
