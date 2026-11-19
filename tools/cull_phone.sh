#!/data/data/com.termux/files/usr/bin/bash
# THE CULL ON THE PHONE (Benny 2026-11-18: "the entire thing needs to run on the phone just like the gym mode."). The
# AutoCatcher app's Cull Now button writes /data/local/tmp/pogo_cull.req; the listener (pogo_extract/cull_button.py, run
# from the repo clone ~/cull) sees it within 15 s and runs ONE cull right here -- walk, 11 audits, tag sync, report, data
# push -- with the PC off. Its status line is the one the app shows (/data/local/tmp/pogo_cull_status.txt). It only tags.
#   cull_phone.sh              the listener, started again if it dies or takes new code (one copy: its mutex port)
#   cull_phone.sh --start      start the listener as its own Termux task unless one runs (Termux:Boot: ~/.termux/boot/40-pogo-cull)
#   cull_phone.sh --setup      once, and safe again: the two libraries the cull needs, the clone on main, the data, the
#                              rank tables / client game master if the PC left them in /data/local/tmp, the boot entry, --start
#   cull_phone.sh --selfcheck  offline: tools/phone/adb (the adb stand-in) against a stand-in su; no phone, no root
# What a pass here runs with: tools/phone/adb first on PATH, POGO_ON_PHONE=1, the audits at most 3 at a time (2.9 GB free
# beside the game, 11-18: all 11 at once peak at 2.7 GB), the dashboard on 127.0.0.1 only, its busy-marker name
# PokemonInventoryPhone (the PC's cull is PokemonInventory: the listener refuses while that one is attached).
R=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
REPO=https://github.com/BennyWaitWhat/PoGo-Gotta-Catch-Em-All.git
LIBS="flask==3.1.3 s2sphere==0.2.5 future==1.0.0"         # the PC's versions; the walk needs s2sphere, the recrawl / sync flask
BOOT=40-pogo-cull

phone_env() {
  export PREFIX=/data/data/com.termux/files/usr HOME=/data/data/com.termux/files/home
  export LD_LIBRARY_PATH=$HOME/applibs:$PREFIX/lib
  export PATH=$R/tools/phone:$PREFIX/bin:/system/bin
  export POGO_ON_PHONE=1 PYTHONIOENCODING=utf-8 ADB_TARGET=phone POGO_BUSY_NAME=PokemonInventoryPhone POGO_AUDIT_JOBS=3 DASH_HOST=127.0.0.1
  [ -n "${TZ:-}" ] || export TZ=$(/system/bin/getprop persist.sys.timezone 2>/dev/null)
  PY=                                                     # the newest installed python3.N, a real file (as run_gym.sh)
  for p in "$PREFIX"/bin/python3.[0-9] "$PREFIX"/bin/python3.[0-9][0-9]; do [ -f "$p" ] && PY=$p; done
  PY=${PY:-$PREFIX/bin/python3}
}

listening() { ps -ef 2>/dev/null | grep -q '[c]ull_button\.py'; }

start() {
  listening && { echo "the Cull Now listener is already running"; return 0; }
  am startservice --user 0 -n com.termux/com.termux.app.RunCommandService -a com.termux.RUN_COMMAND \
    --es com.termux.RUN_COMMAND_PATH "$PREFIX/bin/bash" --esa com.termux.RUN_COMMAND_ARGUMENTS "$R/tools/cull_phone.sh" \
    --ez com.termux.RUN_COMMAND_BACKGROUND true >/dev/null 2>&1
  for i in $(seq 1 20); do listening && { echo "the Cull Now listener is running"; return 0; }; sleep 1; done
  echo "the Cull Now listener did not start -- run: bash $R/tools/cull_phone.sh (it prints why)"; return 1
}

setup() {
  set -e
  "$PY" -m pip install -q --disable-pip-version-check $LIBS
  if [ -d "$R/.git" ]; then git -C "$R" fetch -q origin && git -C "$R" checkout -q main && git -C "$R" merge -q --ff-only origin/main
  else git clone -q "$REPO" "$R"; fi
  cd "$R"
  "$PY" tools/pogo_data.py pull --group inventory
  # what the data store does not carry: the rank tables (335 MB, rebuilt when missing -- slowly here) and the client game
  # master (downloaded when missing). The PC may leave its copies in /data/local/tmp: taken once, then removed.
  for f in pogo_extract/system/scripts/rank_tables.pkl pogo_extract/gamemaster_pokeminers.json; do
    t=/data/local/tmp/pogo_cull_$(basename "$f")
    if [ -f "$t" ]; then cat "$t" > "$R/$f.part" && mv -f "$R/$f.part" "$R/$f" && su -c "rm -f $t" && echo "took $f from the PC"; fi
  done
  mkdir -p "$HOME/.termux/boot"
  printf '%s\n' '#!/data/data/com.termux/files/usr/bin/sh' \
    '# Termux:Boot: the Cull Now listener runs on the phone (Benny 2026-11-18). ~/cull/tools/cull_phone.sh says the rest.' \
    "exec $PREFIX/bin/bash $R/tools/cull_phone.sh --start" > "$HOME/.termux/boot/$BOOT"
  chmod 700 "$HOME/.termux/boot/$BOOT"
  set +e
  start
}

selfcheck() {
  local D A out
  D=$(mktemp -d) || exit 1; trap 'rm -rf "$D"' EXIT
  # a stand-in su: runs the command as this user, chown a no-op (no root here), Android's PATH = this machine's
  printf '#!/bin/sh\n[ "$1" = -c ] || exit 9\nexec sh -c "chown() { :; }; $2"\n' > "$D/su"; chmod +x "$D/su"
  export POGO_SU=$D/su POGO_SYSPATH=$PATH ADB_TARGET=phone
  A=(bash "$R/tools/phone/adb")
  bad() { echo "cull_phone selfcheck FAILED: $1"; exit 1; }
  [ "$("${A[@]}" devices | sed -n 2p)" = "$(printf 'phone\tdevice')" ] || bad "devices"
  "${A[@]}" connect 100.98.158.56:5555 | grep -q '^already connected to ' || bad "connect"
  [ "$("${A[@]}" -s phone get-state)" = device ] || bad "get-state"
  "${A[@]}" -s phone forward tcp:27047 tcp:27047 || bad "a same-port forward"
  "${A[@]}" -s phone forward tcp:1 tcp:2 2>/dev/null && bad "a real forward was accepted"
  [ "$("${A[@]}" -s phone shell 'echo $((1+2))')" = 3 ] || bad "shell"
  [ "$("${A[@]}" -s phone shell -T echo one two)" = "one two" ] || bad "shell options and words"
  out=$(LD_LIBRARY_PATH=/termux/lib "${A[@]}" -s phone shell 'echo "[${LD_LIBRARY_PATH:-}]"'); [ "$out" = "[]" ] || bad "Termux's libraries reach the root shell: $out"
  "${A[@]}" -s phone shell 'exit 7'; [ $? -eq 7 ] || bad "the command's exit status"
  [ "$(echo hi | "${A[@]}" -s phone shell cat)" = hi ] || bad "stdin"
  [ "$("${A[@]}" -s phone exec-out 'printf "a\000b"' | od -An -c | tr -d ' \n')" = 'a\0b' ] || bad "exec-out is not byte-exact"
  echo data > "$D/f"; mkdir "$D/dir"
  "${A[@]}" -s phone push "$D/f" "$D/dir" | grep -q 'pushed' && [ "$(cat "$D/dir/f")" = data ] || bad "push into a folder"
  "${A[@]}" -s phone push "$D/f" "$D/g" >/dev/null && [ "$(cat "$D/g")" = data ] || bad "push to a file"
  "${A[@]}" -s phone pull "$D/g" "$D/h" >/dev/null && [ "$(cat "$D/h")" = data ] || bad "pull to a file"
  "${A[@]}" -s phone pull "$D/missing" "$D/m" 2>/dev/null && bad "a pull of a missing file passed"
  [ -e "$D/m" ] || [ -e "$D/m.part" ] && bad "a failed pull left a file"
  "${A[@]}" -s phone push "$D/it's" "$D/x" 2>/dev/null && bad "a quoted path was accepted"
  "${A[@]}" -s phone install x.apk 2>/dev/null && bad "an unhandled verb was accepted"
  echo "cull_phone selfcheck OK"
}

case "${1:-}" in
  --selfcheck) selfcheck ;;
  --start)     phone_env; start ;;
  --setup)     phone_env; setup ;;
  '')          phone_env; cd "$R/pogo_extract" || exit 1
               while :; do
                 "$PY" cull_button.py; rc=$?
                 case $rc in 3) exit 0 ;; 2) exit 2 ;; 0) ;; *) sleep 30 ;; esac   # 3 = one runs already, 2 = not the phone
               done ;;
  *) echo "usage: bash tools/cull_phone.sh [--start | --setup | --selfcheck]   (unknown: $1 -- nothing was run)"; exit 2 ;;
esac
