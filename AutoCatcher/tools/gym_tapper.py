"""Gym battles, the game's own way: one per-frame tick inside Pokemon GO (Frida), imported by tools/gym_run.py.

Rules learned the hard way (2026-09-25; see memory reference-pogo-native-gym-flow):
  - EVERY game call goes through il2cpp_runtime_invoke with an exception slot. A managed exception comes back as a
    value instead of unwinding through a Frida frame (that aborted the game once).
  - EVERY action and read runs in ONE place: Scheduler.LateUpdate ENTRY via a Frida PROBE hook (frameTick), ≤10 Hz, never nested. Actions
    run from other hooks froze the game twice.
  - Almost no hooks: LateUpdate, the results state's EnterState (plain memory writes), and GuiLayerService
    Register/UnregisterGui (popup auto-dismiss). Whole-class catch-all hooks on the party screen were in place while its
    close path kept failing (screens piled up over the battles) -- none remain.
  - Instances (root state, GUI layer service, map directory) come from the C-only liveness walk, done in install()
    BEFORE any hook exists.
  - Every field offset and type is read live from il2cpp metadata by name/type; nothing is hardcoded.

The flow it drives (gym_run.py asks, this executes): open a gym (MapGym.OnTapped) -> Battle (GymApproachGuiController.
ClickBattle -- its battleButton is an Image) -> GO (the party screen's battleButton, a real Button, Button.Press) ->
attacks (TryOrQueueAttack; charged via ChargeAttackButtonTapped when <IsCharged>, Pokemod's pick by the game's own
effectiveness text) -> continue between defenders (ContinueToNextBattle once the screen is Opening/Open and wired).
A watchdog reports a party screen still Open after its battle started ('prepstuck').

The charged-move pick is power x the game's effectiveness label x the same-type bonus (STAB). STAB never applied before 2026-09-30
(the first-type field was looked up as type / type_, the game names it type1_); see the STAB block in the script and GYM.md. The
runner hands the tapper the client game master's typing table through stab_config() below, used only where the live read yields nothing.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import dump_game_limits as dl  # noqa: E402
import live_graph_js as lg  # noqa: E402

ACT_MS = 100

JS = dl.JS.split("rpc.exports = {")[0] + lg.JS + r"""
var NS = f('il2cpp_class_get_namespace', 'pointer', ['pointer']);
var MFN = f('il2cpp_class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']);
var TN = f('il2cpp_type_get_name', 'pointer', ['pointer']);
var CGF = f('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']), FGN = f('il2cpp_field_get_name', 'pointer', ['pointer']);
var SGV = f('il2cpp_field_static_get_value', 'void', ['pointer', 'pointer']);
var CEC = f('il2cpp_class_get_element_class', 'pointer', ['pointer']), CVS = f('il2cpp_class_value_size', 'int', ['pointer', 'pointer']);
function klassOf(o) { return o.readPointer(); }                 /* obj->klass, a catchable Frida read */
function nameOf(k) { return cs(k.add(0x10).readPointer()); }       /* klass->name */
function isA(o, k) { try { return !!k && !o.isNull() && o.readPointer().equals(k); } catch (e) { return false; } }
function full(k) { var n = cs(NS(k)); return (n ? n + '.' : '') + cs(IL.className(k)); }
var CFN = f('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']);
var PTM = f('il2cpp_method_get_param', 'pointer', ['pointer', 'uint32']), PNM = f('il2cpp_method_get_param_name', 'pointer', ['pointer', 'uint32']);
var MPC = f('il2cpp_method_get_param_count', 'uint32', ['pointer']);
var MCLS = f('il2cpp_method_get_class', 'pointer', ['pointer']);   /* a hook only on the class's OWN method, never an inherited one */
function sigOf(m) { var t = []; for (var i = 0; i < MPC(m); i++) t.push(cs(TN(PTM(m, i)))); return t.join(','); }
function byName(ns, name) {                   /* exact-name lookup per image -- never a walk over every class (that crashed PoGo twice) */
  var sp = Memory.alloc(PS), a = IL.asms(IL.domain(), sp), n = sp.readU32(), nsp = Memory.allocUtf8String(ns), nmp = Memory.allocUtf8String(name);
  for (var i = 0; i < n; i++) { var k = CFN(IL.asmImage(a.add(i * PS).readPointer()), nsp, nmp); if (!k.isNull()) return k; }
  return null;
}
function tname(x) { return cs(TN(x.t)); }

/* ---- the only way this script calls the game ---- */
var RINV = f('il2cpp_runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
var FEXC = EX['il2cpp_format_exception'] ? f('il2cpp_format_exception', 'void', ['pointer', 'pointer', 'int']) : null;
var EXC = Memory.alloc(PS), EXC_TXT = Memory.alloc(512), EXC_N = 0, EXC_BY = {};
function call(m, obj, what, args) {           /* -> return object (boxed for value types), or null if it threw */
  EXC.writePointer(NULL);
  var ap = NULL;
  if (args && args.length) { ap = Memory.alloc(PS * args.length); for (var i = 0; i < args.length; i++) ap.add(PS * i).writePointer(args[i]); }
  var r = RINV(m, obj, ap, EXC), ex = EXC.readPointer();
  if (ex.isNull()) return r;
  var msg = '';
  try { if (FEXC) { EXC_TXT.writeU8(0); FEXC(ex, EXC_TXT, 511); msg = EXC_TXT.readUtf8String(); } } catch (e) {}
  var key = String(what).split(' ')[0];
  if ((EXC_BY[key] = (EXC_BY[key] || 0) + 1) <= 20) send({k: 'exc', what: what, msg: msg});
  return null;
}
function callB(m, o, w) { var r = call(m, o, w); return r !== null && !r.isNull() ? !!r.add(16).readU8() : null; }
function callI(m, o, w) { var r = call(m, o, w); return r !== null && !r.isNull() ? r.add(16).readS32() : null; }

/* ---- metadata, resolved live in install() ---- */
var K = {}, M = {}, O = {}, LIT = {};
function fieldBy(k, pred) { var r = -1; fieldsOf(k).forEach(function (x) { if (r < 0 && pred(x.name, tname(x))) r = x.off; }); return r; }
var GWATCH = null;                            /* the live-graph tripwire (the graph helpers: live_graph_js.py) */
function need(name, v) { if (v === undefined || v === null || v < 0 || (v.isNull && v.isNull())) MISSING.push(name); return v; }
function methodOn(k, name, argc) { var m = MFN(k, Memory.allocUtf8String(name), argc === undefined ? 0 : argc); return m.isNull() ? null : m; }
function enumLits(k) {
  var it = Memory.alloc(PS), fd, out = {}; it.writePointer(NULL);
  while ((fd = CGF(k, it)) && !fd.isNull()) { var nm = cs(FGN(fd)); if (nm === 'value__') continue; var b = Memory.alloc(8); b.writeS64(0); SGV(fd, b); out[nm] = b.readS32(); }
  return out;
}
function alive(o) {                           /* a Unity object that has not been destroyed (plain read) */
  try { return !o.isNull() && (O.cptr < 0 || !o.add(O.cptr).readPointer().isNull()); } catch (e) { return false; }
}
var MISSING = [];

/* ---- live picture ---- */
var ROOT = null, GLS = null, GLS_CANDS = [], DIR = null;
var CHAIN = '', LEAF = '', GAS = null, GBS = null, IN_BATTLE = false, ROUND = false;
var TOP = null, TOP_AT = 0, PREP = null, CONT = null;
var GTEAM = {}, GYMS = {}, MAP_AT = 0, PENDING = null, PENDING_AT = 0;
var ACT = null, ACT_AT = 0, EXPECT_PREP = 0, GO_AT = 0, PREP_AT = 0, WATCH = [], POPQ = [], GUIS = {};
var ST = {last: 0, fast: 0, charged: 0, lastSent: 0, errs: 0, textOff: -1, teamAt: 0, teamKey: null, modal: null, modalAt: 0, nch: 0};
var GSTATE = null;                            /* the active GymState (from the chain): its FailedToStartBattle() ends a hung battle */
var BUSY = false, FT_AT = 0, TOPCHK_AT = 0, TIMERS_TOLD = false, FAST_RESULTS = 0.5, FAST_CAMERA = 0.2, FAST_ROTATE = 0.2, ROT_TOLD = false;
var SKIPQ = {}, SKIP_OFF = {}, FAST_GBS = {}, RESULTS_DELAY = 0.3;
var HS = null;                                /* GuiLayerService's HashSet<IGuiLayerable>: every registered screen (layout read live) */
function registered() {                       /* the registered screens, straight from the layer service (plain reads) */
  var out = [];
  if (!GLS || !HS) return out;
  var set = GLS.add(HS.field).readPointer(); if (set.isNull()) return out;
  var ents = set.add(HS.entries).readPointer(), n = set.add(HS.count).readS32(); if (ents.isNull()) return out;
  for (var i = 0; i < n && i < 512; i++) {
    var e = ents.add(0x20 + HS.esz * i); if (HS.hash >= 0 && e.add(HS.hash).readS32() < 0) continue;
    var g = e.add(HS.value).readPointer(); if (!g.isNull()) out.push(g);
  }
  return out;
}
function hsLayout() {                         /* resolve the HashSet layout once GLS is known */
  if (HS || !GLS) return;
  var off = fieldBy(K.GuiLayerService, function (n, t) { return /^System\.Collections\.Generic\.HashSet(`1)?<Niantic\.Zeppelin\.UI\.IGuiLayerable>$/.test(t); });
  if (off < 0) { HS = {bad: 'no HashSet<IGuiLayerable> field'}; return; }
  var set = GLS.add(off).readPointer(); if (set.isNull()) return;
  var h = {field: off};
  fieldsOf(klassOf(set)).forEach(function (x) {
    if (x.name === '_entries' || x.name === '_slots' || x.name === 'm_slots') h.entries = x.off;
    if (x.name === '_count' || x.name === 'm_lastIndex' || x.name === '_lastIndex') h.count = x.off; });
  if (h.entries === undefined || h.count === undefined) { HS = {bad: 'HashSet layout'}; return; }
  var ents = set.add(h.entries).readPointer(); if (ents.isNull()) return;
  var ek = CEC(klassOf(ents)), al = Memory.alloc(4); h.esz = CVS(ek, al); h.hash = -1;
  fieldsOf(ek).forEach(function (x) { var n = x.name.toLowerCase(); if (n === 'hashcode') h.hash = x.off - 16; if (n === 'value') h.value = x.off - 16; });
  if (h.value === undefined || !(h.esz > 0)) { HS = {bad: 'HashSet entry layout'}; return; }
  HS = h; send({k: 'info', what: 'registered-screens reader ready', layout: h});
}
function earlyScreens(now) {                  /* catch the countdown / NEXT UP / motivation / result screens the moment they register */
  if (!HS || HS.bad || !IN_BATTLE) return;
  for (var og in OUTCOME_SEEN) if (now - OUTCOME_SEEN[og] > 600000) delete OUTCOME_SEEN[og];
  for (var cd in CONT_DONE) if (now - CONT_DONE[cd] > 600000) delete CONT_DONE[cd];
  for (var sd in SKIP_DONE) if (now - SKIP_DONE[sd] > 600000) delete SKIP_DONE[sd];
  registered().forEach(function (g) {
    try {
      var k = g.readPointer();
      if (k.equals(K.GymBattleContinueGuiController)) { if (!CONT_DONE[g] && (!CONT || !CONT.gui.equals(g))) CONT = {gui: g, k: k, at: now}; }
      else {
        var nm = k.equals(K.GymBattleIntroGuiController) ? 'GymBattleIntroGuiController' : k.equals(K.MotivationCpChangeController) ? 'MotivationCpChangeController'
               : k.equals(K.GymBattleVictoryGuiController) ? 'GymBattleVictoryGuiController' : k.equals(K.GymBattleDefeatGuiController) ? 'GymBattleDefeatGuiController' : null;
        if (!nm) return;
        if ((nm === 'GymBattleVictoryGuiController' || nm === 'GymBattleDefeatGuiController') && !OUTCOME_SEEN[g]) {
          OUTCOME_SEEN[g] = now; send({k: 'outcome', v: nm === 'GymBattleVictoryGuiController' ? 'victory' : 'defeat'});
          if (nm === 'GymBattleVictoryGuiController' && DD_OK && AUTODEP && !PLACED) DDW = {fid: AUTODEP.fid, t0: now, until: now + 8000, next: 0}; }
        if (!SKIP_OFF[nm] && !SKIP_DONE[g] && (!SKIPQ[nm] || !SKIPQ[nm].gui.equals(g))) SKIPQ[nm] = {gui: g, k: k, at: now};
      }
    } catch (e) {}
  });
}
var SKIP = ['GymBattleIntroGuiController', 'MotivationCpChangeController', 'GymBattleVictoryGuiController', 'GymBattleDefeatGuiController',
            'DailyIncenseRecapGuiController', 'GymBadgeAwardGuiController'];   /* (the last two: map popups that block a gym open for 20-30 s) */
var SKIP_BASE = {}, CPARENT = null;
function derivesGui(k) {                      /* metadata-only parent walk: is this screen really a GuiController (Dismiss + currentState valid)? */
  if (!CPARENT) CPARENT = f('il2cpp_class_get_parent', 'pointer', ['pointer']);
  for (var i = 0; i < 16 && k && !k.isNull(); i++) { if (k.equals(K.GuiController)) return true; k = CPARENT(k); }
  return false;
}   /* tap-through screens: closed with their own Dismiss once Open */
var OUTCOME_SEEN = {}, CONT_DONE = {}, SKIP_DONE = {};
var AUTODEP = null, MYTEAM = 2, LAST_OPEN = {fid: null, at: 0}, LEFT_GYM_AT = 0, MAP_SINCE = 0;              /* {fid, at, cands, friendly}: act the moment this gym reports empty (or ours with a slot) */
var PP = null;                                /* PokemonProto offsets (live) for the placement checks */
function protoOffs() {
  if (PP) return PP;
  PP = {};
  fieldsOf(byName('Holoholo.Rpc', 'PokemonProto')).forEach(function (x) { var n = x.name.replace(/_$/, ''); PP[n.charAt(0).toLowerCase() + n.slice(1)] = x.off; });
  return PP;
}
function pickCandidate(ids) {                 /* first candidate (CP order) at full HP and not in a gym -- the LIVE proto, by id */
  var o = protoOffs();
  for (var i = 0; i < ids.length; i++) {
    try {
      var p = liveProto(ids[i]); if (!p) continue;
      var hp = p.add(o.stamina).readS32(), mx = p.add(o.maxStamina).readS32(), fort = str(p.add(o.deployedFortId).readPointer());
      if (mx > 0 && hp >= mx && !fort && !(M.isMega && callB(M.isMega, p, 'IsMegaEvolved'))) return {p: p, id: String(ids[i]), cp: p.add(o.cp).readS32()};
    } catch (e) {}
  }
  return null;
}

/* ---- attack team + auto-heal: the runner hands over the roster (ids, highest CP first, Slaking and the Gyarados placement
   stock left out); every read resolves the id through the game's own bag (PokemonBagImpl.GetPokemon), so a proto the bag
   replaced after a heal is never used stale ---- */
var IBAG = null, ROSTER = [], HEALX = [], HEAL_N = 12, TEAMP = null, TEAM_AT = 0, ACTIVE = {}, ACTIVE_AT = 0;
var HEALQ = {}, HEAL_AT = 0, HEAL_OFF = {}, HEAL_EMPTY_TOLD = 0, ITEMS_TOLD = false, ITEM = {};
var U64B = Memory.alloc(8), I32B = Memory.alloc(4), I32C = Memory.alloc(4);
var READY = 0.9;                              /* >= 90% HP fights as-is and is not healed (only Max Potions in the bag: no waste on a scratch) */
var WB = EX['il2cpp_gc_wbarrier_set_field'] ? f('il2cpp_gc_wbarrier_set_field', 'void', ['pointer', 'pointer', 'pointer']) : null;
function pbag() {                            /* the live PokemonBagImpl, re-checked by class on every use */
  if (!IBAG || !isA(IBAG, K.ItemBagImpl)) return NULL;
  var b = IBAG.add(O.ibPokeBag).readPointer(); return isA(b, K.PokemonBagImpl) ? b : NULL;
}
function liveProto(id) {
  var b = pbag(); if (b.isNull() || !M.getPokemon) return null;
  U64B.writeU64(new UInt64(String(id)));
  var r = call(M.getPokemon, b, 'GetPokemon', [U64B]);
  return r && !r.isNull() && r.readPointer().equals(K.PokemonProto) ? r : null;
}
function itemCount(it) { if (!isA(IBAG, K.ItemBagImpl)) return 0; I32C.writeS32(it); var r = call(M.itemCount, IBAG, 'GetItemCount', [I32C]); return r && !r.isNull() ? r.add(16).readS32() : 0; }
function usable(p, o) {                       /* can fight: alive, not in a gym, not at a Power Spot, not an egg / bad */
  return p.add(o.stamina).readS32() > 0 && !str(p.add(o.deployedFortId).readPointer()) && !str(p.add(o.deployedStationId).readPointer())
    && !p.add(o.isEgg).readU8() && !p.add(o.isBad).readU8();
}
var BUDDY = {id: null, at: 0};
function buddyId() {                          /* the current buddy, from the game's own BuddyPokemonService getter (every 30 s) */
  var now = Date.now(); if (now - BUDDY.at < 30000) return BUDDY.id;
  BUDDY.at = now;
  try { if (M.bWho && isA(BUD.pok, K.BuddyPokemonService)) { var bp = call(M.bWho, BUD.pok, 'BuddyWho');
      if (bp && !bp.isNull()) { var bo = {}; fieldsOf(bcls(bp)).forEach(function (x) { bo[x.name] = x.off; });
        var bid = bp.add(bo.BuddyPokemonId).readU64().toString(); BUDDY.id = bid !== '0' ? bid : null; } } } catch (e) {}
  return BUDDY.id;
}
function pickTeam(n) {                        /* highest CP first among >= half HP, then any HP left; never a fainted one -- the BUDDY last */
  var o = protoOffs(), full = [], part = [], low = [], bud = buddyId();
  for (var i = 0; i < ROSTER.length && full.length < n; i++) {
    try {
      if (bud && ROSTER[i].id === bud) continue;   /* the buddy has its own slot: the last one (the user: its battle heart) */
      var p = liveProto(ROSTER[i].id); if (!p || !usable(p, o)) continue;
      var hp = p.add(o.stamina).readS32(), mx = p.add(o.maxStamina).readS32(), t = {p: p, id: ROSTER[i].id, cp: p.add(o.cp).readS32()};
      var q = HEALQ[ROSTER[i].id];                /* a Max Potion already on its way lands before the battle-start request */
      if (hp * 2 >= mx) full.push(t); else low.push(t);   /* >= half HP: ranked purely by CP (a 5629 at 82% beats a 4000 at 100%) */
    } catch (e) {}
  }
  var t = full.concat(part, low).slice(0, n); t.sort(function (a, b) { return b.cp - a.cp; });
  if (bud) { try { var bp = liveProto(bud);
      if (bp && usable(bp, o)) { t = t.slice(0, n - 1); t.push({p: bp, id: bud, cp: bp.add(o.cp).readS32(), buddy: true}); } } catch (e) {} }
  return t;
}
function chooseItem(hp, mx) {                 /* fainted: Max Revive (full in ONE item), else Revive; hurt: the smallest potion that covers it */
  if (hp <= 0) return itemCount(ITEM.MaxRevive) > 0 ? ITEM.MaxRevive : (itemCount(ITEM.Revive) > 0 ? ITEM.Revive : 0);
  var miss = mx - hp, ladder = [[ITEM.Potion, 20], [ITEM.SuperPotion, 50], [ITEM.HyperPotion, 200], [ITEM.MaxPotion, 1e9]];   /* ponytail: HP per potion from the item settings would be exact */
  for (var i = 0; i < ladder.length; i++) if (miss <= ladder[i][1] && itemCount(ladder[i][0]) > 0) return ladder[i][0];
  for (var j = ladder.length - 1; j >= 0; j--) if (itemCount(ladder[j][0]) > 0) return ladder[j][0];
  return 0;
}
function healTick(now) {                      /* the top of the roster, always: during battles too (never the six fighting) */
  if (!ROSTER.length || !IBAG || !M.useItem || now - HEAL_AT < 400) return;
  HEAL_AT = now;
  if (!IN_BATTLE && now - ACTIVE_AT > 1500 && now - TEAM_AT > 15000) ACTIVE = {};   /* the last battle's six are back in the bag */
  if (IN_BATTLE && !Object.keys(ACTIVE).length) return;       /* a battle whose six we do not know: heal nothing mid-fight */
  if (!ITEMS_TOLD) { ITEMS_TOLD = true; var c = {}; ['Potion', 'SuperPotion', 'HyperPotion', 'MaxPotion', 'Revive', 'MaxRevive', 'GoldenRazzBerry'].forEach(function (n) { if (ITEM[n] !== undefined) c[n] = itemCount(ITEM[n]); }); send({k: 'items', c: c}); }
  var o = protoOffs(), inflight = 0;
  for (var k in HEALQ) { if (now - HEALQ[k].at > 6000) delete HEALQ[k]; else inflight++; }
  var list = ROSTER.slice(0, HEAL_N).concat(HEALX), cap = ROUND ? 1 : 3;   /* a live round: one item request at a time */
  if (HEALX.length && now - (ST.hxAt || 0) > 5000) { ST.hxAt = now;
    var need = HEALX.some(function (r) { var p = liveProto(r.id); return p && p.add(o.stamina).readS32() < p.add(o.maxStamina).readS32(); });
    if (!need) { HEALX = []; send({k: 'batchdone'}); } }   /* the batch is done: no more heals until the next 30 */
  for (var i = 0; i < list.length && inflight < cap; i++) {
    var r = list[i];
    if (ACTIVE[r.id] || (HEAL_OFF[r.id] || 0) > now) continue;
    try {
      var p = liveProto(r.id); if (!p) continue;
      var hp = p.add(o.stamina).readS32(), mx = p.add(o.maxStamina).readS32();
      if (HEALQ[r.id]) { if (hp !== HEALQ[r.id].hp) delete HEALQ[r.id]; continue; }      /* the last item landed */
      if (mx <= 0 || hp >= (r.full ? 1 : READY) * mx || str(p.add(o.deployedFortId).readPointer()) || str(p.add(o.deployedStationId).readPointer())) continue;
      var it = chooseItem(hp, mx);
      if (!it) { if (now - HEAL_EMPTY_TOLD > 300000) { HEAL_EMPTY_TOLD = now; send({k: 'heal', none: true, hp: hp, max: mx, id: r.id}); } return; }
      I32B.writeS32(it); U64B.writeU64(new UInt64(String(r.id)));
      if (!isA(IBAG, K.ItemBagImpl)) return;
      var ok = call(M.useItem, IBAG, 'UseItemOnPokemon', [I32B, U64B]) !== null;
      HEALQ[r.id] = {at: now, hp: hp, item: it}; inflight++;
      if (!ok) HEAL_OFF[r.id] = now + 30000;
      send({k: 'heal', id: r.id, item: ITEM_NAME[it], hp: hp, max: mx, ok: ok, battle: IN_BATTLE});
    } catch (e) {}
  }
}
var ITEM_NAME = {};

/* ---- Golden Razz feeder -- the user's rule (2026-09-25): HIS defenders get a Golden Razz as soon as they are in the last third
   of motivation (one knockout from coming home), wherever the gym is. Gym details by id + the defender's own gym coordinates
   (MapPlaceDetailsService.RequestGymDetailsByIdWithRetries); the reply is read out of its Promise with plain memory reads,
   class-checked at every hop (a finished promise may be collected: no il2cpp call ever touches it after it was created);
   the feed is ItemBagImpl.UseItemOnGymDefender(GoldenRazzBerry, pokemon id, fort id). Tick only -- no hook. ---- */
var FAINT_DUE = 0, GYIDS = [];
function faintTick(now) {                     /* fainted Pokemon among the roster + the placement stock (the batch-revive rule) */
  if (!FAINT_DUE || now < FAINT_DUE || !ROSTER.length) return;
  FAINT_DUE = 0;
  var o = protoOffs(), ids = [];
  ROSTER.map(function (r) { return r.id; }).concat(GYIDS).forEach(function (id) {
    try { var p = liveProto(id); if (p && p.add(o.stamina).readS32() <= 0 && p.add(o.maxStamina).readS32() > 0 && !str(p.add(o.deployedFortId).readPointer())) ids.push(id); } catch (e) {} });
  send({k: 'fainted', n: ids.length, ids: ids});
}
var MATE_ON = true, ZERO_AT = 0.02, FEED_ZONE = null, MATE_RESERVE = 20;   /* teammates fed only above this many berries */
function inFeedZone(lat, lng) {
  if (!FEED_ZONE) return false;
  var dy = (lat - FEED_ZONE.lat) * 111320, dx = (lng - FEED_ZONE.lng) * 111320 * Math.cos(FEED_ZONE.lat * Math.PI / 180);
  return Math.sqrt(dx * dx + dy * dy) <= FEED_ZONE.r;
}
var DEFS = {}, DSVC = null, FEED_ON = true, FEED_AT = 0.34, HOT_FEED_AT = 0.67, FEED_EMPTY = 0, POFF = {}, PLACED = null, PLACED_AT = 0, EMPTY = null;
var LLB = Memory.alloc(16), I32R = Memory.alloc(4), I32G = Memory.alloc(4), U64G = Memory.alloc(8), I32D = Memory.alloc(4);
var DD_OK = false, DD_SLOT = 0xb2e9218, DD_FN = 0x5170c34, DDW = null, DDEP = null, LASTPOS = null;   /* direct deploy (0.429.1 RVAs, validated per use) */
var OBJNEW = EX['il2cpp_object_new'] ? f('il2cpp_object_new', 'pointer', ['pointer']) : null, IL2CPP_BASE = Process.findModuleByName('libil2cpp.so').base;
function directDeploy(fid, pick, now) {       /* the gym screen's own GYM_DEPLOY request, sent from the map */
  if (!DD_OK || !LASTPOS || !OBJNEW || !WB || !isA(DSVC, K.MapPlaceDetailsService)) return false;
  var mi = IL2CPP_BASE.add(DD_SLOT).readPointer();
  if (mi.compare(ptr('0x1000000000')) <= 0 || !Process.findRangeByAddress(mi) || !mi.readPointer().sub(IL2CPP_BASE).equals(ptr(DD_FN))) {
    send({k: 'err', e: 'direct deploy: the send method is not resolved yet (first placement after a launch) -- the gym screen places'}); return false; }
  var mg = GYMS[fid]; if (!mg || !alive(mg) || !mg.readPointer().equals(K.MapGym)) return false;
  var fd = mg.add(O.mgFort).readPointer(); if (fd.isNull()) return false;
  var fs = fd.add(O.fFortId).readPointer(); if (str(fs) !== fid) return false;
  var h = DSVC.add(O.mpdsRpc).readPointer(); if (h.isNull()) return false;
  var req = OBJNEW(K.GymDeployProto); if (req.isNull()) return false;
  if (call(M.gdpCtor, req, 'GymDeployProto()') === null) return false;
  WB(req, req.add(O.gdpFort), fs); req.add(O.gdpPoke).writeU64(new UInt64(String(pick.id)));
  req.add(O.gdpLat).writeDouble(LASTPOS[0]); req.add(O.gdpLng).writeDouble(LASTPOS[1]);
  I32D.writeS32(155);                         /* Method.GYM_DEPLOY, as cagd passes it */
  var pr = call(mi, NULL, 'Send(GYM_DEPLOY)', [h, I32D, req]);
  if (pr === null || pr.isNull()) return false;
  var po = promiseOffs(pr); if (!po) return false;
  DDEP = {pr: pr, o: po, at: now, fid: fid};
  return true;
}
function ddTick(now) {                        /* after a drilled gym's VICTORY: scan it every 0.5 s, deploy the moment the server says EMPTY */
  if (DDEP) {
    var r = promiseRead(DDEP); if (r === null && now - DDEP.at < 15000) return;
    var res = null; try { if (r && r.val && !r.val.isNull() && r.val.readPointer().equals(K.GymDeployOutProto)) res = r.val.add(O.gdoRes).readS32(); } catch (e) {}
    var rn = res === null ? (r && r.err ? r.err : 'no reply') : String(LIT.deployResName[res] || res);
    if (res !== 1 && PLACED && PLACED.direct) PLACED = null;   /* refused / no answer: the gym-screen path may still place */
    if (res === 1 && AUTODEP && AUTODEP.fid === DDEP.fid) AUTODEP = null;   /* placed: the gym-screen path must not deploy a 2nd (ErrorAlreadyHasPokemonOnFort, 04:14:38) */
    send({k: 'deployresult', res: rn + ' (direct, ' + (now - DDEP.at) + ' ms)', ok: res === 1});
    DDEP = null; return;
  }
  if (!DDW) return;
  if (now > DDW.until || PLACED || !AUTODEP || AUTODEP.fid !== DDW.fid) { DDW = null; return; }
  var sv = SCAN[DDW.fid];
  if (sv && sv.at > DDW.t0 && sv.n === 0 && sv.team === 0) {
    var fid = DDW.fid, t0 = DDW.t0; DDW = null;
    var pick = (AUTODEP.cands && AUTODEP.cands.length) ? pickCandidate(AUTODEP.cands) : null;
    if (pick && directDeploy(fid, pick, now)) {
      PLACED = {id: pick.id, fid: fid, cp: pick.cp, at: now, direct: true};
      send({k: 'autoplace', fid: fid, id: pick.id, cp: pick.cp, ms: now, direct: true, afterVictory: now - t0});
    }
    return;
  }
  if (now >= DDW.next && !SCANREQ[DDW.fid] && SCANQ.indexOf(DDW.fid) < 0) { DDW.next = now + 500; SCANQ.unshift(DDW.fid); }
}
function promiseOffs(pr) {                    /* THIS promise class's own offsets, read while the object is certainly alive */
  var k = pr.readPointer(), key = String(k); if (POFF[key] !== undefined) return POFF[key];
  var o = {k: k}; fieldsOf(klassOf(pr)).forEach(function (x) { if (x.name === 'completeCalled') o.done = x.off; if (x.name === 'errorCalled') o.err = x.off;
    if (x.name === 'completedValue') o.val = x.off; if (x.name === 'errorValue') o.errv = x.off; });
  POFF[key] = (o.done === undefined || o.val === undefined || o.err === undefined) ? null : o;
  if (!POFF[key]) send({k: 'err', e: 'feeder: not a Promise<T>: ' + nameOf(k)});
  return POFF[key];
}
function promiseRead(q) {                     /* null = still pending */
  if (!q.pr.readPointer().equals(q.o.k)) return {gone: true};
  if (q.pr.add(q.o.err).readU8()) {
    var ev = q.o.errv !== undefined ? q.pr.add(q.o.errv).readPointer() : NULL, t = str(ev);
    if (!t && !ev.isNull() && O.excMsg >= 0) { try { t = str(ev.add(O.excMsg).readPointer()); } catch (e) {} }
    return {err: t || 'error'};
  }
  if (!q.pr.add(q.o.done).readU8()) return null;
  return {val: q.pr.add(q.o.val).readPointer()};
}
function readDefenders(mpd) {                 /* MapPlaceDetails -> {fid, team, inBattle, list: [{id, mot, cp}]} -- plain reads */
  if (mpd.isNull() || !mpd.readPointer().equals(K.MapPlaceDetails)) return null;
  var gd = mpd.add(O.mpdGym).readPointer(); if (gd.isNull()) return null;
  return readStatus(gd.add(O.mgdStatus).readPointer());
}
function readStatus(st) {                     /* GymStatusAndDefendersProto -> {fid, team, inBattle, list} */
  if (st.isNull() || !st.readPointer().equals(K.GymStatusAndDefendersProto)) return null;
  var fort = st.add(O.sadFort).readPointer(), rf = st.add(O.sadDef).readPointer(), idOff = protoOffs().id;
  var out = {fid: fort.isNull() ? null : str(fort.add(O.fFortId).readPointer()), team: fort.isNull() ? -1 : fort.add(O.fTeam).readS32(),
    mod: fort.isNull() || O.fMod === undefined ? 0 : Number(fort.add(O.fMod).readS64()),
    inBattle: !fort.isNull() && !!fort.add(O.fInBattle).readU8(), list: []};
  if (rf.isNull()) return out;
  var arr = rf.add(O.rfArr).readPointer(), n = rf.add(O.rfCount).readS32();
  for (var i = 0; i < n && i < 10 && !arr.isNull(); i++) {
    var d = arr.add(32 + i * PS).readPointer(); if (d.isNull()) continue;
    var mp = d.add(O.gdMot).readPointer(); if (mp.isNull()) continue;
    var p = mp.add(O.mpPoke).readPointer();
    var gold = -1, cd = O.mpCool >= 0 ? Number(mp.add(O.mpCool).readS64()) : -1, food = {};
    try { var fl = O.mpFood >= 0 ? mp.add(O.mpFood).readPointer() : NULL;   /* the game's own: what each berry would add NOW */
      if (!fl.isNull()) { var fa = fl.add(O.rfArr).readPointer(), fn = fl.add(O.rfCount).readS32();
        for (var j = 0; j < fn && j < 16 && !fa.isNull(); j++) { var fv = fa.add(32 + j * PS).readPointer();
          if (fv.isNull()) continue;
          var fit = fv.add(O.fvItem).readS32(), fmot = fv.add(O.fvMot).readFloat(); food[fit] = fmot;
          if (fit === ITEM.GoldenRazzBerry) gold = fmot; } } } catch (e) {}
    out.list.push({id: p.isNull() ? '' : p.add(idOff).readU64().toString(), mot: mp.add(O.mpMot).readDouble(), cp: mp.add(O.mpCp).readS32(),
      max: O.mpCpDep >= 0 ? mp.add(O.mpCpDep).readS32() : 0, gold: gold, cd: cd, food: food,
      dms: O.mpDeploy >= 0 ? Number(mp.add(O.mpDeploy).readS64()) : 0, bv: O.mpBerry >= 0 ? mp.add(O.mpBerry).readFloat() : -1});
  }
  return out;
}
function askDetails(id, d, now) {             /* the gym our defender sits in, by id + its own coordinates (works from anywhere) */
  var p = liveProto(id); if (!p) { d.nextAt = now + 60000; return false; }
  var o = protoOffs(), fs = p.add(o.deployedFortId).readPointer();
  if (!str(fs)) { delete DEFS[id]; send({k: 'feed', what: 'home', id: id, fid: d.fid || null}); return false; }
  d.fid = str(fs);
  var glat = p.add(o.deployedGymLatDegree).readDouble(), glng = p.add(o.deployedGymLngDegree).readDouble();
  if (FEED_ZONE) {                            /* the user: berries only for the gyms in this area -- the others are not even polled */
    var dy = (glat - FEED_ZONE.lat) * 111320, dx = (glng - FEED_ZONE.lng) * 111320 * Math.cos(FEED_ZONE.lat * Math.PI / 180);
    if (Math.sqrt(dx * dx + dy * dy) > FEED_ZONE.r) { if (!d.outTold) { d.outTold = true; send({k: 'feed', what: 'outside', id: id, fid: d.fid}); } d.nextAt = now + 300000; return false; }
    d.outTold = false;
  }
  LLB.writeDouble(glat); LLB.add(8).writeDouble(glng);
  I32R.writeS32(1);
  if (!isA(DSVC, K.MapPlaceDetailsService)) { d.nextAt = now + 60000; return false; }
  var pr = call(M.gymDetails, DSVC, 'RequestGymDetails', [fs, LLB, EMPTY, I32R]);
  if (pr === null || pr.isNull()) { d.nextAt = now + 60000; return false; }
  var po = promiseOffs(pr); if (!po) { FEED_ON = false; return false; }
  d.req = {pr: pr, o: po, at: now};
  return true;
}
var GHIST = {}, SIEGE_AT = 0.67, SIEGE_TOLD = {};   /* fort id -> [[t, in battle], ...] from every details reading of that gym */
function gymSeen(fid, ib, now) {
  var h = GHIST[fid] = (GHIST[fid] || []).filter(function (x) { return now - x[0] <= 90000; }); h.push([now, ib ? 1 : 0]);
}
function siegeLine(fid, now) {                /* long or near-continuous battles: gaps are rare -> use ANY gap once at 2/3 */
  var h = GHIST[fid]; if (!h || h.length < 3) return 0;
  /* the battle stretch just before the latest reading lasted >= 40 s (tuned on 73adb570's hour: 13 of 176 gaps, and it
     catches the one gap that would have saved Gyarados 3211 at 03:00; a 'busy fraction' rule fired on 33-62 gaps) */
  var i = h.length - 2, end = (i >= 0 && h[i][1]) ? h[i][0] : 0, start = end;
  while (i >= 0 && h[i][1]) { start = h[i][0]; i--; }
  var on = end > 0 && end - start >= 40000;
  if (on && now - (SIEGE_TOLD[fid] || 0) > 120000) { SIEGE_TOLD[fid] = now; send({k: 'feed', what: 'siege', fid: fid, line: SIEGE_AT}); }
  return on ? SIEGE_AT : 0;
}
var SCANQ = [], SCAN = {}, SCANREQ = {};    /* the runner's park scan: queued fort ids / verified results / requests in flight */
function scanTick(now) {
  if (!DSVC || !M.gymDetails || !isA(DSVC, K.MapPlaceDetailsService)) return;
  for (var f in SCANREQ) {                    /* replies: the gym's TRUE state, whatever the map record says */
    try {
      var q = SCANREQ[f], r = promiseRead(q);
      if (r === null) { if (now - q.at > 15000) delete SCANREQ[f]; continue; }
      delete SCANREQ[f];
      if (r.gone || r.err) continue;
      var g = readDefenders(r.val); if (!g || g.fid !== f) continue;
      var cp = 0, ours = 0; g.list.forEach(function (x) { cp += x.cp; if (DEFS[x.id]) ours++; });
      gymSeen(f, g.inBattle, now);
      var gnm = ''; try { if (O.mpdName !== undefined) gnm = str(r.val.add(O.mpdName).readPointer()) || ''; } catch (e) {}
      SCAN[f] = {team: g.team, ib: g.inBattle ? 1 : 0, n: g.list.length, cp: cp, ours: ours, at: now, name: gnm,
                 mots: g.list.map(function (x) { return Math.round(x.mot * 100); })};
    } catch (e) { delete SCANREQ[f]; }
  }
  var inflight = Object.keys(SCANREQ).length;
  while (SCANQ.length && inflight < 2) {
    var fid = SCANQ.shift(), mg = GYMS[fid];
    try {
      if (!mg || !alive(mg) || !mg.readPointer().equals(K.MapGym)) continue;
      var fd = mg.add(O.mgFort).readPointer(); if (fd.isNull()) continue;
      var fs = fd.add(O.fFortId).readPointer(); if (str(fs) !== fid) continue;
      LLB.writeDouble(fd.add(O.fLat).readDouble()); LLB.add(8).writeDouble(fd.add(O.fLng).readDouble()); I32R.writeS32(1);
      var pr = call(M.gymDetails, DSVC, 'RequestGymDetails(scan)', [fs, LLB, EMPTY, I32R]);
      if (pr === null || pr.isNull()) continue;
      var po = promiseOffs(pr); if (!po) continue;
      SCANREQ[fid] = {pr: pr, o: po, at: now}; inflight++;
    } catch (e) {}
  }
}
var MAPIB = {};                               /* fort id -> [map IsInBattle, when we saw it change] */
function mapBusyAfter(fid, t) { var v = MAPIB[fid]; return !!(v && v[0] && v[1] > t); }   /* the map turned 'in battle' AFTER time t */
function mapBusy(fid, now) {                  /* the map's own fort record (fresher than the cached gym info) says: in battle */
  var v = GTEAM[fid]; return !!(v && now - v[1] < 5000 && v[6]);
}
var FEED_LAST = 0, FEEDLOG = [], FUTILE_UNTIL = {}, FUTILE_BELOW = 60;   /* futility cutoff only while Golden Razz <= 60 */               /* every feed's time: the server throttles at ~10 per 5 min */
var TOPUP_ON = false, TOPUP = null, TOPUP_LAST = 0, TOPUP_BACKOFF = 0, TOPUP_RESERVE = 30, TOPUP_N = 0;
var TOPUP_BERRIES = ['RazzBerry', 'NanabBerry', 'PinapBerry', 'BlukBerry', 'WeparBerry'];   /* never the golden ones */
function topUp(id, d, g, now, rqAt) {         /* Berry Master: a regular berry to the lowest defender in this gym, quiet gaps only */
  if (!TOPUP_ON || TOPUP || g.inBattle || mapBusyAfter(d.fid, rqAt || 0)) return;
  if (now - TOPUP_LAST < 20000 || now < TOPUP_BACKOFF || now - FEED_LAST < 3000) return;
  FEEDLOG = FEEDLOG.filter(function (t) { return now - t < 300000; });
  if (FEEDLOG.length >= 6) return;            /* 4 of the ~10 per 5 min always stay free for Golden Razz rescues */
  for (var k in DEFS) { var dd = DEFS[k]; if (dd && (dd.fr || dd.await || (dd.mot !== undefined && dd.mot <= Math.max(FEED_AT, HOT_FEED_AT) + 0.05))) return; }
  for (var mk in MATES) { var mm = MATES[mk]; if (mm && (mm.fr || mm.low)) return; }
  var cand = g.list.filter(function (x) { return x.id && x.mot < 0.97 && x.food; }).sort(function (a, b) { return a.mot - b.mot; });
  if (!cand.length) return;
  var t = cand[0], best = null;
  TOPUP_BERRIES.forEach(function (nm) { var it = ITEM[nm]; if (it === undefined || !(t.food[it] > 0.001)) return;
    var c = itemCount(it); if (c > TOPUP_RESERVE && (!best || c > best.c)) best = {it: it, nm: nm, c: c}; });
  if (!best) return;
  var p = liveProto(id); if (!p) return;
  var fs = p.add(protoOffs().deployedFortId).readPointer(); if (!str(fs) || str(fs) !== d.fid) return;
  if (!isA(IBAG, K.ItemBagImpl)) return;
  I32G.writeS32(best.it); U64G.writeU64(new UInt64(String(t.id)));
  FEED_LAST = now; TOPUP_LAST = now; FEEDLOG.push(now);
  var fr = call(M.feed, IBAG, 'UseItemOnGymDefender(top-up)', [I32G, U64G, fs]);
  if (fr !== null && !fr.isNull()) { var po = promiseOffs(fr); if (po) TOPUP = {pr: fr, o: po, at: now, fid: d.fid}; }
  send({k: 'feed', what: 'topup', fid: d.fid, berry: best.nm, mot: t.mot, mine: !!DEFS[t.id], left: best.c - 1});
}
function topUpReply(now) {                    /* every frame: the top-up's reply */
  if (!TOPUP) return;
  var r = promiseRead(TOPUP); if (r === null && now - TOPUP.at < 20000) return;
  var res = null, sdx = null;
  try { if (r && r.val && !r.val.isNull() && r.val.readPointer().equals(K.GymFeedPokemonOutProto)) { res = r.val.add(O.gfoRes).readS32();
    if (O.gfoDust >= 0) sdx = [r.val.add(O.gfoDust).readS32(), r.val.add(O.gfoXp).readS32()]; } } catch (e) {}
  var rn = res === null ? (r && r.err ? r.err : 'no reply') : String(LIT.feedResName[res] || res), good = /success/i.test(rn);
  if (good) TOPUP_N++;
  else if (rn !== 'no reply') { TOPUP_BACKOFF = now + 300000;
    try { var cc = Number(r.val.add(O.gfoCool).readS64()); if (cc > Date.now()) TOPUP_BACKOFF = now + (cc - Date.now()); } catch (e) {} }
  send({k: 'feed', what: 'topupresult', fid: TOPUP.fid, res: rn, ok: good, n: TOPUP_N, sdx: sdx});
  TOPUP = null;
}                            /* two feeds in the same instant: the server answers the 2nd with ErrorTooFast */
function feedNow(id, d, me, now) {            /* ONE Golden Razz on OUR defender, remote or not */
  if (now - FEED_LAST < 1500) { d.nextAt = now + 800; return; }
  var have = itemCount(ITEM.GoldenRazzBerry);
  if (have <= 0) { if (now - FEED_EMPTY > 600000) { FEED_EMPTY = now; send({k: 'feed', what: 'none', id: id, fid: d.fid, mot: me.mot}); } return; }
  var p = liveProto(id); if (!p) return;
  var fs = p.add(protoOffs().deployedFortId).readPointer(); if (!str(fs) || str(fs) !== d.fid) return;
  I32G.writeS32(ITEM.GoldenRazzBerry); U64G.writeU64(new UInt64(String(id)));
  if (!isA(IBAG, K.ItemBagImpl)) return;
  FEED_LAST = now; FEEDLOG.push(now);
  d.tsBefore = GRAPH && GRAPH.inv ? invTs(GRAPH.inv) : -1;   /* the live-graph tripwire's baseline */
  var fr = call(M.feed, IBAG, 'UseItemOnGymDefender', [I32G, U64G, fs]);
  d.fedAt = now; d.fedMot = me.mot; d.nextAt = now + 6000;
  /* a details reply whose gym state (LastModifiedMs) predates this feed is the server's cache, not news */
  if (fr !== null && !fr.isNull()) { var po = promiseOffs(fr); if (po) d.fr = {pr: fr, o: po, at: now}; }
  send({k: 'feed', what: 'fed', id: id, fid: d.fid, mot: me.mot, cp: me.cp, ok: fr !== null, left: have - 1});
  study({src: 'feed', who: 'own', fid: d.fid, id: id.slice(-6), mot: me.mot, map: mapRec(d.fid, now), quietFor: d.quietAt ? now - d.quietAt : -1});
}
var STUDY = false;                          /* --study: the game's own freshness signals, one record per event */
function study(o) { if (!STUDY) return; o.k = 'study'; o.t = Date.now(); try { send(o); } catch (e) {} }
function mapRec(fid, now) { var v = GTEAM[fid]; return v ? [v[6], v[10] || 0, now - v[1]] : null; }   /* [inBattle, LastModifiedMs, age of our read] */
function replyRec(val) {                      /* GymFeedPokemonOutProto: rewards + the reply's own fort state (plain reads) */
  var o = {};
  try { if (O.gfoDust >= 0) o.sd = val.add(O.gfoDust).readS32(); if (O.gfoXp >= 0) o.xp = val.add(O.gfoXp).readS32();
    o.cool = Number(val.add(O.gfoCool).readS64());
    var gs = readStatus(val.add(O.gfoStatus).readPointer()); if (gs) { o.mod = gs.mod; o.ib = gs.inBattle ? 1 : 0;
      o.list = gs.list.map(function (x) { return [x.id.slice(-6), Math.round(x.mot * 1000) / 1000, x.cp]; }); } } catch (e) {}
  return o;
}
var MATES = {};                              /* fort id -> {id, fedAt, fr, await, okAt, coolUntil}: the one teammate we keep fed there */
function mateReplies(now) {                   /* every frame: a teammate feed's reply, before the game drops it */
  for (var fk in MATES) {
    var m = MATES[fk]; if (!m || !m.fr) continue;
    try {
      var r = promiseRead(m.fr);
      if (r === null && now - m.fr.at < 20000) continue;
      var res = null, after = null;
      if (r && r.val && !r.val.isNull() && r.val.readPointer().equals(K.GymFeedPokemonOutProto)) res = r.val.add(O.gfoRes).readS32();
      var rn = res === null ? (r && r.err ? r.err : 'no reply') : String(LIT.feedResName[res] || res), good = /success/i.test(rn);
      if (good || rn === 'no reply') { m.await = now; m.okAt = m.fedAt;   /* no answer = assume it landed: never a 2nd berry on a guess */
        try { if (good) { var gs = readStatus(r.val.add(O.gfoStatus).readPointer()), mm = gs && gs.list.filter(function (x) { return x.id === m.id; })[0];
          if (mm) { after = mm.mot; if (mm.mot > (m.fedMot !== undefined ? m.fedMot : FEED_AT) + 0.05) m.await = 0; else { m.await = 0; m.okAt = 0; good = false; rn = 'Success but not applied (gym in battle)'; } } } } catch (e) {} }
      else { m.fedAt = 0; try { var cc = Number(r.val.add(O.gfoCool).readS64()); if (cc > Date.now()) m.coolUntil = cc; } catch (e) {} }
      if (/not applied/.test(rn)) { m.misses = (m.misses || []).filter(function (t) { return Date.now() - t < 60000; }).concat([Date.now()]);
        m.coolUntil = Date.now() + (m.misses.length >= 2 ? 20000 : 1500); }
      var msx = null; try { if (r && r.val && !r.val.isNull() && O.gfoDust >= 0) msx = [r.val.add(O.gfoDust).readS32(), r.val.add(O.gfoXp).readS32()]; } catch (e) {}
      send({k: 'feed', what: 'materesult', fid: fk, res: rn, ok: good, after: after, max: m.max || 0, sdx: msx});
      if (STUDY) { var mr = (r && r.val && !r.val.isNull()) ? replyRec(r.val) : {}; mr.src = 'reply'; mr.who = 'mate'; mr.fid = fk; mr.res = rn; mr.lat = now - m.fr.at; mr.map = mapRec(fk, now); study(mr); }
    } catch (e) {}
    m.fr = null;
  }
}
function feedMate(id, d, g, now, rqAt, ownLow, mline) {
  if (!MATE_ON) return;
  var others = g.list.filter(function (x) { return x.id && !DEFS[x.id]; });   /* not one of ours */
  if (!others.length) { if (MATES[d.fid]) MATES[d.fid].low = false; return; }
  var mate = others.reduce(function (a, b) { return (b.max || b.cp) > (a.max || a.cp) ? b : a; });   /* highest deployed CP */
  var m = MATES[d.fid]; if (!m || m.id !== mate.id) m = MATES[d.fid] = {id: mate.id}; m.max = mate.max;
  mline = mline || FEED_AT;
  m.low = mate.mot <= mline;                     /* the gym is polled fast while the teammate is low, not only while ours is */
  if (m.fr) return;                          /* its reply is read every frame by mateReplies() */
  if (m.okAt && g.mod && g.mod < m.okAt - 1500) return;                         /* the server's cached pre-feed state */
  if (m.await && (mate.mot > mline + 0.1 || now - m.await > 120000)) m.await = 0;
  if (mate.mot > mline || m.await || (m.coolUntil && Date.now() < m.coolUntil) || now - (m.fedAt || 0) < 8000) return;
  if (m.mot !== undefined && mate.mot < m.mot - 0.2) m.koAt = now;   /* its knockout reading */
  m.mot = mate.mot;
  if (g.inBattle || mapBusyAfter(d.fid, rqAt || 0)) { m.quietAt = 0; return; }   /* mid-battle feeds are taken and not applied */
  if (now - (m.koAt || 0) < 900) return;          /* not in the reading that showed its knockout (18% wasted there) */
  if (ownLow || now - FEED_LAST < 1500) return;   /* his own defender goes first in this gap; the teammate at the next reading */
  if (!m.quietAt) m.quietAt = now;               /* (kept for the study record; the first fresh quiet reading is the gap) */
  if (mate.gold >= 0 && mate.gold < 0.05) return;   /* the game says a Golden Razz would add nothing to it now */
  var have = itemCount(ITEM.GoldenRazzBerry);
  if (have <= MATE_RESERVE) return;              /* the last berries are kept for his own defenders */
  var p = liveProto(id); if (!p) return;
  var fs = p.add(protoOffs().deployedFortId).readPointer(); if (!str(fs) || str(fs) !== d.fid) return;   /* OUR defender's gym = the mate's gym */
  if (!isA(IBAG, K.ItemBagImpl)) return;
  I32G.writeS32(ITEM.GoldenRazzBerry); U64G.writeU64(new UInt64(String(mate.id)));
  FEED_LAST = now; FEEDLOG.push(now);
  var fr = call(M.feed, IBAG, 'UseItemOnGymDefender(teammate)', [I32G, U64G, fs]);
  m.fedAt = now; m.fedMot = mate.mot;
  if (fr !== null && !fr.isNull()) { var po = promiseOffs(fr); if (po) m.fr = {pr: fr, o: po, at: now}; }
  send({k: 'feed', what: 'fedmate', fid: d.fid, mot: mate.mot, cp: mate.cp, max: mate.max, ok: fr !== null, left: have - 1});
  study({src: 'feed', who: 'mate', fid: d.fid, id: String(mate.id).slice(-6), mot: mate.mot, map: mapRec(d.fid, now), quietFor: m.quietAt ? now - m.quietAt : -1});
}
function feedTick(now) {
  if (GWATCH && now - GWATCH.at > 120000 && now - (GWATCH.chk || 0) > 5000) {   /* a server-confirmed berry use must reach the record we read */
    GWATCH.chk = now; var gt = invTs(GRAPH.inv);
    if (gt > GWATCH.ts) GWATCH = null;                              /* it did: the graph we read is live */
    else if (gt > 0 && now - gt > 600000) {                         /* and NOTHING reached it for 10 min either (age alone is only normal quiet) */
      FEED_ON = false;
      send({k: 'graph', stale: true, ts: gt, was: GWATCH.ts, secs: Math.round((now - GWATCH.at) / 1000), age: Math.round((now - gt) / 1000)});
      GWATCH = null;
    }
  }
  if (!FEED_ON || !DSVC || !M.feed || !IBAG || now - (ST.feedAt || 0) < 250) return;
  ST.feedAt = now;
  var ids = Object.keys(DEFS), pending = 0;
  ids.forEach(function (id) { if (DEFS[id].req) pending++; });
  for (var i = 0; i < ids.length; i++) {
    var id = ids[i], d = DEFS[id]; if (!d) continue;
    try {
      if (d.fr) {                             /* the feed's own reply: result + rewards */
        var fr = promiseRead(d.fr);
        if (fr !== null || now - d.fr.at > 20000) {
          var res = null;
          if (fr && fr.val && !fr.val.isNull() && fr.val.readPointer().equals(K.GymFeedPokemonOutProto)) res = fr.val.add(O.gfoRes).readS32();
          var rn = res === null ? (fr && fr.err ? fr.err : 'no reply') : String(LIT.feedResName[res] || res), good = /success/i.test(rn), after = null;
          if (good) { d.await = now; d.okAt = d.fedAt || now;                /* no second berry until a reading confirms this one (gym info is cached server-side) */
            try { var gs = readStatus(fr.val.add(O.gfoStatus).readPointer()), mine = gs && gs.list.filter(function (x) { return x.id === id; })[0];
              if (mine) { after = mine.mot; if (mine.mot > (d.fedMot !== undefined ? d.fedMot : FEED_AT) + 0.05) d.await = 0; else { d.await = 0; d.okAt = 0; good = false; rn = 'Success but not applied (gym in battle)'; } d.mot = mine.mot; } } catch (e) {} }
          var sdx = null; try { if (fr && fr.val && !fr.val.isNull() && O.gfoDust >= 0) sdx = [fr.val.add(O.gfoDust).readS32(), fr.val.add(O.gfoXp).readS32()]; } catch (e) {}
          if (good && GRAPH && GRAPH.inv && !GWATCH && d.tsBefore > 0) GWATCH = {at: now, ts: d.tsBefore};
          if (good) { d.okList = (d.okList || []).concat([now]).slice(-3);
            if (d.okList.length >= 3 && now - d.okList[0] < 300000 && itemCount(ITEM.GoldenRazzBerry) <= FUTILE_BELOW) {
              FUTILE_UNTIL[id] = now + 600000; d.okList = [];
              send({k: 'feed', what: 'futile', id: id, fid: d.fid, span: now - (d.okList0 || now), left: itemCount(ITEM.GoldenRazzBerry)}); } }
          send({k: 'feed', what: 'result', id: id, fid: d.fid, res: rn, ok: good, after: after, sdx: sdx});
          if (STUDY) { var rr = (fr && fr.val && !fr.val.isNull()) ? replyRec(fr.val) : {}; rr.src = 'reply'; rr.who = 'own'; rr.fid = d.fid; rr.res = rn; rr.lat = now - d.fr.at; rr.map = mapRec(d.fid, now); study(rr); }
          if (!good && rn === 'no reply') { d.await = now; d.okAt = d.fedAt || now; }   /* no answer = assume it landed: never a 2nd berry on a guess */
          else if (!good) {                       /* refused: 'too frequent' has a server cooldown -- wait for it, try nothing before */
            d.fedAt = 0; d.nextAt = now + 2500;
            if (/not applied/.test(rn)) { d.misses = (d.misses || []).filter(function (t) { return now - t < 60000; }).concat([now]);
              d.coolUntil = Date.now() + (d.misses.length >= 2 ? 20000 : 1500); }   /* a miss: retry at the next quiet reading; 2 in 60 s: 20 s */
            try { var cc = Number(fr.val.add(O.gfoCool).readS64()); if (cc > Date.now()) { d.coolUntil = cc; send({k: 'feed', what: 'cooldown', id: id, fid: d.fid, until: cc, res: rn}); } } catch (e) {}
          }
          d.fr = null;
        }
      }
      if (d.req) {                            /* a details request in flight */
        var r = promiseRead(d.req);
        if (r === null) { if (now - d.req.at > 20000) { d.req = null; d.nextAt = now + 30000; } continue; }
        var rqAt = d.req.at; d.req = null;
        if (r.gone || r.err) { d.nextAt = now + 30000; if (r.err && (d.errs = (d.errs || 0) + 1) <= 3) send({k: 'feed', what: 'details', id: id, fid: d.fid, err: r.err}); continue; }
        var g = readDefenders(r.val);
        if (g && STUDY) study({src: 'details', fid: g.fid, id: id.slice(-6), lat: now - rqAt, mod: g.mod, ib: g.inBattle ? 1 : 0, map: mapRec(g.fid, now),
          list: g.list.map(function (x) { return [x.id.slice(-6), Math.round(x.mot * 1000) / 1000, x.cp, x.dms, Math.round(x.bv * 1000) / 1000, x.cd]; })});
        if (!g || g.fid !== d.fid) { d.nextAt = now + 30000; continue; }
        gymSeen(g.fid, g.inBattle, now);
        var me = g.list.filter(function (x) { return x.id === id; })[0];
        if (!me) { d.nextAt = now + 15000; d.miss = (d.miss || 0) + 1; if (d.miss >= 2) { delete DEFS[id]; send({k: 'feed', what: 'home', id: id, fid: d.fid}); } continue; }
        if (d.okAt && g.mod && g.mod < d.okAt - 1500) { d.nextAt = now + 4000; continue; }   /* gym state from before our last good feed: cached */
        if (g.inBattle) d.battleAt = now;
        if (d.mot !== undefined && me.mot < d.mot - 0.04) d.dropAt = now;
        if (d.mot === undefined && me.mot < 0.99) d.dropAt = now;   /* already hurt at its first reading: it is being attacked */
        if (d.mot !== undefined && me.mot < d.mot - 0.2) { d.losses = (d.losses || []).concat([now]).slice(-3); d.gapFrom = 0; d.koAt = now; }   /* a knockout */
        if (!g.inBattle && !d.gapFrom) d.gapFrom = now;                                   /* a quiet gap began */
        if (g.inBattle) d.quietAt = 0; else if (!d.quietAt) d.quietAt = now;
        if (g.inBattle && d.gapFrom) { d.gaps = (d.gaps || []).concat([now - d.gapFrom]).slice(-2); d.gapFrom = 0; }
        var sl = siegeLine(d.fid, now);
        var ownLow = me.mot <= Math.max(FEED_AT, HOT_FEED_AT, sl) && !d.await && !d.fr && !(d.coolUntil && Date.now() < d.coolUntil);
        try { feedMate(id, d, g, now, rqAt, ownLow, Math.max(FEED_AT, sl)); } catch (e) {}   /* the strongest teammate in this gym: same rules */
        if (!ownLow) { try { topUp(id, d, g, now, rqAt); } catch (e) {} }   /* Berry Master: regular berries in quiet gaps */
        d.miss = 0; d.mot = me.mot; d.inBattle = g.inBattle;
        var hot = now - (d.battleAt || 0) < 300000 || now - (d.dropAt || 0) < 300000;   /* attacked in the last 5 min: stay on it */
        d.nextAt = now + (hot ? 4000 : (me.mot < 0.67 ? 6000 : 15000));   /* a battle takes >= 10 s: 15 s never misses two knockouts */
        if (MATE_ON && MATES[d.fid] && MATES[d.fid].low && MATES[d.fid].id) d.nextAt = Math.min(d.nextAt, now + 1200);
        var line = Math.max(hot ? HOT_FEED_AT : FEED_AT, sl);   /* the third -- or 2/3 in a siege (gaps are rare: use any) */
        if (me.gold >= 0 && me.gold < 0.05 && me.mot <= line) {                          /* the game says a Golden Razz would add nothing now */
          if (now - (d.goldTold || 0) > 60000) { d.goldTold = now; send({k: 'feed', what: 'noallow', id: id, fid: d.fid, mot: me.mot, gold: me.gold, cd: me.cd}); }
          d.nextAt = now + 10000; continue; }
        if (!d.limTold && me.gold >= 0) { d.limTold = true; send({k: 'feed', what: 'limits', id: id, fid: d.fid, gold: me.gold, cd: me.cd}); }
        if (d.await && (me.mot > line + 0.1 || now - d.await > 120000)) d.await = 0;   /* the feed is confirmed (or old): armed again */
        if (me.mot <= line && d.await) { d.nextAt = now + 5000; continue; }          /* a stale reply of the pre-feed state: never a 2nd berry */
        if (me.mot <= line) {
          d.nextAt = now + 1200;
          if (d.coolUntil && Date.now() < d.coolUntil) continue;                   /* the server's feed cooldown: nothing before it ends */
          if (FUTILE_UNTIL[id] && now < FUTILE_UNTIL[id]) { d.nextAt = now + 10000; continue; }   /* a futile siege: berries saved */
          if (!g.inBattle && !mapBusyAfter(d.fid, rqAt) && now - (d.koAt || 0) > 900) {   /* the first quiet reading AFTER its knockout reading */
            d.lowSince = 0; if (!d.fr && now - (d.fedAt || 0) > 8000) feedNow(id, d, me, now); }
          else {                                    /* in battle: a berry now is taken but not applied -- watch for the battle's end */
            d.lowSince = d.lowSince || now;
            if (now - (d.waitTold || 0) > 30000) { d.waitTold = now; send({k: 'feed', what: 'wait', id: id, fid: d.fid, mot: me.mot, cp: me.cp}); }
          }
          continue;
        }
        if (d.told === undefined || Math.abs(d.told - me.mot) >= 0.1 || g.inBattle !== d.toldBattle) {
          d.told = me.mot; d.toldBattle = g.inBattle;
          send({k: 'feed', what: 'mot', id: id, fid: d.fid, mot: me.mot, cp: me.cp, inBattle: g.inBattle, n: g.list.length}); }
        continue;
      }
      if (now >= (d.nextAt || 0) && pending < (ROUND ? 1 : 3) && askDetails(id, d, now)) pending++;
    } catch (e) { d.req = null; d.fr = null; d.nextAt = now + 60000; if ((ST.feedErr = (ST.feedErr || 0) + 1) <= 10) send({k: 'err', e: 'feeder ' + e}); }
  }
}
function placedTick(now) {                    /* our deploy request, confirmed by the Pokemon's own deployedFortId */
  if (!PLACED || now - PLACED_AT < 300) return;
  PLACED_AT = now;
  var p = liveProto(PLACED.id), f = p ? str(p.add(protoOffs().deployedFortId).readPointer()) : null;
  if (f && f === PLACED.fid) {
    send({k: 'placed', fid: PLACED.fid, id: PLACED.id, cp: PLACED.cp, ok: true, ms: now - PLACED.at});
    if (!DEFS[PLACED.id]) DEFS[PLACED.id] = {nextAt: now + 30000};
    PLACED = null;
  } else if (now - PLACED.at > 15000) { send({k: 'placed', fid: PLACED.fid, id: PLACED.id, ok: false}); PLACED = null; }
}
var POPUPS = ['GymBadgeAwardGuiController', 'BadgeAwardGuiController', 'LevelUpV3GuiController', 'LevelUpDetailsGuiControllerV2',
  'BuddyLevelUpGuiController', 'FriendshipLevelUpGuiController', 'MegaLevelUpGuiController', 'RewardPreviewModalGuiController',
  'VivillonSubBadgeAwardGuiController', 'GymBadgeTutorialGuiController'];

function walkChain() {                        /* the game's own state machine, root .. leaf (main thread) */
  var names = [], cur = ROOT, gas = null, gbs = null, gst = null, g = 0;
  while (!cur.isNull() && g++ < 24) {
    var nm = cs(cur.readPointer().add(0x10).readPointer()); names.push(nm);   /* pure reads: no il2cpp call on object memory */
    if (nm === 'GymApproachState') gas = cur;
    if (nm === 'GymBattleState') gbs = cur;
    if (nm === 'GymState') gst = cur;
    cur = cur.add(O.gsChild).readPointer();
  }
  var chain = names.join(' > '), leaf = names[names.length - 1] || '';
  if (!gst && GSTATE) LEFT_GYM_AT = Date.now();                                  /* the gym just closed */
  if (leaf === 'MapExploreState' && LEAF !== 'MapExploreState') MAP_SINCE = Date.now();
  if (/GymState/.test(chain)) LAST_OPEN = {fid: null, at: 0};                    /* the open landed */
  if (chain !== CHAIN) { CHAIN = chain; send({k: 'state', chain: chain}); }
  if (GAS && (!gas || !gas.equals(GAS)) && ACT && ACT !== 'runaway') ACT = null;   /* a gym-screen action never outlives its screen */
  if (GAS && !gas) EXPECT_PREP = 0;                                              /* left the gym screen: no Battle is pending */
  GAS = gas; GSTATE = gst;
  var wasBattle = IN_BATTLE; IN_BATTLE = !!gbs; GBS = gbs;
  if (IN_BATTLE && !wasBattle) send({k: 'battle', on: true});
  if (!IN_BATTLE && wasBattle) { ROUND = false; FAINT_DUE = Date.now() + 1500; send({k: 'end', fast: ST.fast, charged: ST.charged});
    if (AUTODEP && leaf === 'MapExploreState') { PENDING = AUTODEP.fid; PENDING_AT = Date.now(); } }
  var round = leaf === 'GymBattleState';
  if (round && !ROUND) send({k: 'start'});
  ROUND = round; LEAF = leaf;
}
function topScreen(now) {                     /* the live top screen (GuiLayerService.TopGui) and what it means */
  if (!GLS) {
    for (var i = 0; i < GLS_CANDS.length && !GLS; i++) { if (!isA(GLS_CANDS[i], K.GuiLayerService)) continue;
      var r = call(M.topGui, GLS_CANDS[i], 'topGui?'); if (r !== null && !r.isNull()) GLS = GLS_CANDS[i]; }
    if (!GLS) return;
  }
  if (!isA(GLS, K.GuiLayerService)) { GLS = null; return; }
  var tg = call(M.topGui, GLS, 'topGui'); if (tg === null) return;
  var tn = tg.isNull() ? '' : cs(tg.readPointer().add(0x10).readPointer());
  if (tn === 'GymBattlePrepUIController') {   /* a stale party screen (hidden / closing) is not a top screen */
    try { var pst = tg.add(O.guiState).readS32(); if (pst !== LIT.open.Open && pst !== LIT.open.Opening) tn = ''; } catch (e) { tn = ''; } }
  /* screens are tracked by OBJECT (a new instance of the same class is a new screen), and closed by their own state */
  if (tn === 'GymBattlePrepUIController' && !tg.isNull() && (!PREP || !PREP.equals(tg))) { PREP = tg; PREP_AT = now; send({k: 'gui', open: 'GymBattlePrepUIController'}); }
  if (tn === 'GymBattleContinueGuiController' && !CONT_DONE[tg] && (!CONT || !CONT.gui.equals(tg))) CONT = {gui: tg, k: klassOf(tg), at: now};
  if (SKIP.indexOf(tn) >= 0 && !SKIP_OFF[tn] && !SKIP_DONE[tg] && (!SKIPQ[tn] || !SKIPQ[tn].gui.equals(tg))
      && (SKIP_BASE[tn] !== undefined ? SKIP_BASE[tn] : (SKIP_BASE[tn] = derivesGui(klassOf(tg))))) SKIPQ[tn] = {gui: tg, k: klassOf(tg), at: now};
  if (tn === TOP) return;
  TOP = tn; TOP_AT = now; send({k: 'top', gui: tn});
  if (SAYS[tn]) SAYQ.push({gui: tg, k: klassOf(tg), name: tn, at: now + 400});   /* its text is set as it opens: read it a moment later */
}
function dirGyms() {                          /* every gym on the map, from the game's MapPlaceDirectoryService */
  var out = [];
  if (!DIR) return out;
  var D = DIR.add(O.dirDict).readPointer(); if (D.isNull()) return out;
  var ents = D.add(O.dEntries).readPointer(), n = D.add(O.dCount).readS32(); if (ents.isNull()) return out;
  for (var i = 0; i < n && i < 5000; i++) {
    var e = ents.add(0x20 + O.dEsz * i); if (e.add(O.dHash).readS32() < 0) continue;
    var mg = e.add(O.dValue).readPointer(); if (!mg.isNull() && mg.readPointer().equals(K.MapGym)) out.push(mg);
  }
  return out;
}
var FWATCH = {}, MAPKEY = {};   /* (NOT 'WATCH': that name is the party-screen watch list) */
function readMap(now) {
  var seen = {};
  if (STUDY) { FWATCH = {}; for (var wi in DEFS) if (DEFS[wi] && DEFS[wi].fid) FWATCH[DEFS[wi].fid] = 1; }
  dirGyms().forEach(function (mg) {
    try {
      var fd = mg.add(O.mgFort).readPointer(); if (fd.isNull()) return;
      var fid = str(fd.add(O.fFortId).readPointer()); if (!fid) return;
      var ri = fd.add(O.fRaid).readPointer(), gd = fd.add(O.fGymDisplay).readPointer();
      GTEAM[fid] = [fd.add(O.fTeam).readS32(), now, fd.add(O.fLat).readDouble(), fd.add(O.fLng).readDouble(),
                    ri.isNull() ? 0 : Number(ri.add(O.rEnd).readS64()),
                    (!gd.isNull() && gd.readPointer().equals(K.GymDisplay)) ? gd.add(O.gdSlots).readS32() : -1, fd.add(O.fInBattle).readU8(),
                    (!gd.isNull() && gd.readPointer().equals(K.GymDisplay) && O.gdCp >= 0) ? gd.add(O.gdCp).readS32() : -1,
                    O.fLock !== undefined ? Number(fd.add(O.fLock).readS64()) : 0,   /* [8] deploy lockout end (the finisher's window) */
                    O.fTeamLock !== undefined ? Number(fd.add(O.fTeamLock).readS64()) : 0,   /* [9] same-team deploy lockout end */
                    O.fMod !== undefined ? Number(fd.add(O.fMod).readS64()) : 0,   /* [10] the map record's LastModifiedMs */
                    O.fVisited !== undefined ? fd.add(O.fVisited).readU8() : 0];   /* [11] this account has spun its disc */
      var mib = GTEAM[fid][6]; if (!MAPIB[fid] || MAPIB[fid][0] !== mib) MAPIB[fid] = [mib, MAPIB[fid] ? now : 0];
      if (STUDY && (FWATCH[fid] || inFeedZone(GTEAM[fid][2], GTEAM[fid][3]))) { var nv = GTEAM[fid], key = nv[0] + '/' + nv[6] + '/' + nv[5];
        if (MAPKEY[fid] !== key) { MAPKEY[fid] = key; study({src: 'map', fid: fid, team: nv[0], ib: nv[6], cp: nv[7], slots: nv[5], ours: FWATCH[fid] ? 1 : 0}); } }
      GYMS[fid] = mg; seen[fid] = 1;
    } catch (e) {}
  });
  for (var f in GYMS) if (!seen[f]) delete GYMS[f];
  for (var g in GTEAM) if (now - GTEAM[g][1] > 600000) delete GTEAM[g];
}
function gymScreen(now) {                     /* the gym screen: its gym's own team, its modal, queued Battle/Back/Deploy */
  if (!GAS) return;
  var gui = GAS.add(O.gasGui).readPointer(), root = GAS.add(O.gasRoot).readPointer(), pr = GAS.add(O.gasPrompts).readPointer();
  if (now - ST.teamAt > (AUTODEP ? 200 : 1000) && !root.isNull()) {
    ST.teamAt = now;
    if (!M.grcTeam) { var rk = klassOf(root); M.grcTeam = methodOn(rk, 'get_GymTeam'); M.grcNeutral = methodOn(rk, 'get_IsNeutral'); M.grcFid = methodOn(rk, 'get_FortId'); K.root = rk; }
    if (M.grcTeam && M.grcNeutral && M.grcFid && isA(root, K.root) && isA(gui, K.GymApproachGuiController)) {
      var t = callI(M.grcTeam, root, 'gymTeam'), n = callB(M.grcNeutral, root, 'gymNeutral'), fr = call(M.grcFid, root, 'gymFid');
      if (t !== null && n !== null && fr !== null && !fr.isNull()) {
        var fid = str(fr), key = t + '/' + n + '/' + fid;
        if (key !== ST.teamKey || now - (ST.teamSent || 0) > 3000) { ST.teamKey = key; ST.teamSent = now; send({k: 'gymteam', team: t, neutral: n, fid: fid}); }
        var free = n || (AUTODEP && t === MYTEAM);   /* empty -- or OUR team's gym (joined, or a red player got in first): a refusal is harmless */
        if (AUTODEP && fid === AUTODEP.fid && free && (IN_BATTLE || LEAF !== 'GymApproachState' || prepOpen()) && now - (ST.adWait || 0) > 2000) {
          ST.adWait = now; send({k: 'err', e: 'auto-place waiting: leaf ' + LEAF + ', battle ' + IN_BATTLE + ', party screen ' + prepOpen()}); }
        if (AUTODEP && fid === AUTODEP.fid && free && !IN_BATTLE && LEAF === 'GymApproachState' && !prepOpen() && alive(gui)
            && gui.add(O.guiState).readS32() === LIT.open.Open && !PLACED) {
          var ad = AUTODEP; AUTODEP = null;   /* empty + our gym screen up: act right now */
          var pick = (ad.cands && ad.cands.length && M.pickHandler && IBAG) ? pickCandidate(ad.cands) : null;
          if (pick) {                         /* the gym screen's own "Pokemon picked" handler, as a tap in the list would call it */
            if (call(M.pickHandler, gui, 'placePokemon', [pick.p]) !== null) { PLACED = {id: pick.id, fid: fid, cp: pick.cp, at: now}; send({k: 'autoplace', fid: fid, id: pick.id, cp: pick.cp, ms: now}); }
          } else if (call(M.clickDeploy, gui, 'ClickDeploy') !== null) send({k: 'deployopen', fid: fid, ms: now});
        }
        /* drilling and the gym screen is back while the gym is still theirs: Battle THIS frame. Nobody can deploy into a gym that
           is in battle, so the gap between our sessions is the only window the other team gets -- keep it as short as possible */
        if (AUTODEP && fid === AUTODEP.fid && !n && t !== MYTEAM && !IN_BATTLE && LEAF === 'GymApproachState' && !prepOpen()
            && !ACT && !ST.modal && now - GO_AT > 3000 && now - (ST.autoBattleAt || 0) > 8000 && !EXPECT_PREP && alive(gui)
            && gui.add(O.guiState).readS32() === LIT.open.Open && !prepRegistered()) {
          ST.autoBattleAt = now; EXPECT_PREP = now;
          if (call(M.clickBattle, gui, 'ClickBattle') !== null) send({k: 'pressed', what: 'Battle', auto: true, ms: now});
        }
      }
    }
  }
  if (now - ST.modalAt > 1000 && !pr.isNull()) {
    ST.modalAt = now;
    if (!M.hasModal) { var pk = klassOf(pr); M.hasModal = methodOn(pk, 'HasActiveModal'); M.dismissModal = methodOn(pk, 'DismissActiveModal'); K.prompts = pk; }
    if (M.hasModal && isA(pr, K.prompts)) { var hm = callB(M.hasModal, pr, 'hasModal'); if (hm !== null && hm !== ST.modal) { ST.modal = hm; send({k: 'modal', open: hm}); } }
  }
  if (!ACT || ['battle', 'deploy', 'back', 'dismissmodal', 'pokestop'].indexOf(ACT) < 0) return;   /* go / unhang / runaway belong to frameTick */
  if (now - ACT_AT > 3000) { send({k: 'err', e: 'dropped stale action ' + ACT}); ACT = null; return; }
  if (alive(gui) && !isA(gui, K.GymApproachGuiController) && !ST.guiWarned) { ST.guiWarned = true; send({k: 'err', e: 'gym screen class is ' + nameOf(klassOf(gui)) + ' -- actions held'}); }
  if (!alive(gui) || !isA(gui, K.GymApproachGuiController)) return;   /* the gym screen's GUI is not up yet: keep it queued (≤3 s) */
  if (ACT === 'battle' && (prepOpen() || (GO_AT && now - GO_AT < 8000 && !IN_BATTLE) || (EXPECT_PREP && now - EXPECT_PREP < 8000)
      || now - (ST.autoBattleAt || 0) < 8000 || prepRegistered())) { ACT = null; return; }   /* one Battle per party screen, ever */
  if ((ACT === 'deploy' || ACT === 'back' || ACT === 'battle' || ACT === 'pokestop') && gui.add(O.guiState).readS32() !== LIT.open.Open) return;   /* only on a fully open gym screen */
  if (ACT === 'deploy' && PLACED) { ACT = null; return; }   /* a placement request is in flight */
  var a = ACT; ACT = null;
  if (a === 'battle') { EXPECT_PREP = now; if (call(M.clickBattle, gui, 'ClickBattle') !== null) send({k: 'pressed', what: 'Battle'}); }
  else if (a === 'deploy') { if (call(M.clickDeploy, gui, 'ClickDeploy') !== null) send({k: 'pressed', what: 'Deploy'}); }
  else if (a === 'back') { if (call(M.back, gui, 'Back') !== null) send({k: 'pressed', what: 'Back'}); }
  else if (a === 'pokestop' && M.clickStop) { if (call(M.clickStop, gui, 'ClickPokestopButton') !== null) send({k: 'pressed', what: 'PokestopButton'}); }
  else if (a === 'dismissmodal' && !pr.isNull() && M.dismissModal) { if (call(M.dismissModal, pr, 'dismissModal') !== null) send({k: 'pressed', what: 'DismissModal'}); }
}
function prepRegistered() {                   /* a party screen already registered (it can take >1 s to become TopGui) */
  if (!HS || HS.bad || !K.GymBattlePrepUIController) return false;
  return registered().some(function (g) { try { var k = g.readPointer(); if (!k.equals(K.GymBattlePrepUIController)) return false;
    var st = g.add(O.guiState).readS32(); return st === LIT.open.Open || st === LIT.open.Opening; } catch (e) { return false; } });
}
function prepOpen() {                        /* the tracked party screen is still Opening/Open (its own state) */
  if (!PREP) return false;
  try { if (!alive(PREP)) return false; var st = PREP.add(O.guiState).readS32(); return st === LIT.open.Open || st === LIT.open.Opening; } catch (e) { return false; }
}
function partyState() {                       /* party screen closed (by its own state): tell the runner once */
  if (PREP && !prepOpen()) { PREP = null; send({k: 'gui', close: 'GymBattlePrepUIController'}); }
}
function partyScreen(now) {                   /* GO, exactly once per Battle press (EXPECT_PREP), on a fully open party screen */
  if (EXPECT_PREP && now - EXPECT_PREP > 10000) EXPECT_PREP = 0;   /* that press produced nothing: forget it */
  if (EXPECT_PREP && !PREP && HS && !HS.bad) {   /* TopGui lags (toasts): take the party screen from the registry instead */
    registered().some(function (g) { try { if (g.readPointer().equals(K.GymBattlePrepUIController) && g.add(O.guiState).readS32() === LIT.open.Open) {
      PREP = g; PREP_AT = now - 200; send({k: 'gui', open: 'GymBattlePrepUIController'}); return true; } } catch (e) {} return false; }); }
  if (!PREP || LEAF !== 'GymApproachState' || !EXPECT_PREP || now - EXPECT_PREP > 10000 || now - PREP_AT < 150) return;
  try { if (PREP.add(O.guiState).readS32() !== LIT.open.Open) return; } catch (e) { return; }
  if (!isA(PREP, K.GymBattlePrepUIController)) return;
  var btn = PREP.add(O.prepGo).readPointer(); if (!alive(btn)) return;
  EXPECT_PREP = 0; GO_AT = now;
  if (ROSTER.length && IBAG && M.getPokemon) { try { TEAMP = pickTeam(6); TEAM_AT = now;
    ACTIVE = {}; ACTIVE_AT = now; TEAMP.forEach(function (t) { ACTIVE[t.id] = 1; }); } catch (e) { TEAMP = null; } }
  WATCH.push({p: PREP, at: now, battleAt: 0, told: false});
  if (call(M.press, btn, 'GO') !== null) { send({k: 'pressed', what: 'GO'}); send({k: 'go'}); }
}
function watchParty(now) {                    /* a party screen must be gone once its battle runs */
  WATCH = WATCH.filter(function (w) {
    try {
      if (!alive(w.p)) return false;
      var st = w.p.add(O.guiState).readS32(), vis = w.p.add(O.guiVisible).readU8();
      if (st !== LIT.open.Open && st !== LIT.open.Opening) return false;           /* closing / closed: good */
      if (IN_BATTLE && !w.battleAt) w.battleAt = now;
      if (w.battleAt && now - w.battleAt > 4000 && vis && !w.told) { w.told = true; send({k: 'prepstuck', state: st, secs: (now - w.battleAt) / 1000}); }
      return now - w.at < 120000;
    } catch (e) { return false; }
  });
}
function continueScreen(now) {
  if (!CONT) return;
  if (!alive(CONT.gui) || !isA(CONT.gui, CONT.k)) { CONT = null; return; }
  try {
    var st = CONT.gui.add(O.guiState).readS32();
    if ((st === LIT.open.Open || st === LIT.open.Opening) && !CONT.gui.add(O.contAction).readPointer().isNull()) {
      if (CONT_DONE[CONT.gui]) { CONT = null; return; }          /* once per screen object */
      if (st !== LIT.open.Open) return;                             /* only when fully Open */
      var g = CONT.gui; CONT = null; CONT_DONE[g] = now; if (call(M.cont, g, 'continue') !== null) send({k: 'continued'});
    } else if (now - CONT.at > 15000) { send({k: 'err', e: 'continue screen never wired (state ' + st + ')'}); CONT = null; }
  } catch (e) { CONT = null; }
}
function skipScreens(now) {                  /* 'NEXT UP' intro, motivation/CP-drop: closed with their own Dismiss once Open */
  for (var nm in SKIPQ) {
    var q = SKIPQ[nm]; if (!q) continue;
    try {
      if (!alive(q.gui) || !isA(q.gui, q.k)) { SKIPQ[nm] = null; continue; }
      var st = q.gui.add(O.guiState).readS32();
      if (st !== LIT.open.Open) { if (now - q.at > 8000) SKIPQ[nm] = null; continue; }
      if (now - q.at < 250) continue;
      SKIPQ[nm] = null; SKIP_DONE[q.gui] = now;
      if (call(M.dismiss, q.gui, 'skip ' + nm) === null) { SKIP_OFF[nm] = true; send({k: 'err', e: 'skipping ' + nm + ' threw -- off for this session'}); }
      else send({k: 'skipped', what: nm});
    } catch (e) { SKIPQ[nm] = null; }
  }
}
function fastBattle() {                       /* the battle state's own KO -> results pause, shorter (plain write, once) */
  if (!GBS || FAST_GBS[GBS] || O.gbsResultsDelay < 0) return;
  FAST_GBS[GBS] = 1;
  try { var v = GBS.add(O.gbsResultsDelay).readFloat(); if (v > RESULTS_DELAY) { GBS.add(O.gbsResultsDelay).writeFloat(RESULTS_DELAY); send({k: 'fastdelay', was: v}); } } catch (e) {}
}
function openPending(now) {
  if (!PENDING) return;
  if (now - PENDING_AT > 10000) { send({k: 'err', e: 'open request expired: ' + PENDING}); PENDING = null; return; }
  if (LEAF !== 'MapExploreState') return;     /* only from the plain map */
  if (now - LEFT_GYM_AT < 2000 || now - MAP_SINCE < 700) return;   /* the last gym / battle is still tearing down: wait */
  if (TOP && TOP !== 'MainMenuGuiController' && !/Toast/.test(TOP)) return;   /* only over the plain map */
  if (LAST_OPEN.fid && now - LAST_OPEN.at < 12000 && !/GymState/.test(CHAIN)) return;   /* an open already in flight */
  var mg = GYMS[PENDING]; if (!mg || !alive(mg) || !mg.readPointer().equals(K.MapGym)) return;
  var fid = PENDING; PENDING = null;
  LAST_OPEN = {fid: fid, at: now};
  if (call(M.tapped, mg, 'openGym') !== null) send({k: 'opened', fid: fid});
}
var SAYS = {}, SAYQ = [];
function screenText(now) {                    /* plain reads of the screen's Text components (m_Text) */
  SAYQ = SAYQ.filter(function (q) {
    if (now < q.at) return true;
    try {
      if (!isA(q.gui, q.k) || O.textM === undefined || O.textM < 0) return false;
      var parts = SAYS[q.name].map(function (off) { var t = q.gui.add(off).readPointer(); return t.isNull() ? '' : (str(t.add(O.textM).readPointer()) || ''); })
        .filter(function (x) { return x && x.trim(); });
      if (parts.length) send({k: 'says', gui: q.name, text: parts.join(' | ').replace(/<[^>]+>/g, '').slice(0, 300)});
    } catch (e) {}
    return false;
  });
}
function popups(now) {
  POPQ = POPQ.filter(function (d) {
    if (now < d.at) return true;
    try {
      if (!alive(d.gui) || !isA(d.gui, d.k)) return false;
      var st = d.gui.add(O.guiState).readS32();
      if (st === LIT.open.Open) { if (call(M.dismiss, d.gui, 'dismiss ' + d.name) !== null) send({k: 'dismissed', gui: d.name}); return false; }
      if (st === LIT.open.Dismissing) return false;
      return now - d.at < 10000;              /* Opening, or registered but not open yet: keep waiting */
    } catch (e) { return false; }
  });
}
/* >>> STAB: tools/test_gym_stab.py runs everything from here to the "<<< STAB" marker under node, against mock il2cpp objects */
function rank(disp) {                         /* the game's own effectiveness label on the charge button */
  try {
    var t = disp.add(O.cadEff).readPointer(); if (t.isNull()) return 1;
    if (ST.textOff < 0) ST.textOff = fieldBy(klassOf(t), function (n) { return n === 'm_Text'; });
    var s = (str(t.add(ST.textOff).readPointer()) || '').toUpperCase();
    return s.indexOf('NOT') >= 0 ? 0 : (s.indexOf('SUPER') >= 0 ? 2 : 1);
  } catch (e) { return 1; }
}
/* ---- same-type attack bonus (STAB) ----
   The charge pick scores power x the game's effectiveness label x STAB; STAB = the game's SameTypeAttackBonusMultiplier (client game
   master: 1.2) when the move's type is one of the ATTACKER's types. It never applied (2026-09-30, Benny: "fix it"): over 87 gym logs
   and 327 readings the logged damage / power was always 1.0, 1.6 or 0.625, never x1.2. PROVEN cause, from the repo's live dumps: the
   class recon (pogo_extract/_recon_evolve_out.json: type1_ @24, type2_ @28) and a 0.429.1 dump (AutoCatcher/system/analysis/map_full.json,
   2026-09-25: "uniqueId_": 19, "type1_": 1) both name PokemonSettingsProto's first type type1_; the old matcher wanted type / type_ for
   it, so setT1 stayed -1 and setOffs() returned null WITHOUT a log line (the class matched, so no info line either).
   INFERRED, not provable offline: that ChargeAttackDisplay has an IPokemonSettings field at all, and that it holds the ATTACKER's
   settings (the effectiveness label needs the DEFENDER's). A wrong-side read would boost the wrong moves, so the live read counts only
   when its species is one of OUR fighting six that carries this button's move(s). Order (attackerTypes):
     live   the button's settings object, validated as above;
     table  the attacker = our fighting six matched by the charge moves on the buttons, its types from the game master table the
            runner hands over (stab()); a mega-evolved attacker is never looked up (its types differ);
     none   no boost = the old behaviour. The first supervised run shows which one fired (install line, 'charged moves:' lines). */
var STAB = {mult: 1.2, multSrc: 'default', live: null, gm: null, table: null, tableN: 0, told: {}, err: null, snap: {key: '', at: 0, list: []}};
var SETOFF = {}, MOVE_NAME = {}, TYPE_ID = {}, DISP = null;
function settingsFields(fs) {                 /* PokemonSettingsProto's own fields by DECLARED TYPE -> {t1, t2, id} offsets (-1 = not found); names only break ties */
  var r = {t1: -1, t2: -1, id: -1};
  var pick = function (tn) { return fs.filter(function (x) { return x.tn === tn; }).sort(function (a, b) { return a.off - b.off; }); };
  var ty = pick('Holoholo.Rpc.HoloPokemonType'), ids = pick('Holoholo.Rpc.HoloPokemonId');
  ty.forEach(function (x) { if (/^type2_?$/i.test(x.name)) r.t2 = x.off; else if (/^type1?_?$/i.test(x.name)) r.t1 = x.off; });
  if ((r.t1 < 0 || r.t2 < 0) && ty.length === 2) { r.t1 = ty[0].off; r.t2 = ty[1].off; }   /* renamed again: the two type fields in declaration order */
  ids.forEach(function (x) { if (r.id < 0 && /^uniqueId_?$/i.test(x.name)) r.id = x.off; });
  if (r.id < 0 && ids.length) r.id = ids[0].off;   /* the species (uniqueId_ @16 in the recon) is the first HoloPokemonId field */
  return r;
}
function typeIds(lits) {                      /* the live enum {PokemonTypeWater: 11, ...} -> {WATER: 11, ...}: the game master spells them POKEMON_TYPE_WATER */
  var o = {};
  Object.keys(lits || {}).forEach(function (nm) { var n = nm.replace(/^PokemonType/i, '').toUpperCase(); if (n && n !== 'NONE' && lits[nm] > 0) o[n] = lits[nm]; });
  return o;
}
function liveMult(vals) {                     /* the game's own multiplier from GymBattleSettingsProto: the one sane value every reading agrees on, else null */
  var ok = vals.filter(function (v) { return v > 1 && v <= 2; });
  if (!ok.length || ok.some(function (v) { return Math.abs(v - ok[0]) > 1e-4; })) return null;
  return Math.round(ok[0] * 1e4) / 1e4;
}
function loadStab(cfg) {                      /* the runner hands over the client game master's multiplier + typing table (read only where the live read yields nothing) */
  var t = {}, n = 0, bad = 0, m = cfg ? +cfg.mult : 0, src = (cfg && cfg.types) || {};
  STAB.gm = m > 1 && m <= 2 ? m : null;
  if (STAB.live === null && STAB.gm !== null) { STAB.mult = STAB.gm; STAB.multSrc = 'game master'; }   /* (the live value wins when install() resolved it) */
  Object.keys(src).forEach(function (k) {
    var ids = (src[k] || []).map(function (nm) { return TYPE_ID[String(nm).toUpperCase()]; });
    if (!ids.length || ids.some(function (v) { return !(v > 0); })) { bad++; return; }
    t[k] = [ids[0], ids.length > 1 ? ids[1] : 0]; n++; });
  STAB.table = n ? t : null; STAB.tableN = n;
  return {types: n, rejected: bad, mult: STAB.mult, multSrc: STAB.multSrc, liveMult: STAB.live, gmMult: STAB.gm};
}
function resolveStab() {                      /* install(): the STAB field offsets + the live type enum (optional: a miss is reported in the install line, never a MISSING) */
  O.cadSet = []; O.cadRelated = []; O.setT1 = -1; O.setT2 = -1; O.setId = -1; K.PokemonSettings = null;
  try {
    fieldsOf(K.ChargeAttackDisplay).forEach(function (x) {   /* EVERY IPokemonSettings field (an attacker's AND a defender's, if both exist); attackerTypes() validates each by species */
      if (x.tn === 'Holoholo.Rpc.IPokemonSettings') O.cadSet.push(x.off);
      if (/PokemonProto$|PokemonSettings|BattlePokemon/.test(x.tn)) O.cadRelated.push(x.name + ':' + x.tn.split('.').pop() + '@' + x.off); });
    K.PokemonSettings = byName('Holoholo.Rpc', 'PokemonSettingsProto');
    if (K.PokemonSettings) { var stf = settingsFields(fieldsOf(K.PokemonSettings)); O.setT1 = stf.t1; O.setT2 = stf.t2; O.setId = stf.id; }
    var ptk = byName('Holoholo.Rpc', 'HoloPokemonType'); TYPE_ID = ptk ? typeIds(enumLits(ptk)) : {};
  } catch (e) { STAB.err = String(e); }
}
function resolveLiveMult() {                  /* install(): the game's own SameTypeAttackBonusMultiplier (client game master 1.2); the runner's game master value is the fallback */
  try {
    var bk = byName('Holoholo.Rpc', 'GymBattleSettingsProto'), bo = bk ? fieldBy(bk, function (n, t) { return /^sameTypeAttackBonusMultiplier_?$/i.test(n) && t === 'System.Single'; }) : -1;
    if (bo < 0) return;
    var vals = [];
    instances(bk, 4).forEach(function (g) { try { if (isA(g, bk)) vals.push(g.add(bo).readFloat()); } catch (e) {} });
    var lm = liveMult(vals); if (lm !== null) { STAB.live = lm; STAB.mult = lm; STAB.multSrc = 'live'; }
  } catch (e) { STAB.err = String(e); }
}
function stabReport() {                       /* install()'s STAB line: what resolved, so the first supervised run shows which path can fire */
  return {cadSettings: O.cadSet || [], setT1: O.setT1, setT2: O.setT2, setId: O.setId, settingsClass: !!K.PokemonSettings, moveType: !!O.mvTypeOk,
    typeNames: Object.keys(TYPE_ID).length, related: O.cadRelated || [], mult: STAB.mult, multSrc: STAB.multSrc, liveMult: STAB.live, err: STAB.err};
}
function setOffs(ps) {                        /* the settings object's layout: only the PokemonSettingsProto whose fields install() resolved is readable */
  var k = ps.readPointer(), key = String(k); if (SETOFF[key] !== undefined) return SETOFF[key];
  if (!K.PokemonSettings || !k.equals(K.PokemonSettings)) { SETOFF[key] = null; send({k: 'info', what: 'STAB: a charge button has a settings object of another class (live types unread, the game master table decides):', layout: nameOf(k)}); return null; }
  SETOFF[key] = O.setT1 >= 0 && O.setId >= 0 ? {t1: O.setT1, t2: O.setT2, id: O.setId} : null; return SETOFF[key];
}
function dispOffs() {                         /* PokemonDisplayProto: the form and the temporary (mega / primal) evolution, by name, once */
  if (DISP) return DISP;
  DISP = {form: -1, mega: -1}; var dk = byName('Holoholo.Rpc', 'PokemonDisplayProto');
  if (dk) fieldsOf(dk).forEach(function (x) { if (/^form_?$/i.test(x.name)) DISP.form = x.off; else if (/^currentTempEvolution_?$/i.test(x.name)) DISP.mega = x.off; });
  return DISP;
}
function fightingSix(now) {                   /* our six in this battle as plain numbers {dex, form, mega, m2, m3}, read through the bag by id (cached per roster, no pointer kept) */
  var ids = Object.keys(ACTIVE).sort(), key = ACTIVE_AT + ':' + ids.join(',');
  if (STAB.snap.key === key && (STAB.snap.list.length === ids.length || now - STAB.snap.at < 3000)) return STAB.snap.list;
  var o = protoOffs(), dp = dispOffs(), out = [];
  if (o.pokemonId !== undefined && o.move2 !== undefined) ids.forEach(function (id) {
    try {
      var p = liveProto(id); if (!p) return;
      var disp = o.pokemonDisplay !== undefined ? p.add(o.pokemonDisplay).readPointer() : NULL, has = !disp.isNull();
      out.push({dex: p.add(o.pokemonId).readS32(), form: has && dp.form >= 0 ? disp.add(dp.form).readS32() : 0,
        mega: has && dp.mega >= 0 ? disp.add(dp.mega).readS32() !== 0 : false,
        m2: p.add(o.move2).readS32(), m3: o.move3 !== undefined ? p.add(o.move3).readS32() : 0});
    } catch (e) {}
  });
  STAB.snap = {key: key, at: now, list: out};
  return out;
}
function attackerTypes(ds, now) {             /* who attacks and with what types: {pairs: [[t1, t2], ...], src: 'live' | 'table' | 'none', dex, note} */
  var r = {pairs: [], src: 'none', dex: null, note: ''}, mids = [];
  ds.forEach(function (d) { try { var mv = d.add(O.cadMove).readPointer(); if (!mv.isNull()) mids.push(mv.add(O.mvId).readS32()); } catch (e) {} });
  var six = fightingSix(now);
  if (!six.length) { r.note = 'no snapshot of our six'; return r; }
  var cands = mids.length ? six.filter(function (t) { return mids.every(function (m) { return m === t.m2 || m === t.m3; }); }) : [];
  if (!cands.length) { r.note = 'none of our six carries these moves'; return r; }
  var dexes = {}, live = null, other = null;
  cands.forEach(function (t) { dexes[t.dex] = 1; });
  var mega = cands.filter(function (t) { return t.mega; })[0];
  if (mega) { r.note = '#' + mega.dex + ' is mega evolved (its types differ from the species)'; return r; }
  ds.forEach(function (d) {
    (O.cadSet || []).forEach(function (off) {
      if (live) return;
      try {
        var ps = d.add(off).readPointer(); if (ps.isNull()) return;
        var so = setOffs(ps); if (!so) return;
        var dex = ps.add(so.id).readS32(), t1 = ps.add(so.t1).readS32(), t2 = so.t2 >= 0 ? ps.add(so.t2).readS32() : 0;
        if (dexes[dex]) { if (t1 > 0) live = {dex: dex, t: [t1, t2]}; } else other = dex;   /* another species: the defender's (or stale) -- never the attacker's types */
      } catch (e) {}
    });
  });
  if (live) { r.pairs = [live.t]; r.src = 'live'; r.dex = live.dex; return r; }
  var told = other === null ? null : other + '>' + Object.keys(dexes).join('/');
  if (told && !STAB.told[told]) { STAB.told[told] = 1; send({k: 'info', what: 'STAB: the charge button settings object is species #' + other + ', not the attacker (#' + Object.keys(dexes).join('/') + ') -- its types are not used', layout: ''}); }
  var seen = {}, bad = null;
  cands.forEach(function (t) {
    var key = t.dex + ':' + t.form; if (seen[key]) return; seen[key] = 1;
    var ty = STAB.table ? (STAB.table[key] || STAB.table[t.dex]) : null;
    if (!ty) { bad = t; return; }
    if (!r.pairs.some(function (p) { return p[0] === ty[0] && p[1] === ty[1]; })) r.pairs.push(ty);
  });
  if (bad) { r.pairs = []; r.note = STAB.table ? 'no game master types for #' + bad.dex + ' form ' + bad.form : 'no game master table'; return r; }
  r.src = 'table'; r.dex = Object.keys(dexes).length === 1 ? cands[0].dex : null;
  return r;
}
function moveScore(d, atk) {                  /* the game's own numbers for one charge button; x the same-type bonus when the attacker's types are known */
  var mv = d.add(O.cadMove).readPointer(); if (mv.isNull()) return null;
  var pw = mv.add(O.mvPower).readFloat(), en = -mv.add(O.mvEnergy).readS32(), ty = mv.add(O.mvType).readS32(), stab = 1;
  if (!(en > 0)) en = 100;
  if (atk && O.mvTypeOk && ty > 0 && atk.pairs.length && atk.pairs.every(function (p) { return p[0] === ty || p[1] === ty; })) stab = STAB.mult;   /* every candidate attacker must agree */
  var dmg = pw * [0.625, 1, 1.6][rank(d)] * stab;
  return {dmg: dmg, en: en, dpe: dmg / en, id: mv.add(O.mvId).readS32(), ch: !!d.add(O.cadCharged).readU8(), stab: stab};
}
function attack(now) {
  if (!ROUND || !GBS || now - ST.last < __ACT__) return;
  ST.last = now;
  var svc = GBS.add(O.gbsSvc).readPointer(); if (svc.isNull()) return;
  if (!M.fast || !M.active) { var sk = klassOf(svc), mf = methodOn(sk, 'TryOrQueueAttack'), ma = methodOn(sk, 'get_BattleActive');
    if (!mf || !ma) return; M.fast = mf; M.active = ma; K.svc = sk; }
  if (!isA(svc, K.svc)) return;
  if (!callB(M.active, svc, 'battleActive')) return;
  var ds = [], gh = GBS.add(O.gbsGh).readPointer();
  if (!gh.isNull()) { var arr = gh.add(O.ghDisplays).readPointer();
    if (!arr.isNull()) { var n = arr.add(0x18).readS32(); for (var i = 0; i < n && i < 4; i++) { var d = arr.add(0x20 + 8 * i).readPointer(); if (!d.isNull()) ds.push(d); } } }
  var sc = [], top = -1, nch = 0, fire = -1;   /* the STRONGEST move (power x effectiveness x same-type) fires when charged */
  var atk = null; try { atk = attackerTypes(ds, now); } catch (e) { atk = null; }   /* (a failed STAB read never stops an attack: no boost = the old pick) */
  for (var j = 0; j < ds.length; j++) {
    var m = null; try { m = moveScore(ds[j], atk); } catch (e) {} sc.push(m); if (!m) continue;
    if (m.ch) nch++;
    if (top < 0 || m.dmg > sc[top].dmg) top = j;
  }
  if (top >= 0 && sc[top].ch) fire = top;
  else if (top >= 0) {                        /* the big one is not ready: a charged weaker one only if it is as efficient per energy */
    for (var q = 0; q < sc.length; q++) if (sc[q] && sc[q].ch && sc[q].dpe > sc[top].dpe * 1.1 && (fire < 0 || sc[q].dmg > sc[fire].dmg)) fire = q;   /* clearly more efficient only */
  }
  var mk = sc.map(function (m) { return m ? m.id : 0; }).join(',') + '|' + (atk ? atk.src + ':' + (atk.dex || '') : 'x');
  if (mk !== ST.moveKey) { ST.moveKey = mk;   /* a new attacker (or a new STAB source): say what it will do, and which STAB path decided */
    send({k: 'moves', list: sc.filter(Boolean).map(function (m) { return {n: MOVE_NAME[m.id] || m.id, dmg: Math.round(m.dmg), en: m.en, dpe: Math.round(m.dpe * 100) / 100, stab: m.stab}; }),
      src: atk ? atk.src : 'none', who: atk ? atk.dex : null, note: atk ? atk.note : 'the STAB read failed', mult: STAB.mult}); }
  if (nch > ST.nch) send({k: 'progress'});      /* a charge just filled: our hits land, the battle is moving */
  ST.nch = nch;
  if (fire >= 0) {
    if (!isA(ds[fire], K.ChargeAttackDisplay) || call(M.tapCharge, ds[fire], 'chargedAttack') === null) return;
    ST.charged++; ST.last = now + 600; send({k: 'charged', slot: fire, n: MOVE_NAME[sc[fire].id] || sc[fire].id, dmg: Math.round(sc[fire].dmg)});
  } else { if (call(M.fast, svc, 'fastAttack') === null) return; ST.fast++; }
  if (now - ST.lastSent > 1000) { ST.lastSent = now; send({k: 'act', fast: ST.fast, charged: ST.charged}); }
}
/* <<< STAB */
function runAway() {                          /* the battle's own run-away button (SurrenderButton.TrySurrender) */
  if (!GBS) return false;
  var ui = GBS.add(O.gbsUi).readPointer(); if (ui.isNull()) return false;
  var sb = ui.add(O.uiSurrender).readPointer(); if (!alive(sb) || !isA(sb, K.SurrenderButton)) return false;
  return call(M.surrender, sb, 'runAway') !== null;
}
function bcls(o) { var k = klassOf(o); if (!nameOf(k)) throw new Error('not an object'); return k; }   /* (review: pure reads -- a bad pointer throws, never reaches il2cpp) */
var BUD = {rpc: null, pok: null, q: [], fly: null, lastAt: 0}, BI1 = Memory.alloc(8), BI2 = Memory.alloc(8), BU64 = Memory.alloc(8);
function budHearts(ts) {                      /* BuddyStatsShownHearts -> {km, cat: [heart types]} (MapField: +0x18 LinkedList; node next@0x18, key@0x28, value@0x30) */
  var out = {km: null, cats: {}}; if (ts.isNull()) return out;
  var to = {}; fieldsOf(bcls(ts)).forEach(function (x) { to[x.name] = x.off; });
  out.km = ts.add(to.BuddyAffectionKmInProgress).readFloat();   /* a float (the buddy session, 04:32) */
  var mf = ts.add(to.BuddyShownHeartsPerCategory).readPointer(); if (mf.isNull()) return out;
  var ll = mf.add(0x18).readPointer(); if (ll.isNull()) return out;
  var node = ll.add(0x10).readPointer(), n = ll.add(0x18).readS32();
  for (var i = 0; i < n && i < 20 && !node.isNull(); i++) {
    var key = node.add(0x28).readS32(), val = node.add(0x30).readPointer(), types = [];
    if (!val.isNull()) { var vo = {}; fieldsOf(bcls(val)).forEach(function (x) { vo[x.name] = x.off; });
      var rf = val.add(vo.BuddyShownHeartTypes).readPointer();
      if (!rf.isNull()) { var arr = rf.add(0x10).readPointer(), c = rf.add(0x18).readS32(); for (var j = 0; j < c && j < 20; j++) types.push(arr.add(0x20 + 4 * j).readS32()); } }
    out.cats[key] = types; node = node.add(0x18).readPointer();
  }
  return out;
}
function budRead(v, out) {                    /* any buddy reply: Result, ObservedData (points, emotion, today's hearts, fullness), ShownHearts, UpdatedBuddy, history */
  var o = {}; fieldsOf(bcls(v)).forEach(function (x) { o[x.name] = x.off; });
  if (o.Result !== undefined) out.res = v.add(o.Result).readS32();
  if (o.ShownHearts !== undefined) out.shown = v.add(o.ShownHearts).readS32();
  if (o.KmRemaining !== undefined) out.kmLeft = v.add(o.KmRemaining).readDouble();
  if (o.UpdatedBuddy !== undefined) { var ub = v.add(o.UpdatedBuddy).readPointer(); if (!ub.isNull()) { var uo = {}; fieldsOf(bcls(ub)).forEach(function (x) { uo[x.name] = x.off; });
    out.buddyId = ub.add(uo.BuddyPokemonId).readU64().toString(); } }
  if (o.ObservedData !== undefined) { var od = v.add(o.ObservedData).readPointer();
    if (!od.isNull()) { var oo = {}; fieldsOf(bcls(od)).forEach(function (x) { oo[x.name] = x.off; });
      out.pts = od.add(oo.CurrentPointsEarned).readS32(); out.emotion = od.add(oo.CurrentEmotionPoints).readS32();
      out.today = budHearts(od.add(oo.TodayStatsShownHearts).readPointer());
      var fs = od.add(oo.BuddyFeedStats).readPointer();
      if (!fs.isNull()) { var fo = {}; fieldsOf(bcls(fs)).forEach(function (x) { fo[x.name] = x.off; });
        out.fullUntil = Number(fs.add(fo.FullnessExpirationMs).readS64()); out.full = fs.add(fo.PreMapFullnessPercentage).readFloat();
        out.mapUntil = Number(fs.add(fo.MapExpirationMs).readS64()); } } }
  for (var nm in o) {                         /* GetBuddyHistoryOutProto: the RepeatedField<BuddyHistoryData> */
    if (out.hist || !/History/.test(nm)) continue;
    var rf = v.add(o[nm]).readPointer(); if (rf.isNull() || !/RepeatedField/.test(nameOf(klassOf(rf)))) continue;
    var arr = rf.add(0x10).readPointer(), c = rf.add(0x18).readS32(); out.hist = [];
    for (var i = 0; i < c && i < 800 && !arr.isNull(); i++) { var h = arr.add(0x20 + PS * i).readPointer(); if (h.isNull()) continue;
      var ho = BUD.ho || (BUD.ho = (function () { var z = {}; fieldsOf(bcls(h)).forEach(function (x) { z[x.name] = x.off; }); return z; })());
      out.hist.push([h.add(ho.PokemonId).readU64().toString(), h.add(ho.PokedexId).readS32(), h.add(ho.CurrentPointsEarned).readS32(), Number(h.add(ho.LastSetTimestampMs).readS64())]); }
  }
}
function budTick(now) {                       /* one buddy call at a time, from the game thread */
  if (BUD.fly) {
    var r = promiseRead(BUD.fly); if (r === null && now - BUD.fly.at < 20000) return;
    var out = {k: 'buddy', what: BUD.fly.what, arg: BUD.fly.arg}; BUD.fly = null;
    if (!r || r.gone || r.err) out.err = r ? (r.err || 'gone') : 'no reply';
    else { try { budRead(r.val, out); } catch (e) { out.err = 'read ' + e; } }
    send(out); return;
  }
  if (!BUD.q.length || now - BUD.lastAt < 1500) return;
  var c = BUD.q.shift(), pr = null; BUD.lastAt = now;
  if (c.what === 'who') {                     /* the current buddy + swaps left: the service's own getters, answered at once */
    var w = {k: 'buddy', what: 'who'};
    if (M.bWho && isA(BUD.pok, K.BuddyPokemonService)) { var bp = call(M.bWho, BUD.pok, 'BuddyWho');
      if (bp && !bp.isNull()) { var bo = {}; fieldsOf(bcls(bp)).forEach(function (x) { bo[x.name] = x.off; });
        w.buddyId = bp.add(bo.BuddyPokemonId).readU64().toString(); w.setMs = Number(bp.add(bo.LastSetTimestampMs).readS64()); } }
    if (M.bLeft && isA(BUD.pok, K.BuddyPokemonService)) { var bl = call(M.bLeft, BUD.pok, 'BuddySwapsLeft'); if (bl && !bl.isNull()) w.swapsLeft = bl.add(16).readS32(); }
    send(w); return; }
  if (c.what === 'count') {                   /* the bag's treat counts, with the tapper's own itemCount() */
    var cnt = {}; ['RazzBerry', 'NanabBerry', 'PinapBerry', 'BlukBerry', 'WeparBerry', 'GoldenRazzBerry', 'Poffin'].forEach(function (nm) {
      if (ITEM[nm] !== undefined) cnt[nm] = itemCount(ITEM[nm]); });
    send({k: 'buddy', what: 'count', counts: cnt}); return; }
  if (c.what === 'stats' && M.bStats && isA(BUD.rpc, K.BuddyRpcService)) pr = call(M.bStats, BUD.rpc, 'BuddyStats');
  else if (c.what === 'hist' && M.bHist && isA(BUD.rpc, K.BuddyRpcService)) pr = call(M.bHist, BUD.rpc, 'BuddyHistory');
  else if (c.what === 'pet' && M.bPet && isA(BUD.rpc, K.BuddyRpcService)) pr = call(M.bPet, BUD.rpc, 'BuddyPet');
  else if (c.what === 'feed' && /^Golden/.test(String(c.arg))) { send({k: 'buddy', what: c.what, arg: c.arg, err: 'golden berries are protected (the user: Golden Razz only for his gym defenders)'}); return; }
  else if (c.what === 'feed' && M.bFeed && isA(BUD.rpc, K.BuddyRpcService) && ITEM[c.arg] !== undefined) {
    BI1.writeS32(ITEM[c.arg]); BI2.writeS32(1); pr = call(M.bFeed, BUD.rpc, 'BuddyFeed', [BI1, BI2]); }
  else if (c.what === 'set' && M.bSet && isA(BUD.pok, K.BuddyPokemonService)) { BU64.writeU64(new UInt64(String(c.arg))); pr = call(M.bSet, BUD.pok, 'SetBuddy', [BU64]); }
  if (pr !== null && !pr.isNull()) { var po = promiseOffs(pr); if (po) { BUD.fly = {pr: pr, o: po, at: now, what: c.what, arg: c.arg}; return; } }
  send({k: 'buddy', what: c.what, arg: c.arg, err: 'call not made (service or method missing, or it threw)'});
}
var QUIET = false;                           /* quiesce(): no hook / tick touches the game any more -- then it is safe to unload */
function frameTick() {
  if (BUSY || QUIET) return;
  var now = Date.now(); if (now - FT_AT < 100) return; FT_AT = now;
  BUSY = true;
  try {
    if (ROOT) walkChain();
    if (now - TOPCHK_AT >= 200) { TOPCHK_AT = now; topScreen(now); }
    if (now - MAP_AT > 1000) { MAP_AT = now; readMap(now); }
    openPending(now);
    hsLayout();
    earlyScreens(now);
    partyState();
    continueScreen(now);
    skipScreens(now);
    fastBattle();
    partyScreen(now);
    watchParty(now);
    gymScreen(now);
    popups(now);
    screenText(now);
    if (ACT === 'runaway') { if (IN_BATTLE) { ACT = null; send({k: 'pressed', what: 'RunAway', ok: runAway()}); } else if (now - ACT_AT > 3000) ACT = null; }
    if (ACT === 'go') { ACT = null;             /* a party screen nobody pressed GO on (e.g. left over from a restart): GO now */
      if (prepOpen() && now - GO_AT > 5000 && !EXPECT_PREP) { EXPECT_PREP = now; send({k: 'err', e: 'orphaned party screen -- pressing GO'}); } }
    if (ACT === 'unhang') { ACT = null;         /* a hung battle: the game's own recovery path back to the gym screen */
      var live = false; try { var sv = GBS ? GBS.add(O.gbsSvc).readPointer() : NULL; live = isA(sv, K.svc) && M.active && callB(M.active, sv, 'battleActive?') === true; } catch (e) {}
      if (IN_BATTLE && live) send({k: 'pressed', what: 'RunAway (unhang: the battle is live)', ok: runAway()});
      else if (IN_BATTLE && GSTATE && M.failedToStart && GSTATE.readPointer().equals(K.GymState)) send({k: 'pressed', what: 'Unhang', ok: call(M.failedToStart, GSTATE, 'FailedToStartBattle') !== null});
      else send({k: 'err', e: 'unhang: not in a battle'}); }
    if (TEAMP && now - TEAM_AT < 15000) {       /* re-resolve the picked six every frame: the hook writes pointers the bag holds NOW */
      var o6 = protoOffs(); TEAMP = TEAMP.map(function (t) { var p = liveProto(t.id); return p && usable(p, o6) ? {p: p, id: t.id, cp: t.cp} : null; }).filter(Boolean); }
    attack(now);
    faintTick(now);
    healTick(now);
    placedTick(now);
    feedTick(now);
    mateReplies(now);
    scanTick(now);
    ddTick(now);
    topUpReply(now);
    budTick(now);
  } catch (e) { if (ST.errs++ < 20) send({k: 'err', e: 'frame ' + e}); }
  BUSY = false;
}

rpc.exports = {
  install: function () {
    var want = ['Niantic.Zeppelin.GameStates.GameState', 'Niantic.Zeppelin.Scheduler.Scheduler', 'UnityEngine.Object', 'UnityEngine.UI.Button',
      'Niantic.Holoholo.NUI.GuiController', 'Niantic.Holoholo.NUI.GuiLayerService', 'Niantic.Holoholo.Map.MapPlaceDirectoryService',
      'Niantic.Holoholo.Gym.MapGym', 'Niantic.Holoholo.Gym.Approach.GymApproachState', 'Niantic.Holoholo.Gym.Approach.GymApproachGuiController',
      'Niantic.Holoholo.Gym.GymBattlePrepUIController', 'Niantic.Holoholo.Gym.Battle.GymBattleContinueGuiController',
      'Niantic.Holoholo.Gym.Battle.GymBattleResultsState', 'Niantic.Holoholo.Gym.GymBattleState', 'Niantic.Holoholo.Battle.BattleGestureHandler',
      'Niantic.Holoholo.Gym.GymState',
      'Niantic.Holoholo.Battle.ChargeAttackDisplay', 'Niantic.Holoholo.Battle.GymBattleUI', 'Niantic.Holoholo.Battle.SurrenderButton',
      'Niantic.Holoholo.Gym.GymBattleIntroGuiController', 'Niantic.Holoholo.Gym.Battle.MotivationCpChangeController',
      'Niantic.Holoholo.Gym.Battle.GymBattleVictoryGuiController', 'Niantic.Holoholo.Gym.Battle.GymBattleDefeatGuiController'];
    want.forEach(function (w) { var d = w.lastIndexOf('.'); K[w.slice(d + 1)] = byName(w.slice(0, d), w.slice(d + 1)); });
    var rootK = byName('Niantic.Holoholo', 'RootState');
    want.forEach(function (w) { need('class ' + w, K[w.split('.').pop()] || NULL); });
    /* fields, by name and declared type */
    O.cptr = fieldBy(K.Object, function (n) { return n === 'm_CachedPtr'; });
    O.gsChild = need('GameState.ChildState', fieldBy(K.GameState, function (n) { return n === '<ChildState>k__BackingField'; }));
    O.gsActive = need('GameState.IsActiveState', fieldBy(K.GameState, function (n) { return n === '<IsActiveState>k__BackingField'; }));
    O.guiState = need('GuiController.currentState', fieldBy(K.GuiController, function (n) { return n === 'currentState'; }));
    O.guiVisible = need('GuiController._isVisible', fieldBy(K.GuiController, function (n) { return n === '_isVisible'; }));
    fieldsOf(K.GuiController).forEach(function (x) { if (x.name === 'currentState') LIT.open = enumLits(IL.classFromType(x.t)); });
    need('OpenState.Open', LIT.open && LIT.open.Open !== undefined ? 0 : -1);
    O.gasGui = need('GymApproachState -> GymApproachGuiController', fieldBy(K.GymApproachState, function (n, t) { return t === 'Niantic.Holoholo.Gym.Approach.GymApproachGuiController'; }));
    O.gasRoot = need('GymApproachState -> IGymRootController', fieldBy(K.GymApproachState, function (n, t) { return t === 'Niantic.Holoholo.Gym.IGymRootController'; }));
    O.gasPrompts = need('GymApproachState -> IUserPromptsService', fieldBy(K.GymApproachState, function (n, t) { return t === 'Niantic.Holoholo.UI.IUserPromptsService'; }));
    O.prepGo = need('party screen battleButton (Button)', fieldBy(K.GymBattlePrepUIController, function (n, t) { return n === 'battleButton' && t === 'UnityEngine.UI.Button'; }));
    O.contAction = need('continue OnContinueBattle', fieldBy(K.GymBattleContinueGuiController, function (n) { return n === 'OnContinueBattle'; }));
    O.gbsSvc = need('GymBattleState.battleFrameObservableService', fieldBy(K.GymBattleState, function (n) { return n === 'battleFrameObservableService'; }));
    O.gbsGh = need('GymBattleState.gestureHandler', fieldBy(K.GymBattleState, function (n) { return n === 'gestureHandler'; }));
    O.gbsUi = need('GymBattleState -> IGymBattleUI', fieldBy(K.GymBattleState, function (n, t) { return t === 'Niantic.Holoholo.Battle.IGymBattleUI'; }));
    O.ghDisplays = need('BattleGestureHandler -> ChargeAttackDisplay[]', fieldBy(K.BattleGestureHandler, function (n, t) { return t === 'Niantic.Holoholo.Battle.ChargeAttackDisplay[]'; }));
    O.cadCharged = need('ChargeAttackDisplay.IsCharged', fieldBy(K.ChargeAttackDisplay, function (n) { return n === '<IsCharged>k__BackingField'; }));
    O.cadEff = need('ChargeAttackDisplay.effectivenessText', fieldBy(K.ChargeAttackDisplay, function (n) { return n === 'effectivenessText'; }));
    O.cadMove = need('ChargeAttackDisplay -> MoveSettingsProto', fieldBy(K.ChargeAttackDisplay, function (n, t) { return t === 'Holoholo.Rpc.MoveSettingsProto'; }));
    resolveStab();                             /* the same-type bonus fields (STAB block); a miss is reported in the install line, never a MISSING */
    (function () { var mk = byName('Holoholo.Rpc', 'MoveSettingsProto');
      O.mvPower = need('MoveSettingsProto.Power', fieldBy(mk, function (n, t) { return n === 'Power' && t === 'System.Single'; }));
      O.mvEnergy = need('MoveSettingsProto.EnergyDelta', fieldBy(mk, function (n, t) { return n === 'EnergyDelta' && t === 'System.Int32'; }));
      O.mvType = need('MoveSettingsProto.Type', fieldBy(mk, function (n) { return n === 'Type'; }));
      O.mvTypeOk = fieldBy(mk, function (n, t) { return n === 'Type' && t === 'Holoholo.Rpc.HoloPokemonType'; }) >= 0;   /* STAB compares it with the attacker's HoloPokemonType fields: only if it IS one */
      O.mvId = need('MoveSettingsProto.UniqueId', fieldBy(mk, function (n) { return n === 'UniqueId'; }));
      var ek = byName('Holoholo.Rpc', 'HoloPokemonMove');
      if (ek) { var l = enumLits(ek); for (var nm in l) MOVE_NAME[l[nm]] = nm.replace(/^V\d+Move/, '').replace(/Fast$/, ''); } })();
    O.uiSurrender = need('GymBattleUI.surrenderButton', fieldBy(K.GymBattleUI, function (n) { return n === 'surrenderButton'; }));
    O.gbsResultsDelay = fieldBy(K.GymBattleState, function (n, t) { return n === 'delayBeforeResults' && t === 'System.Single'; });
    O.mgFort = need('MapGym -> PokemonFortProto', fieldBy(K.MapGym, function (n, t) { return t === 'Holoholo.Rpc.PokemonFortProto'; }));
    var fk = byName('Holoholo.Rpc', 'PokemonFortProto');
    fieldsOf(fk).forEach(function (x) {
      if (x.name === 'FortId') O.fFortId = x.off; if (x.name === 'Team') O.fTeam = x.off; if (x.name === 'Latitude') O.fLat = x.off;
      if (x.name === 'Longitude') O.fLng = x.off; if (x.name === 'IsInBattle') O.fInBattle = x.off; if (x.name === 'LastModifiedMs') O.fMod = x.off;
      if (x.name === 'DeployLockoutEndMs') O.fLock = x.off; if (x.name === 'Visited') O.fVisited = x.off; if (x.name === 'SameTeamDeployLockoutEndMs') O.fTeamLock = x.off;
      if (x.name === 'RaidInfo') { O.fRaid = x.off; O.rEnd = fieldBy(IL.classFromType(x.t), function (n) { return n === 'RaidEndMs'; }); }
      if (x.name === 'GymDisplay') { O.fGymDisplay = x.off; K.GymDisplay = IL.classFromType(x.t); O.gdSlots = fieldBy(K.GymDisplay, function (n) { return n === 'SlotsAvailable'; }); O.gdCp = fieldBy(K.GymDisplay, function (n) { return n === 'TotalGymCp'; }); }
    });
    ['fFortId', 'fTeam', 'fLat', 'fLng', 'fInBattle', 'fRaid', 'rEnd', 'fGymDisplay', 'gdSlots'].forEach(function (x) { need('fort ' + x, O[x] === undefined ? -1 : O[x]); });
    O.dirDict = need('directory Dictionary<String, IMapGym>', fieldBy(K.MapPlaceDirectoryService, function (n, t) { return /Dictionary(`2)?<System\.String, ?Niantic\.Holoholo\.Gym\.IMapGym>/.test(t); }));
    /* methods */
    M.press = need('Button.Press', methodOn(K.Button, 'Press'));
    M.clickBattle = need('ClickBattle', methodOn(K.GymApproachGuiController, 'ClickBattle'));
    M.clickDeploy = need('ClickDeploy', methodOn(K.GymApproachGuiController, 'ClickDeploy'));
    M.clickStop = methodOn(K.GymApproachGuiController, 'ClickPokestopButton', 0);   /* (optional: the gym's photo disc side) */
    (function () {                             /* optional: without it Deploy just opens the list for the user */
      var m = methodOn(K.GymApproachGuiController, 'cagd', 1); if (!m) return;
      var pt = f('il2cpp_method_get_param', 'pointer', ['pointer', 'uint32']), rt = f('il2cpp_method_get_return_type', 'pointer', ['pointer']);
      if (cs(TN(pt(m, 0))) === 'Holoholo.Rpc.PokemonProto' && cs(TN(rt(m))) === 'System.Void') M.pickHandler = m;
    })();
    M.back = need('OnBackButtonPressed', methodOn(K.GymApproachGuiController, 'OnBackButtonPressed'));
    M.cont = need('ContinueToNextBattle', methodOn(K.GymBattleContinueGuiController, 'ContinueToNextBattle'));
    M.tapped = need('MapGym.OnTapped', methodOn(K.MapGym, 'OnTapped'));
    M.topGui = need('GuiLayerService.TopGui', methodOn(K.GuiLayerService, 'TopGui'));
    M.dismiss = need('GuiController.Dismiss', methodOn(K.GuiController, 'Dismiss'));
    M.tapCharge = need('ChargeAttackButtonTapped', methodOn(K.ChargeAttackDisplay, 'ChargeAttackButtonTapped'));
    M.surrender = need('TrySurrender', methodOn(K.SurrenderButton, 'TrySurrender'));
    M.failedToStart = need('GymState.FailedToStartBattle', methodOn(K.GymState, 'FailedToStartBattle', 0));
    /* instances -- C-only liveness walk, BEFORE any hook exists */
    if (rootK) instances(rootK, 8).forEach(function (o) { try { if (!ROOT && o.add(O.gsActive).readU8()) ROOT = o; } catch (e) {} });
    need('active RootState', ROOT || NULL);
    GLS_CANDS = instances(K.GuiLayerService, 8);
    need('GuiLayerService instance', GLS_CANDS.length ? 0 : -1);
    var best = -1;
    instances(K.MapPlaceDirectoryService, 8).forEach(function (d) {
      try {
        var D = d.add(O.dirDict).readPointer(); if (D.isNull()) return;
        if (O.dEntries === undefined) {
          fieldsOf(klassOf(D)).forEach(function (x) { if (x.name === '_entries' || x.name === 'entries') O.dEntries = x.off; if (x.name === '_count' || x.name === 'count') O.dCount = x.off; });
          var ents = D.add(O.dEntries).readPointer(), ek = CEC(klassOf(ents)), al = Memory.alloc(4);
          O.dEsz = CVS(ek, al);
          fieldsOf(ek).forEach(function (x) { if (x.name === 'hashCode') O.dHash = x.off - 16; if (x.name === 'value') O.dValue = x.off - 16; });
        }
        var c = D.add(O.dCount).readS32(); if (c > best) { best = c; DIR = d; }
      } catch (e) {}
    });
    need('MapPlaceDirectoryService instance', DIR || NULL);
    var RANGE = null;
    (function () { var gk = byName('Holoholo.Rpc', 'GlobalSettingsProto'), fo = gk ? fieldBy(gk, function (n) { return n === 'FortSettings'; }) : -1;
      if (fo < 0) return; var fk = null; fieldsOf(gk).forEach(function (x) { if (x.name === 'FortSettings') fk = IL.classFromType(x.t); });
      var ro = fk ? fieldBy(fk, function (n, t) { return n === 'InteractionRangeMeters' && t === 'System.Single'; }) : -1; if (ro < 0) return;
      instances(gk, 4).forEach(function (g) { try { if (RANGE === null && isA(g, gk)) { var f = g.add(fo).readPointer(); if (isA(f, fk)) { var v = f.add(ro).readFloat(); if (v > 10 && v < 1000) RANGE = v; } } } catch (e) {} });
    })();
    resolveLiveMult();                         /* the game's own same-type multiplier (another liveness walk, before any hook exists) */
    if (MISSING.length) return {ok: false, missing: MISSING};
    var TEAM_MISSING = [];
    (function () {
      K.PokemonProto = byName('Holoholo.Rpc', 'PokemonProto'); K.ItemBagImpl = byName('Niantic.Holoholo.Internal', 'ItemBagImpl'); K.PokemonBagImpl = byName('Niantic.Holoholo.Internal', 'PokemonBagImpl');
      if (!K.ItemBagImpl || !K.PokemonBagImpl || !K.PokemonProto) { TEAM_MISSING.push('bag classes'); return; }
      O.ibPokeBag = fieldBy(K.ItemBagImpl, function (n, t) { return t === 'Niantic.Holoholo.IPokemonBag'; });
      if (O.ibPokeBag < 0) { TEAM_MISSING.push('ItemBagImpl -> IPokemonBag'); return; }
      var ibs = [];
      instances(K.ItemBagImpl, 8).forEach(function (b) { try { var pb = b.add(O.ibPokeBag).readPointer();
        if (!pb.isNull() && klassOf(pb).equals(K.PokemonBagImpl)) ibs.push(b); } catch (e) {} });
      IBAG = pickGraph(ibs);                   /* the live graph: the newest server inventory update -- never the first hit */
      if (!IBAG) { TEAM_MISSING.push('live ItemBagImpl'); return; }
      M.getPokemon = methodOn(K.PokemonBagImpl, 'GetPokemon', 1); M.itemCount = methodOn(K.ItemBagImpl, 'GetItemCount', 1);
      M.useItem = methodOn(K.ItemBagImpl, 'UseItemOnPokemon', 2);
      M.isMega = methodOn(K.PokemonProto, 'get_IsMegaEvolved', 0);
      ['getPokemon', 'itemCount', 'useItem'].forEach(function (x) { if (!M[x]) TEAM_MISSING.push(x); });
      [['getPokemon', 'System.UInt64'], ['itemCount', 'Holoholo.Rpc.Item'], ['useItem', 'Holoholo.Rpc.Item,System.UInt64']].forEach(function (c) {
        if (M[c[0]] && sigOf(M[c[0]]) !== c[1]) TEAM_MISSING.push(c[0] + ' signature ' + sigOf(M[c[0]])); });
      ITEM = enumLits(byName('Holoholo.Rpc', 'Item'));
      ['Potion', 'SuperPotion', 'HyperPotion', 'MaxPotion', 'Revive', 'MaxRevive'].forEach(function (n) { if (ITEM[n] === undefined) TEAM_MISSING.push('Item.' + n); else ITEM_NAME[ITEM[n]] = n; });
      ['stamina', 'maxStamina', 'cp', 'id', 'deployedFortId', 'deployedStationId', 'isEgg', 'isBad'].forEach(function (x) { if (protoOffs()[x] === undefined) TEAM_MISSING.push('PokemonProto.' + x); });
      M.startBattle = methodOn(K.GymBattleState, 'StartGymBattle', 1);
      var ldk = byName('Niantic.Holoholo.Gym', 'GymBattleLaunchData'); K.GymBattleLaunchData = ldk;
      O.ldTeam = ldk ? fieldBy(ldk, function (n, t) { return n === 'PlayerTeam' && t === 'Holoholo.Rpc.PokemonProto[]'; }) : -1;
      if (!M.startBattle || O.ldTeam < 0) TEAM_MISSING.push('GymBattleState.StartGymBattle / GymBattleLaunchData.PlayerTeam');
      if (TEAM_MISSING.length) { M.getPokemon = M.useItem = M.startBattle = null; IBAG = null; }
    })();
    var FEED_MISSING = [];
    (function () {                             /* the Golden Razz feeder (optional: without it nothing is fed) */
      if (!IBAG) { FEED_MISSING.push('item bag'); return; }
      K.MapPlaceDetailsService = byName('Niantic.Holoholo', 'MapPlaceDetailsService'); K.MapPlaceDetails = byName('Niantic.Holoholo', 'MapPlaceDetails');
      K.GymStatusAndDefendersProto = byName('Holoholo.Rpc', 'GymStatusAndDefendersProto'); K.GymFeedPokemonOutProto = byName('Holoholo.Rpc', 'GymFeedPokemonOutProto');
      var gdefk = byName('Holoholo.Rpc', 'GymDefenderProto'), mpk = byName('Holoholo.Rpc', 'MotivatedPokemonProto');
      if (!K.MapPlaceDetailsService || !K.MapPlaceDetails || !K.GymStatusAndDefendersProto || !K.GymFeedPokemonOutProto || !gdefk || !mpk) { FEED_MISSING.push('classes'); return; }
      M.gymDetails = methodOn(K.MapPlaceDetailsService, 'RequestGymDetailsByIdWithRetries', 4);
      M.feed = methodOn(K.ItemBagImpl, 'UseItemOnGymDefender', 3);
      if (!M.gymDetails || !M.feed) { FEED_MISSING.push('methods'); return; }
      if (sigOf(M.feed) !== 'Holoholo.Rpc.Item,System.UInt64,System.String') { FEED_MISSING.push('feed signature ' + sigOf(M.feed)); return; }
      O.detailsParams = []; for (var qn = 0; qn < 4; qn++) O.detailsParams.push(cs(PNM(M.gymDetails, qn)));
      var sk = byName('System', 'String'), itS = Memory.alloc(PS), fdS; itS.writePointer(NULL);   /* a real, permanently rooted "" -- never NULL */
      while (sk && (fdS = CGF(sk, itS)) && !fdS.isNull()) if (cs(FGN(fdS)) === 'Empty') { var eb = Memory.alloc(PS); eb.writePointer(NULL); SGV(fdS, eb); EMPTY = eb.readPointer(); }
      if (!EMPTY || EMPTY.isNull()) { FEED_MISSING.push('String.Empty'); return; }
      var pt = f('il2cpp_method_get_param', 'pointer', ['pointer', 'uint32']), sig = [];
      for (var q = 0; q < 4; q++) sig.push(cs(TN(pt(M.gymDetails, q))));
      if (sig.join(',') !== 'System.String,Niantic.LatLng,System.String,System.Int32') { FEED_MISSING.push('details signature ' + sig.join(',')); return; }
      var rh = fieldBy(K.MapPlaceDetailsService, function (n, t) { return t === 'Niantic.Holoholo.Rpc.IRpcHandler'; });
      (function () {                           /* the buddy services (the user 2026-09-26) */
        var kr = byName('Niantic.Holoholo.Buddy', 'BuddyRpcService'), kp = byName('Niantic.Holoholo.Buddy', 'BuddyPokemonService');
        if (!kr || !kp) return;
        K.BuddyRpcService = kr; K.BuddyPokemonService = kp;
        M.bFeed = methodOn(kr, 'Feed', 2); M.bPet = methodOn(kr, 'Pet', 0); M.bStats = methodOn(kr, 'RequestBuddyStats', 0);
        M.bHist = methodOn(kr, 'RequestBuddyHistory', 0); M.bSet = methodOn(kp, 'SetBuddyPokemon', 1);
        M.bWho = methodOn(kp, 'get_BuddyPokemon', 0); M.bLeft = methodOn(kp, 'get_BuddySwapsLeft', 0);
        var hr = -1, hp = -1;
        fieldsOf(kr).forEach(function (x) { if (cs(IL.typeName(x.t)) === 'Niantic.Holoholo.Rpc.IRpcHandler') hr = x.off; });
        fieldsOf(kp).forEach(function (x) { if (cs(IL.typeName(x.t)) === 'Niantic.Holoholo.Rpc.IRpcHandler') hp = x.off; });
        var cr = [], cq = [];
        instances(kr, 4).forEach(function (o) { try { if (hr >= 0 && !o.add(hr).readPointer().isNull()) cr.push(o); } catch (e) {} });
        instances(kp, 4).forEach(function (o) { try { if (hp >= 0 && !o.add(hp).readPointer().isNull()) cq.push(o); } catch (e) {} });
        BUD.rpc = graphPick(cr, 'BuddyRpcService'); BUD.pok = graphPick(cq, 'BuddyPokemonService');
      })();
      var ds = []; instances(K.MapPlaceDetailsService, 4).forEach(function (sv) { try { if (rh < 0 || !sv.add(rh).readPointer().isNull()) ds.push(sv); } catch (e) {} });
      DSVC = graphPick(ds, 'MapPlaceDetailsService');
      if (!DSVC) { FEED_MISSING.push('details service instance (live graph)'); return; }
      var gdk = null, rfk = null;
      fieldsOf(K.MapPlaceDetails).forEach(function (x) { if (x.name === 'GymDetails') { O.mpdGym = x.off; gdk = IL.classFromType(x.t); } if (x.name === 'Name') O.mpdName = x.off; });
      O.mgdStatus = gdk ? fieldBy(gdk, function (n, t) { return n === 'Status' && t === 'Holoholo.Rpc.GymStatusAndDefendersProto'; }) : -1;
      fieldsOf(K.GymStatusAndDefendersProto).forEach(function (x) { if (x.name === 'PokemonFortProto') O.sadFort = x.off; if (x.name === 'GymDefender') { O.sadDef = x.off; rfk = IL.classFromType(x.t); } });
      if (rfk) { O.rfArr = fieldBy(rfk, function (n) { return n === 'array'; }); O.rfCount = fieldBy(rfk, function (n) { return n === 'count'; }); }
      if (!(O.rfArr > 0 && O.rfCount > 0 && O.rfArr !== O.rfCount)) { O.rfArr = 16; O.rfCount = 24; }   /* ponytail: RepeatedField<T>{T[] array; int count} if the inflated class is not laid out yet */
      O.gdMot = fieldBy(gdefk, function (n) { return n === 'MotivatedPokemon'; });
      O.mpPoke = fieldBy(mpk, function (n) { return n === 'Pokemon'; }); O.mpMot = fieldBy(mpk, function (n, t) { return n === 'MotivationNow' && t === 'System.Double'; });
      O.mpCp = fieldBy(mpk, function (n) { return n === 'CpNow'; });
      O.mpCpDep = fieldBy(mpk, function (n, t) { return n === 'CpWhenDeployed' && t === 'System.Int32'; });
      O.mpCool = fieldBy(mpk, function (n, t) { return n === 'FeedCooldownDurationMillis' && t === 'System.Int64'; });
      O.mpDeploy = fieldBy(mpk, function (n, t) { return n === 'DeployMs' && t === 'System.Int64'; });
      O.mpBerry = fieldBy(mpk, function (n, t) { return n === 'BerryValue' && t === 'System.Single'; });
      O.mpFood = fieldBy(mpk, function (n) { return n === 'FoodValue'; });
      var fvk = byName('Holoholo.Rpc', 'FoodValue');
      O.fvMot = fvk ? fieldBy(fvk, function (n, t) { return n === 'MotivationIncrease' && t === 'System.Single'; }) : -1;
      O.fvItem = fvk ? fieldBy(fvk, function (n) { return n === 'FoodItem'; }) : -1;
      if (O.fvMot < 0 || O.fvItem < 0) O.mpFood = -1;   /* (optional: without it the feeder simply does not know the allowance) */
      O.gfoStatus = fieldBy(K.GymFeedPokemonOutProto, function (n, t) { return n === 'GymStatusAndDefenders' && t === 'Holoholo.Rpc.GymStatusAndDefendersProto'; });
      O.gfoCool = fieldBy(K.GymFeedPokemonOutProto, function (n, t) { return n === 'CooldownComplete' && t === 'System.Int64'; });
      O.gfoDust = fieldBy(K.GymFeedPokemonOutProto, function (n, t) { return n === 'StardustAwarded' && t === 'System.Int32'; });
      O.gfoXp = fieldBy(K.GymFeedPokemonOutProto, function (n, t) { return n === 'XpAwarded' && t === 'System.Int32'; });
      fieldsOf(K.GymFeedPokemonOutProto).forEach(function (x) { if (x.name === 'Result') { O.gfoRes = x.off; var l = enumLits(IL.classFromType(x.t)); LIT.feedResName = {}; for (var nm in l) LIT.feedResName[l[nm]] = nm; } });
      ['mpdGym', 'mgdStatus', 'sadFort', 'sadDef', 'gdMot', 'mpPoke', 'mpMot', 'mpCp', 'gfoRes', 'gfoStatus', 'gfoCool'].forEach(function (x) { if (O[x] === undefined || O[x] < 0) FEED_MISSING.push(x); });
      ['deployedGymLatDegree', 'deployedGymLngDegree'].forEach(function (x) { if (protoOffs()[x] === undefined) FEED_MISSING.push('PokemonProto.' + x); });
      if (ITEM.GoldenRazzBerry === undefined) FEED_MISSING.push('Item.GoldenRazzBerry');
      var exk = byName('System', 'Exception'); O.excMsg = exk ? fieldBy(exk, function (n) { return n === '_message'; }) : -1;
      if (FEED_MISSING.length) { DSVC = null; M.feed = M.gymDetails = null; }
    })();
    (function () {                             /* which Text fields to read on which screens (all optional) */
      var tk = byName('UnityEngine.UI', 'Text'); O.textM = tk ? fieldBy(tk, function (n) { return n === 'm_Text'; }) : -1;
      [['PgoToastGuiController', ['message']], ['GlobalErrorController', ['errorMessage']], ['QuestUpdateToastGuiController', ['message']],
       ['ModalDialog', ['titleText', 'verticalMessage', 'horizontalMessage']]].forEach(function (e) {
        var k = byName('Niantic.Holoholo.UI', e[0]); if (!k) return;
        var offs = e[1].map(function (f) { return fieldBy(k, function (n) { return n === f; }); }).filter(function (o) { return o >= 0; });
        if (offs.length) SAYS[e[0]] = offs; });
    })();
    /* hooks: three, and none of them acts */
    var lu = methodOn(K.Scheduler, 'LateUpdate');
    Interceptor.attach(lu.readPointer(), function () { if (QUIET) return; frameTick(); });   /* PROBE form: no return trap on the game's unwind path */
    var rf = fieldBy(K.GymBattleResultsState, function (n) { return n === 'dramaticFaintSeconds'; }), rd = fieldBy(K.GymBattleResultsState, function (n) { return n === 'cpDrainWaitSeconds'; });
    var re = methodOn(K.GymBattleResultsState, 'EnterState');
    /* the knockout camera (zoom / tilt / attacker move, 1.0 s each on 0.429.1) -- same plain-write treatment */
    var rc = fieldBy(K.GymBattleResultsState, function (n, t) { return t === 'Niantic.Holoholo.Gym.Battle.GymBattleResultsCameraController'; }), CAM = [];
    if (rc >= 0) { var ck = byName('Niantic.Holoholo.Gym.Battle', 'GymBattleResultsCameraController');
      if (ck) ['cameraZoomSeconds', 'cameraTiltSeconds', 'attackerMoveSeconds'].forEach(function (nm) { var o = fieldBy(ck, function (n, t) { return n === nm && t === 'System.Single'; }); if (o >= 0) CAM.push([nm, o]); }); }
    if (re && rf >= 0 && rd >= 0 && MCLS(re).equals(K.GymBattleResultsState)) Interceptor.attach(re.readPointer(), function (a) { if (QUIET) return;   /* faint / CP-drain timers, shorter */
      try { if (!a[0].readPointer().equals(K.GymBattleResultsState)) return;
        var st = a[0], f0 = st.add(rf).readFloat(), d0 = st.add(rd).readFloat(), cam = {};
        if (f0 > FAST_RESULTS) st.add(rf).writeFloat(FAST_RESULTS); if (d0 > FAST_RESULTS) st.add(rd).writeFloat(FAST_RESULTS);
        var cc = rc >= 0 ? st.add(rc).readPointer() : NULL;
        if (!cc.isNull()) CAM.forEach(function (c) { var v = cc.add(c[1]).readFloat(); cam[c[0]] = v; if (v > FAST_CAMERA) cc.add(c[1]).writeFloat(FAST_CAMERA); });
        if (!TIMERS_TOLD) { TIMERS_TOLD = true; send({k: 'timers', faint: f0, drain: d0, camera: cam}); } } catch (e) {} });
    if (M.startBattle && MCLS(M.startBattle).equals(K.GymBattleState)) Interceptor.attach(M.startBattle.readPointer(), function (a) { if (QUIET) return;
      try {
        var now = Date.now(); if (a[1].isNull() || !TEAMP || now - TEAM_AT > 15000) return;
        if (!a[0].readPointer().equals(K.GymBattleState) || !a[1].readPointer().equals(K.GymBattleLaunchData)) return;
        var arr = a[1].add(O.ldTeam).readPointer(); if (arr.isNull()) return;
        var o = protoOffs(), len = arr.add(24).readU32(), base = arr.add(32), orig = [], have = {};
        for (var i = 0; i < len; i++) orig.push(base.add(i * PS).readPointer());
        var out = TEAMP.filter(function (t) { try { return t.p.readPointer().equals(K.PokemonProto) && t.p.add(o.id).readU64().toString() === t.id && usable(t.p, o); } catch (e) { return false; } })
          .slice(0, len).map(function (t) { have[t.id] = 1; return t.p; });
        var mine = out.length;
        orig.forEach(function (q) { if (out.length < len && !q.isNull() && !have[q.add(o.id).readU64().toString()]) out.push(q); });   /* short: the game's own picks fill in */
        for (var j = 0; j < out.length; j++) { if (WB) WB(arr, base.add(j * PS), out[j]); else base.add(j * PS).writePointer(out[j]); }
        ACTIVE = {}; ACTIVE_AT = now; out.forEach(function (q) { ACTIVE[q.add(o.id).readU64().toString()] = 1; });
        TEAMP = null;
        send({k: 'team', mine: mine, ids: out.map(function (q) { return q.add(o.id).readU64().toString(); }),
          cps: out.map(function (q) { return q.add(o.cp).readS32(); }), was: orig.map(function (q) { return q.isNull() ? 0 : q.add(o.cp).readS32(); })});
      } catch (e) { send({k: 'err', e: 'team ' + e}); } });
    var grs = byName('Niantic.Holoholo.Gym', 'GymRotationState'), grt = grs ? fieldBy(grs, function (n, t) { return n === 'approachRotationTime' && t === 'System.Single'; }) : -1;
    var gre = grs ? methodOn(grs, 'EnterState') : null;
    if (gre && grt >= 0 && MCLS(gre).equals(grs)) Interceptor.attach(gre.readPointer(), function (a) { if (QUIET) return;
      try { if (!a[0].readPointer().equals(grs)) return; var v = a[0].add(grt).readFloat(); if (v > FAST_ROTATE) { a[0].add(grt).writeFloat(FAST_ROTATE);
        if (!ROT_TOLD) { ROT_TOLD = true; send({k: 'info', what: 'gym-open camera spin', layout: v.toFixed(2) + ' s -> ' + FAST_ROTATE + ' s'}); } } } catch (e) {} });
    (function () {                             /* the deploy reply's own Result: probe hook, plain reads only */
      try {                                   /* direct deploy: the request class, its fields, the rpc handler, the reply's Result */
        K.GymDeployProto = byName('Holoholo.Rpc', 'GymDeployProto'); K.GymDeployOutProto = byName('Holoholo.Rpc', 'GymDeployOutProto');
        O.gdpFort = fieldBy(K.GymDeployProto, function (n, t) { return n === 'FortId' && t === 'System.String'; });
        O.gdpPoke = fieldBy(K.GymDeployProto, function (n, t) { return n === 'PokemonId' && t === 'System.UInt64'; });
        O.gdpLat = fieldBy(K.GymDeployProto, function (n, t) { return n === 'PlayerLatDegrees' && t === 'System.Double'; });
        O.gdpLng = fieldBy(K.GymDeployProto, function (n, t) { return n === 'PlayerLngDegrees' && t === 'System.Double'; });
        O.mpdsRpc = fieldBy(K.MapPlaceDetailsService, function (n, t) { return t === 'Niantic.Holoholo.Rpc.IRpcHandler'; });
        M.gdpCtor = methodOn(K.GymDeployProto, '.ctor', 0);
        LIT.deployResName = {}; fieldsOf(K.GymDeployOutProto).forEach(function (x) { if (x.name === 'Result') { O.gdoRes = x.off;
          var l = enumLits(IL.classFromType(x.t)); for (var nm in l) LIT.deployResName[l[nm]] = nm; } });
        DD_OK = !!(K.GymDeployProto && K.GymDeployOutProto && M.gdpCtor && O.gdpFort >= 0 && O.gdpPoke >= 0 && O.gdpLat >= 0 && O.gdpLng >= 0
                   && O.mpdsRpc >= 0 && O.gdoRes !== undefined && OBJNEW && WB);
      } catch (e) { DD_OK = false; }
      var dk = byName('Holoholo.Rpc', 'GymDeployOutProto'), ce = methodOn(K.GymApproachGuiController, 'cage', 2);
      if (!dk || !ce || !MCLS(ce).equals(K.GymApproachGuiController)) return;
      var pt = f('il2cpp_method_get_param', 'pointer', ['pointer', 'uint32']);
      if (cs(TN(pt(ce, 1))) !== 'Holoholo.Rpc.GymDeployOutProto') return;
      var ro = -1, names = {}; fieldsOf(dk).forEach(function (x) { if (x.name === 'Result') { ro = x.off; var l = enumLits(IL.classFromType(x.t)); for (var nm in l) names[l[nm]] = nm; } });
      if (ro < 0) return;
      Interceptor.attach(ce.readPointer(), function (a) { if (QUIET) return;
        try { if (!a[2].isNull() && a[2].readPointer().equals(dk)) { var r = a[2].add(ro).readS32();
          if (r !== 1) PLACED = null;                /* refused: nothing is in flight any more (a retry may fire at once) */
          send({k: 'deployresult', res: names[r] || String(r), ok: r === 1}); } } catch (e) {} });
    })();
    var rg = methodOn(K.GuiLayerService, 'RegisterGui', 2), ug = methodOn(K.GuiLayerService, 'UnregisterGui', 1);
    if (rg) Interceptor.attach(rg.readPointer(), function (a) { if (QUIET) return;   /* pure memory reads only: no il2cpp call inside a hook */
      try { var g = a[1], k = g.readPointer(), nm = cs(k.add(0x10).readPointer()); GUIS[g] = nm;
        if (POPUPS.indexOf(nm) >= 0) POPQ.push({gui: g, k: k, name: nm, at: Date.now() + 700}); } catch (e) {} });
    if (ug) Interceptor.attach(ug.readPointer(), function (a) { if (QUIET) return;
      try { var u = a[1]; delete GUIS[u]; delete CONT_DONE[u]; delete SKIP_DONE[u]; delete OUTCOME_SEEN[u];
        POPQ = POPQ.filter(function (d) { return !d.gui.equals(u); }); } catch (e) {} });
    return {ok: true, gyms: dirGyms().length, root: String(ROOT), guiLayer: GLS_CANDS.length, open: LIT.open, autoplace: !!M.pickHandler,
      team: TEAM_MISSING.length ? TEAM_MISSING : true, feed: FEED_MISSING.length ? FEED_MISSING : true, detailsParams: O.detailsParams || null, range: RANGE, graph: GRAPH, graphNotes: GRAPH_NOTES,
      stab: stabReport()};
  },
  stab: function (cfg) { return loadStab(cfg); },   /* the client game master's same-type multiplier + typing table, handed over by the runner (gym_tapper.stab_config) */
  open: function (fid) { if (/GymRootState|GymRotationState/.test(CHAIN)) return {known: !!GYMS[fid], busy: true};   /* a gym is opening/open */
    PENDING = fid; PENDING_AT = Date.now(); return {known: !!GYMS[fid]}; },
  autodeploy: function (fid, ids, friendly, team) { if (team) MYTEAM = team;
    AUTODEP = fid ? {fid: fid, at: Date.now(), cands: (ids || []).map(String), friendly: !!friendly} : null;
    return {armed: !!AUTODEP, auto: !!(AUTODEP && AUTODEP.cands.length && M.pickHandler && IBAG)}; },
  roster: function (ids, healN, extra, gyids) { ROSTER = ids.map(function (x) { return {id: String(x)}; }); HEAL_N = healN;
    if (gyids) GYIDS = gyids.map(String);
    if (extra && extra.length) HEALX = extra.map(function (x) { return {id: String(x), full: true}; });
    return {n: ROSTER.length, live: !!IBAG, batch: HEALX.length}; },
  defenders: function (ids) { var now = Date.now(), added = 0;
    ids.forEach(function (x, i) { x = String(x); if (!DEFS[x]) { DEFS[x] = {nextAt: now + 1500 * i}; added++; } }); return {watching: Object.keys(DEFS).length, added: added, live: !!DSVC}; },
  bag: function () { var b = pbag(); return b.isNull() ? null : String(b); },   /* the live bag -- no world-stopping liveness walk */
  feedzone: function (lat, lng, r) { FEED_ZONE = lat === null ? null : {lat: lat, lng: lng, r: r};
    for (var k in DEFS) DEFS[k].nextAt = 0; return FEED_ZONE; },
  quiesce: function () { QUIET = true; return !BUSY; },
  buddy: function (what, arg) { BUD.q.push({what: what, arg: arg}); return {queued: BUD.q.length, ready: {rpc: !!BUD.rpc, pok: !!BUD.pok, feed: !!M.bFeed, set: !!M.bSet, stats: !!M.bStats}}; },
  pos: function (lat, lng) { LASTPOS = [lat, lng]; return DD_OK; },
  fastreport: function (ivl) {                /* the battle reports attacks every AttackServerInterval s (server setting: 5). Between a
                                                 knockout and the next report the server says NOT in battle -- 4-7 s windows others can deploy in */
    var k = byName('Holoholo.Rpc', 'GymBattleSettingsProto'); if (!k || !(ivl > 0)) return {ok: false};
    var off = -1; fieldsOf(k).forEach(function (x) { if (x.name === 'AttackServerInterval') off = x.off; });
    if (off < 0) return {ok: false};
    var was = []; instances(k, 4).forEach(function (o) { try { was.push(o.add(off).readFloat()); o.add(off).writeFloat(ivl); } catch (e) {} });
    return {ok: was.length > 0, was: was, now: ivl}; },
  study: function (on) { STUDY = !!on; return STUDY; },
  topup: function (on, reserve) { TOPUP_ON = !!on; if (reserve !== undefined && reserve !== null) TOPUP_RESERVE = reserve;
    var c = {}; TOPUP_BERRIES.forEach(function (nm) { if (ITEM[nm] !== undefined) c[nm] = itemCount(ITEM[nm]); });
    return {on: TOPUP_ON, reserve: TOPUP_RESERVE, berries: c}; },
  scan: function (fids) { (fids || []).forEach(function (f) { if (SCANQ.indexOf(f) < 0 && !SCANREQ[f]) SCANQ.push(f); }); return SCANQ.length; },
  scanned: function () { var o = {}, now = Date.now(); for (var f in SCAN) { var v = SCAN[f]; o[f] = [v.team, now - v.at, v.ib, v.n, v.cp, v.ours, v.mots, v.name || '']; } return o; },
  feedcfg: function (on, at, hotAt, mate) { FEED_ON = !!on; FEED_AT = at; if (hotAt) HOT_FEED_AT = hotAt; if (mate !== undefined) MATE_ON = !!mate; return {on: FEED_ON && !!DSVC, at: FEED_AT, hot: HOT_FEED_AT}; },
  act: function (what) { ACT = what; ACT_AT = Date.now(); return {gymScreen: !!GAS, inBattle: IN_BATTLE}; },
  teams: function () { var now = Date.now(), o = {}; for (var k in GTEAM) { var v = GTEAM[k]; o[k] = [v[0], now - v[1], v[2], v[3], Math.max(0, v[4] - now), v[5], v[6], v[7], Math.max(0, (v[8] || 0) - now), Math.max(0, (v[9] || 0) - now), v[11] || 0]; } return o; },   /* [7] total CP, [8] lockout ms left, [9] team lockout ms left */
  where: function () { return {chain: CHAIN, leaf: LEAF, top: TOP, inBattle: IN_BATTLE, round: ROUND, prepOpen: prepOpen()}; },
  info: function () { return {gyms: Object.keys(GYMS).length, map: Object.keys(GTEAM).length, fast: ST.fast, charged: ST.charged}; }
};
""".replace("__ACT__", str(ACT_MS))

GM_PATH = os.path.join(os.path.dirname(os.path.dirname(HERE)), "pogo_extract", "gamemaster_pokeminers.json")   # the client game master (read-only data)
FORM_ENUM_PATH = os.path.join(os.path.dirname(os.path.dirname(HERE)), "pogo_extract", "form_enum.json")        # the game's own Form enum (tracked)
_STAB_CFG = {}


def stab_config(gm_path=None, enum_path=None):
    """The client game master's same-type multiplier and typing table, for the tapper's stab() export (2026-09-30, Benny: "fix it").
    Read-only; never raises (a missing file comes back as {"err": ...}: the runner carries on with the live read alone).

      {"mult": 1.2, "types": {"150": ["PSYCHIC"], "484": ["WATER", "DRAGON"], "26:50": ["ELECTRIC", "PSYCHIC"], ...},
       "names": {150: "Mewtwo", ...}, "species": 1024, "forms": 117, "unmapped": 0}

    Key "<dex>" = the species' plain typing (its game master template with no form). Key "<dex>:<form>" = a form whose typing differs
    (Alolan / Galarian / Hisuian / Paldean, Arceus and Silvally types, Rotom, Castform, ...), <form> = the game's own Form enum value
    (form_enum.json; the game master spells a form MEWTWO_A where the enum says MewtwoA, so both are matched letters-and-digits only).
    The game master is the client's 0.427.0 and the game is newer: a species or form it lacks is simply absent here, and the tapper then
    has no table types for it (the live read, or no boost). Types are the game master's names without the POKEMON_TYPE_ prefix; the
    tapper turns them into the live HoloPokemonType enum values itself."""
    gm_path, enum_path = gm_path or GM_PATH, enum_path or FORM_ENUM_PATH
    if (gm_path, enum_path) in _STAB_CFG:
        return _STAB_CFG[(gm_path, enum_path)]
    try:
        with open(gm_path, encoding="utf-8") as f:
            gm = json.load(f)
        with open(enum_path, encoding="utf-8") as f:
            enum = json.load(f)
    except (OSError, ValueError) as e:                                   # (not cached: a data pull may bring the file)
        return {"err": f"{type(e).__name__}: {e}", "hint": "python tools/pogo_data.py pull --group inventory brings pogo_extract/gamemaster_pokeminers.json"}
    norm = lambda x: re.sub(r"[^A-Z0-9]", "", str(x).upper())
    by_form = {}
    for k, v in enum.items():
        by_form.setdefault(norm(v), []).append(int(k))
    base, forms, names, mult = {}, {}, {}, None
    for t in gm:
        d = t.get("data") or {}
        if t.get("templateId") == "BATTLE_SETTINGS":
            mult = (d.get("battleSettings") or {}).get("sameTypeAttackBonusMultiplier")
        s, m = d.get("pokemonSettings"), re.match(r"V(\d{4})_POKEMON_", t.get("templateId", ""))
        if not s or not m:
            continue
        dex = int(m.group(1))
        types = [x.replace("POKEMON_TYPE_", "") for x in (s.get("type"), s.get("type2")) if x]
        if s.get("form"):
            forms.setdefault(dex, {})[norm(s["form"])] = types
        else:
            base[dex] = types
            names[dex] = str(s.get("pokemonId") or "").replace("_", " ").title()
    table = {str(dex): types for dex, types in base.items() if types}
    nforms = unmapped = 0
    for dex, fs in forms.items():
        for form, types in fs.items():
            if not types or types == base.get(dex):
                continue                                                  # the species' own typing: no entry needed
            if form not in by_form:
                unmapped += 1
                continue
            for code in by_form[form]:
                table[f"{dex}:{code}"] = types
                nforms += 1
    try:
        mult = float(mult)
    except (TypeError, ValueError):
        mult = None
    cfg = {"mult": mult if mult and 1 < mult <= 2 else None, "types": table, "names": names, "species": len(base), "forms": nforms,
           "unmapped": unmapped}
    _STAB_CFG[(gm_path, enum_path)] = cfg
    return cfg
