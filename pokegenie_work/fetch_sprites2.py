"""Download the OFFICIAL PoGo icon for every distinct pokemon variant in the bag -- form, costume and
shiny accurate -- matching against the mirror's REAL filenames instead of guessing form numbers.

The first attempt guessed a numeric form id and failed on 536 combinations (Unown, Deoxys, Burmy, ...).
The mirror actually names files:

    pm<dex>[.f<FORM>][.c<COSTUME>][.g<GENDER>][.s].icon.png        .s = shiny

with FORM/COSTUME as NAMES, not numbers. Our DB stores a numeric `form` whose name is in
pogo_extract/form_enum.json (e.g. 1 -> 'UnownA', 963 -> 'RattataAlola'), so the form NAME is recoverable.
The enum name embeds the species ('UnownA', 'PikachuFlyingOkinawa'), while upstream uses only the variant
part ('.fA', '.fALOLA'), so we strip the species prefix and upper-case the remainder.

Matching is STRICTLY most-specific-first and always ends at the plain base form. A candidate is only used
if it EXISTS in the upstream listing, so a mon can never be given another species' picture -- if nothing
matches, it gets no art at all (PokeGenie then shows its own default).

    python fetch_sprites2.py [--jobs 16]
"""
import argparse, json, os, re, sqlite3, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(os.path.dirname(HERE), 'pogo_extract')
OUT = os.path.join(HERE, 'sprites')
RAW = 'https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/'

_lock = threading.Lock()


def load_upstream():
    paths = json.load(open(os.path.join(OUT, 'upstream_files.json'), encoding='utf-8'))
    by_name = {}
    for p in paths:
        by_name[p.split('/')[-1]] = p
    return by_name


def variant_suffix(form_name, species):
    """'UnownA' + species 'Unown' -> 'A';  'RattataAlola' -> 'ALOLA';  '' when it is just the species."""
    if not form_name:
        return ''
    s = form_name
    for cand in (species, species.replace(' ', ''), species.replace('_', '')):
        if cand and s.lower().startswith(cand.lower()):
            s = s[len(cand):]
            break
    s = s.strip('_')
    if s.lower() in ('', 'normal', 'unset'):
        return ''
    return re.sub(r'(?<!^)(?=[A-Z])', '_', s).upper()


def candidates(dex, form_name, species, costume_name, shiny, upstream):
    """Ordered, most specific first; only names that actually exist upstream survive."""
    fv = variant_suffix(form_name, species)
    parts = []
    if costume_name:
        parts.append('.c' + costume_name.upper())
    if fv:
        parts.append('.f' + fv)
    out = []
    # every combination of the qualifiers we have, longest first, then bare
    for combo in ([''.join(parts)] if parts else []) + (['.f' + fv] if fv else []) + \
                 (['.c' + costume_name.upper()] if costume_name else []) + ['']:
        for suf in (('.s', '') if shiny else ('',)):
            nm = 'pm%d%s%s.icon.png' % (dex, combo, suf)
            if nm in upstream and nm not in out:
                out.append(nm)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=16)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    upstream = load_upstream()
    print('upstream pokemon images: %d' % len(upstream))
    fe = json.load(open(os.path.join(ROOT, 'form_enum.json'), encoding='utf-8'))
    form_name = {int(k): v for k, v in fe.items()} if isinstance(fe, dict) else {}

    con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
    con.row_factory = sqlite3.Row
    rows = con.execute('SELECT pokemon_id, species_name, form, fresh_costume, fresh_shiny '
                       'FROM pokemon WHERE in_bag=1').fetchall()

    combos = {}
    for r in rows:
        key = '%d|%s|%s|%d' % (r['pokemon_id'], r['form'] or 0, r['fresh_costume'] or 0,
                               1 if r['fresh_shiny'] else 0)
        if key not in combos:
            combos[key] = (r['pokemon_id'], form_name.get(r['form'] or 0, ''), r['species_name'],
                           '', 1 if r['fresh_shiny'] else 0)
    print('distinct variants in bag: %d' % len(combos))

    index, missing = {}, []

    def work(item):
        key, (dex, fname, species, cos, shiny) = item
        cands = candidates(dex, fname, species, cos, shiny, upstream)
        if not cands:
            with _lock:
                missing.append(key)
            return
        for nm in cands:
            dest = os.path.join(OUT, nm)
            if os.path.exists(dest) and os.path.getsize(dest) > 500:
                with _lock:
                    index[key] = nm
                return
            for attempt in range(3):
                try:
                    req = urllib.request.Request(RAW + upstream[nm], headers={'User-Agent': 'pg-sprites'})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        b = resp.read()
                    if len(b) > 500:
                        open(dest, 'wb').write(b)
                        with _lock:
                            index[key] = nm
                        return
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (429, 500, 502, 503):
                        time.sleep(2 * (attempt + 1))
                        continue
                    break
                except Exception:
                    time.sleep(1.5)
        with _lock:
            missing.append(key)

    items = list(combos.items())
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for i, _ in enumerate(ex.map(work, items), 1):
            if i % 250 == 0:
                print('  %d/%d  have %d  missing %d' % (i, len(items), len(index), len(missing)))

    json.dump(index, open(os.path.join(OUT, 'sprite_index.json'), 'w', encoding='utf-8'), indent=0)
    print('\nmatched %d/%d variants (%.1f%%)' % (len(index), len(combos), len(index) / len(combos) * 100))
    print('no upstream art: %d  e.g. %s' % (len(missing), missing[:8]))
    print('wrote %s' % os.path.join(OUT, 'sprite_index.json'))


if __name__ == '__main__':
    main()
