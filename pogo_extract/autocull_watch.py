"""Fire the gated cull automatically when the Pokemon box gets close to full.

WHY THIS SHAPE. The complaint was "I run out of space and then wait ~10 minutes for a cull."
The cull itself is NOT slow -- a measured full_audit.py run is ~55s end to end (recrawl,
6 parallel audits, sync + verify the rest). The 10 minutes was waiting on a human to notice
and start it. So the fix is a trigger, not a rewrite of the decision engine.

Deliberately NOT doing on-the-fly per-catch tagging. Pokemod can decide at catch time because its
rules are purely per-mon (hundo/nundo, shiny, shadow, special ball, class != NORMAL, origin).
This collection's keep law is largely RANKING-based (final_top3, preevo_top2, ll_top3, xxl_top3,
shiny_top5, rarity cap), and a rank cannot be evaluated from the new catch alone -- it depends on
the whole species cohort, which shifts with every catch and release. Deciding per-catch would mean
caching thresholds that go stale, and a stale threshold tags a KEEPER. That risk is unacceptable
here because the tag feeds an irreversible manual mass-release.

SAFETY: this only ever runs full_audit.py, which gates itself -- 6 independent audits must pass or
it refuses to sync ("pile is irreversible; fix first"). It TAGS only. It never releases anything.

Usage:
    python autocull_watch.py                 # watch forever, cull when free space < threshold
    python autocull_watch.py --once          # evaluate once and exit
    python autocull_watch.py --free 150      # custom threshold
"""
import argparse
import os
import sqlite3
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "pokemon.db")
PY = sys.executable
STATE = os.path.join(HERE, "system", "analysis", "autocull_watch.log")


def say(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(STATE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def box_state():
    """(in_bag, cap, free). Capacity is read LIVE from player_state.json -- never hardcode it;
    a hardcoded 11150 was wrong once and the real value was 5700."""
    cap = None
    ps = os.path.join(HERE, "player_state.json")
    try:
        import json
        with open(ps, encoding="utf-8") as fh:
            d = json.load(fh)
        # real key on this build is max_pokemon_storage (written by read_player_state.py from
        # PlayerService.get_MaxPokemon); the others are defensive aliases
        for k in ("max_pokemon_storage", "MaxPokemon", "max_pokemon", "maxPokemon"):
            if k in d:
                cap = int(d[k]); break
    except Exception:
        pass
    c = sqlite3.connect(DB)
    bag = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1").fetchone()[0]
    c.close()
    return bag, cap, (cap - bag) if cap else None


def run_cull():
    say("free space low -> running gated cull (full_audit.py)")
    r = subprocess.run([PY, os.path.join(HERE, "full_audit.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=HERE, timeout=900)
    tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-6:]
    for l in tail:
        say("  " + l.strip()[:120])
    rc = r.returncode
    # full_audit.py returns FOUR distinct non-zero codes and ONLY rc==1 means the gate refused:
    #   rc 1 (full_audit.py:171) audits FAILED, sync never started        -- nothing pushed
    #   rc 2 (full_audit.py:152) recrawl FAILED, audits never ran         -- nothing pushed
    #   rc 3 (full_audit.py:181) audits passed, the SYNC itself failed    -- PHONE WAS CONTACTED
    #   rc 4 (full_audit.py:192) audits passed, sync ok, verify drifted   -- PHONE WAS WRITTEN
    # Printing "NOT synced (audit gate)" for all four was a MISLABEL: on rc 3/4 the sync had already
    # attached and written tags. Telling the operator nothing was pushed when a write was attempted
    # is exactly the desensitisation failure reconcile_tags.py warns about -- it trains them to skim
    # past a line that sometimes reports a real, irreversible-adjacent write.
    if rc == 0:
        say("cull OK -- tagged; release them in-game when you want the space")
    elif rc == 1:
        # a Python traceback out of full_audit also exits 1, so only blame the gate when the gate
        # actually spoke. Never claim "nothing was pushed" on an unproven exit.
        if "AUDIT GATE FAILED" in (r.stdout or ""):
            say("cull rc=1 -- AUDIT GATE refused -- nothing was pushed. Needs a look.")
        else:
            say("cull rc=1 with no AUDIT GATE line -- full_audit likely CRASHED, not refused; "
                "do NOT assume nothing was pushed, check /api/job. Needs a look.")
    elif rc == 2:
        say("cull rc=2 -- RECRAWL failed -- audits never ran, nothing was pushed. Needs a look.")
    elif rc == 3:
        say("cull rc=3 -- audits PASSED; the SYNC ran and FAILED -- the phone MAY have been "
            "partially written, check /api/job. Needs a look.")
    elif rc == 4:
        say("cull rc=4 -- audits PASSED and the sync SUCCEEDED; only the post-sync verify drifted "
            "-- the phone WAS written. Needs a look.")
    else:
        say(f"cull returned rc={rc} -- full_audit crashed (rc={rc}). Needs a look.")
    if rc != 0:
        # stderr was captured and then silently dropped, so a crash logged nothing but its rc.
        for l in [l for l in (r.stderr or "").splitlines() if l.strip()][-4:]:
            say("  stderr: " + l.strip()[:120])
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--free", type=int, default=150,
                    help="run the cull when free slots drop below this (default 150)")
    ap.add_argument("--interval", type=int, default=300, help="seconds between checks")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    say(f"autocull watch started (threshold: free < {a.free}, every {a.interval}s)")
    last_run = 0.0
    while True:
        try:
            bag, cap, free = box_state()
            if free is None:
                say(f"bag {bag} | capacity UNKNOWN (player_state.json missing/stale) -- skipping")
            else:
                say(f"bag {bag}/{cap} | free {free}")
                # Cooldown so a cull that frees nothing (because the user has not released yet)
                # cannot spin. Tagging does NOT create space -- only the user's release does.
                if free < a.free and (time.time() - last_run) > 1800:
                    run_cull()
                    last_run = time.time()
                elif free < a.free:
                    say("  below threshold but a cull ran recently -- waiting "
                        "(tagging does not free space; the release does)")
        except Exception as e:
            say(f"check failed: {e}")
        if a.once:
            return 0
        time.sleep(a.interval)


sys.exit(main())
