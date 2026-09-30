"""RECON (READ-ONLY): verifyFirst gate for the gym-berry-feeder. Confirms the two blockers before any feed:
  1) GymFeedBerryGuiController.FeedPokemon signature (arg count + param types + return),
  2) the LIVE Holoholo.Rpc.Item enum berry ids (Razz / Nanab to use; Golden Razz / Pinap to EXCLUDE),
  3) GymFeedPokemonOutProto.Types.Result ordinals (the back-off signal incl. the 30-min cap).
Also confirms MapPlaceDirectoryService.get_ActiveGyms + the defender accessor. WRITES NOTHING."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),cGNT:b("il2cpp_class_get_nested_types","pointer",["pointer","pointer"]),CGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","uint32"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),FGN:b("il2cpp_field_get_name","pointer",["pointer"]),FGFlags:b("il2cpp_field_get_flags","int",["pointer"]),FSGV:b("il2cpp_field_static_get_value","void",["pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function clsIn(image,ns,nm){var h=H_();var im=img(image);if(!im)return null;return h.cFN(im,Memory.allocUtf8String(ns),Memory.allocUtf8String(nm));}
function paramTypes(m){var h=H_();var pc=h.mGPC(m);var ps=[];for(var i=0;i<pc;i++){try{ps.push(h.tGN(h.mGP(m,i)).readCString());}catch(e){ps.push("?");}}return ps;}
function methodsFull(k){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var out=[];while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+"("+paramTypes(m).join(", ")+") -> "+rt);}catch(e){}}return out;}
function dumpEnumCls(cls){var h=H_();var out={};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.CGF(cls,it))&&!f.isNull()){try{var fl=h.FGFlags(f);if(!((fl&0x10)&&(fl&0x40)))continue;var nm=h.FGN(f).readCString();if(nm==='value__')continue;var buf=Memory.alloc(8);buf.writeU64(0);h.FSGV(f,buf);out[buf.readS32()]=nm;}catch(e){}}return out;}
function nested(k,name){var h=H_();if(!k)return null;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var nt;while((nt=h.cGNT(k,it))&&!nt.isNull()){try{if(h.CGN(nt).readCString()===name)return nt;}catch(e){}}return null;}
rpc.exports.methodsFull=function(image,cls){var k=findClass(image,cls);if(!k)return {err:"no class "+cls};return {ns:(H_().CGNS(k).readCString()||""), methods:methodsFull(k)};};
rpc.exports.searchClasses=function(image,sub){var h=H_();var im=img(image);if(!im)return [];var cnt=h.iGCC(im);var out=[];var s=sub.toLowerCase();for(var i=0;i<cnt&&out.length<80;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(nm.toLowerCase().indexOf(s)>=0)out.push((h.CGNS(k).readCString()||"")+"."+nm);}catch(e){}}return out;};
rpc.exports.searchMethods=function(image,sub){var h=H_();var im=img(image);if(!im)return [];var cnt=h.iGCC(im);var out=[];var s=sub.toLowerCase();for(var i=0;i<cnt&&out.length<60;i++){var k=h.iGC(im,i);if(k.isNull())continue;var cn;try{cn=h.CGN(k).readCString();}catch(e){continue;}var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();if(nm.toLowerCase().indexOf(s)>=0){out.push(cn+"."+nm+"("+h.mGPC(m)+")");if(out.length>=60)break;}}catch(e){}}}return out;};
rpc.exports.itemEnum=function(){var cls=clsIn("holo-protos.dll","Holoholo.Rpc","Item");if(!cls||cls.isNull())return {err:"no Item enum"};return {map:dumpEnumCls(cls)};};
rpc.exports.resultEnum=function(){var k=clsIn("holo-protos.dll","Holoholo.Rpc","GymFeedPokemonOutProto");if(!k||k.isNull())return {err:"no GymFeedPokemonOutProto"};var t=nested(k,"Types");var r=nested(t||k,"Result");if(!r)return {err:"no Result nested type"};return {map:dumpEnumCls(r)};};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
    try:
        print("\n##### 1. FEED CONTROLLER + method signatures #####")
        for sub in ["GymFeed", "FeedBerry", "FeedPokemon"]:
            cl = sc.exports_sync.search_classes("holo-game.dll", sub)
            if cl:
                print(f"  classes ~'{sub}': {sorted(set(cl))}")
        for cls in ["GymRootController", "GymFeedBerryGuiController"]:
            r = sc.exports_sync.methods_full("holo-game.dll", cls)
            print(f"\n  --- {cls} [{(r or {}).get('ns')}] ---")
            for m in ((r or {}).get("methods") or [r]):
                if isinstance(m, str) and any(w in m.lower() for w in ["feed", "select", "berry", "pokemon", "gym", "defend", "open", "approach"]):
                    print("     ", m)
        sm = sc.exports_sync.search_methods("holo-game.dll", "FeedPokemon")
        print(f"\n  methods ~'FeedPokemon': {sm}")

        print("\n##### 2. ITEM enum — berries (USE Razz+Nanab; EXCLUDE Golden Razz+Pinap) #####")
        ie = sc.exports_sync.item_enum()
        if isinstance(ie, dict) and ie.get("map"):
            for k, v in sorted(((int(k), v) for k, v in ie["map"].items())):
                if any(w in v.lower() for w in ["razz", "nanab", "pinap", "berry", "razberry"]):
                    print(f"     {k:>5}  {v}")
        else:
            print("    ", ie)

        print("\n##### 3. GymFeedPokemonOutProto.Result ordinals (back-off signal) #####")
        re_ = sc.exports_sync.result_enum()
        if isinstance(re_, dict) and re_.get("map"):
            for k, v in sorted(((int(k), v) for k, v in re_["map"].items())):
                print(f"     {k:>3}  {v}")
        else:
            print("    ", re_)

        print("\n##### 4. Gym directory + defender access #####")
        r = sc.exports_sync.methods_full("holo-game.dll", "MapPlaceDirectoryService")
        for m in ((r or {}).get("methods") or []):
            if any(w in m.lower() for w in ["gym", "fort", "active", "nearby", "place"]):
                print("     ", m)

        print("\n##### 5. Gym object (IMapGym / MapGym) — defenders + id + team #####")
        gymcls = sorted(set(sc.exports_sync.search_classes("holo-game.dll", "MapGym")
                            + sc.exports_sync.search_classes("holo-game.dll", "GymStatus")))
        print("  gym-ish classes:", gymcls)
        for cls in ["IMapGym", "MapGym", "MapGymImpl"]:
            r = sc.exports_sync.methods_full("holo-game.dll", cls)
            ms = (r or {}).get("methods") or []
            if ms and not (isinstance(r, dict) and r.get("err")):
                print(f"  --- {cls} ---")
                for m in ms:
                    if any(w in m.lower() for w in ["id", "team", "defend", "pokemon", "motivat", "guard", "member", "info", "fort", "raid", "status"]):
                        print("     ", m)

        print("\n##### 6. Defender protos FULL (return types reveal the obfuscated getters) #####")
        for cls in ["GymDefenderProto", "MotivatedPokemonProto"]:
            r = sc.exports_sync.methods_full("holo-protos.dll", cls)
            ms = (r or {}).get("methods") or []
            print(f"  --- {cls} ({len(ms)} methods) ---")
            for m in ms:
                print("     ", m)
        pp = sc.exports_sync.methods_full("holo-protos.dll", "PokemonProto")
        print("  PokemonProto get_Id/get_DeployedFortId present:",
              [m for m in ((pp or {}).get("methods") or []) if m.startswith("get_Id(") or "get_DeployedFortId" in m])
        cf = sc.exports_sync.methods_full("holo-game.dll", "CameraFollowingGround")
        print("  CameraFollowingGround.LateUpdate present:",
              [m for m in ((cf or {}).get("methods") or []) if "LateUpdate" in m])
    finally:
        try:
            sc.unload(); sess.detach()
        except Exception:
            pass


main()
