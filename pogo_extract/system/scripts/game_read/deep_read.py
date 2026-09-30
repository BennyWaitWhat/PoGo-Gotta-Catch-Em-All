#!/usr/bin/env python
"""READ-ONLY deep state reader. WRITES NOTHING.

Three subsystems the other readers skip:
  1. FULL PlayerStatsProto  — reflect EVERY scalar field (all milestone/medal counters:
     GBL wins, Excellent throws, raids, trades, mega-evos, best-buddies, ...).
  2. Pokedex completeness    — walk PokedexImpl's dict, reflect the entry proto, aggregate
     every scalar flag (registered / shiny / perfect / lucky / shadow / purified / size ...).
  3. Dynamax / Max moves     — bag scan: PokemonProto.breadMoves_ @0x1c8 count>0 == Max-leveled.

All offsets self-discovered by reflection where possible; dict walk uses the
probeDexCount-confirmed layout (PokedexImpl+0x10 dict, +0x18 entries, len@+0x18).
"""
import sys, os, json
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r'''
var R={};
function _r(){ if(R.OGC) return; _ensureInit(); var il=Process.findModuleByName('libil2cpp.so');
  function nf(n,r,a){return new NativeFunction(il.getExportByName(n),r,a);}
  R.OGC=nf('il2cpp_object_get_class','pointer',['pointer']);
  R.CGN=nf('il2cpp_class_get_name','pointer',['pointer']);
  R.CGF=nf('il2cpp_class_get_fields','pointer',['pointer','pointer']);
  R.FGN=nf('il2cpp_field_get_name','pointer',['pointer']);
  R.FGO=nf('il2cpp_field_get_offset','uint32',['pointer']);
  R.FGT=nf('il2cpp_field_get_type','pointer',['pointer']);
  R.TGN=nf('il2cpp_type_get_name','pointer',['pointer']);
}
function reflectScalars(p){ _r(); var cls=R.OGC(p); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=R.CGF(cls,it))&&!f.isNull()){ try{ out.push({nm:R.FGN(f).readCString(), off:R.FGO(f), tn:R.TGN(R.FGT(f)).readCString()}); }catch(e){} } return out; }
function clsOf(p){ _r(); try{ return R.CGN(R.OGC(p)).readCString(); }catch(e){ return null; } }

rpc.exports.getStatsPtr = function(svcAddr){ _ensureInit();
  var m=cMN(cFN('Niantic.Holoholo','PlayerService'),'get_PlayerStats',0); if(!m||m.isNull()) return {ok:false};
  try{ var ex=Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0)); var r=rI(m,ptr(svcAddr),ptr(0),ex); return {ok:true, ptr:r.isNull()?null:r.toString()}; }catch(e){ return {ok:false,err:e.toString()}; }
};

rpc.exports.statsFull = function(addr){ var p=ptr(addr); var flds=reflectScalars(p); var vals={};
  for(var i=0;i<flds.length;i++){ var o=flds[i].off, tn=flds[i].tn, nm=flds[i].nm; var v=null;
    try{
      if(tn==='System.Int32'||tn==='System.UInt32') v=p.add(o).readS32();
      else if(tn==='System.Int64') v=p.add(o).readS64().toString();
      else if(tn==='System.UInt64') v=p.add(o).readU64().toString();
      else if(tn==='System.Single') v=p.add(o).readFloat();
      else if(tn==='System.Double') v=p.add(o).readDouble();
      else if(tn==='System.Boolean') v=p.add(o).readU8();
      else if(tn.indexOf('RepeatedField')>=0||tn.indexOf('MapField')>=0){ var rf=p.add(o).readPointer(); if(rf&&!rf.isNull()){ var c=rf.add(0x18).readS32(); if(c>0&&c<100000) v='RF['+c+']'; } }
    }catch(e){}
    if(v!==null && v!==0 && v!=='0') vals[nm]=v;
  }
  return {cls:clsOf(p), vals:vals};
};

rpc.exports.dexAgg = function(dexAddr){ _r(); var inst=ptr(dexAddr);
  var dict=inst.add(0x10).readPointer(); if(!dict||dict.isNull()) return {err:'null dict'};
  var entries=dict.add(0x18).readPointer(); if(!entries||entries.isNull()) return {err:'null entries'};
  var len=entries.add(0x18).readS32(); if(len<=0||len>500000) return {err:'bad len '+len};
  var data=entries.add(0x20), stride=0x18, valOff=0x10;
  var v0=null; for(var i=0;i<len;i++){ try{ var v=data.add(i*stride+valOff).readPointer(); if(v&&!v.isNull()){ v0=v; break; } }catch(e){} }
  if(!v0) return {err:'no non-null value len='+len};
  var schema=reflectScalars(v0).filter(function(x){ return x.tn==='System.Int32'||x.tn==='System.UInt32'||x.tn==='System.Boolean'; });
  var agg={}; for(var s=0;s<schema.length;s++) agg[schema[s].nm]={sum:0,nz:0,off:schema[s].off};
  var walked=0;
  for(var i=0;i<len;i++){ var v=null; try{ v=data.add(i*stride+valOff).readPointer(); }catch(e){} if(!v||v.isNull()) continue; walked++;
    for(var s=0;s<schema.length;s++){ try{ var val=v.add(schema[s].off).readS32(); if(val!==0){ agg[schema[s].nm].sum+=val; agg[schema[s].nm].nz++; } }catch(e){} } }
  return {ok:true, valCls:clsOf(v0), len:len, walked:walked, schema:schema.map(function(x){return x.nm+'@0x'+x.off.toString(16)+':'+x.tn;}), agg:agg};
};

rpc.exports.dynamax = function(arrJson){ _r(); var arr=JSON.parse(arrJson); var out=[]; var schema=null;
  if(arr.length){ try{ schema=reflectScalars(ptr(arr[0])).filter(function(x){var l=x.nm.toLowerCase(); return l.indexOf('bread')>=0||l.indexOf('dyna')>=0||l.indexOf('gigant')>=0||(l.indexOf('max')>=0&&l.indexOf('cp')<0&&l.indexOf('stam')<0);}).map(function(x){return x.nm+'@0x'+x.off.toString(16)+':'+x.tn;}); }catch(e){} }
  for(var i=0;i<arr.length;i++){ var p=ptr(arr[i]); try{ var pid=p.add(0x28).readS32(); var bm=p.add(0x1c8).readPointer(); var bc=(bm&&!bm.isNull())?bm.add(0x18).readS32():0; if(bc>0&&bc<50) out.push([pid,bc]); }catch(e){} }
  return {schema:schema, maxMons:out};
};
'''


def pid_names():
    import sqlite3
    try:
        c = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
        return {r[0]: r[1] for r in c.execute(
            'SELECT DISTINCT pokemon_id, species_name FROM pokemon WHERE pokemon_id IS NOT NULL')}
    except Exception:
        return {}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print('[*] connecting...')
    sess, pid = pg.get_session()
    print('[*] attached pid', pid)
    sc = pg.get_script_with_helpers(sess, JS)
    names = pid_names()

    # ---- PART 1: full player stats ----
    print('\n========== FULL PLAYER STATS (all non-zero scalar counters) ==========')
    try:
        probe = pg.get_script_with_helpers(sess)
        hits = probe.exports_sync.find_singleton('Niantic.Holoholo', 'PlayerService').get('hits', [])
        probe.unload()
        stats = None
        for h in hits:
            gp = sc.exports_sync.get_stats_ptr(h)
            if gp.get('ok') and gp.get('ptr'):
                st = sc.exports_sync.stats_full(gp['ptr'])
                if st.get('vals', {}).get('Level'):
                    stats = st
                    break
        if stats:
            print('  class:', stats['cls'])
            for k, v in sorted(stats['vals'].items()):
                print(f'  {k:38s} {v}')
        else:
            print('  [!] no populated PlayerStatsProto from', len(hits), 'hits')
    except Exception as e:
        print('  stats err:', e)

    # ---- PART 2: pokedex completeness ----
    print('\n========== POKEDEX COMPLETENESS (PokedexImpl) ==========')
    try:
        dex = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokedexImpl')
        d = sc.exports_sync.dex_agg(dex)
        if d.get('ok'):
            print(f"  entry proto: {d['valCls']}   dict-slots={d['len']}  entries-walked={d['walked']}")
            print('  schema:', d['schema'])
            print('  --- per-field aggregate (nz = #species with field>0, sum = total) ---')
            for k, v in sorted(d['agg'].items(), key=lambda x: -x[1]['nz']):
                if v['nz'] > 0:
                    print(f"    {k:32s} nz={v['nz']:5d}  sum={v['sum']}")
        else:
            print('  dex err:', d.get('err'))
    except Exception as e:
        print('  dex err:', e)

    # ---- PART 3: dynamax / max moves ----
    print('\n========== DYNAMAX / MAX MOVES (bag scan) ==========')
    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        bagmap = pg.walk_bag_protos(sess, bag)
        protos = list(bagmap.values())
        dm = sc.exports_sync.dynamax(json.dumps(protos))
        print('  bread/dyna/max-named fields on PokemonProto:', dm.get('schema'))
        mons = dm.get('maxMons', [])
        print(f'  bag mons with Max/bread moves (count>0): {len(mons)}')
        bypid = Counter(m[0] for m in mons)
        for pidv, c in bypid.most_common(40):
            print(f'    {names.get(pidv, "#" + str(pidv)):18s} x{c}')
    except Exception as e:
        print('  dynamax err:', e)

    sc.unload()
    sess.detach()
    print('\n[done]')


if __name__ == '__main__':
    main()
