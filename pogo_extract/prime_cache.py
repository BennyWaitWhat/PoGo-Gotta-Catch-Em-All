"""One-shot priming: discover everything once via Frida, write disk cache.

Run this whenever PoGo is updated. Subsequent scripts load the cache instead
of re-walking exports / assemblies / classes.

Usage:
    python prime_cache.py [--device 127.0.0.1:27047] [--pid <pid>]

Prerequisites:
  - PoGo running with frida-gadget attached (ZygiskFrida setup, listen mode)
  - adb authorized to the device
"""
from __future__ import annotations
import argparse
import json
import sys
import time

import frida

from pogo_il2cpp_cache import (
    CACHE_DIR, Il2cppCache, fetch_fingerprint,
)

PKG = "com.nianticlabs.pokemongo"

WANTED_EXPORTS = [
    "il2cpp_domain_get",
    "il2cpp_domain_get_assemblies",
    "il2cpp_assembly_get_image",
    "il2cpp_image_get_name",
    "il2cpp_image_get_class",
    "il2cpp_image_get_class_count",
    "il2cpp_class_from_name",
    "il2cpp_class_get_name",
    "il2cpp_class_get_namespace",
    "il2cpp_class_get_method_from_name",
    "il2cpp_class_get_methods",
    "il2cpp_class_get_field_from_name",
    "il2cpp_class_get_fields",
    "il2cpp_class_get_type",
    "il2cpp_method_get_name",
    "il2cpp_method_get_param_count",
    "il2cpp_field_get_name",
    "il2cpp_field_get_offset",
    "il2cpp_field_get_value",
    "il2cpp_field_get_value_object",
    "il2cpp_type_get_name",
    "il2cpp_runtime_invoke",
    "il2cpp_thread_attach",
    "il2cpp_string_chars",
    "il2cpp_string_length",
    "il2cpp_string_new",
    "il2cpp_object_new",
    "il2cpp_array_length",
]

# (qualified_name, dll_hint, [field_names])
FIELD_TARGETS = [
    ("Holoholo.Rpc.PokemonProto", "holo-protos.dll", [
        "pokemonId_", "cp_", "stamina_", "staminaMax_",
        "move1_", "move2_", "move3_",
        "individualAttack_", "individualDefense_", "individualStamina_",
        "heightM_", "weightKg_", "nickname_", "pokeball_",
        "cpMultiplier_", "additionalCpMultiplier_",
        "creationTimeMs_", "pokemonDisplay_",
        "isLucky_", "isBad_", "move2IsPurifiedExclusive_",
        "deployedFortId_",
    ]),
    ("Holoholo.Rpc.PokemonDisplayProto", "holo-protos.dll", [
        "gender_", "form_", "costume_", "shiny_",
        "weatherBoostedCondition_", "alignment_", "sizeCategory_",
        "weightCategory_", "heightCategory_",
    ]),
    ("Niantic.Holoholo.Internal.PokemonBagImpl", "holo-game.dll", []),
    ("Niantic.Holoholo.Tagging.TaggingRpcService", "holo-game.dll", []),
]

# Only class lookup (image hint discovery), no field probing
CLASS_TARGETS_NO_FIELDS = [
    ("Niantic.Holoholo.Internal.PokemonBagImpl", "holo-game.dll"),
    ("Niantic.Holoholo.Tagging.TaggingRpcService", "holo-game.dll"),
]


DISCOVERY_JS = r"""
rpc.exports = {
    discover: function(wantedExports, fieldTargets) {
        var mod = Process.findModuleByName("libil2cpp.so");
        if (!mod) return {ok:false, err:"no libil2cpp"};
        var base = mod.base;
        var baseStr = base.toString();
        var exports_rva = {};
        var all = mod.enumerateExports();
        var wanted = {};
        for (var i = 0; i < wantedExports.length; i++) wanted[wantedExports[i]] = true;
        for (var i = 0; i < all.length; i++) {
            var e = all[i];
            if (wanted[e.name]) {
                exports_rva[e.name] = e.address.sub(base).toInt32();
            }
        }
        function bind(name, ret, args) {
            var rva = exports_rva[name];
            if (rva === undefined) return null;
            return new NativeFunction(base.add(rva), ret, args);
        }
        var dG = bind("il2cpp_domain_get", "pointer", []);
        var dGA = bind("il2cpp_domain_get_assemblies", "pointer", ["pointer","pointer"]);
        var aGI = bind("il2cpp_assembly_get_image", "pointer", ["pointer"]);
        var iGN = bind("il2cpp_image_get_name", "pointer", ["pointer"]);
        var cFN = bind("il2cpp_class_from_name", "pointer", ["pointer","pointer","pointer"]);
        var cFFN = bind("il2cpp_class_get_field_from_name", "pointer", ["pointer","pointer"]);
        var fGO = bind("il2cpp_field_get_offset", "int", ["pointer"]);
        var tA = bind("il2cpp_thread_attach", "pointer", ["pointer"]);
        if (!dG || !dGA || !aGI || !cFN) return {ok:false, err:"missing core exports"};

        var dom = dG();
        if (dom.isNull()) return {ok:false, err:"domain NULL - too early"};
        tA(dom);

        var sp = Memory.alloc(4);
        var asms = dGA(dom, sp);
        var n = sp.readS32();
        var images = {};
        for (var i = 0; i < n; i++) {
            var img = aGI(asms.add(i * Process.pointerSize).readPointer());
            if (img.isNull()) continue;
            var nm = iGN(img).readCString();
            images[nm] = img;
        }
        var image_hints = {};
        var field_offsets = {};
        for (var t = 0; t < fieldTargets.length; t++) {
            var spec = fieldTargets[t];
            var qn = spec[0], dllHint = spec[1], fieldNames = spec[2];
            var lastDot = qn.lastIndexOf(".");
            var ns = qn.substring(0, lastDot);
            var cls = qn.substring(lastDot + 1);
            var nsPtr = Memory.allocUtf8String(ns);
            var clsPtr = Memory.allocUtf8String(cls);
            var foundDll = null;
            var klass = null;
            var candidates = dllHint ? [dllHint] : [];
            // Always also fall back to scanning all dlls
            for (var dn in images) if (candidates.indexOf(dn) < 0) candidates.push(dn);
            for (var c = 0; c < candidates.length; c++) {
                var img = images[candidates[c]];
                if (!img) continue;
                var k = cFN(img, nsPtr, clsPtr);
                if (!k.isNull()) { klass = k; foundDll = candidates[c]; break; }
            }
            if (!klass) {
                image_hints[qn] = null;
                continue;
            }
            image_hints[qn] = foundDll;
            if (fieldNames && fieldNames.length > 0 && cFFN && fGO) {
                var fo = {};
                for (var f = 0; f < fieldNames.length; f++) {
                    var fname = fieldNames[f];
                    var fld = cFFN(klass, Memory.allocUtf8String(fname));
                    if (!fld.isNull()) {
                        fo[fname] = fGO(fld);
                    }
                }
                if (Object.keys(fo).length > 0) field_offsets[qn] = fo;
            }
        }

        return {
            ok: true,
            base: baseStr,
            exports_rva: exports_rva,
            image_hints: image_hints,
            field_offsets: field_offsets,
            image_names: Object.keys(images),
        };
    }
};
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="127.0.0.1:27047",
                    help="Frida remote device address")
    ap.add_argument("--pid", type=int, default=None,
                    help="Target PID (defaults to PoGo by package name)")
    ap.add_argument("--wait", type=int, default=30,
                    help="Seconds to wait for domain to be live before failing")
    args = ap.parse_args()

    print("[*] Resolving APK fingerprint via adb...")
    fp = fetch_fingerprint()
    print(f"    versionName={fp.version_name}  versionCode={fp.version_code}")
    print(f"    buildId={fp.build_id[:32]}...")

    print(f"[*] Connecting to Frida at {args.device}...")
    mgr = frida.get_device_manager()
    dev = mgr.add_remote_device(args.device)

    if args.pid is None:
        procs = [p for p in dev.enumerate_processes() if p.name == PKG]
        if not procs:
            print(f"[!] {PKG} not running on device", file=sys.stderr)
            return 1
        pid = procs[0].pid
    else:
        pid = args.pid
    print(f"[*] Attaching to pid {pid}...")
    sess = dev.attach(pid)
    script = sess.create_script(DISCOVERY_JS)
    script.load()

    deadline = time.time() + args.wait
    result = None
    last_err = None
    while time.time() < deadline:
        try:
            result = script.exports_sync.discover(WANTED_EXPORTS, FIELD_TARGETS)
            if result.get("ok"):
                break
            last_err = result.get("err")
            print(f"    not ready: {last_err}; retry...")
        except Exception as e:
            last_err = str(e)
            print(f"    error: {last_err}; retry...")
        time.sleep(2)

    sess.detach()

    if not result or not result.get("ok"):
        print(f"[!] discovery failed: {last_err}", file=sys.stderr)
        return 2

    print(f"[*] Resolved {len(result['exports_rva'])}/{len(WANTED_EXPORTS)} exports")
    print(f"[*] Loaded {len(result['image_names'])} images")
    for qn, dll in result["image_hints"].items():
        flag = "OK" if dll else "MISS"
        print(f"    {flag}  {qn} -> {dll}")
    for qn, fo in result["field_offsets"].items():
        print(f"    fields[{qn}] = {len(fo)}")

    cache = Il2cppCache(
        fingerprint=fp,
        exports=result["exports_rva"],
        images={qn: dll for qn, dll in result["image_hints"].items() if dll},
        field_offsets=result["field_offsets"],
        notes={
            "base_at_prime": result["base"],
            "image_names_seen": result["image_names"],
        },
    )
    out = cache.save()
    print(f"[*] Cache written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
