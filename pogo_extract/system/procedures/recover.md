# Tag recovery

**Verified 2026-09-07.** `Mega` and `Costume` in the examples below are the *historical* tags from the
2026-05-28 incident; neither exists today. The procedure is unchanged, only the names differ.

## Before you start: the traps that make recovery look broken

- **`PokemonTagColor` is 0-8.** Colour 9 makes `AddTag` return ok=True while the tag never
  materialises. `tag_ops.create_tag` rejects out-of-range colours; `_restore_tags.py` does not.
- **Tag creation is server-rate-limited, and name lookups share the same budget.** Recreating several
  tags back-to-back fails silently after the first two. `tag_ops.py` enforces an 8s inter-create gap
  (seeded at import). Prefer it over `_restore_tags.py` for multi-tag recovery, and be patient.
- **"ok=True" is what the client accepted, not what the server stored.** Only `create_tag` reads the
  tag back and is entitled to claim success. Verify a recovery with a real refetch
  (`reconcile_tags.py`), never with the apply call's own return value.

## Before you delete: is the tag actually dead?

Recovery is cheap; a wrong deletion is not, and the two look identical from outside.

- A tag can be **live on the device and unmanaged by any script**. `Safety Hold` was in exactly that
  state on 2026-09-07 and was nearly deleted as stale legacy cruft: it is the real tag for a
  `rank_unknown` / `data_incomplete` mon, emitted once on 2026-09-03 and then not re-emitted, so under
  the old build-derived `PLAN` it fell out of the plan while its `.txt` stayed frozen on disk and kept
  being mirrored into the DB.
- **Check both registries first.** `granular_tags.registry()` (46 tags — run
  `python granular_tags.py --audit`, no DB or device needed) and `granular_tags.EXEMPT_TAGSETS`
  (`6_Transfer.txt`, `Evolve_Shiny.txt`, `Armored_UL.txt`, `Armored_ML.txt` — live, owned elsewhere,
  deliberately outside PLAN). A tag in either one is **managed, not cruft**.
- **Deletion is rate limited** — measured at only 1-3 `DeleteTag` calls per session before it throws —
  and a `DeleteTag` loop deletes the *wrong* tags (see below). Prefer emptying a tag to destroying it.

## When to use

A server tag was accidentally deleted or emptied (e.g. the Mega/Costume incident
caused by `_nuke_tags.py` reading stale pointers after cache reorg).

## How recovery works

Server tags are volatile (live in the TaggingRpcService cache, backed by
Niantic's server). The DB column `auth_tag_names` is a semicolon-delimited
mirror of which tags each pokemon belongs to. As long as the DB mirror is
intact, a deleted tag can be fully reconstructed.

## Recovery procedure

### Option A: `_restore_tags.py` (quick, for known tags)

```
python _restore_tags.py "Mega:6" "Costume:4"
```

Arguments: `"TagName:color"` pairs. For each tag:
1. Queries DB for all `in_bag=1` rows where `auth_tag_names` contains the tag.
2. Bag-walks for live proto addresses.
3. Creates the tag on the server (with retries if the RPC channel is cold).
4. Applies membership in batches of 100.

### Option B: `tag_ops.py apply` (hardened, preferred for ongoing use)

```
python system/scripts/tag_ops.py apply "Mega" 6
python system/scripts/tag_ops.py apply "Costume" 4
```

Same effect but with full warm-up, exponential backoff, the inter-create throttle, per-batch retry,
and DB mirror update. **Preferred over `_restore_tags.py` for any new recovery** -- it is the only one
of the two that validates the colour and paces creation.

Note `tag_ops apply` is ADD-ONLY: it restores members but never removes stale ones. After recovering a
tag that the engine owns, run the normal cycle (`python full_audit.py`) so `prune_tags --atomic`
reconciles it in both directions.

### Option C: manual DB query + bulk_tag.js

If tag_ops.py is not available:
1. Query the DB for member UIDs:
   ```sql
   SELECT uid_hex FROM pokemon
   WHERE in_bag=1
     AND (';'||COALESCE(auth_tag_names,'')||';') LIKE '%;Mega;%';
   ```
2. Attach Frida, load `bulk_tag.js`.
3. `find_tag_id_by_name` or `add_tag_on_instance` to create.
4. Bag-walk for proto addresses, `bulk_tag_many` to apply.

## How Mega and Costume were recovered (2026-05-28)

1. `_nuke_tags.py` was used to delete redundant tags (Shiny, Shadow, etc.).
2. After deleting several tags, the internal tag list reorged. Stale pointers
   caused DeleteTag to hit Mega (deleted entirely) and Costume (emptied).
3. The DB mirror still had correct `auth_tag_names` for both tags.
4. `_restore_tags.py "Mega:6" "Costume:4"` recreated both tags and applied
   all members from the DB mirror.
5. `reconcile_tags.py` confirmed server == DB after restore.
6. `safe_nuke_tags.py` was written to prevent this class of bug permanently.

## Verification after recovery

```
python system/scripts/reconcile_tags.py --tags "Mega,Costume"
```

All restored tags should show `OK` (server count == DB count, zero drift).

## Prevention

- **Always use `safe_nuke_tags.py`** for deletions: one at a time, fresh re-enumerate, 3s settle,
  then re-enumerate ALL tags and verify every non-target still exists with the same member count.
  Each deletion reorgs the `TaggingRpcService` cache and invalidates every `tagProto` pointer already
  read, so a loop deletes off stale pointers — that is the whole mechanism behind the incident above.
- **Never use `_nuke_tags.py`** (root cause of the incident). `delete_tags.py` has been deleted.
- Keep the DB mirror current by running `python full_audit.py` (or `pogo_pipeline.py` alone) before
  any tag operations. The mirror is only trustworthy if it was written *after* a verified push -- see
  the step-order note in [`../../RUNBOOK.md`](../../RUNBOOK.md).
