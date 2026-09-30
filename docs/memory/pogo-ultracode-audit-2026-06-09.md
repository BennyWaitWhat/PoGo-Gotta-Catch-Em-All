---
name: pogo-ultracode-audit-2026-06-09
description: "The 23-agent deep audit — fresh-column law (garbage natural_art_background culled a real shiny Gmax Lapras), what was fixed, and the open approval knobs (F4/F6/F7)."
metadata: 
  node_type: memory
  type: project
  originSessionId: d44dc321-2608-42e7-870c-24289b882f3e
---

# Ultracode deep audit 2026-06-09 (23 agents: 8 code audits + 5 research + synth + 9 adversarial verifies; 30 findings, 9 top all CONFIRMED)

**THE LAW THIS PROVED — fresh_* columns ONLY, everywhere on a live path.** `natural_art_background`
(non-fresh) held GARBAGE on 7 in-bag rows (Lapras 118, Zacian 6357024, Pidgeot, Kabutops, Scyther, Abra,
Camerupt) while `fresh_natural_art_bg`=0 on all 7. The garbage fabricated a phantom "background" bit in the
dominance-collapse bitmask → the iv40 shiny Gmax Lapras read as strict-superset-richer → **collapsed the
user's OTHER shiny Gmax Lapras (78%) into the irreversible Transfer pile**. The user's instinct ("keep my
gmax and shinies for this one time") had pardoned it hours before the audit found the bug — vindicated.
Fix applied to EVERY live read-site (keep_policy ×4, preflight ×2, build_tagsets Event SQL, studio ×6 +
its _SELECT). Engine rerun diff was EXACTLY one mon: Lapras → KEEP ['shiny']; preflight PASS. Extends
[[pogo-source-of-truth-db-rules]] and the display-cols caveat in [[reference-live-cosmetic-reads]].

## Applied same pass (all verified, no keep/transfer change except the Lapras):
- preflight gate now a true superset: AE-roster clause (pid in ae_pids() even at 0 effects-left, F2) +
  per-(species,form) `dex_only_form` re-derivation (F8). Gate-strengthening only.
- Studio red flag = ENGINE truth: `releasable` := uid absent from policy_reasons.json (cap-ranking heuristic
  only for what-if previews; `in_transfer` field added). Killed 5 false-RED (27 keep-all Mewtwo) + 20
  false-GREEN (collapsed shinies). Verified 0 studio-vs-engine mismatches across all 6 tabs. (F3)
- pipeline: display-proto read-failure quarantine (skip cosmetic-field overwrite, keep prior — a transient
  read no longer writes a fake culls-eligible "plain", F17); dex floor guard (<500 entries → keep prior
  dex_caught*.json, F19); captured-forms CLAMP 256 was hard-cutoff at 60 (Pikachu at 46 and climbing, F20);
  species_lookup `_shadow` guard (F27).
- topn() uid tiebreak → pile reproducible across recrawls (F25). COSMETIC_CAP env override now warns (F15).
- deco TEXT '0' normalized in _vkey (F24). read_pokedex_live.py QUARANTINED → writes *.heapscan.json, never
  the canonical file (slim-schema corruption, F11). evo_hundo_gap: UNRELEASED_IN_POGO += 902 Basculegion
  (Niantic disabled White-Striped evo on-record, F5); times default 0 (F18). /api/preflight button now
  regenerates the pile first like /api/sync (F30).

## NOT applied — needs explicit user approval (changes keep/transfer):
- **F4**: live `viability_margin=0` contradicts its docstring/default 100 — reintroduces the Abra
  L50-hundo degenerate-rank keeper. It may be the user's deliberate dashboard edit. ASK: 0 or 100?
- **F6**: collapse bitmask is one-bit-per-CLASS — two DIFFERENT costumes/backgrounds can collapse into
  each other (latent today, lossy by construction). Fix = identity-aware superset (same concrete ids).
- **F7**: collapse + plain-floor displacement ignore GENDER for gender-evolvers — a rare female
  Combee/Salandit/Burmy plain can be dominated by a male special (latent; Burmy has 6 specials).
- Flagged ideas: XXS axis (2026 size badges), Apex Shadow axis, special_bg in collapse equivalence key,
  shadow cap (=1) revisit, ML-rank axis, evolve-tag item/stone gates (F12), SPECIAL_REQUIREMENT advisory
  bucket in evo_hundo_gap.

## Game-truth corrections (researched + adversarially verified):
- **Gigantamax roster** = species whose client-GM `pokemonExtendedSettings.breadOverrides` has breadMode
  `BREAD_DOUGH_MODE`: 18 on 2026-09-20 (Venusaur, Charizard, Blastoise, Butterfree, Pikachu, Meowth, Machamp, Gengar,
  Kingler, Lapras, Snorlax, Garbodor, Rillaboom, Cinderace, Inteleon, Toxtricity, Grimmsnarl, Urshifu), 16 owned
  (missing Kingler, Urshifu). Do NOT count `BREAD_SHARED_SETTINGS.allowedSourdoughPokemon` (31 incl. Eevee, Melmetal:
  a whitelist, not the released roster) or raw BREAD_DOUGH_MODE hits; a GM entry proves the client knows the form, not
  that it is released. references.py GIGANTAMAX_FORMS (31 incl. Eevee) is dead; protection keys on the per-mon
  `fresh_bread_mode==2`, so the roster is informational.
- **Lucky window CHANGED 2025-12-31**: guaranteed-lucky = caught **2020 or earlier** (not pre-July-2018);
  lifetime guaranteed cap 35→45. Floor stays 12/12/12.
- Mega ladder 4th tier "Super Max" (2026-02-20) = exactly {Victreebel, Dragonite, Malamar}.
- Dynamax is NOT a fixed roster (~80+, growing) — engine correctly keys off bread_mode bit, never a list.
- AE roster = 7 dex ids {483,484,646,800,888,889,890} / 9 effects in the keep roster (Kyurem+Necrozma carry 2 each);
  the live registry has 11 effects (+2 Mega Mewtwo, covered by rarity keep-all 150).
- Best-Friend trade floor 5/5/5 confirmed; shadow multipliers combat-only; PvP rank-not-IV validated.
- pvpoke `released` flag unreliable (~84 false-unreleased); strongest availability proof = user already CAUGHT it.

Snapshots: `*.ultrabak` on keep_policy, preflight_transfer, build_tagsets, studio_data, pogo_pipeline,
evo_hundo_gap, read_pokedex_live, dashboard. Baseline pile diff in `.audit_baseline/`. Workflow script:
`.wf_pogo_audit.js` (resume id wf_bdef7a58-3d8). One-time pardon tool: `pile_pardon.py --shiny --gmax`
(server-untag + files + DB mirror; next recrawl re-derives).

## ROUND 3 — COLLAPSE SEMANTICS REVERSED FOR SHINIES (2026-06-10, "the other shinies shouldnt get
## booted......theyre only to collapse up not down"):
**Standing law: COLLAPSE GOES UP, NEVER DOWN.** A richer shiny OUTRANKS poorer shinies at the cap margin
(rule 3 now sorts by IV, then attr-richness `len(_scollect)`, then cp/uid, takes top-N) but NEVER deletes
them — the 2026-06-08 `_dominated_shiny` within-cap erasure is GONE, and `'shiny'` was REMOVED from the
universal pass's `_SOFT` (now `{variant_floor}` only). Shinies live and die by the shiny CAP alone; only
plains/variant-floor-only mons still collapse upward into strictly-richer siblings. This rescued 11 piled
shinies (6 Blissey, 3 Charizard, 2 Gourgeist) with 0 new pile entries; all 7 shiny Blisseys kept (the 80%
shiny-Dmax no longer erases the 6 below it). The user had skipped releasing them TWICE — repeated skip of
a tagged class = the rule is wrong, fix the rule, don't re-explain it. Pile baseline `.audit_baseline/Transfer.preShinyUp.txt`;
dashboard rules R3/R16 + studio shiny note rewritten to match. The same law is restated in
[[pogo-tag-system-2026]] (Displacement / collapse).
**Then "Same with gmax" (2026-06-10) → GENERALIZED: the universal collapse victim must be an
ATTRIBUTE-EMPTY TRUE PLAIN (`if _domattr(_b): continue`) — anything Gmax/Dmax/shiny/costume/bg/shadow is
limited by its OWN CAP ONLY, never deleted by a richer sibling. (The 89% loc-card Gmax Grimmsnarl had been
deleting its two plain-Gmax 87% siblings — all 6 Grimmsnarl Gmax were WITHIN the cap of 8.) Verified diff:
exactly the 2 Grimmsnarl rescued, 0 new; final pile = 3 true plains (93% Blissey covered by 100%+98%Dmax,
2 fresh Fletchling); Transfer tag exact-synced 3/3 so the user can't release rescued mons off a stale tag.
The FULL final lattice: plains collapse UP into richer copies; specials NEVER collapse; richness only
outranks at cap margins; hard axes + hundos immune. Dashboard rule 16 text matches.**

## Round 2 (same day, "Workflow the improvements in" + master plan):
F4/F6/F7 APPLIED with user approval (+`.f467bak` snapshots): viability_margin 0→100 (dropped exactly
Mankey UL#2 + Oddish UL#1 — verifier PROVED both ranks belong to the degenerate Primeape/Gloom band,
NOT Annihilape/Vileplume, drop correct); **F4 OVERRIDDEN BY USER 2026-06-10: margin back to 0 — "why
not just fucking 0" / "its stupid". FINAL: margin=0 is the user's DELIBERATE setting (any species that
can CROSS the cap counts; band IV-dupes wearing the PvP label accepted; can't-reach-cap species like
UL-Xatu still excluded). Docstrings in pvp_iv_rule.py + preflight fallback updated to match — NEVER
"fix" it back to 100. Pile impact on 2026-06-10: zero (band keepers already released).** identity-aware collapse (frozenset (class,id) sigs — the
(ma|mb)==ma comparisons work unchanged on frozensets); gender-split `_gterm` in _special_iv_grp +
_stage_key + _domgrp (None-gender groups consistently). XXS axis = rule 7b, default OFF
(rules.xxs/caps.xxs). All verified behavior-neutral on the live bag; pile byte-reproducible, row-order-proof.
**Verifier-caught regressions of MINE, fixed same pass: (1) DEFAULTS caps.xxs without _CAP_BOUNDS['xxs']
→ validate() KeyError → ALL dashboard saves dead (add bounds + _psc_cats when adding ANY cap!);
(2) location_card had NO independent gate coverage — Event.txt is VACUOUS for leaks because build_tagsets
strips Transfer uids from every tagset before preflight reads them (tagset∩Transfer=∅ BY CONSTRUCTION —
the gate may NEVER rely on a tagset file for leak detection; check DB columns). Gate clause added.**
evo_hundo_gap: EVOLUTION_METHOD_MISSING = {899 Wyrdeer, 900 Kleavor} (in GO as raid/event species but NO
pre-evo evolution method in GAME_MASTER — CLEAN list was over-claiming; only Kingambit + Aromatisse are
real). **Open tooling bug: dex shinyHundo flag reads 0/943 (catEnum 102 wrong/moved?) while the bag holds
2 shiny hundos (Fashion-Sneasel, Vanilluxe) — Frida enum investigation queued.**
Master plan: `wf_master.json` (root) → `gen_master_plan.py` → `master_plan.html` (+ dashboard `/plan`
route). Key intel: 195 missing hundos (67 = legendary raid wall),
lucky guarantee ammo on user side = ZERO (all pre-2021 traded; ride E+F's stock), Unown 28/28 complete,
Vivillon 8/20. June 2026 = missing-hundo jackpot (Zekrom/Necrozma/Kartana/Shadow-Dialga/Giovanni-Reshiram
all caught-never-hundo); GO Fest 2026 global Jul 11-12.
