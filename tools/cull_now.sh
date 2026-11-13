#!/usr/bin/env bash
# ONE cull pass per go (Benny 2026-11-10, "A2": the cull starts the moment he sends "cull").
#   bash tools/cull_now.sh              start a pass -- unless one is running or a hook-started one waits unread -- then
#                                       wait for it and print its output. Claude runs this ONE command for every cull.
#                                       A pass that waits for the phone is reported AT ONCE (rc 3, "PHONE OFFLINE", 2026-11-13);
#                                       it keeps waiting, starts by itself when the phone answers, and stays unread.
#   bash tools/cull_now.sh --wait       the same call, but it sits out that wait and prints the pass when it ends
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
    assert isinstance(p, str)
except Exception:
    sys.exit(1)
GO = {"cull", "recull"}
FILL = {"ok", "okay", "please", "pls", "now", "go", "continue", "and", "then", "also", "again", "yes", "yep", "run", "do",
        "the", "a", "full", "quick"}        # no "it" / "one" / "another": "cull it" can mean one Pokemon, not a pass
w = [x.strip(".,!;:").lstrip("/").lower() for x in p.split()]
sys.exit(0 if "?" not in p and 0 < len(w) <= 6 and GO & set(w) and all(x in GO or x in FILL for x in w) else 1)'
}

# a lock is live while its owner is alive -- two hours at most, so a recycled pid can never hold it forever -- and for its
# first 10 s before it is signed (its starter has made the directory and is about to write its pid)
running() {
  local m age p
  m=$(stat -c %Y "$LOCK" 2>/dev/null) || return 1     # no lock; it can also vanish in the middle of this check
  age=$(( $(date +%s) - m )); p=$(cat "$LOCK/pid" 2>/dev/null)
  [ -n "$p" ] || { [ "$age" -lt 10 ]; return; }
  kill -0 "$p" 2>/dev/null && [ "$age" -lt 7200 ]
}

# shortcut: two starters racing over a DEAD owner's lock in the same few milliseconds could both win; use an OS lock if
# passes are ever started by more than the hook plus one foreground call
take() {    # the lock is a directory: mkdir is atomic, so two starters of a FREE lock can never both win. A dead owner's lock is cleared once
  mkdir "$LOCK" 2>/dev/null || { running && return 1; rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null || return 1; }
  echo $$ > "$LOCK/pid"
}

detach() {  # start `--pass <the lock owner's pid>` detached from this shell; everything it prints goes to $OUT
  BASH_EXE=$(cygpath -w "$BASH" 2>/dev/null || echo "$BASH") python -c "import os, subprocess, sys; subprocess.Popen([os.environ['BASH_EXE'], 'tools/cull_now.sh', '--pass', '$1'], stdout=open(r'$OUT', 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, close_fds=True, **({'creationflags': 0x08000200} if sys.platform == 'win32' else {'start_new_session': True}))"
}

phone_row() {   # the phone's row in `tailscale status`, without the account column: 'pixel-9-pro: offline, last seen 13h ago'
  local ts; ts=$(command -v tailscale || command -v "/c/Program Files/Tailscale/tailscale.exe") || return 0
  "$ts" status 2>/dev/null | tr -d '\r' | awk -v ip="${T%%:*}" '$1 == ip { s = "Tailscale says " $2 ":"; for (i = 5; i <= NF; i++) s = s " " $i; print s }'
}

exits() {   # stdin: `dumpsys activity exit-info <package>`; $1 $2 = MM-DD HH:MM. The game's MAIN process exits since then, oldest first
  python -c '
import re, sys
since, rows, ts, pid = sys.argv[1] + " " + sys.argv[2], [], None, None
for l in sys.stdin:
    m = re.search(r"timestamp=\d{4}-(\d\d-\d\d \d\d:\d\d:\d\d)\S* pid=(\d+)", l)
    if m:
        ts, pid = m.groups()
        continue
    m = re.search(r"process=(\S+) reason=\d+ \((.*?)\) subreason=\d+ \((.*?)\) status=(\d+)", l)
    if m and ts and m.group(1) == "com.nianticlabs.pokemongo" and ts[:11] >= since:   # shortcut: MM-DD as text, like the crash filter
        note = (" -- closed by hand, not a crash" if m.group(3) == "REMOVE TASK" else " -- A CRASH" if "CRASH" in m.group(2)
                else " -- killed (signal %s)" % m.group(4) if m.group(2) == "SIGNALED" else "")
        rows.append("  %s pid %s: %s%s%s" % (ts, pid, m.group(2), "" if m.group(3) == "UNKNOWN" else " / " + m.group(3), note))
    if m:
        ts = None
print("\n".join(rows[::-1][-6:]) or "  (Android kept no exit record of the game since then)")' "$1" "$2" | tr -d '\r'
}

pass() {
  echo "start $(date '+%m-%d %H:%M:%S')"
  [ -f "$A/push.log" ] && echo "last background push: $(grep -m1 '^inventory:' "$A/push.log" || tail -1 "$A/push.log")"
  for i in $(seq 1 180); do
    adb connect "$T" > "$A/cull_now.adb" 2>&1
    adb devices | tr -d '\r' | grep -q "^$T[[:space:]]*device$" && break
    # said at once, never after silent minutes (2026-11-13: the phone's Tailscale was off and the pass waited 5 minutes unseen)
    [ "$i" -eq 1 ] && echo "PHONE OFFLINE at $(date +%H:%M:%S) -- the pass waits: adb connect $T is retried every 15 s for 45 min and it starts by itself when the phone answers. $(phone_row)"
    sleep 15
  done
  if ! adb devices | tr -d '\r' | grep -q "^$T[[:space:]]*device$"; then
    echo "PHONE STILL OFFLINE at $(date +%H:%M) -- last adb connect: $(tr -d '\r' < "$A/cull_now.adb")"; return 3
  fi
  [ "$i" -gt 1 ] && echo "phone back at $(date +%H:%M:%S)"
  # one round trip: the game's pid and age, the gadget's listener, the phone's uptime
  R=$(adb -s "$T" shell 'P=$(pidof com.nianticlabs.pokemongo); echo "pid=$P"; echo "age=$([ -n "$P" ] && ps -o ELAPSED= -p $P)"; echo "gadget=$(grep -ci :69A7 /proc/net/tcp)"; echo "up=$(cut -d" " -f1 /proc/uptime)"' | tr -d '\r')
  P=$(echo "$R" | sed -n 's/^pid=//p'); L=$(echo "$R" | sed -n 's/^gadget=//p')
  ST=$(python tools/pogo_data.py status 2>&1 | grep '^inventory '); echo "$ST"
  PV=$(echo "$ST" | grep -oE 'phone v[0-9]+' | grep -oE '[0-9]+'); HV=$(echo "$ST" | grep -oE 'here v[0-9]+' | grep -oE '[0-9]+')
  # the phone holds newer data (another session pushed, or this checkout is fresh: "here v-"): the pass runs on THAT data or
  # not at all -- keep_config.json and the registries come with it, and the pile must never be judged on stale ones
  if [ -n "$PV" ] && [ "$PV" -gt "${HV:-0}" ]; then
    echo "phone v$PV is newer than here v${HV:--} -- pulling first"; python tools/pogo_data.py pull 2>&1 | tail -3
    ST=$(python tools/pogo_data.py status 2>&1 | grep '^inventory '); echo "$ST"
    HV=$(echo "$ST" | grep -oE 'here v[0-9]+' | grep -oE '[0-9]+')
    if [ "$PV" -gt "${HV:-0}" ]; then
      echo "NOT RUN (the phone's data v$PV did not land here: here v${HV:--} -- the pull lines above say why)"; return 4
    fi
  fi
  [ -f "$LAST" ] && read -r LD LT LP < "$LAST"       # shortcut: MM-DD compares as text, wrong across New Year for one pass
  echo "game pid=$P age=$(echo "$R" | sed -n 's/^age=//p' | tr -d ' ') gadget=$L phone up $(echo "$R" | sed -n 's/^up=//p' | awk '{printf "%.1f h", $1/3600}') | last cull: ${LD:-none} ${LT:-} pid ${LP:-?} | now $(date +%H:%M:%S)"
  if [ -n "$LD" ]; then
    CR=$(adb -s "$T" shell "logcat -d -b crash | grep -E 'Process uptime|>>> com.nianticlabs.pokemongo|Abort message'" | tr -d '\r' \
      | awk -v d="$LD" -v t="$LT" '$1 > d || ($1 == d && $2 >= t)' | sed -E 's/ +[0-9]+ +[0-9]+ F DEBUG +: / /' | cut -c1-150 | tail -10)
    if [ -n "$CR" ]; then echo "--- game crashes since $LD $LT:"; echo "$CR"; else echo "--- game crashes since $LD $LT: none in the crash log"; fi
    # WHY THE GAME IS A NEW PROCESS, said here (2026-11-13): it took two more round trips to tell a swipe-away from a crash
    if [ -n "${LP:-}" ] && [ "${P:-none}" != "$LP" ]; then
      echo "--- the game is a new process since the last cull (pid $LP -> ${P:-not running}); Android's exit record:"
      adb -s "$T" shell "dumpsys activity exit-info com.nianticlabs.pokemongo" | exits "$LD" "$LT"
    fi
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
  if [ "$RC" -eq 0 ]; then
    PYTHONIOENCODING=utf-8 python bag_art.py --text > system/analysis/cull_now.page 2>&1; echo "bag_art rc=$? ($(wc -c < system/analysis/cull_now.page) bytes)"
    cat system/analysis/cull_now.page
  else    # several stop lines match none of the greps above (rc 2, 6, 7, 8, 9), and only a clean pass rebuilds the pages
    echo "--- the pass did not finish clean (rc=$RC); the end of last_cull.log:"; tail -n 12 system/analysis/last_cull.log | cut -c1-300
    echo "--- no page text: Bag Pulse still shows the PREVIOUS pass -- do not publish or quote it as this one"
  fi
  cd ..
  echo "--- pass done $(date +%H:%M:%S), $SECONDS s after the go"      # his wait up to here, measured every pass
  # ALWAYS push after a phone pass, even when the gate failed (the walk changed the data); detached, the next pass shows its result
  python -c "import subprocess, sys; subprocess.Popen([sys.executable, 'tools/pogo_data.py', 'push', '--group', 'inventory'], stdout=open(r'$A/push.log', 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, close_fds=True, **({'creationflags': 0x08000200} if sys.platform == 'win32' else {'start_new_session': True}))" \
    && echo "--- data push started in the background (the next pass shows its result)"
  return $RC
}

# self-check only: the lock, detach and attach paths with no phone and no pass
[ -n "${CULL_NOW_DRY:-}" ] && pass() { echo "start dry"; sleep "$CULL_NOW_DRY"; echo "--- full_audit starting"; echo "rc=0"; }

show() {    # wait for the running pass, print what it wrote, and mark it read
  while running; do
    # A PASS THAT WAITS FOR THE PHONE IS REPORTED AT ONCE (2026-11-13). It keeps waiting, starts by itself, and its result
    # stays unread for the next call; --wait sits the wait out instead.
    if [ -z "$WAIT" ] && tail -n 1 "$OUT" 2>/dev/null | grep -q '^PHONE OFFLINE'; then
      cat "$OUT"
      echo "THE PASS IS STILL WAITING FOR THE PHONE -- nothing has run. Tell Benny now what the line above says is off, then run \`bash tools/cull_now.sh --wait\` (background): it prints the pass when it ends."
      return 3
    fi
    sleep 1
  done
  cat "$OUT"; rm -f "$UNREAD"
  grep -q '^--- full_audit starting' "$OUT" && ! grep -q '^rc=' "$OUT" && { echo "PASS DIED MID-RUN (no rc line) -- NOT retried: read $A/last_cull.log first"; return 7; }
  return "$(sed -n 's/^rc=//p' "$OUT" | tail -1 | grep -E '^[0-9]+$' || echo 1)"
}

WAIT=; [ "${1:-}" = "--wait" ] && { WAIT=1; shift; }
case "${1:-}" in
  --selfcheck)
    for s in 'cull' 'Cull.' 'Continue. Cull.' 'cull again' 'recull' '/cull' 'ok cull now' 'do a full cull' 'run the cull please'; do
      printf '{"prompt": "%s"}' "$s" | is_go || { echo "selfcheck FAILED: should start: $s"; exit 1; }
    done
    for s in 'cull?' 'dont cull' 'do not cull yet' 'why did the cull fail' 'A1 A2 cull' 'cull later' 'stop the cull' 'go' '' \
             'fix X then cull' 'cull\nbut first read this' 'cull the Scyther' 'cull it' 'cull another one'; do
      printf '{"prompt": "%s"}' "$s" | is_go && { echo "selfcheck FAILED: should NOT start: $s"; exit 1; }
    done
    export CULL_NOW_STATE=pogo_extract/system/analysis/.cull_now_selfcheck.$$ CULL_NOW_DRY=3; mkdir -p "$CULL_NOW_STATE"
    bad() { echo "selfcheck FAILED: $1"; rm -rf "$CULL_NOW_STATE"; exit 1; }
    H=$(printf '{"prompt": "cull"}' | bash tools/cull_now.sh --hook); case "$H" in *"started ONE cull pass"*) ;; *) bad "the hook did not start a pass: $H" ;; esac
    H=$(printf '{"prompt": "cull"}' | bash tools/cull_now.sh --hook); case "$H" in *"ALREADY running"*) ;; *) bad "a second go started a second pass: $H" ;; esac
    O=$(bash tools/cull_now.sh); case "$O" in *attached*"start dry"*"rc=0"*) ;; *) bad "the foreground call did not attach: $O" ;; esac
    [ -e "$CULL_NOW_STATE/cull_now.lock" ] || [ -e "$CULL_NOW_STATE/cull_now.unread" ] && bad "state left behind after the pass"
    O=$(bash tools/cull_now.sh --pass 1); case "$O" in *"NOTHING was run"*) ;; *) bad "--pass ran without its hook's lock: $O" ;; esac
    O=$(bash tools/cull_now.sh); case "$O" in "start dry"*"rc=0"*) ;; *) bad "a plain foreground pass: $O" ;; esac
    printf '{"prompt": "cull"}' | bash tools/cull_now.sh --hook > /dev/null; sleep 6
    O=$(bash tools/cull_now.sh); case "$O" in *"already ran"*"s ago"*"rc=0"*) ;; *) bad "a finished hook pass was not picked up: $O" ;; esac
    O=$(bash tools/cull_now.sh); case "$O" in "start dry"*) ;; *) bad "a read pass was shown twice: $O" ;; esac
    # a pass that waits for the phone: the plain call says so at once (rc 3) and leaves it waiting and unread; --wait sits it out
    mkdir -p "$CULL_NOW_STATE/cull_now.lock"; sleep 5 & echo $! > "$CULL_NOW_STATE/cull_now.lock/pid"
    printf 'start dry\nPHONE OFFLINE at 00:00:00 -- the pass waits\n' > "$CULL_NOW_STATE/cull_now.out"; date +%s > "$CULL_NOW_STATE/cull_now.unread"
    O=$(bash tools/cull_now.sh); [ $? -eq 3 ] || bad "an attach to a pass that waits for the phone did not return 3: $O"
    case "$O" in *"PHONE OFFLINE"*"STILL WAITING FOR THE PHONE"*) ;; *) bad "the offline attach did not say so: $O" ;; esac
    [ -e "$CULL_NOW_STATE/cull_now.unread" ] || bad "the offline attach marked the waiting pass read"
    O=$(bash tools/cull_now.sh --wait); case "$O" in *"STILL WAITING"*) bad "--wait did not sit out the wait: $O" ;; esac
    kill -0 $! 2>/dev/null && bad "--wait returned while the pass was still running"
    rm -rf "$CULL_NOW_STATE/cull_now.lock" "$CULL_NOW_STATE/cull_now.unread"
    # the exit-record reader: the main process only, since the given time, oldest first, a swipe-away told from a crash
    E=$(printf '%s\n' 'ApplicationExitInfo #0:' ' timestamp=2026-11-12 13:40:22.940 pid=29076 realUid=1 user=0' \
          ' process=com.nianticlabs.pokemongo:pgp reason=2 (SIGNALED) subreason=0 (UNKNOWN) status=9' 'ApplicationExitInfo #1:' \
          ' timestamp=2026-11-12 13:40:21.579 pid=29205 realUid=1 user=0' \
          ' process=com.nianticlabs.pokemongo reason=10 (USER REQUESTED) subreason=22 (REMOVE TASK) status=0' 'ApplicationExitInfo #2:' \
          ' timestamp=2026-11-12 12:51:07.073 pid=15735 realUid=1 user=0' \
          ' process=com.nianticlabs.pokemongo reason=5 (APP CRASH(NATIVE)) subreason=0 (UNKNOWN) status=11' 'ApplicationExitInfo #3:' \
          ' timestamp=2026-11-12 09:00:00.000 pid=111 realUid=1 user=0' \
          ' process=com.nianticlabs.pokemongo reason=2 (SIGNALED) subreason=0 (UNKNOWN) status=9' | exits 11-12 12:00)
    [ "$E" = "  11-12 12:51:07 pid 15735: APP CRASH(NATIVE) -- A CRASH
  11-12 13:40:21 pid 29205: USER REQUESTED / REMOVE TASK -- closed by hand, not a crash" ] || bad "the exit-record reader: $E"
    [ "$(echo x | exits 11-12 12:00)" = "  (Android kept no exit record of the game since then)" ] || bad "the exit-record reader on no record"
    rm -rf "$CULL_NOW_STATE"
    echo "cull_now self-check OK"; exit 0 ;;
  --hook)
    IN=$(cat); case "${IN,,}" in *cull*) ;; *) exit 0 ;; esac
    printf '%s' "$IN" | is_go || exit 0
    if take; then
      date +%s > "$UNREAD"; : > "$OUT"
      detach $$ || { rm -rf "$LOCK" "$UNREAD"; exit 0; }
      for i in $(seq 1 50); do [ "$(cat "$LOCK/pid" 2>/dev/null)" != "$$" ] && break; sleep 0.1; done   # the pass owns the lock now
      echo "cull_now: the hook started ONE cull pass at $(date +%H:%M:%S) for this message. Do not start another: run \`bash tools/cull_now.sh\` (background) -- it attaches to this pass and prints its output."
    elif running; then
      echo "cull_now: this go is covered by the cull pass that is ALREADY running ($(head -1 "$OUT" 2>/dev/null)). Do not start another pass for this message: if that pass's output was already read in this conversation, report from it; else run \`bash tools/cull_now.sh\` once (background) to attach."
    fi
    exit 0 ;;
  --pass)       # the detached pass a hook started: it takes over THAT hook's lock ($2 = the hook's pid), or it does nothing
    [ -n "${2:-}" ] && [ "$(cat "$LOCK/pid" 2>/dev/null)" = "$2" ] || { echo "--pass is the hook's own entry (its lock is gone or taken) -- NOTHING was run"; exit 2; }
    echo $$ > "$LOCK/pid"; pass; RC=$?; grep -q '^rc=' "$OUT" || echo "rc=$RC"
    [ -f "$UNREAD" ] && date +%s > "$UNREAD"      # the 15 minutes to read this result start when the pass ENDS
    rm -rf "$LOCK"; exit $RC ;;
  '')
    if running; then echo "(attached to the pass that is already running)"; show; exit $?; fi
    U=$(grep -m1 -E '^[0-9]+$' "$UNREAD" 2>/dev/null)
    if [ -n "$U" ] && [ $(( $(date +%s) - U )) -lt 900 ]; then
      if grep -qE '^--- full_audit starting|^rc=' "$OUT"; then echo "(this pass already ran; it ended $(( $(date +%s) - U )) s ago)"; show; exit $?; fi
      echo "(the hook's pass never got going -- starting it here)"; cat "$OUT"
    fi
    rm -f "$UNREAD"
    take || { running || { echo "cull_now: could not take $LOCK and no pass owns it -- NOTHING was run"; exit 1; }
              echo "(attached to the pass that just started)"; show; exit $?; }
    # detached here too (2026-11-13), like the hook's: a wait for the phone is reported at once and the pass still starts by itself
    date +%s > "$UNREAD"; : > "$OUT"
    detach $$ || { rm -rf "$LOCK" "$UNREAD"; echo "cull_now: could not start the pass -- NOTHING was run"; exit 1; }
    for i in $(seq 1 50); do [ "$(cat "$LOCK/pid" 2>/dev/null)" != "$$" ] && break; sleep 0.1; done   # the pass owns the lock now
    show; exit $? ;;
  *) echo "usage: bash tools/cull_now.sh [--wait | --hook | --selfcheck]   (unknown: $1 -- NOTHING was run)"; exit 2 ;;
esac
