"""GYM BERRY AUTO-FEEDER (Berry Master grind). When you OPEN a gym, feeds every defender on the main-thread
pump: GymRootController.FeedPokemon(Item, pokemonId, gymId). Razz(701) then Nanab(703) ONLY — never Golden
/Pinap. Paced ~2.8s (your confirmed-safe manual rate). Reads each defender's MotivationNow/FeedCooldown to
skip full/cooling mons; LOGS every feed + result; backs off on ErrorPokemonFull(5)/ErrorTooFrequent(10).
Self-reconnecting. Usage: python feed_loop.py [MAX]  (MAX feeds; 0 = until you stop. default 5 = test)."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

LOG = os.path.join(ROOT, "system", "analysis", "pokemod", "feed_loop.log")
MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 5
RAZZ, NANAB = 701, 703
BERRY_FLOOR = int(sys.argv[2]) if len(sys.argv) > 2 else 20   # reserve floor per berry (arg2 to override for testing)
FEED_INTERVAL_MS = 2800
PER_DEFENDER_MAX = 8
RESULT = {0: 'Unset', 1: 'Success', 2: 'ErrorCannotUse', 3: 'ErrorNotInRange', 4: 'ErrorPokemonNotThere',
          5: 'ErrorPokemonFull', 6: 'ErrorNoBerriesLeft', 7: 'ErrorWrongTeam', 8: 'ErrorWrongCount',
          9: 'ErrorTooFast', 10: 'ErrorTooFrequent', 11: 'ErrorGymBusy', 12: 'ErrorRaidActive', 13: 'ErrorGymClosed'}

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),isVT:b("il2cpp_class_is_valuetype","int",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function getterByRet(k,sub){var h=H_();if(!k)return null;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGPC(m)!==0)continue;var rt=h.tGN(h.mGRT(m)).readCString();if(rt.indexOf(sub)>=0)return m;}catch(e){}}return null;}
function findMethodLike(k,sub,argc){var h=H_();if(!k)return null;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{if(argc>=0&&h.mGPC(m)!==argc)continue;if(h.mGN(m).readCString().indexOf(sub)>=0)return m;}catch(e){}}return null;}
function inv(m,obj,params){var h=H_();if(!m)return null;var n=params?params.length:0;var args=ptr(0);if(n){args=Memory.alloc(Process.pointerSize*n);for(var i=0;i<n;i++)args.add(i*Process.pointerSize).writePointer(params[i]);}var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,args,exc);if(!exc.readPointer().isNull())return null;return r;}

var GRC=ptr(0), GRCC=ptr(0), IB=ptr(0), RUN=false, MAX=0, FED=0;
var INTERVAL_MS=2800, PERDEF_MAX=8, RAZZ=701, NANAB=703, FLOOR=20;
var ST=0, lastFeedMs=0, RESULT_SEQ=0, LAST_RES=-1, curId="0", preSeq=0, stFrame=0, CUR=null;
var DEF={}, EVENTS=[], M={};

rpc.exports.setItemBag=function(p){IB=ptr(p);};
rpc.exports.setGrc=function(p){GRC=ptr(p);};
rpc.exports.setCfg=function(interval,perdef,floor){if(interval)INTERVAL_MS=interval;if(perdef)PERDEF_MAX=perdef;if(floor!==undefined)FLOOR=floor;};
rpc.exports.setMax=function(m){MAX=m;};
rpc.exports.run=function(on){RUN=!!on; if(on){FED=0;ST=0;}};
rpc.exports.getEvents=function(){var e=EVENTS;EVENTS=[];return e;};
rpc.exports.stats=function(){return {fed:FED,state:ST,grc:(GRC.isNull()?0:1),curId:curId};};
rpc.exports.grcActive=function(p){try{var g=ptr(p);var m=mOf(H_().OGC(g),"get_IsMapGymActive",0);if(!m)return false;var r=inv(m,g,[]);return r?!!r.add(0x10).readU8():false;}catch(e){return false;}};
rpc.exports.diag=function(){var h=H_();var o={grc:!GRC.isNull()};
 if(GRC.isNull())return o;
 try{o.cls=h.CGN(h.OGC(GRC)).readCString();}catch(e){}
 try{var a=inv(M.active,GRC,[]);o.active=a?!!a.add(0x10).readU8():null;}catch(e){o.active='ERR';}
 try{var e=inv(M.defs,GRC,[]);o.hasEnum=!!(e&&!e.isNull());
   if(e&&!e.isNull()){var gem=mOf(h.OGC(e),"GetEnumerator",0);o.hasGetEnum=!!gem;
     if(gem){var enr=inv(gem,e,[]);if(enr&&!enr.isNull()){var enrC=h.OGC(enr);var self=h.isVT(enrC)?enr.add(0x10):enr;var mn=findMethodLike(enrC,"MoveNext",0),gc=findMethodLike(enrC,"get_Current",0);o.hasMN=!!mn;o.hasGC=!!gc;
       if(mn&&gc){var defs=[],g=0;while(g++<40){var r=inv(mn,self,[]);if(!r||r.add(0x10).readU8()===0)break;var def=inv(gc,self,[]);if(!def||def.isNull())continue;try{var mot=def.add(0x10).readPointer();var pk=mot.add(0x10).readPointer();defs.push({cp:pkCp(pk),mv:Math.round(mot.add(0x28).readDouble()*100)/100,cd:mot.add(0x38).readS64().toString(),spec:pkSpec(pk)});}catch(e2){defs.push({err:''+e2});}}o.defCount=defs.length;o.defs=defs;}
     }}
   }}catch(e){o.enumErr=''+e;}
 return o;};
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.findItemBag=function(){var h=H_();var imgs=["holo-game.dll","holo-protos.dll"];for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(/^I[A-Z]/.test(nm))continue;var m=h.cMN(k,Memory.allocUtf8String("GetItemCount"),1);if(m&&!m.isNull())return {ns:h.CGNS(k).readCString(),cls:nm};}catch(e){}}}return null;};
rpc.exports.count=function(ibStr,item){var h=H_();var ib=ptr(ibStr);var m=h.cMN(h.OGC(ib),Memory.allocUtf8String("GetItemCount"),1);if(!m)return -1;var a=Memory.alloc(4);a.writeS32(item);var args=Memory.alloc(Process.pointerSize);args.writePointer(a);var ex=Memory.alloc(Process.pointerSize);ex.writePointer(ptr(0));var r=h.rI(m,ib,args,ex);if(!ex.readPointer().isNull())return -2;try{return r?r.add(0x10).readS32():-3;}catch(e){return -4;}};
function countItem(id){return rpc.exports.count(IB.toString(),id);}

rpc.exports.install=function(){var h=H_();var st={};
 GRCC=findClass("holo-game.dll","GymRootController");
 if(GRCC){
   M.feed=mOf(GRCC,"FeedPokemon",3); st.feed=!!M.feed;
   M.defs=mOf(GRCC,"get_GymDefenders",0); st.defs=!!M.defs;
   M.active=mOf(GRCC,"get_IsMapGymActive",0); st.active=!!M.active;
   var initM=mOf(GRCC,"Initialize",4); if(initM){var ad=initM.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){GRC=a[0];}});st.initHook=true;}}
   // capture the LIVE controller: the game calls these on the active controller while you view/refresh a gym
   var caps=[["RefreshGymDetails",1],["UpdateGymStatusProto",1],["get_GymDefenders",0],["get_GymName",0],["get_GymTeam",0],["StartRefreshGym",0],["get_GymMapPlaceDetails",0],["set_View",1],["SetupGymArenaAssets",0],["SnapGymAnimationToCurrentTier",0]];
   var nh=0; caps.forEach(function(c){var m=mOf(GRCC,c[0],c[1]); if(m){var aa=m.readPointer(); if(!aa.isNull()){Interceptor.attach(aa,{onEnter:function(a){GRC=a[0];}}); nh++;}}});
   st.capHooks=nh;
 }
 var pp=findClass("holo-protos.dll","PokemonProto");
 M.pId=mOf(pp,"get_Id",0); M.pFort=mOf(pp,"get_DeployedFortId",0); M.pCp=mOf(pp,"get_Cp",0); M.pSpec=mOf(pp,"get_PokemonId",0);
 st.pId=!!M.pId; st.pFort=!!M.pFort;
 var op=h.cFN(img("holo-protos.dll"),Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String("GymFeedPokemonOutProto"));
 if(op&&!op.isNull()){var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var n=0;
   while((m=h.cGM(op,it))&&!m.isNull()){try{if(h.mGN(m).readCString()!=="MergeFrom")continue;if(h.mGPC(m)!==1)continue;var c=m.readPointer();if(c.isNull())continue;Interceptor.attach(c,{onEnter:function(a){this.s=a[0];},onLeave:function(r){try{var s=this.s;if(s&&!s.isNull()){LAST_RES=s.add(0x10).readS32();RESULT_SEQ++;}}catch(e){}}});n++;}catch(e){}}
   st.resultHooks=n;}
 var camC=findClass("holo-game.dll","CameraFollowingGround");var lu=mOf(camC,"LateUpdate",0);
 if(lu){var ad=lu.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){tick();}});st.pump=true;}}
 return st;
};

function grcOk(){ if(GRC.isNull())return false; try{ return H_().OGC(GRC).equals(GRCC); }catch(e){ return false; } }
function pkId(pk){var r=inv(M.pId,pk,[]);return r?r.add(0x10).readU64():uint64(0);}
function pkCp(pk){var r=M.pCp?inv(M.pCp,pk,[]):null;return r?r.add(0x10).readS32():0;}
function pkSpec(pk){var r=M.pSpec?inv(M.pSpec,pk,[]):null;return r?r.add(0x10).readS32():0;}
function pickBerry(){ if(countItem(RAZZ)>FLOOR)return RAZZ; if(countItem(NANAB)>FLOOR)return NANAB; return 0; }

function nextTarget(){
 if(!grcOk())return null;
 try{ var act=inv(M.active,GRC,[]); if(act&&act.add(0x10).readU8()===0)return null; }catch(e){return null;}
 var e=inv(M.defs,GRC,[]); if(!e||e.isNull())return null;
 var gem=mOf(H_().OGC(e),"GetEnumerator",0); if(!gem)return null; var enr=inv(gem,e,[]); if(!enr||enr.isNull())return null;
 var enrC=H_().OGC(enr); var self=H_().isVT(enrC)?enr.add(0x10):enr;
 var mn=findMethodLike(enrC,"MoveNext",0), gc=findMethodLike(enrC,"get_Current",0); if(!mn||!gc)return null;
 var now=Date.now(), guard=0;
 while(guard++<60){ var r=inv(mn,self,[]); if(!r||r.add(0x10).readU8()===0)break; var def=inv(gc,self,[]); if(!def||def.isNull())continue;
   try{ var mot=def.add(0x10).readPointer(); if(!mot||mot.isNull())continue;       // GymDefenderProto.MotivatedPokemon @0x10
     var pk=mot.add(0x10).readPointer(); if(!pk||pk.isNull())continue;             // MotivatedPokemonProto.Pokemon @0x10
     var cp=pkCp(pk); if(cp<=0||cp>100000)continue;                                // sanity: real defender (guards a bad offset)
     if(mot.add(0x28).readDouble()>=0.99)continue;                                 // MotivationNow full
     if(mot.add(0x38).readS64()>0)continue;                                        // FeedCooldownDurationMillis remaining
     var id=pkId(pk); var idk=id.toString(); if(idk==="0")continue;
     var d=DEF[idk]||{fed:0,bu:0}; if(d.bu>now)continue; if(d.fed>=PERDEF_MAX)continue;
     var fort=inv(M.pFort,pk,[]); if(!fort||fort.isNull())continue;
     return {id:id,idk:idk,fort:fort,cp:cp,spec:pkSpec(pk)};
   }catch(e2){}
 }
 return null;
}
function fireFeed(t){ try{ var iv=Memory.alloc(4); iv.writeS32(t.berry); var pv=Memory.alloc(8); pv.writeU64(t.id); inv(M.feed,GRC,[iv,pv,t.fort]); }catch(e){EVENTS.push({k:'err',m:'feed:'+e});} }

function tick(){ if(!RUN)return;
 try{ var now=Date.now();
  if(ST===0){ if(now-lastFeedMs<INTERVAL_MS)return; var t=nextTarget(); if(!t)return;
    var berry=pickBerry(); if(berry===0){EVENTS.push({k:'stop',why:'OUT_OF_BERRIES'});RUN=false;return;}
    t.berry=berry; curId=t.idk; CUR=t; EVENTS.push({k:'feed',id:t.idk,berry:berry,cp:t.cp,spec:t.spec}); preSeq=RESULT_SEQ; fireFeed(t); lastFeedMs=now; stFrame=now; ST=1; return;
  }
  if(ST===1){
    if(RESULT_SEQ>preSeq){ var rc=LAST_RES; EVENTS.push({k:'result',id:curId,res:rc}); var d=DEF[curId]||{fed:0,bu:0};
      if(rc===1){d.fed++;FED++;} else if(rc===5){d.fed=PERDEF_MAX;} else if(rc===10){d.bu=now+30*60*1000;}
      DEF[curId]=d;
      if(MAX>0&&FED>=MAX){EVENTS.push({k:'done',fed:FED});RUN=false;return;}
      ST=0; return;
    }
    if(now-stFrame>3500){EVENTS.push({k:'result',id:curId,res:-1});ST=0;return;}
  }
 }catch(err){EVENTS.push({k:'err',m:'tick:'+err});}
}
"""


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    f = open(LOG, "a", encoding="utf-8")

    def w(s):
        line = f"{time.strftime('%H:%M:%S')} {s}"; f.write(line + "\n"); f.flush(); print(line, flush=True)

    w(f"===== GYM FEEDER start MAX={MAX} berries=Razz+Nanab floor={BERRY_FLOOR} interval={FEED_INTERVAL_MS}ms — self-reconnecting =====")
    while True:
        sess = None
        try:
            for i in range(6):
                try:
                    sess, pid = pg.get_session(); break
                except Exception as e:
                    if i == 0:
                        w(f"waiting for PoGo... ({str(e)[:40]})")
                    time.sleep(5)
            if not sess:
                time.sleep(3); continue
            finder = pg.get_script_with_helpers(sess)
            sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
            st = sc.exports_sync.install()
            need = ["pump", "feed", "defs", "pId", "pFort"]
            if not all(st.get(k) for k in need):
                raise RuntimeError(f"install incomplete {st}")
            sc.exports_sync.set_cfg(FEED_INTERVAL_MS, PER_DEFENDER_MAX, BERRY_FLOOR)
            sc.exports_sync.set_max(MAX)
            # ItemBag
            info = sc.exports_sync.find_item_bag(); ib = None
            if info:
                r = finder.exports_sync.find_singleton(info["ns"], info["cls"])
                ib = next((h for h in (r.get("hits", []) if isinstance(r, dict) else []) if sc.exports_sync.count(h, RAZZ) >= 0), None)
            if ib:
                sc.exports_sync.set_item_bag(ib)
            # GymRootController (already-open gym); Initialize hook also captures future opens
            ns = sc.exports_sync.ns_of("GymRootController")
            grc = None
            if ns:
                rg = finder.exports_sync.find_singleton(ns, "GymRootController")
                hits = [h for h in (rg.get("hits", []) if isinstance(rg, dict) else []) if sc.exports_sync.cls_name(h) == "GymRootController"]
                active = [h for h in hits if sc.exports_sync.grc_active(h)]
                grc = active[0] if active else (hits[0] if hits else None)
                w(f"GymRootController hits={len(hits)} active={len(active)}")
                if grc:
                    sc.exports_sync.set_grc(grc)
            razz = sc.exports_sync.count(ib, RAZZ) if ib else -1
            nanab = sc.exports_sync.count(ib, NANAB) if ib else -1
            w(f"connected pid={pid} | install ok | Razz={razz} Nanab={nanab} | gym={'open' if sc.exports_sync.stats().get('grc') else 'none yet — open a gym'}")
            w("===== OPEN A GYM and it'll feed every defender (Razz then Nanab). Watching. =====")
            sc.exports_sync.run(True)
            done = False; last_diag = 0
            while not done:
                for e in (sc.exports_sync.get_events() or []):
                    k = e.get("k")
                    if k == "feed":
                        b = "Razz" if e.get("berry") == RAZZ else ("Nanab" if e.get("berry") == NANAB else e.get("berry"))
                        w(f"FEED dex={e.get('spec')} cp={e.get('cp')} {b} pokemonId={e.get('id')}")
                    elif k == "result":
                        w(f"  -> {RESULT.get(e.get('res'), e.get('res'))}")
                    elif k == "stop":
                        w(f"STOP: {e.get('why')}"); done = True
                    elif k == "done":
                        w(f"===== DONE: fed {e.get('fed')} this session ====="); done = True
                    elif k == "err":
                        w(f"  err {e.get('m')}")
                now = time.time()
                if now - last_diag >= 4:
                    last_diag = now
                    d = sc.exports_sync.diag()
                    if not (isinstance(d, dict) and d.get("active")) and ns:
                        rg2 = finder.exports_sync.find_singleton(ns, "GymRootController")
                        for h in (rg2.get("hits", []) if isinstance(rg2, dict) else []):
                            if sc.exports_sync.cls_name(h) == "GymRootController" and sc.exports_sync.grc_active(h):
                                sc.exports_sync.set_grc(h); d = sc.exports_sync.diag(); break
                    w(f"  [diag] {d}")
                time.sleep(0.5)
            sess.detach(); return
        except Exception as e:
            w(f"--- link drop: {str(e)[:200]} — reconnecting ---")
            try:
                sess.detach()
            except Exception:
                pass
            time.sleep(3)


main()
