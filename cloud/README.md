# cloud

## `setup.sh` — the Claude cloud environment's setup script

Paste the whole file into the environment's **Setup script** field (claude.ai/code → environment settings). It runs once
as root on Ubuntu 24.04 and the result is cached, so later sessions start with everything installed:

- adb, socat, sqlite3, tzdata, `gh`, Node.js
- Tailscale (the official installer, or the static build when the installer can't run)
- Python: `frida==17.9.11` (must match the phone's gadget), `frida-tools==14.8.2`, `s2sphere`, `flask`, `protobuf`

The per-session part — joining the tailnet and bridging adb to the phone — is
`../.claude/hooks/cloud_session_start.sh`. Step-by-step setup and troubleshooting:
[`../docs/cloud_setup.md`](../docs/cloud_setup.md).
