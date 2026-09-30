"""Dump the LIVE game's complete il2cpp metadata: every class, method and field offset.

WHY. Every hook we write has to name a class and a method that actually exist in the build the
user is running. Our previous feature specs came from a 3-month-old copy of somebody else's
agent, and a hook aimed at a renamed or removed method is exactly how this project has frozen
the game before. This dump is ground truth for the CURRENT binary, so ports can be verified
against it instead of trusted.

SAFETY. This walks METADATA only (class/method/field descriptors). It never dereferences a
managed object, so the moving collector is not a concern. It attaches its own il2cpp thread,
which the runtime requires before any il2cpp_* call from a foreign thread.

Output: system/analysis/clone/il2cpp_meta.jsonl.gz  (one JSON object per class)
"""
import frida
import gzip
import json
import os
import sys
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "system", "analysis", "clone", "il2cpp_meta.jsonl.gz")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

JS = r"""
const EXPORTS = [
  'il2cpp_domain_get','il2cpp_thread_attach','il2cpp_domain_get_assemblies',
  'il2cpp_assembly_get_image','il2cpp_image_get_class_count','il2cpp_image_get_class',
  'il2cpp_image_get_name','il2cpp_class_get_name','il2cpp_class_get_namespace',
  'il2cpp_class_get_methods','il2cpp_method_get_name','il2cpp_method_get_param_count',
  'il2cpp_class_get_fields','il2cpp_field_get_name','il2cpp_field_get_offset',
  'il2cpp_class_get_parent','il2cpp_class_get_nested_types'
];
function resolve() {
  // Frida 17 removed Module.findExportByName, so go through the module object.
  const m = Process.findModuleByName('libil2cpp.so');
  if (m === null) throw new Error('libil2cpp.so not loaded');
  const want = new Set(EXPORTS), out = {};
  for (const e of m.enumerateExports()) if (want.has(e.name)) out[e.name] = e.address;
  const missing = EXPORTS.filter(n => !(n in out));
  if (missing.length) throw new Error('missing exports: ' + missing.join(','));
  return out;
}
const A = resolve();
const fn = (n, ret, args) => new NativeFunction(A[n], ret, args);
const domain_get        = fn('il2cpp_domain_get','pointer',[]);
const thread_attach     = fn('il2cpp_thread_attach','pointer',['pointer']);
const get_assemblies    = fn('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
const assembly_image    = fn('il2cpp_assembly_get_image','pointer',['pointer']);
const image_class_count = fn('il2cpp_image_get_class_count','int',['pointer']);
const image_get_class   = fn('il2cpp_image_get_class','pointer',['pointer','int']);
const image_get_name    = fn('il2cpp_image_get_name','pointer',['pointer']);
const class_name        = fn('il2cpp_class_get_name','pointer',['pointer']);
const class_ns          = fn('il2cpp_class_get_namespace','pointer',['pointer']);
const class_methods     = fn('il2cpp_class_get_methods','pointer',['pointer','pointer']);
const method_name       = fn('il2cpp_method_get_name','pointer',['pointer']);
const method_pcount     = fn('il2cpp_method_get_param_count','int',['pointer']);
const class_fields      = fn('il2cpp_class_get_fields','pointer',['pointer','pointer']);
const field_name        = fn('il2cpp_field_get_name','pointer',['pointer']);
const field_offset      = fn('il2cpp_field_get_offset','int',['pointer']);
const class_parent      = fn('il2cpp_class_get_parent','pointer',['pointer']);
const class_nested      = fn('il2cpp_class_get_nested_types','pointer',['pointer','pointer']);
const cstr = p => (p.isNull() ? null : p.readUtf8String());

function dumpAll() {
  const domain = domain_get();
  thread_attach(domain);                       // required before any il2cpp_* from a foreign thread
  const nptr = Memory.alloc(8);
  const asmv = get_assemblies(domain, nptr);
  const ncount = nptr.readUInt();
  send({t: 'begin', assemblies: ncount});
  let batch = [], total = 0;
  for (let i = 0; i < ncount; i++) {
    const asm = asmv.add(i * Process.pointerSize).readPointer();
    if (asm.isNull()) continue;
    const img = assembly_image(asm);
    if (img.isNull()) continue;
    const imgName = cstr(image_get_name(img));
    const cc = image_class_count(img);
    /* il2cpp_image_get_class only yields TOP-LEVEL types. Nested ones (Button/ButtonClickedEvent,
       TextInputDialog/Data, Toggle/ToggleEvent -- every event and factory type the menu code
       touches) were absent from every dump before 2026-09-06, so a hook table naming one could not
       be checked against this oracle at all. Recurse into il2cpp_class_get_nested_types and record
       them as "Outer/Nested", which is exactly how Pokemod's own code spells them. */
    const emit = (k, namePrefix, depth) => {
      const rec = {img: imgName, ns: null, n: null, p: null, m: [], f: []};
      let nested = [];
      try {
        rec.ns = cstr(class_ns(k));
        const own = cstr(class_name(k));
        rec.n = namePrefix ? (namePrefix + '/' + own) : own;
        const par = class_parent(k);
        if (!par.isNull()) rec.p = cstr(class_name(par));
        const it = Memory.alloc(Process.pointerSize); it.writePointer(NULL);
        for (;;) {
          const meth = class_methods(k, it);
          if (meth.isNull()) break;
          rec.m.push([cstr(method_name(meth)), method_pcount(meth), meth.toString()]);
        }
        const it2 = Memory.alloc(Process.pointerSize); it2.writePointer(NULL);
        for (;;) {
          const fld = class_fields(k, it2);
          if (fld.isNull()) break;
          rec.f.push([cstr(field_name(fld)), field_offset(fld)]);
        }
        if (depth < 3) {
          const it3 = Memory.alloc(Process.pointerSize); it3.writePointer(NULL);
          for (;;) {
            const nk = class_nested(k, it3);
            if (nk.isNull()) break;
            nested.push(nk);
          }
        }
      } catch (e) { rec.err = String(e); }
      batch.push(rec); total++;
      if (batch.length >= 400) { send({t: 'batch', d: batch}); batch = []; }
      for (let n = 0; n < nested.length; n++) {
        try { emit(nested[n], rec.n, depth + 1); } catch (e) { /* one bad nested type is not fatal */ }
      }
    };

    for (let c = 0; c < cc; c++) {
      let k;
      try { k = image_get_class(img, c); } catch (e) { continue; }
      if (k === null || k.isNull()) continue;
      emit(k, null, 0);
    }
  }
  if (batch.length) send({t: 'batch', d: batch});
  send({t: 'done', classes: total});
}
rpc.exports.go = function () {
  // House rule: never touch il2cpp from the RPC thread. Hand off and return immediately.
  setImmediate(() => {
    try { dumpAll(); } catch (e) { send({t: 'fatal', e: String(e), stack: String(e.stack)}); }
  });
  return 'started';
};
"""

done = threading.Event()
state = {"classes": 0, "batches": 0, "err": None}
gz = gzip.open(OUT, "wt", encoding="utf-8")


def on_message(msg, data):
    if msg.get("type") == "error":
        state["err"] = str(msg.get("description")) + "\n" + str(msg.get("stack"))
        done.set()
        return
    p = msg.get("payload") or {}
    t = p.get("t")
    if t == "begin":
        print("  assemblies: %d" % p["assemblies"], flush=True)
    elif t == "batch":
        try:
            for rec in (p.get("d") or []):
                gz.write(json.dumps(rec, separators=(",", ":")) + "\n")
                state["classes"] += 1
        except Exception as e:
            state["err"] = "batch decode: %s" % e
            done.set()
            return
        state["batches"] += 1
        if state["batches"] % 10 == 0:
            print("  %d classes..." % state["classes"], flush=True)
    elif t == "done":
        print("  DONE %d classes" % p["classes"], flush=True)
        done.set()
    elif t == "fatal":
        state["err"] = str(p.get("e")) + "\n" + str(p.get("stack"))
        done.set()


dev = frida.get_device_manager().add_remote_device("127.0.0.1:27047")
ses = dev.attach("Gadget")
scr = ses.create_script(JS)
scr.on("message", on_message)
scr.load()
print("script loaded; starting dump", flush=True)
print(" ", scr.exports_sync.go(), flush=True)
done.wait(timeout=2400)
gz.close()
if state["err"]:
    print("ERROR:", state["err"][:2000])
    sys.exit(1)
print("wrote %s  (%d bytes, %d classes)" % (OUT, os.path.getsize(OUT), state["classes"]))
