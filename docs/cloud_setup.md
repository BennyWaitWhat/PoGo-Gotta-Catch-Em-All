# Cloud setup — how a Claude cloud session reaches the phone

```
cloud VM ──tailscaled (userspace, HTTPS via the VM's proxy)──> Benny's tailnet ──> Pixel 100.98.158.56:5555 (adbd)
   adb ─> socat 100.98.158.56:5555 (VM loopback) ─> `tailscale nc` ─┘        Frida: adb forward tcp:27047 over the same link
```
Pieces in this repo: `cloud/setup.sh` (installs adb, socat, Tailscale, Python deps — the environment's setup script),
`.claude/hooks/cloud_session_start.sh` (every session: join the tailnet, restore the adb key, bridge, `adb connect`, export `ADB_TARGET`
and `TZ`), `.claude/settings.json` (registers the hook).

## Benny's one-time steps (≈15 min)
1. **GitHub access.** claude.ai/code → pick the repo `BennyWaitWhat/PoGo-Gotta-Catch-Em-All`. If it isn't listed, install/authorize the
   Claude GitHub app for BennyWaitWhat and give it this repo.
2. **Tailscale** (login.tailscale.com/admin):
   - *Access controls* — add, then Save:
     ```
     "tagOwners": { "tag:claude-cloud": ["autogroup:admin"] },
     ```
     and in `"acls"` add `{"action": "accept", "src": ["tag:claude-cloud"], "dst": ["100.98.158.56:5555"]}`. If the file still has the
     default rule with `"src": ["*"]`, change that `*` to `autogroup:member` — then the cloud can reach ONLY the phone's adb port.
   - *Settings → Keys → Generate auth key*: Reusable ON, Ephemeral ON, Pre-approved ON (if shown), Tags: `tag:claude-cloud`,
     expiry 90 days. Copy the `tskey-auth-…` value.
3. **ADB key** (PowerShell on the PC; the phone already trusts this key, so no "Allow USB debugging?" prompt):
   ```
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:USERPROFILE\.android\adbkey")) | Set-Clipboard
   ```
   paste it as `ADB_KEY_B64=` below; then the same with `adbkey.pub` for `ADB_PUB_B64=`.
4. **Cloud environment** (claude.ai/code → environment settings → new environment "PoGo"):
   - Network access: **Full** (Trusted blocks Tailscale).
   - Environment variables:
     ```
     TAILSCALE_AUTHKEY=tskey-auth-...
     ADB_KEY_B64=...
     ADB_PUB_B64=...
     ```
   - Setup script: paste all of `cloud/setup.sh`.
5. **Test:** start a session on the repo with that environment and say `cull`. The first message context shows `PHONE BRIDGE: connected`;
   the session pulls the data from the phone, runs the cull, pushes the data back, and reports.

Every 90 days the Tailscale key expires: generate a new one (step 2) and replace `TAILSCALE_AUTHKEY`.

## When the bridge says NOT connected (for sessions)
Read `/tmp/pogo_bridge.log`, then tell Benny the one matching line:
| Log shows | Cause | Fix (Benny) |
|---|---|---|
| `tailscale is not installed` | setup script missing/failed | paste `cloud/setup.sh` as the setup script |
| `TAILSCALE_AUTHKEY is not set` | env var missing | step 4 |
| `tailscale up failed` / auth errors | key expired/revoked, or network not Full | new key (step 2) / network Full |
| up, but `adb connect` fails or times out | phone offline, Tailscale off on the phone, or adbd not on TCP 5555 (after a reboot) | wake the phone; `adb tcpip 5555` from the PC, or the boot script |
| `unauthorized` in `adb devices` | wrong adb key | redo step 3 |
| `could not add 100.98.158.56 to loopback` | VM without root/NET_ADMIN | works on `127.0.0.1:5555`; tools that hardcode the address won't reach the phone |

Check by hand: `tailscale --socket=/tmp/tailscaled.sock status`, `adb devices`, `adb -s "$ADB_TARGET" shell getprop ro.product.model`.

## What changed for the PC (2026-09-29)
The PC seeded the phone data store and made the first commit. PoGo work no longer happens there; its folders stay as a backup copy.
