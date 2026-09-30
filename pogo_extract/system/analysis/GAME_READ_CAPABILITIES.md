# GAME_READ_CAPABILITIES — PoGo live IL2CPP read map (consolidated)

**Date:** 2026-05-29 · **Mode:** synthesized from 6 STATIC recon passes (no device used to produce this).
**Goal:** read PoGo's live IL2CPP internals (`holo-game.dll` services, `holo-protos.dll`
`Holoholo.Rpc.*` protos) beyond raw templateIds — human titles/descriptions, step/sub-quest
structure, goal conditions, REWARDS (items + Pokémon encounters + mega energy), inventory,
medals, and completion state.

> **The single biggest leverage upgrade (do this once):** pull `libil2cpp.so` from the device
> and run **Il2CppDumper** against it + `pogo_extract/global-metadata.dat` (v31, magic
> `0xFAB11BAF`, 38 MB — confirmed parseable). That produces `dump.cs` with the exact `// 0xNN`
> offset of *every* field, eliminating all runtime offset-probing below in one shot. Until then,
> field *identity/order* is ground truth (via `meta_dump.py`) but byte offsets are runtime-inferred.

---

## 0. How to read this document

Three asset tiers back every claim:

| Tier | What | Trust |
|---|---|---|
| **PROVEN (live)** | An offset/path a script in this repo already ran successfully and got correct values. | Reuse as-is. |
| **STATIC-AUTHORITATIVE** | Type/field/enum identity + declaration order from `global-metadata.dat` via `meta_dump.py`. NOT byte offsets. | The field *exists and is at this index*; offset is derived, validate once. |
| **INFERRED / [DEVICE]** | Offset or behavior guessed from convention or accessor ordering. | Must be device-validated before trusting. |

Every offset table below tags its rows. The runnable scripts (`system/scripts/game_read/`) are
built so the **accessor-invoke path is offset-free** wherever possible (`il2cpp_runtime_invoke`
of the C# getters), and fixed offsets are used only where PROVEN.

### Static lookup tool (no device) — `meta_dump.py`
`pogo_extract/system/analysis/game_read_recon/meta_dump.py` parses the metadata standalone:
```
python meta_dump.py QuestProto                            # field list (index:name) — declaration order
python meta_dump.py --ns Holoholo.Rpc PlayerStatsProto    # disambiguate by namespace
python meta_dump.py --enum QuestRewardProto.RewardOneofCase   # nested enum members + values
python meta_dump.py --grep Badge                          # find type FQNs by substring
```
Verified working this session. Use it to (a) re-confirm field order after any PoGo update, and
(b) map "field index N" → "the Nth 8-byte/packed slot after the 0x10 arm64 object header."

### Helper surface the scripts reuse (`pogo_extract/pogo_il2cpp.py`)
- `pg.get_session()` → `(frida.Session, pid)` — handles adb connect/forward/pidof + attach with
  PID-drift retry + 15 s hard timeout (fails fast if frida-server is down). Targets Tailscale
  `100.98.158.56:5555` → frida `127.0.0.1:27047`.
- `pg.find_singleton(sess, ns, cls)` → ptr-str; **asserts exactly 1** liveness hit.
- `pg.pick_singleton(sess, ns, cls)` → ptr-str; multi-instance aware. **Has tuned probes only for
  `PokemonBagImpl`, `TaggingRpcService`, `PokedexImpl`; for any other class it returns the FIRST
  hit** (see §6 multi-instance caveat).
- `pg.get_script_with_helpers(sess, extra_js)` → loaded `frida.Script`. The preamble already
  defines `rpc.exports = {...}`, so **`extra_js` must ADD exports via `rpc.exports.foo = function(){...}`,
  never redefine `rpc.exports`** (mirror `_SVC_PROBE_JS`).
- JS preamble helpers available to `extra_js`: `cFN(ns,cls)` (**binds `holo-game.dll` ONLY**),
  `cMN(klass,name,argc)`, `rI(method,inst,args,exc)`, `_ensureInit()`, raw `IL2.*` bindings,
  `liveness_find_instances(klass)`, `bag_walk(addr,filterUids)`.
- **Gap to know:** the preamble does NOT bind `il2cpp_object_get_class` / `il2cpp_class_get_name`
  / a `holo-protos.dll` image handle. Proto types (`Holoholo.Rpc.*`) live in `holo-protos.dll`,
  so `cFN` (game image) won't resolve them. The scripts below add those bindings themselves and
  prefer `il2cpp_object_get_class(liveObject)` to get a proto's runtime class for accessor calls.
- Frida camelCase→snake_case: a JS export `readResearch` is called from Python as
  `script.exports_sync.read_research(...)`.

---

## 1. QUESTS / RESEARCH (active tasks, titles, steps, conditions, completion)

**Service:** `Niantic.Holoholo.Quests.QuestService` (`holo-game.dll`).
**Singleton capture:** hook every method of `QuestService` (and `I18n`), grab `args[0]` on first
fire — the Today/Research screen must be open so a method fires (PROVEN pattern, `dump_quests.py`).
`QuestService` reliably came through as a single hooked `this` in all prior runs.

### 1a. `QuestsProto` (from `QuestService.get_QuestsProto()`) — the two-list model
| Offset | Field | Type | Tier |
|---|---|---|---|
| `+0x10` | **active quests** | `RepeatedField<QuestProto>` | **PROVEN** (`extract_quests_v3.py`) |
| `+0x18` | **completedIds** | `RepeatedField<String>` of bare templateIds (582 entries on this acct) | **PROVEN** |
| `+0x20` | second ~78-entry list | element NOT `QuestProto` (templateId not at +0x40) | **[DEVICE]** — read element class via `il2cpp_object_get_class` first; likely `ProgressedQuests`/`ClientQuestProto` |

> **Critical lifecycle fact:** completing a challenge does NOT set `status=2` in the active list —
> the client **removes** the `QuestProto` from `+0x10` and pushes its templateId string into
> `completedIds` at `+0x18`. `*_HEADER` / `*_SEASON_PASS_*` container rows *persist* in `+0x10`
> with `status==2` for the event window. So "where did my finished challenge go?" is answered by
> `+0x18`, never by scanning only `+0x10`. The "78-entry +0x20 list" is NOT the completed list.

RepeatedField layout (universal this build, **PROVEN**): backing array `@+0x10`, count(s32) `@+0x18`;
inside array, element data starts at `+0x20`, stride 8 bytes (refs) or 4 bytes (int/enum).

### 1b. `QuestProto` scalar offsets (all **PROVEN** by `extract_quests_v3.py`)
Static metadata field order confirms each (`meta_dump.py QuestProto`): index→name in brackets.
| Offset | Field | Type | meta idx |
|---|---|---|---|
| `+0x10` | questType | s32 enum `QuestType` | [1] |
| `+0x28` | questId | String* (UTF-16) — instance id; use for display/RPC lookups | [4] |
| `+0x40` | templateId | String* (e.g. `STORY_QUEST_WAINA23_1`) | [7] |
| `+0x48` | progress | s32 (live count) | [8] |
| `+0x50` | goal | `QuestGoalProto*` (Target@+0x18, Conditions `RF`@+0x10) | [9] |
| `+0x58` | status | s32 (1=ACTIVE, 2=COMPLETE; 3=EXPIRED/claimed, 4=TARGETS_MET — 3/4 guessed) | [10] |
| `+0x68` | createdMs | s64 | [13] |
| `+0x70` | lastUpdateMs | s64 | [14] |
| `+0x78` | completionMs | s64 (0 until claimed) | [15] |
| `+0x80` | fortId | String* (field-research fort) | [16] |
| `+0xb0` | endMs | s64 (event window end; future for live event headers) | — |

**String (UTF-16) layout (PROVEN):** length(s32)@`+0x10`, chars@`+0x14` (2 bytes each).

### 1c. Goals — live x/target + which condition counts (the priority gap)
- `QuestGoalProto.Target` (s32) @ `+0x18` — the number ("Catch **7**") — **PROVEN**.
- `QuestGoalProto.Conditions` = `RepeatedField<QuestConditionProto>` @ `+0x10` — **PROVEN offset**.
- **Ambiguity to lock [DEVICE]:** `QuestProto+0x50` is read as a *single* `QuestGoalProto` by v3,
  but metadata declares `Goal` and some catch tasks came back with an empty target — so `+0x50`
  may be a single goal OR a `RepeatedField<QuestGoalProto>`. The reader auto-detects (treats it as
  a RF only if `count@+0x18` and the backing array look sane), but **validate and lock the branch**.
- **Condition type** = `QuestConditionProto.get_ConditionCase()` (oneof tag). Full oneof name list
  (STATIC-AUTHORITATIVE) is in `QUESTS_TIMED_RESEARCH.md §3` — e.g. `WithPokemonType`,
  `WithThrowType`, `WithWeatherBoost`, `WithDistance`, `WithItem`, … (58 cases).
- **The verb that counts** = `QuestProto.get_QuestCase()` (oneof): `DailyQuest, MultiPart, AddFriend,
  TradePokemon, QuestWalk, EvolveIntoPokemon, GetStardust, Battle, TakeSnapshot, TravelRoute,
  SpinPokestop, PokemonReachCp, SpendStardust, …`.
- **Complete task description = QuestCase (verb) + Goal.Target (number) + ConditionCase(s) (qualifier).**

### 1d. Sub-quest structure (story / multi-part) — **PROVEN** (`walk_waina_subquests.py`)
- `QuestProto.get_MultiPart()` (on `Holoholo.Rpc.QuestProto`, `holo-protos.dll`, 0-arg) →
  `MultiPartQuestProto`.
- `MultiPartQuestProto.SubQuests` = `RepeatedField<QuestProto>` @ `+0x10`.
- Each sub-quest is a full `QuestProto` (same §1b offsets). Many active "quests" are
  headers/containers (questType 3, templateId ends `_HEADER`, progress 0, no goal) whose real
  per-step tasks live in `SubQuests`. The reader calls `get_MultiPart()` on every active quest;
  non-multipart returns null and is skipped.

### 1e. Human title / description / sub-step text — **PROVEN** (`extract_quests_v3.py`)
- `QuestService.GetQuestDisplayProto(questId : String)` → `QuestDisplayProto`. **Pass the
  questId string (NOT templateId).** Build the managed string with `il2cpp_string_new(utf8)`.
- `QuestDisplayProto` offsets (**PROVEN** from v2/v3): descKey `+0x20`, titleKey `+0x28`,
  subTasks `RF` `+0x38` (each sub: titleKey `+0x28`, descKey `+0x20`), tagString key `+0x58`,
  iconName `+0x70`.
- Resolve keys → localized text via `I18n.Text(key : String)` (capture the `I18n` singleton the
  same way). Localized strings keep `{0}`/`{1}` placeholders ("Catch {0} Grass-type Pokémon");
  fill `{0}` from `Goal.Target` client-side, or use `I18n.TextFormat(key, args)`.
- Fallback owner if `GetQuestDisplayProto` ever stops resolving on `QuestService` after an update:
  `Niantic.Holoholo.Quests.QuestRpcService` is the metadata-canonical owner.

### 1f. Confidence + what needs the device (Quests)
- **PROVEN:** active/completed lists, all §1b scalar offsets, goal Target/Conditions offsets,
  MultiPart path, display proto offsets + I18n resolution.
- **[DEVICE]:** (1) lock single-vs-RF for `Goal@+0x50`; (2) classify the `+0x20` second list via
  `il2cpp_object_get_class`; (3) confirm `Status`/`QuestType` enum ordinals (dump from holo-protos);
  (4) confirm a sample ConditionCase tag (e.g. "Catch 7 Grass" → `WithPokemonType`).

**Reader:** `system/scripts/game_read/dump_research_full.py`.

---

## 2. REWARDS (items + Pokémon encounter + mega energy) — the headline expansion

**Proto:** `Holoholo.Rpc.QuestRewardProto` is a **oneof** — `meta_dump.py QuestRewardProto` shows
just `[1] Type, [2] conc, [3] cond` (the case-tag + value-union are obfuscated). **Therefore the
ONLY robust read is the accessor path** (call the C# getters; the active arm is the non-null one).
Do NOT decode rewards by raw offset.

### 2a. Getting the reward list per quest (two routes, both **[DEVICE]** to confirm getter name)
- **Route B (preferred, offset-free):** `QuestProto.get_QuestRewards()` →
  `RepeatedField<QuestRewardProto>` (walk with the universal RF layout). Probe `get_QuestRewards`
  first, fall back to `get_Rewards`. Metadata field is `QuestRewards` = `QuestProto[12]`.
- **Route A:** `QuestRpcService.GetQuestRewardProtos(...)` (canonical owner) — arity unknown
  statically; the reader probes both `QuestService` and `QuestRpcService` for the method.

### 2b. Decoding one `QuestRewardProto` (accessor switch — order matters; gate on RewardCase)
`case = get_RewardCase()` (boxed enum int @ ret`+0x10`) for logging, then call each getter; the
active oneof field is the non-null/non-zero one. **RewardOneofCase members (STATIC-AUTHORITATIVE,
`meta_dump.py --enum QuestRewardProto.RewardOneofCase`) — the integer values are mangled C# case
constants, do NOT hard-code them:**
```
None, Exp, Item, Stardust, Candy, AvatarTemplateId, QuestTemplateId, PokemonEncounter,
Pokecoin, XlCandy, LevelCap, Sticker, MegaResource, Incident, PlayerAttribute, EventBadgeId,
NeutralAvatarTemplateId, NeutralAvatarItemTemplate, NeutralAvatarItemDisplay, PokemonEgg,
PokemonIndividualStat, LootTable, FriendshipPoints, TempEvoResource
```
(raw ints e.g. Item=201984006, PokemonEncounter=370414096, MegaResource=538844186 — present in
metadata but **case-by-getter dispatch is what the reader uses**.)

Accessors confirmed present (invoke per `QuestRewardProto`): `get_RewardCase`, `get_Item`,
`get_PokemonEncounter`, `get_MegaResource`, `get_TempEvoResource`, `get_Stardust`, `get_Candy`,
`get_PokemonCandy`, `get_Exp`, `get_Pokecoin`, `get_XlCandy`, `get_Sticker`, `get_PokemonEgg`,
`get_LootTable`, `get_LevelCap`, `get_FriendshipPoints`, `get_QuestTemplateId`, `get_AvatarTemplateId`.

| Reward arm | Getter → sub-proto | Read | Tier |
|---|---|---|---|
| **Item** | `get_Item()` → `ItemProto` | `Item`(enum)@+0x10, `Count`@+0x14 | STATIC-AUTHORITATIVE layout (idx [1][2]); offsets PROVEN by inventory recon |
| **Pokémon encounter** | `get_PokemonEncounter()` → `PokemonEncounterRewardProto` | see §2c | STATIC names / [DEVICE] offsets |
| **Mega / temp-evo energy** | `get_MegaResource()`/`get_TempEvoResource()` → `TempEvoResourceRewardProto` → inner `TemporaryEvolutionResourceProto` | see §2d | STATIC names / [DEVICE] |
| Stardust / Exp / Pokecoin / LevelCap / FriendshipPoints | `get_Stardust()` etc. (int32) | boxed int @ ret`+0x10` | [DEVICE] confirm boxed-payload offset |
| Candy / XlCandy | `get_Candy()`/`get_PokemonCandy()` → candy proto | PokemonId + Amount | STATIC names / [DEVICE] |

### 2c. `PokemonEncounterRewardProto` — "this research gives a Mega Mewtwo encounter"
(via accessors; `enc = get_PokemonEncounter()`; call getters against `il2cpp_object_get_class(enc)`):
- `get_PokemonId()` → `HoloPokemonId` (boxed enum @+0x10; 150 = Mewtwo). Map via species table.
- `get_PokemonDisplay()` → `PokemonDisplayProto`: `get_Form()`, `get_Costume()`, `get_Gender()`
  (1=M,2=F,3=genderless), `get_Shiny()` (bool), `get_Alignment()` (shadow/purified).
- `get_ShinyProbability()` (boxed float @+0x10; guaranteed-shiny research = 1.0),
  `get_IsFeaturedPokemon()` (bool).
- **Mega X vs Y for the encounter** comes from the *co-listed* MegaResource reward (§2d), whose
  `TemporaryEvolutionId` is authoritative — OR a temp-evo marker on the display. GO-Fest "choose
  Mega Mewtwo X or Y" = two separate quests/branches; read each branch's encounter+megaresource pair.
- If `get_PokemonId()==0` (distribution-based reward), call
  `RewardPreviewModalGuiController.PokemonToDisplayForEncounterReward(enc)` or read
  `PokemonEncounterDistribution` to get the concrete species. **[DEVICE]**.
- **Live spawned encounter** (completed quest only): `QuestService.GetPokemonEncounterForQuest(qp)`
  → `QuestEncounterProto`, pid @ `enc+0x10`. **Returned null this session for in-progress quests
  — that's correct** (the encounter materializes only when the quest is COMPLETE/claimable). For the
  *intended reward species* regardless of completion, use `QuestRewardProto.PokemonEncounter` above.
  If still null on a complete quest, feed a `get_Quests()` element (likely `ClientQuestProto`) instead
  of the raw `QuestProto`. **[DEVICE]**.

### 2d. `TempEvoResourceRewardProto` → mega energy (the X/Y authority)
- Inner getter name **[DEVICE]** (probe `get_TempEvoResource`/`get_Resource`/`get_TemporaryEvolutionResource`)
  → `TemporaryEvolutionResourceProto`:
  - `get_PokemonId()` → species the energy is for,
  - `get_TemporaryEvolutionId()` → `HoloTemporaryEvolutionId` enum: `TEMP_EVOLUTION_MEGA`(1?),
    `_MEGA_X`(2?), `_MEGA_Y`(3?), `_PRIMAL`(4?) — **ordinals [DEVICE]**. (Mewtwo X-vs-Y is exactly this.)
  - `get_Amount()` / `get_MaxEnergyCount()` → energy quantity.
- So "Mega Mewtwo X encounter + 100 Mega Energy" = TWO reward entries: a `PokemonEncounter` (Mewtwo)
  and a `MegaResource` (pid=Mewtwo, TemporaryEvolutionId=MEGA_X, amount=100).

### 2e. Confidence + what needs the device (Rewards)
- **STATIC-AUTHORITATIVE:** the reward oneof member list and accessor names; ItemProto layout.
- **[DEVICE]:** reward-list getter name (`get_QuestRewards` vs `get_Rewards`); per-arm getter
  behavior + boxed-payload `+0x10` for int/bool/float; encounter species getter; MegaResource inner
  getter + `TemporaryEvolutionId` ordinals; whether the encounter reward carries its own temp-evo.

**Reader:** `system/scripts/game_read/dump_research_full.py` (rewards are integrated into the
per-quest decode; a `--probe` mode dumps raw oneof getters on the first reward to lock the int map).

---

## 3. MEDALS / BADGES (event medals, GO Fest districts, progress medals)

**Three "badge" concepts — we care about #1 (the medals UI):**
| # | Concept | Storage | Path |
|---|---|---|---|
| 1 | **Player medals** (Jogger, Kanto, GO Fest district…) | `PlayerStatsProto` | `IPlayerService.get_PlayerStats` |
| 2 | Gym badges (per-gym tier) | `GymBadgeService` | `GymBadgeService.GetGymBadgeData` |
| 3 | Badge visuals (sprites) | `BadgeService` | not needed for "what's earned" |

### 3a. The earned event/district medal list — **DEVICE-VALIDATED offset (2026-05-21 recon)**
`PlayerStatsProto.EventBadges` = `RepeatedField<HoloBadgeType>` @ **+0xB8 (184)**.
Each element is a 4-byte `HoloBadgeType` enum int. **This is where GO Fest district / "Friendship
District" medals live.** Static metadata confirms `EventBadges` = `PlayerStatsProto[34]`
(`meta_dump.py --ns Holoholo.Rpc PlayerStatsProto`).
- `RepeatedField<int|enum>` layout (**PROVEN**, `pogo_pipeline.py` CapturedForms walk): array
  `RF+0x10`, count `RF+0x18`, element i = `array+0x20+i*4`.
- Progress medals (Jogger/Collector/…) are NOT a list — each is a scalar counter on
  `PlayerStatsProto` (DEVICE-VALIDATED offsets in `medals_badges.md §2`): `KmWalked`@+0x30,
  `NumPokemonCaptured`@+0x3C, `NumChallengeQuestsCompleted`@+0xC4, `NumTotalMegaEvolutions`@+0x128,
  `NumForeverFriendsEarned`@+0x1A8, etc. Tier (bronze/…/platinum) is computed client-side from
  GAME_MASTER thresholds, or read per-medal via `BadgeService.GetPlayerBadgeRank` (§3c).

### 3b. The `HoloBadgeType` enum — and the CRITICAL 2026 gap
- C# enum `HoloBadgeType` (`Holoholo.Rpc`). **2026 / Tokyo / District / "Friendship District"
  constants are NOT in ANY static dump** (`_metadata_strings.txt` stops at GOWA 2025) — they exist
  ONLY in the live `holo-game.dll`. **So the reader MUST enumerate the enum at runtime** to name
  the ints in `EventBadges`.
- Runtime enum dump (**PROVEN** pattern, `dump_form_enum.py`): iterate `il2cpp_class_get_fields`,
  keep fields with flags `& 0x10` (STATIC) **and** `& 0x40` (LITERAL/const), read each via
  `il2cpp_field_static_get_value(field, buf)` → `buf.readS32()`, build `{value: name}`.
- GO Fest 2026 district themes are publicly Friendship/Adventure/Discovery/Nostalgia/Mischief — the
  enum constants will encode these in the event-badge range.

### 3c. Read recipes
- **PRIMARY:** `find`/`pick_singleton('Niantic.Holoholo','PlayerService')` → `get_PlayerStats()`
  → read `EventBadges` RF + counters → `dumpEnum('Holoholo.Rpc','HoloBadgeType')` → join ints to
  names → filter by `gofest|district|friendship|city|safari|gotour|gowa`. **PlayerService must be
  live → be on map or open Trainer profile.**
- **SECONDARY (no PlayerService):** walk `InventoryCache` for the `HoloInventoryItemProto` whose
  oneof is PlayerStats (`get_PlayerStats` → `PlayerStatsProto`), then same as above.
- **TERTIARY (per-medal rank):** `BadgeService.GetPlayerBadgeRank(HoloBadgeType)` → tier
  (0=none…4=platinum). **Arg/return shape [DEVICE]** — run `enum_methods` on
  `Niantic.Holoholo.Badges/BadgeService` first.

### 3d. Confidence + what needs the device (Medals)
- **High:** `EventBadges` @ +0xB8 (DEVICE-recon 2026-05-21, reader re-reads by field name so it
  self-heals), RF<int> layout, `get_PlayerStats` 0-arg, runtime enum-dump method.
- **[DEVICE]:** capture the live 2026 district enum names+ints (the headline unknown); confirm
  district completion writes to `EventBadges` (vs a `BadgeData` inventory item); `GetPlayerBadgeRank`
  shape.

**Reader:** `system/scripts/game_read/read_medals.py`.

---

## 4. INVENTORY (items, MEGA ENERGY, raid passes, candy/XL, currencies)

**The whole inventory is one Dictionary** reachable from
`Niantic.Holoholo.Collections.InventoryCache.GetCurrentItems()` (`holo-game.dll`).

### 4a. Walk recipe (**PROVEN live** — 6272 entries)
1. `inv = pick_singleton('Niantic.Holoholo.Collections','InventoryCache')`.
2. `dict = InventoryCache.GetCurrentItems()`; backing Dictionary @ result `+0x10`.
3. Dictionary walk (**PROVEN**): entries `dict+0x18`; array-len `entries+0x18`; stride `0x18`;
   entry `{int hash@+0x0; int next@+0x4; ref key@+0x8; ref value@+0x10}`; skip `hash<0`.
4. Per entry, discriminator `case = key+0x18` (int):
   - **`case==2` (Item):** `value.get_Item()` → `ItemProto{ Item@+0x10, Count@+0x14 }`.
     **CONFIRMED live** (item 1150 → count 2731). STATIC confirms `ItemProto` Item[1] Count[2].
   - **`case==10` (PokemonFamily):** `value.get_PokemonFamily()` → `PokemonFamilyProto{ FamilyId@+0x10,
     Candy@+0x14, MegaEvolutionResources(RF)@+0x18, XlCandy@+0x20 }`. Candy/XL **CONFIRMED live**
     (fam 624 candy=2338 xl=419). STATIC confirms FamilyId[1] Candy[2] MegaEvolutionResources[4] XlCandy[5].
   - other cases (RaidTickets / EggIncubators / EventPasses / InventoryUpgrades / PlayerStats(4) /
     PlayerCurrency(5)): the reader prints a case histogram + dumps sample value bytes to decode.

### 4b. MEGA ENERGY — the one structural unknown
- Mega energy is **NOT an item id and has NO getter.** It is the repeated
  `TemporaryEvolutionResourceProto` list at `PokemonFamilyProto+0x18`. Metadata names the field
  `MaxEnergyCount` but the proto has **no C# getters**, and the per-element energy offset is
  **[DEVICE]** (no static dump). The reader dumps the element's class + reflected
  `il2cpp_class_get_fields` (name+offset+type) + 0x40 raw bytes + candidate ints at
  +0x10/+0x14/+0x18/+0x1c/+0x20. **One run on a mega-capable family locks it.**
- **GOTCHA:** family id = **BASE** species dex number. Mega Charizard energy is under family **4**
  (Charmander), Mega Gengar under **92** (Gastly), Mega Gyarados under **129** (Magikarp), Mega
  Mewtwo under **150**. Do NOT query 6/94/130.

### 4c. Currencies + raid passes
- **Stardust / PokéCoins** are NOT in this dict → `Niantic.Holoholo.Storefront.IapService`:
  `get_Stardusts()` (**CONFIRMED** prior session) / `get_Coins()` / `get_PurchasedCoins()` (boxed
  int @+0x10). (`PlayerCurrencyProto.Gems@+0x10` in the dict is Gems, not coins/dust.)
- **Raid passes:** Remote/Premium raid passes are ordinary **item ids** (`case==2`); there is also a
  separate `RaidTickets` oneof case for event raid tickets.
- **Item enum numeric ids** for RareCandy / XlRareCandy / Remote+Premium passes are NOT pinned
  statically → decode the `Holoholo.Rpc.Item` enum on device (`meta_dump.py --enum` can't reach it
  if it's top-level; use the runtime enum-dump). 1150 = `OtherEvolutionStoneA` (an evolution stone,
  NOT a Gimmighoul coin — a prior note mislabeled this).

### 4d. Cleaner method path (cross-check, **[DEVICE]**)
`Niantic.Holoholo.Internal.ItemBagImpl`: `GetItemCount(itemId)`, `GetCandyCountForPokemonFamily(famId)`,
`GetXlCandyCountForPokemonFamily(famId)` (names verified in metadata; invocation unproven). If they
work, this is the simplest reader (no oneof plumbing) and exposes mega candy via `totalMegaCandyCounts`.

### 4e. Confidence + what needs the device (Inventory)
- **CONFIRMED live:** the full dict walk, item count path, candy/XL path, `get_Stardusts`.
- **[DEVICE]:** `TemporaryEvolutionResourceProto` energy offset; `ItemBagImpl` method path;
  non-{2,4,5,10} case constants; Item enum numeric ids; possible multi-instance of
  InventoryCache/IapService/ItemBagImpl (see §6).

**Reader:** `system/scripts/game_read/read_inventory.py`.

---

## 5. GO FEST 2026 specifics (worked example tying it together)

From `gofest_data_model.md` — the durable model for "did I finish this event thing?":

| Question | WRONG approach | RIGHT read |
|---|---|---|
| Did the City challenge complete? | scan only active `+0x10` (it vanished) | `completedIds` @ `QuestsProto+0x18`; corroborate with medal |
| Did the District complete? | look for a quest | `PlayerStatsProto.EventBadges` via `PlayerService` (the district `HoloBadgeType`) |
| What is this quest in English? | read templateId | `GetQuestDisplayProto(questId)` + `I18n.Text(titleKey/descKey)` |
| What's the goal number? | guess from `{0}` | `QuestProto.goal.target` @ `goal+0x18` |
| What Pokémon does it reward (Mewtwo step)? | infer from name | `QuestRewardProto.get_PokemonEncounter` (intended; completion-independent) |
| Multi-day TR sub-step progress? | read parent progress | `get_MultiPart()` → SubQuests, per-sub `progress+0x48`/`status+0x58` |

**Rotating quest templateIds are server-pushed and invisible to static analysis**
(`QUEST_GOFEST2026_*`, `TR_GOFEST2026_IRL_CITY_*`, `WIN_MEWTWO` are NOT in `_metadata_strings.txt`)
— only a live `QuestsProto` walk sees them. Location-card enums and medal enums ARE baked into
`holo-protos.dll`. GO Fest 2026 Mewtwo location-card enum = **248/249/250**
(`LcSpecialbackground2026Mewtwo001/002/003`) or **245** (`Lc2026TokyoGofest001` if Tokyo-local);
the two DB Mewtwo (uid 7411975807261094796 / 5744441765404633224, CP 2363/2362 IV 41) carry
`fresh_has_location_card=1` but `fresh_loc_card_enum=NULL` because they were out of heap at the last
poll (`parse_fresh.py` NULLs all `fresh_*` then repopulates only polled mons). Open each Mewtwo's
detail screen, re-poll, and the enum rehydrates — no new offset discovery.
**Reader:** `system/scripts/game_read/read_mewtwo_locationcard.py` (bonus, in the recon folder as
draft; ships here too).

---

## 6. Cross-cutting caveats (read before running anything)

1. **Singleton capture races.** `QuestService`/`I18n`/`PlayerService` only fire/populate when the
   user touches the relevant UI. The hooks wait up to ~60 s. If `get_QuestsProto()` returns null,
   the user hasn't opened Research yet — the readers say so explicitly.
2. **Multi-instance.** `pick_singleton` has tuned probes ONLY for `PokemonBagImpl`/`TaggingRpcService`/
   `PokedexImpl`. For `InventoryCache`, `IapService`, `PlayerService`, `BadgeService`, `ItemBagImpl`,
   `QuestService` it returns the **first** liveness hit. If a class returns >1 instance, the right one
   is the one whose data is non-empty (e.g. InventoryCache whose dict walk yields a plausible count) —
   mirror the `_pick_real_bag` pattern. The readers below note this per-call.
3. **`holo-game.dll` vs `holo-protos.dll`.** `cFN` in the preamble binds `holo-game.dll` only.
   Proto types (`Holoholo.Rpc.*`) are in `holo-protos.dll` → resolve their classes via
   `il2cpp_object_get_class(liveObject)` (the readers do this) or by adding a `holo-protos.dll` image
   lookup. Calling `cFN('Holoholo.Rpc','QuestRewardProto')` will return null.
4. **Boxed-payload offset.** Boxed enum/int/bool/float returned by getters: payload at `ret+0x10`
   (arm64 convention). Confirm once per primitive type on device ([DEVICE]).
5. **oneof null-semantics.** Some C# protobuf versions return the *default* sub-message (non-null)
   for an un-set oneof case. Gate on `get_*Case()` first, then call exactly one accessor — the
   readers fall back to "call each getter, the active arm is non-null/non-zero" which is robust.
6. **Read-only guarantee.** Every reader calls getters / reads memory only. None calls
   `CompleteQuest`/`BeginQuestEncounter`/`UpdateQuestDetails` or writes any field. (Quest/medal/
   inventory state is server-authoritative anyway.) The MultiPart *write* helpers from
   `walk_waina_*` are deliberately excluded.
7. **Offset drift across updates.** All magic offsets live in ONE `OFF`/`OFFSETS` block per reader.
   After any PoGo update: re-run `meta_dump.py <Type>` to re-confirm field ORDER, then re-validate
   the byte offsets on device. The readers self-check shapes (won't treat a slot as a RF unless
   count/array look sane) so drift is visible, not silent.

---

## 7. Subsystem confidence summary

| Subsystem | Can read TODAY (PROVEN) | Adds with [DEVICE] validation |
|---|---|---|
| **Quests — list/state** | active+completed lists, type/id/template/progress/status/timestamps, MultiPart sub-steps | lock Goal single-vs-RF; classify +0x20 list; enum ordinals |
| **Quests — display** | English title/desc/sub-step text via GetQuestDisplayProto + I18n | — |
| **Quests — goals** | Target number + condition list offset | which ConditionCase counts (tag confirm) |
| **Rewards** | (structure mapped; accessor-only) | getter-name + per-arm behavior → full item/encounter/mega decode incl. Mega Mewtwo X/Y |
| **Medals** | EventBadges RF @ +0xB8 + all counters | live HoloBadgeType names for 2026 districts; per-medal rank |
| **Inventory** | full dict walk: every item id→count, candy/XL per family, stardust | mega-energy element offset; Item enum ids; ItemBagImpl path |

---

## 8. Deliverable files

- **This map:** `pogo_extract/system/analysis/GAME_READ_CAPABILITIES.md`
- **Static lookup tool (no device):** `pogo_extract/system/analysis/game_read_recon/meta_dump.py`
- **Readers (READ-ONLY, reuse `pogo_il2cpp.py`):** `pogo_extract/system/scripts/game_read/`
  - `dump_research_full.py` — active quests: title/desc, goals (target+condition+verb), rewards
    (items + encounter + mega energy), sub-quests, status/timestamps, completedIds, +0x20 probe.
  - `read_medals.py` — `EventBadges` + counters + live `HoloBadgeType` enum dump → named event/district medals.
  - `read_inventory.py` — item id→count, per-family candy/XL/mega-energy(candidate), currencies, case histogram.
  - `read_mewtwo_locationcard.py` — recover the GO Fest 2026 Mewtwo location-card enum (fills the DB gap).
- **Recon source files:** `pogo_extract/system/analysis/game_read_recon/` (6 markdown + draft readers).
- **The device-read plan (ordered):** see §9.

---

## 9. PRIORITIZED DEVICE-READ PLAN (hand to the lead — run SERIALLY on-device)

Single-serial collision rule: the device is one resource. Run these **one at a time**, in this
order, on the screen each step names. Each step says exactly which future question it answers.

> **Step 0 (one-time, highest leverage):** pull `libil2cpp.so` from the device and run
> **Il2CppDumper** + `global-metadata.dat` → `dump.cs`. This converts every `[DEVICE]` offset
> below into a known constant. If you do only one thing, do this. Path:
> `/data/app/~~*/com.nianticlabs.pokemongo-*/lib/arm64/libil2cpp.so` (or base.apk `lib/arm64-v8a/`).
> Read-only pull; does not touch game state.

1. **Research / Timed Research — "what are my current research tasks (verbatim)?"**
   - Open the **Today/Research** screen, then run `dump_research_full.py`.
   - Answers: every active quest's **English title + description**, per-step **task verb + target +
     condition**, **rewards (items + Pokémon encounter + mega energy)**, sub-quest live progress,
     status/timestamps, and the `completedIds` list (finished challenges).
   - Validates in passing: Goal single-vs-RF, reward getter name, the `+0x20` second-list class.
   - **Run with `--probe` the first time** to lock the RewardOneofCase int map + boxed-payload offset.

2. **Event medals / districts — "which event medals/districts have I completed?"**
   - Stay on the map or open the **Trainer profile**, then run `read_medals.py`.
   - Answers: the full earned-medal list incl. **GO Fest 2026 district medals** (Friendship/Adventure/
     …), with their live `HoloBadgeType` names+ints (captured from the live binary), plus every
     progress-medal counter.
   - This is the durable "did the district ever complete?" answer (medals persist; the quest list doesn't).

3. **Inventory — "what mega energy / passes / candy do I have?"**
   - Run `read_inventory.py` (no special screen needed; InventoryCache is resident).
   - Answers: full **item id→count** map (balls, berries, **remote/premium raid passes**, rare candy),
     **per-family candy + XL**, and **mega energy** per family (after the one-run element-offset lock),
     plus **stardust/coins** via IapService.
   - First run also prints the key-case histogram + the `TemporaryEvolutionResourceProto` byte dump —
     lock the mega-energy offset here, then it's permanent.

4. **Reward deep-dive incl. Mega Mewtwo — "what does THIS research reward?"**
   - Covered by step 1's reward decode. For a specific Mega encounter (X vs Y), confirm in the
     `dump_research_full.py` output that the quest has a `PokemonEncounter` (pid=150 Mewtwo) AND a
     co-listed `MegaResource` whose `TemporaryEvolutionId` = `TEMP_EVOLUTION_MEGA_X`/`_Y` (lock those
     ordinals from the `--probe` block). The Mega-X/Y answer is the MegaResource arm, not the encounter.

5. **(Optional) GO Fest 2026 Mewtwo location card — fill the DB gap.**
   - Open each Mewtwo's **detail screen** (uid 7411975807261094796 and 5744441765404633224) so they
     enter the heap, then run `read_mewtwo_locationcard.py`. Expect enum **248/249/250** (or **245**).
   - Then re-run a targeted `fresh_poll` + `parse_fresh` so `fresh_loc_card_enum` persists.

**After step 0 (Il2CppDumper):** re-baseline the `OFF`/`OFFSETS` blocks in all readers from
`dump.cs` and drop every `[DEVICE]` flag they cover.
