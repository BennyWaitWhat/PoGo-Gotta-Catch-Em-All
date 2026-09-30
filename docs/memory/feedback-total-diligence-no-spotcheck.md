---
name: feedback-total-diligence-no-spotcheck
description: "Scan EVERY pokemon/form from authoritative ground-truth sources; never spot-check a sample or carry a classification forward from past-convo memory or a study agent's claim."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d44dc321-2608-42e7-870c-24289b882f3e
---

The user demands TOTAL diligence: when classifying or auditing the collection, enumerate the FULL set (every species, every form code, every specimen) from the AUTHORITATIVE source — never spot-check a sample, and never carry a classification forward from what a past conversation or a study/workflow agent "said."

**Why:** repeatedly I asserted form/tag facts from prior-convo memory or an agent's hypothesis instead of pulling ground truth, and kept shipping errors the user caught — Dynamax mis-flagged as "garbage," Lapras form **2585 (= `LaprasCostume2020`)** transferred because I assumed it was drift, 123 costumes treated as plain. Each was a sample/assumption, not a full ground-truth scan. The user: *"how many times will we have to do deep-research on the internal workings... you kept being lazy and 'spot check' pokemon only from past convo. I need total diligence."*

**How to apply:**
- **Form codes / costumes:** dump the live `PokemonDisplayProto.Form` enum via `system/scripts/game_read/classify_all_forms.py` → `form_enum.json` (id→name; 1,498 entries / 116 costume codes at the 2026-09-03 dump -- count from the file, don't quote this) and classify EVERY code in the bag from the real NAME. `costume_forms.py` is the committed classifier (costume = enum name not `<Species>Normal`, not regional, carries a year/keyword). A code's meaning is the enum name, not a guess from the number. `system/scripts/deep_audit.py`'s form census + FULL-ENUM costume hunt (every game form, not just in-bag) + false-neg/false-pos + regional-leak checks still apply, but its 12-tag invariant section checks the RETIRED pre-2026-09-09 vocabulary -- use full_audit.py for tag invariants. The classifier is exhaustive only over the form_enum.json dump: the 0.427.0 client already had 1,505 forms, incl. 7 Halloween-2026 costume forms (Zubat/Golbat/Crobat/Sinistea A+P/Polteageist A+P ...Halloween202601) missing from it and from COSTUME_FORMS, and the game is 0.429.1 since 2026-09-18 -- re-dump via classify_all_forms.py now and after every game update. FIXED 2026-06-04 ('everything perfect'): the ~14 regionals that carried a blank `form_region` are now backfilled by `normalize_forms` from the enum name (regional-leak 0, `paldean` tagged) -- it was always cosmetic (cf keys on the form CODE), now also honest.
- **Inventory truth** = query the bag DB by rule. **Lifetime/dex truth** = the Pokedex (PokedexImpl), never the bag.
- **A workflow/study agent's "this is garbage / the same / X can't do Y" is a HYPOTHESIS to verify against ground truth + the user — NEVER an action.** Don't merge, collapse, or transfer the user's proto-distinct variants on a heuristic.
- Re-crawl (`pogo_pipeline.py`) before asserting live state; full-sync + reconcile after every op.

See also [[pogo-tag-system-2026]] [[pogo-il2cpp-internals]] [[pogo-source-of-truth-db-rules]] [[feedback-verify-before-irreversible]] [[pogo-data-completeness-before-destructive-actions]].
