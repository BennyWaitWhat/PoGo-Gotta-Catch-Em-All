#!/data/data/com.termux/files/usr/bin/bash
# Catcher supervisor. It exists ONLY while one of your toggles is on: it starts the catcher once the
# game is up, restarts it after a crash, a PoGo restart or a hang (log silent 240s), and exits as soon
# as every toggle is off. It never writes a toggle -- they are yours.
# Replaces watchdog.sh, a 24/7 loop whose recoveries ran `stop` + `start` and so switched Spin off and
# Catch on behind your back (flags.log 2026-09-20: Catch+Spin re-enabled by hand 5 times in an hour).
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export LD_LIBRARY_PATH=$HOME/applibs:$PREFIX/lib
export PATH=$PREFIX/bin:/system/bin
LOG=$HOME/pogo/system/analysis/pokemod/catch_loop.log
CATCHER=$HOME/pogo/system/scripts/game_write/catch_phone.py
# The newest installed python3.N, a real file. It was hard-coded python3.13: `pkg upgrade` (2026-10-15) installed 3.14,
# and the catcher never started again. Two-digit minors come after one-digit ones here, so the last match is the newest.
PY=
for p in "$PREFIX"/bin/python3.[0-9] "$PREFIX"/bin/python3.[0-9][0-9]; do [ -f "$p" ] && PY=$p; done
on() { for t in catch spin perfect tap; do [ "$(tr -d '[:space:]' < /data/local/tmp/pogo_$t.on 2>/dev/null)" = 1 ] && return 0; done; return 1; }
game_up() { (exec 3<>/dev/tcp/127.0.0.1/27047) 2>/dev/null; }   # PoGo's gadget listens only while the game runs
say() { echo "$(date +%H:%M:%S) SUPERVISOR $*" >> "$LOG"; }
# SIGTERM first so the catcher detaches cleanly; -9 only if it is wedged past 3s.
end() { kill -TERM "$1" 2>/dev/null; for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do kill -0 "$1" 2>/dev/null || return 0; sleep 0.25; done; kill -9 "$1" 2>/dev/null; }

while on; do
  if game_up; then
    "${PY:-$PREFIX/bin/python3}" "$CATCHER" & pid=$!
    while kill -0 "$pid" 2>/dev/null; do
      sleep 30
      on || { end "$pid"; exit 0; }
      age=$(( $(date +%s) - $(date -r "$LOG" +%s 2>/dev/null || echo 0) ))
      [ "$age" -gt 240 ] && { say "catcher silent ${age}s -> restarting it"; end "$pid"; }
    done
    wait "$pid"; say "catcher exited (rc=$?) -> restarting once the game is up"
  fi
  sleep 3   # was 30: every exit or game restart waited up to half a minute here
done
