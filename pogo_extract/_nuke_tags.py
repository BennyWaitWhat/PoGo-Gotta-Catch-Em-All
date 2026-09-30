"""Delete named tags from the server (by uint64 tagId) and clear them from the
DB auth_tag_names mirror. Usage: python _nuke_tags.py "XXS" "Shiny" ...
Tags are rebuildable from rules, so this is reversible."""
import sqlite3, sys, time, os
import pogo_il2cpp as pg
sys.stdout.reconfigure(encoding='utf-8')
HERE=os.path.dirname(os.path.abspath(__file__)); DB=os.path.join(HERE,'pokemon.db')

JS=r"""
function enumTags(s){_ensureInit();var cl=cFN('Niantic.Holoholo.Tagging','TaggingRpcService');var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m,gn=null,gb=null;while((m=IL2.cGM(cl,it))&&!m.isNull()){var nm=IL2.mGN(m).readCString();if(nm==='get_NumberOfTags')gn=m;if(nm==='GetCachedTagToPokemonBindingForIndex')gb=m;}var svc=ptr(s);var tot=rI(gn,svc,ptr(0),null).add(0x10).readS32();var out=[];for(var i=0;i<tot;i++){var ib=Memory.alloc(4);ib.writeS32(i);var ar=Memory.alloc(Process.pointerSize);ar.writePointer(ib);var bp=rI(gb,svc,ar,null);if(bp.isNull())continue;var tp=bp.add(0x10).readPointer();var nm='';try{var ns=tp.add(0x40).readPointer();var ln=ns.add(0x10).readS32();if(ln>0&&ln<100){var ch=[];for(var ci=0;ci<ln;ci++)ch.push(String.fromCharCode(ns.add(0x14+ci*2).readU16()));nm=ch.join('');}}catch(e){}var tid='0';try{tid=tp.add(0x38).readU64().toString();}catch(e){}out.push({name:nm,tagId:tid});}return out;}
function delTag(s,tidStr){_ensureInit();var cl=cFN('Niantic.Holoholo.Tagging','TaggingRpcService');var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m,dm=null;while((m=IL2.cGM(cl,it))&&!m.isNull()){if(IL2.mGN(m).readCString()==='DeleteTag'){dm=m;break;}}if(!dm)return{ok:false,err:'no DeleteTag'};var idBuf=Memory.alloc(8);idBuf.writeU64(uint64(tidStr));var args=Memory.alloc(Process.pointerSize);args.writePointer(idBuf);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));rI(dm,ptr(s),args,exc);if(!exc.readPointer().isNull())return{ok:false,err:'exception'};return{ok:true};}
rpc.exports.enumTags=enumTags; rpc.exports.delTag=delTag;
"""

def main():
    targets=[a for a in sys.argv[1:] if a]
    if not targets: print('no tag names given'); return
    print('Nuking tags:', targets)
    sess,pid=pg.get_session(); print('pid',pid)
    try:
        svc=pg.pick_singleton(sess,'Niantic.Holoholo.Tagging','TaggingRpcService')
        h=pg.get_script_with_helpers(sess,JS)
        for _pass in range(4):
            tags=h.exports_sync.enum_tags(svc)
            todo=[t for t in tags if t['name'] in targets]
            if not todo:
                print(f'  pass {_pass+1}: none of the targets remain'); break
            print(f'  pass {_pass+1}: deleting {len(todo)}: {[t["name"] for t in todo]}')
            for t in todo:
                h.exports_sync.del_tag(svc, t['tagId']); time.sleep(0.4)
            time.sleep(2)
        # final state
        remaining=[t['name'] for t in h.exports_sync.enum_tags(svc) if t['name'] in targets]
        h.unload()
    finally:
        sess.detach()
    # clear DB mirror
    conn=sqlite3.connect(DB); cur=conn.cursor()
    for name in targets:
        rows=cur.execute("SELECT uid_hex,auth_tag_names FROM pokemon WHERE (';'||COALESCE(auth_tag_names,'')||';') LIKE ?",(f'%;{name};%',)).fetchall()
        for uid,atn in rows:
            tg=[t for t in (atn or '').split(';') if t and t!=name]
            cur.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",(';'.join(tg) if tg else None,uid))
    conn.commit(); conn.close()
    print('Remaining (should be none):', remaining)
    print('DB mirror cleared for:', targets)

if __name__=='__main__':
    main()
