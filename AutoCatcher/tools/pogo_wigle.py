"""PoGo "WiGLE": a database that grows as you walk. Read-only.

Every map reply the server sends (GetMapObjectsOutProto, every few seconds while moving) is captured the moment it is
parsed and every record in it is stored in SQLite -- no heap scans, no stutter:
  forts     every PokeStop / gym: position, type, team, defender, lure, visited, EX, power-up, image;
            first_seen / last_seen / times_seen, plus a history of changes (fort_events: new, team, lure, defenders, spin).
            Gym state is read on EVERY sighting: slots (open slots; defenders = 6 - slots), gym_cp, motivation (lowest),
            occupied_ms, in_battle, stamped gym_state_t. `raw` is the full record, stamped raw_t; it is re-read when the
            team/guard change or after 5-6 min, so NEVER read a dynamic value from raw -- use the columns + their stamps.
            raid / displays (Rocket, Showcase) are NOT decoded (user, 2026-09-25): NULL means unknown, not "none".
  spawns    every wild Pokemon: species, form, shiny, exact spot, spawn point, time seen, despawn timer
  nearby    every radar entry: species near which stop, distance
  stations  Power Spots: name, position, Max Battle boss, level, window
  routes    in-game Routes (SharedRouteProto) seen in map cells (raw record)
  weather   per S2 cell gameplay weather
  track     where you were (spoofed position + speed) every few seconds

  python tools/pogo_wigle.py            (runs until stopped; re-attaches if PoGo restarts)
Every 5 min it prints one "SELFCHECK ok|FAIL ..." line (tools/audit_bank.py, DB reads only) and writes
system/map/selfcheck.json, which tools/map_live.py shows. On demand: python tools/audit_bank.py
DB: system/map/pogo_wigle.db
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402
import dump_game_limits as dl  # noqa: E402
import audit_bank as ab  # noqa: E402
import quests as qz  # noqa: E402

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
DB = os.path.join(os.path.dirname(HERE), "system", "map", "pogo_wigle.db")
SCHEMA = """
CREATE TABLE IF NOT EXISTS forts (id TEXT PRIMARY KEY, lat REAL, lng REAL, kind TEXT, first_seen TEXT, last_seen TEXT,
  times_seen INT, team INT, guard INT, enabled INT, visited INT, ex INT, lured INT, lure_item INT, displays INT,
  raid TEXT, power_up_pts INT, closed INT, image TEXT, cell TEXT);
CREATE TABLE IF NOT EXISTS fort_events (t TEXT, fort TEXT, event TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS spawns (enc TEXT PRIMARY KEY, t TEXT, lat REAL, lng REAL, spawn_point TEXT, pid INT, form INT,
  shiny INT, ttl_ms INT, source TEXT, cell TEXT);
CREATE TABLE IF NOT EXISTS nearby (enc TEXT PRIMARY KEY, t TEXT, pid INT, form INT, fort TEXT, dist REAL);
CREATE TABLE IF NOT EXISTS stations (id TEXT PRIMARY KEY, lat REAL, lng REAL, name TEXT, first_seen TEXT, last_seen TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS routes (id TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS weather (cell TEXT, t TEXT, cond INT, raw TEXT, PRIMARY KEY (cell, t));
CREATE TABLE IF NOT EXISTS track (t TEXT, lat REAL, lng REAL, kmh REAL);
CREATE TABLE IF NOT EXISTS fort_details (id TEXT PRIMARY KEY, t TEXT, name TEXT, description TEXT, images TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS spins (t TEXT, fort TEXT, result INT, xp INT, cooldown TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS replies (t TEXT, cells INT, forts INT, wild INT, nearby INT, catchable INT, stations INT, routes INT);
""" + qz.SCHEMA
# columns added in place (ALTER TABLE, additive). Gym state is written on EVERY sighting from GymDisplay/IsInBattle;
# raw_t = when `raw` (the full record) was read, so its age is always visible.
NEW_COLS = (("raw", "TEXT"), ("name", "TEXT"), ("slots", "INT"), ("gym_cp", "INT"), ("motivation", "REAL"),
            ("occupied_ms", "INT"), ("in_battle", "INT"), ("gym_state_t", "TEXT"), ("raw_t", "TEXT"))
# raw keys a partial record (see store()) never carries; none of them changes during play
STATIC_RAW = ("Latitude", "Longitude", "FortType", "IsExRaidEligible", "PartnerId", "FortVpsInfo", "ArExperiencesAllowed",
              "IsArScanEligible")
SELFCHECK_EVERY = 300                       # seconds; the self-check reads the DB only
HEALTH = os.path.join(os.path.dirname(DB), "selfcheck.json")

JS = dl.JS.split("rpc.exports = {")[0] + r"""
var Q = [], Q2 = [], OFF = {}, LASTP = null, LASTT = 0, HOOKS = 0, FULL = {}, LASTX = {}, GDK = null, GDN = '', DRAINS = 0;
/* FULL[id] = {lm, team, guard, due, t} after a successful full read, {retry, fails, t} after a failed one. The full
   record is re-read when LastModifiedMs changes (it is 0 in every fort seen so far), team or guard changed since the
   last full read, or `due` (5-6 min after it) has passed. A failed read is retried after a back-off (30 s, doubling to
   10 min) -- never on every reply.
   GAME SAFETY: all of this runs INSIDE the game's parse call (a reply carries ~500 forts every ~6 s), so full reads
   are capped per reply: FULL_MAX in total (first sightings included -- the first reply after an attach used to
   full-read every fort in one call), timed and retry reads also within BUDGET. A fort over the cap keeps its reason
   and is read on a later reply. prune() (from drain, outside the game's call) keeps FULL / LASTX bounded. */
var FULL_MS = 300000, FULL_JITTER = 60000, FULL_BUDGET = 25, FULL_MAX = 40, BUDGET = 0, NFULL = 0;
var RETRY_MS = 30000, RETRY_MAX_MS = 600000, CACHE_TTL_MS = 3600000, GD_FIELDS = ['SlotsAvailable', 'TotalGymCp', 'LowestPokemonMotivation', 'OccupiedMillis'];
var STAT = {fulls: 0, full_fail: 0, gyms: 0, gym_fail: 0, gym_nogd: 0};
function offs(cls, names) { var k = findClass('holo-protos.dll', cls), o = {}; if (!k) return null;
  fieldsOf(k).forEach(function (f) { if (names.indexOf(f.name) >= 0) o[f.name] = f.off; }); return o; }
function rep(p) { if (p.isNull()) return []; var a = p.add(0x10).readPointer(), n = p.add(0x18).readS32(), out = [];
  if (a.isNull() || n <= 0 || n > 5000) return out; for (var i = 0; i < n; i++) out.push(a.add(0x20 + 8 * i).readPointer()); return out; }
function repInt(p) { if (p.isNull()) return []; var a = p.add(0x10).readPointer(), n = p.add(0x18).readS32(), out = [];
  if (a.isNull() || n <= 0 || n > 64) return out; for (var i = 0; i < n; i++) out.push(a.add(0x20 + 4 * i).readS32()); return out; }
function S(o, off) { return str(o.add(off).readPointer()); }
function gdv(gd, n) {             /* one GymDisplay field, typed by il2cpp metadata; plain memory read */
  var d = OFF.gd[n], v = d ? prim(gd.add(d.off), d.te) : undefined;
  if (v === undefined) throw new Error(n); return v;
}
function readGym(f, r) {          /* dynamic gym state, read on EVERY sighting -- never taken from the cached full record.
     GAME SAFETY (this runs ~50-100x per reply): plain memory reads at offsets resolved from metadata at install. The
     GymDisplay pointer comes out of object memory, so it is never handed to an il2cpp function (readObj would pass its
     class to il2cpp_class_get_fields), and its fields are read only after its class pointer is GymDisplay's own. */
  var O = OFF.fort, gs = r.gs = {battle: null}; STAT.gyms++;
  try {
    if (O.IsInBattle !== undefined) gs.battle = f.add(O.IsInBattle).readU8();
    if (O.GymDisplay === undefined || !GDK) { STAT.gym_fail++; gs.err = 'no GymDisplay offset'; return; }
    var gd = f.add(O.GymDisplay).readPointer();
    if (gd.isNull()) { if (r.team) STAT.gym_nogd++; gs.err = 'GymDisplay null'; return; }   /* neutral: store() stamps it NULL */
    if (!gd.readPointer().equals(GDK) && jsClass(gd).name !== GDN) { STAT.gym_fail++; gs.err = 'GymDisplay wrong class'; return; }
    /* proto3: an unset field reads as 0 -- SlotsAvailable 0 = no open slot = full gym (6 defenders) */
    gs.slots = gdv(gd, 'SlotsAvailable'); gs.cp = gdv(gd, 'TotalGymCp'); gs.mot = gdv(gd, 'LowestPokemonMotivation');
    gs.occ = String(gdv(gd, 'OccupiedMillis'));
  } catch (e) { STAT.gym_fail++; r.gs = {battle: gs.battle, err: 'unreadable ' + e.message}; }
}
function readFort(f) {
  var O = OFF.fort;
  var r = {id: S(f, O.FortId), lat: f.add(O.Latitude).readDouble(), lng: f.add(O.Longitude).readDouble(),
    type: f.add(O.FortType).readS32(), team: f.add(O.Team).readS32(), guard: f.add(O.GuardPokemonId).readS32(),
    en: f.add(O.Enabled).readU8(), vis: f.add(O.Visited).readU8(), ex: f.add(O.IsExRaidEligible).readU8(),
    lure: repInt(f.add(O.ActiveFortModifier).readPointer()), pup: f.add(O.PowerUpProgressPoints).readS32(),
    closed: f.add(O.Closed).readU8(), img: S(f, O.ImageUrl)};
  if (!r.id) return r;             /* store() drops a fort without an id: spend nothing more on it inside the game */
  if (r.type !== 1) readGym(f, r); /* stops carry a placeholder GymDisplay (6 slots, motivation 1): never read */
  var lm = f.add(O.LastModifiedMs).readS64().toString(), now = Date.now(), c = FULL[r.id], why = null;
  if (!c) why = 'new';
  else if (c.retry) why = now >= c.retry ? 'retry' : null;          /* last read failed: wait out the back-off */
  else if (c.lm !== lm) why = 'modified';
  else if (c.team !== r.team || c.guard !== r.guard) why = 'team';
  else if (now >= c.due) why = 'age';
  var timed = why === 'age' || why === 'retry';
  if (why && (NFULL <= 0 || (timed && BUDGET <= 0))) why = null;    /* over this reply's cap: a later reply reads it */
  if (why) {
    NFULL--; if (timed) BUDGET--;
    STAT.fulls++;
    var full = null; try { full = readObj(f, 3); } catch (e) { full = null; }
    if (full && typeof full === 'object' && full.FortId === r.id) {
      r.full = full; r.full_why = why;
      FULL[r.id] = {lm: lm, team: r.team, guard: r.guard, t: now, due: now + FULL_MS + Math.floor(Math.random() * FULL_JITTER)};
    } else {                       /* counted, and retried after a back-off -- not on every reply */
      STAT.full_fail++; var nf = ((c && c.fails) || 0) + 1;
      FULL[r.id] = {t: now, fails: nf, retry: now + Math.min(RETRY_MAX_MS, RETRY_MS * Math.pow(2, nf - 1))};
    }
  }
  return r;                        /* no raid / incident decode (user, 2026-09-25): those columns stay NULL = unknown */
}
function enumMap(name, probe) {   /* {value: name} of a holo-protos enum; install-time metadata read only */
  var sgv = EX['il2cpp_field_static_get_value'] ? new NativeFunction(EX['il2cpp_field_static_get_value'], 'void', ['pointer', 'pointer'], PROP) : null;
  if (!sgv) return null;
  var sp = Memory.alloc(4), a = IL.asms(IL.domain(), sp), n = sp.readS32(), buf = Memory.alloc(16);
  for (var i = 0; i < n; i++) {
    var im = IL.asmImage(a.add(i * PS).readPointer()); if (cs(IL.imageName(im)) !== 'holo-protos.dll') continue;
    var c = IL.classCount(im);
    for (var j = 0; j < c; j++) {
      var k = IL.classAt(im, j); if (k.isNull() || cs(IL.className(k)) !== name || !IL.isEnum(k)) continue;
      var out = {}, hit = false, it = Memory.alloc(PS); it.writePointer(NULL); var fd;
      while ((fd = IL.fields(k, it)) && !fd.isNull()) {
        if ((IL.fieldFlags(fd) & 0x50) !== 0x50) continue;          /* static + literal = the enum's named values */
        buf.writeU64(0); sgv(fd, buf); var nm = cs(IL.fieldName(fd)); out[buf.readS32()] = nm; if (probe.test(nm)) hit = true;
      }
      if (hit) return out;
    }
  }
  return null;
}
function prune() {                 /* bounded caches; runs from drain(), never inside the game's parse call */
  var now = Date.now(), id, k;
  for (id in FULL) if (now - FULL[id].t > CACHE_TTL_MS) delete FULL[id];    /* in view = re-read every 5-6 min */
  for (k in LASTX) if (now - LASTX[k] > 60000) delete LASTX[k];
}
function readWild(w) {
  var O = OFF.wild, pk = w.add(O.Pokemon).readPointer(), pid = 0, form = 0, shiny = 0;
  if (!pk.isNull()) { pid = pk.add(OFF.pk.pid).readS32(); var dp = pk.add(OFF.pk.disp).readPointer();
    if (!dp.isNull()) { form = dp.add(OFF.disp.Form).readS32(); shiny = dp.add(OFF.disp.Shiny).readU8(); } }
  return {enc: w.add(O.EncounterId).readU64().toString(), lat: w.add(O.Latitude).readDouble(), lng: w.add(O.Longitude).readDouble(),
          sp: S(w, O.SpawnPointId), pid: pid, form: form, shiny: shiny, ttl: w.add(O.TimeTillHiddenMs).readS32()};
}
function readNear(n) {
  var O = OFF.near, dp = n.add(O.PokemonDisplay).readPointer();
  return {enc: n.add(O.EncounterId).readU64().toString(), pid: n.add(O.PokedexNumber).readS32(), dist: n.add(O.DistanceMeters).readFloat(),
          fort: S(n, O.FortId), form: dp.isNull() ? 0 : dp.add(OFF.disp.Form).readS32()};
}
function onReply(g) {
  var now = Date.now(); if (LASTP && g.equals(LASTP) && now - LASTT < 1500) return; LASTP = g; LASTT = now; BUDGET = FULL_BUDGET; NFULL = FULL_MAX;
  var cells = rep(g.add(OFF.gmo.MapCell).readPointer()), out = {t: now, cells: []};
  cells.forEach(function (c) {
    var C = OFF.cell, cid = c.add(C.S2CellId).readU64().toString(), rec = {cell: cid, forts: [], wild: [], near: [], catch: [], st: [], rt: 0};
    try { rep(c.add(C.Fort).readPointer()).forEach(function (f) { try { rec.forts.push(readFort(f)); } catch (e) {} }); } catch (e) {}
    try { rep(c.add(C.Stations).readPointer()).forEach(function (s) { try { rec.st.push(readObj(s, 2)); } catch (e) {} }); } catch (e) {}
    try { var rr = rep(c.add(C.Routes).readPointer()); rec.rt = rr.length; if (rr.length) { rec.routes = []; rr.forEach(function (x) { try { rec.routes.push(readObj(x, 2)); } catch (e) {} }); } } catch (e) {}
    out.cells.push(rec);
  });
  Q.push(out); if (Q.length > 200) Q.shift();
  LASTT = Date.now();              /* de-dup window runs from the END: a slow pass is not re-run by the outer parse method */
}
rpc.exports = {
  install: function () {
    OFF.gmo = offs('GetMapObjectsOutProto', ['MapCell', 'ClientWeather']);
    OFF.cell = offs('ClientMapCellProto', ['S2CellId', 'Fort', 'WildPokemon', 'NearbyPokemon', 'CatchablePokemon', 'Stations', 'Routes']);
    OFF.fort = offs('PokemonFortProto', ['FortId', 'Latitude', 'Longitude', 'FortType', 'Team', 'GuardPokemonId', 'Enabled', 'Visited',
      'IsExRaidEligible', 'ActiveFortModifier', 'PokestopDisplays', 'PowerUpProgressPoints', 'Closed', 'ImageUrl', 'RaidInfo', 'LastModifiedMs', 'GymDisplay', 'IsInBattle']);
    /* GymDisplay's class + field offsets/types come from il2cpp METADATA (the declared type of PokemonFortProto.GymDisplay),
       never from object memory; readGym then needs no il2cpp call at all. All four fields or none (= counted gym_fail).
       A failure here must never fail install(): that would make the scanner detach/re-attach in a loop. */
    OFF.gd = {};
    try {
      var fk = findClass('holo-protos.dll', 'PokemonFortProto');
      if (fk) fieldsOf(fk).forEach(function (fd) {
        if (fd.name !== 'GymDisplay') return;
        var gk = IL.classFromType(fd.t); if (!gk || gk.isNull()) return;
        var gf = {}; fieldsOf(gk).forEach(function (g) { if (GD_FIELDS.indexOf(g.name) >= 0) gf[g.name] = {off: g.off, te: g.te}; });
        OFF.gd = gf;
        if (GD_FIELDS.every(function (n) { return gf[n] !== undefined; })) { GDK = gk; GDN = cs(IL.className(gk)); }
      });
    } catch (e) { GDK = null; OFF.gd = {err: String(e)}; }
    OFF.wild = offs('WildPokemonProto', ['EncounterId', 'Latitude', 'Longitude', 'SpawnPointId', 'Pokemon', 'TimeTillHiddenMs']);
    OFF.near = offs('NearbyPokemonProto', ['PokedexNumber', 'DistanceMeters', 'EncounterId', 'FortId', 'PokemonDisplay']);
    var pk = offs('PokemonProto', ['pokemonId_', 'PokemonId', 'pokemonDisplay_', 'PokemonDisplay']);
    OFF.pk = {pid: pk.pokemonId_ !== undefined ? pk.pokemonId_ : pk.PokemonId, disp: pk.pokemonDisplay_ !== undefined ? pk.pokemonDisplay_ : pk.PokemonDisplay};
    OFF.disp = offs('PokemonDisplayProto', ['Form', 'Shiny']);
    var getM = new NativeFunction(EX['il2cpp_class_get_methods'], 'pointer', ['pointer', 'pointer'], PROP);
    var mName = new NativeFunction(EX['il2cpp_method_get_name'], 'pointer', ['pointer'], PROP);
    var mArgs = new NativeFunction(EX['il2cpp_method_get_param_count'], 'uint32', ['pointer'], PROP);
    function hookParse(cls, fn) {   /* every 1-arg parse method (MergeFrom + the obfuscated internal one) */
      var k = findClass('holo-protos.dll', cls), n = 0; if (!k) return 0;
      var it = Memory.alloc(PS); it.writePointer(NULL); var m;
      while ((m = getM(k, it)) && !m.isNull()) {
        var nm = cs(mName(m));
        if (mArgs(m) !== 1 || ['WriteTo', 'Equals', '.ctor', 'CalculateSize'].indexOf(nm) >= 0) continue;
        Interceptor.attach(m.readPointer(), {onEnter: function (a) { this.g = a[0]; }, onLeave: function () { try { fn(this.g); } catch (e) {} }});
        n++;
      }
      return n;
    }
    function extra(kind, depth) { return function (g) { var now = Date.now(), key = kind + g;
      if (LASTX[key] && now - LASTX[key] < 1500) return; LASTX[key] = now;
      try { Q2.push({k: kind, t: now, o: readObj(g, depth === undefined ? 3 : depth)}); } catch (e) {} if (Q2.length > 300) Q2.shift(); }; }
    /* a spin's task sits 5 levels down (spin > ChallengeQuest > Quest > reward > MegaResource): read from depth 1.
       One read per spin, and only a hand spin reaches this process. */
    var EN = {};
    try { EN.Item = enumMap('Item', /^(Item)?RareCandy$/); } catch (e) { EN.Item = null; }
    try { EN.HoloPokemonId = enumMap('HoloPokemonId', /^Bulbasaur$/i); } catch (e) { EN.HoloPokemonId = null; }
    HOOKS = hookParse('GetMapObjectsOutProto', onReply);
    var hd = hookParse('FortDetailsOutProto', extra('details')), hs = hookParse('FortSearchOutProto', extra('spin', 1));
    return {hooks: HOOKS, details_hooks: hd, spin_hooks: hs, off: OFF, enums: EN};
  },
  drain: function () { var q = Q, x = Q2, s = STAT; Q = []; Q2 = [];
    STAT = {fulls: 0, full_fail: 0, gyms: 0, gym_fail: 0, gym_nogd: 0};
    if (++DRAINS % 150 === 0) { try { prune(); } catch (e) {} }     /* ~every 5 min at the scanner's 2 s poll */
    return {replies: q, extras: x, stat: s}; }
};
"""


def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""


def me():
    m = re.search(r"Location\[gps ([-0-9.]+),([-0-9.]+) .*?vel=([0-9.]+)", adb("dumpsys location | grep -m1 'last mock location'"))
    return (float(m[1]), float(m[2]), round(float(m[3]) * 3.6, 2)) if m else None


def ts(ms):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ms / 1000))


def _num(v, cast):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def ensure_columns(db):
    """Additive schema upgrade: never drops or rewrites anything. The new gym-state columns start NULL (= unknown);
    they are NOT back-filled from `raw`, because `raw` is exactly the stale first-sighting copy this fixes."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(forts)")}
    for c, typ in NEW_COLS:
        if c not in cols:
            db.execute(f"ALTER TABLE forts ADD COLUMN {c} {typ}")
    db.commit()


def store(db, rep_):
    t = ts(rep_["t"])
    nf = nw = nn = nc = ns = nr = 0
    for c in rep_["cells"]:
        for f in c["forts"]:
            if not f.get("id"):
                continue
            nf += 1
            lured = 1 if f["lure"] else 0
            # raid / incident are not decoded (user, 2026-09-25): store NULL (= unknown), never 0 / "none"
            disp = f.get("disp") if "disp" in f else None
            rocket = sum(1 for d in disp or [] if isinstance(d, dict) and d.get("IncidentDisplayType"))
            raid = json.dumps(f["raid"]) if f.get("raid") else None
            ndisp = len(disp) if disp is not None else None
            row = db.execute("SELECT team, lured, displays, raid, visited, slots, last_seen, kind FROM forts WHERE id=?", (f["id"],)).fetchone()
            if row is not None and row[6] and row[6] > t:
                continue                # a reply older than what the bank already holds never overwrites it
            # game 0.435.0 resends a fort it already holds as a PARTIAL record (2026-10-31): the changing fields only --
            # no position and no FortType (which then reads 0 = gym). It never places, types or creates a fort.
            partial = not f["lat"] and not f["lng"]
            if partial and row is None:
                continue                # banked when the game sends its full record
            kind = row[7] if partial else ("stop" if f["type"] == 1 else "gym")
            if row is None:
                db.execute("INSERT INTO forts (id, lat, lng, kind, first_seen, last_seen, times_seen, team, guard, enabled,"
                           " visited, ex, lured, lure_item, displays, raid, power_up_pts, closed, image, cell)"
                           " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (f["id"], f["lat"], f["lng"], kind, t, t, 1, f["team"], f["guard"], f["en"], f["vis"], f["ex"], lured,
                            f["lure"][0] if f["lure"] else None, ndisp, raid, f["pup"], f["closed"], f["img"], c["cell"]))
                db.execute("INSERT INTO fort_events VALUES (?,?,?,?)", (t, f["id"], "new", kind))
            else:
                if kind == "gym" and row[0] != f["team"]:
                    db.execute("INSERT INTO fort_events VALUES (?,?,?,?)", (t, f["id"], "team", f"{row[0]}->{f['team']}"))
                if lured and not row[1]:
                    db.execute("INSERT INTO fort_events VALUES (?,?,?,?)", (t, f["id"], "lure", str(f["lure"])))
                if rocket and not row[2]:
                    db.execute("INSERT INTO fort_events VALUES (?,?,?,?)", (t, f["id"], "incident", json.dumps(f.get("disp"))[:500]))
                if raid and raid != row[3]:
                    db.execute("INSERT INTO fort_events VALUES (?,?,?,?)", (t, f["id"], "raid", raid[:500]))
                if partial:             # position, kind, EX and image stay as the last full record gave them
                    db.execute("""UPDATE forts SET last_seen=?, times_seen=times_seen+1, team=?, guard=?, enabled=?, visited=?,
                                  lured=?, lure_item=?, displays=?, raid=?, power_up_pts=?, closed=? WHERE id=?""",
                               (t, f["team"], f["guard"], f["en"], f["vis"], lured, f["lure"][0] if f["lure"] else None,
                                ndisp, raid, f["pup"], f["closed"], f["id"]))
                else:
                    db.execute("""UPDATE forts SET lat=?, lng=?, kind=?, last_seen=?, times_seen=times_seen+1, team=?, guard=?, enabled=?,
                                  visited=?, ex=?, lured=?, lure_item=?, displays=?, raid=?, power_up_pts=?, closed=?,
                                  image=COALESCE(?, image) WHERE id=?""",
                               (f["lat"], f["lng"], kind, t, f["team"], f["guard"], f["en"], f["vis"], f["ex"], lured,
                                f["lure"][0] if f["lure"] else None, ndisp, raid, f["pup"], f["closed"], f["img"], f["id"]))
            gs = f.get("gs") if kind == "gym" else None
            # a NEUTRAL gym whose reply has no GymDisplay was still read at this sighting: stamp it with NULL slots / CP
            # (= not reported), so the self-check does not call it lagging; a HELD gym without one stays an error
            if gs is not None and ("err" not in gs or (gs["err"] == "GymDisplay null" and not f["team"])):
                slots = _num(gs.get("slots"), int)
                if row is not None and row[5] is not None and slots is not None and slots != row[5]:
                    was, now_ = (6 - row[5] if row[0] else 0), (6 - slots if f["team"] else 0)   # neutral = 0 defenders
                    db.execute("INSERT INTO fort_events VALUES (?,?,?,?)",
                               (t, f["id"], "defenders", f"{was}->{now_} (slots {row[5]}->{slots})"))
                # read from THIS sighting only; the guard stops an older reply from overwriting a newer state
                db.execute("UPDATE forts SET slots=?, gym_cp=?, motivation=?, occupied_ms=?, in_battle=?, gym_state_t=?"
                           " WHERE id=? AND (gym_state_t IS NULL OR gym_state_t <= ?)",
                           (slots, _num(gs.get("cp"), int), _num(gs.get("mot"), float), _num(gs.get("occ"), int),
                            None if gs.get("battle") is None else (1 if gs["battle"] else 0), t, f["id"], t))
            if f.get("full"):
                full = f["full"]
                if partial:             # a partial full-read keeps the static fields of the record it replaces
                    old = ab._raw(db.execute("SELECT raw FROM forts WHERE id=?", (f["id"],)).fetchone()[0]) or {}
                    full = dict(full, **{k: old[k] for k in STATIC_RAW if k in old and k not in full})
                db.execute("UPDATE forts SET raw=?, raw_t=? WHERE id=? AND (raw_t IS NULL OR raw_t <= ?)",
                           (json.dumps(full), t, f["id"], t))
        for w in c["wild"]:
            nw += 1
            db.execute("INSERT OR IGNORE INTO spawns VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (w["enc"], t, w["lat"], w["lng"], w["sp"], w["pid"], w["form"], w["shiny"], w["ttl"], "wild", c["cell"]))
        for m in c["catch"]:
            nc += 1
            disp = m.get("PokemonDisplay") or {}
            db.execute("INSERT OR IGNORE INTO spawns VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (str(m.get("EncounterId")), t, m.get("Latitude"), m.get("Longitude"), m.get("SpawnPointId"),
                        m.get("PokedexTypeId") or m.get("PokemonId"), disp.get("Form"), 1 if disp.get("Shiny") else 0,
                        m.get("ExpirationTimeMs"), "catchable", c["cell"]))
        for n in c["near"]:
            nn += 1
            db.execute("INSERT OR IGNORE INTO nearby VALUES (?,?,?,?,?,?)", (n["enc"], t, n["pid"], n["form"], n["fort"], n["dist"]))
        for s in c["st"]:
            ns += 1
            sid = s.get("Id")
            if sid:
                if db.execute("SELECT 1 FROM stations WHERE id=?", (sid,)).fetchone():
                    db.execute("UPDATE stations SET last_seen=?, raw=? WHERE id=?", (t, json.dumps(s), sid))
                else:
                    db.execute("INSERT INTO stations VALUES (?,?,?,?,?,?,?)", (sid, s.get("Lat"), s.get("Lng"), s.get("Name"), t, t, json.dumps(s)))
        for r in c.get("routes") or []:
            nr += 1
            rid = r.get("Id") or json.dumps(r)[:80]
            if db.execute("SELECT 1 FROM routes WHERE id=?", (rid,)).fetchone():
                db.execute("UPDATE routes SET last_seen=?, raw=? WHERE id=?", (t, json.dumps(r), rid))
            else:
                db.execute("INSERT INTO routes VALUES (?,?,?,?)", (rid, t, t, json.dumps(r)))
    for w in rep_.get("weather") or []:
        db.execute("INSERT OR IGNORE INTO weather VALUES (?,?,?,?)", (str(w.get("S2CellId")), t[:16],
                   (w.get("GameplayWeather") or {}).get("GameplayCondition"), json.dumps(w)))
    db.execute("INSERT INTO replies VALUES (?,?,?,?,?,?,?,?)", (t, len(rep_["cells"]), nf, nw, nn, nc, ns, nr))
    return nf, nw, nn, nc, ns, nr


def store_extra(db, x):
    t, o = ts(x["t"]), x.get("o") or {}
    if x["k"] == "details" and o.get("Id"):
        imgs = o.get("ImageUrl") if isinstance(o.get("ImageUrl"), list) else [o.get("ImageUrl")]
        db.execute("INSERT OR REPLACE INTO fort_details VALUES (?,?,?,?,?,?)",
                   (o["Id"], t, o.get("Name"), o.get("Description"), json.dumps(imgs), json.dumps(o)))
        db.execute("UPDATE forts SET name=? WHERE id=?", (o.get("Name"), o["Id"]))
        return "details"
    if x["k"] == "spin" and o.get("FortId"):
        cd = o.get("CooldownComplete")
        db.execute("INSERT INTO spins VALUES (?,?,?,?,?,?)", (t, o["FortId"], o.get("Result"), o.get("XpAwarded"),
                   ts(int(cd)) if cd else None, json.dumps(o)[:20000]))
        db.execute("INSERT INTO fort_events VALUES (?,?,?,?)", (t, o["FortId"], "spin", str(o.get("Result"))))
        try:
            q = qz.store(db, t, o)
        except Exception as qe:                            # a quest that will not decode must never cost the spin row
            q = f"quest not decoded ({type(qe).__name__}: {str(qe)[:80]})"
        return ("quest", o["FortId"], q) if q else "spin"
    return None


def main():
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone")
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    ensure_columns(db)
    started = time.strftime("%Y-%m-%d %H:%M:%S")          # the self-check only judges rows written by this code
    print(f"{started[11:]} scanner started; self-check every {SELFCHECK_EVERY // 60} min", flush=True)
    sess = sc = None
    last_track, last_report, last_check = 0, 0, time.time()
    jsw = {}                                               # JS read counters since the last self-check
    while True:
        try:
            if sc is None:
                pg.wait_ready_to_attach(timeout_s=900, min_age_s=45)
                sess, pid = pg.get_session()
                sc = sess.create_script(JS)
                sc.load()
                info = sc.exports_sync.install()
                print(f"{time.strftime('%H:%M:%S')} attached pid {pid}; hooks: map {info['hooks']}, details {info['details_hooks']}, spins {info['spin_hooks']}", flush=True)
                en = info.get("enums") or {}
                qz.save_enums({k: v for k, v in en.items() if v})
                print(f"{time.strftime('%H:%M:%S')} enums: Item {len(en.get('Item') or {})} names, HoloPokemonId {len(en.get('HoloPokemonId') or {})} names"
                      + ("" if en.get("Item") and en.get("HoloPokemonId") else " -- WARNING missing: quest rewards will show ids"), flush=True)
                off = info.get("off") or {}
                miss = [k for k in ("GymDisplay", "IsInBattle") if k not in (off.get("fort") or {})]
                miss += ["GymDisplay." + k for k in ("SlotsAvailable", "TotalGymCp", "LowestPokemonMotivation", "OccupiedMillis")
                         if k not in (off.get("gd") or {})]
                if miss:
                    print(f"{time.strftime('%H:%M:%S')} WARNING PokemonFortProto has no {miss}: gym state will not be read", flush=True)
                # a fresh attach full-reads its first ~500 forts at 40 per reply (~75 s): no self-check inside that
                last_check = max(last_check, time.time() - SELFCHECK_EVERY + 120)
            tot = [0] * 6
            got = sc.exports_sync.drain()
            for k, v in (got.get("stat") or {}).items():
                jsw[k] = jsw.get(k, 0) + v
            for r in got["replies"]:
                for i, v in enumerate(store(db, r)):
                    tot[i] += v
            for x in got["extras"]:
                res = store_extra(db, x)
                if res == "details":
                    print(f"{time.strftime('%H:%M:%S')} named: {(x.get('o') or {}).get('Name')}", flush=True)
                elif isinstance(res, tuple) and res[0] == "quest":
                    nm = (db.execute("SELECT name FROM forts WHERE id=?", (res[1],)).fetchone() or [None])[0]
                    print(f"{time.strftime('%H:%M:%S')} QUEST {nm or res[1]}: {res[2]}", flush=True)
            if time.time() - last_track >= 5:
                p = me()
                if p:
                    db.execute("INSERT INTO track VALUES (?,?,?,?)", (time.strftime("%Y-%m-%d %H:%M:%S"), p[0], p[1], p[2]))
                last_track = time.time()
            db.commit()
            if time.time() - last_report >= 60:
                c = db.execute("SELECT (SELECT COUNT(*) FROM forts WHERE kind='stop'), (SELECT COUNT(*) FROM forts WHERE kind='gym'),"
                               " (SELECT COUNT(*) FROM spawns), (SELECT COUNT(*) FROM nearby), (SELECT COUNT(*) FROM stations),"
                               " (SELECT COUNT(*) FROM routes), (SELECT COUNT(*) FROM replies), (SELECT COUNT(*) FROM forts WHERE raw IS NOT NULL),"
                               " (SELECT COUNT(*) FROM fort_details), (SELECT COUNT(*) FROM spins)").fetchone()
                print(f"{time.strftime('%H:%M:%S')} DB: {c[0]} stops, {c[1]} gyms, {c[2]} spawns, {c[3]} radar, {c[4]} Power Spots,"
                      f" {c[5]} in-game routes | full records {c[7]}, named {c[8]}, spins {c[9]} | map replies {c[6]}", flush=True)
                last_report = time.time()
            if time.time() - last_check >= SELFCHECK_EVERY:
                last_check = time.time()
                try:                                       # a failing check must never cost the attach
                    # rolling window (10 min > the 5 min period, so every sighting is judged at least once), never
                    # before this scanner started: one past glitch cannot hold FAIL for the rest of the session
                    res = ab.run(db, floor=started, js=jsw, consumers=True)
                    print(f"{time.strftime('%H:%M:%S')} {res['line']}", flush=True)
                    ab.write_health(HEALTH, res)
                except Exception as ce:
                    print(f"{time.strftime('%H:%M:%S')} SELFCHECK ERROR {type(ce).__name__}: {str(ce)[:150]}", flush=True)
                jsw = {}
        except Exception as e:
            print(f"{time.strftime('%H:%M:%S')} {type(e).__name__}: {str(e)[:150]} -- re-attaching", flush=True)
            try:
                sess and sess.detach()
            except Exception:
                pass
            sess = sc = None
            time.sleep(5)
        time.sleep(2)


if __name__ == "__main__":
    main()
