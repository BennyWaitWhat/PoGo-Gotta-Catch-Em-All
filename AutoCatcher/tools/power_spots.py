"""Power Spots near you vs your Dynamax collection. READ-ONLY.

Answers "any dynamax pokemon around me that i dont have yet?" (Benny, 2026-11-18). One attach reads the game's own
records: every Power Spot it holds (Niantic.Holoholo.Bread.StationProto: boss, gender, stars, window), the whole Pokedex
(Holoholo.Rpc.PokedexEntryProto) and the catches made since the bag database was written. Plain memory reads only: no
managed call, no hook, nothing written to the game, no restart, no retry. A POST check confirms the same PoGo pid and
no new PoGo tombstone. A read never needs his go; a teleport or a battle does.

What a Power Spot can give him, in three tiers (nearest spot first):
  1 NEW species    no Dynamax (Gigantamax) of that species in his Pokedex
  2 NEW look       a gender his Pokedex lacks, only for his 14 gender looks (pogo_extract/gender_variants.json),
                   also after evolving (a female Dynamax Pikachu -> his first female Dynamax Raichu)
  3 NEW evolution  a Dynamax evolution never registered. Branches come from the game master per form (Sneasler only
                   from a Hisuian Sneasel) and honour gender (Vespiquen only from a female Combee). It says when he
                   already holds a Dynamax copy that can make it with no battle.
The boss's gender is the catch's gender (14 of 14 on 2026-11-16).

  python AutoCatcher/tools/power_spots.py                          read the game, write the page, print the summary
  python AutoCatcher/tools/power_spots.py --from FILE [--at LAT,LNG]   redo the comparison from a saved read (no phone)
  python AutoCatcher/tools/power_spots.py --selftest               offline checks (CI)
  --data DIR   the pogo_extract folder holding the game master and pokemon.db (default: the one next to AutoCatcher)
Writes AutoCatcher/system/analysis/scans/power_spots_<stamp>.json (the read) and .html (the page: offline, phone width).
That folder is git-ignored: a read holds his whole Pokedex.
"""
import argparse
import collections
import html
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.dirname(HERE)
DATA = os.path.join(os.path.dirname(AC), "pogo_extract")
OUT_DIR = os.path.join(AC, "system", "analysis", "scans")

PROTOS = "holo-protos.dll"
STATION = "Niantic.Holoholo.Bread.StationProto"
DEX = "Holoholo.Rpc.PokedexEntryProto"
MON = "Holoholo.Rpc.PokemonProto"
SLOW_SCAN_MS = 2500        # a slower heap scan skips the rest of the reads (protects the game)
MIN_DEX = 100              # fewer Pokedex entries = an incomplete read: no tier is claimed from it

MODE = {1: "Dynamax", 2: "Gigantamax"}
DEX_CAT = {1: "BREAD_MODE", 2: "BREAD_DOUGH_MODE"}
GENDER = {1: "male", 2: "female", 3: "genderless"}
GENDER_REQ = {"MALE": 1, "FEMALE": 2}
ITEMS = {"ITEM_GEN4_EVOLUTION_STONE": "Sinnoh Stone", "ITEM_GEN5_EVOLUTION_STONE": "Unova Stone", "ITEM_KINGS_ROCK": "King's Rock",
         "ITEM_METAL_COAT": "Metal Coat", "ITEM_DRAGON_SCALE": "Dragon Scale", "ITEM_UP_GRADE": "Up-Grade", "ITEM_SUN_STONE": "Sun Stone"}
LURES = {"ITEM_TROY_DISK_MOSSY": "Mossy Lure", "ITEM_TROY_DISK_GLACIAL": "Glacial Lure", "ITEM_TROY_DISK_MAGNETIC": "Magnetic Lure",
         "ITEM_TROY_DISK_RAINY": "Rainy Lure", "ITEM_TROY_DISK_SPARKLY": "Golden Lure"}
EMPTY = {"cats": frozenset(), "genders": {1: frozenset(), 2: frozenset()}}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def form_key(value, forms=None):
    """'' for a normal or unset form, else the normalised form name. `value` is a form-enum number (needs `forms`),
    a form-enum name ('SneaselHisuian') or a game-master form ('SNEASEL_HISUIAN')."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = (forms or {}).get(value, "") if value else ""
    k = norm(value)
    return "" if (not k or k == "unset" or k.endswith("normal")) else k


def meters(a, b):
    p1, p2, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(h))


class GameMaster:
    """Pokemon templates from the game master, per form: number, name, evolution branches."""

    def __init__(self, templates):
        self.num, self.name = {}, {}
        self.tmpl = collections.defaultdict(dict)        # n -> form key -> branches
        self.form_name = collections.defaultdict(dict)   # n -> form key -> game-master form ('SNEASEL_HISUIAN')
        for t in templates:
            tid, d = t.get("templateId", ""), t.get("data") or {}
            ps = d.get("pokemonSettings")
            if not ps or not re.match(r"^V\d{4}_POKEMON_", tid):
                continue
            n = int(tid[1:5])
            self.num.setdefault(ps["pokemonId"], n)
            self.name.setdefault(n, ps["pokemonId"].replace("_", " ").title())
            fk = norm(ps.get("form"))
            self.tmpl[n][fk] = [b for b in ps.get("evolutionBranch") or [] if b.get("evolution")]
            self.form_name[n][fk] = ps.get("form") or ""

    def label(self, n):
        return self.name.get(n, "#%s" % n)

    def branches(self, n, form):
        """Branches of species n in this form. A normal or unset form takes the plain template, else *_NORMAL."""
        t, f = self.tmpl.get(n, {}), norm(form)
        if f in t:
            return t[f]
        if form_key(form) == "":
            if "" in t:
                return t[""]
            for k, v in t.items():
                if k.endswith("normal"):
                    return v
        return t.get("", [])

    def all_branches(self, n):
        return [(fk, b) for fk, bs in self.tmpl.get(n, {}).items() for b in bs]

    def paths(self, n, form, gender):
        """Every evolution a mon of this species, form and gender can reach: [(target n, target form, steps)],
        step = (from n, to n, branch). A gender-gated branch the gender can't take is left out."""
        out, todo, seen = [], [(n, form, [])], set()
        while todo:
            x, f, path = todo.pop()
            for b in self.branches(x, f):
                need = GENDER_REQ.get(b.get("genderRequirement"))
                if b.get("genderRequirement") and need != gender:
                    continue
                tn = self.num.get(b["evolution"])
                if not tn or (tn, norm(b.get("form"))) in seen or tn == n:
                    continue
                seen.add((tn, norm(b.get("form"))))
                p = path + [(x, tn, b)]
                out.append((tn, b.get("form") or "", p))
                todo.append((tn, b.get("form") or "", p))
        return out


def cost(b):
    """One evolution step's price in plain words."""
    parts = []
    if b.get("candyCost"):
        parts.append("%d candy" % b["candyCost"])
    it = b.get("evolutionItemRequirement")
    if it:
        parts.append(ITEMS.get(it, it.replace("ITEM_", "").replace("_", " ").title()))
    lure = b.get("lureItemRequirement")
    if lure:
        parts.append("at a " + LURES.get(lure, lure.replace("ITEM_", "").replace("_", " ").title()))
    if b.get("kmBuddyDistanceRequirement"):
        parts.append("%g km as buddy" % b["kmBuddyDistanceRequirement"])
    elif b.get("mustBeBuddy"):
        parts.append("as buddy")
    if b.get("onlyDaytime"):
        parts.append("by day")
    if b.get("onlyNighttime"):
        parts.append("at night")
    if b.get("onlyUpsideDown"):
        parts.append("phone upside down")
    if b.get("questDisplay") and not b.get("kmBuddyDistanceRequirement"):
        q = (b["questDisplay"][0] or {}).get("questRequirementTemplateId", "")
        parts.append("the %s quest" % q.replace("_EVOLUTION_QUEST", "").replace("_", " ").title() if q else "a quest")
    if b.get("genderRequirement"):
        parts.append(b["genderRequirement"].lower() + " only")
    return ", ".join(parts) or "no cost listed"


def dex_index(entries):
    """Pokedex per species (union over duplicate records): acquired categories and the genders obtained per Max mode."""
    dex = {}
    for e in entries or []:
        n = e.get("PokedexEntryNumber") if isinstance(e, dict) else None
        if not isinstance(n, int) or n <= 0:
            continue
        d = dex.setdefault(n, {"cats": set(), "genders": {1: set(), 2: set()}})
        for key, st in (e.get("CategoryStatus") or {}).items():
            if isinstance(st, dict) and st.get("Acquired"):
                d["cats"].add(key)
        for b in e.get("BreadDexData") or []:
            if isinstance(b, dict) and b.get("ModifierId") in (1, 2):
                d["genders"][b["ModifierId"]] |= set(b.get("GendersObtained") or [])
    return dex


def spots(stations, forms):
    """One row per Power Spot (records come duplicated; a record with the boss wins)."""
    by = {}
    for s in stations or []:
        if not isinstance(s, dict) or not s.get("Id") or not s.get("Lat"):
            continue
        if (s.get("BattleDetails") or {}).get("BattlePokemon") or s["Id"] not in by:
            by[s["Id"]] = s
    out = []
    for s in by.values():
        bd = s.get("BattleDetails") or {}
        bp = bd.get("BattlePokemon") or {}
        dp = bp.get("pokemonDisplay_") or {}
        form = dp.get("Form") or 0
        out.append({"id": s["Id"], "name": s.get("Name") or "", "lat": s["Lat"], "lng": s["Lng"], "pid": bp.get("pokemonId_"),
                    "form": forms.get(form, str(form)) if form else "", "mode": dp.get("BreadModeEnum"), "gender": dp.get("Gender"),
                    "stars": bd.get("BattleLevel"), "end_ms": int(bd.get("BattleWindowEndMs") or s.get("EndTimeMs") or 0),
                    "open": bool(s.get("IsBreadBattleAvailable")), "dist": None})
    return out


def holders(path, start_form, held, gender=None):
    """Dynamax copies he holds that can walk the rest of `path` to its end: [(species, count)], earliest stage first."""
    stage_forms = [start_form] + [b.get("form") for _, _, b in path]
    out = []
    for i, (x, _, _) in enumerate(path):
        need = {GENDER_REQ.get(b.get("genderRequirement")) for _, _, b in path[i:] if b.get("genderRequirement")}
        if gender:
            need.add(gender)
        fk = form_key(stage_forms[i])
        n = sum(1 for f, g in held.get((x, 1), []) if f == fk and all(g == r for r in need))
        if n:
            out.append((x, n))
    return out


def assess(s, dex, held, gm, looks):
    """What this Power Spot's boss can give him: a list of gaps (tier 1, 2 or 3)."""
    out = []
    pid, mode, g = s["pid"], s["mode"], s["gender"]
    if not pid or mode not in MODE:
        return out
    word, nm, d = MODE[mode], gm.label(pid), dex.get(pid, EMPTY)
    if DEX_CAT[mode] not in d["cats"]:
        out.append({"tier": 1, "key": "%s %s" % (word, nm), "base": pid, "why": "no %s %s in your Pokédex yet" % (word, nm)})
    elif pid in looks and g in (1, 2) and g not in d["genders"][mode]:
        out.append({"tier": 2, "key": "%s %s %s" % (GENDER[g], word, nm), "base": pid,
                    "why": "your first %s %s %s (one of your 14 gender looks)" % (GENDER[g], word, nm)})
    if mode != 1:
        return out
    for tn, _tform, path in gm.paths(pid, s["form"], g):
        dt, tname = dex.get(tn, EMPTY), gm.label(tn)
        price = "; ".join("%s: %s" % (gm.label(to), cost(b)) for _, to, b in path)
        if DEX_CAT[1] not in dt["cats"]:
            out.append({"tier": 3, "key": "Dynamax " + tname, "base": pid, "target": tn, "cost": price,
                        "hold": holders(path, s["form"], held)})
        elif tn in looks and g in (1, 2) and g not in dt["genders"][1]:
            out.append({"tier": 2, "key": "%s Dynamax %s" % (GENDER[g], tname), "base": pid, "target": tn, "cost": price,
                        "why": "evolve a %s Dynamax %s: your first %s Dynamax %s (one of your 14 gender looks)" % (GENDER[g], nm, GENDER[g], tname),
                        "hold": holders(path, s["form"], held, gender=g)})
    return out


def blocked(sp, dex, gm):
    """Dynamax evolutions his Pokedex lacks that this map can't give: a branch of another form of the species
    (Sneasler needs a Hisuian Sneasel) or of the other gender (Vespiquen needs a female Combee)."""
    by = collections.defaultdict(list)
    for s in sp:
        if s["pid"] and s["mode"] == 1:
            by[s["pid"]].append(s)
    out, done = [], set()
    for pid, ss in sorted(by.items()):
        reach = {tn for s in ss for tn, _, _ in gm.paths(pid, s["form"], s["gender"])}
        fks, genders = {form_key(s["form"]) for s in ss}, {s["gender"] for s in ss}
        for fk, b in gm.all_branches(pid):
            tn = gm.num.get(b["evolution"])
            if not tn or tn in reach or tn in done or DEX_CAT[1] in dex.get(tn, EMPTY)["cats"]:
                continue
            if form_key(fk) and form_key(fk) not in fks:
                fname = gm.form_name[pid].get(fk, fk).upper().replace(gm.label(pid).upper().replace(" ", "_") + "_", "")
                why = "needs a %s %s; these are the %s form" % (fname.replace("_", " ").title(), gm.label(pid),
                                                               " / ".join(sorted({(form_key(s["form"]) or "normal") for s in ss})))
            elif b.get("genderRequirement") and GENDER_REQ.get(b["genderRequirement"]) not in genders:
                why = "only a %s %s evolves; all %d spots show %s" % (b["genderRequirement"].lower(), gm.label(pid), len(ss),
                                                                    " / ".join(sorted(GENDER.get(x, "?") for x in genders)))
            else:
                continue
            done.add(tn)
            out.append({"target": tn, "base": pid, "why": why})
    return out


def compare(read, gm, forms, looks, bag, at=None, bag_at=None):
    """The whole answer from one read: spots with distances, gaps by tier, what the map can't give."""
    data = read.get("data") or {}
    here = tuple(at or read.get("here") or ()) or None
    dex = dex_index(data.get(DEX))
    sp = spots(data.get(STATION), forms)
    for s in sp:
        s["dist"] = meters(here, (s["lat"], s["lng"])) if here else None
    sp.sort(key=lambda s: (s["dist"] is None, s["dist"] or 0, s["name"]))
    held = collections.defaultdict(list)
    for pid, mode, fk, g in bag:
        held[(pid, mode)].append((fk, g))
    ids = set()
    for r in ((read.get("new_mons") or {}).get("rows") or []):
        dp = (r or {}).get("pokemonDisplay_") or {}
        if dp.get("BreadModeEnum") in MODE and r.get("id_") not in ids:
            ids.add(r.get("id_"))
            held[(r.get("pokemonId_"), dp["BreadModeEnum"])].append((form_key(dp.get("Form") or 0, forms), dp.get("Gender")))
    complete = len(dex) >= MIN_DEX
    t12, t3 = {}, {}
    for s in sp if complete else []:
        for gp in assess(s, dex, held, gm, looks):
            if gp["tier"] == 3:
                grp = t3.setdefault(gp["base"], {"base": gp["base"], "targets": {}, "spots": []})
                tg = grp["targets"].setdefault(gp["target"], dict(gp, spots=[]))
                tg["spots"].append(s)
                if s not in grp["spots"]:
                    grp["spots"].append(s)
            else:
                g = t12.setdefault(gp["key"], dict(gp, spots=[]))
                g["spots"].append(s)
    kinds = collections.Counter((s["pid"], s["mode"]) for s in sp if s["pid"])
    not_held = sorted({(gm.label(p), MODE.get(m, "?")) for (p, m) in kinds
                       if m in MODE and DEX_CAT[m] in dex.get(p, EMPTY)["cats"] and not held.get((p, m))})
    ends = collections.Counter(s["end_ms"] for s in sp if s["end_ms"])
    return {"read_at": read.get("read_at") or (read.get("meta") or {}).get("started"), "here": here, "spots": sp, "dex_n": len(dex), "complete": complete,
            "tier1": [g for g in t12.values() if g["tier"] == 1], "tier2": [g for g in t12.values() if g["tier"] == 2],
            "tier3": list(t3.values()), "blocked": blocked(sp, dex, gm) if complete else [], "kinds": kinds,
            "not_held": not_held, "change_ms": ends.most_common(1)[0][0] if ends else 0, "gm": gm,
            "errors": list(read.get("errors") or []), "post": (read.get("meta") or {}).get("post"), "bag_at": bag_at}


def _dist(s):
    return "?" if s["dist"] is None else ("%d m" % round(s["dist"], -1) if s["dist"] < 1000 else "%.1f km" % (s["dist"] / 1000))


def _boss(s, gm):
    return "%s %s★ %s" % (gm.label(s["pid"]), s["stars"] or "?", GENDER.get(s["gender"], "")) if s["pid"] else "no boss"


def _hold(hold, gm):
    return ", ".join("%s x%d" % (gm.label(x), n) for x, n in hold)


def summary(res):
    gm, sp = res["gm"], res["spots"]
    far = max((s["dist"] for s in sp if s["dist"] is not None), default=0)
    modes = collections.Counter(MODE.get(s["mode"], "special") for s in sp if s["pid"])
    out = ["Power Spots read %s: %d out to %.1f km, %d boss kinds (%s). Bosses change %s." % (
        (res["read_at"] or "?")[11:16], len(sp), far / 1000, len(res["kinds"]), ", ".join("%d %s" % (n, m) for m, n in modes.most_common()),
        time.strftime("%a %H:%M", time.localtime(res["change_ms"] / 1000)) if res["change_ms"] else "?")]
    if not res["complete"]:
        out.append("STOP: only %d Pokedex entries were read (want %d+) -- no tier is claimed from an incomplete read." % (res["dex_n"], MIN_DEX))
        return out + ["error: " + e for e in res["errors"]]
    if res["tier1"]:
        for g in res["tier1"]:
            s = g["spots"][0]
            out.append("NEW species: %s -- %s %s (%s) +%d more spot(s)" % (g["key"], _dist(s), s["name"], _boss(s, gm), len(g["spots"]) - 1))
    else:
        out.append("NEW species: none -- every boss kind is in your Dynamax Pokedex.")
    for g in res["tier2"]:
        s = g["spots"][0]
        out.append("NEW look: %s -- %s %s (%s)%s" % (g["key"], _dist(s), s["name"], _boss(s, gm),
                                                     " | you hold " + _hold(g["hold"], gm) if g.get("hold") else ""))
    if res["tier3"]:
        out.append("NEW Dynamax evolutions (%d) -- nearest spot of the base:" % sum(len(x["targets"]) for x in res["tier3"]))
    for grp in sorted(res["tier3"], key=lambda x: x["spots"][0]["dist"] or 0):
        s = grp["spots"][0]
        for tg in grp["targets"].values():
            out.append("  %-24s <- %-11s %7s %-28s | %s%s" % (tg["key"], gm.label(grp["base"]), _dist(s), s["name"][:28], tg["cost"],
                                                          " | you hold " + _hold(tg["hold"], gm) if tg["hold"] else ""))
    for b in res["blocked"]:
        out.append("Not here: Dynamax %s -- %s" % (gm.label(b["target"]), b["why"]))
    if res["not_held"]:
        out.append("In your Pokedex but none in your bag now: " + ", ".join("%s %s" % (m, n) for n, m in res["not_held"]))
    if res["post"]:
        out.append("game check after the read: %s" % ("OK (same pid, no crash)" if res["post"].get("ok") else "FAILED %s" % res["post"]))
    return out + ["error: " + e for e in res["errors"]]


CSS = """:root{--bg:#f6f7f9;--fg:#15171a;--mut:#5b6470;--card:#fff;--line:#dde1e6;--acc:#7b2ff7;--new:#e8fbe9;--newb:#1f9d55}
@media (prefers-color-scheme:dark){:root{--bg:#111316;--fg:#e9ecef;--mut:#9aa4af;--card:#1a1d21;--line:#2b3036;--acc:#b48cff;--new:#12261a;--newb:#3ccf7d}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:720px;margin:0 auto;padding:16px}h1{font-size:20px;margin:4px 0}h2{font-size:16px;margin:22px 0 8px}
.lead{font-size:16px}.mut{color:var(--mut)}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin:8px 0}
.card.new{background:var(--new);border-color:var(--newb)}.t{font-weight:700;font-size:16px}.card p{margin:4px 0 6px}
.spot{border-top:1px dashed var(--line);padding-top:6px;margin-top:6px}.d{font-variant-numeric:tabular-nums;font-weight:700;color:var(--acc)}
.pill{display:inline-block;font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--fg);text-decoration:none;margin-right:4px}
.cp{font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--mut)}
ul{padding-left:20px}table{border-collapse:collapse;width:100%;font-size:13px}td{border-top:1px solid var(--line);padding:4px 6px 4px 0;vertical-align:top}
details{margin-top:10px}summary{cursor:pointer;font-weight:600}"""


def page_html(res):
    e, gm = html.escape, res["gm"]

    def pill(s):
        q = "%.6f,%.6f" % (s["lat"], s["lng"])
        return ('<a class="pill" href="https://www.google.com/maps/search/?api=1&amp;query=%s">%s</a>'
                '<button class="cp" data-c="%s">copy</button>') % (q, q, q)

    def spot(s):
        return '<div class="spot"><span class="d">%s</span> <b>%s</b><br><span class="mut">%s</span> %s</div>' % (
            _dist(s), e(_boss(s, gm)), e(s["name"]), pill(s))

    sp = res["spots"]
    far = max((s["dist"] for s in sp if s["dist"] is not None), default=0)
    head = "Read from the game %s. %d Power Spots out to %.1f km, %d boss kinds. Distances from where you stood then. Bosses change %s." % (
        (res["read_at"] or "?")[11:16], len(sp), far / 1000, len(res["kinds"]),
        time.strftime("%a %H:%M", time.localtime(res["change_ms"] / 1000)) if res["change_ms"] else "?")
    if res.get("bag_at"):
        head += " Your bag: the last walk (%s) plus catches since; an evolution since then is not seen." % time.strftime("%m-%d %H:%M", time.localtime(res["bag_at"]))
    body = ['<h1>Dynamax near you</h1><p class="mut">%s</p>' % e(head)]
    if not res["complete"]:
        body.append('<p class="lead"><b>Incomplete read:</b> only %d Pokédex entries. Nothing is claimed from it.</p>' % res["dex_n"])
    else:
        if res["tier1"]:
            body.append('<p class="lead"><b>New Dynamax here:</b> %s.</p>' % e(", ".join(g["key"] for g in res["tier1"])))
        else:
            body.append('<p class="lead"><b>No new Dynamax species here.</b> All %d boss kinds are already in your Dynamax Pokédex.</p>' % len(res["kinds"]))
        if res["not_held"]:
            body.append('<p class="mut">In your Pokédex but none in your bag now: %s.</p>' % e(", ".join("%s %s" % (m, n) for n, m in res["not_held"])))
        if res["tier1"] or res["tier2"]:
            body.append("<h2>New for you (needs a battle)</h2>")
        for g in res["tier1"] + res["tier2"]:
            hold = ('<br><span class="mut">You already hold %s: evolving one gives it with no battle.</span>' % e(_hold(g["hold"], gm))) if g.get("hold") else ""
            price = ('<br><span class="mut">Cost: %s.</span>' % e(g["cost"])) if g.get("cost") else ""
            body.append('<div class="card new"><div class="t">%s</div><p>%s.%s%s</p>%s</div>' % (
                e(g["key"][0].upper() + g["key"][1:]), e(g["why"][0].upper() + g["why"][1:]), price, hold, "".join(spot(s) for s in g["spots"][:2])))
        if res["tier3"]:
            body.append('<h2>Dynamax evolutions you never had</h2><p class="mut">These Power Spots hold the base Pokémon. '
                        'Where you already hold a Dynamax copy, evolving one fills the gap with no battle; a battle gives a spare so your count stays.</p>')
        for grp in sorted(res["tier3"], key=lambda x: x["spots"][0]["dist"] or 0):
            names = ", ".join(gm.label(t) for t in grp["targets"])
            lines = []
            for t, tg in grp["targets"].items():
                only = "" if len(tg["spots"]) == len(grp["spots"]) else " (only from some of these bosses; nearest %s %s)" % (_dist(tg["spots"][0]), tg["spots"][0]["name"])
                lines.append("<b>%s</b>: %s.%s%s" % (e(gm.label(t)), e(tg["cost"]), (" You hold " + e(_hold(tg["hold"], gm)) + ".") if tg["hold"] else
                                                     " You hold no Dynamax copy to evolve.", e(only)))
            body.append('<div class="card"><div class="t">Dynamax %s</div><p>From Dynamax %s.<br>%s</p>%s</div>' % (
                e(names), e(gm.label(grp["base"])), "<br>".join(lines), "".join(spot(s) for s in grp["spots"][:1])))
        if res["blocked"]:
            body.append("<h2>Not possible here</h2><ul>%s</ul>" % "".join(
                "<li><b>Dynamax %s</b>: %s.</li>" % (e(gm.label(b["target"])), e(b["why"])) for b in res["blocked"]))
    kinds = collections.Counter("%s %s" % (MODE.get(m, "special"), gm.label(p)) for (p, m), n in res["kinds"].items() for _ in range(n))
    body.append('<h2>Every boss on the map</h2><p class="mut">%s</p>' % e(", ".join("%s x%d" % (k, n) for k, n in kinds.most_common())))
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (_dist(s), e(_boss(s, gm)), e(s["name"]), pill(s)) for s in sp)
    body.append("<details><summary>All %d Power Spots, nearest first</summary><table>%s</table></details>" % (len(sp), rows))
    if res["errors"]:
        body.append('<p class="mut">Read notes: %s</p>' % e("; ".join(res["errors"])))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Dynamax near you</title><style>%s</style></head><body><main>%s</main><script>document.querySelectorAll('.cp').forEach("
            "function(b){b.onclick=function(){try{navigator.clipboard.writeText(b.dataset.c);b.textContent='copied'}catch(x){}}})</script>"
            "</body></html>") % (CSS, "".join(body))


# ---------------------------------------------------------------- the read (one attach, plain memory reads)
# The JS below is raid_probe.py's (2026-11-16), which read Power Spots + the Pokedex cleanly on 11-16 and 11-18.
JS_HELPERS = r"""
IL.ns = f('il2cpp_class_get_namespace', 'pointer', ['pointer']);
IL.decl = f('il2cpp_class_get_declaring_type', 'pointer', ['pointer']);
IL.fsget = f('il2cpp_field_static_get_value', 'void', ['pointer', 'pointer']);
IL.elemClass = f('il2cpp_class_get_element_class', 'pointer', ['pointer']);
IL.arrElemSize = f('il2cpp_class_array_element_size', 'int', ['pointer']);
IL.classType = f('il2cpp_class_get_type', 'pointer', ['pointer']);
var RLIM = 300, IMG = {}, IDX = {}, KEEP = {}, RFC = {};
function imageOf(img) {
  if (IMG[img]) return IMG[img];
  var sp = Memory.alloc(8), a = IL.asms(IL.domain(), sp), n = sp.readS32();
  for (var i = 0; i < n; i++) { var im = IL.asmImage(a.add(i * PS).readPointer()); if (cs(IL.imageName(im)) === img) { IMG[img] = im; return im; } }
  return null;
}
function qname(k) {
  var parts = [cs(IL.className(k))], top = k, d = IL.decl(k), guard = 0;
  while (d && !d.isNull() && guard++ < 8) { parts.unshift(cs(IL.className(d))); top = d; d = IL.decl(d); }
  var ns = cs(IL.ns(top));
  return (ns ? ns + '.' : '') + parts.join('/');
}
function findQ(img, q) {
  var ix = IDX[img]; if (!ix) throw new Error('image not indexed: ' + img);
  var simple = q.split('/').pop().split('.').pop(), c = ix.map[simple] || [];
  if (q === simple) return c[0] || null;
  for (var i = 0; i < c.length; i++) if (qname(c[i]) === q) return c[i];
  return null;
}
function rfElem(fd) {
  var key = fd.t.toString(); if (RFC[key]) return RFC[key];
  var res = {kind: 'ref', size: 8};
  try {
    var rk = IL.classFromType(fd.t), arrT = null;
    fieldsOf(rk).forEach(function (x) { if (!arrT && x.te === 0x1d) arrT = x.t; });
    if (arrT) {
      var ak = IL.classFromType(arrT), ek = IL.elemClass(ak), te = IL.typeEnum(IL.classType(ek));
      if (IL.isEnum(ek)) res = {kind: 'enum', size: 4};
      else if (te === 0x0e) res = {kind: 'str', size: 8};
      else if (te >= 0x02 && te <= 0x0d) res = {kind: 'prim', te: te, size: IL.arrElemSize(ak)};
      else if (IL.isValueType(ek)) res = {kind: 'struct', size: IL.arrElemSize(ak)};
    } else res = {kind: 'unknown', size: 8};
  } catch (e) { res = {kind: 'unknown', size: 8}; }
  RFC[key] = res; return res;
}
function nm_(x) { return x.name.replace(/[^A-Za-z]/g, '').toLowerCase(); }
/* MapField<K,V> = {.., LinkedList<KeyValuePair<K,V>> list}: walk the list; each node's item is the KeyValuePair struct inline.
   Values are read as messages ONLY when V is named like a message; everything else is read as a plain number. */
function readMap(q, fd, depth) {
  var m = /MapField<([^,]+),\s*(.+)>$/.exec(fd.tn) || [], kt = (m[1] || '').trim(), vt = (m[2] || '').trim();
  var ll = null;
  fieldsOf(jsClass(q).k).forEach(function (x) { if (!ll && /LinkedList/.test(x.tn) && !/Node/.test(x.tn)) ll = q.add(x.off).readPointer(); });
  if (!ll || ll.isNull()) return undefined;
  var head = NULL, cnt = 0;
  fieldsOf(jsClass(ll).k).forEach(function (x) { var n = nm_(x); if (n === 'head' || n === 'first') head = ll.add(x.off).readPointer(); if (n === 'count') cnt = ll.add(x.off).readS32(); });
  if (head.isNull() || cnt <= 0) return undefined;
  var isMsg = /(Proto|Status|Settings|Data)$/.test(vt), el = ELEM[vt], four = /^System\.(Int32|UInt32|Single|Boolean)$/.test(vt) || (!isMsg && !el);
  var out = {}, node = head, it = 0, nOff = -1, iOff = -1;
  while (node && !node.isNull() && it < Math.min(cnt, 600)) {
    if (nOff < 0) fieldsOf(jsClass(node).k).forEach(function (x) { var n = nm_(x); if (n === 'next' || n === 'forward') nOff = x.off; if (n === 'item') iOff = x.off; });
    if (nOff < 0 || iOff < 0) break;
    var ip = node.add(iOff), key, voff = 8, val;
    if (kt === 'System.String') key = str(ip.readPointer());
    else if (/^System\.U?Int32$/.test(kt)) { key = ip.readS32(); voff = four ? 4 : 8; }
    else if (/^System\.U?Int64$/.test(kt)) key = ip.readS64().toString();
    else { key = ip.readS32(); voff = four ? 4 : 8; }
    if (el && el[0] === 's') val = str(ip.add(voff).readPointer());
    else if (el) val = prim(ip.add(voff), el[0]);
    else if (isMsg) { var vp = ip.add(voff).readPointer(); val = vp.isNull() ? null : readObj2(vp, depth + 1); }
    else val = ip.add(voff).readS32();
    out[String(key)] = val;
    var nx = node.add(nOff).readPointer(); if (nx.isNull() || nx.equals(head)) break; node = nx; it++;
  }
  return out;
}
function readField(o, fd, depth) {
  var p = o.add(fd.off), v;
  if (fd.te === 0x11) { var ec = IL.classFromType(fd.t); v = IL.isEnum(ec) ? p.readS32() : undefined; if (v === 0) return undefined; return v; }
  if (fd.te === 0x0e) { v = str(p.readPointer()); return v ? v : undefined; }
  if (fd.te === 0x12 || fd.te === 0x15 || fd.te === 0x1c) {
    if (fd.te === 0x15 && IL.isValueType(IL.classFromType(fd.t))) return undefined;
    var q = p.readPointer(); if (q.isNull()) return undefined;
    var qn; try { qn = jsClass(q).name; } catch (e) { return undefined; }
    if (qn.indexOf('RepeatedField') === 0) {
      var arr = q.add(0x10).readPointer(), cnt = q.add(0x18).readS32(); if (cnt <= 0 || arr.isNull()) return undefined;
      var el = rfElem(fd), list = [], lim = Math.min(cnt, RLIM);
      for (var i = 0; i < lim; i++) {
        var ep = arr.add(0x20 + el.size * i);
        if (el.kind === 'enum') list.push(ep.readS32());
        else if (el.kind === 'str') list.push(str(ep.readPointer()));
        else if (el.kind === 'prim') list.push(prim(ep, el.te));
        else if (el.kind === 'ref') { var e2 = ep.readPointer(); list.push(e2.isNull() ? null : readObj2(e2, depth + 1)); }
        else list.push('<' + el.kind + '>');
      }
      if (cnt > lim) list.push('... ' + cnt + ' total');
      return list;
    }
    if (qn.indexOf('MapField') === 0) { try { return readMap(q, fd, depth); } catch (e) { return '<map unreadable>'; } }
    v = readObj2(q, depth + 1);
    if (v === null || (typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === 0)) return undefined;
    return v;
  }
  v = prim(p, fd.te); if (v === undefined || v === 0 || v === false || v === '0') return undefined;
  return v;
}
function readObj2(o, depth) {
  if (!o || o.isNull()) return null;
  var jc; try { jc = jsClass(o); } catch (e) { return '<unreadable>'; }
  if (jc.name === 'String') return str(o);
  if (depth > 6) return '<' + jc.name + '>';
  var res = {};
  fieldsOf(jc.k).forEach(function (fd) {
    if (/unknownFields/i.test(fd.name)) return;
    try { var v = readField(o, fd, depth); if (v !== undefined) res[fd.name] = v; } catch (e) { res[fd.name] = '<unreadable>'; }
  });
  return res;
}
"""
JS_EXPORTS = r"""
rpc.exports = {
  index: function (img, from, n) {
    var im = imageOf(img); if (!im) return {err: 'no image ' + img};
    var ix = IDX[img] || (IDX[img] = {map: Object.create(null), total: IL.classCount(im)}), t = Date.now(), end = Math.min(ix.total, from + n);
    for (var j = from; j < end; j++) { var k = IL.classAt(im, j); if (k.isNull()) continue; var nm = cs(IL.className(k)); (ix.map[nm] || (ix.map[nm] = [])).push(k); }
    return {next: end, total: ix.total, ms: Date.now() - t};
  },
  scanKeep: function (img, q, max) {
    var k = findQ(img, q); if (!k) return {err: 'no class ' + q};
    var t = Date.now(), a = instances(k, max || 2000); KEEP[q] = a;
    return {n: a.length, ms: Date.now() - t};
  },
  page: function (q, from, n, depth0) {
    var a = KEEP[q] || [], out = [];
    for (var i = from; i < Math.min(a.length, from + n); i++) { try { out.push(readObj2(a[i], depth0 || 0)); } catch (e) { out.push({_err: String(e)}); } }
    return out;
  },
  newMons: function (img, q, max, sinceMs, cap) {
    var k = findQ(img, q); if (!k) return {err: 'no class ' + q};
    var fds = fieldsOf(k), ctOff = -1;
    fds.forEach(function (fd) { if (/^creationTimeMs_?$/i.test(fd.name)) ctOff = fd.off; });
    if (ctOff < 0) return {err: 'no creationTimeMs field'};
    var t = Date.now(), a = instances(k, max), scanMs = Date.now() - t, since = Number(sinceMs), out = [], n = 0;
    for (var i = 0; i < a.length; i++) {
      var ct; try { ct = Number(a[i].add(ctOff).readS64().toString()); } catch (e) { continue; }
      if (ct >= since) { n++; if (out.length < cap) { try { out.push(readObj2(a[i], 0)); } catch (e) { out.push({_err: String(e)}); } } }
    }
    return {n_all: a.length, n_new: n, scan_ms: scanMs, ms: Date.now() - t, rows: out};
  }
};
"""


class CallTimeout(RuntimeError):
    pass


def call(fn, *args, timeout=45):
    """One RPC call with a deadline (short calls release Frida's shared JS lock between them)."""
    box = {}

    def run():
        try:
            box["r"] = fn(*args)
        except Exception as e:  # noqa: BLE001
            box["e"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise CallTimeout("export call still running after %d s" % timeout)
    if "e" in box:
        raise box["e"]
    return box.get("r")


def read_game(since_ms):
    """One attach: Power Spots, the Pokedex, catches since `since_ms`. Returns the raw read."""
    sys.path[:0] = [AC, HERE]
    import pogo_il2cpp as pg          # noqa: E402 -- frida lives here; CI has none, so imported only for a read
    import dump_game_limits as dl     # noqa: E402
    import scan_game as sg            # noqa: E402
    import cutoff_hunt as ch          # noqa: E402
    pg.BUSY_NAME = "PhoneMaint-powerspots/%d" % os.getpid()
    t0 = time.time()

    def log(msg):
        print("%s +%5.1fs %s" % (time.strftime("%H:%M:%S"), time.time() - t0, msg), flush=True)
    here = ch.fix()
    R = {"read_at": time.strftime("%Y-%m-%d %H:%M:%S"), "here": [here[0], here[1]] if here else None, "since_ms": since_ms,
         "data": {}, "new_mons": None, "errors": [], "meta": {}}
    version, pid0 = sg.preflight()
    before = sg.pogo_tombstones()
    R["meta"].update(game_version=version, pid=pid0)
    try:
        sess, pid = pg.get_session()
    except Exception as e:  # noqa: BLE001
        sys.exit("STOP: attach failed (%s: %s) -- not retried; nothing was read" % (type(e).__name__, e))
    log("attached pid %d (game %s)" % (pid, version))
    sc = None
    try:
        sc = sess.create_script(dl.JS.split("rpc.exports = {")[0] + JS_HELPERS + JS_EXPORTS)
        sc.load()
        ex = sc.exports_sync
        nxt = 0
        while True:
            r = call(ex.index, PROTOS, nxt, 2500)
            if r.get("err"):
                raise RuntimeError(r["err"])
            nxt = r["next"]
            if nxt >= r["total"]:
                break
        slow = False
        for q, per in ((STATION, 60), (DEX, 30)):
            r = call(ex.scan_keep, PROTOS, q, 30000)
            if not r or r.get("err"):
                R["errors"].append("scan %s: %s" % (q, (r or {}).get("err")))
                continue
            rows = []
            for i in range(0, r["n"], per):
                rows.extend(call(ex.page, q, i, per, 0) or [])
            R["data"][q] = rows
            log("%-24s %5d records (heap scan %d ms)" % (q.split(".")[-1], r["n"], r["ms"]))
            if r["ms"] > SLOW_SCAN_MS:
                R["errors"].append("slow scan %s: %d ms; later reads skipped" % (q, r["ms"]))
                log("  slow heap scan: the rest is skipped (protecting the game)")
                slow = True
                break
        if since_ms and not slow:
            r = call(ex.new_mons, PROTOS, MON, 40000, str(since_ms), 400, timeout=60)
            R["new_mons"] = r
            if r and not r.get("err"):
                log("PokemonProto: %d in memory, %d created since the bag database was written" % (r["n_all"], r["n_new"]))
    except CallTimeout as e:
        R["errors"].append("TIMEOUT: %s" % e)
        log("!! %s -- detaching now" % e)
    except Exception as e:  # noqa: BLE001
        R["errors"].append("%s: %s" % (type(e).__name__, e))
        log("!! %s: %s" % (type(e).__name__, e))
    finally:
        try:
            if sc is not None:
                sc.unload()
        except Exception:  # noqa: BLE001
            pass
        try:
            sess.detach()
        except Exception:  # noqa: BLE001
            pass
        log("detached")
    time.sleep(5)
    after = sg.sh("pidof %s" % sg.PKG).strip().split()
    new_tomb = {k: v for k, v in sg.pogo_tombstones().items() if before.get(k) != v}
    ok = bool(after) and int(after[0]) == pid and not new_tomb
    R["meta"]["post"] = {"ok": ok, "pid_after": after[0] if after else None, "new_tombstones": new_tomb}
    log(("POST ok: " if ok else "POST FAIL: ") + "PoGo pid %d -> %s, new PoGo tombstones %d" % (pid, after[0] if after else "GONE", len(new_tomb)))
    return R


def read_bag(db_path, forms):
    """Dynamax / Gigantamax mons in the bag as of the last walk: [(pid, mode, form key, gender)], and when it was written."""
    if not os.path.exists(db_path):
        return [], None
    con = sqlite3.connect("file:" + db_path.replace("\\", "/") + "?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT pokemon_id, fresh_bread_mode, form, gender FROM pokemon WHERE in_bag=1 AND fresh_bread_mode IN (1, 2)").fetchall()
    finally:
        con.close()
    return [(p, m, form_key(f or 0, forms), g) for p, m, f, g in rows], os.path.getmtime(db_path)


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- offline checks (CI)
def selftest(data=DATA):
    def T(pid, name, form=None, br=()):
        ps = {"pokemonId": name, "evolutionBranch": list(br)}
        if form:
            ps["form"] = form
        return {"templateId": "V%04d_POKEMON_%s" % (pid, form or name), "data": {"pokemonSettings": ps}}
    stone = {"evolutionItemRequirement": "ITEM_GEN4_EVOLUTION_STONE", "candyCost": 100}
    gm = GameMaster([
        T(25, "PIKACHU", br=[{"evolution": "RAICHU", "candyCost": 50}]),
        T(25, "PIKACHU", "PIKACHU_NORMAL", [{"evolution": "RAICHU", "candyCost": 50}]),
        T(26, "RAICHU"),
        T(111, "RHYHORN", br=[{"evolution": "RHYDON", "candyCost": 25, "form": "RHYDON_NORMAL"}]),
        T(112, "RHYDON", "RHYDON_NORMAL", [dict(stone, evolution="RHYPERIOR", form="RHYPERIOR_NORMAL")]),
        T(464, "RHYPERIOR", "RHYPERIOR_NORMAL"),
        T(215, "SNEASEL", br=[dict(stone, evolution="WEAVILE")]),
        T(215, "SNEASEL", "SNEASEL_NORMAL", [dict(stone, evolution="WEAVILE")]),
        T(215, "SNEASEL", "SNEASEL_HISUIAN", [{"evolution": "SNEASLER", "candyCost": 100, "onlyDaytime": True,
                                             "questDisplay": [{"questRequirementTemplateId": "SNEASLER_EVOLUTION_QUEST"}]}]),
        T(461, "WEAVILE"), T(903, "SNEASLER"),
        T(415, "COMBEE", br=[{"evolution": "VESPIQUEN", "candyCost": 50, "genderRequirement": "FEMALE"}]),
        T(416, "VESPIQUEN"),
        T(884, "DURALUDON"),
    ])
    forms = {0: "Unset", 598: "PikachuNormal", 797: "SneaselNormal", 2794: "SneaselHisuian", 1715: "CombeeNormal", 3208: "DuraludonNormal"}
    looks = {25, 26, 415}
    assert form_key(0, forms) == "" and form_key(598, forms) == "" and form_key("Unset") == ""
    assert form_key(2794, forms) == form_key("SNEASEL_HISUIAN") == "sneaselhisuian"
    assert cost({"candyCost": 100, "kmBuddyDistanceRequirement": 20.0, "questDisplay": [{"questRequirementTemplateId": "MILOTIC_EVOLUTION_QUEST"}]}) == "100 candy, 20 km as buddy"
    assert cost(dict(stone)) == "100 candy, Sinnoh Stone"
    assert cost({"candyCost": 25, "lureItemRequirement": "ITEM_TROY_DISK_MOSSY"}) == "25 candy, at a Mossy Lure"
    assert "Sylveon quest" in cost({"candyCost": 25, "questDisplay": [{"questRequirementTemplateId": "SYLVEON_EVOLUTION_QUEST"}]})

    def entry(n, cats=(), bread=()):
        return {"PokedexEntryNumber": n, "CategoryStatus": {c: {"Acquired": True} for c in cats},
                "BreadDexData": [{"ModifierId": m, "GendersObtained": list(g)} for m, g in bread]}
    entries = [entry(25, ["BREAD_MODE"], [(1, [1])]), entry(25, ["BREAD_DOUGH_MODE"], [(2, [1, 2])]),   # duplicate record: union
               entry(26, ["BREAD_MODE"], [(1, [1])]), entry(111, ["BREAD_MODE"]), entry(112, ["BREAD_MODE"]), entry(464),
               entry(215, ["BREAD_MODE"], [(1, [2])]), entry(461), entry(903), entry(415, ["BREAD_MODE"], [(1, [1])]), entry(416),
               entry(884)] + [entry(2000 + i) for i in range(100)]
    dex = dex_index(entries)
    assert dex[25]["cats"] == {"BREAD_MODE", "BREAD_DOUGH_MODE"} and dex[25]["genders"][2] == {1, 2}, "duplicate records are unioned"
    here = (51.5106, -0.1234)

    def station(i, pid, form, gender, stars, dlat, boss=True):
        s = {"Id": "spot%d" % i, "Name": "Spot %d" % i, "Lat": here[0] + dlat, "Lng": here[1], "IsBreadBattleAvailable": True}
        if boss:
            s["BattleDetails"] = {"BattleLevel": stars, "BattleWindowEndMs": "1795064400000",
                                  "BattlePokemon": {"pokemonId_": pid, "pokemonDisplay_": {"Form": form, "Gender": gender, "BreadModeEnum": 1}}}
        return s
    stations = [station(1, 25, 598, 2, 1, 0.005, boss=False), station(1, 25, 598, 2, 1, 0.005), station(1, 25, 598, 2, 1, 0.005),
                station(2, 111, 0, 1, 1, 0.002), station(3, 215, 797, 1, 2, 0.003), station(4, 415, 1715, 1, 1, 0.004),
                station(5, 884, 3208, 2, 4, 0.010)]
    bag = [(112, 1, "", 1), (112, 1, "", 2), (111, 1, "", 1), (215, 1, "", 2), (215, 1, "", 2), (415, 1, "", 1), (25, 1, "", 1)]
    read = {"read_at": "2026-11-18 15:31:00", "here": list(here), "data": {STATION: stations, DEX: entries},
            "new_mons": {"rows": [{"id_": "9", "pokemonId_": 415, "pokemonDisplay_": {"BreadModeEnum": 1, "Gender": 2, "Form": 1715}}]}}
    res = compare(read, gm, forms, looks, bag)
    assert len(res["spots"]) == 5, "duplicate spot records count once and the record with the boss wins"
    assert [g["key"] for g in res["tier1"]] == ["Dynamax Duraludon"]
    assert sorted(g["key"] for g in res["tier2"]) == ["female Dynamax Pikachu", "female Dynamax Raichu"], res["tier2"]
    t3 = {gm.label(t): tg for grp in res["tier3"] for t, tg in grp["targets"].items()}
    assert sorted(t3) == ["Rhyperior", "Weavile"], sorted(t3)
    assert t3["Rhyperior"]["hold"] == [(111, 1), (112, 2)] and "Sinnoh Stone" in t3["Rhyperior"]["cost"] and "Rhydon: 25 candy" in t3["Rhyperior"]["cost"]
    assert t3["Weavile"]["hold"] == [(215, 2)]
    why = {gm.label(b["target"]): b["why"] for b in res["blocked"]}
    assert sorted(why) == ["Sneasler", "Vespiquen"] and "Hisuian" in why["Sneasler"] and "female" in why["Vespiquen"], why
    # a female Combee boss gives Vespiquen; only the female Combee he caught since the walk can evolve into it
    stations.append(station(6, 415, 1715, 2, 1, 0.006))
    res2 = compare(read, gm, forms, looks, bag)
    t3b = {gm.label(t): tg for grp in res2["tier3"] for t, tg in grp["targets"].items()}
    assert "Vespiquen" in t3b and t3b["Vespiquen"]["hold"] == [(415, 1)] and "Vespiquen" not in {gm.label(b["target"]) for b in res2["blocked"]}
    # a Hisuian Sneasel boss gives Sneasler (and never Weavile)
    assert [gm.label(t) for t, _, _ in gm.paths(215, "SneaselHisuian", 1)] == ["Sneasler"]
    assert [gm.label(t) for t, _, _ in gm.paths(215, "SneaselNormal", 1)] == ["Weavile"]
    # an incomplete Pokedex read claims nothing
    small = dict(read, data={STATION: stations, DEX: entries[:12]})
    res3 = compare(small, gm, forms, looks, bag)
    assert not (res3["tier1"] or res3["tier2"] or res3["tier3"] or res3["blocked"]) and "STOP" in "\n".join(summary(res3))
    lines, page = "\n".join(summary(res)), page_html(res)
    assert "NEW species: Dynamax Duraludon" in lines and "Not here: Dynamax Sneasler" in lines and "you hold Rhyhorn x1, Rhydon x2" in lines
    assert "Dynamax Rhyperior" in page and "Not possible here" in page and "All 5 Power Spots" in page and "<script>" in page
    msg = "selftest ok: tiers, per-form and gender evolution traps, dedupe, holders, incomplete-read guard, page"
    gpath = os.path.join(data, "gamemaster_pokeminers.json")
    if os.path.exists(gpath):
        real = GameMaster(load_json(gpath))
        reach = {k: sorted(real.label(t) for t, _, _ in real.paths(*k)) for k in
                 [(215, "SneaselNormal", 1), (215, "SneaselHisuian", 2), (415, "CombeeNormal", 1), (415, "CombeeNormal", 2), (25, "PikachuNormal", 2)]}
        assert reach[(215, "SneaselNormal", 1)] == ["Weavile"] and reach[(215, "SneaselHisuian", 2)] == ["Sneasler"], reach
        assert reach[(415, "CombeeNormal", 1)] == [] and reach[(415, "CombeeNormal", 2)] == ["Vespiquen"], reach
        assert "Raichu" in reach[(25, "PikachuNormal", 2)], reach
        msg += "; real game master: Sneasel/Combee/Pikachu branches ok"
    print(msg)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Power Spots near you vs your Dynamax collection (read-only).")
    ap.add_argument("--from", dest="src", help="a saved read (power_spots_*.json): redo the comparison, no phone")
    ap.add_argument("--at", help="LAT,LNG to measure distances from (with --from)")
    ap.add_argument("--data", default=DATA, help="the pogo_extract folder (game master, form names, gender looks, pokemon.db)")
    ap.add_argument("--selftest", action="store_true", help="offline checks (CI)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.selftest:
        return selftest(a.data)
    gpath = os.path.join(a.data, "gamemaster_pokeminers.json")
    if not os.path.exists(gpath):
        sys.exit("STOP: no game master at %s (pass --data <pogo_extract folder>)" % gpath)
    forms = {int(k): v for k, v in load_json(os.path.join(a.data, "form_enum.json")).items()}
    looks = set(load_json(os.path.join(a.data, "gender_variants.json")).get("pids") or [])
    gm = GameMaster(load_json(gpath))
    bag, bag_at = read_bag(os.path.join(a.data, "pokemon.db"), forms)
    at = tuple(float(x) for x in a.at.split(",")) if a.at else None
    if a.src:
        read, stem = load_json(a.src), os.path.splitext(a.src)[0]
    else:
        read = read_game(int(bag_at * 1000) if bag_at else 0)
        os.makedirs(OUT_DIR, exist_ok=True)
        stem = os.path.join(OUT_DIR, "power_spots_" + time.strftime("%Y-%m-%d_%H%M"))
        with open(stem + ".json", "w", encoding="utf-8") as fh:
            json.dump(read, fh, indent=0)
    res = compare(read, gm, forms, looks, bag, at=at, bag_at=bag_at)
    if bag_at:
        print("bag as of %s (pokemon.db), plus Dynamax catches read since" % time.strftime("%m-%d %H:%M", time.localtime(bag_at)))
    print("\n".join(summary(res)))
    with open(stem + ".html", "w", encoding="utf-8") as fh:
        fh.write(page_html(res))
    print("page: %s.html" % stem)
    return 0 if res["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
