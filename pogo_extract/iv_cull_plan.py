"""Transfer plan for the 1-24% IV band, decided by the EXISTING cull engine.

Does not invent keep-axes: every candidate is run through cull_v9.is_protected(), the same
function the triggered audits use (lucky/traded/costume/dynamax/location-card/mega/GL-UL-LL
PvP rank/legendary/mythical/ultra-beast/paradox/adventure-effect/shiny caps...).
IV band is applied as an ADDITIONAL filter on top. Read-only: releases nothing.
"""
import sqlite3, json, sys
import cull_v9 as C

LO, HI = 1, 24   # IV percent. 0% (nundo) deliberately excluded -> kept.

conn = sqlite3.connect('pokemon.db'); conn.row_factory = sqlite3.Row
cur = conn.cursor()
rows, ctx = C._load_rows_and_ctx(cur)
print(f"engine loaded: {len(rows)} in-bag Pokemon, {len(C.PROTECTION_RULES)} protection rules\n")

band, prot, free = [], {}, []
for p in rows:
    pct = p['iv_pct']
    if pct is None or not (LO <= pct <= HI):
        continue
    band.append(p)
    reasons = C.is_protected(p, ctx)
    if reasons:
        for r in reasons:
            key = str(r).split(':')[0][:28]
            prot[key] = prot.get(key, 0) + 1
    else:
        free.append(p)

print(f"IV {LO}-{HI}%  candidates: {len(band)}")
print(f"  protected by engine:   {len(band) - len(free)}")
print(f"  >>> TRANSFERABLE:      {len(free)}\n")
print("protection reasons hit:")
for k, v in sorted(prot.items(), key=lambda kv: -kv[1])[:18]:
    print(f"   {k:30s} {v}")
if free:
    print("\nwould transfer:")
    for p in free[:25]:
        print(f"   {p['species_name']:20s} iv={p['iv_pct']}% cp={p['cp']} uid={p['uid_hex']}")
    with open('iv_transfer_plan.csv', 'w', encoding='utf-8') as f:
        f.write("uid_hex,species,iv_pct,cp\n")
        for p in free:
            f.write(f"{p['uid_hex']},{p['species_name']},{p['iv_pct']},{p['cp']}\n")
    print(f"\nwrote iv_transfer_plan.csv ({len(free)} rows) — nothing released")
