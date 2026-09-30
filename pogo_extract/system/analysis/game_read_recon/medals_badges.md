# MEDALS / BADGES — IL2CPP read recon (STATIC analysis, 2026-05-29)

Goal: read the player's **earned medals/badges** from PoGo's live IL2CPP state,
especially **GO Fest City District medals** (the "Friendship District" popup the
lead saw this session). District completions are tracked as MEDALS, not quests.

**TL;DR — the medal list is one RepeatedField:**
`PlayerStatsProto.EventBadges : RepeatedField<HoloBadgeType>` @ **+0x184**.
Each element is a 4-byte `HoloBadgeType` enum int. Resolve int→name by dumping the
`HoloBadgeType` enum **from the live binary** (2026 district medals are absent from
every static dump). Draft reader: `pogo_extract/read_medals.py` (runnable as-is).

---

## 1. Architecture (where badges live)

PoGo has THREE distinct "badge" concepts. We care about #1 (the medals UI).

| # | Concept | Storage | Reader path |
|---|---------|---------|-------------|
| 1 | **Player medals/badges** (Jogger, Kanto, GO Fest district, …) | `PlayerStatsProto` | `IPlayerService.get_PlayerStats` |
| 2 | **Gym badges** (per-gym bronze/silver/gold) | `GymBadgeService` | `GymBadgeService.GetGymBadgeData` (secondary) |
| 3 | **Badge VISUALS** (sprites/frames/rings) | `BadgeService` (`Niantic.Holoholo.Badges`) | not needed for "what's earned" |

Two flavors of player medal inside `PlayerStatsProto`:

- **Progress medals** (Jogger, Collector, Battle Girl…) are NOT a list. Each is a
  scalar counter field (`KmWalked`, `NumPokemonCaptured`, `NumBattleAttackWon`…).
  The bronze/silver/gold/platinum tier is computed client-side by comparing the
  counter to thresholds in GAME_MASTER (`BadgeSettingsProto`). To know the *rank*
  precisely you'd call `BadgeService.GetPlayerBadgeRank(HoloBadgeType)` (see §5).
- **Event / dynamic medals** (GO Fest districts, Safari Zone, GO Tour, City
  Explorer Pass, Mini-Collection…) are discrete on/off badges stored as a list of
  enum values: **`PlayerStatsProto.EventBadges`**. **This is where the GO Fest
  district / "Friendship District" medal lives.**

> Bonus: `HoloInventoryItemProto.get_PlayerStats -> PlayerStatsProto` — i.e. the
> whole stats blob is also an inventory item (oneof case), reachable by walking
> `InventoryCache` exactly like Pokemon/items. The `PlayerService` getter is the
> shortcut; the inventory walk is the fallback (§5).

---

## 2. DEVICE-VALIDATED offsets (`PlayerStatsProto`, Holoholo.Rpc)

From the **2026-05-21 runtime recon** (`_recon_services.py` →
`_recon_services_out.json`, observed klass `0x7623d691c0`). These are real
`il2cpp_field_get_offset` values, not guesses:

| Field | Offset | Type | Use |
|-------|--------|------|-----|
| `Parser` | +0x00 | MessageParser | (proto boilerplate) |
| `Level` | +0x10 | Int32 | trainer level |
| `Experience` | +0x18 | Int64 | XP |
| `KmWalked` | +0x30 | **Single (float)** | Jogger medal |
| `NumPokemonEncountered` | +0x34 | Int32 | |
| `NumUniquePokedexEntries` | +0x38 | Int32 | Kanto…Paldea dex medals |
| `NumPokemonCaptured` | +0x3C | Int32 | Collector |
| `NumEvolutions` | +0x40 | Int32 | Scientist |
| `PokeStopVisits` | +0x44 | Int32 | Backpacker |
| `NumberOfPokeballThrown` | +0x48 | Int32 | |
| `NumEggsHatched` | +0x4C | Int32 | Breeder |
| `BigMagikarpCaught` | +0x50 | Int32 | Fisher |
| `NumBattleAttackWon` | +0x54 | Int32 | Battle Girl |
| `NumPokemonDeployed` | +0x70 | Int32 | |
| `NumPokemonCaughtByType` | +0x78 | **RepeatedField\<Int32\>** | per-type counts (Pikachu Fan etc.) |
| `SmallRattataCaught` | +0x80 | Int32 | Youngster |
| `NumBerriesFed` | +0xA8 | Int32 | Berry Master |
| `TotalDefendedMs` | +0xB0 | Int64 | Gym Leader (hours) |
| **`EventBadges`** | **+0xB8 (184)** | **RepeatedField\<HoloBadgeType\>** | **← the medal list (district medals)** |
| `NumForeverFriendsEarned` | +0x1A8 (424) | Int32 | Forever Friends |
| `KmWalkedPastActiveDay` | +0xC0 | Single | |
| `NumChallengeQuestsCompleted` | +0xC4 | Int32 | |
| `NumTrades` | +0xC8 | Int32 | Successor |
| `NumPokemonPurified` | +0xF4 | Int32 | Purifier |
| `NumGruntsDefeated` | +0xF8 | Int32 | Hero |
| `NumBestBuddies` | +0xFC | Int32 | Best Buddy |
| `NumTotalMegaEvolutions` | +0x128 | Int32 | Mega Guru |
| `NumBreadBattlesWon` | +0x17C | Int32 | Dynamax (Bread=Dynamax) |

All offsets above are verbatim from `_recon_services_out.json`. The reader also
re-reads by **field name** at runtime (`readFieldsAt`), so a future binary update
that shifts layout self-corrects; +0x184 (0xB8) is the fallback constant for the
RepeatedField walk if the named lookup ever fails.

### RepeatedField\<int|enum\> memory layout (PROVEN)
Documented + used in `pogo_pipeline.py` (the battle-tested per-Pokemon parser),
line ~153, for `CapturedForms : RepeatedField<Form>` (identical enum-list type):

```
RF.add(0x10).readPointer()   // backing managed array
RF.add(0x18).readS32()       // element count
array.add(0x20 + i*4).readS32()   // element i (4-byte int / enum)
```

So reading `EventBadges` = read RF ptr at `stats+0x184`, then walk that array.

---

## 3. The `HoloBadgeType` enum (the medal identities)

C# name: **`HoloBadgeType`**, namespace **`Holoholo.Rpc`** (also the proto enum
`.HoloBadgeType`; protobuf field name on `PlayerBadgeProto` is `badge_type`).

**Structure (from static metadata, current binary 2026-05-21):**
`BadgeUnset=0`, then progress badges (`BadgeTravelKm`, `BadgePokedexEntries`,
`BadgeCaptureTotal`, …, type-caught badges `BadgeTypeNormal…BadgeTypeFairy`,
league `BadgeGreatLeague/UltraLeague/MasterLeague`, Gen2..Gen9 dex,
Bread/Dynamax `BadgeBreadBattlesEntered/Won/...`), then the boundary markers:

```
BadgeDynamicMin   ← dynamic (mini-collection / contest / stamp-rally) start
BadgeMiniCollection, BadgeButterflyCollector, BadgeStampRally, ...
BadgeEventMin     ← EVENT badges start here
BadgeChicagoFestJuly2017, BadgePikachuOutbreakYokohama2017, ...
BadgeCityExplorerPass00..40,
BadgeGofest2019..., BadgeGofest2023Osaka..., BadgeGotourLive2024...,
BadgeSafari2025<City>Saturday/Sunday/..., BadgeGowa2025Irl<Day>TicketedCity, ...
```

### CRITICAL GAP — 2026 district medals are NOT in any static dump
- `ipogo_extracted/libnotmain_strings.txt` (May 8) `HoloBadgeType` block (lines
  7926–8219) stops at GOFEST **2021**.
- `_metadata_strings.txt` (May 21) C# enum (lines 134168–~135269) goes up to
  **GOWA 2025** (`BadgeGowa2025Irl…`) — still **no 2026 / Tokyo / District /
  Friendship** entries. Grep for `district|friendship|gofest2026` = 0 hits.

The "Friendship District" medal is a **newer enum value present only in the live
`holo-game.dll`**. Therefore the reader **must enumerate the enum at runtime** to
get its int→name. Expected names (pattern-matched, to confirm on device):
`BadgeGofest2026Tokyo…FriendshipDistrict` / `…<X>District` style, in the
event-badge range. GO Fest 2026 city districts are publicly: Friendship,
Adventure, Discovery, Nostalgia, Mischief (district theme names) — the enum
constants will encode these.

### Runtime enum dump (PROVEN pattern, `dump_form_enum.py`)
Map enum int→name by reading static-literal fields:
- filter fields by flags: `& 0x10` (STATIC) **and** `& 0x40` (LITERAL/const)
- read constant via `il2cpp_field_static_get_value(field, buf)` → `buf.readS32()`
- build `{value: name}`

`read_medals.py` does this for `Holoholo.Rpc / HoloBadgeType` and uses the result
to name every int in `EventBadges`, including 2026 districts.

---

## 4. Proto / class reference (for going deeper than the enum list)

Relevant types (metadata + jadx confirmed):

- `Holoholo.Rpc | PlayerStatsProto` — holds `EventBadges` + all `Num*` counters.
- `Holoholo.Rpc | PlayerBadgeProto` — fields: `badge_type` (HoloBadgeType),
  `start_value`, `end_value`, `current_value`. Used in
  `PlayerPublicProfileProto.badges` (repeated). NOTE: in the *local* PlayerStats
  the earned event badges are the bare `EventBadges` enum list; `PlayerBadgeProto`
  (with progress values) is the richer per-badge struct seen on public profiles /
  `PlayerBadgeTierProto`.
- `Holoholo.Rpc | BadgeData` (+ `MiniCollectionBadgeData`, `ButterflyCollectorBadgeData`,
  `StampRallyBadgeData`, `ContestBadgeData`) — per-dynamic-badge detail, also a
  `HoloInventoryItemProto` oneof case (`get_BadgeData`). Walk inventory to read.
- `Niantic.Holoholo.Badges | BadgeService` / `IBadgeService` — visuals + the
  classifiers/rank API (see §5).
- `Niantic.Holoholo.GymBadges | GymBadgeService` — `GetGymBadgeData`,
  `gymBadgeProto`, `BadgeRankColor` (gym badges, concept #2).
- enum boundary predicates on BadgeService: `IsBasicBadge`, `IsElementalBadge`,
  `IsEventBadge`, `IsDynamicBadge`, `IsDynamicEventBadge`, `IsIncidentBadge`,
  `IsNumberBadge` — useful to *classify* a HoloBadgeType value (district medals
  answer true to `IsDynamicEventBadge`/`IsEventBadge`).

GAME_MASTER tier thresholds: `Holoholo.Rpc | BadgeSettingsProto` /
`EventBadgeSettingsProto` (loaded by BadgeService `defaultBadgeSettingsAddresses`
/ `eventBadgeSettingsAddresses`). These map a HoloBadgeType to its
bronze/silver/gold/platinum target values — needed only if you want to render the
progress-medal *rank* rather than the raw counter.

---

## 5. Read recipes

### PRIMARY (what `read_medals.py` does) — earned event/district medals
1. `find_all('Niantic.Holoholo','PlayerService')` (liveness) → instance.
2. `call_getter(... 'get_PlayerStats')` → `PlayerStatsProto*`.
3. `read_fields_at(ptr,'Holoholo.Rpc','PlayerStatsProto')` → discover `EventBadges`
   offset by name (fallback +0x184) + read all `Num*`/`KmWalked` counters.
4. `read_repeated_int(ptr, eb_off)` → list of HoloBadgeType ints.
5. `dump_enum('Holoholo.Rpc','HoloBadgeType')` → int→name; join.
6. Filter names by `gofest|district|friendship|city|safari|gotour|gowa` → the
   GO Fest district medals (incl. Friendship District).

PlayerService must be live → **be on the map or open the Trainer profile** before
running (same precondition the QuestService readers use).

### SECONDARY (no PlayerService dependency) — inventory walk
If PlayerService isn't captured, walk `InventoryCache` for the
`HoloInventoryItemProto` whose oneof is PlayerStats:
- `HoloInventoryItemProto.get_PlayerStats -> PlayerStatsProto` (confirmed in
  `_recon_gm2_out.json`). Then continue from step 3 above.
- The existing inventory walkers (`reconcile_inventory_v3.py`,
  `extract_friends_v3.py` dict-walk at +0x18/+0x20) show the cache traversal.

### TERTIARY (per-medal rank, incl. progress medals) — BadgeService
`BadgeService.GetPlayerBadgeRank(HoloBadgeType)` returns the earned tier
(0=none,1=bronze,2=silver,3=gold,4=platinum). To use it: liveness-find
`Niantic.Holoholo.Badges/BadgeService`, then `call_int_arg(...,'GetPlayerBadgeRank',
inst, badgeTypeInt)`. **Arg/return shape NOT yet device-validated** (BadgeService
absent from prior recon) — discover with `enum_methods('Niantic.Holoholo.Badges',
'BadgeService')` first. This lets you enumerate *every* HoloBadgeType value and ask
its rank, giving a complete "medals + ranks" picture in one pass without parsing
GAME_MASTER thresholds. Good follow-up once the primary reader is confirmed.

---

## 6. Confidence + what needs the device

**High confidence (cross-checked):**
- Enum name `HoloBadgeType` (Holoholo.Rpc); event/district medals are values in it.
- `PlayerStatsProto.EventBadges` is the earned event/dynamic-badge list, type
  `RepeatedField<HoloBadgeType>` @ +0x184 (device recon 2026-05-21).
- RepeatedField\<int\> layout (array@+0x10, count@+0x18, elems@array+0x20, i*4).
- `IPlayerService.get_PlayerStats -> PlayerStatsProto` 0-arg (proven by
  `account_snapshot.py`).
- Enum int→name dump method (proven by `dump_form_enum.py`).
- 2026 district medal names are NOT in static dumps → must read live enum.

**Needs device validation (flagged in the script):**
1. Confirm `EventBadges` @ +0x184 still current in TODAY's binary (script re-reads
   by name, so it self-heals; just sanity-check the printed offset).
2. Confirm the live `HoloBadgeType` enum actually contains 2026 Tokyo district /
   "Friendship District" constants, and capture their exact names + int values
   (this is the headline unknown; only the live binary has them).
3. Confirm GO Fest district completion writes to `EventBadges` (vs. a separate
   `BadgeData`/inventory item). If a district medal you KNOW is earned (Friendship)
   doesn't show in `EventBadges`, fall back to: walk inventory `BadgeData` items,
   and/or call `GetPlayerBadgeRank` over the dynamic-event enum range.
4. `BadgeService.GetPlayerBadgeRank` arg/return shape (tertiary path) — run
   `enum_methods` first.
5. Map progress-medal counters → tiers either via `GetPlayerBadgeRank` or
   `BadgeSettingsProto` GAME_MASTER (not parsed here).

## 7. Files
- Draft reader: `pogo_extract/read_medals.py` (reuses `pogo_il2cpp.py` +
  `account_snapshot.js`; adds `dumpEnum` + `readRepeatedInt`). Syntax-checked.
- Evidence: `_recon_services_out.json` (PlayerStatsProto offsets),
  `_recon_gm2_out.json` (HoloInventoryItemProto.get_PlayerStats),
  `_metadata_strings.txt` (HoloBadgeType C# enum @134168, PlayerStatsProto @138338,
  BadgeService @38997), `ipogo_extracted/libnotmain_strings.txt` (HoloBadgeType
  proto enum @7926, PlayerBadgeProto fields @7828),
  `pogo_pipeline.py` (RepeatedField\<enum\> layout), `dump_form_enum.py`
  (enum-dump pattern), `account_snapshot.py`/`.js` (PlayerService harness).
