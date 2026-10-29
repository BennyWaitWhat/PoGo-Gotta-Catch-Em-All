// Offline test of catch_loop_fast.py's apple module (appleTick/apNote/apReply), node. Usage: python tools/catcher_apple_sim.py
// Each scenario states what it expects; any mismatch prints FAIL and the exit code is 1.
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
let failed = 0;
function run(name, opts, want) {
  let WORLD = {}, taps = [], NOW = 1790716800000;
  const pending = [];
  const NUL = { isNull: () => true, toString: () => '0x0' };
  const P = (k) => ({ k, toString: () => k, isNull: () => false,
    add: () => ({ readU64: () => ({ toString: () => String((WORLD[k] || {}).enc) }), readU8: () => ((WORLD[k] || {}).isEnc ? 1 : 0), readPointer: () => ({ isNull: () => false }) }) });
  const api = new Function('ptr', 'Process', 'Memory', 'Interceptor', 'NativeFunction', 'NativeCallback', 'CModule', 'NULL', 'rpc', 'Date',
    src + `;return {get:(k)=>eval(k), set:(k,v)=>eval(k+'=v'), tick:(n)=>appleTick(n), note:(p)=>apNote(p), reply:(...a)=>apReply(...a)};`)(
    P, { pointerSize: 8 }, { alloc: () => ({ writePointer: () => {}, readPointer: () => NUL }) }, {}, function () {}, function () {}, function () {}, NUL, {},
    { now: () => NOW });
  api.set('S', { avatar: { isNull: () => false } });
  api.set('avatarPos', () => ({ lat: 40.7, lng: -74.0 }));
  api.set('apRead', (o) => { const c = WORLD[o.k]; return c ? Object.assign({ ready: true }, c) : null; });
  api.set('AP.f', { enc: 0, isEnc: 0, gesture: 0 }); api.set('AP.handler', {}); api.set('AP.ev', { isNull: () => false });
  api.set('AP.names', { 1151: 'Sweet Apple', 1152: 'Tart Apple', 1155: 'Syrupy Apple' });
  api.set('call', (m, o) => { taps.push(Number(WORLD[o.k].enc)); api.set('LASTOK', true); if (opts.onTap) opts.onTap(o.k, WORLD, pending, api, NOW); return null; });
  for (let step = 0; step < 400; step++) {
    NOW += 300;                                   // pump runs appleTick every 300 ms
    while (pending.length) { const r = pending.shift(); api.reply(r.sk, r.st, r.items || [], r.sp === undefined ? -1 : r.sp, -1, null, NOW); }
    if (opts.script) opts.script(step, WORLD, api, NOW);
    Object.keys(WORLD).forEach((k) => api.note(P(k)));
    api.tick(NOW);
  }
  const st = api.get('AP.st');
  const got = { taps, range: api.get('AP.maxDist'), items: st.items, dup: st.dup || 0, mons: st.mons, skipped: st.skipped || 0 };
  const bad = Object.keys(want).filter((k) => JSON.stringify(got[k]) !== JSON.stringify(want[k]));
  if (bad.length) failed++;
  console.log((bad.length ? 'FAIL ' : 'ok   ') + name.padEnd(12), 'taps', JSON.stringify(taps), 'range', got.range, 'items', JSON.stringify(got.items),
    'dup', got.dup, bad.length ? '  want ' + JSON.stringify(want) : '');
}
const at = (m) => ({ lat: 40.7 + m / 111195, lng: -74.0 });   // m metres north of the avatar
const near = at(11), far = at(1100);
const mk = (enc, x) => Object.assign({ enc: String(enc), isEnc: false, type: 'TAPPABLE_TYPE_MAPLE', despawn: 1790716800000 + 600000 }, near, x || {});
const gone = (k, W) => { delete W[k]; };
run('expired', { script: (s, W) => { if (s === 0) W.p1 = mk(1, { despawn: 1790716800000 - 60000 }); } }, { taps: [] });
run('live-once', { script: (s, W) => { if (s === 0) W.p1 = mk(2); }, onTap: gone }, { taps: [2] });
run('live-stays', { script: (s, W) => { if (s === 0) W.p1 = mk(3); } }, { taps: [3] });
run('encounter', { script: (s, W) => { if (s === 0) W.p1 = mk(4, { isEnc: true }); } }, { taps: [] });   // nobody waits for its Pokemon
run('far', { script: (s, W) => { if (s === 0) W.p1 = mk(5, far); } }, { taps: [] });
run('two-apples', { script: (s, W) => { if (s === 0) { W.p1 = mk(6); W.p2 = mk(7); } }, onTap: gone }, { taps: [6, 7] });
run('pool-reuse', { script: (s, W) => { if (s === 0) W.p1 = mk(8, { despawn: 1790716800000 - 1 }); if (s === 100) W.p1 = mk(9); }, onTap: gone }, { taps: [9] });
run('route-pin', { script: (s, W) => { if (s === 0) W.p1 = mk(10, { type: 'TAPPABLE_TYPE_ROUTE_PIN' }); } }, { taps: [] });
run('event-type', { script: (s, W) => { if (s === 0) W.p1 = mk(18, { type: 'TAPPABLE_TYPE_HALLOWEEN' }); }, onTap: gone }, { taps: [18] });   // a new event's type is tapped too
run('not-ready', { script: (s, W) => { if (s === 0) W.p1 = mk(11, { ready: false }); if (s === 50) W.p1 = mk(11); }, onTap: gone }, { taps: [11] });
// RANGE (09-30): start at 150 m; the first NOT_IN_RANGE (status 4) shrinks it below that distance
run('range-122m', { script: (s, W) => { if (s === 0) W.p1 = mk(12, at(122)); }, onTap: gone }, { taps: [12], range: 150 });
run('beyond-150', { script: (s, W) => { if (s === 0) W.p1 = mk(13, at(167)); } }, { taps: [], range: 150 });
run('shrink', { script: (s, W) => { if (s === 0) W.p1 = mk(14, at(122)); if (s === 30) W.p2 = mk(15, at(50)); },
  onTap: (k, W, pend) => { if (W[k].enc === '14') pend.push({ sk: '0xa', st: 4 }); else delete W[k]; } }, { taps: [14, 15], range: 117 });
run('shrink-floor', { script: (s, W) => { if (s === 0) W.p1 = mk(16, at(120)); if (s === 20) W.p2 = mk(17, at(130)); },
  onTap: (k, W, pend) => { pend.push({ sk: '0x' + W[k].enc, st: W[k].enc === '16' ? 1 : 4 }); delete W[k]; } }, { taps: [16, 17], range: 125 });
// ITEMS (09-30): two taps with the same reward both count; the same reply object parsed twice counts once
run('same-reward', { script: (s, W, api, now) => {
  if (s === 1) { api.reply('0xa', 1, [[1152, 1]], -1, -1, null, now); api.reply('0xa', 1, [[1152, 1]], -1, -1, null, now + 5); }   // one reply, 2 parse passes
  if (s === 3) api.reply('0xb', 1, [[1152, 1]], -1, -1, null, now);                                                            // a 2nd tap, same reward
  if (s === 5) { api.reply('0xc', 1, [[1155, 1]], -1, -1, null, now); api.reply('0xd', 1, [[1155, 1]], -1, -1, null, now + 20); }   // + a clone 20 ms later
} }, { items: { 'Tart Apple': 2, 'Syrupy Apple': 1 }, dup: 2 });
// APPLE POKEMON (10-29, "skip the catch sequence"): a revealed Pokemon waiting on the map is never tapped -- a tap opens the
// game's encounter screen; catchTick opens it in the background instead
const waiting = (api, now) => api.set("E['20']", { st: 'new', firstSeen: now });
run('enc-untapped', { script: (s, W, api, now) => { if (s === 0) { W.p1 = mk(20, { isEnc: true }); waiting(api, now); } } }, { taps: [] });
// BOX POKEMON (10-29): our tap's reveal is emptied (skipped); its second parse pass reads the same items without the
// Pokemon and counts once. A reveal no tap of ours explains (a hand's tap) is left to the game.
run('box-skip', { script: (s, W) => { if (s === 0) W.p1 = mk(21, { type: 'TAPPABLE_TYPE_HALLOWEEN' }); },
  onTap: (k, W, pend) => { pend.push({ sk: '0xb', st: 1, items: [[25, 6]], sp: 92 }); pend.push({ sk: '0xb', st: 1, items: [[25, 6]] }); delete W[k]; } },
  { taps: [21], items: { 'item 25': 6 }, mons: 1, skipped: 1, dup: 1 });
run('hand-reveal', { script: (s, W, api, now) => { if (s === 1) api.reply('0xc', 1, [], 92, -1, null, now); } }, { taps: [], mons: 1, skipped: 0 });
process.exit(failed ? 1 : 0);
