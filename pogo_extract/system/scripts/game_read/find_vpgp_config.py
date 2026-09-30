"""Runtime RE: dump the Pokemod VPGP3 agent's DECRYPTED config string table from
PoGo live memory. readByteArray returns null on Vector-mapped ranges, but
readUtf8String works, so we WALK each config range string-by-string. Locates ranges
via distinctive markers (reconnect_when_in_set / vpgp / auto_*), excludes the huge GC
heaps, dumps every null-terminated string, saves to disk, prints config-looking ones.
READ-ONLY."""
import sys, os, re
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402
OUT = os.path.join(ROOT, "system", "analysis", "pokemod", "vpgp_mem.txt")

JS = r"""
function hexOf(s){var h=[];for(var i=0;i<s.length;i++){var c=s.charCodeAt(i).toString(16);h.push(c.length<2?"0"+c:c);}return h.join(" ");}
rpc.exports.findStr=function(needle){
  var pat=hexOf(needle);var out=[];
  Process.enumerateRanges("r--").forEach(function(r){ if(r.file||r.size<256||r.size>268435456)return;
    try{var h=Memory.scanSync(r.base,r.size,pat);if(h.length){out.push({rbase:r.base.toString(),rsize:r.size,hits:h.length,addr:h[0].address.toString()});}}catch(e){}});
  return out;
};
rpc.exports.diag=function(addrStr){
  var a=ptr(addrStr);var r={};
  try{r.utf8=a.readUtf8String(80);}catch(e){r.utf8err=e.message;}
  try{var b=a.readByteArray(48);r.ba=b?("got "+b.byteLength+" bytes"):"null";}catch(e){r.baerr=e.message;}
  try{r.u8=a.readU8();}catch(e){r.u8err=e.message;}
  return r;
};
rpc.exports.walkStrings=function(baseStr,size,minLen){
  var base=ptr(baseStr);var out=[];var i=0;var total=Math.min(size,4194304);var iter=0;
  while(i<total && iter<3000000){ iter++;
    var s=null;try{s=base.add(i).readUtf8String();}catch(e){s=null;}
    if(s===null||s.length===0){i+=1;continue;}
    if(s.length>=minLen)out.push(s);
    var adv=1;try{adv=unescape(encodeURIComponent(s)).length+1;}catch(e){adv=s.length+1;}
    i+=adv;
    if(out.length>40000)break;
  }
  return {strings:out,iters:iter};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        markers = ["reconnect_when_in_set", "vpgp", "Spacial", "auto_spin", "auto_catch",
                   "catch_delay", "spin_delay", "spin_when", "catch_when"]
        ranges = {}
        diag_addr = None
        for mk in markers:
            for r in sc.exports_sync.find_str(mk):
                ranges.setdefault(r["rbase"], r)
                if mk == "reconnect_when_in_set" and not diag_addr:
                    diag_addr = r["addr"]
        if diag_addr:
            print("diag @", diag_addr, "->", sc.exports_sync.diag(diag_addr))
        small = {rb: r for rb, r in ranges.items() if r["rsize"] < 8 * 1024 * 1024}
        print(f"\nwalking {len(small)} small ranges (excluded {len(ranges)-len(small)} huge GC heaps):")
        allstr = []
        for rb, r in small.items():
            res = sc.exports_sync.walk_strings(rb, r["rsize"], 3)
            print(f"  {rb} size {r['rsize']}: {len(res['strings'])} strings ({res['iters']} iters)")
            allstr += res["strings"]
        sess.detach()
        seen = set(); uniq = []
        for s in allstr:
            if s not in seen:
                seen.add(s); uniq.append(s)
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            f.write("\n".join(uniq))
        print(f"\ndumped {len(uniq)} unique strings -> {OUT}")
        rx = re.compile(r"(catch|spin|delay|interval|range|ball|berry|throw|radius|cooldown|reconnect|vpgp|vgp|auto|enabl|disabl|\bmax|\bmin|speed|fast|slow|distance|encounter|when_in|setting|config|mode|tick|rate|_ms|_s\b|spawn|stop|nearby|button|haptic|notif|sleep|scan)", re.I)
        cfg = [s for s in uniq if rx.search(s) and 2 < len(s) < 80]
        print(f"\n=== {len(cfg)} config-looking strings ===")
        for s in cfg[:300]:
            print("  ", s)
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()
