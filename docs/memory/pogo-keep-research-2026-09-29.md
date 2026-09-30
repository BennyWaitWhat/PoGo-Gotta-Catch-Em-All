---
name: pogo-keep-research-2026-09-29
description: 262-agent research on why the kept bag is so large -- root causes, verified slot costs, what he applied (4,5,6 + middle 1) and what is still open
metadata:
  type: project
---
Research 2026-09-29 (workflow wf_866da987-e95; results in the session scratchpad research/findings/workflow_result.json). 92 of 124 findings survived 3-lens verification. Numbers are from the sandboxed real engine (whatif.py) on the 02:58 bag.

**Root causes:** (1) live caps have ~6,560 open slots -> ceiling ~12,300 vs 5,850 storage; no single cap lever gets below storage. (2) Inflow: ~64 net keepers/day (+446 in 7 days at constant rules, 72% via plain ladders). The bag always refills; caps only slow it.

**Applied 2026-09-29 ~04:33 (his picks "4, 5, 6" + "Middle stage 2 -> 1: fine"):**
- Unpaid comb-up holds now COMMIT their slot (keep_policy _unpaid_committed; exported to system/analysis/unpaid_holds.json; _evocheck replays them as earmarked with the rescue bar). Freed 26 on the snapshot (Murkrow 6, Panpour 6, Munna 5 ...).
- candy_now/items_now(walk=...) judge freshness against the walk (pokemon.db last_scanned), not the wall clock; unknown count = cannot pay (hold, no Evolve label).
- caps.rarity_shadow = 3 (shadow legendary variants; Mewtwo keep-all untouched), mirrored in audit_cull, _spotdata, audit_invariants AXES.
- caps.plain_line_preevo = 1 (middle stages).
- First cull with all four: 87 in Transfer, 11/11 audits.

**Still open (numbered for him; he has not picked):** 1 main vs LAW caps (LAW rows carry the florandez 09-26 values; applying them to main frees 783; or rewrite LAW per account); 2 Remote Trade spares (469 kept only as trade stock; releasing frees 469, trading frees 0); 3 merge rule (plain ladder ignores same-look XXL/card/PvP/legacy copies: 235, or 73 if XXL/card are separate looks; needs audit_cull + _lawcheck + preflight mirrors); small levers: gender 2->1 76, first stage 3->2 69, nundo keep-all 45, Mewtwo keep-all 39, Pikachu costume 4->3 31, Gyarados shiny 18 14. Refuted as keeper-losing: line_pool_all 472, hundos taking ladder slots 271, shiny floor 25 183.

Related: [[pogo-xxl-trim-one-off]], [[feedback-number-findings-then-ask]], [[pogo-capped-vs-keepall-bug-class]].
