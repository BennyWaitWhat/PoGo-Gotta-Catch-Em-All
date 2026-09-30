---
name: reference-pogo-buddy-system
description: "PoGo buddy system, read live 2026-09-26: where hearts/levels live (BuddyHistoryData, BuddyObservedData, today's per-category shown hearts MapField), the game's own buddy calls, caps, evolution-quest progress (QuestProto on the mon), gym battles count only with the buddy in the party, and the relay through the Gym Battle runner"
metadata:
  node_type: memory
  type: reference
  originSessionId: 3e41439f-386c-4cde-8bbd-9813692f89c2
  modified: 2026-09-26T08:48:35.806Z
---

Built for the user's job (2026-09-26 04:05): finish the current buddy's task (Snom → Frosmoth needs 10 buddy hearts), then rotate the hundo Eevee evolutions every 3 hearts until each reaches Best Buddy.

**Levels and caps** (game master, confirmed live):
- Good buddy at 1 heart, Great at 70, Ultra at 150, Best at 300 (total hearts). Best = 300 exactly; every ribbon holder has ≥300.
- Daily caps per buddy: treat 3, play 1, snapshot 1, walk 3 (2 km each), battle 3, new place 1, route 1, bonus 6 (double hearts while Excited).
- 20 swaps per day, counted in `BuddyPokemonProto.DailyBuddySwaps` (the Window is a UTC day number).
- Treats give 1 heart each. A berry adds 2 fullness points, and a buddy is full at 6. A Golden Razz or Poffin fills it completely; "full" lasts 1 h after berries, 6 h after a Poffin (`timeFullDurationMs`).
- Evolution quests: Snom → Frosmoth costs 400 candy, must happen at night, and needs 10 hearts (SNOM_FROSMOTH_EVOLUTION_QUEST). Sylveon's event quest needs 20.

**Where the data lives** (exact-name lookups, pure reads):
- `ClientPlayerProto.BuddyPokemonProto` (current buddy: `BuddyPokemonId`, LastSetTimestampMs, DailyBuddySwaps) and `.BuddyObservedData`.
  - ObservedData: CurrentPointsEarned = that buddy's total hearts; CurrentEmotionPoints (Excited at 32); TotalStats (KmWalked, BerriesFed, Communication, Battles, Photos, NewVisits); BuddyFeedStats (FullnessExpirationMs, MapExpirationMs).
  - `TodayStatsShownHearts`: `BuddyAffectionKmInProgress` (walk km toward the next heart) plus `BuddyShownHeartsPerCategory`, a MapField keyed by category (1 treat, 2 play, 3 snapshot, 4 walk, 5 battle, 6 new place, 7 bonus, 8 route). Each value is a list of heart types, one per cap slot: 1 = single heart, 2 = double, 0 = not yet.
  - Two ClientPlayerProto copies can be in memory; take the newest LastSetTimestampMs.
- `BuddyHistoryData` (~250 in memory): PokemonId, PokedexId, CurrentPointsEarned (hearts per Pokémon), Last(Un)SetTimestampMs. This is the per-Pokémon friendship record.
- The DB's `fresh_pokemon_badge == 1` is the Best Buddy ribbon. The DB column `is_best_buddy` is NOT the ribbon; don't use it.
- `PlayerStatsProto.NumBerriesFed`: the Berry Master medal counter.
- Candy: `PokemonFamilyProto` (Snom family 872 had 638).

**The game's own buddy calls** (instance methods, called from the game thread):
- `Niantic.Holoholo.Buddy.BuddyRpcService`: RequestBuddyStats() → BuddyStatsOutProto; Feed(Item, int) → BuddyFeedingOutProto(Result, ObservedData, ShownHearts); Pet() → BuddyPettingOutProto; RequestBuddyHistory().
- `BuddyPokemonService`: SetBuddyPokemon(UInt64) → IRpcPromise<SetBuddyPokemonOutProto>; get_BuddyPokemon(); get_BuddySwapsLeft(); CanSwapBuddyToPokemon(PokemonProto).

**Evolution quests (the game's own progress):**
- `QuestProto` instances with QuestContext 8 (EVOLUTION_QUEST) are each attached to one Pokémon via `PokemonProto.evolutionQuestInfo_` (a `PokemonEvolutionQuestProto`: QuestRequirement, QuestInfo, Evolution, Form).
- Fields to read: TemplateId (e.g. SNOM_FROSMOTH_EVOLUTION_QUEST), Progress, Goal.Target, Status, CreationTimestampMs, LastUpdateTimestampMs. Stale copies coexist in memory; take the newest LastUpdate.
- Probe: `scratchpad/quest_probe.py` (instances(QuestProto) + readObj; read-only).
- A buddy-heart quest is created the moment the Pokémon is set as buddy.
- Progress persists on the Pokémon after a swap. Evidence: Snom 12214631859506727003 still showed 8/10 from 2025-08-08.
- The Frosmoth branch has no `mustBeBuddy` (only Espeon and Umbreon do), so a completed Snom can be swapped out and evolved on a later night.
- A completed evolution quest keeps Status 1 with Progress = Target. The 10000/10000 Espeon and Umbreon quests look the same, and there's no CompletionTimestampMs.
  - Snom reached 10/10 at 04:47:27. It was re-read after the 04:47:53 swap and was still 10/10 (2026-09-26).
- Daily caps are PER BUDDY. At the swap, Espeon's today-map started at all zeros (treat 0/3, play 0/1, battle 0/3...), and play gave a heart at once.

**What counts, measured:**
- Gym battles DO give battle hearts, but ONLY when the buddy is in the battle party. Correction: at 04:01 I wrongly said gym battles give none; the Gym Battle picker simply never took the buddy.
  - Since v2.85 the party is the top 5 by CP plus the buddy last.
  - Snom went from 0/3 to 3/3 battle hearts within 30 s of that change (04:35).
- Walking counts. While the runner circles gyms it credits only ~5 km/h (about 22 min per walk heart).
- A spin of a never-visited PokéStop counts. Pokemod's vPGP spins stops within ~12 m; the Gym Battle runner has a {"spin"} task. `PokemonFortProto.Visited` in the map directory finds never-visited stops (8 of 435 near 5th Ave on 2026-09-26).
- Other affection kinds in the client: BUDDY_AFFECTION_VISIT_POWERED_UP_FORT and ATTRACTIVE_POI (the latter needs Ultra level).

**Tools:**
- `AutoCatcher/tools/buddy_tapper.py` (standalone Frida module) and `buddy_run.py` (--first ID:TARGET, --rotate, --every 3, --feed never golden; --via DIR relays through the Gym Battle runner's command inbox → `buddy_out.jsonl`; since 2026-09-29 both live in `AutoCatcher/tools/gym_state/` -- one file per command in `runner_inbox/`, `runner_cmd.json` is legacy).
- The Gym Battle session merged the module into gym_tapper, so there is ONE script in the game. Never run a second LateUpdate hook next to it.
- Read-only probes: `scratchpad/buddy_probe.py`, `stops_scan.py`.
Related: [[reference-pogo-native-gym-flow]], [[feedback-read-in-game-records]], [[feedback-game-pace-decide-in-runner]].
