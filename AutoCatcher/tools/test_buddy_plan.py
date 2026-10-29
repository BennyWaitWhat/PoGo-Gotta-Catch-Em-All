"""Offline checks of the careful buddy rotation (no phone): every decision buddy_run.plan() makes from the game's own data, and
buddy_tapper's walk from the live PlayerService to the player record (the real JS under node, mock il2cpp objects).
Run: python test_buddy_plan.py"""
import os
import re
import subprocess
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buddy_run as br  # noqa: E402
import buddy_tapper as bt  # noqa: E402

A = types.SimpleNamespace(every=3, idle=60, feed=False)
E, J, F, G, SNOM = "11", "22", "33", "44", "99"                  # rotation ids, closest to Best first; SNOM = not in the rotation
D = "2026-10-29"


def P(buddy, pts, play=0, walk=0, treat=0, full_until=0):        # what peek() returns: the game's own today-map
    return {"buddyId": buddy, "pts": pts, "fullUntil": full_until,
            "today": {"cats": {"2": [1] * play + [0] * (1 - play), "4": [1] * walk + [0] * (3 - walk), "1": [1] * treat + [0] * (3 - treat)}}}


def ST(**kw):
    st = {"rot": [E, J, F, G], "hist": {E: 290, J: 280, F: 250, G: 3}, "ours": None, "at_set": {}, "gain_at": 0, "played": {},
          "capped": {}, "swaps": {}, "hands_off": False, "first": None, "day": D}
    st.update(kw)
    return st


def check(st, p, now, want, label, a=A):
    got = br.plan(st, p, a, now, D)[:2]
    assert got == want, f"{label}: got {got}, want {want}"


n = 0
def ok(*args, **kw):
    global n
    check(*args, **kw)
    n += 1


ok(ST(), P(SNOM, 10), 0, ("set", E), "start-up on another buddy: the one closest to Best")
st = ST()
ok(st, P(J, 280), 0, ("pet", None), "start-up on a rotation Eevee: adopted, today's play heart first")
assert st["ours"] == J and st["at_set"][J] == 280
st["played"][J] = D
ok(st, P(J, 281, play=1), 10, ("wait", None), "played, nothing else yet: wait")
ok(st, P(J, 283, play=1), 20, ("set", F), "3 hearts since set: the next in order")
st = ST(ours=J, at_set={J: 281}, played={J: D}, gain_at=0)
ok(st, P(J, 282, play=1, walk=3), 10, ("set", F), "no play or walk heart left today: move on")
assert st["capped"][J] == D
st = ST(ours=J, at_set={J: 281}, played={J: D}, gain_at=0)
ok(st, P(J, 281, play=1), 3600, ("set", F), "an hour without a heart while others still have today's play heart")
st = ST(ours=J, at_set={J: 281}, played={E: D, J: D, F: D, G: D}, gain_at=0)
ok(st, P(J, 281, play=1), 3600, ("wait", None), "an hour idle but every other Eevee already played: stay, no switch churn")
st = ST(ours=J, at_set={J: 281}, played={J: D}, capped={F: D}, gain_at=0)
ok(st, P(J, 284, play=1), 10, ("set", G), "a capped Eevee is skipped in the cycle")
st = ST(ours=G, at_set={G: 3}, played={G: D}, capped={E: D, J: D, F: D}, gain_at=0)
ok(st, P(G, 6, play=1), 10, ("wait", None), "3 hearts, but nobody else has anything left today: stay")
st = ST(ours=J, at_set={J: 281}, played={J: D})
ok(st, P(SNOM, 10), 10, ("wait", None), "he picked another buddy himself: hands off")
assert st["hands_off"]
ok(st, P(SNOM, 11), 20, ("wait", None), "still hands off")
ok(st, P(J, 281, play=1), 30, ("wait", None), "he set the rotation Eevee back: adopted (one tick to say so)")
assert not st["hands_off"] and st["ours"] == J
ok(st, P(J, 284, play=1), 40, ("set", F), "and the rotation goes on")
st = ST(ours=J, at_set={J: 281}, played={J: D})
ok(st, P(F, 250), 10, ("wait", None), "he set another Eevee from the list: adopted")
ok(st, P(F, 250), 20, ("pet", None), "then cared for like any rotation buddy")
st = ST(ours=E, at_set={E: 299}, played={E: D}, hist={E: 299, J: 280, F: 250, G: 3})
ok(st, P(E, 300, play=1), 10, ("set", J), "Best Buddy reached: out of the rotation, the next closest")
st = ST(ours=E, hist={E: 300, J: 300, F: 301, G: 300})
ok(st, P(E, 300, play=1), 10, ("done", None), "every Eevee is Best Buddy: done")
st = ST(first=(SNOM, 10))
ok(st, P(E, 290), 0, ("set", SNOM), "the quest target first")
st["ours"] = SNOM
ok(st, P(SNOM, 9), 10, ("pet", None), "the quest target gets its play heart")
st["played"][SNOM] = D
ok(st, P(SNOM, 9, play=1), 20, ("wait", None), "the quest target stays until its target")
ok(st, P(SNOM, 10, play=1), 30, ("wait", None), "target reached: DONE, the rotation starts")
assert st["first"] is None
ok(st, P(SNOM, 10, play=1), 40, ("set", E), "the rotation starts with the one closest to Best")
st = ST(ours=J, at_set={J: 270}, played={J: D}, day="2026-10-28")
ok(st, P(J, 283, play=1), 10, ("wait", None), "a new day: the hearts-since-set count starts again (no switch at midnight)")
assert st["at_set"] == {J: 283}
fa = types.SimpleNamespace(every=3, idle=60, feed=True)
st = ST(ours=J, at_set={J: 281}, played={J: D})
ok(st, P(J, 281, play=1), 10, ("feed", None), "--feed: a treat while the treat cap has room and it is not full", a=fa)
ok(st, P(J, 281, play=1, full_until=10 ** 15), 10, ("wait", None), "--feed: not while it is full", a=fa)
st = ST(ours=J, at_set={J: 281}, played={J: D})
ok(st, P(J, 282, play=1, walk=3), 10, ("feed", None), "--feed: treats count as room, so walk 3/3 alone is not 'capped'", a=fa)
assert br.next_in_cycle([E, J, F, G], G, [E, J]) == E and br.next_in_cycle([E, J, F, G], SNOM, [F]) == F
assert br.room(P(J, 0, play=1, walk=2), False) == 1 and br.room(P(J, 0, play=1, walk=3, treat=1), True) == 2


class FakeT:                                                     # --dry must not act, even with no history in memory
    hist, scan, acts = {}, False, []
    def peek(self):
        return {"name": "BennyValentinC", "buddyId": SNOM, "pts": 10, "today": {"cats": {}}}
    def act(self, what, arg=None):
        self.acts.append(what)


br.bag = lambda: ({E: "Espeon 1", J: "Jolteon 2"}, [E, J])
br.say = lambda msg: None
fake = FakeT()
br.loop(types.SimpleNamespace(dry=True, first=None, every=3, idle=60, feed=False, trainer="BennyValentinC", cmd=None), fake)
assert fake.acts == [], f"--dry acted: {fake.acts}"
n += 1


class FakeExports:                                               # Tapper.act's end of a wait: no frame vs in flight vs a late reply
    def __init__(self, inflight=False, late=None):
        self.inflight, self.late = inflight, late
    def act(self, what, arg):
        return 1
    def cancel(self):
        if self.late:
            self.late()
        return not self.inflight
    def idle(self):
        return True


def tapper(ex):
    t = object.__new__(br.Tapper)
    t.sess, t.last, t.detached, t.scan, t.bg = None, {}, False, False, False
    t.sc = types.SimpleNamespace(exports_sync=ex)
    return t


t = tapper(FakeExports())
assert t.act("pet", timeout=0.3) == {"noframe": True} and t.bg, "no game frame: nothing was sent, not a failure"
t = tapper(FakeExports(inflight=True))
assert t.act("pet", timeout=0.3) is None, "sent but never answered: a failure"
t = tapper(None)
t.sc = types.SimpleNamespace(exports_sync=FakeExports(late=lambda: t.last.__setitem__("pet", (time.time(), {"res": 1}))))
assert t.act("pet", timeout=0.3) == {"res": 1} and not t.bg, "a reply that lands at the timeout is the reply"
n += 3


class Done(Exception):
    pass


class LoopT:                                                     # the loop with scripted reads and action replies
    hist, scan, bg = {E: [290, 0, 0], J: [280, 0, 0]}, False, False
    def __init__(self, peeks, acts):
        self.peeks, self.acts, self.calls = list(peeks), acts, []
    def peek(self):
        if not self.peeks:
            raise Done
        return dict(self.peeks.pop(0), name="BennyValentinC")
    def act(self, what, arg=None):
        self.calls.append(what)
        self.bg = bool(self.acts.get(what, {}).get("noframe"))
        return self.acts.get(what, {})
    def unhook(self):
        pass


said, real_sleep = [], br.time.sleep
br.say, br.time.sleep = said.append, lambda s: None


def run_loop(peeks, acts, feed=False):
    T = LoopT(peeks, acts)
    try:
        br.loop(types.SimpleNamespace(dry=False, first=None, every=3, idle=60, feed=feed, reserve=0, max_swaps=10, tick=0,
                                      trainer="BennyValentinC", cmd=None), T)
    except Done:
        pass
    return T


NF = {"noframe": True}
T = run_loop([P(J, 280), P(J, 280)], {"pet": NF})
assert T.calls == ["pet"] and any("not in front" in s for s in said), "play with PoGo in the background: no stop, said once"
T = run_loop([P(SNOM, 10), P(SNOM, 10)], {"set": NF})
assert T.calls == ["set"], "a switch with PoGo in the background: no stop"
T = run_loop([P(J, 281, play=1), P(J, 281, play=1)], {"count": NF}, feed=True)
assert T.calls == ["count"], "a treat with PoGo in the background: no stop, treats stay on"
try:
    run_loop([P(J, 280), P(J, 280)], {"pet": {"err": "x"}})
    raise AssertionError("a refused play must stop the run")
except br.Stop:
    pass
br.time.sleep = real_sleep
said.clear()
T = LoopT([P(J, 295)], {})
T.hist = {E: [290, 0, 0]}                                        # the current buddy is not in the game's history list
br.loop(types.SimpleNamespace(dry=True, first=None, every=3, idle=60, feed=False, trainer="BennyValentinC", cmd=None), T)
rows = [s for s in said if "hearts (" in s]
assert "Jolteon" in rows[0] and "295" in rows[0], f"the buddy's live count sets its place in the order: {rows}"
now = time.time()
utc_day, local_day = int(now // 86400), int((now + time.localtime(now).tm_gmtoff) // 86400)
assert br.swaps_today({"swapsWindow": utc_day, "swapsCount": 13}, now) == 13
assert br.swaps_today({"swapsWindow": local_day, "swapsCount": 13}, now) == 13, "a local-day window still counts"
assert br.swaps_today({"swapsWindow": utc_day - 2, "swapsCount": 13}, now) == 0, "an old window is not today"


class NoActT:
    def act(self, what, arg=None):
        raise AssertionError("a switch past the day's budget must not reach the game")


st = ST(ours=J)
assert br.switch(types.SimpleNamespace(max_swaps=10), NoActT(), st, dict(P(J, 281), swapsWindow=local_day, swapsCount=13), F,
                 "test", {}, now, D) is False, "his 13 switches today hold the runner at its 10"
n += 9
print(f"ok: {n} rotation decisions + cycle/room + dry-run + background checks passed")

# ---- buddy_tapper's walk to the player record (findCpp / follow / isA), the real JS under node ----
def js_fn(name):
    i = bt.JS.index("function " + name + "(")
    line_end = bt.JS.index("\n", i)
    line = bt.JS[i:line_end]
    if line.count("{") and line.count("{") == line.count("}"):
        return line + "\n"
    return bt.JS[i:bt.JS.index("\n}\n", i) + 3]


MOCK = r"""
var NULLP = {isNull: function () { return true; }, toString: function () { return '0x0'; }};
var REG = {};
function O(id, klass, fields) {                 /* a mock object: readPointer() = its klass, add(off).readPointer() = a field */
  var o = {fields: fields || {}, isNull: function () { return false; }, toString: function () { return id; },
    readPointer: function () { return klass; }, add: function (off) { return {readPointer: function () { return o.fields[off] || NULLP; }}; }};
  REG[id] = o; return o;
}
function ptr(s) { return REG[s]; }
function C(name) { var k = {name: name, equals: function (x) { return x === k; },   /* Il2CppClass: name@0x10 */
  add: function (off) { return {readPointer: function () { return {readCString: function () { return name; }}; }}; }}; return k; }
var TYPES = {PlayerService: [['info', 0x12, 16], ['self', 0x12, 32], ['vt', 0x15, 40, 'VT'], ['list', 0x15, 48, 'REF']],
             PlayerInfo: [['proto', 0x12, 24], ['n', 0x08, 8]], Deep: [['a', 0x12, 8]], ClientPlayerProto: []};
var CALLED = [];                                /* every class handed to il2cpp's field enumeration */
function fieldsOf(k) { CALLED.push(k.name); return (TYPES[k.name] || []).map(function (x) { return {name: x[0], te: x[1], off: x[2], t: x[3] || null}; }); }
var IL = {isValueType: function (c) { return c === 'VT'; }, classFromType: function (t) { return t; }};
var KPS = C('PlayerService'), KPI = C('PlayerInfo'), KD = C('Deep'), K = {cpp: C('ClientPlayerProto')}, GRAPH = null;
function ok(c, m) { if (!c) { console.log('FAIL: ' + m); process.exit(1); } }
"""
TESTS = r"""
var cpp1 = O('cpp1', K.cpp), pi = O('pi', KPI, {24: cpp1}), ps = O('ps', KPS, {16: pi});
ps.fields[32] = ps;                                              /* a cycle back to itself */
var path = findCpp(ps, 3);
ok(JSON.stringify(path) === '[16,24]', 'the path PlayerService -> PlayerInfo -> ClientPlayerProto: ' + JSON.stringify(path));
GRAPH = {player: 'ps'};
ok(follow(path) === cpp1, 'follow() reaches the player record');
var cpp2 = O('cpp2', K.cpp); pi.fields[24] = cpp2;
ok(follow(path) === cpp2, 'the game replaced the record: follow() re-walks the path and finds the new one');
pi.fields[24] = O('junk', KD); ok(follow(path) === null, 'something else at the end of the path: null, never a misread');
pi.fields[24] = undefined; ok(follow(path) === null, 'a null on the way: null');
var ps2 = O('ps2', KPS, {40: O('cppvt', K.cpp)});
ok(findCpp(ps2, 3) === null, 'a value-type field is never followed as a pointer');
var d3 = O('d3', KD, {8: O('cppdeep', K.cpp)}), d2 = O('d2', KD, {8: d3}), d1 = O('d1', KD, {8: d2}), ps3 = O('ps3', KPS, {16: d1});
ok(findCpp(ps3, 3) === null && JSON.stringify(findCpp(ps3, 4)) === '[16,8,8,8]', 'the depth limit holds');
ok(isA(cpp1, K.cpp) && !isA(pi, K.cpp) && !isA(NULLP, K.cpp), 'isA');
var ps5 = O('ps5', KPS, {16: O('notobj', C('\u0001\u0007'))}); CALLED.length = 0;
ok(findCpp(ps5, 3) === null && CALLED.indexOf('\u0001\u0007') < 0, 'memory that is not an object never reaches il2cpp');
console.log('ok: 9 player-record walk checks passed');
"""
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(MOCK + js_fn("jsClass") + js_fn("klassOf") + js_fn("isA") + js_fn("findCpp") + js_fn("follow") + TESTS)
try:
    r = subprocess.run(["node", f.name], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    sys.exit(r.returncode)
finally:
    os.unlink(f.name)
