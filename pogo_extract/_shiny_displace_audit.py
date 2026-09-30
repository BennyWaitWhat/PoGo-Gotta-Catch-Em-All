"""Shiny-would-displace-kept-plain audit. Pure-SQL ranking/comparison via window functions,
with keep_policy's exact cf() form-fold and is_costume_form set registered as SQLite UDFs."""
import sqlite3, os, sys, json
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from costume_forms import is_costume_form, COSTUME_FORMS  # noqa

DB = os.path.join(ROOT, 'pokemon.db')
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

# ---- Replicate keep_policy.cf() form-fold mapping EXACTLY (lines 125-139) ----
_REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
# pvid is needed for _is_regional_code. Import from pvp_iv_rule like keep_policy does.
from pvp_iv_rule import pvid  # noqa

def _is_regional_code(nm, f):
    return any(x in pvid(nm, f) for x in _REGSUF)

rows_all = c.execute("SELECT * FROM pokemon").fetchall()  # cf base_form is built over ALL rows in keep_policy (rows = in_bag=1 only!)
# NOTE: keep_policy builds base_form from `rows`, which is `WHERE in_bag=1`. Match that exactly.
rows_inbag = [r for r in rows_all if r['in_bag'] == 1]

_basecnt = defaultdict(Counter)
for r in rows_inbag:
    _f = r['form'] or 0
    _reg = (r['form_region'] or '').strip().lower()
    if _f != 0 and _reg in ('', 'normal', 'kantonian', 'none', 'null') and not _is_regional_code(r['species_name'], _f):
        _basecnt[r['pokemon_id']][_f] += 1
base_form = {pid: cnt.most_common(1)[0][0] for pid, cnt in _basecnt.items() if len(cnt) == 1}

def cf_py(pokemon_id, form):
    _f = form or 0
    return base_form.get(pokemon_id, _f) if _f == 0 else _f

# register UDFs
c.create_function('cf', 2, cf_py)
c.create_function('is_costume', 1, lambda f: 1 if is_costume_form(f) else 0)

# report merged species (where a form-0 and a single nonzero base-region form coexist among in_bag)
merged = []
for pid, f0 in base_form.items():
    forms_present = set((r['form'] or 0) for r in rows_inbag if r['pokemon_id'] == pid)
    if 0 in forms_present and f0 in forms_present:
        nm = next(r['species_name'] for r in rows_inbag if r['pokemon_id'] == pid)
        merged.append((pid, nm, f0))

# ---- PURE SQL: rank PLAIN by iv_total per (pokemon_id, cf), 3rd-best plain vs max non-hundo shiny ----
# PLAIN per keep_policy: fresh_alignment!=1 AND NOT fresh_shiny AND _truly_plain.
# _truly_plain: fresh_costume in(0/NULL) AND special_bg_id in(0/NULL) AND natural_art_background in(0/NULL)
#               AND (costume_decoration_id in(0/NULL) OR ='0') AND fresh_bread_mode NOT IN (1,2)
#               AND NOT is_costume_form(fresh_form).
PLAIN_PRED = """
  in_bag=1 AND fresh_shiny=0 AND (fresh_alignment IS NULL OR fresh_alignment!=1)
  AND COALESCE(fresh_costume,0)=0
  AND COALESCE(special_bg_id,0)=0
  AND COALESCE(natural_art_background,0)=0
  AND (costume_decoration_id IS NULL OR costume_decoration_id=0 OR costume_decoration_id='0')
  AND COALESCE(fresh_bread_mode,0) NOT IN (1,2)
  AND is_costume(fresh_form)=0
"""
# SHINY pool: in_bag fresh_shiny, EXCLUDING hundos (iv_total=45).
SHINY_PRED = "in_bag=1 AND fresh_shiny=1 AND COALESCE(iv_total,0)!=45"

q = f"""
WITH plain AS (
  SELECT pokemon_id, species_name, cf(pokemon_id, form) AS fk, iv_total, cp,
         ROW_NUMBER() OVER (
           PARTITION BY pokemon_id, cf(pokemon_id, form)
           ORDER BY COALESCE(iv_total,0) DESC, COALESCE(cp,0) DESC
         ) AS rn,
         COUNT(*) OVER (PARTITION BY pokemon_id, cf(pokemon_id, form)) AS n_plain
  FROM pokemon
  WHERE {PLAIN_PRED}
),
third_best AS (   -- the 3rd-best plain (LINE_CAP=3 boundary) for groups with >=3 plain
  SELECT pokemon_id, fk, MAX(species_name) AS species_name, iv_total AS lowest_kept_iv, n_plain
  FROM plain
  WHERE rn = 3
  GROUP BY pokemon_id, fk
),
shiny AS (
  SELECT pokemon_id, cf(pokemon_id, form) AS fk, iv_total
  FROM pokemon
  WHERE {SHINY_PRED}
)
SELECT t.pokemon_id, t.species_name, t.fk AS form,
       t.lowest_kept_iv,
       MAX(s.iv_total) AS best_shiny_iv,
       SUM(CASE WHEN s.iv_total > t.lowest_kept_iv THEN 1 ELSE 0 END) AS n_shiny_outranking,
       t.n_plain
FROM third_best t
JOIN shiny s ON s.pokemon_id = t.pokemon_id AND s.fk = t.fk
GROUP BY t.pokemon_id, t.fk
HAVING SUM(CASE WHEN s.iv_total > t.lowest_kept_iv THEN 1 ELSE 0 END) > 0
ORDER BY t.pokemon_id, t.fk
"""
res = c.execute(q).fetchall()

instances = []
for r in res:
    instances.append({
        'species': r['species_name'],
        'pokemon_id': r['pokemon_id'],
        'form': r['form'],
        'best_shiny_iv_pct': round(r['best_shiny_iv'] / 45 * 100),
        'lowest_kept_plain_iv_pct': round(r['lowest_kept_iv'] / 45 * 100),
        'n_plain_kept': min(3, r['n_plain']),
        'n_shiny_outranking': r['n_shiny_outranking'],
        '_best_shiny_iv': r['best_shiny_iv'],
        '_lowest_kept_iv': r['lowest_kept_iv'],
    })

print("MERGED (form-0 folded into single nonzero base-region form, both present in_bag):")
for pid, nm, f0 in sorted(merged):
    print(f"  pid={pid} {nm} form0->{f0}")
print(f"merged_count={len(merged)}  total_merged_base_form_entries={len(base_form)}")
print()
print(f"TOTAL_INSTANCES={len(instances)}")
print(json.dumps(instances, indent=1))
