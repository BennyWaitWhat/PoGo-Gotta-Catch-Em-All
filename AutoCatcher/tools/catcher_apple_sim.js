// Offline test of catch_loop_fast.py's apple module (appleTick/apNote), node. Usage: python tools/catcher_apple_sim.py
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
function run(name, opts) {
  let WORLD = {}, taps = [], NOW = 1790716800000;
  const NUL = { isNull: () => true, toString: () => '0x0' };
  const P = (k) => ({ k, toString: () => k, isNull: () => false,
    add: () => ({ readU64: () => ({ toString: () => String((WORLD[k] || {}).enc) }), readU8: () => ((WORLD[k] || {}).isEnc ? 1 : 0), readPointer: () => ({ isNull: () => false }) }) });
  const api = new Function('ptr', 'Process', 'Memory', 'Interceptor', 'NativeFunction', 'NativeCallback', 'CModule', 'NULL', 'rpc', 'Date',
    src + `;return {get:(k)=>eval(k), set:(k,v)=>eval(k+'=v'), tick:(n)=>appleTick(n), note:(p)=>apNote(p)};`)(
    P, { pointerSize: 8 }, { alloc: () => ({ writePointer: () => {}, readPointer: () => NUL }) }, {}, function () {}, function () {}, function () {}, NUL, {},
    { now: () => NOW });
  api.set('S', { avatar: { isNull: () => false } });
  api.set('avatarPos', () => ({ lat: 40.7, lng: -74.0 }));
  api.set('apRead', (o) => { const c = WORLD[o.k]; return c ? Object.assign({ ready: true }, c) : null; });
  api.set('AP.f', { enc: 0, isEnc: 0, gesture: 0 }); api.set('AP.handler', {}); api.set('AP.ev', { isNull: () => false });
  api.set('call', (m, o) => { taps.push(Number(WORLD[o.k].enc)); api.set('LASTOK', true); if (opts.onTap) opts.onTap(o.k, WORLD); return null; });
  for (let step = 0; step < 400; step++) {
    NOW += 300;                                   // pump runs appleTick every 300 ms
    if (opts.script) opts.script(step, WORLD);
    Object.keys(WORLD).forEach((k) => api.note(P(k)));
    api.tick(NOW);
  }
  const st = api.get('AP.st');
  console.log(name.padEnd(12), 'taps', JSON.stringify(taps), 'live', st.live, 'expired', st.expired, 'taps#', st.taps);
}
const near = { lat: 40.7001, lng: -74.0 }, far = { lat: 40.71, lng: -74.0 };
const mk = (enc, x) => Object.assign({ enc: String(enc), isEnc: false, type: 'TAPPABLE_TYPE_MAPLE', despawn: 1790716800000 + 600000 }, near, x || {});
run('expired', { script: (s, W) => { if (s === 0) W.p1 = mk(1, { despawn: 1790716800000 - 60000 }); } });
run('live-once', { script: (s, W) => { if (s === 0) W.p1 = mk(2); }, onTap: (k, W) => { delete W[k]; } });
run('live-stays', { script: (s, W) => { if (s === 0) W.p1 = mk(3); } });
run('encounter', { script: (s, W) => { if (s === 0) W.p1 = mk(4, { isEnc: true }); } });
run('far', { script: (s, W) => { if (s === 0) W.p1 = mk(5, far); } });
run('two-apples', { script: (s, W) => { if (s === 0) { W.p1 = mk(6); W.p2 = mk(7); } }, onTap: (k, W) => { delete W[k]; } });
run('pool-reuse', { script: (s, W) => { if (s === 0) W.p1 = mk(8, { despawn: 1790716800000 - 1 }); if (s === 100) W.p1 = mk(9); }, onTap: (k, W) => { delete W[k]; } });
run('other-type', { script: (s, W) => { if (s === 0) W.p1 = mk(10, { type: 'TAPPABLE_TYPE_POKEBALL' }); } });
run('not-ready', { script: (s, W) => { if (s === 0) W.p1 = mk(11, { ready: false }); if (s === 50) W.p1 = mk(11); }, onTap: (k, W) => { delete W[k]; } });
