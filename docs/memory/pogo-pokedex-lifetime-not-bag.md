---
name: pogo-pokedex-lifetime-not-bag
description: "Pokedex achievement flags (caught/shiny/hundo ever) are lifetime, per-species, per-stage — read PokedexImpl, never infer from the bag DB."
metadata: 
  node_type: memory
  type: project
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
  modified: 2026-09-21T03:32:00.617Z
---

Pokédex achievement status (caught flag, shiny-ever, hundo-ever, etc.) is a **lifetime, per-species flag** PoGo tracks independently of the current bag. Querying `pokemon WHERE iv_total=45 AND in_bag=1` only shows hundos STILL in the bag — a user who caught a hundo once and then transferred/evolved it still has the dex hundo achievement forever. Each evolution stage tracks independently: a hundo Charizard does NOT credit Charmander/Charmeleon dex hundos (I once fabricated the opposite — see [[feedback-verify-before-irreversible]]).

The authoritative data is the **`Niantic.Holoholo.Internal.PokedexImpl`** singleton (read it via Frida; the pipeline's `step_read_dex` does this). Layout (verified):
- 10 dictionaries at offsets +0x10..+0x58, each `Dictionary<int, PokedexEntryProto>` — per-generation regional dexes, NOT category-keyed; in offset order: All, Kanto, Johto, Hoenn, Sinnoh, Unova, Kalos, Alola, Galar, Paldea. The field names are obfuscated and rotate per release (`cugr`–`cuha` on the 2026-05-10 build): navigate by offset, never by name.
- `PokedexEntryProto`: `timesCaptured` at +0x18 (>0 = caught), `CapturedForms` `RepeatedField<Form>` at +0x50, and a per-category `MapField<String, PokedexCategoryStatus>` at +0x80.
- `PokedexCategoryStatus`: +0x10 category enum, +0x14 Encountered (bool), +0x15 Acquired (bool), +0x18 LastCaptureTimestampMs.
- Category enum values are NON-sequential — empirical: 11=Shiny, 12=Lucky, 13=ThreeStar, **14=FourStar (HUNDO)**, 15=Shadow, 16=Purified, 17=Costume, 18=BreadMode, 19=BreadDoughMode, 101=ShinyThreeStar, 102=ShinyFourStar, 201=SizeXxs, 202=SizeXxl.

**Why:** The bag DB tracks current possession; the Pokédex tracks lifetime acquisition. They are different data and routinely disagree.

**How to apply:** For ANY question about dex achievement status, read `PokedexImpl` directly — never infer from the bag. This is also why the cull's evolution-dex-gap rule must read live `PokedexImpl` (timesCaptured>0 / captured forms), not bag IVs (see [[pogo-data-completeness-before-destructive-actions]]). For PoGo enums generally, read static field VALUES (`il2cpp_field_static_get_value`) — never trust the declaration order from `il2cpp_class_get_fields` (see [[pogo-il2cpp-internals]]). Relates to [[pogo-source-of-truth-db-rules]], [[project-pogo-extract]].
