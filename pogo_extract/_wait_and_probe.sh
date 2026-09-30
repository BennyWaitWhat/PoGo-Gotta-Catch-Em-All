#!/bin/bash
# Wait up to 30 min for the phone to rejoin the tailnet + PoGo to be running, then run the badge probe.
for i in $(seq 1 60); do
  adb connect 100.98.158.56:5555 >/dev/null 2>&1
  if adb -s 100.98.158.56:5555 shell pidof com.nianticlabs.pokemongo >/dev/null 2>&1; then
    echo "[watcher] phone back + PoGo running (attempt $i) -- running probe"
    python dex_badge_probe.py
    exit $?
  fi
  if adb -s 100.98.158.56:5555 shell echo ok >/dev/null 2>&1; then
    echo "[watcher] phone is BACK but PoGo is NOT running (attempt $i) -- waiting for the app"
  fi
  sleep 30
done
echo "[watcher] TIMEOUT: phone did not return within 30 min"
exit 2
