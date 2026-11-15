// Offline test of catch_loop_fast.py's yield ledger + despawn-first queue (node). Usage: python tools/catcher_yield_sim.py
// Each check states what it expects; any mismatch prints FAIL and the exit code is 1.
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
let failed = 0;
const NOW = 1790716800000;
const NUL = { isNull: () => true, toString: () => '0x0' };
function load() {
  return new Function('ptr', 'Process', 'Memory', 'Interceptor', 'NativeFunction', 'NativeCallback', 'CModule', 'NULL', 'rpc', 'Date',
    src + `;return {get:(k)=>eval(k), set:(k,v)=>eval(k+'=v'), call:(f,...a)=>eval(f)(...a)};`)(
    () => NUL, { pointerSize: 8 }, { alloc: () => ({ writePointer: () => {}, readPointer: () => NUL }) }, {}, function () {}, function () {}, function () {},
    NUL, {}, { now: () => NOW });
}
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log((ok ? 'ok   ' : 'FAIL ') + name.padEnd(22), JSON.stringify(got), ok ? '' : '  want ' + JSON.stringify(want));
}
// fake memory: a map Pokemon object at 'o' whose <DespawnTime> sits at 536 and WildPokemonProto pointer at 624
function mapMon(mem, proto) {
  const word = (n) => ({ readS64: () => ({ toNumber: () => mem[n] || 0 }), readS32: () => mem[n] || 0, readDouble: () => mem[n] || 0,
                          readPointer: () => (n === 624 && proto ? proto : NUL), readUtf16String: () => mem.str });
  return { add: word, isNull: () => false };
}
function protoObj(mem) {
  return { isNull: () => false, add: (n) => ({ readS64: () => ({ toNumber: () => mem[n] || 0 }), readS32: () => mem[n] || 0,
    readDouble: () => mem[n] || 0, readPointer: () => (n === 48 ? { isNull: () => false, add: (m) => ({ readS32: () => 7, readUtf16String: () => '3da7c1f' }) } : NUL) }) };
}
function withFields(api) {
  api.set('il', () => ({ objClass: (o) => (o.proto ? 'P' : 'M') }));
  api.set('fieldOffWhere', (k, key) => ({ despawn: k === 'M' ? 536 : -1, wpp: k === 'M' ? 624 : -1, Latitude: 32, Longitude: 40,
    LastModifiedMs: 24, TimeTillHiddenMs: 64, SpawnPointId: 48 })[key]);
}

// 1. despawn time: Nullable<Int64> = hasValue word then value word -> the epoch-ms word wins, whichever it is
{
  const api = load(); withFields(api);
  const p = protoObj({ 32: 1.3149, 40: 103.8161, 24: NOW - 1000, 64: 300000 }); p.proto = true;
  check('despawn hasValue,value', api.call('spawnInfo', mapMon({ 536: 1, 544: NOW + 120000 }, p)).exp, NOW + 120000);
  check('despawn value,hasValue', api.call('spawnInfo', mapMon({ 536: NOW + 90000, 544: 1 }, p)).exp, NOW + 90000);
  check('despawn unset -> proto', api.call('spawnInfo', mapMon({ 536: 0, 544: 0 }, p)).exp, NOW - 1000 + 300000);
  const si = api.call('spawnInfo', mapMon({ 536: 1, 544: NOW + 120000 }, p));
  check('position + spawn point', [si.lat, si.lng, si.sp, si.tth], [1.3149, 103.8161, '3da7c1f', 300000]);
  // live 02:50: every wild spawn said TimeTillHiddenMs 1,258,532,978 (14.6 days) = "not telling" -> unknown, not 2 weeks away
  const ps = protoObj({ 32: 1.3149, 40: 103.8161, 24: NOW - 200, 64: 1258532978 }); ps.proto = true;
  check('14-day tth -> unknown', api.call('spawnInfo', mapMon({ 536: 1, 544: 0 }, ps)).exp, 0);
  check('14-day despawn -> proto', api.call('spawnInfo', mapMon({ 536: 1, 544: NOW + 1258532978 }, p)).exp, NOW - 1000 + 300000);
  const p60 = protoObj({ 24: NOW - 500, 64: 60000 }); p60.proto = true;
  check('real 60 s tth kept', api.call('spawnInfo', mapMon({}, p60)).exp, NOW - 500 + 60000);
  const p2 = protoObj({ 24: NOW, 64: -1 }); p2.proto = true;
  check('unknown time stays 0', api.call('spawnInfo', mapMon({}, p2)).exp, 0);
  check('broken object -> defaults', api.call('spawnInfo', { add: () => { throw new Error('bad'); }, isNull: () => false }).exp, 0);
}
// 2. despawn-first: soonest first, under 1.5 s left / unknown at the back in arrival order, priority in front
{
  const api = load();
  api.set('E', { a: { exp: NOW + 60000, t0: 1 }, b: { exp: NOW + 10000, t0: 2 }, c: { exp: 0, t0: 3 }, d: { exp: NOW + 900, t0: 4 },
                 p: { prio: true, exp: NOW + 99000, t0: 5 }, f: { exp: NOW + 30000, t0: 6 } });
  api.set('PEND', ['a', 'b', 'c', 'd', 'p', 'f', 'gone']);
  api.call('despawnFirst', NOW);
  check('despawn-first order', api.get('PEND'), ['p', 'b', 'f', 'a', 'c', 'd', 'gone']);
}
// 3. the spawn record: every field the funnel needs, the order in force, the outcome
{
  const api = load();
  api.set('POS', { lat: 1.3149, lng: 103.8161 + 100 / 111195 });   // ~100 m east of the spawn
  api.set('CFG.order', 'despawn');
  const e = { pid: 143, cls: 'WildMapPokemon', sp: '3da7c1f', t0: NOW - 9000, seen: NOW - 500, exp: NOW + 600000, tth: 600000,
              lat: 1.3149, lng: 103.8161, d0: 61, tO: NOW - 8000, tR: NOW - 7400, rs: 1, tT: NOW - 7200, tC: NOW - 6100, att: 1, opens: 1,
              ball: 1, probs: { 1: 0.0612, 2: 0.09, 3: 0.12 } };
  api.call('ledgerEnd', e, '123', 'fled', NOW);
  const r = api.get('OUT.led')[0];
  check('record outcome', [r.e, r.id, r.c, r.r, r.ord, r.b, r.pr, r.n], ['123', 143, 'Wild', 'fled', 'despawn', 1, 0.061, 1]);
  check('record times', [r.t0, r.tO, r.tR, r.tT, r.tC, r.t1, r.ls], [NOW - 9000, NOW - 8000, NOW - 7400, NOW - 7200, NOW - 6100, NOW, NOW - 500]);
  check('record distance ~100 m', r.d1 >= 98 && r.d1 <= 102, true);
  check('record position, no throw distance', [r.lat, r.lng, r.dT], [1.3149, 103.8161, null]);
  api.call('ledgerEnd', { cls: 'IncenseMapPokemon', pid: 1, att: 0, opens: 0, lat: null }, '9', 'gone', NOW);
  const r2 = api.get('OUT.led')[1];
  check('incense record (no position)', [r2.c, r2.d1, r2.exp, r2.r, r2.lat], ['Incense', null, null, 'gone', null]);
}
// 4. near-wait: hold the first throw only while > nearM m away AND closing in, for at most nearWait ms after the reply
{
  const api = load();
  api.set('CFG.nearWait', 3000); api.set('CFG.nearM', 55);
  const east = (m) => ({ lat: 1.3149, lng: 103.8161 + m / 111195, t: NOW });   // the avatar m metres east of the spawn
  const spawn = (extra) => Object.assign({ lat: 1.3149, lng: 103.8161, tR: NOW - 500 }, extra);
  api.set('POS', east(70));
  const a = spawn({ d0: 75 });
  check('far + closing in -> wait', [api.call('closingIn', a, NOW), a.nwait], [true, 1]);
  check('far + moving away -> throw', api.call('closingIn', spawn({ d0: 65 }), NOW), false);
  check('time cap -> throw', api.call('closingIn', spawn({ d0: 75, tR: NOW - 3500 }), NOW), false);
  check('no position -> throw', api.call('closingIn', spawn({ d0: 75, lat: null }), NOW), false);
  api.set('POS', east(50));
  check('within nearM -> throw', api.call('closingIn', spawn({ d0: 60 }), NOW), false);
  api.set('POS', Object.assign(east(70), { t: NOW - 5000 }));
  check('stale avatar fix -> throw', api.call('closingIn', spawn({ d0: 75 }), NOW), false);
}
// 5. spins: a refused stop (OutOfRange) is retried 3 s later; BLOCKED only after 6 refusals in a row; a success clears it
{
  const api = load();
  let k = 0;
  const reply = (res) => { const tag = { isNull: () => true, toString: () => 'r' + (k++) };   // each reply its own object
    return { add: (n) => ({ readS32: () => (n === 0x10 ? res : 0), readPointer: () => (n === 0x70 ? tag : NUL) }) }; };
  api.set('SPUN', { f1: NOW - 1000 }); api.set('SPIN.lastFid', 'f1');
  api.call('onSpinOut', reply(2));
  check('refused stop: retry in 3 s', NOW - api.get('SPUN').f1, 327000);
  for (let i = 0; i < 4; i++) api.call('onSpinOut', reply(2));
  check('5 refusals: not blocked', [api.get('LIM.oorStreak'), api.call('spinBlocked', NOW)], [5, false]);
  api.call('onSpinOut', reply(2));
  check('6 refusals: blocked', [api.get('LIM.oorStreak'), api.call('spinBlocked', NOW)], [6, true]);
  api.set('SPIN.next', 0); api.set('LIM.lastSpin', NOW - 10000);
  api.call('spinTick', NOW);
  check('blocked: next probe 30 s', api.get('SPIN.next'), NOW + 20000);
  const ok = { add: (n) => ({ readS32: () => (n === 0x10 ? 1 : n === 0x30 ? 50 : 0), readPointer: () => NUL }) };
  api.call('onSpinOut', ok);
  check('success clears the block', [api.get('LIM.oorStreak'), api.call('spinBlocked', NOW)], [0, false]);
}
// 6. berries: Razz on a hard throw while above its floor; else a Pinap only while the bag has one (Benny 11-08, floor 0)
{
  const api = load();
  api.set('M.useItem', {}); api.set('call', () => NUL); api.set('i32arg', () => NUL);
  api.set('CFG.pinap', true); api.set('CFG.pinapFloor', 0);
  const easy = { probs: { 1: 0.9, 2: 0.95, 3: 0.99 } }, hard = { probs: { 1: 0.1, 2: 0.2, 3: 0.3 } };
  api.set('ITEMC', { 1: 100, 2: 100, 3: 100, 701: 10, 705: 1 });
  check('easy throw -> Pinap', api.call('berryFor', easy), 705);
  check('hard throw -> Razz', api.call('berryFor', hard), 701);
  api.set('ITEMC[701]', 5);
  check('Razz at floor -> Pinap', api.call('berryFor', hard), 705);
  api.call('feed', {}, NUL, 705);
  check('last Pinap fed -> none', [api.get('ITEMC[705]'), api.call('berryFor', easy)], [0, 0]);
  api.set('ITEMC', { 1: 100, 2: 100, 3: 100 });
  check('count unknown -> none', api.call('berryFor', easy), 0);
}
// 7. reply hooks: every 1-argument method is hooked (the game also parses through an obfuscated one), not just MergeFrom
{
  const api = load();
  const ms = [['MergeFrom', 1], ['MergeFrom', 1], ['WriteTo', 1], ['Equals', 1], ['.ctor', 1], ['CalculateSize', 0], ['set_Status', 1], ['puj', 1], ['Clone', 0]];
  const pos = new WeakMap(), hooks = [];
  api.set('il', () => ({ methods: (k, it) => { const i = pos.get(it) || 0; pos.set(it, i + 1); return i < ms.length ? { i, isNull: () => false, readPointer: () => ({ isNull: () => false }) } : NUL; },
                         paramCount: (m) => ms[m.i][1], methodName: (m) => ms[m.i][0] }));
  api.set('cstr', (x) => x);
  api.set('Interceptor', { attach: (code, cbs) => hooks.push(cbs) });
  const seen = [];
  check('hooks: 2 MergeFrom + the obfuscated one', api.call('hookParse', {}, 'enc', (s) => { seen.push(s.id); return s.id !== 'empty'; }), 3);
  const fire = (k, obj) => { const ctx = {}; hooks[k].onEnter.call(ctx, [obj]); hooks[k].onLeave.call(ctx); };
  fire(2, { id: 'viaPuj', isNull: () => false }); fire(0, { id: 'viaMerge', isNull: () => false }); fire(1, { id: 'empty', isNull: () => false });
  check('a reply through the obfuscated method is heard', [seen, api.get('VIA')], [['viaPuj', 'viaMerge', 'empty'], { 'enc:puj': 1, 'enc:MergeFrom': 1 }]);
  // an encounter reply: used once its status is set, ignored while half-filled (status 0)
  const encReply = (st) => ({ add: (n) => ({ readPointer: () => (n === 0x10 ? { isNull: () => false, add: () => ({ readU64: () => ({ compare: () => 1, toString: () => '777' }) }) } : NUL), readS32: () => (n === 0x1c ? st : 0) }) });
  api.set('readProbs', () => ({ 1: 0.5 })); api.set('uint64', (x) => x);
  check('half-filled reply ignored', [api.call('onEncounterOut', encReply(0)), api.get('RESP')['777']], [undefined, undefined]);
  check('complete reply used', [api.call('onEncounterOut', encReply(1)), api.get('RESP')['777'].st], [true, 1]);
  // a spin success seen by two hooks on the same object counts once
  const spinOk = { add: (n) => ({ readS32: () => (n === 0x10 ? 1 : n === 0x30 ? 50 : 0), readPointer: () => NUL }), toString: () => 'obj1' };
  api.call('onSpinOut', spinOk); api.call('onSpinOut', spinOk);
  check('one spin reply, two hooks -> 1 spin', api.get('SPIN.ok'), 1);
}
// 8. Mighty Pokemon (Benny 11-15): the best odds the bag holds -- Safari Ball first when the server lists it, then Ultra /
//    Great / Poke with no reserve; nothing else is ever thrown a Safari Ball; a refused Safari Ball is not thrown for 5 min
{
  const api = load();
  api.set('M.useItem', {}); api.set('call', () => NUL); api.set('i32arg', () => NUL);
  const mOdds = { 1: 0.005, 2: 0.008, 3: 0.011, 7: 0.15 }, mNoSafari = { 1: 0.005, 2: 0.008, 3: 0.011 };
  check('mighty: the game flag', api.call('mightyOf', { strong: 1, p: { 1: 0.5 } }, 598), 1);
  check('mighty: Poke odds under 2%', api.call('mightyOf', { strong: 0, p: mNoSafari }, 598), 1);
  check('ordinary spawn is not mighty', api.call('mightyOf', { strong: 0, p: { 1: 0.02, 2: 0.03, 3: 0.04 } }, 143), 0);
  check('reply of another species: not mighty', api.call('mightyOf', { strong: 1, p: mNoSafari, sp: 598 }, 821), 0);
  api.set('ITEMC', { 1: 100, 2: 5, 3: 5, 7: 3, 701: 2, 705: 0 });
  check('mighty -> Safari Ball', api.call('pickBall', mOdds, false, 1), 7);
  check('mighty, Safari not listed by the server -> Ultra from the reserve', api.call('pickBall', mNoSafari, false, 1), 3);
  api.set('ITEMC[7]', 0);
  check('mighty, no Safari left -> Ultra from the reserve', api.call('pickBall', mOdds, false, 1), 3);
  api.set('ITEMC', { 1: 100, 2: 0, 3: 0, 7: 0 });
  check('mighty, only Poke Balls -> Poke', api.call('pickBall', mOdds, false, 1), 1);
  api.set('ITEMC', { 1: 100, 2: 5, 3: 5, 7: 50, 701: 2, 705: 0 });
  check('ordinary hard catch: never a Safari Ball, reserve kept', api.call('pickBall', { 1: 0.1, 2: 0.15, 3: 0.2, 7: 0.9 }, false, 0), 1);
  api.set('ITEMC', { 1: 100, 2: 100, 3: 100, 7: 50 });
  check('ordinary catches: never a Safari Ball', [api.call('pickBall', { 1: 0.5, 2: 0.6, 3: 0.7, 7: 0.99 }, false, 0),
    api.call('pickBall', { 1: 0.1, 2: 0.15, 3: 0.2, 7: 0.9 }, false, 0), api.call('pickBall', { 1: 0.1, 2: 0.15, 3: 0.2, 7: 0.9 }, true, 0)], [2, 3, 3]);
  api.call('safariRefused', NOW, 'test');
  check('Safari refused -> Ultra for 5 min', api.call('pickBall', mOdds, false, 1), 3);
  api.set('SAFARI_OFF', NOW - 1);
  check('5 min later -> Safari again', api.call('pickBall', mOdds, false, 1), 7);
  api.set('ITEMC', { 1: 100, 2: 5, 3: 5, 7: 0, 701: 2, 705: 0 });
  check('Razz reserve: used on a mighty, kept otherwise', [api.call('berryFor', { probs: mNoSafari, mighty: 1 }), api.call('berryFor', { probs: { 1: 0.1, 2: 0.2, 3: 0.3 } })], [701, 0]);
  // the flag: PokemonProto -> display pointer @OFF.pkDisp -> byte @OFF.dStrong; the wild reply reads it through WildPokemonProto @OFF.wPk
  const disp = (v) => ({ isNull: () => false, add: (m) => ({ readU8: () => (m === 0x64 ? v : 0) }) });
  const pkp = (v) => ({ isNull: () => false, add: (n) => ({ readPointer: () => (n === 0xd8 ? disp(v) : NUL) }) });
  check('flag unreadable (no offsets) -> 0', api.call('strongOf', pkp(1)), 0);
  api.set('OFF.pkDisp', 0xd8); api.set('OFF.dStrong', 0x64); api.set('OFF.wPk', 0x28);
  check('flag read from the display', [api.call('strongOf', pkp(1)), api.call('strongOf', pkp(0)), api.call('strongOf', NUL)], [1, 0, 0]);
  const wild = { isNull: () => false, add: (n) => ({ readU64: () => ({ compare: () => 1, toString: () => '888' }), readPointer: () => (n === 0x28 ? pkp(1) : NUL) }) };
  const reply = { add: (n) => ({ readPointer: () => (n === 0x10 ? wild : NUL), readS32: () => (n === 0x1c ? 1 : 0) }) };
  api.set('readProbs', () => mOdds); api.set('uint64', (x) => x);
  api.call('onEncounterOut', reply);
  check('wild reply carries the flag + odds', [api.get('RESP')['888'].strong, api.get('RESP')['888'].p[7]], [1, 0.15]);
}
// 9. the Mighty reserve: while Mighty Pokemon are around (one in the last 30 min), ordinary spawns leave the last 30
//    Great Balls / Ultra Balls / Razz for them; the Mighty and the priority species are not held back; it ends by itself
{
  const api = load();
  api.set('M.useItem', {}); api.set('call', () => NUL); api.set('i32arg', () => NUL);
  const hard = { 1: 0.1, 2: 0.2, 3: 0.3 }, easy = { 1: 0.5, 2: 0.6, 3: 0.7 }, mOdds = { 1: 0.005, 2: 0.008, 3: 0.011 };
  const three = () => [api.call('pickBall', easy, false, 0), api.call('pickBall', hard, false, 0), api.call('berryFor', { probs: hard })];
  api.set('ITEMC', { 1: 100, 2: 20, 3: 20, 7: 0, 701: 20, 705: 0 });
  check('no Mighty around: the old order', three(), [2, 3, 701]);
  api.set('MLAST', NOW - 60000);
  check('Mighty around: ordinary spawns get Poke Balls, no Razz', three(), [1, 1, 0]);
  check('Mighty around: a Mighty and a priority species still get Ultra', [api.call('pickBall', mOdds, false, 1), api.call('pickBall', hard, true, 0)], [3, 3]);
  api.set('ITEMC', { 1: 100, 2: 31, 3: 31, 7: 0, 701: 31, 705: 0 });
  check('above the reserve: ordinary spawns use them again', three(), [2, 3, 701]);
  api.set('ITEMC', { 1: 100, 2: 20, 3: 20, 7: 0, 701: 20, 705: 0 });
  api.set('MLAST', NOW - 31 * 60000);
  check('no Mighty for 30 min: the old order is back', [api.call('mightyAround'), three()], [false, [2, 3, 701]]);
}
process.exit(failed ? 1 : 0);
