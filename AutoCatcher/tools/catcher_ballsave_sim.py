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
ns = {"CFG": {"floors": {"1": 5, "2": 5, "3": 5}}}
for name in ("usable_balls", "ballsave_skip"):
    exec(re.search(rf"^def {name}\(.*?(?=^\n\ndef )", src, re.S | re.M).group(0), ns)
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
check("balls not read yet", skip_of(PLAN, None, NOW), ([], "off"))
check("unreadable plan", skip_of({"bad": 1}, 10, NOW), ([], "off: unreadable plan"))
check("the why line", skip_of(PLAN, 1700, NOW)[1], "1700 balls for 100 min: leaving 1 of 4 species alone (at most 150 stardust per ball)")
check("balls above the floors", usable({"1": 1704, "2": 5, "3": 9}), 1703)
check("balls not read", usable({}), None)

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
sys.exit(1 if failed else 0)
