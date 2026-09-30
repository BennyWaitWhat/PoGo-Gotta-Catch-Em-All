# IL2CPP Metadata / RE Assets — Inventory & How To Query

**Subsystem:** IL2CPP METADATA / RE ASSETS (the gating recon)
**Date:** 2026-05-29
**Mode:** STATIC analysis only. No Frida/adb/device used to produce this.
**Bottom line:** There is **one** authoritative static RE asset — `global-metadata.dat`
(IL2CPP metadata **version 31**, valid magic `0xFAB11BAF`, 38 MB). There is **NO**
Il2CppDumper output anywhere (no `dump.cs`, `il2cpp.h`, `script.json`,
`stringliteral.json`, `DummyDll/`, or any managed `.dll`). The IL2CPP **binary**
(`libil2cpp.so`) is **also not in the repo**. Every offset used by the existing
quest/bag/dex readers is **runtime-inferred by hand**, not read from a dump.

The good news, proven below: **`global-metadata.dat` can be parsed standalone**
(I did, with `python` + 40 lines) to recover **authoritative type names, field
names, field order, nested enums, and enum member values** for any
`Niantic.Holoholo.*` / `Holoholo.Rpc.*` type. That converts the whole effort from
"probe random offsets" to "look up the field list, then map sequential protobuf
slots." Offsets themselves (exact `+0xNN`) still require the live binary or runtime
probing, but the **field identity/order is now ground truth**.

---

## 1. What authoritative assets exist vs. inferred

| Asset | Path | Status | What it gives |
|---|---|---|---|
| `global-metadata.dat` | `pogo_extract/global-metadata.dat` | **AUTHORITATIVE, v31, parseable** | All type names, namespaces, **field names + order**, nested types, **enum members + values**, method names, string literals. NOT field byte-offsets. |
| `_metadata_strings.txt` | `pogo_extract/_metadata_strings.txt` | Strings dump of the IL2CPP binary's data section | Class FQNs in `Namespace\|TypeName` form, proto names, **embedded source paths** (e.g. `\Assets\Scripts\Quest\QuestService.cs`), enum tokens, log strings. Good for grep recon; not structured. |
| `libholoholo.so`, `libNianticLabsPlugin.so` | `pogo_extract/` | ELF64 aarch64, **NOT IL2CPP** (0 `il2cpp_*` exports), ~13 MB each | Niantic native plugins (NIA-LP / map / AR). Not the managed-code binary. |
| `libnotmain.so` | `pogo_extract/ipogo_extracted/` + `pogo_extract/` | iPoGo/gadget loader (1 ref to `il2cpp_class_from_name`) | The injector, **not** PoGo's `libil2cpp.so`. |
| `ipogo_extracted/jadx_out/sources` | `pogo_extract/ipogo_extracted/jadx_out/` | **iPoGo injector** Java/Kotlin decompile (NOT PoGo) | Irrelevant to Holoholo IL2CPP internals. Don't waste time here for quest data. |
| `*_strings.txt` (many) | `pogo_extract/` | raw `strings` over various `.so`/dex | grep fodder. |
| **`libil2cpp.so`** | — | **ABSENT** | Would pair with metadata.dat for a full Il2CppDumper run (→ `dump.cs` with exact offsets). |
| **Il2CppDumper output** | — | **ABSENT** | No `dump.cs` / `il2cpp.h` / `script.json` / `DummyDll`. |

**Header parse (verified):**
```
magic   = 0xFAB11BAF   (valid il2cpp global-metadata)
version = 31           (Unity 2022.3.x-era IL2CPP)
size    = 38,278,436 bytes
```

### Why this gates everything
- With metadata.dat **alone**, you can already enumerate the **exact field list and
  order** of any proto/class. PoGo protos are Google.Protobuf C# classes whose
  instance layout is deterministic: a managed object header (`0x10` on arm64) then
  the declared fields in declaration order, 8-byte slots for refs/longs, packed for
  smaller scalars, with `static Parser` excluded. So **field index → offset** is
  largely mechanical (and matches every offset the existing code already uses — see §3).
- To get **guaranteed** byte offsets without runtime probing, you'd need
  `libil2cpp.so` (pull `/data/app/.../lib/arm64/libil2cpp.so` — that's a device op,
  out of scope here) and run **Il2CppDumper** (or Il2CppInspector) against it +
  `global-metadata.dat`. That yields `dump.cs` with `// 0xNN` on every field and is
  the single highest-leverage upgrade to this whole pipeline.

---

## 2. Where to look up offsets/structure for each subsystem

All proto messages live in assembly **`holo-protos.dll`**; services/controllers live
in **`holo-game.dll`**. (Both confirmed in `walk_waina_subquests.py`, which resolves
`QuestProto` from `holo-protos.dll` and `QuestService` from `holo-game.dll`.) The
"singleton" stateful objects live under namespace **`Niantic.Holoholo.Internal`**.

| Subsystem | Authoritative lookup (metadata.dat type) | Live read entrypoint |
|---|---|---|
| **Quests (state)** | `Holoholo.Rpc.QuestProto`, `QuestGoalProto`, `QuestConditionProto`, `MultiPartQuestProto`, `QuestRewardProto`, `QuestEncounterProto` | `Niantic.Holoholo.Quests.QuestService` (`holo-game.dll`) — getters in §4 |
| **Quests (display/title)** | `Holoholo.Rpc.QuestDisplayProto` (has `Title`,`Description`,`Dialog`,`SubquestDisplays`,`Branches`,…) | `QuestService.GetQuestDisplayProto(questId)` (1-arg) |
| **Rewards** | `QuestRewardProto` + nested enum `RewardOneofCase` (full kind list §5) + `ItemProto`, `QuestEncounterProto`, `LootItemProto` | `QuestService.GetQuestRewardProtos(...)` and per-reward accessors `get_RewardCase`,`get_Item`,`get_PokemonEncounter`,… |
| **Badges / Medals** | `Holoholo.Rpc.PlayerBadgeProto` (`BadgeType`,`Rank`,`StartValue`,`EndValue`,`CurrentValue`,`Tiers`), `PlayerBadgeTierProto`, `BadgeTierRewardProto`, `CheckAwardedBadgesProto` | `BadgeService` / `IBadgeService` (UI in `Niantic.Holoholo.Badges.*`); gym medals via `Niantic.Holoholo.GymBadges.GymBadgeService` |
| **Inventory (items)** | `Niantic.Platform.Inventory.InventoryItemProto`, `Holoholo.Rpc.ItemProto` (`Item`=item-id enum, `Count`), `InventoryItemProto`, `HoloInventoryItemProto` | `Niantic.Holoholo.Internal.ItemBagImpl` (parallel to PokemonBagImpl); methods `GetItemCount`,`GetItems`,`GetItem`,`GetItemsCount` |
| **Pokemon bag / Pokedex** | (already mapped in repo) | `Niantic.Holoholo.Internal.PokemonBagImpl`, `PokedexImpl` |

**How to query metadata.dat for any of these:** use the parser in
`tools/meta_dump.py` (§6) — `python meta_dump.py QuestDisplayProto` prints the field
list with indices; `python meta_dump.py --enum QuestRewardProto.RewardOneofCase`
prints enum members+values.

---

## 3. Field-index → offset mapping (validates existing runtime offsets)

Parsed `QuestProto` (45 fields) from metadata.dat. Mapping the declared order against
the **known-good offsets** in the existing readers confirms the protobuf layout rule
(arm64: header `0x10`, then fields in order; `Parser` is static and skipped; the
first real ref/long field lands at `0x10`+...; small scalars get packed at the end).

`QuestProto` declared fields (index : name) — abbreviated to the load-bearing ones:
```
[0] Parser (static, skip)   [1] QuestType    [2] WithSingleDay  [3] DaysInARow
[4] QuestId  [5] QuestSeed  [6] QuestContext [7] TemplateId     [8] Progress
[9] Goal     [10] Status    [11] como(oneof) [12] QuestRewards  [13] CreationTimestampMs
[14] LastUpdateTimestampMs ... [23] RewardPokemonIconUrl ... [28] BranchRewards ...
```
Existing **verified** runtime offsets and what metadata says they are:
| Existing offset | Field (metadata) | Type | Note |
|---|---|---|---|
| `templateId @ +0x40` (UTF16 String*) | `[7] TemplateId` | string | ✔ matches |
| `questType @ +0x10` | `[1] QuestType` | enum(int) | ✔ first packed field at header end |
| `progress @ +0x48` | `[8] Progress` | int32 | ✔ |
| `goal* @ +0x50` (→ Target@+0x18) | `[9] Goal` → `QuestGoalProto.Target[3]` | msg→int | ✔ |
| `status @ +0x58` (2=COMPLETE) | `[10] Status` | enum(int) | ✔ |
| sub-quest `questId @ +0x28` | `[4] QuestId` | string | ✔ (in `walk_waina_subquests.py`) |

So the existing offsets are **correct and now named**. The previously-**undecoded**
fields are now identified:
- `QuestProto[12] QuestRewards` = `RepeatedField<QuestRewardProto>` → **this is where
  item/Pokémon rewards live** (the lead asked for this). Likely at the next 8-byte
  slot after `Status@+0x58` region; resolve at runtime by reading the property
  `get_QuestRewards` rather than guessing (recommended — see §7 draft).
- `QuestProto[28] BranchRewards` = branch-choice rewards (branching research).
- The "second ~78-entry RepeatedField at +0x20 of QuestsProto whose element
  templateId is NOT at +0x40": that is almost certainly a **different element type**
  (e.g. `QuestDisplayProto` or `ClientQuestProto`/progressed-quest wrapper), which is
  why `+0x40` (TemplateId of `QuestProto`) doesn't apply. Decode it by first reading
  its element class at runtime (`il2cpp_object_get_class` → `il2cpp_class_get_name`)
  before assuming a layout. (Flagged for device validation.)

---

## 4. QuestService getter surface (from this session's `explore_quests.py` enumeration + metadata)

0-arg: `get_QuestsProto`, `get_Quests`, `get_ProgressedQuests`, `GetStoryQuestProtos`,
`GetWelcomeBackRewardQuests`.
1-arg: `GetQuestDescription(qp)→string`, **`GetQuestDisplayProto(questId)→QuestDisplayProto`**
(Title/Description/Dialog/SubquestDisplays), `GetPokemonEncounterForQuest(qp)→QuestEncounterProto`,
`GetQuestDataOfType(...)`, **`GetQuestRewardProtos(...)→RepeatedField<QuestRewardProto>`**.

Mutation/RPC (do **not** use for read recon; server-authoritative): `QuestRpcService`
has `UpdateQuestDetails(List<string>)`, `CompleteQuest(qid,subqid,Nullable<int>,uint64)`,
`CompleteQueuedQuests()`; `QuestAutoCompleteService.CompleteQueuedQuests()`.

---

## 5. Reward model — fully decoded (the §"REWARDS (items + Pokémon)" ask)

`Holoholo.Rpc.QuestRewardProto` is a protobuf **oneof**. Declared fields:
`[0]Parser [1]Type [2]conc [3]cond` — where `conc`/`cond` are the obfuscated oneof
case-tag + value-union. The nested **`RewardOneofCase`** enum (extracted from
metadata.dat, names are authoritative; integer values are the C#-generated mangled
case constants, **use the names / the `get_RewardCase` accessor, not the raw ints**):

```
None, Exp, Item, Stardust, Candy, AvatarTemplateId, QuestTemplateId,
PokemonEncounter, Pokecoin, XlCandy, LevelCap, Sticker, MegaResource, Incident,
PlayerAttribute, EventBadgeId, NeutralAvatarTemplateId, NeutralAvatarItemTemplate,
NeutralAvatarItemDisplay, PokemonEgg, PokemonIndividualStat, LootTable,
FriendshipPoints, TempEvoResource
```

Per-reward **accessor properties confirmed present** (invoke at runtime on each
`QuestRewardProto`): `get_RewardCase`, `get_Item`, `get_Stardust`, `get_Candy`,
`get_Exp`, `get_Pokecoin`, `get_XlCandy`, `get_MegaResource`, `get_Sticker`,
`get_PokemonEncounter`, `get_PokemonEgg`, `get_LootTable`, `get_QuestTemplateId`,
`get_AvatarTemplateId`.

Sub-message shapes (from metadata.dat):
- `ItemProto` = `[1]Item (item-id enum) [2]Count [3]Unseen [4]ExpirationTime …`
  → an **Item reward** = (`Item` enum id, `Count`).
- `QuestEncounterProto` = `[1]PokemonId [2]QuestId`
  → a **Pokémon reward** = `PokemonId` (the species/encounter the quest grants; this
  is what `dump_quests.py` printed as `POKEMON_REWARD pid=...`).
- `LootItemProto` = `[1]Count [2]colz [3]coma` (loot-table entries; obfuscated inner type/id).

**Decoding recipe:** for each `QuestRewardProto r`: read `get_RewardCase`; switch on
the case name; call the matching `get_X` accessor; for `Item` read `ItemProto.Item`+`Count`,
for `PokemonEncounter` read `QuestEncounterProto.PokemonId`. (Draft in §7.)

---

## 6. Display / title / sub-quest model

`Holoholo.Rpc.QuestDisplayProto` (via `QuestService.GetQuestDisplayProto(questId)`):
```
[1]QuestId [3]Dialog [4]Description [5]Title [6]Slot [8]SubquestDisplays
[9]StoryEndingQuest [10]StoryEndingDescription [11]TagColor [12]TagString
[15]IconName [16]BackgroundName [20]Branches [30]StoryQuestlineTitle [32]QuestHeaderDisplay
```
→ Human-readable **Title** = field `[5]`, **Description** = `[4]`, narrative **Dialog**
= `[3]`, per-step text = `[8]SubquestDisplays`. These are localized client-side via
`LocalizationManager` / `GetLocalizedString`; `GetQuestDescription` already returns the
resolved string (seen working in `read_quest_details.py`).

Sub-quest structure: `MultiPartQuestProto.SubQuests[2]` = `RepeatedField<QuestProto>`
(each sub-quest is itself a `QuestProto`). Already read successfully in
`walk_waina_subquests.py` via `QuestProto.get_MultiPart()`.

---

## 7. Draft readers (lead can run as-is; offsets flagged)

### 7a. `tools/meta_dump.py` — STATIC metadata.dat field/enum lookup (no device)
This is the proven parser I used. Drop it at
`pogo_extract/system/analysis/game_read_recon/meta_dump.py`.

```python
#!/usr/bin/env python
"""Static reader for global-metadata.dat (IL2CPP v31).
Usage:
  python meta_dump.py QuestProto                 # list fields (index:name) of a type
  python meta_dump.py --ns Holoholo.Rpc QuestProto
  python meta_dump.py --enum QuestRewardProto.RewardOneofCase   # enum members+values
No device. Field NAMES/ORDER are authoritative; byte offsets are NOT in metadata."""
import struct, sys
PATH = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\global-metadata.dat"
d = open(PATH, "rb").read()
u32=lambda o:struct.unpack_from('<I',d,o)[0]; i32=lambda o:struct.unpack_from('<i',d,o)[0]
u16=lambda o:struct.unpack_from('<H',d,o)[0]
assert u32(0)==0xFAB11BAF and u32(4)==31, "not metadata v31"
H=['stringLiteral','stringLiteralData','string','events','properties','methods',
'parameterDefaultValues','fieldDefaultValues','fieldAndParameterDefaultValueData',
'fieldMarshaledSizes','parameters','fields','genericParameters','genericParameterConstraints',
'genericContainers','nestedTypes','interfaces','vtableMethods','interfaceOffsets',
'typeDefinitions','images','assemblies','fieldRefs','referencedAssemblies','attributeData',
'attributeDataRange','unresolvedIndirectCallParameterTypes','unresolvedIndirectCallParameterRanges',
'windowsRuntimeTypeNames','windowsRuntimeStrings','exportedTypeDefinitions']
o=8; hdr={}
for nm in H: hdr[nm]=(u32(o),u32(o+4)); o+=8
soff,ssz=hdr['string']; sb=d[soff:soff+ssz]
cstr=lambda i:sb[i:sb.find(b'\x00',i)].decode('utf-8','ignore')
TD,TDSZ=hdr['typeDefinitions'][0],0x58       # Il2CppTypeDefinition size for THIS build
FLD,FLDSZ=hdr['fields'][0],0x0C              # {nameIndex,typeIndex,token}
NEST=hdr['nestedTypes'][0]
FDV=hdr['fieldDefaultValues'][0]; FDVN=hdr['fieldDefaultValues'][1]//12
DATA=hdr['fieldAndParameterDefaultValueData'][0]
fdv={}
for i in range(FDVN):
    b=FDV+i*12; fdv[i32(b)]=i32(b+8)
# TypeDefinition field offsets (v31): name@0 ns@4 fieldStart@0x20 field_count@0x44 nestedStart@0x30 nested_count@0x48
def types():
    n=hdr['typeDefinitions'][1]//TDSZ
    for i in range(n):
        yield i, TD+i*TDSZ
def find(name, ns=None):
    for i,b in types():
        if cstr(i32(b))==name and (ns is None or cstr(i32(b+4))==ns): return b
    return None
def fields(b):
    fs=i32(b+0x20); fc=u16(b+0x44)
    return [cstr(i32(FLD+fi*FLDSZ)) for fi in range(fs,fs+fc)]
def enum_members(b):
    fs=i32(b+0x20); fc=u16(b+0x44); out=[]
    for fi in range(fs,fs+fc):
        nm=cstr(i32(FLD+fi*FLDSZ))
        if nm=='value__': continue
        di=fdv.get(fi); val=struct.unpack_from('<i',d,DATA+di)[0] if di not in (None,-1) else None
        out.append((nm,val))
    return out
args=sys.argv[1:]; ns=None
if '--ns' in args: i=args.index('--ns'); ns=args[i+1]; del args[i:i+2]
if args and args[0]=='--enum':
    outer,inner=args[1].split('.')
    ob=find(outer,ns); ns0=i32(ob+0x30); nc=u16(ob+0x48); tgt=None
    for k in range(ns0,ns0+nc):
        nb=TD+i32(NEST+k*4)*TDSZ
        if cstr(i32(nb))==inner: tgt=nb
    for nm,v in enum_members(tgt): print(f"{v}: {nm}")
else:
    b=find(args[0],ns)
    if not b: print("not found"); sys.exit(1)
    print(f"{cstr(i32(b+4))}.{args[0]}")
    for j,f in enumerate(fields(b)): print(f"  [{j}] {f}")
```

### 7b. Frida JS — full quest read with rewards (DRAFT; reuses pogo_il2cpp.py preamble)
Append to the `JS_PREAMBLE` from `pogo_il2cpp.py`; capture a `QuestService` instance
via the existing interceptor trick (see `dump_quests.py`). **All offsets flagged for
device validation** are tagged `// VALIDATE`.

```javascript
// requires pogo_il2cpp.py JS_PREAMBLE (cFN/cMN/rI/_ensureInit already defined)
function rdU16(p){ if(p.isNull())return''; var n=p.add(0x10).readS32();   // VALIDATE 0x10/0x14 (String layout, known-good in repo)
  if(n<=0||n>4000)return''; var c=[]; for(var i=0;i<n;i++){var ch=p.add(0x14+i*2).readU16(); if(!ch)break; c.push(String.fromCharCode(ch));} return c.join(''); }

rpc.exports.readQuestsFull = function(qsAddr){
  _ensureInit();
  var qs = cFN('Niantic.Holoholo.Quests','QuestService');
  var inst = ptr(qsAddr);
  var getProto = cMN(qs,'get_QuestsProto',0);
  var getDisp  = cMN(qs,'GetQuestDisplayProto',1);     // -> QuestDisplayProto
  var po = rI(getProto, inst, ptr(0), null);
  if(po.isNull()) return {err:'null QuestsProto'};
  var rf  = po.add(0x10).readPointer();                // VALIDATE: RepeatedField @ QuestsProto+0x10 (known-good)
  var arr = rf.add(0x10).readPointer(), cnt = rf.add(0x18).readS32();
  // resolve proto-side classes for rewards
  // (holo-protos.dll image; reuse cFN but it binds to holo-game.dll — for proto types
  //  use il2cpp_object_get_class on the live object instead of cFN, to avoid image mismatch)
  var objClass = new NativeFunction(Process.findModuleByName('libil2cpp.so').getExportByName('il2cpp_object_get_class'),'pointer',['pointer']);
  var className= new NativeFunction(Process.findModuleByName('libil2cpp.so').getExportByName('il2cpp_class_get_name'),'pointer',['pointer']);
  function clsName(o){ try{ return className(objClass(o)).readCString(); }catch(e){ return '?'; } }
  function methOn(o,name,argc){ return cMN(objClass(o), name, argc); }

  var out=[];
  for (var i=0;i<Math.min(cnt,400);i++){
    var qp = arr.add(0x20).add(i*8).readPointer(); if(qp.isNull()) continue;
    var rec = { tid: rdU16(qp.add(0x40).readPointer()),     // [7] TemplateId  VALIDATE 0x40
                qtype: qp.add(0x10).readS32(),               // [1] QuestType   VALIDATE 0x10
                progress: qp.add(0x48).readS32(),            // [8] Progress    VALIDATE 0x48
                status: qp.add(0x58).readS32(),              // [10] Status     VALIDATE 0x58
                qid: rdU16(qp.add(0x28).readPointer()),      // [4] QuestId     VALIDATE 0x28
                target:0, title:'', desc:'', rewards:[] };
    try{ var g=qp.add(0x50).readPointer(); if(!g.isNull()) rec.target=g.add(0x18).readS32(); }catch(e){} // Goal[9].Target[3] @0x18

    // --- DISPLAY (title/description) ---  invoke GetQuestDisplayProto(questId-string)
    try{
      var a1=Memory.alloc(8); a1.writePointer(qp.add(0x28).readPointer());   // pass QuestId string
      var disp=rI(getDisp, inst, a1, null);
      if(!disp.isNull()){
        var gT=methOn(disp,'get_Title',0), gD=methOn(disp,'get_Description',0);
        if(gT&&!gT.isNull()){var t=rI(gT,disp,ptr(0),null); if(!t.isNull()) rec.title=rdU16(t);}
        if(gD&&!gD.isNull()){var de=rI(gD,disp,ptr(0),null); if(!de.isNull()) rec.desc=rdU16(de);}
      }
    }catch(e){ rec.title='<dispErr '+e+'>'; }

    // --- REWARDS ---  read QuestProto.get_QuestRewards -> RepeatedField<QuestRewardProto>
    try{
      var gR=methOn(qp,'get_QuestRewards',0);
      if(gR&&!gR.isNull()){
        var rrf=rI(gR,qp,ptr(0),null);
        if(!rrf.isNull()){
          var rarr=rrf.add(0x10).readPointer(), rc=rrf.add(0x18).readS32();   // RepeatedField layout
          for(var k=0;k<Math.min(rc,20);k++){
            var rw=rarr.add(0x20).add(k*8).readPointer(); if(rw.isNull()) continue;
            var gCase=methOn(rw,'get_RewardCase',0);
            var caseVal = gCase&&!gCase.isNull() ? rI(gCase,rw,ptr(0),null).toInt32() : -1;
            // resolve by accessor based on a small dispatch (names from RewardOneofCase)
            var entry={case:caseVal};
            function tryAcc(name, read){ try{ var m=methOn(rw,name,0); if(m&&!m.isNull()){ var v=rI(m,rw,ptr(0),null); if(!v.isNull()) read(v,entry);} }catch(e){} }
            tryAcc('get_Item', function(v,e){ var mi=methOn(v,'get_Item',0), mc=methOn(v,'get_Count',0);
              e.kind='ITEM'; if(mi&&!mi.isNull())e.itemId=rI(mi,v,ptr(0),null).toInt32(); if(mc&&!mc.isNull())e.count=rI(mc,v,ptr(0),null).toInt32(); });
            tryAcc('get_PokemonEncounter', function(v,e){ var mp=methOn(v,'get_PokemonId',0);
              e.kind='POKEMON_ENCOUNTER'; if(mp&&!mp.isNull())e.pokemonId=rI(mp,v,ptr(0),null).toInt32(); });
            tryAcc('get_Stardust', function(v,e){ e.kind='STARDUST'; e.amount=v.toInt32(); });
            tryAcc('get_Exp',      function(v,e){ e.kind='EXP';      e.amount=v.toInt32(); });
            tryAcc('get_Candy',    function(v,e){ e.kind='CANDY'; });
            tryAcc('get_XlCandy',  function(v,e){ e.kind='XL_CANDY'; });
            tryAcc('get_Pokecoin', function(v,e){ e.kind='POKECOIN'; e.amount=v.toInt32(); });
            tryAcc('get_MegaResource', function(v,e){ e.kind='MEGA_RESOURCE'; });
            tryAcc('get_PokemonEgg',   function(v,e){ e.kind='POKEMON_EGG'; });
            rec.rewards.push(entry);
          }
        }
      }
    }catch(e){ rec.rewards.push({err:String(e)}); }
    out.push(rec);
  }
  return {count:cnt, quests:out};
};
```
> The reward block deliberately uses `il2cpp_object_get_class` + `get_*` accessors
> instead of fixed offsets, because (a) the `holo-protos.dll` vs `holo-game.dll` image
> split makes `cFN` (which binds `holo-game.dll`) unsuitable for proto types, and
> (b) accessors are obfuscation-proof. Only the top-level `QuestProto` field offsets
> (`0x10/0x28/0x40/0x48/0x50/0x58`) are fixed — and those are already device-verified.

---

## 8. Things that NEED device validation
1. **`QuestProto.get_QuestRewards` returns a RepeatedField at the expected layout** —
   verify `rrf+0x10`(items)/`+0x18`(count)/`+0x20`(data) hold for `QuestRewardProto[]`.
2. **The second ~78-entry RepeatedField at `QuestsProto+0x20`**: read element class via
   `il2cpp_object_get_class`→`il2cpp_class_get_name` before assuming it's `QuestProto`
   (its templateId is NOT at +0x40, so it's a different type — likely `QuestDisplayProto`
   or a progressed/ClientQuest wrapper).
3. **`GetQuestDisplayProto` arg type**: confirm it takes the **QuestId string** (vs the
   `QuestProto`); if it expects `QuestProto`, pass `qp` directly instead of the string.
4. **`get_RewardCase` integer → name**: the metadata enum values are mangled C# case
   constants; map by **invoking each accessor and seeing which returns non-null**, or by
   reading the enum at runtime via reflection — don't hard-code the mangled ints.
5. **Reward accessor null-semantics**: a protobuf oneof returns the *default* sub-message
   (not null) for the un-set case in some C# protobuf versions; gate on `get_RewardCase`
   first, then call exactly one accessor.
6. **`ItemBagImpl` / badge `PlayerBadgeProto` live offsets** are entirely unprobed here
   (only the field *names/order* are known from metadata) — validate on device before use.

## 9. Highest-leverage next step (recommended to the lead)
Pull `libil2cpp.so` from the device once (`/data/app/~~*/com.nianticlabs.pokemongo-*/lib/arm64/libil2cpp.so`,
or from the base.apk `lib/arm64-v8a/`) and run **Il2CppDumper** against it +
`global-metadata.dat`. That produces `dump.cs` with **every field's exact `// 0xNN`
offset**, eliminating all runtime offset-probing for quests, rewards, badges, and
inventory in one shot. The metadata is already v31 and parses cleanly, so the dump
will succeed.
