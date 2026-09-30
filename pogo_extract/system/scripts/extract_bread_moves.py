"""Extract Dynamax/GMax Max-move LEVELS (the breadMoves_ RepeatedField, the one
prior data gap). PokemonProto.breadMoves_ @ +456 -> RepeatedField<BreadMoveSlotProto>
(array_@+0x10, count_@+0x18; managed array data @+0x20, 8-byte ptr elements).
BreadMoveSlotProto: MoveType @+0x10 (i32), MoveLevel @+0x14 (i32).
Writes DB columns bread_moves (JSON [[type,level],...]) and bread_max_level.
"""
import sqlite3, sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pogo_il2cpp as pg
sys.stdout.reconfigure(encoding='utf-8')
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB=os.path.join(ROOT,'pokemon.db')

JS=r"""
function readBread(protoStr){
  _ensureInit();
  var p=ptr(protoStr);
  var rf=p.add(456).readPointer();          // breadMoves_ RepeatedField
  if(rf.isNull()) return [];
  var cnt=rf.add(0x18).readS32();
  var arr=rf.add(0x10).readPointer();
  if(arr.isNull()||cnt<=0||cnt>30) return [];
  var out=[];
  for(var i=0;i<cnt;i++){
    var slot=arr.add(0x20+i*8).readPointer();
    if(slot.isNull()) continue;
    out.push([slot.add(0x10).readS32(), slot.add(0x14).readS32()]);  // [MoveType, MoveLevel]
  }
  return out;
}
rpc.exports.readBread=readBread;
"""

def main():
    conn=sqlite3.connect(DB); cur=conn.cursor()
    cols={r[1] for r in cur.execute('PRAGMA table_info(pokemon)')}
    if 'bread_moves' not in cols: cur.execute('ALTER TABLE pokemon ADD COLUMN bread_moves TEXT')
    if 'bread_max_level' not in cols: cur.execute('ALTER TABLE pokemon ADD COLUMN bread_max_level INTEGER')
    conn.commit()
    # Cover EVERY Dynamax/GMax-flagged mon: bread_mode and fresh_bread_mode can
    # disagree (one is the cached proto field, the other the fresh runtime read);
    # union them so no Max mon is skipped. Empty breadMoves_ -> no level (correct).
    uids=[r[0] for r in cur.execute(
        'SELECT uid_hex FROM pokemon WHERE in_bag=1 '
        'AND (bread_mode IN (1,2) OR fresh_bread_mode IN (1,2))')]
    print(f'bread-mode mons: {len(uids)}')

    sess,pid=pg.get_session(); print('pid',pid)
    try:
        bag=pg.pick_singleton(sess,'Niantic.Holoholo.Internal','PokemonBagImpl')
        pm=pg.find_protos_for_uids(sess,bag,sorted({str(int(u,16)) for u in uids}))
        print(f'bag-walk {len(pm)}/{len(uids)}')
        h=pg.get_script_with_helpers(sess,JS)
        n=0; lvl_hist={}
        for u in uids:
            proto=pm.get(str(int(u,16)))
            if not proto: continue
            slots=h.exports_sync.read_bread(proto)
            if not slots: continue
            mx=max((lv for _,lv in slots), default=0)
            cur.execute('UPDATE pokemon SET bread_moves=?, bread_max_level=? WHERE uid_hex=?',
                        (json.dumps(slots), mx, u))
            lvl_hist[mx]=lvl_hist.get(mx,0)+1; n+=1
        conn.commit()
        h.unload()
        print(f'extracted Max-move levels for {n} mons')
        print('top Max-move level distribution:', dict(sorted(lvl_hist.items())))
        # sample
        for r in cur.execute("SELECT species_name,bread_mode,bread_moves,bread_max_level FROM pokemon WHERE bread_moves IS NOT NULL ORDER BY bread_max_level DESC LIMIT 8"):
            md='GMAX' if r[1]==2 else 'DYN'
            print(f'  {r[0]:<14} {md} maxLvl={r[3]} slots={r[2]}')
    finally:
        sess.detach(); conn.close()

if __name__=='__main__':
    main()
