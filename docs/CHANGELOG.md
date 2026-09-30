# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Bag Pulse redesign: a night Pokédex frame from the README banner (Poké Ball header, navy-to-plum) with Oura-style data —
  score rings, light numerals, pastel series, smooth lines with fading fills; the page now shows the real scan time.
- Bag Pulse pictures: the Transfer pile as tiles with each mon's exact icon (form, costume, gender, shiny), location-card
  thumbnails, the game's own species and form names, and small icons in the pass table. Embedded from PokeMiners/pogo_assets
  into the page (`pogo_extract/bag_art.py`, `pogo_display.py`, `pogo_icon_index.txt`, `official_names_en.json`); the cache is
  rebuildable and not in the phone data store; every failure falls back to text and `BAG_ART=0` gives the old page.
- Exact Power Up costs from the game master (`pogo_extract/game_opportunities.py`, Benny 2026-09-30: "yes"): `power_up_cost()` prices any
  level range in stardust, candy (to L39.5) and XL candy (from L40) from the client game master's `POKEMON_UPGRADE_SETTINGS` at call
  time, with the shadow / purified / lucky multipliers and the per-species override (Eternatus: 8,900 XL candy for L40 to L50). The cull
  report gets a report-only Power Up block: each mon the Power Up tags hold, its price against your stardust and its family's candy
  and XL candy, and "doable now" / "doable after exchanging N candy" (if the game allows it) / "short X". No tag, keep reason or pile
  decision reads it: on the 2026-09-30 01:43 bag the pile, the keep reasons and all 33 tag files come out byte-identical to before.
  `python game_opportunities.py --selftest` (offline, golden prices hand-checked against the tables) is in CI and `tools/triple_check.py`.

### Changed
- Evolution quests are worded in the game's own text ("Defeat 15 Dark- or Steel-type Raid Bosses", "Win 10 raids", "Earn 70 hearts
  with your buddy") in the gated-evolution `need` strings, the "Which way to evolve" lines and the ladder report. The hand-built
  wording was wrong for 14 of the 37 quests (Sirfetch'd lost "Excellent", Overqwil "complete" for "win", hearts on a goal of 20 said
  "earn hearts with 20 times"). The texts ship in `pogo_extract/official_names_en.json` (`quests`), rebuilt with the same
  `bag_art.py --refresh-names` command; `evolvable_forms.json` cache v11. Text only: pile, reasons and tags are unchanged.
- A shadow mon's 2nd-move price is now x1.2 and a purified mon's x0.8 (`SHARED_MOVE_SETTINGS`); it was the plain price for every mon.
  `deep_profile.py` prices `power-up->L50` from the same tables (L40 to L50 was 340,000 dust / 290 XL, the game says 250,000 / 296;
  L20 to L50 was 840,000 dust, the game says 475,000). `game_opportunities.py` with an unknown argument prints its usage and exits 2.
- Root tidied: CONTRIBUTING / SECURITY / CODE_OF_CONDUCT moved to `.github/`, the CHANGELOG to `docs/`,
  `data_manifest.txt` to `tools/`, `wf_master.json` to `pogo_extract/`; `.editorconfig` removed.

### Changed
- AutoCatcher: every path that force-stopped PoGo is retired (#6): `restart_pogo_and_wait` raises, `tools/joystick_round.py`
  refuses while PoGo is open, and 41 retired `ondevice_toggle/` files plus `catch_loop_fast.v1-pause.py` left git (they stay on the PC).
- `docs/memory` re-synced with the PC memory (#7).

## [1.0.0] — 2026-09-29 — the move to the cloud

Before this release the tooling lived only on Benny's Windows PC (bag curation since 2026-05, the on-phone catcher
since 2026-06, the gym and buddy runners since 2026-09). This release puts it in one private repo that Claude cloud sessions run.

### Added
- The repository: `pogo_extract/` (bag curation), `AutoCatcher/` (on-phone catcher, research tools, gym/buddy runners),
  `pokegenie_work/` (PokeGenie tooling), whitelist `.gitignore` files, byte-exact `.gitattributes`.
- **Cloud phone bridge**: a SessionStart hook runs Tailscale inside the cloud VM, bridges adb over `tailscale nc`
  (on the phone's own address when the VM allows it) and exports `ADB_TARGET` and `TZ`; `cloud/setup.sh` for the environment.
- **Phone data store** (`tools/pogo_data.py`, `data_manifest.txt`): per-group versioned, sha256-checked tarballs on the
  phone; pull refuses to overwrite newer local work; push refuses to overwrite newer phone data; SQLite-safe packing.
- Docs: `docs/START_HERE.md` (printed into every session), `cloud_setup.md`, `data.md`, `phone_access.md`, and the
  exported working memory (113 notes).
- `pogo_extract/CLAUDE.md`; the `/cull` skill for the cloud (pull → cull → push → Bag Pulse).
- Community files, CI (offline checks + secret scan), issue/PR templates, CODEOWNERS, Dependabot for Actions.

### Changed
- The phone busy marker is **advisory**: logged, never waited on (“no one should be pausing anything for anyone”).
- `full_audit.py` refuses unknown flags (rc 2) and refuses to run without a real `pokemon.db`.
- `evolvable_forms.py` writes its cache atomically (parallel cold starts crashed 6 of 25 rounds before, 0 after).
- `dashboard.py` cancels jobs on Linux; `verify_tags_live.py` honours `ADB_TARGET`.
- `granular_tags.py --audit` says NOT RUN instead of a false green when no tag sets exist.
- `pogo_il2cpp.restart_pogo_and_wait()` refuses (#4): tools never force-stop or relaunch PoGo; `set_nicknames.py` stops
  instead of restarting the game.
- CI actions bumped by Dependabot: `actions/checkout` v7 (#2), `actions/setup-python` v7 (#3).

### Removed
- From the repo (kept on the PC): scripts that break the hard rules — bulk release, tag nukes outside `safe_nuke_tags.py`,
  game force-stoppers, the retired autocull and self-update daemons — plus stale-cap policy docs and third-party RE notes.

### Security
- Secrets and personal data excluded by whitelist; a Google-account identifier kept out of a research doc; CI secret scan.

[Unreleased]: https://github.com/BennyWaitWhat/PoGo-Gotta-Catch-Em-All/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/BennyWaitWhat/PoGo-Gotta-Catch-Em-All/releases/tag/v1.0.0
