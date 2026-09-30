#!/usr/bin/env python
"""READ-ONLY medals/badges reader for PoGo live IL2CPP state.

Reads PlayerStatsProto.EventBadges (RepeatedField<HoloBadgeType> @ +0xB8, DEVICE-recon
2026-05-21) -> the list of EARNED event/dynamic medals (incl. GO Fest 2026 district
medals like "Friendship District"), names them by dumping the live HoloBadgeType enum
(2026 district constants are NOT in any static dump -> must read the live binary), and
prints the progress-medal counters (KmWalked, NumPokemonCaptured, ...).

WRITES NOTHING.

PlayerService capture: liveness via pick_singleton('Niantic.Holoholo','PlayerService').
pick_singleton returns the FIRST hit for this class (no tuned probe) -> if get_PlayerStats
returns junk, there were >1 instances; the script prints all liveness hits so you can
retry against the populated one. PlayerService must be live -> be on the map or open the
Trainer profile before running.

Validation flags (see GAME_READ_CAPABILITIES.md §3):
  [DEVICE] confirm EventBadges offset in TODAY's binary (script re-reads by NAME, self-heals;
           sanity-check the printed offset)
  [DEVICE] confirm the live HoloBadgeType enum contains 2026 Tokyo/district/Friendship
           constants and capture their exact names+ints (the headline unknown)
  [DEVICE] confirm district completion writes EventBadges (vs a BadgeData inventory item)

Usage:
    python read_medals.py
    python read_medals.py --json medals_out.json
    python read_medals.py --all-badges     # print the entire HoloBadgeType enum dump too
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
import pogo_il2cpp as pg  # noqa: E402

JSON_OUT = sys.argv[sys.argv.index('--json') + 1] if '--json' in sys.argv else None
ALL_BADGES = '--all-badges' in sys.argv

# EventBadges fallback offset if the by-name lookup fails (DEVICE-recon 2026-05-21)
EVENTBADGES_FALLBACK = 0xB8

READER_JS = r"""
var PROTO_IMAGE = null, OGC = null, CGN = null, CGF = null, FGN = null, FGO = null,
    FGFlags = null, FGType = null, FSGV = null, CGFcount = null;
function _proto() {
  if (PROTO_IMAGE) return;
  _ensureInit();
  var il = Process.findModuleByName('libil2cpp.so');
  function nf(n,r,a){ return new NativeFunction(il.getExportByName(n),r,a); }
  OGC=nf('il2cpp_object_get_class','pointer',['pointer']);
  CGN=nf('il2cpp_class_get_name','pointer',['pointer']);
  CGF=nf('il2cpp_class_get_fields','pointer',['pointer','pointer']);
  FGN=nf('il2cpp_field_get_name','pointer',['pointer']);
  FGO=nf('il2cpp_field_get_offset','uint32',['pointer']);
  FGFlags=nf('il2cpp_field_get_flags','int',['pointer']);
  FSGV=nf('il2cpp_field_static_get_value','void',['pointer','pointer']);
  var sp=Memory.alloc(4); var asms=IL2.dGA(IL2.dG(),sp); var na=sp.readS32();
  for(var a=0;a<na;a++){ var im=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());
    if(IL2.iGN(im).readCString()==='holo-protos.dll'){ PROTO_IMAGE=im; break; } }
}
function clsName(o){ try{ if(!o||o.isNull()) return null; return CGN(OGC(o)).readCString(); }catch(e){ return null; } }
function protoCls(ns,nm){ _proto(); return IL2.cFN(PROTO_IMAGE, Memory.allocUtf8String(ns), Memory.allocUtf8String(nm)); }
function inv0(instPtr,name){ _proto(); if(!instPtr||instPtr.isNull()) return {ok:false};
  var m=cMN(OGC(instPtr),name,0); if(!m||m.isNull()) return {ok:false};
  try{ var ex=Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0)); var r=rI(m,instPtr,ptr(0),ex); return {ok:true,ret:r}; }catch(e){ return {ok:false,err:e.toString()}; } }
function box32(p){ try{ if(!p||p.isNull()) return null; return p.add(0x10).readS32(); }catch(e){ return null; } }
function boxF(p){ try{ if(!p||p.isNull()) return null; return p.add(0x10).readFloat(); }catch(e){ return null; } }

// dump a static-literal enum (value->name) from holo-protos.dll
rpc.exports.dumpEnum = function(ns, name){
  _proto();
  var cls=protoCls(ns,name); if(!cls||cls.isNull()) return {err:'enum class not found: '+ns+'.'+name};
  var out={}; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=CGF(cls,it)) && !f.isNull()){
    try{ var fl=FGFlags(f); if(!((fl&0x10) && (fl&0x40))) continue;  // STATIC && LITERAL
      var nm=FGN(f).readCString(); if(nm==='value__') continue;
      var buf=Memory.alloc(8); buf.writeU64(0); FSGV(f,buf); out[buf.readS32()]=nm;
    }catch(e){}
  }
  return {ok:true, count:Object.keys(out).length, map:out};
};

// read PlayerStatsProto: discover field offsets by NAME (self-healing), read EventBadges RF + counters
rpc.exports.readStats = function(statsAddr){
  _proto();
  var p=ptr(statsAddr); var cls=OGC(p); var rec={cls:clsName(p), fields:{}, counters:{}, eventBadges:[]};
  // field name -> offset table for PlayerStatsProto
  var offByName={}; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=CGF(cls,it)) && !f.isNull()){ try{ var nm=FGN(f).readCString(); offByName[nm]=FGO(f); }catch(e){} }
  rec.eventBadgesOffset = (offByName['EventBadges']!==undefined) ? offByName['EventBadges'] : null;
  var ebOff = (rec.eventBadgesOffset!==null) ? rec.eventBadgesOffset : __EB_FALLBACK__;
  // walk RepeatedField<HoloBadgeType> (int enum): array@+0x10 count@+0x18 elem@array+0x20+i*4
  try{ var rf=p.add(ebOff).readPointer(); if(rf&&!rf.isNull()){ var arr=rf.add(0x10).readPointer(); var cnt=rf.add(0x18).readS32();
    if(arr&&!arr.isNull()&&cnt>0&&cnt<5000) for(var i=0;i<cnt;i++) rec.eventBadges.push(arr.add(0x20).add(i*4).readS32()); } }catch(e){ rec.ebErr=e.toString(); }
  // a few key counters by name (int unless float-named)
  var floats={'KmWalked':1,'KmWalkedPastActiveDay':1};
  ['Level','Experience','KmWalked','NumPokemonCaptured','NumPokemonEncountered','NumUniquePokedexEntries',
   'NumEvolutions','PokeStopVisits','NumEggsHatched','NumBattleAttackWon','NumChallengeQuestsCompleted',
   'NumTrades','NumPokemonPurified','NumGruntsDefeated','NumBestBuddies','NumTotalMegaEvolutions',
   'NumForeverFriendsEarned','BigMagikarpCaught','SmallRattataCaught','NumBerriesFed'].forEach(function(nm){
    if(offByName[nm]===undefined) return; var o=offByName[nm];
    try{ rec.counters[nm]= floats[nm] ? p.add(o).readFloat() : (nm==='Experience'? p.add(o).readS64().toString() : p.add(o).readS32()); }catch(e){}
  });
  return rec;
};
""".replace('__EB_FALLBACK__', str(EVENTBADGES_FALLBACK))


def main():
    print('[*] connecting...')
    sess, pid = pg.get_session()
    print(f'[*] attached pid={pid}')
    print('[*] resolving PlayerService (be on map / Trainer profile)...')

    # get all liveness hits so we can report/retry on multi-instance
    probe = pg.get_script_with_helpers(sess)
    try:
        hitres = probe.exports_sync.find_singleton('Niantic.Holoholo', 'PlayerService')
    finally:
        probe.unload()
    if 'err' in hitres:
        print('[!] PlayerService:', hitres['err'])
        sess.detach()
        sys.exit(1)
    hits = hitres.get('hits', [])
    print(f'[*] PlayerService liveness hits: {hits}')
    if not hits:
        print('[!] no PlayerService instance — open the Trainer profile and retry.')
        sess.detach()
        sys.exit(1)

    sc = pg.get_script_with_helpers(sess, READER_JS)

    # enum dump (the live HoloBadgeType -> names, incl. 2026 districts)
    enum = sc.exports_sync.dump_enum('Holoholo.Rpc', 'HoloBadgeType')
    badge_names = {}
    if enum.get('ok'):
        badge_names = {int(k): v for k, v in enum['map'].items()}
        print(f"[*] HoloBadgeType enum: {enum['count']} members")
    else:
        print('[!] enum dump failed:', enum.get('err'))

    # try each hit; use the first that yields a populated PlayerStatsProto (sane Level).
    # call get_PlayerStats on each instance to obtain the PlayerStatsProto ptr.
    stats = None
    used_inst = None
    GETSTATS_JS = r"""
    rpc.exports.getStatsPtr = function(svcAddr){
      _ensureInit();
      var p=ptr(svcAddr); var m=cMN(IL2.cFN(GAME_IMAGE, Memory.allocUtf8String('Niantic.Holoholo'), Memory.allocUtf8String('PlayerService')),'get_PlayerStats',0);
      if(!m||m.isNull()) return {ok:false, why:'no get_PlayerStats'};
      try{ var ex=Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0)); var r=rI(m,p,ptr(0),ex); return {ok:true, ptr: r.isNull()?null:r.toString()}; }catch(e){ return {ok:false, err:e.toString()}; }
    };
    """
    gs_sc = pg.get_script_with_helpers(sess, GETSTATS_JS)
    for h in hits:
        gp = gs_sc.exports_sync.get_stats_ptr(h)
        if gp.get('ok') and gp.get('ptr'):
            st = sc.exports_sync.read_stats(gp['ptr'])
            lvl = st.get('counters', {}).get('Level')
            if lvl and 1 <= lvl <= 90:
                stats = st
                used_inst = h
                break
    gs_sc.unload()
    sc.unload()
    sess.detach()

    if not stats:
        print('[!] could not get a populated PlayerStatsProto from any PlayerService instance.')
        sys.exit(1)

    print(f'\n[*] using PlayerService {used_inst}')
    print(f"[*] EventBadges field offset (by name): {hex(stats['eventBadgesOffset']) if stats.get('eventBadgesOffset') is not None else 'NOT FOUND -> used fallback ' + hex(EVENTBADGES_FALLBACK)}")

    print('\n=== PROGRESS-MEDAL COUNTERS ===')
    for k, v in stats.get('counters', {}).items():
        print(f'  {k:32s} {v}')

    eb = stats.get('eventBadges', [])
    print(f'\n=== EARNED EVENT/DYNAMIC MEDALS (EventBadges, {len(eb)}) ===')
    EVENT_KEY = ('gofest', 'district', 'friendship', 'city', 'safari', 'gotour', 'gowa', 'tour', '2026', 'tokyo')
    named = []
    for v in eb:
        nm = badge_names.get(v, f'??({v})')
        named.append({'int': v, 'name': nm})
        print(f'  {v:>12}  {nm}')
    hot = [n for n in named if any(k in n['name'].lower() for k in EVENT_KEY)]
    print(f'\n=== GO Fest / district / event-relevant medals ({len(hot)}) ===')
    for n in hot:
        print(f"  {n['int']:>12}  {n['name']}")

    if ALL_BADGES and badge_names:
        print(f'\n=== FULL HoloBadgeType enum ({len(badge_names)}) ===')
        for v in sorted(badge_names):
            print(f'  {v:>12}  {badge_names[v]}')

    if JSON_OUT:
        with open(JSON_OUT, 'w', encoding='utf-8') as fh:
            json.dump({'instance': used_inst, 'eventBadgesOffset': stats.get('eventBadgesOffset'),
                       'counters': stats.get('counters'), 'eventBadges': named,
                       'holoBadgeTypeEnum': badge_names}, fh, indent=2)
        print(f'\n[*] wrote {JSON_OUT}')
    print('\n[NOTE] 2026 district medal names come from the LIVE enum dump; if a known-earned '
          'district medal is missing from EventBadges, fall back to walking InventoryCache BadgeData '
          '(see GAME_READ_CAPABILITIES.md §3c).')


if __name__ == '__main__':
    main()
