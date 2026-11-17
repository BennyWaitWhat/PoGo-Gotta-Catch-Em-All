"""Offline checks of the gym runner's 2026-11-17 lessons (Benny: "stop touching the phone and improve").
No phone, no Frida: the runner's own functions run against a fake clock and temp files, the tapper's real pick / ban code
runs under node against mock Pokemon records.   python test_gym_awareness.py   (node is needed for parts 1-2; CI has it)

  1. the tapper script text: `node --check`; direct deploy is OFF until the runner turns it on, announces itself before its
     first reflection call, and the stale 0.429.1 addresses are gone;
  2. a fused part (a Zekrom / Reshiram held inside a Kyurem) never fights and is never placed; a banned id never fights;
     a game build without the field changes nothing (the REAL fusedPart / usable / pickCandidate / ban code under node);
  3. jump bookkeeping: jumps the server has not answered are ONE chain -- an island hop + a short jump is measured from the
     hop, with the hop's distance (11-17 00:25: it was written down as "a 74 m jump");
  4. no table wait: a refusal re-asks after the 8 s crash guard; the first counted battle ends the wait and proves the six;
  5. the six as the suspect: proven fighters persist, suspects = never in a counted battle, a ban reaches the tapper, the
     bag list and the counter ranking;
  6. the per-gym report: rounds won per battle shape (as seen in 64 battles of 11-17), win -> placed seconds, the flags,
     the row in gym_reports.jsonl, and the stopwatch fed through Game.on_msg;
  7. the direct deploy crash guard: a game that closes right after an unanswered announcement turns it off for this run
     and for later runs; `--direct-deploy on` asks for another try; an answered announcement is never a suspect;
  8. the banner over the map does not block a gym open; the placement fallback = highest-CP shinies first, never a
     legendary, never one of the attackers;
  9. error 29 ("The Gym battle has already been completed!"): the tapper neither re-opens the gym nor presses Battle
     for 5 s, and an open() the runner asks for inside that hold is queued, never a way around it (the REAL openPending /
     screenText / open under node); the runner handles one error once and at once, sets no hold for a stale one (a round
     start or a jump since, or older than 15 s -- the phantom holds of 11-17 00:25 / 00:30), bans the never-proven member
     after two in a row with NO jump (never after a jump: a cooldown refuses dozens), never waits past 40 s, and starts a
     new streak after 2 min; the battle six is filled with picks that are neither fused nor banned first; every name the
     tapper script reads is declared somewhere (a typo would throw on the phone).
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time as _time
import types

if importlib.util.find_spec("frida") is None:                # CI / the offline sandbox: nothing here ever attaches
    sys.modules["frida"] = types.ModuleType("frida")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gym_tapper  # noqa: E402
import gym_run  # noqa: E402

NODE = shutil.which("node")
FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL:", msg)
    return cond


class Clock:
    """gym_run's `time`, with a clock the test moves (everything else is the real module)."""
    def __init__(self, t):
        self.t = t

    def time(self):
        return self.t

    def __getattr__(self, n):
        return getattr(_time, n)


def said(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ret = fn(*a, **k)
    return buf.getvalue(), ret


def js_fn(js, name):
    """The source of one top-level `function name(...) {...}` of the tapper script (brace-matched, comments and strings skipped)."""
    a = js.index(f"\nfunction {name}(") + 1
    i = js.index("{", js.index(")", a))
    depth = 0
    while i < len(js):
        c = js[i]
        if js.startswith("/*", i):
            i = js.index("*/", i) + 2
            continue
        if c in "'\"":
            j = i + 1
            while js[j] != c:
                j += 2 if js[j] == "\\" else 1
            i = j + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return js[a:i + 1]
        i += 1
    raise ValueError(f"function {name} not closed")


# ------------------------------------------------------------------------------------------------ 1. the script text
def script_text(js):
    n0 = len(FAILS)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "tapper.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run([NODE, "--check", p], capture_output=True, text=True)
        check(r.returncode == 0, "node --check of the whole tapper script failed: " + (r.stderr or r.stdout).strip()[:600])
    check("DD_SLOT" not in js and "DD_FN" not in js, "the stale 0.429.1 direct-deploy addresses (DD_SLOT / DD_FN) are back")
    check(re.search(r"var DD_ON = false\b", js) is not None, "direct deploy must be OFF until the runner says so (var DD_ON = false)")
    check("directdeploy: function (on) { DD_ON = !!on;" in js, "the directdeploy() export (the runner's switch) is missing")
    res = js_fn(js, "ddResolve")
    check(res.index("if (!DD_ON) return null;") < res.index("DD_TRY++"), "ddResolve() must refuse before any reflection call while the switch is off")
    dd = js_fn(js, "directDeploy")
    check("if (!DD_ON || !DD_OK" in dd, "directDeploy() must refuse while the switch is off")
    check("ddResolve(" not in dd and "var mi = DD_SEND;" in dd,
          "directDeploy() must never build the request sender itself: only ddTick does, after its announcement (the crash guard reads it)")
    tick = js_fn(js, "ddTick")
    check("send({k: 'ddtry'})" in tick and tick.index("send({k: 'ddtry'})") < tick.index("ddResolve()"),
          "ddTick must announce ('ddtry') before it builds the request sender")
    check("now - DD_ANN > 400" in tick, "the build must come a moment AFTER its announcement (the message must leave the game first)")
    check("} else DD_ANN = 0;" in tick, "an announcement must not outlive the plain map: leaving it before the build means announcing again")
    callers = re.findall(r"(?<!function )\bddResolve\(", re.sub(r"/\*.*?\*/", "", js, flags=re.S))
    check(len(callers) == 1, f"ddResolve() must have exactly ONE caller (ddTick, after its announcement): {len(callers)} call sites")
    check("send({k: 'ddarmed'" in js, "a victory that arms a direct deploy must say so ('ddarmed') before the call")
    check("send({k: 'ddsend', ok: !!DD_SEND" in res, "ddResolve() must report READY / NOT available ('ddsend')")
    check("!/Toast|^NotificationGuiController$/.test(TOP)" in js, "the tapper's gym open must not wait for the notification banner")
    check("!fusedPart(p, o)" in js_fn(js, "usable") and "!fusedPart(p, o)" in js_fn(js, "pickCandidate"),
          "a fused part must be refused by usable() AND by pickCandidate()")
    if len(FAILS) == n0:
        print("ok: tapper script passes node --check; direct deploy is off until asked, announced before it runs; fused parts are refused")


# The tapper cannot run offline, and `node --check` only parses: a name that is never declared (a typo, a helper that was
# renamed) throws on the phone, the first time that branch runs. This walks the whole script with node's own parser and
# lists every name that is read but declared nowhere -- not in its function, not at top level, not a JS / Frida global.
FRIDA_GLOBALS = ("undefined,NaN,Infinity,Object,Array,String,Number,Boolean,Math,JSON,Date,RegExp,Error,TypeError,RangeError,parseInt,"
                 "parseFloat,isNaN,isFinite,console,setTimeout,clearTimeout,setInterval,clearInterval,setImmediate,Promise,Symbol,Map,Set,"
                 "WeakMap,Uint8Array,ArrayBuffer,Function,globalThis,Memory,Process,Module,NativeFunction,NativeCallback,NativePointer,"
                 "Interceptor,Thread,Script,ptr,NULL,send,recv,rpc,UInt64,Int64,uint64,int64,hexdump,DebugSymbol,ApiResolver,Frida,CModule")
FREE_JS = r"""
const fs = require('fs'); let acorn;
try { acorn = require('internal/deps/acorn/acorn/dist/acorn'); } catch (e) { console.log('SKIP'); process.exit(0); }
const ast = acorn.parse(fs.readFileSync(process.argv[2], 'utf8'), {ecmaVersion: 2020, locations: true});
const ALLOW = new Set(process.argv[3].split(','));
function Scope(parent) { this.names = new Set(); this.parent = parent; }
Scope.prototype.has = function (n) { for (let s = this; s; s = s.parent) if (s.names.has(n)) return true; return false; };
function decl(p, scope) {
  if (!p) return;
  if (p.type === 'Identifier') scope.names.add(p.name);
  else if (p.type === 'ObjectPattern') p.properties.forEach(q => decl(q.value || q.argument, scope));
  else if (p.type === 'ArrayPattern') p.elements.forEach(q => decl(q, scope));
  else if (p.type === 'AssignmentPattern') decl(p.left, scope);
  else if (p.type === 'RestElement') decl(p.argument, scope);
}
function kids(node, fn) { for (const k in node) { if (k === 'type' || k === 'loc') continue; const v = node[k];
  if (Array.isArray(v)) v.forEach(c => { if (c && typeof c.type === 'string') fn(c); }); else if (v && typeof v.type === 'string') fn(v); } }
function hoist(node, scope) {                  /* var / function declarations of THIS function (never of a nested one) */
  if (node.type === 'FunctionDeclaration') { scope.names.add(node.id.name); return; }
  if (node.type === 'FunctionExpression' || node.type === 'ArrowFunctionExpression') return;
  if (node.type === 'VariableDeclaration') node.declarations.forEach(d => decl(d.id, scope));
  kids(node, c => hoist(c, scope));
}
const free = {};
function walk(node, scope) {
  switch (node.type) {
    case 'FunctionDeclaration': case 'FunctionExpression': case 'ArrowFunctionExpression': {
      const s = new Scope(scope); s.names.add('arguments');
      if (node.type === 'FunctionExpression' && node.id) s.names.add(node.id.name);
      node.params.forEach(p => decl(p, s));
      kids(node.body, c => hoist(c, s));
      if (node.body.type === 'BlockStatement') kids(node.body, c => walk(c, s)); else walk(node.body, s);
      return; }
    case 'CatchClause': { const s = new Scope(scope); decl(node.param, s); walk(node.body, s); return; }
    case 'Identifier': if (!scope.has(node.name) && !ALLOW.has(node.name)) (free[node.name] = free[node.name] || []).push(node.loc.start.line); return;
    case 'MemberExpression': walk(node.object, scope); if (node.computed) walk(node.property, scope); return;
    case 'Property': if (node.computed) walk(node.key, scope); walk(node.value, scope); return;
    case 'VariableDeclarator': if (node.init) walk(node.init, scope); return;
    case 'LabeledStatement': walk(node.body, scope); return;
    case 'BreakStatement': case 'ContinueStatement': return;
  }
  kids(node, c => walk(c, scope));
}
const top = new Scope(null);
kids(ast, c => hoist(c, top));
kids(ast, c => walk(c, top));
console.log(JSON.stringify(free));
"""


def free_names(js):
    n0 = len(FAILS)
    with tempfile.TemporaryDirectory() as td:
        p, q = os.path.join(td, "tapper.js"), os.path.join(td, "free.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js)
        with open(q, "w", encoding="utf-8") as f:
            f.write(FREE_JS)
        r = subprocess.run([NODE, "--expose-internals", q, p, FRIDA_GLOBALS], capture_output=True, text=True)
        out = (r.stdout or "").strip()
        if out == "SKIP" or r.returncode != 0:
            print("SKIP: the undeclared-name scan did NOT run -- this node has no internal parser"
                  + (f": {(r.stderr or '').strip()[:200]}" if r.returncode else "") + " (a typo in the tapper script would go unseen here)")
            return
        free = json.loads(out.splitlines()[-1])
        check(not free, "the tapper script reads names that are declared nowhere (they throw on the phone when that line runs): "
              + "; ".join(f"{k} (script line {', '.join(map(str, v[:4]))})" for k, v in sorted(free.items())))
        r2 = subprocess.run([NODE, "--expose-internals", q, p, FRIDA_GLOBALS.replace(",send,", ",")], capture_output=True, text=True)
        seen = json.loads((r2.stdout or "{}").strip().splitlines()[-1] or "{}")
        check("send" in seen and len(seen["send"]) > 20, "the undeclared-name scan is blind: it did not see `send` once it left the allow list")
    if len(FAILS) == n0:
        print("ok: every name the tapper script reads is declared (its own functions and variables, or a JS / Frida global)")


# ------------------------------------------------------------------------------------------------ 2. fused parts / bans under node
PICK_MOCK = r"""
function str(p) { return p ? String(p) : ''; }
var M = {isMega: null}, K = {};
function callB() { return false; }
function Rec(o) { this.o = o; }
Rec.prototype.add = function (key) { var o = this.o; if (key === undefined) throw new Error('read at an undefined offset');
  return { readS32: function () { return o[key] | 0; }, readU8: function () { return o[key] ? 1 : 0; },
           readPointer: function () { return o[key] || null; }, readU64: function () { return {toString: function () { return String(o[key]); }}; } }; };
var LIVE = {};
function liveProto(id) { return LIVE[String(id)] || null; }
var OFFS = {stamina: 'hp', maxStamina: 'max', deployedFortId: 'fort', deployedStationId: 'station', isEgg: 'egg', isBad: 'bad',
            isComponent: 'comp', id: 'id', cp: 'cp'};
function protoOffs() { return OFFS; }
"""
PICK_RUN = r"""
function mk(o) { var r = new Rec(o); LIVE[o.id] = r; return r; }
var zek = mk({id: '12126051191352048111', cp: 3294, hp: 180, max: 180, comp: 1});   /* the Zekrom inside the Black Kyurem */
var gy1 = mk({id: '1', cp: 3721, hp: 0, max: 190});                                 /* fainted */
var gy2 = mk({id: '2', cp: 3680, hp: 190, max: 190, fort: 'abc.16'});               /* in a gym */
var sci = mk({id: '3', cp: 3393, hp: 170, max: 170});
var egg = mk({id: '4', cp: 10, hp: 10, max: 10, egg: 1});
var out = {};
out.fused = [fusedPart(zek, OFFS), fusedPart(sci, OFFS)];
out.usable = [zek, gy1, gy2, sci, egg].map(function (p) { return usable(p, OFFS); });
var pk = pickCandidate(['12126051191352048111', '1', '2', '3']);
out.pick = pk && pk.id; out.pickCp = pk && pk.cp;
out.pickOnlyFused = pickCandidate(['12126051191352048111']);
out.banN = ban(['3']); out.usableBanned = usable(sci, OFFS); out.banAgain = ban(['3', 7]);
var OLD = {}; for (var k in OFFS) if (k !== 'isComponent') OLD[k] = OFFS[k];        /* a game build without the field */
out.oldFused = fusedPart(zek, OLD); out.oldUsable = usable(zek, OLD);
console.log(JSON.stringify(out));
"""


def pick_block(js):
    n0 = len(FAILS)
    m = re.search(r"\n  ban: (function \(ids\) \{.*?\}),   /\* out of every team", js)
    if not check(m is not None, "the ban() export changed shape: the test cannot find it"):
        return
    src = "\n".join([PICK_MOCK, js_fn(js, "fusedPart"), js_fn(js, "usable"), "var BANNED = {};", js_fn(js, "pickCandidate"),
                     "var ban = " + m.group(1) + ";", PICK_RUN])
    check(re.search(r"\nvar BANNED = \{\};", js) is not None, "var BANNED = {} is gone from the tapper script")
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "pick.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(src)
        r = subprocess.run([NODE, p], capture_output=True, text=True)
    if not check(r.returncode == 0, "the pick / ban code threw under node: " + (r.stderr or r.stdout).strip()[:600]):
        return
    o = json.loads(r.stdout.strip().splitlines()[-1])
    check(o["fused"] == [True, False], f"fusedPart(): the Zekrom inside the Kyurem is a fused part, a Scizor is not: {o['fused']}")
    check(o["usable"] == [False, False, False, True, False], f"usable(): fused / fainted / in a gym / healthy / egg = {o['usable']}")
    check(o["pick"] == "3" and o["pickCp"] == 3393, f"pickCandidate() must skip the fused one, the fainted one and the one in a gym: {o['pick']}")
    check(o["pickOnlyFused"] is None, "pickCandidate() must place nothing when only a fused part is offered")
    check(o["banN"] == 1 and o["usableBanned"] is False and o["banAgain"] == 2, f"ban(): a banned id never fights; the count grows: {o}")
    check(o["oldFused"] is False and o["oldUsable"] is True, "a game build without isComponent_: nothing is a fused part, nothing throws")
    if len(FAILS) == n0:
        print("ok: a fused part never fights and is never placed; a banned id never fights; a build without the field changes nothing")


# ------------------------------------------------------------------------------------------------ 9a. the tapper's error-29 hold
HOLD_MOCK = r"""
var SENT = [], CALLS = [], PENDING = null, PENDING_AT = 0, LEAF = 'MapExploreState', LEFT_GYM_AT = 0, MAP_SINCE = 0, TOP = 'MainMenuGuiController';
var LAST_OPEN = {fid: null, at: 0}, CHAIN = 'MapExploreState', K = {MapGym: {}}, M = {tapped: 'tapped'}, O = {textM: 'text'};
var GYMS = {gymA: {readPointer: function () { return {equals: function (k) { return k === K.MapGym; }}; }}};
var SAYS = {GlobalErrorController: ['errorMessage'], PgoToastGuiController: ['message']}, SAYQ = [];
function send(m) { SENT.push(m); }
function alive() { return true; }
function isA() { return true; }
function str(p) { return p ? String(p) : ''; }
function call(m, o, what) { CALLS.push(what); return {}; }
function gui(text) { return {add: function () { return {readPointer: function () { return {isNull: function () { return false; },
  add: function () { return {readPointer: function () { return text; }}; }}; }}; }}; }
"""
HOLD_RUN = r"""
var out = {guard: E29_GUARD_MS};
PENDING = 'gymA'; PENDING_AT = 900;                                 /* the battle's own 'end' asked for a re-open ... */
SAYQ = [{at: 0, gui: gui('The Gym battle has already been completed! (29)'), k: 1, name: 'GlobalErrorController'}];
screenText(1000);                                                   /* ... and the game says (29) */
out.said = SENT.filter(function (m) { return m.k === 'says'; }).map(function (m) { return m.text; });
out.hold = E29_HOLD; out.pendingAfter29 = PENDING;
PENDING = 'gymA'; PENDING_AT = 1000; openPending(3000); out.openedInHold = CALLS.length;
openPending(6100); out.openedAfterHold = CALLS.length; out.pendingAfterOpen = PENDING;
E29_HOLD = 0; SAYQ = [{at: 0, gui: gui('You earned 50 coins (29)'), k: 1, name: 'PgoToastGuiController'}]; screenText(7000);
out.holdAfterToast = E29_HOLD;
CALLS = []; LAST_OPEN = {fid: null, at: 0};
TOP = 'NotificationGuiController'; PENDING = 'gymA'; PENDING_AT = 20000; openPending(21000); out.openedUnderBanner = CALLS.length;
LAST_OPEN = {fid: null, at: 0};
TOP = 'GymApproachGuiController'; PENDING = 'gymA'; PENDING_AT = 40000; openPending(41000); out.openedOverGymScreen = CALLS.length - out.openedUnderBanner;
/* the gym badge popup swallows the open after a victory: open again the moment the map is back, not 12 s later */
CALLS = []; SENT = []; PENDING = 'gymA'; PENDING_AT = 60000; LAST_OPEN = {fid: null, at: 0}; TOP = 'MainMenuGuiController'; CHAIN = 'MapExploreState';
openPending(60100); out.badgeFirstOpen = CALLS.length;
TOP = 'GymBadgeAwardGuiController'; openPending(61000); openPending(62000); out.badgeDuringPopup = CALLS.length;
TOP = 'MainMenuGuiController'; openPending(63000); out.badgeRearmed = CALLS.length; openPending(63100); openPending(64000); out.badgeSecondOpen = CALLS.length;
out.badgeTold = SENT.filter(function (m) { return m.k === 'info'; }).length;
/* ... but never when the gym screen DID come, and never for another screen */
CALLS = []; PENDING = 'gymA'; PENDING_AT = 80000; LAST_OPEN = {fid: null, at: 0}; TOP = 'MainMenuGuiController'; CHAIN = 'MapExploreState';
openPending(80100); TOP = 'GymBadgeAwardGuiController'; openPending(81000);
CHAIN = 'MapExploreState > GymRootState > GymState > GymApproachState'; TOP = 'MainMenuGuiController'; openPending(82000); openPending(82100);
out.noRearmWhenOpened = CALLS.length;
CALLS = []; PENDING = 'gymA'; PENDING_AT = 90000; LAST_OPEN = {fid: null, at: 0}; TOP = 'MainMenuGuiController'; CHAIN = 'MapExploreState';
openPending(90100); TOP = 'ScreenFadeGuiController'; openPending(91000); TOP = 'MainMenuGuiController'; openPending(92000); openPending(92100);
out.noRearmForAFade = CALLS.length;
/* the runner's own open() inside the hold is QUEUED until the hold ends -- it never cancels the hold, it never expires meanwhile */
CALLS = []; PENDING = null; LAST_OPEN = {fid: null, at: 0}; TOP = 'MainMenuGuiController'; CHAIN = 'MapExploreState';
var T = Date.now(); E29_HOLD = T + 5000;
var r1 = openExport('gymA'); out.heldAnswer = r1.held; out.holdKept = E29_HOLD === T + 5000; out.queued = PENDING;
openPending(T + 100); openPending(T + 4900); out.openedInsideHold = CALLS.length;
openPending(T + 5001); out.openedWhenHoldEnded = CALLS.length;
E29_HOLD = 0; var r2 = openExport('gymA'); out.notHeldAnswer = r2.held;
CHAIN = 'MapExploreState > GymRootState > GymState'; out.busyAnswer = openExport('gymA').busy === true;
/* the battle hook's fill-in: the game's own picks that are a fused part or banned go in only if the six would stay short */
function fill(mineIds, origRecs, len) { var o = OFFS, have = {}, out = [];
  mineIds.forEach(function (id) { have[id] = 1; out.push(LIVE[id]); });
  var orig = origRecs;
  FILL_BLOCK
  return out.map(function (q) { return q.o.id; }); }
function rec(o) { var r = new Rec(o); r.isNull = function () { return false; }; LIVE[o.id] = r; return r; }
var NUL = {isNull: function () { return true; }};
var a = rec({id: 'a'}), b = rec({id: 'b'}), c = rec({id: 'c'}), d = rec({id: 'd'}), e = rec({id: 'e'}), f6 = rec({id: 'f'}), g7 = rec({id: 'g'}), zk = rec({id: 'zek', comp: 1});
BANNED = {e: 1};
out.fillClean = fill(['a', 'b', 'c'], [a, zk, d, e, f6, g7], 6);
out.fillShort = fill(['a', 'b'], [a, zk, e, NUL, NUL, NUL], 6);
console.log(JSON.stringify(out));
"""


def hold_block(js):
    n0 = len(FAILS)
    m = re.search(r"\nvar E29_HOLD = 0, E29_GUARD_MS = (\d+);", js)
    if not check(m is not None, "var E29_HOLD / E29_GUARD_MS is gone from the tapper script"):
        return
    ex = re.search(r"\n  open: (function \(fid\) \{.*?\}),\n  pickname:", js, re.S)
    a = js.find("[true, false].forEach(function (clean) {")
    b = js.find("}); });", a)
    if not check(ex is not None and a > 0 and b > a, "the open() export or the battle hook's fill-in changed shape: the test cannot find them"):
        return
    pick_bits = "\n".join([PICK_MOCK.replace("var M = {isMega: null}, K = {};", "M.isMega = null;").replace("function str(p) { return p ? String(p) : ''; }", ""),
                           js_fn(js, "fusedPart"), "var BANNED = {};"])
    src = "\n".join([HOLD_MOCK, f"var E29_HOLD = 0, E29_GUARD_MS = {m.group(1)};", js_fn(js, "openPending"), js_fn(js, "screenText"),
                     "var openExport = " + ex.group(1) + ";", pick_bits, HOLD_RUN.replace("FILL_BLOCK", js[a:b + len("}); });")])])
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "hold.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(src)
        r = subprocess.run([NODE, p], capture_output=True, text=True)
    if not check(r.returncode == 0, "the error-29 hold code threw under node: " + (r.stderr or r.stdout).strip()[:600]):
        return
    o = json.loads(r.stdout.strip().splitlines()[-1])
    check(o["guard"] == 5000 and o["hold"] == 6000 and o["pendingAfter29"] is None and o["said"] == ["The Gym battle has already been completed! (29)"],
          f"error (29) on screen: a 5 s hold starts, the pending re-open is dropped, the text still reaches the runner: {o}")
    check(o["openedInHold"] == 0 and o["openedAfterHold"] == 1 and o["pendingAfterOpen"] is None, f"no re-open inside the hold, one after it: {o}")
    check(o["holdAfterToast"] == 0, "only the game's error dialog starts the hold, never another screen's text")
    check(o["openedUnderBanner"] == 1 and o["openedOverGymScreen"] == 0, f"the notification banner is the plain map; a gym screen is not: {o}")
    check((o["badgeFirstOpen"], o["badgeDuringPopup"], o["badgeRearmed"], o["badgeSecondOpen"], o["badgeTold"]) == (1, 1, 2, 2, 1),
          f"the gym badge popup swallowed the open: ONE more open in the very tick the map is back (not 12 s later), said once: {o}")
    check(o["noRearmWhenOpened"] == 1 and o["noRearmForAFade"] == 1, f"no second open when the gym screen came, nor after a plain screen fade: {o}")
    check("&& now >= E29_HOLD && !ACT" in js, "the tapper's automatic Battle press must respect the error-29 hold")
    check("leaf === 'MapExploreState' && Date.now() >= E29_HOLD) { PENDING = AUTODEP.fid;" in js, "a battle that ends in error 29 must not queue a re-open")
    check((o["heldAnswer"], o["holdKept"], o["queued"], o["openedInsideHold"], o["openedWhenHoldEnded"], o["notHeldAnswer"], o["busyAnswer"]) ==
          (True, True, "gymA", 0, 1, False, True),
          f"an open() from the runner inside the hold is queued, never cancels it, and goes out the tick the hold ends: {o}")
    check(o["fillClean"] == ["a", "b", "c", "d", "f", "g"], f"the battle six is filled with the game's picks that are neither fused nor banned: {o['fillClean']}")
    check(o["fillShort"] == ["a", "b", "zek", "e"], f"only if the six would stay short do the others go in -- never a hole, never one twice: {o['fillShort']}")
    if len(FAILS) == n0:
        print("ok: after error 29 the tapper neither re-opens nor presses Battle for 5 s; the runner's own open is queued until the hold ends; "
              "the banner does not block; the badge popup gets one re-open; the six is filled with clean picks first")


# ------------------------------------------------------------------------------------------------ helpers for 3-9
def fresh(td, t0=1794894000.0):
    """gym_run's module state as at a start, with a clock at t0 and every state file inside td."""
    clock = Clock(t0)
    gym_run.time = clock
    gym_run.JUMPED.clear()
    gym_run.JUMPED.update(t=0.0, m=0.0, told=True)
    gym_run.COOL.update(on=False, until=0.0, n=0, last29=0.0, said=False, ok_seen=0.0)
    gym_run.E29.update(n=0, t1=0.0, until=0.0, last=0.0)
    gym_run.LAST_ACT.update(t=0.0, pos=None)
    gym_run.COOL_OBS = os.path.join(td, "cooldown_obs.jsonl")
    gym_run.PROVEN.update(ids=set(), loaded=False, path=os.path.join(td, "proven_fighters.json"))
    gym_run.TEAM_BAN.clear()
    gym_run.BAG_RO_ALL[:] = []
    gym_run.CT["cur"] = None
    gym_run.GREG["g"] = {}
    gym_run.NAMES.clear()
    gym_run.DD.update(off=None, try_at=0.0, armed_at=0.0, gone_at=0.0, on_done=False, path=os.path.join(td, "direct_deploy_off.json"))
    return clock


def obs_rows():
    try:
        with open(gym_run.COOL_OBS, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except FileNotFoundError:
        return []


class FakeTapper:
    def __init__(self):
        self.calls = []
        self.exports_sync = self

    def ban(self, ids):
        self.calls.append(("ban", sorted(ids)))
        return len(ids)

    def autobattle(self, on):
        self.calls.append(("autobattle", on))
        return on


# ------------------------------------------------------------------------------------------------ 3 + 4. jumps, cooldown
def jump_checks():
    n0 = len(FAILS)
    flat = lambda a, b: round(abs(a[0] - b[0]) * 111320 + abs(a[1] - b[1]) * 84400)   # a simple metre for the pure function
    j1 = gym_run.jump_chain({"t": 0.0, "m": 0.0, "told": True}, 100.0, 2194, (40.6897, -74.0453), {"t": 90.0, "pos": (40.6978, -74.0413)}, flat)
    check((j1["n"], j1["sum_m"], j1["max_m"], j1["t0"], j1["told"], j1["act_gap"]) == (1, 2194, 2194, 100.0, False, 10.0), f"a first jump: {j1}")
    check(j1["act_m"] == flat((40.6978, -74.0413), (40.6897, -74.0453)), f"act_m = metres from the last counted action to the landing: {j1['act_m']}")
    j1["refused_s"] = 12.5
    j2 = gym_run.jump_chain(j1, 130.0, 74, (40.6893, -74.0447), {"t": 90.0, "pos": (40.6978, -74.0413)}, flat)
    check((j2["n"], j2["sum_m"], j2["max_m"], j2["t0"], j2["m"], j2["refused_s"]) == (2, 2268, 2194, 100.0, 74, 12.5),
          f"a second jump before the server answered the first stays in ONE chain (and keeps its refusals): {j2}")
    check(j2["act_gap"] == 10.0 and j2["act_m"] == flat((40.6978, -74.0413), (40.6893, -74.0447)),
          f"a chain keeps the FIRST jump's gap to the last counted action; the metres are to the landing we stand on now: {j2}")
    j_old = gym_run.jump_chain(j2, 130.0 + gym_run.JUMP_CHAIN_S + 1, 50, None, {"t": 90.0}, flat)
    check(gym_run.JUMP_CHAIN_S == 600.0 and (j_old["n"], j_old["sum_m"], j_old["refused_s"]) == (1, 50, 0.0),
          f"an unanswered jump older than 10 min starts no chain (an hour of idle hops is not one cooldown): {j_old}")
    j_edge = gym_run.jump_chain(j2, 130.0 + gym_run.JUMP_CHAIN_S, 50, None, {"t": 90.0}, flat)
    check(j_edge["n"] == 3 and j_edge["t0"] == 100.0, f"...and one inside the 10 min still belongs to it: {j_edge}")
    j2["told"] = True
    j3 = gym_run.jump_chain(j2, 400.0, 163, None, {"t": 0.0}, flat)
    check((j3["n"], j3["sum_m"], j3["max_m"], j3["t0"], j3["refused_s"], j3["act_gap"], j3["act_m"]) == (1, 163, 163, 400.0, 0.0, None, None),
          f"after the server answered, the next jump starts a new chain: {j3}")
    check(gym_run.jump_desc(j3) == "a 163 m jump" and gym_run.jump_desc({"m": 74.4}) == "a 74 m jump", f"jump_desc of one jump: {gym_run.jump_desc(j3)!r}")
    j2["told"] = False
    check(gym_run.jump_desc(j2).startswith("2 jumps (2268 m in all, the longest 2194 m)"), f"jump_desc of a chain: {gym_run.jump_desc(j2)!r}")
    check(gym_run.jump_since(150.0, j2) == 50.0 and gym_run.jump_since(150.0, j3 | {"told": True}) == 0.0,
          "jump_since = seconds since the FIRST unanswered jump; 0 once the server answered")

    with tempfile.TemporaryDirectory() as td:                # the 11-17 00:25 case, end to end
        clock = fresh(td)
        t0 = clock.t
        gym_a, gym_b = "aaaaaaaa11112222333344445555.16", "bbbbbbbb11112222333344445555.16"
        gym_run.GREG["g"] = {gym_a: [40.697778, -74.041302, 1], gym_b: [40.6893, -74.0447, 1]}
        sc = FakeTapper()
        said(gym_run.battles_count, gym_a, "a defender lost CP in our battle (2267 -> 1662 total)", sc)
        check(obs_rows() == [] and gym_run.LAST_ACT["t"] == t0 and tuple(gym_run.LAST_ACT["pos"]) == (40.697778, -74.041302),
              "a counted battle with no jump pending measures nothing, and is remembered as the last counted action (when + where)")
        clock.t = t0 + 10
        said(gym_run.note_jump, 2194, (40.6897, -74.0453))    # the island hop
        clock.t = t0 + 40
        said(gym_run.note_jump, 74, (40.6893, -74.0447))      # onto the gym
        clock.t = t0 + 50
        out, _ = said(gym_run.cool_sign, "battle refused: error 29")
        check("40 s after 2 jumps (2268 m in all, the longest 2194 m)" in out and "50 s after our last counted action" in out,
              f"the refusal line must count from the hop, not from the 74 m jump: {out!r}")
        check(gym_run.COOL["on"] and gym_run.COOL["until"] == clock.t + gym_run.COOL_RETRY_S == clock.t + 8.0 and gym_run.cool_wait(),
              "a refusal re-asks after the 8 s crash guard -- no table wait")
        clock.t = t0 + 70
        said(gym_run.cool_sign, "battle refused: error 29")
        clock.t = t0 + 78.5
        check(not gym_run.cool_wait(), "8 s after the last refusal the next Battle IS the check")
        clock.t = t0 + 157
        out, _ = said(gym_run.battles_count, gym_b, "a defender lost CP in our battle (9327 -> 8265 total)", sc, None, ["11", "22"])
        rows = obs_rows()
        check([r["k"] for r in rows] == ["cooldown_refused", "cooldown_refused", "cooldown"], f"three rows in cooldown_obs.jsonl: {rows}")
        if len(rows) == 3:
            ref, acc = rows[0], rows[2]
            check((ref["jump_m"], ref["chain_n"], ref["chain_m"], ref["last_jump_m"], ref["refused_at_s"], ref["since_last_action_s"]) ==
                  (2194, 2, 2268, 74, 40.0, 50.0), f"the refusal row: {ref}")
            check(rows[1]["refused_at_s"] == 60.0, f"the second refusal, 60 s after the hop: {rows[1]}")
            check((acc["jump_m"], acc["chain_n"], acc["chain_m"], acc["accepted_after_jump_s"], acc["refused_last_s"], acc["since_last_action_s"]) ==
                  (2194, 2, 2268, 147.0, 60.0, 157.0), f"the measured row: {acc}")
            check(acc["from_last_action_m"] is not None and 900 < acc["from_last_action_m"] < 1100 and acc["jumped_after_action_s"] == 10.0
                  and ref["jumped_after_action_s"] == 10.0,
                  f"the landing's distance from the last counted action (Ellis -> Liberty, ~1 km); the chain left 10 s after it (the hop, "
                  f"not the 74 m jump 40 s after): {acc}")
        check("COOLDOWN measured" in out and "147 s after 2 jumps" in out and "between 60 s (refused) and 147 s" in out, f"the measured line: {out!r}")
        check("COOLDOWN over" in out and not gym_run.COOL["on"] and gym_run.JUMPED["told"], "the first counted battle ends the wait")
        check(("autobattle", True) in sc.calls, "Battle presses held back by the wait are released")
        check(gym_run.proven_load() >= {"11", "22"} and tuple(gym_run.LAST_ACT["pos"]) == (40.6893, -74.0447),
              "the six of a counted battle are proven fighters; the last counted action moved to that gym")
        clock.t = t0 + 200
        said(gym_run.note_jump, 163, (40.6899, -74.0455))
        check((gym_run.JUMPED["n"], gym_run.JUMPED["sum_m"], gym_run.JUMPED["act_gap"]) == (1, 163, 43.0) and 60 < gym_run.JUMPED["act_m"] < 110,
              f"the next jump is a new chain, measured from the gym we just battled at: {gym_run.JUMPED}")
    if len(FAILS) == n0:
        print("ok: an island hop + a short jump is one chain measured from the hop; a refusal re-asks after 8 s; a counted battle ends the wait")


# ------------------------------------------------------------------------------------------------ 5. the six as the suspect
def suspect_checks():
    n0 = len(FAILS)
    with tempfile.TemporaryDirectory() as td:
        fresh(td)
        team = ["100", "200", "12126051191352048111", "400"]
        check(gym_run.team_suspects(team) == team, "nothing proven yet: every member is a suspect")
        gym_run.proven_add(["100", 200])
        with open(gym_run.PROVEN["path"], encoding="utf-8") as f:
            check(json.load(f)["ids"] == ["100", "200"], "proven fighters are written to proven_fighters.json")
        gym_run.PROVEN.update(ids=set(), loaded=False)       # a new run reads the file
        check(gym_run.team_suspects(team) == ["12126051191352048111", "400"], f"suspects = never in a counted battle: {gym_run.team_suspects(team)}")
        gym_run.BAG_RO_ALL[:] = [["100", 5000, 1, 1, "Zacian", 0], ["12126051191352048111", 3294, 1, 1, "Zekrom", 0], ["400", 3000, 1, 1, "Raikou", 0]]
        gym_run.CT["cur"] = {"fid": "x", "ids": ["12126051191352048111"], "at": 123.0, "sig": "abc"}
        sc = FakeTapper()
        out, _ = said(gym_run.team_ban, ["12126051191352048111", "400"], "2 battles refused in a row with no jump", sc)
        check(sorted(gym_run.TEAM_BAN) == ["12126051191352048111", "400"] and [r[0] for r in gym_run.BAG_RO_ALL] == ["100"],
              f"a ban leaves the bag list at once: {gym_run.BAG_RO_ALL}")
        check(gym_run.CT["cur"]["at"] == 0 and gym_run.CT["cur"]["sig"] is None, "a ban makes the next reading re-pick the counters")
        check(sc.calls == [("ban", ["12126051191352048111", "400"])], f"a ban is handed to the tapper: {sc.calls}")
        with open(os.path.join(td, "team_bans.jsonl"), encoding="utf-8") as f:
            check(json.loads(f.readline())["ids"] == ["12126051191352048111", "400"], "a ban is written to team_bans.jsonl")
        check(gym_run.team_suspects(team) == [], "banned members are not suspects again; proven ones never were")

        class Broken:
            exports_sync = None
        out, _ = said(gym_run.team_ban, ["500"], "again", Broken())
        check("ban not handed to the tapper" in out and "500" in gym_run.TEAM_BAN, "a tapper that is gone must not stop the ban on the runner's side")
    if len(FAILS) == n0:
        print("ok: proven fighters persist; suspects are the never-proven; a ban reaches the tapper, the bag list and the counter ranking")


# ------------------------------------------------------------------------------------------------ 6. the per-gym report
def msg(g, k, **p):
    return said(g.on_msg, {"type": "send", "payload": dict(p, k=k)}, None)[0]


def report_checks():
    n0 = len(FAILS)
    with tempfile.TemporaryDirectory() as td:
        clock = fresh(td)
        t0 = clock.t
        g = gym_run.Game()
        check(g.rep_line(True, True) is None, "no gym was started: no report")
        g.open_fid = fid = "d431c89010b4434da63e4b6070e6c414.12"
        gym_run.NAMES["d431c890"] = "Statue of Liberty"
        g.rep_new(fid)

        def battle(at, starts, give=False, stay=False, win=False, refused=False):
            clock.t = t0 + at
            msg(g, "pressed", what="Battle", auto=True, ms=1)
            for i in range(starts):
                clock.t += 1 if i == 0 else 10
                msg(g, "start", n=i + 1)
                if stay and i == 0:
                    msg(g, "pressed", what="stay (one-by-one): the first defender was knocked out -- this one is the new first")
                if give and i == starts - 2:
                    msg(g, "pressed", what="Give up now (one-by-one, no prompt)", ok=True)
            if refused:
                msg(g, "says", gui="GlobalErrorController", text="The Gym battle has already been completed! (29)")
            if win:
                clock.t += 9
                msg(g, "outcome", v="victory")
            msg(g, "end", fast=100, charged=5)

        battle(2, 4, give=True, stay=True)                   # 00:48:02: KO (out), KO, abandoned, exit pass  -> 2 rounds won
        battle(38, 3, give=True)                             # 00:48:38: KO, abandoned, exit pass            -> 1
        battle(61, 3, stay=True)                             # 00:49:01: KO (out), KO of the last one, exit   -> 2
        battle(100, 2)                                       # 00:49:40: one defender left: KO, exit pass     -> 1
        battle(114, 1, refused=True)                         # a refused battle (error 29)                    -> 0
        battle(130, 1, win=True)                             # 00:50:09: the last round, VICTORY              -> 1
        t_win = clock.t
        check(g.rep["won"] == 7 and g.rep["empty"] == 1 and g.rep["battles"] == 6 and g.rep["e29"] == 1 and g.rep["stays"] == 2
              and g.rep["giveups"] == 2 and g.rep["starts"] == 14, f"the stopwatch after 6 battles: {g.rep}")
        clock.t = t_win + 6.5
        msg(g, "deployresult", res="Success", ok=True)
        check(g.deploy_ok_at == clock.t, "the deploy result still reaches the runner's own handler")
        clock.t += 1
        path = os.path.join(td, "gym_reports.jsonl")
        line = g.rep_line(True, True, path)
        check(line.startswith("  GYM REPORT d431c890 (Statue of Liberty): arrival -> first battle 3 s | 6 battles, 7 rounds won in "),
              f"the report line: {line!r}")
        check("1 battle(s) won nothing |" in line and "1 refused (error 29) |" in line and "<-- look here" not in line,
              f"one refused battle is reported, not flagged: {line!r}")
        check("win -> your Pokemon in 6.5 s <-- slow" in line and line.endswith("s in all"), f"a slow placement is flagged: {line!r}")
        with open(path, encoding="utf-8") as f:
            row = json.loads(f.readline())
        check((row["rounds_won"], row["battles"], row["refused"], row["win_to_placed_s"], row["placed"], row["one_by_one"], row["knocked_out_mid_battle"]) ==
              (7, 6, 1, 6.5, True, True, 2) and row["fid"] == fid, f"the row in gym_reports.jsonl: {row}")
        check(g.rep is None and g.rep_line(True, True) is None, "a report is given once")

        g.rep_new(fid)                                       # the flags: refused twice, won but not placed
        battle(500, 1, refused=True)
        battle(520, 1, refused=True)
        battle(540, 1, win=True)
        clock.t += 30
        line = g.rep_line(False, True)
        check("2 battle(s) won nothing <-- look here" in line and "2 refused (error 29) <-- look here" in line
              and "won, but NOT placed <-- look here" in line and line.endswith(", nothing placed"), f"the flags: {line!r}")
        g.rep_new(fid)                                       # a join: no battle at all
        clock.t += 5
        msg(g, "deployresult", res="Success", ok=True)
        line = g.rep_line(True, True)
        check(line == "  GYM REPORT d431c890 (Statue of Liberty): 5 s in all", f"a join with no battle: {line!r}")
        g.rep_new(fid)                                       # 'battle over' never came (a detach): the open battle still counts
        clock.t += 1
        msg(g, "pressed", what="Battle")
        msg(g, "start", n=1)
        clock.t += 10
        msg(g, "start", n=2)
        line = g.rep_line(False, False)
        check("1 battles, 1 rounds won" in line, f"a battle whose end never arrived: {line!r}")
    if len(FAILS) == n0:
        print("ok: the per-gym report counts rounds won per battle, times win -> placed, flags refused battles and a win with nothing placed")


# ------------------------------------------------------------------------------------------------ 7. the direct deploy crash guard
def dd_checks():
    n0 = len(FAILS)
    with tempfile.TemporaryDirectory() as td:
        clock = fresh(td)
        t0 = clock.t
        check(gym_run.dd_state("auto") == (True, None) and gym_run.dd_state("off")[0] is False and "Benny's go" in gym_run.dd_state("off")[1],
              "auto = allowed, off = never (and it says whose word it waits for)")
        with open(gym_run.__file__, encoding="utf-8") as f:
            src = f.read()
        check(re.search(r'add_argument\("--direct-deploy", choices=\("auto", "on", "off"\), default="off"', src) is not None,
              "--direct-deploy must default to OFF: direct GYM_DEPLOY requests ran in the hour before the 09-26 lockout -- his go first")
        g = gym_run.Game()
        msg(g, "ddtry")
        check(gym_run.DD["try_at"] == t0, "the announcement is recorded")
        clock.t = t0 + 0.6
        out = msg(g, "ddsend", ok=True, why="Send(...) -> Promise<GymDeployOutProto>, code @0x5170c34", sigs=[])
        check("direct deploy READY" in out and gym_run.DD["try_at"] == 0.0, f"an answered announcement is settled: {out!r}")
        clock.t = t0 + 3
        check(gym_run.dd_guard() is None and gym_run.dd_state("auto") == (True, None), "the game closing AFTER the answer is not the build's doing")
        out = msg(g, "ddsend", ok=False, why="class RpcHandlerExt not found by name", sigs=["x"])
        check("direct deploy NOT available: class RpcHandlerExt not found by name" in out and "Send overloads seen" in out, f"NOT available says why: {out!r}")

        clock.t = t0 + 100                                   # the build takes the game down
        msg(g, "ddtry")
        gym_run.DD["gone_at"] = t0 + 100.9
        clock.t = t0 + 104
        why = gym_run.dd_guard()
        check(why is not None and "request sender was being built" in why, f"the game closed 0.9 s after an unanswered announcement: {why!r}")
        ok, w = gym_run.dd_state("auto")
        check(ok is False and "request sender" in w and os.path.exists(gym_run.DD["path"]), "direct deploy is off for the rest of the run, and written down")
        gym_run.DD.update(off=None, on_done=False)           # a later run
        ok, w = gym_run.dd_state("auto")
        check(ok is False and "'--direct-deploy on' tries it again" in w, f"a later run keeps it off and says how to try again: {w!r}")
        check(gym_run.dd_state("on") == (True, None) and not os.path.exists(gym_run.DD["path"]), "'--direct-deploy on' forgets the verdict and tries again")
        out, _ = said(gym_run.dd_said, why)
        check("direct deploy OFF from here on" in out and said(gym_run.dd_said, None)[0] == "", "the verdict is said once, in plain words")

        gym_run.DD.update(off=None, on_done=False)           # an armed direct deploy
        clock.t = t0 + 200
        msg(g, "ddarmed", fid="abc")
        clock.t = t0 + 203
        msg(g, "deployresult", res="Success (direct, 310 ms)", ok=True)
        check(gym_run.DD["armed_at"] == 0.0 and gym_run.dd_guard() is None, "a direct deploy the server answered is settled")
        msg(g, "ddarmed", fid="abc")
        gym_run.DD["gone_at"] = clock.t + 7
        why = gym_run.dd_guard()
        check(why is not None and "armed" in why and gym_run.dd_state("auto")[0] is False, f"the game closed 7 s after an unanswered armed deploy: {why!r}")
        try:
            os.remove(gym_run.DD["path"])
        except OSError:
            pass
        gym_run.DD.update(off=None, on_done=False)
        msg(g, "ddarmed", fid="abc")
        gym_run.DD["gone_at"] = clock.t + 60
        check(gym_run.dd_guard() is None and gym_run.dd_state("auto") == (True, None), "a game that closes a minute later is not blamed on it")
    if len(FAILS) == n0:
        print("ok: direct deploy turns itself off when the game closes right after an unanswered step; '--direct-deploy on' tries again")


# ------------------------------------------------------------------------------------------------ 8. banner, fallback
def misc_checks():
    n0 = len(FAILS)
    check(gym_run.map_top("NotificationGuiController") and gym_run.map_top("MainMenuGuiController") and gym_run.map_top("GymBadgeToastGuiController"),
          "the plain map: the menu, a toast and the notification banner (it held every re-open after a win for 4-5 s)")
    check(not gym_run.map_top("GymApproachGuiController") and not gym_run.map_top(None) and not gym_run.map_top("ModalDialog"),
          "a gym screen, a prompt or no reading is NOT the plain map")
    with tempfile.TemporaryDirectory() as td:
        fresh(td)
        was = gym_run.NOGYM["set"]
        gym_run.NOGYM["set"] = {"mewtwo"}
        try:
            gym_run.BAG_RO_ALL[:] = [["a1", 5629, 200, 200, "Zacian", 0], ["s1", 3431, 180, 180, "Machamp", 1], ["s2", 3393, 170, 170, "Scizor", 1],
                                     ["n1", 4000, 190, 190, "Dragonite", 0], ["s3", 3900, 100, 190, "Metagross", 1], ["l1", 4724, 200, 200, "Mewtwo", 1],
                                     ["c1", 3600, 200, 200, "Garchomp", 1], ["s4", 3500, 0, 180, "Gardevoir", 1]]
            gym_run.CT["cur"] = {"fid": "x", "ids": ["c1"], "at": 0, "sig": None}
            dep = {"ro": [["a1", 5629, 200, 200, "Zacian"]], "gy": [["g1", 3721, 0, 190], ["g2", 3680, 190, 190]]}
            fb = gym_run.placement_fallback(dep)
            check([x[0] for x in fb] == ["s1", "s2", "n1"],
                  f"the fallback: healthy shinies by CP first, then the rest; never hurt, a legendary, an attacker or a counter: {[x[0] for x in fb]}")
            dep["fb"] = fb
            check(gym_run.place_ids(dep) == ["g1", "g2", "s1", "s2", "n1"], f"what goes in: every Gyarados (HP is read live), then the fallback: {gym_run.place_ids(dep)}")
        finally:
            gym_run.NOGYM["set"] = was
    if len(FAILS) == n0:
        print("ok: the banner does not block a gym open; out of Gyarados = the highest-CP shinies first")


# ------------------------------------------------------------------------------------------------ 9b. the runner's error-29 handling
def stall_checks():
    n0 = len(FAILS)
    with tempfile.TemporaryDirectory() as td:
        clock = fresh(td)
        t0 = clock.t
        fid = "2ace753654b349a6a53edb5f8cdb3e69.16"
        g, sc = gym_run.Game(), FakeTapper()
        check(not gym_run.hold_on() and gym_run.e29_seen(g, sc, fid) is False, "no error on record: nothing to do, no hold")
        gym_run.autobattle(sc, g, False)
        check(g.ab_off is True and sc.calls[-1] == ("autobattle", False), "autobattle(off) is remembered on the Game")
        gym_run.autobattle(sc, g, True)
        check(g.ab_off is False and sc.calls[-1] == ("autobattle", True), "autobattle(on) clears it")

        gym_run.proven_add(["1", "2", "3", "4", "5", "6"])   # a first error 29, no jump, every member proven
        g.last_team = ["1", "2", "3", "4", "5", "6"]
        g.start_at = t0
        clock.t = t0 + 4
        g.err29_at = clock.t
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(ret is True and gym_run.E29["n"] == 1 and gym_run.E29["until"] == clock.t + 5.0 and gym_run.hold_on() and g.ab_off,
              f"a first error 29 with no jump: a 5 s hold, the tapper's Battle press off: {out!r}")
        check("not a cooldown" in out and "re-opening on the next map refresh (5 s)" in out, f"its line: {out!r}")
        check(said(gym_run.e29_seen, g, sc, fid)[1] is False and gym_run.E29["n"] == 1, "one error is handled ONCE")
        clock.t = t0 + 9.1
        check(not gym_run.hold_on(), "the hold ends by itself after 5 s")
        clock.t = t0 + 30                                    # a second one, 26 s after the first: as long again, 40 s at most
        g.err29_at = clock.t
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(gym_run.E29["n"] == 2 and gym_run.E29["until"] == clock.t + 26.0 and not gym_run.TEAM_BAN, f"2 in a row, all proven: wait as long again: {out!r}")
        clock.t = t0 + 100                                   # a third, 70 s after the second: 96 s since the first -> 40 s, the cap
        g.err29_at = clock.t
        said(gym_run.e29_seen, g, sc, fid)
        check(gym_run.E29["n"] == 3 and gym_run.E29["until"] == clock.t + 40.0,
              f"the error-29 wait never grows past 40 s (00:59: the doubling had reached 2 min 47 s): {gym_run.E29}")
        clock.t = t0 + 100 + gym_run.E29_ROW_S + 1           # one more, over 2 min after the last: not "in a row" -- a new first
        g.err29_at = clock.t
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(gym_run.E29_ROW_S == 120.0 and gym_run.E29["n"] == 1 and gym_run.E29["until"] == clock.t + 5.0 and "re-opening on the next map refresh (5 s)" in out,
              f"a refusal more than 2 min after the last one starts a new streak (5 s, no 40 s wait, no ban): {gym_run.E29} {out!r}")
        clock.t += gym_run.E29_ROW_S                         # exactly 2 min later still counts as in a row
        g.err29_at = clock.t
        said(gym_run.e29_seen, g, sc, fid)
        check(gym_run.E29["n"] == 2 and gym_run.E29["until"] == clock.t + 40.0, f"exactly 2 min apart is still in a row: {gym_run.E29}")
        said(gym_run.battles_count, fid, "a defender lost CP in our battle (100 -> 90 total)", sc)
        check(gym_run.E29["n"] == 0 and not gym_run.hold_on() and sc.calls[-1] == ("autobattle", True),
              f"a counted battle ends the streak and its hold, and gives the tapper its Battle press back: {sc.calls[-3:]}")

        clock = fresh(td, t0 + 1000)                         # the fused-Zekrom case: 2 in a row, an unproven member
        t1 = clock.t
        g, sc = gym_run.Game(), FakeTapper()
        gym_run.proven_add(["1", "2", "3", "4", "5"])
        g.last_team, g.names = ["1", "2", "12126051191352048111", "4", "5"], {"12126051191352048111": "Zekrom 3294"}
        g.err29_at = t1
        said(gym_run.e29_seen, g, sc, fid)
        check(not gym_run.TEAM_BAN, "ONE refused battle bans nobody")
        clock.t = t1 + 12
        g.err29_at = clock.t
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(list(gym_run.TEAM_BAN) == ["12126051191352048111"] and gym_run.E29["until"] == clock.t + 5.0 and "Zekrom 3294" in out
              and ("ban", ["12126051191352048111"]) in sc.calls,
              f"2 refused in a row with no jump: the never-proven member is out of every team, Battle again after 5 s: {out!r}")

        clock = fresh(td, t0 + 2000)                         # after a jump the server has not answered: a cooldown sign
        t2 = clock.t
        g, sc = gym_run.Game(), FakeTapper()
        said(gym_run.note_jump, 2194, (40.6897, -74.0453))
        clock.t = t2 + 39
        g.err29_at = clock.t
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(ret is True and "COOLDOWN sign #1" in out and gym_run.COOL["until"] == clock.t + 8.0 and gym_run.E29["n"] == 0 and g.ab_off,
              f"error 29 after an unanswered jump = the server's cooldown: re-ask after the 8 s guard: {out!r}")

        check([r["k"] for r in obs_rows()] == ["cooldown_refused"], f"that real refusal is the one row in cooldown_obs.jsonl: {obs_rows()}")
        g.last_team, g.names = ["1", "2", "777", "888"], {"777": "Zacian 5629", "888": "Rayquaza 4336"}   # nobody proven yet in this run
        for i in range(34):                                  # an ordinary cooldown: 35 refusals in a row at the 8 s re-ask
            clock.t += 8.5
            g.err29_at = clock.t
            out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(ret is True and gym_run.COOL["n"] == 35 and "COOLDOWN sign #35" in out, f"every refusal after the jump is a cooldown sign: {out!r}")
        check(not gym_run.TEAM_BAN and gym_run.E29["n"] == 0 and not [c for c in sc.calls if c[0] == "ban"],
              f"refusals after an unanswered jump NEVER ban a team member, however many (a cooldown refuses 8-35 battles in a row): {gym_run.TEAM_BAN}")

        clock = fresh(td, t0 + 2500)                         # how old an error 29 may be: the drill's longest single wait is 12 s
        t25 = clock.t
        g, sc = gym_run.Game(), FakeTapper()
        g.err29_at = t25
        clock.t = t25 + gym_run.E29_FRESH_S                  # exactly 15 s old: still this drill's
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(gym_run.E29_FRESH_S == 15.0 and ret is True and gym_run.hold_on(), f"an error 29 seen within 15 s is handled: {out!r}")
        clock = fresh(td, t0 + 2700)
        t27 = clock.t
        g, sc = gym_run.Game(), FakeTapper()
        g.err29_at = t27
        clock.t = t27 + gym_run.E29_FRESH_S + 0.1            # no round start, no jump since -- only its age
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(ret is False and not gym_run.hold_on() and gym_run.E29["n"] == 0 and sc.calls == [] and "not from this drill" in out,
              f"an error 29 older than 15 s was not shown to this drill (his own battle, or one that ended as the gym emptied): no hold: {out!r}")
        check(said(gym_run.e29_seen, g, sc, fid) == ("", False), "...and it is not looked at again")
        g.err29_at = clock.t                                 # 4 s old, but we jumped since: that jump's cooldown it is not
        clock.t += 2
        said(gym_run.note_jump, 163, (40.6899, -74.0455))
        clock.t += 2
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(ret is False and not gym_run.COOL["on"] and "a battle round started or we jumped since" in out,
              f"a 4 s old error 29 from BEFORE our last jump is not that jump's cooldown: {out!r}")
        g.err29_at = clock.t                                 # 3 s old, but a round started since
        clock.t += 1
        g.start_at = clock.t
        clock.t += 2
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(ret is False and not gym_run.hold_on() and "a battle round started or we jumped since" in out,
              f"a 3 s old error 29 that a round start has overtaken sets no hold: {out!r}")
        clock = fresh(td, t0 + 3000)                         # stale flags are history (the phantom holds of 00:25:29 / 00:30:09)
        t3 = clock.t
        rows_before = len(obs_rows())
        g, sc = gym_run.Game(), FakeTapper()
        g.err29_at = t3
        clock.t = t3 + 3
        g.start_at = clock.t                                 # the tapper re-opened and a new round started before the loop looked
        clock.t = t3 + 169
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(ret is False and not gym_run.hold_on() and gym_run.E29["n"] == 0 and gym_run.COOL["n"] == 0 and sc.calls == [] and "no hold" in out,
              f"an error 29 that a round start has overtaken sets no hold, 169 s later or ever: {out!r}")
        g.err29_at = clock.t
        clock.t += 20
        said(gym_run.note_jump, 163, (40.6899, -74.0455))    # we jumped away since
        clock.t += 5
        out, ret = said(gym_run.e29_seen, g, sc, fid)
        check(ret is False and not gym_run.COOL["on"] and not gym_run.hold_on(), f"an error 29 from before our last jump is not that jump's cooldown: {out!r}")
        check(len(obs_rows()) == rows_before, "a stale error 29 writes no fake refusal into cooldown_obs.jsonl (two rows of 11-16 were such phantoms)")
    go = gym_run.slip_go                                     # the slip-in: deploy only into the gap between the attacker's battles
    check(go([2, 800, 0, 3, 9000], 100.0, 0.0) == (True, "the server says NOT in battle (0.8 s old reading)"), f"a fresh NOT-in-battle reading = go: {go([2, 800, 0, 3, 9000], 100.0, 0.0)}")
    check(go([2, 800, 0, 3, 9000], 100.0, 99.0)[0] is False, "never two deploy requests within 2 s")
    check(go([2, 800, 0, 3, 9000], 100.0, 98.0)[0] is True, "2 s after the last request a NOT-in-battle reading goes again")
    check(go([2, 800, 1, 3, 9000], 100.0, 95.0) == (False, "the server says IN BATTLE"), "IN BATTLE = no deploy (it would be refused)")
    check(go([2, 800, 1, 3, 9000], 100.0, 90.0) == (True, "a blind try: the server still says IN BATTLE"), "one blind try every 10 s (the flag can lag)")
    check(go([2, 5000, 0, 3, 9000], 100.0, 95.0)[0] is False and go(None, 100.0, 95.0) == (False, "no fresh reading of the gym yet"),
          "a stale reading or none is not a go")
    check(go(None, 100.0, 0.0) == (True, "a blind try: no fresh reading of the gym"), "the very first try goes out at once")
    n_in_battle, last = 0, 0.0
    for t in range(60):                                      # the loop of force_join for one minute: a look every second
        if go([2, 500, 1, 3, 9000], 1000.0 + t, last)[0]:
            n_in_battle, last = n_in_battle + 1, 1000.0 + t
    check(n_in_battle == 6, f"a gym that reads IN BATTLE for a whole minute gets one deploy per 10 s (6), not one per second: {n_in_battle}")
    n_gap, last = 0, 0.0
    for t in range(60):                                      # ...and one whose attacker stops for 4 s every 20 s
        if go([2, 500, 0 if t % 20 in (12, 13, 14, 15) else 1, 3, 9000], 1000.0 + t, last)[0]:
            n_gap, last = n_gap + 1, 1000.0 + t
    check(n_gap >= 7, f"every gap between the attacker's battles gets a deploy in its first second (and a second one 2 s later): {n_gap}")
    if len(FAILS) == n0:
        print("ok: an error 29 is handled once and at once; a stale one sets no hold; two in a row put the unproven member out; the wait is capped at 40 s; "
              "the slip-in deploys into the gap, not every second")


def main():
    js = gym_tapper.JS
    real_time = gym_run.time
    try:
        if NODE is None:
            print("SKIP: node not found -- the tapper script text and its pick / ban code were NOT checked (CI has node)")
            if os.environ.get("CI"):
                FAILS.append("node not found in CI: the tapper script was not checked")
        else:
            script_text(js)
            free_names(js)
            pick_block(js)
            hold_block(js)
        jump_checks()
        suspect_checks()
        report_checks()
        dd_checks()
        misc_checks()
        stall_checks()
    finally:
        gym_run.time = real_time
    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED")
        return 1
    print("\nALL GYM AWARENESS CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
