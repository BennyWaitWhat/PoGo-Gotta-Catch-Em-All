# Existing Tools Survey: Bulk Transfer + Tagging in Pokemon GO (2026)

Research date: 2026-05-08. Read-only desk research. No phone modification performed.

User context: 5,413 pokemon, 858 to transfer, 5,413 to tag, complex multi-rule decision logic already computed. Already on phone: iPogo, Pokemod (rooted Pixel 9 Pro).

---

## TL;DR Recommendation

**There is no drop-in tool that does what you need end-to-end.** Specifically:

- No active 2024-2026 third-party tool exposes a programmable API for `ReleasePokemon` + `SetPokemonNickname` + `SetPokemonTag` driven by an external rule list. The classic API-based ecosystem (pgoapi, NecroBot, PokeManager, PokeInventory) is **dead** since 2019-2022 due to Niantic's anti-cheat overhaul.
- **Pokemod** (already installed) has **mass transfer**, **mass evolve**, **mass purify**, but its built-in filter is **limited to fixed protect-rules** (perfect IV / 0 IV / shiny / quest / raid / shadow / Zorua). It does **not** accept arbitrary external rule lists, and its **mass tag and mass rename functionality is not documented as features**.
- **iPogo** has only **on-catch auto-transfer** with fixed criteria (<90 IV, exact 0 IV, 0/15/15, shinies). No retroactive bulk operations on existing collection.
- The **closest existing tool in spirit** is `pogocleanup.com` - but it only **generates search strings** for the user to paste into the official app's search bar; the user still has to long-press, multi-select, and tap Tag / Transfer manually. No automation. Not a fit for 5,413 individually-decisioned pokemon.

**Closest path forward that reuses existing tooling:**

1. **Best (low-effort, low-risk):** Use the **official game's** built-in mass-select-and-tag UI. Long-press a pokemon, tap-select up to ~all visible matching ones, hit Tag. Combine with **pre-computed search strings per rule bucket** (similar to pogocleanup's output) to filter, select, and tag in 10-20 batches. This sidesteps anti-cheat entirely. Drawback: still ~10-20 tagging sessions of manual taps for 5,413 pokemon, and per-pokemon nicknames are still individual.
2. **Second-best (Pokemod-assisted):** Use Pokemod's **mass transfer** for the 858 transfers (matches its design), then drive **tagging via search-string + manual select** in the official client. This works but doesn't programmatically commit *your specific rule output*.
3. **Custom path (what you are already doing):** Frida-based protobuf injection to call `ReleasePokemonProto` + `SetPokemonTagsProto` + `NicknamePokemonProto` directly. **No mature open-source equivalent exists.** The PoGo bot scene has fully migrated to in-process overlays (Pokemod, iPogo, PolygonX) precisely because direct API calls are now lethal to accounts.

The wheel-reinvention you suspect is real, but the wheel doesn't exist for this use case. The closest analogs are dead.

---

## Per-Tool Feature Matrix

| Tool | Bulk Transfer | Mass Rename | Mass Tag | Filter Language | External Rule Input | Required Setup | Active 2024-2026 | Reliability |
|------|---------------|-------------|----------|-----------------|---------------------|----------------|------------------|-------------|
| **Pokemod** | Yes (mass transfer/evolve/purify) | Not documented | Not documented | Fixed protect-rules only | No | Rooted Android, Magisk | **Yes (active)** | High in community; ban-risk persists |
| **iPogo** | On-catch only (Auto Transfer; <90 IV / 0 IV / 0-15-15 / shiny / costume / shadow / Unown / Lake Trio) | No | No | Toggle checkboxes only | No | Android (rooted preferred) or iOS | **Yes (active)** | Medium; ban-risk |
| **PGSharp** | On-catch (Transfer on Catch with IV preset) | No | No | IV thresholds + species exclusion | No | Android (rooted version 1.247.6 exists) | **Yes (active)** | Hit by 2025-07-20 ban wave |
| **PGTools (PAC/PAG/PAS)** | On-catch via PAC | No | No | IV filters | No | Rooted Android only | **Yes (active)** | Hit by 2025-07-20 ban wave |
| **PolygonX** | Multiselect transfer (mass transfer legendaries/shinies via Polygon# multiselect module) | No | No | UI multiselect | No | Rooted Android | **Yes (active)** | Reported "advanced" but ban-risk persists |
| **PokeGo++ / PoGo++** | n/a | n/a | n/a | n/a | n/a | iOS (sideload) historically | **Dead** (Niantic v. distributor 2019) | Not viable |
| **POGO Cleanup** (`pogocleanup.com`) | **Search string generator** (no automation, manual select required) | No | Generates strings for user to apply manually | KEEP_LUCKY / KEEP_PVP / KEEP_RAID / KEEP_DEX / KEEP_XP / TRANSFER preset filters | No (hard-coded presets + premium granular) | Browser only | **Yes (active)** | Risk-free (no game integration) |
| **NecroBot2** | Yes (config-based) | Yes | n/a | YAML config | Yes (config) | Windows .NET; no mobile | **Dead since ~2019** | Not viable; bans guaranteed |
| **PokeInventory** (norecha) | Mass transfer duplicates / un-evolveables | IV-threshold rename | No | IV % threshold | Limited | Python via tejado pgoapi | **Dead** | Not viable |
| **PokeManager** (cglatot) | Mass transfer with IV/CP filters | No | No | IV/CP thresholds | Yes | Python via rubenvereecken/pokemongo-api | **Archived 2025-01-14** | Not viable |
| **PoGoTools** (nelsyeung) | Mass transfer / evolve | No | No | Config-based | Yes | Python via tejado pgoapi | **Dead (43 commits, no recent activity)** | Not viable |
| **MapADroid / RealDeviceMap** | Mapping/scanning, not inventory | No | No | n/a | n/a | Multi-device infra | **Active for mapping**; not inventory ops | n/a for transfer/tag |
| **Calcy IV / PokeGenie ADB renamers** (Azelphur etc.) | No | Yes (ADB tap automation, IV-stat naming) | No | Calcy IV output -> nickname template | Yes (script) | ADB + Calcy IV / PokeGenie overlay | Most "probably don't work anymore" per readmes; ADB tap approach itself is still possible | ADB tap is **non-API** so not detectable by Niantic, but slow and brittle to UI changes |
| **PokemonGo-CalcyIV-Renamer (Azelphur)** | No | Yes (per-pokemon ADB tap rename via Calcy) | No | Python config | Yes | ADB + Calcy IV | Stale; "probably doesn't work anymore" | Non-API approach is safer than protobuf injection but slow |
| **Ivy** (ownedcore) | No | Yes (batch IV-percentage nicknames) | No | Limited | No | Older tool | Stale (forum-distributed) | Unclear |
| **pgoapi (tejado / pogodevorg)** | Library only; no UI | API call exists | API call exists | n/a (caller's job) | Yes | Python | Last meaningful work ~2018 | Direct API calls = guaranteed ban |

---

## Detailed Notes

### iPogo (already on phone)

**Documented features** ([ipogo.app](https://ipogo.app/)):

- **Auto Transfer On Catch** (VIP feature): hard-coded criteria - transfer if <90 IV, exactly 0 IV, 0/15/15, shiny, costumed, shadow, Unown, Lake Trio.
- **One Click Item Deletion**: bag cleanup, not pokemon.
- **Shiny / 100 IV Filtering**: prevents auto-actions on rares.

**What iPogo does NOT have, per public documentation:**

- No bulk operations on existing collection (only on-catch).
- No mass rename.
- No mass tag.
- No filter grammar exposed to user (toggles only).
- No preview-before-commit step.
- No external rule input.

**On filter-grammar reverse engineering:** consistent with your prior finding that the bulk-grammar appears encrypted/runtime-only - no public docs from iPogo expose any user-facing filter language because **there isn't one for retroactive operations**, only on-catch toggles. You aren't missing a hidden feature; the feature doesn't exist.

### Pokemod (already on phone)

**Documented features** ([pokemod.dev](https://pokemod.dev/), discord.com/invite/pokemod):

- **"Easily mass transfer, evolve, and purify Pokémon"** - the headline mass-action feature.
- Auto-transfer on catch with hard-coded protections (perfect IV / 0 IV / shiny / quest / raid / shadow / Zorua).
- Shiny Scanner, Virtual Pokémon GO Plus, Perfect Throw, Animation Skipping, etc.
- Heal-all, instant gift open, instant raid attacks, auto-pinap.

**What Pokemod does NOT have, per public documentation:**

- **Mass rename**: not listed in any feature roundup found.
- **Mass tag**: not listed in any feature roundup found.
- External rule-list ingestion: no documented mechanism to feed a list of pokemon IDs with desired actions.
- The mass-transfer feature appears to be a UI-driven select/transfer accelerator, not a programmable batch processor.

**Conflicts with iPogo:** both modify the GO process. Running concurrently is generally not recommended; users typically pick one. (No primary source confirming a hard conflict, but the in-process injection model means two simultaneous patchers fight for the same hooks.)

**Ban risk:** Pokemod is regarded as one of the more conservative mods, but tools like Pokemod violate Niantic's TOS and ban risk persists. The 2025-07-20 mass ban wave primarily hit PGSharp and PGTools, sparing Pokemod, but rotation of detection focus is likely.

### PolygonX

Multiselect module supports mass-transferring legendaries/shinies (notable because the official client refuses these in mass-transfer flow). UI-driven, not programmable. Rooted Android only. ([pogospoofing.com 2025 review](https://pogospoofing.com/best-pokemon-go-spoofing-apps-2025-polygonx-pgtools-pokemod-pgsharp-ipogo/))

### POGO Cleanup (`pogocleanup.com`) - the closest in spirit

This is the most interesting find. It is **not an automation tool**; it is a **search-string generator**. Workflow:

1. User configures preset (Casual / PvP Focused / Raid Focused / Collector / Hardcore) and tweaks IV thresholds.
2. Tool emits ~7 search strings (KEEP_LUCKY, KEEP_MECH, KEEP_PVP, KEEP_RAID, KEEP_DEX, KEEP_XP, TRANSFER) using the official game's search grammar.
3. User opens Pokemon GO storage, pastes string, long-press to multi-select, applies tag.
4. Repeat for each KEEP_* string with its corresponding tag.
5. Use TRANSFER string to find the rest, multi-select, mass-transfer.

**Why this is conceptually closest to your problem:** it accepts complex rule input (preset + IV thresholds + league focus) and emits a sequence of operations the user (or some automation layer) can execute. The bulk semantics are pushed into the official game's own search grammar, so Niantic considers it legitimate gameplay - **no anti-cheat exposure**.

**Why it doesn't solve your problem alone:**

- It only emits 7 broad-category strings, not 858 individual transfer decisions and 5,413 individual tag assignments.
- The game's search grammar can't express "this specific instance ID" - only filters by IVs, type, move, age, etc. So per-instance decisions can't be batched via search strings; they require touching each pokemon (or one search-string-per-decision-bucket if your decisions cluster naturally).
- Still requires the human (or ADB tap layer) to long-press and multi-select.

**However:** if your computed rule output **clusters** into a small number of buckets (e.g. "everything with IV<60 AND not legendary" -> bucket A; "every great-league-relevant Bastiodon with IV>= 80" -> bucket B), then encoding each bucket as a search string and running a sequence of [paste search -> mass-select-visible -> mass-tag] passes could replace your Frida script.

### Bot frameworks (NecroBot, pgoapi, etc.) - all dead

The classic pre-2019 ecosystem (pgoapi/tejado, NecroBot, PokeManager, PoGoTools, PokeInventory, rubenvereecken/pokemongo-api) is **completely dead** for current Pokemon GO. Niantic's 2019+ anti-cheat work made direct protobuf API access lethal:

- pgoapi: last meaningful commits ~2018.
- NecroBot2: development stopped after legal action.
- PokeManager: archived 2025-01-14 with explicit "all unofficial APIs stand a risk of getting you banned".
- PokeInventory: 18 commits, stale.
- PoGoTools (nelsyeung): 43 commits, stale.

Reddit/community consensus: any tool that talks to Niantic servers via reverse-engineered protobufs gets the account banned within hours-to-days. The entire scene moved to **in-process injection** (Pokemod, iPogo, PolygonX) where the modded client still presents to Niantic as a regular client making regular calls in regular sequences.

This is a critical anti-cheat insight: **the reason you're using Frida + setenforce 0 to drive protobuf calls from outside the process is exactly the path Niantic detects most reliably.** Pokemod/iPogo bypass detection by running *inside* the GO process with the same network signature as a normal client. Whether your Frida approach inherits that camouflage depends on whether your hooks fire on the existing client's request path or synthesize fresh requests.

### Protobuf reference repos - mixed status

- **AeonLucid/POGOProtos**: archived 2022-01-28. Read-only.
- **Furtif/POGOProtos**: the recommended successor, semantic-versioned to current PoGo version. **Active as of 2025**. Public mirror.
- **Furtif/POGOProtos-Private**: active fork tracking the current game version (private/restricted, but referenced in Furtif's public repo).
- **Furtif/POGOProtos.Core**: archived 2019-06-07.
- **123FLO321/POGOProtos-Swift**: tracks Furtif.

For `ReleasePokemonProto`, `NicknamePokemonProto`, `SetPokemonTagsProto` (likely the actual proto names per game search grammar `#tag` syntax) - these are documented in the Furtif fork. Direct search for `AssignPokemonTagsProto` returned no results; the actual proto name will be discoverable in Furtif's repo under `Networking/Requests/Messages/`. The proto definitions are public; the **anti-cheat layer above them** is what kills reverse-engineered clients.

### Official game's bulk-tag UI on existing collection - confirmed exists

Per Niantic and Pokemon Hub:

- Long-press any pokemon -> enters multi-select mode.
- Tap additional pokemon to select.
- Tag button appears in mass-select toolbar.
- Apply tag to all selected.
- Max tags per trainer: 100.
- **No documented per-tag pokemon limit** (collection cap is 7,300 max, and pokemon can have multiple tags).
- Search-string syntax for filtering before mass-select: `&` AND, `,` `:` `;` OR, `!` NOT, `#tagname` for tag membership, range `cp200-300`, etc.

So the path "search-string-filter -> long-press -> mass-select-visible -> tag" **is officially supported by the game** and has zero anti-cheat exposure.

### ADB tap automation (Calcy IV / PokeGenie renamers)

The Azelphur PokemonGo-CalcyIV-Renamer family of tools uses the **non-API** approach: ADB injects fake taps to drive the regular game UI through Calcy IV's overlay output. This is slow, brittle to UI updates, and most variants are stale, but the **approach itself is fundamentally safer** than API-level protobuf injection because it produces no anomalous network traffic - everything looks like a human tapping.

Quoting the (stale) Azelphur readme: *"These scripts don't login to the pokémon go servers using the unofficial API and only rely on an Android phone, meaning you're very unlikely to get banned for using them. However, the downside is that it's a lot slower, and that you can't use your phone while it's running."*

This is relevant for your use case because **if you can express your tag/transfer plan as a sequence of taps**, ADB tap automation is the most ban-safe path. It would be slow (5,413 pokemon * ~3 seconds per tap-and-confirm = 4-5 hours real time), but would not require Frida or setenforce or any in-process hooks.

### What about renaming?

This is the gap nobody fills. No mainstream 2024-2026 mod (Pokemod, iPogo, PGSharp, PolygonX, PGTools) advertises mass rename. The renamer scene died with the API-based bots. Current options are:

1. **ADB tap automation** (Calcy IV / PokeGenie renamer family) - non-API, slow, ban-safe.
2. **Frida injection of `NicknamePokemonProto`** - what you've been doing - fast, programmable, anti-cheat exposed.
3. **Manual** - 5,413 pokemon * ~5 seconds per rename = unacceptable.

The fact that **no one has shipped a mass-rename overlay** is informative: either it's harder to build than expected (likely - the rename UI requires a soft-keyboard interaction for each pokemon that's awkward to overlay), or the demand is low (most users tag by IV-checker output via Calcy IV's nickname-overlay rather than persistent renames), or the ban-risk-vs-value tradeoff has settled against it.

---

## Reliability Data (Bans 2024-2026)

- **2025-07-20 ban wave**: targeted PGSharp and PGTools heavily. Thousands of accounts hit with 7-day strikes, 30-day suspensions, or permanent bans. Primary trigger appears to be 24/7 farming patterns; recommendations to keep automated farming under 4-6 hours/day. ([pogospoofing.com](https://pogospoofing.com/avoid-bans-spoofing-pokemon-go/))
- **2025-11-late ban wave**: hit Japan/Korea, broader profile - even players using IV-scanning apps and innocent players got swept. Indicates Niantic's anti-cheat now uses behavioral AI and cross-signal corroboration (device hardware, sensors, network context all checked).
- **Pokemod**: regarded as relatively conservative; not specifically named in 2025 ban waves, but no mod is ban-proof. Ban-risk literature recommends Pokemod be used on alt accounts.
- **iPogo**: documented soft-ban and shadow-ban incidents; an appeal pathway exists ([ipogo.app/appeal.php](https://ipogo.app/appeal.php)) but main-account use is risky.
- **3-strike system**: Strike 1 = 7-day warning (limited spawns/no raids); Strike 2 = 30-day suspension; Strike 3 = permanent termination.

For your specific operation - **a one-shot batch of 858 transfers + 5,413 tags + nicknames** - this is a single behavioral spike, not 24/7 farming. Behavioral-AI detection more likely flags sustained anomalous patterns than a single bulk session. But injection-based approaches (Frida, in-process mods) all carry non-zero ban-risk.

---

## Final Recommendation

**Don't keep building the Frida path.** The reason no mature open-source equivalent exists isn't that nobody thought of it; it's that the entire pre-2019 generation that built it got banned, and the post-2019 scene deliberately abandoned external API injection because Niantic's anti-cheat catches it. You are reinventing a wheel that was deliberately scrapped.

**Recommended path, in order of preference:**

1. **Cluster your computed rules into search-string buckets**, then drive the official-client `search -> long-press -> multi-select-visible -> tag/transfer` flow via **ADB tap automation**. This:
   - Uses the game's own legitimate search grammar (zero anti-cheat exposure).
   - Uses the game's own legitimate mass-select UI (zero anti-cheat exposure).
   - Reduces 5,413 individual decisions to ~N tag-bucket passes + 1 transfer pass.
   - Replaces Frida + setenforce with adb shell input tap, which is robust, well-understood, and kernel-safe.
   - Cost: time. Each pass is a 30-second-to-2-minute UI ballet, and you'll want 10-30 passes depending on bucket count.
   - **POGO Cleanup** isn't a drop-in but is the right architectural model: emit search strings from a rule engine, then execute taps.

2. **If your rules don't cluster cleanly**: split the work. Use search-string buckets for the "easy" 80% (the obvious junk transfers, the obvious shiny/legendary tags). Use Frida only for the residual 20% where per-instance decisions can't be expressed as a search string. This shrinks your anti-cheat exposure window from 5,413 operations to ~1,000.

3. **If you must stay all-Frida**: `Furtif/POGOProtos` is your reference for current proto names. Throttle aggressively (reproduce human cadence: 1-3 seconds between operations, not 50ms loops). Avoid running during active raid/catch sessions. Run on alt account if the main account has any value.

**No drop-in tool obviates the work.** But the most-of-the-work could be replaced by: (a) a search-string emitter that translates your rule list into game-native search grammar and (b) an ADB tap driver that automates long-press + multi-select + tag/transfer for each emitted string. Neither component exists open-source as a polished package, but both are fundamentally simpler and safer to build than Frida-based protobuf injection.

---

## Sources

- [iPogo official site](https://ipogo.app/)
- [iPogo appeal page](https://ipogo.app/appeal.php)
- [Pokemod official](https://pokemod.dev/)
- [Pokemod Discord](https://discord.com/invite/pokemod)
- [Pokemod review (pokeep.com)](https://www.pokeep.com/pokemon-go/pokemon-go.html)
- [POGO Cleanup](https://pogocleanup.com/)
- [PGSharp features](https://www.pgsharp.com/features/)
- [PGTools](https://pgtools.net/)
- [2025 mods comparison (pogospoofing)](https://pogospoofing.com/best-pokemon-go-spoofing-apps-2025-polygonx-pgtools-pokemod-pgsharp-ipogo/)
- [Niantic search syntax](https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/1486-searching-filtering-your-pokemon-inventory/)
- [Niantic tagging guide](https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/2800-tagging-your-pokemon-inventory/)
- [Niantic transfer guide](https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/2389-transferring-pokemon/)
- [POGOProtos (archived)](https://github.com/AeonLucid/POGOProtos)
- [Furtif/POGOProtos (active fork)](https://github.com/Furtif/POGOProtos)
- [PokeInventory (stale)](https://github.com/norecha/PokeInventory)
- [PokeManager (archived 2025)](https://github.com/cglatot/PokeManager)
- [PoGoTools (stale)](https://github.com/nelsyeung/PoGoTools)
- [Azelphur Calcy IV Renamer](https://github.com/Azelphur/PokemonGo-CalcyIV-Renamer)
- [Awesome PokemonGO (mostly archived)](https://github.com/pogodevorg/awesome-pokemongo)
- [Mass-transfer search-query gist](https://gist.github.com/Jaid/8d53746f389277a1020301290c794a04)
- [Pokemon GO Hub tags guide](https://pokemongohub.net/post/tips-and-tricks/go-hub-guide-to-tags-and-organisation/)
- [Niantic anti-cheat 2025](https://pogospoofing.com/pokemon-go-spoofing-detection/)
- [Ban wave 2025-07](https://pogospoofing.com/avoid-bans-spoofing-pokemon-go/)
- [Niantic gameplay enforcement update](https://nianticlabs.com/news/gameplay-policy-enforcement-update?hl=en)
