---
name: pogo-source-of-truth-db-rules
description: "For PoGo inventory truth, query the bag DB by RULE — never trust tag membership counts or cached proto/binding state."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

For any PoGo inventory question ("how many hundos do I have?"), query the bag DB by rule — e.g. `SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND iv_total=45` — NOT the tag count. The user's server-side tags are downstream artifacts that DRIFT: members get missed when new Pokémon are caught, members linger when the criteria stops applying (badges expire), and entire tags can VANISH server-side with no user action (observed mid-session: the "Hundos" and "From Florandez" tags disappeared on their own). Same pattern for nundos (`is_zero=1`), lucky (`is_lucky=1`), shadows, etc.

This extends to cached proto/binding reads in general: three sources once disagreed on the favorite count (DB `is_favorite_v2=99` stale, proto `+0xb0=50`, `TaggingRpcService.get_FavoritesTagBinding=NULL` because it's lazy-loaded). When no verified read exists, say "can't reliably read" rather than reporting a number — don't give the user three different counts and pick one. Favorites have one since 2026-09-17: `favorite_`@0xb0 is parsed live every walk into `is_favorite_v2`; query the DB after a fresh walk.

**Why:** Tags and cached protos/bindings are server-state snapshots subject to Niantic-side mutations and client-side desyncs. Rule queries over the materialized bag DB reflect the actual current state of each Pokémon.

**How to apply:** DB rules drive corrections TO tags, never the reverse. The `audit_tags.py` direction is correct: `rule_set - tag_set` = adds needed; `tag_set - rule_set` = surplus to remove. Use tags only as *suggestions* of what should be tagged. For server-authoritative flags, prefer re-fetching inventory (`NianticInventoryCache.HandleInventoryDelta`) over reading a cached binding/proto, and verify an offset by toggling one known instance in-game and diffing bytes before asserting. Relates to [[pogo-data-completeness-before-destructive-actions]], [[pogo-server-authority]], [[project-pogo-extract]].
