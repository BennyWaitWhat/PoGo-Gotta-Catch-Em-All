"""Granular tag membership: turn each coarse keep reason into a SPECIFIC, self-explaining tag.

User 2026-09-02: "your labels dont make sense ... i need the reason theyre kept" and then "you have the
ability to make up to 100 tags ... im sure you can label 1st 2nd 3rd, best ul, best gl, actually ranked
ul and gl, etc. cmon."

Before this, one tag ('Variant Floor') covered 1,939 mons and said nothing useful on a tag chip, and
'Shadow Best' hid the fact that the engine keeps THREE different shadows (best IV, best GL, best UL).
Here every reason is spread into tags a player can act on, named in the user's vocabulary rather than
engine identifiers ('Last Copy', not 'dex_only_copy'; 'Safety Hold', not 'rank_unknown').

LABELS ONLY. This module derives tag membership from decisions keep_policy ALREADY made -- it reads
policy_reasons.json and never changes a keep/transfer verdict. build_tagsets asserts the Transfer pile is
untouched, and the ordinals here are computed with the SAME sort the engine uses
(-iv, -cp, uid_hex) so a tag's "#1" is the same mon the engine ranked first.
"""
import collections
import json
import math
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'system', 'scripts'))

import keep_config
from costume_forms import is_costume_form            # noqa: F401  (kept: callers rely on the import chain)
import evolvable_forms
from pvp_iv_rule import pvid, VIABILITY_MARGIN
import pattern_pools   # pattern-pooled lines: Variant ordinals run over the whole pattern pool (2026-09-08)
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS

_REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
_IV = lambda r: (r['iv_total'] or 0)
# THE engine sort. Must stay identical to keep_policy.topn or a tag's "#1" stops being the engine's #1.
_RANK = lambda r: (-_IV(r), -(r.get('cp') or 0), r['uid_hex'])

# Colours are PokemonTagColor and are valid 0-8 ONLY. 9 makes AddTag report success while the tag never
# materialises -- that cost three wrong diagnoses on 2026-09-02 (a 14-tag account cap, a name filter and a
# creation rate limit, none of which were real).
_COLOURS = 9

# ===========================================================================
# THE TAG VOCABULARY -- every tag build() can EVER emit, whether or not any mon
# qualifies for it today.
#
# WHY THIS EXISTS (D5, 2026-09-07). prune_tags.PLAN used to be derived from
# `build(...)`'s RETURN VALUE -- i.e. from the tags that happened to have >=1
# member on the day it ran. So a tag whose membership fell to zero silently
# DROPPED OUT of the push plan while its tagset file stayed on disk and
# set_db_tags_from_files kept mirroring that frozen file into auth_tag_names
# (that script consumes every .txt, PLAN or not). Result: a tag that is live on
# the phone, live in the DB mirror, has a file -- and is invisible to prune,
# which is the only thing that could ever correct it.
#
# 'Safety Hold' is the proven case: emitted 2026-09-03 for one Enamorus, pushed,
# then that mon's reasons changed to dex_only_copy/rarity/variant_floor. build()
# stopped emitting it, so build_tagsets stopped rewriting Safety_Hold.txt (it
# only writes files for tags build() RETURNS) and prune stopped managing it. On
# 2026-09-07 it looked exactly like a dead legacy tag and was nearly deleted;
# only a file-existence check saved it.
#
# So the plan is now derived from this VOCABULARY, which does not move with the
# data. Every label build() writes comes from a constant below, and build()
# asserts its own output is a subset of all_tags() before returning -- add a new
# label to build() without registering it here and the next run fails loudly
# instead of shipping another half-managed tag.
# ===========================================================================
# League CP caps: game constants, imported from cpm_table.py (single source of truth).
from cpm_table import GL_CAP, UL_CAP

VARIANT_LABELS = ('Variant #1', 'Variant #2', 'Variant #3')
VARIANT_OVERFLOW = 'Variant #4+'
SHINY_SOLE = 'Shiny - Only One'
EVOLVE_GATED = 'Evolve Gated'               # 2026-09-24: an Evolve Next / Twice promise whose promised stage the game gates
#                                             (item / task / buddy walk / time) -- the to-do list; Next / Twice = doable now.
# POWER UP / 2ND MOVE -- dust advice, never a keep reason. Rule since 2026-09-29 (user: "I only want Rank 1-5 PVP pokemon to have
# their 2nd moves unlocked" / "only want to power pokemon who are ranked in the top 100 of pvpoke" -> 200):
#   'Power Up to 1500' / 'Power Up to 2500': own-stage rank <= pvp.action_rank in that league, the stage reaches the league, CP
#     under the cap and below the best level that stays under it, the species in pvpoke's top-N META list for the league
#     (pvp.power_up_meta_top; a shadow by its '_shadow' entry); ONE per (league, stage) -- best rank, then highest level; none
#     when a copy of the stage is already at its best level; never 'Power Up to 2500' on a Great League keeper.
#   'Unlock 2nd Move': game_opportunities.second_moves (own-stage rank <= action_rank in a league it can ENTER, no move3) inside
#     the same meta list when pvp.unlock_meta_top > 0. The producers: power_ups(), second_move_ones(); every threshold from keep_config.
POWER_UP_GL, POWER_UP_UL, SECOND_MOVE = 'Power Up to 1500', 'Power Up to 2500', 'Unlock 2nd Move'
# STOP AT <species> (user 2026-09-26, "THEN WHY IS IT TAGGED FOR EVO? EVER WONDERED WHY I KEPT MAKING THAT MISTAKE?" ->
# option 1). Tags ride along through evolution, so an 'Evolve Next' Tympole promised to Palpitoad became a Palpitoad
# still wearing 'Evolve Next' and got evolved again, twice. A copy whose promised stage can itself evolve carries
# 'Stop at <that stage>' INSTEAD of its evolve tags: true before ("evolve to Palpitoad, stop there") and after ("you are
# there, stop"). The names change with the data, so they live in a small REGISTRY (every one ever emitted); one nobody
# needs is pushed empty and retire_tags deletes the shell, exactly like any other empty managed tag.
EVOLVE_ONCE, EVOLVE_TWICE = 'Evolve Once', 'Evolve Twice'   # THE evolve vocabulary (user 2026-09-29: "I either evolve once
#                                                              or evolve twice"), + EVOLVE_GATED when the game blocks it and
#                                                              'Evo Best GL' / 'Evo Best UL' beside them on a PvP comb-up
#                                                              ("I also like to see the separate PVP ones").
EVOLVE_ADVICE = os.path.join(HERE, 'system', 'analysis', 'evolve_advice.json')   # {uid: {targets, steps, gated, gate, leagues, source, tags}}
STOP_PREFIX = 'Stop at '
STOP_PREFIXES = ('Stop at ', 'Stop ')            # 'Stop X' when 'Stop at X' would pass 18 characters (no ':' -- a filename)
STOP_REGISTRY = os.path.join(HERE, 'system', 'analysis', 'stop_tags.json')   # [tag name, ...]
STOP_ASSIGN = os.path.join(HERE, 'system', 'analysis', 'stop_assign.json')   # {uid_hex: target speciesId} this cycle
EVO_BEST_GATED = 'Evo Best Gated'   # 2026-09-24: a PvP comb-up (rule 15e) the game gates -- task / buddy walk / time / an
#                                     item he holds. Its own tag: Evolve Gated's label law forbids shinies, comb-ups are not.
EVOLVE_SHINY_GATED = 'Evolve Shiny Gated'   # 2026-09-24: would be Evolve Shiny, but the game gates the evolution (item / task /
#                                             buddy walk / time) -- a to-do, not a promise. Same producer run as Evolve Shiny.
EVOLVE_SHINY = 'Evolve Shiny'   # 2026-09-12: computed by build_tagsets (refresh_evolve_shiny.compute_target) and pushed by
#                                 prune like every other tag -- one writer, one attach fewer. Was an exempt, self-pushing tag.
SHINY_OVERFLOW = 'Shiny #4+'        # the 4th+ shiny of a species: first out if the shiny cap tightens. 'Shiny #1' and
#                                     'Shiny #2-3' RETIRED 2026-09-09 -- the native Shiny chip lists every shiny.
# 'Shadow' RETIRED 2026-09-09 (user "drop shadow"): the native Shadow chip lists every shadow (240); the engine's
# 224 shadow keepers are simply the shadows not in Transfer. (It had replaced four slot tags earlier the same day.)
# 'Legendary' / 'Mythical' RETIRED 2026-09-09: the game's own Legendary (572) and Mythical (40) chips list them (the
# native Legendary chip does NOT include Ultra Beasts -- measured against the DB roster, 572 = legendaries only).
RARITY_ROSTERS = (('Ultra Beast', ULTRA_BEAST_IDS),)   # 'Paradox' retired 2026-09-23
RARITY_NATIVE = frozenset(LEGENDARY_IDS) | frozenset(MYTHICAL_IDS)   # covered by a native chip -> no tag
RARITY_OTHER = 'Rare Other'
LEAGUES = (('gl', GL_CAP, 'GL'), ('ul', UL_CAP, 'UL'))
# '%s Rank N' is the mon's OWN stage (what the Pokemod overlay prints for the mon on screen); 'Evo %s Rank N' is
# the best rank a LATER stage of its line reaches (evolve it to get there). User 2026-09-08, a 0/15/15 Raboot:
# "Why is Raboot tagged as GL rank 1 if... it isnt?" -- it is Raboot #7 / Cinderace #1, and one tag said "1".
# GATED to stages that can reach the league cap (user 2026-09-09 "drop 13 + gate"): an under-cap species pins every
# IV to L50, so its hundo ranks "#1" -- true, printed by Pokemod, and useless (UL Rank 1 sat on 352 mons, 89% hundos).
# 'Best GL' / 'Best UL' were RETIRED 2026-09-09 as labels that decided nothing; since 2026-09-23 they label a KEEP
# rule (keep_policy 15d, reasons pvp_best_gl / pvp_best_ul) and are emitted from SIMPLE, not re-derived here.
LEAGUE_TAG_FMTS = ('%s Rank 1-5', 'Evo %s Rank 1-5')   # Rank 1 + Rank 2-5 merged 2026-09-23 (user: "call it 1-5 rank")

# 'Location Card' RETIRED 2026-09-09 (same day it was merged): the native Location Background + Special Background
# chips list every holder (54 + 239 = 293 = the DB count).

# Reasons that are already specific: renamed out of engine-speak into the user's words.
SIMPLE = {
    'hundo': 'Hundo', 'nundo': 'Nundo', 'legacy': 'Legacy Moves',
    'evolve_1': 'Evolve Once', 'evolve_2': 'Evolve Twice',   # 2026-09-29: 'Evolve Next' retired -- Once says stop
    'adventure_effect': 'Adventure Effect',
    'origin': 'Traded by E+F',
    'protected': 'Never Cull',           # was 'Protected'
    'mighty': 'Never Cull',              # 2026-09-09: one member ("kinda useless") -- folded into the keep-all label
    'pvp_spread': '0-15-15',          # was 'PvP Spread' (2026-09-23): only your named trophy spreads
    # BACK 2026-09-23 as a KEEP AXIS (user: best GL + best UL of every species and species+form -> "'Best GL' +
    # 'Best UL'"). Retired 2026-09-09 as labels that decided nothing; they now label keep_policy rule 15d, so the
    # tag set equals the reason set exactly (audit_tags EXACT) and a pvp_best-only keeper is covered.
    'pvp_best_gl': 'Best GL',
    'pvp_best_ul': 'Best UL',
    'pvp_best_ml': 'Best ML',     # Master League joins 2026-09-23
    # 2026-09-24 (user: "expanded to everyone so all ul and gl get combed up"): keep rule 15e / pvp_combup.pick -- EVOLVE
    # this one: it would be a better Great / Ultra League copy of that stage than any you own. Rank-free (Evo GL/UL
    # Rank 1-5 stays the top-5 spread chip).
    'pvp_combup_gl': 'Evo Best GL',
    'pvp_combup_ul': 'Evo Best UL',
    'rank_unknown': 'Safety Hold',       # was 'Rank Unknown' -- it is a HOLD, not a rank
    'data_incomplete': 'Safety Hold',    # same meaning: kept because the data was not trustworthy
}


# RETIRED TAGS (2026-09-09, user: "I feel like I have too many tags and some are redundant" -> "drop 13 + gate",
# then "there's just one under mighty. kinda useless" -> "re-eval all the tags"). A retired name is never emitted,
# never planned, and has no tagset file; build_tagsets DELETES a stale file for it, prune_tags STRIPS every member it
# still holds on the device (never creates it), and retire_tags.py deletes the empty shell one at a time (DeleteTag is
# rate-limited to 1-3 per session and mass deletes caused collateral -- see tag_ops note 7). Re-adding a name here to
# the vocabulary is a deliberate act: the guard in all_tags() refuses a name that is both.
RETIRED_TAGS = {
    # 2026-09-29 THE FOLD (user: "fix the redundant tags? I either evolve once or evolve twice" + "I also like to see the
    # separate PVP ones"): every evolve advice is Evolve Once / Evolve Twice (by the number of evolutions to the target),
    # Evolve Gated when the game blocks it, and Evo Best GL / UL beside those on a PvP comb-up. One table: evolve_advice.json.
    'Evolve Next':        'renamed Evolve Once (2026-09-29) -- "Once" says stop, "Next" did not',
    'Stop at Mid Stage':  'folded into Evolve Once / Twice (2026-09-29): the count says where to stop',
    'Evo Best Gated':     'folded into Evolve Gated + the Evo Best GL / UL marker (2026-09-29)',
    'Evolve Shiny':       'folded into Evolve Once / Twice (2026-09-29)',
    'Evolve Shiny Gated': 'folded into Evolve Gated (2026-09-29)',
    'Evolve for Size':    'folded into Evolve Once / Twice (2026-09-29); build_tagsets writes it, no separate push',
    'Showcase':           'lived one pass (2026-09-23): the user wants the chip only on actual XXLs -- rule 7 is XXL-only again, tag XXL',
    # 2026-09-23 tag clean-up (user picks, numbered list):
    'GL Rank 1':          'merged into GL Rank 1-5',
    'GL Rank 2-5':        'merged into GL Rank 1-5',
    'UL Rank 1':          'merged into UL Rank 1-5',
    'UL Rank 2-5':        'merged into UL Rank 1-5',
    'Evo GL Rank 1':      'merged into Evo GL Rank 1-5',
    'Evo GL Rank 2-5':    'merged into Evo GL Rank 1-5',
    'Evo UL Rank 1':      'merged into Evo UL Rank 1-5',
    'Evo UL Rank 2-5':    'merged into Evo UL Rank 1-5',
    'PvP Spread':         'renamed 0-15-15; over-cap spreads are already Best GL/UL',
    'Last Copy':          'never the only reason a mon is kept; every last copy still is',
    'Paradox':            'empty; rarity is covered by the native chips',
    'Rare Other':         'empty; rarity is covered by the native chips',
    'Armored UL':         'one-shot snapshot, never recomputed',
    'Armored ML':         'one-shot snapshot, never recomputed',
    'Armored Trade':      'one-shot snapshot, never recomputed',
    'Armored Release':    'one-shot snapshot, never recomputed',
    'PvP Over Cap':       'lived one hour: over-cap keepers carry PvP Spread instead (rule 15b still keeps them)',
    'Evolve 1':           'identical set to Evolve Next',
    'Evolve 2':           'identical set to Evolve Twice',
    'XXL #1':             'XXL #1 + XXL #2 was exactly XXL',
    'XXL #2':             'XXL #1 + XXL #2 was exactly XXL',
    'Shadow Best GL':     'merged into Shadow (4 tags were 92% the same mons)',
    'Shadow Best UL':     'merged into Shadow',
    'Shadow IV #1':       'merged into Shadow',
    'Shadow IV #2':       'merged into Shadow',
    'Location Card #1-3': 'merged into Location Card (ordinal trivia on a capped axis)',
    'Location Card #4-6': 'merged into Location Card',
    # 'Best GL' / 'Best UL' UN-RETIRED 2026-09-23: now the labels of keep rule 15d (SIMPLE above).
    'GL IV':              'the GL Rank / Evo GL Rank tags say why a PvP keeper is kept',
    'UL IV':              'the UL Rank / Evo UL Rank tags say why a PvP keeper is kept',
    'Mighty':             'one member; the mon is still kept (rule 11) and labelled Never Cull',
    # 2026-09-09 #2 (user: "are any of the tags redundant with the in-game native filters?"): yes, these six.
    'Legendary':          'native Legendary chip (572) lists them; Transfer marks the fodder',
    'Mythical':           'native Mythical chip (40)',
    'Location Card':      'native Location Background + Special Background chips (293)',
    'Event':              'native Event chip + the two Background chips',
    'Shiny #1':           'native Shiny chip (1,481); Shiny - Only One and Shiny #4+ stay',
    'Shiny #2-3':         'native Shiny chip',
    'Shadow':             'native Shadow chip (240); the kept 224 are the shadows not in Transfer',
}

# Keep reasons the GAME already shows with a filter chip: a kept mon whose only reasons are these needs no tag of
# ours to be explained in-game (build_tagsets coverage treats the chip as the label). 2026-09-09.
NATIVE_COVERED_REASONS = frozenset({'rarity', 'shiny', 'location_card', 'adventure_effect', 'shadow_best',
                                    'favorite',    # the in-game star + Favorite filter is the label (2026-09-17)
                                    'shiny_ladder',    # a shiny held to evolve: the Shiny chip + the Evolve Shiny tag
                                    'fused',           # held inside a fused Kyurem: the game shows it there (2026-09-26)
                                    'dex_only_copy'})  # the ONLY copy of a form explains itself in the bag (2026-09-24: the shadow
                                                       # rank floor left a lone shadow Vibrava kept for that alone; the 'Last Copy'
                                                       # chip stays retired, user 2026-09-23)


def stop_tags():
    """RETIRED 2026-09-29 (folded into Evolve Once / Twice): the vocabulary holds no Stop tag any more. The names ever
    emitted (STOP_REGISTRY + any Stop_*.txt still on disk) are in RETIRED_TAGS so prune strips and retire deletes them."""
    return frozenset()


def _retired_stops():
    out = set()
    try:
        out |= {t for t in json.load(open(STOP_REGISTRY, encoding='utf-8')) if t.startswith(STOP_PREFIXES)}
    except (OSError, ValueError):
        pass
    try:
        out |= {f[:-4].replace('_', ' ') for f in os.listdir(os.path.join(HERE, 'system', 'analysis', 'tagsets'))
                if f.endswith('.txt') and f[:-4].replace('_', ' ').startswith(STOP_PREFIXES)}
    except OSError:
        pass
    return out


def all_tags():
    """Every tag build() can emit. DERIVED from the same constants build() uses, so the two cannot drift."""
    t = set(VARIANT_LABELS) | {VARIANT_OVERFLOW, SHINY_SOLE, SHINY_OVERFLOW, EVOLVE_GATED, POWER_UP_GL, POWER_UP_UL, SECOND_MOVE}
    t |= {nm for nm, _ in RARITY_ROSTERS}
    for _lg, _cap, lbl in LEAGUES:
        t |= {fmt % lbl for fmt in LEAGUE_TAG_FMTS}
    t |= set(SIMPLE.values())
    _both = t & set(RETIRED_TAGS)
    if _both:
        raise SystemExit('granular_tags: %s is in the vocabulary AND in RETIRED_TAGS -- pick one.' % sorted(_both))
    return frozenset(t)


def stage_ranks(r, league):
    """{stage_speciesId: rank} parsed from <league>_chain_ranks ('raboot:7(99.82%);cinderace:1(100.00%)').
    rank_cache writes the mon's OWN stage first, then every later stage of its line."""
    out = {}
    for part in (r.get(league + '_chain_ranks') or '').split(';'):
        part = part.strip()
        if ':' not in part:
            continue
        sid, rest = part.split(':', 1)
        try:
            out[sid.strip()] = int(rest.split('(')[0])
        except ValueError:
            continue
    return out


_DEX = None


def _dex_of():
    """speciesId -> pokedex number, from the game master (cached)."""
    global _DEX
    if _DEX is None:
        gm = json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))
        _DEX = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
    return _DEX


_BS = None
from pvp_iv_rule import fits as pvp_fits, cp_at as _pvp_cp_at                  # ONE definition, shared with the
#                          keep rule (2026-09-19): the label and the keep cannot disagree about who can enter a league.


def _basestats():
    global _BS
    if _BS is None:
        gm = json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))
        _BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
    return _BS


def cp_at_stage(r, sid):
    """This specimen's CP if it were that stage, at the level it is now. None when the stage is unknown."""
    return _pvp_cp_at(sid, r.get('iv_atk'), r.get('iv_def'), r.get('iv_sta'), r.get('level'), _basestats())


def own_and_evo_rank(r, league, viable=None, cap=None):
    """(own_stage_rank, best_later_stage_rank) for 'gl' / 'ul' -- either may be None.
    `viable(sid) -> bool` (optional) drops stages that cannot reach the league cap: an under-cap stage pins
    every IV to L50 and ranks its hundo "#1", which is true and useless as a label (user 2026-09-09)."""
    ranks = stage_ranks(r, league)
    own_sid = pvid(r['species_name'], r.get('form') or 0)
    own = ranks.get(own_sid)
    if own is not None and viable is not None and not viable(own_sid):
        own = None
    # ALREADY OVER THE CAP -> it can never enter that league, because CP only goes up (user 2026-09-19: "some even
    # over the cap"). Three tags were live on mons that cannot play: Gardevoir cp2494 and Charizard cp2500 in Great.
    if own is not None and not pvp_fits(r, own_sid, cap, _basestats()):
        own = None
    # A LATER-STAGE rank is an instruction to EVOLVE, so it must be true for the specimen on screen (2026-09-17):
    # a form that cannot evolve never reaches one (PikachuGofest2026CapYellow was tagged "Evo GL Rank 1" for Raichu),
    # and a gender-locked line only reaches its own branch (a male Snorunt never becomes Froslass). Both gates are
    # the ones the Evolve labels already use -- keep_policy._can_evo and reach().
    if evolvable_forms.row_can_evolve(r) is False:
        return own, None
    _dex = _dex_of()
    # ... and the same for the EVOLVED copy: evolving does not change the level, so if this mon would already be over
    # the cap at that stage it can never enter there either (Wailmer lv27 -> a 1620 CP Wailord, no way back down).
    def _fits(k):
        return pvp_fits(r, k, cap, _basestats())
    later = [v for k, v in ranks.items()
             if k != own_sid and (viable is None or viable(k)) and _fits(k)
             and evolvable_forms.gender_allows(r['pokemon_id'], r.get('gender'), _dex.get(k))]
    return own, (min(later) if later else None)


def is_stop_tag(name):
    return name.startswith(STOP_PREFIXES)


for _t in _retired_stops():
    RETIRED_TAGS.setdefault(_t, 'folded into Evolve Once / Twice (2026-09-29)')

EVOLVE_TAGS = (EVOLVE_ONCE, EVOLVE_TWICE, EVOLVE_GATED, 'Evo Best GL', 'Evo Best UL')   # every evolve tag of the vocabulary
_ADVICE_REASONS = {'evolve_1', 'evolve_2', 'pvp_combup_gl', 'pvp_combup_ul'}              # reasons the table labels, not SIMPLE
_EVO_ADJ = None
LAST_ADVICE = {}                                          # the table build() produced last -- build_tagsets writes it out


def _evo_adj():
    """speciesId -> its evolutions (pvpoke families), for counting the steps to a target."""
    global _EVO_ADJ
    if _EVO_ADJ is None:
        _EVO_ADJ = {q['speciesId']: list((q.get('family') or {}).get('evolutions') or [])
                    for q in json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))['pokemon']}
    return _EVO_ADJ


def path_between(src, dst):
    """The stages from `src` (exclusive) to `dst` (inclusive), by the pvpoke families; [] when they show no way."""
    adj = _evo_adj()
    # an exact id first; a FORM-suffixed id ('gourgeist_average' for 'gourgeist', 'meowstic_female') only at an '_'
    # boundary -- a plain prefix read 'pidgeotto' as 'pidgeot' and 'pawmo' as 'pawmot' (audit review 2026-09-29)
    same = lambda e: bool(dst) and (e.startswith(dst + '_') or dst.startswith(e + '_'))
    front, seen = [(src, [])], {src}
    for _ in (1, 2, 3):
        nxt, fuzzy = [], None
        for s, p in front:
            for e in adj.get(s, ()):
                if e == dst:
                    return p + [e]
                if fuzzy is None and same(e):
                    fuzzy = p + [e]
                if e not in seen:
                    seen.add(e); nxt.append((e, p + [e]))
        if fuzzy:
            return fuzzy
        front = nxt
    return []


def steps_between(src, dst):
    """Evolutions from stage `src` to stage `dst` (1 or 2 in GO), None when the families show no way."""
    return len(path_between(src, dst)) or None


def evolve_advice(kept, reasons, pile):
    """ONE TABLE for every evolve advice (2026-09-29): {uid: {targets, steps, gated, gate, leagues, source, tags}}.
    Producers, in priority order when a copy is in several: the engine's promises (reasons evolve_1 / evolve_2 +
    promises.json), the PvP comb-ups (pvp_combup_labels.json, status now / gated; hold = no tag), the shiny upgrades
    (refresh_evolve_shiny.compute_target) and the showcase picks (sync_evolve_size.picks). A shiny or size rule that
    cannot run is a HARD stop -- silently dropping its members would strip their tags under the empty-set contract.
    Tags: steps 1 -> Evolve Once, 2 -> Evolve Twice; a game-gated target -> Evolve Gated instead; a comb-up also wears
    Evo Best GL / UL. Never a pile mon, never a fused component."""
    A = os.path.join(HERE, 'system', 'analysis')
    load = lambda n: json.load(open(os.path.join(A, n), encoding='utf-8')) if os.path.exists(os.path.join(A, n)) else {}
    prom, cul = load('promises.json'), load('pvp_combup_labels.json')
    kept_by = {r['uid_hex']: r for r in kept if not keep_config.is_fused_component(r)}
    import sys as _sys
    for _p in (HERE, os.path.join(HERE, 'system', 'scripts')):
        if _p not in _sys.path:
            _sys.path.insert(0, _p)
    from refresh_evolve_shiny import compute_target       # raises on a broken rule: fail loud, never an empty list
    _sh_detail, _sh_gated = {}, {}
    _sh = compute_target(detail=_sh_detail, gated=_sh_gated)
    import sync_evolve_size
    _sz_want, _sz_big = sync_evolve_size.picks(set(pile))
    _sz_best = {}
    for e in _sz_big:                                     # one pick per mon: the branch that scores highest
        if e['uid'] not in _sz_best or (e['score_after'] or 0) > (_sz_best[e['uid']]['score_after'] or 0):
            _sz_best[e['uid']] = e
    pad = lambda u: format(int(u, 16), '016x')
    out = {}

    def put(u, targets, source, leagues=(), gated=None):
        if u not in kept_by or not targets:
            return
        e = out.get(u)
        if e is None:
            e = out[u] = {'targets': [], 'steps': None, 'gated': False, 'gate': None, 'leagues': [], 'source': source, 'tags': []}
            r = kept_by[u]
            src = pvid(r['species_name'], r.get('form') or 0)
            e['targets'] = list(targets)         # the producer's own list (a gender split like oinkologne/oinkologne_female stays a split)
            paths = {t: path_between(src, t) for t in targets}
            st = [len(p) for p in paths.values() if p]
            e['steps'] = min(st) if st else (2 if 'evolve_2' in (reasons.get(u) or ()) else 1)
            # a gate on ANY stage of the way counts (Happiny -> Chansey -> Blissey is gated at the Chansey step)
            gate = [g for t in targets for s in (paths[t] or [t]) for g in (evolvable_forms.gate_reason(s) or [])]
            if gated is not None:
                e['gated'] = bool(gated) or bool(gate)
            else:
                e['gated'] = bool(gate)
            e['gate'] = ', '.join(dict.fromkeys(gate)) or (gated if isinstance(gated, str) else None)
        for lg in leagues:
            if lg not in e['leagues']:
                e['leagues'].append(lg)
    for u, r in kept_by.items():                          # 1. the engine's promises
        rs = reasons.get(u) or ()
        if 'evolve_1' in rs or 'evolve_2' in rs:
            put(u, prom.get(u) or [], 'promise')
    for u, v in cul.items():                              # 2. the PvP comb-ups
        if v.get('status') in ('now', 'gated') and v.get('target'):
            put(u, [v['target']], 'combup', leagues=[l for l in v.get('leagues') or [] if l in ('gl', 'ul')],
                gated=(v.get('status') == 'gated'))
    for u, t in _sh_detail.items():                       # 3. the shiny upgrades
        put(pad(u), [t] if isinstance(t, str) else list(t or []), 'shiny')
    for u, v in _sh_gated.items():
        put(pad(u), [v.get('target')] if v.get('target') else [], 'shiny', gated=v.get('need') or True)
    # a showcase pick is an evolution promise too now (bucket 8 under the label law, audit_labels 2026-09-29): never a copy
    # another bucket will not give up -- the last copy of its form, a trophy, protected, legacy, Mighty, Adventure Effect,
    # a card holder, a legendary, a best shadow, a fused component. The XXL badge itself carries through (its point).
    _SIZE_BLOCK = {'protected', 'legacy', 'location_card', 'mighty', 'dex_only_copy', 'rarity', 'adventure_effect',
                   'shadow_best', 'hundo', 'nundo', 'fused'}
    for u, e in _sz_best.items():                         # 4. the showcase picks
        if _SIZE_BLOCK & set(reasons.get(pad(u)) or ()):
            continue
        put(pad(u), [e['target']], 'size')
    for u, e in out.items():
        e['tags'] = [EVOLVE_GATED if e['gated'] else (EVOLVE_TWICE if e['steps'] == 2 else EVOLVE_ONCE)]
        e['tags'] += ['Evo Best %s' % lg.upper() for lg in e['leagues']]
    return out


def evolve_tags(advice):
    """{tag: set(uid)} from the table."""
    T = collections.defaultdict(set)
    for u, e in advice.items():
        for t in e['tags']:
            T[t].add(u)
    return T

_META = {}


def meta_top(lg, n=None):
    """speciesIds in pvpoke's top-N META ranking for the league (system/analysis/pvpoke_rankings/rankings-<cap>.json,
    sorted by score; refreshed with the game master). N defaults to keep_config pvp.power_up_meta_top; 0 = every species."""
    n = keep_config.pvp('power_up_meta_top') if n is None else n
    if lg not in _META:
        try:
            lst = json.load(open(os.path.join(HERE, 'system', 'analysis', 'pvpoke_rankings',
                                              'rankings-%d.json' % {'gl': GL_CAP, 'ul': UL_CAP}[lg]), encoding='utf-8'))
            _META[lg] = [x['speciesId'] for x in sorted(lst, key=lambda x: -(x.get('score') or 0))]
            if len(_META[lg]) < 300:                      # an empty / truncated list would silently block every tag
                _META[lg] = None
        except (OSError, ValueError, KeyError, TypeError):
            _META[lg] = None
    if _META[lg] is None or not n:
        return None                                        # unknown list: no meta gate (never silently empty)
    return frozenset(_META[lg][:n])


def meta_ok(r, own, lg, n=None):
    """Is this copy's species in the league's top-N meta? A shadow copy is judged as its '<id>_shadow' entry."""
    top = meta_top(lg, n)
    if top is None:
        return True
    if (r.get('fresh_alignment') or 0) == 1:
        return (own + '_shadow') in top or own in top
    return own in top


def power_ups(kept, reasons):
    """{'gl': set, 'ul': set} of uids for 'Power Up GL' / 'Power Up UL' (rule at POWER_UP_GL above), plus
    {(uid, league): (level now, best level)} for the report. `kept` = in-bag rows minus the pile."""
    from pvp_iv_rule import pvid, maxcp, true_level, _cp_at_index, VIABILITY_MARGIN
    from cpm_table import MAX_LEVEL_IDX
    BS = _basestats()
    # USER 2026-09-29: "I also only want to power pokemon who are ranked in the top 100 of pvpoke" -- an own-stage rank 1-N
    # (keep_config pvp.action_rank) copy of a species inside pvpoke's top-N META ranking for that league (power_up_meta_top),
    # under the cap and below the best level that stays under it; ONE per (league, stage): the best rank, then the highest
    # level (five Azumarills do not need five power-ups). A twin already at its best level satisfies the stage.
    _AR = keep_config.pvp('action_rank')
    cand = collections.defaultdict(list)        # (league, stage) -> [(rank, level now, best level, uid)]
    for r in kept:
        if keep_config.is_fused_component(r):
            continue
        own = pvid(r['species_name'], r.get('form') or 0)
        b = BS.get(own)
        if not b or r.get('iv_atk') is None:
            continue
        for lg, cap in (('gl', GL_CAP), ('ul', UL_CAP)):
            if r.get(lg + '_stage') != own or (r.get(lg + '_rank') or 9999) > _AR:
                continue
            if not maxcp(own, BS) > cap + VIABILITY_MARGIN or (r.get('cp') or 0) > cap:
                continue
            if not meta_ok(r, own, lg):
                continue
            if lg == 'ul' and ('pvp_best_gl' in (reasons.get(r['uid_hex']) or ())
                               or (r.get('gl_stage') == own and (r.get('gl_rank') or 9999) <= keep_config.pvp('ready_rank') and (r.get('cp') or 0) <= GL_CAP)):
                continue                        # a Great League keeper: powering it for Ultra would burn it
            lv = true_level(r, BS)
            best = max((i for i in range(MAX_LEVEL_IDX + 1)
                        if _cp_at_index(b, r['iv_atk'], r['iv_def'], r['iv_sta'], i) <= cap), default=None)
            if lv is None or best is None:
                continue
            cand[(lg, own)].append((r[lg + '_rank'], lv, 1 + best / 2.0, r['uid_hex']))
    out, detail = {'gl': set(), 'ul': set()}, {}
    for (lg, _own), lst in cand.items():
        if any(lv >= bl for _k, lv, bl, _u in lst):
            continue                            # a copy of this stage is already at its best level
        _k, lv, bl, u = min(lst, key=lambda x: (x[0], -x[1], x[3]))   # best rank, then closest to done
        out[lg].add(u)
        detail[(u, lg)] = (lv, bl)
    return out, detail


def second_move_ones(kept):
    """uids for 'Unlock 2nd Move': own-stage rank 1-N (keep_config pvp.action_rank; user 2026-09-29: "I only want Rank 1-5
    PVP pokemon to have their 2nd moves unlocked") in a league it can enter, no second charged move."""
    import game_opportunities
    live = {r['uid_hex']: r for r in kept if not keep_config.is_fused_component(r)}
    _n = keep_config.pvp('unlock_meta_top')
    return {x['uid'] for x in game_opportunities.second_moves(list(live.values()))
            if x['rank'] <= keep_config.pvp('action_rank')
            and (not _n or meta_ok(live[x['uid']], pvid(live[x['uid']]['species_name'], live[x['uid']].get('form') or 0),
                                   {'Great': 'gl', 'Ultra': 'ul'}[x['league']], _n))}


def _base_form_map(rows):
    """keep_policy's form-0 normalisation, including its regional guard."""
    c = collections.defaultdict(collections.Counter)
    for r in rows:
        fo = r.get('form') or 0
        reg = ((r.get('form_region') or '')).strip().lower()
        if fo and reg in ('', 'normal', 'kantonian', 'none', 'null') \
                and not any(x in pvid(r['species_name'], fo) for x in _REGSUF) and not is_costume_form(fo):   # 2026-09-23
            c[r['pokemon_id']][fo] += 1
    return {p: m.most_common(1)[0][0] for p, m in c.items() if len(m) == 1}


def _maxcp_fn():
    """L50 hundo CP per speciesId, for the league-viability gate."""
    # was: a REGEX SCRAPE of compute_all_ranks.py's source for its CPM literal. That is
    # duplication with extra steps and breaks silently if the literal moves; cpm_table.py
    # is the single source of truth (defect D4).
    from cpm_table import CPM as cpm, MAX_LEVEL_IDX
    gm = json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))
    bs = {p['speciesId']: p['baseStats'] for p in gm['pokemon']}

    def maxcp(sid):
        b = bs.get(sid or '')
        if not b:
            return 0
        return max(10, math.floor((b['atk'] + 15) * math.sqrt(b['def'] + 15)
                                  * math.sqrt(b['hp'] + 15) * cpm[MAX_LEVEL_IDX] ** 2 / 10))
    return maxcp


def build(rows, pile, reasons):
    """rows: in_bag dicts. pile: set of Transfer uid_hex. reasons: policy_reasons.json.

    Returns {tag_name: set(uid_hex)} covering every KEPT mon at least once."""
    # Callers pass sqlite3.Row (build_tagsets) or dicts (the CLI), and build_tagsets' projection is
    # NARROWED -- it has no fresh_shiny. A missing column would read as "not shiny" and silently mis-tag
    # 1,479 mons, so we re-read SELECT * ourselves rather than trust whatever the caller happened to
    # select. (Same reasoning as the "SELECT * IS DELIBERATE" notes in the audits.)
    rows = [r if isinstance(r, dict) else keep_config.row_dict(r) for r in rows]
    if rows and 'fresh_shiny' not in rows[0]:
        _c = sqlite3.connect(os.path.join(HERE, 'pokemon.db'))
        _c.row_factory = sqlite3.Row
        rows = [keep_config.row_dict(r) for r in _c.execute('SELECT * FROM pokemon WHERE in_bag=1')]
        _c.close()
    base = _base_form_map(rows)
    cf = lambda r: (base.get(r['pokemon_id'], r.get('form') or 0)
                    if not (r.get('form') or 0) else r.get('form'))
    kept = [r for r in rows if r['uid_hex'] not in pile]
    kept_uids = {r['uid_hex'] for r in kept}
    has = lambda u, x: x in (reasons.get(u) or [])
    T = collections.defaultdict(set)

    def ordinal(pool, keyfn, labels, overflow):
        g = collections.defaultdict(list)
        for r in pool:
            g[keyfn(r)].append(r)
        for lst in g.values():
            for i, r in enumerate(sorted(lst, key=_RANK)):
                T[labels[i] if i < len(labels) else overflow].add(r['uid_hex'])

    # --- variant floor: WHERE it sits, not just that it qualified (was one 1,939-member lump) ---
    # a PATTERN-POOLED line (Scatterbug/Spewpa/Vivillon) is one pool per pattern across the whole line, so its
    # ordinals must run over that pool -- the engine's cap did (keep_policy._stage_key via pattern_pools).
    ordinal([r for r in kept if has(r['uid_hex'], 'variant_floor')],
            lambda r: pattern_pools.pool_key(r['pokemon_id'], r['species_name'], r.get('form') or 0, r.get('gender'))
            or (r['pokemon_id'], cf(r), evolvable_forms.gender_key(r['pokemon_id'], r.get('gender'))),   # per gender when the look differs (2026-09-23)
            list(VARIANT_LABELS), VARIANT_OVERFLOW)

    # --- shiny: a sole shiny of a species is a different thing from the 4th dupe ---
    shg = collections.defaultdict(list)
    for r in kept:
        if r['fresh_shiny'] and not keep_config.is_fused_component(r):   # (2026-09-26) fused components hold no ladder slot
            shg[(r['pokemon_id'], cf(r))].append(r)
    for lst in shg.values():
        s = sorted(lst, key=_RANK)
        if len(s) == 1:
            T[SHINY_SOLE].add(s[0]['uid_hex'])
        else:
            for i, r in enumerate(s):
                if i >= 3:
                    T[SHINY_OVERFLOW].add(r['uid_hex'])   # #1..#3: the native Shiny chip is the label (2026-09-09)

    # --- shadow: RETIRED 2026-09-09 -- the native Shadow chip is the label; Transfer marks the fodder.

    # --- rarity: Legendary / Mythical have a native chip (no tag); Ultra Beast / Paradox / other still need one ---
    for r in kept:
        if has(r['uid_hex'], 'rarity'):
            if r['pokemon_id'] in RARITY_NATIVE:
                continue
            for nm, s in RARITY_ROSTERS:
                if r['pokemon_id'] in s:
                    T[nm].add(r['uid_hex'])
                    break                   # 'Paradox' / 'Rare Other' retired 2026-09-23 -- 'rarity' is native-covered

    # --- PvP: "my best Machamp for Great League" and "a top-5 IV spread" are DIFFERENT questions.
    # ('Best GL' / 'Best UL' are no longer built here: they follow keep_policy's pvp_best_gl / pvp_best_ul reasons.)
    # '%s Rank 1' / '%s Rank 2-5' are NOT gated as of 2026-09-08 (user: "pokemod labels"): Pokemod's overlay
    # shows every stage's stat-product rank at the L50 ceiling, under-cap stages included, and the user reads
    # his bag with that tool. rank_cache stores the viability-AWARE best (a stage that reaches the cap wins;
    # only a chain that never reaches it falls back to the degenerate rank), so this labels exactly what
    # Pokemod prints. Labels only -- keep decisions are unchanged (measured: +658 chips, 0 pile moves).
    # OWN STAGE vs EVOLVED STAGE (2026-09-08). gl_rank/ul_rank is the chain's best VIABLE stage -- for a 0/15/15
    # Raboot that is Cinderace #1 while Raboot itself is #7, and the overlay the user reads shows #7. So:
    #   '%s Rank 1' / '%s Rank 2-5'         = the mon's OWN stage rank (what Pokemod prints for this mon)
    #   'Evo %s Rank 1' / 'Evo %s Rank 2-5' = the best rank a LATER stage of its line reaches (evolve for it)
    # Both read the per-stage chain rank_cache already stores; nothing is gated (Pokemod labels).
    # GATED (2026-09-09): a stage earns a rank label only if it can reach the league cap (L50-hundo CP above
    # cap + keep_config pvp.viability_margin -- the same test pvp_iv_rule.qualifies uses for the keep decision).
    maxcp = _maxcp_fn()
    for league, cap, lbl in LEAGUES:
        _viable = (lambda _cap: (lambda sid: bool(sid) and maxcp(sid) > _cap + VIABILITY_MARGIN))(cap)
        for r in kept:
            if keep_config.is_fused_component(r):
                continue                              # (2026-09-26) fused components hold no ladder slot
            own, evo = own_and_evo_rank(r, league, viable=_viable, cap=cap)
            if own is not None and own <= 5:
                T[LEAGUE_TAG_FMTS[0] % lbl].add(r['uid_hex'])
            if evo is not None and evo <= 5:
                T[LEAGUE_TAG_FMTS[1] % lbl].add(r['uid_hex'])   # evolve it for this rank (user: "so i know to do it")

    # An over-cap rank 1-5 keeper gets NO extra chip (user 2026-09-23: "why are they even tagged"). Best GL/UL is
    # USABLE-ONLY since 2026-09-23 (keep_policy 15d: the best copy that can ENTER the league), so an over-cap spread is
    # no longer that league's Best -- it keeps its rule-15b keep and is labelled by whatever else it carries (Best of
    # the other league, a UL Rank chip, 0-15-15, Variant ...). build_tagsets' coverage check still refuses the sync if
    # one carries NO tag at all, and audit_tags_membership refuses it if a pvp_iv_rule GL/UL keeper carries no chip of
    # that league -- the safe direction; the question gets asked then (measured 2026-09-23: 2 such, an Eevee and a
    # Clamperl whose evolved CP is over 1500).

    # --- location card: RETIRED 2026-09-09 -- the native Location/Special Background chips are the label. XXL is
    # covered by the legacy 'XXL' tag build_tagsets writes (top-2 by showcase score, which no search term gives).

    # --- reasons that are already specific: renamed out of engine-speak (SIMPLE, module scope) ---
    for r in kept:
        for rs in (reasons.get(r['uid_hex']) or []):
            if rs in SIMPLE and rs not in _ADVICE_REASONS:   # evolve labels come from the advice table below
                T[SIMPLE[rs]].add(r['uid_hex'])
    # BEST ML ONLY WHERE IT IS NOT A HUNDO (user 2026-09-23). A hundo is always its species' ML best, so on a hundo
    # the chip said nothing the Hundo chip does not. Keep decisions are unchanged -- this is a label.
    T[SIMPLE['pvp_best_ml']] -= {u for u in T[SIMPLE['pvp_best_ml']] if 'hundo' in (reasons.get(u) or ())}
    # --- EVOLVE ADVICE, ONE TABLE (2026-09-29, see evolve_advice above) ---
    global LAST_ADVICE
    LAST_ADVICE = evolve_advice(kept, reasons, pile)
    for _t, _us in evolve_tags(LAST_ADVICE).items():
        T[_t] |= _us
    # LEGACY MOVES IS A FACT, NOT A KEEP REASON (2026-09-17). The legacy keep axis is now capped (best 10 per species,
    # user "Best 10"), so a copy past the cap that another axis keeps (shiny, dex copy ...) lost its 'legacy' reason --
    # but it still HAS legacy moves, and a label must be true for the mon on screen. Tag every kept legacy mover.
    try:
        _la = json.load(open(os.path.join(HERE, 'legacy_accurate.json'), encoding='utf-8'))
        _leg = {e['uid_hex'] if isinstance(e, dict) else e for e in _la} if isinstance(_la, list) else set(_la)
        T[SIMPLE['legacy']].update(kept_uids & _leg)
    except (OSError, ValueError) as _e:
        raise SystemExit('granular_tags: legacy_accurate.json unreadable (%s) -- Legacy Moves cannot be built' % _e)

    # --- Power Up 1500/2500 + Unlock 2nd Move: dust advice on the rank 1-N meta copies -- see POWER_UP_GL above ---
    _pu, _pud = power_ups(kept, reasons)
    T[POWER_UP_GL] |= _pu['gl']
    T[POWER_UP_UL] |= _pu['ul']
    T[SECOND_MOVE] |= second_move_ones(kept)

    # VOCABULARY GUARD (D5). Every label emitted here must be a REGISTERED tag, because
    # prune_tags.PLAN is built from all_tags() -- not from this return value. An unregistered
    # label would become half-managed exactly as 'Safety Hold' did: build_tagsets writes its file,
    # set_db_tags_from_files mirrors it into auth_tag_names, and prune can never correct it.
    _unknown = set(T) - all_tags()
    if _unknown:
        raise SystemExit('granular_tags.build: emitted %d tag(s) that are NOT in the vocabulary: %s. '
                         'Register the label in the constants at the top of granular_tags.py -- an '
                         'unregistered tag is invisible to prune_tags.PLAN.'
                         % (len(_unknown), sorted(_unknown)))
    return dict(T)


# ===========================================================================
# THE TAG REGISTRY -- the single answer to "is this tag managed, exempt, or dead?"
#
# Three populations of tag exist on the phone, and before 2026-09-07 telling them
# apart took a forensic investigation:
#   1. MANAGED  -- prune_tags pushes the tagset file to the device and verifies
#                  set equality. LEGACY_TAGS + all_tags().
#   2. EXEMPT   -- a real, live tag with a tagset file that prune deliberately
#                  does NOT push, because something else owns it. Listed in
#                  EXEMPT_TAGSETS below WITH ITS OWNER. Never a silent omission.
#   3. ORPHAN   -- a tagset file that is neither. That is a BUG (someone added a
#                  tag emitter without registering it, or retired a tag and left
#                  the file), and audit_registry() raises rather than letting the
#                  next operator guess. It is also the state 'Safety Hold' was in.
# ===========================================================================

# The 11 ORIGINAL tags keep their historical filenames and colours: they already exist on the device
# and renaming one would ORPHAN ITS MEMBERS. (Colours are PokemonTagColor, 0-8 ONLY -- see _COLOURS.)
LEGACY_TAGS = {
    # 'GL IV' / 'UL IV' / 'Evolve 1' / 'Evolve 2' RETIRED 2026-09-09 (see RETIRED_TAGS) -- 7 remain.
    'XXL':           ('XXL.txt',           5),   # the 2 highest showcase points per species (cosmetics fold), XXL only (2026-09-23)
    'Hundo':         ('Hundo.txt',         1),
    'Nundo':         ('Nundo.txt',         2),
    'Traded by E+F': ('Traded_by_E+F.txt', 7),
    'Legacy Moves':  ('Legacy_Moves.txt',  3),
    'Transfer':      ('Transfer.txt',      1),
}

# Tagset files that legitimately exist WITHOUT a prune_tags.PLAN entry. Every entry names the script
# that owns the file, so a live-but-unmanaged tag is distinguishable from a dead one AT A GLANCE.
# Adding a file here is a deliberate act; leaving one out makes audit_registry() fail loudly.
EXEMPT_TAGSETS = {
    '6_Transfer.txt': dict(
        tag=None, owner='keep_policy.py',
        why="the raw TRANSFER pile, not a server tag. build_tagsets reads it and re-emits it as "
            "Transfer.txt, which IS managed. set_db_tags_from_files skips it by name for the same "
            "reason. It must never be pushed: there is no 6_Transfer tag on the device."),
    # 'Evolve_Shiny.txt' left the exempt list 2026-09-12: build_tagsets writes it, prune pushes it (EVOLVE_SHINY above).
    # 'Armored_*.txt' (four one-shot hand-pushed snapshots) RETIRED 2026-09-23 -- see RETIRED_TAGS.
}

# Server tag names that are LIVE but not pushed by prune_tags. Derived from EXEMPT_TAGSETS so the two
# cannot disagree. reconcile_tags' managed-set allowlist should be (PLAN | EXEMPT_TAGS).
EXEMPT_TAGS = frozenset(v['tag'] for v in EXEMPT_TAGSETS.values() if v['tag'])


def tagset_dir():
    return os.path.join(HERE, 'system', 'analysis', 'tagsets')


def registry():
    """{tag: (filename, colour)} -- THE push plan. prune_tags.PLAN is exactly this.

    DERIVED, never hand-listed: LEGACY_TAGS (historical filenames/colours, which must not move)
    plus every tag in all_tags(). Deriving from all_tags() rather than from a build() RETURN VALUE
    is the D5 fix -- see the vocabulary comment above. A tag with zero members today keeps its plan
    entry, so it stays managed instead of silently falling out of the push.

    Colours are PokemonTagColor and are valid 0-8 ONLY. 9 makes AddTag report success while the tag
    never materialises (three wrong diagnoses on 2026-09-02 before that was found). Because the index
    now runs over the VOCABULARY, a derived tag's colour is stable across runs; it used to shift
    whenever some unrelated tag gained or lost its last member. tag_ops.create_tag returns early for
    a tag that already exists, so this colour only ever applies to a tag being created for the
    first time -- existing tags keep the colour they were made with.
    """
    plan = dict(LEGACY_TAGS)
    for i, t in enumerate(sorted(all_tags())):
        if t not in plan:
            plan[t] = (filename(t), i % _COLOURS)
    for t, (fn, col) in plan.items():
        if not (0 <= int(col) <= 8):
            raise SystemExit('granular_tags.registry: tag %r got colour %r -- PokemonTagColor is '
                             '0-8. Colour 9 makes AddTag return ok while the tag never appears.'
                             % (t, col))
    return plan


def plan(tags=None):
    """Back-compat shim. Callers wanting the push plan should use registry()."""
    return registry() if tags is None else {t: (filename(t), i % _COLOURS)
                                            for i, t in enumerate(sorted(tags))}


def audit_registry(plan_map=None, td=None, strict=True):
    """Cross-check the registry against the tagset files ON DISK.

    Returns (orphan_files, planned_without_file). ORPHANS ARE FATAL when strict: a .txt with no PLAN
    entry and no EXEMPT_TAGSETS entry is a tag nothing manages -- it still gets mirrored into
    auth_tag_names by set_db_tags_from_files (which consumes every .txt regardless of PLAN) and still
    shows on the phone, so it looks alive while being uncorrectable. That is exactly the state
    'Safety Hold' sat in for four days, and the next operator read it as a dead legacy tag.

    A PLAN entry with NO file is NOT an error -- 'Paradox' and 'Rare Other' are registered and simply
    have no qualifying mon today, and build_tagsets only writes files for tags build() emits. It is
    returned so the caller can SKIP those tags: pushing want=<empty> for a missing file would strip
    every member off the device, which is a membership change nobody asked for.
    """
    plan_map = registry() if plan_map is None else plan_map
    td = td or tagset_dir()
    on_disk = {fn for fn in os.listdir(td) if fn.endswith('.txt') and not fn.startswith('_')}
    planned = {fn for fn, _ in plan_map.values()}
    orphans = sorted(on_disk - planned - set(EXEMPT_TAGSETS))
    missing = sorted(fn for fn in planned if fn not in on_disk)
    if orphans and strict:
        raise SystemExit(
            'granular_tags.audit_registry: %d tagset file(s) exist with NO plan entry and NO explicit '
            'exemption: %s\n'
            '  A file in that state is half-managed: set_db_tags_from_files mirrors it into '
            'auth_tag_names and it shows on the phone, but prune_tags cannot correct it and the next '
            'operator cannot tell it from a dead tag (this is D5, the Safety Hold defect).\n'
            '  FIX ONE OF:\n'
            '   (a) the tag is real and this engine owns it -> register the label in the VOCABULARY '
            'constants at the top of granular_tags.py so registry() picks it up;\n'
            '   (b) another script owns it -> add the filename to granular_tags.EXEMPT_TAGSETS with '
            'its owner and the reason;\n'
            '   (c) it is genuinely dead -> retire it deliberately (NOT by deleting the file behind '
            "prune's back; the tag and its members still live on the phone)." % (len(orphans), orphans))
    return orphans, missing


def filename(tag):
    """THE single filename rule. build_tagsets and prune_tags must both call this -- they diverged once
    ('Variant Floor' -> Top_Of_Kind.txt vs Variant_Floor.txt) and the push silently sent a frozen file
    for hours, leaving the newest catches untagged."""
    # ONLY spaces are swapped. '#' and '+' are legal in filenames (the pre-existing Traded_by_E+F.txt
    # proves it) and they MUST survive, because set_db_tags_from_files derives the tag NAME back from the
    # filename. Mangling them wrote 'Variant n4plus' into the DB mirror while the device held
    # 'Variant #4+', so every granular tag showed as DRIFT despite pushing correctly (2026-09-02).
    return tag.replace(' ', '_') + '.txt'


if __name__ == '__main__':
    if '--audit' in sys.argv:
        # Offline registry audit -- no DB, no device, no Frida. Run it after touching any tag label.
        if not os.path.isdir(tagset_dir()) or not any(f.endswith('.txt') for f in os.listdir(tagset_dir())):
            # a fresh checkout has no tagsets until the data pull: every tag would read "NO FILE (skipped)" = a false green
            sys.exit('granular_tags --audit: NOT RUN -- no tagset files in %s (fresh checkout? run '
                     '`python tools/pogo_data.py pull` from the repo root first)' % tagset_dir())
        _plan = registry()
        _orph, _missing = audit_registry(_plan, strict=False)
        _vocab = sorted(all_tags())
        print('registry: %d tags (%d legacy + %d vocabulary)  colours all in 0-8'
              % (len(_plan), len(LEGACY_TAGS), len(_vocab)))
        for _t in sorted(_plan):
            _fn, _col = _plan[_t]
            _src = 'legacy' if _t in LEGACY_TAGS else 'vocab'
            _ex = 'file' if os.path.exists(os.path.join(tagset_dir(), _fn)) else 'NO FILE (skipped)'
            print('  %-20s colour=%d  %-24s %-6s %s' % (_t, _col, _fn, _src, _ex))
        print('\nEXEMPT tagsets (live, deliberately NOT pushed by prune_tags):')
        for _fn in sorted(EXEMPT_TAGSETS):
            _e = EXEMPT_TAGSETS[_fn]
            print('  %-20s tag=%-14s owner=%s' % (_fn, _e['tag'] or '(none)', _e['owner']))
        print('\nPLAN entries with no file yet (registered, zero members today -- skipped, NOT '
              'pushed as empty): %s' % (_missing or 'none'))
        print('ORPHAN tagset files (no plan entry, no exemption -- MUST be zero): %s'
              % (_orph or 'none'))
        sys.exit(1 if _orph else 0)

    con = sqlite3.connect(os.path.join(HERE, 'pokemon.db'))
    con.row_factory = sqlite3.Row
    rows = [keep_config.row_dict(r) for r in con.execute('SELECT * FROM pokemon WHERE in_bag=1')]
    TD = os.path.join(HERE, 'system', 'analysis', 'tagsets')
    pile = set(open(os.path.join(TD, 'Transfer.txt')).read().split())
    reasons = json.load(open(os.path.join(HERE, 'system', 'analysis', 'policy_reasons.json'),
                             encoding='utf-8'))
    T = build(rows, pile, reasons)
    kept = len([r for r in rows if r['uid_hex'] not in pile])
    covered = len(set().union(*T.values())) if T else 0
    for k in sorted(T, key=lambda x: -len(T[x])):
        print('%-22s %6d  -> %s' % (k, len(T[k]), filename(k)))
    print('\ntags %d | kept %d | covered %d | uncovered %d' % (len(T), kept, covered, kept - covered))
