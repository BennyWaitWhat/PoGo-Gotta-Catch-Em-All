"""Query the live-build il2cpp metadata dump.

This is the ground-truth oracle for writing hooks. Before any Interceptor.attach/replace goes
into the agent, the class and method it names must be confirmed here -- a hook aimed at a method
that was renamed or removed in the current build is how this project has frozen the game before.

Usage:
    python q_il2cpp.py class  <NameOrSubstring>       # find classes
    python q_il2cpp.py method <NameOrSubstring>       # find methods anywhere
    python q_il2cpp.py show   <ExactClassName>        # full methods+fields for a class
    python q_il2cpp.py has    <ExactClass> <Method>   # exit 0 if it exists, prints param count
    python q_il2cpp.py ns     <NamespacePrefix>       # list classes in a namespace
"""
import functools
import gzip
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(HERE, "system", "analysis", "clone", "il2cpp_meta.jsonl.gz")


@functools.lru_cache(maxsize=1)
def load():
    with gzip.open(META, "rt", encoding="utf-8") as fh:
        return [json.loads(l) for l in fh]


def fq(r):
    return ("%s.%s" % (r["ns"], r["n"])) if r.get("ns") else r["n"]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd, arg = sys.argv[1], sys.argv[2]
    recs = load()

    if cmd == "class":
        low = arg.lower()
        hits = [r for r in recs if low in (r["n"] or "").lower()]
        print("%d classes matching %r" % (len(hits), arg))
        for r in hits[:60]:
            print("  %-60s img=%-18s methods=%-4d fields=%d"
                  % (fq(r), r["img"], len(r["m"]), len(r["f"])))
        return 0

    if cmd == "ns":
        hits = [r for r in recs if (r["ns"] or "").startswith(arg)]
        print("%d classes under %r" % (len(hits), arg))
        for r in hits[:120]:
            print("  %-60s methods=%-4d fields=%d" % (fq(r), len(r["m"]), len(r["f"])))
        return 0

    if cmd == "method":
        low = arg.lower()
        n = 0
        for r in recs:
            for m in r["m"]:
                if m[0] and low in m[0].lower():
                    print("  %-55s %s(argc=%d)" % (fq(r), m[0], m[1]))
                    n += 1
                    if n >= 80:
                        print("  ... truncated")
                        return 0
        print("%d matches" % n)
        return 0

    if cmd == "show":
        hits = [r for r in recs if r["n"] == arg or fq(r) == arg]
        if not hits:
            print("no such class: %s" % arg)
            return 1
        for r in hits:
            print("=== %s   (img=%s, parent=%s) ===" % (fq(r), r["img"], r["p"]))
            print("-- methods (%d) --" % len(r["m"]))
            for m in r["m"]:
                print("   %-50s argc=%s  ptr=%s" % (m[0], m[1], m[2]))
            print("-- fields (%d) --" % len(r["f"]))
            for f in r["f"]:
                print("   %-50s offset=%s (0x%x)" % (f[0], f[1], f[1]))
        return 0

    if cmd == "has":
        meth = sys.argv[3]
        for r in recs:
            if r["n"] == arg or fq(r) == arg:
                for m in r["m"]:
                    if m[0] == meth:
                        print("YES %s.%s argc=%d ptr=%s" % (fq(r), meth, m[1], m[2]))
                        return 0
        print("NO %s.%s not found in this build" % (arg, meth))
        return 1

    print(__doc__)
    return 2


sys.exit(main())
