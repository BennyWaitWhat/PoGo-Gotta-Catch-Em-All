"""REWARD CATCHER (v2): clear stacked Field-Research ('Today') reward encounters one-by-one. Replicates the
exact traced flow on the main-thread pump (CameraFollowingGround.LateUpdate):
  GetDanglingEncounterOfType(type,"") -> OpenQuestEncounter(proto) -> [wait network open] ->
  QuestMapPokemon.TryCapture(Excellent curveball Poke) -> settle -> next, until no type returns a dangling.

v2 changes (2026-06-08):
  * FAST blocked-throw recovery: STUCK 480->150 frames (~8s -> ~2.5s) + a single NUDGE re-open mid-wait,
    so a throw that doesn't register retries in ~1-2s instead of stalling ~8-11s (user complaint).
  * AUTO-RECONNECT: outer loop re-attaches after a PoGo restart / lossy-Tailscale drop (frida 'script
    destroyed'); catches bank server-side so it continues from the remaining danglings.
  * ROUND LOGGING for self-reflection: per-catch latency + stalls to reward_catch.log, and one structured
    JSON line per session (plus an operation summary) to reward_rounds.jsonl. Dust before/after is read
    in-session (IapService.get_Stardusts, max instance) to confirm stardust + any Star Piece bonus.

Usage:
  python reward_catcher.py [MAX] [--dry]
    MAX    number of catches; 0 = until dry (default 0).
    --dry  readiness check ONLY: attach, install hooks, pick singletons, read dust/box baseline, probe for
           a dangling, then detach WITHOUT catching anything. Use to confirm 'go go go' readiness.
Box count (PokemonOnlyCount) verifies catches (auto-transfer spares reward Pokemon)."""
import sys, os, time, json, shutil, subprocess
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

LOG = os.path.join(ROOT, "system", "analysis", "pokemod", "reward_catch.log")
ROUNDS = os.path.join(ROOT, "system", "analysis", "pokemod", "reward_rounds.jsonl")
_args = [a for a in sys.argv[1:]]
DRY = "--dry" in _args
_pos = [a for a in _args if not a.startswith("--")]
MAX = int(_pos[0]) if _pos else 0      # 0 = until dry
TYPES = [4, 5, 6, 10, 13, 23]          # EncounterType values the Today view itself queries for dangling rewards
BALL = 1                               # Poke (rewards are guaranteed/no-flee; cheapest is fine)
RECONNECT_BUDGET = 8                   # how many re-attaches before giving up (drops bank progress, so generous)
SESSION_TIMEOUT = 1500                 # s, per-session safety cap

PAUSE_FILE = "/data/local/tmp/pogo_pause"   # handshake with the on-phone auto-catcher (see catch_loop_fast.py)


def _adb_su(cmd):
    """Desktop runs only. On the phone (reward_phone.py) there is no adb, and catcher_ctl.sh stops the catcher itself."""
    ser = pg._resolve_device() if shutil.which("adb") else None
    if not ser:
        return None
    try:
        return subprocess.run(["adb", "-s", ser, "shell", f"su -c '{cmd}'"], capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception:
        return None


def catcher_pause(seconds):
    """Ask the auto-catcher to let go of the single gadget, and wait until it has (about 1 s)."""
    if _adb_su(f"echo $(( $(date +%s) + {seconds} )) > {PAUSE_FILE}") is None:
        return
    for _ in range(20):
        if _adb_su("ss -tn | grep -c :27047") == "0":
            return
        time.sleep(0.5)


def catcher_resume():
    _adb_su(f"echo 0 > {PAUSE_FILE}")


JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a,{exceptions:'propagate'}):null;}   /* never steal ART's own faults */
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),oN:b("il2cpp_object_new","pointer",["pointer"]),isVT:b("il2cpp_class_is_valuetype","int",["pointer"]),sN:b("il2cpp_string_new","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj,params){var h=H_();if(!m)return null;var n=params?params.length:0;var args=ptr(0);if(n){args=Memory.alloc(Process.pointerSize*n);for(var i=0;i<n;i++)args.add(i*Process.pointerSize).writePointer(params[i]);}var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,args,exc);if(!exc.readPointer().isNull())return null;return r;}

var QS=ptr(0), QSM=ptr(0), QMP=ptr(0), ACTIVE_QMP=ptr(0), PBT=null, PBT_VT=false, EMPTY=ptr(0);
var BALL=1, TYPES=[], FRAME=0, RUN=false, MAX=0, CAUGHT=0;
var ST=0, stFrame=0, curProto=ptr(0), lastId="0", curId="0";
var SAMESTALL=0, SKIPTYPE={}, TYPEIDX=0, STUCKOUT=0;   // loop-breaker state (see STUCK escalation below)
var OPEN_LAG=52, SETTLE=18, STUCK=150, NUDGE=42;   // frames @ ~60fps  (STUCK 480->150: blocked-throw recovery ~2.5s not ~8s)
var STALLS=0, REOPENED=false, LOST=0, throwFrame=-100000, LOSTWAIT=150;   /* LOSTWAIT ~2.5 s: a registered catch clears its reward well inside that */
var BAG=ptr(0), boxAtThrow=-1, SLOWCONF=0, slowNoted=false;              /* box (PokemonOnlyCount) = proof a throw registered */
var THROWS={}, MAXTHROWS=6, STUCKIDS={};                                   /* per-reward throw cap (a break-out needs a few, never infinite) */
rpc.exports.setBag=function(p){BAG=ptr(p);};
function readBox(){ try{ if(BAG.isNull())return -1; if(!M.box)M.box=mOf(H_().OGC(BAG),"get_PokemonOnlyCount",0); if(!M.box)return -1;
  var r=inv(M.box,BAG,[]); return r?r.add(0x10).readS32():-1; }catch(e){return -1;} }
var ERRS=[];
var M={};  // cached methods

rpc.exports.setQs=function(p){QS=ptr(p);};
rpc.exports.setQsm=function(p){QSM=ptr(p);};
rpc.exports.setQmp=function(p){QMP=ptr(p);};
rpc.exports.setBall=function(b){BALL=b;};
rpc.exports.setTypes=function(arr){TYPES=arr;};
rpc.exports.setMax=function(m){MAX=m;};
rpc.exports.run=function(on){RUN=!!on; if(on){ST=0;CAUGHT=0;STALLS=0;}};
rpc.exports.stats=function(){return {caught:CAUGHT,state:ST,frame:FRAME,curId:curId,lastId:lastId,stalls:STALLS,lost:LOST,slowconf:SLOWCONF,samestall:SAMESTALL,stuckout:STUCKOUT,stuckIds:Object.keys(STUCKIDS),skipped:Object.keys(SKIPTYPE),errs:ERRS.slice(-6)};};
rpc.exports.qmpClass=function(){try{return H_().CGN(H_().OGC(QMP)).readCString();}catch(e){return null;}};
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.call0i=function(inst,name){var m=mOf(H_().OGC(ptr(inst)),name,0);if(!m)return -999;var r=inv(m,ptr(inst),[]);try{return r?r.add(0x10).readS32():-998;}catch(e){return -997;}};
rpc.exports.probe=function(){for(var i=0;i<TYPES.length;i++){var p=getDangling(TYPES[i]);if(p&&!p.isNull())return TYPES[i];}return -1;};

rpc.exports.install=function(){
 var h=H_(); var st={};
 PBT=findClass("holo-game.dll","PokeballThrow"); if(PBT)PBT_VT=!!h.isVT(PBT); st.pbt=!!PBT;
 EMPTY=h.sN(Memory.allocUtf8String(""));
 // cache methods
 M.gde=mOf(h.OGC(QS),"GetDanglingEncounterOfType",2);
 M.open=mOf(h.OGC(QSM),"OpenQuestEncounter",1);
 M.cap=mOf(h.OGC(QMP),"TryCapture",2);
 M.eid=mOf(h.OGC(QMP),"get_EncounterId",0);
 st.gde=!!M.gde; st.open=!!M.open; st.cap=!!M.cap; st.eid=!!M.eid;
 var qmpC=findClass("holo-game.dll","QuestMapPokemon");var mSE=mOf(qmpC,"SendEncounterRequest",0);
 if(mSE){var sad=mSE.readPointer();if(!sad.isNull()){Interceptor.attach(sad,{onEnter:function(a){ACTIVE_QMP=a[0];}});st.hook=true;}}
 var camC=findClass("holo-game.dll","CameraFollowingGround");var mLU=mOf(camC,"LateUpdate",0);
 if(mLU){var ad=mLU.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){tick();}});st.pump=true;}}
 return st;
};

function getDangling(t){ try{ var iv=Memory.alloc(4); iv.writeS32(t); var r=inv(M.gde,QS,[iv,EMPTY]); return (r&&!r.isNull())?r:ptr(0); }catch(e){ERRS.push("gde:"+e);return ptr(0);} }
function openEnc(p){ try{ inv(M.open,QSM,[p]); }catch(e){ERRS.push("open:"+e);} }
function tgt(){ return (ACTIVE_QMP && !ACTIVE_QMP.isNull())?ACTIVE_QMP:QMP; }
function qmpId(){ try{ var r=inv(M.eid,tgt(),[]); return r?r.add(0x10).readU64().toString():"0"; }catch(e){return "0";} }
function fireCatch(){ try{ var obj=H_().oN(PBT); obj.add(0x10).writeS32(BALL); obj.add(0x14).writeFloat(1.0); obj.add(0x18).writeU8(1); obj.add(0x19).writeU8(1); obj.add(0x1a).writeU8(0); var p=PBT_VT?obj.add(0x10):obj; inv(M.cap,tgt(),[p,ptr(0)]); }catch(e){ERRS.push("cap:"+e);} }

function tick(){ if(!RUN)return; FRAME++;
 try{
  if(ST===0){ // IDLE: find next dangling across types
    curProto=ptr(0); REOPENED=false;
    for(var i=0;i<TYPES.length;i++){ if(SKIPTYPE[TYPES[i]])continue; var p=getDangling(TYPES[i]); if(p&&!p.isNull()){ curProto=p; TYPEIDX=i; break; } }
    if(curProto.isNull()){ ST=9; RUN=false; return; }   // dry -> done
    ACTIVE_QMP=ptr(0); openEnc(curProto); stFrame=FRAME; ST=1; return;
  }
  if(ST===1){ // OPENING: wait for SendEncounterRequest hook + network open, then catch. FAST recovery if blocked.
    var waited=FRAME-stFrame;
    if(waited<OPEN_LAG) return;                          // network open must settle (>=OPEN_LAG; racing it crashes PoGo)
    if(ACTIVE_QMP && !ACTIVE_QMP.isNull()){
      curId=qmpId();
      if(curId!=="0"){
        var n=THROWS[curId]||0;
        if(n>=MAXTHROWS){
          /* THROW CAP: this reward refused MAXTHROWS throws. Skip its type for the round and REPORT it (never a silent
             'dry'). Without a per-reward cap both v2 (every 3 stalls: each throw reset SAMESTALL, so the 6/9 escalation
             was unreachable) and a plain lost-throw retry would throw at it forever, burning a ball every few seconds. */
          STUCKIDS[curId]=1; SKIPTYPE[TYPES[TYPEIDX]]=1; STUCKOUT=1; ST=0; return;
        }
        if(curId!==lastId){ THROWS[curId]=n+1; boxAtThrow=readBox(); slowNoted=false; fireCatch(); CAUGHT++; lastId=curId; SAMESTALL=0; throwFrame=FRAME; stFrame=FRAME; ST=2; return; }
        /* The game handed back the SAME reward we threw at. Box rose since that throw -> it WAS caught, the server just
           has not cleared it yet: wait, never throw twice. Box unchanged after LOSTWAIT -> the throw was LOST (or broke
           out): re-throw now. v2 waited out 3 full STUCK cycles here: ~9 s frozen per lost throw, 5 of 100 on 2026-09-26. */
        var bx=readBox();
        if(bx>=0 && boxAtThrow>=0 && bx>boxAtThrow){ if(!slowNoted){ SLOWCONF++; slowNoted=true; } }
        else if(FRAME-throwFrame>=LOSTWAIT){ THROWS[curId]=n+1; boxAtThrow=bx; fireCatch(); LOST++; throwFrame=FRAME; stFrame=FRAME; ST=2; return; }
        if(waited<STUCK) return;   /* the encounter IS open: no nudge re-open here (it would restart the open wait) */
      }
    }
    // not ready (throw blocked / encounter not loaded yet): one mid-wait nudge, then give up FAST and re-probe
    if(!REOPENED && waited>=OPEN_LAG+NUDGE){ openEnc(curProto); REOPENED=true; }
    if(waited>=STUCK){ STALLS++; SAMESTALL++;
      /* LOOP BREAKER: ST0 re-probes and gets the SAME dangling back, so a reward whose throw never
         registers is retried forever ("stuck repeatedly on the same Pokemon"). Escalate instead:
         3 stalls -> clear lastId so a repeat encounterId is allowed to be thrown at again;
         6 stalls -> skip this dangling TYPE for the round; 9 -> end the round and SAY so. */
      if(SAMESTALL===3){ lastId="0"; }
      if(SAMESTALL===6){ SKIPTYPE[TYPES[TYPEIDX]]=1; }
      if(SAMESTALL>=9){ STUCKOUT=1; ST=9; RUN=false; return; }
      ST=0; return; }
    return;
  }
  if(ST===2){ // SETTLE
    if(FRAME-stFrame>=SETTLE){ ST=(MAX>0&&CAUGHT>=MAX)?9:0; if(ST===9)RUN=false; }
    return;
  }
 }catch(err){ERRS.push("tick:"+err);}
}
"""


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    f = open(LOG, "a", encoding="utf-8")

    def w(s):
        line = f"{time.strftime('%H:%M:%S')} {s}"
        f.write(line + "\n"); f.flush(); print(line, flush=True)

    def jlog(obj):
        try:
            with open(ROUNDS, "a", encoding="utf-8") as jf:
                jf.write(json.dumps(obj) + "\n")
        except Exception as e:
            w(f"jlog err: {str(e)[:80]}")

    def best_of(e, hits, getter):
        """(handle, value) of the max-value instance among hits found BEFORE install() (the live one), or (None, None)."""
        best = None; bestv = None
        for h in hits:
            v = e.call0i(h, getter)
            if isinstance(v, int) and v >= 0 and (bestv is None or v > bestv):
                best = h; bestv = v
        return (best, bestv)

    def run_session(max_catches, dry):
        """One attach->install->run cycle. Never raises; returns a result dict."""
        res = {"caught": 0, "reason": "?", "errs": [], "stalls": 0, "box0": None, "box1": None,
               "dust0": None, "dust1": None, "latencies": [], "elapsed": 0.0, "pid": None,
               "install": None, "dangling_type": None}
        sess = None
        catcher_pause(SESSION_TIMEOUT + 120)   # re-armed before every attach, including reconnects
        for i in range(6):
            try:
                sess, pid = pg.get_session(); res["pid"] = pid; break
            except Exception as ex:
                if i == 5:
                    res["reason"] = "attach_failed"; res["errs"].append(str(ex)[:120]); return res
                time.sleep(4)
        try:
            finder = pg.get_script_with_helpers(sess)
            sc = pg.get_script_with_helpers(sess, JS)
            e = sc.exports_sync

            def pick(ns, cls):
                r = finder.exports_sync.find_singleton(ns, cls)
                return [h for h in (r.get("hits", []) if isinstance(r, dict) else []) if e.cls_name(h) == cls]

            qs_hits = pick("Niantic.Holoholo.Quests", "QuestService")
            qsm_hits = pick("Niantic.Holoholo.Quests", "QuestStateManager")
            qmp_hits = pick("Niantic.Holoholo.Quests", "QuestMapPokemon")
            # EVERY heap (liveness, stopped-world) lookup happens HERE, before install() hooks LateUpdate: a stopped
            # world that catches UnityMain inside the pump's JS callback deadlocks on the shared JS lock (catcher 7b).
            def pick_any(ns, cls):
                hits = pick(ns, cls)
                if not hits:
                    alt = e.ns_of(cls)   # namespace moved in a game update: one class walk, still before any hook
                    hits = pick(alt, cls) if alt and alt != ns else []
                return hits
            iap_hits = pick_any("Niantic.Holoholo.Storefront", "IapService")
            bag_hits = pick_any("Niantic.Holoholo.Internal", "PokemonBagImpl")
            # LIVE SERVICE GRAPH (H01, Pokemon Inventory session 2026-09-29): the game can rebuild its services in-process;
            # the old copies answer with frozen data, so 'most stardust' / 'biggest bag' / 'first hit' can pick a stale one.
            # The live graph = the newest InventoryCache.latestTimestamp; each service is matched to it by its
            # IPlayerService / IInventoryCache / IPokemonBag reference. Still before install(): no hook exists yet.
            # The phone's own pogo_il2cpp (reward_phone.py) has no live_graph yet: keep the old picks there.
            HAS_GRAPH = hasattr(pg, "live_graph") and hasattr(pg, "_graph_of")
            try:
                g = pg.live_graph(sess) if HAS_GRAPH else {}
            except pg.GraphRefusal as ex:
                res["reason"] = "graph_refused"; res["errs"].append(str(ex)[:200]); w(f"GRAPH refused: {str(ex)[:200]}"); return res

            def graph_order(hits, label):
                """hits with the live graph's member first; provably-stale copies dropped; unlinkable classes unchanged."""
                if len(hits) <= 1 or not HAS_GRAPH:
                    return hits
                info = pg._graph_of(sess, hits)
                mine = [h for h in hits if pg._graph_link(info.get(h), g)]
                if mine:
                    stale = [h for h in hits if h not in mine and pg._has_graph_ref(info.get(h))]
                    if stale:
                        w(f"GRAPH {label}: {len(stale)} stale copy(ies) ignored, using the live graph's")
                    return mine + [h for h in hits if h not in mine and h not in stale]
                if any(pg._has_graph_ref(info.get(h)) for h in hits):
                    w(f"GRAPH {label}: {len(hits)} copies, none in the live graph -- refusing the stale ones")
                    return []
                return hits   # no graph reference on this class: the behaviour probe below decides (QuestService)

            qs_hits = graph_order(qs_hits, "QuestService")
            qsm_hits = graph_order(qsm_hits, "QuestStateManager")
            iap_hits = graph_order(iap_hits, "IapService")
            bag_hits = [g["bag"]] if g.get("bag") else graph_order(bag_hits, "PokemonBagImpl")
            w(f"attached pid={res['pid']} | hits QS={len(qs_hits)} QSM={len(qsm_hits)} QMP={len(qmp_hits)} "
              f"IAP={len(iap_hits)} BAG={len(bag_hits)}")
            if not (qsm_hits and qmp_hits):
                res["reason"] = "no_qsm"   # Today/Field-Research panel not open (lazily instantiated)
                return res
            if not qs_hits:
                res["reason"] = "no_qs"; return res
            e.set_qs(qs_hits[0]); e.set_qsm(qsm_hits[0]); e.set_qmp(qmp_hits[0])
            e.set_ball(BALL); e.set_types(TYPES); e.set_max(max_catches)
            st = e.install(); res["install"] = st
            need = ("pump", "pbt", "gde", "open", "cap", "hook")
            if not all(st.get(k) for k in need):
                res["reason"] = "install_failed"; res["errs"].append(str(st)); return res

            # pick the live QuestService (one of two is empty): the one returning a dangling
            chosen = None
            for h in qs_hits:
                e.set_qs(h)
                t = e.probe()
                if isinstance(t, int) and t != -1:
                    chosen = h; res["dangling_type"] = t; break
            if chosen is None:
                res["reason"] = "dry"   # nothing pending of these types
            else:
                e.set_qs(chosen)

            # baseline dust + box (cache the live handles for an exact before/after)
            iap_h, d0 = best_of(e, iap_hits[:1], "get_Stardusts")         # the live graph's copy, not the max value
            pb_h, b0 = best_of(e, bag_hits[:1], "get_PokemonOnlyCount")
            if pb_h:
                e.set_bag(pb_h)   # the pump reads the box to tell a LOST throw from a slow-to-clear catch
            res["dust0"] = d0; res["box0"] = b0
            w(f"baseline: dust={d0} box={b0} dangling_type={res['dangling_type']} install={st}")

            if dry:
                res["reason"] = "dry_check"
                res["dust1"] = d0; res["box1"] = b0
                return res
            if res["reason"] == "dry":
                res["dust1"] = d0; res["box1"] = b0
                return res

            # ---- run ----
            e.run(True)
            t0 = time.time(); last = -1; lastcatch_t = t0
            while True:
                time.sleep(0.6)
                try:
                    stt = e.stats()
                except Exception as ex:
                    res["reason"] = "error"; res["errs"].append("stats:" + str(ex)[:100]); break
                if not isinstance(stt, dict):
                    continue
                c = stt.get("caught", 0); res["caught"] = c; res["stalls"] = stt.get("stalls", 0); res["lost"] = stt.get("lost", 0); res["slowconf"] = stt.get("slowconf", 0)
                if c != last:
                    now = time.time(); lat = now - lastcatch_t; lastcatch_t = now
                    if last >= 0:
                        res["latencies"].append(round(lat, 2))
                    last = c
                    bx = e.call0i(pb_h, "get_PokemonOnlyCount") if pb_h else -1
                    w(f"  catch {c} state={stt.get('state')} +{lat:.1f}s stalls={stt.get('stalls')} lost={stt.get('lost')} slowconf={stt.get('slowconf')} box={bx} curId={stt.get('curId')}")
                if stt.get("state") == 9:
                    if stt.get("stuckout"):
                        # Looped on one un-catchable reward past every escalation — report it, don't
                        # pretend the queue is empty (it isn't; the rest are still waiting).
                        res["reason"] = "stuck"
                        res["errs"].append(f"stuck rewards={stt.get('stuckIds')} curId={stt.get('curId')} skipped_types={stt.get('skipped')}")
                        w(f"  STUCK: reward(s) {stt.get('stuckIds') or [stt.get('curId')]} refused every throw "
                          f"(skipped types={stt.get('skipped')}; the rest of those types wait for the next run) — ending round")
                    else:
                        res["reason"] = "max" if (max_catches > 0 and c >= max_catches) else "dry"
                    break
                if time.time() - t0 > SESSION_TIMEOUT:
                    res["reason"] = "timeout"; e.run(False); break
            res["elapsed"] = round(time.time() - t0, 1)
            res["dust1"] = e.call0i(iap_h, "get_Stardusts") if iap_h else None
            res["box1"] = e.call0i(pb_h, "get_PokemonOnlyCount") if pb_h else None
        except Exception as ex:
            res["reason"] = "error"; res["errs"].append(str(ex)[:150])
        finally:
            try:
                sess.detach()
            except Exception:
                pass
        return res

    # ---------------- orchestration ----------------
    if DRY:
        w(f"===== REWARD CATCHER v2 DRY-RUN (no catches) types={TYPES} =====")
        res = run_session(0, dry=True)
        ok = (res["reason"] == "dry_check")
        w(f"DRY result: reason={res['reason']} install={res['install']} dangling_type={res['dangling_type']} "
          f"dust={res['dust0']} box={res['box0']} errs={res['errs']}")
        jlog({"kind": "dry", "ts": time.strftime('%Y-%m-%d %H:%M:%S'), **{k: res[k] for k in
              ("reason", "install", "dangling_type", "dust0", "box0", "errs", "pid")}})
        if ok and res["dangling_type"] is not None:
            w("READY: hooks green, dangling reward present, dust/box baseline read. GO whenever.")
        elif ok:
            w("READY (hooks green) but NO dangling reward found right now — turn in research / open Today, then GO.")
        elif res["reason"] == "no_qsm":
            w("NOT READY: QuestStateManager absent — open the Today / Field Research panel, then re-check.")
        else:
            w(f"NOT READY: {res['reason']}")
        return

    w(f"===== REWARD CATCHER v2 run MAX={MAX} types={TYPES} =====")
    op = {"kind": "operation", "ts": time.strftime('%Y-%m-%d %H:%M:%S'), "caught_total": 0, "rounds": 0,
          "reconnects": 0, "dust0": None, "dust1": None, "box0": None, "box1": None, "errs": []}
    t_op = time.time(); budget = RECONNECT_BUDGET
    while True:
        res = run_session(MAX, dry=False)
        op["rounds"] += 1
        op["caught_total"] += res["caught"]
        if op["dust0"] is None and res["dust0"] is not None:
            op["dust0"] = res["dust0"]; op["box0"] = res["box0"]
        if res["dust1"] is not None:
            op["dust1"] = res["dust1"]; op["box1"] = res["box1"]
        op["errs"] += res["errs"]
        lats = res["latencies"]
        avg = round(sum(lats) / len(lats), 2) if lats else None
        dust_delta = (res["dust1"] - res["dust0"]) if (res["dust1"] is not None and res["dust0"] is not None) else None
        dpc = round(dust_delta / res["caught"], 1) if (dust_delta is not None and res["caught"]) else None
        jlog({"kind": "session", "ts": time.strftime('%Y-%m-%d %H:%M:%S'), "round": op["rounds"],
              "reason": res["reason"], "caught": res["caught"], "elapsed_s": res["elapsed"], "stalls": res["stalls"], "lost_rethrows": res.get("lost"), "slow_confirms": res.get("slowconf"),
              "avg_s_per_catch": avg, "min_s": (min(lats) if lats else None), "max_s": (max(lats) if lats else None),
              "box0": res["box0"], "box1": res["box1"],
              "dust0": res["dust0"], "dust1": res["dust1"], "dust_delta": dust_delta, "dust_per_catch": dpc,
              "latencies": lats, "errs": res["errs"], "pid": res["pid"]})
        w(f"round {op['rounds']} done: reason={res['reason']} caught={res['caught']} elapsed={res['elapsed']}s "
          f"stalls={res['stalls']} lost_rethrows={res.get('lost')} slow_confirms={res.get('slowconf')} "
          f"avg={avg}s/catch dust_delta={dust_delta} (~{dpc}/catch)")
        if res["reason"] in ("dry", "max"):
            break
        if res["reason"] == "graph_refused":
            w("live service graph could not be told apart -- NOT reconnecting (reopen PoGo, then retry)"); break
        if res["reason"] == "stuck":
            w("stuck reward — NOT reconnecting (a new session would just throw at it again)"); break
        if res["reason"] == "timeout":
            w("session timeout — stopping"); break
        budget -= 1
        if budget < 0:
            w("reconnect budget exhausted — stopping"); break
        op["reconnects"] += 1
        w(f"reconnecting (reason={res['reason']})... {budget} reconnects left")
        time.sleep(3)

    op["elapsed_s"] = round(time.time() - t_op, 1)
    op["dust_delta"] = (op["dust1"] - op["dust0"]) if (op["dust1"] is not None and op["dust0"] is not None) else None
    op["box_delta"] = (op["box1"] - op["box0"]) if (op["box1"] is not None and op["box0"] is not None) else None
    op["dust_per_catch"] = (round(op["dust_delta"] / op["caught_total"], 1)
                            if (op["dust_delta"] is not None and op["caught_total"]) else None)
    jlog(op)
    w(f"===== OPERATION DONE: caught_total={op['caught_total']} rounds={op['rounds']} reconnects={op['reconnects']} "
      f"box {op['box0']}->{op['box1']} (+{op['box_delta']}) dust {op['dust0']}->{op['dust1']} "
      f"(+{op['dust_delta']}, ~{op['dust_per_catch']}/catch) in {op['elapsed_s']}s =====")


try:
    main()
finally:
    catcher_resume()   # always hand the gadget back
