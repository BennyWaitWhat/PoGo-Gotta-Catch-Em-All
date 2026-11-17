// _excText from bulk_tag.js against a fake process memory: the output shape, and that bad pointers never throw out of it.
const fs = require('fs');
const src = fs.readFileSync(require('path').join(__dirname, 'bulk_tag.js'), 'utf8');
const m = src.match(/function _excText\(exc\) \{[\s\S]*?\n\}\r?\n/);
if (!m) { console.error('no _excText'); process.exit(1); }
const mem = new Map();                       // address (BigInt) -> {kind, value}
class P {
  constructor(a) { this.a = BigInt(a); }
  isNull() { return this.a === 0n; }
  add(n) { return new P(this.a + BigInt(n)); }
  sub(o) { return new P(this.a - (o instanceof P ? o.a : BigInt(o))); }
  compare(o) { return this.a < o.a ? -1 : this.a > o.a ? 1 : 0; }
  toString(r) { return r === 16 ? this.a.toString(16) : '0x' + this.a.toString(16); }
  _get(kind) { const v = mem.get(this.a); if (!v || v.kind !== kind) throw new Error('access violation accessing 0x' + this.a.toString(16)); return v.value; }
  readPointer() { return new P(this._get('ptr')); }
  readU32() { return this._get('u32'); }
  readS32() { return this._get('s32'); }
  readCString() { return this._get('cstr'); }
  readUtf16String() { return this._get('utf16'); }
}
const put = (a, kind, value) => mem.set(BigInt(a), {kind, value});
const Process = {pointerSize: 8, findModuleByName: () => ({base: new P(0x7000000000n), size: 0x10000000})};
const FIELDS = [{name: '_message', off: 0x18}, {name: '_innerException', off: 0x28}, {name: '_stackTrace', off: 0x38}];
const _GH = () => ({oc: (e) => new P(0x1000), cnm: () => ({readCString: () => 'InvalidOperationException'})});
const _ghFields = () => FIELDS;
const _ghStr = (p) => { try { return p.add(0x14).readUtf16String(); } catch (e) { return null; } };
const _excText = eval('(' + m[0].trim() + ')');
// outer exception: no message, 2 frames; inner: a message, no trace
const E = 0x5000n, I = 0x6000n, T = 0x8000n, MI1 = 0x9000n, MI2 = 0x9100n, K1 = 0xA000n;
put(E + 0x18n, 'ptr', 0n); put(E + 0x28n, 'ptr', I); put(E + 0x38n, 'ptr', T);
put(T + 0x18n, 'u32', 2); put(T + 0x20n, 'ptr', MI1); put(T + 0x28n, 'ptr', MI2);
put(MI1, 'ptr', 0x7000123450n); put(MI1 + 0x18n, 'ptr', 0xB000n); put(0xB000n, 'cstr', 'SetPokemonTags'); put(MI1 + 0x20n, 'ptr', K1);
put(K1 + 0x10n, 'ptr', 0xB100n); put(0xB100n, 'cstr', 'TaggingRpcService');
put(MI2, 'ptr', 0x123n);                      // a frame whose name/klass cannot be read, and a pointer outside the module
put(I + 0x18n, 'ptr', 0xC000n); put(0xC000n + 0x14n, 'utf16', 'Collection was modified'); put(I + 0x28n, 'ptr', 0n); put(I + 0x38n, 'ptr', 0n);
const s = _excText(new P(E));
const want = 'no message thrown in TaggingRpcService.SetPokemonTags +0x123450 < ? 0x123 | inner InvalidOperationException: "Collection was modified"';
if (s !== want) { console.error('GOT : ' + s + '\nWANT: ' + want); process.exit(1); }
// garbage: nothing readable at all -> a note, never a throw
const g = _excText(new P(0xDEAD0000n));
if (!/could not be read/.test(g)) { console.error('garbage gave: ' + g); process.exit(1); }
if (_excText(new P(0n)) !== '') { console.error('null gave: ' + _excText(new P(0n))); process.exit(1); }
console.log('_excText OK: ' + s);
