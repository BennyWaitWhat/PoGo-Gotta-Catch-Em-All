"""Offline test of the BALL-SAVER in catch_loop_fast.py (no phone): python tools/catcher_ballsave_sim.py
Python side: the greedy cut (ballsave_skip) and the ball count (usable_balls). JS side (node): the species list from the
config, a spawn left alone counted once, its 20 s look-again, and its ledger record. Exit code 1 when any check fails."""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, os.pardir, "system", "scripts", "game_write", "catch_loop_fast.py"), encoding="utf-8").read()
import time
ns = {"CFG": {"floors": {"1": 5, "2": 5, "3": 5}}, "_BS": {"mtime": None, "plan": None, "note": "off"}, "re": re, "time": time,
      "SP": {"on": False, "off": False, "since": None, "bare": 0}, "SHINYFIELD": {"ok": True}}
for name in ("usable_balls", "ballsave_skip", "plan_reserve", "plan_live", "floor_short", "reserve_floors", "ballsave_reserve",
             "ballsave_now", "ballsave_log", "cfg_now", "starpiece_seen", "balls_why", "starpiece_why"):
    exec(re.search(rf"^def {name}\(.*?(?=^\n\ndef )", src, re.S | re.M).group(0), ns)
exec(re.search(r"^SPIN_WHY = .*$", src, re.M).group(0), ns)
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
import json
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
ns.update(FLAGS={}, flag=lambda k: False)
ns["CFG"].update(floors={"1": 5, "2": 5, "3": 5})
json.dump(dict(PLAN, end=time.time() - 60, reserve=100), open(pf, "w"))
os.utime(pf, (time.time() + 20, time.time() + 20))
c = ns["cfg_now"]()
check("reserve -> Poke Ball floor 105, end passed", (c["floors"], c["skipSp"]), ({"1": 105, "2": 5, "3": 5}, []))
check("ended plan: no shiny look", c["peek"], False)
json.dump(dict(PLAN, end=time.time() + 600, keep=50), open(pf, "w"))
os.utime(pf, (time.time() + 30, time.time() + 30))
c = ns["cfg_now"]()
check("live plan, keep 50: floor 40 + shiny look", (c["floors"], c["peek"]), ({"1": 40, "2": 5, "3": 5}, True))
os.remove(pf)
c = ns["cfg_now"]()
check("plan deleted -> floors back to 5", c["floors"], {"1": 5, "2": 5, "3": 5})
# a bag short of Great Balls: the keep makes up the floor, and the saver's budget counts it too
json.dump(dict(PLAN, end=time.time() + 100 * 60, keep=50), open(pf, "w"))
os.utime(pf, (time.time() + 40, time.time() + 40))
ns["BALLS"].update(usable=95, items={"1": 100, "2": 3, "3": 5})
c = ns["cfg_now"]()
check("short floor: 58 to spend, floors 42/5/5", (ns["_BS"]["note"][:16], c["floors"]), ("58 balls to spen", {"1": 42, "2": 5, "3": 5}))
ns["SHINYFIELD"]["ok"] = False
check("no shiny field at attach: no shiny look", ns["cfg_now"]()["peek"], False)
ns["SHINYFIELD"]["ok"] = True
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
ns["SP"].update(on=True, off=True, since="20:45:57")
spw = lambda why: ns["starpiece_why"](why, time.time())
check("Star Piece out + spins refused: both", spw("spins are being refused by the server (6 in a row)"),
      "the Star Piece ran out at 20:45:57: catches pay a third less stardust; spins are being refused by the server (6 in a row)")
check("a catching problem is never hidden", spw("the game is not answering: 9 encounters opened"), "the game is not answering: 9 encounters opened")
os.remove(pf)
ns["ballsave_now"]()
check("no plan: no Star Piece line", spw(""), "")
ns["SP"].update(on=False, off=False, since=None, bare=0)

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
api.set('RESP', {s1: {st: 1, p: {1: 0.5, 2: 0.6, 3: 0.7}, t: NOW + 500, strong: 0, shiny: 0},
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
console.log(JSON.stringify(res));
""")
r2 = subprocess.run(["node", t2, p], capture_output=True, text=True)
try:
    got2 = json.loads(r2.stdout.strip() or "{}")
except ValueError:
    got2 = {}
check("JS: a shiny's ball (floors, odds, none)", got2.get("ball"), [0, 3, 1, 0, 2])
check("JS: no ball -> no berry; shiny gets Razz", got2.get("berry"), [0, 701])
check("JS: in-flight poll lowers, never raises", got2.get("poll"), [40, 39, 45, 41])
check("JS: shiny Mighty -> Safari, then Ultra", got2.get("mighty"), [7, 3])
check("JS: another species' reply is not ours", got2.get("other"), [None, 10, -1])
check("JS: a Mighty found by the look stays", got2.get("mightyPeek"), [True, 0, 1, 0])
check("JS: walk tracks a look, ledgers a looked one", got2.get("walk"), [["r1"], ["r1"], {"ballsave": 1}, [["r2", "ballsave", 0, 10]]])
check("JS: left-alone species opened for a look", got2.get("open"), [["s1", "s2", "k1"], 1, 1, 0])
check("JS: not shiny left; shiny kept + logged", got2.get("reply"),
      [True, 1, 1, [["s1", "ballsave", 1]], "ready", 1, 1, 1, True])
check("JS: the shiny gets Ultra; k1 waits (reserve)", got2.get("thrown"), [[3], "ready"])
check("JS: no ball to spend: look, don't hold", got2.get("peekOnly"), [True, 0, 1, 4])
check("JS: 'shiny' on >1 in 10 replies: distrusted", got2.get("wrongField"), [True, True, 1])
if r2.returncode or r2.stderr.strip():
    print(r2.stderr[-1500:])
    failed += 1
sys.exit(1 if failed else 0)
