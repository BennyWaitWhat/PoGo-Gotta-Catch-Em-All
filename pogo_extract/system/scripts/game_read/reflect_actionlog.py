"""BUILD step 1: map the Go-Plus action-log / Sfida proto structures to find where the ball / button /
catch-type is encoded (the field I must forge to make VGP3 report button-press Ultra catches).
Reflects the relevant protos' fields and flags ball/button/item/sfida. READ-ONLY. Self-reconnects."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
rpc.exports.fields=function(ns,cls){var h=H_();var k=h.cFN(img("holo-protos.dll"),Memory.allocUtf8String(ns),Memory.allocUtf8String(cls));if(!k||k.isNull())return null;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var out=[];while((f=h.cGF(k,it))&&!f.isNull()){try{out.push(h.fGN(f).readCString()+"@0x"+h.fGO(f).toString(16)+":"+h.tGN(h.fGT(f)).readCString());}catch(e){}}return out;};
rpc.exports.search=function(sub){var h=H_();var im=img("holo-protos.dll");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<60;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(nm.toLowerCase().indexOf(sub)>=0)out.push(nm);}catch(e){}}return out;};
"""

TARGETS = ["RegisterSfidaRequest", "RegisterSfidaResponse", "SfidaAssociateRequest",
           "SfidaAssociateResponse", "SfidaCertificationRequest", "SfidaCertificationResponse",
           "SfidaCertificationStage", "SfidaCheckPairingRequest", "SfidaCheckPairingResponse",
           "SfidaAuthToken", "SfidaUpdateRequest"]
FLAG = ["ball", "button", "item", "pokeball", "sfida", "capture", "catch"]


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        print("\n=== proto classes matching sfida/actionlog ===")
        for sub in ["sfida", "actionlog"]:
            for nm in sorted(set(sc.exports_sync.search(sub))):
                print("  ", nm)
        for cls in TARGETS:
            fl = sc.exports_sync.fields("Holoholo.Rpc", cls)
            if fl is None:
                continue
            print(f"\n=== {cls} ===")
            for line in fl:
                mark = "   <<<" if any(k in line.lower() for k in FLAG) else ""
                print("  ", line, mark)
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()
