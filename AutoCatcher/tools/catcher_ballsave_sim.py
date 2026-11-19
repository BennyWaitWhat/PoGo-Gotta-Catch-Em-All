"""Offline test of the BALL-SAVER and of STARDUST ONLY in catch_loop_fast.py (no phone): python tools/catcher_ballsave_sim.py
Python side: the greedy cut (ballsave_skip) and the ball count (usable_balls); the stardust switch, its species table (and
the child process that keeps it current), the weather-boost record. JS side (node): the species list from the config, a spawn left alone counted once, its 20 s
look-again, its ledger record, the shiny look, the weather flag. Exit code 1 when any check fails."""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, os.pardir, "system", "scripts", "game_write", "catch_loop_fast.py"), encoding="utf-8").read()
import time
ns = {"CFG": {"floors": {"1": 5, "2": 5, "3": 5}}, "_BS": {"mtime": None, "plan": None, "note": "off"}, "re": re, "time": time,
      "SP": {"on": False, "off": False, "since": None, "bare": 0}, "SHINYFIELD": {"ok": True}, "os": os, "json": json}
# STARDUST ONLY: no switch file and no table until its own section below = off, so everything before it runs as it always did
NODUST = os.path.join(tempfile.gettempdir(), "pogo_dust_sim_no_such_file")
ns.update(DUST_FILE=NODUST + ".on", DUST_TABLE=NODUST + ".json", DUST_LEVELS=NODUST + ".txt", WX_PROOF=NODUST + ".proof",
          AN=tempfile.gettempdir(), su=lambda cmd, timeout=10: "")
for name in ("usable_balls", "ballsave_skip", "plan_reserve", "plan_live", "floor_short", "reserve_floors", "ballsave_reserve",
             "ballsave_now", "ballsave_log", "cfg_now", "sp_bare_odd", "sp_paid", "starpiece_seen", "balls_why", "starpiece_why", "berry_mode",
             "state_extra", "dust_min", "dust_levels_text", "dust_levels_write", "dust_table", "wx_judge", "wx_verdict", "wx_load",
             "wx_seen", "wx_close", "wx_tick", "game_version", "dust_boost_note", "dust_skip", "dust_news", "dust_log", "dust_only",
             "dust_why", "shiny_look", "dust_state", "dust_checked", "dust_update_said", "dust_update_step",
             "dust_update"):   # (wx_load's text ends with the WX_CATCH pattern that follows it)
    exec(re.search(rf"^def {name}\(.*?(?=^\n\ndef )", src, re.S | re.M).group(0), ns)
for pat in (r"^SPIN_WHY = .*$", r"^WX = .*$", r"^WX_NEED = \d+", r"^SP_MULTS = .*$"):
    exec(re.search(pat, src, re.M).group(0), ns)
exec(re.search(r"^_DUST = \{.*?\}\n", src, re.S | re.M).group(0), ns)
skip_of, usable = ns["ballsave_skip"], ns["usable_balls"]
failed = 0


def check(name, got, want):
    global failed
    ok = got == want
    failed += not ok
    print(("ok   " if ok else "FAIL ") + name.ljust(44), repr(got), "" if ok else f"  want {want!r}")


NOW = 1_800_000_000.0
# Minior 2,500 stardust per ball at 4 balls/min, a bonus species 1,300 at 2, two ordinary ones 380 at 12 and 150 at 8
PLAN = {"end": NOW + 100 * 60, "margin": 1.0,
        "species": {"774": [2500, 4.0], "316": [1300, 2.0], "10": [380, 12.0], "41": [150, 8.0]}}
check("enough balls for all: catch everything", skip_of(PLAN, 2600, NOW)[0], [])
check("the last one gets what is left (100)", skip_of(PLAN, 1900, NOW)[0], [])
check("short: the worst per ball goes first", skip_of(PLAN, 1700, NOW)[0], [41])
check("one ball over the top two: #10 gets it", skip_of(PLAN, 601, NOW)[0], [41])
check("exactly the top two's need: rest alone", skip_of(PLAN, 600, NOW)[0], [10, 41])
check("tight: Minior only", skip_of(PLAN, 300, NOW)[0], [10, 41, 316])
check("Minior is never dropped while balls last", skip_of(PLAN, 1, NOW)[0], [10, 41, 316])
check("less time left = more kept", skip_of(PLAN, 600, NOW + 60 * 60)[0], [41])
check("no margin at 900", skip_of(PLAN, 900, NOW)[0], [41])
check("margin 1.5 at 900 reserves more", skip_of(dict(PLAN, margin=1.5), 900, NOW)[0], [10, 41])
check("end time passed: catch everything", skip_of(PLAN, 10, NOW + 101 * 60), ([], "off: the plan's end time has passed"))
check("no plan", skip_of(None, 10, NOW), ([], "off"))
check("balls not read yet", skip_of(PLAN, None, NOW), ([], "waiting for the ball count"))
check("unreadable plan", skip_of({"bad": 1}, 10, NOW), ([], "off: unreadable plan"))
check("the why line", skip_of(PLAN, 1700, NOW)[1], "1700 balls for 100 min: leaving 1 of 4 species alone (at most 150 stardust per ball)")
check("balls above the floors", usable({"1": 1704, "2": 5, "3": 9}), 1703)
# a reserve: the greedy budget is the balls minus the ones kept back
check("reserve 100: 700 balls act like 600", skip_of(dict(PLAN, reserve=100), 700, NOW)[0], skip_of(PLAN, 600, NOW)[0])
check("reserve: balls at the reserve keep nothing", skip_of(dict(PLAN, reserve=100), 100, NOW)[0], [10, 41, 316, 774])
check("reserve in the why line", skip_of(dict(PLAN, reserve=100), 700, NOW)[1],
      "600 balls to spend for 100 min, 115 kept in all: leaving 2 of 4 species alone (at most 380 stardust per ball)")
check("balls not read", usable({}), None)
# "keep": N balls IN ALL (Benny 11-16 "keep just 50 balls"): the floors' 5+5+5 count toward it -> 35 on top of them
check("keep 50 = reserve 35 on top of 5/5/5", ns["plan_reserve"](dict(PLAN, keep=50)), 35)
check("keep 50: 635 balls act like 600", skip_of(dict(PLAN, keep=50), 635, NOW)[0], skip_of(PLAN, 600, NOW)[0])
check("keep in the why line", skip_of(dict(PLAN, keep=50), 635, NOW)[1],
      "600 balls to spend for 100 min, 50 kept in all: leaving 2 of 4 species alone (at most 380 stardust per ball)")
check("keep wins over reserve", ns["plan_reserve"](dict(PLAN, keep=50, reserve=50)), 35)
check("keep below the floors: nothing extra", ns["plan_reserve"](dict(PLAN, keep=10)), 0)
check("below the reserve: 0 to spend, all left", skip_of(dict(PLAN, keep=50), 20, NOW), ([10, 41, 316, 774],
      "0 balls to spend for 100 min, 50 kept in all: leaving 4 of 4 species alone (at most 2500 stardust per ball)"))
check("ended with a keep: still holds them", skip_of(dict(PLAN, keep=50), 300, NOW + 101 * 60),
      ([], "the plan ended: catching everything above the 50 balls kept in all"))
check("spin-only why = NOT SPINNING", ("spins are being refused by the server (6 in a row)".startswith(ns["SPIN_WHY"]),
                                       "the game is not answering: 9 encounters opened".startswith(ns["SPIN_WHY"])), (True, False))

# ---- STAR PIECE: an award with one is not a multiple of 25; two bare catches in a row after one with it = it ran out
sp_lines = []
seen = lambda dust: ns["starpiece_seen"](f"20:45:57 CATCH Wild #774 ball=1 p=0.24 att=1 berry=0 0.6s dust={dust} candy=3", sp_lines.append)
seen(225); seen(225); seen(2025)
check("no Star Piece all day: silent", (sp_lines, ns["SP"]["off"]), ([], False))
seen(3037); seen(2025)
check("one bare catch: not yet", ns["SP"]["off"], False)
seen(337); seen(225); seen(2025)
check("two bare in a row: off, one line", (ns["SP"]["off"], len(sp_lines)), (True, 1))
seen(2025); seen(225)
check("still off: no more lines", len(sp_lines), 1)
ns["starpiece_seen"]("20:47:01 BALLSAVE 85 balls to spend", sp_lines.append); seen(50)
check("other lines and tiny awards ignored", len(sp_lines), 1)
seen(3037)
check("a Star Piece again: on, one line", (ns["SP"]["off"], len(sp_lines), sp_lines[-1][:13]), (False, 2, "STARPIECE on "))
# drain() hands the JS lines over WITHOUT a time (review 11-16: the first regex wanted one and could never fire)
ns["SP"].update(on=False, off=False, since=None, bare=0)
raw = lambda dust: ns["starpiece_seen"](f"CATCH Wild #774 ball=1 p=0.24 att=1 berry=0 0.6s dust={dust} candy=3", sp_lines.append)
raw(3037); raw(2025); raw(225)
check("untimed JS lines: off, one line", (ns["SP"]["off"], sp_lines[-1][:14]), (True, "STARPIECE off:"))
ns["SP"].update(on=False, off=False, since=None, bare=0)

# ---- the reserve spread over the bag (review 11-16: on the Poke floor alone, Great/Ultra could run under the keep)
rfl = ns["reserve_floors"]
check("reserve over the bag: Poke, then Great", rfl(35, {"1": 20, "2": 60, "3": 10}), {"1": 20, "2": 25, "3": 5})
check("a short floor is made up (keep 50 = 50)", rfl(35, {"1": 100, "2": 3, "3": 5}), {"1": 42, "2": 5, "3": 5})
check("counts not read: all on the Poke floor", rfl(35, {}), {"1": 40, "2": 5, "3": 5})
check("fewer balls than the keep: all held", rfl(35, {"1": 10, "2": 6, "3": 5}), {"1": 39, "2": 6, "3": 5})

# ---- the plan file, priority species, and the BALLSAVE log lines
tmp = tempfile.mkdtemp()
pf = os.path.join(tmp, "plan.json")
ns.update(BALLSAVE_FILE=pf, BALLS={"usable": 1700}, _BS={"mtime": None, "plan": None, "note": "off"}, os=os, json=json, time=time,
          CFG={"floors": {"1": 5, "2": 5, "3": 5}, "priority": [41]})
lines = []
log = lambda now: ns["ballsave_log"](lines.append, now)
check("no plan file: nothing left alone", ns["ballsave_now"](), [])
log(0)
check("no plan file: no log line", lines, [])
json.dump(dict(PLAN, end=time.time() + 100 * 60), open(pf, "w"))
check("priority species never left alone", ns["ballsave_now"](), [])   # #41 is the cut (1700 balls) but a priority species
ns["CFG"]["priority"] = []
os.utime(pf, (time.time() + 5, time.time() + 5))                        # same file, new mtime: re-read
check("plan read: the cut", ns["ballsave_now"](), [41])
log(100)
check("one line when it starts", len(lines), 1)
ns["BALLS"]["usable"] = 1699
ns["ballsave_now"]()
log(130)
check("cut moves within a minute: quiet", len(lines), 1)
log(161)
check("a minute later: one line", len(lines), 2)
open(pf, "w").write("{not json")
os.utime(pf, (time.time() + 9, time.time() + 9))
ns["ballsave_now"]()
log(162)
check("unreadable plan: logged at once", lines[-1], "BALLSAVE off: unreadable plan")
os.remove(pf)
ns["ballsave_now"]()
log(163)
check("plan deleted: one 'off' line", lines[-1], "BALLSAVE off")
log(300)
check("then silent", len(lines), 4)

# the reserve rides on the Poke Ball floor while a plan file is on the phone (also after its end time)
NOFILE = os.path.join(tempfile.gettempdir(), "pogo_berries_sim_no_such_file.on")   # the berries switch: missing = none
ns.update(FLAGS={"berries": NOFILE}, flag=lambda k: False)
ns["CFG"].update(floors={"1": 5, "2": 5, "3": 5})
json.dump(dict(PLAN, end=time.time() - 60, reserve=100), open(pf, "w"))
os.utime(pf, (time.time() + 20, time.time() + 20))
ns["CFG"].update(mightyKeep=30)
c = ns["cfg_now"]()
check("reserve 100 pushed (JS spreads it), end passed", (c["floors"], c["reserve"], c["skipSp"]), ({"1": 5, "2": 5, "3": 5}, 100, []))
check("ended plan: no shiny look, Mighty hold back", (c["peek"], c["mightyBalls"], c["mightyKeep"]), (False, 30, 30))
json.dump(dict(PLAN, end=time.time() + 600, keep=50), open(pf, "w"))
os.utime(pf, (time.time() + 30, time.time() + 30))
c = ns["cfg_now"]()
check("live plan, keep 50: reserve 35 + shiny look", (c["floors"], c["reserve"], c["peek"]), ({"1": 5, "2": 5, "3": 5}, 35, True))
check("live plan: no Mighty ball hold; Razz hold kept", (c["mightyBalls"], c["mightyKeep"]), (0, 30))
os.remove(pf)
c = ns["cfg_now"]()
check("plan deleted -> no reserve", (c["floors"], c["reserve"]), ({"1": 5, "2": 5, "3": 5}, 0))
# a plan file with numbers no int() can take must not stop the 1-second loop (review 11-16: OverflowError)
json.dump({"end": 10 ** 400, "keep": 1e999, "species": {"10": [10 ** 400, 1.0]}}, open(pf, "w"))
os.utime(pf, (time.time() + 35, time.time() + 35))
try:
    c = ns["cfg_now"]()
    check("inf in the plan: no crash", (c["reserve"], ns["_BS"]["note"]), (0, "off: unreadable plan"))
except Exception as ex:   # noqa: BLE001
    check("inf in the plan: no crash", repr(ex), "no exception")
os.remove(pf)
ns["cfg_now"]()
# a bag short of Great Balls: the keep makes up the floor, and the saver's budget counts it too
json.dump(dict(PLAN, end=time.time() + 100 * 60, keep=50), open(pf, "w"))
os.utime(pf, (time.time() + 40, time.time() + 40))
ns["BALLS"].update(usable=95, items={"1": 100, "2": 3, "3": 5})
c = ns["cfg_now"]()
check("short floor: 58 to spend, reserve 35", (ns["_BS"]["note"][:16], c["reserve"]), ("58 balls to spen", 35))
ns["SHINYFIELD"]["ok"] = False
check("no shiny field at attach: no shiny look", ns["cfg_now"]()["peek"], False)
ns["SHINYFIELD"]["ok"] = True
# the attach check (session_loop): a read distrusted earlier in the run stays off; a later attach that resolves it is on
blk = re.search(r'    mk = st.get\("mighty"\) or \{\}.*?\n    elif SHINYFIELD\["suspended"\]:\n.*?\n', src, re.S).group(0)
att = "\n".join(ln[4:] for ln in blk.splitlines())
said, wxl = [], []
good = {"mighty": {"wildPokemon": 16, "display": 24, "flag": 40, "shiny": 32}}
attenv = lambda st, sf: {"st": st, "SHINYFIELD": sf, "w": said.append, "wx_load": lambda key, found: wxl.append((key, found)),
                         "game_version": lambda pid: "0.435.2", "pid": 4711}
env = attenv(good, {"ok": True, "suspended": True})
exec(att, env)
check("distrusted earlier in the run: stays off", (env["SHINYFIELD"]["ok"], said[-1][:20]), (False, "SHINY LOOK stays off"))
env = attenv(good, {"ok": False, "suspended": False})
exec(att, env)
check("resolved at a later attach: on again", env["SHINYFIELD"]["ok"], True)
check("the attach marks its shiny check as run (STARDUST ONLY leaves nothing alone before it)", env["SHINYFIELD"].get("checked"), True)
env = attenv({"mighty": dict(good["mighty"], wx=36)}, {"ok": False, "suspended": False})
exec(att, env)
check("the attach hands the weather read its key (game version + offsets) and whether its field was found",
      wxl, [("0.435.2 offsets 16/24/None", False), ("0.435.2 offsets 16/24/None", False), ("0.435.2 offsets 16/24/36", True)])
check("the attach pushes its shiny outcome either way",
      bool(re.search(r"\n    cfg = cfg_now\(\)\n    sc\.exports_sync\.cfg\(cfg\)", src)), True)
check("a 'SHINY LOOK suspended' line turns it off for the run",
      bool(re.search(r'if line\.startswith\("SHINY LOOK suspended"\):[^\n]*\n\s+SHINYFIELD\.update\(ok=False, suspended=True\)', src)), True)
# berries (Benny 11-16 22:14 "stop auto feeding berries for now"; 11-18 "start catching with only pinap berries fed"):
# the switch file says what may be fed -- 1 = Pinap and Razz as configured, pinap / razz = only that one, else none
ns["CFG"].update(pinap=True, razz=True)
c = ns["cfg_now"]()
check("berries switch missing: no Pinap, no Razz", (c["pinap"], c["razz"], c["berries"]), (False, False, ""))
check("berries switch: the config itself is not touched", (ns["CFG"]["pinap"], ns["CFG"]["razz"]), (True, True))
bdir = tempfile.mkdtemp()
ns.update(FLAGS={"berries": os.path.join(bdir, "pogo_berries.on")})
for text, want in (("1", (True, True, "on")), ("1\n", (True, True, "on")), ("pinap\n", (True, False, "pinap")),
                   (" PINAP ", (True, False, "pinap")), ("razz", (False, True, "razz")), ("0", (False, False, "")),
                   ("", (False, False, "")), ("yes", (False, False, "")), ("pinap razz", (False, False, ""))):
    with open(ns["FLAGS"]["berries"], "w") as fh:
        fh.write(text)
    c = ns["cfg_now"]()
    check(f"berries switch {text!r}: Pinap, Razz, mode", (c["pinap"], c["razz"], c["berries"]), want)
ns["CFG"].update(razz=False)
with open(ns["FLAGS"]["berries"], "w") as fh:
    fh.write("1")
c = ns["cfg_now"]()
check("berries switch on: never turns on what the config has off", (c["pinap"], c["razz"]), (True, False))
ns["CFG"].update(razz=True)
os.remove(ns["FLAGS"]["berries"])
os.rmdir(bdir)
ns.update(FLAGS={"berries": NOFILE}, flag=lambda k: False)
check("the toggles line names the berry mode", "{k}={c[k] if isinstance(c[k], str) and c[k] else 'on' if c[k] else 'off'}" in src, True)
# the app's status card (app 1.3): optional keys after the old counters -- a number not reported yet is left out
sx = ns["state_extra"]
check("status keys: all known", sx(109, {"dust": 74725}, {"1": 2280, "2": 6, "3": 6, "705": 202, "701": 10}, 474.2, True),
      "rate=13.8 up=474 dust=74725 balls=2280/6/6 pinap=202 razz=10 sp=1")
check("status keys: a ball count not read yet (-1) -> no balls key; no Star Piece catch yet -> no sp key",
      sx(0, {"dust": 0}, {"1": -1, "2": 5, "3": 5, "705": 0}, 30, None), "rate=0.0 up=30 dust=0 pinap=0")
check("status keys: the run's first second, an empty bag reading, the last catch bare",
      sx(0, {}, {}, 0.4, False), "sp=0")
check("status keys: no '=' with a space in it, no 'why=' (the app splits on spaces; why= must stay last)",
      all("=" in t and not t.startswith("why=") for t in sx(5, {"dust": 9}, {"1": 1, "2": 2, "3": 3}, 61, False).split()), True)
check("the status line carries them, before why=",
      'cooling={sp[\'cooling\']} "\n                + state_extra(c, st, it, time.time() - t0, SP.get("last"), dust_only(), dust_checked(time.time()))).rstrip())' in src, True)
sp0 = dict(ns["SP"])
ns["SP"].update(on=False, off=False, since=None, bare=0, last=None)
ns["starpiece_seen"]("CATCH Wild #1 ball=1 p=0.5 att=1 berry=0 0.5s dust=50 candy=3", lambda s: None)
check("Star Piece chip: an award under 100 says nothing", ns["SP"]["last"], None)
ns["starpiece_seen"]("CATCH Wild #1 ball=1 p=0.5 att=1 berry=705 0.5s dust=337 candy=6", lambda s: None)
check("Star Piece chip: 337 = with one", ns["SP"]["last"], True)
ns["starpiece_seen"]("CATCH Wild #1 ball=1 p=0.5 att=1 berry=705 0.5s dust=225 candy=6", lambda s: None)
check("Star Piece chip: 225 = without (at the first bare catch, before the 2-in-a-row STARPIECE line)",
      (ns["SP"]["last"], ns["SP"]["off"]), (False, False))
ns["SP"].clear()
ns["SP"].update(sp0)
# why no ball is thrown (the app shows it): the plan's balls IN ALL, and a shiny's promise only while it can keep it
ns["CFG"].update(mightyKeep=30)
ns["flag"] = lambda k: k == "catch"
bw = lambda it: ns["balls_why"](it, {"hold": 0, "holdWhy": ""})
check("at the keep: keeping 50, a shiny gets one", bw({"1": 40, "2": 5, "3": 5}),
      "keeping the last 50 balls (the ball-saver's plan): 40 Poke, 5 Great, 5 Ultra left -- a shiny still gets one")
check("a shiny took one: holding 49 of 50", bw({"1": 39, "2": 5, "3": 5}),
      "holding the last 49 balls (the ball-saver's plan keeps 50): 39 Poke, 5 Great, 5 Ultra left -- a shiny still gets one")
check("Great Balls above the keep: no why", (bw({"1": 40, "2": 9, "3": 5}), bw({"1": 60, "2": 5, "3": 5})), ("", ""))
ns["flag"] = lambda k: False
check("catch off: no shiny promise", bw({"1": 40, "2": 5, "3": 5}).endswith("Ultra left"), True)
check("live plan: no 'kept for Mighty' line (no hold then)",
      ns["balls_why"]({"1": 3, "2": 40, "3": 40}, {"hold": 0, "holdWhy": "", "mightyOn": True}), "")
check("cfg_now: Mighty ball hold 0 live, Razz hold kept", (ns["cfg_now"]()["mightyBalls"], ns["cfg_now"]()["mightyKeep"]), (0, 30))
ns["SP"].update(on=True, off=True, since="20:45:57")
spw = lambda why: ns["starpiece_why"](why, time.time())
check("Star Piece out + spins refused: both", spw("spins are being refused by the server (6 in a row)"),
      "the Star Piece ran out at 20:45:57: catches pay a third less stardust; spins are being refused by the server (6 in a row)")
check("a catching problem is never hidden", spw("the game is not answering: 9 encounters opened"), "the game is not answering: 9 encounters opened")
os.remove(pf)
ns["ballsave_now"]()
check("no plan: no Star Piece line", spw(""), "")
ns["SP"].update(on=False, off=False, since=None, bare=0)

# ================= STARDUST ONLY (Benny 2026-11-18) =================
# "i also want a catch mode that only catches high stardust pokemon (+ shinies) that can be toggled on"; "make sure you're
# inclusive of EVERY higher than avg stardust pokemon for that mode"; "yes include weather boosted too".
# /data/local/tmp/pogo_dust.on: 0 / missing / not a whole number = off; 1 = every species above a normal catch; N = of
# those, the ones paying N or more. Always caught: shinies, Mighty, priority species, a species the table does not know.
import shutil
GW = os.path.join(HERE, os.pardir, "system", "scripts", "game_write")
BUILDER, REAL = os.path.join(GW, "catch_dust_table.py"), os.path.join(GW, "catch_dust.json")
sys.path.insert(0, GW)
import catch_dust_table as dt  # noqa: E402  (the table's builder: its text format and its reader)
rb = subprocess.run([sys.executable, BUILDER, "--selftest"], capture_output=True, text=True)
check("dust table builder: its own self-test", (rb.returncode, len(re.findall(r"(?m)^FAIL ", rb.stdout)), len(re.findall(r"(?m)^ok ", rb.stdout)) >= 40), (0, 0, True))
rc = subprocess.run([sys.executable, BUILDER, "--check"], capture_output=True, text=True)
check("dust table in git: header counts = body, exactly as the builder writes it", (rc.returncode, rc.stdout[:5]), (0, "ok   "))

dd = tempfile.mkdtemp()
sw, tb, lv = os.path.join(dd, "pogo_dust.on"), os.path.join(dd, "catch_dust.json"), os.path.join(dd, "pogo_dust_levels.txt")
su_calls = []


def fake_su(cmd, timeout=10):   # root's part of dust_levels_write: copy in, chmod, rename
    su_calls.append(cmd)
    m = re.match(r"cp (\S+) (\S+)\.new && chmod 644 (\S+)\.new && mv -f (\S+)\.new (\S+); rm -f (\S+)$", cmd)
    if m and m.group(2) == m.group(3) == m.group(4) == m.group(5):
        shutil.copyfile(m.group(1), m.group(5))
        os.remove(m.group(6))
    return ""


lit = {}   # the catcher's own starting values (the checks above have already looked for a table once)
exec(re.search(r"^_DUST = \{.*?\}\n", src, re.S | re.M).group(0) + re.search(r"^WX = .*$", src, re.M).group(0), lit)
DUST0, WX0 = lit["_DUST"], lit["WX"]
ns.update(DUST_FILE=sw, DUST_TABLE=tb, DUST_LEVELS=lv, AN=dd, WX_PROOF=os.path.join(dd, "dust_wx_proof.json"), su=fake_su)
ns["CFG"].clear()
ns["CFG"].update(floors={"1": 5, "2": 5, "3": 5}, priority=[999, 1000, 144, 145, 146], mightyKeep=30, pinap=True, razz=True)
ns.update(FLAGS={"berries": NOFILE}, flag=lambda k: k == "catch", BALLS={"usable": 1700, "items": {}}, BALLSAVE_FILE=os.path.join(dd, "plan.json"))
ns["_BS"].clear()
ns["_BS"].update(mtime=None, plan=None, note="off")


def fresh(table=None, switch=None, look="ok", wx="proven"):
    """A catcher right after an attach: the table file, the switch's text, the shiny look, the weather read's record."""
    for f in (sw, tb):
        if os.path.exists(f):
            os.remove(f)
    if table is not None:
        with open(tb, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(table)
    if switch is not None:
        with open(sw, "wb") as fh:
            fh.write(switch if isinstance(switch, bytes) else switch.encode())
    ns["_DUST"].clear()
    ns["_DUST"].update(dict(DUST0, log=[]))
    ns["SHINYFIELD"].clear()
    ns["SHINYFIELD"].update({"ok": dict(ok=True, suspended=False, checked=True), "lost": dict(ok=False, suspended=False, checked=True),
                             "suspended": dict(ok=False, suspended=True, checked=True), "unchecked": dict(ok=True, suspended=False, checked=False)}[look])
    b, u, bad = {"proven": (40, 160, 1), "proving": (3, 20, 0), "wrong": (10, 10, 12), "nofield": (0, 0, 0), "none": (0, 0, 0)}[wx]
    ns["WX"].clear()
    ns["WX"].update(dict(WX0, found=wx != "nofield", key="0.435.2 offsets 56/216/32", b=b, u=u, hi=bad, lo=0, rows={}, ver={}))   # against it: all one way


# the switch's text -- read the way the APP reads it: its readFile() joins the file's lines (every line end dropped) and
# trims, its dustNorm() takes 1 to 7 digits and nothing else. Anything else = off.
SWITCH = ((None, 0), ("0", 0), ("", 0), ("1", 1), ("1\n", 1), ("500", 500), ("700\n", 700), (" 1000 ", 1000), ("\t500\r\n", 500), ("0700", 700),
          ("7\n00", 700), ("7\r\n00\n", 700), ("\n\n700", 700), ("7 00", 0), ("7\t00", 0), ("junk", 0), ("-5", 0), ("+700", 0), ("700.0", 0),
          ("7e2", 0), ("on", 0), ("9999999", 9999999), ("12345678", 0), ("9" * 25, 0), (b"\xff\xfe1", 0), (b"\xef\xbb\xbf700", 0), ("1" * 60, 0))
for text, want in SWITCH:
    fresh(switch=text)
    check(f"dust switch {text if text is None or len(text) < 12 else text[:9] + '...'!r} -> {want}", ns["dust_min"](), want)
# ...the app's own code: if it changes how it reads the number, dust_min() has to change with it
java = open(os.path.join(HERE, os.pardir, "ondevice_toggle", "apk", "src", "com", "benny", "autocatcher", "MainActivity.java"), encoding="utf-8").read()
check("dust switch: the app's dustNorm() still reads what dust_min() mirrors (trimmed, 1 to 7 digits, else 0)",
      bool(re.search(r'static String dustNorm\(String text\) \{\s*String t = text == null \? "" : text\.trim\(\);\s*'
                     r'return digits\(t\) && t\.length\(\) <= 7 \? String\.valueOf\(Integer\.parseInt\(t\)\) : "0";', java)), True)
# ...and catcher_ctl.sh, which WRITES the file (plain digits only): its own dust_mode(), run on the same texts, says the same
# numbers -- but for white space INSIDE the text, which it drops (700) where the app and the catcher say off. No writer
# produces that; the catcher sides with what the app shows.
CTL_OTHER = {"7 00": 700, "7\t00": 700}
ctl = re.search(r"^dust_mode\(\) \{.*\}$", open(os.path.join(HERE, os.pardir, "catcher_ctl.sh"), encoding="utf-8").read(), re.M)
paths = []
for i, (text, _want) in enumerate(SWITCH):
    paths.append(os.path.join(dd, f"sw{i}").replace("\\", "/"))
    if text is not None:
        with open(paths[-1], "wb") as fh:
            fh.write(text if isinstance(text, bytes) else text.encode())
rs = subprocess.run([shutil.which("bash") or "bash", "-c", (ctl.group(0) if ctl else "dust_mode() { echo missing; }") + '\nfor f in "$@"; do DUSTFLAG=$f; dust_mode; done',
                     "dust_mode", *paths], capture_output=True, text=True)
check("dust switch: catcher_ctl.sh's dust_mode() says the same number for every text but the two with white space inside",
      rs.stdout.split(), [str(CTL_OTHER.get(t, w)) for t, w in SWITCH])

# OFF = the config the JS gets is byte for byte what it was before the mode existed (the old cfg_now, kept here verbatim)
exec(r'''def cfg_before():
    c = dict(CFG)
    c["skipSp"] = ballsave_now()
    c["reserve"] = ballsave_reserve()   # the JS spreads it over the live bag (floorOf); reserve_floors() is the same sum
    live = plan_live(time.time())
    c["peek"] = live and SHINYFIELD["ok"]   # SHINY LOOK (Benny 11-16: "catch all shinies regardless")
    # The Mighty hold on Great/Ultra (ballOk): none while a plan spends the bag -- its budget counts them, and a Mighty still
    # gets any ball. The Razz kept for a Mighty (berryFor: mightyKeep) stays as it is (review 11-16).
    c["mightyBalls"] = 0 if live else c["mightyKeep"]
    for k in FLAGS:
        c[k] = flag(k)
    c["berries"] = mode = berry_mode()   # what the switch allows; what it leaves out no Mighty and no shiny gets either
    if mode not in ("on", "pinap"):
        c["pinap"] = False
    if mode not in ("on", "razz"):
        c["razz"] = False
    c["apples"] = True   # Benny 2026-10-29: "i want anything to always be picked up" -- map items no longer wait on a switch
    if c.get("abBlockS") and c.get("abKey"):
        c[c["abKey"]] = c["abArms"][int(time.time() // c["abBlockS"]) % 2]
    return c
''', ns)
real_text = open(REAL, encoding="utf-8").read()
real = dt.read_table(REAL)
rd, rbase = real["dust"], real["base"]
above = {d for d, v in rd.items() if v > rbase}
prio = set(ns["CFG"]["priority"])
same = lambda: json.dumps(ns["cfg_now"]()) == json.dumps(ns["cfg_before"]())
off = []
for text in (None, "0", "", "junk", "-1", "0.5"):
    fresh(table=real_text, switch=text)
    off.append(same())
check("switch off / missing / junk: the config is byte for byte the old one", off, [True] * 6)
json.dump(dict(PLAN, end=time.time() + 100 * 60), open(ns["BALLSAVE_FILE"], "w"))
ns["CFG"]["priority"] = []
fresh(table=real_text, switch="0")
c = ns["cfg_now"]()
check("off with a live plan: its cut, its shiny look, nothing else", (c["skipSp"], c["peek"], "skipWx" in c, same()), ([41], True, False, True))
bd = tempfile.mkdtemp()
ns.update(FLAGS={"berries": os.path.join(bd, "b.on")})
open(ns["FLAGS"]["berries"], "w").write("pinap")
check("off with a plan and Pinap only: still the old config", same(), True)
shutil.rmtree(bd)
ns.update(FLAGS={"berries": NOFILE})
os.remove(ns["BALLSAVE_FILE"])
ns["CFG"]["priority"] = sorted(prio)
check("no table on the phone while the switch is off: nothing changes, no key added", (fresh(switch="0"), same(), sorted(set(ns["cfg_now"]()) - set(ns["cfg_before"]())))[1:], (True, []))

# ---- switch = 1 against the REAL table (Benny: "inclusive of EVERY higher than avg stardust pokemon")
fresh(table=real_text, switch="1")
c = ns["cfg_now"]()
skip = set(c["skipSp"])
check("the real table: 900+ species, a normal catch is its most common value, hundreds pay more",
      (len(rd) >= 900, rbase == dt.base_of(rd), len(above) >= 100), (True, True, True))
check("switch 1: NO species above a normal catch is left alone", sorted(skip & above), [])
check("switch 1: left alone = exactly the normal-level species (priority ones excepted)", skip == {d for d, v in rd.items() if v <= rbase} - prio, True)
check("switch 1: left alone + caught = every species in the table", skip | above | (prio & set(rd)) == set(rd), True)
check("switch 1: a species the table does not know is caught", ([d for d in (902, 2000, 5000) if d in rd], [d for d in (902, 2000, 5000) if d in skip]), ([], []))
check("switch 1: the shiny look runs with NO plan; every weather-boosted spawn is caught; no keep, the usual Mighty hold",
      (c["peek"], c["skipWx"], c["reserve"], c["mightyBalls"], ns["plan_live"](time.time())), (True, [], 0, 30, False))
npk = len([d for d in prio if d in rd and rd[d] <= rbase])
check("switch 1: the log line names the counts", ns["_DUST"]["note"],
      f"(every above-normal species, {len(above):,} of {len(rd):,}, and every weather-boosted spawn): leaving {len(skip):,} alone "
      f"({npk} priority species stay caught); a shiny or a Mighty of any of them is still caught")
check("switch 1: status key only=1", (ns["dust_only"](), ns["state_extra"](5, {}, {}, 0.2, None, ns["dust_only"]())), (1, "only=1"))
DUSTJS = {"skip1": sorted(skip), "base": min(skip), "kept": max(above, key=lambda d: (rd[d], -d))}   # for the JS half below
for n in (500, 700, 1000):
    fresh(table=real_text, switch=str(n))
    c = ns["cfg_now"]()
    skip, swx = set(c["skipSp"]), set(c["skipWx"])
    kept = {d for d, v in rd.items() if v > rbase and v >= n}
    lifted = {d for d in skip if 5 * rd[d] >= 4 * n}
    check(f"switch {n}: the species paying {n}+ are caught, every other one (not priority) is left alone",
          (sorted(skip & kept), skip | kept | (prio & set(rd)) == set(rd), ns["dust_only"]()), ([], True, n))
    check(f"switch {n}: left alone even when weather-boosted = the ones x1.25 does not lift to {n}", (swx == skip - lifted, swx <= skip), (True, True))

# ---- a small table, to pin every rule: normal 100; 300 / 500 / 750 / 800 / 950 / 1000 / 1200 / 2100 above it
TD = {16: 100, 19: 100, 21: 100, 41: 100, 144: 100, 999: 100, 2: 300, 5: 300, 3: 500, 316: 500, 52: 750, 887: 800, 53: 950, 90: 1000, 91: 1200, 531: 2100}
TD.update({d: 100 for d in range(2001, 2031)})
TN = {d: f"Mon {d}" for d in TD}
TN.update({531: "Audino", 91: "Cloyster", 90: "Shellder", 53: "Persian", 887: "Dragapult", 52: "Meowth", 3: "Venusaur", 316: "Gulpin", 2: "Ivysaur", 5: "Charmeleon"})
T_text = dt.table_text(TD, TN, 7)
base_sp = {d for d, v in TD.items() if v == 100} - prio


def on(n, **kw):
    fresh(table=T_text, switch=str(n), **kw)
    c = ns["cfg_now"]()
    return c, set(c["skipSp"]), set(c.get("skipWx") or [])


c, skip, swx = on(1)
check("at 1: a weather-boosted normal-level species is caught (100 x 1.25 = 125 is above a normal catch)", (16 in skip, 16 in swx, swx), (True, False, set()))
check("at 1: the normal-level species are left, the priority ones (144, 999) and everything above are not", (skip == base_sp, {144, 999, 2, 531} & skip), (True, set()))
c, skip, swx = on(500)
check("at 500: a weather-boosted 300 is NOT caught (375 < 500), boosted or not", (2 in skip, 2 in swx, 5 in swx, swx == skip), (True, True, True, True))
check("at 500: 500+ caught, 300s left", ({3, 316, 52, 531} & skip, {2, 5} <= skip), (set(), True))
check("at 500: the log line says no boost reaches it", ns["_DUST"]["note"],
      f"500+ (8 of {len(TD)} species, no weather boost reaches 500): leaving {len(skip)} alone (2 priority species stay caught); a shiny or a Mighty of any of them is still caught")
c, skip, swx = on(700)
check("at 700: 750+ caught, 500s left even when boosted (625 < 700)", ({52, 887, 53, 90} & skip, {3, 316} <= swx), (set(), True))
c, skip, swx = on(1000)
check("at 1000: a weather-boosted 800 IS caught (800 x 1.25 = 1,000), and a boosted 950; a boosted 750 is not (937)",
      (887 in skip, 887 in swx, 53 in skip, 53 in swx, 52 in swx), (True, False, True, False, True))
check("at 1000: the log line counts them", ns["_DUST"]["note"],
      f"1000+ (3 of {len(TD)} species, 2 more when weather-boosted): leaving {len(skip)} alone (2 priority species stay caught); a shiny or a Mighty of any of them is still caught")
c, skip, swx = on(5000)
check("any whole number: at 5000 nothing pays that much -- all left but priority; a shiny / Mighty still caught by the look",
      (skip == set(TD) - prio, c["peek"], ns["dust_only"]()), (True, True, 5000))
c, skip, swx = on(100)
check("at 100: 'above a normal catch' still holds -- a normal-level species is not caught just because it pays 100", skip == base_sp, True)

# ---- the shiny look not trusted: NOTHING is left alone ("+ shinies" comes first), and it is said
for look, text in (("lost", "this game version's shiny field is not found"), ("suspended", "its shiny check was switched off for this run"),
                   ("unchecked", "this attach's shiny check has not run yet")):
    c, skip, swx = on(1, look=look)
    check(f"shiny look {look}: everything is caught, the config is the old one, no status key",
          (c["skipSp"], "skipWx" in c, same(), ns["dust_only"](), ns["_DUST"]["state"]), ([], False, True, 0, "nolook"))
    check(f"shiny look {look}: the app is told why", ns["dust_why"]("", [], True),
          f"stardust only is switched on but NOT applied: the catcher cannot see shinies ({text}), so it catches everything")
c, skip, swx = on(700, look="suspended")
check("shiny look suspended at 700: the same, with the level named", (c["skipSp"], ns["_DUST"]["note"]),
      ([], "700+ NOT applied: the shiny read was distrusted in this run (SHINY LOOK suspended) -- a shiny of a left-alone species could not be seen, so every species is caught"))
# ---- the weather read not trusted where it would decide: nothing is left alone either (never "skip and hope")
for wxs, text in (("nofield", "it cannot read the weather boost in this game version"),
                  ("proving", "it is still proving its weather-boost read on live catches: 3 of 12 boosted, 12 of 12 normal"),
                  ("wrong", "its weather-boost read did not match what the server paid")):
    c, skip, swx = on(1, wx=wxs)
    check(f"weather read {wxs} at 1: everything is caught, the config is the old one, no status key",
          (c["skipSp"], "skipWx" in c, same(), ns["dust_only"](), ns["_DUST"]["state"]), ([], False, True, 0, "nowx"))
    check(f"weather read {wxs}: the app is told why", ns["dust_why"]("out of balls: 5 Poke, 5 Great, 5 Ultra left", [], True),
          f"out of balls: 5 Poke, 5 Great, 5 Ultra left; stardust only is switched on but NOT applied yet: {text} -- until then it catches everything")
for wxs in ("proving", "nofield", "wrong"):
    c, skip, swx = on(1000, wx=wxs)
    check(f"weather read {wxs} at 1000: the level applies at once -- the two a boost could lift to 1,000 (800, 950) are caught whatever "
          "the weather, the 1,000+ ones are caught, everything else is left (also when boosted)",
          (ns["_DUST"]["state"], {887, 53} & skip, {90, 91, 531} & skip, {16, 2, 3, 52} <= skip, swx == skip, ns["dust_only"]()),
          ("on", set(), set(), True, True, 1000))
    check(f"weather read {wxs} at 1000: the log line and the app's line say what is caught meanwhile",
          (ns["_DUST"]["note"], ns["dust_why"]("", [], True)),
          (f"1000+ (3 of {len(TD)} species, 2 more caught whatever the weather until the weather read is proven): leaving {len(skip)} alone "
           "(2 priority species stay caught); a shiny or a Mighty of any of them is still caught", ""))
c, skip, swx = on(1000)
check("weather read proven at 1000: the 800 and the 950 are left alone again unless boosted (their spawns are looked at)",
      ({887, 53} <= skip, {887, 53} & swx, ns["_DUST"]["state"]), (True, set(), "on"))
c, skip, swx = on(500, wx="nofield")
check("weather read missing at 500, where no boost can decide anything: the mode runs", (ns["_DUST"]["state"], 2 in skip, swx == skip), ("on", True, True))
# ---- no table / a broken table: the mode stays off and says so (never a blind skip)
fresh(switch="1")
c = ns["cfg_now"]()
check("no table: everything is caught, the config is the old one", (c["skipSp"], same(), ns["dust_only"](), ns["_DUST"]["state"]), ([], True, 0, "notable"))
check("no table: the app is told", ns["dust_why"]("", [], True),
      "stardust only is switched on but NOT applied: the catcher has no species table on the phone, so it catches everything")
lines = []
ns["dust_log"](lines.append)
check("no table: one DUST TABLE line, one DUST ONLY line", (len(lines), lines[0][:35], lines[1][:43]),
      (2, "DUST TABLE: no species table at " + tb[:3], "DUST ONLY NOT applied: no species table at "))
for bad in ("{not json", '{"dust": []}', '{"dust": [[1, "A", 0]]}', '{"dust": [["x", "A", 100]]}', '[1, 2]'):
    fresh(table=bad, switch="1")
    c = ns["cfg_now"]()
    off.append((c["skipSp"], ns["_DUST"]["state"], "does not read" in ns["_DUST"]["twhy"]))
check("a table that is not one (5 kinds): everything is caught", off[-5:], [([], "notable", True)] * 5)
# ---- the table is re-read when it changes (about once a minute): no restart
fresh(table=T_text, switch="1")
ns["dust_skip"](1000.0)
n_su = len(su_calls)
lines = []
ns["dust_log"](lines.append)
check("table loaded: one DUST TABLE line + the mode's line", lines,
      [f"DUST TABLE batch 7: {len(TD)} species, 10 pay more than a normal catch (100)",
       f"DUST ONLY (every above-normal species, 10 of {len(TD)}, and every weather-boosted spawn): leaving {len(base_sp)} alone "
       f"(2 priority species stay caught); a shiny or a Mighty of any of them is still caught"])
open(tb, "w", encoding="utf-8", newline="\n").write(dt.table_text({**TD, 16: 300, 3000: 100}, {**TN, 3000: "Newmon"}, 8))
os.utime(tb, (time.time() + 50, time.time() + 50))
check("a changed table inside the same minute: not looked at yet", 16 in ns["dust_skip"](1030.0), True)
check("a minute later: re-read, the raised species is caught", (16 in ns["dust_skip"](1061.0), 3000 in ns["dust_skip"](1061.0)), (False, True))
lines = []
ns["dust_log"](lines.append)
check("the re-read says what changed, and the mode's line follows", lines,
      [f"DUST TABLE batch 8: {len(TD) + 1} species, 11 pay more than a normal catch (100); re-read: 2 raised or new: Mon 16 100 -> 300, Newmon new -> 100",
       f"DUST ONLY (every above-normal species, 11 of {len(TD) + 1}, and every weather-boosted spawn): leaving {len(base_sp)} alone "
       f"(2 priority species stay caught); a shiny or a Mighty of any of them is still caught"])
check("each load wrote the app's levels file again", len(su_calls) - n_su, 1)
# ---- the app's levels file (it reads exactly this)
fresh(table=T_text, switch="0")
if os.path.exists(lv):
    os.remove(lv)
n_su = len(su_calls)
ns["cfg_now"]()
check("levels file: written at the table load, switch on or off", open(lv, encoding="utf-8").read(),
      f"base=100 species={len(TD)} batch=7\n"
      "1 10 Audino, Cloyster, Shellder, Persian, Dragapult, Meowth, Venusaur, Gulpin, Ivysaur, Charmeleon\n"
      "500 8 Audino, Cloyster, Shellder, Persian, Dragapult, Meowth, Venusaur, Gulpin\n"
      "700 6 Audino, Cloyster, Shellder, Persian, Dragapult, Meowth\n"
      "1000 3 Audino, Cloyster, Shellder\n")
check("levels file: root copies it in and renames it (Termux cannot create a file there); the temp copy is gone",
      (len(su_calls) - n_su, bool(re.match(r"cp \S+ \S+\.new && chmod 644 \S+\.new && mv -f \S+\.new \S+; rm -f \S+$", su_calls[-1])),
       os.path.exists(os.path.join(dd, "dust_levels.tmp"))), (1, True, False))
fresh(table=T_text, switch="0")
n_su = len(su_calls)
ns["cfg_now"]()
check("levels file: already says the same -> no root call", len(su_calls) - n_su, 0)
big = {d: (300 if d <= 30 else 100) for d in range(1, 101)}
lt = ns["dust_levels_text"]({"dust": big, "names": {d: f"N{d}" for d in big}, "base": 100, "batch": 9})
check("levels file: names only while a level has 25 or fewer; an empty level is just its count", lt, "base=100 species=100 batch=9\n1 30\n500 0\n700 0\n1000 0\n")
rl = ns["dust_levels_text"]({"dust": rd, "names": real["names"], "base": rbase, "batch": real["batch"]}).splitlines()
top = sorted((d for d in rd if rd[d] > rbase and rd[d] >= 1000), key=lambda d: (-rd[d], d))
check("levels file, real table: 5 lines, the level-1 count is every above-normal species, names highest stardust first",
      (len(rl), rl[0], rl[1].split()[:2], rl[4]),
      (5, f"base={rbase} species={len(rd)} batch={real['batch']}", ["1", str(len(above))],
       f"1000 {len(top)}" + (" " + ", ".join(real["names"][d] for d in top) if 0 < len(top) <= 25 else "")))
# ---- with a ball-saver plan running too: what either one leaves alone; the plan's species stay left even when boosted
json.dump(dict(PLAN, end=time.time() + 100 * 60, species={"531": [2500, 4.0], "316": [1300, 2.0], "3": [380, 12.0], "16": [150, 8.0]}), open(ns["BALLSAVE_FILE"], "w"))
ns["BALLS"]["usable"] = 300
c, skip, swx = on(1)
check("plan + switch 1: the plan's cut (3, 16, 316) and the normal-level species, together", (ns["ballsave_now"](), skip == base_sp | {3, 316}), ([3, 16, 316], True))
check("plan + switch 1: a boosted normal-level one is caught unless the PLAN left its species (the plan is a ball budget)",
      (swx, 19 in swx, c["peek"], c["mightyBalls"]), ({3, 16, 316}, False, True, 0))
check("plan + switch 1: the plan's own note is not touched", " leaving 3 of 4 species alone" in ns["_BS"]["note"], True)
os.remove(ns["BALLSAVE_FILE"])
ns["ballsave_now"]()
ns["BALLS"]["usable"] = 1700
# ---- the log: one line per change, silent on days the switch is never used
fresh(table=T_text, switch="0")
lines = []
ns["cfg_now"]()
ns["dust_log"](lines.append)
check("switch never on: only the table's own line", [ln[:19] for ln in lines], ["DUST TABLE batch 7:"])
for text in ("1", "1", "700", "0", "0"):
    open(sw, "w").write(text)
    ns["cfg_now"]()
    ns["dust_log"](lines.append)
check("on -> one line; unchanged -> none; another level -> one; off -> one; then silent", [ln[:28] for ln in lines[1:]],
      ["DUST ONLY (every above-norma", "DUST ONLY 700+ (6 of 46 spec", "DUST ONLY off: every species"])
# ---- the app's why line and status key
H = lambda rows: [(1000.0 - ago, f, o, t, c, h) for ago, f, o, t, c, h in rows]
quiet = H([(60, 100, 3, 3, 3, 6), (30, 900, 9, 3, 3, 12), (0, 1800, 15, 3, 3, 18)])     # looks opened, nothing thrown, nothing caught
busy = H([(60, 100, 3, 3, 3, 6), (30, 900, 9, 4, 4, 12), (0, 1800, 15, 5, 5, 18)])
on(1)
W1 = "no Pokemon worth a ball in range (stardust only: 10 of 46 species, and every weather-boosted spawn; a shiny of the others is still caught)"
dw = ns["dust_why"]
check("why: applied and nothing thrown for a minute = the mode at work", dw("", quiet, True), W1)
check("why: a catch in the last minute -> nothing to say", dw("", busy, True), "")
check("why: 'no Pokemon in range' becomes the mode's line (they are there, just not worth a ball)", dw("no Pokemon in range right now", quiet, True), W1)
check("why: a spin note stays behind it, a Star Piece note in front",
      (dw("spins are being refused by the server (6 in a row, retrying every 30 s)", quiet, True),
       dw("the Star Piece ran out at 20:45:57: catches pay a third less stardust; no Pokemon in range right now", quiet, True)),
      (W1 + "; spins are being refused by the server (6 in a row, retrying every 30 s)",
       "the Star Piece ran out at 20:45:57: catches pay a third less stardust; " + W1))
real_trouble = ["the game is not answering: 9 encounters opened, 0 answered in the last minute", "out of balls: 5 Poke, 5 Great, 5 Ultra left (it saves the last 5/5/5 for you)",
                "paused: Pokemon GO is not showing its map (40 s) -- it only catches while the map is on screen", "Pokemon storage is full",
                "no Pokemon worth a ball in range (saving balls: leaving 3 of 4 species alone)"]
check("why: a real problem is never replaced", [dw(x, quiet, True) for x in real_trouble], real_trouble)
check("why: catch switched off, or too little history -> nothing", (dw("", quiet, False), dw("", quiet[:2], True)), ("", ""))
on(700)
check("why at a level names it", dw("", quiet, True),
      "no Pokemon worth a ball in range (stardust only 700+: 6 of 46 species, no weather boost reaches 700; a shiny of the others is still caught)")
fresh(table=T_text, switch="0")
ns["cfg_now"]()
check("why: switch off -> untouched", (dw("", quiet, True), dw("no Pokemon in range right now", quiet, True), ns["dust_only"]()), ("", "no Pokemon in range right now", 0))
sx = ns["state_extra"]
check("status key: only=N comes last (after sp=, before why=); absent when the mode is not applied",
      (sx(109, {"dust": 74725}, {"1": 2280, "2": 6, "3": 6, "705": 202, "701": 10}, 474.2, True, 700),
       sx(109, {"dust": 74725}, {"1": 2280, "2": 6, "3": 6, "705": 202, "701": 10}, 474.2, True, 0)),
      ("rate=13.8 up=474 dust=74725 balls=2280/6/6 pinap=202 razz=10 sp=1 only=700", "rate=13.8 up=474 dust=74725 balls=2280/6/6 pinap=202 razz=10 sp=1"))
# out of balls with the mode applied: the JS keeps looking (PEEKONLY), so a shiny still gets one -- said only then
on(1)
bw = lambda it: ns["balls_why"](it, {"hold": 0, "holdWhy": ""})
check("out of balls, mode applied: a shiny still gets one", bw({"1": 5, "2": 5, "3": 5}),
      "out of balls: 5 Poke, 5 Great, 5 Ultra left (it saves the last 5/5/5 for you) -- a shiny still gets one")
check("out of balls, not one ball left: no promise", bw({"1": 0, "2": 0, "3": 0}), "out of balls: 0 Poke, 0 Great, 0 Ultra left (it saves the last 5/5/5 for you)")
on(1, look="lost")
check("out of balls, mode not applied: as before", bw({"1": 5, "2": 5, "3": 5}), "out of balls: 5 Poke, 5 Great, 5 Ultra left (it saves the last 5/5/5 for you)")
fresh(table=T_text, switch="0")
ns["cfg_now"]()
check("out of balls, mode off: as before", bw({"1": 5, "2": 5, "3": 5}), "out of balls: 5 Poke, 5 Great, 5 Ultra left (it saves the last 5/5/5 for you)")
check("mode off, no plan: the Mighty line as before", ns["balls_why"]({"1": 3, "2": 40, "3": 40}, {"hold": 0, "holdWhy": "", "mightyOn": True})[:17], "out of Poke Balls")
# a Star Piece that ran out matters in this mode too (it is a stardust mode)
ns["SP"].update(on=True, off=True, since="20:45:57")
on(1)
check("Star Piece ran out while the switch is on: it leads the why", ns["starpiece_why"]("", time.time()),
      "the Star Piece ran out at 20:45:57: catches pay a third less stardust")
fresh(table=T_text, switch="0")
ns["cfg_now"]()
check("...and says nothing when the switch is off and no plan runs", ns["starpiece_why"]("", time.time()), "")
ns["SP"].update(on=False, off=False, since=None, bare=0)

# ---- WEATHER BOOST read: the track record on catches made anyway, before the flag may decide anything
#      wx_judge -> (boosted that agree, unboosted that agree, hi, lo): the catches AGAINST their flag by direction, hi = no
#      flag but paid the boost, lo = flagged but paid the normal amount (until 2026-11-18 one number, their sum)
wj = ns["wx_judge"]
check("weather: boosted paid the step (275 / 225), unboosted did not -> all agree", wj([(225, False)] * 12 + [(275, True)] * 4), (4, 12, 0, 0))
check("weather: no event (150 / 125), a Star Piece minute (412 / 337, 224 / 187)", (wj([(125, False)] * 3 + [(150, True)] * 2), wj([(337, False), (412, True)]),
                                                                              wj([(187, False), (224, True)])), ((2, 3, 0, 0), (1, 1, 0, 0), (1, 1, 0, 0)))
check("weather: an unflagged catch that paid the boost, a flagged one that paid normal -> against the flag", wj([(225, False)] * 5 + [(275, False), (275, True), (275, True), (225, True)]), (2, 5, 1, 1))
check("weather: the flag upside down -> every catch against it", wj([(275, False)] * 5 + [(225, True)] * 4), (0, 0, 5, 4))
check("weather: flagged and unflagged paid the same -> the flag says nothing", wj([(225, False)] * 5 + [(225, True)] * 4), (0, 0, 0, 4))
check("weather: a flag that never sets while two pay levels show -> the higher ones are against it", wj([(225, False)] * 10 + [(275, False)] * 3), (0, 0, 3, 0))
check("weather: a flag that always sets while two pay levels show -> the lower ones are against it", wj([(225, True)] * 10 + [(275, True)] * 3), (0, 0, 0, 10))
check("weather: one kind, one pay level -> nothing proven, nothing against", (wj([(225, False)] * 9), wj([(275, True)] * 9), wj([(225, False)]), wj([])), ((0, 0, 0, 0),) * 4)
check("weather: another catch's award swapped in (2025) or a first-catch bonus (2025 / 9125) is not judged", wj([(225, False)] * 6 + [(275, True)] * 3 + [(2025, False), (9125, True)]), (3, 6, 0, 0))
# two awards that crossed are ONE hi and ONE lo in every minute, also where the crossing itself moved a kind's usual pay
check("weather: crossed awards in a small minute: the only flagged catch crossed; one of two; one unflagged against two flagged",
      (wj([(225, False)] * 8 + [(275, False), (225, True)]), wj([(225, False)] * 8 + [(275, False), (225, True), (275, True)]), wj([(275, False), (225, True), (275, True)])),
      ((0, 0, 1, 1),) * 3)
check("weather: both kinds usually paid the BOOSTED amount (some paid a step less): unflagged at it are hi, flagged below it lo",
      (wj([(225, False), (275, False), (275, False), (225, True), (275, True), (275, True)]), wj([(275, False)] * 4 + [(275, True)] * 3 + [(225, True)])), ((0, 0, 2, 1), (0, 0, 4, 1)))
fresh(table=T_text, switch="1", wx="none")
ns["dust_skip"](1000.0)
said = []
feed = lambda t, dex, award, wxf, tag="": ns["wx_seen"](f"CATCH Wild #{dex} ball=1 p=0.50 att=1 berry=0 0.6s{tag} dust={award} candy=3" + ("" if wxf is None else f" wx={wxf}"), t)
ns["wx_tick"](6000.0, said.append)
check("weather: at the start it says it is being proven, and decides nothing", (len(said), said[0][:42], ns["wx_verdict"](), ns["_DUST"]["state"]),
      (1, "WEATHER BOOST read being proven on the cat", "proving", "nowx"))
for i in range(6):
    feed(6000 + i, 16, 225, 0)
for i in range(3):
    feed(6010 + i, 19, 275, 3)
feed(6020, 52, 1525, 0)                 # not a normal-level species
feed(6021, 16, 225, 0, " [mighty]")     # a Mighty: its own pay
feed(6022, 16, 275, None)               # no flag read on that line
feed(6023, 16, 50, 0)                   # not a catch award
ns["wx_tick"](6030.0, said.append)
check("weather: nothing is judged before its minute ends", (ns["WX"]["b"], ns["WX"]["u"]), (0, 0))
ns["wx_tick"](6061.0, said.append)
check("weather: the minute's normal-level catches judged (other species, Mighty, flagless lines left out)", (ns["WX"]["b"], ns["WX"]["u"], ns["WX"]["hi"] + ns["WX"]["lo"], len(said)), (3, 6, 0, 1))
for mnt in range(102, 105):
    for i in range(6):
        feed(mnt * 60 + i, 21, 337, 0)
    for i in range(3):
        feed(mnt * 60 + 10 + i, 41, 412, 5)
ns["wx_tick"](105 * 60 + 1.0, said.append)
check("weather: 12 boosted + 12 unboosted that agree = PROVEN, said once", (ns["WX"]["b"], ns["WX"]["u"], ns["wx_verdict"](), len(said), said[-1]),
      (12, 24, "proven", 2, "WEATHER BOOST read PROVEN for 0.435.2 offsets 56/216/32: 12 boosted catches paid the +25% and 24 unboosted ones did not (0 of 36 paid against their flag)"))
check("weather: once proven the mode applies", (ns["cfg_now"]()["skipWx"], ns["_DUST"]["state"], ns["dust_only"]()), ([], "on", 1))
rec = json.load(open(ns["WX_PROOF"]))
check("weather: the record is kept in a file, per game version + offsets", (rec["key"], rec["b"], rec["u"], rec["bad"], rec["verdict"], rec["hi"], rec["lo"]),
      ("0.435.2 offsets 56/216/32", 12, 24, 0, "proven", 0, 0))
ns["wx_load"]("0.435.2 offsets 56/216/32", True)
check("weather: a re-attach on the same game version keeps the proof", (ns["WX"]["b"], ns["WX"]["u"], ns["wx_verdict"]()), (12, 24, "proven"))
ns["wx_load"]("0.437.0 offsets 56/216/36", True)
check("weather: a game update (another version / offset) starts from nothing", (ns["WX"]["b"], ns["WX"]["u"], ns["wx_verdict"]()), (0, 0, "proving"))
ns["wx_load"]("0.437.0 offsets 56/216/None", False)
said = []
ns["wx_tick"](7000.0, said.append)
check("weather: field not found at attach -> said, decides nothing", (ns["wx_verdict"](), said[0][:60]), ("nofield", "WEATHER BOOST read off: PokemonDisplayProto.WeatherBoostedCo"))
ns["WX"].update(found=True, b=12, u=12, hi=2, lo=0)
v1 = ns["wx_verdict"]()
ns["WX"].update(hi=1)
v2 = ns["wx_verdict"]()
ns["WX"].update(b=30, u=30, hi=25)
check("weather: proven needs at most 1 in 20 against the flag; 10+ and over a quarter against = WRONG", (v1, v2, ns["wx_verdict"]()), ("proving", "proven", "wrong"))

# ---- ...AND CROSSED AWARDS (2026-11-18, the first live hour). Two throws in the air get each other's awards (the result
#      queue matches replies in send order), so a boosted and an unboosted catch that cross read as ONE unflagged catch
#      that paid the boost (hi) and ONE flagged catch that paid the normal amount (lo). 32 of 818 judged catches did, 24
#      of them inside ten minutes, and "at most 1 in 20 against the flag" took the proof away for 13 minutes (18:51 to
#      19:04) from a flag that was right. Now a pair cancels: what counts is the ONE-WAY remainder abs(hi - lo), at most
#      1 in 20 -- and all the catches against, at most 1 in 5 (a flag that reads at random is balanced as well).
import random


def verdict_of(b, u, hi, lo):
    ns["WX"].update(found=True, b=b, u=u, hi=hi, lo=lo)
    return ns["wx_verdict"]()


def rule_before(b, u, bad):
    n = b + u + bad
    return "wrong" if bad >= 10 and 4 * bad > n else "proven" if b >= 12 and u >= 12 and 20 * bad <= n else "proving"


check("crossed awards: 18:51 that day (70 + 198 agree, 22 against = 11 one way + 11 the other) stays proven; the rule before said proving",
      (verdict_of(70, 198, 11, 11), rule_before(70, 198, 22)), ("proven", "proving"))
check("crossed awards: the hour's totals as measured (183 + 533 agree, 17 hi + 15 lo) are proven", verdict_of(183, 533, 17, 15), "proven")
check("crossed awards: a pair cancels, a one-way remainder does not -- 1 in 20 of the judged catches is the line",
      (verdict_of(100, 300, 32, 10), verdict_of(100, 300, 33, 10), verdict_of(100, 300, 10, 33), verdict_of(100, 300, 0, 21), verdict_of(100, 300, 22, 0)),
      ("proven", "proving", "proving", "proven", "proving"))
check("crossed awards: all the catches against, pairs or not, are at most 1 in 5 (a flag that reads at random stays out)",
      (verdict_of(100, 300, 50, 50), verdict_of(100, 300, 51, 50), verdict_of(30, 30, 25, 25)), ("proven", "proving", "proving"))
check("crossed awards: a class flagged wrong ONE way (1 in 10) is not proven; 10+ one-way and over a quarter = WRONG; 9 are not yet",
      (verdict_of(200, 700, 100, 0), verdict_of(50, 200, 90, 0), verdict_of(30, 30, 20, 0), verdict_of(30, 30, 0, 21), verdict_of(10, 10, 9, 0)),
      ("proving", "wrong", "proving", "wrong", "proving"))
check("crossed awards: most catches against the flag, both ways (upside down, at random) = WRONG; half of them is not most",
      (verdict_of(5, 20, 30, 30), verdict_of(0, 0, 150, 160), verdict_of(30, 30, 30, 30), verdict_of(0, 0, 5, 4)), ("wrong", "wrong", "proving", "proving"))


def wx_hour(seed, minutes, flag, p=0.22, k=18, cross=lambda m: 0.0, other=0.2):
    """A made-up hour through wx_seen / wx_close / wx_verdict: about k catches a minute, a share p of them weather-boosted
    (they pay 275, the others 225), a share `other` of another pay level (never judged). flag(boosted, rng) = what the
    flag says. cross(minute) = the chance that a catch and the next one get each other's awards.
    -> per minute (the verdict, the verdict by the rule before)."""
    rng = random.Random(seed)
    fresh(table=T_text, switch="1", wx="none")
    ns["dust_skip"](1000.0)
    out = []
    for m in range(minutes):
        cs = []
        for _ in range(k - 4 + int(rng.random() * 9)):
            if rng.random() < other:
                cs.append([52, 1525, 0])
            else:
                boosted = rng.random() < p
                cs.append([16, 275 if boosted else 225, 3 if flag(boosted, rng) else 0])
        i, c = 0, cross(m)
        while i < len(cs) - 1:
            if rng.random() < c:
                cs[i][1], cs[i + 1][1] = cs[i + 1][1], cs[i][1]
                i += 1
            i += 1
        for j, (dex, award, wxf) in enumerate(cs):
            feed(60000 + 60 * m + j, dex, award, wxf)
        ns["wx_close"]()
        w = ns["WX"]
        out.append((ns["wx_verdict"](), rule_before(w["b"], w["u"], w["hi"] + w["lo"])))
    return out


def lost(vs):
    """Was the proof lost again after it was first reached?"""
    return "proven" in vs and any(v != "proven" for v in vs[vs.index("proven"):])


right = lambda boosted, rng: boosted
that_day = lambda m: 0.28 if 15 <= m < 25 else 0.04   # 4% of the catches crossed, ten minutes at 28% (12-17% of them show)
hours = [wx_hour(s, 60, right, cross=that_day) for s in range(12)]
check("crossed awards: 12 made-up hours like that day (a right flag, ten minutes of crossing): proven in each, never lost; lost under the rule before",
      (sum("proven" in [v for v, _o in h] for h in hours), sum(lost([v for v, _o in h]) for h in hours), sum(lost([o for _v, o in h]) for h in hours) >= 8),
      (12, 0, True))
hours = [wx_hour(s, 60, right, p=0.5, cross=that_day) for s in range(6)] + [wx_hour(s, 90, right, k=6, cross=that_day) for s in range(6)]
check("crossed awards: the same with half the spawns boosted, and at 6 catches a minute: proven at the end of each",
      [h[-1][0] for h in hours], ["proven"] * 12)
never = {"never sets": lambda boosted, rng: False, "always sets": lambda boosted, rng: True, "reads upside down": lambda boosted, rng: not boosted,
         "reads at random (a quarter of the spawns boosted)": lambda boosted, rng: rng.random() < 0.25,
         "reads at random (half of the spawns boosted)": lambda boosted, rng: rng.random() < 0.5}
for name, fl in never.items():
    hours = [wx_hour(s, 60, fl, p=0.5 if "half" in name else 0.25, cross=that_day) for s in range(4)]
    check("crossed awards: a flag that " + name + " is never proven, with the same crossing -- WRONG at the end",
          (sum(v == "proven" for h in hours for v, _o in h), [h[-1][0] for h in hours]), (0, ["wrong"] * 4))
hours = [wx_hour(s, 120, lambda boosted, rng: boosted and rng.random() >= 0.3) for s in range(6)]
check("crossed awards: a flag that misses 3 in 10 boosted spawns (one way) is not proven at the end, as before",
      ([h[-1][0] for h in hours], [h[-1][1] for h in hours]), (["proving"] * 6, ["proving"] * 6))
# the record: hi and lo are kept (their sum too, as "bad"); a record from before the split is read the strict way
K = "0.435.2 offsets 56/216/32"
with open(ns["WX_PROOF"], "w", encoding="utf-8") as fh:
    json.dump({"key": K, "b": 70, "u": 198, "bad": 22, "verdict": "proving", "at": "2026-11-18 18:51:00"}, fh)
ns["wx_load"](K, True)
check("crossed awards: a record from before the split (b, u, bad) is read the strict way -- all of it one-way",
      (ns["WX"]["b"], ns["WX"]["u"], ns["WX"]["hi"], ns["WX"]["lo"], ns["wx_verdict"]()), (70, 198, 22, 0, "proving"))
ns["WX"].update(hi=11, lo=11, said=None)
said = []
ns["wx_tick"](9000.0, said.append)
rec = json.load(open(ns["WX_PROOF"]))
check("crossed awards: the record keeps both directions and their sum", (rec["b"], rec["u"], rec["hi"], rec["lo"], rec["bad"], rec["verdict"]), (70, 198, 11, 11, 22, "proven"))
check("crossed awards: PROVEN says the split once",
      said, ["WEATHER BOOST read PROVEN for 0.435.2 offsets 56/216/32: 70 boosted catches paid the +25% and 198 unboosted ones did not (22 of 290 paid against their flag: "
             "11 paid the boost without the flag, 11 had the flag and paid the normal amount -- two throws in the air get each other's awards, so a pair of those cancels)"])
ns["wx_load"](K, True)
check("crossed awards: a re-attach reads both directions back", (ns["WX"]["hi"], ns["WX"]["lo"], ns["wx_verdict"]()), (11, 11, "proven"))
ns["WX"].update(hi=30, lo=0, said=None)
said = []
ns["wx_tick"](9100.0, said.append)
ns["WX"].update(b=5, u=20, hi=30, lo=30)
ns["wx_tick"](9200.0, said.append)
check("crossed awards: 12 of each agree but too many are against it one way -> 'being proven' says why; WRONG says the split too",
      said, ["WEATHER BOOST read being proven on the catches made anyway: 70 boosted and 198 unboosted ones agree with the server's pay so far, 30 do not "
             "(30 paid the boost without the flag, 0 had the flag and paid the normal amount) -- it decides nothing while more than 1 in 20 are against it one way, "
             "or more than 1 in 5 in all",
             "WEATHER BOOST read WRONG for 0.435.2 offsets 56/216/32: 60 of 85 catches paid against their flag (30 paid the boost without the flag, 30 had the flag "
             "and paid the normal amount) -- it decides nothing"])
bad_recs = ({"key": K, "b": 5, "u": 5, "hi": -1, "lo": 0}, {"key": K, "b": 5, "u": 5, "bad": "many"}, {"key": K, "b": 5, "u": 5, "hi": 2}, [1, 2], {"key": K, "b": 5, "u": 5})
got = []
for r in bad_recs:
    with open(ns["WX_PROOF"], "w", encoding="utf-8") as fh:
        json.dump(r, fh)
    ns["wx_load"](K, True)
    got.append((ns["WX"]["b"], ns["WX"]["u"], ns["WX"]["hi"], ns["WX"]["lo"]))
check("crossed awards: a record that does not read (a count below 0, text, hi without lo and no sum, not a record) starts from nothing",
      got, [(0, 0, 0, 0)] * 5)
os.remove(ns["WX_PROOF"])
ns["wx_load"](K, True)
asked = []
ns["su"] = lambda cmd, timeout=10: asked.append(cmd) or "    versionName=0.435.2-G\n"
gv = ns["game_version"]
check("weather: the game's version name is asked once per game process; a process whose pid is not known, every attach",
      (gv(4711), gv(4711), len(asked), gv(4712), len(asked), "dumpsys package" in asked[0], gv(None), gv(None), len(asked)),
      ("0.435.2-G", "0.435.2-G", 1, "0.435.2-G", 2, True, "0.435.2-G", "0.435.2-G", 4))
ns["su"] = lambda cmd, timeout=10: ""
check("weather: no answer from the package manager -> '?' (a key of its own, never another version's proof)", gv(4713), "?")
ns["su"] = fake_su

# ---- STAR PIECE read off the award, with the species table loaded (2026-11-18). The pay the 29,636 catches in the
#      phone's logs follow, n = species stardust x event multiplier: without a Star Piece n + 25, + n // 4 when
#      weather-boosted; with one each of the three parts x 1.5 and EACH cut to a whole number (25 -> 37). "Not a multiple
#      of 25 = with one" is right but for ONE kind of catch: boosted, WITHOUT a Star Piece, a species at 750 / 950, an odd
#      multiplier (962, 1212 ...). 44 logged catches paid 962; each was followed by an ordinary catch, so each would have
#      rung the app's "The Star Piece ran out" alert (sp= going 1 -> 0).
import math
shipped = open(os.path.join(HERE, os.pardir, "system", "scripts", "game_write", "catch_dust.json"), encoding="utf-8").read()
fresh(table=shipped, switch="0")
ns["dust_table"](2000.0)
vals = sorted(set(ns["_DUST"]["table"]["dust"].values()))
paid, odd = ns["sp_paid"], ns["sp_bare_odd"](vals)
check("star piece: the shipped table's values whose weather quarter is not always whole", [t for t in vals if t % 4], [750, 950])
check("star piece: ...and the awards WITHOUT one that are not a multiple of 25 (multipliers 1-8)", sorted(odd), [962, 1212, 2837, 3587, 4712, 5962, 6587, 8337])
# the same pay worked out a second way (decimal fractions, cut by math.floor), for every table value x multiplier x weather
bare_all = {m * t + 25 + (math.floor(0.25 * m * t) if b else 0) for t in vals for m in range(1, 9) for b in (False, True)}
star_all = {math.floor(1.5 * m * t) + math.floor(1.5 * 25) + (math.floor(1.5 * 0.25 * m * t) if b else 0) for t in vals for m in range(1, 9) for b in (False, True)}
check("star piece: no award is paid both with one and without one (any two species, any two multipliers)", sorted(bare_all & star_all), [])
check("star piece: with one, no species pays a multiple of 25", [a for a in sorted(star_all) if a % 25 == 0], [])
check("star piece: every award without one reads 'without', every award with one reads 'with' (over 150 different awards)",
      ([a for a in sorted(bare_all) if paid(a)], [a for a in sorted(star_all) if not paid(a)], len(bare_all | star_all) > 150), ([], [], True))
check("star piece: the multiple-of-25 test alone is wrong for exactly those awards", sorted(a for a in bare_all | star_all if bool(a % 25) != paid(a)), sorted(odd))
REAL_WITH = (337, 412, 187, 3037, 224, 2287, 937, 1537, 1162, 1912, 3787, 2849, 487, 787, 599, 974, 1443, 3187, 6337)
REAL_BARE = (125, 225, 150, 275, 2025, 1525, 775, 625, 325, 1025, 525, 1900, 1275, 962, 400, 650, 2525, 1925, 2125, 4225, 975, 9125, 1950)
check("star piece: the 42 different awards of the 29,636 logged catches (a first-catch bonus among them) read as they were paid",
      ([a for a in REAL_WITH if not paid(a)], [a for a in REAL_BARE if paid(a)], len(set(REAL_WITH + REAL_BARE))), ([], [], 42))
check("star piece: on a day without an event a boosted catch with one pays 224, not 225 (568 logged) -- 225 is a 2x catch without one",
      (paid(224), paid(187), paid(225), 224 in star_all, 225 in star_all, 225 in bare_all), (True, True, False, True, False, True))
sp_keep, sp_lines = dict(ns["SP"]), []
ns["SP"].clear()
ns["SP"].update(on=False, off=False, since=None, bare=0, last=None)
got = lambda dex, dust: ns["starpiece_seen"](f"CATCH Wild #{dex} ball=1 p=0.30 att=1 berry=0 0.9s dust={dust} candy=3", sp_lines.append)
got(16, 125); got(415, 962); got(16, 150)
check("star piece: a plain day without one, a boosted Combee (962): the chip never says ON, nothing is said",
      (ns["SP"]["last"], ns["SP"]["on"], sp_lines), (False, False, []))
got(568, 962); got(53, 1212)
check("star piece: ...a boosted Trubbish (962) and Persian (1212) the same", (ns["SP"]["last"], ns["SP"]["on"], sp_lines), (False, False, []))
got(632, 962)
check("star piece: ...and a 962 that the result queue put on another species' line", (ns["SP"]["last"], ns["SP"]["on"]), (False, False))
got(16, 187); got(16, 224); got(415, 1443)
check("star piece: with one on a plain day (187, boosted 224, a boosted Combee 1443): ON", (ns["SP"]["last"], ns["SP"]["on"], sp_lines), (True, True, []))
got(415, 962)
check("star piece: it ran out -- a boosted Combee without one (962) is the first bare catch", (ns["SP"]["last"], ns["SP"]["bare"], ns["SP"]["off"]), (False, 1, False))
got(16, 125)
check("star piece: ...the next catch is the second: STARPIECE off, one line", (ns["SP"]["off"], len(sp_lines), sp_lines[-1][:14]), (True, 1, "STARPIECE off:"))
got(415, 962); got(415, 2837)
check("star piece: ...and no boosted Combee switches it back on (962, 2837 at 3x)", (ns["SP"]["off"], len(sp_lines)), (True, 1))
got(415, 2849)
check("star piece: a boosted Combee WITH one in a 2x event (2849) does", (ns["SP"]["off"], len(sp_lines), sp_lines[-1][:13]), (False, 2, "STARPIECE on "))
check("star piece: a table value whose boosted award another species pays WITH one keeps the old read (250: 337 = 100 at 2x with one)",
      (337 in ns["sp_bare_odd"]([100, 250]), 962 in ns["sp_bare_odd"]([100, 250]), sorted(ns["sp_bare_odd"]([100, 300, 500, 1000]))), (False, True, []))
ns["_DUST"]["table"] = None
check("star piece: no species table -> the multiple-of-25 test, as before", (paid(962), paid(337), paid(225)), (True, True, False))
sys.path.insert(0, HERE)
import ballsave_plan   # noqa: E402  (the ball-saver planner reads the same awards on the PC)
check("star piece: the ball-saver planner works the same awards out the same way, from the same table",
      (ballsave_plan.BARE_ODD == odd, ballsave_plan.bare_odd([100, 250, 750]) == ns["sp_bare_odd"]([100, 250, 750]), ballsave_plan.sp_basis(962), ballsave_plan.sp_basis(337)),
      (True, True, 1443.0, 337.0))
ns["SP"].clear()
ns["SP"].update(sp_keep)
fresh(table=T_text, switch="1")
ns["dust_skip"](1000.0)
bn = ns["dust_boost_note"]
check("a catch made for the boost alone says what it pays (table x 1.25); one whose flag did not read says that",
      (bn("CATCH Wild #16 ball=2 p=0.60 att=1 berry=0 0.6s [boosted] dust=150 candy=3 wx=3"), bn("CATCH Wild #887 ball=2 p=0.60 att=1 berry=0 0.6s [boosted] dust=1275 candy=3 wx=1").split(" -- ")[-1],
       bn("CATCH Incense #16 ball=1 p=0.40 att=2 berry=705 1.1s [boost?] dust=225 candy=6").split(" -- ")[-1],
       bn("CATCH Wild #16 ball=2 p=0.60 att=1 berry=0 0.6s dust=150 candy=3 wx=3"), bn("FLED Wild #16 ball=2 p=0.60 att=1 berry=0 0.6s [boosted]")),
      ("CATCH Wild #16 ball=2 p=0.60 att=1 berry=0 0.6s [boosted] dust=150 candy=3 wx=3 -- weather-boosted, pays 125", "weather-boosted, pays 1000", "its weather flag did not read: caught, not skipped on a guess",
       "CATCH Wild #16 ball=2 p=0.60 att=1 berry=0 0.6s dust=150 candy=3 wx=3", "FLED Wild #16 ball=2 p=0.60 att=1 berry=0 0.6s [boosted]"))
check("the catcher's lines keep the shapes their readers use (star piece, ball-saver plan, tripwires)",
      (bool(re.search(r"(?:^|\s)CATCH \S+ #\d+ .*?dust=(\d+)", bn("CATCH Wild #16 ball=2 p=0.60 att=1 berry=0 0.6s [boosted] dust=150 candy=3 wx=3"))),
       "(e.wx >= 0 ? ' wx=' + e.wx : '')" in src, "w(dust_boost_note(line))" in src, "wx_seen(line, time.time())" in src, "wx_tick(time.time(), w)" in src, "dust_log(w)" in src),
      (True, True, True, True, True, True))
check("this attach's shiny check gates the mode; the table is loaded at the start, PoGo open or not",
      (bool(re.search(r'\n    SHINYFIELD\["checked"\] = False[^\n]*\n    t_att = time\.time\(\)\n    sess, _ = pg\.get_session\(\)', src)),
       bool(re.search(r'catcher start \(rebuilt\)[^\n]*\n    dust_table\(time\.time\(\)\)[^\n]*\n    dust_news\(w\)', src))), (True, True))

# ---- THE TABLE KEEPS ITSELF CURRENT (Benny 11-18: "make sure that table is always updated"): the catcher starts
#      catch_dust_table.py --auto as a CHILD PROCESS at an attach and every 6 hours (never in its own process), logs what
#      it said, and tells the app how old the last successful check is (dustchk=, right after only=)
for pat in (r"^DUST_UPD = .*$", r"^DUST_EVERY_S, DUST_ATTACH_S = .*$"):
    exec(re.search(pat, src, re.M).group(0), ns)
stf, outf, logf = os.path.join(dd, "catch_dust.state.json"), os.path.join(dd, "dust_update.out"), os.path.join(dd, "catch_loop.log")
ns.update(DUST_STATE=stf, DUST_OUT=outf, LOG=logf, HERE=GW, sys=sys)
UPD0 = dict(ns["DUST_UPD"])
NOWU = 1_795_050_000.0
check("the updater's record sits next to the table, where the builder writes it; a check every 6 hours, at an attach when 15 minutes old",
      ('DUST_STATE = os.path.splitext(DUST_TABLE)[0] + ".state.json"' in src,
       'state=os.path.splitext(table)[0] + ".state.json"' in open(BUILDER, encoding="utf-8").read(), ns["DUST_EVERY_S"], ns["DUST_ATTACH_S"]),
      (True, True, 21600, 900))


class FakeProc:
    def __init__(self, cmd, kw):
        self.cmd, self.kw, self.returncode, self.killed = cmd, kw, None, 0

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed += 1
        self.returncode = -9


class FakeSub:
    """subprocess, as far as dust_update_step() uses it. fail = what each Popen call raises, in order (None = it starts)."""
    DEVNULL, STDOUT, SubprocessError = subprocess.DEVNULL, subprocess.STDOUT, subprocess.SubprocessError

    def __init__(self, fail=()):
        self.calls, self.fail, self.proc = [], list(fail), None

    def Popen(self, cmd, **kw):
        self.calls.append(cmd)
        err = self.fail.pop(0) if self.fail else None
        if err:
            raise err
        self.proc = FakeProc(cmd, kw)
        return self.proc


def updater(state=None, fail=(), mtime=None):
    """A catcher that has just started: no child yet; the updater's record as given (None = no file, a str = that text);
    what the catcher knows of its table file ((mtime, size), "none", or None = not looked at yet)."""
    if os.path.exists(stf):
        os.remove(stf)
    if state is not None:
        with open(stf, "w", encoding="utf-8") as fh:
            fh.write(state if isinstance(state, str) else json.dumps(state))
    ns["DUST_UPD"].clear()
    ns["DUST_UPD"].update(UPD0)
    ns["_DUST"]["mtime"] = mtime
    ns["subprocess"] = FakeSub(fail)
    return ns["subprocess"]


def said_of(ans, rc=0, now=NOWU):
    """What the catcher logs once the child has ended with this output."""
    with open(outf, "w", encoding="utf-8", errors="replace") as fh:
        fh.write(ans if isinstance(ans, str) else json.dumps(ans) + "\n")
    out = []
    ns["dust_update_said"](out.append, rc, now)
    return out


# dustchk= : whole hours since the table was last known to be upstream's newest
dc = ns["dust_checked"]
chk = lambda state, mtime=None, now=NOWU: (updater(state, mtime=mtime), dc(now))[1]
check("dustchk: whole hours since this phone's last successful check (ok_ts in the updater's record)",
      [chk({"ok_ts": NOWU - 5 * 3600 - 10, "checked_ts": NOWU - 60}), chk({"ok_ts": NOWU - 3599}), chk({"ok_ts": int(NOWU) - 73 * 3600})], [5, 0, 73])
check("dustchk: no record and no table file -> no key; a record that is not one, or a time from the future -> no key, no error",
      [chk(None), chk(None, "none"), chk("{half"), chk("[1, 2]"), chk({"ok_ts": True}), chk({"ok_ts": "1795000000"}), chk({"ok_ts": NOWU + 301}),
       chk({"checked_ts": NOWU - 60}), chk(None, (NOWU + 9999, 1))], [None] * 9)
check("dustchk: before this phone's first successful check it counts from when the table file last changed (a deploy pushes "
      "it right after the PC's own check)", [chk(None, (NOWU - 100 * 3600, 24732)), chk({"checked_ts": NOWU - 60, "ok": False}, (NOWU - 7200, 1))], [100, 2])
check("dustchk: the later of the two counts (a check that found nothing new; a table that was just replaced)",
      [chk({"ok_ts": NOWU - 2 * 3600}, (NOWU - 50 * 3600, 1)), chk({"ok_ts": NOWU - 50 * 3600}, (NOWU - 3600, 1)), chk({"ok_ts": NOWU + 200})], [2, 1, 0])
updater({"ok_ts": NOWU - 3 * 3600})
first = dc(NOWU)
with open(stf, "w", encoding="utf-8") as fh:
    json.dump({"ok_ts": NOWU - 1}, fh)
check("dustchk: the record is read at most once a minute (the status line is written every 10 s)", (first, dc(NOWU + 30), dc(NOWU + 61)), (3, 3, 0))
check("status keys: dustchk=H comes right after only=N, and only with it (off, or not applied: neither key)",
      (sx(109, {"dust": 74725}, {"1": 2280, "2": 6, "3": 6, "705": 202, "701": 10}, 474.2, True, 700, 5),
       sx(5, {}, {}, 0.2, None, 1, 0), sx(5, {}, {}, 0.2, None, 1, None), sx(5, {}, {}, 0.2, None, 0, 5), sx(5, {}, {}, 0.2, None, 1000, 100)),
      ("rate=13.8 up=474 dust=74725 balls=2280/6/6 pinap=202 razz=10 sp=1 only=700 dustchk=5", "only=1 dustchk=0", "only=1", "", "only=1000 dustchk=100"))

# the child process: started at an attach and every 6 hours, one at a time
said = []
fs = updater()
ns["dust_update"](NOWU, said.append, attach=True)
proc = fs.proc
check("updater: at an attach it starts the builder's --auto as a child at the lowest priority, told which table and which log",
      (fs.calls, said), ([["nice", "-n", "19", sys.executable, os.path.join(GW, "catch_dust_table.py"), "--table", tb, "--auto", logf]], []))
check("updater: the child gets no stdin, writes to its own file (appending), and inherits none of the catcher's sockets (close_fds)",
      (proc.kw["stdin"] == subprocess.DEVNULL, proc.kw["stderr"] == subprocess.STDOUT, proc.kw["close_fds"],
       os.path.normpath(proc.kw["stdout"].name) == os.path.normpath(outf), proc.kw["stdout"].mode), (True, True, True, True, "ab"))
ns["dust_update"](NOWU + 1, said.append)
ns["dust_update"](NOWU + 2, said.append, attach=True)
check("updater: never two at once (the loop's look, and a second attach, while the child runs: nothing started, nothing said)", (len(fs.calls), said), (1, []))
ANS = {"ok": True, "line": "batch 1794878074575 (2026-11-17 01:14 UTC) is upstream's newest (alexelgt): nothing to download", "batch": 1794878074575,
       "catches": 2514, "checked": 2490, "species": 143, "above": []}
with open(outf, "w", encoding="utf-8") as fh:
    fh.write(json.dumps(ANS) + "\n")
proc.returncode = 0
ns["_DUST"]["tcheck"] = NOWU
ns["dust_update"](NOWU + 5, said.append)
check("updater: once the child has ended, ONE line says what upstream said and that the last day's catches fit the table", said,
      ["DUST TABLE check: batch 1794878074575 (2026-11-17 01:14 UTC) is upstream's newest (alexelgt): nothing to download; "
       "the last day's 2,514 catches (143 species): none paid more than the table says"])
check("updater: ...and the table file is looked at now (not within the minute), the record is read again, the child's file is closed",
      (ns["_DUST"]["tcheck"], ns["DUST_UPD"]["proc"], ns["DUST_UPD"]["st"], proc.kw["stdout"].closed), (0, None, None, True))
at = lambda sec, **kw: (ns["dust_update"](NOWU + sec, said.append, **kw), len(fs.calls))[1]
check("updater: the next one starts 6 hours after the last", [at(6 * 3600 - 1), at(6 * 3600)], [1, 2])
fs = updater({"checked_ts": NOWU - 100, "ok_ts": NOWU - 100})
check("updater: a catcher that restarts inside 15 minutes of the last check starts none at its attach -- the record says when that "
      "was, whoever ran it", [at(0, attach=True), at(799, attach=True), at(800, attach=True)], [0, 0, 1])
fs = updater({"checked_ts": NOWU - 100})
check("updater: in the loop it waits the 6 hours from the record's time, across restarts", [at(6 * 3600 - 101), at(6 * 3600 - 100)], [0, 1])
fs = updater({"checked_ts": NOWU + 9999})
check("updater: a record from the future (a wrong clock) is not believed", at(0, attach=True), 1)
fs = updater("{half a rec")
check("updater: a record that does not read = no record: the check runs", at(0), 1)
said = []
fs = updater(fail=[FileNotFoundError(2, "No such file or directory: 'nice'")])
ns["dust_update"](NOWU, said.append, attach=True)
check("updater: a system without nice -> the same command at the catcher's own priority, nothing said",
      ([c[0] for c in fs.calls], fs.calls[1] == fs.calls[0][3:], said, ns["DUST_UPD"]["proc"] is fs.proc), (["nice", sys.executable], True, [], True))
fs = updater(fail=[FileNotFoundError(2, "no nice"), PermissionError(13, "Permission denied")])
ns["dust_update"](NOWU, said.append, attach=True)
n1 = (at(1), at(2, attach=True), ns["DUST_UPD"]["proc"])
check("updater: it cannot be started at all -> one line, and no new try every second; the next attach 15 minutes on tries again",
      (said, n1, at(900, attach=True)), (["DUST TABLE check not started: [Errno 13] Permission denied"], (2, 2, None), 3))
said = []
fs = updater()
ns["DUST_OUT"] = os.path.join(dd, "no_such_dir", "dust_update.out")
ns["dust_update"](NOWU, said.append, attach=True)
ns["DUST_OUT"] = outf
check("updater: its output file cannot be opened -> said, nothing started", (len(said), said[0][:30], fs.calls), (1, "DUST TABLE check not started: ", []))
said = []
fs = updater()
ns["dust_update"](NOWU, said.append, attach=True)
proc = fs.proc
ns["dust_update"](NOWU + 1200, said.append)
k0 = proc.killed
ns["dust_update"](NOWU + 1201, said.append)
ns["dust_update"](NOWU + 1202, said.append)
check("updater: a child still running after 20 minutes is stopped, and that is said; it then counts as a run without an answer",
      (k0, proc.killed, said, ns["DUST_UPD"]["proc"]),
      (0, 1, ["DUST TABLE check still running after 20 minutes: stopped", "DUST TABLE check ended without an answer (exit -9): no output"], None))
said, went = [], []
fs = updater(fail=[RuntimeError("boom"), RuntimeError("boom")])
for sec in (0, 1, 6 * 3600):
    try:
        ns["dust_update"](NOWU + sec, said.append, attach=True)
        went.append(True)
    except Exception as e:   # noqa: BLE001
        went.append(repr(e))
check("updater: whatever goes wrong inside it never reaches the catch loop -- one line, said once; the next try is the next round",
      (went, said, len(fs.calls)), ([True, True, True], ["DUST TABLE check skipped: RuntimeError: boom"], 2))


def no_log(_line):
    raise OSError("the log is gone")


fs = updater(fail=[FileNotFoundError(2, "x"), FileNotFoundError(2, "x")])
try:
    ns["dust_update"](NOWU, no_log, attach=True)
    went = "no exception"
except Exception as e:   # noqa: BLE001
    went = repr(e)
check("updater: not even its own log line failing reaches the catch loop", went, "no exception")

# what the child said -> the log
updater()
MISS2 = dict(ANS, above=[{"dex": 21, "name": "Spearow", "table": 100, "over": 4, "n": 4, "a": 525, "ref": 125},
                         {"dex": 316, "name": "Gulpin", "table": 500, "over": 3, "n": 5, "a": 2525, "ref": 150}])
check("a species paid more than the table says: the check line counts it, and ONE more line names it with its numbers", said_of(MISS2),
      ["DUST TABLE check: batch 1794878074575 (2026-11-17 01:14 UTC) is upstream's newest (alexelgt): nothing to download; "
       "the last day's 2,514 catches (143 species): 2 species paid more than the table says",
       "DUST TABLE MISS: #21 Spearow is in the table at 100, but 4 of its 4 catches in the last day paid twice that or more (typically 525 where a normal catch paid 125); "
       "#316 Gulpin is in the table at 500, but 3 of its 5 catches in the last day paid twice that or more (typically 2525 where a normal catch paid 150)"
       " -- the table is too low there: until it is fixed, STARDUST ONLY may leave that species alone"])
one = dict(MISS2, above=MISS2["above"][:1])
check("...that line once a day while it names the same species (the check runs every 6 hours); other species, or another batch: at once",
      [len(said_of(MISS2, now=NOWU + 6 * 3600)), len(said_of(MISS2, now=NOWU + 86399)), len(said_of(MISS2, now=NOWU + 86400)),
       len(said_of(one, now=NOWU + 86401)), len(said_of(dict(one, batch=5), now=NOWU + 86402)), len(said_of(ANS, now=NOWU + 86403))], [1, 1, 2, 2, 2, 1])
updater()
many = dict(ANS, above=[{"dex": 100 + i, "name": f"Mon {i}", "table": 100, "over": 3, "n": 3, "a": 525, "ref": 125} for i in range(10)])
check("more than 8 such species: the first 8 by name, the rest counted",
      (said_of(many)[1].count(" is in the table at "), "; and 2 more -- the table is too low there" in said_of(many, now=NOWU + 90000)[1]), (8, True))
check("the catches could not be held against the table: said in the same line",
      said_of({"ok": False, "line": "no upstream answered (pokeminers: timed out; alexelgt: timed out) -- the table is kept (batch 7)", "batch": 7, "verify_error": "no table"}),
      ["DUST TABLE check: no upstream answered (pokeminers: timed out; alexelgt: timed out) -- the table is kept (batch 7); "
       "the last day's catches could not be held against it (no table)"])
updater()
junk = [said_of(t, rc) for t, rc in (("", 1), ('Traceback (most recent call last):\n  File "x.py", line 1, in <module>\nValueError: no table\n', 1), ("[1, 2]\n", 0),
                                     ('"text"\n', 0), ('{"ok": true}\n', 0), ("\x00\x01{", 0), ("Usage:\n  --check   ...\nOne update at a time.\n", 2))]
check("an answer that is not one (no output, a crash, other json, an older builder's usage text): one line with its last line, never an error",
      junk, [["DUST TABLE check ended without an answer (exit 1): no output"], ["DUST TABLE check ended without an answer (exit 1): ValueError: no table"],
             ["DUST TABLE check ended without an answer (exit 0): [1, 2]"], ['DUST TABLE check ended without an answer (exit 0): "text"'],
             ['DUST TABLE check ended without an answer (exit 0): {"ok": true}'], ["DUST TABLE check ended without an answer (exit 0): \x00\x01{"],
             ["DUST TABLE check ended without an answer (exit 2): One update at a time. -- catch_dust_table.py on this phone is missing or "
              "older than this catcher: deploy it"]])
odd = said_of('{"line": "x", "catches": "many", "species": null, "above": [5, {"dex": "a"}]}\n')
check("an answer with the wrong kinds of values: still lines, no error; and no line carries a traceback's first words",
      (odd[0], len(odd), [ln for ln in sum(junk, []) + odd if "Traceback" in ln]),
      ("DUST TABLE check: x; the last day's 0 catches (0 species): 1 species paid more than the table says", 2, []))

# end to end: the real builder as the real child (no network asked), the real files
E_TD = {16: 100, 19: 100, 21: 100, 41: 100, 774: 1000}
with open(tb, "w", encoding="ascii", newline="\n") as fh:   # a batch nothing on this PC can be newer than
    fh.write(dt.table_text(E_TD, {d: f"Mon {d}" for d in E_TD}, 9_000_000_000_000))
with open(logf, "w", encoding="utf-8", newline="\n") as fh:
    fh.write("".join("20:%02d:01 CATCH Wild #16 ball=1 p=0.50 att=1 berry=0 0.6s dust=125 candy=3 wx=0\n"
                     "20:%02d:02 CATCH Wild #21 ball=1 p=0.50 att=1 berry=0 0.6s dust=525 candy=3 wx=0\n" % (i, i) for i in range(4)))
updater()
ns["subprocess"] = subprocess
said, env0 = [], os.environ.get("CATCH_DUST_NO_NET")
os.environ["CATCH_DUST_NO_NET"] = "1"
t_run = time.time()
ns["dust_update"](t_run, said.append, attach=True)
started = ns["DUST_UPD"]["proc"] is not None
while ns["DUST_UPD"]["proc"] is not None and time.time() - t_run < 120:
    time.sleep(0.1)
    ns["dust_update"](time.time(), said.append)
if ns["DUST_UPD"]["proc"] is not None:
    ns["DUST_UPD"]["proc"].kill()
os.environ.pop("CATCH_DUST_NO_NET") if env0 is None else os.environ.update(CATCH_DUST_NO_NET=env0)
check("end to end (the real builder as a child process, no network): it starts, ends, and the catcher logs its two lines",
      (started, ns["DUST_UPD"]["proc"], said),
      (True, None, ["DUST TABLE check: upstream not asked -- the table is kept (batch 9000000000000); the last day's 8 catches (2 species): "
                    "1 species paid more than the table says",
                    "DUST TABLE MISS: #21 Mon 21 is in the table at 100, but 4 of its 4 catches in the last day paid twice that or more "
                    "(typically 525 where a normal catch paid 125) -- the table is too low there: until it is fixed, STARDUST ONLY may leave that species alone"]))
rec = dt.read_state(stf)
check("end to end: the child left its record next to the table (when it ran; not a successful check), no lock, no download, the table as it was",
      (abs(rec.get("checked_ts", 0) - t_run) < 300, rec.get("ok"), "ok_ts" in rec, os.path.exists(tb + ".lock"), os.path.exists(tb + ".download"),
       dt.read_table(tb)["batch"]), (True, False, False, False, False, 9_000_000_000_000))
ns["dust_update"](time.time(), said.append, attach=True)
ns["dust_table"](time.time())
check("end to end: with that record a second attach starts nothing; until a check succeeds dustchk counts from the table file",
      (ns["DUST_UPD"]["proc"], len(said), sx(5, {}, {}, 0.2, None, 1, dc(time.time()))), (None, 2, "only=1 dustchk=0"))
check("the session starts the updater at its attach (after that attach's config is pushed) and looks at it once a loop",
      (bool(re.search(r'\n    dust_update\(time\.time\(\), w, attach=True\)[^\n]*\n    last_rep, last_frame, idle = 0, None, 0\n    while dropped\["why"\] is None:\n', src)),
       "        wx_tick(time.time(), w)\n        dust_update(time.time(), w)\n        dust_log(w)\n" in src, src.count("dust_update(time.time(), w")), (True, True, 2))
shutil.rmtree(dd, ignore_errors=True)

# ---- JS (node): applyCfg + ballsave()
i = src.index('JS = r"""') + 9
d = tempfile.mkdtemp()
p = os.path.join(d, "c.js")
open(p, "w", encoding="utf-8").write("var rpc={exports:{}};\n" + src[i:src.index('"""', i)])
t = os.path.join(d, "t.js")
open(t, "w", encoding="utf-8").write(r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8'); const NOW = 1790716800000;
const NUL = { isNull: () => true, toString: () => '0x0' };
const api = new Function('ptr', 'Process', 'Memory', 'Interceptor', 'NativeFunction', 'NativeCallback', 'CModule', 'NULL', 'rpc', 'Date',
  src + `;return {get:(k)=>eval(k), set:(k,v)=>eval(k+'=v'), call:(f,...a)=>eval(f)(...a)};`)(
  () => NUL, { pointerSize: 8 }, { alloc: () => ({ writePointer: () => {}, readPointer: () => NUL }) }, {}, function () {}, function () {}, function () {},
  NUL, {}, { now: () => NOW });
const out = [];
out.push(JSON.stringify(api.get('CFG.skipSp')));
api.call('applyCfg', {skipSp: [10, 41]}); out.push(JSON.stringify(api.get('CFG.skipSp')));
api.call('applyCfg', {catch: true}); out.push(JSON.stringify(api.get('CFG.skipSp')));
api.call('ballsave', 'A', NOW); api.call('ballsave', 'A', NOW + 25000); api.call('ballsave', 'B', NOW);
out.push(JSON.stringify(api.get('ST.skip'))); out.push(api.get('COOL.A') - NOW);
api.set('E.C', {pid: 10, cls: 'WildMapPokemon', st: 'new', t0: NOW, seen: NOW, att: 0, opens: 0}); api.set('NE', 1);
api.call('ballsave', 'C', NOW);
const led = api.get('OUT.led');
out.push(JSON.stringify([api.get('E.C') === undefined, api.get('NE'), led.length, led.length ? led[0].r : null, led.length ? led[0].id : null]));
api.call('applyCfg', {skipSp: []}); out.push(JSON.stringify(api.get('CFG.skipSp')));
// walk(): a left-alone species is not tracked, counted once, and still proves the map is alive (no 45 s REFRESH)
api.set('call', (m, o, args) => m === 'ALL' ? api.get('COLL') : (m === 'VM' ? 1 : (m === 'PID' ? o.pid : null)));
api.set('M', {allPokemon: 'ALL'}); api.set('il', () => ({className: (k) => k, objClass: (o) => 'WildMapPokemon'}));
api.set('cstr', (x) => x); api.set('each', (c, f) => c.forEach(f)); api.set('encOf', (o) => o.enc);
api.set('method', (o, name) => name === 'get_VisibleOnMap' ? 'VM' : 'PID'); api.set('u8', (x) => x); api.set('s32', (x) => x);
api.set('spawnInfo', () => ({exp: 0, tth: 0, sp: '', lat: null, lng: null})); api.set('myPos', () => null);
api.set('E', {}); api.set('PEND', []); api.set('NE', 0); api.set('COOL', {}); api.set('SAVED', {}); api.set('NSAVED', 0); api.set('ST.skip', {});
api.call('applyCfg', {skipSp: [10]});
api.set('COLL', [{enc: 'm1', pid: 774}, {enc: 'r1', pid: 10}]); api.set('LASTVIS', 0);
api.call('walk', NOW);
out.push(JSON.stringify([Object.keys(api.get('E')), api.get('PEND'), api.get('ST.skip'), api.get('COOL.r1') - NOW, api.get('VIS')]));
api.set('E', {}); api.set('PEND', []); api.set('NE', 0); api.set('COLL', [{enc: 'r1', pid: 10}]); api.set('LASTVIS', 0); api.set('COOL', {}); api.set('SAVED', {});
api.call('walk', NOW + 1000); const lv1 = api.get('LASTVIS') - NOW;
api.call('walk', NOW + 5000); const lv2 = api.get('LASTVIS') - NOW;
out.push(JSON.stringify([api.get('VIS'), lv1, lv2, api.get('ST.skip')]));
api.call('applyCfg', {skipSp: []}); api.set('COOL', {});
api.call('walk', NOW + 30000);
out.push(JSON.stringify([Object.keys(api.get('E')), api.get('VIS')]));
console.log(JSON.stringify(out));
""")
r = subprocess.run(["node", t, p], capture_output=True, text=True)
got = r.stdout.strip()
want = '["{}","{\\"10\\":1,\\"41\\":1}","{\\"10\\":1,\\"41\\":1}","{\\"ballsave\\":2}",45000,"[true,0,1,\\"ballsave\\",10]","{}","[[\\"m1\\"],[\\"m1\\"],{\\"ballsave\\":1},20000,1]","[0,1000,5000,{\\"ballsave\\":2}]","[[\\"r1\\"],1]"]'
check("JS: species list, counted once, ledger", got, want)
if r.returncode or r.stderr.strip():
    print(r.stderr[-800:])
    failed += 1

# ---- JS (node): SHINY LOOK (Benny 11-16: "catch all shinies regardless"), the in-flight ball count, the Pinap loop
t2 = os.path.join(d, "t2.js")
open(t2, "w", encoding="utf-8").write(r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8'); const NOW = 1790716800000;
const NUL = { isNull: () => true, toString: () => '0x0' };
const mk = () => new Function('ptr', 'Process', 'Memory', 'Interceptor', 'NativeFunction', 'NativeCallback', 'CModule', 'NULL', 'rpc', 'Date',
  src + `;return {get:(k)=>eval(k), set:(k,v)=>eval(k+'=v'), call:(f,...a)=>eval(f)(...a)};`)(
  () => NUL, { pointerSize: 8 }, { alloc: () => ({ writePointer: () => {}, readPointer: () => NUL }) }, {}, function () {}, function () {}, function () {},
  NUL, {}, { now: () => NOW });
const res = {};
let api = mk();
// a shiny's ball: below every floor and the reserve, the best odds, the stronger ball on a tie or with no odds
api.call('applyCfg', {floors: {'1': 40, '2': 5, '3': 5}});
api.set('ITEMC', {1: 38, 2: 5, 3: 5});
res.ball = [api.call('pickBall', {1: 0.3, 2: 0.4, 3: 0.5}, false, 0, 0), api.call('pickBall', {1: 0.3, 2: 0.4, 3: 0.5}, false, 0, 1)];
api.set('ITEMC', {1: 38, 2: 0, 3: 0}); res.ball.push(api.call('pickBall', {1: 0.3, 2: 0.4, 3: 0.5}, false, 0, 1));
api.set('ITEMC', {1: 0, 2: 0, 3: 0}); res.ball.push(api.call('pickBall', null, false, 0, 1));
api.set('ITEMC', {1: 3, 2: 2, 3: 0}); res.ball.push(api.call('pickBall', null, false, 0, 1));
// no ball may be thrown -> no berry (review 11-16: a Pinap fed every 5.8 s); a shiny gets its Razz below the floor
api.set('M', {useItem: 'U'}); api.set('ITEMC', {1: 40, 2: 5, 3: 5, 701: 3, 705: 50});
api.call('applyCfg', {pinap: true, pinapFloor: 20, razz: true, razzFloor: 5, razzThresh: 0.45});
res.berry = [api.call('berryFor', {probs: {1: 0.3}, prio: false, mighty: 0, shiny: 0}), api.call('berryFor', {probs: {1: 0.3}, prio: false, mighty: 0, shiny: 1})];
// Pinap only (11-18 "only pinap berries fed"): Razz off -> a hard throw, a shiny and an easy throw get the Pinap; none left = no berry
api.set('ITEMC', {1: 400, 2: 50, 3: 50, 701: 30, 705: 50});
api.call('applyCfg', {reserve: 0, pinap: true, pinapFloor: 0, razz: false});
res.pinapOnly = [api.call('berryFor', {probs: {1: 0.3}, prio: false, mighty: 0, shiny: 0}), api.call('berryFor', {probs: {1: 0.3}, prio: false, mighty: 0, shiny: 1}),
                 api.call('berryFor', {probs: {1: 0.9}, prio: false, mighty: 0, shiny: 0})];
api.set('ITEMC', {1: 400, 2: 50, 3: 50, 701: 30, 705: 0});
res.pinapOnly.push(api.call('berryFor', {probs: {1: 0.3}, prio: false, mighty: 0, shiny: 0}));
// a ball in the air: the 3 s poll may lower its count, never raise it (11-16 20:59: the 50 kept ended at 48)
api = mk();
api.set('call', () => 'R'); api.set('s32', () => api.get('BAG')); api.set('i32arg', (v) => v);
api.set('M', {itemCount: 'IC'}); api.set('S', {ib: 'IB'});
api.set('ITEMC', {1: 40}); api.set('BAG', 41); api.set('E', {x: {st: 'thrown', ball: 1, tThrow: NOW - 2000}});
api.call('pollCounts'); res.poll = [api.get('ITEMC[1]')];
api.set('BAG', 39); api.call('pollCounts'); res.poll.push(api.get('ITEMC[1]'));
api.set('E', {}); api.set('BAG', 45); api.call('pollCounts'); res.poll.push(api.get('ITEMC[1]'));
api.set('ITEMC', {1: 40}); api.set('BAG', 41); api.set('E', {x: {st: 'thrown', ball: 1, tThrow: NOW - 13000}});   // catch off mid-throw
api.call('pollCounts'); res.poll.push(api.get('ITEMC[1]'));
// a shiny Mighty: the Mighty path first (only it may throw a Safari Ball), then the shiny's best odds
api = mk();
api.set('ITEMC', {1: 38, 2: 5, 3: 5, 7: 10}); api.call('applyCfg', {floors: {'1': 40, '2': 5, '3': 5}});
const pm = {1: 0.1, 2: 0.2, 3: 0.3, 7: 0.6};
res.mighty = [api.call('pickBall', pm, false, 1, 1)]; api.set('SAFARI_OFF', NOW + 1000); res.mighty.push(api.call('pickBall', pm, false, 1, 1));
// a reply of a KNOWN species no open of ours matches is someone else's encounter: never handed to ours
api = mk();
api.set('readProbs', () => ({1: 0.5})); api.set('strongOf', () => 0); api.set('shinyOf', () => 1); api.set('mightyOf', () => 0);
api.set('OFF.pkId', 5); api.set('NWOFF', {X: {res: 1, pk: 2, cp: 3}});
const sOf = (sp) => ({add: (o) => ({readS32: () => 1, readPointer: () => (o === 2 ? (sp > 0 ? {isNull: () => false, add: () => ({readS32: () => sp})}
                                                                                     : {isNull: () => true}) : {})})});
const other = (sp) => { api.set('E', {a: {pid: 10, st: 'open'}}); api.set('NWQ', [{enc: 'a', t: NOW}]); api.set('RESP', {}); api.set('LASTNW', {t: 0, sig: ''});
  api.call('onOtherEncounterOut', sOf(sp), 'X'); const r = api.get('RESP.a'); return r ? r.sp : null; };
res.other = [other(774), other(10), other(0)];
// walk(): a left-alone species is tracked for a look while a plan runs; one already looked at is left at sight + ledgered
api = mk();
api.set('call', (m, o, args) => m === 'ALL' ? api.get('COLL') : (m === 'VM' ? 1 : (m === 'PID' ? o.pid : null)));
api.set('M', {allPokemon: 'ALL'}); api.set('il', () => ({className: (k) => k, objClass: (o) => 'WildMapPokemon'}));
api.set('cstr', (x) => x); api.set('each', (c, f) => c.forEach(f)); api.set('encOf', (o) => o.enc);
api.set('method', (o, name) => name === 'get_VisibleOnMap' ? 'VM' : 'PID'); api.set('u8', (x) => x); api.set('s32', (x) => x);
api.set('spawnInfo', () => ({exp: 0, tth: 0, sp: '', lat: null, lng: null})); api.set('myPos', () => null);
api.call('applyCfg', {skipSp: [10], peek: true});
api.set('COLL', [{enc: 'r1', pid: 10}, {enc: 'r2', pid: 10}]); api.set('PEEKED', {r2: 1});
api.call('walk', NOW);
res.walk = [Object.keys(api.get('E')), api.get('PEND'), api.get('ST.skip'), api.get('OUT.led').map(r => [r.e, r.r, r.n, r.id])];
// catchTick(): open it for a look -> not shiny: left alone + remembered; shiny: kept and thrown at with any ball
api = mk();
api.call('applyCfg', {catch: true, skipSp: [10], peek: true, floors: {'1': 5, '2': 5, '3': 5}, openMs: 0, maxOpen: 6, readyMs: 150, nearWait: 0});
api.set('walk', () => {}); api.set('ITEMC', {1: 100, 2: 5, 3: 5});
const opened = [], thrown = [];
api.set('openOne', (enc, e, o, now) => { opened.push(enc); e.st = 'open'; e.tOpen = now; e.opens++; });
api.set('throwAt', (e, enc, o, now) => { const b = api.call('pickBall', e.probs, e.prio, e.mighty, e.shiny);   // throwAt's own no-ball path
  if (!b) { e.st = 'ready'; e.due = now + 5000; return; } thrown.push(b); e.st = 'thrown'; e.ball = b; e.tThrow = now; });
const ent = (pid) => ({pid: pid, cls: 'WildMapPokemon', st: 'new', seen: NOW, att: 0, opens: 0, berry: 0, apple: false, t0: NOW});
api.set('E', {s1: ent(10), s2: ent(10), k1: ent(774)}); api.set('NE', 3); api.set('PEND', ['s1', 's2', 'k1']); api.set('LIVE', {s1: {}, s2: {}, k1: {}});
api.call('catchTick', NOW);
res.open = [opened.slice(), api.get('E.s1.peek'), api.get('E.s2.peek'), api.get('E.k1.peek')];
api.set('RESP', {s1: {st: 1, p: {1: 0.5, 2: 0.6, 3: 0.7}, t: NOW + 500, strong: 0, shiny: 0, wx: 0},
                 s2: {st: 1, p: {1: 0.2, 2: 0.3, 3: 0.4}, t: NOW + 500, strong: 0, shiny: 1},
                 k1: {st: 1, p: {1: 0.3, 2: 0.4, 3: 0.5}, t: NOW + 500, strong: 0, shiny: 0}});
api.set('ITEMC', {1: 40, 2: 5, 3: 5}); api.call('applyCfg', {floors: {'1': 40, '2': 5, '3': 5}});   // at the reserve: no ordinary ball
api.call('catchTick', NOW + 600);
const led = api.get('OUT.led');
res.reply = [api.get('E.s1') === undefined, api.get('PEEKED.s1'), api.get('ST.skip.ballsave'), led.map(r => [r.e, r.r, r.pk]),
             api.get('E.s2.st'), api.get('E.s2.shiny'), api.get('ST.shiny'), api.get('OUT.log').filter(l => l.indexOf('SHINY Wild #10') === 0).length,
             api.get('PEEKONLY')];
api.call('catchTick', NOW + 1000);
res.thrown = [thrown.slice(), api.get('E.k1.st')];
// out of spendable balls while a plan runs: no 30 s hold, every spawn is opened for a look
api.set('E', {p1: ent(774)}); api.set('NE', 1); api.set('PEND', ['p1']); api.set('LIVE', {p1: {}}); api.set('HOLD', 0);
api.call('catchTick', NOW + 2000);
res.peekOnly = [api.get('PEEKONLY'), api.get('HOLD'), api.get('E.p1.peek'), opened.length];
// a wrong shiny read (every reply "shiny") must not spend the kept balls: over 1 in 10 -> stop trusting it
api.set('ST.shiny', 5); api.set('ST.rep1', 10); api.set('OUT.log', []);
api.set('E', {w1: Object.assign(ent(10), {st: 'open', tOpen: NOW + 2000, opens: 1, peek: 1})}); api.set('NE', 1); api.set('PEND', []);
api.set('RESP', {w1: {st: 1, p: {1: 0.5}, t: NOW + 2100, strong: 0, shiny: 1}});
api.call('catchTick', NOW + 2200);
res.wrongField = [api.get('SHINYOFF'), api.get('E.w1') === undefined, api.get('OUT.log').filter(l => l.indexOf('SHINY LOOK suspended') === 0).length];
// a Mighty one of a left-alone species: the look found it -> it stays (Mighty Pokemon get their own balls)
api = mk();
api.call('applyCfg', {catch: true, skipSp: [10], peek: true, floors: {'1': 5, '2': 5, '3': 5}, openMs: 0, maxOpen: 6, readyMs: 150, nearWait: 0});
api.set('walk', () => {}); api.set('ITEMC', {1: 100, 2: 5, 3: 5});
api.set('openOne', (enc, e, o, now) => { e.st = 'open'; e.tOpen = now; e.opens++; }); api.set('throwAt', () => {});
api.set('E', {m1: Object.assign(ent(10), {st: 'open', tOpen: NOW, opens: 1, peek: 1})}); api.set('NE', 1); api.set('PEND', []); api.set('LIVE', {m1: {}});
api.set('RESP', {m1: {st: 1, p: {1: 0.01, 3: 0.2}, t: NOW + 100, strong: 1, shiny: 0}});
api.call('catchTick', NOW + 200);
res.mightyPeek = [api.get('E.m1') !== undefined, api.get('E.m1.peek'), api.get('E.m1.mighty'), api.get('PEEKED.m1') || 0];
// KEEP IN ALL from the LIVE bag (review 11-16): floorOf() = Python reserve_floors() on the same counts, 600 bags
const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
api = mk();
res.floorOf = cases.filter(x => { api.call('applyCfg', {floors: {'1': 5, '2': 5, '3': 5}, reserve: x[3]}); api.set('ITEMC', {1: x[0], 2: x[1], 3: x[2]});
  return [1, 2, 3].some(b => api.call('floorOf', b) !== x[4][b - 1]); }).map(x => x.slice(0, 4));
// a new process: Python has no counts yet, the JS has them -- bag 20/25/5 = the 50 kept: no ordinary throw at all
api.call('applyCfg', {floors: {'1': 5, '2': 5, '3': 5}, reserve: 35}); api.set('ITEMC', {1: 20, 2: 25, 3: 5});
res.keepLive = [api.call('pickBall', {1: 0.3, 2: 0.4, 3: 0.5}, false, 0, 0)];
api.set('ITEMC', {}); res.keepLive.push(api.call('ballOk', 1));                      // counts unread + a keep: nothing
api.call('applyCfg', {reserve: 0}); res.keepLive.push(api.call('ballOk', 1));         // counts unread, no keep: as before
// a shiny takes a kept Ultra: the spare Poke Ball now makes up the Ultra floor at once (not 10 s later)
api.call('applyCfg', {reserve: 35}); api.set('ITEMC', {1: 41, 2: 5, 3: 5}); res.keepLive.push(api.call('ballOk', 1));
api.set('ITEMC', {1: 41, 2: 5, 3: 4}); res.keepLive.push(api.call('ballOk', 1));
// the REAL throwAt (review 11-16: the stub hid it): a shiny at the keep gets an Ultra written into the throw; a plain one none
api = mk();
const wrote = [];
api.set('il', () => ({newObject: () => ({add: (off) => ({writeS32: (v) => wrote.push([off, v]), writeFloat: () => {}, writeU8: () => {}})})}));
api.set('method', () => 'TC'); api.set('call', () => null); api.set('LASTOK', true); api.set('myPos', () => null);
api.call('applyCfg', {floors: {'1': 5, '2': 5, '3': 5}, reserve: 35}); api.set('ITEMC', {1: 40, 2: 5, 3: 5});
const eS = {pid: 10, cls: 'WildMapPokemon', st: 'ready', probs: {1: 0.2, 2: 0.3, 3: 0.4}, prio: false, mighty: 0, shiny: 1, att: 0};
const eK = {pid: 774, cls: 'WildMapPokemon', st: 'ready', probs: {1: 0.3, 2: 0.4, 3: 0.5}, prio: false, mighty: 0, shiny: 0, att: 0};
api.call('throwAt', eS, 'S', {}, NOW); api.call('throwAt', eK, 'K', {}, NOW);
res.realThrow = [wrote.filter(w => w[0] === 0x10).map(w => w[1]), eS.st, eK.st, api.get('ITEMC[3]')];
// the latch: 6 shinies in 200 replies is real (no latch); 6 in 58 is a wrong read (latch)
api = mk();
api.call('applyCfg', {catch: true, skipSp: [10], peek: true, floors: {'1': 5, '2': 5, '3': 5}, openMs: 0, maxOpen: 6, readyMs: 150, nearWait: 0});
api.set('walk', () => {}); api.set('ITEMC', {1: 100, 2: 5, 3: 5}); api.set('openOne', () => {}); api.set('throwAt', () => {});
const latch = (rep1) => { api.set('SHINYOFF', false); api.set('ST.shiny', 5); api.set('ST.rep1', rep1);
  api.set('E', {L: Object.assign(ent(774), {st: 'open', tOpen: NOW, opens: 1})}); api.set('NE', 1); api.set('PEND', []); api.set('LIVE', {L: {}});
  api.set('RESP', {L: {st: 1, p: {1: 0.5}, t: NOW + 100, strong: 0, shiny: 1}}); api.call('catchTick', NOW + 200); return api.get('SHINYOFF'); };
res.latch = [latch(199), latch(57)];
// a reply of ANOTHER species can never land on an open (dead in practice, kept as a guard)
api.set('SHINYOFF', false); api.set('ST.shiny', 0);
api.set('E', {x1: Object.assign(ent(10), {st: 'open', tOpen: NOW, opens: 1})}); api.set('NE', 1); api.set('PEND', []); api.set('LIVE', {x1: {}});
api.set('RESP', {x1: {st: 1, p: {1: 0.5}, t: NOW + 100, strong: 0, shiny: 1, sp: 999}});
api.call('catchTick', NOW + 200);
res.latch.push(api.get('E.x1.st'), api.get('RESP.x1') === undefined);
// the shiny read itself: WildPokemon -> PokemonProto -> display -> Shiny byte (wild), and a lure reply's PokemonProto
api = mk();
globalThis.uint64 = (v) => ({v: v});
api.set('OFF.wPk', 0x20); api.set('OFF.pkDisp', 0x30); api.set('OFF.dShiny', 0x40); api.set('OFF.pkId', 0x50);
api.set('readProbs', () => ({1: 0.5})); api.set('strongOf', () => 0); api.set('mightyOf', () => 0);
const disp = (sh) => ({isNull: () => false, add: (o) => ({readU8: () => (o === 0x40 ? sh : 0)})});
const pkP = (sp, sh) => ({isNull: () => false, add: (o) => ({readS32: () => sp, readPointer: () => (o === 0x30 ? disp(sh) : NUL)})});
const wildP = (id, sh) => ({isNull: () => false, add: (o) => ({readU64: () => ({compare: () => 1, toString: () => id}), readPointer: () => (o === 0x20 ? pkP(0, sh) : NUL)})});
const encOut = (id, sh) => ({add: (o) => ({readPointer: () => (o === 0x10 ? wildP(id, sh) : NUL), readS32: () => 1})});
api.set('RESP', {});
api.call('onEncounterOut', encOut('111', 1)); api.call('onEncounterOut', encOut('222', 0));
res.shinyRead = [api.get('RESP')['111'].shiny, api.get('RESP')['222'].shiny];
api.set('NWOFF', {X: {res: 1, pk: 2, cp: 3}});
api.set('E', {a: {pid: 10, st: 'open'}}); api.set('NWQ', [{enc: 'a', t: NOW}]); api.set('LASTNW', {t: 0, sig: ''});
api.call('onOtherEncounterOut', {add: (o) => ({readS32: () => 1, readPointer: () => (o === 2 ? pkP(10, 1) : NUL)})}, 'X');
res.shinyRead.push(api.get('RESP.a') ? api.get('RESP.a').shiny : null);
// walk() + the queue with no ball to spend (PEEKONLY): a spawn already looked at is left; a new one is opened for a look
const walkSetup = (a) => {
  a.set('call', (m, o, args) => m === 'ALL' ? a.get('COLL') : (m === 'VM' ? 1 : (m === 'PID' ? o.pid : null)));
  a.set('M', {allPokemon: 'ALL'}); a.set('il', () => ({className: (k) => k, objClass: (o) => 'WildMapPokemon'}));
  a.set('cstr', (x) => x); a.set('each', (c, f) => c.forEach(f)); a.set('encOf', (o) => o.enc);
  a.set('method', (o, name) => name === 'get_VisibleOnMap' ? 'VM' : 'PID'); a.set('u8', (x) => x); a.set('s32', (x) => x);
  a.set('spawnInfo', () => ({exp: 0, tth: 0, sp: '', lat: null, lng: null})); a.set('myPos', () => null); };
api = mk(); walkSetup(api);
api.call('applyCfg', {skipSp: [], peek: true}); api.set('PEEKONLY', true); api.set('PEEKED', {q1: 1});
api.set('COLL', [{enc: 'q1', pid: 774}, {enc: 'q2', pid: 774}]);
api.call('walk', NOW);
res.peekOnly2 = [Object.keys(api.get('E')), api.get('OUT.led').map(r => r.e)];
api = mk();
api.call('applyCfg', {catch: true, skipSp: [], peek: true, floors: {'1': 40, '2': 5, '3': 5}, openMs: 0, maxOpen: 6, readyMs: 150, nearWait: 0});
api.set('walk', () => {}); api.set('ITEMC', {1: 40, 2: 5, 3: 5});
const op2 = []; api.set('openOne', (enc, e) => { op2.push(enc); e.st = 'open'; e.opens++; });
api.set('E', {pa: ent(774), pb: ent(774)}); api.set('NE', 2); api.set('PEND', ['pa', 'pb']); api.set('LIVE', {pa: {}, pb: {}}); api.set('PEEKED', {pa: 1});
api.call('catchTick', NOW);
res.peekOnly2.push(op2.slice(), api.get('E.pa') === undefined, api.get('E.pb.peek'));
// a distrusted shiny read (SHINYOFF): a left-alone species is left at sight again, no open for nothing
api = mk(); walkSetup(api);
api.call('applyCfg', {skipSp: [10], peek: true}); api.set('SHINYOFF', true);
api.set('COLL', [{enc: 'z1', pid: 10}]);
api.call('walk', NOW);
res.shinyOff = [Object.keys(api.get('E')).length, api.get('OUT.led').map(r => r.r)];
// two lure spawns of one species: one open at a time (their replies are told apart by species only); others go on
api = mk();
api.call('applyCfg', {catch: true, skipSp: [], peek: false, floors: {'1': 5, '2': 5, '3': 5}, openMs: 0, maxOpen: 6, readyMs: 150, nearWait: 0});
api.set('walk', () => {}); api.set('ITEMC', {1: 100, 2: 5, 3: 5});
const op3 = []; api.set('openOne', (enc, e, o, now) => { op3.push(enc); e.st = 'open'; e.tOpen = now; e.opens++; });
const lure = (pid) => Object.assign(ent(pid), {cls: 'TroyDiskMapPlacePokemon'});
api.set('E', {l1: lure(10), l2: lure(10), l3: lure(41), w1: ent(10)}); api.set('NE', 4); api.set('PEND', ['l1', 'l2', 'l3', 'w1']);
api.set('LIVE', {l1: {}, l2: {}, l3: {}, w1: {}});
api.call('catchTick', NOW);
res.nwSerial = [op3.slice(), api.get('PEND')];
// a wild open of a species never holds back a lure of it (wild replies carry the encounter id)
api.set('E', {w0: Object.assign(ent(10), {st: 'open', tOpen: NOW, opens: 1}), l9: lure(10)}); api.set('NE', 2); api.set('PEND', ['l9']);
api.set('LIVE', {w0: {}, l9: {}}); op3.length = 0;
api.call('catchTick', NOW + 50);
res.nwSerial.push(op3.slice());
// SHINYOFF inside catchTick (review 11-16, round 2): at the keep nothing is opened for a look (a HOLD instead); a queued
// left-alone spawn is left; looks already in flight when the read is distrusted stay left alone (the list decides)
api = mk();
api.call('applyCfg', {catch: true, skipSp: [10], peek: true, floors: {'1': 5, '2': 5, '3': 5}, reserve: 35, openMs: 0, maxOpen: 6, readyMs: 150, nearWait: 0});
api.set('walk', () => {}); api.set('ITEMC', {1: 40, 2: 5, 3: 5}); api.set('SHINYOFF', true);
const op4 = [], th4 = [];
api.set('openOne', (enc, e) => { op4.push(enc); e.st = 'open'; e.opens++; }); api.set('throwAt', (e) => { th4.push(e.pid); e.st = 'thrown'; });
api.set('E', {h1: ent(774)}); api.set('NE', 1); api.set('PEND', ['h1']); api.set('LIVE', {h1: {}}); api.set('HOLD', 0);
api.call('catchTick', NOW);
res.shinyOffTick = [api.get('PEEKONLY'), api.get('HOLD') > NOW, op4.slice()];
api.set('ITEMC', {1: 100, 2: 5, 3: 5}); api.set('HOLD', 0);
api.set('E', {q9: ent(10)}); api.set('NE', 1); api.set('PEND', ['q9']); api.set('LIVE', {q9: {}});
api.call('catchTick', NOW + 31000);
res.shinyOffTick.push(op4.slice(), api.get('E.q9') === undefined);
api = mk();
api.call('applyCfg', {catch: true, skipSp: [10], peek: true, floors: {'1': 5, '2': 5, '3': 5}, reserve: 35, openMs: 0, maxOpen: 6, readyMs: 0, nearWait: 0});
api.set('walk', () => {}); api.set('ITEMC', {1: 100, 2: 5, 3: 5}); api.set('ST.shiny', 5); api.set('ST.rep1', 50); api.set('OUT.log', []);
const th5 = []; api.set('openOne', () => {}); api.set('throwAt', (e) => { th5.push(e.pid); e.st = 'thrown'; });
const look = () => Object.assign(ent(10), {st: 'open', tOpen: NOW, opens: 1, peek: 1});
api.set('E', {f1: look(), f2: look(), f3: look()}); api.set('NE', 3); api.set('PEND', []); api.set('LIVE', {f1: {}, f2: {}, f3: {}});
api.set('RESP', {f1: {st: 1, p: {1: 0.5}, t: NOW + 100, strong: 0, shiny: 1}, f2: {st: 1, p: {1: 0.5}, t: NOW + 100, strong: 0, shiny: 0},
                 f3: {st: 1, p: {1: 0.5}, t: NOW + 100, strong: 0, shiny: 0}});
api.call('catchTick', NOW + 200); api.call('catchTick', NOW + 1500);
res.latchInFlight = [api.get('SHINYOFF'), th5.slice(), api.get('ST.skip.ballsave')];
// counts read for some ball types only: with a keep, nothing ordinary is thrown
api.call('applyCfg', {reserve: 35}); api.set('ITEMC', {1: 100}); res.latchInFlight.push(api.call('ballOk', 1));
// the Mighty hold: Great/Ultra only (ballOk, 0 while a plan runs); the Razz kept for a Mighty stays (berryFor)
api = mk();
api.set('M', {useItem: 'U'}); api.set('MLAST', NOW - 60000);
api.call('applyCfg', {floors: {'1': 5, '2': 5, '3': 5}, reserve: 0, mightyKeep: 30, mightyBalls: 0, razz: true, razzFloor: 5, razzThresh: 0.45, pinap: false});
api.set('ITEMC', {1: 0, 2: 20, 3: 20, 701: 20});
res.mightyHold = [api.call('ballOk', 2), api.call('berryFor', {probs: {2: 0.3}, prio: false, mighty: 0, shiny: 0})];
api.call('applyCfg', {mightyBalls: 30});
res.mightyHold.push(api.call('ballOk', 2));
// ---- STARDUST ONLY (Benny 11-18: "only catches high stardust pokemon (+ shinies)"; "yes include weather boosted too").
// The left-alone list is the REAL table's at switch 1 (every normal-level species); each spawn of one is opened for a look.
const dust = JSON.parse(fs.readFileSync(process.argv[4], 'utf8')), B = dust.base, K = dust.kept;
const dmk = (extra) => { const a = mk();
  a.call('applyCfg', Object.assign({catch: true, skipSp: dust.skip1, skipWx: [], peek: true, floors: {'1': 5, '2': 5, '3': 5}, openMs: 0, maxOpen: 12,
                                    readyMs: 150, nearWait: 0}, extra || {}));
  a.set('walk', () => {}); a.set('ITEMC', {1: 100, 2: 50, 3: 50}); return a; };
const stubs = (a, op, th) => { a.set('openOne', (enc, e, o, now) => { op.push(enc); e.st = 'open'; e.tOpen = now; e.opens++; });
  a.set('throwAt', (e, enc, o, now) => { th.push(enc); e.st = 'thrown'; e.ball = 1; e.att++; e.tThrow = now; }); };
const queue = (a, ents) => { const live = {}; Object.keys(ents).forEach(k => { live[k] = {}; });
  a.set('E', ents); a.set('NE', Object.keys(ents).length); a.set('PEND', Object.keys(ents)); a.set('LIVE', live); };
const rp = (o) => Object.assign({st: 1, p: {1: 0.5, 2: 0.6, 3: 0.7}, t: NOW + 500, strong: 0, shiny: 0}, o);
const lk = (pid) => Object.assign(ent(pid), {st: 'open', tOpen: NOW, opens: 1, peek: 1});
api = dmk();
res.dustCfg = [Object.keys(api.get('CFG.skipSp')).length === dust.skip1.length, JSON.stringify(api.get('CFG.skipWx')), api.get('CFG.peek'),
               api.get('CFG.skipSp')[B], api.get('CFG.skipSp')[K] || 0];
const dop = [], dth = [];
stubs(api, dop, dth);
queue(api, {b1: ent(B), b2: ent(B), b3: ent(B), b4: ent(B), k1: ent(K), b6: ent(B)});
api.call('catchTick', NOW);
res.dustOpen = [dop.slice(), ['b1', 'b2', 'b3', 'b4', 'k1', 'b6'].map(k => api.get('E.' + k + '.peek'))];
// the replies: plain, weather-boosted, shiny, Mighty, a kept species, and one whose weather flag did not read
api.set('RESP', {b1: rp({wx: 0}), b2: rp({wx: 3}), b3: rp({wx: 0, shiny: 1}), b4: rp({wx: 0, strong: 1}), k1: rp({wx: 0}), b6: rp({wx: -1})});
api.call('catchTick', NOW + 600);
res.dustReply = [api.get('E.b1') === undefined, api.get('PEEKED.b1'), api.get('OUT.led').map(r => [r.e, r.r, r.pk, r.wx]),
                 api.get('E.b2.wxc'), api.get('E.b2.peek'), api.get('E.b3.shiny'), api.get('E.b3.peek'), api.get('E.b4.mighty'), api.get('E.b6.wxc'), api.get('E.k1.wx'),
                 api.get('OUT.log').filter(l => l.indexOf('SHINY Wild #' + B + ' ') === 0 && l.indexOf(' -- of a species being left alone, caught anyway') > 0).length];
api.call('catchTick', NOW + 1000);
res.dustThrown = dth.slice();
api.set('RES', {b2: {st: 1, dust: 275, candy: 3, xp: 100, t: NOW + 1500}, k1: {st: 1, dust: 4225, candy: 3, xp: 100, t: NOW + 1500},
                b6: {st: 1, dust: 225, candy: 3, xp: 100, t: NOW + 1500}});
api.call('catchTick', NOW + 1600);
res.dustCatch = api.get('OUT.log').filter(l => l.indexOf('CATCH ') === 0);
res.dustLed = api.get('OUT.led').filter(r => r.r === 'caught').map(r => [r.e, r.pk, r.wx, r.d]);
// at a level: the species x1.25 does not lift to it stay left even when boosted (CFG.skipWx), and are marked; the level is
// lowered -> that spawn is looked at again, a plainly left one is not
api = dmk({skipWx: [B]});
const op7 = [], th7 = []; stubs(api, op7, th7);
queue(api, {x1: lk(B), y1: lk(B)}); api.set('PEND', []);
api.set('RESP', {x1: rp({wx: 3}), y1: rp({wx: 0})});
api.call('catchTick', NOW + 600);
res.dustLevel = [api.get('E.x1') === undefined, api.get('PEEKED.x1'), api.get('PEEKED.y1'), api.call('lookedAt', 'x1', B), api.call('lookedAt', 'y1', B)];
api.call('applyCfg', {skipSp: dust.skip1, skipWx: []});
res.dustLevel.push(api.call('lookedAt', 'x1', B), api.call('lookedAt', 'y1', B));
queue(api, {x1: ent(B), y1: ent(B)});
api.call('catchTick', NOW + 30000);
res.dustLevel.push(op7.slice(), api.get('E.y1') === undefined);
// a species the boost DOES lift over the level (L): boosted -> caught; not boosted -> left; a boosted lower one -> left
const L = 5001;
api = dmk({skipSp: [B, L], skipWx: [B]});
const opA = [], thA = []; stubs(api, opA, thA);
queue(api, {l1: lk(L), l2: lk(L), l3: lk(B)}); api.set('PEND', []);
api.set('RESP', {l1: rp({wx: 2}), l2: rp({wx: 0}), l3: rp({wx: 2})});
api.call('catchTick', NOW + 600);
res.dust1000 = [api.get('E.l1.wxc'), api.get('E.l1.peek'), api.get('E.l2') === undefined, api.get('PEEKED.l2'), api.get('E.l3') === undefined, api.get('PEEKED.l3')];
// no ball to spend (every ball at its floor): a boosted one is left too, and comes back when the balls do
api = dmk({floors: {'1': 100, '2': 50, '3': 50}});
const op8 = [], th8 = []; stubs(api, op8, th8);
queue(api, {p1: lk(B)}); api.set('PEND', []);
api.set('RESP', {p1: rp({wx: 3})});
api.call('catchTick', NOW + 600);
res.dustNoBall = [api.get('PEEKONLY'), api.get('E.p1') === undefined, api.get('PEEKED.p1'), th8.length];
api.set('ITEMC', {1: 300, 2: 50, 3: 50});
queue(api, {p1: ent(B)});
api.call('catchTick', NOW + 30000);
res.dustNoBall.push(api.get('PEEKONLY'), op8.slice());
// a ball-saver plan alone sends no weather list: a boosted spawn of a species it leaves is left, exactly as before
api = mk();
api.call('applyCfg', {catch: true, skipSp: [B], peek: true, floors: {'1': 5, '2': 5, '3': 5}, openMs: 0, maxOpen: 6, readyMs: 150, nearWait: 0});
api.set('walk', () => {}); api.set('ITEMC', {1: 100, 2: 50, 3: 50});
const op9 = [], th9 = []; stubs(api, op9, th9);
queue(api, {q1: lk(B)}); api.set('PEND', []);
api.set('RESP', {q1: rp({wx: 3})});
api.call('catchTick', NOW + 600);
res.dustPlanOnly = [api.get('CFG.skipWx'), api.get('E.q1') === undefined, api.get('PEEKED.q1'), api.call('lookedAt', 'q1', B)];
api.call('applyCfg', {skipSp: [B], skipWx: []}); res.dustPlanOnly.push(JSON.stringify(api.get('CFG.skipWx')), api.call('lookedAt', 'q1', B));
api.call('applyCfg', {skipSp: [B]}); res.dustPlanOnly.push(api.get('CFG.skipWx'), api.call('lookedAt', 'q1', B));
// walk(): 46 s of nothing but left-alone spawns keeps the map "alive" (no 45 s REFRESH), each spawn counted once; the
// mode switched off -> the spawn is caught once its 20 s have passed
api = mk(); walkSetup(api);
api.call('applyCfg', {catch: true, skipSp: dust.skip1, skipWx: [], peek: true});
api.set('COLL', [{enc: 'r1', pid: B}]); api.set('PEEKED', {r1: 1}); api.set('LASTVIS', 0);
[0, 10000, 30000, 46000].forEach(ms => api.call('walk', NOW + ms));
res.dustWalk = [api.get('LASTVIS') - NOW, Object.keys(api.get('E')).length, api.get('ST.skip.ballsave'), api.get('OUT.led').length];
api.call('applyCfg', {skipSp: []});
api.call('walk', NOW + 47000); res.dustWalk.push(Object.keys(api.get('E')).length);
api.call('walk', NOW + 51000); res.dustWalk.push(Object.keys(api.get('E')));
// walk(): never looked at -> tracked for its look; left for its boost under another level -> tracked again; plainly left -> left
api = mk(); walkSetup(api);
api.call('applyCfg', {catch: true, skipSp: dust.skip1, skipWx: [], peek: true});
api.set('COLL', [{enc: 'w2', pid: B}, {enc: 'w1', pid: B}, {enc: 'w0', pid: B}]); api.set('PEEKED', {w2: 2, w1: 1});
api.call('walk', NOW);
res.dustWalk2 = [Object.keys(api.get('E')).sort(), api.get('ST.skip.ballsave')];
// the weather flag itself: PokemonProto -> display -> WeatherBoostedCondition (the object the shiny byte is read from)
api = mk();
api.set('OFF.pkDisp', 0x30); api.set('OFF.dWx', 0x20);
const dispW = (v) => ({isNull: () => false, add: (o) => ({readS32: () => (o === 0x20 ? v : 77)})});
const pkW = (v) => ({isNull: () => false, add: (o) => ({readPointer: () => (o === 0x30 ? dispW(v) : NUL)})});
res.wxOf = [api.call('wxOf', pkW(3)), api.call('wxOf', pkW(0)), api.call('wxOf', pkW(99)), api.call('wxOf', pkW(-1)), api.call('wxOf', NUL), api.call('wxOf', null)];
api.set('OFF.dWx', -1); res.wxOf.push(api.call('wxOf', pkW(3)));
api.set('OFF.dWx', 0x20); api.set('OFF.pkDisp', -1); res.wxOf.push(api.call('wxOf', pkW(3)));
api.set('OFF.pkDisp', 0x30); res.wxOf.push(api.call('wxOf', {isNull: () => false, add: () => ({readPointer: () => NUL})}));
api = mk();
api.set('OFF.wPk', 0x20); api.set('OFF.pkDisp', 0x30); api.set('OFF.dShiny', 0x40); api.set('OFF.dWx', 0x44); api.set('OFF.pkId', 0x50);
api.set('readProbs', () => ({1: 0.5})); api.set('strongOf', () => 0); api.set('mightyOf', () => 0);
const dispX = (sh, wx) => ({isNull: () => false, add: (o) => ({readU8: () => (o === 0x40 ? sh : 0), readS32: () => (o === 0x44 ? wx : 77)})});
const pkX = (sp, sh, wx) => ({isNull: () => false, add: (o) => ({readS32: () => sp, readPointer: () => (o === 0x30 ? dispX(sh, wx) : NUL)})});
const wildX = (id, sh, wx) => ({isNull: () => false, add: (o) => ({readU64: () => ({compare: () => 1, toString: () => id}), readPointer: () => (o === 0x20 ? pkX(0, sh, wx) : NUL)})});
const encX = (id, sh, wx) => ({add: (o) => ({readPointer: () => (o === 0x10 ? wildX(id, sh, wx) : NUL), readS32: () => 1})});
api.set('RESP', {});
api.call('onEncounterOut', encX('111', 0, 4)); api.call('onEncounterOut', encX('222', 1, 0));
res.wxRead = [api.get('RESP')['111'].wx, api.get('RESP')['111'].shiny, api.get('RESP')['222'].wx, api.get('RESP')['222'].shiny];
api.set('NWOFF', {X: {res: 1, pk: 2, cp: 3}});
api.set('E', {a: {pid: 10, st: 'open'}}); api.set('NWQ', [{enc: 'a', t: NOW}]); api.set('LASTNW', {t: 0, sig: ''});
api.call('onOtherEncounterOut', {add: (o) => ({readS32: () => 1, readPointer: () => (o === 2 ? pkX(10, 0, 2) : NUL)})}, 'X');
res.wxRead.push(api.get('RESP.a') ? api.get('RESP.a').wx : null);
// PAYERS FIRST (11-18): a spawn that gets a ball is opened before the spawns opened only for a look; each group keeps its order
const pfq = (cfg, ents, items) => { const a = mk(), op = [];
  a.call('applyCfg', Object.assign({catch: true, floors: {'1': 5, '2': 5, '3': 5}, openMs: 0, maxOpen: 12, readyMs: 150, nearWait: 0}, cfg));
  a.set('walk', () => {}); a.set('ITEMC', items || {1: 100, 2: 50, 3: 50});
  a.set('openOne', (enc, e, o, now) => { op.push(enc); e.st = 'open'; e.tOpen = now; e.opens++; }); a.set('throwAt', () => {});
  const live = {}; Object.keys(ents).forEach(k => { live[k] = {}; });
  a.set('E', ents); a.set('NE', Object.keys(ents).length); a.set('PEND', Object.keys(ents)); a.set('LIVE', live);
  const same = a.get('PEND'); a.call('catchTick', NOW); return [op, a.get('PEND') === same]; };
const exp = (pid, ms) => Object.assign(ent(pid), {exp: NOW + ms});
res.pf = [
  pfq({skipSp: [10], peek: true}, {a1: ent(10), k1: ent(774), a2: ent(10), k2: ent(774), a3: ent(10)}),            // looks and payers mixed
  pfq({}, {x1: ent(10), x2: ent(774), x3: ent(10)}),                                                                 // no plan, no mode: arrival order
  pfq({skipSp: [10], peek: false}, {n1: ent(10), n2: ent(774)})[0],                                                  // left alone without a look: only the payer is opened
  pfq({skipSp: [10], peek: true, order: 'despawn'}, {l1: exp(10, 3000), p1: exp(774, 9000), l2: exp(10, 2000), p2: exp(774, 4000)})[0],   // despawn-first inside each group
  pfq({skipSp: [10], peek: true}, {o1: ent(10), o2: ent(774)}, {1: 5, 2: 5, 3: 5})[0],                               // no ball to spend: every open is a look, arrival order
  pfq({skipSp: [10], peek: true}, {q1: ent(774), q2: ent(774), q3: ent(10), q4: ent(10)}),                           // already in order: the queue is not rewritten
  pfq({skipSp: [10], peek: true}, {r1: ent(10), r2: Object.assign(ent(774), {retryAt: NOW + 4000}), r3: ent(774)})[0],   // a payer that must wait does not block the rest
];
console.log(JSON.stringify(res));
""")
import random
rnd = random.Random(1116)
ns["CFG"]["floors"] = {"1": 5, "2": 5, "3": 5}
cases = []
for _ in range(600):   # Python's reserve_floors() on random bags: the JS floorOf() must give the same floors
    bag = {"1": rnd.choice([0, 1, 3, 5, 6, 10, 20, 35, 40, 41, 60, 100, 300]), "2": rnd.randint(0, 60), "3": rnd.randint(0, 60)}
    rv = rnd.choice([0, 1, 10, 35, 85, 200])
    rf = ns["reserve_floors"](rv, bag) if rv else {"1": 5, "2": 5, "3": 5}
    cases.append([bag["1"], bag["2"], bag["3"], rv, [rf["1"], rf["2"], rf["3"]]])
cp = os.path.join(d, "floors.json")
json.dump(cases, open(cp, "w"))
dj = os.path.join(d, "dust.json")
json.dump(DUSTJS, open(dj, "w"))
r2 = subprocess.run(["node", t2, p, cp, dj], capture_output=True, text=True)
try:
    got2 = json.loads(r2.stdout.strip() or "{}")
except ValueError:
    got2 = {}
check("JS: a shiny's ball (floors, odds, none)", got2.get("ball"), [0, 3, 1, 0, 2])
check("JS: no ball -> no berry; shiny gets Razz", got2.get("berry"), [0, 701])
check("JS: Pinap only: hard throw, shiny, easy throw get the Pinap, never a Razz; no Pinap left = no berry",
      got2.get("pinapOnly"), [705, 705, 705, 0])
check("JS: in-flight poll lowers, never raises", got2.get("poll"), [40, 39, 45, 41])
check("JS: shiny Mighty -> Safari, then Ultra", got2.get("mighty"), [7, 3])
check("JS: another species' reply is not ours", got2.get("other"), [None, 10, -1])
check("JS: a Mighty found by the look stays", got2.get("mightyPeek"), [True, 0, 1, 0])
check("JS: floorOf = Python reserve_floors (600 bags)", got2.get("floorOf"), [])
check("JS: keep from live counts (new process, shiny dip)", got2.get("keepLive"), [0, False, True, True, False])
check("JS: the REAL throwAt: shiny Ultra, plain none", got2.get("realThrow"), [[3], "thrown", "ready", 4])
check("JS: latch 6/200 no, 6/58 yes; other species' reply", got2.get("latch"), [False, True, "open", True])
check("JS: the shiny byte read (wild x2, lure)", got2.get("shinyRead"), [1, 0, 1])
check("JS: no ball to spend: looked-at left, new looked at", got2.get("peekOnly2"), [["q2"], ["q1"], ["pb"], True, 1])
check("JS: distrusted shiny read: left at sight", got2.get("shinyOff"), [0, ["ballsave"]])
check("JS: one lure open per species at a time", got2.get("nwSerial"), [["l1", "l3", "w1"], ["l2"], ["l9"]])
check("JS: SHINYOFF: hold at the keep, queued one left", got2.get("shinyOffTick"), [False, True, [], [], True])
check("JS: looks in flight at the latch: no throw", got2.get("latchInFlight"), [True, [], 3, False])
check("JS: Mighty hold on G/U only; its Razz kept", got2.get("mightyHold"), [True, 0, False])
check("JS: walk tracks a look, ledgers a looked one", got2.get("walk"), [["r1"], ["r1"], {"ballsave": 1}, [["r2", "ballsave", 0, 10]]])
check("JS: left-alone species opened for a look -- after the spawn that gets a ball (payers first)", got2.get("open"), [["k1", "s1", "s2"], 1, 1, 0])
check("JS: not shiny left; shiny kept + logged", got2.get("reply"),
      [True, 1, 1, [["s1", "ballsave", 1]], "ready", 1, 1, 1, True])
check("JS: the shiny gets Ultra; k1 waits (reserve)", got2.get("thrown"), [[3], "ready"])
check("JS: no ball to spend: look, don't hold", got2.get("peekOnly"), [True, 0, 1, 4])
check("JS: 'shiny' on >1 in 10 replies: distrusted", got2.get("wrongField"), [True, True, 1])
B, K = DUSTJS["base"], DUSTJS["kept"]
check("JS dust: the real list arrives (every normal-level species); an empty weather list still means 'applied'",
      got2.get("dustCfg"), [True, "{}", True, 1, 0])
check("JS dust: every spawn is opened -- a left-alone species' as a look, a kept species' as a catch",
      got2.get("dustOpen"), [["k1", "b1", "b2", "b3", "b4", "b6"], [1, 1, 1, 1, 0, 1]])
check("JS dust: not boosted -> left (its record: looked, wx 0); boosted -> a throw; shiny and Mighty stay; a flag that did not read -> a throw",
      got2.get("dustReply"), [True, 1, [["b1", "ballsave", 1, 0]], 1, 0, 1, 1, 1, 2, 0, 1])
check("JS dust: thrown at: the boosted one, the shiny, the Mighty, the kept species, the unread one -- never the plain one",
      got2.get("dustThrown"), ["b2", "b3", "b4", "k1", "b6"])
pf = got2.get("pf") or [None] * 7
check("JS payers first: looks and payers mixed -> the payers are opened first, each group in its arrival order; the queue is the same array",
      pf[0], [["k1", "k2", "a1", "a2", "a3"], True])
check("JS payers first: no plan and no mode (nothing is left alone) -> arrival order, the queue untouched", pf[1], [["x1", "x2", "x3"], True])
check("JS payers first: a species left alone WITHOUT a look is never opened; the payer is", pf[2], ["n2"])
check("JS payers first: with despawn-first each group keeps its soonest-first order", pf[3], ["p2", "p1", "l2", "l1"])
check("JS payers first: no ball to spend (every open is a look) -> arrival order", pf[4], ["o1", "o2"])
check("JS payers first: payers already in front -> nothing is rewritten", pf[5], [["q1", "q2", "q3", "q4"], True])
check("JS payers first: a payer that must wait for its retry does not hold up the others", pf[6], ["r3", "r1"])
check("JS payers first: the catch loop calls it only while a look is on and a ball can be spent, after despawn-first",
      (src.count("payersFirst();"), src.find("if (peekOn() && !PEEKONLY && PEND.length > 1 && !holding) payersFirst();")
       > src.find("if (CFG.order === 'despawn' && PEND.length > 1 && !holding) despawnFirst(now);") > 0), (1, True))
check("JS dust: CATCH lines: [boosted] + wx= on the boosted one, wx=0 on the kept species, [boost?] and no wx= when it did not read",
      got2.get("dustCatch"), [f"CATCH Wild #{B} ball=1 p=0.50 att=1 berry=0 1.6s [boosted] dust=275 candy=3 wx=3",
                              f"CATCH Wild #{K} ball=1 p=0.50 att=1 berry=0 1.6s dust=4225 candy=3 wx=0",
                              f"CATCH Wild #{B} ball=1 p=0.50 att=1 berry=0 1.6s [boost?] dust=225 candy=3"])
check("JS dust: the catch records carry the flag and the award", got2.get("dustLed"), [["b2", 0, 3, 275], ["k1", 0, 0, 4225], ["b6", 0, None, 225]])
check("JS dust -> Python: the weather record reads those lines (species, award, flag); a line without wx= is never judged",
      [(int(x.group(1)), int(x.group(3)), int(x.group(4))) if x else None for x in map(ns["WX_CATCH"].search, got2.get("dustCatch") or [])],
      [(B, 275, 3), (K, 4225, 0), None])
check("JS dust: a level leaves a species even when boosted (marked); the level lowered -> looked at again, the plainly left one not",
      got2.get("dustLevel"), [True, 2, 1, True, True, False, True, ["x1"], True])
check("JS dust: a species the boost lifts over the level: boosted -> caught, not boosted -> left; a boosted lower one -> left",
      got2.get("dust1000"), [1, 0, True, 1, True, 2])
check("JS dust: no ball to spend -> a boosted one is left too; balls back -> looked at again", got2.get("dustNoBall"), [True, True, 2, 0, False, ["p1"]])
check("JS dust: a ball-saver plan alone (no weather list): boosted is left as before; the list comes and goes with the config",
      got2.get("dustPlanOnly"), [None, True, 2, True, "{}", False, None, True])
check("JS dust: 46 s of only left-alone spawns: the map stays alive, each counted once; switched off -> back after its 20 s",
      got2.get("dustWalk"), [46000, 0, 1, 1, 0, ["r1"]])
check("JS dust: walk(): never looked at -> tracked; left for its boost under another level -> tracked again; plainly left -> left",
      got2.get("dustWalk2"), [["w0", "w2"], 1])
check("JS dust: the weather flag read (3, 0, out of range, negative, null pointers, field not found, no display)",
      got2.get("wxOf"), [3, 0, -1, -1, -1, -1, -1, -1, -1])
check("JS dust: the encounter reply carries it, read off the shiny byte's own object (wild x2, a lure reply)", got2.get("wxRead"), [4, 0, 0, 1, 2])
if r2.returncode or r2.stderr.strip():
    print(r2.stderr[-1500:])
    failed += 1
sys.exit(1 if failed else 0)
