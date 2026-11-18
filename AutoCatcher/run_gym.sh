#!/data/data/com.termux/files/usr/bin/bash
# Gym Battle supervisor: the AutoCatcher app's Gym Battle switch, ON THE PHONE, no PC. Benny 2026-11-18: "any gym i visit and
# enter it will automatically go drill and finish and place shiny gyrados" / "why cant gym mode work without the PC? i want
# it working on my phone." It lives ONLY while /data/local/tmp/pogo_gym.on holds 1 (the app writes it: catcher_ctl.sh
# gym-on / gym-off). While it does:
#   - the game is up and no gym runner is alive: it starts ONE, from ~/pogo,
#       python -u tools/gym_run.py --on-open --no-feed --no-feed-mate --no-topup --switch /data/local/tmp/pogo_gym.on \
#           --cmd tools/gym_state/runner_cmd.json --minutes 100000
#     (the log: tools/gym_state/logs/onopen_MMDD_HHMMSS.log; one line of extra options, if you want any:
#     tools/gym_state/switch_args.txt). Berries stay OFF (Benny 11-16); a gym runner somebody else started is left alone.
#     Nothing is started while Catch Rewards runs (reward_phone.py): the status line says "waiting: Catch Rewards is running".
#   - the runner ended by itself: it starts it again. Three runs in a row that each ended inside 60 s = it stops trying and
#     says STOPPED, until the switch is set again.
#   - the switch goes off: it asks the runner to stop through its inbox (the file gym_send.sh '{"stop": true}' writes) and
#     waits for it to exit -- the runner finishes the battle in progress, leaves the gym, unloads from the game -- then it
#     writes "off" and leaves. (The runner also reads the switch itself, --switch: OFF stops it even if this script is gone.)
# It never kills a runner, never starts or restarts the game, never sends the joystick anything, never writes the switch.
# Safe to start twice: the second copy finds the lock and leaves. One line for the app, /data/local/tmp/pogo_gym_status.txt
# ("HH:MM:SS text"), rewritten at least every 15 s -- the app calls it dead after 60 s. tools/GYM.md has the rest.
#   run_gym.sh --preflight    after a deploy, before the switch is ever flipped: a READ-ONLY check, one PASS / FAIL line each.
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export LD_LIBRARY_PATH=$HOME/applibs:$PREFIX/lib
export PATH=$PREFIX/bin:/system/bin
export POGO_ON_PHONE=1 PYTHONIOENCODING=utf-8
FLAG=/data/local/tmp/pogo_gym.on
STATUS=/data/local/tmp/pogo_gym_status.txt
P=$HOME/pogo                       # the phone's copy of the repo's AutoCatcher folder
POLL=5                             # s between looks at the switch
EVERY=15                           # the status line is rewritten at least this often (the app's limit: 60 s)
QUICK_S=60; QUICK_MAX=3            # this many runs in a row that each ended inside QUICK_S = stop trying
STOP_AGAIN=20                      # a stop the runner threw away (it discards the stops it finds at its own start) is written again
STOP_GIVE_UP=240                   # switch ON again while a stop is out: after this long the runner evidently never took it
GAP=5                              # a runner that ended gets this long to let go of the game before the next one starts
GAME_EVERY=10                      # while the game is closed, its gadget is looked for this often (each look is one su call)
LOCK_WAIT=10                       # a second copy waits this long for a first one that may be on its way out
KEEP_LOGS=20
# The newest installed python3.N, a real file (run_catch.sh says why it is never hard-coded).
PY=
for p in "$PREFIX"/bin/python3.[0-9] "$PREFIX"/bin/python3.[0-9][0-9]; do [ -f "$p" ] && PY=$p; done
PY=${PY:-$PREFIX/bin/python3}
flag() { tr -d '[:space:]' 2>/dev/null < "$FLAG"; }
# ON = the switch file holds 1. One read can land between the app's truncate and its write: "not 1" is believed only twice.
on() { [ "$(flag)" = 1 ] || { sleep 0.3; [ "$(flag)" = 1 ]; }; }
# PoGo's gadget listens only while the game runs. Read its LISTEN entry, never connect (run_catch.sh: a connect-and-hang-up
# probe aborts the game).
game_up() { su -c 'cat /proc/net/tcp' 2>/dev/null | grep -q ':69A7 00000000:0000 0A'; }
# Every gym runner this user has ([g]: never this grep itself). Termux sees only its own processes -- a runner on the PC is
# invisible from here: flip the switch off before a PC run (GYM.md).
runners() { ps -ef 2>/dev/null | grep '[g]ym_run\.py' | awk '{print $2}'; }
root_id() { su -c 'id -u' 2>/dev/null; }
# Catch Rewards (the app's one-shot reward catcher) is attached to the game: no gym runner is added to it. The same test
# catcher_ctl.sh makes (11-18 16:06: two reward catchers on one game, and PoGo died three times in 100 s).
rewards_alive() { ps -ef 2>/dev/null | grep -q '[r]eward_phone\.py'; }
# The offline check only (tools/test_gym_phone.py): a temp folder stands in for the phone. Nothing on the phone sets this.
[ -n "${GYM_TEST_ENV:-}" ] && . "$GYM_TEST_ENV"
S=$P/tools/gym_state
LOCK=$S/run_gym.lock

now() { date +%s; }
log() { echo "$(date '+%m-%d %H:%M:%S') $*" 2>/dev/null >> "$S/run_gym.log"; }
flag_time() { date -r "$FLAG" +%s 2>/dev/null; }
# A runner of THIS switch: --on-open on its command line (and not the look-only --preflight, which leaves by itself).
is_onopen() {
  local c; c=$(tr '\0' ' ' 2>/dev/null < "/proc/$1/cmdline")
  case "$c" in *--preflight*) return 1 ;; *--on-open*) return 0 ;; esac
  return 1
}
extra() { grep -v '^[[:space:]]*#' "$S/switch_args.txt" 2>/dev/null | tr '\n\r' '  '; }
# Another copy of this supervisor is alive: the lock's pid lives and is a run_gym (never this process itself).
sup_alive() {
  local p; p=$(cat "$LOCK/pid" 2>/dev/null)
  [ -n "$p" ] && [ "$p" != "$$" ] && kill -0 "$p" 2>/dev/null && grep -q run_gym "/proc/$p/cmdline" 2>/dev/null
}

# status TEXT [once]: the app's one line. The same text again is rewritten only every $EVERY s (once: never again).
status() {
  local t; t=$(now)
  if [ "$1" = "$said" ] && { [ -n "${2:-}" ] || [ $((t - said_at)) -lt "$EVERY" ]; }; then return 0; fi
  if { printf '%s %s\n' "$(date +%H:%M:%S)" "$1" > "$STATUS"; } 2>/dev/null || mkstatus "$1"; then
    [ "$1" = "$said" ] || log "status: $1"
    said=$1; said_at=$t
  fi
}
# The file is gone (a cleanup): Termux cannot create one in /data/local/tmp, root can -- root-owned, 666, shell_data_file,
# the way catcher_ctl.sh remakes a flag. (No status text holds a quote: gym_status.py strips them.)
mkstatus() {
  su -c "echo '$(date +%H:%M:%S) $1' > $STATUS && chmod 666 $STATUS && chcon u:object_r:shell_data_file:s0 $STATUS" >/dev/null 2>&1
}

# One supervisor at a time (mkdir is atomic). A copy that is alive keeps the lock: wait a little -- it may be on its way
# out while the switch was set again -- then leave. A lock nobody alive holds (a reboot, a kill) is taken over.
take_lock() {
  local i=0 e=0 p
  while ! mkdir "$LOCK" 2>/dev/null; do
    p=$(cat "$LOCK/pid" 2>/dev/null)
    if [ -z "$p" ] && [ "$e" -lt 3 ]; then e=$((e + 1)); sleep 1; continue; fi     # (made this instant: its pid is not written yet)
    if [ -n "$p" ] && kill -0 "$p" 2>/dev/null && grep -q run_gym "/proc/$p/cmdline" 2>/dev/null; then
      i=$((i + 1)); [ "$i" -gt "$LOCK_WAIT" ] && return 1
      sleep 1
    else
      rm -rf "$LOCK"
    fi
  done
  echo $$ > "$LOCK/pid"
}

# The stop: one file in the runner's inbox, written under a dot name and moved in (gym_send.sh's way). Never a signal.
send_stop() {
  local n
  nstop=$((nstop + 1)); n="$(now)$(printf '%03d' $((nstop % 1000)))_app-switch.json"
  if printf '{"stop": true}\n' 2>/dev/null > "$S/runner_inbox/.$n" && mv "$S/runner_inbox/.$n" "$S/runner_inbox/$n"; then
    stops+=("$S/runner_inbox/$n")
  fi
  stop_at=$(now)
}
stop_pending() { local f; for f in "${stops[@]}"; do [ -e "$f" ] && return 0; done; return 1; }
# A stop of ours that nobody took must not wait in the inbox for the NEXT runner.
clear_stops() { local f; for f in "${stops[@]}"; do rm -f "$f"; done; stops=(); }

start_runner() {
  ls -1t "$S/logs"/onopen_*.log 2>/dev/null | tail -n +"$KEEP_LOGS" | while IFS= read -r f; do rm -f "$f"; done
  LOG=$S/logs/onopen_$(date +%m%d_%H%M%S).log
  # (trap '' HUP: a terminal that goes away must never take an attached runner with it -- GYM.md, "never hard-kill")
  ( set -f; trap '' HUP; cd "$P" && exec "$PY" -u tools/gym_run.py --on-open --no-feed --no-feed-mate --no-topup \
      --switch "$FLAG" --cmd "$S/runner_cmd.json" --minutes 100000 $(extra) >> "$LOG" 2>&1 ) &
  pid=$!; child=1; started=$(now); lsize=-1; rtext=
  echo "$pid $started $LOG" > "$S/run_gym.child"
}

# rtext = where the runner stands, in plain words, from its own log (tools/gym_status.py). Python is started only when the
# log grew, or every 30 s (a result line gives way to the wait after 90 s).
runner_text() {
  local sz; sz=$(wc -c 2>/dev/null < "$LOG"); sz=${sz:-0}
  if [ "$sz" != "$lsize" ] || [ $((t - ltext_at)) -ge 30 ] || [ -z "$rtext" ]; then
    lsize=$sz; ltext_at=$t
    rtext=$("$PY" -S "$P/tools/gym_status.py" "$LOG" 2>/dev/null | head -1); rtext=${rtext%$'\r'}
    rtext=${rtext:-the gym runner is running (its status could not be read)}
  fi
}

# The switch is ON: what this pass does about it.
step_on() {
  local o
  if [ -n "$latched" ] && [ "$(flag_time)" != "$latch_fm" ]; then              # the switch was set again: a new try
    log "the switch was set again: trying afresh"; latched=; quick=0
  fi
  if [ -n "$pid" ] && [ "$stop_at" != 0 ]; then                                # ON again while a stop is out...
    if stop_pending; then                                                      # ...that the runner has not read: take it back
      clear_stops; stop_at=0; log "switch ON again before the runner read the stop: stop taken back, the runner stays"
    elif [ $((t - stop_at)) -lt "$STOP_GIVE_UP" ]; then
      status "starting again: the last runner is still letting go of the game"; return
    else
      stop_at=0                                                                # it never took that stop: it is simply still running
    fi
  fi
  if [ -n "$latched" ]; then status "STOPPED: $latched"; return; fi
  if [ -n "$pid" ]; then runner_text; status "$rtext"; return; fi
  for o in $(runners); do                                                      # (an --on-open one was adopted before this)
    status "another gym runner is already running on the phone -- left alone"; return
  done
  if rewards_alive; then status "waiting: Catch Rewards is running"; return; fi
  if [ $((t - gcheck)) -ge "$GAME_EVERY" ]; then gcheck=$t; if game_up; then gup=1; else gup=0; fi; fi
  if [ "$gup" != 1 ]; then status "the game is closed -- the runner attaches when you open it"; return; fi
  if [ $((t - ended_at)) -lt "$GAP" ]; then status "starting again in a moment"; return; fi
  start_runner
  log "switch ON, the game is up: runner started (pid $pid, log ${LOG##*/})"
  status "starting: attaching to the game"
}

# run_gym.sh --preflight: a READ-ONLY check after a deploy, before the switch is ever flipped. One PASS / FAIL line per check,
# on the screen and in tools/gym_state/preflight.log; exit code 0 = no FAIL. It never writes the switch, the status line or
# the lock, starts no runner and stops none. Its second half is gym_run.py --preflight: attach, read (your Pokemon in gyms,
# your Gyarados, your six, the gyms on the map), unload -- nothing is pressed, placed or fed, the joystick gets nothing.
# It is never run beside a live gym runner or a live supervisor (two tappers in one game). While it runs, catcher_ctl.sh
# takes it for the supervisor ("a run_gym.sh is alive") and a flip of the switch starts none: its last lines say so.
preflight() {
  local bad=0 f o rc
  trap '' HUP PIPE                 # a terminal that goes away (adb drops) must not cut the attach half off mid-look
  mkdir -p "$S/logs" "$S/runner_inbox" 2>/dev/null
  : 2>/dev/null > "$S/preflight.log"
  tell() { printf '%s\n' "$*"; printf '%s\n' "$*" 2>/dev/null >> "$S/preflight.log"; }
  ok() { tell "PASS  $*"; }
  no() { tell "FAIL  $*"; bad=$((bad + 1)); }
  tell "$(date '+%Y-%m-%d %H:%M:%S') Gym Battle switch preflight (read-only)"
  if [ -x "$PY" ]; then ok "python: $("$PY" -V 2>&1 | tr -d '\r') ($PY)"; else no "python: $PY is not there"; fi
  for f in run_gym.sh pogo_il2cpp.py tools/gym_run.py tools/gym_tapper.py tools/live_graph_js.py tools/dump_game_limits.py \
           tools/cutoff_hunt.py tools/on_phone.py tools/gym_status.py; do
    if [ -r "$P/$f" ]; then ok "file $f ($(($(wc -c < "$P/$f"))) bytes)"; else no "file $f is not in $P"; fi
  done
  if [ -w "$S" ] && [ -w "$S/logs" ] && [ -w "$S/runner_inbox" ]; then ok "folder tools/gym_state: this user can write it"
  else no "folder tools/gym_state: cannot be written (it must belong to the Termux user)"; fi
  if [ -r "$FLAG" ]; then ok "switch file: readable, it holds '$(flag)' (left as it is)"
  else no "switch file: missing or unreadable (root makes it: 666, shell_data_file)"; fi
  if [ -w "$STATUS" ]; then ok "status file: writable (left as it is)"
  else no "status file: missing or not writable (root makes it: 666, shell_data_file)"; fi
  o=$(root_id)
  if [ "$o" = 0 ]; then ok "root: su answers"; else no "root: su gave '$o' (Magisk must allow Termux)"; fi
  if game_up; then ok "game: its gadget is listening (port 27047)"; else no "game: not running -- open it, wait a minute, run this again"; fi
  o=$(runners | tr '\n' ' ')
  if [ -n "$o" ]; then
    no "a gym runner is alive (pid $o): the attach checks are never run beside one -- switch off first"
  elif sup_alive; then
    no "the switch's supervisor is running: it may start a runner at any moment -- switch off, wait for 'off', run this again"
  elif rewards_alive; then
    no "Catch Rewards is running (reward_phone.py): the attach checks are never run beside it -- wait until it is done"
  elif [ "$bad" != 0 ]; then
    tell "SKIP  the attach checks (gym_run.py --preflight): fix the FAIL lines above first"
  else
    ( cd "$P" && exec "$PY" -u tools/gym_run.py --on-open --preflight --no-feed --no-feed-mate --no-topup --cmd "$S/runner_cmd.json" ) 2>&1 \
      | while IFS= read -r o; do tell "${o%$'\r'}"; done
    rc=${PIPESTATUS[0]}
    [ "$rc" = 0 ] || no "gym_run.py --preflight ended with exit code $rc (its own lines are above)"
  fi
  if on && ! sup_alive; then
    tell "NOTE  the switch is ON and no supervisor is running (a flip during this check starts none): flip it off and on"
  fi
  if [ "$bad" = 0 ]; then tell "PREFLIGHT PASS"; return 0; fi
  tell "PREFLIGHT FAIL ($bad)"; return 1
}
if [ "${1:-}" = --preflight ]; then preflight; exit $?; fi

said=; said_at=0
mkdir -p "$S/logs" "$S/runner_inbox" 2>/dev/null
ready=
[ -f "$P/tools/gym_run.py" ] && [ -f "$P/tools/gym_status.py" ] || ready="tools/gym_run.py is not on the phone"
[ -w "$S" ] && [ -w "$S/logs" ] && [ -w "$S/runner_inbox" ] || ready="pogo/tools/gym_state cannot be written"
if [ -n "$ready" ]; then           # a deploy that is not finished: say so for as long as the switch is on, start nothing
  while on; do status "STOPPED: $ready -- ask Claude"; sleep "$POLL"; done
  status off once
  exit 0
fi
take_lock || exit 0
trap 'rm -rf "$LOCK"' EXIT
trap 'exit 0' TERM INT
trap '' HUP                        # its terminal going away is not the switch going off
pid=; child=0; started=0; LOG=; quick=0; latched=; latch_fm=; stop_at=0; ended_at=0
stops=(); nstop=0; lsize=-1; rtext=; ltext_at=0; gup=0; gcheck=0
[ "$(wc -c 2>/dev/null < "$S/run_gym.log" || echo 0)" -gt 1000000 ] 2>/dev/null && mv -f "$S/run_gym.log" "$S/run_gym.log.1"
log "supervisor up (pid $$)"

while :; do
  t=$(now)
  if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then                       # the runner ended
    rc='?'; if [ "$child" = 1 ]; then wait "$pid" 2>/dev/null; rc=$?; fi
    ran=$((t - started))
    clear_stops; rm -f "$S/run_gym.child"
    asked=0; [ "$stop_at" != 0 ] && asked=1
    # The runner reads the switch itself: it can be gone before this loop ever saw the switch off. The switch was written
    # during its life and its log ends in a stop = it was asked.
    if [ "$asked" = 0 ] && [ "$(flag_time)" -ge "$started" ] 2>/dev/null && tail -n 8 "$LOG" 2>/dev/null | grep -q 'COMMAND stop'; then asked=1; fi
    if [ "$asked" = 1 ]; then
      log "the runner (pid $pid) ended after $ran s (exit code $rc) -- it was asked to stop"
    else
      log "the runner (pid $pid) ended by itself after $ran s (exit code $rc)"
      if [ "$ran" -lt "$QUICK_S" ]; then quick=$((quick + 1)); else quick=0; fi
      if [ "$quick" -ge "$QUICK_MAX" ]; then
        why=$("$PY" -S "$P/tools/gym_status.py" --why "$LOG" 2>/dev/null | head -1); why=${why%$'\r'}
        latched=${why:-the gym runner quit $quick times in a row -- flip the switch off and on}
        latch_fm=$(flag_time)
        log "STOPPED: $latched (the last log: ${LOG##*/})"
      fi
    fi
    pid=; child=0; stop_at=0; ended_at=$t
  fi
  if [ -z "$pid" ]; then                                                       # a runner of this switch that outlived its
    for o in $(runners); do                                                    # supervisor is this copy's now: its status is
      is_onopen "$o" || continue                                               # read, and switch-off stops it like any other
      pid=$o; child=0; started=$t; LOG=$(ls -1t "$S/logs"/onopen_*.log 2>/dev/null | head -1); lsize=-1; rtext=
      if read -r cp cs cl 2>/dev/null < "$S/run_gym.child" && [ "$cp" = "$o" ]; then started=$cs; LOG=$cl; fi
      log "a runner this switch started earlier is alive (pid $pid): it is this supervisor's now"
      break
    done
  fi
  if on; then
    step_on
  elif [ -n "$pid" ]; then                                                     # OFF: never a kill -- the runner unloads by itself
    if [ "$stop_at" = 0 ]; then
      log "switch OFF: the runner is asked to stop through its inbox"; send_stop
    elif [ $((t - stop_at)) -ge "$STOP_AGAIN" ] && ! stop_pending; then
      send_stop
    fi
    status "stopping: the runner finishes its battle, leaves the gym, lets go of the game"
  else
    status off once                                                            # one last line, then nothing more is written
    log "switch OFF, no runner alive: leaving"
    exit 0
  fi
  sleep "$POLL"
done
