# Curation Studio — LOCKED DECISIONS (2026-06-08)

Resolves the workflow's open questions + the adversarial review's HIGH/MEDIUM findings. Pairs with `.grill/curation-studio-design.md`.

## Release flow + engine coupling (Q1+Q2) — OPTION B: "Tighten-and-apply"
- Culling = tightening a category's cap (global OR per-species) in the Studio → **Apply** writes to `keep_config` (the single source of truth) → next **Recrawl→Sync** recomputes the pile (bag − kept) → over-cap mons land in the REAL Transfer pile → **pre-flight-gated** → manual in-game release. **No candidate/dead-letter file.**
- ADD **per-species (and per-form where needed) caps** to the engine, ADDITIVELY: `keep_config` gains optional per-category cap maps; `keep_policy` reads them; default = empty = **exactly today's global-cap behavior**. This is the "improve effectively" case, not a regression.
- HIGH#1 resolved: the cap IS the mechanism; nothing relies on an ingested file the engine never reads.
- HIGH#2 resolved: the live "what would release" preview re-derives **KEPT-vs-NOT membership** from `fresh_*` columns + `cf()` + the engine's recomputed keep-set under the proposed cap — NEVER from `policy_reasons` strings (`variant_floor` is shared across plain/Gmax/Dmax/cosmetic, so reason-string category tests are invalid). Pre-flight still independently re-checks every axis before any release.

## Other decisions
- **Origin tag drift (Q3): FIX.** `build_tagsets.py:98` → call `keep_config.origin_owners()` instead of the hardcoded E+F list (additive correctness; default identical).
- **Sprites (Q4): local-first + CDN fallback.** Primary = `pokegenie_work/extracted/Pokedex/{dex}[_Form].jpg` (864 local, verified). Fallback for costume/shiny = PokeMiners `pogo_assets` CDN (base URL swappable in config); client onerror chain local→CDN→placeholder.
- **Category scope (Q5): v1 = the 8 named** (Gmax, Dmax, Legendaries, Backgrounds/Locations, XXL, Shiny, Lucky/Traded, Legacy). Shadow/Purified + PvP(GL/UL) curators = fast-follow tabs (engine already has those rules); not blocking v1.
- **XXS (Q6): hidden by default**, opt-in toggle, no dedicated tab.
- **Default tightness (Q7): ship LOOSE** = current engine caps as baseline (nothing flagged until the user tightens). Studio surfaces each category's "biggest dupe stacks" so the user SEES where tightening pays off — powerful, never a surprise cull.
- **Persistence (Q8):** staged cap edits live in `curation_config.json` (Tier B) until Applied; per-species cap maps promote to `keep_config` on Apply. No uid queue (Option B removes it). Validate stored pids/forms against the live bag on load; silently drop stale.
- **Lucky/Traded (HIGH#3): audit/browse view.** Only E+F-owned luckies/trades are kept by the engine; ALL other luckies/trades are normal fodder — labeled clearly. Only load-bearing knob = `kept_owners` (Tier-A, via Apply). `keep_luckies_all`/`keep_self_trades` are display filters only, with no engine effect (or dropped).
- **Names (MEDIUM): prettify layer.** Add `curation_labels.json` (hand-authored display names for the cosmetic/location/form/move tokens actually in the bag) + a humanizer fallback for unknowns (split camelCase, strip `Lc`/year). Enums return code tokens (`UnownA`, `Lc2023NycGofest001`) — these must become real names ("Unown — A", "GO Fest 2023: New York City").
- **Transfer file (MEDIUM): disambiguate.** `keep_policy` writes `6_Transfer.txt`; `build_tagsets` writes `Transfer.txt` from the same set; `preflight_transfer` reads `Transfer.txt`. Studio reads the one pre-flight consumes.
- **Safety/JOB_LOCK (LOW):** Studio reads (`/api/studio/category`, `/preview`) are lock-free read-only (own `?mode=ro` connection, usable during a job). Only `curation_config` save + `apply_engine` take `_JOB_LOCK`.
- **Non-regression (LOW): snapshot `dashboard.py` → `dashboard.py.bak` before editing** (no git in this project). Existing `PAGE`/JS, all 15 rules, all 12 tags, the whole pipeline stay intact; the only existing-file edits are one header `<a>` link, the origin one-liner, and the additive per-species cap support.

## Build surface (all additive)
new `/studio` route + `STUDIO_PAGE` + `/api/studio/*` endpoints + `curation_config.py`/`.json` + `studio_data.py` (RO decode/sprite/keep-reason helpers) + `curation_labels.json` + per-species cap support in `keep_config`/`keep_policy` (default off) + one header link + the origin one-liner. Self-test: existing `/` page byte-unchanged, every category loads RO, preview numbers match the analyses, pre-flight still gates.
