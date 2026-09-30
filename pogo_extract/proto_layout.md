# Pokémon Proto Class Layouts

Enumerated 105 matching classes via IL2CPP reflection.

## `Holoholo.Rpc.PokemonProto` (size 512 bytes, 83 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `cphz` | `Holoholo.Rpc.PokemonSettingsProto` |
| 0x018 | `cpia` | `Holoholo.Rpc.PokemonDisplayProto` |
| 0x020 | `id_` | `System.UInt64` |
| 0x028 | `pokemonId_` | `System.Int32` |
| 0x02c | `cp_` | `System.Int32` |
| 0x030 | `stamina_` | `System.Int32` |
| 0x034 | `maxStamina_` | `System.Int32` |
| 0x038 | `move1_` | `System.Int32` |
| 0x03c | `move2_` | `System.Int32` |
| 0x040 | `deployedFortId_` | `System.String` |
| 0x048 | `ownerName_` | `System.String` |
| 0x050 | `isEgg_` | `System.Boolean` |
| 0x058 | `eggKmWalkedTarget_` | `System.Double` |
| 0x060 | `eggKmWalkedStart_` | `System.Double` |
| 0x068 | `heightM_` | `System.Single` |
| 0x06c | `weightKg_` | `System.Single` |
| 0x070 | `individualAttack_` | `System.Int32` |
| 0x074 | `individualDefense_` | `System.Int32` |
| 0x078 | `individualStamina_` | `System.Int32` |
| 0x07c | `cpMultiplier_` | `System.Single` |
| 0x080 | `pokeball_` | `Holoholo.Rpc.Item` |
| 0x088 | `capturedS2CellId_` | `System.Int64` |
| 0x090 | `battlesAttacked_` | `System.Int32` |
| 0x094 | `battlesDefended_` | `System.Int32` |
| 0x098 | `eggIncubatorId_` | `System.String` |
| 0x0a0 | `creationTimeMs_` | `System.Int64` |
| 0x0a8 | `numUpgrades_` | `System.Int32` |
| 0x0ac | `additionalCpMultiplier_` | `System.Single` |
| 0x0b0 | `favorite_` | `System.Boolean` |
| 0x0b8 | `nickname_` | `System.String` |
| 0x0c0 | `fromFort_` | `System.Boolean` |
| 0x0c4 | `buddyCandyAwarded_` | `System.Int32` |
| 0x0c8 | `buddyKmWalked_` | `System.Single` |
| 0x0cc | `displayPokemonId_` | `System.Int32` |
| 0x0d0 | `displayCp_` | `System.Int32` |
| 0x0d8 | `pokemonDisplay_` | `Holoholo.Rpc.PokemonDisplayProto` |
| 0x0e0 | `isBad_` | `System.Boolean` |
| 0x0e1 | `hatchedFromEgg_` | `System.Boolean` |
| 0x0e4 | `coinsReturned_` | `System.Int32` |
| 0x0e8 | `deployedDurationMs_` | `System.Int64` |
| 0x0f0 | `deployedReturnedTimestampMs_` | `System.Int64` |
| 0x0f8 | `cpMultiplierBeforeTrading_` | `System.Single` |
| 0x0fc | `tradingOriginalOwnerHash_` | `System.Int32` |
| 0x100 | `originalOwnerNickname_` | `System.String` |
| 0x108 | `tradedTimeMs_` | `System.Int64` |
| 0x110 | `isLucky_` | `System.Boolean` |
| 0x114 | `move3_` | `System.Int32` |
| 0x118 | `pvpCombatStats_` | `Holoholo.Rpc.PokemonCombatStatsProto` |
| 0x120 | `npcCombatStats_` | `Holoholo.Rpc.PokemonCombatStatsProto` |
| 0x128 | `move2IsPurifiedExclusive_` | `System.Boolean` |
| 0x130 | `limitedPokemonIdentifier_` | `System.String` |
| 0x138 | `preBoostedCp_` | `System.Int32` |
| 0x13c | `preBoostedAdditionalCpMultiplier_` | `System.Single` |
| 0x140 | `deployedGymLatDegree_` | `System.Double` |
| 0x148 | `deployedGymLngDegree_` | `System.Double` |
| 0x150 | `hasMegaEvolved_` | `System.Boolean` |
| 0x154 | `eggType_` | `Holoholo.Rpc.HoloPokemonEggType` |
| 0x158 | `tempEvoCp_` | `System.Int32` |
| 0x15c | `tempEvoStaminaModifier_` | `System.Single` |
| 0x160 | `tempEvoCpMultiplier_` | `System.Single` |
| 0x168 | `megaEvolvedForms_` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.HoloTemporaryEvolutionId` |
| 0x170 | `evolutionQuestInfo_` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.PokemonEvolutionQuestPro` |
| 0x178 | `originDetail_` | `Holoholo.Rpc.PokemonCreateDetail` |
| 0x180 | `pokemonTagIds_` | `Niantic.Protobuf.Collections.RepeatedField<System.UInt64>` |
| 0x188 | `originEvents_` | `Niantic.Protobuf.Collections.RepeatedField<System.String>` |
| 0x190 | `eggSlotType_` | `Holoholo.Rpc.EggSlotType` |
| 0x198 | `eggTelemetry_` | `Holoholo.Rpc.EggTelemetryProto` |
| 0x1a0 | `eggDistribution_` | `Holoholo.Rpc.EggDistributionProto` |
| 0x1a8 | `size_` | `Holoholo.Rpc.HoloPokemonSize` |
| 0x1b0 | `pokemonContestInfo_` | `Holoholo.Rpc.PokemonContestInfoProto` |
| 0x1b8 | `caughtInParty_` | `System.Boolean` |
| 0x1b9 | `isComponent_` | `System.Boolean` |
| 0x1ba | `isFusion_` | `System.Boolean` |
| 0x1c0 | `irisSocialDeployment_` | `Holoholo.Rpc.IrisSocialDeploymentProto` |
| 0x1c8 | `breadMoves_` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Proto.Shared.Bread.BreadMove` |
| 0x1d0 | `deployedStationId_` | `System.String` |
| 0x1d8 | `deployedStationExpirationTimeMs_` | `System.Int64` |
| 0x1e0 | `isStampCollectionReward_` | `System.Boolean` |
| 0x1e1 | `isActivelyTraining_` | `System.Boolean` |
| 0x1e8 | `bonusStatLevel_` | `Holoholo.Rpc.PokemonBonusStatLevelProto` |
| 0x1f0 | `markedRemoteTradable_` | `System.Boolean` |
| 0x1f1 | `inEscrow_` | `System.Boolean` |
| 0x1f8 | `dayNightBonusStat_` | `Holoholo.Rpc.PokemonBonusStatLevelProto` |

## `Holoholo.Rpc.TradingPokemonProto` (size 152 bytes, 26 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `PokedexEntryNumber` | `System.Int32` |
| 0x01c | `OriginalCp` | `System.Int32` |
| 0x020 | `AdjustedCpMin` | `System.Int32` |
| 0x024 | `AdjustedCpMax` | `System.Int32` |
| 0x028 | `OriginalStamina` | `System.Int32` |
| 0x02c | `AdjustedStaminaMin` | `System.Int32` |
| 0x030 | `AdjustedStaminaMax` | `System.Int32` |
| 0x034 | `FriendLevelCap` | `System.Boolean` |
| 0x038 | `Move1` | `System.Int32` |
| 0x03c | `Move2` | `System.Int32` |
| 0x040 | `PokemonDisplay` | `Holoholo.Rpc.PokemonDisplayProto` |
| 0x048 | `CapturedS2CellId` | `System.Int64` |
| 0x050 | `TradedPokemon` | `Holoholo.Rpc.PokemonProto` |
| 0x058 | `Pokeball` | `Holoholo.Rpc.Item` |
| 0x05c | `IndividualAttack` | `System.Int32` |
| 0x060 | `IndividualDefense` | `System.Int32` |
| 0x064 | `IndividualStamina` | `System.Int32` |
| 0x068 | `Nickname` | `System.String` |
| 0x070 | `Favorite` | `System.Boolean` |
| 0x074 | `Move3` | `System.Int32` |
| 0x078 | `CreationTimeMs` | `System.Int64` |
| 0x080 | `HeightM` | `System.Single` |
| 0x084 | `WeightKg` | `System.Single` |
| 0x088 | `PokemonSize` | `Holoholo.Rpc.HoloPokemonSize` |
| 0x090 | `BreadMoveSlots` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Proto.Shared.Bread.BreadMove` |

## `CombatPokemonProto` (size 152 bytes, 26 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `PokedexId` | `System.Int32` |
| 0x01c | `Cp` | `System.Int32` |
| 0x020 | `CpMultiplier` | `System.Single` |
| 0x024 | `Stamina` | `System.Int32` |
| 0x028 | `MaxStamina` | `System.Int32` |
| 0x02c | `Move1` | `System.Int32` |
| 0x030 | `Move2` | `System.Int32` |
| 0x034 | `Move3` | `System.Int32` |
| 0x038 | `Energy` | `System.Int32` |
| 0x040 | `PokemonDisplay` | `Holoholo.Rpc.PokemonDisplayProto` |
| 0x048 | `IndividualAttack` | `System.Int32` |
| 0x04c | `IndividualDefense` | `System.Int32` |
| 0x050 | `IndividualStamina` | `System.Int32` |
| 0x054 | `AttackStatStage` | `System.Int32` |
| 0x058 | `DefenseStatStage` | `System.Int32` |
| 0x05c | `BattlesWon` | `System.Int32` |
| 0x060 | `BattlesLost` | `System.Int32` |
| 0x068 | `Nickname` | `System.String` |
| 0x070 | `Pokeball` | `Holoholo.Rpc.Item` |
| 0x074 | `HeightM` | `System.Single` |
| 0x078 | `WeightKg` | `System.Single` |
| 0x07c | `PokemonSize` | `Holoholo.Rpc.HoloPokemonSize` |
| 0x080 | `NotableActionHistory` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.VsActionHistory>` |
| 0x088 | `VsEffectTag` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.VsEffectTag>` |
| 0x090 | `CombatPokemonIbfc` | `Holoholo.Rpc.CombatProto.Types.CombatPokemonIbfcProto` |

## `Holoholo.Rpc.PokemonDisplayProto` (size 144 bytes, 25 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Costume` | `Holoholo.Rpc.PokemonDisplayProto.Types.Costume` |
| 0x014 | `Gender` | `Holoholo.Rpc.PokemonDisplayProto.Types.Gender` |
| 0x018 | `Shiny` | `System.Boolean` |
| 0x01c | `Form` | `Holoholo.Rpc.PokemonDisplayProto.Types.Form` |
| 0x020 | `WeatherBoostedCondition` | `Niantic.Rpc.GameplayWeatherProto.Types.WeatherCondition` |
| 0x024 | `Alignment` | `Holoholo.Rpc.PokemonDisplayProto.Types.Alignment` |
| 0x028 | `PokemonBadge` | `Holoholo.Rpc.PokemonBadge` |
| 0x02c | `CurrentTempEvolution` | `Holoholo.Rpc.HoloTemporaryEvolutionId` |
| 0x030 | `TemporaryEvolutionFinishMs` | `System.Int64` |
| 0x038 | `TempEvolutionIsLocked` | `System.Boolean` |
| 0x03c | `LockedTempEvolution` | `Holoholo.Rpc.HoloTemporaryEvolutionId` |
| 0x040 | `OriginalCostume` | `Holoholo.Rpc.PokemonDisplayProto.Types.Costume` |
| 0x048 | `DisplayId` | `System.Int64` |
| 0x050 | `MegaEvolutionLevel` | `Holoholo.Rpc.PokemonMegaEvolutionLevelProto` |
| 0x058 | `LocationCard` | `Holoholo.Rpc.LocationCardDisplayProto` |
| 0x060 | `BreadModeEnum` | `Holoholo.Proto.Shared.Bread.BreadModeEnum.Types.Modifier` |
| 0x064 | `IsStrongPokemon` | `System.Boolean` |
| 0x068 | `ShinyRate` | `System.Single` |
| 0x06c | `LocationCardRate` | `System.Single` |
| 0x070 | `NaturalArtType` | `Holoholo.Rpc.PokemonDisplayProto.Types.NaturalArtType` |
| 0x074 | `NaturalArtBackgroundAsset` | `Holoholo.Rpc.PokemonDisplayProto.Types.NaturalArtBackgroundAsset` |
| 0x078 | `NaturalArtUseFullScene` | `System.Boolean` |
| 0x07c | `DayNightType` | `Holoholo.Rpc.PokemonDisplayProto.Types.DayNight` |
| 0x080 | `BranchedMegaEvolutionLevels` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.PokemonDisplayProto.Type` |
| 0x088 | `TempEvoLocationDisplayAttributes` | `Holoholo.Rpc.PokemonDisplayProto.Types.PokemonTempEvoDisplayProto` |

## `Holoholo.Rpc.BelugaPokemonProto` (size 136 bytes, 25 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `TrainerName` | `System.String` |
| 0x018 | `TrainerGender` | `Holoholo.Rpc.BelugaPokemonProto.Types.TrainerGender` |
| 0x01c | `TrainerTeam` | `Holoholo.Rpc.BelugaPokemonProto.Types.Team` |
| 0x020 | `TrainerLevel` | `System.Int32` |
| 0x024 | `PokedexId` | `System.Int32` |
| 0x028 | `Cp` | `System.Int32` |
| 0x02c | `PokemonLevel` | `System.Single` |
| 0x030 | `MaxHp` | `System.Int32` |
| 0x038 | `OriginLat` | `System.Double` |
| 0x040 | `OriginLng` | `System.Double` |
| 0x048 | `Height` | `System.Single` |
| 0x04c | `Weight` | `System.Single` |
| 0x050 | `IndividualAttack` | `System.Int32` |
| 0x054 | `IndividualDefense` | `System.Int32` |
| 0x058 | `IndividualStamina` | `System.Int32` |
| 0x05c | `CreationDay` | `System.Int32` |
| 0x060 | `CreationMonth` | `System.Int32` |
| 0x064 | `CreationYear` | `System.Int32` |
| 0x068 | `Nickname` | `System.String` |
| 0x070 | `Gender` | `Holoholo.Rpc.BelugaPokemonProto.Types.PokemonGender` |
| 0x074 | `Costume` | `Holoholo.Rpc.BelugaPokemonProto.Types.PokemonCostume` |
| 0x078 | `Form` | `Holoholo.Rpc.BelugaPokemonProto.Types.PokemonForm` |
| 0x07c | `Shiny` | `System.Boolean` |
| 0x080 | `Move1` | `System.Int32` |
| 0x084 | `Move2` | `System.Int32` |

## `Holoholo.Rpc.BattlePokemonProto` (size 104 bytes, 12 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Id` | `System.UInt64` |
| 0x018 | `PokedexId` | `Holoholo.Rpc.HoloPokemonId` |
| 0x020 | `Display` | `Holoholo.Rpc.PokemonDisplayProto` |
| 0x028 | `Cp` | `System.Int32` |
| 0x030 | `Resources` | `Niantic.Protobuf.Collections.MapField<System.Int32,Holoholo.Rpc.BattleResourcePr` |
| 0x038 | `ItemResources` | `Niantic.Protobuf.Collections.MapField<System.Int32,Holoholo.Rpc.BattleResourcePr` |
| 0x040 | `Moves` | `Niantic.Protobuf.Collections.MapField<System.Int32,Holoholo.Rpc.BattlePokemonPro` |
| 0x048 | `Modifiers` | `Niantic.Protobuf.Collections.MapField<System.Int32,Holoholo.Rpc.BattlePokemonPro` |
| 0x050 | `ActiveAbilities` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.AbilityProto.Types.Abili` |
| 0x058 | `Pokeball` | `Holoholo.Rpc.Item` |
| 0x05c | `Size` | `Holoholo.Rpc.HoloPokemonSize` |
| 0x060 | `Nickname` | `System.String` |

## `Holoholo.Rpc.GetHatchedEggsOutProto` (size 104 bytes, 11 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Success` | `System.Boolean` |
| 0x018 | `PokemonId` | `Niantic.Protobuf.Collections.RepeatedField<System.UInt64>` |
| 0x020 | `ExpAwarded` | `Niantic.Protobuf.Collections.RepeatedField<System.Int32>` |
| 0x028 | `CandyAwarded` | `Niantic.Protobuf.Collections.RepeatedField<System.Int32>` |
| 0x030 | `StardustAwarded` | `Niantic.Protobuf.Collections.RepeatedField<System.Int32>` |
| 0x038 | `EggKmWalked` | `Niantic.Protobuf.Collections.RepeatedField<System.Single>` |
| 0x040 | `HatchedPokemon` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.PokemonProto>` |
| 0x048 | `XlCandyAwarded` | `Niantic.Protobuf.Collections.RepeatedField<System.Int32>` |
| 0x050 | `ItemsAwarded` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.LootProto>` |
| 0x058 | `ExpiredEggIncubatorRecap` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.ExpiredIncubatorRecapPro` |
| 0x060 | `BoostableXpToken` | `System.String` |

## `Holoholo.Rpc.TransferPokemonSizeLeaderboardEntryProto` (size 96 bytes, 10 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `FortId` | `System.String` |
| 0x018 | `ContestSchedule` | `Holoholo.Rpc.ContestScheduleProto` |
| 0x020 | `ContestIdToRemove` | `System.String` |
| 0x028 | `ContestMetric` | `Holoholo.Rpc.ContestMetricProto` |
| 0x030 | `PokemonId` | `System.UInt64` |
| 0x038 | `PokemonIdToTransfer` | `System.UInt64` |
| 0x040 | `FortLatDegrees` | `System.Double` |
| 0x048 | `FortLngDegrees` | `System.Double` |
| 0x050 | `PokemonIdToReplace` | `System.UInt64` |
| 0x058 | `EntryPoint` | `Holoholo.Rpc.EntryPointForContestEntry` |

## `Holoholo.Rpc.CatchPokemonProto` (size 88 bytes, 9 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `EncounterId` | `System.UInt64` |
| 0x018 | `Pokeball` | `System.Int32` |
| 0x020 | `NormalizedReticleSize` | `System.Double` |
| 0x028 | `SpawnPointGuid` | `System.String` |
| 0x030 | `HitPokemon` | `System.Boolean` |
| 0x038 | `SpinModifier` | `System.Double` |
| 0x040 | `NormalizedHitPosition` | `System.Double` |
| 0x048 | `ArPlusValues` | `Holoholo.Rpc.ARPlusEncounterValuesProto` |
| 0x050 | `ShouldFlee` | `System.Boolean` |

## `Holoholo.Rpc.BuddyPokemonProto` (size 80 bytes, 8 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `BuddyPokemonId` | `System.UInt64` |
| 0x018 | `StartKmWalked` | `System.Double` |
| 0x020 | `LastKmAwarded` | `System.Double` |
| 0x028 | `DailyBuddySwaps` | `Holoholo.Rpc.DailyCounterProto` |
| 0x030 | `LastKmAwardedMs` | `System.Int64` |
| 0x038 | `BestBuddiesBackfilled` | `System.Boolean` |
| 0x040 | `LastSetTimestampMs` | `System.Int64` |
| 0x048 | `PendingBonusKm` | `System.Single` |

## `Holoholo.Rpc.UpdatePokemonSizeLeaderboardEntryProto` (size 80 bytes, 8 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `FortId` | `System.String` |
| 0x018 | `ContestSchedule` | `Holoholo.Rpc.ContestScheduleProto` |
| 0x020 | `ContestMetric` | `Holoholo.Rpc.ContestMetricProto` |
| 0x028 | `PokemonId` | `System.UInt64` |
| 0x030 | `PokemonIdToReplace` | `System.UInt64` |
| 0x038 | `FortLatDegrees` | `System.Double` |
| 0x040 | `FortLngDegrees` | `System.Double` |
| 0x048 | `EntryPoint` | `Holoholo.Rpc.EntryPointForContestEntry` |

## `Holoholo.Rpc.PokemonSizeSettingsProto` (size 72 bytes, 14 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `XxsLowerBound` | `System.Single` |
| 0x014 | `XsLowerBound` | `System.Single` |
| 0x018 | `MLowerBound` | `System.Single` |
| 0x01c | `MUpperBound` | `System.Single` |
| 0x020 | `XlUpperBound` | `System.Single` |
| 0x024 | `XxlUpperBound` | `System.Single` |
| 0x028 | `XxsScaleMultiplier` | `System.Single` |
| 0x02c | `XsScaleMultiplier` | `System.Single` |
| 0x030 | `XlScaleMultiplier` | `System.Single` |
| 0x034 | `XxlScaleMultiplier` | `System.Single` |
| 0x038 | `DisablePokedexRecordDisplayAggregate` | `System.Boolean` |
| 0x039 | `DisablePokedexRecordDisplayForForms` | `System.Boolean` |
| 0x03c | `PokedexDisplayPokemonTrackedThreshold` | `System.Int32` |
| 0x040 | `RecordDisplayPokemonTrackedThreshold` | `System.Int32` |

## `Holoholo.Rpc.MotivatedPokemonProto` (size 72 bytes, 8 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Pokemon` | `Holoholo.Rpc.PokemonProto` |
| 0x018 | `DeployMs` | `System.Int64` |
| 0x020 | `CpWhenDeployed` | `System.Int32` |
| 0x028 | `MotivationNow` | `System.Double` |
| 0x030 | `CpNow` | `System.Int32` |
| 0x034 | `BerryValue` | `System.Single` |
| 0x038 | `FeedCooldownDurationMillis` | `System.Int64` |
| 0x040 | `FoodValue` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.FoodValue>` |

## `Holoholo.Rpc.WildPokemonProto` (size 72 bytes, 7 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `EncounterId` | `System.UInt64` |
| 0x018 | `LastModifiedMs` | `System.Int64` |
| 0x020 | `Latitude` | `System.Double` |
| 0x028 | `Longitude` | `System.Double` |
| 0x030 | `SpawnPointId` | `System.String` |
| 0x038 | `Pokemon` | `Holoholo.Rpc.PokemonProto` |
| 0x040 | `TimeTillHiddenMs` | `System.Int32` |

## `Holoholo.Rpc.MapPokemonProto` (size 72 bytes, 7 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `SpawnpointId` | `System.String` |
| 0x018 | `EncounterId` | `System.UInt64` |
| 0x020 | `PokedexTypeId` | `System.Int32` |
| 0x028 | `ExpirationTimeMs` | `System.Int64` |
| 0x030 | `Latitude` | `System.Double` |
| 0x038 | `Longitude` | `System.Double` |
| 0x040 | `PokemonDisplay` | `Holoholo.Rpc.PokemonDisplayProto` |

## `Niantic.Holoholo.Bread.PlayerClientStationedPokemonProto` (size 64 bytes, 6 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Pokemon` | `Holoholo.Rpc.PokemonProto` |
| 0x018 | `TrainerName` | `System.String` |
| 0x020 | `DeployTimestampMs` | `System.Int64` |
| 0x028 | `PlayerAvatar` | `Holoholo.Rpc.PlayerAvatarProto` |
| 0x030 | `PlayerNeutralAvatar` | `Holoholo.Rpc.PlayerNeutralAvatarProto` |
| 0x038 | `TrainerLevel` | `System.Int32` |

## `Niantic.Holoholo.Bread.SaveForLaterBreadPokemonProto` (size 64 bytes, 6 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `SaveForLaterSeed` | `System.Int64` |
| 0x018 | `StationId` | `System.String` |
| 0x020 | `SaveForLaterExpireMs` | `System.Int64` |
| 0x028 | `BreadPokemon` | `Holoholo.Rpc.PokemonProto` |
| 0x030 | `RewardPokemon` | `Holoholo.Rpc.PokemonProto` |
| 0x038 | `NumAttemptsLeft` | `System.Int32` |

## `Holoholo.Rpc.CheckPokemonSizeLeaderboardEligibilityProto` (size 64 bytes, 6 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `FortId` | `System.String` |
| 0x018 | `ContestSchedule` | `Holoholo.Rpc.ContestScheduleProto` |
| 0x020 | `ContestMetric` | `Holoholo.Rpc.ContestMetricProto` |
| 0x028 | `PokemonId` | `System.UInt64` |
| 0x030 | `FortLatDegrees` | `System.Double` |
| 0x038 | `FortLngDegrees` | `System.Double` |

## `Niantic.Holoholo.Bread.StationPokemonProto` (size 56 bytes, 5 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `StationId` | `System.String` |
| 0x018 | `PokemonId` | `System.UInt64` |
| 0x020 | `StationLatDegrees` | `System.Double` |
| 0x028 | `StationLngDegrees` | `System.Double` |
| 0x030 | `BreadBattleId` | `System.String` |

## `Holoholo.Rpc.EvolvePokemonProto` (size 56 bytes, 9 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `EvolutionItemRequirement` | `Holoholo.Rpc.Item` |
| 0x01c | `TargetPokemonId` | `Holoholo.Rpc.HoloPokemonId` |
| 0x020 | `TargetPokemonForm` | `Holoholo.Rpc.PokemonDisplayProto.Types.Form` |
| 0x024 | `UseSpecial` | `System.Boolean` |
| 0x025 | `Preview` | `System.Boolean` |
| 0x028 | `DebugProto` | `Holoholo.Rpc.DebugEvolvePreviewProto` |
| 0x030 | `EvolutionItemRequirementCount` | `System.Int32` |
| 0x034 | `EnabledByPlayerBonus` | `System.Boolean` |

## `Holoholo.Rpc.GymFeedPokemonProto` (size 56 bytes, 6 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Item` | `Holoholo.Rpc.Item` |
| 0x014 | `StartingQuantity` | `System.Int32` |
| 0x018 | `GymId` | `System.String` |
| 0x020 | `PokemonId` | `System.UInt64` |
| 0x028 | `PlayerLatDegrees` | `System.Double` |
| 0x030 | `PlayerLngDegrees` | `System.Double` |

## `Holoholo.Rpc.NearbyPokemonProto` (size 56 bytes, 6 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokedexNumber` | `System.Int32` |
| 0x014 | `DistanceMeters` | `System.Single` |
| 0x018 | `EncounterId` | `System.UInt64` |
| 0x020 | `FortId` | `System.String` |
| 0x028 | `FortImageUrl` | `System.String` |
| 0x030 | `PokemonDisplay` | `Holoholo.Rpc.PokemonDisplayProto` |

## `Holoholo.Rpc.FollowerPokemonProto` (size 56 bytes, 5 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Display` | `Holoholo.Rpc.PokemonDisplayProto` |
| 0x018 | `EndMs` | `System.Int64` |
| 0x020 | `Id` | `Holoholo.Rpc.FollowerPokemonProto.Types.FollowerId` |
| 0x028 | `cpys` | `System.Object` |
| 0x030 | `cpyt` | `Holoholo.Rpc.FollowerPokemonProto.PokemonDataOneofCase` |

## `PokemonSize` (size 48 bytes, 4 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `HeightCoefficient` | `System.Double` |
| 0x018 | `WeightCoefficient` | `System.Double` |
| 0x020 | `IvCoefficient` | `System.Double` |
| 0x028 | `XxlAdjustmentFactor` | `System.Double` |

## `Holoholo.Rpc.PokemonStatsLimitsProto` (size 48 bytes, 8 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `MinPokemonLevel` | `System.Int32` |
| 0x014 | `MaxPokemonLevel` | `System.Int32` |
| 0x018 | `MinAttack` | `System.Int32` |
| 0x01c | `MaxAttack` | `System.Int32` |
| 0x020 | `MinDefense` | `System.Int32` |
| 0x024 | `MaxDefense` | `System.Int32` |
| 0x028 | `MinHp` | `System.Int32` |
| 0x02c | `MaxHp` | `System.Int32` |

## `Holoholo.Rpc.LocationCardSettingsProto` (size 48 bytes, 4 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `LocationCard` | `Holoholo.Rpc.LocationCard` |
| 0x018 | `ImageUrl` | `System.String` |
| 0x020 | `CardType` | `Holoholo.Rpc.CardType` |
| 0x028 | `VfxAddress` | `System.String` |

## `Holoholo.Rpc.GetPokemonSizeLeaderboardEntryProto` (size 48 bytes, 5 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `ContestId` | `System.String` |
| 0x018 | `StartIndex` | `System.Int32` |
| 0x01c | `EndIndex` | `System.Int32` |
| 0x020 | `ContestMetric` | `Holoholo.Rpc.ContestMetricProto` |
| 0x028 | `IsRelativeToPlayer` | `System.Boolean` |

## `Holoholo.Rpc.SetLobbyPokemonProto` (size 48 bytes, 4 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `RaidSeed` | `System.Int64` |
| 0x018 | `GymId` | `System.String` |
| 0x020 | `LobbyId` | `Niantic.Protobuf.Collections.RepeatedField<System.Int32>` |
| 0x028 | `PokemonId` | `Niantic.Protobuf.Collections.RepeatedField<System.UInt64>` |

## `GymPokemonProto` (size 48 bytes, 4 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.Int64` |
| 0x018 | `Motivation` | `System.Single` |
| 0x020 | `DeployedTimestampMs` | `System.Int64` |
| 0x028 | `CoinsReturned` | `System.Int32` |

## `Niantic.Holoholo.Bread.BreadLobbyPokemonProto` (size 40 bytes, 4 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Id` | `System.Int64` |
| 0x018 | `PokedexId` | `Holoholo.Rpc.HoloPokemonId` |
| 0x01c | `Cp` | `System.Int32` |
| 0x020 | `PercentHealth` | `System.Single` |

## `Holoholo.Rpc.AdventureSyncEggHatchingProgress` (size 40 bytes, 5 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Status` | `Holoholo.Rpc.AdventureSyncEggHatchingProgress.Types.Status` |
| 0x014 | `EggDistanceKm` | `System.Single` |
| 0x018 | `CurrentDistanceKm` | `System.Single` |
| 0x01c | `Incubator` | `Holoholo.Rpc.AdventureSyncEggHatchingProgress.Types.IncubatorType` |
| 0x020 | `OriginalEggDistanceKm` | `System.Single` |

## `Holoholo.Rpc.MegaEvolvePokemonProto` (size 40 bytes, 4 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `TempEvoId` | `Holoholo.Rpc.HoloTemporaryEvolutionId` |
| 0x01c | `Preview` | `System.Boolean` |
| 0x020 | `ClientContext` | `Holoholo.Rpc.MegaEvolvePokemonClientContextHelper.Types.MegaEvolvePokemonClientC` |

## `Holoholo.Rpc.MegaLevelUpProto` (size 40 bytes, 4 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `TempEvoId` | `Holoholo.Rpc.HoloTemporaryEvolutionId` |
| 0x01c | `TargetMegaLevel` | `System.Int32` |
| 0x020 | `CurrentMegaLevel` | `System.Int32` |

## `Holoholo.Rpc.MegaLevelUpOutProto` (size 40 bytes, 5 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Result` | `Holoholo.Rpc.MegaLevelUpOutProto.Types.Result` |
| 0x014 | `MegaLevelAfter` | `System.Int32` |
| 0x018 | `MegaEnergyBalanceAfter` | `System.Int32` |
| 0x01c | `TotalMegaEnergyCost` | `System.Int32` |
| 0x020 | `UpdatedPokemon` | `Holoholo.Rpc.PokemonProto` |

## `Holoholo.Rpc.GlowFxPokemonProto` (size 40 bytes, 5 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `Holoholo.Rpc.HoloPokemonId` |
| 0x014 | `TempEvoId` | `Holoholo.Rpc.HoloTemporaryEvolutionId` |
| 0x018 | `Form` | `Holoholo.Rpc.PokemonDisplayProto.Types.Form` |
| 0x01c | `Costume` | `Holoholo.Rpc.PokemonDisplayProto.Types.Costume` |
| 0x020 | `Gender` | `Holoholo.Rpc.PokemonDisplayProto.Types.Gender` |

## `TargetPokemonProto` (size 40 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokedexId` | `Holoholo.Rpc.HoloPokemonId` |
| 0x018 | `Display` | `Holoholo.Rpc.PokemonDisplayProto` |
| 0x020 | `HintTextKey` | `System.String` |

## `Holoholo.Rpc.UpdateFieldBookPostCatchPokemonProto` (size 40 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `FieldbookId` | `System.String` |
| 0x018 | `PokemonUid` | `System.UInt64` |
| 0x020 | `StickerId` | `System.String` |

## `Holoholo.Rpc.LobbyPokemonProto` (size 40 bytes, 4 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Id` | `System.Int64` |
| 0x018 | `PokedexId` | `Holoholo.Rpc.HoloPokemonId` |
| 0x01c | `Cp` | `System.Int32` |
| 0x020 | `PercentHealth` | `System.Single` |

## `Holoholo.Rpc.TrainingPokemonProto` (size 40 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `QuestIdsToComplete` | `Niantic.Protobuf.Collections.RepeatedField<System.String>` |
| 0x020 | `ActiveTrainingQuests` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.TrainingPokemonProto.Typ` |

## `CombatQuestPokemonProto` (size 40 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `PokedexId` | `System.Int32` |
| 0x020 | `PokemonDisplay` | `Holoholo.Rpc.PokemonDisplayProto` |

## `Holoholo.Rpc.UpgradePokemonProto` (size 40 bytes, 4 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `Preview` | `System.Boolean` |
| 0x01c | `NumberOfUpgrades` | `System.UInt32` |
| 0x020 | `PokemonCurrentCp` | `System.Int32` |

## `Niantic.Holoholo.Bread.ReleaseStationedPokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `StationId` | `System.String` |
| 0x018 | `PokemonId` | `System.UInt64` |

## `Holoholo.Rpc.GetIncensePokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PlayerLatDegrees` | `System.Double` |
| 0x018 | `PlayerLngDegrees` | `System.Double` |

## `Holoholo.Rpc.SpawnPokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokedexId` | `Holoholo.Rpc.HoloPokemonId` |
| 0x018 | `PokemonDisplay` | `Holoholo.Rpc.PokemonDisplayProto` |

## `Holoholo.Rpc.GetMegaLevelUpPreviewProto` (size 32 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `TempEvoId` | `Holoholo.Rpc.HoloTemporaryEvolutionId` |
| 0x01c | `CurrentMegaLevel` | `System.Int32` |

## `BulkMegaLevelUpCost` (size 32 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `NumberOfLevelUp` | `System.UInt32` |
| 0x014 | `TargetMegaLevel` | `System.Int32` |
| 0x018 | `TotalMegaEnergyCost` | `System.Int32` |

## `Holoholo.Rpc.GetMegaLevelUpPreviewOutProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `BulkLevelUpCostTable` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.GetMegaLevelUpPreviewOut` |
| 0x018 | `Result` | `Holoholo.Rpc.MegaLevelUpOutProto.Types.Result` |

## `Holoholo.Rpc.PokemonStatsAttributesProto` (size 32 bytes, 4 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `BaseStamina` | `System.Int32` |
| 0x014 | `BaseAttack` | `System.Int32` |
| 0x018 | `BaseDefense` | `System.Int32` |
| 0x01c | `DodgeEnergyDelta` | `System.Int32` |

## `Holoholo.Rpc.SpawnTablePokemonProto` (size 32 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `Holoholo.Rpc.HoloPokemonId` |
| 0x014 | `Weight` | `System.Single` |
| 0x018 | `Form` | `Holoholo.Rpc.PokemonDisplayProto.Types.Form` |

## `Holoholo.Rpc.NpcPokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonType` | `Holoholo.Rpc.HoloPokemonId` |
| 0x018 | `PokemonDisplay` | `Holoholo.Rpc.PokemonDisplayProto` |

## `Holoholo.Rpc.FormChangeLocationCardSettingsProto` (size 32 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `BasePokemonLocationCard` | `Holoholo.Rpc.LocationCard` |
| 0x014 | `ComponentPokemonLocationCard` | `Holoholo.Rpc.LocationCard` |
| 0x018 | `FusionPokemonLocationCard` | `Holoholo.Rpc.LocationCard` |

## `Holoholo.Rpc.AddressablePokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `CatalogId` | `System.Int32` |
| 0x018 | `AddressablePokemonIds` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.HoloPokemonId>` |

## `Holoholo.Rpc.EggHatchImprovementsSettingsProto` (size 32 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `FeatureEnabled` | `System.Boolean` |
| 0x014 | `BootDelayMs` | `System.Int32` |
| 0x018 | `RaidInviteHardCapMs` | `System.Int32` |

## `Holoholo.Rpc.RaidPlayerStatsPokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `HoloPokemonId` | `Holoholo.Rpc.HoloPokemonId` |
| 0x018 | `PokemonDisplay` | `Holoholo.Rpc.PokemonDisplayProto` |

## `HatchedEggPokemonSummaryProto` (size 32 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonDisplay` | `Holoholo.Rpc.PokemonDisplayProto` |
| 0x018 | `EggRarity` | `System.Int32` |
| 0x01c | `PokedexId` | `Holoholo.Rpc.HoloPokemonId` |

## `Holoholo.Rpc.UnlockPokemonMoveOutProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Result` | `Holoholo.Rpc.UnlockPokemonMoveOutProto.Types.Result` |
| 0x018 | `UnlockedPokemon` | `Holoholo.Rpc.PokemonProto` |

## `Holoholo.Rpc.CheckPokemonSizeLeaderboardEligibilityOutProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Status` | `Holoholo.Rpc.CheckPokemonSizeLeaderboardEligibilityOutProto.Types.Status` |
| 0x018 | `PokemonIdToReplace` | `System.UInt64` |

## `Holoholo.Rpc.GetPokemonSizeLeaderboardEntryOutProto` (size 32 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Status` | `Holoholo.Rpc.GetPokemonSizeLeaderboardEntryOutProto.Types.Status` |
| 0x014 | `TotalEntries` | `System.Int32` |
| 0x018 | `ContestEntries` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.ContestEntryProto>` |

## `Holoholo.Rpc.GetPokemonSizeLeaderboardFriendEntryProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `ContestId` | `System.String` |
| 0x018 | `ContestMetric` | `Holoholo.Rpc.ContestMetricProto` |

## `Holoholo.Rpc.GetPokemonSizeLeaderboardFriendEntryOutProto` (size 32 bytes, 3 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Status` | `Holoholo.Rpc.GetPokemonSizeLeaderboardFriendEntryOutProto.Types.Status` |
| 0x014 | `TotalFriendEntries` | `System.Int32` |
| 0x018 | `ContestFriendEntries` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.ContestFriendEntryProto>` |

## `Holoholo.Rpc.FortPokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonProto` | `Holoholo.Rpc.MapPokemonProto` |
| 0x018 | `SpawnType` | `Holoholo.Rpc.FortPokemonProto.Types.SpawnType` |

## `Holoholo.Rpc.SetFavoritePokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.Int64` |
| 0x018 | `IsFavorite` | `System.Boolean` |

## `Holoholo.Rpc.ReleasePokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `PokemonIds` | `Niantic.Protobuf.Collections.RepeatedField<System.UInt64>` |

## `Holoholo.Rpc.NicknamePokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `Nickname` | `System.String` |

## `TrainingPokemonProto` (size 32 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |
| 0x018 | `TrainingQuests` | `Holoholo.Rpc.PokemonTrainingQuestProto` |

## `Holoholo.Rpc.ContestHatchedFocusProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `RequireToBeHatched` | `System.Boolean` |

## `EventPokemonMoves` (size 24 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `QuickMove` | `Holoholo.Rpc.HoloPokemonMove` |
| 0x014 | `CinematicMove` | `Holoholo.Rpc.HoloPokemonMove` |

## `Holoholo.Rpc.FormChangeLocationCardBasicSettingsProto` (size 24 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `ExistingLocationCard` | `Holoholo.Rpc.LocationCard` |
| 0x014 | `ReplacementLocationCard` | `Holoholo.Rpc.LocationCard` |

## `Holoholo.Rpc.PokedexLocationCardStatsProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `LocationCards` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.LocationCard>` |

## `Holoholo.Rpc.WithPokemonSizeProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonSize` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.HoloPokemonSize>` |

## `Holoholo.Rpc.WithBattleOpponentPokemonProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `OponentPokemon` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.OpponentPokemonProto>` |

## `Holoholo.Rpc.OpponentPokemonProto` (size 24 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `Holoholo.Rpc.HoloPokemonId` |
| 0x014 | `Form` | `Holoholo.Rpc.PokemonDisplayProto.Types.Form` |

## `Holoholo.Rpc.WithPokemonMoveProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `MoveIds` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.HoloPokemonMove>` |

## `Holoholo.Rpc.LocationCardFeatureSettingsProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Enabled` | `System.Boolean` |

## `Holoholo.Rpc.LocationCardDisplayProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `LocationCard` | `Holoholo.Rpc.LocationCard` |

## `Holoholo.Rpc.UnlockPokemonMoveProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |

## `Holoholo.Rpc.SetPokemonTagsForPokemonProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `TagChanges` | `Niantic.Protobuf.Collections.RepeatedField<Holoholo.Rpc.SetPokemonTagsForPokemon` |

## `Holoholo.Rpc.UpdatePokemonSizeLeaderboardEntryOutProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Status` | `Holoholo.Rpc.UpdatePokemonSizeLeaderboardEntryOutProto.Types.Status` |

## `Holoholo.Rpc.TransferPokemonSizeLeaderboardEntryOutProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `Status` | `Holoholo.Rpc.TransferPokemonSizeLeaderboardEntryOutProto.Types.Status` |

## `Holoholo.Rpc.PurifyPokemonProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |

## `Holoholo.Rpc.SetBuddyPokemonProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `System.UInt64` |

## `Holoholo.Rpc.TrackedPokemonProto` (size 24 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `PokemonId` | `Holoholo.Rpc.HoloPokemonId` |

## `Holoholo.Rpc.Telemetry.EggHatchTelemetry` (size 24 bytes, 2 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `NumEggsHatched` | `System.Int32` |
| 0x014 | `NumAnimationsSkipped` | `System.Int32` |

## `Holoholo.Rpc.HoloPokemonType` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |

## `Holoholo.Rpc.HoloPokemonClass` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |

## `Holoholo.Rpc.HoloPokemonNature` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |

## `Holoholo.Rpc.HoloPokemonMovementType` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |

## `Holoholo.Rpc.HoloPokemonEggType` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |

## `Holoholo.Rpc.HoloPokemonMove` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |

## `Holoholo.Rpc.HoloPokemonId` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |

## `Holoholo.Rpc.HoloPokemonFamilyId` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |

## `Holoholo.Rpc.HoloPokemonSize` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |

## `Holoholo.Rpc.PokemonBadge` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |

## `Holoholo.Rpc.LocationCard` (size 20 bytes, 1 instance fields)

| Offset | Name | Type |
|---:|---|---|
| 0x010 | `value__` | `System.Int32` |
