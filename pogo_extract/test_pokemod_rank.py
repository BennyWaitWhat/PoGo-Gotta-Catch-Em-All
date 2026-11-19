"""Pokemod's rank numbering (rules.pokemod_rank_numbering): the math, the switch, and that OFF changes nothing.

No phone, no data: base stats are written out here. Run: python pogo_extract/test_pokemod_rank.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'system', 'scripts'))
import keep_config
import pokemod_rank as pm
import rank_cache as rc

BS = {'tinkatink': (85, 110, 137), 'tinkatuff': (109, 145, 163), 'tinkaton': (155, 196, 198), 'raichu': (193, 151, 155)}
LL, GL, UL, ML = rc.LL_CAP, rc.GL_CAP, rc.UL_CAP, rc.ML_CAP
assert (LL, GL, UL) == (500, 1500, 2500), (LL, GL, UL)

# ---- 1. the line Pokemod printed on his screen, 2026-09-08: a 13/15/15 Tinkatink ----------------------------------------
IDX = (13 << 8) | (15 << 4) | 15
WANT = {('tinkatink', LL): (2500, 91.25), ('tinkatink', GL): (13, 98.00), ('tinkatink', UL): (13, 98.00),
        ('tinkatuff', GL): (11, 98.39), ('tinkatuff', UL): (11, 98.39),
        ('tinkaton', GL): (1568, 95.53), ('tinkaton', UL): (1, 100.00)}
for (st, cap), want in WANT.items():
    sps = pm.products(*BS[st], cap)
    srt = sorted(sps, reverse=True)
    got = (pm.rank(sps, srt, IDX), pm.pct(sps[IDX], srt[0]))
    assert got == want, 'the 09-08 screen line: %s @%d is %r, Pokemod printed %r' % (st, cap, got, want)

# ---- 2. the numbering: every spread its own number; a tied spread after the tied spreads with a lower IV index ----------
for st in BS:
    for cap in (LL, GL, UL):
        sps = pm.products(*BS[st], cap)
        srt = sorted(sps, reverse=True)
        ranks = [pm.rank(sps, srt, i) for i in range(0, 4096, 7)] + [pm.rank(sps, srt, 4095)]
        order = sorted(range(4096), key=lambda i: -sps[i])              # Python's sort is stable: Pokemod's own order
        place = {i: k + 1 for k, i in enumerate(order)}
        assert ranks == [place[i] for i in range(0, 4096, 7)] + [place[4095]], st
        assert len(set(sps)) < 4096, '%s @%d: a table with no tied products proves nothing about ties' % (st, cap)
# the hundo is the LAST of its tie group: a 15/15/14 that ties it is numbered first
sps = pm.products(*BS['tinkatink'], GL)
srt = sorted(sps, reverse=True)
tied = [i for i in range(4096) if sps[i] == sps[4095]]
assert pm.rank(sps, srt, 4095) == 1 + sum(1 for v in sps if v > sps[4095]) + len(tied) - 1
# a spread over the cap at level 1 has no number (no real species does this at 500 CP and up)
assert pm.products(400, 400, 400, 10) is None

# ---- 3. the percent is the one Pokemod shows: an exact half goes UP (Python's own formatting would say .12) -------------
assert pm.pct(0.98125, 1.0) == 98.13 and '%.2f' % 98.125 == '98.12'
assert pm.pct(1.0, 1.0) == 100.0 and pm.pct(0.9124951, 1.0) == 91.25 and pm.pct(0.9124949, 1.0) == 91.25
assert pm.pct(0.912444, 1.0) == 91.24

# ---- 4. the level tables are Pokemod's: cpm, and cpm^2 / cpm^4 made from it the way its literals were -------------------
assert len(pm.JU) == 101 and pm.JU[0] == 0.094 and pm.JU[1] == 0.1351374318 and pm.JU[98] == 0.8403
assert all(a < b for a, b in zip(pm.JU, pm.JU[1:])) and pm.ZU[1] == 0.018262125473499653 and pm.U4[1] == 0.00033350522680984494

# ---- 5. the ranker: OFF = its own numbers, untouched; ON = Pokemod's for the three leagues it prints ---------------------
assert keep_config.DEFAULTS['rules']['pokemod_rank_numbering'] is False
_cfg = keep_config.CFG


def mode(on):
    keep_config.CFG = dict(_cfg, rules=dict(_cfg.get('rules') or {}, pokemod_rank_numbering=on))


try:
    mode(False)
    assert rc.numbering_mode() == 'native'
    h_native = rc._content_hash(b'gm')
    assert h_native == rc._content_hash(b'gm', 'native')
    mode(True)
    assert rc.numbering_mode() == 'pokemod'
    h_pm = rc._content_hash(b'gm')
    assert h_pm == rc._content_hash(b'gm', 'pokemod') != h_native, 'two numberings must never share one table file'
    assert rc._content_hash(b'gm', 'native') == h_native, "the native key must not depend on the switch"
finally:
    keep_config.CFG = _cfg

DB = {st: {'speciesId': st, 'baseStats': {'atk': a, 'def': d, 'hp': h}} for st, (a, d, h) in BS.items()}
missing = os.path.join(HERE, 'no_such_dir', 'x.pkl')                     # no file: the cache stays in memory
nat = rc.RankTableCache(DB, 'n', pkl_path=missing, numbering='native')
pok = rc.RankTableCache(DB, 'p', pkl_path=missing, numbering='pokemod')
for st in BS:
    a, d, h = BS[st]
    for cap in (LL, GL, UL, ML):
        for shadow in (False, True):
            assert nat.get(st, cap, shadow)[:2] == rc.all_combos_sorted(a, d, h, cap, shadow), 'native tables are the old ones'
            assert rc.build_table(a, d, h, cap, shadow) == rc.all_combos_sorted(a, d, h, cap, shadow)
    assert pok.get(st, ML, False)[:2] == rc.all_combos_sorted(a, d, h, ML, False), 'Master League stays native'
    assert pok.get(st, GL, True)[0] == pok.get(st, GL, False)[0] == pm.products(a, d, h, GL), 'a shadow has its normal form numbers'
for (st, cap), want in WANT.items():
    r = rc.compute_rank_for_iv(pok, st, 13, 15, 15, cap, False)
    assert (r['rank'], r['pct']) == want, (st, cap, r)
# native: the leftmost place, shared by a tie group -- exactly what it returned before this switch existed
for st in BS:
    sps, srt, _bs = nat.get(st, GL, False)
    for i in (0, 1234, 3855, 4095):
        r = rc.compute_rank_for_iv(nat, st, i >> 8, (i >> 4) & 15, i & 15, GL, False)
        assert r['rank'] == srt.index(sps[i]) + 1 and r['pct'] == sps[i] / srt[0] * 100, (st, i, r)
# Pokemod never gives two spreads one number; the native numbering does
p_ranks = {rc.compute_rank_for_iv(pok, 'raichu', i >> 8, (i >> 4) & 15, i & 15, UL, False)['rank'] for i in range(4096)}
n_ranks = {rc.compute_rank_for_iv(nat, 'raichu', i >> 8, (i >> 4) & 15, i & 15, UL, False)['rank'] for i in range(4096)}
assert p_ranks == set(range(1, 4097)) and len(n_ranks) < 4096
# an unknown mode on a cache object without the attribute is native (older pickled callers)
assert rc.compute_rank_for_iv(type('C', (), {'get': nat.get})(), 'raichu', 15, 15, 15, UL, False)['rank'] == \
    rc.compute_rank_for_iv(nat, 'raichu', 15, 15, 15, UL, False)['rank']
# the worker-side builder carries the mode
assert rc._table((193, 151, 155, UL, False, 'pokemod'))[0] == pm.products(193, 151, 155, UL)
assert rc._table((193, 151, 155, UL, False, 'native')) == rc.all_combos_sorted(193, 151, 155, UL, False)
print('test_pokemod_rank OK')
