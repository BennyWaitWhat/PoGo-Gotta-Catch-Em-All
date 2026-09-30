---
name: reference-midtown-dense-loop
description: The Midtown dense loop (2026-09-30) -- where the catcher catches most per km, the lap-length rule, and the tools that plan it, send it to GPS JoyStick and map it.
metadata:
  type: reference
---

**Benny 2026-09-30:** "Only walk thru high density high lure areas exclusively. Map everything from mid Central Park
to Bryant Park ... I'm sure there's a super fancy formula or tactics you can do".

**Measured, not assumed** (speed_governor CSV: mock fix + the catcher's `caught` counter every 5 s, old route
Bryant Park <-> Central Park at 28 km/h, 03:08-03:31): Bryant Park 58 caught/km, 42nd-50th St 41-63/km,
50th-57th 27/km, 57th-60th 16/km, **Central Park 24/km**. Midtown beat the park about 2 to 1.
Historic spawn positions are too thin to map (the server no longer sends spawn points; spawns.jsonl has 27 wild
rows), so the catcher's own catches per km are the density measure.

**The formula:** a wild spawn stays up ~30 min and each spawn point fires once an hour (player-mapped rule, not
measured here). A lap shorter than ~30 min re-walks blocks whose spawns it already caught; a much longer lap lets
spawns expire unseen. So: densest ground, one loop of ~25-30 min at the speed cap, no block twice per lap, one lane
per avenue (avenues ~270 m apart, the game shows Pokemon within ~140 m).

**The loop** (`AutoCatcher/tools/dense_loop.py`): 8th, 7th, 6th, 5th, Park, 3rd Ave between 32nd and 53rd St, back
along 42nd St. 11.45 km, ~25 min at 28 km/h. `--send` hands it to GPS JoyStick `WALK` (`--ez teleport false`),
starting at the corner nearest the fix, 2 laps. Sent 03:35:36: no jump, PoGo stayed in front, no Pro gate.
**Result (the catcher's own 5-min run lines):** lap 1 (03:36-04:01) 23.4 caught/min; lap 2 until the bag filled
(04:01-04:11) 22.9/min -- the same, so a 25-min lap does NOT come back to cleared blocks. Old route: 15.7/min
(03:16-03:35). So ~+50% from where you walk alone, at the same 28 km/h.
**The bag is the limit:** it filled ~04:13 (catcher `HOLD ...: Pokemon storage is full`, catches stopped, 'gone'
climbed +300 by 05:31) after ~1,340 catches since the catcher's 03:02 start. Transfer on Catch keeps only a few
(6 of 97 at 02:48-02:52), yet the bag still fills: cull + release before a long run.
The governor now ignores 'gone' while the catcher holds on a full bag (it read every lost Pokemon as an escape
and sat at 16 km/h) and prints BAG FULL once. OpenStreetMap trap: `manhattan_ways.json` includes New Jersey (a Park Ave
& 42nd St in Weehawken), so corners are clipped to a Midtown box; Park Ave meets 42nd St only on the viaduct.

**Map page:** `tools/catch_map.py` (template `tools/catch_map.html`) -> https://claude.ai/artifact/X896FsYaPb2YbM4nTzGXRZ
(streets, Central Park paths, 1,725 stops/gyms, lure history, catches per km along the walk, the loop, you).
The governor's corridor now covers 30th-60th St, 9th-3rd Ave (`CORRIDOR`), and a SIGTERM restores 20 km/h.

To go back to Benny's own route: pick it in the GPS JoyStick app (its saved name wasn't read).
Related: [[reference-pokemod-and-gps-joystick]], [[reference-gps-joystick-control]], [[reference-pogo-client-limits]].
