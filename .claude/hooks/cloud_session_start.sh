#!/usr/bin/env bash
# SESSION START (cloud only): join Benny's tailnet, bridge the phone's adb into this VM, and hand the session its
# standing rules. In a LOCAL session (the PC) this exits at once -- the PC reaches the phone over its own Tailscale.
#
# Needs these environment variables (set in the cloud environment's settings, NEVER in the repo; docs/cloud_setup.md):
#   TAILSCALE_AUTHKEY   an ephemeral, reusable, pre-approved auth key tagged tag:claude-cloud
#   ADB_KEY_B64         base64 of the PC's ~/.android/adbkey      (the phone already trusts it: no "Allow USB debugging?")
#   ADB_PUB_B64         base64 of the PC's ~/.android/adbkey.pub
# Optional: POGO_PHONE_TS (default 100.98.158.56:5555) -- the phone's Tailscale address and adb port.
#
# The bridge answers on the phone's OWN address when it can (the address is added to this VM's loopback), so the
# ~130 tools that hardcode "adb -s 100.98.158.56:5555" work unchanged; otherwise it falls back to 127.0.0.1:5555 and
# only tools that read ADB_TARGET reach the phone. Either way ADB_TARGET is exported for the session.
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# the tools parse naive timestamps in local time (the PC ran America/New_York; mixed zones shift walk freshness by hours)
[ -n "${CLAUDE_ENV_FILE:-}" ] && echo "export TZ=America/New_York" >>"$CLAUDE_ENV_FILE"
export TZ=America/New_York
LOG=/tmp/pogo_bridge.log
SOCK=/tmp/tailscaled.sock
PHONE="${POGO_PHONE_TS:-100.98.158.56:5555}"
PHONE_IP="${PHONE%:*}"; PHONE_PORT="${PHONE#*:}"
note() { echo "[$(date +%H:%M:%S)] $*" >>"$LOG"; }
asroot() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo -n "$@"; fi; }
TARGET=""

bridge() {
  command -v tailscaled >/dev/null || { note "tailscale is not installed -- paste cloud/setup.sh as the environment's setup script"; return 1; }
  [ -n "${TAILSCALE_AUTHKEY:-}" ] || { note "TAILSCALE_AUTHKEY is not set in the environment -- no phone bridge"; return 1; }
  if ! tailscale --socket="$SOCK" status >/dev/null 2>&1; then
    # userspace networking: no /dev/net/tun needed; control + DERP traffic leaves over HTTPS (honours HTTPS_PROXY)
    nohup tailscaled --tun=userspace-networking --state=mem: --socket="$SOCK" >>"$LOG" 2>&1 &
    for _ in $(seq 1 15); do [ -S "$SOCK" ] && break; sleep 1; done
    # bounded: a proxy that blocks the control plane must not eat the whole hook (nothing below would print)
    timeout 40 tailscale --socket="$SOCK" up --authkey="$TAILSCALE_AUTHKEY" --hostname="claude-cloud-pogo" \
        --accept-dns=false --accept-routes=false >>"$LOG" 2>&1 || { note "tailscale up failed or timed out (40 s)"; return 1; }
  fi
  mkdir -p ~/.android
  [ -n "${ADB_KEY_B64:-}" ] && { echo "$ADB_KEY_B64" | base64 -d > ~/.android/adbkey; chmod 600 ~/.android/adbkey; }
  [ -n "${ADB_PUB_B64:-}" ] && echo "$ADB_PUB_B64" | base64 -d > ~/.android/adbkey.pub
  # adb cannot use a proxy, so a local TCP port is piped through `tailscale nc` to the phone's adb port
  local bind=127.0.0.1
  if ip -4 addr show dev lo 2>/dev/null | grep -q " $PHONE_IP/" || asroot ip addr add "$PHONE_IP/32" dev lo 2>>"$LOG"; then
    bind="$PHONE_IP"
  else
    note "could not add $PHONE_IP to loopback (no root/NET_ADMIN) -- bridging on 127.0.0.1; hardcoded-address tools won't reach the phone"
  fi
  if ! pgrep -f "TCP-LISTEN:$PHONE_PORT,bind=$bind" >/dev/null; then
    nohup socat "TCP-LISTEN:$PHONE_PORT,bind=$bind,fork,reuseaddr" \
        EXEC:"tailscale --socket=$SOCK nc $PHONE_IP $PHONE_PORT" >>"$LOG" 2>&1 &
    sleep 1
  fi
  TARGET="$bind:$PHONE_PORT"
  adb start-server >>"$LOG" 2>&1
  for _ in 1 2; do timeout 12 adb connect "$TARGET" >>"$LOG" 2>&1; adb -s "$TARGET" get-state 2>/dev/null | grep -q device && break; sleep 3; done
  # every project tool reads ADB_TARGET (pogo_il2cpp, walk_tripwires, pogo_data, AutoCatcher, gym)
  [ -n "${CLAUDE_ENV_FILE:-}" ] && echo "export ADB_TARGET=$TARGET" >>"$CLAUDE_ENV_FILE"
  return 0
}

bridge || true
# tools the setup script may not have finished installing (it is best-effort so it can never block a session)
MISSING=""
for m in frida s2sphere flask; do python3 -c "import $m" 2>/dev/null || MISSING="$MISSING $m"; done
for c in adb socat tailscaled; do command -v "$c" >/dev/null || MISSING="$MISSING $c"; done
STATE=0
[ -n "$TARGET" ] && STATE=$(adb devices 2>/dev/null | grep -c "^$TARGET[[:space:]]*device")

# stdout of a SessionStart hook becomes session context: the standing orientation + the bridge state
cat "$ROOT/docs/START_HERE.md" 2>/dev/null
echo
if [ -n "$MISSING" ]; then
  echo "SETUP INCOMPLETE -- missing:$MISSING. Fix it yourself first: bash cloud/setup.sh (it is idempotent), then run this"
  echo "hook again: bash .claude/hooks/cloud_session_start.sh -- and only then continue."
fi
if [ "$STATE" = "1" ]; then
  echo "PHONE BRIDGE: connected -- adb $TARGET -> $PHONE over Tailscale; ADB_TARGET=$TARGET. Log: $LOG"
  echo "DATA: run 'python tools/pogo_data.py pull' before any work that reads game data (docs/data.md)."
else
  echo "PHONE BRIDGE: NOT connected -- phone steps (culls, deploys, gym runs, data pull/push) are unavailable this session."
  echo "Read $LOG and docs/cloud_setup.md; tell Benny in one line what failed."
fi
exit 0
