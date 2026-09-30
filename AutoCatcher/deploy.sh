#!/usr/bin/env bash
# Push AutoCatcher files to the phone's ~/pogo tree (same relative path), md5-verified, owner kept as Termux.
#   ./deploy.sh [--restart] system/scripts/game_write/catch_loop_fast.py [more files...]
# --restart restarts the catcher afterwards (warm game: back up in ~1 s).
# Portable: Git Bash on Windows (cygpath converts the local path for adb.exe) or Linux (the cloud VM: plain paths;
# ADB_TARGET=127.0.0.1:5555 through the Tailscale bridge). MSYS_NO_PATHCONV only matters to Git Bash; Linux ignores it.
set -euo pipefail
D=${ADB_TARGET:-100.98.158.56:5555}
H=/data/data/com.termux/files/home/pogo
cd "$(dirname "$0")"
restart=0; [ "${1:-}" = --restart ] && { restart=1; shift; }
adb connect "$D" >/dev/null 2>&1 || true
for f in "$@"; do
  sum=$(md5sum < "$f" | cut -c1-32); tmp=/data/local/tmp/ac_$(basename "$f")
  if command -v cygpath >/dev/null 2>&1; then src=$(cygpath -w "$f"); else src="$f"; fi
  MSYS_NO_PATHCONV=1 adb -s "$D" push "$src" "$tmp" >/dev/null
  MSYS_NO_PATHCONV=1 adb -s "$D" shell "su -c '[ \"\$(md5sum $tmp | cut -c1-32)\" = $sum ] && cp $tmp $H/$f.tmp && chown 10762:10762 $H/$f.tmp && mv $H/$f.tmp $H/$f && rm -f $tmp && echo \"ok   $f\" || echo \"FAIL $f\"'"
  case "$f" in   # a stale .pyc would keep running the old code
    *.py) MSYS_NO_PATHCONV=1 adb -s "$D" shell "su -c 'rm -f $H/$(dirname "$f")/__pycache__/$(basename "$f" .py).*.pyc'" ;;
  esac
done
if [ $restart = 1 ]; then
  MSYS_NO_PATHCONV=1 adb -s "$D" shell "su -c 'su 10762 -c \"/data/data/com.termux/files/usr/bin/bash $H/catcher_ctl.sh restart\"'"
  echo "restarted"
fi
