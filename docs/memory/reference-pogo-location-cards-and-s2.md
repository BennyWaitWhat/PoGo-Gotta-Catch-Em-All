---
name: reference-pogo-location-cards-and-s2
description: "PoGo location cards (capped top-3 per species/form/card since 2026-09-24; 6 -> 5 -> 3) + how to decode captured_s2_cell to lat/lon (s2sphere, validated) + why recent catches have no place (the walk has captured no S2/coords since ~June 2026)."
metadata:
  node_type: memory
  type: reference
  originSessionId: d44dc321-2608-42e7-870c-24289b882f3e
  modified: 2026-09-24T05:11:37.824Z
---

**Location cards are CAPPED top-3 per (species, form, card id) since 2026-09-24 (6 -> 5 on 09-23 -> 3) -- `caps.location_card`; an unknown card id is kept uncapped.**
Distinct events each get their own 6 slots, so only a 7th identical card on the same species/form is fodder (user 2026-06-05: "theres different location cards you know"). `fresh_has_location_card=1`; the `loc_LocationCard` enum is an EVENT/PLACE code, decoded by the catch coords + date.

**Decode `captured_s2_cell` -> lat/lon with s2sphere (NOT a handroll).**
`captured_s2_cell` is the LEAF (level-30) S2 cell of the catch, stored as a SIGNED int64. Decode:
```python
import s2sphere
cid = s2 if s2 >= 0 else s2 + (1<<64)         # S2 ids are uint64
ll = s2sphere.CellId(cid).to_lat_lng(); lat, lon = ll.lat().degrees, ll.lng().degrees
```
VALIDATED to 0.00000deg vs rows that DID parse lat/lon. A from-scratch S2 decoder I wrote was badly wrong (85-120deg error) -- ALWAYS validate a decoder against known-good rows before trusting it, and prefer s2sphere (`pip install s2sphere`). `captured_cell_hex` (e.g. `3be7...`) is a DIFFERENT field/value from `captured_s2_cell`.

**Recent catches have no place.**
Since about June 2026 the canonical walk (`pogo_pipeline`) captures no S2 cell and no coordinates for new catches: 2,513 in-bag rows have neither (2026-09-20), including 100% of Jul-Sep catches. `normalize_forms.backfill_latlon_from_s2` (wired into `apply_to_db`) only rescues rows that still carry S2, and none are left. Recent catches get a place only if `pogo_pipeline` parses `PokemonProto.capturedS2CellId_` (Int64 @0x88). Until then `trophy_pick` treats every recent catch as an unknown place.

See also [[pogo-il2cpp-internals]] [[project-pogo-extract]] [[pogo-tag-system-2026]] [[reference-dumpsys-location-et-field]].
