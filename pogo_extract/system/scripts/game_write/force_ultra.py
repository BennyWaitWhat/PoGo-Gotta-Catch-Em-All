"""#1 FORCE-ULTRA: on every catch sent via CatchPokemonProto, upgrade the ball to ULTRA_BALL(3).
Only upgrades POKE(1)/GREAT(2) -> ULTRA(3); leaves MASTER(4)/PREMIER(5)/etc untouched (so raid Premier
and intentional Master throws are preserved). Auto-disables if Ultra stock runs low (avoids fleeing on empty).
Server honors the client-chosen ball (proven: 13/13 manual Ultra catches in catch_log). REVERSIBLE: just stop this task.
Note: brief client UI/inventory desync possible (UI may show the selected ball; server records Ultra) until next sync."""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

LOG = os.path.join(ROOT, "system", "analysis", "pokemod", "force_ultra.log")
ITEM = {0: "?", 1: "POKE", 2: "GREAT", 3: "ULTRA", 4: "MASTER", 5: "PREMIER"}
MIN_ULTRA = 5  # stop forcing if Ultra stock drops to/below this (don't strand a catch on empty)

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function ffield(cls,sub){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(cls,it))&&!f.isNull()){try{var nm=h.fGN(f).readCString().toLowerCase();if(nm.indexOf(sub)>=0)return h.fGO(f);}catch(e){}}return -1;}
var FORCE=true;
rpc.exports.setForce=function(b){FORCE=!!b;return FORCE;};
rpc.exports.findItemBag=function(){var h=H_();var imgs=["holo-game.dll","holo-protos.dll"];for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(/^I[A-Z]/.test(nm))continue;var m=h.cMN(k,Memory.allocUtf8String("GetItemCount"),1);if(m&&!m.isNull())return {ns:h.CGNS(k).readCString(),cls:nm};}catch(e){}}}return null;};
rpc.exports.count=function(ibStr,item){var h=H_();var ib=ptr(ibStr);var m=h.cMN(h.OGC(ib),Memory.allocUtf8String("GetItemCount"),1);if(!m||m.isNull())return -1;var arg=Memory.alloc(4);arg.writeS32(item);var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,ib,args,exc);if(!exc.readPointer().isNull())return -2;if(ret.isNull())return -3;try{return ret.add(0x10).readS32();}catch(e){return -4;}};
rpc.exports.hook=function(){
 var h=H_();var st={};
 var CP=h.cFN(img("holo-protos.dll"),Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String("CatchPokemonProto"));
 if(CP&&!CP.isNull()){var pk=ffield(CP,"pokeball");var mW=h.cMN(CP,Memory.allocUtf8String("WriteTo"),1);
  if(mW&&!mW.isNull()&&pk>=0){var ad=mW.readPointer();if(!ad.isNull()){
   Interceptor.attach(ad,{onEnter:function(a){try{var cur=a[0].add(pk).readS32();if(FORCE&&(cur===1||cur===2)){a[0].add(pk).writeS32(3);send({k:'forced',from:cur});}else{send({k:'pass',ball:cur});}}catch(e){}}});
   st.hooked=true;st.pkOff=pk;}}}
 return st;
};
"""


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    f = open(LOG, "a", encoding="utf-8")

    def w(s):
        f.write(f"{time.strftime('%H:%M:%S')} {s}\n"); f.flush()

    w("===== force_ultra session start =====")
    while True:
        try:
            sess, pid = pg.get_session()
            finder = pg.get_script_with_helpers(sess)
            sc = pg.get_script_with_helpers(sess, JS)

            def on_msg(m, d):
                if m.get("type") != "send":
                    return
                p = m.get("payload", {})
                if p.get("k") == "forced":
                    w(f"FORCED {ITEM.get(p.get('from'), p.get('from'))}->ULTRA")
                elif p.get("k") == "pass":
                    w(f"pass ball={ITEM.get(p.get('ball'), p.get('ball'))} (not upgraded)")
            sc.on("message", on_msg)

            info = sc.exports_sync.find_item_bag()
            ib = None
            if info:
                r = finder.exports_sync.find_singleton(info["ns"], info["cls"])
                for h in (r.get("hits", []) if isinstance(r, dict) else []):
                    if sc.exports_sync.count(h, 1) >= 0:
                        ib = h; break
            st = sc.exports_sync.hook()
            w(f"attached pid={pid} hook={st} itembag={'ok' if ib else 'NO'} FORCE=ON (upgrades Poke/Great->Ultra)")
            forcing = True
            while True:
                time.sleep(3)
                if ib:
                    u = sc.exports_sync.count(ib, 3)
                    if u >= 0:
                        if u <= MIN_ULTRA and forcing:
                            sc.exports_sync.set_force(False); forcing = False
                            w(f"Ultra low ({u}) -> forcing DISABLED (won't strand catches)")
                        elif u > MIN_ULTRA and not forcing:
                            sc.exports_sync.set_force(True); forcing = True
                            w(f"Ultra ok ({u}) -> forcing RE-ENABLED")
        except Exception as e:
            w(f"--- link drop: {str(e)[:90]} — reconnecting ---")
            time.sleep(3)


if __name__ == "__main__":
    main()
