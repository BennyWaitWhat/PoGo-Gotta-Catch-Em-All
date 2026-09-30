---
name: reference-pokegenie-art-internals
description: "How PokeGenie stores images on disk, and the PokeMiners listing trap that silently truncates the asset mirror"
metadata: 
  node_type: memory
  type: reference
  originSessionId: ccbe147c-00c0-4f7b-aa2a-666364d34ed9
  modified: 2026-09-03T04:31:35.293Z
---

PokeGenie (`com.cjin.pokegenie.standard`) image storage, confirmed by parsing its DEX string tables
(`classes2.dex` holds `i_%s.jpg` + `imageDir`; `classes3.dex`'s `/Backup/scan_thumb/%s.jpg` is BACKUP-only):

- **Runtime images all live in `app_imageDir/`**, never `files/scan_thumb/`. Writing thumbs to
  `files/scan_thumb/<imageId>.jpg` renders grey placeholders — that dir is only the backup layout.
  - collection thumb: `app_imageDir/i_<imageId>.jpg`
  - Pokedex/raid tile: `app_imageDir/pokedex_<dex>[_<Form>]` AND `app_imageDir/i_df_<dex>[_<Form>].jpg`
    (same PNG bytes under both names; extension is `.jpg` but content is PNG)
- **PokeGenie's Pokedex art is built from the user's OWN capture-screen scans.** That is why the
  "Current Raid Bosses" row showed a cropped old screenshot for a species they had scanned and a `?`
  for everything else. Replacing those files is how you nuke the old photos.
- Per-scan record is `files/ScanHistory/<id>` and the **detail view reads it, not `tempScanDataPath`**.
  Patch scan_data.json alone and the list updates while the detail page still says
  "The Mega-Evolved form of this Pokemon has not been scanned." Patch BOTH.
- Mega art is separate per-scan fields `megaImageId1` / `megaImageId2` (+ `selectedMegaEvol`,
  `megaSwitched`). Charizard/Raichu/Mewtwo are X/Y (slot1=X, slot2=Y); every other mega is slot 1.
- After writing: `chown -R u0_a296:u0_a296` and `chcon -R u:object_r:app_data_file:s0:c40,c257,c512,c768`
  (match `files/`), and force-stop PokeGenie before swapping `tempScanDataPath`.

**The trap that cost hours (2026-09-03):** a cached `upstream_files.json` from the PokeMiners mirror held
5,733 files when the repo actually has **11,726** — over half missing. It made Mega Starmie/Skarmory and
11 other mega species look nonexistent and matched zero costumes. Always list via the git trees API
`https://api.github.com/repos/PokeMiners/pogo_assets/git/trees/master?recursive=1` and **abort if the
response has `truncated: true`**. See [[feedback-always-recheck-upstream]].

Upstream naming: `pm<dex>[.f<FORM>][.c<COSTUME>][.g<GENDER>][.s].icon.png` (`.s`=shiny, `.g2`=female).
Form tokens are inconsistent about repeating the species — `pm19.fALOLA` but `pm201.fUNOWN_A` and
`pm412.fBURMY_PLANT` — so match the enum name BOTH as-is and species-stripped, or 114 pokemon lose art.
Mega Latias and Mega Latios are both purple and near-identical at thumbnail size; the tell is eye colour
(Latias yellow/amber, Latios red). That is correct art, not a mix-up.

Builder: `pokegenie_work/build_art.py` (replaces fetch_sprites2 + wire_sprites + add_mega_images +
rebuild_pokedex_art). Image ids are `sha1('pgimg:'+uid)` / `sha1('pgmega:<TOK>:'+uid)` so re-runs
overwrite in place instead of orphaning thousands of files. Pokedex art is written for OWNED species
only — the user does not want art for pokemon they have not caught. See [[project-pokegenie-backup]].
