"""Extract EVERY primitive + string field from PokemonProto and PokemonDisplayProto
into pokemon.db.

The canonical pipeline decodes ~25 of 108 total fields. This enricher adds the
rest, populating a wide set of new columns. Read-only against the phone
(bag walk + proto-string follow only). Does NOT modify cull/tag state.

Field map authoritative source: proto_layout.json (from _dump_proto_layout.py
via IL2CPP class reflection — no guessed offsets).

Nested protos (PokemonCombatStatsProto, PokemonContestInfoProto, etc.) and
RepeatedFields (megaEvolvedForms, pokemonTagIds, originEvents, breadMoves,
branchedMegaEvolutionLevels) are skipped here — separate enrichers handle them
if/when needed.
"""
import argparse, json, os, re, sqlite3, struct, sys, time
import pogo_il2cpp as pg
from references import (
    LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    MEGA_EVOLUTION_IDS,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
FORM_ENUM_JSON = os.path.join(HERE, 'form_enum.json')

# 17 species with Gigantamax form released in PoGo (verified 2026-05-28).
# Includes #569 Garbodor (was missing from generate_tag_assignments).
GMAX_RELEASED_IDS = {3, 6, 9, 12, 25, 52, 68, 94, 99, 131, 143, 569,
                     812, 815, 818, 849, 861}

# Authoritative Adventure-Effect roster: 7 species, 9 forms total.
ADVENTURE_EFFECT_SPECIES = {483, 484, 646, 800, 888, 889, 890}


def _form_region(form_id, form_enum):
    name = form_enum.get(str(form_id), '') if form_id else ''
    if not name: return 'kantonian'
    if 'Hisuian' in name or 'WhiteStriped' in name: return 'hisuian'
    if 'Galarian' in name: return 'galarian'
    if 'Alola' in name: return 'alolan'
    if 'Paldean' in name or 'PaldeaCombat' in name: return 'paldean'
    return 'kantonian'

# ---------------------------------------------------------------------------
# JS: full bag walk reading proto bytes + display bytes + all strings inline
# ---------------------------------------------------------------------------
WALK_JS = r"""
function readStr(strPtr) {
    if (strPtr.isNull()) return null;
    var len = strPtr.add(0x10).readS32();
    if (len <= 0 || len > 500) return null;
    var chars = [];
    for (var i = 0; i < len; i++) chars.push(String.fromCharCode(strPtr.add(0x14 + i*2).readU16()));
    return chars.join('');
}

function bytesHex(p, n) {
    var bs = p.readByteArray(n);
    var u8 = new Uint8Array(bs);
    var s = '';
    for (var i = 0; i < u8.length; i++) s += ('0' + u8[i].toString(16)).slice(-2);
    return s;
}

rpc.exports.fullEnrichWalk = function(bagAddrStr) {
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
    var node = head, iters = 0;
    while (node && !node.isNull() && iters < lcount + 200) {
        try {
            var uid = node.add(0x28).readU64().toString();
            var proto = node.add(0x30).readPointer();
            var rec = {uid: uid};
            // Full proto bytes (512)
            rec.protoBytes = bytesHex(proto, 512);
            // Strings inside the proto (resolved via pointer follow)
            try { rec.deployedFortId       = readStr(proto.add(0x040).readPointer()); } catch(e) {}
            try { rec.ownerName            = readStr(proto.add(0x048).readPointer()); } catch(e) {}
            try { rec.eggIncubatorId       = readStr(proto.add(0x098).readPointer()); } catch(e) {}
            try { rec.nickname             = readStr(proto.add(0x0b8).readPointer()); } catch(e) {}
            try { rec.originalOwnerNickname= readStr(proto.add(0x100).readPointer()); } catch(e) {}
            try { rec.limitedPokemonId     = readStr(proto.add(0x130).readPointer()); } catch(e) {}
            try { rec.deployedStationId    = readStr(proto.add(0x1d0).readPointer()); } catch(e) {}
            // Display proto (144 bytes)
            try {
                var dispPtr = proto.add(0xd8).readPointer();
                if (!dispPtr.isNull()) rec.displayBytes = bytesHex(dispPtr, 144);
            } catch(e) {}
            out.push(rec);
            var next = node.add(0x18).readPointer();
            if (next.isNull() || next.equals(head)) break;
            node = next;
        } catch(e) { break; }
        iters++;
    }
    return out;
};
"""

# ---------------------------------------------------------------------------
# Field maps. (column_name, offset, prim_type, sql_type)
# prim_type: bool|i8|i16|i32|i64|u32|u64|f32|f64
# Naming convention: keep existing-DB-column names where they already exist;
# new fields get short clear names without prefix.
# ---------------------------------------------------------------------------
PROTO_FIELDS = [
    ('stamina',                       0x030, 'i32',  'INTEGER'),
    ('max_stamina',                   0x034, 'i32',  'INTEGER'),
    ('is_egg',                        0x050, 'bool', 'INTEGER'),
    ('egg_km_target',                 0x058, 'f64',  'REAL'),
    ('egg_km_start',                  0x060, 'f64',  'REAL'),
    ('pokeball_item',                 0x080, 'i32',  'INTEGER'),
    ('captured_s2_cell',              0x088, 'i64',  'INTEGER'),
    ('battles_attacked',              0x090, 'i32',  'INTEGER'),
    ('battles_defended',              0x094, 'i32',  'INTEGER'),
    ('creation_time_ms',              0x0a0, 'i64',  'INTEGER'),
    ('additional_cpm',                0x0ac, 'f32',  'REAL'),
    ('favorite',                      0x0b0, 'bool', 'INTEGER'),
    ('from_fort',                     0x0c0, 'bool', 'INTEGER'),
    ('buddy_candy_awarded',           0x0c4, 'i32',  'INTEGER'),
    ('buddy_km_walked',               0x0c8, 'f32',  'REAL'),
    ('display_pokemon_id',            0x0cc, 'i32',  'INTEGER'),
    ('display_cp',                    0x0d0, 'i32',  'INTEGER'),
    ('is_bad',                        0x0e0, 'bool', 'INTEGER'),
    ('hatched_from_egg',              0x0e1, 'bool', 'INTEGER'),
    ('coins_returned',                0x0e4, 'i32',  'INTEGER'),
    ('deployed_duration_ms',          0x0e8, 'i64',  'INTEGER'),
    ('deployed_returned_ts_ms',       0x0f0, 'i64',  'INTEGER'),
    ('cpm_before_trade',              0x0f8, 'f32',  'REAL'),
    ('traded_owner_hash',             0x0fc, 'i32',  'INTEGER'),
    ('traded_time_ms',                0x108, 'i64',  'INTEGER'),
    ('move2_is_purified_exclusive',   0x128, 'bool', 'INTEGER'),
    ('pre_boosted_cp',                0x138, 'i32',  'INTEGER'),
    ('pre_boosted_cpm',               0x13c, 'f32',  'REAL'),
    ('deployed_gym_lat',              0x140, 'f64',  'REAL'),
    ('deployed_gym_lng',              0x148, 'f64',  'REAL'),
    ('has_mega_evolved',              0x150, 'bool', 'INTEGER'),
    ('egg_type',                      0x154, 'i32',  'INTEGER'),
    ('temp_evo_cp',                   0x158, 'i32',  'INTEGER'),
    ('temp_evo_stamina_mod',          0x15c, 'f32',  'REAL'),
    ('temp_evo_cpm',                  0x160, 'f32',  'REAL'),
    ('size_enum',                     0x1a8, 'i32',  'INTEGER'),
    ('caught_in_party',               0x1b8, 'bool', 'INTEGER'),
    ('is_component',                  0x1b9, 'bool', 'INTEGER'),
    ('is_fusion',                     0x1ba, 'bool', 'INTEGER'),
    ('deployed_station_expiration_ms',0x1d8, 'i64',  'INTEGER'),
    ('is_stamp_reward',               0x1e0, 'bool', 'INTEGER'),
    ('is_actively_training',          0x1e1, 'bool', 'INTEGER'),
    ('marked_remote_tradable',        0x1f0, 'bool', 'INTEGER'),  # Forever Friends
    ('in_escrow',                     0x1f1, 'bool', 'INTEGER'),
]

DISPLAY_FIELDS = [
    ('gender',                        0x014, 'i32',  'INTEGER'),
    ('weather_boost',                 0x020, 'i32',  'INTEGER'),
    ('temp_evo_finish_ms',            0x030, 'i64',  'INTEGER'),
    ('temp_evo_locked',               0x038, 'bool', 'INTEGER'),
    ('locked_temp_evo',               0x03c, 'i32',  'INTEGER'),
    ('original_costume',              0x040, 'i32',  'INTEGER'),
    ('display_id',                    0x048, 'i64',  'INTEGER'),
    ('shiny_rate',                    0x068, 'f32',  'REAL'),
    ('location_card_rate',            0x06c, 'f32',  'REAL'),
    ('natural_art_type',              0x070, 'i32',  'INTEGER'),
    ('natural_art_bg',                0x074, 'i32',  'INTEGER'),
    ('natural_art_full_scene',        0x078, 'bool', 'INTEGER'),
    ('day_night_type',                0x07c, 'i32',  'INTEGER'),
]

# (col_name, json_key_from_walk) — strings written as TEXT
# original_owner_name is the existing DB column; write the proto value there too
# so the existing audit_tags From Ethan/Florandez rules see fresh data.
STRING_FIELDS = [
    ('deployed_fort_id',         'deployedFortId',         True),
    ('owner_name',               'ownerName',              True),
    ('egg_incubator_id',         'eggIncubatorId',         True),
    ('nickname',                 'nickname',               True),
    ('original_owner_nickname',  'originalOwnerNickname',  True),
    # also write originalOwnerNickname to the legacy original_owner_name col
    ('original_owner_name',      'originalOwnerNickname',  False),
    ('limited_pokemon_id',       'limitedPokemonId',       True),
    ('deployed_station_id',      'deployedStationId',      True),
]

# Derived/backfill columns — keep existing legacy column names live for cull
# correctness (cull_v9 reads is_best_buddy + is_deployed) and add new live
# columns for the comprehensive per-pokemon decision pipeline. Computed from
# already-extracted primitives + references.py classifications.
# (sql_col, sql_type, "live"?) — non-live means just backfill an existing legacy column
DERIVED_FIELDS = [
    ('is_best_buddy',         'INTEGER', False),  # cull rule reads this
    ('is_deployed',           'INTEGER', False),  # cull rule reads this
    ('is_purified_flag',      'INTEGER', False),  # legacy mirror of alignment=2
    ('is_mega_evolved',       'INTEGER', False),  # legacy mirror of fresh_current_temp_evolution!=0
    ('is_legendary',          'INTEGER', False),
    ('is_mythical',           'INTEGER', False),
    ('is_ultra_beast',        'INTEGER', True),
    ('is_paradox',            'INTEGER', True),
    ('can_mega_evolve',       'INTEGER', False),
    ('is_dynamax_capable',    'INTEGER', False),
    ('is_gigantamax_capable', 'INTEGER', False),
    ('is_adventure_effect_species', 'INTEGER', True),
    ('form_region',           'TEXT',    True),
    ('was_best_buddy_badge',  'INTEGER', True),  # fresh_pokemon_badge == 1 (Best Buddy badge)
    ('is_three_star',         'INTEGER', True),  # iv_total >= 37
    ('is_four_star',          'INTEGER', True),  # iv_total == 45 (= is_hundo, but keep both names for clarity)
]


def decode(bs, offset, typ):
    if not bs: return None
    if typ == 'bool':
        return bs[offset] if offset < len(bs) else None
    if typ == 'i8':
        if offset >= len(bs): return None
        v = bs[offset]
        return v if v < 128 else v - 256
    if typ == 'i32':
        return struct.unpack_from('<i', bs, offset)[0] if offset+4 <= len(bs) else None
    if typ == 'i64':
        return struct.unpack_from('<q', bs, offset)[0] if offset+8 <= len(bs) else None
    if typ == 'u32':
        return struct.unpack_from('<I', bs, offset)[0] if offset+4 <= len(bs) else None
    if typ == 'u64':
        return struct.unpack_from('<Q', bs, offset)[0] if offset+8 <= len(bs) else None
    if typ == 'f32':
        return struct.unpack_from('<f', bs, offset)[0] if offset+4 <= len(bs) else None
    if typ == 'f64':
        return struct.unpack_from('<d', bs, offset)[0] if offset+8 <= len(bs) else None
    return None


def ensure_columns(conn):
    c = conn.cursor()
    existing = {r[1] for r in c.execute('PRAGMA table_info(pokemon)')}
    added = []
    all_new = (
        [(name, sql) for name, _, _, sql in PROTO_FIELDS] +
        [(name, sql) for name, _, _, sql in DISPLAY_FIELDS] +
        [(name, 'TEXT') for name, _, is_new in STRING_FIELDS if is_new] +
        [(name, sql) for name, sql, is_new in DERIVED_FIELDS if is_new]
    )
    for name, sql_type in all_new:
        if name not in existing:
            c.execute(f'ALTER TABLE pokemon ADD COLUMN {name} {sql_type}')
            added.append(name)
    conn.commit()
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    print('Attaching...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')
    try:
        bag = pg.find_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        print(f'  bag @ {bag}')
        script = pg.get_script_with_helpers(sess, WALK_JS)
        t0 = time.time()
        entries = script.exports_sync.full_enrich_walk(bag)
        print(f'  walked {len(entries)} entries in {time.time()-t0:.2f}s')
        script.unload()
    finally:
        sess.detach()

    if args.dry_run:
        # Show one example to verify
        ex = entries[0] if entries else None
        if ex:
            print(f'\nExample (first entry):')
            print(f'  uid={ex["uid"]}')
            print(f'  nickname={ex.get("nickname")!r}')
            print(f'  ownerName={ex.get("ownerName")!r}')
            print(f'  originalOwnerNickname={ex.get("originalOwnerNickname")!r}')
            pBytes = bytes.fromhex(ex['protoBytes'])
            dBytes = bytes.fromhex(ex.get('displayBytes') or '')
            print('  proto decoded:')
            for name, off, typ, _ in PROTO_FIELDS:
                v = decode(pBytes, off, typ)
                print(f'    {name:32s} = {v}')
            print('  display decoded:')
            for name, off, typ, _ in DISPLAY_FIELDS:
                v = decode(dBytes, off, typ)
                print(f'    {name:32s} = {v}')
        print('\n(--dry-run; no DB writes)')
        return

    conn = sqlite3.connect(DB)
    added = ensure_columns(conn)
    if added:
        print(f'  added {len(added)} new columns: {added}')

    form_enum = json.load(open(FORM_ENUM_JSON, encoding='utf-8')) if os.path.exists(FORM_ENUM_JSON) else {}

    c = conn.cursor()
    proto_cols = [name for name, _, _, _ in PROTO_FIELDS]
    disp_cols  = [name for name, _, _, _ in DISPLAY_FIELDS]
    string_cols = [name for name, _, _ in STRING_FIELDS]
    derived_cols = [name for name, _, _ in DERIVED_FIELDS]
    all_cols = proto_cols + disp_cols + string_cols + derived_cols
    set_clause = ', '.join(f'{col}=?' for col in all_cols)
    update_sql = f'UPDATE pokemon SET {set_clause} WHERE uid_hex=?'

    # Pull pokemon_id, form, iv_total, fresh_current_temp_evolution, fresh_alignment
    # for derived computation (these come from the DB which is fresh from pipeline)
    info_rows = c.execute(
        "SELECT uid_hex, pokemon_id, form, iv_total, fresh_current_temp_evolution, fresh_alignment "
        "FROM pokemon WHERE in_bag=1"
    ).fetchall()
    info_map = {r[0]: r[1:] for r in info_rows}

    n_updated = 0
    t0 = time.time()
    for rec in entries:
        uid_unsigned = int(rec['uid'])
        uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
        pBytes = bytes.fromhex(rec['protoBytes'])
        dBytes = bytes.fromhex(rec.get('displayBytes') or '')

        # Decode proto + display primitives + strings
        vals = []
        decoded_proto = {}
        decoded_disp  = {}
        for name, off, typ, _ in PROTO_FIELDS:
            v = decode(pBytes, off, typ)
            decoded_proto[name] = v
            vals.append(v)
        for name, off, typ, _ in DISPLAY_FIELDS:
            v = decode(dBytes, off, typ) if dBytes else None
            decoded_disp[name] = v
            vals.append(v)
        for _, json_key, _ in STRING_FIELDS:
            vals.append(rec.get(json_key))

        # Derived fields — order matches DERIVED_FIELDS list
        info = info_map.get(uid_hex)
        if info:
            pid, form_id, iv_total, fresh_tempevo, fresh_align = info
        else:
            # New UID not in DB yet (insert pending) — fall back to proto-decoded values
            pid = decoded_proto.get('pokemon_id')  # not in PROTO_FIELDS by name — use proto bytes
            pid = struct.unpack_from('<i', pBytes, 0x28)[0] if len(pBytes) >= 0x2c else 0
            form_id = decoded_disp.get('original_costume')  # not exactly form; safer to skip
            form_id = struct.unpack_from('<i', dBytes, 0x1c)[0] if dBytes and len(dBytes) >= 0x20 else 0
            iv_total = (decoded_proto.get('stamina', 0) or 0)  # not right; recompute
            iv_atk = struct.unpack_from('<i', pBytes, 0x70)[0] if len(pBytes) >= 0x74 else 0
            iv_def = struct.unpack_from('<i', pBytes, 0x74)[0] if len(pBytes) >= 0x78 else 0
            iv_sta = struct.unpack_from('<i', pBytes, 0x78)[0] if len(pBytes) >= 0x7c else 0
            iv_total = iv_atk + iv_def + iv_sta
            fresh_tempevo = struct.unpack_from('<i', dBytes, 0x2c)[0] if dBytes and len(dBytes) >= 0x30 else 0
            fresh_align = struct.unpack_from('<i', dBytes, 0x24)[0] if dBytes and len(dBytes) >= 0x28 else 0

        add_cpm = decoded_proto.get('additional_cpm') or 0
        deployed_fort = rec.get('deployedFortId')
        badge = struct.unpack_from('<i', dBytes, 0x28)[0] if dBytes and len(dBytes) >= 0x2c else 0

        derived = {
            'is_best_buddy':         1 if add_cpm > 0 else 0,
            'is_deployed':           1 if (deployed_fort and deployed_fort.strip()) else 0,
            'is_purified_flag':      1 if fresh_align == 2 else 0,
            'is_mega_evolved':       1 if (fresh_tempevo or 0) != 0 else 0,
            'is_legendary':          1 if pid in LEGENDARY_IDS else 0,
            'is_mythical':           1 if pid in MYTHICAL_IDS else 0,
            'is_ultra_beast':        1 if pid in ULTRA_BEAST_IDS else 0,
            'is_paradox':            1 if pid in PARADOX_IDS else 0,
            'can_mega_evolve':       1 if pid in MEGA_EVOLUTION_IDS else 0,
            'is_dynamax_capable':    None,  # canonical list not derivable; skip
            'is_gigantamax_capable': 1 if pid in GMAX_RELEASED_IDS else 0,
            'is_adventure_effect_species': 1 if pid in ADVENTURE_EFFECT_SPECIES else 0,
            'form_region':           _form_region(form_id, form_enum),
            'was_best_buddy_badge':  1 if badge == 1 else 0,
            'is_three_star':         1 if (iv_total or 0) >= 37 else 0,
            'is_four_star':          1 if (iv_total or 0) == 45 else 0,
        }
        for name, _, _ in DERIVED_FIELDS:
            vals.append(derived.get(name))

        vals.append(uid_hex)
        c.execute(update_sql, vals)
        if c.rowcount > 0: n_updated += 1
    conn.commit()
    print(f'  DB updated: {n_updated}/{len(entries)} rows in {time.time()-t0:.2f}s')

    # ---- Quick verification snapshot ----
    print('\n=== Verification ===')
    GENDER = {0:'UNSET', 1:'MALE', 2:'FEMALE', 3:'GENDERLESS'}
    print('Gender distribution (in_bag):')
    for g, n in c.execute("SELECT gender, COUNT(*) FROM pokemon WHERE in_bag=1 GROUP BY gender ORDER BY gender"):
        print(f'  {g} ({GENDER.get(g, "?")}): {n}')
    fav   = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND favorite=1").fetchone()[0]
    nick  = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND nickname IS NOT NULL AND nickname != ''").fetchone()[0]
    mega  = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND has_mega_evolved=1").fetchone()[0]
    remote= c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND marked_remote_tradable=1").fetchone()[0]
    hatch = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND hatched_from_egg=1").fetchone()[0]
    party = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND caught_in_party=1").fetchone()[0]
    fort  = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND from_fort=1").fetchone()[0]
    own   = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND original_owner_name IS NOT NULL AND original_owner_name != ''").fetchone()[0]
    print(f'Favorite:                 {fav}')
    print(f'Nicknamed:                {nick}')
    print(f'Has mega-evolved (ever):  {mega}')
    print(f'Marked remote-tradable:   {remote}  (Forever Friends opt-in)')
    print(f'Hatched from egg:         {hatch}')
    print(f'Caught in party play:     {party}')
    print(f'From fort/raid:           {fort}')
    print(f'Has original owner name:  {own}')

    # Combee gender check (relevant for Vespiquen evolution)
    print('\nCombee (pid 415) gender breakdown:')
    for r in c.execute("SELECT uid_hex, cp, iv_total, fresh_shiny, gender FROM pokemon WHERE in_bag=1 AND pokemon_id=415 ORDER BY iv_total DESC"):
        g = GENDER.get(r[4], f'enum{r[4]}')
        sh = '★' if r[3] else ' '
        print(f'  {r[0]}  cp={r[1]:>4} iv={r[2]:>2} shiny={sh} gender={g}')

    conn.close()


if __name__ == '__main__':
    main()
