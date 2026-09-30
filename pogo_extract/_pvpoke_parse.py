import json, sys
sys.stdout.reconfigure(encoding='utf-8')

for league, fn in [('UL', 'pvpoke_UL.json'), ('ML', 'pvpoke_ML.json')]:
    d = json.load(open(fn, encoding='utf-8'))
    ratings = [e.get('rating', 0) for e in d]
    mono = all(ratings[i] >= ratings[i+1] for i in range(len(ratings)-1))
    print(f'\n=== PVPoke {league} — {len(d)} entries, monotonic={mono} ===')
    print(f'  keys: {list(d[0].keys())}')
    for i, e in enumerate(d[:30], 1):
        sid = e.get('speciesId', '')
        sn = e.get('speciesName', '')
        r = e.get('rating', '?')
        ms = e.get('moveset', [])
        print(f'{i:>2}. {r:>5}  {sn:<30} [{sid}]  {ms}')
