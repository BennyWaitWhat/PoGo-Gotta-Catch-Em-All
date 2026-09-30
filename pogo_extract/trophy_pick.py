"""One nundo per look (user 2026-09-17: "one nundo. keep the most exotic places not in the US ones if you had to pick").

A look = species, form, shiny, shadow/purified, costume, costume form, Dynamax/Gigantamax, background card, art
background, XXL and lucky -- two nundos that differ in any of these are different collectibles and both stay.
Within one look the keeper is the one caught FARTHEST FROM ATLANTA, GA (user 2026-09-23), an unknown catch place
last; ties go to the more powered-up copy. keep_config caps.nundo copies
per look are kept. ONE definition for the engine, the pre-flight and the audits.
"""
import math
from collections import defaultdict

import keep_config
from costume_forms import is_costume_form

HOME = (33.749, -84.388)   # Atlanta, GA (user 2026-09-23)


def _is_us(lat, lon):
    """True / False from the catch coordinates, None when unknown.
    ponytail: bounding boxes (contiguous US, Alaska, Hawaii) -- a border city in Canada or Mexico reads as US;
    swap in a reverse geocoder if a choice ever hinges on that."""
    if lat is None or lon is None:
        return None
    return bool((24.4 <= lat <= 49.4 and -125.0 <= lon <= -66.9)
                or (51.0 <= lat <= 71.5 and (lon <= -129.0 or lon >= 172.0))
                or (18.8 <= lat <= 22.4 and -160.5 <= lon <= -154.6))


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def look(r):
    f = r['fresh_form'] or r['form'] or 0
    return (r['pokemon_id'], r['form'] or 0, bool(r['fresh_shiny']), r['fresh_alignment'] or 0, r['fresh_costume'] or 0,
            f if is_costume_form(f) else 0,
            r['fresh_bread_mode'] or 0,   # every Max mode is its own bundle (evolvable_forms.BREAD_MODES)
            (r['fresh_loc_card_enum'] or 0) if r['fresh_has_location_card'] else 0,
            r['fresh_natural_art_bg'] or 0, (r['pokemon_size_category'] or 0) == 5, bool(r['is_lucky']))


def _exotic_first(r):
    # FARTHEST FROM ATLANTA FIRST (user 2026-09-23: "always try to keep a nundo thats the further away from Atlanta,
    # GA"). Pure distance: a Honolulu nundo now beats a Havana one. An unknown catch place cannot be measured, so it
    # goes last. 100 km steps make the same city a tie, and then the more powered-up copy wins.
    if r['lat'] is None or r['lon'] is None:
        return (1, 0, -(r['level'] or 0), -(r['cp'] or 0), r['uid_hex'])
    return (0, -round(_km(HOME, (r['lat'], r['lon'])) / 100), -(r['level'] or 0), -(r['cp'] or 0), r['uid_hex'])


def is_nundo(r):
    return bool(r['is_zero'] and r['pokemon_id'])


def pick_nundos(rows):
    """uid_hex of the nundos to keep: caps.nundo per look, most exotic catch place first."""
    n = keep_config.cap('nundo')
    g = defaultdict(list)
    for r in rows:
        if is_nundo(r):
            g[look(r)].append(r)
    return {x['uid_hex'] for lst in g.values() for x in sorted(lst, key=_exotic_first)[:n]}


if __name__ == '__main__':
    assert _is_us(37.8, -122.4) and _is_us(40.77, -73.97) and _is_us(21.3, -157.8)
    assert _is_us(18.93, 72.83) is False and _is_us(34.7, 135.5) is False and _is_us(None, None) is None
    rows = [dict(uid_hex='sf', pokemon_id=81, form=0, fresh_form=0, fresh_shiny=0, fresh_alignment=0, fresh_costume=0,
                 fresh_bread_mode=0, fresh_has_location_card=0, fresh_loc_card_enum=0, fresh_natural_art_bg=0,
                 pokemon_size_category=3, is_lucky=0, is_zero=1, lat=37.8, lon=-122.4, level=30, cp=900)]
    rows.append(dict(rows[0], uid_hex='mumbai', lat=18.93, lon=72.83, level=11, cp=343))
    rows.append(dict(rows[0], uid_hex='unknown', lat=None, lon=None, level=40, cp=1200))
    assert pick_nundos(rows) == {'mumbai'}, pick_nundos(rows)
    osaka = [dict(rows[0], uid_hex='osaka_l4', lat=34.69957, lon=135.49592, level=4), dict(rows[0], uid_hex='osaka_l24', lat=34.69905, lon=135.49886, level=24)]
    assert pick_nundos(osaka) == {'osaka_l24'}, pick_nundos(osaka)
    hon_hav = [dict(rows[0], uid_hex='honolulu', lat=21.31, lon=-157.86), dict(rows[0], uid_hex='havana', lat=23.11, lon=-82.37)]
    assert pick_nundos(hon_hav) == {'honolulu'}, pick_nundos(hon_hav)   # distance, not country
    print('trophy_pick self-check OK')
