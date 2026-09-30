#!/usr/bin/env python3
"""Compute the protected uid_hex set for keep-rule 'variant_floor'.

RULE (finalized PoGo keep policy, KEEP_POLICY.md sec 1):
  Trade-stock floor. Keep top 3 by iv_total (tiebreak cp desc) per
  VARIANT = (pokemon_id, form, fresh_costume).
  EXCEPTION: if a variant has any mon with fresh_bread_mode=2 (gmax),
             keep top 4 for that whole variant.
  EXCLUDE shadows (fresh_alignment=1) and shinies (fresh_shiny=1) entirely.
  Purified (fresh_alignment=2) is treated as normal and IS in the pool.
  Scope: in_bag=1.
"""
import sqlite3, os
from collections import defaultdict

DB = os.path.join(os.path.dirname(__file__), "..", "..", "pokemon.db")
OUT_DIR = os.path.join(os.path.dirname(__file__), "policy_sets")
OUT = os.path.join(OUT_DIR, "variant_floor.txt")
os.makedirs(OUT_DIR, exist_ok=True)

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
c = db.cursor()

# Pool: in_bag, exclude shadows and shinies. Purified stays.
rows = c.execute("""
    SELECT uid_hex, pokemon_id, species_name, form, fresh_costume,
           fresh_alignment, fresh_shiny, fresh_bread_mode,
           iv_total, cp, level
    FROM pokemon
    WHERE in_bag = 1
      AND fresh_alignment != 1   -- exclude shadows
      AND fresh_shiny     != 1   -- exclude shinies
""").fetchall()

# Group by variant = (pokemon_id, form, fresh_costume)
variants = defaultdict(list)
for r in rows:
    key = (r["pokemon_id"], r["form"], r["fresh_costume"])
    variants[key].append(r)

protected = []        # list of (uid_hex)
sample_rows = []      # for reporting deciding stat
gmax_variant_count = 0

for key, mons in variants.items():
    # sort: iv_total desc, then cp desc (tiebreak). Stable; add level as final
    # deterministic tiebreak so the cut is reproducible.
    mons_sorted = sorted(
        mons,
        key=lambda r: (
            -(r["iv_total"] if r["iv_total"] is not None else -1),
            -(r["cp"] if r["cp"] is not None else -1),
            -(r["level"] if r["level"] is not None else -1),
            r["uid_hex"],  # final deterministic tiebreak
        ),
    )
    # gmax exception: any mon in the variant with fresh_bread_mode == 2 -> cap 4
    is_gmax_variant = any(m["fresh_bread_mode"] == 2 for m in mons_sorted)
    cap = 4 if is_gmax_variant else 3
    if is_gmax_variant:
        gmax_variant_count += 1
    keep = mons_sorted[:cap]
    for m in keep:
        protected.append(m["uid_hex"])
        sample_rows.append(m)

# de-dup safety (shouldn't be needed; uid_hex unique) + stable sort for output
protected_set = sorted(set(protected))
assert len(protected_set) == len(protected), "duplicate uid_hex encountered"

with open(OUT, "w", encoding="utf-8") as f:
    for u in protected_set:
        f.write(u + "\n")

# ---- reporting ----
print("RULE: variant_floor")
print("pool size (in_bag, non-shadow, non-shiny):", len(rows))
print("distinct variants:", len(variants))
print("gmax variants (cap=4):", gmax_variant_count)
print("PROTECTED COUNT:", len(protected_set))
print("written to:", os.path.abspath(OUT))
print()

# how many variants actually hit/exceeded their cap (i.e. floor binds)
binding = sum(1 for k, m in variants.items()
              if len(m) > (4 if any(x["fresh_bread_mode"] == 2 for x in m) else 3))
print("variants with MORE mons than cap (floor trims dupes):", binding)
print("variants fully kept (<= cap):", len(variants) - binding)
print()

# sample: 6 items, species + deciding stat
print("SAMPLE (uid_hex | species | form | costume | iv_total | cp | bread):")
for m in sample_rows[:6]:
    print(f"  {m['uid_hex']} | {m['species_name']} | form={m['form']} | "
          f"costume={m['fresh_costume']} | iv={m['iv_total']} | cp={m['cp']} | "
          f"bread={m['fresh_bread_mode']}")

# show a gmax variant if any, to confirm cap=4 path exercised
print()
print("Example gmax (bread=2) variant detail:")
shown = False
for key, mons in variants.items():
    if any(m["fresh_bread_mode"] == 2 for m in mons) and len(mons) >= 1:
        ms = sorted(mons, key=lambda r: (-(r["iv_total"] or -1), -(r["cp"] or -1)))
        sp = ms[0]["species_name"]
        print(f"  variant {key} ({sp}): {len(mons)} mons, cap=4, "
              f"kept={min(4,len(mons))}")
        for m in ms[:5]:
            print(f"    iv={m['iv_total']} cp={m['cp']} bread={m['fresh_bread_mode']}")
        shown = True
        break
if not shown:
    print("  (none)")
