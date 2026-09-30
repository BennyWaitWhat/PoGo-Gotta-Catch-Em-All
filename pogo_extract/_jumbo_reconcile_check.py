import sqlite3, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
c = sqlite3.connect('pokemon.db')

xxl = c.execute("""SELECT uid_hex, species_name, pokemon_id, form, weight_kg, height_m, cp
                   FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5""").fetchall()
by = defaultdict(list)
for r in xxl:
    by[(r[2], r[3] or 0)].append(r)
keep = set()
for k, rows in by.items():
    for r in sorted(rows, key=lambda x: x[4], reverse=True)[:2]:
        keep.add(r[0])
    for r in sorted(rows, key=lambda x: x[5], reverse=True)[:2]:
        keep.add(r[0])

db_tagged = set(r[0] for r in c.execute(
    "SELECT uid_hex FROM pokemon WHERE in_bag=1 "
    "AND (';'||COALESCE(auth_tag_names,'')||';') LIKE ?", ('%;JUMBO;%',)))

print(f"current XXL in bag      : {len(xxl)}")
print(f"correct top-2 keep set  : {len(keep)}")
print(f"DB JUMBO-tagged         : {len(db_tagged)}")

add = keep - db_tagged
remove = db_tagged - keep
print(f"\nADD (in correct set, not tagged in DB): {len(add)}")
for u in add:
    r = c.execute("SELECT species_name,cp,weight_kg,height_m FROM pokemon WHERE uid_hex=?", (u,)).fetchone()
    print(f"   {u}  {r[0]:<14} cp={r[1]} w={r[2]:.2f} h={r[3]:.2f}")
print(f"\nREMOVE (tagged in DB, not in correct set): {len(remove)}")
for u in remove:
    r = c.execute("SELECT species_name,cp,weight_kg,height_m FROM pokemon WHERE uid_hex=?", (u,)).fetchone()
    print(f"   {u}  {r[0]:<14} cp={r[1]} w={r[2]:.2f} h={r[3]:.2f}")

if not add and not remove:
    print("\nDB JUMBO membership is EXACTLY the correct top-2 set. Only the server has +1 stray to clear.")
c.close()
