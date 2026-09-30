# Keep-law handoff — culling + Transfer tagging

Written 2026-08-31 for the session taking over culling / Transfer tagging.
**Re-verified against the live code, `keep_config.json` and `pokemon.db` on 2026-09-07.**

The Transfer pile is the **one irreversible output**. Everything here exists to keep a keeper out of it.

Live numbers: bag **5,727** in-bag · pile **26** · `policy_reasons` **5,701** (5,701 + 26 = 5,727).

---

## 1. Authoritative flow — the order is law

`full_audit.py` and the dashboard's `/api/sync` both compose exactly this. There is one code path.

```
recrawl (pogo_pipeline.py + read_player_state.py)
  -> system/scripts/keep_policy.py        # decides KEEP vs pile; writes policy_reasons.json,
  |                                       #   6_Transfer.txt and pile_provenance.json
  -> system/scripts/build_tagsets.py      # turns decisions into tagset .txt files (incl. Transfer.txt)
  -> system/scripts/preflight_transfer.py # THE HARD GATE. rc != 0 aborts before any phone write.
  |                                       #   Writes the PREFLIGHT STAMP.  <-- see section 2
  -> system/scripts/prune_tags.py --atomic     # pushes to server, ADD **and** REMOVE.
  |                                            #   REFUSES without a fresh, matching stamp.
  -> system/scripts/refresh_evolve_shiny.py    # produces Evolve_Shiny.txt (NOT in prune's PLAN)
  -> system/scripts/set_db_tags_from_files.py  # writes auth_tag_names (the DB mirror) -- LAST
  -> reconcile_tags.py --report / verify_tags_live.py
```

**Do not run `prune_tags.py` as a standalone step.** It is a live, bidirectional pusher whose default
target list is the *entire* plan, `Transfer` included. Run the cycle, or run the five steps above in
order. If you must run the pusher by hand, `preflight_transfer.py` must have passed **on this exact
pile** immediately before it.

**ORDER CORRECTED 2026-09-02 — the mirror runs LAST.** This section previously listed
`set_db_tags_from_files.py` *before* the push. That is the bug it caused: `set_db` writes
`auth_tag_names` straight from the tagset FILES with no knowledge of whether the push then succeeded,
and `auth_tag_names` is exactly what `/api/tagdiff` calls "the phone's last-known tags" — so after ANY
sync, successful or not, the next preview reported "already in sync". Running it last means the DB
only ever records a push that `prune_tags` actually verified, and a non-zero step aborts the job
before it runs at all. `refresh_evolve_shiny` sits between them so its file is fresh when mirrored.

`python full_audit.py` runs the whole cycle and **refuses to sync if any audit fails**.
Flags: `--no-sync` (audit only, never touches the phone), `--skip-crawl`, `--audits-only`.

**`prune_tags.py --atomic` reconciles both directions.** It computes per-tag `remove N, add M` against
live server membership. Do not replace it with an add-only apply — that's the bug that left a stale
member on the server.

---

## 2. Why pre-flight writes an artifact, not just an exit code

`preflight_transfer.py` is the only keeper check standing between the engine and an irreversible
release. Until 2026-09-07 its verdict existed **only as a process exit code**. An exit code lives
inside one process and dies with it, so nothing downstream could distinguish:

- pre-flight ran and passed,
- pre-flight ran, failed, and somebody ran the pusher anyway,
- pre-flight was never run at all.

That is not a *bypassed* gate. It is an **unobservable** one — and the measured consequence was that
`python system/scripts/prune_tags.py`, bare, pushed all 46 planned tags including `Transfer`, live,
by default, having checked nothing about keepers. Its only gate was `ready_gate` (screen on,
foregrounded, not frozen), which is a **write-reliability** check; `--force` skips even that.

The fix is an artifact: **`system/analysis/preflight_stamp.json`** (schema 1), landed 2026-09-07.

| Field | Meaning |
|---|---|
| `pile_sha256` | sha256 of the exact `Transfer.txt` bytes pre-flight vetted |
| `pile_uids` | uid count vetted |
| `config_sha256` | `keep_config.fingerprint()` — merged config, `_note` excluded |
| `db_sha256` | `db_content_sha256` from `pile_provenance.json` |
| `generated` | UTC ISO-8601 |
| `schema` | `1` |

`preflight_transfer.py` **destroys any existing stamp as the first executable statement of a run**
and writes a new one **only** on its final PASS line — so a keeper hit, a uid missing from the DB, a
failed live gym read, an empty pile or an exception all leave no stamp *by construction*. The delete
matters more than the write: a leftover stamp authorising a pile nobody vetted is the dangerous
direction.

`prune_tags.py` refuses with **`sys.exit(2)`** on any push including `Transfer` (which the bare
no-args form does) unless the stamp exists, parses, is complete and is schema 1; `pile_sha256` equals
a **fresh** hash of the current `Transfer.txt`; `pile_uids` matches; `config_sha256` equals the live
fingerprint; `db_sha256` equals the live provenance; and `generated` is younger than **30 minutes**
(more than 120s in the future = bogus). Missing, unreadable, malformed, mismatched or stale all
refuse. Non-`Transfer` tags are unaffected.

Two properties to preserve:

- **It binds the FILE, not the DB mirror.** `Transfer.txt` and `auth_tag_names` drift by design
  (26 vs 25 right now, because the mirror only runs after a *verified* push). That lag is benign and
  self-healing; gating on it would wedge the pipeline for a non-safety reason. The file is what prune
  pushes.
- **`--force` does not bypass it**, by construction: `force` is never passed to
  `require_preflight_stamp()` and the function takes no such parameter. A battery override must never
  double as a keeper override.

It is a stamp and not a subprocess because **Frida is single-client** — shelling out to pre-flight
from inside prune would be a second attach to a device that permits one. The dashboard already runs
pre-flight as its own gate step immediately before the push.

This mirrors what the pile itself already does: `keep_policy` stamps
`system/analysis/pile_provenance.json` with `config_sha256`, `db_content_sha256`, `db_size`,
`in_bag`, `pile_count` and `pile_sha256`, and `audit_invariants` I2 checks them.

---

## 3. Live-truth artifacts

| Artifact | Meaning |
|---|---|
| `system/analysis/policy_reasons.json` | every **kept** uid -> its keep reasons |
| `system/analysis/tagsets/Transfer.txt` | the pile (engine-ordered) |
| `system/analysis/tagsets/6_Transfer.txt` | what keep_policy wrote; must be an identical uid SET |
| `system/analysis/pile_provenance.json` | the config / DB / pile fingerprints the pile was built from |

`policy_reasons.json` and `Transfer.txt` are an **exact partition** of `in_bag=1`:
`len(policy_reasons) + len(Transfer) == in_bag`, zero overlap. Assert it every run — it is the
cheapest corruption detector you have.

**Compare pile MEMBERSHIP as a uid SET, never a file hash.** `Transfer.txt` is engine-ordered, so its
bytes and its hash change on every regeneration even when membership is identical. A hash tripwire on
it fires constantly and trains you to ignore it. Diff against the sorted `6_Transfer.txt`, or
normalise both to a set.

**`cull_decision_v9` is a DEAD legacy column. Ignore it entirely.** At handoff it disagreed with the
live engine on 54 rows (47 where v9 said TRANSFER but the engine keeps). Reading it as live is what
produced the false "24 keepers are tagged" alarm.

---

## 4. The traps — things not obvious from the code

### 4a. NEVER read caps from `keep_config.DEFAULTS`. Always `keep_config.cap(name)`.
`keep_config.json` overrides the defaults. Re-read live 2026-09-07 — **5 of 11 differ**:

| cap | DEFAULTS | LIVE |
|---|---|---|
| cosmetic | 4 | **3** |
| gigantamax | 6 | **8** |
| shiny | 20 | **10** |
| rarity | 12 | **8** |
| shadow | 1 | **2** |

Unchanged from defaults: `plain_line` 3, `plain_line_preevo` 2, `dynamax` 3, `xxl` 2, `xxs` 2
(inactive — `rules.xxs` is false), `location_card` 6. Note `pvp.viability_margin` is also overridden:
DEFAULTS 100, **LIVE 0** — that one is not a cap but it decides four of the audit-6 fixtures.

Per-species overrides live in `per_species_caps`: shiny `130` (Gyarados) = **20**, cosmetic `25`
(Pikachu) = **6**; shiny `228` and `415` are set to 10, which equals the global cap and so currently
change nothing. Uncapped species: `protected_keep_all_pids` = [172 Pichu, 999 Gimmighoul],
`rarity_keep_all_pids` = [150 Mewtwo]. Legacy: `legacy_species_caps` = {359: 10}, no default cap.

Using `DEFAULTS['rarity']=12` instead of the live 8 changes which Groudon are keepers. There are also
**per-species overrides**: `keep_config.species_cap('xxl', pid, keep_config.cap('xxl'))`.

### 4b. CAPPED axes vs KEEP-ALL axes — the distinction that catches everyone
- **Keep-all** (every copy protected, no cap): hundo, nundo, AE roster, mighty, location_card,
  dex-only-copy, dex-only-form, protected species, E+F origin, `rank_unknown`.
- **Capped** (top-N kept, the rest are legitimately fodder): plain_line 3 / plain_line_preevo 2,
  cosmetic, dynamax, gigantamax, shiny, **rarity (legendaries!)**, xxl, shadow.

A legendary in the pile is **not** automatically a bug — rarity is a cap. At handoff the piled Groudon
was #14 of 15 and the only one carrying no independent axis. Same class of trap: XXL is capped
(top-N by showcase score `height*0.80 + weight*0.15 + iv*0.05`, group-normalized), so a 3rd XXL is
expected fodder.

### 4c. NULL / missing data must be treated as PROTECTED
Never cull on incomplete data. Concretely:
- **Rule 15c** (`keep_policy.py`, 2026-09-02): a row with **both** `gl_rank` and `ul_rank` NULL is
  marked `rank_unknown` and kept — "we never checked" is not "we checked and it isn't a keeper", and
  only the second may put a mon in an irreversible pile. If more than a fifth of the bag has no ranks,
  the run **aborts** instead: at that point the rank pipeline did not really run, every PvP rule is
  vacuous, and per-row protection would silently degrade into "keep almost everything" and hide it.
- Preflight **fails safe** when the gamemaster doesn't load (`gm_ok` False) — it cannot judge PvP
  viability, so it over-protects rather than guessing.
- XXL membership is read from the size category **and** the `XXL` auth tag, "so a NULL category can't
  hide one."
- `display_form` / `display_costume` are NULL-unreliable; the engine uses the `fresh_*` columns.
  **Use `fresh_natural_art_bg`, never `natural_art_background`** — the non-fresh column holds garbage on
  real rows and once fabricated a phantom background that collapsed a real shiny Gmax Lapras into the pile.

### 4d. Collapse goes UP, never down
A plain can be collapsed into a strictly-richer, strictly-higher-IV sibling. But a mon carrying **any**
collectible attribute (shiny / costume / bg / Dmax / Gmax / shadow / location card) is **never** a
collapse victim, and **trophies (hundo/nundo) are never dominators** — owning a trophy must never cost
you your only ordinary copy. The soft (collapsible) set is `{variant_floor}` only.

### 4e. Trophies never consume a capped slot
`_slot_exempt()`: hundos always, nundos when `rules.nundo` is on. They're kept unconditionally, so they
must not eat a floor slot. This is enforced in **both** floor pools.

### 4f. Shinies displace the plain floor, and win IV ties
A non-hundo shiny occupies a plain-floor slot by IV. **Unown is the exception** — it keeps a
count-based carve-out: plain cap = `LINE_CAP - (number of non-hundo shinies of that letter)`,
regardless of IV order.

### 4g. Comb-up is keyed by speciesId, never dex
Galarian and Kantonian Rapidash share dex 78. A dex-keyed pool once judged a Galarian Ponyta against
Kantonian Rapidash copies and released it. Use `pvid(species_name, form)`. Evolution targets only count
if the target has actually been **seen in the dex** (i.e. released in PoGo) — otherwise you hold mons
back for evolutions that don't exist (Farigiraf).

### 4h. "lucky" is a misnomer
The keep axis is **origin**: any trade whose `original_owner_name` is in `keep_config.origin_owners()`
(currently `ethanmateovz`, `florandez`). Lucky is not required, and luckies/trades from anyone else are
**normal** and cullable.

### 4i. Deployment must be read LIVE off the proto
`is_deployed` / `deployed_fort_id` DB columns are unreliable (empty-string sentinel). Preflight reads
gym coords live at `proto+0x140` (lat) / `proto+0x148` (lng); non-zero = deployed. A gym defender can't
be transferred, so it's safe in the pile — that's why gym-locked entries don't alarm.

### 4j. Four ways a tag WRITE lies about succeeding
All ack success while nothing lands. Full detail in [`RUNBOOK.md`](RUNBOOK.md) section 6.
- **`PokemonTagColor` is 0-8.** Colour 9 -> `AddTag` returns ok=True, tag never materialises.
- **Tag creation is server-rate-limited, and `find_tag_id_by_name` lookups share the budget.**
  Creating a plan in a loop failed for every tag after the first two. `tag_ops` now enforces an 8s
  inter-create gap, seeded at import so even the first create waits. **Deletion is separately rate
  limited** — measured at only 1-3 `DeleteTag` calls per session before it throws.
- **A `/background`-frozen PoGo accepts no writes.** Attach, singletons, bag-walk and every tag READ
  work normally; writes vanish. `ready_gate.py` checks screen + foreground + cpuset before any write.
- **`ok=True` / `built==N` is what the CLIENT accepted, not what the SERVER stored.** `create_tag`
  re-reads the tag back and is the only primitive entitled to claim success; `apply_members` /
  `apply_changes` log **ACCEPTED**. Proof is a server refetch: `reconcile_tags.py --report` or
  `verify_tags_live.py`.

### 4k. Mass `DeleteTag` in a loop deletes the wrong tags
Each deletion reorgs the `TaggingRpcService` cache and invalidates every `tagProto` pointer already
read; the next iteration deletes off a stale pointer. That is how `Mega` was destroyed and `Costume`
emptied (2026-05-28). **Always `system/scripts/safe_nuke_tags.py`** — one at a time, fresh
re-enumerate, 3s settle, then verify every non-target tag still exists with the same member count.
Never `_nuke_tags.py`. Prefer emptying a tag to destroying it.

### 4l. `pokemon.db` is WAL — compare CONTENT hashes, never mtime
A checkpoint bumps the file's mtime with the content byte-identical (observed: stamp 00:09:59 vs db
00:10:06, both 19,402,752 bytes). Any staleness check built on mtime reports a fresh pile as stale at
random. Likewise, `Transfer.txt` is engine-ordered — compare the uid set, never its hash.

### 4m. A live-but-unmanaged tag looks exactly like a dead one
`Safety Hold` (the `rank_unknown` / `data_incomplete` tag) was emitted once on 2026-09-03, then
stopped qualifying. Back when `prune_tags.PLAN` was derived by *calling* `granular_tags.build()`, a
tag with zero members vanished from the plan — while its `.txt` froze on disk and
`set_db_tags_from_files` (which consumes every file, plan or not) kept mirroring it into the DB. The
tag stayed live on the phone and invisible to the only script that could correct it, and on
2026-09-07 was nearly deleted as stale cruft. `PLAN` is now the data-independent **vocabulary**, so a
zero-member tag keeps its entry and stays managed. See `RUNBOOK.md` §4b before deleting any tag.

---

## 5. What `preflight_transfer.py` hard-gates on

Keep this gate; don't reinvent a weaker one. It **re-derives keepers independently of keep_policy** —
that's the point, it's a cross-check, not a repetition.

`sys.exit(1)` (job aborts before any phone write) when any of:
1. **REAL_KEEPER in the pile** — any pile uid that earns an unconditional keep axis and is *not*
   gym-locked. It deliberately over-protects: broader than keep_policy on lucky/traded, and fail-safe
   when the gamemaster is missing.
2. **A Transfer uid is not present in pokemon.db** — it cannot verify what it can't see.
3. **The live deployment read failed** — the gate must never print PASS for a check it did not
   perform. `--allow-no-live-deployment` accepts a DB-only verdict explicitly.

Every pile uid is classified `PLAIN` / `COSTUME_EXCESS` / `SHINY_EXCESS` / `XXL_EXCESS` /
`LEGACY_EXCESS` / `GYM_LOCKED` / `REAL_KEEPER`. Only the last one alarms. Deliberate trust boundary
(2026-06-08): the **capped** axes are not re-derived here — keep_policy owns the cap maths, and a
cap-excess copy is the user's deliberate trim.

`keep_policy.py` has its own two tripwires that raise `SystemExit`:
- a top-`READY_RANK` **CP-viable** PvP spread leaked into Transfer (the Mareep failure mode);
- a **protected** mon leaked into Transfer.

### The SIX gate audits `full_audit.py` runs in parallel

All read-only, all fast, no device contact. It gates on `rc == 0` AND each script's own verdict
substring, so changing a verdict line without updating `full_audit.AUDITS` silently disarms the gate.

| Script | Proves | Verdict substring |
|---|---|---|
| `audit_cull.py` | pile keeper-free, 8 layers | `ALL LAYERS PASS` |
| `audit_tags_membership.py` | every tag matches its rule, both directions | `ALL TAG MEMBERSHIPS CORRECT` |
| `_evocheck.py` | no piled mon improves a stage by evolving | `none of the tagged mons would improve` |
| `_lawcheck.py` | from-scratch re-derivation of the keep law | `UNEXPLAINED: 0` |
| `audit_invariants.py` | the structural model is coherent (I1–I7) | `ALL STRUCTURAL INVARIANTS HOLD` |
| `system/scripts/regress_pvp_keepers.py` | the 18 lost PvP keepers all come back KEEP **by a PvP axis** | `ALL PVP KEEPER FIXTURES KEPT` |

The first four check a RESULT and catch a wrong *answer*. `audit_invariants.py` checks the MODEL and
catches a wrong *question* — the capped-vs-keep-all class in 4b, plus **I7 stat-line fidelity**
(2026-09-07): every `(species, form)` must reproduce its **own stored CP** under the speciesId the
live ranker maps it to. CP is a pure function of base stats, IVs and CPM, so the game itself signs off
on every mapping decision; a pair that only reconstructs under a *different* speciesId was being
ranked against the wrong pokemon. That found `('Mewtwo',135)→mewtwo_armored` backwards (114 real
Armored Mewtwo falling through to plain `mewtwo`, 160 rows misranked), `('Corsola',3339)` absent
(costume on a regional form, error running in the **under-keep** direction), and
`('Slowking',2734)→slowking_galarian` wrong. None of the other six invariants could see any of them.

`regress_pvp_keepers.py` is the sixth gate and the only one that can speak for mons no longer in the
bag: it re-inserts the 18 lost spreads into a **sandbox** copy of the DB, runs the **real**
`keep_policy`, and demands each come back KEEP **and** for a PvP-class reason — because with the PvP
rules removed, 8 of them are still kept incidentally, so asserting KEEP alone would false-pass. Do not
weaken or skip either audit.

`_spotdata.py` (JSON fact-pack, ~2s) is handy but is not part of the gate. So is
`system/scripts/check_constant_drift.py` (`ALL GAME CONSTANTS SINGLE-SOURCED`) — worth running after
any edit to a ranker, since the CPM ladder, level-cap index and league caps now live only in
`cpm_table.py`.

---

## 6. The forensic finding, stated at its true size

The 2026-09-07 audit found **24** mons a correct engine would have kept; **18** were released and are
unrecoverable.

**One provable loss with a named cause:** a **Mudbray** whose `species_name` parsed as the placeholder
`"pid749"`. No `FORM_OVERRIDES` entry, no resolvable slug, so `pvid()` produced a speciesId absent
from the gamemaster, the ranker wrote NULL ranks, and the engine read "no rank" as "no PvP
protection". Its true rank was **Great League #2 of 4096 (99.65%)**. The defect class is closed by
**rule 15c** (§4c).

The other **17** predate any PvP-rank rule — the pre-2026-06-05 IV-magnitude era, the same defect that
killed the 0/13/11 GL#1 Mareep. Under a league CP cap, stat-product rank **anti-correlates** with
IV%: low attack wins, so every IV floor ever added to a PvP path rejected exactly the spreads that
rank #1. *** DO NOT REINTRODUCE AN IV GATE ON A PvP PATH. ***

**The honest evidence horizon.** 18 is a **floor, not a ceiling**. Historical DB copies exist only at
**2026-05-19, 2026-05-30, 2026-07-25, 2026-08-19, 2026-09-02** and live (plus dense `.db_snapshots/`
from 09-02 onward). There is a **56-day gap between 05-30 and 07-25**, and **nothing at all before
05-19**. Anything released in that gap, or before the first snapshot, leaves no trace we can audit.
Do not round the number up or down; say what it is.

---

## 7. Deliberately NOT automated — and why

- **Releasing/transferring.** We only ever **tag**. The human does every release in-game. Standing
  user rule: "you will never be releasing pokemon for me. just tagging for transfer."
- **XXS culling.** User: "i dont give a shit about xxs" — `rules.xxs` is false.
- **Blanket policy changes.** Never flip a cap or a rule to "keep all" to make a problem go away.
- **Deleting tags.** Outside the cycle, `safe_nuke_tags.py` only, one at a time (§4k).
- **PoGo restarts while the user is playing.** `verify_tags_live.py` self-gates on screen-on +
  PoGo-foregrounded and falls back to a cache reconcile, saying plainly that it is *not* server proof.
  `--force` exists but is for when the user explicitly asks.
- **Attaching to a cold-starting app.** `pogo_il2cpp.get_session()` refuses unless `libil2cpp.so` is
  mapped and the process is >45s old; wait with `wait_ready_to_attach()` (pure `/proc` polling — never
  attach-probe in a retry loop, each probe is a crash roll).

---

## 8. Known live quirks

- **Fresh-catch write lag.** Server tag writes on a **freshly caught** mon can silently no-op —
  `SetPokemonTags` acks OK and the binding never lands. It self-heals on the next sync. An
  off-by-small-N on Transfer means *check catch recency*, not drift. Only escalate if it repeats a
  full cycle later, or if it affects a trophy tag.
- **The tree is rewritten on a timer.** `autocull_watch.py` runs the gated cull on a 5-minute tick and
  `dashboard.py` serves the panel; both rewrite `pokemon.db` and the tagsets. Read
  `system/analysis/autocull_watch.log` and `dashboard_run.log` before blaming a script for a changed
  file.
- **A pile computed but not yet pushed looks like an untagged mon.** Right now exactly one in-bag row
  has no `auth_tag_names`: the Scorbunny caught 2026-09-07 05:25Z, already in `Transfer.txt` but not
  mirrored because the audit gate is holding the sync. Expected, not drift.
