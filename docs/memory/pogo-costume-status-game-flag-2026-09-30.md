---
name: pogo-costume-status-game-flag-2026-09-30
description: A form-encoded costume is a costume when its enum NAME says so OR the client game master flags isCostume -- add-only (Benny 2026-09-30, "do whats best and not lazy" = option 5). FLYING skips Arceus/Silvally type forms, TSHIRT covers Pikachu T-shirt 04-07; the flags survive a missing game master through costume_gm_flags.json; the pile's engine stamp now covers costume_forms.py + form_enum.json + gamemaster_pokeminers.json.
metadata:
  type: project
---

Why: a costume released by mistake is gone, a plain kept by mistake costs one slot ("unknown = protected"). The name rule alone (an event
year or a keyword in the live enum name) missed forms the game itself flags (Armored Mewtwo, Gimmighoul Coin A1) and read Arceus /
Silvally "Flying" TYPE forms as balloon costumes. The game's flag alone would be worse: Niantic leaves `isCostume` unset on event skins
it calls costumes (PsyduckSwim2025, the four Copy2019 clones) and the game master lags the enum (1,449 forms listed, 1,506 enum codes:
the Goggles2026 Charmander line, 19 copies in the bag; Pikachu T-shirt 04-07). So: union, and the game can only ADD. Shown five ways to
decide it (game's flag both ways / add-only + Flying fix / Flying fix only / nothing / add-only + TSHIRT), Benny: "do whats best and not
lazy" -> the recommendation, option 5. LAW.md was edited first: "WHAT COUNTS AS A COSTUME".

## What ships (2026-09-30)
- `pogo_extract/costume_forms.py`: `_costume_set(enum, flags)` = name rule OR flag; `classify()` skips FLYING for names starting ARCEUS /
  SILVALLY (`_TYPE_FORM_SPECIES`) and has a `TSHIRT` keyword; `gm_costume_flags()` = a ladder -- (1) the game master file (parsed once,
  cached in `system/analysis/costume_gm_flags.json` keyed by its mtime), (2) file missing / unreadable / lists no forms -> the LAST cached
  flags, whatever game master they came from, (3) only with neither, the name rule alone. `GM_SOURCE` (`game_master` / `stale_cache` /
  `none`), `GM_NOTE`, `gm_layer_stamp()`; import never raises (~4 ms warm, ~0.2 s cold). `python costume_forms.py --selftest` = golden
  names + every rung on synthetic game masters (CI-safe; ci.yml is NOT wired to it).
- `audit_gamemaster.py` check 6, from the RAW game master (not costume_forms' cache): BLOCK when a form the game flags is not a costume
  here; WARN when the flags came from the stale cache or did not load; one INFO line counts the costumes only the name rule catches
  (36 today: 31 the game does not list yet, 5 it lists unflagged). Mutation-proven: drop the union, a lying cache, or no source -> BLOCK.
- Engine stamp: `keep_policy._engine_sha` and `audit_cull.py`'s mirror hash 12 files now (+ `costume_forms.py`, `form_enum.json`,
  `gamemaster_pokeminers.json`). Before this a classifier / enum / game-master change left an old pile looking fresh to `--audits-only`.
  Each of the three flips the real gate's 8-layer cull to "stale pile"; an unstamped file does not.
- `keep_policy`: prints `[WARN] costume game-master layer is ...` when degraded (full_audit echoes the [WARN] lines of the recrawl job's log,
  keep_policy being its recompute step; the audit's own WARN stays in the audit's log on a passing cull), `pile_provenance.json`
  form_enum.gm_layer records the rung, and the stale "NOT-DONE" comment on the base-form vote is fixed (the exclusion has been applied
  since 2026-09-23). `deep_audit.py` has the Flying type-form guard (ArceusFlying / SilvallyFlying are not "missed costumes").

## Numbers (whole bag 2026-09-30: 5,733 mons, baseline re-derive = the live pile exactly)
- Pile 30 -> 30 (same uids), 0 tag-file changes, 0 label changes. Only reason change: 3 Gimmighoul (IV 44 / 40 / 39, form 3018) lose
  `location_card` (a costume copy holds no card slot) and stay kept (protected, variant_floor, pvp_best_ml). `location_card` 240 -> 237.
- COSTUME_FORMS 124 -> 133: +Armored Mewtwo (29 copies), +Gimmighoul Coin A1 (4), +Pikachu Kariyushi / Doctor / T-shirt 01-07 (0 held),
  -ArceusFlying, -SilvallyFlying (0 held). Bag Pulse costume count 400 -> 433. fodder_oracle seed_bar mewtwo_armored 43 -> 42 (a stage bar;
  lower = fewer copies provably fodder). Base-form vote: Mewtwo and Gimmighoul each gain a base_form (135 / 2998); no form-0 copy to fold.
- Split of the 133: 93 both rules, 4 game only, 36 name only. The proofs ran the real audit code: costume_forms swapped in memory for
  a broken copy (mutation); each stamped file perturbed by one byte, then restored byte- and mtime-exact (stale stamp).

## How to apply
- "Is this form a costume?" = `costume_forms.is_costume_form(code)` / `COSTUME_FORMS`, never `classify(name) == 'costume'` alone (`classify`
  stays the NAME rule: normalize_forms asks only for 'base'; pogo_display uses it for the chip, so Armored Mewtwo reads "Mewtwo (A)").
- After a game-master refresh, a new enum dump or any edit of those three files the pile reads "stale pile" in `--audits-only` and in a
  `--skip-crawl` cull until keep_policy + build_tagsets run again; the cull's recrawl step does it before its audits. Today's stamp went
  stale once on purpose.
- gm_guard (the game-master diff guard, another branch) must treat a flip of a form's `isCostume` as keep-relevant.
- A new costume neither rule knows is still held by the unknown-form guard (`is_unknown_form`) until the enum is re-dumped.

## Gotchas
- `costume_gm_flags.json` rides the `inventory` data group (`system/analysis/*.json`), not git; a fresh VM rebuilds it in ~0.2 s.
- The two engine lists are a hand-synced pair (keep_policy / audit_cull): edit both, same order. `preflight_transfer._gate_sha256` is a
  third, different list (reuse of a <= 120 s stamp): it has costume_forms.py but not form_enum.json or the game master.
- `classify_all_forms.py` (the phone-side enum dumper) keeps its own older first-pass hint list; report only, not the keep path.
- keep_policy.py, audit_cull.py, costume_forms.py, LAW.md are CRLF (byte-exact repo): edit them byte-exact.

Related: [[pogo-special-backgrounds-capped]] (a costume copy rides its costume's ladder, backgrounds first), [[pogo-capped-vs-keepall-bug-class]],
[[pogo-pile-gate-2026-09]], [[project-gamemaster-monthly-refresh]], [[pogo-one-speciesid-many-plain-forms]].
