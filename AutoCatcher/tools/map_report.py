"""Render system/analysis/map_full.json (from map_read.py) as an interactive map page: every stop/gym the game has
loaded, gym teams, lures, Rocket/Showcase stops, visited status, nearby/wild Pokemon, the walking loop, a heat layer."""
import html
import json
import os

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
SRC = os.path.join(ROOT, "system", "analysis", "map_full.json")
# NOT pogo_map.html: that is tools/map_live.py's live page, which this one-time snapshot used to overwrite
OUT = os.path.join(ROOT, "system", "analysis", "pogo_map_snapshot.html")
LOOP = [(40.752635, -73.984926), (40.764800, -73.976400), (40.763581, -73.973496), (40.751416, -73.982022)]


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    forts = {}
    for f in d.get("PokemonFortProto", []):
        if f.get("Latitude") and f.get("FortId"):
            forts[f["FortId"]] = f
    pts = []
    for f in forts.values():
        stop = f.get("FortType") not in (None, 0)
        disp = f.get("PokestopDisplays") or []
        disp = disp if isinstance(disp, list) else []
        rocket = any(isinstance(x, dict) and (x.get("IncidentDisplayType") or x.get("CharacterDisplay")) and not x.get("ContestDisplay") for x in disp)
        show = any(isinstance(x, dict) and x.get("ContestDisplay") for x in disp)
        lured = bool(f.get("ActiveFortModifier"))
        pts.append({"a": round(f["Latitude"], 6), "o": round(f["Longitude"], 6), "s": 1 if stop else 0,
                    "t": int(f.get("Team") or 0) if not stop else 0, "l": 1 if lured else 0, "r": 1 if rocket else 0,
                    "c": 1 if show else 0, "v": 1 if f.get("Visited") else 0, "x": 1 if f.get("IsExRaidEligible") else 0,
                    "g": f.get("GuardPokemonId") or 0, "b": 1 if f.get("IsInBattle") else 0})
    near = {}
    for n in d.get("NearbyPokemonProto", []):
        fid = n.get("FortId")
        if fid in forts:
            near.setdefault(fid, []).append(n.get("PokedexNumber") or n.get("PokemonId") or "?")
    nearby = [{"a": forts[k]["Latitude"], "o": forts[k]["Longitude"], "p": v} for k, v in near.items()]
    wild = [{"a": w["Latitude"], "o": w["Longitude"], "p": (w.get("PokemonData") or {}).get("PokemonId", "?")}
            for w in d.get("WildPokemonProto", []) if w.get("Latitude")]
    stops = sum(p["s"] for p in pts)
    gyms = len(pts) - stops
    teams = {t: sum(1 for p in pts if not p["s"] and p["t"] == t) for t in (0, 1, 2, 3)}
    stats = {"forts": len(pts), "stops": stops, "gyms": gyms, "lured": sum(p["l"] for p in pts), "rocket": sum(p["r"] for p in pts),
             "show": sum(p["c"] for p in pts), "visited": sum(p["v"] for p in pts if p["s"]), "ex": sum(p["x"] for p in pts), "teams": teams}
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PoGo Map</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<style>
:root {{ --bg:#fafaf8; --fg:#1d1d1b; --mut:#6b6b66; --line:#e4e2dc; --card:#ffffff; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141413; --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; }} }}
:root[data-theme="dark"] {{ --bg:#141413; --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; }}
* {{ box-sizing:border-box; }} html,body {{ height:100%; margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
#map {{ position:absolute; inset:0; }}
.panel {{ position:absolute; z-index:1000; top:12px; left:12px; max-width:min(330px, calc(100% - 24px)); background:var(--card); color:var(--fg);
  border:1px solid var(--line); border-radius:10px; padding:10px 12px; box-shadow:0 2px 10px rgba(0,0,0,.15); }}
.panel h1 {{ font-size:15px; margin:0 0 4px; }} .mut {{ color:var(--mut); font-size:12px; }}
.row {{ display:flex; justify-content:space-between; gap:12px; }} .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align:-1px; }}
label {{ display:block; margin:2px 0; cursor:pointer; }}
</style></head><body><div id="map"></div>
<div class="panel"><h1>Pokémon GO map (read from the game)</h1>
<div class="mut"><b>Snapshot, not live:</b> everything PoGo had loaded at {html.escape(d.get('read_at',''))}
(teams, defenders, lures and Rocket have changed since; the live bank is tools/map_live.py): {stats['forts']} stops &amp; gyms. Your walking loop in orange.</div>
<div class="row"><span><span class="dot" style="background:#2f7de1"></span>PokéStops</span><b>{stats['stops']}</b></div>
<div class="row"><span>&nbsp;&nbsp;&nbsp;you've visited</span><b>{stats['visited']}</b></div>
<div class="row"><span><span class="dot" style="background:#e84fa3"></span>lured at {html.escape(d.get('read_at','')[11:])}</span><b>{stats['lured']}</b></div>
<div class="row"><span><span class="dot" style="background:#222"></span>Team Rocket</span><b>{stats['rocket']}</b></div>
<div class="row"><span><span class="dot" style="background:#9b59d0"></span>Showcase</span><b>{stats['show']}</b></div>
<div class="row"><span>Gyms (Mystic / Valor / Instinct / open)</span><b>{teams[1]} / {teams[2]} / {teams[3]} / {teams[0]}</b></div>
<div class="row"><span>EX-raid eligible gyms</span><b>{stats['ex']}</b></div>
<div class="mut" style="margin-top:6px">Layers</div>
<label><input type="checkbox" id="lStops" checked> stops</label>
<label><input type="checkbox" id="lGyms" checked> gyms</label>
<label><input type="checkbox" id="lHeat"> stop density heat</label>
<label><input type="checkbox" id="lNear" checked> nearby Pokémon (at stops)</label>
</div>
<script>
var P = {json.dumps(pts, separators=(',', ':'))};
var NEAR = {json.dumps(nearby, separators=(',', ':'))};
var WILD = {json.dumps(wild, separators=(',', ':'))};
var LOOP = {json.dumps(LOOP)};
var map = L.map('map', {{preferCanvas: true}}).setView([40.758, -73.979], 15);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom: 19, attribution: '&copy; OpenStreetMap'}}).addTo(map);
var TEAM = ['#8a8a8a', '#2f7de1', '#e0463f', '#f2c230'];
var stops = L.layerGroup(), gyms = L.layerGroup(), near = L.layerGroup();
P.forEach(function (p) {{
  if (p.s) {{
    var col = p.r ? '#222' : (p.c ? '#9b59d0' : (p.l ? '#e84fa3' : '#2f7de1'));
    L.circleMarker([p.a, p.o], {{radius: p.l ? 6 : 4, color: p.v ? '#f0a500' : col, weight: p.v ? 2 : 1, fillColor: col, fillOpacity: .85}})
      .bindTooltip((p.l ? 'LURED stop' : p.r ? 'Team Rocket stop' : p.c ? 'Showcase stop' : 'PokéStop') + (p.v ? ' (visited)' : ''))
      .addTo(stops);
  }} else {{
    L.circleMarker([p.a, p.o], {{radius: 7, color: '#111', weight: p.x ? 3 : 1, fillColor: TEAM[p.t] || '#8a8a8a', fillOpacity: .9}})
      .bindTooltip('Gym: ' + ['open', 'Mystic', 'Valor', 'Instinct'][p.t] + (p.g ? ' · defender #' + p.g : '') + (p.x ? ' · EX-eligible' : '') + (p.b ? ' · in battle' : ''))
      .addTo(gyms);
  }}
}});
NEAR.forEach(function (n) {{ L.marker([n.a, n.o], {{icon: L.divIcon({{className: '', html: '<div style="font:600 11px system-ui;background:#fff;color:#000;border-radius:6px;padding:1px 4px;border:1px solid #999">#' + n.p.join(' #') + '</div>'}})}}).addTo(near); }});
WILD.forEach(function (w) {{ L.circleMarker([w.a, w.o], {{radius: 5, color: '#1a9e5a', fillColor: '#1a9e5a', fillOpacity: 1}}).bindTooltip('wild #' + w.p).addTo(near); }});
stops.addTo(map); gyms.addTo(map); near.addTo(map);
L.polygon(LOOP, {{color: '#ff7a00', weight: 4, fill: false}}).bindTooltip('your walking loop').addTo(map);
var heat = L.heatLayer ? L.heatLayer(P.filter(function (p) {{ return p.s; }}).map(function (p) {{ return [p.a, p.o, 0.6]; }}), {{radius: 22, blur: 18}}) : null;
function tog(id, layer) {{ document.getElementById(id).addEventListener('change', function (e) {{ if (!layer) return; e.target.checked ? layer.addTo(map) : map.removeLayer(layer); }}); }}
tog('lStops', stops); tog('lGyms', gyms); tog('lHeat', heat); tog('lNear', near);
</script></body></html>"""
    open(OUT, "w", encoding="utf-8").write(page)
    print(f"wrote {OUT}: {stats}")


if __name__ == "__main__":
    main()
