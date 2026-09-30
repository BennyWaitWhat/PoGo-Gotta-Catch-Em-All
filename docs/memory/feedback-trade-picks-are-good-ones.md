---
name: feedback-trade-picks-are-good-ones
description: "User (2026-09-08): trade fodder must be GOOD copies, never 1-2 star ('i dont want to be a dick'). Rule for a species cut: keep top-10 ML + top-10 UL, then Trade = the top 10 of what is LEFT (by ML rank; ended up ML #18-27, 89-93% IV), release the rest. Never pick the worst copies for trading, even though a lucky trade re-rolls IVs."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 13477788-96d8-4172-8c7d-deee9a225a6b
  modified: 2026-09-21T03:31:47.194Z
---

**What I got wrong (Armored Mewtwo, 114 copies):** I proposed "trade the 10 worst -- a lucky trade re-rolls IVs
to a 12/12/12 floor so the bad copies cost nothing." The user: "why would i want to give someone a low iv one?
... i dont want to be a dick and give someone a 1 or 2 star armored mewtwo wtf." Then, after I swung to
"Trade = all 57 remaining 3-star": "only the top 10 can be traded, whatever is left if they're not already in
UL or ML." The rule he means is a RANKED cut, not a threshold: **ML top 10, UL top 10, then Trade = the next
10 by ML rank, Release = everything else** (including the other 3-star copies). Final: Trade = ML #18-27,
88.9-93.3% IV; Release 84 (47 three-star, 37 two-star).

**How to apply:** for any "cut this species down" request, propose buckets in this order -- league keepers by
rank, then a trade pool taken from the TOP of the remainder (never the bottom), then release -- and say the
IV range of the trade pool out loud. Trades are a gift to another player; IV re-roll mechanics are not a
reason to hand out junk. The tags are static labels: Armored ML / Armored UL / Armored Trade / Armored
Release, pushed by push_armored_plan.py (deltas, one session, verified), all four in granular_tags
EXEMPT_TAGSETS. Mewtwo is rarity keep-all, so the release list is a LABEL for hand release, never the
Transfer pile.

**Tooling lesson (crashed 3x):** WANT/allu were NORMALISED uids (leading zeros stripped, from int(u,16)),
while pokemon.db and the tagset files use zero-padded 16-hex -- a mirror UPDATE keyed on the normalised
form finds no row (`row[0]` on None). Map back through a canon dict before touching the DB or files.

Related: [[pogo-adventure-effect-live-registry]], [[pogo-granular-tags-2026-09]], [[feedback-tell-me-what-to-expect]].

2026-09-19 -- the standing offer list. "Remote Trade" (his own Forever-Friends tag) now holds BOTH:
  * SHINIES: every copy past his best 2 of a (species, form) group that holds more than 2 -- no IV floor (a 2-star
    floor was tried, cut 260 -> 67, and he reverted it the same day), minus already-traded/lucky, shadow, untradable,
    <30-day catches and collectibles.
  * NON-SHINIES: "i save pokemon specifically just to have high quality trades" -- his rules name no trade reserve, so
    the reserve IS the copy the LINE CAP keeps and nothing else: offered only when policy_reasons == {variant_floor},
    never a PvP asset, collectible, trophy, last copy or anything in the pile.
Then "a cap of 3 or 6 for each pokemon regardless if shiny or not" + "fix everything now that you're seeing whats
wrong". Reading the tag mix of the offers exposed two bugs: grouping by (species, form) offered 64 Pikachu including
copies that were the BEST of their own costume (Variant #1 appeared 40 times), and the shiny side filtered on
collectible COLUMNS instead of keep REASONS, so Adventure-Effect and Evolve-Shiny mons were being offered. Final rule
in remote_trade_picks.py: group by COSMETIC VARIANT (species, form, costume, art bg, Dmax/Gmax, shiny), keep the best
2 of each, offer a spare only when its keep reasons are EXACTLY {shiny}, {variant_floor} or {rarity} (rarity = a spare
legendary/mythical/UB/paradox inside its cap, added 2026-09-19), never one tagged Variant #1 / Shiny - Only One /
Last Copy, then cap SPECIES_CAP=3 per species (user 2026-09-19: "make it 3"); 569 offers on 2026-09-20. The quality
bar lives in WHICH REASON keeps a mon, never in an IV threshold.
