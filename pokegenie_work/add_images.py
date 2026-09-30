"""Give every generated PokeGenie entry the BEST real art available, WITHOUT rescanning anything.

Layered source strategy (2026-09-02, per-pokemon, best available wins):
  1. REAL historical scan photo -- an actual PoGo capture-screen screenshot of THIS EXACT individual,
     recovered from the old PokeGenie backup (pg.zip / old_backup/) via match_old_photos.py and matched
     by (dex, cp, 3 IVs, gender) + date/move corroboration (see that script). This is strictly the best
     art possible: it is a real photo of the real individual, so a shiny mon matched this way gets its
     actual shiny appearance for free, and any species/form is correct by construction.
  2. Generic Pokedex art from app_imageDir/ (864 files, i_df_<dex>[_<Form>].jpg) -- exact dex+form match,
     else dex-only match. This is the original fallback: correct species, but NOT shiny-accurate (the art
     set has no shiny variants) and covers only ~802 of the ~936 distinct dex numbers in the bag.
  3. Nothing. A pokemon with no art in either source gets NO imageId and PokeGenie falls back to its own
     default -- NEVER a wrong picture.

PokeGenie renders a scan's thumbnail from files/scan_thumb/<imageId>.jpg. This script writes:
  - scan_thumb/<imageId>.jpg   (a copy of the chosen art, one per pokemon that has any)
  - image_map.json             (uid_hex -> imageId), consumed by generate_pokegenie.py
  - source_map.json            (uid_hex -> which layer supplied the art), for reporting only

    python add_images.py --art-dir <pulled app_imageDir> [--photo-map <photo_map.json>] [--out <dir>]
"""
import argparse, hashlib, json, os, re, shutil, sqlite3, sys

ROOT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract"
WORK = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pokegenie_work"
OUT_DEFAULT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pokegenie_out"
PHOTO_MAP_DEFAULT = os.path.join(WORK, 'photo_map.json')

# PokeGenie form suffixes seen in app_imageDir, mapped from our form_region / species naming.
REGION_SUFFIX = {'alolan': 'Alola', 'galarian': 'Galarian', 'hisuian': 'Hisuian', 'paldean': 'Paldean'}


def art_index(art_dir):
    """{dex: {form_suffix_or_'': filename}} from i_df_<dex>[_<Form>].jpg"""
    idx = {}
    for fn in os.listdir(art_dir):
        m = re.match(r'i_df_(\d+)(?:_(.+))?\.jpg$', fn)
        if not m:
            continue
        idx.setdefault(int(m.group(1)), {})[(m.group(2) or '')] = fn
    return idx


def image_id_for(uid_hex):
    """Deterministic 14-char id in PokeGenie's observed alphabet (lowercase alnum).

    Deterministic on purpose: re-running must reuse the SAME id per pokemon, so a re-run overwrites its
    own thumbnails instead of orphaning 5,500 files in the app's data directory every time.
    """
    h = hashlib.sha1(('pgimg:' + uid_hex).encode()).hexdigest()
    alpha = '0123456789abcdefghijklmnopqrstuvwxyz'
    n = int(h[:24], 16)
    out = []
    for _ in range(14):
        n, r = divmod(n, 36)
        out.append(alpha[r])
    return ''.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--art-dir', required=True, help='local copy of PokeGenie app_imageDir')
    ap.add_argument('--photo-map', default=PHOTO_MAP_DEFAULT,
                     help='output of match_old_photos.py: uid_hex -> {file, conf} for a real historical photo')
    ap.add_argument('--out', default=OUT_DEFAULT)
    a = ap.parse_args()

    idx = art_index(a.art_dir)
    print('app_imageDir art files indexed: %d dex numbers, %d with form variants'
          % (len(idx), sum(1 for v in idx.values() if set(v) - {''})))

    photo_map = {}
    if os.path.exists(a.photo_map):
        photo_map = json.load(open(a.photo_map, encoding='utf-8'))
    print('real historical photo matches available: %d' % len(photo_map))

    con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
    con.row_factory = sqlite3.Row
    rows = con.execute('SELECT uid_hex, pokemon_id, species_name, form_region, fresh_shiny, is_hundo '
                       'FROM pokemon WHERE in_bag=1').fetchall()

    thumb_dir = os.path.join(a.out, 'scan_thumb')
    os.makedirs(thumb_dir, exist_ok=True)

    mapping, source_map = {}, {}
    n_photo_confirmed = n_photo_move = n_hit_form = n_hit_dex = 0
    missed, shiny_no_art, shiny_dex_art = [], 0, 0

    for r in rows:
        uid = r['uid_hex']
        src_file, src_tag = None, None

        photo = photo_map.get(uid)
        if photo and os.path.isfile(photo['file']):
            src_file = photo['file']
            src_tag = 'real-photo-' + photo.get('conf', 'confirmed')
            if photo.get('conf') == 'confirmed':
                n_photo_confirmed += 1
            else:
                n_photo_move += 1
        else:
            pid = r['pokemon_id']
            forms = idx.get(pid)
            if forms:
                want = REGION_SUFFIX.get((r['form_region'] or '').strip().lower(), '')
                fn = forms.get(want)
                if fn:
                    n_hit_form += 1
                else:
                    fn = forms.get('')
                    if not fn:             # only form-specific art exists; take any rather than nothing
                        fn = sorted(forms.values())[0]
                    n_hit_dex += 1
                src_file = os.path.join(a.art_dir, fn)
                src_tag = 'app_imageDir'
                if r['fresh_shiny']:
                    shiny_dex_art += 1

        if not src_file:
            missed.append(r['species_name'])
            if r['fresh_shiny']:
                shiny_no_art += 1
            continue

        iid = image_id_for(uid)
        shutil.copyfile(src_file, os.path.join(thumb_dir, iid + '.jpg'))
        mapping[uid] = iid
        source_map[uid] = src_tag

    json.dump(mapping, open(os.path.join(a.out, 'image_map.json'), 'w', encoding='utf-8'))
    json.dump(source_map, open(os.path.join(a.out, 'source_map.json'), 'w', encoding='utf-8'), indent=0)

    tot = len(rows)
    n_shiny_total = sum(1 for r in rows if r['fresh_shiny'])
    n_shiny_photo = n_photo_confirmed + n_photo_move  # every real-photo match that's ALSO currently shiny
    # recompute shiny-photo count precisely (a real photo can belong to a non-shiny mon too)
    n_shiny_photo = sum(1 for r in rows if r['fresh_shiny'] and source_map.get(r['uid_hex'], '').startswith('real-photo'))

    print()
    print('=== RESULT ===')
    print('total in bag: %d' % tot)
    print('with ANY image: %d (%.1f%%)' % (len(mapping), len(mapping) / tot * 100))
    print('  by source:')
    print('    real historical photo, date-confirmed : %d' % n_photo_confirmed)
    print('    real historical photo, move-verified   : %d' % n_photo_move)
    print('    app_imageDir, exact dex+form            : %d' % n_hit_form)
    print('    app_imageDir, dex-only fallback         : %d' % n_hit_dex)
    print('  no art at all (PokeGenie default)         : %d across %d species' % (len(missed), len(set(missed))))
    print()
    print('shinies (%d total in bag):' % n_shiny_total)
    print('  shiny-ACCURATE art (real photo of the shiny itself): %d' % n_shiny_photo)
    print('  normal-form art only (app_imageDir, not shiny-accurate): %d' % shiny_dex_art)
    print('  no art at all: %d' % shiny_no_art)
    print()
    print('wrote %s (%d entries) and %d thumbnails to %s' % (
        os.path.join(a.out, 'image_map.json'), len(mapping), len(mapping), thumb_dir))
    print('wrote %s for the source breakdown' % os.path.join(a.out, 'source_map.json'))


if __name__ == '__main__':
    main()
