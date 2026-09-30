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
2. **Tailscale key** (login.tailscale.com/admin -> Settings -> Keys -> Generate auth key): Reusable ON, Ephemeral ON,
   Pre-approved ON (if shown), expiry 90 days. Copy the `tskey-auth-...` value. (Optional hardening, after it works: the
   "Lock it down" section below.)
3. **A cloud-only ADB key** (PowerShell on the PC; keeps the PC's own key private, and you can revoke it on its own):
   ```
   adb keygen "$env:USERPROFILE\.android\cloud_adbkey"
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:USERPROFILE\.android\cloud_adbkey")) | Set-Clipboard
   ```
   paste it as `ADB_KEY_B64=` below; then run the last line again with `cloud_adbkey.pub` for `ADB_PUB_B64=`.
   The FIRST cloud session makes the phone ask "Allow USB debugging?": tick **Always allow from this computer**, tap Allow,
   then tell the session "retry the bridge" (it runs `adb connect "$ADB_TARGET"`).
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

## Lock it down (optional, once the bridge works)
Limit the cloud VM to the phone's adb port instead of the whole tailnet:
1. Access controls: add `"tagOwners": {"tag:claude-cloud": ["autogroup:admin"]}`, and an allow rule for
   `tag:claude-cloud` -> `100.98.158.56:5555` only. If the file still has the allow-all rule (`"src": ["*"]`), change that
   `*` to `autogroup:member` so your own devices keep full access and the tag gets only the rule above.
   (`acls` syntax: `{"action": "accept", "src": ["tag:claude-cloud"], "dst": ["100.98.158.56:5555"]}`;
   `grants` syntax: `{"src": ["tag:claude-cloud"], "dst": ["100.98.158.56"], "ip": ["tcp:5555"]}`.)
2. Generate a new key as in step 2 with Tags: `tag:claude-cloud`, and replace `TAILSCALE_AUTHKEY`.

## When the bridge says NOT connected (for sessions)
Read `/tmp/pogo_bridge.log`, then tell Benny the one matching line:
| Log shows | Cause | Fix (Benny) |
|---|---|---|
| `tailscale is not installed` | setup script missing/failed | paste `cloud/setup.sh` as the setup script |
| `TAILSCALE_AUTHKEY is not set` | env var missing | step 4 |
| `tailscale up failed` / auth errors | key expired/revoked, or network not Full | new key (step 2) / network Full |
| up, but `adb connect` fails or times out | phone off/offline, or its Tailscale app is off | wake the phone, turn Tailscale on (adb over TCP 5555 comes back by itself at boot: Magisk `service.d/adb_tcp_5555.sh`) |
| `unauthorized` in `adb devices` | the phone has not allowed the cloud key yet, or a wrong key | tap Allow on the phone ("Always allow"), then `adb connect "$ADB_TARGET"`; else redo step 3 |
| `could not add 100.98.158.56 to loopback` | VM without root/NET_ADMIN | works on `127.0.0.1:5555`; tools that hardcode the address won't reach the phone |

Check by hand: `tailscale --socket=/tmp/tailscaled.sock status`, `adb devices`, `adb -s "$ADB_TARGET" shell getprop ro.product.model`.

## What changed for the PC (2026-09-29)
The PC seeded the phone data store and made the first commit. PoGo work no longer happens there; its folders stay as a backup copy.
