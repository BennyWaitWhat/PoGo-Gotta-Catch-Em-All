"""Close the form-art gap: upstream sometimes KEEPS the species prefix (fUNOWN_A, fBURMY_PLANT) and
sometimes drops it (fBLUE, fBLACK). The original matcher always stripped it, so every prefix-keeping
species (Unown letters, Burmy cloaks, ...) found nothing. Try both spellings."""
import json, os, re, sqlite3, threading, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = '../pogo_extract'
RAW = 'https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/'
up = {p.split('/')[-1]: p for p in json.load(open('sprites/upstream_files.json'))}
idx = json.load(open('sprites/sprite_index.json'))
fe = json.load(open(ROOT + '/form_enum.json'))
form_name = {int(k): v for k, v in fe.items()}

def snake(s):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', s).upper().strip('_')

def variants(fname, species):
    """every plausible upstream spelling of this form's suffix"""
    if not fname or fname.lower() in ('unset', 'normal'):
        return []
    out = [snake(fname)]                       # prefix KEPT: UnownA -> UNOWN_A
    s = fname
    for c in (species, species.replace(' ', ''), species.replace('_', '')):
        if c and s.lower().startswith(c.lower()):
            s = s[len(c):]
            break
    s = s.strip('_')
    if s and s.lower() not in ('normal', 'unset'):
        out.append(snake(s))                   # prefix DROPPED: UnownA -> A
    # TRAILING SEGMENT: the species prefix can differ from species_name (form 'FlabebeRed' vs species
    # 'Flabebe' with accents), so prefix-stripping fails. Take the last CamelCase word(s) instead:
    # FlabebeRed -> RED, KyuremNormal -> NORMAL.
    words = re.findall(r'[A-Z][a-z0-9]*', fname)
    if len(words) > 1:
        out.append(words[-1].upper())
        out.append(snake(''.join(words[1:])))
    return [x for x in dict.fromkeys(out) if x]

con = sqlite3.connect(ROOT + '/pokemon.db'); con.row_factory = sqlite3.Row
rows = con.execute('SELECT pokemon_id,species_name,form,fresh_shiny FROM pokemon WHERE in_bag=1').fetchall()

todo = {}
for r in rows:
    key = '%d|%s|%d' % (r['pokemon_id'], r['form'] or 0, 1 if r['fresh_shiny'] else 0)
    if key in idx or key in todo:
        continue
    dex = r['pokemon_id']; shiny = bool(r['fresh_shiny'])
    cands = []
    for v in variants(form_name.get(r['form'] or 0, ''), r['species_name']):
        for suf in (('.s', '') if shiny else ('',)):
            cands.append('pm%d.f%s%s.icon.png' % (dex, v, suf))
    for suf in (('.s', '') if shiny else ('',)):        # bare base form, last resort
        cands.append('pm%d%s.icon.png' % (dex, suf))
    hit = [c for c in cands if c in up]
    if hit:
        todo[key] = hit[0]

print('gap entries with an upstream match: %d' % len(todo))
lock = threading.Lock(); got = {}
def go(kv):
    k, nm = kv
    dest = os.path.join('sprites', nm)
    if os.path.exists(dest) and os.path.getsize(dest) > 500:
        with lock: got[k] = nm
        return
    try:
        req = urllib.request.Request(RAW + urllib.parse.quote(up[nm]), headers={'User-Agent': 'pg'})
        b = urllib.request.urlopen(req, timeout=30).read()
        if len(b) > 500:
            open(dest, 'wb').write(b)
            with lock: got[k] = nm
    except Exception:
        pass
with ThreadPoolExecutor(max_workers=24) as ex:
    list(ex.map(go, todo.items()))
idx.update(got)
json.dump(idx, open('sprites/sprite_index.json', 'w'), indent=0)
print('downloaded %d | index now %d' % (len(got), len(idx)))
