---
name: reference-pogo-client-limits
description: "Every client-side PoGo limit/threshold was dumped live 2026-09-24 (GlobalSettingsProto + 143 game-master settings) — tools, key values, and the server-sent spoof-app blacklist."
metadata:
  node_type: memory
  type: reference
  originSessionId: 565701b0-1a11-42dd-894a-3bb423b9a491
  modified: 2026-09-25T04:09:15.058Z
---

Dumped 2026-09-24 from game 0.429.1 (read-only Frida pass, PoGo survived):
- `AutoCatcher/tools/dump_game_limits.py` -> `system/analysis/game_limits.json` (GlobalSettingsProto + GameMasterData's
  `Dictionary<System.Type, IMessage>`, 143 objects, 2605 values). Object memory is read in JS; inline generic value
  types are skipped (passing them to il2cpp_object_get_class crashed PoGo once).
- `AutoCatcher/tools/limits_report.py` -> `system/analysis/game_limits.html` (the user's report; API keys redacted).

Key values: driving warning 8.9408 m/s (20 mph), 10 samples 10 s apart, 7 min cooldown; idle threshold 3 m/s;
visible = encounter range 140 m; GMO refresh 5 s / 10 m; stop interaction 80 m (far 2 km, remote 3.5 km); route
recording max 20 m/s; SoftSfida pacing 8 s per catch / per spin. The egg/buddy/Adventure Sync speed cap and soft-ban
cooldowns are server-only and NOT in the client (~10.5 km/h is a community measurement, not a dumped value).

`GlobalSettings.ClientAppBlacklist` (sent by the server) lists 5 spoof packages, including `com.theappninjas.gpsjoystick`.
The user's joystick is `com.theappninjas.fakegpsjoystick`, which is NOT on the list (it's a different package; I didn't trace how the client
matches the list). Re-check this after updates, since the server can change the list. See [[project-pogo-spoof-stack]].

**Hard-coded constants, dumped 2026-09-25:** `tools/dump_game_constants.py` produced `game_constants.json`, and
`constants_report.py` built the `.html`. The class walk runs in C (a CModule, in budgeted steps: 1.5 s total, slowest
step 17 ms, PoGo survived next to the catcher). Consts come from metadata via il2cpp_field_static_get_value, used on
LITERAL fields only; on anything else it would run the class constructor. static readonly values are read raw from
`Il2CppClass.static_fields @0xb8`, an offset proven with Vector3 up/one/forward; `il2cpp_class_get_static_field_data` also
exists. Result: 2,425 values, 1,810 of them with scrambled names. Movement is almost all server-side. The one speed
constant: `Map.SpeedService` hard-codes 10, 2.5, 5.0 and 8.9408 (20 mph). `MapPokemon.CATCH_POKEMON_RPC_TIMEOUT_SEC` = 5.
See [[feedback-one-phone-pass-not-three]].
