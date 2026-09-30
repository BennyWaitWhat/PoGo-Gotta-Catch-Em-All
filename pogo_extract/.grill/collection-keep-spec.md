# Collection Keep Spec — grilled 2026-06-08

## Intent
One curated PoGo box that is three things at once:
1. **Pokémon master** — own every line/form.
2. **Best ally** — ≥3 highest-IV of *everything* on hand to trade to friends.
3. **Hyper-competitive** — the best GL / UL / ML pieces.

**Priority when they collide:** keep-everything-special + 3-for-trade **>** leanness. Leanness is *last* — cut only true redundancy, never breadth. (An earlier "competitive-first, completeness-distant" framing was wrong and is discarded.)

## The unifying model
- **Spine — comb for highest IV per (stage, form):** keep the **top-3 by total IV** of every stage/form. This single rule covers trade stock (≥3), completeness, AND Master League (ML rewards highest IV → your hundo + top-3 floor). Shinies count toward the top-3 (you trade shinies) → the floor is the **merged plain+shiny top-3 by IV** (the shiny-floor rule).
- **GL + UL are the ONLY league exceptions** — because they reward the *opposite* of high IV (low-attack spreads). Kept = each species' **own** rank ≤5 (computed per-species every crawl — NOT a blanket spread) **plus** every 0/15/15 kept flat as a novelty/fallback.
- **ML needs no rule** — best ML = highest IV = already kept by the spine + hundo.
- **Every distinct variant is its own bundle** (form / costume / shiny / shadow / dynamax / gmax), each with its own cap. Never merged across variants.

## Special-status keeps (on top of the spine)
| Axis | Cap | Detected by |
|---|---|---|
| Shiny | top-20 / variant | `fresh_shiny` |
| Hundo (15/15/15) / Nundo (0/0/0) / 0-15-15 | all | iv |
| GL IV / UL IV | per-species rank ≤5 (+ all 0/15/15) | `gl_rank`/`ul_rank` |
| Showcase / XXL | **top-2 by showcase score** (h·0.80 + w·0.15 + iv·0.05), XXL only | `size_category=5` |
| Legendary/Mythical/UB/Paradox | top-12 / variant (**Mewtwo = ALL**) | references roster |
| Legacy moves | all (Absol cap 10) | `legacy_accurate` |
| Costume / Event | top-4 / cosmetic variant | costume/bg/art/decoration/costume-form |
| Location card | all | `fresh_has_location_card` |
| Shadow | best IV + best GL + best UL / variant | `fresh_alignment=1` |
| Dynamax / Gmax | **Dynamax top-3, Gmax top-6** (specials ride on top) | `fresh_bread_mode` 1/2 |
| Origin (Ethan/Florandez traded or lucky) | all | owner ∈ E+F |
| Adventure-effect / Mighty | all | `adventure_effects_left` / `fresh_is_strong` |
| Dex-only | the sole copy of any (species, form) | sole (pid, cf) |

## Resolved this grill
- **The top-3 floor of every line is KEPT** (it's the trade stock). This closes the open "how aggressive on the non-competitive floor" fork — e.g. the 152 Kanto "floor" plains stay. Only the 4th+ dupes, shiny-displaced *sole*-floor, and cap-excess ever leave.
- **Shiny-floor rule stays** — you trade shinies, so a higher-IV shiny legitimately occupies a top-3 slot.
- **Showcase → top-2 by combined score, XXL only** (replaced the top-2h+1w 3-mon proxy). Verified: XXL kept 222→218.
- **ML → no separate rule.**
- **GL/UL ranks are per-species, never blanket** — proved against the live bag (0/15/15 ranks GL #1 for 8 of your species, #50 Lapras … #956 Arcanine).

## Surfaced assumptions (override if wrong)
- "≥3 for trade" → cap is exactly **3** per (stage, form). Deeper stock for popular trade species is not assumed.
- Shadow kept as best-IV + best-GL + best-UL (not keep-all) — carried from prior sessions.
- Legendary top-12 / legacy-all / location-all / origin-all / AE-all / dynamax-gmax top-8 — carried from your prior explicit calls; not re-litigated this grill.

## Out of scope — explicitly NOT special
- **Lucky → normal** (your call).
- **Purified → normal** — the dex sole-copy rule already guarantees you never lose the only one of a line (your exact caveat).
- **XXS → ignored** (your call).
- **Best Buddy → nuked** this session (0 sole-BB mons; nothing transferred).
- **`is_three_star` (80%+ IV, ~half the bag) → not a novelty**; already caught by the IV floor + GL/UL.
- **Corner IV spreads** (15/15/0, 0/0/15, …) → no rule; ~1 each in the bag.

## Process commitments (the reason this spec exists)
- Detect each axis from the **live proto / DB**, never from memory or an agent's claim.
- **Recrawl FIRST** before any tag sync (the bag drifts every turn).
- The Transfer tag is the review pile; the **user** does the irreversible in-game release; the pile is pre-flighted keeper-free across every axis above before it's blessed.
