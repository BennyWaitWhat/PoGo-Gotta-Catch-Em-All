"""Offline test of apple_collector.py's decision logic (no phone): python tools/apple_sim.py
Expected: expired 0 taps (dead 1); live-once [2]; live-stays [3] (never a 2nd tap); encounter 0; far 0;
two-apples [6,7] (1.5 s apart); pool-reuse [9] (the expired 8 never); other-type 0."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(HERE, "apple_collector.py"), encoding="utf-8").read()
i = s.index('JS = r"""') + 9
d = tempfile.mkdtemp(); p = os.path.join(d, "ac.js")
open(p, "w", encoding="utf-8").write("var rpc={exports:{}};\n" + s[i:s.index('"""', i)].replace("Process.findModuleByName('libil2cpp.so').enumerateExports()", "[]"))
sys.exit(subprocess.call(["node", os.path.join(HERE, "apple_sim.js"), p]))
