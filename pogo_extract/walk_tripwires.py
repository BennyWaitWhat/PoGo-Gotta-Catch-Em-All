"""WALK TRIPWIRES (H03, 2026-09-29): a frozen or impossible read must never pass silently again.

WHY: PoGo rebuilt its whole service graph inside one process (05:00). The old PokemonBagImpl / TaggingRpcService /
PokedexImpl / InventoryCache stayed allocated with their last contents, and the walks of 05:06, 05:09 and 05:11 read
them: the same 5,661 uids three times, newest mon 04:58:03, "caught 0, released 0", 41 "tagged", "All tags in sync",
"VERIFY OK" -- while the catcher had caught Ekans 05:00:12, Dratini 05:01:18 and Shieldon 05:09:07. Every check
re-read the same stale objects, so every check agreed with itself. The replay of all 144 walk snapshots also proves
a fourth frozen walk nobody noticed: 2026-09-24 17:33:25 missed Houndour 17:25:38, Munna, Litten and Yanma 17:31:17.

WHAT: every recrawl writes ONE fingerprint line to system/analysis/walk_fingerprints.jsonl and judges it against the
previous line of the SAME trainer. Each rule compares two sources that cannot both be frozen the same way:

  GRAPH_UNPROVEN        no InventoryCache.latestTimestamp / phone clock for the graph we read    -> STOP
  GRAPH_TS_BACKWARDS    same pid, the inventory timestamp went BACK (we read an older graph)      -> STOP
  GRAPH_STALE           phone clock - latestTimestamp > AGE_STOP_MS: WARN; > AGE_STOP_PLAYING_MS while he plays: STOP
  BAG_AHEAD_OF_INV      the bag's newest mon is newer than the inventory it came with (2 graphs)  -> STOP
  FUTURE_DATA           a mon created after the phone's own clock (garbage offset / foreign read)  -> STOP
  FROZEN_REPEAT         same pid, same inventory timestamp AND same uid set, >= 60 s apart: STOP when the catcher
                        caught in between (else WARN -- a quiet game repeats too)
  CATCHER_UNSEEN        the catcher's own counter rose since the last pass, the inventory did not -> STOP
  CATCH_AFTER_GRAPH     the catcher's own log has a catch between the graph's last update (+2 min) and the moment
                        the walk read that graph -- a live graph would have seen it              -> STOP
  COUNTER_BACKWARDS     a lifetime counter (XP, catches, km, evolutions, hatches, dex TimesCaptured) fell -> STOP
  INV_BEHIND_BAG        fresh catches in the bag, but XP / catches / dex TimesCaptured did not move -> STOP
  MIXED_GRAPH           a service this pass read belongs to another graph than the walked bag      -> STOP
  UNPROVEN_SERVICE      a service whose graph could not be read                                     -> WARN
  MULTI_GRAPH           the game holds >1 service graph (it rebuilt without a restart)             -> INFO

and, offline over the .db_snapshots (full_audit / cull_report, every pass):

  RETRO_FROZEN          an EARLIER walk missed catches that this walk proves already existed    -> WARN (loud)

Thresholds: AGE_STOP_MS is set from the two post-fix reads (inventory 20 s old at the 05:20:15 walk, 13 s old at the
05:20:54 sync, catcher on) against the frozen passes (6.6 / 9.6 / 11.5 min). The idle-on-map cadence of
latestTimestamp is NOT measured yet -- see verify_on_phone() for the read-only recipe.

Pure functions, no Frida and no adb in this module except the two optional read-only probes playing() and
catcher_state(), which only shell out to `adb shell dumpsys` / `cat`.

  python walk_tripwires.py --selftest      # the rule table against synthetic fingerprints
  python walk_tripwires.py --retro         # the snapshot proof: which walks read a frozen bag
"""
import glob, gzip, hashlib, json, os, re, shutil, sqlite3, struct, sys, tempfile, time

ROOT = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(ROOT, 'system', 'analysis', 'walk_fingerprints.jsonl')
SNAPS = os.path.join(ROOT, '.db_snapshots')
KEEP_LINES = 500
AGE_STOP_MS = 5 * 60 * 1000          # older than this: GRAPH_STALE WARN
AGE_STOP_PLAYING_MS = 10 * 60 * 1000 # older than this WHILE PoGo is on screen: STOP (2026-09-29 review: the catcher log
                                     # shows 19 live gaps > 5 min in 9,006 catches, 12 > 10 min, most with the catcher
                                     # off; age alone must not block a live cull -- the corroborated rules catch a
                                     # frozen graph instead: CATCH_AFTER_GRAPH (the catcher's own log) from the first
                                     # frozen pass on, CATCHER_UNSEEN / FROZEN_REPEAT from the second)
SLACK_MS = 2 * 60 * 1000
REPEAT_MIN_MS = 60 * 1000
POGO_LAUNCH_MS = 1467590400000
COUNTERS = ('xp', 'captured', 'km_walked', 'evolutions', 'hatched', 'dex_times_sum')
PILE_SERVICES = {'bag', 'svc', 'dex', 'inv', 'ae'}      # what the pile / its protections are computed from
STOP, WARN, INFO = 'STOP', 'WARN', 'INFO'


# ---------------------------------------------------------------- fingerprint parts (pure)
def _i64(hexstr, off):
    try:
        b = bytes.fromhex(hexstr or '')
        return struct.unpack_from('<q', b, off)[0] if off + 8 <= len(b) else 0
    except ValueError:
        return 0


def _i32(hexstr, off):
    try:
        b = bytes.fromhex(hexstr or '')
        return struct.unpack_from('<i', b, off)[0] if off + 4 <= len(b) else 0
    except ValueError:
        return 0


def uid_hex(u):
    return format(int(u) & 0xFFFFFFFFFFFFFFFF, '016x')


def walk_part(entries, walk_meta=None, prev=None):
    """From the RAW walk entries (before reconcile): the uid set digest, the newest creationTimeMs_ (@0xa0, the same
    offset parse_pokemon reads) and how many mons were created after the previous pass's newest one (fresh catches:
    an evolution or a trade keeps its OLD creation time, so it never counts)."""
    uids, created = [], []
    for rec in entries or ():
        pb = rec.get('protoBytes')
        if not pb or _i32(pb, 0x28) == 0:
            continue                                   # unreadable / pid0 (eggs, placeholders): parse_pokemon skips them too
        uids.append(uid_hex(rec['uid']))
        ct = _i64(pb, 0xa0)                            # creationTimeMs_ -- parse_pokemon's offset
        if ct > POGO_LAUNCH_MS:
            created.append(ct)
    uids.sort()
    prev_newest = ((prev or {}).get('walk') or {}).get('newest_creation_ms')
    wm = walk_meta or {}
    return {'n': len(uids), 'declared': wm.get('declared'),
            'uid_sha': hashlib.sha256('\n'.join(uids).encode()).hexdigest()[:16],
            'newest_creation_ms': max(created) if created else None,
            'new_since_prev': (sum(1 for c in created if c > prev_newest) if prev_newest else None),
            'game_count': (wm.get('game') or {}).get('get_Count')}


def inventory_part(doc, read_at_expected=None):
    """The walk's inventory.json -> the lifetime counters. None when the file is not from this walk (the read failed
    and the previous file stayed) -- an old file must not stand in for this walk's inventory."""
    if not doc or (read_at_expected and doc.get('read_at') != read_at_expected):
        return None
    p = doc.get('player') or {}
    def num(k):
        v = p.get(k)
        try:
            return float(v) if k == 'KmWalked' else int(v)
        except (TypeError, ValueError):
            return None
    fams = doc.get('families') or {}
    return {'stardust': doc.get('stardust'), 'coins': doc.get('coins'), 'xp': num('Experience'),
            'captured': num('NumPokemonCaptured'), 'km_walked': num('KmWalked'), 'evolutions': num('NumEvolutions'),
            'hatched': num('NumEggsHatched'),
            'candy_total': sum((v or {}).get('candy', 0) + ((v or {}).get('xl') or 0) for v in fams.values()) if fams else None}


def dex_part(doc):
    if not doc:
        return None
    return {'addr': doc.get('addr'), 'count': doc.get('count'),
            'times_sum': sum(int(e.get('times') or 0) for e in doc.get('entries') or ())}


def new(pid, trainer, graph, phone_now_ms, walk, services=None, playing=None, catcher=None):
    g = graph or {}
    return {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'pid': pid, 'trainer': trainer, 'phone_now_ms': phone_now_ms,
            'graph': {'bags': g.get('bags'), 'ts': _int(g.get('ts')), 'ts_other': [_int(t) for t in g.get('ts_other') or ()],
                      'player': g.get('player'), 'inv': g.get('inv'), 'bag': g.get('bag')},
            'walk': walk, 'services': services or {}, 'playing': playing, 'catcher': catcher,
            'inv': None, 'dex': None, 'tags': None}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- the rules (pure)
def _same_process(fp, prev):
    return bool(prev) and prev.get('pid') == fp.get('pid') and prev.get('trainer') == fp.get('trainer')


def check_graph(fp, prev):
    """Rules that need only the graph, the walk and the phone clock. Runs BEFORE reconcile_db."""
    out = []
    g, w = fp.get('graph') or {}, fp.get('walk') or {}
    ts, now = g.get('ts'), fp.get('phone_now_ms')
    if g.get('bags') and g['bags'] > 1:
        out.append((INFO, 'MULTI_GRAPH', 'the game holds %d service graphs (rebuilt without a restart); reading the one '
                    'updated %s, not %s' % (g['bags'], _hms(ts), ', '.join(_hms(t) for t in g.get('ts_other') or ()) or '?')))
    if not ts or ts <= 0 or not now:
        out.append((STOP, 'GRAPH_UNPROVEN', 'no inventory timestamp%s for the graph this walk read -- its liveness cannot '
                    'be proven' % ('' if now else ' / phone clock')))
        return out
    age = now - ts
    if age > AGE_STOP_MS:
        lvl = STOP if (fp.get('playing') and age > AGE_STOP_PLAYING_MS) else WARN
        out.append((lvl, 'GRAPH_STALE', 'the inventory this walk read was last updated %s, %.1f min before the walk%s'
                    % (_hms(ts), age / 60000.0, ' -- while PoGo is on screen: a frozen graph' if lvl == STOP
                       else (' (PoGo on screen: a quiet game, or frozen)' if fp.get('playing')
                             else ' (PoGo not on screen: idle, or frozen)'))))
    nc = w.get('newest_creation_ms')
    if nc and nc > ts + SLACK_MS:
        out.append((STOP, 'BAG_AHEAD_OF_INV', 'the bag holds a mon created %s but its inventory was last updated %s -- the '
                    'bag and the inventory come from different graphs' % (_hms(nc), _hms(ts))))
    if nc and nc > now + SLACK_MS:
        out.append((STOP, 'FUTURE_DATA', 'a mon created %s, after the phone clock %s -- impossible data' % (_hms(nc), _hms(now))))
    # CATCH_AFTER_GRAPH (review 2026-09-29): the first frozen pass has no previous frozen pass to repeat and its age alone
    # is a quiet game as often as a frozen one -- but the catcher's log is written by another process from the server's
    # catch replies. A catch the catcher logged AFTER the graph's last update (+ SLACK) and BEFORE this walk read the graph
    # is one the graph would show if it were live. Catches after the read are ignored (the walk could not see them).
    cl = [t for t in ((fp.get('catcher') or {}).get('catch_ms') or ()) if t and ts + SLACK_MS < t <= now]
    if cl:
        out.append((STOP, 'CATCH_AFTER_GRAPH', 'the catcher logged %d catch(es) between %s and this read (latest %s), but the '
                    'inventory this walk read was last updated %s -- the graph did not see them: a frozen read'
                    % (len(cl), _hms(ts + SLACK_MS), _hms(max(cl)), _hms(ts))))
    if _same_process(fp, prev):
        pg, pw = prev.get('graph') or {}, prev.get('walk') or {}
        pts, pnow = pg.get('ts'), prev.get('phone_now_ms')
        if pts and ts < pts - 1000:
            out.append((STOP, 'GRAPH_TS_BACKWARDS', 'the inventory timestamp went BACK from %s to %s in the same game '
                        'process -- this walk read an older graph' % (_hms(pts), _hms(ts))))
        cc, pc = fp.get('catcher') or {}, prev.get('catcher') or {}
        caught = (cc['caught'] - pc['caught']) if (cc.get('caught') is not None and pc.get('caught') is not None
                                                   and cc['caught'] > pc['caught']
                                                   and (cc.get('mtime') or 0) > (pc.get('mtime') or 0)) else 0
        if pts and ts == pts and pnow and now - pnow >= REPEAT_MIN_MS and w.get('uid_sha') == pw.get('uid_sha'):
            lvl = STOP if caught else WARN        # a quiet game repeats too; the catcher's own count is the proof
            out.append((lvl, 'FROZEN_REPEAT', 'same inventory timestamp (%s) and the same %d mons as the pass %.1f min '
                        'ago -- nothing in the game moved%s' % (_hms(ts), w.get('n') or 0, (now - pnow) / 60000.0,
                                                               ': a frozen read' if lvl == STOP else ' (no catch in between: a quiet game, or frozen)')))
        if caught and pts and ts == pts:
            out.append((STOP, 'CATCHER_UNSEEN', 'the catcher caught %d since the last pass but the inventory timestamp '
                        'did not move -- this walk cannot see them' % caught))
    return out + check_services(fp)


def check_services(fp, names=None):
    """MIXED_GRAPH / UNPROVEN_SERVICE for the service objects the pass read (fp['services'], or just `names`)."""
    out, g = [], fp.get('graph') or {}
    for name, sv in sorted((fp.get('services') or {}).items()):
        if names is not None and name not in names:
            continue
        if not isinstance(sv, dict) or not sv.get('addr'):
            continue
        lvl = STOP if name in PILE_SERVICES else WARN          # the storage cap / the balance are not pile inputs
        if name.startswith('player'):                           # a PlayerService IS the graph's anchor: compare itself
            if g.get('player') and sv['addr'] != g['player']:
                out.append((lvl, 'MIXED_GRAPH', '%s @%s is not the walked graph\'s PlayerService %s'
                            % (name, sv['addr'], g['player'])))
        elif name == 'inv':                                     # an InventoryCache IS the graph's other anchor: it holds
            if g.get('inv') and sv['addr'] != g['inv']:         # no PlayerService / InventoryCache reference of its own,
                out.append((lvl, 'MIXED_GRAPH', "inv @%s is not the walked graph's InventoryCache %s"   # so compare itself
                            % (sv['addr'], g['inv'])))           # (first live pass 2026-09-29 17:19: a false UNPROVEN_SERVICE)
        elif any(sv.get(k) and g.get(k) for k in ('player', 'inv', 'bag')):
            # R3 + R4 (Gym Battle review): every reference the service carries (player, inventory, bag) is compared, and
            # ONE contradiction is enough -- a service half in another graph is not the walked graph's.
            _refs = [k for k in ('player', 'inv', 'bag') if sv.get(k) and g.get(k)]
            _bad = [k for k in _refs if sv[k] != g[k]]
            if _bad:
                out.append((lvl, 'MIXED_GRAPH', '%s @%s belongs to another service graph (%s)' % (name, sv['addr'], '; '.join(
                    '%s %s, not the walked graph\'s %s' % (k, sv[k], g[k]) for k in _bad))))
        else:
            out.append((WARN, 'UNPROVEN_SERVICE', '%s @%s: its graph could not be read -- a stale copy would pass unseen'
                        % (name, sv['addr'])))
    return out


def check_inventory(fp, prev):
    """Rules on the lifetime counters. Runs after read_candy / read_dex, BEFORE keep_policy rebuilds the pile."""
    out = []
    inv, dex, w = fp.get('inv') or {}, fp.get('dex') or {}, fp.get('walk') or {}
    cur = dict(inv, dex_times_sum=dex.get('times_sum'))
    if prev and prev.get('trainer') == fp.get('trainer'):
        pinv, pdex = prev.get('inv') or {}, prev.get('dex') or {}
        old = dict(pinv, dex_times_sum=pdex.get('times_sum'))
        if (dex.get('count') or 0) < (pdex.get('count') or 0):
            cur['dex_times_sum'] = old['dex_times_sum'] = None   # a dex walk with fewer entries can sum lower honestly
        fell = ['%s %s -> %s' % (k, old[k], cur[k]) for k in COUNTERS
                if cur.get(k) is not None and old.get(k) is not None and cur[k] < old[k]]
        if fell:
            out.append((STOP, 'COUNTER_BACKWARDS', 'lifetime counters went DOWN (%s) -- this pass read an older graph '
                        'than the last one' % '; '.join(fell)))
        fresh = w.get('new_since_prev')
        if fresh:
            known = [k for k in ('xp', 'captured', 'dex_times_sum') if cur.get(k) is not None and old.get(k) is not None]
            still = [k for k in known if cur[k] == old[k]]
            if known and still == known:                         # a catch moves them all; a hatch moves XP and the dex
                out.append((STOP, 'INV_BEHIND_BAG', 'the bag gained %d fresh catch(es) since the last pass but %s did not '
                            'move -- the inventory is read from a frozen graph' % (fresh, ', '.join(still))))
    return out


def verdict(found):
    lv = {f[0] for f in found}
    return STOP if STOP in lv else WARN if WARN in lv else 'OK'


def _hms(ms):
    if not ms:
        return '?'
    return time.strftime('%H:%M:%S', time.localtime(ms / 1000.0))


# ---------------------------------------------------------------- history
def history(path=None):
    try:
        with open(path or HIST, encoding='utf-8') as f:
            return [json.loads(l) for l in f if l.strip()]
    except (OSError, ValueError):
        return []


def last(trainer, path=None):
    for fp in reversed(history(path)):
        if fp.get('trainer') == trainer:
            return fp
    return None


def append(fp, path=None):
    path = path or HIST
    rows = history(path)[-(KEEP_LINES - 1):] + [fp]
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + '\n')
    os.replace(tmp, path)


# ---------------------------------------------------------------- optional read-only phone probes (no Frida)
def phone_probe(adb_target=None):
    """(playing, catcher) in ONE `adb shell` round trip (the walk is timed to the second): playing = screen interactive
    AND PoGo the resumed activity (verify_tags_live.user_is_playing's rule), catcher = the on-phone catcher's own counter
    {'caught', 'mtime'} from /data/local/tmp/pogo_state.txt (mode 666, rewritten every report tick). (None, None) when
    adb cannot answer. Read-only; never touches the game."""
    import subprocess
    dev = adb_target or os.environ.get('ADB_TARGET', '100.98.158.56:5555')
    cmd = ("dumpsys power | grep -E 'mWakefulness=|mScreenOn='; dumpsys activity activities | grep ResumedActivity; "
           "echo '@@'; cat /data/local/tmp/pogo_state.txt 2>/dev/null; echo; "
           "stat -c 'MTIME %Y' /data/local/tmp/pogo_state.txt 2>/dev/null; echo '@@CL'; date +'NOW %s %H %M %S'; "
           "su -c 'tail -c 20000 " + CATCH_LOG + "' 2>/dev/null")
    try:
        o = subprocess.run(['adb', '-s', dev, 'shell', cmd], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None, None
    if '@@' not in o:
        return None, None
    o, _, cl = o.partition('@@CL')
    head, tail = o.split('@@', 1)
    awake = ('mWakefulness=Awake' in head) or ('mScreenOn=true' in head)
    resumed = [l for l in head.splitlines() if 'ResumedActivity' in l]
    playing = bool(awake and resumed and 'com.nianticlabs.pokemongo' in resumed[0]) if (awake is not None) else None
    m, t = re.search(r'caught=(\d+)', tail), re.search(r'MTIME (\d+)', tail)
    catch_ms = catch_times_ms(cl)
    if not m and not catch_ms:
        return playing, None
    return playing, {'caught': int(m.group(1)) if m else None, 'mtime': int(t.group(1)) if t else None,
                     'catch_ms': catch_ms}


CATCH_LOG = '/data/data/com.termux/files/home/pogo/system/analysis/pokemod/catch_loop.log'


def catch_times_ms(text):
    """'NOW <epoch> <H> <M> <S>' + catch_loop.log lines 'HH:MM:SS CATCH ...' (phone local time, no date) -> epoch ms of
    every CATCH line, oldest first. A time later than the phone's now is yesterday's."""
    nm = re.search(r'NOW ([0-9]+) ([0-9]+) ([0-9]+) ([0-9]+)', text or '')
    if not nm:
        return []
    now_s = int(nm.group(1))
    midnight = now_s - (int(nm.group(2)) * 3600 + int(nm.group(3)) * 60 + int(nm.group(4)))
    out = []
    for h, mi, se in re.findall(r'(?m)^([0-9][0-9]):([0-9][0-9]):([0-9][0-9]) CATCH ', text):
        t = midnight + int(h) * 3600 + int(mi) * 60 + int(se)
        if t > now_s + 60:
            t -= 86400
        out.append(t * 1000)
    return sorted(out)


def playing(adb_target=None):
    """Screen interactive AND PoGo the resumed activity (verify_tags_live.user_is_playing's rule). None if unknown."""
    import subprocess
    dev = adb_target or os.environ.get('ADB_TARGET', '100.98.158.56:5555')
    try:
        pw = subprocess.run(['adb', '-s', dev, 'shell', 'dumpsys', 'power'], capture_output=True, text=True, timeout=15).stdout
        if not (('mWakefulness=Awake' in pw) or ('mScreenOn=true' in pw)):
            return False
        top = subprocess.run(['adb', '-s', dev, 'shell', 'dumpsys', 'activity', 'activities'], capture_output=True,
                             text=True, timeout=15).stdout
        for ln in top.splitlines():
            if 'ResumedActivity' in ln:
                return 'com.nianticlabs.pokemongo' in ln
        return False
    except Exception:
        return None


def catcher_state(adb_target=None):
    """The on-phone catcher's own counter (/data/local/tmp/pogo_state.txt, mode 666, written every report tick):
    {'caught', 'mtime'} or None. Read-only `cat` + `stat`; never touches the game."""
    import subprocess
    dev = adb_target or os.environ.get('ADB_TARGET', '100.98.158.56:5555')
    try:
        o = subprocess.run(['adb', '-s', dev, 'shell', 'cat /data/local/tmp/pogo_state.txt; echo; '
                            'stat -c %Y /data/local/tmp/pogo_state.txt'], capture_output=True, text=True, timeout=15).stdout
        m = re.search(r'caught=(\d+)', o)
        t = re.findall(r'^(\d{9,})\s*$', o, re.M)
        return {'caught': int(m.group(1)), 'mtime': int(t[-1]) if t else None} if m else None
    except Exception:
        return None


# ---------------------------------------------------------------- RETRO_FROZEN: the snapshot proof (offline)
def _snap_rows(path, tmpdir):
    stamp = re.search(r'pokemon\.db\.(\d{4}-\d\d-\d\d_\d{6})', path).group(1)
    tmp = os.path.join(tmpdir, 'wt_%s.db' % stamp)
    with gzip.open(path, 'rb') as f, open(tmp, 'wb') as g:
        shutil.copyfileobj(f, g)
    try:
        c = sqlite3.connect('file:%s?mode=ro&immutable=1' % tmp.replace(os.sep, '/'), uri=True)
        cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)')}
        ls = 'last_scanned' if 'last_scanned' in cols else 'NULL'
        tt = 'COALESCE(traded_time_ms,0)' if 'traded_time_ms' in cols else '0'
        rows = {r[0]: r for r in c.execute(
            'SELECT uid_hex, COALESCE(creation_time_ms,0), iv_atk, iv_def, iv_sta, species_name, %s, %s, '
            'COALESCE(is_traded,0) FROM pokemon WHERE in_bag=1' % (ls, tt))}
        c.close()
    finally:
        os.remove(tmp)
    walk = max((r[6] for r in rows.values() if r[6]), default=None)
    wms = int(time.mktime(time.strptime(walk[:19], '%Y-%m-%dT%H:%M:%S')) * 1000) if walk else \
        int(time.mktime(time.strptime(stamp, '%Y-%m-%d_%H%M%S')) * 1000)
    return {'stamp': stamp, 'walk_ms': wms, 'newest': max((r[1] for r in rows.values()), default=0), 'rows': rows}


def _snap_rows_cached(path, tmpdir, cache_dir):
    """_snap_rows, memoised as one small JSON per snapshot (a snapshot never changes once written)."""
    name = os.path.basename(path)
    cp = os.path.join(cache_dir, name + '.rows.json')
    try:
        d = json.load(open(cp, encoding='utf-8'))
        d['rows'] = {u: tuple(r) for u, r in d['rows'].items()}
        return d
    except (OSError, ValueError, KeyError):
        pass
    d = _snap_rows(path, tmpdir)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        json.dump({'stamp': d['stamp'], 'walk_ms': d['walk_ms'], 'newest': d['newest'],
                   'rows': {u: list(r) for u, r in d['rows'].items()}}, open(cp, 'w', encoding='utf-8'))
    except OSError:
        pass
    return d


def retro_frozen(snap_dir=None, last_n=40, slack_ms=SLACK_MS, cache_dir=None):
    """[(stamp, walk_ms, [(creation_ms, species, first_seen_stamp)])] for every walk among the last `last_n` snapshots
    that MISSED a genuine catch a later walk proves already existed: a new uid that is not an evolution of a mon that
    left in the same step (same IVs + creation time), not traded, created after that walk's own newest mon and more
    than slack_ms before it walked. Zero false positives on 144 real walks (2026-09-23..29): it names exactly the
    three frozen walks of 2026-09-29 05:06/05:09/05:11 and 2026-09-24 17:33:25."""
    paths = sorted(glob.glob(os.path.join(snap_dir or SNAPS, 'pokemon.db.*.before_sync.*.gz')))[-last_n:]
    tmpdir = tempfile.mkdtemp(prefix='walk_tripwires_')
    cache_dir = cache_dir or os.path.join(ROOT, 'system', 'analysis', 'retro_rows_cache')
    try:
        walks = [_snap_rows_cached(p, tmpdir, cache_dir) for p in paths]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    try:                                                    # keep the cache to the snapshots still being judged
        keep = {os.path.basename(p) + '.rows.json' for p in paths}
        for f in os.listdir(cache_dir):
            if f.endswith('.rows.json') and f not in keep:
                os.remove(os.path.join(cache_dir, f))
    except OSError:
        pass
    first = {}
    for i in range(1, len(walks)):
        P, N = walks[i - 1], walks[i]
        gone = {(r[1], r[2], r[3], r[4]) for u, r in P['rows'].items() if u not in N['rows']}
        for u, r in N['rows'].items():
            if u in P['rows'] or u in first:
                continue
            if (r[1], r[2], r[3], r[4]) in gone or r[7] or r[8]:
                continue
            first[u] = (i, r[1], r[5])
    out = []
    for i, P in enumerate(walks):
        missed = sorted((c, nm, walks[j]['stamp']) for u, (j, c, nm) in first.items()
                        if j > i and P['newest'] < c < P['walk_ms'] - slack_ms)
        if missed:
            out.append((P['stamp'], P['walk_ms'], missed))
    return out


def retro_lines(found):
    return ['RETRO_FROZEN: the walk of %s (%s) read a FROZEN bag -- it missed %d catch(es) made before it walked: %s. '
            'Anything that pass reported as tagged / in sync / verified was judged on stale objects.'
            % (s, _hms(w), len(m), ', '.join('%s %s' % (nm, _hms(c)) for c, nm, _ in m[:5]) + (' ...' if len(m) > 5 else ''))
            for s, w, m in found]


def verify_on_phone():
    """The read-only calibration still owed (needs the phone, NOT while he plays): with the game idle on the map,
    catcher off, read graphOf(bag).ts and Date.now() every 30 s for 10 min, then the same with the catcher on and with
    PoGo backgrounded. AGE_STOP_MS must sit above the idle-on-map maximum and below 6.6 min (the first frozen pass)."""
    return verify_on_phone.__doc__


# ---------------------------------------------------------------- self-test (synthetic, offline)
def _selftest():
    T = 1790672393114                                                # the stale graph's timestamp, 04:59:53 local
    def fp(now, ts, uid='u1', n=5661, newest=T - 110000, pid=5429, playing=True, **kw):
        f = new(pid, 'BennyValentinC', {'bags': 1, 'ts': ts, 'player': '0xP', 'inv': '0xI'}, now,
                {'n': n, 'uid_sha': uid, 'newest_creation_ms': newest, 'new_since_prev': kw.pop('fresh', None)},
                playing=playing)
        f.update(kw)
        return f
    live = fp(T + 20000, T)                                          # read 20 s after the inventory updated
    assert verdict(check_graph(live, None)) == 'OK', check_graph(live, None)
    p1 = fp(T + 396900, T)                                           # 05:06:30 -- the first frozen pass, 6.6 min
    assert [c for _, c, _ in check_graph(p1, live)] == ['GRAPH_STALE', 'FROZEN_REPEAT'], check_graph(p1, live)
    assert verdict(check_graph(fp(T + 396900, T, playing=False), None)) == WARN        # idle phone: say it, do not stop
    p2 = fp(T + 576900, T)                                           # 05:09:30
    assert 'FROZEN_REPEAT' in [c for _, c, _ in check_graph(p2, p1)]
    idle = [f for f in check_graph(fp(T + 200000, T, playing=False), fp(T + 20000, T, playing=False)) if f[1] == 'FROZEN_REPEAT']
    assert idle and idle[0][0] == WARN, idle                         # an idle phone: said, not stopped
    assert verdict(check_graph(fp(T + 60000, T - 5000), fp(T + 30000, T))) == STOP     # ts went back
    assert 'BAG_AHEAD_OF_INV' in [c for _, c, _ in check_graph(fp(T + 20000, T, newest=T + 600000), None)]
    assert 'GRAPH_UNPROVEN' in [c for _, c, _ in check_graph(fp(T + 20000, None), None)]
    mixed = fp(T + 20000, T, services={'svc': {'addr': '0xS', 'player': '0xOLD'}, 'ae': {'addr': '0xA'},
                                       'player_state': {'addr': '0x6bfbcf01c0'}})
    got = {c: lv for lv, c, _ in check_graph(mixed, None) if c != 'MIXED_GRAPH'}
    mg = [lv for lv, c, m in check_graph(mixed, None) if c == 'MIXED_GRAPH']
    assert sorted(mg) == [STOP, WARN] and got.get('UNPROVEN_SERVICE') == WARN, (mg, got)   # svc STOPs, player_state WARNs
    cat_prev = fp(T + 20000, T, catcher={'caught': 10, 'mtime': 100})
    cat_now = fp(T + 200000, T, uid='u2', catcher={'caught': 14, 'mtime': 300})
    assert 'CATCHER_UNSEEN' in [c for _, c, _ in check_graph(cat_now, cat_prev)]
    a = fp(T + 20000, T); a['inv'] = {'xp': 100, 'captured': 5}; a['dex'] = {'times_sum': 50}
    b = fp(T + 90000, T + 80000, fresh=3); b['inv'] = {'xp': 100, 'captured': 5}; b['dex'] = {'times_sum': 50}
    assert [c for _, c, _ in check_inventory(b, a)] == ['INV_BEHIND_BAG']
    h = fp(T + 90000, T + 80000, fresh=1); h['inv'] = {'xp': 600, 'captured': 5}; h['dex'] = {'times_sum': 51}
    assert check_inventory(h, a) == []                               # a hatch: captured still, XP + dex moved -> fine
    part = fp(T + 90000, T + 80000); part['inv'] = {'xp': 100}; part['dex'] = {'times_sum': 40, 'count': 900}
    a['dex']['count'] = 949
    assert check_inventory(part, a) == []                            # a partial dex walk sums lower honestly
    c_ = fp(T + 90000, T + 80000); c_['inv'] = {'xp': 90, 'captured': 5}; c_['dex'] = {'times_sum': 50}
    assert [c for _, c, _ in check_inventory(c_, a)] == ['COUNTER_BACKWARDS']
    other = fp(T + 90000, T + 80000); other['trainer'] = 'florandez'; other['inv'] = {'xp': 1}
    assert check_inventory(other, a) == []                           # a different trainer is never compared
    # review 2026-09-29: age alone WARNs up to 10 min while playing; the catcher's log proves a frozen first pass
    assert {lv for lv, c, _ in check_graph(p1, None) if c == 'GRAPH_STALE'} == {WARN}          # 6.6 min, playing
    assert {lv for lv, c, _ in check_graph(fp(T + 11 * 60000, T), None) if c == 'GRAPH_STALE'} == {STOP}   # 11 min
    cf = fp(T + 396900, T, catcher={'caught': None, 'mtime': None, 'catch_ms': [T + 12000, T + 200000, T + 400000]})
    got = [(lv, c) for lv, c, _ in check_graph(cf, None) if c == 'CATCH_AFTER_GRAPH']
    assert got == [(STOP, 'CATCH_AFTER_GRAPH')], got                 # 3:20 after the last update, before the read
    ok_ = fp(T + 396900, T, catcher={'caught': None, 'mtime': None, 'catch_ms': [T + 60000, T + 500000]})
    assert not [c for _, c, _ in check_graph(ok_, None) if c == 'CATCH_AFTER_GRAPH']   # inside the slack / after the read
    tt = catch_times_ms('NOW 1790700000 17 20 00' + chr(10) + '17:07:02 CATCH Wild #17 ball=1' + chr(10) +
                        '23:59:59 CATCH Wild #1 ball=1' + chr(10) + '17:07:11 run 484s')
    mid = 1790700000 - (17 * 3600 + 20 * 60)                        # the phone's local midnight today
    assert tt == [(mid - 1) * 1000, (mid + 17 * 3600 + 7 * 60 + 2) * 1000], tt   # 23:59:59 is yesterday's
    anchor = fp(T + 20000, T, services={'inv': {'addr': '0xI'}})       # the graph's own InventoryCache: proven
    assert check_services(anchor) == [], check_services(anchor)
    stray = fp(T + 20000, T, services={'inv': {'addr': '0xOTHER'}})
    assert [(lv, c) for lv, c, _ in check_services(stray)] == [(STOP, 'MIXED_GRAPH')]
    half = fp(T + 20000, T, services={'svc': {'addr': '0xS', 'player': '0xP', 'inv': '0xOTHERINV'}})   # R4
    assert [(lv, c) for lv, c, _ in check_services(half)] == [(STOP, 'MIXED_GRAPH')], check_services(half)
    bagonly = fp(T + 20000, T, services={'svc': {'addr': '0xS', 'bag': '0xOTHERBAG'}})
    bagonly['graph']['bag'] = '0xB'
    assert [(lv, c) for lv, c, _ in check_services(bagonly)] == [(STOP, 'MIXED_GRAPH')], check_services(bagonly)   # R3
    print('walk_tripwires selftest: OK')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        _selftest()
    elif '--retro' in sys.argv:
        n = int(sys.argv[sys.argv.index('--retro') + 1]) if len(sys.argv) > sys.argv.index('--retro') + 1 else 40
        found = retro_frozen(last_n=n)
        print('\n'.join(retro_lines(found)) or 'RETRO_FROZEN: no walk among the last %d missed a catch' % n)
    else:
        print(__doc__)
