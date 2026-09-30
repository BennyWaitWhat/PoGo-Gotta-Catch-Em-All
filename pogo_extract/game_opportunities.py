"""Collection opportunities the GAME MASTER makes visible (user 2026-09-17: "Learn more about what the game has for info
and be comprehensive. There's way to improve."). Advice only -- nothing here tags, keeps or culls a mon.

  purify_to_hundo()   a SURPLUS shadow with every IV >= 13 purifies into 15/15/15 (+2 per IV, capped at 15), at a
                      stage with no hundo of any kind yet. Never a shadow the collection keeps for its own sake (best
                      shadow of the stage, last copy, PvP piece, collectible) and never a shadow hundo.
  second_moves()      a mon ranked 1-N (keep_config pvp.action_rank) at its OWN stage in a league that stage can actually enter (the same viability
                      test the keep rule uses) that has no second charged move -- the game master's thirdMove price.

Both read the bag DB read-only, the client game master, and the walk's candy/stardust (candy.json / inventory.json).
"""
import json, os, re, sqlite3

import evolvable_forms
import keep_config
from pvp_iv_rule import pvid, maxcp, GL_CAP, UL_CAP, VIABILITY_MARGIN

HERE = os.path.dirname(os.path.abspath(__file__))
_PRICES = None


def _prices():
    """{dex: {'purify': (dust, candy), 'third': (dust, candy)}} from pokemonSettings.shadow / .thirdMove."""
    global _PRICES
    if _PRICES is None:
        _PRICES = {}
        for t in json.load(open(os.path.join(HERE, 'gamemaster_pokeminers.json'), encoding='utf-8')):
            s = (t.get('data') or {}).get('pokemonSettings')
            m = re.match(r'V(\d{4})_POKEMON_', t.get('templateId', ''))
            if not s or not m:
                continue
            d = _PRICES.setdefault(int(m.group(1)), {})
            sh = s.get('shadow') or {}
            if sh.get('purificationStardustNeeded') and 'purify' not in d:
                d['purify'] = (int(sh['purificationStardustNeeded']), int(sh.get('purificationCandyNeeded') or 0))
            tm = s.get('thirdMove') or {}
            if tm.get('stardustToUnlock') and 'third' not in d:
                d['third'] = (int(tm['stardustToUnlock']), int(tm.get('candyToUnlock') or 0))
    return _PRICES


def _stardust():
    """This walk's stardust; if that read failed, the last good read (advice may lean on a day-old balance, never on
    a false 0); None when neither exists."""
    try:
        d = json.load(open(os.path.join(HERE, 'system', 'analysis', 'inventory.json'), encoding='utf-8'))
    except Exception:
        return None
    if isinstance(d.get('stardust'), int) and d['stardust'] > 0:
        return d['stardust']
    return (d.get('currency_last_good') or {}).get('stardust')


def _walk_of(rows):
    """The walk these rows came from (MAX last_scanned). candy.json is judged against IT, never against the wall clock
    (2026-09-29, H04): candy_now() with no walk fell back to a 2 h clock, so a page or report made 2 h after the walk
    read no candy at all and called every upgrade 'short' on an unchanged bag."""
    out = None
    for r in rows:
        try:
            v = r['last_scanned']
        except (KeyError, IndexError, TypeError):
            v = None
        if v and (out is None or str(v) > out):
            out = str(v)
    return out


def _affordable(d, c, fam, dust, candy):
    """True / False when this walk's balances are known; None when the stardust or the candy was not read (UNKNOWN is
    never shown as 'short' -- the same rule inventory.json follows for an unread balance, 2026-09-19)."""
    if d is None:
        return False                                   # no price in the game master: nothing to afford
    if dust is None or (candy is None and (c or 0) > 0):
        return None
    return dust >= d and (candy or {}).get(fam, 0) >= (c or 0)


def _rows():
    c = sqlite3.connect('file:%s?mode=ro' % os.path.join(HERE, 'pokemon.db').replace('\\', '/'), uri=True)
    c.row_factory = sqlite3.Row
    try:
        return [__import__('keep_config').row_dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1')]
    finally:
        c.close()


# A shadow kept for any of these reasons is valuable AS A SHADOW (or as the copy it is); purifying would destroy that.
_KEEP_AS_IS = {'shadow_best', 'dex_only_copy', 'legacy', 'gl_iv', 'ul_iv', 'pvp_rank', 'pvp_spread', 'rank_unknown',
               'location_card', 'variant_floor', 'xxl', 'mighty', 'protected', 'favorite', 'adventure_effect', 'origin',
               'rarity', 'hundo', 'nundo', 'shiny', 'shiny_ladder'}
PVP_WORTH = 100          # a shadow ranked this well at a stage that reaches the league cap is a PvP piece -- leave it


def purify_to_hundo(rows=None):
    """SURPLUS shadows whose purified IVs are 15/15/15, at a stage that has no hundo of any kind yet.

    Never suggested (2026-09-17, "hundo shadows are really nice ... check pvp ivs ... dont be stupid"):
      * a shadow the keep rules hold for its own sake -- the stage's best shadow (by IV, GL or UL), the last copy of its
        form, a legacy mover, a PvP keeper, a collectible (_KEEP_AS_IS);
      * a shadow ranked 1-100 in a league its stage can enter (shadow-corrected ranks from the ranker);
      * a stage that already holds a hundo -- plain, purified OR shadow (a shadow hundo counts: you have that hundo).
    What is left is a shadow the cull would otherwise let go, turned into a new hundo for the price in the game master.
    """
    rows = rows if rows is not None else _rows()
    try:
        why = {u: set(v) for u, v in json.load(open(os.path.join(HERE, 'system', 'analysis', 'policy_reasons.json'),
                                                    encoding='utf-8')).items() if not u.startswith('_')}
    except Exception:
        return []                                      # no keep reasons -> cannot tell surplus from keeper: say nothing
    gm = json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))
    BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
    # BY STAGE, AND A STAGE IS A (speciesId, FORM) (2026-09-20). pvpoke calls all 28 Unown letters 'unown' and
    # all 5 Florges colours 'florges', so a hundo Unown-A used to answer for Unown-Z and silence the advice.
    _stg = lambda r: evolvable_forms.stage_of(pvid(r['species_name'], r['form'] or 0), r['form'] or 0)
    hundo_at = {_stg(r) for r in rows if (r['iv_total'] or 0) == 45}
    candy, dust = evolvable_forms.candy_now(walk=_walk_of(rows)), _stardust()     # the walk's candy; None = unread (H04)
    out = []
    for r in rows:
        if r['fresh_alignment'] != 1 or (r['iv_total'] or 0) == 45:
            continue                                   # not a shadow, or already a shadow HUNDO (a trophy as it is)
        if min(r['iv_atk'] or 0, r['iv_def'] or 0, r['iv_sta'] or 0) < 13:
            continue
        stage = _stg(r)
        if stage in hundo_at:
            continue                                   # you already have a hundo of this stage (any alignment)
        if why.get(r['uid_hex'], set()) & _KEEP_AS_IS:
            continue                                   # the collection keeps this shadow for what it is
        good_pvp = False
        for lg, cap in (('gl', GL_CAP), ('ul', UL_CAP)):
            st, rk = r[lg + '_stage'], r[lg + '_rank']
            if rk is not None and rk <= PVP_WORTH and st in BS and maxcp(st, BS) > cap + VIABILITY_MARGIN:
                good_pvp = True
        if good_pvp:
            continue                                   # a good PvP shadow: purifying raises attack and ruins the spread
        d, c = _prices().get(r['pokemon_id'], {}).get('purify', (None, None))
        fam = evolvable_forms.family(stage[0])         # stage = (speciesId, form); family() takes the speciesId (R-B
        #                                                 review: the tuple raised AttributeError on the first real candidate)
        out.append({'uid': r['uid_hex'], 'species': r['species_name'], 'ivs': (r['iv_atk'], r['iv_def'], r['iv_sta']),
                    'dust': d, 'candy': c, 'affordable': _affordable(d, c, fam, dust, candy)})
    return sorted(out, key=lambda x: (not x['affordable'], x['dust'] or 0))


def second_moves(rows=None):
    rows = rows if rows is not None else _rows()
    gm = json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))
    BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
    candy, dust = evolvable_forms.candy_now(walk=_walk_of(rows)), _stardust()     # the walk's candy; None = unread (H04)
    out = []
    for r in rows:
        if r['move3']:
            continue
        own = pvid(r['species_name'], r['form'] or 0)
        best = None
        for lg, cap, name in (('gl', GL_CAP, 'Great'), ('ul', UL_CAP, 'Ultra')):
            rk = r[lg + '_rank']
            if (r[lg + '_stage'] == own and rk is not None and rk <= keep_config.pvp('action_rank') and own in BS and maxcp(own, BS) > cap + VIABILITY_MARGIN   # rank 1-N (2026-09-29)
                    and (r['cp'] or 0) <= cap):   # a league it can ENTER (2026-09-26: a CP 2494 Gardevoir was 'GL #1')
                if best is None or rk < best[1]:
                    best = (name, rk)
        if not best:
            continue
        d, c = _prices().get(r['pokemon_id'], {}).get('third', (None, None))
        fam = evolvable_forms.family(own)
        out.append({'uid': r['uid_hex'], 'species': r['species_name'], 'league': best[0], 'rank': best[1],
                    'dust': d, 'candy': c, 'affordable': _affordable(d, c, fam, dust, candy)})
    return sorted(out, key=lambda x: (x['rank'], not x['affordable'], x['dust'] or 0))


if __name__ == '__main__':
    p = purify_to_hundo()
    print('purify into a hundo (stage has none yet): %d' % len(p))
    for x in p[:8]:
        print('   %-12s %2d/%2d/%2d  %s dust + %s candy%s' % (x['species'], *x['ivs'], format(x['dust'] or 0, ','),
              x['candy'], '' if x['affordable'] else ('  (balance not read this walk)' if x['affordable'] is None else '  (not affordable now)')))
    s = second_moves()
    print('rank 1-N at their own stage, no second charged move: %d (rank 1: %d)' % (len(s), sum(1 for x in s if x['rank'] == 1)))
    for x in s[:8]:
        print('   %-12s %s #%d  %s dust + %s candy%s' % (x['species'], x['league'], x['rank'], format(x['dust'] or 0, ','),
              x['candy'], '' if x['affordable'] else ('  (balance not read this walk)' if x['affordable'] is None else '  (not affordable now)')))
