"""clear_nicknames.py — clear custom Pokemon nicknames in bulk.

Calls Niantic.Holoholo.Internal.PokemonBagImpl.NicknamePokemon(PokemonProto, "")
with an EMPTY string. An empty nickname reverts a Pokemon to its default species
name — the same effect as clearing the name field in-game. Server-authoritative
(real RPC), mirrors the bulk_tag.js il2cpp_runtime_invoke pattern.

Modes:
  scan                  READ-ONLY. Count + sample the mons that have a custom nickname.
  test                  Scan, then clear exactly ONE nickname and verify via a fresh
                        bag re-walk (proves the mechanism, fully reversible).
  clear [--delay S]     Bulk: loop-until-dry. Each pass re-walks the bag, clears every
                        mon that STILL has a custom nickname (throttled by --delay,
                        default 0.15s), until a pass finds none (or --max-pass reached).
                        --limit N caps how many to clear (for a partial run).

Requires PoGo FOREGROUNDED (IL2CPP needs the app un-frozen).
"""
import sys, os, json, time, argparse, sqlite3
sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir))  # system/scripts -> system -> root
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

EXTRA_JS = r"""
var _EXP=null, _SN=null;
function _exp(){ if(_EXP)return _EXP; _EXP={}; Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)_EXP[e.name]=e.address;}); return _EXP; }
function _strnew(s){ if(!_SN){ var e=_exp(); _SN=new NativeFunction(e['il2cpp_string_new'],'pointer',['pointer']); } return _SN(Memory.allocUtf8String(s)); }
function _imgByName(nm){ _ensureInit(); var sp=Memory.alloc(4); var asms=IL2.dGA(IL2.dG(),sp); var na=sp.readS32(); for(var a=0;a<na;a++){ var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer()); if(IL2.iGN(img).readCString()===nm) return img; } return null; }
function _rdStr(p){ try{ if(!p||p.isNull())return ''; var len=p.add(0x10).readS32(); if(len<=0||len>64)return ''; var c=[]; for(var i=0;i<len;i++){ c.push(String.fromCharCode(p.add(0x14+i*2).readU16())); } return c.join(''); }catch(e){ return ''; } }

// Reflect a live PokemonProto to locate nickname_ (NOT originalOwnerNickname_) and PokemonId offsets.
rpc.exports.findOffsets = function(protoStr){
  _ensureInit(); var e=_exp();
  var OGC=new NativeFunction(e['il2cpp_object_get_class'],'pointer',['pointer']);
  var CGN=new NativeFunction(e['il2cpp_class_get_name'],'pointer',['pointer']);
  var CGF=new NativeFunction(e['il2cpp_class_get_fields'],'pointer',['pointer','pointer']);
  var FGN=new NativeFunction(e['il2cpp_field_get_name'],'pointer',['pointer']);
  var FGO=new NativeFunction(e['il2cpp_field_get_offset'],'uint32',['pointer']);
  var p=ptr(protoStr); var cls=OGC(p);
  var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  var nickOff=-1, pidOff=-1, ooNickOff=-1;
  while((f=CGF(cls,it))&&!f.isNull()){ try{ var nm=FGN(f).readCString(); var off=FGO(f); var lo=nm.toLowerCase();
    if(lo==='nickname_'||lo==='nickname') nickOff=off;
    else if(lo==='originalownernickname_'||lo==='originalownernickname') ooNickOff=off;
    if(lo==='pokemonid_'||lo==='pokemonid') pidOff=off;
  }catch(er){} }
  return {cls:CGN(cls).readCString(), nickOff:nickOff, pidOff:pidOff, ooNickOff:ooNickOff};
};

// Read [nickname, pokemonId] for an array of proto pointers.
rpc.exports.readNicks = function(arrJson, nickOff, pidOff){
  var arr=JSON.parse(arrJson); var out=[];
  for(var i=0;i<arr.length;i++){ var p=ptr(arr[i]); var nk=_rdStr(p.add(nickOff).readPointer()); var pid=pidOff>=0?p.add(pidOff).readS32():0; out.push([nk,pid]); }
  return out;
};

rpc.exports.readOne = function(protoStr, nickOff){ return _rdStr(ptr(protoStr).add(nickOff).readPointer()); };

// Force class-init on the classes NicknamePokemon's body touches, so the first
// runtime_invoke doesn't abort (same quirk bulk_tag.js documents).
rpc.exports.prime = function(){
  _ensureInit(); var out=[];
  function pr(img, ns, cls){ try{ if(!img){out.push(ns+'.'+cls+' NOIMG'); return;} var k=IL2.cFN(img, Memory.allocUtf8String(ns), Memory.allocUtf8String(cls)); if(k&&!k.isNull()){ if(IL2.rcInit) IL2.rcInit(k); out.push(ns+'.'+cls+' OK'); } else out.push(ns+'.'+cls+' NOTFOUND'); }catch(er){ out.push(ns+'.'+cls+' threw '+er.message); } }
  var protos=_imgByName('holo-protos.dll');
  pr(GAME_IMAGE,'Niantic.Holoholo.Internal','PokemonBagImpl');
  pr(protos,'Holoholo.Rpc','NicknamePokemonProto');
  pr(protos,'Holoholo.Rpc','NicknamePokemonOutProto');
  return out;
};

// Clear ONE nickname: bag.NicknamePokemon(proto, "")
rpc.exports.clearOne = function(bagStr, protoStr){
  _ensureInit();
  var bagCls=cFN('Niantic.Holoholo.Internal','PokemonBagImpl');
  var m=cMN(bagCls,'NicknamePokemon',2);
  if(!m||m.isNull()) return {ok:false,err:'no NicknamePokemon method'};
  var s=_strnew('');
  var args=Memory.alloc(2*Process.pointerSize);
  args.writePointer(ptr(protoStr));                       // params[0] = PokemonProto* (ref type -> direct)
  args.add(Process.pointerSize).writePointer(s);          // params[1] = System.String* (ref type -> direct)
  var exc=Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
  var ret=rI(m, ptr(bagStr), args, exc);
  var ep=exc.readPointer();
  if(!ep.isNull()){ var e=_exp(); var CGN=new NativeFunction(e['il2cpp_class_get_name'],'pointer',['pointer']); var k=ep.readPointer(); return {ok:false, err:'exc', excClass: CGN(k).readCString()}; }
  return {ok:true, ret: ret.isNull()? '0' : ret.toString()};
};
"""


def display(s):
    try:
        return repr(s)
    except Exception:
        return ascii(s)


def pid_names():
    try:
        c = sqlite3.connect(os.path.join(ROOT, "pokemon.db"))
        return {r[0]: r[1] for r in c.execute(
            "SELECT DISTINCT pokemon_id, species_name FROM pokemon WHERE pokemon_id IS NOT NULL")}
    except Exception:
        return {}


_AUTO_ONLY = False
_NAMES = {}


def _is_auto(nick, pidv):
    """The old rename-based labels: species name truncated, then 'VF<n>' (variant floor ordinal) or '100' (hundo),
    12 characters max. The prefix must be the start of THIS mon's species name, so a user's own name never matches."""
    import re
    m = re.match(r'^(.*?)\s?(VF\d|100)$', nick or '')
    if not m or not m.group(1):
        return False
    norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())
    pre = norm(m.group(1))
    # ANY species name, not only this mon's: an evolved mon keeps its pre-evolution's label ("Meowth VF2" on a
    # Persian, "Abra 100" on a Kadabra) -- 35 of those survived the first clear (2026-09-17)
    return bool(pre) and any(norm(n).startswith(pre) for n in _NAMES.values())


def read_custom(sc, bagmap, nick_off, pid_off):
    """Return list of (uid, proto, nickname, pid) for mons with a non-empty nickname (auto-label names only with
    --auto-only)."""
    uids = list(bagmap.keys())
    protos = [bagmap[u] for u in uids]
    data = sc.exports_sync.read_nicks(json.dumps(protos), nick_off, pid_off)
    return [(uids[i], protos[i], data[i][0], data[i][1]) for i in range(len(uids))
            if data[i][0] and (not _AUTO_ONLY or _is_auto(data[i][0], data[i][1]))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["scan", "test", "clear"])
    ap.add_argument("--delay", type=float, default=0.15, help="seconds between clears (default 0.15)")
    ap.add_argument("--max-pass", type=int, default=4, help="max loop-until-dry passes (default 4)")
    ap.add_argument("--limit", type=int, default=0, help="cap number cleared (0=all)")
    ap.add_argument("--auto-only", action="store_true",
                    help="only the old auto-label names '<species prefix>VF<n>' / '<species prefix>100' (2026-09-17)")
    a = ap.parse_args()

    names = pid_names()
    global _AUTO_ONLY, _NAMES
    _AUTO_ONLY, _NAMES = a.auto_only, names
    sess, pid = pg.get_session()
    print("attached pid", pid)
    try:
        bag = pg.pick_singleton(sess, "Niantic.Holoholo.Internal", "PokemonBagImpl")
        bagmap = pg.walk_bag_protos(sess, bag)
        print("bag mons:", len(bagmap))
        if not bagmap:
            print("FATAL: empty bag (is PoGo foregrounded?)")
            return
        sc = pg.get_script_with_helpers(sess, EXTRA_JS)
        try:
            protos = list(bagmap.values())
            off = sc.exports_sync.find_offsets(protos[0])
            nick_off, pid_off = off["nickOff"], off["pidOff"]
            print(f"PokemonProto={off['cls']}  nickname_@"
                  f"{hex(nick_off) if nick_off >= 0 else '??'}  "
                  f"PokemonId@{hex(pid_off) if pid_off >= 0 else '??'}  "
                  f"(originalOwnerNickname_@{hex(off['ooNickOff']) if off['ooNickOff'] >= 0 else '??'} — NOT touched)")
            if nick_off < 0:
                print("FATAL: nickname_ field not found")
                return

            custom = read_custom(sc, bagmap, nick_off, pid_off)
            print(f"\n{len(custom)} of {len(bagmap)} bag mons have a custom nickname.\n")
            print("sample (first 25):")
            for u, p, nk, pidv in custom[:25]:
                print(f"  {names.get(pidv, '#' + str(pidv)):<16} {display(nk)}")

            if a.mode == "scan":
                return

            print("\npriming classes:", sc.exports_sync.prime())

            if a.mode == "test":
                if not custom:
                    print("no custom nicknames to test on")
                    return
                u, p, nk, pidv = custom[0]
                print(f"\nTEST — clearing ONE: {names.get(pidv, '#' + str(pidv))} {display(nk)} (uid {u})")
                try:
                    r = sc.exports_sync.clear_one(bag, p)
                    print("  clear_one ->", r)
                except Exception as e:
                    print("  clear_one THREW:", e)
                    return
                time.sleep(2.5)
                bm2 = pg.walk_bag_protos(sess, bag)  # fresh — handles proto realloc
                np_ = bm2.get(u)
                if not np_:
                    print("  uid not found on re-walk")
                    return
                newnk = sc.exports_sync.read_one(np_, nick_off)
                print(f"  nickname after (fresh re-walk): {display(newnk)}")
                print("  RESULT:", "CLEARED ✓ (reverts to species name)" if not newnk
                      else f"STILL SET: {display(newnk)}")
                return

            if a.mode == "clear":
                total_ok = 0
                for pno in range(a.max_pass):
                    bm = pg.walk_bag_protos(sess, bag)  # fresh protos each pass
                    todo = read_custom(sc, bm, nick_off, pid_off)
                    if a.limit:
                        todo = todo[:a.limit]
                    print(f"\npass {pno + 1}: {len(todo)} custom nicknames to clear")
                    if not todo:
                        print("  none left — done.")
                        break
                    okc = errc = 0
                    for i, (u, p, nk, pidv) in enumerate(todo):
                        try:
                            r = sc.exports_sync.clear_one(bag, p)
                            if r.get("ok"):
                                okc += 1
                            else:
                                errc += 1
                                if errc <= 3:
                                    print("    err:", r)
                        except Exception as e:
                            errc += 1
                            if errc <= 3:
                                print("    threw:", e)
                        time.sleep(a.delay)
                        if (i + 1) % 50 == 0:
                            print(f"    {i + 1}/{len(todo)}  (ok={okc} err={errc})")
                    total_ok += okc
                    print(f"  pass {pno + 1} done: ok={okc} err={errc}")
                    if a.limit:
                        break
                    time.sleep(1.0)

                bm = pg.walk_bag_protos(sess, bag)
                remaining = len(read_custom(sc, bm, nick_off, pid_off))
                print(f"\nTOTAL cleared this run: {total_ok}   remaining custom nicknames: {remaining}")
        finally:
            sc.unload()
    finally:
        sess.detach()


if __name__ == "__main__":
    main()
