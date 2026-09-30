"""DECISIVE auto-vs-button capture. READ-ONLY. Self-reconnecting. Writes JSONL.

Goal: on the user's REAL Go Plus + (WAINA), find what a BUTTON catch sends to the server
that an AUTO catch does not — the channel that flips Poke -> Ultra. Also confirms, live,
whether the real WAINA even throws Ultra on auto (vs only on button).

Hooks (all onEnter/onLeave dumps — NOTHING is written/invoked on the account):
  native  libholoholo.so:
    - pgp::PgpClientImpl::AddScannedSfida(deviceId, buttonValue, kind)
          -> per BLE scan: buttonValue + DeviceKind  (the authoritative button witness)
    - GarProxyRequestProto::_InternalSerialize
          -> per outbound RPC: methodId (action) + head bytes  (the RPC SET per catch)
    - SfidaCaptureRequest::_InternalSerialize
          -> the catch RPC's wire bytes  (prove no ball field; see if button vs auto differ)
  managed il2cpp (holo-game/holo-protos):
    - PgpActivityMonitor.xek           -> catch marker (Go-Plus path)
    - CatchPokemonProto.WriteTo        -> manual catch + Pokeball
    - ItemBag.GetItemCount(1/2/3) poll -> ball consumed per catch (Ultra vs Poke vs Great)

Run in background; tail the JSONL. Protocol once the REAL Go Plus + is paired:
  STEP A: let it AUTO-catch ~10 times (NO button).
  STEP B: same spot, deliberately PRESS the button to catch ~10 times.
Everything else held constant, so the only variable is the button.
"""
import sys, os, time, json, binascii
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

OUT = os.path.join(ROOT, "system", "analysis", "pokemod", "catch_envelope_capture.jsonl")
ITEM = {0: "?", 1: "POKE", 2: "GREAT", 3: "ULTRA", 4: "MASTER"}
KIND = {0: "UNSET", 1: "GO_PLUS", 2: "POKE_BALL_PLUS", 3: "WAINA"}

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function ffield(cls,sub){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(cls,it))&&!f.isNull()){try{var nm=h.fGN(f).readCString().toLowerCase();if(nm.indexOf(sub)>=0)return h.fGO(f);}catch(e){}}return -1;}

rpc.exports.findItemBag=function(){var h=H_();var imgs=["holo-game.dll","holo-protos.dll"];for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(/^I[A-Z]/.test(nm))continue;var m=h.cMN(k,Memory.allocUtf8String("GetItemCount"),1);if(m&&!m.isNull())return {ns:h.CGNS(k).readCString(),cls:nm};}catch(e){}}}return null;};
rpc.exports.count=function(ibStr,item){var h=H_();var ib=ptr(ibStr);var m=h.cMN(h.OGC(ib),Memory.allocUtf8String("GetItemCount"),1);if(!m||m.isNull())return -1;var arg=Memory.alloc(4);arg.writeS32(item);var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,ib,args,exc);if(!exc.readPointer().isNull())return -2;if(ret.isNull())return -3;try{return ret.add(0x10).readS32();}catch(e){return -4;}};

rpc.exports.hookManaged=function(){
 var h=H_();var st={};
 var PAM=h.cFN(img("holo-game.dll"),Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpActivityMonitor"));
 var mXek=PAM&&!PAM.isNull()?h.cMN(PAM,Memory.allocUtf8String("xek"),1):null;
 if(mXek&&!mXek.isNull()){var ad=mXek.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){try{send({k:'catch'});}catch(e){}}});st.xek=true;}}
 var CP=h.cFN(img("holo-protos.dll"),Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String("CatchPokemonProto"));
 if(CP&&!CP.isNull()){var pk=ffield(CP,"pokeball");var mW=h.cMN(CP,Memory.allocUtf8String("WriteTo"),1);if(mW&&!mW.isNull()&&pk>=0){var ad2=mW.readPointer();if(!ad2.isNull()){Interceptor.attach(ad2,{onEnter:function(a){try{send({k:'manual',ball:a[0].add(pk).readS32()});}catch(e){}}});st.manual=true;st.pkOff=pk;}}}
 return st;
};

// resolve a native symbol in libholoholo.so by requiring ALL substrings to appear in its name.
// NOTE: this build keeps its full C++ symbol table in .dynsym (EXPORTS), not .symtab — must use enumerateExports.
function findSym(mod, parts){
 var syms=mod.enumerateExports();
 for(var i=0;i<syms.length;i++){var n=syms[i].name;if(syms[i].address.isNull())continue;var ok=true;for(var j=0;j<parts.length;j++){if(n.indexOf(parts[j])<0){ok=false;break;}}if(ok)return {addr:syms[i].address,name:n};}
 return null;
}
function readVarint(p){var shift=0,res=0,i=0;while(i<10){var bb=p.add(i).readU8();res+=(bb&0x7f)*Math.pow(2,shift);if((bb&0x80)===0){i++;break;}shift+=7;i++;}return {v:res,len:i};}

rpc.exports.hookNative=function(){
 var st={syms:{}};
 var mod=Process.findModuleByName("libholoholo.so");
 if(!mod){st.err="libholoholo.so not loaded";return st;}
 st.base=mod.base.toString();
 // AddScannedSfida(this, &deviceId, int buttonValue, DeviceKind kind) -> args 2,3
 var s1=findSym(mod,["AddScannedSfida"]);
 if(s1){var last0=0;Interceptor.attach(s1.addr,{onEnter:function(a){try{var btn=a[2].toInt32();var kind=a[3].toInt32();var now=Date.now();if(btn!==0){send({k:'scan',btn:btn,kind:kind});}else if(now-last0>1500){last0=now;send({k:'scan',btn:0,kind:kind});}}catch(e){}}});st.syms.addScanned=s1.name;}
 // GarProxyRequestProto::_InternalSerialize(this, uint8* target, stream) -> envelope {field1=methodId, field2=payload}. onEnter beacon (throttled) distinguishes "called" from "byte-read failed".
 var s2=findSym(mod,["GarProxyRequestProto","_InternalSerialize"]);
 if(s2){var lastE=0;Interceptor.attach(s2.addr,{onEnter:function(a){this.t=a[1];try{var now=Date.now();if(now-lastE>2000){lastE=now;send({k:'env_e'});}}catch(e){}},onLeave:function(r){try{var start=this.t;var total=r.sub(start).toInt32();if(total<=0||total>200000)return;var mid=-1;try{if(start.readU8()===0x08){mid=readVarint(start.add(1)).v;}}catch(e){}var n=total>48?48:total;send({k:'env',mid:mid,len:total},Memory.readByteArray(start,n));}catch(e){}}});st.syms.env=s2.name;}
 // SfidaCaptureRequest::_InternalSerialize -> the catch RPC (per hypothesis: button-press only). onEnter beacon = every one matters.
 var s3=findSym(mod,["SfidaCaptureRequest","_InternalSerialize"]);
 if(s3){Interceptor.attach(s3.addr,{onEnter:function(a){this.t=a[1];try{send({k:'sfcap_e'});}catch(e){}},onLeave:function(r){try{var len=r.sub(this.t).toInt32();if(len<=0||len>4096)return;var n=len>96?96:len;send({k:'sfcap',len:len},Memory.readByteArray(this.t,n));}catch(e){}}});st.syms.sfcap=s3.name;}
 // SfidaUpdateRequest::ByteSizeLong beacon (heartbeat, HARDWARE path) -> the device is sending hardware Sfida updates.
 var s4=findSym(mod,["SfidaUpdateRequest","ByteSizeLong"]);
 if(s4){var lastU=0;Interceptor.attach(s4.addr,{onEnter:function(a){try{var now=Date.now();if(now-lastU>1500){lastU=now;send({k:'supd'});}}catch(e){}}});st.syms.supd=s4.name;}
 // SOFT path (phone-emulated): does VGP3 use SoftSfidaCapture / SoftSfidaLocationUpdate instead of the hardware path?
 var s5=findSym(mod,["SoftSfidaCaptureProto","_InternalSerialize"]);
 if(s5){Interceptor.attach(s5.addr,{onEnter:function(a){this.t=a[1];try{send({k:'softcap_e'});}catch(e){}},onLeave:function(r){try{var len=r.sub(this.t).toInt32();if(len<=0||len>4096)return;var n=len>96?96:len;send({k:'softcap',len:len},Memory.readByteArray(this.t,n));}catch(e){}}});st.syms.softcap=s5.name;}
 var s6=findSym(mod,["SoftSfidaLocationUpdateProto","_InternalSerialize"]);
 if(!s6){s6=findSym(mod,["SoftSfidaLocationUpdateProto","ByteSizeLong"]);}
 if(s6){var lastSU=0;Interceptor.attach(s6.addr,{onEnter:function(a){try{var now=Date.now();if(now-lastSU>1500){lastSU=now;send({k:'softupd'});}}catch(e){}}});st.syms.softupd=s6.name;}
 // SSL_write beacon -> PROVES native Interceptor hooking works + universal outbound witness. Frida-version-robust resolution (no Module.findExportByName).
 try{
  var sw=null;
  var mods=Process.enumerateModules();
  for(var mi=0;mi<mods.length&&!sw;mi++){var mn=mods[mi].name.toLowerCase();if(mn.indexOf("ssl")<0&&mn.indexOf("conscrypt")<0&&mn.indexOf("boringssl")<0)continue;try{var exs=mods[mi].enumerateExports();for(var ej=0;ej<exs.length;ej++){if(exs[ej].name==="SSL_write"){sw=exs[ej].address;break;}}}catch(e){}}
  if(sw){var lastS=0,nS=0;Interceptor.attach(sw,{onEnter:function(a){nS++;try{var now=Date.now();if(now-lastS>2000){lastS=now;send({k:'ssl',n:nS});}}catch(e){}}});st.ssl=true;st.sslAddr=sw.toString();}else{st.ssl=false;}
 }catch(e){st.sslErr=String(e);}
 return st;
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
                if k == "scan":
                    emit({"k": "scan", "btn": p.get("btn"), "kind": KIND.get(p.get("kind"), p.get("kind"))})
                elif k == "catch":
                    emit({"k": "catch"})
                elif k == "manual":
                    emit({"k": "manual", "ball": ITEM.get(p.get("ball"), p.get("ball"))})
                elif k == "env":
                    emit({"k": "env", "mid": p.get("mid"), "len": p.get("len"),
                          "head": binascii.hexlify(d).decode() if d else None})
                elif k == "sfcap":
                    emit({"k": "sfcap", "len": p.get("len"),
                          "bytes": binascii.hexlify(d).decode() if d else None})
                elif k in ("softcap",):
                    emit({"k": "softcap", "len": p.get("len"),
                          "bytes": binascii.hexlify(d).decode() if d else None})
                else:
                    emit(dict(p))  # env_e/sfcap_e/supd/softcap_e/softupd/ssl beacons (keep payload)
            sc.on("message", on_msg)

            info = sc.exports_sync.find_item_bag()
            ib = None
            if info:
                r = finder.exports_sync.find_singleton(info["ns"], info["cls"])
                for h in (r.get("hits", []) if isinstance(r, dict) else []):
                    if sc.exports_sync.count(h, 1) >= 0:
                        ib = h; break
            stm = sc.exports_sync.hook_managed()
            stn = sc.exports_sync.hook_native()
            emit({"k": "attached", "pid": pid, "managed": stm, "native": stn, "itembag": bool(ib)})
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
