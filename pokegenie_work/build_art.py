"""Build ALL PokeGenie art from the official Pokemon GO asset mirror -- one pass, one source of truth.

Why this replaces fetch_sprites2.py + wire_sprites.py + add_mega_images.py + rebuild_pokedex_art.py:
the cached upstream listing those ran against held 5,733 files when the mirror actually has 11,726 --
5,993 missing, more than half. That silently cost real accuracy: costumes were never matched at all
(the old matcher passed an empty costume), and 13 mega species were invisible, which is why the user's
Mega Starmie and Mega Skarmory had no art. The listing is re-fetched live here, every run.

Naming upstream: pm<dex>[.f<FORM>][.c<COSTUME>][.g<GENDER>][.s].icon.png   (.s = shiny, .g2 = female)

Matching is two-pass and every candidate must EXIST upstream, so a pokemon can never be given another
species' picture:
  pass 1 -- shiny art only, most specific qualifier set first (form+costume+gender -> ... -> bare)
  pass 2 -- same ladder without shiny
Shiny accuracy is therefore preferred over qualifier depth, and species is never traded away for either.
A pokemon that matches nothing gets NO image and PokeGenie falls back to its own default.

Outputs (all written under pokegenie_out/):
  scan_thumb/<imageId>.jpg + image_map.json + source_map.json   collection thumbnails
  mega_thumb/<imageId>.jpg + mega_map.json                      megaImageId1/2 art
  pokedex_art/{pokedex_<k>, i_df_<k>.jpg} + pokedex_art_map.json  Pokedex + raid-boss tiles

Image ids are a deterministic hash of the pokemon uid, so a re-run overwrites its own files in place
rather than orphaning thousands of images in the app's data directory.

    python build_art.py [--jobs 24] [--no-refresh]
"""
import argparse, collections, hashlib, json, os, re, shutil, sqlite3, threading, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(BASE, 'pogo_extract')
WORK = os.path.join(BASE, 'pokegenie_work')
OUT = os.path.join(BASE, 'pokegenie_out')
SPR = os.path.join(WORK, 'sprites')
RAW = 'https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/'
TREE = 'https://api.github.com/repos/PokeMiners/pogo_assets/git/trees/master?recursive=1'
_lock = threading.Lock()

# PokeGenie's Pokedex-art form suffix -> upstream form token (only where normalising is not enough)
PG_SUFFIX = {
    'Alola': 'ALOLA', 'Galarian': 'GALARIAN', 'Hisuian': 'HISUIAN', 'Paldean': 'PALDEA',
    'Mega': 'MEGA', 'MegaX': 'MEGA_X', 'MegaY': 'MEGA_Y',
    'Deoxysattack': 'ATTACK', 'Deoxysdefense': 'DEFENSE',
    'zyg10': 'TEN_PERCENT', 'formFour': 'FIFTY_PERCENT',
    'OriBaile': 'BAILE', 'OriPau': 'PAU', 'OriPom': 'POM_POM', 'OriSensu': 'SENSU',
    'FormMidday': 'MIDDAY', 'FormMidnight': 'MIDNIGHT',
    'Sword': 'CROWNED_SWORD', 'Shield': 'CROWNED_SHIELD',
}


def norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def image_id(seed):
    h = hashlib.sha1(seed.encode()).hexdigest()
    alpha = '0123456789abcdefghijklmnopqrstuvwxyz'
    n, out = int(h[:24], 16), []
    for _ in range(14):
        n, r = divmod(n, 36)
        out.append(alpha[r])
    return ''.join(out)


def load_listing(refresh):
    p = os.path.join(SPR, 'upstream_files.json')
    if refresh or not os.path.exists(p):
        req = urllib.request.Request(TREE, headers={'User-Agent': 'pg-art',
                                                    'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.load(r)
        if d.get('truncated'):
            raise SystemExit('upstream tree listing came back TRUNCATED -- refusing to build on it')
        files = sorted(t['path'] for t in d.get('tree', [])
                       if t['type'] == 'blob' and t['path'].startswith('Images/Pokemon')
                       and t['path'].endswith('.png'))
        json.dump(files, open(p, 'w', encoding='utf-8'))
        print('refreshed upstream listing: %d pokemon images' % len(files))
    return json.load(open(p, encoding='utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=24)
    ap.add_argument('--no-refresh', action='store_true')
    a = ap.parse_args()
    os.makedirs(SPR, exist_ok=True)

    paths = {p.split('/')[-1]: p for p in load_listing(not a.no_refresh)}
    print('upstream icon files: %d' % len(paths))

    # index every icon by (dex, form, costume, gender, shiny)
    icons = {}
    forms_of = collections.defaultdict(set)
    for n in paths:
        m = re.match(r'pm(\d+)((?:\.[a-z][A-Za-z0-9_]*)*)\.icon\.png$', n)
        if not m:
            continue
        dex, rest = int(m.group(1)), m.group(2)
        f = c = g = ''
        s = False
        for part in [x for x in rest.split('.') if x]:
            if part == 's':
                s = True
            elif part[0] == 'f':
                f = part[1:]
            elif part[0] == 'c':
                c = part[1:]
            elif part[0] == 'g':
                g = part[1:]
        icons[(dex, f, c, g, s)] = n
        if f:
            forms_of[dex].add(f)

    form_enum = {int(k): v for k, v in json.load(
        open(os.path.join(ROOT, 'form_enum.json'), encoding='utf-8')).items()}
    cos_enum = {int(k): v for k, v in json.load(
        open(os.path.join(ROOT, 'costume_enum.json'), encoding='utf-8')).items()}

    # normalised token lookup per dex, so 'FlyingOkinawa' finds 'FLYING_OKINAWA'
    tok_by_dex = collections.defaultdict(dict)
    cos_by_dex = collections.defaultdict(dict)
    for (dex, f, c, g, s), n in icons.items():
        if f:
            tok_by_dex[dex].setdefault(norm(f), f)
        if c:
            cos_by_dex[dex].setdefault(norm(c), c)

    def form_token(dex, form_id, species):
        """numeric form -> the upstream token for THIS dex, or '' for the plain form

        Upstream is inconsistent about whether the token repeats the species: Rattata Alola is
        'pm19.fALOLA' but Unown A is 'pm201.fUNOWN_A' and Burmy Plant is 'pm412.fBURMY_PLANT'.
        Our enum name always carries the species ('UnownA', 'RattataAlola'), so try it BOTH ways --
        as-is and with the species prefix stripped. Missing this cost 114 pokemon their art.
        """
        name = form_enum.get(form_id or 0, '')
        if not name or name.lower() in ('unset', 'normal'):
            return ''
        cands = [name]
        s = name
        for cand in (species, (species or '').replace(' ', ''), (species or '').replace('_', '')):
            if cand and s.lower().startswith(cand.lower()):
                cands.append(s[len(cand):])
                break
        for cd in cands:
            tok = tok_by_dex[dex].get(norm(cd), '')
            if tok:
                return tok
        return ''

    def cos_token(dex, cos_id):
        name = cos_enum.get(cos_id or 0, '')
        if not name or name.lower() == 'unset':
            return ''
        return cos_by_dex[dex].get(norm(name), '')

    def pick(dex, f, c, g, shiny):
        """most specific existing icon; shiny-first, then the same ladder without shiny"""
        ladder = [(f, c, g), (f, c, ''), (f, '', g), ('', c, g),
                  (f, '', ''), ('', c, ''), ('', '', g), ('', '', '')]
        for want_shiny in ((True, False) if shiny else (False,)):
            for ff, cc, gg in ladder:
                n = icons.get((dex, ff, cc, gg, want_shiny))
                if n:
                    return n
        return None

    # ---------- resolve every pokemon in the bag ----------
    con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
    con.row_factory = sqlite3.Row
    rows = con.execute('SELECT uid_hex, pokemon_id, species_name, fresh_form, form, fresh_costume, '
                       'fresh_shiny, gender FROM pokemon WHERE in_bag=1').fetchall()
    print('bag: %d' % len(rows))

    plan = {}                      # imageId -> upstream filename
    image_map, source_map, missing = {}, {}, []
    n_shiny = n_shiny_ok = n_cos = n_cos_ok = 0
    for r in rows:
        dex = r['pokemon_id']
        fid = r['fresh_form'] if r['fresh_form'] is not None else r['form']
        f = form_token(dex, fid, r['species_name'])
        c = cos_token(dex, r['fresh_costume'])
        g = '2' if r['gender'] == 2 else ''
        shiny = bool(r['fresh_shiny'])
        if shiny:
            n_shiny += 1
        if r['fresh_costume']:
            n_cos += 1
        fn = pick(dex, f, c, g, shiny)
        if not fn:
            missing.append(r['species_name'])
            continue
        iid = image_id('pgimg:' + r['uid_hex'])
        plan[iid] = fn
        image_map[r['uid_hex']] = iid
        source_map[r['uid_hex']] = fn
        if shiny and '.s.' in fn:
            n_shiny_ok += 1
        if r['fresh_costume'] and '.c' in fn:
            n_cos_ok += 1

    # ---------- mega art for every mega species the user owns ----------
    mega_species = collections.defaultdict(set)
    for (dex, f, c, g, s), n in icons.items():
        if f.startswith('MEGA') and not c and not g:
            mega_species[dex].add(f)
    print('mega species upstream: %d' % len(mega_species))

    mega_map, mega_fields = {}, {}
    for r in rows:
        dex = r['pokemon_id']
        if dex not in mega_species:
            continue
        toks = mega_species[dex]
        slots = ([('MEGA_X', 'megaImageId1'), ('MEGA_Y', 'megaImageId2')]
                 if 'MEGA_X' in toks else [('MEGA', 'megaImageId1')])
        shiny = bool(r['fresh_shiny'])
        for tok, field in slots:
            if tok not in toks:
                continue
            fn = (icons.get((dex, tok, '', '', True)) if shiny else None) \
                or icons.get((dex, tok, '', '', False))
            if not fn:
                continue
            mid = image_id('pgmega:%s:%s' % (tok, r['uid_hex']))
            plan[mid] = fn
            mega_map[mid] = fn
            mega_fields.setdefault(r['uid_hex'], {})[field] = mid

    # ---------- Pokedex art, OWNED species only ----------
    existing = [l.strip() for l in open(os.path.join(WORK, 'pokedex_names.txt'), encoding='utf-8')
                if l.strip()]
    owned = {int(re.match(r'pokedex_(\d+)', n).group(1)) for n in existing
             if re.match(r'pokedex_(\d+)', n)}
    owned |= {r['pokemon_id'] for r in rows}

    dex_plan = {}
    for nm in existing:                                   # replace every old scan photo
        m = re.match(r'pokedex_(\d+)(?:_(.+))?$', nm)
        if not m:
            continue
        dex, suf = int(m.group(1)), m.group(2)
        tok = ''
        if suf:
            want = norm(PG_SUFFIX.get(suf, suf))
            tok = tok_by_dex[dex].get(want, '')
            if not tok:                      # upstream may prefix the species: Plant -> BURMY_PLANT
                for k, v in tok_by_dex[dex].items():
                    if k.endswith(want):
                        tok = v
                        break
        fn = pick(dex, tok, '', '', False)
        if fn:
            dex_plan[nm[len('pokedex_'):]] = fn
    n_repl = len(dex_plan)
    n_mega_dex = n_fill = 0
    for dex, toks in mega_species.items():                 # mega tiles, owned only
        if dex not in owned:
            continue
        for tok, suf in (('MEGA', 'Mega'), ('MEGA_X', 'MegaX'), ('MEGA_Y', 'MegaY')):
            if tok in toks:
                k = '%d_%s' % (dex, suf)
                if k not in dex_plan:
                    dex_plan[k] = icons[(dex, tok, '', '', False)]
                    n_mega_dex += 1
    for dex in sorted(owned):                              # base tiles, owned only
        if str(dex) in dex_plan:
            continue
        fn = pick(dex, '', '', '', False)
        if fn:
            dex_plan[str(dex)] = fn
            n_fill += 1

    # ---------- download everything referenced, once ----------
    need = sorted(set(plan.values()) | set(dex_plan.values()))
    print('distinct upstream images referenced: %d' % len(need))
    failed = []

    def fetch(fn):
        dest = os.path.join(SPR, fn)
        if os.path.exists(dest) and os.path.getsize(dest) > 500:
            return
        try:
            req = urllib.request.Request(RAW + urllib.parse.quote(paths[fn]),
                                         headers={'User-Agent': 'pg-art'})
            with urllib.request.urlopen(req, timeout=40) as r:
                b = r.read()
            if len(b) > 500:
                open(dest, 'wb').write(b)
                return
        except Exception:
            pass
        with _lock:
            failed.append(fn)

    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for i, _ in enumerate(ex.map(fetch, need), 1):
            if i % 500 == 0:
                print('  downloaded %d/%d  failed %d' % (i, len(need), len(failed)))
    if failed:
        print('DOWNLOAD FAILURES: %d  e.g. %s' % (len(failed), failed[:6]))
    bad = set(failed)

    # ---------- write the three payloads ----------
    td, md, pd = (os.path.join(OUT, 'scan_thumb'), os.path.join(OUT, 'mega_thumb'),
                  os.path.join(OUT, 'pokedex_art'))
    for d in (td, md, pd):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)

    n_t = n_m = 0
    for iid, fn in plan.items():
        if fn in bad:
            continue
        dest = md if iid in mega_map else td
        shutil.copyfile(os.path.join(SPR, fn), os.path.join(dest, iid + '.jpg'))
        if dest is md:
            n_m += 1
        else:
            n_t += 1
    n_d = 0
    for k, fn in dex_plan.items():
        if fn in bad:
            continue
        data = open(os.path.join(SPR, fn), 'rb').read()
        open(os.path.join(pd, 'pokedex_' + k), 'wb').write(data)
        open(os.path.join(pd, 'i_df_%s.jpg' % k), 'wb').write(data)
        n_d += 1

    json.dump(image_map, open(os.path.join(OUT, 'image_map.json'), 'w', encoding='utf-8'))
    json.dump(source_map, open(os.path.join(OUT, 'source_map.json'), 'w', encoding='utf-8'), indent=0)
    json.dump(mega_map, open(os.path.join(OUT, 'mega_map.json'), 'w', encoding='utf-8'))
    json.dump(mega_fields, open(os.path.join(OUT, 'mega_fields.json'), 'w', encoding='utf-8'))
    json.dump(dex_plan, open(os.path.join(OUT, 'pokedex_art_map.json'), 'w', encoding='utf-8'), indent=0)

    print()
    print('=== COLLECTION ===')
    print('  thumbnails written : %d / %d bag (%.1f%%)' % (n_t, len(rows), n_t / len(rows) * 100))
    n_shiny_art = sum(1 for r in rows if r['fresh_shiny'] and r['uid_hex'] in image_map)
    print('  shinies            : %d, of which got art %d, shiny-accurate %d (%.1f%% of those with art)'
          % (n_shiny, n_shiny_art, n_shiny_ok, n_shiny_ok / max(n_shiny_art, 1) * 100))
    print('  costumed           : %d, costume-accurate art %d (%.1f%%)'
          % (n_cos, n_cos_ok, n_cos_ok / max(n_cos, 1) * 100))
    print('  no art at all      : %d across %d species' % (len(missing), len(set(missing))))
    print('=== MEGA ===')
    print('  mega images        : %d for %d pokemon' % (n_m, len(mega_fields)))
    print('=== POKEDEX / RAID TILES ===')
    print('  old photos replaced: %d' % n_repl)
    print('  mega tiles added   : %d' % n_mega_dex)
    print('  base tiles filled  : %d' % n_fill)
    print('  total written      : %d entries (%d files), owned species only' % (n_d, n_d * 2))


if __name__ == '__main__':
    main()
