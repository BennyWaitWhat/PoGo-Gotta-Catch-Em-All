"""Deep PokedexImpl read: all 10 regional dicts × all per-category flags.

The canonical pipeline only extracts hundo/shinyHundo/purified from the 'All'
dict. For dex-completion analysis I also need Shiny(11), Shadow(15), and the
per-region (cugs..cuha) entry lists.

PokedexImpl layout (verified in [[pogo-il2cpp-internals]]):
  +0x10  cugr  All
  +0x18  cugs  Kanto         +0x40  cugx  Kalos
  +0x20  cugt  Johto         +0x48  cugy  Alola
  +0x28  cugu  Hoenn         +0x50  cugz  Galar
  +0x30  cugv  Sinnoh        +0x58  cuha  Paldea
  +0x38  cugw  Unova

Each is Dictionary<int, PokedexEntryProto>. Entry layout:
  +0x18 timesCaptured (s32)
  +0x50 CapturedForms RepeatedField<int>
  +0x80 MapField<String, PokedexCategoryStatus>
PokedexCategoryStatus: +0x10 cat, +0x14 enc, +0x15 acq, +0x18 lastMs.

Writes dex_deep_full.json — {region: [ {pid, times, forms, cats:[{key,cat,enc,acq}, ...]} ]}.
Categories of interest: 11 Shiny, 13 ThreeStar, 14 FourStar(hundo), 15 Shadow,
16 Purified, 101 ShinyThreeStar, 102 ShinyFourStar, 201 SizeXxs, 202 SizeXxl.
"""
import json, os, sys, time
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'dex_deep_full.json')

# Inline the pipeline's PokedexImpl candidate-picker (multiple liveness hits;
# the real one has dict count 500-4000).
PROBE_JS = r"""
rpc.exports.probeDexCount = function(addr) {
    _ensureInit();
    try {
        var inst = ptr(addr);
        var dict = inst.add(0x10).readPointer();
        if (dict.isNull()) return {ok:false, err:'null dict'};
        var entries = dict.add(0x18).readPointer();
        if (entries.isNull()) return {ok:false, err:'null entries'};
        var count = entries.add(0x18).readS32();
        return {ok:true, n: count};
    } catch(e) { return {ok:false, err: e.toString()}; }
};
"""

DEEP_JS = r"""
var REGIONS = [
    {off: 0x10, name: 'All'},
    {off: 0x18, name: 'Kanto'},
    {off: 0x20, name: 'Johto'},
    {off: 0x28, name: 'Hoenn'},
    {off: 0x30, name: 'Sinnoh'},
    {off: 0x38, name: 'Unova'},
    {off: 0x40, name: 'Kalos'},
    {off: 0x48, name: 'Alola'},
    {off: 0x50, name: 'Galar'},
    {off: 0x58, name: 'Paldea'},
];

function readStr(strPtr) {
    if (strPtr.isNull()) return '';
    var len = strPtr.add(0x10).readS32();
    if (len <= 0 || len > 200) return '';
    var chars = [];
    for (var i = 0; i < len; i++) chars.push(String.fromCharCode(strPtr.add(0x14 + i*2).readU16()));
    return chars.join('');
}

function readEntry(protoPtr) {
    var times = protoPtr.add(0x18).readS32();
    var forms = [];
    try {
        var cf = protoPtr.add(0x50).readPointer();
        if (!cf.isNull()) {
            var n = cf.add(0x18).readS32();
            if (n > 0 && n < 80) {
                var data = cf.add(0x10).readPointer();
                for (var i = 0; i < n; i++) forms.push(data.add(0x20 + i*4).readS32());
            }
        }
    } catch(e) {}
    var cats = [];
    try {
        var mf = protoPtr.add(0x80).readPointer();
        if (!mf.isNull()) {
            var list = mf.add(0x18).readPointer();
            if (!list.isNull()) {
                var head = list.add(0x10).readPointer();
                var lcount = list.add(0x18).readS32();
                var node = head, iters = 0;
                while (node && !node.isNull() && iters < lcount + 50) {
                    try {
                        var key = '';
                        try {
                            var ks = node.add(0x28).readPointer();
                            if (!ks.isNull()) key = readStr(ks);
                        } catch(e) {}
                        var v = node.add(0x30).readPointer();
                        if (!v.isNull()) {
                            cats.push({
                                key: key,
                                cat: v.add(0x10).readS32(),
                                enc: v.add(0x14).readU8(),
                                acq: v.add(0x15).readU8()
                            });
                        }
                        var next = node.add(0x18).readPointer();
                        if (next.isNull() || next.equals(head)) break;
                        node = next;
                    } catch(e) { break; }
                    iters++;
                }
            }
        }
    } catch(e) {}
    return {times: times, forms: forms, cats: cats};
}

rpc.exports.deepReadDex = function(dexAddrStr) {
    var inst = ptr(dexAddrStr);
    var out = {};
    for (var ri = 0; ri < REGIONS.length; ri++) {
        var R = REGIONS[ri];
        var arr = [];
        try {
            var dict = inst.add(R.off).readPointer();
            if (!dict.isNull()) {
                var entries = dict.add(0x18).readPointer();
                if (!entries.isNull()) {
                    var maxLen = entries.add(0x18).readS32();
                    var data = entries.add(0x20);
                    for (var i = 0; i < maxLen; i++) {
                        var ep = data.add(i * 24);
                        var hash = ep.readS32();
                        if (hash < 0) continue;
                        var pidv = ep.add(8).readS32();
                        var protoPtr = ep.add(16).readPointer();
                        if (protoPtr.isNull()) continue;
                        var rec = readEntry(protoPtr);
                        rec.pid = pidv;
                        arr.push(rec);
                    }
                }
            }
        } catch(e) {}
        out[R.name] = arr;
    }
    return out;
};
"""


def _pick_dex(sess):
    script = pg.get_script_with_helpers(sess)
    try:
        r = script.exports_sync.find_singleton('Niantic.Holoholo.Internal', 'PokedexImpl')
        if 'err' in r:
            raise RuntimeError(f'liveness: {r["err"]}')
        hits = r.get('hits', [])
    finally:
        script.unload()
    if len(hits) == 1:
        return hits[0]
    s = pg.get_script_with_helpers(sess, PROBE_JS)
    try:
        best, best_n = None, -1
        for c in hits:
            r = s.exports_sync.probe_dex_count(c)
            n = r.get('n', -1) if r.get('ok') else -1
            print(f"    PokedexImpl candidate {c}: count={n}")
            if 500 <= n <= 4000 and n > best_n:
                best, best_n = c, n
        if best is None:
            raise RuntimeError(f'no plausible PokedexImpl ({len(hits)} candidates)')
        return best
    finally:
        s.unload()


def main():
    print("Attaching...")
    sess, pid = pg.get_session()
    print(f"  pid={pid}")
    try:
        dex = _pick_dex(sess)
        print(f"  dex @ {dex}")
        script = pg.get_script_with_helpers(sess, DEEP_JS)
        t0 = time.time()
        result = script.exports_sync.deep_read_dex(dex)
        total = sum(len(v) for v in result.values())
        print(f"  walked {total} (region, pid) entries in {time.time()-t0:.2f}s")
        for region, arr in result.items():
            print(f"    {region:7s}: {len(arr)} entries")
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(result, f)
        print(f"  wrote {OUT}")
        script.unload()
    finally:
        sess.detach()
    print("Done.")


if __name__ == '__main__':
    main()
