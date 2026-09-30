"""mitmproxy addon: capture all Niantic/PoGO traffic to disk."""
from pathlib import Path
import time, json
from mitmproxy import http

OUT = Path(__file__).parent / "captures"
OUT.mkdir(exist_ok=True)

INDEX = OUT / "index.jsonl"

NIANTIC_HOSTS = ("nianticlabs.com", "niantic.com", "pokemongolive.com", "nianticspatial.com", "ardk-api")

def _matches(flow: http.HTTPFlow) -> bool:
    h = flow.request.pretty_host or ""
    return any(d in h for d in NIANTIC_HOSTS)

def response(flow: http.HTTPFlow):
    if not _matches(flow):
        return
    ts = int(time.time() * 1000)
    host = flow.request.pretty_host
    path = flow.request.path[:100].replace("/", "_").replace("?", "_")
    base = f"{ts}_{host}{path}"
    req_path = OUT / f"{base}.req.bin"
    res_path = OUT / f"{base}.res.bin"
    req_path.write_bytes(flow.request.raw_content or b"")
    res_path.write_bytes(flow.response.raw_content or b"")
    entry = {
        "ts": ts,
        "method": flow.request.method,
        "url": flow.request.pretty_url,
        "host": host,
        "path": flow.request.path,
        "req_size": len(flow.request.raw_content or b""),
        "res_size": len(flow.response.raw_content or b""),
        "status": flow.response.status_code,
        "content_type": flow.response.headers.get("content-type", ""),
        "req_file": str(req_path.name),
        "res_file": str(res_path.name),
    }
    with INDEX.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[+] {flow.request.method} {flow.request.pretty_url[:120]} -> {flow.response.status_code} req={entry['req_size']}B res={entry['res_size']}B")
