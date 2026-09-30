"""Fill PokeGenie's Pokedex art from the LIVE PoGo account dex -- every species and form actually caught.

User 2026-09-03: "i meant the actual list of pokemon i have in my actual pogo account". Right: the bag
(pokemon.db in_bag=1) is only what is currently held, so a species or form caught and later transferred
had no tile, and forms PokeGenie had never downloaded had none either. The recrawl's read_dex step writes
the real thing:
    pogo_extract/dex_caught.json        [dex, ...]                 -- 946 species caught, lifetime
    pogo_extract/dex_caught_forms.json  {dex: [form_id, ...]}      -- every form caught per species
which is the authoritative source and is what this uses.

Two passes, both most-specific-first and always ending at real art for THAT dex, so a species can never
be given another species' picture:
  1. base tile for every caught species. Some species have NO bare pm<dex>.icon.png upstream (Unown,
     Spinda, Burmy, Wormadam, Cherrim, Shellos, Gastrodon, Basculin) -- those fall back to a
     representative form icon instead of being left blank, which is what left holes in the dex.
  2. a tile per caught FORM, keyed the way PokeGenie names them (i_df_<dex>_<Form>.jpg, e.g.
     78_Galarian). A suffix PokeGenie does not happen to use is simply an unused file -- harmless.

Writes into pokegenie_out/pokedex_art/ alongside the existing tiles.

    python fill_dex_from_account.py
"""
import collections, json, os, re, threading, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(BASE, 'pogo_extract')
WORK = os.path.join(BASE, 'pokegenie_work')
ART = os.path.join(BASE, 'pokegenie_out', 'pokedex_art')
SPR = os.path.join(WORK, 'sprites')
RAW = 'https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/'
_lock = threading.Lock()

# our form-enum tail -> the suffix PokeGenie uses in its Pokedex filenames
PG_SUFFIX = {
    'Alolan': 'Alola', 'Alola': 'Alola', 'Galarian': 'Galarian', 'Hisuian': 'Hisuian',
    'Paldea': 'Paldean', 'Paldean': 'Paldean',
}
norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())


def main():
    paths = {p.split('/')[-1]: p for p in
             json.load(open(os.path.join(SPR, 'upstream_files.json'), encoding='utf-8'))}
    icons, tok_by_dex, base, any_form = {}, collections.defaultdict(dict), {}, collections.defaultdict(list)
    for n in paths:
        m = re.match(r'pm(\d+)\.f([A-Z0-9_]+)\.icon\.png$', n)
        if m:
            dex, tok = int(m.group(1)), m.group(2)
            icons[(dex, tok)] = n
            tok_by_dex[dex].setdefault(norm(tok), tok)
            any_form[dex].append((tok, n))
            continue
        m = re.match(r'pm(\d+)\.icon\.png$', n)
        if m:
            base[int(m.group(1))] = n

    caught = json.load(open(os.path.join(ROOT, 'dex_caught.json'), encoding='utf-8'))
    caught_forms = {int(k): v for k, v in
                    json.load(open(os.path.join(ROOT, 'dex_caught_forms.json'), encoding='utf-8')).items()}
    form_enum = {int(k): v for k, v in
                 json.load(open(os.path.join(ROOT, 'form_enum.json'), encoding='utf-8')).items()}
    print('live account dex: %d species caught, %d with form detail'
          % (len(caught), len(caught_forms)))

    con = None
    try:
        import sqlite3
        con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
        species = {r[0]: r[1] for r in con.execute(
            'SELECT DISTINCT pokemon_id, species_name FROM pokemon')}
    except Exception:
        species = {}

    def base_art(dex):
        if dex in base:
            return base[dex]
        for pref in ('NORMAL', 'INCARNATE', 'ALTERED', 'PLANT', 'ARIA', 'MIDDAY', 'HERO',
                     'SPRING', 'WEST', 'RED_STRIPED', 'OVERCAST', 'UNOWN_A'):
            if (dex, pref) in icons:
                return icons[(dex, pref)]
        f = sorted(any_form.get(dex) or [])
        return f[0][1] if f else None

    def form_suffix_and_art(dex, fid):
        name = form_enum.get(fid or 0, '')
        if not name or name.lower() in ('unset', 'normal'):
            return None, None
        tail = name
        sp = species.get(dex, '')
        for cand in (sp, sp.replace(' ', ''), sp.replace('_', '')):
            if cand and tail.lower().startswith(cand.lower()):
                tail = tail[len(cand):]
                break
        if not tail or tail.lower() == 'normal':
            return None, None
        tok = tok_by_dex[dex].get(norm(name)) or tok_by_dex[dex].get(norm(tail))
        if not tok:
            for k, v in tok_by_dex[dex].items():
                if k.endswith(norm(tail)):
                    tok = v
                    break
        if not tok:
            return None, None
        return PG_SUFFIX.get(tail, tail), icons[(dex, tok)]

    have = set(os.listdir(ART)) if os.path.isdir(ART) else set()
    want, no_art, n_base, n_form = {}, [], 0, 0
    for dex in caught:
        fn = base_art(dex)
        if not fn:
            no_art.append(dex)
        elif ('pokedex_%d' % dex) not in have:
            want[str(dex)] = fn
            n_base += 1
        for fid in caught_forms.get(dex, []):
            suf, ffn = form_suffix_and_art(dex, fid)
            if not suf or not ffn:
                continue
            key = '%d_%s' % (dex, suf)
            if ('pokedex_' + key) in have or key in want:
                continue
            want[key] = ffn
            n_form += 1

    print('  new base tiles : %d' % n_base)
    print('  new form tiles : %d' % n_form)
    print('  species with NO upstream art at all: %d %s' % (len(no_art), no_art[:10]))

    failed = []

    def fetch(item):
        key, fn = item
        src = os.path.join(SPR, fn)
        if not (os.path.exists(src) and os.path.getsize(src) > 500):
            try:
                req = urllib.request.Request(RAW + urllib.parse.quote(paths[fn]),
                                             headers={'User-Agent': 'pg-dexacct'})
                with urllib.request.urlopen(req, timeout=40) as r:
                    b = r.read()
                if len(b) <= 500:
                    with _lock:
                        failed.append(key)
                    return
                open(src, 'wb').write(b)
            except Exception:
                with _lock:
                    failed.append(key)
                return
        data = open(src, 'rb').read()
        open(os.path.join(ART, 'pokedex_' + key), 'wb').write(data)
        open(os.path.join(ART, 'i_df_%s.jpg' % key), 'wb').write(data)

    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(fetch, want.items()))
    print('wrote %d tiles (%d files), failures %d' % (len(want) - len(failed),
                                                      (len(want) - len(failed)) * 2, len(failed)))
    print('total Pokedex tiles now: %d' % len([f for f in os.listdir(ART) if f.startswith('pokedex_')]))
    for probe in ('78_Galarian', '201', '327', '412', '585', '586', '421', '422', '423', '550'):
        print('  i_df_%-12s -> %s' % (probe, os.path.exists(os.path.join(ART, 'i_df_%s.jpg' % probe))))


if __name__ == '__main__':
    main()
