"""Disk cache for PoGo IL2CPP discovery data.

Cached values (stable across PoGo restarts for a given APK build):
  - libil2cpp.so export RVAs (offset from module base)
  - Image namespace hints (which dll contains which namespace)
  - C# managed-object field offsets (per class + field name -> int)
  - PokemonBag/ServiceLocator probe results

NOT cached (allocated by libil2cpp at init, address varies each launch):
  - Il2CppClass*  -- must re-resolve each launch via il2cpp_class_from_name
  - MethodInfo*   -- must re-resolve via il2cpp_class_get_method_from_name
  - Il2CppImage*

Invalidation: APK versionName + versionCode + first 16 bytes of libil2cpp.so build-id.
If any drift, cache is considered stale and re-priming required.

Layout on disk:
  ~/.cache/pogo_il2cpp/<apk_version>_<build_id8>.json

Caller usage:
  from pogo_il2cpp_cache import load_cache, attach_to_pogo
  cache = load_cache()  # raises CacheMiss if absent or stale
  js_blob = cache.js_init_blob()  # inline this at top of your Frida script
"""
from __future__ import annotations
import json
import os
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

PKG = "com.nianticlabs.pokemongo"
CACHE_DIR = Path.home() / ".cache" / "pogo_il2cpp"
LIBIL2CPP_REMOTE = f"/data/data/{PKG}/lib/arm64/libil2cpp.so"
LIBIL2CPP_APK_PATH = "lib/arm64-v8a/libil2cpp.so"


class CacheMiss(Exception):
    pass


@dataclass
class ApkFingerprint:
    version_name: str
    version_code: str
    build_id: str

    def slug(self) -> str:
        return f"{self.version_name}_{self.build_id[:16]}"


@dataclass
class Il2cppCache:
    fingerprint: ApkFingerprint
    exports: dict[str, int] = field(default_factory=dict)
    images: dict[str, str] = field(default_factory=dict)
    field_offsets: dict[str, dict[str, int]] = field(default_factory=dict)
    notes: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "fingerprint": asdict(self.fingerprint),
            "exports": self.exports,
            "images": self.images,
            "field_offsets": self.field_offsets,
            "notes": self.notes,
        }, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "Il2cppCache":
        d = json.loads(raw)
        return cls(
            fingerprint=ApkFingerprint(**d["fingerprint"]),
            exports={k: int(v) for k, v in d["exports"].items()},
            images=d["images"],
            field_offsets={k: {fk: int(fv) for fk, fv in v.items()}
                           for k, v in d["field_offsets"].items()},
            notes=d.get("notes", {}),
        )

    def path(self) -> Path:
        return CACHE_DIR / f"{self.fingerprint.slug()}.json"

    def save(self) -> Path:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = self.path()
        p.write_text(self.to_json(), encoding="utf-8")
        return p

    def js_init_blob(self) -> str:
        """Produce JS source that, when prepended to a Frida script, exposes
        global `IL2CPP` with prebound NativeFunctions and helpers. The blob is
        ~5KB and avoids the enumerateExports() walk that costs 1-2s."""
        return _render_js_blob(self)


def adb_shell(args: list[str], device: str | None = None) -> str:
    cmd = ["adb"]
    if device:
        cmd += ["-s", device]
    cmd += ["shell"] + args
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)


def fetch_fingerprint(device: str | None = None) -> ApkFingerprint:
    dump = adb_shell(["dumpsys", "package", PKG], device=device)
    version_name = ""
    version_code = ""
    for line in dump.splitlines():
        s = line.strip()
        if s.startswith("versionName="):
            version_name = s.split("=", 1)[1].strip()
        elif s.startswith("versionCode="):
            version_code = s.split("=", 1)[1].split()[0]
        if version_name and version_code:
            break
    if not version_name:
        raise RuntimeError(f"versionName not found in dumpsys for {PKG}")
    build_id = fetch_build_id(device=device)
    return ApkFingerprint(version_name=version_name, version_code=version_code,
                          build_id=build_id)


def fetch_build_id(device: str | None = None) -> str:
    """Read GNU build-id from libil2cpp.so on device. Requires root."""
    out = adb_shell(
        ["su", "-c", f"readelf -n {LIBIL2CPP_REMOTE} 2>/dev/null | grep -A1 'Build ID' | tail -n1"],
        device=device,
    )
    out = out.strip()
    if out:
        return out.split()[-1]
    out = adb_shell(
        ["su", "-c", f"od -An -tx1 -N32 -j32 {LIBIL2CPP_REMOTE} 2>/dev/null"],
        device=device,
    )
    return "".join(out.split())[:32] or "unknown"


def load_cache(device: str | None = None,
               require_fresh: bool = True) -> Il2cppCache:
    """Load cache for the currently-installed APK. Raises CacheMiss if absent
    or (when require_fresh=True) if the fingerprint no longer matches."""
    fp = fetch_fingerprint(device=device)
    p = CACHE_DIR / f"{fp.slug()}.json"
    if not p.exists():
        raise CacheMiss(f"no cache for {fp.slug()}; run prime_cache.py")
    cache = Il2cppCache.from_json(p.read_text(encoding="utf-8"))
    if require_fresh:
        if (cache.fingerprint.version_name != fp.version_name
                or cache.fingerprint.version_code != fp.version_code
                or cache.fingerprint.build_id != fp.build_id):
            raise CacheMiss(f"fingerprint drift; expected {cache.fingerprint}, got {fp}")
    return cache


def _render_js_blob(cache: Il2cppCache) -> str:
    exports_lit = json.dumps(cache.exports)
    fields_lit = json.dumps(cache.field_offsets)
    images_lit = json.dumps(cache.images)
    return f"""
// --- BEGIN pogo_il2cpp_cache injected blob ---
// Generated for APK {cache.fingerprint.version_name} build {cache.fingerprint.build_id[:16]}
var IL2CPP = (function() {{
    var EXPORT_RVAS = {exports_lit};
    var FIELD_OFFSETS = {fields_lit};
    var IMAGE_HINTS = {images_lit};
    var mod = Process.findModuleByName("libil2cpp.so");
    if (!mod) throw new Error("libil2cpp.so not loaded yet");
    var base = mod.base;
    var fn = {{}};
    function bind(name, ret, args) {{
        var rva = EXPORT_RVAS[name];
        if (rva === undefined) return null;
        return new NativeFunction(base.add(rva), ret, args);
    }}
    fn.domain_get = bind("il2cpp_domain_get", "pointer", []);
    fn.domain_get_assemblies = bind("il2cpp_domain_get_assemblies", "pointer", ["pointer", "pointer"]);
    fn.assembly_get_image = bind("il2cpp_assembly_get_image", "pointer", ["pointer"]);
    fn.image_get_name = bind("il2cpp_image_get_name", "pointer", ["pointer"]);
    fn.class_from_name = bind("il2cpp_class_from_name", "pointer", ["pointer", "pointer", "pointer"]);
    fn.class_get_method_from_name = bind("il2cpp_class_get_method_from_name", "pointer", ["pointer", "pointer", "int"]);
    fn.class_get_methods = bind("il2cpp_class_get_methods", "pointer", ["pointer", "pointer"]);
    fn.class_get_field_from_name = bind("il2cpp_class_get_field_from_name", "pointer", ["pointer", "pointer"]);
    fn.method_get_name = bind("il2cpp_method_get_name", "pointer", ["pointer"]);
    fn.field_get_offset = bind("il2cpp_field_get_offset", "int", ["pointer"]);
    fn.field_get_value_object = bind("il2cpp_field_get_value_object", "pointer", ["pointer", "pointer"]);
    fn.runtime_invoke = bind("il2cpp_runtime_invoke", "pointer", ["pointer", "pointer", "pointer", "pointer"]);
    fn.thread_attach = bind("il2cpp_thread_attach", "pointer", ["pointer"]);
    fn.string_chars = bind("il2cpp_string_chars", "pointer", ["pointer"]);
    fn.string_length = bind("il2cpp_string_length", "int", ["pointer"]);
    fn.array_length = bind("il2cpp_array_length", "int", ["pointer"]);
    fn.class_get_name = bind("il2cpp_class_get_name", "pointer", ["pointer"]);
    fn.class_get_namespace = bind("il2cpp_class_get_namespace", "pointer", ["pointer"]);
    var _state = {{ domain: null, images: {{}}, classes: {{}} }};
    function ensureDomain() {{
        if (_state.domain) return _state.domain;
        var d = fn.domain_get();
        if (d.isNull()) throw new Error("il2cpp_domain_get NULL - game not initialized");
        fn.thread_attach(d);
        _state.domain = d;
        return d;
    }}
    function getImage(dllName) {{
        if (_state.images[dllName]) return _state.images[dllName];
        var dom = ensureDomain();
        var sp = Memory.alloc(4);
        var asms = fn.domain_get_assemblies(dom, sp);
        var n = sp.readS32();
        for (var i = 0; i < n; i++) {{
            var img = fn.assembly_get_image(asms.add(i * Process.pointerSize).readPointer());
            if (img.isNull()) continue;
            var nm = fn.image_get_name(img).readCString();
            _state.images[nm] = img;
            if (nm === dllName) return img;
        }}
        return null;
    }}
    function getClass(qualifiedName) {{
        var hit = _state.classes[qualifiedName];
        if (hit) return hit;
        var hint = IMAGE_HINTS[qualifiedName];
        var lastDot = qualifiedName.lastIndexOf(".");
        var ns = qualifiedName.substring(0, lastDot);
        var cls = qualifiedName.substring(lastDot + 1);
        var nsPtr = Memory.allocUtf8String(ns);
        var clsPtr = Memory.allocUtf8String(cls);
        var dlls = hint ? [hint] : ["holo-game.dll", "holo-protos.dll", "Assembly-CSharp.dll"];
        for (var i = 0; i < dlls.length; i++) {{
            var img = getImage(dlls[i]);
            if (!img) continue;
            var k = fn.class_from_name(img, nsPtr, clsPtr);
            if (!k.isNull()) {{
                _state.classes[qualifiedName] = k;
                return k;
            }}
        }}
        return null;
    }}
    function getMethod(qualifiedName, methodName, argc) {{
        var k = getClass(qualifiedName);
        if (!k) return null;
        return fn.class_get_method_from_name(k, Memory.allocUtf8String(methodName), argc);
    }}
    function getFieldOffset(qualifiedName, fieldName) {{
        var entry = FIELD_OFFSETS[qualifiedName];
        if (entry && entry[fieldName] !== undefined) return entry[fieldName];
        var k = getClass(qualifiedName);
        if (!k) return -1;
        var f = fn.class_get_field_from_name(k, Memory.allocUtf8String(fieldName));
        if (f.isNull()) return -1;
        return fn.field_get_offset(f);
    }}
    return {{
        fn: fn, base: base,
        ensureDomain: ensureDomain,
        getImage: getImage,
        getClass: getClass,
        getMethod: getMethod,
        getFieldOffset: getFieldOffset,
    }};
}})();
// --- END pogo_il2cpp_cache injected blob ---
"""


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        c = load_cache(require_fresh=False)
        print(f"APK {c.fingerprint.version_name} (code {c.fingerprint.version_code})")
        print(f"Build ID: {c.fingerprint.build_id}")
        print(f"Exports cached: {len(c.exports)}")
        print(f"Classes with field offsets: {len(c.field_offsets)}")
        for cls, fields in c.field_offsets.items():
            print(f"  {cls}: {len(fields)} fields")
    else:
        fp = fetch_fingerprint()
        print(f"Current APK: {fp.version_name} (code {fp.version_code})")
        print(f"Build ID: {fp.build_id}")
        print(f"Slug: {fp.slug()}")
        p = CACHE_DIR / f"{fp.slug()}.json"
        print(f"Cache path: {p}")
        print(f"Cached: {p.exists()}")
