"""Refresh pokemon_size_category from full_inventory_v3 protoBytes (offset 424 i32)."""
import json, sqlite3, struct

with open('full_inventory_v3.json') as f:
    data = json.load(f)
results = data['results']
print(f"Inventory: {len(results)} entries")

conn = sqlite3.connect('pokemon.db'); c = conn.cursor()

# Before snapshot
before = {row[0]: row[1] for row in c.execute("SELECT pokemon_size_category, COUNT(*) FROM pokemon WHERE in_bag=1 GROUP BY pokemon_size_category")}
print("\nBefore (in_bag):")
for k in sorted(before, key=lambda x: x or -1):
    label = {1:'XXS',2:'XS',3:'NORMAL',4:'L',5:'JUMBO'}.get(k, f'?{k}')
    print(f"  {k} ({label}): {before[k]}")

updated = 0
for uid_str, rec in results.items():
    u = int(uid_str); h = f'{u & 0xFFFFFFFFFFFFFFFF:016x}'
    pb = rec.get('protoBytes')
    if not pb: continue
    bs = bytes.fromhex(pb)
    if len(bs) < 428: continue
    size = struct.unpack_from('<i', bs, 424)[0]
    height = struct.unpack_from('<f', bs, 104)[0] if len(bs) >= 108 else 0.0
    weight = struct.unpack_from('<f', bs, 108)[0] if len(bs) >= 112 else 0.0
    c.execute("UPDATE pokemon SET pokemon_size_category=?, weight_kg=?, height_m=? WHERE uid_hex=?",
              (size, weight, height, h))
    updated += c.rowcount

conn.commit()
print(f"\nUpdated {updated} rows")

after = {row[0]: row[1] for row in c.execute("SELECT pokemon_size_category, COUNT(*) FROM pokemon WHERE in_bag=1 GROUP BY pokemon_size_category")}
print("\nAfter (in_bag):")
for k in sorted(after, key=lambda x: x or -1):
    label = {1:'XXS',2:'XS',3:'NORMAL',4:'L',5:'JUMBO'}.get(k, f'?{k}')
    delta = after.get(k,0) - before.get(k,0)
    sign = '+' if delta >= 0 else ''
    print(f"  {k} ({label}): {after[k]}  ({sign}{delta})")

# Diff against server JUMBO tag
print("\n=== Server JUMBO vs DB size_category=5 ===")
auth_jumbo = {row[0] for row in c.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND auth_tag_names LIKE '%JUMBO%'")}
db_jumbo = {row[0] for row in c.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5")}
print(f"Server JUMBO (auth_tag_names): {len(auth_jumbo)}")
print(f"DB size=5 in bag:              {len(db_jumbo)}")
both = auth_jumbo & db_jumbo
only_srv = auth_jumbo - db_jumbo
only_db = db_jumbo - auth_jumbo
print(f"  both:           {len(both)}")
print(f"  only server:    {len(only_srv)}")
print(f"  only DB (new):  {len(only_db)}  -- candidates to add to server JUMBO tag")
if only_db:
    print("\n  Sample DB-only JUMBOs:")
    for uh in list(only_db)[:10]:
        r = c.execute("SELECT species_name, iv_total, weight_kg, height_m FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
        print(f"    {uh}  {r[0]:12s}  iv={r[1]:>2}  w={r[2]:.2f}kg  h={r[3]:.2f}m")
conn.close()
