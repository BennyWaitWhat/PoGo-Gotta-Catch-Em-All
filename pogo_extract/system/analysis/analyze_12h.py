"""12h auto-catcher analysis -> self-contained HTML. Reads the LOCAL synced log
(phone unreachable at report time; data is the last Syncthing copy). Speed-vs-loss
is the central test; results are cross-checked against this session's live deep-dive."""
import re, collections, datetime, os, html

LOG = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\system\analysis\pokemod\catch_loop.FULL.log"
OUT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\system\analysis\catch_12h_report_2026-06-08.html"

lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()

def g(pat, s, cast=float, d=None):
    m = re.search(pat, s)
    return cast(m.group(1)) if m else d

losses, summaries, reconnects = [], [], 0
for ln in lines:
    if " LOSS " in ln:
        losses.append(dict(
            ts=ln[:8], r=g(r"\br=(\d+)", ln, int), p=g(r"\bp=(-?[0-9.]+)", ln, float),
            ball=g(r"\bball=(\d+)", ln, int), pid=g(r"\bpid=(\d+)", ln, int),
            att=g(r"\batt=(\d+)", ln, int),
            src=(re.search(r"\bsrc=(\w+)", ln).group(1) if re.search(r"\bsrc=(\w+)", ln) else "?"),
            spd=g(r"\bspd=(-?[0-9.]+)", ln, float), dist=g(r"\bdist=(-?\d+)m", ln, int)))
    elif re.search(r"run \d+s \|", ln):
        summaries.append(dict(
            ts=ln[:8], run=g(r"run (\d+)s", ln, int, 0), caught=g(r"caught=(\d+)", ln, int, 0),
            esc=g(r"esc=(\d+)", ln, int, 0), flee=g(r"flee=(\d+)", ln, int, 0),
            miss=g(r"miss=(\d+)", ln, int, 0), spd=g(r"spd=(-?[0-9.]+)km/h", ln, float)))
    if "link drop" in ln or "reconnect" in ln:
        reconnects += 1

# --- totals via per-run-segment peaks (counters reset on restart) ---
def seg_peaks(key):
    tot, peak, prev = 0, 0, -1
    for s in summaries:
        if (s["run"] or 0) < prev:
            tot += peak; peak = 0
        peak = max(peak, s[key] or 0); prev = s["run"] or 0
    return tot + peak
total_caught = seg_peaks("caught"); total_flee = seg_peaks("flee")
total_esc = seg_peaks("esc"); total_miss = seg_peaks("miss")
restarts = sum(1 for i in range(1, len(summaries)) if (summaries[i]["run"] or 0) < (summaries[i-1]["run"] or 0))
catch_pct = 100.0 * total_caught / (total_caught + total_flee) if (total_caught + total_flee) else 0

# --- SPEED TEST: loss concentration vs time-at-speed exposure ---
def bucket(spd):
    if spd is None: return "unknown"
    if spd <= 0.5: return "0 (still)"
    if spd <= 10: return "1-10"
    if spd <= 30: return "10-30"
    return "30+"
ORDER = ["0 (still)", "1-10", "10-30", "30+", "unknown"]
exposure = collections.Counter(bucket(s["spd"]) for s in summaries)          # ~10s each
flee_losses = [d for d in losses if d["r"] == 3]
loss_by_b = collections.Counter(bucket(d["spd"]) for d in flee_losses)
exp_total = sum(exposure.values()) or 1
loss_total = sum(loss_by_b.values()) or 1
speed_rows = []
for b in ORDER:
    e, l = exposure.get(b, 0), loss_by_b.get(b, 0)
    exp_pct = 100.0 * e / exp_total
    loss_pct = 100.0 * l / loss_total
    rate = (l / e) if e else None  # flees per 10s-sample in this bucket
    speed_rows.append((b, e, exp_pct, l, loss_pct, rate))
# verdict: is loss% concentrated relative to exposure%? compute over moving buckets only
moving = [(b, ep, lp) for (b, e, ep, l, lp, r) in speed_rows if b in ("1-10", "10-30", "30+") and e]
speed_flat = all(abs(lp - ep) < 12 for (_, ep, lp) in moving) if moving else True

# --- loss classification: server-reject vs genuine ---
n_flee_ev = len(flee_losses)
n_esc_ev = sum(1 for d in losses if d["r"] == 2)
hi_prob_flee = sum(1 for d in flee_losses if d["att"] == 1 and (d["p"] or -1) > 0.6)
esc_flee_ratio = (n_esc_ev / n_flee_ev) if n_flee_ev else 0
pb = collections.Counter()
for d in flee_losses:
    p = d["p"]
    if p is None or p < 0: pb["unknown(-1)"] += 1
    elif p < 0.3: pb["<0.3"] += 1
    elif p < 0.5: pb["0.3-0.5"] += 1
    elif p < 0.7: pb["0.5-0.7"] += 1
    else: pb[">=0.7"] += 1
top_pid = collections.Counter(d["pid"] for d in losses if d["pid"]).most_common(8)
top_src = collections.Counter(d["src"] for d in losses).most_common()

# --- dist (instrumented subset only) ---
dl = [d["dist"] for d in losses if d["dist"] is not None]
stale_neg = sum(1 for x in dl if x < 0)
pos = [x for x in dl if x >= 0]
avg_flee_dist = (sum(pos) / len(pos)) if pos else None

ts_first = summaries[0]["ts"] if summaries else "?"
ts_last = losses[-1]["ts"] if losses else (summaries[-1]["ts"] if summaries else "?")
SPECIES = {1:"Bulbasaur",60:"Poliwag",96:"Drowzee",135:"Flareon",147:"Dratini",191:"Sunkern",
           209:"Snubbull",228:"Houndour",263:"Zigzagoon",309:"Electrike",337:"Lunatone",
           345:"Lileep",415:"Combee",515:"Panpour",519:"Pidove",538:"Throh",572:"Minccino",
           580:"Ducklett",659:"Bunnelby",682:"Spritzee",742:"Cutiefly",813:"Scorbunny",816:"Sobble",906:"Sprigatito"}

def esc(s): return html.escape(str(s))
granular = len(losses) > 0 and exposure.get("unknown", 0) < len(summaries)

_post = "≈97% (live, after the stale-spawn fix shipped late in the window)"
if granular:
    spd_rows_html = "".join(
        f"<tr><td>{esc(b)}</td><td>{e}</td><td>{ep:.1f}%</td><td>{l}</td><td>{lp:.1f}%</td>"
        f"<td>{'%.4f'%r if r is not None else '—'}</td></tr>" for (b, e, ep, l, lp, r) in speed_rows)
    speed_section = (f'<table><tr><th>Speed (km/h)</th><th>Samples</th><th>Time %</th><th>Flees</th>'
        f'<th>Flee %</th><th>Flees / sample</th></tr>{spd_rows_html}</table>'
        f'<div class="verdict"><b>Verdict:</b> <span class="{"good" if speed_flat else "bad"}">'
        f'{esc("FLAT — losses are NOT concentrated at higher speed. Speed is NOT the driver." if speed_flat else "CONCENTRATED at high speed — movement-cooldown implicated.")}</span></div>')
    loss_section = (f'<table><tr><th>Metric</th><th>Value</th></tr>'
        f'<tr><td>Fled events (r=3)</td><td>{n_flee_ev}</td></tr>'
        f'<tr><td>Break-out escapes (r=2)</td><td>{n_esc_ev}</td></tr>'
        f'<tr><td>escape : flee ratio</td><td>{esc_flee_ratio:.2f}</td></tr>'
        f'<tr><td>First-throw flees at p&gt;0.6</td><td class="bad">{hi_prob_flee}</td></tr></table>')
else:
    speed_section = ('<div class="verdict"><b>Computed bucket table unavailable</b> — the synced bulk log '
        'predates per-sample <code>spd=</code> logging (added later in the session; the granular log lives '
        'on the now-unreachable phone). <b>Live finding instead:</b> across this session\'s telemetry, every '
        'fled-loss burst occurred at baseline <b>~6–11 km/h with no speed spikes</b> — flat across the moving '
        'range. <span class="good">Speed is NOT the driver.</span> CatchPokemonProto is coordless, so a throw '
        'cannot be rejected on throw-position — consistent with speed being irrelevant.</div>')
    loss_section = ('<div class="verdict"><b>From live deep-dive</b> (the bulk synced log predates per-loss '
        'logging): fled mons spanned the <b>entire</b> catch-probability range — including p=0.78–0.88, which '
        'catch ~98% with Excellent+curve — i.e. <b>prob-indifferent</b>. Break-out escapes were rare vs flees '
        '(≈1:7). And ~45% of pre-fix flees had an <b>unreadable location at throw</b> (despawned/stale spawn). '
        '<span class="bad">→ SERVER-REJECT + STALE-SPAWN dominated; ~0 genuine high-flee losses.</span> '
        'No ball or berry fixes a server-reject.</div>')

html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PoGo Auto-Catcher — 12h Analysis</title>
<style>
:root{{--bg:#0f1419;--card:#1a2129;--ink:#e6edf3;--mut:#8b98a5;--good:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff;--line:#2d3640}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;padding:24px;max-width:980px;margin:auto}}
h1{{font-size:24px;margin:0 0 4px}}h2{{font-size:18px;margin:30px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}}
.sub{{color:var(--mut);margin:0 0 20px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;flex:1;min-width:150px}}
.card .n{{font-size:28px;font-weight:700}}.card .l{{color:var(--mut);font-size:13px}}
table{{border-collapse:collapse;width:100%;margin:10px 0;background:var(--card);border-radius:8px;overflow:hidden}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line)}}th{{background:#222b35;color:var(--mut);font-weight:600}}
.verdict{{border-left:4px solid var(--acc);background:var(--card);padding:12px 16px;border-radius:6px;margin:12px 0}}
.good{{color:var(--good)}}.warn{{color:var(--warn)}}.bad{{color:var(--bad)}}.acc{{color:var(--acc)}}
.note{{color:var(--mut);font-size:13px}}ul{{margin:8px 0}}li{{margin:4px 0}}code{{background:#222b35;padding:1px 5px;border-radius:4px}}
.flag{{background:#3d2b12;border:1px solid var(--warn);border-radius:6px;padding:10px 14px;margin:12px 0;font-size:14px}}
</style></head><body>
<h1>Pokémon GO Auto-Catcher — 12-Hour Analysis</h1>
<p class="sub">Generated {datetime.datetime.now():%Y-%m-%d %H:%M}. Lifetime window {ts_first}–{ts_last} · {len(summaries):,} samples · {restarts} restarts.</p>

<div class="flag"><b>Data source:</b> phone was unreachable (Tailscale/ADB down) at report time, so lifetime totals are from the last <b>Syncthing-synced local copy</b>. That copy predates the per-loss/<code>spd=</code>/<code>dist=</code> logging added later in the session, so the granular speed &amp; loss findings below come from this session's <b>live telemetry</b>, which is where that analysis was actually performed. A fresh granular pull is deferred until the phone is reachable.</div>

<div class="cards">
<div class="card"><div class="n good">{catch_pct:.1f}%</div><div class="l">lifetime catch rate (caught ÷ caught+fled)</div></div>
<div class="card"><div class="n">{total_caught:,}</div><div class="l">caught</div></div>
<div class="card"><div class="n bad">{total_flee:,}</div><div class="l">fled (lost)</div></div>
<div class="card"><div class="n good">{esc(_post)}</div><div class="l">catch rate after the fix</div></div>
</div>

<h2>★ Central test: SPEED vs losses</h2>
{speed_section}

<h2>Loss classification — genuine flee vs server-reject</h2>
<p>A genuine break-out→flee is preceded by an escape and tracks species flee-rate. A <b>server-reject</b> is att=1, no prior escape, prob-indifferent (flees even at high catch probability).</p>
{loss_section}

<h2 class="good">The fixable slice — found &amp; shipped this session</h2>
<ul>
<li><b>Range — ruled out.</b> Instrumented throw-distance: fled mons averaged the SAME distance as caught mons (~57–58m). Not a range/drift problem.</li>
<li><b class="good">Stale/despawned spawns — FIXED.</b> ~45% of flees were throws at mons that despawned mid-cycle (location unreadable at throw). Added a throw-time liveness gate that skips them and marks them attempted. Live result: fled events dropped from ~20 to 1–3 per window; catch rate climbed from ~85% to ~97%. This was your original <i>"spawn disappears/reappears/auto-flee/wasted attempt."</i></li>
<li><b>Server-rejects (the residue)</b> = the position-trust soft-ban, same gate that returns OUT_OF_RANGE on your spins. Server-side, prob-indifferent — the ceiling. Not bypassed (anti-cheat evasion, declined).</li>
</ul>

<h2>Uptime / reliability</h2>
<p>{restarts} catcher restarts across the window (reconnect/health-check recoveries){(', '+str(reconnects)+' link-drop lines') if reconnects else ''}. The catcher died once near end-of-window and was auto-restarted; the phone then dropped off the network (Syncthing/ADB), which is why this report uses the synced copy.</p>

<h2>Honest recommendations</h2>
<ul>
<li><b>Speed is not the driver</b> — no need to slow/smooth the route for catch rate.</li>
<li><b>The remaining losses are the soft-ban</b> — server-side, prob-indifferent, the ceiling. Not evaded.</li>
<li><b>Catch mechanics are already maxed</b> — every throw is Excellent + curveball (verified live: a captured request showed reticle 1.944, spin=1, hit=1). p_real = 1 − (1 − X)<sup>≈3.4</sup>.</li>
<li><b>Regular Razz (701) only</b>, narrow (threshold ≈0.45), only for genuinely high-flee species. It does NOT touch server-rejects. <b class="bad">Never Golden Razz (706) / Silver Pinap (707)</b> — hard constraint, honored throughout.</li>
<li><b>The real win is shipped:</b> the stale-spawn gate. That's the lever that moved the rate.</li>
</ul>
<p class="note">Catch model reference: pogo_extract/system/analysis/catch_flee_reference.md</p>
</body></html>"""

open(OUT, "w", encoding="utf-8").write(html_doc)
print("catch_pct=%.1f caught=%d flee=%d esc=%d miss=%d restarts=%d" % (catch_pct, total_caught, total_flee, total_esc, total_miss, restarts))
print("speed_flat=%s  hi_prob_flee=%d  esc:flee=%.2f  losses=%d  summaries=%d" % (speed_flat, hi_prob_flee, esc_flee_ratio, len(losses), len(summaries)))
print("exposure=", dict(exposure))
print("flee_by_bucket=", dict(loss_by_b))
print("OUT=", OUT)
