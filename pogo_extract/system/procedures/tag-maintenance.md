# Tag maintenance

**Verified 2026-09-07.**

## Overview

**46 registered server tags** (`granular_tags.registry()`) plus **3 exempt** ones
(`Evolve Shiny`, `Armored UL`, `Armored ML`) are managed via Frida RPCs. **The normal way to change
tags is the cycle**, not the tools below:

```powershell
python full_audit.py
```

That composes `keep_policy` → `build_tagsets` → `preflight_transfer` (hard gate, writes the stamp) →
`prune_tags --atomic` → `refresh_evolve_shiny` → `set_db_tags_from_files`. Reach for the individual
tools in this file only for maintenance and recovery outside the cycle.

All write operations require PoGo **open and foregrounded** plus Frida reachable.

## Before any write: the traps

### 1. `PokemonTagColor` is 0-8. Colour 9 silently no-ops.

`AddTag` with colour 9 returns **ok=True** and the tag never materialises — it reads exactly like a
mysterious server failure. This caused three wrong diagnoses on 2026-09-02. `tag_ops.create_tag`
now raises `ValueError` on an out-of-range colour. (The `tag_ops.py` argparse help still says "0-9";
it is wrong, the validator is right.)

### 2. Creation, lookups and deletion are all rate limited.

Creating tags back-to-back fails: of 12 created in a loop, **every one after the first two** returned
ok=True and never appeared. It looks like an account tag cap. It is a server-side rate limit.

`find_tag_id_by_name` **lookups count toward the same budget** — which is why the *first* create was
the one that failed every time, after ~11 rapid lookups had already consumed it. `tag_ops` enforces
`_MIN_CREATE_GAP = 8.0s`, seeded at import (not zero), so even the first create waits.

**Deletion has a separate, much tighter limit:** measured at only **1-3 `DeleteTag` calls per session**
before `DeleteTag` starts throwing. Removing a *member* from a tag (`untag_one`) is a different RPC
and is not subject to it.

### 3. A frozen (`/background`) PoGo accepts no tag writes.

Android's cached-app freezer suspends a backgrounded PoGo in `cpuset:/background`. Writes issued
against it **never land**, while the attach, the singleton lookup, the bag walk and every tag *read*
all work normally. `ready_gate.py` checks screen-on, foreground and cpuset before any write path.
`prune_tags` runs it unless `--dry-run`; `--force` bypasses it and is only for when the user asks.

Note what `ready_gate` **is**: a write-*reliability* check. It has never had any opinion about
whether the pile contains a keeper. Do not read a passing gate as a safety verdict.

### 4. "ok=True" is what the client accepted, not what the server stored.

`create_tag` re-reads the tag back with `find_tag_id_by_name` and is the only primitive entitled to
claim success. `apply_members` / `apply_changes` cannot read back, so their return is named and
logged as **ACCEPTED**. Proof of a membership write is a genuine server refetch:
`reconcile_tags.py --report` or `verify_tags_live.py`.

Every write also needs a **fresh** bag-walk proto from the *same* Frida session — tagging a mon
reallocates its `PokemonProto`, so a pointer from an earlier walk is stale and `SetPokemonTags` throws.

## Create or apply a tag: `tag_ops.py`

Reads members from `pokemon.db` (rows whose `auth_tag_names` contains the tag name), bag-walks for
proto addresses, creates the server tag if absent, applies membership, and mirrors back to the DB.

```
python system/scripts/tag_ops.py apply "GL IV" 1
```

Arguments: `apply <TagName> <color_int>` — colour is `PokemonTagColor`, **0-8**.

Internals: warm-up probe, exponential backoff on AddTag (3/5/5/8/8/13s), 8s inter-create throttle,
batch apply (100/batch, 3 retries per batch), sacrificial warm-up call for untag to avoid the NPE.

**The pile is gated here too.** `apply` refuses for `Transfer` / `6 Transfer` unless all three hold:
`--yes-push-the-release-pile` was typed explicitly, the DB member set matches the tagset file, and
`preflight_transfer.py` runs right there and exits 0. Every other tag is unchanged — one command,
no ceremony.

**`tag_ops apply` is ADD-ONLY.** It never removes a member who stopped qualifying. That is harmless
for a label tag and dangerous for `Transfer` — on 2026-08-19 a legendary Groudon that the DB had
already dropped was still sitting on the server's Transfer tag. Use `prune_tags.py --atomic` (whole
plan, bidirectional, verifies set equality) or `prune_server_tag.py <Tag>` (one tag, removals only).

## Push the computed tagsets: `prune_tags.py`

The sanctioned push. Makes each named server tag **exactly** equal its tagset file — computes
`remove N, add M` against live membership, applies, then re-enumerates and verifies **set equality**
(counts alone can match while membership differs).

```
python system/scripts/prune_tags.py --dry-run          # preview, no writes
python system/scripts/prune_tags.py --atomic           # ALL 46 planned tags, Transfer included
python system/scripts/prune_tags.py --atomic "Hundo"   # named tags only
```

> **Do not run the bare form as a maintenance step.** With no tag arguments the target list is the
> entire plan — `Transfer` is in it, and the push is live. If you only need one label tag repaired,
> name it.

**The pile is now stamp-gated.** Any push whose targets include `Transfer` (the bare form included)
refuses with **rc 2** unless `system/analysis/preflight_stamp.json` exists, is complete and schema 1,
its `pile_sha256` equals a **fresh** hash of the current `Transfer.txt`, its `config_sha256` equals
the live `keep_config.fingerprint()`, its `db_sha256` equals the live `pile_provenance.json` value,
and its `generated` is **younger than 30 minutes**. Pre-flight destroys any old stamp at the start of
every run and writes a new one only on a full PASS, so "no stamp" means "not inspected".
**`--force` does not bypass this** — it bypasses `ready_gate` and nothing else. Non-`Transfer` tags
are unaffected. Each refusal names the real event behind it: the pile was regenerated by a recrawl, a
cap moved, or `autocull_watch` replaced the bag snapshot underneath.

Exit 0 only if every targeted tag verified as an exact set match. **Non-zero means the push did not
fully land — do not mirror it, do not call the sync done.**

It never touches `pokemon.db`. Run `set_db_tags_from_files.py` **after** it, so the mirror only ever
records a push that verified.

### Registered vs exempt vs skipped

- **Registered (46).** In `granular_tags.registry()` = the 11 `LEGACY_TAGS` plus the full label
  vocabulary. `prune_tags.PLAN` *is* this registry, so the plan is data-independent: a tag whose
  membership falls to zero **keeps its entry and stays managed**.
- **Skipped this cycle.** A registered tag with no tagset file is skipped loudly, never pushed as an
  empty set (that would strip every member off the device from a file that simply is not there).
  Today: `Paradox`, `Rare Other`.
- **Exempt (`granular_tags.EXEMPT_TAGSETS`).** Live on the device, deliberately outside PLAN:

  | File | Tag | Owner | Why |
  |---|---|---|---|
  | `6_Transfer.txt` | *(none)* | `keep_policy.py` | the raw pile, not a server tag; `build_tagsets` re-emits it as `Transfer.txt`, which IS managed |
  | `Evolve_Shiny.txt` | `Evolve Shiny` | `refresh_evolve_shiny.py` | recomputed by its own owner after every prune; outside PLAN so prune cannot fight it |
  | `Armored_UL.txt` | `Armored UL` | `push_armored_tags.py` (one-shot) | static hand-pushed snapshot; an empty derived file would strip it |
  | `Armored_ML.txt` | `Armored ML` | `push_armored_tags.py` (one-shot) | same |

  A tagset file with **neither** a plan entry **nor** an exemption **aborts** the run. That check is
  the only thing that distinguishes a live-but-unmanaged tag from dead cruft.

- **`Safety Hold` is live, not legacy.** It is the tag for a `rank_unknown` / `data_incomplete` mon —
  one the engine could not judge and therefore protected. It was emitted once (2026-09-03, one
  Enamorus), then stopped qualifying; under the old build-derived PLAN it vanished from the plan while
  its `.txt` stayed frozen on disk and kept being mirrored into the DB, so the tag stayed live on the
  phone and invisible to the only script that could correct it. On 2026-09-07 it was nearly deleted as
  stale cruft. **Check the registry and `EXEMPT_TAGSETS` before deleting any tag.**

## Delete a tag: `safe_nuke_tags.py`

```
python system/scripts/safe_nuke_tags.py --dry-run "SomeTag"
python system/scripts/safe_nuke_tags.py "SomeTag"
```

Deletes tags **one at a time** with full collateral detection: fresh re-enumerate to find the current
tagId, `DeleteTag`, sleep `SETTLE_DELAY = 3s`, then re-enumerate **all** tags and verify every
non-target still exists with the same member count — aborting immediately on any collateral.

**Why one at a time is not paranoia.** Each deletion reorgs the `TaggingRpcService` cache, which
invalidates every `tagProto` pointer a loop has already read. The next iteration then calls
`DeleteTag` on a **stale pointer** and destroys a different tag — that is exactly how `Mega` was
deleted outright and `Costume` emptied on 2026-05-28.

**NEVER use `_nuke_tags.py` in the repo root.** It is kept only as a cautionary artifact.
`delete_tags.py` has been deleted. `tag_ops.py` has no delete primitive and deliberately keeps none.

Deleting a tag is outside the normal cycle. Prefer emptying it to destroying it.

## Reconcile drift: `reconcile_tags.py`

Compares server tag membership vs DB `auth_tag_names` and reports per-tag drift. Its managed-set
allowlist is `PLAN | EXEMPT_TAGS`, so the two Armored snapshots and `Evolve Shiny` are not reported
as untracked drift forever.

```
python system/scripts/reconcile_tags.py                      # read-only diff table (default)
python system/scripts/reconcile_tags.py --tags "Hundo,XXL"   # restrict
python system/scripts/reconcile_tags.py --verbose            # show drifted UIDs
python system/scripts/reconcile_tags.py --fix-db             # DB := server (safe, no device writes)
python system/scripts/reconcile_tags.py --fix-server         # server := DB (writes to device)
```

Modes are mutually exclusive. Normal direction is server → DB. Use `--fix-server` only when the DB
is known to be more correct.

## Verify tags

```
python system/scripts/verify_tags.py    # SERVER vs DB vs RULE, per registry tag
python verify_tags_live.py              # post-sync server-truth verification
```

`verify_tags_live.py` is what the cycle runs. It self-gates on screen-on + PoGo-foregrounded and
falls back to a cache reconcile, stating plainly that the fallback is **not** server proof. `--force`
exists for when the user explicitly asks; it can restart PoGo, so never use it mid-play.

## Comparing piles

Compare `Transfer` **membership as a uid set**, never a file hash. `Transfer.txt` is written in engine
order, so its bytes and its hash change on every regeneration even when membership is identical — a
hash tripwire on it fires constantly and trains you to ignore it. Diff it against the sorted
`6_Transfer.txt`, or normalise both to a set.

Same rule for the database: `pokemon.db` is **WAL**, and a checkpoint bumps its mtime with the content
byte-identical. Compare content hashes, never mtime.

## Check DB freshness

```
python system/scripts/check_freshness.py
```

Read-only. Walks the live bag, compares UIDs to `pokemon.db in_bag=1`, prints agreement %.
Exit 0 = FRESH, 1 = RE-CRAWL NEEDED. Writes nothing.

## Known live quirk: fresh-catch write lag

Server tag writes on a **freshly caught** mon can silently no-op — `SetPokemonTags` acks OK and the
binding never lands. It self-heals on the next sync. An off-by-small-N on Transfer means *check catch
recency*, not drift. Escalate only if it repeats a full cycle later, or if it affects a trophy tag.

Related and benign: a mon that is in `Transfer.txt` but has no `auth_tag_names` yet is a pile that was
computed and not yet pushed — right now exactly one row (a Scorbunny caught 2026-09-07 05:25Z), because
the audit gate is holding the sync.
