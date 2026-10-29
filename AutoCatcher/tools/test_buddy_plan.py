"""Offline checks of the careful buddy rotation (no phone): every decision buddy_run.plan() makes from the game's own data, and
buddy_tapper's walk from the live PlayerService to the player record (the real JS under node, mock il2cpp objects).
Run: python test_buddy_plan.py"""
import os
import re
import subprocess
import sys
import tempfile
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
print(f"ok: {n} rotation decisions + cycle/room + dry-run checks passed")

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
function C(name) { var k = {name: name, equals: function (x) { return x === k; }}; return k; }
var TYPES = {PlayerService: [['info', 0x12, 16], ['self', 0x12, 32], ['vt', 0x15, 40, 'VT'], ['list', 0x15, 48, 'REF']],
             PlayerInfo: [['proto', 0x12, 24], ['n', 0x08, 8]], Deep: [['a', 0x12, 8]], ClientPlayerProto: []};
function fieldsOf(k) { return (TYPES[k.name] || []).map(function (x) { return {name: x[0], te: x[1], off: x[2], t: x[3] || null}; }); }
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
console.log('ok: 8 player-record walk checks passed');
"""
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(MOCK + js_fn("klassOf") + js_fn("isA") + js_fn("findCpp") + js_fn("follow") + TESTS)
try:
    r = subprocess.run(["node", f.name], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    sys.exit(r.returncode)
finally:
    os.unlink(f.name)
