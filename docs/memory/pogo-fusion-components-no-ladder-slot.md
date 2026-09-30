---
name: pogo-fusion-components-no-ladder-slot
description: A Reshiram/Zekrom fused into a White/Black Kyurem (isComponent_ @PokemonProto+0x1b9) holds NO ladder slot and is kept as 'fused' (user 2026-09-26); read live every walk.
metadata:
  type: project
---

User 2026-09-26, after asking why a 73% Fusion Flare Reshiram was in the pile: "i think 2 are currently fused. So don't
count those in the ladder." He was right -- 2 Reshiram (93%, 91%) and 3 Zekrom are components; they held Best ML,
Variant #1 and legacy top-6 slots and pushed the visible 73% copy out.

- Flags: `isComponent_` @0x1b9 (the held Reshiram/Zekrom), `isFusion_` @0x1ba (the White/Black Kyurem), both
  System.Boolean in proto_layout.json, inside the 0x200 protoBytes. Before this, only the one-off
  `_enrich_proto_fields.py` wrote them (2,846 NULL rows); `pogo_pipeline.parse_pokemon` now SETs them every walk.
  Components have been fused since at least 2026-05-30 (every DB snapshot agrees).
- ONE helper: `keep_config.is_fused_component(r)`. keep_policy drops components from `rows` before every competition
  and marks them 'fused' (registered in audit_invariants AXES/MARK_MODEL, granular_tags NATIVE_COVERED_REASONS);
  `is_component` joined `_PROT_COLS` (NULL = data_incomplete). Audit mirrors skip them in their ladder pools but still see
  them in whole-bag checks. LAW.md row 0.
- The Kyurem fusion itself is a visible mon and competes in its own form (147 Black / 148 White).
- Tag writes on components WORK: tags on them were added (Variant #N, Best ML) and removed (Event) across months.
- Remote Trade: the game already refuses components (sync_remote_trade frozen set) -- see [[pogo-capped-vs-keepall-bug-class]].
