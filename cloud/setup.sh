#!/usr/bin/env bash
# CLOUD ENVIRONMENT SETUP SCRIPT -- paste this into the Claude cloud environment's "Setup script" field.
# Runs once as root on Ubuntu 24.04; the resulting filesystem is cached (~7 days), so every tool installed here is
# already there in later sessions. The per-session work (join the tailnet, bridge adb) is .claude/hooks/cloud_session_start.sh.
#
# Network access for the environment must be FULL, or CUSTOM with at least:
#   *.tailscale.com  tailscale.com  pkgs.tailscale.com  *.tailscale.io
#   pypi.org  files.pythonhosted.org  archive.ubuntu.com  security.ubuntu.com
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends android-tools-adb socat curl ca-certificates iproute2 procps sudo python3-pip python-is-python3 nodejs sqlite3 tzdata

# Tailscale (the official installer; tailscaled runs in userspace-networking mode from the session hook)
curl -fsSL https://tailscale.com/install.sh | sh

# Python side of the pipeline. frida MUST match the phone's frida-server / gadget major (the PC runs 17.9.11).
pip install --break-system-packages \
    frida==17.9.11 frida-tools \
    s2sphere numpy pandas requests flask protobuf

echo "setup done: $(tailscale version | head -1), adb $(adb version | head -1), frida $(python3 -c 'import frida; print(frida.__version__)')"
