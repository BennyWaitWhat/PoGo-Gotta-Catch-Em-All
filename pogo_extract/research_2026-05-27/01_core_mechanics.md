# Pokémon GO — Durable Core Mechanics

**Snapshot date:** 2026-05-27 (live web research)
**Corrected 2026-09-21:** CPM anchors (client game master), the guaranteed-Lucky rule and the Mighty IV floor; the rest is the 2026-05-27 snapshot.
**Author:** Research agent (read-only)
**Game season:** GO Battle League: Memories in Motion (Season 26), March 3 – June 2, 2026

> Convention used below: IVs are written as `Atk/Def/HP` (attack/defense/stamina). `CPM` = CP Multiplier. Quotes are paraphrased unless explicitly indicated.

---

## 1. Level / CP / CPM

### Trainer level
- **Maximum trainer level: 80** (was 50). The Level 50→80 expansion went live **October 15, 2025**, with a full XP rebalance from level 1 to 80. ([pokemongo.com – PGO Leveling Update](https://pokemongo.com/en/post/pgo-leveling-update-details-2025))
- **XP milestones (post-Oct-2025 rebalance):**
  - L10: 48,000
  - L30: 1,083,000
  - L50: 12,753,000
  - L70: 85,853,000
  - L80: 203,353,000 (cumulative)
- All trainers L23+ at the time of the rebalance were "auto-leveled" upward; nobody lost levels.
- **Levels 71–80** require both XP and completing **Level-Up Research tasks** (the old L41–50 research tasks were removed).
- **L15+ feature**: a free **Daily Adventure Egg** (1 km to hatch, awards 10 000 XP).
- **L25+**: avatar cosmetics unlock.
- **L70+**: increased chance of becoming Lucky Friends.

### Pokémon level
- **Max Pokémon level: 50** (unchanged by the L80 update). Powering 40→50 requires **XL Candy**.
- 40→50 total cost: **~250 000 Stardust + 296 XL Candy** ([pokemongohub.net – XL Candy guide via search](https://pokemongohub.net/post/guide/xl-candy-guide-how-to-get-power-up-costs-and-mechanics/))
- **Best Buddy boost** (see §6) effectively gives the active buddy CPM equivalent to **its level + 1** while it remains the active buddy. So a level-50 Pokémon set as Best Buddy uses the **level-51 CPM (0.8453)** in CP calculations.
- "Level 55" CPM is **internal only** — it is used for team-leader Pokémon in Master League training, not attainable by players.

### CP formula
The canonical formula:

```
CP = floor( (Attack × sqrt(Defense) × sqrt(HP) × CPM²) / 10 )
```

where
- `Attack`  = base attack + atk IV (0–15)
- `Defense` = base defense + def IV (0–15)
- `HP`      = base stamina + stamina IV (0–15)
- `CPM`     = the level-based multiplier (see below)

CP floor = **10** (a non-floored result < 10 is clamped to 10).
([bulbapedia – Stat (GO)](https://bulbapedia.bulbagarden.net/wiki/Stat_(GO)))

### CPM table (key anchors — verified)
A full CPM table (one value per whole level, L1-L80) is in the game-master; authoritative anchor values:

| Level | CPM |
|-------|------|
| 1     | 0.094 |
| 10    | 0.4225 |
| 30    | 0.7317 |
| 40    | **0.7903** |
| 50    | **0.8403** |
| 51 (Best Buddy from L50) | **0.8453** |
| 55 (internal/team-leader-only) | **0.8653** (flat from L55 to L80) |

Source (re-read 2026-09-21): the client game master, `PLAYER_LEVEL_SETTINGS` → `playerLevel.cpMultiplier`, 80 whole-level entries — **0.094 (L1) → 0.7903 (L40) → 0.8403 (L50) → 0.8453 (L51)**, flat 0.8653 from L55. Use it as the source of truth for the project's DB.

---

## 2. IV System

IVs are integers `0..15` for each of Attack / Defense / Stamina. Each encounter source applies a per-stat **minimum IV floor**; the value is then random-uniform from floor..15.

| Source | IV floor (Atk/Def/HP) | Notes |
|--------|----------------------|-------|
| Wild — standard | **0/0/0** | |
| Wild — **weather-boosted** | **4/4/4** | Also +5 levels, 1.25× Stardust |
| **Mighty Pokémon** (Wild Area mechanic) | **13/13/13** (verified 2026-09) | Wild Area events; spawn L35-40 (boosted L40-45) ([pokemongohub on X](https://x.com/PokemonGOHubNet/status/1858067654784774496)) |
| Raid (any tier, including Legendary/Mega/Dynamax) | **10/10/10** | Catch level **20** (25 weather-boosted) |
| Shadow Raid | **6/6/6** | (7/7/7 if "IV-boost" event modifier — rare) |
| Egg hatch (all 2/5/7/10/12 km) | **10/10/10** | Always **level 20** |
| Field/Special/Timed Research | **10/10/10** | Not weather-boostable |
| Party Play reward | **10/10/10** | |
| Postcard pinning reward | **10/10/10** | |
| Referral reward | **10/10/10** | |
| GBL standard win reward | **10/10/10** | |
| GO Battle Day/Week/Weekend | **0/0/0** | Yes — *lower* floor than standard GBL |
| Team GO Rocket grunt/leader catch (Shadow) | **0/0/0** | Level **8** (13 weather-boosted) |
| TGR grunt/leader catch — weather-boosted | **4/4/4** | |
| Giovanni Shadow legendary | **6/6/6** | |
| Trade — Friend (no rank) | **0/0/0** | |
| Trade — Good Friend | **1/1/1** | |
| Trade — Great Friend | **2/2/2** | |
| Trade — Ultra Friend | **3/3/3** | |
| Trade — Best Friend | **5/5/5** | |
| Trade — **Lucky Friend** | **12/12/12** (guaranteed Lucky) | |
| **Lucky trade** (any friend rank, becomes Lucky) | **12/12/12** | |
| **Purified** (post-shadow purification) | shadow IV + **2** to each stat (capped 15) | So a 13+/13+/13+ shadow becomes a 15/15/15 hundo on purification |

Sources: ([dittobase – hundo odds](https://www.dittobase.com/pokemon-go/hundo-odds)), ([dexerto – IV floors by encounter](https://www.dexerto.com/pokemon/pokemon-go-iv-floors-by-encounter-1012278/)).

**Mighty floor:** **13/13/13** (verified 2026-09), as the initial 2024 reports and Dittobase said; the later community "consensus" of 12/12/12 is wrong.

---

## 3. PvP Leagues — Caps & Current GBL Schedule

### Standing leagues (CP caps)
- **Great League** — Pokémon must be **≤ 1500 CP**.
- **Ultra League** — ≤ **2500 CP**.
- **Master League** — no CP cap.
- **Master Premier** — no CP cap, **Legendary/Mythical/Ultra Beasts banned**.
- **Little Cup / Little League** — ≤ 500 CP, only basic-stage Pokémon.

### Memories in Motion (Season 26) cup rotations referenced
Across the season Niantic rotated: **Kanto Cup**, **Spring Cup**, **Jungle Cup**, **Electric Cup**, **Fantasy Cup**, **Catch Cup: Memories in Motion (Great League Edition)**, plus standard Great/Ultra/Master.

| Cup | CP cap | Type / Eligibility rules |
|-----|--------|---------------------------|
| Kanto Cup | 1500 | Pokédex #001–#151 only |
| Spring Cup | 1500 | Water, Grass, Fairy only; **Jumpluff, Roserade, Toxapex banned** |
| Jungle Cup | 1500 | Normal, Grass, Electric, Poison, Ground, Flying, Bug, Dark |
| Electric Cup | 1500 | Electric type only |
| Fantasy Cup | 1500 | Dragon, Steel, Fairy only |
| Catch Cup: Memories in Motion (GLE) | 1500 | Only Pokémon **caught between Mar 3 2026 and Jun 2 2026** |

Sources: ([pokemongohub – GBL Memories in Motion](https://pokemongohub.net/post/pvp/go-battle-league-memories-in-motion/)) (via search), ([Dexerto – S26 schedule](https://www.dexerto.com/pokemon/pokemon-go-battle-league-schedule-rewards-1706626/))

### What is active on 2026-05-27 (the snapshot date)
According to Dexerto's S26 schedule retrieval: **May 26 (1 PM PT) → June 2 (1 PM PT) 2026** runs **Great League + Ultra League + Master League** simultaneously (the season-finale "split-3" rotation, with **4× Stardust** from win rewards but **not** end-of-set rewards). This is the *final* rotation of Memories in Motion.

### Upcoming
Season 26 ends **2026-06-02 at 10:00 local time**; the next season begins immediately. As of this snapshot, the next season's cup rotation has not been publicly detailed beyond Niantic's general announcement.

### GO Battle Thursday
All-season: every Thursday is a **"Daily Discoveries: Go Battle Thursday"** event → **10 sets / 50 battles** (vs. 5/25), **4× Stardust** from win rewards.

### Stat Product (rank math)
- "Rank N" in PvP IV tools = position of the IV combo when all 4096 (16³) combinations are sorted by stat product **at the highest legal level for the league**.
- `Stat Product = Effective_Attack × Effective_Defense × Effective_HP`, each = `(base + IV) × CPM_at_max_legal_level`.
- In **capped leagues** (Great/Ultra), **Rank 1 = typically 0/15/15** — lower attack lets the Pokémon reach a *higher* CPM before hitting the cap, and the CPM gain on Def/HP outweighs the lost attack IV.
- In **uncapped Master League**, Rank 1 = **15/15/15** (no level-trade-off).
- ([Switchblade Gaming – PvP IV guide](https://www.switchbladegaming.com/pokemon-go/pvp-iv-guide/))

---

## 4. Move Mechanics

### Fast moves (PvP turn system)
- Each PvP turn = **0.5 seconds**.
- Fast moves have duration **1–5 turns**; damage and energy register on the **final** turn of the move.
- Energy generated per move (EPT × duration) and damage are static per move.
- Charged moves **interrupt** the opponent's fast move and grant the opponent "free turns" — optimal play throws charged moves on the opponent's last fast-move turn.
- ([PvPoke – fast move registration](https://pvpoke.com/articles/strategy/guide-to-fast-move-registration/))

### Charged moves & shields
- Each player has **2 shields** per battle. A shield blocks **all but 1 HP** of an incoming charged move.
- Stat-changing effects (e.g., Power-Up Punch buffing self, Close Combat debuffing self, Icy Wind debuffing opponent) **still apply even when the move is shielded**.
- ([pokemongohub – PvP mechanics](https://pokemongohub.net/post/pvp/comprehensive-pvp-mechanics-guide-in-pokemon-go/))

### Damage formula (PvP)
```
Damage = floor( 0.5 × Power × Atk/Def × STAB × Effectiveness × WeatherBoost × ShadowBoost ) + 1
```

### Modifiers (verified multipliers)
| Modifier | Value | Notes |
|----------|-------|-------|
| **STAB** | **1.2×** | Same in PvE and PvP since Niantic added a separate PvP STAB setting (same numeric value) |
| **Weather boost (PvE only)** | **1.2×** (i.e. +20%) | Excluded from GBL |
| **Weather catch-level bonus** | **+5 levels** | Wild 1–30 → 6–35; raid 20 → 25; TGR 8 → 13 |
| **Weather Stardust catch bonus** | **1.25×** | Applies to all catches under boosted weather |
| **Shadow attack** | **1.2×** | Stacks with STAB/weather/super-effective |
| **Shadow defense** | **0.833×** (effectively –17%) | "0.83×" per most sources |
| **Super-effective** | **1.6×** | (Doubly-SE = 2.56×) |
| **Not very effective** | **0.625×** | (Doubly-NVE = ~0.39×) |
| **Immune** | **0.390625×** (≈) | PoGO does not zero-out immunities, just very weak |

Example stack: Shadow Machamp Counter into Rock raid boss = **1.2 (Shadow) × 1.2 (STAB) × 1.6 (SE) = 2.304×** base. ([sportskeeda – STAB moves](https://www.sportskeeda.com/pokemon/pokemon-go-what-stab-moves-use))

### Move-changing TMs
- **Fast TM** — re-rolls fast move to a random non-current legal fast move from the species' pool. Cannot include event-exclusive moves.
- **Charged TM** — same, for charged moves.
- **Elite Fast TM** — player-chosen fast move from any of the species' **historical pool** (Community Day legacy moves included).
- **Elite Charged TM** — player-chosen charged move from historical pool.
- **Frustration** (Shadow exclusive — see §8) can only be replaced during specific limited-time TGR events; an Elite Charged TM by default **will not** remove Frustration.
- ([pokemon.com – TM Away Frustration](https://www.pokemon.com/us/strategy/shadow-pokemon-in-pokemon-go-tm-away-frustration-plus-tips-on-training-and-purifying))

---

## 5. Size Mechanic (XXS / XS / Normal / XL / XXL)

### Classification
- Five categories: **XXS, XS, M (displayed as no badge), XL, XXL**.
- All Pokémon species are eligible as of **January 17, 2023**.
- Classification is by **height & weight multipliers from the species' standard value**. Both metrics matter — the formula combines weight variate and height (`weight = weight_variate + (height − 1)` for XXL with max variate 1.5 and max height 1.55 / 1.75 / 2.00). The internal roll determines the category, then the visible height/weight is generated within the bucket's range.
- ([pokemongohub – Showcase scoring](https://pokemongohub.net/post/research/showcase-scores-xxs-and-xxl-pokemon-and-how-it-works/) — confirmed via search), ([serebii – size variance](https://www.serebii.net/pokemongo/size.shtml))

### `pokemon_size_category` integer mapping (project DB column)
**Not confirmed by any web source.** The exact 1–5 integer-enum encoding used by the proto / game-master was not surfaced in any community-accessible source during this session. The common convention from data-mining communities is:

```
1 = XXS
2 = XS
3 = Normal / M
4 = XL
5 = XXL
```

…but the project should **verify against the actual GAME_MASTER `POKEMON_SIZE_SETTINGS`** proto enum (`POKEMON_SIZE_XXS / XS / NORMAL / XL / XXL`) rather than trust this assumption. Likely the proto enum's ordering is the canonical mapping but values **may** be 0-indexed (XXS=0..XXL=4). **TODO for project: verify against extracted GAME_MASTER.**

### Rewards / perks given by size
1. **Showcases (the primary use):**
   - Max score = **1000 base + 178 XXL bonus = 1178**.
   - `score = ScaledHeight × 800 + ScaledWeight × 150 + ScaledIVs × 50`
   - The XXL bonus of +178 is a Niantic guarantee that XXL > XL regardless of stats.
2. **No XL Candy bonus for XXL/XXS** — XL Candy guarantees come from **evolution stage** (Stage 1 = 1 XL, Stage 2 = 2 XL, Legendary/Mythical/Ultra Beast = 3 XL), **not size**. Catching a high-level Pokémon increases XL drop chance, but XXL alone gives no XL bonus.
3. **Mighty Pokémon are more likely XL/XXL** at catch — so XL/XXL is a side-effect of high-IV Mighties.
4. Visible model change for XXS/XXL only ("tiny"/"HUGE" animation). XS, M, XL show identical models in-game.
5. **Mainline transfer (Pokémon HOME):** XXS Pokémon transfer with internal size value `0`; XXL transfer with `255` — making them eligible for the *Jumbo* / *Mini* marks in Scarlet/Violet.

---

## 6. Best Buddy Ladder

### Heart thresholds (lifetime hearts earned with that Pokémon as buddy)
| Level | Hearts | Badge |
|-------|--------|-------|
| Buddy | 0 | (none) |
| **Good Buddy** | 1 | Good Buddy badge |
| **Great Buddy** | 70 | Great Buddy |
| **Ultra Buddy** | 150 | Ultra Buddy |
| **Best Buddy** | 300 | Best Buddy + ribbon |

([gamerant – Best Buddy CP boost](https://gamerant.com/pokemon-go-best-buddy-cp-boost/))

### Hearts per day
- **Normal mood**: up to **10 hearts/day** (12 with Poffin)
- **Excited mood**: up to **20 hearts/day**
- Earned via: feed, walk (per 1/2/3/4 km depending on species), play, snapshot, battle together, visit new stop, etc.

### Best Buddy CP boost — the key mechanic
- **+1 level equivalent** to **CPM only while that Pokémon is the active buddy**.
- Mathematically: while active, the CP is recomputed using the CPM of **one level higher**. A L50 Best Buddy uses **CPM 0.8453** (the L51 anchor) instead of L50's 0.8403.
- Switch buddies → the boost is removed (the Pokémon retains the Best Buddy *badge/ribbon* but not the CP).
- This boost **never lets you exceed the max stat** for league caps in the sense that the Pokémon's "true" level remains its raw level; PvP IV rankings use the raw level. For Master League and raids the boost is **live damage**.

### 2025-2026 buddy changes
- Routes integration (Sponsored Routes) increased hearts-per-route slightly in 2024; no material formula change in 2025.
- Daily Adventure Incense interactions count toward buddy hearts in some modes.
- L70+ trainers have an increased Lucky Friend chance during the daily buddy interaction.
- No evidence of a buddy-CP-boost magnitude change in 2025-2026.

---

## 7. Lucky Pokémon

- **Triggered by:** trading. Each trade has a chance to produce a "Lucky" outcome; chance scales with the **age** of the **older** of the two Pokémon being traded (older = higher chance). One stale Pokémon + one fresh Pokémon is identical to two stale.
- **Distance bonus:** trading two Pokémon caught **≥ 100 km apart** boosts lucky odds to **5%**.
- **Lucky Friend status** (separate): once you are Best Friends (90-day milestone), each first interaction of the day has a small chance to flag both parties as Lucky Friends. The **next trade with that friend is a guaranteed Lucky Trade**.
- **Lucky Pokémon properties:**
  - **IV floor 12/12/12** (so min 14% chance of hundo per stat; the per-Pokémon hundo rate is **1/64**)
  - Stardust power-up cost **halved (0.5×)**
  - Visually marked with a gold sparkly background.
- L70+ trainers see an **increased chance of becoming Lucky Friends** (a benefit of the new L80 system).

Sources: ([Wondershare / drfone – trading discount guide](https://drfone.wondershare.com/virtual-location/stardust-trade-cost-pokemon-go.html)), ([dittobase – hundo odds](https://www.dittobase.com/pokemon-go/hundo-odds)).

---

## 8. Shadow & Purified Pokémon

### Shadow (Team GO Rocket / Shadow Raid)
- Possess the **Frustration** charged move (a 2-bar Normal-type 10-power move). **Frustration can only be replaced during specific TGR takeover events** with a regular Charged TM; otherwise it occupies one slot permanently.
- **Damage multipliers** (apply only to shadow attacker):
  - Attack stat × **1.2** (effectively +20% damage they deal)
  - Defense stat × **0.833** (≈ –17%, takes more damage)
- **Power-up cost multipliers** (vs. non-shadow):
  - Stardust cost × **1.2**
  - Candy cost × **1.2**
  - Second-charged-move unlock × 1.2 (Stardust + Candy)
- **IV floors:**
  - TGR grunt/leader catch: **0/0/0** (weather-boosted: 4/4/4)
  - Shadow Raid: **6/6/6** (7/7/7 boosted)
  - Giovanni shadow legendary: **6/6/6**

### Purification
- Removes Shadow status. Replaces Frustration with **Return** (a 130-power Normal charged move, 2 bars).
- **Each IV increased by 2** (cap 15). So a 13/13/13 shadow → 15/15/15 hundo after purification.
- Pokémon **gains +1 level** (Pokémon below L25 are bumped to L25 — verify against current game master).
- Power-up / second-move / evolve costs become **lower than even a normal Pokémon** (the discount is a deliberate purification incentive).
- Stardust+Candy cost to purify is per-species — example: **Weedle 1 000 dust + 1 candy → Legendary up to 20 000 dust + 20 candy**.
- ([pokemongo.fandom – purification cost](https://pokemongo.fandom.com/wiki/List_of_purification_cost))

### Practical note
A Shadow Pokémon with **Frustration unlocked** (i.e., Frustration TM'd out during a TGR event) plus a high-DPS legacy charged move is the most damage-efficient PvE attacker class in the game.

---

## 9. Adventure Effect Mechanic

### How it works
- Activated via the **Charged Move detail screen** on a qualifying Pokémon (i.e., the Pokémon must currently *know* the right signature charged move). The button "Activate Adventure Effect" appears.
- **Costs Stardust + that species' Candy** per activation.
- **Duration** is fixed per effect: **6 minutes or 10 minutes** depending on the move.
- **Extension:** all current Adventure Effects can be **extended** by paying more Stardust+Candy, up to a **24-hour daily cap of total active time per effect** ([dittobase guide](https://www.dittobase.com/pokemon-go/guides/how-to-use-pokemon-go-adventure-effects)).
- **Concurrency:** only **one** Adventure Effect can be active at a time. Activating a second cancels/replaces the first.
- **No explicit cooldown** between activations beyond the 24-hour-per-day cap.
- The "charges-remaining today" / "next-available-at" indicator is encoded in the Pokémon's proto — likely fields on the per-Pokémon record (the game stores per-day usage rather than a global per-account quota). **Project TODO:** the project's note that this is encoded in `pokemon_size_category` is almost certainly wrong; the correct field is more likely `bonus_attack_uses_remaining` / `adventure_effect_remaining_uses` or a usage timestamp.

### Full Adventure Effect list as of 2026-05-27 (**9 effects, 9 Pokémon forms**)

| # | Pokémon (form)              | Move             | Effect                                                                                | Duration | Cost                              |
|---|-----------------------------|------------------|---------------------------------------------------------------------------------------|----------|-----------------------------------|
| 1 | **Dialga (Origin Forme)**   | Roar of Time     | Pauses the timer on Incense, Daily Adventure Incense, Lucky Eggs, Star Pieces         | 6 min    | 5 000 dust + 5 Dialga candy       |
| 2 | **Palkia (Origin Forme)**   | Spacial Rend     | Increases the spawn radius for wild Pokémon around you                                | 10 min   | 5 000 dust + 5 Palkia candy       |
| 3 | **Necrozma (Dusk Mane)**    | Sunsteel Strike  | Game acts like it is daytime (day-only spawns appear; day-only evolutions work)       | 10 min   | 3 000 dust + 3 Necrozma candy     |
| 4 | **Necrozma (Dawn Wings)**   | Moongeist Beam   | Game acts like it is nighttime (night-only spawns appear; night-only evolutions work) | 10 min   | 3 000 dust + 3 Necrozma candy     |
| 5 | **Kyurem (Black)**          | Freeze Shock     | Wild encounters immobilized — easier to catch (+25%/+50% catch rate per source)       | 10 min   | 5 000 dust + 5 Kyurem candy       |
| 6 | **Kyurem (White)**          | Ice Burn         | Target ring slowed — easier Excellent throws (+50% catch rate)                        | 10 min   | 5 000 dust + 5 Kyurem candy       |
| 7 | **Zacian (Crowned Sword)**  | Behemoth Blade   | +10% Attack in Raids, +5% in Max Battles for the trainer's whole team                 | 6 min    | 5 000 dust + 5 Zacian candy       |
| 8 | **Zamazenta (Crowned Shield)** | Behemoth Bash | +10% Defense in Raids, +5% in Max Battles                                             | 6 min    | 5 000 dust + 5 Zamazenta candy    |
| 9 | **Eternatus**               | Dynamax Cannon   | +1 Max Move level for all Dynamax/Gigantamax Pokémon (cap-breaks 3→4)                 | 10 min   | 5 000 dust + 30 Eternatus candy   |

Sources confirm 9 effects as the **current** total ([dittobase guide](https://www.dittobase.com/pokemon-go/guides/how-to-use-pokemon-go-adventure-effects)), ([pokemongo.com fusion adventure effects – Necrozma](https://pokemongo.com/post/fusion-adventure-effects-necrozma)), ([pokemongo.com fusion adventure effects – Kyurem](https://pokemongo.com/post/fusion-adventure-effects-kyurem)).

### Pokémon often **incorrectly assumed** to have Adventure Effects (do NOT)
Several legendaries are widely speculated about but **have not been confirmed as Adventure-Effect-bearing as of 2026-05-27**:
- **Calyrex (Ice Rider)** — Glacial Lance is a signature charged move but **no Adventure Effect** is associated as of this snapshot.
- **Calyrex (Shadow Rider)** — Astral Barrage is a signature charged move; **no Adventure Effect**.
- **Solgaleo / Lunala** standalone — only their **Necrozma fusion** forms have Adventure Effects.
- **Reshiram / Zekrom** standalone — only their **Kyurem fusion** forms have Adventure Effects.
- **Marshadow** — no Adventure Effect.

**For the project's `ADVENTURE_EFFECT_IDS` set:** the 9 species/forms above are the canonical set. If the project set lists fewer than 9, it's missing entries; if it lists more, those extras should be re-verified.

---

## 10. Mega Evolution

### Levels and progression (Mega Levels are **per individual Pokémon**, not per species)
| Mega Level | Mega Evolutions needed (cumulative) | Mega-Energy cost (per evo) | Cooldown to next Mega Evo |
|------------|-------------------------------------|----------------------------|----------------------------|
| **(0 — never)** | 0 | **200** | 14 days |
| **Level 1 — Base**           | 1                                       | **41**                         | 7 days  |
| **Level 2 — High**           | 7 (i.e. 6 more after Base)              | **21**                         | 5 days  |
| **Level 3 — Max**            | 30 (i.e. 23 more after High)            | **11**                         | 3 days  |
| **Super Max (eligible species)** | spend +5 000 Mega Energy after Max | (effectively free first time after Super Max) | 24 hours |

(Some sources call Level 3 "Max" and Level 4 "Super High" / "Super Max" depending on translation. The progression structure above is the consistently reported one.)

### Cooldown decrease
- A Pokémon at low Mega Level has a **7-day cooldown** (after first activation; 14 days for the very first ever).
- At **Max / Super Max**, the cooldown drops to **24 hours**.

### Bonuses by Mega Level
At every level, a Mega Evolved Pokémon while active gives the team:
- **+10% damage** to all attacks for other team members in raids/Max Battles
- **+30% damage** to attacks **matching the Mega's type(s)** (so a Mega Steelix gives Steel and Ground attacks +30%, everything else +10%)
- These boosts apply to *other* trainers' Pokémon, not the Mega holder's own non-Mega Pokémon in the same raid lobby

Mega Levels add:
- **Level 2 (High)**: +50 XP per catch while active, ~10% XL Candy chance per catch
- **Level 3 (Max)**: +100 XP per catch, +2 type-candy per catch, 25% XL Candy chance per catch

### Mega form duration
- **8 hours** by default. Some events extend this.
- After 8 hours expires, the Pokémon reverts; it then enters a cooldown (length depends on the Mega Level above).
- During the active 8 hours the Pokémon **cannot** be deployed in gyms or PvP (some restrictions apply).
- Catch candy bonuses: catching a Pokémon while a Mega of the same type is active gives +1 type Candy and a small XL Candy chance.

([dotesports – Mega Evolution levels and costs](https://dotesports.com/pokemon/news/pokemon-go-mega-evolution-levels-bonuses-cooldown-and-costs-explained) via search)

### 2025-2026 changes
- No structural Mega change in 2025; new Mega species were added (e.g., Mega Metagross debut at October 2025 Raid Day per gamerant). Energy thresholds and cooldowns are unchanged.

---

## 11. Trade Mechanics

### Friendship levels & duration to reach
| Friendship | Days of daily interaction |
|-----------|---------------------------|
| Friend (none / 0 hearts)     | 0 (just added)   |
| Good Friend                  | 1 day            |
| Great Friend                 | 7 days           |
| Ultra Friend                 | 30 days          |
| Best Friend                  | 90 days          |

### Trade stardust costs (Special vs Standard)

A trade is a **Special Trade** if **either** Pokémon is:
- Legendary or Mythical, OR
- Shiny, OR
- Different forms of a species (e.g., Spinda variants beyond what you've registered), OR
- A species the receiver has **not yet registered in Pokédex**.

You can do **1 Special Trade per day**, period (no friendship-level increases this).

**Stardust cost matrix (Special Trade):**

| Friendship | Legendary/Shiny | Unregistered (regional, etc.) |
|-----------|-----------------|------------------------------|
| Good      | 1 000 000 dust  | 20 000 dust                  |
| Great     | 800 000 dust    | 16 000 dust                  |
| Ultra     | 80 000 dust     | 1 600 dust                   |
| Best      | 40 000 dust     | 800 dust                     |

Standard (non-Special) trade costs scale similarly but cap at **100 dust** for Best Friend. (Friendship discounts: Great = ~20%, Ultra = 92%, Best = 96%.)

### Lucky trade odds
- Two new Pokémon: ~5% baseline Lucky chance (varies by source).
- **Guaranteed Lucky** (current rule, re-verified 2026-09-20): a trade where either Pokémon was caught in **2020 or earlier** is guaranteed Lucky until the trainer's lifetime allowance of **45** guaranteed Luckies is spent. The window and the allowance have moved: 25→35 on 2025-02-18 (window: caught 2019 or earlier), then 35→45 on 2025-12-31 (window: caught 2020 or earlier), the rule in force in 2026.
- Distance-bonus (≥100 km apart): **+5%** absolute Lucky chance.
- **Lucky Friend status** (from Best Friend interactions): **next trade with that friend is guaranteed Lucky.**

### Other trade attributes
- **Original Trainer (OT)** field is permanently stored on the Pokémon; OT-matching is a requirement for the Aura ribbon and Showcase eligibility-like fields. Trades pass OT to the new owner record.
- A traded Pokémon **cannot be re-traded**.
- IVs are **re-rolled** at trade time with the floor depending on friendship (see §2 table).

([imobie – special trade guide](https://www.imobie.com/pokemon-go/special-trade-pokemon-go.htm)), ([drfone – trade discount guide](https://drfone.wondershare.com/virtual-location/stardust-trade-cost-pokemon-go.html))

---

## 12. Bag / Inventory / Tag Limits

### Pokémon storage
- **Maximum Pokémon storage: 11 150** (as of **November 11, 2025** capacity increase, +650). ([Pokémon GO X/Twitter announcement](https://x.com/PokemonGoApp/status/1987988717370261973))
- Upgrades are purchased in 50-Pokémon increments from the in-game Shop.

### Item bag
- **Maximum item bag: 10 500** (as of Nov 11 2025, +1 000). Upgrades in 50-item increments.
- Default at L1 is 350 items; upgrade purchasable starting around L10.

### Tag system
- **Maximum distinct tags per account: 100**.
- **Tag colors:** 8 — Red, Blue, Green, Yellow, Orange, Purple, Grey, Black.
- **Tag name length:** up to **16 characters**.
- **Tags per individual Pokémon:** **No publicly documented hard cap.** Niantic Help Center, Bulbapedia, Fandom Wiki, and Gamepur all describe tags as "multiple per Pokémon" but **none confirm a 14-tag-per-Pokémon limit**. The visual display only shows up to **3 tags** and an ellipsis (`…`). The "14" figure used by the project is **not corroborated by any reachable web source** — it is plausibly a project heuristic or an inference from the protobuf field size.
- **Trainer level requirement to use tags:** **L14+**.
- ([pokemongo.fandom – Tag](https://pokemongo.fandom.com/wiki/Tag)), ([gamepur – tag limits](https://www.gamepur.com/guides/all-tagging-colors-and-maximum-number-of-tags-you-can-have-in-pokemon-go))

**Action for the project:** verify the 14-tag-per-Pokemon assumption by either (a) inspecting an actual `Pokemon` proto extraction to count `pokemon_tag` repeated-field entries the game writes, or (b) experimentally tagging one Pokémon with >14 tags to see if the UI blocks the 15th. **Until verified, treat "14" as unconfirmed.**

---

## Summary of confirmed 2025-2026 changes

| Change | When | Source |
|--------|------|--------|
| Trainer level cap raised 50 → 80 + full XP rebalance | **2025-10-15** | [pokemongo.com](https://pokemongo.com/en/post/pgo-leveling-update-details-2025) |
| Daily Adventure Egg (L15+) | 2025-10-15 | same |
| Pokémon storage cap → 11 150 | **2025-11-11** | [Niantic on X](https://x.com/PokemonGoApp/status/1987988717370261973) |
| Item bag cap → 10 500 | 2025-11-11 | same |
| Adventure Effects expanded to 9 (Necrozma fusions added 2024 → 2025, Kyurem fusions added at Tour Unova 2025) | 2024-2025 | [pokemongo.com fusion AE Necrozma](https://pokemongo.com/post/fusion-adventure-effects-necrozma), [Kyurem](https://pokemongo.com/post/fusion-adventure-effects-kyurem) |
| Mighty Pokémon mechanic (Wild Area events; 13/13/13 floor) | First introduced 2024, continued through 2025 Wild Area | [pokemongohub - what are mighty pokemon](https://pokemongohub.net/post/guide/what-are-mighty-pokemon/) |
| Memories in Motion (S26) GBL season runs | **2026-03-03 → 2026-06-02** | [pokemongohub – S26 GBL](https://pokemongohub.net/post/pvp/go-battle-league-memories-in-motion/) |
| Late May 2026 GBL: Great + Ultra + Master simultaneous (May 26 → Jun 2) | 2026 | [Dexerto – S26 schedule](https://www.dexerto.com/pokemon/pokemon-go-battle-league-schedule-rewards-1706626/) |

---

## Confidence / unresolved items

1. **CPM table**: resolved 2026-09-21 — read from the client game master (`PLAYER_LEVEL_SETTINGS` → `playerLevel.cpMultiplier`, 80 levels); see §1.
2. **`pokemon_size_category` integer enum 1–5 mapping**: assumed XXS=1..XXL=5 but **not** verified against the proto. Could be 0-indexed. Verify in extracted GAME_MASTER.
3. **14-tag-per-Pokémon limit**: **unconfirmed by any web source**. Display limit is 3 tags + "…"; the *applied* limit may be higher. Recommend in-game test or proto inspection.
4. **Mighty Pokémon IV floor**: resolved — **13/13/13** (verified 2026-09).
5. **Calyrex / Solgaleo / Lunala / Reshiram / Zekrom / Marshadow Adventure Effects**: standalone forms **do not** have Adventure Effects as of this snapshot. Only the **fusion forms** (Necrozma DM/DW, Kyurem B/W) carry them.
6. **Exact Adventure Effect daily-cap encoding in the proto**: the *charges-remaining* / next-eligible-time fields are encoded in the per-Pokémon proto but I could not confirm the exact field name from public sources. The project's prior speculation that uses-left lives in `pokemon_size_category` is almost certainly wrong — that column holds the size enum.

---

## Source list (load-bearing URLs)

- https://pokemongo.com/en/post/pgo-leveling-update-details-2025
- https://x.com/PokemonGoApp/status/1987988717370261973
- https://www.dittobase.com/pokemon-go/hundo-odds
- https://www.dexerto.com/pokemon/pokemon-go-iv-floors-by-encounter-1012278/
- https://www.dittobase.com/pokemon-go/weather
- https://www.dittobase.com/pokemon-go/guides/how-to-use-pokemon-go-adventure-effects
- https://pokemongo.com/post/fusion-adventure-effects-necrozma
- https://pokemongo.com/post/fusion-adventure-effects-kyurem
- https://www.serebii.net/pokemongo/adventureeffect.shtml
- https://pokemongo.fandom.com/wiki/Adventure_Effects
- https://www.serebii.net/pokemongo/megaevolution.shtml
- https://dotesports.com/pokemon/news/pokemon-go-mega-evolution-levels-bonuses-cooldown-and-costs-explained
- https://leekduck.com/events/gbl-memories-in-motion_master-league_catch-cup-memories-in-motion-great-league-edition/
- https://www.dexerto.com/pokemon/pokemon-go-battle-league-schedule-rewards-1706626/
- https://www.dexerto.com/pokemon/pokemon-go-memories-in-motion-season-3325703/
- https://pokemongo.fandom.com/wiki/Tag
- https://www.gamepur.com/guides/all-tagging-colors-and-maximum-number-of-tags-you-can-have-in-pokemon-go
- https://pokemongo.fandom.com/wiki/Buddy_Pok%C3%A9mon
- https://www.pokemon.com/us/strategy/shadow-pokemon-in-pokemon-go-tm-away-frustration-plus-tips-on-training-and-purifying
- https://pokemongo.fandom.com/wiki/List_of_purification_cost
- https://drfone.wondershare.com/virtual-location/stardust-trade-cost-pokemon-go.html
- https://www.imobie.com/pokemon-go/special-trade-pokemon-go.htm
- https://bulbapedia.bulbagarden.net/wiki/Stat_(GO)
- https://www.switchbladegaming.com/pokemon-go/pvp-iv-guide/
- https://pvpoke.com/articles/strategy/guide-to-fast-move-registration/
- https://www.sportskeeda.com/pokemon/pokemon-go-what-stab-moves-use
- https://x.com/PokemonGOHubNet/status/1858067654784774496
