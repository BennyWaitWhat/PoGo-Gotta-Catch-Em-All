# Request: a CULL button in the AutoCatcher app

**Status: BUILT 2026-11-05 by Pokemon Inventory** on Benny's "you do it": app 1.2 (`MainActivity.java`: CULL NOW + status
line) and `pogo_extract/cull_button.py`. One change from the plan below: the app writes `pogo_cull.req` itself through su
(chmod 666, shell_data_file), so `catcher_ctl.sh` needs no `cull` verb and no root pre-created files.

**From** Pokemon Inventory · **to** AutoCatcher (owner of `AutoCatcher/`) · **asked by** Benny, 2026-11-05:
"i also need a cull button added to the auto catcher app we've made on my phone."

The cull itself runs on the PC (`pogo_extract/full_audit.py`, Frida over Tailscale ADB), so the button only *asks* for one.
The app never attaches, never pauses the catcher (rule 5) and never restarts the game (rule 3).

## AutoCatcher's part (the app + `catcher_ctl.sh`)
1. **Button.** In `ondevice_toggle/apk/src/com/benny/autocatcher/MainActivity.java`, add `CULL NOW` under ONE-OFF ACTIONS,
   built like `CATCH REWARDS NOW`. Description line: "Asks the PC to run one cull. It tags the Transfer pile; you release by hand."
2. **Verb.** Add `catcher_ctl.sh cull`. It writes ONE line, `requested <epoch> <HH:MM:SS>`, to `/data/local/tmp/pogo_cull.req`
   and does nothing else. Root pre-creates the file 666, like the other flags (the app cannot create files there).
3. **Status.** Show `/data/local/tmp/pogo_cull_status.txt` under the button (root pre-creates it 666), refreshed by the existing
   ticker. The PC writes one line: `queued HH:MM`, `running since HH:MM`, `done HH:MM: release N in the Transfer tag | bag X/Y`,
   or `STOPPED HH:MM: <reason> -- nothing tagged`.
4. **One tap = one request.** Disable the button while the status starts with `queued` or `running`.
5. **Report (optional).** A `SHOW REPORT` view reading `/data/local/tmp/pogo_cull_report.txt`, which the PC pushes after a pass.

## Pokemon Inventory's part (the PC)
A small watcher on the PC reads `pogo_cull.req` over ADB. For each new request it runs ONE cull through the same runner the
`/cull` skill uses, then writes the status and report files. It keeps a 3-minute gap after the last pass, never retries, and
on a failed gate or a frozen walk it stops and writes `STOPPED` (`.claude/skills/cull/FAILURES.md`). It needs Benny's OK to run
in the background (2026-09-22: "kill all the background stuff").

Contract to keep fixed: the two file paths above and the four status prefixes (`queued`, `running`, `done`, `STOPPED`).
