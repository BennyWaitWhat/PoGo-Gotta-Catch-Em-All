"""gm_guard.py -- the guard rail around the CLIENT game master (gamemaster_pokeminers.json).

WHY (2026-09-30): refresh_pokeminers() downloaded PokeMiners' latest.json over the installed file with one check
('>= 1500 pokemonSettings'): no diff, no stamp, no review. Measured 0.407 -> 0.427: 22 in-bag mons hold a move that went
from 'no normal roll' to 'plain TM' (each can lose its Legacy protection), 58 rows change evolvability (25 more rows flip in
the resting account's bag). This module is the pure half of the fix; system/scripts/refresh_gamemaster.py is the
orchestrator (network, install, review record).

    stamp     read_meta / write_meta / new_meta   {batch_ts, batch_utc, apk, folder, downloaded_at, sha256, ...}
    upstream  parse_ts / lookup_apk               the 13-byte latest/timestamp.txt; the APK from the history folder name
    diff      diff_gm / digest_lines              what changed, on the fields the keep engine reads
    impact    load_bag / assess                   which IN-BAG rows (the active account's and every resting account's: the
                                                  file is shared) flip a keep verdict, by REUSING the engine's own
                                                  functions (detect_legacy pools, evolvable_forms, size_line,
                                                  remote_trade_picks, audit_gamemaster) against the candidate file BEFORE
                                                  it is installed. Axes: moves, evolve, size (numbers + types), tradable,
                                                  transferable, rarity
    warn      freshness_findings                  the offline audit WARN (audit_invariants I2.7)

FAIL CLOSED: a candidate the engine's own loaders cannot read is never installed; a baseline / bag / verdict that cannot
be read is a STOP (exit 2 + the review record), never a pass. Read-only: this module writes nothing but what the caller
asks (write_meta) and its own temp dir. No adb, no frida, no phone. Never changes what is KEPT.
"""
import calendar
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
from collections import OrderedDict, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PM_BASE = 'https://raw.githubusercontent.com/PokeMiners/game_masters/master/latest/'
PM_TS_URL = PM_BASE + 'timestamp.txt'          # 13 bytes: the batch time in ms since the epoch
PM_JSON_URL = PM_BASE + 'latest.json'
PM_TREE_URL = 'https://api.github.com/repos/PokeMiners/game_masters/git/trees/master?recursive=1'
MIN_POKEMON_SETTINGS = 1500     # what refresh_pokeminers() always required (18,8xx templates / 2,4xx pokemonSettings today)
SHRINK_FLOOR = 0.9              # a candidate with < 90% of the installed pokemonSettings count looks truncated
MIN_BAG_ROWS = 50               # fewer in-bag rows than this is not a bag: nothing can be judged -> STOP, never 'no flips'
MAX_VERIFY_AGE_DAYS = 14        # the client GM was last compared with PokeMiners' latest longer ago than this -> WARN
MAX_BATCH_AGE_DAYS = 150        # longest 2026 PokeMiners gap was 133 days (Apr 17 -> Aug 28); older than this -> WARN
SLOTS = ('move1', 'move2', 'move3')
ROW_COLS = ('uid_hex, species_name, pokemon_id, form, fresh_form, fresh_costume, move1, move2, move3')
_norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x).upper())


class GMUnreadable(Exception):
    """A game master file the engine must not trust: missing, truncated, not JSON, wrong shape, too small."""


# ------------------------------------------------------------------------------------------------ file + stamp helpers
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_gm(path, min_settings=None):
    """(templates, sha256, n_pokemonSettings). Raises GMUnreadable for anything short of a whole, plausible game master.
    Every element is checked (18k dicts, ~10 ms): a half-parsed or hand-mangled file must not reach the engine."""
    min_settings = MIN_POKEMON_SETTINGS if min_settings is None else min_settings
    try:
        sha = sha256_file(path)
        with open(path, 'r', encoding='utf-8') as f:
            gm = json.load(f)
    except (OSError, UnicodeDecodeError, ValueError, MemoryError) as e:
        raise GMUnreadable('%s: %s: %s' % (os.path.basename(path), type(e).__name__, e))
    if not isinstance(gm, list):
        raise GMUnreadable('%s: top level is %s, not a template list' % (os.path.basename(path), type(gm).__name__))
    n = 0
    for t in gm:
        if not isinstance(t, dict) or not isinstance(t.get('templateId'), str) or not isinstance(t.get('data', {}), dict):
            raise GMUnreadable('%s: an element is not a {templateId, data} template' % os.path.basename(path))
        if 'pokemonSettings' in t.get('data', {}):
            n += 1
    if n < min_settings:
        raise GMUnreadable('%s: only %d pokemonSettings (need %d) -- truncated?' % (os.path.basename(path), n, min_settings))
    return gm, sha, n


def _utc(ts, fmt='%Y-%m-%d %H:%M:%S'):
    return time.strftime(fmt, time.gmtime(ts))


def parse_ts(text):
    """latest/timestamp.txt -> int milliseconds. ValueError on anything that is not a plausible 2001-2096 time."""
    if isinstance(text, bytes):
        text = text.decode('ascii', 'strict')
    v = int(text.strip())
    if not 10 ** 12 < v < 4 * 10 ** 12:
        raise ValueError('timestamp %r is not milliseconds since the epoch' % text.strip()[:20])
    return v


def parse_apk(folder):
    """'gm_v2_apk4270_2026.08.28-17.35.50' -> '0.427.0'; '..apk3951..' -> '0.395.1'. None when it does not parse.
    PokeMiners writes the version as digits: minor = all but the last digit, patch = the last digit."""
    m = re.search(r'apk(\d{3,6})(?:_|$)', str(folder))
    if not m:
        return None
    d = m.group(1)
    return '0.%d.%s' % (int(d[:-1]), d[-1])


def apk_tuple(v):
    try:
        t = tuple(int(x) for x in str(v).strip().split('.'))
        return t if 2 <= len(t) <= 4 else None
    except ValueError:
        return None


_FOLDER = re.compile(r'previous_game_masters/(gm_v\d+_apk\d{3,6}_(\d{4})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2}))(?:/|$)')


def apk_from_tree(tree, batch_ts_ms):
    """(apk, folder) of the previous_game_masters folder that IS this batch, from the GitHub trees API answer (a dict).
    (None, None) when the tree is truncated (a partial listing may hide the folder), holds no match, or is malformed.
    The folder name carries the batch time in the pusher's LOCAL time (+10:00 in August; +11:00 in an Australian summer),
    so the match is: naive time - batch UTC = a whole 9..12 hours, within 5 s. Never a nearest-folder guess."""
    try:
        if not isinstance(tree, dict) or tree.get('truncated') is not False:
            return None, None
        want = int(batch_ts_ms) // 1000
        hits = set()
        for e in tree.get('tree') or []:
            m = _FOLDER.search(str(e.get('path', '')))
            if not m:
                continue
            y, mo, d, h, mi, s = (int(x) for x in m.groups()[1:])
            delta = calendar.timegm((y, mo, d, h, mi, s)) - want
            off = round(delta / 3600.0)
            if 9 <= off <= 12 and abs(delta - off * 3600) <= 5:
                hits.add(m.group(1))
        if len(hits) != 1:
            return None, None
        folder = hits.pop()
        return parse_apk(folder), folder
    except (TypeError, ValueError, AttributeError):
        return None, None


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'pogo-gm-guard/1', 'Accept': 'application/vnd.github+json, */*'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def lookup_apk(batch_ts_ms, fetch=http_get):
    """(apk, folder) or (None, None): best effort, NEVER raises (the tree API is rate limited to 60/h/IP and is refused
    outright in a session without GitHub access -- the apk is a nicety for the audit WARN, not a gate)."""
    try:
        return apk_from_tree(json.loads(fetch(PM_TREE_URL, 25).decode('utf-8')), batch_ts_ms)
    except Exception:
        return None, None


def new_meta(batch_ts_ms, sha, apk, folder, now, tail_pending):
    """The stamp of an INSTALLED (or adopted) batch. tail_pending = the reconcile + rank pass this GM still owes."""
    m = OrderedDict()
    m['batch_ts'] = int(batch_ts_ms)
    m['batch_utc'] = _utc(batch_ts_ms / 1000.0)
    m['apk'] = apk
    m['folder'] = folder
    m['downloaded_ts'] = int(now)
    m['downloaded_at'] = _utc(now)
    m['sha256'] = sha
    m['checked_ts'] = int(now)
    m['checked_at'] = _utc(now)
    m['upstream_ts'] = int(batch_ts_ms)
    m['tail_pending'] = bool(tail_pending)
    return m


def read_meta(path):
    """The meta dict, or None when it is missing / unreadable / not the shape write_meta writes (callers WARN, never crash)."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            m = json.load(f)
        if isinstance(m, dict) and isinstance(m.get('batch_ts'), int) and isinstance(m.get('sha256'), str):
            return m
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    return None


def write_meta(path, meta):
    """ATOMIC (tmp + os.replace). ASCII only. False (never raises) when it could not be written."""
    tmp = '%s.%d.tmp' % (path, os.getpid())
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=1)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def next_backup_path(path, day=None):
    """<path>.bak-YYYYMMDD, or -2, -3 ... : NEVER an existing backup (two installs in a day must not overwrite the
    pre-batch file with the first batch -- refresh_gamemaster's pvpoke backup does)."""
    base = '%s.bak-%s' % (path, day or time.strftime('%Y%m%d'))
    p, n = base, 1
    while os.path.exists(p):
        n += 1
        p = '%s-%d' % (base, n)
    return p


def clear_tail_pending(meta_path):
    """The reconcile + rank pass an install owed has run: drop the flag. Never raises."""
    m = read_meta(meta_path)
    if m and m.get('tail_pending'):
        m['tail_pending'] = False
        write_meta(meta_path, m)


def local_state(gm_path, meta):
    """'no-file' | 'no-meta' | 'sha-mismatch' | 'ok': is the installed file the one its stamp describes?"""
    if not os.path.exists(gm_path):
        return 'no-file'
    if meta is None:
        return 'no-meta'
    try:
        return 'ok' if sha256_file(gm_path) == meta.get('sha256') else 'sha-mismatch'
    except OSError:
        return 'no-file'


# ------------------------------------------------------------------------------------------------------------------ diff
def _pokemon_settings(gm):
    return {t['templateId']: t['data']['pokemonSettings'] for t in gm
            if isinstance(t.get('data'), dict) and isinstance(t['data'].get('pokemonSettings'), dict)}


def _forms(gm):
    r = {}
    for t in gm:
        fs = (t.get('data') or {}).get('formSettings')
        if isinstance(fs, dict):
            for f in fs.get('forms') or []:
                if isinstance(f, dict):
                    r[str(f.get('form'))] = f
    return r


def _extended_sizes(gm):
    """{templateId: canonical sizeSettings} of the EXTENDED_V####_POKEMON_* templates (pokemonExtendedSettings)."""
    return {t['templateId']: _canon(t['data']['pokemonExtendedSettings'].get('sizeSettings')) for t in gm
            if isinstance(t.get('data'), dict) and isinstance(t['data'].get('pokemonExtendedSettings'), dict)}


def _moves_str(x):
    return sorted(map(str, x or []))


def _canon(b):
    return json.dumps(b, sort_keys=True, default=str)


def diff_gm(old, new):
    """OrderedDict {label: [strings]} of what changed between two client game masters, on the fields the keep engine
    reads (the whole evolutionBranch, not a key whitelist: a new gate key must not slip past). Only non-empty labels."""
    out = OrderedDict()
    A, B = _pokemon_settings(old), _pokemon_settings(new)

    def add(label, v):
        out.setdefault(label, []).append(v)
    for k in sorted(set(B) - set(A)):
        add('pokemon templates added', k)
    for k in sorted(set(A) - set(B)):
        add('pokemon templates removed', k)
    for k in sorted(set(A) & set(B)):
        a, b = A[k], B[k]
        short = k.split('_POKEMON_', 1)[-1]
        if sorted(map(_canon, a.get('evolutionBranch') or [])) != sorted(map(_canon, b.get('evolutionBranch') or [])):
            add('evolutionBranch changed', short)
        for f in ('pokemonClass', 'isTransferable', 'isTradable', 'isDeployable', 'type', 'type2', 'familyId'):
            if a.get(f) != b.get(f):
                add('%s changed' % f, '%s: %s -> %s' % (short, a.get(f), b.get(f)))
        if a.get('stats') != b.get('stats'):
            add('base stats changed', short)
        if _canon(a.get('allowNoevolveEvolution')) != _canon(b.get('allowNoevolveEvolution')):
            add('allowNoevolveEvolution changed (costumes that may evolve)', short)
        for f in ('quickMoves', 'cinematicMoves', 'eliteQuickMove', 'eliteCinematicMove', 'nonTmCinematicMoves'):
            ma, mb = set(_moves_str(a.get(f))), set(_moves_str(b.get(f)))
            if ma != mb:
                add('%s changed' % f, '%s +%s -%s' % (short, sorted(mb - ma), sorted(ma - mb)))
        ta = sorted(str(o.get('tempEvoId', '')) for o in a.get('tempEvoOverrides') or [] if isinstance(o, dict))
        tb = sorted(str(o.get('tempEvoId', '')) for o in b.get('tempEvoOverrides') or [] if isinstance(o, dict))
        if ta != tb or _canon(a.get('tempEvoOverrides')) != _canon(b.get('tempEvoOverrides')):
            add('mega/primal (tempEvoOverrides) changed', short)
        if (a.get('shadow') is None) != (b.get('shadow') is None):
            add('shadow availability changed', short)
        # NOT informational (2026-09-30, review): size_line.best_points scores a copy at every LATER stage it can become from
        # THESE numbers (the live read only fixes a stage the bag holds), so a change here moves an XXL keep; the 'size' axis
        # of assess() judges it per row, this label only says what moved
        sa = tuple(a.get(x) for x in ('pokedexHeightM', 'pokedexWeightKg', 'heightStdDev', 'weightStdDev')) + (_canon(a.get('sizeSettings')),)
        sb = tuple(b.get(x) for x in ('pokedexHeightM', 'pokedexWeightKg', 'heightStdDev', 'weightStdDev')) + (_canon(b.get('sizeSettings')),)
        if sa != sb:
            add('size numbers changed', short)
    XA, XB = _extended_sizes(old), _extended_sizes(new)          # the EXTENDED_V####_POKEMON_* bounds (XXL upper bound, size bands)
    for k in sorted(set(XA) & set(XB)):
        if XA[k] != XB[k]:
            add('extended sizeSettings (XXL bound, size bands) changed', k.split('_POKEMON_', 1)[-1])
    fa, fb = _forms(old), _forms(new)
    for f in sorted(set(fb) - set(fa)):
        add('form added' + (' (costume)' if fb[f].get('isCostume') else ''), f)
    for f in sorted(set(fa) - set(fb)):
        add('form removed', f)
    for f in sorted(set(fa) & set(fb)):
        if bool(fa[f].get('isCostume')) != bool(fb[f].get('isCostume')):
            add('form isCostume flipped', '%s: %s -> %s' % (f, bool(fa[f].get('isCostume')), bool(fb[f].get('isCostume'))))
    return out


def digest_lines(diff, per_cat=3, width=150):
    """Compact ASCII digest: one line per label, its count and the first few examples."""
    lines = []
    for label, items in diff.items():
        ex = '; '.join(items[:per_cat]) + (' ...' if len(items) > per_cat else '')
        lines.append(('%4d  %s: %s' % (len(items), label, ex))[:width])
    return lines or ['   0  no keep-relevant field differs']


# ------------------------------------------------------------------------------------------------------------ verdicts
def _import_root(name):
    """Import a pogo_extract module without letting its import-time os.chdir (audit_gamemaster) leak to the caller."""
    cwd = os.getcwd()
    try:
        return importlib.import_module(name)
    finally:
        os.chdir(cwd)


def fresh_evolvable_forms(tag, gm_path, work_dir):
    """A PRIVATE INSTANCE of evolvable_forms, loaded from `gm_path`, its cache in `work_dir`. evolvable_forms.py is not
    edited (it is in keep_policy._engine_sha: an edit re-stamps the whole pile) and the live module, its module globals
    and system/analysis/evolvable_forms.json are never touched. Raises whatever _load() raises on a file it cannot read
    (0.395.1 has integer branch forms and crashes it: that is an unreadable candidate, not an install)."""
    spec = importlib.util.spec_from_file_location('evolvable_forms_gg_' + tag, os.path.join(ROOT, 'evolvable_forms.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._GM = gm_path
    m._CACHE = os.path.join(work_dir, 'evolvable_forms_%s.json' % tag)
    m._load()
    return m


def fresh_size_line(tag, gm_path, work_dir):
    """A PRIVATE INSTANCE of size_line whose tables -- every form's height / weight / std-devs, the XXL upper bound and the six
    size bands (pokemonSettings.sizeSettings and the EXTENDED_V####_POKEMON_* templates), the types -- are built by the module's
    OWN _load() / _load_types() from `gm_path` (2026-09-30, review: the guard judged moves, evolution, tradability and rarity
    but not the numbers size_line.best_points scores an XXL copy by, so a batch that moved them installed unseen).
    size_line.py is not edited (it is in keep_policy._engine_sha, like evolvable_forms.py) and the live module is never
    touched: _load / _load_types / _load_live read everything through the module global HERE, which points at a private
    directory holding just this candidate and form_enum.json -- with no showcase_gm_live.json in it the live read is off, so
    the two files are compared as the monthly dump says them (the live read is the same for both). Raises whatever _load()
    raises on a file it cannot read: an unreadable candidate, never an install."""
    d = os.path.join(work_dir, 'size_line_' + tag)
    os.makedirs(d)
    shutil.copyfile(gm_path, os.path.join(d, 'gamemaster_pokeminers.json'))
    shutil.copyfile(os.path.join(ROOT, 'form_enum.json'), os.path.join(d, 'form_enum.json'))
    spec = importlib.util.spec_from_file_location('size_line_gg_' + tag, os.path.join(ROOT, 'size_line.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.HERE = d
    m._load()
    m._load_types()
    return m


class View(object):
    """Every client-game-master verdict the keep engine reads, built by the engine's OWN functions from one file."""

    def __init__(self, gm, gm_path, tag, work_dir, move_map):
        dl = _import_root('detect_legacy')
        ag = _import_root('audit_gamemaster')
        rtp = _import_root('remote_trade_picks')
        self.move_map = move_map
        self.pools = dl._game_master_pools(move_map, gm)        # moves the game rolls normally (any form)
        self.roll = dl._game_master_rollable(move_map, gm)      # plain-TM pool: vetoes a stale pvpoke elite flag
        self.cls, _dex, self.tf_form, self.tf_pid, _g = ag.scan_client_gm(gm)
        self.row_transferable = ag.row_transferable
        self.trade = rtp.tradable_tables_from(gm)
        self.row_tradable = rtp.row_tradable
        self.ef = fresh_evolvable_forms(tag, gm_path, work_dir)
        self.sl = fresh_size_line(tag, gm_path, work_dir)


def evo_facts(ef, r):
    """The row's evolution verdict: everything the keep engine reads from evolvable_forms about THIS row, walked the way the
    engine walks it (2026-09-30; the design's own-branch-only verdict missed both of the first two, shown by a critic run):
      row_can_evolve  the form / costume rule (True / False / None)
      is_middle_pid   the middle-stage flag that CAPS costume copies (costume_cap 3 -> 1, read by keep_policy / audit_cull /
                      preflight): a new non-baby pre-evolution ABOVE a held species flips it though its own branches did not move
      form hops       target_forms / can_reach (rank_cache reach, size_line) walk the branches to depth 4 (FlabebeRed ->
                      FLOETTERED -> FLORGESRED): every hop's target forms + gender, gate reasons and gate detail -- read by the
                      bare target AND by each target form: a REGIONAL branch is keyed by its form only ('slowbro_galarian', never
                      'slowbro'), so a quest gate on the Galarian Slowpoke line is invisible to the bare key (2026-09-30, review)
      stages          path_cost / path_items / family (keep_policy._afford: a copy is held beyond its stage cap only for an
                      evolution its family can pay) walk the species chain to depth 4: every stage's candy, item, item count,
                      family and gendered target forms -- so a change further down the line flips the held pre-evolution too
    Public accessors where they exist; the private tables only where the module offers no per-row accessor
    (audit_invariants._gm_steps already reads ef._costs the same way). Deterministic for the same content in any order."""
    fid = r['fresh_form'] or r['form'] or 0
    pid = int(r['pokemon_id'] or 0)
    gid = ef._dexname.get(pid)
    start = [k for k in (ef.form_name(fid), _norm(gid) if gid else '') if k]
    seen, frontier, hops = set(start), list(start), []
    gn = ef.__dict__.get('_gg_gnorm')                    # normalised gate key -> gate key: once per file
    if gn is None:
        gn = ef.__dict__['_gg_gnorm'] = {_norm(g): g for g in ef._gated}
    for _ in range(4):                                   # target_forms' depth
        nxt = []
        for k in frontier:
            for t, forms in sorted((ef._tform.get(k) or {}).items()):
                fg = tuple((gn[f], tuple(ef.gate_reason(gn[f])), json.dumps(ef._gdetail.get(gn[f], {}), sort_keys=True))
                           for f, _g in sorted(tuple(x) for x in forms) if f in gn)
                hops.append((k, t, tuple(sorted(tuple(x) for x in forms)), tuple(ef.gate_reason(t)),
                             json.dumps(ef._gdetail.get(t, {}), sort_keys=True), fg))
                for f, _g in forms:
                    if f not in seen:
                        seen.add(f)
                        nxt.append(f)
        if not nxt:
            break
        frontier = nxt
    reach, fr = ({gid} if gid else set()), ([gid] if gid else [])
    for _ in range(4):                                   # the species-level chain path_cost / path_items follow
        nx = []
        for s in fr:
            for t in sorted(set(ef._costs.get(s) or {}) | set(ef._items.get(s) or {})):
                if t not in reach:
                    reach.add(t)
                    nx.append(t)
        fr = nx
    stages = tuple((s, json.dumps(ef._costs.get(s) or {}, sort_keys=True), json.dumps(ef._items.get(s) or {}, sort_keys=True),
                    json.dumps(ef._icost.get(s) or {}, sort_keys=True), ef._family.get(s),
                    json.dumps([ef._gform.get(s + '|MALE'), ef._gform.get(s + '|FEMALE')], sort_keys=True)) for s in sorted(reach))
    mid = ef.__dict__.setdefault('_gg_middle', {})       # species-level and a full scan of the cost table: once per species per file
    if pid not in mid:
        mid[pid] = ef.is_middle_pid(pid)
    return (ef.row_can_evolve(r), mid[pid], tuple(hops), stages)


_SIZE_TABLES = ('numbers', 'base numbers', 'xxl bound', 'types')


def _sid_facts(sl, sid):
    """What size_line resolves for a LATER stage id (a pvpoke-style speciesId, 'rapidash' / 'slowbro_galarian'): the numbers
    projected_points / showcase_points_at / project read, the XXL upper bound (showcase_points_at's own two-key line) and
    the types xxl_keepers scores per type -- size_line's own lookups, in its own order."""
    xup = sl._XUP.get(sl._norm(sid)) or sl._XUP.get(sl._norm(str(sid).split('_')[0]))
    return (sid, sl._rec_for_sid(sid, own=True), sl._rec_for_sid(sid), xup, sl.types_for_sid(sid))


def later_sids(v, r, evo):
    """The LATER stage ids (pvpoke-style speciesIds) this row's size verdict reads, from the evolve walk (evo = evo_facts): the
    species chain minus the row's own species, every branch target, and each regional / gendered target form as the id the engine
    uses for it (SLOWBROGALARIAN -> 'slowbro_galarian'; a colour like FLORGESRED gives 'florges_red', which just falls back to
    'florges': harmless). A superset of what keep_policy.pvp_later_stages hands best_points (measured on the real bag)."""
    sl = v.sl
    sids = {s[0].lower() for s in evo[3]} - {(v.ef._dexname.get(int(r['pokemon_id'] or 0)) or '').lower()}
    for h in evo[2]:                                     # hops: (source key, target species, ((target form, gender), ...), ...)
        sids.add(h[1])
        tn = sl._norm(h[1])
        for f, _g in h[2]:
            if f.startswith(tn) and f[len(tn):] not in ('', 'NORMAL'):
                sids.add('%s_%s' % (h[1], f[len(tn):].lower()))
    return sids


def size_facts(v, r, evo):
    """The row's SIZE verdict (2026-09-30, review: the one keep input the first version did not judge): everything size_line
    resolves from the client game master for THIS copy, under the candidate file -- (numbers, base numbers, xxl bound, types):
      numbers / base numbers   height, weight and both std-devs (_OWN: the form's own record an evolution scales between;
                               _BASE: the score / z baseline -- they differ only in a size-form family)
      xxl bound                sizeSettings.xxlUpperBound (pokemonSettings, else the EXTENDED_V####_POKEMON_* template): the n
                               every score divides by
      types                    type / type2 (the xxl_per_type trim scores a copy once per type)
    Resolved the way the engine resolves them, so a template that merely APPEARS for a form the bag already holds (same numbers
    as the species it fell back to) is no change, and a number that moves is: for the row's OWN stage size_line's accessors
    (_rec_for_row / _xup_for_row); for every LATER stage the evolve walk above reaches (the species chain, each branch target
    and the regional / gendered target forms -- what pvp_later_stages hands best_points) _rec_for_sid / types_for_sid.
    best_points is the max over the own stage and every later stage's PROJECTED points, so a later stage's numbers decide an
    XXL keep; the live read fixes the stages the bag holds, never one it does not. Measured 2026-09-30 on the real bag: the
    XXL Ponyta scores 983 at its own stage (live read) and 1082 as a projected Rapidash; scale the base sizes x0.6 and the
    projection is 735, best_points falls to 983, under min_points (1000), and a copy kept only as 'xxl' leaves the keep."""
    sl = v.sl
    pid = int(r['pokemon_id'] or 0)
    chain = []                                           # the keys size_line tries for this row's own stage, in its order
    for f in (r['fresh_form'], r['form']):
        nm = sl._norm(sl._ENUM.get(int(f or 0), ''))
        if nm:
            chain += ['DEX%d:%s' % (pid, nm), nm]
    chain.append('DEX%d' % pid)
    own = ('own', sl._rec_for_row(r, own=True), sl._rec_for_row(r), sl._xup_for_row(r),
           next((sl._TYPES[k] for k in chain if sl._TYPES.get(k)), ()))
    return (own,) + tuple(_sid_facts(sl, sid) for sid in sorted(later_sids(v, r, evo)))


def row_verdict(v, r, enum):
    """{axis: verdict} of one in-bag row under View v. Raises on anything it cannot judge (the caller fails closed)."""
    pid = r['pokemon_id']
    mv = []
    for k in SLOTS:
        raw = r[k]
        name = v.move_map.get(str(raw)) if raw else None
        if not name:
            continue                       # empty slot / a move id the map cannot name: detect_legacy protects it anyway
        pool = v.pools.get(pid)
        mv.append((name, bool(pool) and name not in pool, name in (v.roll.get(pid) or ())))
    evo = evo_facts(v.ef, r)
    return {'moves': tuple(mv),
            'evolve': evo,
            'size': size_facts(v, r, evo),
            'tradable': bool(v.row_tradable(r, v.trade, enum)),
            'transferable': bool(v.row_transferable(r, enum, v.tf_form, v.tf_pid)),
            'rarity': tuple(sorted(k.replace('POKEMON_CLASS_', '') for k, ds in v.cls.items() if pid in ds))}


def _evo_change(ea, eb):
    """A short human description of how an evolution verdict (evo_facts) changed."""
    if ea[0] != eb[0]:
        return 'can_evolve %s -> %s' % (ea[0], eb[0])
    bits = []
    if ea[1] != eb[1]:
        bits.append('middle stage %s -> %s' % (ea[1], eb[1]))
    ha, hb = {(h[0], h[1]): h for h in ea[2]}, {(h[0], h[1]): h for h in eb[2]}
    for k in sorted(set(ha) | set(hb)):
        a, b = ha.get(k), hb.get(k)
        if a is None or b is None:
            bits.append('%s%s>%s' % ('+' if a is None else '-', k[0], k[1]))
        elif a != b:
            bits.append('%s>%s: %s' % (k[0], k[1], ', '.join('%s %s->%s' % (n, x, y) for n, x, y in zip(('forms', 'gates', 'detail', 'form gates'), a[2:], b[2:]) if x != y)))
    sa, sb = {s[0]: s for s in ea[3]}, {s[0]: s for s in eb[3]}
    for s in sorted(set(sa) | set(sb)):
        a, b = sa.get(s), sb.get(s)
        if a is None or b is None:
            bits.append('%sstage %s' % ('+' if a is None else '-', s))
        elif a != b:
            bits.append('%s: %s' % (s, ', '.join('%s %s->%s' % (n, x, y) for n, x, y in zip(('candy', 'item', 'item_n', 'family', 'gender forms'), a[1:], b[1:]) if x != y)))
    return ('evolution chain: ' + ('; '.join(bits) or 'changed'))[:120]


def _size_change(sa, sb):
    """['KEY table+table', ...] for every key whose size / type numbers moved between two size_facts. Only keys BOTH files look
    up for this row: a stage that appears or disappears is an evolution change, which the evolve axis already flags."""
    da, db = {x[0]: x[1:] for x in sa}, {x[0]: x[1:] for x in sb}
    return ['%s %s' % (k, '+'.join(n for n, x, y in zip(_SIZE_TABLES, da[k], db[k]) if x != y))
            for k in sorted(set(da) & set(db)) if da[k] != db[k]]


def _move_dir(a, b):
    lost = (a[1] and not b[1]) or ((not a[2]) and b[2])
    gained = ((not a[1]) and b[1]) or (a[2] and not b[2])
    return 'LOST' if lost and not gained else 'GAINED' if gained and not lost else 'CHANGED'


def compare_row(va, vb):
    """[(axis, what, old, new, direction)] for every axis whose verdict differs between two verdict dicts."""
    out = []
    if va['moves'] != vb['moves']:
        for a, b in zip(va['moves'], vb['moves']):
            if a != b:
                d = _move_dir(a, b)
                sp = lambda x: 'no normal roll' if x[1] else ('plain TM' if x[2] else 'normal roll')
                out.append(('moves', a[0], sp(a), sp(b), d))
    if va['evolve'] != vb['evolve']:
        out.append(('evolve', _evo_change(va['evolve'], vb['evolve']), '', '', 'CHANGED'))
    sz = _size_change(va['size'], vb['size'])
    if sz:
        out.append(('size', ('size / types: ' + ', '.join(sz))[:120], '', '', 'CHANGED'))
    for ax in ('tradable', 'transferable'):
        if va[ax] != vb[ax]:
            out.append((ax, ax, str(va[ax]), str(vb[ax]), 'CHANGED'))
    if va['rarity'] != vb['rarity']:
        out.append(('rarity', 'pokemonClass', '/'.join(va['rarity']) or 'NORMAL', '/'.join(vb['rarity']) or 'NORMAL',
                    'GAINED' if len(vb['rarity']) > len(va['rarity']) else 'LOST' if len(vb['rarity']) < len(va['rarity']) else 'CHANGED'))
    return out


def load_rows(db_path):
    """[dict] of every in-bag row, read-only (the repo's own ro URI). Raises OSError NAMING the file when it is unreadable: a stray
    0-byte accounts/<name>/pokemon.db (the repo's accidental-sqlite3.connect class) would otherwise only say 'no such table: pokemon'."""
    if not os.path.exists(db_path):
        raise OSError('no such file: %s' % db_path)
    try:
        c = sqlite3.connect('file:%s?mode=ro' % db_path.replace('\\', '/'), uri=True)
        c.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in c.execute('SELECT %s FROM pokemon WHERE in_bag=1' % ROW_COLS)]
        finally:
            c.close()
    except sqlite3.Error as e:
        raise OSError('%s: %s: %s' % (db_path, type(e).__name__, e))


def load_bag(db_path):
    """The rows the client game master is judged against: the ACTIVE account's bag (db_path, the live data set) plus every RESTING
    account's parked bag (accounts/<name>/pokemon.db, see switch_account.py). The game master is ONE file for both trainers, so a
    batch installed during one account's cull would otherwise change the other's verdicts unseen (measured 0.407 -> 0.427: 25 of
    the resting account's 939 mons flip; none is visible from the active bag). The active account's own parked copy is a stale
    duplicate of the live set and is skipped; with no readable active_account.txt every parked set is judged (extra rows only add
    noise). A resting row is named 'Species (account)'. Raises whatever load_rows raises for ANY of them: a bag that cannot be
    read cannot be judged (assess() turns that into a STOP)."""
    rows = load_rows(db_path)
    if len(rows) < MIN_BAG_ROWS:            # an empty ACTIVE bag is a STOP whatever else rests: assess() checks the count
        return rows
    base = os.path.dirname(os.path.abspath(db_path))
    try:
        with open(os.path.join(base, 'active_account.txt'), encoding='utf-8') as f:
            active = f.read().strip() or None
    except OSError:
        active = None
    adir = os.path.join(base, 'accounts')
    for name in (sorted(os.listdir(adir)) if os.path.isdir(adir) else []):
        p = os.path.join(adir, name, 'pokemon.db')
        if name == active or not os.path.isfile(p):
            continue
        for r in load_rows(p):
            r['species_name'] = '%s (%s)' % (r['species_name'], name)
            rows.append(r)
    return rows


def assess(old_path, new_path, rows, move_map, enum, min_settings=None, min_rows=None):
    """Compare the INSTALLED client game master with a CANDIDATE, on the in-bag rows. Never writes outside a private temp
    dir. Returns a dict:
      rows / move_map / enum may each be a value or a zero-argument callable (read only when the bytes differ).
      verdict  SAME (identical bytes) | CLEAR (differs, no in-bag verdict moved) | FLIPS (>= 1 row moved or could not be
               judged) | UNREADABLE_NEW (the candidate is not a whole game master / the engine cannot load it: do NOT
               install, the installed one stays) | STOP (the baseline, the bag or a verdict cannot be read: nothing can
               be proven, so nothing is installed and a human is asked)
      reason   one ASCII line       diff  {label: [..]}      flips [dict]      nulled [uid]      axes {axis: rows}
      old / new  {'sha256', 'n'}"""
    min_rows = MIN_BAG_ROWS if min_rows is None else min_rows
    res = {'verdict': None, 'reason': '', 'diff': OrderedDict(), 'flips': [], 'nulled': [], 'axes': {}, 'old': None, 'new': None}

    def done(verdict, reason):
        res['verdict'], res['reason'] = verdict, reason
        return res
    try:
        new_gm, new_sha, new_n = load_gm(new_path, min_settings)
    except GMUnreadable as e:
        return done('UNREADABLE_NEW', 'the candidate is not a whole game master (%s)' % e)
    res['new'] = {'sha256': new_sha, 'n': new_n}
    try:
        old_gm, old_sha, old_n = load_gm(old_path, min_settings)
    except GMUnreadable as e:
        return done('STOP', 'the INSTALLED client game master cannot be read, so nothing can be compared (%s) -- restore '
                            'pogo_extract/gamemaster_pokeminers.json (python tools/pogo_data.py pull, or a dated '
                            'gamemaster_pokeminers.json.bak-* copy) and run again' % e)
    res['old'] = {'sha256': old_sha, 'n': old_n}
    if old_sha == new_sha:
        return done('SAME', 'identical bytes')
    if new_n < SHRINK_FLOOR * old_n:
        return done('UNREADABLE_NEW', 'the candidate has %d pokemonSettings against %d installed (< %d%%) -- looks truncated'
                    % (new_n, old_n, int(SHRINK_FLOOR * 100)))
    try:                                                       # lazily: identical bytes never need the bag
        rows, move_map, enum = [x() if callable(x) else x for x in (rows, move_map, enum)]
    except Exception as e:
        return done('STOP', 'the bag or the move / form tables cannot be read, so nothing can be judged (%s: %s) -- restore the '
                            'file it names from the data store (python tools/pogo_data.py pull) and run again' % (type(e).__name__, e))
    if len(rows) < min_rows:
        return done('STOP', 'only %d in-bag rows to judge (need %d): pokemon.db is missing, empty or not pulled -- "no rows" '
                            'must never read as "no flips"' % (len(rows), min_rows))
    with tempfile.TemporaryDirectory(prefix='gm_guard_') as work:
        try:
            nv = View(new_gm, new_path, 'new', work, move_map)
        except Exception as e:                                  # the engine's own loaders are the parse test
            return done('UNREADABLE_NEW', 'the engine cannot load the candidate (%s: %s)' % (type(e).__name__, e))
        try:
            ov = View(old_gm, old_path, 'old', work, move_map)
        except Exception as e:
            return done('STOP', 'the engine cannot load the INSTALLED client game master (%s: %s)' % (type(e).__name__, e))
        try:
            res['diff'] = diff_gm(old_gm, new_gm)
        except Exception as e:                                  # informational only: the impact below decides
            res['diff'] = OrderedDict([('digest unavailable', ['%s: %s' % (type(e).__name__, e)])])
        axes = defaultdict(set)
        for r in rows:
            try:
                fl = compare_row(row_verdict(ov, r, enum), row_verdict(nv, r, enum))
            except Exception:
                res['nulled'].append(r['uid_hex'])              # cannot be judged -> counted, listed, STOPs
                continue
            for ax, what, a, b, d in fl:
                axes[ax].add(r['uid_hex'])
                res['flips'].append({'uid': r['uid_hex'], 'species': r['species_name'], 'axis': ax, 'what': what,
                                     'old': a, 'new': b, 'dir': d})
        res['axes'] = {k: len(v) for k, v in sorted(axes.items())}
    if res['flips'] or res['nulled']:
        n = len({f['uid'] for f in res['flips']} | set(res['nulled']))
        return done('FLIPS', '%d in-bag row(s) flip a keep verdict (%s)%s' % (
            n, ', '.join('%s %d' % kv for kv in res['axes'].items()) or 'none judged',
            ('; %d could not be judged' % len(res['nulled'])) if res['nulled'] else ''))
    return done('CLEAR', 'no in-bag verdict moves')


def review_lines(res, old_meta, new_meta_, bak, with_digest=True, max_lines=200):
    """The record's `lines` (review_gate prints the first 40): the reason, how to reverse, the flipped rows (LOST first),
    then -- when with_digest -- what changed in the file."""
    def ident(m):
        return '%s%s' % (m.get('batch_utc', '?')[:10] if m else 'unstamped', (' APK %s' % m['apk']) if m and m.get('apk') else '')
    L = ['CLIENT GAME MASTER %s -> %s: %s' % (ident(old_meta), ident(new_meta_), res['reason'])]
    if bak:
        L.append('to REVERSE (in pogo_extract): copy %s over gamemaster_pokeminers.json, %s, and delete the review record'
                 % (os.path.basename(bak), 'its .meta.bak-* over the .meta' if old_meta else 'delete the .meta (none was there before)'))
        if old_meta and old_meta.get('folder'):
            L.append('(no backup any more, e.g. a new VM? the old batch is public: raw.githubusercontent.com/PokeMiners/game_masters/'
                     'master/previous_game_masters/%s/game_master.json, sha256 %s)' % (old_meta['folder'], str(old_meta.get('sha256'))[:16]))
    grouped = OrderedDict()
    order = {'LOST': 0, 'CHANGED': 1, 'GAINED': 2}
    for f in sorted(res['flips'], key=lambda f: (order.get(f['dir'], 1), f['axis'], f['species'], f['what'])):
        k = (f['dir'], f['axis'], f['species'], f['what'], f['old'], f['new'])
        grouped[k] = grouped.get(k, 0) + 1
    for (d, ax, sp, what, a, b), n in grouped.items():
        L.append(('%-7s %-12s %s x%d: %s%s' % (d, ax, sp, n, what, (' | %s -> %s' % (a, b)) if a or b else ''))[:200])
    if res['nulled']:
        L.append('NULL    %d row(s) could not be judged (unknown = protected): %s' % (len(res['nulled']), ' '.join(res['nulled'][:8])))
    if with_digest:
        L.append('what changed in the file:')
        L += ['   ' + x for x in digest_lines(res['diff'])[:14]]
    return [x[:200] for x in L][:max_lines]


# --------------------------------------------------------------------------------------------------- the audit WARN
def freshness_findings(meta, game_version, now=None):
    """[(WARN, message, do)] for audit_invariants I2.7. [] = nothing to say. NEVER raises: a missing or broken meta is a
    finding, not a crash. Four independent causes, each with its own remedy:
      no stamp     the client GM was installed before gm_guard (or its .meta was lost): batch and APK unknown
      APK skew     the GM is for an older game than the phone runs (game_version.json is written by full_audit each cull)
      not checked  the GM has not been compared with PokeMiners' latest for MAX_VERIFY_AGE_DAYS: refresh is not running
      batch age    older than MAX_BATCH_AGE_DAYS (the longest quiet gap seen in 2026 was 133 days): upstream may be dead
      rejected     the newest upstream batch could not be loaded by the engine and was NOT installed (meta['rejected'])
    WARN, never BLOCK: the pile gate is the real gate; an older GM leaves what it does not know on protected defaults
    (detect_legacy keeps an unnamed move as legacy, costume_forms reads an unknown form as a costume; only a new form's
    evolvability falls back to the species graph); and a BLOCK could not be cleared while PokeMiners is quiet (0.427.0 is
    upstream's newest today, the phone runs 0.429.1)."""
    now = time.time() if now is None else now
    do = ('python system/scripts/refresh_gamemaster.py  (asks PokeMiners on every run; a new batch is installed only after '
          'it is diffed against the bag, and stops for review if a keep verdict moves)')
    out = []
    try:
        if not isinstance(meta, dict) or not isinstance(meta.get('batch_ts'), int):
            return [('WARN', 'gamemaster_pokeminers.json has no readable stamp (gamemaster_pokeminers.json.meta): its batch '
                             'and APK are unknown, so nothing can say whether it matches the game', do)]
        batch_age = (now - meta['batch_ts'] / 1000.0) / 86400.0
        ver_ts = max(meta.get('checked_ts') or 0, meta.get('downloaded_ts') or 0)
        ver_age = (now - ver_ts) / 86400.0 if ver_ts else None
        gv = (game_version or {}).get('version') if isinstance(game_version, dict) else None
        apk, gvt = apk_tuple(meta.get('apk')), apk_tuple(gv)
        newer = ''
        if ver_age is not None and ver_age <= MAX_VERIFY_AGE_DAYS:
            newer = (' PokeMiners had published nothing newer when last checked (%s UTC): a refresh would change nothing yet.'
                     % meta.get('checked_at', '?')) if meta.get('upstream_ts') == meta['batch_ts'] else \
                    ' PokeMiners has a NEWER batch (seen %s UTC).' % meta.get('checked_at', '?')
        if apk and gvt and apk < gvt:
            out.append(('WARN', 'the client game master is APK %s (batch %s UTC) but the phone runs %s: forms, moves and '
                                'evolutions added since are unknown to it (an unnamed move stays legacy, an unknown form stays a costume; '
                                'nothing new is judged).%s' % (meta['apk'], meta['batch_utc'][:10], gv, newer), do))
        if ver_age is None or ver_age > MAX_VERIFY_AGE_DAYS:
            out.append(('WARN', 'the client game master has not been compared with PokeMiners\' latest for %s (limit %d '
                                'days): a cull does this on every run, so no cull has finished a refresh since'
                        % ('ever' if ver_age is None else '%.0f days' % ver_age, MAX_VERIFY_AGE_DAYS), do))
        rj = meta.get('rejected')
        if isinstance(rj, dict):
            out.append(('WARN', 'the newest PokeMiners batch (%s UTC) was REJECTED at %s UTC and is NOT installed -- %s; the client '
                                'game master is still batch %s UTC. Every refresh retries it; a real fix is in the loaders '
                                '(evolvable_forms / gm_guard)' % (rj.get('batch_utc', '?'), rj.get('at', '?'), str(rj.get('reason', '?'))[:200],
                                                                  meta['batch_utc']), do))
        if batch_age > MAX_BATCH_AGE_DAYS:
            out.append(('WARN', 'the client game master batch is %.0f days old (%s UTC; limit %d): PokeMiners may have '
                                'stopped publishing -- read the game\'s own data live instead' % (
                                    batch_age, meta['batch_utc'][:10], MAX_BATCH_AGE_DAYS), do))
    except Exception as e:                                       # a WARN check must never take the audit down
        out.append(('WARN', 'the client game master stamp could not be judged (%s: %s)' % (type(e).__name__, e), do))
    return out


# ----------------------------------------------------------------------------------------------------------- self-test
def _T(dex, key, **ps):
    ps.setdefault('pokemonId', key.split('_')[0])
    return {'templateId': 'V%04d_POKEMON_%s' % (dex, key), 'data': {'pokemonSettings': ps}}


def _X(dex, key, xxl):
    """An EXTENDED_V####_POKEMON_<KEY> template: the size bands size_line reads the XXL upper bound from."""
    return {'templateId': 'EXTENDED_V%04d_POKEMON_%s' % (dex, key), 'data': {'pokemonExtendedSettings': {
        'uniqueId': key.split('_')[0], 'sizeSettings': {'xxsLowerBound': 0.5, 'xsLowerBound': 0.6, 'mLowerBound': 0.8, 'mUpperBound': 1.0,
                                                        'xlUpperBound': 1.2, 'xxlUpperBound': xxl}}}}


_MOVES = {'1': 'TACKLE_FAST', '2': 'DIG', '3': 'SWIFT', '4': 'WATER_GUN_FAST', '5': 'AQUA_TAIL'}


def _fixture_gm(variant=None):
    """A tiny synthetic client game master in the real one's shape; `variant` moves exactly ONE fact."""
    ev = [{'evolution': 'GOLDUCK', 'candyCost': 50, 'form': 'GOLDUCK_NORMAL'}]
    num = lambda h, w: dict(pokedexHeightM=h, pokedexWeightKg=w, heightStdDev=round(h / 8, 3), weightStdDev=round(w / 8, 3), type='POKEMON_TYPE_WATER')
    psy = dict(pokemonId='PSYDUCK', familyId='FAMILY_PSYDUCK', quickMoves=['WATER_GUN_FAST'], cinematicMoves=['AQUA_TAIL'], **num(0.8, 19.6))
    gold = dict(pokemonId='GOLDUCK', familyId='FAMILY_PSYDUCK', **num(1.7, 76.6))
    eev = dict(pokemonId='EEVEE', familyId='FAMILY_EEVEE', quickMoves=['TACKLE_FAST'], cinematicMoves=['DIG'])
    mew, bul, cha = {}, {'isTransferable': True}, {'isTradable': True}   # the real game master prints these flags only when true
    fill = dict(pokemonId='FILLER', familyId='FAMILY_FILLER', quickMoves=['TACKLE_FAST'], cinematicMoves=['DIG'], **num(1.0, 10.0))
    chain_cost, top_form, top_h = 50, 'TOPX_NORMAL', 1.6
    xpsy, xgold, sx_h, sz_h, fy_h, nx_h = 1.4, 2.975, 1.5, 1.0, 1.6, 1.8
    sz_ev = [{'evolution': 'SIZERX', 'candyCost': 25, 'form': 'SIZERX_ALOLA'}]
    if variant == 'chain_cost':        # a stage FURTHER DOWN the BABYX -> MIDX -> TOPX line: the held BABYX must flip too
        chain_cost = 100
    if variant == 'chain_form':        # the form the MIDX -> TOPX branch lands in: from BABYX only the two-hop form walk sees it
        top_form = 'TOPX_ALT'
    if variant == 'evo_cost':
        ev = [{'evolution': 'GOLDUCK', 'candyCost': 100, 'form': 'GOLDUCK_NORMAL'}]
    if variant == 'evo_gone':
        ev = []
    if variant == 'move':
        eev['cinematicMoves'] = ['DIG', 'SWIFT']
    if variant == 'rarity':
        mew['pokemonClass'] = 'POKEMON_CLASS_MYTHIC'
    if variant == 'transferable':
        del bul['isTransferable']      # absent = false: the game master never prints a literal false (2026-09-30)
    if variant == 'tradable':
        del cha['isTradable']
    if variant == 'unbagged':
        fill['quickMoves'] = ['TACKLE_FAST', 'DIG']
    if variant == 'nontm':             # SWIFT enters the any-form pool (nonTmCinematicMoves) WITHOUT becoming a plain-TM move: only the pool answer flips
        eev['nonTmCinematicMoves'] = ['SWIFT']
    if variant == 'size':              # the held species' OWN height
        psy['pokedexHeightM'] = 0.5
    if variant == 'size_later':        # a LATER stage of the held Psyduck: best_points projects the copy onto Golduck's numbers
        gold['pokedexWeightKg'] = 50.0
    if variant == 'size_ext':          # that later stage's EXTENDED_ XXL upper bound (the n its points divide by)
        xgold = 3.4
    if variant == 'size_ext_own':      # the held species' own EXTENDED_ bound
        xpsy = 1.9
    if variant == 'type':              # a later stage's type (the xxl_per_type trim scores a copy once per type)
        gold['type2'] = 'POKEMON_TYPE_PSYCHIC'
    if variant == 'type_own':
        psy['type2'] = 'POKEMON_TYPE_PSYCHIC'
    if variant == 'size_chain':        # TWO stages down the BABYX -> MIDX -> TOPX line: only the held BABYX / MIDX rows look that far
        top_h = 2.4
    if variant == 'size_regional':     # a regional TARGET form's own template (SIZERX_ALOLA); the species-level SIZERX does not move
        sx_h = 2.5
    if variant == 'size_unheld':       # a species nobody holds or evolves from / into: in the digest, no stop
        fill['pokedexHeightM'] = 9.9
    if variant == 'size_free':         # a stage only the FORM-level walk reaches (its branch has no candy cost and no item)
        fy_h = 2.0
    if variant == 'size_noform':       # a stage only the SPECIES-level chain reaches (a species whose templates carry no form)
        nx_h = 3.0
    if variant == 'regional_gate':     # a gate on a REGIONAL branch: evolvable_forms keys it by the form only ('sizerx_alola'), never 'sizerx'
        sz_ev[0]['mustBeBuddy'] = True
    if variant == 'size_shape':        # a shape size_line cannot load (sizeSettings is a list) though evolvable_forms can: still an unreadable file
        fill['sizeSettings'] = ['x']
    forms = [{'form': 'FILLER_PLAIN'}, {'form': 'FILLER_HAT', 'isCostume': False}]
    if variant == 'digest':            # every digest-only field, all on the species nobody holds (proves each label is computed)
        fill.update(tempEvoOverrides=[{'tempEvoId': 'TEMPORARY_EVOLUTION_MEGA'}], shadow={'purificationStardustNeeded': 1000},
                    stats={'baseAttack': 100}, isDeployable=False, allowNoevolveEvolution=['FILLER_HAT'], pokemonClass='POKEMON_CLASS_MYTHIC')
        forms = [{'form': 'FILLER_HAT', 'isCostume': True}, {'form': 'FILLER_NEW', 'isCostume': True}]
    gm = [_T(54, 'PSYDUCK', evolutionBranch=ev, **psy), _T(54, 'PSYDUCK_NORMAL', form='PSYDUCK_NORMAL', evolutionBranch=ev, **psy),
          _T(55, 'GOLDUCK', **gold), _T(133, 'EEVEE', **eev),
          _T(150, 'MEWTWO', pokemonId='MEWTWO', **mew), _T(1, 'BULBASAUR', pokemonId='BULBASAUR', **bul),
          _T(4, 'CHARMANDER', pokemonId='CHARMANDER', **cha), _T(999, 'FILLER', **fill)]
    for dex, key, nxt, cost, nform in ((996, 'BABYX', 'MIDX', 25, 'MIDX_NORMAL'), (995, 'MIDX', 'TOPX', chain_cost, top_form)):    # a 3-stage line, form templates like the real ones
        br = [{'evolution': nxt, 'candyCost': cost, 'form': nform}]
        if variant == 'gate' and key == 'BABYX':                # a plain gate: gate_reason changes, no item, no cost, no gate detail
            br[0]['mustBeBuddy'] = True
        gm += [_T(dex, key, familyId='FAMILY_BABYX', evolutionBranch=br, **num(0.3 if key == 'BABYX' else 0.6, 3.0)),
               _T(dex, key + '_NORMAL', form=key + '_NORMAL', pokemonId=key, familyId='FAMILY_BABYX', evolutionBranch=br,
                  **num(0.3 if key == 'BABYX' else 0.6, 3.0))]
    gm.append(_T(994, 'TOPX', familyId='FAMILY_BABYX', **num(top_h, 30.0)))
    # the size fixtures: EXTENDED_ bounds for Psyduck / Golduck; SIZER (held, in form UnownA) evolves into SIZERX's ALOLA form; FREEX
    # -> FREEY has no candy cost and no item (only the form-level walk reaches FREEY); NOFORM -> NOFORMX sits on a template with no
    # form (only the species-level chain reaches NOFORMX); a FORMS_ template and a GONER template for the digest labels
    free = [{'evolution': 'FREEY', 'form': 'FREEY_NORMAL'}]
    gm += [_X(54, 'PSYDUCK', xpsy), _X(55, 'GOLDUCK', xgold),
           _T(993, 'SIZER', familyId='FAMILY_SIZER', evolutionBranch=sz_ev, **num(sz_h, 10.0)),
           _T(993, 'SIZER_NORMAL', form='SIZER_NORMAL', pokemonId='SIZER', familyId='FAMILY_SIZER', evolutionBranch=sz_ev, **num(sz_h, 10.0)),
           _T(992, 'SIZERX', familyId='FAMILY_SIZER', **num(1.5, 15.0)),
           _T(992, 'SIZERX_ALOLA', form='SIZERX_ALOLA', pokemonId='SIZERX', familyId='FAMILY_SIZER', **num(sx_h, 15.0)),
           _T(988, 'FREEX', familyId='FAMILY_FREEX', evolutionBranch=free, **num(1.0, 10.0)),
           _T(988, 'FREEX_NORMAL', form='FREEX_NORMAL', pokemonId='FREEX', familyId='FAMILY_FREEX', evolutionBranch=free, **num(1.0, 10.0)),
           _T(987, 'FREEY', familyId='FAMILY_FREEX', **num(fy_h, 20.0)),
           _T(986, 'NOFORM', familyId='FAMILY_NOFORM', evolutionBranch=[{'evolution': 'NOFORMX', 'candyCost': 25}], **num(1.0, 10.0)),
           _T(985, 'NOFORMX', familyId='FAMILY_NOFORM', **num(nx_h, 20.0)),
           {'templateId': 'FORMS_V0999_POKEMON_FILLER', 'data': {'formSettings': {'pokemon': 'FILLER', 'forms': forms}}}]
    if variant != 'digest':
        gm.append(_T(990, 'GONER', familyId='FAMILY_GONER'))
    if variant in ('form_new', 'form_new_diff'):   # a template APPEARS for the form the held Sizer is in (UnownA): the same numbers as the
        gm.append(_T(993, 'SIZER_UNOWN_A', form='UNOWN_A', pokemonId='SIZER', familyId='FAMILY_SIZER',    # species it fell back to, or not
                     **num(2.0 if variant == 'form_new_diff' else sz_h, 10.0)))
    if variant == 'pre':               # a NEW non-baby species that evolves INTO the held Psyduck: Psyduck becomes a middle stage
        gm.append(_T(997, 'FAKEPRE', familyId='FAMILY_PSYDUCK', evolutionBranch=[{'evolution': 'PSYDUCK', 'candyCost': 25, 'form': 'PSYDUCK_NORMAL'}]))
    if variant == 'unbagged':
        gm.append(_T(998, 'NEWFILLER', pokemonId='NEWFILLER', familyId='FAMILY_NEWFILLER'))
    if variant == 'newmon':            # a species that had NO pool gets one: the held Ghost's SWIFT goes from 'unknown pool' to 'no normal roll'
        gm.append(_T(991, 'GHOST', familyId='FAMILY_GHOST', quickMoves=['TACKLE_FAST'], cinematicMoves=['DIG']))
    if variant == 'int_form':          # the real 0.395.1 shape: an INTEGER branch form on a gated branch crashes evolvable_forms
        gm[1]['data']['pokemonSettings']['evolutionBranch'] = [{'evolution': 'GOLDUCK', 'candyCost': 50, 'form': 3290,
                                                                'questDisplay': [{'questRequirementTemplateId': 'Q'}]}]
    return gm


def selftest(rgm=None):
    """Offline proof, synthetic fixtures, a private temp dir -- nothing outside it is written (the live files' stat is
    compared before and after). Run: python system/scripts/refresh_gamemaster.py --selftest"""
    n = [0]

    def ok(cond, msg):
        assert cond, 'gm_guard selftest FAILED: ' + msg
        n[0] += 1
    live = [p for p in (getattr(rgm, 'PM', None), getattr(rgm, 'PM_META', None), getattr(rgm, 'REVIEW', None),
                        getattr(rgm, 'GM', None), os.path.join(ROOT, 'system', 'analysis', 'evolvable_forms.json')) if p]
    stat0 = {p: (os.stat(p).st_size, os.stat(p).st_mtime_ns) if os.path.exists(p) else None for p in live}
    enum = {int(k): v for k, v in json.load(open(os.path.join(ROOT, 'form_enum.json'), encoding='utf-8')).items()}
    psy = next(k for k, v in enum.items() if _norm(v) == 'PSYDUCKNORMAL')
    base = dict(form=0, fresh_form=0, fresh_costume=0, move1=0, move2=0, move3=0)
    rows = [dict(base, uid_hex='u_psy', species_name='Psyduck', pokemon_id=54, form=psy, fresh_form=psy, move1=4, move2=5),
            dict(base, uid_hex='u_eev_swift', species_name='Eevee', pokemon_id=133, move1=1, move2=3),
            dict(base, uid_hex='u_eev_plain', species_name='Eevee', pokemon_id=133, move1=1, move2=2),
            dict(base, uid_hex='u_mew', species_name='Mewtwo', pokemon_id=150),
            dict(base, uid_hex='u_baby', species_name='Babyx', pokemon_id=996), dict(base, uid_hex='u_mid', species_name='Midx', pokemon_id=995),
            dict(base, uid_hex='u_bul', species_name='Bulbasaur', pokemon_id=1),
            dict(base, uid_hex='u_cha', species_name='Charmander', pokemon_id=4),
            dict(base, uid_hex='u_sizer', species_name='Sizer', pokemon_id=993, form=1, fresh_form=1),    # in form UnownA: its own template appears in a variant
            dict(base, uid_hex='u_ghost', species_name='Ghost', pokemon_id=991, move1=3),                 # a species the game master has no pool for yet
            dict(base, uid_hex='u_free', species_name='Freex', pokemon_id=988),                           # its evolution has no candy cost / item
            dict(base, uid_hex='u_noform', species_name='Noform', pokemon_id=986)]                        # its templates carry no form
    saved = (MIN_POKEMON_SETTINGS, MIN_BAG_ROWS)
    globals()['MIN_POKEMON_SETTINGS'], globals()['MIN_BAG_ROWS'] = 3, 5
    try:
        with tempfile.TemporaryDirectory(prefix='gm_guard_selftest_') as td:
            def put(name, obj):
                p = os.path.join(td, name)
                with open(p, 'w', encoding='utf-8') as f:
                    f.write(obj if isinstance(obj, str) else json.dumps(obj))
                return p
            A = put('old.json', _fixture_gm())
            A2 = put('old_reserialized.json', json.dumps(list(reversed(_fixture_gm())), indent=2, sort_keys=True))
            same = lambda o, nw, **k: assess(o, nw, k.pop('rows', rows), _MOVES, enum, **k)
            # 1. IDENTICAL input never stops -- byte-identical, and the same content written differently
            r = same(A, A)
            ok(r['verdict'] == 'SAME' and not r['flips'], 'identical bytes must be SAME, got %s' % r['verdict'])
            r = same(A, A2)
            ok(r['verdict'] == 'CLEAR' and not r['flips'] and not r['nulled'] and not r['diff'],
               're-serialised identical content must be CLEAR with an empty diff, got %s %s' % (r['verdict'], dict(r['diff'])))
            # 2. every axis flips exactly the row that holds it, and nothing else; a change nobody holds does not stop. Each variant
            #    also names the digest label that must say what moved (spec (b): every field of the digest is computed, not assumed)
            xl = 'extended sizeSettings (XXL bound, size bands) changed'
            want = {'move': ('moves', 'u_eev_swift', 'LOST', 'cinematicMoves changed'),
                    'evo_cost': ('evolve', 'u_psy', 'CHANGED', 'evolutionBranch changed'),
                    'evo_gone': ('evolve', 'u_psy', 'CHANGED', 'evolutionBranch changed'),
                    'regional_gate': ('evolve', 'u_sizer', 'CHANGED', 'evolutionBranch changed'),
                    'tradable': ('tradable', 'u_cha', 'CHANGED', 'isTradable changed'),
                    'transferable': ('transferable', 'u_bul', 'CHANGED', 'isTransferable changed'),
                    'rarity': ('rarity', 'u_mew', 'GAINED', 'pokemonClass changed'),
                    # the SIZE axis (2026-09-30, review): the numbers size_line scores an XXL copy by, each from its own source --
                    # the held species' own template, a LATER stage's template (best_points projects the copy onto it), the
                    # EXTENDED_ XXL upper bound of either, the types (the xxl_per_type trim), a regional target form's own template
                    'size': ('size', 'u_psy', 'CHANGED', 'size numbers changed'),
                    'size_later': ('size', 'u_psy', 'CHANGED', 'size numbers changed'),
                    'size_ext': ('size', 'u_psy', 'CHANGED', xl), 'size_ext_own': ('size', 'u_psy', 'CHANGED', xl),
                    'type': ('size', 'u_psy', 'CHANGED', 'type2 changed'), 'type_own': ('size', 'u_psy', 'CHANGED', 'type2 changed'),
                    'size_regional': ('size', 'u_sizer', 'CHANGED', 'size numbers changed'),
                    # the two ways a later stage is found (evo_facts walks both, and they differ on the real bag): the form-level hops
                    # see a branch with no candy cost, the species-level chain sees a species whose templates carry no form
                    'size_free': ('size', 'u_free', 'CHANGED', 'size numbers changed'),
                    'size_noform': ('size', 'u_noform', 'CHANGED', 'size numbers changed')}
            for var, (axis, uid, d, label) in want.items():
                r = same(A, put('new_%s.json' % var, _fixture_gm(var)))
                fl = [(f['axis'], f['uid'], f['dir']) for f in r['flips']]
                ok(r['verdict'] == 'FLIPS' and fl == [(axis, uid, d)] and r['axes'] == {axis: 1},
                   '%s: want FLIPS %s got %s %s' % (var, (axis, uid, d), r['verdict'], fl))
                ok(label in r['diff'], '%s: the digest must say "%s", got %s' % (var, label, list(r['diff'])))
                gm_lines = review_lines(r, None, None, 'bak')
                ok(bool(gm_lines) and gm_lines[0].startswith('CLIENT GAME MASTER'), 'record lines')
            r = same(A, put('new_regional_gate.json', _fixture_gm('regional_gate')))
            ok('form gates' in r['flips'][0]['what'] and 'sizerx_alola' in r['flips'][0]['what'],
               'a gate on a regional branch is named in the flip: %s' % r['flips'][0]['what'])
            r = same(A, put('new_size.json', _fixture_gm('size')))
            rl = review_lines(r, None, None, 'bak')
            ok('size / types:' in ' '.join(rl), 'a size flip is named in the review record')
            ok('delete the .meta' in rl[1] and '.meta.bak-' not in rl[1],
               'the REVERSE line must not send anyone to a .meta backup that was never made (the baseline had no stamp): %s' % rl[1])
            rl = review_lines(r, {'batch_utc': '2026-08-28 07:35:50', 'apk': None, 'sha256': 'ab'}, None, 'bak')
            ok('.meta.bak-' in rl[1], 'with a stamped baseline the REVERSE line names its .meta backup: %s' % rl[1])
            # 2a. the game's TWO pool functions, one at a time (spec (c): detect_legacy's _game_master_pools AND _game_master_rollable;
            #     the 'move' variant flips both at once, so it cannot tell either from a neutered View): a move that enters the any-form
            #     pool without becoming a plain-TM move flips ONLY the pool answer; a move already in the pool that becomes plain-TM
            #     flips ONLY the plain-TM bit (it lifts the stale-elite protection). The reverse direction is GAINED.
            r = same(A, put('new_nontm.json', _fixture_gm('nontm')))
            fl = [(f['axis'], f['uid'], f['old'], f['new']) for f in r['flips']]
            ok(r['verdict'] == 'FLIPS' and fl == [('moves', 'u_eev_swift', 'no normal roll', 'normal roll')],
               'the pool answer alone (_game_master_pools) must flip a held move: %s %s' % (r['verdict'], fl))
            ok('nonTmCinematicMoves changed' in r['diff'], 'the digest names the nonTm move pool')
            r = same(put('old_nontm.json', _fixture_gm('nontm')), put('new_move3.json', _fixture_gm('move')))
            fl = [(f['axis'], f['uid'], f['old'], f['new']) for f in r['flips']]
            ok(r['verdict'] == 'FLIPS' and fl == [('moves', 'u_eev_swift', 'normal roll', 'plain TM')],
               'the plain-TM bit alone (_game_master_rollable) must flip a held move: %s %s' % (r['verdict'], fl))
            r = same(put('old_move4.json', _fixture_gm('move')), A)
            fl = [(f['axis'], f['uid'], f['dir']) for f in r['flips']]
            ok(r['verdict'] == 'FLIPS' and fl == [('moves', 'u_eev_swift', 'GAINED')], 'a move LEAVING the pool is a GAINED protection: %s %s' % (r['verdict'], fl))
            #     a species the game master had NO pool for is 'not special' (detect_legacy: the pvpoke test stands alone then); the
            #     day it gets one, the held move can be 'no normal roll' (the evolve axis moves too: the species became known)
            r = same(A, put('new_newmon.json', _fixture_gm('newmon')))
            fl = [(f['axis'], f['uid'], f['old'], f['new']) for f in r['flips']]
            ok(('moves', 'u_ghost', 'normal roll', 'no normal roll') in fl and not [x for x in r['nulled']],
               'a species that gets its first pool must flip its held move (an unknown pool is not special): %s %s' % (r['verdict'], fl))
            # 2b. the whole evolution chain, not only a row's own branches: a stage FURTHER DOWN the line flips its held
            #     pre-evolution too (keep_policy._afford reads path_cost), and a new pre-evolution ABOVE a held species flips its
            #     middle-stage flag (costume_cap 3 -> 1) -- both were invisible to an own-branch-only verdict
            r = same(A, put('new_chain_cost.json', _fixture_gm('chain_cost')))
            fl = sorted((f['axis'], f['uid']) for f in r['flips'])
            ok(r['verdict'] == 'FLIPS' and fl == [('evolve', 'u_baby'), ('evolve', 'u_mid')] and r['axes'] == {'evolve': 2},
               'a cost change further down the line must flip the held pre-evolution too: %s %s' % (r['verdict'], fl))
            r = same(A, put('new_chain_form.json', _fixture_gm('chain_form')))
            fl = sorted((f['axis'], f['uid']) for f in r['flips'])
            ok(r['verdict'] == 'FLIPS' and fl == [('evolve', 'u_baby'), ('evolve', 'u_mid')],
               'the form a branch two stages down lands in must flip the held pre-evolution too: %s %s' % (r['verdict'], fl))
            r = same(A, put('new_gate.json', _fixture_gm('gate')))
            fl = sorted((f['axis'], f['uid']) for f in r['flips'])
            ok(r['verdict'] == 'FLIPS' and fl == [('evolve', 'u_baby')], 'a new gate on a branch (buddy-only) flips its held source: %s %s' % (r['verdict'], fl))
            r = same(A, put('new_pre.json', _fixture_gm('pre')))
            fl = [(f['axis'], f['uid'], f['what']) for f in r['flips']]
            ok(r['verdict'] == 'FLIPS' and len(fl) == 1 and fl[0][:2] == ('evolve', 'u_psy') and 'middle stage False -> True' in fl[0][2],
               'a new pre-evolution above a held species must flip its middle-stage flag (the costume cap): %s %s' % (r['verdict'], fl))
            r = same(A, put('new_unbagged.json', _fixture_gm('unbagged')))
            ok(r['verdict'] == 'CLEAR' and 'pokemon templates added' in r['diff'] and not r['flips'],
               'a change to species nobody holds is in the digest but does not stop: %s' % r['verdict'])
            ok(digest_lines(r['diff'])[0].lstrip().split()[0].isdigit(), 'digest lines start with a count')
            # 2c. SIZE, further: a number TWO stages down the line flips the held pre-evolutions (best_points walks every later stage);
            #     a number nobody holds or evolves to is in the digest but does not stop; a template that APPEARS for a form the bag
            #     holds is no size change when it carries the numbers the row already resolved to (the species it fell back to) and
            #     IS one when it does not (the evolve axis moves either way: None -> False is a real change for the engine)
            r = same(A, put('new_size_chain.json', _fixture_gm('size_chain')))
            fl = sorted((f['axis'], f['uid']) for f in r['flips'])
            ok(r['verdict'] == 'FLIPS' and fl == [('size', 'u_baby'), ('size', 'u_mid')] and r['axes'] == {'size': 2},
               'a number two stages down the line must flip the held pre-evolutions: %s %s' % (r['verdict'], fl))
            r = same(A, put('new_size_unheld.json', _fixture_gm('size_unheld')))
            ok(r['verdict'] == 'CLEAR' and 'size numbers changed' in r['diff'] and not r['flips'],
               'a size change on a species nobody holds or evolves to is in the digest but does not stop: %s' % r['verdict'])
            for var, axes in (('form_new', {'evolve'}), ('form_new_diff', {'evolve', 'size'})):
                r = same(A, put('new_%s.json' % var, _fixture_gm(var)))
                got = {f['axis'] for f in r['flips']}
                ok(r['verdict'] == 'FLIPS' and got == axes and {f['uid'] for f in r['flips']} == {'u_sizer'},
                   '%s: a form template appearing must flip %s on the Sizer only, got %s %s' % (var, sorted(axes), r['verdict'], sorted(got)))
            # 2d. every field of the digest is computed: all on species nobody holds, so the verdict stays CLEAR
            r = same(A, put('new_digest.json', _fixture_gm('digest')))
            labels = ['pokemon templates removed', 'allowNoevolveEvolution changed (costumes that may evolve)', 'pokemonClass changed',
                      'isDeployable changed', 'base stats changed', 'mega/primal (tempEvoOverrides) changed', 'shadow availability changed',
                      'form added (costume)', 'form removed', 'form isCostume flipped']
            ok(r['verdict'] == 'CLEAR' and not r['flips'] and all(x in r['diff'] for x in labels),
               'the digest must name every field that moved: %s missing from %s' % ([x for x in labels if x not in r['diff']], list(r['diff'])))
            # 3. FAIL CLOSED: an unreadable / truncated / implausible / engine-unloadable file is never a pass
            good = json.dumps(_fixture_gm('move'))
            bad = {'truncated': good[:len(good) // 2], 'not_a_list': '{"a": 1}', 'not_templates': '[1, 2, 3]',
                   'no_data': '[{"templateId": "X"}]', 'empty': '', 'not_utf8': b'\xff\xfe\x00'.decode('latin-1'),
                   'tiny': json.dumps(_fixture_gm()[:2]), 'shrunk': json.dumps(_fixture_gm()[:4]),
                   'int_form': json.dumps(_fixture_gm('int_form')), 'size_shape': json.dumps(_fixture_gm('size_shape'))}
            for nm, txt in bad.items():
                p = put('bad_%s.json' % nm, txt)
                r = same(A, p)
                ok(r['verdict'] == 'UNREADABLE_NEW' and not r['flips'], 'candidate %s must be UNREADABLE_NEW, got %s (%s)' % (nm, r['verdict'], r['reason']))
                if nm != 'shrunk':                       # a smaller-but-whole file is a fine INSTALLED one
                    r = same(p, A)
                    ok(r['verdict'] == 'STOP', 'an unreadable INSTALLED file (%s) must STOP, got %s' % (nm, r['verdict']))
            r = same(A, put('missing.json', '')[:-len('missing.json')] + 'no_such_file.json')
            ok(r['verdict'] == 'UNREADABLE_NEW', 'a missing candidate is UNREADABLE_NEW')
            r = same(os.path.join(td, 'no_such_file.json'), A)
            ok(r['verdict'] == 'STOP' and 'no_such_file.json' in r['reason'] and 'restore' in r['reason'],
               'a missing installed file must STOP, name the file and say how to restore it: %s' % r['reason'])
            r = same(A, put('new_move2.json', _fixture_gm('move')), rows=[])
            ok(r['verdict'] == 'STOP' and 'no flips' in r['reason'], 'an EMPTY bag must STOP, never read as "no flips": %s' % r['verdict'])
            bad_row = dict((k, v) for k, v in rows[1].items() if k != 'move1')                                  # complete but for move1
            r = same(A, A2, rows=rows + [dict(bad_row, uid_hex='u_bad'), {'uid_hex': 'u_bad2', 'species_name': 'X', 'pokemon_id': 54}])
            ok(r['verdict'] == 'FLIPS' and r['nulled'] == ['u_bad', 'u_bad2'], 'a row that cannot be judged must STOP, got %s %s' % (r['verdict'], r['nulled']))
            # 4. the stamp: APK from the folder name, the batch match, the timestamp, the meta file
            ok(parse_apk('gm_v2_apk4270_2026.08.28-17.35.50') == '0.427.0' and parse_apk('gm_v2_apk3951_x') == '0.395.1'
               and parse_apk('nonsense') is None, 'parse_apk')
            ts = 1787902550208                                                    # 2026-08-28 07:35:50 UTC, the real batch
            tree = {'truncated': False, 'tree': [{'path': 'previous_game_masters/gm_v2_apk4270_2026.08.28-17.35.50', 'type': 'tree'},
                                                 {'path': 'previous_game_masters/gm_v2_apk4270_2026.08.28-17.35.50/game_master.json', 'type': 'blob'},
                                                 {'path': 'previous_game_masters/gm_v2_apk4070_2026.04.17-10.48.50', 'type': 'tree'}]}
            ok(apk_from_tree(tree, ts) == ('0.427.0', 'gm_v2_apk4270_2026.08.28-17.35.50'), 'apk_from_tree +10:00')
            t11 = {'truncated': False, 'tree': [{'path': 'previous_game_masters/gm_v2_apk4270_2026.08.28-18.35.50', 'type': 'tree'}]}
            ok(apk_from_tree(t11, ts)[0] == '0.427.0', 'apk_from_tree +11:00 (an Australian summer)')
            ok(apk_from_tree(dict(tree, truncated=True), ts) == (None, None), 'a truncated tree must give no apk')
            ok(apk_from_tree({'tree': tree['tree']}, ts) == (None, None), 'a tree that does not say truncated:false must give no apk')
            ok(apk_from_tree(tree, ts + 60000) == (None, None) and apk_from_tree('junk', ts) == (None, None), 'no nearest-folder guess')
            ok(parse_ts(b'1787902550208\n') == ts, 'parse_ts')
            for junk in ('', 'abc', '12', '99999999999999'):
                try:
                    parse_ts(junk)
                    ok(False, 'parse_ts must refuse %r' % junk)
                except ValueError:
                    ok(True, 'parse_ts refuses junk')
            mp = os.path.join(td, 'x.meta')
            ok(read_meta(mp) is None and write_meta(mp, new_meta(ts, 'ab' * 32, '0.427.0', 'f', 1787990000, False)) and
               read_meta(mp)['apk'] == '0.427.0' and read_meta(mp)['batch_utc'] == '2026-08-28 07:35:50', 'meta round trip')
            put('x.meta', '{"batch_ts": "x"}')
            ok(read_meta(mp) is None, 'a meta of the wrong shape is unreadable, not a crash')
            ok(open(mp, 'rb').read().isascii() and open(__file__, 'rb').read().isascii(), 'ASCII only (the repo guards cp1252)')
            # 5. the audit WARN (I2.7): every cause on its own, never a crash
            now = ts / 1000.0 + 33 * 86400
            m = dict(new_meta(ts, 'a', '0.427.0', 'f', now - 3600, False), checked_ts=int(now - 3600), checked_at='2026-09-30 06:00:00')
            gv = {'version': '0.429.1'}
            ok(len(freshness_findings(None, gv, now)) == 1 and 'no readable stamp' in freshness_findings(None, gv, now)[0][1], 'no stamp')
            ok(len(freshness_findings({'batch_ts': 'x'}, gv, now)) == 1, 'garbage stamp')
            f = freshness_findings(m, gv, now)
            ok(len(f) == 1 and 'phone runs 0.429.1' in f[0][1] and 'nothing newer' in f[0][1] and 'refresh_gamemaster.py' in f[0][2], 'APK skew: %s' % f)
            ok(freshness_findings(m, {'version': '0.427.0'}, now) == [] and freshness_findings(m, None, now) == [], 'no skew, or no game version')
            ok(freshness_findings(dict(m, apk=None), gv, now) == [], 'apk unknown (lookup blocked) and freshly checked: no noise')
            f = freshness_findings(dict(m, checked_ts=int(now - 20 * 86400), downloaded_ts=int(now - 20 * 86400)), {'version': '0.427.0'}, now)
            ok(len(f) == 1 and 'not been compared' in f[0][1], 'not checked for 20 days: %s' % f)
            f = freshness_findings(dict(m, batch_ts=int((now - 200 * 86400) * 1000), batch_utc='2026-03-13 00:00:00'), {'version': '0.427.0'}, now)
            ok(len(f) == 1 and 'stopped publishing' in f[0][1], 'batch older than 150 days: %s' % f)
            f = freshness_findings(dict(m, rejected={'batch_utc': '2026-09-29 00:00:00', 'at': '2026-09-30 06:00:00', 'reason': 'boom'}), {'version': '0.427.0'}, now)
            ok(len(f) == 1 and 'REJECTED' in f[0][1] and 'boom' in f[0][1], 'a rejected batch is named: %s' % f)
            # 6. the orchestrator, end to end in the temp dir (needs refresh_gamemaster; --selftest passes it in)
            if rgm is not None:
                _orchestrator_tests(rgm, td, put, rows, enum, ok)
            # 7. the real files, only where they exist (skipped cleanly on CI / a fresh clone)
            _live_check(rows, ok)
    finally:
        globals()['MIN_POKEMON_SETTINGS'], globals()['MIN_BAG_ROWS'] = saved
    stat1 = {p: (os.stat(p).st_size, os.stat(p).st_mtime_ns) if os.path.exists(p) else None for p in live}
    ok(stat0 == stat1, 'the self-test touched a live file: %s' % [p for p in live if stat0[p] != stat1[p]])
    print('gm_guard selftest: OK (%d checks)' % n[0])
    return 0


def _orchestrator_tests(rgm, td, put, rows, enum, ok):
    ts_a, ts_b = 1787902550208, 1790000000000
    NOW = ts_b / 1000.0 + 3600
    tree = {'truncated': False, 'tree': [{'path': 'previous_game_masters/gm_v2_apk4010_%s' % time.strftime('%Y.%m.%d-%H.%M.%S', time.gmtime(ts_b / 1000.0 + 36000)), 'type': 'tree'}]}
    dbp = os.path.join(td, 'pokemon.db')
    con = sqlite3.connect(dbp)
    con.execute('CREATE TABLE pokemon (%s, in_bag)' % ROW_COLS)
    for r in rows:
        con.execute('INSERT INTO pokemon VALUES (?,?,?,?,?,?,?,?,?,1)', [r[k] for k in ROW_COLS.replace(' ', '').split(',')])
    con.commit()
    con.close()
    served = {'json': None, 'ts': str(ts_b), 'n_json': 0, 'ts_seq': None, 'no_tree': False}

    def fetch(url, timeout=30):
        if url.startswith(PM_TS_URL):
            if served['ts_seq']:
                return served['ts_seq'].pop(0).encode()
            if served['ts'] is None:
                raise OSError('offline')
            return served['ts'].encode()
        if url.startswith(PM_JSON_URL):
            served['n_json'] += 1
            return served['json'].encode()
        if url.startswith(PM_TREE_URL):
            if served['no_tree']:
                raise OSError('the tree API is refused')
            return json.dumps(tree).encode()
        raise OSError('unexpected url ' + url)
    saved = (rgm.REVIEW, rgm._pm_engine_inputs, rgm.PM, rgm.PM_META, rgm.GM, rgm.DB)
    rgm._pm_engine_inputs = lambda: (_MOVES, enum)

    def run(argv=(), review=None):
        rgm.REVIEW = review or os.path.join(td, 'review.json')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = rgm.pokeminers_phase(list(argv), fetch=fetch, now=NOW, gm_path=gmp, meta_path=mtp, db_path=dbp)
        return rc, buf.getvalue()

    def reset(gm_variant, with_meta=True, ts=ts_a):
        for p in (gmp, mtp, rgm.REVIEW):
            if os.path.exists(p):
                os.remove(p)
        for f in os.listdir(td):
            if '.bak-' in f or f.endswith('.download'):
                os.remove(os.path.join(td, f))
        put('gm.json', _fixture_gm(gm_variant))
        if with_meta:
            write_meta(mtp, new_meta(ts, sha256_file(gmp), '0.400.0', 'gm_v2_apk4000_x', NOW - 86400, False))
    gmp, mtp = os.path.join(td, 'gm.json'), os.path.join(td, 'gm.json.meta')
    try:
        # FLIPS: install + backup + meta + the SAME record; rc 2; review_gate reads it; --ack clears it exactly as for a rank crossing
        reset(None)
        old_bytes = open(gmp, 'rb').read()
        served['json'] = json.dumps(_fixture_gm('move'))
        rc, out = run()
        rec = json.load(open(rgm.REVIEW, encoding='utf-8'))
        baks = sorted(f for f in os.listdir(td) if f.startswith('gm.json.bak-'))
        ok(rc == (2, True), 'FLIPS must exit 2 with the tail owed, got %s' % (rc,))
        ok(rec['crossed'] == ['u_eev_swift'] and rec['nulled'] == [] and rec['kind'] == 'client_gm' and rec['target'] == 'pokeminers'
           and rec['lines'][0].startswith('CLIENT GAME MASTER') and rec['backup'] == baks[0] and 'status' not in rec,
           'the record has the rows the gate reads: %s' % {k: rec[k] for k in ('crossed', 'nulled', 'backup')})
        ok(open(os.path.join(td, baks[0]), 'rb').read() == old_bytes and sha256_file(gmp) == read_meta(mtp)['sha256'], 'backup = the old bytes; new file stamped')
        ok(read_meta(mtp)['batch_ts'] == ts_b and read_meta(mtp)['tail_pending'] is True and read_meta(mtp)['apk'] == '0.401.0', 'meta of the installed batch: %s' % read_meta(mtp))
        ok(not os.path.exists(gmp + '.download') and os.path.exists(mtp + '.bak-' + baks[0].split('.bak-', 1)[1]), 'no temp file left; the old stamp is backed up too')
        ok(json.dumps(rec).isascii() and 'pokeminers' in out and 'NEEDS A HUMAN' in out, 'ASCII record, the run says it needs a human')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            g = rgm.review_gate([])
            ok(g == 2 and 'REVIEW PENDING' in buf.getvalue() and 'CLIENT GAME MASTER' in buf.getvalue(), 'review_gate stops every run and prints the rows')
            ok(rgm.review_gate(['--ack']) == 0 and not os.path.exists(rgm.REVIEW), '--ack clears it exactly as today')
        ok(sha256_file(gmp) != sha256_file(os.path.join(td, baks[0])), '--ack does not roll a client-GM record back')
        # the batch is upstream's latest now: no second download, only the check time moves
        n0 = served['n_json']
        rc, out = run()
        ok(rc == (None, True) and served['n_json'] == n0 and 'nothing to download' in out, 'same batch: no re-download (%s)' % (rc,))
        # a second install the same day never overwrites the first backup
        served['ts'], served['json'] = str(ts_b + 5000), json.dumps(_fixture_gm('evo_cost'))
        rc, out = run(review=os.path.join(td, 'review2.json'))
        ok(len([f for f in os.listdir(td) if f.startswith('gm.json.bak-')]) == 2, 'a same-day second install gets its own backup')
        served['ts'] = str(ts_b)
        # an interrupted-refresh record that names the client GM rolls back the CLIENT file, never pvpoke's
        pv = os.path.join(td, 'pvpoke.json')
        put('pvpoke.json', '{"pokemon": []}')
        rgm.GM, rgm.PM = pv, gmp
        bak = os.path.join(td, 'gm.json.bak-rollback')
        put('gm.json.bak-rollback', _fixture_gm())
        with open(rgm.REVIEW, 'w', encoding='utf-8') as f:
            json.dump({'status': 'in progress', 'since': 'x', 'backup': 'gm.json.bak-rollback', 'target': 'pokeminers'}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok(rgm.review_gate(['--ack']) == 0, 'rollback --ack')
        ok(open(gmp, 'rb').read() == open(bak, 'rb').read() and open(pv).read() == '{"pokemon": []}', 'the rollback restored the client GM and left pvpoke alone')
        # CLEAR: a change nobody holds installs silently (backup + stamp, tail owed, no record)
        reset(None)
        served['ts'], served['json'] = str(ts_b), json.dumps(_fixture_gm('unbagged'))
        rc, out = run()
        ok(rc == (None, True) and not os.path.exists(rgm.REVIEW) and read_meta(mtp)['batch_ts'] == ts_b and sha256_file(gmp) == read_meta(mtp)['sha256'],
           'CLEAR installs without a stop: %s' % (rc,))
        # SAME: a file installed before the stamp existed is adopted, not re-diffed; no tail owed
        reset(None, with_meta=False)
        served['json'] = open(gmp, encoding='utf-8').read()
        rc, out = run()
        ok(rc == (None, False) and read_meta(mtp)['tail_pending'] is False and read_meta(mtp)['batch_ts'] == ts_b and not os.path.exists(rgm.REVIEW),
           'an unstamped file that IS upstream is adopted: %s' % (rc,))
        # the timestamp moved but the bytes did not (a stale CDN edge): not adopted, asked again next run
        reset(None)
        served['json'] = open(gmp, encoding='utf-8').read()
        before = open(mtp, 'rb').read()
        rc, out = run()
        ok(rc == (None, False) and open(mtp, 'rb').read() == before and 'NOT adopted' in out, 'ts moved, content same: kept, stamp untouched')
        # FAIL CLOSED / SOFT: a truncated download, an unreachable upstream, upstream moving mid-download -- nothing installed
        reset(None)
        served['json'] = json.dumps(_fixture_gm('move'))[:400]
        b0 = (open(gmp, 'rb').read(), os.stat(gmp).st_mtime_ns, open(mtp, 'rb').read())
        m0 = read_meta(mtp)
        rc, out = run()
        m1 = read_meta(mtp)
        ok(rc == (None, False) and (open(gmp, 'rb').read(), os.stat(gmp).st_mtime_ns) == b0[:2] and not os.path.exists(rgm.REVIEW)
           and not os.path.exists(gmp + '.download') and 'NOT installed' in out and 'WARN' in out, 'a truncated candidate is never installed: %s' % out[-160:])
        ok(m1.get('rejected', {}).get('batch_ts') == ts_b and all(m1[k] == m0[k] for k in ('batch_ts', 'sha256', 'apk', 'downloaded_ts')),
           'the rejection is remembered (for the offline WARN) and the stamp of what IS installed is untouched: %s' % m1.get('rejected'))
        served['json'] = open(gmp, encoding='utf-8').read()
        served['ts'] = str(ts_a)                                  # the batch is upstream's latest again: the rejection is stale
        rc, out = run()
        ok('rejected' not in read_meta(mtp), 'a good check clears a stale rejection')
        served['ts'] = str(ts_b)
        served['json'] = json.dumps(_fixture_gm('move'))[:400]
        served['ts'] = None
        rc, out = run()
        ok(rc == (None, False) and open(gmp, 'rb').read() == b0[0] and 'WARN' in out, 'upstream unreachable: WARN, nothing changes')
        served['ts'], served['ts_seq'], served['json'] = str(ts_b), [str(ts_b), str(ts_b + 1)], json.dumps(_fixture_gm('move'))
        rc, out = run()
        ok(rc == (None, False) and open(gmp, 'rb').read() == b0[0] and 'published while' in out, 'upstream moved mid-download: nothing installed')
        served['ts_seq'] = None
        # STOP: an empty bag (or an unreadable installed file) is never "no flips": nothing installed, the record is written
        con = sqlite3.connect(dbp)
        con.execute('UPDATE pokemon SET in_bag=0')
        con.commit()
        con.close()
        reset(None)
        served['json'] = json.dumps(_fixture_gm('move'))
        rc, out = run()
        rec = json.load(open(rgm.REVIEW, encoding='utf-8'))
        ok(rc == (2, False) and open(gmp, 'rb').read() == b0[0] and 'no flips' in rec['reason'] and rec['crossed'] == [], 'an empty bag STOPs, installs nothing: %s' % (rc,))
        # the record cannot be written -> not installed (never a silent install)
        con = sqlite3.connect(dbp)
        con.execute('UPDATE pokemon SET in_bag=1')
        con.commit()
        con.close()
        reset(None)
        rc, out = run(review=os.path.join(td, 'no_such_dir', 'review.json'))
        ok(rc == (1, False) and open(gmp, 'rb').read() == b0[0] and 'NOT installed' in out, 'FLIPS without a writable record must not install: %s' % (rc,))
        # --force on an unchanged, stamped file re-verifies it (identical bytes -> stamp refreshed, install time kept)
        reset(None)
        served['json'] = open(gmp, encoding='utf-8').read()
        served['ts'] = str(ts_a)
        d0 = read_meta(mtp)['downloaded_ts']
        rc, out = run(['--force'])
        ok(rc == (None, False) and read_meta(mtp)['downloaded_ts'] == d0 and read_meta(mtp)['checked_ts'] == int(NOW), '--force re-verifies without reinstalling')
        # ... and a KNOWN apk survives it while the tree API is refused (it is the same batch, so the same APK)
        reset(None)
        served['json'], served['no_tree'] = open(gmp, encoding='utf-8').read(), True
        rc, out = run(['--force'])
        served['no_tree'] = False
        ok(read_meta(mtp)['apk'] == '0.400.0' and read_meta(mtp)['folder'] == 'gm_v2_apk4000_x', 'a forced re-check must not erase a known APK: %s' % read_meta(mtp))
        # NEVER A DOWNGRADE: upstream's timestamp OLDER than the installed batch's (a stale edge / a rollback) installs nothing
        reset(None)
        served['ts'], served['json'] = str(ts_a - 100000), json.dumps(_fixture_gm('move'))
        b_old, n0 = open(gmp, 'rb').read(), served['n_json']
        rc, out = run()
        ok(rc == (None, False) and open(gmp, 'rb').read() == b_old and served['n_json'] == n0 and 'OLDER' in out and 'WARN' in out
           and not os.path.exists(rgm.REVIEW), 'an older upstream batch is never installed over a newer one: %s' % (rc,))
        served['ts'] = str(ts_b)
        # CRASH WINDOW: a new batch was installed but the process died before its stamp (the file is upstream's, the stamp is the
        # old batch's): it is adopted, and the reconcile + rank pass that install owed is owed AGAIN
        reset(None)
        put('gm.json', _fixture_gm('unbagged'))
        served['json'] = open(gmp, encoding='utf-8').read()
        rc, out = run()
        ok(rc == (None, True) and read_meta(mtp)['tail_pending'] is True and read_meta(mtp)['batch_ts'] == ts_b
           and sha256_file(gmp) == read_meta(mtp)['sha256'], 'a file its stamp does not describe is adopted AND owes its pass again: %s' % (rc,))
        # SWAPPED CANDIDATE: another refresh rewrites the download after it was judged -- the bytes that were judged are the only
        # ones that may be installed (a FLIPS record written for them is cleared again)
        real_assess = assess
        for judged, swapped in (('unbagged', 'move'), ('move', 'unbagged')):
            reset(None)
            served['json'] = json.dumps(_fixture_gm(judged))
            b_old = open(gmp, 'rb').read()

            def swapping(*a, **k):
                res = real_assess(*a, **k)
                with open(gmp + '.download', 'w', encoding='utf-8') as f:
                    f.write(json.dumps(_fixture_gm(swapped)))
                return res
            globals()['assess'] = swapping
            try:
                rc, out = run()
            finally:
                globals()['assess'] = real_assess
            ok(rc == (1, False) and open(gmp, 'rb').read() == b_old and not os.path.exists(rgm.REVIEW) and not os.path.exists(gmp + '.download')
               and 'NOT installed' in out and 'changed after it was judged' in out,
               'a candidate swapped after judging (judged %s, swapped %s) must not be installed: %s %s' % (judged, swapped, rc, out[-160:]))
        # main(): an unknown flag runs NOTHING (rc 2); a crash inside the guard is loud, non-fatal for full_audit, installs nothing
        called = []
        real_phase = rgm.pokeminers_phase
        rgm.pokeminers_phase = lambda argv, **k: called.append(argv) or (None, False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc_bad = rgm.main(['--help'])
        ok(rc_bad == 2 and not called and 'NOTHING was run' in buf.getvalue(), 'an unknown flag (even --help) must run nothing')
        def boom(argv, **k):
            raise RuntimeError('boom')
        rgm.pokeminers_phase = boom
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc_crash = rgm.main([])
        rgm.pokeminers_phase = real_phase
        ok(rc_crash == 1 and 'CRASHED' in buf.getvalue() and 'WARN' in buf.getvalue(), 'a crash in the guard is a loud rc 1, not a traceback or a pass')
        # THE OTHER ACCOUNT: the game master is one file for both trainers, so the RESTING account's parked bag is judged too (its
        # flips stop the pass and are named); the ACTIVE account's own parked copy is a stale duplicate and is skipped; a parked bag
        # that cannot be read is a STOP that installs nothing, never a pass
        import shutil
        adir = os.path.join(td, 'accounts')

        def park(name, uid, extra=0):
            os.makedirs(os.path.join(adir, name), exist_ok=True)
            c = sqlite3.connect(os.path.join(adir, name, 'pokemon.db'))
            c.execute('CREATE TABLE pokemon (%s, in_bag)' % ROW_COLS)
            for r in [dict(rows[1], uid_hex=uid)] + [dict(rows[2], uid_hex='%s_%d' % (uid, i)) for i in range(extra)]:
                # rows[1] is an Eevee holding Swift (the 'move' variant flips it); the extras hold a move that never flips
                c.execute('INSERT INTO pokemon VALUES (?,?,?,?,?,?,?,?,?,1)', [r[k] for k in ROW_COLS.replace(' ', '').split(',')])
            c.commit()
            c.close()
        put('active_account.txt', 'main')
        park('main', 'u_stale_swift')
        park('rest', 'u_rest_swift')
        reset(None)
        served['json'] = json.dumps(_fixture_gm('move'))
        rc, out = run()
        rec = json.load(open(rgm.REVIEW, encoding='utf-8'))
        ok(rc == (2, True) and rec['crossed'] == ['u_eev_swift', 'u_rest_swift'],
           'the resting account is judged, the active account\'s stale parked copy is not: %s %s' % (rc, rec['crossed']))
        ok(any('Eevee (rest)' in l for l in rec['lines']), 'a resting row is named with its account')
        with open(os.path.join(adir, 'rest', 'pokemon.db'), 'wb') as f:
            f.write(b'not a database')
        reset(None)
        b_old = open(gmp, 'rb').read()
        rc, out = run()
        rec = json.load(open(rgm.REVIEW, encoding='utf-8'))
        ok(rc == (2, False) and open(gmp, 'rb').read() == b_old and 'cannot be read' in rec['reason']
           and os.path.join('rest', 'pokemon.db') in rec['reason'] and 'pogo_data.py pull' in rec['reason'],
           'a parked bag that cannot be read is a STOP that installs nothing, names the file and the remedy: %s %s' % (rc, rec['reason'][:160]))
        with open(os.path.join(adir, 'rest', 'pokemon.db'), 'wb') as f:          # the accidental-sqlite3.connect class: an EMPTY file
            f.write(b'')
        reset(None)
        rc, out = run()
        rec = json.load(open(rgm.REVIEW, encoding='utf-8'))
        ok(rc == (2, False) and open(gmp, 'rb').read() == b_old and os.path.join('rest', 'pokemon.db') in rec['reason'] and 'no such table' in rec['reason'],
           'a stray empty parked pokemon.db is a STOP that names it: %s %s' % (rc, rec['reason'][:160]))
        os.remove(os.path.join(adir, 'rest', 'pokemon.db'))
        park('rest', 'u_rest_swift', extra=8)              # enough rows that only the ACTIVE bag's own count can stop the run
        c = sqlite3.connect(dbp)
        c.execute('UPDATE pokemon SET in_bag=0')
        c.commit()
        c.close()
        reset(None)
        rc, out = run()
        rec = json.load(open(rgm.REVIEW, encoding='utf-8'))
        ok(rc == (2, False) and 'no flips' in rec['reason'] and rec['crossed'] == [],
           'an empty ACTIVE bag is a STOP even when a resting account holds rows: %s %s' % (rc, rec['reason'][:100]))
        c = sqlite3.connect(dbp)
        c.execute('UPDATE pokemon SET in_bag=1')
        c.commit()
        c.close()
        shutil.rmtree(adir)
        os.remove(os.path.join(td, 'active_account.txt'))
        # the owed reconcile + rank pass: _pm_tail_done clears the flag, and main() calls it once the ranks were diffed
        reset(None)
        write_meta(mtp, dict(read_meta(mtp), tail_pending=True))
        rgm.PM_META = mtp
        rgm._pm_tail_done()
        ok(read_meta(mtp)['tail_pending'] is False, '_pm_tail_done clears the owed pass')
        import ast
        with open(os.path.join(rgm.HERE, 'refresh_gamemaster.py'), encoding='utf-8') as f:
            fn = next(x for x in ast.parse(f.read()).body if isinstance(x, ast.FunctionDef) and x.name == 'main')
        ok(any(isinstance(c, ast.Call) and getattr(c.func, 'id', '') == '_pm_tail_done' for c in ast.walk(fn)), 'main() clears the owed pass')
        # main()'s control flow around the guard (what full_audit relies on): a client-GM stop ends the run BEFORE the pvpoke half
        # (so nothing is recrawled or synced), a pending record stops main() before it even asks upstream, a client GM installed
        # this run forces the pvpoke half (reconcile + ranks) though pvpoke is young, and a quiet run ends with ONE line
        # '<pvpoke> | <pokeminers>' (full_audit echoes only the last line, cut at 110)
        class _Reached(Exception):
            pass

        def _pvpoke_half(*a, **k):
            raise _Reached()
        real_rr, real_age = rgm.refresh_rankings, rgm.age_days
        rgm.refresh_rankings, rgm.age_days = _pvpoke_half, (lambda p: 3.0)
        rgm.REVIEW = os.path.join(td, 'main_review.json')
        asked = []
        try:
            rgm.pokeminers_phase = lambda argv, **k: asked.append(1) or (2, True)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc_stop = rgm.main([])
            except _Reached:
                rc_stop = 'the pvpoke half ran'
            ok(rc_stop == 2 and asked, 'a client-GM stop ends main() with 2 before the pvpoke half (got %s)' % rc_stop)
            with open(rgm.REVIEW, 'w', encoding='utf-8') as f:
                json.dump({'since': 'x', 'crossed': ['u'], 'nulled': [], 'lines': ['x'], 'kind': 'client_gm'}, f)
            del asked[:]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc_pend = rgm.main([])
            except _Reached:
                rc_pend = 'the pvpoke half ran'
            ok(rc_pend == 2 and not asked, 'a pending record stops main() before the guard asks upstream (got %s)' % rc_pend)
            os.remove(rgm.REVIEW)
            rgm.pokeminers_phase = lambda argv, **k: (None, True)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rgm.main([])
                ok(False, 'a client GM installed this run must force the pvpoke half')
            except _Reached:
                ok(True, 'a tail forces the pvpoke half')
            rgm._PM_NOTE[0] = 'pokeminers test note'
            rgm.pokeminers_phase = lambda argv, **k: (None, False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_quiet = rgm.main([])
            last = buf.getvalue().strip().splitlines()[-1]
            ok(rc_quiet == 0 and last == 'fresh enough (pvpoke 3 d old) | pokeminers test note', 'a quiet run ends with ONE line: %r' % last)
        finally:
            rgm.pokeminers_phase, rgm.refresh_rankings, rgm.age_days = real_phase, real_rr, real_age
    finally:
        rgm.REVIEW, rgm._pm_engine_inputs, rgm.PM, rgm.PM_META, rgm.GM, rgm.DB = saved


def _live_check(rows, ok):
    """The 22 flips, reproduced from the REAL 0.407 / 0.427 game masters and the real bag -- only where those exist, and
    cross-checked against an independent count from the raw templates (the number moves with every walk, so it is printed,
    never asserted). Also: the size repro on the real files (every XXL copy flagged when the held species' base sizes shrink) and
    0.395.1's integer branch forms must read as an unreadable candidate."""
    clone = os.environ.get('GM_GUARD_PM_CLONE', '/home/user/pokeminers/game_masters')
    p407 = os.path.join(clone, 'previous_game_masters', 'gm_v2_apk4070_2026.04.17-10.48.50', 'game_master.json')
    p427 = os.path.join(clone, 'latest', 'latest.json')
    p395 = os.path.join(clone, 'previous_game_masters', 'gm_v2_apk3951_2026.02.05-06.35.49', 'game_master.json')
    db = os.path.join(ROOT, 'pokemon.db')
    mmp, fep = os.path.join(ROOT, 'move_id_to_name.json'), os.path.join(ROOT, 'form_enum.json')
    if not all(os.path.exists(p) for p in (p407, p427, db, mmp, fep)) or os.path.getsize(db) < 1000000:
        print('gm_guard selftest: live 0.407 -> 0.427 check skipped (%s / pokemon.db not on this machine)' % clone)
        return
    move_map = json.load(open(mmp, encoding='utf-8'))
    enum = {int(k): v for k, v in json.load(open(fep, encoding='utf-8')).items()}
    bag = load_rows(db)
    r = assess(p407, p427, bag, move_map, enum)
    # ONLY the rows whose held move LEAVES 'no normal roll' (the direction `want` counts below): one (species, move) pair flips the
    # other way on this very pair (Cramorant DRILL_PECK: plain -> no normal roll), so a bag holding such a Cramorant would
    # otherwise fail this check in a data session although nothing is wrong
    got = len({f['uid'] for f in r['flips'] if f['axis'] == 'moves' and f['old'] == 'no normal roll' and f['new'] != 'no normal roll'})

    def pools(path):                      # independent of detect_legacy: raw templates -> dex -> normal-roll move names
        out = defaultdict(set)
        for t in json.load(open(path, encoding='utf-8')):
            s = (t.get('data') or {}).get('pokemonSettings')
            m = re.match(r'V(\d{4})_POKEMON_', t.get('templateId', ''))
            if s and m:
                for k in ('quickMoves', 'cinematicMoves', 'nonTmCinematicMoves'):
                    for x in s.get(k) or []:
                        nm = move_map.get(str(x)) if isinstance(x, int) else x
                        if nm:
                            out[int(m.group(1))].add(nm)
        return out
    a, b = pools(p407), pools(p427)
    want = 0
    for row in bag:
        for k in SLOTS:
            nm = move_map.get(str(row[k])) if row[k] else None
            if nm and a.get(row['pokemon_id']) and nm not in a[row['pokemon_id']] and nm in b.get(row['pokemon_id'], ()):
                want += 1
                break
    ok(r['verdict'] == 'FLIPS' and got == want, 'live: reused detect_legacy pools flip %d in-bag rows, the raw templates say %d' % (got, want))
    _c = sqlite3.connect('file:%s?mode=ro' % db.replace('\\', '/'), uri=True)
    try:
        walk = _c.execute('SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1').fetchone()[0]
    finally:
        _c.close()
    if walk == '2026-09-30T01:42:49':                 # the walk the 22 was measured on (2026-09-30); later bags differ
        ok(got == 22, 'live: on the 2026-09-30 01:42:49 walk exactly 22 in-bag rows flip on a held move, got %d' % got)
    print('gm_guard selftest: live 0.407 -> 0.427: %d in-bag rows lose "no normal roll" on a held move (evolve axis %d rows, size axis %d rows, %s)'
          % (got, r['axes'].get('evolve', 0), r['axes'].get('size', 0), r['verdict']))
    # THE SIZE REPRO ON THE REAL FILES (2026-09-30, review): the base height / weight of every species that has an XXL copy in the bag,
    # scaled x0.6 in a copy of 0.427 -- what moved an XXL Ponyta out of the keep (its projection as a Rapidash falls 1082 -> 735, so
    # best_points 983 is under min_points) while the first version of the guard said CLEAR. Every one of those XXL rows must be flagged.
    _c = sqlite3.connect('file:%s?mode=ro' % db.replace('\\', '/'), uri=True)
    try:
        xxl = dict(_c.execute('SELECT uid_hex, pokemon_id FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5').fetchall())
    finally:
        _c.close()
    if xxl:
        gm, held = json.load(open(p427, encoding='utf-8')), set(xxl.values())
        for t in gm:
            s = (t.get('data') or {}).get('pokemonSettings')
            m = re.match(r'V(\d{4})_POKEMON_', t.get('templateId', ''))
            if s and m and int(m.group(1)) in held:
                for k in ('pokedexHeightM', 'pokedexWeightKg'):
                    if s.get(k):
                        s[k] = round(s[k] * 0.6, 3)
        with tempfile.TemporaryDirectory(prefix='gm_guard_live_') as td:
            cand = os.path.join(td, 'scaled_0427.json')
            with open(cand, 'w', encoding='utf-8') as f:
                json.dump(gm, f)
            del gm
            r2 = assess(p427, cand, bag, move_map, enum)
        flagged = {f['uid'] for f in r2['flips'] if f['axis'] == 'size'}
        ok(r2['verdict'] == 'FLIPS' and set(xxl) <= flagged,
           'live: 0.427 with the held XXL species\' base sizes x0.6 must flag every XXL row on the size axis (%d of %d, %s)' % (
               len(set(xxl) & flagged), len(xxl), r2['verdict']))
        print('gm_guard selftest: live size check: base sizes x0.6 flag %d in-bag rows, all %d XXL copies among them' % (len(flagged), len(xxl)))
    if os.path.exists(p395):
        r = assess(p427, p395, bag, move_map, enum)
        ok(r['verdict'] == 'UNREADABLE_NEW', 'live: the engine cannot load 0.395.1 (integer forms) -- must be UNREADABLE_NEW, got %s' % r['verdict'])
        ok(assess(p427, p427, bag, move_map, enum)['verdict'] == 'SAME', 'live: identical is SAME')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    print(__doc__)
