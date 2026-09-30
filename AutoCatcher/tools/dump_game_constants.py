"""Read-only dump of the numbers hard-coded in Pokemon GO's own code.

  * C# `const` fields (literal): the value comes straight from the IL2CPP metadata.
  * `static readonly` numbers, TimeSpans and numeric arrays: read from the class's static storage, only for classes
    the game has already initialized (storage exists) and only non-zero values (zero = unset / not run yet).
Nothing is written to the game and no class is initialized by us (il2cpp_field_static_get_value is used for
literals only -- for anything else it would run the class constructor).

The class walk runs in C (CModule) in budgeted steps: a NativeFunction releases Frida's shared JS lock while C runs,
so the catcher's per-frame tick is never blocked. Every il2cpp call uses exceptions:'propagate'.

Usage (desktop, phone on adb):  python tools/dump_game_constants.py
Writes system/analysis/game_constants.json
"""
import json
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

OUT = os.path.join(ROOT, "system", "analysis", "game_constants.json")
# engine, runtime and third-party libraries: their constants are not the game's
SKIP_IMAGES = re.compile(r"^(mscorlib|netstandard|System|Mono\.|Microsoft\.|Unity\.|UnityEngine|Newtonsoft|Google\.|Firebase|"
                         r"Facebook|Bolts|DOTween|Demigiant|Zenject|UniRx|Rx\.|Sentry|AppsFlyer|Adjust|Lottie|Cinemachine|"
                         r"TextMesh|com\.unity|Purchasing|Crashlytics|I18N|__Generated)", re.I)

C_SRC = r"""
typedef unsigned long u64;
typedef struct {
  char *buf; u64 cap; u64 len;
  void **images; int nimg; int img; int cls; int budget;
  u64 sf_off; int done; int full;
  u64 nclass; u64 nfield; u64 nconst; u64 nstatic;
} St;
extern void *il2cpp_image_get_class(void *image, u64 index);
extern u64 il2cpp_image_get_class_count(void *image);
extern const char *il2cpp_class_get_name(void *k);
extern const char *il2cpp_class_get_namespace(void *k);
extern void *il2cpp_class_get_declaring_type(void *k);
extern unsigned char il2cpp_class_is_enum(void *k);
extern unsigned char il2cpp_class_is_generic(void *k);
extern void *il2cpp_class_get_fields(void *k, void **iter);
extern void *il2cpp_class_from_type(void *t);
extern void *il2cpp_class_enum_basetype(void *k);
extern const char *il2cpp_field_get_name(void *f);
extern int il2cpp_field_get_flags(void *f);
extern void *il2cpp_field_get_type(void *f);
extern u64 il2cpp_field_get_offset(void *f);
extern void il2cpp_field_static_get_value(void *f, void *v);
extern int il2cpp_type_get_type(void *t);

static int tsize(int te) {
  switch (te) {
    case 0x02: case 0x04: case 0x05: return 1;
    case 0x03: case 0x06: case 0x07: return 2;
    case 0x08: case 0x09: case 0x0c: return 4;
    case 0x0a: case 0x0b: case 0x0d: case 0x18: case 0x19: return 8;
  }
  return 0;
}
static void putc1(St *s, char c) { if (s->len + 1 < s->cap) s->buf[s->len++] = c; }
static void put(St *s, const char *t) {
  if (!t) return;
  while (*t && s->len + 1 < s->cap) { char c = *t++; if (c == '\t' || c == '\n' || c == '\r') c = ' '; s->buf[s->len++] = c; }
}
static void puthex(St *s, u64 v) { const char *hx = "0123456789abcdef"; int i; for (i = 60; i >= 0; i -= 4) putc1(s, hx[(v >> i) & 15]); }
static void putint(St *s, u64 v) {
  char t[24]; int n = 0;
  if (!v) { putc1(s, '0'); return; }
  while (v && n < 23) { t[n++] = (char)('0' + (v % 10)); v /= 10; }
  while (n) putc1(s, t[--n]);
}
static int endswith(const char *a, const char *b) {
  int la = 0, lb = 0;
  while (a[la]) la++;
  while (b[lb]) lb++;
  if (lb > la) return 0;
  while (lb) { if (a[--la] != b[--lb]) return 0; }
  return 1;
}
static int streq(const char *a, const char *b) { if (!a || !b) return 0; while (*a && *a == *b) { a++; b++; } return *a == *b; }
static u64 rd(const unsigned char *p, int n) { u64 v = 0; int i; for (i = 0; i < n; i++) v |= ((u64)p[i]) << (8 * i); return v; }
static void putclass(St *s, void *k) {
  void *d = il2cpp_class_get_declaring_type(k);
  if (d) {
    void *dd = il2cpp_class_get_declaring_type(d);
    if (dd) { put(s, il2cpp_class_get_name(dd)); putc1(s, '/'); }
    put(s, il2cpp_class_get_name(d)); putc1(s, '/');
  }
  put(s, il2cpp_class_get_name(k));
}
static void putns(St *s, void *k) {
  void *top = k, *d; int i = 0;
  while ((d = il2cpp_class_get_declaring_type(top)) != 0 && i++ < 8) top = d;
  put(s, il2cpp_class_get_namespace(top));
}
static void head(St *s, void *k, const char *fn, char kind, int te, int ut) {
  putint(s, (u64)s->img); putc1(s, '\t'); putns(s, k); putc1(s, '\t'); putclass(s, k); putc1(s, '\t'); put(s, fn);
  putc1(s, '\t'); putc1(s, kind); putc1(s, '\t'); putint(s, (u64)te); putc1(s, '\t'); putint(s, (u64)ut); putc1(s, '\t');
}
static void do_class(St *s, void *k) {
  const char *cn = il2cpp_class_get_name(k);
  void *it = 0, *f;
  if (!cn || cn[0] == '<' || il2cpp_class_is_enum(k)) return;
  s->nclass++;
  while ((f = il2cpp_class_get_fields(k, &it)) != 0) {
    int fl = il2cpp_field_get_flags(f), te, ut, n;
    void *t; const char *fn; u64 v = 0;
    if (!(fl & 0x10)) continue;                                  /* static only */
    s->nfield++;
    fn = il2cpp_field_get_name(f);
    if (!fn || fn[0] == '<' || endswith(fn, "FieldNumber")) continue;
    t = il2cpp_field_get_type(f);
    if (!t) continue;
    te = il2cpp_type_get_type(t); ut = te;
    if (te == 0x11) {                                            /* enums by their base type, TimeSpan by ticks */
      void *ek = il2cpp_class_from_type(t);
      if (!ek) continue;
      if (il2cpp_class_is_enum(ek)) { void *bt = il2cpp_class_enum_basetype(ek); ut = bt ? il2cpp_type_get_type(bt) : 0x08; }
      else if (!(fl & 0x40) && streq(il2cpp_class_get_name(ek), "TimeSpan") && streq(il2cpp_class_get_namespace(ek), "System")) ut = 0x7f;
      else continue;
    }
    if (fl & 0x40) {                                             /* const: value from metadata, no class init */
      if (!tsize(ut)) continue;
      il2cpp_field_static_get_value(f, &v);
      head(s, k, fn, 'c', te, ut); puthex(s, v); putc1(s, '\n'); s->nconst++;
      continue;
    }
    if (!(fl & 0x20) || !s->sf_off || (fl & 0x100)) continue;   /* static readonly without RVA data */
    if (il2cpp_class_is_generic(k)) continue;
    {
      u64 off = il2cpp_field_get_offset(f);
      unsigned char *sf;
      if (off > 0x100000) continue;                              /* thread-static (-1) */
      sf = *(unsigned char **)((unsigned char *)k + s->sf_off);
      if (!sf) continue;                                         /* never initialized: no storage */
      if (ut == 0x7f) n = 8; else n = tsize(ut);
      if (n) {
        v = rd(sf + off, n);
        if (!v) continue;                                        /* zero = unset or not run yet */
        head(s, k, fn, 's', te, ut); puthex(s, v); putc1(s, '\n'); s->nstatic++;
        continue;
      }
      if (te == 0x1d) {                                          /* numeric array */
        void *et = *(void **)t; int es; u64 len, i; unsigned char *arr;
        if (!et) continue;
        ut = il2cpp_type_get_type(et); es = tsize(ut);
        if (!es) continue;
        arr = *(unsigned char **)(sf + off);
        if (!arr) continue;
        len = *(u64 *)(arr + 0x18);
        if (len == 0 || len > 1000000) continue;
        head(s, k, fn, 'a', te, ut); putint(s, len); putc1(s, ':');
        for (i = 0; i < len && i < 64; i++) { if (i) putc1(s, ','); puthex(s, rd(arr + 0x20 + i * es, es)); }
        putc1(s, '\n'); s->nstatic++;
      }
    }
  }
}
int step(St *s) {
  int budget = s->budget;
  while (s->img < s->nimg) {
    void *im = s->images[s->img];
    u64 n = il2cpp_image_get_class_count(im);
    while ((u64)s->cls < n) {
      void *k;
      if (budget-- <= 0) return 0;
      if (s->len + 65536 > s->cap) { s->full = 1; return 0; }
      k = il2cpp_image_get_class(im, (u64)s->cls);
      s->cls++;
      if (k) do_class(s, k);
    }
    s->img++; s->cls = 0;
  }
  s->done = 1;
  return 1;
}
"""

JS = r"""
var PROP = {exceptions: 'propagate'}, PS = Process.pointerSize;
var EX = {}; Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function (x) { EX[x.name] = x.address; });
function f(n, r, a) { if (!EX[n]) throw new Error('missing export ' + n); return new NativeFunction(EX[n], r, a, PROP); }
function cs(p) { try { return p.isNull() ? '' : p.readCString(); } catch (e) { return ''; } }
var IL = {
  domain: f('il2cpp_domain_get', 'pointer', []), asms: f('il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']),
  asmImage: f('il2cpp_assembly_get_image', 'pointer', ['pointer']), imageName: f('il2cpp_image_get_name', 'pointer', ['pointer']),
  classCount: f('il2cpp_image_get_class_count', 'uint32', ['pointer']),
  fromName: f('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']),
  fieldByName: f('il2cpp_class_get_field_from_name', 'pointer', ['pointer', 'pointer']),
  fieldOffset: f('il2cpp_field_get_offset', 'uint32', ['pointer'])
};
var IMGS = [];
function images() {
  var sp = Memory.alloc(8); sp.writeU64(0);
  var a = IL.asms(IL.domain(), sp), n = sp.readU32(), out = [];
  for (var i = 0; i < n; i++) { var im = IL.asmImage(a.add(i * PS).readPointer()); out.push({im: im, name: cs(IL.imageName(im)), classes: IL.classCount(im)}); }
  return out;
}
/* Il2CppClass.static_fields: found, not assumed -- the one pointer inside UnityEngine.Vector3 whose storage holds
   up=(0,1,0), one=(1,1,1) and forward=(0,0,1) at those fields' offsets. Memory reads only (they throw, not crash). */
function staticFieldsOffset(core) {
  var k = IL.fromName(core, Memory.allocUtf8String('UnityEngine'), Memory.allocUtf8String('Vector3'));
  if (k.isNull()) return {err: 'no Vector3'};
  function off(n) { var fd = IL.fieldByName(k, Memory.allocUtf8String(n)); return fd.isNull() ? -1 : IL.fieldOffset(fd); }
  var up = off('upVector'), one = off('oneVector'), fwd = off('forwardVector');
  if (up < 0 || one < 0 || fwd < 0) return {err: 'Vector3 static fields missing'};
  function v3(p) { return [p.readFloat(), p.add(4).readFloat(), p.add(8).readFloat()].join(','); }
  var hits = [];
  for (var o = 0x60; o <= 0x180; o += 8) {
    try {
      var p = k.add(o).readPointer();
      if (p.compare(ptr(0x100000)) < 0) continue;
      if (v3(p.add(up)) === '0,1,0' && v3(p.add(one)) === '1,1,1' && v3(p.add(fwd)) === '0,0,1') hits.push(o);
    } catch (e) {}
  }
  return {hits: hits};
}
var CM = null, STEP = null, ST = null, BUF = null, CAP = 8 * 1024 * 1024;
rpc.exports = {
  probe: function () {
    IMGS = images();
    var core = IMGS.filter(function (x) { return x.name === 'UnityEngine.CoreModule.dll'; })[0];
    return {images: IMGS.map(function (x) { return [x.name, x.classes]; }), sf: core ? staticFieldsOffset(core.im) : {err: 'no CoreModule'},
            exports: Object.keys(EX).filter(function (n) { return /static_field|class_is_inited|enum_basetype|class_is_generic/.test(n); })};
  },
  start: function (idxs, sfOff, budget) {
    var syms = {};
    ['il2cpp_image_get_class', 'il2cpp_image_get_class_count', 'il2cpp_class_get_name', 'il2cpp_class_get_namespace',
     'il2cpp_class_get_declaring_type', 'il2cpp_class_is_enum', 'il2cpp_class_is_generic', 'il2cpp_class_get_fields',
     'il2cpp_class_from_type', 'il2cpp_class_enum_basetype', 'il2cpp_field_get_name', 'il2cpp_field_get_flags',
     'il2cpp_field_get_type', 'il2cpp_field_get_offset', 'il2cpp_field_static_get_value', 'il2cpp_type_get_type'].forEach(function (n) {
      if (!EX[n]) throw new Error('missing export ' + n); syms[n] = EX[n]; });
    CM = new CModule(%C_SRC%, syms);
    STEP = new NativeFunction(CM.step, 'int', ['pointer'], PROP);
    var arr = Memory.alloc(PS * idxs.length);
    idxs.forEach(function (ix, i) { arr.add(i * PS).writePointer(IMGS[ix].im); });
    BUF = Memory.alloc(CAP); ST = Memory.alloc(96);
    ST.writePointer(BUF); ST.add(8).writeU64(CAP); ST.add(16).writeU64(0); ST.add(24).writePointer(arr);
    ST.add(32).writeS32(idxs.length); ST.add(36).writeS32(0); ST.add(40).writeS32(0); ST.add(44).writeS32(budget);
    ST.add(48).writeU64(sfOff); ST.add(56).writeS32(0); ST.add(60).writeS32(0);
    for (var o = 64; o < 96; o += 8) ST.add(o).writeU64(0);
    this.arr = arr;   /* keep the image array alive */
    return true;
  },
  step: function () {
    var t = Date.now(), r = STEP(ST), ms = Date.now() - t;
    var len = ST.add(16).readU64().toNumber(), text = len ? BUF.readUtf8String(len) : '';
    ST.add(16).writeU64(0); ST.add(60).writeS32(0);
    return {done: r, ms: ms, img: ST.add(36).readS32(), cls: ST.add(40).readS32(), text: text,
            n: [ST.add(64).readU64().toNumber(), ST.add(72).readU64().toNumber(), ST.add(80).readU64().toNumber(), ST.add(88).readU64().toNumber()]};
  }
};
""".replace("%C_SRC%", json.dumps(C_SRC))

SIGNED = {0x04: 8, 0x06: 16, 0x08: 32, 0x0a: 64, 0x18: 64}
SIZE = {0x02: 1, 0x03: 2, 0x04: 1, 0x05: 1, 0x06: 2, 0x07: 2, 0x08: 4, 0x09: 4, 0x0a: 8, 0x0b: 8, 0x0c: 4, 0x0d: 8, 0x18: 8, 0x19: 8, 0x7f: 8}
TYPE = {0x02: "bool", 0x03: "char", 0x04: "sbyte", 0x05: "byte", 0x06: "short", 0x07: "ushort", 0x08: "int", 0x09: "uint",
        0x0a: "long", 0x0b: "ulong", 0x0c: "float", 0x0d: "double", 0x18: "nint", 0x19: "nuint", 0x7f: "TimeSpan"}


def decode(ut, raw):
    if ut == 0x0c:
        return round(struct.unpack("<f", struct.pack("<I", raw & 0xffffffff))[0], 7)
    if ut == 0x0d:
        return struct.unpack("<d", struct.pack("<Q", raw))[0]
    if ut == 0x02:
        return bool(raw & 0xff)
    if ut == 0x7f:
        return {"seconds": (raw - (1 << 64) if raw >> 63 else raw) / 1e7}
    bits = SIGNED.get(ut)
    if bits:
        raw &= (1 << bits) - 1
        return raw - (1 << bits) if raw >> (bits - 1) else raw
    return raw & ((1 << (8 * SIZE.get(ut, 8))) - 1)


def main():
    sess, pid = pg.get_session()
    print(f"attached pid {pid}")
    sc = sess.create_script(JS)
    sc.load()
    pr = sc.exports_sync.probe()
    imgs = pr["images"]
    print(f"{len(imgs)} images; exports: {pr['exports']}; static_fields probe: {pr['sf']}")
    hits = (pr.get("sf") or {}).get("hits") or []
    sf_off = hits[0] if len(hits) == 1 else 0
    print(f"static readonly reads: {'ON, Il2CppClass.static_fields @0x%x' % sf_off if sf_off else 'OFF (offset not proven)'}")
    idxs = [i for i, (name, n) in enumerate(imgs) if not SKIP_IMAGES.search(name)]
    print("walking: " + ", ".join(f"{imgs[i][0]}({imgs[i][1]})" for i in idxs))
    sc.exports_sync.start(idxs, sf_off, 1500)
    rows, t0, steps, slow = [], time.time(), 0, 0
    while True:
        r = sc.exports_sync.step()
        steps += 1
        slow = max(slow, r["ms"])
        for line in r["text"].splitlines():
            p = line.split("\t")
            if len(p) != 8:
                continue
            img, ns, cls, fld, kind, te, ut, val = p
            te, ut = int(te), int(ut)
            if kind == "a":
                n, _, hv = val.partition(":")
                v = {"count": int(n), "values": [decode(ut, int(h, 16)) for h in hv.split(",") if h]}
            else:
                v = decode(ut, int(val, 16))
            rows.append({"image": imgs[idxs[int(img)]][0], "ns": ns, "class": cls, "field": fld,
                         "kind": {"c": "const", "s": "static readonly", "a": "static readonly array"}[kind],
                         "type": ("enum:" if te == 0x11 and ut != 0x7f else "") + TYPE.get(ut, hex(ut)) + ("[]" if kind == "a" else ""),
                         "value": v})
        if r["done"]:
            break
        if steps % 20 == 0:
            print(f"  step {steps}: image {r['img']} class {r['cls']} rows {len(rows)} (slowest step {slow} ms)")
    n = r["n"]
    print(f"done in {time.time() - t0:.1f}s, {steps} steps, slowest {slow} ms: {n[0]} classes, {n[1]} static fields, "
          f"{n[2]} consts, {n[3]} static readonly values")
    sc.unload()
    sess.detach()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"pid": pid, "read_at": time.strftime("%Y-%m-%d %H:%M:%S"), "static_fields_offset": sf_off,
                   "images": [imgs[i] for i in idxs], "constants": rows}, fh, indent=0)
    print(f"wrote {OUT} ({os.path.getsize(OUT) // 1024} KB, {len(rows)} values)")


if __name__ == "__main__":
    main()
