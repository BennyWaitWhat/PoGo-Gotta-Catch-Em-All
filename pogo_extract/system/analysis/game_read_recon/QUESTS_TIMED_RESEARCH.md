# QUESTS / TIMED RESEARCH — live-read recon (static analysis)

Goal: read everything human-meaningful about active quests / Timed Research / Field
Research straight out of PoGo's live IL2CPP memory — human title + description, the
step / sub-quest structure with each task's condition type and x/target, the rewards
(items + Pokemon encounter), and completion / claim status.

**Static analysis only — nothing in here was run against the device.** Every offset that
is not already proven by working code in the repo is flagged **VALIDATE**. Two runnable
draft scripts ship with this report (paths at the bottom).

Source-of-truth files cross-referenced: `extract_quests_v3.py` (the most complete working
reader — already pulls human titles + sub-task display + completed ids), `extract_quests_v2.py`,
`walk_waina_subquests.py` (proves the `QuestProto.get_MultiPart()` sub-quest path),
`dump_quests.py` / `read_quest_details.py` / `explore_quests.py` (this session's readers),
`pogo_il2cpp.py` (helper surface), and `_metadata_strings.txt` (the IL2CPP metadata blob).

---

## 0. TL;DR — the right way to read research

1. **Get the two singletons by hooking** (proven): attach `Interceptor` to every method of
   `Niantic.Holoholo.Quests.QuestService` and `Niantic.Holoholo.Internationalization.I18n`,
   grab `args[0]` (`this`) on first fire. The user must be on the map / Today / Research
   screen so a method fires. (I18n *may* also be reachable as a static `Instance` — it has
   `set_Instance` in metadata — VALIDATE; the hook is the safe path.)
2. `QuestService.get_QuestsProto()` → a `Holoholo.Rpc.QuestsProto`.
   - `+0x10` = `RepeatedField<QuestProto>` **Quests** — the ACTIVE quests (full `QuestProto`).
   - `+0x18` = `RepeatedField<String>` — completed template-ids history (582 entries on this
     account; proven in v2/v3).
   - `+0x20` = the **second ~78-entry list** — element is NOT a `QuestProto` (its templateId
     is not at +0x40). See §5.
3. For each active `QuestProto`: read scalars by offset (§2), decode **Goals** (target +
   condition type, §3), decode **QuestRewards** (items + Pokemon encounter, §4), and if it
   is a story / multi-part quest pull **sub-quests** via `QuestProto.get_MultiPart()` (§6).
4. Resolve display text with `QuestService.GetQuestDisplayProto(questId : string)` →
   `QuestDisplayProto`, then translate its `titleKey` / `descKey` via `I18n.Text(key)`
   (§7). `{0}`/`{1}` placeholders stay literal with `Text`; use `TextFormat(key, args)` to
   fill them, or substitute the goal target client-side.

What was already solved (in `extract_quests_v3.py`) vs. **what this recon adds**:

| Capability | v3 status | This recon |
|---|---|---|
| Active list, templateId/questId/type/progress/status/timestamps | ✅ working | reused verbatim |
| Human title + description (I18n) | ✅ working | reused |
| Sub-task **display** titles (from `QuestDisplayProto.SubquestDisplays`) | ✅ working | reused |
| Completed-id history | ✅ working | reused |
| **Per-task live x/target + which condition counts** | ❌ missing | §3 (Goals decode) |
| **Rewards: items (id+count)** | ❌ missing | §4 |
| **Rewards: Pokemon encounter (species)** | ❌ missing (`GetPokemonEncounterForQuest` returned null) | §4 + §8 |
| **Sub-quest live progress (MultiPart)** | partial (waina-only script) | §6 (generalized) |
| **Second +0x20 list decoded** | ❌ undecoded | §5 (self-classifying probe) |

---

## 1. Class map (verified present in `_metadata_strings.txt`)

Services (in `holo-game.dll`):
- `Niantic.Holoholo.Quests.QuestService` — local cache + display. Methods (param counts):
  `get_QuestsProto/0`, `get_Quests/0`, `get_ProgressedQuests/0`, `GetStoryQuestProtos`,
  `GetWelcomeBackRewardQuests`, `GetQuestDataOfType`, `GetPokemonEncounterForQuest/1`,
  `GetIncidentForQuest`, `GetQuestDescription/1`, `GetLevelUpQuestDisplay`,
  **`GetQuestDisplayProto/1`** (resolves here on this build per v2/v3).
- `Niantic.Holoholo.Quests.QuestRpcService` — **metadata-canonical owner** of
  `GetQuestDisplayProto`, **`GetQuestRewardProtos`**, `GetQuestDetails`, `CompleteQuest`,
  `BeginQuestEncounter`, `GetQuestFromQuestDialogueInbox`. (So if `GetQuestDisplayProto`
  ever stops resolving on `QuestService` after an update, fall back to `QuestRpcService`.)
- `Niantic.Holoholo.Internationalization.I18n` — `Text`, `TextFormat`, `HasText`,
  `set_Instance`/`set_Language`.

Protos (in `holo-protos.dll`, namespace `Holoholo.Rpc`):
- `QuestsProto`, `QuestProto`, `ClientQuestProto`, `MultiPartQuestProto`,
  `QuestGoalProto`, `QuestConditionProto`, `QuestRewardProto`, `QuestDisplayProto`,
  `QuestEncounterProto`, `QuestPokemonEncounterProto`, plus per-type payloads
  (`CatchPokemonQuestProto`, `SpinPokestopQuestProto`, `EvolveIntoPokemonQuestProto`,
  `BattleQuestProto`, `TakeSnapshotQuestProto`, `TravelRouteQuestProto`,
  `SubmitSleepRecordsQuestProto`, `DailyBuddyAffectionQuestProto`, `GetStardustQuestProto`,
  `SpendStardustQuestProto`, `BuddyEvolutionWalkQuestProto`, `PokemonReachCpQuestProto`,
  `AddFriendQuestProto`, `TradePokemonQuestProto`, `DaysWithARowQuestProto`,
  `DailyQuestProto`), and reward payloads (`ItemRewardProto`,
  `PokemonEncounterRewardProto`, `PokemonCandyRewardProto`, `LootTableRewardProto`,
  `PokemonEggRewardProto`, `PokemonIndividualStatRewardProto`).

> ⚠️ The metadata string blob is obfuscated/deduplicated, so adjacency of names does **not**
> give field order. Field **offsets must come from runtime reflection** — that is exactly
> what `dump_quest_layouts.py` does (run it first).

---

## 2. `QuestProto` scalar offsets (CONFIRMED by working code)

From `extract_quests_v3.py` (these produced correct live values — titles, progress, status,
dates — on this build):

| Offset | Field | Type | Notes |
|---:|---|---|---|
| 0x10 | `questType` | s32 enum `QuestType` | see enum in §9 |
| 0x28 | `questId` | String | server quest **instance** id (use for display lookups) |
| 0x40 | `templateId` | String | template id, e.g. `STORY_QUEST_WAINA23_1` |
| 0x48 | `progress` | s32 | live progress count |
| 0x50 | `Goals` | RepeatedField **or** single `QuestGoalProto` | **VALIDATE** — see §3 |
| 0x58 | `status` | s32 enum | 1 ACTIVE, 2 COMPLETE/TARGETS_MET (see §9) |
| 0x68 | `createdMs` | s64 | |
| 0x70 | `lastUpdateMs` | s64 | |
| 0x78 | `completionMs` | s64 | |
| 0x80 | `fortId` | String | field-research fort (from v2) |
| 0xb0 | `endMs` | s64 | |
| 0x60 | `QuestRewards` | RepeatedField<QuestRewardProto> | **VALIDATE** — best static guess; confirm name+offset in `quest_layouts.md` |

`questId` vs `templateId`: `walk_waina_subquests.py` reads `questId@+0x28` AND
`templateId@+0x40` on sub-quests — both present. This is the key to §5: the +0x20 list's
element is likely keyed at +0x28, not +0x40.

---

## 3. Goals — the live x/target + which action counts  (the priority gap)

`QuestProto.Goals` is declared **repeated** in metadata, but v3 read `quest+0x50` as a single
`QuestGoalProto` and used `+0x18` as the target — and for the leaf catch tasks v3's
`goalTarget` came out **empty** (the v3 dump shows `progress 6 / ?`), which means the
single-goal-at-0x50 assumption is wrong for at least some quests. Two possibilities, both
handled by the reader:

- **(A)** `+0x50` is a single `QuestGoalProto`: `target@+0x18`, conditions
  `RepeatedField<QuestConditionProto>@+0x10`. (This is what the existing notes assume.)
- **(B)** `+0x50` is `RepeatedField<QuestGoalProto>`: walk it; each goal has `target` +
  conditions.

`dump_research_full.py::readGoals()` **auto-detects** which by checking whether `+0x50`
looks like a RepeatedField (sane `count@+0x18` and a backing array with `capacity >= count`).
**VALIDATE** against `quest_layouts.md` (`QuestGoalProto` field offsets + whether `Goals` is
repeated) and lock the correct branch.

`QuestGoalProto` (CONFIRMED offsets from existing code):
- `Conditions` = `RepeatedField<QuestConditionProto>` @ `+0x10`
- `Target` (s32) @ `+0x18`

**Condition type** = which `With*` field is set on `QuestConditionProto` (a protobuf oneof).
Read it resiliently via `QuestConditionProto.get_ConditionCase()` (returns the proto field
tag). The full oneof list (verified in metadata, the `ConditionCase`):

```
WithPokemonType, WithPokemonCategory, WithWeatherBoost, WithDailyCaptureBonus,
WithDailySpinBonus, WithWinRaidStatus, WithRaidLevel, WithThrowType,
WithWinGymBattleStatus, WithSuperEffectiveChargeMove, WithItem, WithUniquePokestop,
WithQuestContext, WithBadgeType, WithPlayerLevel, WithWinBattleStatus, WithUniquePokemon,
WithNpcCombat, WithPvpCombat, WithLocation, WithDistance, WithInvasionCharacter,
WithPokemonAlignment, WithBuddy, WithDailyBuddyAffection, WithPokemonLevel, WithMaxCp,
WithTempEvoId, WithGblRank, WithEncounterType, WithCombatType, WithItemType,
WithElapsedTime, WithFriendLevel, WithPokemonCp, WithRaidLocation, WithFriendsRaid,
WithPokemonCostume, WithPokemonSize, WithDeviceType, WithRouteTravel, WithUniqueRoute,
WithTappableType, WithAuthProviderType, WithOpponentPokemonBattleStatus, WithFortId,
WithPokemonMove, WithPokemonForm, WithBreadPokemon, WithBreadDoughPokemon,
WithBreadMoveType, WithPoiSponsorId, WithPageType, WithTraineePokemonAttributes,
WithBattleOpponentPokemon, WithPokemonTypeMove, WithPokemonFamily, WithQuestId
```

But the **action that counts** (catch vs spin vs walk vs battle …) is actually the quest's
`QuestCase` oneof, not the condition — the condition narrows it (e.g. catch *Grass-type*).
`QuestProto.get_QuestCase()` returns which concrete payload is set:

```
DailyQuest, MultiPart, AddFriend, TradePokemon, DailyBuddyAffection, QuestWalk,
EvolveIntoPokemon, GetStardust, GeotargetedQuest, BuddyEvolutionWalk, Battle,
TakeSnapshot, SubmitSleepRecords, TravelRoute, SpinPokestop, PokemonReachCp,
SpendStardust, SpendTempEvoResource
```

So a complete task description = `QuestCase` (the verb) + `Goal.Target` (the number) +
active `ConditionCase`(s) (the qualifier). The reader emits all three; the `COND_NAMES` /
`REWARD_NAMES` maps in the script are best-effort tag→name and always print the raw int too,
so nothing is lost if a tag number is off. **VALIDATE** a couple of tag numbers against a
known quest (e.g. the live "Catch 7 Grass-type" → expect `QuestCase=CatchPokemon`,
`ConditionCase=WithPokemonType`, `target=7`).

---

## 4. Rewards — items + Pokemon encounter

`QuestProto.QuestRewards` = `RepeatedField<QuestRewardProto>`. Each `QuestRewardProto` is a
**oneof reward** — read the active arm via `get_RewardCase()` then the matching getter. The
oneof (verified in metadata):

```
Exp(int), QuestTemplateId(string), PokemonEncounter, LevelCap, MegaResource, Incident,
PlayerAttribute, EventBadgeId, PokemonIndividualStat, LootTable, FriendshipPoints,
TempEvoResource,  +  Item, PokemonCandy, Sticker, AvatarClothing, PokemonEgg
```

Reward payloads of interest:
- **`ItemRewardProto`** → `get_Item()` (Item enum id) + `get_Count()` (s32). E.g. id=1 ball,
  id=101 potion, etc. (Item enum is the standard PoGo item enum — already in this repo's
  currency/item decoding work.)
- **`PokemonEncounterRewardProto`** → the species. Fields seen in metadata:
  `PokemonEncounterDistribution`, `IsHiddenDitto`, `DittoDisplay`, `PokeBallOverride`,
  `ShinyProbability`, `SizeOverride`, `StatsLimitsOverride`, `IsFeaturedPokemon`. The plain
  species id comes via `get_PokemonId()` if present, else via the `PokemonDisplay` /
  distribution sub-message — **VALIDATE which getter exists** (`dump_quest_layouts.py` lists
  the methods). This is the reliable, completion-independent way to know "this research
  rewards a Galarian Mr. Mime", regardless of `GetPokemonEncounterForQuest` (see §8).
- `Exp`, `Stardust`, `PokemonCandy`, `MegaResource`, `LootTable` — scalar/sub-message arms.

The reader prefers `QuestRpcService.GetQuestRewardProtos(...)` when that service+method
resolves (returns the canonical reward list), and **falls back** to reading
`QuestProto.QuestRewards@+0x60` directly. The direct-offset path is the dependable one for a
read-only tool because it needs no RPC instance.

---

## 5. The second ~78-entry list at `QuestsProto+0x20`

Facts: `+0x10` is the active `RepeatedField<QuestProto>`; `+0x18` is the completed-id
`RepeatedField<String>`; `+0x20` holds ~78 entries whose element is **not** a `QuestProto`
(templateId not at +0x40). Candidates, by `QuestsProto`/`IQuestService` surface:

- `ProgressedQuests` (`IQuestService.get_ProgressedQuests`) — likely `ClientQuestProto` or a
  progress record. **Most probable.**
- A second completed/state list (`CompletedQuestStates`).
- `ClientQuestProto` wrappers (a `ClientQuestProto` *wraps* a `QuestProto` + display).

Reasoning from `walk_waina_subquests.py`: sub-quest records expose `questId@+0x28` and
`templateId@+0x40`. If the +0x20 element's id is at **+0x28** (and +0x40 is empty), it is a
`ClientQuestProto`-shaped record (id-first), not a raw `QuestProto`. If its id is at **+0x10/
+0x18**, it is a lighter status/progress struct.

`dump_research_full.py::read_second_list` **probes the first element's string at +0x10/+0x18/
+0x28/+0x40 and dumps a sample of ids**, so one read tells you the element type and the right
templateId offset. Once classified, add a typed decode. The authoritative answer is in
`quest_layouts.md` under `QuestsProto` (field name + element type at +0x20) — **VALIDATE
there first**, the probe is the cross-check.

---

## 6. Sub-quest structure (story / multi-part) — generalized from waina

`walk_waina_subquests.py` proves the path (CONFIRMED):
- `QuestProto.get_MultiPart()` (class `Holoholo.Rpc.QuestProto`, 0 args) → `MultiPartQuestProto`.
- `MultiPartQuestProto.SubQuests` = `RepeatedField<QuestProto>` @ **`+0x10`**.
- Each sub-quest is a full `QuestProto` (same offsets as §2): `templateId@+0x40`,
  `questId@+0x28`, `questType@+0x10`, `progress@+0x48`, `status@+0x58`, goal@+0x50.

So a story quest like `STORY_QUEST_WAINA23_1` ("Catching Some Z's (2/2)") expands into N
sub-quests, each with its own live progress / target / status — which is exactly what the UI
shows as the step list. The generalized reader calls `get_MultiPart()` for **every** active
quest; non-multipart quests return null and are skipped. For each sub-quest it also decodes
goals (§3) and rewards (§4), so you get the per-step task + reward.

Note: many active "quests" are actually **headers/containers** (questType 3
`NonNarrativeStoryQuest`, templateId ends `_HEADER`, progress 0, no goal) whose real tasks
live in `SubQuests`. The leaf daily/weekly tasks (questType 4, "Catch {0} …") carry the real
progress directly. The reader handles both: headers surface their sub-quests; leaves surface
their own goal.

---

## 7. Display text + i18n (CONFIRMED working in v3)

`QuestService.GetQuestDisplayProto(questId : System.String)` → `QuestDisplayProto`. Build the
managed string with `il2cpp_string_new(utf8)`. `QuestDisplayProto` offsets (from v2/v3):

| Offset | Field | Notes |
|---:|---|---|
| 0x20 | `descKey` | i18n key |
| 0x28 | `titleKey` | i18n key |
| 0x30 | `slot` (s32) | |
| 0x38 | `SubquestDisplays` | RepeatedField; each: `titleKey@+0x28`, `descKey@+0x20` |
| 0x40 | `StoryEndingQuest` (u8) | |
| 0x48 | `StoryEndingDescription` (String) | |
| 0x58 | `TagString` | i18n key (e.g. event name) |
| 0x70 | `iconName` (String) | |
| 0xd8 | `sortOrder` (s32) | |

Field order from metadata (`QuestDisplayProto`): `Dialog, SubquestDisplays, StoryEndingQuest,
StoryEndingDescription, TagString, SponsorString, BackgroundName, ForegroundName,
ProgressInterval, Branches, …` — consistent with the offsets above. **VALIDATE the exact
byte offsets in `quest_layouts.md`** (they're build-stable but cheap to confirm).

Translate keys via `I18n.Text(key : String)` → localized `System.String`. The localized
string keeps `{0}`/`{1}` placeholders (the v3 dump shows literal "Catch {0} Grass-type
Pokémon"). To render the number, either (a) `I18n.TextFormat(key, values[])`, or (b)
substitute `Goal.Target` for `{0}` client-side (simplest for a read tool). The reader keeps
the raw template AND prints the goal target so the human number is always available.

---

## 8. Why `GetPokemonEncounterForQuest(questProto)` returned null — and the fix

Observed this session: passing the raw `QuestProto*` to
`QuestService.GetPokemonEncounterForQuest` returned null. Likely causes (in priority order):

1. **No encounter to give yet.** The encounter is part of the *reward*, materialized only
   when the quest is COMPLETE/claimable (status 2). For an in-progress quest there is no live
   encounter object — null is correct. → Read the *intended* species from
   `QuestRewardProto.PokemonEncounter` (§4) instead; it's in the quest definition regardless
   of completion.
2. **Wrong argument type.** The method may want the `ClientQuestProto` wrapper (from
   `get_Quests()` — note `get_Quests` vs `get_QuestsProto`), not the raw `QuestProto` from
   `get_QuestsProto()`. `get_Quests()` likely returns `ClientQuestProto[]` (a
   `ClientQuestProto` wraps a `QuestProto` + display). → **VALIDATE**: call
   `GetPokemonEncounterForQuest` with the element from `get_Quests()` and compare.
3. Method overload/owner: `GetDanglingEncounterOfType` / `GetQuestDataOfType` exist too;
   `GetPokemonEncounterForQuest` is the right one but confirm its single param type in
   `quest_layouts.md` (`dump_quest_layouts.py` prints method signatures).

**Recommendation:** rely on `QuestRewardProto.PokemonEncounter` for the *reward species*
(deterministic, no completion needed). Use `GetPokemonEncounterForQuest` only to fetch the
*live spawned* encounter for a completed quest, and feed it a `get_Quests()` element.

---

## 9. Enums to confirm (`dump_quest_layouts.py` can pull these from holo-protos)

- **`QuestProto+Types.Status`** (the `status@+0x58` enum). Working code uses
  `{0:UNSET,1:ACTIVE,2:COMPLETE,3:EXPIRED,4:TARGETS_MET,5:CLAIMED}` but 3–5 are guesses.
  Real values: dump the `Status` enum nested under `Holoholo.Rpc.QuestProto`. (Existing
  `_dump_quest_enums3.py` already targets a `Status`/`QuestType` enum in holo-protos — reuse
  its static-field reflection.)
- **`QuestType`** (the `questType@+0x10` enum). Names verified in metadata include
  `DailyCoinQuest, NonNarrativeStoryQuest, LevelUpQuest, TgcTrackingQuest, EvolutionQuest,
  BranchingQuest, MpWalkQuest, ServerChallengeQuest, TutorialQuest,
  PersonalizedTimedChallengeQuest, TimedBranchingQuest, EventPassBonusQuest,
  PokemonTrainingQuest, FieldBookQuest, FieldBookCollectionQuest, FieldBookDailyQuest,
  WelcomeBackRewardsQuest`. Live values seen: 3 = header/story container, 4 = catch task,
  75 = MP walk. **Ordinals need the enum dump** to map all of them.
- **`RewardOneofCase`** and **`ConditionOneofCase`** — the script's name maps are by
  declaration order; the live case returns the proto field tag. Confirm a couple.

---

## 10. Robustness / gotchas

- **Singleton capture races.** `QuestService`/`I18n` only fire when the user touches the
  Today/Research UI. The hook waits up to 60s. If `get_QuestsProto()` returns null, the
  proto isn't populated yet (user hasn't opened Research) — the reader says so explicitly.
- **Multi-instance.** Unlike `PokemonBagImpl`/`PokedexImpl`, `QuestService` came through as a
  single hooked `this` in all prior runs. If liveness ever shows 2 instances, prefer the one
  whose `get_QuestsProto().Quests` count is non-zero.
- **Offset drift across updates.** All the magic offsets live in ONE place
  (`OFF_*` block in `dump_research_full.py`, passed into JS as a dict). After any PoGo update,
  re-run `dump_quest_layouts.py` and reconcile. The reader also self-checks (e.g. it won't
  treat `+0x50` as a list unless the shape is sane) so a drift is visible, not silent.
- **Read-only guarantee.** The reader only calls getters / reads memory. It never calls
  `CompleteQuest`, `BeginQuestEncounter`, or writes any field. (Quest state is
  server-authoritative anyway — see `read_quest_details.py` header + MEMORY
  `pogo-server-authority`.) The MultiPart write helpers from `walk_waina_*` are deliberately
  NOT included here.
- **Frida stability.** Use the project's known-good attach path (`pogo_il2cpp.get_session()`
  handles PID drift + the Tailscale target). `dump_quest_layouts.py` already uses it;
  `dump_research_full.py` uses the same inline adb-pidof + add_remote_device pattern as the
  other quest scripts for consistency — switch it to `pg.get_session()` if you prefer.

---

## Deliverable scripts (run order)

1. `pogo_extract/dump_quest_layouts.py` — **run first, once.** Reflects authoritative field
   offsets for all quest protos + method signatures. Writes `quest_layouts.json` /
   `quest_layouts.md`. Reconcile the `# VALIDATE` offsets in the reader against it.
2. `pogo_extract/dump_research_full.py` — the full reader. Prints + writes
   `research_full_dump.json`: per active quest → title/desc, goals (target+condition+verb),
   rewards (items + encounter), sub-quests (live per-step progress), status/timestamps, and
   the +0x20 second-list classification probe.

## VALIDATE checklist for the lead (device)

1. `QuestProto.Goals@+0x50`: single goal or RepeatedField? Confirm `QuestGoalProto` offsets
   (`Target@+0x18`, `Conditions@+0x10`). Lock the branch in `readGoals()`.
2. `QuestProto.QuestRewards` offset + that it's a RepeatedField (guessed `+0x60`).
3. `QuestRewardProto` `RewardCase` offset and which `get_*` arms exist; `ItemRewardProto`
   `get_Item`/`get_Count`; `PokemonEncounterRewardProto` species getter.
4. `QuestConditionProto` `ConditionCase` (and a sample tag number, e.g. `WithPokemonType`).
5. `QuestsProto+0x20` element type (ProgressedQuests vs ClientQuestProto vs states) + its id
   offset — confirm against the probe output and `quest_layouts.md`.
6. `Status` and `QuestType` enum ordinals (dump from holo-protos).
7. `GetPokemonEncounterForQuest`: does feeding a `get_Quests()` element (ClientQuestProto)
   return non-null where the raw `QuestProto` returned null?
8. Whether `GetQuestDisplayProto` still resolves on `QuestService` (else use `QuestRpcService`).
