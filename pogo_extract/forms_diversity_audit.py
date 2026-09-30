"""Forms diversity audit: per-species form coverage, gaps, surpluses, costumes."""
import json, sqlite3, os
from collections import defaultdict

DB = 'pokemon.db'
FORM_CAT = 'form_category.json'
OUT = 'agent_outputs/forms_diversity_audit.json'

with open(FORM_CAT) as f:
    form_cat = json.load(f)

# Build reference: per pokemon_id -> {form_id: {form_name, category, species}}
ref_by_pid = defaultdict(dict)
species_by_pid = {}
for k, v in form_cat.items():
    pid_s, frm_s = k.split('_')
    pid = int(pid_s); frm = int(frm_s)
    ref_by_pid[pid][frm] = {
        'form_name': v.get('form_name'),
        'category': v.get('category'),
    }
    species_by_pid[pid] = v.get('species')

conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("""
    SELECT pokemon_id, species_name, form, display_costume, COUNT(*) as cnt
    FROM pokemon WHERE in_bag=1
    GROUP BY pokemon_id, species_name, form, display_costume
""")
held = cur.fetchall()

# Aggregate held forms/costumes per species
held_forms_by_pid = defaultdict(lambda: defaultdict(int))   # pid -> form -> count
held_costumes_by_pid = defaultdict(lambda: defaultdict(int))  # pid -> costume_id -> count
total_by_pid = defaultdict(int)
species_name_by_pid = {}
for pid, sp_name, frm, costume, cnt in held:
    held_forms_by_pid[pid][frm] += cnt
    total_by_pid[pid] += cnt
    species_name_by_pid[pid] = sp_name
    if costume and costume > 0:
        held_costumes_by_pid[pid][costume] += cnt

# Build per-species report
species_reports = {}
all_pids = sorted(set(list(species_name_by_pid.keys()) + list(ref_by_pid.keys())))

for pid in all_pids:
    species = species_name_by_pid.get(pid) or species_by_pid.get(pid) or f'Pokemon_{pid}'
    ref_forms = ref_by_pid.get(pid, {})  # {form_id: {form_name, category}}
    held = held_forms_by_pid.get(pid, {})  # {form_id: count}
    costumes = dict(held_costumes_by_pid.get(pid, {}))

    # Reference catalog excludes pure 'default' since form=0 covers default in DB
    catalog_non_default = {f: d for f, d in ref_forms.items() if d.get('category') != 'default' or len(ref_forms) > 1}
    # Simpler: list all known reference form variants
    catalog_all = ref_forms

    total_held = total_by_pid.get(pid, 0)
    if total_held == 0 and not ref_forms:
        continue

    # Distinct forms held: filter to known forms in catalog (skip garbage form values)
    distinct_forms_held_known = sum(1 for f in held if f == 0 or f in ref_forms)
    distinct_garbage = sum(1 for f in held if f != 0 and f not in ref_forms)

    # Determine reference variant count
    # Form variants worth tracking = non-default categories (cosmetic, regional, event)
    # PLUS multiple 'default' entries (rare splits)
    cosmetic_forms = {f: d for f, d in ref_forms.items() if d.get('category') == 'cosmetic'}
    regional_forms = {f: d for f, d in ref_forms.items() if d.get('category') == 'regional'}
    event_forms = {f: d for f, d in ref_forms.items() if d.get('category') == 'event'}
    default_forms = {f: d for f, d in ref_forms.items() if d.get('category') == 'default'}

    # Held variants by category
    def variants_held(cat_map):
        return sorted(f for f in cat_map if f in held)
    def variants_missing(cat_map):
        return sorted(f for f in cat_map if f not in held)

    cosmetic_held = variants_held(cosmetic_forms)
    regional_held = variants_held(regional_forms)
    event_held = variants_held(event_forms)

    cosmetic_missing = variants_missing(cosmetic_forms)
    regional_missing = variants_missing(regional_forms)
    event_missing = variants_missing(event_forms)

    # form=0 = default/no-form possession
    has_default_form = 0 in held

    report = {
        'pokemon_id': pid,
        'species': species,
        'total_held': total_held,
        'reference': {
            'cosmetic_count': len(cosmetic_forms),
            'regional_count': len(regional_forms),
            'event_count': len(event_forms),
            'default_count': len(default_forms),
            'total_variants': len(ref_forms),
        },
        'held': {
            'has_form_0_default': has_default_form,
            'cosmetic_held_count': len(cosmetic_held),
            'regional_held_count': len(regional_held),
            'event_held_count': len(event_held),
            'cosmetic_held_ids': cosmetic_held,
            'regional_held_ids': regional_held,
            'event_held_ids': event_held,
            'garbage_form_ids': distinct_garbage,
        },
        'gaps': {
            'cosmetic_missing_ids': cosmetic_missing,
            'cosmetic_missing_names': [cosmetic_forms[f]['form_name'] for f in cosmetic_missing],
            'regional_missing_ids': regional_missing,
            'regional_missing_names': [regional_forms[f]['form_name'] for f in regional_missing],
            'event_missing_ids': event_missing,
            'event_missing_names': [event_forms[f]['form_name'] for f in event_missing],
        },
        'costumes': {
            'distinct_count': len(costumes),
            'by_costume_id': {str(k): v for k, v in sorted(costumes.items(), key=lambda x: -x[1])},
        },
    }
    species_reports[pid] = report

# 1. Species with all forms collected
all_forms_complete = []
for pid, r in species_reports.items():
    ref = r['reference']
    has_variants = (ref['cosmetic_count'] + ref['regional_count'] + ref['event_count']) > 0
    if not has_variants:
        continue
    all_cosmetic = ref['cosmetic_count'] == 0 or r['held']['cosmetic_held_count'] == ref['cosmetic_count']
    all_regional = ref['regional_count'] == 0 or r['held']['regional_held_count'] == ref['regional_count']
    all_event = ref['event_count'] == 0 or r['held']['event_held_count'] == ref['event_count']
    if all_cosmetic and all_regional and all_event:
        all_forms_complete.append({
            'pokemon_id': pid, 'species': r['species'],
            'cosmetic': f"{r['held']['cosmetic_held_count']}/{ref['cosmetic_count']}",
            'regional': f"{r['held']['regional_held_count']}/{ref['regional_count']}",
            'event': f"{r['held']['event_held_count']}/{ref['event_count']}",
            'total_held': r['total_held'],
        })

# 2. Species missing forms
missing_forms = []
for pid, r in species_reports.items():
    ref = r['reference']
    has_variants = (ref['cosmetic_count'] + ref['regional_count'] + ref['event_count']) > 0
    if not has_variants:
        continue
    cosmetic_missing = ref['cosmetic_count'] - r['held']['cosmetic_held_count']
    regional_missing = ref['regional_count'] - r['held']['regional_held_count']
    event_missing = ref['event_count'] - r['held']['event_held_count']
    total_missing = cosmetic_missing + regional_missing + event_missing
    if total_missing > 0:
        missing_forms.append({
            'pokemon_id': pid, 'species': r['species'],
            'total_held': r['total_held'],
            'cosmetic_missing': cosmetic_missing,
            'regional_missing': regional_missing,
            'event_missing': event_missing,
            'total_missing': total_missing,
            'missing_cosmetic_names': r['gaps']['cosmetic_missing_names'],
            'missing_regional_names': r['gaps']['regional_missing_names'],
            'missing_event_names': r['gaps']['event_missing_names'],
        })
missing_forms.sort(key=lambda x: (-x['total_missing'], x['pokemon_id']))

# 3. Multi-form species (those with >1 non-default reference variant or both cosmetic+regional etc.)
multi_form = []
for pid, r in species_reports.items():
    ref = r['reference']
    variants = ref['cosmetic_count'] + ref['regional_count'] + ref['event_count']
    if variants >= 2:
        multi_form.append({
            'pokemon_id': pid, 'species': r['species'],
            'cosmetic_count': ref['cosmetic_count'],
            'regional_count': ref['regional_count'],
            'event_count': ref['event_count'],
            'total_variants': variants,
            'forms_held': r['held']['cosmetic_held_count'] + r['held']['regional_held_count'] + r['held']['event_held_count'],
            'total_specimens': r['total_held'],
        })
multi_form.sort(key=lambda x: (-x['total_variants'], x['pokemon_id']))

# 4. Costume forms held per species (only those with >0 costumes)
costume_holders = []
for pid, r in species_reports.items():
    if r['costumes']['distinct_count'] > 0:
        costume_holders.append({
            'pokemon_id': pid, 'species': r['species'],
            'distinct_costumes': r['costumes']['distinct_count'],
            'by_costume_id': r['costumes']['by_costume_id'],
        })
costume_holders.sort(key=lambda x: -x['distinct_costumes'])

# 5. Cull surplus: single-form species (no variants in reference) tiered by count
cull_surplus_30plus = []
cull_surplus_10_29 = []
for pid, r in species_reports.items():
    ref = r['reference']
    has_variants = (ref['cosmetic_count'] + ref['regional_count'] + ref['event_count']) > 0
    if has_variants:
        continue
    item = {
        'pokemon_id': pid, 'species': r['species'],
        'total_held': r['total_held'],
        'reference_total_variants': ref['total_variants'],
    }
    if r['total_held'] >= 30:
        cull_surplus_30plus.append(item)
    elif r['total_held'] >= 10:
        cull_surplus_10_29.append(item)
cull_surplus_30plus.sort(key=lambda x: -x['total_held'])
cull_surplus_10_29.sort(key=lambda x: -x['total_held'])

# 6. Acquisition targets: multi-form species with gaps (filter to meaningful gaps - cosmetic + regional only by default)
acquisition_targets = []
for m in missing_forms:
    pid = m['pokemon_id']
    r = species_reports[pid]
    ref = r['reference']
    variants = ref['cosmetic_count'] + ref['regional_count'] + ref['event_count']
    if variants >= 2:
        acquisition_targets.append({
            'pokemon_id': pid, 'species': m['species'],
            'total_held': m['total_held'],
            'total_variants_in_reference': variants,
            'forms_held_count': r['held']['cosmetic_held_count'] + r['held']['regional_held_count'] + r['held']['event_held_count'],
            'forms_missing_count': m['total_missing'],
            'missing_cosmetic_names': m['missing_cosmetic_names'],
            'missing_regional_names': m['missing_regional_names'],
            'missing_event_names': m['missing_event_names'],
        })
acquisition_targets.sort(key=lambda x: (-x['forms_missing_count'], -x['total_held']))

output = {
    'meta': {
        'database': DB,
        'form_category_source': FORM_CAT,
        'total_pokemon_in_bag': sum(total_by_pid.values()),
        'distinct_species_in_bag': len(species_name_by_pid),
        'reference_species_with_variants': sum(1 for pid, refs in ref_by_pid.items()
                                                 if any(d.get('category') in ('cosmetic','regional','event') for d in refs.values())),
    },
    'all_forms_complete': all_forms_complete,
    'missing_forms': missing_forms,
    'multi_form_species': multi_form,
    'costume_holders': costume_holders,
    'cull_surplus_single_form_30plus': cull_surplus_30plus,
    'cull_surplus_single_form_10_to_29': cull_surplus_10_29,
    'acquisition_targets_multi_form_gaps': acquisition_targets,
    'per_species_detail': {str(pid): species_reports[pid] for pid in sorted(species_reports)},
}

os.makedirs('agent_outputs', exist_ok=True)
with open(OUT, 'w') as f:
    json.dump(output, f, indent=2)

# Summary
print(f"Total in-bag: {output['meta']['total_pokemon_in_bag']}")
print(f"Distinct species in bag: {output['meta']['distinct_species_in_bag']}")
print(f"Species with reference variants: {output['meta']['reference_species_with_variants']}")
print(f"All-forms-complete species: {len(all_forms_complete)}")
print(f"Species with missing forms: {len(missing_forms)}")
print(f"Multi-form species (in bag or reference): {len(multi_form)}")
print(f"Species with held costumes: {len(costume_holders)}")
print(f"Cull surplus candidates (single-form 30+): {len(cull_surplus_30plus)}")
print(f"Cull surplus candidates (single-form 10-29): {len(cull_surplus_10_29)}")
print(f"Acquisition targets (multi-form gaps): {len(acquisition_targets)}")
print(f"Written: {OUT}")
