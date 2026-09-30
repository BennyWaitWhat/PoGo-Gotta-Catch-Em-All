"""DRY RUN: legendary trim rule. Keep all cull-protected (100%/shiny/shadow/purified/
lucky/keep-tag) uncapped, then best 8 plain per species by IV (tiebreak CP). Trim rest.
No transfers - just reports."""
import json, sqlite3
from collections import defaultdict
oc = {int(k): v for k, v in json.load(open('official_class.json')).items()}
gm = json.load(open('pvpoke_gamemaster.json')); name = {}
for x in gm['pokemon']:
    if x.get('dex'): name.setdefault(x['dex'], x['speciesName'].split(' (')[0])
c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row
rows = [dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1').fetchall()]
KEEP_TAGS = ['Hundos','Nundos','JUMBO','GL','UL','Legacy','Background','Adventure Eff','From Ethan','From Florandez','0-15-15','Evolve Me']
CAP = 8

def htag(p, t):
    a = p.get('auth_tag_names') or ''
    return t in [x for x in a.split(';') if x]

def protected(p):
    if p['iv_total'] == 45 or p['iv_total'] == 0: return '100%' if p['iv_total']==45 else 'nundo'
    if p['is_shiny']: return 'shiny'
    if p['alignment'] == 1: return 'shadow'
    if p['alignment'] == 2: return 'purified'
    if p['is_lucky']: return 'lucky'
    for t in KEEP_TAGS:
        if htag(p, t): return 'tag:' + t
    return None

leg = defaultdict(list)
for p in rows:
    if oc.get(p['pokemon_id']) == 1: leg[p['pokemon_id']].append(p)

tot = trim_tot = prot_tot = 0
per_species_trim = []
form_wipe = []  # (species, form) fully trimmed -> completion risk
for d, ps in leg.items():
    nm = name.get(d, f'dex{d}')
    prot = [p for p in ps if protected(p)]
    plain = [p for p in ps if not protected(p)]
    plain.sort(key=lambda p: (-(p['iv_total'] or 0), -(p['cp'] or 0)))
    keep_plain = plain[:CAP]; trim = plain[CAP:]
    tot += len(ps); prot_tot += len(prot); trim_tot += len(trim)
    if trim:
        per_species_trim.append((len(trim), nm, len(ps), len(prot), len(plain)))
        # completion check: would any FORM be entirely gone (no kept copy of that form)?
        kept_forms = set(p['form'] for p in prot + keep_plain)
        for p in trim:
            if p['form'] not in kept_forms:
                form_wipe.append((nm, p['form'])); break
per_species_trim.sort(reverse=True)
print(f'LEGENDARY TRIM DRY-RUN  (cap {CAP}/species, protected uncapped)')
print(f'  total legendaries: {tot}')
print(f'  always-kept (protected): {prot_tot}')
print(f'  would TRIM: {trim_tot}   -> would remain: {tot - trim_tot}')
print(f'  species affected: {len(per_species_trim)}')
print(f"\n  {'species':14s}{'have':>5}{'prot':>5}{'plain':>6}{'trim':>5}")
for t, nm, n, pr, pl in per_species_trim:
    print(f'  {nm:14s}{n:>5}{pr:>5}{pl:>6}{t:>5}')
if form_wipe:
    print('\n  COMPLETION RISK - a form would lose its last copy:')
    for nm, f in form_wipe: print(f'    {nm} form {f}')
else:
    print('\n  completion: every form retains at least one copy.')
