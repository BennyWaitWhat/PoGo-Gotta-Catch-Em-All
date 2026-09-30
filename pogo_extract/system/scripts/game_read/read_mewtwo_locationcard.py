#!/usr/bin/env python
"""READ-ONLY: recover the GO Fest 2026 Mewtwo location-card enum (fills a DB gap).

For target UIDs (the two GO Fest 2026 Mewtwo), walk the live bag proto, read
PokemonDisplayProto.LocationCard sub-message, and map the enum via location_card_enum.json.

The two Mewtwo (uid 7411975807261094796 CP2363/IV41, uid 5744441765404633224 CP2362/IV41)
MUST be in the heap -> open each one's detail screen in PoGo first, or this returns
'not in bag walk'. Expected enum: 248/249/250 (LcSpecialbackground2026Mewtwo001/002/003)
or 245 (Lc2026TokyoGofest001 if Tokyo-local).

WRITES NOTHING. After this confirms the enum, re-run a targeted fresh_poll + parse_fresh
so fresh_loc_card_enum persists in pokemon.db.

Validation flags (see gofest_data_model.md §4):
  [DEVICE] PokemonProto.PokemonDisplay @ +0xd8 ; displayProto.LocationCard @ +0x58 ;
           LocationCard enum @ locBytes+0x10 (all from parse_fresh.py; proven there, re-confirm)

Usage:
    python read_mewtwo_locationcard.py
    python read_mewtwo_locationcard.py 7411975807261094796 5744441765404633224
"""
import sys
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))   # pogo_extract/
sys.path.insert(0, PROJ)
import pogo_il2cpp as pg  # noqa: E402

DEFAULT_UIDS = ['7411975807261094796', '5744441765404633224']  # signed
TARGET_UIDS = [a for a in sys.argv[1:] if a.isdigit()] or DEFAULT_UIDS

# location_card_enum.json lives at pogo_extract root (per gofest_data_model.md)
ENUM_PATH = os.path.join(PROJ, 'location_card_enum.json')
ENUM = {}
if os.path.exists(ENUM_PATH):
    ENUM = {int(k): v for k, v in json.load(open(ENUM_PATH)).items()}
else:
    print(f'[!] {ENUM_PATH} not found; enum names will be numeric only.')

READ_JS = r"""
rpc.exports.readLoc = function(protoStr){
  var p = ptr(protoStr);
  var disp = p.add(0xd8).readPointer();          // PokemonProto.PokemonDisplay  [DEVICE]
  if (disp.isNull()) return {ok:false, why:'no display (mon not in heap?)'};
  var loc = disp.add(0x58).readPointer();         // displayProto.LocationCard sub-message [DEVICE]
  if (loc.isNull()) return {ok:false, why:'no LocationCard set'};
  var enumVal = loc.add(0x10).readS32();          // LocationCard enum @ +0x10 (parse_fresh.py)
  return {ok:true, enumVal:enumVal};
};
"""


def main():
    print('[*] connecting...')
    sess, pid = pg.get_session()
    print(f'[*] attached pid={pid}')

    bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
    print(f'[*] PokemonBagImpl={bag}')

    # bag_walk keys are UNSIGNED uint64 strings; convert the signed targets
    want = {str(int(u) & 0xFFFFFFFFFFFFFFFF): int(u) for u in TARGET_UIDS}
    protos = pg.find_protos_for_uids(sess, bag, list(want.keys()))
    print(f'[*] found {len(protos)} of {len(want)} target protos in the bag walk')

    sc = pg.get_script_with_helpers(sess, READ_JS)
    print('\nuid (signed)            | card enum | card name')
    print('------------------------+-----------+------------------------------')
    for us, signed in want.items():
        pp = protos.get(us)
        if not pp:
            print(f'{signed:<23} | (not in bag walk / out of heap — open its detail screen)')
            continue
        r = sc.exports_sync.read_loc(pp)
        if not r.get('ok'):
            print(f'{signed:<23} | -- {r.get("why")}')
            continue
        ev = r['enumVal']
        print(f'{signed:<23} | {ev:<9} | {ENUM.get(ev, "??(%d)" % ev)}')
    sc.unload()
    sess.detach()
    print('\n[expect] 248/249/250 (LcSpecialbackground2026Mewtwo001/002/003) or 245 (Lc2026TokyoGofest001).')
    print('[then] re-run fresh_poll + parse_fresh with these mons in heap to persist fresh_loc_card_enum.')


if __name__ == '__main__':
    main()
