# pokegenie_work

Tooling that rebuilds Benny's **PokeGenie** app data from `pokemon.db`, so PokeGenie shows the real bag without rescanning.
Only the scripts are in git; the PokeGenie data they work on (~590 MB of backups, sprites and extracted app files) is not.

| Script | What it does |
|---|---|
| `generate_pokegenie.py` | Writes a complete PokeGenie `scan_data.json` for the current bag |
| `build_art.py`, `rebuild_pokedex_art.py`, `add_images.py`, `add_mega_images.py` | Official Pokémon GO art for every entry and Pokédex tile (form-, costume-, shiny- and mega-accurate) |
| `fetch_sprites.py`, `fetch_sprites2.py`, `wire_sprites.py` | Download the official icon sprites and build thumbnails from them |
| `fill_dex_forms.py`, `fill_dex_from_account.py`, `fill_gap.py` | Complete Pokédex coverage for every (dex, form) actually owned |
| `match_old_photos.py` | Reuse real historical scan photos from an old PokeGenie backup |
| `verify*.py`, `hp_*.py`, `moveres*.py`, `_cpm_probe.py`, `_verify_pvp.py` | One-off checks from the build |

Status: these ran on the Windows PC (several hardcode `C:/Users/Blanco/...` paths and need the PokeGenie data folder).
Background: `docs/memory/project-pokegenie-backup.md` and `docs/memory/reference-pokegenie-art-internals.md`.
