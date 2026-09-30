# PoGo Curation Toolkit — Operator Runbook

**Verified against the live tree, `keep_config.json` and `pokemon.db` on 2026-09-07.**
Anything not stated here was not verified; prefer the source over an older doc.

> **The one standing rule: we only ever TAG. The user releases by hand.**
> `Transfer` is a tag, not an action. No script in the sanctioned cycle releases or transfers a
> pokemon, and none should ever be given that power.

Live numbers at time of writing: **bag 5,727 in-bag · pile 26 · policy_reasons 5,701**
(5,701 + 26 = 5,727 exactly, zero overlap).

---

## 1. The one-command cycle

```powershell
python full_audit.py
```

That is the whole cycle. It does, in order:

1. **Ensure the dashboard is up** (`dashboard.py` on `http://127.0.0.1:8765`; started automatically
   if it is not already running).
2. **Recrawl** via `POST /api/recrawl` → `pogo_pipeline.py` + `read_player_state.py`.
3. **Run all six audits concurrently** (read-only SQLite, no device contact).
4. **HARD GATE** — if *any* audit fails, the sync does **not** run.
5. **Sync** via `POST /api/sync` — recomputes the pile, runs the pre-flight gate, pushes, mirrors.
6. **Verify** with `verify_tags_live.py`.

### Flags

| Flag | Effect |
|---|---|
| *(none)* | Full cycle: recrawl → audits → gate → sync → verify |
| `--no-sync` | Recrawl + audit only. **Never touches the phone's tags.** |
| `--skip-crawl` | Audit the DB as it stands (no recrawl) |
| `--audits-only` | Just the six audits, in parallel; exit non-zero if any fails |

Use `--no-sync` or `--audits-only` for any "is the pile still sane?" question. Neither can write a tag.

---

## 2. The six audits, and what each one proves

`full_audit.py` gates on **both** `rc == 0` **and** the audit's own verdict substring — a crashed
subprocess that prints nothing is not a pass. All six are read-only, take seconds, and touch no device.

| # | Audit | Script | What it PROVES | Passing line must contain |
|---|---|---|---|---|
| 1 | 8-layer cull | `audit_cull.py` | The pile is keeper-free across eight independent layers | `ALL LAYERS PASS` |
| 2 | tag membership | `audit_tags_membership.py` | Every tag's membership matches its rule — **both** directions (no non-qualifier in, no qualifier out) | `ALL TAG MEMBERSHIPS CORRECT` |
| 3 | evo comb-up | `_evocheck.py` | No piled mon would beat your best copy of a later stage if evolved (IV survives evolution) | `none of the tagged mons would improve` |
| 4 | law re-derive | `_lawcheck.py` | Every piled mon reduces to a named reason under the keep law, re-derived from scratch (**not** from the engine's own `policy_reasons.json`) | `UNEXPLAINED: 0` |
| 5 | structural inv. | `audit_invariants.py` | The *model* is coherent: no axis capped in one file and keep-all in another, no column read that nothing writes, no stale enum, one gated push path, and every stat line reproduces its own stored CP | `ALL STRUCTURAL INVARIANTS HOLD` |
| 6 | pvp keepers | `system/scripts/regress_pvp_keepers.py` | The 18 historically-lost PvP keepers all come back **KEEP, by a PvP axis**, under today's engine | `ALL PVP KEEPER FIXTURES KEPT` |

Audits 1–4 check a **result** and will catch a wrong *answer*. Audits 5 and 6 exist because that is
not enough.

### What audit 5 (`audit_invariants.py`) adds

It checks the **model**, so it is the only one that can catch a wrong *question*. Seven invariants:

| ID | Invariant | Asserts |
|---|---|---|
| I1 | AXIS CONSISTENCY | Every keep axis is modelled the same way (capped vs keep-all) by every consumer; every cap comes from `keep_config.cap()` / `species_cap()`, never a literal |
| I2 | STALENESS | Form enum covers the live max form id; the gamemaster resolves every live `(species, form)`; the pile's provenance stamp matches the live config and DB; no input is newer than the pile |
| I3 | NULL DIRECTION | No engine-read column turns a NULL into the *unprotected* value; no pile producer reads a legacy column that has a `fresh_*` twin |
| I4 | NO-WRITER COLS | No engine-read column lacks a writer in the sanctioned pipeline (the `special_bg_id` pattern) |
| I5 | PARTITION | `policy_reasons` + `Transfer` is an exact partition of `in_bag`, zero overlap, no strays, no keep tag holding a pile member |
| I6 | SINGLE PUSH PATH | Exactly one gated path from a pile to the phone, and the dashboard's gate still precedes its push in every job |
| I7 | STAT-LINE FIDELITY | **New 2026-09-07.** Every `(species, form)` in the bag reproduces its **own stored CP** under the speciesId the live ranker maps it to; one species map and one CPM ladder across both rankers; and a mon whose species did not resolve (NULL ranks) is PROTECTED, never read as "no protection" |

**Why I7 is a real invariant and not a nicety.** CP is a pure function of base stats, IVs and CPM:

```
CP = max(10, floor((atk+ia)*cpm * sqrt((def+id)*cpm) * sqrt((sta+is)*cpm) / 10))
```

The game computed the CP it stored using the stat line *it* believes the mon has, so every row in the
bag carries a signed receipt for the ranker's mapping decision. If our speciesId cannot reproduce that
CP at any level and a different speciesId on the same dex number can, the mon was ranked against the
wrong pokemon — and every PvP protection derived from it is a number nobody ever computed. It was not
"checked and found unremarkable"; it was **never checked**. Restoring the pre-fix mapping table makes
I7 independently rediscover all three real defects it was built from:

- `('Mewtwo', 135) → mewtwo_armored` — **backwards**. Form 133 is Armored (182/278/214), 135 is
  Normal (300/182/214), and there was no `('Mewtwo', 133)` key at all, so 114 real Armored Mewtwo
  fell through to plain `mewtwo`. 160 rows ranked off the wrong stat line.
- `('Corsola', 3339)` — **absent**. A costume on a *regional* form; its CP/HP reproduce only under
  `corsola_galarian`. Galarian is the bulkier one, so the error ran in the under-keep direction. 3 rows.
- `('Slowking', 2734) → slowking_galarian` — **wrong**. `Slowking2022` is an event re-release of the
  plain form; only `slowking` reproduces. 2 rows.

CP **decides**; HP only corroborates (the HP columns carry current, battle-damaged hit points on an
unknown subset of rows). The reconstruction solves for the level rather than trusting the stored
`level` / `cp_multiplier`, so "no level reproduces this CP" is a statement about the base stats.

### What audit 6 (`regress_pvp_keepers.py`) adds

The five above all judge the **current** bag. None of them can speak for a mon that is no longer in
it. This one can: it encodes the **18 real IV spreads we provably lost**, inserts them into a
**sandbox copy** of the bag, runs the **real current `keep_policy`**, and demands every one come out
KEEP *by a PvP-class axis* (`pvp_rank` / `gl_iv` / `ul_iv` / `pvp_spread`, or `rank_unknown` for the
Mudbray). Currently **18/18**.

Two things make it a real gate rather than a comfort blanket:

- **KEEP alone is not enough.** With the PvP rules removed, 8 of the 17 are still kept by an
  incidental `evolve` / `variant_floor` reason. Asserting KEEP would false-pass on half of them, so
  the reason set is asserted too. Deleting rule 15c makes it fail on the Mudbray, as it should.
- **It is sandboxed.** The live `pokemon.db` is opened read-only and copied via SQLite's backup API;
  `keep_policy`'s `DB` / `TD` / `ROOT` / `__file__` are repointed into a temp tree and asserted to
  live under it before `main()` runs, so the live pile, `policy_reasons.json`, `pile_provenance.json`
  and `fodder_oracle.json` cannot be written. No Frida, no ADB, no network.

**Auditor's caveat before "fixing" a failure:** 14 of the 18 are keepers under any viability margin.
Four (three Abra, one Wailmer) qualify only because `keep_config` `pvp.viability_margin` is currently
**0**. Raise it to 100 and those four stop qualifying — because the *policy* changed, not because the
engine broke. Those four carry `margin_sensitive=True` and the script says so in its failure text.

> Those verdict substrings are load-bearing. Editing an audit's final line without updating
> `full_audit.AUDITS` silently disarms the gate.

**Not part of the gate, but useful:** `_spotdata.py` (a ~2s read-only JSON fact-pack) and
`system/scripts/check_constant_drift.py` (asserts every game constant has exactly one definition;
prints `ALL GAME CONSTANTS SINGLE-SOURCED`).

---

## 3. The manual path — the required order

Use this when you need to run a stage in isolation. The dashboard and `full_audit.py` compose the
exact same scripts, so there is only one code path. **The order is law, not style.**

```powershell
python system/scripts/keep_policy.py            # 1. decide KEEP vs pile
python system/scripts/build_tagsets.py          # 2. decisions -> tagset .txt files
python system/scripts/preflight_transfer.py     # 3. HARD GATE. Writes the preflight STAMP.
python system/scripts/prune_tags.py --atomic    # 4. push to the phone (refuses without a fresh stamp)
python system/scripts/refresh_evolve_shiny.py   # 5. rebuild Evolve Shiny (not in prune's PLAN)
python system/scripts/set_db_tags_from_files.py # 6. mirror auth_tag_names — LAST, after a verified push
```

| # | Script | What it does |
|---|---|---|
| 1 | `keep_policy.py` | Decides KEEP vs pile. Writes `system/analysis/policy_reasons.json` (kept uid → reasons), `system/analysis/tagsets/6_Transfer.txt` (its internal pile) and `system/analysis/pile_provenance.json` (the config + DB fingerprints the pile was built from). Two `SystemExit` tripwires: a CP-viable top-`READY_RANK` PvP spread in Transfer, or a protected mon in Transfer. |
| 2 | `build_tagsets.py` | Turns those decisions into the tagset `.txt` files, including the server-facing `Transfer.txt`. |
| 3 | `preflight_transfer.py` | Independent second opinion. Re-derives **every** keep axis straight from `pokemon.db`, reads gym deployment **live** off the proto, exits 1 on any real keeper in the pile, and on a full PASS writes `system/analysis/preflight_stamp.json`. Mutates nothing else. |
| 4 | `prune_tags.py --atomic` | Pushes to the server. **Refuses with rc 2** if the push includes `Transfer` and the stamp is missing, stale (>30 min) or does not match the live pile / config / DB. Bidirectional — computes `remove N, add M` per tag against live membership, then re-enumerates and verifies **set equality**. Exit 0 only if every tag matched exactly. |
| 5 | `refresh_evolve_shiny.py` | Rebuilds `Evolve_Shiny.txt` and pushes it. It is deliberately outside `prune_tags.PLAN`, so nothing else repairs it. |
| 6 | `set_db_tags_from_files.py` | Mirrors the tagset files into the DB's `auth_tag_names`. DB-only, no device. |

### 3a. Why the stamp exists

`preflight_transfer.py` is the only keeper check standing between the engine and the one irreversible
output. Until 2026-09-07 its verdict existed **only as an exit code** — and an exit code lives inside
one process and dies with it. Nothing downstream could tell the difference between:

- pre-flight ran and passed,
- pre-flight ran and failed but somebody ran the pusher anyway,
- pre-flight was never run at all.

That is not a bypassed gate; it is an **unobservable** one. `python system/scripts/prune_tags.py`
with no arguments pushes every planned tag, `Transfer` included, live, and the only thing it checked
was `ready_gate` — which is a **write-reliability** check (screen on, foregrounded, not frozen), not
a keeper check. `--force` skips even that.

The fix is an **artifact**: `system/analysis/preflight_stamp.json` (schema 1), landed 2026-09-07.
An exit code vanishes; an artifact can be re-read, hashed and compared by any later step, by an
audit, and by a human reading the tree tomorrow.

**The contract, shared verbatim by both halves:**

| Field | Meaning |
|---|---|
| `pile_sha256` | sha256 of the **exact bytes** of `Transfer.txt` that pre-flight vetted |
| `pile_uids` | how many uids it vetted (a cheap human cross-check) |
| `config_sha256` | `keep_config.fingerprint()` — the **merged** config, `_note` excluded, not file bytes |
| `db_sha256` | the `db_content_sha256` from `pile_provenance.json` |
| `generated` | UTC ISO-8601 timestamp |
| `schema` | `1` |

**Producer** (`preflight_transfer.py`): destroys any existing stamp as the **first executable
statement** of a run, and writes a new one **only** on the final PASS line. Every other path — a
REAL_KEEPER, a uid missing from the DB, a failed live gym read, an empty `Transfer.txt`, an
exception — therefore leaves no stamp *by construction*. The delete is the load-bearing half: a
leftover stamp authorising a pile nobody vetted is the dangerous direction, so the invalidation runs
above even the argument parsing and never fails silently. A stamp that cannot be written is not a
pile failure — absence is already the safe state — but it is printed loudly, because `prune_tags`
will then refuse.

**Consumer** (`prune_tags.py`, `require_preflight_stamp()`): any push whose targets include
`Transfer` — **and the default no-args push does** — refuses with **`sys.exit(2)`** unless *all* of:
the stamp exists, parses, is complete and is schema 1; `pile_sha256` equals a **fresh** hash of the
current `Transfer.txt`; `pile_uids` matches its uid count; `config_sha256` equals the live
`keep_config.fingerprint()`; `db_sha256` equals the live provenance value; and `generated` is
younger than **30 minutes** (a timestamp more than 120s in the future is treated as bogus, since an
unaged stamp would never expire). Missing, unreadable, malformed, mismatched or stale all refuse.
Non-`Transfer` tags are unaffected — repairing one label tag needs no ceremony.

Matching, not merely present, is the whole point: a stale stamp from an earlier pile is exactly the
failure a bare "did pre-flight run?" flag would wave through. Each mismatch names a real event — the
pile was regenerated by a recrawl, a cap moved, or `autocull_watch` replaced the bag snapshot
underneath.

Two design notes worth keeping:

- **The stamp binds the FILE, not the DB mirror.** `Transfer.txt` and `auth_tag_names` drift by
  design (right now 26 vs 25, because the mirror only runs after a *verified* push). That lag is
  benign and self-healing; keying the gate off it would wedge the pipeline for a reason that has
  nothing to do with keeper safety. The file is the exact thing prune pushes.
- **`--force` does not bypass it.** `--force` bypasses `ready_gate` and nothing else, enforced by
  construction: `force` is never passed to `require_preflight_stamp()` and the function takes no
  such parameter. A battery override must never double as a keeper override.

It is a stamp rather than a subprocess because **Frida is single-client** — shelling out to
pre-flight from inside prune would be a second attach to a device that permits exactly one. The
dashboard already runs `preflight_transfer.py` as its own gate step immediately before the push.

Same reasoning as `pile_provenance.json`, which is why the pile itself already carries
`config_sha256` and `db_content_sha256` and why `audit_invariants` I2 checks them.

### 3b. Why the mirror runs LAST

Corrected 2026-09-02, in the code and in this runbook. `set_db_tags_from_files.py` writes
`auth_tag_names` straight from the **files**, with no knowledge of whether the push succeeded.
`auth_tag_names` is exactly what the dashboard's `/api/tagdiff` calls "the phone's last-known tags".
Run it *first*, and every sync — successful or not — reports "already in sync" on the next preview.

It runs last, after `prune_tags` has verified the push, so the DB only ever records a push that
actually landed. A non-zero step aborts the dashboard job, so a failed push never gets mirrored.
`refresh_evolve_shiny` sits between them so its file is fresh by the time it is consumed.

The full push sequence the dashboard's `/api/sync` uses is:

```
keep_policy -> build_tagsets -> preflight_transfer -> prune_tags --atomic
            -> refresh_evolve_shiny -> set_db_tags_from_files
```

### 3c. Dry runs

`python full_audit.py --no-sync` is the safe read-only cycle. If you dry-run the push directly, note
that `prune_tags.py --dry-run` covers only prune; the dashboard's dry mode also passes `--dry-run` to
`refresh_evolve_shiny.py` and skips the mirror entirely, so `auth_tag_names` stays an honest record of
what the phone actually has.

---

## 4. The tag scheme

**46 registered tags + 3 exempt server tags.** `granular_tags.registry()` is the single registry:
6 historical tags (`granular_tags.LEGACY_TAGS`; `system/tags/registry.json` is regenerated from it) plus the full
label **vocabulary** `build()` can emit. `prune_tags.PLAN` *is* that registry — derived, not
restated, so `build_tagsets` and `prune` can never disagree about a filename again. If the derivation
fails, `prune_tags` **exits loudly** rather than pushing a silently-short plan.
`python granular_tags.py --audit` prints the whole registry offline — no DB, no device.

The 6 historical tags keep their original filenames and colours — they already exist on the device,
and renaming one would orphan its members:

`XXL` · `Hundo` · `Nundo` · `Traded by E+F` · `Legacy Moves` · `Transfer`

The other 24: `Adventure Effect`, `Evo GL Rank 1`, `Evo GL Rank 2-5`, `Evo UL Rank 1`, `Evo UL Rank 2-5`,
`Evolve Next`, `Evolve Twice`, `GL Rank 1`, `GL Rank 2-5`, `Last Copy`, `Never Cull`, `Paradox`, `PvP Spread`,
`Rare Other`, `Safety Hold`, `Shiny #4+`, `Shiny - Only One`, `UL Rank 1`, `UL Rank 2-5`, `Ultra Beast`,
`Variant #1`, `Variant #2`, `Variant #3`, `Variant #4+`.

**Native filter chips are labels too (2026-09-09).** Legendary, Mythical, Shiny, Shadow, Event, Location/Special
Background and Adventure Effect chips match the DB counts exactly, so the engine emits no tag for those reasons
(`granular_tags.NATIVE_COVERED_REASONS`); a kept mon whose only reasons are native-covered is explained by the
chip plus the absence of Transfer. `Adventure Effect` (ours) = the FORM that has the effect, 38 mons, like the chip.

**Retired 2026-09-09** (user: "too many tags and some are redundant" -> "drop 13 + gate" -> "re-eval all the
tags"), `granular_tags.RETIRED_TAGS`: `Evolve 1`/`Evolve 2` (identical to Evolve Next/Twice), `XXL #1`/`XXL #2`
(= XXL), `Shadow Best GL`/`Shadow Best UL`/`Shadow IV #1`/`Shadow IV #2` (-> `Shadow`), `Location Card #1-3`/
`#4-6` (-> `Location Card`), `Best GL`/`Best UL` (a "best copy" per species, ~1,900 chips), `GL IV`/`UL IV` (the
Rank tags say why), `Mighty` (one member; folded into `Never Cull`). A retired tag: no file (build_tagsets deletes a
stale one), members STRIPPED on the device by prune, empty shell deleted by `retire_tags.py` up to 3 per cycle
(DeleteTag is rate-limited, 1-3 per session; mass deletes once destroyed `Mega`). Keep decisions did not move.

**Rank tags are per STAGE (2026-09-08).** `GL Rank 1` / `GL Rank 2-5` (and UL) are the mon's OWN-stage
stat-product rank at the L50 ceiling -- the number the Pokemod overlay prints for the mon on screen.
`Evo GL Rank 1` / `Evo GL Rank 2-5` (and UL) mean a LATER stage of its line reaches that rank: evolve it
to get there. A 0/15/15 Raboot is `Evo GL Rank 1` (Cinderace #1) and NOT `GL Rank 1` (Raboot is #7).
Rank tags are GATED to stages that can reach the league cap (2026-09-09): an under-cap species pins every IV to
L50 and its hundo ranks "#1" -- true, printed by Pokemod, useless (`UL Rank 1` sat on 352 mons, 89% hundos).

**Empty-set contract (2026-09-09).** `build_tagsets` writes a file for EVERY registered tag — an EMPTY file
when nobody qualifies — so `prune` pushes want=<empty> and strips stale members. A file that is *missing* still
means "the producer did not run: do not touch" (prune skips it loudly); *present and empty* means "the engine
says nobody qualifies". `prune` never CREATES a device tag for an empty want (`Paradox`, `Rare Other`, `Safety
Hold` stay off the phone until someone qualifies). Before this, `Safety Hold` sat on an Enamorus for 5 days:
`build()` stopped emitting it, its 2026-09-03 file was never rewritten, and prune pushed the stale file every
cycle ("Why is it tagged in safety hold and never resolved?").

### 4a. What is deliberately OUTSIDE the prune plan, and why

Registered in `granular_tags.EXEMPT_TAGSETS`. A tagset file with **neither** a plan entry **nor** an
exemption aborts the run — that check is the only thing that catches a live-but-unmanaged tag.

| File | Server tag | Owner | Why it is exempt |
|---|---|---|---|
| `6_Transfer.txt` | *(none)* | `keep_policy.py` | The raw pile, **not** a server tag. `build_tagsets` reads it and re-emits it as `Transfer.txt`, which **is** managed. There is no `6_Transfer` tag on the device; it must never be pushed. |
| `Evolve_Shiny.txt` | `Evolve Shiny` | `refresh_evolve_shiny.py` | A candy-upgrade advisory list, recomputed and pushed by its own owner after every prune. Outside PLAN so prune cannot fight its owner over membership. `reconcile_tags` allowlists it for the same reason. |
| `Armored_UL.txt` | `Armored UL` | `push_armored_tags.py` (one-shot) | A **static** snapshot of the Armored Mewtwo UL picks, pushed once by hand. Nothing recomputes it, so an empty derived file would strip it. |
| `Armored_ML.txt` | `Armored ML` | `push_armored_tags.py` (one-shot) | Static snapshot, same as above. |

### 4b. `Safety Hold` — a live tag that is not dead cruft

`Safety Hold` is the tag `keep_policy` emits for a `rank_unknown` / `data_incomplete` mon: one the
engine could not judge and therefore protected. It is **in the plan**, not exempt — and that is the
2026-09-07 fix.

It was emitted on 2026-09-03 for one Enamorus and pushed. The mon's reasons then changed to
`dex_only_copy` / `rarity` / `variant_floor`, so `build()` stopped emitting it. Back when `PLAN` was
derived by *calling* `build()` and taking the keys, the tag's membership falling to zero made it
**vanish from PLAN** — while `build_tagsets` left `Safety_Hold.txt` frozen on disk at 1 uid and
`set_db_tags_from_files` (which consumes every `.txt`, plan or not) kept mirroring that frozen file
into `auth_tag_names`. The tag stayed live on the phone and in the DB and became invisible to the one
script that could ever correct it. On 2026-09-07 it was nearly deleted as stale legacy cruft; only a
file-existence check caught it.

`PLAN` is now the data-independent **vocabulary**, so a zero-member tag keeps its plan entry and stays
managed. **A live-but-unmanaged tag and a dead tag look identical from the outside** — the registry
plus `EXEMPT_TAGSETS` is what tells them apart. Before deleting any tag, check both.

### 4c. Transfer is the only pile

`Transfer` is the one irreversible output — the human reads it and mass-transfers those uids in-game.
Every other tag is a label.

Two files must always describe the identical uid set:

| File | Meaning |
|---|---|
| `system/analysis/tagsets/6_Transfer.txt` | what `keep_policy` decided |
| `system/analysis/tagsets/Transfer.txt` | what gets pushed as the `Transfer` tag |

And `policy_reasons.json` + `Transfer.txt` are an **exact partition** of `in_bag=1`:

```
len(policy_reasons) + len(Transfer) == in_bag      # currently 5701 + 26 == 5727
```

with zero overlap. Assert it every run — it is the cheapest corruption detector available.

**Compare pile MEMBERSHIP as a uid SET, never a file hash.** `Transfer.txt` is written in engine
order, so its bytes and its hash change on every regeneration even when the membership is identical.
Diff it against the sorted `6_Transfer.txt`, or normalise both to a set. A hash tripwire on
`Transfer.txt` fires constantly and teaches you to ignore it.

**`cull_decision_v9` is a dead legacy column. Ignore it entirely.** It disagrees with the live engine,
and reading it as current is what produced a false "24 keepers are tagged" alarm.

### 4d. Coverage

Every in-bag mon should carry at least one tag. Right now **one row does not**: the Scorbunny
`c25b64a0bed60e9a` (10/14/13, CP 598) caught 2026-09-07 05:25Z. It is in `Transfer.txt` but the pile
has not been pushed since (the audit gate is holding), so `auth_tag_names` has not been mirrored for
it yet. That is the expected shape of "pile computed, not yet pushed" — not drift.

---

## 5. Caps and species exceptions

**Never read a cap from `keep_config.DEFAULTS`. Always `keep_config.cap(name)`** — and
`keep_config.species_cap(axis, pid, default)` where a per-species override may exist.
`keep_config.json` overrides the defaults and **5 of 11 currently differ**. Hardcoding one, or using
a global cap where a per-species override exists, makes a report lie about the pile immediately
before an irreversible mass release. That is the recurring bug class here.

Live values, read from `keep_config.json` on 2026-09-07:

| Axis | Live cap | Engine default | Note |
|---|---|---|---|
| `plain_line` | **3** | 3 | top-N plain per (species, form, gender) by IV — FINAL stages. **Pattern-pooled lines** (`pattern_line_pools`, today Scatterbug/Spewpa/Vivillon) use ONE `plain_line` pool per pattern across the WHOLE line (all Jungle Scatterbug + Spewpa + Vivillon share 3 slots; user 2026-09-08) — see `pattern_pools.py` |
| `plain_line_preevo` | **2** | 2 | tighter cap for MIDDLE stages only (can evolve AND has a pre-evolution); base and final stages use `plain_line` (user 2026-09-13); not applied inside a pattern pool |
| `cosmetic` | **3** | 4 | costume / art bg / decoration bucket |
| `dynamax` | **3** | 3 | bread=1 |
| `gigantamax` | **8** | 6 | bread=2 |
| `shiny` | **8** | 20 | per (species, form); 10 -> 8 by the user 2026-09-17 |
| `rarity` | **8** | 12 | legendary / mythical / UB / paradox |
| `rarity_floor_iv` (top-level key) | **37** | 37 | 3-star floor: any roster legendary / mythical / UB / paradox at or above this IV total is kept regardless of the cap, shiny-cap overflow included (user 2026-09-13); 46 = off |
| `xxl` | **2** | 2 | top-N by showcase score, size=5 |
| `xxs` | **2** | 2 | **inactive** — `rules.xxs` is false |
| `shadow` | **2** | 1 | per (species, cf), plus always best-GL + best-UL |
| `location_card` | **6** | 6 | |

### Per-species cap overrides

`keep_config.json` → `per_species_caps`:

| Axis | pid | Cap | Note |
|---|---|---|---|
| shiny | 130 (Gyarados) | **20** | the only override that actually changes anything |
| shiny | 228 | 10 | equal to the global cap — currently a no-op |
| shiny | 415 | 10 | equal to the global cap — currently a no-op |
| cosmetic | 25 (Pikachu) | **6** | |

Legacy has its own per-species table: `legacy_species_caps = {359: 10}`, `legacy_default_cap = null`
(i.e. no cap by default).

### Uncapped species

| pid | Species | Source key |
|---|---|---|
| 172 | Pichu | `protected_keep_all_pids` |
| 999 | Gimmighoul | `protected_keep_all_pids` |
| 150 | Mewtwo | `rarity_keep_all_pids` |

### Capped axes vs keep-all axes

The distinction that catches everyone:

- **Keep-all** (every copy protected, no cap): hundo, nundo, Adventure-Effect roster, mighty,
  location_card, dex-only-copy, dex-only-form, protected species, E+F origin, `rank_unknown`.
- **Capped** (top-N kept, the rest are legitimately fodder): `plain_line` / `plain_line_preevo`
  (pattern-pooled lines: one `plain_line` pool per pattern across the line, no comb-up),
  cosmetic, dynamax, gigantamax, shiny, **rarity (legendaries!)**, xxl, shadow.

A legendary in the pile is **not** automatically a bug — rarity is a cap. Likewise a 3rd XXL.

Other live rosters: `adventure_effect_pids = [483, 484, 646, 800, 888, 889, 890]`,
`origin_owners = ["ethanmateovz", "florandez"]`, `pvp.ready_rank = 5`, `pvp.viability_margin = 0`,
`pvp.gl_floor = 1400`, `pvp.ul_floor = 2400`, `pvp_spread_keep = [[0, 15, 15]]`,
`showcase_weights = height 0.80 / weight 0.15 / iv 0.05`.

---

## 6. Known traps

Incidents, not theory. Each of these cost real debugging time.

### 6a. `PokemonTagColor` is 0–8. Colour 9 silently no-ops.

`AddTag` with colour 9 returns **ok=True** and the tag never materialises. This produced three wrong
diagnoses on 2026-09-02 before it was found. `tag_ops.create_tag` now rejects out-of-range colours up
front (`ValueError`). Note that the `tag_ops.py` argparse help string still says "0-9" — it is wrong;
the validator is right.

### 6b. Tag creation, tag lookups and tag DELETION are all rate limited.

- **Creation.** `prune_tags` creates its whole plan in a loop. Creating 12 tags that way, **every one
  after the first two failed** — `AddTag` returned ok=True and the tag never appeared. It reads
  exactly like an account tag cap and was misdiagnosed as one. It is a server-side rate limit.
- **Lookups share the same budget.** `find_tag_id_by_name` counts toward it. `prune_tags` resolves
  ~11 existing tags with rapid lookups and then fires the first create instantly — so the *first*
  create was the one that failed every time. `tag_ops` enforces `_MIN_CREATE_GAP = 8.0s`, **seeded at
  import time, not zero**, so even the first create waits out the gap.
- **Deletion has its own limit.** Measured: only **1–3 `DeleteTag` calls succeed per session** before
  `DeleteTag` starts throwing. `tag_ops` has no delete primitive and deliberately keeps none.

Removing a *member* from a tag (`untag_one`) is a different RPC and is **not** subject to the
`DeleteTag` limit.

### 6c. Mass `DeleteTag` in a loop causes COLLATERAL deletes. Always use `safe_nuke_tags.py`.

Deleting a tag reorgs the `TaggingRpcService` cache, which invalidates every `tagProto` pointer the
loop already read. The next iteration then calls `DeleteTag` on a **stale pointer** and destroys a
different tag. That is how `Mega` was deleted outright and `Costume` emptied on 2026-05-28.

`system/scripts/safe_nuke_tags.py` is the only sanctioned deletion path: one tag at a time, fresh
re-enumerate to find the target's current id, delete, sleep `SETTLE_DELAY = 3s`, then re-enumerate
**all** tags and verify every non-target still exists with the same member count — aborting
immediately on any collateral. **Never use `_nuke_tags.py`** in the repo root; it is kept only as a
cautionary artifact. Prefer emptying a tag to destroying it.

### 6d. A frozen (`/background`) PoGo accepts no tag writes.

Android's cached-app freezer parks a backgrounded PoGo in `cpuset:/background` and suspends it. A
write issued against a frozen process **never lands** — but the Frida attach succeeds, the singleton
resolves, and the bag-walk and every tag *read* work fine, so everything looks healthy. A foreground
app sits in `/top-app` or `/foreground`.

`ready_gate.py` checks this (along with screen-on and foreground) before any tag-write path.
`prune_tags` runs the gate unless `--dry-run`; `--force` bypasses it and is only for when the user
explicitly asks. **Reads are unaffected** — only writes. And note what the gate *is*: a
write-**reliability** check. It has never had any opinion about whether the pile contains a keeper.

### 6e. `pokemon.db` is WAL. Compare CONTENT hashes, never mtime.

A SQLite checkpoint rewrites the main database file and bumps its mtime while the content is byte-for-byte
unchanged (observed: stamp 00:09:59 vs db 00:10:06, both 19,402,752 bytes). Any staleness check built
on mtime will report a fresh pile as stale, forever and at random. Hash the content.

Related: merely *opening* a WAL database as a reader updates `pokemon.db-shm`, SQLite's shared-memory
index. `audit_invariants` documents this explicitly rather than leaving it as a rounding error,
because "this audit writes nothing" is a claim the user relies on when running it mid-transfer.

### 6f. `Transfer.txt` is engine-ordered. Never tripwire on its hash.

Its bytes change on every regeneration even when membership is identical. Compare the uid **set**, or
diff against the sorted `6_Transfer.txt`. See §4c.

### 6g. The capped-axis-vs-keep-all bug class.

The recurring one. An axis modelled as a **cap** in one file and as **keep-all** in another (or the
reverse). It has surfaced here one bug at a time, each found only after it nearly cost a real keeper:
costume bucket, XXL, Dynamax, Gigantamax, shiny floor-displacement, the Unown carve-out, shadow, and
rarity-skips-shiny. Same family: `special_bg_id`, a garbage column with **no writer**, read at four
engine sites; and `form_enum.json` going stale so brand-new costume forms were judged as plain.

The result-checking audits are structurally blind to this — they re-derive the same wrong question.
`audit_invariants.py` exists specifically to assert the model instead of the membership. **Do not
weaken or skip it.**

### 6h. Tag writes on a freshly-caught mon can silently no-op.

`SetPokemonTags` acks OK and the binding never lands. It self-heals on the next sync. An off-by-small-N
on Transfer means *check catch recency*, not drift. Escalate only if it repeats a full cycle later, or
if it affects a trophy tag.

### 6i. `fresh_*` columns only.

`display_form` / `display_costume` are NULL-unreliable. Use `fresh_natural_art_bg`, **never**
`natural_art_background` — the non-fresh column holds garbage on real rows and once fabricated a
phantom background that collapsed a real shiny Gmax Lapras into the pile.

### 6j. Deployment must be read LIVE off the proto.

The `is_deployed` / `deployed_fort_id` DB columns are unreliable (empty-string sentinel).
`preflight_transfer.py` reads gym coords live at `proto+0x140` (lat) / `proto+0x148` (lng); non-zero =
deployed. A gym defender cannot be transferred, so it is safe in the pile — that is why gym-locked
entries are reported but do not alarm.

### 6k. `ok=True` / `built==N` is not proof of persistence.

Every tag RPC reports what the **client** accepted, not what the **server** stored. `create_tag` is
the only primitive entitled to claim success, because it re-reads the tag back with
`find_tag_id_by_name`. `apply_members` / `apply_changes` cannot read back, so their return value is
named and logged as **ACCEPTED**. The proof of a membership write is a genuine server refetch:
`reconcile_tags.py --report`, or `verify_tags_live.py`.

Relatedly: every write needs a **fresh** bag-walk proto from the *same* session. Tagging a mon
reallocates its `PokemonProto`, so pointers from an earlier walk are stale and `SetPokemonTags`
throws.

---

## 7. The forensic record — stated at its true size

A forensic audit on **2026-09-07** looked for keepers a past engine had put in the irreversible pile.
Report it exactly as follows; it is neither a footnote nor a catastrophe.

**One provable loss.** A **Mudbray** whose `species_name` parsed as the placeholder `"pid749"`. With
no `FORM_OVERRIDES` entry and no resolvable slug, `pvid()` produced a speciesId absent from the
gamemaster, the ranker wrote **NULL** ranks, and the engine read "no rank" as "no PvP protection"
instead of "unknown → protect". Its true rank was **Great League #2 of 4096 (99.65%)**. It was
released and is unrecoverable.

**The defect class that closed it** is rule **15c**, the rank-data guard in `keep_policy.py`
(2026-09-02) — the missing half of the Mareep lesson. Rules 15 / 15a / 15b all begin
`rank is not None`, so a mon whose ranks were never computed silently got no PvP protection at all:
the same outcome as a mon that genuinely ranks badly, from data that simply is not there. 15c marks
any row with **both** `gl_rank` and `ul_rank` NULL as `rank_unknown` → protected, and additionally
**aborts the whole run** if more than a fifth of the bag has no ranks (at that point the rank
pipeline did not really run, every PvP rule is vacuous, and per-row protection would silently degrade
into "keep almost everything" and hide the breakage). Rule 15b, the `pvp_rank` safety net, is its
sibling: any mon top-`READY_RANK` for a CP-viable evolved league form is kept, period.

**The honest evidence horizon.** The audit found **24** mons a correct engine would have kept, **18**
of them released and unrecoverable — but that number is a **floor, not a ceiling**, because of what
we can actually look at. Historical DB copies exist at only:

| Date | Artifact |
|---|---|
| 2026-05-19 | `.db_snapshots/…2026-05-19…` , `pokemon.db.bak_perf` |
| 2026-05-30 | `pokemon.db.bak-ghostdrop` |
| 2026-07-25 | `pokemon_ACCOUNT1_20260725_0503.db` |
| 2026-08-19 | `pokemon.db.bak-2146` |
| 2026-09-02 | `pokemon.db.prebgfix.bak` (plus dense `.db_snapshots/` from 09-02 onward) |
| live | `pokemon.db` |

There is a **56-day gap between 2026-05-30 and 2026-07-25** and **nothing at all before 2026-05-19**.
Anything released inside that gap, or before the first snapshot, leaves no trace we can audit. Do not
round "18 confirmed lost" up to "18 lost" or down to "only 18". Say what it is: 18 that we can prove,
over a window that does not cover the whole history.

Of the 18, **17** predate any PvP-rank rule — the pre-2026-06-05 IV-magnitude era, the same defect
that killed the 0/13/11 Great League rank-1 Mareep. Under a league CP cap, stat-product rank
**anti-correlates** with IV%: low attack wins. Every IV floor or threshold ever added to a PvP path
has therefore rejected exactly the spreads that rank #1. Do not reintroduce one.

All 18 are now permanent fixtures in audit 6. A rule can be deleted; a fixture that proves the rule
cannot be deleted quietly.

---

## 8. Prerequisites

### ADB (Tailscale)

```powershell
adb connect 100.98.158.56:5555
adb -s 100.98.158.56:5555 forward tcp:27047 tcp:27047
```

`pogo_il2cpp.py` does both automatically on every `get_session()` call.

### frida-server

```bash
su -c setenforce 0
su -c /data/local/tmp/frida-server &
```

Must be running before any script that calls `pg.get_session()`.

### Frida is single-client

**Only one Frida session may be attached to PoGo at a time.** Two concurrent attaches collide
(`frida.InvalidOperationError`). `full_audit.py` keeps every phone-bound step (recrawl / sync /
verify) serial for exactly this reason, and runs only the read-only SQLite audits in parallel.
`preflight_transfer.py` reads deployment live, so run it alone.

Wait for a safe attach window rather than retry-looping — **every attach probe is a crash roll**:

```powershell
python -c "import sys;sys.path.insert(0,'.');import pogo_il2cpp as pg;print(pg.wait_ready_to_attach(timeout_s=300))"
```

`get_session()` refuses to attach unless `libil2cpp.so` is mapped and the process is >45s old.

### Never restart PoGo while the user is playing

`verify_tags_live.py` self-gates on screen-on + PoGo-foregrounded and falls back to a cache reconcile,
stating plainly that it is *not* server proof. `--force` exists for when the user explicitly asks.

### Something is rewriting the tree on a timer

`autocull_watch.py` runs the gated cull on a 5-minute tick and `dashboard.py` serves the control
panel; both rewrite `pokemon.db` and the tagsets. Before blaming a script or yourself for a changed
file, read `system/analysis/autocull_watch.log` and `dashboard_run.log`.

---

## 9. Deliberately not automated

- **Releasing / transferring.** We only ever tag. Standing user rule: *"you will never be releasing
  pokemon for me. just tagging for transfer."*
- **XXS culling.** `rules.xxs` is false.
- **Blanket policy changes.** Never flip a cap or a rule to "keep all" to make a problem go away.
- **PoGo restarts mid-play.** See above.
- **Deleting tags.** Outside the cycle, one at a time, `safe_nuke_tags.py` only. See §6c.

---

## 10. Where things live

| Path | Contents |
|---|---|
| `full_audit.py` | The one-command cycle |
| `dashboard.py` | Control panel on `127.0.0.1:8765` — single scrolling page; `/studio` curation tool |
| `autocull_watch.py` | Timer daemon: runs the gated cull when free space is low. Logs to `system/analysis/autocull_watch.log` |
| `keep_config.json` | **Single source of truth** for every cap and roster. Never re-hardcode in the engine. |
| `cpm_table.py` | **Single source of truth** for the CPM ladder, level-cap index and league CP caps. Import it; never re-hardcode a value from it. |
| `granular_tags.py` | The tag registry (`registry()`, `LEGACY_TAGS`, `EXEMPT_TAGSETS`) and `build()` / `filename()` |
| `system/scripts/` | The canonical pipeline: keep_policy, build_tagsets, preflight_transfer, prune_tags, refresh_evolve_shiny, set_db_tags_from_files, tag_ops, ready_gate, reconcile_tags, safe_nuke_tags, regress_pvp_keepers, check_constant_drift |
| `system/analysis/tagsets/*.txt` | One file per tag. `Transfer.txt` is the pile. |
| `system/analysis/policy_reasons.json` | Every **kept** uid → its keep reasons |
| `system/analysis/pile_provenance.json` | The config fingerprint, DB content hash and pile hash the current pile was built from |
| `pokemon.db` | The mirror + analysis layer (WAL). `auth_tag_names` is semicolon-separated. |
| `system/SCRIPTS_INDEX.md` | Full catalog of every `.py` in the repo |
| `system/procedures/` | Maintenance and recovery runbooks around this one |
| `HANDOFF_KEEP_LAW.md` | The keep law in depth, plus the traps behind it |

### Evolve labels are a simulation of the keep rule (2026-09-13)

There is ONE answer to "would this copy be kept at that stage?" and both the cull and the Evolve labels use it.
`keep_policy._earns_slot(t, r)` drops a virtual evolved copy of `r` (same IV, CP and collectible attributes) into
stage `t`'s real plain pool plus the copies already promised there, ranks it with rule 1b's own `_eff_cap` + `topn`
(specials displace by IV, CP breaks ties), then applies the dominance pass's own test (a kept, non-trophy copy with a
strict superset of attributes and higher IV collapses a plain). "Evolve Next" = the reserved slot is one stage up,
"Evolve Twice" = it is at the final. Item-gated branches (`ITEM_GATED_TARGETS`) are never promised beside a candy
branch. No backfill: a stage holds the best N you own, promised or not; a copy enters only by beating one of them
("comb up"). The seed-bar oracle is derived from the same function with a max-CP plain probe (a lower bound).
`_evocheck.py` re-derives the dominance test independently (`_attrs`/`doms`).
