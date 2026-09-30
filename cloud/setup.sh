#!/usr/bin/env bash
# CLOUD ENVIRONMENT SETUP SCRIPT -- paste this into the Claude cloud environment's "Setup script" field.
# Runs once as root on Ubuntu 24.04; the resulting filesystem is cached (~7 days), so every tool installed here is
# already there in later sessions. The per-session work (join the tailnet, bridge adb) is .claude/hooks/cloud_session_start.sh.
#
# Network access for the environment must be FULL (Trusted blocks Tailscale), or CUSTOM with at least:
#   *.tailscale.com  tailscale.com  pkgs.tailscale.com  *.tailscale.io  controlplane.tailscale.com  derp*.tailscale.com
#   pypi.org  files.pythonhosted.org  archive.ubuntu.com  security.ubuntu.com  raw.githubusercontent.com (game-master refresh)
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends android-tools-adb socat curl ca-certificates iproute2 procps sudo \
    python3-pip python-is-python3 nodejs sqlite3 tzdata gh

# Tailscale: the official installer; if it fails (no systemd in the container), the static build. tailscaled runs in
# userspace-networking mode from the session hook, so no service or /dev/net/tun is needed.
if ! curl -fsSL https://tailscale.com/install.sh | sh; then
  echo "tailscale install.sh failed -- falling back to the static build"
fi
if ! command -v tailscaled >/dev/null; then
  TGZ=$(curl -fsSL 'https://pkgs.tailscale.com/stable/?mode=json' | python3 -c 'import json,sys; print(json.load(sys.stdin)["Tarballs"]["amd64"])')
  curl -fsSL "https://pkgs.tailscale.com/stable/$TGZ" | tar xz -C /tmp
  install -m 755 "/tmp/${TGZ%.tgz}/tailscale" "/tmp/${TGZ%.tgz}/tailscaled" /usr/local/bin/
fi

# Python: only what the committed code imports. frida MUST match the phone's gadget major (the PC ran 17.9.11).
# (Research-only extras, install per task: loguru, androguard, mitmproxy.)
pip install --break-system-packages frida==17.9.11 frida-tools s2sphere flask protobuf

echo "setup done: tailscale $(tailscale version | head -1), $(adb version | head -1), frida $(python3 -c 'import frida; print(frida.__version__)')"
