"""Live map of the bank the scanner builds (system/map/pogo_wigle.db): every PokéStop, gym and Power Spot the game
has shown us, plus the path it was scanned along. No spawns, Rocket, lures or raids.
Gym defenders / CP / motivation / in-battle come ONLY from the live gym-state columns (gym_state_t stamped on every
sighting) and are shown with their age; older than 2 min they are marked stale. Nothing dynamic is read from `raw`.
The panel shows the scanner's last SELFCHECK (system/map/selfcheck.json) and turns red when replies stop.

  python tools/map_live.py [--every 4]

Writes system/analysis/pogo_map.html once (the page) and rewrites system/analysis/pogo_map_data.js every few seconds.
The page reloads that data file on its own, so leaving it open shows the bank growing while you walk.
Read-only on the DB; never touches the phone.
"""
import argparse
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quests as qz  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
DB = os.path.join(ROOT, "system", "map", "pogo_wigle.db")
OUT = os.path.join(ROOT, "system", "analysis", "pogo_map.html")
DATA = os.path.join(ROOT, "system", "analysis", "pogo_map_data.js")
ROUTE = os.path.join(ROOT, "system", "map", "routes", "active_route.json")
HEALTH = os.path.join(ROOT, "system", "map", "selfcheck.json")
TEAM = {0: "no team", 1: "Mystic", 2: "Valor", 3: "Instinct"}
FMT = "%Y-%m-%d %H:%M:%S"
GYM_FRESH_S = 120                                      # gym state older than this is shown as stale


def _ep(s):
    try:
        return time.mktime(time.strptime(s[:19], FMT)) if s else None
    except ValueError:
        return None


def snapshot():
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    cols = {r[1] for r in db.execute("PRAGMA table_info(forts)")}
    has_details = db.execute("SELECT 1 FROM sqlite_master WHERE name='fort_details'").fetchone() is not None
    name_sql = "COALESCE(f.name, d.name)" if has_details else ("f.name" if "name" in cols else "NULL")
    join = "LEFT JOIN fort_details d ON d.id = f.id" if has_details else ""
    raw_sql = "f.raw" if "raw" in cols else "NULL"
    gcols = ", ".join(f"f.{c}" if c in cols else "NULL" for c in ("slots", "gym_cp", "motivation", "in_battle", "gym_state_t", "raw_t"))
    forts = []
    for (fid, lat, lng, kind, first, last, seen, team, guard, vis, ex, pup, name, raw,
         slots, cp, mot, bat, gst, rawt) in db.execute(
            f"SELECT f.id, f.lat, f.lng, f.kind, f.first_seen, f.last_seen, f.times_seen, f.team, f.guard, f.visited, f.ex,"
            f" f.power_up_pts, {name_sql}, {raw_sql}, {gcols} FROM forts f {join}"):
        # raw only for POI-level facts (route-eligible, sponsor, stamp); never for team / defenders / motivation
        o = json.loads(raw) if raw else {}
        d = {"i": fid, "a": round(lat, 6), "o": round(lng, 6), "g": 1 if kind == "gym" else 0,
             "n": name or "", "v": vis or 0, "x": ex or 0, "p": pup or 0, "t": team or 0,
             "re": 1 if o.get("IsRouteEligible") else 0, "sp": 1 if o.get("PartnerId") else 0,
             "st": o.get("StampCollectionIds") or [], "f": first, "l": last, "k": seen, "full": 1 if raw else 0, "rt": rawt}
        if kind == "gym":
            d["gd"] = guard or 0
            # [open slots (None = the game sent no display), CP, lowest motivation, in battle (None = unknown), read at,
            #  read AT the last sighting]; team (t) is always from the last sighting
            d["gs"] = ([slots, cp, None if mot is None else round(mot, 3), bat, gst, 1 if gst == last else 0]
                       if gst else None)
        forts.append(d)
    stations = [{"i": i, "a": a, "o": o, "n": n or "", "f": f} for i, a, o, n, f in
                db.execute("SELECT id, lat, lng, name, first_seen FROM stations")]
    track = [[round(a, 6), round(o, 6)] for a, o in db.execute("SELECT lat, lng FROM track ORDER BY t")]
    last_reply = db.execute("SELECT MAX(t) FROM replies").fetchone()[0]
    first_reply = db.execute("SELECT MIN(t), COUNT(*) FROM replies").fetchone()
    qt = qz.today(db, time.strftime("%Y-%m-%d"))          # tasks rotate at local midnight: today's only
    for f in forts:
        if f["i"] in qt:
            f["q"] = qt[f["i"]]
    db.close()
    now = time.time()
    lr = _ep(last_reply)
    selfcheck = None
    if os.path.exists(HEALTH):
        try:
            h = json.load(open(HEALTH, encoding="utf-8"))
            selfcheck = {"ok": h.get("ok"), "line": h.get("line", "")[:600], "at": h.get("checked_at")}
        except (OSError, ValueError):
            selfcheck = None
    fresh_gyms = [f for f in forts if f["g"] and f.get("gs") and _ep(f["gs"][4]) and now - _ep(f["gs"][4]) <= GYM_FRESH_S]
    stops = [f for f in forts if not f["g"]]
    gyms = [f for f in forts if f["g"]]
    km = 0.0
    for p, q in zip(track, track[1:]):
        dy = (q[0] - p[0]) * 111320
        dx = (q[1] - p[1]) * 111320 * 0.7568          # cos(40.75 deg)
        step = (dx * dx + dy * dy) ** 0.5
        if step < 400:                                 # a teleport is not a walk
            km += step / 1000
    stats = {"stops": len(stops), "gyms": len(gyms), "spots": len(stations),
             "never": sum(1 for f in stops if not f["v"]), "ex": sum(1 for f in gyms if f["x"]),
             "powered": sum(1 for f in stops if f["p"]), "named": sum(1 for f in forts if f["n"]),
             "full": sum(1 for f in forts if f["full"]), "km": round(km, 2),
             "raw_recent": sum(1 for f in forts if lr and _ep(f["rt"]) and lr - _ep(f["rt"]) <= 600),
             "gyms_fresh": len(fresh_gyms),
             # neutral gyms have every slot open; a held gym counts only when its display said so
             "gyms_open": sum(1 for f in fresh_gyms if f["gs"][5] and (not f["t"] or (f["gs"][0] or 0) > 0)),
             "q_all": len(qt), "q_mega": sum(1 for v in qt.values() if v["k"] == "mega"),
             "q_rare": sum(1 for v in qt.values() if v["k"] == "rare"),
             "since": first_reply[0], "replies": first_reply[1], "last_reply": last_reply,
             "last_reply_age_s": round(now - lr) if lr else None, "selfcheck": selfcheck,
             "written": time.strftime(FMT, time.localtime(now))}
    route = None
    if os.path.exists(ROUTE):
        try:
            r = json.load(open(ROUTE, encoding="utf-8"))
            vis = {f["i"]: f["v"] for f in forts}
            seen_at = {f["i"]: f["l"] for f in forts}
            legs = r.get("legs") or [{"name": "route", "points": [r["start"]] + [[x["lat"], x["lng"]] for x in r["stops"]],
                                      "km": r["km"], "minutes": r["minutes"], "unspun": len(r["stops"])}]
            route = {"legs": [{"name": g["name"], "pts": g["points"], "km": g["km"], "min": g["minutes"], "unspun": g.get("unspun")}
                              for g in legs], "n": len(r["stops"]),
                     "done": sum(1 for x in r["stops"] if vis.get(x["id"])),
                     # visited=0 is only known-true for stops the scanner has seen since the plan was made
                     "unseen": sum(1 for x in r["stops"] if (seen_at.get(x["id"]) or "") < r["created"]),
                     "km": r["km"], "min": r["minutes"],
                     "speed": r["speed_kmh"], "created": r["created"], "kind": r.get("kind", "route")}
        except Exception:
            route = None
    return {"forts": forts, "stations": stations, "track": track, "stats": stats, "route": route}


def write_data(d):
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("window.onData(" + json.dumps(d, separators=(",", ":")) + ");\n")
    for _ in range(5):                                 # the browser may hold the file for a moment on Windows
        try:
            os.replace(tmp, DATA)
            return True
        except PermissionError:
            time.sleep(0.2)
    return False


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PoGo Map</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<style>
:root { --bg:#fafaf8; --fg:#1d1d1b; --mut:#6b6b66; --line:#e4e2dc; --card:#ffffff; --live:#1a9e5a; --stale:#c0392b; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#141413; --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; } }
:root[data-theme="dark"] { --bg:#141413; --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; }
* { box-sizing:border-box; } html,body { height:100%; margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
#map { position:absolute; inset:0; }
.panel { position:absolute; z-index:1000; top:12px; left:12px; width:min(300px, calc(100% - 24px)); background:var(--card); color:var(--fg);
  border:1px solid var(--line); border-radius:10px; padding:10px 12px; box-shadow:0 2px 10px rgba(0,0,0,.15); }
.panel h1 { font-size:15px; margin:0 0 2px; } .mut { color:var(--mut); font-size:12px; }
.row { display:flex; justify-content:space-between; gap:12px; font-variant-numeric:tabular-nums; }
.dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align:-1px; }
label { display:block; margin:2px 0; cursor:pointer; } hr { border:0; border-top:1px solid var(--line); margin:6px 0; }
#live { font-size:12px; } #live b { color:var(--live); } #live.stale b, #live.stale { color:var(--stale); }
#check.fail, .stale-txt { color:var(--stale); } #check.ok b { color:var(--live); }
details summary { cursor:pointer; color:var(--mut); font-size:12px; margin-top:4px; }
@media (max-width:520px) { .panel { top:auto; bottom:12px; max-height:45vh; overflow:auto; } }
</style></head><body><div id="map"></div>
<div class="panel"><h1>My PokéStop &amp; gym bank</h1>
<div id="live" class="mut">waiting for data…</div>
<div id="check" class="mut"></div><hr>
<div class="row"><span><span class="dot" style="background:#2f7de1"></span>PokéStops</span><b id="sStops">–</b></div>
<div class="row"><span><span class="dot" style="background:#f0a500"></span>&nbsp;never spun</span><b id="sNever">–</b></div>
<div class="row"><span><span class="dot" style="background:#e04f5f"></span>Gyms</span><b id="sGyms">–</b></div>
<div class="row"><span>&nbsp;&nbsp;&nbsp;EX-raid eligible</span><b id="sEx">–</b></div>
<div class="row"><span>&nbsp;&nbsp;&nbsp;state read in the last 2 min</span><b id="sGymFresh">–</b></div>
<div class="row"><span>&nbsp;&nbsp;&nbsp;of those, with open slots</span><b id="sGymOpen">–</b></div>
<div class="row"><span><span class="dot" style="background:#8e44ad"></span>Power Spots</span><b id="sSpots">–</b></div>
<div class="row"><span>Scanned path</span><b id="sKm">–</b></div>
<div class="row"><span><span style="color:#7048e8">&#9733;</span> Mega Energy tasks today</span><b id="sQMega">–</b></div>
<div class="row"><span><span style="color:#e64980">&#9733;</span> Rare Candy tasks today</span><b id="sQRare">–</b></div>
<div class="mut" id="sQNote">Tasks show up only for stops you spin by hand.</div>
<div class="row" id="rRow" style="display:none"><span><span class="dot" style="background:#00a3a3"></span>Route (spun / stops)</span><b id="sRoute">–</b></div>
<div class="mut" id="rMore" style="display:none"></div>
<details><summary>Layers &amp; more</summary>
<label><input type="checkbox" id="lStops" checked> stops</label>
<label><input type="checkbox" id="lGyms" checked> gyms</label>
<label><input type="checkbox" id="lSpots" checked> Power Spots</label>
<label><input type="checkbox" id="lTrack" checked> scanned path</label>
<label><input type="checkbox" id="lRoute" checked> planned route</label>
<label><input type="checkbox" id="lQuests" checked> today's tasks (stars)</label>
<label><input type="checkbox" id="lHeat"> stop density heat</label>
<label><input type="checkbox" id="lNew" checked> ring spots found in the last 10 min</label>
<label><input type="checkbox" id="lFollow"> follow me</label>
<div class="mut" id="sMore" style="margin-top:4px"></div>
</details>
</div>
<script>
var map = L.map('map', {preferCanvas: true}).setView([40.758, -73.979], 15);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 20, maxNativeZoom: 19, attribution: '&copy; OpenStreetMap'}).addTo(map);
var TEAM = ['no team', 'Mystic', 'Valor', 'Instinct'];
map.createPane('routes'); map.getPane('routes').style.zIndex = 450; var ROUTE_R = L.canvas({pane: 'routes'});
var L_ = {stops: L.layerGroup().addTo(map), gyms: L.layerGroup().addTo(map), spots: L.layerGroup().addTo(map),
          track: L.layerGroup().addTo(map), me: L.layerGroup().addTo(map), route: L.layerGroup().addTo(map),
          quests: L.layerGroup().addTo(map), heat: null};
var QCOL = {mega: '#7048e8', rare: '#e64980', other: '#868e96'};
var first = true, lastWritten = null, LAST = null;
var SEED = '2026-09-25 03:13:57', GYM_FRESH_S = 120, TEAM_KNOWN_S = 600;
function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }
function ageS(s) { var t = Date.parse(String(s || '').replace(' ', 'T')); return t ? (Date.now() - t) / 1000 : null; }
function ago(sec) { return sec == null ? '?' : sec < 90 ? Math.max(0, Math.round(sec)) + ' s' : sec < 5400 ? Math.round(sec / 60) + ' min' : (sec / 3600).toFixed(1) + ' h'; }
function isNew(f) { var a = ageS(f.f); return a != null && a < 10 * 60; }
function gymLine(f) {        /* defenders / CP / motivation from the live gym-state columns only, always with their age */
  var G = f.gs;
  if (!G) return '<br><span class="stale-txt">defenders / CP / motivation: not read yet (needs a sighting by the fixed scanner)</span>';
  var ga = ageS(G[4]), line;
  if (!G[5]) return '<br><span class="stale-txt">defenders / CP / motivation not read at the last sighting (last read ' +
    ago(ga) + ' ago, team may have changed since)</span>';
  if (!f.t) line = 'open gym, no defenders';
  else if (G[0] == null) line = 'defenders unknown (the game sent no gym display)';
  else line = (6 - G[0]) + '/6 defenders ' + (G[0] ? '(' + G[0] + ' open slot' + (G[0] > 1 ? 's' : '') + ')' : '(full)') +
              ' · ' + (G[1] || 0) + ' CP · lowest motivation ' + Math.round((G[2] || 0) * 100) + '%' + (f.gd ? ' · top #' + f.gd : '');
  if (G[3]) line += ' · <b>in battle</b>';
  return ga != null && ga <= GYM_FRESH_S ? '<br>' + line + ' <span style="color:#777">(' + ago(ga) + ' ago)</span>'
    : '<br><span class="stale-txt">stale, read ' + ago(ga) + ' ago:</span> ' + line;
}
function tip(f) {
  var h = '<b>' + (f.n ? esc(f.n) : (f.g ? 'Gym' : 'PokéStop')) + '</b><br>' + (f.g ? 'Gym' : 'PokéStop');
  var la = ageS(f.l), seed = f.f === SEED && f.l === SEED;
  if (!f.g) h += f.v ? ' · spun before' : ' · <b>never spun</b>';
  if (f.g) {
    h += (f.x ? ' · <b>EX-raid eligible</b>' : '') + (la != null && la <= TEAM_KNOWN_S ? ' · held by ' : ' · last known: ') + TEAM[f.t];
    h += gymLine(f);
  }
  if (f.q) h += '<br><b style="color:' + QCOL[f.q.k] + '">Today\'s task reward: ' + esc(f.q.s) + '</b>' + (f.q.goal ? ' (goal ' + f.q.goal + ')' : '');
  if (f.p) h += '<br>power-up points ' + f.p;
  if (f.re) h += '<br>route-eligible';
  if (f.sp) h += '<br>sponsored';
  if (f.st && f.st.length) h += '<br>stamp: ' + esc(f.st.join(', '));
  h += '<br><span style="color:#777">' + (seed ? 'from the 03:13 one-time read, not seen live since' :
       'last seen ' + ago(la) + ' ago · first seen ' + esc(f.f) + ' · seen ' + f.k + '×') + '</span>';
  return h;
}
function paintLive() {      /* red when map_live stopped writing, or the game sent no map reply for > 60 s */
  if (!LAST) return;
  var s = LAST, wa = ageS(s.written), ra = s.last_reply_age_s == null ? null : s.last_reply_age_s + (wa || 0);
  var dead = wa == null || wa > 20, quiet = ra == null || ra > 60, lv = document.getElementById('live');
  lv.className = (dead || quiet) ? 'mut stale' : 'mut';
  lv.innerHTML = (dead ? 'map_live.py stopped ' + ago(wa) + ' ago · ' : quiet ? 'No map reply for ' + ago(ra) + ' · ' : 'Live · ') +
    'last game map reply <b>' + esc((s.last_reply || '–').slice(11)) + '</b> · file ' + esc(s.written.slice(11));
  var c = s.selfcheck, ck = document.getElementById('check');
  if (!c) { ck.className = 'mut fail'; ck.textContent = 'Self-check: none yet (the scanner writes one every 5 min)'; return; }
  var ca = ageS(c.at), old = ca == null || ca > 11 * 60;
  ck.className = 'mut ' + (c.ok && !old ? 'ok' : 'fail'); ck.title = c.line || '';
  ck.innerHTML = 'Self-check <b>' + (c.ok ? 'ok' : 'FAIL') + '</b> ' + ago(ca) + ' ago' + (old ? ' (overdue: is the scanner running?)' : '') +
    (c.ok ? '' : '<br>' + esc((c.line || '').replace(/^SELFCHECK FAIL /, '').split(' | ')[0]).slice(0, 300));
}
window.onData = function (d) {
  var s = d.stats; LAST = s; paintLive();
  if (s.written === lastWritten) return; lastWritten = s.written;
  var ringNew = document.getElementById('lNew').checked;
  L_.stops.clearLayers(); L_.gyms.clearLayers(); L_.spots.clearLayers(); L_.track.clearLayers(); L_.me.clearLayers(); L_.route.clearLayers(); L_.quests.clearLayers();
  var R = d.route;
  document.getElementById('rRow').style.display = R ? '' : 'none';
  document.getElementById('rMore').style.display = R ? '' : 'none';
  if (R) {
    var LEGC = ['#00a3a3', '#d9480f', '#5f3dc4', '#2b8a3e', '#c2255c', '#1864ab'];
    R.legs.forEach(function (g, k) {
      var c = LEGC[k % LEGC.length];
      L.polyline(g.pts, {color: c, weight: 4, opacity: .95, dashArray: '8 6', renderer: ROUTE_R})
        .bindTooltip('<b>' + esc(g.name) + '</b><br>' + g.km + ' km, about ' + g.min + ' min, ' + (g.unspun || '?') + ' unspun stops').addTo(L_.route);
      L.marker(g.pts[0], {interactive: false, icon: L.divIcon({className: '', iconSize: [0, 0], html: '<div style="transform:translate(-50%,-50%);width:20px;height:20px;border-radius:50%;background:' + c + ';color:#fff;font:700 11px/20px system-ui;text-align:center;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)">' + (k + 1) + '</div>'})}).addTo(L_.route);
    });
    document.getElementById('sRoute').textContent = R.done + ' / ' + R.n;
    document.getElementById('rMore').textContent = 'Planned ' + R.created.slice(11) + ': ' + (R.legs.length > 1 ? R.legs.length + ' legs, ' : '') + R.km + ' km loop, about ' + R.min + ' min at ' + R.speed + ' km/h. The numbered circle is the start.' +
      (R.unseen ? ' ' + R.unseen + ' of the ' + R.n + ' stops have not been seen by the scanner since then, so their spun state is not current.' : '');
  }
  d.forts.forEach(function (f) {
    var nw = ringNew && isNew(f);
    if (f.g) {
      L.circleMarker([f.a, f.o], {radius: 7, color: nw ? '#12b76a' : (f.x ? '#111' : '#7a1f2b'), weight: nw ? 2 : (f.x ? 3 : 1),
        fillColor: '#e04f5f', fillOpacity: .9}).bindTooltip(tip(f)).addTo(L_.gyms);
    } else {
      var col = f.v ? '#2f7de1' : '#f0a500';
      L.circleMarker([f.a, f.o], {radius: f.v ? 4 : 6, color: nw ? '#12b76a' : col, weight: nw ? 1.5 : 1, fillColor: col, fillOpacity: .85})
        .bindTooltip(tip(f)).addTo(L_.stops);
    }
  });
  d.forts.forEach(function (f) {
    if (!f.q) return;
    var big = f.q.k !== 'other';
    L.marker([f.a, f.o], {icon: L.divIcon({className: '', iconSize: [0, 0], html: '<div style="transform:translate(-50%,-85%);font:700 ' +
      (big ? 22 : 14) + 'px/1 system-ui;color:' + QCOL[f.q.k] + ';text-shadow:0 0 3px #fff,0 0 3px #fff">&#9733;</div>'})})
      .bindTooltip(tip(f)).addTo(L_.quests);
  });
  d.stations.forEach(function (p) {
    L.circleMarker([p.a, p.o], {radius: 6, color: '#4a2360', weight: 1, fillColor: '#8e44ad', fillOpacity: .9})
      .bindTooltip('<b>' + esc(p.n || 'Power Spot') + '</b><br>Power Spot<br><span style="color:#777">first seen ' + esc(p.f) + '</span>').addTo(L_.spots);
  });
  if (d.track.length > 1) L.polyline(d.track, {color: '#ff7a00', weight: 3, opacity: .75}).addTo(L_.track);
  if (d.track.length) {
    var me = d.track[d.track.length - 1];
    L.circleMarker(me, {radius: 8, color: '#fff', weight: 3, fillColor: '#ff7a00', fillOpacity: 1}).bindTooltip('you (last scanner fix)').addTo(L_.me);
    if (document.getElementById('lFollow').checked) map.panTo(me);
  }
  if (L_.heat) map.removeLayer(L_.heat);
  L_.heat = L.heatLayer ? L.heatLayer(d.forts.filter(function (f) { return !f.g; }).map(function (f) { return [f.a, f.o, 0.6]; }), {radius: 22, blur: 18}) : null;
  if (L_.heat && document.getElementById('lHeat').checked) L_.heat.addTo(map);
  if (first && d.forts.length) { map.fitBounds(d.forts.map(function (f) { return [f.a, f.o]; }), {padding: [30, 30]}); first = false; }
  document.getElementById('sStops').textContent = s.stops;
  document.getElementById('sNever').textContent = s.never;
  document.getElementById('sGyms').textContent = s.gyms;
  document.getElementById('sEx').textContent = s.ex;
  document.getElementById('sSpots').textContent = s.spots;
  document.getElementById('sGymFresh').textContent = s.gyms_fresh == null ? '–' : s.gyms_fresh;
  document.getElementById('sGymOpen').textContent = s.gyms_open == null ? '–' : s.gyms_open;
  document.getElementById('sKm').textContent = s.km.toFixed(2) + ' km';
  document.getElementById('sQMega').textContent = s.q_mega == null ? '–' : s.q_mega;
  document.getElementById('sQRare').textContent = s.q_rare == null ? '–' : s.q_rare;
  document.getElementById('sQNote').textContent = (s.q_all || 0) + ' task' + (s.q_all === 1 ? '' : 's') + ' seen today. Tasks show up only for stops you spin by hand.';
  document.getElementById('sMore').innerHTML = 'Bank since ' + esc(s.since || '–') + ' from ' + s.replies + ' map replies.<br>' +
    s.full + ' forts with a full record (' + (s.raw_recent || 0) + ' re-read in the 10 min before the last reply), ' +
    s.named + ' with names (names arrive when a stop is opened in the game), ' +
    s.powered + ' stops with power-up points.';
};
function pull() {
  var old = document.getElementById('dataJs'); if (old) old.remove();
  var sc = document.createElement('script'); sc.id = 'dataJs'; sc.src = 'pogo_map_data.js?t=' + Date.now(); document.body.appendChild(sc);
  paintLive();
}
['lStops', 'lGyms', 'lSpots', 'lTrack', 'lRoute', 'lQuests'].forEach(function (id) {
  var lay = {lStops: L_.stops, lGyms: L_.gyms, lSpots: L_.spots, lTrack: L_.track, lRoute: L_.route, lQuests: L_.quests}[id];
  document.getElementById(id).addEventListener('change', function (e) { e.target.checked ? lay.addTo(map) : map.removeLayer(lay); });
});
document.getElementById('lHeat').addEventListener('change', function (e) { if (L_.heat) e.target.checked ? L_.heat.addTo(map) : map.removeLayer(L_.heat); });
document.getElementById('lNew').addEventListener('change', function () { lastWritten = null; pull(); });
pull(); setInterval(pull, 5000);
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=float, default=4.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(PAGE)
    print(f"{time.strftime('%H:%M:%S')} page {OUT}", flush=True)
    last = 0
    while True:
        try:
            d = snapshot()
            write_data(d)
            if a.once or time.time() - last >= 60:
                s = d["stats"]
                print(f"{time.strftime('%H:%M:%S')} map: {s['stops']} stops ({s['never']} never spun), {s['gyms']} gyms ({s['ex']} EX),"
                      f" {s['spots']} Power Spots, {s['km']} km scanned", flush=True)
                last = time.time()
        except Exception as e:
            print(f"{time.strftime('%H:%M:%S')} {type(e).__name__}: {e}", flush=True)
        if a.once:
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
