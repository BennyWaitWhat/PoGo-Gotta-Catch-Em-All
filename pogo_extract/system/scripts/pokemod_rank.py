"""Pokemod's own PvP rank numbering, so a rank this project prints is the number Pokemod shows on the same Pokemon.

Benny 2026-11-18: "i need you to align with pokemods numbers." -- and at 20:07, after his hundo Naclstack lost My Best GL to
a 15/15/14 that only TIES it (the same Attack, Defense and HP at level 50; pvpoke lists the hundo first): "so pokemod is
wrong?" / "keep the pokemod numbers but be inclusive of ties." So THE NUMBER THIS PROJECT USES is rank_ties():
Pokemod's number, with every spread of a tie group sharing the group's first number. rank() stays Pokemod's own printed
number: the proof against his screen, used by no decision.

The math is Pokemod's PVPMetrics.get_Rank as it stood in Pokemod 13.1.1 (the last version that shipped readable code; read
2026-09-08 and checked against his screen that day: a 13/15/15 Tinkatink printed LL2500(91.25%) GL13(98.00%) UL13(98.00%)).
It differs from this project's own ranker (rank_cache) in three ways, and each one moves numbers:
  1. TIES. Spreads with the same stat product get numbers one after another, the lower IV index (atk*256 + def*16 + sta)
     first. rank_cache gives every tied spread the same, better number.
  2. The level table: Pokemod's own cpm list (10 digits on the half levels), and the level is the last one whose cpm^4 is
     at or under (cap+1)^2 * 100 / (atk^2 * def * sta), with level 50 as the ceiling.
  3. The product is cpm^2 * atk * def * floor(cpm * sta), in that order of operations (the order decides which near-equal
     products tie in floating point).
NOT CHECKED against Pokemod 14.2.1 (on the phone since 2026-11-13): that version ships compiled code. Its method names
(getRankIVs, an IV-index encode / decode) point at the same one-number-per-spread design; no rank line of it has been read.
"""
import bisect
import math
from decimal import Decimal, ROUND_HALF_UP

# Pokemod's cpm per half-level index (level = 1 + index / 2), its own literals.
JU = (
    0.094, 0.1351374318, 0.16639787, 0.192650919, 0.21573247, 0.2365726613, 0.25572005, 0.2735303812,
    0.29024988, 0.3060573775, 0.3210876, 0.3354450362, 0.34921268, 0.3624577511, 0.3752356, 0.387592416,
    0.39956728, 0.4111935514, 0.4225, 0.4329264091, 0.44310755, 0.4530599591, 0.4627984, 0.472336093,
    0.48168495, 0.4908558003, 0.49985844, 0.508701765, 0.51739395, 0.5259425113, 0.5343543, 0.5426357375,
    0.5507927, 0.5588305862, 0.5667545, 0.5745691333, 0.5822789, 0.5898879072, 0.5974, 0.6048236651,
    0.6121573, 0.6194041216, 0.6265671, 0.6336491432, 0.64065295, 0.6475809666, 0.65443563, 0.6612192524,
    0.667934, 0.6745818959, 0.6811649, 0.6876849038, 0.69414365, 0.70054287, 0.7068842, 0.7131691091,
    0.7193991, 0.7255756136, 0.7317, 0.7347410093, 0.7377695, 0.7407855938, 0.74378943, 0.7467812109,
    0.74976104, 0.7527290867, 0.7556855, 0.7586303683, 0.76156384, 0.7644861, 0.76739717, 0.7702973,
    0.7731865, 0.77606493, 0.77893275, 0.7817901, 0.784637, 0.78747356, 0.7903, 0.79280394,
    0.7953, 0.79780394, 0.8003, 0.8028039, 0.8053, 0.80780387, 0.8103, 0.81280386,
    0.8153, 0.8178038, 0.8203, 0.8228038, 0.8253, 0.82780373, 0.8303, 0.8328037,
    0.8353, 0.8378038, 0.8403, 0.84279999, 0.8453,
)
ZU = tuple(j * j for j in JU)            # its cpm^2 table, exactly (checked element by element against its literals)
U4 = tuple(z * z for z in ZU)            # its cpm^4 table, exactly
TOP = 98                                 # level 50: the ceiling it ranks to


def products(ba, bd, bs, cap):
    """The 4096 stat products in IV-index order, or None when a spread is over the cap at level 1 (Pokemod's own code
    reads past its table there and prints nothing usable)."""
    lim = (cap + 1) * (cap + 1) * 100
    out = []
    for a in range(16):
        te = ba + a
        for d in range(16):
            g = bd + d
            for s in range(16):
                c = bs + s
                i = bisect.bisect_right(U4, lim / (te * te * g * c)) - 1
                if i < 0:
                    return None
                y = i if i < TOP else TOP
                out.append(ZU[y] * te * g * math.floor(JU[y] * c))
    return out


def _neg(x):
    return -x


def rank(sps, sorted_sp, iv_idx):
    """1-based place of spread iv_idx after a stable descending sort: the spreads with a bigger product, then the tied
    spreads with a lower IV index. sorted_sp is sps sorted descending."""
    v = sps[iv_idx]
    return bisect.bisect_left(sorted_sp, -v, key=_neg) + 1 + sps[:iv_idx].count(v)


def rank_ties(sps, sorted_sp, iv_idx):
    """THE NUMBER THIS PROJECT USES (2026-11-18: "keep the pokemod numbers but be inclusive of ties."): the place of the FIRST spread of the
    tie group in Pokemod's order -- spreads with the same stat product share one number, so a tie never ranks one copy
    under another, and a tied copy counts wherever a rule says rank 1-5, #1 or Best."""
    return bisect.bisect_left(sorted_sp, -sps[iv_idx], key=_neg) + 1


def pct(v, best):
    """The percent as Pokemod prints it beside the rank: (0.5 + v / best * 1e5 << 0) / 1e3, shown with toFixed(2) -- which
    rounds the double's exact value and sends an exact tie up, where Python's own formatting sends it to the even digit."""
    return float(Decimal(math.floor(0.5 + v / best * 1e5) / 1e3).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
