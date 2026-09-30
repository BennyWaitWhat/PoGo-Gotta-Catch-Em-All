// Offline test of apple_collector.py's tick()/note() decisions (node). Usage: python tools/apple_sim.py
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
function run(name, controllers, opts) {
  const P = (k) => ({ k, toString: () => k, isNull: () => false, add: () => ({ readU64: () => ({ toString: () => String((WORLD[k] || {}).enc) }), readU8: () => ((WORLD[k] || {}).isEnc ? 1 : 0), readPointer: () => ({ isNull: () => false }) }) });
  let WORLD = {};
  const api = new Function('ptr', 'Process', 'Memory', 'Interceptor', 'NativeFunction', 'NULL', 'Date',
    src + `;return {get:(k)=>eval(k), set:(k,v)=>eval(k+'=v'), tick:()=>tick(), note:(p)=>note(p)};`)(
    P, { pointerSize: 8, findModuleByName: () => ({ enumerateExports: () => [] }) },
    { alloc: () => { const m = { writePointer: () => m, readPointer: () => ({ isNull: () => true }), add: () => m }; return m; } }, {}, function () {}, null,
    { now: () => NOW });
  let NOW = 1790716800000, taps = [];
  api.set('F', { enc: 0, isEnc: 0 }); api.set('TYPES', ['TAPPABLE_TYPE_MAPLE']); api.set('LIVE', true); api.set('MAXDIST', 60);
  api.set('PLAT', 40.7); api.set('PLNG', -74.0);
  api.set('read', (o) => { const c = WORLD[o.k]; return c ? Object.assign({ ready: true }, c) : null; });
  api.set('IL', { invoke: (m, o) => { taps.push(WORLD[o.k].enc); if (opts.onTap) opts.onTap(o.k, WORLD); } });
  api.set('M_TAPPED', {}); api.set('M_HANDLER', {}); api.set('F', { enc: 0, isEnc: 0, gesture: 0 });
  for (let step = 0; step < 400; step++) {
    NOW += 50;   // 20 frames per tick below = one decision pass per step
    if (opts.script) opts.script(step, WORLD);
    Object.keys(WORLD).forEach((k) => api.note(P(k)));   // the game touches every controller it holds
    for (let f = 0; f < 20; f++) api.tick();
  }
  const st = api.get('STATS');
  console.log(name.padEnd(16), 'taps', JSON.stringify(taps), 'live', st.live, 'dead', st.dead, 'seen', st.seen, 'skipped', JSON.stringify(st.skipped));
  return taps;
}
const near = { lat: 40.7001, lng: -74.0 }, far = { lat: 40.71, lng: -74.0 };
const mk = (enc, extra) => Object.assign({ enc, isEnc: false, type: 'TAPPABLE_TYPE_MAPLE', despawn: 1790716800000 + 600000 }, near, extra || {});
run('expired', {}, { script: (s, W) => { if (s === 0) W['p1'] = mk(1, { despawn: 1790716800000 - 60000 }); } });
run('live-once', {}, { script: (s, W) => { if (s === 0) W['p1'] = mk(2); }, onTap: (k, W) => { delete W[k]; } });
run('live-stays', {}, { script: (s, W) => { if (s === 0) W['p1'] = mk(3); } });   // server slow to remove it: still 1 tap
run('encounter', {}, { script: (s, W) => { if (s === 0) W['p1'] = mk(4, { isEnc: true }); } });
run('far', {}, { script: (s, W) => { if (s === 0) W['p1'] = mk(5, far); } });
run('two-apples', {}, { script: (s, W) => { if (s === 0) { W['p1'] = mk(6); W['p2'] = mk(7); } }, onTap: (k, W) => { delete W[k]; } });
run('pool-reuse', {}, { script: (s, W) => { if (s === 0) W['p1'] = mk(8, { despawn: 1790716800000 - 1 }); if (s === 100) W['p1'] = mk(9); }, onTap: (k, W) => { delete W[k]; } });
run('other-type', {}, { script: (s, W) => { if (s === 0) W['p1'] = mk(10, { type: 'TAPPABLE_TYPE_POKEBALL' }); } });
