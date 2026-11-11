#!/usr/bin/env bash
# ONE cull pass per go (Benny 2026-11-10, "A2": the cull starts the moment he sends "cull").
#   bash tools/cull_now.sh              start a pass -- unless one is running or a hook-started one waits unread -- then
#                                       wait for it and print its output. Claude runs this ONE command for every cull.
#   bash tools/cull_now.sh --hook       the UserPromptSubmit hook: hook JSON on stdin; a bare cull go ("cull", "Continue. Cull.",
#                                       "cull again") starts the pass detached and prints one context line; anything else is silent
#   bash tools/cull_now.sh --selfcheck  the go matcher on fixed samples (no phone, no pass)
# The pass itself: the phone reachable, the game running with its gadget up, then full_audit.py, its report, the page text,
# the data push in the background. No gap wait, no young-game wait (Benny 2026-11-08). It never restarts the game, never
# retries, and only tags (full_audit.py). State lives beside the cull's own files: pogo_extract/system/analysis/cull_now.*
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
A=${CULL_NOW_STATE:-pogo_extract/system/analysis}        # the self-check points this at its own folder
OUT=$A/cull_now.out; LOCK=$A/cull_now.lock; UNREAD=$A/cull_now.unread; LAST=$A/cull_now.last
T="${ADB_TARGET:-100.98.158.56:5555}"

is_go() {   # stdin: the hook JSON. True only when the WHOLE prompt is a cull go: every word known, no question, no "don't"
  python -c '
import json, sys
try:
    p = json.load(sys.stdin).get("prompt") or ""
except Exception:
    sys.exit(1)
GO = {"cull", "recull"}
FILL = {"ok", "okay", "please", "pls", "now", "go", "continue", "and", "then", "also", "again", "yes", "yep", "run", "do",
        "the", "a", "it", "another", "one", "more", "time", "full", "quick"}
w = [x.strip(".,!;:").lstrip("/").lower() for x in p.split()]
sys.exit(0 if "?" not in p and 0 < len(w) <= 6 and GO & set(w) and all(x in GO or x in FILL for x in w) else 1)'
}

# a lock is live while its owner is alive -- and for two hours at most, so a recycled pid can never hold it forever
running() { [ -d "$LOCK" ] && kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null && [ $(( $(date +%s) - $(stat -c %Y "$LOCK") )) -lt 7200 ]; }

# shortcut: two starters racing over a DEAD owner's lock in the same few milliseconds could both win; use an OS lock if
# passes are ever started by more than the hook plus one foreground call
take() {    # the lock is a directory: mkdir is atomic, so two starters can never both win. A dead owner's lock is cleared once
  mkdir "$LOCK" 2>/dev/null || { running && return 1; rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null || return 1; }
  echo $$ > "$LOCK/pid"
}

pass() {
  echo "start $(date '+%m-%d %H:%M:%S')"
  [ -f "$A/push.log" ] && echo "last background push: $(grep -m1 '^inventory:' "$A/push.log" || tail -1 "$A/push.log")"
  for i in $(seq 1 180); do
    adb connect "$T" > "$A/cull_now.adb" 2>&1
    adb devices | tr -d '\r' | grep -q "^$T[[:space:]]*device$" && break
    sleep 15
  done
  if ! adb devices | tr -d '\r' | grep -q "^$T[[:space:]]*device$"; then
    echo "PHONE STILL OFFLINE at $(date +%H:%M) -- last adb connect: $(tr -d '\r' < "$A/cull_now.adb")"; return 3
  fi
  # one round trip: the game's pid and age, the gadget's listener, the phone's uptime
  R=$(adb -s "$T" shell 'P=$(pidof com.nianticlabs.pokemongo); echo "pid=$P"; echo "age=$([ -n "$P" ] && ps -o ELAPSED= -p $P)"; echo "gadget=$(grep -ci :69A7 /proc/net/tcp)"; echo "up=$(cut -d" " -f1 /proc/uptime)"' | tr -d '\r')
  P=$(echo "$R" | sed -n 's/^pid=//p'); L=$(echo "$R" | sed -n 's/^gadget=//p')
  ST=$(python tools/pogo_data.py status 2>&1 | grep '^inventory '); echo "$ST"
  PV=$(echo "$ST" | grep -oE 'phone v[0-9]+' | grep -oE '[0-9]+'); HV=$(echo "$ST" | grep -oE 'here v[0-9]+' | grep -oE '[0-9]+')
  if [ -n "$PV" ] && [ -n "$HV" ] && [ "$PV" -gt "$HV" ]; then
    echo "phone v$PV is newer than here v$HV -- pulling first"; python tools/pogo_data.py pull 2>&1 | tail -3
    python tools/pogo_data.py status 2>&1 | grep '^inventory '
  fi
  [ -f "$LAST" ] && read -r LD LT LP < "$LAST"       # shortcut: MM-DD compares as text, wrong across New Year for one pass
  echo "game pid=$P age=$(echo "$R" | sed -n 's/^age=//p' | tr -d ' ') gadget=$L phone up $(echo "$R" | sed -n 's/^up=//p' | awk '{printf "%.1f h", $1/3600}') | last cull: ${LD:-none} ${LT:-} pid ${LP:-?} | now $(date +%H:%M:%S)"
  if [ -n "$LD" ]; then
    echo "--- game crashes since $LD $LT"
    adb -s "$T" shell "logcat -d -b crash | grep -E 'Process uptime|>>> com.nianticlabs.pokemongo|Abort message'" | tr -d '\r' \
      | awk -v d="$LD" -v t="$LT" '$1 > d || ($1 == d && $2 >= t)' | sed -E 's/ +[0-9]+ +[0-9]+ F DEBUG +: / /' | cut -c1-150 | tail -10
  fi
  if [ -z "$P" ] || [ "${L:-0}" -lt 1 ]; then
    echo "NOT RUN (game not running / no gadget)"; return 4
  fi
  echo "$(date '+%m-%d %H:%M') $P" > "$LAST"
  echo "--- full_audit starting $(date +%H:%M:%S)"
  ( cd pogo_extract && python full_audit.py > system/analysis/last_cull.log 2>&1 ); RC=$?; echo "rc=$RC"
  cd pogo_extract || return 1
  grep -E "bag [0-9]|AUDIT GATE|DONE --|PHASES|STOPPED|frozen|session is gone|WARN|FAILED|remote trade:|hundo buckets:|VERIFY|retire:" system/analysis/last_cull.log \
    | awk '{ if ($0 ~ /hundo buckets:/) print; else if ($0 ~ /remote trade:/) print substr($0, 1, 700); else print substr($0, 1, 260) }'
  grep -E "^\[ *[0-9.]+s\]   ! " system/analysis/last_cull.log | cut -c1-220
  sed -n '/=== REPORT ===/,$p' system/analysis/last_cull.log | grep -v '^\['
  PYTHONIOENCODING=utf-8 python bag_art.py --text > system/analysis/cull_now.page 2>&1; echo "bag_art rc=$? ($(wc -c < system/analysis/cull_now.page) bytes)"
  cat system/analysis/cull_now.page
  cd ..
  # ALWAYS push after a phone pass, even when the gate failed (the walk changed the data); detached, the next pass shows its result
  python -c "import subprocess, sys; subprocess.Popen([sys.executable, 'tools/pogo_data.py', 'push', '--group', 'inventory'], stdout=open(r'$A/push.log', 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, close_fds=True, **({'creationflags': 0x08000200} if sys.platform == 'win32' else {'start_new_session': True}))" \
    && echo "--- data push started in the background (the next pass shows its result)"
  return $RC
}

# self-check only: the lock, detach and attach paths with no phone and no pass
[ -n "${CULL_NOW_DRY:-}" ] && pass() { echo "start dry"; sleep "$CULL_NOW_DRY"; echo "--- full_audit starting"; echo "rc=0"; }

show() {    # wait for the running pass, print what it wrote, and mark it read
  while running; do sleep 1; done
  cat "$OUT"; rm -f "$UNREAD"
  grep -q '^--- full_audit starting' "$OUT" && ! grep -q '^rc=' "$OUT" && { echo "PASS DIED MID-RUN (no rc line) -- NOT retried: read $A/last_cull.log first"; return 7; }
  return "$(sed -n 's/^rc=//p' "$OUT" | tail -1 | grep -E '^[0-9]+$' || echo 1)"
}

case "${1:-}" in
  --selfcheck)
    for s in 'cull' 'Cull.' 'Continue. Cull.' 'cull again' 'recull' '/cull' 'ok cull now' 'do a full cull' 'run the cull please'; do
      printf '{"prompt": "%s"}' "$s" | is_go || { echo "selfcheck FAILED: should start: $s"; exit 1; }
    done
    for s in 'cull?' 'dont cull' 'do not cull yet' 'why did the cull fail' 'A1 A2 cull' 'cull later' 'stop the cull' 'go' '' \
             'fix X then cull' 'cull\nbut first read this' 'cull the Scyther'; do
      printf '{"prompt": "%s"}' "$s" | is_go && { echo "selfcheck FAILED: should NOT start: $s"; exit 1; }
    done
    export CULL_NOW_STATE=pogo_extract/system/analysis/.cull_now_selfcheck.$$ CULL_NOW_DRY=2; mkdir -p "$CULL_NOW_STATE"
    bad() { echo "selfcheck FAILED: $1"; rm -rf "$CULL_NOW_STATE"; exit 1; }
    H=$(printf '{"prompt": "cull"}' | bash tools/cull_now.sh --hook); case "$H" in *"started ONE cull pass"*) ;; *) bad "the hook did not start a pass: $H" ;; esac
    H=$(printf '{"prompt": "cull"}' | bash tools/cull_now.sh --hook); case "$H" in *"ALREADY running"*) ;; *) bad "a second go started a second pass: $H" ;; esac
    O=$(bash tools/cull_now.sh); case "$O" in *attached*"start dry"*"rc=0"*) ;; *) bad "the foreground call did not attach: $O" ;; esac
    [ -e "$CULL_NOW_STATE/cull_now.lock" ] || [ -e "$CULL_NOW_STATE/cull_now.unread" ] && bad "state left behind after the pass"
    O=$(bash tools/cull_now.sh --pass 1); case "$O" in *"NOTHING was run"*) ;; *) bad "--pass ran without its hook's lock: $O" ;; esac
    O=$(bash tools/cull_now.sh); case "$O" in "start dry"*"rc=0"*) ;; *) bad "a plain foreground pass: $O" ;; esac
    printf '{"prompt": "cull"}' | bash tools/cull_now.sh --hook > /dev/null; sleep 4
    O=$(bash tools/cull_now.sh); case "$O" in *"hook already ran"*"rc=0"*) ;; *) bad "a finished hook pass was not picked up: $O" ;; esac
    O=$(bash tools/cull_now.sh); case "$O" in "start dry"*) ;; *) bad "a read pass was shown twice: $O" ;; esac
    rm -rf "$CULL_NOW_STATE"
    echo "cull_now self-check OK"; exit 0 ;;
  --hook)
    IN=$(cat); case "${IN,,}" in *cull*) ;; *) exit 0 ;; esac
    printf '%s' "$IN" | is_go || exit 0
    if take; then
      date +%s > "$UNREAD"; : > "$OUT"
      BASH_EXE=$(cygpath -w "$BASH" 2>/dev/null || echo "$BASH") python -c "import os, subprocess, sys; subprocess.Popen([os.environ['BASH_EXE'], 'tools/cull_now.sh', '--pass', '$$'], stdout=open(r'$OUT', 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, close_fds=True, **({'creationflags': 0x08000200} if sys.platform == 'win32' else {'start_new_session': True}))" \
        || { rm -rf "$LOCK" "$UNREAD"; exit 0; }
      for i in $(seq 1 50); do [ "$(cat "$LOCK/pid" 2>/dev/null)" != "$$" ] && break; sleep 0.1; done   # the pass owns the lock now
      echo "cull_now: the hook started ONE cull pass at $(date +%H:%M:%S) for this message. Do not start another: run \`bash tools/cull_now.sh\` (background) -- it attaches to this pass and prints its output."
    elif running; then
      echo "cull_now: this go is covered by the cull pass that is ALREADY running ($(head -1 "$OUT" 2>/dev/null)). Do not start another pass for this message: if that pass's output was already read in this conversation, report from it; else run \`bash tools/cull_now.sh\` once (background) to attach."
    fi
    exit 0 ;;
  --pass)       # the detached pass a hook started: it takes over THAT hook's lock ($2 = the hook's pid), or it does nothing
    [ -n "${2:-}" ] && [ "$(cat "$LOCK/pid" 2>/dev/null)" = "$2" ] || { echo "--pass is the hook's own entry (its lock is gone or taken) -- NOTHING was run"; exit 2; }
    echo $$ > "$LOCK/pid"; pass; RC=$?; grep -q '^rc=' "$OUT" || echo "rc=$RC"; rm -rf "$LOCK"; exit $RC ;;
  '')
    if running; then echo "(attached to the pass that is already running)"; show; exit $?; fi
    U=$(grep -m1 -E '^[0-9]+$' "$UNREAD" 2>/dev/null)
    if [ -n "$U" ] && [ $(( $(date +%s) - U )) -lt 900 ]; then
      if grep -qE '^--- full_audit starting|^rc=' "$OUT"; then echo "(the hook already ran this pass)"; show; exit $?; fi
      echo "(the hook's pass never got going -- starting it here)"; cat "$OUT"
    fi
    rm -f "$UNREAD"
    take || { echo "(attached to the pass that just started)"; show; exit $?; }
    pass 2>&1 | tee "$OUT"; RC=${PIPESTATUS[0]}
    grep -q '^rc=' "$OUT" || echo "rc=$RC" | tee -a "$OUT"
    rm -rf "$LOCK"; exit "$RC" ;;
  *) echo "usage: bash tools/cull_now.sh [--hook | --selfcheck]   (unknown: $1 -- NOTHING was run)"; exit 2 ;;
esac
