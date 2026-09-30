"""curation_config.py -- Studio-only (Tier-B) settings: display prefs + STAGED cap proposals.

The keep engine NEVER reads this file, so curation tuning can't drift a single keep decision.
Only the Curation Studio's preview + the explicit "Apply to engine" path use it; Apply promotes a
staged cap into keep_config (Tier-A, the real single source of truth). Mirrors keep_config's hardened
pattern: defaults-merge, crash-proof accessors, validate() with bounds, atomic write().
"""
import os
import json
import copy

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, 'curation_config.json')
_CATS = ("gigantamax", "dynamax", "cosmetic", "shiny", "rarity", "xxl")

DEFAULTS = {
    "prefs": {"sort": "iv_desc", "show_protected": True, "include_xxs": False},
    "staged_global_caps": {},    # {category: int} proposed global caps -> keep_config.caps on Apply
    "staged_species_caps": {},   # {category: {pid: int}} proposed per-species caps -> keep_config.per_species_caps on Apply
    "sprite_base_cdn": "https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/Images/Pokemon/",
}


def _deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _deep_merge(out[k], v) if (k in out and isinstance(out[k], dict) and isinstance(v, dict)) else v
    return out


def _load():
    try:
        with open(PATH, encoding='utf-8') as f:
            u = json.load(f)
        if not isinstance(u, dict):
            u = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        u = {}
    return _deep_merge(DEFAULTS, u)


CFG = _load()


def reload():
    global CFG
    CFG = _load()
    return CFG


def raw():
    return copy.deepcopy(CFG)


def prefs():
    p = CFG.get("prefs")
    return p if isinstance(p, dict) else dict(DEFAULTS["prefs"])


def sprite_cdn():
    v = CFG.get("sprite_base_cdn")
    return v if isinstance(v, str) and v else DEFAULTS["sprite_base_cdn"]


def validate(cfg):
    probs = []
    if cfg.get("staged_global_caps") is not None:
        m = cfg["staged_global_caps"]
        if not isinstance(m, dict):
            probs.append("'staged_global_caps' must be an object {category:int}")
        else:
            for cat, val in m.items():
                if cat not in _CATS:
                    probs.append("staged_global_caps: unknown category '%s'" % cat)
                elif not (isinstance(val, int) and not isinstance(val, bool) and 0 <= val <= 500):
                    probs.append("staged_global_caps['%s'] must be int 0..500" % cat)
    if cfg.get("staged_species_caps") is not None:
        m = cfg["staged_species_caps"]
        if not isinstance(m, dict):
            probs.append("'staged_species_caps' must be {category:{pid:int}}")
        else:
            for cat, sub in m.items():
                if cat not in _CATS:
                    probs.append("staged_species_caps: unknown category '%s'" % cat)
                elif not isinstance(sub, dict):
                    probs.append("staged_species_caps['%s'] must be {pid:int}" % cat)
                else:
                    for pid, c in sub.items():
                        if not (str(pid).isdigit() and isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 500):
                            probs.append("staged_species_caps['%s'] pid %s must be int 0..500" % (cat, pid))
    if cfg.get("prefs") is not None and not isinstance(cfg["prefs"], dict):
        probs.append("'prefs' must be an object")
    _allowed = {"prefs", "staged_global_caps", "staged_species_caps", "sprite_base_cdn", "_note"}
    for k in cfg:
        if k not in _allowed:
            probs.append("unknown key '%s'" % k)
    return probs


def write(new_cfg):
    merged = _deep_merge(DEFAULTS, new_cfg)
    probs = validate(merged)
    if probs:
        raise ValueError("invalid curation_config: " + "; ".join(probs))
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    os.replace(tmp, PATH)
    reload()
    return merged
