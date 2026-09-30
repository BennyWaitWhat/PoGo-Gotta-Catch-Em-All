"""Fetch the official Pokemon GO icon sprites for every pokemon in the bag, shiny-accurate.

Why this exists: every on-device source was exhausted first and each was a dead end --
  * PoGo UnityCache (2GB, 13,984 bundles): 488 hold Texture2D, all 1,009 are avatar clothing/scenery.
  * PoGo DiskCache (938 files): PokeStop photos and item icons, no pokemon.
  * Live IL2CPP: 243 Texture2D objects exist, but they are GPU-side and not CPU-readable, so
    ImageConversion.EncodeToPNG returns nothing.
  * PokeGenie app_imageDir: 864 species-art files, no shiny and no costume variants, 136 species missing.
The game streams pokemon icons from Niantic's CDN on demand, so the art genuinely is not on the phone for
anything the user has not recently viewed. These are the same icons the game renders.

Naming: pokemon_icon_<dex:3>_<form:2>[_shiny].png  (form 00 = base). Regional/costume forms use higher
form numbers; we try the specific form first and fall back to 00 so a mon never gets a WRONG species.

    python fetch_sprites.py [--out sprites] [--limit N]
"""
import argparse, json, os, sqlite3, sys, time, urllib.error, urllib.request

ROOT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract"
BASE = "https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/Images/Pokemon/"

# form_region -> the form suffix Niantic uses in the icon filename
REGION_FORM = {'alolan': 61, 'galarian': 62, 'hisuian': 63, 'paldean': 64}


def candidates(dex, form_region, shiny):
    """Filenames to try, most specific first."""
    out = []
    reg = (form_region or '').strip().lower()
    fnum = REGION_FORM.get(reg)
    suf = '_shiny' if shiny else ''
    if fnum is not None:
        out.append('pokemon_icon_%03d_%02d%s.png' % (dex, fnum, suf))
    out.append('pokemon_icon_%03d_00%s.png' % (dex, suf))
    if shiny:                     # last resort: non-shiny art rather than nothing
        if fnum is not None:
            out.append('pokemon_icon_%03d_%02d.png' % (dex, fnum))
        out.append('pokemon_icon_%03d_00.png' % dex)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sprites'))
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
    con.row_factory = sqlite3.Row
    rows = con.execute('SELECT DISTINCT pokemon_id, form_region, fresh_shiny FROM pokemon '
                       'WHERE in_bag=1').fetchall()
    # one download per distinct (dex, region, shiny) -- ~1.5k at most, not 5,592
    want = sorted({(r['pokemon_id'], (r['form_region'] or '').strip().lower(), 1 if r['fresh_shiny'] else 0)
                   for r in rows})
    if a.limit:
        want = want[:a.limit]
    print('distinct (dex, region, shiny) combinations needed: %d' % len(want))

    got, missing, cached = {}, [], 0
    for i, (dex, reg, shiny) in enumerate(want, 1):
        key = '%d|%s|%d' % (dex, reg, shiny)
        hit = None
        for fn in candidates(dex, reg, shiny):
            dest = os.path.join(a.out, fn)
            if os.path.exists(dest) and os.path.getsize(dest) > 500:
                hit = fn
                cached += 1
                break
            try:
                with urllib.request.urlopen(BASE + fn, timeout=25) as r:
                    b = r.read()
                if len(b) > 500:
                    open(dest, 'wb').write(b)
                    hit = fn
                    break
            except urllib.error.HTTPError:
                continue           # this form does not exist upstream; try the next candidate
            except Exception as e:
                print('  net error on %s: %s' % (fn, e))
                time.sleep(1.5)
                continue
        if hit:
            got[key] = hit
        else:
            missing.append(key)
        if i % 100 == 0:
            print('  %d/%d  (have %d, missing %d)' % (i, len(want), len(got), len(missing)))

    json.dump(got, open(os.path.join(a.out, 'sprite_index.json'), 'w', encoding='utf-8'), indent=0)
    print('\nfetched/……cached: %d  (already on disk: %d)' % (len(got), cached))
    print('no upstream art: %d  %s' % (len(missing), missing[:10]))
    print('wrote %s' % os.path.join(a.out, 'sprite_index.json'))


if __name__ == '__main__':
    main()
