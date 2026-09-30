"""keep_engine.py -- the SINGLE source of truth that unifies the three systems.

For years there were THREE parallel implementations of "what's worth keeping":
  1. cull_v9.PROTECTION_RULES  (KEEP vs TRANSFER, sanity-gated)
  2. deep_profile's purpose block (COLLECTION / PVP / ... / TRANSFER)
  3. tags/registry.json rules   (the 16 server tags)
They drifted (shadow kept by cull but transferred by purpose; best_buddy column
mismatch; species-top-N sort-key differences; Reserve-tag sync gaps -> ~197 mons
disagreed on 2026-05-28).

THE MODEL: there is ONE keep-reason engine (cull_v9's registry) and THREE VIEWS:
  * CULL view    = transfer iff the reason set is EMPTY.
  * PURPOSE view = the single highest-PRIORITY reason's category.
  * TAG view     = the reasons PoGo can't filter natively (the custom 16 tags).

This module owns the reason -> (purpose, native-filterable?, related tag) mapping
and the purpose-priority collapse. deep_profile imports `classify_purpose`; the
system-map imports `REASON_META`. Change a mapping HERE and all views move together.
"""
import re

# Roles-first priority: an actionable battle/system role outranks passive
# collection; quality reserve outranks trade/junk. Index = priority (lower wins).
PURPOSE_PRIORITY = ['PVP', 'MEGA', 'ADVENTURE', 'MAX', 'COLLECTION', 'RESERVE', 'TRADE', 'TRANSFER']
_PRIO = {p: i for i, p in enumerate(PURPOSE_PRIORITY)}

# Per-reason metadata. Keys are reason PREFIXES (suffixes like _rank3 / _from_x
# / the ll_topN number are normalized away by reason_prefix()).
#   purpose : which PURPOSE view bucket this reason drives
#   native  : True if PoGo's in-game search can already filter it (=> no custom
#             tag needed, per the "only tag what's not native" philosophy)
#   tag     : the related custom server tag, or None
REASON_META = {
    # --- PVP (actionable battle role beats everything) ---
    'gl_top2_pvp':           {'purpose': 'PVP', 'native': False, 'tag': '1 GL IV / 1 GL Meta'},
    'ul_top2_pvp':           {'purpose': 'PVP', 'native': False, 'tag': '1 UL IV / 1 UL Meta'},
    'll_top':                {'purpose': 'PVP', 'native': False, 'tag': None},  # ll_topN collapses here
    # --- MEGA ---
    'current_mega_evolved':  {'purpose': 'MEGA', 'native': True,  'tag': '2 Mega'},
    'has_mega_level':        {'purpose': 'MEGA', 'native': False, 'tag': '2 Mega'},
    # --- ADVENTURE (only mons with CHARGES remaining are an actionable AE role;
    #     being an AE *species* is just a cull protection -> its purpose is the
    #     mon's collection/role value, usually COLLECTION as a legendary). ---
    'adventure_effect_uses':    {'purpose': 'ADVENTURE',  'native': True, 'tag': None},
    'adventure_effect_species': {'purpose': 'COLLECTION', 'native': True, 'tag': None},
    # --- MAX (Dynamax / Gigantamax) ---
    'bread':                 {'purpose': 'MAX', 'native': True, 'tag': None},
    # --- COLLECTION (passive keep-forever) ---
    'hundo':                 {'purpose': 'COLLECTION', 'native': False, 'tag': '4 Hundo'},
    'nundo':                 {'purpose': 'COLLECTION', 'native': False, 'tag': '4 Nundo'},
    'shiny_top5':            {'purpose': 'COLLECTION', 'native': True,  'tag': None},
    'shiny_protected_chain': {'purpose': 'COLLECTION', 'native': True,  'tag': None},
    'shiny_3star+':          {'purpose': 'COLLECTION', 'native': True,  'tag': None},
    'legendary':             {'purpose': 'COLLECTION', 'native': True,  'tag': None},
    'mythical':              {'purpose': 'COLLECTION', 'native': True,  'tag': None},
    'ultra_beast':           {'purpose': 'COLLECTION', 'native': True,  'tag': None},
    'paradox':               {'purpose': 'COLLECTION', 'native': False, 'tag': None},
    'costume':               {'purpose': 'COLLECTION', 'native': True,  'tag': '4 Costume'},
    'xxl_top3_heaviest':     {'purpose': 'COLLECTION', 'native': False, 'tag': '4 XXL'},
    'full_protect_species':  {'purpose': 'COLLECTION', 'native': False, 'tag': None},
    'lucky':                 {'purpose': 'COLLECTION', 'native': True,  'tag': None},
    'has_badge':             {'purpose': 'COLLECTION', 'native': False, 'tag': None},
    'location_card':         {'purpose': 'COLLECTION', 'native': True,  'tag': None},
    'best_buddy':            {'purpose': 'COLLECTION', 'native': True,  'tag': '3 Best Buddy'},
    'shadow':                {'purpose': 'COLLECTION', 'native': True,  'tag': None},
    'purified':              {'purpose': 'COLLECTION', 'native': True,  'tag': None},
    'traded':                {'purpose': 'COLLECTION', 'native': True,  'tag': '5 Ethan / 5 Florandez'},
    # --- RESERVE (quality battler / dex copy / completion) ---
    'final_top3':            {'purpose': 'RESERVE', 'native': False, 'tag': '6 Reserve'},
    'preevo_top2':           {'purpose': 'RESERVE', 'native': False, 'tag': '6 Reserve'},
    'preevo2_top2':          {'purpose': 'RESERVE', 'native': False, 'tag': '6 Reserve'},
    'legacy_move':           {'purpose': 'RESERVE', 'native': False, 'tag': '3 Legacy Moves'},
    'dex_gap_evolution':     {'purpose': 'RESERVE', 'native': False, 'tag': None},
    'deployed_in_gym':       {'purpose': 'RESERVE', 'native': True,  'tag': None},
    'is_strong':             {'purpose': 'RESERVE', 'native': False, 'tag': None},
}

# Human-readable label + plain-English description for every keep-reason prefix.
# Keyed by the SAME normalized prefix as REASON_META (+ the special prefixes
# user_tag / ll_top / shadow / purified). Used by build_map.py so the matrix
# reads in English instead of cull_v9's internal codenames.
REASON_LABELS = {
    # PVP
    'gl_top2_pvp':   ('Great League — top 2', "One of the 2 best of its species for GL (rank ≤10 + CP gate) — a build target."),
    'ul_top2_pvp':   ('Ultra League — top 2', "One of the 2 best of its species for UL (rank ≤10 + CP gate) — a build target."),
    'll_top':        ('Little League — ranked', "Ranked top-15 of its species for Little League."),
    # MEGA
    'current_mega_evolved': ('Mega-Evolved now', "Currently in its Mega form."),
    'has_mega_level':       ('Has Mega level', "Mega energy already invested (has a Mega level) — your mega keeper."),
    # ADVENTURE / MAX
    'adventure_effect_uses':   ('Adventure-Effect charges left', "Has Adventure-Effect uses remaining — usable in-field right now."),
    'adventure_effect_species':('Adventure-Effect species', "An AE-capable species (Dialga, Palkia, Kyurem, Necrozma, Zacian, Zamazenta…)."),
    'bread':         ('Dynamax / Gigantamax', "Can Dynamax or Gigantamax (used in Max Battles)."),
    # COLLECTION — IV / rarity
    'hundo':         ('Perfect IV (15/15/15)', "A 'hundo' — maxed individual values."),
    'nundo':         ('Zero IV (0/0/0)', "A 'nundo' — the rare all-zero IV specimen."),
    'legendary':     ('Legendary', "A Legendary species."),
    'mythical':      ('Mythical', "A Mythical species."),
    'ultra_beast':   ('Ultra Beast', "An Ultra Beast species."),
    'paradox':       ('Paradox', "A Paradox species (ancient/future)."),
    'full_protect_species': ('Always-keep species', "Hand-protected species — Mimikyu & Blissey — never culled."),
    # COLLECTION — shiny
    'shiny_protected_chain': ('Shiny (protected family)', "A shiny in a hand-protected evolution line — always kept regardless of IV."),
    'shiny_top5':    ('Shiny — top 5 of species', "One of your 5 best shinies of this species/form."),
    'shiny_3star+':  ('Shiny — 3★+ extra', "A shiny beyond the top 5 but still 3-star-or-better IVs."),
    # COLLECTION — status / cosmetic / origin
    'shadow':        ('Shadow', "A Shadow Pokémon (boosted attack; needed for shadow raids)."),
    'purified':      ('Purified', "A Purified Pokémon."),
    'lucky':         ('Lucky (special friend)', "A Lucky trade from a tracked friend (Ethan/Florandez) or unknown owner."),
    'traded':        ('Traded (special friend)', "Traded from a tracked friend (Ethan/Florandez) or unknown owner."),
    'best_buddy':    ('Best Buddy', "At Best Buddy level with you."),
    'deployed_in_gym':('Defending a gym', "Currently deployed in a gym."),
    'costume':       ('Costume', "Wearing a costume / event hat."),
    'location_card': ('Location card', "Caught at a special place (carries a background/location card)."),
    'has_badge':     ('Has a badge', "Carries a decorative per-Pokémon badge."),
    'is_strong':     ('Mighty', "Flagged 'strong' / Mighty (L40+, high-IV elite specimen)."),
    'xxl_top3_heaviest': ('XXL — top 3 heaviest', "One of the 3 heaviest XXL of its species (Showcase fodder)."),
    # RESERVE — quality / dex / completion
    'final_top3':    ('Top 3 of a final form', "One of your 3 best (IV→CP) of a fully-evolved species/form."),
    'preevo_top2':   ('Top 2 of a pre-evo', "One of your 2 best of a not-fully-evolved species/form."),
    'preevo2_top2':  ('Top 2 of a multi-form pre-evo', "Top 2 of a per-form-tracked pre-evo (Scatterbug/Tandemaus/Rockruff)."),
    'legacy_move':   ('Legacy move', "Knows a legacy / exclusive-event-only move."),
    'dex_gap_evolution': ('Only path to a missing dex form', "Your best — and possibly only — way to fill a missing Pokédex entry/form."),
    # tag fallback
    'user_tag':      ('Carries a custom tag', "You hand-tagged it with one of your 16 server tags — kept by your choice."),
}


# user_tag_<name> reasons: purpose derived from the tag's number-prefix scheme
# (1=PvP 2=Raid/Mega 3=Keep 4=Collection 5=Origin 6=Sort). A mon usually also
# carries the INTRINSIC reason (hundo, legendary, ...), which wins on priority;
# the user_tag is the fallback so a hand-tagged mon still gets a sensible purpose.
_TAGNUM_PURPOSE = {'1': 'PVP', '2': 'MEGA', '3': 'RESERVE', '4': 'COLLECTION',
                   '5': 'COLLECTION', '6': 'RESERVE'}
_SPECIAL_TAG_PURPOSE = {'6 trade': 'TRADE'}  # 6 Reserve -> RESERVE (default), 6 Trade -> TRADE


def reason_prefix(reason):
    """Normalize a raw cull reason string to its mapping key."""
    if reason.startswith('ll_top'):
        return 'll_top'
    if reason.startswith('user_tag_'):
        return 'user_tag'
    # strip trailing _rankN, _<digits>, _from_<owner>
    return re.sub(r'_(rank\d+|\d+|from_.*)$', '', reason)


def _reason_purpose(reason):
    """Purpose category a single reason maps to (None if unknown)."""
    if reason.startswith('user_tag_'):
        name = reason[len('user_tag_'):].strip()
        low = name.lower()
        if low in _SPECIAL_TAG_PURPOSE:
            return _SPECIAL_TAG_PURPOSE[low]
        digit = name[:1]
        return _TAGNUM_PURPOSE.get(digit, 'RESERVE')
    meta = REASON_META.get(reason_prefix(reason))
    return meta['purpose'] if meta else None


def classify_purpose(reasons, ivt=0):
    """Collapse a mon's keep-reason list to ONE purpose (the single view).

    reasons : list returned by cull_v9.is_protected(p, ctx)
    ivt     : iv_total, used only to split an unprotected mon into TRADE vs TRANSFER.

    Empty reasons -> TRADE (decent-IV dupe worth trading) or TRANSFER (junk).
    Otherwise -> the highest-PRIORITY purpose among the reasons.
    """
    if not reasons:
        return 'TRADE' if (ivt or 0) >= 37 else 'TRANSFER'
    best = None
    for r in reasons:
        pur = _reason_purpose(r)
        if pur is None:
            continue
        if best is None or _PRIO[pur] < _PRIO[best]:
            best = pur
    return best or 'RESERVE'  # protected but unmapped reason -> conservative keep


def purpose_of(p, ctx, cull):
    """Convenience: reasons + purpose for a cull-format row `p`.

    cull is the imported cull_v9 module (passed in to avoid a hard import cycle).
    Returns (reasons_list, purpose_str).
    """
    reasons = cull.is_protected(p, ctx)
    return reasons, classify_purpose(reasons, p['iv_total'] if 'iv_total' in p.keys() else 0)
