"""Parse the harvest JSON: pull every distinct string, every LocalTimeProto (as a date),
every tsMs, grouped by top-level proto class + instance. Compact summary for the agent."""
import json, sys, re
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
P = r"C:\Users\Blanco\.claude\projects\C--Users-Blanco-Desktop-Claude-Operations-Phone-Maintenance\565701b0-1a11-42dd-894a-3bb423b9a491\tool-results\bgz8q5r3c.txt"
data = json.load(open(P, encoding="utf-8"))


def localtime(slots):
    # LocalTimeProto: +0x18 year, +0x20 month, +0x28 day (from observed). Collect plausible ints.
    y = slots.get("+0x18", {}).get("i32")
    mo = slots.get("+0x20", {}).get("i32")
    d = slots.get("+0x28", {}).get("i32")
    hh = slots.get("+0x30", {}).get("i32")
    mm = slots.get("+0x38", {}).get("i32") if isinstance(slots.get("+0x38", {}).get("i32"), int) else None
    tz = slots.get("+0x38", {}).get("str")
    if y and 2024 <= y <= 2030:
        s = f"{y:04d}-{(mo or 0):02d}-{(d or 0):02d}"
        if hh is not None:
            s += f" {hh:02d}:00"
        if tz:
            s += f" {tz}"
        return s
    return None


def walk(node, path, acc):
    if not isinstance(node, dict):
        return
    cls = node.get("cls")
    slots = node.get("slots", {})
    # LocalTimeProto detection
    if cls == "LocalTimeProto":
        lt = localtime(slots)
        if lt:
            acc["times"].append((path, lt))
    for sk, sv in slots.items():
        if not isinstance(sv, dict):
            continue
        if "str" in sv and sv["str"]:
            acc["strings"].append((path + sk, sv["str"]))
        if "tsMs" in sv:
            acc["ts"].append((path + sk, sv["tsMs"]))
        if "sub" in sv and isinstance(sv["sub"], dict):
            walk(sv["sub"], path + sk + "/", acc)
        if "elems" in sv and isinstance(sv["elems"], list):
            for i, el in enumerate(sv["elems"]):
                if isinstance(el, dict):
                    if "s" in el and el["s"]:
                        acc["strings"].append((path + sk + f"[{i}]", el["s"]))
                    if "h" in el and isinstance(el["h"], dict):
                        walk(el["h"], path + sk + f"[{i}]/", acc)


for cls, blk in data["events"].items():
    pops = blk.get("populated", [])
    if not pops:
        continue
    print("=" * 70)
    print(f"### {cls}  (live n={blk['n']}, populated={len(pops)})")
    for idx, inst in enumerate(pops):
        acc = {"strings": [], "times": [], "ts": []}
        walk(inst, f"[{idx}]", acc)
        # dedup strings preserve order
        seen = set()
        strs = []
        for p, s in acc["strings"]:
            if s not in seen:
                seen.add(s)
                strs.append(s)
        if not strs and not acc["times"] and not acc["ts"]:
            continue
        print(f"  -- instance {idx} --")
        if strs:
            print("     strings:", " | ".join(strs[:40]))
        for p, t in acc["times"][:12]:
            print(f"     time {p}: {t}")
        for p, t in acc["ts"][:12]:
            print(f"     tsMs {p}: {t}")
