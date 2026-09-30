---
name: reference-pogo-limit-detection
description: "How the catcher detects being rate-limited in game (2026-09-29) — spin OutOfRange streaks, flee streaks, GetPlayer account flags; the user's \"can't spin\" = server OutOfRange, account flags clean"
metadata:
  node_type: memory
  type: reference
  originSessionId: 565701b0-1a11-42dd-894a-3bb423b9a491
  modified: 2026-09-30T00:46:30.004Z
---

User 2026-09-29: "You need to detect in game if im rate limited. i cant spin because i am."

**What the game says (read live, 20:39):**
- GetPlayerOutProto from a fresh `PlayerService.RequestPlayerFromServer()`: Success 1, **Banned 0, Warn 0, WasSuspended 0, WarnExpireMs 0**. So there is no account warning; the limit is per action.
- `PlayerService.<UserPermissions>` is an EMPTY set. Its enum (SPONSORED_CONTENT, FRIEND_LIST, SHARED_AR_EXPERIENCES, PARTY_PLAY) has nothing about spins.
- His spins: the catcher's FortSearch hook logged `res2` (**OutOfRange**) repeatedly all day at stops he stood at. That is the server refusing ("Try again later"), i.e. position-trust.

**Offsets and codes (0.429.1):**
- GetPlayerOutProto: Success@10, Player@18, Banned@20, Warn@21, WasSuspended@24, WarnExpireMs@28.
- PlayerService keeps no reply after the promise resolves (`@148` is null); catch it by hooking the parse.
- FortSearch Result: 0 NoResultSet, 1 Success, 2 OutOfRange, 3 InCooldownPeriod, 4 InventoryFull, 5 ExceededDailyLimit, 6 PoiInaccessible.
- Other related classes: ModerationWarningService, CheatingWarningGui (WarnedPlayerReason), BannedPlayerLockoutGuiController.

**In the catcher (the LIMIT line, deployed 20:42):**
- Spins: OutOfRange twice in a row with no success = BLOCKED since HH:MM. Auto-spin then probes once per 10 min.
- Catches: FLEESTREAK on sure throws. Stale apple reveals are excluded from it.
- Account: parsed from every GetPlayer reply. The catcher asks for one at attach and hourly.
- A `LIMIT ...` log line is written whenever the state changes.

Related: [[pogo-ban-lockout-2026-09-26]], [[pogo-on-phone-catcher]], [[reference-pogo-map-tappables-apples]], [[pogo-stale-service-graph-2026-09-29]].
