"""Probe the LIVE PokedexImpl badge map: dump the real PokedexCategory-ish enum(s) from IL2CPP and
census every category id actually present across all dex entries -- to find (or refute) the
'shinyHundo' category. The readers assumed catEnum 102 = shinyHundo; it reads 0/943 while the bag
holds 2 self-caught shiny hundos (Vanilluxe 584, Fashion-Sneasel 215), so either the id is wrong or
the badge does not exist. READ-ONLY.
"""
import json, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pogo_il2cpp as pg   # hardened attach: PID-drift + libil2cpp-loaded + readiness proof (audit F26 --
                           # the first probe attached a freshly-restarted PoGo before libil2cpp mapped)

sess, pid = pg.get_session()
print(f"PID: {pid}")

js = r"""
var IL2=null, CLS=null, IMGS=null;
function init(){
    var il2cpp=Process.findModuleByName('libil2cpp.so');
    if(!il2cpp) return {ok:false, err:'libil2cpp.so not loaded yet'};
    var exp={}; il2cpp.enumerateExports().forEach(function(e){ if(e.name.indexOf('il2cpp_')===0) exp[e.name]=e.address; });
    function B(n,r,a){ if(!exp[n]) return null; try{ return new NativeFunction(exp[n],r,a);}catch(e){ return null;} }
    IL2={ dG:B('il2cpp_domain_get','pointer',[]), dGA:B('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),
          aGI:B('il2cpp_assembly_get_image','pointer',['pointer']), iGN:B('il2cpp_image_get_name','pointer',['pointer']),
          iGCC:B('il2cpp_image_get_class_count','uint32',['pointer']), iGC:B('il2cpp_image_get_class','pointer',['pointer','uint32']),
          cFN:B('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),
          cGN:B('il2cpp_class_get_name','pointer',['pointer']), cGNS:B('il2cpp_class_get_namespace','pointer',['pointer']),
          cGF:B('il2cpp_class_get_fields','pointer',['pointer','pointer']), fGN:B('il2cpp_field_get_name','pointer',['pointer']),
          fGF:B('il2cpp_field_get_flags','int',['pointer']), fGSV:B('il2cpp_field_static_get_value','void',['pointer','pointer']),
          tA:B('il2cpp_thread_attach','pointer',['pointer']),
          lAlloc: exp['il2cpp_unity_liveness_allocate_struct'] ? B('il2cpp_unity_liveness_allocate_struct','pointer',['pointer','int','pointer','pointer','pointer']) : null,
          lStat: exp['il2cpp_unity_liveness_calculation_from_statics'] ? B('il2cpp_unity_liveness_calculation_from_statics','void',['pointer']) : null,
          lFin: exp['il2cpp_unity_liveness_finalize'] ? B('il2cpp_unity_liveness_finalize','void',['pointer']) : null,
          lFree: exp['il2cpp_unity_liveness_free_struct'] ? B('il2cpp_unity_liveness_free_struct','void',['pointer']) : null,
          stop: exp['il2cpp_stop_gc_world'] ? B('il2cpp_stop_gc_world','void',[]) : null,
          start: exp['il2cpp_start_gc_world'] ? B('il2cpp_start_gc_world','void',[]) : null,
          alloc:B('il2cpp_alloc','pointer',['size_t']), free:B('il2cpp_free','void',['pointer']) };
    IL2.tA(IL2.dG());
    var sp=Memory.alloc(4); var asms=IL2.dGA(IL2.dG(),sp); var na=sp.readS32();
    IMGS=[]; var gi=null;
    for(var a=0;a<na;a++){ var im=IL2.aGI(asms.add(a*Process.pointerSize).readPointer()); IMGS.push(im);
        if(IL2.iGN(im).readCString()==='holo-game.dll') gi=im; }
    CLS=IL2.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokedexImpl'));
    return {ok:!CLS.isNull(), hasLiveness:!!(IL2.lAlloc&&IL2.lStat)};
}
function dumpEnum(cls){
    var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var f,res={};
    while((f=IL2.cGF(cls,iter)) && !f.isNull()){
        var fl=IL2.fGF(f);
        if((fl&0x10)===0||(fl&0x40)===0) continue;     // static literal = enum member
        var vb=Memory.alloc(8); vb.writeS64(0);
        try{ IL2.fGSV(f,vb); res[vb.readS32()]=IL2.fGN(f).readCString(); }catch(e){}
    }
    return res;
}
rpc.exports={
    init:init,
    dumpcats:function(){
        var found={};
        for(var i=0;i<IMGS.length;i++){
            var cc=IL2.iGCC(IMGS[i]);
            for(var ci=0;ci<cc;ci++){
                var cls=IL2.iGC(IMGS[i],ci);
                if(!cls||cls.isNull()) continue;
                var nm; try{ nm=IL2.cGN(cls).readCString(); }catch(e){ continue; }
                if(!nm) continue;
                var ln=nm.toLowerCase();
                if(ln.indexOf('categor')<0 && ln.indexOf('badge')<0) continue;
                var en=dumpEnum(cls);
                if(Object.keys(en).length>=4){
                    var ns=''; try{ ns=IL2.cGNS(cls).readCString()||''; }catch(e){}
                    found[(ns?ns+'.':'')+nm]=en;
                }
            }
        }
        return found;
    },
    find:function(){
        var hits=[];
        var onObj=new NativeCallback(function(objs,count,ud){ for(var i=0;i<count;i++) hits.push(objs.add(i*Process.pointerSize).readPointer().toString()); },'void',['pointer','int','pointer']);
        var re=new NativeCallback(function(h,size,ud){ if(!h.isNull()&&size.compare(0)===0){ IL2.free(h); return ptr(0);} return IL2.alloc(size); },'pointer',['pointer','size_t','pointer']);
        try{
            if(IL2.stop) IL2.stop();
            var st=IL2.lAlloc(CLS,0,onObj,ptr(0),re);
            IL2.lStat(st);
            if(IL2.lFin) IL2.lFin(st);
            if(IL2.start) IL2.start();
            if(IL2.lFree) IL2.lFree(st);
        }catch(e){ if(IL2.start){try{IL2.start();}catch(e2){}} return {err:''+e}; }
        return {hits:hits};
    },
    catstats:function(addr, wantPids){
        var inst=ptr(addr);
        var dict=inst.add(0x10).readPointer();
        if(dict.isNull()) return {notready:'dex dict null (login still loading)'};
        var entries=dict.add(0x18).readPointer();
        if(entries.isNull()) return {notready:'dex entries null'};
        var maxLen=entries.add(0x18).readS32();
        if(maxLen<=0||maxLen>100000) return {notready:'dex entries empty/garbage ('+maxLen+')'};
        var data=entries.add(0x20);
        var agg={};                       // cat -> {present, acq, expid}
        var detail={};                    // wanted pid -> [[cat,acq],...]
        var want={}; (wantPids||[]).forEach(function(p){ want[p]=1; });
        for(var i=0;i<maxLen;i++){
            var ep=data.add(i*24);
            if(ep.readS32()<0) continue;
            var pidv=ep.add(8).readS32();
            var proto=ep.add(16).readPointer();
            if(proto.isNull()) continue;
            var mapField=proto.add(0x80).readPointer();
            if(mapField.isNull()) continue;
            var list=mapField.add(0x18).readPointer();
            if(list.isNull()) continue;
            var head=list.add(0x10).readPointer();
            var lcount=list.add(0x18).readS32();
            var node=head, iters=0;
            while(node && !node.isNull() && iters<lcount+50){
                try{
                    var kv=node.add(0x30).readPointer();
                    if(!kv.isNull()){
                        var cat=kv.add(0x10).readS32();
                        var acq=kv.add(0x15).readU8();
                        if(!agg[cat]) agg[cat]={present:0,acq:0,expid:0};
                        agg[cat].present++;
                        if(acq){ agg[cat].acq++; if(!agg[cat].expid) agg[cat].expid=pidv; }
                        if(want[pidv]){ if(!detail[pidv]) detail[pidv]=[]; detail[pidv].push([cat,acq]); }
                    }
                    var nx=node.add(0x18).readPointer();
                    if(nx.isNull()||nx.equals(head)) break;
                    node=nx;
                }catch(e){ break; }
                iters++;
            }
        }
        return {agg:agg, detail:detail};
    }
};
"""
sc = sess.create_script(js); sc.load()
for _try in range(24):                      # PoGo just restarted? wait for libil2cpp (up to ~2 min)
    ir = sc.exports_sync.init()
    if ir.get('ok'):
        break
    print('init retry (%s)...' % ir.get('err')); time.sleep(5)
print('init:', ir)
if not ir.get('ok'):
    raise SystemExit('libil2cpp never loaded -- is PoGo past the splash screen?')

cats = sc.exports_sync.dumpcats()
print('\n=== enum classes named *categor*/*badge* (>=4 members) ===')
for name, en in cats.items():
    members = ', '.join('%s=%s' % (v, k) for k, v in sorted(en.items(), key=lambda kv: int(kv[0]))[:40])
    print(f'{name} ({len(en)}): {members[:600]}')
json.dump(cats, open('dex_category_enums.json', 'w', encoding='utf-8'), indent=1)

hits = []
for _try in range(24):                      # dex populates after login -- wait for a real instance
    r = sc.exports_sync.find()
    hits = r.get('hits') or []
    if hits:
        break
    print('no live PokedexImpl yet (game still loading?), retrying...'); time.sleep(5)
print(f'\nPokedexImpl instances: {len(hits)}')
if hits:
    st = None
    for _try in range(36):                  # wait for the dex dict to be populated (~943 entries post-login)
        st = sc.exports_sync.catstats(hits[0], [584, 215, 150])
        if st.get('notready'):
            print('dex not ready (%s), retrying...' % st['notready']); time.sleep(5); continue
        hundo_present = (st['agg'].get('14') or st['agg'].get(14) or {}).get('present', 0)
        if hundo_present < 500:             # partial walk = still loading; norm ~943
            print('dex partially loaded (FourStar present=%d), retrying...' % hundo_present); time.sleep(5); continue
        break
    print('\n=== category ids ACTUALLY IN THE DEX MAP (cat: present/acquired, example pid) ===')
    for cat, v in sorted(st['agg'].items(), key=lambda kv: int(kv[0])):
        print('  cat %4s: present=%4d acq=%4d  expid=%s' % (cat, v['present'], v['acq'], v['expid']))
    print('\n=== full badge readout: Vanilluxe 584 / Sneasel 215 / Mewtwo 150 ===')
    for p, lst in st['detail'].items():
        print('  pid %s: %s' % (p, sorted([tuple(x) for x in lst])))
sess.detach()
print('\nsaved dex_category_enums.json')
