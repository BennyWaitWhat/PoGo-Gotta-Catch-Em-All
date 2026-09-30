---
name: reference-gps-joystick-control
description: "GPS Joystick (com.theappninjas.fakegpsjoystick 5.3.3) has an intent API (TELEPORT/WALK/SPEED/ROUTE/STATUS...), but every command is locked behind Pro or a rewarded-video window, and a locked command pops its unlock screen OVER PoGo."
metadata:
  node_type: memory
  type: reference
  originSessionId: 565701b0-1a11-42dd-894a-3bb423b9a491
  modified: 2026-09-25T05:19:23.631Z
---

**I have controlled it before.** In August the catcher's double-tap-to-move (`teleport()` in
`AutoCatcher/system/scripts/game_write/catch_loop_fast.py`, flag `/data/local/tmp/pogo_tap.on`) sent TELEPORT and landed
within ~1 m (Aug 21 Osaka, Aug 29 San Francisco). After a context compaction on 2026-09-25 I forgot this and
"rediscovered" the API. The user asked how I had tested without control. Read this file before touching the joystick.

**Commands:** `am start-foreground-service -n com.theappninjas.fakegpsjoystick/.service.OverlayService -a theappninjas.gpsjoystick.<ACTION>`
(extra types are from the dex, OverlayService.onStartCommand):
- TELEPORT `--ef lat --ef lng [--ef alt]` (floats, ~0.5 m precision). SPEED `--ef speed` (>0).
- WALK: `waypoints` (string), `speed` (float), `teleport` (bool).
- ROUTE `--es name`, plus reverse/loop/route_mode. ROUTE_PAUSE, ROUTE_RESUME, ROUTE_NEXT, ROUTE_PREV, STOP, HIDE, SHOW.
- FAVORITES `--es name`. RECORD_START, RECORD_ADD, RECORD_STOP `name` (needs at least 2 points).
- GENERATE: mode (int), marker_count (1-5000), offset (float >0).
- STATUS: the reply is a broadcast `theappninjas.gpsjoystick.STATUS_RESPONSE` with position, bearing, is_route_active/paused,
  route_remaining/total, is_running, is_hidden, is_recording. Failures broadcast `theappninjas.gpsjoystick.ERROR`
  (source_action, error, message).
- The same commands work as deep links `gpsjoystick://teleport?lat=..&lng=..` (walk, route, speed, stop, ...) via DeepLinkActivity.
  `geo:` links and map URLs open MainActivity.

**It is OFFICIAL and documented:** the "Pro Intents API" (theappninjas.com/docs/pro-intents-api/), with an ADB cheatsheet
(…/pro-intents-api/adb-commands/) and Tasker/MacroDroid guides. FREE: TELEPORT, ROUTE, STOP. PRO (active subscription):
WALK (`--es waypoints "lat,lng;lat,lng"`, `--ez teleport`, `--ef speed`), SPEED, STATUS, ROUTE_PAUSE/RESUME/NEXT/PREV,
HIDE/SHOW, FAVORITES, RECORD_*, GENERATE. Input numbers are floats; STATUS_RESPONSE outputs are doubles. STATUS has no deep link.
Double-tap-to-move only uses TELEPORT, which is free, so it never needed Pro.

**THE LOCK (2026-09-25 00:06):** the docs say a Pro command without Pro only broadcasts ERROR `PRO_REQUIRED`. The app
(5.3.3) actually starts MainActivity with `act=GATE_REQUIRED` ("Pro subscription or rewarded video") ON TOP OF POGO. It
checks Pro, or a rewarded-ad window via `content://…rewardwindow/window`. My STATUS test did this even though the user HAS
the Pro subscription (confirmed by the user 2026-09-25), so the running service didn't see Pro at that moment (cause
unknown; the joystick logs showed nothing). Cost: about 1.5 min of catching. Recovery that keeps the game session (same pid):
`monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1`. Rule: test Pro commands only when the user
isn't playing, and confirm the user wants it first.

**WHAT MAKES PRO DIFFERENT (the user bought Pro 2026-09-25 ~01:15; prefs diffed before vs after):** 4 NEW keys
appeared: `server_validated_tier` and `last_receipt_validation_ms` (the purchase receipt was server-validated; almost
certainly what the command lock checks), plus `rewarded_intent_watch_count` and `rewarded_intent_last_reset_date`
(the watch-an-ad unlock). `pro_subscription_active` and `remove_ads_subscription_active` were rewritten.
paid_storage_sp (paidv1/v2 old purchases) was unchanged. Before this, the user's "unlocked pro" had
pro_subscription_active but NO server_validated_tier, and every Pro command popped the lock screen. After:
STATUS goes through silently (tested 01:18 with PoGo closed). The STATUS_RESPONSE broadcast is not visible in
`dumpsys activity broadcasts history`; it needs a receiver.

**INCIDENT 2026-09-25 01:14-01:17 (real location reached PoGo):** during the Pro purchase the joystick's
`:overlay` process died, so spoofing stopped. Android then RELAUNCHED PoGo twice (am_proc_start
"next-top-activity" at 01:16:15 and 01:16:58), because PoGo's task sat under the joystick's screens and came back to
the front when they closed. It had the real Georgia fix. The catcher attached and threw 3 balls, and all 3 FLED
(p=0.94 included), the soft-ban signature. I force-stopped PoGo each time, then TELEPORT + launching the joystick
app brought the spoof back (overlay 4456, 01:17:19). The catcher's crash-loop breaker then held it for 30 min.
TELEPORT alone did NOT start the service while the app was dead (the docs: "app is in background" -- open the app).
**RULES:**
- Before ANY joystick UI work, force-stop PoGo.
- Never leave PoGo's task under joystick screens.
- Before letting PoGo run: check `pidof …:overlay` AND a fresh NY `last mock location`.
- If the overlay is gone, force-stop PoGo FIRST, then restart the spoof.

**Settings are unreadable on disk:** `shared_prefs/com.theappninjas.fakegpsjoystick_preferences.xml` values are Tink AES-GCM
ciphertext. The keyset in `gpsjoystick_pref_keyset_prefs.xml` is wrapped by an Android Keystore key. The key NAMES are
visible: walking/jogging/running speed, speed_offset, update/process/idle intervals, min/max moving/idle accuracy,
indirect/suspended mocking, auto_suspend_location, agps_reset, and so on. Reading the values needs its Settings screen,
which pulls PoGo out of the foreground, or an in-process read. Ask the user before doing either.

**THE SPEED BUG (measured 2026-09-25):** the movement loop runs on a Process Interval tick. It moves
`speed × UpdateInterval` only on a tick where at least UpdateInterval has passed since the last move. With the user's
750 ms / 1000 ms, a 5.0 m move landed every 1.5 s (0.75 s positions, alternating 0 / 5 m), so a real 12 km/h under an
18 km/h label, with stutter. Exact multiples (500/1000) risk random skips from ±1 ms jitter. The robust rule is
Update = Process − small margin. Set 2026-09-25 at the user's request ("smoothest, borderline fastest"): Process 250 ms,
Update 248 ms (real speed = 0.992 × setting), Speed Offset 0.5 → 0.1 km/h, Walking 3.0 → 5.0, Jogging 10.0 → 10.4
(real ≈ 10.3, label ≤ 10.5, egg-safe), Running 18.0 → 20.0. Unchanged: Idle Interval 1000 ms, idle ±2 m, heading ±7.5°,
altitude ±1.5 m, all accuracies 2.5 m, Save Last Location ON, Always Ignore Mock Location ON. **Settings load only when
movement restarts**: the running route kept 750/1000/18 after the edits. Its on-screen controls stay HIDDEN while any
GPS Joystick activity is open (my `su am start …SettingsActivity` launches stacked them). Settings screen: root
`am start -n com.theappninjas.fakegpsjoystick/.ui.settings.SettingsActivity`; each value is a dialog with an EditText
and OK. Never stop the joystick while PoGo is open: the real GPS would leak. Close PoGo first.
**Safe restart, verified 2026-09-25 00:38 (user approved):**
1. Record the spot with `dumpsys location`.
2. `am force-stop com.nianticlabs.pokemongo`.
3. Free `STOP` intent, then `am force-stop com.theappninjas.fakegpsjoystick`; that kills the stale `:overlay` process.
4. Free `TELEPORT --ef lat --ef lng` to the recorded spot. That starts a FRESH service; it landed 0.7 m off, about 10 s.
5. Free `ROUTE --es name "NY Long"` walks on from the current spot (no jump), in Walking mode.
6. HOME, then tap `jogging_button` on the overlay (`uiautomator dump --windows` finds it).
7. Reopen PoGo with `monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1`.
Result: a fix every 0.250 s, 0.7 m steps, REAL 10.33 km/h, LABEL 10.40 (10.31-10.50). Saved route names are readable as
plain strings in `files/default.realm` (T-DB, unencrypted): NY Long, NY Lower, Last Route, SF Route, …

**Speed reading:** each mock fix carries `vel` ≈ 18 km/h, but the positions advance at about 12.3 km/h (2026-09-25,
25 s sample). Measure real speed from successive `dumpsys location` fixes, using `et=` for time
([[reference-dumpsys-location-et-field]]). Android keeps no location history, so "the last minute" can only be sampled
forward. Spoof stack: [[project-pogo-spoof-stack]]. The server's spoof-app blacklist doesn't list this package:
[[reference-pogo-client-limits]].
