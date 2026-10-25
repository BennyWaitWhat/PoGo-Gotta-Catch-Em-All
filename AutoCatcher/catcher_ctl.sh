#!/data/data/com.termux/files/usr/bin/bash
# PoGo Auto control. ONE python process HOSTS BOTH features (catch + spin); each feature is
# enabled by its own flag FILE CONTENT ("1"/"0"), polled live by the catcher — so turning
# catching off no longer kills the process the spinner lives inside.
# Flag files must already exist (root pre-creates them 666); we only ever WRITE into them,
# because neither Termux nor the app can create/delete files in /data/local/tmp.
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin
RUN="$HOME/pogo/run_catch.sh"
CATCHFLAG=/data/local/tmp/pogo_catch.on
SPINFLAG=/data/local/tmp/pogo_spin.on
TAPFLAG=/data/local/tmp/pogo_tap.on
# Perfect Throw: forces Excellent + curveball on EVERY throw, manual ones included.
PERFFLAG=/data/local/tmp/pogo_perfect.on
# Apples: tap event map tappables (TAPPABLE_TYPE_MAPLE at Mossy-lured stops) the way a finger does.
APPLEFLAG=/data/local/tmp/pogo_apples.on

# [c]/[r] trick: the patterns never match this grep's own cmdline (avoids the pgrep self-match false positive).
# The supervisor (run_catch.sh) counts as running: it is alive while it waits for the game.
running() { ps -ef 2>/dev/null | grep -qE "[c]atch_phone\.py|[r]un_catch\.sh"; }

flag_on() { [ "$(cat "$1" 2>/dev/null | tr -d '[:space:]')" = "1" ]; }

# AUDIT: every flag transition is logged with the verb that caused it, so a toggle that silently
# flips off can be traced to its cause instead of guessed at.
FLAGLOG="$HOME/pogo/system/analysis/pokemod/flags.log"
setflag() { # setflag <file> <0|1> <label>
  old=$(cat "$1" 2>/dev/null | tr -d '[:space:]')
  [ -z "$2" ] && return 0                     # never write an empty value
  { echo "$2" > "$1"; } 2>/dev/null || mkflag "$1" "$2"
  now=$(cat "$1" 2>/dev/null | tr -d '[:space:]')
  if [ "$now" != "$2" ]; then
    echo "$(date '+%H:%M:%S') $3: $(basename "$1") NOT SAVED, still '$now' (verb=$VERB pid=$$)" >> "$FLAGLOG"
  elif [ "$old" != "$2" ]; then
    echo "$(date '+%H:%M:%S') $3: $(basename "$1") $old -> $2 (verb=$VERB pid=$$)" >> "$FLAGLOG"
  fi
  return 0
}
# Termux can write the flag files but not CREATE them (/data/local/tmp belongs to shell). An on-phone cleanup deleted
# them on 2026-10-15, and every toggle then failed silently: flags.log said "-> 1" but no file existed. Root makes them
# again the way setup did: root-owned, 666, shell_data_file. (Termux has Magisk root.)
mkflag() {
  su -c "echo $2 > $1 && chmod 666 $1 && chcon u:object_r:shell_data_file:s0 $1" >/dev/null 2>&1
}

start_proc() {
  running && return 0
  am startservice --user 0 \
    -n com.termux/com.termux.app.RunCommandService \
    -a com.termux.RUN_COMMAND \
    --es com.termux.RUN_COMMAND_PATH "$PREFIX/bin/bash" \
    --esa com.termux.RUN_COMMAND_ARGUMENTS "$RUN" \
    --ez com.termux.RUN_COMMAND_BACKGROUND true >/dev/null 2>&1
  # DEDUPE: two instances once raced in (both at the same second) and fought over the single-client
  # gadget — each resolved its own singletons, one latched a bad object and reported 135km distances.
  sleep 2
  keep=""
  for p in $(ps -ef 2>/dev/null | grep "[c]atch_phone\.py" | awk '{print $2}'); do
    if [ -z "$keep" ]; then keep="$p"; else kill -9 "$p" 2>/dev/null; fi
  done
}

stop_proc() {
  # SIGTERM first so the catcher detaches cleanly. kill -9 while attached leaves a dead ESTABLISHED
  # socket on the single-client gadget, and every later attach then times out ("timeout was reached")
  # — the state where the toggle reads ON but nothing happens. Supervisor first, so it cannot restart
  # the catcher we are stopping.
  pkill -TERM -f "run_catch\.sh" 2>/dev/null
  pkill -TERM -f catch_phone.py 2>/dev/null
  i=0
  while running && [ $i -lt 12 ]; do sleep 0.25; i=$((i+1)); done
  running && { pkill -9 -f "run_catch\.sh"; pkill -9 -f catch_phone.py; } 2>/dev/null
  return 0
}


LOG="$HOME/pogo/system/analysis/pokemod/catch_loop.log"
# "healthy" means: process alive AND it wrote to the log in the last 60s. A process that is up but
# wedged on a stale gadget socket writes nothing — that is the state where the toggle looked ON but
# nothing happened.
healthy() {
  running || return 1
  [ -f "$LOG" ] || return 1
  now=$(date +%s); mt=$(date -r "$LOG" +%s 2>/dev/null || echo 0)
  [ $((now - mt)) -lt 60 ]
}

# Turning a feature ON must GUARANTEE a working attach, not just set a flag. If we are not healthy,
# tear down and re-attach; if the gadget is holding a dead socket, restart PoGo to clear it.
ensure_live() {
  # Toggling ON must GUARANTEE a fresh working attach, not just set a flag: if the process is up but
  # wedged (writing nothing), tear it down and re-attach. Never touches the user's game.
  healthy && return 0
  stop_proc; sleep 1
  start_proc
}

# keep the host process alive while EITHER feature is on; shut down only when both are off
reconcile() {
  if flag_on "$CATCHFLAG" || flag_on "$SPINFLAG" || flag_on "$TAPFLAG" || flag_on "$PERFFLAG" || flag_on "$APPLEFLAG"; then start_proc; else stop_proc; fi
}

# Serialize control ops (mkdir is atomic) so concurrent taps can't spawn two processes.
# MUST WAIT, NEVER DROP: an earlier version exited 0 when the lock was held, so a toggle tapped
# while start_proc was mid-dedupe was silently swallowed — the switch looked ON but the flag stayed OFF.
LOCK="$HOME/pogo/.ctl.lock"
i=0
while ! mkdir "$LOCK" 2>/dev/null; do
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +2 2>/dev/null)" ]; then rmdir "$LOCK" 2>/dev/null; continue; fi
  i=$((i+1)); [ "$i" -ge 40 ] && break   # ~20s max, then proceed anyway rather than lose the command
  sleep 0.5
done
trap 'rmdir "$LOCK" 2>/dev/null' EXIT INT TERM

# Flags are written BEFORE taking any slow path, so a toggle is never lost even if the process
# work below is interrupted.

case "$1" in
  start)      echo 1 > "$CATCHFLAG"; stop_proc; sleep 1; start_proc ;;   # legacy: hard restart, catching on
  stop)       echo 0 > "$CATCHFLAG"; echo 0 > "$SPINFLAG"; stop_proc ;;  # legacy: everything off
  catch-on)   setflag "$CATCHFLAG" 1 "catch-on"; ensure_live ;;
  catch-off)  setflag "$CATCHFLAG" 0 "catch-off"; reconcile ;;
  spin-on)    setflag "$SPINFLAG" 1 "spin-on"; ensure_live ;;
  spin-off)   setflag "$SPINFLAG" 0 "spin-off"; reconcile ;;
  perfect-on)  setflag "$PERFFLAG" 1 "perfect-on"; ensure_live ;;
  perfect-off) setflag "$PERFFLAG" 0 "perfect-off"; reconcile ;;
  tap-on)     setflag "$TAPFLAG" 1 "tap-on"; ensure_live ;;
  tap-off)    setflag "$TAPFLAG" 0 "tap-off"; reconcile ;;
  apples-on)  setflag "$APPLEFLAG" 1 "apples-on"; ensure_live ;;
  apples-off) setflag "$APPLEFLAG" 0 "apples-off"; reconcile ;;
  restart)    stop_proc; sleep 1; start_proc ;;
  reconcile)  reconcile ;;   # boot hook: starts the supervisor only if a toggle was left on
  rewards)
    # One-shot: clear stacked Field-Research ("Today") reward encounters. The reward catcher needs the
    # gadget to ITSELF (single client), so park the auto-catcher, run it, then restore both toggles.
    echo "queued $(date +%H:%M:%S)" > /data/local/tmp/pogo_rewards.txt 2>/dev/null
    was_c=$(cat "$CATCHFLAG" 2>/dev/null | tr -d '[:space:]')
    was_s=$(cat "$SPINFLAG"  2>/dev/null | tr -d '[:space:]')
    stop_proc; sleep 2
    LD_LIBRARY_PATH=$HOME/applibs:$PREFIX/lib "$PREFIX/bin/python3.13" \
      "$HOME/pogo/system/scripts/game_write/reward_phone.py" "$2" \
      >> "$HOME/pogo/system/analysis/pokemod/reward_stdout.log" 2>&1
    echo "$was_c" > "$CATCHFLAG"; echo "$was_s" > "$SPINFLAG"
    reconcile
    ;;
  toggle)     if flag_on "$CATCHFLAG"; then echo 0 > "$CATCHFLAG"; else echo 1 > "$CATCHFLAG"; fi; reconcile ;;
  status)     echo "proc=$(running && echo up || echo down) catch=$(flag_on "$CATCHFLAG" && echo 1 || echo 0) spin=$(flag_on "$SPINFLAG" && echo 1 || echo 0) perfect=$(flag_on "$PERFFLAG" && echo 1 || echo 0) tap=$(flag_on "$TAPFLAG" && echo 1 || echo 0) apples=$(flag_on "$APPLEFLAG" && echo 1 || echo 0)" ;;
  *) echo "usage: catcher_ctl.sh start|stop|restart|reconcile|catch-on|catch-off|spin-on|spin-off|perfect-on|perfect-off|tap-on|tap-off|apples-on|apples-off|rewards|toggle|status" ;;
esac
