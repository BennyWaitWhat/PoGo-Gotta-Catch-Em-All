"""Send the 48 costume-evo gaps to Telegram + compute the shiny-SAFE additional trim
(cap shadow/lucky/size dupes at 3 per variant, keep ALL shinies + 100%/legacy/PvP/keep-tags),
write tag_drift.json (CLAUDE_TX add = the NEW ones not already in commons_trim_n3.json)."""
import json, sqlite3, os, urllib.request, urllib.parse
from collections import defaultdict
oc = {int(k): v for k, v in json.load(open('official_class.json')).items()}
gm = json.load(open('pvpoke_gamemaster.json'))
dex2sid = {}; sid2dex = {}; sid2evos = {}; dex2name = {}
for x in gm['pokemon']:
    sid = x['speciesId']; d = x.get('dex')
    if d is None: continue
    sid2dex[sid] = d; dex2sid.setdefault(d, sid); dex2name.setdefault(d, x['speciesName'].split(' (')[0])
    sid2evos[sid] = x.get('family', {}).get('evolutions') or []
c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row
rows = [dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1').fetchall()]

# --- costume-evo gaps -> Telegram ---
CN = {1:'PartyHat',2:'Santa',5:'Summer',6:'Halloween',7:'Anniv',8:'Cake',9:'Witch',10:'Flower',11:'Holiday',12:'Scarf',
      16:'c16',48:'c48',49:'c49',52:'c52',56:'c56',59:'c59',61:'c61',62:'c62',63:'c63',75:'c75',77:'c77',79:'c79',82:'c82',84:'c84',85:'c85'}
have = defaultdict(int)
for p in rows:
    if (p['fresh_costume'] or 0) != 0: have[(p['pokemon_id'], p['fresh_costume'])] += 1
gaps = []
for (dex, cost), n in have.items():
    sid = dex2sid.get(dex)
    for evo_sid in sid2evos.get(sid, []):
        ed = sid2dex.get(evo_sid)
        if ed is not None and (ed, cost) not in have:
            gaps.append((CN.get(cost, f'c{cost}'), dex2name.get(dex, str(dex)), dex2name.get(ed, evo_sid), n))
gaps.sort()
lines = [f"{cl}: {base}->{evo}" + (" (1 base!)" if n == 1 else f" (x{n})") for cl, base, evo, n in gaps]
msg = f"Special-evo to-do ({len(gaps)} costume evolutions you haven't done):\n\n" + "\n".join(lines)
tok = os.environ.get('TELEGRAM_BOT_TOKEN')
data = urllib.parse.urlencode({'chat_id': '8749793156', 'text': msg}).encode()
r = urllib.request.urlopen('https://api.telegram.org/bot' + tok + '/sendMessage', data=data, timeout=20)
print('telegram special-evos sent ok=', json.load(r).get('ok'), 'gaps=', len(gaps))

# --- shiny-safe additional trim ---
def htag(p, t):
    a = p.get('auth_tag_names') or ''; return t in [x for x in a.split(';') if x]
KEEP_TAGS = ['Hundos','Nundos','JUMBO','GL','UL','LL','Legacy','Background','Adventure Eff','From Ethan','From Florandez','0-15-15','Evolve Me']
def exemptp(p):
    return (p['is_shiny'] or p['iv_total'] in (0, 45) or any(htag(p, t) for t in KEEP_TAGS)
            or (p['gl_rank'] is not None and p['gl_rank'] <= 10) or (p['ul_rank'] is not None and p['ul_rank'] <= 10))
com = [p for p in rows if oc.get(p['pokemon_id']) not in (1, 2, 3)]
bucket = defaultdict(list)
for p in com:
    if not exemptp(p):
        bucket[(p['pokemon_id'], p['form'], p['fresh_costume'] or 0, p['alignment'], bool(p['is_lucky']), p['pokemon_size_category'])].append(p)
trim = []
for k, ps in bucket.items():
    ps.sort(key=lambda p: -(p['cp'] or 0)); trim += ps[3:]
prev = set(e['uid_hex'] for e in json.load(open('commons_trim_n3.json')))
new = [p for p in trim if p['uid_hex'] not in prev]
name = dex2name
bysp = defaultdict(int)
for p in new: bysp[name.get(p['pokemon_id'], str(p['pokemon_id']))] += 1
json.dump({'CLAUDE_TX': {'add': [p['uid_hex'] for p in new], 'remove': []}}, open('tag_drift.json', 'w'))
allrec = json.load(open('commons_trim_n3.json')) + [{'uid_hex': p['uid_hex'], 'species': name.get(p['pokemon_id']), 'form': p['form'], 'cp': p['cp'], 'iv': p['iv_total'], 'extra': True} for p in new]
json.dump(allrec, open('commons_trim_n3.json', 'w'), indent=1)
print(f'shiny-safe additional trim: {len(new)} new (on top of the 42)')
print('  by species:', ', '.join(f'{n} {co}' for n, co in sorted(bysp.items(), key=lambda x: -x[1])[:15]))
print('wrote tag_drift.json (CLAUDE_TX add = new only)')
