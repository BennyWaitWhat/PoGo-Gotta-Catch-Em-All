"""Field Research tasks, read from the player's OWN spins (FortSearchOutProto.ChallengeQuest).

A stop's task is only revealed by spinning it, so this bank only holds stops you spun yourself (by hand: the virtual
GO Plus spins in the :pgp process, which the scanner does not hook). Tasks rotate at local midnight, so rows are keyed
by (day, fort) and the map shows today's only.

Names come from the game's own enums (Item, HoloPokemonId), read by the scanner at attach and saved to
system/map/enums.json -- never from a hard-coded id table (1301 vs 902 for Rare Candy was already wrong once).
Used by tools/pogo_wigle.py (store) and tools/map_live.py (read).
"""
import json
import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
ENUMS = os.path.join(ROOT, "system", "map", "enums.json")
SCHEMA = """
CREATE TABLE IF NOT EXISTS quests (day TEXT, fort TEXT, t TEXT, template TEXT, goal INT, rewards TEXT, mega_pid INT,
  mega_name TEXT, mega_amount INT, rare_candy INT, summary TEXT, raw TEXT, PRIMARY KEY (day, fort));
"""
REWARD_KEYS = ("MegaResource", "Item", "Candy", "XlCandy", "Stardust", "Exp", "PokemonEncounter", "Pokecoin", "Sticker",
               "AvatarTemplateId", "LevelCap", "Incident", "PlayerAttribute", "NeutralAvatarItemTemplate")
_cache = {"mtime": None, "enums": {}}


def save_enums(enums):
    if not enums:
        return
    os.makedirs(os.path.dirname(ENUMS), exist_ok=True)
    tmp = ENUMS + ".tmp"
    json.dump(enums, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, ENUMS)


def enums():
    try:
        m = os.path.getmtime(ENUMS)
    except OSError:
        return {}
    if m != _cache["mtime"]:
        try:
            _cache["enums"] = json.load(open(ENUMS, encoding="utf-8"))
            _cache["mtime"] = m
        except (OSError, ValueError):
            pass
    return _cache["enums"]


def human(name):
    """RareCandy -> Rare Candy; keeps unknown ids readable."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name))


def _name(kind, v):
    table = (enums().get(kind) or {})
    n = table.get(str(v))
    return n if n else f"{kind} {v}"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def rewards(quest):
    """Every reward dict inside the quest subtree (a dict with a Type and a known reward key)."""
    out = []
    for d in _walk(quest):
        keys = [k for k in REWARD_KEYS if k in d]
        if not keys or "Type" not in d:
            continue
        k = keys[0]
        v = d[k]
        if k == "MegaResource" and isinstance(v, dict):
            pid = _int(v.get("PokemonId"))
            out.append({"kind": "mega", "pid": pid, "name": _name("HoloPokemonId", pid), "amount": _int(v.get("Amount"))})
        elif k == "Item" and isinstance(v, dict):
            it = _int(v.get("Item"))
            out.append({"kind": "item", "item": it, "name": _name("Item", it), "amount": _int(v.get("Amount") or v.get("ItemCount"))})
        elif k in ("Candy", "XlCandy") and isinstance(v, dict):
            pid = _int(v.get("PokemonId"))
            out.append({"kind": k.lower(), "pid": pid, "name": _name("HoloPokemonId", pid), "amount": _int(v.get("Amount"))})
        elif k == "PokemonEncounter" and isinstance(v, dict):
            pid = _int(v.get("PokemonId"))
            out.append({"kind": "encounter", "pid": pid, "name": _name("HoloPokemonId", pid)})
        elif k in ("Stardust", "Exp", "Pokecoin"):
            out.append({"kind": k.lower(), "amount": _int(v)})
        else:
            out.append({"kind": k, "raw": v if isinstance(v, (int, str)) else None})
    return out


def describe(rw):
    parts = []
    for r in rw:
        k = r["kind"]
        if k == "mega":
            parts.append(f"{human(r['name'])} Mega Energy x{r['amount']}")
        elif k == "item":
            parts.append(f"{human(r['name'])} x{r['amount']}")
        elif k in ("candy", "xlcandy"):
            parts.append(f"{human(r['name'])} {'XL ' if k == 'xlcandy' else ''}Candy x{r['amount']}")
        elif k == "encounter":
            parts.append(f"{human(r['name'])} encounter")
        elif k in ("stardust", "exp", "pokecoin"):
            parts.append(f"{r['amount']} {k}")
        else:
            parts.append(k)
    return ", ".join(parts) or "no reward decoded"


def store(db, t, spin):
    """Record the task a spin handed out. Returns the summary, or None when the spin carried no task."""
    q = spin.get("ChallengeQuest")
    if not isinstance(q, dict) or not q:
        return None
    rw = rewards(q)
    mega = next((r for r in rw if r["kind"] == "mega"), None)
    rare = sum(r.get("amount", 0) for r in rw if r["kind"] == "item" and re.search(r"RareCandy", str(r["name"]), re.I))
    tpl = next((d.get("TemplateId") for d in _walk(q) if isinstance(d.get("TemplateId"), str)), None)
    goal = next((_int(d["Goal"].get("Target")) for d in _walk(q) if isinstance(d.get("Goal"), dict)), 0)
    summary = describe(rw)
    db.executescript(SCHEMA)
    db.execute("INSERT OR REPLACE INTO quests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (t[:10], spin.get("FortId"), t, tpl, goal, json.dumps(rw), mega["pid"] if mega else None,
                mega["name"] if mega else None, mega["amount"] if mega else None, rare or None, summary, json.dumps(q)[:20000]))
    return summary


def today(db, day):
    """{fort_id: {summary, kind: 'mega'|'rare'|'other', ...}} for the given local day; {} when there is no table yet."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='quests'").fetchone():
        return {}
    out = {}
    for fort, s, mn, ma, rc, tpl, goal in db.execute(
            "SELECT fort, summary, mega_name, mega_amount, rare_candy, template, goal FROM quests WHERE day=?", (day,)):
        out[fort] = {"s": s, "k": "mega" if mn else ("rare" if rc else "other"), "tpl": tpl, "goal": goal}
    return out
