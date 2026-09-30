"""Reconcile DB against authoritative full_inventory_v2 (5031 pokemon, 222 shadows).

- Mark each DB entry as in_bag=1 if its UID is in the inventory, else 0 (transferred ghost).
- For new UIDs in inventory not in DB, insert them (parsed from protoBytes).
- Update fresh_* columns from the authoritative data.
"""
import json, sqlite3, struct

with open('full_inventory_v2.json') as f:
    data = json.load(f)
results = data['results']
print(f"Authoritative inventory: {len(results)} pokemon")

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
if 'in_bag' not in cols:
    c.execute("ALTER TABLE pokemon ADD COLUMN in_bag INTEGER")

# Pre-mark all as not-in-bag (will set 1 below)
c.execute("UPDATE pokemon SET in_bag=0")

# Build set of authoritative UIDs
auth_uids = set()
for uid_str in results.keys():
    uid_unsigned = int(uid_str)
    uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
    auth_uids.add(uid_hex)

# Mark each in DB
n_marked = 0
for uid_hex in auth_uids:
    r = c.execute("UPDATE pokemon SET in_bag=1 WHERE uid_hex=?", (uid_hex,)).rowcount
    n_marked += r
print(f"Marked in_bag=1 for {n_marked} existing DB rows")

# Find UIDs in inventory but not in DB
db_uids = set(r[0] for r in c.execute("SELECT uid_hex FROM pokemon").fetchall())
new_uids = auth_uids - db_uids
print(f"NEW UIDs in inventory not in DB: {len(new_uids)}")
ghost_uids = db_uids - auth_uids
print(f"GHOST UIDs in DB but not in inventory (transferred): {len(ghost_uids)}")

# Update fresh_* columns from authoritative data for ALL pokemon in inventory
def i32(bs, o): return struct.unpack_from('<i', bs, o)[0] if o+4 <= len(bs) else 0
def i64(bs, o): return struct.unpack_from('<q', bs, o)[0] if o+8 <= len(bs) else 0
def f32(bs, o): return struct.unpack_from('<f', bs, o)[0] if o+4 <= len(bs) else 0.0
def byte(bs, o): return bs[o] if o < len(bs) else 0

species_lookup = {r[0]: r[1] for r in c.execute("SELECT DISTINCT pokemon_id, species_name FROM pokemon WHERE species_name IS NOT NULL").fetchall()}

# CPM table for level
def cpm_to_level(cpm):
    table = [(0.094,1.0),(0.135137432,1.5),(0.16639787,2.0),(0.192650919,2.5),(0.21573247,3.0),(0.236572661,3.5),(0.25572005,4.0),(0.273530381,4.5),(0.29024988,5.0),(0.306057377,5.5),(0.3210876,6.0),(0.335445036,6.5),(0.34921268,7.0),(0.362457751,7.5),(0.37523559,8.0),(0.387592406,8.5),(0.39956728,9.0),(0.411193551,9.5),(0.42250001,10.0),(0.432926419,10.5),(0.44310755,11.0),(0.4530599578,11.5),(0.46279839,12.0),(0.472336083,12.5),(0.48168495,13.0),(0.4908558,13.5),(0.49985844,14.0),(0.508701765,14.5),(0.51739395,15.0),(0.525942511,15.5),(0.53435433,16.0),(0.542635767,16.5),(0.55079269,17.0),(0.558830576,17.5),(0.56675452,18.0),(0.574569153,18.5),(0.58227891,19.0),(0.589887907,19.5),(0.59740001,20.0),(0.604818814,20.5),(0.61215729,21.0),(0.619399365,21.5),(0.62656713,22.0),(0.633644533,22.5),(0.64065295,23.0),(0.647576426,23.5),(0.65443563,24.0),(0.661214806,24.5),(0.667934,25.0),(0.674577537,25.5),(0.68116492,26.0),(0.687680648,26.5),(0.69414365,27.0),(0.700538673,27.5),(0.7068842,28.0),(0.713164996,28.5),(0.71939909,29.0),(0.725571552,29.5),(0.7317,30.0),(0.734741009,30.5),(0.73776948,31.0),(0.740785574,31.5),(0.74378943,32.0),(0.746781211,32.5),(0.74976104,33.0),(0.752729087,33.5),(0.7556855,34.0),(0.758630378,34.5),(0.76156384,35.0),(0.764486065,35.5),(0.76739717,36.0),(0.770297266,36.5),(0.7731865,37.0),(0.776064962,37.5),(0.77893275,38.0),(0.781790055,38.5),(0.78463697,39.0),(0.787473578,39.5),(0.79030001,40.0),(0.792803968,40.5),(0.79530001,41.0),(0.797800015,41.5),(0.8003,42.0),(0.802799995,42.5),(0.8053,43.0),(0.807800014,43.5),(0.81029999,44.0),(0.812799985,44.5),(0.81529999,45.0),(0.81779999,45.5),(0.82029998,46.0),(0.82279998,46.5),(0.82529997,47.0),(0.82779996,47.5),(0.83029996,48.0),(0.83279996,48.5),(0.83529995,49.0),(0.83779995,49.5),(0.84029995,50.0),(0.84279995,50.5),(0.84529994,51.0)]
    if cpm <= 0: return 0.0
    for cpm_v, lvl in table:
        if cpm <= cpm_v + 1e-6:
            return lvl
    return 51.0

# Insert new ones
inserted = 0
shadow_inserted = 0
for uid_str, rec in results.items():
    uid_unsigned = int(uid_str)
    uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
    if uid_hex in db_uids: continue
    if uid_hex not in new_uids: continue
    uid = uid_unsigned if uid_unsigned <= 2**63-1 else uid_unsigned - 2**64

    pb = rec.get('protoBytes')
    db_b = rec.get('displayBytes')
    if not pb or not db_b: continue
    bs = bytes.fromhex(pb)
    dbs = bytes.fromhex(db_b)

    pid = i32(bs, 0x28)
    cp = i32(bs, 0x2c)
    iv_atk = i32(bs, 0x70)
    iv_def = i32(bs, 0x74)
    iv_sta = i32(bs, 0x78)
    cpm = f32(bs, 0x7c)
    level = cpm_to_level(cpm)
    is_lucky = byte(bs, 0x110)
    favorite = byte(bs, 0xb0)
    num_upgrades = i32(bs, 0xa8)
    move1 = i32(bs, 0x38); move2 = i32(bs, 0x3c); move3 = i32(bs, 0x114)
    trad = i32(bs, 0xfc)
    iv_total = iv_atk + iv_def + iv_sta
    iv_pct = iv_total * 100 / 45.0

    costume = i32(dbs, 0x10)
    is_shiny = byte(dbs, 0x18)
    form = i32(dbs, 0x1c)
    align = i32(dbs, 0x24)
    badge = i32(dbs, 0x28)
    cur_temp_evo = i32(dbs, 0x2c)
    bread_mode = i32(dbs, 0x60)
    is_strong = byte(dbs, 0x64)
    has_loc = 1 if rec.get('locBytes') else 0
    has_mega = 1 if rec.get('megaBytes') else 0

    align_name = {0:'NORMAL',1:'SHADOW',2:'PURIFIED'}.get(align,str(align))
    species = species_lookup.get(pid, f'pid{pid}')
    is_hundo = 1 if iv_atk==15 and iv_def==15 and iv_sta==15 else 0
    is_zero = 1 if iv_atk==0 and iv_def==0 and iv_sta==0 else 0
    is_traded = 1 if trad != 0 else 0

    tag_ids = ';'.join(rec.get('tagIds',[]))
    tag_count = rec.get('tagCount',0)

    if align == 1: shadow_inserted += 1

    c.execute("""INSERT INTO pokemon
        (uid_hex, uid, pokemon_id, species_name, cp, level, form,
         iv_atk, iv_def, iv_sta, iv_total, iv_pct,
         is_shiny, is_lucky, is_traded, is_hundo, is_zero,
         alignment, alignment_name, costume_decoration_id,
         move1, move2, move3,
         is_powered_up, is_traded_flag_v2,
         in_bag,
         fresh_in_heap, fresh_costume, fresh_form, fresh_alignment, fresh_pokemon_badge,
         fresh_current_temp_evolution, fresh_has_mega_level, fresh_has_location_card,
         fresh_bread_mode, fresh_is_strong, fresh_shiny,
         fresh_tag_count, fresh_tag_ids)
        VALUES (?,?,?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?, ?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?)""",
        (uid_hex, uid, pid, species, cp, level, form,
         iv_atk, iv_def, iv_sta, iv_total, iv_pct,
         is_shiny, is_lucky, is_traded, is_hundo, is_zero,
         align, align_name, costume,
         move1, move2, move3,
         1 if num_upgrades>0 else 0, is_traded,
         1,
         1, costume, form, align, badge,
         cur_temp_evo, has_mega, has_loc,
         bread_mode, is_strong, is_shiny,
         tag_count, tag_ids))
    inserted += 1

# Re-update fresh_* for ALL in-bag pokemon (refresh from authoritative data)
for uid_str, rec in results.items():
    uid_unsigned = int(uid_str)
    uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
    db_b = rec.get('displayBytes')
    if not db_b: continue
    dbs = bytes.fromhex(db_b)
    align = i32(dbs, 0x24)
    is_shiny = byte(dbs, 0x18)
    costume = i32(dbs, 0x10)
    bread_mode = i32(dbs, 0x60)
    badge = i32(dbs, 0x28)
    is_strong = byte(dbs, 0x64)
    has_loc = 1 if rec.get('locBytes') else 0
    has_mega = 1 if rec.get('megaBytes') else 0
    cur_temp_evo = i32(dbs, 0x2c)
    tag_ids = ';'.join(rec.get('tagIds', []))

    c.execute("""UPDATE pokemon SET
        fresh_alignment=?, fresh_shiny=?, fresh_costume=?, fresh_bread_mode=?,
        fresh_pokemon_badge=?, fresh_is_strong=?, fresh_has_location_card=?,
        fresh_has_mega_level=?, fresh_current_temp_evolution=?, fresh_tag_ids=?
        WHERE uid_hex=?""",
        (align, is_shiny, costume, bread_mode, badge, is_strong,
         has_loc, has_mega, cur_temp_evo, tag_ids, uid_hex))

conn.commit()

print(f"\nInserted {inserted} new pokemon ({shadow_inserted} shadows)")

# Verify final counts
total_in_bag = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1").fetchone()[0]
shadow_in_bag = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_alignment=1").fetchone()[0]
purified_in_bag = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_alignment=2").fetchone()[0]
shiny_in_bag = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_shiny=1").fetchone()[0]
print(f"\n=== FINAL DB STATE (in_bag=1) ===")
print(f"  Total: {total_in_bag}")
print(f"  Shadow: {shadow_in_bag}")
print(f"  Purified: {purified_in_bag}")
print(f"  Shiny: {shiny_in_bag}")

ghost_count = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=0").fetchone()[0]
print(f"\n  Ghost rows (transferred): {ghost_count}")

conn.close()
