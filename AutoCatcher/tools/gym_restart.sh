#!/bin/bash
# GRACEFUL restart of the gym runner (see GYM.md). The runner is OFF since the 2026-09-26 lockout: run this only after Benny's go.
# Asks the running runner to stop -- it finishes the battle in progress, leaves the gym, quiesces, unloads its script and
# detaches -- waits for it to exit, THEN starts the new one. Never force-kills (a kill mid-hook deadlocked PoGo, 2026-09-26 03:39).
# The stop goes into gym_state/runner_inbox/ (one file per command, nothing overwrites it); the runner removes the file when it
# takes it -> "stop taken". A runner older than the inbox reads only runner_cmd.json: the stop is re-sent there when overwritten.
# Portable: Windows Git Bash (PowerShell + cygpath) or Linux (the cloud VM: pgrep / kill -0). The phone = $ADB_TARGET.
# usage: gym_restart.sh NEWLOG [extra gym_run args...]      (the log lands in gym_state/logs/NEWLOG)
HERE="$(cd "$(dirname "$0")" && pwd)"; command -v cygpath >/dev/null 2>&1 && HERE="$(cygpath -m "$HERE")"
S="$HERE/gym_state"; PY="$(command -v python || command -v python3)"
mkdir -p "$S/runner_inbox" "$S/logs"
NEW="$S/logs/$1"; shift; EXTRA="$*"
if command -v powershell >/dev/null 2>&1; then
  runner_pid() { powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'gym_run' } | Select-Object -ExpandProperty ProcessId" | tr -d '\r'; }
  alive() { [ "$(powershell -NoProfile -Command "if (Get-Process -Id $1 -ErrorAction SilentlyContinue) {'1'} else {'0'}" | tr -d '\r')" = "1" ]; }
else
  runner_pid() { pgrep -f 'python[0-9.]* -u gym_run\.py' | head -1; }
  alive() { kill -0 "$1" 2>/dev/null; }
fi
PID=$(runner_pid)
if [ -n "$PID" ]; then
  F="$S/runner_inbox/$(date +%s%3N)_restart_stop.json"
  echo '{"stop": true}' > "$S/runner_inbox/.stop.tmp" && mv "$S/runner_inbox/.stop.tmp" "$F"
  still=1; taken=""
  for i in $(seq 1 150); do
    alive "$PID" || { still=0; break; }
    if [ -z "$taken" ] && [ ! -f "$F" ]; then taken=1; echo "stop taken by the runner after ~${i} s"; fi
    # an older runner: (re-)send through runner_cmd.json once the other writer's last command there had 2 s to be read
    if [ -f "$F" ] && [ "$i" -ge 3 ] && ! grep -q '"stop"' "$S/runner_cmd.json" 2>/dev/null \
       && [ $(( $(date +%s) - $(stat -c %Y "$S/runner_cmd.json" 2>/dev/null || echo 0) )) -ge 2 ]; then
      echo '{"stop": true}' > "$S/runner_cmd.json"; echo "(an older runner: stop sent through runner_cmd.json at ~${i} s)"
    fi
    sleep 1
  done
  rm -f "$F"
  if [ "$still" = "1" ]; then echo "runner $PID did not stop cleanly in ~150 s -- NOT force-killing; look at it first"; exit 1; fi
  echo "runner $PID stopped cleanly"
  sleep 3
fi
cd "$HERE" && PYTHONIOENCODING=utf-8 nohup "$PY" -u gym_run.py --goal 40.753597,-73.983233 --area 250 --detour 0 --travel-speed 30 --heal-batch 30 --heal-top 0 --route "$(cat "$HERE/gym_lap_route.txt")" --lap-every 2 --feed-zone 40.753597,-73.983233,250 --study "$S/feed_study.jsonl" --feed-at 0.36 --feed-hot 0.36 --cmd "$S/runner_cmd.json" --topup $EXTRA > "$NEW" 2>&1 &
sleep 20; grep -E "attached|starting in|Traceback|lost the game|could not attach|discarded|live service graph|phone marker" "$NEW" | head -8
