"""Give every mega-capable pokemon its MEGA art in PokeGenie, shiny-accurate.

User 2026-09-02: "I also noticed you didn't seem to extract or gather all the MEGA pokemon form images."
Correct -- add_images.py only ever set `imageId` (the base-form thumbnail). PokeGenie stores the mega
picture SEPARATELY, in per-scan fields `megaImageId1` / `megaImageId2` (confirmed in the app's own dex:
MEGA_1_LIST / MEGA_2_LIST / doesNotHaveMegaImage, and in the user's old backup where 6 entries carried a
megaImageId1). Without them the app falls back to `doesNotHaveMegaImage` when the mega toggle is used.

Slots: Charizard is the only species with two megas in Pokemon GO -> MEGA_X = slot 1, MEGA_Y = slot 2.
Every other mega species is single -> slot 1 only.

Runtime path is app_imageDir/i_<imageId>.jpg (dex string "i_%s.jpg" + getDir("imageDir")); files/scan_thumb
is only the BACKUP layout, which is why thumbnails rendered as placeholders until this was corrected.

    python add_mega_images.py
"""
import collections, hashlib, io, json, os, re, sqlite3, sys, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(BASE, 'pogo_extract')
WORK = os.path.join(BASE, 'pokegenie_work')
OUT  = os.path.join(BASE, 'pokegenie_out')
SPR  = os.path.join(WORK, 'sprites')
RAW  = 'https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/'

def image_id_for(seed):
    h = hashlib.sha1(seed.encode()).hexdigest()
    alpha = '0123456789abcdefghijklmnopqrstuvwxyz'
    n = int(h[:24], 16); out = []
    for _ in range(14):
        n, r = divmod(n, 36); out.append(alpha[r])
    return ''.join(out)

up = json.load(open(os.path.join(SPR, 'upstream_files.json'), encoding='utf-8'))
names = {p.split('/')[-1]: p for p in up}
meg = collections.defaultdict(dict)
for n in names:
    m = re.match(r'pm(\d+)\.f(MEGA(?:_X|_Y)?)(\.s)?\.icon\.png$', n)
    if m:
        meg[int(m.group(1))].setdefault(m.group(2), {})[bool(m.group(3))] = n
print('mega species upstream: %d (X/Y: %s)' % (len(meg), sorted(d for d, v in meg.items() if 'MEGA_X' in v)))

# uid <- imageId, so we can find each scan entry's pokemon from the id already written into it
image_map = json.load(open(os.path.join(OUT, 'image_map.json'), encoding='utf-8'))
by_iid = {v: k for k, v in image_map.items()}

con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db')); con.row_factory = sqlite3.Row
info = {r['uid_hex']: (r['pokemon_id'], bool(r['fresh_shiny']), r['species_name'])
        for r in con.execute('SELECT uid_hex, pokemon_id, fresh_shiny, species_name '
                             'FROM pokemon WHERE in_bag=1')}

stage = os.path.join(OUT, 'mega_thumb'); os.makedirs(stage, exist_ok=True)

def sprite(fn):
    """Local path to an upstream icon, downloading once if needed."""
    dest = os.path.join(SPR, fn)
    if os.path.exists(dest) and os.path.getsize(dest) > 500:
        return dest
    req = urllib.request.Request(RAW + urllib.parse.quote(names[fn]), headers={'User-Agent': 'pg-mega'})
    with urllib.request.urlopen(req, timeout=30) as r:
        b = r.read()
    if len(b) <= 500:
        return None
    open(dest, 'wb').write(b)
    return dest

sd_path = os.path.join(OUT, 'scan_data.json')
data = json.load(open(sd_path, encoding='utf-8'))
entries = data if isinstance(data, list) else (data.get('scans') or list(data.values())[0])

n_set = n_slot2 = n_shiny = 0
missing_art = collections.Counter()
new_files = {}

for e in entries:
    iid = e.get('imageId')
    uid = by_iid.get(iid)
    if not uid:
        continue
    dex, shiny, species = info.get(uid, (None, False, ''))
    forms = meg.get(dex)
    if not forms:
        continue
    slots = [('MEGA_X', 'megaImageId1'), ('MEGA_Y', 'megaImageId2')] if 'MEGA_X' in forms \
            else [('MEGA', 'megaImageId1')]
    for tok, field in slots:
        v = forms.get(tok)
        if not v:
            continue
        fn = v.get(shiny) or v.get(False)          # shiny art if it exists, else normal -- never wrong species
        if not fn:
            missing_art[species] += 1
            continue
        src = sprite(fn)
        if not src:
            missing_art[species] += 1
            continue
        mid = image_id_for('pgmega:%s:%s' % (tok, uid))
        dst = os.path.join(stage, mid + '.jpg')
        if not os.path.exists(dst):
            open(dst, 'wb').write(open(src, 'rb').read())
        new_files[mid] = dst
        e[field] = mid
        n_set += 1
        if field == 'megaImageId2':
            n_slot2 += 1
        if shiny and v.get(shiny):
            n_shiny += 1

json.dump(data, open(sd_path, 'w', encoding='utf-8'), separators=(',', ':'))
json.dump({k: os.path.basename(v) for k, v in new_files.items()},
          open(os.path.join(OUT, 'mega_map.json'), 'w', encoding='utf-8'))

print('mega image fields written : %d (slot2/Charizard-Y: %d)' % (n_set, n_slot2))
print('shiny-accurate mega art   : %d' % n_shiny)
print('distinct mega files staged: %d -> %s' % (len(new_files), stage))
if missing_art:
    print('no mega art for           : %s' % dict(missing_art))
print('patched %s' % sd_path)
