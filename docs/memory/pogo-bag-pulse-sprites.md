---
name: pogo-bag-pulse-sprites
description: Bag Pulse shows the Transfer pile as sprites (exact form / costume / gender / shiny icon) plus location-card thumbnails and the game's own species and form names since 2026-09-30; bag_art.py + pogo_display.py, a committed icon index, a cache that is NOT in the data store.
metadata:
  type: project
---

Why: Benny releases the Transfer pile BY HAND in the game (the tool only tags). Seeing each pile mon's exact look next to its
name (form, costume, gender, shiny, background card) finds the right copy faster. Display only: nothing here changes what is
kept, tagged or released, and no stored identifier (pvid, tag name, `_pile_names`, `last_report.json`) is derived from it.

## What ships (2026-09-30)
- `pogo_extract/pogo_display.py` (pure, stdlib, no repo imports at import time): `IconIndex.resolve(row)` -> the pogo_assets
  icon file + which qualifiers (shiny / form / costume / gender) the mirror has no art for; `Names` (official species and form
  text, `label(row)`, `stage(pvpoke id, dex)`, `card_info(id)`); `look_chips(row)`.
- `pogo_extract/bag_art.py` (impure): PNG thumbnailer (stdlib zlib+struct: Pillow and numpy are NOT installed in the cloud VM),
  cache, fetch policy, the tile HTML/CSS/JS, `--refresh-index` / `--refresh-names` / `--selftest`. Any other flag prints usage,
  rc 2 (never run for real on a guessed flag). Env: `BAG_ART=0` = today's page byte for byte (art AND names off; verified on the
  real page), `BAG_ART_CACHE=<dir>`, `BAG_ART_OFFLINE=1`.
- Reference files (tracked, so a fresh clone and CI have them; `pogo_extract/.gitignore` section 4 allows both):
  `pogo_icon_index.txt` (3,696 icon names of 'Images/Pokemon - 256x256/Addressable Assets/' + 256 card stems, at a named upstream
  commit and list date) and `official_names_en.json` (1,008 species + 277 form strings from the game's i18n_english.json, plus a
  `quests` section of 27 evolution-quest texts that `evolvable_forms` reads: [[pogo-evolution-quest-wording]]).
- `gen_bag_pulse.py`: a new first card "In the Transfer tag now (N)" = one tile per look, one row per copy (IV %, CP, sex sign
  where `evolvable_forms.gender_key` says it is a look, chips: shiny / shadow / costume / Dynamax / Gigantamax / XXL / lucky), a
  location-card thumbnail + kind ("Special Background" vs "Location Background") + name where the mon has one; 24 px sprites in the
  pass table's "Tagged for Transfer" cells for mons still in the bag; official names everywhere Bag Pulse prints a species.
  The pile card is server-rendered and its sprites are filled by a tiny script BEFORE any Chart.js code, so a dead CDN cannot hide it.
- `cull_report.py` (phase 2, display strings only): `species_label(r)` and `stage_name(pvpoke id, dex)` -- 'Nidoran F' -> Nidoran with the
  female sign, 'Mr Mime' -> 'Mr. Mime', 'Ho Oh' -> 'Ho-Oh', 'Farfetchd Galarian' -> "Galarian Farfetch'd" (83 of the 1,742 pvpoke ids
  read differently; the rest keep the old title-cased id). The "Which way to evolve" lines come from `evolve_targets` and are untouched,
  so nothing is re-announced by the standing-lines dedupe.

## Numbers (whole bag 2026-09-30: 5,733 mons)
- 100.0% resolve to an icon of their own species (0 without); 99.0% (5,673) with the EXACT look. The 60 approximate: 39 Scatterbug /
  Spewpa patterns (no upstream art at all) + 21 female copies of dimorphic species that have no female icon for that form. Shown with a
  dashed outline and a note. 1,364 shinies all keep shiny art; 2,170 unique icon files.
- `pokegenie_work/build_art.py`'s matcher would choose another file for 26 of them and every one is a correction: Galarian Farfetch'd x6
  and Mr. Mime x2 (a punctuated species name defeats its prefix strip), Flabebe colours x15 (accent), Raichu costume `_2` x3 (enum vs
  upstream token). NOT changed here (PokeGenie output is Benny's call): adopting `pogo_display.IconIndex` there is a small edit.
- Pile of the day: 30 mons -> 16 sprites; page 62 KB -> ~240 KB (19 sprites, 124 KB raw); cold cache = 19 single-file GETs in ~2.2 s.
  Cards: 290 mons carry one (68 ids); 283 have a game-master entry and a PNG; 7 (S24 Sep 2026, Midautumn 2026) are newer than the client
  game master copy -> kind + name as text only. None is in today's pile.
- Names: of the bag's 942 (dex, name) pairs, 937 equal the game's name, 2 differ (Nidoran F / M -> Nidoran with the female / male sign) and
  3 have no i18n key (dex 1012 Poltchageist, 1013 Sinistcha, 1019 Hydrapple: they keep the DB name). 809 of the 5,733 mons read
  differently from their DB species name (regional adjective, official form text, Nidoran signs; 244 distinct spellings); 400 wear a
  costume chip (208 `fresh_costume` + 192 costume-class forms such as PikachuWinter2020, kept out of the name), and all 208 costumed
  mons resolve to an exact costume icon.

## Decisions and why
- Icon index COMMITTED, not listed at cull time: api.github.com answered 403 for PokeMiners from a cloud session while raw single-file
  GETs worked. This is not the stale-listing trap of [[reference-pokegenie-art-internals]]: the seed comes from a complete, non-truncated
  listing, carries commit + dates (shown in the page footnote, and flagged when older than 60 days), `--refresh-index` refuses to shrink
  (floor 3,000 icons, 90% of the committed count) and aborts on `truncated: true`, and `resolve()` can only return a file of the same dex,
  so a stale index degrades to a flagged approximate sprite, never another species. Refresh with a saved trees-API JSON / `git ls-tree`
  list (`--tree FILE`) or a local clone (`--clone DIR`; read-only git only: never checkout / pull in /home/user/pokeminers).
- Icons come from the 256x256 dir only (a strict superset of the trimmed one); cropped to the alpha box and area-downscaled to 72 px
  (5-10 KB each) so both source dirs give the same thumbnail.
- Past passes whose mons left the bag stay TEXT: 921 of the last 973 pile uids are gone from the DB, so a picture cannot help find
  them, and stamping a sprite key into `ladder_history` would touch a file other tools read.
- Cache = `pogo_extract/system/analysis/art_cache/{s72,c64}/` + `misses.json`, gitignored, NOT in the phone data store: it is derived from
  a public source (same class as `rank_tables.pkl` and `pokegenie_work/sprites`), a cold cull pays ~2-4 s, the cull must never depend on
  it, and packing it would add MBs to every pull / push over the ~1 MB/s adb link. `tools/data_manifest.txt` was checked with the real
  `[inventory]` globs on a fake tree: single-level `system/analysis/*.json` etc. do not match it. Revisit if a cold fetch ever takes
  over ~10 s or raw.githubusercontent.com is unreliable from cloud sessions: add `pogo_extract/system/analysis/art_cache/**`.
- The cull must never fail because of art: guarded import, `prepare()` never raises, 6 daemon threads, 6 s per request, ONE 25 s wall
  budget, 80 sprite + 12 card fetches per run, a circuit breaker after 3 network failures in a row, 640 KB sprite / 100 KB card budget per
  page. Negative cache: 404 = 7 days, undecodable = 1 day, oversize = 30 days; a network failure is NEVER cached. Offline or a broken
  cache dir = the text tile (letter placeholder), same numbers.
- Location card: `fresh_has_location_card == 1` and a non-zero `fresh_loc_card_enum` (the keep engine's own test) -- not `loc_LocationCard`,
  not `special_bg_id`. Enum name -> game master `locationCardSettings` (loaded lazily, 0.5 s, only when a pile mon has a card) -> `imageUrl`
  -> 'Images/LocationCards/<imageUrl>.png' (9 of 246 differ from the file name only in case).

## Gotchas
- The golden cases in `bag_art.py --selftest` flip when upstream adds art (Scatterbug patterns, Pikachu Diwali 2024 female): update
  them, the failure message says so.
- `gen_bag_pulse.py` and `cull_report.py` are CRLF files (byte-exact repo): edit them byte-exact, never with a tool that rewrites line endings.
- `full_audit.finish_step` shows only the LAST stdout line of gen_bag_pulse, so the art summary line prints before the KPI line.
- Verify locally in a worktree copy only (gen_bag_pulse overwrites `system/analysis/collection_stats.html`); Playwright + Chromium from
  `/opt/pw-browsers` with every non-file request blocked and Chart.js stubbed.
