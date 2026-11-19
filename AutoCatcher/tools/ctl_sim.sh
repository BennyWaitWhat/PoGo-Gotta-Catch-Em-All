#!/usr/bin/env bash
# Offline test of AutoCatcher/catcher_ctl.sh (no phone):   bash AutoCatcher/tools/ctl_sim.sh [another catcher_ctl.sh]
# The script runs in a sandbox: its phone paths point into a temp folder; am / su / pkill / sleep / python are stubs
# that only write down what they were asked; ps prints a made-up process list. Every verb's process work is counted
# call by call, and each rule of the reward run (NEVER TWO GAME CLIENTS in the script) is one case here.
# Exit code 1 when any check fails. VERBOSE=1 prints the calls of every run.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="${1:-$HERE/../catcher_ctl.sh}"
SB="$(mktemp -d)"; export SB
case "$SB" in /*) [ -d "$SB" ] || exit 1 ;; *) echo "no temp folder" >&2; exit 1 ;; esac   # every path below hangs off it
trap 'rm -rf "$SB"' EXIT
mkdir -p "$SB/tmp" "$SB/termux/usr/bin" "$SB/termux/home/pogo/system/analysis/pokemod" "$SB/termux/home/pogo/system/scripts/game_write"
export CALLS="$SB/calls.log" ORDER="$SB/order.log"
P="$SB/termux/home/pogo"; MARK="$P/.reward.run"; LOCKD="$P/.ctl.lock"; FLOG="$P/system/analysis/pokemod/flags.log"
B="$SB/termux/usr/bin"

# ---- the stubs -------------------------------------------------------------------------------------------------------
cat > "$B/am" <<'EOF'
#!/bin/bash
M="$SB/termux/home/pogo/.reward.run"; L="$SB/termux/home/pogo/.ctl.lock"
m=no; [ -d "$M" ] && m=yes
echo "am $*" >> "$CALLS"; echo "am $(echo "$*" | grep -oE 'run_(catch|gym)\.sh' | head -n 1) marker=$m" >> "$ORDER"
a=none; [ -d "$L" ] && a=$(( $(date +%s) - $(date -r "$L" +%s) )); [ -f "$L" ] && a=file
echo "$a" > "$SB/lock_at_am.txt"   # how old the lock is when a supervisor is started
if [ -f "$SB/marker_on_am" ]; then rm -f "$SB/marker_on_am"; mkdir -p "$M"; fi   # another run makes its marker right now
if [ -f "$SB/am_works" ]; then     # the supervisor it was asked to start is alive from now on
  case "$*" in
    *run_gym.sh*)   echo "u0_a762  5151  1  0 15:00 ?  00:00:01 bash $SB/termux/home/pogo/run_gym.sh" >> "$SB/ps.txt" ;;
    *run_catch.sh*) echo "u0_a762  4242  1  0 15:00 ?  00:00:01 bash $SB/termux/home/pogo/run_catch.sh" >> "$SB/ps.txt" ;;
  esac
fi
exit 0
EOF
cat > "$B/su" <<'EOF'
#!/bin/bash
echo "su $*" >> "$CALLS"
exit 0
EOF
cat > "$B/pkill" <<'EOF'
#!/bin/bash
echo "pkill $*" >> "$CALLS"; echo "pkill" >> "$ORDER"
if [ -f "$SB/pkill_works" ]; then   # what it was asked to end is gone from now on
  case "$*" in
    *run_catch*)   grep -v 'run_catch\.sh' "$SB/ps.txt" > "$SB/ps.tmp"; mv "$SB/ps.tmp" "$SB/ps.txt" ;;
    *catch_phone*) grep -v 'catch_phone\.py' "$SB/ps.txt" > "$SB/ps.tmp"; mv "$SB/ps.tmp" "$SB/ps.txt" ;;
  esac
fi
exit 0
EOF
cat > "$B/ps" <<'EOF'
#!/bin/bash
M="$SB/termux/home/pogo/.reward.run"
if [ -f "$SB/marker_on_ps" ]; then rm -f "$SB/marker_on_ps"; mkdir -p "$M"; fi         # another tap makes its marker right now
if [ -f "$SB/marker_off_ps" ]; then rm -f "$SB/marker_off_ps"; rmdir "$M" 2>/dev/null; fi   # the run ends right now
cat "$SB/ps.txt" 2>/dev/null
exit 0
EOF
cat > "$B/sleep" <<'EOF'
#!/bin/bash
M="$SB/termux/home/pogo/.reward.run"
a=none; [ -d "$M" ] && a=$(( $(date +%s) - $(date -r "$M" +%s) ))
echo "sleep $*" >> "$SB/sleeps.log"; echo "sleep $*" >> "$ORDER"; echo "$* $a" >> "$SB/sleep_marker.log"   # the marker's age during each wait
if [ -f "$SB/marker_on_sleep" ]; then rm -f "$SB/marker_on_sleep"; mkdir -p "$M"; fi   # a reward run starts while this verb waits
if [ -f "$SB/tap_on_sleep" ]; then v=$(cat "$SB/tap_on_sleep"); rm -f "$SB/tap_on_sleep"; bash "$SB/ctl.sh" $v > /dev/null 2>&1; fi   # a tap during this wait
exit 0
EOF
cat > "$B/python3.14" <<'EOF'
#!/bin/bash
M="$SB/termux/home/pogo/.reward.run"; L="$SB/termux/home/pogo/.ctl.lock"
m=no; [ -d "$M" ] && m=yes
echo "python $* marker=$m" >> "$CALLS"; echo "python marker=$m" >> "$ORDER"
echo "u0_a762  6161  6100  1 16:06 ?  00:00:00 python3.14 $1" >> "$SB/ps.txt"   # alive for as long as this stub runs
trap 'grep -v "reward_phone\.py" "$SB/ps.txt" > "$SB/ps.tmp"; mv "$SB/ps.tmp" "$SB/ps.txt"' EXIT
[ -f "$SB/py_hook.sh" ] && . "$SB/py_hook.sh"
exit 0
EOF
chmod +x "$B"/*
sed -e "s#/data/local/tmp#$SB/tmp#g" \
    -e "s#/data/data/com.termux/files/usr#$SB/termux/usr#g" \
    -e "s#/data/data/com.termux/files/home#$SB/termux/home#g" \
    -e 's#^export PATH=.*#export PATH="$PREFIX/bin:$ORIG_PATH"#' "$SRC" > "$SB/ctl.sh"
export ORIG_PATH="$PATH"

# ---- helpers ---------------------------------------------------------------------------------------------------------
GYMRUN="$P/run_gym.sh"
RWSTAT="$SB/tmp/pogo_rewards.txt"
CATCHER_PS="u0_a762  4242  1  0 15:00 ?  00:00:01 bash $P/run_catch.sh
u0_a762  4243  4242  5 15:00 ?  00:01:01 python3.14 catch_phone.py"
GYM_PS="u0_a762  5151  1  0 15:00 ?  00:00:01 bash $P/run_gym.sh
u0_a762  5152  5151  5 15:00 ?  00:01:01 python3.14 tools/gym_run.py --on-open"
RUNNER_PS="u0_a762  5152  1  5 15:00 ?  00:01:01 python3.14 tools/gym_run.py --on-open"
PREFLIGHT_PS="u0_a762  5300  5200  0 16:51 ?  00:00:00 bash $P/run_gym.sh --preflight
u0_a762  5301  5300  9 16:51 ?  00:00:02 python3.14 -u tools/gym_run.py --on-open --preflight --no-feed"
REWARD_PS="u0_a762  6161  6100  1 16:06 ?  00:00:00 python3.14 $P/system/scripts/game_write/reward_phone.py"
FULL="pkill|pkill|sleep 5|python marker=yes|sleep 5|am run_catch.sh marker=no|sleep 2|"   # a whole reward run, catcher on
fail=0; checks=0
ok() { checks=$((checks+1)); echo "   ok   $1"; }
bad() { checks=$((checks+1)); fail=1; echo "   FAIL $1"; sed -e "s#$SB#<sb>#g" -e 's/^/        call: /' "$CALLS" | cut -c1-220; sed -e "s#$SB#<sb>#g" -e 's/^/        log:  /' "$FLOG" | cut -c1-220; }
is() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1: got [$2], wanted [$3]"; fi; }   # is <label> <got> <want>
flags() {   # flags catch spin perfect tap apples gym berries
  local k=0 n val
  for n in catch spin perfect tap apples gym berries; do k=$((k+1)); eval "val=\${$k}"; printf '%s\n' "$val" > "$SB/tmp/pogo_$n.on"; done
  : > "$SB/tmp/pogo_state.txt"
}
flag() { tr -d '[:space:]' < "$SB/tmp/pogo_$1.on"; }
count() { wc -l < "$1" | tr -d ' '; }
ps_is() { if [ $# = 0 ]; then : > "$SB/ps.txt"; else printf '%s\n' "$@" > "$SB/ps.txt"; fi; }
clean() {   # nothing left over from the case before
  rmdir "$LOCKD" "$MARK" 2>/dev/null; rm -rf "$LOCKD" "$MARK" "$RWSTAT"
  rm -f "$SB"/pkill_works "$SB"/am_works "$SB"/py_hook.sh "$SB"/marker_on_sleep "$SB"/marker_on_ps "$SB"/marker_off_ps "$SB"/marker_on_am "$SB"/tap_on_sleep
  : > "$FLOG"
}
mark() { mkdir -p "$MARK"; touch -d "@$(( $(date +%s) - $1 ))" "$MARK"; }   # mark <seconds old>
said() { sed 's/ @ [0-2][0-9]:[0-5][0-9]:[0-5][0-9]$//' "$RWSTAT" 2>/dev/null; }   # the app's line without its clock time
quiet() {   # run one verb: out / rc hold what it printed and returned
  : > "$CALLS"; : > "$ORDER"; : > "$SB/sleeps.log"; : > "$SB/sleep_marker.log"; echo unset > "$SB/lock_at_am.txt"
  out=$(bash "$SB/ctl.sh" "$@" 2>&1); rc=$?
  if [ -n "${VERBOSE:-}" ]; then echo "     verb=$* exit=$rc${out:+ out=[$out]}"; sed -e "s#$SB#<sb>#g" -e 's/^/     call: /' "$CALLS" | cut -c1-220; fi
}
expect() { n=$(grep -cE "$3" "$CALLS"); if [ "$n" = "$2" ]; then ok "$1"; else bad "$1: wanted $2 x /$3/, got $n"; fi; }   # expect <label> <count> <pattern>
total() { n=$(count "$CALLS"); if [ "$n" = "$2" ]; then ok "$1"; else bad "$1: wanted $2 calls in all, got $n"; fi; }
logged() { if grep -qE "$2" "$FLOG"; then ok "$1"; else bad "$1: no flags.log line /$2/"; fi; }
order() { is "$1" "$(tr '\n' '|' < "$ORDER")" "$2"; }
nothing_left() { if [ ! -e "$MARK" ] && [ ! -e "$LOCKD" ]; then ok "$1"; else bad "$1: left $(ls -ld "$MARK" "$LOCKD" 2>/dev/null | tr '\n' ' ')"; fi; }
clean

echo "== the gym verbs, the boot hook, the flag-only verbs (as before)"
# A. gym-on, no run_gym.sh on the phone yet: the flag is written, nothing is started, exit 0
clean; flags 1 1 0 0 1 0 pinap; rm -f "$GYMRUN"; ps_is "$CATCHER_PS"; quiet gym-on
total "A gym-on with no run_gym.sh on the phone: no call at all" 0; is "A flag and exit" "$(flag gym)|$rc" "1|0"
# B. gym-on, run_gym.sh there, no supervisor alive: exactly one start, of run_gym.sh, and nothing else
clean; flags 1 1 0 0 1 0 pinap; echo '#!/bin/bash' > "$GYMRUN"; ps_is "$CATCHER_PS"; quiet gym-on
expect "B gym-on: one am start of run_gym.sh" 1 "^am startservice .*RUN_COMMAND_ARGUMENTS [^ ]*/run_gym\.sh "; total "B nothing else" 1
# C. gym-on, supervisor already alive: no second start
clean; ps_is "$CATCHER_PS" "$GYM_PS"; quiet gym-on; total "C gym-on with the supervisor alive: no call at all" 0
# D. gym-off with the gym runner alive: the flag is written and NOTHING else (no pkill, no kill, no am)
clean; flags 1 1 0 0 1 1 pinap; quiet gym-off; total "D gym-off: no call at all" 0; is "D flag" "$(flag gym)" 0
# E. the boot hook with catch on (catcher alive) and gym on, supervisor not alive: starts run_gym.sh, leaves the catcher
clean; flags 1 0 0 0 0 1 pinap; ps_is "$CATCHER_PS"; quiet reconcile
expect "E boot hook: one am start of run_gym.sh" 1 "run_gym\.sh"; total "E nothing else" 1
# F. the boot hook, every catcher switch off, gym on and alive: the catcher's stop names only its own two processes
clean; flags 0 0 0 0 0 1 0; ps_is "$GYM_PS"; quiet reconcile
expect "F pkill run_catch.sh" 1 '^pkill -TERM -f run_catch\\\.sh$'; expect "F pkill catch_phone.py" 1 '^pkill -TERM -f catch_phone\.py$'
expect "F no -9 (the gym processes do not count as the catcher)" 0 "pkill -9"; expect "F nothing names gym" 0 "gym"; total "F two calls" 2
# G. catch-off with gym on, supervisor NOT alive: an off verb of the catcher never starts the gym runner
clean; flags 1 0 0 0 0 1 pinap; ps_is "$CATCHER_PS"; quiet catch-off; expect "G catch-off: nothing names gym" 0 "gym"
# H. the boot hook with gym off: exit 0, no gym start
clean; flags 1 0 0 0 0 0 pinap; ps_is "$CATCHER_PS"; quiet reconcile; total "H boot hook, gym off: no call at all" 0; is "H exit" "$rc" 0
# J. running() is blind to the gym processes: with ONLY gym processes alive, catch-on must still start run_catch.sh
clean; flags 0 0 0 0 0 1 pinap; ps_is "$GYM_PS"; quiet catch-on
expect "J catch-on: am start of run_catch.sh" 1 "RUN_COMMAND_ARGUMENTS [^ ]*/run_catch\.sh "; expect "J nothing names gym" 0 "gym"
# K. berries verbs: the flag only
clean; flags 1 1 0 0 1 0 1; ps_is "$CATCHER_PS"
for v in berries-off:0 berries-pinap:pinap berries-razz:razz berries-on:1; do
  quiet "${v%%:*}"; is "K ${v%%:*}: the flag, no call" "$(flag berries)|$(count "$CALLS")" "${v##*:}|0"
done
# S. status: read only
clean; flags 1 1 0 0 1 0 pinap; rm -f "$SB/tmp/pogo_dust.on"; ps_is "$CATCHER_PS"; quiet status; total "S status: no call at all" 0
is "S line (no dust file = 0)" "$out" "proc=up catch=1 spin=1 perfect=0 tap=0 apples=1 gym=0 berries=pinap dust=0"
# L. Stardust-only verbs: the flag only, a whole number only
clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS"; echo 0 > "$SB/tmp/pogo_dust.on"
for v in dust-500:500 dust-off:0 dust-on:1 dust-1000:1000 dust-abc:1000 dust-:1000 dust-99999999:1000 dust-5x:1000 dust-007:7 dust-700:700; do
  quiet "${v%%:*}"; is "L ${v%%:*}: the file, no call" "$(flag dust)|$(count "$CALLS")|$rc" "${v##*:}|0|0"
done
quiet status; is "L status says dust=700" "$out" "proc=up catch=1 spin=1 perfect=0 tap=0 apples=1 gym=0 berries=pinap dust=700"
echo junk > "$SB/tmp/pogo_dust.on"; quiet status; is "L a file that is not a number reads as 0" "${out##* }" "dust=0"
clean; flags 0 0 0 0 0 0 0; ps_is; echo 0 > "$SB/tmp/pogo_dust.on"; quiet dust-500; total "L dust-500 with everything off: no call (a dust verb starts nothing)" 0
# R. Reset counters (app 1.7): the tap's time goes into the request file, and nothing else happens
REQ="$SB/tmp/pogo_counters.req"
clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS"; rm -f "$REQ"; t1=$(date +%s); quiet counters-reset; t2=$(date +%s)
r=$(tr -d '[:space:]' < "$REQ" 2>/dev/null)
case "$r" in ''|*[!0-9]*) bad "R counters-reset: wanted the time in the request file, got [$r]" ;;
  *) if [ "$r" -ge "$t1" ] && [ "$r" -le "$t2" ]; then ok "R counters-reset: the tap's time in the request file"; else bad "R counters-reset: time $r not in $t1..$t2"; fi ;; esac
total "R counters-reset: no call at all (it starts, stops and switches nothing)" 0
is "R exit, and Catch / Spin / Gym / berries as they were" "$rc|$(flag catch)$(flag spin)$(flag gym)|$(flag berries)" "0|110|pinap"
logged "R flags.log names the verb" "counters-reset: pogo_counters\.req  -> [0-9]+ \(verb=counters-reset "
echo 1700000000 > "$REQ"; quiet counters-reset; r=$(tr -d '[:space:]' < "$REQ")
is "R a second tap writes a newer time (the catcher carries out each new time once)" "$([ "$r" -gt 1700000000 ] && echo newer)|$(count "$CALLS")" "newer|0"
logged "R ... logged old -> new" "counters-reset: pogo_counters.req 1700000000 -> $r "
clean; flags 0 0 0 0 0 0 0; ps_is; quiet counters-reset; total "R counters-reset with every switch off and no catcher: no call (it starts nothing)" 0
quiet bogus-verb; is "R the usage line lists it" "$(echo "$out" | grep -c '|counters-reset|')" 1

echo "== N: no reward run in flight, each verb does its process work"
for v in catch-on spin-on perfect-on tap-on apples-on start restart; do
  clean; flags 0 0 0 0 0 0 0; case "$v" in restart) echo 1 > "$SB/tmp/pogo_catch.on" ;; esac; ps_is "$CATCHER_PS"; : > "$SB/pkill_works"; quiet "$v"
  n=$(grep -c "^pkill -TERM" "$CALLS"); a=$(grep -c "^am " "$CALLS")
  if [ "$n" -ge 1 ] && [ "$a" = 1 ] && [ ! -e "$LOCKD" ] && ! grep -q "in flight" "$FLOG"; then ok "N $v: the catcher is restarted, the lock given back"; else bad "N $v: pkill=$n am=$a"; fi
done
for v in catch-off spin-off perfect-off tap-off apples-off stop; do
  clean; flags 0 0 0 0 0 0 0; ps_is "$CATCHER_PS"; quiet "$v"
  n=$(grep -c "^pkill -TERM" "$CALLS"); if [ "$n" -ge 1 ] && [ ! -e "$LOCKD" ]; then ok "N $v: everything off, the catcher is stopped"; else bad "N $v: pkill=$n"; fi
done
clean; flags 1 0 0 0 0 0 0; ps_is "$CATCHER_PS"; quiet toggle
is "N toggle: the flag flips, the catcher is stopped" "$(flag catch)|$(grep -c '^pkill -TERM' "$CALLS")" "0|2"
clean; flags 1 0 0 0 0 0 0; ps_is "$CATCHER_PS"; quiet catch-off
logged "N the log line of a flag change names its verb" "catch-off: pogo_catch.on 1 -> 0 \(verb=catch-off pid=[0-9]+\)"
clean; flags 1 0 0 0 0 1 0; echo '#!/bin/bash' > "$GYMRUN"; ps_is; : > "$SB/am_works"; quiet reconcile
order "N the boot hook starts each supervisor whose switch is on" "am run_catch.sh marker=no|sleep 2|am run_gym.sh marker=no|"

echo "== R1: a whole reward run; during it he switches Spin on and Catch off and taps Catch Rewards again"
clean; flags 1 0 0 0 0 0 pinap; ps_is "$CATCHER_PS"; : > "$SB/pkill_works"; : > "$SB/am_works"; echo "done: old" > "$RWSTAT"
cat > "$SB/py_hook.sh" <<'EOF'
cat "$SB/tmp/pogo_rewards.txt" > "$SB/status_during_run.txt"
[ -d "$L" ] && echo yes > "$SB/lock_during_run.txt" || echo no > "$SB/lock_during_run.txt"
touch -d "@$(( $(date +%s) - 100 ))" "$M"   # the run has been going for a while
touch -d "@$(( $(date +%s) - 300 ))" "$L"
wc -l < "$CALLS" | tr -d ' ' > "$SB/calls_before_taps.txt"
bash "$SB/ctl.sh" spin-on > /dev/null 2>&1
bash "$SB/ctl.sh" catch-off > /dev/null 2>&1
bash "$SB/ctl.sh" rewards > /dev/null 2>&1
wc -l < "$CALLS" | tr -d ' ' > "$SB/calls_after_taps.txt"
echo perfect-on > "$SB/tap_on_sleep"        # and one more tap while the run waits out its last seconds
EOF
quiet rewards
order "R1 order: catcher parked, gap, reward catcher with the marker there, gap, marker gone, catcher started" "$FULL"
total "R1 four calls: two TERMs, one reward catcher, one catcher start" 4
expect "R1 the reward catcher ran once" 1 "^python .*reward_phone\.py"
expect "R1 no kill -9" 0 "pkill -9"
is "R1 the app's line during the run" "$(cut -c1-7 "$SB/status_during_run.txt")" "queued "
is "R1 it held the lock during the run" "$(cat "$SB/lock_during_run.txt")" yes
is "R1 the three taps during the run made no call" "$(cat "$SB/calls_after_taps.txt")" "$(cat "$SB/calls_before_taps.txt")"
is "R1 Spin on, Catch off, Perfect on: the flags stay as he set them (nothing is restored)" "$(flag spin)|$(flag catch)|$(flag perfect)" "1|0|1"
logged "R1 spin-on during the run: one line" "spin-on: reward run in flight: flag only -- the catcher starts or stops by the flags when it ends \(verb=spin-on "
logged "R1 catch-off during the run: one line" "catch-off: reward run in flight: flag only"
logged "R1 perfect-on in its last seconds: flag only too" "perfect-on: reward run in flight: flag only"
logged "R1 a second rewards tap during the run: refused" "rewards: a reward run is in flight, this tap does nothing \(verb=rewards "
a1=$(sed -n '1p' "$SB/sleep_marker.log"); a2=$(grep '^5 ' "$SB/sleep_marker.log" | sed -n '2p')
case "$a1" in "5 "[0-5]) ok "R1 the marker is there while the catcher is being parked ($a1 s)";; *) bad "R1 first gap: [$a1]";; esac
case "$a2" in "5 "[0-5]) ok "R1 the marker is young again for the last gap (100 s old before it)";; *) bad "R1 last gap: [$a2]";; esac
case "$(cat "$SB/lock_at_am.txt")" in [0-5]) ok "R1 the lock is young again when the catcher is started (300 s old before it)";; *) bad "R1 lock at the start of the catcher: $(cat "$SB/lock_at_am.txt")";; esac
nothing_left "R1 marker and lock are gone at the end"; is "R1 exit" "$rc" 0
clean; flags 0 0 0 0 0 0 pinap; ps_is; quiet rewards --dry
expect "R1 rewards --dry hands --dry to the reward catcher" 1 "^python .*reward_phone\.py --dry marker=yes$"

echo "== R2: a run is in flight and still parking the catcher (marker 5 s old, no reward_phone.py yet)"
for v in catch-on:catch:1 catch-off:catch:0 spin-on:spin:1 spin-off:spin:0 perfect-on:perfect:1 perfect-off:perfect:0 tap-on:tap:1 tap-off:tap:0 apples-on:apples:1 apples-off:apples:0 gym-on:gym:1 start:catch:1 stop:catch:0 toggle:catch:0 restart:catch:1 reconcile:catch:1; do
  verb=${v%%:*}; rest=${v#*:}; f=${rest%%:*}; want=${rest##*:}
  clean; flags 1 1 1 1 1 0 pinap; case "$verb" in *-on|start) echo 0 > "$SB/tmp/pogo_$f.on" ;; esac
  echo '#!/bin/bash' > "$GYMRUN"; ps_is "$CATCHER_PS"; mark 5; quiet "$verb"
  l=$(grep -c "$verb: reward run in flight: flag only" "$FLOG")
  if [ "$(flag "$f")" = "$want" ] && [ "$(count "$CALLS")" = 0 ] && [ "$(count "$SB/sleeps.log")" = 0 ] && [ "$l" = 1 ] && [ ! -e "$LOCKD" ] && [ -d "$MARK" ] && [ "$rc" = 0 ]; then
    ok "R2 $verb: flag $f=$want, no call, no wait, one log line, lock and marker untouched"
  else bad "R2 $verb: flag=$(flag "$f") calls=$(count "$CALLS") sleeps=$(count "$SB/sleeps.log") lines=$l rc=$rc"; fi
done
clean; flags 1 1 0 0 1 0 pinap; mark 5; quiet stop; is "R2 stop also writes spin=0" "$(flag spin)" 0
clean; flags 0 0 0 0 0 0 0; echo '#!/bin/bash' > "$GYMRUN"; ps_is; mark 5; quiet gym-on
logged "R2 gym-on says the gym runner starts at the end" "gym-on: reward run in flight: flag only -- the gym runner starts when it ends"
for a in "" "--dry"; do
  clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS"; mark 5; echo "queued 16:06:09" > "$RWSTAT"; quiet rewards $a
  if [ "$(count "$CALLS")" = 0 ] && [ "$(count "$SB/sleeps.log")" = 0 ] && [ "$rc" = 0 ] && [ "$(cat "$RWSTAT")" = "queued 16:06:09" ] && [ -d "$MARK" ] && grep -q "a reward run is in flight, this tap does nothing" "$FLOG"; then
    ok "R2 rewards $a: nothing at all (no park, no second reward catcher, the run's line untouched, logged)"
  else bad "R2 rewards $a: calls=$(count "$CALLS") sleeps=$(count "$SB/sleeps.log") rc=$rc"; fi
done
clean; flags 1 1 0 0 1 1 pinap; ps_is "$CATCHER_PS"; mark 5; echo "queued 16:06:09" > "$RWSTAT"; quiet rewards
is "R2 rewards during a run, Gym switched on meanwhile: still nothing, the run's line is not replaced" "$(count "$CALLS")|$(cat "$RWSTAT")" "0|queued 16:06:09"
for v in gym-off:gym:0 berries-razz:berries:razz dust-700:dust:700; do
  verb=${v%%:*}; rest=${v#*:}; f=${rest%%:*}; want=${rest##*:}
  clean; flags 1 1 0 0 1 1 pinap; echo 0 > "$SB/tmp/pogo_dust.on"; mark 5; quiet "$verb"
  if [ "$(flag "$f")" = "$want" ] && [ "$(count "$CALLS")" = 0 ] && [ "$(count "$SB/sleeps.log")" = 0 ] && ! grep -q "in flight" "$FLOG"; then ok "R2 $verb: its flag as always, and no wait for the lock"; else bad "R2 $verb: flag=$(flag "$f")"; fi
done
clean; flags 1 1 0 0 1 0 pinap; echo 0 > "$SB/tmp/pogo_dust.on"; ps_is "$CATCHER_PS"; mark 5; mkdir "$LOCKD"; quiet status
is "R2 status during a run: its line, at once" "$out|$(count "$SB/sleeps.log")" "proc=up catch=1 spin=1 perfect=0 tap=0 apples=1 gym=0 berries=pinap dust=0|0"
if [ -d "$LOCKD" ]; then ok "R2 status leaves the run's lock alone"; else bad "R2 status removed the lock"; fi

echo "== R3-R5: when a marker counts"
clean; flags 0 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$REWARD_PS"; mark 40; quiet catch-on
is "R3 marker 40 s + reward_phone.py alive = in flight: catch-on is flag only" "$(count "$CALLS")|$(flag catch)|$(ls -d "$MARK" | wc -l | tr -d ' ')" "0|1|1"
quiet rewards; is "R3 ... and rewards does nothing" "$(count "$CALLS")|$(ls -d "$MARK" | wc -l | tr -d ' ')" "0|1"
clean; flags 0 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$REWARD_PS"; mark 880; quiet catch-on
is "R3 marker 14 min 40 s + reward_phone.py alive = still in flight" "$(count "$CALLS")|$(ls -d "$MARK" | wc -l | tr -d ' ')" "0|1"
clean; flags 0 1 0 0 1 0 pinap; ps_is "$CATCHER_PS"; mark 40; quiet catch-on
if [ ! -e "$MARK" ]; then ok "R4 marker 40 s and no reward_phone.py = stale: removed"; else bad "R4 marker left"; fi
logged "R4 ... and said so" "rewards: stale reward marker removed \(4[0-9] s old, reward_phone.py gone\) \(verb=catch-on "
n=$(grep -c "^pkill -TERM" "$CALLS"); if [ "$n" -ge 1 ] && [ ! -e "$LOCKD" ]; then ok "R4 ... and the verb does its process work"; else bad "R4 no process work"; fi
clean; flags 0 1 0 0 1 0 pinap; ps_is "$CATCHER_PS"; mark 20; quiet catch-on
is "R4 marker 20 s and no reward_phone.py yet = in flight" "$(count "$CALLS")|$(ls -d "$MARK" | wc -l | tr -d ' ')" "0|1"
clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$REWARD_PS"; mark 960; quiet status
if [ ! -e "$MARK" ]; then ok "R5 marker 16 min = stale even with reward_phone.py alive: removed"; else bad "R5 marker left"; fi
logged "R5 ... and said so" "rewards: stale reward marker removed \(96[0-9] s old, reward_phone.py still alive\) \(verb=status "
clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$REWARD_PS"; mark -3600; quiet status
if [ ! -e "$MARK" ]; then ok "R5 a marker dated in the future (the clock went back) is stale too"; else bad "R5 future marker left"; fi
clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$REWARD_PS"; echo "running... (started 15:40:00)" > "$RWSTAT"; mark 960; quiet rewards
is "R5 rewards after a run went stale but its reward_phone.py is alive: no second one, its line untouched" "$(count "$CALLS")|$(cat "$RWSTAT")" "0|running... (started 15:40:00)"
logged "R5 ... and said so" "rewards: reward_phone.py is alive without a marker, this tap does nothing"
nothing_left "R5 ... no marker made, the lock given back"

echo "== R6: Gym Battle and Catch Rewards"
clean; flags 1 1 0 0 1 1 pinap; ps_is "$CATCHER_PS" "$GYM_PS"; echo "done: old" > "$RWSTAT"; quiet rewards
total "R6 Gym Battle on and its runner alive: no call at all (no park, no reward catcher, nothing gym-related)" 0
case "$(cat "$RWSTAT")" in "Gym Battle is on: switch it off first @ "[0-2][0-9]:[0-5][0-9]:[0-5][0-9]) ok "R6 the app's line, with its clock time: $(cat "$RWSTAT")";; *) bad "R6 status: $(cat "$RWSTAT")";; esac
nothing_left "R6 no marker made, the lock given back"
logged "R6 logged" "rewards: not run, Gym Battle is on or a gym process is alive"; is "R6 exit" "$rc" 0
clean; flags 1 1 0 0 1 1 pinap; ps_is "$CATCHER_PS"; quiet rewards
is "R6 Gym Battle on, no gym process seen (the supervisor may be starting): not run either" "$(count "$CALLS")|$(said)" "0|Gym Battle is on: switch it off first"
clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$GYM_PS"; quiet rewards
is "R6 Gym Battle off but its supervisor and runner still alive (it is stopping)" "$(count "$CALLS")|$(said)" "0|Gym Battle is still running: tap again when it has stopped"
clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$RUNNER_PS"; quiet rewards
is "R6 Gym Battle off but a gym runner alone still alive" "$(count "$CALLS")|$(said)" "0|Gym Battle is still running: tap again when it has stopped"
clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$PREFLIGHT_PS"; quiet rewards
is "R6 Gym Battle off, its look-only preflight is running (it attaches too)" "$(count "$CALLS")|$(said)" "0|Gym Battle is still running: tap again when it has stopped"
nothing_left "R6 ... no marker made, the lock given back"
clean; flags 1 1 0 0 1 1 pinap; ps_is "$CATCHER_PS" "$GYM_PS"; mkdir "$RWSTAT"; quiet rewards   # the line cannot be written
expect "R6 the app's line cannot be written: root makes the file again, with the line" 1 "^su -c echo 'Gym Battle is on: switch it off first @ [0-9:]+' > [^ ]*pogo_rewards\.txt && chmod 666 "
total "R6 ... and nothing else" 1
clean; flags 0 0 0 0 0 0 pinap; ps_is; mkdir "$RWSTAT"; quiet rewards
expect "R6 the same for the queued line of a run" 1 "^su -c echo queued > [^ ]*pogo_rewards\.txt && chmod 666 "

echo "== R7-R10: the end of a run"
clean; flags 1 0 0 0 0 0 pinap; echo '#!/bin/bash' > "$GYMRUN"; ps_is "$CATCHER_PS"; : > "$SB/pkill_works"; : > "$SB/am_works"
echo 'bash "$SB/ctl.sh" gym-on > /dev/null 2>&1; grep -c "^am " "$CALLS" > "$SB/am_during_run.txt"' > "$SB/py_hook.sh"
quiet rewards
is "R7 Gym switched on during the run started nothing then" "$(cat "$SB/am_during_run.txt")" 0
order "R7 the end starts the catcher, then the gym runner" "${FULL}am run_gym.sh marker=no|"
expect "R7 the gym runner is started once" 1 "^am .*run_gym\.sh"; nothing_left "R7 marker and lock gone"
clean; flags 0 0 0 0 0 0 pinap; ps_is; : > "$SB/pkill_works"; : > "$SB/am_works"; echo 'echo catch-on > "$SB/tap_on_sleep"' > "$SB/py_hook.sh"; quiet rewards
order "R8 everything off, Catch switched on in the run's last seconds: flag only then, started by the end" "$FULL"
logged "R8 ... with its line" "catch-on: reward run in flight: flag only"; nothing_left "R8 marker and lock gone"
clean; flags 0 0 0 0 0 0 pinap; ps_is; : > "$SB/pkill_works"; : > "$SB/am_works"; quiet rewards
order "R8 everything off and it stays off: the end starts nothing" "pkill|pkill|sleep 5|python marker=yes|sleep 5|pkill|pkill|"
clean; flags 1 0 0 0 0 0 pinap; ps_is "$CATCHER_PS"; : > "$SB/pkill_works"; : > "$SB/am_works"; echo 'exit 3' > "$SB/py_hook.sh"; quiet rewards
order "R9 the reward catcher fails (exit 3): the end still runs" "$FULL"; nothing_left "R9 marker and lock gone"
clean; flags 1 0 0 0 0 0 pinap; ps_is "$CATCHER_PS"; : > "$SB/pkill_works"; : > "$SB/am_works"; echo 'kill -TERM $PPID' > "$SB/py_hook.sh"; quiet rewards
order "R10 a SIGTERM during the run does not cut it short: it still reaches its end" "$FULL"
case "$(cat "$SB/lock_at_am.txt")" in [0-5]) ok "R10 ... it still holds its lock when it starts the catcher";; *) bad "R10 lock at the start of the catcher: $(cat "$SB/lock_at_am.txt")";; esac
nothing_left "R10 ... and leaves nothing behind (no marker, no lock, no lock FILE)"
clean; flags 1 0 0 0 0 0 pinap; ps_is "$CATCHER_PS"; : > "$SB/pkill_works"; : > "$SB/am_works"; echo 'rmdir "$L"; rmdir "$M"' > "$SB/py_hook.sh"; quiet rewards
order "R10 marker and lock taken away during a very long run: the end is the same" "$FULL"
a2=$(grep '^5 ' "$SB/sleep_marker.log" | sed -n '2p')
case "$a2" in "5 "[0-5]) ok "R10 ... the marker is back for the last gap";; *) bad "R10 last gap: [$a2]";; esac
is "R10 ... and no lock is made where there was none (touch -c)" "$(cat "$SB/lock_at_am.txt")" none
nothing_left "R10 ... nothing left behind"
clean; flags 1 0 0 0 0 0 pinap; ps_is "$CATCHER_PS"; : > "$SB/pkill_works"; : > "$SB/am_works"; : > "$SB/marker_on_am"; quiet rewards
if [ -d "$MARK" ]; then ok "R10 a marker that another run makes while this one ends is not removed by it"; else bad "R10 it removed a marker that was not its own"; fi

echo "== R11-R18: the lock, and the moments around a run's start and end"
clean; flags 1 1 0 0 1 0 pinap; echo 0 > "$SB/tmp/pogo_dust.on"; ps_is "$CATCHER_PS"; mkdir "$LOCKD"; quiet status
is "R11 the lock is held by another verb: 39 half-second waits, then it answers anyway" "$(grep -c '^sleep 0.5$' "$SB/sleeps.log")|$out" "39|proc=up catch=1 spin=1 perfect=0 tap=0 apples=1 gym=0 berries=pinap dust=0"
if [ -d "$LOCKD" ]; then ok "R11 ... and the other verb's lock is still there"; else bad "R11 it removed a lock it did not hold"; fi
clean; flags 0 1 0 0 1 0 pinap; ps_is "$CATCHER_PS"; mkdir "$LOCKD"; : > "$SB/marker_on_sleep"; quiet catch-on
if [ "$(count "$CALLS")" = 0 ] && [ "$(flag catch)" = 1 ] && [ -d "$LOCKD" ] && grep -q "catch-on: reward run in flight: flag only" "$FLOG"; then ok "R12 a run starts while catch-on waits for the lock: it looks again and is flag only"; else bad "R12 catch-on"; fi
clean; flags 0 1 0 0 1 0 pinap; ps_is "$CATCHER_PS"; mkdir "$LOCKD"; : > "$SB/marker_on_sleep"; quiet rewards
if [ "$(count "$CALLS")" = 0 ] && [ -d "$MARK" ] && [ -d "$LOCKD" ]; then ok "R12 the same for a second rewards: nothing"; else bad "R12 rewards"; fi
clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS"; : > "$SB/marker_on_ps"; echo "queued 16:06:09" > "$RWSTAT"; quiet rewards
if [ "$(count "$CALLS")" = 0 ] && [ -d "$MARK" ] && [ ! -e "$LOCKD" ] && [ "$(cat "$RWSTAT")" = "queued 16:06:09" ] && grep -q "a reward run is in flight, this tap does nothing" "$FLOG"; then
  ok "R13 two taps both get as far as the marker: the one that loses the mkdir does nothing and leaves the winner's marker"
else bad "R13 calls=$(count "$CALLS")"; fi
clean; flags 1 0 0 0 0 0 pinap; ps_is "$CATCHER_PS"; mkdir "$LOCKD"; touch -d "@$(( $(date +%s) - 200 ))" "$LOCKD"; quiet spin-off
is "R14 a lock older than 2 min is taken without a wait, and given back" "$(grep -c '^sleep 0.5$' "$SB/sleeps.log")|$(ls -d "$LOCKD" 2>/dev/null)" "0|"
clean; flags 1 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$REWARD_PS"; quiet rewards
is "R15 a reward_phone.py alive with no marker at all: rewards does nothing" "$(count "$CALLS")|$(grep -c 'alive without a marker' "$FLOG")" "0|1"
nothing_left "R15 ... no marker made, the lock given back"
clean; flags 0 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$REWARD_PS"; mark 40; : > "$SB/marker_off_ps"; : > "$SB/pkill_works"; quiet catch-on
n=$(grep -c "^pkill -TERM" "$CALLS")
if [ "$n" -ge 1 ] && [ "$(grep -c '^am ' "$CALLS")" = 1 ] && [ "$(flag catch)" = 1 ] && ! grep -q "flag only" "$FLOG" && [ ! -e "$LOCKD" ]; then
  ok "R17 the run ends between a verb's first look and its flag: the verb does its own work, under the lock"
else bad "R17 pkill=$n"; fi
clean; flags 0 1 0 0 1 0 pinap; ps_is "$CATCHER_PS" "$REWARD_PS"; mark 40; : > "$SB/marker_off_ps"; mkdir "$LOCKD"; : > "$SB/marker_on_sleep"; quiet catch-on
if [ "$(count "$CALLS")" = 0 ] && [ "$(flag catch)" = 1 ] && [ "$(grep -c 'catch-on: reward run in flight: flag only' "$FLOG")" = 1 ] && [ -d "$MARK" ] && [ -d "$LOCKD" ]; then
  ok "R18 ... unless the next run is in flight by then: flag only again"
else bad "R18 calls=$(count "$CALLS")"; fi

echo "== the process patterns"
for line in "bash /x/pogo/run_gym.sh" "python3.14 tools/gym_run.py --phone"; do
  if echo "$line" | grep -qE "[c]atch_phone\.py|[r]un_catch\.sh"; then bad "running() matches: $line"; else ok "running() does not match: $line"; fi
done
if echo "bash /x/pogo/run_catch.sh" | grep -qE "[r]un_gym\.sh"; then bad "gym_running() matches run_catch.sh"; else ok "gym_running() does not match run_catch.sh"; fi
if echo "python3.14 tools/gym_run.py" | grep -qE "[r]un_gym\.sh"; then bad "gym_running() matches gym_run.py"; else ok "gym_running() does not match gym_run.py (only the supervisor counts)"; fi
if echo "python3.14 /x/pogo/system/scripts/game_write/reward_phone.py" | grep -qE "[r]eward_phone\.py"; then ok "reward_running() matches reward_phone.py"; else bad "reward pattern"; fi
for line in "python3.14 /x/pogo/catch_phone.py" "bash /x/pogo/run_catch.sh" "python3.14 /x/pogo/reward_catcher.py"; do
  if echo "$line" | grep -qE "[r]eward_phone\.py"; then bad "reward_running() matches: $line"; else ok "reward_running() does not match: $line"; fi
done
if [ $fail = 0 ]; then echo "ALL OK ($checks checks)"; else echo "SOME FAILED"; fi
exit $fail
