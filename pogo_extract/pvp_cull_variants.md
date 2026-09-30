# PvP Cull Rule Variants

Designs for 5 cull-rule variants that incorporate Great League / Ultra League / Little League PvP rank data. Lower rank number = better PvP IVs (1 is the best possible roll).

## Bag context

- 4819 total pokemon in bag, 4639 with PvP ranks computed (180 are species not in pvpoke - eggs, special forms, etc).
- All variants assume the **existing untouchables layer** still applies on top (hundo/nundo/lucky/shiny/traded/gmax/dmax/location_card/costume/shadow/purified/legendary/mythical/UB/paradox/adventure-effect/legacy-move/best-buddy/deployed/mega-evolved/strong/XXL-top3) - see [cull_engine_v3.py](cull_engine_v3.py:35).
- Existing v3 keeps 4794, transfers 22 (the "top 3 per species/form/costume by IV" rule already protects almost everything). PvP variants should be evaluated for what they would do to a hypothetically *unprotected* bag, since combined-with-v3 numbers barely move.
- Schema fields used: `gl_rank`, `ul_rank`, `ll_rank` (NULL if species absent from pvpoke), `iv_total`, `cp`, `pokemon_id`, `form`.

Rank distribution sanity check:

| Threshold | GL count | UL count | LL count |
|-----------|----------|----------|----------|
| <= 50     | 1070     | 1576     | 117      |
| <= 100    | 1299     | 1831     | 200      |
| <= 500    | 1860     | 2389     | 865      |
| <= 1000   | 2387     | 2808     | 1665     |

LL ranks are sparse because most caught pokemon don't fit under 500 CP at level 50.

---

## Variant 1: Strict PvP (rank <= 100 any league)

**Idea.** Keep any pokemon with rank <= 100 in *any* of GL/UL/LL. Conservative because it adds keeps without ever forcing a transfer.

```python
def variant1_strict_pvp(p):
    if p['gl_rank'] is not None and p['gl_rank'] <= 100: return ('KEEP', 'gl_rank<=100')
    if p['ul_rank'] is not None and p['ul_rank'] <= 100: return ('KEEP', 'ul_rank<=100')
    if p['ll_rank'] is not None and p['ll_rank'] <= 100: return ('KEEP', 'll_rank<=100')
    return None  # defer to other rules
```

**Counts:**

```sql
-- Kept by this rule alone (untouchables layer ignored)
SELECT
  SUM(CASE WHEN gl_rank<=100 OR ul_rank<=100 OR ll_rank<=100 THEN 1 ELSE 0 END) AS keep,
  SUM(CASE WHEN NOT (gl_rank<=100 OR ul_rank<=100 OR ll_rank<=100) OR (gl_rank IS NULL AND ul_rank IS NULL AND ll_rank IS NULL) THEN 1 ELSE 0 END) AS xfer
FROM pokemon WHERE in_bag=1;
-- => keep 1969, xfer 2850

-- Of currently-transferred pokemon under v3, how many V1 re-saves
SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v3='TRANSFER'
  AND (gl_rank<=100 OR ul_rank<=100 OR ll_rank<=100);
-- => 7
```

**Verdict.** Adds keeps; pure ratchet rule. Useful as a layer alongside untouchables.

---

## Variant 2: PvP-bucketed top 3

**Idea.** Group by `(pokemon_id, form)`. Within each bucket, keep the 3 with the lowest best-of-3-leagues rank. This dedupes per-form: you don't need 8 copies of GL Bastiodon, just the 3 best.

```python
def variant2_pvp_top3(rows):
    from collections import defaultdict
    buckets = defaultdict(list)
    for p in rows:
        ranks = [r for r in (p['gl_rank'], p['ul_rank'], p['ll_rank']) if r is not None]
        best = min(ranks) if ranks else None
        buckets[(p['pokemon_id'], p['form'] or 0)].append((best if best is not None else 10**9, p['uid_hex']))
    keep = set()
    for k, lst in buckets.items():
        lst.sort()
        for _, uid in lst[:3]:
            keep.add(uid)
    return keep
```

**Counts:**

```sql
-- Mostly Python, but a CTE form:
WITH ranked AS (
  SELECT uid_hex, pokemon_id, COALESCE(form, 0) AS f,
         MIN(COALESCE(gl_rank, 99999), COALESCE(ul_rank, 99999), COALESCE(ll_rank, 99999)) AS best_rank,
         ROW_NUMBER() OVER (
           PARTITION BY pokemon_id, COALESCE(form, 0)
           ORDER BY MIN(COALESCE(gl_rank, 99999), COALESCE(ul_rank, 99999), COALESCE(ll_rank, 99999))
         ) AS rk
  FROM pokemon WHERE in_bag=1
)
SELECT SUM(CASE WHEN rk<=3 THEN 1 ELSE 0 END) AS keep,
       SUM(CASE WHEN rk>3  THEN 1 ELSE 0 END) AS xfer
FROM ranked;
-- => keep 3268, xfer 1551
```

**Verdict.** The most natural per-species PvP dedupe. Bucket key matches v3's species/form grouping (minus costume, since we don't want costume to fragment PvP buckets - costume is its own untouchable).

---

## Variant 3: Combined PvP + species top IV

**Idea.** Keep top 5 GL + top 5 UL + top 3 by IV, all per species (not per form, on purpose - PvP usefulness applies across all forms of a species). Union of three independent picks.

```python
def variant3_combined(rows):
    from collections import defaultdict
    by_pid = defaultdict(lambda: {'gl': [], 'ul': [], 'iv': []})
    for p in rows:
        pid = p['pokemon_id']
        if p['gl_rank'] is not None: by_pid[pid]['gl'].append((p['gl_rank'], p['uid_hex']))
        if p['ul_rank'] is not None: by_pid[pid]['ul'].append((p['ul_rank'], p['uid_hex']))
        by_pid[pid]['iv'].append((-(p['iv_total'] or 0), -(p['cp'] or 0), p['uid_hex']))

    keep = set()
    for pid, d in by_pid.items():
        d['gl'].sort(); d['ul'].sort(); d['iv'].sort()
        for _, uid in d['gl'][:5]: keep.add(uid)
        for _, uid in d['ul'][:5]: keep.add(uid)
        for _, _, uid in d['iv'][:3]: keep.add(uid)
    return keep
```

**Counts:**

```sql
WITH gl_top5 AS (
  SELECT uid_hex FROM (
    SELECT uid_hex, ROW_NUMBER() OVER (PARTITION BY pokemon_id ORDER BY gl_rank) AS rk
    FROM pokemon WHERE in_bag=1 AND gl_rank IS NOT NULL
  ) WHERE rk <= 5
),
ul_top5 AS (
  SELECT uid_hex FROM (
    SELECT uid_hex, ROW_NUMBER() OVER (PARTITION BY pokemon_id ORDER BY ul_rank) AS rk
    FROM pokemon WHERE in_bag=1 AND ul_rank IS NOT NULL
  ) WHERE rk <= 5
),
iv_top3 AS (
  SELECT uid_hex FROM (
    SELECT uid_hex, ROW_NUMBER() OVER (PARTITION BY pokemon_id ORDER BY iv_total DESC, cp DESC) AS rk
    FROM pokemon WHERE in_bag=1
  ) WHERE rk <= 3
),
keep_set AS (
  SELECT uid_hex FROM gl_top5
  UNION SELECT uid_hex FROM ul_top5
  UNION SELECT uid_hex FROM iv_top3
)
SELECT
  (SELECT COUNT(*) FROM keep_set) AS keep,
  (SELECT COUNT(*) FROM pokemon WHERE in_bag=1) - (SELECT COUNT(*) FROM keep_set) AS xfer;
-- => keep 3676, xfer 1143
```

**Verdict.** Most generous of the standalone PvP rules. Drops LL entirely (LL pokemon are rare; rolled into IV-top-3 anyway). Risks ignoring some unique LL specialists.

---

## Variant 4: Aggressive transfer (rank > 1000 in ALL leagues)

**Idea.** Force-transfer anything that's worse than rank 1000 in *every* league - i.e., bad in all three formats. Inverse of V1: this rule only marks transfers and yields to untouchables.

```python
def variant4_aggressive(p):
    g = p['gl_rank']; u = p['ul_rank']; l = p['ll_rank']
    if g is None or u is None or l is None:
        return None  # no opinion if any league rank missing
    if g > 1000 and u > 1000 and l > 1000:
        return ('TRANSFER', 'rank>1000_all_leagues')
    return None
```

**Counts:**

```sql
-- Solo (no untouchables override)
SELECT
  SUM(CASE WHEN gl_rank>1000 AND ul_rank>1000 AND ll_rank>1000 THEN 1 ELSE 0 END) AS xfer,
  COUNT(*) - SUM(CASE WHEN gl_rank>1000 AND ul_rank>1000 AND ll_rank>1000 THEN 1 ELSE 0 END) AS keep
FROM pokemon WHERE in_bag=1
  AND gl_rank IS NOT NULL AND ul_rank IS NOT NULL AND ll_rank IS NOT NULL;
-- => xfer 1073, keep 3566 (out of 4639 with all ranks)

-- Combined: the spec says "AND not protected", so we apply the v3 untouchable filter first.
-- Of v3-KEEP, how many would be flagged by V4 if untouchables didn't override?
SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v3='KEEP'
  AND gl_rank>1000 AND ul_rank>1000 AND ll_rank>1000;
-- => 1071 (so when V4 runs AFTER untouchables-keep, almost all of these are saved by an untouchable)
-- Net additional transfers under combined V4 + v3 untouchables: ~2 (the 22 v3-TRANSFER minus 7 V1-saves, intersected with V4 condition)
```

**Verdict.** As a *combined* rule with the existing untouchable layer this is nearly a no-op (untouchables already keep ~4794 of the bag). To make V4 meaningful you'd have to *replace* "top 3 per bucket by IV" with PvP-aware variants from V2/V3/V5. Useful only as a tiebreaker in a more selective base ruleset.

---

## Variant 5: Best-of (1 best PvP + 3 IV per species)

**Idea.** Per species: keep the single best PvP-rank pokemon (best of any league) plus the top 3 by IV. Designed for very lean keepers - one battler + a small breeding/trade pool.

```python
def variant5_best_of(rows):
    from collections import defaultdict
    pvp = defaultdict(list); iv = defaultdict(list)
    for p in rows:
        ranks = [r for r in (p['gl_rank'], p['ul_rank'], p['ll_rank']) if r is not None]
        if ranks:
            pvp[p['pokemon_id']].append((min(ranks), p['uid_hex']))
        iv[p['pokemon_id']].append((-(p['iv_total'] or 0), -(p['cp'] or 0), p['uid_hex']))
    keep = set()
    for pid, lst in pvp.items():
        lst.sort()
        if lst: keep.add(lst[0][1])
    for pid, lst in iv.items():
        lst.sort()
        for _, _, uid in lst[:3]:
            keep.add(uid)
    return keep
```

**Counts:**

```sql
WITH best_pvp AS (
  SELECT uid_hex FROM (
    SELECT uid_hex,
           ROW_NUMBER() OVER (
             PARTITION BY pokemon_id
             ORDER BY MIN(COALESCE(gl_rank, 99999), COALESCE(ul_rank, 99999), COALESCE(ll_rank, 99999))
           ) AS rk
    FROM pokemon WHERE in_bag=1
      AND (gl_rank IS NOT NULL OR ul_rank IS NOT NULL OR ll_rank IS NOT NULL)
  ) WHERE rk = 1
),
iv_top3 AS (
  SELECT uid_hex FROM (
    SELECT uid_hex,
           ROW_NUMBER() OVER (PARTITION BY pokemon_id ORDER BY iv_total DESC, cp DESC) AS rk
    FROM pokemon WHERE in_bag=1
  ) WHERE rk <= 3
),
keep_set AS (
  SELECT uid_hex FROM best_pvp UNION SELECT uid_hex FROM iv_top3
)
SELECT
  (SELECT COUNT(*) FROM keep_set) AS keep,
  (SELECT COUNT(*) FROM pokemon WHERE in_bag=1) - (SELECT COUNT(*) FROM keep_set) AS xfer;
-- => keep 2521, xfer 2298
```

**Verdict.** Aggressive trim. Still leaves 1 PvP specialist + 3 IV-top per species, so trade fodder is preserved but bulk duplicates go.

---

## Summary

| Variant | Rule type | Solo keep | Solo xfer | Notes |
|---------|-----------|-----------|-----------|-------|
| V1 Strict PvP   | Add-keep | 1969 | 2850 | Conservative ratchet on top of untouchables |
| V2 PvP top3 by (species,form) | Bucketed dedupe | 3268 | 1551 | Most natural per-form PvP rule |
| V3 5GL+5UL+3IV per species | Union | 3676 | 1143 | Generous; drops LL |
| V4 rank>1000 in ALL | Force-transfer | 3566 | 1073 | Almost no-op when combined with v3 untouchables |
| V5 1 best PvP + 3 IV per species | Lean | 2521 | 2298 | Aggressive trim, preserves 1 battler/species |

**Recommendation note.** V2 is the closest drop-in replacement for v3's existing "top 3 per (species,form,costume) by IV" rule - just swap the IV ordering for best-PvP-rank ordering. V3 and V5 are unions and grow/shrink the keep set vs current. V1 is a pure additive layer; V4 is meaningful only if used to displace the IV-top-3 layer.

Combined-with-untouchables impact on the current 22 v3-TRANSFER pokemon:

- V1 re-keeps 7 (rank <= 100 in some league but no untouchable matched).
- V2/V3/V5 would all re-keep most of the 22 because they expand the bucket-keep set.
- V4 has near-zero combined impact: it only fires on pokemon that the untouchable layer doesn't already save, which is essentially the 22 already heading to transfer.

To see real differentiation, the untouchable+IV-top3 layer in v3 needs to be tightened or partially replaced. That decision is out of scope for this design pass.
