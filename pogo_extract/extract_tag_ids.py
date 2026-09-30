"""Extract pokemonTagIds_ (RepeatedField<UInt64> @ +0x180 of PokemonProto) for every
pokemon in pokemon.db, write a tag_ids column (semicolon-separated tag IDs).

Strategy:
  1. Connect to the ZygiskFrida-injected gadget on 127.0.0.1:27047 (port forwarded via adb).
  2. Load bulk_tag.js, call init + indexPokemon to build the heap proto index.
  3. Hook ALL TaggingRpcService methods so we capture a real instance when the user
     opens the tag manager (per the working recipe: capturing real instances yields
     fully-loaded RepeatedField structures since the tag manager forces materialization).
  4. Probe the RepeatedField layout against the known-tagged Cinderace
     (uid_hex c9094ad9544fd198, tagged "U" = tag id 6). Find which (countOff, itemsOff,
     dataOff) triple yields [6].
  5. Run extractAllTagIds with the discovered offsets.
  6. Update pokemon.db: add tag_ids column (TEXT), populate per-uid.
"""
import argparse, frida, json, os, sqlite3, sys, time

WD = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(WD, "pokemon.db")
JS = os.path.join(WD, "bulk_tag.js")
GADGET = "127.0.0.1:27047"

# Known-tagged Cinderace from prior runs - tagged "U" (tag id 6)
KNOWN_UID_HEX = "c9094ad9544fd198"
KNOWN_TAG_ID = "6"

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def uid_hex_to_low_high(uid_hex):
    """uid_hex is the literal byte ordering as seen on heap (low32 then high32, little-endian within each).
    PokemonProto +32 is int32 low, +36 is int32 high. The hex string in pokemon.db
    is the uid as 8 bytes big-endian text, but the heap layout reads them as 2 signed int32s.
    See run_bulk_tag.py: low = uid & 0xFFFFFFFF, high = (uid >> 32) & 0xFFFFFFFF, then sign-correct."""
    # uid_hex is e.g. "c9094ad9544fd198" — that's the uid as a 64-bit unsigned in hex (big-endian textual).
    # But pokemon.db stores uid as signed int64 too; let's use uid_hex as a literal hex value.
    u = int(uid_hex, 16)
    low = u & 0xFFFFFFFF
    high = (u >> 32) & 0xFFFFFFFF
    if low > 0x7FFFFFFF: low -= 0x100000000
    if high > 0x7FFFFFFF: high -= 0x100000000
    return low, high

def uid_signed_to_low_high(uid):
    """uid is signed int64 as stored in DB."""
    u = uid & 0xFFFFFFFFFFFFFFFF
    low = u & 0xFFFFFFFF
    high = (u >> 32) & 0xFFFFFFFF
    if low > 0x7FFFFFFF: low -= 0x100000000
    if high > 0x7FFFFFFF: high -= 0x100000000
    return low, high

def attach_gadget():
    mgr = frida.get_device_manager()
    d = mgr.add_remote_device(GADGET)
    # The gadget has one process: the host app (PoGo). Pick the first/only one.
    procs = d.enumerate_processes()
    if not procs:
        raise RuntimeError("no processes on gadget")
    p = procs[0]
    log(f"gadget device: pid={p.pid} name={p.name}")
    return d.attach(p.pid)

def make_handler(captured_status):
    def on_msg(msg, data):
        if msg.get("type") == "send":
            p = msg["payload"]
            t = p.get("type", "?")
            if t == "methods":
                captured_status["methods"] = p.get("data", [])
            else:
                m = p.get("msg", json.dumps(p))
                log(f"  [JS {t}] {str(m)[:300]}")
        elif msg.get("type") == "error":
            log(f"  [FRIDA-ERR] {msg.get('description')}")
    return on_msg

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["probe", "extract", "all"], default="all", nargs="?",
                    help="probe = just dump RepeatedField for the known Cinderace; "
                         "extract = run full extraction (assumes offsets are already known); "
                         "all = probe then extract.")
    ap.add_argument("--hook-seconds", type=int, default=60,
                    help="seconds to leave hooks running while user opens tag manager")
    ap.add_argument("--count-off", type=lambda x:int(x,0), default=None)
    ap.add_argument("--items-off", type=lambda x:int(x,0), default=None)
    ap.add_argument("--data-off",  type=lambda x:int(x,0), default=None)
    ap.add_argument("--no-hook", action="store_true",
                    help="skip the hookForRealInstance step (use if proto index already populated)")
    args = ap.parse_args()

    sess = attach_gadget()
    src = open(JS, "r", encoding="utf-8").read()
    script = sess.create_script(src)
    captured = {"methods": []}
    script.on("message", make_handler(captured))
    script.load()
    log("script loaded")

    log("init...")
    st = script.exports_sync.init_status()
    log(f"  init: {st}")
    if not st.get("ready"):
        log(f"init failed: {st.get('err')}"); sys.exit(2)

    log("indexing pokemon protos in heap...")
    res = script.exports_sync.index_pokemon()
    log(f"  index: {res}")
    if not res.get("ok"):
        log("index failed"); sys.exit(2)

    # Enumerate PokemonTagProto instances to build snowflake-id -> name map.
    log("enumerating PokemonTagProto instances on heap...")
    tp = script.exports_sync.enumerate_tag_protos()
    snowflake_to_name = {}
    if tp.get("ok"):
        log(f"  found {tp.get('count')} unique tag protos (scanned {tp.get('scanned')})")
        for r in tp.get("results", []):
            name = r.get("name")
            if not name: continue
            # Save every candidate u64 under this name for later resolution.
            for k, v in r.items():
                if k.endswith("_u64") or k.endswith("_i64"):
                    snowflake_to_name.setdefault(v, set()).add(name)
        with open(os.path.join(WD, "_tag_proto_dump.json"), "w") as f:
            json.dump(tp.get("results", []), f, indent=2)
    else:
        log(f"  enumerate_tag_protos failed: {tp}")

    # Hook to force real-instance materialization (and refresh tag fields).
    if not args.no_hook:
        log(f"hooking ALL TaggingRpcService methods for {args.hook_seconds}s")
        h = script.exports_sync.hook_for_real_instance(args.hook_seconds)
        log(f"  hooked {h.get('hookedCount')} methods")
        log(f"INTERACT: open the in-game tag manager and scroll through pokemon for {args.hook_seconds}s.")
        for left in range(args.hook_seconds, 0, -10):
            log(f"  {left}s remaining")
            time.sleep(min(10, left))
        captured_pointers = script.exports_sync.get_captured()
        n = len(captured_pointers.get("captured", {}))
        log(f"  captured {n} this-pointer(s) on TaggingRpcService")

    # Re-index after interaction (heap may have grown).
    log("re-indexing protos after hook window...")
    res = script.exports_sync.index_pokemon()
    log(f"  re-index: {res}")

    if args.phase in ("probe", "all"):
        log(f"PROBE: dumping RepeatedField for known Cinderace {KNOWN_UID_HEX}")
        low, high = uid_hex_to_low_high(KNOWN_UID_HEX)
        log(f"  low={low} high={high}")
        dump = script.exports_sync.dump_repeated_field(low, high)
        if not dump.get("ok"):
            log(f"probe failed: {dump}"); sys.exit(2)

        # Find a trial with count==1 and items pointer dereferenceable + the data
        # variant whose first id is plausibly a snowflake tag ID (NOT zero, NOT a
        # pointer-shaped value). PokemonTagIds_ stores 64-bit PokemonTagProto.id
        # values (snowflake-shaped), so we look for a non-zero u64 below
        # 2^63 and not in a pointer range.
        trials = dump["dump"].get("trials", [])
        winner = None
        for t in trials:
            if t.get("count") != 1: continue
            for variant_key in ("ids_at_data_0x20", "ids_at_data_0x10", "ids_at_data_0x00"):
                ids = t.get(variant_key, [])
                if not ids: continue
                v = int(ids[0])
                # Heuristic: snowflake IDs are ~10^17 to 10^19; pointers > 10^19.
                if 1 <= v < 10**19 and v < 0x7fffffffffffffff:
                    data_off = int(variant_key.rsplit("_", 1)[-1], 16)
                    winner = (int(t["countOff"], 16), int(t["itemsOff"], 16), data_off, t.get("count"), v)
                    log(f"  WINNER: countOff={hex(winner[0])} itemsOff={hex(winner[1])} dataOff={hex(winner[2])} count={winner[3]} sample_id={winner[4]}")
                    break
            if winner: break

        if not winner:
            log("could not find plausible RepeatedField layout for Cinderace")
            print(json.dumps(trials, indent=2))
            if args.phase == "all":
                log("aborting full extraction"); sys.exit(2)
        else:
            with open(os.path.join(WD, "_tag_repeated_field_offsets.json"), "w") as f:
                json.dump({"countOff":winner[0], "itemsOff":winner[1], "dataOff":winner[2]}, f)

    # Resolve offsets for extraction.
    if args.phase == "extract" or args.phase == "all":
        if args.count_off is not None and args.items_off is not None and args.data_off is not None:
            count_off, items_off, data_off = args.count_off, args.items_off, args.data_off
        else:
            try:
                with open(os.path.join(WD, "_tag_repeated_field_offsets.json")) as f:
                    off = json.load(f)
                count_off, items_off, data_off = off["countOff"], off["itemsOff"], off["dataOff"]
            except Exception:
                log("no offsets known and --count-off/--items-off/--data-off not provided"); sys.exit(2)

        log(f"EXTRACT: countOff={hex(count_off)} itemsOff={hex(items_off)} dataOff={hex(data_off)}")
        result = script.exports_sync.extract_all_tag_ids(count_off, items_off, data_off)
        if not result.get("ok"):
            log(f"extract failed: {result}"); sys.exit(2)
        stats = result["stats"]
        results = result["results"]
        log(f"  stats: {stats}")
        log(f"  pokemon with >=1 tag: {len(results)}")

        # Save raw JSON snapshot for forensics.
        with open(os.path.join(WD, "tag_ids_extracted.json"), "w") as f:
            json.dump({"stats":stats, "uid_to_tag_ids":results}, f)
        log(f"  wrote tag_ids_extracted.json ({len(results)} tagged pokemon)")

        # Update pokemon.db.
        log("updating pokemon.db...")
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cols = [r[1] for r in cur.execute("PRAGMA table_info(pokemon)").fetchall()]
        if "tag_ids" not in cols:
            cur.execute("ALTER TABLE pokemon ADD COLUMN tag_ids TEXT")
            log("  added tag_ids column")

        # Build uid -> tag_ids string. Match by signed int64 uid.
        # uid in pokemon.db is signed int64; results keys are decimal-string uids
        # produced by JS as (BigInt(hi)<<32n)|(BigInt(lo)&0xFFFFFFFFn) — that's the
        # 64-bit value reinterpreted as unsigned. Convert to signed for join.
        updates = []
        for uid_unsigned_str, ids in results.items():
            u = int(uid_unsigned_str)
            if u >= 0x8000000000000000:
                u -= 0x10000000000000000
            updates.append((";".join(ids), u))

        # Clear old values first (re-runs).
        cur.execute("UPDATE pokemon SET tag_ids = NULL")
        cur.executemany("UPDATE pokemon SET tag_ids = ? WHERE uid = ?", updates)
        n_updated = sum(1 for _ in cur.execute("SELECT 1 FROM pokemon WHERE tag_ids IS NOT NULL"))
        conn.commit()
        log(f"  rows updated: {n_updated}")

        # Summary report.
        log("=== SUMMARY ===")
        total = cur.execute("SELECT COUNT(*) FROM pokemon").fetchone()[0]
        with_tag = cur.execute("SELECT COUNT(*) FROM pokemon WHERE tag_ids IS NOT NULL").fetchone()[0]
        log(f"  total pokemon: {total}")
        log(f"  pokemon with >=1 tag: {with_tag}")

        # Tag-ID distribution.
        from collections import Counter
        cnt = Counter()
        for (s,) in cur.execute("SELECT tag_ids FROM pokemon WHERE tag_ids IS NOT NULL"):
            for t in s.split(";"):
                cnt[t] += 1
        # Load tag definitions for label.
        try:
            tagdefs = json.load(open(os.path.join(WD, "tag_definitions.json")))
        except Exception:
            tagdefs = {}
        log("  tag distribution:")
        # Build snowflake -> name from earlier enumeration. The extracted tag
        # IDs are unsigned-decimal strings; snowflake_to_name has both signed
        # and unsigned forms collected from heap probes. Try both.
        sf2name = {}
        for tag_id in cnt:
            names = snowflake_to_name.get(tag_id, set())
            if not names:
                # Try signed-twin
                try:
                    u = int(tag_id)
                    if u >= 0x8000000000000000:
                        signed = u - 0x10000000000000000
                    elif u < 0:
                        signed = u + 0x10000000000000000
                    else:
                        signed = u
                    names = snowflake_to_name.get(str(signed), set())
                except: pass
            if names:
                sf2name[tag_id] = sorted(names)[0]
        for tag_id, n in sorted(cnt.items(), key=lambda x:-x[1]):
            name = sf2name.get(tag_id, "?")
            log(f"    tag {tag_id:>22} ({name:<18}): {n}")

        # Verify the known Cinderace.
        row = cur.execute("SELECT uid_hex, species_name, tag_ids FROM pokemon WHERE uid_hex=?",
                          (KNOWN_UID_HEX,)).fetchone()
        log(f"  CINDERACE check: {row}")
        conn.close()

    log("done. detaching.")
    try: sess.detach()
    except: pass

if __name__ == "__main__":
    main()
