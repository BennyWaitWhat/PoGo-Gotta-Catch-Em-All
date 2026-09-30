# Pokémon GO — Major NEW FRAMEWORK Additions (2024 → 2026-05-27)

**Research date:** 2026-05-27
**Scope:** Structural player-facing systems Niantic/Scopely have added since early 2024 that materially change day-to-day play.
**Sourcing:** Live web research (pokemongo.com, pokemongohub.net, leekduck.com, dexerto, serebii, pokemon.com, fandom wikis, niantic helpshift, Scopely press, gamerant, pocketgamer). Items dated Feb–May 2026 are from post-cutoff live searches.

---

## 1. Dynamax + Gigantamax / Max Battles (THE headline framework addition)

**Launched:** Season of Max Out — September 3, 2024 (season start). Dynamax Pokémon began spawning at Power Spots on **September 10, 2024 at 10:00 a.m. local**. Gigantamax debuted during the **GO Bigger event on October 26, 2024** (Gigantamax Venusaur first).

**Core mechanics**
- **Power Spots** = gray tower-like map structures (magenta orbs). Temporary, persist up to ~2 days. Two interactions: (a) drop a Pokémon into a Power Spot to earn Candy and boost the spot for later raiders, (b) consume a Power Spot to start a Max Battle.
- **Max Particles** are a separate currency from Stardust. Daily cap of **800 MP**, refill by visiting Power Spots (~100 MP per spot, +20 first-visit bonus). Battle costs scale by star tier (250 MP at 1-star → 800 MP at 5/6-star).
- **Max Battles** are co-op battles against Dynamax/Gigantamax bosses. Up to **40 trainers per Power Spot**, split into parties of **4**. Only Dynamax-eligible Pokémon may enter — six-slot Max Party.
- **MAX moves**: Max Attack (type-based offensive), Max Guard (damage reduction), Max Spirit (party heal). Each starts at level 1; only Max Attack is unlocked by default — **Max Guard and Max Spirit are locked until levelled**. Levelling uses **Max Particles + species candy + species candy XL**. New Max Attack variants released during 2025: Max Rockfall (Mar 4 2025), Max Flutterby (Mar 24 2025), Max Starfall (Jun 16 2025).
- **Max Mushrooms** = consumable that 2× damage of all Dynamax/Gigantamax Pokémon for **30 minutes** (stack duration, not multiplier).

**Per-Pokémon state added**
- **Dynamax-eligible flag** — species-level. Per Serebii's roster, ~150+ species are flagged Dynamax-capable; 16 of those also have a Gigantamax form (see roster below).
- **Per-individual Max move levels**: Max Attack level, Max Guard level, Max Spirit level (each requires unlock + levelling separately, so this is per-instance state, not just per-species).
- **Form flag**: Dynamax vs Gigantamax (some species like Charizard, Pikachu, Snorlax, Lapras have both — Gigantamax is the rarer/distinct-model form).
- A caught Dynamax/Gigantamax Pokémon is permanently flagged in your bag (filterable in inventory).

**Gigantamax roster (as of May 2026)** — 16 species confirmed: Venusaur, Charizard, Blastoise, Butterfree, Pikachu, Meowth, Machamp, Gengar, Kingler, Lapras, Snorlax, Rillaboom, Cinderace, Inteleon, Toxtricity, Grimmsnarl. Eternamax Eternatus debuted as a battle-only encounter at GO Fest 2025: Max Finale (Aug 23–24 2025) — Eternatus itself is catchable via the GO Pass: Max Finale, but Eternamax form cannot be caught. Crowned Sword Zacian + Crowned Shield Zamazenta returned via raids in 2025 as legendary Max-capable forms.

**2025–2026 evolution**
- GO Fest 2025: Max Finale (Aug 23–24 2025) — Eternatus debut, return of every prior Dyna/Gmax boss, uncapped Max Battle participation.
- Gigantamax Pikachu debuted **March 28, 2026** (Max Battle Day).
- Replay: GO Bigger (April 2026) — return of the four Kanto starters' Gmax forms + Gengar.
- "Max Mondays" (since Memories in Motion season, March 2026) — Power Spots only widely available on Mondays under the Daily Discovery schedule, plus dedicated Max Battle Days. **This is a significant cadence change**: Max content used to be everyday; it is now largely Monday-gated.

**Sources:**
- https://www.serebii.net/pokemongo/maxbattles.shtml
- https://pokemongo.com/max-pokemon-battle
- https://www.dexerto.com/pokemon/every-dynamax-and-gigantamax-pokemon-in-pokemon-go-so-far-2876339/
- https://pokemongohub.net/post/guide/max-attackers-tier-list/
- https://nintendowire.com/guides/pokemon-go/season-of-max-out/max-battles-max-particles-power-spots-dynamax-pokemon/

---

## 2. Routes

**Launched:** July 2023 (so older than the 2024 cutoff, but the surrounding ecosystem — Mateo, Wiglett biomes, Zygarde — is 2023-2024). Listed because most of its dependent content is post-2024.

**Mechanics**
- A **Route** is a saved walking path between two PokéStops/Gyms. Created in two ways: by Niantic, an official partner, or by any player (record the walk, submit for review, become available to community once accepted).
- Following a Route: open the Nearby panel → Routes tab → tap a nearby Route → walk it → tap COMPLETE ROUTE at the endpoint. First completion of a unique Route = Route Badge (badges are permanent per route).
- **Bonuses while on a Route**: accelerated buddy candy, longer Incense effect on a fresh Route, daily XP bonus (boosted after 7-day streak), buddy hearts.
- **Zygarde Cube** (in-bag item): cells fill the Cube. **50 cells → Zygarde 10% Forme**, **200 cells → Zygarde Complete Forme**. Max **3 cells per day**; cells only have a chance to appear the first time you walk each unique Route per day. Cube also shows running cell count.
- **Mateo (NPC)** — see §5.

**Per-Pokémon state**
- **No** "caught on Route" flag for ordinary spawns has been confirmed.
- **Biome-locked species** are effectively Route/biome flagged via where they spawn (see below). The bag-side metadata isn't a flag, but the *only place* certain species spawn is on Routes that pass through specific biomes.

**Biome-exclusive species** (the de-facto Route-locked roster as of May 2026):
- **Wiglett → Wugtrio** — Beach biome only (50 Wiglett candy to evolve). Adventure Week 2025 added shiny Wiglett.
- **Toedscool / Toedscruel** — forested/grassy biomes.
- **Silicobra → Sandaconda** — desert biome (added Memories in Motion 2026).
- **Orthworm** — desert biome (added Memories in Motion 2026).
- **Cyclizar** — NOT yet released in Pokémon GO as of 2026-05-27.

**2025–2026 evolution**
- Memories in Motion (March 2026) added Blipbug, Flittle, Silicobra, Orthworm, and Mimikyu spawns with biome ties.
- QoL: Nearby panel now lists more Routes; directional arrows; cell counter visible in Zygarde Cube.

**Sources:**
- https://pokemongo.com/routes
- https://leekduck.com/events/routes-new-feature/
- https://pokemongohub.net/post/guide/biomes-in-pokemon-go-complete-guide/
- https://pokemongohub.net/post/guide/pokemon-go-routes-everything-you-need-to-know/

---

## 3. Party Play

**Launched:** October 17, 2023 (pre-2024 but expanded materially in 2024+).

**Mechanics**
- 4-trainer parties, level 15+. Host invites; party persists for ~1 hour (longer during events e.g. Sinnoh Tour didn't expire).
- **Party Challenges** — chosen by host; shared progress; everyone gets the reward. Categories: Pokémon, Throws, Adventure, Battle, General.
- **Party Power** (raid-only buff): doubles next Charged Attack damage; charges with Fast Attacks; more party members = faster charge.
- **Item sharing** added August 2024.

**Per-Pokémon state**
- **No per-Pokémon state added**. Party Play is a session-level feature; nothing is stored on a caught Pokémon to mark it as "caught in a party". (Important: do **not** add a tag like "party caught" to your culling schema — it has no in-game representation.)

**Sources:**
- https://pokemongohub.net/post/guide/go-hub-guide-to-party-play/
- https://leekduck.com/events/party-play-feature/

---

## 4. PokéStop Showcases

**Launched:** late 2023; **major restructure January 2024 and again September 2024**.

**Mechanics**
- A PokéStop runs a contest for a defined window (typically 10:00 a.m. – 8:00 p.m. local on **Showcase Tuesdays** as of 2026). Trainers deposit one eligible Pokémon. Highest score at deadline wins.
- **Score formula** (per individual Pokémon entry):
  `score = scaled_height × 800 + scaled_weight × 150 + scaled_IVs × 50`
  Theoretical individual max: **1178** (species-targeted showcases). XXL bonus: **+178** added on top.
- Showcase **categories** in 2026:
  - **Species-specific** (e.g. "biggest Wailmer").
  - **Type-based** (added Jan 2024) — any Pokémon of a given type can enter; in Sept 2024 they were re-normalised so each species scores against its own species mean (so any XXL of any species of that type can compete).
  - Up to **20 different categories on a Showcase Tuesday** in the Forever Forward season.

**Per-Pokémon state implications**
- The size category (**XXS / XS / Normal / XL / XXL**) is per-individual permanent state, set at catch — *this is the single most important per-Pokémon attribute showcases interact with*.
- Height and weight are stored per-individual (have been since 2016). Showcases gave them mechanical relevance from late 2023 on.
- Per-species **Pokédex records**: largest, smallest, heaviest, lightest caught — populated once you've caught ≥3 of a species. Worth surfacing in any "do not cull" criteria.

**2025–2026 evolution**
- Tuesday-gated under Daily Discovery schedule starting Memories in Motion (March 2026).
- May 26, 2026: PokéStops hosting Showcases were refreshed (rotation update).
- Showcase Tuesdays now standard 10am–8pm local.

**Sources:**
- https://pokemongohub.net/post/research/showcase-scores-xxs-and-xxl-pokemon-and-how-it-works/
- https://pokemongohub.net/post/news/major-changes-made-to-pokestop-showcases/
- https://nintendowire.com/guides/pokemon-go/showcase-tuesday-for-may-26th-2026/
- https://pokemongo.com/post/different-sized-pokemon-in-pokemon-go-xxl-xxs

---

## 5. Mateo / Wandering Wayfarer (Gift Exchange)

**Launched:** December 5, 2023 (Along the Routes event) — relevant to 2024+ context.

**Mechanics**
- Mateo is an NPC researcher who appears at the **endpoint of a completed Route**, much like a Rocket Grunt does on the map.
- Interaction = Gift Exchange: you give a Gift, you receive a Gift back from another player anywhere in the world. The Postcard attached to the received Gift counts toward **Vivillon Collector medal** progress (regions you've collected from).
- **Cap**: one Mateo Gift Exchange per day.
- Gifts handed to Mateo do **not** consume your bag's Gift inventory — they're generated from local PokéStops/Gyms when the exchange begins.

**Per-Pokémon state**
- None. Mateo affects Postcard book / Vivillon medal progress (Scatterbug/Spewpa/Vivillon line — 2,250 candies per pattern).

**2025–2026 evolution**: no significant change. Still daily-capped via Routes.

**Sources:**
- https://www.pokemon.com/us/pokemon-news/pokemon-gos-along-the-routes-event-introduces-mateo
- https://dotesports.com/pokemon/news/how-does-mateos-route-gift-exchange-work-in-pokemon-go
- https://leekduck.com/events/vivillon-launch-postcard-feature/

---

## 6. Gimmighoul / Gholdengo

**Mechanics (active since Nov 2023, fully relevant in 2024+):**
- **Coin Bag** is unlocked by sending a Postcard from Pokémon GO to Pokémon Scarlet/Violet on Switch (one-time tie-in).
- Opening Coin Bag = 30-minute window where Gimmighoul (Roaming Form) spawns roughly every 1.5 minutes.
- **Gimmighoul Coins** are a separate per-account currency (not stardust, not candy). Sources: catching Gimmighoul, spinning **Golden PokéStops** (PokéStops with a **Golden Lure** active), buddy-walking Gimmighoul.
- **Evolution requirement**: **999 Gimmighoul Coins** to evolve into Gholdengo. **No Gimmighoul Candy is consumed** — this is the only candy-less evolution in the game.

**Per-Pokémon state**
- Gimmighoul's "Roaming Form" is the only form catchable in GO.
- Coin count is account-level inventory state, not per-individual.

**Sources:**
- https://pokemongohub.net/post/tips-and-tricks/how-to-get-gimmighoul-coin-bag-in-pokemon-go/
- https://www.nintendolife.com/guides/pokemon-go-how-to-evolve-roaming-form-gimmighoul-into-gholdengo
- https://bulbapedia.bulbagarden.net/wiki/Gimmighoul_Coin

---

## 7. Wiglett / Wugtrio

Covered under §2. **Beach biome-locked** species. 50 Wiglett candy evolves to Wugtrio. Shiny Wiglett added Adventure Week 2025.

---

## 8. Daily Adventure Incense & Galarian Birds

**Mechanics**
- Auto-added to bag at midnight local each day, **15 min duration** (vs. 1hr for normal Incense), must be used before midnight (can't stockpile). Coin-purchasable upgrade to 60 min still available.
- Only source of **Galarian Articuno / Zapdos / Moltres** in the wild. Base catch rate 0.3%, flee rate 90%. Shiny rate ~1/20; **shiny variants of Galarian birds will NOT flee** — you keep throwing balls until you run out, which makes them effectively guaranteed once seen.

**2025–2026 evolution**
- **GO Pass Rank 50** (under the new monthly progression system) doubles Daily Adventure Incense duration as a Rank 50 perk. This is a notable structural buff for grinders.

**Per-Pokémon state**: standard — no special DAI flag. Galarian regional forms are species/form-tagged like any regional.

**Sources:**
- https://pokemongohub.net/post/guide/daily-adventure-incense-release/
- https://www.dittobase.com/pokemon-go/guides/how-to-catch-galarian-birds-pokemon-go
- https://bulbapedia.bulbagarden.net/wiki/Incense_(GO)

---

## 9. Sponsored / location-based integrations (2024-2026)

No major new flagship sponsor launches in 2024-2026 comparable to the 2019 7-Eleven Japan or 2021 Verizon events. The standing sponsor framework (Verizon-sponsored PokéStops, Sponsored Gyms, Sponsored Gifts; AmazingFitness pods, Yoshinoya/7-Eleven Mexico) continues but with no novel cross-program spawn mechanic added in the research window. Sponsor backgrounds (Verizon avatar clothing) remained available.

**Per-Pokémon state**: nothing new — Sponsored gifts/PokéStops just route through normal gift/stop systems.

**Sources:**
- https://pokemongo.fandom.com/wiki/Official_sponsorship
- https://pokemongohub.net/post/news/verizion-clothing-now-available-worldwide/

---

## 10. GO Tour 2026 + GO Fest 2026

### GO Tour 2026: Kalos
- **In-person**: Los Angeles, USA + Tainan, Taiwan, **February 20–22, 2026**.
- **Global**: **February 28 – March 1, 2026**.
- **Road to Kalos** (Feb 23–27, 2026): revisits Kanto/Johto/Hoenn/Sinnoh/Unova legendaries with special backgrounds. (Per pokemongohub.)
- **Mega Lucario** debuted as the first Z-A-themed Mega; **Mega Charizard X** followed; **Mega Gyarados** and **Mega Charizard Y** rolled out across 2025.

### GO Fest 2026 (Pokémon GO 10th Anniversary)
- **Tokyo**: Tokyo Waterfront City, **May 29 – June 1, 2026** (literally this weekend — TODAY is 2026-05-27).
- **Chicago**: Grant Park, **June 5–7, 2026**.
- **Copenhagen**: Fælledparken, **June 12–14, 2026**.
- **Global**: **July 11–12, 2026** — for the first time, **FREE for all logged-in trainers**.
- **Debuts**: **Mega Mewtwo X + Mega Mewtwo Y** (Super Mega Raid Battles), **Zeraora** (Mythical, Special Research, free for all), team-hat Pikachu (Mystic at Tokyo, Valor/Instinct etc. across other in-person events), Shiny Wash Rotom, Shiny Tauros, regional Comfey.

**Sources:**
- https://leekduck.com/events/pokemon-go-fest-2026-global/
- https://leekduck.com/events/pokemon-go-fest-2026-tokyo/
- https://pokemongohub.net/post/event/pokemon-go-fest-2026-global/
- https://gamerant.com/pokemon-go-tour-2026-cities-dates/
- https://pokemongohub.net/post/event/road-to-kalos/

---

## 11. Niantic → Scopely transition (CRITICAL CONTEXT)

- **Announced:** March 12, 2025.
- **Closed:** **May 29, 2025**, valued at **$3.5 billion**.
- **What transferred:** Pokémon GO, Pikmin Bloom, Monster Hunter Now, Campfire and Wayfarer companion apps, ~400 Niantic Games employees.
- **What stayed at Niantic:** the AR/maps tech platform spun out as **Niantic Spatial Inc.** (CEO: John Hanke); Ingress Prime and Peridot remain there.
- **Pokémon GO operations:** continue under Kei Kawai + Ed Wu (existing studio leads). No layoffs at closing. Michael Steranka (Senior Product Director) publicly stated no forced ads / no disruptive monetization. **As of May 2026 there is no second client, no engine swap — core mechanics unchanged.**
- **Scopely-era cadence shifts observable in 2026:**
  - Move away from paid event tickets toward **GO Pass Deluxe** ($7.99 typical, $14.99 for big-event Deluxe like Max Finale).
  - **Daily Discovery** weekly schedule (Memories in Motion, March 2026) gates major features to specific weekdays (see §13/§14).
  - Field Research now season-long instead of monthly-rotating (Forever Forward).
  - Standardised Saturday-Sunday event windows; weekend events moved to Saturdays.
  - **Remote Trading + Forever Friends** (Dec 8, 2025) — first major mechanical change under Scopely.

**Sources:**
- https://www.scopely.com/en/news/scopely-to-acquire-niantic-games-business-which-includes-pokemon-go-one-of-the-most-successful-mobile-games-of-all-time
- https://pokemongohub.net/post/news/scopely-completes-the-acquisition-of-niantics-game-business/
- https://www.pocketgamer.biz/pokemon-go-under-new-ownership-as-scopely-closes-35bn-niantic-deal/
- https://massivelyop.com/2025/06/06/massively-on-the-go-the-good-the-bad-and-the-ugly-of-pokemon-gos-transition-to-scopely/

---

## 12. Sleep / Wellness integration

**Status: dormant / mostly defunct as of May 2026.**

- Original Catching Some Z's event ran July 15–16, 2023, alongside Pokémon GO Plus+ device launch. Snorlax-with-nightcap was the headline Special Research reward; pairing required the GO Plus+ device + Pokémon Sleep app + Pokémon GO.
- No new Catching Some Z's research events have been announced for 2024, 2025, or 2026.
- The GO Plus+ device is still listed as compatible with Pokémon Sleep on niantic.helpshift.com, but no further GO ↔ Sleep crossover Special Research has shipped.

**Per-Pokémon state**: Komala remains catchable as a normal mon (no Sleep-specific flag). Snorlax with nightcap was a one-time costume.

**Sources:**
- https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/4163-pokemon-go-plus-and-pokemon-sleep/
- https://pokemongo.com/post/pokemon-sleep-pokemon-go-plus-plus-event

---

## 13. Adventure Sync / Weekly Steps / Adventure Effects (cross-reference)

(Owned by another agent — concise corroboration only.)

**Adventure Effects** are temporary out-of-battle bonuses triggered by certain Signature Attacks of specific Pokémon, consuming Stardust + that species' candy. Confirmed effects active in May 2026:
- **Sunsteel Strike** (Solgaleo) — daytime-Incense effect + forces daytime evolutions (Espeon, etc.) regardless of clock.
- **Moongeist Beam** (Lunala) — nighttime-Incense effect + forces nighttime evolutions (Umbreon, Ursaluna, etc.).
- **Behemoth Blade** (Crowned Sword Zacian) — +10% Attack in Raids, +5% Attack in Max Battles.
- Others exist (Rending Claws, etc.).

**Per-Pokémon state**: a species' Adventure-Effect-eligible move is per-individual move state (taught/unlocked). Most are signatures of legendaries.

**Mega Evolution** (cross-ref): Through Gen 6 nearly all Megas implemented as of "Changing Story" season (Sep 2 2025). Mega Mewtwo X + Y debut **July 11–12, 2026** at GO Fest Global.

**Sources:**
- https://www.serebii.net/pokemongo/adventureeffect.shtml
- https://pokemongo.fandom.com/wiki/Adventure_Effects
- https://www.sportskeeda.com/pokemon/all-yet-released-mega-evolutions-regional-variants-forms-pokemon-go

---

## 14. AR / Postcard / Photo features (Buddy + camera)

**Buddy system in 2026:**
- 4 Buddy levels (Good → Great → Ultra → Best). Buddy History (since Memories in Motion) tracks every prior buddy, time played, and **Souvenirs** brought.
- **Souvenirs** are buddy-brought-back collectible items. Ultra Buddy unlocks Souvenir chance.
- Affection hearts include "spin a new Photo Disc you've never spun" with your buddy on the map.
- Buddy mood is "readable" from Good Buddy onward.

**"What's Your Favorite?" camera feature (March 2026, Memories in Motion):**
- Lets you take AR photos with **any** Pokémon — even species you haven't caught yet. This is a major shift from the old GO Snapshot, which required ownership.
- Includes a 5-second self-timer countdown.
- Part of the year-long "What's Your Favorite?" 30th-anniversary brand campaign (Lady Gaga, Trevor Noah, Jisoo et al. — Super Bowl LX commercial).

**Per-Pokémon state**: GO Snapshot encounters from buddy still drop the rare 1-in-N "Snapshot bonus" mon (Smeargle, etc.). Buddy Souvenirs are per-Pokémon items in your bag. No new "photographed" flag on caught Pokémon.

**Sources:**
- https://pokemongohub.net/post/ar/whats-your-favorite-special-research-new-ar-feature/
- https://pokemongohub.net/post/guide/go-hub-guide-to-buddy-interactions-in-pokemon-go/
- https://www.gamespot.com/articles/pokemon-go-memories-in-motion-offers-more-shiny-pokemon-and-new-events/1100-6538392/

---

## 15. Trades / Friendship — **MAJOR 2025-2026 OVERHAUL**

### Forever Friends + Remote Trading (December 8, 2025)
The single biggest social-system change since the trade-distance experiment.

**Forever Friends** — a new **6th friendship tier** above Best Friends.
- Requires **90 Friendship Points** earned *after* hitting Best Friends. (Some sources say 180 total points; the canonical figure is 90 post-BF.)
- **Friendship Points** is a new progression replacing the old daily-interaction-only model. Up to **1 FP per day per friend** from interactions (open gift, raid, trade, battle, send gift). Plus up to **7 FP per week** from completing **Weekly Challenges** with that friend.
- Friend list cap raised from **450 → 650** in early 2026.

**Remote Trading**
- Once you're Forever Friends with someone, the **100m proximity requirement is removed**. You can trade from anywhere globally.
- **1 Remote Trade per friend pair per day.**
- Stardust costs are the **same as in-person** (Good/Ultra/Best Friend tier still applies; new/shiny/regional surcharges unchanged).
- **Restrictions**: Pokémon caught in last **30 days** cannot be remotely traded. Mythicals cannot be remotely traded. Cross-region rules unchanged.

**Lucky Trade tuning**
- **Lucky trade lifetime cap raised from 25 → 35** in 2026.
- **Lucky Friends** mechanic still works remotely — first trade after becoming Lucky Friends guarantees Lucky, then the status clears.
- The "caught before 2019" guaranteed-Lucky rule remains, now subject to the new 35-trade cap.
- Lucky Friends odds (community-estimated ~1.1% per first daily interaction with a Best Friend) unchanged officially.

**Per-Pokémon state implications**
- **Tradeable / Untradeable** flag is **now date-sensitive on remote trades** (30-day rule). Pokémon caught <30 days ago can still in-person trade.
- **Lucky** flag is per-individual permanent (existing).
- A traded Pokémon has the "received from trade" attribute, IV-rerolled at receipt (existing). Friendship tier at time of trade determines IV floor (existing — Best Friend = 5/5/5, Forever Friends inherits Best Friend floor; no separate floor confirmed yet for FF).

### Friendship Friday (under Daily Discovery)
Every Friday: up to **2 Special Trades**, increased Lucky-Trade chance, **-10% Stardust** trade cost, **2 guaranteed Candy XL** from trades for trainers ≥ L31.

**Sources:**
- https://pokemongo.com/news/pgo-remote-trade-2025
- https://pokemongohub.net/post/news/forever-friends-and-remote-trading-debut-in-major-friendship-update/
- https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/1485-lucky-friends/
- https://www.techtimes.com/articles/312634/20251111/secrets-pokemon-go-friendship-system-2025-key-insights-lucky-friend-changes-friend-rewards.htm
- https://anyto.imyfone.com/pokemon-go/pokemon-go-remote-trades/

---

## 16. (Bonus framework) Daily Discovery — the new weekly cadence (March 2026)

Not in the original scope list but it's the single biggest day-to-day pacing change of 2026. Added at start of **Memories in Motion** (March 3, 2026), continued in **Forever Forward** (June 2 → Sep 8, 2026).

| Day | Theme | Headline bonus |
|---|---|---|
| Sun | Double-Time Sunday | Incense + Lure last 2× |
| Mon | Max Monday | Max Battles 6am–9pm + Fast-Track |
| Tue | Showcase Tuesday | PokéStop Showcases 10am–8pm, up to 20 categories |
| Wed | Raid Wednesday | 5★/Mega rotation, Raid Hour 6–7pm |
| Thu | GO Battle Thursday | 4× Stardust from GBL, 50 battles allowed |
| Fri | Friendship Friday | 2 Special Trades, lucky↑, -10% dust, 2 XL Candy from trade |
| Sat | (free) | Reserved for Community Day |

Paused during GO Fest / GO Wild Area / GO Tour weeks.

**Sources:**
- https://www.switchbladegaming.com/pokemon-go/daily-discovery-guide/
- https://pokemongohub.net/post/event/memories-in-motion-pokemon-go-season/

---

## 17. (Bonus framework) Mighty Pokémon (Wild Area mechanic, Nov 2025)

Debuted at GO Wild Area 2025: Global (Nov 15–16, 2025). A wild-encounter variant with:
- Guaranteed **13/13/13 minimum IVs**.
- Always **final evolution**.
- Catch level **35–40** (unboosted) or **40–45** (weather-boosted) — well above the normal L1–35 wild range.
- Visually marked by a **yellow aura** on the map and `!!!` for CP in the encounter screen.
- More likely to be XL/XXL. Much harder catch — uses event-exclusive **GO Safari Balls** (high catch rate, disappear at event end).

**Per-Pokémon state**: appears identical once caught — there is **no permanent "Mighty" flag on the bag entry**, only the catch-level (40+) and high IVs give them away. Worth noting: anything caught at L40+ pre-Best-Buddy is essentially diagnostic of a Mighty origin.

**Sources:**
- https://pokemongohub.net/post/guide/what-are-mighty-pokemon/
- https://leekduck.com/events/pokemon-go-wild-area-2025-global/
- https://pokemongohub.net/post/meta/analyzing-every-mighty-pokemon-in-go-wild-area-2025/

---

## Per-Pokémon state additions to capture in tagging/culling (synthesis)

These are the NEW pieces of per-individual data introduced by 2024+ frameworks that any responsible culling script should respect:

1. **Dynamax-eligible flag** (species level, ~150+ species).
2. **Gigantamax form flag** (16 species). Distinct caught entry from the same species' Dynamax.
3. **Per-instance Max Move levels** — Max Attack lvl, Max Guard lvl (unlocked?), Max Spirit lvl (unlocked?). Investment lost on transfer.
4. **Size category** XXS/XS/N/XL/XXL — populated since 2023 but mechanically relevant from late-2023 Showcases on. **XXL = +178 Showcase bonus.** XXS = collectable, no Showcase score bonus but plays in XXS-themed categories.
5. **Pokédex size records** — largest/smallest/heaviest/lightest per species. Cull-prevention: never transfer a record-holder without checking.
6. **Mighty origin** (inferred from catch level ≥40 + high IV floor; no explicit flag).
7. **Lucky** flag (per-individual, permanent, pre-existing but Lucky rules tuned in 2026: 35-cap, remote-trade-eligible).
8. **Caught ≤30 days ago** — blocks Remote Trade; matters if your trading strategy is built around remote.
9. **Souvenir items** — bag items, not on Pokémon, but tied to specific buddy.
10. **Postcard book entries** + **Vivillon medal progress** — affected by Mateo gift exchanges; not per-Pokémon but per-account.
11. **Gimmighoul Coins** — account-level inventory, 999 needed for first Gholdengo.
12. **Zygarde Cells** — account-level inventory in Zygarde Cube, 50/200 thresholds.

## New collector criteria (do-not-cull triggers added since 2024)

- Has Gigantamax form (rare — only 16 species).
- Has investment in Max Moves (any Max Guard or Max Spirit unlocked = significant resource sunk).
- XXL + high IV (Showcase candidate, especially in type-based showcases post-Sept-2024 rebalance).
- Pokédex size/weight record-holder.
- Caught at L40+ (Mighty origin).
- Lucky.
- Caught from a region-locked Postcard origin you need for Vivillon medal.
- Galarian birds (regardless of IV — they're effort-locked behind DAI grind).

---

*End of file. Compiled 2026-05-27 from live web research. All dates verified against multiple sources where available.*
