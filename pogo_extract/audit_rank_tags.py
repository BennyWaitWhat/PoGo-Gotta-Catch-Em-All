"""PER-POKEMON AUDIT OF EVERY GL / UL RANK TAG (user 2026-09-19: "recheck all the ivs for each and every pokemon you
have tagged for gl and ul potential and current ... some are incorrect. some even over the cap").

For every mon carrying `GL/UL Rank 1-5` (own stage) or `GL/UL 1-5 No Evolve` (a later stage) this re-derives
the answer from scratch -- the ranker's own tables, the stage chain, the league caps -- and reports every mon where
the tag does not match. Five independent checks per mon:

  1. OVER THE CAP     -- its CURRENT CP already exceeds the league cap. CP only goes up, so it can never enter that
                         league. A rank tag on it is a promise it cannot keep.
  2. RANK MISMATCH    -- the rank recomputed from its IVs differs from the rank stored in the DB.
  3. TAG vs RANK      -- `Rank 1` on a mon whose own-stage rank is not 1, or `Rank 2-5` outside 2..5.
  4. STAGE            -- an OWN-stage tag whose stage cannot reach the league cap (viability), or an EVO tag whose
                         named stage the specimen cannot actually reach (form / gender / costume gates).
  5. UNRANKED         -- a tag on a mon the ranker cannot rank at all.

Read-only. Exit 1 if anything is off.
"""
import collections, json, os, sqlite3, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts')); sys.path.insert(0, ROOT)
import rank_cache
import evolvable_forms
import granular_tags as gt
from pvp_iv_rule import pvid, maxcp, GL_CAP, UL_CAP, VIABILITY_MARGIN

TAGS = {'GL Rank 1-5': ('gl', 1, 5, 'own'), 'UL Rank 1-5': ('ul', 1, 5, 'own'),          # merged 2026-09-23
        'GL 1-5 No Evolve': ('gl', 1, 5, 'evo'), 'UL 1-5 No Evolve': ('ul', 1, 5, 'evo')}   # was Evo GL/UL Rank 1-5 (2026-09-30)
CAP = {'gl': GL_CAP, 'ul': UL_CAP}


def main():
    with open('pvpoke_gamemaster.json', 'rb') as f:
        gm_bytes = f.read()
    gm = json.loads(gm_bytes)
    pdb = {p['speciesId']: p for p in gm['pokemon']}
    BS = {k: v.get('baseStats', {}) for k, v in pdb.items()}
    # INDEPENDENT TABLES (H02, 2026-09-29). This audit used to re-derive every rank through
    # RankTableCache(pdb, hash) -- the DEFAULT pkl_path, i.e. system/scripts/rank_tables.pkl, the very tables the pipeline
    # wrote the stored ranks from. A ranking-math change without a hand-bumped version string kept both on the old
    # tables and this audit said EVERY RANK TAG CHECKS OUT (measured: 0 of 150 disagreements under a changed stat
    # product, vs 144 with fresh tables). The per-tag checks now use tables built fresh in a throw-away path
    # (regress_pvp_keepers' pattern, ~10 ms a table), and a sample of the shared pickle is compared table-for-table.
    import tempfile, random
    _tmp = tempfile.mkdtemp(prefix='audit_rank_')
    cache = rank_cache.RankTableCache(pdb, rank_cache._content_hash(gm_bytes), pkl_path=os.path.join(_tmp, 'fresh.pkl'))
    shared = rank_cache.RankTableCache(pdb, rank_cache._content_hash(gm_bytes))        # the pipeline's own pickle
    _keys = [k for k, v in shared.tables.items() if v is not None]
    random.seed(len(_keys))
    stale_tables = [k for k in random.sample(_keys, min(200, len(_keys))) if cache.get(*k)[1] != shared.tables[k][1]]

    con = sqlite3.connect('file:pokemon.db?mode=ro', uri=True); con.row_factory = sqlite3.Row
    rows = {r['uid_hex']: __import__('keep_config').row_dict(r) for r in con.execute('SELECT * FROM pokemon WHERE in_bag=1')}
    con.close()
    TD = os.path.join('system', 'analysis', 'tagsets')
    members = {}
    for tag in TAGS:
        p = os.path.join(TD, tag.replace(' ', '_') + '.txt')
        members[tag] = [u for u in (open(p).read().split() if os.path.exists(p) else []) if u in rows]

    bad = collections.defaultdict(list)
    checked = 0
    for tag, (lg, lo, hi, kind) in TAGS.items():
        cap = CAP[lg]
        for u in members[tag]:
            r = rows[u]; checked += 1
            own = pvid(r['species_name'], r['form'] or 0)
            name = '%s %d/%d/%d cp%s' % (r['species_name'], r['iv_atk'], r['iv_def'], r['iv_sta'], r['cp'])
            # 1. already over the league cap -> it can never enter
            if (r['cp'] or 0) > cap:
                bad['over the %s cap (cp %d > %d) -- cannot enter that league' % (lg.upper(), r['cp'], cap)].append(
                    '%-26s [%s]' % (name, tag))
            # 2/3. recompute the rank from the IVs
            got = rank_cache.compute_rank_for_iv(cache, own, r['iv_atk'], r['iv_def'], r['iv_sta'], cap,
                                                 r['fresh_alignment'] == 1)
            stored = None
            for part in str(r[lg + '_chain_ranks'] or '').split(';'):
                if ':' in part and part.split(':')[0].strip() == own:
                    try:
                        stored = int(part.split(':')[1].split('(')[0])
                    except ValueError:
                        pass
            if got is None:
                if kind == 'own':
                    bad['the ranker cannot rank this stage at all'].append('%-26s [%s]' % (name, tag))
            else:
                if stored is not None and stored != got['rank']:
                    bad['stored rank disagrees with a fresh computation'].append(
                        '%-26s [%s] stored #%s, recomputed #%s' % (name, tag, stored, got['rank']))
                if kind == 'own' and not (lo <= got['rank'] <= hi):
                    bad['tag says rank %s-%s, its own stage is #%d' % (lo, hi, got['rank'])].append(
                        '%-26s [%s] as %s' % (name, tag, own))
            # 4. stage checks
            if kind == 'own':
                if not (own in BS and maxcp(own, BS) > cap + VIABILITY_MARGIN):
                    bad['own stage cannot reach the league cap'].append('%-26s [%s] %s' % (name, tag, own))
            else:
                if evolvable_forms.row_can_evolve(r) is False:
                    bad['an EVO tag on a form that cannot evolve'].append('%-26s [%s]' % (name, tag))
                else:
                    later = [k for k in gt.stage_ranks(r, lg) if k != own]
                    if not later:
                        bad['an EVO tag with no later stage in its chain'].append('%-26s [%s]' % (name, tag))
    # ---- AND EVERY RANK OF EVERY MON, tagged or not (user 2026-09-19: "i told you to check each pokemon for a
    # reason" -> "this is why i asked you to check PVP ranks"). The per-tag checks above only see mons that already
    # carry a chip, so a wrong rank on an untagged mon -- the one that would show up next cycle -- was invisible.
    # This re-derives all ~16.6k chain-stage ranks from the IVs and compares them with what the bag stores.
    n_stage = 0
    for r in rows.values():
        for lg, cap in (('gl', GL_CAP), ('ul', UL_CAP)):
            for part in str(r[lg + '_chain_ranks'] or '').split(';'):
                if ':' not in part:
                    continue
                sid = part.split(':')[0].strip()
                try:
                    stored = int(part.split(':')[1].split('(')[0])
                except ValueError:
                    continue
                n_stage += 1
                got = rank_cache.compute_rank_for_iv(shared, sid, r['iv_atk'], r['iv_def'], r['iv_sta'], cap,   # 4.7k tables: the sampled check above vouches for them
                                                     r['fresh_alignment'] == 1)
                if got is None:
                    bad['a stored stage the ranker cannot rank'].append('%s %s %s' % (r['species_name'], lg, sid))
                elif got['rank'] != stored:
                    bad['STORED RANK DISAGREES WITH A FRESH COMPUTATION (whole bag)'].append(
                        '%-22s %s %-22s stored #%d, fresh #%d' % (r['species_name'], lg.upper(), sid, stored,
                                                                  got['rank']))
    if stale_tables:
        bad['THE PIPELINE\'S PICKLED RANK TABLES DIFFER FROM A FRESH BUILD (ranking math changed without a cache '
            'invalidation -- every stored rank is suspect; delete system/scripts/rank_tables.pkl and recrawl)'].extend(
            '%s cap %s shadow %s' % k for k in stale_tables)
    if _keys:
        print('shared rank tables checked against a fresh build: %d sampled, %d differ' % (min(200, len(_keys)), len(stale_tables)))
    else:                                 # the pickle is keyed to other math / game master: nothing shared was loaded
        print('shared rank tables: none built for this math + game master yet (the next recrawl rebuilds them) -- every '
              'rank below was re-derived from fresh tables')
    print('whole-bag chain-stage ranks re-derived: %d across %d mons' % (n_stage, len(rows)))
    print('rank-tag members checked: %d across %d tags' % (checked, len(TAGS)))
    for tag in sorted(TAGS):
        print('   %-18s %d' % (tag, len(members[tag])))
    print()
    if not bad:
        print('VERDICT: EVERY RANK TAG CHECKS OUT')
        return 0
    for k in sorted(bad, key=lambda k: -len(bad[k])):
        print('*** %s: %d' % (k, len(bad[k])))
        for line in sorted(bad[k])[:40]:
            print('      ' + line)
    print('\nVERDICT: %d rank-tag problem(s)' % sum(len(v) for v in bad.values()))
    return 1


if __name__ == '__main__':
    sys.exit(main())
