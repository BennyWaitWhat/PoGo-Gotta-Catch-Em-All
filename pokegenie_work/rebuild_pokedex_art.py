"""Replace PokeGenie's Pokedex art with official Pokemon GO art, and complete the coverage.

User 2026-09-03: "btw the Drampa you saw was my old scan photo. so you need to nuke my old photos."
Correct. PokeGenie builds its POKEDEX art out of the user's own capture-screen screenshots: every
app_imageDir/pokedex_<dex>[_<Form>] (and its i_df_<dex>[_<Form>].jpg twin) was a cropped old scan --
which is also why the "Current Raid Bosses" row showed a scan photo for Drampa and a "?" for everything
the user had never scanned. Both files hold the same PNG bytes under two names, so both get rewritten.

Resolution is most-specific-first and ALWAYS ends at the plain base form, and every candidate must exist
upstream, so a species can never be given another species art:
    1. curated PokeGenie-suffix -> upstream form token
    2. fuzzy match of the suffix against this dex's real upstream form tokens
    3. bare pm<dex>.icon.png

Also adds what was never there: _Mega / _MegaX / _MegaY for all mega species (so mega raid bosses and the
mega Pokedex entries render), and base art for every remaining dex upstream has.

    python rebuild_pokedex_art.py [--jobs 16]
"""
import argparse, collections, json, os, re, threading, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(BASE, 'pokegenie_work')
OUT = os.path.join(BASE, 'pokegenie_out', 'pokedex_art')
SPR = os.path.join(WORK, 'sprites')
RAW = 'https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/'
_lock = threading.Lock()

# PokeGenie's own form suffix -> the upstream form token
SUFFIX = {
    'Alola': 'ALOLA', 'Galarian': 'GALARIAN', 'Hisuian': 'HISUIAN', 'Paldean': 'PALDEA',
    'Mega': 'MEGA', 'MegaX': 'MEGA_X', 'MegaY': 'MEGA_Y',
    'Therian': 'THERIAN', 'Incarnate': 'INCARNATE', 'Female': 'FEMALE', 'Male': 'MALE',
    'Hero': 'HERO', 'Rainy': 'RAINY', 'Sunny': 'SUNNY', 'Aqua': 'AQUA',
    'Deoxysattack': 'ATTACK', 'Deoxysdefense': 'DEFENSE',
    'Plant': 'PLANT', 'Sandy': 'SANDY', 'Trash': 'TRASH',
    'Altered': 'ALTERED', 'Land': 'LAND', 'Black': 'BLACK', 'White': 'WHITE', 'Aria': 'ARIA',
    'Burn': 'BURN', 'Chill': 'CHILL', 'Douse': 'DOUSE', 'Shock': 'SHOCK',
    'Unbound': 'UNBOUND', 'zyg10': 'TEN_PERCENT', 'formFour': 'FIFTY_PERCENT',
    'OriBaile': 'BAILE', 'OriPau': 'PAU', 'OriPom': 'POM_POM', 'OriSensu': 'SENSU',
    'FormMidday': 'MIDDAY', 'FormMidnight': 'MIDNIGHT',
    'Sword': 'CROWNED_SWORD', 'Shield': 'CROWNED_SHIELD',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=16)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(SPR, exist_ok=True)

    upstream = json.load(open(os.path.join(SPR, 'upstream_files.json'), encoding='utf-8'))
    paths = {p.split('/')[-1]: p for p in upstream}
    forms = collections.defaultdict(dict)      # dex -> {FORM_TOKEN: filename}, non-shiny only
    base = {}
    for n in paths:
        m = re.match(r'pm(\d+)\.f([A-Z0-9_]+)\.icon\.png$', n)
        if m:
            forms[int(m.group(1))][m.group(2)] = n
            continue
        m = re.match(r'pm(\d+)\.icon\.png$', n)
        if m:
            base[int(m.group(1))] = n
    print('upstream: %d species with base art, %d with form art' % (len(base), len(forms)))

    existing = [l.strip() for l in open(os.path.join(WORK, 'pokedex_names.txt'), encoding='utf-8')
                if l.strip()]
    print('existing PokeGenie pokedex art files (all old scan photos): %d' % len(existing))

    def resolve(dex, suf):
        """upstream filename for this (dex, PokeGenie suffix); never another species"""
        if suf:
            tok = SUFFIX.get(suf)
            if tok and tok in forms.get(dex, {}):
                return forms[dex][tok]
            key = re.sub(r'[^a-z0-9]', '', suf.lower())
            for t, fn in forms.get(dex, {}).items():
                if re.sub(r'[^a-z0-9]', '', t.lower()) == key:
                    return fn
        if dex in base:
            return base[dex]
        f = forms.get(dex) or {}
        for t in ('NORMAL', 'INCARNATE', 'ALTERED', 'PLANT', 'ARIA', 'MIDDAY', 'HERO'):
            if t in f:
                return f[t]
        return sorted(f.values())[0] if f else None

    want, unresolved = {}, []
    for nm in existing:                                   # 1. replace every old photo
        m = re.match(r'pokedex_(\d+)(?:_(.+))?$', nm)
        if not m:
            unresolved.append(nm)
            continue
        fn = resolve(int(m.group(1)), m.group(2))
        if fn:
            want[nm[len('pokedex_'):]] = fn
        else:
            unresolved.append(nm)
    n_replaced = len(want)

    # User 2026-09-03: "you're only filling the current pokemon i have in my dex right? not pokemon i
    # havent caught or seen yet?" -- right. Art is only ever written for a species the user ACTUALLY HAS,
    # so the Pokedex never illustrates something they have not caught. "Has" = the species PokeGenie
    # already held art for (i.e. they scanned it at some point) plus everything currently in the bag.
    # Reading PoGo's lifetime PokedexImpl would be the exact set, but that means attaching to the running
    # game, and the game is not to be touched mid-play.
    owned = {int(re.match(r'pokedex_(\d+)', nm).group(1)) for nm in existing
             if re.match(r'pokedex_(\d+)', nm)}
    n_prev = len(owned)
    try:
        import sqlite3
        con = sqlite3.connect(os.path.join(BASE, 'pogo_extract', 'pokemon.db'))
        bag = {r[0] for r in con.execute('SELECT DISTINCT pokemon_id FROM pokemon WHERE in_bag=1')}
        owned |= bag
    except Exception as e:
        bag = set()
        print('  (bag read failed, using scanned species only: %s)' % e)
    print('  owned species: %d (%d already had art, %d in bag, %d new from bag)'
          % (len(owned), n_prev, len(bag), len(owned) - n_prev))

    n_mega = 0                                            # 2. mega art, owned species only
    for dex, f in forms.items():
        if dex not in owned:
            continue
        for tok, suf in (('MEGA', 'Mega'), ('MEGA_X', 'MegaX'), ('MEGA_Y', 'MegaY')):
            if tok in f:
                key = '%d_%s' % (dex, suf)
                if key not in want:
                    want[key] = f[tok]
                    n_mega += 1

    n_fill = 0                                            # 3. base art, owned species only
    for dex, fn in base.items():
        if dex in owned and str(dex) not in want:
            want[str(dex)] = fn
            n_fill += 1

    print('  replacing old photos : %d' % n_replaced)
    print('  adding mega art      : %d' % n_mega)
    print('  filling base coverage: %d' % n_fill)
    if unresolved:
        print('  could not resolve    : %d %s' % (len(unresolved), unresolved[:6]))

    got, failed = {}, []

    def work(item):
        key, fn = item
        src = os.path.join(SPR, fn)
        if not (os.path.exists(src) and os.path.getsize(src) > 500):
            try:
                req = urllib.request.Request(RAW + urllib.parse.quote(paths[fn]),
                                             headers={'User-Agent': 'pg-dex'})
                with urllib.request.urlopen(req, timeout=30) as r:
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
        open(os.path.join(OUT, 'pokedex_' + key), 'wb').write(data)
        open(os.path.join(OUT, 'i_df_%s.jpg' % key), 'wb').write(data)
        with _lock:
            got[key] = fn

    items = list(want.items())
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for i, _ in enumerate(ex.map(work, items), 1):
            if i % 300 == 0:
                print('  %d/%d  ok %d  failed %d' % (i, len(items), len(got), len(failed)))

    json.dump(got, open(os.path.join(BASE, 'pokegenie_out', 'pokedex_art_map.json'), 'w',
                        encoding='utf-8'), indent=0)
    print('\nwrote %d entries (%d files) to %s' % (len(got), len(got) * 2, OUT))
    if failed:
        print('failed: %d  e.g. %s' % (len(failed), failed[:8]))


if __name__ == '__main__':
    main()
