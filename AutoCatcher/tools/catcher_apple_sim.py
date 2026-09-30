"""Offline test of the apple module inside catch_loop_fast.py (no phone): python tools/catcher_apple_sim.py
Every scenario states its expected result in catcher_apple_sim.js; the exit code is 1 when any of them fails."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(HERE, os.pardir, "system", "scripts", "game_write", "catch_loop_fast.py"), encoding="utf-8").read()
i = s.index('JS = r"""') + 9
d = tempfile.mkdtemp(); p = os.path.join(d, "c.js")
open(p, "w", encoding="utf-8").write("var rpc={exports:{}};\n" + s[i:s.index('"""', i)])
sys.exit(subprocess.call(["node", os.path.join(HERE, "catcher_apple_sim.js"), p]))
