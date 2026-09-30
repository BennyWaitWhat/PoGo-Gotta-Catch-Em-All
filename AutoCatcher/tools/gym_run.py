"""Gym run: head for the goal (Bryant Park), beat every enemy gym on the way and in the goal area, keep moving.

Everything is read live from the game through tools/gym_tapper.py (one per-frame tick inside PoGo): the state-machine
chain, the top screen, every gym on the map (team, position, raid timer, open slots), the open gym's own report.
Never stands still unless battling: it walks toward the next gym, circles each gym inside its live interaction range
while opening/battling, and loops the goal area's gyms when there is nothing to beat. A gym is beaten in one
continuous run (every defender, straight back in) until it is empty; then Deploy opens and it waits (circling) for you
to leave a Pokemon, unless you already have the cap (20) in gyms. It stops at once if a party screen is left open
over a battle (the bug that hid the battles on 2026-09-25).

  python tools/gym_run.py [--enemy 1,3] [--speed 10.4] [--goal LAT,LNG] [--area 170] [--minutes 180]
"""
import argparse
import subprocess
import json
import re
import math
import os
import sys
import time

import frida

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import cutoff_hunt as ch  # noqa: E402  (adb, fix, meters, api -- the joystick helpers)
import gym_tapper as gt  # noqa: E402
import pogo_il2cpp as pg  # noqa: E402

BATTLE_STATES = ("GymBattleLauncherStateShim", "GymBattleState", "GymBattleIntroState", "GymBattleResultsState")
ABORT = "abort"
STALL, DETOUR = "stall", "detour"                # drill exits: no progress (skip it a while) / a red gym with room first (come back)


class Detached(Exception):
    """The Frida session to the game dropped (network blip, gadget reset): re-attach and carry on."""


NAMES = {}                                       # gym id (8 chars) -> its name, from the gym details (the user: add the names)
FEEDREC = {"sent": 0, "applied": 0, "missed": 0, "failed": 0, "at": time.time(), "base": None}   # the feeder's own record (watched)


def feed_record():                                   # every 10 min the feeder reports its own record (the user: watch what recurs)
    if time.time() - FEEDREC["at"] < 600:
        return
    _b = FEEDREC["base"] or {"sent": 0, "applied": 0, "missed": 0, "failed": 0}
    _d = {x: FEEDREC[x] - _b[x] for x in ("sent", "applied", "missed", "failed")}
    say(f"  FEED RECORD (10 min): {_d['sent']} sent, {_d['applied']} applied, {_d['missed']} missed"
        f"{', ' + str(_d['failed']) + ' failed' if _d['failed'] else ''}"
        f"{' (' + format(_d['missed'] / _d['sent'], '.0%') + ' wasted)' if _d['sent'] else ''} | since start {FEEDREC['applied']}/{FEEDREC['sent']} applied")
    FEEDREC["at"], FEEDREC["base"] = time.time(), {x: FEEDREC[x] for x in ("sent", "applied", "missed", "failed")}


def say(s):
    if NAMES:
        s = re.sub(r"\b([0-9a-f]{8})\b", lambda m: m.group(1) if m.group(1) not in NAMES or m.string[m.end():].startswith(" (" + NAMES[m.group(1)])
                   else f"{m.group(1)} ({NAMES[m.group(1)]})", s)
    print(time.strftime("%H:%M:%S"), s, flush=True)


def stab_tag(p, names):
    """The same-type-bonus path behind one 'charged moves:' line (2026-09-30): who the tapper thinks is attacking, where the types came
    from (live = the game's own settings object, validated against our six; table = the game master, the attacker matched by its charge
    moves; none = no boost, with the reason) and the multiplier used. The first supervised run reads which path fired from this."""
    who = p.get("who")
    nm = (f"#{who} {names[who]}" if who in names else f"#{who}") if who else "unknown"
    return f" [attacker {nm}; types: {p.get('src', 'none')}" + (f" ({p['note']})" if p.get("note") else "") + f"; same-type x{p.get('mult', 1.2):g}]"


def stab_setup(sc, g, r):
    """Same-type attack bonus (STAB), 2026-09-30: say what install() resolved for it, then hand the tapper the client game master's
    multiplier + typing table (used only where the live read yields nothing). A missing data file never stops the runner."""
    sb = r.get("stab") or {}
    fld = sb.get("cadSettings") or []
    say("  same-type bonus (STAB): charge-button settings field(s) " + (", ".join(f"@{x}" for x in fld) or "NONE")
        + f"; PokemonSettingsProto types @{sb.get('setT1')}/@{sb.get('setT2')}, species @{sb.get('setId')}; multiplier x{sb.get('mult', 1.2):g} ({sb.get('multSrc')})"
        + (f"; button fields that mention a Pokemon: {', '.join(sb['related'])}" if sb.get("related") else ""))
    if not fld:
        say("  !! STAB: the charge button has no IPokemonSettings field -- the live read is off; the game master table decides (attacker matched by its charge moves)")
    if min(sb.get("setT1", -1), sb.get("setT2", -1), sb.get("setId", -1)) < 0:
        say("  !! STAB: PokemonSettingsProto types / species not all found -- the live read is off; the game master table decides")
    if not sb.get("moveType"):
        say("  !! STAB: MoveSettingsProto.Type is not a HoloPokemonType -- the same-type bonus is OFF")
    if not sb.get("typeNames"):
        say("  !! STAB: the live HoloPokemonType enum was not read -- the game master table cannot be used")
    if sb.get("err"):
        say(f"  !! STAB: resolving it raised: {sb['err']}")
    cfg = gt.stab_config()
    g.stab_names = cfg.get("names") or {}
    if cfg.get("err"):
        say(f"  !! STAB: game master table unavailable ({cfg['err']}; {cfg.get('hint')}) -- the live read decides alone")
        return
    rep = sc.exports_sync.stab({"mult": cfg["mult"], "types": cfg["types"]})
    say(f"  STAB table from the game master: {rep['types']} typings ({cfg['species']} species + {cfg['forms']} form overrides), multiplier x{rep['mult']:g} "
        f"({rep['multSrc']}; live {rep.get('liveMult')}, game master {rep.get('gmMult')})"
        + (f"; {rep['rejected']} REJECTED (type names the live enum lacks)" if rep.get("rejected") else ""))


def map_top(t):
    """The top screen is the plain map (toasts -- catch rewards, notices -- may sit over it)."""
    return t is not None and (t in ("MainMenuGuiController", "") or "Toast" in t)


class Game:
    """Live picture of the game, fed by gym_tapper's messages."""
    def __init__(self):
        self.chain, self.top, self.prep, self.round, self.battle = "", None, False, False, False
        self.gym_team, self.open_fid, self.modal, self.modal_at = None, None, False, 0
        self.ends, self.last_act, self.prepstuck, self.detached, self.outcomes = {}, 0.0, False, False, {}
        self.deploy_open = None
        self.placed, self.autoplaced, self.autoplaced_id = {}, None, None
        self.fainted, self.fainted_new = (0, []), False
        self.armed, self.batch_active = False, False
        self.deploy_refused = None
        self.study_f = None
        self.graph_stale = False                             # the live-graph tripwire fired: stop cleanly
        self.buddy_f = None                                  # the buddy session's replies (buddy_out.jsonl next to the command file)
        self.progress_at, self.opened_at, self.user_gym = time.time(), 0.0, False

    def on_msg(self, m, _d):
        if m.get("type") != "send":
            say(f"JS {m}")
            return
        p, k = m["payload"], m["payload"]["k"]
        if k == "state":
            self.progress_at = time.time()                   # any state change = the battle is moving
            entering = "GymState" in p["chain"].split(" > ") and not self.has("GymState")
            if entering:                                     # a gym screen we did not open in the last 15 s is the user's
                self.user_gym = time.time() - self.opened_at > 15
            self.chain = p["chain"]
            if "GymState" not in self.chain.split(" > "):
                self.gym_team = self.open_fid = None          # a gym report never outlives its gym screen
                self.prep = False
            say(f"    state: {self.chain.replace('RootState > MapRootState > WorldMapState > ', '')}")
        elif k == "top":
            self.top = p["gui"]
            say(f"    top screen: {self.top or '(none)'}")
        elif k == "gui":
            self.prep = p.get("open") == "GymBattlePrepUIController"
        elif k == "gymteam":
            team, fid = (0 if p["neutral"] else p["team"]), p.get("fid")
            if (team, fid) != (self.gym_team, self.open_fid):
                say(f"    gym says: team {team} ({fid[:8] if fid else fid})")
            self.gym_team, self.open_fid = team, fid
        elif k == "modal":
            self.modal, self.modal_at = p["open"], time.time()
            say(f"    modal prompt {'OPEN' if p['open'] else 'closed'}")
        elif k == "battle":
            self.battle = True
        elif k == "progress":
            self.progress_at = time.time()
        elif k == "start":
            self.round, self.last_act, self.progress_at = True, time.time(), time.time()
            say("    round start")
        elif k == "end":
            self.round = self.battle = False
            if self.open_fid:
                self.ends[self.open_fid] = self.ends.get(self.open_fid, 0) + 1
            say(f"    battle over (fast {p['fast']}, charged {p['charged']} in total)")
        elif k == "act":
            self.last_act = time.time()
            if time.time() - getattr(self, "_act_said", 0) > 10:
                self._act_said = time.time()
                say(f"    attacking: {p['fast']} fast, {p['charged']} charged so far")
        elif k == "charged":
            self.last_act = time.time()
        elif k == "moves":
            say("    charged moves: " + ", ".join(f"{m['n']} {m['dmg']} dmg / {m['en']} energy stab x{m.get('stab', 1):g}" for m in p["list"])
                + " -> the strongest fires when charged" + stab_tag(p, getattr(self, "stab_names", {})))
        elif k == "timers":
            say(f"    results timers were faint {p['faint']:.2f} s / CP drain {p['drain']:.2f} s -> 0.5 s; knockout camera {p.get('camera')} -> 0.2 s each")
        elif k == "prepstuck":
            self.prepstuck = True
            say(f"    !! the party screen is still OPEN {p['secs']:.0f} s after its battle started (state {p['state']})")
        elif k == "info":
            say(f"    {p.get('what')} {p.get('layout', '')}")
        elif k == "autoplace" and p.get("direct"):
            say(f"    DIRECT DEPLOY: the server said {p['fid'][:8]} is empty {p.get('afterVictory', '?')} ms after the victory -- "
                f"Gyarados (CP {p['cp']}) sent from the map, no gym screen")
            self.placed.pop(p["fid"], None)
            self.deploy_open = self.autoplaced = p["fid"]
            self.autoplaced_id = p["id"]
        elif k == "autoplace":
            self.placed.pop(p.get("fid"), None)              # a verdict from an earlier visit must never answer this one
            self.deploy_open = self.autoplaced = p.get("fid")
            self.autoplaced_id = p.get("id")
            say(f"    placing your shiny Gyarados (CP {p['cp']}) the instant the gym emptied -- the game's own deploy request")
        elif k == "deployopen":
            self.deploy_open = p.get("fid")
            say("    Deploy opened the instant the gym emptied -- pick your Pokemon")
        elif k == "team":
            nm = getattr(self, "names", {})
            fill = len(p["ids"]) - p["mine"]
            say(f"    battle team: {', '.join(nm.get(i, str(c)) for i, c in zip(p['ids'], p['cps']))}"
                + (f" ({fill} filled in by the game)" if fill > 0 else "") + f" -- the game had picked CP {p['was']}")
        elif k == "heal":
            nm = getattr(self, "names", {}).get(p.get("id"), p.get("id"))
            if p.get("none"):
                say(f"    !! no potions / revives left for {nm} ({p['hp']}/{p['max']} HP)")
            else:
                if p.get("ok"):
                    STATS["heals"][p["item"]] = STATS["heals"].get(p["item"], 0) + 1
                say(f"    heal {nm}: {p['hp']}/{p['max']} HP -> {p['item']}{' (during a battle)' if p['battle'] else ''}{'' if p['ok'] else ' -- REFUSED'}")
        elif k == "buddy":                                   # a teammate session's buddy call (Pokemon Switcher): log + hand back
            say(f"    BUDDY {p.get('what')} {p.get('arg') if p.get('arg') is not None else ''}: "
                + (f"error {p['err']}" if p.get("err") else json.dumps({x: p[x] for x in p if x not in ('k', 'what', 'arg', 'hist')})[:300]))
            if self.buddy_f:
                p["t"] = int(time.time() * 1000)
                self.buddy_f.write(json.dumps(p) + "\n")
                self.buddy_f.flush()
        elif k == "study":
            if self.study_f:
                self.study_f.write(json.dumps(p) + "\n")
                self.study_f.flush()
        elif k == "feed":
            nm = getattr(self, "names", {}).get(p.get("id"), p.get("id"))
            w, fid = p.get("what"), (p.get("fid") or "?")[:8]
            if w in ("result", "materesult"):
                FEEDREC["sent"] += 1
                FEEDREC["applied" if p.get("ok") else ("missed" if "not applied" in str(p.get("res")) else "failed")] += 1
            if w in ("result", "materesult") and p.get("ok"):
                STATS["fed"] += 1
            if w == "mot":
                say(f"    defender {nm} at {fid}: motivation {p['mot']:.0%} (CP {p['cp']}){' -- UNDER ATTACK' if p.get('inBattle') else ''}")
            elif w == "fed":
                say(f"    GOLDEN RAZZ -> {nm} at {fid} (motivation was {p['mot']:.0%}, CP {p['cp']}){'' if p['ok'] else ' -- the call threw'}; {p['left']} left")
            elif w == "topup":
                STATS["topups"] = STATS.get("topups", 0) + 1
                say(f"    BERRY MASTER top-up: a {p['berry']} to {'YOUR' if p.get('mine') else 'a teammate'} defender at {fid} "
                    f"({p['mot']:.0%}); {p['left']} left")
            elif w == "topupresult":
                say(f"    top-up at {fid}: {p['res']}" + (f" (+{p['sdx'][0]} stardust, +{p['sdx'][1]} XP)" if p.get('sdx') else "")
                    + (f" -- {p['n']} applied this run" if p.get('ok') else " -- top-ups pause for the server's cooldown"))
            elif w == "futile":
                say(f"    FUTILE SIEGE: {nm} at {fid} needed 3 Golden Razz within 5 min (each bought too little time) -- not feeding it for "
                    f"10 min to save berries ({p['left']} left); your other defenders are still fed")
            elif w == "siege":
                say(f"    SIEGE at {fid}: long / near-continuous battles, gaps are rare -- feeding at {p['line']:.0%} or less in ANY gap there")
            elif w == "limits":
                say(f"    feed limits for {nm} at {fid}: a Golden Razz adds {p['gold']:.0%} now; feed cooldown {p['cd'] / 1000:.0f} s")
            elif w == "noallow":
                say(f"    {nm} at {fid} is at {p['mot']:.0%} but a Golden Razz would add {p['gold']:.0%} now (allowance used) -- not feeding")
            elif w == "outside":
                say(f"    {nm} at {fid} is outside the feeding area -- not fed (your rule)")
            elif w == "fedmate":
                say(f"    GOLDEN RAZZ -> the strongest TEAMMATE defender (CP {p['max']}) at {fid} (motivation was {p['mot']:.0%}); {p['left']} left")
            elif w == "materesult":
                say(f"    teammate feed at {fid}: {p['res']}" + (f" -- motivation now {p['after']:.0%}" if p.get('after') is not None else "")
                    + (f" (+{p['sdx'][0]} stardust, +{p['sdx'][1]} XP)" if p.get('sdx') else ""))
            elif w == "result":
                say(f"    feed result for {nm} at {fid}: {p['res']}"
                    + (f" -- motivation now {p['after']:.0%}" if p.get('after') is not None else "")
                    + (f" (+{p['sdx'][0]} stardust, +{p['sdx'][1]} XP)" if p.get('sdx') else "")
                    + ("" if p.get('ok') else " -- will retry in the next gap"))
            elif w == "cooldown":
                say(f"    {nm} at {fid}: the server says {p['res']} -- next feed allowed at {time.strftime('%H:%M:%S', time.localtime(p['until'] / 1000))}")
            elif w == "wait":
                say(f"    {nm} at {fid} is at {p['mot']:.0%} with the gym mid-battle -- checking every ~1.5 s, feeding the moment the battle ends (never mid-battle: those berries are wasted)")
            elif w == "home":
                say(f"    {nm} came home from {fid}")
            elif w == "none":
                say(f"    !! {nm} at {fid} is at {p['mot']:.0%} motivation but you have NO Golden Razz left")
            else:
                say(f"    feeder: {p}")
        elif k == "deployresult":
            say(f"    deploy result: {p['res']}")
            if not p.get("ok") and self.autoplaced:        # the game said no: end the wait now, with the reason
                self.placed[self.autoplaced] = {"ok": False, "id": self.autoplaced_id, "res": p["res"]}
                self.deploy_refused = (self.autoplaced, p["res"])
        elif k == "placed":
            self.placed[p["fid"]] = p
            if p.get("ok"):
                say(f"    confirmed: {getattr(self, 'names', {}).get(p['id'], p['id'])} is in {p['fid'][:8]} ({p['ms']} ms after the request)")
        elif k == "fainted":
            self.fainted, self.fainted_new = (p["n"], p["ids"]), True
        elif k == "batchdone":
            self.batch_active = False
            say("    batch revive done -- no more heals until the next batch")
        elif k == "graph":                                   # the live-graph tripwire (H01, 2026-09-29)
            self.graph_stale = True
            say(f"    !! STALE SERVICE GRAPH: a server-confirmed Golden Razz use {p.get('secs')} s ago never reached the inventory "
                f"record this runner reads, and nothing else has for {p.get('age')} s (latestTimestamp {p.get('ts')}, before the feed "
                f"{p.get('was')}) -- the game rebuilt its services in-process; feeding is OFF and the runner stops cleanly "
                f"(a restart picks the live graph)")
        elif k == "says":
            say(f"    GAME SAYS ({p['gui']}): {p['text']}")
        elif k == "items":
            say(f"    healing items in the bag: {p['c']}")
        elif k == "outcome":
            self.outcomes[p["v"]] = self.outcomes.get(p["v"], 0) + 1
            STATS["won" if p["v"] == "victory" else "lost"] += 1
            say(f"    session result: {p['v'].upper()} (tonight: {self.outcomes.get('victory', 0)} won, {self.outcomes.get('defeat', 0)} lost)")
        elif k == "fastdelay":
            say(f"    KO -> results pause was {p['was']:.2f} s -> 0.3 s")
        elif k == "skipped":
            if time.time() - getattr(self, "_skip_said", 0) > 60:
                self._skip_said = time.time()
                say(f"    tap-through: {p['what']}")
        elif k in ("err", "exc", "opened", "continued", "pressed", "dismissed"):
            if k == "opened":
                self.opened_at = time.time()
            if k != "pressed" or p.get("what") not in ("GO",):
                say(f"    [{k}] {dict((a, b) for a, b in p.items() if a != 'k')}")
        elif k != "go":                                      # (go = the GO press, already logged as [pressed])
            say(f"    !! unhandled message from the game script: {p}")   # (the user: 'not catching msgs' -- none is dropped silently)

    def has(self, name):
        return name in self.chain.split(" > ")

    def leaf(self):
        return self.chain.split(" > ")[-1] if self.chain else ""

    def in_battle(self):
        return self.battle or self.round or any(self.has(s) for s in BATTLE_STATES)

    def wait_for(self, pred, timeout, tick=None):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.detached:
                raise Detached("game connection lost")
            if pred():
                return True
            if tick:
                tick()
            time.sleep(0.2)
        return pred()


class Mover:
    """Never stand still: every movement is a joystick WALK, re-sent when the plan changes, when the walk should have
    finished, or when the avatar has not moved 1.5 m in 8 s (real clock, not the fix's own timestamps)."""
    def __init__(self, speed, travel_speed=None):
        self.speed, self.key, self.sent, self.expect, self.samples = speed, None, 0.0, 0.0, []
        self.travel_speed = travel_speed or speed             # only while far from the goal area; everything else at `speed`
        self.fast = False

    def _walk(self, key, pts, here, speed=None):
        speed = speed or self.speed
        wp = ";".join(f"{x:.6f},{y:.6f}" for x, y in pts)
        ch.api("WALK", f'--es waypoints "{wp}" --ef speed {speed}')
        route = ch.meters(here, pts[0]) + sum(ch.meters(a, b) for a, b in zip(pts, pts[1:]))
        self.key, self.sent, self.expect, self.samples = key, time.monotonic(), route / (speed / 3.6) + 10, []

    def due(self, here):
        now = time.monotonic()
        self.samples = [s for s in self.samples if now - s[2] <= 12] + [(here[0], here[1], now)]
        old = [s for s in self.samples if now - s[2] >= 8]
        stalled = bool(old) and ch.meters(old[-1][:2], here) < 1.5
        return stalled or now - self.sent > self.expect

    def travel(self, pt, here):
        key = ("travel", round(pt[0], 5), round(pt[1], 5), self.fast)
        if key != self.key or self.due(here):
            self._walk(key, [pt], here, self.travel_speed if self.fast else self.speed)

    def orbit(self, center, here, r=25.0, laps=40):
        """Circle a point at r meters (a gym: well inside its live interaction range)."""
        key = ("orbit", round(center[0], 5), round(center[1], 5), r)
        if key != self.key or self.due(here):
            n, cl = 12, math.cos(math.radians(center[0]))
            ring = [(center[0] + r * math.cos(2 * math.pi * i / n) / 111320.0,
                     center[1] + r * math.sin(2 * math.pi * i / n) / (111320.0 * cl)) for i in range(n)]
            i0 = min(range(n), key=lambda i: ch.meters(here, ring[i]))
            self._walk(key, [ring[(i0 + i) % n] for i in range(n * laps + 1)], here)

    def loop(self, pts, here, laps=6):
        """Walk a closed loop through pts, starting at the nearest one."""
        key = ("loop", tuple((round(x, 5), round(y, 5)) for x, y in pts))
        if key != self.key or self.due(here):
            i0 = min(range(len(pts)), key=lambda i: ch.meters(here, pts[i]))
            self._walk(key, [pts[(i0 + i) % len(pts)] for i in range(len(pts) * laps + 1)], here)


BUSY = {}                                        # fort id -> smoothed share of scans that found it in battle (contest level)


def pick(enemy, skip, here, goal, live, detour, area_r, ok=None):
    """The nearest enemy gym on the LIVE map that is raid-free and on the way: at most `detour` extra meters versus
    walking straight to the goal, or anywhere inside the goal area. `ok(fid, v)` admits more (a red gym with a free slot)."""
    best, best_key = None, None
    for fid, v in live.items():
        team, age, lat, lng, raid_left = v[0], v[1], v[2], v[3], v[4]
        if fid in skip or age > 60000 or raid_left or not (team in enemy or (ok and ok(fid, v))):
            continue
        gp = (lat, lng)
        in_area = ch.meters(gp, goal) <= area_r
        extra = ch.meters(here, gp) + ch.meters(gp, goal) - ch.meters(here, goal)
        if extra > detour and not in_area:
            continue
        d_m = ch.meters(here, gp)                            # the user (02:52): dominate strategically -- the CHEAPEST gym, not the closest
        cp = v[7] if len(v) > 7 and v[7] > 0 else 0
        contest = BUSY.get(fid, 0.5) * 60                    # a contested gym costs berries to hold / gets fed while we drain it
        if team == 0 or team not in enemy:                   # empty, or a red gym with room: a placement with no battle
            cost = d_m * 0.35 - 60 + contest
        else:                                                # walking time + the CP to drain (measured ~1-2k CP per 40 s session)
            cost = d_m * 0.35 + cp * 0.03 + contest
        key = (0 if in_area else 1, cost)
        if best is None or key < best_key:
            best, best_key = (fid, gp, team), key
    return best


def live_range(sess):
    """FortSettings.InteractionRangeMeters, read live from GlobalSettingsProto (C liveness walk; before any hook)."""
    import dump_game_limits as dl
    s = sess.create_script(dl.JS)
    s.load()
    try:
        return float(((s.exports_sync.global_settings().get("settings") or {}).get("FortSettings") or {})["InteractionRangeMeters"])
    finally:
        s.unload()


def bag_status(sess, tapper=None):
    """One live bag walk (C-only instance lookup, safe with the tapper attached): (your deployed count, your shiny
    Gyarados not in a gym, highest CP first, as [(id, cp, hp, maxhp)], the attack roster highest CP first as
    [(id, cp, hp, maxhp, name)] -- everything that can fight except Slaking and the shiny Gyarados kept for placing).
    Species ids and names from the live enum."""
    import dump_game_limits as dl
    js = dl.JS.split("rpc.exports = {")[0] + r"""
var PO = null, GY = -1, DO = null, SLAKING = -1, NAMES = {};
var CFN = f('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']);
function byName(ns, name) {                   /* exact-name lookup per image -- never a walk over every class (that crashed PoGo twice) */
  var sp = Memory.alloc(PS), a = IL.asms(IL.domain(), sp), n = sp.readU32(), nsp = Memory.allocUtf8String(ns), nmp = Memory.allocUtf8String(name);
  for (var i = 0; i < n; i++) { var k = CFN(IL.asmImage(a.add(i * PS).readPointer()), nsp, nmp); if (!k.isNull()) return k; }
  return null;
}
var CGF = f('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']), FGN = f('il2cpp_field_get_name', 'pointer', ['pointer']), SGV = f('il2cpp_field_static_get_value', 'void', ['pointer', 'pointer']);
function nice(n) { n = n.replace(/_$/, ''); return n.charAt(0).toLowerCase() + n.slice(1); }
function setup() {
  if (PO) return; PO = {}; DO = {};
  fieldsOf(byName('Holoholo.Rpc', 'PokemonProto')).forEach(function (x) { PO[nice(x.name)] = x.off; if (nice(x.name) === 'pokemonDisplay') DO._k = IL.classFromType(x.t); });
  fieldsOf(DO._k).forEach(function (x) { DO[nice(x.name)] = x.off; });
  var k = byName('Holoholo.Rpc', 'HoloPokemonId'); if (!k) throw new Error('HoloPokemonId not found');
  var it = Memory.alloc(PS), fd; it.writePointer(NULL);
  while ((fd = CGF(k, it)) && !fd.isNull()) { var fn = cs(FGN(fd)); if (fn === 'value__') continue;
    var b = Memory.alloc(8); b.writeS64(0); SGV(fd, b); var v = b.readS32(); NAMES[v] = fn.replace(/^V\d+Pokemon/, '');
    if (fn === 'V0130PokemonGyarados') GY = v; if (fn === 'V0289PokemonSlaking') SLAKING = v; }
  if (GY < 0 || SLAKING < 0) throw new Error('Gyarados / Slaking id not found in the live enum');
}
rpc.exports = {
  scan: function (ptrs) {
    setup(); var dep = 0, gy = [], ro = [], dp = [], fa = [];
    ptrs.forEach(function (q) { var p = ptr(q);
      if (str(p.add(PO.deployedFortId).readPointer())) { dep++;
        dp.push([p.add(PO.id).readU64().toString(), p.add(PO.cp).readS32(), NAMES[p.add(PO.pokemonId).readS32()] || '?',
          p.add(PO.deployedGymLatDegree).readDouble(), p.add(PO.deployedGymLngDegree).readDouble(), str(p.add(PO.deployedFortId).readPointer())]); return; }
      if (p.add(PO.isEgg).readU8() || p.add(PO.isBad).readU8() || str(p.add(PO.deployedStationId).readPointer())) return;
      var sp = p.add(PO.pokemonId).readS32(), d = p.add(PO.pokemonDisplay).readPointer(), shiny = !d.isNull() && d.add(DO.shiny).readU8();
      var row = [p.add(PO.id).readU64().toString(), p.add(PO.cp).readS32(), p.add(PO.stamina).readS32(), p.add(PO.maxStamina).readS32(), NAMES[sp] || String(sp)];
      if (row[2] <= 0 && row[3] > 0) fa.push([row[0], row[1], row[4]]);
      if (sp === GY && shiny) gy.push(row.slice(0, 4));              /* the placement stock */
      else if (sp !== SLAKING) ro.push(row); });
    ro.sort(function (x, y) { return y[1] - x[1]; });
    return {dep: dep, gy: gy, ro: ro.slice(0, 80), dp: dp, fa: fa};
  }
};"""
    s = sess.create_script(js)
    s.load()
    try:
        live = tapper.exports_sync.bag() if tapper is not None else None
        if not live:                                         # never the biggest / first bag: after an in-process rebuild the frozen one wins
            raise RuntimeError("no live-graph bag from the tapper (it refuses to guess between the game's service graphs)")
        best = list(pg.walk_bag_protos(sess, live).values())
        if not best:
            raise RuntimeError("the live bag read empty")
        dep, gy, ro, dp, fa = 0, [], [], [], []
        for i in range(0, len(best), 500):
            r = s.exports_sync.scan(best[i:i + 500])
            dep += r["dep"]
            gy += r["gy"]
            ro += r["ro"]
            dp += r["dp"]
            fa += r["fa"]
        gy.sort(key=lambda x: -x[1])
        ro.sort(key=lambda x: -x[1])
        fa.sort(key=lambda x: -x[1])
        return dep, gy, ro[:80], dp, fa
    finally:
        s.unload()


STATS = {"t0": time.time(), "area_t0": time.time(), "emptied": 0, "placed": 0, "won": 0, "lost": 0, "fed": 0, "heals": {}, "gym_s": []}


def stats_line(dep, a):
    m = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"
    gs = STATS["gym_s"]
    heals = ", ".join(f"{k} {v}" for k, v in sorted(STATS["heals"].items())) or "none"
    return (f"  STATS  run {m(time.time() - STATS['t0'])} (this area {m(time.time() - STATS['area_t0'])}) | gyms emptied "
            f"{STATS['emptied']}, joined {STATS.get('joins', 0)}, placed {STATS['placed']} | yours in gyms {dep.get('n', '?')} (in this area {dep.get('held', '?')}"
            f"{f', leaving at {a.hold}' if a.next_goal else ''}) | sessions won {STATS['won']} lost {STATS['lost']} | "
            f"avg {m(sum(gs) / len(gs)) if gs else '-'} per emptied gym | fainted {dep.get('nfa', '?')}/{a.heal_batch} "
            f"(batch heals {STATS.get('batches', 0)}) | items: {heals} | Golden Razz fed {STATS['fed']}")


BUSY_FILE = "/data/local/tmp/pogo_desktop_busy"          # the shared phone-access marker: "<name> <epoch deadline>"
BUSY_NAME = "GymBattle/%d" % os.getpid()


def phone_mark(hold):
    """The marker is ADVISORY (Benny, 2026-09-29: "no one should be pausing anything for anyone"). The runner writes its own
    only around the world-stopping phases -- the install scans and quiesce + unload -- and clears it after them if it is still
    ours; a foreign live marker is logged, never waited for. adb through cutoff_hunt (-s the phone: a TV shares the server)."""
    try:
        o = ch.adb(f"cat {BUSY_FILE} 2>/dev/null; echo; date +%s").split()
        now = int(o[-1])
        who, dl = (o[-3], int(o[-2])) if len(o) >= 3 and o[-2].isdigit() else (None, 0)
        if hold and who not in (None, "free", BUSY_NAME) and dl > now:
            say(f"  (phone marker: {who} is attached too, for another {dl - now} s -- advisory, carrying on)")
        if hold or who == BUSY_NAME:
            txt = f"{BUSY_NAME} {now + 300}" if hold else "free 0"
            ch.adb(f"su -c 'echo \"{txt}\" > {BUSY_FILE}; chmod 666 {BUSY_FILE}'")
    except Exception as e:
        say(f"  (phone marker not updated: {e})")


def deployed_count(sess, tapper=None):
    """How many of your Pokemon sit in gyms right now (the live bag walk)."""
    return bag_status(sess, tapper)[0]


def leave_gym(g, sc, tick):
    """Back to the map: the gym screen's own back twice, then the game's own Android back handling. A party screen on
    top is closed with the game's back first (the gym's own back under it would orphan it over the map)."""
    for i in range(4):
        if not g.has("GymState"):
            return True
        if g.prep:
            ch.adb("input keyevent 4")
            g.wait_for(lambda: not g.prep, 4, tick)
            continue
        if i < 2:
            sc.exports_sync.act("back")
        else:
            ch.adb("input keyevent 4")
        g.wait_for(lambda: not g.has("GymState"), 5, tick)
    return not g.has("GymState")


def drill(fid, enemy, g, sc, a, tick, until, refresh=None, join_near=None, cmd_waiting=None):
    """Beat the gym in one continuous run until it is no longer an enemy gym. Returns its final team, None (gave up),
    or ABORT (a party screen was left open over a battle -- stop everything)."""
    opens = misses = backs = go_misses = hangs = 0
    noreport, live_at, lv, odd_since = None, 0.0, None, None
    last_end, cps = g.ends.get(fid, 0), []               # the gym's total CP at each session end: is it moving?
    leaving = None                                       # STALL / DETOUR: finish the battle in progress, then leave
    dw = {"at": 0.0, "key": None, "seen": 0.0}               # drill watch: the gym's own state every 2 s
    while time.time() < until or g.in_battle():             # never walk away from a battle in progress
        if g.detached:
            raise Detached("game connection lost")
        tick()
        if g.prepstuck:
            return ABORT
        if g.autoplaced == fid and fid in g.placed:          # a direct deploy went out and was answered: nothing left to beat
            return 0
        if not g.chain:
            time.sleep(0.3)
            continue
        if time.time() - dw["at"] > 2:                       # the user: nobody can ADD a defender while it is in battle -- verify
            dw["at"] = time.time()
            sc.exports_sync.scan([fid])
            _sv = sc.exports_sync.scanned().get(fid)
            if _sv and _sv[1] < 4000 and dw["seen"] != round(time.time() * 1000 - _sv[1], -2):
                dw["seen"] = round(time.time() * 1000 - _sv[1], -2)
                _key = (_sv[0], _sv[3], _sv[2])
                if _key != dw["key"]:
                    _prev = dw["key"]
                    dw["key"] = _key
                    _added = _prev is not None and _sv[0] == _prev[0] and _sv[3] > _prev[1]
                    say(f"    WATCH {fid[:8]}: {_sv[3]} defender(s), {_sv[4]} CP, server says {'IN BATTLE' if _sv[2] else 'NOT in battle'}"
                        f"{' -- a defender was ADDED (last reading: ' + ('in battle' if _prev[2] else 'not in battle') + ')' if _added else ''}"
                        f" [client: {'battle' if g.in_battle() else g.leaf()}]")
                    if g.study_f:
                        g.study_f.write(json.dumps({"k": "study", "src": "drillwatch", "t": int(time.time() * 1000) - _sv[1], "fid": fid,
                                                    "team": _sv[0], "n": _sv[3], "cp": _sv[4], "ib": _sv[2], "added": _added,
                                                    "client": "battle" if g.in_battle() else g.leaf()}) + "\n")
        if g.in_battle():                                    # the tick is fighting; watch that the battle MOVES
            if refresh and g.fainted_new:                    # the phone counted the fainted after the last battle
                g.fainted_new = False
                refresh()
            stall = time.time() - g.progress_at
            if stall > a.hang_secs:
                hangs += 1
                say(f"  battle hung: no knockout, charge or screen change for {stall:.0f} s -- the game's own "
                    f"recovery (GymState.FailedToStartBattle), try {hangs}")
                sc.exports_sync.act("unhang")
                g.progress_at = time.time()
                if hangs >= 4:
                    say("  !! the battle will not leave after 4 recoveries -- giving up on this gym")
                    return None
            time.sleep(0.2)
            continue
        if leaving and not g.prep:                           # the session in progress is over: leave now
            leave_gym(g, sc, tick)
            return leaving
        if time.time() - live_at > 2:
            live_at, lv = time.time(), sc.exports_sync.teams().get(fid)
        if lv and lv[4] and not g.has("GymState"):
            say("  a raid appeared on it -- no gym battles now")
            return None
        if g.ends.get(fid, 0) != last_end and lv and len(lv) > 7 and lv[7] > 0:
            last_end = g.ends.get(fid, 0)
            cps.append(lv[7])
            say(f"    progress: session {len(cps)} ended with the gym at {lv[7]} total CP"
                + (f" (started {cps[0]}, {100 - 100 * lv[7] // cps[0]}% drained)" if len(cps) > 1 else ""))   # the user: never give up
            if len(cps) >= 8:                                # ...but make sure progress is being made
                lo = min(cps)
                since = len(cps) - 1 - max(i for i, c in enumerate(cps) if c == lo)
                if since >= 6 and cps[-1] > lo * 1.3:
                    leaving = STALL
                    say(f"  STALEMATE at {fid[:8]}: {since} sessions without a new low (lowest {lo}, now {cps[-1]} CP) -- its team "
                        f"feeds/refills it faster than we drain it; moving on, back to it in 10 min")
            if not leaving and cmd_waiting and cmd_waiting():   # a live command (go / hunt) is waiting: it decides now
                leaving = DETOUR
                say(f"  a new command is waiting -- leaving {fid[:8]} after this session")
            if not leaving and join_near:
                jf = join_near(fid)
                if jf:
                    leaving = DETOUR
                    say(f"  a red gym with room is in reach ({jf[:8]}) -- placing there first, then back to {fid[:8]}")
            if leaving:
                sc.exports_sync.autodeploy(None)             # no new automatic Battle on the gym being left
                g.armed = False
                continue
        if g.has("GymState"):
            if g.open_fid and g.open_fid != fid and not g.prep:
                backs += 1
                say(f"  another gym ({g.open_fid[:8]}) is open -- leaving it (try {backs})")
                leave_gym(g, sc, tick)
                if backs >= 3:
                    return None
                continue
            if g.open_fid != fid or g.gym_team is None:
                noreport = noreport or time.time()
                if time.time() - noreport > 10:
                    say("  the gym screen never reported this gym -- leaving")
                    leave_gym(g, sc, tick)
                    return None
                time.sleep(0.3)
                continue
            noreport = None
            opens = 0                                        # it opened and reported: only consecutive failed opens count
            if g.gym_team not in enemy:
                return g.gym_team
            if g.ends.get(fid, 0) >= a.max_sessions:
                say(f"  {a.max_sessions} battle sessions and still team {g.gym_team} -- giving up on it")
                return None
            leaf = g.leaf()
            if leaf == "GymApproachDetailsState":            # a defender's card: back to the gym
                sc.exports_sync.act("back")
                g.wait_for(lambda: g.leaf() != "GymApproachDetailsState", 4, tick)
                continue
            if g.modal and time.time() - g.modal_at > 3:
                sc.exports_sync.act("dismissmodal")
                time.sleep(1)
            if g.prep:                                       # party screen: gym_tapper presses GO itself, once
                if not g.wait_for(g.in_battle, 1.5, tick):   # not ours (left over from a restart)? GO on it now, not 12 s later
                    sc.exports_sync.act("go")
                if g.in_battle() or g.wait_for(g.in_battle, 12, tick):
                    go_misses = 0
                else:
                    go_misses += 1
                    say(f"  GO did not start a battle -- the game's back on the party screen (try {go_misses}/3)")
                    ch.adb("input keyevent 4")
                    g.wait_for(lambda: not g.prep, 4, tick)
                    if go_misses >= 3:
                        return None
                continue
            if leaf == "GymApproachState":                   # gym screen: the phone presses Battle itself; this only backs it up
                if not g.wait_for(lambda: g.prep or g.in_battle(), 4.0 if g.armed else 1.0, tick):   # armed: the phone presses it
                    sc.exports_sync.act("battle")
                if g.wait_for(lambda: g.prep or g.in_battle(), 6, tick):
                    misses = 0
                else:
                    misses += 1
                    say(f"  Battle did not open the party screen (top '{g.top}', modal {g.modal}) -- try {misses}/3")
                    if misses >= 3:
                        return None
                continue
            if leaf and leaf.startswith("GymBattle"):        # battle intro / results / launcher: the tick handles it -- NEVER press BACK
                odd_since = None
                time.sleep(0.2)
                continue
            odd_since = odd_since or time.time()            # a gym sub-screen this loop does not handle
            if time.time() - odd_since > 20:
                say(f"  stuck on '{leaf}' (top '{g.top}') for 20 s -- the game's back")
                ch.adb("input keyevent 4")
                odd_since = None
            time.sleep(0.4)
            continue
        odd_since = None
        if not map_top(g.top) or g.leaf() != "MapExploreState":   # another screen is up: never open over it
            time.sleep(0.2)
            continue
        if opens >= 3:
            say("  the gym would not open 3 times -- giving up on it")
            return None
        opens += 1
        sc.exports_sync.open(fid)
        if not g.wait_for(lambda: g.has("GymState"), 12, tick):
            say(f"  open attempt {opens}: still '{g.leaf()}' (top '{g.top}')")
    lv = sc.exports_sync.teams().get(fid)
    if lv and lv[0] == 0:
        say("  gym deadline reached, but it is EMPTY now -- placing")
        return 0
    say("  gym deadline reached -- moving on")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enemy", default="1,3", help="teams to beat (yours is red = 2)")
    ap.add_argument("--speed", type=float, default=10.4, help="km/h while circling a gym; 10.4 keeps egg/buddy walking credit")
    ap.add_argument("--travel-speed", type=float, default=None, help="km/h only while outside the goal area (default: --speed)")
    ap.add_argument("--no-adopt", dest="adopt", action="store_false", help="do not carry on with a gym already open at start")
    ap.add_argument("--goal", default="40.753597,-73.983233", help="lat,lng to head for (default Bryant Park)")
    ap.add_argument("--area", type=float, default=170, help="radius (m) around the goal where every enemy gym is fair game")
    ap.add_argument("--detour", type=float, default=300, help="max extra meters to take a gym on the way")
    ap.add_argument("--minutes", type=float, default=180)
    ap.add_argument("--gym-minutes", type=float, default=100000, help="never give up on a gym (the user's rule); a huge outer cap")
    ap.add_argument("--max-sessions", type=int, default=100000, help="never give up on a gym (the user's rule); a huge outer cap")
    ap.add_argument("--hang-secs", type=float, default=45, help="a battle with no progress this long is hung: recover it")
    ap.add_argument("--place-wait", type=float, default=240, help="seconds to wait (circling) for you to leave a Pokemon")
    ap.add_argument("--max-deployed", type=int, default=20, help="the gym cap: at it, empty the gym and move on")
    ap.add_argument("--prewait", type=float, default=5, help="minutes: wait on a non-red gym whose raid ends within this")
    ap.add_argument("--no-autoplace", dest="autoplace", action="store_false", help="open Deploy for you instead of placing a shiny Gyarados")
    ap.add_argument("--heal-top", type=int, default=0, help="keep this many of the highest-CP attackers healed at all times (0 = never; the user's rule)")
    ap.add_argument("--heal-batch", type=int, default=30, help="revive every fainted Pokemon once this many are fainted (0 = never)")
    ap.add_argument("--no-feed", dest="feed", action="store_false", help="never feed Golden Razz to your defenders")
    ap.add_argument("--no-battle", dest="battle", action="store_false", help="battle break: no gyms, keep moving and feeding the defenders")
    ap.add_argument("--route", default=None, help="battle break: walk these waypoints once (lat,lng;lat,lng;...), then circle the goal")
    ap.add_argument("--lap-every", type=int, default=0, help="while battling: after this many placements, walk --route once, then battle again")
    ap.add_argument("--start-lap-at", type=int, default=None, help="start inside a lap, at this --route waypoint index")
    ap.add_argument("--no-feed-mate", dest="feed_mate", action="store_false", help="do not also feed the strongest teammate in your gyms")
    ap.add_argument("--topup", action="store_true", help="Berry Master: regular berries to defenders in quiet gaps (never golden)")
    ap.add_argument("--topup-reserve", type=int, default=30, help="keep at least this many of each regular berry")
    ap.add_argument("--attack-report", type=float, default=3.0,   # Benny 2026-09-30 ("Maybe middle ground?"): 3 s, was 1.5 -- 20 reports/min instead of 40
                    help="s between the battle's attack reports (server setting 5; 0 = leave it)")
    ap.add_argument("--cmd", default=None, help="live command file (JSON, re-read when it changes): {go: fid} / {hunt: meters}")
    ap.add_argument("--join-first", default=None, help="fort id: go there first -- beat + place (enemy/empty) or join (red with room)")
    ap.add_argument("--study", default=None, help="append the feed-study JSON lines (gym readings, map flags, feed replies) here")
    ap.add_argument("--feed-zone", default=None, help="lat,lng,radius_m: feed only defenders in gyms inside this circle")
    ap.add_argument("--next-goal", default=None, help="lat,lng: once you hold --hold gyms around --goal, go here (fast trip)")
    ap.add_argument("--next-area", type=float, default=170, help="radius (m) around --next-goal")
    ap.add_argument("--hold", type=int, default=6, help="gyms to hold around --goal before heading to --next-goal")
    ap.add_argument("--team", type=int, default=2, help="your team (2 = red): its gyms with a free slot are joined without a battle")
    ap.add_argument("--feed-at", type=float, default=0.34, help="feed a Golden Razz at this motivation or less (the last third)")
    ap.add_argument("--feed-hot", type=float, default=0.34, help="...or at this level when the gym was attacked in the last 5 min (the server allows ~10 berries per defender, so a buffer burns them)")
    a = ap.parse_args()
    enemy = [int(x) for x in a.enemy.split(",")]
    goal = [float(x) for x in a.goal.split(",")]               # a list: the next-goal switch survives a re-attach
    mv, done, t_start = Mover(a.speed, a.travel_speed), {}, time.time()
    while time.time() - t_start < a.minutes * 60:            # re-attach and carry on if the game connection drops
        g = Game()
        try:
            run(a, g, mv, done, t_start, enemy, goal)
            return
        except (Detached, frida.InvalidOperationError, frida.TransportError, frida.ServerNotRunningError) as e:
            say(f"lost the game connection ({type(e).__name__}: {e}) -- re-attaching in 3 s")
            time.sleep(3)
        except Exception as e:                               # never die: a relaunched / recovering game is re-attached by itself
            say(f"session failed ({type(e).__name__}: {e}) -- retrying in 10 s")
            time.sleep(10)


def run(a, g, mv, done, t_start, enemy, goal):
    """One attached session: attach, install, then walk/battle until the time is up or a STOP."""
    pg.wait_ready_to_attach(timeout_s=300, min_age_s=45)
    pg.busy_acquire = lambda *_a, **_k: None                 # the marker is advisory: get_session must never wait / refuse (phone_mark)
    sess, pid = pg.get_session()
    sc = sess.create_script(gt.JS)
    sc.on("message", g.on_msg)
    sess.on("detached", lambda *args: setattr(g, "detached", True))
    sc.load()
    try:
        return _run(a, g, mv, done, t_start, enemy, goal, sess, pid, sc)
    finally:                                                 # never leave a second tapper hooked on a re-attach
        phone_mark(True)                                     # a world-stopping phase: say so on the phone (advisory)
        try:                                                 # quiet first: an unload while a hook is inside a game call deadlocked the game (03:39)
            sc.exports_sync.quiesce()
            time.sleep(1.0)
        except Exception:
            pass
        for f in (sc.unload, sess.detach):
            try:
                f()
            except Exception:
                pass
        phone_mark(False)


def _run(a, g, mv, done, t_start, enemy, goal, sess, pid, sc):
    phone_mark(True)                                         # the install's liveness scans stop the GC world: say so (advisory)
    try:
        r = sc.exports_sync.install()
    finally:
        phone_mark(False)                                    # steadily attached from here: exempt, like the on-phone catcher
    rng = r.get("range") or 80.0                             # FortSettings.InteractionRangeMeters, read live at install
    engage, orbit_r = rng - 10, 25.0                         # open it from 70 m while still walking in to the 25 m circle
    if not r.get("ok"):
        say(f"attached pid {pid}, but these could not be read live -- not running: {r.get('missing')}")
        return
    if r.get("feed") is not True:
        say(f"  !! Golden Razz feeder unavailable: {r.get('feed')}")
    elif r.get("detailsParams"):
        say(f"  gym-details request parameters: {r['detailsParams']}")
    if r.get("team") is not True:
        say(f"  !! custom team / heal unavailable: {r.get('team')}")
    _gr = r.get("graph") or {}                               # the live service graph (H01, 2026-09-29): which one, and how fresh
    say(f"  live service graph: {_gr.get('graphs', '?')} ItemBagImpl graph(s), inventory last updated "
        + (f"{(time.time() * 1000 - _gr['ts']) / 1000:.0f} s ago" if (_gr.get("ts") or -1) > 0 else "(unreadable)")
        + (f"; older graphs at {_gr['other']} -- the game rebuilt its services in-process, reading the newest" if _gr.get("other") else ""))
    for _gn in r.get("graphNotes") or []:
        say(f"  !! live graph: {_gn}")
    stab_setup(sc, g, r)                                     # same-type bonus: what install() resolved + the game master's typing table
    sc.exports_sync.feedcfg(a.feed, a.feed_at, a.feed_hot, a.feed_mate)
    if a.study and os.path.exists(a.study):                  # contest level of each gym, seeded from the last hour of readings
        try:
            _cut, _cnt = time.time() * 1000 - 3600000, {}       # (own names: 'r' here is the install() result -- never shadow it)
            for _ln in open(a.study, encoding="utf-8").readlines()[-20000:]:
                _rec = json.loads(_ln)
                if _rec.get("src") in ("scan", "details") and _rec.get("t", 0) > _cut:
                    _c = _cnt.setdefault(_rec["fid"], [0, 0]); _c[0] += 1; _c[1] += 1 if _rec.get("ib") else 0
            for _f, (_n, _b) in _cnt.items():
                if _n >= 10:
                    BUSY[_f] = _b / _n
            if BUSY:
                say("  contest level (share of readings in battle, last hour): "
                    + ", ".join(f"{_k[:8]} {_v:.0%}" for _k, _v in sorted(BUSY.items(), key=lambda x: x[1])))
        except Exception as e:
            say(f"  (contest seed skipped: {e})")
    if a.attack_report > 0:                                  # shorter 'not in battle' windows after each knockout
        say(f"  battle attack reports every {a.attack_report} s instead of 5: {sc.exports_sync.fastreport(a.attack_report)}")
    if a.topup:
        _tu = sc.exports_sync.topup(True, a.topup_reserve)
        say(f"  Berry Master top-ups ON: regular berries only, quiet gaps only, keeping {a.topup_reserve} of each -- in the bag: {_tu.get('berries')}")
    if a.cmd:
        g.buddy_f = open(os.path.join(os.path.dirname(a.cmd), "buddy_out.jsonl"), "a", encoding="utf-8")
    if a.study:                                              # the game's own freshness signals, one JSON line per event
        g.study_f = open(a.study, "a", encoding="utf-8")
        sc.exports_sync.study(True)
        say(f"  feed study: recording gym readings, map battle flags and feed replies to {a.study}")
    if a.feed_zone:                                          # berries only for the defenders in gyms around the goal
        z = [float(x) for x in a.feed_zone.split(",")]
        sc.exports_sync.feedzone(z[0], z[1], z[2])
        say(f"  Golden Razz ONLY for gyms within {z[2]:.0f} m of {z[0]:.5f},{z[1]:.5f} (the others are not fed)")
    say(f"attached pid {pid}: {r['gyms']} gyms on the game's map directory; live fort range {rng:.0f} m -> engage inside "
        f"{engage:.0f} m, circle gyms at {orbit_r:.0f} m, {a.speed} km/h")
    g.wait_for(lambda: g.chain and g.top is not None, 10)
    say(f"starting in state: {g.chain or 'unknown'} / top {g.top}")
    target, said = None, None
    dep = {"n": None, "at": 0.0, "gy": [], "ro": [], "dp": [], "fa": []}   # deployed, Gyarados, roster, defenders, fainted -- OFF the critical path

    def refresh_deployed(force=False):
        if force or dep["n"] is None or time.time() - dep["at"] > 600:
            try:
                dep["n"], dep["gy"], dep["ro"], dep["dp"], dep["fa"] = bag_status(sess, sc)
                dep["at"] = time.time()
                top = ", ".join(f"{cp}{'' if hp >= mx else ' (hurt)'}" for _, cp, hp, mx in dep["gy"][:5])
                say(f"  your Pokemon in gyms right now: {dep['n']}/{a.max_deployed}; shiny Gyarados ready to place (CP): {top} (live bag)")
                g.names = {x[0]: f"{x[4]} {x[1]}" for x in dep["ro"]}
                g.names.update({x[0]: f"Gyarados {x[1]}" for x in dep["gy"]})
                g.names.update({x[0]: f"{x[2]} {x[1]}" for x in dep["dp"]})
                nfa = len(dep["fa"])
                batch = [x[0] for x in dep["fa"]] if a.heal_batch and nfa >= a.heal_batch and not g.batch_active else []   # none until 30 fainted
                g.names.update({x[0]: f"{x[2]} {x[1]}" for x in dep["fa"]})
                rr = sc.exports_sync.roster([x[0] for x in dep["ro"]], a.heal_top, batch, [x[0] for x in dep["gy"]])
                up = ([x for x in dep["ro"] if x[2] * 2 >= x[3]] + [x for x in dep["ro"] if 0 < x[2] and x[2] * 2 < x[3]])[:6]
                say("  attack team = highest CP with HP left, no Slaking, no placement Gyarados: "
                    + ", ".join(f"{x[4]} {x[1]}{'' if x[2] >= x[3] else f' ({x[2]}/{x[3]} HP)'}" for x in up)
                    + ("" if rr.get("live") else "  [!! bag not readable live -- the game's own team is used]"))
                if batch:
                    g.batch_active = True
                    say(f"  {nfa} fainted (batch at {a.heal_batch}) -- reviving ALL of them now, one Max Revive each while they last")
                    STATS["batches"] = STATS.get("batches", 0) + 1
                else:
                    say(f"  fainted: {nfa}/{a.heal_batch} -- no heals or revives until {a.heal_batch}")
                dep["nfa"] = nfa
                dep["held"] = sum(1 for x in dep["dp"] if ch.meters((x[3], x[4]), goal) <= a.area)
                if a.next_goal and dep["held"] >= a.hold:   # the user's plan: hold N here, then the next place (fast trip)
                    ng = [float(x) for x in a.next_goal.split(",")]
                    say(f"  >> you hold {dep['held']} gyms in this area (goal {a.hold}) -- heading to the next place "
                        f"{ng[0]:.5f},{ng[1]:.5f} at {mv.travel_speed:.0f} km/h, then normal speed")
                    goal[:] = ng
                    a.area, a.next_goal = a.next_area, None
                    STATS["area_t0"] = time.time()
                    dep["held"] = sum(1 for x in dep["dp"] if ch.meters((x[3], x[4]), goal) <= a.area)
                if a.feed:
                    fd = sc.exports_sync.defenders([x[0] for x in dep["dp"]])
                    say(f"  Golden Razz watch: {', '.join(g.names.get(x[0], x[0]) for x in dep['dp']) or 'no defenders yet'} -- fed at "
                        f"{a.feed_at:.0%} motivation or less ({a.feed_hot:.0%} while a gym is under attack)" + ("" if fd.get("live") else "  [!! feeder not available]"))
            except Exception as e:
                say(f"  could not read your bag live ({e})")
    refresh_deployed(True)

    ROUTE = [tuple(float(v) for v in w.split(",")) for w in a.route.split(";")] if a.route else []
    route_i = [0 if a.start_lap_at is None else a.start_lap_at]
    lap = {"active": bool(ROUTE) and (not a.battle or a.start_lap_at is not None), "placed": 0}   # the user's cycle: N gyms, a lap, repeat
    if ROUTE:
        say(f"  route of {len(ROUTE)} waypoints, {sum(ch.meters(x, y) for x, y in zip(ROUTE, ROUTE[1:])) / 1000:.1f} km, at {a.speed} km/h")

    def retry_lockout(fid):                                  # refused for the finisher's deploy window: wait it out, place again
        lv = sc.exports_sync.teams().get(fid) or []
        wait = min(30.0, (lv[8] / 1000.0 if len(lv) > 8 and lv[8] else 5.0) + 0.3)
        say(f"  deploy lockout (the finisher's window) -- trying again in {wait:.1f} s")
        g.wait_for(lambda: False, wait, tick)
        if not (g.open_fid == fid and g.gym_team == 0 and g.leaf() == "GymApproachState"):
            return False
        g.deploy_refused, g.autoplaced_id = None, None
        g.placed.pop(fid, None)
        sc.exports_sync.autodeploy(fid, [x[0] for x in dep["gy"][:12]], False, a.team)
        if not g.wait_for(lambda: fid in g.placed and g.autoplaced_id and g.placed[fid].get("id") == g.autoplaced_id, 20, tick):
            return False
        return bool(g.placed[fid].get("ok"))

    def batch_check():                                       # the user's rule: no heals until 30 fainted, then ALL of them at once
        n, ids = g.fainted
        dep["nfa"] = n
        if a.heal_batch and n >= a.heal_batch and dep["ro"] and not g.batch_active:
            g.batch_active = True
            sc.exports_sync.roster([x[0] for x in dep["ro"]], a.heal_top, ids, [x[0] for x in dep["gy"]])
            STATS["batches"] = STATS.get("batches", 0) + 1
            say(f"  {n} fainted (batch at {a.heal_batch}) -- reviving ALL of them now, one Max Revive each")
    if g.has("GymState") and not a.adopt:                    # open at start = the previous runner's gym: leave it after this battle
        g.wait_for(lambda: g.open_fid is not None, 3)
        g.user_gym = False
    if g.has("GymState") and a.adopt:                        # attached mid-gym (restart / re-attach): adopt THAT gym
        g.wait_for(lambda: g.open_fid is not None, 8)
        lv = sc.exports_sync.teams().get(g.open_fid) if g.open_fid else None
        g.user_gym = False                                   # this one is ours (adopted), not the user's
        if lv and lv[0] in enemy + [0]:
            target = (g.open_fid, (lv[2], lv[3]), lv[0])
            say(f"already at {g.open_fid[:8]} (team {lv[0]}{', in battle' if g.in_battle() else ''}) -- carrying on with it")
    last_tick = [0.0]
    scan_at, scan_said, scan_logged, scan_seen = [0.0], {}, {}, {}
    first_done = [not a.join_first]                          # --join-first: the user sent us back to one gym
    cmd_st = {"mtime": os.path.getmtime(a.cmd) if a.cmd and os.path.exists(a.cmd) else 0, "hunt": None}   # (old commands are not replayed)
    inbox = os.path.join(os.path.dirname(a.cmd), "runner_inbox") if a.cmd else None   # one FILE per command: a queue, never overwritten
    cmdq = []                                                # commands in arrival order (the single file lost a stop under the buddy polls)
    if inbox:
        os.makedirs(inbox, exist_ok=True)
        for _n in sorted(os.listdir(inbox)):                 # a stop meant for the LAST runner, or anything > 5 min old, is not replayed
            _p = os.path.join(inbox, _n)
            try:
                if _n.endswith(".json") and (time.time() - os.path.getmtime(_p) > 300 or json.load(open(_p, encoding="utf-8")).get("stop")):
                    os.remove(_p)
                    say(f"  (a stale command {_n} discarded at startup)")
            except Exception as _e:
                say(f"  (inbox file {_n}: {_e})")
    tscan_at, tpick_cp = [0.0], {}                           # the target's own re-scan / its CP when it was picked
    stop_req = [False]                                       # {"stop": true}: finish the battle, leave the gym, unload cleanly
    spin_st = {"fid": None, "said": 0.0, "tries": 0}          # {"spin": fid}: spin one fort's disc (a teammate session's buddy task)
    gpos_now = [None]

    def pull():                                              # new commands -> cmdq in arrival order; each file read ONCE, then removed
        if not a.cmd:
            return
        if os.path.exists(a.cmd) and os.path.getmtime(a.cmd) != cmd_st["mtime"]:   # the old single file (the buddy session, until it moves)
            cmd_st["mtime"] = os.path.getmtime(a.cmd)
            try:
                cmdq.append(json.load(open(a.cmd, encoding="utf-8")) or {})
            except Exception as _e:
                say(f"  !! command file unreadable ({_e}) -- that command is LOST (writers: one file per command in {inbox})")
        try:
            _ns = sorted(n for n in os.listdir(inbox) if n.endswith(".json") and not n.startswith("."))
        except OSError:
            return
        for _n in _ns:
            _p = os.path.join(inbox, _n)
            try:
                _c = json.load(open(_p, encoding="utf-8"))
            except Exception as _e:
                _c = None
                say(f"  !! command {_n} unreadable ({_e}) -- discarded")
            try:
                os.remove(_p)
            except OSError:
                pass
            if _c:
                cmdq.append(_c)

    def quick_cmds():                                        # buddy / topup commands: handled at once, even mid-drill
        pull()
        for _q in [c for c in cmdq if not set(c) - {"buddy", "topup"}]:
            cmdq.remove(_q)                                  # (go / hunt / stop / spin / lap stay queued: the main loop decides)
            if _q.get("buddy"):
                _r = None
                for _c in _q["buddy"]:
                    _r = sc.exports_sync.buddy(_c[0], _c[1] if len(_c) > 1 else None)
                say(f"  COMMAND buddy: {_q['buddy']} queued -- {_r}")
            if "topup" in _q:
                _tu = sc.exports_sync.topup(bool(_q["topup"]), a.topup_reserve)
                say(f"  COMMAND topup: {'ON' if _tu.get('on') else 'OFF'}")

    def urgent_cmd():                                        # a queued command that should end a drill
        pull()
        return g.graph_stale or any(set(c) & {"go", "hunt", "stop", "spin", "lap"} for c in cmdq)

    def tick():                                              # keep circling the current gym while waiting on it
        quick_cmds()
        feed_record()
        if gpos_now[0] and time.time() - last_tick[0] > 2:
            last_tick[0] = time.time()
            q = ch.fix()
            if q:
                mv.orbit(gpos_now[0], q[:2], r=orbit_r)
                sc.exports_sync.pos(q[0], q[1])

    while time.time() - t_start < a.minutes * 60:
        if g.detached:
            raise Detached("game connection lost")
        if g.prepstuck:
            say("STOP: a party screen stayed open over a battle -- not continuing (joystick keeps circling)")
            return
        p = ch.fix()
        if not p:
            time.sleep(1)
            continue
        here = p[:2]
        sc.exports_sync.pos(here[0], here[1])                # (the direct deploy sends the player's position)
        mv.fast = ch.meters(here, goal) > a.area                 # the far trip only: normal speed once inside the goal area
        if g.has("GymState") and g.user_gym:                 # the user opened a gym: never touch it, keep walking
            if said != "user-gym":
                say("  you have a gym open -- waiting for you to leave it (still moving)")
                said = "user-gym"
            if gpos_now[0] is None and target:
                mv.orbit(target[1], here, r=orbit_r)
            time.sleep(1)
            continue
        if g.has("GymState") and not g.in_battle() and not (target and g.open_fid == target[0]):   # never walk off with a gym screen open
            if not leave_gym(g, sc, tick):
                say(f"  could not leave the gym screen ({g.chain} / top {g.top}) -- retrying")
                time.sleep(2)
                continue
        live = sc.exports_sync.teams()
        if time.time() - scan_at[0] > 15:                    # verified park state: the map record of a far gym can be stale
            scan_at[0] = time.time()
            sc.exports_sync.scan([f for f, v in live.items() if ch.meters((v[2], v[3]), goal) <= a.area]
                                 + [f for f, v in live.items() if f[:8] not in NAMES and ch.meters((v[2], v[3]), here) <= 300][:6])
        if target and time.time() - tscan_at[0] > 5:         # the gym we are walking to: re-verified every 5 s
            tscan_at[0] = time.time()
            sc.exports_sync.scan([target[0]])
        verified = set()                                     # scan < 30 s old: its free slot is real
        for f, sv in sc.exports_sync.scanned().items():      # [team, age ms, in battle, defenders, CP now, ours, motivations, name]
            if len(sv) > 7 and sv[7]:
                NAMES[f[:8]] = sv[7]
            if f in live and sv[1] < 30000:
                verified.add(f)
            if f in live and sv[1] < 45000:
                v = live[f]
                if (v[0], 6 - sv[3]) != (sv[0], v[5]) and scan_said.get(f) != (sv[0], sv[3]):
                    scan_said[f] = (sv[0], sv[3])
                    say(f"    scan {f[:8]}: team {sv[0]}, {sv[3]} defender(s), {sv[4]} CP now{' (in battle)' if sv[2] else ''}"
                        f" -- the map had team {v[0]}, {6 - v[5] if v[5] >= 0 else '?'} defender(s)")
                v[0], v[5], v[6] = sv[0], 6 - sv[3], sv[2]
                if len(v) > 7:
                    v[7] = sv[4]
                if scan_seen.get(f) != round(time.time() * 1000 - sv[1], -3):   # a NEW scan of it: update its contest level
                    scan_seen[f] = round(time.time() * 1000 - sv[1], -3)
                    BUSY[f] = 0.9 * BUSY.get(f, 0.5) + 0.1 * sv[2]
                if g.study_f and scan_logged.get(f) != sv[1] // 15000:
                    scan_logged[f] = sv[1] // 15000
                    g.study_f.write(json.dumps({"k": "study", "src": "scan", "t": int(time.time() * 1000) - sv[1], "fid": f,
                                                "team": sv[0], "ib": sv[2], "n": sv[3], "cp": sv[4], "ours": sv[5], "mots": sv[6]}) + "\n")
        skip = {f for f, t in done.items() if time.time() - t < 600}
        mine = {x[5] for x in dep["dp"] if len(x) > 5}

        def slot(f, v):                                  # OUR team's gym with a free slot and none of ours: join it, no battle
            return (a.autoplace and v[0] == a.team and len(v) > 5 and v[5] > 0 and f not in mine
                    and not (len(v) > 9 and v[9] > 0)            # its same-team deploy lockout is running: it would refuse us
                    and (dep["n"] is None or dep["n"] < a.max_deployed))
        passing = None                                   # the avatar's reflex: a red gym in reach with room for him -> join it now
        if not g.in_battle() and not g.has("GymState"):
            near = sorted((ch.meters(here, (v[2], v[3])), f) for f, v in live.items()
                          if f not in skip and v[1] < 60000 and not v[4] and not (len(v) > 6 and v[6]) and slot(f, v)
                          and ch.meters(here, (v[2], v[3])) <= (150 if f in verified else engage))   # a VERIFIED slot: worth a short detour
            if near:
                pf = near[0][1]
                passing = (pf, (live[pf][2], live[pf][3]), live[pf][0])
                if not target or target[0] != pf:
                    say(f"passing {pf[:8]}: red, {live[pf][5]} free slot(s), {near[0][0]:.0f} m -- joining it on the way")
                target = passing
        feed_record()
        pull()
        while cmdq:                                          # live commands, in arrival order -- a queue, none is lost: no restart
            _cmd = cmdq.pop(0)
            if "lap" in _cmd and ROUTE:                      # {"lap": N}: a battle break -- walk the route from waypoint N now
                lap["active"], route_i[0], target = True, max(0, min(len(ROUTE) - 1, int(_cmd["lap"] or 0))), None
                say(f"  COMMAND lap: battle break -- walking the route from waypoint {route_i[0]}/{len(ROUTE)}, feeding continues; "
                    f"battling again after the lap")
            if _cmd.get("go"):
                _g = str(_cmd["go"])
                a.join_first = _g if _g in live else next((_f for _f in live if _f.startswith(_g)), None)
                first_done[0], target = not a.join_first, None
                say(f"  COMMAND go: {str(a.join_first)[:8] if a.join_first else _g + ' (not on the map)'}")
            if _cmd.get("buddy"):                         # [[what, arg], ...] from the buddy session: queued in the tapper, one at a time
                for _c in _cmd["buddy"]:
                    _r = sc.exports_sync.buddy(_c[0], _c[1] if len(_c) > 1 else None)
                say(f"  COMMAND buddy: {_cmd['buddy']} queued -- {_r}")
            if _cmd.get("spin"):
                _g = str(_cmd["spin"])
                _at = _cmd.get("at")                      # a PokeStop: its coordinates (stops are not in the gym list)
                spin_st.update(fid=_g if _g in live else next((_f for _f in live if _f.startswith(_g)), None) or (_g if _at else None),
                               said=0.0, tries=0, at=tuple(_at) if _at else None, linger=0.0)
                say(f"  COMMAND spin: {spin_st['fid'][:8] if spin_st['fid'] else _g + ' (not on the map)'}")
            if _cmd.get("stop"):
                stop_req[0] = True
                say("  COMMAND stop: finishing any battle in progress, leaving the gym, then unloading from the game cleanly")
            if "topup" in _cmd:
                _tu = sc.exports_sync.topup(bool(_cmd["topup"]), a.topup_reserve)
                say(f"  COMMAND topup: {'ON' if _tu.get('on') else 'OFF'} (keeping {a.topup_reserve} of each; bag {_tu.get('berries')})")
            if _cmd.get("hunt"):
                _hr = float(_cmd["hunt"])
                _near = sorted((ch.meters(here, (_v[2], _v[3])), _f) for _f, _v in live.items() if not _v[4])
                _near = [_f for _d, _f in _near if _d <= _hr][:16]
                sc.exports_sync.scan(_near)
                cmd_st["hunt"] = (time.time() + 5, _hr, bool(_cmd.get("drill")))   # drill: enemy gyms only (the user: 'drill it')
                say(f"  COMMAND hunt: verifying {len(_near)} gym(s) within {_hr:.0f} m with the game's own gym details")
        if spin_st["fid"] and not g.in_battle() and not g.prep:   # spin one fort's photo disc, then carry on
            _sf = spin_st["fid"]
            _sv = live.get(_sf)
            if not _sv and spin_st.get("at"):              # a PokeStop: walk right next to it and linger; the auto-catcher spins it
                _sp = spin_st["at"]
                if ch.meters(here, _sp) > 12:
                    if g.has("GymState"):
                        leave_gym(g, sc, tick)
                    gpos_now[0] = None
                    mv.orbit(_sp, here, r=6)
                    if time.time() - spin_st["said"] > 30:
                        spin_st["said"] = time.time()
                        say(f"  SPIN stop {_sf[:8]}: walking to it ({ch.meters(here, _sp):.0f} m)")
                    time.sleep(1)
                    continue
                spin_st["linger"] = spin_st["linger"] or time.time()
                mv.orbit(_sp, here, r=6)
                if time.time() - spin_st["linger"] < 45:
                    time.sleep(1)
                    continue
                say(f"  SPIN stop {_sf[:8]}: stood within 12 m for 45 s (the auto-catcher spins stops in range) -- back to what I was doing")
                spin_st["fid"] = None
                continue
            if not _sv or (len(_sv) > 10 and _sv[10]) or spin_st["tries"] >= 3:
                say(f"  SPIN {_sf[:8]}: " + ("not on the map any more" if not _sv else "DONE -- its Visited flag is set" if _sv[10]
                                              else "3 tries without the Visited flag -- giving up") + "; back to what I was doing")
                spin_st["fid"] = None
            elif ch.meters(here, (_sv[2], _sv[3])) > 35:  # walk to it (a gym disc needs the avatar within range)
                if g.has("GymState"):
                    leave_gym(g, sc, tick)
                gpos_now[0] = None
                mv.orbit((_sv[2], _sv[3]), here, r=15)
                if time.time() - spin_st["said"] > 30:
                    spin_st["said"] = time.time()
                    say(f"  SPIN {_sf[:8]}: walking to it ({ch.meters(here, (_sv[2], _sv[3])):.0f} m)")
                time.sleep(1)
                continue
            else:                                         # open it, its own disc button, a finger's swipe across the disc
                spin_st["tries"] += 1
                if not (g.has("GymState") and g.open_fid == _sf):
                    sc.exports_sync.open(_sf)
                if g.wait_for(lambda: g.open_fid == _sf and g.leaf() == "GymApproachState", 12, tick):
                    time.sleep(1.2)
                    sc.exports_sync.act("pokestop")
                    time.sleep(2.5)
                    try:
                        _png = subprocess.run(["adb", "-s", os.environ.get("ADB_TARGET", ch.DEV), "exec-out", "screencap", "-p"],
                                              capture_output=True, timeout=20).stdout   # the phone, by name (a TV / the cloud bridge share adb)
                        open(os.path.join(os.path.dirname(a.study) if a.study else ".", f"spin_{_sf[:8]}_{spin_st['tries']}.png"), "wb").write(_png)
                    except Exception:
                        pass
                    ch.adb("input swipe 200 1430 1080 1430 150")
                    time.sleep(3.0)
                    say(f"  SPIN {_sf[:8]}: disc button pressed + swiped (try {spin_st['tries']}); checking its Visited flag")
                else:
                    say(f"  SPIN {_sf[:8]}: the gym did not open (top '{g.top}') -- try {spin_st['tries']}/3")
                leave_gym(g, sc, tick)
                continue
        if g.graph_stale:                                    # a frozen service graph: a clean stop (a restart re-picks it)
            stop_req[0] = True
        if stop_req[0] and not g.in_battle() and not g.prep:   # a CLEAN stop: never a hard kill mid-battle (03:39 deadlock)
            if g.has("GymState"):
                leave_gym(g, sc, tick)
            say("  stopped cleanly -- the tapper unloads and the session detaches now; a new runner can attach")
            return
        if cmd_st["hunt"] and time.time() >= cmd_st["hunt"][0]:   # the hunt: the cheapest VERIFIED gym in range, now
            _hr, _drill, cmd_st["hunt"], _best = cmd_st["hunt"][1], cmd_st["hunt"][2], None, None
            for _f, _s in sc.exports_sync.scanned().items():  # [team, age ms, in battle, defenders, CP now, ours, motivations]
                _v = live.get(_f)
                if not _v or _s[1] > 20000 or _v[4] or ch.meters(here, (_v[2], _v[3])) > _hr:
                    continue
                _dm = ch.meters(here, (_v[2], _v[3]))
                if _s[0] in enemy:
                    _c = _dm * 0.35 + _s[4] * 0.03
                elif not _drill and (_s[0] == 0 or (_s[0] == a.team and slot(_f, _v))):   # the SAME placement test the go-to uses
                    _c = _dm * 0.35 - 60
                else:
                    continue
                if _best is None or _c < _best[0]:
                    _best = (_c, _f, _s, _dm)
            if _best:
                a.join_first, first_done[0], target = _best[1], False, None
                _s = _best[2]
                say(f"  HUNT: {_best[1][:8]} -- team {_s[0]}, {_s[3]} defender(s), {_s[4]} CP now, motivations {_s[6]}, {_best[3]:.0f} m -- going")
            else:
                say("  HUNT: nothing beatable or joinable in range right now")
        if not first_done[0] and not g.in_battle() and (not g.has("GymState") or g.open_fid == a.join_first):   # go there first
            _jv = live.get(a.join_first)
            if _jv and not _jv[4] and (_jv[0] in enemy + [0] or slot(a.join_first, _jv)):   # beat + place, or join
                if not target or target[0] != a.join_first:
                    _what = "join it" if _jv[0] == a.team else f"drill it (team {_jv[0]}, {_jv[7] if len(_jv) > 7 else '?'} CP) and place"
                    say(f"going to {a.join_first[:8]} ({ch.meters(here, (_jv[2], _jv[3])):.0f} m) to {_what} -- then back to the lap")
                passing = target = (a.join_first, (_jv[2], _jv[3]), _jv[0])
            elif _jv is not None:
                first_done[0] = True
                say(f"  {a.join_first[:8]} is team {_jv[0]} now{' (raid)' if _jv[4] else ''} -- nothing to do there; back to the lap")
        if (not a.battle or lap["active"]) and not passing:   # battle break / a lap: keep moving, keep feeding, fight nothing
            if g.in_battle() or g.has("GymState"):
                time.sleep(0.5)                              # (the session in progress finishes; its gym screen is left above)
                continue
            gpos_now[0] = None
            if route_i[0] < len(ROUTE):                      # a one-way route: always toward the NEXT waypoint, never back
                if ch.meters(here, ROUTE[route_i[0]]) < 20:
                    route_i[0] += 1
                    say(f"  route: waypoint {route_i[0]}/{len(ROUTE)} reached" + (" -- lap done" if route_i[0] >= len(ROUTE) else ""))
                    if route_i[0] >= len(ROUTE) and a.battle:  # the lap is over: back to the gyms
                        lap["active"], lap["placed"] = False, 0
                        say(f"  LAP DONE -- battling again (next lap after {a.lap_every} more placements)")
                        continue
                if route_i[0] < len(ROUTE):
                    key = ("route", route_i[0])
                    if mv.key != key or mv.due(here):
                        mv._walk(key, ROUTE[route_i[0]:], here)
                    time.sleep(1)
                    continue
            mv.orbit(goal, here, r=60)
            refresh_deployed()                               # (every 10 min: the defender list for the feeder)
            if said != "break":
                say("  BATTLE BREAK -- walking in the park, still feeding your defenders + one teammate per gym")
                said = "break"
            time.sleep(2)
            continue
        tv = live.get(target[0]) if target else None
        if target is None or target[0] in skip or not tv or tv[4] or not (tv[0] in enemy + [0] or slot(target[0], tv)):
            target = pick(enemy + [0], skip, here, goal, live, a.detour, a.area, slot)   # an empty gym: straight to Deploy
            if target:
                say(f"target {target[0][:8]} team {target[2]}, {ch.meters(here, target[1]):.0f} m away")
        if not target:                                       # nothing to beat right now: keep moving
            gpos_now[0] = None
            refresh_deployed()                               # (only every 15 min; the walk keeps going meanwhile)
            if ch.meters(here, goal) > a.area:
                mv.travel(goal, here)
                msg = "no enemy gym on the way yet -- walking toward the goal"
            else:
                soon = [(v[4], fid, (v[2], v[3])) for fid, v in live.items()          # a non-red gym whose raid ends soon:
                        if v[0] in enemy + [0] and 0 < v[4] <= a.prewait * 60000        # wait ON it, battle the second it ends
                        and ch.meters((v[2], v[3]), goal) <= a.area and fid not in skip]
                if soon:
                    left, sfid, spos = min(soon)
                    gpos_now[0] = None
                    mv.orbit(spos, here, r=orbit_r)
                    msg = f"in the goal area, nothing to beat now -- circling {sfid[:8]}, its raid ends in {left / 60000:.1f} min"
                else:
                    ring = sorted([(v[2], v[3]) for v in live.values() if ch.meters((v[2], v[3]), goal) <= a.area],
                                  key=lambda q: math.atan2((q[1] - goal[1]) * math.cos(math.radians(goal[0])), q[0] - goal[0]))
                    if len(ring) >= 3:
                        mv.loop(ring, here)
                    else:
                        mv.orbit(goal, here, r=60)
                    msg = "in the goal area, nothing to beat (raids or red) -- looping its gyms"
            if msg != said:
                say(msg)
                said = msg
            time.sleep(2)
            continue
        fid, gpos, team = target
        _ts = sc.exports_sync.scanned().get(fid)
        if _ts and _ts[1] < 8000:
            _pcp = tpick_cp.setdefault(fid, _ts[4])
            if _ts[0] in enemy and _ts[4] > max(_pcp * 1.5, _pcp + 3000) and ch.meters(here, gpos) > engage:
                say(f"  target {fid[:8]} grew from {_pcp} to {_ts[4]} CP ({_ts[3]} defenders) while we walked -- re-picking")
                tpick_cp.pop(fid, None)
                if _pcp > 0:                                 # it really got stronger: skipped 10 min
                    done[fid] = time.time()                  # (an EMPTY gym that just filled is re-judged at once -- often a small gym)
                if a.join_first == fid:
                    first_done[0] = True
                gpos_now[0], target, said = None, None, None
                continue
        d = ch.meters(here, gpos)
        if d > engage:                                       # on the way: walk to it
            gpos_now[0] = None
            mv.travel(gpos, here)
            said = None
            time.sleep(2)
            continue
        gpos_now[0] = gpos
        mv.orbit(gpos, here, r=orbit_r)                      # in range: keep circling it the whole time
        say(f"engaging {fid[:8]} (team {team}) at {d:.0f} m")
        gym_t0 = time.time()
        g.deploy_open = None
        g.placed.pop(fid, None)
        friendly = team == a.team
        g.armed = False
        if dep["n"] is None or dep["n"] < a.max_deployed:   # arm: the instant it reports empty, place (or open Deploy)
            r_ad = sc.exports_sync.autodeploy(fid, [x[0] for x in dep["gy"][:12]] if a.autoplace else [], friendly, a.team)
            g.armed = bool(r_ad.get("armed"))
            if not r_ad.get("auto") and a.autoplace:
                say("  (auto-place unavailable -- Deploy will open the list for you)")
        if friendly:                                         # a red gym with a free slot: open it, the phone places at once
            say("  your team's gym with a free slot -- joining it (no battle)")
            sc.exports_sync.open(fid)
            final = 0 if g.wait_for(lambda: g.open_fid == fid and g.leaf() == "GymApproachState", 10, tick) else None
        else:
            def join_near(cur):                          # a red gym with room within open range of where we stand
                q = ch.fix()
                if not q:
                    return None
                lvv = sc.exports_sync.teams()
                near = sorted((ch.meters(q[:2], (v[2], v[3])), f) for f, v in lvv.items()
                              if f != cur and f not in skip and v[1] < 60000 and not v[4] and not (len(v) > 6 and v[6])
                              and slot(f, v) and ch.meters(q[:2], (v[2], v[3])) <= engage)
                return near[0][1] if near else None
            final = drill(fid, enemy, g, sc, a, tick, time.time() + a.gym_minutes * 60, refresh=batch_check, join_near=join_near,
                          cmd_waiting=urgent_cmd)
        if final in (STALL, DETOUR):                         # left mid-drill on purpose: no placement step here
            g.autoplaced = None
            if final == STALL:
                done[fid] = time.time()                      # skipped for 10 min, then tried again
            gpos_now[0], target, said = None, None, None
            continue
        if final == ABORT:
            say("STOP: a party screen stayed open over a battle -- not continuing (joystick keeps circling)")
            return
        done[fid] = time.time()
        if a.join_first and fid == a.join_first:
            first_done[0] = True
        say(f"  gym {fid[:8]} now team {final}" if final is not None else f"  gave up on {fid[:8]}")
        if final == a.team and not friendly and g.armed:
            lv = sc.exports_sync.teams().get(fid)
            if lv and slot(fid, lv):
                say(f"  a red player got in first -- {lv[5]} slot(s) still free: joining it")
                friendly, final = True, 0
                if not (g.open_fid == fid and g.leaf() == "GymApproachState"):
                    sc.exports_sync.open(fid)
                    g.wait_for(lambda: g.open_fid == fid and g.leaf() == "GymApproachState", 10, tick)
        placed_ok = False
        if final == 0:                                       # empty: you can leave a Pokemon (unless at the cap)
            n = dep["n"]
            placed_ok = False
            if n is not None and n >= a.max_deployed:
                say(f"  EMPTY -- you already have {n} Pokemon in gyms (cap {a.max_deployed}): moving on")
            else:
                if g.deploy_open != fid and not g.wait_for(lambda: g.deploy_open == fid, 3, tick):
                    sc.exports_sync.autodeploy(None)         # disarm FIRST: never a Deploy list over a late auto-place
                    g.wait_for(lambda: g.deploy_open == fid, 0.5, tick)
                    if g.autoplaced != fid and friendly:
                        say("  could not join it (no candidate at full HP, or the slot is gone) -- moving on")
                    elif g.autoplaced != fid:
                        say("  auto-place did not fire in 3 s -- opening Deploy for you")
                        sc.exports_sync.act("deploy")        # fallback: the phone-side action did not fire
                if g.autoplaced == fid:                      # our deploy request went out: its own Pokemon confirms it
                    ok_now = lambda: fid in g.placed and g.placed[fid].get("id") == g.autoplaced_id
                    if g.wait_for(ok_now, 17, tick) and g.placed[fid].get("ok"):
                        placed_ok = True
                        dep["n"] = (n or 0) + 1
                        STATS["placed"] += 1
                        say(f"  you placed {g.names.get(g.placed[fid]['id'], 'a Pokemon') if hasattr(g, 'names') else 'a Pokemon'} "
                            f"({dep['n']}/{a.max_deployed} in gyms now) -- next gym")
                    elif g.deploy_refused and "Lockout" in g.deploy_refused[1] and not friendly and retry_lockout(fid):
                        placed_ok = True
                        dep["n"] = (n or 0) + 1
                        STATS["placed"] += 1
                        say(f"  you placed {g.names.get(g.placed[fid]['id'], 'a Pokemon') if hasattr(g, 'names') else 'a Pokemon'} "
                            f"right after the lockout ({dep['n']}/{a.max_deployed} in gyms now) -- next gym")
                    elif friendly:
                        why = (g.placed.get(fid) or {}).get("res", "no answer")
                        say(f"  the red gym did not take it ({why}) -- moving on")
                    elif g.leaf() == "GymApproachState" and (g.open_fid != fid or g.gym_team in (0, None)):
                        say("  auto-place did not land -- opening Deploy for you")
                        sc.exports_sync.act("deploy")
                if not placed_ok and not friendly:
                    say(f"  EMPTY -- {n if n is not None else '?'}/{a.max_deployed} in gyms: Deploy is open, leave a Pokemon "
                        f"(circling the gym, up to {a.place_wait:.0f} s)")
                t0 = time.time()
                while not placed_ok and not friendly and time.time() - t0 < a.place_wait:
                    tick()
                    lv = sc.exports_sync.teams().get(fid)
                    now_team = lv[0] if lv else None
                    if now_team not in (0, None):
                        if now_team == 2:                    # red -- but was it YOU? only your live deployed count says
                            try:
                                n2 = deployed_count(sess, sc)
                            except Exception:
                                n2 = None
                            if n2 is not None:
                                dep["n"], dep["at"] = n2, time.time()
                            if n is not None and n2 is not None and n2 > n:
                                placed_ok = True             # (manual / fallback placement: counted, and the bag refresh after this gym registers it)
                                STATS["placed"] += 1
                                say(f"  you placed a Pokemon ({n2}/{a.max_deployed} in gyms now) -- next gym")
                            else:
                                say(f"  another red player filled it first (your gym count is still {n2 if n2 is not None else '?'}) -- moving on")
                        else:
                            say(f"  team {now_team} took it first -- moving on")
                        break
                    time.sleep(1)
                else:
                    if not placed_ok and not friendly:
                        say("  no placement seen -- moving on")
        sc.exports_sync.autodeploy(None)                     # disarm only now: the whole placement step is over
        g.autoplaced = None
        if g.deploy_refused and g.deploy_refused[0] == fid and re.search(r"SameKind|AlreadyHas|Disabled", g.deploy_refused[1]):
            done[fid] = time.time() + 3000                   # it cannot take a Gyarados now: skip it for about an hour
            say(f"  skipping {fid[:8]} for an hour ({g.deploy_refused[1]})")
        g.deploy_refused = None
        if final == 0 and friendly:
            if placed_ok:
                STATS["joins"] = STATS.get("joins", 0) + 1
        elif final == 0:
            STATS["emptied"] += 1
            STATS["gym_s"].append(time.time() - gym_t0)
        refresh_deployed(True)                               # fainted count, hold count, feeder watch list: the live bag
        say(stats_line(dep, a))
        if placed_ok and not lap["active"]:                  # (a join on the lap is a bonus: it never restarts the lap)
            lap["placed"] += 1
            if a.lap_every and ROUTE and lap["placed"] >= a.lap_every:   # the user's cycle: every N placements, a lap
                lap["active"], route_i[0] = True, 0
                say(f"  {lap['placed']} gyms taken and placed -- LAP TIME ({len(ROUTE)} waypoints), feeding continues")
        leave_gym(g, sc, tick)
        gpos_now[0], target, said = None, None, None


if __name__ == "__main__":
    main()
