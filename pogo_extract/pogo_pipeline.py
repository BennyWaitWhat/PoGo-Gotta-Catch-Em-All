"""Single-attach Frida pipeline: walk bag -> reconcile DB -> refresh size -> refresh
server tags -> read dex hundos -> run cull_v9 -> sanity check -> summary.

Replaces the ~10 min chain of run_full_inventory.py + reconcile_inventory_v3.py +
refresh_size_category.py + refresh_tag_bindings.py + read_pokedex_liveness.py +
cull_v9.py with one process that does ONE attach, ONE bag walk, and reuses cached
singletons across every step.

READ-ONLY WITH RESPECT TO THE PHONE. This process walks the bag, mirrors server tags into the
DB, and rebuilds FILES (pokemon.db, the tagsets, dex json). It has no tag-write primitive and must
never acquire one. Pushing the pile is `prune_tags.py --atomic`, and only after
`preflight_transfer.py` passes. (--tag-transfers, a second ungated pusher, removed 2026-09-07.)

Flags:
    --dry-run        skip the server-tag mirror read (refresh_tag_bindings). It has never meant
                     "safe to run" in any other sense: the reconcile, form normalization, cull and
                     tagset rebuild all still write to disk under it.
"""
import argparse, datetime, json, os, shutil, sqlite3, struct, sys, time

import pogo_il2cpp as pg

sys.stdout.reconfigure(line_buffering=True)

_T0 = time.time()
_STEP_TIMES = {}
def _tick(label): print(f"[t+{time.time()-_T0:6.2f}s] {label}")
def _step(name):
    class _C:
        def __enter__(s):
            s.t = time.time(); _tick(f">> {name}"); return s
        def __exit__(s, *_):
            d = time.time() - s.t
            _STEP_TIMES[name] = d
            _tick(f"<< {name} ({d:.2f}s)")
    return _C()

# ---------------------------------------------------------------------------
# JS payload. One script, loaded once. Extends pg.JS_PREAMBLE with pipeline RPCs.
# ---------------------------------------------------------------------------
# The storage screen's own numbers (2026-09-24): PokemonBagImpl's no-arg Int32 getters, called by NAME only.
BAG_COUNTS_JS = r"""
rpc.exports.counters = function (bag) {
    _ensureInit();
    var cl = IL2.objGC(ptr(bag)), it = Memory.alloc(Process.pointerSize), m, out = {};
    var want = {get_Count: 1, get_PokemonOnlyCount: 1, get_EggCount: 1, get_IncubatedEggCount: 1};
    it.writePointer(ptr(0));
    while ((m = IL2.cGM(cl, it)) && !m.isNull()) {
        var n = IL2.mGN(m).readCString();
        if (want[n] && !(n in out)) out[n] = rI(m, ptr(bag), ptr(0), null).add(0x10).readS32();
    }
    return out;
};
"""

PIPELINE_JS = r"""
function readBytesHex(p, n) {
    try {
        var bs = p.readByteArray(n);
        var u8 = new Uint8Array(bs);
        var s = '';
        for (var i = 0; i < u8.length; i++) s += ('0' + u8[i].toString(16)).slice(-2);
        return s;
    } catch(e) { return null; }
}

function pipelineWalk(bagAddrStr) {
    _ensureInit();
    var bagCls = cFN('Niantic.Holoholo.Internal', 'PokemonBagImpl');
    var ga = cMN(bagCls, 'get_AllPokemon', 0);
    var bag = ptr(bagAddrStr);
    var values = rI(ga, bag, ptr(0), null);
    var lhm = values.add(0x10).readPointer();
    var list = lhm.add(0x18).readPointer();
    var head = list.add(0x10).readPointer();
    var lcount = list.add(0x18).readS32();
    var out = [];
    var node = head;
    var iters = 0;
    // TRUNCATION TRACKING (audit lockdown 2026-09-02). `lcount` is the list's DECLARED length. The
    // old loop swallowed any per-node error with `catch(e){break}` and returned a SHORT list with no
    // signal at all -- and the only downstream guard was `len(parsed) >= 0.70 * prior_inbag`, a
    // floor of 3891 against a 5559 bag. A walk could lose 1668 REAL mons and still read as
    // "complete", and two identically-truncated walks in a row reach the unfiltered DELETE.
    // Report declared/walked/truncated so the caller can refuse to purge on a short walk.
    var truncated = false;
    var truncReason = null;
    while (node && !node.isNull() && iters < lcount + 200) {
        try {
            var uid = node.add(0x28).readU64().toString();
            var proto = node.add(0x30).readPointer();
            var rec = {uid: uid, ptr: proto.toString()};
            rec.protoBytes = readBytesHex(proto, 0x200);
            try {  // nickname_ @0xb8 (C# string) -- read LIVE every walk (2026-09-17; the column was a stale one-off)
                var nkP = proto.add(0xb8).readPointer();
                rec.nickname = '';
                if (!nkP.isNull()) { var nkL = nkP.add(0x10).readS32();
                    if (nkL > 0 && nkL < 64) rec.nickname = nkP.add(0x14).readUtf16String(nkL); }
            } catch(e) { rec.nickname = null; }
            try {  // originalOwnerNickname_ @0x100 (C# string) -> Traded-by-E+F tag
                var onP = proto.add(0x100).readPointer();
                if (!onP.isNull()) { var onL = onP.add(0x10).readS32();
                    if (onL > 0 && onL < 64) rec.originalOwner = onP.add(0x14).readUtf16String(onL); }
            } catch(e) {}
            try {
                var dispPtr = proto.add(0xd8).readPointer();
                if (dispPtr.isNull()) {
                    // NULL display pointer: the cosmetic fields are UNKNOWN, not "all zero". The
                    // old code had no else-branch, so neither displayBytes nor displayReadFailed
                    // was set -- parse_pokemon then computed every cosmetic field as 0 with
                    // display_read_failed=0, and the FULL update wrote a fabricated all-zero
                    // "plain" record. That is verbatim what the audit-F17 guard exists to prevent,
                    // and a plain-looking record is cull-eligible. (lockdown 2026-09-02)
                    rec.displayReadFailed = true;
                    rec.displayNull = true;
                } else {
                    rec.displayBytes = readBytesHex(dispPtr, 0x80);
                    // display proto EXISTS but the read failed: mark it so the writer keeps the prior
                    // cosmetic fields instead of writing a fake all-zero 'plain' record (audit F17)
                    if (!rec.displayBytes) rec.displayReadFailed = true;
                    try {
                        var locPtr = dispPtr.add(0x58).readPointer();
                        if (!locPtr.isNull()) rec.locBytes = readBytesHex(locPtr, 0x40);
                    } catch(e) {}
                    try {
                        var megaPtr = dispPtr.add(0x50).readPointer();
                        if (!megaPtr.isNull()) rec.megaBytes = readBytesHex(megaPtr, 0x40);
                    } catch(e) {}
                }
            } catch(e) { rec.displayReadFailed = true; }
            // POINTER FIELDS RE-READ EVERY WALK (2026-09-23). Null pointer -> field absent (Python writes NULL).
            try {  // breadMoves_ @0x1c8: RepeatedField<BreadMoveSlotProto> (array_@0x10, count_@0x18, items @0x20+8i)
                var bmP = proto.add(0x1c8).readPointer();
                if (!bmP.isNull()) {
                    var bmC = bmP.add(0x18).readS32(); var bmA = bmP.add(0x10).readPointer(); var bmL = [];
                    if (!bmA.isNull() && bmC > 0 && bmC <= 30) {
                        for (var bi = 0; bi < bmC; bi++) { var sl = bmA.add(0x20 + bi * 8).readPointer();
                            if (!sl.isNull()) bmL.push([sl.add(0x10).readS32(), sl.add(0x14).readS32()]); } }
                    rec.breadSlots = bmL;
                }
            } catch(e) {}
            try {  // bonusStatLevel_ @0x1e8 + dayNightBonusStat_ @0x1f8: PokemonBonusStatLevelProto (atk@0x10 def@0x14 sta@0x18)
                var bsP = proto.add(0x1e8).readPointer();
                if (!bsP.isNull()) rec.bonusBytes = readBytesHex(bsP, 0x20);
                var dnP = proto.add(0x1f8).readPointer();
                if (!dnP.isNull()) rec.dayNightBytes = readBytesHex(dnP, 0x20);
            } catch(e) {}
            try {  // pokemonContestInfo_ @0x1b0: PokemonContestInfoProto (ContestEndTimeMs@0x18, FreeUpTimeMs@0x20)
                var ciP = proto.add(0x1b0).readPointer();
                if (!ciP.isNull()) rec.contestBytes = readBytesHex(ciP, 0x30);
            } catch(e) {}
            out.push(rec);
            var next = node.add(0x18).readPointer();
            if (next.isNull() || next.equals(head)) break;
            node = next;
        } catch(e) {
            // a node blew up mid-walk -> the REST of the list is unreachable. That is a truncated
            // walk, not a complete one. Say so instead of returning a silently short list.
            truncated = true;
            truncReason = 'node error at iter ' + iters + ': ' + e;
            break;
        }
        iters++;
    }
    if (iters >= lcount + 200) {          // ran out of iteration budget -> we never reached the end
        truncated = true;
        truncReason = 'iteration cap hit (' + iters + ' >= declared ' + lcount + ' + 200)';
    }
    // `truncated` is a HARD signal (a node blew up, or we never reached the end of the list) and the
    // caller retries then raises on it. `short` is a SOFT signal: fewer records than the list's
    // declared _size. It is reported separately and NEVER raises, because we cannot prove from here
    // that `lcount` counts exactly the nodes this walk visits (a sentinel head would make it
    // permanently off-by-one and a hard failure there would brick every crawl). A short walk only
    // blocks the DELETE, which is the thing that must never run on doubtful data.
    return {declared: lcount, walked: out.length, truncated: truncated,
            short: (out.length < lcount), truncReason: truncReason, entries: out};
}

function pipelineEnumBindings(svcAddrStr, protoToUid) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, gnt = null, gctb = null;
    while ((m = IL2.cGM(svcCls, iter)) && !m.isNull()) {
        var nm = IL2.mGN(m).readCString();
        if (nm === 'get_NumberOfTags') gnt = m;
        if (nm === 'GetCachedTagToPokemonBindingForIndex') gctb = m;
    }
    var svc = ptr(svcAddrStr);
    var ret = rI(gnt, svc, ptr(0), null);
    var totalTags = ret.add(0x10).readS32();
    var bindings = {};
    for (var i = 0; i < totalTags; i++) {
        var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
        var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
        var bp = rI(gctb, svc, args, null);
        if (bp.isNull()) continue;
        var tagProto = bp.add(0x10).readPointer();
        var name = '';
        try {
            var ns = tagProto.add(0x40).readPointer();
            if (!ns.isNull()) {
                var len = ns.add(0x10).readS32();
                if (len > 0 && len < 100) {
                    var chars = [];
                    for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(ns.add(0x14 + ci*2).readU16()));
                    name = chars.join('');
                }
            }
        } catch(e) {}
        var listPtr = bp.add(0x18).readPointer();
        var count = 0, items = ptr(0);
        try { count = listPtr.add(0x18).readS32(); } catch(e) {}
        try { items = listPtr.add(0x10).readPointer(); } catch(e) {}
        var uids = [];
        for (var j = 0; j < count; j++) {
            try {
                var pp = items.add(0x20 + j*8).readPointer().toString();
                var u = protoToUid[pp];
                if (u) uids.push(u);
            } catch(e) {}
        }
        bindings[name || ('__anon_' + i)] = {idx: i, count: count, uids: uids};
    }
    return bindings;
}

function pipelineReadDex(dexAddrStr) {
    var inst = ptr(dexAddrStr);
    var dictAll = inst.add(0x10).readPointer();
    var entries = dictAll.add(0x18).readPointer();
    var maxLen = entries.add(0x18).readS32();
    var data = entries.add(0x20);
    var results = [];
    for (var i = 0; i < maxLen; i++) {
        var ep = data.add(i * 24);
        var hashCode = ep.readS32();
        if (hashCode < 0) continue;
        var pidv = ep.add(8).readS32();
        var protoPtr = ep.add(16).readPointer();
        if (protoPtr.isNull()) continue;
        var timesCaptured = protoPtr.add(0x18).readS32();
        // CapturedForms RepeatedField<Form> @ +0x50 (count@+0x18, items@+0x10, data@+0x20 int32)
        var capturedForms = [];
        try {
            var cf = protoPtr.add(0x50).readPointer();
            if (!cf.isNull()) {
                var cfn = cf.add(0x18).readS32();
                // CLAMP, not cutoff: Pikachu is at 46 captured forms and climbing -- the old <60 guard
                // silently dropped the WHOLE list past 60, blanking form-gap detection (audit F20)
                if (cfn > 0 && cfn < 1000) {
                    var cfx = Math.min(cfn, 256);
                    var cfi = cf.add(0x10).readPointer();
                    for (var ci = 0; ci < cfx; ci++) capturedForms.push(cfi.add(0x20 + ci*4).readS32());
                }
            }
        } catch(e) {}
        var hundoAcq = false, shinyHundoAcq = false, purifiedAcq = false;
        var mapField = protoPtr.add(0x80).readPointer();
        if (!mapField.isNull()) {
            var list = mapField.add(0x18).readPointer();
            if (!list.isNull()) {
                var head = list.add(0x10).readPointer();
                var lcount = list.add(0x18).readS32();
                var node = head, iters = 0;
                while (node && !node.isNull() && iters < lcount + 50) {
                    try {
                        var kvpVal = node.add(0x30).readPointer();
                        if (!kvpVal.isNull()) {
                            var catEnum = kvpVal.add(0x10).readS32();
                            var acq = kvpVal.add(0x15).readU8();
                            if (catEnum === 14 && acq) hundoAcq = true;
                            if (catEnum === 102 && acq) shinyHundoAcq = true;
                            if (catEnum === 16 && acq) purifiedAcq = true;
                        }
                        var next = node.add(0x18).readPointer();
                        if (next.isNull() || next.equals(head)) break;
                        node = next;
                    } catch(e) { break; }
                    iters++;
                }
            }
        }
        results.push({pid: pidv, times: timesCaptured, forms: capturedForms, hundo: hundoAcq, shinyHundo: shinyHundoAcq, purified: purifiedAcq});
    }
    return {count: results.length, entries: results};
}

rpc.exports.pipelineWalk = pipelineWalk;
rpc.exports.pipelineEnumBindings = pipelineEnumBindings;
rpc.exports.pipelineReadDex = pipelineReadDex;
"""


# ---------------------------------------------------------------------------
# proto byte parsers (lifted from reconcile_inventory_v3.py / refresh_size_category.py)
# ---------------------------------------------------------------------------
def i32(bs, o): return struct.unpack_from('<i', bs, o)[0] if o+4 <= len(bs) else 0
def i64(bs, o): return struct.unpack_from('<q', bs, o)[0] if o+8 <= len(bs) else 0
def f32(bs, o): return struct.unpack_from('<f', bs, o)[0] if o+4 <= len(bs) else 0.0
def byte(bs, o): return bs[o] if o < len(bs) else 0


def _rec_is_egg(rec):
    """True iff this walk record is an EGG (PokemonProto.isEgg_ @0x50, inside the 0x200 dumped).

    Used only to tell a legitimate skip (an egg) apart from a genuine proto parse failure, which
    must block the purge. A record we cannot read at all is NOT reported as an egg. (2026-09-02)

    isEgg_ is a System.Boolean (proto_layout.json, Holoholo.Rpc.PokemonProto isEgg_ offset 80), so
    its ONLY true value is exactly 1. This used to test bool(...), which calls ANY nonzero byte an
    egg -- but a byte that is neither 0 nor 1 means the record is not a readable PokemonProto, i.e.
    precisely the corrupt-record case this helper exists to keep OUT of the egg bucket. The cached
    00:23 walk carried 5 such records (bytes 9/240/2/59/9, pointer-shaped uids, none of them in the
    bag) and NOT ONE record with a genuine 1. Calling one of those an egg would score it as a
    legitimate skip instead of incrementing skipped_unparsed -- and skipped_unparsed == 0 is a hard
    precondition of the 2-crawl-confirm DELETE. Today the true branch is unreachable (the only
    caller runs this when protoBytes is ABSENT, which returns False above), so tightening it changes
    no current behaviour; it is the guard that has to be right BEFORE the egg test is ever hoisted
    into a real filter. (2026-09-07)"""
    pb = rec.get('protoBytes')
    if not pb:
        return False
    try:
        return byte(bytes.fromhex(pb), 0x50) == 1
    except (ValueError, TypeError):
        return False


def _atomic_json(path, obj, indent=None):
    """R5 (Gym Battle review, 2026-09-29): write a JSON file other processes read (candy.json, inventory.json) through a
    temp file + os.replace, so a reader never sees half of it."""
    tmp = '%s.tmp.%d' % (path, os.getpid())
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=indent)
    os.replace(tmp, path)


def _rec_uid_hex(rec):
    """The DB key (zero-padded 16-hex, exactly as parse_pokemon builds uid_hex) of a walk record, or None when its uid
    cannot be read. Used to keep an unreadable-but-present record in the bag (H07 2026-09-29)."""
    try:
        return f"{int(rec['uid']) & 0xFFFFFFFFFFFFFFFF:016x}"
    except (KeyError, TypeError, ValueError):
        return None

CPM_TABLE = [(0.094,1.0),(0.135137432,1.5),(0.16639787,2.0),(0.192650919,2.5),(0.21573247,3.0),(0.236572661,3.5),(0.25572005,4.0),(0.273530381,4.5),(0.29024988,5.0),(0.306057377,5.5),(0.3210876,6.0),(0.335445036,6.5),(0.34921268,7.0),(0.362457751,7.5),(0.37523559,8.0),(0.387592406,8.5),(0.39956728,9.0),(0.411193551,9.5),(0.42250001,10.0),(0.432926419,10.5),(0.44310755,11.0),(0.4530599578,11.5),(0.46279839,12.0),(0.472336083,12.5),(0.48168495,13.0),(0.4908558,13.5),(0.49985844,14.0),(0.508701765,14.5),(0.51739395,15.0),(0.525942511,15.5),(0.53435433,16.0),(0.542635767,16.5),(0.55079269,17.0),(0.558830576,17.5),(0.56675452,18.0),(0.574569153,18.5),(0.58227891,19.0),(0.589887907,19.5),(0.59740001,20.0),(0.604818814,20.5),(0.61215729,21.0),(0.619399365,21.5),(0.62656713,22.0),(0.633644533,22.5),(0.64065295,23.0),(0.647576426,23.5),(0.65443563,24.0),(0.661214806,24.5),(0.667934,25.0),(0.674577537,25.5),(0.68116492,26.0),(0.687680648,26.5),(0.69414365,27.0),(0.700538673,27.5),(0.7068842,28.0),(0.713164996,28.5),(0.71939909,29.0),(0.725571552,29.5),(0.7317,30.0),(0.734741009,30.5),(0.73776948,31.0),(0.740785574,31.5),(0.74378943,32.0),(0.746781211,32.5),(0.74976104,33.0),(0.752729087,33.5),(0.7556855,34.0),(0.758630378,34.5),(0.76156384,35.0),(0.764486065,35.5),(0.76739717,36.0),(0.770297266,36.5),(0.7731865,37.0),(0.776064962,37.5),(0.77893275,38.0),(0.781790055,38.5),(0.78463697,39.0),(0.787473578,39.5),(0.79030001,40.0),(0.792803968,40.5),(0.79530001,41.0),(0.797800015,41.5),(0.8003,42.0),(0.802799995,42.5),(0.8053,43.0),(0.807800014,43.5),(0.81029999,44.0),(0.812799985,44.5),(0.81529999,45.0),(0.81779999,45.5),(0.82029998,46.0),(0.82279998,46.5),(0.82529997,47.0),(0.82779996,47.5),(0.83029996,48.0),(0.83279996,48.5),(0.83529995,49.0),(0.83779995,49.5),(0.84029995,50.0),(0.84279995,50.5),(0.84529994,51.0)]

def cpm_to_level(cpm):
    """The level whose multiplier is NEAREST the game's (2026-09-30). The old 'first entry >= cpm - 1e-6' walk read 142 bag mons
    exactly half a level high: 20 half-level CPM_TABLE entries (L20.5-29.5, L41.5-50.5) sit up to 4.85e-6 below the game's own
    ladder (PokeMiners game master playerLevel.cpMultiplier; deep dive), so the game's float overshot them. Neighbouring entries
    are >= 0.0025 apart, so the nearest one is unambiguous; a value far from every entry keeps the old rule."""
    if cpm <= 0: return 0.0
    _best = min(CPM_TABLE, key=lambda t: abs(t[0] - cpm))
    if abs(_best[0] - cpm) <= 1e-4:
        return _best[1]
    for cpm_v, lvl in CPM_TABLE:
        if cpm <= cpm_v + 1e-6: return lvl
    return 51.0


# Supplemental National-Dex id->name for species the DB has no named copy of
# (so evolutions / first-of-species don't land as 'pidN'). Extend as needed.
SUPPLEMENTAL_NAMES = {
    16: 'Pidgey', 17: 'Pidgeotto', 18: 'Pidgeot', 70: 'Weepinbell',
    285: 'Shroomish', 519: 'Pidove', 705: 'Sliggoo', 826: 'Orbeetle',
    857: 'Hattrem', 917: 'Tarountula', 955: 'Squawkabilly', 956: 'Flittle',
}


def _bonus(hx):
    """PokemonBonusStatLevelProto bytes -> (atk, def, sta) bonus IV levels, or None when the pointer was null."""
    if not hx:
        return None
    b = bytes.fromhex(hx)
    return (i32(b, 0x10), i32(b, 0x14), i32(b, 0x18))


def _contest(hx):
    """PokemonContestInfoProto bytes -> (end_ms, free_up_ms), or None when the pointer was null."""
    if not hx:
        return None
    b = bytes.fromhex(hx)
    return (i64(b, 0x18), i64(b, 0x20))


def parse_pokemon(rec, species_lookup):
    """Return dict of fresh_* + structural fields for one bag entry, or None on bad data."""
    pb = rec.get('protoBytes'); db_b = rec.get('displayBytes')
    if not pb: return None
    bs = bytes.fromhex(pb)
    dbs = bytes.fromhex(db_b) if db_b else b''

    uid_unsigned = int(rec['uid'])
    uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
    uid_signed = uid_unsigned if uid_unsigned <= 2**63-1 else uid_unsigned - 2**64

    pid = i32(bs, 0x28)
    cp = i32(bs, 0x2c)
    iv_atk, iv_def, iv_sta = i32(bs, 0x70), i32(bs, 0x74), i32(bs, 0x78)
    # Total CPM = base cp_multiplier (0x7c) + additional_cpm (0xac). PoGo splits
    # the multiplier across two fields; powered-up mons carry the bulk in 0xac.
    # Reading only 0x7c yields a wildly-low level for high-level mons.
    cpm = f32(bs, 0x7c) + f32(bs, 0xac)
    is_lucky = byte(bs, 0x110)
    num_upgrades = i32(bs, 0xa8)
    move1, move2, move3 = i32(bs, 0x38), i32(bs, 0x3c), i32(bs, 0x114)
    trad = i32(bs, 0xfc)
    # The size enum is 1..5 (XXS..XXL); 0 is NOT a valid value, it is "we didn't read it". Writing
    # 0 on a short read silently strips the XXL trophy axis (keep_policy rule 7 tests ==5) with no
    # F17-style guard on this path -- 10 in-bag rows sit at size_category=0 with real height/weight
    # and is_egg=0. None means "unknown" and the writer COALESCEs to the stored value instead of
    # clobbering it. (lockdown 2026-09-02)
    size_category = i32(bs, 424) if len(bs) >= 428 else None
    if size_category is not None and not (1 <= size_category <= 5):
        size_category = None
    weight = f32(bs, 108)
    height = f32(bs, 104)
    # isEgg_ = System.Boolean at PokemonProto+0x50 (proto_layout.json, Holoholo.Rpc.PokemonProto
    # isEgg_ offset 80), inside the 0x200 the walk already dumps -- NO new device read. The column
    # had no writer in this pipeline at all: 2031 in-bag rows sat at NULL and 3697 at 0 (left by the
    # one-off _enrich_proto_fields.py), and `WHERE in_bag = 1 AND is_egg = 0`
    # (_raid_attacker_analysis.py:112) silently drops every NULL row -- 2031 of 5728 mons -- because
    # NULL = 0 is not true in SQL. Only 0 and 1 are valid for a Boolean; any other byte means this
    # is not a readable PokemonProto and is written as NOT-an-egg on purpose. That direction is the
    # safe one: a false is_egg=1 makes a real mon VANISH from any `is_egg = 0` reader, while a false
    # is_egg=0 on a genuine egg is inert (eggs are not in the keep chain and cannot be transferred).
    # (2026-09-07)
    is_egg = 1 if byte(bs, 0x50) == 1 else 0
    iv_total = iv_atk + iv_def + iv_sta
    ctms = i64(bs, 0xa0)                                          # creationTimeMs_ @0xa0 (reflection-verified 2026-06-05); the live pipeline had NEVER read it -> every fresh catch landed with a NULL capture date
    creation_time_ms = ctms if ctms > 1467590400000 else None    # POGO_LAUNCH floor rejects 0/garbage
    creation_date = (datetime.datetime.fromtimestamp(creation_time_ms / 1000, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if creation_time_ms else None)

    costume = i32(dbs, 0x10) if len(dbs) >= 0x14 else 0
    gender = i32(dbs, 0x14) if len(dbs) >= 0x18 else 0          # display proto +0x14 (1=M 2=F 3=genderless)
    is_shiny = byte(dbs, 0x18) if len(dbs) > 0x18 else 0
    form = i32(dbs, 0x1c) if len(dbs) >= 0x20 else 0
    align = i32(dbs, 0x24) if len(dbs) >= 0x28 else 0
    badge = i32(dbs, 0x28) if len(dbs) >= 0x2c else 0
    cur_temp_evo = i32(dbs, 0x2c) if len(dbs) >= 0x30 else 0
    bread_mode = i32(dbs, 0x60) if len(dbs) >= 0x64 else 0
    is_strong = byte(dbs, 0x64) if len(dbs) > 0x64 else 0
    # --- cosmetic fields the pipeline dumped but never parsed (lockdown 2026-09-02) ---------------
    # NaturalArtType@0x70, NaturalArtBackgroundAsset@0x74, NaturalArtUseFullScene@0x78 (bool) and
    # DayNightType@0x7c are all INSIDE the 0x80 of displayBytes this walk already reads, and
    # LocationCardDisplayProto.LocationCard@0x10 is inside the 0x40 of locBytes. Parsing stopped at
    # 0x64 and reduced the location card to a boolean, so the ONLY writers of these five columns
    # were parse_fresh.py / _fresh_rescan_safe.py -- neither of which is a pipeline step. Result:
    # every fresh catch landed with NULL on all five, and keep_policy DROPS the ('loc', N)
    # collectible when fresh_loc_card_enum is NULL. Offsets verified against proto_layout.json and
    # parsed identically to parse_fresh.py so the two writers cannot disagree. NO new device read.
    nat_art_type = i32(dbs, 0x70) if len(dbs) >= 0x74 else 0
    nat_art_bg = i32(dbs, 0x74) if len(dbs) >= 0x78 else 0
    nat_art_full = byte(dbs, 0x78) if len(dbs) > 0x78 else 0
    day_night = i32(dbs, 0x7c) if len(dbs) >= 0x80 else 0
    has_loc = 1 if rec.get('locBytes') else 0
    loc_bs = bytes.fromhex(rec['locBytes']) if rec.get('locBytes') else b''
    loc_card_enum = i32(loc_bs, 0x10) if len(loc_bs) >= 0x14 else 0
    has_mega = 1 if rec.get('megaBytes') else 0
    mega_bs = bytes.fromhex(rec['megaBytes']) if rec.get('megaBytes') else b''   # PokemonMegaEvolutionLevelProto: Points@0x10 (i64), Level@0x18 (i32) -- reflection-verified 2026-06-05
    mega_level = i32(mega_bs, 0x18) if len(mega_bs) >= 0x1c else 0
    mega_points = i64(mega_bs, 0x10) if len(mega_bs) >= 0x18 else 0
    align_name = {0:'NORMAL',1:'SHADOW',2:'PURIFIED'}.get(align, str(align))
    species = species_lookup.get(pid, f'pid{pid}')

    out = {
        'uid_hex': uid_hex, 'uid': uid_signed, 'pokemon_id': pid, 'species_name': species,
        'cp': cp, 'level': cpm_to_level(cpm), 'form': form,
        'iv_atk': iv_atk, 'iv_def': iv_def, 'iv_sta': iv_sta,
        'iv_total': iv_total, 'iv_pct': iv_total * 100 / 45.0,
        'is_shiny': is_shiny, 'is_lucky': is_lucky,
        'gender': gender, 'gender_name': {0: 'UNSET', 1: 'MALE', 2: 'FEMALE', 3: 'GENDERLESS'}.get(gender, str(gender)),
        'is_traded': 1 if trad != 0 else 0,
        'is_hundo': 1 if iv_atk == 15 and iv_def == 15 and iv_sta == 15 else 0,
        'is_zero': 1 if iv_atk == 0 and iv_def == 0 and iv_sta == 0 else 0,
        'alignment': align, 'alignment_name': align_name,
        'costume_decoration_id': costume,
        'move1': move1, 'move2': move2, 'move3': move3,
        'is_powered_up': 1 if num_upgrades > 0 else 0,
        'is_traded_flag_v2': 1 if trad != 0 else 0,
        'pokemon_size_category': size_category,
        'weight_kg': weight, 'height_m': height,
        'is_egg': is_egg,
        # PROTO SCALARS RE-READ EVERY WALK (2026-09-23, user: "Every single pokemon in my bag needs to be rescanned.
        # things can change"). All inside the 0x200 bytes above; offsets from proto_layout.json, proven on 2,899 saved
        # records (s2 cell / ball / hatched / traded time / cp_multiplier: 100% agreement).
        'captured_s2_cell': i64(bs, 0x88),                        # capturedS2CellId_ (SIGNED, as stored before: SQLite INTEGER)
        'pokeball': i32(bs, 0x80),                                # pokeball_ (Holoholo.Rpc.Item)
        'hatched_from_egg': byte(bs, 0xe1),                       # hatchedFromEgg_
        'traded_time_ms': i64(bs, 0x108),                         # tradedTimeMs_
        'buddy_km_walked': f32(bs, 0xc8),                         # buddyKmWalked_
        'buddy_candy_awarded': i32(bs, 0xc4),                     # buddyCandyAwarded_
        'cp_multiplier': f32(bs, 0x7c), 'additional_cpm': f32(bs, 0xac),
        'raw_proto_hex': pb,
        'bread_slots': rec.get('breadSlots'),                      # [[moveType, level], ...] or None (no pointer)
        'bonus_ivs': _bonus(rec.get('bonusBytes')), 'daynight_bonus_ivs': _bonus(rec.get('dayNightBytes')),
        'contest': _contest(rec.get('contestBytes')),
        'fresh_costume': costume, 'fresh_form': form, 'fresh_alignment': align,
        'fresh_pokemon_badge': badge, 'fresh_current_temp_evolution': cur_temp_evo,
        'fresh_has_mega_level': has_mega, 'fresh_has_location_card': has_loc,
        'fresh_bread_mode': bread_mode, 'fresh_is_strong': is_strong,
        'fresh_shiny': is_shiny,
        'fresh_loc_card_enum': loc_card_enum,
        'fresh_natural_art_type': nat_art_type, 'fresh_natural_art_bg': nat_art_bg,
        'fresh_natural_art_full': nat_art_full, 'fresh_day_night': day_night,
        'creation_time_ms': creation_time_ms, 'creation_date': creation_date,
        'mega_Level': mega_level, 'mega_Points': mega_points,
        'was_best_buddy_badge': 1 if badge == 1 else 0,
        'original_owner_name': rec.get('originalOwner'), 'original_owner_nickname': rec.get('originalOwner'),
        'is_favorite_v2': (bs[0xb0] if len(bs) > 0xb0 else None),   # favorite_ @0xb0 (proto_layout.json) -- keep axis 'favorite' (2026-09-17)
        # FUSION, LIVE every walk (2026-09-26, user: "i think 2 are currently fused. So don't count those in the ladder").
        # isComponent_ @0x1b9 = a Reshiram/Zekrom HELD inside a White/Black Kyurem; isFusion_ @0x1ba = that Kyurem. Both
        # System.Boolean (proto_layout.json). Were written only by the one-off _enrich_proto_fields.py -> 2,846 NULL rows.
        'is_component': (bs[0x1b9] if len(bs) > 0x1ba else None),
        'is_fusion': (bs[0x1ba] if len(bs) > 0x1ba else None),
        'nickname': rec.get('nickname'),           # None = read failed (leave the column), '' = no nickname
        'display_read_failed': 1 if rec.get('displayReadFailed') else 0,   # audit F17
        'display_null': 1 if rec.get('displayNull') else 0,                # subset: pointer was NULL (2026-09-02)
        # id_ @0x20 (proto_layout.json PokemonProto id_ offset 32) is the mon's own uid: it must equal the node KEY the walk
        # read at node+0x28. Equal on all 230,603 stored rows of the last 40 snapshots. (H07 2026-09-29)
        'proto_id_matches': (i64(bs, 0x20) & 0xFFFFFFFFFFFFFFFF) == (uid_unsigned & 0xFFFFFFFFFFFFFFFF),
    }
    if out['display_read_failed']:
        # UNKNOWN, NOT ZERO (H07 2026-09-29). Every _DISPLAY_FIELDS value above comes from the display proto (or the loc /
        # mega pointers read THROUGH it), so on a failed or NULL display read they are the 0-defaults of an EMPTY buffer.
        # The UPDATE path already refuses to write them (audit F17) -- but the INSERT of a NEW uid wrote them verbatim: a
        # brand-new shiny / shadow / costume / background catch landed as fresh_shiny=0, fresh_alignment=0, fresh_form=0,
        # i.e. a fabricated PLAIN, and keep_policy judged it in this same run while the pile gate (no phone contact since
        # 2026-09-24) read the same row. None -> NULL, which keep_policy's data-completeness gate (_PROT_COLS) keeps as
        # 'data_incomplete' until a walk reads the display.
        for _k in _DISPLAY_FIELDS:
            out[_k] = None
    return out


# Every parse_pokemon field derived from the display proto (+ its loc / mega sub-pointers) -- see the note at its end.
_DISPLAY_FIELDS = ('is_shiny', 'form', 'alignment', 'alignment_name', 'costume_decoration_id', 'gender', 'gender_name',
                   'fresh_costume', 'fresh_form', 'fresh_alignment', 'fresh_pokemon_badge', 'fresh_current_temp_evolution',
                   'fresh_has_mega_level', 'fresh_has_location_card', 'fresh_bread_mode', 'fresh_is_strong', 'fresh_shiny',
                   'fresh_loc_card_enum', 'fresh_natural_art_type', 'fresh_natural_art_bg', 'fresh_natural_art_full',
                   'fresh_day_night', 'mega_Level', 'mega_Points', 'was_best_buddy_badge')


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def _liveness_hits(sess, ns, cls):
    """Wrap pg.get_script_with_helpers + findSingleton to return the raw hit list."""
    script = pg.get_script_with_helpers(sess)
    try:
        r = script.exports_sync.find_singleton(ns, cls)
        if 'err' in r: raise RuntimeError(f'liveness({ns}.{cls}): {r["err"]}')
        return r.get('hits', [])
    finally:
        script.unload()
        # the liveness scan stops the GC world; if it came back stopped, restart it NOW rather than leave the
        # game frozen for the user to kill (2026-09-09 ANR traces: every Unity thread in sigsuspend).
        try:
            pg.rescue_frozen_world(sess, f'liveness({ns}.{cls})')
        except Exception:
            pass


# _pick_real_bag / _pick_real_svc / _pick_real_dex: NOT CALLED since 2026-09-29 (H06-1). Each picks the biggest /
# busiest copy, which after a graph rebuild is the FROZEN one -- never wire them back in as a fallback for a
# pick_singleton refusal (see step_singletons).
def _pick_real_bag(sess, candidates):
    """Probe each PokemonBagImpl candidate, return the one whose get_AllPokemon walk
    returns > 100 entries. Liveness API can include stale/proxy instances."""
    if len(candidates) == 1: return candidates[0]
    script = pg.get_script_with_helpers(sess)
    try:
        best = None; best_count = -1
        for c in candidates:
            try:
                w = script.exports_sync.bag_walk(c)
                n = len(w)
                _tick(f"   bag candidate {c}: {n} entries")
                if n > best_count: best, best_count = c, n
            except Exception as e:
                _tick(f"   bag candidate {c}: walk failed ({e})")
        if best_count < 100:
            raise RuntimeError(f'no PokemonBagImpl candidate has > 100 entries; best={best_count}')
        return best
    finally:
        script.unload()


_PROBE_SVC_JS = r"""
rpc.exports.probeNumberOfTags = function(addr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, gnt = null;
    while ((m = IL2.cGM(svcCls, iter)) && !m.isNull()) {
        if (IL2.mGN(m).readCString() === 'get_NumberOfTags') { gnt = m; break; }
    }
    try {
        var ret = rI(gnt, ptr(addr), ptr(0), null);
        var n = ret.add(0x10).readS32();
        return {ok:true, n: n};
    } catch(e) { return {ok:false, err: e.toString()}; }
};

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


def _pick_real_svc(sess, candidates):
    """Probe each TaggingRpcService candidate by calling get_NumberOfTags. The real
    service returns a small positive int (~10-30); stale ones throw or return junk."""
    if len(candidates) == 1: return candidates[0]
    script = pg.get_script_with_helpers(sess, _PROBE_SVC_JS)
    try:
        best = None; best_n = -1
        for c in candidates:
            try:
                r = script.exports_sync.probe_number_of_tags(c)
                n = r.get('n', -1) if r.get('ok') else -1
                _tick(f"   svc candidate {c}: NumberOfTags={n}")
                if 0 < n < 200 and n > best_n: best, best_n = c, n
            except Exception as e:
                _tick(f"   svc candidate {c}: probe failed ({e})")
        if best is None:
            raise RuntimeError(f'no TaggingRpcService candidate has a plausible NumberOfTags')
        return best
    finally:
        script.unload()


def _pick_real_dex(sess, candidates):
    """Probe each PokedexImpl candidate; pick whichever dict has 500-4000 entries."""
    if len(candidates) == 1: return candidates[0]
    script = pg.get_script_with_helpers(sess, _PROBE_SVC_JS)
    try:
        best = None; best_n = -1
        for c in candidates:
            try:
                r = script.exports_sync.probe_dex_count(c)
                n = r.get('n', -1) if r.get('ok') else -1
                _tick(f"   dex candidate {c}: dict count={n}")
                if 500 <= n <= 4000 and n > best_n: best, best_n = c, n
            except Exception as e:
                _tick(f"   dex candidate {c}: probe failed ({e})")
        if best is None:
            raise RuntimeError(f'no PokedexImpl candidate has a plausible dict size')
        return best
    finally:
        script.unload()


def step_singletons(sess):
    """Cache PokemonBagImpl, TaggingRpcService, PokedexImpl singleton pointers.

    Returns dict {bag, svc, dex}. Each is the address-as-string.
    """
    # CACHED FIRST (2026-09-12, "speed and precision"): three liveness scans cost ~18 s of every recrawl and
    # each one stops the GC world. pg.pick_singleton keeps the address per game pid and re-validates it with
    # the same plausibility probes used below (bag > 100 entries, 0 < tags < 200, dex dict 500..4000), so a
    # hit is exact and a miss falls back to the scan.
    # NO FALLBACK PICKER (2026-09-29, H06-1). pick_singleton already runs the liveness scan itself on a cache miss, and
    # for these three classes it resolves the LIVE service graph (pg.live_graph / pg._same_graph_pick). When it RAISES,
    # it is refusing to guess between two graphs. The old `except Exception -> _pick_real_bag/_svc/_dex(scan)` turned
    # that refusal into the pre-fix "biggest bag / most tags / biggest dex" pick -- the one that read the FROZEN graph
    # (four culls, 2026-09-29) -- behind a "cached lookup failed -- scanning" tick nobody saw. A refused pick now fails
    # the walk: a recrawl that stops is simply re-run, while a walk of a stale graph rewrites pokemon.db, the dex files,
    # the tag mirror and the pile from it (and a second one purges the rows of real, present mons).
    out = {}
    for key, ns, cls in (('bag', 'Niantic.Holoholo.Internal', 'PokemonBagImpl'),
                         ('svc', 'Niantic.Holoholo.Tagging', 'TaggingRpcService'),
                         ('dex', 'Niantic.Holoholo.Internal', 'PokedexImpl')):
        try:
            out[key] = pg.pick_singleton(sess, ns, cls)
        except Exception as e:
            raise RuntimeError(f"{key}: no trustworthy live {ns}.{cls} ({type(e).__name__}: {e}) -- refusing to walk a "
                               f"guessed service graph (the old biggest-copy fallback read the frozen one); re-run the "
                               f"recrawl") from e
        _tick(f"   {key} @ {out[key]}")
    return out


def step_walk_bag(script, bag_addr, retries=2):
    """Single bag walk. Returns (entries, meta) where meta = {declared, walked, truncated, ...}.

    A TRUNCATED walk is retried (the linked list is walked live while the GC may move nodes, so a
    transient node error is usually gone on the next pass). If every attempt is short we RAISE:
    the 2-crawl-confirm purge in step_reconcile_db deletes rows that are absent from the walk, and
    a short walk that still clears the old 70%-of-prior-bag floor would delete real, present mons.
    Refusing to proceed is the only safe answer -- the crawl can simply be re-run. (lockdown 2026-09-02)
    """
    last = None
    for attempt in range(1, retries + 2):
        r = script.exports_sync.pipeline_walk(bag_addr)
        if isinstance(r, list):          # defensive: older JS shape (plain array, no metadata)
            # no metadata = completeness UNKNOWN -> flagged short (H07 2026-09-29): the purge is skipped and rows this
            # payload did not carry keep their in_bag. short=None used to read as "not short" in step_reconcile_db, so an
            # unprovable walk counted as complete and could reach the DELETE.
            return r, {'declared': None, 'walked': len(r), 'truncated': None, 'short': True,
                       'truncReason': 'legacy JS payload -- no truncation metadata'}
        last = r
        if not r.get('truncated'):
            if r.get('short') and attempt <= retries:
                # RE-WALK A SHORT WALK FIRST (H07 2026-09-29). declared == walked on the 05:20 walk (5632 of 5632), so a short
                # walk is not the feared sentinel off-by-one: it is a release / catch that cut the chain while it was being
                # read (a removed LinkedListNode's next is nulled -> the loop stops early), and the next pass is normally
                # whole. Accepting it at once cost the unread tail its place in the bag for the whole pass.
                _tick(f"   [WARN] bag walk attempt {attempt} SHORT: walked {r.get('walked')} of declared "
                      f"{r.get('declared')} -- re-walking")
                continue
            if r.get('short'):
                # SOFT: fewer records than the list's declared _size. Reported loudly and it blocks
                # the purge, but it does NOT abort -- see the JS note (a sentinel head would make
                # `declared` permanently off-by-one and aborting there would brick every crawl).
                _tick(f"   [WARN] bag walk is SHORT of the declared list size: walked "
                      f"{r.get('walked')} of {r.get('declared')} (delta "
                      f"{(r.get('declared') or 0) - (r.get('walked') or 0)}). Continuing, but the "
                      f"2-crawl-confirm purge will be SKIPPED. If this delta is constant every run "
                      f"it is a counting artefact, not data loss -- ghosts will accumulate until it "
                      f"is investigated.")
            return r.get('entries', []), r
        _tick(f"   [WARN] bag walk attempt {attempt} TRUNCATED: walked {r.get('walked')} of "
              f"declared {r.get('declared')} ({r.get('truncReason')}) -- retrying")
    raise RuntimeError(
        "bag walk TRUNCATED on every attempt (walked %s of declared %s; %s). Refusing to continue: "
        "a truncated walk feeds the 2-crawl-confirm purge and can DELETE present mons. "
        "Re-run the crawl." % (last.get('walked'), last.get('declared'), last.get('truncReason')))


def step_reconcile_db(conn, entries, species_lookup, walk_meta=None, allow_purge=True):
    """Mark in_bag, insert new UIDs, refresh fresh_*/size for every entry."""
    c = conn.cursor()
    cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
    if 'in_bag' not in cols: c.execute("ALTER TABLE pokemon ADD COLUMN in_bag INTEGER")
    # The five cosmetic columns the pipeline now writes itself (previously only parse_fresh.py /
    # _fresh_rescan_safe.py wrote them, and neither is a pipeline step). Create them if absent so a
    # fresh DB does not fail the INSERT below. (lockdown 2026-09-02)
    for _col in ('fresh_loc_card_enum', 'fresh_natural_art_type', 'fresh_natural_art_bg',
                 'fresh_natural_art_full', 'fresh_day_night'):
        if _col not in cols:
            c.execute(f"ALTER TABLE pokemon ADD COLUMN {_col} INTEGER")
            cols.add(_col)
    # is_egg is written by the INSERT/UPDATE below as of 2026-09-07; create it on any DB that
    # predates the column so the INSERT cannot fail. No-op on the live DB, which already has it.
    if 'is_egg' not in cols:
        c.execute("ALTER TABLE pokemon ADD COLUMN is_egg INTEGER")
        cols.add('is_egg')

    parsed = []
    skipped_pid0 = 0          # pid0 records that are NOT eggs (also counted in skipped_unparsed) -- see below
    skipped_eggs = 0
    skipped_unparsed = 0
    unread_uids = set()       # records the walk REACHED but could not read: present in the bag, never "gone" (H07)
    skipped_idmismatch = 0    # records whose proto id_ != the node key (also counted in skipped_unparsed) (H07)
    for rec in entries:
        p = parse_pokemon(rec, species_lookup)
        if not p:
            # `if not p: continue` used to drop these with NO counter and NO message, while the
            # adjacent pid0 skip WAS counted -- so a proto whose bytes could not be read looked
            # exactly like "nothing to do". Split eggs (a legitimate skip) from genuine parse
            # failures (which mean the walk data is bad and must block the purge). isEgg_ is at
            # PokemonProto+0x50, inside the 0x200 already dumped. (lockdown 2026-09-02)
            if _rec_is_egg(rec):
                skipped_eggs += 1
            else:
                skipped_unparsed += 1
                _u = _rec_uid_hex(rec)
                if _u:
                    unread_uids.add(_u)
            continue
        if not p['pokemon_id']:
            # pid0 (H07 2026-09-29). An EGG is pokemonId_ 0 with isEgg_ (System.Boolean @0x50) == 1 (eggs_walker.py, verified
            # on 9 eggs), and every walk carries them: 05:20 walked 5632 = 5623 mons + the game's own get_EggCount 9, and this
            # skip counted exactly 9 -- logged as "parse-failure entries (not real bag mons)" while skipped_eggs stayed 0 for
            # ever. The dangerous half was the rest: a pid0 record whose isEgg_ is NOT 1 is a real bag node whose proto read
            # back zeroed (a freed / reused object). It was dropped with no effect on the purge, so the same mon misread on
            # two walks running was DELETED from pokemon.db. It is now unreadable-but-present: counted in skipped_unparsed
            # (the purge is skipped) and kept in the bag on its last-read row.
            if _rec_is_egg(rec):
                skipped_eggs += 1
            else:
                skipped_pid0 += 1
                skipped_unparsed += 1
                unread_uids.add(p['uid_hex'])
            continue
        if not p.get('proto_id_matches', True):
            # THE NODE'S VALUE IS NOT THIS MON (H07 2026-09-29): its proto's own id_ differs from the node key, i.e. the
            # value pointer was read mid-replacement or points at a freed-and-reused object (the tag cache already showed
            # hundo protos reused by eggs, 2026-09-29 02:27). Writing it would put ANOTHER mon's species / IVs / cosmetics
            # on this uid's row -- a real hundo could be judged as someone else's fodder and reach the pile. It is present
            # but unreadable: purge skipped, row kept as last read.
            skipped_idmismatch += 1
            skipped_unparsed += 1
            unread_uids.add(p['uid_hex'])
            continue
        parsed.append(p)
    if skipped_idmismatch:
        _tick(f"   [WARN] {skipped_idmismatch} record(s) carry a proto whose id_ is NOT the node's uid -- not written "
              f"(kept as last read), purge SKIPPED")
    if skipped_eggs:
        _tick(f"   skipped {skipped_eggs} eggs (pokemonId 0 + isEgg_ -- not bag mons)")
    if skipped_pid0:
        _tick(f"   [WARN] {skipped_pid0} pid0 record(s) are NOT eggs (isEgg_ != 1): real bag nodes whose proto read back "
              f"zeroed -- kept in the bag on their last-read row, 2-crawl-confirm purge SKIPPED: "
              f"{', '.join(sorted(unread_uids)[:10])}")
    if skipped_unparsed - skipped_pid0 - skipped_idmismatch:
        _tick(f"   [WARN] {skipped_unparsed - skipped_pid0 - skipped_idmismatch} entries FAILED to parse (no protoBytes) -- the walk "
              f"data is incomplete; the 2-crawl-confirm purge will be SKIPPED this run")

    # current-bag-only: remember who was already missing last crawl + the prior bag
    # size, so the end-of-step purge can delete CONFIRMED-gone mons (missing two
    # crawls running) without risking a present mon a single partial/frozen walk missed.
    prev_missing = {r[0] for r in c.execute("SELECT uid_hex FROM pokemon WHERE in_bag=0").fetchall()}
    prior_inbag = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1").fetchone()[0]
    # A walk that did NOT reach the end of the list (short after its re-walks, or a legacy payload) says nothing about the
    # rows it never got to: when the GAME'S OWN COUNT proves mons were missed (get_PokemonOnlyCount > mons this walk
    # reached) they keep the in_bag the last walk gave them (walked rows are set to 1 below). Clearing them dropped a present
    # tail out of keep_policy, the tag files the sync pushes and the report ("released N") for a whole pass. A short walk
    # that still reached every mon the game counts (a counting artefact) clears normally -- keeping rows on a mere `short`
    # flag would leave a released mon in_bag=1 for ever, holding a ladder slot a real copy needs. A record that was reached
    # but could not be read is PRESENT: it stays in the bag on its last-read row. (H07 2026-09-29)
    _unfinished = bool((walk_meta or {}).get('short')) or bool((walk_meta or {}).get('truncated'))
    _gm0 = ((walk_meta or {}).get('game') or {}).get('get_PokemonOnlyCount')
    _seen0 = len({p['uid_hex'] for p in parsed} | unread_uids)
    _missed = _unfinished and isinstance(_gm0, int) and _gm0 > _seen0
    if _missed:
        _tick(f"   [WARN] the walk reached {_seen0} of the {_gm0} mons the game counts -- the {_gm0 - _seen0} it never "
              f"reached keep their in_bag from the last walk")
    else:
        c.execute("UPDATE pokemon SET in_bag=0")
    if unread_uids:
        c.executemany("UPDATE pokemon SET in_bag=1 WHERE uid_hex=?", [(u,) for u in unread_uids])
    db_uids = {r[0] for r in c.execute("SELECT uid_hex FROM pokemon").fetchall()}
    new_uids = {p['uid_hex'] for p in parsed} - db_uids
    # A NEW uid whose display proto could not be read is NOT ingested on this walk (H07 2026-09-29). Its shiny / shadow /
    # costume / form / background are unknown: the old INSERT wrote the empty buffer's zeros (a fabricated plain that
    # keep_policy judged in this same run and the DB-only pile gate passed), and even as NULLs ('data_incomplete', kept)
    # it would still sit in a plain ladder and could push a REAL plain copy out of its top-N into the pile. It is present,
    # so it counts as unread (purge skipped) and it is inserted by the first walk that reads its display.
    _blind_new = {p['uid_hex'] for p in parsed if p['uid_hex'] in new_uids and p.get('display_read_failed')}
    if _blind_new:
        parsed = [p for p in parsed if p['uid_hex'] not in _blind_new]
        new_uids -= _blind_new
        unread_uids |= _blind_new
        skipped_unparsed += len(_blind_new)
        _tick(f"   [WARN] {len(_blind_new)} NEW mon(s) with an unreadable display proto -- NOT ingested until a walk reads "
              f"their shiny/shadow/costume/form (purge SKIPPED): {', '.join(sorted(_blind_new)[:10])}")
    inserted = 0; shadow_inserted = 0
    for p in parsed:
        if p['uid_hex'] not in new_uids: continue
        if p['fresh_alignment'] == 1: shadow_inserted += 1
        c.execute("""INSERT INTO pokemon
            (uid_hex, uid, pokemon_id, species_name, cp, level, form,
             iv_atk, iv_def, iv_sta, iv_total, iv_pct,
             is_shiny, is_lucky, is_traded, is_hundo, is_zero,
             alignment, alignment_name, costume_decoration_id,
             move1, move2, move3,
             is_powered_up, is_traded_flag_v2,
             in_bag, pokemon_size_category, weight_kg, height_m, is_egg,
             fresh_in_heap, fresh_costume, fresh_form, fresh_alignment, fresh_pokemon_badge,
             fresh_current_temp_evolution, fresh_has_mega_level, fresh_has_location_card,
             fresh_bread_mode, fresh_is_strong, fresh_shiny,
             fresh_loc_card_enum, fresh_natural_art_type, fresh_natural_art_bg,
             fresh_natural_art_full, fresh_day_night)
            VALUES (?,?,?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?,?)""",
            (p['uid_hex'], p['uid'], p['pokemon_id'], p['species_name'], p['cp'], p['level'], p['form'],
             p['iv_atk'], p['iv_def'], p['iv_sta'], p['iv_total'], p['iv_pct'],
             p['is_shiny'], p['is_lucky'], p['is_traded'], p['is_hundo'], p['is_zero'],
             p['alignment'], p['alignment_name'], p['costume_decoration_id'],
             p['move1'], p['move2'], p['move3'],
             p['is_powered_up'], p['is_traded_flag_v2'],
             1, p['pokemon_size_category'], p['weight_kg'], p['height_m'], p['is_egg'],
             1, p['fresh_costume'], p['fresh_form'], p['fresh_alignment'], p['fresh_pokemon_badge'],
             p['fresh_current_temp_evolution'], p['fresh_has_mega_level'], p['fresh_has_location_card'],
             p['fresh_bread_mode'], p['fresh_is_strong'], p['fresh_shiny'],
             p['fresh_loc_card_enum'], p['fresh_natural_art_type'], p['fresh_natural_art_bg'],
             p['fresh_natural_art_full'], p['fresh_day_night']))
        inserted += 1

    # FULL refresh of every mutable column for every parsed entry (captures
    # powerups: cp/level; TMs: move1/2/3; evolutions: pokemon_id/species/form;
    # purification: iv shift+alignment). species_name is guarded so a 'pidN'
    # placeholder never overwrites a previously-resolved real name.
    # is_egg is NO LONGER an inert column: preflight_transfer.py's EGG bucket (2026-09-07) BLOCKS
    # the pile on `is_egg != 0` unconditionally, and self-arms its NULL sub-clause off "does any row
    # carry is_egg != 0". So a recrawl that flipped a stored 1 back to 0 would silently disarm BOTH
    # halves of a pile gate -- the exact unblocking direction this project forbids. The live proto is
    # the better oracle for a row that has never been read, so the INSERT above takes it verbatim;
    # but for a row already FLAGGED as an egg the update below refuses to clear the flag on its own
    # authority and says so out loud instead. Sticky-on costs at worst a pile that keeps blocking
    # (a nuisance, and fail-closed); sticky-off would hand an egg to an irreversible release list.
    # (2026-09-07)
    # SUPERSEDED 2026-09-29 (H07): is_egg now MIRRORS the live isEgg_. Both premises above expired. (1) Since 2026-09-08
    # the EGG bucket blocks only the egg SHAPE (the bit AND no CP/IVs) and passes a CP-bearing row with the bit as a recent
    # hatch, so a sticky 1 on a real mon protects nothing there. (2) The NULL sub-clause fires only on a NULL is_egg, and
    # every row a walk marks in_bag=1 gets is_egg written (the INSERT and both UPDATEs below), so no pile row carries one.
    # What sticky-on DID do: prune_tags' verify and reconcile_tags read is_egg=1 as "a hatchling the game ignores tag
    # writes on" and excuse its drift -- for ever, because the flag never cleared. Fennekin 67001d9d6350a390 (hatched
    # 2026-09-19; isEgg_ byte 00 in all 133 stored protos 2026-09-23..29) was still excused on 2026-09-29, the only in-bag
    # row with the flag; Torchic, Scorbunny, Bulbasaur and Grookey carried it until they were released.
    _egg_flagged = {r[0] for r in c.execute(
        "SELECT uid_hex FROM pokemon WHERE is_egg IS NOT NULL AND is_egg <> 0").fetchall()}
    _egg_conflicts = []

    disp_failed = 0
    disp_null = 0                     # subset of disp_failed: the display POINTER itself was NULL
    for p in parsed:
        if p['uid_hex'] in _egg_flagged and not p['is_egg']:
            _egg_conflicts.append(p['uid_hex'])
        if p.get('display_null'):
            disp_null += 1
        if p.get('display_read_failed'):
            # display proto exists but its read failed THIS walk: a full update would write a fake
            # all-zero 'plain' (form=0, not shiny, no costume) indistinguishable from a real plain --
            # and a plain looks cull-eligible. Refresh only the NON-display fields; the prior
            # cosmetic values survive. (audit F17)
            disp_failed += 1
            c.execute("""UPDATE pokemon SET in_bag=1,
                pokemon_id=?,
                species_name=CASE WHEN ? GLOB 'pid[0-9]*' THEN species_name ELSE ? END,
                cp=?, level=?,
                iv_atk=?, iv_def=?, iv_sta=?, iv_total=?, iv_pct=?,
                is_lucky=?, is_traded=?, is_hundo=?, is_zero=?,
                move1=?, move2=?, move3=?,
                is_powered_up=?, is_traded_flag_v2=?,
                pokemon_size_category=COALESCE(?, pokemon_size_category), weight_kg=?, height_m=?,
                is_egg=?
                WHERE uid_hex=?""",
                (p['pokemon_id'],
                 p['species_name'], p['species_name'],
                 p['cp'], p['level'],
                 p['iv_atk'], p['iv_def'], p['iv_sta'], p['iv_total'], p['iv_pct'],
                 p['is_lucky'], p['is_traded'], p['is_hundo'], p['is_zero'],
                 p['move1'], p['move2'], p['move3'],
                 p['is_powered_up'], p['is_traded_flag_v2'],
                 p['pokemon_size_category'], p['weight_kg'], p['height_m'],
                 p['is_egg'],
                 p['uid_hex']))
            continue
        c.execute("""UPDATE pokemon SET in_bag=1,
            pokemon_id=?,
            species_name=CASE WHEN ? GLOB 'pid[0-9]*' THEN species_name ELSE ? END,
            cp=?, level=?, form=?,
            iv_atk=?, iv_def=?, iv_sta=?, iv_total=?, iv_pct=?,
            is_shiny=?, is_lucky=?, is_traded=?, is_hundo=?, is_zero=?,
            alignment=?, alignment_name=?, costume_decoration_id=?,
            move1=?, move2=?, move3=?,
            is_powered_up=?, is_traded_flag_v2=?,
            pokemon_size_category=COALESCE(?, pokemon_size_category), weight_kg=?, height_m=?,
            is_egg=?,
            fresh_alignment=?, fresh_shiny=?, fresh_costume=?, fresh_bread_mode=?,
            fresh_pokemon_badge=?, fresh_is_strong=?, fresh_has_location_card=?,
            fresh_has_mega_level=?, fresh_current_temp_evolution=?, fresh_form=?,
            fresh_loc_card_enum=?, fresh_natural_art_type=?, fresh_natural_art_bg=?,
            fresh_natural_art_full=?, fresh_day_night=?
            WHERE uid_hex=?""",
            (p['pokemon_id'],
             p['species_name'], p['species_name'],
             p['cp'], p['level'], p['form'],
             p['iv_atk'], p['iv_def'], p['iv_sta'], p['iv_total'], p['iv_pct'],
             p['is_shiny'], p['is_lucky'], p['is_traded'], p['is_hundo'], p['is_zero'],
             p['alignment'], p['alignment_name'], p['costume_decoration_id'],
             p['move1'], p['move2'], p['move3'],
             p['is_powered_up'], p['is_traded_flag_v2'],
             p['pokemon_size_category'], p['weight_kg'], p['height_m'],
             p['is_egg'],
             p['fresh_alignment'], p['fresh_shiny'], p['fresh_costume'], p['fresh_bread_mode'],
             p['fresh_pokemon_badge'], p['fresh_is_strong'], p['fresh_has_location_card'],
             p['fresh_has_mega_level'], p['fresh_current_temp_evolution'], p['fresh_form'],
             p['fresh_loc_card_enum'], p['fresh_natural_art_type'], p['fresh_natural_art_bg'],
             p['fresh_natural_art_full'], p['fresh_day_night'],
             p['uid_hex']))
    if _egg_conflicts:
        _tick(f"   {len(_egg_conflicts)} hatchling(s) read isEgg_=0 this walk after a stored is_egg=1 -- the flag "
              f"cleared on the device, is_egg now 0: {', '.join(_egg_conflicts[:10])}")
    if disp_failed:
        _tick(f"   [WARN] {disp_failed} entries had display-proto read failures "
              f"({disp_null} of them a NULL display pointer) -- kept their prior cosmetic fields "
              f"(form/shiny/costume/art-bg/loc-card) instead of writing zeros (audit F17)")
    # gender (display proto +0x14): the canonical INSERT/UPDATE above doesn't carry it, so a fresh
    # catch would land with NULL gender -- which the gender-locked evolve logic must NOT guess at
    # (a NULL-gender male Combee got wrongly tagged 'evolve'). Patch every parsed mon's gender here.
    for p in parsed:
        if p.get('display_read_failed'):
            continue   # gender comes from the display proto -- keep the prior value (audit F17)
        c.execute("UPDATE pokemon SET gender=?, gender_name=? WHERE uid_hex=?",
                  (p['gender'], p['gender_name'], p['uid_hex']))

    # EVERY MON'S PROTO SCALARS, EVERY WALK (2026-09-23): catch place, ball, hatched, traded time, buddy progress,
    # cp multipliers and the raw bytes were filled ONCE (May) and never again -- 2,651 in-bag mons had no catch
    # location, which the nundo "farthest from Atlanta" pick needs. lat/lon = the S2 cell centre (how the old
    # columns were built: 300/300 match). A zero cell (unknown) never overwrites a stored location.
    try:
        import s2sphere as _s2
    except Exception:
        _s2 = None
    _ball_names = dict(c.execute("SELECT pokeball, MAX(pokeball_name) FROM pokemon WHERE pokeball_name IS NOT NULL "
                                 "GROUP BY pokeball").fetchall())
    _stamp = datetime.datetime.now().isoformat(timespec='seconds')
    _have = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
    for _col, _ty in (('last_scanned', 'TEXT'), ('bread_moves', 'TEXT'), ('bread_max_level', 'INTEGER'),
                      ('fresh_bonus_atk', 'INTEGER'), ('fresh_bonus_def', 'INTEGER'), ('fresh_bonus_sta', 'INTEGER'),
                      ('fresh_daynight_bonus_atk', 'INTEGER'), ('fresh_daynight_bonus_def', 'INTEGER'),
                      ('fresh_daynight_bonus_sta', 'INTEGER'), ('contest_end_ms', 'INTEGER'), ('contest_free_up_ms', 'INTEGER')):
        if _col not in _have:
            c.execute("ALTER TABLE pokemon ADD COLUMN %s %s" % (_col, _ty))
    _rows = []
    for p in parsed:
        if 'captured_s2_cell' not in p:
            continue
        _cell = p['captured_s2_cell'] or None
        _lat = _lon = None
        if _cell and _s2 is not None:
            try:
                _ll = _s2.CellId(_cell & 0xFFFFFFFFFFFFFFFF).to_lat_lng()   # the cell id is unsigned
                _lat, _lon = _ll.lat().degrees, _ll.lng().degrees
            except Exception:
                _lat = _lon = None
        _bs = p.get('bread_slots')
        _bv = p.get('bonus_ivs') or (None, None, None)
        _dv = p.get('daynight_bonus_ivs') or (None, None, None)
        _ct = p.get('contest') or (None, None)
        _rows.append((_cell, _lat, _lon, p['pokeball'], _ball_names.get(p['pokeball']), p['hatched_from_egg'],
                      p['hatched_from_egg'], p['traded_time_ms'] or None, p['buddy_km_walked'], p['buddy_candy_awarded'],
                      p['cp_multiplier'], p['additional_cpm'], p['raw_proto_hex'], _stamp,
                      json.dumps(_bs) if _bs is not None else None, (max((lv for _, lv in _bs), default=0) if _bs else None),
                      _bv[0], _bv[1], _bv[2], _dv[0], _dv[1], _dv[2], _ct[0] or None, _ct[1] or None,
                      p['uid_hex']))
    c.executemany("UPDATE pokemon SET captured_s2_cell=COALESCE(?, captured_s2_cell), lat=COALESCE(?, lat), "
                  "lon=COALESCE(?, lon), pokeball=?, pokeball_name=COALESCE(?, pokeball_name), hatched_from_egg=?, "
                  "is_hatched_from_egg=?, traded_time_ms=COALESCE(?, traded_time_ms), buddy_km_walked=?, "
                  "buddy_candy_awarded=?, cp_multiplier=?, additional_cpm=?, raw_proto_hex=?, last_scanned=?, "
                  "bread_moves=?, bread_max_level=?, fresh_bonus_atk=?, fresh_bonus_def=?, fresh_bonus_sta=?, "
                  "fresh_daynight_bonus_atk=?, fresh_daynight_bonus_def=?, fresh_daynight_bonus_sta=?, "
                  "contest_end_ms=?, contest_free_up_ms=? "
                  "WHERE uid_hex=?", _rows)
    # x[14] (bread_moves) is '[]' for every mon with the pointer and x[16] is a 0 bonus level on 1,864 mons: the log said
    # "Max moves 5623, bonus IVs 1864" for 289 and 2. Count what the words say. (H07 2026-09-29)
    _nb = sum(1 for x in _rows if x[15] is not None)
    _nv = sum(1 for x in _rows if (x[16] or 0) + (x[17] or 0) + (x[18] or 0) > 0)
    _nc = sum(1 for x in _rows if x[22] is not None)
    _tick(f"   rescanned {len(_rows)} mons' proto scalars + pointers (Max moves {_nb}, bonus IVs {_nv}, showcase entries {_nc})")

    # creation_time_ms / creation_date (capture date): the canonical INSERT/UPDATE above don't carry it
    # either, so EVERY fresh catch had been landing with a NULL capture date (creationTimeMs_ @0xa0,
    # reflection-verified). Fill it for every parsed mon; COALESCE keeps an existing good value so a
    # transient bad read never clobbers it (creation time is immutable). (2026-06-05)
    for p in parsed:
        if p.get('creation_time_ms'):
            c.execute("UPDATE pokemon SET creation_time_ms=COALESCE(creation_time_ms,?), "
                      "creation_date=COALESCE(creation_date,?) WHERE uid_hex=?",
                      (p['creation_time_ms'], p['creation_date'], p['uid_hex']))

    # mega_Level / mega_Points (PokemonMegaEvolutionLevelProto, parsed from the already-dumped megaBytes):
    # the canonical INSERT/UPDATE only carried the has-mega BOOLEAN, so the actual Level/Points were stale
    # (last set by a one-off script -> 9 mons wrong). SET (not COALESCE) when mega data is present, since
    # the level CLIMBS as the user mega-evolves (1->2->3). (2026-06-05)
    for p in parsed:
        if p.get('fresh_has_mega_level') and 1 <= (p.get('mega_Level') or 0) <= 3:
            c.execute("UPDATE pokemon SET mega_Level=?, mega_Points=? WHERE uid_hex=?",
                      (p['mega_Level'], p['mega_Points'], p['uid_hex']))

    # was_best_buddy_badge (Best Buddy tag) = PokemonBadge==1 (the only badge in use; the pipeline read the
    # badge but never derived this). original_owner_name/nickname (Traded-by-E+F tag) from
    # originalOwnerNickname_@0x100, now read in the bag-walk. Both had been stale (a one-off script); wire
    # them in so new best-buddies / E+F trades are captured every crawl. (2026-06-05)
    # favorite + nickname, LIVE every crawl (2026-09-17). Both were written only by retired one-off scripts, so
    # is_favorite_v2 was stale and new catches read NULL -- the same silent-stale class as capture date and mega.
    # SET, not COALESCE: a star can be removed and a nickname cleared.
    for p in parsed:
        if p.get('is_component') is not None:          # SET: an unfuse must clear it (2026-09-26)
            c.execute("UPDATE pokemon SET is_component=?, is_fusion=? WHERE uid_hex=?",
                      (1 if p['is_component'] else 0, 1 if p['is_fusion'] else 0, p['uid_hex']))
        if p.get('is_favorite_v2') is not None:
            c.execute("UPDATE pokemon SET is_favorite_v2=? WHERE uid_hex=?", (p['is_favorite_v2'], p['uid_hex']))
        if p.get('nickname') is not None:
            c.execute("UPDATE pokemon SET nickname=? WHERE uid_hex=?", (p['nickname'] or None, p['uid_hex']))
    for p in parsed:
        if not p.get('display_read_failed'):     # the badge is a DISPLAY field: a failed read is unknown, not 0 (H07)
            c.execute("UPDATE pokemon SET was_best_buddy_badge=? WHERE uid_hex=?",
                      (p.get('was_best_buddy_badge', 0), p['uid_hex']))
        if p.get('original_owner_name'):
            c.execute("UPDATE pokemon SET original_owner_name=?, original_owner_nickname=? WHERE uid_hex=?",
                      (p['original_owner_name'], p['original_owner_nickname'], p['uid_hex']))

    # 2-crawl-confirm purge (keeps the DB current-bag-only; no ghost accumulation).
    # Delete a mon only if it is missing THIS walk AND was already missing last crawl
    # (in prev_missing) = gone two runs = genuinely transferred. Skipped entirely when
    # the walk is grossly short (<70% of last bag -> suspect a partial/frozen walk),
    # so a bad walk never deletes anyone. A one-off missed-present mon reappears next
    # crawl and so never survives in prev_missing -> it is never wrongly deleted.
    walked = {p['uid_hex'] for p in parsed} | unread_uids     # an unreadable record is still PRESENT (H07)
    # The 70%-of-prior-bag floor is NOT sufficient on its own: against a 5559 bag it permits losing
    # 1668 real mons and still calling the walk "complete", and two identically-truncated walks in a
    # row reach this unfiltered DELETE. Require, in addition, that the JS walk reported itself
    # COMPLETE (walked >= declared list length) and that nothing failed to parse. Any doubt at all
    # skips the purge -- ghosts are harmless, a wrong DELETE is not. (lockdown 2026-09-02)
    _meta = walk_meta or {}
    _walk_truncated = bool(_meta.get('truncated'))
    _declared = _meta.get('declared')
    _short_of_declared = bool(_meta.get('short'))
    # TWO MORE PROOFS BEFORE A DELETE (H07 2026-09-29).
    # (a) THE GAME'S OWN COUNTS. main() reads PokemonBagImpl.get_PokemonOnlyCount / get_EggCount right after the walk
    #     (05:20: 5623 mons + 9 eggs == this walk's 5623 parsed + 9 eggs). A mon the parser dropped, a garbage record taken
    #     for an egg or a mon, or a release between the walk and the counter read all break the equality: the walk is then
    #     not a faithful copy of the bag, and nothing is deleted on it. Unreadable counters = unproven.
    _g = _meta.get('game') or {}
    _g_mons, _g_eggs = _g.get('get_PokemonOnlyCount'), _g.get('get_EggCount')
    _n_parsed = len({p['uid_hex'] for p in parsed})
    _counts_agree = (isinstance(_g_mons, int) and isinstance(_g_eggs, int)
                     and _g_mons == _n_parsed and _g_eggs == skipped_eggs)
    # (b) THE ACCOUNT. account_guard.check() only WARNS when it cannot read the trainer name, and the 70% floor is measured
    #     against the LAST walk's bag: one walk of another trainer's 939-mon bag flips this set's 5623 rows to in_bag=0 (no
    #     purge, 939 < 70%), and a second passes the floor against 939 and DELETES all 5623. The purge needs the trainer
    #     positively matched THIS run (main() sets account_verified).
    _acct_ok = _meta.get('account_verified') is True
    walk_complete = (len(parsed) >= 0.70 * max(prior_inbag, 1)
                     and not _walk_truncated
                     and not _short_of_declared
                     and _declared is not None
                     and skipped_unparsed == 0
                     and _counts_agree
                     and _acct_ok)
    if not walk_complete:
        _tick("   [WARN] purge SKIPPED -- walk not provably complete "
              f"(parsed={len(parsed)} prior_inbag={prior_inbag} declared={_declared} "
              f"truncated={_walk_truncated} short={_short_of_declared} unparsed={skipped_unparsed} "
              f"game={_g_mons} mons + {_g_eggs} eggs vs walk {_n_parsed} + {skipped_eggs} "
              f"account_verified={_meta.get('account_verified')})")
    _departed = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=0").fetchone()[0]
    purged = 0
    # A FROZEN WALK IS COMPLETE, FULL-SIZE AND AGREES WITH ITS OWN COUNTERS (H03, 2026-09-29). Every guard above measures
    # the walk against itself or against the same bag object: the 05:06 / 05:09 / 05:11 walks were 5,661 of 5,661
    # declared, of a graph frozen at 04:59:53, and get_PokemonOnlyCount of that same frozen bag agrees with them. A mon
    # seen by one live walk and missing from two frozen ones is DELETED while it sits in the bag (replayed on the real
    # 05:20 -> 05:11 -> 05:11 sequence: Dratini, Ekans, Quilava, Shieldon, Staravia). The walk tripwires decide
    # liveness (step_freshness_graph); anything but a clean verdict keeps every row.
    if walk_complete and prev_missing and not allow_purge:
        _tick("   [WARN] purge SKIPPED -- the walk tripwires could not prove this walk live (see freshness_graph)")
    if walk_complete and prev_missing and allow_purge:
        gone = [(u,) for u in prev_missing if u not in walked]
        # MASS-PURGE BRAKE (H07 2026-09-29). The 70% floor is measured against the LAST walk's bag, so two self-consistent
        # partial reads in a row (a bag caught mid-fill after a graph rebuild, or any wrong bag that slips past the gates
        # above) ratchet it down and the second DELETEs every row the first one missed. The largest purge in the 144 DB
        # snapshots of 2026-09-23..29 is 123 rows; a purge of more than half the bag this walk saw is refused (the rows stay
        # in_bag=0, excluded from everything). Deliberate mass release: POGO_ALLOW_MASS_PURGE=1 for one run.
        _brake = max(250, len(walked) // 2)
        if len(gone) > _brake and os.environ.get('POGO_ALLOW_MASS_PURGE') != '1':
            _tick(f"   [WARN] purge REFUSED -- {len(gone)} rows would be deleted, more than half the {len(walked)}-mon bag "
                  f"this walk saw (brake {_brake}); they stay in_bag=0. A real mass release: re-run with "
                  f"POGO_ALLOW_MASS_PURGE=1")
            gone = []
        if gone:
            c.executemany("DELETE FROM pokemon WHERE uid_hex=?", gone)
            purged = len(gone)
    conn.commit()
    return {'parsed': len(parsed), 'inserted': inserted, 'shadow_inserted': shadow_inserted,
            'ghost': _departed, 'purged': purged,
            'walk_complete': walk_complete, 'skipped_eggs': skipped_eggs,
            'skipped_unparsed': skipped_unparsed, 'skipped_pid0': skipped_pid0}


def step_refresh_tags(script, conn, entries, svc_addr):
    """Pull tag bindings, map proto pointers to uids using bag walk data, write to DB."""
    c = conn.cursor()
    cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
    if 'auth_tag_names' not in cols: c.execute("ALTER TABLE pokemon ADD COLUMN auth_tag_names TEXT")

    proto_to_uid = {}
    for rec in entries:
        uid_unsigned = int(rec['uid'])
        uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
        proto_to_uid[rec['ptr']] = uid_hex

    bindings = script.exports_sync.pipeline_enum_bindings(svc_addr, proto_to_uid)

    # Build uid_hex -> [tag names]
    from collections import defaultdict
    uid_to_tags = defaultdict(list)
    for name, b in bindings.items():
        if name.startswith('__anon_'): continue
        for uid_hex in b['uids']:
            uid_to_tags[uid_hex].append(name)

    # FLOOR GUARD (audit-F19 shape, added 2026-09-02). The wipe below is TABLE-WIDE and the refill
    # only covers uids this walk saw, so a partial/failed tag enumeration silently blanks the
    # server-tag mirror for the whole bag. keep_policy never reads auth_tag_names, so this cannot
    # move the pile -- but every tag audit and reconcile treats it as server truth, so a blanked
    # column reads as "the phone has no tags" and invites a mass re-push. Refuse to wipe when the
    # enumeration collapsed relative to what is already recorded.
    prior_tagged = c.execute(
        "SELECT COUNT(*) FROM pokemon WHERE auth_tag_names IS NOT NULL AND auth_tag_names!=''"
    ).fetchone()[0]
    if prior_tagged >= 50 and len(uid_to_tags) < 0.50 * prior_tagged:
        _tick(f"   [WARN] tag enumeration returned only {len(uid_to_tags)} tagged uids vs "
              f"{prior_tagged} already recorded (<50% floor) -- KEEPING the prior auth_tag_names "
              f"instead of blanking the server-tag mirror. bindings={len(bindings)}")
        return {'tags': len(bindings), 'tagged_uids': len(uid_to_tags), 'skipped_wipe': True}

    c.execute("UPDATE pokemon SET auth_tag_names=NULL")
    for uid_hex, tags in uid_to_tags.items():
        c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                  (';'.join(tags), uid_hex))
    conn.commit()
    return {'tags': len(bindings), 'tagged_uids': len(uid_to_tags), 'skipped_wipe': False}


AE_REGISTRY_JS = r"""
function ustr(p){ try{ if(p.isNull())return ''; var n=p.add(0x10).readS32(); return p.add(0x14).readUtf16String(n);}catch(x){return '';} }
rpc.exports={ aeList:function(svc){ var s=ptr(svc); var lst=s.add(0x20).readPointer(); if(lst.isNull())return {size:0,items:[]};
  var items=lst.add(0x10).readPointer(); var size=lst.add(0x18).readS32(); var out=[];
  for(var i=0;i<size&&i<64;i++){ var ae=items.add(0x20+i*Process.pointerSize).readPointer(); if(ae.isNull())continue;
    out.push({move:ae.add(0x18).readS32(), bonus:ae.add(0x1c).readS32(), hasItem:ae.add(0x28).readU8(), item:ae.add(0x2c).readS32(),
              descKey:ustr(ae.add(0x38).readPointer())}); }
  return {size:size, items:out}; } };
"""


def step_read_player_state(sess):
    """LIVE storage cap (PlayerService.get_MaxPokemon) on the session the walk already holds -- the separate
    read_player_state.py attach is gone from the recrawl job (2026-09-12, "fold"). The live PlayerService
    instance is the LIVE graph's (pg.pick_singleton, 2026-09-29 H07) and is read with one plain invoke -- no liveness
    scan, no GC world stop. Fail-SOFT: any failure leaves the previous player_state.json in place and never fails the
    recrawl. NEVER a hardcoded fallback capacity."""
    import json as _json
    try:
        import read_player_state as _rps
        dev = pg._resolve_device()
        pid = pg._adb_pidof(dev) if dev else None
        key = 'PlayerService'
        # THE LIVE GRAPH'S PlayerService (H07 2026-09-29). This step kept its OWN cache key ('PlayerService', no namespace)
        # and on a miss took the instance with the LARGEST MaxPokemon -- both bypass pg.pick_singleton's live-graph match.
        # After the 05:00 in-process rebuild the per-pid cache held two different PlayerService addresses for pid 5429:
        # 'PlayerService' 0x6bfbcf01c0 (read here) and the live graph's 'Niantic.Holoholo.PlayerService' 0x6e478b6540.
        # The address now always comes from pick_singleton; only the klass pointer (identical in every graph) is cached.
        live = pg.pick_singleton(sess, 'Niantic.Holoholo', 'PlayerService')
        cached_klass = pg._singleton_cache_get(pid, key + '.klass') if pid else None
        cap = items = None
        sc = pg.get_script_with_helpers(sess, _rps.EXTRA_JS)
        try:
            # ONE plain invoke on the live instance. No klass cached -> maxPokemonAt resolves it BY NAME (~6 s, no GC world
            # stop) and returns it (read_player_state, H01) -- the all-instances liveness scan is gone from the walk.
            r = sc.exports_sync.max_pokemon_at(live, cached_klass) or {}
            if r.get('err') and cached_klass:
                r = sc.exports_sync.max_pokemon_at(live, None) or {}   # a stale cached klass: re-resolve it once
            if r.get('err'):
                raise RuntimeError('live graph PlayerService %s: %s' % (live, r['err']))
            v = r.get('maxPokemon')
            if not (v and 100 < v < 100000):
                raise RuntimeError('the live graph PlayerService %s gave no plausible MaxPokemon (%s)' % (live, v))
            cap = v
            vi = r.get('maxItems')
            items = vi if (vi and 50 < vi < 100000) else None
            if pid and r.get('klass') and r.get('klass') != cached_klass:
                pg._singleton_cache_put(pid, key + '.klass', r['klass'])
        finally:
            sc.unload()
        try:
            pg.rescue_frozen_world(sess, 'PlayerService read')
        except Exception:
            pass
        state = {'max_pokemon_storage': cap, 'source': 'PlayerService.get_MaxPokemon (live, in-walk)'}
        if items:
            state['max_item_storage'] = items
        with open('player_state.json', 'w') as f:
            _json.dump(state, f, indent=1)
        _tick('   live max pokemon storage = %d%s' % (cap, ('  (items %d)' % items) if items else ''))
    except Exception as e:
        _tick('   [WARN] live storage cap read failed (%s) -- previous player_state.json kept' % e)


def step_read_candy(sess):
    """LIVE inventory, every walk (user 2026-09-17: "read candy always so you can get better recommending stuff", then
    "read everything"): candy, XL candy and mega energy per family, every item by its game name, stardust and coins,
    and the player stats. Same session, cached singletons, read-only. Writes system/analysis/candy.json (the engine's
    candy budget) and system/analysis/inventory.json. Fail-SOFT: the previous files stay."""
    import json as _json, time as _time
    try:
        import read_inventory as _ri
        inv = pg.pick_singleton(sess, 'Niantic.Holoholo.Collections', 'InventoryCache')
        sc = pg.get_script_with_helpers(sess, _ri.JS + _ri.INVENTORY_EXTRA_JS)
        stats, cur = {}, {}
        try:
            sc.exports_sync.init()
            fr = sc.exports_sync.family_resources(inv, _ri.CASE_POKEMON_FAMILY, [], False)
            items = (sc.exports_sync.items(inv, _ri.CASE_ITEM) or {}).get('items') or {}
            inames = (sc.exports_sync.enum_of_field('Holoholo.Rpc', 'ItemProto', 'Item') or {}).get('map') or {}
            enames = (sc.exports_sync.enum_of_field('Holoholo.Rpc', 'TemporaryEvolutionResourceProto', 'TemporaryEvolutionId') or {}).get('map') or {}
            try:
                _f = sc.exports_sync.class_fields('Holoholo.Rpc', 'PlayerStatsProto')
                _p = sc.exports_sync.player_stats(inv, _ri.CASE_PLAYER_STATS)
                if _p.get('addr'):
                    stats = sc.exports_sync.read_ints(_p['addr'], [(f['name'], f['type'], f['off']) for f in _f
                                                                  if f['type'] in ('System.Int32', 'System.Int64', 'System.Single')])
            except Exception as _se:
                stats = {'err': str(_se)}
            iap = None
            try:
                iap = pg.pick_singleton(sess, 'Niantic.Holoholo.Storefront', 'IapService')
                cur = sc.exports_sync.currency(iap) or {}
                if not cur.get('get_Stardusts') and not cur.get('get_Coins'):
                    # 0 AND 0 is a stale instance, not a balance (2026-09-19): re-pick across every live instance
                    iap = pg.pick_singleton(sess, 'Niantic.Holoholo.Storefront', 'IapService', fresh=True)
                    cur = sc.exports_sync.currency(iap) or {}
            except Exception as _ce:
                cur = {'err': str(_ce)}
        finally:
            sc.unload()
        fams = {}
        for k, v in ((fr or {}).get('families') or {}).items():
            if isinstance(v, dict) and 'candy' in v and 0 <= v['candy'] < 10 ** 7:
                mega = {enames.get(str(t), enames.get(t, t)): e.get('w14') for t, e in (v.get('megaEnergy') or {}).items() if isinstance(e, dict)}
                fams[int(k)] = {'candy': v['candy'], 'xl': v['xlCandy'], **({'mega_energy': mega} if mega else {})}
        if len(fams) < 50:
            raise RuntimeError('only %d families read (%s)' % (len(fams), (fr or {}).get('err')))
        _root = os.path.dirname(os.path.abspath(__file__))
        _now = _time.strftime('%Y-%m-%d %H:%M:%S')
        # PROVENANCE (H03, 2026-09-29): which InventoryCache this came from, the graph it had to belong to, that graph's
        # latestTimestamp and the phone clock. candy_now()/items_now() judge these files by WHEN they were written; the
        # counts of a frozen InventoryCache read during this walk were "this walk's" and gated keep_policy's Evolve
        # promises and holds. 'verdict' stays None until step_freshness_inventory stamps the pass (STOP = unusable).
        _g = getattr(sess, '_pogo_graph', None) or {}
        _src = {'inv': inv, 'graph_inv': _g.get('inv'), 'graph_ts': _g.get('ts'), 'phone_now_ms': _g.get('now'),
                'bags': _g.get('bags'), 'verdict': None}
        _atomic_json(os.path.join(_root, 'system', 'analysis', 'candy.json'),   # R5: never a half-written file
                     {'read_at': _now, 'source': _src,
                      'families': {k: {'candy': v['candy'], 'xl': v['xl']} for k, v in fams.items()}})
        named = {inames.get(str(i), inames.get(i, 'item_%s' % i)): (c or {}).get('count') for i, c in items.items()}
        _dust, _coins = cur.get('get_Stardusts'), cur.get('get_Coins')
        _ok = isinstance(_dust, int) and isinstance(_coins, int) and (_dust or _coins)
        _ip = os.path.join(_root, 'system', 'analysis', 'inventory.json')
        try:
            _prev = _json.load(open(_ip, encoding='utf-8'))
        except Exception:
            _prev = {}
        _last = ({'stardust': _dust, 'coins': _coins, 'at': _now} if _ok else
                 _prev.get('currency_last_good') or ({'stardust': _prev['stardust'], 'coins': _prev.get('coins'),
                                                      'at': _prev.get('read_at')} if _prev.get('stardust') else None))
        # an unreadable balance is UNKNOWN (None), never a 0 that downstream code would believe (2026-09-19)
        _atomic_json(_ip, {'read_at': _now, 'source': dict(_src, iap=iap if isinstance(iap, str) else None),
                           'stardust': _dust if _ok else None, 'coins': _coins if _ok else None,
                           'currency_last_good': _last, 'items': named, 'families': fams, 'player': stats}, indent=1)
        _tick('   inventory read: %d families, %d items, stardust %s, level %s' % (len(fams), len(named), cur.get('get_Stardusts'), (stats or {}).get('Level')))
        return _now                                      # H03: step_freshness_inventory judges only a file THIS walk wrote
    except Exception as e:
        _tick('   [WARN] inventory read failed (%s) -- previous candy.json / inventory.json kept' % e)
        return None


def step_read_ae_registry(sess):
    """READ the game's own Adventure-Effect registry (AdventureEffectService.adventureEffects: List<AdventureEffect>,
    each with PokemonMove@0x18 / BonusType@0x1c / MoveDescriptionKey@0x38) into system/analysis/ae_registry_live.json.

    WHY (user, 2026-09-08: the AE roster "should be scanned every time"): the roster in keep_config was a hand list
    that had silently gone stale -- the live registry held 11 effects (Mega Mewtwo X/Y were new) against 9 known.
    The public game master has NO adventure-effect field at all, so the game process is the only source.
    Pure memory reads on the session the walk already holds -- NO extra attach, no method calls, cannot crash the
    game. Fail-SOFT: a failed read logs and leaves the previous json in place; it must never fail a recrawl.
    Offsets verified live 2026-09-08 (class dump: PokemonMove@0x18, BonusType@0x1c, HasAppliedItem@0x28,
    AppliedItem@0x2c, MoveDescriptionKey@0x38; List<T>._items@0x10/_size@0x18).
    """
    import json as _json, time as _time
    try:
        _root = os.path.dirname(os.path.abspath(__file__))       # pogo_pipeline.py lives in the project root
        out_path = os.path.join(_root, 'system', 'analysis', 'ae_registry_live.json')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.AdventureEffect', 'AdventureEffectService')
        sc = sess.create_script(AE_REGISTRY_JS); sc.load()
        try:
            r = sc.exports_sync.ae_list(str(svc))
        finally:
            sc.unload()
        names = {}
        try:
            names = {int(k): v for k, v in _json.load(open(os.path.join(_root, 'move_id_to_name.json'), encoding='utf-8')).items()}
        except Exception:
            pass
        effects = [{'move_id': it['move'], 'move': names.get(it['move'], 'MOVE_%d' % it['move']), 'bonus_id': it['bonus'],
                    'item': it['item'] if it.get('hasItem') else None, 'desc_key': it.get('descKey', '')} for it in r.get('items', [])]
        if not effects:
            print('  [ae_registry] read returned 0 effects -- keeping the previous json (not overwriting)')
            return None
        _json.dump({'schema': 1, 'generated': _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime()),
                    'source': 'AdventureEffectService.adventureEffects (live, in-walk read)', 'effects': effects},
                   open(out_path, 'w', encoding='utf-8'), indent=1)
        print('  [ae_registry] %d adventure effects read live -> %s' % (len(effects), os.path.relpath(out_path, _root)))
        return effects
    except Exception as e:                                   # fail-soft by design -- see docstring
        print('  [ae_registry] read FAILED (%s) -- previous json left in place' % e)
        return None


SHOWCASE_GM_JS = r"""
// THE GAME'S OWN SHOWCASE INPUTS (2026-09-24). Reads on GameMasterData, the class Pokemod's showcaseScoreMath
// reads: its settings dictionary -> ContestSettingsProto (coefficients + every flag), Get_PokemonExtendedSettings
// (pid, form).SizeSettings -> the six metre bounds, Get_PokemonSettings(pid, form) -> pokedexHeightM/WeightKg.
// Every method is resolved by NAME + PARAMETER TYPES (never by argc alone -- Get_PokemonSettings has a (pid, bool)
// twin), generic/inflated methods are refused, every field is read at its LIVE offset by name (no proto_layout
// offsets), and a managed exception is caught per call. No world stop anywhere.
var _SG = null;
function _sgInit() {
    if (_SG) return;
    _ensureInit();
    var il = Process.findModuleByName('libil2cpp.so');
    function nf(n, r, a) { var p = il.findExportByName(n); return p ? new NativeFunction(p, r, a) : null; }
    _SG = { MPC: nf('il2cpp_method_get_param_count', 'uint32', ['pointer']), MP: nf('il2cpp_method_get_param', 'pointer', ['pointer', 'uint32']),
            TGN: nf('il2cpp_type_get_name', 'pointer', ['pointer']), MIG: nf('il2cpp_method_is_generic', 'bool', ['pointer']),
            MII: nf('il2cpp_method_is_inflated', 'bool', ['pointer']), CGF: nf('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']),
            FGN: nf('il2cpp_field_get_name', 'pointer', ['pointer']), FGO: nf('il2cpp_field_get_offset', 'uint32', ['pointer']),
            FGT: nf('il2cpp_field_get_type', 'pointer', ['pointer']), FGF: nf('il2cpp_field_get_flags', 'int', ['pointer']),
            CGP: nf('il2cpp_class_get_parent', 'pointer', ['pointer']) };
}
function _cs(p) { try { return p.isNull() ? '' : p.readCString(); } catch (e) { return ''; } }
function _clsName(obj) { try { return _cs(IL2.cGN(IL2.objGC(obj))); } catch (e) { return ''; } }
function _ustr(p) { try { if (p.isNull()) return ''; var n = p.add(0x10).readS32(); return p.add(0x14).readUtf16String(n); } catch (x) { return ''; } }
function _findMethod(klass, name, pats) {          // pats: one RegExp per parameter type, exact count
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; var seen = [];
    while ((m = IL2.cGM(klass, it)) && !m.isNull()) {
        if (_cs(IL2.mGN(m)) !== name) continue;
        var n = _SG.MPC(m); var types = [];
        for (var i = 0; i < n; i++) types.push(_cs(_SG.TGN(_SG.MP(m, i))));
        seen.push(types.join(','));
        if (n !== pats.length) continue;
        if ((_SG.MIG && _SG.MIG(m)) || (_SG.MII && _SG.MII(m))) continue;
        var ok = true;
        for (var j = 0; j < n; j++) { if (!pats[j].test(types[j])) { ok = false; break; } }
        if (ok) return { m: m, types: types };
    }
    return { m: null, seen: seen };
}
var _FC = {};
function _fields(obj) {                              // {normalized name: {name, off, type}} for the object's runtime class
    var k = IL2.objGC(obj); var key = k.toString();
    if (_FC[key]) return _FC[key];
    var out = {}; var c = k; var depth = 0;
    while (c && !c.isNull() && depth < 6) {
        var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
        while ((f = _SG.CGF(c, it)) && !f.isNull()) {
            var fl = _SG.FGF(f); if (fl & 0x10) continue;                 // static
            var nm = _cs(_SG.FGN(f)); var nk = nm.toLowerCase().replace(/[^a-z0-9]/g, '');
            if (!(nk in out)) out[nk] = { name: nm, off: _SG.FGO(f), type: _cs(_SG.TGN(_SG.FGT(f))) };
        }
        c = _SG.CGP ? _SG.CGP(c) : ptr(0); depth++;
        if (c && !c.isNull() && _cs(IL2.cGN(c)) === 'Object') break;
    }
    _FC[key] = out; return out;
}
function _get(F, name) { return F[name.toLowerCase().replace(/[^a-z0-9]/g, '')]; }
function _rd(obj, f) {
    if (!f) return undefined;
    var p = obj.add(f.off), t = f.type;
    if (t === 'System.Double') return p.readDouble();
    if (t === 'System.Single') return p.readFloat();
    if (t === 'System.Boolean') return p.readU8() !== 0;
    if (t === 'System.Int32' || t === 'System.UInt32') return p.readS32();
    if (t === 'System.Int64' || t === 'System.UInt64') return p.readS64().toString();
    if (t === 'System.String') { var s = p.readPointer(); return s.isNull() ? null : _ustr(s); }
    return null;
}
function _rp(obj, f) { return f ? obj.add(f.off).readPointer() : ptr(0); }
function _scalars(obj) {                             // every scalar of a proto, plus repeated-field COUNTS: the shape we diff pass to pass
    var F = _fields(obj); var o = {};
    for (var k in F) {
        var f = F[k];
        if (/^System\.(Double|Single|Boolean|Int32|UInt32|Int64|UInt64|String)$/.test(f.type)) o[f.name] = _rd(obj, f);
        else if (/RepeatedField/.test(f.type)) { var rf = _rp(obj, f); o[f.name] = rf.isNull() ? null : 'repeated[' + _rd(rf, _get(_fields(rf), 'count')) + ']'; }
    }
    return o;
}
function _inv2(m, inst, a, b) {                      // two value-type (enum/int32) parameters: params[i] points at the raw value
    var pa = Memory.alloc(4); pa.writeS32(a); var pb = Memory.alloc(4); pb.writeS32(b);
    var arr = Memory.alloc(2 * Process.pointerSize); arr.writePointer(pa); arr.add(Process.pointerSize).writePointer(pb);
    return rI(m, inst, arr, null);
}
rpc.exports.findGameMaster = function (addrs) {   // borrow the GameMasterData reference a held singleton already carries: NO world stop
    _sgInit();
    for (var i = 0; i < addrs.length; i++) {
        try {
            var o = ptr(addrs[i]); var F = _fields(o); var via = _clsName(o);
            for (var k in F) {
                var f = F[k];
                if (!/(^|\.)I?GameMasterData$/.test(f.type)) continue;
                var p = _rp(o, f);
                if (!p.isNull() && _clsName(p) === 'GameMasterData') return { addr: p.toString(), via: via, field: f.name + ':' + f.type };
            }
        } catch (e) {}
    }
    return { addr: null };
};
rpc.exports.showcaseGm = function (gmAddr, pairs) {
    _sgInit();
    var gm = ptr(gmAddr); var out = { ok: true, methods: {}, contest: null, stages: {}, errors: {} };
    var k = IL2.objGC(gm); out.klass = _cs(IL2.cGN(k));
    if (out.klass !== 'GameMasterData') return { ok: false, err: 'instance is ' + out.klass };
    try {
        // CONTEST_SETTINGS (2026-09-25): GetByKey / MaybeGetByKey are GENERIC on 0.429.1, so runtime_invoke cannot call
        // them (the read failed every pass since 09-24). GameMasterData keeps ONE message per settings type in a
        // Dictionary<System.Type, IMessage> (143 entries; the AutoCatcher's tools/dump_game_limits.py reads it the same
        // way) -- plain memory reads, no managed call. Entry <ref,ref>: hashCode@0 (<0 = free), next@4, key@8, value@16.
        var GF = _fields(gm), dict = ptr(0), data = null;
        for (var g in GF) { if (/Dictionary<System\.Type,.*IMessage>/.test(GF[g].type)) { dict = _rp(gm, GF[g]); break; } }
        if (dict.isNull()) throw new Error('no Dictionary<System.Type,IMessage> on GameMasterData');
        var DF = _fields(dict), ents = _rp(dict, _get(DF, 'entries')), n = _rd(dict, _get(DF, 'count'));
        for (var d = 0; d < n && !ents.isNull(); d++) {
            var en = ents.add(0x20 + 24 * d); if (en.readS32() < 0) continue;
            var v = en.add(16).readPointer(); if (!v.isNull() && _clsName(v) === 'ContestSettingsProto') { data = v; break; }
        }
        out.methods.contest = 'settings dictionary, ' + n + ' entries';
        if (!data) out.errors.contest = 'no ContestSettingsProto among ' + n + ' settings';
        else {
            var CF = _fields(data);
            var c = { scalars: _scalars(data), coefficients: [],
                      fields: Object.keys(CF).map(function (x) { return CF[x].name + ':' + CF[x].type; }).sort() };
            var rf = _rp(data, _get(CF, 'contestScoreCoefficient'));
            if (!rf.isNull()) {
                var RF = _fields(rf); var arr = _rp(rf, _get(RF, 'array')); var cnt = _rd(rf, _get(RF, 'count'));
                for (var i = 0; i < cnt && i < 8; i++) {
                    var el = arr.add(0x20 + i * Process.pointerSize).readPointer(); if (el.isNull()) continue;
                    var EF = _fields(el); var ps = null;
                    for (var e2 in EF) { if (EF[e2].type === 'System.Object') { var q = _rp(el, EF[e2]); if (!q.isNull()) { ps = q; break; } } }
                    if (!ps) { c.coefficients.push({ cls: _clsName(el), scalars: _scalars(el) }); continue; }
                    var PF = _fields(ps);
                    c.coefficients.push({ cls: _clsName(ps), heightCoefficient: _rd(ps, _get(PF, 'heightCoefficient')),
                                          weightCoefficient: _rd(ps, _get(PF, 'weightCoefficient')), ivCoefficient: _rd(ps, _get(PF, 'ivCoefficient')),
                                          xxlAdjustmentFactor: _rd(ps, _get(PF, 'xxlAdjustmentFactor')), scalars: _scalars(ps) });
                }
            }
            var ff = _get(CF, 'contestScoreFormulas');
            if (ff) { var fr = _rp(data, ff); c.contestScoreFormulas = fr.isNull() ? 0 : _rd(fr, _get(_fields(fr), 'count')); }
            out.contest = c;
        }
    } catch (e) { out.errors.contest = 'threw: ' + e.toString(); }
    var ge = _findMethod(k, 'Get_PokemonExtendedSettings', [/HoloPokemonId$/, /(^|\.)Form$/]);
    out.methods.getExt = ge.m ? ge.types : ('none of ' + JSON.stringify(ge.seen));
    var gs = _findMethod(k, 'Get_PokemonSettings', [/HoloPokemonId$/, /(^|\.)Form$/]);
    out.methods.getSettings = gs.m ? gs.types : ('none of ' + JSON.stringify(gs.seen));
    var nErr = 0;
    for (var p = 0; p < pairs.length; p++) {
        var pid = pairs[p][0], form = pairs[p][1]; var rec = {};
        if (ge.m) {
            try {
                var ext = _inv2(ge.m, gm, pid, form);
                if (ext.isNull()) rec.ext = null;
                else {
                    var XF = _fields(ext); var ss = _rp(ext, _get(XF, 'sizeSettings'));
                    if (ss.isNull()) rec.ext = { sizeSettings: null };
                    else {
                        var SF = _fields(ss); var b = {};
                        for (var s2 in SF) { var f2 = SF[s2]; if (/^System\.(Single|Double|Boolean|Int32)$/.test(f2.type)) b[f2.name] = _rd(ss, f2); }
                        rec.ext = { sizeSettings: b, cls: _clsName(ss) };
                    }
                }
            } catch (e) { rec.extErr = e.toString(); nErr++; }
        }
        if (gs.m) {
            try {
                var st = _inv2(gs.m, gm, pid, form);
                if (st.isNull()) rec.base = null;
                else {
                    var BF = _fields(st);
                    rec.base = { pokedexHeightM: _rd(st, _get(BF, 'pokedexHeightM')), pokedexWeightKg: _rd(st, _get(BF, 'pokedexWeightKg')),
                                 heightStdDev: _rd(st, _get(BF, 'heightStdDev')), weightStdDev: _rd(st, _get(BF, 'weightStdDev')) };
                }
            } catch (e) { rec.baseErr = e.toString(); nErr++; }
        }
        out.stages[pid + ':' + form] = rec;
        if (nErr > 20) { out.errors.stages = 'stopped after 20 managed errors'; break; }
    }
    return out;
};
"""


def step_read_showcase_gm(sess, conn, held=None):
    """THE GAME'S OWN SHOWCASE INPUTS, every walk (user 2026-09-24: "5 should be done everytime"): CONTEST_SETTINGS
    (coefficients 800/150/50, xxl adjustment, every flag) and, for every (species, form) in the bag, the EXTENDED size
    bounds + pokedex height/weight -- the exact inputs Pokemod's showcaseScoreMath reads -- into
    system/analysis/showcase_gm_live.json. size_line scores by these (they beat the monthly PokeMiners dump) and
    full_audit.showcase_formula_step reports/stops on a change. Same session, cached singleton (one liveness scan
    per game process), managed reads with per-call exception capture. Fail-SOFT: the previous json stays."""
    import json as _json, time as _time
    try:
        _root = os.path.dirname(os.path.abspath(__file__))
        out_path = os.path.join(_root, 'system', 'analysis', 'showcase_gm_live.json')
        pairs = {(int(p), int(f or 0)) for p, f in conn.execute('SELECT pokemon_id, form FROM pokemon WHERE in_bag=1')}
        pairs = sorted(pairs | {(p, 0) for p, _ in pairs})
        # NO NEW WORLD STOP (2026-09-24): the singletons the walk already holds (PokedexImpl / PokemonBagImpl /
        # TaggingRpcService) carry an injected GameMasterData reference -- read that pointer (typed field, class name
        # verified) instead of paying a fifth liveness scan. The scan is only the fallback when no held object has it.
        gm = None
        try:
            _cands = [str(a) for a in (held or []) if a]
            if _cands:
                _sc0 = pg.get_script_with_helpers(sess, SHOWCASE_GM_JS)
                try:
                    _r0 = _sc0.exports_sync.find_game_master(_cands)
                finally:
                    _sc0.unload()
                gm = (_r0 or {}).get('addr')
                if gm:
                    _tick('   GameMasterData borrowed from %s (%s) -- no scan' % (_r0.get('via'), _r0.get('field')))
        except Exception as _e0:
            _tick('   (GameMasterData pointer borrow failed: %s)' % _e0)
        if not gm:
            gm = pg.pick_singleton(sess, '', 'GameMasterData')
        sc = pg.get_script_with_helpers(sess, SHOWCASE_GM_JS)
        try:
            r = sc.exports_sync.showcase_gm(str(gm), [list(x) for x in pairs])
        finally:
            sc.unload()
        try:
            pg.rescue_frozen_world(sess, 'showcase game-master read')
        except Exception:
            pass
        if not r.get('ok'):
            raise RuntimeError(r.get('err'))
        stages = r.get('stages') or {}
        n_ext = sum(1 for v in stages.values() if (v.get('ext') or {}).get('sizeSettings'))
        n_base = sum(1 for v in stages.values() if v.get('base') and v['base'].get('pokedexHeightM'))
        coef = (r.get('contest') or {}).get('coefficients') or []
        if n_ext < 0.5 * len(pairs) or not coef:
            raise RuntimeError('implausible read: size settings for %d/%d stages, %d coefficient rows; methods %s; errors %s'
                               % (n_ext, len(pairs), len(coef), _json.dumps(r.get('methods'))[:300], _json.dumps(r.get('errors'))[:300]))
        doc = {'schema': 1, 'generated': _time.strftime('%Y-%m-%d %H:%M:%S'),
               'source': 'GameMasterData.GetByKey(CONTEST_SETTINGS) + Get_PokemonExtendedSettings/Get_PokemonSettings per (species, form) in the bag (live, in-walk)',
               'methods': r.get('methods'), 'errors': r.get('errors'), 'contest': r.get('contest'), 'stages': stages,
               'pairs': len(pairs), 'with_size_settings': n_ext, 'with_base': n_base}
        _json.dump(doc, open(out_path, 'w', encoding='utf-8'), indent=1)
        c0 = coef[0]
        _tick('   showcase GM read live: coefficients %s/%s/%s xxl-adj %s; size bounds %d/%d stages, base numbers %d'
              % (c0.get('heightCoefficient'), c0.get('weightCoefficient'), c0.get('ivCoefficient'), c0.get('xxlAdjustmentFactor'), n_ext, len(pairs), n_base))
    except Exception as e:
        _tick('   [WARN] showcase GM read failed (%s) -- previous showcase_gm_live.json kept' % e)


ENUM_NAMES_JS = r"""
function cs(p){ try{return p.isNull()?'':p.readCString();}catch(x){return '';} }
rpc.exports={ enumNames:function(sub){ var il=Process.findModuleByName('libil2cpp.so'); var m={};
   il.enumerateExports().forEach(function(x){ if(x.name.indexOf('il2cpp_')===0) m[x.name]=x.address; });
   function b(n,r,a){ return new NativeFunction(m[n],r,a); }
   var DGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),DG=b('il2cpp_domain_get','pointer',[]),AGI=b('il2cpp_assembly_get_image','pointer',['pointer']),
       IGCC=b('il2cpp_image_get_class_count','uint',['pointer']),IGC=b('il2cpp_image_get_class','pointer',['pointer','uint']),CGN=b('il2cpp_class_get_name','pointer',['pointer']),
       CGF=b('il2cpp_class_get_fields','pointer',['pointer','pointer']),FGN=b('il2cpp_field_get_name','pointer',['pointer']),FSGV=b('il2cpp_field_static_get_value','void',['pointer','pointer']);
   var n=Memory.alloc(8); var asm=DGA(DG(),n); var cnt=n.readU32(); var out={};
   for(var i=0;i<cnt;i++){ var img=AGI(asm.add(i*Process.pointerSize).readPointer()); var cc=IGCC(img);
     for(var j=0;j<cc;j++){ var k=IGC(img,j); if(cs(CGN(k))!==sub) continue; var it=Memory.alloc(8); it.writePointer(ptr(0)); var f;
       while((f=CGF(k,it))&&!f.isNull()){ var nm=cs(FGN(f)); if(nm==='value__')continue; var v=Memory.alloc(8); try{ FSGV(f,v); out[v.readS32()]=nm; }catch(e){} } return out; } }
   return out; } };
"""


_ENUM_NEWS = {}          # enum -> {id: name} that appeared since the last scan (read by step_refresh_game_enums)

# (game enum class, local file, name style, minimum plausible size). Form/Costume names are the enum's own
# (UnownA, Holiday2016); move_id_to_name.json holds game-master style (THUNDER_SHOCK), so a NEW move id gets
# its C# name converted, and an existing move name is never touched.
_GAME_ENUMS = (('Form', 'form_enum.json', 'same', 1000),
               ('Costume', 'costume_enum.json', 'same', 50),
               ('HoloPokemonMove', 'move_id_to_name.json', 'upper_snake', 300))


def _upper_snake(n):
    """'V0001MoveThunderShock' -> 'THUNDER_SHOCK' (the enum's field names carry a V####Move prefix; verified 376/376
    against move_id_to_name.json on the 0.427 metadata, 2026-09-23)."""
    import re as _re
    n = _re.sub(r'^V\d+Move', '', n)
    return _re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', n).upper()


def step_refresh_game_enums(sess):
    """Re-read the Form, Costume and HoloPokemonMove enums from the live game, every walk (2026-09-23).

    WHY (user: "you need to rescan for all new things like cards, moves, backgrounds, costumes etc, you're always
    falling behind on that"): only LocationCard was refreshed in-walk; form_enum.json was 3 weeks old,
    costume_enum.json 3.5 months, and the 09-18 game update raised no signal at all.
    SAFE BY CONSTRUCTION: pure static-field reads (same JS as the card refresh); the live read must AGREE with the
    local file on >=99% of the ids both know (else it matched a different class of that name -> file untouched);
    only ids the file does not have are ADDED; nothing is ever removed or renamed. Fail-soft: never fails a walk.
    Writes system/analysis/enum_refresh.json (what is new) for full_audit to report."""
    import json as _json
    _root = os.path.dirname(os.path.abspath(__file__))
    summary = {'ts': datetime.datetime.now().isoformat(timespec='seconds'), 'enums': {}}
    try:
        sc = sess.create_script(ENUM_NAMES_JS); sc.load()
    except Exception as e:
        print('  [game_enums] script load FAILED (%s) -- files left in place' % e)
        return None
    try:
        for cls, fname, style, floor in _GAME_ENUMS:
            path = os.path.join(_root, fname)
            try:
                live = {str(k): v for k, v in (sc.exports_sync.enum_names(cls) or {}).items()}
                try:
                    old = _json.load(open(path, encoding='utf-8'))
                except Exception:
                    old = {}
                if len(live) < floor:
                    summary['enums'][cls] = {'status': 'skipped: live read returned %d names' % len(live)}
                    print('  [game_enums] %s: live read returned %d names -- keeping %s' % (cls, len(live), fname)); continue
                shared = set(live) & set(old)
                if style == 'same':
                    agree = sum(1 for k in shared if live[k] == old[k])
                else:                                           # moves: the ids must line up, names differ in style
                    agree = sum(1 for k in shared if _upper_snake(live[k]).replace('_', '') == old[k].replace('_', ''))
                if old and (len(shared) < 0.9 * len(old) or agree < 0.99 * len(shared)):
                    summary['enums'][cls] = {'status': 'rejected: agrees on %d of %d shared ids' % (agree, len(shared))}
                    print('  [game_enums] %s: live read disagrees with %s (%d/%d) -- another class of that name? file kept'
                          % (cls, fname, agree, len(shared))); continue
                new = {k: (live[k] if style == 'same' else _upper_snake(live[k]))
                       for k in sorted(set(live) - set(old), key=lambda x: int(x))
                       if not (style != 'same' and k == '0')}      # MOVE_UNSET is not a move (the file never had it)
                if new:
                    merged = dict(old); merged.update(new)
                    merged = {k: merged[k] for k in sorted(merged, key=lambda x: int(x))}
                    _json.dump(merged, open(path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
                    print('  [game_enums] %s: +%d new -> %s (%d total): %s' % (cls, len(new), fname, len(merged),
                          ', '.join(list(new.values())[:8])))
                else:
                    print('  [game_enums] %s: unchanged (%d)' % (cls, len(old)))
                summary['enums'][cls] = {'status': 'ok', 'count': len(old) + len(new), 'new': new}
            except Exception as e:
                summary['enums'][cls] = {'status': 'failed: %s' % e}
                print('  [game_enums] %s refresh FAILED (%s) -- %s left in place' % (cls, e, fname))
    finally:
        try:
            sc.unload()
        except Exception:
            pass
    if 'LocationCard' in _ENUM_NEWS:
        summary['enums']['LocationCard'] = {'status': 'ok', 'new': _ENUM_NEWS['LocationCard']}
    try:
        _json.dump(summary, open(os.path.join(_root, 'system', 'analysis', 'enum_refresh.json'), 'w', encoding='utf-8'),
                   indent=1, ensure_ascii=False)
    except Exception as e:
        print('  [game_enums] summary not written (%s)' % e)
    return summary


def step_refresh_location_card_enum(sess):
    """Refresh location_card_enum.json from the game's LocationCard enum (static fields, pure reads).

    WHY (user, 2026-09-08: "I suspected that new cards or backgrounds and such weren't being found"): the local
    dump had 280 names while the live enum had 411 -- the card IDS were read fine (the top-6-per-card cap
    grouped correctly), but 131 cards including LcSpecialbackgroundLego202601 had no NAME, so nothing could
    say what they were. Same fail-soft, same-session pattern as step_read_ae_registry: never fails a recrawl,
    never overwrites with an empty/smaller result.
    """
    import json as _json
    try:
        _root = os.path.dirname(os.path.abspath(__file__))
        out_path = os.path.join(_root, 'location_card_enum.json')
        sc = sess.create_script(ENUM_NAMES_JS); sc.load()
        try:
            names = sc.exports_sync.enum_names('LocationCard')     # python enum_names -> JS enumNames
        finally:
            sc.unload()
        names = {str(k): v for k, v in (names or {}).items()}
        old = {}
        try:
            old = _json.load(open(out_path, encoding='utf-8'))
        except Exception:
            pass
        if len(names) < max(50, len(old)):
            print('  [loc_card_enum] live read returned %d names (have %d) -- keeping the previous file' % (len(names), len(old)))
            return None
        if names != old:
            _json.dump(names, open(out_path, 'w', encoding='utf-8'), indent=1)
            print('  [loc_card_enum] LocationCard enum refreshed: %d names (+%d new)' % (len(names), len(set(names) - set(old))))
            if old:                                           # first-ever read is not "new since last scan"
                _ENUM_NEWS['LocationCard'] = {k: names[k] for k in sorted(set(names) - set(old), key=int)}
        else:
            print('  [loc_card_enum] LocationCard enum unchanged (%d names)' % len(names))
        return names
    except Exception as e:                                   # fail-soft by design
        print('  [loc_card_enum] refresh FAILED (%s) -- previous file left in place' % e)
        return None


def step_read_dex(script, dex_addr):
    """Read PokedexImpl hundo state via liveness-cached singleton.

    Saves pokedex_hundos_live.json (overwriting previous after stashing it to .prev).
    Returns (current_entries, new_hundo_pids_since_prev).
    """
    prev_path = 'pokedex_hundos_live.prev.json'
    cur_path = 'pokedex_hundos_live.json'
    if os.path.exists(cur_path):
        shutil.copyfile(cur_path, prev_path)
    prev_hundo_pids = set()
    if os.path.exists(prev_path):
        try:
            prev = json.load(open(prev_path))
            prev_hundo_pids = {e['pid'] for e in prev.get('entries', []) if e.get('hundo')}
        except Exception: pass

    r = script.exports_sync.pipeline_read_dex(dex_addr)
    # FLOOR GUARD (audit F19): a partially-loaded PokedexImpl walks to a tiny/empty list; persisting it
    # would blank dex_caught*.json -> the cull's dex_gap sees nothing caught -> mass over-protection,
    # and the hundo diff trashes. Norm is ~943 entries; refuse to persist anything implausibly small.
    if (r.get('count') or 0) < 500:
        _tick(f"   [WARN] dex walk returned only {r.get('count')} entries (<500 floor) -- dex not fully "
              f"loaded? KEEPING prior pokedex_hundos_live.json / dex_caught*.json (audit F19)")
        return r, []
    new_hundo_pids = sorted({e['pid'] for e in r['entries'] if e.get('hundo')} - prev_hundo_pids)
    with open(cur_path, 'w') as f:
        json.dump({'addr': dex_addr, 'count': r['count'], 'entries': r['entries']}, f)
    try:                                   # RELEASED species, every account (2026-09-26; keep_policy.released_pids)
        _rel = set(json.load(open('released_pids.json'))) if os.path.exists('released_pids.json') else set()
        _new = {e['pid'] for e in r['entries']} - _rel
        if _new:
            with open('released_pids.json.tmp', 'w') as f:
                json.dump(sorted(_rel | _new), f)
            os.replace('released_pids.json.tmp', 'released_pids.json')
    except Exception as _e:
        _tick(f"   [WARN] released_pids.json not updated ({_e})")
    # caught state for the cull's dex_gap_evolution rule:
    #   dex_caught.json   = list of caught pids (timesCaptured>0)  [back-compat]
    #   dex_caught_forms.json = {pid: [captured form ids]}  (form-aware gap detection)
    caught = sorted({e['pid'] for e in r['entries'] if e.get('times', 0) > 0})
    with open('dex_caught.json', 'w') as f:
        json.dump(caught, f)
    caught_forms = {str(e['pid']): e.get('forms', []) for e in r['entries'] if e.get('times', 0) > 0}
    with open('dex_caught_forms.json', 'w') as f:
        json.dump(caught_forms, f)
    return r, new_hundo_pids


def step_run_cull(conn):
    """Run cull_v9 logic in-process (no subprocess re-import)."""
    import cull_v9
    rows = [dict(r) for r in conn.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()]
    gm = json.load(open('pvpoke_gamemaster.json'))
    ctx = cull_v9.build_ctx(rows, gm)
    c = conn.cursor()
    cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
    if 'cull_decision_v9' not in cols: c.execute('ALTER TABLE pokemon ADD COLUMN cull_decision_v9 TEXT')
    if 'cull_reason_v9' not in cols: c.execute('ALTER TABLE pokemon ADD COLUMN cull_reason_v9 TEXT')

    keep = xfer = 0
    transfer_uids = []
    for p in rows:
        reasons = cull_v9.is_protected(p, ctx)
        if reasons:
            decision, reason_str = 'KEEP', ';'.join(reasons[:8]); keep += 1
        else:
            decision, reason_str = 'TRANSFER', 'no_keep_rule'; xfer += 1
            transfer_uids.append(p['uid_hex'])
        c.execute('UPDATE pokemon SET cull_decision_v9=?, cull_reason_v9=? WHERE uid_hex=?',
                  (decision, reason_str, p['uid_hex']))
    conn.commit()
    return {'keep': keep, 'transfer': xfer, 'transfer_uids': transfer_uids, 'ctx': ctx}


def step_sanity(conn, ctx):
    """Run cull_v9 sanity checks - every count must be 0."""
    import cull_v9
    c = conn.cursor()
    drift = []
    for r in cull_v9.PROTECTION_RULES:
        if not r.sanity_sql: continue
        n = c.execute(
            f"SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v9='TRANSFER' AND {r.sanity_sql}"
        ).fetchone()[0]
        if n > 0: drift.append((r.name, n))
    xfer_uids = {r[0] for r in c.execute(
        "SELECT uid_hex FROM pokemon WHERE in_bag=1 AND cull_decision_v9='TRANSFER'")}
    n_xxl = len(ctx['xxl_top3_uids'] & xfer_uids)
    if n_xxl > 0: drift.append(('xxl_top3', n_xxl))
    return drift


# ---------------------------------------------------------------------------
# REMOVED 2026-09-07: step_tag_transfers_impl() + the --tag-transfers flag.
#
# This was a SECOND, UNGATED path from this process to the irreversible output. It loaded
# bulk_tag.js in the live Frida session and called bulk_tag_many() to stamp CLAUDE_TX onto
# whatever `cull_decision_v9='TRANSFER'` happened to hold -- with NO preflight_transfer.py in
# front of it, and it ran BEFORE the pre-flight block at the bottom of main(), so a FAIL verdict
# printed after the tags were already on the phone. That is the exact defect class that cost 18
# pokemon: a route to the pile that does not pass the gate.
#
# It was also pushing the WRONG SET. cull_v9 is a retired generation kept only as the advisory
# `cull_decision_v9` column that keep_policy.py diffs against; the pile is keep_policy.py ->
# 6_Transfer.txt. On 2026-09-07 cull_v9 said TRANSFER for 13 mons while the sanctioned pile held
# 26 -- two different universes, and CLAUDE_TX is not even in the tag registry (doctor.py
# subtracts it by name; 0 rows in the bag carry it).
#
# Proof it was dead before removal: nothing in the tree passes --tag-transfers.
#   dashboard.py:181 (_recrawl_steps)      -> _py(pogo_pipeline.py), no extra argv
#   self_update.py:312                     -> ['pogo_pipeline.py'] (+ --dry-run only)
#   system/scripts/refresh.py:174          -> [sys.executable, 'pogo_pipeline.py']
#   autocull_watch.py:72 / start_autocull.vbs -> full_audit.py, never this file
#   Windows Task Scheduler                 -> no task references python/pogo at all
#   system/procedures/refresh.md:67 and system/SCRIPTS_INDEX.md:101 already documented the flag
#   as "Legacy, do not use ... not the pile and is not gated".
#
# THE SANCTIONED PATH IS THE ONLY PATH:
#   keep_policy.py -> build_tagsets.py -> preflight_transfer.py -> set_db_tags_from_files.py
#   -> prune_tags.py --atomic          (or just: python full_audit.py)
# preflight_transfer.py is what proves the pile is keeper-free on EVERY axis. Do not re-add a
# tag-ADD primitive to this file. This process may READ the phone; it may not write to it.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# WALK TRIPWIRES (H03, 2026-09-29) -- a frozen or impossible read must never pass silently again.
# 05:06 / 05:09 / 05:11 walked a service graph the game had abandoned at 04:59:53: the same 5,661 uids three times,
# newest mon 04:58:03, "caught 0 released 0", 41 "tagged", "All tags in sync", "VERIFY OK". Every existing guard
# measures SIZE or re-reads the SAME objects, so all of them agreed. These two steps compare sources that cannot be
# frozen together: the graph's InventoryCache.latestTimestamp against the phone's own clock, against the previous
# pass, against the bag's newest mon and against the catcher's own counter; then the lifetime counters (XP, catches,
# km, evolutions, hatches, dex TimesCaptured) against the previous pass. Rules + thresholds: walk_tripwires.py.
# ---------------------------------------------------------------------------
def step_freshness_graph(sess, pid, trainer, s, entries, walk_meta):
    """(fingerprint, previous fingerprint of this trainer, findings). Read-only: two field reads per service through
    pogo_il2cpp._GRAPH_JS, plus `adb shell dumpsys` / `cat` of the catcher's state file (no Frida)."""
    import walk_tripwires as wt
    prev = wt.last(trainer)
    g = dict(getattr(sess, '_pogo_graph', None) or {})
    # R1 (Gym Battle review, 2026-09-29): the graph's timestamp and the phone clock were captured when the graph was
    # PICKED, before the walk. A catch between that pick and the walk's read (after a quiet spell) put a mon in the bag
    # newer than ts + 2 min -> a false BAG_AHEAD_OF_INV STOP on a live pass. One plain graphOf(bag) read AFTER the walk
    # (field reads, no scan) is what the rules judge; ts_pick keeps the old value, and ts > ts_pick proves it moved.
    try:
        _after = pg._graph_of(sess, [s['bag']]).get(s['bag']) or {}
        if _after.get('ts') and _after.get('now'):
            g.update(ts_pick=g.get('ts'), ts=_after['ts'], now=_after['now'])
    except Exception as _ae:
        _tick(f"   (graph re-read after the walk failed: {_ae} -- judging the values from the pick)")
    playing, catcher = wt.phone_probe()                   # one read-only `adb shell` round trip
    fp = wt.new(pid, trainer, g, g.get('now'), wt.walk_part(entries, walk_meta, prev),
                services=pg.graph_membership(sess, {'bag': s.get('bag'), 'svc': s.get('svc'), 'dex': s.get('dex')}),
                playing=playing, catcher=catcher)
    fp['graph']['ts_pick'] = g.get('ts_pick')
    found = wt.check_graph(fp, prev)
    for lv, code, msg in found:
        _tick(f"   {'[WARN] ' if lv != 'INFO' else ''}{code}: {msg}")
    fp['verdict'] = wt.verdict(found)
    fp['findings'] = [list(f) for f in found]
    if fp['verdict'] == 'STOP':
        wt.append(fp)
    else:
        _tick(f"   walk freshness {fp['verdict']}: inventory updated "
              f"{((fp['phone_now_ms'] or 0) - (fp['graph']['ts'] or 0)) / 1000.0:.0f} s before the walk")
    return fp, prev, found


def step_freshness_inventory(sess, pid, fp, prev, found, inv_read_at, dex_r, tag_stats, conn):
    """Adds the inventory / dex / tag parts, runs the counter rules, proves the graph of every service the later read
    steps used (the InventoryCache and IapService read_candy recorded, the AdventureEffectService and PlayerService picks
    read_ae_registry / read_player_state left in the per-pid singleton cache), appends the fingerprint and stamps the verdict into
    candy.json / inventory.json (so candy_now()/items_now() never hand a STOP pass's counts to the engine)."""
    import walk_tripwires as wt
    A = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'system', 'analysis')
    def _load(p):
        try:
            return json.load(open(p, encoding='utf-8'))
        except Exception:
            return None
    fp['inv'] = wt.inventory_part(_load(os.path.join(A, 'inventory.json')), read_at_expected=inv_read_at) if inv_read_at else None
    fp['dex'] = wt.dex_part(_load('pokedex_hundos_live.json')) if (dex_r or {}).get('count', 0) >= 500 else None
    fp['tags'] = tag_stats
    fp['walk_iso'] = conn.execute("SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1").fetchone()[0]
    _src = ((_load(os.path.join(A, 'inventory.json')) or {}).get('source') or {}) if inv_read_at else {}
    extra = {'inv': _src.get('inv'), 'iap': _src.get('iap'),
             'ae': pg._singleton_cache_get(pid, 'Niantic.Holoholo.AdventureEffect.AdventureEffectService'),
             'player_state': pg._singleton_cache_get(pid, 'Niantic.Holoholo.PlayerService')}   # read_player_state's pick
    extra = {k: v for k, v in extra.items() if v}
    fp['services'].update(pg.graph_membership(sess, extra))
    more = wt.check_inventory(fp, prev) + wt.check_services(fp, names=set(extra))
    for lv, code, msg in more:
        _tick(f"   [WARN] {code}: {msg}")
    allf = list(found) + list(more)
    fp['verdict'] = wt.verdict(allf)
    fp['findings'] = [list(f) for f in allf]
    wt.append(fp)
    for name in ('candy.json', 'inventory.json'):
        d = _load(os.path.join(A, name))
        if d and inv_read_at and d.get('read_at') == inv_read_at:
            d.setdefault('source', {})['verdict'] = fp['verdict']
            _atomic_json(os.path.join(A, name), d, indent=1 if name == 'inventory.json' else None)   # R5
    return fp


def _freshness_stop(found, script, sess):
    """Print the tripwires that fired, detach, exit 8. Nothing downstream runs: no reconcile (graph STOP) or no
    ranks / cull / keep_policy / tagsets / pre-flight (inventory STOP) -- the pile on disk stays the last live pass's."""
    print('\n' + '=' * 60)
    print('FROZEN OR IMPOSSIBLE READ -- this pass judged NOTHING and changes nothing on the phone:')
    for f in found:
        if f[0] == 'STOP':
            print('  *** %s: %s' % (f[1], f[2]))
    print('The walk read a service graph that cannot be proven live. Re-run once the game has been on screen for a')
    print('minute; if it repeats, PoGo is holding an abandoned graph -- close PoGo and relaunch it through Pokemod.')
    print('=' * 60)
    try:
        script.unload()
        sess.detach()
    except Exception:
        pass
    raise SystemExit(8)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true',
                    help='skip the server-tag MIRROR read (refresh_tag_bindings); this process '
                         'never writes to the phone under any flag')
    # Retired 2026-09-07. Kept ONLY as a fail-closed tombstone so a forgotten caller (or a copied
    # command line) dies with an explanation instead of argparse's bare "unrecognized arguments",
    # which reads like a typo and invites someone to re-add the flag. The full removal rationale
    # is in the "REMOVED 2026-09-07" block just above this function.
    ap.add_argument('--tag-transfers', action='store_true', help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.tag_transfers:
        ap.error(
            '--tag-transfers is REMOVED. It pushed the retired cull_v9 TRANSFER set to the phone '
            'as CLAUDE_TX with NO pre-flight in front of it, and CLAUDE_TX is not the pile. '
            'The only sanctioned path to the irreversible pile is: keep_policy.py -> '
            'build_tagsets.py -> preflight_transfer.py -> set_db_tags_from_files.py -> '
            'prune_tags.py --atomic  (or simply: python full_audit.py). '
            'Re-run this file with no flags for the read-only re-crawl.')

    _tick("start")
    with _step('attach'):
        # WAIT, DO NOT FAIL (user 2026-09-20: "fuck waiting for the guard"). get_session() refuses to attach in
        # PoGo's first 45s because attaching mid init-storm is what froze the game before -- a real protection,
        # but it was surfacing as "RECRAWL FAILED rc=1" and a manual retry. wait_ready_to_attach() sits through
        # the storm and then attaches, so a relaunched game costs a few silent seconds instead of a failed run.
        pg.wait_ready_to_attach(timeout_s=300)
        sess, pid = pg.get_session()
        _tick(f"   PoGo pid={pid}")

    with _step('account_guard'):                           # 2026-09-26: one data set per trainer -- stop BEFORE any DB write
        import account_guard
        # The trainer name when it was read AND matched the live data set; None when it could not be read (the guard only
        # warns then). step_reconcile_db's DELETE needs a positive match (H07 2026-09-29).
        _acct_name = account_guard.check(sess, _tick)
        _acct_verified = bool((_acct_name or '').strip()) and bool(account_guard.active())

    with _step('singletons'):
        s = step_singletons(sess)

    with _step('pipeline_script_load'):
        script = pg.get_script_with_helpers(sess, PIPELINE_JS)

    with _step('walk_bag'):
        entries, walk_meta = step_walk_bag(script, s['bag'])
        walk_meta['account_verified'] = _acct_verified
        _tick(f"   walked {len(entries)} entries"
              + (f" (declared {walk_meta.get('declared')})" if walk_meta.get('declared') is not None else ""))

    with _step('game_counts'):
        # THE NUMBER THE GAME SHOWS (user 2026-09-24: "The bag is 5743/5850. Check for yourself..."): read live, the
        # storage screen's count is PokemonBagImpl.get_Count = Pokemon + eggs IN INCUBATORS (5734 + 7 = 5741 while
        # the screen said 5741; the 4 un-incubated eggs do not count). Read-only int getters, same session.
        try:
            _gc = pg.get_script_with_helpers(sess, BAG_COUNTS_JS)
            walk_meta['game'] = _gc.exports_sync.counters(s['bag'])
            _gc.unload()
            _g = walk_meta['game']
            _tick(f"   game storage count {_g.get('get_Count')} = {_g.get('get_PokemonOnlyCount')} Pokemon + "
                  f"{_g.get('get_IncubatedEggCount')} eggs in incubators ({_g.get('get_EggCount')} eggs in all)")
        except Exception as _e:
            _tick(f"   (game storage counters unread: {_e})")

    with _step('freshness_graph'):                         # H03 (2026-09-29): BEFORE any DB write -- see step_freshness_graph
        _fp, _fp_prev, _fresh = step_freshness_graph(sess, pid, _acct_name, s, entries, walk_meta)
        if _fp.get('verdict') == 'STOP':
            _freshness_stop(_fresh, script, sess)

    conn = sqlite3.connect('pokemon.db')
    conn.row_factory = sqlite3.Row
    species_lookup = {r[0]: r[1] for r in conn.execute(
        "SELECT DISTINCT pokemon_id, species_name FROM pokemon "
        "WHERE species_name IS NOT NULL AND species_name NOT GLOB 'pid[0-9]*'"
    ).fetchall()}
    # Seed names for species we have no named copy of (evolutions / firsts)
    for _pid, _nm in SUPPLEMENTAL_NAMES.items():
        species_lookup.setdefault(_pid, _nm)
    # Robust fallback: fill ANY remaining missing pid from the PvPoke gamemaster
    # national dex, so a never-before-seen first-catch (Mudbray/Mudsdale/Whirlipede)
    # resolves instead of staying 'pidN' -- which also blocks its PvP ranks
    # (compute_all_ranks keys off the resolved name). DB-resolved names win.
    try:
        for _p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']:
            if _p.get('dex') and _p.get('speciesName') and '_shadow' not in _p.get('speciesId', ''):
                species_lookup.setdefault(_p['dex'], _p['speciesName'])   # _shadow guard: a reorder would seed 'X (Shadow)' names (audit F27)
    except Exception as _e:
        print(f'   (gamemaster name fallback unavailable: {_e})')

    with _step('reconcile_db'):
        recon = step_reconcile_db(conn, entries, species_lookup, walk_meta,
                                  allow_purge=(_fp.get('verdict') == 'OK'))   # H03: never DELETE rows on a doubtful walk
        _tick(f"   parsed={recon['parsed']} inserted={recon['inserted']} "
              f"(shadow={recon['shadow_inserted']}) departed={recon['ghost']} "
              f"purged={recon['purged']}"
              + ("" if recon['walk_complete'] else "  [purge SKIPPED -- the WARN above says why]"))
        # THE GAME'S OWN STORAGE COUNT (user 2026-09-24: "Game shows 5743/5850" when the cull said 5733): the game
        # counts EGGS against Pokemon storage; they are the pid0 entries this walk skips. Written every walk so
        # every "bag / free" line can show the number the game shows.
        try:
            _g = (walk_meta or {}).get('game') or {}
            json.dump({'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'declared': (walk_meta or {}).get('declared'),
                       'mons': recon['parsed'], 'game_count': _g.get('get_Count'),
                       'pokemon_only': _g.get('get_PokemonOnlyCount'), 'eggs': _g.get('get_EggCount'),
                       'eggs_incubated': _g.get('get_IncubatedEggCount'),
                       # H07 2026-09-29: what this walk itself saw, so a reader can compare it with the game's numbers
                       'eggs_walked': recon['skipped_eggs'], 'unread': recon['skipped_unparsed'],
                       'walk_complete': recon['walk_complete'], 'account_verified': walk_meta.get('account_verified'),
                       'graphs': (getattr(sess, '_pogo_graph', None) or {}).get('bags'),
                       'inventory_ts': (getattr(sess, '_pogo_graph', None) or {}).get('ts')},
                      open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'system', 'analysis', 'bag_count.json'), 'w'))
        except Exception as _e:
            _tick(f"   (bag_count.json not written: {_e})")

    # 2026-06-03: DATA-LAYER form-drift normalization. PoGo re-encodes the SAME real
    # "normal" form under different numeric codes across eras (Umbreon 2848->1235,
    # Caterpie 953/3346, Ditto 0/1089/3337/3338, ...). Collapse those to one canonical so
    # the per-(pid,cf) cap doesn't over-split into phantom collectibles. FORMLESS species
    # ONLY (pvpoke gm_base==1, not a cosmetic-collectible, no FORM_OVERRIDES code);
    # collectibles (Unown/Spinda/Basculin) + regionals stay distinct. `fresh_form` keeps raw.
    with _step('normalize_forms'):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'system', 'scripts'))
        import normalize_forms as _nf
        # ALWAYS apply. --dry-run means "no SERVER/tag writes" (the flag's own docstring), and the
        # pipeline already writes the whole reconcile to the DB under it. Skipping ONLY the form
        # normalization made --dry-run run the cull over UN-normalized forms and then rewrite
        # 6_Transfer.txt from that different universe -- so a dry run silently replaced the real
        # pile with one computed under different rules. (0 would-change rows today; this closes
        # the divergence rather than waiting for it to bite.) (lockdown 2026-09-02)
        _nchg = _nf.apply_to_db(conn, apply=True, verbose=False)
        _tick(f"   normalized {len(_nchg)} drifted form ids")

    if not args.dry_run:
        with _step('refresh_tag_bindings'):
            tag_stats = step_refresh_tags(script, conn, entries, s['svc'])
            _tick(f"   bindings={tag_stats['tags']} tagged_uids={tag_stats['tagged_uids']}")
    else:
        _tick(">> refresh_tag_bindings SKIPPED (--dry-run)")
        tag_stats = None

    with _step('read_dex'):
        dex_r, new_hundo_pids = step_read_dex(script, s['dex'])
    with _step('read_ae_registry'):                       # 2026-09-08: live AE roster, same session, fail-soft
        step_read_ae_registry(sess)
    with _step('read_showcase_gm'):                       # 2026-09-24: the game's OWN showcase coefficients + size bounds, same session, fail-soft
        step_read_showcase_gm(sess, conn, [s.get('dex'), s.get('bag'), s.get('svc')])
    with _step('refresh_location_card_enum'):             # 2026-09-08: card/background NAMES, same session, fail-soft
        step_refresh_location_card_enum(sess)
    with _step('refresh_game_enums'):                     # 2026-09-23: forms / costumes / moves too, same session, fail-soft
        step_refresh_game_enums(sess)
    with _step('read_player_state'):                       # 2026-09-12: live storage cap, same session, cached, fail-soft
        step_read_player_state(sess)
    with _step('read_candy'):                              # 2026-09-17: candy per family, same session, cached, fail-soft
        _inv_read_at = step_read_candy(sess)
        _tick(f"   walked {dex_r['count']} dex entries; new hundos since last run: {len(new_hundo_pids)}")

    with _step('freshness_inventory'):                     # H03: lifetime counters vs the last pass, BEFORE the pile is rebuilt
        _fp = step_freshness_inventory(sess, pid, _fp, _fp_prev, _fresh, _inv_read_at, dex_r, tag_stats, conn)
        if _fp.get('verdict') == 'STOP':
            conn.commit()
            conn.close()
            _freshness_stop(_fp.get('findings') or [], script, sess)

    # Data-completeness gate: cull rules read gl/ul ranks+stages and legacy_accurate.json.
    # Recompute both for fresh captures BEFORE cull, or new mons fall into the NULL-trap.
    with _step('compute_ranks_legacy'):
        conn.commit()  # flush reconcile/refresh writes; release for subprocesses (WAL)
        import subprocess as _sub
        here_dir = os.path.dirname(os.path.abspath(__file__))
        # rank_cache.py = verified byte-identical to compute_all_ranks.py (0 mismatches,
        # 2026-05-29) but ~44x faster: caches the per-species 4096-combo IV tables
        # (rebuilt only when pvpoke_gamemaster.json changes) while still re-ranking
        # EVERY in-bag mon every run (no per-mon skip). Fallback: compute_all_ranks.py.
        r1 = _sub.run([sys.executable, os.path.join('system', 'scripts', 'rank_cache.py')], cwd=here_dir, capture_output=True, text=True)
        r2 = _sub.run([sys.executable, 'detect_legacy.py'], cwd=here_dir, capture_output=True, text=True)
        _tick(f"   ranks rc={r1.returncode}  legacy rc={r2.returncode}")
        if r1.returncode or r2.returncode:
            # FATAL, not a warning. This used to _tick and fall straight through into cull_v9 +
            # keep_policy + build_tagsets, which REWRITE the irreversible 6_Transfer.txt from
            # STALE ranks / a stale legacy_accurate.json. A mon whose legacy detection failed has
            # no legacy keep axis and lands in the pile; the operator then reads the pipeline's
            # own "TRANSFER PRE-FLIGHT: PASS" and releases by hand. Never build a pile on data we
            # know is stale. (lockdown 2026-09-02)
            _tick(f"   ! rank/legacy compute FAILED - refusing to rebuild the Transfer pile on "
                  f"stale data. ranks_err={r1.stderr[-400:]} legacy_err={r2.stderr[-400:]}")
            print('\n' + '=' * 60)
            print("PIPELINE ABORTED: rank/legacy recompute failed (ranks rc=%d, legacy rc=%d)."
                  % (r1.returncode, r2.returncode))
            print("The DB reconcile above is committed and safe. The cull / keep_policy / tagsets"
                  " were NOT re-run, so the tagset files on disk are from the PREVIOUS run.")
            print("DO NOT SYNC OR RELEASE until this is fixed and the pipeline re-run.")
            conn.commit()
            script.unload()
            sess.detach()
            conn.close()
            raise SystemExit(2)

    with _step('cull_v9'):
        cull_r = step_run_cull(conn)
        _tick(f"   KEEP={cull_r['keep']} TRANSFER={cull_r['transfer']}")

    with _step('sanity'):
        drift = step_sanity(conn, cull_r['ctx'])
        if drift:
            for name, n in drift: _tick(f"   ! {name}: {n}")
        else:
            _tick("   all rules clean (0 drift)")

    # 2026-05-30: fold the tag-truth recompute INTO the crawl so the tagset files
    # can never go stale behind a forgotten manual step (step 6). keep_policy.py is
    # the authoritative keep engine (-> 6_Transfer.txt + policy_reasons.json);
    # build_tagsets.py derives all 11 tag membership files. Both are DB-only
    # subprocesses (no Frida) and only refresh FILES -- the server push stays the
    # deliberate `prune_tags.py` step (needs foreground). Non-fatal on error.
    with _step('keep_tagsets'):
        conn.commit()  # flush cull writes; keep_policy reads cull_decision_v9
        kp = _sub.run([sys.executable, os.path.join('system', 'scripts', 'keep_policy.py')],
                      cwd=here_dir, capture_output=True, text=True)
        bt2 = _sub.run([sys.executable, os.path.join('system', 'scripts', 'build_tagsets.py')],
                       cwd=here_dir, capture_output=True, text=True)
        _kpl = next((l for l in kp.stdout.splitlines() if l.startswith('in_bag=')), '(keep_policy: no summary)')
        _tick(f"   {_kpl}  build_tagsets rc={bt2.returncode}")
        _tagsets_stale = bool(kp.returncode or bt2.returncode)
        if _tagsets_stale:
            # Was warn-only, and the pre-flight below then ran over the PREVIOUS run's pile and
            # printed PASS -- blessing a stale Transfer.txt that the operator releases by hand.
            # Skip the pre-flight entirely and exit non-zero so no caller can read this as a
            # green light. (lockdown 2026-09-02)
            _tick(f"   ! tagset recompute FAILED kp={kp.stderr[-400:]} bt={bt2.stderr[-400:]}")

    # Done with the pipeline JS. Nothing else in this process touches the phone: the tag-push
    # block that used to sit here (--tag-transfers -> bulk_tag_many -> CLAUDE_TX) was removed
    # 2026-09-07 as an ungated route to the irreversible pile. Detach immediately so the
    # pre-flight below can open its own clean session.
    script.unload()
    sess.detach()

    # ---- final report ----
    wall = time.time() - _T0
    print('\n' + '=' * 60)
    print(f"PIPELINE COMPLETE in {wall:.2f}s")
    print('=' * 60)
    print(f"\nBag:        {recon['parsed']} pokemon + {recon['skipped_eggs']} eggs ({len(entries)} walk records)")
    print(f"Cull:       KEEP={cull_r['keep']}  TRANSFER={cull_r['transfer']}")
    print(f"New dex hundos since last run: {len(new_hundo_pids)}"
          + (f"  pids={new_hundo_pids[:20]}{'...' if len(new_hundo_pids) > 20 else ''}"
             if new_hundo_pids else ""))
    if drift:
        print(f"DRIFT WARNINGS ({len(drift)}):")
        for name, n in drift: print(f"   ! {name}: {n}")
    else:
        print("Drift: none (all sanity rules pass)")

    print(f"\nPer-step timing:")
    for name, d in _STEP_TIMES.items():
        print(f"  {name:25s} {d:6.2f}s")

    # 2026-06-06: comprehensive Transfer-pile PRE-FLIGHT (independent guard; reads deployment LIVE off
    # the proto). Since 2026-09-24 (no gym excuse) the gate makes NO phone contact at all.
    # Non-fatal to the pipeline (tagsets are already built) -- it surfaces any keeper that leaked into
    # the irreversible pile so the operator never syncs/releases a bad pile. Gate the sync on its verdict.
    print('\n' + '=' * 60)
    if _tagsets_stale:
        print("TRANSFER PRE-FLIGHT: SKIPPED -- keep_policy/build_tagsets FAILED this run, so the")
        print("tagset files on disk are from the PREVIOUS run. Pre-flighting them would bless a")
        print("STALE pile. *** TAGSETS STALE -- DO NOT SYNC OR RELEASE. ***")
        conn.close()
        raise SystemExit(3)
    # 2026-09-07: the verdict now drives the EXIT CODE. This block already printed
    # "DO NOT SYNC/RELEASE" on a FAIL and then returned 0, so `pogo_pipeline.py; echo $?` -- and
    # every subprocess caller that checks rc (system/scripts/refresh.py:174 raises only on rc!=0,
    # dashboard.py's job runner marks a step failed only on rc!=0, self_update.py sets
    # pipeline_ok = (rc == 0)) -- read a pile with a proven keeper in it as a clean run. This run
    # REBUILT 6_Transfer.txt a few lines above, so a FAIL here means the freshly written pile is
    # bad. Same fail-closed shape as the two aborts above (rc 2 = stale ranks/legacy, rc 3 = stale
    # tagsets). rc 4 = pile rebuilt but the keeper gate REJECTED it.
    _pf_failed = False
    try:
        pf = _sub.run([sys.executable, os.path.join('system', 'scripts', 'preflight_transfer.py')],
                      cwd=here_dir, capture_output=True, text=True, timeout=180)
        print(pf.stdout.rstrip())
        if pf.stderr.strip():
            print(pf.stderr.rstrip())
        _pf_failed = (pf.returncode != 0)
        print('TRANSFER PRE-FLIGHT: ' + ('PASS' if pf.returncode == 0
                                         else 'FAIL (rc=%d) -- DO NOT SYNC/RELEASE' % pf.returncode))
    except Exception as _pfe:
        # NOT promoted to a non-zero exit (deliberately, 2026-09-07): preflight_transfer.py opens
        # its OWN Frida session, so a transient collision/timeout here would turn every dashboard
        # re-crawl red and train the operator to ignore red. But understand what this branch means:
        # the pile was rebuilt this run and is UNPROVEN. Treat it as FAIL until run by hand.
        print('TRANSFER PRE-FLIGHT: COULD NOT RUN (%s) -- the pile was REBUILT this run and is'
              ' UNPROVEN. Run system/scripts/preflight_transfer.py by hand and require PASS'
              ' before any sync or release.' % _pfe)

    # 2026-06-07: per-tag consistency audit (keep_policy reason <-> build_tagsets file + partition).
    # DB/file only (no Frida); runs EVERY recrawl so a keep_policy<->build_tagsets drift is caught
    # automatically, not only when asked. Non-fatal to the pipeline.
    try:
        au = _sub.run([sys.executable, os.path.join('system', 'scripts', 'audit_tags.py')],
                      cwd=here_dir, capture_output=True, text=True, timeout=60)
        print(au.stdout.rstrip())
        if au.returncode != 0:
            if au.stderr.strip():
                print(au.stderr.rstrip())
            print('!! TAG AUDIT FAILED (rc=%d) -- keep_policy<->build_tagsets drift; investigate before release.'
                  % au.returncode)
    except Exception as _aue:
        print('TAG AUDIT: SKIPPED (%s) -- run system/scripts/audit_tags.py manually' % _aue)

    conn.close()
    if _pf_failed:
        # Exit AFTER the tag audit so the operator still gets the whole report, but never with a
        # zero status: a rejected pile is not a successful run.
        print()
        print('*** PIPELINE EXIT 4: the Transfer pile rebuilt this run FAILED the keeper gate.'
              ' DO NOT SYNC OR RELEASE. ***')
        raise SystemExit(4)


if __name__ == '__main__':
    main()
