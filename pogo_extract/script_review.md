# Script Review: cull_v9 / pogo_pipeline / audit_all_tags / reconcile_from_drift

Reviewed: 2026-05-21. DB queries used to confirm each finding is real, not speculative.

---

## CRITICAL

### C1 - cull_v9.py:151-159: xxl_top3 uses top-3 weight only; spec requires top-2-weight UNION top-2-height

**File/line:** `cull_v9.py`, `build_ctx()`, lines 151-159 (the xxl_groups loop).

**Problem:** The `xxl_top3_uids` bucket sorts by `-weight_kg` and takes `lst[:3]`. Height is never considered. The spec (and `audit_all_tags.py` `rule_jumbo`) define JUMBO as top-2-weight UNION top-2-height per `(pokemon_id, form, fresh_costume)` bucket.

**Why it is wrong:** Two divergences from spec:
1. cull uses N=3 (heaviest) but spec says N=2 for weight.
2. cull does not include the top-2-tallest dimension at all.

**DB confirmation:** In the bucket `(710, 2644, 0)` (Pumpkaboo XXL, 5 pokemon):
- Heaviest three: `70dfce9b` (17.48 kg), `28146ba5` (15.43 kg), `1e10371a` (15.21 kg).
- Tallest two: `5a8d0b0f` (0.783 m), `70dfce9b` (0.774 m).
- Spec JUMBO set: `{70dfce9b, 28146ba5, 5a8d0b0f}` (union of top-2w and top-2h).
- cull xxl_top3 set: `{70dfce9b, 28146ba5, 1e10371a}` (top-3 weight only).
- `1e10371a` is wrongly protected (3rd heaviest, not tall); `5a8d0b0f` is wrongly unprotected (2nd tallest, not in weight-top-3).
- Same pattern confirmed in Gourgeist `(711, 2648, 0)`: `6abb2d6b` (33.25 kg, 1.557 m) is cull-protected but not JUMBO-spec; the 2nd-tallest is already covered by weight-top-2 there.
- Currently `5a8d0b0f` (Pumpkaboo) is saved by `user_tag_JUMBO` and `preevo_top2_rank2`, so no wrong transfer today. But if the JUMBO tag is removed by drift reconcile, only `preevo_top2_rank2` remains -- fragile.

**Fix in `cull_v9.py` `build_ctx()`:**
```python
# replace the xxl_top3 block with:
xxl_top2_weight_height = set()
for lst in xxl_groups.values():
    for p in sorted(lst, key=lambda x: -(x['weight_kg'] or 0))[:2]:
        xxl_top2_weight_height.add(p['uid_hex'])
    for p in sorted(lst, key=lambda x: -(x['height_m'] or 0))[:2]:
        xxl_top2_weight_height.add(p['uid_hex'])
ctx['xxl_top3_uids'] = xxl_top2_weight_height  # key name can stay for compat
```
Update the rule name/label from `xxl_top3_heaviest` to `jumbo_top2` for clarity.

---

## HIGH

### H1 - cull_v9.py: No NULL-rank protection rule; spec says NULLs must be treated as PROTECTED

**File/line:** `cull_v9.py`, `build_ctx()` `qualify()` function (lines 205-219), and `PROTECTION_RULES` (no rule covers this case).

**Problem:** When `compute_all_ranks.py` fails to produce rank data for a species (e.g., new form not yet in the ranker), all three rank columns (`gl_rank`, `ul_rank`, `ll_rank`) are NULL. The `qualify()` function correctly skips NULL-rank rows (`if r is None or r > 10: continue`), so these pokemon never enter `gl_qualify_uids` / `ul_qualify_uids`. No other rule catches them. They can be TRANSFERRED.

**Why it is wrong:** The spec states "NULLs must be treated as PROTECTED (never culled on missing data)." The intent is: if the ranker didn't run for a species, we must not assume it has no good PVP value.

**DB confirmation:** Flittle (pid=955, speciesId=`flittle`) has 3 in-bag instances, all with `gl_rank IS NULL`, `ul_rank IS NULL`, `ll_rank IS NULL`. One (`ea8ce6055b7a61d5`, iv_total=39, form=3268) has `cull_decision_v9='TRANSFER'` with reason `no_keep_rule`. The other two are saved only by `preevo_top2_rank1/2` (iv_total=41). The transferred one is rank 3 in the preevo bucket and has no other protection.

**Fix in `cull_v9.py`:** Add a rule (or a check inside the existing rank rules) that protects any pokemon where ALL three rank columns are NULL:
```python
Rule('null_rank_protection',
     lambda p, _: 'null_rank_uncomputed'
         if p['gl_rank'] is None and p['ul_rank'] is None and p['ll_rank'] is None else None,
     'gl_rank IS NULL AND ul_rank IS NULL AND ll_rank IS NULL'),
```
Insert this rule early in `PROTECTION_RULES` (before the `gl_pvp`/`ul_pvp` rules). Alternatively, scope it to species where at least one other in-bag member of the same `pokemon_id` HAS a rank (so it catches rank-compute failures, not legitimately unranked species). The broader blanket version is safer per spec.

---

## MEDIUM

### M1 - cull_v9.py:98 sanity SQL for user_tag is a string-equality check, not a tag-membership check

**File/line:** `cull_v9.py`, `PROTECTION_RULES`, `Rule('user_tag', ...)` sanity_sql (line 98).

**Problem:** The sanity SQL is:
```sql
auth_tag_names IS NOT NULL AND auth_tag_names NOT IN ('','CLAUDE_TX','Traded')
```
This checks if the raw `auth_tag_names` string is not one of three literal values. It does NOT handle multi-tag strings containing only excluded tags (e.g., `auth_tag_names='CLAUDE_TX;Traded'`). Such a string passes `NOT IN` (the combined string is not in the exclusion list), so the sanity check would report the pokemon as expected-to-be-protected -- but the rule correctly returns `None` (all tags are excluded), so the pokemon may be TRANSFER. This would cause a false sanity alarm.

**DB confirmation:** No pokemon currently has `auth_tag_names='CLAUDE_TX;Traded'` (verified by query), so this is latent. However there are 5 pokemon with `auth_tag_names='CLAUDE_TX'` that are correctly being transferred -- those are handled correctly because `'CLAUDE_TX' IN ('','CLAUDE_TX','Traded')`.

**Fix:** Replace the sanity SQL with a more accurate approximation, or just leave it as a known gap since it only generates false-positive sanity noise (never a wrong cull decision):
```python
# More precise: check that after removing excluded tags, something remains
"auth_tag_names IS NOT NULL AND auth_tag_names != '' "
"AND replace(replace(auth_tag_names,'CLAUDE_TX',''),'Traded','') != replace(auth_tag_names,'CLAUDE_TX;Traded','') "
```
Or simply widen the sanity SQL to exclude any row where all tags are in the excluded set (SQLite doesn't support this elegantly -- a comment noting the limitation is acceptable).

---

## LOW

### L1 - reconcile_from_drift.py:33-34: warm-up call overlaps with loop start; adds[0] is sent twice

**File/line:** `reconcile_from_drift.py`, lines 33-34.

**Problem:**
```python
bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], adds[:1]); time.sleep(0.5)   # warm-up: sends adds[0]
for i in range(0, len(adds), 60):                                                    # loop: sends adds[0..59] first
    bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], adds[i:i+60]); time.sleep(0.3)
```
`adds[0]` is tagged in the warm-up, then again in the first loop iteration (`adds[0:60]`). If `bulk_tag_many` is idempotent (adding to a set), this causes no incorrect result, but it is a logic error and adds an extra round-trip for every tag operation.

**Fix:**
```python
bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], adds[:1]); time.sleep(0.5)
for i in range(1, len(adds), 60):  # start at 1, not 0
    bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], adds[i:i+60]); time.sleep(0.3)
```

### L2 - audit_all_tags.py: rule_jumbo bucket key uses `p['form']` not `p['fresh_form']`; inconsistent with cull

**File/line:** `audit_all_tags.py`, `rule_jumbo()` line 35: `g[(p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)]`.

**Problem:** The bucket key mixes a persisted column (`form`) with a fresh column (`fresh_costume`). `cull_v9.build_ctx()` xxl_groups uses `p['form']` for form and `p['fresh_costume']` for costume (same as audit). However `form` vs `fresh_form` can differ if a form-change event happened between pipeline runs without a full reconcile -- both scripts use `p['form']` (not `p['fresh_form']`), so they are consistent with each other. This is only a concern if `form` and `fresh_form` diverge; in the current DB they are the same for all in-bag pokemon. Flag as low priority to align both scripts to use `fresh_form` for consistency with other fresh_* fields.

**DB check:** `SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND form != fresh_form` returns 0. No current impact.

---

## Verified Correct

The following areas were audited and found correct:

- **GL/UL strict parameter:** `qualify(..., 1425, False)` correctly uses `>=` for GL; `qualify(..., 2425, True)` correctly uses `>` for UL.
- **NULL rank skip in qualify():** `if r is None or r > 10: continue` correctly excludes NULL-rank rows from PVP candidate sets. This is correct for the qualify function itself; the missing protection rule is a separate issue (H1 above).
- **Sort order (rank/pct tiebreak):** Both `cull_v9` and `audit_all_tags` sort by `(rank_col ASC, -pct_col DESC)` -- consistent, correct.
- **GL/UL qualify set identity:** cull and audit produce identical `gl_qualify_uids` / `ul_qualify_uids` sets (verified by set difference = empty on live DB).
- **has_tag parsing in audit_all_tags.py:** `name in [t for t in a.split(';') if t]` correctly handles semicolon-delimited tag strings including tags with spaces (e.g., `'From Ethan'`, `'Adventure Eff'`).
- **Tag drift direction:** `add = ruleset - srv` (missing from server, needs adding); `rem = srv - ruleset` (stale on server, needs removing). Correct.
- **uid_hex / uid conversion in reconcile:** `u + 2**64` for negative signed int correctly produces the unsigned 64-bit representation matching uid_hex. Verified against live data.
- **CP formula consistency:** Both scripts use `CPM_L50 = 0.84029999` and the identical formula. No divergence.
- **Pipeline step ordering:** tag refresh runs before cull, so `auth_tag_names` is populated before `cull_v9` reads it.
- **ll_rank threshold:** `_rank('ll_rank')` uses `PVP_RANK_KEEP = 15`; GL/UL `qualify()` uses hard-coded `10`. Correct per spec.
