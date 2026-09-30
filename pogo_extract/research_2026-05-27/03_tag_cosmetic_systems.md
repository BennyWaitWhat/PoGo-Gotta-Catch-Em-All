# Pokemon GO Cosmetic / Display / Collector Attributes
**Research date:** 2026-05-27
**Scope:** the proto display fields parsed by `pogo_pipeline.py` (postcards, costumes, badges, sizes, adventure-effect uses, mega levels, breadmode/strong markers).

The aim is to give every field a player-facing source-of-truth so the tag/cull rules can be audited. Citations inline.

---

## TL;DR for the decoder

| Decoder field | Display offset | Real player-facing meaning | Confidence |
|---|---|---|---|
| `costume_decoration_id` | +0x10 | Costume / event-skin variant of the species (e.g. Party-Hat Pikachu). Single integer enum; many gaps. | High |
| `is_shiny` | +0x18 | Star-marked shiny. | High |
| `form` | +0x1c | Form value (Alola / Galar / Hisuian / Therian / region). | High |
| `alignment` | +0x24 | 0=Normal, 1=Shadow (Rocket), 2=Purified. | High |
| `fresh_pokemon_badge` | +0x28 | "Star ribbon" badge enum — the icon at the top-left of the Pokemon info card. Values include Best Buddy / 3-Star-Best-Buddy / Lucky / 3-Star-Lucky / Hundo / Shiny-Lucky etc. See §3. | Medium (enum order inferred) |
| `fresh_current_temp_evolution` | +0x2c | Currently Mega-Evolved form id; 0 if not currently mega. | High |
| `fresh_has_mega_level` | derived from +0x50 ptr | True iff the Pokemon has been Mega-Evolved at least once (Mega Level >= Base/1). The actual mega-level proto submessage is at this offset. | High |
| `fresh_has_location_card` | derived from +0x58 ptr | True iff the Pokemon has a Background ("Location Card" / "Special Background" / "GO Snapshot"). The proto submessage holds the background-id string. | High |
| `fresh_bread_mode` | +0x60 | "Bread" is Niantic's internal codename for Dynamax/Gigantamax. This is the **Dynamax-active state** marker (Pokemon is currently Dynamaxed). Distinct from "is this a Dynamax-capable specimen". | High |
| `fresh_is_strong` | +0x64 | "Strong Pokemon" — the **XXL-Strong / XXS-Strong** mark used for Pokestop Showcases (NOT the league/PvP "Strong" rating). True when the specimen's height/weight scaled value sits in the strong tier. | Medium |
| `adventure_effects_left` | (separate) | Charges remaining on a Pokemon's signature Adventure Effect (Roar of Time, Behemoth Blade, Dynamax Cannon, etc). Capped per species at the initial charge count (commonly 5); does not auto-recharge — refilled by re-catching the species or via event task rewards. | Medium |
| `pokemon_size_category` | (separate) | 1=XXS, 2=XS, 3=Normal (M), 4=XL, 5=XXL. | High |

---

## 1. Backgrounds — postcards, location cards, special backgrounds

### What it actually is
A "Background" is a souvenir image displayed on the Pokemon summary page. By default every Pokemon shows an animated **Type Background** for its primary type; this is overridden to gold if Lucky, to dark blue if Shadow. On top of that, certain catches can carry an additional **Location Background** or **Special Background**, which is what shows up as a "fancy postcard art" behind the Pokemon's portrait and is what `+0x58` / `fresh_has_location_card` corresponds to.

### Sources of a background
| Type | Trigger | Cite |
|---|---|---|
| **Type** | Default for every Pokemon, based on primary type. Not stored in the proto field. | Bulbapedia Background (GO) |
| **Lucky override** | Gold overlay applied automatically to any Lucky Pokemon. | Bulbapedia Background (GO) |
| **Shadow override** | Dark blue overlay applied automatically to any Shadow Pokemon. | Bulbapedia Background (GO) |
| **Location Background** | Caught at an in-person event (Pokemon GO Tour Hoenn LV — Feb 2023 onwards). First feature debut. First catch of each featured species at in-person events is guaranteed. | pokemongo.com `location-card-new-feature`; pokemongohub.net |
| **Special Background** | Catching certain Pokemon during certain global events (Ultra Beasts July 2024 was the debut; ongoing since GO Fest 2024 Global). Chance-based, not guaranteed. Trades involving a Pokemon with a Special Background count as Special Trades. | pokemongo.com `special-backgrounds` (June 2024) |
| **Evolution-acquired** | Some backgrounds can only be obtained by evolving certain Pokemon. | Bulbapedia |

### Postcards vs Backgrounds (important distinction)
"Postcards" (Postcard Book, Dec 2021) are the **gift-attached** postcards stored in the player's Postcard Book — used for the Vivillon collection medal. **They are not stored on the Pokemon itself**. The Pokemon's `+0x58` background pointer is *only* the Location/Special Background. Do not conflate.

Cite: niantic.helpshift.com/.../3196-what-is-the-postcard-book; pokemongo.com `postcardbook`.

### Stability
The Backgrounds list is **fast-growing** (every in-person event, GO Fest, Air Adventures, Mega Festa Seoul, MLB partnership, Pokelid Stamp Rally, City Safari adds entries). Background IDs are strings ("hoenn_tour_las_vegas_2023", "go_fest_paris_2025", etc); fan databases keep up via serebii.net/pokemongo/backgrounds.shtml. Treat `fresh_has_location_card` as boolean only; the per-event string is too churn-prone for fixed parsing rules.

---

## 2. Costumes — and what "Bread Mode" really is

### Costume system
Costumes are species variants applied to a base species + form (e.g. Pikachu species 25, form NORMAL, costume DAWN_HAT). They are granted via event encounters (raids, field research, wild spawns during the event), occasional re-issue events (Fashion Raid Day, see below), or Pokemon GO Tour passes. There is no in-app way to add or remove a costume after the catch — it is fixed at spawn time.

Decoder field: `costume_decoration_id` (display +0x10, single int). Enum lives in `PokemonDisplayProto.Costume` in PokeMiners game-master files. Notable entries 2024-2026:

- **2024:** Cap's Hat Pikachu (Horizons), Sun-Crown Pikachu + Moon-Crown Eevee (GO Fest Sendai), Ph.D. Pikachu (World of Wonders), Dawn Hat / Lucas Hat / Akari Kerchief / Rei Cap Pikachu (Tour Sinnoh LA), Flying Red & Batik Shirt Pikachu (Bali), Saree Pikachu, ribboned Jigglypuff (New Years 2024).
- **2025:** Fashion Week Minccino + Cinccino; Halloween 2025 Part II (11 costumed species, 8 obtainable in-game); GO Fest 2025 Falinks costume.
- **2026:** Fashion Raid Day 4 Apr 2026 brought returning costumes (Butterfree, Diglett, Dragonite, Wooper, Sneasel, Kirlia, Absol, Shinx, Croagunk, Blitzle, Minccino).

There is no centralized public ID-to-name map maintained continuously; the closest authoritative mapping is the PokeMiners game-master text files (`pokeminers.com/gmexplore`). The Pokemon GO Fandom Wiki's "Event Pokemon" page and Serebii's per-species pages list the human-readable costumes per event with rough ordering.

Cites: pokemon.com/us/pokemon-news (Halloween 2025), thephrasemaker.com Fashion Raid Day; thegamer.com Fashion Week 2025 (Minccino); pokemongohub.net Halloween 2025; bulbapedia Event Pokemon (GO).

### "Bread Mode" — confirmed: this is Dynamax-active state

`fresh_bread_mode` (display +0x60) is **NOT a costume**. "Bread" is Niantic's internal codename for **Dynamax** (and "BreadDough" for Gigantamax) confirmed across multiple datamines:

> "Dynamaxing and Gigantamaxing appear to be called 'Bread' in the game code … New map object 'Bread Station' = Dynamax Den, 'Bread MP' crystal in shop, Max Moves prefixed 'BM' (Bread Move)." — pokemongohub.net/post/news/dynamax-assets-discovered

> "Asset added 'bread retreat eternamax'" — Pokemod Group datamine July 2025

Player-facing: Dynamax/Max Battles launched **Sep 4, 2024** with the GO Big event. Dynamax-capable Pokemon are caught at Power Spots; they have a Max Move tree (level-up via Max Particles + Candy). When the player **activates Dynamax** during a Max Battle, the specimen enters its "bread mode" briefly — large form, gains Max Moves. The decoder boolean is true for **the specimen being a Dynamax Pokemon** (i.e. one that can Dynamax / has the Dynamax bit set on its display). Some bots/decoders distinguish "is Dynamax-capable" from "is currently dynamaxed in battle"; the proto field on the long-term player inventory record is the former.

Auditing recommendation: tag a Pokemon as "Dynamax" when `fresh_bread_mode` is true, treat it as a **keeper for Max Battle attackers**.

Cites: pokemongohub.net/post/news/dynamax-assets-discovered (codename), dexerto.com `pokemon-go-datamine-reveals-surprising-bread-event-coming-soon` (Aug 2022 first leak), pokemongohub.net/post/news/eternatus-brings-the-dynamax-cannon-adventure-effect (Eternatus uses Dynamax Cannon directly tied to bread mechanic).

---

## 3. Pokemon Badges — what `fresh_pokemon_badge` is

This is **per-Pokemon** decorative badges (the star/ribbon icon at the top of the Pokemon's info card), not trainer medals.

| Badge | Earn condition | Notes |
|---|---|---|
| **(none)** | Default | 0 |
| **Best Buddy** | 300 Affection Hearts with Pokemon set as Buddy (Good=1, Great=70, Ultra=150, Best=300). Permanent. | Has been live since 2019. |
| **Lucky** | Pokemon obtained via trade where the trade rolled Lucky (rate ~5% normally, guaranteed with Lucky Friends). | Yellow sparkly background overrides type background; the badge enum entry is separate. |
| **Lucky-Friend trade Lucky** | Same icon as Lucky, but reached via Lucky-Friend status (Best Friends rolling ~1.1% per first-interaction-of-day). Cleared after the trade. | dexerto.com / dotesports.com |
| **Hundo (3-star)** | 15/15/15 IV. Shown by red 3-star rating on appraisal. Not visually a "badge" in the same column — surfaced as the IV-bar/star icon. | pogoskill.com / dittobase.com |
| **Shiny** | A Shiny Pokemon: separate proto bool (`is_shiny`, +0x18), not in this enum. | — |

There is **no canonical public mapping** of `fresh_pokemon_badge` integer → meaning. The protobuf enum has been observed (PokeMiners game-master + purified-protos) to use values in a small set; the consistent pattern across community decoders is:

```
0 = NONE
1 = BEST_BUDDY
2 = (reserved / Lucky?)
```

Higher values are added with each new badge type and tend to be appended. We did **not find an authoritative published mapping** for the 3-Star Best Buddy or any "3-Star Lucky" variant; those appear to be **graphical overlays driven by other state** (Mega Level Max + Best Buddy etc), not a separate badge index. **Recommendation:** treat `fresh_pokemon_badge>0` as "has at least one cosmetic badge" and audit the value-frequency table from the user's own Pokemon storage to pin down the exact enum once collected.

Cites: niantic.helpshift.com/.../2155-buddy-adventure; pokemongohub.net buddy guide; gosunoob.com / dotesports.com / dexerto.com on Lucky / Lucky Friend.

### Trade badge / Apex / Lucky-Friend
There is **no separate "from-trade" cosmetic badge** distinct from Lucky in the Pokemon-display proto. Trade origin is tracked elsewhere (`origin`, `trader_id`) in the captured Pokemon proto, not in display. Apex (Ho-Oh, Lugia, Mewtwo from Pokemon GO Tour Johto/Kanto/Sinnoh in 2022/2023) **does** carry a distinguishing form/costume id but appears via `form`/`costume_decoration_id`, not via the badge enum.

### Adventure Effects badge?
The "uses-remaining" indicator is shown on the Pokemon as a charge counter, but is **not** the badge enum value; it is `adventure_effects_left` (see §5).

---

## 4. Size category & the "Strong" marker

### Categories
Five tiers: **XXS, XS, M (Normal), XL, XXL**. All species can roll all sizes since Jan 17 2023. Classification is based on the scaled height/weight roll against species baseline. ~1 in 20 catches is XXS or XXL. (pokemongohub.net `xxs-and-xxl-pokemon`; serebii.net/pokemongo/size; pokemongo.fandom.com Weight_and_Height.)

### The Pokedex per-species "size record" (largest/smallest/heaviest/lightest)
After catching ≥3 of any species, the Pokedex displays your **records** for largest / smallest / heaviest / lightest specimen. A celebratory message ("HUGE" / "tiny") fires when a record breaks. This is the player-facing flag tied to size.

### "Strong" — confirmed: the size-Showcase mark, not PvP
The internal "is_strong" flag (decoder field `fresh_is_strong`) corresponds to the **XXL-Strong (or XXS-Strong) mark used for Pokestop Showcases**. Showcase Score formula is published by pokemongohub.net:

```
score = scaled_height * 800 + scaled_weight * 150 + scaled_IVs * 50
(+178 if XXL)
```

A specimen earning a Strong mark in Showcases sits at top-tier height+weight, comfortably above the M boundary. The flag is set at catch time and persists.

This is **not** the PvP/league "Strong" used to denote a battle-ready Pokemon in PvP tier lists — that has no proto representation. Audit `fresh_is_strong=True` as "the specimen has the in-game Showcase Strong indicator (XXL-Strong)".

Cites: pokemongohub.net `showcase-scores-xxs-and-xxl-pokemon-and-how-it-works`; sunnyweb.org Definitive Guide to XXS and XXL Pokemon.

---

## 5. Adventure Effects — exhaustive species roster (as of May 2026)

Adventure Effects are signature Charged Attacks usable **outside battle** for stardust + candy cost, granting timed buffs. Introduced at Pokemon GO Tour: Sinnoh (Feb 2024).

### Mechanic
- Activation cost: stardust + species candy (per row below).
- Per-activation duration: 6 or 10 minutes (per row).
- Extension: tap "Use again" stacks more duration in 2-hour increments to a **max stored 24 hours**.
- Only **one** Adventure Effect active at a time, **except Dynamax Cannon**, which is allowed simultaneously.
- "Uses remaining" counter: the activations stored on the Pokemon. The Pokemon must "have" Adventure Effect uses to activate. Charges come pre-attached when caught from the debut event; refilled by re-catching or by event-pass tasks (Tour Pass rank-up etc.).
- There is **no published global cap and no auto-recharge timer**; the decoder field is the charges-left integer.

### Authoritative roster (as of 2026-05)

| # | Species | Form | Move | Effect | Cost | Base Dur | First avail |
|---|---|---|---|---|---|---|---|
| 483 | **Dialga** | **Origin Forme** | Roar of Time | Pauses Incense / Daily Adventure Incense / Lucky Egg / Star Piece timers. | 5,000 dust + 5 Dialga candy | 6 min | Tour Sinnoh Feb 2024 |
| 484 | **Palkia** | **Origin Forme** | Spacial Rend | Increases spawn radius for wild Pokemon. | 5,000 dust + 5 Palkia candy | 10 min | Tour Sinnoh Feb 2024 |
| 800 | **Necrozma** | Dusk Mane (fused w/ Solgaleo) | Sunsteel Strike | Simulates daytime: attracts daytime spawns + lets day-only evolutions evolve. | 3,000 dust + 3 Necrozma candy | 10 min | Necrozma Fusion Raid Day 2024 |
| 800 | **Necrozma** | Dawn Wings (fused w/ Lunala) | Moongeist Beam | Simulates nighttime: attracts nighttime spawns + lets night-only evolutions evolve. | 3,000 dust + 3 Necrozma candy | 10 min | Necrozma Fusion Raid Day 2024 |
| 646 | **Kyurem** | **Black** (fused w/ Zekrom) | Freeze Shock | Catch-rate buff: encountered Pokemon are immobile / easier to catch (+25% catch rate). | 5,000 dust + 5 Kyurem candy | 10 min | Tour Unova 2025 |
| 646 | **Kyurem** | **White** (fused w/ Reshiram) | Ice Burn | Slows target ring movement (+50% catch rate; easier excellent throws). | 5,000 dust + 5 Kyurem candy | 10 min | Tour Unova 2025 |
| 888 | **Zacian** | Crowned Sword | Behemoth Blade | +10% attack damage in Raid Battles, +5% in Max Battles. | 5,000 dust + 5 Zacian candy | 6 min | GO Fest 2025 Global (June 28-29) |
| 889 | **Zamazenta** | Crowned Shield | Behemoth Bash | +10% defense in Raid Battles, +5% in Max Battles. | 5,000 dust + 5 Zamazenta candy | 6 min | GO Fest 2025 Global |
| 890 | **Eternatus** | Base | Dynamax Cannon | Boosts Max Move level by +1 in Max Battles (Lvl 3 → Lvl 4 possible). Stackable with other Adventure Effects. | 5,000 dust + 30 Eternatus candy | 10 min | GO Fest 2025: Max Finale (Aug 23-24, 2025); preceded by Dark Skies event Aug 18-23 |

### Filling gaps from the audit
The project reference set "currently misses Origin Dialga (483), Origin Palkia (484), Kyurem (646), Eternatus (890)" — **all four are confirmed Adventure-Effect species** (cited above). They should be added.

The other AE species the project should also confirm are in:
- **Necrozma Dusk Mane / Dawn Wings (#800 with form discriminator)**
- **Crowned Sword Zacian (#888 crowned form)**
- **Crowned Shield Zamazenta (#889 crowned form)**

No other species had an Adventure Effect as of 2026-05 (no AE has been announced for any Gen 9 starter, Calyrex, Koraidon/Miraidon, etc. through May 2026 release schedule).

Cites: pokemongo.com `news/adventure-effect-eternatus`, `post/fusion-adventure-effects-kyurem`, `post/fusion-adventure-effects-necrozma`, `post/adventure-effects-crowned-zacian-zamazenta`; serebii.net/pokemongo/adventureeffect.shtml; dexerto.com `pokemon-go-what-adventure-effects-are-how-to-use-them-2469718`; dittobase.com.

---

## 6. Mega Evolution — Mega Levels in detail

Released April 2022; Super Max added during **Pokemon GO Tour: Kalos** (announced 2026, "mega-evolution-2026-update").

### Levels and thresholds

| Level | Evolutions to reach | Mega Energy cost (free) | Rest cooldown | Bonuses |
|---|---|---|---|---|
| No level / first evolve | 0 | 200 | 14 days | 1.1x atk; 1.3x same-type |
| **Base (Lvl 1)** | 1 (the first one) | 41 | **7 days** | 1.1x atk; 1.3x same-type |
| **High (Lvl 2)** | 7 (i.e. 6 more after Base) | 21 | **5 days** | +50 catch XP; +10% Candy XL chance for same-type catches |
| **Max (Lvl 3)** | 30 | 11 | **3 days** | +100 catch XP; +25% Candy XL chance for same-type catches; +2 candy per catch |
| **Super Max** (2026) | 30 + further Mega Energy power-ups (no fixed evo count; **uses Mega Energy at Max**) | — | **24 hours** | Greatly enhanced CP; greatly increased catch candy, catch XP, Candy XL chance for same-type |

`fresh_has_mega_level` (the boolean derived from display +0x50 pointer being non-null) becomes True the moment the specimen mega-evolves for the first time. The submessage at +0x50 holds `mega_level` (1/2/3/4) plus per-level evolution counts.

Cites: serebii.net/pokemongo/megaevolution.shtml; pokemongo.com `news/mega-evolution-2026-update`; pokemongohub.net `new-and-improved-complete-guide-to-the-updated-mega-evolution-system`; attackofthefanboy.com `pokemon-go-mega-levels-explained`.

### Per-individual, not per-species
"The Level is specific to each Pokemon, not each species, so when one Charizard reaches Max Level, the others will still be different." (serebii.net) — meaning `fresh_current_temp_evolution` shows which mega is active *now* (0 if not currently mega), and the mega-level submessage attaches to the individual specimen.

### Super Mega Raids and Link Charges (2026 system)
Super Max requires Mega Energy from **Super Mega Raids** (7+ trainers, shielded boss, "Link Charge" item required to enter all Mega Raids). The Adventure-Effect attack-boosts (Behemoth Blade, Behemoth Bash) explicitly call out Super Max compatibility.

Cite: pokemongo.com `news/mega-evolution-2026-update`.

---

## 7. New badges 2024-2026 the decoder might miss

These are categories whose data points the decoder *may* encounter:

- **Special Background trade flag**: Pokemon with Special Background count as Special Trade. Not a new badge but a side-effect on trade limits.
- **Best Buddy** unchanged through 2026; no public confirmation of 3-Star Best Buddy as a real game state — community references to "3-star" appear to conflate Mega Level Max + Best Buddy or a Showcase 3-place finish.
- **Lucky-Friend lucky trade**: in 2025 Niantic added "Lucky Friend transitions can drop Lucky Pokemon outside trades" reports — confirmed by techtimes.com Nov 2025 article re: Friendship System changes — but this still produces a normal Lucky badge value, not a separate enum.
- **Pokedex 3-star (Hundo) ribbon**: existed since 2018; no enum change.

No known new badge enum entry in 2024-2026 that the decoder would need beyond the existing Best Buddy / Lucky / Lucky-Friend / Hundo set. Treat any unknown `fresh_pokemon_badge` value as "future / unknown — keep" rather than culling.

Cite: techtimes.com `secrets-pokemon-go-friendship-system-2025`.

---

## 8. Costume `decoration_id` mapping

There is **no actively-maintained public Pokemon-GO-API mapping** of costume_decoration_id → human costume name. The authoritative source is the PokeMiners game-master files, where the `PokemonDisplayProto.Costume` enum lives. As of May 2026:

- The enum is updated each time a new costume drops (typically twice a month in event-heavy stretches).
- Values are appended; old IDs are not reused.
- Latest known additions (Apr-May 2026): Fashion Raid Day re-releases (Butterfree, Diglett, Dragonite, Wooper, Sneasel, Kirlia, Absol, Shinx, Croagunk, Blitzle, Minccino).
- Roughly 250-300 active costume IDs exist as of May 2026.

**Practical recommendation:** snapshot the current `PokemonDisplayProto.Costume` enum from PokeMiners `game_masters` repo and store the int→name table as a project resource updated quarterly. Treat unknown IDs as "novel costume, do not cull".

Cite: github.com/PokeMiners/game_masters; pokeminers.com/gmexplore; serebii.net/pokemongo/pokemon/025.shtml (per-species costume listings); Style & Customisation serebii.net/pokemongo/style.shtml.

---

## Key references

- pokemongo.com (Niantic news): location-card-new-feature; special-backgrounds; postcardbook; news/adventure-effect-eternatus; news/mega-evolution-2026-update; news/fusion-adventure-effects-kyurem; post/fusion-adventure-effects-necrozma; post/adventure-effects-crowned-zacian-zamazenta; max-pokemon-battle
- niantic.helpshift.com: 3196-what-is-the-postcard-book; 2155-buddy-adventure; 3331-how-can-i-increase-a-pokemon-s-mega-level; 4386-what-are-adventure-effects; 1485-lucky-friends
- serebii.net/pokemongo: backgrounds.shtml; adventureeffect.shtml; megaevolution.shtml; size.shtml; maxbattles.shtml
- bulbapedia.bulbagarden.net: Background_(GO); Event_Pokemon_(GO); Dynamax_(GO)
- pokemongohub.net: dynamax-assets-discovered; complete-mega-evolution-guide; full-list-of-adventure-effects-in-pokemon-go; xxs-and-xxl-pokemon-in-pokemon-go; showcase-scores-xxs-and-xxl-pokemon-and-how-it-works; eternatus-brings-the-dynamax-cannon-adventure-effect
- pokemongo.fandom.com: Backgrounds; Adventure_Effects; Buddy_Pokemon; Mega_Evolution; Postcard_Book; Weight_and_Height; List_of_Dynamax_Pokemon
- leekduck.com/posts/mega-evolution-update-super-mega-raids-super-max
- dexerto.com: pokemon-go-datamine-reveals-surprising-bread-event-coming-soon; pokemon-go-dynamax-max-battles-explained; pokemon-go-what-adventure-effects-are-how-to-use-them
- github.com/PokeMiners/game_masters; pokeminers.com/gmexplore
- pokeminers.com/sitereports/mega-levels-free-mega-mega-evolve-in-l (April 6 2022)
- thephrasemaker.com (Halloween 2025; Fashion Raid Day 2026)
- pocketmonsters.net (Fashion Raid Day 2026)
- techtimes.com `secrets-pokemon-go-friendship-system-2025` (Nov 2025 Lucky Friend change)
