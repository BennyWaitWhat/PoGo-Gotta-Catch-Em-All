"""READ-ONLY deep reflector for PoGo's Go Plus ("Sfida"/PGP) subsystem.

Iterates holo-game.dll classes, finds every Sfida/Pgp/GoPlus/autocatch/wearable
class, and dumps each one's fields (name@offset:type) + methods (ret name(params)).
Saves the full map to system/analysis/pokemod/sfida_classes.json and prints the
timing/range-relevant members (interval, range, distance, radius, scan, catch,
spin, delay, period, cooldown, countdown, etc.) so we can find the cadence/range
knobs the virtual Go Plus rides on. WRITES NOTHING to the game.
"""
import sys, os, json, re
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))  # game_read -> scripts -> system -> root
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

OUT = os.path.join(ROOT, "system", "analysis", "pokemod", "sfida_classes.json")

EXTRA_JS = r"""
var _R=null;
function _refl(){ if(_R) return _R; _ensureInit(); var il=Process.findModuleByName('libil2cpp.so'); var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _R={
    IGCC:b('il2cpp_image_get_class_count','uint32',['pointer']),
    IGC: b('il2cpp_image_get_class','pointer',['pointer','uint32']),
    CN:  b('il2cpp_class_get_name','pointer',['pointer']),
    CNS: b('il2cpp_class_get_namespace','pointer',['pointer']),
    CGF: b('il2cpp_class_get_fields','pointer',['pointer','pointer']),
    FGN: b('il2cpp_field_get_name','pointer',['pointer']),
    FGT: b('il2cpp_field_get_type','pointer',['pointer']),
    FGO: b('il2cpp_field_get_offset','uint32',['pointer']),
    CGM: b('il2cpp_class_get_methods','pointer',['pointer','pointer']),
    MGN: b('il2cpp_method_get_name','pointer',['pointer']),
    MGPC:b('il2cpp_method_get_param_count','int',['pointer']),
    MGP: b('il2cpp_method_get_param','pointer',['pointer','int']),
    MGRT:b('il2cpp_method_get_return_type','pointer',['pointer']),
    TGN: b('il2cpp_type_get_name','pointer',['pointer']),
  };
  return _R;
}
function _cs(p){ try{return p.isNull()?'':p.readCString();}catch(e){return '';} }

rpc.exports.findClasses = function(rx){
  _ensureInit(); var R=_refl(); var re=new RegExp(rx,'i');
  var n=R.IGCC(GAME_IMAGE); var out=[];
  for(var i=0;i<n;i++){ var k=R.IGC(GAME_IMAGE,i); if(k.isNull())continue; var nm=_cs(R.CN(k)); if(nm && re.test(nm)){ out.push({ns:_cs(R.CNS(k)), name:nm, addr:k.toString()}); } }
  return out;
};

rpc.exports.dumpClassByAddr = function(addrStr){
  _ensureInit(); var R=_refl(); var k=ptr(addrStr);
  var rec={ns:_cs(R.CNS(k)), name:_cs(R.CN(k)), fields:[], methods:[]};
  var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=R.CGF(k,it))&&!f.isNull()){ try{ rec.fields.push(_cs(R.FGN(f))+'@0x'+R.FGO(f).toString(16)+':'+_cs(R.TGN(R.FGT(f)))); }catch(e){} }
  var it2=Memory.alloc(Process.pointerSize); it2.writePointer(ptr(0)); var m;
  while((m=R.CGM(k,it2))&&!m.isNull()){ try{ var nm=_cs(R.MGN(m)); var pc=R.MGPC(m); var ps=[]; for(var i=0;i<pc;i++){ var p=R.MGP(m,i); ps.push(p&&!p.isNull()?_cs(R.TGN(p)):'?'); } rec.methods.push(_cs(R.TGN(R.MGRT(m)))+' '+nm+'('+ps.join(',')+')'); }catch(e){} }
  return rec;
};
"""

KW = re.compile(r"interval|range|distance|radius|\btime|scan|catch|spin|delay|period|cooldown|tick|loop|\brate|countdown|nearby|enabled|encounter|throw|sec\b|_ms\b|millis|duration|frequency|throttle", re.I)


def main():
    sess, pid = pg.get_session()
    print("attached pid", pid)
    try:
        sc = pg.get_script_with_helpers(sess, EXTRA_JS)
        try:
            matches = sc.exports_sync.find_classes(r"sfida|pgp|goplus|gotcha|autocatch|wearable")
            matches.sort(key=lambda m: (m["ns"], m["name"]))
            print(f"\n=== {len(matches)} matching classes in holo-game.dll ===")
            for m in matches:
                print(f"  {m['ns']}.{m['name']}")

            full = {}
            for m in matches:
                d = sc.exports_sync.dump_class_by_addr(m["addr"])
                full[f"{m['ns']}.{m['name']}"] = d
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(full, f, indent=1)
            print(f"\nfull dump -> {OUT}")

            # curated behavioral classes to spotlight
            CUR = re.compile(r"SoftSfida|PgpService|PgpDevice|ScannedSfida|SfidaSession|AutoCatch|SfidaScan|Wearables.*(Service|Controller|Manager)", re.I)
            for key, d in full.items():
                if not CUR.search(d["name"]):
                    continue
                print(f"\n================ {key} ================")
                print(f"  [{len(d['fields'])} fields, {len(d['methods'])} methods]")
                hf = [x for x in d["fields"] if KW.search(x)]
                hm = [x for x in d["methods"] if KW.search(x)]
                print("  -- timing/range FIELDS --")
                for x in (hf or ["(none matched keywords)"]):
                    print(f"     {x}")
                print("  -- timing/range METHODS --")
                for x in (hm or ["(none matched keywords)"]):
                    print(f"     {x}")
        finally:
            sc.unload()
    finally:
        sess.detach()


if __name__ == "__main__":
    main()
