"""Offline check of the live-service-graph pick (H01, 2026-09-29): runs the REAL live_graph_js block under node against mock
il2cpp objects, and checks that gym_tapper and buddy_tapper both carry it. No phone. Run: python test_graph_pick.py"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buddy_tapper  # noqa: E402
import gym_tapper  # noqa: E402
import live_graph_js  # noqa: E402

for mod in (gym_tapper, buddy_tapper):
    assert mod.JS.count(live_graph_js.JS) == 1, f"{mod.__name__} must include live_graph_js.JS exactly once"
MOCK = r"""
var NULLP = {isNull: function () { return true; }, toString: function () { return '0x0'; }};
var REG = {};
function P(id, klass, fields) {                 /* a mock object: readPointer() = its klass; add(off) = its fields */
  var o = {fields: fields || {}, isNull: function () { return false; }, toString: function () { return id; },
    readPointer: function () { return klass; },
    add: function (off) { var f = o.fields[off]; return {readPointer: function () { return f || NULLP; },
      readS64: function () { return {toNumber: function () { return f; }}; }}; }};
  REG[id] = o; return o;
}
function ptr(s) { return REG[s]; }
var TYPES = {ItemBagImpl: [['cuwm', 'Niantic.Holoholo.IPlayerService', 48], ['cuwj', 'Niantic.Holoholo.Collections.InventoryCache', 64],
                           ['cuwq', 'Niantic.Holoholo.IPokemonBag', 72]],
             InventoryCache: [['latestTimestamp', 'System.Int64', 24]],
             BuddyRpcService: [['h', 'Niantic.Holoholo.Rpc.IRpcHandler', 16], ['ps', 'Niantic.Holoholo.IPlayerService', 24],
                               ['ic', 'Niantic.Holoholo.Collections.InventoryCache', 32]],
             MapPlaceDetailsService: [['h', 'Niantic.Holoholo.Rpc.IRpcHandler', 16]]};
function fieldsOf(k) { return (TYPES[k] || []).map(function (x) { return {name: x[0], tn: x[1], off: x[2]}; }); }
function ok(c, m) { if (!c) { console.log('FAIL: ' + m); process.exit(1); } }
function graph(tag, ts) {                        /* one service graph: player, inventory (with its timestamp), pokemon bag, item bag */
  var pl = P(tag + 'pl', 'PlayerService'), inv = P(tag + 'inv', 'InventoryCache', {24: ts}), pb = P(tag + 'pb', 'PokemonBagImpl');
  return {pl: pl, inv: inv, ib: P(tag + 'ib', 'ItemBagImpl', {48: pl, 64: inv, 72: pb})};
}
"""
TESTS = r"""
var OLD = graph('old', 1000), NEW = graph('new', 5000);
ok(pickGraph([OLD.ib, NEW.ib]) === NEW.ib, 'newest inventory timestamp wins');
ok(GRAPH.inv === 'newinv' && GRAPH.graphs === 2 && GRAPH.other[0] === 1000, 'GRAPH describes the live graph + the stale one');
ok(pickGraph([NEW.ib, OLD.ib]) === NEW.ib, 'order does not matter (never the first hit)');
var live = P('s2', 'BuddyRpcService', {16: P('h2', 'RpcHandler'), 24: NEW.pl}), stale = P('s1', 'BuddyRpcService', {16: P('h1', 'RpcHandler'), 24: OLD.pl});
ok(graphPick([stale, live], 'buddy') === live, 'the service tied to the live PlayerService');
GRAPH_NOTES = [];
ok(graphPick([stale], 'buddy') === null && GRAPH_NOTES.length === 1, 'a lone service of the STALE graph is refused');
GRAPH_NOTES = [];
var mixed = P('s3', 'BuddyRpcService', {16: P('h3', 'RpcHandler'), 24: NEW.pl, 32: OLD.inv});   /* live player, STALE inventory */
ok(graphPick([mixed], 'buddy') === null && GRAPH_NOTES.length === 1, 'a service with a contradicting reference is refused (partial rebuild)');
ok(graphPick([mixed, live], 'buddy') === live, 'the consistent live service wins over a contradicting one');
GRAPH_NOTES = [];
var d1 = P('d1', 'MapPlaceDetailsService', {16: P('dh1', 'RpcHandler')}), d2 = P('d2', 'MapPlaceDetailsService', {16: P('dh2', 'RpcHandler')});
ok(graphPick([d1], 'details') === d1, 'one instance with no graph reference: nothing to confuse it with');
ok(graphPick([d1, d2], 'details') === null && GRAPH_NOTES.length === 1, 'two unreferenced instances are refused, not guessed');
GRAPH = null; GRAPH_NOTES = [];
var A = graph('a', 7000), B = graph('b', 7000);
ok(pickGraph([A.ib, B.ib]) === null && GRAPH === null && GRAPH_NOTES.length === 1, 'a timestamp tie is refused');
GRAPH_NOTES = [];
var U1 = graph('u1', -1), U2 = graph('u2', -1);
ok(pickGraph([U1.ib, U2.ib]) === null && GRAPH_NOTES.length === 1, 'two graphs with unreadable timestamps are refused');
ok(pickGraph([U1.ib]) === U1.ib && GRAPH.ts === -1, 'a single graph is used even without a readable timestamp');
ok(pickGraph([]) === null, 'no candidates -> null');
console.log('ok: 13 live-graph checks passed; gym_tapper + buddy_tapper both carry the shared block');
"""
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(MOCK + live_graph_js.JS + TESTS)
try:
    r = subprocess.run(["node", f.name], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    sys.exit(r.returncode)
finally:
    os.unlink(f.name)
