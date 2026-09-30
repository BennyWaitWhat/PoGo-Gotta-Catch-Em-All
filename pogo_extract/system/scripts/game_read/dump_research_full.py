#!/usr/bin/env python
"""READ-ONLY full research/quest reader for PoGo live IL2CPP state.

For every ACTIVE quest emits:
  - templateId / questId / questType / progress / status / timestamps
  - English title + description + per-sub-step text (GetQuestDisplayProto + I18n.Text)
  - Goal target + Condition list (offset-detected single-goal vs RepeatedField)
  - REWARDS: items (id+count), Pokemon encounter (species/form/shiny/featured),
             mega energy (pid + TemporaryEvolutionId X/Y + amount), stardust/exp/etc.
  - sub-quests (MultiPart) with their own live progress
Plus the completedIds list (QuestsProto+0x18) and a self-classifying probe of the
second ~78-entry list at QuestsProto+0x20.

WRITES NOTHING. Never calls CompleteQuest / UpdateQuestDetails / BeginQuestEncounter.

Reuses pogo_il2cpp.py (get_session + JS_PREAMBLE helpers). The QuestService + I18n
singletons are captured by hooking their methods (the proven dump_quests.py pattern),
because liveness on a service that may be multi-instance is less reliable than the hook
for these two; the Today/Research screen must be open so a method fires.

CONSTRAINTS / device-validation flags (see GAME_READ_CAPABILITIES.md §1, §2):
  [DEVICE] Goal@+0x50 single-vs-RF (auto-detected; confirm the branch taken)
  [DEVICE] reward list getter name (get_QuestRewards vs get_Rewards; both tried)
  [DEVICE] boxed primitive payload @ ret+0x10 (int/bool/float)
  [DEVICE] TEMP_EVOLUTION_* ordinals (table below; verify against --probe)
  [DEVICE] the QuestsProto+0x20 element class (probe prints its il2cpp class name)

Usage:
    python dump_research_full.py             # decode active research + rewards
    python dump_research_full.py --probe     # + raw oneof-getter dump on quest#0 reward#0
    python dump_research_full.py --json out.json   # also write machine-readable dump
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
import pogo_il2cpp as pg  # noqa: E402

PROBE = '--probe' in sys.argv
JSON_OUT = None
if '--json' in sys.argv:
    JSON_OUT = sys.argv[sys.argv.index('--json') + 1]

# ---- enum maps (logging only; [DEVICE]-confirm ordinals via --probe) ----
STATUS = {0: 'inactive', 1: 'ACTIVE', 2: 'COMPLETE', 3: 'EXPIRED/claimed', 4: 'TARGETS_MET'}
TEVO = {0: 'UNSET', 1: 'MEGA', 2: 'MEGA_X', 3: 'MEGA_Y', 4: 'PRIMAL'}  # [DEVICE]

# =====================================================================
# 1) capture QuestService + I18n by hooking every method (proven pattern)
# =====================================================================
HOOK_JS = r"""
var Q = null, I = null;
function hookInit() {
  var il = Process.findModuleByName('libil2cpp.so'); var A = {};
  il.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) A[e.name]=e.address; });
  function b(n,r,a){ return A[n] ? new NativeFunction(A[n],r,a) : null; }
  var dG=b('il2cpp_domain_get','pointer',[]), dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),
      aGI=b('il2cpp_assembly_get_image','pointer',['pointer']), iGN=b('il2cpp_image_get_name','pointer',['pointer']),
      cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),
      cGM=b('il2cpp_class_get_methods','pointer',['pointer','pointer']), tA=b('il2cpp_thread_attach','pointer',['pointer']);
  tA(dG());
  var sp=Memory.alloc(4), asms=dGA(dG(),sp), na=sp.readS32(), gi=null;
  for (var a=0;a<na;a++){ var im=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(im).readCString()==='holo-game.dll'){ gi=im; break; } }
  [['Niantic.Holoholo.Quests','QuestService','Q'],
   ['Niantic.Holoholo.Internationalization','I18n','I']].forEach(function(p){
    var c=cFN(gi,Memory.allocUtf8String(p[0]),Memory.allocUtf8String(p[1])); if (!c||c.isNull()) return;
    var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m;
    while ((m=cGM(c,it)) && !m.isNull()) {
      try { var ad=m.readPointer(); if (ad.isNull()) continue;
        (function(lbl){ Interceptor.attach(ad,{onEnter:function(ar){ if (lbl==='Q'&&!Q) Q=ar[0].toString(); if (lbl==='I'&&!I) I=ar[0].toString(); }}); })(p[2]);
      } catch(e) {}
    }
  });
}
rpc.exports.hookSetup = function(){ hookInit(); return 1; };
rpc.exports.hookGet = function(){ return { q: Q, i: I }; };
"""

# =====================================================================
# 2) the reader (appended to JS_PREAMBLE -> has cFN/cMN/rI/_ensureInit)
#    adds holo-protos image + il2cpp_object_get_class for proto accessors
# =====================================================================
READER_JS = r"""
var PROTO_IMAGE = null, OGC = null, CGN = null;
function _proto() {
  if (PROTO_IMAGE) return;
  _ensureInit();
  var il = Process.findModuleByName('libil2cpp.so');
  OGC = new NativeFunction(il.getExportByName('il2cpp_object_get_class'),'pointer',['pointer']);
  CGN = new NativeFunction(il.getExportByName('il2cpp_class_get_name'),'pointer',['pointer']);
  var sp = Memory.alloc(4); var asms = IL2.dGA(IL2.dG(), sp); var na = sp.readS32();
  for (var a=0;a<na;a++){ var im=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());
    if (IL2.iGN(im).readCString()==='holo-protos.dll'){ PROTO_IMAGE = im; break; } }
}
function clsName(o){ try{ if(!o||o.isNull()) return null; return CGN(OGC(o)).readCString(); }catch(e){ return null; } }
function rdStr(p){ if(!p||p.isNull()) return ''; var n=p.add(0x10).readS32(); if(n<=0||n>4000) return '';
  var c=[]; for(var i=0;i<n;i++){ var ch=p.add(0x14+i*2).readU16(); if(ch===0) break; c.push(String.fromCharCode(ch)); } return c.join(''); }
function strNew(s){ var f=Process.findModuleByName('libil2cpp.so').getExportByName('il2cpp_string_new');
  return new NativeFunction(f,'pointer',['pointer'])(Memory.allocUtf8String(s)); }
// invoke 0-arg getter by name on instance, against instance's OWN runtime class -> {ok,ret}
function inv0(instPtr, name){ _proto();
  if(!instPtr||instPtr.isNull()) return {ok:false};
  var m=cMN(OGC(instPtr), name, 0); if(!m||m.isNull()) return {ok:false};
  try{ var ex=Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0)); var r=rI(m,instPtr,ptr(0),ex); return {ok:true,ret:r}; }catch(e){ return {ok:false,err:e.toString()}; }
}
function box32(p){ try{ if(!p||p.isNull()) return null; return p.add(0x10).readS32(); }catch(e){ return null; } }
function boxF(p){ try{ if(!p||p.isNull()) return null; return p.add(0x10).readFloat(); }catch(e){ return null; } }
// RepeatedField<ref> -> array of element ptrs
function rfRefs(rf, cap){ var out=[]; if(!rf||rf.isNull()) return out;
  var cnt=rf.add(0x18).readS32(); var arr=rf.add(0x10).readPointer();
  if(arr.isNull()||cnt<=0||cnt>5000) return out;
  for(var i=0;i<Math.min(cnt,cap||500);i++) out.push(arr.add(0x20).add(i*8).readPointer()); return out; }
function looksLikeRF(p){ try{ if(!p||p.isNull()) return false; var cnt=p.add(0x18).readS32();
  if(cnt<0||cnt>5000) return false; var arr=p.add(0x10).readPointer(); if(arr.isNull()) return false;
  var maxlen=arr.add(0x18).readS32(); return maxlen>=cnt && maxlen<10000; }catch(e){ return false; } }

// ---- decode one QuestGoalProto (target + condition cases) ----
function readGoals(qp) {
  var slot = qp.add(0x50).readPointer();
  if (!slot || slot.isNull()) return {kind:'none', goals:[]};
  function readOne(g){ var o={}; try{ o.target=g.add(0x18).readS32(); }catch(e){}
    try{ var cond=g.add(0x10).readPointer(); var cs=rfRefs(cond,20); o.conditions=[];
      for(var i=0;i<cs.length;i++){ var cc=inv0(cs[i],'get_ConditionCase'); o.conditions.push(cc.ok?box32(cc.ret):null); } }catch(e){}
    return o; }
  if (looksLikeRF(slot)) {  // [DEVICE] Goal repeated branch
    var gs=rfRefs(slot,20); var out=[]; for(var i=0;i<gs.length;i++) if(!gs[i].isNull()) out.push(readOne(gs[i]));
    return {kind:'repeated', goals:out};
  }
  return {kind:'single', goals:[readOne(slot)]};  // single QuestGoalProto branch
}

// ---- decode one QuestRewardProto via accessors (offset-free) ----
function decodeReward(rp) {
  var rec={cls:clsName(rp)};
  var rc=inv0(rp,'get_RewardCase'); if(rc.ok) rec.caseInt=box32(rc.ret);
  var pe=inv0(rp,'get_PokemonEncounter');
  if(pe.ok&&pe.ret&&!pe.ret.isNull()){ var enc=pe.ret; rec.type='POKEMON_ENCOUNTER';
    var id=inv0(enc,'get_PokemonId'); if(id.ok) rec.pid=box32(id.ret);
    var dr=inv0(enc,'get_PokemonDisplay');
    if(dr.ok&&dr.ret&&!dr.ret.isNull()){ var d=dr.ret;
      var f=inv0(d,'get_Form'); if(f.ok) rec.form=box32(f.ret);
      var c=inv0(d,'get_Costume'); if(c.ok) rec.costume=box32(c.ret);
      var g=inv0(d,'get_Gender'); if(g.ok) rec.gender=box32(g.ret);
      var s=inv0(d,'get_Shiny'); if(s.ok) rec.shiny=box32(s.ret);
      var al=inv0(d,'get_Alignment'); if(al.ok) rec.alignment=box32(al.ret); }
    var sp=inv0(enc,'get_ShinyProbability'); if(sp.ok) rec.shinyProb=boxF(sp.ret);
    var ft=inv0(enc,'get_IsFeaturedPokemon'); if(ft.ok) rec.featured=box32(ft.ret);
    return rec; }
  var mr=inv0(rp,'get_MegaResource'); if(!(mr.ok&&mr.ret&&!mr.ret.isNull())) mr=inv0(rp,'get_TempEvoResource');
  if(mr.ok&&mr.ret&&!mr.ret.isNull()){ rec.type='MEGA_ENERGY'; var wrap=mr.ret; rec.wrapCls=clsName(wrap);
    var inner=null; var nm=['get_TempEvoResource','get_Resource','get_TemporaryEvolutionResource','get_MegaResource'];
    for(var n=0;n<nm.length;n++){ var t=inv0(wrap,nm[n]); if(t.ok&&t.ret&&!t.ret.isNull()){ inner=t.ret; rec.innerGetter=nm[n]; break; } }
    var src=inner||wrap;
    var pid=inv0(src,'get_PokemonId'); if(pid.ok) rec.pid=box32(pid.ret);
    var te=inv0(src,'get_TemporaryEvolutionId'); if(te.ok) rec.tempEvoId=box32(te.ret);
    var am=inv0(src,'get_Amount'); if(!(am.ok&&am.ret&&!am.ret.isNull())) am=inv0(src,'get_MaxEnergyCount');
    if(am.ok) rec.amount=box32(am.ret); return rec; }
  var it=inv0(rp,'get_Item');
  if(it.ok&&it.ret&&!it.ret.isNull()){ rec.type='ITEM';
    var im=inv0(it.ret,'get_Item'); if(im.ok) rec.itemId=box32(im.ret);
    var ct=inv0(it.ret,'get_Count'); if(!(ct.ok&&ct.ret&&!ct.ret.isNull())) ct=inv0(it.ret,'get_Amount');
    if(ct.ok) rec.count=box32(ct.ret); return rec; }
  var ca=inv0(rp,'get_Candy'); if(!(ca.ok&&ca.ret&&!ca.ret.isNull())) ca=inv0(rp,'get_PokemonCandy');
  if(ca.ok&&ca.ret&&!ca.ret.isNull()){ rec.type='CANDY';
    var cp=inv0(ca.ret,'get_PokemonId'); if(cp.ok) rec.pid=box32(cp.ret);
    var cam=inv0(ca.ret,'get_Amount'); if(cam.ok) rec.amount=box32(cam.ret); return rec; }
  var eg=inv0(rp,'get_PokemonEgg'); if(eg.ok&&eg.ret&&!eg.ret.isNull()){ rec.type='EGG'; return rec; }
  var sd=inv0(rp,'get_Stardust'); var sv=sd.ok?box32(sd.ret):null; if(sv){ rec.type='STARDUST'; rec.amount=sv; return rec; }
  var xp=inv0(rp,'get_Exp'); var xv=xp.ok?box32(xp.ret):null; if(xv){ rec.type='EXP'; rec.amount=xv; return rec; }
  var pc=inv0(rp,'get_Pokecoin'); var pcv=pc.ok?box32(pc.ret):null; if(pcv){ rec.type='POKECOIN'; rec.amount=pcv; return rec; }
  var lc=inv0(rp,'get_LevelCap'); var lcv=lc.ok?box32(lc.ret):null; if(lcv){ rec.type='LEVEL_CAP'; rec.amount=lcv; return rec; }
  var fp=inv0(rp,'get_FriendshipPoints'); var fpv=fp.ok?box32(fp.ret):null; if(fpv){ rec.type='FRIENDSHIP'; rec.amount=fpv; return rec; }
  rec.type='UNKNOWN'; return rec;
}

// ---- reward RepeatedField off a QuestProto (try both getter names) ----
function readRewards(qp) {
  var rf=null, used=null;
  var a=inv0(qp,'get_QuestRewards'); if(a.ok&&a.ret&&!a.ret.isNull()){ rf=a.ret; used='get_QuestRewards'; }
  else { var b=inv0(qp,'get_Rewards'); if(b.ok&&b.ret&&!b.ret.isNull()){ rf=b.ret; used='get_Rewards'; } }
  var out=[]; if(rf){ var rps=rfRefs(rf,40); for(var i=0;i<rps.length;i++) if(!rps[i].isNull()) out.push(decodeReward(rps[i])); }
  return {used:used, rewards:out};
}

// ---- I18n.Text(key) ----
function tr(i18nPtr, key) {
  if(!key) return ''; try{ var m=cMN(OGC(i18nPtr),'Text',1); if(!m||m.isNull()) return key;
    var arg=Memory.alloc(8); arg.writePointer(strNew(key)); var ex=Memory.alloc(8); ex.writePointer(ptr(0));
    var r=rI(m,i18nPtr,arg,ex); return (r&&!r.isNull())?(rdStr(r)||key):key; }catch(e){ return key; }
}

// ---- display proto (title/desc/sub-step text) via GetQuestDisplayProto(questId) ----
function readDisplay(qsPtr, i18nPtr, questIdStr) {
  var rec={};
  try{ var m=cMN(OGC(qsPtr),'GetQuestDisplayProto',1); if(!m||m.isNull()) return rec;
    var arg=Memory.alloc(8); arg.writePointer(strNew(questIdStr)); var ex=Memory.alloc(8); ex.writePointer(ptr(0));
    var dp=rI(m,qsPtr,arg,ex); if(!dp||dp.isNull()) return rec;
    rec.title=tr(i18nPtr, rdStr(dp.add(0x28).readPointer()));
    rec.desc =tr(i18nPtr, rdStr(dp.add(0x20).readPointer()));
    var sr=dp.add(0x38).readPointer(); if(sr&&!sr.isNull()){ var subs=rfRefs(sr,20); rec.subTasks=[];
      for(var i=0;i<subs.length;i++){ if(subs[i].isNull()) continue; rec.subTasks.push(tr(i18nPtr, rdStr(subs[i].add(0x28).readPointer()))); } }
  }catch(e){ rec.dispErr=e.toString(); }
  return rec;
}

rpc.exports.readResearch = function(qsAddr, i18nAddr, doProbe) {
  _proto();
  var qs=ptr(qsAddr), i18n=i18nAddr?ptr(i18nAddr):ptr(0);
  var gp=inv0(qs,'get_QuestsProto'); if(!(gp.ok&&gp.ret&&!gp.ret.isNull())) return {error:'null QuestsProto (open Research screen)'};
  var po=gp.ret;
  var active=rfRefs(po.add(0x10).readPointer(), 400);
  // completedIds (RepeatedField<String> @ +0x18)
  var completed=[]; (function(){ var rf=po.add(0x18).readPointer(); if(rf&&!rf.isNull()){ var arr=rf.add(0x10).readPointer(); var cnt=rf.add(0x18).readS32();
    if(arr&&!arr.isNull()&&cnt>0) for(var i=0;i<Math.min(cnt,2000);i++) completed.push(rdStr(arr.add(0x20).add(i*8).readPointer())); } })();
  // second list probe (+0x20): classify element + sample ids at +0x10/+0x18/+0x28/+0x40
  var second=null; (function(){ try{ var rf=po.add(0x20).readPointer(); if(!rf||rf.isNull()) return;
    var arr=rf.add(0x10).readPointer(); var cnt=rf.add(0x18).readS32(); if(!arr||arr.isNull()||cnt<=0) return;
    var e0=arr.add(0x20).readPointer(); var samp={count:cnt, elemCls:clsName(e0)};
    [0x10,0x18,0x28,0x40].forEach(function(off){ try{ samp['str@'+off]=rdStr(e0.add(off).readPointer()); }catch(e){} });
    second=samp; }catch(e){ second={err:e.toString()}; } })();

  var rewardGetterUsed=null, probeBlock=null, out=[];
  function decodeQuest(qp, depth) {
    var rec={ questType:qp.add(0x10).readS32(), questId:rdStr(qp.add(0x28).readPointer()),
              templateId:rdStr(qp.add(0x40).readPointer()), progress:qp.add(0x48).readS32(),
              status:qp.add(0x58).readS32(), createdMs:qp.add(0x68).readS64().toString(),
              completionMs:qp.add(0x78).readS64().toString(), endMs:qp.add(0xb0).readS64().toString() };
    rec.goals=readGoals(qp);
    var rr=readRewards(qp); if(rr.used) rewardGetterUsed=rr.used; rec.rewards=rr.rewards;
    var disp=readDisplay(qs, i18n, rec.questId); for(var k in disp) rec[k]=disp[k];
    // MultiPart sub-quests
    if(depth<1){ var mp=inv0(qp,'get_MultiPart');
      if(mp.ok&&mp.ret&&!mp.ret.isNull()){ var sq=mp.ret.add(0x10).readPointer(); var subs=rfRefs(sq,60);
        rec.subQuests=[]; for(var s=0;s<subs.length;s++) if(!subs[s].isNull()) rec.subQuests.push(decodeQuest(subs[s], depth+1)); } }
    return rec;
  }
  for(var i=0;i<active.length;i++){ var qp=active[i]; if(qp.isNull()) continue; out.push(decodeQuest(qp,0));
    if(doProbe && !probeBlock){ var rr=readRewards(qp);  // raw oneof dump on first quest WITH rewards
      if(rr.rewards.length){ // re-fetch first reward ptr for raw getter sweep
        var rf=null; var a=inv0(qp,'get_QuestRewards'); if(a.ok&&a.ret&&!a.ret.isNull()) rf=a.ret; else { var b=inv0(qp,'get_Rewards'); if(b.ok&&b.ret&&!b.ret.isNull()) rf=b.ret; }
        if(rf){ var r0=rfRefs(rf,1); if(r0.length&&!r0[0].isNull()){ var rp0=r0[0]; var pb={rewardCls:clsName(rp0), getters:{}};
          ['get_RewardCase','get_PokemonEncounter','get_MegaResource','get_TempEvoResource','get_Item','get_Stardust','get_Candy','get_Exp','get_Pokecoin','get_PokemonEgg','get_LevelCap','get_LootTable','get_FriendshipPoints'].forEach(function(gn){
            var rr2=inv0(rp0,gn); pb.getters[gn]=(rr2.ok&&rr2.ret&&!rr2.ret.isNull())?('ptr cls='+clsName(rr2.ret)+' box32='+box32(rr2.ret)):'null'; });
          probeBlock=pb; } } }
    }
  }
  return { questCount:active.length, rewardGetterUsed:rewardGetterUsed, active:out,
           completedIds:completed, secondListProbe:second, probe:probeBlock };
};
"""


def main():
    print('[*] connecting (Tailscale 100.98.158.56:5555)...')
    sess, pid = pg.get_session()
    print(f'[*] attached pid={pid}')

    # capture singletons via hook
    hs = sess.create_script(pg.JS_PREAMBLE + '\n' + HOOK_JS)
    hs.on('message', lambda m, d: None)
    hs.load()
    hs.exports_sync.hook_setup()
    print('[*] Open the Today/Research screen so QuestService + I18n fire (up to 60s)...')
    q = i = None
    for _ in range(60):
        time.sleep(1)
        g = hs.exports_sync.hook_get()
        if g.get('q'):
            q = g['q']
        if g.get('i'):
            i = g['i']
        if q and i:
            break
    hs.unload()
    if not q:
        print('[!] NO QuestService instance captured. Interact with the Research UI and retry.')
        sess.detach()
        sys.exit(1)
    if not i:
        print('[!] WARNING: no I18n instance — titles will show raw i18n keys.')
    print(f'[*] QuestService={q}  I18n={i}')

    sc = pg.get_script_with_helpers(sess, READER_JS)
    res = sc.exports_sync.read_research(q, i or '0', PROBE)
    sc.unload()
    sess.detach()

    if 'error' in res:
        print('[!]', res['error'])
        sys.exit(1)

    print(f"\n=== ACTIVE RESEARCH ({res['questCount']}) ===")
    print(f"[reward list getter in use: {res.get('rewardGetterUsed')}]")
    KEY = ('GOFEST', 'MEWTWO', 'IRL_CITY', 'DISTRICT', 'TOKYO', 'APAC', 'WAINA', '2026')

    def show_quest(q, indent='  '):
        flag = '  <<<' if any(k in (q.get('templateId') or '').upper() for k in KEY) else ''
        gtxt = ''
        gs = q.get('goals', {})
        if gs.get('goals'):
            tgts = [str(g.get('target')) for g in gs['goals'] if g.get('target') is not None]
            if tgts:
                gtxt = ' target=' + '/'.join(tgts)
        print(f"{indent}[{STATUS.get(q['status'], q['status'])}] type={q['questType']} prog={q['progress']}{gtxt} {q['templateId']}{flag}")
        if q.get('title'):
            print(f"{indent}    title: {q['title']}")
        if q.get('desc') and q['desc'] != q.get('title'):
            print(f"{indent}    desc:  {q['desc']}")
        for st in q.get('subTasks', []) or []:
            print(f"{indent}    step:  {st}")
        for rw in q.get('rewards', []) or []:
            t = rw.get('type')
            if t == 'POKEMON_ENCOUNTER':
                ex = []
                if rw.get('form'):
                    ex.append(f"form={rw['form']}")
                if rw.get('shiny'):
                    ex.append('SHINY')
                if rw.get('shinyProb'):
                    ex.append(f"shinyP={rw['shinyProb']}")
                if rw.get('featured'):
                    ex.append('FEATURED')
                print(f"{indent}    REWARD ENCOUNTER pid={rw.get('pid')} {' '.join(ex)}")
            elif t == 'MEGA_ENERGY':
                print(f"{indent}    REWARD MEGA_ENERGY pid={rw.get('pid')} tevo={TEVO.get(rw.get('tempEvoId'), rw.get('tempEvoId'))} amt={rw.get('amount')}")
            elif t == 'ITEM':
                print(f"{indent}    REWARD ITEM id={rw.get('itemId')} x{rw.get('count')}")
            else:
                print(f"{indent}    REWARD {t} {json.dumps({k: v for k, v in rw.items() if k not in ('cls', 'type', 'wrapCls', 'caseInt')})}")
        for sq in q.get('subQuests', []) or []:
            show_quest(sq, indent + '    ')

    for q in res['active']:
        show_quest(q)

    if res.get('probe'):
        print('\n--- PROBE: raw oneof getters on quest#0 reward#0 (lock RewardOneofCase int map) ---')
        print(json.dumps(res['probe'], indent=2))

    print('\n--- secondListProbe (QuestsProto+0x20 element class) [DEVICE] ---')
    print(json.dumps(res.get('secondListProbe'), indent=2))

    print(f"\n=== completedIds ({len(res['completedIds'])}) — event-relevant ===")
    for c in res['completedIds']:
        if any(k in c.upper() for k in KEY):
            print('  ', c)

    if JSON_OUT:
        with open(JSON_OUT, 'w', encoding='utf-8') as fh:
            json.dump(res, fh, indent=2)
        print(f"\n[*] wrote {JSON_OUT}")
    print('\n[NOTE] TEMP_EVOLUTION ordinals + reward getter name are [DEVICE]-flagged; verify vs --probe.')


if __name__ == '__main__':
    main()
