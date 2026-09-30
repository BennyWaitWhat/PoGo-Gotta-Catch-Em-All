# Tag Rule Verification Report
Generated: 2026-05-21

---

## 1. Nundos (server=29, rule=37, to-add=8)

**Verdict: ARTIFACT - do NOT reconcile. All 8 to-add rows are phantom/placeholder entries (pokemon_id=0).**

### Findings

The rule `iv_atk=0 AND iv_def=0 AND iv_sta=0` matches 37 in-bag rows. Of those 37:
- 27 have a real pokemon_id (!=0) - these are genuine zero-IV pokemon.
- 10 have pokemon_id=0, species_name="pid0", cp=0 - these are placeholder/ghost rows, not real pokemon.

The server has 29 Nundos tagged. Breakdown:
- 2 of the 10 pid=0 rows are already tagged "Nundos" on the server (uid_hex: `0fd651da82dfed33`, `8de05237b3bcdabd`).
- The 8 to-add rows are the remaining 8 pid=0 rows with auth_tag_names=null.

**The 8 to-add uid_hex values (all pid=0 ghosts):**
- `032c7bec5e8b2198`
- `0445a7076a5774f4`
- `9223054502498ba0`
- `9710c3d051ffab76`
- `996f40c8ee63f7dd`
- `a5a7f28fdbd73595`
- `ab6e2b8965976776`
- `d00deb51daeb9a7e`

All 8 have iv_atk=0, iv_def=0, iv_sta=0, iv_total=0 - the IV columns are not NULL, they are genuinely 0. However pokemon_id=0 and cp=0 conclusively identifies them as placeholder/dedupe-cache rows, not real caught pokemon. They satisfy the rule predicate by coincidence (default 0 values).

The 2 already-tagged pid=0 rows represent prior sessions where tagging happened to hit these ghost rows before the issue was understood. The 29 server-side Nundos = 27 real pokemon + 2 accidentally-tagged ghosts. The "true" real Nundos count is 27.

**Recommended action:** Leave alone. Do not tag the 8 pid=0 rows. Consider whether the 2 already-tagged pid=0 ghosts (`0fd651da82dfed33`, `8de05237b3bcdabd`) should be untagged as cleanup, but that is cosmetic. Rule is fine; the audit rule should ideally filter `AND pokemon_id != 0` to avoid this false positive in future runs.

---

## 2. Adventure Eff (server=16, rule=17, to-add=1)

**Verdict: REAL drift. The 1 to-add is a genuine Adventure Effect pokemon that is untagged.**

**uid_hex:** `781e883559062a39`
- species: Eternatus (pokemon_id=890)
- iv_atk=11, iv_def=14, iv_sta=10, iv_total=35
- fresh_pokemon_badge=1 (non-zero, satisfies rule)
- auth_tag_names=null (not yet tagged anything)

The `fresh_pokemon_badge` column has only two values in the bag: 0 (4402 rows) and 1 (17 rows). The rule `fresh_pokemon_badge != 0` is reliable - this is a binary field representing the Adventure Effect badge on a pokemon. The value 1 for this Eternatus is a valid signal.

The server has 16 tagged; the rule finds 17. The discrepancy is exactly this one Eternatus that was caught/obtained after the last tag sync and has not been tagged yet.

**Recommended action:** RECONCILE - add "Adventure Eff" tag to `781e883559062a39` (Eternatus).

**Note:** This uid also appears in the Legacy to-add list below - it is the same pokemon needing two tags added.

---

## 3. Legacy (server=252, rule=253, to-add=1)

**Verdict: REAL drift. The 1 to-add is a genuine legacy-move pokemon confirmed by detect_legacy.py output.**

**uid_hex:** `781e883559062a39`
- species: Eternatus (pokemon_id=890)
- legacy_moves: ["DYNAMAX_CANNON"]
- iv_total: 35

Verification against pvpoke_gamemaster.json confirms DYNAMAX_CANNON is in Eternatus's `eliteMoves` list (not just chargedMoves - it appears in both, meaning it is explicitly flagged as elite/legacy). detect_legacy.py correctly identifies this as a legacy move via the `if cm in elite` branch. The move was confirmed in the DB as move2=482, which move_id_to_name.json maps to "DYNAMAX_CANNON".

legacy_accurate.json has 253 entries total. The server has 252 tagged. The missing one is this same Eternatus - a recently-obtained pokemon that cleared the detect_legacy.py check but was not yet tagged.

**Recommended action:** RECONCILE - add "Legacy" tag to `781e883559062a39` (Eternatus). This is the same pokemon as the Adventure Eff to-add above: a single tagging call adds both tags.

---

## Summary Table

| Tag          | Server | Rule | Verdict  | Action                                           |
|--------------|--------|------|----------|--------------------------------------------------|
| Nundos       | 29     | 37   | ARTIFACT | Leave alone. 8 to-add are pid=0 ghost rows.      |
| Adventure Eff| 16     | 17   | REAL     | Add tag to 781e883559062a39 (Eternatus).         |
| Legacy       | 252    | 253  | REAL     | Add tag to 781e883559062a39 (Eternatus, same).   |

Adventure Eff and Legacy resolve with a single operation: tag `781e883559062a39` with both "Adventure Eff" and "Legacy".
