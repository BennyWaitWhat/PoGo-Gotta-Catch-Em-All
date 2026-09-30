"""Which Pokemon HAVE an Adventure Effect -- decided PER SPECIMEN, from the moves it knows.

User 2026-09-23: "I'm looking at the adventure effect tag and most of those pokemon dont have the adventure effect at
all. You need to stop generalizing and look at each pokemon that actually has it." (and 2026-09-09: "if it doesnt
have the adventure effect, i dont want it tagged").

The game keys every Adventure Effect to a MOVE (AdventureEffectService.adventureEffects: Roar of Time, Spacial Rend,
Freeze Shock, Ice Burn, Sunsteel Strike, Moongeist Beam, Behemoth Blade, Behemoth Bash, Dynamax Cannon, the two Mega
Mewtwo moves). A Pokemon has the effect when it KNOWS that move -- an Origin Dialga without Roar of Time has none.
The 2026-09-09 rule judged the FORM (every Origin Dialga / Palkia): on 2026-09-23 that tagged 38 mons of which only
19 knew the move. The registry is re-read from the game every walk (pogo_pipeline.step_read_ae_registry ->
system/analysis/ae_registry_live.json), and move1/move2/move3 are re-read for every mon every walk, so a TM that
teaches or removes the move is picked up on the next scan.

move_ids() -> {move_id: name} or None when the registry cannot be read. None means UNKNOWN: callers must fall back to
their old over-protective roster rule (unknown data is protected, never fodder).
"""
import json
import os

_REG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'system', 'analysis', 'ae_registry_live.json')


def move_ids():
    """{move_id: move name} of every live Adventure-Effect move, or None when the registry is missing or empty."""
    try:
        effects = json.load(open(_REG, encoding='utf-8')).get('effects') or []
        out = {int(e['move_id']): e.get('move') or str(e['move_id']) for e in effects if e.get('move_id')}
        return out or None
    except Exception:
        return None


def _get(r, k):
    try:
        return r[k]
    except (KeyError, IndexError):
        return None


def known(r, ids):
    """The Adventure-Effect move names this specimen knows (fast, charged, second charged) -- [] = no effect."""
    if not ids:
        return []
    return [ids[m] for m in (_get(r, 'move1'), _get(r, 'move2'), _get(r, 'move3')) if m in ids]
