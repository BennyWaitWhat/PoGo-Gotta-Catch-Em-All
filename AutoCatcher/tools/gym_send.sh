#!/bin/bash
# Queue ONE command for the gym runner: its own file in gym_state/runner_inbox/, written as a dot-file and renamed in -- never read
# half-written, never overwritten by another writer (the single runner_cmd.json lost a stop under the buddy session's polls).
# Portable: Windows Git Bash or Linux (the cloud VM).
# usage: gym_send.sh '{"go": "c55faf39"}' [writer-name]    commands: go / hunt (+drill) / stop / spin (+at) / lap / buddy / topup
HERE="$(cd "$(dirname "$0")" && pwd)"; command -v cygpath >/dev/null 2>&1 && HERE="$(cygpath -m "$HERE")"
S="$HERE/gym_state"; PY="$(command -v python || command -v python3)"
"$PY" -c "import json,sys; assert isinstance(json.loads(sys.argv[1]), dict)" "$1" 2>/dev/null || { echo "not a JSON object: $1"; exit 1; }
mkdir -p "$S/runner_inbox"; N="$(date +%s%3N)_${2:-avatar}.json"
printf '%s\n' "$1" > "$S/runner_inbox/.$N" && mv "$S/runner_inbox/.$N" "$S/runner_inbox/$N" && echo "queued $N"
