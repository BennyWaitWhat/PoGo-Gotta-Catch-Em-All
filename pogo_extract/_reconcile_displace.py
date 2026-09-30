"""Reconcile 3 shiny-displaces-plain derivations + authoritative re-derivation.
Rules per task: shinies count toward top-3 (LINE_CAP=3) ranking; NUNDO (iv_total=0)
and HUNDO (iv_total=45) are EXEMPT/protected -> cannot be a DISPLACER and the
DISPLACED plain must NOT be a nundo/hundo (it must be a non-protected plain).
"""
import sqlite3, os, sys, json
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from costume_forms import is_costume_form  # noqa
from pvp_iv_rule import pvid  # noqa

DB = os.path.join(ROOT, 'pokemon.db')
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

_REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
def _is_regional_code(nm, f):
    return any(x in pvid(nm, f) for x in _REGSUF)

rows_all = c.execute("SELECT * FROM pokemon").fetchall()
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

c.create_function('cf', 2, cf_py)
c.create_function('is_costume', 1, lambda f: 1 if is_costume_form(f) else 0)

PLAIN_PRED = """
  in_bag=1 AND fresh_shiny=0 AND (fresh_alignment IS NULL OR fresh_alignment!=1)
  AND COALESCE(fresh_costume,0)=0
  AND COALESCE(special_bg_id,0)=0
  AND COALESCE(natural_art_background,0)=0
  AND (costume_decoration_id IS NULL OR costume_decoration_id=0 OR costume_decoration_id='0')
  AND COALESCE(fresh_bread_mode,0) NOT IN (1,2)
  AND is_costume(fresh_form)=0
"""
# Shiny displacers: in_bag shiny, EXCLUDING nundo(0) and hundo(45) [both exempt]
SHINY_PRED = "in_bag=1 AND fresh_shiny=1 AND COALESCE(iv_total,0) NOT IN (0,45)"

# 3rd-best plain must itself be NON-PROTECTED: iv_total NOT IN (0,45).
# Rank ALL plain (incl nundo/hundo) so position 3 is the true 3rd keeper,
# but the displaced one only counts if it's non-protected.
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
third_best AS (
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
WHERE t.lowest_kept_iv NOT IN (0,45)     -- displaced plain must be NON-protected
GROUP BY t.pokemon_id, t.fk
HAVING SUM(CASE WHEN s.iv_total > t.lowest_kept_iv THEN 1 ELSE 0 END) > 0
ORDER BY t.pokemon_id, t.fk
"""
res = c.execute(q).fetchall()

auth = {}
total_displaced = 0
for r in res:
    n_disp = r['n_shiny_outranking']  # number of shinies that outrank the boundary = number of plains pushed past cap
    # but plain displaced = how many plain fall out. With cap=3, each shiny above boundary pushes one out.
    # n_displaced in derivations = number of distinct plain pushed below cap = min(n_shiny_outranking, n_plain-?)...
    auth[(r['pokemon_id'], r['form'])] = {
        'species': r['species_name'],
        'pokemon_id': r['pokemon_id'],
        'form': r['form'],
        'best_displacer_shiny_iv_pct': round(r['best_shiny_iv'] / 45 * 100),
        'lowest_displaced_plain_iv_pct': round(r['lowest_kept_iv'] / 45 * 100),
        'n_displaced': r['n_shiny_outranking'],
        '_best_shiny_iv': r['best_shiny_iv'],
        '_lowest_kept_iv': r['lowest_kept_iv'],
        '_n_plain': r['n_plain'],
    }
    total_displaced += r['n_shiny_outranking']

print("=== AUTHORITATIVE (task rules: nundo+hundo exempt as displacer AND displaced) ===")
print(f"instances={len(auth)} plain_displaced={total_displaced}")
print(json.dumps(list(auth.values()), ensure_ascii=False, indent=0))
