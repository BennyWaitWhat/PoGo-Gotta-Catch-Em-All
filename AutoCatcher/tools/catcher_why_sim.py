"""Offline test of why_idle() in catch_loop_fast.py -- the line the AutoCatcher app shows when it is switched on and
catching nothing (no phone): python tools/catcher_why_sim.py. Exit code 1 when any check fails."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, os.pardir, "system", "scripts", "game_write", "catch_loop_fast.py"), encoding="utf-8").read()
ns = {}
exec(re.search(r"^def why_idle\(.*?(?=^\n\ndef )", src, re.S | re.M).group(0), ns)
why_idle = ns["why_idle"]
failed = 0


def check(name, got, want):
    global failed
    ok = got == want
    failed += not ok
    print(("ok   " if ok else "FAIL ") + name.ljust(34), repr(got), "" if ok else f"  want {want!r}")


def hist(rows):   # (seconds ago, frame, opened, thrown, caught, heard), oldest first
    return [(1000.0 - ago, f, o, t, c, h) for ago, f, o, t, c, h in rows]


ok_map = {"vis": 4, "limit": {"spin": "ok"}}
check("too little history", why_idle(hist([(10, 1, 0, 0, 0, 0), (0, 9, 0, 0, 0, 0)]), ok_map, True, True), "")
check("catching normally", why_idle(hist([(60, 100, 0, 0, 0, 0), (30, 900, 12, 10, 9, 24), (0, 1800, 25, 22, 20, 50)]), ok_map, True, True), "")
check("opens with no answer",
      why_idle(hist([(60, 100, 10, 5, 5, 20), (30, 900, 22, 5, 5, 20), (0, 1800, 34, 5, 5, 20)]), ok_map, True, False),
      "the game is not answering: 24 encounters opened, 0 answered in the last minute")
check("...but not while catch is off",
      why_idle(hist([(60, 100, 10, 5, 5, 20), (30, 900, 22, 5, 5, 20), (0, 1800, 34, 5, 5, 20)]), ok_map, False, False), "")
check("the game left its map",
      why_idle(hist([(40, 500, 3, 3, 3, 6), (20, 500, 3, 3, 3, 6), (0, 500, 3, 3, 3, 6)]), ok_map, True, True),
      "paused: Pokemon GO is not showing its map (40 s) -- it only catches while the map is on screen")
check("nothing on the map",
      why_idle(hist([(60, 100, 3, 3, 3, 6), (30, 900, 3, 3, 3, 6), (0, 1800, 3, 3, 3, 6)]), {"vis": 0, "limit": {"spin": "ok"}}, True, True),
      "no Pokemon in range right now")
blocked = {"vis": 3, "limit": {"spin": "BLOCKED", "oorStreak": 6}}
check("spins refused",
      why_idle(hist([(60, 100, 0, 0, 0, 0), (30, 900, 12, 10, 9, 24), (0, 1800, 25, 22, 20, 50)]), blocked, True, True),
      "spins are being refused by the server (6 in a row, retrying every 30 s)")
check("spins refused, spin switched off",
      why_idle(hist([(60, 100, 0, 0, 0, 0), (30, 900, 12, 10, 9, 24), (0, 1800, 25, 22, 20, 50)]), blocked, True, False), "")
check("both at once",
      why_idle(hist([(60, 100, 10, 5, 5, 20), (30, 900, 22, 5, 5, 20), (0, 1800, 34, 5, 5, 20)]), blocked, True, True),
      "the game is not answering: 24 encounters opened, 0 answered in the last minute; "
      "spins are being refused by the server (6 in a row, retrying every 30 s)")
sys.exit(1 if failed else 0)
