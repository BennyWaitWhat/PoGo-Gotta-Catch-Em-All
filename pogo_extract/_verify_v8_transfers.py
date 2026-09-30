import json
import sqlite3
import sys
import os

base = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract"
inv_path = os.path.join(base, "full_inventory_v3.json")
db_path = os.path.join(base, "pokemon.db")

# 1. Load inventory
with open(inv_path, "r", encoding="utf-8") as f:
    data = json.load(f)

results = data.get("results")
if results is None:
    print("ERROR: no 'results' key. Top-level keys:", list(data.keys()))
    sys.exit(1)

live_uids = set()
sample_keys = []
for i, uid_str in enumerate(results.keys()):
    u = int(uid_str)
    hx = f"{u & 0xFFFFFFFFFFFFFFFF:016x}"
    live_uids.add(hx)
    if i < 5:
        sample_keys.append((uid_str, hx))

print(f"Inventory entries: {len(results)}")
print(f"Unique live UIDs (hex): {len(live_uids)}")
print("Sample conversions (signed_int -> hex):")
for s, h in sample_keys:
    print(f"  {s} -> {h}")

# 2. Inspect schema
con = sqlite3.connect(db_path)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("\nDB tables:", tables)
cur.execute("PRAGMA table_info(pokemon)")
cols = cur.fetchall()
print("pokemon columns:")
for c in cols:
    print(f"  {c[1]:<30} {c[2]}")

# 3. Query V8 transfers
cur.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND cull_decision_v8='TRANSFER'")
v8_rows = [r[0] for r in cur.fetchall()]
print(f"\nV8 transfers (in_bag=1): {len(v8_rows)}")

# Normalize uid_hex
def norm(u):
    if u is None:
        return None
    return u.lower().lstrip("0x").zfill(16)

v8_set = set(norm(u) for u in v8_rows if u is not None)
print(f"Unique V8 transfer uid_hex (normalized): {len(v8_set)}")

# Sample
print("Sample V8 uid_hex rows:")
for u in v8_rows[:5]:
    print(f"  raw={u!r}  norm={norm(u)!r}")

# 4. Compare
found = v8_set & live_uids
missing = v8_set - live_uids

print(f"\n=== RESULTS ===")
print(f"Total V8 transfers (in_bag=1): {len(v8_set)}")
print(f"Found in live bag:             {len(found)}")
print(f"Missing from live bag (ghosts):{len(missing)}")

if missing:
    print("\nMISSING UIDS:")
    for u in sorted(missing):
        # Get details for each missing
        cur.execute("SELECT uid_hex, species_id, form_id, nickname, cp, in_bag, cull_decision_v8 FROM pokemon WHERE LOWER(uid_hex)=?", (u,))
        rows = cur.fetchall()
        for r in rows:
            print(f"  {u} | sp={r[1]} form={r[2]} nick={r[3]!r} cp={r[4]} in_bag={r[5]} v8={r[6]}")
else:
    print("\nNo ghost transfers. Cull plan is consistent with live bag.")

con.close()
