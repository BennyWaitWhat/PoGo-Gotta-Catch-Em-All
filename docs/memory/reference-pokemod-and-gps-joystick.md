---
name: reference-pokemod-and-gps-joystick
description: What Pokemod Hal and GPS JoyStick Pro actually do on Benny's phone (checked 2026-09-30) -- which modules are on, where their log is, and the GPS JoyStick intents we drive the walk with.
metadata:
  type: reference
---

**Read Pokemod's own log before guessing what it does:** `/data/local/tmp/logs/logcat` (root) -- lines tagged
`[HAL INFO]` ("Enabling X...", "TransferOnCatch] Transfered Pokemon a/d/s"). It is the whole phone's logcat, written by a
`logcat -f ... -n10 -r9128` started with the game, and it ROTATES: ten ~9 MB files (`logcat`, `logcat.01` .. `.10`,
~5 min each while catching). Launch lines are gone about an hour after a launch -- grep `logcat*`, not one file.

**Modules ON (log, 2026-09-30 02:48 launch):** TransferOnCatch, FirstAidKit, MagicBag, PinapMaster, AutoQuests,
Spawn Booster, Instant Loading, virtual Go Plus (+VPGPTweaks), Eggspresso, InstantCatch, PerfectedThrow and more.
**OFF:** Performance Mode ("Loading" but no "Enabling" line; Benny picked turning it on, 2026-09-30 -- a toggle in the Hal menu; its settings are
encrypted (`Hawk2.xml`), so nothing here can set it).

What each one means for our tools:
- **TransferOnCatch releases most catches seconds after capture** (91 of 97 at 02:48-02:52) on its own IV filter.
  The cull only ever sees the survivors: "caught N" in the ladder counts survivors, not the catcher's catches. It is
  Benny's setting; asked once (A keep / B off / C keep PvP spreads) on 2026-09-30, no answer -- left as is.
- **FirstAidKit forces the game's frame rate** (`set_targetFrameRate: replacing target -1 with 90`). PoGo's own
  Native Refresh Rate toggle is overridden (`replacing target 120 with 90`). Benny said he'd drop it to 60; it was still 90
  at 03:20:58. The screen rendered at 60 Hz anyway (`dumpsys SurfaceFlinger` renderRate=60.00 Hz, 03:21), so the extra
  30 fps were never shown. Never count waits in frames: reward_catcher waits in ms since.
- **PinapMaster feeds Pinaps too** -> our catcher's Pinap use is OFF (`CFG["pinap"] = False`, "pause autocatcher use
  for it now"). Razz stays ours.
- **AutoQuests' claim option is what puts reward Pokemon in limbo** for the reward catcher (Benny: "Leave it").
- **Virtual Go Plus spinning is the ball supply** (our spin flag is off).

**GPS JoyStick Pro Intents API** (`com.theappninjas.fakegpsjoystick`, docs: theappninjas.com/docs/pro-intents-api/):
`adb shell am start-foreground-service -a theappninjas.gpsjoystick.SPEED --ef speed 22.0` changes the speed of the
running route within ~3 s (tested 20 -> 22 -> 20, 2026-09-30). Also WALK (waypoints), ROUTE (saved route by name),
ROUTE_PAUSE / ROUTE_RESUME, TELEPORT, STATUS (its reply is a broadcast adb cannot catch -- read
`dumpsys location` "last mock location" for lat, lng, vel m/s, bearing instead). Its prefs are encrypted.
`AutoCatcher/tools/speed_governor.py` drives only SPEED: 28 km/h (the cap), 16 for 20 s after a Pokemon escapes out
of range. No slow-down for a busy screen (03:08-03:16 it saved 0 escapes). Sends nothing on a jump, outside Midtown, when
stopped, when the joystick's `:overlay` process is gone or a JoyStick screen is in front. Restores 20 on exit. Benny's route 2026-09-30: Bryant Park
<-> Central Park, back and forth, 20 km/h. His real location is near Atlanta: the walk is spoofed -- never teleport.

Related: [[pogo-on-phone-catcher]], [[pogo-field-research-reward-catcher]], [[feedback-check-before-saying]].
