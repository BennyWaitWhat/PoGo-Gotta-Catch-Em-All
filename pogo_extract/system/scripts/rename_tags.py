"""Rename server tags IN PLACE via TaggingRpcService.EditTag(PokemonTagProto, bool).
EditTag keeps the tag Id (+0x38) and members; we just swap the name String* at
tagProto+0x40 to a fresh il2cpp string. Then mirror the new name into the DB
auth_tag_names and registry. Name limit = 15 chars (server-enforced).

REFUSES any rename naming the irreversible release pile, on EITHER side -- see
the PILE GATE block below. Every source name in RENAMES is a pre-2026-05-30 name
that is no longer among the 47 device tags, so in practice only the ad-hoc
--from/--to path is live, and it is gated too.

Usage:
  python rename_tags.py --only "Legacy"     # test one
  python rename_tags.py                      # apply all in RENAMES
"""
import sqlite3, sys, os, time, argparse
sys.stdout.reconfigure(encoding='utf-8')
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)   # HERE: tag_ops lives in system/scripts
os.chdir(ROOT)                      # pogo_il2cpp/bulk_tag.js use relative paths
import pogo_il2cpp as pg
import tag_ops                      # module-level ON PURPOSE. _refuse_if_pile() reads it
                                    # through the module object, so a future local `import
                                    # tag_ops` inside main() cannot leave the name unbound
                                    # (the bug that bit prune_server_tag.py on 2026-09-07).
DB=os.path.join(ROOT,'pokemon.db')

RENAMES = {                          # current server name -> new (de-numbered) name, 2026-05-30
 '1 GL IV':'GL IV', '1 UL IV':'UL IV', '4 XXL':'XXL', '4 Hundo':'Hundo',
 '4 Nundo':'Nundo', '4 Costume':'Event', '3 Best Buddy':'Best Buddy',
 '3 Legacy Moves':'Legacy Moves', '5 Ethan':'Traded by E+F', '6 Transfer':'Transfer',
}                                    # '5 Florandez' is DELETED (merged into Traded by E+F), not renamed

JS=r"""
function _bindStrNew(){
  var f=null; Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function(e){ if(e.name==='il2cpp_string_new') f=e.address; });
  return new NativeFunction(f,'pointer',['pointer']);
}
function enumTags(svc){
  var cl=cFN('Niantic.Holoholo.Tagging','TaggingRpcService');
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));
  var m,gn=null,gb=null;
  while((m=IL2.cGM(cl,it))&&!m.isNull()){var nm=IL2.mGN(m).readCString();if(nm==='get_NumberOfTags')gn=m;if(nm==='GetCachedTagToPokemonBindingForIndex')gb=m;}
  var tot=rI(gn,ptr(svc),ptr(0),null).add(0x10).readS32();
  var out=[];
  for(var i=0;i<tot;i++){var ib=Memory.alloc(4);ib.writeS32(i);var ar=Memory.alloc(Process.pointerSize);ar.writePointer(ib);var bp=rI(gb,ptr(svc),ar,null);if(bp.isNull())continue;
    var tp=bp.add(0x10).readPointer();var nm='';try{var ns=tp.add(0x40).readPointer();var ln=ns.add(0x10).readS32();if(ln>0&&ln<100){var ch=[];for(var ci=0;ci<ln;ci++)ch.push(String.fromCharCode(ns.add(0x14+ci*2).readU16()));nm=ch.join('');}}catch(e){}
    var mc=0;try{var l=bp.add(0x18).readPointer();if(!l.isNull())mc=l.add(0x18).readS32();}catch(e){}
    out.push({name:nm,tagProto:tp.toString(),members:mc});}
  return out;
}
function renameTag(svc, oldName, newName){
  _ensureInit();
  var tags=enumTags(svc); var tp=null;
  for(var i=0;i<tags.length;i++){ if(tags[i].name===oldName){ tp=ptr(tags[i].tagProto); break; } }
  if(!tp) return {ok:false, err:'old name not found'};
  var strNew=_bindStrNew();
  var s=strNew(Memory.allocUtf8String(newName));
  if(s.isNull()) return {ok:false, err:'string_new null'};
  tp.add(0x40).writePointer(s);
  var cl=cFN('Niantic.Holoholo.Tagging','TaggingRpcService');
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m,em=null;
  while((m=IL2.cGM(cl,it))&&!m.isNull()){ if(IL2.mGN(m).readCString()==='EditTag'){em=m;break;} }
  if(!em) return {ok:false, err:'no EditTag'};
  var b=Memory.alloc(1); b.writeU8(1);
  var args=Memory.alloc(2*Process.pointerSize);
  args.writePointer(tp); args.add(Process.pointerSize).writePointer(b);
  var exc=Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
  rI(em, ptr(svc), args, exc);
  if(!exc.readPointer().isNull()) return {ok:false, err:'EditTag exception'};
  return {ok:true};
}
rpc.exports.enumTags=function(s){_ensureInit();return enumTags(s);};
rpc.exports.renameTag=renameTag;
"""

# ---------------------------------------------------------------------------
# 2026-09-07 PILE GATE
# ---------------------------------------------------------------------------
# EditTag rewrites a tag's NAME String* in place (tagProto+0x40): the tag Id and
# EVERY member survive the rename. That makes this script the only route in the
# tree that can manufacture a tag literally named 'Transfer' out of some OTHER
# tag's membership -- i.e. put arbitrary mons in front of a human who releases by
# hand. It has no pre-flight stamp check, no keeper gate and no --dry-run, and the
# I6 unsanctioned-pusher census does not see it (it loads bulk_tag.js without ever
# calling a classified ADD primitive). The sanctioned -- and only -- route to the
# pile tag is preflight_transfer.py (writes system/analysis/preflight_stamp.json)
# -> prune_tags.py --atomic (refuses without a fresh, matching stamp).
#
# BOTH directions are pile writes:
#   --to   <pile>   manufactures the pile out of another tag's members;
#   --from <pile>   renames the pile out from under the human and orphans its tagset.
# Matching is tag_ops.is_pile_tag, so 'Transfer', 'transfer', '6 Transfer',
# '6_Transfer' and the tagset FILENAME forms ('Transfer.txt', a full path) all trip.
def _refuse_if_pile(mapping, what):
    for _src, _dst in mapping.items():
        if tag_ops.is_pile_tag(_src) or tag_ops.is_pile_tag(_dst):
            sys.exit("REFUSING: %s maps %r -> %r, which names the irreversible release "
                     "pile. A rename INTO the pile name is a pile write (EditTag keeps the "
                     "tag Id and every member); a rename OUT of it is one too. Use "
                     "preflight_transfer.py -> prune_tags.py --atomic." % (what, _src, _dst))


def mirror_db(old,new):
    # Unreachable while main()'s gate stands -- kept as a tripwire so the DB writer is
    # self-defending: mirror_db rewrites auth_tag_names for every row carrying `old`.
    _refuse_if_pile({old: new}, 'the DB mirror')
    conn=sqlite3.connect(DB); cur=conn.cursor()
    rows=cur.execute("SELECT uid_hex,auth_tag_names FROM pokemon WHERE (';'||COALESCE(auth_tag_names,'')||';') LIKE ?",(f'%;{old};%',)).fetchall()
    for uid,atn in rows:
        parts=[(new if t==old else t) for t in (atn or '').split(';') if t]
        cur.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",(';'.join(parts),uid))
    conn.commit(); conn.close(); return len(rows)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--only')
    ap.add_argument('--from',dest='frm'); ap.add_argument('--to')
    a=ap.parse_args()
    if a.frm and a.to: todo={a.frm:a.to}            # ad-hoc: --from "Old" --to "New"
    elif a.only:       todo={a.only:RENAMES[a.only]}
    else:              todo=dict(RENAMES)

    # ---- PILE GATE, before ANY Frida attach so a refusal never costs an attach ----
    # (a) The RESOLVED plan, not just RENAMES. --from/--to bypasses the table entirely
    #     and is the reachable route ('--to Transfer'), so a RENAMES-only check would
    #     miss exactly the case that matters.
    _refuse_if_pile(todo, 'the requested rename plan')
    # (b) ...and the built-in table whenever the table feeds the plan (bare run, --only).
    #     RENAMES still carries the historical '6 Transfer' -> 'Transfer' pair, so every
    #     table-driven run now refuses. Intended: all ten source names are pre-2026-05-30
    #     names that no longer exist among the 47 device tags, so the table is dead weight
    #     kept for the record. --from/--to with two non-pile names is the one live path
    #     and is deliberately left working -- this is a pile gate, not a retirement.
    if not (a.frm and a.to):
        _refuse_if_pile(RENAMES, 'the built-in RENAMES table')

    sess,pid=pg.get_session(); print('pid',pid)
    try:                                  # 2026-05-30: EditTag silently NO-OPs unless foregrounded
        sys.path.insert(0, HERE)          #   -- this was the real cause of past "renames reverted"
        from ready_gate import ensure_ready_for_writes, NotReadyForWrites
        ensure_ready_for_writes(sess, pid)
    except NotReadyForWrites:
        sess.detach(); raise
    except Exception as _e:
        print(f'[ready_gate] skipped (proceeding): {_e}')
    before={}
    try:
        svc=pg.pick_singleton(sess,'Niantic.Holoholo.Tagging','TaggingRpcService')
        h=pg.get_script_with_helpers(sess,JS)
        before={t['name']:t['members'] for t in h.exports_sync.enum_tags(svc)}
        for old,new in todo.items():
            if old not in before:
                print(f'  ! {old!r} not on server (already renamed?) — skip'); continue
            r=h.exports_sync.rename_tag(svc,old,new); time.sleep(1.0)
            n=mirror_db(old,new) if r.get('ok') else 0
            print(f'  {old!r:<18} -> {new!r:<16} {r}  db_mirror={n}')
        h.unload()
    finally:
        sess.detach()
    # VERIFY in a FRESH session -- same-session enum reads the locally-overwritten name
    # String* and self-reports false success; only a fresh attach reflects the server.
    time.sleep(3)
    sess2,_=pg.get_session()
    try:
        svc2=pg.pick_singleton(sess2,'Niantic.Holoholo.Tagging','TaggingRpcService')
        h2=pg.get_script_with_helpers(sess2,JS)
        after={t['name']:t['members'] for t in h2.exports_sync.enum_tags(svc2)}
        h2.unload()
    finally:
        sess2.detach()
    print('\nAfter (FRESH session) — server tags:')
    for nm in sorted(after): print(f'  {nm:<16} {after[nm]}')
    bad=[new for new in todo.values() if new not in after]
    print(f'\nbefore total members={sum(before.values())}  after total={sum(after.values())}')
    print('NOT-PERSISTED renames:', bad if bad else 'none -- all renames confirmed in fresh session')

if __name__=='__main__':
    main()
