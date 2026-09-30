---
name: reference-pokemod-and-gps-joystick
description: What Pokemod Hal and GPS JoyStick Pro actually do on Benny's phone (checked 2026-09-30) -- which modules are on, where their log is, and the GPS JoyStick intents we drive the walk with.
metadata:
  type: reference
---

**Read Pokemod's own log before guessing what it does:** `/data/local/tmp/logs/logcat` (root) -- lines tagged
`[HAL INFO]` ("Enabling X...", "TransferOnCatch] Transfered Pokemon a/d/s"). It restarts with each game launch.

**Modules ON (log, 2026-09-30 02:48 launch):** TransferOnCatch, FirstAidKit, MagicBag, PinapMaster, AutoQuests,
Spawn Booster, Instant Loading, virtual Go Plus (+VPGPTweaks), Eggspresso, InstantCatch, PerfectedThrow and more.
**OFF:** Performance Mode (Benny picked it on 2026-09-30 -- it is a toggle in the Hal menu; its settings are
encrypted (`Hawk2.xml`), so nothing here can set it).

What each one means for our tools:
- **TransferOnCatch releases most catches seconds after capture** (91 of 97 at 02:48-02:52) on its own IV filter.
  The cull only ever sees the survivors: "caught N" in the ladder counts survivors, not the catcher's catches. It is
  Benny's setting; asked once (A keep / B off / C keep PvP spreads) on 2026-09-30, no answer -- left as is.
- **FirstAidKit forces the game's frame rate** (`set_targetFrameRate: replacing target -1 with 90`). PoGo's own
  Native Refresh Rate toggle is overridden. Benny set 60. Never count waits in frames: reward_catcher waits in ms since.
- **PinapMaster feeds Pinaps too** -> our catcher's Pinap use is OFF (`CFG["pinap"] = False`, "pause autocatcher use
  for it now"). Razz stays ours.
- **AutoQuests' claim option is what puts reward Pokemon in limbo** for the reward catcher (Benny: "Leave it").
- **Virtual Go Plus spinning is the ball supply** (our spin flag is off).

**GPS JoyStick Pro Intents API** (`com.theappninjas.fakegpsjoystick`, docs: theappninjas.com/docs/pro-intents-api/):
`adb shell am start-foreground-service -a theappninjas.gpsjoystick.SPEED --ef speed 22.0` changes the speed of the
running route within ~3 s (tested 20 -> 22 -> 20, 2026-09-30). Also WALK (waypoints), ROUTE (saved route by name),
ROUTE_PAUSE / ROUTE_RESUME, TELEPORT, STATUS (its reply is a broadcast adb cannot catch -- read
`dumpsys location` "last mock location" for lat, lng, vel m/s, bearing instead). Its prefs are encrypted.
`AutoCatcher/tools/speed_governor.py` drives only SPEED (cap 28 km/h; slows to 16 when the catcher backs up;
hands off on a jump, outside Midtown or when stopped; restores 20 on exit). Benny's route 2026-09-30: Bryant Park
<-> Central Park, back and forth, 20 km/h. His real location is near Atlanta: the walk is spoofed -- never teleport.

Related: [[pogo-on-phone-catcher]], [[pogo-field-research-reward-catcher]], [[feedback-check-before-saying]].
