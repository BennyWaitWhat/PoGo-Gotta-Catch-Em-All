"""Turn system/analysis/game_limits.json (from dump_game_limits.py) into a readable HTML page.

Every number shown is read from the dump; the headline rows only add plain-English names and unit conversions.
"""
import html
from datetime import datetime, timezone
import json
import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
SRC = os.path.join(ROOT, "system", "analysis", "game_limits.json")
OUT = os.path.join(ROOT, "system", "analysis", "game_limits.html")
MY_JOYSTICK = "com.theappninjas.fakegpsjoystick"   # installed on the phone (pm list packages, 2026-09-24)

SECRET = re.compile(r"ApiKey|Token|Secret|ClientId|AllowList|Url$", re.I)
# whole settings objects that are visuals, AR, ads or telemetry -- kept in "Everything", left out of the highlights
NOISE = re.compile(r"^(BreadPokemonScaling|BreadMove|Sourdough|BattleAnimation|BattleVisual|PokeballThrowProperty|ARPhoto|ArMapping|Ardk|"
                   r"Monodepth|Optimizations|Advanced|Iris|Photo|Camera|Avatar|Sticker|Haptics|Telemetry|Sponsored|Addressable|"
                   r"ItemInventoryUpdate|Tutorials|VerboseLog|PartyDarkLaunch|Funnel|.*FeatureFlag)", re.I)
NOISE_LEAF = re.compile(r"Flyout|Flyin|CrossFade|Animation|Probability|Music|Weight$|Flag$|StepNumber|^Event$|^Source$|Type$|"
                        r"Multiplier$|ScoreBase$|Bounds$", re.I)
NOISE_PATH = re.compile(r"ItemRequirement|LootItem|XpRewardV2Thresholds|VsSeekerSchedules|NeutralAvatar|RankNum|RequiredExp|CpMultiplier")

WORDS = {
    "Speed, walking & distance": {"speed", "driving", "idle", "velocity", "walk", "walking", "km", "distance", "dist", "travel",
                                  "drift", "breadcrumb", "fitness"},
    "Ranges & radii": {"range", "radius", "meters", "visible", "nearby", "panning"},
    "Timers & cooldowns": {"cooldown", "interval", "timeout", "delay", "period", "duration", "refresh", "expiration", "cutoff"},
    "Caps & limits": {"max", "min", "maximum", "minimum", "limit", "cap", "threshold", "count", "quota", "daily", "capacity",
                      "base", "allowed", "hoard"},
}
TIME_UNITS = {"ms": 0.001, "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "min": 60, "minute": 60, "minutes": 60,
              "hour": 3600, "hours": 3600, "day": 86400, "days": 86400}


def tokens(leaf):
    return re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", leaf)


def walk(o, path):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        if all(not isinstance(x, (dict, list)) for x in o):
            yield path, o
        else:
            for i, x in enumerate(o):
                yield from walk(x, f"{path}[{i}]")
    else:
        yield path, o


def num(v):
    """int64 fields come out of the dump as strings."""
    if isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v):
        return float(v) if "." in v else int(v)
    return v


def dur(sec):
    for lim, div, u in ((120, 1, "s"), (7200, 60, "min"), (172800, 3600, "h")):
        if sec < lim:
            return f"{sec / div:.3g} {u}"
    return f"{sec / 86400:.3g} days"


def unit(leaf, v):
    """A second, human unit where the field name says what the number is."""
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
        return ""
    t = [x.lower() for x in tokens(leaf)]
    last, per = (t[-1] if t else ""), (len(t) > 1 and t[-2] in ("per", "of"))   # a rate or a clock hour, not a duration
    if 1e12 <= v <= 4.2e12:   # epoch milliseconds
        return datetime.fromtimestamp(v / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if re.search(r"(Start|End)Minute$", leaf) and v < 1440:
        return f"clock {int(v) // 60:02d}:{int(v) % 60:02d}"
    if "MetersPerSecond" in leaf or leaf.endswith("MPerS"):
        return f"{v * 3.6:.1f} km/h, {v * 2.23694:.1f} mph"
    if last in TIME_UNITS and not per:
        s = v * TIME_UNITS[last]
        return dur(s) if (last == "ms" and v >= 1000) or s >= 120 else ""
    if last in ("meters", "m") and v >= 1000:
        return f"{v / 1000:g} km, {v / 1609.34:.1f} mi"
    if last == "km":
        return f"{v / 1.60934:.1f} mi"
    return ""


def classify(leaf):
    t = [x.lower() for x in tokens(leaf)]
    w, last = set(t), (t[-1] if t else "")
    per, clock = len(t) > 1 and t[-2] == "per", len(t) > 1 and t[-2] == "of"
    if w & WORDS["Speed, walking & distance"] or "MetersPerSecond" in leaf:
        return "Speed, walking & distance"
    if w & WORDS["Ranges & radii"] or (last == "m" and not per and not w & WORDS["Timers & cooldowns"]):
        return "Ranges & radii"
    if w & WORDS["Timers & cooldowns"] or (last in TIME_UNITS and not per and not clock):
        return "Timers & cooldowns"
    if w & WORDS["Caps & limits"] or per:
        return "Caps & limits"
    return None


def fmt(v):
    if isinstance(v, list):
        if any(x == "<unreadable>" for x in v):
            return f"(list of {len(v)} enum values, not decoded)"
        s = json.dumps(v)
    elif isinstance(v, str):
        s = v
    else:
        s = json.dumps(v)
    return html.escape(s if len(s) <= 200 else s[:200] + " ...")


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    g = d.get("global_settings") or {}
    gm = {t["type"].replace("Proto", ""): t.get("data") or {} for t in d.get("game_master_settings") or []}

    def get(obj, *keys):
        for k in keys:
            obj = (obj or {}).get(k)
        return num(obj)

    rows = []   # (group, path-within-group, value)
    for p, v in walk(g, ""):
        parts = p.lstrip(".").split(".", 1)
        grp = "Server settings / " + parts[0] if len(parts) > 1 else "Server settings"
        rows.append((grp, parts[1] if len(parts) > 1 else parts[0], v))
    for t, data in gm.items():
        for p, v in walk(data, ""):
            rows.append((t, p.lstrip("."), v))
    rows = [(grp, p, "(hidden)" if SECRET.search(p.split(".")[-1]) else num(v)) for grp, p, v in rows]

    cats = {c: [] for c in WORDS}
    for grp, p, v in rows:
        obj = grp.replace("Server settings / ", "")
        leaf = re.sub(r"\[\d+\]$", "", p.split(".")[-1])
        if NOISE.search(obj) or NOISE_LEAF.search(leaf) or NOISE_PATH.search(p) or not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        c = classify(leaf)
        if c:
            cats[c].append((f"{obj}.{p}", leaf, v))

    gps, mp, fort = g.get("GpsSettings") or {}, g.get("MapSettings") or {}, g.get("FortSettings") or {}
    rc, soft = gm.get("RoutesCreationSettings") or {}, gm.get("SoftSfidaSettings") or {}
    enc, lvl, inv = gm.get("EncounterSettings") or {}, gm.get("PlayerLevelSettings") or {}, gm.get("InventorySettings") or {}
    drv = gps.get("DrivingWarningSpeedMetersPerSecond")
    idle = gps.get("IdleThresholdSpeedMetersPerSecond")
    rec = rc.get("MaxRecordingSpeedMetersPerSecond")

    def kmh(ms):
        return f"{ms:g} m/s = <b>{ms * 3.6:.1f} km/h</b> ({ms * 2.23694:.1f} mph)" if isinstance(ms, (int, float)) else "?"

    speed = [
        ("&ldquo;You&rsquo;re going too fast&rdquo; warning", "GpsSettings.DrivingWarningSpeedMetersPerSecond", kmh(drv)),
        ("&hellip; judged from", "DrivingSpeedSampleCount, DrivingSpeedSampleIntervalSeconds",
         f"{gps.get('DrivingSpeedSampleCount')} speed samples, {gps.get('DrivingSpeedSampleIntervalSeconds')} s apart"),
        ("&hellip; shown again at most every", "DrivingWarningCooldownMinutes", f"{gps.get('DrivingWarningCooldownMinutes')} min"),
        ("&ldquo;Idle&rdquo; speed threshold", "GpsSettings.IdleThresholdSpeedMetersPerSecond",
         f"{kmh(idle)}, over {gps.get('IdleSpeedSampleCount')} samples {gps.get('IdleSampleIntervalSeconds')} s apart "
         f"({gps.get('IdleThresholdDurationSeconds')} s)"),
        ("Route recording top speed", "RoutesCreationSettings.MaxRecordingSpeedMetersPerSecond", kmh(rec)),
        ("Route GPS drift allowed", "RoutesCreationSettings.AllowableGpsDriftMeters", f"{rc.get('AllowableGpsDriftMeters')} m"),
        ("Buddy heart from walking", "BuddyWalkSettings.KmRequiredPerAffectionPoint",
         f"{get(gm, 'BuddyWalkSettings', 'KmRequiredPerAffectionPoint')} km"),
        ("Adventure Sync weekly goals", "BackgroundModeSettings.WeeklyFitnessGoalLevel1..4DistanceKm",
         " / ".join(str(get(gm, "BackgroundModeSettings", f"WeeklyFitnessGoalLevel{i}DistanceKm")) for i in range(1, 5)) + " km"),
        ("Max Particles walking goal", "MpSharedSettings.NumMetersGoal, NumMpFromWalkQuest",
         f"{get(gm, 'MpSharedSettings', 'NumMetersGoal')} m walked = {get(gm, 'MpSharedSettings', 'NumMpFromWalkQuest')} MP"),
    ]
    ranges = [
        ("Pokémon shown on the map", "MapSettings.PokemonVisibleRange", f"<b>{mp.get('PokemonVisibleRange')} m</b>"),
        ("Pokémon you can open (encounter)", "MapSettings.EncounterRangeMeters", f"<b>{mp.get('EncounterRangeMeters')} m</b>"),
        ("Map refresh from the server", "GetMapObjectsMaxRefreshSeconds, GetMapObjectsMinDistanceMeters",
         f"longest gap <b>{mp.get('GetMapObjectsMaxRefreshSeconds')} s</b>; moving <b>{mp.get('GetMapObjectsMinDistanceMeters')} m</b> also triggers one"),
        ("Spin a PokéStop / use a gym", "FortSettings.InteractionRangeMeters", f"<b>{fort.get('InteractionRangeMeters')} m</b>"),
        ("Far interaction (e.g. raid lobby from the map)", "FortSettings.FarInteractionRangeMeters",
         f"{fort.get('FarInteractionRangeMeters')} m"),
        ("Remote interaction", "FortSettings.RemoteInteractionRangeMeters", f"{fort.get('RemoteInteractionRangeMeters')} m"),
        ("Showcase catch prompt", "ContestSettings.MaxCatchPromptRange", f"{get(gm, 'ContestSettings', 'MaxCatchPromptRange')} m"),
        ("Power Spot &ldquo;nearby&rdquo; (Bread = Max Battles)", "BreadSharedSettings.MaxRangeForNearbyStateMeters",
         f"{get(gm, 'BreadSharedSettings', 'MaxRangeForNearbyStateMeters')} m"),
    ]
    catching = [
        ("Throw bonus thresholds", "EncounterSettings.Nice/Great/ExcellentThrowThreshold",
         f"Nice {enc.get('NiceThrowThreshold')} &middot; Great {enc.get('GreatThrowThreshold')} &middot; Excellent {enc.get('ExcellentThrowThreshold')}"),
        ("Curveball (spin) bonus threshold", "EncounterSettings.SpinBonusThreshold", f"{enc.get('SpinBonusThreshold')}"),
        ("Wild Pokémon level stops rising at trainer level", "PlayerLevelSettings.MaxEncounterPlayerLevel", f"{lvl.get('MaxEncounterPlayerLevel')}"),
        ("Research-reward level stops rising at", "PlayerLevelSettings.MaxQuestEncounterPlayerLevel", f"{lvl.get('MaxQuestEncounterPlayerLevel')}"),
        ("Egg hatch level stops rising at", "PlayerLevelSettings.MaxEggPlayerLevel", f"{lvl.get('MaxEggPlayerLevel')}"),
        ("Pokémon storage cap / starting size", "InventorySettings.MaxPokemon, BasePokemon", f"{inv.get('MaxPokemon')} / {inv.get('BasePokemon')}"),
        ("Item bag cap / starting size", "InventorySettings.MaxBagItems, BaseBagItems", f"{inv.get('MaxBagItems')} / {inv.get('BaseBagItems')}"),
        ("Egg slots", "InventorySettings.BaseEggs, SpecialEggOverflowSpots", f"{inv.get('BaseEggs')} + {inv.get('SpecialEggOverflowSpots')} overflow"),
        ("Rewarded GO Battle League sets per day", "CombatGlobalSettings.MaximumDailyRewardedBattles",
         f"{get(g, 'CombatGlobalSettings', 'MaximumDailyRewardedBattles')}"),
        ("Remote Raid Passes held", "RaidClientSettings.MaxRemoteRaidPasses", f"{get(gm, 'RaidClientSettings', 'MaxRemoteRaidPasses')}"),
        ("Max Particles cap / daily limit", "MpSharedSettings.MpCapacity, MpBaseDailyLimit",
         f"{get(gm, 'MpSharedSettings', 'MpCapacity')} / {get(gm, 'MpSharedSettings', 'MpBaseDailyLimit')}"),
    ]
    black = g.get("ClientAppBlacklist") or []
    cheat = [
        ("Blacklisted apps (sent by the server)", "ClientAppBlacklist",
         "<br>".join(html.escape(x) for x in black) + f"<br><span class=u>Your joystick is <code>{MY_JOYSTICK}</code>: "
         + ("<b>ON the list</b>" if MY_JOYSTICK in black else "not on the list") + "</span>"),
        ("&ldquo;SoftSfida&rdquo; pacing (Sfida = the Go Plus; by name, a software Go Plus)", "SoftSfidaSettings.CatchActionDelayMs, SpinActionDelayMs",
         f"one catch every {get(soft, 'CatchActionDelayMs') / 1000:g} s, one spin every {get(soft, 'SpinActionDelayMs') / 1000:g} s, "
         f"{get(soft, 'GeofenceSizeM')} m geofence, trainer level {get(soft, 'MinPlayerLevel')}+"
         if isinstance(get(soft, "CatchActionDelayMs"), (int, float)) else "?"),
        ("Route: max distance from the anchor stops", "RoutesCreationSettings.MaxDistanceFromAnchorPoisM", f"{rc.get('MaxDistanceFromAnchorPoisM')} m"),
    ]

    P = []
    P.append(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PoGo Limits</title>
<style>
:root {{ --bg:#fafaf8; --fg:#1d1d1b; --mut:#6b6b66; --line:#e4e2dc; --card:#ffffff; --hl:#fff4d6; --bad:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141413; --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; --hl:#3a3220; --bad:#ff8a80; }} }}
:root[data-theme="dark"] {{ --bg:#141413; --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; --hl:#3a3220; --bad:#ff8a80; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:1000px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} h2 {{ font-size:18px; margin:32px 0 8px; }} .mut, .u {{ color:var(--mut); }} .u {{ font-size:13px; }}
.tw {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--card); }}
table {{ width:100%; border-collapse:collapse; }}
td, th {{ padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
tr:last-child td {{ border-bottom:0; }}
th {{ font-size:13px; color:var(--mut); font-weight:600; }}
td.v {{ font-variant-numeric:tabular-nums; }} td.p, code {{ font-family:ui-monospace,Consolas,monospace; font-size:12.5px; word-break:break-all; }}
td.p {{ color:var(--mut); }}
.note {{ background:var(--hl); border:1px solid var(--line); border-radius:8px; padding:10px 12px; margin:14px 0; }}
details {{ background:var(--card); border:1px solid var(--line); border-radius:8px; margin:6px 0; }}
summary {{ cursor:pointer; padding:8px 12px; font-weight:600; }}
details table {{ border-top:1px solid var(--line); }}
input {{ width:100%; padding:9px 12px; font-size:15px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--fg); margin-bottom:8px; }}
@media (max-width:640px) {{ td.p {{ display:none; }} th.p {{ display:none; }} }}
</style></head><body><main>
<h1>Pokémon GO limits &amp; thresholds</h1>
<div class="mut">Read from the running game on your Pixel (client {html.escape(str(g.get('MinimumClientVersion', '?')))}) at {html.escape(d.get('read_at', ''))}:
the settings the server sends at login plus the game master&rsquo;s {len(gm)} settings objects, {len(rows)} values in all.
The numbers are exact. The plain-English names come from the field names.
Code names: Bread = Max Battles &amp; Power Spots, Sfida = Go Plus, Beluga = Let&rsquo;s Go transfer.</div>
<div class="note"><b>Not in the game, so not listed:</b> limits that only the server enforces. That includes the speed above which walking
stops counting for eggs, buddy candy and Adventure Sync (players measure it at about 10.5 km/h), soft-ban and teleport cooldowns,
and catch or spin rate limits. The game can&rsquo;t show those numbers because it never receives them.</div>""")

    def table(title, items, sub=""):
        P.append(f"<h2>{title}</h2>{sub}<div class=tw><table><tr><th>What</th><th class=p>Setting</th><th>Value</th></tr>")
        for what, field, val in items:
            P.append(f"<tr><td>{what}</td><td class=p>{html.escape(field)}</td><td class=v>{val}</td></tr>")
        P.append("</table></div>")

    table("Speed &amp; walking", speed)
    table("Ranges", ranges)
    table("Catching, levels &amp; storage", catching)
    table("Anti-cheat &amp; automation", cheat)

    P.append("<h2>Every limit-type value, grouped</h2><div class=mut>All numeric settings whose names say speed, distance, range, "
             "time, or max/min/limit. Visual, AR, ad and telemetry settings are left out here but are still in the full list below.</div>")
    for c, items in cats.items():
        P.append(f"<details><summary>{html.escape(c)} <span class=mut>({len(items)})</span></summary><div class=tw><table>")
        for path, leaf, v in items:
            u = unit(leaf, v)
            P.append(f"<tr><td class=p style='color:var(--fg)'>{html.escape(path)}</td><td class=v>{fmt(v)}"
                     f"{(' <span class=u>(' + u + ')</span>') if u else ''}</td></tr>")
        P.append("</table></div></details>")

    P.append(f"<h2>Everything ({len(rows)} values)</h2><input id=q type=search placeholder='Filter, e.g. range, speed, raid, egg, cooldown'>")
    groups = {}
    for grp, p, v in rows:
        groups.setdefault(grp, []).append((p, v))
    for grp in sorted(groups, key=lambda x: (not x.startswith("Server"), x.lower())):
        items = groups[grp]
        P.append(f"<details class=all><summary>{html.escape(grp)} <span class=mut>({len(items)})</span></summary><div class=tw><table>")
        for p, v in items:
            u = unit(re.sub(r"\[\d+\]$", "", p.split(".")[-1]), v)
            P.append(f"<tr><td class=p style='color:var(--fg)'>{html.escape(p)}</td><td class=v>{fmt(v)}"
                     f"{(' <span class=u>(' + u + ')</span>') if u else ''}</td></tr>")
        P.append("</table></div></details>")
    P.append("""<script>
document.getElementById('q').addEventListener('input', function (e) {
  var q = e.target.value.toLowerCase().trim();
  document.querySelectorAll('details.all').forEach(function (d) {
    var head = d.querySelector('summary').textContent.toLowerCase().indexOf(q) >= 0, any = head;
    d.querySelectorAll('tr').forEach(function (r) {
      var hit = !q || head || r.textContent.toLowerCase().indexOf(q) >= 0;
      r.style.display = hit ? '' : 'none'; any = any || hit;
    });
    d.style.display = any || !q ? '' : 'none'; d.open = !!q && any;
  });
});
</script></main></body></html>""")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(P))
    print(f"wrote {OUT}: " + ", ".join(f"{c} {len(v)}" for c, v in cats.items()) + f"; {len(rows)} values, {len(groups)} groups")


if __name__ == "__main__":
    main()
