# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

### Removed
- From the repo (kept on the PC): scripts that break the hard rules — bulk release, tag nukes outside `safe_nuke_tags.py`,
  game force-stoppers, the retired autocull and self-update daemons — plus stale-cap policy docs and third-party RE notes.

### Security
- Secrets and personal data excluded by whitelist; a Google-account identifier kept out of a research doc; CI secret scan.

[Unreleased]: https://github.com/BennyWaitWhat/PoGo-Gotta-Catch-Em-All/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/BennyWaitWhat/PoGo-Gotta-Catch-Em-All/releases/tag/v1.0.0
