"""check_constant_drift.py -- GUARD: every game constant has exactly ONE definition.

WHY THIS EXISTS (defect D4, 2026-09-07)
---------------------------------------
The level-50 CP multiplier existed as two different values for one number --
rank_cache.py's CPM[98] said 0.84029995 while pvp_iv_rule.py's CPM50 said 0.84029999 --
plus five more copies, two of which were REGEX SCRAPES of another file's source text.
Neither literal was the value the game actually stores (float32(0.8403)). That constant
feeds the PvP stat-product ranks, the ranks feed the rank<=5 keep gate, and that gate
decides the ONE irreversible output: the Transfer pile a human then releases by hand.

A drift like that is invisible: both files parse, both run, both produce plausible ranks.
The only thing that catches it is a check that asserts there is ONE definition. Two
literals that merely happen to match are NOT a single source of truth -- the next person
to "correct" one of them silently re-splits the brain.

WHAT IT CHECKS
--------------
  RUNTIME : import each live consumer and assert the constant it exposes IS the canonical
            one from cpm_table.py. Catches drift that only appears once modules load.
  SOURCE  : AST-scan the live engine files for a RE-HARDCODED CPM ladder, L50/L51
            multiplier, league CP cap, or level-cap index (MAX_LEVEL_IDX). Catches a
            literal pasted back in before it can ever diverge, and catches the
            source-scrape antipattern returning.

            This scan is a set of NAMED rules, not a proof of full coverage: it knows the
            four shapes below. A game constant in a shape none of them models is NOT
            covered, and the clean verdict does not claim otherwise.

Read-only. No device contact, no DB writes. ~2s.
Exit 0 and print "ALL GAME CONSTANTS SINGLE-SOURCED" when clean, else exit 1.

NOTE ON compute_all_ranks.py: it is scanned by AST but deliberately NOT imported -- it has
no `if __name__ == '__main__'` guard, so importing it RE-RANKS THE WHOLE BAG and writes
pokemon.db as a side effect of the import.
"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import cpm_table  # the single source of truth

CANON = os.path.join(ROOT, 'cpm_table.py')

# Files the live pipeline actually runs. A re-hardcoded constant in one of these is a
# BLOCKING failure. Everything else in the tree is reported as INFO (historical one-shot
# scripts keep their own frozen copies; they do not decide today's pile).
LIVE = [
    'system/scripts/rank_cache.py',       # the ranker pogo_pipeline runs
    'compute_all_ranks.py',               # its fallback ranker
    'pvp_iv_rule.py',                     # the GL/UL keep rule + viability gate
    'system/scripts/keep_policy.py',      # builds the pile
    'system/scripts/build_tagsets.py',    # writes the tagset files
    'system/scripts/preflight_transfer.py',  # pre-flights the irreversible pile
    'granular_tags.py',                   # the 23-tag scheme
    'audit_cull.py',                      # the 8-layer cull audit
    'cull_v9.py',                         # advisory, but pogo_pipeline imports and RUNS it in-process
]

# KNOWN OUTSTANDING -- a real live duplicate that is NOT yet collapsed, listed by name so it
# is printed on EVERY run instead of quietly allowlisted. Reported as WARN (does not fail the
# guard) purely because it was owned by another agent editing in parallel when this landed.
# Collapse it and delete the entry.
PENDING = {
    'pogo_pipeline.py': (
        'CPM_TABLE (~line 275) re-hardcodes the whole ladder as (cpm, level) pairs for '
        'cpm_to_level(). It is the REVERSE lookup that derives the `level` column, matched '
        'with a 1e-6 tolerance, so it is insensitive to the L50 correction -- but it is still '
        'a second copy of the ladder that can drift from the ranker\'s. '
        'FIX: `from cpm_table import CPM, level_for_index` then '
        '`CPM_TABLE = [(v, level_for_index(i)) for i, v in enumerate(CPM)]`.'),
}

# Modules that are SAFE to import (no side effects at module scope) and the canonical
# attribute each must agree with.
RUNTIME = [
    ('pvp_iv_rule', {'CPM50': 'CPM50', 'GL_CAP': 'GL_CAP', 'UL_CAP': 'UL_CAP'}),
    ('rank_cache', {'MAX_LEVEL_IDX': 'MAX_LEVEL_IDX', 'GL_CAP': 'GL_CAP', 'UL_CAP': 'UL_CAP'}),
    ('build_tagsets', {'CPM50': 'CPM50'}),
    ('granular_tags', {'GL_CAP': 'GL_CAP', 'UL_CAP': 'UL_CAP'}),
]

CAP_VALUES = {500, 1500, 2500}

# Rule (2b): the LEVEL-LADDER constants that live in cpm_table.py -- MAX_LEVEL_IDX (the
# highest rung the ranker evaluates), LEVEL_50_IDX, LEVEL_51_IDX. Matched on BOTH the name
# (case-folded substring) and the value, because a re-hardcoded `MAX_LEVEL_IDX = 98` is an
# int whose name holds neither 'CPM' nor a trailing '_CAP' -- it slips past every other rule
# in this file. Values: 98/100 are the TABLE INDICES, 50/51 the levels they stand for.
LEVEL_NAME_RE = re.compile(r'MAX_LEVEL|MAX_LEVEL_IDX|LEVEL_CAP|LEVEL_50|LEVEL_51|MAXIDX')
LEVEL_IDX_VALUES = {50, 51, 98, 100}

FAILURES = []
INFO = []


def fail(msg, why):
    FAILURES.append((msg, why))
    print('   *** DRIFT  %s' % msg)
    print('              -> %s' % why)


def ok(msg):
    print('   ok        %s' % msg)


# --------------------------------------------------------------------------------------
def _floats(node):
    """The float constants in a list/tuple literal, or None if it is not one.

    Handles BOTH ladder shapes: a flat list of multipliers (the ranker's CPM) and a list of
    (cpm, level) PAIRS (pogo_pipeline/build_db's reverse cpm_to_level table). The pair form
    was a blind spot -- a scanner that only understood flat lists reported "clean" on a file
    holding a complete second copy of the ladder.
    """
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    out = []
    for e in node.elts:
        if isinstance(e, ast.Constant) and isinstance(e.value, (int, float)) and not isinstance(e.value, bool):
            out.append(float(e.value))
        elif isinstance(e, ast.Tuple) and e.elts and isinstance(e.elts[0], ast.Constant) \
                and isinstance(e.elts[0].value, (int, float)) and not isinstance(e.elts[0].value, bool):
            out.append(float(e.elts[0].value))   # (cpm, level) pair -> take the multiplier
        else:
            return None
    return out


def scan_source(rel):
    """Report re-hardcoded CPM ladders / L50 multipliers / league caps / level-cap
    indices in one file. Four named rules -- see the module docstring: this is coverage of
    known shapes, not a proof that no constant is duplicated."""
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        INFO.append('%s: not found (skipped)' % rel)
        return []
    try:
        tree = ast.parse(open(path, encoding='utf-8').read())
    except SyntaxError as e:
        return [('%s does not parse (%s)' % (rel, e), 'A guard cannot clear a file it cannot read.')]

    hits = []
    for node in ast.walk(tree):
        # (1) a CPM ladder pasted back in: a long run of float literals in the CPM range
        vals = _floats(node)
        if vals and len(vals) >= 20 and all(0.09 <= v <= 0.90 for v in vals):
            hits.append(('%s re-hardcodes a %d-entry CPM ladder' % (rel, len(vals)),
                         'Import it: `from cpm_table import CPM` (or cpm_list() for a mutable copy).'))
        # (2) NAME = <float literal> where NAME looks like a CP multiplier
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, float):
            for tg in node.targets:
                if isinstance(tg, ast.Name) and 'CPM' in tg.id.upper():
                    hits.append(('%s hardcodes %s = %r' % (rel, tg.id, node.value.value),
                                 'Import it: `from cpm_table import CPM50`.'))
        # (2b) NAME = <int literal> where NAME is a LEVEL-LADDER constant. This is the hole
        #      the other three rules leave open: `MAX_LEVEL_IDX = 98` is an int (rule 1 wants
        #      a >=20-entry float list, rule 2 wants a float), its name holds no 'CPM'
        #      (rule 2) and does not end in '_CAP' (rule 3) -- and even `LEVEL_CAP = 50` gets
        #      past rule 3, whose CAP_VALUES are the league caps {500,1500,2500}, not 50. So a
        #      re-hardcoded level cap scanned CLEAN while the guard printed its all-good
        #      verdict. It matters because MAX_LEVEL_IDX is the highest rung the ranker
        #      evaluates: drift in it moves EVERY rank, and the ranks feed the rank<=5 gate
        #      that decides the irreversible Transfer pile.
        #      SCOPE: the plain `NAME = <int>` form only. A tuple unpack
        #      (`LEVEL_50_IDX, LEVEL_51_IDX = 98, 100`) or an annotated assignment
        #      (`MAX_LEVEL_IDX: int = 98`) is NOT caught -- said out loud rather than implied
        #      away, because a guard that overstates its reach is how D4 survived.
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, int) \
                and node.value.value in LEVEL_IDX_VALUES:
            for tg in node.targets:
                if isinstance(tg, ast.Name) and LEVEL_NAME_RE.search(tg.id.upper()):
                    hits.append(('%s hardcodes %s = %r' % (rel, tg.id, node.value.value),
                                 'Import it: `from cpm_table import MAX_LEVEL_IDX`. '
                                 '(cpm_table.py owns MAX_LEVEL_IDX / LEVEL_50_IDX / '
                                 'LEVEL_51_IDX -- import the one you need, never re-type '
                                 'it; level 50.0 is level_for_index(MAX_LEVEL_IDX).)'))
        # (3) league CP caps as literals in an assignment
        if isinstance(node, ast.Assign):
            names = [tg.id for tg in node.targets if isinstance(tg, ast.Name)]
            names += [e.id for tg in node.targets if isinstance(tg, ast.Tuple)
                      for e in tg.elts if isinstance(e, ast.Name)]
            if any(n.endswith('_CAP') for n in names):
                lits = []
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
                    lits = [node.value.value]
                elif isinstance(node.value, ast.Tuple):
                    lits = [e.value for e in node.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, int)]
                if any(v in CAP_VALUES for v in lits):
                    hits.append(('%s hardcodes a league CP cap (%s = %s)'
                                 % (rel, '/'.join(names), lits),
                                 'Import it: `from cpm_table import GL_CAP, UL_CAP, LL_CAP`.'))
        # (4) the source-scrape antipattern returning
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ('search', 'findall') and node.args:
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str) and 'CPM' in a0.value:
                hits.append(('%s REGEX-SCRAPES a CPM literal out of source text' % rel,
                             'Import it from cpm_table instead; a scrape breaks silently when the '
                             'literal it reads moves or becomes an import.'))
    return hits


def main():
    print('=' * 78)
    print('CONSTANT-DRIFT GUARD -- one definition per game constant (defect D4)')
    print('=' * 78)
    print('\ncanonical: cpm_table.py  CPM50=%r  caps=%s  MAX_LEVEL_IDX=%d'
          % (cpm_table.CPM50, cpm_table.LEAGUE_CAPS, cpm_table.MAX_LEVEL_IDX))

    print('\n[1] RUNTIME -- every consumer exposes the canonical value')
    for modname, attrs in RUNTIME:
        try:
            mod = __import__(modname)
        except Exception as e:
            fail('cannot import %s (%s)' % (modname, e),
                 'A consumer that will not load cannot be proven to share the constant.')
            continue
        for attr, canon_attr in attrs.items():
            want = getattr(cpm_table, canon_attr)
            got = getattr(mod, attr, '<missing>')
            if got == want:
                ok('%s.%s == cpm_table.%s (%r)' % (modname, attr, canon_attr, want))
            else:
                fail('%s.%s = %r but cpm_table.%s = %r' % (modname, attr, got, canon_attr, want),
                     'One number, two values -- this is defect D4 exactly. Make %s import it.' % modname)

    # rank_cache holds a mutable COPY of the ladder; it must still match element-wise.
    try:
        import rank_cache as _rk
        if list(_rk.CPM) == list(cpm_table.CPM):
            ok('rank_cache.CPM is element-wise identical to the canonical ladder')
        else:
            fail('rank_cache.CPM differs from cpm_table.CPM',
                 'The ranker is not using the canonical ladder; every rank it writes is suspect.')
        if _rk.CPM is cpm_table.CPM:
            fail('rank_cache.CPM IS the canonical tuple object',
                 'Consumers that patch their own CPM (regress_pvp_keepers.py does) would corrupt '
                 'the canonical table for the whole process. Use cpm_table.cpm_list().')
        else:
            ok('rank_cache.CPM is a private copy -- a consumer cannot corrupt the canonical table')
    except Exception as e:
        fail('cannot verify rank_cache.CPM (%s)' % e, 'The live ranker must be checkable.')

    print('\n[2] SOURCE -- no live engine file re-hardcodes a constant')
    for rel in LIVE:
        hits = scan_source(rel)
        if not hits:
            ok('%s: no re-hardcoded CPM ladder / L50-L51 multiplier / league CP cap / '
               'level-cap index, and no CPM source-scrape' % rel)
        for msg, why in hits:
            fail(msg, why)

    print('\n[3] KNOWN OUTSTANDING duplicates (reported every run, not allowlisted away)')
    if not PENDING:
        ok('none')
    for rel, why in sorted(PENDING.items()):
        hits = scan_source(rel)
        if hits:
            print('   !! WARN     %s' % rel)
            print('              -> %s' % why)
        else:
            fail('%s is listed in PENDING but no longer duplicates anything' % rel,
                 'It was fixed -- delete its PENDING entry so this guard stays honest.')

    print('\n[4] canonical file sanity')
    if not os.path.exists(CANON):
        fail('cpm_table.py is MISSING', 'Every consumer imports it; without it nothing ranks.')
    else:
        ok('cpm_table.py present and its import-time self-checks passed')

    print('\n' + '=' * 78)
    if FAILURES:
        print('VERDICT: %d CONSTANT-DRIFT FAILURE(S) -- a game constant has more than one '
              'definition' % len(FAILURES))
        print('=' * 78)
        return 1
    print('VERDICT: ALL GAME CONSTANTS SINGLE-SOURCED')
    print('=' * 78)
    return 0


if __name__ == '__main__':
    sys.exit(main())
