# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Bag Pulse redesign: a night Pokédex frame from the README banner (Poké Ball header, navy-to-plum) with Oura-style data —
  score rings, light numerals, pastel series, smooth lines with fading fills; the page now shows the real scan time.

### Changed
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
