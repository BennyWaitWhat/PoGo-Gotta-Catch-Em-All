# INVENTORY subsystem recon (items / MEGA ENERGY / raid passes / candy)

Static analysis only. Goal: read PoGo's live inventory (item_id -> count, per-species mega
energy, candy/XL, raid passes, currencies). Draft reader: `pogo_extract/read_inventory.py`.

## TL;DR for the lead
- The whole inventory lives in **one Dictionary** reachable from `InventoryCache.GetCurrentItems()`.
  Each entry is `key=HoloInventoryKeyProto`, `value=ClientInventoryItem` wrapping a
  `HoloInventoryItemProto`. Both protos are **oneofs**; the discriminator (TypeCase) sits at
  `+0x18` (raw int), the payload object at `+0x10`.
- **Per-item counts** (balls, berries, passes, rare candy): key TypeCase==2 -> `value.get_Item`
  -> `ItemProto{ Item@+0x10, Count@+0x14 }`. **CONFIRMED live** (item 1150 -> count 2731).
- **Candy + XL candy + MEGA ENERGY are all per-family**: key TypeCase==10 -> `value.get_PokemonFamily`
  -> `PokemonFamilyProto{ FamilyId@+0x10, Candy@+0x14, MegaEvolutionResources(RepeatedField)@+0x18,
  XlCandy@+0x20 }`. Candy/XL **CONFIRMED live** (e.g. fam 624 candy=2338 xl=419).
- **MEGA ENERGY is NOT an item id and has NO getter.** It is the repeated
  `TemporaryEvolutionResourceProto` list at `PokemonFamilyProto+0x18`. The per-element energy
  field offset is the **one unknown** -> the draft dumps raw bytes + reflected fields so you can
  lock it in one run.
- **Raid passes**: Remote/Premium raid passes are ordinary **item ids** (TypeCase==2). There is
  ALSO a separate `RaidTickets` oneof case (`RaidTicketsProto`) for event raid tickets.
- **Stardust / PokeCoins** are NOT in this dict -> read via `IapService.get_Stardusts()` /
  `get_Coins()` / `get_PurchasedCoins()`. (`get_Stardusts` confirmed working in prior session.)

## How to read it (recipe)
1. `inv = pg.find_singleton(sess, 'Niantic.Holoholo.Collections', 'InventoryCache')`
2. `dict = InventoryCache.GetCurrentItems()` then `coll+0x10` = the backing Dictionary.
3. Walk the Dictionary (standard IL2CPP `Dictionary<TKey ref, TValue ref>`):
   `entries = dict+0x18`; `count = entries+0x18` (managed-array length); stride `0x18`;
   entry = `{int hash; int next; ref key@+0x8; ref value@+0x10}`; skip `hash<0`.
4. Per entry read `case = key+0x18` (int):
   - `case==2`  -> item:  `key.get_Item`(boxed int id) + `value.get_Item`->ItemProto.Count@+0x14
   - `case==10` -> family: `key.get_PokemonFamilyId`(boxed int) + `value.get_PokemonFamily`
                   ->candy@+0x14 / xl@+0x20 / megaEnergy list@+0x18
   - other cases (RaidTickets / EggIncubators / EventPasses ...) -> dump raw value bytes to decode.
5. Currencies: `IapService` singleton -> `get_Stardusts/get_Coins/get_PurchasedCoins` (unbox @+0x10).

The draft does all of this in one attach / one walk and also tries the cleaner **method path**
(`ItemBagImpl.GetItemCount` / `GetCandyCountForPokemonFamily` / `GetXlCandyCountForPokemonFamily`)
as a cross-check.

## IL2CPP classes + methods
- `Niantic.Holoholo.Collections.InventoryCache` (holo-game.dll)
  - `GetCurrentItems()` (0-arg) -> ValueCollection; `_dictionary @ +0x10`.
- `Holoholo.Rpc.HoloInventoryKeyProto` (holo-protos.dll)
  - payload `cozs @ +0x10` (System.Object); `TypeOneofCase cozt @ +0x18`.
  - getters: `get_Item`->Item enum, `get_PokemonFamilyId`->int, `get_PokemonId`->u64,
    `get_QuestType`, `get_MegaEvoPokemonSpeciesId`->int, `get_PokemonTempEvoResource`->string,
    `get_TypeCase`.
- `Holoholo.Rpc.HoloInventoryItemProto` (holo-protos.dll)
  - payload `cozu @ +0x10`; `TypeOneofCase cozv @ +0x18`.
  - getters (oneof payloads): `get_Item`->ItemProto, `get_PokemonFamily`->PokemonFamilyProto,
    `get_PlayerStats`->PlayerStatsProto, `get_PlayerCurrency`->PlayerCurrencyProto,
    `get_RaidTickets`->RaidTicketsProto, `get_EggIncubators`->EggIncubatorsProto,
    `get_InventoryUpgrades`, `get_AppliedItems`, `get_EventPasses`->EventPassesStateProto,
    `get_PokemonTempEvoResource`->PokemonTempEvoResourceProto, `get_Quest(s)`, `get_TypeCase`.
- `Holoholo.Rpc.ItemProto` (holo-protos.dll): `Item@+0x10`, `Count@+0x14`, `Unseen@+0x18`.
- `Holoholo.Rpc.PokemonFamilyProto` (holo-protos.dll):
  `FamilyId@+0x10`, `Candy@+0x14`, `MegaEvolutionResources(RepeatedField<TemporaryEvolutionResourceProto>)@+0x18`, `XlCandy@+0x20`.
- `Holoholo.Rpc.TemporaryEvolutionResourceProto` (holo-protos.dll) -- element of the mega list.
  Named field in metadata: `MaxEnergyCount`. **Layout NOT statically known** (see gaps).
- `Holoholo.Rpc.PlayerCurrencyProto`: `Gems@+0x10` (this is the in-dict "PlayerCurrency"; it is
  NOT pokecoins/stardust -- those come from IapService).
- `Niantic.Holoholo.Storefront.IapService` (holo-game.dll):
  `get_Stardusts()`, `get_Coins()`, `get_PurchasedCoins()` (all 0-arg, return boxed int @+0x10).
- `Niantic.Holoholo.Internal.ItemBagImpl` (holo-game.dll) -- cleaner method path (VALIDATE):
  `GetItemCount(itemId)->int`, `GetCandyCountForPokemonFamily(famId)->int`,
  `GetXlCandyCountForPokemonFamily(famId)->int`, `get_AllItems`, `GetCandyCountForPokemon(proto)`.
  Fields: `familyToXlCandyMap`, `totalCandyCounts`, `totalMegaCandyCounts` (Dictionaries).

## Confirmed offsets (cross-validated: live reads AND IL2CPP field-reflection dumps)
- InventoryCache.GetCurrentItems() result, `_dictionary @ +0x10`               (live walk: 6272 entries)
- Dictionary: `entries @ +0x18`; array-len `@ entries+0x18`; entry stride `0x18`;
  `hash@+0x0 next@+0x4 key@+0x8 value@+0x10`                                    (live)
- HoloInventoryKeyProto:  payload `@ +0x10`; TypeCase `@ +0x18`                 (reflection: research_pokedex_inv_types.json)
- HoloInventoryItemProto: payload `@ +0x10`; TypeCase `@ +0x18`                 (reflection: research_pokedex_inv_types.json)
- ItemProto: `Item@+0x10  Count@+0x14  Unseen@+0x18`                            (live: item1150 -> 1150/2731/0)
- PokemonFamilyProto: `FamilyId@+0x10  Candy@+0x14  MegaEvolutionResources@+0x18  XlCandy@+0x20`
                                                                               (reflection: _recon_evolve_out.json; candy/xl also live-confirmed)
- RepeatedField<msg>: `items-array@+0x10  count@+0x18  element[i]@ array+0x20+i*8`  (matches Pokedex CapturedForms walk in pogo_pipeline.py)
- PlayerCurrencyProto: `Gems@+0x10`                                             (reflection: _recon_evolve_out.json)

## Key TypeCase constants (from prior WORKING runs; re-assert via key-census)
- `2`  = Item
- `4`  = PlayerStats   (PlayerStatsProto; level@+0x10; the big int-blob the dust scanner walks)
- `5`  = PlayerCurrency (PlayerCurrencyProto.Gems -- not pokecoins)
- `10` = PokemonFamilyId (candy + XL + mega energy)
- other present cases (raid tickets / incubators / event passes / upgrades): the **draft's key
  census prints the histogram** so you can see exactly which non-{2,4,5,10} cases exist before
  decoding them. Their numeric values were not nailed down statically -- VALIDATE.

## Item ids of interest (IL2CPP enum names; numeric ids need device confirm where flagged)
Confirmed-present in the live item census (each appeared once): 1,2,3,4,7,101-104,201,202,
301-305,401,406,501-505,650,651,701/703/705/706/708/709,901-905,1101-1107,1150-1155,1201-1204,
1250,1301,1302,1351-1353,1401/1402/1404/1408/1410/1411,1501-1507,1600+,2001,2021,2022,2041,
2101-2108,2151-2153.
- `1150` = `OtherEvolutionStoneA` (CONFIRMED count 2731) -- NOTE: an evolution stone, NOT
  Gimmighoul Coin (a prior note mislabeled this).
- Rare candy / XL rare candy / remote+premium raid passes: names exist in metadata
  (`RareCandy`, `XlRareCandy`, `RemoteRaidTicket`-ish, `PremiumRaidTicket`-ish) but the **exact
  numeric Item enum ids are not pinned statically** -> the draft prints the full id->count census
  AND a labelled WATCH_ITEMS subset; reconcile names by decoding the `Item` enum on device
  (use `_decode_items_stardust.py::enumValues('holo-protos.dll','Holoholo.Rpc','Item',[...])`).

## Prior art reused (all in pogo_extract/)
- `_walk_inventory.py` -- first working dict walk + candy reader (families 824/624/999).
- `_diag_model.py` / `_diag_clientitem.py` -- ClientInventoryItem layout + resolveItem probe;
  established TypeCase@+0x18 and candy fields.
- `_extract_currency_items.py` -- item-by-id reader (ItemProto Count@+0x14); the item census.
- `_decode_items_stardust.py` -- Item-enum name decode + currency getter discovery.
- `_confirm_coin_stardust.py` / `_stardust_probe.py` -- IapService.get_Stardusts path.
- `pogo_il2cpp.py` -- find_singleton/liveness + IL2CPP preamble (the draft imports it).
- Offset dumps: `_recon_evolve_out.json` (PokemonFamilyProto/PlayerCurrencyProto offsets),
  `research_pokedex_inv_types.json` (HoloInventoryItem/KeyProto layouts + full oneof getter list),
  `proto_layout.json` (HoloPokemonFamilyId enum: e.g. `V0150FamilyMewtwo` => family id 150).

## GOTCHA: family id == BASE species, not the mega
A PoGo family id is the dex number of the family's **base** species. Mega energy is stored under
that base family. So Mega Charizard energy is under family **4** (Charmander), Mega Gengar under
**92** (Gastly), Mega Beedrill under **13** (Weedle), Mega Gyarados under **129** (Magikarp), etc.
The draft's `MEGA_ENERGY_FAMILIES` already uses the corrected base-family ids (extracted from the
live `HoloPokemonFamilyId` enum literals `VNNNNFamily<BaseSpecies>`), labelled by mega form. Do NOT
query family 6/94/130 expecting Charizard/Gengar/Gyarados mega energy.
- Empirical outputs: `_candy_out.json`, `_currency_items_out.json`, `_walk_inventory_out.json`,
  `_items_stardust_out.json`. Agent class-analysis: `tgt_items.json`, `tgt_currency.json`,
  `tgt_candy.json` (propose the ItemBagImpl method path; method names verified in metadata).

## DEVICE-VALIDATION-NEEDED (flagged)
1. **TemporaryEvolutionResourceProto element layout** -- the per-mega-form energy amount offset.
   No static dump exists; metadata only names `MaxEnergyCount`, and the proto has **no C# getters**.
   Draft dumps `objCls`, reflected `il2cpp_class_get_fields` (name+offset+type), and 0x40 raw
   bytes of the first element, plus candidate ints at +0x10/+0x14/+0x18/+0x1c/+0x20. Expect the
   element to hold `{ TemporaryEvolutionId(int enum) ; current energy(int) ; MaxEnergyCount(int) }`.
   One run on a mega-capable family (e.g. fam 150 Mewtwo, fam 384 Rayquaza) locks it.
2. **ItemBagImpl method path** -- `GetItemCount`/`GetCandyCountForPokemonFamily`/
   `GetXlCandyCountForPokemonFamily` (names confirmed in metadata; invocation + boxed-int arg +
   boxed-int return @+0x10 unproven). Draft calls them and cross-checks vs the dict walk. If they
   work this is the simplest reader (no oneof plumbing) and also exposes mega candy via
   `totalMegaCandyCounts`.
3. **Key TypeCase numeric constants for non-candy/item cases** (RaidTickets / EggIncubators /
   EventPasses / InventoryUpgrades). The 2/4/5/10 set is from working runs; the rest are inferred
   from accessor ordering. Use the draft's `keyCensus` histogram to see which cases are actually
   present, then `probeCase(n)` dumps their value bytes for decoding.
4. **Item enum numeric ids** for RareCandy / XlRareCandy / Remote+Premium raid passes / event
   tickets -- confirm by decoding the `Holoholo.Rpc.Item` enum on device (helper exists).
5. **Multi-instance singletons** -- InventoryCache/IapService/ItemBagImpl may return >1 liveness
   hit (stale + live). `find_singleton` asserts exactly 1; if it trips, fall back to the multi-hit
   list and pick the candidate whose dict walk yields a plausible entry count (mirror the
   PokemonBagImpl `_pick_real_bag` pattern in pogo_pipeline.py).

## What the draft outputs
`read_inventory.py` -> stdout summary + `_read_inventory_out.json` containing: key-case histogram,
full item id->count map (+ labelled watch list), per-family candy/xl/megaEnergy(candidate fields),
the TemporaryEvolutionResourceProto sample (class+fields+bytes), case-probe samples for
tickets/incubators/passes, IapService currencies, and the ItemBagImpl method-path cross-check.
