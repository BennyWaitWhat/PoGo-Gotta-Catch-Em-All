"""Download EVERY Pokemon GO icon (pm*.icon.png) from PokeMiners/pogo_assets that is not already in
pokegenie_work/sprites. Live tree listing (abort if truncated), same raw URL scheme as dl_now.py,
each file verified as PNG with the exact upstream byte size. Never overwrites existing files."""
import json, os, re, sys, time, threading, urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor

SPR = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pokegenie_work\sprites"
SCR = os.path.dirname(os.path.abspath(__file__))
API = "https://api.github.com/repos/PokeMiners/pogo_assets/git/trees/master?recursive=1"
RAW = "https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/"
D256 = "Images/Pokemon - 256x256/Addressable Assets/"
DREG = "Images/Pokemon/Addressable Assets/"
ICON = re.compile(r"pm(\d+).*\.icon\.png$")

H = {"User-Agent": "pg-sprites", "Accept": "application/vnd.github+json"}
_cache = {}

def subtree(sha):
    """One NON-recursive tree level (the recursive whole-repo listing 500s server-side)."""
    if sha not in _cache:
        for attempt in range(4):
            try:
                url = "https://api.github.com/repos/PokeMiners/pogo_assets/git/trees/" + urllib.parse.quote(sha)
                t = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=120))
                break
            except urllib.error.HTTPError as e:
                if e.code in (500, 502, 503) and attempt < 3:
                    time.sleep(3 * (attempt + 1)); continue
                raise
        if t.get("truncated"):
            sys.exit("ABORT: live tree listing is truncated at " + sha)
        _cache[sha] = t["tree"]
    return _cache[sha]

def folder(path):
    sha = "master"
    for part in path.strip("/").split("/"):
        hit = [e for e in subtree(sha) if e["path"] == part and e["type"] == "tree"]
        if not hit:
            sys.exit("ABORT: upstream folder missing: " + path)
        sha = hit[0]["sha"]
    return {e["path"]: e for e in subtree(sha) if e["type"] == "blob" and ICON.match(e["path"])}

d256 = folder(D256)
dreg = folder(DREG)
json.dump({"d256": d256, "dreg": dreg}, open(os.path.join(SCR, "tree_live.json"), "w", encoding="utf-8"))

# which upstream folder the existing local files came from (byte-size match), so new files match them
local = {f: os.path.getsize(os.path.join(SPR, f)) for f in os.listdir(SPR) if f.endswith(".png")}
m256 = sum(1 for f, s in local.items() if f in d256 and d256[f]["size"] == s)
mreg = sum(1 for f, s in local.items() if f in dreg and dreg[f]["size"] == s)
print(f"live tree ok | 256-folder icons {len(d256)} | regular-folder icons {len(dreg)} | local pngs {len(local)}")
print(f"local files byte-identical to: 256-folder {m256}, regular-folder {mreg}")
src = d256 if m256 >= mreg else dreg
srcdir = D256 if src is d256 else DREG
extra = {n: b for n, b in (dreg if src is d256 else d256).items() if n not in src}
print(f"using {srcdir!r}; names only in the other folder: {len(extra)}")
allicons = dict(extra)
allicons.update(src)
allicons = {n: (b, (srcdir if n in src else (DREG if srcdir == D256 else D256))) for n, b in allicons.items()}

up_dex = {int(ICON.match(n).group(1)) for n in allicons}
todo = [(n, b, d) for n, (b, d) in allicons.items() if n not in local]
print(f"upstream species {len(up_dex & set(range(1, 1026)))}/1025 | to download {len(todo)} files, "
      f"{sum(b['size'] for n, b, d in todo) / 1e6:.1f} MB")
stale = sum(1 for n, (b, d) in allicons.items() if n in local and local[n] != b["size"] and d == srcdir)
print(f"existing local files whose upstream copy changed since (left untouched): {stale}")

lock = threading.Lock(); ok = []; bad = []

def go(item):
    n, b, d = item
    url = RAW + urllib.parse.quote(d + n)
    for attempt in range(4):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pg-sprites"}), timeout=45).read()
            if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) == b["size"]:
                tmp = os.path.join(SPR, n + ".part")
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(SPR, n))
                with lock: ok.append(n)
                return
            err = f"bad content ({len(data)} B vs {b['size']})"
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
        except Exception as e:
            err = type(e).__name__
        time.sleep(1.5 * (attempt + 1))
    with lock: bad.append((n, err))

t0 = time.time()
with ThreadPoolExecutor(max_workers=24) as ex:
    for i, _ in enumerate(ex.map(go, todo), 1):
        if i % 300 == 0:
            print(f"  {i}/{len(todo)}  ok {len(ok)}  failed {len(bad)}  {time.time() - t0:.0f}s", flush=True)

now = [f for f in os.listdir(SPR) if f.endswith(".png")]
now_dex = {int(ICON.match(f).group(1)) for f in now if ICON.match(f)}
print(f"\nDOWNLOADED {len(ok)} | FAILED {len(bad)} {bad[:10]}")
print(f"local pngs now {len(now)} | species covered {len(now_dex & set(range(1, 1026)))}/1025 | "
      f"shiny {sum(1 for f in now if '.s.icon' in f)}")
print("upstream species still not local:", sorted(up_dex - now_dex))
print("species with no PoGo icon upstream:", sorted(set(range(1, 1026)) - up_dex))
old = json.load(open(os.path.join(SPR, "_tree_raw.json"), encoding="utf-8"))
old_n = {b["path"].rsplit("/", 1)[-1] for b in old["tree"] if b["type"] == "blob" and ICON.match(b["path"].rsplit("/", 1)[-1])}
print("new upstream icons since the Sept 2 listing:", len(set(allicons) - old_n))
