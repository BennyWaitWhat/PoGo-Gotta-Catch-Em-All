import json, sys, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
d = json.load(open("_showcase_detail_out.json", encoding="utf-8"))


def flat_strings(node, acc, depth=0):
    if not isinstance(node, dict):
        return
    for sk, sv in node.get("slots", {}).items():
        if not isinstance(sv, dict):
            continue
        if "str" in sv:
            acc.append(sv["str"])
        if "tsMs" in sv:
            acc.append("TS:" + sv["tsMs"])
        if "sub" in sv:
            flat_strings(sv["sub"], acc, depth + 1)
        if "elems" in sv:
            for el in sv["elems"]:
                if isinstance(el, dict):
                    if "s" in el and el["s"]:
                        acc.append(el["s"])
                    if "h" in el:
                        flat_strings(el["h"], acc, depth + 1)


def ints_of(node, acc):
    if not isinstance(node, dict):
        return
    for sk, sv in node.get("slots", {}).items():
        if not isinstance(sv, dict):
            continue
        if "i32" in sv:
            acc.append((sk, sv["i32"]))
        if "sub" in sv:
            ints_of(sv["sub"], acc)
        if "elems" in sv:
            for el in sv["elems"]:
                if isinstance(el, dict) and "h" in el:
                    ints_of(el["h"], acc)


def ts(ms):
    try:
        t = int(ms) / 1000
        u = datetime.datetime.fromtimestamp(t, datetime.UTC)
        return u.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ms


print("###### CONTEST SCHEDULES (", len(d["contests"]), ")")
for i, c in enumerate(d["contests"]):
    acc = []
    flat_strings(c, acc)
    seen = set()
    strs = []
    tss = []
    for s in acc:
        if s.startswith("TS:"):
            v = s[3:]
            if v not in seen:
                seen.add(v)
                tss.append(v)
        elif s not in seen:
            seen.add(s)
            strs.append(s)
    if not strs and not tss:
        continue
    print(f"\n--- contest[{i}] ---")
    for s in strs[:50]:
        print("   ", s)
    for v in tss:
        print("   TIME", v, "=>", ts(v))

print("\n\n###### LOCALTIME CALIBRATION")
for c in d.get("localtime_calib", []):
    print(c["ptr"], c["ints"])
