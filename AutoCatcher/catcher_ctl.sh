#!/data/data/com.termux/files/usr/bin/bash
# PoGo Auto control. ONE python process HOSTS BOTH features (catch + spin); each feature is
# enabled by its own flag FILE CONTENT ("1"/"0"), polled live by the catcher — so turning
# catching off no longer kills the process the spinner lives inside.
# Flag files must already exist (root pre-creates them 666); we only ever WRITE into them,
# because neither Termux nor the app can create/delete files in /data/local/tmp.
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin
# The newest installed python3.N, picked the way run_catch.sh picks it. "rewards" hard-coded python3.13 and ran nothing
# after `pkg upgrade` (2026-10-15) replaced it with 3.14: the app's Catch Rewards tap on 2026-10-25 01:04 died that way.
PY=
for p in "$PREFIX"/bin/python3.[0-9] "$PREFIX"/bin/python3.[0-9][0-9]; do [ -f "$p" ] && PY=$p; done
RUN="$HOME/pogo/run_catch.sh"
CATCHFLAG=/data/local/tmp/pogo_catch.on
SPINFLAG=/data/local/tmp/pogo_spin.on
TAPFLAG=/data/local/tmp/pogo_tap.on
# Perfect Throw: forces Excellent + curveball on EVERY throw, manual ones included.
PERFFLAG=/data/local/tmp/pogo_perfect.on
# Apples: tap event map tappables (TAPPABLE_TYPE_MAPLE at Mossy-lured stops) the way a finger does.
APPLEFLAG=/data/local/tmp/pogo_apples.on
# Gym Battle (app 1.3, Benny 2026-11-18: "any gym i visit and enter it will automatically go drill and finish and place
# shiny gyrados", then "why cant gym mode work without the PC? i want it working on my phone"). The gym runner runs ON
# the phone under its own supervisor, run_gym.sh (Gym Battle's file). The supervisor watches this flag: when it goes off
# it stops its runner gracefully through the runner's inbox and exits by itself.
#   gym-on  = write the flag, then start the supervisor if it is not alive (start_gym below).
#   gym-off = write the flag and NOTHING else. Never pkill / kill anything gym-related from here: a kill of a runner
#             attached to the game deadlocked PoGo (tools/GYM.md).
# The catcher stays blind to all of it: running() / stop_proc / reconcile() match only catch_phone.py and run_catch.sh,
# the gym verbs never start, keep alive or stop the catcher, and run_catch.sh's on() does not count this flag.
GYMFLAG=/data/local/tmp/pogo_gym.on
GYMRUN="$HOME/pogo/run_gym.sh"
# Gym mode (app 1.8; Benny 2026-11-19: "make an option to gym mode in order vs one by one"): 1 = one by one (the runner's
# own battles beat the FIRST defender, run at the 2nd defender's round and Battle again), anything else (or no file) =
# in order (every defender, in order). Only the gym runner reads it -- live, between battles (gym_run.py gym_mode_sync):
# like the berries flag it starts, stops and switches nothing else.
GYMOBOFLAG=/data/local/tmp/pogo_gym_obo.on
# Berries (catch_loop_fast.berry_mode, read every second): 1 = Pinap and Razz, pinap = Pinap only, razz = Razz only,
# anything else = none. Only the catcher reads it; it keeps no process alive either.
BERRYFLAG=/data/local/tmp/pogo_berries.on
# High stardust only (Benny 2026-11-18: "a catch mode that only catches high stardust pokemon (+ shinies) that can be
# toggled on", "inclusive of EVERY higher than avg stardust pokemon for that mode"). A whole number: 0 (or no file, or
# anything else) = catch everything; 1 = everything that pays more than a normal catch (a higher-paying species, or
# anything weather-boosted: "yes include weather boosted too"); N >= 2 = only catches worth N or more stardust.
# Every shiny is always caught. Only the catcher reads it: like the berries flag it keeps no process alive, and
# run_catch.sh's on() does not count it.
DUSTFLAG=/data/local/tmp/pogo_dust.on
# Reset counters (the app's button, app 1.7; Benny 2026-11-18: "how to restart/reset the stardust counter etc"). The
# catcher keeps the app's counters (caught, stardust, ...) across its re-attaches and restarts, and starts them from 0
# when this file holds a time it has not carried out yet (catch_loop_fast.counters_tick, read every second). The verb
# writes the tap's time (epoch seconds) and NOTHING else: it starts, stops and switches nothing, catcher running or not.
COUNTREQ=/data/local/tmp/pogo_counters.req

# [c]/[r] trick: the patterns never match this grep's own cmdline (avoids the pgrep self-match false positive).
# The supervisor (run_catch.sh) counts as running: it is alive while it waits for the game.
running() { ps -ef 2>/dev/null | grep -qE "[c]atch_phone\.py|[r]un_catch\.sh"; }

flag_on() { [ "$(cat "$1" 2>/dev/null | tr -d '[:space:]')" = "1" ]; }
# What the berries flag says, the way the catcher reads it: 1 / pinap / razz, anything else = 0 (none).
berry_mode() { b=$(cat "$BERRYFLAG" 2>/dev/null | tr -d '[:space:]'); case "$b" in 1|pinap|razz) echo "$b" ;; *) echo 0 ;; esac; }
# What the high-stardust flag says: its whole number, anything else (or no file) = 0 (everything).
dust_mode() { d=$(cat "$DUSTFLAG" 2>/dev/null | tr -d '[:space:]'); case "$d" in ''|*[!0-9]*|????????*) echo 0 ;; *) echo "$((10#$d))" ;; esac; }

# AUDIT: every flag transition is logged with the verb that caused it, so a toggle that silently
# flips off can be traced to its cause instead of guessed at.
FLAGLOG="$HOME/pogo/system/analysis/pokemod/flags.log"
setflag() { # setflag <file> <value> <label>   value = 0 / 1; the berries flag also takes pinap / razz
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
# The app's live catcher line (catch_loop_fast's state()). Same trap: the 2026-10-15 cleanup deleted it, nothing made it
# again, and until 2026-10-30 the app said "waiting for catcher..." while the catcher ran. Every verb remakes it if gone.
STATEF=/data/local/tmp/pogo_state.txt
[ -e "$STATEF" ] || mkflag "$STATEF" ""

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

# The gym supervisor is alive ([r] trick as in running(); this pattern matches run_gym.sh and nothing of the catcher).
gym_running() { ps -ef 2>/dev/null | grep -qE "[r]un_gym\.sh"; }

# Start the gym supervisor the way start_proc starts run_catch.sh. No run_gym.sh on the phone (the gym runner is not
# deployed) or a supervisor already alive: nothing to do. It never stops or kills anything.
start_gym() {
  [ -f "$GYMRUN" ] || return 0
  gym_running && return 0
  am startservice --user 0 \
    -n com.termux/com.termux.app.RunCommandService \
    -a com.termux.RUN_COMMAND \
    --es com.termux.RUN_COMMAND_PATH "$PREFIX/bin/bash" \
    --esa com.termux.RUN_COMMAND_ARGUMENTS "$GYMRUN" \
    --ez com.termux.RUN_COMMAND_BACKGROUND true >/dev/null 2>&1
  return 0
}

# keep the host process alive while EITHER feature is on; shut down only when both are off
reconcile() {
  if flag_on "$CATCHFLAG" || flag_on "$SPINFLAG" || flag_on "$TAPFLAG" || flag_on "$PERFFLAG" || flag_on "$APPLEFLAG"; then start_proc; else stop_proc; fi
}

# Each supervisor by its switch: the catcher while one of its five switches is on, the gym runner while its switch is
# on. The boot hook's work, and the last thing a reward run does.
settle() { reconcile; if flag_on "$GYMFLAG"; then start_gym; fi; }

# ---- NEVER TWO GAME CLIENTS ------------------------------------------------------------------------------------------
# The reward catcher needs the game to ITSELF: the auto-catcher, the gym runner and a second reward catcher are each
# one client too many. 2026-11-18 16:06, two Catch Rewards taps 18 s apart: the second reward catcher attached to the
# same game, which crashed 7 s later (APP CRASH NATIVE) and, started again, froze under the two (ANR); and the first
# run's end started the auto-catcher while the second reward catcher was still attached. The lock further down cannot
# prevent that: a waiting verb goes ahead after ~20 s "rather than lose the command", and a reward run takes minutes.
# So the rewards verb makes a MARKER for as long as it runs, and while a run is in flight
#   - another rewards verb does nothing (the run that is alive keeps writing its own status line);
#   - every other verb writes its flag as always and does NO process work: nothing starts, stops or restarts the
#     catcher or the gym runner, and nothing waits for the lock. The run's end follows the flags as they are then.
# The rewards verb itself does not run while Gym Battle is on or one of its processes is alive: nothing here ever parks
# or kills a gym process (see GYMFLAG), so he switches Gym Battle off first.
RWSTAT=/data/local/tmp/pogo_rewards.txt   # the app shows this line under Catch Rewards
RWMARK="$HOME/pogo/.reward.run"           # a directory: mkdir is atomic, so two taps cannot both make it
# Seconds between one client letting go of the game and the next one attaching. A quick re-attach is a crash roll for
# the gadget (the crash notes of 2026-10-23 and 10-29 name no number; on 2026-11-18 16:10 the catcher re-attached 2 s
# after a reward run let go, and he closed the game 17 s later).
REATTACH_GAP=5
VERB=$1
note() { echo "$(date '+%H:%M:%S') $* (verb=$VERB pid=$$)" >> "$FLAGLOG"; }
reward_running() { ps -ef 2>/dev/null | grep -qE "[r]eward_phone\.py"; }
# A gym process is alive on this phone: the supervisor (it can start a runner at any moment), a runner (it outlives its
# supervisor while it unloads), or run_gym.sh --preflight, whose second half attaches to the game as well.
gym_busy() { ps -ef 2>/dev/null | grep -qE "[r]un_gym\.sh|[g]ym_run\.py"; }
# In flight = the marker is younger than 15 min AND (reward_phone.py is alive OR the marker is younger than 30 s: a run
# parks the catcher before its python starts, and makes its marker young again for its last seconds). Any other marker
# is stale -- its run died without cleaning up, or has hung for 15 min -- and is removed here, with a line in flags.log,
# so a dead run can never block the switches.
reward_in_flight() {
  [ -d "$RWMARK" ] || return 1
  age=$(( $(date +%s) - $(date -r "$RWMARK" +%s 2>/dev/null || echo 0) ))
  if [ "$age" -ge 0 ] && [ "$age" -lt 900 ]; then
    [ "$age" -lt 30 ] && return 0
    reward_running && return 0
  fi
  alive=gone; reward_running && alive="still alive"
  rmdir "$RWMARK" 2>/dev/null && note "rewards: stale reward marker removed (${age} s old, reward_phone.py $alive)"
  return 1
}
reward_refuse() { note "rewards: a reward run is in flight, this tap does nothing"; exit 0; }

# What THIS run of the script made is removed when it exits, and nothing else: a verb that went ahead without the lock
# must not remove the lock of the verb that holds it. TERM and INT do not end the script (they never did: the old trap
# ran its rmdir and the script went on): a reward run has to reach its end, where the catcher starts again by the
# flags. kill -9 leaves the marker and the lock behind: the marker goes stale by the rule above, the lock after 2 min.
LOCK="$HOME/pogo/.ctl.lock"
OWNLOCK=; OWNMARK=
cleanup() {
  [ -n "$OWNMARK" ] && rmdir "$RWMARK" 2>/dev/null
  [ -n "$OWNLOCK" ] && rmdir "$LOCK" 2>/dev/null
  return 0
}
trap cleanup EXIT
trap : INT TERM

# Serialize control ops (mkdir is atomic) so concurrent taps can't spawn two processes.
# MUST WAIT, NEVER DROP: an earlier version exited 0 when the lock was held, so a toggle tapped
# while start_proc was mid-dedupe was silently swallowed — the switch looked ON but the flag stayed OFF.
take_lock() {
  i=0
  while :; do
    if mkdir "$LOCK" 2>/dev/null; then OWNLOCK=1; return 0; fi
    if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +2 2>/dev/null)" ]; then rmdir "$LOCK" 2>/dev/null && continue; fi
    i=$((i+1)); [ "$i" -ge 40 ] && return 0   # ~20s max, then proceed anyway rather than lose the command
    sleep 0.5
  done
}

# Is a reward run in flight? Asked BEFORE the lock, so a tap during a run does not sit out the lock's ~20 s first, and
# once more after a wait for the lock: a run may have started meanwhile (it holds the lock for minutes).
HOLD=
gate() {
  HOLD=
  if reward_in_flight; then HOLD=1; return 0; fi
  [ -n "$OWNLOCK" ] || take_lock
  if reward_in_flight; then HOLD=1; fi
  return 0
}
gate
[ -n "$HOLD" ] && [ "$1" = rewards ] && reward_refuse

# While a reward run is in flight a verb is flag only: one line in flags.log says so, and what the run's end will do.
# Called AFTER the verb wrote its flag, and it looks at the marker once more: a run removes its marker and only THEN
# reads the flags, so a flag written while the marker was still there is always seen by that run's end. Marker gone =
# the run ended and may have missed this flag, so the verb does its own work after all (gate again: lock, look again).
held() {
  if [ -n "$HOLD" ] && [ ! -d "$RWMARK" ]; then gate; fi
  [ -n "$HOLD" ] || return 1
  note "$VERB: reward run in flight: flag only -- $1"
  return 0
}
LATER="the catcher starts or stops by the flags when it ends"

# Flags are written BEFORE taking any slow path, so a toggle is never lost even if the process
# work below is interrupted.

case "$1" in
  start)      echo 1 > "$CATCHFLAG"; held "$LATER" || { stop_proc; sleep 1; start_proc; } ;;   # legacy: hard restart, catching on
  stop)       echo 0 > "$CATCHFLAG"; echo 0 > "$SPINFLAG"; held "$LATER" || stop_proc ;;      # legacy: everything off
  catch-on)   setflag "$CATCHFLAG" 1 "catch-on"; held "$LATER" || ensure_live ;;
  catch-off)  setflag "$CATCHFLAG" 0 "catch-off"; held "$LATER" || reconcile ;;
  spin-on)    setflag "$SPINFLAG" 1 "spin-on"; held "$LATER" || ensure_live ;;
  spin-off)   setflag "$SPINFLAG" 0 "spin-off"; held "$LATER" || reconcile ;;
  perfect-on)  setflag "$PERFFLAG" 1 "perfect-on"; held "$LATER" || ensure_live ;;
  perfect-off) setflag "$PERFFLAG" 0 "perfect-off"; held "$LATER" || reconcile ;;
  tap-on)     setflag "$TAPFLAG" 1 "tap-on"; held "$LATER" || ensure_live ;;
  tap-off)    setflag "$TAPFLAG" 0 "tap-off"; held "$LATER" || reconcile ;;
  apples-on)  setflag "$APPLEFLAG" 1 "apples-on"; held "$LATER" || ensure_live ;;
  apples-off) setflag "$APPLEFLAG" 0 "apples-off"; held "$LATER" || reconcile ;;
  gym-on)     setflag "$GYMFLAG" 1 "gym-on"; held "the gym runner starts when it ends" || start_gym ;;
  gym-off)    setflag "$GYMFLAG" 0 "gym-off" ;;   # the flag ONLY: run_gym.sh sees it and stops by itself (see GYMFLAG)
  gym-order)    setflag "$GYMOBOFLAG" 0 "gym-order" ;;      # the flag only: the gym runner reads it between battles
  gym-onebyone) setflag "$GYMOBOFLAG" 1 "gym-onebyone" ;;
  berries-off)   setflag "$BERRYFLAG" 0 "berries-off" ;;        # the flag only: the catcher reads it every second
  berries-pinap) setflag "$BERRYFLAG" pinap "berries-pinap" ;;
  berries-razz)  setflag "$BERRYFLAG" razz "berries-razz" ;;
  berries-on)    setflag "$BERRYFLAG" 1 "berries-on" ;;
  dust-off)   setflag "$DUSTFLAG" 0 "dust-off" ;;                # the flag only: the catcher reads it
  dust-on)    setflag "$DUSTFLAG" 1 "dust-on" ;;                 # everything that pays more than a normal catch
  dust-*)     n=${1#dust-}                                       # dust-500 / dust-700 / dust-1000: a whole number, nothing else
              case "$n" in
                ''|*[!0-9]*|????????*) echo "usage: catcher_ctl.sh dust-off | dust-on | dust-<whole number>" ;;
                *) setflag "$DUSTFLAG" "$((10#$n))" "dust-$n" ;;
              esac ;;
  counters-reset) setflag "$COUNTREQ" "$(date +%s)" "counters-reset" ;;   # the file only: the catcher reads it every second
  restart)    held "$LATER" || { stop_proc; sleep 1; start_proc; } ;;
  reconcile)  held "$LATER" || settle ;;   # boot hook: starts each supervisor only if its toggle was left on
  rewards)
    # One-shot: clear stacked Field-Research ("Today") reward encounters. The reward catcher needs the game to ITSELF
    # (NEVER TWO GAME CLIENTS, above): park the auto-catcher, run it, then let the flags decide what runs.
    # The app shows the status file. A cleanup can delete it and Termux can't create it, so root remakes it.
    if reward_running; then   # a reward catcher with no marker (its run went stale, or it was started by hand) is a client too
      note "rewards: reward_phone.py is alive without a marker, this tap does nothing"
      exit 0
    fi
    if flag_on "$GYMFLAG" || gym_busy; then
      if flag_on "$GYMFLAG"; then t="Gym Battle is on: switch it off first"; else t="Gym Battle is still running: tap again when it has stopped"; fi
      t="$t @ $(date +%H:%M:%S)"
      { echo "$t" > "$RWSTAT"; } 2>/dev/null || mkflag "$RWSTAT" "'$t'"
      note "rewards: not run, Gym Battle is on or a gym process is alive"
      exit 0
    fi
    mkdir "$RWMARK" 2>/dev/null || reward_refuse   # atomic: of two taps that both got this far, one makes it
    OWNMARK=1
    { echo "queued $(date +%H:%M:%S)" > "$RWSTAT"; } 2>/dev/null || mkflag "$RWSTAT" queued
    stop_proc; sleep "$REATTACH_GAP"
    LD_LIBRARY_PATH=$HOME/applibs:$PREFIX/lib "${PY:-$PREFIX/bin/python3}" \
      "$HOME/pogo/system/scripts/game_write/reward_phone.py" "$2" \
      >> "$HOME/pogo/system/analysis/pokemod/reward_stdout.log" 2>&1
    # Its last seconds are in flight too: the marker is young again (and back, if a verb removed it as stale during a
    # run of more than 15 min), so nothing attaches during the gap. touch -c never makes a file.
    mkdir "$RWMARK" 2>/dev/null; touch -c "$RWMARK" 2>/dev/null
    sleep "$REATTACH_GAP"
    # After minutes the lock looks abandoned (2 min): young again, so a verb that comes now waits for the line below.
    [ -n "$OWNLOCK" ] && touch -c "$LOCK" 2>/dev/null
    # The flags as they are NOW decide. A switch he flipped during the run was written at once (flag only) and is
    # honoured here. Until 2026-11-18 this restored Catch and Spin to what they were BEFORE the run and so undid such a
    # tap; neither reward_phone.py nor reward_catcher.py writes those flags, so there is nothing to restore.
    rmdir "$RWMARK" 2>/dev/null; OWNMARK=
    settle
    ;;
  toggle)     if flag_on "$CATCHFLAG"; then echo 0 > "$CATCHFLAG"; else echo 1 > "$CATCHFLAG"; fi; held "$LATER" || reconcile ;;
  status)     echo "proc=$(running && echo up || echo down) catch=$(flag_on "$CATCHFLAG" && echo 1 || echo 0) spin=$(flag_on "$SPINFLAG" && echo 1 || echo 0) perfect=$(flag_on "$PERFFLAG" && echo 1 || echo 0) tap=$(flag_on "$TAPFLAG" && echo 1 || echo 0) apples=$(flag_on "$APPLEFLAG" && echo 1 || echo 0) gym=$(flag_on "$GYMFLAG" && echo 1 || echo 0) gymmode=$(flag_on "$GYMOBOFLAG" && echo onebyone || echo order) berries=$(berry_mode) dust=$(dust_mode)" ;;
  *) echo "usage: catcher_ctl.sh start|stop|restart|reconcile|catch-on|catch-off|spin-on|spin-off|perfect-on|perfect-off|tap-on|tap-off|apples-on|apples-off|gym-on|gym-off|gym-order|gym-onebyone|berries-off|berries-pinap|berries-razz|berries-on|dust-off|dust-on|dust-<N>|counters-reset|rewards|toggle|status" ;;
esac
