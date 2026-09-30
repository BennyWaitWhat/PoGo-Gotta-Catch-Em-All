# Quest Rewards + Pokemon-Encounter Reward proto recon (STATIC)

Subsystem: **QuestRewardProto reward list + PokemonEncounterRewardProto** inside
`holo-game.dll` / `holo-protos.dll`, namespace `Holoholo.Rpc` and
`Niantic.Holoholo.Quests`.

Goal: read, per quest, the full reward list and decode a Pokemon-encounter reward
to "this research rewards a Mega Mewtwo X/Y encounter (mega form, shiny-eligible,
with a location background)". Plus item / mega-energy / stardust / candy rewards.

All facts below are **derived from static dumps** (`_metadata_strings.txt` =
IL2CPP global-metadata string pool, `global-metadata.dat`, jadx). The string pool
gives **class + method/field NAMES** but is an unordered, de-duplicated pool, so it
**cannot give byte offsets or field ordering**. Therefore the reader is built on
`il2cpp_runtime_invoke` of the C# protobuf getters (offset-independent, the same
proven technique as the existing quest scripts). Raw offsets are only used where
the existing code already validated them (QuestProto). **Everything that needs a
live device to confirm is flagged `[DEVICE]`.**

---

## 1. Proto class hierarchy (confirmed in metadata)

`_metadata_strings.txt` line refs in parentheses.

```
QuestProto (holo-protos.dll, Holoholo.Rpc)            # 304284
  ├─ Goals          : RepeatedField<QuestGoalProto>   # "Goals" @132725, QuestGoalProto @304282
  ├─ QuestRewards   : RepeatedField<QuestRewardProto>  # "QuestRewards" @99267
  ├─ (also reachable via QuestRpcService.GetQuestRewardProtos)
  └─ MultiPart.SubQuests : RepeatedField<QuestProto>   # proven in walk_waina_subquests.py

QuestRewardProto (Holoholo.Rpc)                        # 304309, fields @139104-139140
  oneof Reward {                                        # discriminator: get_RewardCase()  (139139)
     Exp                 (int32)                        # get_Exp        139105
     Item                (ItemRewardProto)              # get_Item       (verified present)
     Stardust            (int32)                        # get_Stardust   (verified present)
     Candy               (PokemonCandyRewardProto)      # get_Candy      (verified present)
     PokemonEncounter    (PokemonEncounterRewardProto)  # get_PokemonEncounter  139113  <-- TARGET
     Pokemon             (PokemonProto)                 # get_Pokemon    (verified present)
     PokemonEgg          (PokemonEggRewardProto)        # get_PokemonEgg (verified present)
     LevelCap            (int32)                        # get_LevelCap   139115
     MegaResource        (TempEvoResourceRewardProto)   # get_MegaResource 139119  <-- MEGA ENERGY
     TempEvoResource     (TempEvoResourceRewardProto)   # get_TempEvoResource 139137
     Sticker             (StickerRewardProto)           # get_Sticker
     AvatarTemplateId    (string)                       # get_AvatarTemplateId
     PlayerAttribute     (PlayerAttributeRewardProto)   # get_PlayerAttribute 139123
     Incident            (IncidentRewardProto)          # get_Incident   139121
     EventBadgeId        (string)                       # get_EventBadgeId 139125
     PokemonIndividualStat (PokemonIndividualStatRewardProto) # 139129
     LootTable           (LootTableRewardProto)         # get_LootTable  139131
     FriendshipPoints    (int32)                        # get_FriendshipPoints 139133
     PokemonCandy        (PokemonCandyRewardProto)      # get_PokemonCandy
  }
  QuestTemplateId (string)                              # get_QuestTemplateId 139109

PokemonEncounterRewardProto (Holoholo.Rpc)             # 304317, fields @139167-139186
  PokemonId            (HoloPokemonId enum)             # species (POGOProtos: field 1)
  PokemonDisplay       (PokemonDisplayProto)            # form / costume / gender / shiny / temp-evo  (PokemonDisplayProto @302893)
  UseQuestPokemonEncounterDistribuition (bool)          # get_UseQuestPokemonEncounterDistribuition 139168
  PokemonEncounterDistribution (PokemonEncounterDistributionRewardProto) # 139172
  DittoDisplay         (PokemonDisplayProto)            # 139175
  PokeBallOverride                                       # 139176
  ShinyProbability     (float/double)                   # 139177
  SizeOverride                                           # 139178
  StatsLimitsOverride  (PokemonStatsLimitsProto)        # 139179 / 139207
  IsFeaturedPokemon    (bool)                            # 139180
  ForceFullModelDisplay(bool)                            # 139181
  IsHiddenDitto        (bool)                            # 139174

PokemonDisplayProto (Holoholo.Rpc)                     # 302893
  Form / Costume / Gender / Shiny / Alignment           # getters all confirmed present
  (NOTE: temp-evo on display is the Mega form indicator on the *display*; the
   authoritative mega type is in the mega-energy reward, see below)

TempEvoResourceRewardProto (Holoholo.Rpc)             # 304311  (= what get_MegaResource AND get_TempEvoResource return)
  wraps -> TemporaryEvolutionResourceProto              # 304141 / @138448
     PokemonId           (HoloPokemonId)
     TemporaryEvolutionId (HoloTemporaryEvolutionId enum: TEMP_EVOLUTION_MEGA / _MEGA_X / _MEGA_Y / _PRIMAL)  # 323743-323747
     Amount / MaxEnergyCount                            # MaxEnergyCount @138449

HoloTemporaryEvolutionId enum (mega form id)           # 323743-323747
   TEMP_EVOLUTION_UNSET   = 0
   TEMP_EVOLUTION_MEGA    = 1     [DEVICE: confirm ordinal]
   TEMP_EVOLUTION_MEGA_X  = 2     [DEVICE]
   TEMP_EVOLUTION_MEGA_Y  = 3     [DEVICE]
   TEMP_EVOLUTION_PRIMAL  = 4     [DEVICE]
   (Mewtwo: MEGA_X vs MEGA_Y is exactly this enum.)
```

### Why NOT raw offsets for the reward proto
The `_metadata_strings.txt` pool is order-shuffled and name-deduplicated: the
`get_*` clusters next to `QuestProto`/`PokemonEncounterRewardProto` literals in the
file are **frequently the accessors of an unrelated UI class that happened to reuse
the same string** (verified: the `get_Mega`/`get_Shiny` cluster near a display-like
name is actually `ContestFocusProto`, not `PokemonDisplayProto`). And the
serialized protobuf `FileDescriptorProto` (which would give true field numbers) is
**not present** in `global-metadata.dat` (Holoholo strips proto reflection;
`raw.find(0x0A+len+"QuestRewardProto")` returns nothing, and there are only 15
`.proto` literals total). So field-number / offset derivation from these static
artifacts is not possible — the getter-invoke path is the correct one, and any raw
offset MUST be device-validated.

---

## 2. Two routes to a quest's reward list

### Route A (preferred, offset-free): QuestRpcService.GetQuestRewardProtos
- Class `QuestRpcService` (metadata @17617) exposes `GetQuestRewardProtos`
  (@17619). Signature unknown statically — **[DEVICE] enumerate param count**;
  likely `(QuestProto)` or `(string templateId)` and returns
  `RepeatedField<QuestRewardProto>` or `IList<QuestRewardProto>`.
- Also on `QuestService` there may be a passthrough. The draft probes both
  `QuestService` and `QuestRpcService` for the method and its arity.

### Route B (offset-free via the proto): QuestProto.get_QuestRewards()
- Each `QuestProto` (the per-quest object already obtained by the existing
  scripts at `QuestsProto` RepeatedField +0x10 → items @+0x20, element ptr; proven
  offsets templateId@+0x40, status@+0x58) has a protobuf getter
  `get_QuestRewards()` returning `RepeatedField<QuestRewardProto>`.
- Iterate that RepeatedField with the standard layout (count @+0x18, backing array
  @+0x10, elements at array+0x20 + i*8) — **same layout the existing code already
  uses for QuestsProto**, so reuse is safe. `[DEVICE]` confirm the getter name is
  `get_QuestRewards` vs `get_Rewards` (probe both).

Both routes converge on a `QuestRewardProto*` per reward; decode each with §3.

---

## 3. Decoding a single QuestRewardProto (the core helper)

Offset-free algorithm (all via runtime_invoke on `Holoholo.Rpc.QuestRewardProto`):

1. `case = get_RewardCase()` → returns the `RewardOneofCase` enum boxed int.
   Read the boxed int at `ret + 0x10` (standard IL2CPP boxed-enum payload, same
   convention the existing tag/dex probes use). `[DEVICE]` confirm the int->case
   mapping by cross-referencing which getter returns non-null.
2. Switch on the populated getter (robust even without knowing the enum ints —
   just call each `get_X` and the active oneof field is the non-null/non-zero one):
   - `get_PokemonEncounter()` non-null  → **POKEMON ENCOUNTER** (decode §4)
   - `get_MegaResource()` non-null OR `get_TempEvoResource()` non-null → **MEGA / TEMP-EVO ENERGY** (decode §5)
   - `get_Item()` non-null → item: read `ItemRewardProto.Item` (enum) + `.Amount`
   - `get_Stardust()` (int32) > 0 → stardust amount
   - `get_Candy()` / `get_PokemonCandy()` non-null → candy (PokemonId + Amount)
   - `get_Exp()` (int32) > 0 → XP
   - `get_Pokemon()` non-null → direct PokemonProto grant
   - `get_PokemonEgg()` non-null → egg
   - `get_LevelCap()` (int32) > 0 → level-cap unlock
   - else → fall back to the numeric RewardCase for logging.

For int32 oneof fields (Exp, Stardust, LevelCap, FriendshipPoints) the getter
returns a **boxed int**; read payload at `ret+0x10`. For message fields the getter
returns the sub-proto object pointer directly.

---

## 4. Decoding PokemonEncounterRewardProto -> "Mega Mewtwo X encounter"

Given `enc = QuestRewardProto.get_PokemonEncounter()` (a
`Holoholo.Rpc.PokemonEncounterRewardProto*`):

- `pid_enum = enc.get_PokemonId()`  (boxed enum int @+0x10) → HoloPokemonId
  (1=Bulbasaur … 150=Mewtwo). Map via existing species table.
- `disp = enc.get_PokemonDisplay()` (PokemonDisplayProto*) — if non-null:
    - `form    = disp.get_Form()`     (boxed enum) — form id (use the verified
      Form-enum table in `pogo-il2cpp-internals` memory).
    - `costume = disp.get_Costume()`  (boxed enum int)
    - `gender  = disp.get_Gender()`   (1=male,2=female,3=genderless)
    - `shiny   = disp.get_Shiny()`    (boxed bool)
    - `align   = disp.get_Alignment()`(shadow/purified)
- `shinyProb = enc.get_ShinyProbability()` (boxed float @+0x10) — guaranteed-shiny
  research shows 1.0.
- `featured  = enc.get_IsFeaturedPokemon()` (boxed bool)

**Mega form for the encounter**: the encounter's *species*+*display* tells you it's
Mewtwo; the **X vs Y distinction** for a "Mega Mewtwo X/Y encounter reward" comes
from the paired mega-energy reward in the SAME QuestRewardProto list (§5) OR from a
temp-evo marker on the display. For GO-Fest-style "choose Mega Mewtwo X or Y"
research the two choices are two separate quests / branches — read each branch's
encounter+megaresource pair. `[DEVICE]` verify whether the encounter reward alone
carries a temp-evo id (some events set `PokemonDisplay` temp-evo; if so read it),
otherwise rely on the co-listed MegaResource (§5) whose `TemporaryEvolutionId` is
the authoritative MEGA_X / MEGA_Y.

**Location background** ("with a location background"): this is the quest's
*display* asset, not on the encounter proto. Pull it from
`QuestService.GetQuestDisplayProto(quest)` (@17610) — a `QuestDisplayProto` whose
fields include the background/image asset name. `[DEVICE]` enumerate
QuestDisplayProto getters (e.g. `get_BackgroundImage` / `get_ImageUrl` /
`get_Title` / `get_Description`). The existing `GetQuestDescription` already returns
the human title/description string; `GetQuestDisplayProto` is the richer object.

Display-side helper: `RewardPreviewModalGuiController.PokemonToDisplayForEncounterReward`
(@99268) converts a `PokemonEncounterRewardProto` into the exact `PokemonProto` the
game renders (resolves distribution/featured/ditto). If `get_PokemonId` is 0
because the reward uses `PokemonEncounterDistribution`, calling this helper (or
reading `PokemonEncounterDistribution`) yields the concrete species. `[DEVICE]`.

---

## 5. Decoding MegaResource / TempEvoResource (mega energy)

`mr = QuestRewardProto.get_MegaResource()` (or `get_TempEvoResource()`), a
`TempEvoResourceRewardProto*` which wraps a `TemporaryEvolutionResourceProto`:

- get the inner `TemporaryEvolutionResourceProto` (likely
  `mr.get_TempEvoResource()` / `mr.get_Resource()` — `[DEVICE]` confirm getter
  name; the wrapper has one message field).
- `pid   = inner.get_PokemonId()`            → species the energy is for
- `tevo  = inner.get_TemporaryEvolutionId()` (boxed enum) → **TEMP_EVOLUTION_MEGA_X
  / _MEGA_Y / _MEGA / _PRIMAL** — this is the authoritative Mega-X-vs-Y answer.
- `amt   = inner.get_Amount()` or `get_MaxEnergyCount()` → energy quantity

So a quest that "rewards a Mega Mewtwo X encounter + 100 Mega Energy" appears as TWO
QuestRewardProto entries: one `PokemonEncounter` (Mewtwo) and one `MegaResource`
(pid=Mewtwo, TemporaryEvolutionId=TEMP_EVOLUTION_MEGA_X, amount=100).

---

## 6. RewardCase / oneof enum (RewardOneofCase)  [DEVICE for exact ints]
Names confirmed (`RewardCase` @139154, `RewardOneofCase` @139155). The integer
value of each case == the protobuf field number of that oneof member. Field numbers
are NOT in the static dump (descriptor stripped). The reader does NOT depend on
them — it switches on which getter returns non-null. Capture the int->name map
on-device once for nicer logging (dump `get_RewardCase()` alongside the matched
getter).

---

## 7. Offsets summary

| What | Offset / method | Source | Confidence |
|---|---|---|---|
| QuestsProto active list | RepeatedField @+0x10 (cnt@+0x18, arr@+0x10, items@arr+0x20+i*8) | existing scripts | HIGH (proven) |
| QuestProto.templateId | UTF16 String* @+0x40 | existing scripts | HIGH (proven) |
| QuestProto.status | s32 @+0x58 (2=COMPLETE,3=claimed) | existing scripts | HIGH (proven) |
| QuestProto.progress | s32 @+0x48 | existing scripts | HIGH (proven) |
| QuestProto.goal | ptr @+0x50 (target@+0x18) | existing scripts | HIGH (proven) |
| QuestProto.MultiPart.SubQuests | get_MultiPart() → RF @+0x10 | walk_waina_subquests.py | HIGH (proven) |
| RepeatedField generic layout | count@+0x18, array@+0x10, elem@array+0x20+i*8 | existing scripts | HIGH (proven) |
| Boxed value payload (enum/int/bool/float) | @+0x10 | IL2CPP convention + existing probes | MEDIUM — `[DEVICE]` confirm per type |
| UTF16 String | len@+0x10, chars@+0x14 (2 bytes each) | existing scripts | HIGH (proven) |
| QuestProto.get_QuestRewards | invoke (name `get_QuestRewards` vs `get_Rewards`) | metadata "QuestRewards" @99267 | MEDIUM — `[DEVICE]` probe both |
| QuestRewardProto.get_RewardCase / get_* | invoke | metadata 139104-139140 | HIGH (names) / MEDIUM (behavior `[DEVICE]`) |
| PokemonEncounterRewardProto.get_PokemonId / PokemonDisplay / ShinyProbability | invoke | metadata 139167+ | MEDIUM — `[DEVICE]` |
| TemporaryEvolutionId enum ints | TEMP_EVOLUTION_* | metadata 323743-323747 | MEDIUM — `[DEVICE]` confirm ordinals |
| QuestRpcService.GetQuestRewardProtos | invoke (arity unknown) | metadata 17617/17619 | LOW — `[DEVICE]` enumerate signature |
| QuestService.GetQuestDisplayProto | invoke (1-arg) → QuestDisplayProto | metadata 17610 | MEDIUM — `[DEVICE]` map fields |

---

## 8. Device-validation checklist (hand to the lead, single Frida session)
1. Capture a `QuestService` instance (existing hook) AND a `QuestRpcService`
   instance (same hook, different class) — confirm which exposes
   `GetQuestRewardProtos` and its param count.
2. On one known quest object: call `get_QuestRewards` (and `get_Rewards`) — see
   which returns a non-empty RepeatedField; record the working getter name.
3. For each QuestRewardProto in that list: dump `get_RewardCase()` int and which
   `get_*` returns non-null → build the int->case map; confirm boxed-payload @+0x10
   for an int field (e.g. Stardust) and a bool field (Shiny).
4. On a PokemonEncounter reward: confirm `get_PokemonId` (expect a sane 1..1025),
   `get_PokemonDisplay`→`get_Form/Shiny`, `get_ShinyProbability`.
5. On a MegaResource reward (if any active): confirm the inner-getter name and that
   `get_TemporaryEvolutionId` yields TEMP_EVOLUTION_MEGA_X/_Y; lock the enum ints.
6. `GetQuestDisplayProto(quest)` → enumerate its getters to find the
   title/description/background-image fields (the "location background").

Draft reader that performs steps 1-6 read-only: see
`draft_read_quest_rewards.py` in this folder.
