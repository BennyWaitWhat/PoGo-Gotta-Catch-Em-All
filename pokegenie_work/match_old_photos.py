"""Match current bag pokemon to a REAL historical PokeGenie scan photo from the old backup (pg.zip),
extracted to old_backup/. Conservative, date-verified matching -- never guess a picture.

Key = (pokemon_id/dex, cp, iv_atk, iv_def, iv_sta, gender_as_pokegenie).
For each bag row, look at all old-backup entries sharing that key:
  - if the old entry has a recorded capture date, accept only if it's within 1 day of the bag row's
    creation_date (UTC/local rollover slack) AND it's the unique such dated candidate for this row.
  - if no old entry has a date but exactly one undated candidate also matches this row's quick+charge
    move names, accept that (weaker corroboration, still real).
  - otherwise, no match (ambiguous or coincidental key collision) -- leave for app_imageDir fallback.
Each old-backup entry is used AT MOST ONCE (an old photo can't be assigned to two different mons).

Writes photo_map.json: {uid_hex: {"file": <path to old_backup/scan_thumb/<imageId>.jpg>, "conf": "confirmed"|"move-verified"}}
"""
import json, os, sqlite3, sys, datetime

ROOT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract"
WORK = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pokegenie_work"
OLD = os.path.join(WORK, 'old_backup')

sys.path.insert(0, ROOT)

def pg_gender(g):
    return 3 if (g in (0, None)) else int(g)

def load_move_namer():
    mid2name = json.load(open(os.path.join(ROOT, 'move_id_to_name.json'), encoding='utf-8'))
    gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
    GM_NAME = {m['moveId']: m['name'] for m in gm['moves']}
    def movename(mid):
        if not mid: return ""
        raw = mid2name.get(str(int(mid)))
        if not raw: return ""
        base = raw[:-5] if raw.endswith('_FAST') else raw
        nm = GM_NAME.get(base) or GM_NAME.get(raw)
        if nm: return nm
        if base.startswith('HIDDEN_POWER'): return 'Hidden Power'
        return ' '.join(w.capitalize() for w in base.split('_'))
    return movename

def main():
    movename = load_move_namer()

    old = json.load(open(os.path.join(OLD, 'scan_data.json'), encoding='utf-8'))
    thumb_dir = os.path.join(OLD, 'scan_thumb')

    # index old entries by key, keep only those with a real present thumbnail file
    from collections import defaultdict
    by_key = defaultdict(list)
    have_thumb = missing_thumb = 0
    for e in old:
        iid = e.get('imageId')
        if not iid or not os.path.isfile(os.path.join(thumb_dir, iid + '.jpg')):
            missing_thumb += 1
            continue
        have_thumb += 1
        key = (e['pokemonNumber'], e.get('cp', 0), e.get('avgAttackIV', 0),
               e.get('avgDefenseIV', 0), e.get('avgStaminaIV', 0), pg_gender(e.get('gender')))
        by_key[key].append(e)
    print('old entries: %d total, %d with a real present thumbnail, %d without' % (len(old), have_thumb, missing_thumb))

    con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
    con.row_factory = sqlite3.Row
    rows = con.execute('SELECT uid_hex, pokemon_id, cp, iv_atk, iv_def, iv_sta, gender, '
                        'creation_time_ms, move1, move2, fresh_shiny, is_hundo, in_bag '
                        'FROM pokemon WHERE in_bag=1 ORDER BY creation_time_ms').fetchall()

    used_old_ids = set()  # id() of old entry dicts already claimed
    photo_map = {}
    confirmed = move_verified = ambiguous = no_candidate = 0
    shiny_confirmed = hundo_confirmed = 0

    for r in rows:
        key = (r['pokemon_id'], r['cp'] or 0, r['iv_atk'] or 0, r['iv_def'] or 0,
               r['iv_sta'] or 0, pg_gender(r['gender']))
        cands = [e for e in by_key.get(key, []) if id(e) not in used_old_ids]
        if not cands:
            no_candidate += 1
            continue

        bag_date = None
        if r['creation_time_ms']:
            bag_date = datetime.datetime.fromtimestamp(r['creation_time_ms'] / 1000).date()

        dated = [e for e in cands if e.get('captureYear', 0)]
        undated = [e for e in cands if not e.get('captureYear', 0)]

        dated_ok = []
        if bag_date is not None:
            for e in dated:
                try:
                    od = datetime.date(e['captureYear'], e['captureMonth'], e['captureDay'])
                except (ValueError, KeyError):
                    continue
                if abs((od - bag_date).days) <= 1:
                    dated_ok.append(e)

        if len(dated_ok) == 1:
            chosen = dated_ok[0]
            used_old_ids.add(id(chosen))
            photo_map[r['uid_hex']] = {'file': os.path.join(thumb_dir, chosen['imageId'] + '.jpg'),
                                        'conf': 'confirmed'}
            confirmed += 1
            if r['fresh_shiny']: shiny_confirmed += 1
            if r['is_hundo']: hundo_confirmed += 1
            continue
        elif len(dated_ok) > 1:
            ambiguous += 1
            continue

        # no dated candidate -- try move-name corroboration among undated entries
        if undated:
            bag_m1, bag_m2 = movename(r['move1']), movename(r['move2'])
            mv_ok = [e for e in undated if e.get('quickMove', '') == bag_m1 and e.get('chargeMove', '') == bag_m2
                     and (bag_m1 or bag_m2)]
            if len(mv_ok) == 1:
                chosen = mv_ok[0]
                used_old_ids.add(id(chosen))
                photo_map[r['uid_hex']] = {'file': os.path.join(thumb_dir, chosen['imageId'] + '.jpg'),
                                            'conf': 'move-verified'}
                move_verified += 1
                if r['fresh_shiny']: shiny_confirmed += 1
                if r['is_hundo']: hundo_confirmed += 1
                continue
            elif len(mv_ok) > 1:
                ambiguous += 1
                continue
        no_candidate += 1

    print('MATCHED: confirmed(date) %d, move-verified %d -> total %d' % (confirmed, move_verified, confirmed + move_verified))
    print('rejected as ambiguous (multiple candidates, no way to pick): %d' % ambiguous)
    print('no candidate at all: %d' % no_candidate)
    print('of matches: %d are currently shiny, %d are hundo' % (shiny_confirmed, hundo_confirmed))
    print('bag total: %d' % len(rows))

    out_path = os.path.join(WORK, 'photo_map.json')
    json.dump(photo_map, open(out_path, 'w', encoding='utf-8'), indent=0)
    print('wrote', out_path, 'with', len(photo_map), 'entries')

if __name__ == '__main__':
    main()
