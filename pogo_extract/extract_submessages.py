"""extract_submessages.py — read PokemonMegaEvolutionLevelProto + LocationCardDisplayProto
contents for every pokemon, populate DB columns + summarize.

Connects via ZygiskFrida gadget on port 27047 (PoGo MUST be already running).
"""
import frida, json, sqlite3, subprocess, sys, time

DB = 'pokemon.db'
SCRIPT = 'extract_submessages.js'

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def attach_gadget():
    subprocess.run(["adb","forward","tcp:27047","tcp:27047"],
                   capture_output=True, timeout=10)
    mgr = frida.get_device_manager()
    d = mgr.add_remote_device("127.0.0.1:27047")
    return d.attach("Gadget")

def main():
    sess = attach_gadget()
    log("attached to Gadget")

    src = open(SCRIPT,"r",encoding="utf-8").read()
    script = sess.create_script(src)
    msgs = []
    def on_msg(m, data):
        if m.get("type") == "send":
            msgs.append(m["payload"])
            p = m["payload"]
            if p.get("type") == "status":
                log(f"  [JS] {p.get('msg')}")
        elif m.get("type") == "error":
            log(f"  [FRIDA-ERR] {m.get('description')}")
    script.on("message", on_msg)
    script.load()
    time.sleep(0.5)

    # init
    st = script.exports_sync.init_status()
    log(f"init: {st}")
    if not st.get("ready"):
        log(f"FAIL: {st}")
        return

    # probe class layouts
    log("probing class layouts...")
    probe = script.exports_sync.probe_fields()
    if not probe.get("ok"):
        log(f"probe failed: {probe}")
        return

    log("--- PokemonMegaEvolutionLevelProto ---")
    mega_fields = probe['mega']['fields']
    for f in mega_fields:
        log(f"  +0x{f['offset']:02x} {f['name']:30s} {f['type']}")

    log("--- LocationCardDisplayProto ---")
    loc_fields = probe['locCard']['fields']
    for f in loc_fields:
        log(f"  +0x{f['offset']:02x} {f['name']:30s} {f['type']}")

    log("--- LocationCard (inner) ---")
    loc_inner_fields = probe.get('locCardInner', {}).get('fields', []) or []
    for f in loc_inner_fields:
        log(f"  +0x{f['offset']:02x} {f['name']:30s} {f['type']}")

    log("--- TempEvoLocationDisplayAttributes ---")
    temp_fields = probe.get('tempEvo', {}).get('fields', []) or []
    for f in temp_fields:
        log(f"  +0x{f['offset']:02x} {f['name']:30s} {f['type']}")

    # save the schema so we know what columns to add to the DB
    with open('submessage_schema.json','w') as f:
        json.dump({
            'mega': mega_fields,
            'locationCard': loc_fields,
            'locationCardInner': loc_inner_fields,
            'tempEvo': temp_fields,
        }, f, indent=2)
    log("saved submessage_schema.json")

    # index pokemon protos
    log("indexing PokemonProto in heap...")
    idx = script.exports_sync.index_pokemon()
    log(f"index: {idx}")

    # Detect enum classes: heuristic = has a value__ field at +0x10 + other "fields"
    # at offset 0 (the enum constants). Pass these type names to the extractor so
    # it reads them as i32 instead of dereferencing as a sub-message pointer.
    def is_enum(probe_entry):
        if not probe_entry or not probe_entry.get('fields'): return False
        names = [f['name'] for f in probe_entry['fields']]
        return 'value__' in names

    enum_types = {}
    if is_enum(probe.get('locCardInner')):
        # probe response gave us the type literal as Holoholo.Rpc.LocationCard
        enum_types['Holoholo.Rpc.LocationCard'] = True
    log(f"enum types: {list(enum_types.keys())}")

    # extract sub-messages
    log("extracting sub-messages...")
    res = script.exports_sync.extract_all(mega_fields, loc_fields, loc_inner_fields, temp_fields, enum_types)
    if not res.get("ok"):
        log(f"extract failed: {res}")
        return
    stats = res['stats']
    results = res['results']
    log(f"stats: {stats}")
    log(f"got {len(results)} pokemon with non-null sub-messages")

    with open('submessage_results.json','w') as f:
        json.dump(res, f, indent=2)
    log("saved submessage_results.json")

    # populate DB
    log("populating DB columns...")
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # Build column list from probed fields. Prefix with mega_ / loc_ / temp_.
    def col_list(prefix, fields):
        out = []
        for f in fields:
            if f['offset'] < 0x10: continue
            t = f['type']
            simple = t.split('.')[-1]
            if simple in ('Int32','UInt32','Int64','UInt64','Byte','Boolean'):
                col_type = 'INTEGER'
            elif simple in ('Single','Double'):
                col_type = 'REAL'
            elif simple == 'String':
                col_type = 'TEXT'
            else:
                # sub-pointer: just 0/1 flag column
                col_type = 'INTEGER'
            out.append((prefix + f['name'].rstrip('_'), col_type, f['name'], simple))
        return out

    mega_cols = col_list('mega_', mega_fields)
    loc_cols = col_list('loc_', loc_fields)
    # loc_inner is the enum constant list, not real instance fields - don't add columns
    temp_cols = col_list('temp_', temp_fields)

    existing = {row[1] for row in c.execute("PRAGMA table_info(pokemon)").fetchall()}
    all_cols = []
    for cols in [mega_cols, loc_cols, temp_cols]:
        for col_name, col_type, _, _ in cols:
            if col_name not in existing:
                c.execute(f"ALTER TABLE pokemon ADD COLUMN \"{col_name}\" {col_type}")
                log(f"  added {col_name} {col_type}")
            all_cols.append(col_name)

    # Reset all sub-message columns to NULL so stale data from previous runs is cleared.
    if all_cols:
        sql = "UPDATE pokemon SET " + ", ".join([f'"{c}"=NULL' for c in all_cols])
        c.execute(sql)
        log(f"  reset {len(all_cols)} columns to NULL")

    # Update rows. Match by uid (signed int64).
    n = 0
    for uid_str, rec in results.items():
        # Convert uid to signed int64 to match DB storage
        uid_unsigned = int(uid_str)
        if uid_unsigned >= (1 << 63):
            uid_signed = uid_unsigned - (1 << 64)
        elif uid_unsigned < -(1 << 63):
            uid_signed = uid_unsigned + (1 << 64)
        else:
            uid_signed = uid_unsigned

        sets = []
        vals = []
        for prefix, fields, sub in [
            ('mega_', mega_cols, rec.get('mega')),
            ('loc_',  loc_cols,  rec.get('locationCard')),
            ('temp_', temp_cols, rec.get('tempEvo')),
        ]:
            if not sub: continue
            for col_name, col_type, src_name, simple in fields:
                v = sub.get(src_name)
                if v is None and simple not in ('String',):
                    # Some types (sub-pointers) get suffixed with _ptr/_i32/_i64
                    v_ptr = sub.get(src_name + "_ptr")
                    if v_ptr is not None:
                        v = 1 if v_ptr != "0x0" else 0
                if v is None: continue
                if isinstance(v, bool): v = 1 if v else 0
                sets.append(f'"{col_name}"=?')
                vals.append(v)

        if not sets: continue
        vals.append(uid_signed)
        sql = f'UPDATE pokemon SET {", ".join(sets)} WHERE uid=?'
        c.execute(sql, vals)
        if c.rowcount > 0:
            n += 1

    conn.commit()
    log(f"updated {n} rows")

    # Build lookup: location card enum int -> name
    loc_card_names = {}  # int -> name
    for f in loc_inner_fields:
        if f['name'] == 'value__': continue
        # Each enum constant has its int value... but we don't have it in metadata.
        # Index by declaration order starting at 0 (Unset=0, then enumerated).
        loc_card_names[len(loc_card_names)] = f['name']

    # Save mapping so users can lookup by int
    with open('location_card_enum.json','w') as f:
        json.dump(loc_card_names, f, indent=2)
    log(f"saved location_card_enum.json ({len(loc_card_names)} cards)")

    # Summary
    log("\n=== SUMMARY ===")

    log(f"\nMega evolution levels (mega_Level distribution):")
    for r in c.execute('SELECT mega_Level, count(*) FROM pokemon WHERE mega_Level IS NOT NULL GROUP BY mega_Level ORDER BY 2 DESC'):
        log(f"  level={r[0]}: {r[1]} pokemon")

    log(f"\nMega Points distribution:")
    for r in c.execute('SELECT mega_Points, count(*) FROM pokemon WHERE mega_Points IS NOT NULL GROUP BY mega_Points ORDER BY 1 DESC LIMIT 30'):
        log(f"  points={r[0]}: {r[1]} pokemon")

    log(f"\nUnique location cards (loc_LocationCard enum int -> name):")
    for r in c.execute('SELECT loc_LocationCard, count(*) FROM pokemon WHERE loc_LocationCard IS NOT NULL GROUP BY loc_LocationCard ORDER BY 2 DESC'):
        ev = loc_card_names.get(r[0], f"?{r[0]}")
        log(f"  {r[0]:5d} ({ev}): {r[1]} pokemon")

    log("\nSample LocationCard pokemon (species, card_int, card_name):")
    for r in c.execute('SELECT species_name, loc_LocationCard FROM pokemon WHERE loc_LocationCard IS NOT NULL ORDER BY species_name LIMIT 25'):
        ev = loc_card_names.get(r[1], f"?{r[1]}")
        log(f"  {r[0]:20s} {r[1]:5d} {ev}")

    # Coverage check
    coverage_q = '''
        SELECT
            (SELECT count(*) FROM pokemon WHERE has_mega_evolution_level=1) AS flag_mega,
            (SELECT count(*) FROM pokemon WHERE mega_Level IS NOT NULL) AS got_mega,
            (SELECT count(*) FROM pokemon WHERE has_location_card=1) AS flag_loc,
            (SELECT count(*) FROM pokemon WHERE loc_LocationCard IS NOT NULL) AS got_loc
    '''
    cov = c.execute(coverage_q).fetchone()
    log(f"\nCoverage:")
    log(f"  has_mega_evolution_level=1: {cov[0]}, populated: {cov[1]} (missing: {cov[0]-cov[1]})")
    log(f"  has_location_card=1:        {cov[2]}, populated: {cov[3]} (missing: {cov[2]-cov[3]})")

    log("\nSample Mega pokemon (species, points, level):")
    for r in c.execute('SELECT species_name, mega_Points, mega_Level FROM pokemon WHERE has_mega_evolution_level=1 ORDER BY species_name LIMIT 20'):
        log(f"  {r[0]:20s} points={r[1]} level={r[2]}")

    conn.close()
    log("done")
    try: sess.detach()
    except: pass

if __name__ == "__main__":
    main()
