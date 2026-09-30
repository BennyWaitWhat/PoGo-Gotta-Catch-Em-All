"""Build PokeGenie thumbnails from the OFFICIAL PoGo sprites (form + shiny accurate)."""
import hashlib, json, os, shutil, sqlite3
ROOT = '../pogo_extract'
OUT = '../pokegenie_out'
idx = json.load(open('sprites/sprite_index.json'))
fe = json.load(open(ROOT + '/form_enum.json'))
con = sqlite3.connect(ROOT + '/pokemon.db'); con.row_factory = sqlite3.Row
rows = con.execute('SELECT uid_hex,pokemon_id,species_name,form,fresh_shiny FROM pokemon WHERE in_bag=1').fetchall()

def iid(u):
    h = hashlib.sha1(('pgimg:' + u).encode()).hexdigest()
    a = '0123456789abcdefghijklmnopqrstuvwxyz'; n = int(h[:24], 16); o = []
    for _ in range(14):
        n, r = divmod(n, 36); o.append(a[r])
    return ''.join(o)

td = os.path.join(OUT, 'scan_thumb'); os.makedirs(td, exist_ok=True)
mapping, src, miss, shiny_ok, shiny_tot = {}, {}, [], 0, 0
for r in rows:
    key = '%d|%s|%d' % (r['pokemon_id'], r['form'] or 0, 1 if r['fresh_shiny'] else 0)
    fn = idx.get(key)
    if r['fresh_shiny']: shiny_tot += 1
    if not fn:
        miss.append(r['species_name']); continue
    p = os.path.join('sprites', fn)
    if not os.path.exists(p):
        miss.append(r['species_name']); continue
    i = iid(r['uid_hex'])
    shutil.copyfile(p, os.path.join(td, i + '.jpg'))
    mapping[r['uid_hex']] = i
    src[r['uid_hex']] = fn
    if r['fresh_shiny'] and '.s.' in fn: shiny_ok += 1
json.dump(mapping, open(os.path.join(OUT, 'image_map.json'), 'w'))
json.dump(src, open(os.path.join(OUT, 'source_map.json'), 'w'), indent=0)
print('bag %d | with official sprite: %d (%.1f%%)' % (len(rows), len(mapping), len(mapping)/len(rows)*100))
print('shinies %d | with TRUE shiny art: %d' % (shiny_tot, shiny_ok))
print('no art: %d across %d species' % (len(miss), len(set(miss))))
