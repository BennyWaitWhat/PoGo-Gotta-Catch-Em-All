# PoGo Keep Policy (finalized 2026-05-29)

## Intent
The "ultimate organized collection": **every Pokémon must earn a purpose, or it gets trimmed.**
A mon with no purpose → `6 Transfer` (human reviews in-game and transfers; nothing auto-released).
This is *organize*, not *space-clear* — but the caps below deliberately trim dupes.

## Metric (the one rule that governs everything)
**IV (total) is the strength metric everywhere.** Tiebreak: CP, then level.
**CP is used ONLY to gate GL/UL eligibility** (a mon must be able to reach the league cap;
see the CP-floor below). Nowhere else.

## A mon is KEPT if it earns ANY purpose below; otherwise TRIMMED.

### 1. Variant floor (trade stock)
- **Plain** specimens: keep the **3 strongest by IV** per (species, form) — applied to EACH
  distinct stage/form independently (not pooled across the evolutionary line).
- **Cosmetic variants** (costume / event-bg / art / decoration): keep the **TOP-4 by IV per
  cosmetic variant**. **Dynamax = TOP-3, Gigantamax (Gmax) = TOP-6** (user 2026-06-08)
  per (species, form, bread-mode) bundle. All caps now live in `keep_config.json` (dashboard-editable).
- A mon counts as cosmetic if it has any of: `fresh_costume`, a form-encoded costume
  (`is_costume_form`), `special_bg_id`, `natural_art_background`, or `costume_decoration_id`.
- **Variant = (species, form, costume, event-bg, art, decoration, bread-mode).** Each distinct
  cosmetic axis is its own bundle. Purified counts as **normal/plain** (competes in the plain cap).
- Pool **excludes shadows** (§2) and **shinies** (§3) — they're handled separately and do
  NOT consume floor slots.

### 2. Shadow (untradeable in PoGo → battle/collection only)
- Keep the **single strongest by IV** shadow per **(species, form)** — each evo stage separate
  (best shadow Gastly *and* best shadow Gengar).
- PLUS any shadow in the **top-10 GL or UL** IV-rank, **CP-floored** (its ranked form must
  reach the league cap — else the rank is the under-cap-hundo artifact).

### 3. Shiny
- Keep **top 6 by IV per form**. Always protected; do **not** count toward the §1 floor.

### 4. Collection caps — top-N by IV, per (species, form)
- **Hundo (15/15/15): keep ALL** (uncapped).
- **Legendary / Mythical / Ultra Beast / Paradox: top 6.**
- **Legacy / event-only moves: top 4.**
- **XXL (Showcase): top 2 biggest per form** (by weight ∪ by height).

### 5. Keep-all purposes (uncapped)
- **Adventure-Effect species** (Dialga, Palkia, Kyurem, Necrozma, Zacian, Zamazenta).
- **Nundo (0/0/0).**
- **Best Buddy badge.**
- **From Ethan / From Florandez** (incl. their lucky trades).
- **Mighty** (`is_strong`).
- **Location / background card** (special-event-background catches).
- **Dex completeness:** never transfer your **only** copy of a species/form, even with no other purpose.

### 6. PvP (normal, non-shadow)
- **GL and UL: strict top-5 ("Meta") per league**, CP-floored (form reaches the league cap).

## Dropped — no longer a keep-reason (these trim unless another purpose applies)
- **Mega** (delete the `2 Mega` tag entirely).
- **General Lucky** (only Ethan/Florandez lucky is kept, via §5).
- **Gym-defender** (transient) · **decorative badge** · **hatched** · **general traded**.
- **Move-level investment** and **CP/maxed investment** — IV decides; a maxed-but-mediocre-IV
  mon trims if it's not top-N IV (you power up your best-IV ones, so this rarely bites).

## Surfaced assumptions
- "Strongest" = total IV (not league-specific stat-product); units are per **species+form**
  (regionals/formes counted separately).
- Shadows are untradeable (true in PoGo) → that's why they get 1/species, not a 3-trade-stock.
- Purified is tradeable + re-makeable → lumped with normal, no carve-out.
- Caps by axis: **plain = top-3**, **cosmetic (costume/event-bg/art/decoration) = top-4**,
  **Dynamax = top-3, Gmax = top-6** (keep_config.json). Cosmetic dupes past 4 are rare (most cosmetics are 1-of-a-kind
  collectibles already kept by another rule), so the top-4 cosmetic cap rarely bites.

## Consequence to expect
This **tightens** several categories that used to be keep-all → so the transfer pile **grows**:
shadows (was keep-all → 1/species + PvP), legendaries (→ top 6), legacy (→ top 4), mega (dropped).
Verify the new KEEP/TRANSFER counts with a dry-run before applying anything to the device.

## Out of scope (deferred)
- The exact GL/UL meta-species universe size and per-league nuances ("we'll do this later", #5).
