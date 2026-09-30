"""set_nicknames.py — bulk-SET custom nicknames to target values (the keep-codes).

Same PROVEN engine as clear_nicknames.py (class-PRIME + real nickname_ field reflection
+ fresh bag-walk each pass + read-back verify). Reads targets from keepcode_targets.json
([[uid_hex, nickname], ...]; empty nickname = clear to species). Loop-until-dry: each pass
re-walks, sets only mons whose CURRENT real nickname != target, until none mismatch.

Throttle handling: if a pass makes NO progress (sets didn't commit -> Niantic rename
throttle), it stops and tells you to restart PoGo and re-run (re-running auto-resumes,
since it only touches mismatches). Restarting PoGo resets the server throttle.

Usage:
  python set_nicknames.py                 # full run, delay 0.3, loop-until-dry
  python set_nicknames.py --delay 0.4 --max-pass 6
  python set_nicknames.py --limit 300     # cap writes this run
"""
import sys, os, json, time, argparse
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

EXTRA_JS = r"""
var _EXP=null, _SN=null;
function _exp(){ if(_EXP)return _EXP; _EXP={}; Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)_EXP[e.name]=e.address;}); return _EXP; }
function _strnew(s){ var e=_exp(); var f=new NativeFunction(e['il2cpp_string_new'],'pointer',['pointer']); return f(Memory.allocUtf8String(s)); }
function _imgByName(nm){ _ensureInit(); var sp=Memory.alloc(4); var asms=IL2.dGA(IL2.dG(),sp); var na=sp.readS32(); for(var a=0;a<na;a++){ var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer()); if(IL2.iGN(img).readCString()===nm) return img; } return null; }
function _rdStr(p){ try{ if(!p||p.isNull())return ''; var len=p.add(0x10).readS32(); if(len<=0||len>64)return ''; var c=[]; for(var i=0;i<len;i++){ c.push(String.fromCharCode(p.add(0x14+i*2).readU16())); } return c.join(''); }catch(e){ return ''; } }

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

rpc.exports.readNicks = function(arrJson, nickOff){
  var arr=JSON.parse(arrJson); var out=[];
  for(var i=0;i<arr.length;i++){ var p=ptr(arr[i]); out.push(_rdStr(p.add(nickOff).readPointer())); }
  return out;
};
rpc.exports.readOne = function(protoStr, nickOff){ return _rdStr(ptr(protoStr).add(nickOff).readPointer()); };

rpc.exports.prime = function(){
  _ensureInit(); var out=[];
  function pr(img, ns, cls){ try{ if(!img){out.push(ns+'.'+cls+' NOIMG'); return;} var k=IL2.cFN(img, Memory.allocUtf8String(ns), Memory.allocUtf8String(cls)); if(k&&!k.isNull()){ if(IL2.rcInit) IL2.rcInit(k); out.push(ns+'.'+cls+' OK'); } else out.push(ns+'.'+cls+' NOTFOUND'); }catch(er){ out.push(ns+'.'+cls+' threw '+er.message); } }
  var protos=_imgByName('holo-protos.dll');
  pr(GAME_IMAGE,'Niantic.Holoholo.Internal','PokemonBagImpl');
  pr(protos,'Holoholo.Rpc','NicknamePokemonProto');
  pr(protos,'Holoholo.Rpc','NicknamePokemonOutProto');
  return out;
};

// SET ONE nickname: bag.NicknamePokemon(proto, name)
//
// NOTE: NicknamePokemon returns IPromise<NicknamePokemonOutProto> — it is
// ASYNCHRONOUS. runtime_invoke only KICKS OFF the rename; the server round-trip
// and the local nickname_ field update happen LATER, pumped by the game's
// scheduler on the Unity main thread. So {ok:true} here means "dispatched", NOT
// "committed". The Python side MUST pump (sleep) and then re-read nickname_ to
// confirm. `ret` is the promise object pointer (non-null = dispatch succeeded).
rpc.exports.setOne = function(bagStr, protoStr, nameStr){
  _ensureInit();
  var bagCls=cFN('Niantic.Holoholo.Internal','PokemonBagImpl');
  var m=cMN(bagCls,'NicknamePokemon',2);
  if(!m||m.isNull()) return {ok:false,err:'no NicknamePokemon method'};
  var s=_strnew(nameStr);
  var args=Memory.alloc(2*Process.pointerSize);
  args.writePointer(ptr(protoStr));
  args.add(Process.pointerSize).writePointer(s);
  var exc=Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
  var ret=rI(m, ptr(bagStr), args, exc);
  var ep=exc.readPointer();
  if(!ep.isNull()){
    var e=_exp(); var CGN=new NativeFunction(e['il2cpp_class_get_name'],'pointer',['pointer']);
    var k=ep.readPointer(); return {ok:false, err:'exc', excClass: CGN(k).readCString()};
  }
  // ret is the IPromise object; null would mean dispatch never produced a promise.
  return {ok:true, promise: ret.isNull()? null : ret.toString()};
};

// Is the player's nickname privilege blocklisted (shadowban)? If true, the
// server silently rejects every rename — explains "ok:true, never commits".
rpc.exports.isBlocklisted = function(){
  _ensureInit();
  try {
    var psCls = cFN('Niantic.Holoholo','PlayerService');
    if(!psCls || psCls.isNull()) return {ok:false, err:'no PlayerService class'};
    // PlayerService is a singleton; find a live instance via liveness.
    var inst = liveness_find_instances(psCls);
    if(inst.err || !inst.hits || !inst.hits.length) return {ok:false, err:'no PlayerService instance'};
    var m = cMN(psCls,'get_IsNicknameBlocklisted',0);
    if(!m || m.isNull()) return {ok:false, err:'no get_IsNicknameBlocklisted'};
    var ret = rI(m, ptr(inst.hits[0]), ptr(0), null);
    // runtime_invoke boxes the System.Boolean return; the unboxed byte sits at
    // +0x10 of the boxed object (object header is 0x10 on arm64 il2cpp).
    if(ret.isNull()) return {ok:true, blocklisted:false};
    var b = ret.add(0x10).readU8();
    return {ok:true, blocklisted: b !== 0};
  } catch(e){ return {ok:false, err:e.toString()}; }
};
"""


class Engine:
    """A live (session, bag, script, nick_off) bundle. Rebuildable after a
    PoGo restart (PID changes -> everything must be re-resolved)."""
    def __init__(self):
        self.sess = self.pid = self.bag = self.sc = None
        self.nick_off = -1

    def attach_and_prime(self, fresh_session=None, fresh_pid=None):
        """Resolve session, the LIVE bag (re-proven via pick_singleton's >100
        walk), the helper script, the nickname_ offset, and prime the classes."""
        if fresh_session is not None:
            self.sess, self.pid = fresh_session, fresh_pid
        else:
            self.sess, self.pid = pg.get_session()
        print("attached pid", self.pid, flush=True)
        # pick_singleton(PokemonBagImpl) already rejects any candidate whose walk
        # has <100 mons, so this is the live bag, not a stale husk. (Addresses H2.)
        self.bag = pg.pick_singleton(self.sess, "Niantic.Holoholo.Internal", "PokemonBagImpl")
        bm0 = pg.walk_bag_protos(self.sess, self.bag)
        print("bag mons:", len(bm0), flush=True)
        if len(bm0) < 100:
            raise RuntimeError(f"bag walk only {len(bm0)} — not ready / stale")
        self.sc = pg.get_script_with_helpers(self.sess, EXTRA_JS)
        off = self.sc.exports_sync.find_offsets(next(iter(bm0.values())))
        self.nick_off = off["nickOff"]
        if self.nick_off < 0:
            raise RuntimeError("nickname_ field not found")
        print(f"nickname_@{hex(self.nick_off)}  "
              f"(originalOwnerNickname_@{hex(off['ooNickOff'])} untouched)", flush=True)
        print("priming:", self.sc.exports_sync.prime(), flush=True)
        try:
            bl = self.sc.exports_sync.is_blocklisted()
            if bl.get("ok") and bl.get("blocklisted"):
                print("  !! WARNING: IsNicknameBlocklisted = TRUE — server will "
                      "silently reject renames (nickname shadowban).", flush=True)
            else:
                print("  IsNicknameBlocklisted:", bl, flush=True)
        except Exception as e:
            print("  blocklist probe skipped:", e, flush=True)

    def cur_nick(self, uid):
        """Fresh re-walk -> real nickname_ for one uid (or None if uid gone)."""
        bm = pg.walk_bag_protos(self.sess, self.bag)
        p = bm.get(uid)
        return (self.sc.exports_sync.read_one(p, self.nick_off) if p else None), bm

    def set_one_verified(self, uid, name, pump=1.6, polls=4, dispatch_retries=2):
        """Mirror the PROVEN single-mon path: dispatch the rename, PUMP the
        scheduler (NicknamePokemon is async -> returns a promise), then re-walk
        and read the REAL nickname_ field. Only report committed if it equals
        the target. Returns 'ok' | 'noop' | 'fail'.

        Each dispatch is followed by up to `polls` re-reads spaced `pump`s apart,
        so a slow server round-trip still counts as success instead of a false
        throttle. (This is exactly why the single test worked and fire-the-batch
        did not: the batch never pumped/verified per mon.)"""
        # Already correct? (idempotent resume — skip without spending a rename.)
        before, bm = self.cur_nick(uid)
        if before is None:
            return "noop"          # uid not in bag (traded/evolved away)
        if before == name:
            return "noop"
        proto = bm[uid]
        for attempt in range(dispatch_retries + 1):
            try:
                r = self.sc.exports_sync.set_one(self.bag, proto, name)
            except Exception as e:
                r = {"ok": False, "err": f"threw {e}"}
            if not r.get("ok"):
                # Dispatch itself failed (exception/method) — re-walk proto (may
                # have reallocated) and retry.
                bm = pg.walk_bag_protos(self.sess, self.bag)
                proto = bm.get(uid, proto)
                if attempt < dispatch_retries:
                    time.sleep(0.6); continue
                print(f"    dispatch fail uid {uid}: {r}", flush=True)
                return "fail"
            # Dispatched OK — now PUMP + verify the real field.
            for _ in range(polls):
                time.sleep(pump)
                after, bm = self.cur_nick(uid)
                if after == name:
                    return "ok"
                proto = bm.get(uid, proto)   # keep proto fresh for any re-dispatch
            # Not committed after polling this dispatch; re-dispatch (unless out
            # of attempts) — promise may have been dropped under contention.
        return "fail"

    def close(self):
        try:
            if self.sc: self.sc.unload()
        except Exception: pass
        try:
            if self.sess: self.sess.detach()
        except Exception: pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="set", choices=["set", "test"])
    ap.add_argument("--delay", type=float, default=0.4,
                    help="gap between mons AFTER a verified commit (default 0.4)")
    ap.add_argument("--pump", type=float, default=1.6,
                    help="seconds to let the async rename promise resolve before re-reading")
    ap.add_argument("--polls", type=int, default=4, help="re-reads per dispatch")
    ap.add_argument("--pid", type=int, default=0, help="only this pokemon_id (e.g. 1=Bulbasaur)")
    ap.add_argument("--limit", type=int, default=0, help="cap committed writes this run")
    ap.add_argument("--throttle-run", type=int, default=8,
                    help="consecutive verify-fails that mean 'throttled' -> restart PoGo")
    ap.add_argument("--max-restarts", type=int, default=6)
    ap.add_argument("--no-restart", action="store_true",
                    help="on throttle, stop instead of auto-restarting PoGo")
    a = ap.parse_args()

    targets = {str(int(u, 16)): n for u, n in json.load(open(os.path.join(ROOT, "keepcode_targets.json")))}
    print(f"targets: {len(targets)}")

    import sqlite3
    pidmap = {}
    try:
        _c = sqlite3.connect(os.path.join(ROOT, "pokemon.db"))
        pidmap = {str(int(uh, 16)): (pid if pid is not None else 99999)
                  for uh, pid in _c.execute("SELECT uid_hex, pokemon_id FROM pokemon")}
        _c.close()
    except Exception as _e:
        print("pidmap load failed (writes will not be #-ordered):", _e)

    if a.pid:
        targets = {u: n for u, n in targets.items() if pidmap.get(u) == a.pid}
        print(f"FILTERED to pokemon_id {a.pid}: {len(targets)} targets -> {sorted(targets.values())}")

    eng = Engine()
    eng.attach_and_prime()
    try:
        # ---- TEST: prove the per-mon write+verify on ONE mismatched mon ----
        if a.mode == "test":
            bm = pg.walk_bag_protos(eng.sess, eng.bag)
            uids = [u for u in targets if u in bm]
            cur = eng.sc.exports_sync.read_nicks(json.dumps([bm[u] for u in uids]), eng.nick_off)
            pick = next((uids[i] for i in range(len(uids)) if cur[i] != targets[uids[i]]), None)
            if not pick:
                print("no mismatched mon to test on (all already correct)"); return
            print(f"\nTEST — uid {pick}: want {targets[pick]!r}")
            res = eng.set_one_verified(pick, targets[pick], pump=a.pump, polls=a.polls)
            after, _ = eng.cur_nick(pick)
            print(f"  RESULT: {res}  (nickname_ now {after!r}, wanted {targets[pick]!r})")
            return

        # ---- BULK: per-mon write->pump->verify, with throttle-restart-resume ----
        committed = noop = 0
        consec_fail = 0
        restarts = 0
        # Pre-filter: ONE walk to find which targets still mismatch, so a RESUME
        # skips already-correct mons fast (instead of a per-mon walk for each of
        # the ~1550 already done before a crash).
        _bm = pg.walk_bag_protos(eng.sess, eng.bag)
        _uids = [u for u in targets if u in _bm]
        _cur = eng.sc.exports_sync.read_nicks(json.dumps([_bm[u] for u in _uids]), eng.nick_off)
        _todo = {u: targets[u] for i, u in enumerate(_uids) if _cur[i] != targets[u]}
        print(f"pre-filter: {len(_todo)} of {len(_uids)} in-bag targets still need setting", flush=True)
        order = sorted(_todo.items(), key=lambda kv: (pidmap.get(kv[0], 99999), kv[0]))
        idx = 0
        while idx < len(order):
            uid, name = order[idx]
            try:
                res = eng.set_one_verified(uid, name, pump=a.pump, polls=a.polls)
            except Exception as e:
                # Gadget connection dropped (PoGo churn/crash) — reconnect & resume
                # the SAME mon. Light re-attach first; full restart if PoGo is down.
                print(f"\n=== CONNECTION LOST at idx {idx} (committed {committed}): "
                      f"{type(e).__name__}: {e} === reconnecting...", flush=True)
                try: eng.close()
                except Exception: pass
                eng = Engine()
                try:
                    eng.attach_and_prime()
                except Exception as e2:
                    print(f"    re-attach failed ({e2}); full PoGo restart...", flush=True)
                    fs, fp = pg.restart_pogo_and_wait()
                    eng = Engine(); eng.attach_and_prime(fresh_session=fs, fresh_pid=fp)
                consec_fail = 0
                continue
            if res == "ok":
                committed += 1; consec_fail = 0
                if committed <= 20 or committed % 25 == 0:
                    print(f"  [{committed}] uid {uid} -> {name!r} ✓", flush=True)
                time.sleep(a.delay)
            elif res == "noop":
                noop += 1; consec_fail = 0
            else:  # fail
                consec_fail += 1
                print(f"  verify-fail ({consec_fail}/{a.throttle_run}) uid {uid} want {name!r}", flush=True)

            if a.limit and committed >= a.limit:
                print(f"\n--limit {a.limit} reached."); break

            if consec_fail >= a.throttle_run:
                # THROTTLE: per-mon writes stopped committing. The reliable reset
                # is a PoGo restart (documented: ~1065 cleared before throttle, a
                # restart reset it). Restart with a readiness gate, rebuild the
                # engine on the FRESH pid+bag, and RESUME at the same index.
                if a.no_restart:
                    print(f"\nTHROTTLED at idx {idx} (committed {committed}). "
                          f"--no-restart set; re-run to resume."); break
                if restarts >= a.max_restarts:
                    print(f"\nTHROTTLED and hit --max-restarts {a.max_restarts}; "
                          f"committed {committed}. Re-run later to resume."); break
                restarts += 1
                print(f"\n=== THROTTLE detected (committed {committed}). "
                      f"Restarting PoGo [{restarts}/{a.max_restarts}] + waiting for "
                      f"readiness, then resuming at idx {idx} ===", flush=True)
                eng.close()
                fs, fp = pg.restart_pogo_and_wait()   # blocks until libil2cpp+bag ready
                eng = Engine(); eng.attach_and_prime(fresh_session=fs, fresh_pid=fp)
                consec_fail = 0
                continue   # retry SAME mon on the fresh, un-throttled session
            idx += 1

        # ---- FINAL VERIFY (authoritative: fresh walk, real nickname_) ----
        bm = pg.walk_bag_protos(eng.sess, eng.bag)
        uids = [u for u in targets if u in bm]
        cur = eng.sc.exports_sync.read_nicks(json.dumps([bm[u] for u in uids]), eng.nick_off)
        remaining = [(u, targets[u], cur[i]) for i, u in enumerate(uids) if cur[i] != targets[u]]
        print(f"\nTOTAL committed this run: {committed}  (noop/already-correct: {noop})")
        print(f"still mismatched: {len(remaining)}/{len(uids)} in-bag targets", flush=True)
        if a.pid or len(uids) <= 40 or remaining:
            print("\nPER-MON VERIFY (real nickname_ read-back):")
            show = remaining if len(remaining) > 40 else \
                   [(u, targets[u], cur[i]) for i, u in enumerate(uids)]
            for u, want, got in show[:60]:
                ok = "OK ✓" if got == want else "✗ MISMATCH"
                print(f"  want {want!r:<16} got {got!r:<16} {ok}")
            if len(remaining) > 60:
                print(f"  ... and {len(remaining)-60} more mismatched")
    finally:
        eng.close()


if __name__ == "__main__":
    main()
