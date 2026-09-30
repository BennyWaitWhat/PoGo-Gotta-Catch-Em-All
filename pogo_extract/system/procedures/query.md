# Query cheat-sheet

**Verified 2026-09-07.**

## Purpose

`system/scripts/query.py` **exists** and is the fast entry point for ad-hoc questions. It answers
from the pre-computed `deep_profiles.json`, so run `deep_profile.py` first if the DB has changed.

```
python system/scripts/query.py stats              # collection-wide counts
python system/scripts/query.py mon <name|uid>     # full dossier
python system/scripts/query.py best gl|ul         # top meta-viable by rank
python system/scripts/query.py powerup [gl|ul|ml] # power-up opportunities by value
python system/scripts/query.py evolve             # evolve-to-meta gems
python system/scripts/query.py lucky              # lucky-trade candidates
```

For anything it does not cover, query `pokemon.db` directly. The SQL below is a starting set.

> Tag names in SQL must match the live tag exactly. Current names include `Legacy Moves` (not
> "Legacy"), `Hundo`, `Nundo`, `XXL`, `GL IV`, `UL IV`, `Traded by E+F`, `Transfer`. `auth_tag_names`
> is semicolon-separated. There are **46 registered tags plus 3 exempt** ones — print the authoritative
> list offline with `python granular_tags.py --audit` (no DB, no device); see `../../RUNBOOK.md` §4.

## Direct SQL (always works)

Open the DB read-only:
```
sqlite3 -readonly pokemon.db
```

### What to power up for Ultra League

```sql
SELECT species_name, iv_atk||'/'||iv_def||'/'||iv_sta AS iv, level, cp,
       ul_rank, ul_stage, ul_chain_ranks
FROM pokemon
WHERE in_bag=1 AND ul_rank=1 AND level<50
ORDER BY level ASC;
```

### Show my shundos

```sql
SELECT species_name, cp, level, form, fresh_alignment
FROM pokemon
WHERE in_bag=1 AND iv_total=45 AND fresh_shiny=1;
```

### The current Transfer pile (the one irreversible output)

```sql
SELECT uid_hex, species_name, cp, iv_atk||'/'||iv_def||'/'||iv_sta AS iv, iv_total
FROM pokemon
WHERE in_bag=1
  AND (';'||COALESCE(auth_tag_names,'')||';') LIKE '%;Transfer;%'
ORDER BY species_name;
```

This mirrors `system/analysis/tagsets/Transfer.txt`. The file is authoritative; the column is the
mirror of the last verified push — so between a recompute and a successful sync they legitimately
differ (right now the column has 25 and the file 26).

**Compare the pile as a uid SET, never a file hash.** `Transfer.txt` is engine-ordered, so its bytes
change on every regeneration even when membership is identical. Diff it against the sorted
`6_Transfer.txt`. And the partition check is the cheapest corruption detector available:
`len(policy_reasons) + len(Transfer) == in_bag`, zero overlap — currently 5701 + 26 == 5727.

### Dossier for a specific species (e.g. Garchomp)

```sql
SELECT uid_hex, species_name, cp, level,
       iv_atk||'/'||iv_def||'/'||iv_sta AS iv, iv_total,
       fresh_shiny, is_lucky, fresh_alignment,
       gl_rank, ul_rank, auth_tag_names,
       move1, move2, move3
FROM pokemon
WHERE in_bag=1 AND species_name LIKE '%garchomp%'
ORDER BY cp DESC;
```

### Best Great League picks I own (meta species, rank 1)

```sql
SELECT species_name, iv_atk||'/'||iv_def||'/'||iv_sta AS iv,
       gl_rank, gl_stage, gl_chain_ranks, level, cp
FROM pokemon
WHERE in_bag=1 AND gl_rank=1
ORDER BY gl_chain_ranks;
```

### XXL specimens (size enum 5)

```sql
SELECT species_name, form, height_m, weight_kg, iv_total, cp
FROM pokemon
WHERE in_bag=1 AND pokemon_size_category=5
ORDER BY species_name, height_m DESC;
```

Note: `best_buddy` was removed as a keep axis on 2026-06-08. `was_best_buddy_badge` still exists as a
column but protects nothing -- do not reintroduce it as a keep rule.

### Costume collection

```sql
SELECT species_name, form, fresh_costume, cp, fresh_shiny
FROM pokemon
WHERE in_bag=1 AND fresh_costume!=0
ORDER BY species_name;
```

### Legacy move holders

```sql
SELECT species_name, cp, move1, move2, move3, auth_tag_names
FROM pokemon
WHERE in_bag=1
  AND (';'||COALESCE(auth_tag_names,'')||';') LIKE '%;Legacy Moves;%'
ORDER BY species_name;
```

## Using deep_profiles.json

The deep profiler output has pre-computed flags. After running
`python system/scripts/deep_profile.py`, load the JSON:

```python
import json
profiles = json.load(open('system/analysis/deep_profiles.json'))

# Shundos
[p for p in profiles if 'SHUNDO' in p['flags']]

# Evolve-to-meta opportunities
[p for p in profiles if any(o.startswith('evolve') for o in p['opps'])]

# PvP-ranked but missing moves
[p for p in profiles if p.get('pvp',{}).get('need_moves')]

# Safe fodder
[p for p in profiles if p['fodder']]
```
