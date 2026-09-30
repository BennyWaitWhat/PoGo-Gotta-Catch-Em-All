"""UI-FREE catch test: WildMapPokemon.SendEncounterRequest() then MapPokemon.TryCapture(GreatThrow, null).
NO SetupEncounter / NO EncounterInteractionState / NO scene -> nothing should appear on screen.
Confirms via Great-ball delta (attempt sent) and that no UI was touched. ONE Great. Attach-retry."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),oN:b("il2cpp_object_new","pointer",["pointer"]),isVT:b("il2cpp_class_is_valuetype","int",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj,params){var h=H_();if(!m)return null;var n=params?params.length:0;var args=ptr(0);if(n){args=Memory.alloc(Process.pointerSize*n);for(var i=0;i<n;i++)args.add(i*Process.pointerSize).writePointer(params[i]);}var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,args,exc);if(!exc.readPointer().isNull()){send({k:'p',s:'EXC'});return null;}return r;}
function P(s){try{send({k:'p',s:s,st:ST,f:F});}catch(e){}}

var ST=-9,TARGET=ptr(0),F=0,mark=0,M={},PBT=null,PBT_VT=false,SENDENC=true;
rpc.exports.findItemBag=function(){var h=H_();var imgs=["holo-game.dll","holo-protos.dll"];for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(/^I[A-Z]/.test(nm))continue;var m=h.cMN(k,Memory.allocUtf8String("GetItemCount"),1);if(m&&!m.isNull())return {ns:h.CGNS(k).readCString(),cls:nm};}catch(e){}}}return null;};
rpc.exports.count=function(ibStr,item){var h=H_();var ib=ptr(ibStr);var m=h.cMN(h.OGC(ib),Memory.allocUtf8String("GetItemCount"),1);if(!m||m.isNull())return -1;var arg=Memory.alloc(4);arg.writeS32(item);var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,ib,args,exc);if(!exc.readPointer().isNull())return -2;if(ret.isNull())return -3;try{return ret.add(0x10).readS32();}catch(e){return -4;}};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.wmp=function(inst){var out={};function g(n){var m=mOf(H_().OGC(ptr(inst)),n,0);return m?inv(m,ptr(inst),[]):null;}
 try{out.pid=(function(){var r=g("get_PokemonId");return r?r.add(0x10).readS32():null;})();}catch(e){}
 try{out.cp=(function(){var r=g("get_Cp");return r?r.add(0x10).readS32():null;})();}catch(e){}
 try{out.vis=(function(){var r=g("get_VisibleOnMap");return r?!!r.add(0x10).readU8():null;})();}catch(e){}
 try{out.enc=(function(){var r=g("get_EncounterId");return r?r.add(0x10).readU64().toString():null;})();}catch(e){}
 return out;};
rpc.exports.install=function(){
 var h=H_();var st={};
 PBT=findClass("holo-game.dll","PokeballThrow"); if(PBT)PBT_VT=!!h.isVT(PBT); st.pbt=!!PBT;
 var camC=findClass("holo-game.dll","CameraFollowingGround"); var mLU=mOf(camC,"LateUpdate",0);
 if(mLU){var ad=mLU.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){tick();}});st.pump=true;}}
 return st;
};
rpc.exports.arm=function(tptr){TARGET=ptr(tptr);M.send=mOf(H_().OGC(TARGET),"SendEncounterRequest",0);M.try=mOf(H_().OGC(TARGET),"TryCapture",2);ST=0;F=0;mark=0;P('armed send='+(!!M.send)+' try='+(!!M.try));};
rpc.exports.state=function(){return {st:ST};};
function tick(){ if(ST<0||ST>=9)return; F++;
 try{
  if(ST===0){ if(SENDENC&&M.send)inv(M.send,TARGET,[]); P('sent_encounter'); ST=1; mark=F; }
  else if(ST===1){ if(F-mark>=120){ var obj=H_().oN(PBT);obj.add(0x10).writeS32(2);obj.add(0x14).writeFloat(1.0);obj.add(0x18).writeU8(1);obj.add(0x19).writeU8(0);obj.add(0x1a).writeU8(0);var p=PBT_VT?obj.add(0x10):obj; var r=inv(M.try,TARGET,[p,ptr(0)]); P('try_capture ret='+(r&&!r.isNull()?'promise':'null')); ST=9; } }
 }catch(e){ST=-1;P('ERR '+e);}
}
"""


def attach():
    for i in range(10):
        try:
            return pg.get_session()
        except Exception as e:
            print(f"attach retry {i}: {str(e)[:50]}"); time.sleep(5)
    return None, None


def main():
    sess, pid = attach()
    if not sess:
        print("could not attach"); return
    print("attached", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    sc.on("message", lambda m, d: print("  [pump]", m["payload"].get("s")) if m.get("type") == "send" and m.get("payload", {}).get("k") == "p" else None)
    st = sc.exports_sync.install()
    print("install:", st)
    if not (st.get("pump") and st.get("pbt")):
        sess.detach(); return
    info = sc.exports_sync.find_item_bag(); ib = None
    if info:
        r = finder.exports_sync.find_singleton(info["ns"], info["cls"])
        ib = next((h for h in (r.get("hits", []) if isinstance(r, dict) else []) if sc.exports_sync.count(h, 2) >= 0), None)
    great0 = sc.exports_sync.count(ib, 2) if ib else None
    target = None
    r = finder.exports_sync.find_singleton("Niantic.Holoholo.Map", "WildMapPokemon")
    for h in (r.get("hits", []) if isinstance(r, dict) else []):
        if sc.exports_sync.cls_name(h) != "WildMapPokemon":
            continue
        i = sc.exports_sync.wmp(h)
        if i.get("vis") and i.get("pid") and i.get("enc") and i.get("enc") != "0":
            target = (h, i); break
    if not target:
        print("no visible target"); sess.detach(); return
    print(f"TARGET dex={target[1]['pid']} cp={target[1]['cp']} | Great before={great0}")
    sc.exports_sync.arm(target[0])
    end = time.time() + 20
    while time.time() < end:
        time.sleep(0.5)
        if sc.exports_sync.state().get("st") == 9:
            break
    time.sleep(6)
    great1 = sc.exports_sync.count(ib, 2) if ib else None
    print(f"\nGreat: before={great0} after={great1} delta={None if great0 is None or great1 is None else great1-great0}")
    print("=> if delta is -1 and your screen showed NO encounter popup, the UI-free catch path works.")
    sess.detach()


main()
