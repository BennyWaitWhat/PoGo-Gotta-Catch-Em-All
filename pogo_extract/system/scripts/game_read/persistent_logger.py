"""PERSISTENT catch logger — runs continuously in the background, self-reconnecting through a lossy
link, appending every event to catch_log.txt so nothing in the gaps is missed:
  - VGP3 / Go-Plus catch   (hook PgpActivityMonitor.xek)
  - MANUAL catch + ball     (hook CatchPokemonProto.WriteTo, read Pokeball)
  - inventory ball counts   (poll Poke/Great/Ultra every few seconds; deltas reveal each catch's ball)
READ-ONLY. Meant to be launched with run_in_background and left running."""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

LOG = os.path.join(ROOT, "system", "analysis", "pokemod", "catch_log.txt")
ITEM = {0: "?", 1: "POKE", 2: "GREAT", 3: "ULTRA", 4: "MASTER"}

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
rpc.exports.hook=function(){
 var h=H_();var st={};
 var PAM=h.cFN(img("holo-game.dll"),Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpActivityMonitor"));
 var mXek=PAM&&!PAM.isNull()?h.cMN(PAM,Memory.allocUtf8String("xek"),1):null;
 if(mXek&&!mXek.isNull()){var ad=mXek.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){try{send({k:'vgp3'});}catch(e){}}});st.vgp3=true;}}
 var CP=h.cFN(img("holo-protos.dll"),Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String("CatchPokemonProto"));
 if(CP&&!CP.isNull()){var pk=ffield(CP,"pokeball");var mW=h.cMN(CP,Memory.allocUtf8String("WriteTo"),1);if(mW&&!mW.isNull()&&pk>=0){var ad2=mW.readPointer();if(!ad2.isNull()){Interceptor.attach(ad2,{onEnter:function(a){try{send({k:'manual',ball:a[0].add(pk).readS32()});}catch(e){}}});st.manual=true;st.pkOff=pk;}}}
 return st;
};
"""


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    f = open(LOG, "a", encoding="utf-8")

    def w(s):
        f.write(f"{time.strftime('%H:%M:%S')} {s}\n"); f.flush()

    w("===== logger session start =====")
    while True:
        try:
            sess, pid = pg.get_session()
            finder = pg.get_script_with_helpers(sess)
            sc = pg.get_script_with_helpers(sess, JS)

            def on_msg(m, d):
                if m.get("type") == "send":
                    p = m.get("payload", {})
                    if p.get("k") == "vgp3":
                        w("CATCH vgp3/go-plus")
                    elif p.get("k") == "manual":
                        w(f"CATCH manual ball={ITEM.get(p.get('ball'), p.get('ball'))}")
            sc.on("message", on_msg)

            info = sc.exports_sync.find_item_bag()
            ib = None
            if info:
                r = finder.exports_sync.find_singleton(info["ns"], info["cls"])
                for h in (r.get("hits", []) if isinstance(r, dict) else []):
                    if sc.exports_sync.count(h, 1) >= 0:
                        ib = h; break
            st = sc.exports_sync.hook()
            w(f"attached pid={pid} hooks={st} itembag={'ok' if ib else 'NO'}")
            last = None
            while True:
                time.sleep(4)
                if ib:
                    inv = {ITEM[i]: sc.exports_sync.count(ib, i) for i in (1, 2, 3)}
                    if inv != last:
                        w(f"INV {inv}"); last = inv
        except Exception as e:
            w(f"--- link drop: {str(e)[:80]} — reconnecting ---")
            time.sleep(3)


if __name__ == "__main__":
    main()
