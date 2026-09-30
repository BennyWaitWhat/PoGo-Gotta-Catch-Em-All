# Procedures Index

**Verified 2026-09-07.** The authoritative operating doc is [`../../RUNBOOK.md`](../../RUNBOOK.md).
These runbooks cover the maintenance and recovery paths around it.

## Golden path

1. Open Pokemon GO on the phone and leave it **foregrounded** (a backgrounded, frozen app accepts
   tag writes that never land).
2. Run the cycle:
   ```
   python full_audit.py
   ```
   Recrawl → six audits in parallel → hard gate → sync → verify. If any audit fails, **no sync runs**.
3. Read the pile and release by hand. Tagging is never releasing.

Read-only variants: `--no-sync` (recrawl + audit, never touches the phone's tags), `--audits-only`,
`--skip-crawl`.

Ask questions against the fresh DB with:
```
python system/scripts/query.py <subcommand>
```

That is the entire happy path. Everything else is maintenance or recovery.

## The pile path, in order — this is law

If you run stages by hand instead of `full_audit.py`, run them in **this** order and skip nothing:

```
1  python system/scripts/keep_policy.py             # decide KEEP vs pile
2  python system/scripts/build_tagsets.py           # decisions -> tagset .txt files
3  python system/scripts/preflight_transfer.py      # HARD GATE. rc != 0 -> STOP. Writes the STAMP.
4  python system/scripts/prune_tags.py --atomic     # push (refuses without a fresh, matching stamp)
5  python system/scripts/refresh_evolve_shiny.py    # rebuild Evolve Shiny (not in prune's PLAN)
6  python system/scripts/set_db_tags_from_files.py  # mirror auth_tag_names -- LAST
```

**Why step 3 writes an artifact.** Pre-flight is the only keeper check in front of the one
irreversible output, and until 2026-09-07 its verdict was **only an exit code** — which lives in one
process and dies with it. Nothing downstream could tell "pre-flight passed" from "pre-flight failed
and someone pushed anyway" from "pre-flight was never run". That gate was not bypassed; it was
**unobservable**. An exit code vanishes; an artifact can be re-read and compared.

The artifact is `system/analysis/preflight_stamp.json` (schema 1), carrying `pile_sha256`,
`pile_uids`, `config_sha256`, `db_sha256` and `generated`. Pre-flight destroys any existing stamp as
the first statement of a run and writes a new one **only** on a full PASS. Any push including
`Transfer` then refuses with **rc 2** unless the stamp exists, is complete, matches a **fresh** hash
of the current `Transfer.txt`, matches the live `keep_config.fingerprint()` and the live
`pile_provenance.json` db hash, and is **younger than 30 minutes**. **`--force` does not bypass this**
— it bypasses `ready_gate` and nothing else.

**Why step 6 is last.** `set_db_tags_from_files` writes `auth_tag_names` straight from the files with
no idea whether the push landed, and `auth_tag_names` is what `/api/tagdiff` calls "the phone's
last-known tags". Run it first and every sync, successful or not, reports "already in sync" forever
after.

**Never run `prune_tags.py` on its own.** With no tag arguments it targets the whole 46-tag plan,
`Transfer` included, live. Its `ready_gate` is a write-*reliability* check (screen, foreground, not
frozen) — it has no opinion about keepers, and `--force` skips even that.

## Procedure runbooks

| Runbook | When to use |
|---------|-------------|
| [refresh.md](refresh.md) | Re-crawl the DB from the live bag |
| [query.md](query.md) | Cheat-sheet for `query.py` and direct SQL |
| [tag-maintenance.md](tag-maintenance.md) | Create/apply/reconcile/verify server tags outside the cycle |
| [recover.md](recover.md) | Restore an accidentally deleted or emptied tag from the DB mirror |

## Canonical scripts (quick reference)

The keep/tag cycle:

| Script | Role |
|--------|------|
| `full_audit.py` | The one command: recrawl → six audits → gate → sync → verify |
| `dashboard.py` | Control panel on `127.0.0.1:8765`; same code path as the cycle |
| `autocull_watch.py` | Timer daemon; runs the gated cull when free bag space is low |
| `system/scripts/keep_policy.py` | Step 1 — decide KEEP vs pile |
| `system/scripts/build_tagsets.py` | Step 2 — decisions to tagset files |
| `system/scripts/preflight_transfer.py` | Step 3 — the hard gate; `rc != 0` means STOP; writes the stamp |
| `system/scripts/prune_tags.py --atomic` | Step 4 — bidirectional push, verifies set equality |
| `system/scripts/refresh_evolve_shiny.py` | Step 5 — rebuilds `Evolve_Shiny.txt` (outside prune's PLAN) |
| `system/scripts/set_db_tags_from_files.py` | Step 6 — mirror `auth_tag_names`, **runs last** |

The six gate audits (all read-only, no device contact): `audit_cull.py`,
`audit_tags_membership.py`, `_evocheck.py`, `_lawcheck.py`, `audit_invariants.py`,
`system/scripts/regress_pvp_keepers.py`.

Supporting tools:

| Script | Role |
|--------|------|
| `pogo_pipeline.py` | Single-attach re-crawl: bag walk, reconcile, tags, ranks, cull |
| `pogo_il2cpp.py` | Shared Frida/IL2CPP session + singleton helpers |
| `granular_tags.py` | The tag registry: `registry()` (46 tags), `EXEMPT_TAGSETS`, `build()`, `filename()` |
| `keep_config.py` / `keep_config.json` | Every cap and roster. `cap()` / `species_cap()`, never `DEFAULTS` |
| `cpm_table.py` | The CPM ladder, level-cap index and league CP caps. Import; never re-hardcode |
| `system/scripts/ready_gate.py` | The gate every tag-WRITE path must pass (screen, foreground, not frozen) |
| `system/scripts/refresh.py` | Turnkey wrapper: pipeline + deep_profile + reconcile + verify |
| `system/scripts/query.py` | Instant-answer CLI over `deep_profiles.json` |
| `system/scripts/doctor.py` | Read-only health check (0=PASS, 1=WARN, 2=FAIL) |
| `system/scripts/deep_profile.py` | Per-specimen profiler |
| `system/scripts/tag_ops.py` | Hardened tag create/apply (colour is 0-8; no delete primitive) |
| `system/scripts/safe_nuke_tags.py` | The only sanctioned tag deletion path (one at a time, collateral check) |
| `system/scripts/reconcile_tags.py` | Server-vs-DB tag drift reporter and fixer |
| `system/scripts/check_freshness.py` | Staleness **report** only — read-only, writes nothing |
| `system/scripts/check_constant_drift.py` | Asserts every game constant has exactly one definition |
| `system/scripts/verify_tags.py` | Tag membership verifier (SERVER vs DB vs RULE) |
| `verify_tags_live.py` | Post-sync server-truth verification |
| `bulk_tag.js` | Frida JS: AddTag, SetPokemonTags, bulk_tag_many, bulk_untag_one |
| `compute_all_ranks.py` | GL/UL/LL IV-spread rank calculator (chain-aware) |
| `detect_legacy.py` | Legacy/elite-move detector → `legacy_accurate.json` |

See [`../SCRIPTS_INDEX.md`](../SCRIPTS_INDEX.md) for the full catalog of every `.py` in the repo,
including the deleted and retired ones.
