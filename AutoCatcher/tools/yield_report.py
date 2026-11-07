"""Catch YIELD of the on-phone catcher, from the raw game data (read-only, desktop): python tools/yield_report.py [since=HH:MM] [until=HH:MM]

Reads the phone's spawn_ledger.jsonl (catch_loop_fast.py, since 2026-11-07: one record per spawn per stay on the map --
the server's spawn point, position, despawn time when the server tells it, our open, the server's encounter reply, first
throw, result, the queue order in force; plus the avatar track every 5 s) and catch_loop.log (MINUTE lines carry the
server's own catch counter, PlayerStatsProto.NumPokemonCaptured; HOLD lines). Prints:
  1. the funnel: in range -> opened -> encounter ok -> thrown -> caught
  2. one cause for every miss
  3. latencies (queue wait, encounter reply, throw -> result) and reply time vs requests outstanding (the pipeline)
  4. supply-limited vs catcher-limited minutes
  5. the despawn-first vs fifo A/B by 5-minute block
  6. the catcher's count against the server's
Nothing on the phone is changed: two `cat`s over adb."""
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")
AN = "/data/data/com.termux/files/home/pogo/system/analysis/pokemod"
BLOCK_S = 300          # the A/B block length in catch_loop_fast.py (CFG abBlockS)
RANGE_M = 140          # MapSettingsProto EncounterRangeMeters, read live 2026-11-07
BACKLOG_MS = 1000      # a spawn waiting longer than this for its open = the catcher is behind
LIMITED_S = 20         # seconds of backlog in a minute that make it catcher-limited


def usage():
    print(__doc__)
    sys.exit(2)


def pull(name):
    r = subprocess.run(["adb", "-s", DEV, "exec-out", f"su -c 'cat {AN}/{name}'"], capture_output=True)
    if r.returncode != 0:
        sys.exit(f"adb cat {name} failed: {r.stderr.decode(errors='replace')[:200]}")
    return r.stdout.decode("utf-8", errors="replace")


def hm_to_ms(hm, ref_ms):
    """HH:MM or HH:MM:SS (phone local time = this PC's local time) on the day of ref_ms -> epoch ms."""
    d = time.localtime(ref_ms / 1000)
    parts = [int(x) for x in hm.split(":")] + [0, 0]
    return int(time.mktime((d.tm_year, d.tm_mon, d.tm_mday, parts[0], parts[1], parts[2], 0, 0, -1)) * 1000)


def meters(a_lat, a_lng, b_lat, b_lng):
    r = 6371008.8
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dl = math.radians(b_lng - a_lng)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q / 100 * (len(xs) - 1))))]


def fmt_ms(v):
    return "-" if v is None else (f"{v / 1000:.1f}s" if abs(v) >= 1000 else f"{int(v)}ms")


def today_only(lines):
    """The log has times, no dates: keep the lines since the last midnight (walking back, a jump up of 1 h+ = the day before)."""
    out, prev = [], None
    for ln in reversed(lines):
        m = re.match(r"^(\d\d):(\d\d):(\d\d) ", ln)
        if not m:
            continue
        s = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        if prev is not None and s > prev + 3600:
            break
        prev = s
        out.append(ln)
    return out[::-1]


def main():
    args = {}
    for a in sys.argv[1:]:
        if a.startswith("-") or "=" not in a:
            usage()
        k, v = a.split("=", 1)
        args[k] = v
    led = [json.loads(x) for x in pull("spawn_ledger.jsonl").splitlines() if x.strip().startswith("{")]
    log = today_only(pull("catch_loop.log").splitlines())
    spawns = [r for r in led if r.get("k") == "spawn" and r.get("t0")]
    track = sorted((r["t"], r["lat"], r["lng"]) for r in led if r.get("k") == "pos")
    if not spawns:
        sys.exit("no spawn records yet")
    ref = spawns[0]["t0"]
    lo = hm_to_ms(args["since"], ref) if "since" in args else min(r["t0"] for r in spawns)
    hi = hm_to_ms(args["until"], ref) if "until" in args else max(r["t1"] for r in spawns)
    spawns = [r for r in spawns if lo <= r["t0"] < hi]
    for r in spawns:   # records before the 02:55 fix kept the server's 14-day "not telling" time: unknown, not a time
        if r.get("exp") and not (r["t0"] - 60000 < r["exp"] <= r["t0"] + 3600000):
            r["exp"] = None
    print(f"window {time.strftime('%H:%M:%S', time.localtime(lo / 1000))} - {time.strftime('%H:%M:%S', time.localtime(hi / 1000))}"
          f"  ({(hi - lo) / 60000:.1f} min, {len(spawns)} spawn records, {len(track)} avatar fixes)")

    # HOLD windows from the log (the catcher stopped opening on purpose)
    holds = []
    for ln in log:
        m = re.match(r"^(\d\d:\d\d:\d\d) HOLD (\d+)s: (.*)$", ln)
        if m:
            t = hm_to_ms(m[1], ref)
            holds.append((t, t + int(m[2]) * 1000, m[3]))

    def in_hold(t):
        return any(a <= t < b for a, b, _ in holds)

    def pos_at(t):   # the avatar position at t, linear between the 5 s fixes
        if not track:
            return None
        j = next((i for i, x in enumerate(track) if x[0] >= t), None)
        if j is None:
            return track[-1][1:]
        if j == 0:
            return track[0][1:]
        a, b = track[j - 1], track[j]
        f = (t - a[0]) / max(1, b[0] - a[0])
        return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f

    # one encounter = every stay of one encounter id; the final outcome is the best of its stays
    enc = defaultdict(list)
    for r in spawns:
        enc[r["e"]].append(r)
    rank = {"caught": 0, "fled": 1}
    final = {}
    for e, rs in enc.items():
        rs.sort(key=lambda r: r["t0"])
        best = min(rs, key=lambda r: (rank.get(r["r"], 2), -r["t1"]))
        final[e] = best

    skipped = [e for e, r in final.items() if r["r"] == "legendary"]
    E = {e: r for e, r in final.items() if r["r"] != "legendary"}
    n = len(E)

    def any_(e, k):
        return any(r.get(k) for r in enc[e])

    opened = [e for e in E if any_(e, "tO")]
    enc_ok = [e for e in E if any(r.get("rs") == 1 for r in enc[e])]
    thrown = [e for e in E if any_(e, "tT")]
    caught = [e for e in E if E[e]["r"] == "caught"]
    print("\n1. FUNNEL (one line per encounter id; skipped by rule: %d legendary)" % len(skipped))
    for name, xs in (("in range", list(E)), ("opened", opened), ("encounter ok", enc_ok), ("thrown", thrown), ("caught", caught)):
        print(f"   {name:<13} {len(xs):>5}  {100 * len(xs) / max(1, n):5.1f}%")
    far = [e for e in E if (E[e].get("d0") or 0) > RANGE_M]
    print(f"   first seen beyond {RANGE_M} m: {len(far)}; classes: " + ", ".join(f"{k} {v}" for k, v in Counter(E[e]['c'] for e in E).most_common()))

    # 2. one cause per miss
    causes = Counter()
    examples = defaultdict(list)
    for e, r in E.items():
        if r["r"] == "caught":
            continue
        last = enc[e][-1]
        why = r["r"]
        exp = next((x["exp"] for x in enc[e] if x.get("exp")), None)
        if why == "fled":
            p = r.get("pr")
            ball = {1: "Poke", 2: "Great", 3: "Ultra"}.get(r.get("b"), str(r.get("b")))
            if p is not None and p >= 0.99:
                c = "fled at a sure catch (spawn expired)"
            elif (r.get("n") or 0) <= 1:
                c = f"fled on the first throw ({ball} Ball)"
            else:
                c = f"fled after {r.get('n')} throws ({ball} Ball)"
        elif why == "gone":
            ever_open = any_(e, "tO")
            t_last = last.get("ls") or last["t1"]
            me = pos_at(t_last)
            d_last = meters(me[0], me[1], last["lat"], last["lng"]) if (me and last.get("lat") is not None) else None
            if ever_open and not any_(e, "tT"):
                c = "gone after our open (no throw yet)"
            elif ever_open:
                c = "gone with a throw in the air"
            elif in_hold(t_last):
                c = "gone while the catcher was on HOLD"
            elif exp and t_last >= exp - 3000:
                c = "despawned while waiting in the queue"
            elif d_last is not None and d_last >= RANGE_M - 15:
                c = "walked out of range while waiting in the queue"
            else:
                c = "left the map while waiting in the queue (cause unknown)"
            if d_last is not None:
                examples[c].append(round(d_last))
        elif why.startswith("enc") or why in ("notinrange", "srverror"):
            c = f"encounter refused by the server ({why})"
        else:
            c = f"no server answer / client error ({why})"
        causes[c] += 1
    miss = n - len(caught)
    print(f"\n2. MISSES: {miss} of {n} ({100 * miss / max(1, n):.1f}%), one cause each")
    for c, k in causes.most_common():
        ex = examples.get(c)
        extra = f"   (distance at last sight: median {statistics.median(ex)} m)" if ex else ""
        print(f"   {k:>4}  {c}{extra}")

    # 2b. flees by the avatar's distance (at the first throw when recorded, else at the result) and by species
    fd = defaultdict(Counter)
    for r in spawns:
        if r["r"] not in ("caught", "fled"):
            continue
        d = r.get("dT") if r.get("dT") is not None else r.get("d1")
        if d is None:
            continue
        fd["<30 m" if d < 30 else "30-60 m" if d < 60 else "60-90 m" if d < 90 else "90+ m"][r["r"]] += 1
    print("   fled share by distance:  " + "  ".join(f"{k} {c['fled']}/{sum(c.values())} = {100 * c['fled'] / sum(c.values()):.1f}%"
                                              for k, c in sorted(fd.items(), key=lambda kv: kv[0]) if sum(c.values())))
    fs = Counter(r["id"] for r in spawns if r["r"] == "fled")
    ns = Counter(r["id"] for r in spawns if r["r"] in ("caught", "fled"))
    worst = sorted(((fs[s] / ns[s], s) for s in ns if ns[s] >= 10), reverse=True)[:5]
    print("   worst species (10+ throws at): " + ", ".join(f"#{s} {fs[s]}/{ns[s]} = {100 * v:.0f}%" for v, s in worst))

    # 3. latencies + the pipeline
    recs = sorted(spawns, key=lambda r: r["t0"])
    wait = [r["tO"] - r["t0"] for r in recs if r.get("tO")]
    rep = [r["tR"] - r["tO"] for r in recs if r.get("tR") and r.get("tO") and r["tR"] >= r["tO"]]
    res1 = [r["tC"] - r["tT"] for r in recs if r.get("tC") and r.get("tT") and r.get("n") == 1]
    o2r = [r["tC"] - r["tO"] for r in recs if r.get("tC") and r.get("tO")]
    print("\n3. LATENCY            p50     p90     p99")
    for name, xs in (("queue wait", wait), ("encounter reply", rep), ("throw -> result", res1), ("open -> result", o2r)):
        print(f"   {name:<17} {fmt_ms(pct(xs, 50)):>7} {fmt_ms(pct(xs, 90)):>7} {fmt_ms(pct(xs, 99)):>7}   n={len(xs)}")

    def outstanding(t):   # our requests waiting for the server at t: opens without a reply + throws without a result
        k = 0
        for r in recs:
            if r["t0"] > t:
                break
            if r.get("tO") and r["tO"] <= t < (r.get("tR") or r["t1"]):
                k += 1
            elif r.get("tT") and r["tT"] <= t < (r.get("tC") or r["t1"]):
                k += 1
        return k

    buckets = defaultdict(list)
    for r in recs:
        if r.get("tR") and r.get("tO") and r["tR"] >= r["tO"]:
            buckets[("reply", min(outstanding(r["tO"] - 1), 6))].append(r["tR"] - r["tO"])
        if r.get("tC") and r.get("tT") and r.get("n") == 1:
            buckets[("result", min(outstanding(r["tT"] - 1), 6))].append(r["tC"] - r["tT"])
    print("   time to answer vs our requests already waiting (6 = 6+): a straight rise = the requests go one at a time")
    for kind in ("reply", "result"):
        row = []
        for q in range(7):
            xs = buckets.get((kind, q))
            if xs:
                row.append(f"{q}:{fmt_ms(statistics.median(xs))}(n{len(xs)})")
        print(f"   {('encounter ' + kind) if kind == 'reply' else 'catch result':<17} " + "  ".join(row))

    # 4. per minute: supply vs catcher-limited. A minute with a 15 s+ hole in the avatar track = the catcher was not
    #    running (game in the background / screen off / restart): neither group.
    t_first, t_last = lo // 60000 * 60000, hi
    fixes = [t for t, _, _ in track]
    minutes = []
    for m0 in range(t_first, t_last, 60000):
        m1 = m0 + 60000
        arr = [r for r in recs if m0 <= r["t0"] < m1 and r["r"] != "legendary"]
        got = [r for r in recs if r["r"] == "caught" and r.get("tC") and m0 <= r["tC"] < m1]
        lost_q = [r for r in recs if r["r"] == "gone" and not r.get("tO") and m0 <= r["t1"] < m1]
        backlog = 0
        for s in range(m0, m1, 1000):
            if any(r["t0"] <= s - BACKLOG_MS and s < (r.get("tO") or r["t1"]) for r in recs if r["t0"] <= s and r["r"] != "legendary"):
                backlog += 1
        inside = [m0] + [t for t in fixes if m0 <= t < m1] + [min(m1, hi)]
        down = max(b - a for a, b in zip(inside, inside[1:])) > 15000
        minutes.append((m0, len(arr), len(got), backlog, len(lost_q), down))
    lim = [x for x in minutes if not x[5] and (x[3] >= LIMITED_S or x[4] > 0)]
    sup = [x for x in minutes if not x[5] and not (x[3] >= LIMITED_S or x[4] > 0)]
    print(f"\n4. MINUTES (catcher-limited = {LIMITED_S}+ s with a spawn waiting > {BACKLOG_MS / 1000:.0f} s for its open, or one lost waiting;"
          f" {sum(1 for x in minutes if x[5])} minute(s) with the catcher down are in neither)")
    for name, xs in (("supply-limited", sup), ("catcher-limited", lim)):
        if xs:
            c = [x[2] for x in xs]
            print(f"   {name:<16} {len(xs):>3} min  caught/min mean {statistics.mean(c):5.1f}  max {max(c):>3}  "
                  f"60+: {sum(1 for v in c if v >= 60)}  new spawns/min {statistics.mean(x[1] for x in xs):5.1f}")
    print("   minute  new  caught  backlog_s  lost_waiting")
    for m0, a, g, b, lq, dn in minutes:
        tag = "  <- catcher down part of the minute" if dn else ("  <- catcher-limited" if (b >= LIMITED_S or lq) else "")
        print(f"   {time.strftime('%H:%M', time.localtime(m0 / 1000))}  {a:>4}  {g:>6}  {b:>9}  {lq:>12}{tag}")

    # 5. the A/B. An encounter belongs to the arm in force at its FIRST sight: the experiment running then (the log's
    #    "A/B key=value" / "ORDER value" flip lines) and the parity of the clock's 5-minute block, as cfg_now() picks it.
    flips = []
    for ln in log:
        m = re.match(r"^(\d\d:\d\d:\d\d) (?:A/B (\w+)=(\S+) \(block|ORDER (\w+) \(A/B block)", ln)
        if m:
            flips.append((hm_to_ms(m[1], ref), m[2] or "order", m[3] or m[4]))
    by_parity = {(k, int(t // 1000 // BLOCK_S) % 2): v for t, k, v in flips}

    field = {"order": "ord", "openMs": "om", "nearWait": "nw", "readyMs": "rm"}   # the record field that carries each experiment's setting

    def arm_of(rec):
        """The experiment of the last flip line before the record's first sight (a restart logs an "at start" line;
        the 03:01:44 restart predates those: its records carry openMs but the last line before them is an ORDER flip)."""
        key = None
        for ft, k, _ in flips:
            if ft <= rec["t0"]:
                key = k
        if key is None:
            key = flips[0][1] if flips else "order"
        if key == "order" and "om" in rec:
            key = "openMs"
        v = by_parity.get((key, int(rec["t0"] // 1000 // BLOCK_S) % 2), rec.get(field.get(key, key)))
        return f"{key}={v}"

    def waiting_at(t):
        return sum(1 for r in recs if r["t0"] < t and t < (r.get("tO") or r["t1"]) and r["r"] != "legendary")

    blocks = defaultdict(Counter)
    arms = defaultdict(lambda: defaultdict(list))
    opened_recs = sorted((r for r in recs if r.get("tO")), key=lambda r: r["tO"])
    for a_, b_ in zip(opened_recs, opened_recs[1:]):   # the open pacing achieved while others were waiting
        if waiting_at(a_["tO"] + 1) > 0:
            arms[arm_of(b_)]["gap"].append(b_["tO"] - a_["tO"])
    for e, r in E.items():
        first = enc[e][0]
        b = int(first["t0"] // 1000 // BLOCK_S)
        arm = arm_of(first)
        if first.get("tO") and waiting_at(first["t0"]) >= 3:
            arms[arm]["wave_wait"].append(first["tO"] - first["t0"])
        k = blocks[(b, arm)]
        k["n"] += 1
        k["caught"] += r["r"] == "caught"
        k["fled"] += r["r"] == "fled"
        k["gone_q"] += r["r"] == "gone" and not any_(e, "tO")
        k["known_exp"] += any(x.get("exp") for x in enc[e])
        a = arms[arm]
        if first.get("tO"):
            a["wait"].append(first["tO"] - first["t0"])
        if first.get("tR") and first.get("tO") and first["tR"] >= first["tO"]:
            a["reply"].append(first["tR"] - first["tO"])
        if first.get("rs") not in (None, 1):
            a["refused"].append(first["rs"])
        thrown_rec = next((x for x in enc[e] if x.get("tT")), None)
        if thrown_rec and thrown_rec.get("d0") is not None and thrown_rec["d0"] > 55:
            a["far"].append(r["r"] == "fled")   # first seen beyond 55 m: what near-wait is for
        if any((x.get("nwt") or 0) > 0 for x in enc[e]):
            a["held"].append(r["r"] == "fled")
    print("\n5. A/B (5-minute blocks by first sight)  block  arm              spawns caught  yield  fled  lost-waiting  had-despawn-time")
    tot = defaultdict(Counter)
    for (b, arm), k in sorted(blocks.items()):
        tot[arm].update(k)
        print(f"   {time.strftime('%H:%M', time.localtime(b * BLOCK_S))}  {arm:<16} {k['n']:>6} {k['caught']:>6}  {100 * k['caught'] / max(1, k['n']):5.1f}%"
              f"  {k['fled']:>4}  {k['gone_q']:>12}  {k['known_exp']:>5}")
    for arm, k in sorted(tot.items()):
        a = arms[arm]
        print(f"   TOTAL {arm:<16} {k['n']:>6} {k['caught']:>6}  {100 * k['caught'] / max(1, k['n']):5.1f}%  {k['fled']:>4}  {k['gone_q']:>12}  {k['known_exp']:>5}")
        print(f"         open gap while others wait p50 {fmt_ms(pct(a['gap'], 50))} (n{len(a['gap'])}) | queue wait p50 {fmt_ms(pct(a['wait'], 50))}"
              f" p90 {fmt_ms(pct(a['wait'], 90))} | arriving behind 3+: p50 {fmt_ms(pct(a['wave_wait'], 50))} p90 {fmt_ms(pct(a['wave_wait'], 90))}"
              f" (n{len(a['wave_wait'])}) | encounter reply p50 {fmt_ms(pct(a['reply'], 50))} p90 {fmt_ms(pct(a['reply'], 90))} | refused {len(a['refused'])}")
        far, held = a["far"], a["held"]
        print(f"         first seen beyond 55 m: {len(far)}, fled {sum(far)} ({100 * sum(far) / max(1, len(far)):.1f}%)"
              f" | first throw held while closing in: {len(held)}, fled {sum(held)}")

    # 6. the catcher's count vs the server's
    # A minute with a catcher (re)start counts only the new run's catches: left out. The MINUTE lines are cut at the 10 s
    # report, the ledger at each catch's own time, so single minutes differ by a few; the sums agree.
    restarts = {hm_to_ms(m[1][:5], ref) for m in (re.match(r"^(\d\d:\d\d:\d\d) attached pid=", ln) for ln in log) if m}
    ours = srv = fled = s_enc = fled_e = srv_e = 0
    mins = set()
    for ln in log:
        m = re.match(r"^(\d\d:\d\d:\d\d) MINUTE (\d\d:\d\d) caught=(\d+) fled=(\d+) .*?server caught=\+(\d+)(?: encountered=\+(\d+))?", ln)
        if m and lo <= hm_to_ms(m[2], ref) < hi and hm_to_ms(m[2], ref) not in restarts:
            ours += int(m[3])
            fled += int(m[4])
            srv += int(m[5])
            mins.add(hm_to_ms(m[2], ref))
            if m[6] is not None:
                s_enc += int(m[6])
                srv_e += int(m[5])
                fled_e += int(m[4])
    led_caught = sum(1 for r in recs if r["r"] == "caught" and r.get("tC") and r["tC"] // 60000 * 60000 in mins)
    print(f"\n6. COUNTS over the {len(mins)} minutes that carry the server counter:  catcher log caught {ours}  |  server "
          f"NumPokemonCaptured +{srv}  |  ledger caught records {led_caught}")
    if s_enc:
        print(f"   server NumPokemonEncountered +{s_enc} vs NumPokemonCaptured +{srv_e} in the same minutes: encountered - caught = "
              f"{s_enc - srv_e} (catcher log fled {fled_e})")


def html_page(text, title):
    """The printed report as one self-contained page (light/dark), for sharing."""
    esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--bg:#fbfbf9;--fg:#1d1d1b;--mut:#6b6b66;--line:#e2e1dc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--fg:#ecebe6;--mut:#a3a29c;--line:#2e2e2b}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px}}h1{{font-size:20px;margin:0 0 4px}}p{{color:var(--mut);margin:0 0 16px}}
pre{{font:12.5px/1.45 ui-monospace,Consolas,monospace;white-space:pre;overflow-x:auto;border:1px solid var(--line);border-radius:8px;padding:14px}}
</style></head><body><main><h1>{title}</h1><p>Generated {time.strftime('%Y-%m-%d %H:%M')} by tools/yield_report.py from the phone's spawn_ledger.jsonl + catch_loop.log</p>
<pre>{esc}</pre></main></body></html>"""


if __name__ == "__main__":
    out = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("html=")), None)
    if out:   # html=<path>: print as usual and also write the page
        import io
        sys.argv = [a for a in sys.argv if not a.startswith("html=")]
        buf, real = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            main()
        finally:
            sys.stdout = real
        print(buf.getvalue(), end="")
        open(out, "w", encoding="utf-8").write(html_page(buf.getvalue(), "Catcher yield"))
        print(f"\nwrote {out}")
    else:
        main()
