"""Stamp collector: every stop of a stamp rally he has not stamped yet, one by one.

Benny, 2026-11-18 (the LEGO rally, 221 stops on three continents): "go to each one, collect the stamp and capture the
pokemon and on to the next stop" / "wait for each map to totally load, collect the stamp, then capture the pokemon,
then repeat" / "we're going to call this stamp collector mode".

At each stop, in the game's own order (learned from his own taps, recorded call by call on 11-18):
  1 jump onto the stop        the joystick's free TELEPORT, to the rally's OFFICIAL map point (it was the stop's exact
                              place 2 of 2 times the game's own stamp list was 126 m and 235 m off)
  2 wait for the map          the game's own map reply for the new place, and the stop itself on the map
  3 open the stop             MapPokestop.OnTap -- an unstamped rally stop opens straight into the stamp screen
  4 press the stamp           OnButtonDown, hold (1.9 s = ink 0.54; the press length IS the ink, see --ink), OnButtonUp -> SaveStamp
  5 claim the reward          OnExit -> the reward pulse -> OnClaimRewardPressed -> ClaimReward
  6 catch the reward          the encounter the game opens by itself; MapPokemon.TryCapture until the server says caught
A stop counts only when the server answered: stamp saved, reward claimed, Pokemon CAUGHT. A fled reward is said, not hidden.

Never restarts the game. While it moves him it only listens (hooks) and calls the six game methods above on the game's
own thread: no heap scan runs between the first jump and the last (the two heap reads -- the stamp list before, the
check after -- happen while he stands still). It ends by itself, and says why, when the map stops loading (the server's
map answers are recorded: on 11-18 the map went empty for 4 minutes and only a game restart brought it back), when the
game leaves the screen, or when a step does nothing; a stop is never thrown away because of those.

  python AutoCatcher/tools/stamp_collector.py                 READ ONLY: the rally, what is left, room in the bag
  python AutoCatcher/tools/stamp_collector.py --go            run the tour (game automation: only on his go)
      --until N      end when N stamps are collected in all        --max-stops K   at most K stops this run
      --minutes M    end after M minutes                           --safe          the slower step timings of 11-18
      --ink X        stamp ink 0.1 (a tap, faint) .. 1.0 (a 3.2 s press, full); default 0.54 = the 1.9 s press
      --collection ID (default STAMP_RALLY_LEGO_GLOBAL_2026)       --official FILE the rally's official map points
  python AutoCatcher/tools/stamp_collector.py --selftest      offline checks (CI)
To end a running tour: create the file `stop` in the state folder's inbox (printed at start). It ends after the stop
it is on. Writes a log (.jsonl) and a page (.html) per run under AutoCatcher/system/analysis/scans/ (git-ignored).
"""
import argparse
import collections
import html
import json
import subprocess
import math
import os
import queue
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.dirname(HERE)
OUT_DIR = os.path.join(AC, "system", "analysis", "scans")
DATA_DIR = os.path.join(HERE, "stamp_data")
COLLECTION = "STAMP_RALLY_LEGO_GLOBAL_2026"
PROTOS = "holo-protos.dll"
COL = "Holoholo.Rpc.PlayerRpcStampCollectionProto"
PLAYER = "Holoholo.Rpc.ClientPlayerProto"

MAP_STATUS = {0: "Unset", 1: "Success", 2: "LocationUnset", 3: "Error"}          # GetMapObjectsOutProto.Types.Status (0.435.2)
CATCH = {0: "error", 1: "caught", 2: "broke out", 3: "fled", 4: "missed", 5: "item replaced"}   # CatchPokemonOutProto status
SAVE = {1: "saved", 2: "already stamped", 3: "no such collection", 4: "no such stop", 5: "stop not in the rally",
        6: "rally expired"}
CLAIM = {1: "claimed", 2: "already claimed", 3: "no such reward", 4: "not enough stamps", 5: "not in range",
         6: "no such collection"}
STALL_S = 150              # no good map answer this long after a jump = the map is not loading here. 11-18 22:13-22:17:
                           # after many jumps the server holds EVERY new place 30-70 s after the jump (Woodfield 31 s,
                           # farmland 71 s, while the game kept asking from there); earlier that evening 2-9 s. Giving
                           # up at 13 s and jumping back and on only added jumps and made the hold longer: wait here.
STOP_CAP_S = 210           # one stop never holds the tour longer than this
ALT_MIN_M = 30             # the other known point of a stop is tried only when it is this far from the first
INK_MIN_MS, INK_FULL_MS = 420, 2750   # the stamp's ink (PlayerStampProto.Pressure, 0.1 faint .. 1.0 full) grows with the press:
                                       # read back from 51 stamps on 11-18 -- a tap 0.10, 1.9 s 0.54, his 2.5 s 0.77, his longest 1.0


def hold_ms(ink):
    """How long to press for an ink strength (0.1 .. 1.0)."""
    return int(INK_MIN_MS + INK_FULL_MS * max(0.1, min(1.0, ink)) + (80 if ink >= 1.0 else 0))


# step timings (ms). "fast" = the same calls in the same order as 11-18, with my own waits cut; "safe" = the 11-18 values.
# 11-18 21:57-22:01 live: tap 0.5 s after the stop's object, press 0.25 s after the stamp screen opens (not at the end
# of the finger intro), claim 0.3 s after the stamp -- every stop stamped, ~1.5 s a stop less (was 1000/1700/150/400).
# The first throw stays 1.15 s into the encounter: at 0.85 s, 1 of 8 encounters (Fashion Place 22:00:36) closed right
# after the throw with no catch answer, and that reward was lost (0 of 21 at 1.15 s).
FAST = {"settle": 500, "posSettle": 300, "moveSettle": 1500, "retap": 1600, "introMax": 250, "pressLag": 60, "hold": 1900,
        "exitLag": 80, "pulseMax": 200, "claimLag": 150, "saveMax": 3000, "claimMax": 2500, "throwLag": 1150, "rethrow": 900,
        "replyMax": 2200, "endMax": 4000, "lateMax": 1500, "maxThrows": 12, "stepLimit": 9000, "encLimit": 13000, "maxOff": 30, "ball": 1, "saveGo": -1,
        "prejump": False, "preMs": 20000}  # prejump: jump to the next stop when the reward encounter opens (asked 11-18
                                           # 21:36 "preload maps ... during the bottle necks"). OFF: 21:46 "you cant catch
                                           # the pikachu if you early jump before catching it" (the server's answers had
                                           # 6 of 6 caught in run 7, bag +6 -- off on his word; it saved ~1 s a stop)
SAFE = dict(FAST, settle=1500, introMax=1700, pressLag=250, exitLag=550, pulseMax=2500, claimLag=400, throwLag=1150, rethrow=1500,
            replyMax=2600)
# 11-18 21:14-21:21, the first live runs (17 stops): a tap 0.4 s after the stop appeared did not open it 4 times in a row
# (1 stop) -> settle 1.0 s. A press 60 ms after the intro works (the "did not send" of the first run was a blind hook,
# see press()). The claim 0.4 s after OnExit, without waiting ~1.3 s for the reward pulse, worked on 2 of 2.

# every game method the tour hooks or calls: the tour refuses to start when one of them is not found (a game update)
REQUIRED = ["MapPokestop.UpdateData", "MapPokestop.OnTap", "PokestopInteractionState.EnterState",
            "PokestopInteractionState.ExitState", "StampMiniGameGuiController.Initialize",
            "StampMiniGameGuiController.SetFinishedIntroFingerAnim", "StampMiniGameGuiController.PlayStampCollectHaptic",
            "StampMiniGameGuiController.PlayRewardPulse", "StampMiniGameGuiController.OnButtonDown",
            "StampMiniGameGuiController.OnButtonUp", "StampMiniGameGuiController.OnExit",
            "StampMiniGameGuiController.OnClaimRewardPressed", "StampCollectionService.SaveStamp",
            "StampCollectionService.ClaimReward", "StampCollectionService.RewardPokemonSpawned",
            "EncounterInteractionState.EnterState", "EncounterState.ExitState", "MapPokemon.TryCapture",
            "GetMapObjectsOutProto.reply", "GetMapObjectsProto.CalculateSize", "CatchPokemonOutProto.reply",
            "SaveStampOutProto.reply", "ClaimStampCollectionRewardOutProto.reply", "PokeballThrow", "pump"]

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a,{exceptions:'propagate'}):null;}   /* never steal ART's own faults */
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),oN:b("il2cpp_object_new","pointer",["pointer"]),isVT:b("il2cpp_class_is_valuetype","int",["pointer"]),
   cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","uint32"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),
   cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),fGFl:b("il2cpp_field_get_flags","int",["pointer"])};
 return H;}
function img(name){var h=H_();var sp=Memory.alloc(8);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
/* one pass per image for every wanted class name (metadata reads only: safe from the RPC thread) */
function classMap(image,want,ns){var h=H_();var im=img(image);var out={};if(!im)return out;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var n=h.CGN(k).readCString();if(!want[n])continue;if(ns&&h.CGNS(k).readCString()!==ns)continue;(out[n]=out[n]||[]).push(k);}catch(e){}}return out;}
function methods(k){var h=H_();var it=Memory.alloc(8);it.writePointer(ptr(0));var out=[];for(var g=0;g<700;g++){var m=h.cGM(k,it);if(m.isNull())break;out.push(m);}return out;}
function fields(k){var h=H_();var it=Memory.alloc(8);it.writePointer(ptr(0));var o={};for(var g=0;g<500;g++){var f=h.cGF(k,it);if(f.isNull())break;if(h.fGFl(f)&0x10)continue;o[h.fGN(f).readCString().replace(/_$/,'').toLowerCase()]=h.fGO(f);}return o;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function sstr(p){try{if(p.isNull())return null;var n=p.add(0x10).readS32();if(n<0||n>400)return null;return p.add(0x14).readUtf16String(n);}catch(e){return null;}}
/* il2cpp_runtime_invoke. The game's main thread only (the pump). A managed exception comes back as {exc}, never as a signal. */
function inv(m,obj,params){var h=H_();var n=params?params.length:0;var args=ptr(0);if(n){args=Memory.alloc(Process.pointerSize*n);for(var i=0;i<n;i++)args.add(i*Process.pointerSize).writePointer(params[i]);}var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,args,exc);var ex=exc.readPointer();if(!ex.isNull()){var cn='?';try{cn=h.CGN(h.OGC(ex)).readCString();}catch(e){}return {exc:cn+': '+sstr(ex.add(0x18).readPointer())};}return {r:r};}
function inv0(p,name){var m=mOf(H_().OGC(p),name,0);if(!m)return 'no '+name;var r=inv(m,p,[]);if(r.exc){out('err',{e:name+' '+r.exc});return 'EXC';}return 'ok';}
function rfN(obj,o){try{if(o===undefined||o<0)return -1;var rf=obj.add(o).readPointer();if(rf.isNull())return 0;return rf.add(0x18).readS32();}catch(e){return -2;}}
function rfAt(obj,o,i){var rf=obj.add(o).readPointer();var arr=rf.add(0x10).readPointer();return arr.add(0x20+8*i).readPointer();}
function dist(a,b,c,d){var dy=(c-a)*111320,dx=(d-b)*111320*Math.cos(a*Math.PI/180);return Math.sqrt(dx*dx+dy*dy);}

var G={}, O={}, M={}, PBT=null, PBT_VT=false, FORTS={}, BYOBJ={}, NFORT=0, SCHED=[], PUMPS=0, SEQ=0, A={st:'idle',seq:0}, LASTASK=0, LASTREP={}, NREP=0, QJ=[];
var MAPIDS={}, NMAP=0, LASTPOS={t:0,lat:0,lng:0};   /* every stop in the map answers (with a position), and the last asked place:
   what arm() needs when the tour jumped to this stop BEFORE arming it (while the last reward was being caught) */
function now(){return Date.now();}
function out(k,o){o=o||{};o.k=k;o.t=now();o.fid=A.fid||null;o.seq=A.seq||0;send(o);}
function later(ms,fn){SCHED.push({at:now()+ms,seq:A.seq,fn:fn});}                 /* a job dies with its stop */
function live(){return A.st!=='idle'&&A.st!=='done'&&A.st!=='fail';}
function st(s,why){A.st=s;A.at=now();if(A.marks[s]===undefined)A.marks[s]=A.at-A.t0;out('st',{st:s,why:why||''});}
function fail(why){ if(!live())return; var at=A.st; A.st='fail'; A.enc=false; out('fail',{at:at,why:why,marks:A.marks,taps:A.taps,throws:A.throws,save:A.saveResult,claim:A.claimResult,catches:A.catches}); }

/* ---- the stop on the map. MapPokestop.Initialize(PoiSetupData{FortProto@24}) = the moment the game creates the stop's
   map object; MapPokestop.UpdateData(PokemonFortProto) = its refreshes. 11-18 21:18: UpdateData came ~6 s after the map
   answer that held the stop (one map cycle), on 5 of 6 stops: Initialize is the earlier signal. ---- */
function fortProto(obj,p,how){ try{ var fid=sstr(p.add(O.fortId).readPointer()); if(!fid)return; var key=obj.toString();
   var f={p:obj,t:now(),lat:p.add(O.fortLat).readDouble(),lng:p.add(O.fortLng).readDouble(),how:how}; FORTS[fid]=f; BYOBJ[key]=fid; NFORT++;
   if(fid===A.fid&&A.st==='wait'&&!A.fortAt){ A.marks[how]=now()-A.t0; seen(f,false); } }catch(e){} }
function onFort(a){ fortProto(a[0],a[1],'upd'); }
function onInit(a){ try{ if(O.setupFort<0||a[1].isNull())return; var p=a[1].add(O.setupFort).readPointer(); if(!p.isNull())fortProto(a[0],p,'init'); }catch(e){} }
function seen(f,pre){ A.fortAt=pre?Math.min(now(),f.t):now(); A.flat=f.lat; A.flng=f.lng; A.fd=(f.lat||f.lng)?dist(A.tlat,A.tlng,f.lat,f.lng):0; A.marks.fort=A.fortAt-A.t0;
   out('fort',{lat:f.lat,lng:f.lng,d:Math.round(A.fd),pre:!!pre});
   if(A.fd>G.maxOff&&!A.moved){ A.needMove=true; out('move',{lat:f.lat,lng:f.lng,d:Math.round(A.fd)}); } }

/* ---- the six steps: each one starts from the game's own signal that the step before is finished ---- */
function onOpen(a){ A.inStop=true; if(A.st==='tap')st('open'); }
function onClose(a){ A.inStop=false; if(A.st==='fail'||A.st==='idle'||A.st==='done')out('closed',{}); }
function onPage(a){ out('page',{open:true}); }
function onPageClose(a){ out('page',{open:false}); }
function onGame(a){ if(!(A.st==='tap'||A.st==='open'))return; A.gui=a[0]; st('game'); var g=a[0]; later(G.introMax,function(){press(g);}); }
function onIntro(a){ if(A.st==='game')press(a[0]); }
/* A game method called from here never fires the hooks of the methods IT calls (Frida does not trap calls made by its own
   NativeFunction): SaveStamp inside OnButtonUp and ClaimReward inside OnClaimRewardPressed are invisible (11-18 21:14:
   "the press did not send the stamp" on 4 of 4 stops that were in fact stamped). So the proof of each step is the
   game's NEXT step, which runs on its own (the stamp haptic, the reward spawn), and a step is repeated only when that
   does not come. */
function press(g){ if(A.st!=='game'||A.pressing)return; A.pressing=true;
   later(G.pressLag,function(){ if(A.st!=='game')return; inv0(g,'OnButtonDown'); st('press');
     later(G.hold,function(){ if(A.st!=='press')return; inv0(g,'OnButtonUp'); st('saving'); var mine=A.presses;
       later(G.saveMax,function(){ if(A.st!=='saving'||A.presses!==mine)return;
         A.pressing=false; A.presses++; if(A.presses>=3){ fail('no stamp after 3 presses'); return; }
         A.st='game'; A.at=now(); out('note',{m:'no stamp '+G.saveMax+' ms after the press -- pressing again'}); press(g); }); }); }); }
function onSaveCall(a){ A.saveCalled=true; }
function onHaptic(a){ if(!(A.st==='saving'||A.st==='press'))return; st('stamped'); var g=a[0]; later(G.exitLag,function(){exitNow(g);}); }
function exitNow(g){ if(A.st!=='stamped'||A.pulse)return; A.exits++; inv0(g,'OnExit'); A.at=now();
   if(G.noClaim){ A.st='done'; out('done',{caught:null,noclaim:true,inStop:!!A.inStop,save:A.saveResult,marks:A.marks,taps:A.taps,d:Math.round(A.fd||0)}); return; }
   later(G.pulseMax,function(){ if(A.st!=='stamped'||A.pulse)return; claim(g); }); }      /* no pulse seen: press claim anyway (a second OnExit could close the screen) */
function onPulse(a){ if(A.st!=='stamped'||A.pulse)return; A.pulse=true; var g=a[0]; later(G.claimLag,function(){claim(g);}); }
function claim(g){ if(A.st!=='stamped')return; A.claims++; if(A.claims>3){ fail('no reward after 3 claim presses'); return; }
   /* no claim button at this stop (11-18 22:29 PokéXciting! Singapore: NullReference): the rally pays on its own page */
   if(inv0(g,'OnClaimRewardPressed')==='EXC'){ A.st='done'; out('done',{caught:null,noclaim:true,inStop:!!A.inStop,save:A.saveResult,marks:A.marks,taps:A.taps,d:Math.round(A.fd||0)}); return; }
   st('claim'); A.at=now(); var mine=A.claims;
   later(G.claimMax,function(){ if(A.st!=='claim'||A.claims!==mine)return; A.st='stamped'; out('note',{m:'no reward '+G.claimMax+' ms after the claim -- pressing it again'}); claim(g); }); }
function onClaimCall(a){ A.claimCalled=true; }
function onSpawn(a){ A.mon=a[1]; if(A.st==='claim'||A.st==='stamped')st('spawn'); }
function onEnc(a){ if(!A.mon||!(A.st==='spawn'||A.st==='claim'))return; A.enc=true; st('enc'); later(G.throwLag,throwIt); }
function capture(p,ball){var h=H_();var cap=mOf(h.OGC(p),'TryCapture',2);if(!cap||!PBT)return 'no TryCapture';var obj=h.oN(PBT);obj.add(0x10).writeS32(ball);obj.add(0x14).writeFloat(1.0);obj.add(0x18).writeU8(1);obj.add(0x19).writeU8(1);obj.add(0x1a).writeU8(0);var r=inv(cap,p,[PBT_VT?obj.add(0x10):obj,ptr(0)]);return r.exc?('EXC '+r.exc):'ok';}
/* A throw is followed by ONE of: the encounter ends (caught or fled), a "broke out / missed" answer (throw again
   G.rethrow later), or nothing at all -- a throw the game dropped (11-18: 3 of 19 encounters took 3-4 throws, 2.6 s
   apart; the game's own reward catcher sees the same). So every path ends in "still in the encounter and no throw
   since? throw again". The answers of the on-phone catcher's own catches arrive through the same parser: an answer is
   only a hint here, never the proof -- the proof of the end is the encounter closing. */
function again(ms,since){ later(ms,function(){ if(A.enc&&A.st==='enc'&&A.lastThrow<=since)throwIt(); }); }
function throwIt(){ if(!A.enc||A.st!=='enc')return; if(A.throws>=G.maxThrows){ fail('not caught after '+A.throws+' throws'); return; }
   A.throws++; A.lastThrow=now(); A.replyAt=0; A.at=now(); var since=A.lastThrow; out('throw',{n:A.throws,r:capture(A.mon,G.ball)});
   later(G.replyMax,function(){ if(A.enc&&A.st==='enc'&&A.lastThrow<=since&&!A.replyAt)throwIt(); }); }     /* no answer at all: the game dropped that throw */
/* caught = ANY catch answer said 1: 11-18 22:18 Edinburgh answered [2, 1, 3] -- caught on throw 2, then a second answer
   "fled" 9 ms later (a second throw in flight); the last answer alone called a caught reward "fled" */
function encDone(){ var caught=A.catches.indexOf(1)>=0; var last=caught?1:(A.catches.length?A.catches[A.catches.length-1]:-1); A.late=false; A.st='done';
   out('done',{caught:caught,catch:last,catches:A.catches,throws:A.throws,save:A.saveResult,claim:A.claimResult,marks:A.marks,taps:A.taps,d:Math.round(A.fd||0),lateMs:A.lateMs||0}); }
/* 11-19 16:35 (game 0.437): the encounter closed 0.1 s after throw 2 before any answer to that throw came; the verdict said
   "broke out" while the catcher's MINUTE line counted the catch on the server. So when the last throw has no answer yet,
   the verdict waits up to G.lateMax ms for it. */
function onEncExit(a){ if(!A.enc||A.st!=='enc')return; A.enc=false; A.marks.over=now()-A.t0;
   if(A.catches.indexOf(1)<0&&A.throws&&A.replyAt<A.lastThrow){ A.late=true; A.st='late'; var t0=now();
     later(G.lateMax||1500,function(){ if(A.st==='late'){ A.lateMs=now()-t0; encDone(); } }); return; }
   encDone(); }

/* ---- the server's answers (parsed on a network thread: memory reads only, never a game call) ---- */
function onSaveReply(s){ var r=s.add(O.saveResult).readS32(); if(!live())return; A.saveResult=r; out('save',{r:r}); if(r!==1&&r!==2){ fail('the server refused the stamp ('+r+')'); return; }
   /* saveGo >= 0: go on saveGo ms after the server's "saved" instead of waiting ~0.8 s for the stamp animation's haptic
      (11-18 21:58 "for all i care, you can skip the scenes and animations") */
   if(G.saveGo>=0&&A.gui&&(A.st==='saving'||A.st==='press')){ var g=A.gui; later(G.saveGo,function(){ if(A.st!=='saving'&&A.st!=='press')return; st('stamped'); later(G.exitLag,function(){exitNow(g);}); }); } }
function onClaimReply(s){ var r=s.add(O.claimResult).readS32(); if(!live())return; if(A.claimResult!==1)A.claimResult=r; out('claim',{r:r}); if(r!==1&&r!==2)fail('the server refused the reward ('+r+')'); }
function onCatchReply(s){ if(!(A.enc||A.late)||!A.throws)return; var r=s.add(O.catchStatus).readS32(); A.catches.push(r); A.replyAt=now(); A.at=now(); out('catch',{s:r});
   if(A.late){ if(A.st==='late'){ A.lateMs=now()-A.lastThrow; encDone(); } return; }
   again((r===2||r===4||r===0)?G.rethrow:G.endMax,A.lastThrow); }      /* caught / fled: the encounter closes by itself; still open after endMax = that answer was another catch's */
function onAsk(s){ var n=now(); if(n-LASTASK<200)return; LASTASK=n; var lat=s.add(O.rlat).readDouble(), lng=s.add(O.rlng).readDouble(); LASTPOS={t:n,lat:lat,lng:lng};
   if(A.st==='wait'&&!A.posOk&&dist(lat,lng,A.tlat,A.tlng)<80){ A.posOk=true; A.posAt=n; A.marks.pos=n-A.t0; }
   send({k:'ask',t:n,lat:lat,lng:lng,cells:rfN(s,O.rcells)}); }
/* The map answer itself says whether the stop is there and exactly where: the stop's map object can come seconds
   later (11-18 21:14, Westfarms: the object appeared after 2 answers, the tour had already jumped 8 km to the other
   point and had to come back). So the answer decides: stop in it = wait for its object (and move onto it now when the
   point is off); 2 answers without it = the other point. */
function onMap(s){ var st_=s.add(O.mapStatus).readS32(), n=rfN(s,O.mapCells), forts=0, wild=0, mine=null, t=now();
   for(var i=0;i<n&&i<200;i++){ var c=rfAt(s,O.mapCells,i); if(c.isNull())continue; var f=rfN(c,O.cellForts);
     if(f>0){ forts+=f; for(var j=0;j<f&&j<400;j++){ try{ var fp=rfAt(c,O.cellForts,j); var id=sstr(fp.add(O.fortId).readPointer()); if(!id)continue;
         var la=fp.add(O.fortLat).readDouble(), ln=fp.add(O.fortLng).readDouble(); if(!la&&!ln)continue;   /* a cached cell's record carries no position (0.435) */
         MAPIDS[id]={t:t,lat:la,lng:ln}; NMAP++; if(id===A.fid)mine=MAPIDS[id]; }catch(e){} } }
     var w=rfN(c,O.cellWild); if(w>0)wild+=w; }
   if(NMAP>30000){ MAPIDS={}; NMAP=0; }
   if(mine)inMapNow(mine);
   send({k:'map',t:t,status:st_,cells:n,stops:forts,wild:wild,mine:!!mine}); }
function inMapNow(mine){ if(!live()||A.inMapAt)return; A.inMapAt=Math.min(now(),mine.t); A.marks.inMap=A.inMapAt-A.t0; var d=dist(A.tlat,A.tlng,mine.lat,mine.lng);
   out('inmap',{lat:mine.lat,lng:mine.lng,d:Math.round(d)});
   if(d>G.maxOff&&!A.moved&&!A.fortAt){ A.needMove=true; out('move',{lat:mine.lat,lng:mine.lng,d:Math.round(d)}); } }

/* ---- the pump: once per frame on the game's main thread ---- */
function tick(){ PUMPS++; var n=now();
  if(QJ.length){ var q=QJ.shift(); try{q();}catch(e){out('err',{e:String(e)});} }
  for(var i=0;i<SCHED.length;i++){ var j=SCHED[i]; if(j.at<=n){ SCHED.splice(i,1); if(j.seq===A.seq){ try{j.fn();}catch(e){out('err',{e:String(e)});} } break; } }
  if(A.st==='wait'||A.st==='tap'){
    /* a short move onto the stop sends no new map request (the next one comes with the 5 s cycle): after a move the
       settle time is the proof the game has the new place */
    if(A.fortAt&&!A.needMove&&(A.posOk||(A.moveAt&&n-A.moveAt>=G.moveSettle))){
      var ready=Math.max(A.fortAt+G.settle, A.posAt+G.posSettle, A.moveAt?A.moveAt+G.moveSettle:0);
      if(n>=ready&&n-A.lastTap>=G.retap){
        var f=FORTS[A.fid];
        /* only an object the game put on / refreshed on its map during THIS stop is tapped (one kept from an earlier
           place can be a destroyed object); a stop that was already on the map and is not refreshed gets 10 s, then
           is tapped if it is under 2 minutes old */
        var fresh=f&&(f.t>=A.t0-(G.preMs||3000)||(n-A.posAt>10000&&n-f.t<120000));
        if(f&&fresh&&BYOBJ[f.p.toString()]===A.fid){
          if(A.taps>=4){ fail('the stop did not open after 4 taps'); return; }
          A.taps++; A.lastTap=n; if(A.st==='wait')st('tap'); else A.at=n;
          var r=inv(M.onTap,f.p,[ptr(0),ptr(0)]); if(r.exc)out('err',{e:'OnTap '+r.exc}); } } } }
  if(live()&&A.st!=='wait'&&A.st!=='tap'){ var lim=(A.st==='enc')?G.encLimit:G.stepLimit; if(n-A.at>lim)fail('nothing happened for '+Math.round((n-A.at)/1000)+' s'); }
}

function hook(k,name,argc,cb,p0){ var h=H_(); var n=0; methods(k).forEach(function(m){ try{ if(h.mGN(m).readCString()!==name||h.mGPC(m)!==argc)return; if(p0){ if(h.tGN(h.mGP(m,0)).readCString().indexOf(p0)<0)return; }
   var ad=m.readPointer(); if(ad.isNull())return; Interceptor.attach(ad,{onEnter:function(a){ try{cb(a);}catch(e){} }}); n++; }catch(e){} }); return n; }
function hookReply(k,cb){ var h=H_(); var n=0, seen_={}; methods(k).forEach(function(m){ try{ if(h.mGPC(m)!==1)return; var tn=h.tGN(h.mGP(m,0)).readCString(); if(!/CodedInputStream|ParseContext/.test(tn))return;
   var ad=m.readPointer(); if(ad.isNull()||seen_[ad.toString()])return; seen_[ad.toString()]=1;
   Interceptor.attach(ad,{onEnter:function(a){this.s=a[0];},onLeave:function(){ try{ var key=this.s.toString(), t=now(); if(LASTREP[key]&&t-LASTREP[key]<80)return; LASTREP[key]=t; if(++NREP%200===0)LASTREP={}; cb(this.s); }catch(e){} }}); n++; }catch(e){} }); return n; }

rpc.exports.install=function(){ var h=H_(); var got={}; function add(n,c){ got[n]=(got[n]||0)+c; }
  var g=classMap('holo-game.dll',{MapPokestop:1,PokestopInteractionState:1,StampMiniGameGuiController:1,StampCollectionService:1,EncounterInteractionState:1,EncounterState:1,MapPokemon:1,PokeballThrow:1,CameraFollowingGround:1,PoiSetupData:1});
  var p=classMap('holo-protos.dll',{PokemonFortProto:1,GetMapObjectsOutProto:1,GetMapObjectsProto:1,ClientMapCellProto:1,CatchPokemonOutProto:1,SaveStampOutProto:1,ClaimStampCollectionRewardOutProto:1},'Holoholo.Rpc');
  function each(n,fn){ (g[n]||[]).forEach(fn); }
  function pf(n){ return p[n]?fields(p[n][0]):{}; }
  var ff=pf('PokemonFortProto'), fo=pf('GetMapObjectsOutProto'), fr=pf('GetMapObjectsProto'), fc=pf('ClientMapCellProto');
  O={fortId:ff.fortid, fortLat:ff.latitude, fortLng:ff.longitude, mapStatus:fo.status, mapCells:fo.mapcell, cellForts:fc.fort, cellWild:fc.wildpokemon,
     rcells:fr.cellid, rlat:fr.playerlat, rlng:fr.playerlng, catchStatus:pf('CatchPokemonOutProto').status, saveResult:pf('SaveStampOutProto').result, claimResult:pf('ClaimStampCollectionRewardOutProto').result};
  var okOff=Object.keys(O).every(function(k){ return typeof O[k]==='number'&&O[k]>=0x10; });
  O.setupFort=-1; (g.PoiSetupData||[]).forEach(function(k){ var fs=fields(k); Object.keys(fs).forEach(function(n){ if(/fortproto/.test(n))O.setupFort=fs[n]; }); });
  each('MapPokestop',function(k){ if(okOff){ add('MapPokestop.UpdateData',hook(k,'UpdateData',1,onFort,'PokemonFortProto')); if(O.setupFort>=0)add('MapPokestop.Initialize',hook(k,'Initialize',1,onInit,'PoiSetupData')); }
     var m=mOf(k,'OnTap',2); if(m){ M.onTap=m; add('MapPokestop.OnTap',1); } });
  each('PokestopInteractionState',function(k){ add('PokestopInteractionState.EnterState',hook(k,'EnterState',0,onOpen)); add('PokestopInteractionState.ExitState',hook(k,'ExitState',0,onClose)); });
  each('StampMiniGameGuiController',function(k){ add('StampMiniGameGuiController.Initialize',hook(k,'Initialize',1,onGame)); add('StampMiniGameGuiController.SetFinishedIntroFingerAnim',hook(k,'SetFinishedIntroFingerAnim',0,onIntro));
     add('StampMiniGameGuiController.PlayStampCollectHaptic',hook(k,'PlayStampCollectHaptic',0,onHaptic)); add('StampMiniGameGuiController.PlayRewardPulse',hook(k,'PlayRewardPulse',0,onPulse));
     ['OnButtonDown','OnButtonUp','OnExit','OnClaimRewardPressed'].forEach(function(n){ if(mOf(k,n,0))add('StampMiniGameGuiController.'+n,1); }); });
  each('StampCollectionService',function(k){ add('StampCollectionService.SaveStamp',hook(k,'SaveStamp',4,onSaveCall)); add('StampCollectionService.ClaimReward',hook(k,'ClaimReward',1,onClaimCall)); add('StampCollectionService.RewardPokemonSpawned',hook(k,'RewardPokemonSpawned',1,onSpawn)); });
  each('StampCollectionGuiState',function(k){ add('StampCollectionGuiState.EnterState',hook(k,'EnterState',2,onPage)); add('StampCollectionGuiState.ExitState',hook(k,'ExitState',0,onPageClose)); });
  each('EncounterInteractionState',function(k){ add('EncounterInteractionState.EnterState',hook(k,'EnterState',0,onEnc)); });
  each('EncounterState',function(k){ add('EncounterState.ExitState',hook(k,'ExitState',0,onEncExit)); });
  each('MapPokemon',function(k){ if(mOf(k,'TryCapture',2))add('MapPokemon.TryCapture',1); });
  each('PokeballThrow',function(k){ PBT=k; PBT_VT=!!h.isVT(k); add('PokeballThrow',1); });
  if(okOff){ (p.GetMapObjectsOutProto||[]).forEach(function(k){ add('GetMapObjectsOutProto.reply',hookReply(k,onMap)); });
     (p.GetMapObjectsProto||[]).forEach(function(k){ add('GetMapObjectsProto.CalculateSize',hook(k,'CalculateSize',0,function(a){onAsk(a[0]);})); });
     (p.CatchPokemonOutProto||[]).forEach(function(k){ add('CatchPokemonOutProto.reply',hookReply(k,onCatchReply)); });
     (p.SaveStampOutProto||[]).forEach(function(k){ add('SaveStampOutProto.reply',hookReply(k,onSaveReply)); });
     (p.ClaimStampCollectionRewardOutProto||[]).forEach(function(k){ add('ClaimStampCollectionRewardOutProto.reply',hookReply(k,onClaimReply)); }); }
  var pump=[]; var es=classMap('UnityEngine.UI.dll',{EventSystem:1}); (es.EventSystem||[]).forEach(function(k){ var m=mOf(k,'Update',0); if(m&&!m.readPointer().isNull()&&!pump.length){ Interceptor.attach(m.readPointer(),{onEnter:function(){tick();}}); pump.push('EventSystem.Update'); } });
  if(!pump.length) each('CameraFollowingGround',function(k){ var m=mOf(k,'LateUpdate',0); if(m&&!m.readPointer().isNull()&&!pump.length){ Interceptor.attach(m.readPointer(),{onEnter:function(){tick();}}); pump.push('CameraFollowingGround.LateUpdate'); } });
  if(pump.length)add('pump',1);
  return {got:got,off:O,okOff:okOff,pump:pump}; };
rpc.exports.arm=function(fid,lat,lng,opt){ SEQ++; SCHED=[]; G=opt;
  A={seq:SEQ,fid:fid,tlat:lat,tlng:lng,st:'wait',t0:now(),at:now(),marks:{},taps:0,lastTap:0,fortAt:0,inMapAt:0,fd:0,needMove:false,moved:false,moveAt:0,posOk:false,posAt:0,gui:null,pressing:false,presses:0,
     saveCalled:false,saveResult:-1,claimCalled:false,claims:0,claimResult:-1,exits:0,pulse:false,mon:null,enc:false,throws:0,lastThrow:0,replyAt:0,catches:[]};
  out('armed',{}); var pm=G.preMs||3000, n=now();
  /* jumped here before arming (during the last catch): what the game did since then counts */
  if(LASTPOS.t&&n-LASTPOS.t<pm&&dist(LASTPOS.lat,LASTPOS.lng,lat,lng)<80){ A.posOk=true; A.posAt=LASTPOS.t; A.marks.pos=LASTPOS.t-A.t0; }
  var mp=MAPIDS[fid]; if(mp&&n-mp.t<pm)inMapNow(mp);
  var f=FORTS[fid]; if(f&&n-f.t<60000&&BYOBJ[f.p.toString()]===fid)seen(f,true); return SEQ; };
rpc.exports.moved=function(lat,lng){ A.moved=true; A.needMove=false; A.moveAt=now(); A.tlat=lat; A.tlng=lng; return true; };
rpc.exports.retarget=function(lat,lng){ if(A.st!=='wait')return false; A.tlat=lat; A.tlng=lng; A.posOk=false; A.posAt=0; return true; };
rpc.exports.disarm=function(){ SCHED=[]; A={st:'idle',seq:++SEQ}; return true; };
rpc.exports.state=function(){ return {st:A.st,fid:A.fid||null,pumps:PUMPS,forts:NFORT,sched:SCHED.length}; };
rpc.exports.callInt=function(p,name){ var o=ptr(p); QJ.push(function(){ var m=mOf(H_().OGC(o),name,0); if(!m){ send({k:'int',name:name,v:null,e:'no method'}); return; } var r=inv(m,o,[]); send({k:'int',name:name,v:r.exc?null:r.r.add(0x10).readS32(),e:r.exc||null}); }); return true; };
"""


# ----------------------------------------------------------------------------------------------- pure helpers
def meters(a, b):
    r = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl_ = math.radians(b[1] - a[1])
    return 2 * r * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl_ / 2) ** 2))


def tour(start, pts):
    """Nearest-neighbour order from `start`, then 2-opt on the open path (a shorter total jump distance)."""
    left, path, cur = list(pts), [], start
    while left:
        j = min(range(len(left)), key=lambda i: meters(cur, left[i]["at"]))
        cur = left[j]["at"]
        path.append(left.pop(j))
    pos = [start] + [p["at"] for p in path]
    improved = True
    while improved:
        improved = False
        for i in range(1, len(pos) - 2):
            for k in range(i + 1, len(pos) - 1):
                if meters(pos[i - 1], pos[k]) + meters(pos[i], pos[k + 1]) < meters(pos[i - 1], pos[i]) + meters(pos[k], pos[k + 1]) - 1:
                    pos[i:k + 1] = pos[i:k + 1][::-1]
                    path[i - 1:k] = path[i - 1:k][::-1]
                    improved = True
    return path


def stamped_count(stamps):
    """How many stamps he HAS: state 2 and nothing else. (11-18: "collected" was total minus the to-do list, so the two
    stops left out for other reasons counted as collected -- it said 50 at 48.)"""
    return sum(1 for s in stamps.values() if s.get("state") == 2)


def plan(stamps, official=None, skip=()):
    """(to_do, left_out): every unstamped stop with a point to jump to. With an official map, its point comes first (the
    stop's exact place) and the game's own stamp-list point is the second try; a stop the official map does not have is
    left out and named."""
    todo, out = [], []
    for fid, s in stamps.items():
        if s.get("state") == 2:
            continue
        listed = (s["lat"], s["lng"]) if s.get("lat") is not None and s.get("lng") is not None else None
        off = None
        if official is not None:
            o = official.get(fid)
            if o is None:
                out.append({"fort": fid, "name": s.get("name") or fid, "why": "not on the rally's official map"})
                continue
            off = (o["lat"], o["lng"]) if o.get("lat") is not None else None
        if fid in skip:
            out.append({"fort": fid, "name": s.get("name") or fid, "why": "skipped before: %s" % skip[fid]})
            continue
        at = off or listed
        if at is None:
            out.append({"fort": fid, "name": s.get("name") or fid, "why": "no point known"})
            continue
        alt = listed if (off and listed and meters(off, listed) > ALT_MIN_M) else None
        todo.append({"fort": fid, "name": s.get("name") or fid, "at": at, "alt": alt, "cat": s.get("cat"), "sub": s.get("sub")})
    return todo, out


class MapWatch:
    """The game's map requests and the server's answers since the last jump. Only what comes after the game's first
    request FOR THE PLACE HE JUMPED TO counts (an answer still on its way for the place before says nothing about this
    one). A good answer = status Success. The server answers at most one request per 5 s with Success; one that comes
    sooner gets status Error and no cells -- normal, measured 11-18 on every one of 60 answers."""

    def __init__(self, start=None):
        self.total = collections.Counter()
        self.last_good = start                     # the last place that got a good answer in this game session
        self.reset(0.0, None)

    def reset(self, t, at):
        self.t0, self.at, self.here = t, at, at is None
        self.asks, self.asks_here, self.ok, self.bad, self.first_ok, self.stops, self.last_status = 0, 0, 0, 0, None, 0, None

    def feed(self, ev, t):
        if ev["k"] == "ask":
            self.asks += 1
            self.total["asks"] += 1
            if self.at is not None and ev.get("lat") is not None and meters((ev["lat"], ev["lng"]), self.at) < 150:
                self.here = True
            if self.here:
                self.asks_here += 1
        elif ev["k"] == "map":
            good = ev.get("status") == 1
            self.total["ok" if good else "bad"] += 1
            if not self.here:
                return
            self.last_status = ev.get("status")
            if good:
                self.ok += 1
                self.last_good = self.at or self.last_good
                self.stops = max(self.stops, ev.get("stops") or 0)
                if self.first_ok is None:
                    self.first_ok = t - self.t0
            else:
                self.bad += 1

    def stalled(self, now):
        """None, or why the map is not loading: no good answer for STALL_S since the jump."""
        if self.ok or now - self.t0 < STALL_S:
            return None
        secs = now - self.t0
        if not self.asks:
            return "the game sent no map request for %d s" % secs
        if not self.asks_here:
            return "the game asked for the map %d times in %d s, every time for another place (its position did not follow the jump)" % (self.asks, secs)
        if not self.bad:
            return "the game asked for the map of this place %d times in %d s and no answer came back" % (self.asks_here, secs)
        return "the game asked for the map of this place %d times in %d s and the server answered %s every time (%d answers, none with stops)" % (
            self.asks_here, secs, MAP_STATUS.get(self.last_status, self.last_status), self.bad)


def verdict(ev):
    """One line for a finished stop from the tapper's `done` / `fail` message."""
    if ev["k"] == "done" and ev.get("noclaim"):
        return True, "stamped (no reward at this stop)"
    if ev["k"] == "done":
        c = ev.get("catch")
        if ev.get("caught"):
            return True, "stamped + caught (%d throw%s)" % (ev.get("throws") or 0, "" if ev.get("throws") == 1 else "s")
        return False, "stamped, reward %s after %d throws" % (CATCH.get(c, "not caught (%s)" % c), ev.get("throws") or 0)
    return False, "%s (at step: %s)" % (ev.get("why"), ev.get("at"))


def eta_text(done, left, secs):
    if not done:
        return "?"
    per = secs / done
    return "%.1f s per stop, about %d min for the %d left" % (per, round(per * left / 60), left)


def page_html(run):
    """The run's page: offline, phone width."""
    rows = []
    for r in run["stops"]:
        rows.append("<tr class='%s'><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            "ok" if r["ok"] else "bad", r["i"], html.escape(r["name"]), html.escape(r["text"]), "%.0f s" % r["secs"]))
    times = [r["secs"] for r in run["stops"] if r["ok"]]
    med = "%.1f s" % statistics.median(times) if times else "-"
    left = "".join("<li>%s <span>%s</span></li>" % (html.escape(x["name"]), html.escape(x["why"])) for x in run.get("left_out", []))
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stamp collector</title><style>
body{font:15px/1.4 system-ui,sans-serif;margin:0;padding:16px;background:#0f1216;color:#e8eaed}
h1{font-size:20px;margin:0 0 4px}.sub{color:#9aa4af;margin-bottom:14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:14px}
.card{background:#1a2027;border-radius:10px;padding:10px}.card b{display:block;font-size:22px}
table{width:100%%;border-collapse:collapse}td{padding:6px 4px;border-bottom:1px solid #232a33;vertical-align:top}
tr.bad td{color:#ff9d8a}tr.ok td:nth-child(3){color:#8fd6a4}li span{color:#9aa4af}
.why{background:#2a1f1a;border-radius:10px;padding:10px;margin-bottom:14px}</style></head><body>
<h1>Stamp collector</h1><div class="sub">%s &middot; %s</div>
<div class="cards"><div class="card"><b>%s</b>stamps in the game now</div><div class="card"><b>%d</b>stops done this run</div>
<div class="card"><b>%d</b>stops not done</div><div class="card"><b>%s</b>median per stop</div></div>
%s<table>%s</table>%s</body></html>""" % (
        html.escape(run["collection"]), html.escape(run["when"]), html.escape(str(run.get("stamped_after", "?"))),
        sum(1 for r in run["stops"] if r["ok"]), sum(1 for r in run["stops"] if not r["ok"]), med,
        "<div class='why'>Ended: %s</div>" % html.escape(run["ended"]) if run.get("ended") else "",
        "".join(rows), "<h3>Left out</h3><ul>%s</ul>" % left if left else "")


# ----------------------------------------------------------------------------------------------- the game
def _imports():
    sys.path[:0] = [AC, HERE]
    import pogo_il2cpp as pg
    import power_spots as ps
    import dump_game_limits as dl
    import cutoff_hunt as ch
    pg.BUSY_NAME = "AutoCatcher-stamps/%d" % os.getpid()
    return pg, ps, dl, ch


def log(msg):
    print("%s %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def read_rally(pg, ps, dl, sess, cid):
    """The rally from the game's memory: {fort: {name, lat, lng, state}} and the bag's size limit. Heap reads: only ever
    called while he stands still (before the first jump, after the last). The reader cuts every list at 300 (power_spots
    RLIM): the Poke Lid rally has 490 stamps (11-18 22:50), so the cap is raised for this read."""
    sc = sess.create_script(dl.JS.split("rpc.exports = {")[0] + ps.JS_HELPERS + ";RLIM = 5000;" + ps.JS_EXPORTS)
    sc.load()
    try:
        ex, nxt = sc.exports_sync, 0
        while True:
            r = ps.call(ex.index, PROTOS, nxt, 2500)
            nxt = r["next"]
            if nxt >= r["total"]:
                break
        best = {}
        r = ps.call(ex.scan_keep, PROTOS, COL, 200)
        for i in range(0, r["n"], 4):
            for c in ps.call(ex.page, COL, i, 4, 0) or []:
                if c.get("CollectionId") != cid:
                    continue
                for s in c.get("Stamps") or []:
                    m = s.get("StampMetadata") or {}
                    k = m.get("FortId")
                    if k and (k not in best or s.get("State") == 2):
                        best[k] = {"fort": k, "lat": m.get("Latitude"), "lng": m.get("Longitude"), "name": m.get("FortTitleKey") or k, "state": s.get("State"),
                               "cat": m.get("CategoryKey"), "sub": m.get("SubcategoryKey")}
        cap = None
        try:
            r = ps.call(ex.scan_keep, PROTOS, PLAYER, 40)
            caps = [c.get("MaxPokemonStorage") for i in range(0, r["n"], 4) for c in (ps.call(ex.page, PLAYER, i, 4, 0) or [])]
            caps = [c for c in caps if isinstance(c, int) and c > 0]
            cap = max(caps) if caps else None
        except Exception:  # noqa: BLE001
            pass
        return best, cap
    finally:
        sc.unload()


class Game:
    """One attach: the hook script, its messages, and the joystick."""

    def __init__(self, pg, ch):
        self.pg, self.ch, self.q = pg, ch, queue.Queue()
        self.sess = self.sc = self.pid = None
        self.gone = False

    def attach(self):
        self.pg.wait_ready_to_attach()
        self.sess, self.pid = self.pg.get_session()
        self.gone = False
        self.sess.on("detached", lambda *a: setattr(self, "gone", True))
        return self.pid

    def hooks(self):
        self.sc = self.sess.create_script(JS)
        self.sc.on("message", lambda m, d: self.q.put(m["payload"] if m.get("type") == "send" else {"k": "jserr", "e": str(m)[:300]}))
        self.sc.load()
        r = self.sc.exports_sync.install()
        missing = [n for n in REQUIRED if not r["got"].get(n)]
        if not r.get("okOff"):
            missing.append("proto field offsets %s" % r.get("off"))
        return r, missing

    def unhook(self):
        try:
            if self.sc:
                self.sc.unload()
        except Exception:  # noqa: BLE001
            pass
        self.sc = None

    def detach(self):
        self.unhook()
        try:
            if self.sess:
                self.sess.detach()
        except Exception:  # noqa: BLE001
            pass

    def on_top(self):
        return "pokemongo" in self.ch.adb("dumpsys activity activities | grep -m1 topResumedActivity")

    def teleport(self, at):
        """The joystick's free TELEPORT. No wait here: the game's own map request for the new place is the proof it
        arrived (run_stop sends the jump once more when none came in 8 s)."""
        self.ch.api("TELEPORT", "--ef lat %.6f --ef lng %.6f" % (at[0], at[1]))

    def page_on_screen(self):
        """True when the rally page's close button is on screen: dark teal at the bottom centre (11-18 22:29 screenshot:
        (28, 134, 148) at 92.7 % and 95 % of the height; the map's menu button there is red-orange (255, 76, 0))."""
        try:
            import io
            from PIL import Image
            raw = subprocess.run(["adb", "-s", self.ch.DEV, "exec-out", "screencap", "-p"], capture_output=True, timeout=8).stdout
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            w, h = im.size
            for fy in (0.927, 0.95):
                r, gg, b = im.getpixel((w // 2, int(h * fy)))
                if r < 70 and 100 <= gg <= 170 and 120 <= b <= 180:
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def screen(self):
        if not getattr(self, "_wh", None):
            try:
                out = self.ch.adb("wm size") or ""
                w, h = out.strip().split(":")[-1].strip().split("x")
                self._wh = (int(w), int(h))
            except Exception:  # noqa: BLE001
                self._wh = (1280, 2856)
        return self._wh

    def bag_count(self):
        """Pokemon in the bag, from the live bag object (one heap scan + one game getter). None when it cannot be told."""
        try:
            g = self.pg.live_graph(self.sess)
            self.sc.exports_sync.call_int(g["bag"], "get_PokemonOnlyCount")
            t0, keep, v = time.time(), [], None
            while time.time() - t0 < 5:
                try:
                    ev = self.q.get(timeout=0.3)
                except queue.Empty:
                    continue
                if ev.get("k") == "int":
                    v = ev.get("v")
                    break
                keep.append(ev)                            # the next stop's events (the tour may already be there)
            for ev in keep:
                self.q.put(ev)
            return v
        except Exception as e:  # noqa: BLE001
            log("bag count not read: %s" % str(e)[:120])
        return None


def run_stop(g, s, opt, mw, inbox, jl, pre=False, nxt=None):
    """One stop. Returns (ok, text, detail). Raises MapStall / GameGone.
    pre = the tour already jumped here (during the last stop's catch); nxt = the stop after this one: the tour jumps there
    the moment this stop's reward encounter opens, so the next place's map loads while the reward is caught."""
    ex = g.sc.exports_sync
    ex.arm(s["fort"], s["at"][0], s["at"][1], opt)
    t0 = time.time()
    if not pre:
        g.teleport(s["at"])
        mw.reset(time.time(), s["at"])
    target, tried_alt, fort, moved, last_st, last_ev, resent, inmap = s["at"], False, None, False, "wait", time.time(), False, None
    jumped, told = False, -30.0
    while True:
        now = time.time()
        if g.gone:
            raise GameGone("the game went away at %s" % s["name"])
        try:
            ev = g.q.get(timeout=0.2)
        except queue.Empty:
            ev = None
        if ev is None and now - last_ev > 8:
            # nothing at all from the game for 8 s (it asks for the map every 5 s): it is not on screen, or it is gone
            last_ev = now
            if not g.on_top():
                ex.disarm()
                log("  Pokemon GO is not on screen -- the tour waits here until it is back")
                while not g.on_top():
                    if os.path.exists(os.path.join(inbox, "stop")):
                        return False, "ended before this stop", {"stopped": True}
                    time.sleep(3)
                time.sleep(3)
                return False, "redo", {"redo": True}
        if ev:
            last_ev = now
            k = ev.get("k")
            if k in ("ask", "map"):
                mw.feed(ev, time.time())
                jl(ev)
                continue
            jl(ev)
            if ev.get("fid") != s["fort"]:
                continue
            if k == "fort":
                fort = ev
            elif k == "inmap":
                inmap = ev
            elif k == "move":
                if abs(ev["lat"]) < 1 and abs(ev["lng"]) < 1:
                    log("  ignored a move to %.4f,%.4f (a stop record without a position)" % (ev["lat"], ev["lng"]))
                elif not moved:
                    g.teleport((ev["lat"], ev["lng"]))
                    ex.moved(ev["lat"], ev["lng"])
                    moved = True
                    log("  the stop is %d m from the point -- moved onto it" % ev["d"])
            elif k == "st":
                last_st = ev["st"]
                if last_st == "enc" and nxt and opt.get("prejump") and not jumped:
                    # the stamp is saved and the reward claimed: only the catch is left, and it needs no map. The next
                    # place's map (two answers, 5 s apart) loads while it runs.
                    g.teleport(nxt["at"])
                    mw.reset(time.time(), nxt["at"])
                    jumped = True
            elif k == "catch" and jumped and ev.get("s") == 0:
                # the server refused a throw after the jump: back to the stop, and no early jumps for the rest of the tour
                g.teleport(fort and (fort["lat"], fort["lng"]) or s["at"])
                opt["prejump"], jumped = False, False
                log("  a throw was refused after the early jump -- back at the stop; the tour now jumps only after each catch")
            elif k == "note":
                log("  %s" % ev.get("m"))
            elif k == "err":
                log("  game call error: %s" % ev.get("e"))
            elif k in ("done", "fail"):
                ok, text = verdict(ev)
                ev["secs"], ev["moved"], ev["first_map_s"], ev["map_ok"], ev["map_bad"] = time.time() - t0, moved, mw.first_ok, mw.ok, mw.bad
                ev["prejumped"] = jumped
                return ok, text, ev
            continue
        if fort is None:
            held = now - mw.t0
            if not mw.ok and held > 15 and held - told >= 30:
                told = held
                log("  the server holds this new place (it does after many jumps): %d s so far -- waiting here, no jumps" % held)
            if not mw.asks_here and not resent and now - mw.t0 > 8:
                resent = True
                log("  no map request for this place after 8 s -- sending the jump once more")
                g.teleport(target)
            why = mw.stalled(now)
            if why:
                ex.disarm()
                raise MapStall(why)
            # the other point only when the map answers do NOT hold the stop (11-18 21:20, Barton Creek: the stop was in
            # the answer, its object came after the 2nd answer, the tour jumped to the other point and came back: 6 s)
            if mw.ok >= 2 and not tried_alt and s.get("alt") and not inmap:
                tried_alt = True
                log("  2 map answers and the stop is not on the map at the official point -- trying the game's own point (%.0f m away)" % meters(s["at"], s["alt"]))
                ex.retarget(s["alt"][0], s["alt"][1])
                g.teleport(s["alt"])
                target, resent = s["alt"], False
                mw.reset(time.time(), s["alt"])
            elif mw.ok >= 3 and (tried_alt or not s.get("alt")) and not inmap:
                ex.disarm()
                return False, "not on the game's map (%d good map answers, up to %d stops in them)" % (mw.ok, mw.stops), {"at": "wait", "map_ok": mw.ok, "secs": now - t0}
        if now - t0 > STOP_CAP_S:
            ex.disarm()
            return False, "no result after %d s (last step: %s)" % (STOP_CAP_S, last_st), {"at": last_st, "secs": now - t0, "timeout": True}


class MapStall(RuntimeError):
    pass


def recover(g, mw, jl, wait_s=14):
    """After a place whose map never loaded: back to the last place that loaded in this game session until one good
    answer comes. 11-18 21:33: after Scottsdale's errors the next NEW place (Las Vegas) got Error too; one good answer
    at Arrowhead (loaded earlier in that game session) and Las Vegas loaded at once. True = a good answer came."""
    at = mw.last_good
    if not at:
        return False
    g.teleport(at)
    mw.reset(time.time(), at)
    t0 = time.time()
    while time.time() - t0 < wait_s:
        try:
            ev = g.q.get(timeout=0.3)
        except queue.Empty:
            continue
        if ev.get("k") in ("ask", "map"):
            mw.feed(ev, time.time())
            jl(ev)
            if mw.ok:
                return True
    return False


class GameGone(RuntimeError):
    pass


BAD_FOR_S = 45 * 60           # a place whose map answered Error goes to the end of the next runs' lists for this long
REGION_M = 200000             # ... and so does every stop within 200 km of it (whole areas answered Error together)


def in_north_america(at):
    """Canada, the US (with Alaska and Hawaii) and Mexico: a box, enough for store points."""
    lat, lng = at
    return 14.0 <= lat <= 72.0 and -170.0 <= lng <= -52.0


def load_bad(state):
    """{stop id: when its map last answered Error}, kept between runs (bad_places.json in the state folder)."""
    try:
        raw = json.load(open(os.path.join(state, "bad_places.json"), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {k: (v if isinstance(v, list) else [v, None, None]) for k, v in raw.items()}   # [when, lat, lng]


def save_bad(state, bad):
    p = os.path.join(state, "bad_places.json")
    try:
        json.dump(bad, open(p + ".tmp", "w", encoding="utf-8"))
        os.replace(p + ".tmp", p)
    except Exception:  # noqa: BLE001
        pass


GUI_STEPS = ("open", "game", "press", "saving", "stamped", "claim", "spawn")


def close_page(g, wait_s=3.0):
    """After a no-claim stamp the game opens the rally's own page (StampCollectionGuiState). Its X (bottom centre) closes
    it. Taps only when the page is known to be open: on the map that spot is the main menu button."""
    t0, opened = time.time(), False
    while time.time() - t0 < wait_s:
        try:
            ev = g.q.get(timeout=0.2)
        except queue.Empty:
            continue
        if ev.get("k") == "page" and ev.get("open"):
            opened = True
            break
    if not opened and not g.page_on_screen():
        return None                                        # no page came: nothing to close
    time.sleep(0.6)
    w, h = g.screen()
    for _ in range(3):
        if not g.page_on_screen():
            return True
        g.ch.adb("input tap %d %d" % (w // 2, int(h * 0.9395)))
        t0 = time.time()
        while time.time() - t0 < 2.0:
            try:
                ev = g.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if ev.get("k") == "page" and not ev.get("open"):
                time.sleep(0.5)
                return True
    return False


def close_stop(g, wait_s=2.0):
    """11-18 22:53 he: "you gotta exit the pokestop when you get the stamp for the ones with no rewards. but be careful
    some have rewards." A no-reward stop leaves the stop's own screen open after the stamp (the next map then took 12-24 s
    to come, ~6 s after a reward stop). Android BACK closes it -- ONCE, and only when the game says that screen is open
    (no ExitState since its EnterState): BACK on the map would ask to leave the game. A reward stop never comes here."""
    g.ch.adb("input keyevent 4")
    t0 = time.time()
    while time.time() - t0 < wait_s:
        try:
            ev = g.q.get(timeout=0.2)
        except queue.Empty:
            continue
        if ev.get("k") == "closed":
            return True
    return False


def close_gui(g, detail):
    """After a failed stop a screen may still be open: Android BACK closes it (the stop screen answers with ExitState).
    True when the map is back. An open ENCOUNTER is never backed out of."""
    at = (detail or {}).get("at")
    if at == "enc":
        return False
    if at not in GUI_STEPS:
        return True
    for _ in range(3):
        g.ch.adb("input keyevent 4")
        t0 = time.time()
        while time.time() - t0 < 2.0:
            try:
                ev = g.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if ev.get("k") == "closed":
                return True
    return False


def only_filter(todo, only):
    """(kept, others): the stops whose rally list (CategoryKey, e.g. region_hokkaido_tohoku) or prefecture
    (SubcategoryKey, e.g. prefecture_iwate) is named in `only` (comma separated; the region_/prefecture_ prefix may be
    left out). 11-18 22:45 "complete all the ones in the hokkaido list" (the Poke Lid page's Hokkaido - Tohoku list)."""
    keys = set()
    for k in (only or "").split(","):
        k = k.strip().lower()
        if k:
            keys |= {k, "region_" + k, "prefecture_" + k}

    def hit(s):
        return (s.get("cat") or "").lower() in keys or (s.get("sub") or "").lower() in keys
    return [s for s in todo if hit(s)], [s for s in todo if not hit(s)]


def run(a):
    pg, ps, dl, ch = _imports()
    region_m = int(a.region_km * 1000)
    official = None
    off_path = a.official or os.path.join(DATA_DIR, a.collection + ".json")
    if os.path.exists(off_path):
        official = {x["id"]: x for x in json.load(open(off_path, encoding="utf-8"))}
    os.makedirs(OUT_DIR, exist_ok=True)
    state = a.state or os.path.join(OUT_DIR, "stamp_collector_state")
    inbox = os.path.join(state, "inbox")
    os.makedirs(inbox, exist_ok=True)
    for f in os.listdir(inbox):
        os.remove(os.path.join(inbox, f))
    g = Game(pg, ch)
    pid = g.attach()
    stamps, cap = read_rally(pg, ps, dl, g.sess, a.collection)
    if not stamps:
        log("the game holds no rally named %s -- open the rally's page in the game once, then run this again" % a.collection)
        g.detach()
        return 2
    have = stamped_count(stamps)
    todo, left_out = plan(stamps, official)
    hk, missing = g.hooks()
    bag = g.bag_count() if not missing else None
    room = cap - bag if (cap and bag is not None) else None
    f = ch.fix()
    if a.north_america:
        # 11-18 21:50 "maybe just focus on getting all the ones in north america rn. go from east coast to west coast."
        far = [s for s in todo if not in_north_america(s["at"])]
        todo = [s for s in todo if in_north_america(s["at"])]
        log("North America only: %d stops; %d elsewhere wait for another run" % (len(todo), len(far)))
    if a.only:
        todo, far = only_filter(todo, a.only)
        log("only %s: %d stops; %d others wait for another run" % (a.only, len(todo), len(far)))
    if a.east_west:
        order = sorted(todo, key=lambda s: -s["at"][1])        # east coast first, west coast last
    else:
        order = tour((f[0], f[1]), todo) if f else todo
    km = sum(meters(order[i]["at"], order[i + 1]["at"]) for i in range(len(order) - 1)) / 1000 if order else 0
    log("%s: %d stamps, %d collected, %d to do (%d left out); %.0f km of jumps; game pid %d" % (a.collection, len(stamps), have, len(order), len(left_out), km, pid))
    for x in left_out:
        log("  left out: %s -- %s" % (x["name"], x["why"]))
    log("bag: %s Pokemon of %s%s" % (bag if bag is not None else "?", cap or "?", "" if room is None else " -- room for %d" % room))
    if missing:
        log("NOT READY: these game methods were not found (a game update?): %s" % ", ".join(missing))
        g.detach()
        return 3
    log("ready: every game method found (%s)" % ", ".join(hk["pump"]))
    if not a.go:
        log("READ ONLY -- nothing moved. Run with --go on his go.")
        g.detach()
        return 0
    if room is not None and room < len(order):
        # no cut here: he frees slots while it runs (11-18 21:41 "dont assume, ive made more space"). The bag is read
        # again after every stop, and the tour ends only when that read says it is full.
        log("the bag has room for %d now (%d stops to do): it is read again after every stop" % (room, len(order)))
    bad = load_bad(state)
    recent = [v for v in bad.values() if time.time() - v[0] < BAD_FOR_S]
    late = [s for s in order if any(meters(s["at"], (v[1], v[2])) < region_m for v in recent if v[1] is not None)
            or any(k == s["fort"] for k, v in bad.items() if time.time() - v[0] < BAD_FOR_S)]
    if late:
        order = [s for s in order if s not in late] + late
        log("%d stops whose map answered Error in the last %d min go last: %s" % (len(late), BAD_FOR_S // 60, ", ".join(s["name"] for s in late)))
    if a.max_stops:
        order = order[:a.max_stops]
    opt = dict(SAFE if a.safe else FAST)
    opt["hold"] = hold_ms(a.ink)
    opt["noClaim"] = bool(a.no_claim)
    log("stamp press: %.1f s (ink %.2f of 1.00)" % (opt["hold"] / 1000, a.ink))
    stamp = time.strftime("%Y-%m-%d_%H%M")
    jpath = os.path.join(OUT_DIR, "stamp_collector_%s.jsonl" % stamp)
    jf = open(jpath, "a", encoding="utf-8")

    def jl(o):
        jf.write(json.dumps(dict(o, at=time.strftime("%H:%M:%S")), ensure_ascii=False) + "\n")
        jf.flush()                                         # readable while the tour runs (11-18 21:14: 0 bytes after 4 stops)

    log("log: %s   to end it: create %s" % (jpath, os.path.join(inbox, "stop")))
    mw, results, ended, t_run, got, stalls = MapWatch((f[0], f[1]) if f else None), [], None, time.time(), 0, 0
    queue_ = [(s, 1) for s in order]
    i, pre, streak, pages = 0, False, set(), [0, 0]       # pages: [no-reward stops with no page, with a page]
    while queue_:
        s, attempt = queue_.pop(0)
        if os.path.exists(os.path.join(inbox, "stop")):
            ended = "you asked it to stop"
            break
        if a.until and have + got >= a.until:
            ended = "%d stamps reached" % a.until
            break
        if a.more and got >= a.more:
            ended = "%d more stamps collected" % a.more
            break
        op = os.path.join(inbox, "opt.json")                # live tuning: step timings change between two stops, no restart
        if os.path.exists(op):
            try:
                new = json.load(open(op, encoding="utf-8"))
                os.remove(op)
                opt.update(new)
                log("timings changed: %s" % new)
                jl({"k": "opt", "new": new})
            except Exception as e:  # noqa: BLE001
                log("opt.json not read yet: %s" % str(e)[:80])
        if a.minutes and time.time() - t_run > a.minutes * 60:
            ended = "%d minutes are over" % a.minutes
            break
        i += 1
        t_s = time.time()
        try:
            ok, text, detail = run_stop(g, s, opt, mw, inbox, jl, pre=pre, nxt=queue_[0][0] if queue_ else None)
            pre = bool(detail.get("prejumped"))
        except MapStall as e:
            pre = False
            # 11-18 21:24-21:31: the server answered Error for Scottsdale Quarter's place for 7 minutes, before AND after a
            # game restart, while Chandler (36 km) and Arrowhead (28 km) loaded at once. One bad place is not a reason to
            # stop: it goes to the end of the list. Two places in a row = the map itself: the tour ends.
            # 11-18 21:44-21:48: Mission Viejo, Ontario Mills (bad in run 6 too) and University Place answered Error for
            # minutes while Disneyland, the last place that loaded, answered at once every time it was asked. A bad place
            # is the place, not the map: back to the last good place, then the next stop. The tour ends only when the
            # last good place stops answering too (60 s).
            stalls += 1
            streak.add(s["fort"])
            bad[s["fort"]] = [time.time(), s["at"][0], s["at"][1]]
            save_bad(state, bad)
            jl({"k": "stall", "why": str(e), "stop": s["name"], "row": stalls})
            more_ = attempt < 3
            if more_:
                queue_.append((s, attempt + 1))
            # 11-18 21:44-21:50: whole areas answered Error together (University Place, Fashion Place, Station Park:
            # Utah; Mission Viejo + Ontario Mills) while far places loaded at once. The stops near a bad place go last.
            near = [q for q in queue_ if meters(q[0]["at"], s["at"]) < region_m]
            if len(near) > 1:
                queue_ = [q for q in queue_ if q not in near] + near
                log("  %d stops within %g km of it go to the end too (the map of a whole area answers Error at once)"
                    % (len(near) - 1, region_m / 1000.0))
            log("  MAP NOT LOADING at %s (%s) -- %s" % (s["name"], e, "it goes to the end of the list" if more_ else
                                                        "3 tries tonight: left for the next run"))
            if not more_:
                results.append({"i": i, "fort": s["fort"], "name": s["name"], "ok": False, "secs": 0, "detail": {},
                                "text": "the map never loaded at this place (3 tries)"})
            if len(streak) >= 5:
                # 11-18 21:44-21:51: 8 NEW places in a row answered Error while the one loaded before answered at once:
                # the game session no longer gets new places (the same at 18:10: only a game restart brought it back).
                # 5 DIFFERENT places: at 22:10 two places tried in turns ended a session that may still have been fine.
                ended = ("THE MAP IS NOT LOADING: %d different new places in a row answered Error, only places loaded before "
                         "answer -- restart the game, then run it again. Nothing was skipped." % len(streak))
                break
            if not (recover(g, mw, jl) or recover(g, mw, jl, wait_s=45)):
                ended = ("THE MAP IS NOT LOADING: %s answered Error, and the last place that loaded did not answer for a "
                         "minute either -- restart the game, then run it again. Nothing was skipped." % s["name"])
                break
            log("  back at the last place that loaded: it answers again -- next stop")
            i -= 1
            continue
        except Exception as e:  # noqa: BLE001
            if not (isinstance(e, GameGone) or g.gone or any(w in str(e) for w in ("destroyed", "detached", "closed"))):
                raise
            log("the game went away -- waiting until it is ready, then this stop again")
            pre = False
            g.detach()
            time.sleep(8)
            g.attach()
            hk, missing = g.hooks()
            if missing:
                ended = "after the game came back these methods were missing: %s" % ", ".join(missing)
                break
            queue_.insert(0, (s, attempt))
            i -= 1
            continue
        stalls, streak = 0, set()
        if detail.get("stopped"):
            ended = "you asked it to stop"
            break
        if detail.get("redo"):
            queue_.insert(0, (s, attempt))
            i -= 1
            pre = False
            continue
        if detail.get("noclaim"):
            # 11-18 22:51: no Poke Lid stop opened a page, and the 3 s wait for one was 3 s lost on every no-reward
            # stop. Three stops with no page = this rally opens none: wait 0.8 s from then on (the screen check stays).
            r_ = close_page(g, wait_s=3.0 if (pages[1] or pages[0] < 3) else 0.8)
            pages[0 if r_ is None else 1] += 1
            if detail.get("inStop") and not close_stop(g):
                log("  the stop's screen did not answer BACK (left open; the next jump goes on)")
        secs = time.time() - t_s
        if ok:
            got += 1
        results.append({"i": i, "fort": s["fort"], "name": s["name"], "ok": ok, "text": text, "secs": secs, "detail": detail})
        jl({"k": "stop", "i": i, "name": s["name"], "ok": ok, "text": text, "secs": round(secs, 1)})
        log("%s (%d/%d) %s: %s, %.0f s  [%s]" % ("DONE" if ok else "NOT DONE", i, len(order), s["name"], text, secs,
                                              eta_text(got, len(queue_), time.time() - t_run)))
        if detail.get("marks"):                             # when each step began, seconds after the jump
            log("    steps: " + "  ".join("%s %.1f" % (k, v / 1000) for k, v in sorted(detail["marks"].items(), key=lambda x: x[1])))
        if not ok:
            if not close_gui(g, detail):
                ended = "a screen stayed open after %s (%s) -- the tour ends here so nothing is tapped blind" % (s["name"], text)
                break
            if detail.get("k") != "done" and attempt == 1:
                queue_.append((s, 2))                      # one more try at the end (a stamped stop whose reward got away has none)
        if cap and (room is None or room - got < 25 or got % 5 == 0):
            # the on-phone catcher keeps catching during the tour (~1 a minute on 11-18): the room read at the start is
            # not enough. A full bag would let the stamp and the claim through and lose the reward Pokemon. With room
            # for 25+ it is read every 5th stop only (11-18 22:35: the read right after a stop hung a run 3 minutes).
            b = g.bag_count()
            if b is not None and cap - b <= 1:
                ended = "the bag is full (%d of %d) -- free some slots, then run it again (nothing was skipped)" % (b, cap)
                break
    bag_after = g.bag_count() if g.sc and not g.gone else None
    g.unhook()
    stamped_after = None
    try:
        time.sleep(2)
        after, _ = read_rally(pg, ps, dl, g.sess, a.collection)
        stamped_after = stamped_count(after)
    except Exception as e:  # noqa: BLE001
        log("the check read failed: %s" % str(e)[:120])
    g.detach()
    ended = ended or "every stop on the list was visited"
    run_ = {"collection": a.collection, "when": time.strftime("%Y-%m-%d %H:%M"), "stops": results, "left_out": left_out, "ended": ended,
            "stamped_before": have, "stamped_after": stamped_after, "bag_before": bag, "bag_after": bag_after, "bag_limit": cap,
            "map": dict(mw.total), "minutes": (time.time() - t_run) / 60}
    json.dump(run_, open(os.path.join(OUT_DIR, "stamp_collector_%s.json" % stamp), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    hpath = os.path.join(OUT_DIR, "stamp_collector_%s.html" % stamp)
    open(hpath, "w", encoding="utf-8").write(page_html(run_))
    bad = [r for r in results if not r["ok"]]
    log("ENDED: %s" % ended)
    log("stamps: %d before, %s now (the game's own list); this run: %d done, %d not done, %.1f min; map answers: %d good, %d refused"
        % (have, stamped_after if stamped_after is not None else "?", got, len(bad), run_["minutes"], mw.total["ok"], mw.total["bad"]))
    if bag is not None and bag_after is not None:
        caught_n = sum(1 for r in results if (r.get("detail") or {}).get("caught"))
        log("bag: %d -> %d of %s (+%d; the %d reward Pokemon caught are in it, with whatever the catcher caught meanwhile)"
            % (bag, bag_after, cap or "?", bag_after - bag, caught_n))      # Poke Lid: a reward every 2nd stamp, not every one
    for r in bad:
        log("  not done: %s -- %s" % (r["name"], r["text"]))
    log("page: %s" % hpath)
    return 0


# ----------------------------------------------------------------------------------------------- self-test
def selftest():
    ok = []

    def check(name, cond):
        ok.append((name, bool(cond)))

    ny, la, ldn = (40.75, -73.99), (34.05, -118.24), (51.5, -0.12)
    check("meters NY-LA", 3_900_000 < meters(ny, la) < 3_980_000)
    pts = [{"fort": "a", "at": la}, {"fort": "b", "at": (40.76, -73.98)}, {"fort": "c", "at": ldn}, {"fort": "d", "at": (34.06, -118.25)}]
    t = tour(ny, pts)
    check("tour visits every stop once", sorted(x["fort"] for x in t) == ["a", "b", "c", "d"])
    check("tour starts with the nearest", t[0]["fort"] == "b")
    lids = [{"fort": "a", "cat": "region_kanto", "sub": "prefecture_tokyo"},
            {"fort": "b", "cat": "region_hokkaido_tohoku", "sub": "prefecture_iwate"}]
    k_, f_ = only_filter(lids, "region_hokkaido_tohoku")
    check("--only keeps one list's stops", [s["fort"] for s in k_] == ["b"] and [s["fort"] for s in f_] == ["a"])
    check("--only takes prefectures without the prefix", len(only_filter(lids, "tokyo, iwate")[0]) == 2)
    check("tour keeps the two LA stops together", abs([x["fort"] for x in t].index("a") - [x["fort"] for x in t].index("d")) == 1)
    stamps = {"s1": {"state": 2, "lat": 1.0, "lng": 1.0, "name": "one"}, "s2": {"state": 1, "lat": 2.0, "lng": 2.0, "name": "two"},
              "s3": {"state": 1, "lat": 3.0, "lng": 3.0, "name": "three"}, "s4": {"state": 1, "lat": None, "lng": None, "name": "four"},
              "s5": {"state": 1, "lat": 5.0, "lng": 5.0, "name": "five"}}
    check("only state 2 counts as collected (11-18: 50 said at 48)", stamped_count(stamps) == 1)
    todo, out = plan(stamps, None)
    check("no official map: listed points, no-point stop left out", [x["fort"] for x in todo] == ["s2", "s3", "s5"] and [x["fort"] for x in out] == ["s4"])
    off = {"s2": {"id": "s2", "lat": 2.0, "lng": 2.002}, "s3": {"id": "s3", "lat": 3.0, "lng": 3.0}, "s4": {"id": "s4", "lat": 4.0, "lng": 4.0}}
    todo, out = plan(stamps, off)
    by = {x["fort"]: x for x in todo}
    check("official point first, the game's point as the second try", by["s2"]["at"] == (2.0, 2.002) and by["s2"]["alt"] == (2.0, 2.0))
    check("same point = no second try", by["s3"]["alt"] is None)
    check("official point rescues a stop the game has no point for", by["s4"]["at"] == (4.0, 4.0))
    check("a stop the official map lacks is left out and named", [x["fort"] for x in out] == ["s5"] and "official" in out[0]["why"])
    check("left-out stops never count as collected", stamped_count(stamps) + len(todo) + len(out) == len(stamps))
    mw, here = MapWatch(), (40.0, -74.0)
    mw.reset(100.0, here)
    check("no stall verdict before %d s" % STALL_S, mw.stalled(100.0 + STALL_S - 1) is None)
    check("silence = the game stopped asking", "no map request" in mw.stalled(100.0 + STALL_S + 1))
    mw.feed({"k": "ask", "lat": 30.0, "lng": -81.0}, 101.0)
    mw.feed({"k": "map", "status": 1, "stops": 158}, 101.2)
    check("an answer for the place before does not count", mw.ok == 0 and "another place" in mw.stalled(100.0 + STALL_S + 1))
    for _ in range(6):
        mw.feed({"k": "ask", "lat": 40.0001, "lng": -74.0001}, 110.0)
        mw.feed({"k": "map", "status": 3, "stops": 0}, 110.1)
    check("only refusals = the server's doing, with its status name", "Error every time" in mw.stalled(100.0 + STALL_S + 1))
    mw.feed({"k": "map", "status": 1, "stops": 128}, 112.0)
    check("one good answer = no stall", mw.stalled(100.0 + 3 * STALL_S) is None and mw.first_ok == 12.0 and mw.stops == 128)
    mw.reset(200.0, here)
    check("a new jump starts a new count, totals stay", mw.ok == 0 and mw.total["ok"] == 2 and mw.total["bad"] == 6)
    check("caught", verdict({"k": "done", "caught": True, "catch": 1, "throws": 2}) == (True, "stamped + caught (2 throws)"))
    check("a fled reward is said", verdict({"k": "done", "caught": False, "catch": 3, "throws": 4})[1] == "stamped, reward fled after 4 throws")
    check("a failed step names the step", verdict({"k": "fail", "why": "the stop did not open after 4 taps", "at": "tap"})[1].endswith("(at step: tap)"))
    check("eta", eta_text(10, 20, 150.0) == "15.0 s per stop, about 5 min for the 20 left" and eta_text(0, 5, 0) == "?")
    page = page_html({"collection": COLLECTION, "when": "x", "stamped_after": 52, "ended": "<test>", "left_out": [{"name": "A & B", "why": "w"}],
                      "stops": [{"i": 1, "name": "LEGO® Store", "ok": True, "text": "stamped + caught (1 throw)", "secs": 12.0},
                                {"i": 2, "name": "<b>", "ok": False, "text": "fled", "secs": 30.0}]})
    check("page escapes names and shows the count", "&lt;b&gt;" in page and "A &amp; B" in page and ">52<" in page and "&lt;test&gt;" in page)
    check("every required method is hooked or looked up in the script", all(n.split(".")[-1] in JS or n in ("pump",) or n.endswith(".reply") for n in REQUIRED))
    check("script braces balance", JS.count("{") == JS.count("}") and JS.count("(") == JS.count(")"))
    check("safe timings only ever slower", all(SAFE[k] >= FAST[k] for k in FAST))
    check("ink 0.54 = the 1.9 s press, a tap is the floor, full ink is the longest", abs(hold_ms(0.54) - 1905) < 10 and hold_ms(0.0) == hold_ms(0.1) and hold_ms(1.0) == 3250 and hold_ms(5) == 3250)
    data = os.path.join(DATA_DIR, COLLECTION + ".json")
    if os.path.exists(data):
        rows = json.load(open(data, encoding="utf-8"))
        check("official LEGO map: 219 stops, each with an id and a point", len(rows) == 219 and all(x.get("id") and x.get("lat") is not None for x in rows) and len({x["id"] for x in rows}) == 219)
    bad = [n for n, c in ok if not c]
    for n, c in ok:
        print("%s %s" % ("ok  " if c else "FAIL", n))
    print("%d checks, %d failed" % (len(ok), len(bad)))
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stamp collector (see the top of this file)")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--collection", default=COLLECTION)
    ap.add_argument("--official")
    ap.add_argument("--state")
    ap.add_argument("--until", type=int, default=0)
    ap.add_argument("--max-stops", type=int, default=0)
    ap.add_argument("--more", type=int, default=0, help="end when N more stamps are collected this run")
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--safe", action="store_true")
    ap.add_argument("--ink", type=float, default=0.54, help="stamp ink strength 0.1 .. 1.0 (the press length); 0.54 = the 1.9 s press of 11-18")
    ap.add_argument("--no-claim", action="store_true", help="rallies that pay on their own page: stamp, close the page, next")
    ap.add_argument("--only", help="only these rally lists / prefectures, e.g. region_hokkaido_tohoku or iwate,miyagi")
    ap.add_argument("--region-km", type=float, default=REGION_M / 1000,
                    help="a place whose map never loads sends the stops within this many km to the end (200 for the LEGO "
                         "world tour; 1 for one town's Poke Lids)")
    ap.add_argument("--north-america", action="store_true", help="only the stops in North America (Canada, the US, Mexico)")
    ap.add_argument("--east-west", action="store_true", help="the order: east to west (by longitude), not the shortest route")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    return run(a)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
