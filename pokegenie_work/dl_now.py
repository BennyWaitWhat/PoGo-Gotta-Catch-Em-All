import json, os, urllib.request, urllib.error, threading, urllib.parse
from concurrent.futures import ThreadPoolExecutor
RAW = 'https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/'
up = {p.split('/')[-1]: p for p in json.load(open('sprites/upstream_files.json'))}
need = json.load(open('sprites/still_need.json'))
lock = threading.Lock(); ok = {}; bad = []
def go(item):
    key, nm = item
    dest = os.path.join('sprites', nm)
    if os.path.exists(dest) and os.path.getsize(dest) > 500:
        with lock: ok[key] = nm
        return
    try:
        req = urllib.request.Request(RAW + urllib.parse.quote(up[nm]), headers={'User-Agent': 'pg'})
        b = urllib.request.urlopen(req, timeout=30).read()
        if len(b) > 500:
            open(dest, 'wb').write(b)
            with lock: ok[key] = nm
            return
    except Exception as e:
        pass
    with lock: bad.append(key)
with ThreadPoolExecutor(max_workers=24) as ex:
    list(ex.map(go, need))
idx = json.load(open('sprites/sprite_index.json'))
idx.update(ok)
json.dump(idx, open('sprites/sprite_index.json', 'w'), indent=0)
print('downloaded %d, failed %d, index now %d' % (len(ok), len(bad), len(idx)))
