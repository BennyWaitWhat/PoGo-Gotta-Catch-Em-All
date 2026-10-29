"""audit_invariants.py -- READ-ONLY STRUCTURAL invariant harness for the keep engine.

WHY THIS FILE EXISTS
====================
Every audit that already exists checks a RESULT: "is this pile keeper-free", "does this tag's
membership match its rule", "can every piled mon be explained". They are re-derivations, and they
are excellent at catching a wrong ANSWER. They are structurally incapable of catching a wrong
QUESTION -- an axis that one file models as a cap and another models as keep-all, a column read
that nothing writes, a stale enum that silently reclassifies a costume as plain. Those bugs have
been surfacing here ONE AT A TIME, each found only after it nearly cost a real keeper:

    capped-axis-modelled-as-keep-all (or the reverse):
        costume bucket / XXL / Dynamax / Gigantamax / shiny floor-displacement /
        Unown carve-out / shadow / rarity-skips-shiny (2026-09-02)
    data bugs of the same family:
        special_bg_id  -- a garbage column with NO writer, read at 4 engine sites
        form_enum.json -- stale since 2026-06-04, so brand-new costume forms judged PLAIN
                          and SEVEN reached the irreversible pile

This harness asserts the STRUCTURE those bugs violated, so the class cannot return silently. It
never re-derives a keep set (that is the other four audits' job); it asserts that the MODEL is
coherent across every consumer, that every input is current, that missing data leans PROTECTED,
that every column read has a writer, that the pile partitions the bag, and that exactly one
gated code path can push tags.

WHAT IT ASSERTS
===============
  I1  AXIS CONSISTENCY  every keep axis is modelled the same way (capped vs keep-all) by every
                        consumer; every cap comes from keep_config.cap()/species_cap(), never a
                        literal; every axis is re-derived by at least one independent consumer.
  I2  STALENESS         max live form id <= form_enum max; the gamemaster resolves every live
                        (species,form); the dex walk covers the bag; the pile's provenance stamp
                        matches the live config and database; no input is newer than the pile.
  I3  NULL DIRECTION    no engine-read column turns a NULL into the UNPROTECTED value without
                        either rule-0 coverage or a written exemption whose premise is re-checked
                        here; no pile producer reads a legacy column that has a fresh_* twin, or a
                        retired one.
  I4  NO-WRITER COLS    no engine-read column lacks a writer in the sanctioned pipeline
                        (the special_bg_id pattern).
  I5  PARTITION         policy_reasons + Transfer is an exact partition of in_bag, zero overlap,
                        no strays, every emitted reason declared, no keep tag holding a pile member.
  I6  SINGLE PUSH PATH  exactly one gated path from a pile to the phone, and the dashboard's gate
                        still precedes its push in every job.
  I7  STAT-LINE FIDELITY  every (species,form) in the bag reproduces its OWN STORED CP under the
                        speciesId the live ranker maps it to. CP is a pure function of base stats,
                        IVs and CPM, so the game itself signs off on every mapping decision: a pair
                        that reconstructs under a DIFFERENT speciesId is a silently wrong rank
                        feeding the irreversible pile. Also: one species map and one CPM ladder
                        across both rankers, and the Mudbray assertion -- a mon whose species did
                        not resolve carries NULL ranks, and a NULL-rank mon must be PROTECTED and
                        out of the pile, never read as "no protection".
  I8  TAG VOCABULARY    (2026-09-26; the fold 2026-09-29) every managed tag name is <= 18 characters,
                        a legal Windows filename, and reads back to itself through the DB mirror;
                        ONE evolve-advice table (evolve_advice.json) equals the five evolve tag
                        files exactly, every row a kept, unfused mon tagged by its own fields
                        (Evolve Once / Twice / Gated + Evolve for GL / UL), each Once / Twice count
                        confirmed by the client game master; the fold's retired names (Evolve
                        Next, every Stop tag, Evolve Shiny, Evolve for Size ...) stay retired and
                        off disk; the advice tags sit on kept mons only and never contradict each
                        other; no post-tags path pushes Evolve for Size; the remote-trade stamp
                        and retire_tags' grace clock are written the safe way round.

CONTRACT
========
* READ-ONLY. No adb, no frida, no device, no network, no dashboard API. Writes NOTHING -- not even
  a cache file. Safe to run while the user is mid-transfer on the phone. (Verified 2026-09-02 by
  hashing all 448 project artifacts around a run: zero changed, zero created. Re-verified
  2026-09-03 across all 11,549 files in the tree: the ONE thing a run touches is
  pokemon.db-shm, SQLite's shared-memory INDEX for a WAL database, which every reader of a WAL
  db updates simply by opening it -- pokemon.db and pokemon.db-wal are byte-identical across a
  run. Stated out loud rather than left as a rounding error, because "writes NOTHING" is a
  claim the user relies on when running this mid-transfer.)
* Exit 0  -> prints 'VERDICT: ALL STRUCTURAL INVARIANTS HOLD'  (the needle full_audit greps).
* Exit 1  -> at least one BLOCK-level violation. Every violation prints a 'DO:' line.
* Exit 2  -> the harness itself could not run (a missing input it cannot check around).

SEVERITY, and why there are two
-------------------------------
BLOCK  a breach that can put a keeper in the irreversible pile, or push a pile nothing verified.
WARN   a real breach whose harm is currently blocked by a compensating guard IN THE CODE, or whose
       only direction is over-keeping. Printed loudly, does not fail the gate.
This is not grade inflation. Every WARN below names the exact guard that holds it down, the harness
CHECKS that guard is still present, and a WARN auto-promotes to BLOCK the moment the guard
disappears or the live config makes it bite (e.g. a per-species cosmetic cap being added). A gate
that cries wolf gets bypassed, and this one sits directly in front of the sync.
"""
import ast
import atexit
import functools
import hashlib
import io
import json
import math
import os
import pickle
import re
import sqlite3
import sys
import time
import tokenize
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))

DB = os.path.join(ROOT, 'pokemon.db')
SCR = os.path.join(ROOT, 'system', 'scripts')
ANA = os.path.join(ROOT, 'system', 'analysis')
TD = os.path.join(ANA, 'tagsets')

BLOCK, WARN = 'BLOCK', 'WARN'
_FINDINGS = []          # (severity, invariant-id, message, DO-line)
_SECTION = ['?']


def section(sid, title):
    _SECTION[0] = sid
    print('\n%s  %s' % (sid, title))
    print('-' * (len(sid) + len(title) + 2))


def fail(sev, msg, do, sid=None):
    _FINDINGS.append((sev, sid or _SECTION[0], msg, do))
    print('   *** %s  %s' % (sev, msg))


def ok(msg):
    print('   ok    %s' % msg)


def info(msg):
    print('   ..    %s' % msg)


# ---------------------------------------------------------------------------- source helpers
_SRC = {}


def src(path):
    """File text, cached. Returns '' if unreadable (callers treat that as 'cannot verify')."""
    if path not in _SRC:
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                _SRC[path] = f.read()
        except OSError:
            _SRC[path] = ''
    return _SRC[path]


# ---- ACROSS-RUN MEMO (2026-10-29, user: "I need it to be 60 secs. With same results, just faster."). code_only,
# code_no_strings, _ast_strings and tag_write_sites are pure functions of ONE file's text and of this audit's own code;
# their AST walks were ~5 of this audit's 7 s every cull. Kept per (helper, path, sha256 of the text) beside
# rank_tables.pkl (local: not in git, not in the data store), dropped whole when this file or the Python version changes.
_MEMO_FILE = os.path.join(ROOT, 'system', 'scripts', 'audit_invariants_memo.pkl')
with open(os.path.abspath(__file__), 'rb') as _f:      # read now: __file__ is gone by the time atexit saves
    _MEMO = {'disk': None, 'run': {}, 'new': False, 'tag': hashlib.sha256(_f.read() + sys.version.encode()).hexdigest()}


def _memo_save():
    if not _MEMO['new']:
        return
    try:
        with open(_MEMO_FILE + '.tmp', 'wb') as f:
            pickle.dump({'tag': _MEMO['tag'], 'memo': _MEMO['run']}, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(_MEMO_FILE + '.tmp', _MEMO_FILE)
    except Exception:
        pass                    # a memo that cannot be written only costs the next run its speed


def _memoized(fn):
    @functools.wraps(fn)
    def inner(path):
        if _MEMO['disk'] is None:
            _MEMO['disk'] = {}
            try:
                with open(_MEMO_FILE, 'rb') as f:
                    blob = pickle.load(f)
                if blob.get('tag') == _MEMO['tag']:
                    _MEMO['disk'] = blob['memo']
            except Exception:
                pass
            atexit.register(_memo_save)
        k = (fn.__name__, path, hashlib.sha256(src(path).encode('utf-8')).hexdigest())
        if k not in _MEMO['run']:
            if k in _MEMO['disk']:
                _MEMO['run'][k] = _MEMO['disk'][k]
            else:
                _MEMO['run'][k] = fn(path)
                _MEMO['new'] = True
        v = _MEMO['run'][k]
        # each call used to build its own set / lists: hand out copies, never the memo's own object
        if isinstance(v, set):
            return set(v)
        if isinstance(v, tuple):
            return tuple(list(x) for x in v)
        return v
    return inner


_TREE = {}


def tree(path):
    if path not in _TREE:
        try:
            _TREE[path] = ast.parse(src(path), filename=path)
        except SyntaxError:
            _TREE[path] = None
    return _TREE[path]


_CODE = {}


@_memoized
def code_only(path):
    """File text with comments and docstrings blanked out, LINE NUMBERS PRESERVED.

    Two reasons this is not optional:
      * every 'is this column still read?' / 'does anything still call this?' question has to
        survive the fact that the RETIRED things are discussed at length in prose. special_bg_id
        appears in seven files purely as an explanation of why it is NOT read; pogo_pipeline's
        docstring names apply_tx_tag.py without ever invoking it. Matching raw text reports the
        explanation as the defect.
      * the per-species-cap check below pairs a cap() read with a nearby species_cap() call by LINE
        NUMBER. An earlier version of this helper rebuilt the source with tokenize.untokenize,
        which silently renumbered every line -- and the check then found one cap site in a file
        that has nine. A source transform that moves lines cannot be used for a proximity test.
    """
    if path in _CODE:
        return _CODE[path]
    s = src(path)
    if not s:
        _CODE[path] = ''
        return ''
    lines = s.split('\n')
    t = tree(path)
    if t is not None:
        for n in ast.walk(t):
            if not isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            b = getattr(n, 'body', None)
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                    and isinstance(b[0].value.value, str):
                for ln in range(b[0].lineno, (b[0].end_lineno or b[0].lineno) + 1):
                    if 1 <= ln <= len(lines):
                        lines[ln - 1] = ''
    try:
        for tok in tokenize.generate_tokens(io.StringIO(s).readline):
            if tok.type == tokenize.COMMENT:
                r, c = tok.start
                if 1 <= r <= len(lines) and lines[r - 1]:
                    lines[r - 1] = lines[r - 1][:c]
    except Exception:
        lines = [re.sub(r'#.*$', '', ln) for ln in lines]
    _CODE[path] = '\n'.join(lines)
    return _CODE[path]


def py_files(root=ROOT):
    """Every live .py in the project: no __pycache__, no backups, no snapshot dirs."""
    skip_dir = {'__pycache__', '.git', '.venv', 'venv', 'node_modules', '.db_snapshots',
                '.audit_baseline', '.grill', '.claude', 'agent_outputs'}
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dir]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            if '.bak' in fn or fn.endswith('bak'):
                continue
            out.append(os.path.relpath(os.path.join(dirpath, fn), ROOT).replace('\\', '/'))
    return sorted(out)


def mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return None


def ts(m):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(m)) if m else 'MISSING'


# ============================================================================= THE AXIS REGISTRY
# The single written-down answer to "is this axis capped or keep-all?".
#
# This table is the whole point of invariant 1. Until now that answer lived implicitly in each
# consumer's code, which is exactly how the same axis came to be modelled two different ways in
# two different files eight separate times. Anything that disagrees with this table is a finding:
# either the code is wrong, or this table is out of date and someone has to say so deliberately.
#
#   model     'capped'   -- membership is a top-N; N MUST come from keep_config, never a literal
#             'keep_all' -- every qualifying mon is kept; no ranking, no N
#             'hybrid'   -- a capped core PLUS a named, deliberately-uncapped sub-rule
#   cap_key   keep_config.cap() key, or None
#   per_sp    True if keep_config.species_cap() overrides apply to this category
#   reasons   the policy_reasons.json strings this axis emits
AXES = {
    # ---- capped collection axes -------------------------------------------------------------
    'plain_line':        dict(model='capped', cap_key='plain_line',        per_sp=False, reasons=['variant_floor']),
    'plain_line_preevo': dict(model='capped', cap_key='plain_line_preevo', per_sp=False, reasons=['variant_floor']),
    'plain_line_gender': dict(model='capped', cap_key='plain_line_gender', per_sp=False, reasons=['variant_floor']),   # per gender, dimorphic (2026-09-25)
    'cosmetic':          dict(model='capped', cap_key='cosmetic',          per_sp=True,  reasons=['variant_floor']),
    'cosmetic_middle':   dict(model='capped', cap_key='cosmetic_middle',   per_sp=False, reasons=['variant_floor']),   # middle-stage costumes (2026-09-25)
    'dynamax':           dict(model='capped', cap_key='dynamax',           per_sp=True,  reasons=['variant_floor']),
    'gigantamax':        dict(model='capped', cap_key='gigantamax',        per_sp=True,  reasons=['variant_floor']),
    'shiny':             dict(model='capped', cap_key='shiny',             per_sp=True,  reasons=['shiny']),
    'shiny_plain':       dict(model='capped', cap_key='shiny_plain',       per_sp=False, reasons=['shiny']),   # sub-cap inside 'shiny' (2026-09-23)
    'xxl':               dict(model='capped', cap_key='xxl',               per_sp=True,  reasons=['xxl']),
    'rarity_shadow':     dict(model='capped', cap_key='rarity_shadow',     per_sp=True,  reasons=['rarity']),   # shadow legendaries (2026-09-29)
    'xxl_per_type':      dict(model='capped', cap_key='xxl_per_type',      per_sp=False, reasons=['xxl']),   # XXL TRIM only: top-N per type (2026-09-29)
    'xxs':               dict(model='capped', cap_key='xxs',               per_sp=True,  reasons=['xxs']),
    # ---- hybrids: a cap PLUS an explicitly uncapped sub-rule the user asked for --------------
    'rarity':            dict(model='hybrid', cap_key='rarity',            per_sp=True,  reasons=['rarity'],
                              uncapped='best GL-rank + best UL-rank per (pid,cf) kept regardless of the cap (user 2026-05-30)'),
    'shadow':            dict(model='hybrid', cap_key='shadow',            per_sp=False, reasons=['shadow_best'],
                              uncapped='best GL-rank + best UL-rank per (pid,cf) kept regardless of the cap (user 2026-05-30)'),
    'legacy':            dict(model='hybrid', cap_key=None,                per_sp=False, reasons=['legacy'],
                              uncapped='keep-all unless the species carries an explicit legacy_species_caps entry'),
    # ---- keep-all axes ----------------------------------------------------------------------
    'hundo':            dict(model='keep_all', cap_key=None, per_sp=False, reasons=['hundo']),
    'nundo':            dict(model='capped', cap_key='nundo', per_sp=False, reasons=['nundo']),   # one per look (2026-09-17)
    'adventure_effect': dict(model='keep_all', cap_key=None, per_sp=False, reasons=['adventure_effect']),
    'origin':           dict(model='keep_all', cap_key=None, per_sp=False, reasons=['origin']),
    'mighty':           dict(model='keep_all', cap_key=None, per_sp=False, reasons=['mighty']),
    'location_card':     dict(model='hybrid', cap_key='location_card',     per_sp=True,  reasons=['location_card'],
                              uncapped='a holder whose fresh_loc_card_enum is still UNKNOWN is kept uncapped -- unknown data is protected, never fodder (2026-09-02)'),
    'protected':        dict(model='keep_all', cap_key=None, per_sp=False, reasons=['protected']),
    'favorite':         dict(model='keep_all', cap_key=None, per_sp=False, reasons=['favorite']),   # user 2026-09-17 'keep em'
    'shiny_ladder':     dict(model='keep_all', cap_key=None, per_sp=False, reasons=['shiny_ladder']),   # shiny ladder like plains (2026-09-17)
    'dex_only':         dict(model='keep_all', cap_key=None, per_sp=False, reasons=['dex_only_copy']),
    'pvp_iv':           dict(model='keep_all', cap_key=None, per_sp=False, reasons=['gl_iv', 'ul_iv']),
    'pvp_spread':       dict(model='keep_all', cap_key=None, per_sp=False, reasons=['pvp_spread']),
    'pvp_rank':         dict(model='keep_all', cap_key=None, per_sp=False, reasons=['pvp_rank']),
    # best-of-1, no N (user 2026-09-23): the best GL + best UL NON-shadow copy per pokemon_id AND per (pid,cf),
    # key (viable stage first, rank, uid_hex). keep_all in the model sense: every winner is kept, nothing ranked out.
    'pvp_best':         dict(model='keep_all', cap_key=None, per_sp=False, reasons=['pvp_best_gl', 'pvp_best_ul', 'pvp_best_ml']),
    # 2026-09-24: rule 15e, one comb-up copy per (league, target stage) -- every pick is kept, nothing ranked out.
    'pvp_combup':       dict(model='keep_all', cap_key=None, per_sp=False, reasons=['pvp_combup_gl', 'pvp_combup_ul']),
    'rank_unknown':     dict(model='keep_all', cap_key=None, per_sp=False, reasons=['rank_unknown']),
    'data_incomplete':  dict(model='keep_all', cap_key=None, per_sp=False, reasons=['data_incomplete']),
    # 2026-09-26: a fusion component (held inside a White/Black Kyurem) -- kept, out of every ladder.
    'fused':            dict(model='keep_all', cap_key=None, per_sp=False, reasons=['fused']),
    'evolve':           dict(model='keep_all', cap_key=None, per_sp=False, reasons=['evolve_1', 'evolve_2']),
}
REASON_TO_AXIS = {r: a for a, d in AXES.items() for r in d['reasons']}

# Which mark() sites in keep_policy may sit OUTSIDE a cap expression, per emitted reason.
#   'capped'   every mark for this reason must be reachable from a cap (topn()/[:N])
#   'uncapped' no mark for this reason may sit inside a cap
#   'both'     a hybrid: legitimately emitted from both, and BOTH must still be present
MARK_MODEL = {
    'variant_floor': 'both',      # capped floor pools + the comb-up 'stays at-stage stock' fallbacks
    'shiny':         'capped',
    'xxl':           'capped',
    'xxs':           'capped',
    'rarity':        'both',      # top-N + best GL/UL
    'shadow_best':   'both',      # top-N + best GL/UL
    'legacy':        'uncapped',  # the cap is applied while BUILDING the kept set -- see I1.7
    'hundo': 'uncapped', 'nundo': 'uncapped', 'adventure_effect': 'uncapped',
    'origin': 'uncapped', 'mighty': 'uncapped',
    # 'both': capped top-N per (pid,cf,card enum), PLUS an uncapped mark for a holder whose card enum
    # is still unknown -- unknown data is protected, never fodder (2026-09-02).
    'location_card': 'both',
    'protected': 'uncapped', 'favorite': 'uncapped', 'shiny_ladder': 'uncapped', 'dex_only_copy': 'uncapped', 'gl_iv': 'uncapped',
    'ul_iv': 'uncapped', 'pvp_spread': 'uncapped', 'pvp_rank': 'uncapped',
    'pvp_best_gl': 'uncapped', 'pvp_best_ul': 'uncapped', 'pvp_best_ml': 'uncapped',   # min()-picked best-of-1 (2026-09-23), never a [:1] slice
    'pvp_combup_gl': 'uncapped', 'pvp_combup_ul': 'uncapped',   # pvp_combup.pick (2026-09-24), one per target, never a slice
    'rank_unknown': 'uncapped', 'data_incomplete': 'uncapped', 'evolve_<n>': 'uncapped',
    'fused': 'uncapped',          # every fusion component, never a slice (2026-09-26)
}

ENGINE = 'system/scripts/keep_policy.py'
TAGSETS = 'system/scripts/build_tagsets.py'
GATE = 'system/scripts/preflight_transfer.py'
PILE_PRODUCERS = [ENGINE, TAGSETS, GATE]
CONSUMERS = {
    ENGINE:                     'ENGINE -- the only sanctioned pile producer',
    TAGSETS:                    'tagset builder -- what actually gets pushed',
    GATE:                       'keeper gate -- the last check before a human releases',
    'audit_cull.py':            'audit: 8-layer cull re-derivation',
    'audit_tags_membership.py': 'audit: tag membership',
    '_lawcheck.py':             'audit: law re-derivation of the pile',
    '_evocheck.py':             'audit: evolve comb-up',
    '_spotdata.py':             'audit: per-mon pile data sweep',
    'size_line.py':             'shared XXL selection (xxl_keepers): engine + mirrors call it (2026-09-29)',
}
# dashboard.py reads cap('...') ONLY to render the human-readable rules explainer (one HTML string
# per rule). It computes no membership and decides nothing, so per-species overrides are correctly
# absent there -- the panel documents the GLOBAL policy. Exempt from I1.6 by that reasoning only.
CAP_DISPLAY_ONLY = {'dashboard.py'}


# ============================================================================= I1 AXIS CONSISTENCY
# Shared selections that apply keep_config caps THEMSELVES (each reads its caps through keep_config.cap / species_cap,
# which the per-species scan below checks in its own file). A mark() loop over one of these is a capped site.
CAPPING_HELPERS = {'xxl_keepers': "size_line.xxl_keepers: species_cap('xxl') per species + cap('xxl_per_type') per type (2026-09-29)"}


def _cap_iter_kind(node, fn_assigns, depth=0):
    """Is this `for ... in <node>` iterating a CAPPED selection? -> label, or None.

    Recognises topn(rows, N), any [:N] slice, and one level of wrapper (enumerate/list/sorted/
    reversed) or local variable indirection -- which matters because the engine's biggest capped
    loop is `_ranked = topn(_pool, _eff_cap(...))` followed by `for i, r in enumerate(_ranked)`.
    A checker that only looked at the literal For.iter would call that loop UNCAPPED and then
    cheerfully accept a shiny axis with no cap at all.
    """
    if depth > 4 or node is None:
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in CAPPING_HELPERS:
        return '%s()' % node.func.attr          # a shared selection that applies the keep_config caps itself
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in ('topn', '_topn', 'top_n'):
            return 'topn()'
        if node.func.id in ('enumerate', 'list', 'reversed', 'sorted', 'tuple', 'set'):
            return _cap_iter_kind(node.args[0], fn_assigns, depth + 1) if node.args else None
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice) \
            and node.slice.upper is not None:
        return 'slice[:N]'
    if isinstance(node, ast.Name):
        for v in fn_assigns.get(node.id, []):
            k = _cap_iter_kind(v, fn_assigns, depth + 1)
            if k:
                return '%s via %s' % (k, node.id)
    return None


def _fn_assigns(fnnode):
    """name -> [assigned value nodes] inside one function body (for the indirection above)."""
    out = defaultdict(list)
    for n in ast.walk(fnnode):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id].append(n.value)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)) and isinstance(n.target, ast.Name):
            if getattr(n, 'value', None) is not None:
                out[n.target.id].append(n.value)
    return out


def engine_mark_model():
    """reason -> set of {'capped','uncapped'} observed at every mark() site in keep_policy."""
    t = tree(ENGINE)
    if t is None:
        return None
    parent = {}
    for n in ast.walk(t):
        for ch in ast.iter_child_nodes(n):
            parent[ch] = n
    fnassign = {}
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fnassign[n] = _fn_assigns(n)
    model = defaultdict(set)
    sites = defaultdict(list)
    for n in ast.walk(t):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == 'mark' and len(n.args) == 2):
            continue
        a = n.args[1]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            why = a.value
        elif isinstance(a, ast.JoinedStr):
            why = 'evolve_<n>'
        else:
            why = '<dynamic>'
        # nearest enclosing function, for local-variable resolution
        cur, fn = n, None
        chain = []
        while cur in parent:
            cur = parent[cur]
            chain.append(cur)
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn is None:
                fn = cur
        assigns = fnassign.get(fn, {})
        kind = None
        for anc in chain:
            if isinstance(anc, ast.For):
                kind = _cap_iter_kind(anc.iter, assigns)
                if kind:
                    break
        model[why].add('capped' if kind else 'uncapped')
        sites[why].append((n.lineno, kind or 'uncapped'))
    return model, sites


def _cap_sites(path):
    """[(lineno, category)] for every keep_config.cap('X') read in a file."""
    out = []
    for m in re.finditer(r"(?<!species_)\bcap\(\s*['\"]([a-z_]+)['\"]", code_only(path)):
        out.append((code_only(path)[:m.start()].count('\n') + 1, m.group(1)))
    return out


def _str_consts(node):
    """Every string constant this expression can evaluate to (ternaries and or-chains included)."""
    out = set()
    if node is None:
        return out
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.add(node.value)
    elif isinstance(node, ast.IfExp):
        out |= _str_consts(node.body) | _str_consts(node.orelse)
    elif isinstance(node, ast.BoolOp):
        for v in node.values:
            out |= _str_consts(v)
    return out


def _name_str_values(tnode, name):
    """Every string constant assignable to `name` in this module, tuple targets aligned.

    Covers the two idioms the consumers actually use for a per-variant category:
        _cat = 'gigantamax' if bm == 2 else 'dynamax' if bm == 1 else 'cosmetic'  (_lawcheck, preflight)
        _vc, _vcat = keep_config.cap('dynamax'), 'dynamax'                        (keep_policy)
    """
    vals = set()
    for n in ast.walk(tnode):
        if not isinstance(n, ast.Assign):
            continue
        for tgt in n.targets:
            if isinstance(tgt, ast.Name) and tgt.id == name:
                vals |= _str_consts(n.value)
            elif isinstance(tgt, ast.Tuple):
                for i, el in enumerate(tgt.elts):
                    if isinstance(el, ast.Name) and el.id == name \
                            and isinstance(n.value, ast.Tuple) and i < len(n.value.elts):
                        vals |= _str_consts(n.value.elts[i])
    return vals


def _species_cap_cats(path):
    """(the cap categories this file demonstrably routes through species_cap, unresolved sites).

    CATEGORY-AWARE, deliberately (2026-09-03). Two earlier shapes of this check were both wrong in
    a way that mattered:
      1. LINE PROXIMITY -- credit a cap('X') read only if a species_cap() call sat within +/-8
         lines. The normal idiom is a module-level constant holding the global
         (preflight_transfer.py:84 COSMETIC_CAP, _lawcheck.py:51 CAP_COS) applied via species_cap
         hundreds of lines later -- 221 lines apart in _lawcheck. Both files were already correct
         and both were reported as "never calls species_cap()", which became a false BLOCK the
         moment a per-species cosmetic cap was added. A false BLOCK on the gate standing in front
         of the irreversible pile is the worst failure this harness can have: it trains everyone
         to bypass the gate.
      2. FILE-SCOPE CREDIT -- any ONE dynamic species_cap(<var>, ...) call credited EVERY category
         read anywhere in that file. That killed the false BLOCK by going blind, and it hid a REAL
         defect: keep_policy.py routes cosmetic/dynamax/gigantamax through a dynamic
         species_cap(_vcat, ...) at rule 12 and therefore silently earned credit for its FLAT
         cap('location_card') read at rule 13b as well. The engine ignores a per-species
         location_card cap that preflight_transfer.py:411 honours -- the exact
         one-axis-modelled-two-ways class this whole harness exists to catch, invisible because
         the checker had been taught to look away.
    So: resolve the category ARGUMENT instead of guessing from distance. A literal is itself; a
    variable resolves to the string constants assigned to it. Only a site whose category cannot be
    resolved at all falls back to file-scope credit -- reported on an `..` line so it is never
    silent. That keeps shape 1's false BLOCK impossible without keeping shape 2's blindness.
    """
    t = tree(path)
    if t is None:
        return set(), [(0, 'file does not parse')]
    cats, unresolved = set(), []
    for n in ast.walk(t):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else '')
        if nm != 'species_cap' or not n.args:
            continue
        a = n.args[0]
        got = _str_consts(a)
        if not got and isinstance(a, ast.Name):
            got = _name_str_values(t, a.id)
        if got:
            cats |= got
        else:
            unresolved.append((n.lineno, type(a).__name__))
    return cats, unresolved


# What is ALREADY known about an uncovered axis, so the next reader does not re-derive it.
# Written down deliberately (2026-09-03) after tracing every consumer by hand: a bare "nobody
# covers this" sends the next agent back through eight files to learn what this line already knows.
AXIS_COVERAGE_NOTE = {
    'data_incomplete':
        'Measured 2026-09-03: the closest thing to coverage is audit_cull.py LAYER 8, whose '
        'writer-regression sentinel flags a pile member with a NULL fresh_natural_art_bg or '
        'fresh_loc_card_enum -- 2 of the 13 columns in keep_policy._PROT_COLS, and it self-disarms '
        'to INFO while a column has no writer (both are dormant today, so it currently proves '
        'nothing). The other 11 -- fresh_shiny, fresh_alignment, fresh_costume, fresh_form, '
        'fresh_bread_mode, fresh_has_location_card, fresh_is_strong, costume_decoration_id, '
        'iv_total, pokemon_size_category, is_zero -- have NO re-derivation anywhere: if rule 0 '
        'stopped firing, a never-rescanned row would enter the pile and all five audits would '
        'still say PASS. The gate is the right home for it (one query over the pile).'}


con_reason_count = [None]      # axis -> live keeper count, filled by main() before I1 runs


def check_axis_consistency(kc):
    section('I1', 'AXIS CONSISTENCY -- one model per axis, every cap from keep_config')

    # --- I1.1 the registry and keep_config must describe the same set of caps -----------------
    declared = {d['cap_key'] for d in AXES.values() if d['cap_key']}
    configured = set(kc.DEFAULTS['caps'])
    if declared != configured:
        miss, extra = configured - declared, declared - configured
        fail(BLOCK, 'AXES registry and keep_config.DEFAULTS["caps"] disagree: '
                    'config-only=%s registry-only=%s' % (sorted(miss), sorted(extra)),
             'A cap exists that no axis in this registry claims (or vice versa). Add the axis to '
             'AXES in audit_invariants.py with its model, or remove the dead cap from '
             'keep_config.DEFAULTS. Until then NO consumer is known to honour it.')
    else:
        ok('every keep_config cap key is claimed by exactly one declared axis (%d)' % len(declared))

    # --- I1.2 per-species override categories must match the registry -------------------------
    psc = set()
    for m in re.finditer(r"_psc_cats\s*=\s*\{([^}]*)\}", src('keep_config.py')):
        psc = set(re.findall(r"['\"]([a-z_]+)['\"]", m.group(1)))
    reg_psc = {d['cap_key'] for d in AXES.values() if d['per_sp'] and d['cap_key']}
    if psc and psc != reg_psc:
        fail(BLOCK, 'keep_config.validate() accepts per_species_caps for %s but the registry says '
                    'per-species applies to %s' % (sorted(psc), sorted(reg_psc)),
             'The dashboard can save a per-species cap for a category no consumer applies. Align '
             '_psc_cats in keep_config.py with the per_sp flags in AXES, then make every consumer '
             'read species_cap() for the newly-allowed category.')
    elif psc:
        ok('per-species cap categories agree with the registry (%s)' % ', '.join(sorted(psc)))

    # --- I1.3 the engine's mark() sites must match the declared model -------------------------
    res = engine_mark_model()
    if res is None:
        fail(BLOCK, '%s does not parse -- cannot verify any axis model' % ENGINE,
             'Fix the syntax error in keep_policy.py. Nothing downstream can be trusted until it '
             'parses; this harness deliberately refuses to guess.')
    else:
        model, sites = res
        unknown = sorted(set(model) - set(MARK_MODEL))
        if unknown:
            fail(BLOCK, 'keep_policy emits keep reason(s) with NO declared model: %s' % unknown,
                 'A new keep axis landed without anyone recording whether it is capped or '
                 'keep-all. Add it to AXES + MARK_MODEL in audit_invariants.py and confirm every '
                 'consumer (audits, preflight, build_tagsets) models it the same way.')
        for why, want in sorted(MARK_MODEL.items()):
            got = model.get(why)
            if got is None:
                info('%-16s declared %-8s -- not emitted in this build' % (why, want))
                continue
            have = ('both' if got == {'capped', 'uncapped'}
                    else ('capped' if got == {'capped'} else 'uncapped'))
            if have == want:
                ok('%-16s %-8s  %s' % (why, have, sites[why]))
                continue
            axis = REASON_TO_AXIS.get(why, why)
            if want in ('capped', 'both') and have == 'uncapped':
                fail(BLOCK, "axis '%s' (reason '%s') is declared %s but EVERY mark() site is "
                            "uncapped -- sites %s" % (axis, why, want, sites[why]),
                     "A capped axis is being applied as KEEP-ALL. That is the exact class that hid "
                     "the costume bucket, XXL, Dynamax, Gigantamax and shadow bugs. Restore the "
                     "cap read (keep_config.cap('%s')) around the mark, or -- if the user really "
                     "changed the rule -- update AXES/MARK_MODEL to say so." % (AXES.get(axis, {}).get('cap_key') or axis))
            else:
                fail(BLOCK, "axis '%s' (reason '%s') is declared %s but the marks are %s -- "
                            "sites %s" % (axis, why, want, have, sites[why]),
                     "A keep-all axis has acquired a cap, or a hybrid lost one of its two halves. "
                     "Compare keep_policy against AXES/MARK_MODEL and fix whichever is wrong. A "
                     "keep-all axis silently capped is how a trophy gets released.")

    # --- I1.4 no LITERAL cap anywhere a keeper is marked --------------------------------------
    lit_hits = []
    for path in CONSUMERS:
        t = tree(path)
        if t is None:
            fail(BLOCK, '%s does not parse' % path,
                 'Fix the syntax error; this consumer cannot be checked and must not be trusted.')
            continue
        fnassign = {}
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fnassign[n] = _fn_assigns(n)
        mod_assigns = _fn_assigns(t)
        for n in ast.walk(t):
            if not isinstance(n, ast.For):
                continue
            # does this loop MARK a keeper?
            marks = False
            for b in ast.walk(n):
                if isinstance(b, ast.Call):
                    fname = (b.func.id if isinstance(b.func, ast.Name)
                             else getattr(b.func, 'attr', ''))
                    if fname in ('mark', 'add', 'append', 'update') or fname.endswith('_keep'):
                        txt = ast.dump(b)
                        if 'uid_hex' in txt or fname == 'mark':
                            marks = True
                            break
            if not marks:
                continue
            kind = _cap_iter_kind(n.iter, mod_assigns)
            if not kind:
                continue
            # find the literal, if the cap really is one
            up = None
            probe = n.iter
            for _ in range(4):
                if isinstance(probe, ast.Call) and isinstance(probe.func, ast.Name):
                    if probe.func.id in ('topn', '_topn', 'top_n') and len(probe.args) > 1:
                        up = probe.args[1]
                        break
                    probe = probe.args[0] if probe.args else None
                elif isinstance(probe, ast.Subscript) and isinstance(probe.slice, ast.Slice):
                    up = probe.slice.upper
                    break
                else:
                    break
                if probe is None:
                    break
            if isinstance(up, ast.Constant) and isinstance(up.value, int):
                lit_hits.append((path, n.lineno, up.value))
    for path, ln, val in lit_hits:
        fail(BLOCK, 'LITERAL cap %d applied to a keep-marking loop at %s:%d' % (val, path, ln),
             "Every cap is the user's policy and lives in keep_config.json. Replace the literal "
             "with keep_config.cap('<axis>') (and species_cap() if the axis takes per-species "
             "overrides), so a dashboard edit reaches this consumer instead of silently not.")
    if not lit_hits:
        ok('no literal top-N cap in any keep-marking loop across %d consumers' % len(CONSUMERS))

    # --- I1.5 no consumer keeps its own numeric default for a cap ----------------------------
    own = []
    for path in CONSUMERS:
        for m in re.finditer(r"(?m)^\s*([A-Z][A-Z0-9_]*CAP[A-Z0-9_]*)\s*=\s*(\d+)\s*$",
                             code_only(path)):
            own.append((path, m.group(1), int(m.group(2))))
    for path, nm, val in own:
        fail(BLOCK, '%s defines its own numeric cap %s = %d' % (path, nm, val),
             'A second copy of a cap value drifts the moment the user edits the dashboard. Read '
             "it from keep_config.cap(...) instead. (keep_config.py's DEFAULTS are the ONE "
             'permitted hardcoded copy.)')
    if not own:
        ok('no consumer hardcodes a cap value; keep_config.DEFAULTS is the only copy')

    # --- I1.6 per-species overrides honoured wherever the global cap is read -----------------
    live_over = {k for k, v in (kc.raw().get('per_species_caps') or {}).items() if v}
    for path in CONSUMERS:
        if path in CAP_DISPLAY_ONLY:
            continue
        caps = _cap_sites(path)
        covered, unresolved = _species_cap_cats(path)
        if unresolved:
            # LAST-RESORT file-scope credit, and ONLY for a category argument this harness cannot
            # read at all (a dict lookup, a call, a function parameter). Blanket-crediting the file
            # is what hid keep_policy's flat cap('location_card') for a day, so it is now reserved
            # for genuine unreadability and is announced rather than applied silently.
            covered |= {c for _, c in caps}
            info('%-38s species_cap() category unresolvable at line(s) %s -- file-scope credit'
                 % (path, [ln for ln, _ in unresolved][:3]))
        need = {c for _, c in caps} & {d['cap_key'] for d in AXES.values() if d['per_sp']}
        missing = sorted(need - covered)
        if not missing:
            if need:
                ok('%-38s applies per-species overrides for %s' % (path, sorted(need)))
            continue
        bites = sorted(set(missing) & live_over)
        sev = BLOCK if bites else WARN
        why = ('keep_config.per_species_caps ALREADY overrides %s, so this consumer is live-wrong'
               % bites) if bites else \
              ('no per_species_caps entry exists for these categories today, so it is latent -- it '
               'becomes BLOCK the moment one is added from the dashboard')
        fail(sev, '%s reads the GLOBAL cap for %s but never keep_config.species_cap() -- %s'
                  % (path, missing, why),
             "Wrap each read: keep_config.species_cap('<cat>', pid, keep_config.cap('<cat>')). "
             "This is the bug that made preflight label ten IN-CAP shinies 'past the top-10' to a "
             'human reading the gate immediately before an irreversible release.')

    # --- I1.8 every axis must be re-derived by at least one audit -----------------------------
    # An axis nothing independently re-derives is invisible: the four result-checking audits will
    # report PASS on a pile that violates it. audit_cull's own F1 found exactly this -- rarity,
    # legacy, protected and pvp_spread appeared NOWHERE in any of the five audits, and injecting
    # one within-cap keeper per axis into the pile produced NOTHING AT ALL from all of them.
    # The audits legitimately spell some axes differently from the reason string the engine emits
    # (pvp_rank is re-derived as READY_RANK; the PvP-IV axis is the 'GL IV'/'UL IV' tags). Those
    # aliases are written down here rather than guessed, so an axis can never look covered by
    # accident -- and so that adding an axis without coverage is a visible decision.
    # 'rank_unknown' (2026-09-03): preflight_transfer.py:526 re-derives this axis EXACTLY --
    #     if r['gl_rank'] is None and r['ul_rank'] is None:
    #         why.append('pvp_unknown(no gl/ul rank -- unrankable species/form, cannot judge)')
    # -- the same predicate as keep_policy rule 15c, on the pile, in the gate a human reads
    # immediately before releasing. It is a REAL_KEEPER alarm there, so a rank_unknown mon that
    # reached the pile WOULD be caught. The axis was reported uncovered only because the gate
    # spells it 'pvp_unknown', which is precisely the aliasing this table exists to record. Verified
    # by reading both sites, not by matching a name.
    AUDIT_TOKENS = {'pvp_rank': ['pvp_rank', 'ready_rank'],
                    'pvp_iv': ['gl_iv', 'ul_iv', 'gl iv', 'ul iv', 'pvp_iv'],
                    'rank_unknown': ['rank_unknown', 'pvp_unknown']}
    # preflight_transfer counts: it is an INDEPENDENT re-derivation of every keep axis, run on the
    # pile immediately before a human releases from it.
    COVERERS = [p for p in CONSUMERS if p != ENGINE and p != TAGSETS]
    csrc = {p: code_only(p).lower() for p in COVERERS}
    for axis, d in sorted(AXES.items()):
        toks = AUDIT_TOKENS.get(axis, [axis] + d['reasons'])
        if d['cap_key']:
            toks = toks + [d['cap_key']]
        covered = [p for p, s in csrc.items() if any(t.lower() in s for t in toks)]
        if covered:
            continue
        live = (con_reason_count[0] or {}).get(axis, 0)
        # Always WARN, never BLOCK: a coverage gap means nobody has PROVEN this axis works, not
        # that it is broken. A gate that blocks the sync over a missing test would be blocking the
        # user for something that has not gone wrong -- and the axis this currently names is the
        # newest and most PROTECTIVE one (rule 0 data-completeness), whose failure direction is
        # over-keeping.
        fail(WARN, "axis '%s' (%s, reasons %s) is re-derived by NO independent consumer -- %s"
                   % (axis, d['model'], d['reasons'],
                      ('%d live keeper(s) rest on it' % live) if live
                      else 'no live members in the current reason map'),
             'Add a re-derivation to audit_cull.py (LAYER 2), _lawcheck.py, or the preflight gate. '
             'Until one exists, every result-checking audit reports PASS on a pile that violates '
             'this axis -- audit_cull F1 proved exactly that by injecting one within-cap keeper '
             'per uncovered axis and getting NOTHING AT ALL back from all five audits. '
             + AXIS_COVERAGE_NOTE.get(axis, ''))

    # --- I1.8b A RE-DERIVATION THAT CALLS THE ENGINE'S OWN SELECTOR IS NOT INDEPENDENT (H08, 2026-09-29) ----------
    # I1.8 above calls an axis "covered" when a consumer's code merely MENTIONS it. For the axes keep_policy marks
    # straight from ONE shared selector function, every consumer that mentioned them CALLED that same function --
    # trophy_pick.pick_nundos (nundo: keep_policy, preflight_transfer, audit_cull), pvp_combup.pick (comb-up: keep_policy,
    # preflight, audit_cull, _lawcheck, audit_tags_membership, audit_tag_truth), refresh_evolve_shiny.compute_target
    # (shiny ladder), size_line.xxl_keepers (XXL) -- so a bug there was re-derived identically and blessed by every gate.
    # Proven 2026-09-29 in a sandbox: a one-token trophy_pick.look regression piled the only plain nundo Squirtle, and a
    # misread floor in pvp_combup.pick piled a comb-up keeper; all 11 audits passed both. For each such axis:
    #   (a) the engine must still mark it from that selector (else this table is stale -- WARN);
    #   (b) a DECLARED independent re-derivation must exist, be called by a gate audit, and its own code must never
    #       reference the selector. A declared one that vanished or started calling the selector is a BLOCK (a guard
    #       regressed silently); an axis that never had one is a WARN naming the keepers that rest on it ALONE.
    SHARED_SELECTORS = {'nundo': ('trophy_pick', 'pick_nundos'),
                        'pvp_combup': ('pvp_combup', 'pick'),
                        'shiny_ladder': ('refresh_evolve_shiny', 'compute_target'),
                        'xxl': ('size_line', 'xxl_keepers')}
    # axis -> (file holding the re-derivation, its function or None = inline in that file, the gate audit that runs it)
    INDEPENDENT = {'nundo': ('independent_law.py', 'nundo_violations', 'audit_cull.py'),
                   'pvp_combup': ('independent_law.py', 'combup_uncovered', 'audit_cull.py'),
                   'shiny_ladder': ('independent_law.py', 'shiny_ladder_violations', 'audit_cull.py'),
                   'xxl': ('audit_cull.py', None, 'audit_cull.py')}   # the top-N selection is re-derived inline (_xxl_keep)
    _gate_src = code_only('full_audit.py')
    _eng_calls = set()
    _et = tree(ENGINE)
    for _n in (ast.walk(_et) if _et is not None else ()):
        if isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute):
            _eng_calls.add(_n.func.attr)
    try:
        _pol8 = json.load(open(os.path.join(ANA, 'policy_reasons.json'), encoding='utf-8'))
    except Exception:
        _pol8 = {}
    for axis, (mod, fn) in sorted(SHARED_SELECTORS.items()):
        _rs = set(AXES.get(axis, {}).get('reasons') or ())
        _sole = sum(1 for _v in _pol8.values() if isinstance(_v, list) and _v and set(_v) <= _rs)
        if fn not in _eng_calls:
            fail(WARN, "I1.8b table stale: keep_policy no longer calls %s.%s() for axis '%s'" % (mod, fn, axis),
                 'Update SHARED_SELECTORS in audit_invariants.py to the function the engine marks this axis from.')
            continue
        dec = INDEPENDENT.get(axis)
        if dec is None:
            fail(WARN, "axis '%s' is marked from %s.%s() and NOTHING re-derives it without calling that function -- %d "
                       "keeper(s) rest on it alone" % (axis, mod, fn, _sole),
                 'Write an independent re-derivation (independent_law.py) from LAW.md, call it from a gate audit, and '
                 'declare it in INDEPENDENT here.')
            continue
        f_, g_, caller = dec
        bad = []
        body = code_only(f_)
        if not body:
            bad.append('%s is missing or unreadable' % f_)
        if g_ is not None:
            _ft = tree(f_)
            _fns = {n.name for n in (_ft.body if _ft is not None else ()) if isinstance(n, ast.FunctionDef)}
            if g_ not in _fns:
                bad.append('%s defines no %s()' % (f_, g_))
            if g_ + '(' not in code_only(caller):
                bad.append('%s never calls %s()' % (caller, g_))
        for tok in ((fn + '(',) if g_ is None else (mod, fn + '(')):   # inline: the file may import the module for FACTS
            if tok in body:
                bad.append('%s references %s -- the engine\'s own selector' % (f_, tok.rstrip('(')))
        if caller not in _gate_src:
            bad.append('%s is not one of full_audit.py\'s gate audits' % caller)
        if bad:
            fail(BLOCK, "axis '%s': its independent re-derivation is gone or no longer independent (%s) -- every gate "
                        "now re-derives it with %s.%s(), the engine's own function (%d keeper(s) rest on it alone)"
                        % (axis, '; '.join(bad), mod, fn, _sole),
                 'Restore the independent re-derivation (independent_law.py / audit_cull.py) so it never imports or '
                 'calls the engine selector, and keep the gate audit calling it.')
        else:
            ok("axis '%s' (engine: %s.%s) is re-derived WITHOUT that function: %s%s, run by %s -- %d keeper(s) rest on it alone"
               % (axis, mod, fn, f_, (' ' + g_ + '()') if g_ else ' inline', caller, _sole))

    # --- I1.7 the legacy axis's cap must still come from keep_config -------------------------
    e = code_only(ENGINE)
    if 'legacy_caps()' in e and 'legacy_default_cap()' in e:
        ok('legacy axis reads BOTH keep_config.legacy_caps() and legacy_default_cap()')
    else:
        fail(BLOCK, 'keep_policy no longer reads keep_config.legacy_caps()/legacy_default_cap()',
             "Legacy is the one hybrid whose cap is applied while BUILDING the kept set, so the "
             "mark-site check above cannot see it. Restore the keep_config reads, or legacy "
             "silently reverts to keep-all (or to a hardcoded cap) with no other check noticing.")


# ============================================================================= I2 STALENESS
# --------------------------------------------------------- db CONTENT fingerprint (shared contract)
# SHARED PROVENANCE CONTRACT -- key "db_content_sha256" in system/analysis/pile_provenance.json
# (schema stays 1).
#   producer : system/scripts/keep_policy.py, when it stamps provenance
#   consumer : this file, in the staleness family below (I2.5 and I2.6)
#
# DEFINITION (both sides must implement this EXACTLY or the hashes will never agree):
#   sha256 over the pokemon-table content the pile actually depends on -- every column of every
#   in_bag=1 row, rows ordered by uid_hex, columns in a STABLE declared order (the column names
#   SORTED; never SELECT * order, which follows physical schema order and would silently change
#   the digest after an ALTER TABLE), each value rendered with repr() and joined by a separator
#   that cannot appear ambiguously (chr(0x1f), the ASCII UNIT SEPARATOR: repr() escapes every
#   control character, so that byte can never occur inside a rendered value).
#   It is deterministic across processes and contains NO file mtime and NO file size, by design.
#   The producer computes it from the SAME connection/transaction the engine reads its rows from,
#   so the hash can never describe a different snapshot than the one that produced the pile.
#
# WHY CONTENT AND NOT THE FILE'S mtime/size -- do NOT "restore" the metadata check:
#   pokemon.db runs in WAL journal mode. When the LAST connection to it closes after any write,
#   SQLite checkpoints the -wal sidecar back into the main file and deletes the sidecar. That
#   rewrite BUMPS the db's mtime while leaving its SIZE byte-identical and its CONTENT identical:
#   measured on a copy, mtime +1.11s / size delta 0 -- exactly the signature of the live failure
#   (stamp 00:09:59, db 00:10:06, both 19402752 bytes). So merely READING the database -- which the
#   audit itself does -- can move the mtime the audit then judges. The old gate therefore tripped
#   on its own pipeline: system/analysis/autocull_watch.log shows the same rc=1 gate failure at
#   20:58, 21:28, 23:39, 02:29 and 00:10, and the daemon has NEVER synced.
#   mtime was only ever a PROXY for "did the bag change". This is the thing it was proxying for.
#   The check is not weakened: a real content change between the pile and the db still BLOCKs.
#
# Producer and consumer MUST derive the SAME digest for the same snapshot, or this check inverts
# into a permanent false alarm -- precisely the failure mode being repaired here. So the canonical
# algorithm lives in exactly ONE place, keep_policy.db_content_sha256(), and this consumer IMPORTS
# it rather than re-deriving it (the same pattern, for the same reason, as keep_config.fingerprint()
# behind config_sha256). The local re-implementation below is used only if that import fails, and
# it must stay digest-identical to the producer's.
#
# Separator: chr(0x1f), the ASCII UNIT SEPARATOR. repr() escapes every control character, so this
# byte can never occur inside a rendered value and the flat join is unambiguous. Written as chr()
# so the source carries no literal control byte for an editor or a heredoc to mangle.
_DBHASH_SEP = chr(0x1f)


class _HashUnavailable(RuntimeError):
    """keep_policy.db_content_sha256 could not be imported, so the pile's content stamp cannot be
    checked. Raised, never worked around: this gate guards an IRREVERSIBLE pile, so being unable to
    verify must FAIL CLOSED (a BLOCK the operator sees) rather than pass, and must never be answered
    by a second implementation of the algorithm.

    THIS REPLACED A DUPLICATE. There used to be a full re-implementation here, carrying the comment
    "must stay byte-identical" to the producer. It DIVERGED WITHIN THREE DAYS: on 2026-09-06 the
    producer began excluding pipeline OUTPUT columns (auth_tag_names, the tag mirror the sync writes
    after the pile is stamped) and this copy did not, so the two returned different digests for the
    same rows -- producer 8652b317..., this copy e3249b4d.... Runtime happened to prefer the producer,
    so nothing failed and the divergence was invisible; had the import ever failed, the fallback would
    have reported a permanent, unexplainable content mismatch on a perfectly current pile.
    Two copies of one algorithm cannot be kept in sync by asking future editors nicely. There is now
    exactly ONE definition, in keep_policy.py.
    """


def _db_content_sha256_local(src):
    raise _HashUnavailable(
        'keep_policy.db_content_sha256 is unavailable and there is deliberately no second '
        'implementation to fall back on -- fix the import rather than trusting an unverified pile')


def _shared_hasher():
    """keep_policy.db_content_sha256 if it can be imported, else None.

    Importing keep_policy is side-effect free: everything it does at module level is path setup,
    keep_config reads and an idempotent os.makedirs; the engine itself sits behind an
    `if __name__ == '__main__'` guard. It cannot start a cull, write the db or touch a tag.
    """
    _sp = os.path.join(ROOT, 'system', 'scripts')
    if _sp not in sys.path:
        sys.path.insert(0, _sp)
    try:
        import keep_policy as _kp
        return getattr(_kp, 'db_content_sha256', None)
    except Exception:
        return None


def db_content_sha256(src, _shared=[]):
    """The shared-contract hash, taken from the PRODUCER's own function wherever possible."""
    if not _shared:
        _shared.append(_shared_hasher())
    fn = _shared[0]
    return fn(src) if fn is not None else _db_content_sha256_local(src)


def check_staleness(con, kc, cfm):
    section('I2', 'STALENESS -- every input current enough to decide an irreversible pile')

    # --- I2.1 form enum vs the forms actually in the bag --------------------------------------
    live_max = con.execute(
        'SELECT MAX(MAX(COALESCE(form,0)), MAX(COALESCE(fresh_form,0))) FROM pokemon WHERE in_bag=1'
    ).fetchone()[0] or 0
    enum_max = getattr(cfm, '_MAX_KNOWN_FORM', 0)
    guard_live = ('is_unknown_form' in code_only('costume_forms.py')
                  and re.search(r'def is_costume_form.*?is_unknown_form',
                                code_only('costume_forms.py'), re.S) is not None)
    tag_guard = ('_MAX_KNOWN_FORM' in code_only(TAGSETS))
    if not cfm.enum_ok():
        fail(BLOCK, 'form_enum.json did not load (%s)' % cfm.LOAD_ERROR,
             'Re-dump it: python system/scripts/game_read/classify_all_forms.py. With no enum, '
             'EVERY non-zero form is judged an unknown-and-therefore-costume, the plain pool '
             'empties and the comb-up dies (+62 mons into the pile, measured 2026-09-02).')
    elif live_max > enum_max:
        n = con.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND '
                        '(COALESCE(form,0)>? OR COALESCE(fresh_form,0)>?)',
                        (enum_max, enum_max)).fetchone()[0]
        ids = sorted({r[0] for r in con.execute(
            'SELECT DISTINCT form FROM pokemon WHERE in_bag=1 AND form>?', (enum_max,))})
        sev = WARN if (guard_live and tag_guard) else BLOCK
        fail(sev, 'form_enum.json is STALE: max known form %d, live bag holds %d (%d rows, ids %s); '
                  'dumped %s' % (enum_max, live_max, n, ids, ts(mtime('form_enum.json'))),
             'Re-dump the enum: python system/scripts/game_read/classify_all_forms.py. '
             + ('Currently held down by is_costume_form()\'s unknown-form guard (unknown ids are '
                'treated as COSTUMES = protected) and build_tagsets\' matching Event SQL clause. '
                'That guard over-protects on purpose; it is not a substitute for a current dump, '
                'and if either half is removed this becomes BLOCK.'
                if sev == WARN else
                'THE UNKNOWN-FORM GUARD IS GONE (costume_forms.is_costume_form no longer consults '
                'is_unknown_form, and/or build_tagsets dropped its _MAX_KNOWN_FORM clause), so a '
                'brand-new costume form is judged PLAIN again -- exactly how seven Pikachu '
                'costumes reached the irreversible pile.'))
    else:
        ok('form enum covers every live form (enum max %d >= bag max %d)' % (enum_max, live_max))

    # --- I2.2 gamemaster resolves every live (species, form) ---------------------------------
    try:
        from pvp_iv_rule import pvid
        gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
        sids = {p['speciesId'] for p in gm['pokemon']}
        unresolved = {}
        for pid, nm, f in con.execute(
                'SELECT DISTINCT pokemon_id, species_name, form FROM pokemon WHERE in_bag=1'):
            s = pvid(nm, f or 0)
            if s not in sids:
                unresolved.setdefault((pid, nm, f), s)
        if unresolved:
            # Direction check: is the unresolved row protected anyway?
            uids = []
            for (pid, nm, f) in unresolved:
                uids += [r[0] for r in con.execute(
                    'SELECT uid_hex FROM pokemon WHERE in_bag=1 AND pokemon_id=? AND '
                    'COALESCE(form,0)=COALESCE(?,0)', (pid, f))]
            guarded = 'rank_unknown' in code_only(ENGINE)
            fail(BLOCK if not guarded else WARN,
                 '%d (species,form) combination(s) do not resolve to a gamemaster speciesId: %s '
                 '(%d bag rows)' % (len(unresolved), sorted(unresolved)[:6], len(uids)),
                 'Add the form to form_overrides_complete.py (or refresh pvpoke_gamemaster.json). '
                 'An unresolved form has NO PvP ranks and NO maxcp, so rules 15/15b are vacuous '
                 'for it. ' + ('keep_policy rule 15c currently catches these as "rank_unknown" -> '
                               'PROTECTED, which is why this is a WARN and not a release risk; the '
                               'data gap is still real and must be closed.' if guarded else
                               'RULE 15c IS GONE, so these rows now get NO PvP protection at all.'))
        else:
            ok('every live (species,form) resolves in pvpoke_gamemaster.json')
    except Exception as e:
        fail(BLOCK, 'could not check gamemaster currency (%s)' % e,
             'pvpoke_gamemaster.json / pvp_iv_rule.py must be readable; every PvP keep rule and '
             'the whole evolution graph are built from them.')

    # --- I2.3 the live dex walk covers the bag ------------------------------------------------
    try:
        dex = {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']}
        bag = {r[0] for r in con.execute('SELECT DISTINCT pokemon_id FROM pokemon WHERE in_bag=1')}
        missing = sorted(bag - dex)
        if missing:
            fail(BLOCK, 'pokedex_hundos_live.json is missing %d species that are IN THE BAG: %s'
                        % (len(missing), missing[:12]),
                 'Re-run the dex walk (read_pokedex_hundos.py). keep_policy gates every evolution '
                 'on "is the TARGET in the live dex", so a missing species makes its whole line '
                 'un-evolvable and no pre-evo of it can be comb-up rescued -- 108 extra mons into '
                 'the pile when the file was absent entirely.')
        else:
            ok('dex walk covers all %d bag species' % len(bag))
        _dexm = mtime('pokedex_hundos_live.json') or 0
        if _dexm < (mtime(DB) or 0):
            # JUSTIFICATION CORRECTED 2026-09-03. This used to say "held to WARN because the
            # species-coverage check above passed, so nothing in the current bag is affected".
            # That was wrong about what the file is FOR, and it is the kind of wrong that makes a
            # reader dismiss the finding. keep_policy:164 reads this file ONLY as _seen_pids, the
            # set of dex-registered species, and uses it at build_evo_graph() to decide whether an
            # evolution is AVAILABLE -- the gamemaster lists evolutions PoGo has never enabled. The
            # TARGET of an evolution does not have to be in the bag, so bag-coverage does not bound
            # this at all. Measured evidence is cheap here, so take it instead of asserting.
            _new = con.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND '
                               'COALESCE(creation_time_ms,0) > ?', (_dexm * 1000,)).fetchone()[0]
            # mtime ALONE is not evidence: the pipeline reads the dex at step 'read_dex' and then keeps
            # writing ranks/tags into pokemon.db for another two minutes, so the file is older than the
            # db on EVERY healthy run. A finding that always fires is a finding nobody reads. The real
            # signal is the one this block already measures -- a mon acquired after the dex walk.
            if not _new:
                info('pokedex_hundos_live.json (%s) predates pokemon.db (%s) by design -- the pipeline '
                     'reads the dex mid-walk and keeps writing ranks/tags afterwards; 0 in-bag mon(s) '
                     'were acquired after that walk, so there is nothing it could be missing'
                     % (ts(_dexm), ts(mtime(DB))))
            else:
                fail(WARN, 'pokedex_hundos_live.json (%s) is OLDER than pokemon.db (%s) -- %d in-bag '
                       'mon(s) were caught after that walk'
                       % (ts(_dexm), ts(mtime(DB)), _new),
                     'Re-run the dex walk (read_pokedex_hundos.py) after a crawl. What this file '
                     'actually decides is evolution AVAILABILITY, not bag coverage: a species '
                     'registered since the walk makes every evolution INTO it look unavailable, so a '
                     'pre-evo that the comb-up would have rescued lands in the pile instead. The '
                     'direction of harm is UNDER-keeping, i.e. a release. The coverage check above '
                     'does NOT bound it -- an evolution target need not be in the bag. Held to WARN '
                     'rather than BLOCK because the dex only ever grows (a stale entry is never wrong, '
                     'only missing) and because I2.5 already BLOCKs when the database moved after the '
                     'pile was computed, which is this same event seen from the other side. The catch '
                     'count is the local evidence: a dex entry can only be created by acquiring the '
                     'species, so 0 catches narrows the risk to an evolution (which PRESERVES the '
                     'pre-evo creation_date and is therefore invisible to this count), a hatch or a '
                     'trade.')
    except Exception as e:
        fail(BLOCK, 'could not read pokedex_hundos_live.json (%s)' % e,
             'Re-run read_pokedex_hundos.py. keep_policy refuses to build a pile without it.')

    # --- I2.4 legacy currency -----------------------------------------------------------------
    try:
        leg = json.load(open('legacy_accurate.json', encoding='utf-8'))
        legu = {e['uid_hex'] for e in leg}
        allu = {r[0] for r in con.execute('SELECT uid_hex FROM pokemon')}
        if not legu:
            fail(BLOCK, 'legacy_accurate.json is EMPTY -- rule 6 protects nobody',
                 'Re-run detect_legacy.py. Legacy moves cannot be re-rolled without an Elite TM, '
                 'so a legacy mon released is unrecoverable by definition.')
        stray = legu - allu
        if stray:
            fail(WARN, 'legacy_accurate.json names %d uids that are not in pokemon.db at all'
                       % len(stray),
                 'Re-run detect_legacy.py against the current DB; the file is describing a bag '
                 'that no longer exists.')
        info('legacy_accurate.json: %d entries, written %s'
             % (len(legu), ts(mtime('legacy_accurate.json'))))
    except Exception as e:
        fail(BLOCK, 'could not read legacy_accurate.json (%s)' % e,
             'Re-run detect_legacy.py before keep_policy; the engine aborts without it.')

    # --- I2.5 pile provenance: was THIS pile built from THIS config and THIS db? --------------
    prov_path = os.path.join(ANA, 'pile_provenance.json')
    pile_path = os.path.join(TD, '6_Transfer.txt')
    # Verdict of the CONTENT comparison below, shared with I2.6 so the two sites cannot disagree
    # about whether the database moved:
    #   True  -- the stamp carries db_content_sha256 and it matches the live db exactly
    #   False -- it carries one and it does NOT match (a real bag change; BLOCKed at I2.5)
    #   None  -- no content stamp available (missing/old provenance, or the recompute failed),
    #            so both sites fall back to the LEGACY mtime/size behaviour and say so
    _db_content_ok = None
    if not os.path.exists(prov_path):
        fail(BLOCK, 'system/analysis/pile_provenance.json is MISSING -- the pile on disk records '
                    'nothing about the config or the database it came from',
             'Re-run: python system/scripts/keep_policy.py && python system/scripts/build_tagsets.py. '
             'keep_policy stamps the provenance; a missing stamp must be read as STALE, never as '
             'fine -- the engine deliberately leaves the OLD pile on disk when it aborts.')
    else:
        try:
            prov = json.load(open(prov_path, encoding='utf-8'))
            import hashlib
            live_cfg = kc.fingerprint()
            if prov.get('config_sha256') != live_cfg:
                fail(BLOCK, 'pile was built from a DIFFERENT keep_config (stamp %s..., live %s...)'
                            % (str(prov.get('config_sha256'))[:12], live_cfg[:12]),
                     'The caps changed after the pile was computed. Re-run keep_policy.py then '
                     'build_tagsets.py before any sync -- every audit below re-derives with the '
                     'LIVE caps, so a cap LOWERED after the build hides real over-cap members and '
                     'a cap RAISED invents false ones.')
            else:
                ok('pile provenance config_sha256 matches the live keep_config')
            if os.path.exists(pile_path):
                h = hashlib.sha256(open(pile_path, 'rb').read()).hexdigest()
                if prov.get('pile_sha256') != h:
                    fail(BLOCK, '6_Transfer.txt bytes do not match the provenance stamp',
                         'Something rewrote the pile outside keep_policy. Re-run keep_policy.py '
                         'and build_tagsets.py; do NOT sync a pile with no verified producer.')
            # -- was the pile computed from the CURRENT pokemon.db? -----------------------------
            # This compares CONTENT, never the file's mtime/size. pokemon.db is in WAL journal
            # mode: when the LAST connection closes after any write, SQLite checkpoints the -wal
            # sidecar back into the main file and deletes it. That rewrite BUMPS the mtime while
            # leaving the SIZE byte-identical and the CONTENT identical -- measured on a copy,
            # mtime +1.11s / size delta 0, exactly the live failure's signature (stamp 00:09:59,
            # db 00:10:06, both 19402752 bytes). Under WAL an mtime move is therefore evidence of
            # a CHECKPOINT, not of a bag change, and the old metadata gate was BLOCKing the
            # sanctioned pipeline on its own file I/O (autocull_watch.log: rc=1 at 20:58, 21:28,
            # 23:39, 02:29, 00:10 -- the daemon has never synced). mtime/size was only ever a
            # PROXY for "did the bag change"; db_content_sha256 IS that question, so do not
            # "restore" the metadata comparison. Nothing is weakened: a genuine content change
            # between the pile and the db still BLOCKs, below.
            st = os.stat(DB)
            _stamp_content = prov.get('db_content_sha256')
            if _stamp_content:
                try:
                    _live_content = db_content_sha256(con)
                except Exception as _ce:
                    _db_content_ok = None
                    fail(BLOCK, 'provenance carries db_content_sha256 but it could NOT be '
                                'recomputed from the live pokemon.db (%s)' % _ce,
                         'The content fingerprint is the only thing that can tell a real bag '
                         'change from a WAL checkpoint, so a pile whose freshness cannot be '
                         'established must not be synced. Check the pokemon table is readable '
                         '(schema / uid_hex / in_bag intact), then re-run keep_policy.py and '
                         'build_tagsets.py.')
                else:
                    _db_content_ok = (_stamp_content == _live_content)
                    _meta_moved = (prov.get('db_mtime') is not None
                                   and (abs((prov['db_mtime'] or 0) - st.st_mtime) > 1
                                        or prov.get('db_size') != st.st_size))
                    if not _db_content_ok:
                        fail(BLOCK, 'pile was computed from DIFFERENT pokemon.db CONTENT (stamp '
                                    '%s..., live %s...; stamp described %s in-bag rows)'
                                    % (str(_stamp_content)[:12], _live_content[:12],
                                       prov.get('in_bag')),
                             'The bag really changed after the pile was built -- this is a '
                             'content mismatch over every column of every in-bag row, not a file '
                             'timestamp. Re-run keep_policy.py and build_tagsets.py; the bag '
                             'drifts every turn and syncing a stale pile is how a keeper caught '
                             'since the build gets tagged for transfer.')
                    else:
                        ok('pile provenance db_content_sha256 matches the live pokemon.db '
                           '(every column of every in-bag row; %s rows stamped)'
                           % prov.get('in_bag'))
                        if _meta_moved:
                            # The exact false positive this check used to fire on. Not a defect:
                            # the bytes that decide the pile are identical.
                            info('pokemon.db file metadata moved since the stamp (mtime %s -> %s, '
                                 'size %s -> %s) but its CONTENT is identical -- a WAL checkpoint '
                                 'rewrote the file, the bag did not change. NOT staleness.'
                                 % (ts(prov.get('db_mtime')), ts(st.st_mtime),
                                    prov.get('db_size'), st.st_size))
            elif prov.get('db_mtime') is not None and (
                    abs((prov['db_mtime'] or 0) - st.st_mtime) > 1 or prov.get('db_size') != st.st_size):
                # LEGACY PATH -- this provenance predates db_content_sha256, so there is nothing
                # to compare but file metadata. Kept so an older stamp loses no coverage, at the
                # cost of the WAL-checkpoint false positive described above.
                fail(BLOCK, 'pile was computed from a different pokemon.db (stamp %s / %s bytes, '
                            'live %s / %s bytes) [LEGACY mtime/size path -- this provenance stamp '
                            'carries no db_content_sha256, so file metadata is all there is to '
                            'compare, and a WAL checkpoint alone can trip it]'
                            % (ts(prov.get('db_mtime')), prov.get('db_size'),
                               ts(st.st_mtime), st.st_size),
                     'Re-run keep_policy.py and build_tagsets.py: that both rebuilds the pile '
                     'against the current bag AND rewrites the stamp with db_content_sha256, '
                     'which distinguishes a real bag change from a WAL checkpoint. The bag drifts '
                     'every turn and syncing a stale pile is how a keeper caught since the build '
                     'gets tagged for transfer.')
        except Exception as e:
            fail(BLOCK, 'pile_provenance.json unreadable (%s)' % e,
                 'Re-run keep_policy.py to rewrite the stamp.')

    # --- I2.6 artifact ordering ---------------------------------------------------------------
    order = [('pokemon.db', DB), ('keep_config.json', 'keep_config.json'),
             ('legacy_accurate.json', 'legacy_accurate.json'),
             ('policy_reasons.json', os.path.join(ANA, 'policy_reasons.json')),
             ('6_Transfer.txt', pile_path), ('Transfer.txt', os.path.join(TD, 'Transfer.txt'))]
    for nm, p in order:
        info('%-22s %s' % (nm, ts(mtime(p))))
    pol = mtime(os.path.join(ANA, 'policy_reasons.json')) or 0
    STALE_WHY = {
        'pokemon.db': 'The BAG changed after the pile was built. The bag drifts every turn; a mon '
                      'caught since the build has never been judged, and one already released '
                      'still occupies a cap slot in the pile that exists.',
        'keep_config.json': 'A CAP changed after the pile was built, so the pile is not the one '
                            'your config describes -- and every audit re-derives with the LIVE '
                            'caps, so a cap lowered since then hides real over-cap members while a '
                            'cap raised invents false ones.',
        'legacy_accurate.json': 'The LEGACY set changed after the pile was built. A mon that '
                                'gained a legacy move since then is still sitting in the pile, and '
                                'legacy moves cannot be re-rolled without an Elite TM.',
    }
    # ORDERING NOTE -- pokemon.db is exempt from the mtime comparison below, and must stay exempt.
    # It is a WAL database: closing the last connection after any write checkpoints the -wal
    # sidecar into the main file and deletes it, which BUMPS the mtime with the content byte-for-
    # byte identical (measured: +1.11s, size delta 0). Reading the db -- which this audit does --
    # is enough to make it look "NEWER than the computed pile", so mtime ORDERING between the db
    # and policy_reasons.json carries no information about whether the bag changed. The question
    # this check exists to ask is answered at I2.5 by db_content_sha256, and its verdict is reused
    # here via _db_content_ok so the two sites can never disagree. Do NOT restore an mtime
    # comparison for pokemon.db. keep_config.json and legacy_accurate.json are ordinary files
    # nothing rewrites in place, so they keep the mtime check unchanged.
    for nm, p in (('pokemon.db', DB), ('keep_config.json', 'keep_config.json'),
                  ('legacy_accurate.json', 'legacy_accurate.json')):
        m = mtime(p) or 0
        if m <= pol:
            continue
        if nm == 'pokemon.db':
            if _db_content_ok is True:
                # I2.5 already proved the content is identical to what the pile was built from.
                info('pokemon.db mtime (%s) is newer than the computed pile (%s), but its CONTENT '
                     'matches the provenance stamp (I2.5) -- a WAL checkpoint touched the file, '
                     'the bag did not change. NOT staleness.' % (ts(m), ts(pol)))
                continue
            if _db_content_ok is False:
                # Real staleness. I2.5 already raised the BLOCK with the hashes; do not double-count.
                info('pokemon.db mtime (%s) is newer than the computed pile (%s) AND its content '
                     'differs from the stamp -- see the db_content_sha256 BLOCK at I2.5.'
                     % (ts(m), ts(pol)))
                continue
            # _db_content_ok is None: no content stamp to consult, so fall back to mtime ordering.
            fail(BLOCK, '%s (%s) is NEWER than the computed pile (%s) [LEGACY mtime path -- no '
                        'db_content_sha256 in the provenance stamp, so ordering by file timestamp '
                        'is all there is, and a WAL checkpoint alone can trip it]'
                        % (nm, ts(m), ts(pol)),
                 '%s Re-run: python system/scripts/keep_policy.py && python '
                 'system/scripts/build_tagsets.py -- that also rewrites the stamp with '
                 'db_content_sha256, which tells a real bag change from a WAL checkpoint.'
                 % STALE_WHY[nm])
            continue
        fail(BLOCK, '%s (%s) is NEWER than the computed pile (%s)' % (nm, ts(m), ts(pol)),
             '%s Re-run: python system/scripts/keep_policy.py && python '
             'system/scripts/build_tagsets.py' % STALE_WHY[nm])
    a = mtime(pile_path) or 0
    b = mtime(os.path.join(TD, 'Transfer.txt')) or 0
    if b < a:
        fail(BLOCK, 'Transfer.txt (%s) is OLDER than 6_Transfer.txt (%s) -- the tag that gets '
                    'PUSHED is not the pile that was computed' % (ts(b), ts(a)),
             'Run build_tagsets.py. It reads 6_Transfer.txt and re-emits Transfer.txt; until it '
             'does, prune_tags would push a pile from an earlier engine run.')
    elif a:
        ok('Transfer.txt is at least as new as the computed pile')

    # --- I2.7 the CLIENT game master (PokeMiners): stamped, checked, and not behind the game ------------------
    # gamemaster_pokeminers.json feeds evolvability, the legacy-move pools, tradability and the rarity classes
    # (evolvable_forms, detect_legacy, remote_trade_picks, audit_gamemaster). refresh_gamemaster.py stamps every batch it
    # installs (gamemaster_pokeminers.json.meta: batch time, APK, sha256, last upstream check) and stops for review when
    # an in-bag keep verdict flips; this is the OFFLINE backstop for the entry points that never run it (the dashboard's
    # `full_audit.py --audits-only`, a stale checkout). WARN, never BLOCK -- gm_guard.freshness_findings says why: the pile
    # gate is the real gate, an older game master leaves what it does not know on protected defaults (an unnamed move
    # stays legacy, an unknown form stays a costume), and a BLOCK could not be cleared while PokeMiners is quiet (its
    # newest batch was APK 0.427.0 when the phone ran 0.429.1).
    try:
        import gm_guard as _gg
        _gm_meta = _gg.read_meta(os.path.join(ROOT, 'gamemaster_pokeminers.json.meta'))
        try:
            with open(os.path.join(ANA, 'game_version.json'), encoding='utf-8') as _gvf:
                _gm_gv = json.load(_gvf)
        except (OSError, ValueError):
            _gm_gv = None
        _gm_f = _gg.freshness_findings(_gm_meta, _gm_gv)
        for _lvl, _msg, _do in _gm_f:
            fail(WARN, _msg, _do)
        if not _gm_f:
            ok('the client game master is stamped: batch %s UTC (APK %s), last compared with PokeMiners %s UTC, game %s'
               % (_gm_meta['batch_utc'], _gm_meta.get('apk') or '?', _gm_meta.get('checked_at', '?'),
                  (_gm_gv or {}).get('version', '?')))
    except Exception as e:
        fail(WARN, 'could not judge the client game master stamp (%s: %s)' % (type(e).__name__, e),
             'Check pogo_extract/gm_guard.py imports and gamemaster_pokeminers.json.meta.')


# ============================================================================= I3 NULL DIRECTION
# Every engine read of the form `r['col'] or 0` turns a NULL into the value that means
# "not special" -- i.e. UNPROTECTED. That is silent under-protection aimed squarely at the rows we
# know LEAST about. keep_policy rule 0 (the data-completeness gate) covers most of them by keeping
# any row with a NULL protection input. Anything NOT covered needs a written exemption here, and
# the exemption's own premise is re-checked at runtime below -- an exemption whose evidence stops
# holding is itself a BLOCK.
NULL_EXEMPT = {
    'form_region': (
        'grouping input, not a protection input. Read as (r["form_region"] or "").strip().lower() '
        'purely to elect a species canonical BASE form; NULL falls into the base-region set, which '
        'is the SAME answer as an explicit "normal". The regional-masquerade risk it creates is '
        'closed by the _is_regional_code() guard, whose presence is asserted below.'),
    'is_legendary': ('secondary OR-term only; references.RARE_PIDS is tested FIRST and is '
                     'authoritative. Evidence re-checked below.'),
    'is_mythical': ('same as is_legendary.'),
    'is_ultra_beast': ('same as is_legendary.'),
    'is_paradox': ('same as is_legendary.'),
    'adventure_effects_left': (
        'the AE axis is (col > 0) OR (pid in keep_config.adventure_effect_pids); the ROSTER is the '
        'real protection and the column can only ADD keeps. Its own integrity is a separate '
        'finding under I4 (no live writer).'),
    'original_owner_name': (
        'gated behind is_traded/is_traded_flag_v2/is_lucky, so it is only consulted for a mon that '
        'IS traded or lucky. A traded row with a NULL owner would be under-protected, so the '
        'harness asserts below that no such row exists.'),
    'gl_rank': ('covered by rule 15c: a row with BOTH ranks NULL is kept as "rank_unknown". The '
                'harness asserts below that no row has exactly ONE rank NULL, which 15c would miss.'),
    'ul_rank': ('same as gl_rank.'),
    'gl_stage': ('same as gl_rank -- read only alongside it.'),
    'ul_stage': ('same as gl_rank -- read only alongside it.'),
    'ml_rank': ('same as gl_rank (2026-10-23): read only behind an `is not None` guard (the shadow ML pick, Best ML), never '
                'as `or 0`, and a row with every rank NULL is kept by rule 15c. The harness asserts below that no row has '
                'its ML rank or stage NULL while it holds a GL or UL rank, which 15c would miss.'),
    'ml_stage': ('same as ml_rank -- read only alongside it.'),
    'cull_decision_v9': ('reporting only -- the "newly trimmed vs cull_v9" print. Decides nothing.'),
}

# fresh_* rescan column -> the legacy pre-rescan column(s) that hold the same thing. Reading the
# legacy twin is the natural_art_background bug: garbage on real rows, and a phantom "background"
# bit dominance-collapsed a real sibling.
FRESH_TWINS = {
    'fresh_costume': ['costume', 'display_costume', 'original_costume'],
    'fresh_alignment': ['alignment', 'display_alignment'],
    'fresh_shiny': ['is_shiny'],
    'fresh_has_location_card': ['has_location_card'],
    'fresh_loc_card_enum': ['loc_LocationCard', 'loc_inner_value', 'location_bg_id'],
    'fresh_bread_mode': ['bread_mode', 'is_gmax_dmax'],
    'fresh_is_strong': ['is_strong_pokemon'],
    'fresh_natural_art_bg': ['natural_art_background', 'natural_art_bg'],
    'fresh_natural_art_type': ['natural_art_type'],
    'fresh_natural_art_full': ['natural_art_use_full_scene', 'natural_art_full_scene'],
    'fresh_day_night': ['day_night_type'],
    'fresh_tag_count': ['pokemon_tag_count'],
    'fresh_pokemon_badge': ['display_pokemon_badge'],
}
# `form` is deliberately NOT a legacy twin of fresh_form: it is the crawl's own column, pvid()
# needs it, and _cosf_id() falls back to it ON PURPOSE so a never-rescanned fresh_form cannot make
# a form-encoded costume look plain. display_form IS junk (max value 1950495077 in the live bag).
FRESH_TWINS['fresh_form'] = ['display_form']
# Columns proven to be garbage and formally retired. Any engine read is a regression.
RETIRED_COLS = {
    'special_bg_id': 'PokemonProto has NO background field (proto_layout.json). Every stored value '
                     'is a retired-offset artifact; no writer anywhere in the tree.',
}


def engine_read_columns(schema):
    """Columns keep_policy actually reads off a row, from its source."""
    s = code_only(ENGINE)
    got = set(re.findall(r"""[A-Za-z_][A-Za-z0-9_]*\[\s*['"]([a-z0-9_]+)['"]\s*\]""", s))
    got |= set(re.findall(r"""\.get\(\s*['"]([a-z0-9_]+)['"]""", s))
    # rule 0's protection-column tuple, in case any member is only named there
    for m in re.finditer(r"_PROT_COLS\s*=\s*\(([^)]*)\)", s):
        got |= set(re.findall(r"['\"]([a-z0-9_]+)['\"]", m.group(1)))
    return sorted(c for c in got if c in schema)


def check_null_direction(con, schema):
    section('I3', 'NULL DIRECTION -- missing data must never read as UNPROTECTED')

    prot = set()
    for m in re.finditer(r"_PROT_COLS\s*=\s*\(([^)]*)\)", code_only(ENGINE)):
        prot = set(re.findall(r"['\"]([a-z0-9_]+)['\"]", m.group(1)))
    if not prot:
        fail(BLOCK, 'keep_policy has no _PROT_COLS data-completeness gate (rule 0)',
             'Restore rule 0. Without it a row the fresh rescan never reached is indistinguishable '
             'from a genuinely plain one, is ranked bottom of every cap, and is dropped.')
    else:
        ok('rule 0 data-completeness gate covers %d protection columns' % len(prot))

    reads = engine_read_columns(schema)
    n = con.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1').fetchone()[0]
    undocumented = []
    for col in reads:
        k = con.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND %s IS NULL'
                        % col).fetchone()[0]
        if not k:
            continue
        if col in prot:
            info('%-26s %d/%d NULL -- covered by rule 0 (kept as data_incomplete)' % (col, k, n))
        elif col in NULL_EXEMPT:
            info('%-26s %d/%d NULL -- EXEMPT: %s' % (col, k, n, NULL_EXEMPT[col][:96]))
        else:
            undocumented.append((col, k))
    for col, k in undocumented:
        fail(BLOCK, "engine-read column '%s' is NULL on %d/%d in-bag rows and has neither rule-0 "
                    'coverage nor a documented exemption' % (col, k, n),
             "Every `r['%s'] or 0` turns a NULL into 'not special' = UNPROTECTED. Either add the "
             'column to keep_policy._PROT_COLS (so a NULL row is kept as data_incomplete), or add '
             'a written exemption to NULL_EXEMPT in audit_invariants.py explaining why a NULL '
             'there cannot cost a keeper.' % col)
    if not undocumented:
        ok('every NULL-bearing engine-read column is gated or documented (%d read, %d NULL-bearing)'
           % (len(reads), len(reads) - sum(1 for c in reads if c not in prot and c not in NULL_EXEMPT)))

    # --- exemption evidence: each premise re-checked, so an exemption cannot rot ---------------
    try:
        from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
        rare = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
        flagged = {r[0] for r in con.execute(
            'SELECT DISTINCT pokemon_id FROM pokemon WHERE in_bag=1 AND (is_legendary=1 OR '
            'is_mythical=1 OR is_ultra_beast=1 OR is_paradox=1)')}
        gap = sorted(flagged - rare)
        if gap:
            fail(BLOCK, 'references.RARE_PIDS does NOT cover DB-flagged rare species %s -- the '
                        'is_legendary/is_mythical/is_ultra_beast/is_paradox NULL exemption is void'
                        % gap,
                 'Add those pids to references.py. The exemption rests on the roster being a '
                 'SUPERSET of the columns; while it is not, a rare mon whose flag column is NULL '
                 'gets no rarity protection at all.')
        else:
            ok('RARE_PIDS covers every DB-flagged rare species (%d pids) -- rarity NULL exemption '
               'holds' % len(flagged))
    except Exception as e:
        fail(BLOCK, 'could not verify the RARE_PIDS roster (%s)' % e,
             'references.py must import; it is the ONLY protection for ~24 legendary species whose '
             'is_legendary column is NULL.')

    bad_owner = con.execute(
        'SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND (is_traded=1 OR is_traded_flag_v2=1 OR '
        'is_lucky=1) AND (original_owner_name IS NULL OR TRIM(original_owner_name)="")').fetchone()[0]
    if bad_owner:
        fail(BLOCK, '%d traded/lucky in-bag mon(s) have NO original_owner_name -- the origin axis '
                    'reads them as "not from E+F"' % bad_owner,
             'Re-run the crawl so original_owner_name is populated, or add the column to '
             'keep_policy._PROT_COLS. A traded mon whose origin we cannot read must be PROTECTED, '
             'not assumed to be from a stranger.')
    else:
        ok('every traded/lucky mon has a readable original_owner_name -- origin exemption holds')

    one_rank = con.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND '
                           '((gl_rank IS NULL)+(ul_rank IS NULL))=1').fetchone()[0]
    if one_rank:
        fail(BLOCK, '%d in-bag mon(s) have exactly ONE of gl_rank/ul_rank NULL -- rule 15c only '
                    'protects rows where BOTH are NULL' % one_rank,
             'Re-run compute_all_ranks.py / rank_cache.py. A half-ranked row is judged on PvP data '
             'that was only half computed, which is the Mareep failure shape with one league '
             'missing instead of both.')
    else:
        ok('no half-ranked rows -- rule 15c fully covers the rank NULL exemption')

    half_ml = con.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND (ml_rank IS NULL OR ml_stage IS NULL) '
                          'AND NOT (gl_rank IS NULL AND ul_rank IS NULL)').fetchone()[0]
    if half_ml:
        fail(BLOCK, '%d in-bag mon(s) have a NULL ml_rank/ml_stage but a GL or UL rank -- rule 15c only '
                    'protects rows where every rank is NULL' % half_ml,
             'Re-run compute_all_ranks.py / rank_cache.py. The shadow ML and Best ML picks skip a NULL ML rank, '
             'so a ranked row missing only its ML rank could lose its ML keep with nothing else catching it.')
    else:
        ok('no ML-only NULL rows -- rule 15c covers the ml_rank / ml_stage NULL exemption')

    if '_is_regional_code' in code_only(ENGINE):
        ok('form_region NULL exemption holds: _is_regional_code() guard present in the engine')
    else:
        fail(BLOCK, 'keep_policy lost the _is_regional_code() guard -- the form_region NULL '
                    'exemption is void',
             'Restore it. Without the guard a regional form carrying a blank form_region can be '
             'elected a species\' canonical BASE form, collapsing Kantonian and Alolan copies into '
             'one capped group.')

    # --- legacy-twin reads in the pile producers ---------------------------------------------
    legacy_of = {l: f for f, ls in FRESH_TWINS.items() for l in ls}
    for path in PILE_PRODUCERS + [p for p in CONSUMERS if p not in PILE_PRODUCERS]:
        s = code_only(path)
        if not s:
            continue
        localkeys = set(re.findall(r"""['"]([a-z0-9_]+)['"]\s*:""", s))   # dict-literal keys
        hits = set()
        for tok in set(re.findall(r"""[A-Za-z_][A-Za-z0-9_]*\[\s*['"]([a-z0-9_]+)['"]\s*\]""", s)) \
                | set(re.findall(r"""\.get\(\s*['"]([a-z0-9_]+)['"]""", s)):
            if tok in legacy_of and tok not in localkeys:
                hits.add(tok)
        for m in re.finditer(r"SELECT(.{0,1200}?)FROM\s+pokemon", s, re.S | re.I):
            for tok in re.findall(r'[A-Za-z0-9_]+', m.group(1)):
                if tok in legacy_of:
                    hits.add(tok)
        for tok in sorted(hits):
            sev = BLOCK if path in PILE_PRODUCERS else WARN
            fail(sev, "%s reads LEGACY column '%s' which has a fresh_* twin '%s'"
                      % (path, tok, legacy_of[tok]),
                 "Read '%s' instead. The pre-rescan columns hold garbage on real rows -- "
                 'natural_art_background invented a phantom background that dominance-collapsed a '
                 "real shiny Gmax Lapras's sibling." % legacy_of[tok])
    # retired columns
    for col, why in RETIRED_COLS.items():
        for path in PILE_PRODUCERS:
            s = code_only(path)
            if re.search(r"""\[\s*['"]%s['"]\s*\]""" % col, s) or \
                    re.search(r"""\.get\(\s*['"]%s['"]""" % col, s):
                fail(BLOCK, "%s reads RETIRED column '%s'" % (path, col),
                     'Delete the read. %s Reading it invents phantom cosmetic variants that split '
                     'cap groups and pollute the dominance identity set.' % why)
    ok('no pile producer reads a retired column (%s)' % ', '.join(RETIRED_COLS))


# ============================================================================= I4 NO-WRITER COLS
# Scripts that actually write pokemon.db in the sanctioned pipeline (dashboard _recrawl_steps ->
# pogo_pipeline.py, which itself shells out to rank_cache + detect_legacy, plus the recompute and
# mirror steps). A column read by the engine but written by NONE of these is the special_bg_id
# pattern: whatever is in it is a fossil of some retired one-off script.
LIVE_WRITERS = ['pogo_pipeline.py', 'system/scripts/rank_cache.py', 'compute_all_ranks.py',
                'system/scripts/normalize_forms.py', 'cull_v9.py', 'detect_legacy.py',
                'system/scripts/set_db_tags_from_files.py', 'system/scripts/reconcile_tags.py']
WRITER_EXEMPT = {
    'is_legendary': 'roster-backed', 'is_mythical': 'roster-backed',
    'is_ultra_beast': 'roster-backed', 'is_paradox': 'roster-backed',
    # adventure_effects_left: the axis is (col > 0) OR (pid in the configured roster), so a stale
    # column can only ADD keeps -- the direction of harm is over-keeping, never a release. The
    # integrity problem it causes gets its own dedicated finding immediately below.
    'adventure_effects_left': 'roster-backed, and only additive',
}


def written_columns(paths, schema):
    cols = set()
    for p in paths:
        s = code_only(p)
        if not s:
            continue
        for m in re.finditer(r'UPDATE\s+pokemon\s+SET(.{0,6000}?)WHERE', s, re.S | re.I):
            for t in re.findall(r'([A-Za-z0-9_]+)\s*=', m.group(1)):
                if t in schema:
                    cols.add(t)
        for m in re.finditer(r'INSERT\s+(?:OR\s+\w+\s+)?INTO\s+pokemon\s*\(([^)]{0,9000})\)',
                             s, re.S | re.I):
            for t in re.findall(r'[A-Za-z0-9_]+', m.group(1)):
                if t in schema:
                    cols.add(t)
    return cols


def check_no_writer(con, schema, kc):
    section('I4', 'NO-WRITER COLUMNS -- nothing may be READ that nothing WRITES')

    missing_writer_files = [p for p in LIVE_WRITERS if not os.path.exists(p)]
    if missing_writer_files:
        fail(BLOCK, 'pipeline writer script(s) missing from disk: %s' % missing_writer_files,
             'Restore them, or update LIVE_WRITERS in audit_invariants.py. Every column-provenance '
             'answer below is computed from these files.')
    written = written_columns([p for p in LIVE_WRITERS if os.path.exists(p)], schema)
    reads = engine_read_columns(schema)
    orphans = [c for c in reads if c not in written]
    _rare_orphans = []
    for col in orphans:
        nz = con.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND COALESCE(%s,0)!=0'
                         % col).fetchone()[0]
        nul = con.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND %s IS NULL'
                          % col).fetchone()[0]
        if col == 'adventure_effects_left' and 'adventure_effects_left' not in code_only(ENGINE):
            # NOTE the module constant is ENGINE, not KEEP_POLICY -- there has never been a name
            # KEEP_POLICY in this file, and both of these branches carried it until 2026-09-07.
            # They were unreachable (the column is absent from engine_read_columns() the moment
            # keep_policy stops reading it, so `col` is never 'adventure_effects_left'), which is
            # the only reason the audit did not die of NameError. The surviving WARN's DO-line
            # invites the engine to read the column again -- the day someone accepts, this branch
            # becomes live and a typo'd constant would take the whole audit down with it.
            # 2026-09-07: RETIRED from the engine. Offset 0x1F0 is markedRemoteTradable_ (a bool read as
            # i32 by a 2026-05-05 one-off) -- PokemonProto has no per-mon Adventure-Effect charge. The
            # roster governs; preflight_transfer keeps the column only as an additive superset guard.
            ok("column '%s' is retired from keep_policy (mis-identified proto field); roster governs" % col)
            continue
        if col == 'adventure_effects_left':
            fail(WARN, "engine-read column '%s' has NO writer in the sanctioned pipeline "
                       '(%d non-zero, %d NULL in bag)' % (col, nz, nul),
                 'Rule 8 reads it as (col > 0) OR (pid in keep_config.adventure_effect_pids), so '
                 'the ROSTER is the real protection and a stale column can only ADD keeps -- that '
                 'is the only reason this is a WARN. Nothing in the pipeline has populated it '
                 'since a one-off migration, so a newly caught Adventure-Effect mon off the roster '
                 'is invisible to this axis. Wire a writer into pogo_pipeline.parse_pokemon, or '
                 'drop the column term and let the roster decide (see the next finding).')
        elif col in WRITER_EXEMPT:
            # GROUPED, not silenced (2026-09-03): is_legendary / is_mythical / is_paradox /
            # is_ultra_beast are ONE defect -- the same retired one-off (add_species_flags.py)
            # wrote all four, the same rule 5 reads all four behind the same references.RARE_PIDS
            # test, and one fix (a pipeline writer, or dropping the OR-term) closes all four. Four
            # near-identical paragraphs made the reader's eye skip the block that also contains the
            # adventure_effect finding, which is NOT the same defect. Every column name and both of
            # its counts are still printed.
            _rare_orphans.append((col, nz, nul))
        else:
            fail(BLOCK, "engine-read column '%s' has NO writer in the sanctioned pipeline "
                        '(%d non-zero, %d NULL in bag)' % (col, nz, nul),
                 'This is the special_bg_id pattern: an engine decision resting on a column whose '
                 'contents no current script produces. Either add a writer to pogo_pipeline.py, or '
                 'retire the read. Values already in the column are fossils from a one-off script '
                 'and are not evidence of anything.')
    if _rare_orphans:
        fail(WARN, '%d engine-read rare-species flag column(s) have NO writer in the sanctioned '
                   'pipeline: %s' % (len(_rare_orphans),
                                     ', '.join('%s (%d non-zero, %d NULL)' % t
                                               for t in _rare_orphans)),
             'ONE defect, four columns: all of them were written by the retired one-off '
             'add_species_flags.py and all of them are read by rule 5 behind the SAME '
             'references.RARE_PIDS test, which is checked FIRST and was verified above to be a '
             'superset of every DB-flagged rare species -- so these columns can currently only ADD '
             'protection, which is the only reason this is a WARN. They are fossils: is_paradox '
             'holds no non-zero value at all. Either wire a live writer into pogo_pipeline.py or '
             'delete the OR-terms and rely on the roster alone. Whichever you choose, do all four '
             'together -- a partial fix leaves the same hole with fewer signs of it.')
    if not orphans:
        ok('every engine-read column has a writer in the sanctioned pipeline (%d columns)'
           % len(reads))

    # the AE axis specifically: how much of it rests on the orphan column vs the roster?
    if 'adventure_effects_left' in orphans and 'adventure_effects_left' not in code_only(ENGINE):
        ok('adventure_effect axis is roster-only (column term dropped 2026-09-07); off-roster keeps from '
           'the orphan column are no longer possible')
    elif 'adventure_effects_left' in orphans:
        ae = sorted(kc.ae_pids())
        col_only = con.execute(
            'SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND COALESCE(adventure_effects_left,0)>0 '
            'AND pokemon_id NOT IN (%s)' % (','.join(map(str, ae)) or '-1')).fetchone()[0]
        odd = [r[0] for r in con.execute(
            'SELECT DISTINCT adventure_effects_left FROM pokemon WHERE in_bag=1 AND '
            'COALESCE(adventure_effects_left,0) NOT IN (0,1,2,3)')]
        fail(WARN, 'the adventure_effect axis grants a keep to %d mon(s) OUTSIDE the configured '
                   'roster %s purely from that orphan column (implausible values present: %s)'
                   % (col_only, ae, odd),
             'Direction of harm is OVER-keeping, which is why this is a WARN and not a release '
             'risk. Confirm with the user whether the roster alone should decide this axis; if so '
             'drop the column term, otherwise give the column a live pipeline writer so a newly '
             'caught Adventure-Effect mon is actually detected.')

    # 2026-09-08 (user: the AE roster "should be scanned every time"). pogo_pipeline reads the game's own
    # AdventureEffectService registry in-walk -> ae_registry_live.json; derive_ae_roster.py turns it into
    # ae_roster_derived.json; keep_policy UNIONS the derived species into AE_IDS. Here: is that chain alive,
    # and does anything the game calls an Adventure Effect lack protection?
    _der = os.path.join(ROOT, 'system', 'analysis', 'ae_roster_derived.json')
    if not os.path.exists(_der):
        fail(WARN, 'ae_roster_derived.json is MISSING -- the Adventure-Effect roster is running on the hand list only',
             'Run: python system/scripts/derive_ae_roster.py (needs ae_registry_live.json from a recrawl).')
    else:
        _age = (time.time() - os.path.getmtime(_der)) / 86400.0
        try:
            _dd = json.load(open(_der, encoding='utf-8'))
            _unp = [int(x) for x in _dd.get('unprotected', [])]
            # THE REGISTRY'S OWN READ, AGAINST THE WALK BEING JUDGED (2026-09-29, H04). derive_ae_roster.py rewrites the
            # derived file on EVERY pass, so its age read "0 day(s) old" over a registry the fail-soft in-walk read had
            # not refreshed at all. keep_policy's per-mon rule (ae_moves) reads ae_registry_live.json itself: judge THAT.
            _rg_this, _rg_when, _walk = None, None, None
            try:
                import calendar as _cal
                _rgd = json.load(open(os.path.join(ROOT, 'system', 'analysis', 'ae_registry_live.json'), encoding='utf-8'))
                _rg_when = _cal.timegm(time.strptime(str(_rgd.get('generated'))[:19], '%Y-%m-%dT%H:%M:%S'))   # UTC
                _walk = con.execute('SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1').fetchone()[0]    # local
                if _walk:
                    _rg_this = _rg_when >= time.mktime(time.strptime(str(_walk)[:19], '%Y-%m-%dT%H:%M:%S')) - 5
            except Exception:
                pass
            _rg_age = ((time.time() - _rg_when) / 86400.0) if _rg_when else _age
            if _unp:
                fail(BLOCK, 'the GAME lists Adventure-Effect species that NOTHING in keep_config protects: %s' % _unp,
                     'Add them to keep_config.adventure_effect_pids. keep_policy unions the derived set defensively, '
                     'but the configured roster is the documented law and must catch up.')
            elif _rg_this is False:
                fail(WARN, 'the live Adventure-Effect registry was NOT re-read by the walk being judged (registry read %s, '
                           'walk %s) -- every Adventure-Effect keep and the AE tag were judged on that older read'
                           % (time.strftime('%Y-%m-%d %H:%M', time.localtime(_rg_when)), _walk),
                     'The in-walk read (pogo_pipeline.step_read_ae_registry) is fail-soft and left the old json in place: '
                     'find its "[ae_registry] read FAILED" line in system/analysis/last_job_api_recrawl.log. '
                     'ae_roster_derived.json is rewritten every pass, so its age proves nothing about the registry.')
            elif _rg_age > 14:
                fail(WARN, 'ae_registry_live.json is %.0f days old -- the live registry has not been re-read' % _rg_age,
                     'A recrawl refreshes ae_registry_live.json; full_audit runs derive_ae_roster.py after it.')
            else:
                ok('live Adventure-Effect registry -> %d species derived, all protected (registry read %s)'
                   % (len(_dd.get('species', [])), 'by the walk being judged' if _rg_this else '%.0f day(s) ago' % _rg_age))
        except Exception as _e:
            fail(WARN, 'ae_roster_derived.json unreadable (%s)' % _e, 'Re-run derive_ae_roster.py.')

    # WALK INPUTS BELONG TO THE WALK BEING JUDGED (2026-09-29, H04). Each in-walk read below is FAIL-SOFT: a failed
    # read logs one [WARN] line in the recrawl log and leaves the PREVIOUS walk's file in place, and every consumer
    # used it as this walk's -- the candy budget by a 2 h wall clock, the rest with no check at all. After
    # switch_account.py they are another trainer's files. ONE rule for all of them: evolvable_forms._walk_fresh
    # (written by the walk that stamped pokemon.db MAX(last_scanned), inside the in-walk window).
    try:
        import evolvable_forms as _efw
        _wk = con.execute('SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1').fetchone()[0]
        _inputs = (('system/analysis/candy.json', 'the candy budget of every Evolve promise and slot hold'),
                   ('system/analysis/inventory.json', 'the evolution items those promises need'),
                   ('system/analysis/showcase_gm_live.json', 'the XXL showcase scores (size_line)'),
                   ('pokedex_hundos_live.json', "the evolution graph's registered species (keep_policy)"))
        _old = []
        for _rel, _use in _inputs:
            _pp = os.path.join(ROOT, *_rel.split('/'))
            if _wk and os.path.exists(_pp) and not _efw._walk_fresh(_pp, 7200, _wk):
                _old.append('%s (written %s: %s)' % (os.path.basename(_pp), ts(mtime(_pp)), _use))
        if not _wk:
            info('walk inputs: pokemon.db carries no last_scanned stamp -- they cannot be tied to a walk')
        elif _old:
            fail(WARN, '%d walk input(s) were NOT written by the walk being judged (%s): %s'
                       % (len(_old), _wk, '; '.join(_old)),
                 'Each is a fail-soft in-walk read that left the previous file in place (find its [WARN] line in '
                 'system/analysis/last_job_api_recrawl.log), or another trainer\'s file after switch_account.py. The '
                 'engine treats unread candy/items as UNKNOWN (held, no Evolve label); the others are used as they are. '
                 'Recrawl before trusting this pile.')
        else:
            ok('walk inputs (candy, inventory, showcase game data, pokedex) were all written by the walk being judged (%s)'
               % _wk)
    except Exception as _e:
        fail(WARN, 'could not tie the walk inputs to the judged walk (%s)' % _e, 'Check evolvable_forms._walk_fresh.')

    # 2026-09-08 (user: "I suspected that new cards or backgrounds and such weren't being found"): the card IDS
    # were always read off the proto, but the NAME table (location_card_enum.json) had gone stale (280 names vs
    # 411 live). pogo_pipeline now refreshes it in-walk; this is the backstop: any card id in the bag with no
    # name means the refresh is not running.
    try:
        _cn = json.load(open(os.path.join(ROOT, 'location_card_enum.json'), encoding='utf-8'))
        _ids = [r[0] for r in con.execute('SELECT DISTINCT fresh_loc_card_enum FROM pokemon WHERE in_bag=1 '
                                          'AND fresh_has_location_card=1 AND COALESCE(fresh_loc_card_enum,0)<>0')]
        _unk = sorted(i for i in _ids if str(i) not in _cn)
        if _unk:
            fail(WARN, '%d location-card/background id(s) in the bag have NO NAME in location_card_enum.json: %s'
                       % (len(_unk), _unk[:12]),
                 'The in-walk refresh (pogo_pipeline.step_refresh_location_card_enum) is not landing -- check the '
                 'recrawl job log for [loc_card_enum]. Caps still group by id, so this is a naming gap, not a keep risk.')
        else:
            ok('every location-card/background id in the bag resolves to a name (%d ids, %d names known)' % (len(_ids), len(_cn)))
    except Exception as _e:
        fail(WARN, 'location_card_enum.json unreadable (%s)' % _e, 'Re-run a recrawl; the walk refreshes it.')

    # retired columns must have no writer AND no engine reader (both halves)
    for col, why in RETIRED_COLS.items():
        if col in written:
            fail(WARN, "retired column '%s' still has a pipeline writer" % col,
                 'Remove the write. Keeping a retired column fed invites a future reader.')
        else:
            ok("retired column '%s': no writer, no engine reader" % col)


# ============================================================================= I5 PARTITION
def check_partition(con):
    section('I5', 'PARTITION -- policy_reasons + Transfer exactly covers in_bag, zero overlap')

    bag = {r[0] for r in con.execute('SELECT uid_hex FROM pokemon WHERE in_bag=1')}
    try:
        reasons = json.load(open(os.path.join(ANA, 'policy_reasons.json'), encoding='utf-8'))
    except Exception as e:
        fail(BLOCK, 'policy_reasons.json unreadable (%s)' % e,
             'Re-run keep_policy.py. Without the reason map nothing can explain why a mon is kept.')
        return
    kept = {u for u in reasons if not u.startswith('_')}     # '_meta'-style stamps are not mons
    try:
        pile = {u for u in open(os.path.join(TD, '6_Transfer.txt')).read().split() if u}
    except Exception as e:
        fail(BLOCK, '6_Transfer.txt unreadable (%s)' % e, 'Re-run keep_policy.py.')
        return

    overlap = kept & pile
    if overlap:
        fail(BLOCK, '%d uid(s) are BOTH kept and piled: %s' % (len(overlap), sorted(overlap)[:8]),
             'A mon with a keep reason is in the irreversible pile. Re-run keep_policy.py; if it '
             'persists the engine is emitting a reason after the pile is computed, which means the '
             'pile no longer reflects the reasons that justify it.')
    else:
        ok('keep set and pile are disjoint (%d kept, %d piled)' % (len(kept), len(pile)))

    for label, s in (('kept', kept), ('piled', pile)):
        stray = s - bag
        if stray:
            fail(BLOCK, '%d %s uid(s) are not in_bag: %s' % (len(stray), label, sorted(stray)[:8]),
                 'The pile/reason map describes mons that are no longer in the bag (traded, '
                 'released, or a stale artifact). RECRAWL, then re-run keep_policy.py -- never '
                 'sync a pile computed against a bag that has moved on.')
    uncovered = bag - kept - pile
    if uncovered:
        fail(BLOCK, '%d in-bag mon(s) are NEITHER kept nor piled: %s'
                    % (len(uncovered), sorted(uncovered)[:8]),
             'The partition is broken -- these mons have no recorded decision at all. Re-run '
             'keep_policy.py. A mon with no decision is invisible to every audit downstream.')
    if not uncovered and not (kept - bag) and not (pile - bag) and not overlap:
        ok('exact partition: %d kept + %d piled = %d in_bag' % (len(kept), len(pile), len(bag)))

    # every emitted reason must be a declared axis
    emitted = {r for rs in reasons.values() if isinstance(rs, list) for r in rs}
    unknown = sorted(emitted - set(REASON_TO_AXIS))
    if unknown:
        fail(BLOCK, 'policy_reasons.json contains undeclared keep reason(s): %s' % unknown,
             'A keep axis is live that this registry does not know about, so nothing here (or in '
             'the four re-derivation audits) is checking whether it is capped or keep-all. Add it '
             'to AXES/MARK_MODEL in audit_invariants.py.')
    else:
        ok('every emitted keep reason maps to a declared axis (%d reasons in use)' % len(emitted))

    # the pushed tagsets must agree with the pile
    tf = os.path.join(TD, 'Transfer.txt')
    if os.path.exists(tf):
        pushed = {u for u in open(tf).read().split() if u}
        if pushed != pile:
            fail(BLOCK, 'Transfer.txt (%d) != 6_Transfer.txt (%d), symmetric difference %d'
                        % (len(pushed), len(pile), len(pushed ^ pile)),
                 'build_tagsets.py re-emits the pile as Transfer.txt; run it. prune_tags pushes '
                 'Transfer.txt, so any gap is a pile the engine never authorised.')
        else:
            ok('Transfer.txt matches the computed pile exactly (%d uids)' % len(pile))
    # INVARIANT build_tagsets promises: no KEEP tag may hold a pile member (advice tags -- the evolve tags, Power Up,
    # Unlock 2nd Move -- included: they ride on kept mons only, 2026-09-26; the fold 2026-09-29)
    _held = False
    for fn in sorted(os.listdir(TD)) if os.path.isdir(TD) else []:
        if not fn.endswith('.txt') or fn in ('Transfer.txt', '6_Transfer.txt'):
            continue
        mem = {u for u in open(os.path.join(TD, fn)).read().split() if u}
        bad = mem & pile
        if bad:
            _held = True
            fail(BLOCK, 'keep tagset %s holds %d pile member(s): %s'
                        % (fn, len(bad), sorted(bad)[:6]),
                 "build_tagsets subtracts Transfer from every keep tag at the end -- re-run it. A "
                 "keep tag that names a pile member tells the user, on the phone, that a mon is "
                 "both a keeper and fodder.")
    if not _held:                   # (2026-09-26) was printed even after a failure above
        ok('no keep tagset contains a pile member')


# ============================================================================= I6 SINGLE PUSH PATH
# The sanctioned push path, from dashboard._push_steps():
#     prune_tags.py --atomic  ->  refresh_evolve_shiny.py  ->  set_db_tags_from_files.py (DB mirror)
# gated by dashboard._gate_steps() (preflight_transfer.py) which must run BEFORE any of them.
SANCTIONED_PUSH = {'system/scripts/prune_tags.py', 'system/scripts/refresh_evolve_shiny.py'}
PUSH_PRIMITIVE = 'system/scripts/tag_ops.py'
# The tag-write primitives, split by DIRECTION. Only an ADD can put a mon into a release pile;
# untag_one can only take one out, so a removal-only tool cannot cause a release and is censused
# rather than flagged.
TAG_ADD_FUNCS = {'apply_members', 'apply_changes', 'bulk_apply_changes', 'bulk_tag_many',
                 'set_tags', 'bulk_tag_single', 'bulk_tag_one'}
TAG_REMOVE_FUNCS = {'untag_one', 'bulk_untag_one'}
TAG_WRITE_FUNCS = TAG_ADD_FUNCS | TAG_REMOVE_FUNCS | {'create_tag'}

# ---- bulk_tag.js RPC exports, BY DIRECTION -----------------------------------------------------
# Loading bulk_tag.js is not a push. The library has 40 exports and only five of them can put a mon
# INTO a tag; the rest read, probe, dump, create an empty tag definition, or REMOVE membership.
# Classified 2026-09-03 by reading each body in bulk_tag.js, not by name:
#   ADD      bulkTagMany:919  bulkApplyChanges:1029  bulkTagSingle:1152  bulkTagOne:1314  tagOne:2143
#   REMOVE   bulkUntagOne:815  setPokemonTagsNull:1267 (nulls the whole list -- destructive, but it
#            cannot ADD a mon to the release pile, which is the question this invariant asks)
#   CREATE   addTagOnInstance:1466  addTagTest:2068  addTagVerified:1906 -- a tag DEFINITION with no
#            members; the python primitive create_tag is treated the same way, as neither direction
#   READ     the remaining 32 (countTagsByName, 2026-09-30: the duplicate-name guard; tagsByName, 2026-10-29: the
#            same walk, every name at once)
# Names are canonicalised (lowercased, underscores dropped) because frida exposes JS camelCase to
# python as snake_case, so the same export appears as bulkTagMany and bulk_tag_many.
def _canon(n):
    return n.replace('_', '').lower()


_BT_ADD = {_canon(x) for x in ('bulkTagMany', 'bulkApplyChanges', 'bulkTagSingle', 'bulkTagOne',
                               'tagOne')}
_BT_REMOVE = {_canon(x) for x in ('bulkUntagOne', 'setPokemonTagsNull')}
_BT_SAFE = {_canon(x) for x in (
    'addTagOnInstance', 'addTagTest', 'addTagVerified', 'countTags', 'countTagsByName', 'tagsByName', 'discoverMethods',
    'dumpCapturedList', 'dumpRepeatedField', 'enumerateTagProtos', 'extractAllTagIds',
    'extractRuntimeFlags', 'findAllInstances', 'findPokemonProto', 'findRealInstance',
    'findTagIdByName', 'getAllTagsTest', 'getCaptured', 'getListClassForSetTags',
    'getPokemonForTag', 'getPokemonTags', 'hookForRealInstance', 'indexPokemon', 'initStatus',
    'listAllTagDefinitions', 'listAllTags', 'probeMethodInfo', 'probePokemonDisplayProtoFields',
    'probePokemonProtoFields', 'probePokemonTagChanges', 'probePokemonTagChangesFields',
    'probeRepeatedField', 'readDisplayProto', 'readPokemonTagProto', 'validateInstance')}
_BT_KNOWN = _BT_ADD | _BT_REMOVE | _BT_SAFE
# Strings that mean "this script handles the RELEASE pile", not merely some label tag.
#
# 'tagsets' WAS in this tuple and was removed 2026-09-07. It is the name of a DIRECTORY
# (system/analysis/tagsets), so os.path.join(HERE, 'system', 'analysis', 'tagsets') matched it --
# and push_armored_tags.py, whose PLAN is hardcoded to {'Armored UL', 'Armored ML'}, which parses
# no argument but --dry-run and so has no way to be pointed at another tag, and which contains no
# Transfer string of any kind, was classified a RELEASE-pile pusher on the strength of one path
# segment. That misclassification is what turned the granular_tags edge below into a BLOCK on the
# sync gate. What the token was actually reaching for is covered exactly, and only, by
# _enumerates_tagset_dir(): a script that LISTS that directory picks Transfer.txt up without ever
# naming it, and is still a pile pusher. Verified before removing it that no other census member
# depends on the token: of the 42 tag-ADD scripts, push_armored_tags.py was the only one whose
# pile classification changed.
PILE_STRINGS = ('Transfer', '6 Transfer', '6_Transfer.txt', 'Transfer.txt', 'CLAUDE_TX',
                'cull_decision_v9')

#: Directory-listing calls. A script that runs one of these over the tagset directory handles
#: every tagset in it, Transfer.txt included, without naming any of them.
_DIR_ENUM = {'listdir', 'scandir', 'walk', 'glob', 'iglob', 'iterdir', 'rglob'}


def _enumerates_tagset_dir(path):
    """True if this file ENUMERATES the tagset directory rather than naming specific files."""
    if 'tagsets' not in src(path):
        return False
    t = tree(path)
    if t is None:
        return True                 # names the directory and will not parse: assume the worst
    for n in ast.walk(t):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else '')
        if nm in _DIR_ENUM:
            return True
    return False
# The sanctioned entry points. "Reachable" means reachable FROM ONE OF THESE, not "mentioned
# somewhere". An earlier version called apply_tagsets.py reachable because one scratch analysis
# file listed its path in a dict, and called pogo_pipeline.py unreachable-from-nothing while it is
# itself an entry point -- both answers were useless.
ENTRY_POINTS = {'dashboard.py', 'full_audit.py', 'pogo_pipeline.py', 'verify_tags_live.py',
                'system/scripts/keep_policy.py', 'system/scripts/build_tagsets.py',
                'system/scripts/preflight_transfer.py', 'system/scripts/prune_tags.py',
                'system/scripts/refresh_evolve_shiny.py',
                'system/scripts/set_db_tags_from_files.py', 'system/scripts/reconcile_tags.py',
                'read_player_state.py'}


@_memoized
def _ast_strings(path):
    """Every string CONSTANT in real code (docstrings excluded)."""
    t = tree(path)
    if t is None:
        return set()
    doc_ids = set()
    for n in ast.walk(t):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = getattr(n, 'body', None)
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant):
                doc_ids.add(id(b[0].value))
    return {n.value for n in ast.walk(t)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids}


@_memoized
def tag_write_sites(path):
    """(add_sites, remove_sites) -- where this file actually CALLS a tag-write primitive.

    AST, not text. The first version of this check grepped for the primitive NAMES and produced
    fifty false positives: full_audit.py 'pushes tags' because one log filter reads
    `if 'apply_changes' in l`, and this harness matched its own regex. A census that noisy is worse
    than none -- the two real findings were buried in it.
    """
    t = tree(path)
    if t is None:
        return [], []
    imported = set()
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and (n.module or '').endswith('tag_ops'):
            imported |= {a.asname or a.name for a in n.names}
    adds, rems = [], []
    for n in ast.walk(t):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else '')
        if not nm:
            continue
        if isinstance(f, ast.Name) and nm not in imported and nm not in TAG_WRITE_FUNCS:
            continue
        if nm in TAG_ADD_FUNCS:
            adds.append((n.lineno, '%s()' % nm))
        elif nm in TAG_REMOVE_FUNCS:
            rems.append((n.lineno, '%s()' % nm))
    # ---- the Frida route, resolved BY DIRECTION (2026-09-03) ------------------------------------
    # The previous rule was "this file mentions bulk_tag.js or SetPokemonTags -> it is an ADD".
    # bulk_tag.js is a 40-export LIBRARY that every tag tool in this project loads, so that rule
    # reported half the census wrongly: of the 28 scripts it named as dormant RELEASE-pile pushers,
    # 14 could not add a mon to a tag at all -- 8 pure readers (find_tag_id, find_fp, verify_all,
    # get_authoritative_tagged, full_pipeline, _dump_tags_from_svc, _dump_claudetx_binding,
    # find_dmax_gmax_in_cull), 5 removal-only untaggers, and add_real_tag.py which only creates an
    # empty tag DEFINITION. The docstring above says a census that noisy is worse than none,
    # because the real findings drown in it; that applied to this rule too. So: read which exports
    # the file actually CALLS and classify those. Unknown or unreadable dispatch still counts as an
    # ADD -- ignorance is never the safe answer in front of an irreversible pile.
    strs = _ast_strings(path)
    raw_rpc = any('SetPokemonTags' in x for x in strs)
    loads_bt = any('bulk_tag.js' in x for x in strs)
    if raw_rpc:
        # names the tag-write RPC inside its OWN injected JS: a hand-rolled writer, unchanged.
        adds.append((0, 'raw Frida SetPokemonTags'))
    elif loads_bt:
        called = {_canon(x) for x in _frida_exports_called(path)}
        local = {_canon(x) for x in _frida_exports_defined(strs)}
        unknown = sorted(called - _BT_KNOWN - local)
        if called & _BT_ADD:
            adds.append((0, 'bulk_tag.js %s()' % sorted(called & _BT_ADD)[0]))
        elif unknown:
            adds.append((0, 'bulk_tag.js, UNKNOWN export(s) %s' % unknown[:3]))
        elif not called:
            adds.append((0, 'bulk_tag.js loaded, no resolvable export call'))
        elif called & _BT_REMOVE:
            rems.append((0, 'bulk_tag.js %s()' % sorted(called & _BT_REMOVE)[0]))
    return adds, rems


def _frida_exports_called(path):
    """Export names this file invokes on a frida script handle: <x>.exports[_sync|_async].NAME.

    AST-only on purpose. The names also appear as DEFINITIONS inside the inline-JS string literals
    ('rpc.exports.readProtoUid = function'), and a text scan cannot tell a definition from a call.
    """
    t = tree(path)
    if t is None:
        return set()
    out = set()
    for n in ast.walk(t):
        if not isinstance(n, ast.Attribute):
            continue
        v = n.value
        if isinstance(v, ast.Attribute) and v.attr in ('exports', 'exports_sync', 'exports_async'):
            out.add(n.attr)
        elif isinstance(v, ast.Name) and v.id in ('exports', 'exports_sync'):
            out.add(n.attr)
    for n in ast.walk(t):
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute)                 and n.value.attr in ('exports', 'exports_sync', 'exports_async')                 and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
            out.add(n.slice.value)
    return out


def _frida_exports_defined(strs):
    """Export names the file DEFINES in its own inline JS -- known-local, not unknown dispatch."""
    out = set()
    for x in strs:
        out |= set(re.findall(r'rpc\.exports\.([A-Za-z0-9_]+)\s*=', x))
        out |= set(re.findall(r'(?m)^\s*([A-Za-z0-9_]+)\s*:\s*function', x))
    return out


_FILE_RE = re.compile(r'\b([A-Za-z0-9_]+)\.py\b')
_IMP_RE = re.compile(r'(?m)^\s*(?:import|from)\s+([A-Za-z0-9_.]+)')
_NOSTR = {}


@_memoized
def code_no_strings(path):
    """code_only() with every STRING LITERAL blanked too. Line numbers preserved.

    A filename inside a string is only sometimes a call. `os.path.join(SCR, 'prune_tags.py')` IS
    how the dashboard invokes every stage, so string constants cannot simply be dropped from the
    reachability scan -- doing that severs every real edge in the sanctioned pipeline and turns
    live pushers into 'dormant' WARNs. But `owner='push_armored_tags.py (one-shot)'`, a
    DOCUMENTATION field in granular_tags.EXEMPT_TAGSETS, is not a call, and matching it fabricated
    a reachability edge that BLOCKed the sync gate (2026-09-07). So the two are separated: this
    helper supplies the structural half (filenames appearing OUTSIDE any string), and
    _looks_like_command() decides which string constants are argv/paths rather than prose.
    """
    if path in _NOSTR:
        return _NOSTR[path]
    c = code_only(path)
    if not c:
        _NOSTR[path] = ''
        return ''
    lines = c.split('\n')
    strtypes = {tokenize.STRING}
    for nm in ('FSTRING_START', 'FSTRING_MIDDLE', 'FSTRING_END'):
        if hasattr(tokenize, nm):
            strtypes.add(getattr(tokenize, nm))
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src(path)).readline))
    except Exception:
        # Cannot tokenize -> keep every mention. Over-reporting reachability is the safe
        # direction in front of an irreversible pile; under-reporting is not.
        _NOSTR[path] = c
        return c
    for tok in toks:
        if tok.type not in strtypes:
            continue
        (r1, c1), (r2, c2) = tok.start, tok.end
        for r in range(r1, r2 + 1):
            if not (1 <= r <= len(lines)):
                continue
            ln = lines[r - 1]
            a = min(c1 if r == r1 else 0, len(ln))
            b = min(c2 if r == r2 else len(ln), len(ln))
            if b > a:
                lines[r - 1] = ln[:a] + ' ' * (b - a) + ln[b:]
    _NOSTR[path] = '\n'.join(lines)
    return _NOSTR[path]


#: Words that can legitimately sit next to a script name in a command string.
_RUNNER_TOKENS = {'python', 'python3', 'py', 'pythonw', 'sys.executable', 'exec', 'start',
                  '&&', '||', ';', '|', 'cmd', '/c', '/k', '-m', 'uv', 'poetry', 'nohup'}
_PATHY = re.compile(r'^[\w.+~$%{}:@!/\\-]+$')


def _looks_like_command(s):
    """True if this string constant is an argv element / command line naming a .py, not prose.

    Three accepted shapes, deliberately narrow:
      (i)   the WHOLE string is one path token ending in .py   -- os.path.join(SCR,'prune_tags.py')
      (ii)  ANY token is a runner word and some token names a .py
                                                               -- 'cd x && python system/scripts/y.py'
      (iii) it starts with the .py and every later token is a flag or a path
                                                               -- 'prune_tags.py --atomic'
    Everything else is prose. 'push_armored_tags.py (one-shot)' fails (iii) on '(one-shot)';
    'Run gen_line_report.py first.' fails all three because its first token is a bare word.
    """
    if len(s) > 400 or chr(10) in s:
        return False        # a command is one line; this is an inline-JS blob or a paragraph
    toks = s.strip().split()
    if not toks or not any(_FILE_RE.search(t) for t in toks):
        return False
    if len(toks) == 1:
        return bool(_PATHY.match(toks[0]) and toks[0].endswith('.py'))
    if any(t in _RUNNER_TOKENS for t in toks):
        # ANY position, not just the first: `cd x && python pusher.py` and `nohup python -m x` are
        # real invocations. Measured cost on the current tree: 6 extra prose strings admitted, all
        # of them DO-lines of the form "Re-run: python keep_policy.py", all naming NON-pushers, so
        # they produce no finding at all. That asymmetry is deliberate -- a MISSED edge downgrades
        # a live unsanctioned pusher from BLOCK to a dormant WARN, and being wrong in THAT
        # direction is what this whole invariant exists to prevent.
        return True
    if not toks[0].endswith('.py') or not _PATHY.match(toks[0]):
        return False
    for t in toks[1:]:
        if t.startswith('-') or t in _RUNNER_TOKENS:
            continue
        if _PATHY.match(t) and ('/' in t or '\\' in t or '.' in t):
            continue
        return False
    return True


def _invokes(path):
    """Scripts `path` actually runs or imports: an import of the stem, or its .py named in code.

    Indexed by stem rather than tested pairwise. The pairwise form compiled 736x736 regexes and
    took 34 seconds -- unusable in full_audit, which runs the audits in parallel and expects each
    to finish in well under a second.

    A .py named inside a PROSE string constant is not a call (see code_no_strings): a name in a
    DO-line, an error message or a registry's `owner=` documentation field is a mention, and
    treating it as an edge put an unsanctioned-pusher BLOCK on the sync gate for a script that
    cannot name the pile at all.
    """
    c = code_no_strings(path)
    if not c:
        return set()
    stems = set(_FILE_RE.findall(c))
    for s in _ast_strings(path):
        if _looks_like_command(s):
            stems |= set(_FILE_RE.findall(s))
    stems |= {m.split('.')[-1] for m in _IMP_RE.findall(c)}
    stems |= {m.split('.')[0] for m in _IMP_RE.findall(c)}
    out = set()
    for s in stems:
        for q in _STEM_INDEX[0].get(s, ()):
            if q != path:
                out.add(q)
    return out


_STEM_INDEX = [{}]
_CLOSURE = [None]


def build_stem_index(files):
    idx = defaultdict(set)
    for q in files:
        idx[os.path.splitext(os.path.basename(q))[0]].add(q)
    _STEM_INDEX[0] = idx


def entry_closure():
    """Every script transitively reachable FROM a sanctioned entry point."""
    if _CLOSURE[0] is not None:
        return _CLOSURE[0]
    seen, stack = set(), [p for p in ENTRY_POINTS if os.path.exists(p)]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        stack.extend(q for q in _invokes(p) if q not in seen)
    _CLOSURE[0] = seen
    return seen


def optin_flag(path, add_sites):
    """If every tag-ADD in this file sits behind an argparse flag, return that flag, else None.

    pogo_pipeline.py is the case this exists for: it is a sanctioned ENTRY POINT that also contains
    a second, ungated pile pusher (`--tag-transfers`, which tags the RETIRED cull_v9 TRANSFER set
    as CLAUDE_TX via bulk_tag.js). Calling that 'reachable' with no qualifier would be alarmist --
    the dashboard never passes the flag -- and calling it unreachable would be false.
    """
    t = tree(path)
    if t is None:
        return None
    parent = {}
    for n in ast.walk(t):
        for ch in ast.iter_child_nodes(n):
            parent[ch] = n
    # the functions containing an add site, plus the module itself
    hosts = set()
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for b in ast.walk(n):
                if isinstance(b, ast.Call) and b.lineno in {ln for ln, _ in add_sites}:
                    hosts.add(n.name)
    pos, neg = set(), set()
    for n in ast.walk(t):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in hosts):
            continue
        cur = n
        while cur in parent:
            cur = parent[cur]
            if not isinstance(cur, ast.If):
                continue
            negated = set()
            for u in ast.walk(cur.test):
                if isinstance(u, ast.UnaryOp) and isinstance(u.op, ast.Not):
                    for a in ast.walk(u.operand):
                        if isinstance(a, ast.Attribute):
                            negated.add(a.attr)
            for a in ast.walk(cur.test):
                if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) \
                        and a.value.id in ('args', 'a', 'opts'):
                    # `if args.tag_transfers and not args.dry_run:` -- the POSITIVE term is the
                    # opt-in; --dry-run is a global safety switch, not the gate being described.
                    (neg if a.attr in negated else pos).add('--' + a.attr.replace('_', '-'))
    return sorted(pos)[0] if pos else (sorted(neg)[0] if neg else None)


PILE_TAG = 'Transfer'
PRUNER = 'system/scripts/prune_tags.py'
PREFLIGHT = 'system/scripts/preflight_transfer.py'
_STAMP_RE = re.compile(r'[A-Za-z0-9_.-]*stamp[A-Za-z0-9_.-]*\.json')
_GATE_RE = re.compile(r'stamp|preflight', re.I)
_BYPASS_RE = re.compile(r'force|skip|no_?gate|unsafe|override', re.I)


def _stamp_artifact(path):
    """The receipt the pre-flight gate writes, discovered from its own source rather than
    hardcoded here: a string constant naming a *stamp*.json."""
    for s in sorted(_ast_strings(path)):
        m = _STAMP_RE.fullmatch(s.strip())
        if m:
            return m.group(0)
    return None


def _top_fns(path):
    t = tree(path)
    return {} if t is None else {n.name: n for n in t.body
                                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _called_names(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            out.add(n.func.id)
    return out


def _gate_closure(path, stamp):
    """(seed, closure) -- the functions that IMPLEMENT the stamp gate in `path`.

    seed     top-level functions named for the gate, or whose body names the stamp artifact or
             any stamp/preflight identifier.
    closure  seed plus every local function they call, transitively -- because the refusal
             usually lives one call down (`require_preflight_stamp()` -> `_stamp_refuse()` ->
             sys.exit(2)), and a fixed line-window around the mention misses it.
    """
    fns = _top_fns(path)
    seed = set()
    for name, n in fns.items():
        if _GATE_RE.search(name):
            seed.add(name)
            continue
        for u in ast.walk(n):
            if isinstance(u, ast.Constant) and isinstance(u.value, str) and stamp in u.value:
                seed.add(name)
                break
            if isinstance(u, ast.Name) and _GATE_RE.search(u.id):
                seed.add(name)
                break
            if isinstance(u, ast.Attribute) and _GATE_RE.search(u.attr):
                seed.add(name)
                break
    closure, stack = set(seed), list(seed)
    while stack:
        cur = stack.pop()
        for c in _called_names(fns[cur]) if cur in fns else ():
            if c in fns and c not in closure:
                closure.add(c)
                stack.append(c)
    return seed, closure


def _has_refusal(path, names):
    """True if any of these top-level functions raises or exits non-zero."""
    fns = _top_fns(path)
    for nm in names:
        n = fns.get(nm)
        if n is None:
            continue
        for u in ast.walk(n):
            if isinstance(u, ast.Raise):
                return True
            if isinstance(u, ast.Call):
                f = u.func
                fn = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else '')
                if fn in ('exit', '_exit', 'SystemExit', 'abort'):
                    return True
    return False


# --------------------------------------------------------------- pile-refusal gates, by AST
# WHY THIS IS AST AND NOT A SUBSTRING TEST (2026-09-07)
# code_only() blanks comments and docstrings -- and NOTHING ELSE. An ordinary string literal
# survives it intact, so the first version of the pile-pusher exemption,
#     ('is_pile_tag(' in code_only(p) or '_is_pile(' in code_only(p))
#          and ('sys.exit(' in code_only(p) or 'SystemExit' in code_only(p))
# was satisfiable by a file that never calls the function at all: print("run is_pile_tag() first")
# supplies the first token, and any unrelated sys.exit() anywhere in the file supplies the second.
# That certifies an UNGATED release-pile pusher as gated, which is the one direction this census
# is not allowed to be wrong in. What counts as a gate now is structural: a real CALL to
# is_pile_tag()/_is_pile() whose own `if` (or `assert`) refuses in the branch that call selects,
# sited BEFORE every tag-ADD primitive in the file.
_PILE_REFUSAL_FUNCS = frozenset({'is_pile_tag', '_is_pile'})
_EXIT_FUNCS = frozenset({'exit', '_exit', 'SystemExit', 'abort'})


def _parent_map(t):
    """child node id -> parent node, for one parsed tree."""
    par = {}
    for n in ast.walk(t):
        for c in ast.iter_child_nodes(n):
            par[id(c)] = n
    return par


def _walk_flow(node):
    """ast.walk that does NOT descend into nested def/lambda/class bodies.

    A `raise` sitting inside a helper that is merely DEFINED in the refusal branch is not a
    refusal the branch performs; only code the branch itself runs counts.
    """
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        for c in ast.iter_child_nodes(n):
            if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            stack.append(c)


def _call_name(n):
    f = getattr(n, 'func', None)
    return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else '')


def _stmts_refuse(stmts):
    """True if this statement list itself raises or exits non-zero."""
    for s in stmts:
        for u in _walk_flow(s):
            if isinstance(u, ast.Raise):
                return True
            if isinstance(u, ast.Call) and _call_name(u) in _EXIT_FUNCS:
                return True
    return False


def _pile_alias_names(scope):
    """Local names bound EXACTLY ONCE, directly from an is_pile_tag()/_is_pile() call.

    tag_ops.cmd_apply does `pile = is_pile_tag(tag_name)` and then guards TWO separate blocks
    with `if pile:` (part A refuses without the explicit flag, part B runs preflight_gate and
    refuses on its verdict). That gate is branch-scoped and correct, and a checker that only
    recognises the call written inline in the `if` reports it as an ungated CLI -- a confident
    wrong answer, which is worse than the substring test it replaced. One binding only: a name
    rebound anywhere else in the same scope is no longer a reliable stand-in for the call.
    """
    counts, aliases = {}, set()
    # EVERY binding of a name, however it is written -- assignment, tuple unpack, for-target,
    # with-as, except-as, walrus, augassign. Counting only `x = ...` would miss `x, y = ...` and
    # then trust a name that IS rebound, which is the direction that over-exempts.
    for n in ast.walk(scope):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            counts[n.id] = counts.get(n.id, 0) + 1
        elif isinstance(n, ast.ExceptHandler) and n.name:
            counts[n.name] = counts.get(n.name, 0) + 1
    for n in ast.walk(scope):
        tgt, val = None, None
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            tgt, val = n.targets[0].id, n.value
        elif isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
            tgt, val = n.target.id, n.value
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
            tgt, val = n.target.id, n.value
        if tgt and isinstance(val, ast.Call) and _call_name(val) in _PILE_REFUSAL_FUNCS:
            aliases.add(tgt)
    return {a for a in aliases if counts.get(a) == 1}


def _mentions_pile(node, aliases):
    """True if this expression asks 'is this the release pile?' -- by call or by single alias."""
    for c in ast.walk(node):
        if isinstance(c, ast.Call) and _call_name(c) in _PILE_REFUSAL_FUNCS:
            return True
        if isinstance(c, ast.Name) and c.id in aliases:
            return True
    return False


def _negated_pile(node, aliases):
    """True if the pile question appears anywhere under a `not`."""
    return any(isinstance(c, ast.UnaryOp) and isinstance(c.op, ast.Not)
               and _mentions_pile(c.operand, aliases) for c in ast.walk(node))


def _pile_guards(path):
    """Every `if <is-this-the-pile>:` / `assert not <is-this-the-pile>` in this file, as
    (lineno, refuses, runs_preflight_gate, enclosing_function_name_or_None)."""
    t = tree(path)
    if t is None:
        return []
    par = _parent_map(t)
    fn_of, alias_of = {}, {}

    def scope_of(node):
        cur = par.get(id(node))
        while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                       ast.Module)):
            cur = par.get(id(cur))
        return cur if cur is not None else t

    def aliases_for(node):
        s = scope_of(node)
        if id(s) not in alias_of:
            alias_of[id(s)] = _pile_alias_names(s)
            fn_of[id(s)] = getattr(s, 'name', None)
        return alias_of[id(s)], fn_of[id(s)]

    out = []
    for u in ast.walk(t):
        if isinstance(u, ast.Assert):
            al, fn = aliases_for(u)
            # An assert only RAISES on a pile when the pile question is negated
            # (`assert not is_pile_tag(TAG)`). It is also strippable by `python -O`, so it is
            # a weaker gate than a real `if` + exit -- accepted, but never preferred.
            if _mentions_pile(u.test, al) and _negated_pile(u.test, al):
                out.append((u.lineno, True, False, fn))
            continue
        if not isinstance(u, ast.If):
            continue
        al, fn = aliases_for(u)
        if not _mentions_pile(u.test, al) or _negated_pile(u.test, al):
            continue                    # a `not`-guarded branch refuses the wrong half
        gate = any(isinstance(c, ast.Call) and _call_name(c) == 'preflight_gate'
                   for s in u.body for c in _walk_flow(s))
        out.append((u.lineno, _stmts_refuse(u.body), gate, fn))
    return sorted(out)


def pile_refusal_lines(path):
    """Lines carrying a STRUCTURALLY REAL pile-tag refusal in this file.

    A line qualifies when an `if` that asks "is this the release pile?" actually raises or
    exits in the branch that question selects (or an `assert not is_pile_tag(...)` does).
    Over-reporting is the safe direction in front of an irreversible pile; under-reporting is
    how auto_tag.py happened.
    """
    return sorted({ln for ln, refuses, _g, _f in _pile_guards(path) if refuses})


def pile_block_shape(path, fname):
    """(found, refuses, runs_preflight_gate) for the pile guard(s) inside top-level `fname`.

    Branch-scoped on purpose. `'is_pile_tag(' in src and 'sys.exit(' in src` is true of tag_ops.py
    from `def is_pile_tag(` and any exit in the file, so the substring form of this test survives
    deleting the very exits it claims to be checking. Aggregated across every pile-guarded block
    in the function because the gate is legitimately split in two: one block refuses an operator
    who did not pass the explicit flag, the other runs preflight_gate and refuses on its verdict.
    """
    n = _top_fns(path).get(fname)
    if n is None:
        return (False, False, False)
    lo, hi = n.lineno, (n.end_lineno or n.lineno)
    mine = [g for g in _pile_guards(path) if g[3] == fname or lo <= g[0] <= hi]
    if not mine:
        return (False, False, False)
    return (True, any(g[1] for g in mine), any(g[2] for g in mine))


def _gate_call_lines(path, seed, stamp):
    """Where the gate is INVOKED from ordinary control flow.

    Only functions NAMED for the gate count as its entry points. Anything that merely mentions
    the gate is a caller, and `main` is always one of those -- an earlier version of this helper
    treated main as part of the gate, discarded the real `require_preflight_stamp(targets)` call
    inside it, and reported the `main()` call in the __main__ guard at the bottom of the file as
    the gate's invocation line. That is how a correctly-ordered gate reads as "AFTER the first tag
    write". Calls a gate entry point makes to its own helpers (require_preflight_stamp ->
    _stamp_refuse) are excluded the same way: they are the gate, not a use of it.
    """
    t = tree(path)
    if t is None:
        return []
    spans = [(nm, n.lineno, n.end_lineno or n.lineno) for nm, n in _top_fns(path).items()]

    def enclosing(ln):
        return next((nm for nm, lo, hi in spans if lo <= ln <= hi), None)

    entries = {nm for nm in seed if _GATE_RE.search(nm)}
    if entries:
        lines = [u.lineno for u in ast.walk(t)
                 if isinstance(u, ast.Call) and isinstance(u.func, ast.Name)
                 and u.func.id in entries and enclosing(u.lineno) not in entries]
        if lines:
            return sorted(lines)
    # Gate written inline rather than as a function: fall back to where it reads the artifact --
    # but only OUTSIDE the gate's own functions. Reading the artifact inside require_preflight_stamp
    # is the gate; it is not evidence that anything CALLS it. Without this exclusion, deleting the
    # `require_preflight_stamp(targets)` line from main() left the check reporting a healthy,
    # correctly-ordered gate (verified 2026-09-07 -- it did exactly that).
    return sorted(u.lineno for u in ast.walk(t)
                  if isinstance(u, ast.Constant) and isinstance(u.value, str)
                  and stamp in u.value and enclosing(u.lineno)
                  and enclosing(u.lineno) not in entries)


def _bypass_flags(path, lines):
    """Flag names of any `if <flag>:` block that ENCLOSES one of `lines`.

    prune_tags already has a --force that bypasses ready_gate. A keeper gate the same flag can
    switch off is not a gate: ready_gate is a write-RELIABILITY check (battery, foreground) and
    skipping it risks a no-op write; skipping a keeper gate risks a release.
    """
    t = tree(path)
    if t is None:
        return []
    out = set()
    for n in ast.walk(t):
        if not isinstance(n, ast.If):
            continue
        lo, hi = n.lineno, (n.end_lineno or n.lineno)
        if not any(lo <= g <= hi for g in lines):
            continue
        for u in ast.walk(n.test):
            if isinstance(u, ast.Name) and _BYPASS_RE.search(u.id):
                out.add(u.id)
            elif isinstance(u, ast.Attribute) and _BYPASS_RE.search(u.attr):
                out.add(u.attr)
    return sorted(out)


def check_pile_stamp_gate(adders):
    """I6.STAMP -- prune_tags.py must not be able to push the pile tag without a fresh receipt.

    ROOT CAUSE, stated plainly. preflight_transfer.py's verdict used to exist ONLY as an exit
    code. Nothing downstream could ask "was THIS pile inspected?", so prune_tags.py -- a live
    route to the phone Transfer tag, whose default target list is the WHOLE plan
    (`targets = [...] or list(PLAN)`, so a bare `python prune_tags.py` pushes every tag INCLUDING
    Transfer), whose only gate was ready_gate (battery/foreground: a write-RELIABILITY check, not
    a keeper check), which --force bypassed even that, and which calls the GATED=False tag_ops
    primitives directly -- had nothing it could check. Hardening the tag_ops CLI closed a side
    door and left this one open, and both RUNBOOK.md and HANDOFF_KEEP_LAW.md instruct a HUMAN to
    run this script by hand. The gate was not so much bypassed as UNOBSERVABLE.

    So the CONTRACT is asserted in both halves:
      producer   preflight_transfer.py writes a stamp artifact on PASS and destroys any existing
                 one when a run starts (a receipt from an earlier pass must never authorise a
                 later, different pile).
      consumer   prune_tags.py reads that same artifact and REFUSES -- raise or non-zero exit --
                 before its first tag write, with no flag that switches the check off.
    The refusal is looked for across the gate's CALL GRAPH, not in a line window around the
    mention: the real shape is require_preflight_stamp() -> _stamp_refuse() -> sys.exit(2), and a
    window tight enough to be meaningful is too tight to see one call down.
    """
    if not os.path.exists(PRUNER) or not os.path.exists(PREFLIGHT):
        fail(BLOCK, 'cannot find %s and/or %s -- the pile push path is unverifiable'
                    % (PRUNER, PREFLIGHT),
             'Restore them. These two files ARE the gate and the push.')
        return

    # (1) name the exposure rather than assuming it: the pusher's default really is the whole plan
    default_all = bool(re.search(r'or\s+list\(\s*_?PLAN\s*\)', code_only(PRUNER)))
    legacy = _const_provenance('granular_tags.py', 'LEGACY_TAGS')['value'] or {}
    pile_planned = PILE_TAG in legacy
    if default_all and pile_planned:
        info('%s default targets = the whole PLAN, which contains %r (a bare run pushes the pile)'
             % (PRUNER, PILE_TAG))
    elif not pile_planned:
        info('%r is not in granular_tags.LEGACY_TAGS -- the pile tag may have been renamed; the '
             'stamp check below still applies to whatever prune_tags pushes' % PILE_TAG)

    # (2) producer half
    stamp = _stamp_artifact(PREFLIGHT)
    if not stamp:
        fail(BLOCK, '%s writes NO stamp artifact -- its verdict exists only as an exit code, so '
                    'nothing downstream can confirm the gate ever ran' % PREFLIGHT,
             'Have a PASS write a receipt (e.g. system/analysis/preflight_stamp.json) carrying the '
             'sha256 of the exact Transfer.txt bytes it vetted, the config fingerprint, the db '
             'content hash and a UTC timestamp; destroy any existing one as the FIRST statement of '
             'a run so no other exit path can leave a stale receipt behind. Then make prune_tags '
             'refuse to push the pile tag without it. Until both halves exist the gate is '
             'UNOBSERVABLE and a bare `python prune_tags.py` pushes the pile.')
        return
    if not re.search(r'\b(?:os\.)?(?:remove|unlink)\s*\(', code_only(PREFLIGHT)):
        fail(BLOCK, '%s writes %s but never DESTROYS it -- a receipt from an earlier passing run '
                    'can authorise a later, different pile' % (PREFLIGHT, stamp),
             'Invalidate the stamp as the first executable statement of a run (above the project '
             'imports, which can themselves raise). The delete is the load-bearing half of failing '
             'closed: every non-PASS exit then leaves no receipt BY CONSTRUCTION, instead of by '
             'enumerating exits and hoping none was missed.')
    else:
        ok('%-42s writes AND invalidates %s' % (PREFLIGHT, stamp))

    # (3) consumer half
    seed, closure = _gate_closure(PRUNER, stamp)
    if stamp not in code_only(PRUNER) or not seed:
        fail(BLOCK, '%s can push the %r tag with NO %s check -- the pre-flight verdict is still '
                    'unobservable to the one script that pushes' % (PRUNER, PILE_TAG, stamp),
             'Make prune_tags load %s before any tag write and REFUSE (exit non-zero) unless it '
             'exists, its schema matches, its pile_sha256 equals the sha256 of the RAW BYTES of '
             'the Transfer.txt it is about to push, and its config/db hashes match the live ones. '
             'A missing or mismatched receipt must be a refusal, never a warning: the producer '
             'half already exists, so the only thing between a hand-run `python prune_tags.py` '
             'and the irreversible pile is this check.' % stamp)
        return

    calls = _gate_call_lines(PRUNER, seed, stamp)
    if not calls:
        fail(BLOCK, '%s defines a %s gate (%s) but never calls it'
                    % (PRUNER, stamp, ', '.join(sorted(seed))),
             'The gate has to run in the pusher, before the pusher writes. Call it from main() '
             'once `targets` is final and ahead of the first tag_ops write.')
        return

    if not _has_refusal(PRUNER, closure):
        fail(BLOCK, '%s consults %s but nothing in that gate\'s call graph (%s) raises or exits '
                    'non-zero' % (PRUNER, stamp, ', '.join(sorted(closure))),
             'A gate that only prints is not a gate. Exit non-zero -- and do it before the Frida '
             'attach, so a stale or missing receipt costs nothing but a message.')
    else:
        ok('%-42s refuses (raise / non-zero exit) when the %s check fails' % (PRUNER, stamp))

    bypass = _bypass_flags(PRUNER, calls)
    if bypass:
        fail(BLOCK, 'the %s gate in %s is invoked inside a flag-controlled branch (%s) -- it can '
                    'be switched off' % (stamp, PRUNER, ', '.join(bypass)),
             '--force exists to bypass ready_gate, which is a write-RELIABILITY check '
             '(battery/foreground): skipping it risks a no-op write. Skipping a KEEPER gate risks '
             'a release. Make the stamp check unconditional for the pile tag.')
    else:
        ok('%-42s has no flag that switches the %s gate off (called at line %d)'
           % (PRUNER, stamp, calls[0]))

    first_write = min([ln for ln, _ in adders.get(PRUNER, []) if ln] or [0])
    if first_write and calls[0] > first_write:
        fail(BLOCK, '%s invokes the %s gate at line %d, AFTER its first tag write at line %d'
                    % (PRUNER, stamp, calls[0], first_write),
             'A gate behind the push has already lost. Move the stamp check above the first '
             'tag_ops call -- ideally above the Frida attach, so a refusal costs no device '
             'contact at all.')
    elif first_write:
        ok('%-42s gate (line %d) precedes its first tag write (line %d)'
           % (PRUNER, calls[0], first_write))


def check_single_push_path():
    section('I6', 'SINGLE PUSH PATH -- one gated producer, one gated pusher')

    files = py_files()
    build_stem_index(files)
    me = os.path.relpath(os.path.abspath(__file__), ROOT).replace('\\', '/')

    # Cheap text prefilter before any AST parse: a file that never mentions a primitive by name
    # cannot call one. Parsing all 736 files unconditionally is most of this audit's runtime, and
    # this gate has to finish alongside four audits that each take a third of a second.
    prim_re = re.compile('|'.join(re.escape(x) for x in
                                  sorted(TAG_WRITE_FUNCS | {'bulk_tag.js', 'SetPokemonTags'})))
    adders, removers = {}, []
    for p in files:
        if p == me or not prim_re.search(src(p)):
            continue
        a, r = tag_write_sites(p)
        if a:
            adders[p] = a
        elif r:
            removers.append(p)

    for p in sorted(SANCTIONED_PUSH | {PUSH_PRIMITIVE}):
        if p in adders:
            ok('%-42s %s' % (p, 'SANCTIONED' if p in SANCTIONED_PUSH else 'shared primitive'))
        else:
            fail(BLOCK, 'the sanctioned pusher %s no longer calls any tag-ADD primitive' % p,
                 'Either the push path moved (update SANCTIONED_PUSH here AND the dashboard step '
                 'list together) or it is broken. Nothing may push tags except this path.')

    pile_pushers, label_only = [], []
    for p in sorted(adders):
        if p in SANCTIONED_PUSH or p == PUSH_PRIMITIVE:
            continue
        strs = _ast_strings(p)
        (pile_pushers if (any(any(t in s for t in PILE_STRINGS) for s in strs)
                          or _enumerates_tagset_dir(p))
         else label_only).append(p)

    closure = entry_closure()
    info('tag-write census: %d script(s) can ADD tag members (%d sanctioned/primitive, %d touch '
         'the RELEASE pile, %d label tags only); %d are removal-only tools'
         % (len(adders), len(SANCTIONED_PUSH) + 1, len(pile_pushers), len(label_only),
            len(removers)))
    if label_only:
        info('label-tag-only adders (cannot cause a release): %s' % ', '.join(sorted(label_only)))
    if removers:
        info('removal-only tag tools (untag_one; cannot cause a release): %s'
             % ', '.join(sorted(removers)))

    # The direction table is only worth trusting while it still describes bulk_tag.js. An export
    # nobody has classified is already handled the safe way (any caller of it is reported as a pile
    # pusher), but a reader has to be told the table has drifted -- otherwise the de-noising above
    # slowly becomes the blindness it replaced.
    _bt = src('bulk_tag.js')
    if not _bt:
        fail(WARN, 'bulk_tag.js is missing -- the Frida tag-write census cannot resolve export '
                   'direction and every loader of it is reported as a pile pusher',
             'Restore bulk_tag.js, or update the census in audit_invariants.py. The census is '
             'over-reporting (the safe direction) until then.')
    else:
        _real = {m for m in re.findall(r'(?m)^    ([A-Za-z][A-Za-z0-9]*): function', _bt)}
        _un = sorted(n for n in _real if _canon(n) not in _BT_KNOWN)
        if _un:
            fail(WARN, 'bulk_tag.js exposes %d export(s) this harness has never classified by '
                       'direction: %s' % (len(_un), _un),
                 'Read each new body in bulk_tag.js and put it in _BT_ADD / _BT_REMOVE / _BT_SAFE '
                 'in audit_invariants.py. Until then any script calling one is reported as a '
                 'RELEASE-pile pusher, which is the safe direction but is noise if it is wrong.')
        else:
            ok('bulk_tag.js: all %d exports classified by direction (%d can ADD tag membership)'
               % (len(_real), len(_BT_ADD)))

    live, gated, dormant = [], [], []
    for p in pile_pushers:
        # 2026-09-07: a script that REFUSES pile tags at runtime is gated, not a loaded gun --
        # apply_tagsets.py, prune_server_tag.py and test_atomic_changes.py were closed this way.
        # Recognise the fix the DO-line asks for. The exemption is STRUCTURAL (pile_refusal_lines:
        # a real call whose own branch exits, ahead of every tag write) because the substring form
        # it replaced could be satisfied by the token sitting in a print plus any unrelated exit.
        _ref = pile_refusal_lines(p)
        _adds = adders.get(p, [])
        _add_lines = sorted(ln for ln, _ in _adds if ln)
        _opaque = [w for ln, w in _adds if not ln]
        if _ref and _add_lines and not _opaque and _ref[0] < _add_lines[0]:
            ok('%-42s refuses pile tags at runtime before any attach (is_pile_tag gate at line %d, '
               'first tag write line %d)' % (p, _ref[0], _add_lines[0]))
            continue
        if _ref and _opaque:
            # The Frida route has no resolvable call line (tag_write_sites reports it at 0), so
            # "the gate comes first" cannot be PROVEN here even though a real gate is present.
            fail(WARN, '%s has a real pile-tag refusal (line %s) but also writes tags through an '
                       'unpositioned Frida route (%s), so this census cannot prove the gate runs '
                       'before the write' % (p, _ref[0], ', '.join(sorted(set(_opaque)))[:120]),
                 'Read the file and confirm by hand that the is_pile_tag() refusal precedes the '
                 'bulk_tag.js/SetPokemonTags write -- ideally that it precedes the Frida attach, '
                 'so a refusal costs no device contact. Move the gate to the top of the entry '
                 'function if it is not already there. Not claimed as gated, because an exemption '
                 'this census cannot prove is the auto_tag.py failure with extra steps.')
            continue
        if p not in closure:
            dormant.append(p)
            continue
        flag = optin_flag(p, adders[p])
        (gated if flag else live).append((p, flag))
    for p, _ in live:
        fail(BLOCK, 'UNSANCTIONED pile pusher %s is REACHABLE from the sanctioned entry points' % p,
             'There must be exactly ONE path from a pile to the phone: keep_policy -> '
             'build_tagsets -> preflight_transfer (rc != 0 aborts) -> prune_tags --atomic. This '
             'script writes the release pile without that gate. Retire it the way auto_tag.py was '
             '(replace the body with a refusal stub that exits 2, keep the original as a .bak), or '
             'route it through the sanctioned stages.')
    for p, flag in gated:
        # `q != me` matters: this harness's own DO-line names both the script and the flag, and
        # without the exclusion the checker reports ITSELF as the caller that arms the gun.
        stem = os.path.splitext(os.path.basename(p))[0]
        passers = [q for q in files
                   if q not in (p, me) and flag in src(q) and ('%s.py' % stem) in src(q)
                   and flag in code_only(q)
                   and re.search(r'\b%s\.py\b' % re.escape(stem), code_only(q))]
        sev = BLOCK if passers else WARN
        fail(sev, 'SANCTIONED entry point %s contains a SECOND, ungated pile pusher behind %s%s'
                  % (p, flag, (' -- and %s passes it' % passers[:2]) if passers
                     else ' -- no caller passes it today'),
             'This is auto_tag.py living inside the pipeline: it tags a pile that keep_policy never '
             'produced and preflight_transfer never gated (pogo_pipeline --tag-transfers pushes '
             "the RETIRED cull_v9 TRANSFER set as CLAUDE_TX via bulk_tag.js; cull_v9 wanted 65 "
             'uids where the sanctioned engine wanted 52, and all 44 extras were keepers). Delete '
             'the flag and its step, or make it refuse unless a fresh preflight_transfer passed. '
             + ('' if passers else 'WARN because no caller passes the flag -- the dashboard runs '
                                   'this script with no arguments -- so it fires only if a human '
                                   'or an agent types it.'))
    if dormant:
        fail(WARN, '%d unsanctioned script(s) can push the RELEASE pile but are unreachable from '
                   'any sanctioned entry point: %s' % (len(dormant), ', '.join(dormant)),
             'These are the auto_tag.py class: second pile producers that skip preflight_transfer '
             'entirely. auto_tag wanted 65 uids where the sanctioned engine wanted 52, and all 44 '
             'extras were keepers -- 26 shiny, 13 variant_floor, 5 protected Pichu. WARN only '
             'because nothing invokes them today; they are still loaded guns on disk, and any one '
             'run by hand or by a future agent pushes an ungated pile. Retire each with a refusal '
             'stub (keep the body in a .bak), or delete them.')
    if not pile_pushers:
        ok('the only scripts that can add to the release pile are the sanctioned path')

    # the primitive's own CLI is an ungated push -- UNLESS cmd_apply refuses pile tags and runs the
    # preflight gate itself (added 2026-09-07). Recognise that gate rather than crying wolf forever:
    # the detector must be able to see the fix it recommended, or the WARN trains people to ignore it.
    # The four substrings this replaced were supplied FOR FREE by the file's own definitions --
    # `def is_pile_tag(`, `def preflight_gate(`, `def cmd_apply(` -- plus one flag name that
    # appears in the help text. Three of the four could not go away without deleting the
    # functions, so the test stayed green while the gate itself was removable: deleting both
    # sys.exit(2) calls out of cmd_apply's pile block left the audit still printing
    # "refuses pile tags". What is asserted now is that the refusal is IN that block.
    _cli = code_only(PUSH_PRIMITIVE)
    _cli_found, _cli_exits, _cli_gate = pile_block_shape(PUSH_PRIMITIVE, 'cmd_apply')
    _gated_cli = (_cli_found and _cli_exits and _cli_gate
                  and _has_refusal(PUSH_PRIMITIVE, ['cmd_apply']))
    if _gated_cli:
        ok('%s CLI refuses pile tags in cmd_apply and runs preflight_gate before any pile push' % PUSH_PRIMITIVE)
    elif _cli_found:
        fail(WARN, '%s cmd_apply HAS an `if is_pile_tag(...)` block, but that block %s'
                   % (PUSH_PRIMITIVE,
                      ' and '.join([x for x in (
                          None if _cli_exits else 'never exits or raises',
                          None if _cli_gate else 'never calls preflight_gate()') if x])
                      or 'no longer satisfies the refusal check'),
             'The pile branch is what stops `python tag_ops.py apply Transfer` from pushing the '
             'release pile with no engine, no build_tagsets and no keeper gate in front of it. A '
             'branch that logs and falls through is not a refusal. Restore BOTH halves: sys.exit(2) '
             'when the operator did not pass the explicit flag, and preflight_gate() -> sys.exit(2) '
             'on a non-empty refusal when they did.')
    elif 'cmd_apply' in _cli and 'add_parser' in _cli:
        fail(WARN, '%s exposes an ungated CLI (`python tag_ops.py apply <tag>`) that pushes a tag '
                   'straight from pokemon.db.auth_tag_names' % PUSH_PRIMITIVE,
             'It bypasses keep_policy, build_tagsets AND preflight_transfer. WARN because it needs '
             'a deliberate manual invocation with an explicit tag name. Consider refusing the tag '
             'name "Transfer" in cmd_apply unless a fresh preflight has passed.')

    check_pile_stamp_gate(adders)

    # the gate must still precede the push in the dashboard job composer
    d = code_only('dashboard.py')
    if not d:
        fail(BLOCK, 'dashboard.py unreadable -- cannot verify the sync gate order',
             'Restore dashboard.py; it composes every sanctioned job.')
        return
    for job, name in (('api_sync', '/api/sync'), ('api_autotag', '/api/autotag'),
                      ('api_full_audit', '/api/full_audit')):
        m = re.search(r'def %s\(.*?\n(.*?)\n@app\.' % job, d, re.S)
        body = m.group(1) if m else ''
        if not body:
            m = re.search(r'def %s\(.*?\n(.*?)\Z' % job, d, re.S)
            body = m.group(1)[:3000] if m else ''
        if not body:
            fail(WARN, 'could not locate %s in dashboard.py to check its gate order' % name,
                 'Verify by hand that _gate_steps() still precedes _push_steps() there.')
            continue
        gi, pi = body.find('_gate_steps'), body.find('_push_steps')
        if pi == -1:
            ok('%-18s does not push' % name)
        elif gi == -1 or gi > pi:
            fail(BLOCK, '%s pushes to the phone WITHOUT the pre-flight keeper gate in front of it'
                        % name,
                 'Put _gate_steps() before _push_steps() in that handler. preflight_transfer '
                 'returning rc!=0 is the ONLY thing that stops a pile with a real keeper in it '
                 'from reaching the phone.')
        else:
            ok('%-18s gate (_gate_steps) precedes push (_push_steps)' % name)
    if 'keep_policy.py' in d and '_recompute_steps' in d:
        ok('the dashboard recomputes the pile from keep_policy before gating it')
    else:
        fail(BLOCK, 'dashboard.py no longer recomputes the pile via keep_policy before pushing',
             'Restore _recompute_steps() ahead of the gate, or the artifact that is audited is not '
             'the artifact that gets pushed.')


# ============================================================================= main
# ============================================================================ I7 STAT-LINE FIDELITY
# WHY THIS INVARIANT EXISTS
# -------------------------
# CP is a PURE FUNCTION of (base stats, IVs, CPM):
#     CP = max(10, floor((atk+ia)*cpm * sqrt((def+id)*cpm) * sqrt((sta+is)*cpm) / 10))
# The GAME computed the CP it stored using the stat line IT believes the mon has. So every mon in
# the bag carries a signed receipt for the mapping decision the ranker makes about it. If the
# speciesId we resolve a (species, form) to cannot reproduce that stored CP at ANY level, and a
# DIFFERENT speciesId on the same dex number can, then the ranker has been ranking that mon against
# the wrong stat line -- and every PvP protection derived from it is a number nobody ever computed.
# The mon was not "checked and found unremarkable"; it was never checked. That is the Mareep shape,
# and it feeds the ONE irreversible output this project has.
#
# This is not hypothetical. Three live mappings failed exactly this test (forensic audit 2026-09-07,
# after 24 wrongly-culled mons were found and 18 were gone for good):
#   ('Mewtwo',135):'mewtwo_armored'  BACKWARDS. form_enum 133='MewtwoA' (Armored, 182/278/214),
#       135='MewtwoNormal' (300/182/214). There was no ('Mewtwo',133) key at all, so 114 REAL
#       Armored Mewtwo fell through to plain 'mewtwo'. 160 rows ranked off the wrong stat line.
#   ('Corsola',3339) ABSENT.  form_enum 3339='CorsolaSpring2026' -- a costume ON A REGIONAL FORM.
#       Its stored CP/HP reproduce only under 'corsola_galarian' (116/182/155), never under
#       Kantonian 'corsola' (118/156/146). Galarian is the bulkier one, so the error ran in the
#       UNDER-KEEP direction. 3 rows.
#   ('Slowking',2734):'slowking_galarian' WRONG. 'Slowking2022' is an event re-release of the PLAIN
#       form; only 'slowking' (177/180/216) reproduces. 2 rows.
# Not one of the other six invariants could see any of them. The axis model was coherent (I1), every
# input was fresh (I2), nothing was NULL (I3), every column had a writer (I4), the partition was
# exact (I5) and the push path was gated (I6). The engine was answering a perfectly well-formed
# question about the wrong pokemon. Only the game's own arithmetic could tell us.
#
# WHAT DECIDES, AND WHAT ONLY CORROBORATES
# ----------------------------------------
# CP DECIDES. It is reproducible from the stored row alone and it discriminates: on the live bag it
# separates the three real defects from ~1,540 correct pairs with no threshold tuning at all.
# HP CORROBORATES, it never decides. The HP columns carry CURRENT hit points, not max, on an unknown
# subset of rows (a battle-damaged Vespiquen stores 47 where its stat line says 122), so an HP
# mismatch on its own is data staleness, not a mapping error. HP is therefore reported alongside CP
# and used ONLY as a tie-break when two candidate stat lines fit the CP evidence equally well.
# The reconstruction SOLVES FOR THE LEVEL instead of trusting the `level` / `cp_multiplier` columns:
# CP over the CPM ladder is a discrete staircase, so "no level reproduces this CP" is a statement
# about the BASE STATS -- the thing actually under test -- and cannot be confounded by a stale level.
GM_JSON = 'pvpoke_gamemaster.json'
RANKER = 'system/scripts/rank_cache.py'     # pogo_pipeline.py:1058 runs THIS one -- the live path
RANKER_ALT = 'compute_all_ranks.py'         # its documented fallback; must give the SAME answers
PVP_RULE = 'pvp_iv_rule.py'                 # the keep rule's own copy of the L50 CPM


# ---------------------------------------------------------------------------- game-constant
# provenance: how a constant REACHES a consumer, and what it actually resolves to.
#
# WHY THIS IS NOT A LITERAL SCRAPE ANY MORE (2026-09-07)
# -----------------------------------------------------
# The old _module_const() understood exactly one shape, `NAME = <literal>`, and returned None for
# anything else. Defect D4 then did the correct thing -- collapsed the two duplicated CPM tables
# and the third copy of the L50 scalar into cpm_table.py, so the ranker now says
#     from cpm_table import MAX_LEVEL_IDX, ... , cpm_list
#     CPM = cpm_list()
# and the scrape went blind. The check BLOCKED on its own recommended remediation: it was demanding
# that a duplicated literal still be present in order to prove the values had not diverged.
#
# The invariant was never "there is a literal here". It is "there is exactly ONE value for this
# game constant across every consumer". So this resolves the constant the way python does -- follow
# the import to its source module and read the resolved value -- and additionally reports the
# PROVENANCE, which is the stronger statement: a constant that arrives by import from one shared
# module CANNOT have diverged, whereas two literals that merely match today are one careless edit
# away from the split-brain that fed the irreversible pile.
#
# THE IMPORT IS NOT FREE, AND THAT IS WHY _import_safe() EXISTS
# ------------------------------------------------------------
# `import compute_all_ranks` is NOT a read. That file is a plain script with no __main__ guard: at
# module scope it opens pokemon.db, ALTER TABLEs twelve rank columns into it and UPDATEs every
# in-bag row. Importing it from this harness would break the READ-ONLY contract in the docstring
# at the top of this file, mid-transfer, on the user's live database. So a module is only ever
# imported here after its module-scope body has been shown to contain nothing but imports,
# assignments, defs/classes and asserts -- and the constant is then resolved from THAT module's
# namespace, never from the script's.
_SAFE_MODS = {}

#: Call names that make a module-scope import a side effect rather than a read.
_UNSAFE_CALLS = {
    'open', 'connect', 'execute', 'executemany', 'executescript', 'commit', 'cursor',
    'system', 'run', 'call', 'check_call', 'check_output', 'Popen', 'remove', 'unlink',
    'rmtree', 'rename', 'replace', 'mkdir', 'makedirs', 'copy', 'copy2', 'move', 'write',
    'write_text', 'write_bytes', 'dump', 'urlopen', 'request', 'attach', 'spawn',
    'get_session', 'main', 'input', 'exit',
}


def _module_scope_stmts(t):
    """Every statement at MODULE scope -- descending into module-level if/try/with/for/while, but
    never into a def or a class (a call inside a function body is not an import-time side effect).
    """
    out, stack = [], list(t.body)
    while stack:
        n = stack.pop()
        out.append(n)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ('body', 'orelse', 'finalbody'):
            stack.extend(getattr(n, field, None) or [])
        for h in getattr(n, 'handlers', None) or []:
            stack.extend(h.body)
    return out


def _import_safe(path):
    """True if importing `path` cannot write anything. See the block comment above."""
    t = tree(path)
    if t is None:
        return False
    for n in _module_scope_stmts(t):
        if isinstance(n, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
            return False
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(n, ast.Expr) and not (isinstance(n.value, ast.Constant)
                                            and isinstance(n.value.value, str)):
            return False        # a bare module-scope expression statement is a call for effect
        for u in ast.walk(n):
            if not isinstance(u, ast.Call):
                continue
            f = u.func
            nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else '')
            if nm in _UNSAFE_CALLS:
                return False
    return True


def _safe_import(modname):
    """Import `modname` ONLY if its module-scope body is provably side-effect free; else None.

    Anything already in sys.modules (rank_cache, imported by I7.1 above) is served from there.
    An ImportError or a failing import-time assert -- cpm_table asserts its own table is strictly
    increasing and that CPM50 IS the table entry, not a second literal -- resolves to None, which
    every caller treats as 'could not verify' and BLOCKs on. Ignorance is never the safe answer
    in front of an irreversible pile.
    """
    if modname in _SAFE_MODS:
        return _SAFE_MODS[modname]
    mod = sys.modules.get(modname)
    if mod is None:
        rel = modname.replace('.', '/') + '.py'
        cand = [p for p in (rel, 'system/scripts/' + rel)
                if os.path.exists(os.path.join(ROOT, p))]
        if not cand or not _import_safe(cand[0]):
            _SAFE_MODS[modname] = None
            return None
        try:
            import importlib
            mod = importlib.import_module(modname)   # NOT __import__: that returns the top-level
        except Exception:                            # package for a dotted name, not the module
            mod = None
    _SAFE_MODS[modname] = mod
    return mod


def _const_provenance(path, name):
    """How the game constant `name` reaches module `path`, and what it resolves to.

    Returns dict(kind, source, value, how):
      'imported'  `from <source> import name`                     -- single-sourced
      'derived'   `name = <expr>` built ONLY from names imported from <source>
                  (the live shape: `CPM = cpm_list()`)            -- single-sourced
      'literal'   `name = <literal>` -- a LOCAL SECOND COPY of a game constant. This is the D4
                  state, and it is what must never come back, matching value or not.
      'unknown'   defined, but not resolvable from here (the caller BLOCKs: cannot verify)
      'absent'    this module does not define it at all
    A local assignment WINS over an import even when both are present, because that is what python
    does: `from cpm_table import CPM50` followed by `CPM50 = 0.84` leaves the literal in force.
    """
    t = tree(path)
    if t is None:
        return dict(kind='unknown', source=None, value=None, how='%s does not parse' % path)

    imports = {}                                  # local name -> (module, original name)
    assigns = []                                  # module-scope assignments to `name`, in order
    for n in _module_scope_stmts(t):
        if isinstance(n, ast.ImportFrom) and n.module and not n.level:
            for a in n.names:
                imports[a.asname or a.name] = (n.module, a.name)
        elif isinstance(n, ast.Assign):
            if any(isinstance(tg, ast.Name) and tg.id == name for tg in n.targets):
                assigns.append(n)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) \
                and n.target.id == name and n.value is not None:
            assigns.append(n)

    if assigns:
        last = assigns[-1]                        # last write wins, as at runtime
        node = last.value
        try:
            return dict(kind='literal', source=None, value=ast.literal_eval(node),
                        how='%s:%d  %s = <literal>' % (path, last.lineno, name))
        except Exception:
            pass
        used = {u.id for u in ast.walk(node) if isinstance(u, ast.Name)}
        srcs = {imports[u][0] for u in used if u in imports}
        if used and used <= set(imports) and len(srcs) == 1:
            source = srcs.pop()
            mod = _safe_import(source)
            val = None
            if mod is not None:
                ns = {u: getattr(mod, imports[u][1], None) for u in used}
                if all(v is not None for v in ns.values()):
                    try:
                        val = eval(ast.unparse(node), {'__builtins__': {}}, ns)
                    except Exception:
                        val = None
            return dict(kind='derived' if val is not None else 'unknown', source=source, value=val,
                        how='%s:%d  %s = %s   (from %s.py)'
                            % (path, last.lineno, name, ast.unparse(node), source))
        return dict(kind='unknown', source=None, value=None,
                    how='%s:%d  %s = %s   (not resolvable from a single source module)'
                        % (path, last.lineno, name, ast.unparse(node)))

    if name in imports:
        source, orig = imports[name]
        mod = _safe_import(source)
        val = getattr(mod, orig, None) if mod is not None else None
        return dict(kind='imported' if val is not None else 'unknown', source=source, value=val,
                    how='%s  from %s import %s' % (path, source, orig))

    return dict(kind='absent', source=None, value=None,
                how='%s does not define %s' % (path, name))


def _module_const(path, name):
    """Resolved value of a module-level constant, however it arrives (import, derivation or
    literal). None means 'could not be resolved', which every caller treats as unverifiable."""
    return _const_provenance(path, name)['value']


def _fn_shape(path, name):
    """Structural fingerprint of a top-level function: its AST with docstring, comments, formatting
    and line numbers removed. Two files that both define one mapping must define it the SAME way."""
    t = tree(path)
    if t is None:
        return None
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            try:
                fresh = ast.parse(ast.unparse(n)).body[0]
            except Exception:
                return None
            b = fresh.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                    and isinstance(b[0].value.value, str):
                fresh.body = b[1:]
            return ast.dump(fresh)
    return None


def _fn_body_names(path, name):
    """Every bare identifier referenced inside a top-level function."""
    t = tree(path)
    if t is None:
        return set()
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
    return set()


def check_stat_line_fidelity(con):
    section('I7', 'STAT-LINE FIDELITY -- every (species,form) must reproduce its own stored CP')

    # ---- I7.1  the mapping under test must BE the live ranker's, and there must be only one ----
    try:
        import rank_cache as _rk
    except Exception as e:
        fail(BLOCK, 'cannot import the live ranker %s (%s) -- CP reconstruction cannot run'
                    % (RANKER, e),
             'Fix the import. Without it nothing checks that the speciesId feeding every PvP rank '
             'is the species the game itself says the mon is -- the check that found the '
             'Armored-Mewtwo inversion, the Galarian-Corsola gap and the Slowking mis-map.')
        return
    to_pvpoke_id, CPMT, MAXIDX = _rk.to_pvpoke_id, list(_rk.CPM), _rk.MAX_LEVEL_IDX

    # to_pvpoke_id's third argument (costume) is DEAD: the mapping is keyed on (species, form)
    # alone. This whole check groups the bag by (species, form) on that basis, so if the mapping
    # ever starts consulting costume, the grouping stops being the right key and a costume-
    # dependent mis-map would become invisible here.
    if 'costume' in _fn_body_names(RANKER, 'to_pvpoke_id'):
        fail(BLOCK, 'rank_cache.to_pvpoke_id now READS its costume argument -- this invariant groups '
                    'the bag by (species, form) only and no longer covers the whole mapping',
             'Re-key check_stat_line_fidelity() on (species, form, fresh_costume) in '
             'audit_invariants.py. Until then a costume-dependent mis-map is invisible here.')
    else:
        ok('mapping key confirmed: to_pvpoke_id resolves on (species, form) alone')

    shape_live, shape_alt = _fn_shape(RANKER, 'to_pvpoke_id'), _fn_shape(RANKER_ALT, 'to_pvpoke_id')
    if shape_live is None or shape_alt is None:
        fail(BLOCK, 'could not read to_pvpoke_id from %s and/or %s' % (RANKER, RANKER_ALT),
             'Both files define the species mapping. If one cannot be parsed, nothing here can '
             'prove the primary ranker and its fallback answer "which pokemon is this" the same '
             'way, and the pile is decided by whichever one happened to run.')
    elif shape_live != shape_alt:
        fail(BLOCK, 'SPLIT-BRAIN MAPPING: %s and %s define DIFFERENT to_pvpoke_id bodies'
                    % (RANKER, RANKER_ALT),
             'pogo_pipeline runs rank_cache.py and falls back to compute_all_ranks.py, so the same '
             'bag can be ranked against two different species maps depending on which one ran. '
             'Make one import the other, or make them textually identical.')
    else:
        ok('to_pvpoke_id is identical in the live ranker and its fallback (one species map)')

    # ---- I7.1b  the KEEP RULE's own species map is a THIRD copy and must agree ------------------
    # pvp_iv_rule.pvid() answers the same question as to_pvpoke_id ("which pokemon is this") in a
    # SEPARATE function body, and keep_policy, build_tagsets, granular_tags, preflight_transfer and
    # five audits all resolve a specimen's speciesId through it (keep_policy.py:257
    # `pvid(r['species_name'], r['form'] or 0)`). The check above proves the two RANKERS agree; it
    # says nothing about the rule that decides the pile. The two bodies are deliberately NOT
    # compared with _fn_shape: they differ on purpose (pvid takes no costume argument and tolerates
    # a None species_name), so a structural test would BLOCK on a difference that is not a defect.
    # What must hold is BEHAVIOURAL -- same answer on every (species, form) the bag actually
    # contains -- plus one structural fact: both must read the SAME FORM_OVERRIDES object, because
    # an equal-but-separate copy is the D4 constant defect in a different costume.
    try:
        import pvp_iv_rule as _pv
    except Exception as e:
        fail(BLOCK, 'cannot import the keep rule %s (%s) -- its species map cannot be compared '
                    'with the ranker\'s' % (PVP_RULE, e),
             'Fix the import. pvid() is what keep_policy resolves every specimen through; if it '
             'cannot be loaded here, nothing proves the pile was decided with the ranker\'s map.')
    else:
        _combos = con.execute('SELECT DISTINCT species_name, form FROM pokemon '
                              'WHERE in_bag=1').fetchall()
        _div = []
        for _sp, _fm in _combos:
            try:
                _a = to_pvpoke_id(_sp or '', _fm or 0, 0)
            except Exception as _e:
                _a = '<raised %s>' % type(_e).__name__
            try:
                _b = _pv.pvid(_sp, _fm or 0)
            except Exception as _e:
                _b = '<raised %s>' % type(_e).__name__
            if _a != _b:
                _div.append((_sp, _fm, _a, _b))
        if _div:
            fail(BLOCK, 'SPLIT-BRAIN SPECIES MAP: the keep rule\'s pvid() and the ranker\'s '
                        'to_pvpoke_id() disagree on %d of %d in-bag (species,form) combo(s): %s'
                        % (len(_div), len(_combos),
                           '; '.join('%s f=%s -> rule %r vs ranker %r' % d for d in _div[:6])),
                 'The RANKS were computed with to_pvpoke_id and the KEEP DECISION reads pvid, so a '
                 'disagreement means keep_policy protected (or failed to protect) a mon on numbers '
                 'calculated for a different pokemon -- the Mudbray/Mareep shape, arriving through '
                 'the rule instead of through the ranker. Make pvid() delegate to to_pvpoke_id, or '
                 'fix whichever map is wrong, then re-run the ranker AND keep_policy before any '
                 'sync.')
        else:
            ok('the keep rule\'s pvid() and the ranker\'s to_pvpoke_id() agree on all %d in-bag '
               '(species,form) combo(s)' % len(_combos))
        _fo_rule = getattr(_pv, 'FORM_OVERRIDES', None)
        _fo_rank = getattr(_rk, 'FORM_OVERRIDES', None)
        if _fo_rule is None or _fo_rank is None:
            fail(WARN, 'could not read FORM_OVERRIDES from %s and/or %s'
                       % (PVP_RULE, RANKER),
                 'Both are supposed to import it from form_overrides_complete.py. If one has '
                 'stopped, the species map has two upstreams again.')
        elif _fo_rule is not _fo_rank:
            fail(BLOCK, '%s and %s hold SEPARATE FORM_OVERRIDES objects (%d vs %d entries)'
                        % (PVP_RULE, RANKER, len(_fo_rule), len(_fo_rank)),
                 'One override table, two copies: they agree today and nothing keeps them '
                 'agreeing, and the table is the whole species map for every non-default form. '
                 'Import it from form_overrides_complete.py in both files.')
        else:
            ok('the keep rule and the ranker share ONE FORM_OVERRIDES table (%d entries)'
               % len(_fo_rank))

    # ---- I7.2  ONE value per game constant, and it must be SINGLE-SOURCED, not merely equal ----
    # What this asserts and what it does NOT: it does not demand a literal (that was the bug -- it
    # BLOCKed on its own remediation once D4 collapsed the duplicates into cpm_table.py). It
    # demands that every consumer of a game constant reach the SAME source module, and that the
    # values it resolves to are equal. Two matching literals are still a violation: cpm_table.py's
    # own header says "DO NOT RE-HARDCODE ANY VALUE FROM THIS FILE ANYWHERE ELSE -- IMPORT IT",
    # and the D4 forensics are the reason (0.84029995 vs 0.84029999 vs the game's own
    # 0.8403000235557556 -- three values for one number, feeding the ranks that decide the pile).
    # A re-duplication that happens to match today is exactly the state that silently diverges
    # tomorrow, so it BLOCKs on the duplication itself, not on the difference.
    const_sources = {}
    for const in ('CPM', 'MAX_LEVEL_IDX'):
        pv = {p: _const_provenance(p, const) for p in (RANKER, RANKER_ALT)}
        bad = {p: d for p, d in pv.items() if d['kind'] in ('unknown', 'absent')}
        dup = {p: d for p, d in pv.items() if d['kind'] == 'literal'}
        if bad:
            fail(BLOCK, 'could not resolve %s in %s' % (const, ', '.join(sorted(bad))),
                 'The CPM ladder and the level cap are what turn base stats into a CP. If they '
                 'cannot be resolved, this reconstruction is not verifiably using the ranker\'s '
                 'own arithmetic. Resolution follows the import to its source module, so this '
                 'means the constant is neither imported from one shared module nor a literal '
                 'here: ' + ' | '.join(d['how'] for d in bad.values()))
            continue
        vals = {p: d['value'] for p, d in pv.items()}
        if vals[RANKER] != vals[RANKER_ALT]:
            fail(BLOCK, '%s differs between %s and %s' % (const, RANKER, RANKER_ALT),
                 'Two CPM ladders / level caps means two different rank tables for one bag. '
                 'Collapse them to one definition that both files import (cpm_table.py is where '
                 'that lives). Provenance: ' + ' | '.join(pv[p]['how'] for p in (RANKER, RANKER_ALT)))
            continue
        if dup:
            fail(BLOCK, 'RE-DUPLICATED GAME CONSTANT: %s is defined as a local literal in %s '
                        '(values agree today)' % (const, ', '.join(sorted(dup))),
                 'This is the D4 state coming back. cpm_table.py is the single source of truth and '
                 'says so in its own header: import the constant, never re-type it. Two literals '
                 'that merely match are not one value -- 0.84029995 / 0.84029999 / '
                 '0.8403000235557556 were three transcriptions of ONE number, and the ranks they '
                 'produce decide the irreversible Transfer pile. BLOCKs on the duplication itself, '
                 'not on a difference, because by the time they differ the pile has already moved. '
                 + ' | '.join(d['how'] for d in dup.values()))
            continue
        srcs = {d['source'] for d in pv.values()}
        if len(srcs) != 1:
            fail(BLOCK, '%s reaches %s and %s from DIFFERENT source modules (%s)'
                        % (const, RANKER, RANKER_ALT, ', '.join(sorted(map(str, srcs)))),
                 'One game constant, two upstreams: they agree by coincidence today and nothing '
                 'keeps them agreeing. Point both files at the same module.')
            continue
        source = srcs.pop()
        const_sources[const] = source
        ok('%-13s single-sourced: both rankers resolve it from %s.py (%s)'
           % (const, source, ('%d entries' % len(vals[RANKER]))
              if isinstance(vals[RANKER], (list, tuple)) else repr(vals[RANKER])))

    # The live ranker OBJECT must carry the same values this file just resolved statically. The
    # provenance walk reads source; check_stat_line_fidelity reconstructs CP from the imported
    # rank_cache module. If those two ever disagree, the audit is proving something about a file
    # that is not what ran (a stale .pyc, a shadowing module earlier on sys.path, a monkeypatch).
    for const, live in (('CPM', list(CPMT)), ('MAX_LEVEL_IDX', MAXIDX)):
        if const not in const_sources:
            continue
        static = _module_const(RANKER, const)
        static = list(static) if isinstance(static, (list, tuple)) else static
        if static != live:
            fail(BLOCK, 'the imported rank_cache.%s does not match what %s resolves to on disk'
                        % (const, RANKER),
                 'The CP reconstruction below runs against the IMPORTED module. If the module in '
                 'memory is not the file on disk, this audit is vetting source nobody executed. '
                 'Check for a stale __pycache__ or a second rank_cache.py earlier on sys.path.')
        else:
            ok('the imported ranker\'s %s IS the value on disk (no stale module in the way)' % const)

    # The keep RULE consumes the L50 CPM for its viability gate. Same invariant, third consumer.
    # A drifted copy is the same defect class (one number, two values) -- but CPM50 is used only
    # inside maxcp() for the `maxcp(stage) > cap + margin` VIABILITY test, so a larger value can
    # only make a stage read as viable = MORE protection. Direction of harm is over-keeping, so a
    # DIFFERENCE is WARN; a re-typed literal is BLOCK for the same reason as above.
    pv50 = _const_provenance(PVP_RULE, 'CPM50')
    ladder50 = CPMT[MAXIDX] if 0 <= MAXIDX < len(CPMT) else None
    if pv50['kind'] in ('unknown', 'absent') or ladder50 is None:
        fail(WARN, 'could not resolve %s CPM50 -- the keep rule\'s own copy of the L50 CPM is '
                   'unverified' % PVP_RULE,
             'pvp_iv_rule.maxcp() multiplies by this constant to decide whether a stage is even '
             'league-viable. Unverified means nothing here proves the rule and the ranker agree '
             'about level 50. Import it from the same module the rankers use. (%s)' % pv50['how'])
    elif pv50['kind'] == 'literal':
        # Checked BEFORE the value comparison on purpose. A re-typed literal is the defect
        # whether or not it currently matches -- this is the exact pair that held two
        # different values for one number in D4 (pvp_iv_rule 0.84029999 vs the ranker's
        # 0.84029995, neither of them the game's own 0.8403000235557556), and a matching
        # re-type restores the conditions, not the fix.
        fail(BLOCK, 'RE-DUPLICATED GAME CONSTANT: %s defines CPM50 as a local literal (%r; the '
                    'ranker ladder CPM[%d] is %r)'
                    % (PVP_RULE, pv50['value'], MAXIDX, ladder50),
             'Import it from the module the rankers use. Two literals are not one value: this '
             'is the pair D4 found holding 0.84029995 / 0.84029999 for one number, and those '
             'ranks decide the irreversible Transfer pile.')
    elif pv50['value'] != ladder50:
        fail(WARN, 'L50 CPM SPLIT-BRAIN: %s CPM50=%r but the ranker ladder CPM[%d]=%r'
                   % (PVP_RULE, pv50['value'], MAXIDX, ladder50),
             'One number, two values. Import the constant from the ranker\'s source instead of '
             're-typing it. WARN only because CPM50 is consulted solely in the maxcp() viability '
             'test, where a larger value can only ADD protection; it cannot drop a keeper. Fix it '
             'anyway -- the next copy of this constant may not land on the safe side.')
    elif const_sources.get('CPM') and pv50['source'] != const_sources['CPM']:
        fail(WARN, 'L50 CPM: %s resolves CPM50 from %s.py but the rankers resolve CPM from %s.py'
                   % (PVP_RULE, pv50['source'], const_sources['CPM']),
             'The values agree today, but they are two upstreams and nothing keeps them agreeing. '
             'Point all three consumers at one module.')
    else:
        ok('the L50 CPM constant is single-sourced from %s.py and is the same number in the keep '
           'rule and the ranker ladder (%r)' % (pv50['source'], ladder50))

    # ---- inputs -------------------------------------------------------------------------------
    try:
        with open(os.path.join(ROOT, GM_JSON), encoding='utf-8') as f:
            gm = json.load(f)
        gm_by_id = {p['speciesId']: p for p in gm['pokemon']}
        # 2026-09-08 (user: "checked often, at least once a month"): the game master is the base-stat
        # source of EVERY rank this project culls on. It had gone 85 days with no producer. Now
        # system/scripts/refresh_gamemaster.py exists and full_audit.py runs it when stale; this WARN is
        # the backstop in case that hook is ever removed.
        try:                                     # the DOWNLOAD time when refresh_gamemaster recorded it (H04-11), else mtime
            _gm_age = (time.time() - float(json.load(open(os.path.join(ROOT, GM_JSON + '.downloaded'), encoding='utf-8'))['ts'])) / 86400.0
        except (OSError, ValueError, KeyError, TypeError):
            _gm_age = (time.time() - os.path.getmtime(os.path.join(ROOT, GM_JSON))) / 86400.0
        if _gm_age > 30:
            fail(WARN, 'pvpoke_gamemaster.json is %.0f days old (limit 30) -- base stats for every PvP '
                       'rank may be stale' % _gm_age,
                 'Run: python system/scripts/refresh_gamemaster.py  (downloads PvPoke current file, '
                 'recomputes ranks, exits 2 if any keep decision crossed the rank<=5 line). full_audit.py '
                 'does this automatically when the file is over 30 days old.')
        else:
            ok('pvpoke_gamemaster.json is %.0f day(s) old (refreshed within 30 days)' % _gm_age)
    except Exception as e:
        fail(BLOCK, 'pvpoke_gamemaster.json unreadable (%s) -- no base stats, no reconstruction' % e,
             'Restore it. It is the only source of the base stats every rank in this project is '
             'computed from.')
        return
    by_dex = defaultdict(dict)          # dex -> {(atk,def,hp): [speciesId, ...]}
    for p in gm['pokemon']:
        b = p['baseStats']
        by_dex[p.get('dex')].setdefault((b['atk'], b['def'], b['hp']), []).append(p['speciesId'])

    rows = con.execute("""SELECT uid_hex, species_name, pokemon_id, form, fresh_form,
        iv_atk, iv_def, iv_sta, cp, COALESCE(stamina, max_stamina), gl_rank, ul_rank
        FROM pokemon WHERE in_bag=1""").fetchall()
    try:
        pile = {u for u in open(os.path.join(TD, '6_Transfer.txt')).read().split() if u}
    except Exception:
        pile = None
    try:
        reasons = json.load(open(os.path.join(ANA, 'policy_reasons.json'), encoding='utf-8'))
    except Exception:
        reasons = None

    # ---- the reconstruction -------------------------------------------------------------------
    _fitcache = {}

    def _fits(bstat, ia, idf, ista, cp, hp):
        """(cp_reproduces, cp_and_hp_reproduce_at_the_SAME_level) for one row under one stat line.

        Solves for the level: is there ANY rung of the CPM ladder that yields exactly this stored
        CP? Deliberately does not consult the row's own level/cp_multiplier columns -- a stale level
        must not be able to masquerade as (or mask) a wrong stat line.
        """
        key = (bstat, ia, idf, ista, cp, hp)
        got = _fitcache.get(key)
        if got is None:
            ba, bd, bs = bstat
            cp_ok = both_ok = False
            for cpm in CPMT:
                if max(10, int((ba + ia) * cpm * math.sqrt((bd + idf) * cpm)
                               * math.sqrt((bs + ista) * cpm) / 10)) != cp:
                    continue
                cp_ok = True
                if hp is None or max(10, int(math.floor((bs + ista) * cpm))) == hp:
                    both_ok = True
                    break
            got = _fitcache[key] = (cp_ok, both_ok)
        return got

    pairs = defaultdict(list)       # (species_name, pid, form) -> [(uid, ia, idf, ista, cp, hp)]
    unresolved_rows, norank_rows, placeholder_rows, formdrift = [], [], [], []
    incomplete = 0
    for (uid, sp, pid, form, ffm, ia, idf, ista, cp, hp, glr, ulr) in rows:
        sp = sp or ''
        sid = to_pvpoke_id(sp, form or 0, 0)
        if None in (ia, idf, ista, cp):
            incomplete += 1         # cannot reconstruct a row whose own IVs/CP were never read
        else:
            pairs[(sp, pid, form)].append((uid, ia, idf, ista, cp, hp))
        if sid not in gm_by_id:
            unresolved_rows.append((uid, sp, pid, form, sid, glr, ulr))
        if glr is None and ulr is None:
            norank_rows.append((uid, sp, pid, form, sid))
        if re.fullmatch(r'(?i)\s*pid\d+\s*', sp):
            placeholder_rows.append((uid, sp, pid, form))
        if to_pvpoke_id(sp, ffm or 0, 0) != sid:
            formdrift.append((uid, sp, form, ffm, sid, to_pvpoke_id(sp, ffm or 0, 0)))

    mismapped, unreproducible, partial, hp_dissent = [], [], [], []
    undiscriminated = []            # (key, sid, tied_ids, n_rows) -- CP cannot tell these apart
    n_clean = n_checked = n_rows_checked = 0
    for key in sorted(pairs, key=lambda k: (k[0], k[1] if k[1] is not None else -1,
                                            k[2] if k[2] is not None else -1)):
        sp, pid, form = key
        mons = pairs[key]
        sid = to_pvpoke_id(sp, form or 0, 0)
        mapped = gm_by_id.get(sid)
        if mapped is None:
            continue                # unresolved -- I7.3's business; there is nothing to fit against
        n_checked += 1
        n_rows_checked += len(mons)
        b = mapped['baseStats']
        mb = (b['atk'], b['def'], b['hp'])
        # Candidate stat lines = every DISTINCT base-stat line the gamemaster carries for this dex
        # number (shadow/mega/regional/costume variants), keyed by the stats themselves so two ids
        # that share a stat line can never be told apart and can never produce a false accusation.
        cands = {k: list(v) for k, v in by_dex.get(pid, {}).items()}
        if mb not in cands:
            cands[mb] = [sid]
        elif sid not in cands[mb]:
            cands[mb].append(sid)
        scores = {}
        for bstat, ids in cands.items():
            ncp = nboth = 0
            for (_u, ia, idf, ista, cp, hp) in mons:
                c, bo = _fits(bstat, ia, idf, ista, cp, hp)
                ncp += c
                nboth += bo
            scores[bstat] = (ncp, nboth, sorted(set(ids)))
        m_cp, m_hp, _m_ids = scores[mb]
        best_cp = max(v[0] for v in scores.values())
        n = len(mons)
        piled = sorted(u for (u, *_r) in mons if pile and u in pile)
        # THE BLIND SPOT OF THIS WHOLE INVARIANT, MEASURED (2026-09-07). Candidate stat lines are
        # keyed BY THE STATS, so two speciesIds on one dex that share a stat line can never be
        # told apart by CP -- deliberately, because that is what stops a false accusation. The
        # cost is that for those pairs this check proves nothing about WHICH of them the mon is.
        # It has never been counted. It is not a small set, and it is not all harmless.
        if len(_m_ids) > 1:
            undiscriminated.append((key, sid, list(_m_ids), n))
        if best_cp > m_cp:
            win = max((v for v in scores.values() if v[0] == best_cp), key=lambda v: v[1])
            mismapped.append((key, sid, n, m_cp, m_hp, win, piled))
        elif m_cp == 0:
            unreproducible.append((key, sid, n, piled))
        else:
            better_hp = [v for k2, v in scores.items()
                         if k2 != mb and v[0] == m_cp and v[1] > m_hp]
            if better_hp:
                hp_dissent.append((key, sid, n, m_cp, m_hp, max(better_hp, key=lambda v: v[1])))
            if m_cp < n:
                # only a pile member whose OWN row fails is suspect: a 78% shadow Electivire that fit L20 exactly was
                # flagged because the hundo Electivire beside it (a best buddy) did not (2026-09-25)
                piled_bad = [u for (u, ia, idf, ista, cp, hp) in mons
                             if u in piled and not _fits(mb, ia, idf, ista, cp, hp)[0]]
                partial.append((key, sid, n, m_cp, piled_bad))
            else:
                n_clean += 1

    info('reconstructed %d in-bag row(s) across %d resolvable (species,form) pair(s) against the '
         "game's own CP arithmetic" % (n_rows_checked, n_checked))
    if incomplete:
        fail(WARN, '%d in-bag row(s) have a NULL iv_atk/iv_def/iv_sta/cp and could not be '
                   'reconstructed at all' % incomplete,
             'RECRAWL. A row whose own IVs or CP were never read cannot be checked against the '
             "game's arithmetic, so its stat line is unverified. keep_policy rule 0 keeps such rows "
             "as data_incomplete, which is why this is a WARN and not a BLOCK.")

    for (key, sid, n, m_cp, m_hp, win, piled) in mismapped:
        sp, pid, form = key
        wcp, whp, wids = win
        fail(BLOCK, "WRONG STAT LINE: (%s, form %s) maps to '%s', which reproduces the stored CP on "
                    'only %d/%d row(s) -- %s reproduces %d/%d (CP+HP %d/%d)%s'
                    % (sp, form, sid, m_cp, n, '/'.join(wids), wcp, n, whp, n,
                       ('; %d of them are IN THE TRANSFER PILE: %s'
                        % (len(piled), ', '.join(piled[:6]))) if piled else ''),
             "The game's own stored CP says these are %s, not '%s'. Every gl_rank/ul_rank on these "
             '%d row(s) was computed from the wrong base stats, so their PvP protection is a number '
             'nobody actually calculated -- the exact shape that lost a Great League #2 Mudbray and '
             'a GL#1 Mareep. Fix the (species, form) entry in form_overrides_complete.py, re-run '
             'the ranker, then re-run keep_policy BEFORE any sync. Release nothing from this pair '
             'until the ranks have been recomputed.' % ('/'.join(wids), sid, n))

    for (key, sid, n, piled) in unreproducible:
        sp, pid, form = key
        fail(WARN, "UNVERIFIABLE STAT LINE: (%s, form %s) -> '%s' reproduces the stored CP on 0/%d "
                   'row(s), and no other stat line on dex %s reproduces it either%s'
                   % (sp, form, sid, n, pid,
                      (' -- %d in the pile: %s' % (len(piled), ', '.join(piled[:6]))) if piled else ''),
             'Either the gamemaster carries no entry with this form\'s real base stats (a '
             'pvpoke_gamemaster.json gap -- refresh it), or these rows\' cp/iv columns are stale '
             'from a torn crawl (RECRAWL and re-check). WARN rather than BLOCK because no '
             'alternative species fits better, so there is no evidence of a WRONG mapping -- only '
             'of an UNVERIFIED one. It becomes a BLOCK the moment some other stat line fits better. '
             'Do not release a mon whose stat line could not be verified.')

    for (key, sid, n, m_cp, m_hp, alt) in hp_dissent:
        sp, pid, form = key
        fail(WARN, "HP TIE-BREAK DISSENT: (%s, form %s) -> '%s' fits the CP evidence exactly as well "
                   'as %s (%d/%d each), but %s also reproduces more stored HP (%d vs %d of %d)'
                   % (sp, form, sid, '/'.join(alt[2]), m_cp, n, '/'.join(alt[2]), alt[1], m_hp, n),
             'Two stat lines on this dex are indistinguishable by CP alone and the HP evidence '
             'favours the OTHER one. Confirm the mapping against the live Form enum before the next '
             'cull. WARN, not BLOCK: the HP columns carry CURRENT hit points on an unknown subset '
             'of rows, so HP on its own is not proof.')

    # ---- what the CP evidence could NOT decide -------------------------------------------------
    # Honest reporting, NOT a weakening of the tie rule: two ids that share a stat line still get
    # no accusation, because CP genuinely cannot separate them. What changes is that the size of
    # that hole is now printed instead of silently absorbed into the "every pair reproduces its
    # stored CP" ok(). The subset that matters is the one where the tied ids have DIFFERENT
    # evolution chains -- Weezing/Ponyta/Rapidash/Slowpoke/Stunfisk/Zigzagoon galarian, Rotom
    # appliances, Tauros paldean, Genesect drives. rank_cache ranks the whole chain and keeps the
    # best stage, so a swap there changes the rank that feeds the rank<=5 keep gate. Shadow twins
    # are collapsed out first: 'bulbasaur' and 'bulbasaur_shadow' carry identical base stats and
    # the SAME family, the ranker keeps shadow as a separate boolean, and to_pvpoke_id never
    # returns a _shadow id (asserted below) -- so they are one pokemon. Without that collapse all
    # 696 ties read as evolution-divergent and the 138 that actually are drown in the other 558.
    if undiscriminated:
        _shadow_mapped = sorted({s for (_k, s, _i, _n) in undiscriminated if '_shadow' in s})
        if _shadow_mapped:
            fail(WARN, 'to_pvpoke_id now maps in-bag rows to SHADOW speciesId(s) (%s) -- the '
                       'shadow-twin collapse in the CP-tie census is no longer sound'
                       % ', '.join(_shadow_mapped[:6]),
                 'The tie census treats "x" and "x_shadow" as one pokemon because the ranker '
                 'carries shadow as a boolean, not as a speciesId. If the mapping starts '
                 'returning shadow ids, that assumption is dead and a shadow/non-shadow mix-up '
                 'stops being invisible-because-harmless. Re-key the collapse in '
                 'audit_invariants.check_stat_line_fidelity().')

        def _chain(i):
            try:
                return tuple(x.replace('_shadow', '') for x in _rk.get_evolutions(gm_by_id, i))
            except Exception:
                return (i,)

        # ...and only when SOME tied id actually evolves. get_evolutions returns the chain INCLUDING the
        # id itself, so a set of non-evolving forms (Oricorio styles, Mimikyu busted, a final stage tied
        # with a pvpoke typo id) yields a different 1-length "chain" per id and read as evolution-split.
        # A swap inside that set cannot move any rank: the ids share a stat line AND neither has a later
        # stage, so the ranker computes the same number either way. Not a coverage gap -- a non-event.
        evo_split = [t for t in undiscriminated
                     if len({_chain(i) for i in t[2]}) > 1 and any(len(_chain(i)) > 1 for i in t[2])]
        info('%d of %d resolvable pair(s) (%d row(s)) could NOT be discriminated by CP -- their '
             'mapped stat line is shared by more than one speciesId on the same dex, so this '
             'invariant proves the stat line and NOT which of the tied ids the mon is'
             % (len(undiscriminated), n_checked,
                sum(t[3] for t in undiscriminated)))
        # ---- THE LIVE FORM ENUM ARBITRATES WHAT CP CANNOT (2026-09-20) --------------------------
        # The DO line under this finding has always said "the only real check is the live Form enum:
        # verify these entries against classify_all_forms.py output, not against memory". That is a
        # check, so run it instead of asking a human to. CP cannot separate burmy_plant from
        # burmy_sandy -- one stat line -- but the game NAMES the variant ('BurmySandy') and the
        # speciesId carries the same word. Score each tied candidate by how many of its suffix tokens
        # the enum name for THIS form id contains; a lone winner decides the pair.
        #   winner == mapped        -> VERIFIED. The hole closes for that pair; it is no longer a
        #                              coverage gap, it is a checked mapping.
        #   winner != mapped, and   -> a REAL mis-mapping the CP evidence could never have shown.
        #     mapped id is suffixed    BLOCK: rank_cache would rank another pokemon's chain.
        #   mapped id is PLAIN      -> deliberate collapse, never an accusation. A costume Pikachu is
        #                              'pikachu' on purpose (measured: all 5 such pairs are costumes).
        #   no lone winner          -> the enum cannot speak either; stays the WARN below.
        _enum_names = {}
        try:
            _enum_names = {int(k): v for k, v in
                           json.load(open(os.path.join(ROOT, 'form_enum.json'), encoding='utf-8')).items()}
        except Exception as _e:
            fail(WARN, 'form_enum.json unreadable (%s) -- the Form-enum arbiter below cannot run and '
                       'every evolution-split CP tie stays unverified' % _e,
                 'Restore form_enum.json (refresh_form_enum.py reads it off the live game).')

        def _etok(x):
            x = str(x)
            if re.search(r'[A-Z]', x[1:]):
                return [t.lower() for t in re.findall(r'[A-Z][a-z0-9]*|[0-9]+', x)]
            return [t for t in re.split(r'[^a-z0-9]+', x.lower()) if t]

        def _etok_match(a, b):   # regional spellings differ by a suffix: alola/alolan, paldea/paldean
            return a == b or (len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)))

        def _escore(cand, form):
            # CONFIRMED tokens minus CONTRADICTED ones. Counting only matches leaves
            # 'darmanitan_standard' and 'darmanitan_galarian_standard' tied at 1 against the name
            # 'DarmanitanStandard'; charging for the 'galarian' the name does NOT carry separates them.
            nm = _etok(_enum_names.get(form, ''))[1:]
            sf = _etok(cand)[1:]
            if not sf:                                   # the plain id wins when the enum is also plain
                return 1 if (not nm or nm[0] in ('normal', 'unset')) else 0
            hit = sum(1 for t in sf if any(_etok_match(t, n) for n in nm))
            return hit - (len(sf) - hit)

        # SELF-TEST: an arbiter that can no longer accuse is worse than none -- it prints "VERIFIED"
        # over the exact gap it was built to close. Two synthetic pairs whose answer is not in doubt.
        _enum_names[-1], _enum_names[-2] = 'GeodudeAlolan', 'CastformSunny'
        _st = [(-1, ['geodude', 'geodude_alolan'], 'geodude_alolan'),
               (-2, ['castform', 'castform_sunny', 'castform_rainy'], 'castform_sunny')]
        for _f, _cs, _want in _st:
            _s2 = {c: _escore(c, _f) for c in _cs}
            _w2 = [c for c, v in _s2.items() if v == max(_s2.values())]
            if _w2 != [_want]:
                fail(BLOCK, 'the Form-enum arbiter FAILED its own self-test: %r with candidates %s '
                            'picked %s, not %r -- it can no longer separate a regional from its plain '
                            'twin, so every "VERIFIED" it printed below is worthless'
                            % (_enum_names[_f], _cs, _w2, _want),
                     'Fix _escore()/_etok() in audit_invariants.check_stat_line_fidelity(). Until then '
                     'treat every evolution-split CP tie as unverified.')
        del _enum_names[-1], _enum_names[-2]

        _verified, _collapse, _unresolved, _contradict, _maximal = [], [], [], [], []
        for t in evo_split:
            _form = t[0][2]
            # shadow twins are ONE pokemon here (same family, ranker carries shadow as a boolean, and
            # to_pvpoke_id never returns a _shadow id -- asserted above), so they must not split the vote
            _cands = sorted({c.replace('_shadow', '') for c in t[2]})
            _sc = {c: _escore(c, _form) for c in _cands}
            _best = max(_sc.values()) if _sc else 0
            _win = [c for c, v in _sc.items() if v == _best]
            # LATER stages only. The own stage is stat-identical across the whole tie by definition, so
            # it cannot move a rank; only a stage the ranker would ADD can. 'pikachu_shaymin' evolves to
            # the same raichu plain 'pikachu' does -- a different first element, an identical ladder.
            _later = lambda i: set(_chain(i)) - {i}
            _mine = _later(t[1])
            if all(_later(c) <= _mine for c in _cands if c != t[1]):
                # The mapped id's chain CONTAINS every rival's -- these are the costume ids (a
                # Pikachu costume has no raichu stage while plain 'pikachu' does, and neither does a
                # stub id like 'pika'). The mapping already
                # picked the maximal chain, so a swap could only ever REMOVE stages, and whether this
                # specimen may use them is decided elsewhere, by rank_cache._reachable() gating the
                # chain on form/gender/costume evolvability. Covered, not unverified.
                _maximal.append(t)
            elif not _enum_names or _best <= 0 or len(_win) != 1:
                _unresolved.append(t)
            elif _win[0] == t[1]:
                _verified.append(t)
            elif not _etok(t[1])[1:]:
                _collapse.append(t)
            else:
                _contradict.append((t, _win[0]))
        if _verified:
            ok('Form enum VERIFIED %d of the %d evolution-split CP tie(s) (%d row(s)): the live form '
               'name names the same variant the mapping picked'
               % (len(_verified), len(evo_split), sum(t[3] for t in _verified)))
        if _maximal:
            info('%d evolution-split tie(s) (%d row(s)) map to the id whose chain CONTAINS every tied '
                 "rival's -- the costume/cosmetic ids that simply lack the later stage. A swap could "
                 'only shorten the chain, and rank_cache._reachable() already gates later stages on '
                 'form/gender/costume evolvability' % (len(_maximal), sum(t[3] for t in _maximal)))
        if _collapse:
            info('%d evolution-split tie(s) map a NAMED form to the PLAIN speciesId on purpose '
                 '(costume/cosmetic collapse, e.g. %s) -- not an accusation'
                 % (len(_collapse), ', '.join(sorted({_enum_names.get(t[0][2], '?') for t in _collapse})[:4])))
        for t, want in _contradict:
            fail(BLOCK, 'FORM ENUM CONTRADICTS THE MAPPING: (%s, form %s) is named %r by the live Form '
                        'enum but maps to %r; %r is the tied id that name describes, and the two have '
                        'DIFFERENT evolution chains, so rank_cache is ranking another pokemon (%d row(s))'
                        % (t[0][0], t[0][2], _enum_names.get(t[0][2]), t[1], want, t[3]),
                 'Fix the (species, form) entry in form_overrides_complete.py to resolve to %r, then '
                 're-run the ranker. CP cannot see this class of error at all -- the two ids share a '
                 'stat line -- so this arbiter is the only thing standing in front of it. Do NOT '
                 'release anything from the pile until the ranks are rebuilt.' % want)
        evo_split = _unresolved
        if evo_split:
            ex = sorted({'%s -> %s (tied with %s)'
                         % (t[0][0], t[1], '/'.join(x for x in t[2] if x != t[1])[:60])
                         for t in evo_split})
            fail(WARN, '%d of those pair(s) (%d row(s)) are tied to speciesId(s) with a DIFFERENT '
                       'evolution chain, so a mis-mapping there would change the rank this project '
                       'culls on and CP could not detect it: %s'
                       % (len(evo_split), sum(t[3] for t in evo_split), '; '.join(ex[:6])),
                 'Not a defect report -- a coverage gap, stated so it stops being invisible. These '
                 'are the regional/appliance/drive splits (galarian Weezing, Rapidash, Slowpoke, '
                 'Ponyta, Stunfisk, Zigzagoon; Rotom forms; paldean Tauros; Genesect drives) whose '
                 'variants share a stat line but not a family, and rank_cache ranks the whole chain '
                 'and keeps the best stage -- so the wrong twin yields a rank computed for another '
                 'pokemon, which is exactly what feeds the rank<=5 keep gate. CP cannot arbitrate '
                 'them and must not be made to (that would manufacture false accusations). The only '
                 'real check is the live Form enum: verify these (species, form) entries in '
                 'form_overrides_complete.py against classify_all_forms.py output, not against '
                 'memory. WARN, not BLOCK, because nothing here is evidence that any of them IS '
                 'wrong -- only that this invariant cannot say.')
        else:
            ok('every CP-indiscriminable tie is between speciesIds that share an evolution chain '
               '(a swap could not change any rank)')

    if partial:
        info('%d pair(s) have individual rows whose CP does not reconstruct while the pair as a '
             'whole does -- per-row staleness (a powered-up mon crawled mid-write), not a mapping '
             'error: %s' % (len(partial),
                            ', '.join('%s/f%s %d/%d' % (k[0], k[2], mc, nn)
                                      for (k, _s, nn, mc, _p) in partial[:8])))
        stale_piled = sorted({u for (_k, _s, _n, _m, pl) in partial for u in pl})
        if stale_piled:
            fail(WARN, '%d pile member(s) have a CP that matches no level of their own stat line: %s'
                       % (len(stale_piled), ', '.join(stale_piled[:8])),
                 'RECRAWL before releasing these. Their own stored CP does not match any '
                 'level of its own base stats, so the crawl that produced this pile decision was '
                 'not clean.')
    if not mismapped and not unreproducible:
        ok('every resolvable (species,form) pair reproduces its stored CP under the speciesId it '
           'maps to (%d/%d pairs reconstruct on every row)' % (n_clean, n_checked))

    # ---- I7.2  form and fresh_form must resolve to the SAME stat line -------------------------
    if formdrift:
        ex = ['%s: form %s -> %s but fresh_form %s -> %s' % (d[1], d[2], d[4], d[3], d[5])
              for d in formdrift[:6]]
        fail(BLOCK, '%d in-bag row(s) resolve to a DIFFERENT speciesId through fresh_form than '
                    'through the `form` column the ranker reads: %s'
                    % (len(formdrift), '; '.join(ex)),
             'The ranker keys on `form` on purpose (see FRESH_TWINS). When the two disagree, the mon '
             'was ranked against a stat line it does not have. Re-run normalize_forms.py and the '
             'ranker, then re-run keep_policy before any sync.')
    else:
        ok('form and fresh_form resolve to the same speciesId on every in-bag row')

    # ---- I7.3  THE MUDBRAY CASE: species did not resolve -> NULL ranks -> must be PROTECTED ----
    # A Mudbray whose species_name parsed as "pid749" had no FORM_OVERRIDES entry, resolved to no
    # gamemaster speciesId, produced NULL ranks -- and the old engine read NULL as "no PvP
    # protection" instead of "unknown -> protect". Its real rank was GREAT LEAGUE #2 of 4096
    # (99.65%). It is gone. keep_policy rule 15c now keeps a both-NULL-rank row as 'rank_unknown';
    # what follows asserts that guard actually bit, on every such mon, every run -- and BLOCKS if
    # one reached the irreversible pile anyway.
    if placeholder_rows:
        fail(BLOCK, '%d in-bag row(s) carry a RAW PID PLACEHOLDER as species_name (%s) -- the crawl '
                    'never resolved the species'
                    % (len(placeholder_rows),
                       ', '.join(sorted({r[1] for r in placeholder_rows})[:8])),
             'This is the literal Mudbray signature: "pid749". A placeholder name can never match a '
             'FORM_OVERRIDES key, never resolves to a gamemaster speciesId, and produces NULL ranks '
             'on a mon that may be a league #2. RECRAWL until the species resolves; do not cull '
             'while any row still carries one.')
    else:
        ok('no in-bag row carries a raw pid placeholder species_name (the Mudbray signature)')

    if unresolved_rows:
        pairs_u = sorted({(r[1], r[3], r[4]) for r in unresolved_rows})
        fail(WARN, '%d in-bag row(s) in %d (species,form) pair(s) resolve to a speciesId that is NOT '
                   'in the gamemaster -- every PvP axis is BLIND for them: %s'
                   % (len(unresolved_rows), len(pairs_u),
                      ', '.join("%s f=%s -> '%s'" % p for p in pairs_u[:8])),
             'Add the missing (species, form) entries to form_overrides_complete.py (or refresh '
             'pvpoke_gamemaster.json) and re-run the ranker. WARN, not BLOCK, ONLY because the '
             'assertions immediately below verify that every one of these mons is in fact PROTECTED '
             "as 'rank_unknown' and is out of the pile. Unknown must mean protected, never fodder.")
        stale = [r for r in unresolved_rows if not (r[5] is None and r[6] is None)]
        if stale:
            fail(BLOCK, '%d row(s) whose species does NOT resolve still carry non-NULL gl/ul ranks: %s'
                        % (len(stale),
                           ', '.join('%s(%s f=%s)' % (r[0], r[1], r[3]) for r in stale[:6])),
                 'Those ranks belong to a DIFFERENT form. The ranker is supposed to NULL all 12 rank '
                 'columns when it cannot map a row (rank_cache.py / compute_all_ranks.py). Stale '
                 'ranks on an unmappable row are protection decided from numbers computed for '
                 'another pokemon. Re-run the ranker.')
        else:
            ok('every unresolvable row carries NULL ranks (no stale ranks leaked from a prior form)')
    else:
        ok('every in-bag (species,form) resolves to a gamemaster speciesId')

    info('%d in-bag row(s) have BOTH gl_rank and ul_rank NULL (rule 15c "rank_unknown" territory)'
         % len(norank_rows))
    if norank_rows:
        if pile is None:
            fail(BLOCK, 'cannot read 6_Transfer.txt, so it is impossible to prove the %d NULL-rank '
                        'mon(s) are out of the irreversible pile' % len(norank_rows),
                 'Re-run keep_policy.py. A NULL-rank mon is one whose PvP worth was NEVER computed; '
                 'it may not be released on the strength of a check that did not happen.')
        else:
            in_pile = [r for r in norank_rows if r[0] in pile]
            if in_pile:
                fail(BLOCK, 'THE MUDBRAY CASE IS LIVE: %d mon(s) with NO gl_rank and NO ul_rank are '
                            'in the TRANSFER pile: %s'
                            % (len(in_pile),
                               ', '.join('%s (%s f=%s)' % (r[0], r[1], r[3]) for r in in_pile[:8])),
                     'These mons were never judged on PvP at all -- their ranks were never computed, '
                     'and NULL is being read as "not a keeper" instead of "we do not know". A '
                     'Mudbray in exactly this state was Great League #2 of 4096 and was released. '
                     'DO NOT SYNC. Restore keep_policy rule 15c ("rank_unknown"), fix the mapping in '
                     'form_overrides_complete.py, re-run the ranker and re-run keep_policy.')
            else:
                ok('no NULL-rank mon is in the Transfer pile')
        if reasons is None:
            fail(BLOCK, 'policy_reasons.json unreadable, so the "unknown rank => PROTECTED" '
                        'assertion cannot be made for %d mon(s)' % len(norank_rows),
                 'Re-run keep_policy.py. Without the reason map there is no evidence rule 15c '
                 'protected these at all.')
        else:
            unprot = [r for r in norank_rows
                      if 'rank_unknown' not in (reasons.get(r[0]) or [])]
            if unprot:
                fail(BLOCK, '%d NULL-rank mon(s) do NOT carry the "rank_unknown" keep reason: %s'
                            % (len(unprot),
                               ', '.join('%s (%s f=%s -> %s)' % (r[0], r[1], r[3], r[4])
                                         for r in unprot[:8])),
                     'keep_policy rule 15c must mark EVERY row with both ranks NULL as '
                     "'rank_unknown'. One that is not marked is being judged on PvP data that was "
                     'never computed. Restore rule 15c and re-run keep_policy.py -- unknown is '
                     'PROTECTED, it is never "no protection".')
            else:
                ok('every NULL-rank mon carries the "rank_unknown" keep reason (unknown = PROTECTED)')


# ============================================================================= I8 TAG VOCABULARY
# (2026-09-26, user: "Be clear with what I need to do simply in the tag names" / "always put them on top".) A tag name IS
# the instruction: <= 18 characters, a legal filename, the action tags first in the in-game list.
# THE FOLD (2026-09-29, user: "fix the redundant tags? I either evolve once or evolve twice" + "I also like to see the
# separate PVP ones"): every evolve advice is ONE table, granular_tags.evolve_advice -> system/analysis/evolve_advice.json
# ({uid: {targets, steps, gated, gate, leagues, source, tags}}), labelled Evolve Once / Evolve Twice by the number of
# evolutions to the target, Evolve Gated when the game blocks it, plus Evolve for GL / UL on a PvP comb-up. The dynamic
# 'Stop at <stage>' tags, Evolve Next, Evo Best Gated, Evolve Shiny (+ Gated) and Evolve for Size are RETIRED: prune
# strips them, retire_tags deletes the shells. Asserted here: the vocabulary, prune's PLAN, order_tags.ORDER and
# RETIRED_TAGS agree; the table equals the five evolve tag files exactly and every row is a kept, unfused mon tagged by
# its own fields; the dust advice (Power Up / Unlock 2nd Move) sits on kept mons only, never beside an evolve tag; no
# post-tags path still pushes Evolve for Size; the remote-trade stamp and retire_tags' grace clock are written the safe
# way round. Like I5 this TRUSTS the engine's output files and cross-checks them (the membership RULE is re-derived by
# audit_tags_membership / audit_tag_truth). The one independent read: the CLIENT game master (evolvable_forms) must
# count the same evolutions as every Once / Twice -- a Twice the game calls ONE evolution is the Tympole trap (evolved
# past its target and into the pile, 2026-09-25/26), so that direction BLOCKs.
TAG_NAME_MAX = 18           # the longest name the game has accepted (Evolve Shiny Gated); the real limit is unknown
_WIN_BAD = set('<>:"/\\|?*')   # ':' is the nasty one: NTFS writes an alternate data stream, not the tagset file
_WIN_RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {'COM%d' % i for i in range(10)} | {'LPT%d' % i for i in range(10)}
# (2026-09-29) what the fold retired, pinned: a name dropped from granular_tags.RETIRED_TAGS is no longer stripped by
# prune nor deleted by retire_tags, so the old label stays on the phone for good. The Stop names come from stop_tags.json.
FOLD_RETIRED = ('Evolve Next', 'Stop at Mid Stage', 'Evo Best Gated', 'Evolve Shiny', 'Evolve Shiny Gated',
                'Evolve for Size',
                'Evo Best GL', 'Evo Best UL', 'Evo GL Rank 1-5', 'Evo UL Rank 1-5')   # THE SECOND FOLD (2026-09-30)


def _calls_named(path, callee, skip_fn=None):
    """Line numbers of every call to `callee` (bare or attribute) in `path`, outside the def `skip_fn`. None = no parse."""
    t = tree(path)
    if t is None:
        return None
    skip = set()
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == skip_fn:
            skip |= {id(x) for x in ast.walk(n)}
    out = []
    for n in ast.walk(t):
        if isinstance(n, ast.Call) and id(n) not in skip:
            f = n.func
            if (f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', '')) == callee:
                out.append(n.lineno)
    return sorted(out)


def _gm_steps(ef, src, dst):
    """Evolutions from game-master pokemonId `src` to `dst` over the CLIENT game master's branches (evolvable_forms._costs,
    species level); None when it shows no way. Independent of pvpoke's families, which granular_tags.steps_between reads
    (and whose 'parent' links are wrong in places: carkol -> boltund). (2026-09-29)"""
    if not src or not dst:
        return None
    front, seen = [src], {src}
    for d in (1, 2, 3):
        nxt = []
        for s in front:
            for e in (ef._costs.get(s) or {}):
                if e == dst:
                    return d
                if e not in seen:
                    seen.add(e)
                    nxt.append(e)
        front = nxt
    return None


def _written_on_rc0(path, const):
    """[(line, ok)] for every WRITE of the file the module constant `const` names -- an open() in a write mode, or an
    os.replace / rename / move onto it. ok = it can run only when the step's rc is 0: in the else of `if r:` (or the
    body of `if not r:` / `if r == 0:`), r bound from a call, and every except around that call sets r non-zero or
    raises. None = no parse. (2026-09-29, sync_post_tags' remote-trade stamp)"""
    t = tree(path)
    if t is None:
        return None
    par = _parent_map(t)
    names = lambda n: any(isinstance(x, ast.Name) and x.id == const for x in ast.walk(n))
    out = []
    for n in ast.walk(t):
        if not isinstance(n, ast.Call):
            continue
        cn = _call_name(n)
        if cn == 'open' and n.args and names(n.args[0]):
            m = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == 'mode'), None)
            if m is None or (isinstance(m, ast.Constant) and not set(str(m.value)) & set('wax+')):
                continue                                  # a read
        elif not (cn in ('replace', 'rename', 'move') and len(n.args) > 1 and names(n.args[1])):
            continue
        guard, up, fn = None, n, None
        while id(up) in par:
            p = par[id(up)]
            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = p
                break
            if isinstance(p, ast.If) and guard is None:
                te, in_else = p.test, any(up is s for s in p.orelse)
                if isinstance(te, ast.Name) and in_else:
                    guard = te.id
                elif isinstance(te, ast.UnaryOp) and isinstance(te.op, ast.Not) and isinstance(te.operand, ast.Name) \
                        and not in_else:
                    guard = te.operand.id
                elif isinstance(te, ast.Compare) and isinstance(te.left, ast.Name) and len(te.ops) == 1 \
                        and isinstance(te.comparators[0], ast.Constant) and te.comparators[0].value == 0 \
                        and (isinstance(te.ops[0], ast.NotEq) if in_else else isinstance(te.ops[0], ast.Eq)):
                    guard = te.left.id
            up = p
        good = False
        if guard and fn is not None:
            binds = [a for a in ast.walk(fn) if isinstance(a, ast.Assign)
                     and any(isinstance(g, ast.Name) and g.id == guard for g in a.targets)]
            calls = [a for a in binds if any(isinstance(x, ast.Call) for x in ast.walk(a.value))]
            good = bool(calls)
            for tr in (x for x in ast.walk(fn) if isinstance(x, ast.Try)):
                inside = {id(x) for s in tr.body for x in ast.walk(s)}
                if not any(id(a) in inside for a in calls):
                    continue
                for h in tr.handlers:           # an exception must never leave r at 0 (or at the previous step's 0)
                    nz = any(a in binds and isinstance(a.value, ast.Constant) and a.value.value for a in ast.walk(h))
                    if not (nz or _stmts_refuse(h.body)):
                        good = False
        out.append((n.lineno, good))
    return out


def check_tag_vocabulary(con):
    section('I8', 'TAG VOCABULARY -- names, the evolve-advice table (the fold), the advice tags')
    try:
        import granular_tags as gt
        import set_db_tags_from_files as mirror
        reg, vocab = gt.registry(), gt.all_tags()        # both raise SystemExit on a broken vocabulary
        ev, dust = tuple(gt.EVOLVE_TAGS), (gt.POWER_UP_GL, gt.POWER_UP_UL, gt.SECOND_MOVE)
    except (Exception, SystemExit) as e:
        fail(BLOCK, 'cannot import granular_tags / set_db_tags_from_files, or its vocabulary does not build (%s)' % e,
             'Fix it first. prune_tags derives its whole PLAN from granular_tags.registry() (it refuses to run without '
             'it), the DB mirror turns filenames back into tag names, and all_tags() refuses a name that is both live '
             'and RETIRED.')
        return

    def _mem(t):
        p = os.path.join(TD, reg[t][0] if t in reg else gt.filename(t))
        return {u for u in open(p, encoding='utf-8').read().split() if u} if os.path.exists(p) else set()

    # ---- I8.1  every managed name: <= 18 characters, a legal Windows filename, reads back to itself ---------------
    bad, by_file = [], defaultdict(list)
    for t in sorted(set(reg) | set(gt.EXEMPT_TAGS)):
        fn = reg[t][0] if t in reg else gt.filename(t)
        by_file[fn.lower()].append(t)
        why = []
        if len(t) > TAG_NAME_MAX:
            why.append('%d characters' % len(t))
        if set(t) & _WIN_BAD or any(ord(ch) < 32 for ch in t):
            why.append('a character Windows refuses in a filename (%s)' % ''.join(sorted(set(t) & _WIN_BAD)))
        if fn[:-4].split('.')[0].strip().upper() in _WIN_RESERVED:
            why.append('%s is a reserved Windows device name' % fn)
        if mirror.tag_of(fn) != t:
            why.append('the DB mirror reads %r back out of %s' % (mirror.tag_of(fn), fn))
        if why:
            bad.append('%r: %s' % (t, '; '.join(why)))
    bad += ['%s is the file of %s (Windows is case-blind)' % (k, ' AND '.join(v)) for k, v in by_file.items() if len(v) > 1]
    if bad:
        fail(BLOCK, '%d managed tag name(s) break the name contract: %s' % (len(bad), ' | '.join(bad[:6])),
             'Rename in granular_tags. %d characters is the longest name the game has accepted -- an over-long one can '
             'fail like colour 9 (AddTag says ok, the tag never appears); an illegal character breaks the tagset file '
             "(':' writes an NTFS alternate stream); a '_' in a name makes set_db_tags_from_files mirror a different "
             'name than prune pushes.' % TAG_NAME_MAX)
    else:
        ok('all %d managed tag names are <= %d characters, legal Windows filenames, and read back to themselves '
           'through the DB mirror (set_db_tags_from_files.tag_of)' % (len(by_file), TAG_NAME_MAX))

    # ---- I8.2  the fold's vocabulary: evolve tags registered and on top; retired names out of it and off disk -----
    retired = set(gt.RETIRED_TAGS)
    bad = ['%s is not in all_tags() / registry()' % t for t in ev if t not in vocab or t not in reg]
    # THE SECOND FOLD (2026-09-30, user: "The tag is the bug"): a keep label must never read as an evolve instruction.
    # 'Evo UL Rank 1-5' did, and he asked whether to evolve 14 copies -- 13 of them copies of a stage he already owned
    # as good or better. A managed name with an evolve word is an EVOLVE_TAGS member or says it in the negative.
    bad += ['%r reads as an evolve instruction but is not an evolve tag' % t for t in sorted(vocab)
            if re.search(r'\bEvo', t) and t not in ev and not t.endswith('No Evolve')]
    bad += ['%s is RETIRED and still managed' % t for t in sorted(retired & (set(vocab) | set(reg) | set(gt.EXEMPT_TAGS)))]
    stops = []
    try:
        stops = json.load(open(gt.STOP_REGISTRY, encoding='utf-8'))
        if not isinstance(stops, list) or any(not isinstance(x, str) for x in stops):
            bad.append('stop_tags.json is not a list of tag names')
            stops = []
    except FileNotFoundError:
        info('stop_tags.json absent -- no Stop tag left to retire')
    except (OSError, ValueError) as e:
        bad.append('stop_tags.json unreadable (%s) -- the Stop tags it names just fell out of RETIRED_TAGS' % e)
    folded = sorted(set(FOLD_RETIRED) | set(stops))
    bad += ['%s is no longer RETIRED' % t for t in folded if t not in retired]
    bad += ['%s is RETIRED but still has a tagset file' % t for t in sorted(retired)
            if os.path.exists(os.path.join(TD, gt.filename(t)))]
    if bad:
        fail(BLOCK, "the fold's vocabulary is broken: %s" % ' | '.join(bad[:6]),
             "granular_tags.EVOLVE_TAGS must be in all_tags() (registry() = prune's PLAN is built from it). Every name "
             'the fold retired (%s, and every stop_tags.json name) must STAY in RETIRED_TAGS -- that is what makes prune '
             'strip it and retire_tags delete its shell -- and never has a tagset file (build_tagsets deletes it; a '
             'leftover is an orphan prune refuses). Keep stop_tags.json: nothing else remembers the Stop names.'
             % ', '.join(FOLD_RETIRED))
    else:
        ok("the %d evolve tags are in all_tags() and prune's PLAN; the fold's %d retired names (%d Stop tags among them) "
           'stay RETIRED, and none of the %d RETIRED names is managed or has a tagset file'
           % (len(ev), len(folded), len([t for t in folded if t.startswith('Stop')]), len(retired)))
    _pr = code_only('system/scripts/prune_tags.py')
    if not (re.search(r'granular_tags\.registry\(\)', _pr) and re.search(r'(?m)^PLAN\s*=\s*_build_plan\(\)', _pr)):
        fail(BLOCK, 'prune_tags.PLAN is no longer derived from granular_tags.registry()',
             'The evolve tags reach prune ONLY through registry(). Restore PLAN = _build_plan() -> '
             'granular_tags.registry(); a hand-listed PLAN drifts from the vocabulary the moment a tag is renamed.')
    orphans, _missing = gt.audit_registry(reg, td=TD, strict=False)
    if orphans:
        fail(BLOCK, '%d tagset file(s) have no plan entry and no exemption: %s' % (len(orphans), orphans[:6]),
             "prune_tags refuses to import with an orphan on disk (granular_tags.audit_registry). A retired name's file "
             '(Evolve_Next.txt, Stop_*.txt ...) means build_tagsets did not run its RETIRED sweep -- re-run it.')
    else:
        ok('no orphan tagset file (every .txt is planned or exempt)')
    # Transfer counts as an action tag (user 2026-09-30: "put the transfers tag on top"): it heads ORDER, then the evolve
    # and dust tags, then the reference tags.
    order, act = _module_const('system/scripts/order_tags.py', 'ORDER'), ['Transfer'] + list(ev) + list(dust)
    if not isinstance(order, (list, tuple)):
        fail(WARN, 'order_tags.ORDER is not readable as a literal list -- cannot say the action tags sit on top',
             'Keep ORDER a plain list literal in system/scripts/order_tags.py.')
    else:
        first = next((i for i, t in enumerate(order) if t not in act), len(order))
        low = [t for t in act if t not in order] + [t for t in act if t in order and order.index(t) > first]
        if low:
            fail(WARN, 'action tag(s) missing from order_tags.ORDER or listed below a reference tag: %s' % low,
                 'User 2026-09-26: "always put them on top." Put every evolve tag and Power Up / Unlock 2nd Move at the '
                 'head of ORDER; an unlisted tag sorts below every listed one on the phone.')
        else:
            ok('order_tags.ORDER lists the %d action tags first (%s)' % (len(act), ', '.join(act)))
    if not re.search(r'granular_tags\.registry\(\)', code_only('system/scripts/retire_tags.py')):
        fail(WARN, 'retire_tags.py no longer sweeps granular_tags.registry() for empty managed shells',
             'An empty evolve tag then stays on the phone as a 0-member chip (user 2026-09-23: "delete the tags '
             'they\'re empty"). Restore the registry sweep: a registered tag whose file is PRESENT AND EMPTY.')

    # ---- I8.3  post-tags: no path pushes Evolve for Size; the two new state files are written the safe way round ---
    spt, rtg = 'sync_post_tags.py', 'system/scripts/retire_tags.py'
    t_spt = tree(spt)
    if t_spt is None:
        fail(BLOCK, '%s does not parse -- cannot prove it no longer pushes the retired Evolve for Size' % spt,
             'Fix the syntax error.')
    else:
        imps = {a.name.split('.')[0] for n in ast.walk(t_spt) if isinstance(n, ast.Import) for a in n.names} | \
               {n.module.split('.')[0] for n in ast.walk(t_spt) if isinstance(n, ast.ImportFrom) and n.module}
        push = (['imports sync_evolve_size'] if 'sync_evolve_size' in imps else []) + \
               ['code string %r' % s[:60] for s in sorted(_ast_strings(spt))
                if 'evolve for size' in s.lower() or 'sync_evolve_size' in s]
        if push:
            fail(BLOCK, "%s still pushes the RETIRED 'Evolve for Size': %s" % (spt, '; '.join(push[:4])),
                 'The fold (2026-09-29) moved those picks into Evolve Once / Twice (granular_tags.evolve_advice), which '
                 'prune pushes; a second writer re-creates a retired tag every cull and prune strips it again the next.')
        else:
            ok("%s no longer pushes 'Evolve for Size' (no sync_evolve_size import, no such name in code)" % spt)
    _sec = sorted(s for s in _ast_strings('full_audit.py') if s.strip(' =').upper() == 'EVOLVE FOR SIZE')
    if _sec:
        fail(WARN, "full_audit.py still expects an 'EVOLVE FOR SIZE' section from sync_post_tags: %s" % _sec,
             "sync_post_tags prints only '=== REMOTE TRADE ===' and '=== TAG ORDER ===' since the fold (2026-09-29); drop "
             'the key from post_tags_step.')
    else:
        ok("full_audit.py expects no 'EVOLVE FOR SIZE' section (post-tags = Remote Trade + tag order)")
    _w = _written_on_rc0(spt, 'RT_STAMP')
    if _w is None:
        pass                                                   # the parse failure is reported above
    elif not _w:
        info('%s writes no RT_STAMP -- no skip, every cull re-verifies Remote Trade' % spt)
    elif not all(g for _l, g in _w):
        fail(BLOCK, '%s writes the remote-trade stamp where the push may have failed (line(s) %s)'
                    % (spt, [l for l, g in _w if not g]),
             'remote_trade_verified.json lets the next cull SKIP the Remote Trade re-verify for RT_REVERIFY_H hours, so '
             'it may only be written when that step returned rc 0 (the else of `if r:`, every except setting r = 1). '
             'Written after a failed push, the phone can keep offering an old set -- a keeper among them -- for hours.')
    else:
        ok('%s writes the remote-trade stamp only on rc 0 (line(s) %s)' % (spt, [l for l, _g in _w]))
    _gf = [a for a in ast.walk(tree(rtg) or ast.Module(body=[], type_ignores=[]))
           if isinstance(a, ast.Assign) and isinstance(a.value, ast.Call) and _call_name(a.value) == 'grace_filter']
    _att = sorted(x for c in ('wait_ready_to_attach', 'get_session') for x in (_calls_named(rtg, c) or []))
    _gok = [a for a in _gf if _att and a.lineno < _att[0] and a.value.args and isinstance(a.value.args[0], ast.Name)
            and isinstance(a.targets[0], ast.Tuple) and a.targets[0].elts and isinstance(a.targets[0].elts[0], ast.Name)
            and a.targets[0].elts[0].id == a.value.args[0].id]
    if not _gok:
        fail(WARN, 'retire_tags.py no longer runs grace_filter over the empty shells before the attach (calls at %s, '
                   'attach at %s)' % ([a.lineno for a in _gf], _att[:1]),
             'An evolve tag flips between 0 and 1 members from cull to cull; deleting its shell at the first empty pass '
             'and re-creating it the next reshuffled the whole tag order every cull (2026-09-27..29). Restore '
             '`empty_files, waiting = grace_filter(empty_files, a.grace_hours)` BEFORE pg.wait_ready_to_attach.')
    else:
        ok('retire_tags.py filters the empty shells through grace_filter (line %d) before the attach (line %d)'
           % (_gok[0].lineno, _att[0]))

    # ---- I8.4  THE TABLE: evolve_advice.json == the five evolve tag files; every row kept, unfused, true to itself --
    try:
        reasons = json.load(open(os.path.join(ANA, 'policy_reasons.json'), encoding='utf-8'))
        kept = {u for u in reasons if not u.startswith('_')}
    except Exception as e:
        fail(BLOCK, 'policy_reasons.json unreadable (%s) -- cannot prove the advice tags sit on kept mons' % e,
             'Re-run keep_policy.py.')
        return
    pile = set()
    for _fn in ('6_Transfer.txt', 'Transfer.txt'):
        if os.path.exists(os.path.join(TD, _fn)):
            pile |= {u for u in open(os.path.join(TD, _fn), encoding='utf-8').read().split() if u}
    try:
        fused = {u for (u,) in con.execute('SELECT uid_hex FROM pokemon WHERE in_bag=1 AND COALESCE(is_component,0)!=0')}
    except sqlite3.OperationalError:
        fused = set()                                          # no column: keep_config.is_fused_component says False too
    adv = None
    try:
        adv = json.load(open(gt.EVOLVE_ADVICE, encoding='utf-8'))
        if not isinstance(adv, dict):
            raise ValueError('not a {uid: row} object')
    except (OSError, ValueError) as e:
        adv = None
        fail(BLOCK, 'evolve_advice.json is missing or unreadable (%s)' % e,
             'build_tagsets writes it in the same pass as the five evolve tag files (granular_tags.LAST_ADVICE); the '
             "report's which-way-to-evolve lines and these checks read it. Re-run build_tagsets.py.")
    if adv is not None:
        rowbad, want, src_n = [], defaultdict(set), defaultdict(int)
        for u, e in sorted(adv.items()):
            if not isinstance(e, dict) or not all(isinstance(e.get(k), list) and all(isinstance(x, str) for x in e[k])
                                                  for k in ('tags', 'targets', 'leagues')):
                rowbad.append('%s: not a row (tags / targets / leagues must be lists of names)' % u)
                continue
            src_n[str(e.get('source'))] += 1
            for t in e['tags']:
                want[t].add(u)
            lg = e['leagues']
            rule = [gt.evolve_tag(e.get('gated'), e.get('gate'), e.get('final'))] + \
                   [gt.SIMPLE.get('pvp_combup_%s' % x, '?%s' % x) for x in lg]
            why = ([] if e.get('steps') in (1, 2) else ['steps %r' % (e.get('steps'),)]) + \
                  ([] if isinstance(e.get('final'), bool) else ['final %r' % (e.get('final'),)]) + \
                  ([] if e.get('targets') else ['no target']) + \
                  ([] if set(lg) <= {'gl', 'ul'} else ['leagues %r' % lg]) + \
                  ([] if sorted(e['tags']) == sorted(rule) else ['tags %s but its fields say %s' % (e['tags'], rule)])
            if why:
                rowbad.append('%s: %s' % (u, ', '.join(why)))
        where = ['%s %s' % (u, 'is in the pile' if u in pile else 'is a fused component' if u in fused else 'is not kept')
                 for u in sorted(adv) if u not in kept or u in pile or u in fused]
        diff = ['the table names non-evolve tag(s) %s' % sorted(set(want) - set(ev))] if set(want) - set(ev) else []
        for t in ev:
            if not os.path.exists(os.path.join(TD, reg[t][0] if t in reg else gt.filename(t))):
                diff.append('%s: NO tagset file' % t)
            elif _mem(t) != want.get(t, set()):
                diff.append('%s: file %d vs table %d (%d only in the file, %d only in the table)'
                            % (t, len(_mem(t)), len(want.get(t, ())), len(_mem(t) - want.get(t, set())),
                               len(want.get(t, set()) - _mem(t))))
        if rowbad or where or diff:
            fail(BLOCK, 'evolve_advice.json and the evolve tags disagree: %s' % ' | '.join((diff + where + rowbad)[:6]),
                 'THE RULE (2026-10-25): one table, one row per copy -- gated -> Evolve Needs Item (every gate an item) or '
                 'Evolve Needs Task, else Evolve to Final (every target ends its line) or Evolve to Mid, plus Evolve for GL / '
                 'UL per comb-up league; never a pile mon, never a fused component; the evolve tag files are exactly the '
                 'table. build_tagsets writes both in one pass, so a gap '
                 'is a stale or hand-edited file (or a crash between the two writes): re-run build_tagsets.py; if it '
                 'persists, granular_tags.evolve_advice and the tag files disagree.')
        else:
            ok('evolve_advice.json: %d row(s) (%s), every one kept, unfused and tagged by its own fields; the '
               'evolve tag files are exactly the table (%s)'
               % (len(adv), ', '.join('%s %d' % kv for kv in sorted(src_n.items())),
                  ', '.join('%s %d' % (t, len(_mem(t))) for t in ev)))

    # ---- I8.5  advice tags ride on KEPT mons only, and never contradict each other ---------------------------------
    advice = list(ev) + list(dust)
    stray = ['%s: %s' % (t, sorted(_mem(t) - kept)[:4]) for t in advice if _mem(t) - kept]
    if stray:
        fail(BLOCK, 'advice tag(s) on a mon that is NOT kept (piled, gone, or never decided): %s' % ' | '.join(stray[:6]),
             'Evolve / Power Up / Unlock 2nd Move are advice for KEPT mons; on a pile mon they say "invest in this" '
             'about fodder. build_tagsets strips the pile from every tag -- re-run it; granular_tags.evolve_advice / '
             'power_ups / second_move_ones must only see kept rows.')
    else:
        ok('every advice tag member is kept (%s)' % ', '.join('%s %d' % (t, len(_mem(t))) for t in advice))
    law = []
    if _mem(gt.POWER_UP_GL) & _mem(gt.POWER_UP_UL):
        law.append('in both Power Up tags: %s' % sorted(_mem(gt.POWER_UP_GL) & _mem(gt.POWER_UP_UL))[:4])
    if _mem(gt.POWER_UP_UL) & _mem(gt.SIMPLE['pvp_best_gl']):
        law.append('%s on a Best GL keeper: %s' % (gt.POWER_UP_UL, sorted(_mem(gt.POWER_UP_UL) & _mem(gt.SIMPLE['pvp_best_gl']))[:4]))
    as_reason = sorted(set(dust) & set(gt.SIMPLE.values()))
    if as_reason:
        law.append('a keep reason is labelled with a dust-advice tag: %s' % as_reason)
    _beside = sorted(set().union(*(_mem(t) for t in dust)) & set().union(*(_mem(t) for t in ev)))   # (2026-09-29)
    if _beside:
        law.append('Power Up / Unlock 2nd Move beside an evolve tag: %s' % _beside[:4])
    if law:
        fail(BLOCK, 'advice tags contradict each other or a keeper: %s' % ' | '.join(law),
             "Powering a Great League keeper for Ultra burns it past 1500 for good (user 2026-09-26: never 'Power Up to "
             "2500' on a GL keeper); dust advice is never a keep reason; and a copy told to evolve is never told to "
             'power up the stage it is leaving (build_tagsets strips Power Up / Unlock 2nd Move off every EVOLVE_TAGS '
             'member). Fix granular_tags.power_ups / SIMPLE or that strip and re-run build_tagsets.py.')
    else:
        ok('no copy is told to power up for both leagues, none for Ultra while it is a Best GL keeper, no keep reason is '
           'labelled with dust advice, and no evolve-tagged copy carries Power Up / Unlock 2nd Move')

    # ---- I8.6  independent read: the CLIENT game master confirms where every Evolve to Mid / Final ends (2026-10-25) --------
    if adv:
        try:
            import evolvable_forms as _ef
            from pvp_iv_rule import pvid as _pvid
            _ef._load()
            if not isinstance(_ef._costs, dict):
                raise ValueError('evolvable_forms._costs did not load')
        except Exception as e:
            fail(WARN, 'cannot read the client game master to check where the evolutions end (%s)' % e,
                 'Restore gamemaster_pokeminers.json / evolvable_forms.')
            return
        rows = {u: (sp, fo) for u, sp, fo in con.execute('SELECT uid_hex, species_name, form FROM pokemon WHERE in_bag=1')}
        past, short, blind, n = [], [], [], 0
        for u, e in sorted(adv.items()):
            if not isinstance(e, dict) or e.get('gated') or not isinstance(e.get('final'), bool) or u not in rows \
                    or not isinstance(e.get('targets'), list) or not e['targets']:
                continue                                       # a gated tag names no end; bad rows reported above
            n += 1
            own = _pvid(rows[u][0], rows[u][1] or 0)
            way = [_gm_steps(_ef, _ef._gm_id(own), _ef._gm_id(str(t))) for t in e['targets']]
            ends = all(not _ef.stage_evolves(str(t)) for t in e['targets'])   # per FORM (plain Linoone ends, 2026-10-25)
            lbl = '%s %s -> %s: tagged %s, the game %s' % (u, rows[u][0], '/'.join(map(str, e['targets'])),
                                                           'Final' if e['final'] else 'Mid',
                                                           'shows no way' if not all(way) else
                                                           'ends there' if ends else 'evolves it further')
            if not all(way):
                blind.append(lbl)
            elif e['final'] and not ends:
                past.append(lbl)
            elif not e['final'] and ends:
                short.append(lbl)
        if past:
            fail(BLOCK, '%d Evolve to Final copy/copies whose target the client game master evolves further: %s'
                        % (len(past), ' | '.join(past[:6])),
                 'The Tympole trap: "to Final" gets it evolved past its target -- irreversible. The end comes from '
                 "pvpoke's families (granular_tags.is_final); the game outranks pvpoke. Fix the family "
                 '(reconcile_gamemaster.py) or is_final and re-run build_tagsets.py.')
        if short or blind:
            fail(WARN, '%d Evolve to Mid / Final row(s) the client game master does not confirm: %s'
                       % (len(short) + len(blind), ' | '.join((short + blind)[:6])),
                 'A label must be true for the mon on screen. WARN: "to Mid" on a stage that ends the line only stops him '
                 'where he would stop anyway (nothing irreversible), and "shows no way" means the game master cannot say.')
        if not (past or short or blind):
            ok('the client game master confirms where all %d Evolve to Mid / Final row(s) end' % n)


def main():
    print('audit_invariants.py -- STRUCTURAL invariants of the keep engine (READ-ONLY)')
    print('root: %s' % ROOT)

    try:
        import keep_config as kc
        import costume_forms as cfm
    except Exception as e:
        print('*** cannot import keep_config/costume_forms: %s' % e)
        return 2
    if not kc.file_loaded():
        # This is a BLOCK by construction: the shipped DEFAULTS are a different policy, so every
        # cap comparison below would be against caps the user never chose.
        print('*** BLOCK  keep_config.json did not load (%s)' % kc.LOAD_ERROR)
        print('    DO: fix or restore keep_config.json. Until then every cap read here (and in '
              'keep_policy) is the shipped default, which is a DIFFERENT policy.')
        return 1
    if not os.path.exists(DB):
        print('*** pokemon.db not found at %s' % DB)
        return 2
    con = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)
    try:
        schema = {r[1] for r in con.execute('PRAGMA table_info(pokemon)')}
        # how many live keepers rest on each axis -- decides whether an UNAUDITED axis is a
        # latent gap (nothing depends on it yet) or a live one (real keepers with no coverage)
        try:
            _r = json.load(open(os.path.join(ANA, 'policy_reasons.json'), encoding='utf-8'))
            _cnt = defaultdict(int)
            for _rs in _r.values():
                if isinstance(_rs, list):
                    for _why in _rs:
                        _cnt[REASON_TO_AXIS.get(_why, _why)] += 1
            con_reason_count[0] = dict(_cnt)
        except Exception:
            con_reason_count[0] = {}
        check_axis_consistency(kc)
        check_staleness(con, kc, cfm)
        check_null_direction(con, schema)
        check_no_writer(con, schema, kc)
        check_partition(con)
        check_single_push_path()
        check_stat_line_fidelity(con)
        check_tag_vocabulary(con)        # I8 (2026-09-26; the fold 2026-09-29)
    finally:
        con.close()

    blocks = [f for f in _FINDINGS if f[0] == BLOCK]
    warns = [f for f in _FINDINGS if f[0] == WARN]
    print('\n' + '=' * 78)
    if not _FINDINGS:
        print('VERDICT: ALL STRUCTURAL INVARIANTS HOLD  (0 BLOCK, 0 WARN)')
        return 0
    for sev in (BLOCK, WARN):
        group = [f for f in _FINDINGS if f[0] == sev]
        if not group:
            continue
        print('\n%s -- %d finding(s)' % (sev, len(group)))
        for i, (_, sid, msg, do) in enumerate(group, 1):
            print('\n %d. [%s] %s' % (i, sid, msg))
            for line in _wrap('DO: ' + do, 74):
                print('    ' + line)
    print('\n' + '=' * 78)
    if blocks:
        print('VERDICT: %d STRUCTURAL INVARIANT(S) VIOLATED -- the pile is NOT safe to sync '
              '(%d BLOCK, %d WARN)' % (len(blocks), len(blocks), len(warns)))
        return 1
    print('VERDICT: ALL STRUCTURAL INVARIANTS HOLD  (0 BLOCK, %d WARN -- see above, each is a real '
          'issue held down by a guard this run verified is still present)' % len(warns))
    return 0


def _wrap(s, w):
    out, line = [], ''
    for word in s.split():
        if len(line) + len(word) + 1 > w:
            out.append(line)
            line = word
        else:
            line = (line + ' ' + word).strip()
    if line:
        out.append(line)
    return out


if __name__ == '__main__':
    sys.exit(main())
