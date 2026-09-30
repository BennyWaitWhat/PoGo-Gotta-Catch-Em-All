# TEST_PROTOCOL.md — single-shot on-device test of `catch.js` in gadget SCRIPT mode

**One test, run once, with PoGo FOREGROUNDED on the live map the whole time.**

This sheet covers exactly the script-mode path: stop the desktop catcher → swap to a single-shot
script config → relaunch PoGo → confirm SUCCESS (`init → installed → READY → a throw`) vs the
**native-fault signature** that killed the last smoke test → restore to listen if it fails.

> **Why "foregrounded" is the whole point.** The previous crash happened with the screen off / PoGo
> backgrounded. A backgrounded Unity game does not pump `CameraFollowingGround.LateUpdate`, so the
> per-frame engine is paused. The hardened `catch.js` gates its one-shot GC discovery behind
> `READY_FRAMES = 90` real LateUpdate frames — if PoGo is backgrounded, warmup never completes,
> discovery never runs, and the catcher stays inert instead of stopping the GC world at the wrong
> time. **Keep PoGo on-screen, avatar + spawns visible, screen on, the entire test.** Do not let the
> screen sleep (the protocol takes a wake-lock).

> **Deploy the HARDENED script as `catch.js`.** This test assumes the file at
> `/data/local/tmp/re.zyg.fri/catch.js` is the hardened build
> (`ondevice_toggle/catch.hardened.js`, renamed to `catch.js` on push). The original crashing
> `catch.js` must NOT be the one on the phone for this test.

> **PRIMARY path is Termux-attach, not this.** The recommended end state runs the *proven* desktop
> catcher on-device over the gadget's listen socket (`ondevice_toggle/termux_catch.py`), which needs
> NO script-mode and NO `catch.js`. Do that first (see `DEPLOY_commands.md` / the plan). Use THIS
> sheet only for the zero-Termux, push-and-go endgame, or to prove the hardened script.

---

## Ground facts (so the commands below are exact)

- Gadget dir: `/data/local/tmp/re.zyg.fri/`  •  PoGo package: `com.nianticlabs.pokemongo`
- The gadget reads its config **only at PoGo process start** → every mode change needs a force-stop +
  relaunch. There is no live mode-switch.
- Live config file the gadget reads: `libgadget.config.so`.
- **Overwrite-in-place preserves the file's mode (0644) and SELinux `system_file` context** — CONFIRMED
  working on this device. So we always **overwrite** `libgadget.config.so` (via `cp` over it, or
  `cat >` into it). **Never `rm` then recreate it** — a fresh file can land with the wrong SELinux
  label and the gadget may refuse to read it.
- Canonical staged configs already on the phone: `config.listen.so` (restore source of truth) and
  `config.script.so`. Today's `config.script.so` uses `on_change:"reload"` (a live-reload watcher).
  **For a clean single shot we write a `on_change:"ignore"` config instead**, so the watcher can't
  reload the script mid-test and confuse the result.
- SUCCESS markers and faults both surface under the **logcat tag `frida-catch`** (the script logs via
  `__android_log_write`; there is no host console in script mode). `catch.log` / `catch.hb` are a
  best-effort bonus — **logcat is the source of truth.**

---

## Phase 0 — backup + version (run once, READ-ONLY except the backup)

```sh
# Guaranteed rollback: timestamped whole-dir copy.
su -c 'cp -a /data/local/tmp/re.zyg.fri /data/local/tmp/re.zyg.fri.bak.$(date +%s)'
su -c 'ls -la /data/local/tmp/re.zyg.fri.bak.*'

# Confirm the gadget is the Frida-17 fork that DOES run script mode (smoke test already proved this).
su -c 'strings /data/local/tmp/re.zyg.fri/libgadget.so | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+" | sort -uV | tail'

# Confirm the deployed catch.js is the HARDENED build (must show the kill-switch + one-shot markers).
su -c 'grep -c "one-shot-discovery" /data/local/tmp/re.zyg.fri/catch.js'   # expect 1+
su -c 'grep -c "KILL-SWITCH"        /data/local/tmp/re.zyg.fri/catch.js'   # expect 1+
```

> If `grep -c` shows `0`, the wrong `catch.js` is on the phone. Push the hardened one first:
> ```sh
> # desktop:  adb push catch.hardened.js /sdcard/catch.hardened.js
> su -c 'cp /sdcard/catch.hardened.js /data/local/tmp/re.zyg.fri/catch.js'
> su -c 'chmod 644 /data/local/tmp/re.zyg.fri/catch.js'
> ```

---

## Phase 1 — stop the desktop catcher (free port 27047)

The desktop catcher attaches over `127.0.0.1:27047`. In script mode the gadget does NOT listen, so a
still-running desktop catcher would error/retry against a phone that no longer accepts attaches, and
its log noise muddies the read. **Stop it before switching.**

- **On the desktop**, kill the running `catch_loop_fast.py` (Ctrl-C in its terminal, or stop its task).
- Confirm nothing is still talking to the gadget (optional, on the phone):
  ```sh
  su -c 'netstat -tnp 2>/dev/null | grep 27047 || echo "27047 idle"'
  ```
- **Do NOT** also be running `termux_catch.py` — the two paths are mutually exclusive. One attach at a
  time.

---

## Phase 2 — arm the single-shot SCRIPT config (no watcher)

Marker OFF (safe — catching idle until you arm it in Phase 5). Write a **single-shot** script config
(`on_change:"ignore"`) by **overwriting the existing** live config in place (preserves 0644 +
`system_file` context).

```sh
# marker OFF so the script comes up idle, not catching, on first launch (safe default).
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'

# write the one-shot SCRIPT config to a named file (heredoc -> atomic, valid JSON, no watcher).
su -c 'cat > /data/local/tmp/re.zyg.fri/config.script.oneshot.so <<EOF
{"interaction":{"type":"script","path":"/data/local/tmp/re.zyg.fri/catch.js","on_change":"ignore"},"runtime":"qjs"}
EOF'

# OVERWRITE the live config in place from that file (preserves mode 0644 + SELinux system_file label).
su -c 'cp /data/local/tmp/re.zyg.fri/config.script.oneshot.so /data/local/tmp/re.zyg.fri/libgadget.config.so'

# verify the live config is now script/ignore/qjs and points at catch.js.
su -c 'cat /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'ls -laZ /data/local/tmp/re.zyg.fri/libgadget.config.so'   # mode should be 0644, context u:object_r:system_file:s0
```

Expected `cat` output (one line):

```json
{"interaction":{"type":"script","path":"/data/local/tmp/re.zyg.fri/catch.js","on_change":"ignore"},"runtime":"qjs"}
```

> Optional read-only preflight (does not touch anything, safe while everything is staged):
> ```sh
> su -c 'sh /data/local/tmp/re.zyg.fri/selftest.sh'
> ```
> Look for `VERDICT: READY` and `live gadget mode is SCRIPT`. A WARN about "Frida 17+" is expected and
> fine — this device's fork runs script mode (Phase 0 proved it).

---

## Phase 3 — start logcat FIRST (in its own terminal), THEN relaunch PoGo

Open **two Termux sessions**. Session A tails the log; start it *before* the relaunch so you catch the
`init` line. Session B does the relaunch.

**Session A — the watch window (start this first, leave it running):**
```sh
su -c 'logcat -c'                 # clear old log so you only see THIS run
su -c 'logcat -s frida-catch:*'   # follow only the catcher's tag
```

**Session B — switch is already done (Phase 2); now force-stop + relaunch, then FOREGROUND PoGo:**
```sh
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'
```
**>>> Immediately bring PoGo to the foreground on the live map (avatar + spawns visible) and KEEP IT
THERE. Screen on. Do not background it. <<<** (Take a wake-lock so the screen/CPU don't sleep:)
```sh
termux-wake-lock
```

---

## Phase 4 — read the result in Session A

You are watching for one of three outcomes. Give it up to ~30–60 s after the map is interactive
(discovery needs 90 real frames ≈ 3 s of foreground rendering, plus PoGo's own login/sync).

### SUCCESS — the sequence you want (in order)

```
[catch] init stage=early — hardened on-device catcher (single-thread, one-shot-discovery)
[catch] warming up (frames 0/90) before discovery ...
[catch] installed (bootstrap): {"pbt":true,"pump":true,"probhook":...,"catchhook":...} liveness=ok
[catch] READY — msvc=ok avatar=ok itembag=ok iap=ok | Poke=.. Great=.. Ultra=.. Stardust=..
```

Reading it:
- `init stage=...` → the gadget executed the script (script mode works — expected).
- `installed (... ) ... liveness=ok` → hooks bound (pump + PokeballThrow + the two MergeFrom hooks)
  AND the four IL2CPP liveness exports are present. **`liveness=ok` is the green light** that the
  fork can self-find singletons in-process.
- `READY — msvc=ok ... itembag=ok ...` → the **one-shot GC discovery ran once, on a foregrounded
  engine, and started the world back up** (guaranteed in a `finally`). Singletons resolved:
  `msvc` (spawn source), `itembag` (ball counts), ideally `avatar` + `iap`.
- **Crucially: NO `NATIVE FAULT` lines, and no repeating storm.** The warmup window should be quiet.

If you see `READY` with `msvc=ok itembag=ok`, the script is healthy. Proceed to Phase 5 to arm a
throw. (`avatar=NO` or `iap=NO` is non-fatal — catching still works; range-gating just falls back.)

### FAULT SIGNATURE — the failure that must NOT recur (and now self-limits)

The old crash was a **storm**: `pc == fault-addr`, ~15 threads, addresses in the `0x72xxxxxxx`
(libil2cpp) range, looping for ~40 s. With the hardened build the kill-switch makes it **exactly one
line, then silence**:

```
[catch] NATIVE FAULT access-violation @0x72XXXXXX pc=0x72XXXXXX — KILL-SWITCH set, catcher disabled
```

- **One** such line (not a flood) = the kill-switch fired on the first fault; `tick()`/`manage()`/
  liveness are now permanent no-ops, so PoGo keeps running but the catcher is dead. **This is a FAIL.**
  Capture the `@addr` and `pc`, then go to Phase 6 (restore) and report the address.
- If you somehow still see a **flood** of `NATIVE FAULT` lines across many threads → the kill-switch
  didn't take; treat as FAIL, restore immediately (Phase 6).

### LIVENESS-MISSING — route to Termux-attach instead

```
[catch] FATAL: gadget libil2cpp missing liveness exports [...] — cannot self-find singletons; use Termux-attach fallback
```
This means the fork's `libil2cpp` lacks the `il2cpp_unity_liveness_*` / `il2cpp_stop_gc_world`
quartet, so the in-process script can't find singletons safely. **Not a crash — a clean decision
signal.** Restore to listen (Phase 6) and use the PRIMARY Termux-attach path (`termux_catch.py`),
which doesn't need in-process liveness.

### STUCK IN WARMUP — almost always "not actually foregrounded"

```
[catch] warming up (frames 0/90) before discovery ...
```
…and it never advances to `installed`/`READY`. The LateUpdate pump isn't ticking ⇒ PoGo is
backgrounded / screen asleep / stuck on a loading or login screen. **Bring PoGo to the live map,
keep the screen on**, and it should advance within a few seconds. If `init` itself never prints, the
gadget didn't load the script — re-check Phase 2 (`cat libgadget.config.so` is script/ignore/qjs).

---

## Phase 5 — arm ONE catch cycle (only after `READY`, with a spawn nearby)

Stand near a visible spawn. Create the presence marker to flip `RUN=true` (polled ~1/s by the pump —
**no relaunch**):

```sh
su -c 'touch /data/local/tmp/re.zyg.fri/catch.on && chmod 666 /data/local/tmp/re.zyg.fri/catch.on'
```

Expected in Session A:
```
[catch] >>> TOGGLE ON  — catching
[catch] run | dust=.. | fired=.. refired=.. | caught=.. esc=.. flee=.. miss=.. | q=.. vis=.. inr=.. | P=.. G=.. U=.. pc=..
```
On the phone you should see an **encounter open** then an **Excellent throw**; an escape re-throws
(≤4 attempts, ~2 s apart); legendaries are skipped; the box stays empty (auto-transfer); `caught`
and `dust` tick up over a few cycles. Watch 2–3 `run | ...` lines to confirm it's actually catching.

Turn it back OFF when satisfied (no relaunch):
```sh
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'
```
Expect: `[catch] <<< TOGGLE OFF — idle`.

---

## Phase 6 — RESTORE TO LISTEN (the panic button — run any time, any phase)

Hands control back to the desktop/Termux attach path. **Overwrites in place** (preserves SELinux
context):

```sh
su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'
```

After this, the gadget is back in **listen mode on `127.0.0.1:27047`** — the desktop catcher (or
`termux_catch.py`) can attach again. Verify:
```sh
su -c 'cat /data/local/tmp/re.zyg.fri/libgadget.config.so'   # should show "type":"listen" ... 27047
```

### Recovery ladder (only if PoGo won't even launch after the switch)

```sh
# 1) fastest — already done above: restore listen + relaunch (fixes a bad script/config 99% of the time).

# 2) neutralise Frida entirely (PoGo runs with NO gadget): rename the .so aside, relaunch, verify, restore.
su -c 'mv /data/local/tmp/re.zyg.fri/libgadget.so /data/local/tmp/re.zyg.fri/libgadget.so.bak'
su -c 'am force-stop com.nianticlabs.pokemongo'
#   ...confirm PoGo launches clean... then:
su -c 'mv /data/local/tmp/re.zyg.fri/libgadget.so.bak /data/local/tmp/re.zyg.fri/libgadget.so'

# 3) restore the whole dir from the Phase-0 backup (replace <TS> with your timestamp).
su -c 'rm -rf /data/local/tmp/re.zyg.fri && cp -a /data/local/tmp/re.zyg.fri.bak.<TS> /data/local/tmp/re.zyg.fri'
```

---

## One-screen cheat sheet

| Step | Command (root, in Termux; PoGo foregrounded throughout) |
|---|---|
| 0. backup | `su -c 'cp -a /data/local/tmp/re.zyg.fri /data/local/tmp/re.zyg.fri.bak.$(date +%s)'` |
| 1. stop desktop | (desktop) Ctrl-C the running `catch_loop_fast.py` |
| 2a. marker OFF | `su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'` |
| 2b. write one-shot cfg | `su -c 'cat > /data/local/tmp/re.zyg.fri/config.script.oneshot.so <<EOF`<br>`{"interaction":{"type":"script","path":"/data/local/tmp/re.zyg.fri/catch.js","on_change":"ignore"},"runtime":"qjs"}`<br>`EOF'` |
| 2c. go script (overwrite) | `su -c 'cp /data/local/tmp/re.zyg.fri/config.script.oneshot.so /data/local/tmp/re.zyg.fri/libgadget.config.so'` |
| 3a. watch (Session A) | `su -c 'logcat -c'` then `su -c 'logcat -s frida-catch:*'` |
| 3b. relaunch (Session B) | `su -c 'am force-stop com.nianticlabs.pokemongo'` then `su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'` then **foreground PoGo** + `termux-wake-lock` |
| 4. SUCCESS = | `init …` → `installed (…) liveness=ok` → `READY — msvc=ok … itembag=ok …`, **no `NATIVE FAULT`** |
| 4. FAIL = | a `NATIVE FAULT … KILL-SWITCH set` line (capture `@addr`/`pc`) — go to restore |
| 5. arm a throw | `su -c 'touch /data/local/tmp/re.zyg.fri/catch.on && chmod 666 /data/local/tmp/re.zyg.fri/catch.on'` → expect `TOGGLE ON` + a throw; OFF: `su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'` |
| 6. RESTORE listen | `su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'` + force-stop + relaunch |
