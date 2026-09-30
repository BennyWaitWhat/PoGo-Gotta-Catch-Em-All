"""Runtime RE: the Pokemod agent (main_agent/vpgp_agent) is a browserify-bundled JS app,
decrypted in PoGo memory. Locate the range(s) holding the bundle (browserify marker
'(require,module,exports)') and walk them out to .js files so the source — including the
PokemodSettings module + VPGP catch/spin logic — can be read. READ-ONLY."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402
OUTDIR = os.path.join(ROOT, "system", "analysis", "pokemod")

JS = r"""
function hexOf(s){var h=[];for(var i=0;i<s.length;i++){var c=s.charCodeAt(i).toString(16);h.push(c.length<2?"0"+c:c);}return h.join(" ");}
rpc.exports.findStr=function(needle){
  var pat=hexOf(needle);var out=[];
  Process.enumerateRanges("r--").forEach(function(r){ if(r.file||r.size<1024||r.size>268435456)return;
    try{var h=Memory.scanSync(r.base,r.size,pat);if(h.length){out.push({rbase:r.base.toString(),rsize:r.size,hits:h.length});}}catch(e){}});
  return out;
};
rpc.exports.walkAll=function(baseStr,size){
  var base=ptr(baseStr);var out=[];var i=0;var total=Math.min(size,12582912);var iter=0;
  while(i<total && iter<12000000){iter++;
    var s=null;try{s=base.add(i).readUtf8String();}catch(e){s=null;}
    if(s===null||s.length===0){i+=1;continue;}
    out.push(s);
    var adv=1;try{adv=unescape(encodeURIComponent(s)).length+1;}catch(e){adv=s.length+1;}
    i+=adv;
    if(out.length>600000)break;
  }
  return {strings:out,iters:iter};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        rngs = {}
        for mk in ["(require,module,exports)", "PokemodSettings", "toast.vpgp"]:
            for r in sc.exports_sync.find_str(mk):
                rngs.setdefault(r["rbase"], r)
        rngs = {rb: r for rb, r in rngs.items() if r["rsize"] < 16 * 1024 * 1024}
        print(f"{len(rngs)} JS-bundle candidate ranges")
        os.makedirs(OUTDIR, exist_ok=True)
        for rb, r in rngs.items():
            res = sc.exports_sync.walk_all(rb, r["rsize"])
            blob = "\n".join(res["strings"])
            fn = os.path.join(OUTDIR, f"agent_js_{rb}.js")
            with open(fn, "w", encoding="utf-8") as f:
                f.write(blob)
            print(f"  {rb} size {r['rsize']}: {len(res['strings'])} strings, {len(blob)} bytes -> {os.path.basename(fn)}")
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()
