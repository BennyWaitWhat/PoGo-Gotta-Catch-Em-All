"""Buddy runner (the user, 2026-09-26): keep --first as buddy until its hearts reach its target (Snom -> Frosmoth needs 10
hearts), then rotate --rotate as buddy, switching after every --every hearts.

On the current buddy it plays once a day (the "play" heart) and, with --feed, gives regular berries while the treat cap (3/day)
has room and the buddy is not full. Every number comes from the game's own replies (BuddyObservedData via RequestBuddyStats,
BuddyPokemonService getters); nothing is derived. Live commands through --cmd (JSON, re-read when the file changes):
  {"stats":1} {"hist":1} {"pet":1} {"feed":"RazzBerry"} {"set":"<pokemon id>"} {"pause":1} {"resume":1} {"stop":1}
Never dies: re-attaches to a relaunched game by itself (after the 45 s attach-safe wait). {"stop":1} = quiet, then unload.

usage: python buddy_run.py --first 5625741171209217810:10 --rotate ID,ID,... --every 3 --feed --cmd CMD.json
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import frida  # noqa: E402
import pogo_il2cpp as pg  # noqa: E402
import buddy_tapper as bt  # noqa: E402

CAT = {1: "treat", 2: "play", 3: "snapshot", 4: "walk", 5: "battle", 6: "new place", 7: "bonus", 8: "route"}
CAP = {1: 3, 2: 1, 3: 1, 4: 3, 5: 3, 6: 1, 7: 6, 8: 1}          # game master BUDDY_CATEGORY_* maxPointsPerDay
REGULAR = ["RazzBerry", "NanabBerry", "PinapBerry", "BlukBerry", "WeparBerry"]   # never the golden ones
AUTO = (2, 4, 5)                                                 # hearts earned without the user: play (here), walk, battle (gym party)


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Detached(Exception):
    pass


class Link:
    def __init__(self):
        self.last, self.detached = {}, False

    def on_msg(self, m, _data):
        if m["type"] == "send":
            p = m["payload"]
            if p.get("k") == "buddy":
                self.last[p["what"]] = (time.time(), p)
            elif p.get("k") in ("exc", "err"):
                say(f"  [{p.get('k')}] {p}")
        elif m["type"] == "error":
            say(f"  [script error] {m.get('description')}")


class FileLink:
    """--via DIR: the Gym Battle runner owns the Frida session. One command at a time: write the WHOLE runner_cmd.json
    ({"buddy": [[what, arg]]}), then wait for its reply line in buddy_out.jsonl before the next (the file is shared)."""
    def __init__(self, d):
        self.cmd, self.out = os.path.join(d, "runner_cmd.json"), os.path.join(d, "buddy_out.jsonl")

    def ask(self, what, arg=None, timeout=30.0):
        pos = os.path.getsize(self.out) if os.path.exists(self.out) else 0
        wait = 1.5 - (time.time() - getattr(self, "last_write", 0))   # the relay notices a change by mtime: never 2 writes in 1.5 s
        if wait > 0:
            time.sleep(wait)
        with open(self.cmd, "w", encoding="utf-8") as f:
            json.dump({"buddy": [[what, arg]]}, f)
        self.last_write = time.time()
        os.utime(self.cmd, (self.last_write, self.last_write))
        t0 = time.time()
        while time.time() - t0 < timeout:
            if os.path.exists(self.out) and os.path.getsize(self.out) > pos:
                with open(self.out, encoding="utf-8") as f:
                    f.seek(pos)
                    for line in f.read().splitlines():
                        try:
                            p = json.loads(line)
                        except ValueError:
                            continue
                        if p.get("what") == what and (arg is None or str(p.get("arg")) == str(arg)):
                            return p
            time.sleep(0.3)
        say(f"  (no reply to {what} {arg or ''} in {timeout:.0f} s)")
        return None


def A(what, arg=None, timeout=25.0):
    t0 = time.time()
    sc.exports_sync.buddy(what, arg)
    while time.time() - t0 < timeout:
        if ln.detached:
            raise Detached("game connection lost")
        v = ln.last.get(what)
        if v and v[0] >= t0:
            return v[1]
        time.sleep(0.2)
    return None


def slots(stats):
    """today's used slots per category from the game's own shown-hearts map (0 = free slot; a double heart uses one slot).
    The caps are per buddy: a buddy that was set earlier today keeps what it used."""
    cats = (stats.get("today") or {}).get("cats") or {}
    return {int(c): sum(1 for x in v if x) for c, v in cats.items()}


def loop(a, A):
    first = a.first.split(":") if a.first else None
    rot = [x.strip() for x in (a.rotate or "").split(",") if x.strip()]
    st = {"phase": "first" if first else "rotate", "idx": 0, "at_set": {}, "capped": {}, "paused": False, "said": None, "hist_at": 0.0}
    cmd_mtime = os.path.getmtime(a.cmd) if a.cmd and os.path.exists(a.cmd) else 0     # old commands are not replayed
    names = {}
    if a.names and os.path.exists(a.names):
        names = json.load(open(a.names, encoding="utf-8"))
    nm = lambda i: names.get(str(i), str(i)[-6:])
    while True:
        if a.cmd and os.path.exists(a.cmd) and os.path.getmtime(a.cmd) != cmd_mtime:
            cmd_mtime = os.path.getmtime(a.cmd)
            try:
                c = json.load(open(a.cmd, encoding="utf-8"))
            except Exception as e:
                c = {}
                say(f"  (command file unreadable: {e})")
            if c.get("stop"):
                say("COMMAND stop: unloading cleanly")
                return
            if c.get("pause"):
                st["paused"] = True
                say("COMMAND pause: watching only")
            if c.get("resume"):
                st["paused"] = False
                say("COMMAND resume")
            for w in ("pet", "stats", "hist"):
                if c.get(w):
                    say(f"COMMAND {w}: {A(w)}")
            if c.get("feed"):
                say(f"COMMAND feed {c['feed']}: {A('feed', c['feed'])}")
            if c.get("set"):
                say(f"COMMAND set {c['set']}: {A('set', str(c['set']))}")
        if not st.get("who") or time.time() - st.get("who_at", 0) > 300:    # (shared command file: keep the traffic low)
            st["who"], st["who_at"] = (A("who") or {}), time.time()
        who = st["who"]
        stats = A("stats") or {}
        cur, pts = who.get("buddyId"), stats.get("pts")
        if not cur or pts is None or stats.get("err"):
            say(f"  (no fresh buddy data: who={who} stats={stats})")
            time.sleep(15)
            continue
        h = slots(stats)
        room = sum(CAP[c] - h.get(c, 0) for c in AUTO + ((1,) if a.feed else ()))
        line = (f"buddy {nm(cur)}: {pts} hearts total | today " + ", ".join(f"{CAT[c]} {h.get(c, 0)}/{CAP[c]}" for c in CAP)
                + f" | walk {stats.get('today', {}).get('km') or 0:.2f}/2 km | room {room} | swaps left {who.get('swapsLeft')}")
        if line != st["said"]:
            say(line)
            st["said"] = line
        if a.hist_every and time.time() - st["hist_at"] > a.hist_every:         # the rotation's own progress, from the game
            st["hist_at"] = time.time()
            hs = (A("hist") or {}).get("hist") or []
            byid = {x[0]: x for x in hs}
            for i in ([first[0]] if first else []) + rot:
                x = byid.get(i)
                p = pts if i == cur else x[2] if x else None                    # (the current buddy: its live count)
                lvl = "-" if p is None else "BEST" if p >= 300 else "Ultra" if p >= 150 else "Great" if p >= 70 else "Good"
                say(f"    {nm(i)}: {p if p is not None else 'never a buddy'} hearts ({lvl}{', ' + str(300 - p) + ' to Best' if p is not None and p < 300 else ''})")
        if st["paused"]:
            time.sleep(a.tick)
            continue
        # the plan
        if st["phase"] == "first":
            if pts >= int(first[1]) and cur == first[0]:
                say(f"DONE: {nm(first[0])} has {pts} hearts (target {first[1]}) -- its task is complete; starting the rotation")
                st["phase"] = "rotate"
                continue
            want = first[0]
        else:
            if not rot:
                time.sleep(a.tick)
                continue
            if not st["at_set"] and cur in rot:                      # restarted mid-rotation: adopt the current buddy
                st["idx"] = rot.index(cur)
            today = time.strftime("%Y-%m-%d")
            for _ in rot:                                            # skip the ones with nothing left to earn today
                want = rot[st["idx"] % len(rot)]
                if st["capped"].get(want) != today:
                    break
                st["idx"] += 1
            else:
                if st.get("allcapped") != today:
                    st["allcapped"] = today
                    say("every rotation buddy has used today's automatable hearts -- keeping the current one until tomorrow")
                time.sleep(max(a.tick, 300))
                continue
            base = st["at_set"].get(want)
            if cur == want and base is not None and (pts - base >= a.every or room == 0):
                if room == 0:
                    st["capped"][want] = today
                say(f"{nm(want)} earned {pts - base} hearts since set{' and has no play/walk/battle hearts left today' if room == 0 else ''} -> switching to the next")
                st["idx"] += 1
                continue
        if cur != want:
            if (who.get("swapsLeft") or 0) <= 0:
                say(f"  no buddy swaps left today -- keeping {nm(cur)}")
                time.sleep(120)
                continue
            r = A("set", want) or {}
            st["who"] = None                                          # re-read who is buddy after a swap
            say(f"SET buddy {nm(want)}: result {r.get('res')}{' err ' + str(r.get('err')) if r.get('err') else ''} -> buddy now {nm(r.get('buddyId'))}, hearts {r.get('pts')}")
            if r.get("buddyId") == want and r.get("pts") is not None:
                st["at_set"][want] = r["pts"]
            time.sleep(3)
            continue
        if st["phase"] == "rotate" and want not in st["at_set"]:
            st["at_set"][want] = pts                                  # (it was already the buddy when we started)
        # care for the current buddy: play once, then treats while there is room and it is not full
        if h.get(2, 0) < CAP[2]:
            r = A("pet") or {}
            say(f"  PLAY with {nm(cur)}: result {r.get('res')} shown-heart {r.get('shown')} -> {r.get('pts')} hearts{' err ' + str(r.get('err')) if r.get('err') else ''}")
        elif a.feed and h.get(1, 0) < CAP[1] and (stats.get("fullUntil") or 0) < time.time() * 1000:
            cnt = (A("count") or {}).get("counts") or {}
            pick = max((b for b in REGULAR if (cnt.get(b) or 0) > a.reserve), key=lambda b: cnt.get(b) or 0, default=None)
            if pick:
                r = A("feed", pick) or {}
                say(f"  TREAT {pick} -> {nm(cur)}: result {r.get('res')} shown-heart {r.get('shown')} -> {r.get('pts')} hearts, "
                    f"full until {time.strftime('%H:%M', time.localtime((r.get('fullUntil') or 0) / 1000))}{' err ' + str(r.get('err')) if r.get('err') else ''}")
            elif st.get("nofood") != cur:
                st["nofood"] = cur
                say(f"  no regular berries above the reserve ({a.reserve}) for treats: {cnt}")
        time.sleep(a.tick)


def run(a):
    pg.wait_ready_to_attach(timeout_s=300, min_age_s=45)
    sess, pid = pg.get_session()
    ln = Link()
    sc = sess.create_script(bt.JS)
    sc.on("message", ln.on_msg)
    sess.on("detached", lambda *x: setattr(ln, "detached", True))
    sc.load()
    try:
        r = sc.exports_sync.install()
        say(f"attached pid {pid}: {r}")
        if not r.get("ok"):
            raise RuntimeError(f"install failed: {r}")
        return loop(a, lambda what, arg=None: ask(sc, ln, what, arg))
    finally:
        try:                                                  # quiet first: never unload while the hook is inside a game call
            sc.exports_sync.quiesce()
            time.sleep(1.0)
        except Exception:
            pass
        for f in (sc.unload, sess.detach):
            try:
                f()
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", default=None, help="ID:TARGET -- keep this buddy until its hearts reach TARGET")
    ap.add_argument("--rotate", default="", help="comma-separated pokemon ids to rotate as buddy afterwards")
    ap.add_argument("--every", type=int, default=3, help="hearts per buddy before switching")
    ap.add_argument("--feed", action="store_true", help="give regular berries (never golden) when the treat cap has room")
    ap.add_argument("--reserve", type=int, default=0, help="keep at least this many of each regular berry")
    ap.add_argument("--tick", type=float, default=20.0, help="seconds between checks")
    ap.add_argument("--hist-every", type=float, default=900.0, help="seconds between history (progress) reports; 0 = off")
    ap.add_argument("--names", default=None, help="JSON {id: name} for readable logs")
    ap.add_argument("--cmd", default=None, help="live command file")
    ap.add_argument("--via", default=None, help="DIR: drive the game through the Gym Battle runner's command file (no own Frida session)")
    a = ap.parse_args()
    if a.via:
        loop(a, FileLink(a.via).ask)
        return
    while True:                                               # never die: a relaunched game is re-attached by itself
        try:
            run(a)
            return
        except KeyboardInterrupt:
            return
        except (Detached, frida.InvalidOperationError, frida.TransportError, frida.ServerNotRunningError) as e:
            say(f"lost the game connection ({type(e).__name__}: {e}) -- re-attaching in 5 s")
            time.sleep(5)
        except Exception as e:
            say(f"session failed ({type(e).__name__}: {e}) -- retrying in 15 s")
            time.sleep(15)


if __name__ == "__main__":
    main()
