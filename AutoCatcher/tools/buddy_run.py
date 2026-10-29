"""Buddy rotation. The user, 2026-09-26: "rotate my hundo Eevee evolutions as buddy, switch them out after every 3 hearts";
2026-10-29: "revisit the eevee rotation again please. Be careful." Keeps --first as buddy until its hearts reach TARGET, then
rotates the hundo Eevee evolutions that are not Best Buddy yet (read from the bag DB), the one closest to Best Buddy first.

CAREFUL, after the 2026-09-26 lockout:
- Nothing is asked of the server just to look. Progress is read from what the game already holds in memory (buddy_tapper
  peek); the 2026-09-26 version asked the server every 30 s. The only server calls are a player's own actions: set a buddy,
  play once a day per buddy, treats with --feed (regular berries only), and one history request if none is in memory.
- An action is made only when it gains something: play while today's play heart is free; a switch when the buddy earned
  --every hearts since it was set, has no play/walk heart left today, or earned nothing for --idle minutes while another
  rotation buddy still has today's play heart. At most --max-swaps switches a day (the game's own count: his own count too).
- Hands off when he picks a buddy himself: an Eevee from the list is adopted, anything else pauses the rotation until an
  Eevee from the list is buddy again.
- Stops, with a phone screencap, on anything unexpected: a failed action, another trainer, an unreadable buddy, a memory read
  that does not show its own switch. One attach; if the game dies it waits until the game has run 2 min and attaches once
  more, and a second death within 30 min ends the run.
- No game hook between actions (buddy_tapper adds one only while an action runs). Not next to gym_run.py (own buddy module).

usage: python buddy_run.py --dry          look only: the rotation, the current buddy and the next step; nothing is done
       python buddy_run.py [--every 3] [--idle 60] [--max-swaps 10] [--feed] [--cmd CMD.json] [--first ID:TARGET]
Live commands (--cmd, JSON, read when the file changes): {"pause":1} {"resume":1} {"stop":1} {"set":"<pokemon id>"}
Check: python test_buddy_plan.py (the decisions, offline)
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

CAT = {1: "treat", 2: "play", 3: "snapshot", 4: "walk", 5: "battle", 6: "new place", 7: "bonus", 8: "route"}
CAP = {1: 3, 2: 1, 3: 1, 4: 3, 5: 3, 6: 1, 7: 6, 8: 1}          # game master BUDDY_CATEGORY_* maxPointsPerDay (read 2026-09-26)
BEST = 300                                                       # game master: Best Buddy at 300 hearts; every ribbon holder has >= 300
REGULAR = ["RazzBerry", "NanabBerry", "PinapBerry", "BlukBerry", "WeparBerry"]   # never the golden ones
EEVEELUTIONS = (134, 135, 136, 196, 197, 470, 471, 700)
DB = os.path.join(os.path.dirname(os.path.dirname(HERE)), "pogo_extract", "pokemon.db")


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Stop(Exception):
    pass


class Detached(Exception):
    pass


def slots(p):
    """today's used heart slots per category, from the game's own shown-hearts map (0 = a free slot)."""
    cats = (p.get("today") or {}).get("cats") or {}
    return {int(c): sum(1 for x in v if x) for c, v in cats.items()}


def room(p, feed):
    """hearts this buddy can still earn today without the user: play, walk (+ treats with --feed)."""
    h = slots(p)
    return CAP[2] - h.get(2, 0) + CAP[4] - h.get(4, 0) + ((CAP[1] - h.get(1, 0)) if feed else 0)


def bag():
    """the hundo Eevee evolutions in the bag DB (refreshed by every cull) -> ({id: name}, [ids without the Best Buddy ribbon])."""
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = c.execute("SELECT uid, species_name, cp, fresh_pokemon_badge FROM pokemon WHERE iv_total = 45 AND pokemon_id IN (%s)"
                         % ",".join(map(str, EEVEELUTIONS))).fetchall()
    finally:
        c.close()
    names = {str(u & 0xFFFFFFFFFFFFFFFF): f"{sp} {cp}" for u, sp, cp, _b in rows}
    return names, [str(u & 0xFFFFFFFFFFFFFFFF) for u, _s, _c, b in rows if not b]


def name_of(names, i):
    if i not in names:
        names[i] = str(i)[-6:]
        try:                                                     # any other buddy: its name from the DB (uid is a signed int64 there)
            u = int(i)
            c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
            r = c.execute("SELECT species_name, cp FROM pokemon WHERE uid = ?", (u - (1 << 64) if u >= 1 << 63 else u,)).fetchone()
            c.close()
            if r:
                names[i] = f"{r[0]} {r[1]}"
        except Exception:
            pass
    return names[i]


def next_in_cycle(rot, cur, pool):
    """the first of pool after cur in rotation order (closest to Best first), wrapping."""
    k = rot.index(cur) + 1 if cur in rot else 0
    for i in rot[k:] + rot[:k]:
        if i in pool and i != cur:
            return i
    return None


def plan(st, p, a, now, today):
    """One decision from the game's own data -> (what, arg, why); what = pet / set / feed / wait / done. Updates st."""
    cur, pts = p.get("buddyId"), p.get("pts")
    h = slots(p)
    first = st.get("first")
    ours = st["rot"] + ([first[0]] if first else [])
    if st.get("day") != today:                                   # a new day: fresh caps, so the hearts-since-set count starts again
        st["day"], st["at_set"] = today, ({cur: pts} if cur == st["ours"] else {})
    if cur in ours:
        st["hist"][cur] = pts                                    # the live count beats the history copy
    if cur in ours and (cur != st["ours"] or st["hands_off"]):  # an Eevee from the list we did not set (or set back): adopt it
        said = st["ours"] is not None
        st.update(ours=cur, gain_at=now, hands_off=False)
        st["at_set"][cur] = pts
        if said:
            return ("wait", None, f"{cur} was set as buddy outside the runner -- continuing the rotation from it")
    elif cur not in ours and st["ours"] is not None and cur != st["ours"]:
        st["hands_off"] = True                                   # his own pick of another buddy: hands off
        return ("wait", None, f"{cur} was set as buddy outside the runner -- the rotation waits until an Eevee from the list "
                              "is buddy again")
    if st["hands_off"]:
        return ("wait", None, None)
    if first:                                                    # the quest target first (e.g. Snom -> Frosmoth needs 10 hearts)
        if cur == first[0] and pts >= first[1]:
            st["first"] = None
            return ("wait", None, f"DONE: {cur} has {pts} hearts (target {first[1]}) -- its task is complete; starting the rotation")
        if cur != first[0]:
            return ("set", first[0], "the quest target")
        if h.get(2, 0) < CAP[2] and st["played"].get(cur) != today:
            return ("pet", None, "today's play heart")
        return ("wait", None, None)
    rot = [i for i in st["rot"] if st["hist"].get(i, 0) < BEST]
    if not rot:
        return ("done", None, "every Eevee in the rotation is Best Buddy")
    avail = [i for i in rot if st["capped"].get(i) != today]
    if cur not in rot:                                           # start-up on another buddy, or this one just reached Best
        return ("set", avail[0], "the one closest to Best Buddy") if avail else ("wait", None, "every rotation Eevee used today's hearts")
    if h.get(2, 0) < CAP[2] and st["played"].get(cur) != today:
        return ("pet", None, "today's play heart")
    if room(p, a.feed) <= 0:
        st["capped"][cur] = today
    gained = pts - st["at_set"].get(cur, pts)
    unplayed = [i for i in avail if i != cur and st["played"].get(i) != today]
    if gained >= a.every:
        why, pool = f"{gained} hearts since it was set", avail
    elif st["capped"].get(cur) == today:
        why, pool = "no play or walk heart left today", avail
    elif now - st["gain_at"] >= a.idle * 60 and unplayed:
        why, pool = f"no heart for {a.idle} min while others still have today's play heart", unplayed
    else:
        if a.feed and h.get(1, 0) < CAP[1] and (p.get("fullUntil") or 0) < now * 1000:
            return ("feed", None, "a treat heart")
        return ("wait", None, None)
    nxt = next_in_cycle(st["rot"], cur, pool)
    return ("set", nxt, why) if nxt else ("wait", None, f"{why}, but no other Eevee has anything left today")


class Tapper:
    """buddy_tapper in the game: install (one liveness pass), peek (plain reads), act (one action, hook only meanwhile)."""

    def __init__(self, sess):
        import buddy_tapper as bt
        self.sess, self.last, self.detached, self.scan = sess, {}, False, False
        self.sc = sess.create_script(bt.JS)
        self.sc.on("message", self.on_msg)
        sess.on("detached", lambda *x: setattr(self, "detached", True))
        self.sc.load()

    def on_msg(self, m, _data):
        if m["type"] == "send" and m["payload"].get("k") == "buddy":
            self.last[m["payload"]["what"]] = (time.time(), m["payload"])
        elif m["type"] == "send":
            say(f"  !! game says: {m['payload']}")              # exc / err / anything unknown: never dropped silently
        else:
            say(f"  !! script error: {m.get('description')}")

    def install(self):
        r = self.sc.exports_sync.install()
        if not r.get("ok"):
            raise Stop(f"!! the game objects could not be found safely: {r}")
        self.hist = r.get("hist") or {}
        return r

    def peek(self):
        if self.detached:
            raise Detached("game connection lost")
        p = self.sc.exports_sync.peek_scan() if self.scan else self.sc.exports_sync.peek()
        if p.get("err") and not self.scan:
            p = self.sc.exports_sync.peek_scan()
            if not p.get("err"):
                self.scan = True
                say("  !! no pointer path to the player record -- reading it by liveness lookup instead, every 5 min")
        if p.get("err") or not p.get("buddyId") or p.get("pts") is None:
            raise Stop(f"!! the current buddy is unreadable: {p}")
        return p

    def act(self, what, arg=None, timeout=25.0):
        if self.detached:
            raise Detached("game connection lost")
        t0 = time.time()
        if self.sc.exports_sync.act(what, arg) < 0:
            raise Stop("!! the tapper is quiet")
        try:
            while time.time() - t0 < timeout:
                if self.detached:
                    raise Detached("game connection lost")
                v = self.last.get(what)
                if v and v[0] >= t0:
                    return v[1]
                time.sleep(0.2)
            self.sc.exports_sync.cancel()                          # no frame came (game in the background?): drop the queued call
            return None
        finally:
            self.unhook()

    def unhook(self):
        for _ in range(50):                                        # the hook comes off as soon as nothing is pending
            try:
                if self.detached or self.sc.exports_sync.idle():
                    return
            except Exception:
                return
            time.sleep(0.2)

    def close(self):
        try:
            for _ in range(10):                                    # quiet first: never unload while the hook is inside a game call
                if self.sc.exports_sync.quiesce():
                    break
                time.sleep(0.5)
        except Exception:
            pass
        for f in (self.sc.unload, self.sess.detach):
            try:
                f()
            except Exception:
                pass


def shot(a):
    """the phone's screen at a stop (what the game showed is the one thing that can't be read back later)."""
    try:
        import pogo_il2cpp as pg
        path = os.path.join(a.shots, time.strftime("buddy_stop_%Y%m%d_%H%M%S.png"))
        with open(path, "wb") as f:
            subprocess.run(["adb", "-s", pg._resolve_device(), "exec-out", "screencap", "-p"], stdout=f, timeout=30, check=True)
        say(f"   phone screen saved: {path}")
    except Exception as e:
        say(f"   (no screencap: {e})")


def table(st, names, cur=None):
    for i in st["rot"]:
        p = st["hist"].get(i)
        lvl = "-" if p is None else "BEST" if p >= BEST else "Ultra" if p >= 150 else "Great" if p >= 70 else "Good"
        say(f"    {name_of(names, i)}: {'never a buddy' if p is None else p} hearts ({lvl}"
            f"{'' if p is None or p >= BEST else f', {BEST - p} to Best'}){'  <- buddy now' if i == cur else ''}")


def status(p, names, st, now):
    h, today = slots(p), p.get("today") or {}
    cur, pts = p["buddyId"], p["pts"]
    since = pts - st["at_set"][cur] if cur in st["at_set"] else None
    return (f"buddy {name_of(names, cur)}: {pts} hearts" + (f" ({BEST - pts} to Best)" if pts < BEST else " (Best)")
            + " | today " + ", ".join(f"{CAT[c]} {h.get(c, 0)}/{CAP[c]}" for c in (2, 4, 1, 5, 3, 6))
            + f" | walk {today.get('km') or 0:.2f}/2 km" + (f" | +{since} since set" if since is not None else "")
            + f" | switches today {p.get('swapsCount') if p.get('swapsWindow') == int(now // 86400) else 0}")


def trainer(a, p):
    if a.trainer and (p.get("name") or "").strip().lower() != a.trainer.lower():
        raise Stop(f"!! the phone is on trainer {p.get('name')!r}, not {a.trainer!r} -- the rotation's Eevees belong to {a.trainer}")
    return p


def loop(a, T):
    names, rot = bag()
    hist = {i: v[0] for i, v in T.hist.items()}
    if not hist and not a.dry:                                   # none in memory: ask once, like opening the buddy history screen
        r = T.act("hist") or {}
        hist = {x[0]: x[2] for x in r.get("hist") or []}
        say(f"  no buddy history in memory -- asked the game once: {len(hist)} records{' ' + str(r.get('err')) if r.get('err') else ''}")
    first = a.first.split(":") if a.first else None
    st = {"rot": sorted(rot, key=lambda i: -hist.get(i, 0)), "hist": hist, "ours": None, "at_set": {}, "gain_at": time.time(),
          "played": {}, "capped": {}, "swaps": {}, "hands_off": False, "paused": False, "first": (first[0], int(first[1])) if first else None,
          "key": None, "said": None, "why": None, "table_at": time.time()}
    p = trainer(a, T.peek())
    say(f"trainer {p.get('name')}; the rotation, closest to Best Buddy first (hearts from the game's buddy history):")
    table(st, names, p["buddyId"])
    if a.dry:
        say(status(p, names, st, time.time()))
        what, arg, why = plan(st, p, a, time.time(), time.strftime("%Y-%m-%d"))
        say(f"DRY RUN -- next step would be: {what}{' ' + name_of(names, arg) if arg else ''}{' (' + why + ')' if why else ''}; nothing done")
        return
    cmd_mtime = os.path.getmtime(a.cmd) if a.cmd and os.path.exists(a.cmd) else 0     # old commands are not replayed
    while True:
        if a.cmd and os.path.exists(a.cmd) and os.path.getmtime(a.cmd) != cmd_mtime:
            cmd_mtime = os.path.getmtime(a.cmd)
            try:
                c = json.load(open(a.cmd, encoding="utf-8"))
            except Exception as e:
                c = {}
                say(f"  (command file unreadable: {e})")
            if c.get("stop"):
                say("COMMAND stop")
                return
            if c.get("pause") or c.get("resume"):
                st["paused"] = bool(c.get("pause"))
                say(f"COMMAND {'pause: watching only' if st['paused'] else 'resume'}")
            if c.get("set"):                                     # outside the rotation = pause it (resume with {"resume":1})
                st["ours"], st["paused"] = str(c["set"]), str(c["set"]) not in st["rot"] or st["paused"]
                say(f"COMMAND set {name_of(names, str(c['set']))}: {T.act('set', str(c['set']))}"
                    f"{' -- rotation paused' if st['paused'] else ''}")
        p = trainer(a, T.peek())
        now, today = time.time(), time.strftime("%Y-%m-%d")
        if (p["buddyId"], p["pts"]) != st["key"]:
            st["key"], st["gain_at"] = (p["buddyId"], p["pts"]), now
        line = status(p, names, st, now)
        if line != st["said"]:
            say(line)
            st["said"] = line
        if now - st["table_at"] > 3600:
            st["table_at"] = now
            table(st, names, p["buddyId"])
        what, arg, why = ("wait", None, None) if st["paused"] else plan(st, p, a, now, today)
        if why and why != st["why"] and what == "wait":
            say(("  " if not why.startswith("DONE") else "") + why.replace(str(p["buddyId"]), name_of(names, p["buddyId"])))
        st["why"] = why
        if what == "done":
            say(f"DONE: {why}")
            table(st, names, p["buddyId"])
            return
        if what == "pet":
            r = T.act("pet") or {}
            if r.get("err") or r.get("res") != 1:
                raise Stop(f"!! play with {name_of(names, p['buddyId'])} failed: {r or 'no reply'}")
            st["played"][p["buddyId"]] = today
            say(f"  PLAY with {name_of(names, p['buddyId'])}: {p['pts']} -> {r.get('pts')} hearts")
        elif what == "set":
            switch(a, T, st, p, arg, why, names, now, today)
        elif what == "feed":
            feed(a, T, p, names)
        T.unhook()                                               # leftovers from an action whose reply came late
        time.sleep(300 if T.scan else a.tick)


def switch(a, T, st, p, want, why, names, now, today):
    used = max(p.get("swapsCount") or 0 if p.get("swapsWindow") == int(now // 86400) else 0, st["swaps"].get(today, 0))
    if used >= a.max_swaps:
        if st.get("budget") != today:
            st["budget"] = today
            say(f"  {why} -- but today's {a.max_swaps} switches are used ({used}); keeping {name_of(names, p['buddyId'])}")
        return
    r = T.act("set", want) or {}
    if r.get("err") or r.get("res") != 1 or r.get("buddyId") != want:
        raise Stop(f"!! the switch to {name_of(names, want)} failed: {r or 'no reply'}")
    st["swaps"][today] = st["swaps"].get(today, 0) + 1
    st["ours"], st["gain_at"], st["hist"][want], st["at_set"][want] = want, time.time(), r["pts"], r["pts"]
    h = slots(r)
    if h.get(2, 0) >= CAP[2]:
        st["played"][want] = today
    say(f"SWITCH {name_of(names, p['buddyId'])} -> {name_of(names, want)} ({why}): {r['pts']} hearts, {BEST - r['pts']} to Best | "
        f"its day so far: play {h.get(2, 0)}/1, walk {h.get(4, 0)}/3, treat {h.get(1, 0)}/3")
    for attempt in (1, 2):                                       # the memory read must follow our own switch, or we steer blind
        for _ in range(10):
            time.sleep(2)
            if T.peek().get("buddyId") == want:
                return
        if attempt == 1:
            say("  !! the memory read does not show the switch -- finding the game objects again")
            T.install()
    raise Stop(f"!! the game confirmed the switch to {name_of(names, want)}, but the memory read never showed it -- stopping")


def feed(a, T, p, names):
    cnt = (T.act("count") or {}).get("counts") or {}
    pick = max((b for b in REGULAR if (cnt.get(b) or 0) > a.reserve), key=lambda b: cnt.get(b) or 0, default=None)
    if not pick:
        say(f"  no regular berries above the reserve ({a.reserve}) for treats: {cnt}")
        a.feed = False
        return
    r = T.act("feed", pick) or {}
    if r.get("err") or r.get("res") != 1:
        raise Stop(f"!! treat {pick} -> {name_of(names, p['buddyId'])} failed: {r or 'no reply'}")
    say(f"  TREAT {pick} -> {name_of(names, p['buddyId'])}: {p['pts']} -> {r.get('pts')} hearts, full until "
        f"{time.strftime('%H:%M', time.localtime((r.get('fullUntil') or 0) / 1000))}")


def run(a):
    import pogo_il2cpp as pg
    pg.wait_ready_to_attach(timeout_s=3600, min_age_s=120)       # never attach to a game that has just (re)started
    sess, pid = pg.get_session()
    try:
        T = Tapper(sess)
    except Exception:
        sess.detach()
        raise
    try:
        r = T.install()
        say(f"attached pid {pid}: player record path {r.get('cppPath')}, {len(T.hist)} buddy records in memory, "
            f"live graph {r.get('graph')}{' -- notes: ' + str(r['graphNotes']) if r.get('graphNotes') else ''}")
        return loop(a, T)
    finally:
        T.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="look only: show the rotation and the next step, do nothing")
    ap.add_argument("--first", default=None, help="ID:TARGET -- keep this buddy until its hearts reach TARGET (an evolution quest)")
    ap.add_argument("--every", type=int, default=3, help="hearts per buddy before switching")
    ap.add_argument("--idle", type=float, default=60, help="minutes without a heart before moving on to an unplayed Eevee")
    ap.add_argument("--max-swaps", type=int, default=10, help="switches per day at most (the game allows 20)")
    ap.add_argument("--feed", action="store_true", help="give regular berries (never golden) when the treat cap has room")
    ap.add_argument("--reserve", type=int, default=0, help="keep at least this many of each regular berry")
    ap.add_argument("--tick", type=float, default=60.0, help="seconds between memory reads (no server traffic)")
    ap.add_argument("--trainer", default="BennyValentinC", help="the trainer the Eevees belong to; any other stops the run")
    ap.add_argument("--cmd", default=None, help="live command file")
    ap.add_argument("--shots", default=tempfile.gettempdir(), help="where a stop saves the phone's screen")
    a = ap.parse_args()
    import frida
    import pogo_il2cpp as pg
    deaths = []
    while True:
        try:
            run(a)
            return
        except KeyboardInterrupt:
            return
        except Stop as e:
            say(str(e))
            shot(a)
            return
        except (Detached, pg.NotReadyToAttach, frida.InvalidOperationError, frida.TransportError, frida.ServerNotRunningError) as e:
            deaths = [d for d in deaths if time.time() - d < 1800] + [time.time()]
            if a.dry or len(deaths) >= 2:
                say(f"!! lost the game ({type(e).__name__}: {e}){' twice within 30 min' if len(deaths) >= 2 else ''} -- stopping")
                return
            say(f"lost the game ({type(e).__name__}: {e}) -- attaching once more when it has run 2 min")
        except Exception as e:
            say(f"!! {type(e).__name__}: {e} -- stopping")
            shot(a)
            return


if __name__ == "__main__":
    main()
