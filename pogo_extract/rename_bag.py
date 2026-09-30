"""rename_bag.py -- RELIABLE, CHURN-RESILIENT bag-walk nickname set/clear.

Resolves each target's PokemonProto via the PROVEN PokemonBagImpl walk (node+0x30),
then PokemonBagImpl::NicknamePokemon(proto, string).  Empty string = clear.

The ZygiskFrida gadget drops whenever PoGo's PID churns, so a bulk run gets
interrupted ("script is destroyed").  Resilience:
 - small CHUNKS, FRESH session + re-forward each chunk
 - per-mon try/except; early-bail after a few consecutive fails (dead script)
 - do_chunk NEVER raises (returns partial progress)
 - OUTER retry-rounds: keep re-sweeping not-yet-done targets until done or stuck
 - cumulative progress in keepcode_done.json (resume-safe; re-applying a name is idempotent)

Usage:
  python rename_bag.py <uid_hex> [nickname]
  python rename_bag.py targets.json [--chunk 100] [--throttle 0.15] [--rounds 10] [--resume]
"""
import sys, os, json, time, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'system', 'scripts'))
import pogo_il2cpp as pg

NS, CLS = 'Niantic.Holoholo.Internal', 'PokemonBagImpl'
TARGET = getattr(pg, 'ADB_TARGET', '100.98.158.56:5555')
DONE_LOG = os.path.join(HERE, 'keepcode_done.json')
THROTTLE = 0.15

JS = r"""
function _bindStrNew(){var f=null;Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function(e){if(e.name==='il2cpp_string_new')f=e.address;});return new NativeFunction(f,'pointer',['pointer']);}
function setNick(bagAddrStr, protoStr, name){
  _ensureInit();
  var bagCls=cFN('Niantic.Holoholo.Internal','PokemonBagImpl');
  var m=cMN(bagCls,'NicknamePokemon',2);
  if(!m||m.isNull())return {ok:false,err:'no NicknamePokemon method'};
  var strNew=_bindStrNew();
  var s=strNew(Memory.allocUtf8String(name));
  if(s.isNull())return{ok:false,err:'string_new null'};
  var args=Memory.alloc(2*Process.pointerSize);
  args.writePointer(ptr(protoStr));args.add(Process.pointerSize).writePointer(s);
  var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));
  var r=rI(m,ptr(bagAddrStr),args,exc);
  if(!exc.readPointer().isNull())return{ok:false,err:'NicknamePokemon threw'};
  return{ok:true};
}
rpc.exports.setNick=setNick;
"""


def reforward():
    try:
        subprocess.run(['adb', '-s', TARGET, 'forward', 'tcp:27047', 'tcp:27047'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def do_chunk(chunk):
    """chunk = list of (uid_hex, nick). NEVER raises. Returns (ok_uids, fail_uids)."""
    uid_map = {str(int(u, 16)): (u, n) for u, n in chunk}
    all_hex = [u for u, _ in chunk]
    reforward()
    ok, sess = [], None
    try:
        sess, pid = pg.get_session()
        try:
            from ready_gate import ensure_ready_for_writes
            ensure_ready_for_writes(sess, pid)
        except Exception:
            pass
        bag = pg.pick_singleton(sess, NS, CLS)
        protos = pg.find_protos_for_uids(sess, bag, list(uid_map.keys()))
        h = pg.get_script_with_helpers(sess, JS)
        try:
            consec = 0
            for dec, proto in protos.items():
                uhex, nick = uid_map[dec]
                try:
                    r = h.exports_sync.set_nick(bag, proto, nick)
                    if r.get('ok'):
                        ok.append(uhex); consec = 0
                    else:
                        consec += 1
                except Exception:
                    consec += 1
                if consec >= 4:        # script likely dead -> stop, outer round retries the rest
                    break
                time.sleep(THROTTLE)
        finally:
            try: h.unload()
            except Exception: pass
    except Exception:
        pass
    finally:
        try:
            if sess: sess.detach()
        except Exception: pass
    fails = [u for u in all_hex if u not in set(ok)]
    return ok, fails


def main():
    global THROTTLE
    args = sys.argv[1:]
    chunk_sz, rounds = 100, 12
    resume = '--resume' in args
    if resume: args.remove('--resume')
    for flag in ('--throttle', '--chunk', '--rounds'):
        if flag in args:
            i = args.index(flag); val = args[i + 1]; del args[i:i + 2]
            if flag == '--throttle': THROTTLE = float(val)
            elif flag == '--chunk': chunk_sz = int(val)
            elif flag == '--rounds': rounds = int(val)

    if args[0].endswith('.json'):
        targets = [(u, n) for u, n in json.load(open(args[0], encoding='utf-8'))]
    else:
        targets = [(args[0], args[1] if len(args) > 1 else '')]

    done = set()
    if resume and os.path.exists(DONE_LOG):
        done = set(json.load(open(DONE_LOG)))
    targets = [(u, n) for u, n in targets if u not in done]
    print(f"to apply: {len(targets)}  (already done: {len(done)})  chunk={chunk_sz} throttle={THROTTLE}s")

    all_ok = set(done)
    t0 = time.time()
    remaining = targets
    for rnd in range(1, rounds + 1):
        if not remaining:
            break
        before = len(remaining)
        round_ok = []
        for ci in range(0, len(remaining), chunk_sz):
            ok, _ = do_chunk(remaining[ci:ci + chunk_sz])
            round_ok += ok; all_ok |= set(ok)
            json.dump(sorted(all_ok), open(DONE_LOG, 'w'))
            print(f"  r{rnd} chunk {ci//chunk_sz+1}/{(len(remaining)+chunk_sz-1)//chunk_sz}: "
                  f"+{len(ok)} | done {len(all_ok)} | {time.time()-t0:.0f}s", flush=True)
        remaining = [(u, n) for u, n in remaining if u not in all_ok]
        print(f"  -- round {rnd}: applied {len(round_ok)}, remaining {len(remaining)}", flush=True)
        if not round_ok:
            print("  -- no progress this round (foreground? churn?) — stopping"); break
    print(f"\nDONE: applied {len(all_ok)-len(done)} this run, {len(all_ok)} total, "
          f"{len(remaining)} still pending in {time.time()-t0:.0f}s")
    if remaining:
        print("  pending sample:", [u for u, _ in remaining][:10])


if __name__ == '__main__':
    main()
