# TEST_ONDEVICE.md — single-shot on-device test of `catch.ondevice.js` (gadget SCRIPT mode)

**One test, run once, with PoGo FOREGROUNDED on the live map near spawns the whole time.**

This sheet tests the **hook-based** catcher (`catch.ondevice.js`) — the build that has **NO Unity
GC-world / liveness walk**. All object discovery is passive `this`-capture from methods the game
already calls on the render thread. The whole class of fault that killed earlier smoke tests
(`il2cpp_stop_gc_world` from the render thread) **cannot happen here** — there is no such call in the
file. You are therefore confirming a *positive* sequence (`init → installed → READY (hook-based) →
avatar+bag captured → a spawn captured → a throw`), not just "did it avoid crashing."

> **Why "foregrounded + near spawns" is the whole point.**
> - **Foreground:** a backgrounded Unity game does not pump `CameraFollowingGround.LateUpdate`, which
>   is the script's clock. The discovery-hook install is gated behind `READY_FRAMES = 90` real
>   LateUpdate frames (~3 s of on-screen rendering). Background it and warmup never completes — the
>   catcher sits inert (by design), it does **not** crash.
> - **Near spawns:** discovery is now hook-based. The spawn table (`SPAWNS`) is populated by hooking
>   `MapPokemon.get_VisibleOnMap` / `get_Location`, which the map renderer calls **per visible
>   spawn, per frame**. With NO wild spawns on screen, those hooks never fire and `SPAWNS` stays
>   empty — you would see `READY` but `spawns=0` and nothing to throw at. **Stand where you can see
>   at least one or two wild Pokémon on the map.**
> Keep PoGo on-screen, avatar + spawns visible, screen on, the entire test. Take a wake-lock so the
> screen/CPU don't sleep.

> **Deploy `catch.ondevice.js` as `catch.js`.** This test assumes the file at
> `/data/local/tmp/re.zyg.fri/catch.js` is the hook-based build (`ondevice_toggle/catch.ondevice.js`,
> renamed to `catch.js` on push). The old crashing `catch.js` and the older `catch.fixed.js` /
> `catch.hardened.js` (which DO contain the GC walk) must NOT be the one on the phone for this test.

---

## Ground facts (so the commands below are exact)

- Gadget dir: `/data/local/tmp/re.zyg.fri/`  •  PoGo package: `com.nianticlabs.pokemongo`
- The gadget reads its config **only at PoGo process start** → every mode change needs a force-stop +
  relaunch. There is no live mode-switch. (The ON/OFF *toggle* in Phase 5 needs no relaunch — it is a
  marker file polled ~1/s by the pump.)
- Live config file the gadget reads: `libgadget.config.so`.
- **Overwrite-in-place preserves the file's mode (0644) and SELinux `system_file` context** — CONFIRMED
  on this device. Always **overwrite** `libgadget.config.so` (`cp` over it, or `cat >` into it).
  **Never `rm` then recreate it** — a fresh file can land with the wrong SELinux label and the gadget
  may refuse to read it.
- Canonical staged configs already on the phone: `config.listen.so` (restore source of truth, the
  desktop-attach mode on `127.0.0.1:27047`) and `config.script.so` (script mode, `on_change:"reload"`).
  **For a clean single shot we write an `on_change:"ignore"` config** so the live-reload watcher can't
  reload the script mid-test and confuse the result.
- SUCCESS markers and faults both surface under the **logcat tag `frida-catch`** (the script logs via
  `__android_log_write`; there is no host console in script mode). `catch.log` / `catch.hb` are a
  best-effort bonus — **logcat is the source of truth.**

---

## Phase 0 — backup + verify the RIGHT script is staged (run once; READ-ONLY except the backup)

```sh
# Guaranteed rollback: timestamped whole-dir copy.
su -c 'cp -a /data/local/tmp/re.zyg.fri /data/local/tmp/re.zyg.fri.bak.$(date +%s)'
su -c 'ls -la /data/local/tmp/re.zyg.fri.bak.*'

# Confirm the gadget is the Frida-17 fork that DOES run script mode (already proven on this device).
su -c 'strings /data/local/tmp/re.zyg.fri/libgadget.so | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+" | sort -uV | tail'

# Confirm the deployed catch.js is the HOOK-BASED build — it MUST contain the hook-based markers
# and MUST NOT contain the GC-world stop. (If any check is wrong, push the right file, below.)
su -c 'grep -c "hook-based on-device catcher" /data/local/tmp/re.zyg.fri/catch.js'   # expect 1+
su -c 'grep -c "READY (hook-based)"            /data/local/tmp/re.zyg.fri/catch.js'   # expect 1+
su -c 'grep -c "il2cpp_stop_gc_world"          /data/local/tmp/re.zyg.fri/catch.js'   # expect 0 in CODE
# (the only matches for stop_gc_world are inside /* */ comments; there is no live call.)
```

> If `hook-based` shows `0`, the wrong `catch.js` is on the phone. Push the hook-based one:
> ```sh
> # desktop (phone busy now? do this in the deploy window):
> #   adb push catch.ondevice.js /sdcard/catch.ondevice.js
> su -c 'cp /sdcard/catch.ondevice.js /data/local/tmp/re.zyg.fri/catch.js'
> su -c 'chmod 644 /data/local/tmp/re.zyg.fri/catch.js'
> ```

---

## Phase 1 — stop the desktop catcher (free port 27047)

The desktop catcher attaches over `127.0.0.1:27047`. In script mode the gadget does NOT listen, so a
still-running desktop catcher would just error/retry and muddy the log read. **Stop it before
switching.**

- **On the desktop**, kill the running `catch_loop_fast.py` (Ctrl-C in its terminal, or stop its task).
- Confirm nothing is still attached (optional, on the phone):
  ```sh
  su -c 'netstat -tnp 2>/dev/null | grep 27047 || echo "27047 idle"'
  ```
- **Do NOT** also be running `termux_catch.py` — one attach at a time; the paths are mutually exclusive.

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
su -c 'ls -laZ /data/local/tmp/re.zyg.fri/libgadget.config.so'   # mode 0644, context u:object_r:system_file:s0
```

Expected `cat` output (one line):

```json
{"interaction":{"type":"script","path":"/data/local/tmp/re.zyg.fri/catch.js","on_change":"ignore"},"runtime":"qjs"}
```

---

## Phase 3 — start logcat FIRST (its own terminal), THEN relaunch PoGo

Open **two Termux sessions**. Session A tails the log; start it *before* the relaunch so you catch the
`init` line. Session B does the relaunch.

**Session A — the watch window (start this first, leave it running):**
```sh
su -c 'logcat -c'                 # clear old log so you only see THIS run
su -c 'logcat -s frida-catch:*'   # follow only the catcher's tag
```

**Session B — switch is already done (Phase 2); now force-stop + relaunch:**
```sh
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'
```
**>>> Immediately bring PoGo to the foreground on the live map, with at least one or two wild spawns
visible, and KEEP IT THERE. Screen on. Do not background it. <<<** Take a wake-lock so nothing sleeps:
```sh
termux-wake-lock
```

---

## Phase 4 — read the result in Session A

Watch for one of the outcomes below. Give it up to ~30–60 s after the map is interactive (hook install
needs 90 real frames ≈ 3 s of foreground rendering, plus PoGo's own login/sync; then the avatar/bag/
spawn captures fill in over a few more seconds as the game calls those methods).

### SUCCESS — the sequence you want (in order)

```
[catch] init stage=early — hook-based on-device catcher (single-thread, NO GC-walk; hook-fed discovery)
[catch] warming up (frames 0/90) before installing discovery hooks ...
[catch] installed (bootstrap): {"pbt":true,"pump":true,"probhook":2,"catchhook":2}
[catch] READY (hook-based) — getterHooks=2 lifecycleHooks=0 teardownHooks=1 avatarHook=ok itembagHook=ok | avatar/itembag/spawns fill in as the game calls them
```

Reading it:
- `init stage=...` → the gadget executed the script (script mode works — expected).
- `installed (...) {"pbt":true,"pump":true,...}` → the catch hooks bound: `pbt` = PokeballThrow class
  found, `pump` = the `CameraFollowingGround.LateUpdate` per-frame clock is attached, `probhook`/
  `catchhook` = the `EncounterOutProto` / `CatchPokemonOutProto` `MergeFrom` hooks (≥1 each, typically
  2). **There is deliberately NO `liveness=...` field here** — the GC machinery is gone.
- `READY (hook-based) — getterHooks=N ...` → the hook-based discovery installed. **The number that
  matters most is `getterHooks` ≥ 1** (the `get_VisibleOnMap` / `get_Location` spawn-capture hooks —
  the reliable source). `avatarHook=ok` and `itembagHook=ok` mean those capture hooks are armed; the
  actual pointers fill in passively a moment later. `teardownHooks` is best-effort (0 is fine — the
  refill lazy-reap keeps the spawn table clean regardless).
- **Crucially: NO `NATIVE FAULT` lines.** The warmup window should be quiet.

Then **arm a throw (Phase 5)** and confirm in the same window:
```
[catch] >>> TOGGLE ON  — catching
[catch] run | spawns=3 | fired=1 refired=0 | caught=0 esc=0 flee=0 miss=0 | q=2 vis=3 inr=2 | P=.. G=.. U=.. pc=1 | avatar=ok bag=ok
```
- `spawns=` > 0 → the **spawn table is populating** (the getter hooks are firing on real wild spawns).
  **This is the single most important live signal that the new discovery works.**
- `avatar=ok` and `bag=ok` → the MapAvatar GPS and ItemBag pointers were captured (range-gating and
  ball-floor logic are now fully active). `bag=NO` for the first few seconds is normal — see fallback
  below; `avatar=NO` for longer just disables range-gating (still catches).
- `fired=` ticking up + an **encounter open then an Excellent throw on the phone** = end-to-end win.
  `caught` rises over a few cycles; the box stays empty (auto-transfer); legendaries are skipped.

If you see `READY (hook-based)` with `getterHooks ≥ 1`, then after arming `spawns > 0` and a throw on
screen — **PASS.**

### FAULT SIGNATURE — must NOT occur (and self-limits to ONE line if it somehow does)

The kill-switch flips on the FIRST native fault, so even an unexpected fault is **exactly one line,
then silence** (never the old multi-thread storm):

```
[catch] NATIVE FAULT access-violation @0x72XXXXXX pc=0x72XXXXXX — KILL-SWITCH set, catcher disabled (no storm)
```

- **One** such line = the kill-switch fired; `tick()`/`manage()` are now permanent no-ops, so PoGo
  keeps running but the catcher is dead. **This is a FAIL.** Capture the `@addr` and `pc`, go to
  Phase 6 (restore), and report the address. (Note: with the GC walk removed, a fault here would be a
  *new* signature — not the old `stop_gc_world` storm — and worth reporting verbatim.)

### EMPTY-TABLE / DISCOVERY-INCOMPLETE — the most likely thing to need a tweak

Two sub-cases, both **non-crash** (the catcher stays safe and inert):

**(a) No spawn-capture hook resolved** — you will see, ONCE, the actual method list, then a repeated
incomplete notice:
```
[catch] NO MapPokemon spawn-capture method resolved — MapPokemon methods: get_EncounterId/0,get_PokemonId/0,...
[catch] discovery hooks incomplete (no MapPokemon spawn-capture method resolved) — see the logged MapPokemon method list to pick the right getter/lifecycle name.
```
This means neither `get_VisibleOnMap` nor `get_Location` (nor any lifecycle name) resolved on this
build's `MapPokemon`. **The fix is in that logged method list** — find the real per-frame getter (look
for `get_VisibleOnMap`, `get_Location`, `get_Position`, or similar 0-arg getters) and add its exact
name to the `getterNames` array in `installDiscoveryHooks()`, then re-push. (You will NOT need to
touch anything else.) **Capture that `MapPokemon methods:` line — it is the whole diagnostic.**

**(b) `READY` but `spawns=0` forever** — hooks installed but the table never fills. Almost always
"no wild spawns on screen" (stand near visible Pokémon) or "still on a loading/login screen" (get to
the live map). If spawns ARE clearly on screen and it still reads `spawns=0` after ~20–30 s, that is
case (a) in disguise (the getters resolved to a slot that doesn't fire) — restore and report.

### STUCK IN WARMUP — "not actually foregrounded"

```
[catch] warming up (frames 0/90) before installing discovery hooks ...
```
…and it never advances to `installed`/`READY`. The LateUpdate pump isn't ticking ⇒ PoGo is
backgrounded / screen asleep / on a loading or login screen. **Bring PoGo to the live map, keep the
screen on**; it advances within a few seconds. If `init` itself never prints, the gadget didn't load
the script — re-check Phase 2 (`cat libgadget.config.so` is script/ignore/qjs).

---

## Phase 5 — arm ONE catch cycle (only after `READY (hook-based)`, with a spawn nearby)

Stand near a visible wild spawn. Create the presence marker to flip `RUN=true` (polled ~1/s by the
pump — **no relaunch**):

```sh
su -c 'touch /data/local/tmp/re.zyg.fri/catch.on && chmod 666 /data/local/tmp/re.zyg.fri/catch.on'
```

Expected in Session A: `>>> TOGGLE ON — catching`, then `run | spawns=N ... | avatar=ok bag=ok` lines
(see SUCCESS above), and on the phone an **encounter open** then an **Excellent throw**; an escape
re-throws (≤4 attempts, ~2 s apart); legendaries are skipped; the box stays empty (auto-transfer);
`caught` ticks up over a few cycles. Watch 2–3 `run | ...` lines with `fired` rising to confirm it is
actually catching.

> **Ball-floor fallback while the bag fills in:** for the first few seconds `bag=NO` is normal. While
> the ItemBag pointer is uncaptured, the script assumes all balls available and throws the default
> ball (Poké-first), and it does NOT auto-stop or feed berries. Once `bag=ok` (within seconds) ball
> selection becomes data-driven exactly like the desktop. This is expected, not a bug.

Turn it back OFF when satisfied (no relaunch):
```sh
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'
```
Expect: `<<< TOGGLE OFF — idle`.

---

## Phase 6 — RESTORE TO LISTEN (the panic button — run any time, any phase)

Hands control back to the desktop/Termux attach path. **Overwrites in place** (preserves SELinux
context). This is the one-command restore (well, the standard 4-line block):

```sh
su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'
```

After this the gadget is back in **listen mode on `127.0.0.1:27047`** — the desktop catcher (or
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

| Step | Command (root, in Termux; PoGo foregrounded on spawns throughout) |
|---|---|
| 0. backup | `su -c 'cp -a /data/local/tmp/re.zyg.fri /data/local/tmp/re.zyg.fri.bak.$(date +%s)'` |
| 0. verify script | `su -c 'grep -c "hook-based on-device catcher" /data/local/tmp/re.zyg.fri/catch.js'` (expect 1+); `grep -c "il2cpp_stop_gc_world"` (expect 0 in code) |
| 1. stop desktop | (desktop) Ctrl-C the running `catch_loop_fast.py` |
| 2a. marker OFF | `su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'` |
| 2b. write one-shot cfg | `su -c 'cat > /data/local/tmp/re.zyg.fri/config.script.oneshot.so <<EOF`<br>`{"interaction":{"type":"script","path":"/data/local/tmp/re.zyg.fri/catch.js","on_change":"ignore"},"runtime":"qjs"}`<br>`EOF'` |
| 2c. go script (overwrite) | `su -c 'cp /data/local/tmp/re.zyg.fri/config.script.oneshot.so /data/local/tmp/re.zyg.fri/libgadget.config.so'` |
| 3a. watch (Session A) | `su -c 'logcat -c'` then `su -c 'logcat -s frida-catch:*'` |
| 3b. relaunch (Session B) | `su -c 'am force-stop com.nianticlabs.pokemongo'` then `su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'` then **foreground PoGo on spawns** + `termux-wake-lock` |
| 4. SUCCESS = | `init …` → `installed (…) {"pbt":true,"pump":true,…}` → `READY (hook-based) — getterHooks≥1 … avatarHook=ok itembagHook=ok`, **no `NATIVE FAULT`** |
| 4. then arm → | after `READY`: `spawns>0` + an Excellent throw on screen |
| 4. FAIL = | a `NATIVE FAULT … KILL-SWITCH set` line (capture `@addr`/`pc`), OR `NO MapPokemon spawn-capture method resolved` (capture the logged method list) — go to restore |
| 5. arm a throw | `su -c 'touch /data/local/tmp/re.zyg.fri/catch.on && chmod 666 /data/local/tmp/re.zyg.fri/catch.on'` → expect `TOGGLE ON` + a throw; OFF: `su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'` |
| 6. RESTORE listen | `su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'` + force-stop + relaunch |
