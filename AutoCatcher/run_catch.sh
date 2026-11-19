#!/data/data/com.termux/files/usr/bin/bash
# Catcher supervisor. It exists ONLY while one of your toggles is on: it starts the catcher once the
# game is up, restarts it after a crash, a PoGo restart or a hang (log silent 240s while the game is on
# screen), and exits as soon as every toggle is off. It never writes a toggle -- they are yours.
# Replaces watchdog.sh, a 24/7 loop whose recoveries ran `stop` + `start` and so switched Spin off and
# Catch on behind your back (flags.log 2026-09-20: Catch+Spin re-enabled by hand 5 times in an hour).
#
# The catcher attaches only while Pokemon GO is on screen, and detaches by itself when it leaves (catch_loop_fast's
# screen watcher). The game died at 02:52 and 10:54 on 2026-11-19 with the gadget's own abort (gdbus, libsoup "could not
# get remote address: Transport endpoint is not connected") while it sat behind other apps, frozen by Android: the
# catcher's call hung there, this supervisor took the silence for a hang, killed it (-9 after 3 s) and started another
# catcher, whose connect waited unanswered; the gadget aborts when it accepts a connection whose client has gone
# (docs/requests/2026-11-15-catcher-attach-loop-crashes.md). So: a silent catcher behind other apps is idle, not hung,
# and a kill -9 never cuts off a connection the gadget has not accepted yet.
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
on() { for t in catch spin perfect tap apples; do [ "$(tr -d '[:space:]' < /data/local/tmp/pogo_$t.on 2>/dev/null)" = 1 ] && return 0; done; return 1; }
# PoGo's gadget listens only while the game runs. Read its LISTEN entry, never connect: a connect-and-hang-up probe hits
# the gadget's server mid-accept and aborts the game ("could not get remote address", 10 crashes 2026-10-27/28).
game_up() { su -c 'cat /proc/net/tcp' 2>/dev/null | grep -q ':69A7 00000000:0000 0A'; }
say() { echo "$(date +%H:%M:%S) SUPERVISOR $*" >> "$LOG"; }

# One root read, made only before this script would restart or kill the catcher: the gadget's LISTEN line (its 5th field
# is tx_queue:rx_queue, and a LISTEN socket's rx_queue counts the connections waiting to be accepted), the app Android has
# resumed on top, and the screen's state (the two lines the cull reads, pogo_il2cpp._adb_on_screen).
look() {
  LOOK=$(su -c 'grep -m1 ":69A7 00000000:0000 0A" /proc/net/tcp; dumpsys activity activities 2>/dev/null | grep -m1 -E "topResumedActivity|ResumedActivity"; dumpsys power 2>/dev/null | grep -m1 mWakefulness=' 2>/dev/null)
}
up() { case "$LOOK" in *":69A7 00000000:0000 0A"*) return 0 ;; esac; return 1; }
on_screen() {
  case "$LOOK" in *mWakefulness=Awake*) ;; *) return 1 ;; esac
  case "$LOOK" in *"ActivityRecord{"*" com.nianticlabs.pokemongo/"*) return 0 ;; esac
  return 1
}
queued() {   # a connection waits in the gadget's accept queue
  set -- $(echo "$LOOK" | grep -m1 ':69A7 00000000:0000 0A')
  q=${5#*:}
  case "$q" in ''|*[!0-9A-Fa-f]*) return 1 ;; esac
  [ "$((16#$q))" -gt 0 ]
}

# End the catcher: SIGTERM, and it detaches and exits by itself once the call it is in returns. -9 only where that cannot
# cut off a connection the gadget has not accepted yet (ask 2): when the game is gone, or when it is on screen with nothing
# in the gadget's accept queue -- never while it is behind other apps, where a frozen game answers nothing and the
# connection would be cut off mid-handshake. (The old -9 after 3 s came 15 s and 89 s before the two crashes of 11-19.)
end() {
  kill -TERM "$1" 2>/dev/null
  n=0
  while kill -0 "$1" 2>/dev/null; do
    sleep 1; n=$((n + 1))
    [ "$n" -lt 30 ] && continue
    [ $((n % 5)) -eq 0 ] || continue
    look
    if ! up; then
      kill -9 "$1" 2>/dev/null; say "catcher still alive ${n}s after TERM and the game is gone -> killed"; return 0
    fi
    if on_screen && ! queued; then
      kill -9 "$1" 2>/dev/null; say "catcher still alive ${n}s after TERM -> killed (the game is on screen, no connection waits on the gadget)"; return 0
    fi
    [ $((n % 60)) -eq 0 ] && say "catcher still in a call ${n}s after TERM -> not killed: the game is not on screen or a connection waits on the gadget (a kill mid-handshake crashes the game)"
  done
  return 0
}

while on; do
  if game_up; then
    "${PY:-$PREFIX/bin/python3}" "$CATCHER" & pid=$!
    while kill -0 "$pid" 2>/dev/null; do
      sleep 30
      on || { end "$pid"; exit 0; }
      age=$(( $(date +%s) - $(date -r "$LOG" +%s 2>/dev/null || echo 0) ))
      [ "$age" -gt 240 ] || continue
      # A silent log is a hang only while the game is on screen (ask 6). Behind other apps the game is frozen, so the
      # catcher's call waits for it, and goes on when the game is back. (This line also restarts the 240 s.)
      look
      if up && ! on_screen; then say "catcher silent ${age}s while the game is not on screen -> left alone (idle, not a hang)"; continue; fi
      say "catcher silent ${age}s -> restarting it"; end "$pid"
    done
    wait "$pid"; say "catcher exited (rc=$?) -> restarting once the game is up"
  fi
  sleep 3   # was 30: every exit or game restart waited up to half a minute here
done
