"""Read LIVE interaction-range values to confirm the ~40m Go-Plus gate:
  - ClientMapObjectsInteractionRangeSettingsProto (InteractionRangeMeters / Far / Remote)
  - FortSettingsProto.InteractionRangeMeters
  - SpawnPokemonService.spawn/despawnInteractionRangeMultiplier
Heap-scans for each class's instances and prints the range fields. READ-ONLY."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
function kp(k){var b=[];var t=ptr(k);for(var i=0;i<8;i++){var v=t.and(0xff).toInt32();b.push((v<16?"0":"")+v.toString(16));t=t.shr(8);}return b.join(" ");}
rpc.exports.scanClass=function(imageName,clsName,offs){
 var h=H_();var k=findClass(imageName,clsName);if(!k)return{err:"no class "+clsName};
 var pat=kp(k);var out=[];
 Process.enumerateRanges("rw-").forEach(function(r){if(r.file||r.size<256||r.size>134217728)return;
   try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length&&out.length<60;i++){var p=hs[i].address;
     var rec={addr:p.toString(),vals:{}};for(var j=0;j<offs.length;j++){try{rec.vals[offs[j]]=p.add(offs[j]).readDouble();}catch(e){rec.vals[offs[j]]="err";}}
     out.push(rec);}}catch(e){}});
 return {cls:clsName,count:out.length,hits:out};
};
"""


def show(label, image, cls, offs, names):
    return label, image, cls, offs, names


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        jobs = [
            ("ClientMapObjectsInteractionRangeSettingsProto", "holo-protos.dll",
             "ClientMapObjectsInteractionRangeSettingsProto", [0x10, 0x18, 0x20],
             ["InteractionRangeMeters", "FarInteractionRangeMeters", "RemoteInteractionRangeMeters"]),
            ("FortSettingsProto", "holo-protos.dll", "FortSettingsProto", [0x10, 0x30, 0x48],
             ["InteractionRangeMeters", "FarInteractionRangeMeters", "RemoteInteractionRangeMeters"]),
            ("SpawnPokemonService", "holo-game.dll", "SpawnPokemonService", [0x20, 0x28],
             ["despawnInteractionRangeMultiplier", "spawnInteractionRangeMultiplier"]),
        ]
        for label, image, cls, offs, names in jobs:
            print(f"\n===== {label} ({image}) =====")
            r = sc.exports_sync.scan_class(image, cls, [hex(o) for o in offs])
            if isinstance(r, dict) and r.get("err"):
                print("  ", r["err"]); continue
            hits = r.get("hits", [])
            # show distinct value-tuples (filter implausible)
            seen = set()
            shown = 0
            for h in hits:
                vals = h["vals"]
                tup = tuple(round(vals.get(hex(o), -1), 3) if isinstance(vals.get(hex(o)), (int, float)) else vals.get(hex(o)) for o in offs)
                # plausibility: first value in (0,1000)
                v0 = vals.get(hex(offs[0]))
                if not isinstance(v0, (int, float)) or not (0 < v0 < 5000):
                    continue
                if tup in seen:
                    continue
                seen.add(tup)
                parts = [f"{names[i]}={vals.get(hex(offs[i]))}" for i in range(len(offs))]
                print(f"  @{h['addr']}  " + "  ".join(parts))
                shown += 1
                if shown >= 8:
                    break
            if shown == 0:
                print(f"  ({r.get('count',0)} raw hits, none plausible)")
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()
