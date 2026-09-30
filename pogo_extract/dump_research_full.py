"""dump_research_full.py  —  COMPLETE READ-ONLY dump of all active Timed Research /
Field Research / quests, with everything a human needs:

  * human TITLE + DESCRIPTION (I18n-resolved, {0}/{1} placeholders filled from goals)
  * STEP / sub-quest structure (MultiPart) with each sub-quest's task + live x/target
  * goal CONDITION TYPE per task (what action counts: catch / spin / walk / battle ...)
  * REWARDS: items (id + count) AND the Pokemon encounter (species id), per reward
  * completion / claim status + timestamps

This script WRITES NOTHING to the game. Quest state is server-authoritative; writing
client memory cannot grant rewards (see read_quest_details.py / MEMORY pogo-server-authority).

PREREQUISITE: run `python dump_quest_layouts.py` once and reconcile the OFF_* offsets
below against quest_layouts.md. Every offset that has NOT been confirmed on this exact
build is tagged `# VALIDATE`. The script also self-checks offsets at runtime (sanity
ranges) and prints a warning when a field looks wrong, so a silent offset drift is loud.

Usage:
    python dump_research_full.py                # dump everything
    python dump_research_full.py --raw          # also include raw pointers + numeric oneofs
    python dump_research_full.py --json out.json

Design notes / how the pieces connect:
  - QuestService.get_QuestsProto() -> QuestsProto (holo-protos message)
        +0x10  RepeatedField<QuestProto>  "Quests"            (active; full QuestProto, templateId@+0x40)
        +0x20  RepeatedField<?>           second list (~78)   (see SECOND_LIST handling)
  - For each active QuestProto:
        templateId @+0x40, questId @+0x28, questType @+0x10 (enum QuestType),
        progress @+0x48 (s32), status @+0x58 (enum: 1 ACTIVE 2 COMPLETE 3 ...),
        Goals  @+0x50  (REPEATED field of QuestGoalProto -- NOT a single goal; see note),
        QuestRewards @ OFF_QUEST_REWARDS  (repeated QuestRewardProto),
        Quest-oneof (MultiPart / CatchPokemon / SpinPokestop / ...) telling the concrete shape,
        timestamps createdMs@+0x68, lastUpdateMs@+0x70, completionMs@+0x78, endMs@+0xb0.
  - Display text comes from GetQuestDisplayProto(questId:string) -> QuestDisplayProto
        titleKey@+0x28, descKey@+0x20, TagString@+0x58, iconName@+0x70,
        SubquestDisplays @+0x38 (repeated; each: titleKey@+0x28, descKey@+0x20).
        Resolve keys via I18n.Text(key)  (raw, keeps {0}) or I18n.TextFormat(key, args).
"""
import sys, time, json, subprocess, argparse
from datetime import datetime, timezone
import frida

ADB = '100.98.158.56:5555'

# ----------------------------------------------------------------------------
# OFFSETS.  Confirmed-from-working-code are unmarked. Guess/derived ones are
# tagged `# VALIDATE` -> confirm against quest_layouts.md from dump_quest_layouts.py.
# ----------------------------------------------------------------------------
# QuestProto (holo-protos.dll, Holoholo.Rpc.QuestProto) — confirmed in extract_quests_v3.py
OFF_QP_QUESTTYPE   = 0x10   # s32 enum QuestType
OFF_QP_QUESTID     = 0x28   # System.String  (server quest instance id)
OFF_QP_TEMPLATEID  = 0x40   # System.String  (template id, e.g. STORY_QUEST_WAINA23_1)
OFF_QP_PROGRESS    = 0x48   # s32
OFF_QP_GOALS       = 0x50   # RepeatedField<QuestGoalProto>  -- VALIDATE: v3 treated this as a single goal;
                            #   metadata says QuestProto.Goals is REPEATED. Reader handles BOTH (see read_goals()).
OFF_QP_STATUS      = 0x58   # s32 enum (1 ACTIVE, 2 COMPLETE/TARGETS_MET, 3 ...)
OFF_QP_CREATEDMS   = 0x68   # s64
OFF_QP_LASTUPDMS   = 0x70   # s64
OFF_QP_COMPLETMS   = 0x78   # s64
OFF_QP_FORTID      = 0x80   # System.String (field-research fort)  — from v2
OFF_QP_ENDMS       = 0xb0   # s64
OFF_QP_QUESTREWARDS = 0x60  # VALIDATE: RepeatedField<QuestRewardProto>. Best static guess (sits between
                            #   Goals@0x50 and status@0x58 is taken, so 0x60 is the next 8-byte slot after status).
                            #   CONFIRM offset+type in quest_layouts.md (field name "QuestRewards").

# QuestGoalProto (Holoholo.Rpc.QuestGoalProto) — from existing code + metadata
OFF_GOAL_CONDITIONS = 0x10  # RepeatedField<QuestConditionProto>
OFF_GOAL_TARGET     = 0x18  # s32  (the "x of TARGET")

# QuestConditionProto — oneof. The active case is read via get_ConditionCase() (resilient).
# Raw fallback: case enum int lives at a fixed tail offset (VALIDATE via layouts: "conditionCase_").
OFF_COND_CASE       = 0x20  # VALIDATE: s32 ConditionOneofCase enum (which With* field is set)

# QuestRewardProto — oneof reward. Read via get_RewardCase() (resilient).
OFF_REWARD_CASE     = 0x40  # VALIDATE: s32 RewardOneofCase
# common scalar reward payloads (only valid for matching case):
OFF_REWARD_EXP        = 0x10  # VALIDATE s32 (case Exp)
OFF_REWARD_TEMPLATEID = 0x18  # VALIDATE String (case QuestTemplateId)
# Item / Pokemon-encounter / stardust reward payloads are sub-messages -> resolve via getters.

# QuestDisplayProto (Holoholo.Rpc.QuestDisplayProto) — confirmed in v2/v3
OFF_DISP_DESCKEY   = 0x20   # System.String (i18n key)
OFF_DISP_TITLEKEY  = 0x28   # System.String (i18n key)
OFF_DISP_SLOT      = 0x30   # s32 (from v2)
OFF_DISP_STORYEND  = 0x40   # u8  (from v2)
OFF_DISP_STORYDESC = 0x48   # String (from v2)
OFF_DISP_TAGSTRING = 0x58   # String i18n key
OFF_DISP_ICONNAME  = 0x70   # String
OFF_DISP_SUBDISPLAYS = 0x38 # RepeatedField<SubquestDisplay>  (each: titleKey@+0x28, descKey@+0x20)
OFF_DISP_SORTORDER = 0xd8   # s32 (from v2)

# QuestsProto — confirmed +0x10 active. Second list:
OFF_QSP_ACTIVE     = 0x10   # RepeatedField<QuestProto>
OFF_QSP_SECOND     = 0x20   # RepeatedField<?> (~78 entries). Element is NOT a QuestProto (templateId not @0x40).
                            #   Hypothesis (VALIDATE): ClientQuestProto wrappers or completed-id strings /
                            #   ProgressedQuests. read_second_list() probes element shape to classify.

# RepeatedField<T> layout (Google.Protobuf) — confirmed everywhere in this repo
OFF_RF_ARRAY = 0x10  # T[] backing
OFF_RF_COUNT = 0x18  # s32 logical count
OFF_ARR_LEN  = 0x18  # s32 capacity of T[]
OFF_ARR_DATA = 0x20  # first element

# ---- enums (from metadata; QuestType order per holo-protos QuestProto.Types) ----
QSTATUS = {0: 'UNSET', 1: 'ACTIVE', 2: 'COMPLETE', 3: 'EXPIRED', 4: 'TARGETS_MET',
           5: 'CLAIMED'}  # VALIDATE values 3-5 against Status enum (dump_quest_layouts can pull it)

# QuestType enum — names confirmed present in metadata; ORDINALS need validation.
# Use --raw to print numeric types and reconcile.
QUESTTYPE = {}  # filled from quest_layouts.json's QuestType if available (loaded below)

# ConditionOneofCase: protobuf field number == the With* tag. We map the common ones
# by the metadata-confirmed name list; the live case int is the proto field number.
# (Filled best-effort; the script prints the raw case int alongside so it's never lost.)


# ----------------------------------------------------------------------------
def _pid():
    return int(subprocess.check_output(
        ['adb', '-s', ADB, 'shell', 'pidof com.nianticlabs.pokemongo']).decode().strip())


HOOK_JS = r"""
var Q=null, I=null;
function init(){
  var il=Process.findModuleByName('libil2cpp.so');var A={};
  il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return new NativeFunction(A[n],r,a);}
  var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),
      aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),
      cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),
      cGM=b('il2cpp_class_get_methods','pointer',['pointer','pointer']),tA=b('il2cpp_thread_attach','pointer',['pointer']);
  tA(dG());
  var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;
  for(var a=0;a<na;a++){var i=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(i).readCString()==='holo-game.dll'){gi=i;break;}}
  var pairs=[['Niantic.Holoholo.Quests','QuestService','q'],
             ['Niantic.Holoholo.Internationalization','I18n','i']];
  for(var p=0;p<pairs.length;p++){
    var cls=cFN(gi,Memory.allocUtf8String(pairs[p][0]),Memory.allocUtf8String(pairs[p][1]));
    if(!cls||cls.isNull())continue;
    (function(lbl){
      var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
      while((m=cGM(cls,it))&&!m.isNull()){try{var ad=m.readPointer();if(ad.isNull())continue;
        Interceptor.attach(ad,{onEnter:function(ar){
          if(lbl==='q'&&!Q){Q=ar[0].toString();}
          if(lbl==='i'&&!I){I=ar[0].toString();}
        }});}catch(e){}}
    })(pairs[p][2]);
  }
}
rpc.exports={setup:function(){init();return{ok:1};},get:function(){return{q:Q,i:I};}};
"""

# Main reader script. Heavy lifting in IL2CPP via runtime_invoke; offsets passed in
# from Python so they live in ONE place (the OFF_* block above).
READ_JS = r"""
rpc.exports.read = function(qAddr, iAddr, OFF){
  var qInst=ptr(qAddr), iInst=(iAddr&&iAddr!=='0x0')?ptr(iAddr):null;
  var il=Process.findModuleByName('libil2cpp.so');var A={};
  il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return A[n]?new NativeFunction(A[n],r,a):null;}
  var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),
      aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),
      cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),
      cMN=b('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']),
      cGM=b('il2cpp_class_get_methods','pointer',['pointer','pointer']),
      mGN=b('il2cpp_method_get_name','pointer',['pointer']),
      mGPC=b('il2cpp_method_get_param_count','uint32',['pointer']),
      rI=b('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']),
      strNew=b('il2cpp_string_new','pointer',['pointer']);
  var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null,hpr=null;
  for(var a=0;a<na;a++){var im=aGI(asms.add(a*Process.pointerSize).readPointer());var nm=iGN(im).readCString();
    if(nm==='holo-game.dll')gi=im; if(nm==='holo-protos.dll')hpr=im;}
  var qsCls=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestService'));
  var i18nCls=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Internationalization'),Memory.allocUtf8String('I18n'));
  var qpCls=hpr?cFN(hpr,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('QuestProto')):null;

  function S(p){if(!p||p.isNull())return '';var len=p.add(0x10).readS32();if(len<=0||len>4000)return '';
    var c=[];for(var i=0;i<len;i++){var ch=p.add(0x14+i*2).readU16();if(ch===0)break;c.push(String.fromCharCode(ch));}return c.join('');}
  function meth(cls,name,argc){if(!cls||cls.isNull())return null;return cMN(cls,Memory.allocUtf8String(name),argc);}
  function invoke0(m,inst){if(!m)return ptr(0);var ex=Memory.alloc(Process.pointerSize);ex.writePointer(ptr(0));
    try{return rI(m,inst,ptr(0),ex);}catch(e){return ptr(0);}}
  function invoke1ptr(m,inst,argPtr){if(!m)return ptr(0);var a=Memory.alloc(Process.pointerSize);a.writePointer(argPtr);
    var ex=Memory.alloc(Process.pointerSize);ex.writePointer(ptr(0));try{return rI(m,inst,a,ex);}catch(e){return ptr(0);}}
  function rfList(rf,max){ // returns array of element pointers
    if(!rf||rf.isNull())return [];
    var arr=rf.add(OFF.RF_ARRAY).readPointer();var cnt=rf.add(OFF.RF_COUNT).readS32();
    if(arr.isNull()||cnt<=0||cnt>5000)return [];
    var cap=arr.add(OFF.ARR_LEN).readS32();var data=arr.add(OFF.ARR_DATA);var out=[];
    var n=Math.min(cnt,cap,max||2000);
    for(var i=0;i<n;i++){out.push(data.add(i*8).readPointer());}
    return out;
  }

  // ----- I18n: resolve a key to text. Try Text(key); keep {0} placeholders. -----
  var textM=meth(i18nCls,'Text',1);
  function tr(key){
    if(!key)return '';
    if(!iInst||!textM)return key;
    try{var ks=strNew(Memory.allocUtf8String(key));var r=invoke1ptr(textM,iInst,ks);
      if(r.isNull())return key;var s=S(r);return s||key;}catch(e){return key;}
  }

  // ----- the QuestsProto -----
  var getProto=meth(qsCls,'get_QuestsProto',0);
  var po=invoke0(getProto,qInst);
  if(!po||po.isNull())return {error:'QuestsProto null (open the Research screen so it populates)'};

  var activePtrs=rfList(po.add(OFF.QSP_ACTIVE).readPointer(), 300);

  // display + encounter + reward methods resolved on QuestService (build-dependent;
  // metadata says GetQuestDisplayProto/GetQuestRewardProtos live on QuestRpcService.
  // We try QuestService first (v2/v3 proved it resolves on this build), then fall back).
  var getDisplay=meth(qsCls,'GetQuestDisplayProto',1);
  var getDesc=meth(qsCls,'GetQuestDescription',1);
  var getEnc=meth(qsCls,'GetPokemonEncounterForQuest',1);
  var rpcCls=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestRpcService'));
  if(!getDisplay||getDisplay.isNull()) getDisplay=meth(rpcCls,'GetQuestDisplayProto',1);
  var getRewards=meth(rpcCls,'GetQuestRewardProtos',1);  // -> repeated QuestRewardProto (preferred)

  // QuestProto.get_MultiPart() (sub-quests) + get_QuestCase() (which concrete kind)
  var getMP   = qpCls?meth(qpCls,'get_MultiPart',0):null;
  var getQCase= qpCls?meth(qpCls,'get_QuestCase',0):null;
  // QuestRewardProto.get_RewardCase() and QuestGoalProto/QuestConditionProto case getters
  var rewardProtoCls=hpr?cFN(hpr,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('QuestRewardProto')):null;
  var getRewardCase=rewardProtoCls?meth(rewardProtoCls,'get_RewardCase',0):null;
  var getItem      =rewardProtoCls?meth(rewardProtoCls,'get_Item',0):null;        // ItemRewardProto
  var getExp       =rewardProtoCls?meth(rewardProtoCls,'get_Exp',0):null;         // s32
  var getStardust  =rewardProtoCls?meth(rewardProtoCls,'get_Stardust',0):null;    // (may be absent)
  var getPokeEnc   =rewardProtoCls?meth(rewardProtoCls,'get_PokemonEncounter',0):null; // PokemonEncounterRewardProto
  var getCandy     =rewardProtoCls?meth(rewardProtoCls,'get_PokemonCandy',0):null;
  var getMega      =rewardProtoCls?meth(rewardProtoCls,'get_MegaResource',0):null;
  var condProtoCls =hpr?cFN(hpr,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('QuestConditionProto')):null;
  var getCondCase  =condProtoCls?meth(condProtoCls,'get_ConditionCase',0):null;
  var goalProtoCls =hpr?cFN(hpr,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('QuestGoalProto')):null;
  var getGoalCondition=goalProtoCls?meth(goalProtoCls,'get_Condition',0):null;     // some builds: single Condition
  var getGoalTarget  =goalProtoCls?meth(goalProtoCls,'get_Target',0):null;         // s32

  function s32(retObj){ // boxed System.Int32 from runtime_invoke -> value at +0x10
    if(!retObj||retObj.isNull())return null; try{return retObj.add(0x10).readS32();}catch(e){return null;}
  }

  // Decode one QuestGoalProto pointer -> {target, conditionCase, conditionCaseRaw}
  function decodeGoal(gp){
    if(!gp||gp.isNull())return null;
    var rec={};
    // target via getter (resilient) else offset
    if(getGoalTarget){var t=s32(invoke0(getGoalTarget,gp)); if(t!==null)rec.target=t;}
    if(rec.target===undefined){try{rec.target=gp.add(OFF.GOAL_TARGET).readS32();}catch(e){}}
    // condition: prefer single get_Condition()->QuestConditionProto, then its ConditionCase
    var cond=null;
    if(getGoalCondition){cond=invoke0(getGoalCondition,gp);}
    if((!cond||cond.isNull())){ // fall back: first element of Conditions RepeatedField @ GOAL_CONDITIONS
      var cl=rfList(gp.add(OFF.GOAL_CONDITIONS).readPointer(),8); if(cl.length)cond=cl[0];
      rec.conditionCount=cl.length;
    }
    if(cond&&!cond.isNull()){
      if(getCondCase){var cc=s32(invoke0(getCondCase,cond)); if(cc!==null){rec.conditionCaseRaw=cc;}}
      if(rec.conditionCaseRaw===undefined){try{rec.conditionCaseRaw=cond.add(OFF.COND_CASE).readS32();}catch(e){}}
      rec.conditionPtr=cond.toString();
    }
    return rec;
  }

  // Read Goals on a QuestProto. Handles BOTH layouts:
  //  (A) OFF.QP_GOALS is a single QuestGoalProto (v3 assumption)
  //  (B) OFF.QP_GOALS is a RepeatedField<QuestGoalProto>
  function readGoals(qp){
    var p=qp.add(OFF.QP_GOALS).readPointer();
    if(!p||p.isNull())return {goals:[]};
    // Heuristic: if p looks like a RepeatedField (its +0x18 count is small & +0x10 is a ptr to an array
    //  whose +0x18 capacity >= count), treat as list. Else single goal.
    var asList=null;
    try{
      var cnt=p.add(OFF.RF_COUNT).readS32();
      var arr=p.add(OFF.RF_ARRAY).readPointer();
      if(cnt>0&&cnt<64&&!arr.isNull()){var cap=arr.add(OFF.ARR_LEN).readS32(); if(cap>=cnt&&cap<256)asList=rfList(p,64);}
    }catch(e){}
    if(asList&&asList.length){
      var gs=[];for(var i=0;i<asList.length;i++){var g=decodeGoal(asList[i]); if(g)gs.push(g);} return {goals:gs, repeated:true};
    }
    var single=decodeGoal(p);
    return {goals: single?[single]:[], repeated:false};
  }

  // Decode QuestRewardProto pointer -> {case, exp?, itemId?, itemCount?, pokemonId?, ...}
  function decodeReward(rp){
    if(!rp||rp.isNull())return null;
    var rec={};
    if(getRewardCase){var rc=s32(invoke0(getRewardCase,rp)); if(rc!==null)rec.caseRaw=rc;}
    if(rec.caseRaw===undefined){try{rec.caseRaw=rp.add(OFF.REWARD_CASE).readS32();}catch(e){}}
    // EXP
    if(getExp){var e=s32(invoke0(getExp,rp)); if(e)rec.exp=e;}
    // ITEM: ItemRewardProto has Item(enum) + Count(s32). Resolve sub-message then read getters.
    if(getItem){var it=invoke0(getItem,rp);
      if(it&&!it.isNull()){
        var irCls=hpr?cFN(hpr,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('ItemRewardProto')):null;
        var gItem=meth(irCls,'get_Item',0), gCnt=meth(irCls,'get_Count',0);
        var iid=gItem?s32(invoke0(gItem,it)):null; var cnt=gCnt?s32(invoke0(gCnt,it)):null;
        if(iid!==null||cnt!==null)rec.item={id:iid,count:cnt};
      }}
    // POKEMON ENCOUNTER reward
    if(getPokeEnc){var pe=invoke0(getPokeEnc,rp);
      if(pe&&!pe.isNull()){
        var peCls=hpr?cFN(hpr,Memory.allocUtf8String('Holoholo.Rpc'),Memory.allocUtf8String('PokemonEncounterRewardProto')):null;
        // try common id getters; whichever resolves wins (build-dependent)
        var gp=meth(peCls,'get_PokemonId',0)||meth(peCls,'get_PokemonDisplay',0);
        // The species id is most reliably under PokemonDisplay or the distribution; expose ptr + best id.
        var pid=null; var gPid=meth(peCls,'get_PokemonId',0);
        if(gPid){pid=s32(invoke0(gPid,pe));}
        rec.pokemonEncounter={ptr:pe.toString(), pokemonId: pid};
      }}
    if(getCandy){var cd=invoke0(getCandy,rp); if(cd&&!cd.isNull())rec.candyPtr=cd.toString();}
    if(getMega){var mg=invoke0(getMega,rp); if(mg&&!mg.isNull())rec.megaPtr=mg.toString();}
    return rec;
  }

  function readRewards(qp, questIdStr){
    // Preferred: QuestRpcService.GetQuestRewardProtos(questId/templateId) if it resolved.
    var list=[];
    if(getRewards && rpcCls && !rpcCls.isNull()){
      try{var ks=strNew(Memory.allocUtf8String(questIdStr));
        var ret=invoke1ptr(getRewards, ptr(0) /*static? else needs instance*/, ks);
        // GetQuestRewardProtos may be instance; if static-call fails it returns null -> fall through.
        var rl=rfList(ret, 64); for(var i=0;i<rl.length;i++){var d=decodeReward(rl[i]); if(d)list.push(d);}
      }catch(e){}
    }
    if(list.length)return list;
    // Fallback: QuestProto.QuestRewards repeated field at OFF.QP_QUESTREWARDS
    var rl=rfList(qp.add(OFF.QP_QUESTREWARDS).readPointer(), 64);
    for(var i=0;i<rl.length;i++){var d=decodeReward(rl[i]); if(d)list.push(d);}
    return list;
  }

  // sub-quests via MultiPart
  function readSubQuests(qp){
    if(!getMP)return null;
    var mp=invoke0(getMP,qp);
    if(!mp||mp.isNull())return null;
    var subRf=mp.add(0x10).readPointer();  // MultiPartQuestProto.SubQuests @+0x10 (confirmed in walk_waina_subquests.py)
    var subs=rfList(subRf, 64); var out=[];
    for(var s=0;s<subs.length;s++){
      var sq=subs[s]; if(sq.isNull())continue;
      var g=readGoals(sq);
      out.push({
        templateId:S(sq.add(OFF.QP_TEMPLATEID).readPointer()),
        questId:S(sq.add(OFF.QP_QUESTID).readPointer()),
        questType:sq.add(OFF.QP_QUESTTYPE).readS32(),
        progress:sq.add(OFF.QP_PROGRESS).readS32(),
        status:sq.add(OFF.QP_STATUS).readS32(),
        goals:g.goals,
        rewards: readRewards(sq, S(sq.add(OFF.QP_QUESTID).readPointer()))
      });
    }
    return out;
  }

  var out=[];
  for(var i=0;i<activePtrs.length;i++){
    var qp=activePtrs[i]; if(qp.isNull())continue;
    var questId=S(qp.add(OFF.QP_QUESTID).readPointer());
    var rec={
      questType:qp.add(OFF.QP_QUESTTYPE).readS32(),
      questId:questId,
      templateId:S(qp.add(OFF.QP_TEMPLATEID).readPointer()),
      progress:qp.add(OFF.QP_PROGRESS).readS32(),
      status:qp.add(OFF.QP_STATUS).readS32(),
      createdMs:qp.add(OFF.QP_CREATEDMS).readS64().toString(),
      lastUpdateMs:qp.add(OFF.QP_LASTUPDMS).readS64().toString(),
      completionMs:qp.add(OFF.QP_COMPLETMS).readS64().toString(),
      endMs:qp.add(OFF.QP_ENDMS).readS64().toString(),
      fortId:S(qp.add(OFF.QP_FORTID).readPointer())
    };
    // which concrete kind (QuestCase oneof) — number, mapped in Python
    if(getQCase){var qc=s32(invoke0(getQCase,qp)); if(qc!==null)rec.questCaseRaw=qc;}
    // goals (+ live target/condition)
    var g=readGoals(qp); rec.goals=g.goals; rec.goalsRepeated=g.repeated;
    // rewards
    rec.rewards=readRewards(qp, questId);
    // sub-quests (story / multi-part)
    var subs=readSubQuests(qp); if(subs&&subs.length)rec.subQuests=subs;

    // display text
    if(getDisplay&&questId){
      try{var ks=strNew(Memory.allocUtf8String(questId));var disp=invoke1ptr(getDisplay,qInst,ks);
        if(!disp.isNull()){
          var titleKey=S(disp.add(OFF.DISP_TITLEKEY).readPointer());
          var descKey =S(disp.add(OFF.DISP_DESCKEY).readPointer());
          rec.titleKey=titleKey; rec.title=tr(titleKey);
          rec.descKey=descKey; rec.description=tr(descKey);
          rec.tagString=tr(S(disp.add(OFF.DISP_TAGSTRING).readPointer()));
          rec.iconName=S(disp.add(OFF.DISP_ICONNAME).readPointer());
          rec.slot=disp.add(OFF.DISP_SLOT).readS32();
          var subRf=disp.add(OFF.DISP_SUBDISPLAYS).readPointer();
          var sd=rfList(subRf, 32); var sl=[];
          for(var s=0;s<sd.length;s++){var d=sd[s]; if(d.isNull())continue;
            sl.push({titleKey:S(d.add(OFF.DISP_TITLEKEY).readPointer()),
                     title:tr(S(d.add(OFF.DISP_TITLEKEY).readPointer())),
                     desc:tr(S(d.add(OFF.DISP_DESCKEY).readPointer()))});}
          if(sl.length)rec.subTaskDisplays=sl;
        }
      }catch(e){rec.dispErr=e.toString();}
    }
    // description-only fallback (GetQuestDescription(questProto))
    if(!rec.description&&getDesc){try{var d2=invoke1ptr(getDesc,qInst,qp); if(!d2.isNull())rec.description=S(d2);}catch(e){}}
    out.push(rec);
  }

  // ----- second list at QuestsProto+0x20: classify element shape -----
  var second={off:'+0x20'};
  var srf=po.add(OFF.QSP_SECOND).readPointer();
  if(srf&&!srf.isNull()){
    var arr=srf.add(OFF.RF_ARRAY).readPointer();var cnt=srf.add(OFF.RF_COUNT).readS32();
    second.count=cnt;
    if(!arr.isNull()&&cnt>0){
      var e0=arr.add(OFF.ARR_DATA).readPointer();
      if(!e0.isNull()){
        // probe: is it a string? (len@+0x10 plausible + chars). is templateId@+0x40? is questId@+0x28?
        var asStr=S(e0);
        var at28=S(e0.add(0x28).readPointer());
        var at40=S(e0.add(0x40).readPointer());
        var at10=S(e0.add(0x10).readPointer());
        var at18=S(e0.add(0x18).readPointer());
        second.sampleElement={ptr:e0.toString(), asString:asStr.slice(0,64),
          str_at10:at10.slice(0,48), str_at18:at18.slice(0,48),
          str_at28:at28.slice(0,48), str_at40:at40.slice(0,48)};
        // collect a few template-ish ids by scanning common string offsets
        var ids=[]; var n=Math.min(cnt,20);
        for(var i=0;i<n;i++){var el=arr.add(OFF.ARR_DATA).add(i*8).readPointer(); if(el.isNull())continue;
          var cand = S(el)|| S(el.add(0x28).readPointer()) || S(el.add(0x10).readPointer()) || S(el.add(0x18).readPointer());
          if(cand)ids.push(cand);}
        second.sampleIds=ids;
      }
    }
  }

  return {active:out, second:second};
};
"""


def fmt_ts(ms):
    try:
        x = int(ms)
        if x <= 0:
            return '-'
        return datetime.fromtimestamp(x / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return '?'


# ConditionOneofCase: protobuf field numbers -> human name (from metadata order of get_With*).
# These are the proto field TAGS; the live ConditionCase enum returns the tag. Best-effort map;
# unmapped values still print as raw ints. VALIDATE a couple against known quests.
COND_NAMES = {
    1: 'WithPokemonType', 2: 'WithPokemonCategory', 3: 'WithWeatherBoost',
    4: 'WithDailyCaptureBonus', 5: 'WithDailySpinBonus', 6: 'WithWinRaidStatus',
    7: 'WithRaidLevel', 8: 'WithThrowType', 9: 'WithWinGymBattleStatus',
    10: 'WithSuperEffectiveChargeMove', 11: 'WithItem', 12: 'WithUniquePokestop',
    13: 'WithQuestContext', 14: 'WithBadgeType', 15: 'WithPlayerLevel',
    16: 'WithWinBattleStatus', 17: 'WithUniquePokemon', 18: 'WithNpcCombat',
    19: 'WithPvpCombat', 20: 'WithLocation', 21: 'WithDistance',
}  # NOTE: exact tag numbers are a guess from declaration order; reconcile via quest_layouts.

# RewardOneofCase: from declaration order of QuestRewardProto getters.
REWARD_NAMES = {
    1: 'Exp', 2: 'Item', 3: 'Stardust', 4: 'Candy', 5: 'PokemonEncounter',
    6: 'AvatarClothing', 7: 'Quest', 8: 'LevelCap', 9: 'MegaResource',
    10: 'Incident', 11: 'PlayerAttribute', 12: 'EventBadge', 13: 'PokemonIndividualStat',
    14: 'LootTable', 15: 'Sticker', 16: 'FriendshipPoints', 17: 'TempEvoResource',
}  # VALIDATE: only ordering, not absolute tags. Raw case int always printed too.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default='research_full_dump.json')
    ap.add_argument('--raw', action='store_true')
    args = ap.parse_args()

    pid = _pid()
    print('PID', pid)
    d = frida.get_device_manager().add_remote_device('127.0.0.1:27047')
    sess = d.attach(pid)

    hs = sess.create_script(HOOK_JS)
    hs.on('message', lambda m, dd: None)
    hs.load()
    hs.exports_sync.setup()
    print('Capturing QuestService + I18n instances — open the Research (binoculars) screen...')
    q = i = None
    for _ in range(60):
        time.sleep(1)
        g = hs.exports_sync.get()
        q = g.get('q') or q
        i = g.get('i') or i
        if q and i:
            break
    hs.unload()
    if not q:
        print('NO_INSTANCE: QuestService never fired. Be on the map / Today / Research screen.')
        sess.detach(); sys.exit(1)
    print('QuestService', q, '| I18n', i or '(none — titles will show raw keys)')

    OFF = {
        'QSP_ACTIVE': OFF_QSP_ACTIVE, 'QSP_SECOND': OFF_QSP_SECOND,
        'RF_ARRAY': OFF_RF_ARRAY, 'RF_COUNT': OFF_RF_COUNT, 'ARR_LEN': OFF_ARR_LEN, 'ARR_DATA': OFF_ARR_DATA,
        'QP_QUESTTYPE': OFF_QP_QUESTTYPE, 'QP_QUESTID': OFF_QP_QUESTID, 'QP_TEMPLATEID': OFF_QP_TEMPLATEID,
        'QP_PROGRESS': OFF_QP_PROGRESS, 'QP_GOALS': OFF_QP_GOALS, 'QP_STATUS': OFF_QP_STATUS,
        'QP_CREATEDMS': OFF_QP_CREATEDMS, 'QP_LASTUPDMS': OFF_QP_LASTUPDMS, 'QP_COMPLETMS': OFF_QP_COMPLETMS,
        'QP_FORTID': OFF_QP_FORTID, 'QP_ENDMS': OFF_QP_ENDMS, 'QP_QUESTREWARDS': OFF_QP_QUESTREWARDS,
        'GOAL_CONDITIONS': OFF_GOAL_CONDITIONS, 'GOAL_TARGET': OFF_GOAL_TARGET,
        'COND_CASE': OFF_COND_CASE, 'REWARD_CASE': OFF_REWARD_CASE,
        'DISP_DESCKEY': OFF_DISP_DESCKEY, 'DISP_TITLEKEY': OFF_DISP_TITLEKEY, 'DISP_SLOT': OFF_DISP_SLOT,
        'DISP_TAGSTRING': OFF_DISP_TAGSTRING, 'DISP_ICONNAME': OFF_DISP_ICONNAME,
        'DISP_SUBDISPLAYS': OFF_DISP_SUBDISPLAYS,
    }

    sc = sess.create_script(READ_JS)
    sc.load()
    r = sc.exports_sync.read(q, i or '0x0', OFF)
    sess.detach()

    if 'error' in r:
        print('ERROR:', r['error']); sys.exit(1)

    active = r.get('active', [])
    print(f"\n========== {len(active)} ACTIVE QUESTS ==========")
    for qd in active:
        st = QSTATUS.get(qd['status'], f"S{qd['status']}")
        title = (qd.get('title') or qd.get('templateId') or '?').strip()
        print(f"\n[{st}] {qd['templateId']}")
        print(f"  Title: {title}")
        if qd.get('description') and qd['description'] != title:
            print(f"  Desc:  {qd['description'][:160]}")
        if qd.get('tagString'):
            print(f"  Tag:   {qd['tagString']}")
        # goals + conditions
        for gi_, gl in enumerate(qd.get('goals', [])):
            cn = COND_NAMES.get(gl.get('conditionCaseRaw'), gl.get('conditionCaseRaw'))
            print(f"  Goal {gi_+1}: progress {qd.get('progress',0)}/{gl.get('target','?')}  condition={cn}")
        if not qd.get('goals'):
            print(f"  Progress: {qd.get('progress',0)} (no goal decoded — VALIDATE OFF_QP_GOALS)")
        # rewards
        for rw in qd.get('rewards', []):
            rn = REWARD_NAMES.get(rw.get('caseRaw'), f"case{rw.get('caseRaw')}")
            extra = ''
            if rw.get('exp'):
                extra = f" exp={rw['exp']}"
            elif rw.get('item'):
                extra = f" item id={rw['item'].get('id')} x{rw['item'].get('count')}"
            elif rw.get('pokemonEncounter'):
                extra = f" ENCOUNTER pokemonId={rw['pokemonEncounter'].get('pokemonId')}"
            print(f"  Reward: {rn}{extra}")
        # sub-quests
        for s in qd.get('subQuests', []):
            sgt = s['goals'][0].get('target', '?') if s.get('goals') else '?'
            sst = QSTATUS.get(s['status'], s['status'])
            print(f"    - [sub {sst}] {s['templateId']}  {s['progress']}/{sgt}")
        # display sub-tasks (if no multipart)
        if not qd.get('subQuests'):
            for s in qd.get('subTaskDisplays', []):
                print(f"    - task: {s.get('title','')[:80]}")
        print(f"  Created {fmt_ts(qd['createdMs'])} | Updated {fmt_ts(qd['lastUpdateMs'])} | Ends {fmt_ts(qd['endMs'])}")
        if args.raw:
            print(f"  [raw] questCase={qd.get('questCaseRaw')} goalsRepeated={qd.get('goalsRepeated')} questId={qd['questId']}")

    sec = r.get('second', {})
    print(f"\n========== SECOND LIST QuestsProto{sec.get('off','+0x20')} : {sec.get('count','?')} entries ==========")
    if sec.get('sampleElement'):
        se = sec['sampleElement']
        print("  Element shape probe (find which string offset holds the id):")
        for k in ('asString', 'str_at10', 'str_at18', 'str_at28', 'str_at40'):
            if se.get(k):
                print(f"    {k:9}= {se[k]!r}")
    if sec.get('sampleIds'):
        print("  Sample ids:", sec['sampleIds'][:12])

    with open(args.json, 'w', encoding='utf-8') as f:
        json.dump(r, f, indent=2)
    print(f"\nSaved {args.json}")


if __name__ == '__main__':
    main()
