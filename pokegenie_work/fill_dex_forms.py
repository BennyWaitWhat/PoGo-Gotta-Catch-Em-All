"""Give EVERY (dex, form) the user actually owns a Pokedex tile -- not just the ones PokeGenie
had already downloaded.

User 2026-09-03: "im pretty sure i have a galar rapidash, why isnt the photo loading?" -- correct.
build_art.py replaced the 864 Pokedex files PokeGenie already had and added base art per owned species,
but a regional/alternate form PokeGenie had NEVER downloaded got no tile at all. Galarian Rapidash is
one of those: its collection thumbnail was right (pm78.fGALARIAN) while the Pokedex tile was absent.

The authoritative key is the scan entry's own `form` value: PokeGenie renders a Pokedex entry from
`app_imageDir/i_df_<pokemonNumber>[_<form>].jpg` (and its `pokedex_...` twin), where <form> is exactly
the string written into the scan record. So the complete set of tiles the user needs is precisely the
distinct (pokemonNumber, form) pairs present in scan_data.json.

Resolution is most-specific-first against the live upstream listing and always ends at the plain base
form, so a form can never be given another species' art.

    python fill_dex_forms.py
"""
import collections, json, os, re, threading, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(BASE, 'pokegenie_work')
OUT = os.path.join(BASE, 'pokegenie_out')
SPR = os.path.join(WORK, 'sprites')
ART = os.path.join(OUT, 'pokedex_art')
RAW = 'https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/'
_lock = threading.Lock()

# PokeGenie's scan `form` value -> upstream form token, where normalising alone will not get there
FORM_TOKEN = {
    'Alola': 'ALOLA', 'Galarian': 'GALARIAN', 'Hisuian': 'HISUIAN', 'Paldean': 'PALDEA',
    'Mega': 'MEGA', 'MegaX': 'MEGA_X', 'MegaY': 'MEGA_Y',
    'Deoxysattack': 'ATTACK', 'Deoxysdefense': 'DEFENSE',
    'zyg10': 'TEN_PERCENT', 'formFour': 'FIFTY_PERCENT',
    'OriBaile': 'BAILE', 'OriPau': 'PAU', 'OriPom': 'POM_POM', 'OriSensu': 'SENSU',
    'FormMidday': 'MIDDAY', 'FormMidnight': 'MIDNIGHT',
    'Sword': 'CROWNED_SWORD', 'Shield': 'CROWNED_SHIELD',
}

norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())


def main():
    paths = {p.split('/')[-1]: p for p in
             json.load(open(os.path.join(SPR, 'upstream_files.json'), encoding='utf-8'))}
    icons, tok_by_dex, base = {}, collections.defaultdict(dict), {}
    for n in paths:
        m = re.match(r'pm(\d+)\.f([A-Z0-9_]+)\.icon\.png$', n)
        if m:
            dex, tok = int(m.group(1)), m.group(2)
            icons[(dex, tok)] = n
            tok_by_dex[dex].setdefault(norm(tok), tok)
            continue
        m = re.match(r'pm(\d+)\.icon\.png$', n)
        if m:
            base[int(m.group(1))] = n

    data = json.load(open(os.path.join(OUT, 'scan_data.json'), encoding='utf-8'))
    entries = data if isinstance(data, list) else (data.get('scans') or list(data.values())[0])
    pairs = collections.Counter()
    for e in entries:
        pairs[(e.get('pokemonNumber'), e.get('form') or '')] += 1
    print('distinct (dex, form) the user owns: %d' % len(pairs))

    have = {f for f in os.listdir(ART)} if os.path.isdir(ART) else set()
    want, missing_art, already = {}, [], 0
    for (dex, form), n in pairs.items():
        if not dex:
            continue
        key = '%d_%s' % (dex, form) if form else str(dex)
        if 'pokedex_' + key in have:
            already += 1
            continue
        tok = ''
        if form:
            t = FORM_TOKEN.get(form, form)
            tok = tok_by_dex[dex].get(norm(t), '')
            if not tok:                      # upstream may prefix the species: Plant -> BURMY_PLANT
                for k, v in tok_by_dex[dex].items():
                    if k.endswith(norm(t)):
                        tok = v
                        break
        fn = icons.get((dex, tok)) if tok else None
        fn = fn or base.get(dex)
        if not fn:
            missing_art.append((dex, form, n))
            continue
        want[key] = fn

    print('  already have a tile : %d' % already)
    print('  NEW tiles to write  : %d' % len(want))
    if missing_art:
        print('  no upstream art     : %s' % missing_art[:8])

    failed = []

    def fetch(item):
        key, fn = item
        src = os.path.join(SPR, fn)
        if not (os.path.exists(src) and os.path.getsize(src) > 500):
            try:
                req = urllib.request.Request(RAW + urllib.parse.quote(paths[fn]),
                                             headers={'User-Agent': 'pg-dexform'})
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

    print('wrote %d new tiles (%d files); failures: %d'
          % (len(want) - len(failed), (len(want) - len(failed)) * 2, len(failed)))
    for probe in ('78_Galarian', '77_Galarian', '78', '58_Hisuian'):
        print('  %-14s -> %s' % (probe, os.path.exists(os.path.join(ART, 'i_df_%s.jpg' % probe))))


if __name__ == '__main__':
    main()
