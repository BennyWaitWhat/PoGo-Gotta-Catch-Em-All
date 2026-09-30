---
name: pogo-special-backgrounds-capped
description: "User decision 2026-09-08: special backgrounds (LcSpecialbackground* -- LEGO 2026, Team Red, Extra2025xx) are CAPPED exactly like location cards: top 3 per (species, form, card) since 2026-09-24 (was 6, then 5 on 09-23). The game files both under the LocationCard enum. Card IDs were always read; the NAME table had gone stale (280 vs 411) -- now refreshed in-walk every recrawl, with an audit backstop for unnamed ids. COSTUME + BACKGROUND = ONE LADDER since 2026-09-24: a non-shiny, non-shadow costume copy never rides the card ladder."
metadata:
  node_type: memory
  type: project
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-24T05:11:34.026Z
---

**The complaint:** "You keep tagging a pikachu that has a Lego background. Why?" -- 7 plain Pikachu carried
`LcSpecialbackgroundLego202601` (card 281) and 14 Anniversary-2026 Pikachu carried `LcSpecialbackgroundTeamRed`
(card 19); the top-6-per-(species,form,card) cap piled the weakest 1 and 8. Only those two groups in the whole
bag exceed 6 (247 special-background holders across 100 groups; 52 true location-card holders across 43).

**Decision (user): "keep the cap."** Special backgrounds are collectibles like location cards and are capped the
same way; a 7th identical LEGO Pikachu is fodder. PikachuAnniversary2026 (form 3348) costume cap stays 6.

**What WAS stale -- and is now automatic:** `location_card_enum.json` had 280 names when the live enum had 411;
131 cards (incl. LEGO 2026) had an id but no name. Grouping/caps key on the id, so no keep decision was wrong,
but nothing could say what a card was. `pogo_pipeline.step_refresh_location_card_enum(sess)` now reads the
LocationCard enum's static fields on the walk's own Frida session (pure reads, fail-soft, never shrinks the
file) right after `read_ae_registry`; `audit_invariants` WARNs if any in-bag card id lacks a name. Studio
(`studio_data.py`) and `read_mewtwo_locationcard.py` read that file.

Frida note: python `exports_sync.enum_names` -> JS export **`enumNames`** (snake -> camelCase).

**Costume + background = one ladder (user 2026-09-24):** "if a costume and the SAME costume with a back ground, dont count
them seperate, if one with background ranks higher, than take slot of costume with JUST costume". A background copy
already competed in the costume's top-3 by IV; the per-card ladder was rescuing the losers as a SECOND slot (party-hat
Bulbasaur: 3 no-bg + 2 Team Red). Now `costume_forms.card_folds_into_costume(r)` (non-shiny, non-shadow, any costume /
costume form / deco / art bg) skips the card ladder in keep_policy, audit_cull (+ orphan ident drops the card), preflight,
the card comb-up sim and cull_cost_table. Plain / Max / shiny / shadow copies keep their card ladder.
**BACKGROUNDS FIRST (same day, user corrected me):** I first ranked the merged ladder by IV and piled the 10 LOWER-IV
background copies -- and pushed that to the phone. He said "wait no, the ones where a costume with a background/card CAN
take the slot of one thats just a costume" and picked "Backgrounds first" (even with goggles Charmander losing three 98%s
to 84/84/82% background copies). `costume_forms.backgrounds_first()` = stable partition, background copies ahead of
costume-only; used by keep_policy topn(bg_first=True) in rule 1a, audit_cull, preflight cos ranking, _lawcheck bucket.
Shinies still displace by IV. LESSON: when he says a richer copy 'takes the slot', richer WINS -- don't rank it by IV.

Related: [[reference-pogo-location-cards-and-s2]], [[pogo-adventure-effect-live-registry]], [[pogo-capped-vs-keepall-bug-class]].
