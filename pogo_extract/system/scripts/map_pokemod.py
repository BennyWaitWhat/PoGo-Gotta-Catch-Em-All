"""Map EVERY Pokemod module out of its decrypted agent bundle into an implementation reference.

The bundle (system/analysis/pokemod/agent_js_0x*.js, ~3.5MB of browserify-minified JS) is the
authoritative answer to "how does Pokemod actually do X". Reading it ad hoc per feature was slow and
error-prone: I emulated Perfect Throw by rewriting the outgoing proto, which was simply the wrong
mechanism -- their module hooks the CLIENT so the game computes the result itself. Their real class
is `PerfectedThrow`, which a search for "PerfectThrow" never finds.

So: parse it once, list every module with the exact il2cpp classes and methods it touches, and work
from that instead of guessing.

Emits a JSON map and a self-contained HTML reference. READ-ONLY -- touches no running game.
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir))
SRC = os.path.join(ROOT, "system", "analysis", "pokemod")
OUT_JSON = os.path.join(SRC, "pokemod_module_map.json")
OUT_HTML = os.path.join(ROOT, "POKEMOD_IMPLEMENTATION_MAP.html")

# A module is a `class X extends <ModuleBase alias>`; the alias is minified per-file so match loosely.
RE_CLASS = re.compile(r"class\s+([A-Za-z0-9_]+)\s+extends\s+([A-Za-z0-9_$.]+)\s*\{")
RE_USE = re.compile(r'use\("([^"]+)"\)')
# ditto style: <expr>.<Method>.attach( / .replace( / .implement(
RE_HOOK = re.compile(r"([A-Za-z0-9_$]+)\.([A-Za-z0-9_<>$]+)\.(attach|replace|implement)\s*\(")
RE_TOGGLE = re.compile(r'addToggle\("([^"]+)"')
RE_SLIDER = re.compile(r'addSlider\("([^"]+)"')
RE_CHEAT = re.compile(r'addCheatCode\("([^"]+)"')
RE_PREF = re.compile(r'(?:get|set)\("([A-Za-z0-9_]+)"')


def load_bundle():
    """Concatenate every extracted range; the biggest one holds the module bodies."""
    parts = []
    for fn in sorted(os.listdir(SRC)):
        if fn.startswith("agent_js_") and fn.endswith(".js"):
            p = os.path.join(SRC, fn)
            parts.append((fn, io.open(p, encoding="utf-8", errors="replace").read()))
    return parts


def body_of(src, start):
    """Brace-match a class body so a module's hooks are not attributed to its neighbour."""
    i = src.find("{", start)
    if i < 0:
        return ""
    depth = 0
    for j in range(i, min(len(src), i + 400000)):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    return src[i:i + 40000]


def describe(name, body):
    uses = sorted(set(RE_USE.findall(body)))
    hooks = []
    for var, meth, kind in RE_HOOK.findall(body):
        if meth in ("default", "prototype"):
            continue
        hooks.append({"method": meth, "kind": kind})
    # de-dup preserving order
    seen, uniq = set(), []
    for h in hooks:
        k = (h["method"], h["kind"])
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return {
        "module": name,
        "classes": uses,
        "hooks": uniq,
        "toggles": sorted(set(RE_TOGGLE.findall(body))),
        "sliders": sorted(set(RE_SLIDER.findall(body))),
        "cheatCodes": sorted(set(RE_CHEAT.findall(body))),
        "prefs": sorted(set(RE_PREF.findall(body)))[:20],
        "size": len(body),
    }


def main():
    mods, skipped = {}, 0
    for fn, src in load_bundle():
        for m in RE_CLASS.finditer(src):
            name, base = m.group(1), m.group(2)
            body = body_of(src, m.end() - 1)
            if not body:
                continue
            info = describe(name, body)
            # Keep anything that actually hooks the game or exposes UI; drop pure helper classes.
            if not (info["classes"] or info["hooks"] or info["toggles"] or info["cheatCodes"]):
                skipped += 1
                continue
            info["base"] = base
            info["file"] = fn
            prev = mods.get(name)
            if prev is None or info["size"] > prev["size"]:
                mods[name] = info

    ordered = sorted(mods.values(), key=lambda d: -(len(d["classes"]) + len(d["hooks"])))
    io.open(OUT_JSON, "w", encoding="utf-8").write(json.dumps(ordered, indent=1))
    print(f"modules with hooks/UI: {len(ordered)}   (skipped {skipped} helper classes)")
    print(f"json -> {OUT_JSON}")

    rows = []
    for d in ordered:
        cls = "".join(f"<li><code>{c}</code></li>" for c in d["classes"]) or "<li class='none'>-</li>"
        hk = "".join(
            f"<li><code>{h['method']}</code> <span class='k k-{h['kind']}'>{h['kind']}</span></li>"
            for h in d["hooks"]) or "<li class='none'>-</li>"
        extras = []
        if d["toggles"]:
            extras.append("<b>toggles:</b> " + ", ".join(d["toggles"]))
        if d["sliders"]:
            extras.append("<b>sliders:</b> " + ", ".join(d["sliders"]))
        if d["cheatCodes"]:
            extras.append("<b>cheat codes:</b> " + ", ".join(d["cheatCodes"]))
        if d["prefs"]:
            extras.append("<b>prefs:</b> " + ", ".join(d["prefs"]))
        rows.append(
            f"<tr><td class='mod'>{d['module']}</td>"
            f"<td><ul>{cls}</ul></td><td><ul>{hk}</ul></td>"
            f"<td class='ex'>{'<br>'.join(extras) or '-'}</td></tr>")

    html = """<title>Pokemod Implementation Map</title>
<style>
:root{--bg:#ffffff;--fg:#1a1d21;--mut:#5b6674;--line:#e3e7ec;--acc:#b8860b;--card:#f7f9fb;}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
--bg:#0e1116;--fg:#e6edf3;--mut:#8b98a8;--line:#232a33;--acc:#ffcb05;--card:#161b22;}}
:root[data-theme="dark"]{--bg:#0e1116;--fg:#e6edf3;--mut:#8b98a8;--line:#232a33;--acc:#ffcb05;--card:#161b22;}
body{background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding:32px 20px 64px;}
.wrap{max-width:1180px;margin:0 auto;}
h1{font-size:26px;margin:0 0 6px;} .sub{color:var(--mut);margin:0 0 26px;}
.note{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--acc);padding:12px 16px;border-radius:6px;margin:0 0 26px;color:var(--mut);}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px;}
table{border-collapse:collapse;width:100%;min-width:900px;background:var(--card);}
th{text-align:left;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--acc);padding:10px 14px;border-bottom:1px solid var(--line);}
td{padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top;}
tr:last-child td{border-bottom:none;}
.mod{font-weight:600;white-space:nowrap;}
ul{margin:0;padding-left:15px;} li{margin:1px 0;}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;}
.none{list-style:none;margin-left:-15px;color:var(--mut);}
.ex{color:var(--mut);font-size:13px;max-width:320px;}
.k{font-size:10px;padding:1px 5px;border-radius:3px;border:1px solid var(--line);}
.k-replace{color:#e5534b;} .k-attach{color:#3fb950;} .k-implement{color:#a371f7;}
</style>
<div class="wrap">
<h1>Pokemod Implementation Map</h1>
<p class="sub">Every module in the decrypted agent bundle, with the il2cpp classes and methods it hooks.</p>
<div class="note">Extracted from Pokemod's own agent bundle. <b>replace</b> swaps the method outright,
<b>attach</b> keeps the original and edits arguments or the return value. Hook names are the
game's real method names, so they can be resolved directly by name rather than guessed.</div>
<div class="scroll"><table>
<tr><th>Module</th><th>il2cpp classes used</th><th>methods hooked</th><th>settings / prefs</th></tr>
""" + "\n".join(rows) + """
</table></div></div>"""
    io.open(OUT_HTML, "w", encoding="utf-8").write(html)
    print(f"html -> {OUT_HTML}")

    print("\ntop modules by hook count:")
    for d in ordered[:14]:
        print(f"  {d['module']:<24} classes={len(d['classes']):<3} hooks={len(d['hooks'])}")


main()
