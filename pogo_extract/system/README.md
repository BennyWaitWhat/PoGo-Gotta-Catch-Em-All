# PoGo Tag & Inventory System

Authoritative system for the Pokémon GO collection: the keep law, tag definitions, operating
procedures, issue tracking, and analyses. Built on the Frida/IL2CPP extractor in the parent
`pogo_extract/` directory.

**Verified 2026-09-03.** Start at [`../RUNBOOK.md`](../RUNBOOK.md) — it has the cycle, the caps and
the traps. This file is the map.

> **We only ever TAG. The user releases by hand.** `Transfer` is a tag, not an action.

## Core model (source of truth)

1. **Server tags are authoritative.** They live server-side
   (`Niantic.Holoholo.Tagging.TaggingRpcService`) and persist across app restarts and DB rebuilds.
2. **`pokemon.db` is a mirror + analysis layer.** `auth_tag_names` (semicolon-separated) mirrors the
   server tags; every other column is extracted from live protos.
3. **The live bag is ground truth for membership.** Tags and columns drift; a re-crawl
   (`pogo_pipeline.py`) re-syncs the DB from the live bag, then re-mirrors server tags into the DB.
4. **`keep_config.json` is the single source of truth for every cap and roster.** Never re-hardcode
   one in the engine, and always read it through `keep_config.cap(name)` — the JSON overrides the
   in-code defaults and 5 of 11 caps currently differ.
5. **Reconcile direction:** server → DB (mirror). DB → server only via the sanctioned push
   (`prune_tags.py --atomic`), and the mirror is written **after** the push has verified.

## The cycle

```powershell
python full_audit.py          # recrawl -> 5 audits -> hard gate -> sync -> verify
python full_audit.py --no-sync   # read-only; never touches the phone's tags
```

The manual five-step path, the five audits, the live caps and the known traps are all documented in
[`../RUNBOOK.md`](../RUNBOOK.md).

## Tag philosophy

**Only tag what PoGo cannot filter natively.** In-game bag search already filters Shiny, Shadow,
Purified, Lucky, Legendary, Mythical, Hatched, Traded, Dynamax, Gigantamax, Adventure Effect,
Backgrounds, Event, Can Evolve, Can Mega Evolve and Buddies, so custom tags duplicating those were
removed. What survives captures something native search cannot: PvP rank bands, exact IV spreads,
legacy movesets, trainer origin, curated XXL/variant tiers, and the action lists.

**45 tags currently.** 44 are pushed and reconciled by `prune_tags.py` — 11 historical ones
(`_LEGACY_PLAN`, matching `tags/registry.json`) plus 33 derived at run time by `granular_tags.build()`.
The 45th, `Evolve Shiny`, is produced by `refresh_evolve_shiny.py` and is **not** in that plan.
Every in-bag mon carries at least one tag.

## Folder map

| Path | Contents |
|------|----------|
| `scripts/` | The canonical pipeline (keep_policy, build_tagsets, preflight_transfer, prune_tags, set_db_tags_from_files) plus hardened tag tooling |
| `analysis/tagsets/*.txt` | One file per tag. `Transfer.txt` is **the pile** — the one irreversible output. |
| `analysis/policy_reasons.json` | Every **kept** uid → its keep reasons. With `Transfer.txt` this is an exact partition of `in_bag=1`. |
| `tags/REGISTRY.md` / `tags/registry.json` | The 11 historical tags: rule, colour, rebuild method |
| `procedures/` | Runbooks: re-crawl, tag lifecycle, query, recover |
| `issues/ISSUES.md` | Issue tracker: root cause → solution → status |
| `KEEP_POLICY.md` | The keep law as policy prose |

## Key parent-dir tooling

- `full_audit.py` — the one-command cycle
- `dashboard.py` — control panel on `127.0.0.1:8765`, plus `/studio`
- `keep_config.json` / `keep_config.py` — every cap and roster
- `granular_tags.py` — derives most of the tag plan at run time
- `pogo_pipeline.py` — single-attach re-crawl (walk → reconcile → re-mirror tags → ranks → cull)
- `pogo_il2cpp.py` — Frida session + singletons (`get_session`, `pick_singleton`, `wait_ready_to_attach`)
- `bulk_tag.js` — tag RPC helpers
- `compute_all_ranks.py` — GL/UL/LL IV-spread ranks (chain-aware)
- `verify_tags_live.py` — post-sync server-truth verification

See [`SCRIPTS_INDEX.md`](SCRIPTS_INDEX.md) for the full catalog, including what was deleted or retired.

## Current state (2026-09-03)

- Bag **5,618** in-bag; pile **80**; kept **5,538**. Exact partition, zero overlap.
- **45** distinct tags in the DB mirror; **0** in-bag rows carry no tag.
- All five gate audits PASS; pre-flight PASS; phone verified in sync with zero drift.
