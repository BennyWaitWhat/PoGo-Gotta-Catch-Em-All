"""Offline check of the gym tapper's same-type attack bonus (STAB) and of its script text (2026-09-30, Benny: "fix it").
No phone, no Frida: the REAL code between the ">>> STAB" and "<<< STAB" markers of gym_tapper.JS runs under node against mock
il2cpp objects (a typed memory: a read of the wrong width throws like Frida's access violation), the runner's new report lines
run against a fake tapper, and the typing table is built from a small synthetic game master (plus the real one when it is here).
Run: python test_gym_stab.py      (needs node; frida is not needed -- a stub stands in when it is not installed)

  1. the whole tapper script text passes `node --check`, and declares no top-level name twice (`node --check` lets a second
     `var X` silently replace the first: a duplicate WATCH killed the feeder for 3 minutes once);
  2. the STAB block: the field-offset resolution against the REAL PokemonSettingsProto recon (the old matcher could not find type1_),
     the live read (validated by species), the game master table fallback, every refusal, the multiplier, the pick that changes;
  3. stab_config(): the typing table from a synthetic game master, and from the real one when present;
  4. gym_run's report lines: stab_tag() and stab_setup() with a fake tapper.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

try:
    import frida  # noqa: F401
except ImportError:                                          # CI / the offline sandbox: nothing here ever attaches
    sys.modules["frida"] = types.ModuleType("frida")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gym_tapper  # noqa: E402

NODE = shutil.which("node")
FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL:", msg)
    return cond


def block(js):
    a, b = js.index("/* >>> STAB"), js.index("/* <<< STAB */")
    check(js.count("/* >>> STAB") == 1 and js.count("/* <<< STAB */") == 1, "the STAB markers appear exactly once in the tapper script")
    for fn in ("rank", "settingsFields", "typeIds", "liveMult", "loadStab", "resolveStab", "resolveLiveMult", "stabReport", "setOffs", "dispOffs",
               "fightingSix", "attackerTypes", "moveScore", "attack"):
        check(f"function {fn}(" in js[a:b], f"function {fn}() fell out of the marked STAB block (the markers must still cover it)")
    return js[a:b]


# ------------------------------------------------------------------------------------------------ 1. the script text
def script_text(js):
    check("/^type_?$/i" not in js, "the old first-type matcher (type / type_ only) is back in the script")
    check("O.cadSettings" not in js, "a stale O.cadSettings reference is back in the script")
    check("stab: function (cfg)" in js and "stab: stabReport()" in js, "the stab() export / the install stab report are missing")
    check("    resolveStab();" in js and "    resolveLiveMult();" in js, "install() no longer calls resolveStab() / resolveLiveMult()")
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "tapper.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run([NODE, "--check", p], capture_output=True, text=True)
        check(r.returncode == 0, "node --check of the whole tapper script failed: " + (r.stderr or r.stdout).strip()[:600])
        dup = r"""
const fs = require('fs'); let acorn;
try { acorn = require('internal/deps/acorn/acorn/dist/acorn'); } catch (e) { console.log('SKIP'); process.exit(0); }
const ast = acorn.parse(fs.readFileSync(process.argv[2], 'utf8'), {ecmaVersion: 2020});
const seen = {}, dups = [];
const add = (n) => { if (seen[n]) dups.push(n); seen[n] = 1; };
for (const s of ast.body) {
  if (s.type === 'FunctionDeclaration') add(s.id.name);
  else if (s.type === 'VariableDeclaration') for (const d of s.declarations) if (d.id.type === 'Identifier') add(d.id.name);
}
console.log(dups.length ? 'DUP ' + dups.join(',') : 'OK ' + Object.keys(seen).length);
"""
        q = os.path.join(td, "dup.js")
        with open(q, "w", encoding="utf-8") as f:
            f.write(dup)
        r = subprocess.run([NODE, "--expose-internals", q, p], capture_output=True, text=True)
        out = (r.stdout or "").strip()
        if out.startswith("OK"):
            print(f"ok: tapper script passes node --check; {out[3:]} top-level names, none declared twice")
        elif out == "SKIP" or r.returncode != 0:
            print("ok: tapper script passes node --check (top-level duplicate scan skipped: this node has no internal parser)")
        else:
            check(False, "top-level names declared twice in the tapper script: " + out)


# ------------------------------------------------------------------------------------------------ 2. the STAB block
MOCK = r"""
var N = 0, MEM = {}, STRS = {}, KL = {}, NEXT = 0x100000, SENT = [], CALLS = [], NOW = 1000;
function ok(c, m) { if (!c) { console.log('FAIL: ' + m); process.exit(1); } N++; }
function near(a, b, m) { ok(Math.abs(a - b) < 1e-6, m + ' (got ' + a + ', want ' + b + ')'); }
function Ptr(a) { this.a = a; }
Ptr.prototype.add = function (n) { return new Ptr(this.a + n); };
Ptr.prototype.isNull = function () { return this.a === 0; };
Ptr.prototype.equals = function (o) { return !!o && this.a === o.a; };
Ptr.prototype.toString = function () { return '0x' + this.a.toString(16); };
function rd(p, t) { var c = MEM[p.a]; if (!c || c.t !== t) throw new Error('access violation: ' + t + ' read at ' + p); return c.v; }
Ptr.prototype.readPointer = function () { return new Ptr(rd(this, 'p')); };
Ptr.prototype.readS32 = function () { return rd(this, 'i'); };
Ptr.prototype.readFloat = function () { return rd(this, 'f'); };
Ptr.prototype.readU8 = function () { return rd(this, 'b'); };
var NULL = new Ptr(0);
function alloc(n) { var p = new Ptr(NEXT); NEXT += (n || 0x400); return p; }
function put(p, off, t, v) { MEM[p.a + off] = {t: t, v: t === 'p' ? (v ? v.a : 0) : v}; }
function klass(name) { var k = alloc(32); KL[k.a] = name; return k; }
function obj(k, fields) { var p = alloc(); put(p, 0, 'p', k); Object.keys(fields || {}).forEach(function (off) { put(p, +off, fields[off][0], fields[off][1]); }); return p; }
function sobj(text) { var p = alloc(32); STRS[p.a] = text; return p; }
/* ---- the tapper globals the block uses ---- */
function klassOf(o) { return o.readPointer(); }
function nameOf(k) { return KL[k.a] || ''; }
function isA(o, k) { try { return !!k && !o.isNull() && o.readPointer().equals(k); } catch (e) { return false; } }
function str(p) { return p.isNull() ? null : (STRS[p.a] === undefined ? null : STRS[p.a]); }
function send(m) { SENT.push(m); }
var BATTLE_ACTIVE = true;
function callB(m, o, w) { return BATTLE_ACTIVE; }
function call(m, o, w) { CALLS.push({m: m, o: o, w: w}); return {}; }
function methodOn() { return 1; }
var FIELDS = {}, CLASSES = {}, HIDE = {}, ENUMS = {}, INSTANCES = {}, INSTANCES_THROW = false;
function fieldsOf(k) { return FIELDS[KL[k.a]] || []; }
function fieldBy(k, pred) { var r = -1; fieldsOf(k).forEach(function (x) { if (r < 0 && pred(x.name, x.tn)) r = x.off; }); return r; }
function byName(ns, name) { return HIDE[name] ? null : (CLASSES[name] || null); }
function enumLits(k) { return ENUMS[KL[k.a]] || {}; }
function instances(k, n) { if (INSTANCES_THROW) throw new Error('liveness walk failed'); return (INSTANCES[KL[k.a]] || []).slice(0, n); }
function protoOffs() { return {pokemonId: 40, move2: 60, move3: 276, pokemonDisplay: 216}; }
var PROTOS = {}, LIVEPROTO_CALLS = 0, LIVEPROTO_THROWS = false;
function liveProto(id) { LIVEPROTO_CALLS++; if (LIVEPROTO_THROWS) throw new Error('bag gone'); return PROTOS[id] || null; }
var ACTIVE = {}, ACTIVE_AT = 0, ROUND = true, GBS = null;
var ST = {last: 0, fast: 0, charged: 0, lastSent: 0, textOff: 16, nch: 0, moveKey: null};
var K = {}, M = {fast: 1, active: 1, tapCharge: 1}, O = {};
['PokemonSettingsProto', 'TempEvoPokemonSettings', 'PokemonProto', 'PokemonDisplayProto', 'MoveSettingsProto', 'ChargeAttackDisplay', 'Text',
 'BattleFrameObservableService', 'BattleGestureHandler', 'GymBattleState', 'HoloPokemonType', 'GymBattleSettingsProto'].forEach(function (n) { CLASSES[n] = klass(n); });
K.PokemonSettings = CLASSES.PokemonSettingsProto; K.svc = CLASSES.BattleFrameObservableService; K.ChargeAttackDisplay = CLASSES.ChargeAttackDisplay;
FIELDS.PokemonDisplayProto = [{name: 'Costume', off: 16, tn: 'Holoholo.Rpc.PokemonDisplayProto.Types.Costume'}, {name: 'Shiny', off: 24, tn: 'System.Boolean'},
  {name: 'Form', off: 28, tn: 'Holoholo.Rpc.PokemonDisplayProto.Types.Form'}, {name: 'CurrentTempEvolution', off: 44, tn: 'Holoholo.Rpc.HoloTemporaryEvolutionId'}];
/* the live enum values (HoloPokemonType: NORMAL 1 ... FAIRY 18) */
var TY = {NORMAL: 1, FIGHTING: 2, FLYING: 3, POISON: 4, GROUND: 5, ROCK: 6, BUG: 7, GHOST: 8, STEEL: 9, FIRE: 10, WATER: 11, GRASS: 12, ELECTRIC: 13,
          PSYCHIC: 14, ICE: 15, DRAGON: 16, DARK: 17, FAIRY: 18};
var LITS = {PokemonTypeNone: 0}; Object.keys(TY).forEach(function (n) { LITS['PokemonType' + n.charAt(0) + n.slice(1).toLowerCase()] = TY[n]; });
/* the live offsets (made up, except the PokemonSettingsProto ones: uniqueId_ @16, type1_ @24, type2_ @28 from the recon) */
function freshO() {
  return {cadMove: 96, cadCharged: 440, cadEff: 104, cadSet: [112, 120], mvPower: 32, mvEnergy: 36, mvType: 40, mvId: 44, mvTypeOk: true,
    gbsSvc: 48, gbsGh: 56, ghDisplays: 64, setT1: 24, setT2: 28, setId: 16, cadRelated: []};
}
/* ---- builders ---- */
function mkMove(power, energy, type, id) { return obj(CLASSES.MoveSettingsProto, {32: ['f', power], 36: ['i', -energy], 40: ['i', type], 44: ['i', id]}); }
function mkSettings(dex, t1, t2, cls) { return obj(CLASSES[cls || 'PokemonSettingsProto'], {16: ['i', dex], 24: ['i', t1], 28: ['i', t2]}); }
function mkDisplay(o) {                       /* {move: [power, energy, type, id] | null, charged, eff, sets: [settings objects]} */
  var f = {}, sets = o.sets || [];
  f[96] = ['p', o.move ? mkMove.apply(null, o.move) : NULL]; f[440] = ['b', o.charged ? 1 : 0];
  f[104] = ['p', obj(CLASSES.Text, {16: ['p', sobj(o.eff || '')]})];
  for (var i = 0; i < 2; i++) f[112 + 8 * i] = ['p', sets[i] || NULL];
  return obj(CLASSES.ChargeAttackDisplay, f);
}
function mkProto(id, dex, form, mega, m2, m3) {
  var disp = obj(CLASSES.PokemonDisplayProto, {28: ['i', form], 44: ['i', mega ? 1 : 0]});
  PROTOS[id] = obj(CLASSES.PokemonProto, {40: ['i', dex], 60: ['i', m2], 276: ['i', m3 || 0], 216: ['p', disp]});
}
function team(list) {                         /* [[id, dex, form, mega, move2, move3], ...] = our fighting six */
  ACTIVE = {}; PROTOS = {}; ACTIVE_AT++; LIVEPROTO_THROWS = false;
  list.forEach(function (t) { ACTIVE[t[0]] = 1; mkProto.apply(null, t); });
}
function tick(displays) {                     /* one attack tick on these buttons -> {moves, infos, charged: the display that fired, fast} */
  var svc = obj(K.svc, {}), arr = alloc(256);
  put(arr, 0x18, 'i', displays.length); displays.forEach(function (d, i) { put(arr, 0x20 + 8 * i, 'p', d); });
  GBS = obj(CLASSES.GymBattleState, {48: ['p', svc], 56: ['p', obj(CLASSES.BattleGestureHandler, {64: ['p', arr]})]});
  SENT = []; CALLS = []; ST.moveKey = null; ST.last = 0; NOW += 200; attack(NOW);
  var ch = CALLS.filter(function (c) { return c.w === 'chargedAttack'; })[0];
  return {moves: SENT.filter(function (m) { return m.k === 'moves'; })[0], infos: SENT.filter(function (m) { return m.k === 'info'; }),
          charged: ch ? displays.map(function (d) { return d.a; }).indexOf(ch.o.a) : -1, fast: CALLS.some(function (c) { return c.w === 'fastAttack'; })};
}
/* the game master typing table the runner would hand over (only what these tests need) */
var TABLE = {'150': ['PSYCHIC'], '484': ['WATER', 'DRAGON'], '68': ['FIGHTING'], '130': ['WATER', 'FLYING'], '486': ['NORMAL'], '143': ['NORMAL'],
             '26': ['ELECTRIC'], '26:50': ['ELECTRIC', 'PSYCHIC'], '646': ['DRAGON', 'ICE']};
/* real moves (power / energy / type / id from the game master) */
var AQUA = [50, 33, TY.WATER, 58], DRACO = [150, 100, TY.DRAGON, 285], PSYSTRIKE = [95, 50, TY.PSYCHIC, 109], SHADOW = [100, 50, TY.GHOST, 70],
    HYDRO = [135, 100, TY.WATER, 107], RETURN = [25, 33, TY.NORMAL, 323], PSYCHIC_ = [95, 50, TY.PSYCHIC, 108], CROSS = [50, 50, TY.FIGHTING, 28],
    DYNAMIC = [85, 50, TY.FIGHTING, 246];
function resetAll() {
  O = freshO(); TYPE_ID = typeIds(LITS); SETOFF = {}; DISP = null; STAB.told = {}; STAB.live = null; STAB.gm = null; STAB.mult = 1.2; STAB.multSrc = 'default';
  K.PokemonSettings = CLASSES.PokemonSettingsProto; HIDE = {}; STAB.err = null;
  STAB.snap = {key: '', at: 0, list: []}; loadStab({mult: 1.2, types: TABLE});
}
"""

TESTS = r"""
/* ---- field offsets, against the REAL PokemonSettingsProto recon (pogo_extract/_recon_evolve_out.json, instance fields only) ---- */
var RECON = [{name: 'uniqueId_', off: 16, tn: 'Holoholo.Rpc.HoloPokemonId'}, {name: 'modelScale_', off: 20, tn: 'System.Single'},
  {name: 'type1_', off: 24, tn: 'Holoholo.Rpc.HoloPokemonType'}, {name: 'type2_', off: 28, tn: 'Holoholo.Rpc.HoloPokemonType'},
  {name: 'camera_', off: 32, tn: 'Holoholo.Rpc.PokemonCameraAttributesProto'}, {name: 'pokemonClass_', off: 92, tn: 'Holoholo.Rpc.HoloPokemonClass'},
  {name: 'parentId_', off: 104, tn: 'Holoholo.Rpc.HoloPokemonId'}, {name: 'familyId_', off: 120, tn: 'Holoholo.Rpc.HoloPokemonFamilyId'},
  {name: 'form_', off: 156, tn: 'Holoholo.Rpc.PokemonDisplayProto.Types.Form'}, {name: 'parentForm_', off: 200, tn: 'Holoholo.Rpc.PokemonDisplayProto.Types.Form'}];
ok(!/^type_?$/i.test('type1_') && /^type2_?$/i.test('type2_'), 'the OLD matcher finds type2_ but cannot find type1_ (the bug: setT1 stayed -1)');
var sf = settingsFields(RECON);
ok(sf.t1 === 24 && sf.t2 === 28 && sf.id === 16, 'the recon resolves type1_ @24, type2_ @28, uniqueId_ @16 (got ' + JSON.stringify(sf) + ')');
sf = settingsFields(RECON.map(function (x) { return {name: x.name.replace('type1_', 'type_'), off: x.off, tn: x.tn}; }));
ok(sf.t1 === 24 && sf.t2 === 28, 'type_ / type2_ also resolve');
['type', 'type_', 'type1', 'type1_', 'Type1_', 'TYPE1'].forEach(function (nm) {   /* a third type-typed field: the order fallback cannot apply, the NAME has to */
  var f = [{name: nm, off: 24, tn: 'Holoholo.Rpc.HoloPokemonType'}, {name: 'type2_', off: 28, tn: 'Holoholo.Rpc.HoloPokemonType'},
           {name: 'typeOverride_', off: 300, tn: 'Holoholo.Rpc.HoloPokemonType'}];
  ok(settingsFields(f).t1 === 24 && settingsFields(f).t2 === 28, 'the first type field named ' + nm + ' resolves by name');
});
sf = settingsFields(RECON.map(function (x) { return {name: x.name.replace(/^type[12]_$/, function (m) { return 'zz' + m; }), off: x.off, tn: x.tn}; }));
ok(sf.t1 === 24 && sf.t2 === 28, 'two renamed type fields resolve by declared type and declaration order');
sf = settingsFields(RECON.concat([{name: 'mystery', off: 300, tn: 'Holoholo.Rpc.HoloPokemonType'}]).map(function (x) { return {name: x.name.replace(/^type[12]_$/, function (m) { return 'zz' + m; }), off: x.off, tn: x.tn}; }));
ok(sf.t1 === -1 && sf.t2 === -1, 'three type fields with no recognisable names stay unresolved (-1), never guessed');
sf = settingsFields([{name: 'whatever', off: 40, tn: 'System.Int32'}]);
ok(sf.t1 === -1 && sf.t2 === -1 && sf.id === -1, 'a class with none of the fields resolves nothing');
var ids = typeIds(LITS);
ok(ids.WATER === 11 && ids.PSYCHIC === 14 && ids.FAIRY === 18 && ids.NONE === undefined && Object.keys(ids).length === 18, 'typeIds: 18 live enum names, NONE dropped');
near(liveMult([1.2000000476837158]), 1.2, 'liveMult reads the float32 1.2');
ok(liveMult([]) === null && liveMult([0, 0]) === null && liveMult([1.2, 1.5]) === null && liveMult([5]) === null, 'liveMult: no reading, junk, disagreement and an insane value all give null');
near(liveMult([0, 1.2, 1.2]), 1.2, 'liveMult ignores a zeroed default instance when the others agree');

/* ---- install(): resolveStab() / resolveLiveMult() on realistic field lists (the glue that only ever ran on the phone) ---- */
FIELDS.ChargeAttackDisplay = [{name: 'moveSettings', off: 96, tn: 'Holoholo.Rpc.MoveSettingsProto'}, {name: 'attackerSettings', off: 112, tn: 'Holoholo.Rpc.IPokemonSettings'},
  {name: 'defenderSettings', off: 120, tn: 'Holoholo.Rpc.IPokemonSettings'}, {name: 'owner', off: 128, tn: 'Holoholo.Rpc.PokemonProto'},
  {name: 'label', off: 136, tn: 'UnityEngine.UI.Text'}, {name: 'all', off: 144, tn: 'System.Collections.Generic.List<Holoholo.Rpc.PokemonProto>'}];
FIELDS.PokemonSettingsProto = RECON; ENUMS.HoloPokemonType = LITS;
O = {}; TYPE_ID = {}; K.PokemonSettings = null; STAB.err = null; resolveStab();
ok(O.cadSet.join() === '112,120' && O.setT1 === 24 && O.setT2 === 28 && O.setId === 16 && K.PokemonSettings === CLASSES.PokemonSettingsProto && STAB.err === null,
   'resolveStab: both IPokemonSettings fields (112, 120), type1_ @24, type2_ @28, uniqueId_ @16, the class (got ' + JSON.stringify([O.cadSet, O.setT1, O.setT2, O.setId]) + ')');
ok(Object.keys(TYPE_ID).length === 18 && TYPE_ID.WATER === 11, 'resolveStab: the live HoloPokemonType enum became {WATER: 11, ...}');
ok(O.cadRelated.join() === 'attackerSettings:IPokemonSettings@112,defenderSettings:IPokemonSettings@120,owner:PokemonProto@128',
   'resolveStab: the install line names every Pokemon-ish button field (attackerSettings / defenderSettings answer the question at once): ' + O.cadRelated.join());
HIDE.PokemonSettingsProto = true; O = {}; K.PokemonSettings = null; resolveStab(); HIDE = {};
ok(O.setT1 === -1 && O.setT2 === -1 && O.setId === -1 && K.PokemonSettings === null && O.cadSet.length === 2 && STAB.err === null, 'resolveStab: the settings class missing leaves the offsets at -1, the button fields still listed, no throw');
var realFieldsOf = fieldsOf; fieldsOf = function () { throw new Error('boom'); }; O = {}; resolveStab(); fieldsOf = realFieldsOf;
ok(/boom/.test(STAB.err) && O.cadSet.length === 0 && O.setT1 === -1, 'resolveStab: a throw is caught, reported in STAB.err (-> the install line), never escapes install()'); STAB.err = null;
var g1 = obj(CLASSES.GymBattleSettingsProto, {24: ['f', 5], 40: ['f', 1.2000000476837158]}), g2 = obj(CLASSES.GymBattleSettingsProto, {24: ['f', 5], 40: ['f', 1.5]});
FIELDS.GymBattleSettingsProto = [{name: 'AttackServerInterval', off: 24, tn: 'System.Single'}, {name: 'SameTypeAttackBonusMultiplier', off: 40, tn: 'System.Single'}];
function freshMult() { STAB.live = null; STAB.mult = 1.2; STAB.multSrc = 'default'; STAB.err = null; }
INSTANCES.GymBattleSettingsProto = [g1]; freshMult(); resolveLiveMult();
ok(STAB.live === 1.2 && STAB.mult === 1.2 && STAB.multSrc === 'live', 'resolveLiveMult: the game\'s own 1.2 (a float32) is read and marked live');
INSTANCES.GymBattleSettingsProto = [obj(CLASSES.GymBattleSettingsProto, {24: ['f', 5], 40: ['f', 1.25]})]; freshMult(); resolveLiveMult();
ok(STAB.live === 1.25 && STAB.mult === 1.25, 'resolveLiveMult: a different live value (1.25) replaces the default');
INSTANCES.GymBattleSettingsProto = [g1, g2]; freshMult(); resolveLiveMult();
ok(STAB.live === null && STAB.multSrc === 'default', 'resolveLiveMult: two instances that disagree are not trusted (the game master value stays the fallback)');
INSTANCES.GymBattleSettingsProto = []; freshMult(); resolveLiveMult(); ok(STAB.live === null, 'resolveLiveMult: no live instance -> the fallback');
HIDE.GymBattleSettingsProto = true; INSTANCES.GymBattleSettingsProto = [g1]; freshMult(); resolveLiveMult(); HIDE = {};
ok(STAB.live === null && STAB.err === null, 'resolveLiveMult: the class missing -> the fallback, no throw');
FIELDS.GymBattleSettingsProto = [{name: 'AttackServerInterval', off: 24, tn: 'System.Single'}]; INSTANCES.GymBattleSettingsProto = [g1]; freshMult(); resolveLiveMult();
ok(STAB.live === null && STAB.err === null, 'resolveLiveMult: the field missing -> the fallback, no liveness walk needed');
FIELDS.GymBattleSettingsProto = [{name: 'SameTypeAttackBonusMultiplier', off: 40, tn: 'System.Single'}]; INSTANCES_THROW = true; freshMult(); resolveLiveMult(); INSTANCES_THROW = false;
ok(STAB.live === null && /liveness walk failed/.test(STAB.err), 'resolveLiveMult: a failing liveness walk is caught and reported'); freshMult();

/* ---- the multiplier and the table hand-over ---- */
resetAll(); STAB.multSrc = 'default';
var rep = loadStab({mult: 1.3, types: {'150': ['PSYCHIC'], '1': ['NOPE'], '2': []}});
ok(rep.types === 1 && rep.rejected === 2 && STAB.mult === 1.3 && rep.multSrc === 'game master', 'loadStab: the game master multiplier is used when the live one did not resolve; unknown / empty types are rejected, counted');
STAB.live = 1.25; STAB.mult = 1.25; STAB.multSrc = 'live'; rep = loadStab({mult: 1.2, types: TABLE});
ok(STAB.mult === 1.25 && rep.multSrc === 'live' && rep.gmMult === 1.2 && rep.liveMult === 1.25, 'loadStab never overrides the live multiplier');
resetAll(); STAB.multSrc = 'default'; loadStab({mult: 9, types: TABLE}); ok(STAB.mult === 1.2 && STAB.gm === null, 'an insane game master multiplier is ignored (the 1.2 default stays)');
resetAll(); loadStab({mult: null, types: TABLE}); ok(STAB.mult === 1.2, 'no game master multiplier: the default 1.2 stays');
TYPE_ID = {}; rep = loadStab({mult: 1.2, types: TABLE}); ok(rep.types === 0 && STAB.table === null && rep.rejected === Object.keys(TABLE).length, 'no live type enum: every table entry is rejected, the table is off');
resetAll();
var r0 = stabReport();
ok(r0.setT1 === 24 && r0.setT2 === 28 && r0.setId === 16 && r0.cadSettings.length === 2 && r0.moveType === true && r0.typeNames === 18 && r0.mult === 1.2, 'stabReport: what install() tells the runner');

/* ---- Palkia (Water/Dragon): Aqua Tail 50 and Draco Meteor 150 gain the bonus -- the brief's own example (60 / 180) ---- */
var SIX = [['1', 150, 0, false, PSYSTRIKE[3], SHADOW[3]], ['2', 68, 0, false, DYNAMIC[3], CROSS[3]], ['3', 646, 0, false, 14, 40],
           ['4', 484, 0, false, AQUA[3], DRACO[3]], ['5', 486, 0, false, 14, 0], ['6', 130, 0, false, 107, 0]];
resetAll(); team(SIX);
var palkia = mkSettings(484, TY.WATER, TY.DRAGON), t;
t = tick([mkDisplay({move: AQUA, charged: true, sets: [palkia]}), mkDisplay({move: DRACO, charged: false, sets: [palkia]})]);
ok(t.moves && t.moves.src === 'live' && t.moves.who === 484, 'Palkia: the live read is validated (species 484 is on our six with these moves)');
near(t.moves.list[0].dmg, 60, 'Palkia Aqua Tail 50 -> 60 with the bonus'); near(t.moves.list[1].dmg, 180, 'Palkia Draco Meteor 150 -> 180 with the bonus');
ok(t.moves.list[0].stab === 1.2 && t.moves.list[1].stab === 1.2 && t.moves.mult === 1.2, 'the moves line carries the factor per move (1.2) and the multiplier');
/* the same attacker, no settings object on the buttons at all: the game master table carries it (the brief's independent fallback) */
O.cadSet = []; t = tick([mkDisplay({move: AQUA, charged: true}), mkDisplay({move: DRACO, charged: false})]);
ok(t.moves.src === 'table' && t.moves.who === 484 && t.moves.list[0].dmg === 60 && t.moves.list[1].dmg === 180, 'Palkia without a live settings field: the table gives the same 60 / 180');
/* the state that produced the bug: the settings class matches but the first type field was never found (setT1 = -1) */
O = freshO(); O.setT1 = -1; SETOFF = {};
t = tick([mkDisplay({move: AQUA, charged: true, sets: [palkia]}), mkDisplay({move: DRACO, charged: false, sets: [palkia]})]);
ok(t.moves.src === 'table' && t.moves.list[0].dmg === 60 && t.moves.list[1].dmg === 180, 'setT1 = -1 (the old failure): the table still applies the bonus -- and install() now reports it');

/* ---- Mewtwo: Psystrike 95 vs Shadow Ball 100. Psychic is its type: 114 beats 100, so the pick changes ---- */
resetAll(); team(SIX);
var mewtwo = mkSettings(150, TY.PSYCHIC, 0);
var ps = mkDisplay({move: PSYSTRIKE, charged: true, sets: [mewtwo]}), sb = mkDisplay({move: SHADOW, charged: true, sets: [mewtwo]});
t = tick([ps, sb]);
near(t.moves.list[0].dmg, 114, 'Mewtwo Psystrike 95 -> 114'); near(t.moves.list[1].dmg, 100, 'Mewtwo Shadow Ball stays 100 (Ghost is not its type)');
ok(t.charged === 0 && !t.fast, 'both charged: Psystrike (the same-type move) fires, not Shadow Ball');
team([]); t = tick([ps, sb]);
ok(t.moves.src === 'none' && t.moves.list[0].dmg === 95 && t.charged === 1, 'no snapshot of our six: no boost, the OLD pick (Shadow Ball 100 > Psystrike 95) -- unchanged behaviour');
ok(/snapshot/.test(t.moves.note), 'the moves line says why there is no boost');

/* ---- a settings object of ANOTHER species (the defender's) must never boost the attacker's moves ---- */
resetAll(); team([['1', 150, 0, false, PSYSTRIKE[3], HYDRO[3]]]);
var gyarados = mkSettings(130, TY.WATER, TY.FLYING);
t = tick([mkDisplay({move: PSYSTRIKE, charged: true, sets: [gyarados]}), mkDisplay({move: HYDRO, charged: true, sets: [gyarados]})]);
ok(t.moves.src === 'table' && t.moves.who === 150, 'a defender settings object is refused: the attacker comes from our six + the table');
ok(t.moves.list[0].stab === 1.2 && t.moves.list[1].stab === 1 && t.moves.list[1].dmg === 135, 'Mewtwo: Psystrike boosted, Hydro Pump NOT boosted just because the defender is Water');
ok(t.infos.length === 1 && /species #130, not the attacker/.test(t.infos[0].what), 'it says so once');
t = tick([mkDisplay({move: PSYSTRIKE, charged: true, sets: [gyarados]}), mkDisplay({move: HYDRO, charged: true, sets: [gyarados]})]);
ok(t.infos.length === 0, '...and only once');
t = tick([mkDisplay({move: PSYSTRIKE, charged: true, sets: [gyarados, mewtwo]}), mkDisplay({move: HYDRO, charged: true, sets: [gyarados, mewtwo]})]);
ok(t.moves.src === 'live' && t.moves.who === 150, 'two settings fields (defender first, attacker second): the one that matches our six is used');
/* another class of settings object (a wrapper): unreadable, the table decides, reported once */
resetAll(); team([['1', 150, 0, false, PSYSTRIKE[3], SHADOW[3]]]);
t = tick([mkDisplay({move: PSYSTRIKE, charged: true, sets: [mkSettings(150, TY.PSYCHIC, 0, 'TempEvoPokemonSettings')]}), mkDisplay({move: SHADOW, charged: true})]);
ok(t.moves.src === 'table' && t.moves.list[0].stab === 1.2 && t.infos.length === 1 && /another class/.test(t.infos[0].what) && t.infos[0].layout === 'TempEvoPokemonSettings', 'an unreadable settings class falls back to the table and names the class');
/* a readable object with garbage types is not trusted either */
resetAll(); team([['1', 150, 0, false, PSYSTRIKE[3], SHADOW[3]]]);
t = tick([mkDisplay({move: PSYSTRIKE, charged: true, sets: [mkSettings(150, 0, 0)]}), mkDisplay({move: SHADOW, charged: true})]);
ok(t.moves.src === 'table' && t.moves.list[0].stab === 1.2, 'a matching species with no types falls through to the table');

/* ---- every refusal leaves the old behaviour ---- */
resetAll(); team([['1', 150, 0, true, PSYSTRIKE[3], SHADOW[3]]]);
t = tick([mkDisplay({move: PSYSTRIKE, charged: true, sets: [mewtwo]}), mkDisplay({move: SHADOW, charged: true, sets: [mewtwo]})]);
ok(t.moves.src === 'none' && /mega/.test(t.moves.note) && t.moves.list[0].stab === 1, 'a mega-evolved attacker: no boost (its types differ), even with a live object');
resetAll(); team([['1', 150, 0, false, 1, 2]]);
t = tick([mkDisplay({move: PSYSTRIKE, charged: true, sets: [mewtwo]})]); ok(t.moves.src === 'none' && /none of our six/.test(t.moves.note), 'no member of our six carries the button moves: no boost');
resetAll(); team([['1', 999, 0, false, PSYSTRIKE[3], SHADOW[3]]]);
t = tick([mkDisplay({move: PSYSTRIKE, charged: true}), mkDisplay({move: SHADOW, charged: true})]);
ok(t.moves.src === 'none' && /no game master types for #999 form 0/.test(t.moves.note), 'a species the game master table lacks: no boost, says which');
STAB.table = null; team([['1', 150, 0, false, PSYSTRIKE[3], SHADOW[3]]]);
t = tick([mkDisplay({move: PSYSTRIKE, charged: true}), mkDisplay({move: SHADOW, charged: true})]); ok(t.moves.src === 'none' && /no game master table/.test(t.moves.note), 'no table handed over and no live read: no boost');
resetAll(); O.mvTypeOk = false; team(SIX);
t = tick([mkDisplay({move: AQUA, charged: true, sets: [palkia]}), mkDisplay({move: DRACO, charged: false, sets: [palkia]})]);
ok(t.moves.list[0].stab === 1 && t.moves.list[0].dmg === 50, 'a move-type field that is not a HoloPokemonType: the bonus is off');
resetAll(); team(SIX); ACTIVE = null;
t = tick([mkDisplay({move: AQUA, charged: true, sets: [palkia]})]);
ok(t.moves.src === 'none' && t.moves.note === 'the STAB read failed' && t.moves.who === null && t.charged === 0 && !t.fast, 'a throw inside the STAB read is contained: the tick still ran, no boost, Aqua Tail (only move, charged) fired');
resetAll(); team(SIX); LIVEPROTO_THROWS = true;
t = tick([mkDisplay({move: AQUA, charged: true, sets: [palkia]})]); ok(t.moves.src === 'none' && t.charged === 0, 'the bag throwing while the six are read: no boost, the tick carries on');

/* ---- ambiguity: two of our six share the only charge move ---- */
resetAll(); team([['1', 486, 0, false, RETURN[3], 0], ['2', 68, 0, false, RETURN[3], 0]]);
t = tick([mkDisplay({move: RETURN, charged: true}), mkDisplay({move: null})]);
ok(t.moves.src === 'table' && t.moves.who === null && t.moves.list.length === 1 && t.moves.list[0].stab === 1, 'two candidates with different types (Normal, Fighting) disagree on Return: no boost');
resetAll(); team([['1', 486, 0, false, RETURN[3], 0], ['2', 143, 0, false, RETURN[3], 0]]);
t = tick([mkDisplay({move: RETURN, charged: true}), mkDisplay({move: null})]);
ok(t.moves.src === 'table' && t.moves.list[0].stab === 1.2 && t.moves.list[0].dmg === 30 && t.moves.who === null, 'two Normal-type candidates agree: Return gets the bonus (25 -> 30)');
resetAll(); team([['1', 486, 0, false, RETURN[3], 0], ['2', 68, 0, false, RETURN[3], 0]]);
t = tick([mkDisplay({move: RETURN, charged: true, sets: [mkSettings(486, TY.NORMAL, 0)]}), mkDisplay({move: null})]);
ok(t.moves.src === 'live' && t.moves.who === 486 && t.moves.list[0].stab === 1.2, 'the live object\'s species settles the ambiguity');

/* ---- forms, placeholder buttons, effectiveness, the multiplier ---- */
resetAll();
var WILD = [90, 50, TY.ELECTRIC, 251], PSY2 = [95, 50, TY.PSYCHIC, 108];
team([['1', 26, 50, false, 251, 108]]);
t = tick([mkDisplay({move: WILD, charged: true}), mkDisplay({move: PSY2, charged: true})]);
ok(t.moves.list[0].stab === 1.2 && t.moves.list[1].stab === 1.2, 'Alolan Raichu (form 50): Electric AND Psychic both get the bonus from the form entry');
team([['1', 26, 0, false, 251, 108]]); t = tick([mkDisplay({move: WILD, charged: true}), mkDisplay({move: PSY2, charged: true})]);
ok(t.moves.list[0].stab === 1.2 && t.moves.list[1].stab === 1, 'plain Raichu (form 0): only Electric does');
resetAll(); team(SIX);
t = tick([mkDisplay({move: null}), mkDisplay({move: DRACO, charged: true, eff: 'SUPER EFFECTIVE!', sets: [palkia]})]);
ok(t.moves.list.length === 1 && t.charged === 1, 'a placeholder button (no move) is skipped');
ok(t.moves.list[0].dmg === Math.round(150 * 1.6 * 1.2), 'super effective x the bonus: 150 x 1.6 x 1.2 = 288');
t = tick([mkDisplay({move: DRACO, charged: true, eff: 'NOT VERY EFFECTIVE', sets: [palkia]})]);
ok(t.moves.list[0].dmg === Math.round(150 * 0.625 * 1.2), 'not very effective x the bonus: 150 x 0.625 x 1.2 = 112.5 (shown rounded)');
STAB.live = 1.25; STAB.mult = 1.25; STAB.multSrc = 'live';
t = tick([mkDisplay({move: DRACO, charged: true, sets: [palkia]})]);
ok(t.moves.list[0].dmg === Math.round(150 * 1.25), 'the live multiplier (1.25) is what is applied'); near(t.moves.mult, 1.25, 'and what the line reports');

/* ---- the moves line is re-sent when the STAB source changes, not on every tick ---- */
resetAll(); team(SIX);
var b1 = [mkDisplay({move: AQUA, charged: false, sets: [palkia]}), mkDisplay({move: DRACO, charged: false, sets: [palkia]})];
function tickKeep(ds) {                        /* like tick() but keeps ST.moveKey, as the real tapper does */
  var svc = obj(K.svc, {}), arr = alloc(256);
  put(arr, 0x18, 'i', ds.length); ds.forEach(function (d, i) { put(arr, 0x20 + 8 * i, 'p', d); });
  GBS = obj(CLASSES.GymBattleState, {48: ['p', svc], 56: ['p', obj(CLASSES.BattleGestureHandler, {64: ['p', arr]})]});
  SENT = []; ST.last = 0; NOW += 200; attack(NOW); return SENT.filter(function (m) { return m.k === 'moves'; }).length;
}
ST.moveKey = null; ok(tickKeep(b1) === 1 && tickKeep(b1) === 0 && tickKeep(b1) === 0, 'one moves line per attacker, not one per tick');
O.cadSet = []; ok(tickKeep(b1) === 1, 'a new STAB source (live -> table) on the same attacker says so once');

/* ---- the snapshot of our six: read once per roster, not once per tick ---- */
resetAll(); team(SIX); LIVEPROTO_CALLS = 0;
tick([mkDisplay({move: AQUA, charged: false})]); var first = LIVEPROTO_CALLS; tick([mkDisplay({move: AQUA, charged: false})]); tick([mkDisplay({move: AQUA, charged: false})]);
ok(first === 6 && LIVEPROTO_CALLS === 6, 'six bag reads for the first tick, none after (got ' + first + ' then ' + LIVEPROTO_CALLS + ')');
team(SIX); LIVEPROTO_CALLS = 0; tick([mkDisplay({move: AQUA, charged: false})]); ok(LIVEPROTO_CALLS === 6, 'a new battle (new roster stamp) reads the six again');

/* ---- what attack() does around the STAB: the old rules are intact ---- */
resetAll(); team(SIX);
t = tick([mkDisplay({move: AQUA, charged: true, sets: [palkia]}), mkDisplay({move: HYDRO, charged: false, sets: [palkia]})]);
ok(t.charged === 0, 'the big move is not ready: the clearly more efficient charged one (Aqua Tail) still fires');
ok(t.moves.src === 'none' && /none of our six/.test(t.moves.note) && t.moves.list[0].dmg === 50 && t.moves.list[1].dmg === 135,
   'Aqua Tail (Palkia) + Hydro Pump (Gyarados) are carried by no ONE of our six: the buttons match nobody, no boost');
t = tick([mkDisplay({move: AQUA, charged: false, sets: [palkia]}), mkDisplay({move: DRACO, charged: false, sets: [palkia]})]);
ok(t.charged === -1 && t.fast, 'nothing charged: a fast attack');
ok(ST.charged >= 1 && ST.fast >= 1, 'the tapper counters still move');
console.log('ok: ' + N + ' STAB checks passed (field resolution, live read, table, refusals, pick, multiplier, reporting)');
"""


def stab_block(js):
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "stab_block.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(MOCK + block(js) + "\n" + TESTS)
        r = subprocess.run([NODE, p], capture_output=True, text=True)
        out = (r.stdout.strip() + "\n" + r.stderr.strip()).strip()
        print(out)
        check(r.returncode == 0, "the STAB block checks failed under node")


# ------------------------------------------------------------------------------------------------ 3. stab_config()
def gm_fixture(td):
    def tpl(tid, **kw):
        return {"templateId": tid, "data": {"templateId": tid, "pokemonSettings": kw}}
    gm = [{"templateId": "BATTLE_SETTINGS", "data": {"battleSettings": {"sameTypeAttackBonusMultiplier": 1.2}}},
          tpl("V0019_POKEMON_RATTATA", pokemonId="RATTATA", type="POKEMON_TYPE_NORMAL"),
          tpl("V0019_POKEMON_RATTATA_NORMAL", pokemonId="RATTATA", type="POKEMON_TYPE_NORMAL", form="RATTATA_NORMAL"),
          tpl("V0019_POKEMON_RATTATA_ALOLA", pokemonId="RATTATA", type="POKEMON_TYPE_DARK", type2="POKEMON_TYPE_NORMAL", form="RATTATA_ALOLA"),
          tpl("V0150_POKEMON_MEWTWO", pokemonId="MEWTWO", type="POKEMON_TYPE_PSYCHIC"),
          tpl("V0150_POKEMON_MEWTWO_A", pokemonId="MEWTWO", type="POKEMON_TYPE_PSYCHIC", form="MEWTWO_A"),
          tpl("V0484_POKEMON_PALKIA", pokemonId="PALKIA", type="POKEMON_TYPE_WATER", type2="POKEMON_TYPE_DRAGON"),
          tpl("V0122_POKEMON_MR_MIME", pokemonId="MR_MIME", type="POKEMON_TYPE_PSYCHIC", type2="POKEMON_TYPE_FAIRY"),
          tpl("V0122_POKEMON_MR_MIME_GALARIAN", pokemonId="MR_MIME", type="POKEMON_TYPE_ICE", type2="POKEMON_TYPE_PSYCHIC", form="MR_MIME_GALARIAN"),
          tpl("V0493_POKEMON_ARCEUS", pokemonId="ARCEUS", type="POKEMON_TYPE_NORMAL"),
          tpl("V0493_POKEMON_ARCEUS_WATER", pokemonId="ARCEUS", type="POKEMON_TYPE_WATER", form="ARCEUS_WATER"),
          tpl("V0999_POKEMON_NEWMON", pokemonId="NEWMON", type="POKEMON_TYPE_FIRE"),
          tpl("V0999_POKEMON_NEWMON_SHINY_FORM", pokemonId="NEWMON", type="POKEMON_TYPE_FIRE", type2="POKEMON_TYPE_GHOST", form="NEWMON_SHINY_FORM"),
          {"templateId": "SOMETHING_ELSE", "data": {}}]
    enum = {"0": "Unset", "45": "RattataNormal", "46": "RattataAlola", "133": "MewtwoA", "200": "MrMimeGalarian", "101": "ArceusWater"}
    g, e = os.path.join(td, "gm.json"), os.path.join(td, "form_enum.json")
    with open(g, "w", encoding="utf-8") as f:
        json.dump(gm, f)
    with open(e, "w", encoding="utf-8") as f:
        json.dump(enum, f)
    return g, e


def config_checks():
    with tempfile.TemporaryDirectory() as td:
        g, e = gm_fixture(td)
        c = gym_tapper.stab_config(g, e)
        t = c["types"]
        check(c["mult"] == 1.2 and c["species"] == 6, f"synthetic game master: multiplier / species ({c['mult']}, {c['species']})")
        check(t["19"] == ["NORMAL"] and t["150"] == ["PSYCHIC"] and t["484"] == ["WATER", "DRAGON"], "species typings")
        check(t["19:46"] == ["DARK", "NORMAL"] and "19:45" not in t, "the Alolan form gets its own entry, the plain form none")
        check("150:133" not in t, "a form typed like its species (Armored Mewtwo) gets no entry")
        check(t["122:200"] == ["ICE", "PSYCHIC"] and t["493:101"] == ["WATER"], "Galarian Mr. Mime / Arceus Water: matched letters-and-digits against the enum's CamelCase")
        check(c["unmapped"] == 1 and "999:1" not in t and c["forms"] == 3, f"a form the enum lacks is counted, not guessed ({c['unmapped']} unmapped, {c['forms']} forms)")
        check(c["names"][122] == "Mr Mime" and c["names"][484] == "Palkia", "names for the log lines")
        check(gym_tapper.stab_config(g, e) is c, "the table is built once per file pair")
        check(json.dumps({"mult": c["mult"], "types": t}), "the hand-over payload is plain JSON")
        bad = gym_tapper.stab_config(os.path.join(td, "missing.json"), e)
        check("err" in bad and "hint" in bad and "types" not in bad, "a missing game master comes back as an error dict (the runner goes on), never raises")
        broken = os.path.join(td, "broken.json")
        with open(broken, "w", encoding="utf-8") as f:
            f.write("{not json")
        check("err" in gym_tapper.stab_config(broken, e), "a game master that is not JSON comes back as an error dict, never raises")
        gm2 = os.path.join(td, "gm2.json")
        with open(gm2, "w", encoding="utf-8") as f:
            json.dump([{"templateId": "BATTLE_SETTINGS", "data": {"battleSettings": {"sameTypeAttackBonusMultiplier": 9}}}], f)
        check(gym_tapper.stab_config(gm2, e)["mult"] is None, "an insane multiplier in the game master is dropped (the tapper keeps its default)")
    real = gym_tapper.GM_PATH
    if os.path.exists(real):
        c = gym_tapper.stab_config()
        t = c["types"]
        check(c["mult"] == 1.2 and c["species"] >= 1000 and c["forms"] >= 100 and c["unmapped"] == 0, f"real game master: {c['species']} species, {c['forms']} form entries, {c['unmapped']} unmapped")
        check(t["150"] == ["PSYCHIC"] and t["484"] == ["WATER", "DRAGON"] and t["26:50"] == ["ELECTRIC", "PSYCHIC"] and t["19:46"] == ["DARK", "NORMAL"], "real game master: Mewtwo, Palkia, Alolan Raichu / Rattata")
        print(f"ok: real game master table: {len(t)} entries ({c['species']} species + {c['forms']} form overrides), multiplier {c['mult']}")
    else:
        print("ok: synthetic game master table (the real pogo_extract/gamemaster_pokeminers.json is not here -- data, not in git)")
    if not FAILS:
        print("ok: stab_config() builds the typing table and never raises")


# ------------------------------------------------------------------------------------------------ 4. the runner's report lines
def runner_checks():
    import gym_run
    names = {150: "Mewtwo"}
    tag = gym_run.stab_tag({"who": 150, "src": "live", "mult": 1.2, "note": ""}, names)
    check(tag == " [attacker #150 Mewtwo; types: live; same-type x1.2]", f"stab_tag live: {tag!r}")
    tag = gym_run.stab_tag({"who": None, "src": "none", "mult": 1.2, "note": "no snapshot of our six"}, names)
    check("attacker unknown" in tag and "types: none (no snapshot of our six)" in tag, f"stab_tag none: {tag!r}")
    check("#999;" in gym_run.stab_tag({"who": 999, "src": "table", "mult": 1.25}, names) and "x1.25" in gym_run.stab_tag({"who": 999, "src": "table", "mult": 1.25}, names),
          "stab_tag for a species with no name")

    def said(fn, *a):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(*a)
        return buf.getvalue()

    g = gym_run.Game()
    g.stab_names = names
    out = said(g.on_msg, {"type": "send", "payload": {"k": "moves", "list": [{"n": "V0109MovePsystrike", "dmg": 114, "en": 50, "dpe": 2.28, "stab": 1.2},
                                                                              {"n": "V0070MoveShadowBall", "dmg": 100, "en": 50, "dpe": 2.0, "stab": 1}],
                                                     "src": "live", "who": 150, "note": "", "mult": 1.2}}, None)
    check("charged moves: V0109MovePsystrike 114 dmg / 50 energy stab x1.2, V0070MoveShadowBall 100 dmg / 50 energy stab x1 -> the strongest fires when charged "
          "[attacker #150 Mewtwo; types: live; same-type x1.2]" in out, f"the charged moves line: {out!r}")

    class Fake:                                   # a tapper that answers stab() like the real one
        def __init__(self):
            self.sent = None
            self.exports_sync = self

        def stab(self, cfg):
            self.sent = cfg
            return {"types": len(cfg["types"]), "rejected": 0, "mult": 1.2, "multSrc": "game master", "liveMult": None, "gmMult": cfg["mult"]}

    with tempfile.TemporaryDirectory() as td:
        gm, en = gm_fixture(td)
        real_cfg = gym_tapper.stab_config
        gym_tapper.stab_config = lambda: real_cfg(gm, en)
        try:
            good = {"stab": {"cadSettings": [560], "setT1": 24, "setT2": 28, "setId": 16, "moveType": True, "typeNames": 18, "mult": 1.2, "multSrc": "live",
                             "related": ["attackerSettings:IPokemonSettings@560"], "err": None}}
            fk, g2 = Fake(), gym_run.Game()
            out = said(gym_run.stab_setup, fk, g2, good)
            check("settings field(s) @560" in out and "types @24/@28, species @16" in out and "multiplier x1.2 (live)" in out and "attackerSettings:IPokemonSettings@560" in out, f"install line: {out!r}")
            check("!!" not in out and "STAB table from the game master: 9 typings (6 species + 3 form overrides)" in out, f"table line: {out!r}")
            check(fk.sent and fk.sent["mult"] == 1.2 and "484" in fk.sent["types"] and "names" not in fk.sent and g2.stab_names[484] == "Palkia", "the tapper gets mult + types only; the names stay on the runner")
            bad = {"stab": {"cadSettings": [], "setT1": -1, "setT2": 28, "setId": 16, "moveType": False, "typeNames": 0, "mult": 1.2, "multSrc": "default", "err": "boom"}}
            out = said(gym_run.stab_setup, Fake(), gym_run.Game(), bad)
            for want in ("settings field(s) NONE", "no IPokemonSettings field", "types / species not all found", "is not a HoloPokemonType", "enum was not read", "raised: boom"):
                check(want in out, f"the report flags {want!r}: {out!r}")
            gym_tapper.stab_config = lambda: {"err": "FileNotFoundError: gone", "hint": "pull it"}
            fk = Fake()
            out = said(gym_run.stab_setup, fk, gym_run.Game(), good)
            check("table unavailable (FileNotFoundError: gone; pull it)" in out and fk.sent is None, "no game master: said plainly, the tapper is not called, the runner goes on")
        finally:
            gym_tapper.stab_config = real_cfg
    if not FAILS:
        print("ok: gym_run stab_tag() / stab_setup() / the charged moves line")


def main():
    js = gym_tapper.JS
    if NODE is None:
        print("SKIP: node not found -- the script text and the STAB block were NOT checked (CI has node)")
    else:
        script_text(js)
        stab_block(js)
    config_checks()
    runner_checks()
    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED")
        return 1
    print("\nALL GYM STAB CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
