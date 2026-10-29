"""What changed in the game between two scans (offline, no phone).

  python tools/scan_diff.py BASE_LIMITS NEW_LIMITS [BASE_CONSTANTS NEW_CONSTANTS]

Inputs are the files tools/dump_game_limits.py and tools/dump_game_constants.py write. Outputs:
  system/analysis/scan_diff.json   every change, machine-readable
  system/analysis/scan_diff.html   the report (API keys are never printed: any value under a *Key* path is hidden)

How the two dumps are compared:
  * limits: GlobalSettingsProto and every game-master settings message are flattened to dotted paths
    ("FortSettings.InteractionRangeMeters"). The dumps leave out proto3 defaults (0 / false / empty), so a path that
    disappears means "now 0 / off / unset", not "deleted".
  * constants: about three quarters of the field names are scrambled by the game's obfuscator and get NEW names every
    release, so a name-to-name match would report thousands of fake renames. Readable names are matched by name;
    scrambled ones are compared as the multiset of (kind, type, value) per class: a value that appears or disappears
    in a class is a real change, a rename alone is not.
Each change is tagged with the project process it can touch (catcher, spinner, joystick speeds, cull, ...).
"""
import html
import json
import os
import re
import sys
import time
from collections import Counter

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
OUT_JSON = os.path.join(ROOT, "system", "analysis", "scan_diff.json")
OUT_HTML = os.path.join(ROOT, "system", "analysis", "scan_diff.html")
SECRET = re.compile(r"(?i)(api_?key|token|secret|clientid|allowlist|password|url$)")   # limits_report.py's list + password
SCRAMBLED = re.compile(r"[a-z]{3,5}")

# which of OUR processes a setting can touch (first match wins; order = most specific first)
AREAS = [
    (r"ClientAppBlacklist", "spoof safety"),
    (r"Tappable|Maple", "map pickups (boxes, apples)"),
    (r"Incense|Lure|Troy|Disk", "catcher (incense, lures)"),
    (r"Catch|Encounter|Pokeball|Throw|Berry|Razz|Pinap|Flee", "catcher"),
    (r"PowerUpPokestop|Fort|Pokestop|Spin", "auto-spin, routes"),
    (r"Gps|Driving|Idle|Speed|Velocity", "joystick speeds, walking"),
    (r"Egg|Incubat|Hatch|AdventureSync|Fitness|Distance|Walk", "eggs, walking credit"),
    (r"Buddy", "buddy"),
    (r"Raid|Gym|Defender|Motivation|Deploy", "gyms (runner stopped)"),
    (r"Route", "routes"),
    (r"Quest|Research|Challenge", "rewards, quest log"),
    (r"Contest|Showcase", "showcase rule (cull)"),
    (r"Inventory|Storage|ItemBag|Bag|Upgrade|Recycle", "bag and storage (cull)"),
    (r"Combat|Pvp|League", "PvP ranks (cull)"),
    (r"Evolution|Evolve|Mega|TempEvo|Fusion", "evolve and mega (cull)"),
    (r"Trade|Friend|Social|Gift|Party", "friends, trades, party"),
    (r"Station|PowerSpot|Bread|Dynamax|Gmax|MaxBattle", "Power Spots, Max"),
    (r"MapSettings|MapObjects|GetMapObjects|Visible|Map", "catcher, map scanner"),
    (r"Weather", "weather"),
    (r"Rocket|Invasion|Incident|Grunt", "Team Rocket"),
    (r"Pokedex|Dex", "dex"),
    (r"Event|Seasonal|Halloween|Holiday", "events"),
    (r"Avatar|Neutral|Sticker|Store|Iap|Purchase|Telemetry|ArPhoto|ARPhoto|ArBackend|Accessibility|Notification|News|"
     r"Login|Address|Survey|Ad[A-Z]|Ads|Shop|Sku|Camera|Photo|Vps|Ar[A-Z]", "app/UI (not ours)"),
]
OURS = {a for _, a in AREAS} - {"app/UI (not ours)", "Team Rocket", "weather", "dex", "events"}


def area(path):
    for rx, name in AREAS:
        if re.search(rx, path):
            return name
    return "other"


def flatten(o, prefix=""):
    out = {}
    if isinstance(o, dict):
        for k, v in o.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(o, list):
        if all(not isinstance(x, (dict, list)) for x in o):
            out[prefix] = o
        else:
            for i, v in enumerate(o):
                out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = o
    return out


def _shown(path, v):
    """The value as the report may show it: anything under a key/token/secret path is hidden, at any depth."""
    if SECRET.search(path.split(".")[-1] if path else ""):
        return "(hidden)"
    if isinstance(v, dict):
        return {k: _shown(k, x) for k, x in v.items()}
    if isinstance(v, list):
        return [_shown(path, x) if not isinstance(x, (dict, list)) else _shown("", x) for x in v]
    return v


def diff_flat(old, new, where):
    rows = []
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k, None), new.get(k, None)
        if k in old and k in new and a == b:
            continue
        kind = "added" if k not in old else ("now 0 / off / unset" if k not in new else "changed")
        full = f"{where}.{k}" if where else k
        rows.append({"path": full, "kind": kind, "old": _shown(full, a), "new": _shown(full, b), "area": area(full)})
    return rows


def load_limits(path):
    d = json.load(open(path, encoding="utf-8"))
    gm = {}
    for x in d.get("game_master_settings") or []:
        t = x.get("type") or "?"
        if t.startswith("error@"):
            continue
        gm[t] = x.get("data") or {}
    return d, flatten(d.get("global_settings") or {}), gm


def diff_limits(base_path, new_path):
    bd, bg, bgm = load_limits(base_path)
    nd, ng, ngm = load_limits(new_path)
    rows = diff_flat(bg, ng, "GlobalSettings")
    added_types = sorted(set(ngm) - set(bgm))
    gone_types = sorted(set(bgm) - set(ngm))
    for t in sorted(set(bgm) & set(ngm)):
        rows += diff_flat(flatten(bgm[t]), flatten(ngm[t]), t)
    for t in added_types:
        rows.append({"path": t, "kind": "new settings type", "old": None, "new": _shown(t, ngm[t]), "area": area(t)})
    for t in gone_types:
        rows.append({"path": t, "kind": "settings type gone", "old": _shown(t, bgm[t]), "new": None, "area": area(t)})
    meta = {"base": {"file": os.path.basename(base_path), "read_at": bd.get("read_at"), "version": bd.get("game_version")},
            "new": {"file": os.path.basename(new_path), "read_at": nd.get("read_at"), "version": nd.get("game_version")},
            "global_paths": [len(bg), len(ng)], "gm_types": [len(bgm), len(ngm)]}
    return rows, meta


def diff_constants(base_path, new_path):
    b = json.load(open(base_path, encoding="utf-8"))
    n = json.load(open(new_path, encoding="utf-8"))
    rows, stats = [], Counter()

    def split(d):
        named, groups = {}, {}
        for r in d.get("constants") or []:
            cls = f"{r['image']}:{r['ns']}.{r['class']}" if r["ns"] else f"{r['image']}:{r['class']}"
            if SCRAMBLED.fullmatch(r["field"]):
                groups.setdefault((cls, r["kind"], r["type"]), Counter())[json.dumps(r["value"], sort_keys=True)] += 1
            else:
                named[(cls, r["field"], r["kind"])] = r
        return named, groups

    bn, bgr = split(b)
    nn, ngr = split(n)
    for k in sorted(set(bn) | set(nn)):
        a, c = bn.get(k), nn.get(k)
        if a and c and a["value"] == c["value"]:
            stats["named same"] += 1
            continue
        cls, field, kind = k
        path = f"{cls}.{field}"
        if a and c:
            stats["named changed"] += 1
            rows.append({"path": path, "kind": "changed", "old": a["value"], "new": c["value"], "type": c["type"], "area": area(path)})
        elif c:
            stats["named added"] += 1
            rows.append({"path": path, "kind": "added", "old": None, "new": c["value"], "type": c["type"], "area": area(path)})
        else:
            stats["named gone"] += 1
            rows.append({"path": path, "kind": "gone", "old": a["value"], "new": None, "type": a["type"], "area": area(path)})
    for k in sorted(set(bgr) | set(ngr)):
        a, c = bgr.get(k, Counter()), ngr.get(k, Counter())
        if a == c:
            stats["scrambled groups same"] += 1
            continue
        cls, kind, typ = k
        lost, got = a - c, c - a
        if not lost and not got:
            continue
        stats["scrambled groups changed"] += 1
        rows.append({"path": f"{cls} ({kind} {typ}, scrambled names)", "kind": "values changed",
                     "old": sorted(json.loads(x) for x in lost.elements()) if lost else [],
                     "new": sorted(json.loads(x) for x in got.elements()) if got else [], "type": typ,
                     "area": area(cls)})
    meta = {"base": {"file": os.path.basename(base_path), "read_at": b.get("read_at"), "version": b.get("game_version"),
                     "rows": len(b.get("constants") or [])},
            "new": {"file": os.path.basename(new_path), "read_at": n.get("read_at"), "version": n.get("game_version"),
                    "rows": len(n.get("constants") or [])},
            "stats": dict(stats)}
    return rows, meta


def _fmt(v):
    if v is None:
        return "—"
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= 400 else s[:400] + " …"


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Game Scan Diff</title>
<style>
:root { --bg:#fafaf8; --fg:#1d1d1b; --mut:#6b6b66; --line:#e4e2dc; --card:#fff; --add:#1a7f45; --chg:#9a6700; --gone:#b42318; --chip:#f1efe9; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#141413; --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; --add:#4cc38a; --chg:#e3b341; --gone:#f97066; --chip:#24231f; } }
:root[data-theme="dark"] { --bg:#141413; --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; --add:#4cc38a; --chg:#e3b341; --gone:#f97066; --chip:#24231f; }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width:1100px; margin:0 auto; padding:20px 16px 60px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:16px; margin:28px 0 8px; } .mut { color:var(--mut); font-size:13px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:14px 0; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 12px; }
.card b { display:block; font-size:22px; font-variant-numeric:tabular-nums; }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0; } .chip { background:var(--chip); border:1px solid var(--line); border-radius:999px; padding:3px 10px; cursor:pointer; font-size:13px; }
.chip.on { outline:2px solid var(--fg); }
table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; font-size:13px; }
th { font-weight:600; color:var(--mut); } td.v { font-family:ui-monospace,Consolas,monospace; word-break:break-word; max-width:320px; }
.k-added, .k-new { color:var(--add); } .k-changed, .k-values { color:var(--chg); } .k-gone, .k-now { color:var(--gone); }
.wrap { overflow-x:auto; }
</style></head><body><main>
<h1>What changed in the game</h1>
<div class="mut">%META%</div>
<div class="cards">%CARDS%</div>
<div class="mut">Filter by the process a change can touch:</div>
<div class="chips" id="chips"></div>
%SECTIONS%
</main>
<script>
var chips = document.getElementById('chips'), on = null;
var areas = {}; document.querySelectorAll('tr[data-a]').forEach(function (r) { var a = r.getAttribute('data-a'); areas[a] = (areas[a] || 0) + 1; });
Object.keys(areas).sort(function (a, b) { return areas[b] - areas[a]; }).forEach(function (a) {
  var c = document.createElement('span'); c.className = 'chip'; c.textContent = a + ' (' + areas[a] + ')';
  c.onclick = function () { on = on === a ? null : a; document.querySelectorAll('.chip').forEach(function (x) { x.classList.toggle('on', x === c && on === a); });
    document.querySelectorAll('tr[data-a]').forEach(function (r) { r.style.display = !on || r.getAttribute('data-a') === on ? '' : 'none'; }); };
  chips.appendChild(c);
});
</script></body></html>"""


def table(rows, cols):
    if not rows:
        return '<p class="mut">No changes.</p>'
    out = ['<div class="wrap"><table><tr>' + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"]
    for r in rows:
        k = r["kind"].split()[0]
        out.append(f'<tr data-a="{html.escape(r["area"])}"><td>{html.escape(r["path"])}</td><td class="k-{k}">{html.escape(r["kind"])}</td>'
                   f'<td class="v">{html.escape(_fmt(r["old"]))}</td><td class="v">{html.escape(_fmt(r["new"]))}</td>'
                   f'<td>{html.escape(r["area"])}</td></tr>')
    out.append("</table></div>")
    return "".join(out)


def order(rows):
    return sorted(rows, key=lambda r: (r["area"] not in OURS, r["area"], r["path"]))


def write(lim_rows, lim_meta, con_rows=None, con_meta=None):
    res = {"written": time.strftime("%Y-%m-%d %H:%M:%S"), "limits": {"meta": lim_meta, "changes": order(lim_rows)}}
    if con_meta is not None:
        res["constants"] = {"meta": con_meta, "changes": order(con_rows)}
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False)
    ours = [r for r in lim_rows + (con_rows or []) if r["area"] in OURS]
    cards = [("settings changes", len(lim_rows)), ("touch our processes", len(ours)),
             ("new settings types", sum(1 for r in lim_rows if r["kind"] == "new settings type")),
             ("settings types gone", sum(1 for r in lim_rows if r["kind"] == "settings type gone"))]
    if con_meta is not None:
        cards.append(("constant changes", len(con_rows)))
    b, n = lim_meta["base"], lim_meta["new"]
    meta = (f"Base: game {html.escape(str(b.get('version') or '?'))}, read {html.escape(str(b.get('read_at')))} · "
            f"New: game {html.escape(str(n.get('version') or '?'))}, read {html.escape(str(n.get('read_at')))} · "
            f"written {res['written']}. Values under a key/token path are hidden.")
    secs = ['<h2>Settings the server sends (global settings + game master settings)</h2>',
            '<p class="mut">A value that is "now 0 / off / unset" left the dump because proto3 drops defaults.</p>',
            table(order(lim_rows), ["Setting", "Change", "Before", "Now", "Can touch"])]
    if con_meta is not None:
        st = con_meta.get("stats") or {}
        secs += ['<h2>Numbers hard-coded in the game</h2>',
                 f'<p class="mut">{con_meta["base"]["rows"]} → {con_meta["new"]["rows"]} values. Scrambled names change every release, '
                 f'so those are compared by value per class ({st.get("scrambled groups changed", 0)} classes changed, '
                 f'{st.get("scrambled groups same", 0)} unchanged).</p>',
                 table(order(con_rows), ["Constant", "Change", "Before", "Now", "Can touch"])]
    page = (PAGE.replace("%META%", meta)
                .replace("%CARDS%", "".join(f'<div class="card"><b>{v}</b>{html.escape(k)}</div>' for k, v in cards))
                .replace("%SECTIONS%", "".join(secs)))
    with open(OUT_HTML, "w", encoding="utf-8") as fh:
        fh.write(page)
    return res, ours


def summary(res, ours, top=12):
    lines = []
    for sect in ("limits", "constants"):
        if sect not in res:
            continue
        ch = res[sect]["changes"]
        lines.append(f"{sect}: {len(ch)} changes, {sum(1 for r in ch if r['area'] in OURS)} touch our processes")
    for r in ours[:top]:
        lines.append(f"  [{r['area']}] {r['path']}: {r['kind']} {_fmt(r['old'])} -> {_fmt(r['new'])}"[:240])
    if len(ours) > top:
        lines.append(f"  ... {len(ours) - top} more in {OUT_HTML}")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if len(args) not in (2, 4) or any(a.startswith("-") for a in args):
        print(__doc__)
        sys.exit(2)
    lim_rows, lim_meta = diff_limits(args[0], args[1])
    con_rows = con_meta = None
    if len(args) == 4:
        con_rows, con_meta = diff_constants(args[2], args[3])
    res, ours = write(lim_rows, lim_meta, con_rows, con_meta)
    print(summary(res, order(ours)))
    print(f"wrote {OUT_JSON} and {OUT_HTML}")


if __name__ == "__main__":
    main()
