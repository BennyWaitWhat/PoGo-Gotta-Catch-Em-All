"""dashboard.py -- local control panel for the PoGo keep engine + recrawl.

Run:  python dashboard.py   ->  open http://127.0.0.1:8765

SEE: bag totals, per-rule keep counts, server-tag counts, the live Transfer pile, a per-region
     breakdown, and bag search.
CONFIG: every tunable cap/roster/toggle (keep_config.json) with validation + a live impact PREVIEW
     (recomputes keep_policy + build_tagsets on the current DB, no phone writes), export/import, diff.
RUN: Recrawl (full pipeline) and Sync (recompute -> preflight -> prune -> mirror -> reconcile),
     the latter HARD-GATED by the keeper pre-flight; plus a DB-only dry-run tag-diff preview.

Dashboard and linked artifact pages. Single Frida-serial job at a time. Binds 0.0.0.0:8765.
"""
import os
import sys
import json
import time
import sqlite3
import subprocess
import threading
from collections import Counter, defaultdict

from flask import Flask, request, jsonify, Response, send_file

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import keep_config
import curation_config
import studio_data

DB = os.path.join(HERE, 'pokemon.db')
SCR = os.path.join(HERE, 'system', 'scripts')
TD = os.path.join(HERE, 'system', 'analysis', 'tagsets')
POLICY = os.path.join(HERE, 'system', 'analysis', 'policy_reasons.json')
PORT = int(os.environ.get('DASH_PORT') or 8765)

app = Flask(__name__)


@app.before_request
def _origin_guard():
    """Reject cross-origin POSTs (a browser tab on another site can't trigger a phone job). Same-origin UI
    sends a matching Origin; curl/agent POSTs send NO Origin and are allowed -- so the established API
    workflow keeps working without any token (F29)."""
    if request.method == 'POST':
        o = request.headers.get('Origin')
        if o and o not in ('http://127.0.0.1:%d' % PORT, 'http://localhost:%d' % PORT):
            return jsonify({'ok': False, 'error': 'cross-origin POST rejected'}), 403


@app.errorhandler(500)
def _err500(e):
    return jsonify({'ok': False, 'error': 'internal server error'}), 500   # every failure stays JSON (F23)


# ---- national-dex region ranges (pokemon_id == national dex no.) ----
REGIONS = [
    ('Kanto', 1, 151), ('Johto', 152, 251), ('Hoenn', 252, 386), ('Sinnoh', 387, 493),
    ('Unova', 494, 649), ('Kalos', 650, 721), ('Alola', 722, 809), ('Galar', 810, 905),
    ('Paldea', 906, 1025),
]
def region_of(pid):
    for nm, lo, hi in REGIONS:
        if lo <= (pid or 0) <= hi:
            return nm
    return 'Other'

# tag files (the 12 server tags) -> filename
TAG_FILES = {   # GL IV / UL IV / Evolve 1 / Evolve 2 retired 2026-09-09 (granular_tags.RETIRED_TAGS)
    'XXL': 'XXL.txt', 'Hundo': 'Hundo.txt',
    'Nundo': 'Nundo.txt', 'Traded by E+F': 'Traded_by_E+F.txt',   # Event retired 2026-09-09
    'Legacy Moves': 'Legacy_Moves.txt', 'Evolve Once': 'Evolve_Once.txt', 'Evolve Twice': 'Evolve_Twice.txt',
    'Evolve Gated': 'Evolve_Gated.txt', 'Transfer': 'Transfer.txt',   # the fold (2026-09-29): Next/Shiny/Size/Stop retired
    'Best GL': 'Best_GL.txt', 'Best UL': 'Best_UL.txt', 'Best ML': 'Best_ML.txt',   # keep rule 15d (2026-09-23)
    'Evo Best GL': 'Evo_Best_GL.txt', 'Evo Best UL': 'Evo_Best_UL.txt',              # keep rule 15e (2026-09-24)
    'Power Up to 1500': 'Power_Up_to_1500.txt', 'Power Up to 2500': 'Power_Up_to_2500.txt',   # 2026-09-26
    'Unlock 2nd Move': 'Unlock_2nd_Move.txt',
}

# ----------------------------------------------------------------------------- job runner
JOB = {'name': None, 'status': 'idle', 'log': '', 'rc': None, 'running': False, 'started': None, 'ended': None}
_JOB_LOCK = threading.Lock()
_BASELINE = None   # snapshot to diff the current state against (set on load + before each recrawl/sync)
_PROC = {'p': None}        # the live child Popen, so /api/cancel can tree-kill a wedged Frida step (F16)
BUSY = {'name': None}      # short read-only recomputes (preview/tagdiff) -- mutual-exclusion WITHOUT clobbering JOB's log (F17)
# captured at import so /api/health can tell the user their on-disk code is newer than the running process (F15)
_BOOT = {'t': time.time(), 'dash': os.path.getmtime(os.path.abspath(__file__)),
         'kc': os.path.getmtime(keep_config.__file__)}


def _child_env():
    """Env for engine subprocesses: force UTF-8 I/O and DROP COSMETIC_CAP so a stray env override can never
    silently make the cull differ from what keep_config.json (and this dashboard) display (audit F25)."""
    e = {k: v for k, v in os.environ.items() if k != 'COSMETIC_CAP'}
    e['PYTHONUTF8'] = '1'
    return e


def _append(s):
    JOB['log'] += s


def _runner(name, steps, gate=None, snap=None):
    JOB.update(running=True, name=name, status='running', log='', rc=None)
    try:
        if snap:
            # ROLLBACK POINT (2026-09-02 audit): db_safety has a sound snapshot API (sqlite backup() +
            # gzip, retention "last 20 + one per day for 30 days") but the dashboard had never called
            # it -- four months of syncs with no restore point. Take one before the first step that can
            # mutate pokemon.db or the phone. Deliberately NON-FATAL: a failed snapshot must not become
            # a new way to block a job, but it is logged loudly so "there was no backup" is never a
            # surprise after the fact.
            _append('=== ROLLBACK POINT (%s) ===\n' % snap)
            try:
                import db_safety
                _append('snapshot: %s\n' % db_safety.snapshot(snap, DB))
            except Exception as e:
                _append('!! SNAPSHOT FAILED (%s) -- continuing, but this run has NO restore point\n' % e)
        if gate:
            glabel, gargv = gate
            _append('=== GATE: %s ===\n' % glabel)
            p = subprocess.run([sys.executable] + gargv, cwd=HERE,
                               capture_output=True, text=True, encoding='utf-8', errors='replace',
                               stdin=subprocess.DEVNULL, env=_child_env())
            _append((p.stdout or '') + (p.stderr or ''))
            if p.returncode != 0:
                JOB.update(status='BLOCKED -- pre-flight failed, sync refused', rc=p.returncode, running=False)
                return
        for label, argv in steps:
            _append('\n=== %s ===\n' % label)
            p = subprocess.Popen([sys.executable] + argv, cwd=HERE,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, text=True, bufsize=1,
                                 encoding='utf-8', errors='replace', env=_child_env(),
                                 start_new_session=(os.name != 'nt'))   # POSIX: own group, so Cancel kills the tree
            _PROC['p'] = p
            for line in p.stdout:
                _append(line)
            p.wait()
            _PROC['p'] = None
            if JOB.pop('cancelled', False):
                _append('\n=== CANCELLED by user ===\n')
                JOB.update(status='cancelled', rc=p.returncode, running=False)
                return
            if p.returncode != 0:
                # a keeper pre-flight refusal is a SAFE block (keepers protected, nothing pushed), not a crash (F18)
                if label.upper().startswith('PRE-FLIGHT') or label.startswith('preflight'):
                    JOB.update(status='BLOCKED -- keeper pre-flight refused the sync (keepers safe, nothing pushed)',
                               rc=p.returncode, running=False)
                else:
                    JOB.update(status='FAILED at "%s" (rc=%d)' % (label, p.returncode), rc=p.returncode, running=False)
                return
        JOB.update(status='done', rc=0, running=False)
    except Exception as e:
        JOB.update(status='error: %s' % e, rc=-1, running=False)
    finally:
        _PROC['p'] = None
        JOB['ended'] = time.time()


def start_job(name, steps, gate=None, snap=None):
    global _BASELINE
    with _JOB_LOCK:
        if JOB['running'] or BUSY['name']:
            return False
        if name.startswith('recrawl') or name.startswith('sync'):
            _BASELINE = snapshot()   # capture PRE-job state so the post-job diff shows exactly what this run changed
        JOB.update(running=True, name=name, status='starting', log='', rc=None,
                   started=time.time(), ended=None)  # set UNDER the lock -- no TOCTOU
        threading.Thread(target=_runner, args=(name, steps, gate, snap), daemon=True).start()
        return True


def _py(*argv):
    return list(argv)


# ------------------------------------------------------------------ shared job stages (ONE definition)
# Every job endpoint composes its step list from these. Hand-copied step lists are how /api/full_audit
# ended up running its AUDIT GATE and then REGENERATING the audited artifact afterwards, and how the
# Auto-tag button ended up on a completely different (ungated) engine. If a stage changes, it changes
# for every caller at once.

def _recrawl_steps():
    return [
        ('full pipeline (walk + recompute + preflight + audit + live storage cap)', _py(os.path.join(HERE, 'pogo_pipeline.py'))),
        # the live storage cap (player_state.json) is read INSIDE the pipeline's session since 2026-09-12
        # (step_read_player_state); read_player_state.py remains as the standalone tool.
    ]


def _recompute_steps():
    """Regenerate the pile from the CURRENT config so the gates and the push all see one artifact."""
    return [
        ('recompute: keep_policy', _py(os.path.join(SCR, 'keep_policy.py'))),
        ('recompute: build_tagsets', _py(os.path.join(SCR, 'build_tagsets.py'))),
    ]


def _gate_steps(expect_members=None):
    """The keeper gate. rc != 0 on either aborts the job BEFORE any phone write. expect_members (X3, 2026-09-24): the
    pile fingerprint full_audit took when the 11 audits judged it -- the gate refuses a pile with other members."""
    extra = ['--expect-pile-members', expect_members] if expect_members else []
    return [
        ('PRE-FLIGHT keeper gate (aborts on any real keeper)', _py(os.path.join(SCR, 'preflight_transfer.py'), *extra)),
    ]


def _push_steps(dry=False, reconcile=True):
    """Phone writes + the DB mirror, in the ONLY safe order.

    Pass reconcile=False when a full verify_tags_live run follows -- that script restarts PoGo and
    reconciles against a genuine server refetch, so a cache-only reconcile just before it is a second
    Frida attach for a strictly weaker check.

    ORDER MATTERS (2026-09-02 audit, two separate defects):
      1. set_db_tags_from_files USED TO RUN FIRST. It rewrites auth_tag_names straight from the tagset
         FILES with no knowledge of whether the push then succeeded -- and auth_tag_names is exactly
         what /api/tagdiff calls "the phone's last-known tags". So after ANY sync, successful or not,
         the preview reported "already in sync". It now runs LAST, and because a non-zero step aborts
         the job it only runs at all once prune_tags actually verified the push.
      2. Evolve_Shiny.txt is produced by refresh_evolve_shiny, which used to run AFTER set_db -- so the
         DB mirror was staged from a stale file (measured: 2 days old, 1 uid, while every other tagset
         was minutes old) and repaired only by a later step. prune_tags.PLAN does not own 'Evolve Shiny',
         so nothing else repairs it. Running set_db last fixes this for free: the file is fresh by then.
    """
    prune = _py(os.path.join(SCR, 'prune_tags.py'), '--atomic') + (['--dry-run'] if dry else [])
    # A dry-run must touch NOTHING (F06): the flag previously reached only prune, so refresh_evolve_shiny
    # still did live Frida tag writes and set_db_tags_from_files still overwrote auth_tag_names (the
    # server-truth mirror tagdiff reads), making the next preview falsely report "already in sync".
    refresh = _py(os.path.join(SCR, 'refresh_evolve_shiny.py')) + (['--dry-run'] if dry else [])
    return [
        ('prune_tags' + (' (DRY-RUN)' if dry else ' --atomic'), prune),
        # refresh_evolve_shiny step removed 2026-09-12: build_tagsets writes Evolve_Shiny.txt, prune pushes it.
        # DB mirror LAST, and skipped entirely in dry mode so auth_tag_names stays an honest record of
        # what the phone actually has.
        *([] if dry else [('set_db_tags_from_files (mirror, AFTER a verified push)',
                           _py(os.path.join(SCR, 'set_db_tags_from_files.py')))]),
        *([('reconcile_tags --report', _py(os.path.join(SCR, 'reconcile_tags.py'), '--report'))]
          if reconcile else []),
    ]


# ----------------------------------------------------------------------------- state
def _tag_counts():
    out = {}
    for name, fn in TAG_FILES.items():
        try:
            with open(os.path.join(TD, fn), encoding='utf-8') as f:
                out[name] = sum(1 for ln in f if ln.strip())
        except FileNotFoundError:
            out[name] = None
    return out


def snapshot():
    con = sqlite3.connect(DB)
    try:
        con.row_factory = sqlite3.Row
        bag = con.execute("SELECT uid_hex, pokemon_id, species_name, form, iv_total, iv_atk, iv_def, "
                          "iv_sta, fresh_shiny, cp FROM pokemon WHERE in_bag=1").fetchall()
    finally:
        con.close()
    total = len(bag)
    baguids = {r['uid_hex'] for r in bag}
    pol = {}
    if os.path.exists(POLICY):
        try:
            pol = json.load(open(POLICY, encoding='utf-8'))
        except Exception:
            pol = {}
    kept = set(pol)
    per_rule = Counter(r for u, rs in pol.items() if u in baguids for r in rs)   # in-bag only -> matches 'kept' (F12)
    try:
        transfer = set(x.strip() for x in open(os.path.join(TD, '6_Transfer.txt'), encoding='utf-8') if x.strip())
    except FileNotFoundError:
        transfer = set()
    # the pile (6_Transfer.txt, engine output) vs the Transfer TAG file (Transfer.txt, what sync pushes) can
    # diverge if build_tagsets hasn't re-run since the last keep_policy -> flag it so the UI warns (F20)
    try:
        xfer_tag = set(x.strip() for x in open(os.path.join(TD, 'Transfer.txt'), encoding='utf-8') if x.strip())
    except FileNotFoundError:
        xfer_tag = set()
    pile_stale = bool(transfer != xfer_tag) if (transfer or xfer_tag) else False
    pile_why = '6_Transfer.txt (engine pile) and Transfer.txt (sync tag) differ' if pile_stale else ''
    # SECOND staleness axis (2026-09-02 audit). The set comparison above only catches build_tagsets
    # lagging keep_policy. It does NOT catch the more common case: keep_config.json edited AFTER the
    # pile was computed, so the on-disk pile encodes caps the user has since changed. Measured live on
    # 2026-09-02 -- keep_config.json 01:59 > policy_reasons.json 01:58 > Transfer.txt 01:39, the two
    # files were set-identical, the badge said NOT stale, and `full_audit.py --audits-only` was failing
    # on shadow (top-N) purely from that skew. mtime is a heuristic, not proof; the durable fix is a
    # config fingerprint stamped by keep_policy into policy_reasons.json (cross-package -- when that
    # lands, compare the hash here and delete this block rather than keeping both).
    try:
        cfg_m = os.path.getmtime(getattr(keep_config, 'PATH', os.path.join(HERE, 'keep_config.json')))
        art = [os.path.getmtime(p) for p in (POLICY, os.path.join(TD, 'Transfer.txt'),
                                             os.path.join(TD, '6_Transfer.txt')) if os.path.exists(p)]
        if art and cfg_m > min(art):
            pile_stale = True
            pile_why = ((pile_why + '; ') if pile_why else '') + \
                'keep_config.json is NEWER than the computed pile -- recompute before trusting this list'
    except Exception:
        pass   # a missing/unreadable mtime must never break the dashboard read

    regions = {}
    for r in bag:
        d = regions.setdefault(region_of(r['pokemon_id']), {'total': 0, 'kept': 0, 'transfer': 0})
        d['total'] += 1
        if r['uid_hex'] in kept:
            d['kept'] += 1
        if r['uid_hex'] in transfer:
            d['transfer'] += 1
    region_rows = [{'region': nm, **regions[nm]} for nm, *_ in REGIONS if nm in regions]
    if 'Other' in regions:
        region_rows.append({'region': 'Other', **regions['Other']})

    bymap = {r['uid_hex']: r for r in bag}
    pile = []
    for u in sorted(transfer):
        r = bymap.get(u)
        if r:
            pile.append({'uid': u, 'species': r['species_name'], 'iv': r['iv_total'],
                         'spread': '%s/%s/%s' % (r['iv_atk'], r['iv_def'], r['iv_sta']),
                         'shiny': bool(r['fresh_shiny']), 'cp': r['cp']})
    return {
        'bag_total': total,
        'kept': len(kept & set(bymap)),
        'transfer': len([u for u in transfer if u in bymap]),
        'per_rule': dict(sorted(per_rule.items(), key=lambda x: -x[1])),
        'tags': _tag_counts(),
        'regions': region_rows,
        'transfer_pile': pile,
        'pile_stale': pile_stale,
        'pile_stale_why': pile_why,
        'db_mtime': os.path.getmtime(DB) if os.path.exists(DB) else None,        # data-freshness KPI (F15)
        'policy_mtime': os.path.getmtime(POLICY) if os.path.exists(POLICY) else None,
        'adb_target': os.environ.get('ADB_TARGET') or '100.98.158.56:5555 (default Tailscale)',
    }


def _diff(cur, base):
    """What changed between the baseline snapshot and the current one -- so the user SEES each recrawl's effect."""
    if not base:
        return None
    cur_by = {m['uid']: m for m in cur['transfer_pile']}
    base_by = {m['uid']: m for m in base['transfer_pile']}
    new_uids = set(cur_by) - set(base_by)
    gone_uids = set(base_by) - set(cur_by)
    new_sp = Counter(cur_by[u]['species'] for u in new_uids)
    gone_sp = Counter(base_by[u]['species'] for u in gone_uids)
    tagd = {}
    for t in set(cur['tags']) | set(base['tags']):
        d = (cur['tags'].get(t) or 0) - (base['tags'].get(t) or 0)
        if d:
            tagd[t] = d
    return {
        'd_bag': cur['bag_total'] - base['bag_total'],
        'd_keep': cur['kept'] - base['kept'],
        'd_transfer': cur['transfer'] - base['transfer'],
        'tags': tagd,
        'pile_new_count': len(new_uids), 'pile_gone_count': len(gone_uids),
        'pile_new': sorted(new_sp.items(), key=lambda x: -x[1])[:30],
        'pile_gone': sorted(gone_sp.items(), key=lambda x: -x[1])[:30],
        'any': bool(new_uids or gone_uids or tagd or (cur['bag_total'] != base['bag_total'])),
    }



# --------------------------------------------------------------- tailnet-only access guard
@app.before_request
def _tailnet_guard():
    """The dashboard triggers IRREVERSIBLE tag writes, so binding 0.0.0.0 (needed for the phone button)
    must NOT expose it to the LAN/hotel-wifi. Allow loopback + the CGNAT tailnet range only."""
    ip = request.remote_addr or ''
    if ip.startswith('127.') or ip in ('::1', 'localhost'):
        return None
    try:
        a, b = int(ip.split('.')[0]), int(ip.split('.')[1])
        if a == 100 and 64 <= b <= 127:      # 100.64.0.0/10 -- Tailscale
            return None
    except Exception:
        pass
    return Response('forbidden: dashboard is loopback + tailnet only', status=403, mimetype='text/plain')

# ----------------------------------------------------------------------------- routes
@app.get('/api/state')
def api_state():
    global _BASELINE
    cur = snapshot()
    if _BASELINE is None:
        _BASELINE = cur   # first load establishes the reference point
    cur['diff'] = _diff(cur, _BASELINE)
    return jsonify(cur)


@app.post('/api/baseline')
def api_baseline():
    global _BASELINE
    with _JOB_LOCK:
        if JOB['running'] or BUSY['name']:
            return jsonify({'ok': False, 'error': 'job running -- the baseline is captured automatically before each run'}), 409
        _BASELINE = snapshot()
    return jsonify({'ok': True})


@app.get('/api/health')
def api_health():
    """Liveness + a stale-code check: if dashboard.py/keep_config.py on disk are newer than the running
    process, config edits won't behave until restart -- the UI surfaces this as a persistent warning (F15)."""
    def _st(path, was):
        try:
            return os.path.getmtime(path) > was + 1
        except OSError:
            return False
    return jsonify({
        'ok': True, 'pid': os.getpid(), 'started': _BOOT['t'],
        'src_stale': {
            'dashboard.py': _st(os.path.abspath(__file__), _BOOT['dash']),
            'keep_config.py': _st(keep_config.__file__, _BOOT['kc']),
        },
    })


@app.get('/report')
def line_report():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'line_report.html')
    return send_file(p) if os.path.exists(p) else ('Run gen_line_report.py first.', 404)


@app.get('/plan')
def master_plan():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'master_plan.html')
    return send_file(p) if os.path.exists(p) else ('Run gen_master_plan.py first.', 404)


@app.get('/dex')
def art_dex():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'art_dex.html')
    return send_file(p) if os.path.exists(p) else ('Run gen_artifacts.py first.', 404)


@app.get('/snapshot')
def art_snapshot():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'art_collection.html')
    return send_file(p) if os.path.exists(p) else ('Run gen_artifacts.py first.', 404)


@app.get('/lattice')
def art_lattice():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'art_lattice.html')
    return send_file(p) if os.path.exists(p) else ('Run gen_artifacts.py first.', 404)


@app.get('/upgrades')
def art_upgrades():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'art_upgrades.html')
    return send_file(p) if os.path.exists(p) else ('Run gen_artifacts.py first.', 404)


@app.get('/<any(art_dex,art_collection,art_lattice,art_upgrades,master_plan,line_report):name>.html')
def art_file(name):
    # serve the artifacts by filename too, so their relative cross-links work under the dashboard
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + '.html')
    return send_file(p) if os.path.exists(p) else ('Run gen_artifacts.py first.', 404)


@app.get('/api/config')
def api_config():
    return jsonify({'config': keep_config.reload(), 'defaults': keep_config.DEFAULTS,
                    'cap_bounds': keep_config._CAP_BOUNDS, 'pvp_bounds': keep_config._PVP_BOUNDS})


@app.post('/api/config')
def api_config_save():
    cfg = request.get_json(force=True) or {}
    with _JOB_LOCK:   # hold the lock ACROSS the write so a job can't start mid-save (F27)
        if JOB['running'] or BUSY['name']:
            return jsonify({'ok': False, 'error': 'a recrawl/sync job is running; wait for it'}), 409
        try:
            merged = keep_config.write(cfg)
        except ValueError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400
        except Exception as e:   # any other failure stays JSON the UI can show, never a raw 500 (F01)
            return jsonify({'ok': False, 'error': 'internal: %s' % e}), 500
    return jsonify({'ok': True, 'config': merged})


@app.post('/api/preview')
def api_preview():
    """Save the posted config, recompute keep_policy + build_tagsets on the CURRENT DB (no phone),
    and return the new snapshot. This is the live impact preview."""
    cfg = request.get_json(force=True) or {}
    with _JOB_LOCK:
        if JOB['running'] or BUSY['name']:
            return jsonify({'ok': False, 'error': 'a recrawl/sync job is running; wait for it'}), 409
        BUSY['name'] = 'preview'   # mutually exclusive w/ jobs but does NOT clobber the last job's log (F17)
    prev = None
    try:
        if os.path.exists(keep_config.PATH):
            with open(keep_config.PATH, encoding='utf-8') as f:
                prev = f.read()
    except Exception:
        prev = None

    def _restore_artifacts():
        """Roll the config file back AND re-emit the engine artifacts from it, so a rejected preview leaves
        policy_reasons.json / 6_Transfer.txt / Transfer.txt consistent with the restored config (F19)."""
        if prev is None:
            return
        try:
            with open(keep_config.PATH, 'w', encoding='utf-8') as f:
                f.write(prev)
            keep_config.reload()
            for argv in (_py(os.path.join(SCR, 'keep_policy.py')), _py(os.path.join(SCR, 'build_tagsets.py'))):
                subprocess.run([sys.executable] + argv, cwd=HERE, capture_output=True,
                               text=True, encoding='utf-8', errors='replace', env=_child_env())
        except Exception:
            pass

    try:
        try:
            keep_config.write(cfg)
        except ValueError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400   # rejected before write -> config unchanged
        except Exception as e:
            return jsonify({'ok': False, 'error': 'internal: %s' % e}), 500
        before = snapshot()
        for argv in (_py(os.path.join(SCR, 'keep_policy.py')), _py(os.path.join(SCR, 'build_tagsets.py'))):
            p = subprocess.run([sys.executable] + argv, cwd=HERE, capture_output=True,
                               text=True, encoding='utf-8', errors='replace', env=_child_env())
            if p.returncode != 0:
                _restore_artifacts()
                return jsonify({'ok': False, 'error': 'recompute failed (config rolled back, artifacts restored from saved config)',
                                'log': (p.stdout or '') + (p.stderr or '')}), 500
        after = snapshot()
        return jsonify({'ok': True, 'before': {'kept': before['kept'], 'transfer': before['transfer'], 'per_rule': before['per_rule']},
                        'after': after})
    except Exception as e:
        return jsonify({'ok': False, 'error': 'internal: %s' % e}), 500
    finally:
        BUSY['name'] = None


@app.get('/api/tagdiff')
def api_tagdiff():
    """DRY-RUN Sync preview, DB-only (no Frida): recompute the tag files from the SAVED config, then
    diff them against the phone's last-known tags (DB auth_tag_names). Shows exactly what a real Sync
    would ADD / REMOVE per tag, so a push is never a surprise."""
    with _JOB_LOCK:
        if JOB['running'] or BUSY['name']:
            return jsonify({'ok': False, 'error': 'a recrawl/sync job is running; wait for it'}), 409
        BUSY['name'] = 'sync-preview'   # don't clobber the last job's log (F17)
    try:
        for argv in (_py(os.path.join(SCR, 'keep_policy.py')), _py(os.path.join(SCR, 'build_tagsets.py'))):
            p = subprocess.run([sys.executable] + argv, cwd=HERE, capture_output=True,
                               text=True, encoding='utf-8', errors='replace', env=_child_env())
            if p.returncode != 0:
                return jsonify({'ok': False, 'error': 'recompute failed', 'log': (p.stdout or '') + (p.stderr or '')}), 500
        # read the bag FIRST so computed tags can be intersected with it -- a stale tagset file (e.g.
        # Evolve_Shiny.txt, regenerated only by a real sync) otherwise shows phantom adds for uids no
        # longer in the bag, and add_sample then leaks raw uid-hex instead of a species name (F11)
        con = sqlite3.connect(DB)
        try:
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT uid_hex, species_name, auth_tag_names FROM pokemon WHERE in_bag=1").fetchall()
        finally:
            con.close()
        nm = {r['uid_hex']: r['species_name'] for r in rows}
        bagset = set(nm)
        computed = {}
        for name, fn in TAG_FILES.items():
            try:
                with open(os.path.join(TD, fn), encoding='utf-8') as f:
                    computed[name] = set(x.strip() for x in f if x.strip()) & bagset
            except FileNotFoundError:
                computed[name] = set()
        server = defaultdict(set)
        for r in rows:
            for t in (r['auth_tag_names'] or '').split(';'):   # DB stores multi-tags semicolon-joined ("Event;Hundo")
                t = t.strip()
                if t:
                    server[t].add(r['uid_hex'])
        out, untracked = [], []
        for t in sorted(set(computed) | set(server)):
            if t not in TAG_FILES:   # a personal server tag the engine doesn't manage -- inform, never "remove" (F28)
                untracked.append({'tag': t, 'server': len(server.get(t, set()))})
                continue
            comp, srv = computed.get(t, set()), server.get(t, set())
            adds, rem = comp - srv, srv - comp
            out.append({'tag': t, 'server': len(srv), 'computed': len(comp),
                        'add': len(adds), 'remove': len(rem),
                        'add_sample': sorted({nm.get(u, u) for u in adds})[:8],
                        'remove_sample': sorted({nm.get(u, u) for u in rem})[:8]})
        return jsonify({'ok': True, 'tags': out, 'untracked': untracked,
                        'total_add': sum(x['add'] for x in out),
                        'total_remove': sum(x['remove'] for x in out)})
    except Exception as e:
        return jsonify({'ok': False, 'error': 'internal: %s' % e}), 500
    finally:
        BUSY['name'] = None


@app.post('/api/recrawl')
def api_recrawl():
    ok = start_job('recrawl', _recrawl_steps())
    return jsonify({'ok': ok, 'error': None if ok else 'a job is already running'}), (200 if ok else 409)


@app.post('/api/autotag')
def api_autotag():
    """Auto-TAGGING (never auto-transferring): recrawl, recompute, keeper-gate, then sync the tags.

    REWIRED 2026-09-02. This used to be ONE step -- auto_tag.py -- which decided the pile with cull_v9
    (hardcoded, historical caps; no cosmetic/dynamax/gigantamax/rarity/shadow axis at all), rewrote
    auth_tag_names from that column, pushed 'Transfer', then had prune_server_tag.py strip every server
    member NOT in it. Measured against the live DB, one press would have tagged 44 KEEPERS for release
    (26 shiny, 13 variant_floor, 5 unconditionally-protected Pichu) and untagged 31 real pile members.
    auto_tag.py's own pre-flight returned zero hits on that pile, so nothing stopped it.

    The button now runs exactly the sanctioned path -- the SAME stage functions /api/sync uses -- so
    there is one pile producer (keep_policy) and one keeper gate (preflight_transfer). Still tags only:
    nothing here releases anything; the user releases in-game by hand."""
    dry = bool((request.get_json(silent=True) or {}).get('dry'))
    steps = _recrawl_steps() + _recompute_steps() + _gate_steps() + _push_steps(dry)
    ok = start_job('autotag' + (' (dry-run)' if dry else ''), steps,
                   snap=None if dry else 'before_autotag')
    return jsonify({'ok': ok, 'error': None if ok else 'a job is already running'}), (200 if ok else 409)


@app.post('/api/sync')
def api_sync():
    _body = request.get_json(silent=True) or {}
    dry = bool(_body.get('dry'))
    # X3 (2026-09-24): only a well-formed sha256 is passed on; anything else is ignored (no fingerprint = no check,
    # exactly today's behaviour for the dashboard's own buttons).
    _exp = _body.get('audited_pile_members')
    _exp = _exp if isinstance(_exp, str) and __import__('re').fullmatch(r'[0-9a-f]{64}', _exp) else None
    steps = (
        # 1) REGENERATE the pile from the CURRENT config so the gate + push match what's configured
        _recompute_steps()
        # 2) KEEPER GATE -- preflight returns rc!=0 to ABORT here, before any phone write
        + _gate_steps(_exp)
        # 3) push to phone, then mirror the DB (see _push_steps for why that order)
        + _push_steps(dry)
    )
    ok = start_job('sync' + (' (dry-run)' if dry else ''), steps,
                   snap=None if dry else 'before_sync')
    return jsonify({'ok': ok, 'error': None if ok else 'a job is already running'}), (200 if ok else 409)


@app.post('/api/full_audit')
def api_full_audit():
    """THE PHONE BUTTON (user 2026-08-29 "Make it a button on my phone"). One job = the whole cycle:
    recrawl -> 4 audits IN PARALLEL (one step; rc!=0 ABORTS the job = the keeper gate) -> sync -> verify.

    Composed from the SAME steps as /api/recrawl and /api/sync so there is exactly one code path for
    each stage; the audit step sits between them, so a failing audit means the sync steps never run.

    GATE ORDER FIX (2026-09-02): the AUDIT GATE used to run BEFORE recompute, so keep_policy and
    build_tagsets then rewrote 6_Transfer.txt / Transfer.txt after the four audits had already passed
    -- the artifact that was audited was not the artifact that got pushed. The gate now runs on the
    regenerated pile, immediately before the pre-flight."""
    steps = (
        # THE GAME-MASTER STOP FIRST, like full_audit.py (H10-6, 2026-09-29): a refresh whose rank changes moved keep
        # decisions exits 2 until a human runs --ack, and a job step's rc != 0 aborts before any phone write.
        [('game master freshness + review gate', _py(os.path.join(SCR, 'refresh_gamemaster.py')))]
        + _recrawl_steps()
        # REGENERATE FIRST, so the audits below judge the artifact this job will actually push
        + _recompute_steps()
        # KEEPER GATE 1: 4 audits in parallel; any failure -> rc!=0 -> job aborts BEFORE any phone write
        + [('AUDIT GATE (8-layer + membership + comb-up + law + structure)',
            _py(os.path.join(HERE, 'full_audit.py'), '--audits-only'))]
        # KEEPER GATE 2: live pre-flight on that same pile
        + _gate_steps()
        + _push_steps(False, reconcile=False)   # verify_tags_live below is the stronger check
        + [('verify vs live phone', _py(os.path.join(HERE, 'verify_tags_live.py')))]
    )
    ok = start_job('FULL AUDIT', steps, snap='before_full_audit')
    return jsonify({'ok': ok, 'error': None if ok else 'a job is already running'}), (200 if ok else 409)


from _mobile_html import MOBILE_HTML          # phone one-button page (kept out of this file for size)


@app.get('/api/stats_lite')
def api_stats_lite():
    """Tiny payload for the phone button page -- counts only, no heavy joins."""
    try:
        con = sqlite3.connect(DB); q = lambda x: con.execute(x).fetchone()[0]
        bag = q('SELECT COUNT(*) FROM pokemon WHERE in_bag=1')
        hund = q('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND iv_total=45')
        nund = q('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND iv_total=0')
        con.close()
        cap = json.load(open(os.path.join(HERE, 'player_state.json')))['max_pokemon_storage']
        tf = os.path.join(HERE, 'system', 'analysis', 'tagsets', 'Transfer.txt')
        pile = len(open(tf).read().split())
        when = time.strftime('%b %d %H:%M', time.localtime(os.path.getmtime(tf)))
        return jsonify({'bag': bag, 'cap': cap, 'hundos': hund, 'nundos': nund, 'pile': pile, 'when': when})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.get('/m')
def mobile_page():
    """Phone-sized one-button page. Add to Home screen -> it launches standalone like an app."""
    return Response(MOBILE_HTML, mimetype='text/html')


@app.post('/api/cancel')
def api_cancel():
    """Tree-kill the running job's child process -- a wedged Frida step would otherwise block every gated
    endpoint forever. A mid-write step left partial is harmless (next Recrawl re-stages); the dead Frida
    session may need the documented freezer-fix before the next job (F16)."""
    with _JOB_LOCK:
        if not JOB['running']:
            return jsonify({'ok': False, 'error': 'no job running'}), 409
        p = _PROC.get('p')
        JOB['cancelled'] = True
    if p is not None:
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)], capture_output=True)
            else:                                # Linux (cloud): the job runs in its own session -> kill its group
                os.killpg(os.getpgid(p.pid), 9)
        except Exception as e:
            return jsonify({'ok': False, 'error': 'kill failed: %s' % e}), 500
    return jsonify({'ok': True})


@app.post('/api/verify')
def api_verify():
    # TRUE server-side tag verification: restarts PoGo so the client refetches tags from the server,
    # then reconciles. reconcile alone reads GetCachedTag* (the CLIENT CACHE) and so can bless a write
    # that never persisted -- that is how a 480-member Transfer tag silently vanished (2026-07-25).
    steps = [('VERIFY tags (cache reconcile -- PoGo is never restarted, user rule 2026-09-25)', _py(os.path.join(HERE, 'verify_tags_live.py')))]
    ok = start_job('verify-tags', steps)
    return jsonify({'ok': ok, 'error': None if ok else 'a job is already running'}), (200 if ok else 409)


@app.post('/api/preflight')
def api_preflight():
    # Regenerate the pile FIRST (mirror /api/sync): the standalone button used to preflight whatever
    # stale Transfer.txt was on disk, so a green result after a config edit was meaningless (audit F30)
    steps = [
        ('recompute: keep_policy', _py(os.path.join(SCR, 'keep_policy.py'))),
        ('recompute: build_tagsets', _py(os.path.join(SCR, 'build_tagsets.py'))),
        ('preflight_transfer (live Frida)', _py(os.path.join(SCR, 'preflight_transfer.py'))),
    ]
    ok = start_job('preflight', steps)
    return jsonify({'ok': ok, 'error': None if ok else 'a job is already running'}), (200 if ok else 409)


@app.get('/api/job')
def api_job():
    st, en = JOB.get('started'), JOB.get('ended')
    if st:
        elapsed = round((time.time() if JOB['running'] else (en or time.time())) - st, 1)
    else:
        elapsed = 0
    d = {k: JOB[k] for k in ('name', 'status', 'rc', 'running', 'log')}
    d['elapsed'] = elapsed
    d['busy'] = BUSY['name']   # a short read-only recompute is in flight (F17)
    return jsonify(d)


@app.get('/api/search')
def api_search():
    q = (request.args.get('q') or '').strip().lower()
    shiny = request.args.get('shiny') == '1'
    hundo = request.args.get('hundo') == '1'
    con = sqlite3.connect(DB)
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT uid_hex, pokemon_id, species_name, form, iv_total, iv_atk, iv_def, "
                           "iv_sta, fresh_shiny, cp FROM pokemon WHERE in_bag=1").fetchall()
    finally:
        con.close()
    # guard the policy load: a torn read during a recompute must NOT silently mark every mon TRANSFER
    # (that would violate engine-truth) -- tell the UI to retry instead (F23)
    pol = {}
    if os.path.exists(POLICY):
        try:
            pol = json.load(open(POLICY, encoding='utf-8'))
        except Exception:
            return jsonify({'count': 0, 'shown': 0, 'rows': [],
                            'error': 'keep reasons are being recomputed -- retry in a moment'})
    out = []
    for r in rows:
        variant = (studio_data.decode_form(r['form']) or '') if r['form'] else ''   # distinguish same-species rows (F35)
        if q and q not in (r['species_name'] or '').lower() and q not in r['uid_hex'] and q not in variant.lower():
            continue
        if shiny and not r['fresh_shiny']:
            continue
        if hundo and (r['iv_total'] or 0) != 45:
            continue
        out.append({'uid': r['uid_hex'], 'species': r['species_name'],
                    'spread': '%s/%s/%s' % (r['iv_atk'], r['iv_def'], r['iv_sta']),
                    'iv': r['iv_total'], 'cp': r['cp'], 'shiny': bool(r['fresh_shiny']),
                    'form': r['form'] or 0, 'variant': variant,
                    'region': region_of(r['pokemon_id']),
                    'reasons': sorted(pol.get(r['uid_hex'], [])) or ['TRANSFER']})
    out.sort(key=lambda x: (x['species'], -(x['iv'] or 0)))   # sort the FULL match set, THEN cap
    total = len(out)
    out = out[:500]
    return jsonify({'count': total, 'shown': len(out), 'rows': out})


# ----------------------------------------------------------------------------- Curation Studio (additive)
@app.get('/studio')
def studio_index():
    return Response(STUDIO_PAGE, mimetype='text/html')


@app.get('/api/studio/categories')
def api_studio_categories():
    return jsonify({'categories': studio_data.categories(), 'sprite_cdn': curation_config.sprite_cdn()})


@app.get('/api/studio/category/<cat>')
def api_studio_category(cat):
    gcap = request.args.get('gcap')
    try:
        g = int(gcap) if gcap not in (None, '') else None
    except ValueError:
        return jsonify({'ok': False, 'error': 'gcap must be an integer'}), 400
    pspec = None   # optional what-if per-species overrides as JSON {pid: cap} (F02 axis-aware preview)
    raw_ps = request.args.get('pspec')
    if raw_ps:
        try:
            pspec = {str(k): int(v) for k, v in (json.loads(raw_ps) or {}).items()}
        except Exception:
            return jsonify({'ok': False, 'error': 'pspec must be JSON {pid: int}'}), 400
    return jsonify(studio_data.category_view(cat, proposed_global=g, proposed_species=pspec))


@app.get('/api/studio/sprite/<int:pid>')
def api_studio_sprite(pid):
    form = request.args.get('form')
    try:
        f = int(form) if form not in (None, '') else 0
    except ValueError:
        f = 0   # bad form -> serve base art rather than erroring an <img> (F26)
    fn = studio_data.sprite_rel(pid, f)
    p = studio_data.sprite_path(fn) if fn else None
    if p:
        return send_file(p, mimetype='image/jpeg')
    return ('', 404)


@app.post('/api/studio/apply')
def api_studio_apply():
    body = request.get_json(force=True) or {}
    cat = body.get('cat')
    cap_name = (studio_data.CATS.get(cat) or {}).get('cap')
    if not cap_name:
        return jsonify({'ok': False, 'error': 'unknown category'}), 400
    with _JOB_LOCK:   # hold the lock across parse+write so a job can't start mid-apply (F27)
        if JOB['running'] or BUSY['name']:
            return jsonify({'ok': False, 'error': 'a recrawl/sync job is running; wait for it'}), 409
        try:
            cfg = keep_config.raw()
            if body.get('global_cap') is not None:
                cfg.setdefault('caps', {})[cap_name] = int(body['global_cap'])
            if isinstance(body.get('species_caps'), dict):
                psc = cfg.setdefault('per_species_caps', {}).setdefault(cap_name, {})
                for pid, c in body['species_caps'].items():
                    if c is None:
                        psc.pop(str(pid), None)
                    else:
                        psc[str(pid)] = int(c)
                if not psc:
                    cfg['per_species_caps'].pop(cap_name, None)
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'caps must be integers'}), 400   # bad numeric body (F26)
        try:
            keep_config.write(cfg)
        except ValueError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400
        except Exception as e:
            return jsonify({'ok': False, 'error': 'internal: %s' % e}), 500   # never a raw 500 (F01)
    return jsonify({'ok': True, 'caps': keep_config.raw().get('caps'), 'per_species_caps': keep_config.raw().get('per_species_caps')})


@app.get('/')
def index():
    return Response(PAGE, mimetype='text/html')


# ----------------------------------------------------------------------------- frontend (single page; no Jinja)
PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Keep Engine — Control Center</title>
<style>
 :root{
   --bg:#0a0e14;--bg2:#070a0f;--panel:#11161f;--panel2:#161c27;--elev:#1b2230;
   --ink:#e8eef6;--ink2:#aeb9c7;--mut:#6e7b8c;--line:#222b38;--line2:#2c3645;
   --acc:#4c9aff;--acc2:#2b6fe0;--acc-dim:rgba(76,154,255,.14);
   --ok:#3fb950;--ok-dim:rgba(63,185,80,.14);--warn:#e3a008;--warn-dim:rgba(227,160,8,.14);
   --bad:#f7544b;--bad-dim:rgba(247,84,75,.14);--purple:#a371f7;--shiny:#f5c518;
   --r:14px;--r2:10px;--sh:0 1px 2px rgba(0,0,0,.4),0 8px 24px -12px rgba(0,0,0,.6);
 }
 *{box-sizing:border-box}
 html,body{margin:0}
 body{background:radial-gradient(1200px 600px at 80% -10%,#0e1722,transparent),var(--bg);color:var(--ink);
   font:14px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
 h1{font-size:16px;margin:0;font-weight:700;letter-spacing:-.01em}
 h2{font-size:11px;margin:0 0 12px;color:var(--mut);text-transform:uppercase;letter-spacing:.09em;font-weight:700}
 h3{font-size:13px;margin:0;font-weight:650}
 a{color:var(--acc);text-decoration:none}
 .mut{color:var(--mut)} .ink2{color:var(--ink2)} .shiny{color:var(--shiny)}
 .tnum{font-variant-numeric:tabular-nums}

 /* top bar */
 header{display:flex;align-items:center;gap:16px;padding:0 22px;height:58px;border-bottom:1px solid var(--line);
   position:sticky;top:0;z-index:30;background:rgba(10,14,20,.9);backdrop-filter:blur(14px) saturate(1.2)}
 .brand{display:flex;align-items:center;gap:10px}
 .logo{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--acc),var(--purple));
   display:grid;place-items:center;font-size:16px;box-shadow:0 4px 14px -4px var(--acc)}
 .kpis{display:flex;gap:8px;margin-left:6px}
 .kpi{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:6px 13px;min-width:78px}
 .kpi .k{font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
 .kpi .v{font-size:17px;font-weight:750;line-height:1.15}
 .kpi.keep .v{color:var(--ok)} .kpi.xfer .v{color:var(--warn)} .kpi.rate .v{color:var(--acc)}
 .spacer{flex:1}
 .jobchip{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line);
   border-radius:999px;padding:5px 12px 5px 11px;font-size:12px}
 .dot{width:9px;height:9px;border-radius:50%;background:#39424f;flex:none}
 .dot.d-run{background:var(--warn);animation:pulse 1.1s infinite} .dot.d-ok{background:var(--ok)} .dot.d-bad{background:var(--bad)}
 @keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(227,160,8,.5)}50%{box-shadow:0 0 0 6px rgba(227,160,8,0)}}
 .adb{font-size:11px;color:var(--mut);max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

 main{max-width:1560px;margin:0 auto;padding:18px}
 .layout{display:grid;grid-template-columns:400px 1fr;gap:16px;align-items:start}
 @media(max-width:1080px){.layout{grid-template-columns:1fr}}
 .col{display:flex;flex-direction:column;gap:16px;min-width:0}
 .sticky{position:sticky;top:74px}
 @media(max-width:1080px){.sticky{position:static}}

 .grid{display:grid;gap:16px}
 .g-2{grid-template-columns:1fr 1fr} .g-3{grid-template-columns:1fr 1fr 1fr}
 @media(max-width:680px){.g-2,.g-3{grid-template-columns:1fr}}

 .card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:var(--r);
   padding:18px;box-shadow:var(--sh)}
 .cardhead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}
 .cardhead h2{margin:0}

 .stat{display:flex;align-items:center;gap:13px}
 .stat .big{font-size:26px;font-weight:800;letter-spacing:-.02em;line-height:1}
 .stat .sub{font-size:11.5px;color:var(--mut);margin-top:3px}
 .ico{width:42px;height:42px;border-radius:11px;display:grid;place-items:center;font-size:20px;flex:none}
 .ico.blue{background:var(--acc-dim)} .ico.amber{background:var(--warn-dim)} .ico.green{background:var(--ok-dim)} .ico.violet{background:rgba(163,113,247,.14)}

 .barrow{display:grid;grid-template-columns:120px 1fr 48px;align-items:center;gap:10px;padding:3px 0}
 .barrow .lab{font-size:12.5px;color:var(--ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .bar{height:9px;background:var(--bg2);border-radius:6px;overflow:hidden;border:1px solid var(--line)}
 .bar>i{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,var(--acc2),var(--acc))}
 .barrow .n{text-align:right;font-size:12.5px;font-weight:600}
 .stackbar{display:flex;height:11px;border-radius:6px;overflow:hidden;border:1px solid var(--line);background:var(--bg2)}
 .stackbar i{height:100%} .sb-keep{background:linear-gradient(90deg,#2e9e46,var(--ok))} .sb-xfer{background:linear-gradient(90deg,#c98a06,var(--warn))}

 .taggrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
 .tcell{display:flex;justify-content:space-between;align-items:center;background:var(--bg2);border:1px solid var(--line);border-radius:9px;padding:8px 11px}
 .tcell .tn{font-size:12.5px;color:var(--ink2)} .tcell .tv{font-weight:750;font-variant-numeric:tabular-nums}

 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--line)}
 th{color:var(--mut);font-weight:650;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;position:sticky;top:0;background:var(--panel2)}
 td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
 tbody tr:hover td{background:rgba(255,255,255,.025)}
 .scroll{max-height:320px;overflow:auto;border:1px solid var(--line);border-radius:var(--r2)}

 .field{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px dashed var(--line)}
 .field:last-child{border-bottom:0}
 .field .lab{flex:1} .field .lab b{font-weight:600;font-size:13px} .field .lab .h{display:block;font-size:11px;color:var(--mut);margin-top:1px}
 .field input[type=number]{width:88px;background:var(--bg2);color:var(--ink);border:1px solid var(--line2);border-radius:8px;
   padding:7px 10px;text-align:right;font-variant-numeric:tabular-nums;font-size:13px;transition:border-color .14s,box-shadow .14s}
 .field input:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px var(--acc-dim)}
 .field input.changed{border-color:var(--warn);color:var(--warn)}
 .field input.bad{border-color:var(--bad);box-shadow:0 0 0 3px var(--bad-dim)}
 .seclab{font-size:10.5px;color:var(--acc);text-transform:uppercase;letter-spacing:.08em;font-weight:700;margin:15px 0 4px;display:flex;align-items:center;gap:8px}
 .seclab:first-child{margin-top:2px} .seclab .ln{flex:1;height:1px;background:var(--line)}
 textarea{width:100%;background:var(--bg2);color:var(--ink);border:1px solid var(--line2);border-radius:9px;padding:9px;
   font:12px/1.5 ui-monospace,Consolas,monospace;min-height:40px;resize:vertical;transition:border-color .14s}
 textarea:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px var(--acc-dim)} textarea.bad{border-color:var(--bad)}
 .rost{margin:8px 0} .rost .rh{font-size:12px;font-weight:600} .rost .rhelp{font-size:11px;color:var(--mut);margin:1px 0 3px}

 .sw{position:relative;width:38px;height:22px;flex:none;cursor:pointer}
 .sw input{opacity:0;width:0;height:0;position:absolute}
 .sw .tr{position:absolute;inset:0;background:#2a3340;border:1px solid var(--line2);border-radius:999px;transition:.18s}
 .sw .tr:before{content:"";position:absolute;width:16px;height:16px;left:3px;top:2px;background:#9aa7b6;border-radius:50%;transition:.18s}
 .sw input:checked + .tr{background:var(--acc-dim);border-color:var(--acc)} .sw input:checked + .tr:before{transform:translateX(15px);background:var(--acc)}

 .btn{background:var(--acc2);color:#fff;border:0;border-radius:10px;padding:10px 15px;font:650 13px/1 inherit;cursor:pointer;
   display:inline-flex;align-items:center;gap:7px;transition:transform .06s,filter .14s}
 .btn:hover{filter:brightness(1.12)} .btn:active{transform:translateY(1px)}
 .btn.ghost{background:var(--elev);color:var(--ink);border:1px solid var(--line2)} .btn.ghost:hover{background:#222b3a}
 .btn.warn{background:linear-gradient(180deg,#eab308,#d29005);color:#241a00}
 .btn.ok{background:linear-gradient(180deg,#3fb950,#2e9e46)}
 .btn:disabled{opacity:.45;cursor:not-allowed;filter:none;transform:none}
 .btns{display:flex;flex-wrap:wrap;gap:9px}
 .pillbtn{font-size:11px;padding:7px 11px;border-radius:8px}
 .badge{font-size:10px;font-weight:750;padding:3px 10px;border-radius:999px;background:var(--elev);color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
 .badge.b-run{background:var(--warn-dim);color:var(--warn)} .badge.b-ok{background:var(--ok-dim);color:var(--ok)} .badge.b-bad{background:var(--bad-dim);color:var(--bad)}
 .tag{display:inline-flex;align-items:center;background:var(--elev);border:1px solid var(--line);border-radius:7px;padding:2px 8px;margin:2px 3px 2px 0;font-size:11px;color:var(--ink2)}
 .pos{color:var(--bad);font-weight:650} .neg{color:var(--ok);font-weight:650}
 .note{font-size:12px;color:var(--mut);margin-top:9px;line-height:1.5}
 .msg{font-size:12.5px;margin-top:10px;min-height:16px} .msg.err{color:var(--bad)} .msg.ok{color:var(--ok)}

 .action{display:flex;gap:13px;align-items:flex-start;padding:14px;border:1px solid var(--line);border-radius:var(--r2);background:var(--bg2)}
 .action .meta{flex:1;min-width:0} .action .meta .t{font-weight:700;font-size:13.5px} .action .meta .d{font-size:11.5px;color:var(--mut);margin-top:2px}

 .runwrap{display:grid;grid-template-columns:170px 1fr;border:1px solid var(--line);border-radius:var(--r2);overflow:hidden}
 @media(max-width:520px){.runwrap{grid-template-columns:1fr}}
 .steps{background:var(--bg2);border-right:1px solid var(--line);padding:12px}
 .steps .sh{font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:.07em;font-weight:700;margin-bottom:9px}
 .step{display:flex;align-items:center;gap:8px;padding:5px 0;font-size:12px;color:var(--ink2)}
 .step .si{width:15px;height:15px;border-radius:50%;border:2px solid var(--line2);flex:none;display:grid;place-items:center;font-size:8px}
 .step.ok .si{background:var(--ok);border-color:var(--ok);color:#04210b} .step.ok .si:after{content:"✓"}
 .step.run .si{border-color:var(--warn);border-top-color:transparent;animation:spin .8s linear infinite}
 .step.bad .si{background:var(--bad);border-color:var(--bad);color:#fff} .step.bad .si:after{content:"!"}
 @keyframes spin{to{transform:rotate(360deg)}}
 .logtop{display:flex;align-items:center;gap:10px;padding:9px 13px;background:var(--panel2);border-bottom:1px solid var(--line)}
 .logtop .el{margin-left:auto;font-size:11px;color:var(--mut);font-variant-numeric:tabular-nums}
 .log{background:#05080c;padding:13px;font:12px/1.6 ui-monospace,Consolas,monospace;white-space:pre-wrap;height:330px;overflow:auto;color:#8896a6}
 .log .l-step{color:var(--acc);font-weight:700;display:block;margin:6px 0 1px} .log .l-ok{color:var(--ok)}
 .log .l-bad{color:var(--bad);font-weight:600} .log .l-warn{color:var(--warn)}

 .rulegrid{display:grid;grid-template-columns:1fr 1fr;gap:0 26px}
 @media(max-width:820px){.rulegrid{grid-template-columns:1fr}}
 .rule{display:flex;gap:12px;padding:11px 0;border-bottom:1px solid var(--line)}
 .rule .rn{width:28px;height:28px;border-radius:8px;background:var(--acc-dim);color:var(--acc);display:grid;place-items:center;font-weight:750;flex:none;font-size:12px}
 .rule .rt{font-weight:650;font-size:13px} .rule .rd{font-size:12px;color:var(--ink2);margin-top:2px}
 .rv{font-size:11px;color:var(--bad);background:var(--bad-dim);border-radius:6px;padding:1px 7px;margin-left:6px;font-weight:600}
 .off{opacity:.5} .off .rn{background:var(--bad-dim);color:var(--bad)}

 ::-webkit-scrollbar{width:10px;height:10px} ::-webkit-scrollbar-thumb{background:#2a3340;border-radius:7px;border:2px solid transparent;background-clip:padding-box}
 ::-webkit-scrollbar-thumb:hover{background:#39455a;background-clip:padding-box} ::-webkit-scrollbar-track{background:transparent}
 input[type=text]{background:var(--bg2);color:var(--ink);border:1px solid var(--line2);border-radius:9px;padding:8px 11px;width:200px;font-size:13px}
 input[type=text]:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px var(--acc-dim)}
 .chk{display:inline-flex;gap:6px;align-items:center;color:var(--ink2);font-size:13px;cursor:pointer}
 .kpi.warn .v{color:var(--warn)} .kpi.bad .v{color:var(--bad)}
 #stalebadge{background:var(--warn-dim);color:var(--warn);border:1px solid var(--warn);border-radius:9px;padding:6px 11px;font-size:11.5px;font-weight:700}
 .ghostlink{text-decoration:none;color:var(--ink2);font-weight:650;font-size:12px;border:1px solid var(--line2);border-radius:9px;padding:7px 10px}
 .ghostlink:hover{background:var(--elev)}
 @media(max-width:1100px){header{flex-wrap:wrap;height:auto;padding:8px 22px;row-gap:8px}}
</style></head><body>
<header>
  <div class="brand"><div class="logo">🎮</div><div><h1>Keep Engine</h1><div style="font-size:10.5px;color:var(--mut);margin-top:-1px">Control Center</div></div></div>
  <div class="kpis">
    <div class="kpi"><div class="k">Bag</div><div class="v tnum" id="k-bag">—</div></div>
    <div class="kpi keep"><div class="k">Keep</div><div class="v tnum" id="k-keep">—</div></div>
    <div class="kpi xfer"><div class="k">Transfer</div><div class="v tnum" id="k-xfer">—</div></div>
    <div class="kpi rate"><div class="k">Keep rate</div><div class="v tnum" id="k-rate">—</div></div>
    <div class="kpi" id="kpi-dbage"><div class="k">DB age</div><div class="v tnum" id="k-dbage">—</div></div>
  </div>
  <a href="/studio" style="text-decoration:none;color:var(--acc);font-weight:700;font-size:13px;border:1px solid var(--acc);border-radius:9px;padding:7px 12px">🎯 Curation Studio →</a>
  <a href="/report" class="ghostlink" target="_blank">📊 Line report</a>
  <a href="/plan" class="ghostlink" target="_blank">🗺 Plan</a>
  <div class="spacer"></div>
  <span id="stalebadge" style="display:none" title="dashboard.py or keep_config.py changed on disk after this server started — restart it">⚠ code changed — restart</span>
  <div class="adb" id="adb">adb —</div>
  <div class="jobchip"><span class="dot" id="jdot"></span><span id="jbadge" class="badge">idle</span><button id="b-cancel" class="btn ghost pillbtn" style="display:none;padding:3px 9px;font-size:11px" title="Kill the running job">✕ Cancel</button></div>
</header>
<main>
  <div class="layout">
    <!-- LEFT: control -->
    <div class="col">
      <div class="card" style="order:3">
        <div class="cardhead"><h2>Configuration</h2><span id="dirty" class="badge"></span></div>
        <div id="cfg"></div>
        <div class="btns" style="margin-top:15px"><button class="btn" id="b-preview">⚡ Preview impact</button><button class="btn ok" id="b-save">💾 Save</button></div>
        <div class="btns" style="margin-top:9px">
          <button class="btn ghost pillbtn" id="b-reset">↺ Reset</button>
          <button class="btn ghost pillbtn" id="b-defaults">Defaults</button>
          <button class="btn ghost pillbtn" id="b-export">⭳ Export</button>
          <button class="btn ghost pillbtn" id="b-import">⭱ Import</button>
          <input type="file" id="file" accept="application/json" style="display:none">
        </div>
        <div id="cfgmsg" class="msg"></div>
        <div id="diffwrap" style="display:none"><div class="seclab">Changed from defaults<span class="ln"></span></div><div id="diff"></div></div>
      </div>

      <div class="card" style="order:1">
        <h2>Run &amp; Sync</h2>
        <div style="display:flex;flex-direction:column;gap:10px">
          <div class="action"><div class="ico blue">↻</div><div class="meta"><div class="t">Recrawl</div><div class="d">Walk the bag, rebuild the DB, recompute, pre-flight + audit. <b>Read-only — no tags pushed.</b></div><div class="btns" style="margin-top:8px"><button class="btn pillbtn" id="b-recrawl">Run recrawl</button></div></div></div>
          <div class="action"><div class="ico blue">◉</div><div class="meta"><div class="t">Auto-tag</div><div class="d">Recrawl → recompute (<b>keep_policy</b>) → keeper pre-flight → sync the <b>Transfer</b> tag (adds new ones <i>and</i> prunes stale ones). Same gated engine as Sync — the ungated cull_v9 path was retired 2026-09-02. <b>Tags only — nothing is ever released.</b></div><div class="btns" style="margin-top:8px"><button class="btn pillbtn" id="b-autotag-dry">Dry run</button> <button class="btn pillbtn" id="b-autotag">Auto-tag now</button></div></div></div>
          <div class="action"><div class="ico amber">⇪</div><div class="meta"><div class="t">Sync to phone</div><div class="d">Recompute, then <b>write the Transfer tag (and the rest) to your phone</b> — it never releases anything; you release tagged pokémon in-game yourself. Hard-gated by the keeper pre-flight.</div><div class="btns" style="margin-top:8px"><button class="btn warn pillbtn" id="b-sync">Sync now</button><label class="chk"><input type="checkbox" id="dry"> dry-run</label></div></div></div>
          <div class="action"><div class="ico green">🛡</div><div class="meta"><div class="t">Pre-flight only</div><div class="d">Live keeper safety check (Frida), no sync.</div><div class="btns" style="margin-top:8px"><button class="btn ghost pillbtn" id="b-preflight">Run pre-flight</button></div></div></div>
        </div>
        <div style="margin-top:14px;border-top:1px solid var(--line);padding-top:13px">
          <div class="cardhead" style="margin-bottom:7px"><h3>Dry-run sync preview</h3><button class="btn ghost pillbtn" id="b-tagdiff">↻ Compute diff</button></div>
          <div class="note" style="margin:0 0 9px">What a Sync would <span class="pos">add</span>/<span class="neg">remove</span> on the phone — DB-only, no writes.</div>
          <div id="tagdiff"><div class="mut" style="font-size:12.5px">Click <b>Compute diff</b> to see pending tag changes.</div></div>
        </div>
      </div>

      <div class="card" style="order:2">
        <div class="cardhead"><h2>Job log</h2><div style="display:flex;align-items:center;gap:9px"><span id="jobname" class="mut" style="font-size:12px"></span><span class="dot" id="jdot2"></span><span class="badge" id="jbadge2">idle</span></div></div>
        <div class="runwrap">
          <div class="steps"><div class="sh">Steps</div><div id="steps"><div class="mut" style="font-size:12px">No job running.</div></div></div>
          <div><div class="logtop"><span class="mut" style="font-size:11px">live output</span><span class="el" id="elapsed"></span></div><div class="log" id="log">Run a job to see live, color-coded output here…</div></div>
        </div>
      </div>
    </div>

    <!-- RIGHT: state -->
    <div class="col">
      <div class="grid g-3">
        <div class="card"><div class="stat"><svg id="donut" width="64" height="64" viewBox="0 0 42 42"></svg><div><div class="big" id="o-keep">—</div><div class="sub">kept / <span id="o-bag">—</span></div></div></div></div>
        <div class="card"><div class="stat"><div class="ico amber">📦</div><div><div class="big" id="o-xfer" style="color:var(--warn)">—</div><div class="sub">transfer pile</div></div></div></div>
        <div class="card"><div class="stat"><div class="ico blue">🏷️</div><div><div class="big" id="o-tags" style="color:var(--acc)">—</div><div class="sub">computed tags (next sync)</div></div></div></div>
      </div>
      <div id="changescard" class="card" style="display:none">
        <div class="cardhead"><h2>⟳ What changed</h2>
          <button class="btn ghost pillbtn" id="b-baseline" onclick="setBaseline()" title="Mark the current bag as the reference point — every recrawl after this diffs against it">📌 Set baseline</button></div>
        <div id="changes"></div>
      </div>
      <div id="previewcard" class="card" style="display:none"></div>
      <div class="grid g-2">
        <div class="card"><div class="cardhead"><h2>Keep reasons</h2><span class="mut" id="pr-n" style="font-size:11px"></span></div><div id="perrule"></div></div>
        <div class="card"><h2>Computed tags — next sync</h2><div class="taggrid" id="tags"></div></div>
      </div>
      <div class="card"><h2>By region — keep vs transfer</h2><div id="regions"></div></div>
      <div class="grid g-2">
        <div class="card"><div class="cardhead"><h2>Transfer pile</h2><div style="display:flex;align-items:center;gap:7px"><span id="pilestale" class="badge b-run" style="display:none" title="stale — run Preview or Recrawl to regenerate before trusting this list">⚠ stale</span><span class="badge b-bad" id="pilen">0</span></div></div><div class="scroll"><table id="pile"></table></div></div>
        <div class="card"><h2>Bag search</h2>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
            <input type="text" id="q" placeholder="species or uid…"><label class="chk"><input type="checkbox" id="f-shiny"> shiny</label><label class="chk"><input type="checkbox" id="f-hundo"> hundo</label><button class="btn ghost pillbtn" id="b-search">Search</button><span id="searchn" class="mut" style="font-size:12px"></span>
          </div>
          <div class="scroll" style="max-height:300px"><table id="searchres"></table></div></div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-top:16px">
    <div class="cardhead"><h2>Keep rules — your live policy</h2><span class="mut" style="font-size:11px">values pulled from your config</span></div>
    <div class="rulegrid" id="rules"></div>
  </div>
</main>
<script>
const $=s=>document.querySelector(s);
// hardened: a backend 500 or a dead server used to silently resolve to undefined -> blank UI. Now non-JSON
// throws a readable error the call sites surface (F14). 4xx with {ok:false,error} still parses as JSON.
const api=async(u,o)=>{const r=await fetch(u,o);try{return await r.json();}catch(e){throw new Error('HTTP '+r.status+' — server error (non-JSON). Check the dashboard console or restart it.');}};
let CFG=null,DEF=null,EDIT=null,BOUNDS={cap:{},pvp:{}},BAD=new Set(),polling=false;
const LABELS={plain_line:'Plain · per stage',plain_line_gender:'Plain · per gender (dimorphic)',cosmetic:'Cosmetic variant',dynamax:'Dynamax',gigantamax:'Gigantamax',shiny:'Shiny',rarity:'Legendary / rare',xxl:'XXL · showcase',shadow:'Shadow · top-N IV',ready_rank:'PvP rank ≤',viability_margin:'Min CP over league cap',gl_floor:'GL floor (legacy)',ul_floor:'UL floor (legacy)'};
const HELP={plain_line:'Top-N highest-IV plain per species+stage for BASE and FINAL stages (middle stages use the pre-evo cap) — trade stock + completeness floor. Pattern-pooled lines (Scatterbug/Spewpa/Vivillon) share ONE pool per pattern across the whole line.',cosmetic:'Top-N per costume / event-bg / art / decoration variant.',dynamax:'Top-N Dynamax per species.',gigantamax:'Top-N Gigantamax per species.',shiny:'Top-N shiny per species+form (gym cap; special shinies kept on top).',rarity:'Top-N legendary / mythical / UB / paradox per variant.',xxl:'Top-N XXL by showcase score (weights below).',shadow:'Top-N shadows by IV — plus best GL & best UL shadow always kept.',ready_rank:'Keep GL/UL spreads ranked this good or better for their species.',viability_margin:"A species earns a GL/UL tag only if its strongest possible CP (L50 hundo) beats the league cap by at least this much — filters species too weak to compete.",gl_floor:'Legacy GL CP floor (superseded by the viability margin).',ul_floor:'Legacy UL CP floor (superseded by the viability margin).'};
const RULELABEL={nundo:'Keep all Nundos (0/0/0)',adventure_effect:'Keep Adventure-Effect forms (the form that has the effect)',mighty:'Keep all Mighty',location_card:'Keep all location-card mons',dex_only:'Keep the sole copy of a form'};
const ROSTERHELP={legacy_species_caps:'Per-species legacy-move cap {dex:N}. Species not listed use the default cap below.',rarity_keep_all_pids:'Dex #s exempt from the rarity cap — keep ALL (150 = Mewtwo).',protected_keep_all_pids:'Dex #s to keep EVERY copy of, no caps (172 = Pichu).',adventure_effect_pids:'Adventure-Effect roster — kept regardless.',origin_owners:'Trainer names whose traded/lucky mons you always keep.',showcase_weights:'XXL score weights {height,weight,iv}; Niantic ≈ 0.80/0.15/0.05. Each 0–1.',pvp_spread_keep:'IV spreads always kept as PvP trophies, e.g. [[0,15,15]].'};
const ROSTERS=['legacy_species_caps','rarity_keep_all_pids','protected_keep_all_pids','adventure_effect_pids','origin_owners','showcase_weights','pvp_spread_keep'];

const num=n=>n==null?'—':n.toLocaleString();
const esc=s=>(''+s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

/* ---------- state ---------- */
function donut(keep,total){const r=15.915,p=total?keep/total*100:0;
  return '<circle cx="21" cy="21" r="'+r+'" fill="none" stroke="#222b38" stroke-width="6"/>'+
    '<circle cx="21" cy="21" r="'+r+'" fill="none" stroke="url(#dg)" stroke-width="6" stroke-dasharray="'+p+' '+(100-p)+'" stroke-dashoffset="25" stroke-linecap="round"/>'+
    '<defs><linearGradient id="dg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3fb950"/><stop offset="1" stop-color="#4c9aff"/></linearGradient></defs>'+
    '<text x="21" y="22" text-anchor="middle" font-size="9" font-weight="700" fill="#e8eef6">'+Math.round(p)+'%</text>';}
async function loadState(){try{paintState(await api('/api/state'));}catch(e){const b=$('#jbadge');if(b){b.textContent='offline';b.className='badge b-bad';}}}
function ageTxt(h){if(h==null)return '—';if(h<1)return Math.max(1,Math.round(h*60))+'m';if(h<48)return Math.round(h)+'h';return Math.round(h/24)+'d';}
function paintState(s){
  const rate=s.bag_total?Math.round(s.kept/s.bag_total*100):0;
  $('#k-bag').textContent=num(s.bag_total);$('#k-keep').textContent=num(s.kept);$('#k-xfer').textContent=num(s.transfer);$('#k-rate').textContent=rate+'%';
  // data freshness (F15): how long since the last recrawl wrote pokemon.db -> amber >1h, red >24h
  const h=s.db_mtime?((Date.now()/1000-s.db_mtime)/3600):null;window.__dbAgeH=h;window.__dbAgeTxt=ageTxt(h);
  $('#k-dbage').textContent=ageTxt(h);$('#kpi-dbage').className='kpi'+(h!=null&&h>24?' bad':(h!=null&&h>1?' warn':''));
  $('#adb').textContent='adb '+s.adb_target;
  $('#donut').innerHTML=donut(s.kept,s.bag_total);
  $('#o-keep').textContent=num(s.kept);$('#o-bag').textContent=num(s.bag_total);$('#o-xfer').textContent=num(s.transfer);
  $('#o-tags').textContent=num(Object.values(s.tags).reduce((a,b)=>a+(b||0),0));
  const ent=Object.entries(s.per_rule),mx=Math.max(...ent.map(x=>x[1]),1);$('#pr-n').textContent=ent.length+' reasons';
  $('#perrule').innerHTML=ent.map(([k,v])=>'<div class="barrow"><span class="lab">'+k+'</span><div class="bar"><i style="width:'+(100*v/mx)+'%"></i></div><span class="n">'+num(v)+'</span></div>').join('');
  $('#tags').innerHTML=Object.entries(s.tags).map(([k,v])=>'<div class="tcell"><span class="tn">'+k+'</span><span class="tv">'+(v==null?'—':num(v))+'</span></div>').join('');
  const rmx=Math.max(...s.regions.map(r=>r.total),1);
  $('#regions').innerHTML=s.regions.map(r=>'<div style="margin:9px 0"><div style="display:flex;justify-content:space-between;font-size:12.5px;margin-bottom:3px"><b>'+r.region+'</b><span class="mut">'+num(r.kept)+' keep · <span style="color:var(--warn)">'+num(r.transfer)+' xfer</span> · '+num(r.total)+'</span></div><div class="stackbar" style="width:'+(100*r.total/rmx)+'%"><i class="sb-keep" style="flex:'+r.kept+'"></i><i class="sb-xfer" style="flex:'+r.transfer+'"></i></div></div>').join('');
  $('#pilen').textContent=s.transfer_pile.length;
  $('#pilestale').style.display=s.pile_stale?'':'none';if(s.pile_stale&&s.pile_stale_why)$('#pilestale').title=s.pile_stale_why+' — run Preview or Recrawl to regenerate before trusting this list';
  $('#pile').innerHTML='<tr><th>species</th><th>spread</th><th class="n">iv</th><th class="n">cp</th></tr>'+
    s.transfer_pile.map(m=>'<tr><td>'+(m.shiny?'<span class="shiny">✦</span> ':'')+esc(m.species)+'</td><td class="mut">'+m.spread+'</td><td class="n">'+m.iv+'</td><td class="n">'+num(m.cp)+'</td></tr>').join('');
  renderChanges(s.diff);
}
function renderChanges(d){
  const card=$('#changescard');if(!card)return;
  if(d===undefined)return;                      // preview repaint passes no diff -> leave the card as-is (F21)
  if(!d){card.style.display='none';return;}     // explicit null hides it
  card.style.display='';
  if(!d.any){$('#changes').innerHTML='<div class="mut" style="font-size:12.5px">No changes since the baseline. Run a <b>Recrawl</b> to pull new catches — every delta lands here. Hit <b>📌 Set baseline</b> to reset the reference point to right now.</div>';return;}
  // a GROWING transfer pile is amber (more to tag), not green; bag/keep growth stays green (F21)
  const dc=(lab,v,warnPos)=>v?'<span class="badge '+(warnPos?(v>0?'b-run':'b-ok'):(v>0?'b-ok':'b-bad'))+'" style="font-size:12px">'+lab+' '+(v>0?'+':'')+num(v)+'</span>':'';
  let h='<div style="display:flex;gap:8px;flex-wrap:wrap">'+dc('bag',d.d_bag)+dc('keep',d.d_keep)+dc('transfer',d.d_transfer,true)+'</div>';
  const td=Object.entries(d.tags||{});
  if(td.length)h+='<div class="note" style="margin-top:11px">computed-tag changes</div><div style="margin-top:5px;display:flex;gap:6px;flex-wrap:wrap">'+td.map(([k,v])=>'<span class="tag">'+esc(k)+' '+(v>0?'+':'')+v+'</span>').join('')+'</div>';
  const moreNew=d.pile_new_count>d.pile_new.reduce((a,x)=>a+x[1],0), moreGone=d.pile_gone_count>d.pile_gone.reduce((a,x)=>a+x[1],0);
  if(d.pile_new_count)h+='<div class="note" style="margin-top:11px">newly headed to transfer ('+d.pile_new_count+')</div><div style="margin-top:5px;display:flex;gap:6px;flex-wrap:wrap">'+d.pile_new.map(([sp,n])=>'<span class="tag" style="color:var(--warn)">'+esc(sp)+(n>1?' ×'+n:'')+'</span>').join('')+(moreNew?'<span class="tag">…+ more species</span>':'')+'</div>';
  if(d.pile_gone_count)h+='<div class="note" style="margin-top:11px">pulled back from transfer ('+d.pile_gone_count+')</div><div style="margin-top:5px;display:flex;gap:6px;flex-wrap:wrap">'+d.pile_gone.map(([sp,n])=>'<span class="tag" style="color:var(--ok)">'+esc(sp)+(n>1?' ×'+n:'')+'</span>').join('')+(moreGone?'<span class="tag">…+ more species</span>':'')+'</div>';
  $('#changes').innerHTML=h;
}
async function setBaseline(){const b=$('#b-baseline');if(b)b.disabled=true;try{await api('/api/baseline',{method:'POST'});await loadState();}finally{if(b)b.disabled=false;}}

/* ---------- config ---------- */
function bnd(p){const[a,b]=p.split('.');const t=(a=='caps'?BOUNDS.cap:BOUNDS.pvp)[b];return t?(' min="'+t[0]+'" max="'+t[1]+'"'):'';}
function numField(group,k){const v=EDIT[group][k],ch=v!=CFG[group][k];
  return '<div class="field"><div class="lab"><b>'+(LABELS[k]||k)+'</b><span class="h">'+(HELP[k]||'')+'</span></div><input type="number" step="1"'+bnd(group+'.'+k)+' data-p="'+group+'.'+k+'" class="'+(ch?'changed':'')+'" value="'+v+'"></div>';}
const HIDDEN=new Set(['xxs']);   // engine knob kept in config but never shown in the UI (F04)
function renderCfg(){
  let h='<div class="seclab">Caps · per species / form<span class="ln"></span></div>';
  for(const k of Object.keys(EDIT.caps)){if(HIDDEN.has(k))continue;h+=numField('caps',k);}
  h+='<div class="seclab">PvP<span class="ln"></span></div>';
  for(const k of Object.keys(EDIT.pvp)) h+=numField('pvp',k);
  h+='<div class="seclab">Keep-all rules · switch off to tag excess for transfer<span class="ln"></span></div>';
  for(const k of Object.keys(EDIT.rules||{})){if(HIDDEN.has(k))continue;const on=EDIT.rules[k],ch=on!=(CFG.rules||{})[k];
    h+='<div class="field"><div class="lab"><b>'+(RULELABEL[k]||k)+'</b>'+(ch?' <span class="rv" style="color:var(--warn);background:var(--warn-dim)">edited</span>':'')+'</div><label class="sw"><input type="checkbox" data-rule="'+k+'"'+(on?' checked':'')+'><span class="tr"></span></label></div>';}
  h+='<div class="seclab">Legacy moves<span class="ln"></span></div>';
  const ldc=EDIT.legacy_default_cap,ldcch=ldc!=CFG.legacy_default_cap;
  h+='<div class="field"><div class="lab"><b>Default legacy cap</b><span class="h">Legacy species not listed below. Blank = keep every legacy mon.</span></div><input type="number" step="1" min="0" max="500" id="ldc" placeholder="∞ keep all" class="'+(ldcch?'changed':'')+'" value="'+(ldc==null?'':ldc)+'"></div>';
  h+='<div class="seclab">Rosters &amp; weights (JSON)<span class="ln"></span></div>';
  for(const k of ROSTERS) h+='<div class="rost"><div class="rh">'+k+'</div><div class="rhelp">'+(ROSTERHELP[k]||'')+'</div><textarea data-r="'+k+'">'+esc(JSON.stringify(EDIT[k]))+'</textarea></div>';
  $('#cfg').innerHTML=h;
  $('#cfg').querySelectorAll('input[data-p]').forEach(el=>el.oninput=()=>{
    const p=el.dataset.p,[a,b]=p.split('.'),n=parseInt(el.value,10);
    if(Number.isNaN(n)){BAD.add(p);el.classList.add('bad');return;}
    const t=(a=='caps'?BOUNDS.cap:BOUNDS.pvp)[b];   // block out-of-range as the user types, not only on save (F33)
    if(t&&(n<t[0]||n>t[1])){BAD.add(p);el.classList.add('bad');return;}
    BAD.delete(p);el.classList.remove('bad');EDIT[a][b]=n;el.className=(n!=CFG[a][b]?'changed':'');done();});
  $('#cfg').querySelectorAll('input[data-rule]').forEach(el=>el.onchange=()=>{EDIT.rules[el.dataset.rule]=el.checked;renderCfg();done();});
  $('#ldc').oninput=e=>{const v=e.target.value.trim();if(v===''){EDIT.legacy_default_cap=null;BAD.delete('ldc');e.target.classList.remove('bad');}
    else{const n=parseInt(v,10);if(Number.isNaN(n)||n<0||n>500){BAD.add('ldc');e.target.classList.add('bad');}else{EDIT.legacy_default_cap=n;BAD.delete('ldc');e.target.classList.remove('bad');}}done();};
  $('#cfg').querySelectorAll('textarea[data-r]').forEach(el=>el.oninput=()=>{
    const k=el.dataset.r;try{EDIT[k]=JSON.parse(el.value);BAD.delete(k);el.classList.remove('bad');}catch(e){BAD.add(k);el.classList.add('bad');}done();});
}
function done(){const d=JSON.stringify(EDIT)!=JSON.stringify(CFG);$('#dirty').textContent=d?'edited':'';$('#dirty').className='badge'+(d?' b-run':'');renderDiff();renderRules();}
function renderDiff(){
  const out=[];const walk=(a,b,pre)=>{for(const k in a){const p=pre?pre+'.'+k:k;
    if(a[k]&&typeof a[k]=='object'&&!Array.isArray(a[k]))walk(a[k],(b||{})[k]||{},p);
    else if(JSON.stringify(a[k])!=JSON.stringify((b||{})[k]))out.push([p,(b||{})[k],a[k]]);}};
  walk(EDIT,DEF,'');
  $('#diffwrap').style.display=out.length?'':'none';
  $('#diff').innerHTML=out.map(([p,d,e])=>'<div class="field" style="font-size:12.5px"><div class="lab"><b>'+p+'</b></div><span class="mut">'+esc(JSON.stringify(d))+'</span> <span style="margin:0 6px">→</span> <span style="color:var(--warn);font-weight:600">'+esc(JSON.stringify(e))+'</span></div>').join('');
}
async function loadCfg(){const r=await api('/api/config');CFG=r.config;DEF=r.defaults;BOUNDS={cap:r.cap_bounds||{},pvp:r.pvp_bounds||{}};EDIT=JSON.parse(JSON.stringify(CFG));BAD.clear();renderCfg();done();}

function delta(b,a){const d=a-b;if(!d)return '<span class="mut"> =</span>';return ' <span class="'+(d>0?'pos':'neg')+'">('+(d>0?'+':'')+d+')</span>';}
async function preview(){
  if(BAD.size){msg('fix the highlighted field(s) first',1);return;}
  setBusy(true);msg('recomputing on current DB…');
  try{const r=await api('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(EDIT)});
    if(!r.ok){msg(r.error||'error',1);return;}
    CFG=JSON.parse(JSON.stringify(EDIT));renderCfg();done();msg('applied to config + recomputed — phone NOT touched.',0);
    const pv=$('#previewcard');pv.style.display='';
    let h='<div class="cardhead"><h2>Preview impact</h2><span class="mut" style="font-size:11px">current DB · no phone</span></div><div class="grid g-2">';
    h+='<div class="stat"><div class="ico green">✓</div><div><div class="big" style="color:var(--ok)">'+num(r.after.kept)+'</div><div class="sub">keep'+delta(r.before.kept,r.after.kept)+'</div></div></div>';
    h+='<div class="stat"><div class="ico amber">📦</div><div><div class="big" style="color:var(--warn)">'+num(r.after.transfer)+'</div><div class="sub">transfer'+delta(r.before.transfer,r.after.transfer)+'</div></div></div></div>';
    const keys=new Set([...Object.keys(r.before.per_rule),...Object.keys(r.after.per_rule)]);
    let chips='';for(const k of keys){const b=r.before.per_rule[k]||0,a=r.after.per_rule[k]||0;if(a!=b)chips+='<span class="tag">'+k+' '+b+'→'+a+'</span>';}
    if(chips)h+='<div class="note" style="margin-top:12px">per-rule deltas</div><div style="margin-top:5px">'+chips+'</div>';
    pv.innerHTML=h;paintState(r.after);
  }catch(e){msg(e.message,1);}finally{setBusy(false);}   // surface a 500/dead-server instead of a silent blank (F14)
}
async function saveOnly(){if(BAD.size){msg('fix the highlighted field(s) first',1);return;}
  try{const r=await api('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(EDIT)});
    if(r.ok){CFG=JSON.parse(JSON.stringify(EDIT));renderCfg();done();msg('saved — the next Recrawl / Sync will use it.',0);}else msg(r.error,1);
  }catch(e){msg(e.message,1);}}
const msg=(t,err)=>{const m=$('#cfgmsg');m.textContent=t;m.className='msg'+(err?' err':(err===0?' ok':''));};
function expCfg(){const blob=new Blob([JSON.stringify(EDIT,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='keep_config.json';a.click();URL.revokeObjectURL(a.href);msg('exported keep_config.json',0);}

/* ---------- run / jobs ---------- */
function setBusy(b){['b-recrawl','b-autotag','b-autotag-dry','b-sync','b-preflight','b-preview','b-save','b-tagdiff','b-baseline'].forEach(id=>{const e=$('#'+id);if(e)e.disabled=b;});}
async function jobreq(url,body){try{const r=await api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});if(!r.ok){alert(r.error||'busy');return;}poll();}catch(e){alert(e.message);}}
function fmtLog(t){if(!t||!t.trim())return '<span class="mut">Run a job to see live, color-coded output here…</span>';
  return t.split('\n').map(l=>{const u=l.trim();let c='';
    if(u.startsWith('===')||u.startsWith('####')||u.startsWith('>>'))c='l-step';
    else if(/(FAIL|BLOCKED|ALARM|ABORT|Traceback|Error|error|REAL KEEPER)/.test(l))c='l-bad';
    else if(/(PASS|ALL TARGETS|in sync|\bOK\b|\bdone\b)/.test(l))c='l-ok';
    else if(/(WARN|short=|extra=|not yet equal)/.test(l))c='l-warn';
    return c?'<span class="'+c+'">'+esc(l)+'</span>':esc(l);}).join('\n');}
function renderSteps(log,running,rc){
  const labels=[...log.matchAll(/^=== (.+?) ===$/gm)].map(m=>m[1]);
  if(!labels.length){$('#steps').innerHTML='<div class="mut" style="font-size:12px">'+(running?'starting…':'No job running.')+'</div>';return;}
  $('#steps').innerHTML=labels.map((lab,i)=>{const last=i==labels.length-1,cls=last?(running?'run':(rc===0?'ok':'bad')):'ok';
    return '<div class="step '+cls+'"><span class="si"></span>'+esc(lab.replace(/ \(.*/,'').slice(0,26))+'</div>';}).join('');}
function setJob(j){const st=j.running?'run':(j.rc===0?'ok':(j.rc==null?'':'bad'));
  ['jbadge','jbadge2'].forEach(id=>{const e=$('#'+id);if(e){e.textContent=j.status||'idle';e.className='badge'+(st?' b-'+st:'');}});
  ['jdot','jdot2'].forEach(id=>{const e=$('#'+id);if(e)e.className='dot'+(st?' d-'+st:'');});
  $('#jobname').textContent=j.name?('· '+j.name):'';
  $('#elapsed').textContent=j.elapsed?(j.elapsed+'s'):'';
  // stick-to-bottom only if already near the bottom, so a user scrolled up to read mid-job isn't yanked back (F31)
  const lg=$('#log'),stick=lg.scrollHeight-lg.scrollTop-lg.clientHeight<24;
  lg.innerHTML=fmtLog(j.log);if(stick)lg.scrollTop=lg.scrollHeight;
  const cb=$('#b-cancel');if(cb)cb.style.display=j.running?'':'none';   // Cancel only while a job runs (F16)
  renderSteps(j.log||'',j.running,j.rc);}
let _wasRunning=false,_tick=0;
async function poll(){if(polling)return;polling=true;   // runs FOREVER -> the dashboard always mirrors job state,
  setInterval(async()=>{
    let j;
    try{j=await api('/api/job');}catch(e){const b=$('#jbadge'),b2=$('#jbadge2');[b,b2].forEach(x=>{if(x){x.textContent='offline';x.className='badge b-bad';}});['jdot','jdot2'].forEach(id=>{const e=$('#'+id);if(e)e.className='dot d-bad';});return;}
    setJob(j);setBusy(j.running||!!j.busy);   // even a job triggered outside this tab
    if(_wasRunning&&!j.running)loadState();   // a job just finished -> refresh the snapshot once
    _wasRunning=j.running;
    if((_tick++ % 50)===0){loadState();        // keep the DB-age live; check for on-disk code staleness (F15)
      try{const hp=await api('/api/health');const st=hp.src_stale&&Object.values(hp.src_stale).some(Boolean);const sb=$('#stalebadge');if(sb)sb.style.display=st?'':'none';}catch(e){}}
  },1200);}
async function tagdiff(){setBusy(true);$('#tagdiff').innerHTML='<div class="mut" style="font-size:12.5px">recomputing + diffing…</div>';
  try{const r=await api('/api/tagdiff');if(!r.ok){$('#tagdiff').innerHTML='<div class="msg err">'+(r.error||'error')+'</div>';return;}
    const ch=r.tags.filter(t=>t.add||t.remove);
    let h='<div style="display:flex;gap:8px;margin-bottom:10px"><span class="badge b-ok">+'+r.total_add+' add</span><span class="badge b-bad">−'+r.total_remove+' remove</span>'+(ch.length?'':' <span class="mut" style="font-size:12px;align-self:center">— phone already in sync</span>')+'</div>';
    if(ch.length){h+='<table><tr><th>tag</th><th class="n">add</th><th class="n">remove</th><th class="n">→ total</th></tr>';
      for(const t of ch)h+='<tr><td>'+esc(t.tag)+'<div class="mut" style="font-size:10.5px">'+[...t.add_sample.map(x=>'+'+esc(x)),...t.remove_sample.map(x=>'−'+esc(x))].slice(0,5).join(', ')+'</div></td><td class="n">'+(t.add?'<span class="pos">+'+t.add+'</span>':'·')+'</td><td class="n">'+(t.remove?'<span class="neg">−'+t.remove+'</span>':'·')+'</td><td class="n">'+t.computed+'</td></tr>';
      h+='</table>';}
    if(r.untracked&&r.untracked.length)h+='<div class="note" style="margin-top:9px">untouched personal tags: '+r.untracked.map(u=>esc(u.tag)+' ('+u.server+')').join(', ')+'</div>';   // F28
    $('#tagdiff').innerHTML=h;}catch(e){$('#tagdiff').innerHTML='<div class="msg err">'+esc(e.message)+'</div>';}finally{setBusy(false);}}

/* ---------- rules explainer ---------- */
function renderRules(){const c=EDIT||CFG;if(!c)return;const cap=k=>c.caps[k],pv=k=>c.pvp[k],on=k=>(c.rules||{})[k]!==false;
  const R=[
   [1,'Variant floor',true,'Top-'+cap('plain_line')+' highest-IV plain per species &amp; stage; each cosmetic variant keeps its own top-'+cap('cosmetic')+' (Dynamax '+cap('dynamax')+', Gmax '+cap('gigantamax')+'). Any higher-IV special (shiny or cosmetic) takes a plain slot; a shiny also takes a slot in its own cosmetic variant; gender-evolver lines are capped per gender. Pattern-pooled lines (Scatterbug/Spewpa/Vivillon): ONE top-'+cap('plain_line')+' pool per pattern across the whole line.'],
   [2,'Shadow',true,'Top-'+cap('shadow')+' shadow by IV per species, plus the best GL and best UL shadow -- each only while that rank is inside pvp.shadow_rank_floor.'],
   [3,'Shiny',true,'Top-'+cap('shiny')+' shiny per species+form, at most '+cap('shiny_plain')+' of them plain (a plain one under the shiny floor takes no slot unless it is the form\'s best); a richer shiny (bg/costume/Dmax/Gmax) outranks at the cap margin, but shinies are NEVER collapsed by richer copies — collapse goes up, not down (2026-06-10).'],
   [4,'Hundo',true,'Every 15/15/15, always.'],
   [5,'Legendary / rare',true,'Top-'+cap('rarity')+' per legendary/mythical/UB/paradox variant (keep-all: dex '+(((c.rarity_keep_all_pids||[]).join(', '))||'none')+'), plus best GL &amp; UL. Any copy at or above '+(c.rarity_floor_iv||37)+'/45 (3 stars) is kept regardless of the cap.'],
   [6,'Legacy moves',true,'Keep all legacy-move mons'+(c.legacy_default_cap==null?'':' (default cap '+c.legacy_default_cap+')')+'; per-species overrides apply. Specials + best GL/UL protected first.'],
   [7,'XXL showcase',true,'Top-'+cap('xxl')+' XXL by showcase score (h '+Math.round(c.showcase_weights.height*100)+'% / w '+Math.round(c.showcase_weights.weight*100)+'% / IV '+Math.round(c.showcase_weights.iv*100)+'%).'],
   [8,'Nundo',on('nundo'),'Every 0/0/0.'],
   [9,'Adventure-Effect',on('adventure_effect'),'Every copy of a FORM that has an Adventure Effect (Origin Dialga/Palkia, Black/White Kyurem, Crowned Zacian/Zamazenta, Dusk Mane/Dawn Wings Necrozma, Eternatus), kept regardless. Base forms are ordinary legendaries (rarity cap).'],
   [10,'Origin (E+F)',true,'Traded/lucky from your trusted trainers — not switchable.'],
   [11,'Mighty',on('mighty'),'Every Mighty (L40+ elite spread).'],
   [12,'Location card',on('location_card'),'Every mon carrying a location postcard.'],
   [13,'Protected',true,'Every copy of your protected dex #s (e.g. Pichu) — not switchable.'],
   [14,'Dex completeness',on('dex_only'),'The sole copy of any (species, form).'],
   [15,'PvP rank + trophy',true,'Any GL/UL spread ranked ≤ '+pv('ready_rank')+' for a CP-viable form (margin '+pv('viability_margin')+'), plus trophy spreads '+JSON.stringify(c.pvp_spread_keep)+'.'],
   [17,'Best GL / UL copy',true,'The single best Great League and best Ultra League copy of every species AND of every species+form, among non-shadow copies. Every form, card, background, costume and shiny competes; a stage that can reach the league cap ranks first. Tagged Best GL / Best UL. Shadows keep their own best GL/UL (rule 2).'],
   [16,'Dominance collapse',true,'Only TRUE PLAINS (no shiny / costume / bg / Dmax / Gmax / shadow attribute) collapse — a plain kept only by the variant floor is dropped when a strictly richer same-gender sibling exists at strictly higher IV. Every special is limited by its own cap ONLY; hundos and all hard axes are immune. Collapse goes up, never down (2026-06-10).'],
  ];
  $('#rules').innerHTML=R.map(([n,t,en,d])=>'<div class="rule'+(en?'':' off')+'"><div class="rn">'+n+'</div><div><div class="rt">'+t+(en?'':' <span class="rv">off</span>')+'</div><div class="rd">'+d+'</div></div></div>').join('');}

/* ---------- search ---------- */
async function search(){const q=encodeURIComponent($('#q').value),s=$('#f-shiny').checked?'&shiny=1':'',hu=$('#f-hundo').checked?'&hundo=1':'';
  const r=await api('/api/search?q='+q+s+hu);$('#searchn').textContent=r.count+' match'+(r.count==1?'':'es')+(r.count>=500?' (capped)':'');
  if(r.error){$('#searchres').innerHTML='';$('#searchn').textContent=r.error;return;}   // don't render rows as TRANSFER on a torn read (F23)
  $('#searchres').innerHTML='<tr><th>species</th><th>spread</th><th class="n">iv</th><th class="n">cp</th><th>kept for</th></tr>'+
    r.rows.map(m=>'<tr><td>'+(m.shiny?'<span class="shiny">✦</span> ':'')+esc(m.species)+(m.variant?' <span class="mut" style="font-size:11px">— '+esc(m.variant)+'</span>':'')+'</td><td class="mut">'+m.spread+'</td><td class="n">'+m.iv+'</td><td class="n">'+num(m.cp)+'</td><td>'+m.reasons.map(x=>'<span class="tag">'+esc(x)+'</span>').join('')+'</td></tr>').join('');}

/* ---------- wire ---------- */
$('#b-preview').onclick=preview;$('#b-save').onclick=saveOnly;
$('#b-reset').onclick=()=>{EDIT=JSON.parse(JSON.stringify(CFG));BAD.clear();renderCfg();done();msg('');};
$('#b-defaults').onclick=()=>{EDIT=JSON.parse(JSON.stringify(DEF));BAD.clear();renderCfg();done();msg('reverted to shipped defaults (not saved).',0);};
$('#b-export').onclick=expCfg;
$('#b-import').onclick=()=>$('#file').click();
$('#file').onchange=e=>{const f=e.target.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>{try{const o=JSON.parse(rd.result);EDIT=JSON.parse(JSON.stringify(o));BAD.clear();renderCfg();done();msg('imported — review, then Preview or Save.',0);}catch(x){msg('not valid JSON',1);}};rd.readAsText(f);e.target.value='';};
$('#b-recrawl').onclick=()=>{if(confirm('Recrawl the phone? (full walk + recompute — no tags pushed)'))jobreq('/api/recrawl');};
$('#b-autotag-dry').onclick=()=>jobreq('/api/autotag',{dry:true});
$('#b-autotag').onclick=()=>{if(confirm('Auto-tag now?\n\nRecrawls, recomputes with keep_policy, runs the keeper pre-flight, then syncs the Transfer tag (add + prune).\nSame gated engine as Sync.\n\nNOTHING is released.'))jobreq('/api/autotag');};
$('#b-sync').onclick=()=>{const age=(window.__dbAgeH>1)?('DB last crawled '+window.__dbAgeTxt+' ago — consider Recrawl first.\n\n'):'';
  const m=$('#dry').checked?'Dry-run sync? Computes the diff only — NOTHING is written to the phone.':'Sync tags to the phone? This writes the Transfer tag (and the rest); it never releases pokémon — you release tagged ones in-game yourself. The keeper pre-flight gates the push.';
  if(confirm(age+m))jobreq('/api/sync',{dry:$('#dry').checked});};
$('#b-preflight').onclick=()=>jobreq('/api/preflight');
$('#b-cancel').onclick=()=>{if(confirm('Kill the running job? A mid-write step may leave staging incomplete (the next Recrawl heals it), and a killed Frida session can need the freezer-fix before the next job.'))jobreq('/api/cancel');};
$('#b-tagdiff').onclick=tagdiff;
$('#b-search').onclick=search;$('#q').addEventListener('keydown',e=>{if(e.key=='Enter')search();});
loadCfg();loadState();poll();
</script></body></html>"""


STUDIO_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Curation Studio</title>
<style>
 :root{--bg:#0a0e14;--panel:#11161f;--panel2:#161c27;--bg2:#070a0f;--elev:#1b2230;--ink:#e8eef6;--ink2:#aeb9c7;--mut:#6e7b8c;--line:#222b38;--line2:#2c3645;--acc:#4c9aff;--acc2:#2b6fe0;--acc-dim:rgba(76,154,255,.14);--ok:#3fb950;--warn:#e3a008;--warn-dim:rgba(227,160,8,.16);--bad:#f7544b;--bad-dim:rgba(247,84,75,.16);--purple:#a371f7;--shiny:#f5c518;--r:14px;--sh:0 1px 2px rgba(0,0,0,.4),0 8px 24px -12px rgba(0,0,0,.6)}
 *{box-sizing:border-box}html,body{margin:0}
 body{background:radial-gradient(1200px 600px at 80% -10%,#0e1722,transparent),var(--bg);color:var(--ink);font:14px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
 a{color:var(--acc);text-decoration:none}.mut{color:var(--mut)}
 header{display:flex;align-items:center;gap:13px;padding:0 22px;height:58px;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:30;background:rgba(10,14,20,.92);backdrop-filter:blur(14px)}
 .logo{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--acc),var(--purple));display:grid;place-items:center;font-size:16px}
 h1{font-size:16px;margin:0;font-weight:750}
 .tabs{display:flex;gap:4px;flex-wrap:wrap;margin-left:6px}
 .tab{background:var(--panel);border:1px solid var(--line);color:var(--ink2);border-radius:999px;padding:6px 13px;font:600 12.5px/1 inherit;cursor:pointer}
 .tab.on{background:var(--acc-dim);border-color:var(--acc);color:var(--acc)}.tab .n{opacity:.55;margin-left:5px}
 .spacer{flex:1}.btn{background:var(--acc2);color:#fff;border:0;border-radius:10px;padding:10px 16px;font:650 13px/1 inherit;cursor:pointer;display:inline-flex;gap:7px;align-items:center}.btn:hover{filter:brightness(1.12)}.btn.ghost{background:var(--elev);border:1px solid var(--line2);color:var(--ink)}
 main{max-width:1440px;margin:0 auto;padding:18px}
 .toolbar{display:flex;align-items:center;gap:18px;flex-wrap:wrap;background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:var(--r);padding:15px 18px;margin-bottom:14px;position:sticky;top:58px;z-index:20;box-shadow:var(--sh)}
 .toolbar h2{margin:0;font-size:17px;font-weight:750}
 .capctl{display:flex;align-items:center;gap:10px}.capctl label{font-size:12px;color:var(--mut)}
 input[type=range]{width:170px;accent-color:var(--acc)}
 .capnum{width:52px;background:var(--bg2);color:var(--ink);border:1px solid var(--line2);border-radius:8px;padding:6px 8px;text-align:center;font-weight:700;font-variant-numeric:tabular-nums}
 .rel b{color:var(--bad);font-size:20px}.keepn b{color:var(--ok)}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
 .sp{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:var(--r);padding:14px;box-shadow:var(--sh)}
 .sphead{display:flex;align-items:center;gap:11px;margin-bottom:9px}
 .sphead img{width:46px;height:46px;border-radius:10px;background:var(--bg2);object-fit:contain;flex:none}
 .sphead .nm{font-weight:750;font-size:14.5px}.sphead .sub{font-size:11.5px;color:var(--mut)}
 .scap{margin-left:auto;font-size:11px;color:var(--mut);display:flex;align-items:center;gap:5px}
 .mons{display:flex;flex-direction:column;gap:5px;max-height:340px;overflow:auto}
 .mon{display:flex;align-items:center;gap:8px;padding:6px 9px;border-radius:8px;background:var(--bg2);border:1px solid var(--line);font-size:12.5px}
 .mon.rel{background:var(--bad-dim);border-color:var(--bad)}.mon.prot{background:var(--warn-dim);border-color:rgba(227,160,8,.4)}
 .mon .iv{font-weight:750;width:40px}.mon .spread{color:var(--mut);font-variant-numeric:tabular-nums}.mon .cp{margin-left:auto;color:var(--ink2);font-variant-numeric:tabular-nums}
 .b{display:inline-block;background:var(--elev);border:1px solid var(--line);border-radius:5px;padding:1px 6px;margin-left:3px;font-size:10px;color:var(--ink2)}
 .b.Shiny{color:var(--shiny)}.b.Hundo{color:var(--ok)}.b.Gmax,.b.Dmax{color:var(--purple)}
 .tag{font-size:10.5px;color:var(--warn);margin-left:6px}.relpill{font-size:10px;color:#fff;background:var(--bad);border-radius:5px;padding:1px 6px;margin-left:6px;font-weight:700}
 .capline{height:0;border-top:1px dashed var(--acc);margin:3px 0;position:relative}.capline span{position:absolute;right:0;top:-8px;font-size:9px;color:var(--acc);background:var(--panel2);padding:0 5px}
 .toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--elev);border:1px solid var(--line2);border-radius:10px;padding:12px 18px;box-shadow:var(--sh);font-size:13px;z-index:50;display:none;max-width:560px}
 .note{font-size:12px;color:var(--mut);line-height:1.55}
 ::-webkit-scrollbar{width:9px;height:9px}::-webkit-scrollbar-thumb{background:#2a3340;border-radius:7px}
</style></head><body>
<header><div class="logo">🎯</div><h1>Curation Studio</h1><div class="tabs" id="tabs"></div><div class="spacer"></div><a class="btn ghost" href="/">← Dashboard</a></header>
<main>
 <div class="toolbar" id="toolbar" style="display:none">
   <h2 id="t-label"></h2>
   <div class="capctl"><label>Keep top</label><input type="range" id="gcap" min="0" max="50"><input type="number" id="gcapn" class="capnum" min="0" max="50"><span class="mut" style="font-size:12px">of each species</span></div>
   <div class="rel">Tag for transfer <b id="reln">0</b> <span class="mut">· keep <span class="keepn"><b id="keepn">0</b></span></span></div>
   <div class="spacer"></div>
   <button class="btn" id="apply">✓ Apply caps</button>
 </div>
 <div class="note" id="hint" style="margin-bottom:12px;display:none">Set <b>Keep top N</b> for the whole category, or override any single species with its own box. Highest IV is kept first. <span style="color:var(--bad)">Red</span> = tagged for transfer; <span style="color:var(--warn)">amber 🔒</span> = protected by another reason, stays. After <b>Apply caps</b>, run <b>Recrawl → Sync</b> on the dashboard to tag them for transfer — you release them in-game yourself.</div>
 <div class="grid" id="grid"></div>
</main>
<div class="toast" id="toast"></div>
<script>
const $=s=>document.querySelector(s);
const api=async(u,o)=>{const r=await fetch(u,o);try{return await r.json();}catch(e){throw new Error('HTTP '+r.status+' — server error');}};
const esc=s=>(''+s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let CDN='',ST={cat:null,data:null,gcap:0,scaps:{},touched:false};
const sprite=(pid,form)=>'/api/studio/sprite/'+pid+(form?('?form='+form):'');
// staged sprite fallback (F36): local API art -> CDN pokemon_icon -> inline pokeball, so a newer dex#
// with no asset shows a placeholder instead of a broken image
const PLACEHOLDER='data:image/svg+xml;utf8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="46" height="46"><circle cx="23" cy="23" r="20" fill="#1b2230" stroke="#2c3645"/><path d="M3 23h40" stroke="#2c3645" stroke-width="3"/><circle cx="23" cy="23" r="6" fill="#11161f" stroke="#2c3645" stroke-width="3"/></svg>');
function spErr(img,pid){const st=img.dataset.st||'0';if(st==='0'){img.dataset.st='1';img.src=CDN+'pokemon_icon_'+String(pid).padStart(3,'0')+'_00.png';}else{img.onerror=null;img.src=PLACEHOLDER;}}
async function boot(){const r=await api('/api/studio/categories');CDN=r.sprite_cdn||'';
  $('#tabs').innerHTML=r.categories.map(c=>'<button class="tab" data-c="'+c.key+'">'+esc(c.label)+'<span class="n">'+c.count+'</span></button>').join('');
  document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>pick(b.dataset.c));
  if(r.categories[0])pick(r.categories[0].key);}
async function pick(cat){ST.cat=cat;document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('on',b.dataset.c==cat));
  $('#grid').innerHTML='<div class="mut" style="padding:20px">Loading…</div>';
  let d;try{d=await api('/api/studio/category/'+cat);}catch(e){$('#grid').innerHTML='<div class="msg err" style="padding:20px">'+esc(e.message)+'</div>';return;}
  if(ST.cat!==cat)return;   // a slower earlier tab's response must not overwrite the current one (F30)
  ST.data=d;ST.gcap=d.global_cap;ST.scaps=Object.assign({},d.per_species||{});ST.touched=false;   // show SAVED per-species overrides (F03); fresh truth (F02)
  $('#toolbar').style.display='';$('#hint').style.display='';$('#t-label').textContent=d.label;
  $('#hint').innerHTML='<b style="color:var(--ink)">'+esc(d.protected_note||'')+'</b><br><span style="color:var(--bad)">Red</span> = tagged for transfer on the next sync · <span style="color:var(--warn)">amber 🔒</span> = protected by another reason, always stays. After <b>Apply caps</b>, run <b>Recrawl → Sync</b> on the dashboard to TAG them for transfer (the keeper pre-flight gates every push) — you release tagged pokémon in-game yourself.';
  $('#gcap').max=mxCap();$('#gcapn').max=mxCap();   // shiny/rarity sliders reach 200, not 50 (F26)
  $('#gcap').value=d.global_cap;$('#gcapn').value=d.global_cap;render();}
const mxCap=()=>(ST.cat==='shiny'||ST.cat==='rarity')?200:50;   // shiny/rarity bounds reach 200 (F26)
const effCap=pid=>ST.scaps[pid]!=null?ST.scaps[pid]:ST.gcap;
function render(){const d=ST.data;let rel=0,keep=0,h='';
  for(const s of d.species){const cap=effCap(s.pid);let mh='';
    s.mons.forEach((m,i)=>{const over=i>=cap;
      // UNTOUCHED = engine truth (in_transfer from policy_reasons.json); TOUCHED = a what-if estimate at the
      // proposed cap (the engine hasn't re-run yet). Never let "safe" contradict an empty reason set (F02).
      let can,prot;
      if(!ST.touched){can=m.in_transfer;prot=!can&&over&&m.protected_by.length;}
      else{can=over&&!m.protected_by.length;prot=over&&m.protected_by.length;}
      if(can)rel++;else keep++;
      const pill=can?(ST.touched?'<span class="relpill" title="over the proposed cap — the engine decides on Recrawl">→ est. transfer</span>':'<span class="relpill">→ transfer tag</span>'):(prot?'<span class="tag">🔒 '+esc(m.protected_by[0])+'</span>':'');
      mh+=(i===cap&&i>0&&i<s.mons.length?'<div class="capline"><span>keep '+cap+'</span></div>':'')+
        '<div class="mon '+(can?'rel':prot?'prot':'')+'"><span class="iv">'+Math.round(m.iv/45*100)+'%</span><span class="spread">'+m.atk+'/'+m['def']+'/'+m.sta+'</span>'+
        m.badges.map(b=>'<span class="b '+b.split(' ')[0]+'">'+esc(b)+'</span>').join('')+
        '<span class="cp">CP '+(m.cp||'?')+'</span>'+pill+'</div>';});
    const ov=(ST.scaps[s.pid]!=null&&ST.scaps[s.pid]!=ST.gcap);   // per-species override active (F03)
    h+='<div class="sp"><div class="sphead"><img loading="lazy" src="'+sprite(s.pid,s.mons[0].form)+'" data-st="0" onerror="spErr(this,'+s.pid+')" alt=""><div><div class="nm">'+esc(s.name)+(s.variant?' <span style="font-weight:400;color:var(--mut);font-size:12px">- '+esc(s.variant)+'</span>':'')+'</div><div class="sub">'+s.count+' total · keeping '+Math.min(cap,s.count)+'</div></div><div class="scap">keep <input type="number" class="capnum" style="width:46px'+(ov?';border-color:var(--acc);color:var(--acc)':'')+'" min="0" max="'+mxCap()+'" value="'+cap+'" data-pid="'+s.pid+'"'+(ov?' title="per-species override (clear to use the category cap)"':'')+'></div></div><div class="mons">'+mh+'</div></div>';}
  $('#grid').innerHTML=h;$('#reln').textContent=rel;$('#keepn').textContent=keep;
  $('#grid').querySelectorAll('input[data-pid]').forEach(el=>el.oninput=()=>{const v=el.value.trim();ST.scaps[el.dataset.pid]=v===''?null:Math.max(0,parseInt(v,10)||0);ST.touched=true;
    const pid=el.dataset.pid;render();const n=$('#grid').querySelector('input[data-pid="'+pid+'"]');if(n){n.focus();const L=n.value.length;try{n.setSelectionRange(L,L);}catch(e){}}});}   // re-focus the rebuilt input (F32)
let _raf;
$('#gcap').oninput=()=>{ST.gcap=+$('#gcap').value;$('#gcapn').value=ST.gcap;ST.touched=true;cancelAnimationFrame(_raf);_raf=requestAnimationFrame(render);};   // debounce the full-grid rebuild (F32)
$('#gcapn').oninput=()=>{ST.gcap=Math.max(0,Math.min(mxCap(),parseInt($('#gcapn').value,10)||0));$('#gcap').value=ST.gcap;ST.touched=true;cancelAnimationFrame(_raf);_raf=requestAnimationFrame(render);};
const toast=t=>{const e=$('#toast');e.textContent=t;e.style.display='block';setTimeout(()=>e.style.display='none',5000);};
$('#apply').onclick=async()=>{
  // send explicit nulls for cleared overrides so the backend pop actually removes them (F03)
  const sc={},saved=ST.data.per_species||{};
  for(const k of new Set([...Object.keys(ST.scaps),...Object.keys(saved)])){const v=ST.scaps[k];
    if(v!=null&&v!=ST.gcap)sc[k]=v;else if(saved[k]!=null)sc[k]=null;}
  try{const r=await api('/api/studio/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cat:ST.cat,global_cap:ST.gcap,species_caps:sc})});
    toast(r.ok?'✓ Caps saved. Now run Recrawl → Sync on the dashboard to TAG the excess for transfer — the keeper pre-flight gates every push; you release them in-game yourself.':'⚠ '+(r.error||'error'));}
  catch(e){toast('⚠ '+e.message);}};
boot().catch(e=>{$('#grid').innerHTML='<div class="msg err" style="padding:20px">'+esc(e.message)+'</div>';});
</script></body></html>"""


if __name__ == '__main__':
    print('PoGo Keep Dashboard -> http://127.0.0.1:%d   (Ctrl-C to stop)' % PORT)
    # bind all interfaces so the PHONE can reach it over Tailscale; _tailnet_guard below still
    # rejects anything that is not loopback or a 100.64.0.0/10 tailnet peer, so the LAN cannot touch it.
    app.run(host='0.0.0.0', port=PORT, threaded=True, debug=False)
