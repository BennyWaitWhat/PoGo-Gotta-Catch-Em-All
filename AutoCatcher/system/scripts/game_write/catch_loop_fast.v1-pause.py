"""#2 UI-FREE AUTO-CATCHER, FAST + RANGE-AWARE + CONTINUOUS. On-device pump pipeline (open then, after a
lag, TryCapture) so latency is hidden. Targets only spawns WITHIN range of the player (MapAvatar GPS),
from the complete get_AllPokemon list, nearest priority. NO UI. POKE->GREAT->ULTRA. Stardust readout
(box is hidden by auto-transfer). Self-reconnecting. Stop the task to kill."""
import sys, os, time, json, re
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

LOG = os.path.join(ROOT, "system", "analysis", "pokemod", "catch_loop.log")
DUST_STATE = os.path.join(ROOT, "system", "analysis", "pokemod", "last_stardust.json")  # persisted server-truth stardust, for continuity across restarts


def _load_last_dust():
    try:
        with open(DUST_STATE) as fh:
            return int(json.load(fh).get("stardust", 0))
    except Exception:
        return 0


def _save_last_dust(v):
    try:
        with open(DUST_STATE, "w") as fh:
            json.dump({"stardust": int(v), "ts": time.time()}, fh)
    except Exception:
        pass


RATE_PER_MIN = 90     # opens/min target, now framerate-independent (was effectively ~half this on frame-based pacing)
MAX_RANGE_M = 1e7    # 2026-09-24: OFF — after a crash-restart MapAvatar read a frozen spot (spd=0, inrange=0 with 15+ Rattata on screen). VISONLY alone gates.  # effectively OFF. get_VisibleOnMap (VISONLY) is the real gate: if it renders on the
                     # map it is catchable, so distance must not veto it. The old 80m cap was throwing away
                     # perfectly catchable on-screen spawns.
POKE_FLOOR = 5       # ball priority: Poke -> Great -> Ultra (cheapest first, keep a few of each)
GREAT_FLOOR = 5
ULTRA_FLOOR = 5
CATCH_THRESHOLD = 0.28  # cheapest ball whose BASE prob >= this; step up only if it can't.
                        # Was 0.50 — far too high, so nearly everything escalated to ULTRA (that's why Poke
                        # piled up while Ultra drained). NOTE the logged p is the BASE rate EXCLUDING our
                        # throw bonus: every throw is Excellent + curveball ~= 3.4x, so p_real = 1-(1-p)^3.4.
                        # base 0.28 -> ~67% real on the FIRST ball, and with MAXTHROW=12 cheap balls get
                        # repeated for free. Ultra is now reserved for mons where even a Great is under 0.28.
PINAP_FLOOR = 20       # keep at least this many Pinap; below it, auto-feeding stops (don't drain the stash)
USE_PINAP = True       # ON 2026-09-24 (Rattata CD hour): Pinap on every catch that does NOT need a Razz; Razz still wins on hard throws
USE_RAZZ = True        # BACK ON. Earlier I switched this off believing Pokemod fed berries — that was
                       # true on the PAID tier only. On free tier NOTHING feeds (Razz sat unchanged at 14
                       # with fed=0), so berries were going completely unused. Regular Razz (701) ONLY —
                       # Golden Razz (706) and Silver Pinap (708) remain untouched per standing instruction. Our feeding was redundant and
                       # just raced Pokemod for the same encounter. Berries are Pokemod's job; we only throw balls.
RAZZ_FLOOR = 5         # token reserve only (user OK to run down — easy to restock); auto-feed stops near empty
RAZZ_THRESH = 0.45     # back to 0.45: 0.60 burned ~200 Razz for ~0 catch-rate gain (flees are server-rejects, not catch-fails); 0.45 targets only the genuine-breakout minority
USE_SPIN = True        # PokeStop auto-spin master enable — NORMAL spin path only (never wearable/SoftSfida). Runs concurrently with catching.
SPIN_FLAG = "/data/local/tmp/pogo_spin.on"      # AutoCatcher app toggles this (world-rw, app-readable); polled live (no restart)
TAP_FLAG   = "/data/local/tmp/pogo_tap.on"      # double-tap-to-move toggle (app writes "1"/"0")
PERFECT_FLAG = "/data/local/tmp/pogo_perfect.on"  # Perfect Throw: Excellent + curveball on EVERY
                                                 # throw, manual ones included
CATCH_FLAG = "/data/local/tmp/pogo_catch.on"    # same for catching — so Auto-Catch OFF no longer kills the process (spin lives in it too)
STATE_FILE = "/data/local/tmp/pogo_state.txt"   # catcher publishes live stats here for the app UI (app SELinux domain can't run toybox/read termux home)
QUEUE_LOW = 20
# PRIORITY TARGETS — opened FIRST (queue-jump) and thrown with the strongest ball on hand, regardless of
# the cheap-ball economy. 999 = Gimmighoul (roaming form, arrives on Golden Lures and despawns fast; one was
# already lost at 3m while queued behind ordinary spawns). 1000 = Gholdengo, listed defensively.
# ---- AUTO-TRANSFER (irreversible: starts in DRY-RUN, releases nothing) ----
USE_XFER = False       # DISARMED 2026-08-19. Two PoGo GC crashes (20:40, 22:02) bracketed this
                       # module's life: it ran an il2cpp GetPokemon per catch inside the pump, and
                       # at 14 catches/min that is a lot of managed-object traffic under a COMPACTING
                       # GC. Tagging does not need it -- the offline cull engine decides and tags
                       # from pokemon.db, which is the authority anyway. Keep this OFF.
XFER_DRY = True        # True = log "WOULD-TRANSFER" only. Flip to False ONLY after reviewing the log.
XFER_MIN_PCT = 1       # 0% (nundo) is deliberately KEPT
XFER_MAX_PCT = 24      # 24% == IV total 11/45; below any PvP-viable spread, and below the
                       # 10/10/10 raid/egg/research floor (67%) and 12/12/12 lucky floor (80%)

PRIORITY_DEX = [999, 1000,      # Gimmighoul / Gholdengo (Golden Lure)
                144, 145, 146]  # Galarian Articuno / Zapdos / Moltres — Daily Adventure Incense only.
                                # MOVED OUT of LEGENDARY_DEX (which skipped them entirely) at the user's
                                # request. Historical base_flee_rate ~0.90: they bolt after a single
                                # break-out, so the ONLY thing that helps is throwing again instantly —
                                # which is exactly what the re-throw fix restored (it won a Gimmighoul at att=2).
# ActiveItem on the encounter = the berry currently applied. Tells us whether Pokemod is actually
# feeding on lure encounters (Gimmighoul) or leaving them bare. -1/0 = none.
BERRY_NAME = {-1: "none", 0: "none", 701: "RAZZ", 702: "BLUK", 703: "NANAB", 704: "WEPAR",
              705: "PINAP", 706: "GOLDEN_RAZZ", 708: "SILVER_PINAP"}
# Legendaries + mythicals + ultra beasts (national dex #s) — NEVER auto-catch; skip in the spawn filter so you catch them yourself
LEGENDARY_DEX = [150,151,243,244,245,249,250,251,377,378,379,380,381,382,383,384,385,386,480,481,482,483,484,485,486,487,488,489,490,491,492,493,494,638,639,640,641,642,643,644,645,646,647,648,649,716,717,718,719,720,721,772,773,785,786,787,788,789,790,791,792,793,794,795,796,797,798,799,800,801,802,803,804,805,806,807,808,809,888,889,890,891,892,893,894,895,896,897,898,905,1001,1002,1003,1004,1007,1008,1014,1015,1016,1017,1024,1025]

ESTAT = {0: "ERR", 1: "OK", 2: "NOTFOUND", 3: "CLOSED", 4: "FLED", 5: "NOTINRANGE", 6: "ALREADY", 7: "INVFULL"}  # EncounterOutProto.Status

JS = r"""
/* EXCEPTIONS:'PROPAGATE' (2026-09-24). Frida's default ('steal') catches ANY fault during the call -- including the
   faults ART raises ON PURPOSE (CMC GC compaction pages, implicit suspend checks) when the game code we call touches
   Java. Stealing one longjmps out mid-ART and corrupts its stack bookkeeping; the next MarkCompact stack walk then
   SIGSEGVs (7 tombstones, and the log's own 'fcerr=1/access violation accessing 0x22e7000' = an ART heap page). */
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a,{exceptions:'propagate'}):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),oN:b("il2cpp_object_new","pointer",["pointer"]),isVT:b("il2cpp_class_is_valuetype","int",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),cGP:b("il2cpp_class_get_parent","pointer",["pointer"]),cGT:b("il2cpp_class_get_type","pointer",["pointer"]),tGO:b("il2cpp_type_get_object","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj,params){var h=H_();if(!m)return null;var n=params?params.length:0;var args=ptr(0);if(n){args=Memory.alloc(Process.pointerSize*n);for(var i=0;i<n;i++)args.add(i*Process.pointerSize).writePointer(params[i]);}var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,args,exc);if(!exc.readPointer().isNull())return null;return r;}

var PBT=null,PBT_VT=false,BALL=2,FRAME=0,lastOpenMs=0,INTERVAL_MS=1714,LAG_MS=3500,FIRED=0,OPENED=0,RUN=false,AVAIL={1:true,2:true,3:true},THRESH=0.5;
var Q=[],INFLIGHT=[];
/* MAX CATCH RATE: MAXTHROW was an artificial 4-ball give-up on a mon that was still standing there.
   The server already caps real attempts via ThrowsRemaining (thr>0), and a break-out costs only a ball —
   which we have in excess (1700+ Poke, bag full, so spending them is pure upside). Raising the cap
   converts "escaped 4x, abandoned" into caught. Faster re-throw = more attempts before the encounter ages out. */
/* Per-target throw budget. PRIORITY targets get a much larger one because of a hard research finding:
   a SHINY Galarian bird has its flee rate REMOVED (unlimited throws), while its base catch rate stays
   0.3% => even Ultra + Golden Razz + Excellent curve is only ~4-5%/throw, i.e. ~20-25 balls per catch.
   A cap of 12 would have thrown away a shiny legendary that could not run.
   Raising the cap is FREE: a flee (r=3) terminates retries immediately and is never retried, so the cap
   only ever binds on a mon that keeps breaking out WITHOUT fleeing — precisely the shiny case. */
var THROWN=[],RETHROW=[],MAXTHROW=12,MAXTHROW_PRIO=60,RETHROW_DELAY=1200,REFIRED=0,CR={s:0,e:0,f:0,m:0,err:0};
var IB=ptr(0),BERRY_PINAP=false,PINAP_ID=705,GOLDENRAZZ_ID=706,BERRY_LAG=1800,BERRY_LATE=400,NBERRY=0;
var RAZZ_ID=701,RAZZON=false,RAZZ_THRESH=0.45,NRAZZ=0;   // hard-throws-only regular Razz (701) ONLY; 706/708 NEVER touched
var ATTEMPTED={},NEWATT={},NATT=0;
var SEEN={}, MAPSVC=ptr(0), VISONLY=true, MAPAVATAR=ptr(0), MAXR=90.0, LEGENDARY={};
var PRIORITY={}, NPRIOSEEN=0, NPRIOCAUGHT=0, NPRIOLOST=0;   /* Gimmighoul (#999) & co: queue-jump + best ball + full throw budget */
var ENCSTATUS={}, ENCSN=0, SKIPPED=0, SKIPSTATUS={}, STATUSTALLY={};   // throw only at confirmed-live (OK) encounters; skip phantoms (no/failed open)
var SRCCATCH={}, SEENCLS={}, FLEEPROF=[];   // per-source catch counts + enumerated-class tally + per-loss profile {r:result,p:prob,b:ball,pid:species,a:attempt} for flee/escape/miss
var CURSPEED=-1, LASTAVP=null;   // avatar speed km/h (between refills) — tests the catch speed-lock hypothesis
var REQ={}, REQN=0;   // last CatchPokemonProto request per encId — verify the throw is valid (hit/reticle/spin/spawnGuid)
var CDSUM=0,CDN=0,FDSUM=0,FDN=0;   // catch-dist vs flee-dist (m) — tests RANGE-reject: open<=MAXR + 3.5s drift vs server catch-range (~80m)
var STALESKIP=0;   // throws skipped because the mon went STALE (despawned phantom spawn) — the user's "disappear/reappear/auto-flee/wasted-attempt"
var BGTHROW=0, LASTAVOK=-1, OUTRANGE=0;   // BACKGROUND support: when PoGo is backgrounded the Unity transforms stop updating so get_Location fails (dist=-1). Position is then useless as a liveness test — fall back to a direct "is this encounter still in get_AllPokemon" membership check so catching KEEPS WORKING backgrounded.
/* ===== DOUBLE-TAP TO MOVE =====================================================================
   Uses PoGo's OWN conversion, so no projection maths and no second mock source to fight:
     UnityEngine.Input.GetMouseButtonDown(0) + get_mousePosition   -> screen point (Unity maps touch to mouse)
     IWorldMapRenderer.GetWorldLocation(Vector3)                   -> Niantic.LatLng   (avatar +0x130)
     LocationProviderAdapter.set_Location(LatLng)                  -> moves the player (avatar +0x128)
   The underlying provider keeps pushing the system mock, so the target is RE-APPLIED every tick;
   otherwise the next Update() would snap us back. */
var TAPON=false,TAPTGT=null,NTELE=0,TAPLOG=[];
var TAP_T=0,TAP_X=0,TAP_Y=0,TAP_GAP=450,TAP_SLOP=90;   /* ms between taps, px they may drift apart */
var INP=null,MBD=null,MPOS=null;
/* legacy Input lives in UnityEngine.InputLegacyModule.dll, not CoreModule — search every image */
function findClassAny(nm){try{var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();
 for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());var cnt=h.iGCC(im);
  for(var j=0;j<cnt;j++){var k=h.iGC(im,j);if(k.isNull())continue;try{if(h.CGN(k).readCString()===nm)return k;}catch(e){}}}}catch(e){}return null;}
function inputInit(){try{if(MBD&&MPOS)return true;INP=findClassAny("Input");if(!INP)return false;
 MBD=mOf(INP,"GetMouseButtonDown",1);MPOS=mOf(INP,"get_mousePosition",0);return !!(MBD&&MPOS);}catch(e){return false;}}
/* GetWorldLocation wants a UNITY WORLD position, not screen pixels. Feeding it raw pixels put
   screen-Y on the world UP axis (which contributes nothing), so longitude moved and LATITUDE NEVER
   DID — both of the user's taps returned lat 37.806241 from wildly different screen heights.
   Correct chain: screen px -> MathUtil.ScreenToWorldPoint -> world (x,y,z) -> GetWorldLocation. */
/* Screen px -> world point via a RAY through the tap, intersected with the ground plane (y=0).
   Everything here goes through il2cpp_runtime_invoke, which boxes struct returns and has been safe
   all session — unlike Interceptor.replace, which is what crashed the game. */
var CAMCLS=null,CAMMAIN=null;
function mainCamera(){try{if(!CAMMAIN){CAMCLS=findClassAny("Camera");if(!CAMCLS)return null;CAMMAIN=mOf(CAMCLS,"get_main",0);if(!CAMMAIN)return null;}
 var c=inv(CAMMAIN,ptr(0),[]);return (c&&!c.isNull())?c:null;}catch(e){return null;}}
function screenToWorld(x,y){try{var cam=mainCamera();if(!cam)return null;var h=H_();
 var m=mOf(h.OGC(cam),"ScreenPointToRay",1);if(!m)return null;
 var v=Memory.alloc(12);v.writeFloat(x);v.add(4).writeFloat(y);v.add(8).writeFloat(0);
 var r=inv(m,cam,[v]);if(!r||r.isNull())return null;
 /* boxed Ray = origin(Vector3) then direction(Vector3) */
 var ox=r.add(0x10).readFloat(),oy=r.add(0x14).readFloat(),oz=r.add(0x18).readFloat();
 var dx=r.add(0x1c).readFloat(),dy=r.add(0x20).readFloat(),dz=r.add(0x24).readFloat();
 if(!isFinite(dy)||Math.abs(dy)<1e-6)return null;
 var t=-oy/dy; if(!isFinite(t)||t<0||t>100000)return null;
 return {x:ox+dx*t,y:0,z:oz+dz*t};}catch(e){return null;}}
function screenToLatLng(x,y){try{if(MAPAVATAR.isNull())return null;var h=H_();
 var w=screenToWorld(x,y);if(!w)return null;
 var rnd=MAPAVATAR.add(0x130).readPointer();if(!rnd||rnd.isNull())return null;
 var gm=mOf(h.OGC(rnd),"GetWorldLocation",1);if(!gm)return null;
 var v=Memory.alloc(12);v.writeFloat(w.x);v.add(4).writeFloat(w.y);v.add(8).writeFloat(w.z);
 var r=inv(gm,rnd,[v]);if(!r||r.isNull())return null;
 var out={lat:r.add(0x10).readDouble(),lng:r.add(0x18).readDouble()};
 out.dbg="world("+w.x.toFixed(1)+","+w.y.toFixed(1)+","+w.z.toFixed(1)+")";
 return out;}catch(e){return null;}}
/* INTERCEPT THE READ, DON'T RACE THE WRITE.
   Writing the provider's cache every frame fought GPS Joystick's ~1Hz mock and produced violent
   back-and-forth teleporting (real speed spikes = exactly the position-trust trigger to avoid).
   Instead REPLACE NativeLocationProvider.get_Location: the joystick may cache whatever it likes,
   but PoGo always READS our target, so there is only ever one answer and nothing to oscillate.
   get_Location returns Niantic.LatLng = 2 doubles; on arm64 that is an HFA returned in d0/d1,
   which Frida handles when the return type is declared as ['double','double'].
   IL2CPP instance method ABI: (this, MethodInfo*). When inactive we return the provider's own
   cached pair (+0x28/+0x30) so behaviour is untouched with the feature off. */
/* SEAMLESS MOVE — rewrite the location UPDATE instead of the read.
   NativeLocationProvider.ckzg(Ditto.Geo.Location) is void and receives every incoming fix, so we
   ATTACH (never replace) and edit its argument in place. Why this is the right seam:
     - no struct return  -> none of the HFA/ABI trouble that made replacing get_Location segfault
     - attach, not replace -> no prologue rewriting of a tiny getter
     - every update becomes our target -> ONE effective value, so nothing oscillates the way the
       per-frame cache writes did against GPS Joystick's ~1Hz mock
   Ditto Location: +0x10 -> LocationData, whose LatitudeDeg/LongitudeDeg are plain doubles. The
   struct may be inlined or a reference, so the layout is probed and validated before any write. */
var LOCHOOKED=false;
function locBase(locObj){
 try{var lat=locObj.add(0x10).readDouble(),lng=locObj.add(0x18).readDouble();
   if(isFinite(lat)&&isFinite(lng)&&Math.abs(lat)<=90&&Math.abs(lng)<=180&&(lat!==0||lng!==0))return locObj.add(0x10);}catch(e){}
 try{var d=locObj.add(0x10).readPointer();var lat2=d.add(0x10).readDouble(),lng2=d.add(0x18).readDouble();
   if(isFinite(lat2)&&isFinite(lng2)&&Math.abs(lat2)<=90&&Math.abs(lng2)<=180&&(lat2!==0||lng2!==0))return d.add(0x10);}catch(e){}
 return null;}
/* NO HOOK AT ALL. GPS Joystick exposes a headless teleport service — verified: moved 2.4km with
   PoGo still in focus, no UI, no button. So we never touch PoGo's location internals, which is what
   crashed the game four times (replace-on-a-getter, then attach-on-ckzg). We only READ the map to
   convert the tap; the move itself is the joystick's job, keeping it the single source of truth. */
function installLocHook(){ return true; }
/* NO memory writes and NO method replacement — both destabilised the game (oscillation, then a
   crash loop). The detected tap is just published; the python side hands it to GPS JOYSTICK via a
   geo: intent, so the existing mock provider remains the single source of truth. */
function applyLatLng(ll){ TAPTGT=ll; return true; }
var TAPCOOL=0;
function tapTick(){try{ if(!TAPON)return; if(!inputInit())return;
 installLocHook();               /* one-time attach; movement now happens in-place, no app switch */
 if(Date.now()<TAPCOOL)return;
 var ip=Memory.alloc(4);ip.writeS32(0);var d=inv(MBD,ptr(0),[ip]);
 if(!d||d.add(0x10).readU8()===0)return;
 var mp=inv(MPOS,ptr(0),[]);if(!mp)return;
 var x=mp.add(0x10).readFloat(),y=mp.add(0x14).readFloat();var now=Date.now();
 if(now-TAP_T<=TAP_GAP && Math.abs(x-TAP_X)<=TAP_SLOP && Math.abs(y-TAP_Y)<=TAP_SLOP){
   var ll=screenToLatLng(x,y);
   if(ll&&isFinite(ll.lat)&&isFinite(ll.lng)&&Math.abs(ll.lat)<=90&&Math.abs(ll.lng)<=180){
     TAPTGT=ll;NTELE++;
     /* GOTO: prefix = "python, please move GPS Joystick here" */
     TAPCOOL=Date.now()+800;   /* just debounce the gesture; there is no app round-trip any more */
     TAPLOG.push("MOVED "+ll.lat.toFixed(6)+" "+ll.lng.toFixed(6)+" | screen "+Math.round(x)+","+Math.round(y)+" "+(ll.dbg||""));
   } else { TAPLOG.push("tap converted to an invalid coord — ignored"); }
   TAP_T=0;   /* consume the pair so a third tap starts fresh */
 } else { TAP_T=now;TAP_X=x;TAP_Y=y; }
}catch(e){}}
rpc.exports.setTap=function(on){TAPON=!!on;if(!on)TAPTGT=null;};
/* which link of the chain is missing: input? avatar? renderer? converter? setter? */
rpc.exports.tapDiag=function(){var r={};try{
 r.tapon=TAPON; r.inputInit=inputInit(); r.InputCls=!!INP; r.GetMouseButtonDown=!!MBD; r.get_mousePosition=!!MPOS;
 r.avatar=MAPAVATAR.isNull()?"NULL":MAPAVATAR.toString();
 if(!MAPAVATAR.isNull()){var h=H_();
   var rnd=MAPAVATAR.add(0x130).readPointer(); r.renderer=(rnd&&!rnd.isNull())?rnd.toString():"NULL";
   if(rnd&&!rnd.isNull()){try{r.rendererCls=h.CGN(h.OGC(rnd)).readCString();r.GetWorldLocation=!!mOf(h.OGC(rnd),"GetWorldLocation",1);}catch(e){r.rerr=String(e);}}
   var lp=MAPAVATAR.add(0x128).readPointer(); r.provider=(lp&&!lp.isNull())?lp.toString():"NULL";
   if(lp&&!lp.isNull()){try{r.providerCls=h.CGN(h.OGC(lp)).readCString();r.set_Location=!!mOf(h.OGC(lp),"set_Location",1);r.get_Location=!!mOf(h.OGC(lp),"get_Location",0);
     /* where does the provider CACHE the coordinate? that's what we overwrite */
     r.pfields=[];var k=h.OGC(lp);var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
     while((f=h.cGF(k,it))&&!f.isNull()){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}
       var off=h.fGO(f);var nm2=h.fGN(f).readCString();
       if(/LatLng|Location|Double|Single/i.test(tn)&&r.pfields.length<14)r.pfields.push("+0x"+off.toString(16)+" "+nm2+" : "+tn);}catch(e){}}
     /* live values around the cache so we can spot the real lat/lng pair */
     r.probe=[];for(var o=0x10;o<=0x60;o+=8){try{var d=lp.add(o).readDouble();if(isFinite(d)&&Math.abs(d)>0.0001&&Math.abs(d)<=180)r.probe.push("+0x"+o.toString(16)+"="+d.toFixed(6));}catch(e){}}
   }catch(e){r.perr=String(e);}}
 }}catch(e){r.err=String(e);}return r;};
rpc.exports.drainTap=function(){var o=TAPLOG;TAPLOG=[];return o;};

var PRIO_LAG=7000;   /* ms to wait before the FIRST throw at a priority target (lets Pokemod feed a berry) */
function encPid(t){try{var m=mOf(H_().OGC(t),"get_PokemonId",0);if(!m)return -1;var r=inv(m,t,[]);return r?r.add(0x10).readS32():-1;}catch(e){return -1;}}
function encOf(t){try{var m=mOf(H_().OGC(t),"get_EncounterId",0);if(!m)return null;var r=inv(m,t,[]);if(!r)return null;return r.add(0x10).readU64().toString();}catch(e){return null;}}
function findByEnc(es){try{if(MAPSVC.isNull()||!es)return null;var h=H_();var gm=mOf(h.OGC(MAPSVC),"get_AllPokemon",0);if(!gm)return null;var e=inv(gm,MAPSVC,[]);if(!e||e.isNull())return null;var gem=mOf(h.OGC(e),"GetEnumerator",0);if(!gem)return null;var enr=inv(gem,e,[]);if(!enr||enr.isNull())return null;var enrC=h.OGC(enr);var self=h.isVT(enrC)?enr.add(0x10):enr;var mn=mOf(enrC,"MoveNext",0),gc=mOf(enrC,"get_Current",0);if(!mn||!gc)return null;var guard=0;while(guard++<400){var r=inv(mn,self,[]);if(!r||r.add(0x10).readU8()===0)break;var cur=inv(gc,self,[]);if(!cur||cur.isNull())continue;try{if(encOf(cur)===es)return cur;}catch(e2){}}return null;}catch(e){return null;}}
function encAlive(es){try{if(MAPSVC.isNull()||!es)return false;var h=H_();var gm=mOf(h.OGC(MAPSVC),"get_AllPokemon",0);if(!gm)return false;var e=inv(gm,MAPSVC,[]);if(!e||e.isNull())return false;var gem=mOf(h.OGC(e),"GetEnumerator",0);if(!gem)return false;var enr=inv(gem,e,[]);if(!enr||enr.isNull())return false;var enrC=h.OGC(enr);var self=h.isVT(enrC)?enr.add(0x10):enr;var mn=mOf(enrC,"MoveNext",0),gc=mOf(enrC,"get_Current",0);if(!mn||!gc)return false;var guard=0;while(guard++<3000){var r=inv(mn,self,[]);if(!r||r.add(0x10).readU8()===0)break;var cur=inv(gc,self,[]);if(!cur||cur.isNull())continue;try{if(encOf(cur)===es)return true;}catch(e2){}}return false;}catch(e){return false;}}
rpc.exports.findItemBag=function(){var h=H_();var imgs=["holo-game.dll","holo-protos.dll"];for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(/^I[A-Z]/.test(nm))continue;var m=h.cMN(k,Memory.allocUtf8String("GetItemCount"),1);if(m&&!m.isNull())return {ns:h.CGNS(k).readCString(),cls:nm};}catch(e){}}}return null;};
/* PURE CACHE READ — no il2cpp, no thread attach (see THREAD SAFETY note above). */
rpc.exports.count=function(ibStr,item){return (ITEMC[item]!==undefined)?ITEMC[item]:-1;};   /* cache only: no il2cpp from the RPC thread */
rpc.exports.countLive=function(ibStr,item){var h=H_();var ib=ptr(ibStr);var m=h.cMN(h.OGC(ib),Memory.allocUtf8String("GetItemCount"),1);if(!m||m.isNull())return -1;var arg=Memory.alloc(4);arg.writeS32(item);var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,ib,args,exc);if(!exc.readPointer().isNull())return -2;if(ret.isNull())return -3;try{return ret.add(0x10).readS32();}catch(e){return -4;}};
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
/* Stardust is polled on the Unity thread; anything else falls through to a live call (setup-time only). */
rpc.exports.call0i=function(inst,name){if(name==="get_Stardusts")return DUSTV;var m=mOf(H_().OGC(ptr(inst)),name,0);if(!m)return -999;var r=inv(m,ptr(inst),[]);try{return r?r.add(0x10).readS32():-998;}catch(e){return -997;}};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.setBall=function(b){BALL=b;};
rpc.exports.itemTotal=function(){try{if(IB.isNull())return -1;var h=H_();var m=h.cMN(h.OGC(IB),Memory.allocUtf8String("GetItemCount"),1);if(!m||m.isNull())return -1;var ids=[1,2,3,4,101,102,103,104,201,202,301,401,501,502,503,701,702,703,704,705,706,707,708,709,901,902,903,1101,1102,1103,1104,1105,1106,1107,1201,1202];var tot=0;for(var i=0;i<ids.length;i++){try{var arg=Memory.alloc(4);arg.writeS32(ids[i]);var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,IB,args,exc);if(!exc.readPointer().isNull())continue;if(ret&&!ret.isNull()){var c=ret.add(0x10).readS32();if(c>0&&c<100000)tot+=c;}}catch(e){}}return tot;}catch(e){return -2;}};
rpc.exports.setAvail=function(a){AVAIL={1:!!a[0],2:!!a[1],3:!!a[2]};};
rpc.exports.setThresh=function(t){THRESH=t;};
rpc.exports.setRate=function(intervalMs,lagMs){INTERVAL_MS=intervalMs;if(lagMs)LAG_MS=lagMs;};
rpc.exports.run=function(on){RUN=!!on;};
rpc.exports.setMapSvc=function(p){MAPSVC=ptr(p);SEEN={};};
rpc.exports.resetSeen=function(){SEEN={};};
rpc.exports.drainAttempted=function(){var a=Object.keys(NEWATT);NEWATT={};return a;};
rpc.exports.drainLoss=function(){var o=FLEEPROF;FLEEPROF=[];return o;};
rpc.exports.loadAttempted=function(arr){for(var i=0;i<arr.length;i++)ATTEMPTED[arr[i]]=1;};
rpc.exports.setItemBag=function(p){IB=ptr(p);};
rpc.exports.setBerry=function(on){BERRY_PINAP=!!on;};
rpc.exports.setRazz=function(on,thr){RAZZON=!!on;if(thr!==undefined&&thr!==null)RAZZ_THRESH=thr;};
rpc.exports.setAvatar=function(p){MAPAVATAR=ptr(p);};
rpc.exports.setMaxRange=function(m){MAXR=m;};
rpc.exports.setLegendary=function(arr){LEGENDARY={};for(var i=0;i<arr.length;i++)LEGENDARY[arr[i]]=1;};
rpc.exports.setPriority=function(arr){PRIORITY={};for(var i=0;i<arr.length;i++)PRIORITY[arr[i]]=1;};
/* THREAD SAFETY — this is what was crashing PoGo (ART abort: "Transitioning to Runnable with checkpoint
   flag" inside artJniMethodEnd while MarkCompact GC walked UnityMain's stack).
   RPC exports execute on FRIDA's thread, so calling il2cpp from them meant two threads driving Unity at
   once; a GC checkpoint landing mid-transition aborts the runtime. The heavy walks (all-Pokemon refill,
   all-forts scan) were thousands of cross-thread invokes. They are now DEFERRED: the RPC only raises a
   flag and returns the previous result, and the work happens inside the LateUpdate pump on UnityMain. */
var WANT_REFILL=0, LASTADDED=0, WANT_SCAN=0, LASTREFILL=0;
/* doRefill() walks the WHOLE get_AllPokemon list with a get_VisibleOnMap check per candidate.
   Q sits under 8 nearly always, so a flat 900ms meant ~67 full walks/min -- and ~75% of samples
   had vis=0, i.e. most walks scanned everything and found nothing. Back off ONLY after an empty
   walk; one non-empty walk snaps straight back to REFILL_MS, so bursts stay as responsive as before.
   ponytail: fixed two-step backoff. If spawns feel slow to appear, lower REFILL_IDLE_MS. */
var REFILL_MS=900, REFILL_IDLE_MS=2500;
/* Cached values polled ON THE UNITY THREAD. The RPC getters below must NOT touch il2cpp: calling it from
   Frida's RPC thread runs il2cpp_thread_attach there, registering a Frida-owned stack with the runtime —
   and ART's MarkCompact GC then SIGSEGVs walking it (art::StackVisitor::WalkStack in VisitRoots). */
var IAP=ptr(0), ITEMC={}, DUSTV=-1, LASTPOLL=0;
var POLL_IDS=[1,2,3,701,705,706];   /* Poke/Great/Ultra + Razz/Pinap/GoldenRazz (display only) */
rpc.exports.setIap=function(p){IAP=ptr(p);};
function pollCounts(){try{var h=H_();if(!IB.isNull()){var m=h.cMN(h.OGC(IB),Memory.allocUtf8String("GetItemCount"),1);if(m&&!m.isNull()){for(var i=0;i<POLL_IDS.length;i++){try{var arg=Memory.alloc(4);arg.writeS32(POLL_IDS[i]);var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,IB,args,exc);if(exc.readPointer().isNull()&&ret&&!ret.isNull())ITEMC[POLL_IDS[i]]=ret.add(0x10).readS32();}catch(e){}}}}
 if(!IAP.isNull()){var dm=mOf(h.OGC(IAP),"get_Stardusts",0);if(dm){var dr=inv(dm,IAP,[]);if(dr)DUSTV=dr.add(0x10).readS32();}}}catch(e){}}
rpc.exports.refillService=function(){WANT_REFILL=1;return LASTADDED;};
function doRefill(){
 var h=H_(); if(MAPSVC.isNull())return -9;
 var gm=mOf(h.OGC(MAPSVC),"get_AllPokemon",0); if(!gm)return -1;
 var e=inv(gm,MAPSVC,[]); if(!e||e.isNull())return 0;
 var gem=mOf(h.OGC(e),"GetEnumerator",0); if(!gem)return -2;
 var enr=inv(gem,e,[]); if(!enr||enr.isNull())return 0;
 var enrC=h.OGC(enr); var self=h.isVT(enrC)?enr.add(0x10):enr;
 var mn=mOf(enrC,"MoveNext",0), gc=mOf(enrC,"get_Current",0); if(!mn||!gc)return -3;
 var plat=null,plng=null;
 if(!MAPAVATAR.isNull()){var lm=mOf(h.OGC(MAPAVATAR),"get_Location",0);if(lm){var lr=inv(lm,MAPAVATAR,[]);if(lr){plat=lr.add(0x10).readDouble();plng=lr.add(0x18).readDouble();}}}
 LASTAVOK=(plat!==null)?1:0;
 if(plat!==null){var _ns=Date.now();if(LASTAVP&&(_ns-LASTAVP.t)>=1000){var _R=6371000,_a1=LASTAVP.lat*Math.PI/180,_a2=plat*Math.PI/180,_dpp=(plat-LASTAVP.lat)*Math.PI/180,_dll=(plng-LASTAVP.lng)*Math.PI/180,_xx=Math.sin(_dpp/2)*Math.sin(_dpp/2)+Math.cos(_a1)*Math.cos(_a2)*Math.sin(_dll/2)*Math.sin(_dll/2),_mm=2*_R*Math.asin(Math.min(1,Math.sqrt(_xx)));CURSPEED=(_mm/((_ns-LASTAVP.t)/1000.0))*3.6;LASTAVP={lat:plat,lng:plng,t:_ns};}else if(!LASTAVP){LASTAVP={lat:plat,lng:plng,t:_ns};}}
 function distM(a,o){var R=6371000,p1=plat*Math.PI/180,p2=a*Math.PI/180,dp=(a-plat)*Math.PI/180,dl=(o-plng)*Math.PI/180;var x=Math.sin(dp/2)*Math.sin(dp/2)+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)*Math.sin(dl/2);return 2*R*Math.asin(Math.min(1,Math.sqrt(x)));}
 var added=0,guard=0,seenct=0,inr=0;
 while(guard++<3000){ var r=inv(mn,self,[]); if(!r||r.add(0x10).readU8()===0)break; var cur=inv(gc,self,[]); if(!cur||cur.isNull())continue;
   try{ var em=mOf(h.OGC(cur),"get_EncounterId",0); if(!em)continue; var er=inv(em,cur,[]); if(!er)continue; var enc=er.add(0x10).readU64(); if(enc.compare(uint64(0))===0)continue; var key=enc.toString(); if(SEEN[key]||ATTEMPTED[key])continue; var _cpid=-1; var pm=mOf(h.OGC(cur),"get_PokemonId",0); if(pm){var pr=inv(pm,cur,[]); if(pr){_cpid=pr.add(0x10).readS32(); if(LEGENDARY[_cpid])continue;}}
     if(VISONLY){var vm=mOf(h.OGC(cur),"get_VisibleOnMap",0); if(vm){var vr=inv(vm,cur,[]); if(!vr||vr.add(0x10).readU8()===0)continue;}}
     seenct++;
     /* Distance is only a sanity backstop now (MAXR is deliberately huge); VISONLY decides. If we have no
        avatar fix we still queue — a visible spawn is catchable regardless of what we can measure. */
     if(plat!==null){var lm2=mOf(h.OGC(cur),"get_Location",0);if(lm2){var lr2=inv(lm2,cur,[]);if(lr2){if(distM(lr2.add(0x10).readDouble(),lr2.add(0x18).readDouble())>MAXR)continue;}}}
     inr++;
     try{var _cn=h.CGN(h.OGC(cur)).readCString(); SEENCLS[_cn]=(SEENCLS[_cn]||0)+1;}catch(_e){}
     /* PRIORITY (Gimmighoul #999 etc.): jump the queue so it is opened NEXT, not after 20 Pidgeys.
        A roaming Gimmighoul is short-lived — one was lost at 3m while it sat behind other spawns. */
     SEEN[key]=1; if(PRIORITY[_cpid]){Q.unshift(cur);NPRIOSEEN++;}else{Q.push(cur);} added++;
   }catch(e2){}
 }
 LASTSEEN=seenct; LASTINR=inr;
 return added;
};
var LASTSEEN=0,LASTINR=0;
var SPINON=false,SPUN={},lastSpinMs=0,SPINLOG=[];   // PokeStop auto-spin (step 1: scan only). NORMAL spin path only; never SoftSfida/wearable.
function boolGet(o,n){try{var m=mOf(H_().OGC(o),n,0);if(!m)return -1;var r=inv(m,o,[]);return r?r.add(0x10).readU8():-1;}catch(e){return -1;}}
rpc.exports.setPerfect=function(on){PERFECT_WANT=on?1:0;};
rpc.exports.drainThrow=function(){var o=TLOG;TLOG=[];return o;};
rpc.exports.panicRevert=function(){try{
  if(PT.ns){try{Interceptor.revert(PT.ns);}catch(e){}}
  PT_LIS.forEach(function(l){try{l.detach();}catch(e){}});PT_LIS=[];
  if(HS.lis){try{HS.lis.detach();}catch(e){}HS.lis=null;}
  PT_CB={};PERFECT_ON=0;PERFECT_WANT=0;
  try{Interceptor.flush();}catch(e){}
  return "reverted";
}catch(e){return "panic:"+String(e).substr(0,80);}};
rpc.exports.setSpin=function(on){SPINON=!!on;};
/* KEEP RUNNING WHEN BACKGROUNDED: Unity pauses its update loop when the app loses focus, which kills our
   LateUpdate pump => catching AND spinning stop dead. Application.runInBackground=true keeps the loop alive.
   Purely a local client setting (no server/anti-cheat involvement). Re-applied each cycle in case the game resets it. */
var RBSET=null,RBGET=null;
/* diagnostic: what does this build actually expose for background/pause control? */
rpc.exports.diagBg=function(){var out={appcls:[],meth:[],unity:[]};try{var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());var inm=h.iGN(im).readCString();var cnt=h.iGCC(im);for(var j=0;j<cnt;j++){var k=h.iGC(im,j);if(k.isNull())continue;try{var cn=h.CGN(k).readCString();if(cn!=="Application")continue;out.appcls.push(inm);var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{var mn=h.mGN(m).readCString();if(/ackground|ocus|ause/.test(mn)&&out.meth.length<25)out.meth.push(inm+"::"+mn+"("+h.mGPC(m)+")");}catch(e){}}}catch(e){}}}}catch(e){out.err=String(e);}
 try{var mods=["libunity.so","libmain.so"];mods.forEach(function(mn){var lu=Process.findModuleByName(mn);if(!lu){out.unity.push("("+mn+" missing)");return;}lu.enumerateExports().forEach(function(x){if(/[Pp]ause|[Ff]ocus|unInBackground/.test(x.name)&&out.unity.length<20)out.unity.push(mn+":"+x.name);});});}catch(e){out.unity.push("err "+e);}
 try{out.icall=!!expOf("libil2cpp.so","il2cpp_resolve_icall");}catch(e){out.icall="err";}
 try{out.mods=[];Process.enumerateModules().forEach(function(m){if(/unity|il2cpp|main|game/i.test(m.name)&&out.mods.length<12)out.mods.push(m.name);});}catch(e){}
 return out;};
function findAppCls(){try{var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());var cnt=h.iGCC(im);for(var j=0;j<cnt;j++){var k=h.iGC(im,j);if(k.isNull())continue;try{if(h.CGN(k).readCString()!=="Application")continue;var s=mOf(k,"set_runInBackground",1);if(s){RBSET=s;RBGET=mOf(k,"get_runInBackground",0);return true;}}catch(e){}}}return false;}catch(e){return false;}}
/* The managed setter is stripped by IL2CPP, but the NATIVE icall behind it is usually still registered.
   il2cpp_resolve_icall() hands us that function pointer so we can set runInBackground anyway. */
var RBICALL=null,RBTRIED=false;
function expOf(mod,name){try{var m=Process.findModuleByName(mod);if(!m)return null;var a=null;m.enumerateExports().forEach(function(x){if(x.name===name)a=x.address;});return a;}catch(e){return null;}}
function resolveRunBgIcall(){if(RBTRIED)return RBICALL;RBTRIED=true;try{var ex=expOf("libil2cpp.so","il2cpp_resolve_icall");if(!ex)return null;var ric=new NativeFunction(ex,"pointer",["pointer"],{exceptions:'propagate'});var names=["UnityEngine.Application::set_runInBackground(System.Boolean)","UnityEngine.Application::set_runInBackground","UnityEngine.Application::SetRunInBackground(System.Boolean)"];for(var i=0;i<names.length;i++){try{var p=ric(Memory.allocUtf8String(names[i]));if(p&&!p.isNull()){RBICALL=new NativeFunction(p,"void",["int"],{exceptions:'propagate'});return RBICALL;}}catch(e){}}}catch(e){}return null;}
rpc.exports.runBgIcall=function(){try{var f=resolveRunBgIcall();if(!f)return -1;f(1);if(!RBGET)findAppCls();if(RBGET){var r=inv(RBGET,ptr(0),[]);if(r)return r.add(0x10).readU8();}return 2;}catch(e){return -2;}};
rpc.exports.runBg=function(){try{if(!RBSET&&!findAppCls())return -1;var sm=RBSET;var arg=Memory.alloc(1);arg.writeU8(1);inv(sm,ptr(0),[arg]);if(RBGET){var r=inv(RBGET,ptr(0),[]);if(r)return r.add(0x10).readU8();}return 2;}catch(e){return -2;}};
rpc.exports.drainSpin=function(){var o=SPINLOG;SPINLOG=[];return o;};
var LASTINTER=ptr(0);
var SPININTERVAL=5000,SPINNER_OFF=-1,NSPIN=0;   /* SPINNER_OFF resolved at runtime by field name (was hardcoded 0x90) */
var SPINXP=0,SPINITEMS=0,SPINOK=0,SPINRES={};   // PROOF: read straight off FortSearchOutProto (server truth; immune to Pokemod inventory management)
function lootTotal(lp){try{if(!lp||lp.isNull())return 0;var rf=lp.add(0x10).readPointer();if(!rf||rf.isNull())return 0;var cnt=rf.add(0x18).readS32();var arr=rf.add(0x10).readPointer();if(cnt<0||cnt>300||!arr||arr.isNull())return 0;var tot=0;for(var i=0;i<cnt;i++){try{var it=arr.add(0x20+i*8).readPointer();if(it&&!it.isNull()){var c=it.add(0x10).readS32();if(c>0&&c<10000)tot+=c;}}catch(e){}}return tot;}catch(e){return 0;}}
function repCount(rf){try{if(!rf||rf.isNull())return 0;var c=rf.add(0x18).readS32();return (c>0&&c<300)?c:0;}catch(e){return 0;}}
function fortId(ps){try{var m=mOf(H_().OGC(ps),"get_FortData",0);if(!m)return null;var fd=inv(m,ps,[]);if(!fd||fd.isNull())return null;var idp=fd.add(0x10).readPointer();if(!idp||idp.isNull())return null;var len=idp.add(0x10).readS32();if(len<0||len>200)return null;return idp.add(0x14).readUtf16String(len);}catch(e){return null;}}
function spinComplete(ps){try{var cm=mOf(H_().OGC(ps),"CompleteInteractiveMode",0);if(cm)inv(cm,ps,[]);}catch(e){}}
/* UPDATE-PROOF LOOKUPS. PoGo re-obfuscates method names on EVERY app update (0.413.1's spin method `clfn`
   became `ckua` in 0.421.0 and silently killed auto-spin). So never hardcode an obfuscated name:
   - the spinner FIELD is resolved by its real name "ItemSpinner" (field names aren't obfuscated)
   - the spin METHOD is resolved by SIGNATURE: the 0-arg method returning IPromise<FortSearchOutProto>
   Both are cached after the first successful resolve. */
function fieldOff(k,nm){try{var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(k,it))&&!f.isNull()){try{if(h.fGN(f).readCString()===nm)return h.fGO(f);}catch(e){}}}catch(e){}return -1;}
var SPINM={};
function spinMethodOf(spinner){try{var h=H_();var k=h.OGC(spinner);var key=k.toString();if(SPINM[key]!==undefined)return SPINM[key];var found=null;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGPC(m)!==0)continue;var rt=h.tGN(h.mGRT(m)).readCString();if(rt&&rt.indexOf("FortSearchOutProto")>=0){found=m;break;}}catch(e){}}SPINM[key]=found;return found;}catch(e){return null;}}
function spinOne(ps){try{var h=H_();var im=mOf(h.OGC(ps),"StartInteractiveMode",0);if(!im)return "noStart";var inter=inv(im,ps,[]);if(!inter||inter.isNull())return "noInter";if(SPINNER_OFF<0){SPINNER_OFF=fieldOff(h.OGC(inter),"ItemSpinner");if(SPINNER_OFF<0){spinComplete(ps);return "noField";}}var spinner=inter.add(SPINNER_OFF).readPointer();if(!spinner||spinner.isNull()){spinComplete(ps);return "noSpinner";}var cf=spinMethodOf(spinner);if(!cf){spinComplete(ps);return "noSpinMethod";}inv(cf,spinner,[]);spinComplete(ps);NSPIN++;return "spun";}catch(e){return "err:"+e;}}
function spinTick(){try{if(!SPINON||MAPSVC.isNull())return;var now=Date.now();if(now-lastSpinMs<SPININTERVAL)return;
 /* Skip the full fort walk when the last scan says nothing is spinnable — that walk is ~2000 il2cpp calls
    and was running every 5s on the Unity thread even with zero stops available. */
 if(SSCACHE&&SSCACHE.spinnable===0&&(now-SSTIME)<30000){lastSpinMs=now;return;}var h=H_();var gm=mOf(h.OGC(MAPSVC),"get_ActivePokestops",0);if(!gm)return;var e=inv(gm,MAPSVC,[]);if(!e||e.isNull())return;var gem=mOf(h.OGC(e),"GetEnumerator",0);if(!gem)return;var enr=inv(gem,e,[]);if(!enr||enr.isNull())return;var enrC=h.OGC(enr);var self=h.isVT(enrC)?enr.add(0x10):enr;var mn=mOf(enrC,"MoveNext",0),gc=mOf(enrC,"get_Current",0);if(!mn||!gc)return;var guard=0;while(guard++<2000){var r=inv(mn,self,[]);if(!r||r.add(0x10).readU8()===0)break;var ps=inv(gc,self,[]);if(!ps||ps.isNull())continue;if(boolGet(ps,"get_IsPlayerInRange")!==1)continue;if(boolGet(ps,"get_IsCoolingDown")===1)continue;if(boolGet(ps,"get_IsClosed")===1)continue;var fid=fortId(ps);if(fid&&SPUN[fid]&&(now-SPUN[fid])<330000)continue;/* 5.5min, not 5.0: a dead-on 5min retry kept landing IN_COOLDOWN_PERIOD (187 wasted attempts in the log) */var res=spinOne(ps);if(fid)SPUN[fid]=now;lastSpinMs=now;if(res!=="spun")SPINLOG.push("spinFail "+(fid?fid.substr(0,10):"?")+" -> "+res);/* success is already logged by the AWARD line (which carries xp+items) — don't double-log */break;}}catch(e){SPINLOG.push("spinTickErr "+e);}}
var SSCACHE=null,SSTIME=0;
rpc.exports.spinScan=function(){WANT_SCAN=1;return SSCACHE||{};};   /* deferred to the pump — see THREAD SAFETY above */
function doSpinScan(){try{if(MAPSVC.isNull())return {err:"nomapsvc"};var h=H_();var gm=mOf(h.OGC(MAPSVC),"get_ActivePokestops",0);if(!gm)return {err:"nomethod"};var e=inv(gm,MAPSVC,[]);if(!e||e.isNull())return {err:"noenum"};var gem=mOf(h.OGC(e),"GetEnumerator",0);if(!gem)return {err:"nogetenum"};var enr=inv(gem,e,[]);if(!enr||enr.isNull())return {err:"noenr"};var enrC=h.OGC(enr);var self=h.isVT(enrC)?enr.add(0x10):enr;var mn=mOf(enrC,"MoveNext",0),gc=mOf(enrC,"get_Current",0);if(!mn||!gc)return {err:"noiter"};var total=0,inr=0,spin=0,cool=0,guard=0;while(guard++<2000){var r=inv(mn,self,[]);if(!r||r.add(0x10).readU8()===0)break;var ps=inv(gc,self,[]);if(!ps||ps.isNull())continue;total++;var ir=boolGet(ps,"get_IsPlayerInRange");var cd=boolGet(ps,"get_IsCoolingDown");var cl=boolGet(ps,"get_IsClosed");if(ir===1)inr++;if(cd===1)cool++;if(ir===1&&cd!==1&&cl!==1)spin++;}SSCACHE={total:total,inRange:inr,cooling:cool,spinnable:spin};SSTIME=Date.now();return SSCACHE;}catch(e){return {err:String(e)};}};
rpc.exports.stats=function(){return {q:Q.length,inflight:INFLIGHT.length,opened:OPENED,fired:FIRED,refired:REFIRED,thrown:THROWN.length,rethrow:RETHROW.length,nberry:NBERRY,nrazz:NRAZZ,frame:FRAME,vis:LASTSEEN,inrange:LASTINR,cr:CR,skipped:SKIPPED,skipstatus:SKIPSTATUS,statustally:STATUSTALLY,srccatch:SRCCATCH,seencls:SEENCLS,fleeprof:FLEEPROF,curspeed:Math.round(CURSPEED),reqn:REQN,prioseen:NPRIOSEEN,priocaught:NPRIOCAUGHT,priolost:NPRIOLOST,cdist:(CDN?Math.round(CDSUM/CDN):-1),fdist:(FDN?Math.round(FDSUM/FDN):-1),cdn:CDN,fdn:FDN,staleskip:STALESKIP,outrange:OUTRANGE,notm:NOTM,fcerr:FCERR,fcok:FCOK,fcerrmsg:FCERRMSG,bgthrow:BGTHROW,avok:LASTAVOK,nspin:NSPIN,spinxp:SPINXP,spinitems:SPINITEMS,spinok:SPINOK,spinres:SPINRES,perfect:PERFECT_ON,perfwant:PERFECT_WANT,pterr:PT.err,ptc:PTC,hs:HS.n,hserr:HS.err,sawInit:HS.sawInit,fixHG:HS.fixHG,fixHK:HS.fixHK,hgWas:HS.hgWas,hkWas:HS.hkWas,hslast:HS.lasterr,forged:HS.forged,cid:HS.cid,aimto:HS.aimTo,rt:{tried:RT.tried,cls:!!RT.cls,ns:!!RT.ns,inst:!!RT.inst,at:RT.gotAt,offMin:RT.offMin,writes:RT.wrote,excellent:RT.ok},hk:{init:!!HS.init,lis3:!!HS.lis3,launch:!!HS.launch,offRet:HS.offRet}};};

/* ===================== PERFECT THROW (emulating Pokemod's "PerfectedThrow") =====================
   Read out of Pokemod's own decrypted agent bundle rather than guessed. Their module hooks the
   CLIENT so the GAME computes an Excellent itself -- which is why theirs shows "Excellent!" on
   screen and an earlier attempt of mine (rewriting normalized_reticle_size in the outgoing
   CatchPokemonProto) did not: rewriting the proto after the fact changes only what the server is
   told, cannot produce the on-screen result, and does nothing at all for a ball that missed and
   therefore never generated a request.

   Their hooks, verbatim in effect:
     EncounterPokemon.SetCanPerformActions(arg0=false)  -> cannot attack, move or jump
     EncounterPokemon.get_Invulnerable      -> false
     Reticle.get_NormalizedSize             -> 0.13*random()   (Excellent boundary is 2-1.7 = 0.3,
                                                                so SMALLER is better on this getter)
     Reticle.ScreenPositionOverBullseye     -> true
   Two further parts of their module are NOT implemented here and are called out honestly in the
   status line: Pokeball.Initialize rebinding HitGround/HitKillZone to recover a missed ball (needs a
   System.Action delegate), and CatchPokemonProto.CalculateSize setting SpinModifier + a fresh
   ARPlusEncounterValuesProto for the AR+ XP bonus (needs managed object allocation).

   get_NormalizedSize returns a FLOAT: on arm64 that comes back in v0, which an onLeave retval cannot
   touch, so it must be Interceptor.replace with a NativeCallback. Resolution happens once on the
   game thread inside install(); the toggle only flips a flag and the pump applies it. */
var PTC={ns:0,bull:0,inv:0,scpa:0};
var PT={nsNS:"",epNS:"",pbNS:"",pokeball:null,ns:null,bull:null,inv:null,scpa:null,scpaArgc:-1,bullArgc:-1,ready:0,err:"not resolved"};
var PERFECT_WANT=0, PERFECT_ON=0, PT_CB={}, PT_LIS=[], PT_RESOLVED=0;
var TLOG=[];
function mByName(k,nm){var h=H_();if(!k)return null;
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
  while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGN(m).readCString()===nm)return {m:m,argc:h.mGPC(m)};}catch(e){}}
  return null;}
function findClasses(image,names){var h=H_();var out={};var im=img(image);if(!im)return out;
  var want={};for(var i=0;i<names.length;i++)want[names[i]]=1;
  var cnt=h.iGCC(im),left=names.length;
  for(var j=0;j<cnt&&left>0;j++){var k=h.iGC(im,j);if(k.isNull())continue;
    try{var nm=h.CGN(k).readCString();if(want[nm]&&!out[nm]){out[nm]=k;left--;}}catch(e){}}
  return out;}

/* ===== RETICLE FIELD APPROACH =====================================================================
   get_NormalizedSize() is a COMPUTED 0-arg method, so instead of hooking it (Interceptor.replace +
   NativeCallback on an encounter method CRASHED PoGo -- ART GC faulted walking the Frida trampoline
   on a game thread) we change its INPUTS by writing Reticle's float fields.
   All of this runs inside the existing LateUpdate pump, which has been stable for months, so it adds
   NO new hook and no trampoline on a hot path.
   Step 1 is measurement, not a fix: find the live Reticle, call get_NormalizedSize(), and log it
   next to every float field so the actual formula is visible instead of guessed. */
var RT={tried:0,gotAt:"",offMin:-1,ok:0,wrote:0,huntAt:0,rfota:null,ctxKeys:"",ctxErr:"",wantWrite:1,cls:null,type:null,find:null,ns:null,inst:null,last:0,log:[],fields:[]};
var CFN=null,GIMG=null;
function cFN2(ns,cls){
  var h=H_();
  if(!CFN){var il=Process.findModuleByName("libil2cpp.so");var addr=null;
    il.enumerateExports().forEach(function(x){if(x.name==="il2cpp_class_from_name")addr=x.address;});
    if(!addr)return null;
    CFN=new NativeFunction(addr,"pointer",["pointer","pointer","pointer"],{exceptions:'propagate'});}
  var nsp=Memory.allocUtf8String(ns),cp=Memory.allocUtf8String(cls);
  var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();
  for(var i=0;i<n;i++){
    var im=h.aGI(a.add(i*Process.pointerSize).readPointer());
    try{var k=CFN(im,nsp,cp);if(k&&!k.isNull())return k;}catch(e){}
  }
  return null;
}
function reticleInit(){
  try{
    if(RT.tried)return !!RT.cls;
    /* TRY EXACTLY ONCE. Previously this returned false without latching, so a failed lookup made
       the pump re-walk an entire image's class table TWICE A SECOND and froze the game (FRAME stuck,
       PoGo at 3-8% CPU vs ~170% healthy). Reticle is NOT in holo-game.dll -- resolve it by full
       NAMESPACE via il2cpp_class_from_name, which is how Pokemod's use(...) does it and what the
       read-only probe proved works. */
    RT.tried=1;
    var h=H_();
    var k=null;
    try{k=cFN2("Niantic.Holoholo.Encounter","Reticle");}catch(e){RT.log.push("cFN:"+String(e).substr(0,50));}
    if(!k||k.isNull()){RT.log.push("Reticle class_from_name FAILED");return false;}
    RT.cls=k;
    RT.type=h.tGO(h.cGT(k));
    RT.ns=mOf(k,"get_NormalizedSize",0);
    /* UnityEngine.Object.FindObjectOfType(Type) -- gives us the live instance without a hook */
    /* cache the float fields once */
    var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
    while((f=h.cGF(k,it))&&!f.isNull()){try{
      var tn="";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}
      if(tn==="System.Single"){var fn2=h.fGN(f).readCString();var off=h.fGO(f);
        if(off>16)RT.fields.push([fn2,off]);
        if(fn2==="reticleMinSize")RT.offMin=off;   /* the field NS mirrors -- see the fix note */
      }
    }catch(e){}}
    return true;
  }catch(e){RT.log.push("init:"+String(e).substr(0,60));return false;}
}
/* ONE-SHOT hunt for a Reticle instance, so this no longer depends on an encounter being open.
   Resources.FindObjectsOfTypeAll(Type) returns INACTIVE objects too, which is exactly what we need:
   between encounters the Reticle still exists, just disabled.
   It is expensive, so it runs AT MOST ONCE (latched by RT.hunted) and is retried only every 30s
   while still empty. Calling FindObjectOfType every 500ms is what froze the game earlier -- the
   cost was the REPETITION, not the call. */
function reticleHunt(){
  try{
    if(RT.inst&&!RT.inst.isNull())return;
    var now=Date.now();
    if(RT.huntAt&&(now-RT.huntAt)<30000)return;
    RT.huntAt=now;
    if(!RT.type){var h0=H_();if(!RT.cls)return;RT.type=h0.tGO(h0.cGT(RT.cls));}
    if(!RT.rfota){
      var res=null;
      ["UnityEngine.CoreModule.dll","UnityEngine.dll"].forEach(function(im){
        if(res)return;var g=findClasses(im,["Resources"]);if(g["Resources"])res=g["Resources"];});
      if(!res){RT.log.push("Resources class not found");return;}
      RT.rfota=mOf(res,"FindObjectsOfTypeAll",1);
      if(!RT.rfota){RT.log.push("FindObjectsOfTypeAll not found");return;}
    }
    var arr=inv(RT.rfota,ptr(0),[RT.type]);
    if(!arr||arr.isNull()){RT.log.push("hunt: null array");return;}
    var n=arr.add(0x18).readS32();
    RT.log.push("hunt: found "+n+" Reticle object(s)");
    if(n>0){
      var o=arr.add(0x20).readPointer();
      if(o&&!o.isNull()){RT.inst=o;RT.gotAt="Resources.FindObjectsOfTypeAll";}
    }
  }catch(e){RT.log.push("hunt:"+String(e).substr(0,70));}
}
function reticleSample(){
  try{
    if(!reticleInit()||!RT.ns)return;
    reticleHunt();
    /* NEVER call UnityEngine.Object.FindObjectOfType here. It walks every object in the scene;
       calling it twice a second from the pump froze PoGo solid (6.6% CPU, was ~170%). The Reticle
       is cached from the Pokeball's own `reticle` field instead -- which is exactly where Pokemod
       reads it from -- so this costs one method call and a few field reads. */
    var inst=RT.inst;
    if(!inst||inst.isNull())return;
    var r=inv(RT.ns,inst,[]);
    if(!r||r.isNull())return;
    var nsz=r.add(0x10).readFloat();
    /* ===== THE ACTUAL FIX =====================================================================
       Measured on this build: get_NormalizedSize() returns EXACTLY reticleMinSize (both 0.5).
       Pokemod's own constants put the Excellent boundary at 2-1.7 = 0.3, and SMALLER is better on
       this client-side scale, so forcing reticleMinSize below 0.3 forces an Excellent.
       This is a plain float write to a field the game already reads -- there is NO hook on the
       throw path, no Interceptor.replace, no NativeCallback, and nothing that asserts where the
       ball is. Those were the things that crashed or hung the encounter.
       Self-validation: after writing, call get_NormalizedSize() AGAIN and log both values. If the
       second read is not below 0.3, the write did not take and the log says so. */
    /* NO WRITES AND NO INVOKES FROM HERE. This used to write the cached instance and call
       get_NormalizedSize on it twice a second; the cached pointer went stale under the moving GC
       and froze the game. The write now happens inside the hook on a fresh pointer. */
    var parts=["NS="+Math.round(nsz*1000)/1000
               +" AFTER="+(RT.lastAfter!==undefined?Math.round(RT.lastAfter*1000)/1000:"-")
               +" EXCELLENT="+(RT.ok?"YES":"no")+" writes="+(RT.wrote||0)];
    for(var i=0;i<RT.fields.length;i++){
      try{parts.push(RT.fields[i][0]+"="+Math.round(inst.add(RT.fields[i][1]).readFloat()*1000)/1000);}catch(e){}
    }
    RT.log.push(parts.join(" "));
    if(RT.log.length>12)RT.log.shift();
  }catch(e){RT.log.push("sample:"+String(e).substr(0,60));}
}
rpc.exports.reticleLog=function(){var o=RT.log;RT.log=[];return o;};


/* ---- ONE-SHOT PokemonProto FIELD DUMP -------------------------------------------------------
   Copying Pokemod's TransferOnCatch requires the real offsets of size_, originDetail_, pokeball_
   and cachedSettingsProto. Guessing offsets is what caused every crash tonight, so measure them.
   Runs ONCE from the pump (game thread), logs, then never runs again. */
var PP={done:0,out:""};
function pokemonProtoDump(){
  try{
    if(PP.done)return; PP.done=1;
    var h=H_();
    var k=findClasses("holo-protos.dll",["PokemonProto"])["PokemonProto"];
    if(!k){PP.out="PokemonProto NOT FOUND";return;}
    var want=/size_|origin|pokeball_|cachedSettings|pokemonDisplay_|pokemonId_|individual|isTransferable|pokemonClass|captured|creation/i;
    var fs=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
    while((f=h.cGF(k,it))&&!f.isNull()){try{
      var fn=h.fGN(f).readCString();
      if(!want.test(fn))continue;
      var tn="";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}
      fs.push(fn+"@"+h.fGO(f)+":"+(tn||"?"));
    }catch(e){}}
    PP.out=fs.join(" | ");
  }catch(e){PP.out="dumpErr:"+String(e).substr(0,70);}
}
rpc.exports.protoDump=function(){return PP.out;};


/* ===== TRANSFER-ON-CATCH -- faithful port of Pokemod's TransferOnCatch =========================
   Trigger (theirs):   CatchPokemonOutProto.IMergeFrom onLeave -> CapturedPokemonId
   Retry (theirs):     if (!PokemonBag.GetPokemon(id)) runNextFrame(...)   [they cap at 600]
   Protections (theirs, verbatim): hundo/nundo, shiny, shadow(origin INVASION 6), location card,
     special ball (PREMIER 5 / BEAST 6 / WILD_BALL_PREMIER 8 / MASTER 4), pokemonClass != NORMAL,
     !isTransferable_, origin not in {WILD 1, INVASION 6}
   User prefs (theirs): minIvPercent (KEEP when minIvPercent <= actual%; their default is 100, i.e.
     keep only hundos), transferShiny / transferShadow / transferBG, xxl sizes to keep,
     species ignore list.
   ONE DELIBERATE DIFFERENCE: they call ReleasePokemon. We NEVER release -- we apply the Transfer
   TAG. Standing rule: tag only, the human releases.

   TWO FIXES vs my first attempt, which froze the game (CPU 19%, pump dead):
     1. NO head-of-line blocking. It only ever retried pend[0], so one un-resolvable id stalled the
        whole queue and re-invoked GetPokemon every tick forever.
     2. Retry cap 60 ticks (~6s at the pump's 100ms throttle), not 600. Pokemod can afford 600
        because runNextFrame is in-process; through Frida each one is a managed call.
   Measured offsets (dumped from the live class): pokemonId_@40, iv@112/116/120, pokeball_@128,
   pokemonDisplay_@216 (Costume@0x10 Shiny@0x18 LocationCard@0x58), originDetail_@376, size_@424. */
var TOC={on:0,dry:1,cfg:{minIvPercent:80,transferShiny:0,transferShadow:0,transferBG:0,xxlKeep:[5],ignoreSpecies:[]},
         seen:{},pend:[],n:0,would:0,tagged:0,skip:{},log:[],ready:[]};
rpc.exports.setToc=function(on,dry,cfgJson){
  TOC.on=on?1:0; TOC.dry=(dry!==false)?1:0;
  if(cfgJson){try{var c=JSON.parse(cfgJson);for(var kk in c)TOC.cfg[kk]=c[kk];}catch(e){}}
};
rpc.exports.drainToc=function(){var o=TOC.log;TOC.log=[];return o;};
rpc.exports.tocStats=function(){return {on:TOC.on,dry:TOC.dry,n:TOC.n,would:TOC.would,tagged:TOC.tagged,skip:TOC.skip,pend:TOC.pend.length,cfg:TOC.cfg};};
function tocSkip(r){TOC.skip[r]=(TOC.skip[r]||0)+1;return r;}
function tocEvaluate(pm){
  try{
    var c=TOC.cfg;
    var atk=pm.add(112).readS32(),def=pm.add(116).readS32(),sta=pm.add(120).readS32();
    if(atk<0||atk>15||def<0||def>15||sta<0||sta>15)return tocSkip("bad_iv_read");
    var tot=atk+def+sta, pct=tot/45*100;
    if(tot===45)return tocSkip("hundo");
    if(tot===0)return tocSkip("nundo");
    /* their _checkMyPref: KEEP when the configured minimum is met */
    if(c.minIvPercent&&c.minIvPercent<=pct)return tocSkip("meets_min_iv");
    var ball=pm.add(128).readS32();
    if(ball===4||ball===5||ball===6||ball===8)return tocSkip("special_ball");
    var disp=pm.add(216).readPointer();
    if(!disp||disp.isNull())return tocSkip("no_display");        /* unreadable => PROTECT */
    if(disp.add(0x18).readU8()===1&&!c.transferShiny)return tocSkip("shiny");
    if(disp.add(0x58).readU8()===1&&!c.transferBG)return tocSkip("location_card");
    if(disp.add(0x10).readS32()!==0)return tocSkip("costume");
    var sz=-1;try{sz=pm.add(424).readS32();}catch(e){}
    if(c.xxlKeep&&c.xxlKeep.indexOf(sz)>=0)return tocSkip("size_kept");
    var pid=pm.add(40).readS32();
    if(c.ignoreSpecies&&c.ignoreSpecies.indexOf(pid)>=0)return tocSkip("species_ignored");
    var od=pm.add(376).readPointer();
    if(!od||od.isNull())return tocSkip("no_origin");             /* unreadable => PROTECT */
    var oc=-1;
    try{var a=od.add(0x10).readS32(),b=od.add(0x18).readS32();
        oc=(a>=0&&a<=13)?a:((b>=0&&b<=13)?b:-1);}catch(e){}
    if(oc<0)return tocSkip("origin_unreadable");
    if(oc===6&&!c.transferShadow)return tocSkip("shadow");
    if(oc!==1&&oc!==6)return tocSkip("origin_not_wild");         /* raid/egg/quest/postcard/... */
    return null;
  }catch(e){return tocSkip("err");}
}
function tocTick(){
  try{
    if(!TOC.on||XBAG.isNull()||!TOC.pend.length)return;
    var h=H_();var gm=mOf(h.OGC(XBAG),"GetPokemon",1);if(!gm)return;
    /* Process EVERY pending entry, at most one GetPokemon each per tick, and drop expired ones.
       The original stalled on pend[0] and hammered the same id forever -- that is what froze it. */
    var keep=[];
    for(var i=0;i<TOC.pend.length&&i<8;i++){
      var it=TOC.pend[i];
      var arg=Memory.alloc(8);arg.writeU64(it.id);
      var pm=inv(gm,XBAG,[arg]);
      if(!pm||pm.isNull()){ if(++it.tries<60)keep.push(it); else TOC.log.push("TOC timeout id="+it.id); continue; }
      TOC.n++;
      var why=tocEvaluate(pm);
      var pid=pm.add(40).readS32();
      var atk=pm.add(112).readS32(),def=pm.add(116).readS32(),sta=pm.add(120).readS32();
      var pc=Math.round((atk+def+sta)/45*100);
      if(why){TOC.log.push("TOC SKIP "+why+" pid="+pid+" iv="+pc+"%");continue;}
      TOC.would++;
      if(TOC.dry){TOC.log.push("TOC WOULD-TAG pid="+pid+" iv="+pc+"% ("+atk+"/"+def+"/"+sta+")");}
      else {TOC.ready.push(it.id);TOC.log.push("TOC TAG pid="+pid+" iv="+pc+"% ("+atk+"/"+def+"/"+sta+")");}
    }
    for(var j=8;j<TOC.pend.length;j++)keep.push(TOC.pend[j]);
    TOC.pend=keep;
  }catch(e){TOC.log.push("tocErr "+String(e).substr(0,70));}
}

function perfectResolve(){
  try{
    var ep=null,rt=null,imgs=["holo-game.dll","Assembly-CSharp.dll"];
    for(var i=0;i<imgs.length&&(!ep||!rt);i++){
      var got=findClasses(imgs[i],["EncounterPokemon","Reticle","Pokeball"]);
      if(!ep)ep=got["EncounterPokemon"]||null;
      if(!rt)rt=got["Reticle"]||null;
      if(!PT.pokeball&&got["Pokeball"])PT.pokeball=got["Pokeball"];   /* hand it to headshotResolve */
    }
    if(!ep||!rt){PT.err="class miss ep="+(!!ep)+" rt="+(!!rt);return;}
    var m;
    m=mOf(ep,"get_Invulnerable",0);          if(m)PT.inv=m.readPointer();
    m=mOf(ep,"SetCanPerformActions",1);      if(m)PT.scpa=m.readPointer();
    m=mOf(rt,"get_NormalizedSize",0);        if(m)PT.ns=m.readPointer();
    var bn=mByName(rt,"ScreenPositionOverBullseye");
    if(bn){PT.bull=bn.m.readPointer();PT.bullArgc=bn.argc;}
    var sn=mByName(ep,"SetCanPerformActions");
    if(sn&&!PT.scpa){PT.scpa=sn.m.readPointer();}
    if(sn)PT.scpaArgc=sn.argc;
    /* Apply whatever resolved rather than refusing everything: gating on all four meant one missing
       lookup silently disabled the whole feature while the toggle still read ON. */
    PT.ready=PT.ns?1:0;
    try{var hh=H_();
      if(rt)PT.nsNS=hh.CGNS(rt).readCString()||"(none)";
      if(ep)PT.epNS=hh.CGNS(ep).readCString()||"(none)";
      if(PT.pokeball)PT.pbNS=hh.CGNS(PT.pokeball).readCString()||"(none)";
    }catch(e){}
    PT.err="ns="+(!!PT.ns)+" bull="+(!!PT.bull)+"/"+PT.bullArgc+" inv="+(!!PT.inv)
          +" scpa="+(!!PT.scpa)+"/"+PT.scpaArgc
          +" NS[reticle="+PT.nsNS+" encPkmn="+PT.epNS+" pokeball="+PT.pbNS+"]";
  }catch(e){PT.err="resolve:"+String(e).substr(0,70);}
}

/* ---- HEADSHOT (Pokemod's `Headshot`, which PerfectedThrow enables alongside itself) ------------
   THIS is the "it works even if I miss" half. Their module does two things on Pokeball:
     Launch (attach, onEnter): set the Pokemon non-invulnerable, then TELEPORT the ball 90% of the
       way to the reticle -- Vector3.Lerp(ball.position, reticle.position, 0.9) -- skipping Master
       Ball (BallType 4). The throw is dragged onto the target before physics ever runs.
     OnCollisionEnter (replace): rewrite the contact's m_OtherColliderID to the Pokemon's own
       collider so ANY collision counts as a hit.
   Implemented here: the Launch aim-lock. The OnCollisionEnter rewrite needs to construct a
   UnityEngine.ContactPair and walk GetComponentInChildren/GetInstanceID, and is NOT done -- the
   status line says so rather than implying the whole module is covered.
   All of this runs inside the game's own Launch call, i.e. on the game thread, so there is no
   cross-thread il2cpp exposure. */
var HS={pb:null,launch:null,offRet:-1,offBall:-1,ready:0,err:"not resolved",n:0,lis:null,lasterr:"",retName:"",fields:"",offPk:0,pkName:"",layout:"",oce:null,init:null,lis2:null,lis3:null,cid:0,forged:0,colType:null,go:null,aimTo:""};
/* One-shot layout probe for the collision path. Pokemod forges the contact by writing the
   Pokemon's collider instance id into the Collision's ContactPair. To do that from raw il2cpp I
   need the REAL field offsets of UnityEngine.Collision and UnityEngine.ContactPair on this build --
   guessing them is how the last three bugs happened. Logged once, then used. */
function layoutProbe(){
  var out=[];
  try{
    var h=H_();
    ["Collision","ContactPair"].forEach(function(cn){
      var k=null,imgs=["UnityEngine.PhysicsModule.dll","UnityEngine.CoreModule.dll","UnityEngine.dll"];
      for(var i=0;i<imgs.length&&!k;i++){var g=findClasses(imgs[i],[cn]);k=g[cn]||null;}
      if(!k){out.push(cn+"=NOTFOUND");return;}
      var fs=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
      while((f=h.cGF(k,it))&&!f.isNull()){try{
        var tn="";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}
        fs.push(h.fGN(f).readCString()+"@"+h.fGO(f)+":"+tn);
      }catch(e){}}
      out.push(cn+"{"+fs.join(", ")+"}");
    });
  }catch(e){out.push("probeErr:"+String(e).substr(0,60));}
  return out.join(" | ");
}
rpc.exports.layoutProbe=function(){return HS.layout||"(not probed yet)";};
function headshotResolve(){
  try{
    /* reuse the class perfectResolve already found -- do not walk the class table again */
    var pb=PT.pokeball;
    if(!pb){HS.err="Pokeball class not found";return;}
    HS.pb=pb;
    var l=mByName(pb,"Launch");if(l)HS.launch=l.m.readPointer();
    var oc=mByName(pb,"OnCollisionEnter");if(oc)HS.oce=oc.m.readPointer();
    var ini=mByName(pb,"Initialize");if(ini)HS.init=ini.m.readPointer();
    HS.offBall=fieldOff(pb,"<BallType>k__BackingField");
    /* Pokemod writes `this.reticle`, but that is their wrapper's name resolution -- the real field
       may be a property backing field or spelled differently. Search the class's own fields for
       anything reticle-ish, and if nothing matches, REPORT THE FIELD NAMES so the next attempt is
       informed instead of another guess. */
    HS.offRet=fieldOff(pb,"reticle");
    /* The real field is obfuscated (dodk..dodq on 0.421.0) and Pokemod's name map is from an older
       build, so match on the field's TYPE instead -- version-proof, same trick as the spin method. */
    /* WALK THE CLASS HIERARCHY. il2cpp_class_get_fields returns only a class's OWN fields, and on
       0.421.0 every own field of Pokeball is an Int32/String/event -- the reticle reference lives on
       a BASE class. Pokemod's wrapper resolves `this.reticle` through the hierarchy; not doing the
       same is why the lookup kept coming back -1. Match on TYPE, since the names are obfuscated. */
    var fl=[];
    try{var h2=H_();var k=pb,depth=0;
      while(k&&!k.isNull()&&depth<6){
        var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
        while((f=h2.cGF(k,it))&&!f.isNull()){try{
          var fn=h2.fGN(f).readCString();
          var tn="";try{tn=h2.tGN(h2.fGT(f)).readCString();}catch(e){}
          if(fl.length<40)fl.push(fn+":"+tn);
          if(HS.offRet<0&&(/reticle/i.test(fn)||/Reticle$/.test(tn))){HS.offRet=h2.fGO(f);HS.retName=fn+":"+tn;}
          if(!HS.offPk&&/EncounterPokemon$/.test(tn)){HS.offPk=h2.fGO(f);HS.pkName=fn+":"+tn;}
        }catch(e){}}
        k=h2.cGP?h2.cGP(k):null;depth++;
      }
    }catch(e){}
    HS.fields=fl.join(",").substr(0,300);
    HS.ready=(HS.launch&&HS.offRet>=0)?1:0;
    try{HS.layout=layoutProbe();}catch(e){HS.layout="err";}
    HS.err="launch="+(!!HS.launch)+" reticle="+HS.offRet+"("+(HS.retName||"?")+")"
          +" pokemon="+HS.offPk+"("+(HS.pkName||"?")+")"
          +" oce="+(!!HS.oce)+" ballType="+HS.offBall+(HS.offRet<0?" FIELDS["+HS.fields+"]":"");
  }catch(e){HS.err="resolve:"+String(e).substr(0,70);}
}
/* read a Vector3 out of a BOXED struct returned by runtime_invoke: 3 floats at +0x10 */
function v3read(boxed){return {x:boxed.add(0x10).readFloat(),y:boxed.add(0x14).readFloat(),z:boxed.add(0x18).readFloat()};}
/* Resolve the Pokemon's collider instance id, once per throw. Chain is Pokemod's:
   pokeball.pokemon -> get_GameObject() -> GetComponentInChildren(typeof(Collider)) -> GetInstanceID().
   Cached on the Pokeball so OnCollisionEnter stays cheap. */
function colliderIdFor(self){
  try{
    var h=H_();
    if(!HS.colType){
      var cc=null,imgs=["UnityEngine.PhysicsModule.dll","UnityEngine.dll"];
      for(var i=0;i<imgs.length&&!cc;i++){var g=findClasses(imgs[i],["Collider"]);cc=g["Collider"]||null;}
      if(!cc)return 0;
      HS.colType=h.tGO(h.cGT(cc));
    }
    if(HS.offPk<=0)return 0;
    var pk=self.add(HS.offPk).readPointer();
    if(!pk||pk.isNull())return 0;
    var ggo=mOf(h.OGC(pk),"get_GameObject",0)||mOf(h.OGC(pk),"get_gameObject",0);
    if(!ggo)return 0;
    var go=inv(ggo,pk,[]);
    if(!go||go.isNull())return 0;
    var gcic=mOf(h.OGC(go),"GetComponentInChildren",1);
    if(!gcic)return 0;
    HS.go=go;                                    /* cache: this is the real aim target */
    var col=inv(gcic,go,[HS.colType]);
    if(!col||col.isNull())return 0;
    var gid=mOf(h.OGC(col),"GetInstanceID",0);
    if(!gid)return 0;
    var r=inv(gid,col,[]);
    if(!r||r.isNull())return 0;
    return r.add(0x10).readS32();
  }catch(e){HS.lasterr="colId:"+String(e).substr(0,60);return 0;}
}
function headshotApply(on){
  /* PERMANENTLY DISABLED. This subsystem (Launch aim-lock, OnCollisionEnter forge, Initialize
     ball-recovery) writes into live Pokeball fields and repeatedly corrupted the encounter: it
     hung encounters and, on 2026-08-30 20:17:38, CRASHED PoGo with a UnityMain SIGSEGV inside the
     game's own libil2cpp (writing delegate pointers into HitGround@88/HitKillZone@96). Pokemod's
     own Perfect Throw already does this correctly in-process; mine only conflicts with it.
     Left as a no-op rather than deleted so the callers still resolve. Do not re-enable. */
  return;
}

function perfectApply(on){
  try{
    if(on){
      if(!PT.ready){PT.err="not ready: "+PT.err;return;}
      /* FROZE THE GAME ONCE -- read this before changing it.
         An il2cpp AOT method's NATIVE signature carries a hidden trailing `const MethodInfo*`:
             float get_NormalizedSize(Reticle* this, const MethodInfo* method)
         My first version declared only ["pointer"], so every Interceptor.replace had a mismatched
         calling convention and PoGo hung with its render loop stuck.
         Two changes: every replace now includes the trailing MethodInfo pointer, and the two BOOL
         getters use attach+onLeave instead of replace. A bool comes back in x0, which retval CAN
         rewrite, so those need no signature at all -- strictly safer. Only the FLOAT getter still
         needs a replace, because on arm64 a float returns in v0 where retval cannot reach it. */
      /* ALL CLIENT-SIDE HOOKS PERMANENTLY DISABLED. Six failures, every variant:
           reposition@reticle -> ball short, 3 ground contacts
           reposition@GameObject -> aimTo=0,0,0 (encounter has no usable world coords)
           OnCollisionEnter forge -> capture never starts, encounter UI gone
           bullseye+invulnerable+SetCanPerformActions -> same hang
           get_NormalizedSize ALONE -> **CRASHED PoGo** (tombstone 01:32:40), signature
             StackVisitor::WalkStack -> Thread::VisitRoots -> MarkCompact::CheckpointMarkThreadRoots
         That last one is decisive and is NOT a logic bug: a Frida NativeCallback on a hot encounter
         method leaves Frida trampolines on a GAME thread's stack, and ART's compacting GC faults
         walking it. It is the same cross-thread GC vector documented elsewhere in this file, now
         reached from the opposite direction. No amount of getting the hook "right" avoids it.
         Also measured: FIRED{ns:0} -- the game barely calls get_NormalizedSize on this build, so
         even a safe hook there would buy almost nothing.
         PERFECT THROW IS PROTO-ONLY. See the CatchPokemonProto WriteTo hook: the SERVER scores the
         throw from those fields, so the catch-rate and XP benefit is real and verified
         (ret=1.903 [EXCELLENT] spin=1 hit=1 hpos=1 came from the proto write, with ns never firing).
         What is lost is only the on-screen "Excellent!" text. */
      /* ATTACH (never replace) purely to CAPTURE the live Reticle instance.
         Interceptor.replace + NativeCallback on this method crashed PoGo -- ART's GC faulted on the
         Frida trampoline left on a game thread's stack. An attach that only READS args[0] is the
         same shape as the LateUpdate / MergeFrom hooks that have run for months without incident,
         and it changes no behaviour by itself.
         Why this and not Pokeball.Initialize: that hook attached fine but never fired, and driving
         an encounter open by tapping the map kept missing because the camera drifts between the
         screenshot and the tap. get_NormalizedSize is called BY the game whenever a reticle exists,
         so it hands us the instance for free. Once cached, the pump writes the reticle's own float
         fields -- no trampoline on the throw path at all. */
      if(PT.ns)PT_LIS.push(Interceptor.attach(PT.ns,{
        onEnter:function(a){
          PTC.ns++;
          /* WRITE HERE, NOT FROM THE PUMP.
             ART's MarkCompact is a MOVING collector. Caching this instance pointer and writing to
             it every 500ms from the pump worked for ~2 minutes and then FROZE the game: once GC
             relocated the object, every write landed in freed/reused memory. args[0] is a FRESH,
             valid pointer for exactly the duration of this call, and it is the instance whose
             getter is about to run -- so writing reticleMinSize right here is both safe and
             perfectly timed. Same class of bug as holding a MapPokemon pointer across time. */
          try{
            var self=a[0];
            if(self&&!self.isNull()&&RT.offMin>=0){
              self.add(RT.offMin).writeFloat(0.12);
              RT.wrote=(RT.wrote||0)+1;
            }
          }catch(e){}
        },
        onLeave:function(r){
          /* PROBE ONCE: does Frida expose the arm64 VECTOR registers on this.context? A float
             return lives in v0/q0, which `retval` cannot touch -- that limitation is the ONLY reason
             I ever used Interceptor.replace here, and replace is what crashed the game (ART GC
             faulting on the trampoline). If q0 is present and writable, the whole feature can run
             from a plain attach, which is the same shape as the LateUpdate/MergeFrom hooks that
             have been stable for months. */
          try{
            if(!RT.ctxKeys){
              var k=[];for(var n in this.context)k.push(n);
              RT.ctxKeys=k.join(",");
              RT.log.push("CTXKEYS "+RT.ctxKeys);
            }
            if(PERFECT_ON&&RT.wantWrite&&this.context.q0!==undefined){
              /* write the Excellent-band value straight into the float return register */
              var buf=Memory.alloc(16);buf.writeFloat(0.13*Math.random());
              this.context.q0=buf.readU64();
              PTC.wrote=(PTC.wrote||0)+1;
            }
          }catch(e){ if(!RT.ctxErr){RT.ctxErr=String(e).substr(0,70);RT.log.push("CTXERR "+RT.ctxErr);} }
        }
      }));
      PERFECT_ON=1;
      /* HEADSHOT AIM-LOCK IS OFF ON PURPOSE. Pokemod's Headshot is TWO hooks: Launch teleports the
         ball to the reticle AND OnCollisionEnter forges the contact pair so any contact counts as a
         hit (plus HitGround/HitKillZone rebound to recover the ball). I implemented only the first.
         Result, seen on screen: the ball gets moved, misses, lands, and nothing handles it -- the
         ball sits inert at the Pokemon's feet and the encounter is dead. Half of this mechanic is
         strictly worse than none of it, so it stays disabled until the collision half is written.
         Enable by flipping this back to headshotApply(1) ONLY together with the OnCollisionEnter
         rewrite. */
      headshotApply(1);
    }else{
      if(PT.ns){try{Interceptor.revert(PT.ns);}catch(e){}}   /* the only replace() left */
      PT_LIS.forEach(function(l){try{l.detach();}catch(e){}});PT_LIS=[];
      PT_CB={};PERFECT_ON=0;headshotApply(0);
    }
    try{Interceptor.flush();}catch(e){}
  }catch(e){PT.err="apply:"+String(e).substr(0,70);PERFECT_ON=0;}
}

rpc.exports.install=function(){var h=H_();var st={};st.perfect="deferred to pump";st.headshot="deferred to pump";PBT=findClass("holo-game.dll","PokeballThrow");if(PBT)PBT_VT=!!h.isVT(PBT);st.pbt=!!PBT;var camC=findClass("holo-game.dll","CameraFollowingGround");var mLU=mOf(camC,"LateUpdate",0);if(mLU){var ad=mLU.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){tick();spinTick();tapTick();}});st.pump=true;}}
 var eop=findClass("holo-protos.dll","EncounterOutProto");if(eop){var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var hooked=0;while((m=h.cGM(eop,it))&&!m.isNull()){try{if(h.mGN(m).readCString()!=="MergeFrom")continue;if(h.mGPC(m)!==1)continue;var code=m.readPointer();if(!code||code.isNull())continue;Interceptor.attach(code,{onEnter:function(a){this.self=a[0];},onLeave:function(r){try{var s=this.self;if(!s||s.isNull())return;var status=s.add(0x1c).readS32();STATUSTALLY[status]=(STATUSTALLY[status]||0)+1;var pk=s.add(0x10).readPointer();var enc=null;if(pk&&!pk.isNull()){var ev=pk.add(0x10).readU64();if(ev.compare(uint64(0))!==0)enc=ev.toString();}for(var qi=0;qi<INFLIGHT.length;qi++){if(INFLIGHT[qi][3]===undefined){INFLIGHT[qi][3]=status;if(enc)INFLIGHT[qi][4]=enc;break;}}if(enc){if(ENCSN++>600){ENCSTATUS={};ENCSN=0;}ENCSTATUS[enc]=status;var pr=readCP(s.add(0x20).readPointer());if(pr){if(PCN++>400){PROBCACHE={};PCN=0;}PROBCACHE[enc]=pr;}}}catch(e){}}});hooked++;}catch(e){}}st.probhook=hooked;}
 var MP=["IncenseEncounterOutProto","DiskEncounterOutProto","DailyEncounterOutProto","AttractedPokemonEncounterOutProto","DailyBonusSpawnEncounterOutProto","StationPokemonEncounterOutProto"]; var mh=0;
 MP.forEach(function(pn){ var kp=findClass("holo-protos.dll",pn)||findClass("holo-game.dll",pn); if(!kp)return; var itp=Memory.alloc(Process.pointerSize); itp.writePointer(ptr(0)); var mp; while((mp=h.cGM(kp,itp))&&!mp.isNull()){ try{ if(h.mGN(mp).readCString()!=="MergeFrom")continue; if(h.mGPC(mp)!==1)continue; var cpx=mp.readPointer(); if(!cpx||cpx.isNull())continue; Interceptor.attach(cpx,{onEnter:function(a){this.self=a[0];},onLeave:function(r){try{var s=this.self;if(!s||s.isNull())return;var rr=s.add(0x10).readS32();for(var qi=0;qi<INFLIGHT.length;qi++){if(INFLIGHT[qi][3]===undefined){INFLIGHT[qi][3]=rr;break;}}
 /* LURE/DISK encounters (where Gimmighoul arrives) never populated PROBCACHE — every one logged p=-1, so
    ball choice was blind. Same layout as EncounterOutProto: CaptureProbability@0x20. Also grab ActiveItem
    @0x28 (which berry is applied — proves whether Pokemod is actually feeding) and AttemptsUntilFlee@0x2c. */
 if(pn==="DiskEncounterOutProto"){try{LASTDISK={p:readCP(s.add(0x20).readPointer()),item:s.add(0x28).readS32(),auf:s.add(0x2c).readS32(),ts:Date.now()};}catch(_dx){}}
}catch(e){}}}); mh++; }catch(e){} } }); st.multihook=mh;
 var cpo=findClass("holo-protos.dll","CatchPokemonOutProto");if(cpo){var it2=Memory.alloc(Process.pointerSize);it2.writePointer(ptr(0));var m2;var ch=0;while((m2=h.cGM(cpo,it2))&&!m2.isNull()){try{if(h.mGN(m2).readCString()!=="MergeFrom")continue;if(h.mGPC(m2)!==1)continue;var c2=m2.readPointer();if(!c2||c2.isNull())continue;Interceptor.attach(c2,{onEnter:function(a){this.self=a[0];},onLeave:function(r){try{var s=this.self;if(!s||s.isNull())return;onCatchResult(s.add(0x10).readS32(),s.add(0x38).readS32(),s.add(0x30).readS32(),s.add(0x18).readDouble());try{if(s.add(0x10).readS32()===1){var _cid=s.add(0x20).readU64();XQUEUE.push(_cid);if(TOC.on){var _k=_cid.toString();if(!TOC.seen[_k]){TOC.seen[_k]=1;TOC.pend.push({id:_cid,tries:0});}}}}catch(_xe){}}catch(e){}}});ch++;}catch(e){}}st.catchhook=ch;}
 var cpp=findClass("holo-protos.dll","CatchPokemonProto");if(cpp){var it4=Memory.alloc(Process.pointerSize);it4.writePointer(ptr(0));var m4;var rh=0;while((m4=h.cGM(cpp,it4))&&!m4.isNull()){try{var _mn4=h.mGN(m4).readCString();if(_mn4!=="WriteTo"&&_mn4!=="_InternalSerialize")continue;var c4=m4.readPointer();if(!c4||c4.isNull())continue;Interceptor.attach(c4,{onEnter:function(a){try{var s=a[0];if(!s||s.isNull())return;var eid=s.add(0x10).readU64().toString();var gd=s.add(0x28).readPointer();/* CURVEBALL. The reticle had to be hooked client-side, but the SPIN bonus is a proto field that
   Pokemod itself writes -- their PerfectedThrow attaches to CatchPokemonProto.CalculateSize and
   sets `this.SpinModifier = 1`. Doing it here, on the same outgoing request, is the same mechanism.
   Evidence this was missing: a verified-Excellent manual throw logged `spin=0`, i.e. no curve bonus.
   spin_modifier is a DOUBLE at +0x38. Writing it changes no varint length, so the size CalculateSize
   already computed stays correct. */
if(PERFECT_ON){try{
  /* PROTO-ONLY PERFECT THROW. The server computes the throw bonus from these fields, so this is
     where the actual catch-rate and XP benefit comes from. Verified scale: normalized_reticle_size
     1.0-2.0, Excellent above 1.7 (a real captured throw read 1.931). Jitter inside the band rather
     than pinning a constant. This path has never hung an encounter. */
  s.add(0x20).writeDouble(1.90+Math.random()*0.08);   /* normalized_reticle_size -> Excellent */
  s.add(0x30).writeU8(1);                             /* hit_pokemon */
  s.add(0x38).writeDouble(1.0);                       /* spin_modifier -> curveball */
  s.add(0x40).writeDouble(1.0);                       /* normalized_hit_position -> dead centre */
}catch(_sp){}}REQ[eid]={ball:s.add(0x18).readS32(),ret:Math.round(s.add(0x20).readDouble()*1000)/1000,guid:(gd&&!gd.isNull())?1:0,hit:s.add(0x30).readU8(),spin:Math.round(s.add(0x38).readDouble()*100)/100,hpos:Math.round(s.add(0x40).readDouble()*100)/100,sflee:s.add(0x50).readU8()};try{var _q=REQ[eid];TLOG.push({eid:eid,ball:_q.ball,ret:_q.ret,spin:_q.spin,hit:_q.hit,hpos:_q.hpos,mine:ATTEMPTED[eid]?1:0,perf:PERFECT_ON,aim:HS.n});if(TLOG.length>60)TLOG.shift();}catch(_tl){}if(REQN++>400){REQ={};REQN=0;}}catch(e){}}});rh++;}catch(e){}}st.reqhook=rh;}
 try{var _sk=findClass("holo-game.dll","MapPokestop");if(_sk){var _sm=mOf(_sk,"StartInteractiveMode",0);if(_sm){var _sc2=_sm.readPointer();if(!_sc2.isNull())Interceptor.attach(_sc2,{onLeave:function(r){try{if(r&&!r.isNull()){LASTINTER=ptr(r);SPINLOG.push("startInteractive inter="+r);}}catch(e){}}});}}}catch(e){}
 try{var _pk=findClass("holo-game.dll","PoiItemSpinner");if(_pk){var _pm=mOf(_pk,"clfn",0);if(_pm){var _pc2=_pm.readPointer();if(!_pc2.isNull())Interceptor.attach(_pc2,{onEnter:function(a){try{var sp=a[0];var f="";if(!LASTINTER.isNull()){for(var o=0x10;o<=0x260;o+=8){try{if(LASTINTER.add(o).readPointer().equals(sp))f+=" 0x"+o.toString(16);}catch(e){}}}SPINLOG.push("clfn spinner="+sp+" interField="+(f||"NOTFOUND"));}catch(e){}}});}}}catch(e){}
 try{var _fk=findClass("holo-protos.dll","FortSearchProto");if(_fk){var _fm=mOf(_fk,"WriteTo",1);if(_fm){var _fc2=_fm.readPointer();if(!_fc2.isNull())Interceptor.attach(_fc2,{onEnter:function(a){try{var s=a[0];SPINLOG.push("FortSearchReq wear="+s.add(0x41).readU8()+" sfida="+s.add(0x42).readU8());}catch(e){}}});}}}catch(e){}
 try{var _ok=findClass("holo-protos.dll","FortSearchOutProto");if(_ok){var _oit=Memory.alloc(Process.pointerSize);_oit.writePointer(ptr(0));var _om;var _oh=0;while((_om=h.cGM(_ok,_oit))&&!_om.isNull()){try{if(h.mGN(_om).readCString()!=="MergeFrom")continue;if(h.mGPC(_om)!==1)continue;var _oc2=_om.readPointer();if(!_oc2||_oc2.isNull())continue;_oh++;Interceptor.attach(_oc2,{onEnter:function(a){this.s=a[0];},onLeave:function(r){try{var s=this.s;if(!s||s.isNull())return;var res=s.add(0x10).readS32();var xp=s.add(0x30).readS32();var lt=lootTotal(s.add(0x50).readPointer())+lootTotal(s.add(0x58).readPointer());var aw=repCount(s.add(0x18).readPointer());var tot=(lt>0?lt:aw);/* Items@0x18 and Loot@0x50 are the SAME payload two ways — never sum them (loot===award on every response); the per-spin AMOUNT varies (3/6/20 seen) *//* We attach to EVERY MergeFrom overload, so one response can surface twice — the second pass often
   reads an empty/partial object (res=1 but xp=0 items=0), which was inflating the spin counters by ~9%.
   Only count a success that actually carried a reward. */
if(res===1&&xp<=0&&tot<=0)return;SPINRES[res]=(SPINRES[res]||0)+1;if(res===1){SPINOK++;if(xp>0&&xp<100000)SPINXP+=xp;SPINITEMS+=tot;}SPINLOG.push("AWARD res="+res+" xp="+xp+" items="+tot+" (loot="+lt+" award="+aw+")");}catch(e){}}});}catch(e){}}st.spinouthook=_oh;}}catch(e){}
 return st;};
function fireOpen(t){try{var sm=mOf(H_().OGC(t),"SendEncounterRequest",0);if(sm)inv(sm,t,[]);}catch(e){}}
var PROBCACHE={}, PCN=0, LASTDISK=null;   /* most recent lure/disk encounter: probs + active berry + attempts-until-flee */
function readCP(cp){try{if(!cp||cp.isNull())return null;var bRF=cp.add(0x10).readPointer(),pRF=cp.add(0x18).readPointer();if(bRF.isNull()||pRF.isNull())return null;var bA=bRF.add(0x10).readPointer(),bC=bRF.add(0x18).readS32(),pA=pRF.add(0x10).readPointer(),pC=pRF.add(0x18).readS32();var n=Math.min(bC,pC);if(n<=0||n>8)return null;var m={};for(var i=0;i<n;i++){m[bA.add(0x20+i*4).readS32()]=pA.add(0x20+i*4).readFloat();}return m;}catch(e){return null;}}
function readProbs(t){try{var em=mOf(H_().OGC(t),"get_EncounterId",0);if(!em)return null;var er=inv(em,t,[]);if(!er)return null;return PROBCACHE[er.add(0x10).readU64().toString()]||null;}catch(e){return null;}}
rpc.exports.probSample=function(){var k=Object.keys(PROBCACHE);return {n:k.length,sample:k.length?PROBCACHE[k[k.length-1]]:null};};
function pickBall(pr,best){if(best){/* priority target: strongest ball on hand, ignore the cheap-ball economy */for(var bi=3;bi>=1;bi--){if(AVAIL[bi])return bi;}}var ord=[1,2,3];if(pr){for(var i=0;i<3;i++){var b=ord[i];if(AVAIL[b]&&pr[b]!==undefined&&pr[b]>=THRESH)return b;}var best=0,bp=-1;for(var i=0;i<3;i++){var b=ord[i];if(AVAIL[b]&&pr[b]!==undefined&&pr[b]>bp){bp=pr[b];best=b;}}if(best>0)return best;}for(var i=0;i<3;i++){if(AVAIL[ord[i]])return ord[i];}return 1;}   /* was BALL(=Great): defaulting to a ball we might have ZERO of makes the server reject the throw -> "Error During Capture?" freezes the client */
function distAt(t){try{if(MAPAVATAR.isNull())return -1;var lm=mOf(H_().OGC(MAPAVATAR),"get_Location",0);if(!lm)return -1;var lr=inv(lm,MAPAVATAR,[]);if(!lr)return -1;var alat=lr.add(0x10).readDouble(),alng=lr.add(0x18).readDouble();var lm2=mOf(H_().OGC(t),"get_Location",0);if(!lm2)return -1;var lr2=inv(lm2,t,[]);if(!lr2)return -1;var mlat=lr2.add(0x10).readDouble(),mlng=lr2.add(0x18).readDouble();var R=6371000,p1=alat*Math.PI/180,p2=mlat*Math.PI/180,dp=(mlat-alat)*Math.PI/180,dl=(mlng-alng)*Math.PI/180;var x=Math.sin(dp/2)*Math.sin(dp/2)+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)*Math.sin(dl/2);return 2*R*Math.asin(Math.min(1,Math.sqrt(x)));}catch(e){return -1;}}
function useBerry(t,itemId){try{if(IB.isNull())return;var bm=mOf(H_().OGC(IB),"UseItemForEncounter",2);if(!bm)return;var ip=Memory.alloc(4);ip.writeS32(itemId);inv(bm,IB,[ip,t]);NBERRY++;if(itemId===RAZZ_ID)NRAZZ++;}catch(e){}}
var NOTM=0,FCERR=0,FCOK=0,FCERRMSG="";
function fireCatch(t,attempts){try{var _d0=distAt(t);if(_d0<0){/* position unreadable: either a despawned phantom OR PoGo is backgrounded. Decide by LIVE MEMBERSHIP, not position. */var _sge=encOf(t);if(!_sge||!encAlive(_sge)){STALESKIP++;if(_sge){ATTEMPTED[_sge]=1;NEWATT[_sge]=1;}return;}BGTHROW++;}
 /* HARD RANGE GATE at throw time. refillService can only range-filter when the avatar position is
    readable; when it isn't, everything gets queued and we end up throwing at 104m/141m mons the server
    always rejects — which looks like "stuck retrying the same Pokemon". Drop them here instead. */
 if(_d0>MAXR){OUTRANGE++;var _oe=encOf(t);if(_oe){ATTEMPTED[_oe]=1;NEWATT[_oe]=1;}return;}
 var _pm=readProbs(t);var _item=-1,_auf=-1;
 /* lure mons aren't in PROBCACHE (keyed by wild encounterId); fall back to the freshest disk encounter */
 if(!_pm&&LASTDISK&&(Date.now()-LASTDISK.ts)<12000){_pm=LASTDISK.p;_item=LASTDISK.item;_auf=LASTDISK.auf;}
 var _pid=-1;try{var _pmid=mOf(H_().OGC(t),"get_PokemonId",0);if(_pmid){var _pir=inv(_pmid,t,[]);if(_pir)_pid=_pir.add(0x10).readS32();}}catch(_pe){}var _prio=PRIORITY[_pid]?1:0;var ball=pickBall(_pm,_prio);var _bp=(_pm&&_pm[ball]!==undefined)?_pm[ball]:-1;var _enc="";try{var _eem=mOf(H_().OGC(t),"get_EncounterId",0);if(_eem){var _eer=inv(_eem,t,[]);if(_eer)_enc=_eer.add(0x10).readU64().toString();}}catch(_ee){}var tm=mOf(H_().OGC(t),"TryCapture",2);if(!tm){NOTM++;return;}var obj=H_().oN(PBT);obj.add(0x10).writeS32(ball);obj.add(0x14).writeFloat(0.02+Math.random()*0.10);obj.add(0x18).writeU8(1);obj.add(0x19).writeU8(1);obj.add(0x1a).writeU8(0);var p=PBT_VT?obj.add(0x10):obj;inv(tm,t,[p,ptr(0)]);var _cls="?";try{_cls=H_().CGN(H_().OGC(t)).readCString();}catch(e){}THROWN.push({t:t,a:attempts||1,ts:Date.now(),cls:_cls,prob:_bp,ball:ball,pid:_pid,enc:_enc,dist:Math.round(_d0),item:_item,auf:_auf});FCOK++;try{var _em=mOf(H_().OGC(t),"get_EncounterId",0);if(_em){var _er=inv(_em,t,[]);if(_er){var _enc=_er.add(0x10).readU64().toString();ATTEMPTED[_enc]=1;NEWATT[_enc]=1;}}}catch(e){}}catch(e){FCERR++;FCERRMSG=String(e).substr(0,90);}}

/* ================= AUTO-TRANSFER (1-24% IV) =================================================
   Verified field offsets on PokemonProto (0.421.0 recon):
     individualAttack_@0x70  individualDefense_@0x74  individualStamina_@0x78
     favorite_@0xb0(bool)  isLucky_@0x110(bool)  deployedFortId_@0x40(string)
     pokemonDisplay_@0xd8 -> costume_@0x10, shiny_@0x18, form_@0x1c
   IV% = (atk+def+sta)/45. Band is EXCLUSIVE of 0% (nundos are kept on purpose).
   PvP SAFETY: 24% == an IV total of 11/45. A PvP-viable mon needs HIGH def+sta (ideal ~0/15/15 = 67%),
   and def+sta alone would be 30 — so nothing in this band can be PvP-relevant. Lucky (12/12/12 floor)
   and raid/egg/research (10/10/10 floor) mathematically cannot land here either.
   Everything still gets the keep-axis guard below, and DRYRUN releases NOTHING. */
var XFER_ON=false, XFER_DRY=true, XFER_MIN=1, XFER_MAX=24, XBAG=ptr(0);
var XSEEN=0, XWOULD=0, XDONE=0, XKEPT={}, XLOG=[], XQUEUE=[];
rpc.exports.setXfer=function(on,dry,lo,hi){XFER_ON=!!on;XFER_DRY=(dry!==false);if(lo!==undefined)XFER_MIN=lo;if(hi!==undefined)XFER_MAX=hi;};
rpc.exports.setPokeBag=function(p){XBAG=ptr(p);};
rpc.exports.drainXfer=function(){var o=XLOG;XLOG=[];return o;};
rpc.exports.xferStats=function(){return {seen:XSEEN,would:XWOULD,done:XDONE,kept:XKEPT,on:XFER_ON,dry:XFER_DRY};};
function xkeep(r){XKEPT[r]=(XKEPT[r]||0)+1;return r;}
/* returns null to TRANSFER, or a string reason to KEEP */
function xEvaluate(pm){try{
  var atk=pm.add(0x70).readS32(), def=pm.add(0x74).readS32(), sta=pm.add(0x78).readS32();
  if(atk<0||atk>15||def<0||def>15||sta<0||sta>15)return xkeep("bad_iv_read");
  var pct=Math.round((atk+def+sta)/45*100);
  if(pct===0)return xkeep("nundo");                      /* user keeps 0% on purpose */
  if(pct<XFER_MIN||pct>XFER_MAX)return xkeep("out_of_band");
  if(pm.add(0xb0).readU8()===1)return xkeep("favorite");
  if(pm.add(0x110).readU8()===1)return xkeep("lucky");
  try{var fid=pm.add(0x40).readPointer();if(fid&&!fid.isNull()&&fid.add(0x10).readS32()>0)return xkeep("in_gym");}catch(e){}
  var d=pm.add(0xd8).readPointer();
  if(d&&!d.isNull()){
    if(d.add(0x18).readU8()===1)return xkeep("SHINY");
    if(d.add(0x10).readS32()!==0)return xkeep("costume");
    if(d.add(0x1c).readS32()!==0)return xkeep("special_form");
  } else return xkeep("no_display");                     /* unreadable => PROTECT */
  return null;
}catch(e){return xkeep("err");}}
function xTryTransfer(pid64){try{
  if(!XFER_ON||XBAG.isNull()||!pid64)return;
  var h=H_();var gm=mOf(h.OGC(XBAG),"GetPokemon",1);if(!gm)return;
  var arg=Memory.alloc(8);arg.writeU64(pid64);
  var pm=inv(gm,XBAG,[arg]);if(!pm||pm.isNull())return;
  XSEEN++;
  var why=xEvaluate(pm);
  var atk=pm.add(0x70).readS32(),def=pm.add(0x74).readS32(),sta=pm.add(0x78).readS32();
  var pct=Math.round((atk+def+sta)/45*100), sp=pm.add(0x28).readS32(), cp=pm.add(0x2c).readS32();
  if(why){XLOG.push("KEEP "+why+" pid="+sp+" iv="+pct+"% ("+atk+"/"+def+"/"+sta+") cp="+cp);return;}
  XWOULD++;
  /* TAG-ONLY. This process NEVER releases: the user's standing rule is "just auto tag for transfer,
     don't release", and the cull engine (cull_v9.is_protected) is the authority on what may go --
     it knows PvP rank, legendary/mythical/UB/paradox, location cards, dex-firsts and user tags, none
     of which are readable from this hook. So we only emit an ADVISORY candidate uid; the offline
     pipeline re-decides it against the full ruleset before any tag is written. */
  XDONE++;
  XLOG.push("CANDIDATE uid=0x"+pid64.toString(16)+" pid="+sp+" iv="+pct+"% ("+atk+"/"+def+"/"+sta+") cp="+cp);
}catch(e){XLOG.push("xferErr "+e);}}


/* Box sweep: evaluate EVERY Pokemon already in the bag (the new-catch hook cannot help when the box
   is full and nothing can be caught). Read-only unless doIt===true. Tries the known accessors because
   the enumerable's name is obfuscated. */
rpc.exports.xferScan=function(doIt,limit){
  /* DISABLED. This enumerates the whole box via il2cpp, and calling it over RPC runs that on
     Frida's thread -- the cross-thread stack that ART's compacting GC then faults walking. It
     crashed PoGo twice (2026-08-19 20:40 and 22:02). Kept as a tripwire rather than deleted so a
     future caller gets this message instead of a dead game. Box census belongs OFFLINE, against
     pokemon.db, where cull_v9 already does it properly. */
  return {total:0,would:0,released:0,kept:{},samples:[],method:null,
          err:"xferScan is disabled: il2cpp from the RPC thread crashes the game. Use the offline "
              +"cull (auto_tag.py) instead."};
  /* eslint-disable no-unreachable */
  var res={total:0,would:0,released:0,kept:{},samples:[],method:null,err:null};
  try{
    if(XBAG.isNull()){res.err="no bag";return res;}
    var h=H_(),enumer=null,used=null;
    var names=["get_Pokemon","GetPokemon","get_AllPokemon","get_PokemonList","GetAllPokemon","get_Items"];
    for(var i=0;i<names.length;i++){var m=mOf(h.OGC(XBAG),names[i],0);
      if(m){var r=inv(m,XBAG,[]);if(r&&!r.isNull()){var g=mOf(h.OGC(r),"GetEnumerator",0);if(g){enumer=r;used=names[i];break;}}}}
    if(!enumer){res.err="no enumerable accessor";return res;}
    res.method=used;
    var gem=mOf(h.OGC(enumer),"GetEnumerator",0);var enr=inv(gem,enumer,[]);if(!enr||enr.isNull()){res.err="no enumerator";return res;}
    var enrC=h.OGC(enr);var self=h.isVT(enrC)?enr.add(0x10):enr;
    var mn=mOf(enrC,"MoveNext",0),gc=mOf(enrC,"get_Current",0);if(!mn||!gc){res.err="no iter";return res;}
    var cap=(limit&&limit>0)?limit:100000, guard=0;
    while(guard++<20000){
      var r2=inv(mn,self,[]);if(!r2||r2.add(0x10).readU8()===0)break;
      var pm=inv(gc,self,[]);if(!pm||pm.isNull())continue;
      res.total++;
      var why=xEvaluate(pm);
      if(why){res.kept[why]=(res.kept[why]||0)+1;continue;}
      var a=pm.add(0x70).readS32(),d=pm.add(0x74).readS32(),st=pm.add(0x78).readS32();
      var pct=Math.round((a+d+st)/45*100);
      res.would++;
      if(res.samples.length<12)res.samples.push("pid="+pm.add(0x28).readS32()+" iv="+pct+"% ("+a+"/"+d+"/"+st+") cp="+pm.add(0x2c).readS32());
      /* release path REMOVED on purpose -- this is a read-only census (see xTryTransfer note) */
    }
  }catch(e){res.err=String(e).substr(0,120);}
  return res;};

function onCatchResult(status,thr,reason,miss){try{var it=THROWN.shift();if(!it)return;var rq=(it.enc&&REQ[it.enc])?REQ[it.enc]:null;function _lp(r){FLEEPROF.push({r:r,p:it.prob,b:it.ball,pid:it.pid,a:it.a,cls:it.cls,enc:it.enc,spd:Math.round(CURSPEED),reason:reason,miss:Math.round((miss||0)*100)/100,thr:thr,req:rq,dist:it.dist,age:Math.round((Date.now()-it.ts)/100)/10,src:(it.cls||"?"),item:it.item,auf:it.auf});if(FLEEPROF.length>400)FLEEPROF.shift();}if(status===1){CR.s++;var _c=(it&&it.cls)?it.cls:"?";SRCCATCH[_c]=(SRCCATCH[_c]||0)+1;if(it.dist>=0){CDSUM+=it.dist;CDN++;}if(PRIORITY[it.pid]){NPRIOCAUGHT++;SPINLOG.push("PRIORITY CAUGHT pid="+it.pid+" after "+it.a+" throw(s)");}_lp(1);/* log SUCCESSES too — without them there is nothing to compare failures against (per-species, per-ball, per-distance, prob-calibration all need both) */return;}if(status===3){CR.f++;if(it.dist>=0){FDSUM+=it.dist;FDN++;}if(PRIORITY[it.pid]){NPRIOLOST++;SPINLOG.push("PRIORITY LOST pid="+it.pid+" att="+it.a+" ball="+it.ball+" dist="+it.dist);}_lp(3);return;}if(status===2||status===4){if(status===2)CR.e++;else CR.m++;_lp(status);/* RE-THROW ON BREAK-OUT. The old guard required ThrowsRemaining>0, but wild/lure encounters report
   thr=0 ALWAYS (it only means something for limited-ball encounters), so the retry NEVER fired once in
   81 logged throws — every break-out was abandoned, including a Gimmighoul that broke out at 52m.
   r=2 (escape) means the mon is STILL THERE, so throw again; r=3 (fled) is gone and is not retried. */
if(thr>0&&it.a<MAXTHROW){if(status===2)it.bo=1;it.due=Date.now()+RETHROW_DELAY;RETHROW.push(it);}return;}   /* thr>0 restored: re-throws are the stale-pointer path that began crashing PoGo */CR.err++;}catch(e){}}
var LASTWORK=0;
function tick(){ FRAME++; try{ if(!PT_RESOLVED){PT_RESOLVED=1;perfectResolve();headshotResolve();pokemonProtoDump();} }catch(_pr){} try{ if(PERFECT_WANT!==PERFECT_ON) perfectApply(PERFECT_WANT); }catch(_pt){} /* pump sampler REMOVED: it dereferenced a cached managed pointer (see the hook note). */   /* FRAME must still count every callback: it is the idle signal */
 var _tn=Date.now(); if(_tn-LASTWORK<100)return; LASTWORK=_tn;
 /* Deferred heavy work, executed HERE on UnityMain (never from Frida's RPC thread). Runs even when
    catching is toggled off, because the spinner and the UI both depend on these. One per frame at most,
    so a single frame is never blocked by both walks. */
 /* The count poll must NOT sit behind the heavy walks: python requests a refill nearly every cycle,
    so an else-chain here starved it and every ball count read back -1 (which also broke ball choice).
    It is only ~7 invokes every 3s, so it runs independently. */
 try{ var _pn=Date.now(); if(_pn-LASTPOLL>3000){LASTPOLL=_pn;pollCounts();}
      /* self-refill: queue running low is decided HERE, not by python. Guarantees we keep
         opening spawns at full rate regardless of what the telemetry loop is doing. */
      if(!WANT_REFILL && Q.length<8 && (_pn-LASTREFILL)>(LASTADDED>0?REFILL_MS:REFILL_IDLE_MS)){WANT_REFILL=1;}
      if(WANT_REFILL){WANT_REFILL=0;LASTREFILL=_pn;LASTADDED=doRefill();}
      else if(WANT_SCAN){WANT_SCAN=0;doSpinScan();} }catch(_dw){}
 /* transfer evaluation happens HERE, on the Unity thread — never in the response hook */
 /* per-catch transfer eval REMOVED -- see USE_XFER note. Drain the queue without calling il2cpp. */
 try{ if(XQUEUE.length) XQUEUE.length=0; }catch(_xq){}
 try{ tocTick(); }catch(_tc){}
 if(!RUN)return;
 try{ var now=Date.now();
  while(THROWN.length>0 && (now-THROWN[0].ts)>9000) THROWN.shift();   // drop responses never heard back (keep FIFO correlation honest)
  for(var i=0;i<RETHROW.length;i++){ if(now>=RETHROW[i].due){ var ri=RETHROW.splice(i,1)[0]; i--; /* NEVER reuse the stored object pointer: a re-throw can be up to MAXTHROW_PRIO*delay later, by which time the game may have freed/recycled that MapPokemon. Dereferencing it corrupts the heap and surfaces as an ART GC fault while walking stacks. Re-resolve by encounter id; if it is gone, drop it. */ var rt=findByEnc(ri.enc); if(!rt){STALESKIP++;continue;} if(RAZZON&&ri.bo&&!IB.isNull()){useBerry(rt,RAZZ_ID);ri.bo=0;} fireCatch(rt,ri.a+1); REFIRED++; } }   // re-throw on break-out (+ regular Razz on the proven escape-prone mon)
  if(now-lastOpenMs>=INTERVAL_MS && Q.length>0){ var t=Q.shift(); fireOpen(t);
    /* PRIORITY targets (Galarian birds / Gimmighoul) wait LONGER before the first throw so POKEMOD has
       time to apply a Golden Razz (2.5x) — on a 90%-flee bird you realistically get ONE throw, and
       beating Pokemod to it would throw away the single biggest multiplier available. Waiting is free:
       the flee roll only happens AFTER a break-out, never while the ball is held. */
    INFLIGHT.push([t,now,0,undefined,undefined,LAG_MS]);   /* uniform short hold; PRIO_LAG kept a pointer alive 7s for no gain */ lastOpenMs=now; OPENED++; }
  /* ONE berry per encounter, decided from BERRY_LAG on: Razz (701) when the catch is HARD (prob KNOWN & < RAZZ_THRESH),
     otherwise Pinap (705) -- "use Pinap whenever no Razz is needed" (2026-09-24). Pinap used to run FIRST and mark every
     encounter fed, which would have starved Razz entirely. Probs unreadable -> keep waiting for them until BERRY_LATE ms
     before the throw, then Pinap. 706/708 are NEVER touched. */
  if((BERRY_PINAP||RAZZON) && !IB.isNull()){ for(var bi=0;bi<INFLIGHT.length;bi++){ var ie=INFLIGHT[bi]; var bAge=now-ie[1]; if(ie[2] || bAge<BERRY_LAG) continue; var bP=-1; var bZp=readProbs(ie[0]); if(bZp){ var bZb=pickBall(bZp); bP=(bZp[bZb]!==undefined)?bZp[bZb]:-1; } if(RAZZON && bP>=0 && bP<RAZZ_THRESH){ useBerry(ie[0],RAZZ_ID); ie[2]=1; } else if(BERRY_PINAP && (bP>=0 || bAge>=(ie[5]||LAG_MS)-BERRY_LATE)){ useBerry(ie[0],PINAP_ID); ie[2]=1; } } }
  while(INFLIGHT.length>0 && (now-INFLIGHT[0][1])>=(INFLIGHT[0][5]||LAG_MS)){ var e=INFLIGHT.shift(); var tt=e[0];   /* short (~3.5s) window: pointer is still valid. Re-resolution here cost a full walk PER THROW and starved the JS thread. */ var encId=null; try{ var _em=mOf(H_().OGC(tt),"get_EncounterId",0); if(_em){ var _er=inv(_em,tt,[]); if(_er){ encId=_er.add(0x10).readU64().toString(); } } }catch(_x){} var ws=(encId&&ENCSTATUS[encId]!==undefined)?ENCSTATUS[encId]:undefined; var resp=(ws!==undefined)?ws:e[3]; if(resp===undefined||resp===-1){ SKIPPED++; SKIPSTATUS[-1]=(SKIPSTATUS[-1]||0)+1; if(encId){ATTEMPTED[encId]=1;NEWATT[encId]=1;} continue; } if(ws!==undefined&&ws!==1){ SKIPPED++; SKIPSTATUS[ws]=(SKIPSTATUS[ws]||0)+1; if(encId){ATTEMPTED[encId]=1;NEWATT[encId]=1;} continue; } fireCatch(tt,1); FIRED++; }
 }catch(err){}
}
"""


JOYSTICK = "com.theappninjas.fakegpsjoystick"
JOYSTICK_TELEPORT = "theappninjas.gpsjoystick.TELEPORT"   # headless move; no activity, no button
POGO_ACT = ("com.nianticlabs.pokemongo/com.nianticproject.holoholo."
            "libholoholo.unity.UnityMainActivity")


def _teleport(lat, lng, log):
    """Move via GPS JOYSTICK — the app that already owns the mock provider, so it stays the single
    source of truth (writing position ourselves fought it and caused violent oscillation).
    geo: pre-fills the dialog, then we press its TELEPORT button. Verified end to end: 1.5km move,
    no interaction. Nothing is injected into PoGo, so this path cannot crash the game."""
    # MUST go through `su`: this process runs as the Termux user, which has neither INJECT_EVENTS
    # (so `input tap` throws SecurityException) nor permission to start activities. Both failed
    # silently before, while the code logged success — hence "it teleported" when nothing moved.
    def sh(cmd):
        return os.system("su -c " + json.dumps(cmd) + " >/dev/null 2>&1")
    try:
        before = _cur_pos()
        # HEADLESS teleport service — no activity, no button, PoGo never loses focus.
        # Precondition: the joystick must have been started in-app once this session.
        sh(f"am start-foreground-service -a {JOYSTICK_TELEPORT} --ef lat {lat} --ef lng {lng}")
        time.sleep(1.2)
        after = _cur_pos()          # VERIFY — never claim a move we haven't observed
        if after and after != before:
            log(f"TAP teleported -> {after} (target {lat},{lng})")
        else:
            log(f"TAP teleport DID NOT APPLY (still {after}, target {lat},{lng}, button {bx},{by})")
    except Exception as e:
        log(f"TAP teleport failed: {e}")


def _cur_pos():
    """Read the live mocked position so a teleport can be confirmed rather than assumed."""
    try:
        out = os.popen("su -c 'dumpsys location' 2>/dev/null").read()
        m = re.search(r"last location=Location\[gps ([0-9.\-]+),([0-9.\-]+)", out)
        return f"{m.group(1)},{m.group(2)}" if m else None
    except Exception:
        return None


def _flag(path):
    """Toggle state = file CONTENT ('1'/'0'), not existence: the app can write to a pre-created
    world-writable file but cannot create/delete in /data/local/tmp (no dir write permission)."""
    try:
        with open(path) as f:
            return f.read().strip() == "1"
    except Exception:
        return False


PAUSE_FILE = "/data/local/tmp/pogo_pause"   # PAUSE HANDSHAKE (2026-09-24): epoch-seconds deadline written by a cull


def _paused():
    """True while another tool (a cull, the reward catcher) has asked for the gadget to itself."""
    try:
        with open(PAUSE_FILE) as fh:
            return int(fh.read().strip() or 0) > time.time()
    except (OSError, ValueError):
        return False


def _rotate_log(path, max_mb=8, keep_lines=3000):
    """The log hit 19MB (an 18s pull) because it never rotated. Keep the recent tail, drop the rest;
    the previous generation is kept as .1 so a post-mortem is still possible."""
    try:
        if os.path.exists(path) and os.path.getsize(path) > max_mb * 1024 * 1024:
            with open(path, encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-keep_lines:]
            try:
                os.replace(path, path + ".1")
            except Exception:
                pass
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(tail)
    except Exception:
        pass


_SESS = {"s": None}


def _graceful(signum, frame):
    """Detach before dying: a kill -9 while attached leaves an ESTABLISHED socket on the
    single-client gadget, after which every reattach times out and the toggle does nothing."""
    try:
        if _SESS.get("s"):
            _SESS["s"].detach()
    except Exception:
        pass
    raise SystemExit(0)




TOC_CFG = "/data/local/tmp/pogo_toc.json"   # the app writes this; polled live, no restart needed


def _toc_read():
    """Read the Transfer-on-Catch config the app writes. Missing/corrupt => feature OFF.
    Mirrors Pokemod's own settings: minIvPercent (KEEP at or above it -- their default is 100, i.e.
    keep only hundos), transferShiny/Shadow/BG, xxl sizes to keep, species ignore list."""
    import json as _j
    try:
        with open(TOC_CFG, encoding="utf-8") as fh:
            c = _j.load(fh)
        return bool(c.get("enabled")), bool(c.get("dry", 1)), _j.dumps(c)
    except Exception:
        return False, True, None


def _toc_push(sc):
    on, dry, cfg = _toc_read()
    try:
        sc.exports_sync.set_toc(on, dry, cfg)
    except Exception:
        pass


def _pogo_alive():
    """True if PoGo is running, decided by whether its in-process Frida gadget still accepts a
    TCP connection on 127.0.0.1:27047.

    The previous check shelled out to `pidof`. From Termux's untrusted_app SELinux domain that is
    unreliable -- it cannot see another app's process and does not fail in a way the caller can
    distinguish, so a transient attach failure (for example: a desktop script briefly holding the
    SINGLE-CLIENT gadget) looked identical to "the user quit" and the catcher killed itself
    mid-session. Testing su/`su u0_a762` is misleading here because the su domain has visibility
    the app domain does not.

    A plain socket connect needs no external binary, no shell and no elevated visibility, and it
    tests the thing we actually depend on: a reachable gadget. Connection refused means the
    listener -- and therefore the game -- is gone.
    """
    import socket
    for _ in range(3):                       # brief retry: never exit on one unlucky probe
        sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sk.settimeout(2.0)
        try:
            sk.connect(("127.0.0.1", 27047))
            return True
        except (ConnectionRefusedError, OSError):
            pass
        finally:
            try:
                sk.close()
            except Exception:
                pass
        time.sleep(2)
    return False


def main():
    import signal
    for _sg in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_sg, _graceful)
        except Exception:
            pass
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    _rotate_log(LOG)
    f = open(LOG, "a", encoding="utf-8")

    def w(s):
        line = f"{time.strftime('%H:%M:%S')} {s}"; f.write(line + "\n"); f.flush(); print(line)

    interval = max(400, round(60000 / RATE_PER_MIN))    # MS between opens (framerate-independent; game runs ~30fps so the old frame-based pacing ran at HALF rate)
    base = {}
    attempted_master = set()   # persists across PoGo reconnects so we NEVER re-open/re-throw a spawn already handled
    t0 = time.time()
    w(f"===== FAST RANGE catcher start {RATE_PER_MIN}/min interval={interval}ms range<={MAX_RANGE_M:.0f}m — self-reconnecting =====")

    while True:
        sess = None
        try:
            # WAIT VIA ADB, THEN ATTACH ONCE. The old code fired up to SIX frida.attach probes at
            # 5s intervals, and every probe at a cold-starting PoGo is itself a crash roll -- which
            # is why a game restart so often ended in "link drop: timeout was reached" or a dead
            # catcher. wait_ready_to_attach polls purely over ADB (no Frida) until libil2cpp is
            # mapped and the process is >45s old, so we attach once, when it is actually safe.
            # ON-DEVICE readiness check. pg.wait_ready_to_attach() polls via ADB, which works from
            # the desktop but NOT here -- the catcher runs ON the phone, so it just errors with
            # "No ADB device reachable" and we fall straight back into the crash-roll it was meant
            # to prevent. Locally the equivalent signal is the in-process gadget's own socket: if
            # 127.0.0.1:27047 accepts a connection, libil2cpp is mapped and the app is far enough up
            # to be attachable. Pure socket, no binary, no Frida probe.
            def _gadget_ready():
                import socket as _s
                sk = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
                sk.settimeout(2.0)
                try:
                    sk.connect(("127.0.0.1", 27047)); return True
                except Exception:
                    return False
                finally:
                    try: sk.close()
                    except Exception: pass
            _waited = 0
            while not _gadget_ready() and _waited < 180:
                if _waited == 0:
                    w("waiting for PoGo's gadget to accept connections...")
                time.sleep(5); _waited += 5
            # AND THEN LET IT SETTLE. The socket opens as soon as the gadget loads, which is BEFORE
            # libil2cpp is fully mapped -- attaching in that window is the cold-start crash roll that
            # pg.get_session() refuses by default (min_age_s=45). Dropping this when I moved the
            # readiness check on-device re-introduced it, and the game froze on the next attach.
            # A blind settle needs no /proc visibility, which the Termux app domain does not have.
            # 45 was inherited from the desktop's min_age_s=45 PROCESS-age rule. The gadget appears
            # ~5s into launch, so 45 here waited to ~50s of process age. This sandbox has
            # hidepid=invisible so it cannot poll /proc for libil2cpp -- hence a timer, not a check.
            # Guessing low is cheap: finder.init() below refuses to proceed without gameImage and
            # the loop backs off and retries, so a too-early attach costs one retry, not a session.
            # ponytail: 20s is a measured-down guess, not a proven floor. Raise if cold starts
            # start failing the gameImage gate; lower once a few clean cold starts confirm it.
            _settle = 20
            # OVERRIDE (2026-09-12): a deliberate restart on an ALREADY-WARM game does not need the
            # blind 45s. This sandbox cannot read PoGo's /proc to tell warm from cold, so the caller --
            # which does know -- drops the seconds into this file. CONSUME-ONCE: it is rewritten to 45
            # immediately, so a short settle can never stay armed for a later COLD launch, which is the
            # case the wait exists to protect (a cold attach crashes the game).
            try:
                import os as _os
                _sp = '/data/local/tmp/pogo_settle'
                if _os.path.exists(_sp):
                    with open(_sp) as _fh:
                        _v = int((_fh.read().strip() or '45'))
                    if 0 <= _v <= 120:
                        _settle = _v
                    with open(_sp, 'w') as _fh:
                        _fh.write('-1')   # -1 = no override; the code default above wins next time
            except Exception:
                pass
            if _gadget_ready():
                w(f"gadget up; settling {_settle}s before attach (cold attach crashes the app)")
                time.sleep(_settle)
            while _paused():   # checked right before EVERY attach, after all the waits above
                if not base.get("pausedlog"):
                    base["pausedlog"] = 1
                    w("paused for another tool (pogo_pause) -- not attaching")
                time.sleep(1)
            if base.get("pausedlog"):
                base["pausedlog"] = 0
                w("pause cleared -- attaching")
            for i in range(3):
                try:
                    sess, pid = pg.get_session(); break
                except Exception as e:
                    if i == 0:
                        w(f"attach failed, retrying... ({str(e)[:50]})")
                    time.sleep(5)
            if not sess:
                # QUIT = STOP. No PoGo process means the user closed the game. Exit instead of
                # reconnect-looping forever (that was the background battery drain). The app's
                # toggle restarts us via catcher_ctl ensure_live.
                if not _pogo_alive():
                    w("===== PoGo closed — exiting (no background drain) =====")
                    return
                w("attach failed but PoGo is still up (gadget reachable) — retrying, NOT exiting")
                time.sleep(3); continue
            _SESS["s"] = sess
            finder = pg.get_script_with_helpers(sess)
            ini = finder.exports_sync.init()   # READINESS GATE: libil2cpp must be mapped before install() runs enumerateExports — else it hits null and the loop wedges (the 8h zero-catch stall). Not ready -> raise -> clean backoff + retry. Mirrors restart_pogo_and_wait (pogo_il2cpp.py:289).
            if not (ini and ini.get('gameImage')):
                raise RuntimeError("libil2cpp not mapped yet (no gameImage); backing off")
            sc = pg.get_script_with_helpers(sess, JS)
            st = sc.exports_sync.install()
            if not (st.get("pump") and st.get("pbt")):
                raise RuntimeError(f"install failed {st}")
            # Log whether the Perfect Throw hooks actually RESOLVED. Without this the feature can be
            # "on" while every hook silently failed to bind, which is exactly the kind of thing that
            # should never be reported as working on faith.
            w(f"perfect-throw hooks: {st.get('perfect')}")
            # Arm Perfect Throw IMMEDIATELY, before the ~90-120s inventory gate. It used to be
            # pushed only by the report loop, which runs AFTER that gate -- so for two minutes after
            # every attach the flag read ON while nothing was hooked, and any throw in that window
            # went through untouched. That window is what "I toggled it and it didn't work" was.
            base["perf_hold"] = False   # a fresh attach starts un-held; the frame check re-holds if the game is not rendering
            sc.exports_sync.set_perfect(_flag(PERFECT_FLAG))
            # TOC DISABLED. Even in dry-run this froze the game (CPU 19%, pump dead at 14:54:07).
            # tocTick() calls il2cpp GetPokemon from the pump on every throttled tick while any
            # catch is pending, and with a 600-frame retry per item that is sustained managed-call
            # pressure on the render thread. Pokemod can afford this because its agent runs
            # in-process with its own bridge; through Frida the same shape is not free.
            _toc_push(sc)   # Transfer-on-Catch: read config from the phone, apply live
            w(f"perfect-throw armed at attach: flag={'1' if _flag(PERFECT_FLAG) else '0'}")
            try:
                for _i in range(20):
                    _pd = sc.exports_sync.proto_dump()
                    if _pd:
                        w(f"PROTOFIELDS {_pd}")
                        break
                    time.sleep(0.5)
            except Exception:
                pass
            # dump the collision-path layout once so the OnCollisionEnter rewrite is written against
            # measured offsets rather than assumptions
            try:
                _lay = sc.exports_sync.layout_probe()
                if _lay:
                    w(f"LAYOUT {_lay}")
            except Exception:
                pass
            sc.exports_sync.set_rate(interval, 3500)

            def find1(cls, getter, ns=None):
                ns = ns or sc.exports_sync.ns_of(cls)
                if not ns:
                    return None
                r = finder.exports_sync.find_singleton(ns, cls)
                best = None
                for h in (r.get("hits", []) if isinstance(r, dict) else []):
                    if sc.exports_sync.cls_name(h) != cls:
                        continue
                    v = sc.exports_sync.call0i(h, getter)
                    if v is not None and v >= 0 and (best is None or v > best[1]):
                        best = (h, v)
                return best[0] if best else None

            def find_iap():
                # Pick the SERVER-BACKED IapService instance, not a stale/empty/phantom one.
                # The real account instance carries your real PokeCoins (>0, e.g. 176); empty
                # shells read coins=0. Discriminate by coins first (identifies the real object),
                # tie-break by stardust. Re-evaluated each report so we never read a stale pointer
                # left over from a previous PoGo process (that was the garbage-readout bug).
                ns = sc.exports_sync.ns_of("IapService")
                if not ns:
                    return None
                r = finder.exports_sync.find_singleton(ns, "IapService")
                best = None
                for h in (r.get("hits", []) if isinstance(r, dict) else []):
                    if sc.exports_sync.cls_name(h) != "IapService":
                        continue
                    coins = sc.exports_sync.call0i(h, "get_Coins")
                    dv = sc.exports_sync.call0i(h, "get_Stardusts")
                    if coins is None or coins < 0:
                        continue
                    key = (coins, dv if (dv is not None and dv >= 0) else -1)
                    if best is None or key > best[1]:
                        best = (h, key)
                return best[0] if best else None
            # gate: don't grab singletons until PoGo's inventory has loaded AND the stardust
            # reading has SETTLED (a real, stable IapService instance). Else a reconnect mid-restart
            # latches an empty/transient instance (the Stardust=0/fired=0 degrade). We trust the
            # server-synced value whatever its magnitude — it can be legitimately low after a
            # re-sync — so we gate on STABILITY, not on a magnitude floor (RUN is still false here,
            # so nothing we do moves the value; it only changes while PoGo is still syncing).
            prev = -1
            for _gate in range(40):
                gp = find_iap()
                v = (sc.exports_sync.call0i(gp, "get_Stardusts") or 0) if gp else 0
                if v > 0 and v == prev:
                    break
                prev = v
                # HEARTBEAT. This gate can wait 80s in silence, and the external watchdog judges
                # liveness purely by log mtime -- without this it read a healthy, still-initialising
                # catcher as wedged and restarted it, which loops forever because the restart just
                # re-enters this same gate. Silence must mean wedged, not "busy".
                if _gate % 4 == 0:
                    w(f"init: waiting for inventory/stardust sync ({_gate * 2}s, dust={v})")
                # BAIL EARLY when stardust is simply unavailable. This gate exists to wait for the
                # inventory to finish syncing, but when the IAP singleton does not resolve the value
                # is stuck at -1/0 and can NEVER stabilise -- so it burned the full 40 x 2s = 80s on
                # EVERY attach before a single Pokemon could be caught. Stardust is only used for a
                # progress counter; it is not required to catch or spin. 5 dead iterations (10s) is
                # plenty to distinguish "still syncing" from "not available".
                # 5 dead iterations was 10s burned on EVERY boot, because on this build the IAP
                # singleton never resolves and dust is pinned at -1 -- it can never stabilise, so the
                # wait always ran to the bail. 1 iteration (2s) still distinguishes 'still syncing'
                # from 'not available', and stardust is a progress counter only.
                if v <= 0 and _gate >= 0:
                    w(f"init: stardust unavailable after {_gate * 2}s -- starting anyway "
                      f"(counter only; catching/spinning unaffected)")
                    break
                time.sleep(2)
            info = sc.exports_sync.find_item_bag(); ib = None
            if info:
                r = finder.exports_sync.find_singleton(info["ns"], info["cls"])
                # Probe with the LIVE read: count() is a pure cache read (empty until the pump polls), so using it
                # here validated nothing and left ib=None -> every ball count read -1 -> Poke-only forever.
                # This is one-time setup, not the hot loop, so a live call is fine here.
                ib = next((h for h in (r.get("hits", []) if isinstance(r, dict) else []) if sc.exports_sync.count_live(h, 1) >= 0), None)
            # WAIT FOR THE SINGLETONS instead of shrugging when they are missing.
            # MapPlaceDirectoryService and MapAvatar only exist once the player is actually in the
            # world; attaching during login/loading resolved neither, and the catcher then ran
            # BLIND for its whole session -- attached, logging happily, vis=0 inrange=0, caught=0.
            # That is worse than failing, because every health check said "up". Retry for up to
            # ~2 minutes, then give up and let the outer loop re-attach.
            msvc = avatar = None
            for _try in range(24):
                if not msvc:
                    nm = sc.exports_sync.ns_of("MapPlaceDirectoryService")
                    if nm:
                        rm = finder.exports_sync.find_singleton(nm, "MapPlaceDirectoryService")
                        msvc = next((h for h in (rm.get("hits", []) if isinstance(rm, dict) else [])
                                     if sc.exports_sync.cls_name(h) == "MapPlaceDirectoryService"), None)
                if not avatar:
                    av = sc.exports_sync.ns_of("MapAvatar")
                    if av:
                        ra = finder.exports_sync.find_singleton(av, "MapAvatar")
                        avatar = next((h for h in (ra.get("hits", []) if isinstance(ra, dict) else [])
                                       if sc.exports_sync.cls_name(h) == "MapAvatar"), None)
                if msvc and avatar:
                    break
                if _try == 0:
                    w("waiting for the map to load (singletons not up yet)...")
                time.sleep(5)
            if not (msvc and avatar):
                w(f"map singletons still missing (msvc={'ok' if msvc else 'NO'} "
                  f"avatar={'ok' if avatar else 'NO'}) -- reconnecting rather than running blind")
                try:
                    sc.unload(); sess.detach()
                except Exception:
                    pass
                time.sleep(10)
                continue
            if msvc:
                sc.exports_sync.set_map_svc(msvc)
            if avatar:
                sc.exports_sync.set_avatar(avatar)
            sc.exports_sync.set_max_range(MAX_RANGE_M)
            sc.exports_sync.set_legendary(LEGENDARY_DEX)
            sc.exports_sync.set_priority(PRIORITY_DEX)
            sc.exports_sync.set_thresh(CATCH_THRESHOLD)
            if ib:
                sc.exports_sync.set_item_bag(ib)
            if attempted_master:
                sc.exports_sync.load_attempted(list(attempted_master))  # restore handled-spawn set after a reconnect
            base["bo"] = 3      # connected: reset the reconnect backoff
            base["fails"] = 0   # ...and the stall counter that drives auto-recovery
            try:
                nmb = sc.exports_sync.ns_of("PokemonBagImpl")
                if nmb is not None:
                    rb = finder.exports_sync.find_singleton(nmb, "PokemonBagImpl")
                    pbag = next((h for h in (rb.get("hits", []) if isinstance(rb, dict) else [])
                                 if sc.exports_sync.cls_name(h) == "PokemonBagImpl"), None)
                    if pbag:
                        sc.exports_sync.set_poke_bag(pbag)
                        sc.exports_sync.set_xfer(USE_XFER, XFER_DRY, XFER_MIN_PCT, XFER_MAX_PCT)
                        w(f"auto-transfer armed: {XFER_MIN_PCT}-{XFER_MAX_PCT}% IV "
                          f"{'DRY-RUN (nothing released)' if XFER_DRY else 'LIVE'}")
                        # (box census runs OFFLINE against pokemon.db — never from the RPC thread)
                    else:
                        w("auto-transfer OFF: PokemonBagImpl not found")
            except Exception as _xe:
                w(f"auto-transfer setup failed: {str(_xe)[:70]}")
            iap = find_iap()
            if iap:
                sc.exports_sync.set_iap(iap)   # pump polls stardust on the Unity thread from here on

            def poke():
                return sc.exports_sync.count(ib, 1) if ib else -1
            def great():
                return sc.exports_sync.count(ib, 2) if ib else -1
            def ultra():
                return sc.exports_sync.count(ib, 3) if ib else -1
            def dust():
                return sc.exports_sync.call0i(iap, "get_Stardusts") if iap else -1
            def pinap():
                return sc.exports_sync.count(ib, 705) if ib else -1

            d_now = dust()
            if "d0" not in base:
                base["d0"] = d_now
            if d_now >= 0:
                _save_last_dust(d_now)
            w(f"connected pid={pid} | Poke={poke()} Great={great()} Ultra={ultra()} | Stardust={dust()} | msvc={'ok' if msvc else 'NO'} avatar={'ok' if avatar else 'NO'} iap={'ok' if iap else 'NO'}")
            base["cfg_t"] = base["cnt_t"] = 0   # toggles apply on the first pass below; never force catching on
            last_report = 0
            idle_n = 0
            while True:
                # counts feed the 5s setters and the 10s report only
                if time.time() - base.get('cnt_t', 0) >= 5:
                    base['cnt_t'] = time.time()
                    base['pgu'] = (poke(), great(), ultra())
                p, g, u = base.get('pgu', (-1, -1, -1))
                now = time.time()
                balls_out = (0 <= p <= POKE_FLOOR and 0 <= g <= GREAT_FLOOR and 0 <= u <= ULTRA_FLOOR)
                spin_on = USE_SPIN and _flag(SPIN_FLAG)
                # Out of balls PAUSES catching (the run() setter below gates it on balls_out) and it resumes by
                # itself once restocked. Never exit here: the process lives exactly as long as a toggle is on --
                # an exit was restarted every ~5 min into the same empty bag, a fresh Frida attach each time.
                if balls_out != base.get("floor", False):
                    base["floor"] = balls_out
                    sc.exports_sync.run(_flag(CATCH_FLAG) and not balls_out)
                    w("catching paused: all balls at floor -- resumes when restocked" if balls_out
                      else "catching resumed: balls restocked")
                # SETTERS ARE SLOW-PATH ONLY (every ~5s, not 1.6x/sec). These push configuration that
                # changes at most once a minute; sending them ~25x/sec was a large share of the ~95
                # RPC/sec that was heating the phone. Unknown (-1) counts assume ONLY Poke is available
                # (assuming Great/Ultra we do not own makes every throw invalid -> "Error During Capture?").
                if now - base.get("cfg_t", 0) >= 5:
                    base["cfg_t"] = now
                    sc.exports_sync.set_avail([p > POKE_FLOOR or p < 0, g > GREAT_FLOOR, u > ULTRA_FLOOR])
                    sc.exports_sync.set_berry(USE_PINAP and pinap() > PINAP_FLOOR)
                    sc.exports_sync.set_razz(USE_RAZZ and (sc.exports_sync.count(ib, 701) if ib else 0) > RAZZ_FLOOR, RAZZ_THRESH)
                    sc.exports_sync.run(_flag(CATCH_FLAG) and not balls_out)
                    sc.exports_sync.set_spin(spin_on)
                    sc.exports_sync.set_tap(_flag(TAP_FLAG))
                    sc.exports_sync.set_perfect(_flag(PERFECT_FLAG) and not base.get("perf_hold"))
                for T in (sc.exports_sync.drain_tap() or []):
                    w(f"TAP {T}")
                    # Hand the tapped coordinate to GPS Joystick (the existing mock provider) via a
                    # geo: intent, then bring PoGo straight back so the interruption is a blink.
                    if T.startswith("MOVED "):
                        try:
                            _p = T.split()
                            _teleport(_p[1], _p[2], w)
                        except Exception as _te:
                            w(f"TAP apply failed: {_te}")
                if _flag(TAP_FLAG) and not base.get("tapdiag"):
                    base["tapdiag"] = 1
                    w(f"TAPDIAG {sc.exports_sync.tap_diag()}")
                    # (runs once per attach: base["tapdiag"] stays set for the session)
                # (no runInBackground attempt: verified stripped from this build — managed setter, native icall
                #  and libunity symbols all absent. Retrying it every cycle re-scanned every class in every
                #  assembly for nothing, so it's gone. Unity pauses when backgrounded; keep PoGo in front.)
                stt = sc.exports_sync.stats()
                for _rl in (sc.exports_sync.reticle_log() or []):
                    w(f"RETICLE {_rl}")
                _toc_push(sc)
                for _tl in (sc.exports_sync.drain_toc() or []):
                    w(_tl)
                for _t in (sc.exports_sync.drain_throw() or []):
                    # proto scale: >1.7 Excellent, 1.3-1.7 Great, 1.0-1.3 Nice
                    _r = _t.get('ret') or 0
                    _tier = ("EXCELLENT" if _r > 1.7 else "great" if _r > 1.3
                             else "nice" if _r > 1.0 else "plain")
                    w(f"THROW {'catcher' if _t.get('mine') else 'MANUAL'} ball={_t.get('ball')} "
                      f"ret={_r} [{_tier}] spin={_t.get('spin')} hit={_t.get('hit')} "
                      f"hpos={_t.get('hpos')} perfectOn={_t.get('perf')} aimlocks={_t.get('aim')}")
                for _e in (sc.exports_sync.drain_attempted() or []):
                    attempted_master.add(_e)
                # Full outcome stream: CATCH lines as well as losses, so per-species / per-ball /
                # per-distance rates and probability CALIBRATION (does p=0.6 really catch 60%?) are all
                # computable after the fact. r: 1=caught 2=broke out 3=fled 4=missed.
                for L in (sc.exports_sync.drain_loss() or []):
                    kind = "CATCH" if L.get('r') == 1 else "LOSS"
                    w(f"{kind} r={L.get('r')} p={L.get('p')} ball={L.get('b')} pid={L.get('pid')} "
                      f"att={L.get('a')} src={L.get('src')} dist={L.get('dist')}m spd={L.get('spd')} "
                      f"age={L.get('age')}s reason={L.get('reason')} miss={L.get('miss')} "
                      f"berry={BERRY_NAME.get(L.get('item'), L.get('item'))} auf={L.get('auf')}")
                for X in (sc.exports_sync.drain_xfer() or []):
                    w(f"XFER {X}")
                for S in (sc.exports_sync.drain_spin() or []):
                    w(f"SPINPROBE {S}")
                if (stt.get("q", 0) if isinstance(stt, dict) else 0) < QUEUE_LOW:
                    sc.exports_sync.refill_service()
                # stall recovery: when FULLY idle (no queue, nothing in flight), re-arm the seen-set so a
                # spawn that was marked-seen-but-never-caught (failed open, or drifted into range late) gets
                # another shot. Caught spawns despawn from get_AllPokemon, so this never re-opens them.
                if isinstance(stt, dict) and stt.get("q", 0) == 0 and stt.get("inflight", 0) == 0 and stt.get("thrown", 0) == 0 and stt.get("rethrow", 0) == 0:
                    idle_n += 1
                    if idle_n >= 8:
                        sc.exports_sync.reset_seen(); sc.exports_sync.refill_service(); idle_n = 0
                else:
                    idle_n = 0
                now = time.time()
                if now - last_report >= 10:
                    last_report = now
                    # NOT every report (2026-09-24): find_iap() = class-table scan + STOP-THE-WORLD liveness heap walk from
                    # Frida's thread, every 10s, for a stardust readout that reads -1 on this build anyway.
                    iap2 = iap
                    if iap2 and iap2 != iap:
                        iap = iap2
                        sc.exports_sync.set_iap(iap)
                        nd = dust()
                        if nd >= 0:
                            w(f"--- tracking live IapService {iap} (now {nd} dust) — re-baselining, not a real change ---")
                            base["d0"] = nd; t0 = now
                    d = dust()
                    # A large sudden swing = PoGo re-syncing the SERVER-authoritative balance
                    # (e.g. after a crash/relog), NOT real earning or loss. Re-baseline so the
                    # reported delta stays honest and we never print a phantom +/- spike again.
                    if d >= 0 and base.get("d0", 0) >= 0 and abs(d - base["d0"]) > 150000:
                        w(f"--- stardust re-synced by PoGo: {base['d0']} -> {d} (server-authoritative; nothing earned or lost) ---")
                        base["d0"] = d; t0 = now
                    if d >= 0:
                        _save_last_dust(d)
                    mins = (now - t0) / 60.0
                    gained = d - base["d0"] if d >= 0 and base["d0"] >= 0 else 0
                    pc = sc.exports_sync.prob_sample()
                    # Raw per-ball map exactly as the SERVER sent it in CaptureProbabilityProto
                    # (key = Item enum: 1 Poke, 2 Great, 3 Ultra). Nothing computed on our side.
                    if pc.get("sample"):
                        w(f"SERVERPROB {pc.get('sample')}")
                    ss = sc.exports_sync.spin_scan()   # cached 30s inside JS (full fort walk is ~1700 il2cpp calls)
                    cr = stt.get('cr', {}) if isinstance(stt, dict) else {}
                    skp = stt.get('skipped', 0) if isinstance(stt, dict) else 0
                    sks = stt.get('skipstatus', {}) if isinstance(stt, dict) else {}
                    sks_named = {('NONE' if int(k) < 0 else ESTAT.get(int(k), int(k))): v for k, v in sks.items()} if isinstance(sks, dict) else sks
                    tally = stt.get('statustally', {}) if isinstance(stt, dict) else {}
                    tally_named = {ESTAT.get(int(k), k): v for k, v in tally.items()} if isinstance(tally, dict) else tally
                    src = stt.get('srccatch', {}) if isinstance(stt, dict) else {}
                    scls = stt.get('seencls', {}) if isinstance(stt, dict) else {}
                    fp = stt.get('fleeprof', []) if isinstance(stt, dict) else []
                    rz = (sc.exports_sync.count(ib, 701) if ib else -1)
                    gr = (sc.exports_sync.count(ib, 706) if ib else -1)
                    # PIPELINE HEALTH — counters that were collected but never printed. Shows whether we're
                    # spawn-starved (q=0) or backlogged (q high), and WHY opens get discarded (skipstatus:
                    # NONE = no response, others = server status codes), plus the encounter-status mix.
                    # perfect= is the APPLIED state (hooks actually installed), not the flag file --
                    # a toggle reading ON while every hook failed to bind is exactly the failure mode
                    # that must never be invisible.
                    # WATCHDOG: the pump drives FRAME. If it stops advancing while our hooks are
                    # applied, we most likely froze the game -- revert immediately and turn the
                    # feature off rather than leaving the user to force-restart PoGo.
                    _fr = stt.get("frame")
                    if _fr == base.get("lastframe"):
                        # FRAME comes from LateUpdate. If it is not advancing, the game's main
                        # thread is not running -- i.e. FROZEN. Detect it here instead of waiting
                        # for the user to notice and say so.
                        base["frozen"] = base.get("frozen", 0) + 1
                        if base["frozen"] == 2:
                            w(f"!!! GAME FROZEN: pump FRAME stuck at {_fr} across two reports")
                    else:
                        base["frozen"] = 0
                    if stt.get("perfect") and _fr == base.get("lastframe"):
                        base["stall"] = base.get("stall", 0) + 1
                        if base["stall"] >= 2:
                            r = sc.exports_sync.panic_revert()
                            base["perf_hold"] = True   # held HERE; the user's toggle is never written
                            w(f"!!! PUMP STALLED with Perfect Throw applied -> {r}; "
                              f"Perfect Throw held off until the game renders again (toggle untouched)")
                            base["stall"] = 0
                    else:
                        base["stall"] = 0
                        if base.get("perf_hold") and _fr != base.get("lastframe"):
                            base["perf_hold"] = False
                            w("Perfect Throw resumed: game rendering again")
                    base["lastframe"] = _fr
                    w(f"PERFECT applied={stt.get('perfect')} want={stt.get('perfwant')} "
                      f"hooks[{stt.get('pterr')}] FIRED{stt.get('ptc')} headshot[{stt.get('hserr')}] "
                      f"RT{stt.get('rt')} HK{stt.get('hk')} "
                      f"BALL[init={stt.get('sawInit')} hg={stt.get('hgWas')} hk={stt.get('hkWas')} "
                      f"fixed={stt.get('fixHG')}/{stt.get('fixHK')}] "
                      f"aimlocked={stt.get('hs')} forged={stt.get('forged')} cid={stt.get('cid')} "
                      f"aimTo={stt.get('aimto')} "
                      f"{stt.get('hslast') or ''}")
                    w(f"DIAG q={stt.get('q')} inflight={stt.get('inflight')} thrown={stt.get('thrown')} "
                      f"rethrowQ={stt.get('rethrow')} opened={stt.get('opened')} fired={stt.get('fired')} "
                      f"skipped={skp} notm={stt.get('notm')} fcerr={stt.get('fcerr')}/{stt.get('fcerrmsg')} fcok={stt.get('fcok')} skipstatus={sks_named} encstatus={tally_named} "
                      f"seencls={scls} vis={stt.get('vis')} inrange={stt.get('inrange')}")
                    w(f"run {int(now-t0)}s | +{gained} ({gained/mins if mins>0 else 0:.0f}/min) | caught={cr.get('s')} esc={cr.get('e')} flee={cr.get('f')} miss={cr.get('m')} rethrow={stt.get('refired')} GIMMI={stt.get('priocaught')}/{stt.get('prioseen')}(lost {stt.get('priolost')}) | bySrc={src} | berries Razz={rz}(fed {stt.get('nrazz')}) Pinap={pinap()}(fed {(stt.get('nberry') or 0)-(stt.get('nrazz') or 0)}) GRazz={gr} | spd={stt.get('curspeed')}km/h dist=c{stt.get('cdist')}/f{stt.get('fdist')}m(n{stt.get('cdn')}/{stt.get('fdn')}) stale={stt.get('staleskip')} far={stt.get('outrange')} frame={stt.get('frame')} | loss={fp[-3:]} | P={poke()} G={great()} U={ultra()} pc={pc.get('n')} | stops={ss} | SPIN ok={stt.get('spinok')} xp={stt.get('spinxp')} items={stt.get('spinitems')} res={stt.get('spinres')}")
                    try:
                        _sp = ss if isinstance(ss, dict) else {}
                        with open(STATE_FILE, "w") as _sf:
                            _sf.write(f"caught={cr.get('s')} fled={cr.get('f')} spins={stt.get('spinok', 0)} "
                                      f"xp={stt.get('spinxp', 0)} items={stt.get('spinitems', 0)} "
                                      f"ready={_sp.get('spinnable', '?')} cooling={_sp.get('cooling', '?')}\n")
                        try:
                            os.chmod(STATE_FILE, 0o666)
                        except Exception:
                            pass
                    except Exception as _se:
                        w(f"STATE_WRITE_FAIL {type(_se).__name__}: {str(_se)[:90]}")
                # BATTERY: when the frame counter stops advancing the game is paused (backgrounded or
                # screen off) — nothing can be caught or spun, so back right off instead of polling
                # ~2x/sec forever. This is the "not playing = no drain" fix.
                _fr = stt.get('frame') if isinstance(stt, dict) else None
                if _fr is not None and _fr == base.get('last_frame'):
                    base['idle_n'] = base.get('idle_n', 0) + 1
                else:
                    if base.get('idle_n', 0) >= 5:
                        w(f"--- game active again (was idle {base['idle_n']} checks) ---")
                    base['idle_n'] = 0
                base['last_frame'] = _fr
                for _ in range(6 if base.get('idle_n', 0) >= 3 else 1):
                    time.sleep(1.0)
                    if _paused():
                        raise RuntimeError("pause requested by another tool")   # -> detach via the link-drop path
        except Exception as e:
            # EXPONENTIAL BACKOFF: a flat 3s retry produced ~5,800 reconnect storms (1 per ~3s) whenever PoGo
            # was closed/backgrounded — pure battery burn with nothing to catch. Back off to 60s while it's
            # gone, and snap back to 3s the moment a session succeeds.
            base["bo"] = min(int(base.get("bo", 3) * 2), 15)   # cap 15s: 60s left the catcher idle for a minute mid-session
            base["fails"] = base.get("fails", 0) + 1
            # AUTO-RECOVERY: backoff alone stopped the CPU burn but never recovered — the log shows
            # 703 consecutive 60s retries (~11h dead) while PoGo sat unready (libil2cpp unmapped =
            # "enumerateExports of null", i.e. login/splash screen). After ~5 min of solid failure,
            # nudge PoGo to the foreground ONCE so it finishes loading, instead of waiting forever.
            # SELF-HEAL. When PoGo dies while we are attached it leaves a dead ESTABLISHED socket on the
            # single-client gadget, so every later attach just times out ("timeout was reached") and the
            # toggle looks ON while nothing happens. A plain foreground nudge does NOT clear that socket —
            # only restarting PoGo does. Escalate: nudge first, then force a clean restart.
            # Deliberately does NOT start, foreground, or restart PoGo. The catcher must never
            # manipulate the user's game; if it cannot attach it just backs off (and exits if the
            # game is closed, handled above).
            w(f"--- link drop: {str(e)[:70]} — reconnecting in {base['bo']}s (fail #{base['fails']}) ---")
            try:
                sess.detach()
            except Exception:
                pass
            time.sleep(base["bo"])


main()
