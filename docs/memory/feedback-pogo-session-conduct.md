---
name: feedback-pogo-session-conduct
description: "How to run a PoGo session correctly — reuse the one known-good tool, don't over-fan agents, apply env fixes up front, be terse."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

On a 2026-05-21 session the user called "unbearable" ("so many mistakes and so slow"), I optimized for *appearing* productive (many one-off scripts, ~50 fanned agents, fast output) over being correct and fast. Three anti-patterns to kill, and their replacements:

1. **Use the ONE known-good tool.** The canonical pipeline is `pogo_pipeline.py` + `pogo_il2cpp.py`. Do NOT write a new script when an existing one already does the job — extend the existing one. I burned hours re-writing `robust_tag.py` / `lean_legacy.py` / many one-offs that re-hit the SAME PoGo PID-drift crash the pipeline already handled.
2. **Don't spawn agents for what a single DB query or one script answers.** The ~50 agents produced a REVIEW tag full of regional/legacy/dex-gap errors that then needed cleanup — net-negative complexity. Agents are for genuinely parallel, independent research only.
3. **Apply known environment fixes at session start, not per-command.** Disable the cached-app freezer and set up adb forward up front (see [[pogo-frida-stability]]) instead of fighting the symptoms of PID drift on every command.

Plus: when a command fails the same way TWICE, STOP and fix the root cause — never enter a retry loop on a known-broken approach. And be terse; verbosity compounded the user's frustration.

**Why:** Producing output before validating inputs and reusing infrastructure feels fast but is slow and error-prone — every mistake gets caught by the user and needs a cleanup pass, and the visible churn reads as thrashing.

**How to apply:** At the start of any PoGo task: (a) apply the env fixes, (b) reach for `pogo_pipeline.py` first and extend it if needed, (c) run the data-completeness gate before any irreversible action (see [[pogo-data-completeness-before-destructive-actions]]), (d) reserve agents for parallel independent research, (e) keep responses short. Relates to [[feedback-verify-before-irreversible]] and [[pogo-source-of-truth-db-rules]].

---

**2026-05-28 update — corrections from a long live session:**

1. **ALWAYS check before asserting state.** I claimed "PoGo is closed" off a single transient `get_session()` failure (it was PID-drift; the app was open, pid had just changed) and claimed "you're missing only 9 species" off an unverified `dex_caught.json` I assumed was current. Both wrong; the user: *"Always check before asserting."* Before stating device state, run `adb shell pidof com.nianticlabs.pokemongo` (+ `dumpsys ... ResumedActivity`); before stating inventory/dex facts, query the live source, not a cached file. A single tool failure is not proof of a state — re-check.

2. **Agent fan-out — the real constraint is FRIDA, not agents per se.** The earlier "don't over-fan" lesson is about the single Frida attach: never run multiple agents that each attach to PoGo (PID-drift/contention/collateral). But for **non-device work — DB queries, doc generation, code/script authoring, web/PVPoke data — fan out liberally and in parallel** when the user asks; just give each agent a DISTINCT output file so they don't collide. (User explicitly wanted this: "liberally create agents to solution it. Don't collide.")

3. **Tag philosophy: only keep tags PoGo can't filter natively.** In-game bag search already filters Shiny/Shadow/Purified/Lucky/Legendary/Mythical/Hatched/Traded/Dynamax/Gigantamax/Adventure Effect/Backgrounds/Event/Can-Evolve/Can-Mega/Buddies — custom tags for those are redundant and were nuked (the retirements live in `granular_tags.RETIRED_TAGS`), except Adventure Effect, kept as a managed tag (form-level AE holders). Keep only what native search can't do (exact IV spreads, PvP ranks, legacy moves, trainer origin, curated XXL, action lists). See [[pogo-tag-system-2026]].

4. **The hardened toolkit lives in `pogo_extract/system/`** — use it instead of writing new one-offs: `scripts/safe_nuke_tags.py`, `scripts/tag_ops.py`, `scripts/reconcile_tags.py`, `scripts/check_freshness.py`, plus `procedures/`. `granular_tags.py` is the tag source of truth: `registry()` is the push plan (31 managed on 2026-09-20: 6 legacy + 25 vocabulary, Evolve Shiny managed since 2026-09-12), `EXEMPT_TAGSETS` = 4 Armored tags, `RETIRED_TAGS` = 23. `system/tags/registry.json` is a one-off snapshot regenerated 2026-09-09 and NOT kept in sync. Count from granular_tags, never from the JSON or this note.

---

**2026-06-05 update — REPORT PROGRESS ON EVERY RECRAWL (standing user request, asked with a :)).** After EVERY recrawl, give a short "what changed" digest — NOT just "bag X, synced". Report: (a) **bag delta** (+caught / −released since the last crawl); (b) the **new notable catches** — pull via `creation_date` (capture dates now parse live every crawl) and surface hundos / shinies / high-IV / legendaries / **league #1s** (`gl_rank` or `ul_rank` == 1) / new-dex / costumes; (c) **tag deltas** (Transfer Δ, Legacy / etc.) — and **ALWAYS show GL/UL Rank 1, Rank 2-5, Evo GL/UL Rank counts and Evolve Next / Evolve Twice / Evolve Shiny counts, even when flat** (the user watches PvP AND the evolve-me advisories and will ask if they're missing); IVs are re-read for EVERY mon each crawl (the pipeline UPDATE rewrites iv/cp/level/moves/form/alignment — captures purifications +2/stat, power-ups, TMs, evolutions); to catch power-up / evolution **bumps**, track per-tag **MEMBERSHIP (uids)** in the before-snapshot, not just counts, and NAME any mon that newly qualifies or drops; (d) any **field/level updates** (new best-buddy, mega level-up). Keep it tight but informative — the user explicitly likes seeing the progress each time. (Learned 2026-06-05: a digest that only shows *changed* tag counts hid that GL IV had climbed 21→24 across the session; the user noticed.)
