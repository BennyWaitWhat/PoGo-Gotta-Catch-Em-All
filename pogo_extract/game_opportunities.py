"""Collection opportunities the GAME MASTER makes visible (user 2026-09-17: "Learn more about what the game has for info
and be comprehensive. There's way to improve."). Advice only -- nothing here tags, keeps or culls a mon.

  purify_to_hundo()   a SURPLUS shadow with every IV >= 13 purifies into 15/15/15 (+2 per IV, capped at 15), at a
                      stage with no hundo of any kind yet. Never a shadow the collection keeps for its own sake (best
                      shadow of the stage, last copy, PvP piece, collectible) and never a shadow hundo.
  second_moves()      a mon ranked 1-N (keep_config pvp.action_rank) at its OWN stage in a league that stage can actually enter (the same viability
                      test the keep rule uses) that has no second charged move -- the game master's thirdMove price (x1.2 for a shadow,
                      x0.8 for a purified mon: SHARED_MOVE_SETTINGS; third_price()).
  power_up_cost()     what the game charges to power a mon up from one level to another: stardust, candy (to L39.5) and XL candy (from
                      L40), read from the game master's POKEMON_UPGRADE_SETTINGS at call time, with the shadow / purified / lucky
                      multipliers and the per-species override (Eternatus). THE one price: deep_profile and the cull report use it.
  power_up_plan()     the same prices for the mons the Power Up tags hold, against this walk's stardust / candy / XL candy: 'doable now',
                      'doable after exchanging N candy into XL' or 'short X' (Benny 2026-09-30: "yes" to exact Power Up costs).
                      REPORT ONLY: no keep reason, no tag and no pile decision reads it.

All read the bag DB read-only, the client game master, and the walk's candy/stardust (candy.json / inventory.json).
  python game_opportunities.py             print what is on offer today
  python game_opportunities.py --selftest  offline (CI has no game master): golden prices hand-checked against the tables
Any other argument prints this usage and exits 2.
"""
import json, math, os, re, sqlite3, sys

import evolvable_forms
import keep_config
from pvp_iv_rule import pvid, maxcp, GL_CAP, UL_CAP, VIABILITY_MARGIN

HERE = os.path.dirname(os.path.abspath(__file__))
_GM = None                                              # the game master's prices, parsed once per process (see _gm)
_READ = object()                                        # power_up_plan: "read this balance from the walk" (None = was not read)
_norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x or '').upper())


def _up(v, m):
    """A price after a game-master multiplier, rounded UP. The game master gives the multipliers (shadow 1.2, purified 0.9 and 0.8,
    lucky 0.5), not the rounding; up is the safe side -- a 'doable now' never rests on a price rounded down, and the in-game
    screen wins where it differs. The 1e-9 keeps float noise (50 * 1.1 = 55.00000000000001) from costing a whole candy; today's tables
    and multipliers (1.2, 0.9, 0.8, 0.5) never hit it -- a future multiplier might."""
    return int(math.ceil(v * m - 1e-9))


def _parse(templates):
    """The prices this module quotes, from the client game master's templates (a list of {'templateId', 'data'}), in ONE pass
    (the file is 19 MB: it is parsed once per process, never once per question):
      prices    {dex: {'purify': (dust, candy), 'third': (dust, candy), 'third_shadow': ..., 'third_purified': ...}} -- pokemonSettings.shadow
                and .thirdMove; the shadow / purified second-move price is the thirdMove price times SHARED_MOVE_SETTINGS' multipliers
                (2026-09-30: it used to be quoted at the plain price for every mon -- too low for a shadow, too high for a purified one)
      upgrade   POKEMON_UPGRADE_SETTINGS.pokemonUpgrades -- the Power Up tables
      override  {(dex, POKEMON_ID, FORM): tables} from POKEMON_UPGRADE_OVERRIDE_SETTINGS_<pokemonSettings templateId>: the game
                names an override after the template it belongs to (V0890_POKEMON_ETERNATUS); no other template points at it
      lucky     LUCKY_POKEMON_SETTINGS' powerUpStardustDiscountPercent
      xl_rate   {candy family: candyPerXlCandy} from the V####_FAMILY_ templates (100 candy buy 1 XL candy, where the game allows it)"""
    T = {'prices': {}, 'upgrade': None, 'override': {}, 'lucky': None, 'xl_rate': {}}
    shared, ov, ps = {}, {}, {}
    for t in templates:
        tid, dat = t.get('templateId', ''), t.get('data') or {}
        s = dat.get('pokemonSettings')
        m = re.match(r'V(\d{4})_POKEMON_', tid)
        if s and m:
            d = T['prices'].setdefault(int(m.group(1)), {})
            sh = s.get('shadow') or {}
            if sh.get('purificationStardustNeeded') and 'purify' not in d:
                d['purify'] = (int(sh['purificationStardustNeeded']), int(sh.get('purificationCandyNeeded') or 0))
            tm = s.get('thirdMove') or {}
            if tm.get('stardustToUnlock') and 'third' not in d:
                d['third'] = (int(tm['stardustToUnlock']), int(tm.get('candyToUnlock') or 0))
            ps[tid] = (int(m.group(1)), _norm(s.get('pokemonId')), _norm(s.get('form')))
        elif tid == 'POKEMON_UPGRADE_SETTINGS':
            T['upgrade'] = dat.get('pokemonUpgrades')
        elif tid.startswith('POKEMON_UPGRADE_OVERRIDE_SETTINGS_'):
            ov[tid[len('POKEMON_UPGRADE_OVERRIDE_SETTINGS_'):]] = dat.get('pokemonUpgrades')
        elif tid == 'LUCKY_POKEMON_SETTINGS':
            T['lucky'] = (dat.get('luckyPokemonSettings') or {}).get('powerUpStardustDiscountPercent')
        elif tid == 'SHARED_MOVE_SETTINGS':
            shared = dat.get('sharedMoveSettings') or {}
        elif re.match(r'V\d{4}_FAMILY_', tid) and (dat.get('pokemonFamily') or {}).get('candyPerXlCandy'):
            T['xl_rate'][int(tid[1:5])] = int(dat['pokemonFamily']['candyPerXlCandy'])
    T['override'] = {ps[k]: v for k, v in ov.items() if k in ps}
    for key, who in (('third_shadow', 'shadow'), ('third_purified', 'purified')):
        md, mc = shared.get(who + 'ThirdMoveUnlockStardustMultiplier'), shared.get(who + 'ThirdMoveUnlockCandyMultiplier')
        if isinstance(md, (int, float)) and isinstance(mc, (int, float)) and md > 0 and mc > 0:
            for d in T['prices'].values():
                if 'third' in d:
                    d[key] = (_up(d['third'][0], md), _up(d['third'][1], mc))
    return T


def _gm():
    """_parse of the client game master, cached. Raises when the file is unreadable, as the plain json.load it replaced did
    (the 2nd-move prices are not optional for the tags built on them); the Power Up callers catch that and say 'unknown'."""
    global _GM
    if _GM is None:
        _GM = _parse(json.load(open(os.path.join(HERE, 'gamemaster_pokeminers.json'), encoding='utf-8')))
    return _GM


def _prices():
    """{dex: {'purify': (dust, candy), 'third': (dust, candy), 'third_shadow': ..., 'third_purified': ...}} -- see _parse."""
    return _gm()['prices']


def third_price(dex, alignment=0):
    """(stardust, candy) of a mon's second charged move, by alignment (0 normal, 1 shadow, 2 purified); (None, None) = no price in
    the game master -- for a shadow / purified mon that includes a game master without the multipliers: never the plain price."""
    return _prices().get(dex, {}).get({1: 'third_shadow', 2: 'third_purified'}.get(alignment or 0, 'third'), (None, None))


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


def _alignment(r):
    """0 normal, 1 shadow, 2 purified (fresh_alignment). A row without the column (a narrowed projection) reads as normal --
    the price the old code quoted for every mon -- and never raises."""
    try:
        return r['fresh_alignment'] or 0
    except (KeyError, IndexError, TypeError):
        return 0


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
        d, c = third_price(r['pokemon_id'], _alignment(r))      # a shadow pays x1.2, a purified mon x0.8 (2026-09-30)
        fam = evolvable_forms.family(own)
        out.append({'uid': r['uid_hex'], 'species': r['species_name'], 'league': best[0], 'rank': best[1],
                    'dust': d, 'candy': c, 'affordable': _affordable(d, c, fam, dust, candy)})
    return sorted(out, key=lambda x: (x['rank'], not x['affordable'], x['dust'] or 0))


# ------------------------------------------------------------------------------------------------------------ Power Up prices
def _shape_ok(u):
    """Is this a Power Up table set in the shape power_up_cost prices? A game master that changes the shape (another upgradesPerLevel,
    a missing table) makes every cost UNKNOWN (None) -- never a wrong number."""
    try:
        return (u['upgradesPerLevel'] == 2 and int(u['maxNormalUpgradeLevel']) >= 2 and int(u['xlCandyMinPokemonLevel']) >= 1
                and all(isinstance(u[k], list) and u[k] and all(isinstance(x, (int, float)) and x >= 0 for x in u[k])
                        for k in ('stardustCost', 'candyCost', 'xlCandyCost'))
                and all(isinstance(u[k], (int, float)) and u[k] > 0 for k in (
                    'shadowStardustMultiplier', 'shadowCandyMultiplier', 'purifiedStardustMultiplier', 'purifiedCandyMultiplier')))
    except (KeyError, TypeError, ValueError):
        return False


def _tables(T, dex=None, form=0):
    """The Power Up tables of a bag mon: its POKEMON_UPGRADE_OVERRIDE_SETTINGS_<pokemonSettings templateId> when the game master has
    one, else POKEMON_UPGRADE_SETTINGS; None when they are not in a shape we price. The template is the mon's dex plus its form --
    the base form (no form, or <ID>_NORMAL) is the formless template V0890_POKEMON_ETERNATUS, any other form its own template."""
    u = T.get('upgrade')
    fn = evolvable_forms.form_name(form) if form else ''
    for (d, pid, frm), tab in T.get('override', {}).items():
        if dex and d == dex and (frm == fn or (frm in ('', pid + 'NORMAL') and fn in ('', pid + 'NORMAL'))):
            u = tab
    return u if u and _shape_ok(u) else None


def power_up_cost(level_from, level_to, shadow=False, purified=False, lucky=False, dex=None, form=0):
    """What the game charges to power a mon up from level_from to level_to, half a level at a time: {'dust', 'candy', 'xl', 'steps'},
    or None = cost UNKNOWN (never a guess). level_to at or below level_from is nothing to do: all 0.

    THE ONE PRICE (2026-09-30, Benny: "yes" to the game master's exact costs). deep_profile priced L40 -> L50 at 340,000 dust / 290 XL
    and L20 -> L50 at 840,000 dust; the game master says 250,000 dust / 296 XL and 475,000. Everything is READ from the client game
    master's POKEMON_UPGRADE_SETTINGS at call time, never hard-coded, so a new game master moves the numbers by itself:
      * upgradesPerLevel 2: one table slot per WHOLE level, paid twice. A step from level L reads slot floor(L) - 1 (L1 -> L1.5,
        L1.5 -> L2, L2 -> L2.5 and L2.5 -> L3 all cost 200 dust: slots 0 and 1; L39.5 -> L40 is slot 38, L49.5 -> L50 slot 48).
      * stardustCost[slot] dust, candyCost[slot] candy (the table holds 0 from L40), and from xlCandyMinPokemonLevel (40) also
        xlCandyCost[floor(L) - 40] XL candy (10, 10, 12, 12, 15, 15, 17, 17, 20, 20 per whole level). L1 -> L50 = 520,000 dust + 304
        candy + 296 XL candy; L40 -> L50 = 250,000 dust + 296 XL candy, the figures the game's own screens show.
      * shadow x shadowStardustMultiplier / shadowCandyMultiplier (1.2), purified x purified... (0.9), on dust AND on candy and XL
        candy; lucky x (1 - powerUpStardustDiscountPercent) on dust only (LUCKY_POKEMON_SETTINGS, 0.5; a purified lucky mon gets
        both, which no one has checked in game). Each step is rounded UP after the multiplier (_up).
      * a species with a POKEMON_UPGRADE_OVERRIDE_SETTINGS_<template> pays by ITS tables (dex + form pick the template): Eternatus
        30-890 candy and 100-890 XL candy per whole level for the same dust (L40 -> L50 is 8,900 XL candy, not 296).
    The trainer-level cap (level + allowedLevelsAbovePlayer) is max_power_up_level(), a question about the trainer, not the price."""
    try:
        T = _gm()
        u = _tables(T, dex, form)
        a, b = (float(level_from) - 1) * 2, (float(level_to) - 1) * 2
        if u is None or (shadow and purified) or not (math.isfinite(a) and math.isfinite(b)):
            return None
        if abs(a - round(a)) > 1e-6 or abs(b - round(b)) > 1e-6:
            return None                                 # not a half level: the game has no such level, so it has no price
        a, b = int(round(a)), int(round(b))
        out = {'dust': 0, 'candy': 0, 'xl': 0, 'steps': 0}
        if b <= a:
            return out
        if a < 0 or b > int(round((u['maxNormalUpgradeLevel'] - 1) * 2)):
            return None                                 # below L1, or above the last level a Power Up reaches
        md = u['shadowStardustMultiplier'] if shadow else u['purifiedStardustMultiplier'] if purified else 1.0
        mc = u['shadowCandyMultiplier'] if shadow else u['purifiedCandyMultiplier'] if purified else 1.0
        if lucky:
            disc = T.get('lucky')
            if not isinstance(disc, (int, float)) or not 0 <= disc <= 100:
                return None
            md *= 1 - (disc / 100.0 if disc > 1 else disc)   # 0.5 is half off; 50 would be the same, said in percent
        xmin = int(u['xlCandyMinPokemonLevel'])
        for i in range(a, b):
            whole = 1 + i // 2                          # the whole level this half step starts in; its table slot is whole - 1
            if whole > len(u['stardustCost']) or whole > len(u['candyCost']):
                return None
            out['dust'] += _up(u['stardustCost'][whole - 1], md)
            out['candy'] += _up(u['candyCost'][whole - 1], mc)
            if whole >= xmin:
                if whole - xmin >= len(u['xlCandyCost']):
                    return None
                out['xl'] += _up(u['xlCandyCost'][whole - xmin], mc)
        out['steps'] = b - a
        return out
    except Exception:
        return None                                     # no game master, or one we cannot read: UNKNOWN, never a number


def max_power_up_level(player_level, dex=None, form=0):
    """The highest level this trainer can power a mon to: trainer level + allowedLevelsAbovePlayer (10), at most maxNormalUpgradeLevel
    (50); None when unknown. Level 78 here, so it never binds -- a low-level second account's could."""
    try:
        u = _tables(_gm(), dex, form)
        if not u or not isinstance(player_level, int) or player_level < 1 or not isinstance(u.get('allowedLevelsAbovePlayer'), int):
            return None
        return float(min(u['maxNormalUpgradeLevel'], player_level + u['allowedLevelsAbovePlayer']))
    except Exception:
        return None


def _inventory(walk):
    """inventory.json when THIS walk wrote it and the walk's own tripwires did not STOP it -- the two gates evolvable_forms gives
    candy_now / items_now -- else None: stardust and the trainer level are read like the candy, never from another trainer's file
    (switch_account.py swaps pokemon.db but not inventory.json)."""
    p = os.path.join(HERE, 'system', 'analysis', 'inventory.json')
    try:
        if not evolvable_forms._walk_fresh(p, 7200, walk):
            return None
        d = json.load(open(p, encoding='utf-8'))
        return d if evolvable_forms._source_live(d) else None
    except Exception:
        return None


def _xl_now(walk):
    """{family: XL candy} from the walk's candy.json under the SAME gates evolvable_forms.candy_now applies (this walk wrote it, the walk
    was not STOPped), else None = unread, never a 0 he would believe. Kept here, not next to candy_now: evolvable_forms is hashed into
    the pile's engine stamp (keep_policy._engine_sha), and a report-only price must not touch the engine that decides the pile."""
    p = os.path.join(HERE, 'system', 'analysis', 'candy.json')
    try:
        if not evolvable_forms._walk_fresh(p, 7200, walk):
            return None
        d = json.load(open(p, encoding='utf-8'))
        if not evolvable_forms._source_live(d):
            return None
        return {int(k): v['xl'] for k, v in d['families'].items()}
    except Exception:
        return None


_STATUS_ORDER = {'now': 0, 'exchange': 1, 'short': 2, 'level': 3, 'unread': 4, 'unknown': 5}


def power_up_plan(items, rows, dust=_READ, candy=_READ, xl=_READ, player_level=_READ, family=None):
    """REPORT ONLY (2026-09-30): what it takes to power up the mons the Power Up tags hold, against what you hold. No keep reason,
    no tag and no pile decision reads this -- it only prices advice that is already given.

    items   [(uid, league, level now, target level)] -- granular_tags.power_ups' own (level now, best level) for the tag's members
    rows    {uid: bag row as a dict} -- the species, alignment, lucky flag, dex and form that pick the price
    dust / candy / xl / player_level   the balances: _READ (default) = this walk's (inventory.json for the stardust and the trainer
            level, candy.json for {family: candy} and {family: XL candy}, each only when THIS walk wrote it); None = was not read
    family  row -> candy family number (default: evolvable_forms.family of the mon's own stage)
    Returns one dict per item, best news first: uid, league, species, lv, target, need {dust, candy, xl} (None = no price), have
    {dust, candy, xl} (the family's balances; None = unread), family, short {dust, candy, xl} (what is missing), swap (the candy that
    buys the missing XL candy at candyPerXlCandy, 0 when unknown) and spare (the family's candy left after the power-up's own), status:
      now       every price is in stock
      exchange  only XL candy is missing and the family's spare candy covers swapping it in (100 candy per XL candy, candyPerXlCandy):
                doable IF the game allows the swap -- no tool here has ever done one and a daily limit is unknown, so the report says so
      short     something is missing that candy cannot cover
      level     the target is above the trainer's cap (max_power_up_level)
      unread    a balance it needs was not read by this walk: UNKNOWN is never shown as 'short' (H04)
      unknown   no price: no game master tables, an unknown family, or a level the game does not have"""
    rows = rows or {}
    if any(v is _READ for v in (dust, candy, xl, player_level)):
        walk = _walk_of(list(rows.values()))
        inv = _inventory(walk)
        if dust is _READ:
            dust = _stardust() if inv is not None else None
        if player_level is _READ:
            _lv = ((inv or {}).get('player') or {}).get('Level')
            player_level = _lv if isinstance(_lv, int) else None
        if candy is _READ:
            candy = evolvable_forms.candy_now(walk=walk)
        if xl is _READ:
            xl = _xl_now(walk)
    fam_of = family or (lambda r: evolvable_forms.family(pvid(r['species_name'], r['form'] or 0)))
    try:
        T = _gm()
    except Exception:
        T = None
    out = []
    for uid, league, lv, target in items:
        r = rows.get(uid)
        e = {'uid': uid, 'league': league, 'species': (r or {}).get('species_name') or '?', 'lv': lv, 'target': target, 'need': None,
             'have': None, 'family': None, 'short': {}, 'swap': 0, 'spare': None, 'status': 'unknown'}
        out.append(e)
        if r is None or T is None:
            continue
        al, dex, form = _alignment(r), r.get('pokemon_id'), r.get('form') or 0
        e['need'] = need = power_up_cost(lv, target, shadow=al == 1, purified=al == 2, lucky=bool(r.get('is_lucky')), dex=dex, form=form)
        try:
            e['family'] = fam = fam_of(r)
        except Exception:                               # a row the family lookup cannot read: no candy to look up
            e['family'] = fam = None
        if need is None or fam is None:
            continue
        have = e['have'] = {'dust': dust, 'candy': None if candy is None else candy.get(fam, 0),
                            'xl': None if xl is None else xl.get(fam, 0)}
        cap = max_power_up_level(player_level, dex, form)
        if cap is not None and target > cap:
            e['status'], e['cap'] = 'level', cap
        elif any(have[k] is None and need[k] > 0 for k in have):
            e['status'] = 'unread'
        else:
            e['short'] = short = {k: max(0, need[k] - (have[k] or 0)) for k in have}
            rate = T['xl_rate'].get(fam)
            if short['xl'] and rate:
                e['swap'], e['spare'] = short['xl'] * rate, (have['candy'] or 0) - need['candy']
            if not any(short.values()):
                e['status'] = 'now'
            elif short['xl'] and not short['dust'] and not short['candy'] and e['swap'] and e['spare'] >= e['swap']:
                e['status'] = 'exchange'
            else:
                e['status'] = 'short'
    return sorted(out, key=lambda e: (_STATUS_ORDER[e['status']], (e['need'] or {}).get('dust', 0), e['uid']))


# ----------------------------------------------------------------------------------------------------------------- self-test
def _selftest():
    """Offline -- CI has no game master, no bag DB and no data store: the parser on a miniature game master shaped like the real
    one, and golden prices hand-checked against POKEMON_UPGRADE_SETTINGS (APK 0.427.0; identical in 0.395.1 and 0.407.0). Where the
    real game master IS here (a cloud or PC session) the same goldens also run on IT, so a game master that changes a price fails
    this test: check the new numbers by hand, then update the fixture and the goldens. Wired into tools/triple_check.py and CI."""
    global _GM, HERE
    import contextlib, inspect, io, tempfile
    bad, n = [], [0]

    def ck(cond, msg):
        n[0] += 1
        if not cond:
            bad.append(msg)

    dust = ([200, 200, 400, 400, 600, 600, 800, 800, 1000, 1000] + [1300, 1300, 1600, 1600, 1900, 1900, 2200, 2200, 2500, 2500]
            + [3000, 3000, 3500, 3500, 4000, 4000, 4500, 4500, 5000, 5000] + [6000, 6000, 7000, 7000, 8000, 8000, 9000, 9000, 10000, 10000]
            + [11000, 11000, 12000, 12000, 13000, 13000, 14000, 14000, 15000])            # 49 slots, L1 .. L49
    base = {'upgradesPerLevel': 2, 'allowedLevelsAbovePlayer': 10, 'stardustCost': dust,
            'candyCost': [1] * 10 + [2] * 10 + [3] * 5 + [4] * 5 + [6, 6, 8, 8, 10, 10, 12, 12, 15] + [0] * 11,   # 50 slots: 0 from L40
            'shadowStardustMultiplier': 1.2, 'shadowCandyMultiplier': 1.2, 'purifiedStardustMultiplier': 0.9, 'purifiedCandyMultiplier': 0.9,
            'maxNormalUpgradeLevel': 50, 'defaultCpBoostAdditionalLevel': 1, 'xlCandyMinPlayerLevel': 31,
            'xlCandyCost': [10, 10, 12, 12, 15, 15, 17, 17, 20, 20], 'xlCandyMinPokemonLevel': 40}
    etern = dict(base, candyCost=[30] * 10 + [60] * 10 + [90] * 5 + [120] * 5 + [175, 175, 225, 225, 300, 300, 375, 375, 890] + [0] * 11,
                 xlCandyCost=[100, 100, 200, 200, 400, 400, 635, 635, 890, 890])

    def tpl(tid, **data):
        return {'templateId': tid, 'data': dict(data, templateId=tid)}
    shared = {'shadowThirdMoveUnlockStardustMultiplier': 1.2, 'shadowThirdMoveUnlockCandyMultiplier': 1.2,
              'purifiedThirdMoveUnlockStardustMultiplier': 0.8, 'purifiedThirdMoveUnlockCandyMultiplier': 0.8}
    mini = [tpl('POKEMON_UPGRADE_SETTINGS', pokemonUpgrades=base),
            tpl('POKEMON_UPGRADE_OVERRIDE_SETTINGS_V0890_POKEMON_ETERNATUS', pokemonUpgrades=etern),
            tpl('POKEMON_UPGRADE_OVERRIDE_SETTINGS_V0999_POKEMON_NOBODY', pokemonUpgrades=etern),   # names no template: dropped
            tpl('LUCKY_POKEMON_SETTINGS', luckyPokemonSettings={'powerUpStardustDiscountPercent': 0.5}),
            tpl('SHARED_MOVE_SETTINGS', sharedMoveSettings=shared),
            tpl('V0355_FAMILY_DUSKULL', pokemonFamily={'familyId': 'FAMILY_DUSKULL', 'candyPerXlCandy': 100}),
            tpl('V0108_FAMILY_LICKITUNG', pokemonFamily={'familyId': 'FAMILY_LICKITUNG', 'candyPerXlCandy': 100}),
            tpl('V0001_POKEMON_BULBASAUR', pokemonSettings={'pokemonId': 'BULBASAUR', 'thirdMove': {'stardustToUnlock': 10000, 'candyToUnlock': 25},
                                                            'shadow': {'purificationStardustNeeded': 3000, 'purificationCandyNeeded': 3}}),
            tpl('V0002_POKEMON_IVYSAUR', pokemonSettings={'pokemonId': 'IVYSAUR'}),                 # no price at all
            tpl('V0890_POKEMON_ETERNATUS', pokemonSettings={'pokemonId': 'ETERNATUS', 'thirdMove': {'stardustToUnlock': 100000, 'candyToUnlock': 100}}),
            tpl('V0890_POKEMON_ETERNATUS_ETERNAMAX', pokemonSettings={'pokemonId': 'ETERNATUS', 'form': 'ETERNATUS_ETERNAMAX'})]

    # ---- the parser, on the miniature game master
    T = _parse(mini)
    ck(T['upgrade'] == base and T['lucky'] == 0.5 and T['xl_rate'] == {355: 100, 108: 100}, 'parser: tables / lucky / candyPerXlCandy')
    ck(list(T['override']) == [(890, 'ETERNATUS', '')] and T['override'][(890, 'ETERNATUS', '')] == etern,
       'parser: the override belongs to the template its name says, and an override naming no template is dropped: %s' % list(T['override']))
    ck(T['prices'][1] == {'purify': (3000, 3), 'third': (10000, 25), 'third_shadow': (12000, 30), 'third_purified': (8000, 20)},
       'parser: Bulbasaur prices %s' % T['prices'][1])
    ck(T['prices'][2] == {} and T['prices'][890]['third_shadow'] == (120000, 120) and T['prices'][890]['third_purified'] == (80000, 80),
       'parser: a mon with no price stays empty; Eternatus x1.2 / x0.8: %s' % T['prices'][890])
    _GM = _parse([t for t in mini if t['templateId'] != 'SHARED_MOVE_SETTINGS'])
    ck(third_price(1, 1) == (None, None) and third_price(1, 2) == (None, None) and third_price(1) == (10000, 25),
       'no SHARED_MOVE_SETTINGS: a shadow / purified price is unknown, never the plain one')

    # ---- golden prices: (from, to) -> (dust, candy, XL candy, half-level steps), every figure worked out by hand from the tables
    def goldens(tag):
        G = [((1, 50), {}, (520000, 304, 296, 98)),         # the whole ladder: 270,000 + 250,000 dust, 304 candy (L1-L40), 296 XL (L40-L50)
             ((1, 40), {}, (270000, 304, 0, 78)),
             ((40, 50), {}, (250000, 0, 296, 20)),          # what the game's own screens show for L40 -> L50 (deep_profile said 340,000 / 290)
             ((20, 50), {}, (475000, 248, 296, 60)),        # (deep_profile said 840,000 dust)
             ((16, 50), {}, (492600, 264, 296, 68)),        # the Mandibuzz of the 2026-09-30 bag: 242,600 + 250,000 dust
             ((49.5, 50), {}, (15000, 0, 20, 1)),           # the last half level: Dusknoir / Slurpuff / Stunfisk, 15,000 dust + 20 XL
             ((39.5, 40), {}, (10000, 15, 0, 1)),           # the last step paid in plain candy ...
             ((40, 40.5), {}, (10000, 0, 10, 1)),           # ... the first paid in XL candy, for the same 10,000 dust (slot 39)
             ((1, 1.5), {}, (200, 1, 0, 1)), ((2, 2.5), {}, (200, 1, 0, 1)), ((2.5, 3), {}, (200, 1, 0, 1)), ((3, 3.5), {}, (400, 1, 0, 1)),
             ((10, 10.5), {}, (1000, 1, 0, 1)), ((11, 11.5), {}, (1300, 2, 0, 1)),
             ((40, 50), {'shadow': True}, (300000, 0, 360, 20)),    # dust x1.2 exactly; XL 12,12,15,15,18,18,21,21,24,24 twice (up, not 355.2)
             ((1, 2), {'shadow': True}, (480, 4, 0, 2)),            # 240 dust and ceil(1 x 1.2) = 2 candy per half level
             ((1, 40), {'shadow': True}, (324000, 406, 0, 78)),
             ((40, 50), {'purified': True}, (225000, 0, 272, 20)),  # dust x0.9 exactly; XL 9,9,11,11,14,14,16,16,18,18 twice
             ((40, 50), {'lucky': True}, (125000, 0, 296, 20)),     # lucky halves the dust only
             ((1, 50), {'lucky': True}, (260000, 304, 296, 98)),
             ((40, 50), {'dex': 890, 'form': 2581}, (250000, 0, 8900, 20)),    # Eternatus (EternatusNormal): same dust, 100..890 XL a level
             ((1, 40), {'dex': 890}, (270000, 9980, 0, 78)),
             ((45, 50), {'dex': 890, 'form': 2581}, (138000, 0, 6900, 10)),    # the Eternatus L45 of the bag
             ((40, 50), {'dex': 25}, (250000, 0, 296, 20)),                    # any other species: the default tables
             ((50, 40), {}, (0, 0, 0, 0)), ((51, 50), {}, (0, 0, 0, 0)), ((20, 20), {}, (0, 0, 0, 0))]
        for a, kw, want in G:
            got = power_up_cost(*a, **kw)
            ck(got is not None and (got['dust'], got['candy'], got['xl'], got['steps']) == want, '%s: %s %s -> %s, want %s' % (tag, a, kw, got, want))
        for a, kw in (((1, 50.5), {}), ((0.5, 10), {}), ((12.3, 20), {}), (('x', 5), {}), ((None, 5), {}), ((float('nan'), 5), {}),
                      ((1, 50), {'shadow': True, 'purified': True})):
            ck(power_up_cost(*a, **kw) is None, '%s: %s %s has no price, got %s' % (tag, a, kw, power_up_cost(*a, **kw)))
        for lv in [1 + i / 2 for i in range(0, 99)]:                     # a price is the sum of its steps, for every split of L1 -> L50
            w, p1, p2 = power_up_cost(1, 50), power_up_cost(1, lv), power_up_cost(lv, 50)
            ck(all(p1[k] + p2[k] == w[k] for k in ('dust', 'candy', 'xl', 'steps')), '%s: L1 -> L%s -> L50 does not add up' % (tag, lv))

    _GM = T
    goldens('fixture')
    ck(power_up_cost(40, 50, dex=890, form=2580)['xl'] == 296, 'an Eternamax has its own template, which has no override')
    ck(third_price(1) == (10000, 25) and third_price(1, 1) == (12000, 30) and third_price(1, 2) == (8000, 20) and third_price(2) == (None, None)
       and third_price(999) == (None, None) and third_price(1, None) == (10000, 25), 'third_price by alignment')
    ck(max_power_up_level(78) == 50.0 and max_power_up_level(30) == 40.0 and max_power_up_level(0) is None and max_power_up_level(None) is None,
       'the trainer-level cap: level + 10, at most 50')
    _GM = _parse(mini[:1] + [dict(mini[1], data={'pokemonUpgrades': dict(base, upgradesPerLevel=4)})] + mini[3:])
    ck(power_up_cost(1, 50, dex=890) is None and power_up_cost(1, 50)['dust'] == 520000, 'a table in a shape we do not price is UNKNOWN, the rest is not')
    _GM = _parse([tpl('POKEMON_UPGRADE_SETTINGS', pokemonUpgrades=dict(base, stardustCost=dust[:30]))])
    ck(power_up_cost(1, 30)['dust'] == 120000 and power_up_cost(1, 40) is None, 'a table too short for the levels asked is UNKNOWN')
    _GM = _parse([tpl('POKEMON_UPGRADE_SETTINGS', pokemonUpgrades=dict(base, maxNormalUpgradeLevel=40))])
    ck(power_up_cost(1, 40)['dust'] == 270000 and power_up_cost(1, 40.5) is None, 'the game master\'s own top level is the limit, whatever the tables hold')
    ck(_up(50, 1.1) == 55 and _up(25, 1.2) == 30 and _up(15, 0.9) == 14 and _up(1, 1.2) == 2 and _up(8, 0.9) == 8,
       '_up: rounds up, and float noise (50 x 1.1 = 55.00000000000001) does not cost a whole candy')
    _saved, _GM = HERE, None
    with tempfile.TemporaryDirectory() as tmp:
        HERE = tmp
        try:
            ck(power_up_cost(1, 50) is None and max_power_up_level(78) is None, 'no game master: UNKNOWN, no exception')
        finally:
            HERE = _saved

    # ---- power_up_plan: statuses, in the order the report lists them
    _GM = T
    row = lambda **kw: dict({'species_name': 'Dusknoir', 'pokemon_id': 477, 'form': 0, 'fresh_alignment': 0, 'is_lucky': 0, 'fam': 355}, **kw)
    rows = {'a': row(), 'b': row(), 'c': row(fam=108), 'd': row(), 'e': row(), 'f': row(fresh_alignment=1), 'g': row(fam=None), 'h': row(fam=999)}
    items = [('a', 'ul', 16.0, 50.0), ('b', 'ul', 49.5, 50.0), ('c', 'ul', 43.0, 48.5), ('d', 'ul', 49.5, 50.0), ('e', 'ul', 40.0, 50.0),
             ('f', 'ul', 40.0, 50.0), ('g', 'ul', 40.0, 50.0), ('h', 'ul', 49.5, 50.0), ('zz', 'ul', 40.0, 50.0), ('a', 'gl', 40.0, 52.0)]

    def plan(**kw):
        bal = dict(dust=2462829, candy={355: 6488, 108: 982, 999: 10}, xl={355: 601, 108: 14, 999: 1}, player_level=78)
        bal.update(kw)
        return {e['uid'] + '/' + e['league']: e for e in power_up_plan(items, rows, family=lambda r: r['fam'], **bal)}
    P = plan()
    ck(P['a/ul']['need'] == {'dust': 492600, 'candy': 264, 'xl': 296, 'steps': 68} and P['a/ul']['status'] == 'now', 'plan: doable now %s' % P['a/ul'])
    ck(P['b/ul']['status'] == 'now', 'plan: 601 XL held, 20 needed: now')
    P = plan(xl={355: 18, 108: 14, 999: 1})
    ck(P['b/ul']['status'] == 'exchange' and P['b/ul']['swap'] == 200 and P['b/ul']['short'] == {'dust': 0, 'candy': 0, 'xl': 2},
       'plan: 18 XL held, 20 needed: exchange 200 candy, %s' % P['b/ul'])
    ck(P['c/ul']['status'] == 'short' and P['c/ul']['short']['xl'] == 158 and P['c/ul']['swap'] == 15800 and P['c/ul']['spare'] == 982,
       'plan: 158 XL short, 15,800 candy to swap, 982 held: short, %s' % P['c/ul'])
    ck(P['a/ul']['status'] == 'short' and P['a/ul']['short'] == {'dust': 0, 'candy': 0, 'xl': 278} and P['a/ul']['swap'] == 27800
       and P['a/ul']['spare'] == 6488 - 264, 'plan: 278 XL short swaps for 27,800 candy, and the 264 it needs itself are not spare: %s' % P['a/ul'])
    ck(P['h/ul']['status'] == 'short' and P['h/ul']['short']['xl'] == 19 and P['h/ul']['swap'] == 0, 'plan: a family with no candyPerXlCandy: short, no swap offered')
    P = plan(dust=10000, xl={355: 18, 108: 14, 999: 1})
    ck(P['b/ul']['status'] == 'short' and P['b/ul']['short'] == {'dust': 5000, 'candy': 0, 'xl': 2}, 'plan: dust short too: no exchange offered, %s' % P['b/ul'])
    P = plan(candy={355: 100, 108: 982, 999: 10}, xl={355: 18, 108: 14, 999: 1})
    ck(P['b/ul']['status'] == 'short' and P['b/ul']['spare'] == 100, 'plan: the family candy cannot cover the swap: short')
    ck(plan(candy={355: 200}, xl={355: 18})['b/ul']['status'] == 'exchange' and plan(candy={355: 199}, xl={355: 18})['b/ul']['status'] == 'short',
       'plan: 200 spare candy is exactly the swap of 2 XL; 199 is not')
    ck(P['f/ul']['need'] == {'dust': 300000, 'candy': 0, 'xl': 360, 'steps': 20}, 'plan: a shadow is priced as a shadow')
    ck(plan(player_level=30)['e/ul']['status'] == 'level' and plan(player_level=30)['e/ul']['cap'] == 40.0, 'plan: above the trainer-level cap')
    for k, who in (('dust', 'e'), ('xl', 'e'), ('candy', 'a')):      # 'e' needs dust + XL and no candy, 'a' needs candy too
        ck(plan(**{k: None})[who + '/ul']['status'] == 'unread', 'plan: %s not read this walk is unread, never short' % k)
    ck(plan(candy=None)['e/ul']['status'] == 'now', 'plan: a balance the mon does not need may stay unread')
    ck(plan(player_level=None)['e/ul']['status'] == 'now', 'plan: an unread trainer level skips the cap check')
    P = plan()
    ck(P['g/ul']['status'] == 'unknown' and P['zz/ul']['status'] == 'unknown' and P['a/gl']['status'] == 'unknown' and P['a/gl']['need'] is None,
       'plan: no family, no row, a level above 50: unknown')
    order = [e['status'] for e in power_up_plan(items, rows, family=lambda r: r['fam'], dust=2462829, candy={355: 6488, 108: 982}, xl={355: 300, 108: 14},
                                                 player_level=78)]
    ck(order == sorted(order, key=['now', 'exchange', 'short', 'level', 'unread', 'unknown'].index) and order[0] == 'now' and order[-1] == 'unknown'
       and 'exchange' in order, 'plan: best news first %s' % order)

    # ---- the balances come only from THIS walk's files (evolvable_forms' gates), read from a scratch folder standing in for system/analysis
    import time
    _candy_now, _saved = evolvable_forms.candy_now, HERE
    with tempfile.TemporaryDirectory() as tmp:
        ad = os.path.join(tmp, 'system', 'analysis')
        os.makedirs(ad)
        t_mt = time.mktime((2026, 6, 15, 12, 0, 0, 0, 0, -1))                     # a fixed noon, never inside a DST change: no flaky hour
        walk = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t_mt - 20))      # the walk stamps its rows ~20 s before it writes the files
        fams = {'355': {'candy': 6488, 'xl': 18}}

        def put(name, obj, mt=t_mt):
            p = os.path.join(ad, name)
            with open(p, 'w', encoding='utf-8') as fh:
                json.dump(obj, fh)
            os.utime(p, (mt, mt))
        HERE = tmp
        evolvable_forms.candy_now = lambda max_age_s=7200, walk=None: {355: 6488}     # candy.json's candy half is evolvable_forms' own test
        try:
            put('candy.json', {'families': fams, 'source': {'verdict': 'OK'}})
            put('inventory.json', {'stardust': 2462829, 'player': {'Level': 78}, 'source': {'verdict': 'OK'}})
            wr = {'b': row(last_scanned=walk)}
            ck(_xl_now(walk) == {355: 18} and _inventory(walk)['stardust'] == 2462829, 'balances: the files this walk wrote are read')
            P = power_up_plan([('b', 'ul', 49.5, 50.0)], wr, family=lambda r: 355)[0]
            ck(P['status'] == 'exchange' and P['have'] == {'dust': 2462829, 'candy': 6488, 'xl': 18} and P['swap'] == 200,
               'balances: read from the walk by default: %s' % P)
            put('inventory.json', {'stardust': 2462829, 'player': {'Level': 30}, 'source': {'verdict': 'OK'}})
            P = power_up_plan([('b', 'ul', 40.0, 50.0)], wr, family=lambda r: 355)[0]
            ck(P['status'] == 'level' and P['cap'] == 40.0, 'balances: the trainer level is the walk\'s own: %s' % P)
            put('inventory.json', {'stardust': 2462829, 'player': {'Level': 78}, 'source': {'verdict': 'STOP'}})
            ck(_inventory(walk) is None, 'balances: an inventory the tripwires STOPped is not read')
            put('inventory.json', {'stardust': 2462829, 'player': {'Level': 78}, 'source': {'verdict': 'OK'}})
            put('candy.json', {'families': fams, 'source': {'verdict': 'STOP'}})
            ck(_xl_now(walk) is None, 'balances: a walk the tripwires STOPped is not read')
            put('candy.json', {'families': {'355': {'candy': 1}}, 'source': {'verdict': 'OK'}})
            ck(_xl_now(walk) is None, 'balances: a file without XL counts reads as unread, never as 0')
            put('candy.json', {'families': fams, 'source': {'verdict': 'OK'}}, mt=t_mt - 7200)
            put('inventory.json', {'stardust': 2462829, 'player': {'Level': 78}}, mt=t_mt - 7200)
            ck(_xl_now(walk) is None and _inventory(walk) is None, 'balances: files an older walk wrote are not read')
            P = power_up_plan([('b', 'ul', 49.5, 50.0)], wr, family=lambda r: 355)[0]
            ck(P['status'] == 'unread' and P['have']['dust'] is None, 'balances: stale files make the plan unread, never short: %s' % P)
        finally:
            HERE, evolvable_forms.candy_now = _saved, _candy_now

    # ---- wiring: the 2nd-move price is chosen by alignment, and the CLI runs nothing on a guessed flag
    src = inspect.getsource(second_moves)
    ck('third_price(r[' in src and '_alignment(r)' in src and ".get('third'" not in src, 'second_moves prices by alignment')
    ck(_alignment({'fresh_alignment': 1}) == 1 and _alignment({'fresh_alignment': None}) == 0 and _alignment({}) == 0, '_alignment')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rcs = [main(['--bogus']), main(['--help']), main(['--selftest', 'x'])]
    ck(rcs == [2, 2, 2] and 'Any other argument prints this usage' in buf.getvalue(), 'a guessed flag prints the usage and runs nothing: %s' % rcs)

    # ---- the real game master, when it is here: the same goldens, and the fixture must BE its tables
    live = os.path.exists(os.path.join(HERE, 'gamemaster_pokeminers.json'))
    if live:
        _GM = None
        try:
            L = _gm()
            ck(L['upgrade'] == base, 'live game master: POKEMON_UPGRADE_SETTINGS is not the table these goldens were checked against')
            ck(list(L['override']) == [(890, 'ETERNATUS', '')] and L['override'][(890, 'ETERNATUS', '')] == etern,
               'live game master: the upgrade overrides changed: %s' % list(L['override']))
            ck(L['lucky'] == 0.5 and L['xl_rate'].get(355) == 100 and len(L['xl_rate']) > 400, 'live game master: lucky discount / candyPerXlCandy')
            ck(all(v.get('third_shadow') == (_up(v['third'][0], 1.2), _up(v['third'][1], 1.2)) and v.get('third_purified') == (_up(v['third'][0], 0.8), _up(v['third'][1], 0.8))
                   for v in L['prices'].values() if 'third' in v), 'live game master: the 2nd-move multipliers are not x1.2 / x0.8')
            goldens('live game master')
        finally:
            _GM = None
    _GM = None
    if bad:
        print('game_opportunities selftest FAILED (%d of %d checks):' % (len(bad), n[0]))
        for b in bad:
            print('  -', b)
        return 1
    print('game_opportunities selftest: ok (%d checks; %s)' % (n[0], 'fixture and the live game master' if live else 'fixture only, no game master here'))
    return 0


def _demo():
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


def main(argv):
    """No argument: what is on offer today. --selftest: the offline checks. Anything else: the usage, rc 2, and nothing runs (2026-09-30,
    docs/memory/feedback-never-probe-scripts-with-help.md: this file used to ignore its arguments and run for real)."""
    if argv == ['--selftest']:
        return _selftest()
    if argv:
        print(__doc__)
        return 2
    _demo()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
