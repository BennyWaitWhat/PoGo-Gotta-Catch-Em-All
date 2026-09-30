---
name: pogo-granular-tags-2026-09
description: "Granular keep-reason tags (2026-09-02): every kept mon carries >=1 tag naming WHY (ordinals like Variant #1, GL Rank 1) or is explained by a native filter chip. Gotchas: PokemonTagColor is 0-8, filenames may only swap spaces, _RANK must equal keep_policy.topn. The tag list itself: granular_tags.registry() (see pogo-tag-vocabulary-2026-09-09)."
metadata: 
  node_type: memory
  type: project
  originSessionId: 13477788-96d8-4172-8c7d-deee9a225a6b
  modified: 2026-09-21T03:30:59.762Z
---

Tag list: [[pogo-tag-vocabulary-2026-09-09]]. Live = `granular_tags.registry()` (31 managed as of 2026-09-20,
including Evolve Shiny) and `granular_tags.RETIRED_TAGS` (23); `system/tags/registry.json` is a 2026-09-09
snapshot (30/22).

**WHY.** User 2026-09-02: *"i think i want every pokemon to be tagged for the reasons theyre staying"* and
*"im sure you can label 1st 2nd 3rd, best ul, best gl, actually ranked ul and gl, etc. cmon"* and
*"keep spreading if needed. every reason."* Before this, **56.9% of the bag carried no tag at all** — the
old 12 tags covered only 9 of the 20 keep reasons, so 1,325 mons held solely by shininess and 1,507 held
solely by variant_floor were invisible in-game. Every kept mon now carries >=1 of our tags OR is fully explained by
a native filter chip (`granular_tags.NATIVE_COVERED_REASONS`); `build_tagsets` raises otherwise.

**`granular_tags.py`** is the single owner of the scheme. `build(rows, pile, reasons)` derives tags
straight from `policy_reasons.json` — the engine's own per-mon reason map — so a tag can never disagree
with the decision that produced it. It re-reads `SELECT *` if the caller narrowed the projection.

Ordinals come from `_RANK = (-IV, -CP, uid_hex)`, which **must stay identical to `keep_policy.topn`** or
the tag ordinal will disagree with the cull decision. Renames toward the user's own vocabulary, not my jargon (his note:
*"you should probably use the terms you use rather than some jargon things you made earlier"*):
`dex_only_copy` -> **Last Copy**, `protected` -> **Never Cull**, `rank_unknown` -> **Safety Hold**.

**GOTCHA 1 — `PokemonTagColor` is 0-8, NOT 0-9.** `AddTag` with colour 9 returns **ok=True** and the tag
silently never materialises. This cost most of a session; I fabricated four different causes for it (a
14-tag account cap, a name filter, a creation rate limit, a length limit) before finding the real one.
`tag_ops.py` now raises `ValueError` on an out-of-range colour. The account supports ~100 tags, not 14.

**GOTCHA 2 — the filename rule is spaces-only.** `granular_tags.filename(tag)` is
`tag.replace(' ', '_') + '.txt'` and nothing else. `#` and `+` MUST survive into the filename because
`set_db_tags_from_files` derives the tag name back FROM the filename; sanitising `#`->`n` and `+`->`plus`
made the DB hold "Variant n4plus" while the phone held "Variant #4+" — permanent phantom drift.
`prune_tags.PLAN` is DERIVED from `granular_tags` (plus `_LEGACY_PLAN`, so the 6 legacy tags XXL, Hundo,
Nundo, Traded by E+F, Legacy Moves and Transfer keep their historical filenames and colours), so the two can
never drift apart again.

**`full_audit.py`** is the one-command cycle: game-master freshness gate (`refresh_gamemaster`; rank<=5
crossing -> rc 5) -> fresh recrawl -> live Adventure-Effect roster gate (`derive_ae_roster`; unprotected ->
rc 6) -> the audits in parallel (`full_audit.AUDITS`, 10 on 2026-09-20) -> sync job (`preflight_transfer`
keeper gate, then tag push) -> retire stale shells (max 3) -> verify -> Remote Trade / Evolve-for-Size tags.
Flags `--audits-only`, `--no-sync`, `--skip-crawl`.

Related: [[pogo-tag-system-2026]] (displacement/collapse history), [[pogo-capped-vs-keepall-bug-class]],
[[project-keep-config-dashboard]],
[[reference-pogo-tag-inheritance]], [[feedback-transfer-preflight-every-axis]].
