# GO Fest 2026 Data Model — Session-Dump Forensics

Static analysis only. No device calls were made. Everything below is derived from
code + data already on disk in `pogo_extract/`, cross-referenced against the live
captures this session left behind.

Scope: build a durable model of how the GO Fest research / medal / reward / location-card
pieces fit together, document which READ would have answered each question, and flag
exactly what still needs a device re-poll.

---

## 0. TL;DR for the lead

1. **Completed City/District challenges do NOT live in the active quest list.** They move
   to a *second* list on the same `QuestsProto` object: a `RepeatedField<string>` of bare
   templateIds at **`QuestsProto + 0x18`** (NOT `+0x20`, and NOT element-`+0x40`-decoded).
   `extract_quests_v3.py` already reads it correctly as `completedIds`. The "78-entry
   undecoded +0x20 list" in the task brief is a red herring — the real completed list is the
   string list at +0x18.
2. **District completion surfaces as a MEDAL**, not a quest, once the challenge is claimed.
   It becomes a `Holoholo.Rpc.PlayerBadgeProto` (`BadgeEventNNNN` / `BadgeGofest` /
   `BadgeChallengeQuests` family). Read it through `BadgeService`, not `QuestService`.
3. **The GO Fest 2026 Mewtwo location card is recoverable but NOT yet in the DB.** Both
   Mewtwo catches (CP 2363/2362, IV 41) carry `fresh_has_location_card=1` but
   `fresh_loc_card_enum=NULL`. They are simply **absent from the current `fresh_poll.json`**
   (out of heap at last poll). The enum they *should* carry is **248/249/250 =
   `LcSpecialbackground2026Mewtwo001/002/003`** (confirmed present in metadata). A targeted
   re-poll with them in the heap fills the gap — no new offset discovery required.
4. **Rotating event templateIds are server-pushed and invisible to static analysis.** The
   `QUEST_GOFEST2026_APAC_*`, `TR_GOFEST2026_IRL_CITY_*`, `WIN_MEWTWO` ids do **not** appear in
   `_metadata_strings.txt`. Only the live `QuestsProto` walk sees them. The *location-card
   enum* and *medal* string tables, by contrast, ARE baked into the DLL and can be mapped offline.

---

## 1. The concrete GO Fest data captured this session

### 1a. Rotating templateIds seen in the live `QuestsProto` walk
These were observed this session via `dump_quests.py` / `find_cities.py` / `extract_quests_v3.py`
but are **not** in any static dump:

| templateId (family) | questType | Where it lives | Meaning |
|---|---|---|---|
| `QUEST_GOFEST2026_APAC_CATCH_*` | 4 (CHALLENGE) | active `+0x10` while in progress | per-task catch challenge |
| `QUEST_GOFEST2026_APAC_SPIN_*` | 4 (CHALLENGE) | active `+0x10` while in progress | per-task spin challenge |
| `QUEST_GOFEST2026_APAC_..._WIN_MEWTWO` | 4 (CHALLENGE) | active `+0x10` → vanishes on claim | Mewtwo raid-win step |
| `TR_GOFEST2026_IRL_CITY_FRIENDSHIP` | 3 (STORY/TR header) | active `+0x10`; header persists | city-pass friendship TR |
| `TR_GOFEST2026_IRL_CITY_FULL4` | 3 (STORY/TR header) | active `+0x10`; header persists | city-pass set-4 TR |
| `STORY_QUEST_WAINA23_1` | 3 (STORY) | active `+0x10`, MultiPart | "Catching Some Z's (2/2)" sleep TR |

Cross-check from `quests_v3_dump.json` (this session's enriched dump): the 2025 analogues of
these — `SR_GOFEST2025_IRL_CITY_*`, `TR_GOFEST2025_*` — appear in the **`completedIds`** list,
confirming the lifecycle: **active `+0x10` → (claim) → `completedIds` `+0x18`**, with the
season-pass *header* rows (`*_SEASON_PASS_BONUS_QUESTS_HEADER`, `*_HEADER`) lingering in active
because the header is a container, not a single-shot quest.

### 1b. The "vanishing City challenge" mechanic (the thing that confused us)
- A City/District challenge, while you are working it, is a `questType==4` row in the active
  list at `QuestsProto+0x10`, with `progress`/`goal.target`.
- The moment it is **claimed/completed**, the live client **removes the QuestProto from
  `+0x10`** and pushes its templateId string into the **`completedIds` list at `+0x18`**.
- Therefore a snapshot of only `+0x10` that is taken *after* completion shows the challenge as
  GONE, not as `status==2`. That is expected, not a bug. To prove a challenge was finished you
  must read **`+0x18` (completedIds)** AND/OR the corresponding **medal** (§3).
- The **season-pass header** (`WEEK1_MAY2026_SEASON_PASS_BONUS_QUESTS_HEADER`, the
  GO-Fest IRL city `*_HEADER` rows) PERSISTS in `+0x10` with `status==2` because it is the
  parent grouping object and stays resident for the event window (`endMs` in the future).

---

## 2. QuestsProto / QuestProto / QuestDisplayProto — the read map

All offsets below are **proven** by the scripts that already ran successfully this session
(`extract_quests_v3.py` produced `quests_v3_dump.json` with correct titles, timestamps, and
the completed list). Class: `Niantic.Holoholo.Quests.QuestService` (`holo-game.dll`).
Singleton capture: hook every QuestService method, grab `args[0]` (the proven pattern in
`dump_quests.py`); the Research/Today screen must be open so a method fires.

### 2a. `QuestsProto` (returned by `QuestService.get_QuestsProto()`)
| Offset | Field | Type | Notes |
|---|---|---|---|
| `+0x10` | **active quests** | `RepeatedField<QuestProto>` | count `+0x18`, items array `+0x10`→`+0x20` data |
| `+0x18` | **completedIds** | `RepeatedField<string>` | bare templateId strings; THIS is the completed list |
| (`+0x20`) | other container | RepeatedField | ~78 entries, element NOT templateId-at-`+0x40`; **do not rely on it** — `+0x18` is the answer |

RepeatedField layout (universal in this build): `items_array_ptr @ +0x10`, `count(s32) @ +0x18`;
inside the array: `max_len(s32) @ +0x18`, element data begins at `+0x20` (8 bytes/elem).

### 2b. `QuestProto` (each active element)
| Offset | Field | Type | Verified by |
|---|---|---|---|
| `+0x10` | questType | s32 | dump_quests / v3 (3=story/TR, 4=challenge, 75=walk/`MP_WALK_QUEST`) |
| `+0x28` | questId | String* (UTF-16) | v3 (`questId` distinct from templateId for instanced challenges, e.g. `...:-631749975917826206`) |
| `+0x40` | templateId | String* (UTF-16) | all quest readers |
| `+0x48` | progress | s32 | all |
| `+0x50` | goal | GoalProto* | target `+0x18`, conditions `RepeatedField @ +0x10` |
| `+0x58` | status | s32 | all (1=ACTIVE, 2=COMPLETE; v3 maps 3=EXPIRED, 4=TARGETS_MET) |
| `+0x68` | createdMs | s64 | v3 (`createdMs`) |
| `+0x70` | lastUpdateMs | s64 | v3 |
| `+0x78` | completionMs | s64 | v3 (0 until claimed) |
| `+0xb0` | endMs | s64 | v3 (event window end; future for live event headers) |

### 2c. MultiPart sub-quests (for `STORY_QUEST_WAINA23_1`-style multi-day TRs)
From `walk_waina_subquests.py` (ran successfully). `QuestProto.get_MultiPart()` lives on
`Holoholo.Rpc.QuestProto` in **`holo-protos.dll`**; returns `MultiPartQuestProto` whose
`SubQuests` is a `RepeatedField<QuestProto> @ +0x10`. Each sub-quest QuestProto uses the same
offsets as 2b (questId `+0x28`, templateId `+0x40`, progress `+0x48`, goal `+0x50`,
status `+0x58`).

### 2d. `QuestDisplayProto` (human-readable text) — `GetQuestDisplayProto(questId)`
This is what made `quests_v3_dump.json` readable. Pass the **questId string** (not templateId)
as arg1. Returns a display proto:
| Offset | Field | Type | Notes |
|---|---|---|---|
| `+0x20` | descKey | String* | i18n key, feed to `I18n.Text` |
| `+0x28` | titleKey | String* | i18n key |
| `+0x38` | subTasks | `RepeatedField<sub>` | each sub: title key `+0x28`, desc key `+0x20` |
| `+0x58` | tagString key | String* | i18n key |
| `+0x70` | iconName | String* | raw asset name |

### 2e. i18n resolution — `Niantic.Holoholo.Internationalization.I18n.Text(key)`
Capture the `I18n` singleton the same way (hook its methods). `Text(string)` → localized
`String*`. v3 already wires this; titles like `"Catch {0} Grass-type Pokémon"` and
`"Track sleep using Pokémon GO Plus + for {0} days"` came straight out of it. Note the
`{0}` placeholders are NOT filled — the numeric target comes from `goal.target` (2b).

### 2f. Reward reads (the part still worth expanding)
- **Pokémon encounter reward:** `QuestService.GetPokemonEncounterForQuest(questProto*)` (1-arg,
  pass the QuestProto pointer). `read_quest_details.py` reads `pid` at `enc+0x10`. This is the
  cleanest path to "what Pokémon does this quest give" and to locating the Mewtwo step.
- **Item rewards:** not yet decoded. The encounter method only returns the mon. Items live in
  the quest's reward/`QuestRewardProto` list — candidate next target is
  `GetQuestDisplayProto` siblings or a `get_Rewards`/`QuestRewardsProto` on the QuestProto
  (DEVICE-VALIDATE: enumerate QuestProto methods for a `Rewards`/`Reward` getter; the proto is
  `Holoholo.Rpc.QuestRewardProto` per metadata).

---

## 3. Medals — how District/City completion is actually recorded

Completing a District (set of City challenges) does not leave a quest; it grants a **medal**.
Source: `tgt_medals.json` (this session's medal facet recon) + `_metadata_strings.txt`.

- **Authoritative unit:** `Holoholo.Rpc.PlayerBadgeProto` — holds `BadgeType` (HoloBadgeType
  enum) and a `Tiers` `RepeatedField<PlayerBadgeTierProto>` (each tier: `TierIndex`,
  `CurrentValue`). Tier index 1=bronze,2=silver,3=gold,4=platinum.
- **Live access:** `Niantic.Holoholo.Badges.BadgeService` (inject-bound service). Resolve via
  liveness scan (`pg.find_singleton('Niantic.Holoholo.Badges','BadgeService')`) or hook its
  methods. Then `GetPlayerBadgeRank(badgeType)` for tier, or walk the cached
  `PlayerBadgeProto` list. `PlayerBadgeProtoExt` (also liveness-scannable) adds precomputed
  `CurrentProgressPercent` / `IsLocked`.
- **Relevant medal enum names (confirmed in metadata):** `BadgeGofest`, `BadgeChallengeQuests`,
  `BadgeCityExplorerPass`, `BadgeChicagoFestJuly`, `BadgeSafari`, `BadgeSafariZoneEurope`,
  `BadgeGlobalTicketedEvent`, `BadgePartnerEvent`, and the generic event-medal slots
  `BadgeEvent0001 … BadgeEvent00NN`. A 2026 APAC/Tokyo district medal is almost certainly one
  of the `BadgeEvent00NN` slots or `BadgeGofest` — DEVICE-VALIDATE by reading the live
  `PlayerBadgeProto` set and matching the `CurrentValue` change to the district you finished.
- **Why this matters for the model:** "Did I finish the District?" is answered by the **medal**
  (persists forever) + the **completedIds** echo of the underlying City TRs — never by the
  active quest list, which is empty for finished challenges.

---

## 4. The GO Fest 2026 Mewtwo — DB cross-reference (pid 150)

`pokemon.db` (the real one: `pogo_extract/pokemon.db`, 25 MB; the root
`Phone Maintenance/pokemon.db` is a 0-byte stub — ignore it).

14 Mewtwo rows total. The two GO-Fest-2026 catches are unmistakable:

| uid (signed) | CP | IV | shiny | fresh_has_location_card | fresh_loc_card_enum | in current fresh_poll.json? |
|---|---|---|---|---|---|---|
| `7411975807261094796` | 2363 | 41 | 0 | **1** | **NULL** | **NO** |
| `5744441765404633224` | 2362 | 41 | 0 | **1** | **NULL** | **NO** |

(CP ~2362 / IV 41 with no costume, no nickname, traded-flag clear = the raid-caught GO Fest
research Mewtwo. The other 12 rows are older Mewtwo: a hundo `Mew2Hundo` from 2024, a
Photobombed one from 2026-03, NYC 2025, etc. — none GO-Fest-2026.)

### 4a. Why the enum is NULL (root cause, fully traced)
1. `fresh_poll.js` captures, for any Pokémon whose `displayProto+0x58` (LocationCard
   sub-message) is non-null, 0x40 raw bytes as `locBytes`, and counts it in `withLoc`.
2. `parse_fresh.py` decodes the **enum from `locBytes[+0x10]`** → `fresh_loc_card_enum`, and
   sets `fresh_has_location_card = 1 if locBytes present`.
3. **But** `parse_fresh.py` line ~46 first does `UPDATE pokemon SET <all fresh_*>=NULL`, then
   only re-populates rows **present in the current `fresh_poll.json`**. And line ~80-83: if a
   polled record has **no `displayBytes`**, it sets `fresh_in_heap=1` and `continue`s —
   skipping the location parse entirely.
4. The current `fresh_poll.json` has **5483** records (`stats.withLoc=108`), and **neither
   Mewtwo uid is in it** (verified: `present: False` for both). So the latest parse wiped their
   `fresh_loc_card_enum` to NULL and never re-set it.
5. The surviving `fresh_has_location_card=1` is a **stale flag** from an *earlier* poll
   (a prior `fresh_poll.json` / `full_inventory_v3.json` pass that DID have them in heap and
   saw `locBytes`). That earlier pass set the boolean but the column for the enum got reset.

Net: **the flag is trustworthy (these two genuinely have a location card), the enum is just
un-rehydrated.** 113 rows have the flag; **10** of them (incl. both Mewtwo) have a NULL enum —
all are simply "not in the most recent poll."

### 4b. What the enum should be
The Mewtwo location-card overlays are baked into the LocationCard enum
(`location_card_enum.json`, sourced from `holo-protos.dll`):

```
245 = Lc2026TokyoGofest001                 (the IRL Tokyo city-challenge card)
247 = LcSpecialbackground2026GlobalGofest001
248 = LcSpecialbackground2026Mewtwo001      <- GO Fest 2026 Mewtwo card
249 = LcSpecialbackground2026Mewtwo002      <- GO Fest 2026 Mewtwo card
250 = LcSpecialbackground2026Mewtwo003      <- GO Fest 2026 Mewtwo card
```
All five strings are confirmed present in `_metadata_strings.txt`. The APAC/Tokyo GO Fest
Mewtwo caught from research should resolve to one of **248–250** (likely keyed to the global
Mewtwo background tier), and a Mewtwo caught *in-Tokyo* could instead carry **245**
(`Lc2026TokyoGofest001`). Which one is on each of the two catches is the single fact a re-poll
recovers.

---

## 5. "What read would have answered each question correctly" — the lookup table

| Question we asked this session | WRONG approach we hit | RIGHT read |
|---|---|---|
| Did the GO Fest City challenge complete? | scan only active `+0x10` (it vanished) | read `completedIds` at `QuestsProto+0x18`; corroborate with medal |
| Did the District complete? | look for a quest | read `PlayerBadgeProto` via `BadgeService` (`BadgeGofest`/`BadgeEvent00NN`); tier `CurrentValue` |
| What is this quest, in English? | read templateId only | `GetQuestDisplayProto(questId)` + `I18n.Text(titleKey/descKey)` (offsets §2d/2e) |
| What is the goal number? | guess from text `{0}` | `QuestProto.goal.target` at `goal+0x18` |
| What Pokémon does the quest give (where's Mewtwo)? | infer from name | `GetPokemonEncounterForQuest(questProto)` → pid at `enc+0x10` |
| What location card is on this Mewtwo? | trust DB `fresh_loc_card_enum` (NULL) | re-poll with mon in heap → `locBytes[+0x10]` → map via `location_card_enum.json` |
| Is this Mewtwo a GO-Fest catch at all? | — | DB `fresh_has_location_card=1` + CP~2362/IV41 + no costume/trade flags |
| Multi-day TR sub-step progress? | read parent progress | `QuestProto.get_MultiPart()` → SubQuests `+0x10`, per-sub `progress+0x48`/`status+0x58` |

---

## 6. Durable learnings (promote to memory)

- **Two quest lists, not one.** `QuestsProto+0x10` = active `RepeatedField<QuestProto>`;
  `QuestsProto+0x18` = completed `RepeatedField<string>` of templateIds. Completion *moves*
  a quest between them. Any "where did my finished challenge go" question is answered by `+0x18`.
- **Headers persist, instances don't.** `*_HEADER` / `*_SEASON_PASS_*` rows stay in active with
  `status==2` for the whole event window; individual challenges disappear on claim.
- **Completion → medal.** District/City/event completion is durably recorded as a
  `PlayerBadgeProto` medal (`BadgeService`), independent of the quest lists. Read medals for
  "did this ever happen" certainty.
- **Server-pushed vs DLL-baked.** Rotating *quest* templateIds (`QUEST_GOFEST2026_*`,
  `TR_GOFEST2026_IRL_CITY_*`, `WIN_MEWTWO`) are server-pushed and absent from static dumps —
  only a live `QuestsProto` walk sees them. *Location-card* enums and *medal* enums are baked
  into `holo-protos.dll` and fully mappable offline (`location_card_enum.json`,
  `_metadata_strings.txt`).
- **`fresh_*` columns are poll-scoped and reset each parse.** `parse_fresh.py` NULLs every
  `fresh_*` then repopulates only Pokémon present in the *current* `fresh_poll.json`. A leftover
  `fresh_has_location_card=1` with `fresh_loc_card_enum=NULL` means "had a card in a previous
  poll, not in the latest one" — NOT "no card." To read a specific mon's card you must poll it
  while it is in the heap (open it / its tab in PoGo).
- **Use questId, not templateId, for display + RPC.** Instanced challenges have
  `questId = templateId + ':' + <int>`; `GetQuestDisplayProto` and the Complete/Update RPCs key
  on `questId`.

---

## 7. Draft reader code (lead can run as-is)

Two readers. Both READ-ONLY. Both reuse the proven QuestService-singleton-by-hook pattern
(`dump_quests.py`) and the `pogo_il2cpp.py` helper conventions. **Every offset is already
validated by this session's successful runs**, except where flagged DEVICE-VALIDATE.

### 7a. `read_gofest_quests.py` — active + completed + display + encounter, in one pass
```python
"""READ-ONLY. Dump active quests (templateId/questId/progress/goal/status + English
title/desc via I18n + Pokemon-encounter reward) AND the completedIds list. Highlights
GO Fest / Mewtwo / City / District rows. Writes nothing. Static-validated offsets from
extract_quests_v3.py + read_quest_details.py."""
import sys, time, json, subprocess, frida

ADB = '100.98.158.56:5555'
pid = int(subprocess.check_output(['adb','-s',ADB,'shell','pidof com.nianticlabs.pokemongo']).decode().strip())
d = frida.get_device_manager().add_remote_device('127.0.0.1:27047')
sess = d.attach(pid)

# --- capture QuestService + I18n singletons by hooking every method (proven) ---
HOOK = r"""
var Q=null,I=null;
function init(){
  var il=Process.findModuleByName('libil2cpp.so');var A={};il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return new NativeFunction(A[n],r,a);}
  var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),cGM=b('il2cpp_class_get_methods','pointer',['pointer','pointer']),tA=b('il2cpp_thread_attach','pointer',['pointer']);tA(dG());
  var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;
  for(var a=0;a<na;a++){var i=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(i).readCString()==='holo-game.dll'){gi=i;break;}}
  [['Niantic.Holoholo.Quests','QuestService','Q'],['Niantic.Holoholo.Internationalization','I18n','I']].forEach(function(p){
    var c=cFN(gi,Memory.allocUtf8String(p[0]),Memory.allocUtf8String(p[1]));if(!c||c.isNull())return;
    var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
    while((m=cGM(c,it))&&!m.isNull()){try{var ad=m.readPointer();if(ad.isNull())continue;(function(lbl){Interceptor.attach(ad,{onEnter:function(ar){if(lbl==='Q'&&!Q)Q=ar[0].toString();if(lbl==='I'&&!I)I=ar[0].toString();}});})(p[2]);}catch(e){}}
  });
}
rpc.exports={setup:function(){init();return 1;},get:function(){return {q:Q,i:I};}};
"""
hs = sess.create_script(HOOK); hs.on('message', lambda m,d: None); hs.load(); hs.exports_sync.setup()
print('Open the Today/Research screen so QuestService + I18n fire...')
q=i=None
for _ in range(60):
    time.sleep(1); g=hs.exports_sync.get()
    if g.get('q'): q=g['q']
    if g.get('i'): i=g['i']
    if q and i: break
hs.unload()
if not (q and i):
    print('NO_INSTANCE (need both QuestService and I18n; interact with quest UI)'); sess.detach(); sys.exit(1)
print('QuestService', q, 'I18n', i)

WALK = r"""
rpc.exports={walk:function(qa,ia){
  var qi=ptr(qa),ii=ptr(ia);
  var il=Process.findModuleByName('libil2cpp.so');var A={};il.enumerateExports().forEach(function(e){if(e.name.indexOf('il2cpp_')===0)A[e.name]=e.address;});
  function b(n,r,a){return new NativeFunction(A[n],r,a);}
  var dG=b('il2cpp_domain_get','pointer',[]),dGA=b('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),aGI=b('il2cpp_assembly_get_image','pointer',['pointer']),iGN=b('il2cpp_image_get_name','pointer',['pointer']),cFN=b('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),cMN=b('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']),rI=b('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']),sNew=new NativeFunction(A['il2cpp_string_new'],'pointer',['pointer']);
  var sp=Memory.alloc(4),asms=dGA(dG(),sp),na=sp.readS32(),gi=null;
  for(var a=0;a<na;a++){var im=aGI(asms.add(a*Process.pointerSize).readPointer());if(iGN(im).readCString()==='holo-game.dll'){gi=im;break;}}
  var QS=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Quests'),Memory.allocUtf8String('QuestService'));
  var I18=cFN(gi,Memory.allocUtf8String('Niantic.Holoholo.Internationalization'),Memory.allocUtf8String('I18n'));
  function rs(p){if(p.isNull())return '';var l=p.add(0x10).readS32();if(l<=0||l>2000)return '';var c=[];for(var k=0;k<l;k++){var ch=p.add(0x14+k*2).readU16();if(ch===0)break;c.push(String.fromCharCode(ch));}return c.join('');}
  var tM=cMN(I18,Memory.allocUtf8String('Text'),1);
  function tr(key){if(!key)return '';try{var ks=sNew(Memory.allocUtf8String(key));var ar=Memory.alloc(8);ar.writePointer(ks);var ex=Memory.alloc(8);ex.writePointer(ptr(0));var r=rI(tM,ii,ar,ex);return r.isNull()?key:(rs(r)||key);}catch(e){return key;}}
  var gP=cMN(QS,Memory.allocUtf8String('get_QuestsProto'),0);
  var gD=cMN(QS,Memory.allocUtf8String('GetQuestDisplayProto'),1);
  var gE=cMN(QS,Memory.allocUtf8String('GetPokemonEncounterForQuest'),1);
  var ex=Memory.alloc(8);ex.writePointer(ptr(0));
  var po=rI(gP,qi,ptr(0),ex);if(po.isNull())return {error:'null proto'};
  function rf(p,asStr){if(p.isNull())return [];var arr=p.add(0x10).readPointer();var cnt=p.add(0x18).readS32();if(arr.isNull()||cnt<=0)return [];var ml=arr.add(0x18).readS32();var dat=arr.add(0x20);var o=[];for(var k=0;k<Math.min(cnt,ml,1000);k++){var e=dat.add(k*8).readPointer();o.push(asStr?rs(e):e);}return o;}
  var active=rf(po.add(0x10).readPointer(),false);
  var completed=rf(po.add(0x18).readPointer(),true);
  var out=[];
  for(var x=0;x<active.length;x++){
    var Qp=active[x];if(Qp.isNull())continue;
    var rec={questType:Qp.add(0x10).readS32(),questId:rs(Qp.add(0x28).readPointer()),templateId:rs(Qp.add(0x40).readPointer()),progress:Qp.add(0x48).readS32(),status:Qp.add(0x58).readS32(),createdMs:Qp.add(0x68).readS64().toString(),completionMs:Qp.add(0x78).readS64().toString(),endMs:Qp.add(0xb0).readS64().toString()};
    var g=Qp.add(0x50).readPointer();if(!g.isNull())try{rec.goalTarget=g.add(0x18).readS32();}catch(e){}
    // display (English)
    try{var qs=sNew(Memory.allocUtf8String(rec.questId));var ar=Memory.alloc(8);ar.writePointer(qs);var e2=Memory.alloc(8);e2.writePointer(ptr(0));var dp=rI(gD,qi,ar,e2);
      if(!dp.isNull()){rec.title=tr(rs(dp.add(0x28).readPointer()));rec.desc=tr(rs(dp.add(0x20).readPointer()));
        var sr=dp.add(0x38).readPointer();if(!sr.isNull()){var sa=sr.add(0x10).readPointer(),sc=sr.add(0x18).readS32(),subs=[];if(!sa.isNull()&&sc>0){var sd=sa.add(0x20);for(var s=0;s<Math.min(sc,20);s++){var ss=sd.add(s*8).readPointer();if(ss.isNull())continue;subs.push(tr(rs(ss.add(0x28).readPointer())));}}rec.subTasks=subs;}}
    }catch(e){}
    // pokemon encounter reward
    try{var a2=Memory.alloc(8);a2.writePointer(Qp);var e3=Memory.alloc(8);e3.writePointer(ptr(0));var enc=rI(gE,qi,a2,e3);if(!enc.isNull())rec.rewardPid=enc.add(0x10).readS32();}catch(e){}
    out.push(rec);
  }
  return {active:out,completedIds:completed};
}};
"""
sc = sess.create_script(WALK); sc.load()
r = sc.exports_sync.walk(q, i); sess.detach()
if 'error' in r: print('ERR', r['error']); sys.exit(1)
ST={0:'UNSET',1:'ACTIVE',2:'COMPLETE',3:'EXPIRED',4:'TARGETS_MET'}
KEY=('GOFEST','MEWTWO','IRL_CITY','DISTRICT','TOKYO','APAC','WAINA','2026')
print('\n=== ACTIVE (%d) ===' % len(r['active']))
for qd in r['active']:
    print('[%s] %s  q=%s  %s/%s' % (ST.get(qd['status'],qd['status']), qd['templateId'], qd.get('questType'), qd.get('progress'), qd.get('goalTarget','?')))
    if qd.get('title'): print('    title:', qd['title'])
    if qd.get('rewardPid'): print('    *** REWARD pid=%d ***' % qd['rewardPid'])
    for s in qd.get('subTasks',[]) or []: print('    -', s)
print('\n=== GO Fest / Mewtwo / City in completedIds ===')
for c in r['completedIds']:
    if any(k in c.upper() for k in KEY): print('  ', c)
print('\n(completedIds total: %d)' % len(r['completedIds']))
```

### 7b. `read_mewtwo_locationcard.py` — recover the Mewtwo card enum (fills the DB gap)
```python
"""READ-ONLY. For target UIDs (the GO Fest 2026 Mewtwo), walk the live bag proto,
read the PokemonDisplayProto.LocationCard sub-message, and map the enum via
location_card_enum.json. The two Mewtwo (CP2363/IV41 uid 7411975807261094796 and
CP2362/IV41 uid 5744441765404633224) MUST be in the heap -- open each one's detail
screen in PoGo first, or this returns 'no display'. Uses pogo_il2cpp helpers."""
import json, struct, sys
import pogo_il2cpp as pg

TARGET_UIDS = ['7411975807261094796', '5744441765404633224']  # signed; bag walk keys are unsigned strings
ENUM = {int(k): v for k, v in json.load(open('location_card_enum.json')).items()}

sess, _pid = pg.get_session()
bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')

# bag_walk returns {uid_unsigned_str: proto_ptr_str}; convert targets to unsigned
want = {str(int(u) & 0xFFFFFFFFFFFFFFFF): int(u) for u in TARGET_UIDS}
protos = pg.find_protos_for_uids(sess, bag, list(want.keys()))

READ = r"""
rpc.exports.readLoc = function(protoStr){
  var p = ptr(protoStr);
  var disp = p.add(0xd8).readPointer();          // PokemonProto.PokemonDisplay
  if (disp.isNull()) return {ok:false, why:'no display (mon not in heap?)'};
  var loc = disp.add(0x58).readPointer();         // displayProto.LocationCard sub-message
  if (loc.isNull()) return {ok:false, why:'no LocationCard set'};
  var enumVal = loc.add(0x10).readS32();          // LocationCard enum @ +0x10 (parse_fresh.py)
  return {ok:true, enumVal:enumVal};
};
"""
sc = pg.get_script_with_helpers(sess, READ)
print('uid (signed)            | card enum | card name')
for us, signed in want.items():
    pp = protos.get(us)
    if not pp:
        print('%-22s | (not in bag walk / out of heap)' % signed); continue
    r = sc.exports_sync.read_loc(pp)
    if not r.get('ok'):
        print('%-22s | -- %s' % (signed, r.get('why'))); continue
    ev = r['enumVal']
    print('%-22s | %-9d | %s' % (signed, ev, ENUM.get(ev, '??(%d)' % ev)))
sc.unload(); sess.detach()
# Expectation: enum 248/249/250 (LcSpecialbackground2026Mewtwo001/002/003) or 245 (Lc2026TokyoGofest001).
```

### 7c. `read_event_medals.py` — District/City completion as a medal (DEVICE-VALIDATE offsets)
```python
"""READ-ONLY. Liveness-scan PlayerBadgeProto and dump GO-Fest/event medals with tier.
Confirms District/City completion the durable way. PlayerBadgeProto field offsets for
BadgeType / Tiers are NOT yet pinned in this repo -> DEVICE-VALIDATE before trusting.
Approach proven; offsets need one confirmation pass."""
import pogo_il2cpp as pg

sess, _ = pg.get_session()
PROBE = r"""
rpc.exports.dumpBadges = function(){
  _ensureInit();
  // liveness scan for every PlayerBadgeProto
  var cls = IL2.cFN(/*holo-protos image*/0, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('PlayerBadgeProto'));
  // NOTE: cFN helper uses GAME_IMAGE; PlayerBadgeProto is in holo-protos.dll.
  // DEVICE-VALIDATE: resolve via holo-protos image (see walk_waina_subquests pattern that
  // also looks up holo-protos), then liveness_find_instances(cls).
  return {todo:'resolve holo-protos image + iterate; read BadgeType(enum) and Tiers RepeatedField; map enum via HoloBadgeType names'};
};
"""
# Recommended concrete path (matches tgt_medals.json notes):
#  1. find_singleton('Niantic.Holoholo.Badges','BadgeService')
#  2. call GetPlayerBadgeRank(badgeType) for each candidate Badge* enum (BadgeGofest,
#     BadgeChallengeQuests, BadgeCityExplorerPass, BadgeEvent0001..00NN), OR
#  3. liveness_find_instances on Holoholo.Rpc.PlayerBadgeProto (resolve cls via holo-protos
#     image), then per-instance read BadgeType + Tiers[last].CurrentValue.
print('See gofest_data_model.md section 3. BadgeService singleton + GetPlayerBadgeRank is the '
      'lowest-risk read; PlayerBadgeProto field offsets need one DEVICE-VALIDATE pass.')
sess.detach()
```

---

## 8. Device-validation checklist (hand to the lead with the serial)

1. **(low risk, high value)** Run `read_mewtwo_locationcard.py` with both Mewtwo detail screens
   opened first. Expect enum **248/249/250** (or **245** if Tokyo-local). This closes the DB gap
   — then re-run a targeted `fresh_poll` + `parse_fresh` so `fresh_loc_card_enum` persists.
2. **(low risk)** Run `read_gofest_quests.py` on the Research screen to re-confirm:
   - active `+0x10` GO Fest rows + their English titles + `rewardPid` (find the Mewtwo step),
   - `completedIds` `+0x18` contains the finished `TR_GOFEST2026_IRL_CITY_*` / district ids.
3. **(needs offset confirmation)** Pin `Holoholo.Rpc.PlayerBadgeProto` `BadgeType` and `Tiers`
   offsets, then dump the event medals to identify the exact 2026 District medal enum slot.
4. **Items reward decode** (unstarted): enumerate `Holoholo.Rpc.QuestProto` methods for a
   `Rewards`/`Reward`/`QuestRewardProto` getter to read item rewards (currently only the
   Pokémon encounter reward is decodable).

### Offsets that are PROVEN this session (safe to reuse)
- `QuestsProto`: active `+0x10`, completedIds `+0x18`.
- `QuestProto`: questType `+0x10`, questId `+0x28`, templateId `+0x40`, progress `+0x48`,
  goal `+0x50` (target `+0x18`), status `+0x58`, createdMs `+0x68`, lastUpdateMs `+0x70`,
  completionMs `+0x78`, endMs `+0xb0`.
- `QuestDisplayProto`: descKey `+0x20`, titleKey `+0x28`, subTasks `+0x38` (sub title `+0x28`,
  sub desc `+0x20`), tagKey `+0x58`, iconName `+0x70`.
- `PokemonDisplayProto.LocationCard`: sub-message ptr at displayProto `+0x58`; enum at
  `locBytes+0x10`. Pokémon display proto at `PokemonProto+0xd8`.
- MultiPart: `QuestProto.get_MultiPart()` (holo-protos) → SubQuests `RepeatedField +0x10`.

### Offsets / paths that need DEVICE-VALIDATE
- `PlayerBadgeProto.BadgeType` and `.Tiers` field offsets (and which image resolves the class).
- A `QuestProto` item-reward getter (`QuestRewardProto` list) — not yet located.
- Exact 2026 District/APAC medal enum value within `BadgeEvent00NN` / `BadgeGofest`.
