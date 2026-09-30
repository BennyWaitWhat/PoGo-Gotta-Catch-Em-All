# Security

This repo controls a rooted phone and a live game account. Treat it that way.

## What must never be in git
Credentials of any kind (tokens, keys, cookies, passwords), the game's and Pokemod's preference/secret files, signing
keystores, captured sessions, and personal game data. Both `.gitignore` files are **whitelists** (deny by default), the
data store is **on the phone**, and CI scans every push for key and token patterns.

## Where the real secrets live
| Secret | Where | Who can see it |
|---|---|---|
| `TAILSCALE_AUTHKEY` | Claude cloud environment variables | Benny (environment owner) |
| `ADB_KEY_B64` / `ADB_PUB_B64` (the cloud-only adb key) | Claude cloud environment variables | Benny |
| Game / Pokemod sessions and prefs | the phone (and old copies on the PC, git-ignored) | Benny |
| GitHub access | the Claude GitHub app / the PC's `gh` login | Benny |

The adb key gives **root** on the phone. Lock the cloud down to the phone's adb port with a Tailscale tag + ACL
([`docs/cloud_setup.md`](docs/cloud_setup.md#lock-it-down-optional-once-the-bridge-works)).

## If something leaks
1. **Tailscale key:** admin console → Settings → Keys → revoke it; generate a new one; update the environment variable.
2. **Cloud adb key:** on the phone, Developer options → *Revoke USB debugging authorizations*, re-allow the PC, then
   make a new cloud key (`docs/cloud_setup.md` step 3).
3. **Anything committed:** tell Benny at once. Rotate first, then scrub history (the repo is private; a rewrite needs his OK).

## Reporting
Private repo: open an issue labelled `security`, or tell Benny directly. Never paste the secret itself into the issue.
