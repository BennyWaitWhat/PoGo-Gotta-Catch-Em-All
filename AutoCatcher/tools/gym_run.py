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
import threading
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
OBO_OK_TAP = "input tap 640 1432"                # one-by-one: OK on "Are you sure you want to give up?" (1280x2856 screen, 11-17 00:00)


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
    st = cfg.get("species_typed") or []
    if st:                                                   # 2026-09-30 (review of #27): say which forms run on their species' typing
        say(f"  STAB: {len(st)} form(s) the game master does not list use their species' typing (a bonus for a type the form adds is "
            f"missed): {', '.join(st[:12])}{' ...' if len(st) > 12 else ''}")


DD = {"off": None, "try_at": 0.0, "armed_at": 0.0, "gone_at": 0.0, "on_done": False,   # direct deploy (the place request sent from
      "path": os.path.join(os.path.dirname(os.path.abspath(__file__)), "gym_state", "direct_deploy_off.json")}   # the map): its crash guard


def dd_state(mode):
    """May the tapper use direct deploy on this attach? mode = --direct-deploy: 'off' never; 'on' = try again (forgets an
    earlier crash-guard verdict, once per run); 'auto' = yes unless the crash guard turned it off -- in this run, or in an
    earlier one (direct_deploy_off.json). Returns (allowed, why not)."""
    if mode == "off":
        return False, "--direct-deploy is off, the default: it waits for Benny's go (a request kind from before the 09-26 lockout)"
    if mode == "on" and not DD["on_done"]:
        DD["on_done"] = True                                 # (a verdict of THIS run still holds after that)
        try:
            os.remove(DD["path"])
        except OSError:
            pass
    if DD["off"]:
        return False, DD["off"]
    try:
        with open(DD["path"], encoding="utf-8") as f:
            rec = json.load(f)
        return False, f"{rec.get('why')} ({rec.get('at')}) -- '--direct-deploy on' tries it again"
    except Exception:
        return True, None


def dd_guard(now=None):
    """The game connection dropped. Direct deploy calls into the game through reflection (gym_tapper ddResolve / directDeploy)
    and had never run on the phone when this was written (11-17), and Benny's rule is that the game is never restarted. So
    the tapper announces each step BEFORE it makes it ('ddtry', 'ddarmed'), and a connection that drops within seconds of
    an unanswered announcement makes that step the suspect: direct deploy stays OFF -- for this run and for later runs
    (direct_deploy_off.json) -- until '--direct-deploy on' asks for another try. At most ONE game exit can ever be its
    doing. Returns the reason, or None (not a suspect)."""
    now = now or DD["gone_at"] or time.time()
    why = None
    if DD["try_at"] and 0 <= now - DD["try_at"] < 6:
        why = "the game closed while the direct deploy's request sender was being built"
    elif DD["armed_at"] and 0 <= now - DD["armed_at"] < 12:
        why = "the game closed right after a direct deploy was armed"
    DD["try_at"] = DD["armed_at"] = DD["gone_at"] = 0.0
    if why and not DD["off"]:
        DD["off"] = why
        try:
            with open(DD["path"], "w", encoding="utf-8") as f:
                json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "why": why}, f)
        except Exception:
            pass
    return why


def gym_report(r, placed_ok, obo, now, path=None):
    """One line per finished gym from its stopwatch r (Game.rep_new): arrival -> first battle; battles, rounds won (each
    takes a third of a defender's motivation) and the seconds per round; battles that won nothing; refused battles
    (error 29); win -> your Pokemon in. The same numbers go to gym_reports.jsonl, one row per gym."""
    won = r.get("won", 0)
    end = r["placed"] or now
    row = {"fid": r["fid"], "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["t0"])), "total_s": round(end - r["t0"], 1),
           "first_battle_s": round(r["first"] - r["t0"], 1) if r["first"] else None, "battles": r["battles"], "rounds_won": won,
           "battles_won_nothing": r.get("empty", 0), "giveups": r["giveups"], "knocked_out_mid_battle": r["stays"],
           "refused": r["e29"], "placed": bool(placed_ok), "one_by_one": bool(obo),
           "fight_s": round((r["victory"] or now) - r["first"], 1) if r["first"] else None,
           "win_to_placed_s": round(r["placed"] - r["victory"], 1) if (r["placed"] and r["victory"] and r["placed"] >= r["victory"]) else None}
    row["per_round_s"] = round(row["fight_s"] / won, 1) if (won and row["fight_s"]) else None
    bits = []
    if row["first_battle_s"] is not None:
        bits.append(f"arrival -> first battle {row['first_battle_s']:.0f} s")
        bits.append(f"{row['battles']} battles, {won} rounds won in {row['fight_s']:.0f} s"
                    + (f" ({row['per_round_s']:.0f} s per round)" if row["per_round_s"] else ""))
        if row["battles_won_nothing"]:
            bits.append(f"{row['battles_won_nothing']} battle(s) won nothing" + (" <-- look here" if row["battles_won_nothing"] >= 2 else ""))
        bits.append(f"{row['refused']} refused (error 29)" + (" <-- look here" if row["refused"] >= 2 else ""))
    if row["win_to_placed_s"] is not None:
        bits.append(f"win -> your Pokemon in {row['win_to_placed_s']:.1f} s" + (" <-- slow" if row["win_to_placed_s"] > 3 else ""))
    elif r["victory"] and not placed_ok:
        bits.append("won, but NOT placed <-- look here")
    bits.append(f"{row['total_s']:.0f} s in all" + ("" if placed_ok else ", nothing placed"))
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception:
            pass
    return f"  GYM REPORT {r['fid'][:8]}{' (' + NAMES[r['fid'][:8]] + ')' if r['fid'][:8] in NAMES else ''}: " + " | ".join(bits)


def map_top(t):
    """The top screen is the plain map (toasts -- catch rewards, notices -- may sit over it)."""
    return t is not None and (t in ("MainMenuGuiController", "", "NotificationGuiController") or "Toast" in t)   # (the banner too:
                                                             # it held the re-open after every gym win for 4-5 s, 11-17)


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
        self.his_gym = None                                  # (fid, when, why): the gym YOUR own deploy was refused at -- ours to get

    def on_msg(self, m, _d):
        if m.get("type") != "send":
            say(f"JS {m}")
            return
        p, k = m["payload"], m["payload"]["k"]
        if k in ("start", "end", "pressed", "says", "outcome", "deployresult"):
            self.rep_ev(k, p)                                # the per-gym stopwatch
        if k == "deployresult":
            DD["armed_at"] = 0.0                             # the server's answer was read: an armed direct deploy is settled
        if k == "state":
            self.progress_at = time.time()                   # any state change = the battle is moving
            entering = "GymState" in p["chain"].split(" > ") and not self.has("GymState")
            if "GymState" not in p["chain"].split(" > ") and self.has("GymState") and self.user_gym:
                self.user_left_at = time.time()              # you closed YOUR gym (recorded for the log; no timer hangs on it)
            if entering:                                     # a gym screen we did not open in the last 15 s is the user's --
                self.user_gym = time.time() - self.opened_at > 15   # and ONE open of ours covers ONE gym screen (11-16 22:53: Benny
                self.opened_at = 0.0                         # re-opened the gym we had left 14 s before; we pressed Back on him)
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
            self.start_at = time.time()                      # (an error 29 older than this is history: e29_seen)
            say(f"    round start{' ' + str(p['n']) if p.get('n') else ''}")
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
        elif k == "ddtry":                                   # said 0.4 s BEFORE the tapper's reflection calls (dd_guard reads it)
            DD["try_at"] = time.time()
        elif k == "ddarmed":                                 # a victory armed a direct deploy: the request goes out when the gym reads EMPTY
            DD["armed_at"] = time.time()
        elif k == "ddsend":                                  # the direct deploy's request sender, built by the game's own reflection
            DD["try_at"] = 0.0                               # (answered: the build did not take the game down)
            say(f"  direct deploy {'READY' if p.get('ok') else 'NOT available'}: {p.get('why')}"
                + ("" if p.get("ok") else f" | Send overloads seen: {p.get('sigs')}"))
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
            self.last_team = list(p.get("ids") or [])        # the six that fight this session (the session record reads it)
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
                if p.get("berry") and p["berry"] != "GoldenRazzBerry":
                    say(f"    NO GOLDEN RAZZ -> fed a {p['berry']} to {nm} at {fid} (motivation was {p['mot']:.0%}, CP {p['cp']})"
                        f"{'' if p['ok'] else ' -- the call threw'}; {p['left']} {p['berry']} left (bag: {p.get('berries')})")
                else:
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
                say(f"    !! {nm} at {fid} is at {p['mot']:.0%} motivation but you have NO Golden Razz and no Razz/Nanab/Pinap berry left (bag: {p.get('berries')})")
            else:
                say(f"    feeder: {p}")
        elif k == "pickcall":                                # a place-handler candidate ran (learning which one places)
            say(f"    the game called {p['name']} (a place-handler candidate)")
        elif k == "picklearned":                             # a placement went through right after that candidate: it IS the handler
            if p.get("name") == p.get("was"):
                say(f"  auto-place handler {p['name']} CONFIRMED by a real placement")
            else:
                say(f"  auto-place handler LEARNED from a real placement: {p['name']} (was {p.get('was')}) -- auto-place uses it now")
            try:
                if getattr(self, "pick_file", None):
                    json.dump({"name": p["name"], "at": time.strftime("%Y-%m-%d %H:%M:%S")}, open(self.pick_file, "w", encoding="utf-8"))
            except Exception as _e:
                say(f"    (could not save the learned handler: {_e})")
        elif k == "deployresult":
            say(f"    deploy result: {p['res']}")
            if p.get("ok"):                                  # the game's own reply: a Pokemon of yours went in (by hand or auto-place)
                self.deploy_ok_at = time.time()
                if self.his_gym and self.his_gym[0] == self.open_fid:
                    self.his_gym = None
            elif self.user_gym and self.open_fid and not self.autoplaced:   # YOUR deploy was refused (11-17 00:27, Benny: "try putting
                self.his_gym = (self.open_fid, time.time(), str(p.get("res")))   # a gyarados into the gym im at"): that gym is ours to get
                say(f"    your deploy into {self.open_fid[:8]} was refused ({p.get('res')}) -- the runner takes it over for you: it stands "
                    f"at that gym, joins the moment the server lets red in, and fights for it if it falls")
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
            if p.get("gui") == "GlobalErrorController" and "(29)" in str(p.get("text")):
                self.err29_at = time.time()                  # "The Gym battle has already been completed! (29)": the game died 3-5 s
                                                             # after a re-open + Battle right behind it, twice on 11-16 (22:03, 22:37)
        elif k == "mdopen":                                  # a ModalDialog is fully Open (the game's own GUI state)
            _ran = getattr(self, "obo_ran", 0.0)
            if time.time() - _ran < 8 and getattr(self, "obo_ok", 0.0) < _ran:   # OUR one-by-one run-away's give-up prompt:
                self.obo_ok = self.obo_last_tap = time.time()   # OK with ONE tap, once it is Open (11-17 00:00: 30 run-aways
                self.obo_taps = 1                            # piled up the prompt; a tap while it was opening missed)
                threading.Thread(target=ch.adb, args=(OBO_OK_TAP,), daemon=True).start()
                say(f"    one-by-one: OK on the give-up prompt (tap 1, {p.get('ms')} ms after it appeared)")
        elif k == "sbmethods":
            say(f"    (run-away button methods: {p.get('m') or p.get('err')})")
        elif k == "mdfields":
            say(f"    (give-up prompt OK button, for a native press: {p.get('pbN')} x {p.get('pbCls')} {p.get('pb')} | "
                f"container {p.get('bc')} | {p.get('err')})")
        elif k == "items":
            self.items = dict(p["c"])
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
            if k == "pressed" and str(p.get("what", "")).startswith("RunAway (one-by-one"):
                self.obo_ran, self.obo_retry = time.time(), False
            if k != "pressed" or p.get("what") not in ("GO",):
                say(f"    [{k}] {dict((a, b) for a, b in p.items() if a != 'k')}")
        elif k != "go":                                      # (go = the GO press, already logged as [pressed])
            say(f"    !! unhandled message from the game script: {p}")   # (the user: 'not catching msgs' -- none is dropped silently)

    def rep_new(self, fid):
        """A stopwatch per gym (Benny 11-17 00:55: "i expect you to improve after each gym and battle. pay attention"): where
        the seconds went, in one line at the end of every gym and one row in gym_state/gym_reports.jsonl."""
        self.rep = {"fid": fid, "t0": time.time(), "first": None, "starts": 0, "giveups": 0, "stays": 0, "battles": 0, "e29": 0,
                    "victory": None, "placed": None, "won": 0, "empty": 0, "cur": [0, 0, False]}

    def rep_ev(self, k, p):
        """One tapper message into the stopwatch. Rounds WON are counted per battle: in the 0.435 flow every battle that does
        not end in a victory shows one more 'round start' than it fought -- the pass through the battle state on the way out
        (64 battles of 11-17 00:15-00:59: 3 starts + 1 give-up = 1 round won; 2 starts, no give-up, one defender left = 1
        won; 1 start + VICTORY = 1 won; 1 start and nothing else = a refused battle, 0 won). So per battle:
        won = round starts - give-ups - (0 after a victory, else 1)."""
        r = getattr(self, "rep", None)
        if not r:
            return
        now, what, cur = time.time(), str(p.get("what", "")), r["cur"]
        if k == "start":
            r["starts"] += 1
            cur[0] += 1
            r["first"] = r["first"] or now
        elif k == "pressed" and what == "Battle":
            r["battles"] += 1
        elif k == "pressed" and what.startswith(("Give up now", "RunAway")) and p.get("ok") is not False:
            r["giveups"] += 1
            cur[1] += 1
        elif k == "pressed" and what.startswith("stay ("):
            r["stays"] += 1
        elif k == "says" and p.get("gui") == "GlobalErrorController" and "(29)" in str(p.get("text")):
            r["e29"] += 1
        elif k == "outcome" and p.get("v") == "victory":
            r["victory"] = now
            cur[2] = True
        elif k == "end":
            self.rep_close()
        elif k == "deployresult" and p.get("ok"):
            r["placed"] = r["placed"] or now

    def rep_close(self):
        """The battle is over: its rounds won go into the gym's total (a battle that won nothing is counted too)."""
        r = getattr(self, "rep", None)
        if not r or not r["cur"][0]:
            return
        won = max(0, r["cur"][0] - r["cur"][1] - (0 if r["cur"][2] else 1))
        r["won"] += won
        r["empty"] += 0 if won else 1
        r["cur"] = [0, 0, False]

    def rep_line(self, placed_ok, obo, path=None):
        r = getattr(self, "rep", None)
        if not r:
            return None
        self.rep_close()                                     # (a battle whose 'battle over' never came still counts)
        self.rep = None
        return gym_report(r, placed_ok, obo, time.time(), path)

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
TAKEN = {}                                       # fort id -> the rest stamp of a gym we EMPTIED (its rest ends when an enemy team holds it)
USER_SKIP = set()                                # 8-char gym ids Benny said to leave alone this run (--skip / {"skip": ...}; 11-15: Starbucks)


def rested(done, taken, scanned, enemy, now, rest=600):
    """The gyms left alone right now, and the ones just put back on the list: (skip, back).
    A gym rests `rest` seconds after a battle that made no progress, after it grew while we walked, or while it stays empty
    after we emptied it. A gym we EMPTIED that an enemy team holds again NEVER rests (Benny 2026-11-15: "you skipped a yellow
    gym and walked by it" -- yellow had retaken it 2 minutes after he took it, and the 10-minute rest hid it from the picker):
    the game's own gym details, read after we left it, put it back at once. back = [(fid, scan)]; the caller forgets their rest."""
    skip, back = set(), []
    for f, t in done.items():
        if now - t >= rest:
            continue
        sv = scanned.get(f)                              # [team, age ms, in battle, defenders, CP now, ...]
        if taken.get(f) == t and sv and sv[0] in enemy and sv[1] < 45000 and now - sv[1] / 1000.0 > t + 3:
            back.append((f, sv))
        else:
            skip.add(f)
    return skip, back


def pick(enemy, skip, here, goal, live, detour, area_r, ok=None):
    """The NEAREST non-red gym on the LIVE map that is raid-free and on the way: at most `detour` extra meters versus
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
        d_m = ch.meters(here, gp)                            # Benny 2026-11-15 22:09: "go to the closest non red gym" -- the NEAREST one
        key = (0 if in_area else 1, d_m)                     # (it replaced 02:52's cheapest-by-CP-and-contest order: it walked past near gyms)
        if best is None or key < best_key:
            best, best_key = (fid, gp, team), key
    return best


def pick_any(enemy, skip, done, here, goal, live, detour, area_r, ok, now, areas=None):
    """pick() over the gyms that are not resting; when that finds nothing, an ENEMY gym that is only resting (Benny 2026-11-15:
    "drill and finish" -- never idle while an enemy gym stands): never an empty one, never one under a raid, never one in a refused
    placement's one-hour rest. Returns (target, it_was_resting). areas (--monitor): every watched area, not just the goal's."""
    if areas:
        t = pick_areas(enemy + [0], skip, here, live, areas, ok)
    else:
        t = pick(enemy + [0], skip, here, goal, live, detour, area_r, ok)
    if t or not skip:
        return t, False
    hard = {f for f in skip if done.get(f, 0) > now}
    t = pick_areas(enemy, hard, here, live, areas) if areas else pick(enemy, hard, here, goal, live, detour, area_r)
    return t, bool(t)


def live_range(sess):
    """FortSettings.InteractionRangeMeters, read live from GlobalSettingsProto (C liveness walk; before any hook)."""
    import dump_game_limits as dl
    s = sess.create_script(dl.JS)
    s.load()
    try:
        return float(((s.exports_sync.global_settings().get("settings") or {}).get("FortSettings") or {})["InteractionRangeMeters"])
    finally:
        s.unload()


HOP = {"list": [], "i": None, "idle": None}             # --hop: the areas to cycle, the current one, since when nothing to do (survives a re-attach)
GREG = {"path": None, "g": {}, "dirty": False, "saved": 0.0, "raid": {}}   # --hop monitor: fid -> [lat, lng, seen on the map (1/0)]
JUMPED = {"t": 0.0, "m": 0.0, "told": True}              # the last TELEPORT: when, how far; told = its cooldown was measured
                                                         # (+ t0 / n / sum_m / max_m / act_m / act_gap: the whole unanswered chain)
COOL = {"on": False, "until": 0.0, "n": 0, "last29": 0.0, "said": False, "ok_seen": 0.0}   # the server's cooldown is ON: no Battle press until `until`
E29 = {"n": 0, "t1": 0.0, "until": 0.0}                  # error (29) with NO unanswered jump: the gym changed under the battle, not a cooldown
COOL_OBS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gym_state", "cooldown_obs.jsonl")


def cool_measured(jump_m):
    """The cooldown MEASURED after earlier jumps (cooldown_obs.jsonl, written by the runner from the server's answers): the
    shortest one seen after a jump at least this long, else the longest one seen. None = nothing measured yet."""
    obs = []
    try:
        for ln in open(COOL_OBS, encoding="utf-8"):
            o = json.loads(ln)
            if o.get("accepted_after_jump_s") and o.get("jump_m"):
                obs.append((float(o["jump_m"]), float(o["accepted_after_jump_s"])))
    except Exception:
        return None
    longer = [s for m, s in obs if m >= jump_m]
    return min(longer) if longer else (max(s for m, s in obs) if obs else None)


BAG_COMP = []                                            # fused parts found by the last bag walk [[id, cp, name]]: never in a team
TEAM_BAN = {}                                            # id -> why: out of every team for the rest of this run (team_ban)
PROVEN = {"ids": set(), "loaded": False,                 # ids seen in a battle the server COUNTED (kept across runs)
          "path": os.path.join(os.path.dirname(os.path.abspath(__file__)), "gym_state", "proven_fighters.json")}


def proven_load():
    if not PROVEN["loaded"]:
        PROVEN["loaded"] = True
        try:
            PROVEN["ids"].update(str(x) for x in json.load(open(PROVEN["path"], encoding="utf-8")).get("ids", []))
        except Exception:
            pass
    return PROVEN["ids"]


def proven_add(ids):
    """These fought in a battle the server COUNTED (a defender lost CP in it): none of them poisons a team."""
    new = {str(i) for i in (ids or [])} - proven_load()
    if not new:
        return
    PROVEN["ids"].update(new)
    try:
        tmp = PROVEN["path"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "ids": sorted(PROVEN["ids"])}, f)
        os.replace(tmp, PROVEN["path"])
    except Exception:
        pass


def team_suspects(team):
    """Battles refused in a row with nothing else to explain it: the six themselves are the suspect. 11-16 22:36 (ferry gym)
    and 11-17 00:56 (Liberty flagpole): a Zekrom fused into a Black Kyurem was picked as an electric counter and the server
    answered every battle 'already completed (29)' -- 13 of 13 -- until Benny closed the game. The bag walk now leaves fused
    parts out; this is the net for whatever else can do it. Suspects = members never seen in a counted battle."""
    proven = proven_load()
    return [str(i) for i in (team or []) if str(i) not in proven and str(i) not in TEAM_BAN]


def team_ban(ids, why, sc):
    """Out of every team for the rest of this run: the tapper stops picking them at once, the counter ranking loses them."""
    for i in ids:
        TEAM_BAN[str(i)] = why
    BAG_RO_ALL[:] = [r for r in BAG_RO_ALL if r[0] not in TEAM_BAN]
    if CT.get("cur"):
        CT["cur"]["at"], CT["cur"]["sig"] = 0, None       # the next reading re-picks the counters without them
    try:
        sc.exports_sync.ban(list(TEAM_BAN))
    except Exception as e:
        say(f"  (ban not handed to the tapper: {e})")
    try:
        with open(os.path.join(os.path.dirname(PROVEN["path"]), "team_bans.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "ids": [str(i) for i in ids], "why": why}) + "\n")
    except Exception:
        pass


LAST_ACT = {"t": 0.0, "pos": None}                       # the last action the server COUNTED (a defender lost CP to us / a deploy):
                                                         # when, and where (the gym) -- the cooldown runs from THERE, not from a jump


def jump_chain(prev, now, m, to=None, act=None, meters=None):
    """The jump record after one more TELEPORT (pure: note_jump stores it). Jumps the server has not answered yet are ONE
    chain -- the cooldown is not the last short jump's. 11-17 00:25: an island hop of 2.2 km and, 30 s later, 74 m onto the
    gym was written down as 'refused 10 s / accepted 117 s after a 74 m jump'. t0 / n / sum_m / max_m describe the whole
    chain, refused_s (seconds after t0) survives the chain; act_gap = seconds since the server last counted an action of
    ours, act_m = metres from that action's gym to this landing (None: not known)."""
    chained = bool(prev.get("t")) and not prev.get("told", True)
    act = act or {}
    rec = {"t": now, "m": m, "told": False, "to": tuple(to) if to else None,
           "t0": (prev.get("t0") or prev["t"]) if chained else now,
           "n": (prev.get("n") or 1) + 1 if chained else 1,
           "sum_m": (prev.get("sum_m") or prev.get("m") or 0.0) + m if chained else m,
           "max_m": max(prev.get("max_m") or prev.get("m") or 0.0, m) if chained else m,
           "refused_s": (prev.get("refused_s") or 0.0) if chained else 0.0,
           "act_gap": round(now - act["t"], 1) if act.get("t") else None, "act_m": None}
    if act.get("pos") and to and meters:
        try:
            rec["act_m"] = round(meters(tuple(act["pos"]), tuple(to)))
        except Exception:
            pass
    return rec


def jump_desc(j=None):
    """'a 74 m jump' / '2 jumps (2268 m in all, the longest 2194 m)' -- the jumps the server has not answered yet."""
    j = JUMPED if j is None else j
    n = j.get("n") or 1
    what = f"a {j.get('m') or 0:.0f} m jump" if n <= 1 else \
        f"{n} jumps ({j.get('sum_m') or 0:.0f} m in all, the longest {j.get('max_m') or 0:.0f} m)"
    return what + (f", landing {j['act_m']} m from our last counted action" if j.get("act_m") is not None else "")


def jump_since(now=None, j=None):
    """Seconds since the FIRST jump the server has not answered yet (0: it has answered every jump)."""
    j = JUMPED if j is None else j
    if not j.get("t") or j.get("told", True):
        return 0.0
    return (now or time.time()) - (j.get("t0") or j["t"])


def act_pos(fid):
    """Where an action at this gym happened: the gym's own spot (the --hop register), else the last jump's landing."""
    gr = GREG["g"].get(fid) if fid else None
    return (gr[0], gr[1]) if gr else JUMPED.get("to")
LAST_TEAM = {}                                           # fid -> the last non-empty team seen on the map (who held an emptied gym)
SLIP_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gym_state", "slip_in.jsonl")
COOL_RETRY_S = 8.0                                       # the crash guard after an error 29 (an instant re-open crashed the game
                                                         # twice, 11-16 22:03 / 22:37) -- a safety bound, NOT a cooldown guess


def cool_sign(what):
    """A cooldown sign from the server (error 29 right after a jump, a refused join on a gym with room): that battle did not
    count. Ask the server again after the crash guard -- every answer brackets the REAL cooldown, and the first counted
    battle ends the wait. Benny 11-17 00:36: "figure out the exact cooldown to permit you to go asap" / "DUDE BATTLE
    ALREADY": the table wait (106 s after a 302 m jump, 283 s after 2.2 km) sat out time his own battle proved was over --
    it counted 65 s after the 2.2 km jump, ours were refused at 33 s and 52 s and we would have waited until 104 s."""
    now = time.time()
    fresh = bool(JUMPED["t"]) and not JUMPED["told"]       # only a jump the server has not answered yet anchors the bracket
    since = jump_since(now)                                # (from the FIRST unanswered jump: a hop + a short jump is one chain)
    COOL["n"] += 1
    COOL["until"] = now + COOL_RETRY_S
    COOL["on"], COOL["said"] = True, False
    if fresh:
        JUMPED["refused_s"] = max(JUMPED.get("refused_s") or 0.0, since)
    _act = (now - LAST_ACT["t"]) if LAST_ACT["t"] else None
    say(f"  COOLDOWN sign #{COOL['n']} ({what}, {since:.0f} s after {jump_desc()}"
        + (f", {_act:.0f} s after our last counted action" if _act is not None else "")
        + f") -- asking the server again at {time.strftime('%H:%M:%S', time.localtime(COOL['until']))} "
          f"({COOL_RETRY_S:.0f} s crash guard; no table wait -- its answer decides)")
    try:
        with open(COOL_OBS, "a", encoding="utf-8") as f:
            f.write(json.dumps({"k": "cooldown_refused", "t": int(now), "what": what,
                                "jump_m": round(JUMPED.get("max_m") or JUMPED["m"]), "refused_at_s": round(since, 1),
                                "since_last_action_s": round(_act, 1) if _act is not None else None,
                                "jumped_after_action_s": JUMPED.get("act_gap"), **jump_cols()}) + "\n")
    except Exception:
        pass


def cool_off(why):
    if COOL["on"]:
        say(f"  COOLDOWN over: {why}")
    COOL.update(on=False, n=0, said=False)


def cool_wait():
    """True only while a cooldown wait runs (no Battle, no jump). Once `until` is past, the next battle IS the check -- and
    a jump is allowed again (11-16 23:36: an error 29 with no jump set the flag and nothing cleared it: no more jumps)."""
    return COOL["on"] and time.time() < COOL["until"]


def battles_count(fid, why, sc=None, extra=None, team=None):
    """The server COUNTS our actions (a defender lost CP in our battle / it accepted a deploy): there is no cooldown now.
    Measures the last jump's cooldown if the server had not answered it yet; ends a cooldown wait and an error-29 streak.
    team = the six of a counted BATTLE: proven fighters from now on."""
    held = COOL["on"] or E29["n"] > 0                       # Battle presses were held back: release them
    E29.update(n=0, until=0.0)
    _now = time.time()
    _gap = round(_now - LAST_ACT["t"], 1) if LAST_ACT["t"] else None
    if team:
        proven_add(team)
    if JUMPED["t"] and not JUMPED["told"]:
        _cd = {"k": "cooldown", "t": int(_now), "signal": why, "jump_m": round(JUMPED.get("max_m") or JUMPED["m"]),
               "accepted_after_jump_s": round(jump_since(_now), 1), "refused_last_s": round(JUMPED.get("refused_s") or 0.0, 1) or None,
               "jumped_after_action_s": JUMPED.get("act_gap"), "since_last_action_s": _gap, **jump_cols(), "fid": fid, **(extra or {})}
        say(f"  COOLDOWN measured: {why} {_cd['accepted_after_jump_s']:.0f} s after {jump_desc()}"
            + (f", {_gap:.0f} s after our last counted action" if _gap is not None else "")
            + (f" -- the real cooldown lies between {_cd['refused_last_s']:.0f} s (refused) and {_cd['accepted_after_jump_s']:.0f} s"
               if _cd["refused_last_s"] else ""))
        JUMPED["told"] = True
        try:
            with open(COOL_OBS, "a", encoding="utf-8") as f:
                f.write(json.dumps(_cd) + "\n")
        except Exception:
            pass
    LAST_ACT.update(t=_now, pos=act_pos(fid) or LAST_ACT.get("pos"))
    if COOL["on"]:
        cool_off(why)
    if held and sc is not None:
        try:
            sc.exports_sync.autobattle(True)
        except Exception:
            pass


def jump_cols():
    """The jump chain's columns for cooldown_obs.jsonl (jump_m there = the LONGEST jump of the chain)."""
    return {"chain_n": JUMPED.get("n") or 1, "chain_m": round(JUMPED.get("sum_m") or JUMPED["m"]),
            "last_jump_m": round(JUMPED["m"]), "from_last_action_m": JUMPED.get("act_m")}


def note_jump(m, to=None):
    """A TELEPORT went out. The server's cooldown is measured from the FIRST jump it has not answered yet (jump_chain): a
    finished wait / error-29 streak ends, an unanswered jump before this one stays in the record."""
    JUMPED.update(jump_chain(dict(JUMPED), time.time(), m, to, LAST_ACT, ch.meters))
    if COOL["on"]:
        cool_off("a new jump -- its cooldown is measured from the first jump the server has not answered")
    E29.update(n=0, until=0.0)


def hop_area(gp):
    """The index of the --hop area this position lies in (None: outside every one)."""
    for i, h in enumerate(HOP["list"]):
        if ch.meters(gp, h[:2]) <= h[2]:
            return i
    return None


def greg_load(path):
    GREG["path"] = path
    try:
        GREG["g"] = {k: list(v) for k, v in json.load(open(path, encoding="utf-8")).items()}
    except Exception:
        GREG["g"] = {}


def greg_note(fid, lat, lng, on_map):
    """Remember a gym of the watched areas: its position, and whether this run has seen it on the game's own map."""
    old = GREG["g"].get(fid)
    if old is None or abs(old[0] - lat) > 1e-6 or abs(old[1] - lng) > 1e-6 or (on_map and not old[2]):
        GREG["g"][fid] = [lat, lng, 1 if (on_map or (old and old[2])) else 0]
        GREG["dirty"] = True


def greg_save():
    if GREG["dirty"] and GREG["path"] and time.time() - GREG["saved"] > 20:
        try:
            tmp = GREG["path"] + ".tmp"
            json.dump(GREG["g"], open(tmp, "w", encoding="utf-8"))
            os.replace(tmp, GREG["path"])
            GREG["dirty"], GREG["saved"] = False, time.time()
        except Exception as e:
            say(f"  (gym registry not saved: {e})")


NOGYM = {"set": None}                                    # species that cannot defend a gym (legendary / mythical / Ultra Beast)


def _nogym_species():
    if NOGYM["set"] is None:
        s = set()
        try:
            for e in json.load(open(os.path.join(GM_DIR, "gamemaster_pokeminers.json"), encoding="utf-8")):
                ps = (e.get("data") or {}).get("pokemonSettings")
                if ps and ps.get("pokemonClass") in ("POKEMON_CLASS_LEGENDARY", "POKEMON_CLASS_MYTHIC", "POKEMON_CLASS_ULTRA_BEAST"):
                    s.add(re.sub(r"[^a-z0-9]", "", str(ps.get("pokemonId", "")).lower()))
        except Exception as e:
            say(f"  (legendary list not read: {e})")
        NOGYM["set"] = s
    return NOGYM["set"]


def placement_fallback(dep):
    """Benny 11-16 23:27: "dont ever leave our hard work battling up for grabs" -- the runner had emptied Liggett Hall with no
    shiny Gyarados at full HP, opened Deploy for him and waited; he placed Tyranitar by hand ~30 s later. With no healthy
    Gyarados, the strongest healthy Pokemon that can defend goes in at once: never a legendary / mythical / Ultra Beast,
    never one of the top 18 attackers (rank order) or this gym's counter team."""
    bad = _nogym_species()
    keep = {x[0] for x in dep["ro"][:18]} | set(((CT.get("cur") or {}).get("ids") or [])[:12])
    rows = [x for x in (BAG_RO_ALL or dep["ro"]) if x[3] > 0 and x[2] >= x[3] and x[0] not in keep
            and re.sub(r"[^a-z0-9]", "", str(x[4]).lower()) not in bad]
    rows.sort(key=lambda x: (not (len(x) > 5 and x[5]), -x[1]))   # Benny 11-17 00:41: "if out of gyarados, use highest cp
    return rows[:12]                                         # shinies" -- every shiny first (whole bag), highest CP first


def place_ids(dep):
    """What goes into a gym, in order: shiny Gyarados at full HP, then the fallback. The tapper takes the first one that is
    at full HP and not in a gym, so an emptied gym never waits for a hand."""
    return ([x[0] for x in dep["gy"]] + [x[0] for x in dep.get("fb", [])])[:16]   # (all Gyarados: the tapper reads HP LIVE --
                                                             # one revived a second ago goes in, never a fallback for a stale read)


def pick_areas(enemy, skip, here, live, areas, ok=None):
    """--monitor: the NEAREST gym that needs us in ANY watched area -- this island from the game's map, the others from gym
    details read by id. Never one resting, under a raid or with a stale record. Teleports make the distance a jump, not a walk."""
    best, best_key = None, None
    for fid, v in live.items():
        if fid in skip or v[1] > 60000 or v[4] or not (v[0] in enemy or (ok and ok(fid, v))):
            continue
        gp = (v[2], v[3])
        if not any(ch.meters(gp, (x[0], x[1])) <= x[2] for x in areas):
            continue
        key = ch.meters(here, gp)
        if best is None or key < best_key:
            best, best_key = (fid, gp, v[0]), key
    return best
RANK = {"path": None, "mtime": None, "score": {}}       # attack_rank.json: PokemonProto.id (decimal string) -> score
BAG_RO_ALL = []                                          # every fighter of the last bag walk (a rank reload re-sorts these, no new walk)


def rank_load(path, first=False):
    """Read the attack rank file (Benny's ranking of his best attackers) when its mtime changed. True = a new ranking is in use.
    No file = the old order, highest CP first (said once at startup)."""
    RANK["path"] = path
    try:
        mt = os.path.getmtime(path) if path else None
    except OSError:
        mt = None
    if mt is None:
        had = bool(RANK["score"])
        if first or had:
            say(f"  attack rank: no {os.path.basename(path) if path else 'attack_rank.json'} -- the attack team is the highest CP, as before")
        RANK["mtime"], RANK["score"] = None, {}
        return had
    if mt == RANK["mtime"]:
        return False
    try:
        rows = json.load(open(path, encoding="utf-8")).get("rank") or []
        RANK["score"] = {str(r["id"]): float(r.get("score", 0)) for r in rows if r.get("id") is not None}
        RANK["mtime"] = mt
        say(f"  attack rank: {len(RANK['score'])} Pokemon ranked from {os.path.basename(path)} -- they fight first, best score first; the rest by CP")
        return True
    except Exception as e:
        RANK["mtime"] = mt                               # do not retry a broken file every second; keep the last good ranking
        say(f"  !! attack rank file unreadable ({e}) -- keeping the previous order")
        return False


def rank_sort(rows):
    """Ranked ids first (score high to low), then everyone else by CP -- the sort comes BEFORE any cut."""
    sc_ = RANK["score"]
    return sorted(rows, key=lambda x: (0, -sc_[x[0]], -x[1]) if x[0] in sc_ else (1, 0, -x[1]))


def rank_say(ro):
    sc_ = RANK["score"]
    say("  attack roster, top 6 by rank: " + (", ".join(f"{x[4]} CP {x[1]}" + (f" (score {sc_[x[0]]:g})" if x[0] in sc_ else " (unranked)") for x in ro[:6]) or "none"))


# ---- counter team (Benny 2026-11-16: "put the top 3 selection of my team to be the most effect and fastest") ----
# Every ranked attacker in the bag is scored against THIS gym's defenders -- their real species, moves and CP now, from the
# gym's own details -- and the tapper's pickTeam takes the first six usable in that order (the buddy keeps slot 6).
# Per defender: ER = (DPS^3 x TDO)^(1/4), DPS = cycle DPS with type effectiveness + same-type bonus (its better charged move:
# the tapper fires the strongest), TDO = DPS x its HP / the defender's DPS on it. The gym score weights each defender by
# its HP, the first three in battle order (oldest placed first) twice: they meet the top three. Mechanics used: defenders
# have doubled HP and fight with the CP their motivation leaves them (all stats scaled alike), a fast move every
# duration + 2 s, 1 energy per 2 HP lost (game master BATTLE_SETTINGS).
GM_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), "pogo_extract")
TYPES18 = ["NORMAL", "FIGHTING", "FLYING", "POISON", "GROUND", "ROCK", "BUG", "GHOST", "STEEL", "FIRE", "WATER", "GRASS",
           "ELECTRIC", "PSYCHIC", "ICE", "DRAGON", "DARK", "FAIRY"]
TIDX = {t: i for i, t in enumerate(TYPES18)}
CT = {"ok": None, "mv_id": {}, "mv_nm": {}, "ps_form": {}, "ps_base": {}, "ps_dex": {}, "chart": {}, "cpm": [], "stab": 1.2,
      "sh_atk": 1.2, "sh_def": 0.8333333, "epl": 0.5, "forms": {}, "att": {}, "att_mtime": None, "cur": None}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def ct_load():
    """The game master tables, once (~1 s): moves, typings + base stats, the type chart, CP multipliers, battle settings."""
    if CT["ok"] is not None:
        return CT["ok"]
    try:
        gm = json.load(open(os.path.join(GM_DIR, "gamemaster_pokeminers.json"), encoding="utf-8"))
        CT["forms"] = json.load(open(os.path.join(GM_DIR, "form_enum.json"), encoding="utf-8"))
        for t in gm:
            tid, d = t.get("templateId", ""), t.get("data") or {}
            m = re.match(r"V(\d+)_MOVE_", tid)
            if m and "moveSettings" in d:
                ms = d["moveSettings"]
                mv = (float(ms.get("power") or 0), int(ms.get("energyDelta") or 0), (ms.get("durationMs") or 1000) / 1000.0,
                      str(ms.get("pokemonType", "")).replace("POKEMON_TYPE_", ""), str(ms.get("movementId", tid)))
                CT["mv_id"][int(m.group(1))] = mv
                CT["mv_nm"][mv[4]] = mv
                continue
            m = re.match(r"V(\d+)_POKEMON_", tid)
            if m and "pokemonSettings" in d:
                ps = d["pokemonSettings"]
                st = ps.get("stats") or {}
                if not st.get("baseAttack"):
                    continue
                v = (st["baseAttack"], st.get("baseDefense") or 1, st.get("baseStamina") or 1,
                     tuple(x.replace("POKEMON_TYPE_", "") for x in (ps.get("type"), ps.get("type2")) if x),
                     str(ps.get("pokemonId", "?")).replace("_", " ").title())
                dex = int(m.group(1))
                if ps.get("form"):
                    CT["ps_form"][_norm(ps["form"])] = v
                    CT["ps_dex"].setdefault(dex, v)
                else:
                    CT["ps_base"][_norm(ps.get("pokemonId"))] = v
                    CT["ps_dex"][dex] = v
                continue
            if tid.startswith("POKEMON_TYPE_") and "typeEffective" in d:
                te = d["typeEffective"]
                CT["chart"][str(te.get("attackType", "")).replace("POKEMON_TYPE_", "")] = list(te.get("attackScalar") or [])
            elif tid == "PLAYER_LEVEL_SETTINGS":
                CT["cpm"] = list((d.get("playerLevel") or {}).get("cpMultiplier") or [])
            elif tid == "BATTLE_SETTINGS":
                b = d.get("battleSettings") or {}
                CT["stab"] = float(b.get("sameTypeAttackBonusMultiplier", 1.2))
                CT["sh_atk"] = float(b.get("shadowPokemonAttackBonusMultiplier", 1.2))
                CT["sh_def"] = float(b.get("shadowPokemonDefenseBonusMultiplier", 0.8333333))
                CT["epl"] = float(b.get("energyDeltaPerHealthLost", 0.5))
        CT["ok"] = bool(CT["mv_id"] and len(CT["chart"]) >= 18 and CT["cpm"])
        if not CT["ok"]:
            say("  !! counter team off: the game master is missing moves / the type chart / CP multipliers -- attack rank order")
    except Exception as e:
        CT["ok"] = False
        say(f"  !! counter team off: the game master did not load ({e}) -- the attack rank order is used")
    return CT["ok"]


def ct_cpm(level):
    c = CT["cpm"]
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return 0.0
    i = int(lv)
    if not c or i < 1:
        return 0.0
    if i >= len(c):
        return c[-1]
    if lv == i:
        return c[i - 1]
    return math.sqrt((c[i - 1] ** 2 + c[i] ** 2) / 2)    # a half level


def ct_eff(mtype, dtypes):
    row = CT["chart"].get(mtype)
    e = 1.0
    if row:
        for t in dtypes:
            if t in TIDX:
                e *= row[TIDX[t]]
    return e


def ct_attackers():
    """Battle numbers for every ranked attacker (attack_rank.json rows: species, form, level, IVs, shadow, its moves)."""
    if CT["att"] and CT["att_mtime"] == RANK["mtime"]:
        return CT["att"]
    att = {}
    try:
        rows = json.load(open(RANK["path"], encoding="utf-8")).get("rank") or []
    except Exception:
        rows = []
    for r in rows:
        fm = str(r.get("form") or "")
        ps = CT["ps_form"].get(_norm(fm)) if fm not in ("", "Unset") else None
        ps = ps or CT["ps_base"].get(_norm(r.get("species")))
        fast = CT["mv_nm"].get(str(r.get("fast")))
        chs = [c for c in (CT["mv_nm"].get(str(x)) for x in (r.get("charged") or [])) if c and c[1] < 0]
        cpm = ct_cpm(r.get("level"))
        if not ps or not fast or fast[1] <= 0 or not chs or not cpm or r.get("id") is None:
            continue
        iv = list(r.get("iv") or [0, 0, 0]) + [0, 0, 0]
        sh = bool(r.get("shadow"))
        att[str(r["id"])] = {"atk": (ps[0] + iv[0]) * cpm * (CT["sh_atk"] if sh else 1.0),
                             "def": (ps[1] + iv[1]) * cpm * (CT["sh_def"] if sh else 1.0),
                             "hp": max(1, math.floor((ps[2] + iv[2]) * cpm)), "types": ps[3], "fast": fast, "ch": chs,
                             "name": str(r.get("species") or ps[4]), "cp": r.get("cp", 0)}
    CT["att"], CT["att_mtime"] = att, RANK["mtime"]
    return att


def ct_defender(x):
    """One live defender [dex, form, move1, move2, CP now, CP placed, cpm, ivA, ivD, ivS, placed ms, motivation %] -> numbers."""
    try:
        dex, form, m1, m2, cp, cpm = int(x[0]), int(x[1]), int(x[2]), int(x[3]), int(x[4]), float(x[6])
        iv = [max(0, int(v)) for v in x[7:10]]
    except (TypeError, ValueError, IndexError):
        return None
    fn = str(CT["forms"].get(str(form), ""))
    ps = CT["ps_form"].get(_norm(fn)) if fn not in ("", "Unset") else None
    ps = ps or CT["ps_dex"].get(dex)
    if not ps or cp <= 0 or len(iv) < 3:
        return None
    a_, d_, s_ = ps[0] + iv[0], ps[1] + iv[1], ps[2] + iv[2]
    if cpm <= 0:                                         # no level read: the one that gives its CP now
        cpm, k = math.sqrt(10.0 * cp / (a_ * math.sqrt(d_ * s_))), 1.0
    else:                                                # its motivation (and IVs the gym may hide): every stat scaled alike
        k = max(0.3, min(1.6, math.sqrt(cp / max(10.0, a_ * math.sqrt(d_ * s_) * cpm * cpm / 10.0))))
    return {"atk": a_ * cpm * k, "def": d_ * cpm * k, "hp": 2.0 * s_ * cpm * k, "types": ps[3], "fast": CT["mv_id"].get(m1),
            "ch": CT["mv_id"].get(m2), "name": ps[4], "cp": cp}


def ct_dmg(mv, atk, dfn, atypes, dtypes):
    return math.floor(0.5 * mv[0] * atk / dfn * (CT["stab"] if mv[3] in atypes else 1.0) * ct_eff(mv[3], dtypes)) + 1


def ct_vs(A, D):
    """Attacker A against defender D -> (ER, DPS, best effectiveness of its moves)."""
    fd, fdur, fen = ct_dmg(A["fast"], A["atk"], D["def"], A["types"], D["types"]), A["fast"][2], A["fast"][1]
    dps, use = 0.0, None
    for c in A["ch"]:
        n = math.ceil(-c[1] / fen)
        v = (n * fd + ct_dmg(c, A["atk"], D["def"], A["types"], D["types"])) / (n * fdur + c[2])
        if v > dps:
            dps, use = v, c
    if dps <= 0:
        return 0.0, 0.0, 1.0
    inc = 10.0                                           # the defender's DPS on it (unknown moves: a middling 10)
    if D["fast"] and D["fast"][2] > 0:
        per = D["fast"][2] + 2.0
        inc = ct_dmg(D["fast"], D["atk"], A["def"], D["types"], A["types"]) / per
        if D["ch"] and D["ch"][1] < 0:
            rate = max(0.1, max(0, D["fast"][1]) / per + CT["epl"] * dps)
            inc += ct_dmg(D["ch"], D["atk"], A["def"], D["types"], A["types"]) / (-D["ch"][1] / rate + D["ch"][2])
    tdo = dps * A["hp"] / max(inc, 0.5)
    return (dps ** 3 * tdo) ** 0.25, dps, max(ct_eff(A["fast"][3], D["types"]), ct_eff(use[3], D["types"]))


def ct_score(A, Ds):
    num = den = dsum = 0.0
    se = 0
    for i, D in enumerate(Ds):
        w = D["hp"] * (2.0 if i < 3 else 1.0)
        er, dps, eff = ct_vs(A, D)
        num, den, dsum = num + w * er, den + w, dsum + w * dps
        se += eff > 1.01
    return (num / den, dsum / den, se) if den else (0.0, 0.0, 0)


def _mv_short(mv):
    return str(mv[4]).replace("_FAST", "").replace("_", " ").title()


def roster_ids(dep, head=None):
    """What the tapper picks the six from: this gym's counters first (once its defenders are known), then the WHOLE rank
    order (the faint scan / batch revive reads the roster too -- nothing of it is cut)."""
    base = [x[0] for x in dep["ro"]]
    head = head if head is not None else (CT["cur"]["ids"] if CT["cur"] else [])
    seen = set(head)
    return list(head) + [i for i in base if i not in seen]


def counter_push(fid, sv, sc, dep, a, g):
    """sv = scanned()[fid]; sv[8] = its defenders. Re-ranks only when they changed (or every 2 min); True = handed over."""
    defs = sv[8] if sv and len(sv) > 8 else None
    if not defs or not RANK["path"] or not ct_load():
        return False
    sig = (fid, tuple((x[0], x[1], x[2], x[3], int(x[4]) // 250) for x in defs if len(x) > 4))
    cur = CT["cur"]
    if cur and cur["sig"] == sig and time.time() - cur["at"] < 120:
        return False
    att = ct_attackers()
    Ds = [d for d in (ct_defender(x) for x in sorted(defs, key=lambda x: x[10] if len(x) > 10 and x[10] else 0)) if d]
    if getattr(a, "one_by_one", False):                  # one-by-one: only the FIRST defender is ever fought
        Ds = Ds[:1]
    if not Ds or not att:
        return False
    bag = {r[0]: r for r in BAG_RO_ALL}
    scored = []
    for aid, A in att.items():
        r = bag.get(aid)
        if r is None or (r[2] <= 0 and not a.heal_top):  # not in the bag now (in a gym, released) / fainted at the last walk
            continue                                     # (--heal-top: the fainted best stay on top -- they get revived)
        s, dps, se = ct_score(A, Ds)
        scored.append((s, dps, aid, se))
    if not scored:
        return False
    scored.sort(key=lambda x: (-x[0], -x[1]))
    ids = [x[2] for x in scored[:60]]
    was = cur["ids"][:5] if cur and cur["fid"] == fid else None
    try:
        sc.exports_sync.roster(roster_ids(dep, ids), a.heal_top, [], [x[0] for x in dep["gy"]])
    except Exception as e:                               # not recorded: the next reading tries again
        say(f"  !! counter team not handed over ({e})")
        return False
    CT["cur"] = {"fid": fid, "sig": sig, "ids": ids, "at": time.time()}
    if ids[:5] != was:
        say(f"  COUNTERS vs {fid[:8]} -- defenders, oldest first: " + ", ".join(f"{D['name']} {D['cp']}" for D in Ds))
        say("    top 5, fastest vs THESE defenders: " + "; ".join(
            f"{att[x[2]]['name']} {att[x[2]]['cp']} [{_mv_short(att[x[2]]['fast'])} / {' + '.join(_mv_short(c) for c in att[x[2]]['ch'])}] "
            f"ER {x[0]:.1f}, DPS {x[1]:.1f}, super-effective on {x[3]}/{len(Ds)}" for x in scored[:5]))
        if g.study_f:
            g.study_f.write(json.dumps({"k": "study", "src": "counters", "t": int(time.time() * 1000), "fid": fid, "defs": defs,
                                        "top": [[x[2], round(x[0], 2), round(x[1], 2), x[3]] for x in scored[:12]]}) + "\n")
            g.study_f.flush()
    return True


def bag_status(sess, tapper=None):
    """One live bag walk (C-only instance lookup, safe with the tapper attached): (your deployed count, your shiny
    Gyarados not in a gym, highest CP first, as [(id, cp, hp, maxhp)], the attack roster highest CP first as
    [(id, cp, hp, maxhp, name)] -- everything that can fight except Slaking, Regigigas and the shiny Gyarados kept for placing; ranked first when attack_rank.json exists).
    Species ids and names from the live enum."""
    import dump_game_limits as dl
    js = dl.JS.split("rpc.exports = {")[0] + r"""
var PO = null, GY = -1, DO = null, SLAKING = -1, REGI = -1, NAMES = {};
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
    if (fn === 'V0130PokemonGyarados') GY = v; if (fn === 'V0289PokemonSlaking') SLAKING = v; if (fn === 'V0486PokemonRegigigas') REGI = v; }
  if (GY < 0 || SLAKING < 0 || REGI < 0) throw new Error('Gyarados / Slaking / Regigigas id not found in the live enum');
}
rpc.exports = {
  scan: function (ptrs) {
    setup(); var dep = 0, gy = [], ro = [], dp = [], fa = [], comp = [];
    ptrs.forEach(function (q) { var p = ptr(q);
      if (PO.isComponent !== undefined && p.add(PO.isComponent).readU8()) {   /* held inside a White / Black Kyurem: never in a team */
        comp.push([p.add(PO.id).readU64().toString(), p.add(PO.cp).readS32(), NAMES[p.add(PO.pokemonId).readS32()] || '?']); return; }
      if (str(p.add(PO.deployedFortId).readPointer())) { dep++;
        dp.push([p.add(PO.id).readU64().toString(), p.add(PO.cp).readS32(), NAMES[p.add(PO.pokemonId).readS32()] || '?',
          p.add(PO.deployedGymLatDegree).readDouble(), p.add(PO.deployedGymLngDegree).readDouble(), str(p.add(PO.deployedFortId).readPointer())]); return; }
      if (p.add(PO.isEgg).readU8() || p.add(PO.isBad).readU8() || str(p.add(PO.deployedStationId).readPointer())) return;
      var sp = p.add(PO.pokemonId).readS32(), d = p.add(PO.pokemonDisplay).readPointer(), shiny = !d.isNull() && d.add(DO.shiny).readU8();
      var row = [p.add(PO.id).readU64().toString(), p.add(PO.cp).readS32(), p.add(PO.stamina).readS32(), p.add(PO.maxStamina).readS32(), NAMES[sp] || String(sp)];
      if (row[2] <= 0 && row[3] > 0) fa.push([row[0], row[1], row[4]]);
      if (sp === GY && shiny) gy.push(row.slice(0, 4));              /* the placement stock */
      else if (sp !== SLAKING && sp !== REGI) ro.push(row.concat([shiny ? 1 : 0])); });   /* [5] shiny: the placement fallback */
    return {dep: dep, gy: gy, ro: ro, dp: dp, fa: fa, comp: comp};   /* all of them: Python ranks, THEN cuts to 80 */
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
        dep, gy, ro, dp, fa, comp = 0, [], [], [], [], []
        for i in range(0, len(best), 500):
            r = s.exports_sync.scan(best[i:i + 500])
            dep += r["dep"]
            gy += r["gy"]
            ro += r["ro"]
            dp += r["dp"]
            fa += r["fa"]
            comp += r.get("comp") or []
        BAG_COMP[:] = sorted(comp, key=lambda x: -x[1])       # fused parts: in no list below (the scan returned before them)
        _cid = {str(x[0]) for x in comp}
        ro = [x for x in ro if x[0] not in TEAM_BAN and x[0] not in _cid]   # + whatever this run took out of every team
        gy = [x for x in gy if x[0] not in _cid]
        fa = [x for x in fa if x[0] not in _cid]
        gy.sort(key=lambda x: -x[1])
        BAG_RO_ALL[:] = ro
        ro = rank_sort(ro)
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


def autobattle(sc, g, on):
    """The tapper's own Battle press on the gym screen, on / off -- REMEMBERED on the Game, so the tick gives it back the
    moment no hold is on. 11-17 00:30:09-00:34:19: a hold ended outside the drill's map branch (the only place that turned
    it back on); seven enemy gym screens opened with no Battle press from the tapper -- 4 min 10 s of 4 s backups."""
    g.ab_off = not on
    sc.exports_sync.autobattle(bool(on))


def e29_seen(g, sc, fid):
    """The game said "The Gym battle has already been completed! (29)" since the last look: decide what it means -- once,
    and from ANY place in the drill loop. It used to be read only on the plain map; the tapper re-opened the gym 2 s after
    the kick, so the flag sat unread for minutes and fired as a brand-new refusal the next time the loop touched the map
    (11-17: a real 29 at 00:22:40 handled at 00:25:29, one at 00:29:05 handled at 00:30:09 -- each the second a gym had
    just been emptied). A flag that a round start or a jump of ours has overtaken is history: no hold for it.
    Returns True when a hold was set."""
    at = getattr(g, "err29_at", 0.0)
    if at <= COOL["last29"]:
        return False
    COOL["last29"] = at
    if getattr(g, "start_at", 0.0) > at or at < JUMPED["t"]:
        say(f"  (error 29 from {time.time() - at:.0f} s ago: a battle round started or we jumped since -- no hold for it)")
        return False
    _nm = getattr(g, "names", {})
    if JUMPED["t"] and not JUMPED["told"]:                # no battle has counted since OUR last jump: the server's cooldown
        cool_sign("battle refused: error 29")             # sign (Benny 23:28: "you keep trying to battle and not reading
        autobattle(sc, g, False)                          # the signs for a cooldown")
        _sus = team_suspects(getattr(g, "last_team", None)) if COOL["n"] >= 4 else []
        if _sus:                                         # 4 refusals after one jump AND members no counted battle ever saw
            team_ban(_sus, f"{COOL['n']} battles refused in a row at {fid[:8]} after a jump; never in a counted battle", sc)
            say(f"  {COOL['n']} refusals in a row: also taking the unproven members out of every team for this run: "
                + ", ".join(_nm.get(i, i) for i in _sus))
        return True
    _now = time.time()                                   # battles HAVE counted since the last jump (or no jump): NOT a
    if E29["n"] == 0:                                    # cooldown -- the gym changed under the battle (its team fed a
        E29["t1"] = _now                                 # defender between rounds: Ellis 23:36 + 23:40, no jump, 3-8%
    E29["n"] += 1                                        # drained per session). Re-open on the game's next map refresh
    _sus = team_suspects(getattr(g, "last_team", None)) if E29["n"] >= 2 else []   # (GMO 5 s; an instant re-open after (29)
    autobattle(sc, g, False)                             # crashed the game twice)
    if _sus:                                             # twice running, no jump: the six are the suspect (the fused Zekrom,
        team_ban(_sus, f"{E29['n']} battles refused in a row at {fid[:8]} with no jump; never in a counted battle", sc)   # 11-17)
        E29["until"] = _now + 5.0
        say(f"  error 29 x{E29['n']} at {fid[:8]} with no jump: the six are the suspect -- out of every team for this "
            f"run: {', '.join(_nm.get(i, i) for i in _sus)} (never in a battle the server counted); Battle again with "
            f"the rest on the next map refresh (5 s)")
    else:
        E29["until"] = _now + min(max(_now - E29["t1"], 5.0), 40.0)   # as long again, 40 s at most (00:59: the doubling had
        say(f"  error 29 at {fid[:8]}, not a cooldown (battles counted since the last jump): the gym changed under "   # grown to
            f"the battle -- "                                                                 # 2 min 47 s of standing)
            f"{'re-opening on the next map refresh (5 s)' if E29['n'] == 1 else str(E29['n']) + ' in a row, every member proven in counted battles: waiting as long again (40 s at most)'}"
            f" until {time.strftime('%H:%M:%S', time.localtime(E29['until']))}")
    return True


def hold_on():
    """A cooldown / error-29 hold is running: no Battle press, no GO, no re-open -- from anyone."""
    return cool_wait() or time.time() < E29["until"]


SLIP_BLIND_S = 10.0                                      # slip-in: one deploy with no "NOT in battle" reading behind it, at most
SLIP_GAP_S = 2.0                                         # this often; and never two deploy requests closer than this


def slip_go(sv, now, last_try):
    """Slip-in: send a deploy NOW? sv = the gym's latest reading from the tapper ([team, age ms, in battle, ...]) or None.
    A reading under 3 s old that says NOT in battle = the gap between the attacker's battles: go (2 s after the last
    request at the earliest). A reading that says IN BATTLE, or no fresh reading at all: only the one blind try every
    SLIP_BLIND_S. Returns (go, why)."""
    since = now - last_try
    fresh = bool(sv) and len(sv) > 2 and sv[1] is not None and sv[1] < 3000
    if fresh and not sv[2]:
        if since >= SLIP_GAP_S:
            return True, f"the server says NOT in battle ({sv[1] / 1000:.1f} s old reading)"
        return False, "the last request went out under 2 s ago"
    if since >= SLIP_BLIND_S:
        return True, ("a blind try: the server still says IN BATTLE" if fresh else "a blind try: no fresh reading of the gym")
    return False, ("the server says IN BATTLE" if fresh else "no fresh reading of the gym yet")


def drill(fid, enemy, g, sc, a, tick, until, refresh=None, join_near=None, cmd_waiting=None, counters=None):
    """Beat the gym in one continuous run until it is no longer an enemy gym. Returns its final team, None (gave up),
    or ABORT (a party screen was left open over a battle -- stop everything). counters(sv): re-pick the team from the
    gym's latest defenders before the next session."""
    opens = misses = backs = go_misses = hangs = 0
    noreport, live_at, lv, odd_since, his_said = None, 0.0, None, None, 0.0
    sess_t0 = None                                       # when the session in progress started (the session record)
    last_end, cps = g.ends.get(fid, 0), []               # the gym's total CP at each session end: is it moving?
    leaving = None                                       # STALL / DETOUR: finish the battle in progress, then leave
    dw = {"at": 0.0, "key": None, "seen": 0.0}               # drill watch: the gym's own state every 2 s
    while time.time() < until or g.in_battle():             # never walk away from a battle in progress
        if g.detached:
            raise Detached("game connection lost")
        tick()
        if g.prepstuck:
            return ABORT
        e29_seen(g, sc, fid)                                 # an error 29 is read HERE, whatever screen is up (never minutes later)
        if g.autoplaced == fid and fid in g.placed:          # a direct deploy went out and was answered: nothing left to beat
            return 0
        if not g.chain:
            time.sleep(0.3)
            continue
        if time.time() - dw["at"] > 2:                       # the user: nobody can ADD a defender while it is in battle -- verify
            dw["at"] = time.time()
            sc.exports_sync.scan([fid])
            _sv = sc.exports_sync.scanned().get(fid)
            if counters and _sv and _sv[1] < 4000:          # the next session's six: the counters to the defenders left NOW
                try:
                    counters(_sv)
                except Exception as e:
                    say(f"  (counter team: {e})")
            if _sv and _sv[1] < 4000 and dw["seen"] != round(time.time() * 1000 - _sv[1], -2):
                dw["seen"] = round(time.time() * 1000 - _sv[1], -2)
                _cpn = _sv[4] or 0                           # a defender LOST CP during our session = the server counts our battle
                if (sess_t0 or g.in_battle()) and dw.get("cp") and dw.get("team") == _sv[0] and 0 < _cpn < dw["cp"] * 0.98:
                    battles_count(fid, f"a defender lost CP in our battle ({dw['cp']} -> {_cpn} total)", sc,   # (its team refeeds it
                                  team=getattr(g, "last_team", None) if (sess_t0 and time.time() - sess_t0 >= 8) else None)
                                                             # (>= 8 s in: a refused battle is over after 4 s -- its six prove nothing)
                if a.one_by_one and g.in_battle() and dw.get("team") == _sv[0] and dw.get("n") and _sv[3] < dw["n"]:
                    _k = sc.exports_sync.obokeep()           # one-by-one: the first defender was KNOCKED OUT -- the next round's
                    say(f"    one-by-one: a defender was knocked out ({dw['n']} -> {_sv[3]}) -- "   # defender is the new first:
                        f"{'staying in for the new first one' if _k else 'too late for this battle'}")   # no exit (Benny 00:08)
                dw["cp"], dw["team"], dw["n"] = _cpn, _sv[0], _sv[3]   # (the SESSION total can stay flat: Ellis 23:31-23:41)
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
            sess_t0 = sess_t0 or time.time()
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
            if len(cps) > 1 and cps[-2] > 0 and not JUMPED["told"] and JUMPED["t"]:   # the server's answer = the cooldown CHECK
                if (cps[-2] - cps[-1]) * 100 >= 5 * cps[-2]:  # (a session that drains = the server counts our battles again)
                    battles_count(fid, "a battle session drained again", sc)
                elif cps[-1] >= cps[-2] and time.time() - JUMPED["t"] < 1800:   # (no defender lost CP in the whole session)
                    cool_sign("a battle session drained 0%")
                    leave_gym(g, sc, tick)
                    say(f"  the server's cooldown: session {len(cps)} drained 0% ({jump_since():.0f} s after "
                        f"{jump_desc()}) -- the next session checks again")
            if g.study_f:                                    # learn from every session: who fought, how long, how much it drained
                _cur = CT["cur"]
                g.study_f.write(json.dumps({"k": "study", "src": "session", "t": int(time.time() * 1000), "fid": fid, "n": len(cps),
                                            "cp_after": lv[7], "cp_before": cps[-2] if len(cps) > 1 else None,
                                            "secs": round(time.time() - sess_t0, 1) if sess_t0 else None,
                                            "team": getattr(g, "last_team", None),
                                            "counters": _cur["ids"][:6] if _cur and _cur["fid"] == fid else None}) + "\n")
                g.study_f.flush()
            sess_t0 = None
            if len(cps) >= 8:                                # ...but make sure progress is being made
                lo = min(cps)
                since = len(cps) - 1 - max(i for i, c in enumerate(cps) if c == lo)
                if since >= 6 and cps[-1] > lo * 1.3 and since % 6 == 0:   # no leaving: Benny 11-16 23:48 answered the old
                    say(f"  no new low at {fid[:8]} in {since} sessions (lowest {lo}, now {cps[-1]} CP) -- its team feeds/refills "
                        f"it between our rounds; drilling on (\"keep drilling\": their berry quota runs out first)")   # STALEMATE line: "keep drilling"
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
                if g.user_gym:                               # HIS gym screen (he opened another gym): never Back out of it
                    if time.time() - his_said > 30:          # (11-16 23:30:58 and 11-17 00:17:19: the drill pressed Back on him
                        his_said = time.time()               # one second after he opened his own gym -- his rule: never touch it)
                        say(f"  you have another gym open ({g.open_fid[:8]}) -- the drill of {fid[:8]} waits next to it; "
                            f"it goes on the moment you close it")
                    time.sleep(0.5)
                    continue
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
            if (g.prep or leaf == "GymApproachState") and not g.in_battle() and hold_on():
                time.sleep(0.3)                              # a cooldown / error-29 hold is on: no GO, no Battle from here either
                continue                                     # (00:33:17: this backup pressed Battle 4 s into the hold; no Back --
            if g.prep:                                       # the screen may be his). party screen: gym_tapper presses GO itself, once
                if not g.wait_for(lambda: g.in_battle() or not g.prep, 1.5, tick):   # not ours (left over from a restart)? GO on
                    sc.exports_sync.act("go")                # it now, not 12 s later
                if g.in_battle() or (g.wait_for(lambda: g.in_battle() or not g.prep, 12, tick) and g.in_battle()):
                    go_misses = 0
                elif not g.prep:                             # the party screen closed by itself (00:36:43): nothing to back out of,
                    continue                                 # no 12 s wait, no miss
                else:
                    go_misses += 1
                    say(f"  GO did not start a battle -- the game's back on the party screen (try {go_misses}/3)")
                    ch.adb("input keyevent 4")
                    g.wait_for(lambda: not g.prep, 4, tick)
                    if go_misses >= 3:
                        return None
                continue
            if leaf == "GymApproachState":                   # gym screen: the phone presses Battle itself; this only backs it up
                _up = lambda: g.prep or g.in_battle() or not g.has("GymState")   # (or the screen CLOSED under us: the game or a
                if not g.wait_for(_up, 4.0 if g.armed else 1.0, tick):          # hand shuts it 1-5 s after it opens, mostly right
                    sc.exports_sync.act("battle")                               # after an error 29 or a far jump -- 5 times in
                if not g.has("GymState"):                                       # 21 min on 11-17, each an 8-10 s wait, a Battle
                    continue                                                    # pressed into nothing and a miss toward giving
                g.wait_for(_up, 6, tick)                                        # the gym up. The map branch re-opens it.)
                if g.prep or g.in_battle():
                    misses = 0
                elif not g.has("GymState"):
                    continue
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
        if time.time() < E29["until"]:                       # the error-29 settle: no re-open, no Battle press
            time.sleep(0.3)
            continue
        if COOL["on"] and time.time() < COOL["until"]:        # no Battle press, no re-open: wait out the cooldown at the gym
            if not COOL["said"]:
                COOL["said"] = True
                autobattle(sc, g, False)
                say(f"  waiting out the cooldown at {fid[:8]} until {time.strftime('%H:%M:%S', time.localtime(COOL['until']))} "
                    f"-- then one check")
            time.sleep(0.5)
            continue
        if COOL["on"] or E29["n"] or getattr(g, "ab_off", False):   # the wait is up: ONE check (a Battle) -- its answer decides
            autobattle(sc, g, True)
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
    ap.add_argument("--one-by-one", action="store_true", help="drill the FIRST defender over and over: run away when the 2nd "
                                                               "defender's round starts and Battle again (Benny 11-16 23:58)")
    ap.add_argument("--direct-deploy", choices=("auto", "on", "off"), default="off",
                    help="after a win, send the place request straight from the map (no gym screen: under 1 s instead of ~3 s). "
                         "OFF unless Benny says go: direct GYM_DEPLOY requests were one of the things running in the hour before "
                         "the 09-26 lockout, and it has not worked (so has not been sent) since 0.431. auto = on unless its crash "
                         "guard turned it off (gym_state/direct_deploy_off.json); on = also forget that verdict and try again")
    ap.add_argument("--heal-batch", type=int, default=30, help="revive every fainted Pokemon once this many are fainted (0 = never)")
    ap.add_argument("--no-feed", dest="feed", action="store_false", help="never feed Golden Razz to your defenders")
    ap.add_argument("--no-battle", dest="battle", action="store_false", help="battle break: no gyms, keep moving and feeding the defenders")
    ap.add_argument("--route", default=None, help="battle break: walk these waypoints once (lat,lng;lat,lng;...), then circle the goal")
    ap.add_argument("--lap-every", type=int, default=0, help="while battling: after this many placements, walk --route once, then battle again")
    ap.add_argument("--start-lap-at", type=int, default=None, help="start inside a lap, at this --route waypoint index")
    ap.add_argument("--no-feed-mate", dest="feed_mate", action="store_false", help="do not also feed the strongest teammate in your gyms")
    ap.add_argument("--topup", action="store_true", help="Berry Master: regular berries to defenders in quiet gaps (never golden)")
    ap.add_argument("--no-topup", dest="topup", action="store_false", help="no Berry Master top-ups (overrides an earlier --topup)")
    ap.add_argument("--topup-reserve", type=int, default=30, help="keep at least this many of each regular berry")
    ap.add_argument("--attack-report", type=float, default=3.0,   # Benny 2026-09-30 ("Maybe middle ground?"): 3 s, was 1.5 -- 20 reports/min instead of 40
                    help="s between the battle's attack reports (server setting 5; 0 = leave it)")
    ap.add_argument("--cmd", default=None, help="live command file (JSON, re-read when it changes): {go: fid} / {hunt: meters}")
    ap.add_argument("--skip", default="", help="gym ids (8-char prefixes, comma-separated) to leave alone for this whole run")
    ap.add_argument("--join-first", default=None, help="fort id: go there first -- beat + place (enemy/empty) or join (red with room)")
    ap.add_argument("--study", default=None, help="append the feed-study JSON lines (gym readings, map flags, feed replies) here")
    ap.add_argument("--feed-zone", default=None, help="lat,lng,radius_m: feed only defenders in gyms inside this circle")
    ap.add_argument("--hop", default=None, help="areas to cycle by TELEPORT, 'lat,lng,radius;lat,lng,radius;...': once the current one has "
                    "had nothing to beat, join or guard for --hop-idle s, jump to the next and retake / fill its gyms (Benny 11-16: 'control all of them')")
    ap.add_argument("--hop-idle", type=float, default=45.0, help="seconds with nothing to do in an area before the next --hop area")
    ap.add_argument("--rscan", action="store_true",
                    help="--monitor: also read gyms OFF the game's map (other islands) by id. OFF: 11-16 23:14-23:19 the game "
                         "exited 3 times in 6 min with it on (no crash record) -- off-map reads were never run on this game build")
    ap.add_argument("--no-monitor", dest="monitor", action="store_false",
                    help="with --hop: walk/loop the areas instead of WATCHING every gym in them (gym details by id, any island) and "
                         "teleporting straight to the one that needs us (Benny 11-16 23:05: 'actively monitor the gyms rather than "
                         "waste time walking thru them all')")
    ap.add_argument("--next-goal", default=None, help="lat,lng: once you hold --hold gyms around --goal, go here (fast trip)")
    ap.add_argument("--next-area", type=float, default=170, help="radius (m) around --next-goal")
    ap.add_argument("--hold", type=int, default=6, help="gyms to hold around --goal before heading to --next-goal")
    ap.add_argument("--team", type=int, default=2, help="your team (2 = red): its gyms with a free slot are joined without a battle")
    ap.add_argument("--feed-at", type=float, default=0.34, help="feed a Golden Razz at this motivation or less (the last third)")
    ap.add_argument("--feed-hot", type=float, default=0.34, help="...or at this level when the gym was attacked in the last 5 min (the server allows ~10 berries per defender, so a buffer burns them)")
    a = ap.parse_args()
    USER_SKIP.update(x.strip()[:8] for x in a.skip.split(",") if x.strip())
    enemy = [int(x) for x in a.enemy.split(",")]
    goal = [float(x) for x in a.goal.split(",")]               # a list: the next-goal switch survives a re-attach
    HOP["list"] = [tuple(float(v) for v in w.split(",")) for w in a.hop.split(";") if w.strip()] if a.hop else []
    a.monitor = bool(a.monitor and HOP["list"])
    if HOP["list"]:
        greg_load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gym_state", "gym_registry.json"))
        say(f"  HOP areas ({len(HOP['list'])}): " + "; ".join(f"{x[0]:.4f},{x[1]:.4f} r{x[2]:.0f}" for x in HOP["list"])
            + (f" -- MONITOR: every gym in them is read every 12-45 s (by id, any island); the runner stands still and teleports "
               f"straight to the gym that needs it ({len(GREG['g'])} gyms known)" if a.monitor else
               f" -- the next one after {a.hop_idle:.0f} s with nothing to beat, join or guard"))
    mv, done, t_start = Mover(a.speed, a.travel_speed), {}, time.time()
    while time.time() - t_start < a.minutes * 60:            # re-attach and carry on if the game connection drops
        g = Game()
        try:
            run(a, g, mv, done, t_start, enemy, goal)
            return
        except (Detached, frida.InvalidOperationError, frida.TransportError, frida.ServerNotRunningError) as e:
            say(f"lost the game connection ({type(e).__name__}: {e}) -- re-attaching in 3 s")
            dd_said(dd_guard())
            time.sleep(3)
        except Exception as e:                               # never die: a relaunched / recovering game is re-attached by itself
            say(f"session failed ({type(e).__name__}: {e}) -- retrying in 10 s")
            dd_said(dd_guard())
            time.sleep(10)


def dd_said(why):
    if why:
        say(f"  !! direct deploy OFF from here on: {why}. The gym screen places again (as in every run before 11-17). "
            f"If you closed the game yourself, '--direct-deploy on' turns it back on")


def run(a, g, mv, done, t_start, enemy, goal):
    """One attached session: attach, install, then walk/battle until the time is up or a STOP."""
    pg.wait_ready_to_attach(timeout_s=300, min_age_s=45)
    pg.busy_acquire = lambda *_a, **_k: None                 # the marker is advisory: get_session must never wait / refuse (phone_mark)
    sess, pid = pg.get_session()
    sc = sess.create_script(gt.JS)
    sc.on("message", g.on_msg)
    sess.on("detached", lambda *args: (setattr(g, "detached", True), DD.__setitem__("gone_at", time.time())))
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
    _pf = os.path.join(os.path.dirname(a.study) if a.study else HERE, "pick_handler.json")   # a place handler learned in an earlier run
    try:
        _pl = json.load(open(_pf, encoding="utf-8")).get("name")
    except Exception:
        _pl = None
    if _pl and _pl in (r.get("pickNames") or []) and _pl != r.get("pickName"):
        _pr = sc.exports_sync.pickname(_pl)
        if _pr.get("ok"):
            r["autoplace"], r["pickName"], r["pickWhy"] = True, _pl, "learned from a placement in an earlier run"
    g.pick_file = _pf
    say("  auto-place: " + (f"ON -- place handler {r.get('pickName')}: {r.get('pickWhy')}" if r.get("autoplace")
                            else "OFF -- Deploy opens the list for you") + f" | shape matches {r.get('pickNames')}, deploy replies {r.get('deployCbNames')}")
    _gr = r.get("graph") or {}                               # the live service graph (H01, 2026-09-29): which one, and how fresh
    say(f"  live service graph: {_gr.get('graphs', '?')} ItemBagImpl graph(s), inventory last updated "
        + (f"{(time.time() * 1000 - _gr['ts']) / 1000:.0f} s ago" if (_gr.get("ts") or -1) > 0 else "(unreadable)")
        + (f"; older graphs at {_gr['other']} -- the game rebuilt its services in-process, reading the newest" if _gr.get("other") else ""))
    for _gn in r.get("graphNotes") or []:
        say(f"  !! live graph: {_gn}")
    try:                                                     # same-type bonus: what install() resolved + the game master's typing table
        stab_setup(sc, g, r)
    except (Detached, frida.InvalidOperationError, frida.TransportError, frida.ServerNotRunningError):
        raise                                                # a dropped game connection keeps its own re-attach path
    except Exception as e:                                   # STAB is an extra: an odd game master file must not abort the session (main() would re-attach + re-run install() every 10 s)
        say(f"  !! STAB setup failed ({type(e).__name__}: {e}) -- running with the old (non-STAB) pick")
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
    if TEAM_BAN:                                             # a re-attach installs a fresh tapper: hand it this run's bans again
        say(f"  out of every team for this run ({len(TEAM_BAN)}): the tapper has them again ({sc.exports_sync.ban(list(TEAM_BAN))})")
    _ddok, _ddwhy = dd_state(a.direct_deploy)                # the tapper keeps direct deploy OFF until this call says otherwise
    _ddr = sc.exports_sync.directdeploy(bool(_ddok and a.autoplace))
    say("  direct deploy " + (f"allowed (parts found: {_ddr.get('parts')}): the tapper builds its request sender on the plain map -- "
                              f"READY / NOT available follows" if _ddr.get("on") else
                              f"OFF ({_ddwhy or '--no-autoplace'}): the gym screen places"))
    if a.one_by_one:                                         # Benny 11-16 23:58: "drill at the first one over and over"
        say(f"  ONE-BY-ONE mode {'ON' if sc.exports_sync.onebyone(True) else 'NOT SET'}: beat the first defender, run away at the "
            f"2nd defender's round, Battle again -- the counters are picked against the first defender only")
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
    dep = {"n": None, "at": 0.0, "gy": [], "ro": [], "dp": [], "fa": [], "fb": []}   # deployed, Gyarados, roster, defenders, fainted -- OFF the critical path

    def refresh_deployed(force=False, every=600):
        """The live bag: which gyms hold one of yours (`mine`), the placement stock, the roster. Every 10 min, after each
        placement, and every `every` s while idle -- 11-17 00:27: a Gyarados knocked out of a gym still counted as "in it"
        for up to 10 min, so that gym was never joined ("you need a lot more situational awareness")."""
        if force or dep["n"] is None or time.time() - dep["at"] > every:
            _was = (dep["n"], sorted(str(x[5]) for x in dep["dp"] if len(x) > 5),
                    sorted(str(x[0]) for x in dep["gy"] if x[2] >= x[3]))
            _quiet = not force and every < 600 and dep["n"] is not None   # the idle re-read speaks only when something changed
            try:
                dep["n"], dep["gy"], dep["ro"], dep["dp"], dep["fa"] = bag_status(sess, sc)
                dep["at"] = time.time()
                if _quiet and _was == (dep["n"], sorted(str(x[5]) for x in dep["dp"] if len(x) > 5),
                                       sorted(str(x[0]) for x in dep["gy"] if x[2] >= x[3])):
                    return
                if _quiet:
                    _gone = sorted(set(_was[1]) - {str(x[5]) for x in dep["dp"] if len(x) > 5})
                    if _gone:
                        say("  CAME HOME: yours left " + ", ".join(f"{f[:8]}{' (' + NAMES[f[:8]] + ')' if f[:8] in NAMES else ''}" for f in _gone)
                            + " -- those gyms can be joined or retaken again")
                dep["fb"] = placement_fallback(dep)            # no healthy Gyarados: these go in, never an open gym
                top = ", ".join(f"{cp}{'' if hp >= mx else (' (fainted)' if hp <= 0 else ' (hurt)')}" for _, cp, hp, mx in dep["gy"][:5])
                say(f"  your Pokemon in gyms right now: {dep['n']}/{a.max_deployed}; shiny Gyarados ready to place (CP): {top} (live bag)")
                if dep["fb"]:
                    say("  if no Gyarados is at full HP, these go in at once (never a gym left open): " + ", ".join(f"{x[4]} {x[1]}" for x in dep["fb"][:5]))
                g.names = {x[0]: f"{x[4]} {x[1]}" for x in BAG_RO_ALL}   # every fighter (a counter outside the top 80 had no name)
                g.names.update({x[0]: f"{x[4]} {x[1]}" for x in dep["ro"]})
                g.names.update({x[0]: f"Gyarados {x[1]}" for x in dep["gy"]})
                g.names.update({x[0]: f"{x[2]} {x[1]} (fused part)" for x in BAG_COMP})
                _ck = tuple(x[0] for x in BAG_COMP)
                if BAG_COMP and getattr(g, "comp_said", None) != _ck:
                    g.comp_said = _ck
                    say(f"  {len(BAG_COMP)} Pokemon fused into a White / Black Kyurem are left out of every team (the server refuses a "
                        f"battle with one in the six -- error 29): " + ", ".join(f"{x[2]} {x[1]}" for x in BAG_COMP))
                g.names.update({x[0]: f"{x[2]} {x[1]}" for x in dep["dp"]})
                nfa = len(dep["fa"])
                batch = [x[0] for x in dep["fa"]] if a.heal_batch and nfa >= a.heal_batch and not g.batch_active else []   # none until 30 fainted
                g.names.update({x[0]: f"{x[2]} {x[1]}" for x in dep["fa"]})
                _its = getattr(g, "items", None) or {}
                _rev = _its.get("MaxRevive", 1) + _its.get("Revive", 0)   # (unknown until the tapper's first item read: assume some)
                gyfix = [x[0] for x in dep["gy"] if x[2] < x[3] and (x[2] > 0 or _rev > 0)] if a.heal_top else []   # 11-17 00:30:
                if gyfix:                                    # three shiny Gyarados knocked out of gyms waited for the 30-fainted
                    say(f"  reviving + healing {len(gyfix)} shiny Gyarados back from gyms now, so they can be placed: "   # batch
                        + ", ".join(f"{cp} ({hp}/{mx} HP)" for _id, cp, hp, mx in dep["gy"] if _id in gyfix))   # (--heal-top)
                _dead = [x for x in dep["gy"] if x[2] <= 0 < x[3]]
                if _dead and _rev <= 0 and not getattr(g, "norev_said", False):
                    g.norev_said = True
                    say(f"  !! NO REVIVES in the bag: {len(_dead)} fainted shiny Gyarados ({', '.join(str(x[1]) for x in _dead)}) wait -- "
                        f"your highest-CP shinies go in instead")
                rr = sc.exports_sync.roster(roster_ids(dep), a.heal_top, batch + [x for x in gyfix if x not in batch],
                                            [x[0] for x in dep["gy"]])   # this gym's counters first
                up = ([x for x in dep["ro"] if x[2] * 2 >= x[3]] + [x for x in dep["ro"] if 0 < x[2] and x[2] * 2 < x[3]])[:6]
                say(f"  attack team = {'best rank' if RANK['score'] else 'highest CP'} with HP left, no Slaking, no Regigigas, no placement Gyarados: "
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
    rank_load(os.path.join(os.path.dirname(a.cmd), "attack_rank.json") if a.cmd else None, first=True)
    refresh_deployed(True)
    rank_say(dep["ro"])

    ROUTE = [tuple(float(v) for v in w.split(",")) for w in a.route.split(";")] if a.route else []
    route_i = [0 if a.start_lap_at is None else a.start_lap_at]
    lap = {"active": bool(ROUTE) and (not a.battle or a.start_lap_at is not None), "placed": 0}   # the user's cycle: N gyms, a lap, repeat
    if ROUTE:
        say(f"  route of {len(ROUTE)} waypoints, {sum(ch.meters(x, y) for x, y in zip(ROUTE, ROUTE[1:])) / 1000:.1f} km, at {a.speed} km/h")

    def retry_lockout(fid):                                  # refused for a deploy lockout: wait it out, place again -- until it lands
        """Two lockouts refuse a deploy on a gym that was just emptied: the finisher's window (ErrorFortDeployLockout, "Battle
        winners have priority", ~23-30 s) and OUR team's lockout on a gym it just lost (ErrorTeamDeployLockout, "The Gym is
        under attack! Try again later."). 11-16 22:35, the Ellis Island ferry gym: refused twice 23 s apart, then Deploy was
        opened by hand and blue placed Walrein at 22:36:09 (Benny: "thats a common situation id like you to figure out").
        Wait for BOTH map lockouts ([8] finisher, [9] same team), try again, and keep at it for up to 3 min while the gym
        stays empty. The moment another team places, return False: the caller battles it NOW (1 defender)."""
        t_stop, tries = time.time() + 180, 0
        while time.time() < t_stop:
            try:
                lv = sc.exports_sync.teams().get(fid) or []
            except Exception:
                lv = []
            fin = lv[8] / 1000.0 if len(lv) > 8 and lv[8] else 0.0
            own = lv[9] / 1000.0 if len(lv) > 9 and lv[9] and LAST_TEAM.get(fid) == a.team else 0.0   # the SAME-team lockout binds
            # only the team that held it -- 11-17 00:39 it waited 60 s on blue's lockout at 9c126dbd and Benny placed by hand 25 s in
            wait = min(60.0, max(fin, own, 2.0 if tries else 0.0) + 0.3)
            why = "your team is locked out of it after losing it" if own >= fin and own > 0 else "the finisher's window"
            say(f"  deploy lockout ({why}) -- try {tries + 2} in {wait:.1f} s (at once if a team places)")
            t_end = time.time() + wait
            while time.time() < t_end:                       # Benny 11-16: the moment ANOTHER team places, battle it (it has 1 defender)
                try:
                    _tm = (sc.exports_sync.teams().get(fid) or [None])[0]
                except Exception:
                    _tm = None
                if _tm not in (0, None):
                    sc.exports_sync.scan([fid])              # its new defender: the counter team is picked before the Battle
                    return False                             # somebody placed: the placement loop below sees the new team at once
                g.wait_for(lambda: False, 0.5, tick)
            if not (g.open_fid == fid and g.leaf() == "GymApproachState"):
                sc.exports_sync.open(fid)                    # the gym screen closed meanwhile: open it again
                if not g.wait_for(lambda: g.open_fid == fid and g.leaf() == "GymApproachState", 8, tick):
                    return False
            if g.gym_team not in (0, None):
                return False
            g.deploy_refused, g.autoplaced_id = None, None
            g.placed.pop(fid, None)
            sc.exports_sync.autodeploy(fid, place_ids(dep), False, a.team)
            if not g.wait_for(lambda: fid in g.placed and g.autoplaced_id and g.placed[fid].get("id") == g.autoplaced_id, 20, tick):
                return False
            if g.placed[fid].get("ok"):
                return True
            if "Lockout" not in str(g.placed[fid].get("res", "")):
                return False                                 # refused for another reason: no use waiting
            tries += 1
        say("  still locked out after 3 min -- moving on (it is judged again at once)")
        return False

    def retry_join(fid, why):                                # a red gym WITH ROOM refused the join: the server's cooldown
        """ErrorFortIsFull from a gym the game's own details show with room = the server does not trust the position yet (the
        cooldown after a jump -- the client does not hold it, only the server's answers show it). Bartholdi 22:03: refused right
        after the 8.8 km jump, accepted 7 min later; Castle Williams 22:53: refused after a fast 819 m move, Benny placed by hand
        28 s later; Brooklyn Sign 23:14: refused 4 times within 25 s of a 595 m jump. So: ask again on every map refresh of
        the game (GMO, 5 s -- a client value, not a guess) while the gym has room, log when the server accepts (the measured
        cooldown for that jump), and stop the moment he takes the screen."""
        t_first = time.time()
        for _try in range(36):                               # 36 refreshes x 5 s = the 3-min bound of the lockout retry
            if g.user_gym or (g.has("GymState") and g.open_fid not in (None, fid)):
                sc.exports_sync.autodeploy(None)             # his screen now (review 11-16): never Back out of it, never place on it
                return False
            try:
                lv = sc.exports_sync.teams().get(fid)
                sv = sc.exports_sync.scanned().get(fid)
            except Exception:
                lv, sv = None, None
            n_now = sv[3] if (sv and sv[1] < 60000 and sv[0] == a.team) else None
            if n_now is None and lv and lv[0] == a.team and len(lv) > 5 and lv[5] >= 0:
                n_now = 6 - lv[5]
            if n_now is None or n_now >= 6 or (dep["n"] is not None and dep["n"] >= a.max_deployed):
                return False
            _sj = jump_since() or (time.time() - JUMPED["t"])
            say(f"  {why} from a red gym with {n_now} defender(s) -- the server's cooldown "
                f"({_sj:.0f} s after {jump_desc()}): asking again on the game's next map refresh (5 s), ask {_try + 2}")
            g.wait_for(lambda: False, 5.0, tick)             # GMO refresh: the client's own map interval (game_limits, 5 s)
            if g.user_gym or (g.has("GymState") and g.open_fid not in (None, fid)):
                sc.exports_sync.autodeploy(None)
                return False
            if not (g.open_fid == fid and g.leaf() == "GymApproachState"):
                sc.exports_sync.open(fid)
                if not g.wait_for(lambda: g.open_fid == fid and g.leaf() == "GymApproachState", 10, tick):
                    return False
            g.deploy_refused, g.autoplaced_id, g.autoplaced = None, None, None
            g.placed.pop(fid, None)
            sc.exports_sync.autodeploy(fid, place_ids(dep), True, a.team)
            if g.wait_for(lambda: g.autoplaced == fid, 6, tick) and \
               g.wait_for(lambda: fid in g.placed and g.autoplaced_id and g.placed[fid].get("id") == g.autoplaced_id, 17, tick):
                if g.placed[fid].get("ok"):
                    battles_count(fid, "the server accepted the join", sc, {"refused_for_s": round(time.time() - t_first, 1)})
                    return True
                why = str(g.placed[fid].get("res", "no answer"))
                if re.search(r"SameKind|AlreadyHas|Disabled|TooMany|Lockout", why):
                    return False                             # a real reason: no use trying again now
            else:
                why = "no answer"
        return False

    def force_join(fid, budget_s=25.0):
        """Slip a Pokemon into a red gym with room while another team attacks it. Benny 11-17 00:42-00:44: "figure out how to
        force my pokemon in this gym we're at" / "watch these lockouts and slip my pokemon in there fast ... the ppl battling
        have to stop for a moment when they complete the cycle". The server refuses red deploys while the gym is in battle
        (ErrorTeamDeployLockout, "The Gym is under attack!"), but every attacker's battle stops between rounds and sessions
        (0.435: one server battle per defender). So WATCH the gym (its own details, read every second -- the reads the
        drill already makes) and deploy the moment a reading says NOT in battle: that request lands in the gap. While
        the readings say IN BATTLE no deploy goes out -- it would only be refused -- except one blind try every
        SLIP_BLIND_S (the flag can lag); never more than one deploy request per 2 s. (The first cut sent a deploy every
        second whatever the gym said: a stream of refused requests, on an account with the 09-26 lockout behind it.)
        Every answer is logged to slip_in.jsonl with the readings. True = in; False = no longer possible (fell, full,
        ours in, his screen, no stock); None = budget used (the main loop looks around, then comes back)."""
        t_stop, n_try, last_res, last_try, told = time.time() + budget_s, 0, "", 0.0, 0.0
        refresh_deployed(every=10)
        while time.time() < t_stop:
            try:
                lv = sc.exports_sync.teams().get(fid) or []
            except Exception:
                lv = []
            if not lv or lv[0] != a.team:
                return False                                 # it fell / turned: the main loop fights for it
            if len(lv) > 5 and lv[5] <= 0:
                return False                                 # full
            if fid in {x[5] for x in dep["dp"] if len(x) > 5} or (dep["n"] is not None and dep["n"] >= a.max_deployed):
                return False
            if not place_ids(dep) or stop_req[0] or g.in_battle():
                return None
            if g.user_gym and g.has("GymState") and g.open_fid not in (None, fid):
                return False                                 # his screen: never touch it
            sv = None
            try:
                sc.exports_sync.scan([fid])                  # the gym's own state, fresh (a read)
                sv = sc.exports_sync.scanned().get(fid)
            except Exception:
                pass
            go, why_go = slip_go(sv, time.time(), last_try)
            if not go:
                if time.time() - told > 10:
                    told = time.time()
                    say(f"  slip-in at {fid[:8]}: {why_go} -- no deploy now, watching for the gap between their battles")
                g.wait_for(lambda: False, 1.0, tick)
                continue
            if not (g.open_fid == fid and g.leaf() == "GymApproachState"):
                sc.exports_sync.open(fid)
                if not g.wait_for(lambda: g.open_fid == fid and g.leaf() == "GymApproachState", 6, tick):
                    g.wait_for(lambda: False, 1.0, tick)
                    continue
            if g.gym_team not in (None, a.team):
                return False
            g.deploy_refused, g.autoplaced_id, g.autoplaced = None, None, None
            g.placed.pop(fid, None)
            t_try = last_try = time.time()
            sc.exports_sync.autodeploy(fid, place_ids(dep), True, a.team)
            n_try += 1
            got = g.wait_for(lambda: g.autoplaced == fid, 3, tick) and \
                g.wait_for(lambda: fid in g.placed and g.autoplaced_id and g.placed[fid].get("id") == g.autoplaced_id, 6, tick)
            ok = bool(got and g.placed[fid].get("ok"))
            res = "Success" if ok else (str(g.placed[fid].get("res", "")) if got else "no answer")
            try:
                with open(SLIP_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"t": round(t_try, 2), "fid": fid[:8], "try": n_try, "ok": ok, "res": res, "why": why_go,
                                        "scan_ib": bool(sv[2]) if sv else None, "scan_age_ms": sv[1] if sv else None,
                                        "answer_s": round(time.time() - t_try, 2), "ib": lv[6] if len(lv) > 6 else None,
                                        "lock_ms": lv[8] if len(lv) > 8 else None, "team_lock_ms": lv[9] if len(lv) > 9 else None,
                                        "slots": lv[5] if len(lv) > 5 else None}) + "\n")
            except Exception:
                pass
            if ok:
                dep["n"] = (dep["n"] or 0) + 1
                STATS["placed"] += 1
                STATS["joins"] = STATS.get("joins", 0) + 1
                LAST_ACT.update(t=time.time(), pos=act_pos(fid) or LAST_ACT.get("pos"))
                say(f"  SLIPPED IN: {g.names.get(g.placed[fid]['id'], 'a Pokemon') if hasattr(g, 'names') else 'a Pokemon'} is in "
                    f"{fid[:8]}{' (' + NAMES[fid[:8]] + ')' if fid[:8] in NAMES else ''} on try {n_try} -- {dep['n']}/{a.max_deployed} in gyms")
                refresh_deployed(True)
                return True
            if re.search(r"SameKind|AlreadyHas|Disabled|TooMany|IsFull|NotInRange|OutOfRange", res):
                say(f"  slip-in at {fid[:8]} stopped: {res}")
                if "AlreadyHas" in res:
                    refresh_deployed(True)
                return False
            if res != last_res or n_try % 5 == 1:
                say(f"  slip-in try {n_try} at {fid[:8]} ({why_go}): {res} -- watching for the next gap between their battles")
                last_res = res
            g.wait_for(lambda: False, 1.0, tick)
        return None

    def join_after_loss(fid):                                # a gym we fought for turned red without us and still has room: JOIN it
        def room():
            try:
                lv = sc.exports_sync.teams().get(fid)
            except Exception:
                return None
            return lv if (lv and lv[0] == a.team and len(lv) > 5 and lv[5] > 0 and (dep["n"] is None or dep["n"] < a.max_deployed)) else None
        lv = room()
        if not lv:
            return False
        say(f"  {fid[:8]} is red without us and has {lv[5]} free slot(s) -- joining it NOW (and again the moment the server "
            f"says it is NOT in battle)")
        _fj = force_join(fid, budget_s=40.0)                 # 11-17 00:39: the 35 s wait for blue's lockout let Benny place first
        if _fj is not None:
            return bool(_fj)
        t0 = time.time()
        while time.time() - t0 < 35:                         # its same-team deploy lockout (v[9]) must run out first
            lv = room()
            if not lv:
                say("  the gym filled up while we waited -- moving on")
                return False
            if not (len(lv) > 9 and lv[9] > 0):
                break
            if int(time.time() - t0) % 10 == 0:
                say(f"  waiting out the deploy lockout ({time.time() - t0:.0f} s of 35)")
            g.wait_for(lambda: False, 1.0, tick)
        else:
            say("  the lockout did not end within 35 s -- trying anyway")
        for _try in range(2):
            if not room():
                return False
            g.deploy_refused, g.autoplaced_id, g.autoplaced = None, None, None
            g.placed.pop(fid, None)
            sc.exports_sync.autodeploy(fid, place_ids(dep), True, a.team)
            if not (g.open_fid == fid and g.leaf() == "GymApproachState"):
                sc.exports_sync.open(fid)
                g.wait_for(lambda: g.open_fid == fid and g.leaf() == "GymApproachState", 10, tick)
            if g.wait_for(lambda: g.autoplaced == fid, 6, tick) and                g.wait_for(lambda: fid in g.placed and g.autoplaced_id and g.placed[fid].get("id") == g.autoplaced_id, 17, tick)                and g.placed[fid].get("ok"):
                dep["n"] = (dep["n"] or 0) + 1
                STATS["placed"] += 1
                say(f"  you joined {fid[:8]} with {g.names.get(g.placed[fid]['id'], 'a Pokemon') if hasattr(g, 'names') else 'a Pokemon'} "
                    f"({dep['n']}/{a.max_deployed} in gyms now) -- next gym")
                return True
            if g.deploy_refused and g.deploy_refused[0] == fid and re.search(r"SameKind|AlreadyHas|Disabled", g.deploy_refused[1]):
                say(f"  a Gyarados cannot go into {fid[:8]} ({g.deploy_refused[1]}) -- moving on")
                return False
            if g.deploy_refused and "Lockout" in g.deploy_refused[1]:
                say("  still locked out -- waiting once more")
                g.wait_for(lambda: False, 8.0, tick)
                continue
            break
        say(f"  could not join {fid[:8]} -- moving on")
        return False

    def batch_check():                                       # the user's rule: no heals until 30 fainted, then ALL of them at once
        n, ids = g.fainted
        dep["nfa"] = n
        if a.heal_batch and n >= a.heal_batch and dep["ro"] and not g.batch_active:
            g.batch_active = True
            sc.exports_sync.roster(roster_ids(dep), a.heal_top, ids, [x[0] for x in dep["gy"]])
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
        else:                                                # any other gym open at start (red, or a battle whose gym we cannot
            g.user_gym = True                                # read yet) is YOURS: a graceful restart leaves its own gym first.
                                                             # Never Back out of it, never walk off from it (11-16 23:00 / 23:08)
    last_tick = [0.0]
    scan_at, scan_said, scan_logged, scan_seen = [0.0], {}, {}, {}
    rscan_at, rscan_warned, idle_anchor = [0.0], [False], [None]   # --monitor: last remote sweep / told it is missing / where we stand
    user_anchor = [None]                                     # where we stand while YOUR gym is open
    rscan_sent = {}                                          # --monitor: fid -> when its last remote reading was asked

    def _land(lat, lng, r, fid=None):
        """After a TELEPORT: go on the moment the joystick fix is there AND the game's map shows that island's gyms (or the
        target gym) -- no fixed wait. 10 s is only the give-up bound."""
        t0 = time.time()

        def ready():
            q = ch.fix()
            if not q or ch.meters(q[:2], (lat, lng)) > 30:
                return False
            lvv = sc.exports_sync.teams()
            if fid:
                return fid in lvv and lvv[fid][1] < 5000
            return any(v[1] < 5000 and ch.meters((v[2], v[3]), (lat, lng)) <= r for v in lvv.values())
        ok = g.wait_for(ready, 10, tick)
        say(f"    landed: {'map ready' if ok else 'map NOT ready'} {time.time() - t0:.1f} s after the teleport")
        return ok
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
        if RANK["path"] and rank_load(RANK["path"]) and BAG_RO_ALL:    # attack_rank.json changed: re-sort the last walk, hand the tapper the new roster
            dep["ro"] = rank_sort(BAG_RO_ALL)[:80]
            try:
                if CT["cur"]:
                    CT["cur"]["at"] = 0                      # a new ranking: the counters are re-scored at the next reading
                sc.exports_sync.roster(roster_ids(dep), a.heal_top, [], [x[0] for x in dep["gy"]])
            except Exception as e:
                say(f"  (new attack rank not handed to the tapper: {e})")
            rank_say(dep["ro"])
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
                a.topup = bool(_q["topup"])                  # kept across a re-attach (see the inbox command)
                _tu = sc.exports_sync.topup(a.topup, a.topup_reserve)
                say(f"  COMMAND topup: {'ON' if _tu.get('on') else 'OFF'}")

    def urgent_cmd():                                        # a queued command that should end a drill
        pull()
        return g.graph_stale or any(set(c) & {"go", "hunt", "stop", "spin", "lap", "skip"} for c in cmdq)

    def tick():                                              # keep circling the current gym while waiting on it
        quick_cmds()
        feed_record()
        _oran = getattr(g, "obo_ran", 0.0)
        if a.one_by_one and g.top == "ModalDialog" and 1.0 < time.time() - _oran < 8 and getattr(g, "obo_ok", 0.0) < _oran:
            g.obo_ok = g.obo_last_tap = time.time()          # our run-away's prompt is up and no Open signal came: tap now
            g.obo_taps = 1
            threading.Thread(target=ch.adb, args=(OBO_OK_TAP,), daemon=True).start()
            say("    one-by-one: OK on the give-up prompt (tap 1, no Open signal -- fallback)")
        if a.one_by_one and g.top == "ModalDialog" and getattr(g, "obo_ok", 0.0) > getattr(g, "obo_ran", 0.0):
            _w = time.time() - getattr(g, "obo_last_tap", 0.0)   # the give-up prompt is still up after our tap: another
            if _w > 0.8 and getattr(g, "obo_taps", 1) < 3:      # tap 0.8 s later (a tap on a closed prompt only lands on
                g.obo_taps = getattr(g, "obo_taps", 1) + 1      # the battle = one fast attack), 3 at most, never another run-away
                g.obo_last_tap = time.time()
                threading.Thread(target=ch.adb, args=(OBO_OK_TAP,), daemon=True).start()
                say(f"    one-by-one: the give-up prompt is still up -- tap {g.obo_taps} on OK")
            elif _w > 2 and getattr(g, "obo_taps", 1) >= 3:
                a.one_by_one = False
                sc.exports_sync.onebyone(False)
                say("  !! one-by-one OFF: the give-up prompt stayed up after 3 taps -- normal battles from here; the prompt is yours")
        if getattr(g, "ab_off", False) and not hold_on():   # a hold that ended ANYWHERE gives the tapper its Battle press back
            autobattle(sc, g, True)
        _dok = getattr(g, "deploy_ok_at", 0.0)              # the server accepted a deploy (ours or his, by hand) after the
        if _dok > max(COOL["ok_seen"], JUMPED["t"]) and (COOL["on"] or not JUMPED["told"]):   # last jump: no cooldown now
            COOL["ok_seen"] = _dok
            battles_count(getattr(g, "open_fid", None), "the server accepted a deploy", sc)
        elif _dok > LAST_ACT["t"]:                           # every accepted deploy is a counted action: the next jump's
            LAST_ACT.update(t=_dok, pos=act_pos(getattr(g, "open_fid", None)) or LAST_ACT.get("pos"))   # cooldown runs from it
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
        pull()                                               # commands are read on EVERY pass: with no GPS fix, or your gym open, the
        if not g.in_battle() and not g.prep and any(_c.get("stop") for _c in cmdq):   # loop below never got to them (11-15: a stop sat 6 min)
            if g.has("GymState") and not g.user_gym:
                leave_gym(g, sc, tick)
            say("  COMMAND stop: no battle in progress -- stopped cleanly; the tapper unloads and the session detaches now")
            return
        p = ch.fix()
        if not p:
            if said != "nofix":
                say("  no GPS fix from the joystick (stopped, or a teleport?) -- waiting for one; commands still work")
                said = "nofix"
            time.sleep(1)
            continue
        here = p[:2]
        sc.exports_sync.pos(here[0], here[1])                # (the direct deploy sends the player's position)
        mv.fast = ch.meters(here, goal) > a.area                 # the far trip only: normal speed once inside the goal area
        if g.has("GymState") and g.user_gym:                 # the user opened a gym
            _of, _lv = g.open_fid, None
            try:
                _lv = sc.exports_sync.teams().get(_of) if _of else None
            except Exception:
                _lv = None
            if _lv and _lv[0] in enemy and not _lv[4] and (_of[:8] not in USER_SKIP):   # Benny 11-16 23:10: "you need to start with
                g.user_gym = False                           # the gym im at right now" -- his open ENEMY gym is OUR target: drill it
                done.pop(_of, None)                          # from here (counters, every Battle press, a Gyarados when it falls)
                TAKEN.pop(_of, None)
                target, gpos_now[0], said, user_anchor[0] = (_of, (_lv[2], _lv[3]), _lv[0]), None, None, None
                say(f"  you opened {_of[:8]}{' (' + NAMES[_of[:8]] + ')' if _of[:8] in NAMES else ''} (team {_lv[0]}) -- taking it "
                    f"over: drilling it from here, then a Gyarados in")
                continue
            if said != "user-gym":
                say("  you have a gym open -- standing still next to it until you leave it")
                said = "user-gym"
            HOP["idle"] = None                               # you are playing HERE: never --hop you away from it
            if user_anchor[0] is None:                       # NEVER walk you away from your gym (Benny 11-16 23:12, after the
                user_anchor[0] = (_lv[2], _lv[3]) if _lv else (here[0], here[1])   # old code circled ITS target 160 m off)
            mv.orbit(user_anchor[0], here, r=10)
            time.sleep(1)
            continue
        user_anchor[0] = None
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
        _scn = sc.exports_sync.scanned()
        for f, sv in _scn.items():                           # [team, age ms, in battle, defenders, CP now, ours, motivations, name]
            if len(sv) > 7 and sv[7]:
                NAMES[f[:8]] = sv[7]
            if f in live and sv[1] < 30000:
                verified.add(f)
            if f in live and sv[1] < 45000 and not (len(live[f]) > 10 and live[f][10]
                                                    and live[f][10] > time.time() * 1000 - sv[1] + 2000):
                v = live[f]                                  # (never over a map record that changed AFTER this scan -- 11-16 22:36:
                                                             # a 34 s old "empty" scan hid blue's new Walrein: "drill it (team 0)")
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
        if a.monitor:                                        # --monitor: WATCH every gym of every --hop area, never walk through them
            _nowms = time.time() * 1000
            for f, v in live.items():                        # the game's own map: positions (and raids) of this island's gyms
                if v[1] < 60000 and hop_area((v[2], v[3])) is not None:
                    greg_note(f, v[2], v[3], True)
                    if v[4]:
                        GREG["raid"][f] = _nowms + v[4]
            for x in dep["dp"]:                              # your defenders' gyms: known positions on any island
                if len(x) > 5 and x[5] and hop_area((x[3], x[4])) is not None:
                    greg_note(x[5], x[3], x[4], False)
            greg_save()
            if a.rscan and time.time() - rscan_at[0] > 3:    # gyms off this island: by id + position, 12 s apart (45 s for a full red one)
                rscan_at[0] = time.time()
                _due = []
                for f, gr in GREG["g"].items():
                    if (f in live and live[f][1] < 20000 and ch.meters((gr[0], gr[1]), goal) <= a.area) or hop_area((gr[0], gr[1])) is None:
                        continue                             # (this island's gyms: the map + the 15 s park scan above)
                    sv = _scn.get(f)
                    ivl = 45000 if (sv and sv[0] == a.team and sv[3] >= 6 and not sv[2]) else 12000
                    if (not sv or sv[1] > ivl) and time.time() - rscan_sent.get(f, 0.0) > ivl / 1000.0:
                        _due.append([f, gr[0], gr[1]])       # (never re-asked sooner than its interval, even with no answer)
                        rscan_sent[f] = time.time()
                if _due:
                    _r = sc.exports_sync.rscan(_due)
                    if not _r.get("il") and not rscan_warned[0]:   # (a missing service right after attach is NOT permanent)
                        rscan_warned[0] = True
                        say("  MONITOR: this game build has no il2cpp string export -- off-map gyms are not read")
                        a.rscan = False
            for f, gr in GREG["g"].items():                  # their readings join the map as gyms we can pick and jump to
                if f in live and live[f][1] < 60000:
                    continue
                sv = _scn.get(f)
                if not sv or sv[1] > 45000 or hop_area((gr[0], gr[1])) is None:
                    continue
                live[f] = [sv[0], sv[1], gr[0], gr[1], max(0, int(GREG["raid"].get(f, 0) - _nowms)), 6 - sv[3], sv[2], sv[4], 0, 0, 0, 0]
        for f in live:                                       # gyms Benny said to skip: left alone for the rest of the run (a hard rest:
            if f[:8] in USER_SKIP and done.get(f, 0) < time.time() + 3600:   # never picked, not even with nothing else to beat)
                done[f] = time.time() + 12 * 3600
                TAKEN.pop(f, None)
        skip, _back = rested(done, TAKEN, _scn, enemy, time.time())
        for f, sv in _back:                                  # an enemy team holds a gym we emptied: no rest, it is a target now
            done.pop(f, None)
            TAKEN.pop(f, None)
            say(f"  {f[:8]} is team {sv[0]} again ({sv[3]} defender(s), {sv[4]} CP) -- no rest: it is a target now")
        mine = {x[5] for x in dep["dp"] if len(x) > 5}
        for _lf, _lv in live.items():                        # who held each gym last (an emptied gym's same-team lockout binds only them)
            if _lv[0]:
                LAST_TEAM[_lf] = _lv[0]

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
            if _cmd.get("skip"):                             # {"skip": "4232f472"} or a list: leave those gyms alone this run
                for _s in ([_cmd["skip"]] if isinstance(_cmd["skip"], str) else _cmd["skip"]):
                    USER_SKIP.add(str(_s)[:8])
                if target and target[0][:8] in USER_SKIP:
                    target = None
                say(f"  COMMAND skip: {sorted(USER_SKIP)} left alone for the rest of this run -- the nearest other gym next")
            if "feed" in _cmd:                               # {"feed": false}: no berries to defenders (Golden Razz + the regular fallback)
                a.feed = bool(_cmd["feed"])
                if not hasattr(a, "feed_mate0"):
                    a.feed_mate0 = a.feed_mate               # the start setting: feeding back ON restores it
                a.feed_mate = a.feed_mate0 and a.feed
                _fc = sc.exports_sync.feedcfg(a.feed, a.feed_at, a.feed_hot, a.feed_mate)
                say(f"  COMMAND feed: {'ON' if a.feed else 'OFF'} -- berries to your defenders {'on' if a.feed else 'stopped'} ({_fc})")
            if "topup" in _cmd:
                a.topup = bool(_cmd["topup"])                # kept: a re-attach after a game crash re-installs with THIS (11-16 22:38 it came back ON)
                _tu = sc.exports_sync.topup(a.topup, a.topup_reserve)
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
        if cmd_st["hunt"] and target is None and not g.in_battle():   # Benny 11-16 "find an easy gym": the hunt verifies gyms for ~5 s --
            g.wait_for(lambda: False, 0.3, tick)                       # wait for ITS pick; never grab the nearest gym meanwhile
            continue
        tv = live.get(target[0]) if target else None
        if target is None or target[0] in skip or not tv or tv[4] or not (tv[0] in enemy + [0] or slot(target[0], tv)):
            target, _was_resting = pick_any(enemy, skip, done, here, goal, live, a.detour, a.area, slot, time.time(),
                                            areas=HOP["list"] if a.monitor else None)   # an empty gym: straight to Deploy
            if target and _was_resting:                      # nothing else to beat: its rest ends now
                done.pop(target[0], None)
                TAKEN.pop(target[0], None)
                say(f"target {target[0][:8]} team {target[2]} (it was resting -- nothing else to beat), {ch.meters(here, target[1]):.0f} m away")
            elif target:
                say(f"target {target[0][:8]} team {target[2]}, {ch.meters(here, target[1]):.0f} m away")
        if not target:                                       # nothing to beat right now: keep moving
            gpos_now[0] = None
            refresh_deployed(every=30)                       # idle: which gyms still hold yours, read live (a knocked-out one = a
                                                             # gym to join or retake), and the Gyarados back from gyms get revived
            if not HOP.get("ready", True):                   # (11-17 00:32: "map NOT ready" after a jump read as "nothing here" --
                if any(v[1] < 5000 and ch.meters((v[2], v[3]), goal) <= a.area for v in live.values()) \
                        or time.time() - HOP.get("landed", 0.0) > 60:   # three island jumps in 21 s; the 60 s is only a give-up bound)
                    HOP["ready"] = True
                else:
                    if said != "landing":
                        say("  waiting for this island's gyms to show on the game's map -- no second jump on an empty map")
                        said = "landing"
                    time.sleep(1)
                    continue
            if ch.meters(here, goal) > a.area:
                mv.travel(goal, here)
                msg = "no enemy gym on the way yet -- walking toward the goal"
            else:
                soon = [(v[4], fid, (v[2], v[3])) for fid, v in live.items()          # a non-red gym whose raid ends soon:
                        if v[0] in enemy + [0] and 0 < v[4] <= a.prewait * 60000        # wait ON it, battle the second it ends
                        and ch.meters((v[2], v[3]), goal) <= a.area and fid not in skip]
                _hg = g.his_gym[0] if (g.his_gym and time.time() - g.his_gym[1] < 1800) else None
                guard = sorted(((f != _hg, f in mine, (6 - v[5]) if len(v) > 5 and v[5] >= 0 else 6, ch.meters(here, (v[2], v[3]))), f)
                               for f, v in live.items()                                             # a red gym being drained by another
                               if v[0] == a.team and f not in skip and not v[4]                     # team: stand at it -- the moment it
                               and ch.meters((v[2], v[3]), goal) <= a.area                          # falls we are in range to fight for
                               and ((len(v) > 6 and v[6]) or (len(v) > 9 and v[9] > 0)))           # it (11-16 22:35, the ferry gym).
                # Which one (11-17 00:27, "a lot more situational awareness"): the gym YOUR deploy was refused at first, then one
                # with NONE of yours (the moment the attack ends we join it -- one with yours gives us nothing), then the one
                # closest to falling (fewest defenders), then the nearest. 00:27 it stood at 8e12222d while 951dc951 fell.
                if soon:
                    left, sfid, spos = min(soon)
                    gpos_now[0] = None
                    mv.orbit(spos, here, r=orbit_r)
                    msg = f"in the goal area, nothing to beat now -- circling {sfid[:8]}, its raid ends in {left / 60000:.1f} min"
                elif guard:
                    gf = guard[0][1]
                    mv.orbit((live[gf][2], live[gf][3]), here, r=orbit_r)
                    _gw = ("you tried to place here" if gf == _hg else "yours is in it" if gf in mine
                           else "none of yours in it: we join the moment the attack ends")
                    msg = (f"in the goal area, nothing to beat -- standing by red {gf[:8]}{' (' + NAMES[gf[:8]] + ')' if gf[:8] in NAMES else ''} "
                           f"({_gw}): another team is attacking it; the second it falls we fight for it"
                           + (f" [{len(guard) - 1} more red gym(s) under attack]" if len(guard) > 1 else ""))
                    if gf not in mine and len(live[gf]) > 5 and live[gf][5] > 0 and not g.in_battle() \
                            and ch.meters(here, (live[gf][2], live[gf][3])) <= engage \
                            and (dep["n"] is None or dep["n"] < a.max_deployed) and not (g.user_gym and g.has("GymState")):
                        if msg != said:                      # room and none of yours: slip one in between the attacker's battles
                            say(msg)
                            said = msg
                        if force_join(gf) is not None:
                            said = None
                        time.sleep(0.3)
                        continue
                _undisc = [i for i in range(len(HOP["list"]))   # --monitor + --rscan: an island this run never saw on the map -> look once
                           if not any(gr[2] and hop_area((gr[0], gr[1])) == i for gr in GREG["g"].values())] if (a.monitor and a.rscan) else []
                _gy_ready = bool(place_ids(dep)) and (dep["n"] is None or dep["n"] < a.max_deployed) and not cool_wait()
                _cur_i = HOP["i"] if HOP["i"] is not None else (hop_area(tuple(goal)) or 0)
                if a.monitor and not a.rscan and not soon and not guard and _gy_ready and len(HOP["list"]) > 1 \
                        and len(HOP.setdefault("empty", set()) | {_cur_i}) < len(HOP["list"]):   # (every island empty: stay)
                    HOP["empty"].add(_cur_i)
                    _nx = (_cur_i + 1) % len(HOP["list"])
                    hl, hg, hr = HOP["list"][_nx]            # nothing to beat or fill HERE and a Gyarados to place: the next island
                    say(f">> NEXT ISLAND {_nx + 1}/{len(HOP['list'])}: nothing to beat or fill here and a Gyarados is ready -- "
                        f"teleporting to {hl:.5f},{hg:.5f}")
                    ch.api("TELEPORT", f"--ef lat {hl} --ef lng {hg}")
                    note_jump(ch.meters(here, (hl, hg)), (hl, hg))
                    goal[:] = [hl, hg]
                    a.area, HOP["i"] = hr, _nx
                    mv.key, gpos_now[0], said, target, idle_anchor[0] = None, None, None, None, None
                    STATS["area_t0"] = time.time()
                    HOP["ready"], HOP["landed"] = _land(hl, hg, hr), time.time()   # not ready = wait for its map, never hop on
                    continue
                if a.monitor and _undisc and not soon and not guard and HOP["i"] != _undisc[0]:
                    hl, hg, hr = HOP["list"][_undisc[0]]
                    say(f">> LOOK: island {_undisc[0] + 1}/{len(HOP['list'])} has gyms this run never saw -- teleporting there once "
                        f"to list them (then they are watched from anywhere)")
                    ch.api("TELEPORT", f"--ef lat {hl} --ef lng {hg}")
                    note_jump(ch.meters(here, (hl, hg)), (hl, hg))
                    goal[:] = [hl, hg]
                    a.area, HOP["i"] = hr, _undisc[0]
                    mv.key, gpos_now[0], said, target, idle_anchor[0] = None, None, None, None, None
                    STATS["area_t0"] = time.time()
                    _land(hl, hg, hr)                        # until its gyms are on the game's map (no fixed wait)
                    continue
                _idle_done = False
                if a.monitor and not soon and not guard:     # nothing to beat or fill: stand still, watch (never loop the gyms)
                    if idle_anchor[0] is None:
                        idle_anchor[0] = (here[0], here[1])
                    mv.orbit(idle_anchor[0], here, r=8)
                    _nw = sum(1 for v in live.values() if ch.meters((v[2], v[3]), goal) <= a.area)
                    msg = (f"watching the {_nw} gyms of this island on the game's map -- nothing to beat or fill"
                           f"{'' if _gy_ready else ' (no Gyarados left to place)'}: standing still")
                    _idle_done = True
                elif HOP["list"] and not soon and not guard:   # --hop: nothing to do here -> the next area, by TELEPORT
                    HOP["idle"] = HOP["idle"] or time.time()
                    if time.time() - HOP["idle"] >= a.hop_idle:
                        HOP["idle"] = None
                        if HOP["i"] is None:
                            HOP["i"] = min(range(len(HOP["list"])), key=lambda i: ch.meters(goal, HOP["list"][i][:2]))
                        HOP["i"] = (HOP["i"] + 1) % len(HOP["list"])
                        hl, hg, hr = HOP["list"][HOP["i"]]
                        say(f">> HOP {HOP['i'] + 1}/{len(HOP['list'])}: nothing to beat, join or guard here for {a.hop_idle:.0f} s -- "
                            f"teleporting to {hl:.5f},{hg:.5f} (area {hr:.0f} m) to retake and fill its gyms")
                        ch.api("TELEPORT", f"--ef lat {hl} --ef lng {hg}")
                        note_jump(ch.meters(here, (hl, hg)), (hl, hg))   # (this hop was never written down: its cooldown had no anchor)
                        goal[:] = [hl, hg]
                        a.area = hr
                        if a.feed_zone:
                            sc.exports_sync.feedzone(hl, hg, hr)
                        mv.key, gpos_now[0], said, target = None, None, None, None
                        STATS["area_t0"] = time.time()
                        time.sleep(3)                        # the game loads the new area's gyms
                        continue
                else:
                    HOP["idle"] = None
                if soon or guard or _idle_done:              # (11-16 review: the monitor's stand-still fell through into the
                    pass                                     # gym ring below -- it still walked through all of them)
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
        HOP["idle"] = None                                   # work here: no hop
        HOP["empty"] = set()                                 # (islands found with nothing to do: forgotten once there is work)
        idle_anchor[0] = None                                # (stand still where the NEXT idle starts, not at an old spot)
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
        if d > engage and a.monitor and not g.in_battle() and not g.has("GymState") and not cool_wait():   # --monitor: TELEPORT onto it
            _ji = hop_area(gpos)
            _nm = NAMES.get(fid[:8])
            say(f">> JUMP to {fid[:8]}{' (' + _nm + ')' if _nm else ''}, team {team}, {d:.0f} m -- teleporting onto it, no walking")
            ch.api("TELEPORT", f"--ef lat {gpos[0]} --ef lng {gpos[1]}")
            note_jump(d, gpos)
            if _ji is not None and (abs(goal[0] - HOP["list"][_ji][0]) > 1e-6 or abs(goal[1] - HOP["list"][_ji][1]) > 1e-6):
                hl, hg, hr = HOP["list"][_ji]                # another island: it becomes the area we watch from
                goal[:] = [hl, hg]
                a.area, HOP["i"] = hr, _ji
                if a.feed_zone:
                    sc.exports_sync.feedzone(hl, hg, hr)
                STATS["area_t0"] = time.time()
            mv.key, idle_anchor[0], said = None, None, None
            _land(gpos[0], gpos[1], 80, fid)                 # the avatar lands and the game's map shows the gym: no fixed wait
            continue
        if d > engage:                                       # on the way: walk to it
            gpos_now[0] = None
            mv.travel(gpos, here)
            said = None
            if team in enemy and d < 700:                    # its defenders pick the team (counters): read them while we walk
                try:                                         # (the target's own 5 s re-scan above -- no extra server request)
                    _cv = sc.exports_sync.scanned().get(fid)
                    if _cv and _cv[1] < 15000:
                        counter_push(fid, _cv, sc, dep, a, g)
                except Exception as e:
                    say(f"  (counter team: {e})")
            time.sleep(2)
            continue
        gpos_now[0] = gpos
        mv.orbit(gpos, here, r=orbit_r)                      # in range: keep circling it the whole time
        say(f"engaging {fid[:8]} (team {team}) at {d:.0f} m")
        gym_t0 = time.time()
        g.rep_new(fid)
        g.deploy_open = None
        g.placed.pop(fid, None)
        friendly = team == a.team
        g.armed = False
        if dep["n"] is None or dep["n"] < a.max_deployed:   # arm: the instant it reports empty, place (or open Deploy)
            r_ad = sc.exports_sync.autodeploy(fid, place_ids(dep) if a.autoplace else [], friendly, a.team)
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
            try:                                             # the counter team for THIS gym before its first Battle press:
                _cv = sc.exports_sync.scanned().get(fid)     # no fresh reading yet (a start right next to it, 11-16 22:29: the
                _lt = (live.get(fid) or [team])[0]           # (the map's team NOW: a retake target can still read 0 in `team`)
                if (team in enemy or _lt in enemy) and not (_cv and _cv[1] < 8000 and len(_cv) > 8 and _cv[8]):   # picks landed 1 s after the
                    sc.exports_sync.scan([fid])              # team) -> ask, <= 2.5 s. Never for an EMPTY gym: that is a race
                    _t = time.time()
                    while time.time() - _t < 2.5:
                        g.wait_for(lambda: False, 0.25, tick)
                        _cv = sc.exports_sync.scanned().get(fid)
                        if _cv and _cv[1] < 3000 and len(_cv) > 8 and (_cv[8] or not _cv[3]):
                            break
                _ok = bool(_cv and _cv[1] < 30000) and counter_push(fid, _cv, sc, dep, a, g)
                if not _ok and CT["cur"] and CT["cur"]["fid"] != fid:   # no counters for this gym: never another gym's
                    CT["cur"] = None
                    sc.exports_sync.roster(roster_ids(dep), a.heal_top, [], [x[0] for x in dep["gy"]])
            except Exception as e:
                say(f"  (counter team: {e})")
            final = drill(fid, enemy, g, sc, a, tick, time.time() + a.gym_minutes * 60, refresh=batch_check, join_near=None,
                          cmd_waiting=urgent_cmd,            # join_near=None: Benny 11-15 "drill and finish" -- a red gym with room
                          counters=lambda sv, _f=fid: counter_push(_f, sv, sc, dep, a, g))
                                                             # is filled BETWEEN gyms (passing), never by leaving one mid-drill
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
        if final in (0, a.team):                             # emptied (or red now): this rest ends the moment an enemy team holds it again
            TAKEN[fid] = done[fid]
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
        placed_ok, retake = False, False
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
                    elif friendly and retry_join(fid, (g.placed.get(fid) or {}).get("res", "no answer")):
                        placed_ok = True
                        dep["n"] = (n or 0) + 1
                        STATS["placed"] += 1
                        say(f"  you joined {fid[:8]} with {g.names.get(g.placed[fid]['id'], 'a Pokemon') if hasattr(g, 'names') else 'a Pokemon'} "
                            f"on a retry ({dep['n']}/{a.max_deployed} in gyms now) -- next gym")
                    elif friendly:
                        why = (g.placed.get(fid) or {}).get("res", "no answer")
                        say(f"  the red gym did not take it ({why}) -- moving on, tried again in 60 s")
                        done[fid] = time.time() - 540                # never a 10-min rest on a red gym with room (Benny 11-16 22:55)
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
                            _ok = getattr(g, "deploy_ok_at", 0.0) >= t0 - 5   # the game's own deploy reply said Success (11-15: the
                            if (n is not None and n2 is not None and n2 > n) or _ok:   # live count lagged twice -> "another red player" was YOU)
                                placed_ok = True             # (manual / fallback placement: counted, and the bag refresh after this gym registers it)
                                STATS["placed"] += 1
                                if _ok and n is not None and (n2 is None or n2 <= n):
                                    dep["n"] = n + 1
                                say(f"  you placed a Pokemon ({dep['n']}/{a.max_deployed} in gyms now{'; the game said Success' if _ok else ''}) -- next gym")
                            else:
                                say(f"  another red player filled it first (your gym count is still {n2 if n2 is not None else '?'}) -- moving on")
                        else:
                            say(f"  team {now_team} took it first -- battling it NOW while it has 1 defender (Benny: before their teammates add theirs)")
                            retake = True
                            try:
                                sc.exports_sync.scan([fid])  # its new defender: the counters are picked before the Battle press
                            except Exception:
                                pass
                        break
                    time.sleep(1)
                else:
                    if not placed_ok and not friendly:
                        say("  no placement seen -- moving on")
        if not placed_ok and not friendly and final in (0, a.team) and join_after_loss(fid):
            placed_ok, final = True, 0                          # we got in (the placed count is already taken)
        elif not placed_ok and not friendly and final in (0, a.team):
            try:
                _lv = sc.exports_sync.teams().get(fid)
            except Exception:
                _lv = None
            #  not in: never leave a gym with room rested -- it is judged again at once
            if _lv and _lv[0] == a.team and len(_lv) > 5 and _lv[5] > 0:
                done.pop(fid, None)
                TAKEN.pop(fid, None)
        if retake:                                           # another team got in first: no rest, this gym is drilled NEXT
            done.pop(fid, None)
            TAKEN.pop(fid, None)
            a.join_first, first_done[0] = fid, False
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
        _rl = g.rep_line(placed_ok, a.one_by_one, os.path.join(os.path.dirname(COOL_OBS), "gym_reports.jsonl"))
        if _rl:
            say(_rl)
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
