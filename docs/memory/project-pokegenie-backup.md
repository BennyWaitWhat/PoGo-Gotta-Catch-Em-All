---
name: project-pokegenie-backup
description: PokeGenie collection is regenerable from pokemon.db via a generator script; how to refresh it after catching new mons.
metadata: 
  node_type: memory
  type: project
  originSessionId: cbf03dd1-a60e-4ad1-a959-393c99d1df55
---

PokeGenie (`com.cjin.pokegenie.standard`) has no in-app import UI, but its scan store is **plain JSON, NOT locked Java objects** (earlier belief was wrong — that was a bad `run-as`/non-su read). With Magisk root (`su`, context `u:r:magisk:s0`, SELinux can stay Enforcing — no setenforce needed) you can read AND write `/data/data/com.cjin.pokegenie.standard/files/`:
- `ScanHistory/<id>` — one JSON file per scan (keys alphabetical, ivPercentage as float32) = the live store; file count == numScans.
- `tempScanDataPath` — the full JSON array, byte-identical to the Dropbox `scan_data.json` (verified md5 match after a restore).
- `scanMetadataPath` = metadata.json; `tempNameGenPath` = name_generator_settings.json.
So **direct import is feasible**: force-stop the app, write the `ScanHistory/<id>` files + `tempScanDataPath` + `scanMetadataPath`, `chown u0_a296:u0_a296` + `chcon u:object_r:app_data_file:s0:c40,c257,c512,c768`, restart — OR just let the Dropbox restore re-serialize (what happened 2026-06-04). Either way the same generator below produces the content. The **Dropbox backup** (`scan_data.json`+`metadata.json`+`Pokedex/`) remains the no-root path. The format was reverse-engineered (10-agent workflow `wf_024767ce`) and a generator built:

`pokegenie_work\generate_pokegenie.py` maps every `in_bag=1` row of [[project-pogo-extract]]'s pokemon.db → one scan entry (exact single IV comb) → `pokegenie_out\{scan_data.json,metadata.json}`. Last run 2026-09-03: 5618 mons (applied; phone ScanHistory = 5618).

Key reverse-engineered rules (all verified vs 6568 ground-truth entries):
- **`imageId`** is set (2026-09-02) from `pokegenie_out\image_map.json`, written by `pokegenie_work\build_art.py` (2026-09-03: official PoGo art from the PokeMiners mirror). Its map replaced the add_images.py / wire_sprites.py ones; never rerun add_images.py (its first layer is the old capture-screen scan photos), and generate_pokegenie.py's comment naming it is stale. A uid with no art gets no imageId and falls back to PokeGenie's default art. See [[reference-pokegenie-art-internals]].
- `ivPercentage`=`ivLower`=`ivUpper`=(a+d+s)/45; avg=min=max IV = the DB IVs; `singleIVComb`=true.
- `minBattleIV`=`maxBattleIV`=atk+def; `setPokemonLevel`=round((level−1)*2); `dust`=standard PoGo table; `id`=contiguous "0".."N−1".
- Moves: DB move1/2/3 (numeric) → `move_id_to_name.json` (SCREAMING_SNAKE) → pvpoke gamemaster `name` (Title Case), strip `_FAST`.
- `form`: emit regional only (alolan/galarian/hisuian/paldean → Alola/Galarian/Hisuian/Paldean), else omit (non-fatal).
- `maxCP`/`maxHP` = max(L50 CP/HP from gamemaster base stats with this mon's IVs, current cp/hp) — the max() guards ~90 special-form base-stat mis-resolves (e.g. armored Mewtwo) so maxCP is never < cp.
- **PvP blocks omitted** (optional; PokeGenie recomputes from IVs). If they ever need injecting: `rankAvg`=1−(rank−1)/4095 from gl_rank/ul_rank; `prod`=round(pct*100) from gl_pct/ul_pct; league GL=0/UL=1/LL=2; pokeNum=dex of gl_stage/ul_stage.

**To refresh after catching new mons:** rerun the bag extraction so pokemon.db is current, `python generate_pokegenie.py`, then the user replaces `scan_data.json`+`metadata.json` in their Dropbox PokeGenie folder (leave `Pokedex/`) and does Restore from Dropbox. Original safety-net backup: `pokegenie_work\old_backup\` (unzipped original, 6568 scans, 358 MB).
