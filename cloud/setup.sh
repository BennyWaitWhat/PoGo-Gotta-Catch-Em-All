#!/usr/bin/env bash
# CLOUD ENVIRONMENT SETUP SCRIPT -- the copy in the repo is cloud/setup.sh (keep them identical).
# BEST-EFFORT ON PURPOSE: a failing setup script blocks the whole session (2026-09-29: pip died mid-download and the
# session never started). Nothing here may fail hard; the SessionStart hook reports anything still missing, with the fix.
# Network access must be FULL (Trusted blocks Tailscale).
set -uo pipefail
log() { echo "[setup] $*"; }
export DEBIAN_FRONTEND=noninteractive

apt-get update -y >/dev/null 2>&1 || log "apt-get update failed"
for pkgs in "android-tools-adb socat curl ca-certificates iproute2 procps tzdata sqlite3" \
            "python3-pip nodejs sudo gh" "python-is-python3"; do
  apt-get install -y --no-install-recommends $pkgs >/dev/null 2>&1 || log "apt could not install some of: $pkgs"
done

# Tailscale: the official installer; if it fails (no systemd in the container), the static build.
if ! command -v tailscaled >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh >/dev/null 2>&1 || log "tailscale install.sh failed -- trying the static build"
fi
if ! command -v tailscaled >/dev/null; then
  TGZ=$(curl -fsSL 'https://pkgs.tailscale.com/stable/?mode=json' | python3 -c 'import json,sys; print(json.load(sys.stdin)["Tarballs"]["amd64"])' 2>/dev/null)
  if [ -n "${TGZ:-}" ] && curl -fsSL "https://pkgs.tailscale.com/stable/$TGZ" | tar xz -C /tmp; then
    install -m 755 "/tmp/${TGZ%.tgz}/tailscale" "/tmp/${TGZ%.tgz}/tailscaled" /usr/local/bin/ || log "tailscale static install failed"
  else
    log "tailscale static download failed"
  fi
fi

# Python: frida MUST match the phone's gadget (17.9.11); frida-tools pinned with it (newer ones need frida >= 17.10).
# Two tries with retries/timeouts; the image's own python3 (3.11 on 2026-09-29) is fine -- frida ships abi3 wheels.
PIP="python3 -m pip install --break-system-packages --retries 5 --timeout 120 --progress-bar off"
# 2026-09-30: Debian's python3-blinker 1.7 has no RECORD file, so pip can't upgrade it to flask's blinker>=1.9 and the
# whole install below failed (flask + frida-tools missing). Install the new one beside it (earlier on sys.path).
python3 -c 'import flask' 2>/dev/null || timeout 300 $PIP --ignore-installed 'blinker>=1.9' || log "blinker install failed"
for try in 1 2; do
  timeout 600 $PIP frida==17.9.11 frida-tools==14.8.2 s2sphere flask protobuf && break
  log "pip install failed (try $try)"; sleep 5
done

log "summary: tailscale=$(command -v tailscaled >/dev/null && echo ok || echo MISSING)" \
    "adb=$(command -v adb >/dev/null && echo ok || echo MISSING)" \
    "socat=$(command -v socat >/dev/null && echo ok || echo MISSING)" \
    "frida=$(python3 -c 'import frida; print(frida.__version__)' 2>/dev/null || echo MISSING)"
exit 0
