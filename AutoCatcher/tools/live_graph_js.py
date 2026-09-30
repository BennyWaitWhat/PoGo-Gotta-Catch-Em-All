"""The LIVE service graph pick, shared by gym_tapper.py and buddy_tapper.py (JS, concatenated after dump_game_limits' prefix).

The Inventory session's finding H01 (2026-09-29): PoGo can rebuild every service inside the same process; the old objects stay
allocated with frozen contents and answer calls like live ones. The live graph = the one whose InventoryCache.latestTimestamp (last
server inventory update, ms) is newest -- the rule proven in pogo_extract/pogo_il2cpp.py live_graph / _same_graph_pick. A tie, or a
service that cannot be tied to the live graph, is REFUSED (null + a note), never guessed: first hit / biggest is how a cull read a
frozen bag four times. Needs only fieldsOf (dump_game_limits) and plain memory reads. test_graph_pick.py runs it under node."""

JS = r"""
/* ---- THE LIVE SERVICE GRAPH (live_graph_js.py; H01, 2026-09-29) ---- */
var GRAPH = null, GRAPH_NOTES = [];
var GREF = [['player', /(^|\.)I?PlayerService$/], ['inv', /(^|\.)I?InventoryCache$/], ['bag', /(^|\.)I?PokemonBag$/]];
function gField(k, pred) { var fs = fieldsOf(k); for (var i = 0; i < fs.length; i++) if (pred(fs[i].name, fs[i].tn)) return fs[i].off; return -1; }
function graphRefs(o) {                       /* this object's PlayerService / InventoryCache / PokemonBag pointers (plain reads) */
  var k = o.readPointer(), out = {};
  GREF.forEach(function (r) { var off = gField(k, function (n, t) { return r[1].test(t); });
    if (off >= 0) { var q = o.add(off).readPointer(); if (!q.isNull()) out[r[0]] = q.toString(); } });
  return out;
}
function invTs(inv) {                         /* InventoryCache.latestTimestamp (ms), or -1 */
  try { var q = ptr(inv), to = gField(q.readPointer(), function (n) { return n === 'latestTimestamp'; });
    return to < 0 ? -1 : q.add(to).readS64().toNumber(); } catch (e) { return -1; }
}
function graphPick(cands, label) {            /* the candidate of the live graph, or null + a note (never the first hit) */
  var mine = cands.filter(function (o) { try { var r = graphRefs(o), hit = 0, clash = 0;
      GREF.forEach(function (g) { var k = g[0]; if (r[k] && GRAPH && GRAPH[k]) { if (r[k] === GRAPH[k]) hit++; else clash++; } });
      return hit > 0 && clash === 0; } catch (e) { return false; } });   /* >= 1 link to the live graph AND none to another one */
  if (mine.length) return mine[0];
  if (cands.length === 1) { try { if (!Object.keys(graphRefs(cands[0])).length) return cands[0]; } catch (e) {} }   /* one, nothing to confuse it with */
  GRAPH_NOTES.push(label + ': ' + cands.length + ' instance(s), none tied to the live graph -- refused, not guessed');
  return null;
}
function pickGraph(cands) {                   /* the ItemBagImpl of the NEWEST graph (sets GRAPH), or null + a note on a tie */
  var rk = cands.map(function (b) { var r = {}; try { r = graphRefs(b); } catch (e) {} return {b: b, r: r, ts: r.inv ? invTs(r.inv) : -1}; })
                .sort(function (x, y) { return y.ts - x.ts; });
  if (rk.length === 1 || (rk.length > 1 && rk[0].ts > 0 && rk[0].ts > rk[1].ts)) {
    GRAPH = {player: rk[0].r.player || null, inv: rk[0].r.inv || null, bag: rk[0].r.bag || null, ts: rk[0].ts,
      graphs: rk.length, other: rk.slice(1).map(function (x) { return x.ts; })};
    return rk[0].b;
  }
  if (rk.length) GRAPH_NOTES.push('ItemBagImpl: ' + rk.length + ' service graphs, inventory timestamps '
    + rk.map(function (x) { return x.ts; }).join(' / ') + ' -- no newest one, refused (never the first or the biggest)');
  return null;
}
/* ---- end of the live-graph helpers ---- */
"""
