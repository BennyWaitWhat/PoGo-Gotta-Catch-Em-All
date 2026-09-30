"""Offline test of the reward catcher's state machine (no phone): extracts the JS from reward_catcher.py, fakes the
game calls and runs 4 scenarios -- normal / one lost throw / a catch the server is slow to clear / a reward that never
registers. Run after ANY change to the tick() logic:

  python tools/reward_sim.py [path/to/reward_catcher.py]

Expected (2026-09-26 build): normal 3 throws; lost-once 4 throws lost=1 (~364 frames, v2 took 738); slow-clear 3 throws
slowconf=1 (never a double throw); never 7 throws then ST 9 (throw cap 6; v2 threw forever)."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, os.pardir, "system", "scripts", "game_write", "reward_catcher.py")
s = open(src, encoding="utf-8").read()
i = s.index('JS = r"""') + 9
js = s[i:s.index('"""', i)]
d = tempfile.mkdtemp()
open(os.path.join(d, "rc.js"), "w", encoding="utf-8").write("var rpc={exports:{}};\n" + js)
sys.exit(subprocess.call(["node", os.path.join(HERE, "reward_sim.js"), os.path.join(d, "rc.js")]))
