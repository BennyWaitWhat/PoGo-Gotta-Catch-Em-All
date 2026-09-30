"""Turn system/analysis/game_constants.json (from dump_game_constants.py) into a readable HTML page."""
import html
import json
import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
SRC = os.path.join(ROOT, "system", "analysis", "game_constants.json")
OUT = os.path.join(ROOT, "system", "analysis", "game_constants.html")
SECRET = re.compile(r"KEY|VECTOR|SECRET|TOKEN|PASSWORD|SALT", re.I)
SCRAMBLED = re.compile(r"[a-z]{3,5}")

# (class, field or None for every field, plain-English note) -- the numbers themselves always come from the dump
HIGHLIGHTS = [
    ("Niantic.Holoholo.Map.SpeedService", None, "The game's speed tracker. 8.9408 m/s is the same 20 mph as the server's driving "
     "warning (GpsSettings); the other three are unnamed (scrambled) and their use is not traced."),
    ("Niantic.Holoholo.Map.MapPokemon", "CATCH_POKEMON_RPC_TIMEOUT_SEC", "How long a throw waits for the server's catch reply."),
    ("Niantic.Holoholo.Rpc.RpcRequest`1", None, "Server request retries: first retry after 10 s, backing off to at most 60 s."),
    ("Niantic.Holoholo.Map.NativeLocationProvider", None, "Location provider distance constant (meters, by its value; name scrambled)."),
    ("Niantic.Holoholo.Services.MapObjectRepositioningService", None, "How far map objects are nudged away from your avatar and each other (meters)."),
    ("Niantic.Holoholo.Gym.RaidTopperPresentation", None, "Raid coin/topper visible range (meters)."),
    ("Niantic.Holoholo.Map.AbstractMapPlace", None, "Map geometry: latitude cutoff (degrees) and meters-to-map-unit scale."),
    ("Niantic.Holoholo.Routes.RoutesLocationService", None, "Route tracking timers (seconds / milliseconds)."),
    ("Niantic.Platform.SocialWebview.Internal.CampfireClientSettings", None, "Campfire location upload interval: fast 20 s, slow 15 min."),
    ("Niantic.Platform.SocialWebview.Internal.NativeLocationProvider", None, "Campfire/social location timeout and change threshold."),
    ("Niantic.Holoholo.Services.ClientInboxService.ClientInboxService", None, "Inbox refresh cooldown and longest interval (seconds)."),
    ("Holoholo.Rpc.PokemonProto", None, "IV cap per stat, number of IVs, and the minimum CP."),
    ("Niantic.Holoholo.Buddy.BuddyPokemonService", None, "Buddy candy distance multiplier."),
    ("Niantic.Holoholo.PlayerService", None, "Unnamed (scrambled) player-service numbers; use not traced."),
    ("Niantic.Holoholo.SpaceTimeThrottle", None, "A throttle keyed on distance and time; one unnamed constant."),
    ("Google.Common.Geometry.S2LatLng", "EarthRadiusMeters", "Earth radius the map's S2 geometry uses."),
]


def cls(r):
    return (r["ns"] + "." if r["ns"] else "") + r["class"]


def fmt(r):
    v = r["value"]
    if SECRET.search(r["field"]):
        return "(hidden)"
    if isinstance(v, dict) and "values" in v:
        s = json.dumps(v["values"])
        s = s if len(s) <= 160 else s[:160] + " ..."
        return html.escape(f"[{v['count']} values] {s}")
    if isinstance(v, dict) and "seconds" in v:
        return html.escape(f"{v['seconds']:g} s")
    s = json.dumps(v)
    if isinstance(v, float) and 0 < abs(v) < 1e6:
        s = f"{v:.7g}"
    return html.escape(s)


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    rows = d["constants"]
    named = [r for r in rows if not SCRAMBLED.fullmatch(r["field"])]
    scrambled = len(rows) - len(named)
    P = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PoGo Constants</title>
<style>
:root {{ --bg:#fafaf8; --fg:#1d1d1b; --mut:#6b6b66; --line:#e4e2dc; --card:#ffffff; --hl:#fff4d6; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141413; --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; --hl:#3a3220; }} }}
:root[data-theme="dark"] {{ --bg:#141413; --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; --hl:#3a3220; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:1000px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} h2 {{ font-size:18px; margin:32px 0 8px; }} .mut {{ color:var(--mut); }}
.tw {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--card); }}
table {{ width:100%; border-collapse:collapse; }}
td, th {{ padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
tr:last-child td {{ border-bottom:0; }}
th {{ font-size:13px; color:var(--mut); font-weight:600; }}
td.v {{ font-variant-numeric:tabular-nums; word-break:break-word; }}
td.p, code {{ font-family:ui-monospace,Consolas,monospace; font-size:12.5px; word-break:break-all; }}
.note {{ background:var(--hl); border:1px solid var(--line); border-radius:8px; padding:10px 12px; margin:14px 0; }}
details {{ background:var(--card); border:1px solid var(--line); border-radius:8px; margin:6px 0; }}
summary {{ cursor:pointer; padding:8px 12px; font-weight:600; }}
details table {{ border-top:1px solid var(--line); }}
input {{ width:100%; padding:9px 12px; font-size:15px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--fg); margin-bottom:8px; }}
</style></head><body><main>
<h1>Pokémon GO hard-coded constants</h1>
<div class="mut">Read from the running game&rsquo;s code on your Pixel at {html.escape(d['read_at'])}: {len(rows)} numbers
({sum(r['kind'] == 'const' for r in rows)} C# <code>const</code> values and {sum(r['kind'] != 'const' for r in rows)}
<code>static readonly</code> values from classes the game had already loaded), across {len(d['images'])} of the game&rsquo;s code
libraries. Unity, system and third-party libraries were skipped.</div>
<div class="note"><b>What this shows:</b> the game&rsquo;s own code has very few movement limits. The speed, range and cooldown
rules live in the server settings (the other page). {scrambled} of these {len(rows)} numbers have scrambled names
(Niantic obfuscates its code, e.g. <code>eisg</code>), so only the value and the class they sit in are known.</div>
<h2>Speed, location &amp; timing</h2><div class=tw><table><tr><th>Where</th><th>Values</th><th>What it is</th></tr>"""]
    for c, fld, note in HIGHLIGHTS:
        hits = [r for r in rows if cls(r) == c and (fld is None or r["field"] == fld)]
        if not hits:
            continue
        vals = "<br>".join(f"<code>{html.escape(r['field'])}</code> = {fmt(r)}" for r in hits)
        P.append(f"<tr><td class=p>{html.escape(c)}</td><td class=v>{vals}</td><td>{html.escape(note)}</td></tr>")
    P.append("</table></div>")

    P.append(f"<h2>Every named constant ({len(named)})</h2><div class=mut>Constants that kept a readable name, grouped by class.</div>")
    groups = {}
    for r in named:
        groups.setdefault((r["image"], cls(r)), []).append(r)
    P.append("<div class=tw><table><tr><th>Class</th><th>Constants</th></tr>")
    for (img, c) in sorted(groups, key=lambda x: (x[0] != "holo-game.dll", x[1].lower())):
        vals = "<br>".join(f"<code>{html.escape(r['field'])}</code> = {fmt(r)}" for r in groups[(img, c)][:40])
        P.append(f"<tr><td class=p>{html.escape(c)}<br><span class=mut>{html.escape(img)}</span></td><td class=v>{vals}</td></tr>")
    P.append("</table></div>")

    P.append(f"<h2>Everything ({len(rows)})</h2><input id=q type=search placeholder='Filter by class, name or value, e.g. Speed, Location, 8.94'>")
    byimg = {}
    for r in rows:
        byimg.setdefault(r["image"], []).append(r)
    for img in sorted(byimg, key=lambda x: (-len(byimg[x]), x)):
        P.append(f"<details class=all><summary>{html.escape(img)} <span class=mut>({len(byimg[img])})</span></summary><div class=tw><table>"
                 "<tr><th>Class</th><th>Name</th><th>Kind</th><th>Value</th></tr>")
        for r in byimg[img]:
            P.append(f"<tr><td class=p>{html.escape(cls(r))}</td><td class=p>{html.escape(r['field'])}</td>"
                     f"<td class=mut>{html.escape(r['kind'] + ' ' + r['type'])}</td><td class=v>{fmt(r)}</td></tr>")
        P.append("</table></div></details>")
    P.append("""<script>
document.getElementById('q').addEventListener('input', function (e) {
  var q = e.target.value.toLowerCase().trim();
  document.querySelectorAll('details.all').forEach(function (d) {
    var any = false;
    d.querySelectorAll('tr').forEach(function (r, i) {
      if (i === 0) return;
      var hit = !q || r.textContent.toLowerCase().indexOf(q) >= 0;
      r.style.display = hit ? '' : 'none'; any = any || hit;
    });
    d.style.display = any || !q ? '' : 'none'; d.open = !!q && any;
  });
});
</script></main></body></html>""")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(P))
    print(f"wrote {OUT}: {len(rows)} values, {len(named)} named, {scrambled} scrambled")


if __name__ == "__main__":
    main()
