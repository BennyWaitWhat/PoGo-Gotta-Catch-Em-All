#!/usr/bin/env bash
# CLOUD ENVIRONMENT SETUP SCRIPT -- the copy in the repo is cloud/setup.sh (keep them identical).
# Runs once as root on Ubuntu 24.04; the result is cached (~7 days). Per-session work (tailnet + adb bridge) is
# .claude/hooks/cloud_session_start.sh. Network access must be FULL (Trusted blocks Tailscale).
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends android-tools-adb socat curl ca-certificates iproute2 procps sudo \
    python3-pip python-is-python3 nodejs sqlite3 tzdata gh

# Tailscale: the official installer; if it fails (no systemd in the container), the static build.
if ! curl -fsSL https://tailscale.com/install.sh | sh; then
  echo "tailscale install.sh failed -- falling back to the static build"
fi
if ! command -v tailscaled >/dev/null; then
  TGZ=$(curl -fsSL 'https://pkgs.tailscale.com/stable/?mode=json' | python3 -c 'import json,sys; print(json.load(sys.stdin)["Tarballs"]["amd64"])')
  curl -fsSL "https://pkgs.tailscale.com/stable/$TGZ" | tar xz -C /tmp
  install -m 755 "/tmp/${TGZ%.tgz}/tailscale" "/tmp/${TGZ%.tgz}/tailscaled" /usr/local/bin/
fi

# Python: frida MUST match the phone's gadget (17.9.11); frida-tools pinned with it (newer ones need frida >= 17.10).
pip install --break-system-packages frida==17.9.11 frida-tools==14.8.2 s2sphere flask protobuf

echo "setup done: tailscale $(tailscale version | head -1), $(adb version | head -1), frida $(python3 -c 'import frida; print(frida.__version__)')"
