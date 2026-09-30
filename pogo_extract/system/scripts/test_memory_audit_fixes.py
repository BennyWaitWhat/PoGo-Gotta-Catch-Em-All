"""Offline regression checks for the recovered memory audit's two remaining code gaps."""
import ast
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import evolvable_forms
import preflight_transfer as preflight


def main():
    # Load the production function without running the report's top-level bag query/output.
    path = ROOT / 'evo_hundo_gap.py'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'source_can_evolve')
    scope = {'evolvable_forms': evolvable_forms}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), scope)
    eligible = scope['source_can_evolve']
    forms = {v: int(k) for k, v in json.loads((ROOT / 'form_enum.json').read_text()).items()}
    costumes = {v: int(k) for k, v in json.loads((ROOT / 'costume_enum.json').read_text()).items()}

    def source(pid, form, costume=0):
        f = forms[form] if form else 0
        return dict(pokemon_id=pid, form=f, fresh_form=f, fresh_costume=costume)

    # Ordinary costumes evolve; Noevolve has species-specific game-master exceptions.
    assert eligible(source(572, 'MinccinoNormal', costumes['Fashion2025']))[0]
    assert eligible(source(1, 'BulbasaurNormal', costumes['Jan2020Noevolve']))[0]
    assert not eligible(source(25, 'PikachuNormal', costumes['Jan2020Noevolve']))[0]
    assert eligible(source(1, 'BulbasaurNormal'))[0]
    assert eligible(source(0, None))[0]  # existing species-graph fallback for unreadable forms

    def card(uid, form, iv, cp=100, enum=7, pid=1, holder=1):
        return dict(uid_hex=uid, pokemon_id=pid, form=form, iv_total=iv, cp=cp,
                    fresh_has_location_card=holder, fresh_loc_card_enum=enum)

    bag = [card('best', 0, 44), card('second', 163, 43),
           card('excess0', 0, 42), card('excess163', 163, 41),
           card('hundo', 163, 45), card('nundo', 0, 0),
           card('unknown-card', 0, 1, enum=0), card('other-card', 0, 1, enum=8),
           card('other-form', 999, 1), card('no-card', 0, 44, holder=0),
           card('tie-a', 0, 40, cp=200, pid=2), card('tie-b', 0, 40, cp=100, pid=2)]
    canonical = lambda r: 163 if r['pokemon_id'] == 1 and r['form'] == 0 else r['form']
    with patch.object(preflight.keep_config, 'cap', return_value=1), \
            patch.object(preflight.keep_config, 'species_cap', side_effect=lambda axis, pid, default: 2 if pid == 1 else default):
        actual = preflight._loc_card_kept_uids(bag, canonical)
    assert actual == {'best', 'second', 'hundo', 'nundo', 'unknown-card',
                      'other-card', 'other-form', 'tie-a'}, actual
    print('PASS: costume/form eligibility, canonical card pools, separate variants/cards, '
          'trophy exemptions, unknown cards, per-species caps and CP tie-break.')


if __name__ == '__main__':
    main()
