# How stardust is added (Pokemon GO, RE record)

Recorded from IL2CPP RE of the live client (`holo-game.dll` / `holo-protos.dll`) on the rooted Pixel 9 Pro. Current balance at time of record: **37,133** (via `IapService.get_Stardusts`).

## Local balance storage
- Held on **`Niantic.Holoholo.Storefront.IapService`** in field `<Stardusts>k__BackingField`.
- Read: `get_Stardusts()` (0 args). Write: **`set_Stardusts(long value)`** (1 arg).
- Resolve at runtime (addresses are per-launch): `il2cpp_class_from_name('Niantic.Holoholo.Storefront','IapService')` -> `il2cpp_class_get_method_from_name('set_Stardusts',1)` -> native code pointer = `MethodInfo->methodPointer` (offset 0). Confirmed live; the singleton has 2 live instances, only one is populated (read the one whose `<Stardusts>k__BackingField` is non-zero).

## How it actually gets added (server-authoritative)
The client never mints stardust. The **server** computes and grants it; the client just applies the new total. Add paths seen in metadata:
- **Catch rewards**: capture response carries `BonusStardustCaptureReward` / `StardustAwarded` / `StardustEarned`.
- **Server-applied multipliers** (folded into the granted amount): `GlobalStardustMultiplier` (Star Piece +50%, item `StardustBoost` / `ITEM_TYPE_STARDUST_BOOST`), event/weather `StardustBonusMultiplier`, `ShadowStardustMultiplier`, `PurifiedStardustMultiplier`.
- **Quests / research**: `RewardItemStardust`, `QuestGetStardust`.
- **Gifts**: `ConvertToStardust` / `EnableGiftToStardust` (gift-to-stardust feature).
- **GBL & other currency grants**: `CurrencyUpdateProto` with `currencyGranted_` / `currencyDelta_` (`get_CurrencyGranted` / `get_CurrencyDelta`), where stardust is a currency type.

## The single apply point
All of the above converge to **`IapService.set_Stardusts(newTotal)`** updating the backing field (coins use an `add_OnCoinChange` notification; stardust follows the same pattern). Hooking `set_Stardusts` therefore captures **every** balance change = the recording hook.

## Recording live additions
`stardust_watch.py` hooks `set_Stardusts` and logs `{ts, new_total, delta (new - prior get_Stardusts), caller backtrace}` to `stardust_log.jsonl`. Run it while playing; each catch/gift/quest reward fires it. The backtrace identifies the source path.

## Important: this is observe-only
Calling `set_Stardusts` with a fabricated value does **not** persist - the balance is server-authoritative and will re-sync on the next inventory update, and client-side currency tampering is exactly what anti-cheat flags (account-ban risk). So this is for understanding/recording gains, not adding stardust.
