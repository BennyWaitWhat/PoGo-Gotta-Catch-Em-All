# PoGo-Gotta-Catch-Em-All

Private repo of Benny's Pokémon GO tooling for one rooted Pixel 9 Pro. All work runs in Claude cloud sessions; each session reaches the
phone over Tailscale and keeps the game data on the phone.

| Path | What |
|---|---|
| `pogo_extract/` | **Bag curation.** A Frida/IL2CPP walk reads every Pokémon into `pokemon.db`; the keep law (`LAW.md`) decides; the result goes back as the game's own tags. `Transfer` = safe to release — **Benny releases by hand, the tools only tag.** 11 audits gate every push. Start: `pogo_extract/CLAUDE.md` |
| `AutoCatcher/` | **The on-phone catcher** (Termux + the Frida gadget) plus desktop research tools, and the gym/buddy runners. Start: `AutoCatcher/README.md`, `AutoCatcher/tools/GYM.md` |
| `docs/` | `START_HERE.md` (every session reads it first), `cloud_setup.md`, `data.md`, `phone_access.md`, `memory/` (standing rules + incident notes) |
| `tools/pogo_data.py`, `data_manifest.txt` | The phone data store: pull/push of the game data to `/data/local/tmp/pogo_data` |
| `cloud/setup.sh`, `.claude/` | Cloud environment setup script, the SessionStart phone-bridge hook, the `/cull` skill |
| `pokegenie_work/*.py` | PokeGenie backup tooling (regenerates its collection from `pokemon.db`) |

Not in git by design: game data (on the phone, see `docs/data.md`), secrets, phone dumps, binaries. Both `.gitignore` files are
whitelists — a new file stays untracked until it is allowed there. Setting up a new cloud environment: `docs/cloud_setup.md`.
