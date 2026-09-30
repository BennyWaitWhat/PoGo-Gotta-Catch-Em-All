"""Bulk-release PoGo pokemon via PokemonBagImpl.ReleasePokemon (or its overload).

Phase 1 (probe, always runs): enumerate PokemonBagImpl + IPokemonBag methods,
                              find ReleasePokemon overload(s), report signatures.
Phase 2 (inventory): read CLAUDE_TX binding from TaggingRpcService to get UID list,
                     or accept --uids-file with one UID per line.
Phase 3 (safety):    default is --dry-run. --execute additionally requires the
                     interactive prompt "TYPE TRANSFER TO CONTINUE".
Phase 4 (pacing):    batches of --batch-size (default 22) with --batch-gap
                     seconds between batches (default 4.0).

Usage:
  python bulk_release.py                       # dry-run, probe only
  python bulk_release.py --dry-run             # explicit dry-run
  python bulk_release.py --execute             # actually transfer (asks for confirm)
  python bulk_release.py --execute --uids-file claudetx_uids.txt

Reads UIDs from --uids-file if provided, otherwise pulls live from CLAUDE_TX
binding (TaggingRpcService.GetCachedTagToPokemonBindingForIndex).
"""

import argparse
import json
import sys
import time

import pogo_il2cpp as pg


PROBE_JS = r"""
var STATE = {ready:false, err:null};

function _img(name) {
    _ensureInit();
    var sp = Memory.alloc(4);
    var asms = IL2.dGA(IL2.dG(), sp);
    var na = sp.readS32();
    for (var a = 0; a < na; a++) {
        var img = IL2.aGI(asms.add(a * Process.pointerSize).readPointer());
        if (IL2.iGN(img).readCString() === name) return img;
    }
    return null;
}

function _bindExtra() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){
        if (e.name.indexOf('il2cpp_') === 0) exp[e.name] = e.address;
    });
    function bind(n, ret, args) { return exp[n] ? new NativeFunction(exp[n], ret, args) : null; }
    return {
        mGPC: bind('il2cpp_method_get_param_count','int',['pointer']),
        mGP:  bind('il2cpp_method_get_param','pointer',['pointer','int']),
        mGPN: bind('il2cpp_method_get_param_name','pointer',['pointer','int']),
        mGRT: bind('il2cpp_method_get_return_type','pointer',['pointer']),
        tGN:  bind('il2cpp_type_get_name','pointer',['pointer']),
        cFT:  bind('il2cpp_class_from_type','pointer',['pointer']),
        cN:   bind('il2cpp_class_get_name','pointer',['pointer']),
        cGNs: bind('il2cpp_class_get_namespace','pointer',['pointer']),
        cGF:  bind('il2cpp_class_get_fields','pointer',['pointer','pointer']),
        fGN:  bind('il2cpp_field_get_name','pointer',['pointer']),
        fGT:  bind('il2cpp_field_get_type','pointer',['pointer']),
        fGO:  bind('il2cpp_field_get_offset','uint32',['pointer']),
    };
}

function _dumpMethods(klass) {
    var x = _bindExtra();
    var out = [];
    if (!klass || klass.isNull()) return out;
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = IL2.cGM(klass, iter)) && !m.isNull()) {
        try {
            var name = IL2.mGN(m).readCString();
            var pc = x.mGPC(m);
            var params = [];
            for (var i = 0; i < pc; i++) {
                var pt = x.mGP(m, i);
                var pn = x.mGPN(m, i);
                params.push({
                    type: (pt && !pt.isNull()) ? x.tGN(pt).readCString() : '?',
                    name: (pn && !pn.isNull()) ? pn.readCString() : ('p'+i)
                });
            }
            var rt = x.mGRT(m);
            out.push({
                name: name,
                ptr: m.toString(),
                paramCount: pc,
                params: params,
                ret: (rt && !rt.isNull()) ? x.tGN(rt).readCString() : 'void'
            });
        } catch(e) {}
    }
    return out;
}

function _dumpFields(klass) {
    var x = _bindExtra();
    var out = [];
    if (!klass || klass.isNull()) return out;
    if (!x.cGF) return out;
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var f;
    while ((f = x.cGF(klass, iter)) && !f.isNull()) {
        try {
            out.push({
                name: x.fGN(f).readCString(),
                type: x.tGN(x.fGT(f)).readCString(),
                offset: '0x' + x.fGO(f).toString(16)
            });
        } catch(e) {}
    }
    return out;
}

rpc.exports.probeRelease = function() {
    _ensureInit();
    var result = {classes: {}};

    var classesToCheck = [
        ['Niantic.Holoholo.Internal','PokemonBagImpl'],
        ['Niantic.Holoholo','IPokemonBag'],
        ['Niantic.Holoholo.Services','IPokemonBagService'],
        ['Niantic.Holoholo.Services','PokemonBagService']
    ];
    for (var i = 0; i < classesToCheck.length; i++) {
        var ns = classesToCheck[i][0], cn = classesToCheck[i][1];
        var k = cFN(ns, cn);
        if (!k || k.isNull()) {
            result.classes[ns + '.' + cn] = {found:false};
            continue;
        }
        var allMethods = _dumpMethods(k);
        var releaseHits = allMethods.filter(function(m){
            var n = m.name.toLowerCase();
            return n.indexOf('release') >= 0 || n.indexOf('transfer') >= 0;
        });
        result.classes[ns + '.' + cn] = {
            found: true,
            klass: k.toString(),
            methodCount: allMethods.length,
            releaseMethods: releaseHits,
            allMethodNames: allMethods.map(function(m){return m.name;})
        };
    }

    // Also probe ReleasePokemonProto / OutProto field layout
    var protoImg = _img('holo-protos.dll');
    if (protoImg) {
        var rpKlass = IL2.cFN(protoImg,
            Memory.allocUtf8String('Holoholo.Rpc'),
            Memory.allocUtf8String('ReleasePokemonProto'));
        if (rpKlass && !rpKlass.isNull()) {
            result.releasePokemonProto = {
                klass: rpKlass.toString(),
                fields: _dumpFields(rpKlass),
                methods: _dumpMethods(rpKlass).map(function(m){return {name:m.name, ret:m.ret, paramCount:m.paramCount};})
            };
        } else {
            result.releasePokemonProto = {found:false};
        }
        var ropKlass = IL2.cFN(protoImg,
            Memory.allocUtf8String('Holoholo.Rpc'),
            Memory.allocUtf8String('ReleasePokemonOutProto'));
        if (ropKlass && !ropKlass.isNull()) {
            result.releasePokemonOutProto = {
                klass: ropKlass.toString(),
                fields: _dumpFields(ropKlass)
            };
        } else {
            result.releasePokemonOutProto = {found:false};
        }
    }
    return result;
};

rpc.exports.findBagSingleton = function() {
    _ensureInit();
    var bagCls = cFN('Niantic.Holoholo.Internal', 'PokemonBagImpl');
    if (!bagCls || bagCls.isNull()) return {err:'PokemonBagImpl class not found'};
    var r = liveness_find_instances(bagCls);
    if (r.err) return r;
    return {hits: r.hits};
};

rpc.exports.dumpClaudeTxBinding = function(serviceAddrStr, tagName) {
    _ensureInit();
    var svc = ptr(serviceAddrStr);
    var x = _bindExtra();
    var taggingCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    if (!taggingCls || taggingCls.isNull()) return {err:'TaggingRpcService not found'};

    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, getCount=null, getBinding=null;
    while ((m = IL2.cGM(taggingCls, iter)) && !m.isNull()) {
        var nm = IL2.mGN(m).readCString();
        if (nm === 'get_NumberOfTags') getCount = m;
        if (nm === 'GetCachedTagToPokemonBindingForIndex') getBinding = m;
    }
    if (!getCount || !getBinding) return {err:'tag methods missing'};

    var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
    var ret = rI(getCount, svc, ptr(0), exc);
    var totalTags = ret.add(0x10).readS32();

    var targetIdx = -1;
    for (var i = 0; i < totalTags; i++) {
        var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
        var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
        var ex2 = Memory.alloc(Process.pointerSize); ex2.writePointer(ptr(0));
        var bp = rI(getBinding, svc, args, ex2);
        if (!ex2.readPointer().isNull() || bp.isNull()) continue;
        try {
            var tagProto = bp.add(0x10).readPointer();
            if (tagProto.isNull()) continue;
            var nsp = tagProto.add(0x40).readPointer();
            if (nsp.isNull()) continue;
            var len = nsp.add(0x10).readS32();
            if (len <= 0 || len > 100) continue;
            var chars = [];
            for (var ci = 0; ci < len; ci++)
                chars.push(String.fromCharCode(nsp.add(0x14 + ci*2).readU16()));
            var s = chars.join('');
            if (s === tagName) { targetIdx = i; break; }
        } catch(e) {}
    }
    if (targetIdx < 0) return {err:'tag not found: ' + tagName};

    var idxBuf2 = Memory.alloc(4); idxBuf2.writeS32(targetIdx);
    var args2 = Memory.alloc(Process.pointerSize); args2.writePointer(idxBuf2);
    var ex3 = Memory.alloc(Process.pointerSize); ex3.writePointer(ptr(0));
    var bpFinal = rI(getBinding, svc, args2, ex3);
    var listPtr = bpFinal.add(0x18).readPointer();
    if (listPtr.isNull()) return {err:'binding list null'};
    var count = listPtr.add(0x18).readS32();
    var items = listPtr.add(0x10).readPointer();
    var uids = [];
    for (var i = 0; i < count; i++) {
        try {
            var proto = items.add(0x20 + i*8).readPointer();
            if (proto.isNull()) continue;
            var lo = proto.add(32).readS32();
            var hi = proto.add(36).readS32();
            var uidBn = (BigInt(hi) << 32n) | (BigInt(lo) & 0xFFFFFFFFn);
            uids.push(uidBn.toString());
        } catch(e) {}
    }
    return {ok:true, idx:targetIdx, count:count, uids:uids};
};

rpc.exports.locateTaggingService = function() {
    _ensureInit();
    var cls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    if (!cls || cls.isNull()) return {err:'TaggingRpcService class missing'};
    var r = liveness_find_instances(cls);
    if (r.err) return r;
    return {hits: r.hits};
};
"""

EXECUTE_JS = r"""
// Builds + invokes ReleasePokemon. Shapes:
//   shape = 'pokemon_proto' -> ReleasePokemon(PokemonProto) - requires proto ptr per UID
//   shape = 'uid'           -> ReleasePokemon(ulong uid)
//   shape = 'list'          -> ReleasePokemon(List<ulong> uids)
//   shape = 'release_proto' -> ReleasePokemon(ReleasePokemonProto proto)
//
// Result returns IPromise<ReleasePokemonOutProto>. The promise is async-resolved
// by the game's HTTP layer. We capture the promise pointer; the actual Status
// can be read after the promise resolves (poll, or hook the .Resolve callback).

var RELEASE_METHOD = null;
var RELEASE_SHAPE = null;
var BAG_INSTANCE = null;
var STATUS_OFFSET = null;

rpc.exports.prepRelease = function(opts) {
    _ensureInit();
    RELEASE_METHOD = ptr(opts.methodPtr);
    RELEASE_SHAPE = opts.shape;
    BAG_INSTANCE = ptr(opts.bagAddr);
    STATUS_OFFSET = opts.statusOffsetHex ? parseInt(opts.statusOffsetHex, 16) : null;
    return {ok:true, method: RELEASE_METHOD.toString(), shape: RELEASE_SHAPE, bag: BAG_INSTANCE.toString(), statusOff: STATUS_OFFSET};
};

rpc.exports.releaseByProto = function(protoAddrStr) {
    if (!RELEASE_METHOD) return {err:'not primed'};
    if (RELEASE_SHAPE !== 'pokemon_proto') return {err:'shape mismatch: ' + RELEASE_SHAPE};
    var exp = {};
    Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function(e){
        if (e.name.indexOf('il2cpp_') === 0) exp[e.name] = e.address;
    });
    var rI = new NativeFunction(exp.il2cpp_runtime_invoke,'pointer',['pointer','pointer','pointer','pointer']);
    var protoPtr = ptr(protoAddrStr);
    var args = Memory.alloc(Process.pointerSize);
    args.writePointer(protoPtr);
    var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
    var promise = rI(RELEASE_METHOD, BAG_INSTANCE, args, exc);
    var excPtr = exc.readPointer();
    if (!excPtr.isNull()) return {err:'exception', excPtr:excPtr.toString()};
    return {ok:true, protoAddr: protoAddrStr, promise: promise ? promise.toString() : null};
};

rpc.exports.releaseSingle = function(uidStr) {
    if (!RELEASE_METHOD) return {err:'not primed'};
    if (RELEASE_SHAPE !== 'uid') return {err:'shape mismatch: ' + RELEASE_SHAPE};
    var exp = {};
    Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function(e){
        if (e.name.indexOf('il2cpp_') === 0) exp[e.name] = e.address;
    });
    var rI = new NativeFunction(exp.il2cpp_runtime_invoke,'pointer',['pointer','pointer','pointer','pointer']);
    var uidBuf = Memory.alloc(8);
    var bn = BigInt(uidStr);
    var lo32 = Number(bn & 0xFFFFFFFFn);
    var hi32 = Number((bn >> 32n) & 0xFFFFFFFFn);
    uidBuf.writeU32(lo32);
    uidBuf.add(4).writeU32(hi32);
    var args = Memory.alloc(Process.pointerSize);
    args.writePointer(uidBuf);
    var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
    var outProto = rI(RELEASE_METHOD, BAG_INSTANCE, args, exc);
    var excPtr = exc.readPointer();
    if (!excPtr.isNull()) return {err:'exception', excPtr:excPtr.toString()};
    var status = null;
    if (outProto && !outProto.isNull() && STATUS_OFFSET != null) {
        try { status = outProto.add(STATUS_OFFSET).readS32(); } catch(e) {}
    }
    return {ok:true, uid:uidStr, outProto: outProto ? outProto.toString() : null, status: status};
};
"""


def render_param_signature(method):
    parts = []
    for p in method.get("params", []):
        parts.append(f"{p.get('type','?')} {p.get('name','?')}")
    return f"{method.get('ret','void')} {method['name']}({', '.join(parts)})"


def pick_release_shape(release_methods):
    """Examine the probed release methods and decide which overload to use.

    Returns: dict with keys {shape, method, reason}, or {error: ...}.

    Shape detection:
      - 1 param, type containing 'PokemonProto' (not Release...Proto)  -> 'pokemon_proto' (per-uid, requires bag walk)
      - 1 param, type containing 'UInt64'/'Int64'/'ulong'/'long'  -> 'uid'
      - 1 param, type containing 'ReleasePokemonProto'            -> 'release_proto' (bulk RPC proto)
      - 1 param, type containing 'List' + UInt64/Int64            -> 'list'
    """
    candidates = []
    for m in release_methods:
        name_lower = m["name"].lower()
        if "release" not in name_lower:
            continue
        if m["paramCount"] == 1:
            p = m["params"][0]
            ptype = p["type"]
            if "ReleasePokemonProto" in ptype:
                candidates.append((m, "release_proto", f"single-param ReleasePokemonProto: {ptype}"))
            elif "PokemonProto" in ptype:
                candidates.append((m, "pokemon_proto", f"single-param PokemonProto (per-pokemon): {ptype}"))
            elif "List" in ptype and ("UInt64" in ptype or "Int64" in ptype or "ulong" in ptype or "long" in ptype):
                candidates.append((m, "list", f"single-param list-of-ulong: {ptype}"))
            elif "UInt64" in ptype or "Int64" in ptype or "ulong" in ptype or "long" in ptype:
                candidates.append((m, "uid", f"single-param scalar uid: {ptype}"))
        elif m["paramCount"] == 2:
            ptypes = [p["type"] for p in m["params"]]
            if any("PokemonProto" in t for t in ptypes) and any(
                "UInt64" in t or "Int64" in t for t in ptypes
            ):
                candidates.append(
                    (m, "uid", f"2-param (proto,uid): {ptypes}; uses uid path")
                )
    if not candidates:
        return {"error": "no Release* methods matched a known shape"}
    # Prefer impl on PokemonBagImpl over interface (interface methods are abstract stubs).
    # Within shape, prefer 'release_proto' (bulk), then 'list', then 'pokemon_proto', then 'uid'.
    pref = {"release_proto": 0, "list": 1, "pokemon_proto": 2, "uid": 3}
    def sort_key(c):
        method, shape, _reason = c
        # Heuristic: methods on the *Impl class tend to have larger ptr ranges,
        # but more reliably we can check if it lives in holo-game (we can't easily here),
        # so just rely on probe phase iterating PokemonBagImpl first.
        return pref.get(shape, 99)
    candidates.sort(key=sort_key)
    chosen = candidates[0]
    return {"shape": chosen[1], "method": chosen[0], "reason": chosen[2]}


def status_offset_from_outproto(probe_result):
    """Find the offset of the 'status' field of ReleasePokemonOutProto.

    Returns hex string ('0x18') or None if unknown.
    """
    op = probe_result.get("releasePokemonOutProto", {})
    if not op or not op.get("fields"):
        return None
    for f in op["fields"]:
        n = f["name"].lower()
        if n.startswith("status") or n in ("status_", "result_", "result"):
            return f["offset"]
    return None


def read_uids_from_file(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            uid_str = ln.split(",")[0].strip().split()[0]
            int(uid_str)
            out.append(uid_str)
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True)
    g.add_argument(
        "--execute",
        action="store_true",
        help="Actually invoke ReleasePokemon. Requires interactive confirmation.",
    )
    ap.add_argument(
        "--uids-file",
        help="File with one UID (decimal) per line. If omitted, pulls live CLAUDE_TX tag.",
    )
    ap.add_argument("--tag-name", default="CLAUDE_TX")
    ap.add_argument(
        "--batch-size", type=int, default=22, help="UIDs per batch (default 22)"
    )
    ap.add_argument(
        "--batch-gap",
        type=float,
        default=4.0,
        help="Seconds between batches (default 4.0)",
    )
    ap.add_argument(
        "--per-call-gap",
        type=float,
        default=0.15,
        help="Seconds between individual ReleasePokemon invocations within a batch",
    )
    ap.add_argument(
        "--probe-only",
        action="store_true",
        help="Stop after probe phase; do not even fetch UIDs.",
    )
    ap.add_argument("--save-probe", default="release_probe.json")
    args = ap.parse_args()

    print("[bulk_release] phase 1: connecting + attaching to PoGo")
    sess, pid = pg.get_session()
    print(f"[bulk_release] attached pid={pid}")

    script = pg.get_script_with_helpers(sess, PROBE_JS)
    try:
        print(f"[bulk_release] phase 1: probing PokemonBagImpl for Release* methods")
        probe = script.exports_sync.probe_release()
        with open(args.save_probe, "w", encoding="utf-8") as f:
            json.dump(probe, f, indent=2)
        print(f"[bulk_release] probe saved to {args.save_probe}")

        # Report findings
        print()
        print("=" * 70)
        print("PROBE RESULTS")
        print("=" * 70)
        for fqcn, info in probe.get("classes", {}).items():
            print(f"\n--- {fqcn} ---")
            if not info.get("found"):
                print("  NOT FOUND")
                continue
            print(
                f"  klass={info['klass']}  methodCount={info['methodCount']}"
            )
            rels = info.get("releaseMethods", [])
            if not rels:
                print("  no Release*/Transfer* methods on this class")
            else:
                for m in rels:
                    print(f"  * {render_param_signature(m)}")
                    print(f"      ptr={m['ptr']}  paramCount={m['paramCount']}")

        if probe.get("releasePokemonProto"):
            print("\n--- Holoholo.Rpc.ReleasePokemonProto fields ---")
            rp = probe["releasePokemonProto"]
            if rp.get("found") is False:
                print("  NOT FOUND in holo-protos.dll")
            else:
                for f in rp.get("fields", []):
                    print(f"  {f['offset']:>6}  {f['type']:<40}  {f['name']}")

        if probe.get("releasePokemonOutProto"):
            print("\n--- Holoholo.Rpc.ReleasePokemonOutProto fields ---")
            op = probe["releasePokemonOutProto"]
            if op.get("found") is False:
                print("  NOT FOUND")
            else:
                for f in op.get("fields", []):
                    print(f"  {f['offset']:>6}  {f['type']:<40}  {f['name']}")

        # Pick shape
        bag_info = probe.get("classes", {}).get(
            "Niantic.Holoholo.Internal.PokemonBagImpl", {}
        )
        iface_info = probe.get("classes", {}).get("Niantic.Holoholo.IPokemonBag", {})
        rels = list(bag_info.get("releaseMethods", []) or []) + list(
            iface_info.get("releaseMethods", []) or []
        )
        choice = pick_release_shape(rels)
        print()
        print("=" * 70)
        print("SHAPE SELECTION")
        print("=" * 70)
        if choice.get("error"):
            print(f"  ERROR: {choice['error']}")
            print("  Cannot proceed with execute path.")
        else:
            print(f"  shape   = {choice['shape']}")
            print(f"  method  = {choice['method']['name']} @ {choice['method']['ptr']}")
            print(f"  reason  = {choice['reason']}")
            print(f"  sig     = {render_param_signature(choice['method'])}")

        status_off = status_offset_from_outproto(probe)
        print(
            f"\n  ReleasePokemonOutProto.status offset = {status_off or 'UNKNOWN'}"
        )

        if args.probe_only:
            print("\n[bulk_release] --probe-only set, exiting.")
            return

        if "error" in choice:
            print("\n[bulk_release] STOP: no usable Release method shape.")
            return

        # Phase 2: inventory (UIDs)
        uids = []
        if args.uids_file:
            uids = read_uids_from_file(args.uids_file)
            print(f"\n[bulk_release] phase 2: loaded {len(uids)} UIDs from {args.uids_file}")
        else:
            print(
                f"\n[bulk_release] phase 2: locating TaggingRpcService to read {args.tag_name} binding"
            )
            svc_r = script.exports_sync.locate_tagging_service()
            if "err" in svc_r:
                print(f"  ERROR locating service: {svc_r['err']}")
                return
            svc_hits = svc_r.get("hits", [])
            if not svc_hits:
                print("  no TaggingRpcService instances live")
                return
            print(f"  TaggingRpcService live hits: {svc_hits}")
            # take first
            svc_addr = svc_hits[0]
            tag_r = script.exports_sync.dump_claude_tx_binding(svc_addr, args.tag_name)
            if "err" in tag_r:
                print(f"  ERROR reading {args.tag_name}: {tag_r['err']}")
                return
            uids = tag_r["uids"]
            print(
                f"  {args.tag_name} tag idx={tag_r['idx']} count={tag_r['count']} (UIDs read: {len(uids)})"
            )

        if not uids:
            print("  no UIDs to release, exiting")
            return

        print(f"\n  first 5 UIDs: {uids[:5]}")
        print(f"  last  5 UIDs: {uids[-5:]}")

        # Phase 3 + 4: execute path
        n_uids = len(uids)
        n_batches = (n_uids + args.batch_size - 1) // args.batch_size
        print()
        print("=" * 70)
        print("EXECUTION PLAN")
        print("=" * 70)
        print(f"  total UIDs       = {n_uids}")
        print(f"  batch size       = {args.batch_size}")
        print(f"  batch gap        = {args.batch_gap}s")
        print(f"  per-call gap     = {args.per_call_gap}s")
        print(f"  number of batches = {n_batches}")
        est = n_batches * args.batch_gap + n_uids * args.per_call_gap
        print(f"  est. wall time   = {est:.0f}s  (~{est/60:.1f} min)")
        print(f"  shape            = {choice['shape']}")
        print(
            f"  method to invoke = {choice['method']['name']} ({choice['method']['ptr']})"
        )

        # Locate PokemonBagImpl singleton (needed by both dry-run preview + execute)
        bag_r = script.exports_sync.find_bag_singleton()
        if "err" in bag_r:
            print(f"\n[bulk_release] ERROR finding PokemonBagImpl: {bag_r['err']}")
            return
        bag_hits = bag_r.get("hits", [])
        if len(bag_hits) != 1:
            print(
                f"\n[bulk_release] expected exactly 1 PokemonBagImpl, got {len(bag_hits)}: {bag_hits}"
            )
            return
        bag_addr = bag_hits[0]
        print(f"  PokemonBagImpl   = {bag_addr}")

        if args.execute:
            print()
            print("=" * 70)
            print("FINAL CONFIRMATION REQUIRED")
            print("=" * 70)
            print(
                f"  About to call {choice['method']['name']} on {n_uids} pokemon UIDs."
            )
            print(
                "  This is IRREVERSIBLE - the pokemon will be transferred to Professor."
            )
            print()
            try:
                resp = input("  Type 'TYPE TRANSFER TO CONTINUE' to proceed: ")
            except EOFError:
                resp = ""
            if resp.strip() != "TYPE TRANSFER TO CONTINUE":
                print("  Did not receive exact confirmation string. ABORTED.")
                return

            if choice["shape"] not in ("uid", "pokemon_proto"):
                print(
                    f"\n[bulk_release] shape {choice['shape']} execution path not implemented yet."
                )
                return

            # For pokemon_proto shape, resolve UIDs -> PokemonProto ptrs via bag walk
            uid_to_proto = {}
            if choice["shape"] == "pokemon_proto":
                print(f"\n  resolving {len(uids)} UIDs -> PokemonProto pointers via bag walk")
                uid_to_proto = pg.find_protos_for_uids(sess, bag_addr, uids)
                missing = [u for u in uids if u not in uid_to_proto]
                print(
                    f"  resolved: {len(uid_to_proto)}  missing: {len(missing)}"
                )
                if missing:
                    print(f"  first missing UIDs: {missing[:5]}")
                if not uid_to_proto:
                    print("  cannot proceed - no UIDs resolved")
                    return

            # Inject the execute JS
            exec_script = pg.get_script_with_helpers(sess, EXECUTE_JS)
            try:
                prep = exec_script.exports_sync.prep_release(
                    {
                        "methodPtr": choice["method"]["ptr"],
                        "shape": choice["shape"],
                        "bagAddr": bag_addr,
                        "statusOffsetHex": status_off,
                    }
                )
                print(f"  prep result: {prep}")

                results = []
                t_start = time.time()
                work_list = uids if choice["shape"] == "uid" else [
                    u for u in uids if u in uid_to_proto
                ]
                n_work = len(work_list)
                n_batches_real = (n_work + args.batch_size - 1) // args.batch_size
                for bidx in range(n_batches_real):
                    chunk = work_list[
                        bidx * args.batch_size : (bidx + 1) * args.batch_size
                    ]
                    print(
                        f"\n[batch {bidx+1}/{n_batches_real}] releasing {len(chunk)} UIDs"
                    )
                    batch_results = []
                    for uid in chunk:
                        if choice["shape"] == "uid":
                            r = exec_script.exports_sync.release_single(uid)
                        else:
                            proto_addr = uid_to_proto[uid]
                            r = exec_script.exports_sync.release_by_proto(proto_addr)
                            r["uid"] = uid
                            r["protoAddr"] = proto_addr
                        batch_results.append({"uid": uid, **r})
                        if "status" in r:
                            status_str = f"status={r.get('status')}"
                        elif "promise" in r:
                            status_str = f"promise={r.get('promise')}"
                        else:
                            status_str = str(r)
                        print(f"  uid={uid}  {status_str}")
                        time.sleep(args.per_call_gap)
                    results.extend(batch_results)
                    if bidx < n_batches_real - 1:
                        time.sleep(args.batch_gap)

                with open("release_results.json", "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2)
                ok_count = sum(1 for r in results if r.get("ok"))
                print(
                    f"\n[bulk_release] done in {time.time()-t_start:.1f}s. "
                    f"ok count: {ok_count}/{len(results)}"
                )
                print(f"  saved to release_results.json")
            finally:
                try:
                    exec_script.unload()
                except Exception:
                    pass
        else:
            # Dry-run: explain what WOULD have happened
            print()
            print("=" * 70)
            print("DRY-RUN: NO TRANSFER PERFORMED")
            print("=" * 70)
            print(
                f"  Would have located PokemonBagImpl via liveness API (single instance)."
            )
            print(
                f"  Would have primed JS execute helper with method ptr {choice['method']['ptr']}"
                f", bag instance, status offset {status_off or 'UNKNOWN'}."
            )
            if choice["shape"] == "pokemon_proto":
                print(
                    f"  Would walk the bag LinkedHashMap to resolve UIDs to PokemonProto ptrs."
                )
                print(
                    f"  (verifying this against {len(uids)} UIDs requires entering bag walk path now)"
                )
            print(f"\n  Would have iterated {n_batches} batches:")
            for bidx in range(min(n_batches, 3)):
                start = bidx * args.batch_size
                end = min(start + args.batch_size, n_uids)
                first = uids[start]
                last = uids[end - 1]
                print(
                    f"    batch {bidx+1}: UIDs[{start}..{end-1}] ({end-start} UIDs) - {first} ... {last}"
                )
            if n_batches > 3:
                print(f"    ... ({n_batches - 3} more batches)")
            if choice["shape"] == "uid":
                print(
                    f"\n  For each UID, would call rI(method, bag, &uid_u64, &exc) and read"
                )
                print(
                    f"  outProto +{status_off or '<unknown>'} for status; sleep {args.per_call_gap}s;"
                )
            elif choice["shape"] == "pokemon_proto":
                print(
                    f"\n  For each UID, would resolve protoAddr via bag walk, then call"
                )
                print(
                    f"  rI(method, bag, &protoAddr, &exc) -> IPromise<ReleasePokemonOutProto>;"
                )
                print(
                    f"  promise resolves async on HTTP response; status at +{status_off or '<unknown>'}."
                )
                print(f"  per-call gap {args.per_call_gap}s.")
            print(f"  sleep {args.batch_gap}s between batches.")
            print(
                f"\n  To execute for real: re-run with --execute (will require typed confirm)."
            )

            # Bag walk preview (dry-run): resolve first 5 UIDs to prove path works
            if choice["shape"] == "pokemon_proto" and uids:
                preview_uids = uids[:5]
                print(f"\n  Bag-walk preview (resolving first {len(preview_uids)} UIDs to proto ptrs)...")
                proto_map = pg.find_protos_for_uids(sess, bag_addr, preview_uids)
                for u in preview_uids:
                    print(f"    UID {u} -> {proto_map.get(u, '(NOT FOUND IN BAG)')}")
    finally:
        try:
            script.unload()
        except Exception:
            pass
        try:
            sess.detach()
        except Exception:
            pass


if __name__ == "__main__":
    main()
