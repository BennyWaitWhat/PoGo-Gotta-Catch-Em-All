"""READ-ONLY: list the player's EARNED medals/badges from PoGo's live IL2CPP state.

Two things get read, no writes:

  1. EVENT / DYNAMIC badges (incl. GO Fest **City District** medals such as the
     'Friendship District' popup) — these live in
         PlayerStatsProto.EventBadges : RepeatedField<HoloBadgeType>   @ +0x184
     Each element is a 4-byte HoloBadgeType enum int. We resolve int -> name by
     dumping the HoloBadgeType enum (Holoholo.Rpc) from the LIVE binary, because
     2026 GO Fest district medals do NOT exist in any static string dump.

  2. STANDARD progress medals (Jogger / Kanto / Collector / Battle Girl ...) —
     these are not a list; each is a counter field on PlayerStatsProto
     (KmWalked, NumUniquePokedexEntries, NumPokemonCaptured, ...). We print the
     raw counters so the lead can map them to bronze/silver/gold/platinum tiers.

Engine: reuses pogo_il2cpp.JS_PREAMBLE + account_snapshot.js (findAll / callGetter
/ readFieldsAt) and adds two tiny RPC exports (dumpEnum, readRepeatedInt).

HARD OFFSETS (device-validated 2026-05-21 via _recon_services.py, klass 0x7623d691c0):
    PlayerStatsProto.Level                 @ +0x10  (0x10)
    PlayerStatsProto.Experience            @ +0x18
    PlayerStatsProto.KmWalked  (float)     @ +0x30
    PlayerStatsProto.NumUniquePokedexEntries@+0x38
    PlayerStatsProto.EventBadges  RF<enum> @ +0xB8 (184)   <-- the medal list
RepeatedField<int/enum> layout (proven in pogo_pipeline.py CapturedForms):
    backing array ptr = RF + 0x10 ;  count = RF + 0x18 ;  elem[i] = array + 0x20 + i*4

Usage:
    python read_medals.py                 # be on the map so PlayerService is live
    python read_medals.py --json out.json
"""
import sys, os, json, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frida
import pogo_il2cpp as pg

# account_snapshot.js gives us findAll / callGetter / readFieldsAt / enumFields.
_ENGINE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'account_snapshot.js'),
                'r', encoding='utf-8').read()

# Two extra primitives this task needs, appended after the engine.
_MEDAL_JS = r"""
// Dump an enum's {intValue: name} from the LIVE binary (incl. values absent from
// static dumps). Mirrors dump_form_enum.py: STATIC(0x10) + LITERAL(0x40) fields,
// read constant via il2cpp_field_static_get_value.
var _FX = null;
function _ensureFX() {
    if (_FX) return;
    _ensureInit();
    var il2 = Process.findModuleByName('libil2cpp.so');
    function b(n, r, a){ var x = il2.findExportByName(n); return x ? new NativeFunction(x, r, a) : null; }
    _FX = {
        cGF:  b('il2cpp_class_get_fields', 'pointer', ['pointer','pointer']),
        fGN:  b('il2cpp_field_get_name', 'pointer', ['pointer']),
        fGF:  b('il2cpp_field_get_flags', 'int', ['pointer']),
        fGSV: b('il2cpp_field_static_get_value', 'void', ['pointer','pointer']),
    };
}
rpc.exports.dumpEnum = function (ns, cls) {
    _ensureFX();
    var k = cFN(ns, cls);
    if (!k || k.isNull()) return { err: 'enum class not found: ' + ns + '.' + cls };
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var out = {}, f, n = 0;
    while ((f = _FX.cGF(k, it)) && !f.isNull()) {
        var flags = _FX.fGF(f);
        if ((flags & 0x10) === 0) continue;   // not static
        if ((flags & 0x40) === 0) continue;   // not literal/const
        var nm = _FX.fGN(f).readCString();
        var vbuf = Memory.alloc(8); vbuf.writeS64(0);
        try { _FX.fGSV(f, vbuf); out[vbuf.readS32().toString()] = nm; n++; } catch (e) {}
        if (n > 5000) break;
    }
    return { count: n, values: out };
};

// Read a RepeatedField<int|enum> living at `inst + off`. Returns the int elements.
// Layout proven on PlayerStatsProto.NumPokemonCaughtByType / CapturedForms:
//   RF.add(0x10)=array, RF.add(0x18)=count, elem = array.add(0x20 + i*4).readS32()
rpc.exports.readRepeatedInt = function (instPtrStr, off, maxN) {
    _ensureInit();
    var inst = ptr(instPtrStr);
    if (inst.isNull()) return { err: 'null instance' };
    try {
        var rf = inst.add(off).readPointer();
        if (rf.isNull()) return { count: 0, items: [] };
        var arr = rf.add(0x10).readPointer();
        var cnt = rf.add(0x18).readS32();
        if (arr.isNull() || cnt < 0 || cnt > 100000) return { err: 'bad RF cnt=' + cnt };
        var lim = (maxN && cnt > maxN) ? maxN : cnt;
        var out = [];
        for (var i = 0; i < lim; i++) out.push(arr.add(0x20 + i * 4).readS32());
        return { count: cnt, items: out };
    } catch (e) { return { err: 'threw: ' + e.toString() }; }
};
"""

# Offsets from the May-21 device recon. readFieldsAt re-reads these by name at
# runtime (so a binary update that shifts layout self-corrects); EVENT_BADGES_OFF
# is the fallback if the named field read fails.
EVENT_BADGES_OFF = 0x184  # PlayerStatsProto.EventBadges  RepeatedField<HoloBadgeType>

# Standard "progress" medals: the PlayerStatsProto counter that drives each tier.
# (name shown -> field on PlayerStatsProto). Lead maps value->tier offline.
PROGRESS_MEDALS = [
    ('Jogger (km walked)',         'KmWalked'),
    ('Kanto..Paldea (dex entries)','NumUniquePokedexEntries'),
    ('Collector (caught)',         'NumPokemonCaptured'),
    ('Scientist (evolutions)',     'NumEvolutions'),
    ('Breeder (eggs hatched)',     'NumEggsHatched'),
    ('Backpacker (pokestops)',     'PokeStopVisits'),
    ('Pokeball thrower',           'NumberOfPokeballThrown'),
    ('Battle Girl (gym atk won)',  'NumBattleAttackWon'),
    ('Ace Trainer (training won)', 'NumBattleTrainingWon'),
    ('Berry Master (berries fed)', 'NumBerriesFed'),
    ('Gym Leader (hours defended)','TotalDefendedMs'),
    ('Champion (raids won)',       'NumRaidBattleWon'),
    ('Battle Legend (legendary)',  'NumLegendaryBattleWon'),
    ('Fisher (big magikarp)',      'BigMagikarpCaught'),
    ('Youngster (tiny rattata)',   'SmallRattataCaught'),
    ('Pikachu Fan',                'NumPokemonCaughtByType'),  # repeated; informational
    ('Great League Veteran',       None),  # league wins are not in PlayerStats; see note
    ('Purifier (purified)',        'NumPokemonPurified'),
    ('Hero (grunts defeated)',     'NumGruntsDefeated'),
    ('Best Buddy',                 'NumBestBuddies'),
    ('Max Level Friends',          'NumMaxLevelFriends'),
    ('Successor (trades)',         'NumTrades'),
    ('Pilot (trade distance km)',  'TradeAccumulatedDistanceKm'),
    ('Mega Evolution Guru',        'NumTotalMegaEvolutions'),
    ('Unique Mega Evos',           'NumUniqueMegaEvolutions'),
    ('Wayfarer (agreements)',      'NumWayfarerAgreement'),
    ('Photobomb',                  'NumPhotobombSeen'),
    ('Friends (forever)',          'NumForeverFriendsEarned'),
    ('Routes accepted',            'NumRoutesAccepted'),
    ('Party challenges',           'NumPartyChallengesCompleted'),
    ('Dynamax battles entered',    'NumBreadBattlesEntered'),
    ('Dynamax battles won',        'NumBreadBattlesWon'),
    ('Check-ins',                  'NumCheckIns'),
]


def _fval(fields, name):
    """Pull the best-typed value for a named field out of readFieldsAt output."""
    e = fields.get(name)
    if not isinstance(e, dict):
        return None
    v = e.get('val', {})
    tn = (e.get('type') or '')
    if 'Single' in tn or 'float' in tn:
        return round(v.get('f32'), 3) if v.get('f32') is not None else None
    if 'Int64' in tn or 'int64' in tn or 'Double' in tn:
        return v.get('i64')
    return v.get('i32')


def run(out_path=None):
    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, _ENGINE + '\n' + _MEDAL_JS)
    print(f'[attach pid={pid}] engine+medal js loaded')

    # 1) live HoloBadgeType enum  int -> name  (covers 2026 district/friendship)
    en = sc.exports_sync.dump_enum('Holoholo.Rpc', 'HoloBadgeType')
    if 'err' in en:
        print('  enum dump FAILED:', en['err']); sess.detach(); sys.exit(1)
    badge_names = {int(k): v for k, v in en['values'].items()}
    print(f"  HoloBadgeType: {en['count']} enum values resolved from live binary")

    # 2) PlayerService singleton -> get_PlayerStats -> PlayerStatsProto ptr
    fa = sc.exports_sync.find_all('Niantic.Holoholo', 'PlayerService')
    hits = fa.get('hits', []) if isinstance(fa, dict) else []
    if not hits:
        print('  NO PlayerService instance (open the map / profile so it is live).')
        print('  find_all said:', fa); sess.detach(); sys.exit(1)
    psvc = hits[0]
    gp = sc.exports_sync.call_getter('Niantic.Holoholo', 'PlayerService', 'get_PlayerStats', psvc)
    stats_ptr = gp.get('ptr') if isinstance(gp, dict) else None
    if not stats_ptr:
        print('  get_PlayerStats returned no ptr:', gp); sess.detach(); sys.exit(1)
    print(f'  PlayerService inst={psvc}  PlayerStatsProto={stats_ptr}')

    # 3) read all PlayerStatsProto fields by name (self-correcting offsets)
    fields = sc.exports_sync.read_fields_at(stats_ptr, 'Holoholo.Rpc', 'PlayerStatsProto')
    if not isinstance(fields, dict) or 'err' in fields:
        print('  readFieldsAt PlayerStatsProto failed:', fields); sess.detach(); sys.exit(1)

    # 4) EventBadges list — prefer the named field's discovered offset, fall back to const
    eb_off = EVENT_BADGES_OFF
    if isinstance(fields.get('EventBadges'), dict):
        eb_off = fields['EventBadges'].get('off', EVENT_BADGES_OFF)
    rep = sc.exports_sync.read_repeated_int(stats_ptr, eb_off, 4096)
    sess.detach()

    if 'err' in rep:
        print('  EventBadges read err:', rep); earned = []
    else:
        earned = rep['items']
    print(f"  EventBadges @ +0x{eb_off:x}: {len(earned)} earned event/dynamic medals\n")

    # ---- report ----
    def nm(v):
        return badge_names.get(v, f'<unknown #{v}>')

    earned_named = sorted({(v, nm(v)) for v in earned}, key=lambda t: t[1])
    district = [(v, n) for v, n in earned_named
                if any(k in n.lower() for k in ('gofest', 'district', 'friendship',
                                                'city', 'safari', 'gotour', 'gowa'))]

    print('=== EVENT / DYNAMIC MEDALS EARNED (%d) ===' % len(earned_named))
    for v, n in earned_named:
        print(f'  [{v:>5}] {n}')
    print('\n--- GO Fest / District / Friendship / City highlights ---')
    if district:
        for v, n in district:
            print(f'  *** [{v:>5}] {n} ***')
    else:
        print('  (none matched gofest/district/friendship/city/safari keywords)')

    print('\n=== STANDARD PROGRESS MEDALS (raw counters; map to tiers offline) ===')
    prog = {}
    for label, fld in PROGRESS_MEDALS:
        if fld is None:
            continue
        val = _fval(fields, fld)
        prog[label] = {'field': fld, 'value': val}
        print(f'  {label:<32} {fld:<26} = {val}')

    snap = {
        'pid': pid,
        'player_stats_ptr': stats_ptr,
        'level': _fval(fields, 'Level'),
        'xp': _fval(fields, 'Experience'),
        'event_badges_off': hex(eb_off),
        'event_badges_count': len(earned_named),
        'event_badges': [{'enum': v, 'name': n} for v, n in earned_named],
        'district_medals': [{'enum': v, 'name': n} for v, n in district],
        'progress_medals': prog,
        'holo_badge_type_enum_size': en['count'],
    }
    if out_path:
        json.dump(snap, open(out_path, 'w'), indent=2)
        print(f'\nwrote {out_path}')
    return snap


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', dest='json_out', default=None, help='write snapshot JSON here')
    args = ap.parse_args()
    for attempt in range(6):
        try:
            run(args.json_out); break
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f'[retry {attempt+1}] {type(e).__name__}: {e}'); time.sleep(4)
