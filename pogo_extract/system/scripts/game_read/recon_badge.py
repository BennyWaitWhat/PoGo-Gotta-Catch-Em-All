"""RECON (READ-ONLY): read the REAL Berry Master tier thresholds from the device's loaded BadgeSettingsProto
(target[] per tier) instead of trusting web/canonical numbers. Dumps HoloBadgeType to find the berry-feed
badge, then finds BadgeSettingsProto instances and prints the matching target array. WRITES NOTHING."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

READER_JS = r"""
var PROTO_IMAGE=null,OGC=null,CGN=null,CGF=null,FGN=null,FGO=null,FGFlags=null,FSGV=null;
function _proto(){ if(PROTO_IMAGE)return; _ensureInit(); var il=Process.findModuleByName('libil2cpp.so'); function nf(n,r,a){return new NativeFunction(il.getExportByName(n),r,a);}
 OGC=nf('il2cpp_object_get_class','pointer',['pointer']); CGN=nf('il2cpp_class_get_name','pointer',['pointer']); CGF=nf('il2cpp_class_get_fields','pointer',['pointer','pointer']); FGN=nf('il2cpp_field_get_name','pointer',['pointer']); FGO=nf('il2cpp_field_get_offset','uint32',['pointer']); FGFlags=nf('il2cpp_field_get_flags','int',['pointer']); FSGV=nf('il2cpp_field_static_get_value','void',['pointer','pointer']);
 var sp=Memory.alloc(4); var asms=IL2.dGA(IL2.dG(),sp); var na=sp.readS32(); for(var a=0;a<na;a++){var im=IL2.aGI(asms.add(a*Process.pointerSize).readPointer()); if(IL2.iGN(im).readCString()==='holo-protos.dll'){PROTO_IMAGE=im;break;}} }
function protoCls(ns,nm){_proto(); return IL2.cFN(PROTO_IMAGE,Memory.allocUtf8String(ns),Memory.allocUtf8String(nm));}
function clsName(o){try{if(!o||o.isNull())return null;return CGN(OGC(o)).readCString();}catch(e){return null;}}
function rfInts(rf){var out=[];try{if(!rf||rf.isNull())return out;var arr=rf.add(0x10).readPointer();var cnt=rf.add(0x18).readS32();if(arr&&!arr.isNull()&&cnt>0&&cnt<32)for(var i=0;i<cnt;i++)out.push(arr.add(0x20).add(i*4).readS32());}catch(e){}return out;}
rpc.exports.dumpEnum=function(ns,name){ _proto(); var cls=protoCls(ns,name); if(!cls||cls.isNull())return {err:'no '+name}; var out={}; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f; while((f=CGF(cls,it))&&!f.isNull()){try{var fl=FGFlags(f); if(!((fl&0x10)&&(fl&0x40)))continue; var nm=FGN(f).readCString(); if(nm==='value__')continue; var buf=Memory.alloc(8); buf.writeU64(0); FSGV(f,buf); out[buf.readS32()]=nm;}catch(e){}} return {map:out}; };
rpc.exports.readBadge=function(addr){ _proto(); var p=ptr(addr); var cls=OGC(p); var off={}; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
 while((f=CGF(cls,it))&&!f.isNull()){try{off[FGN(f).readCString()]=FGO(f);}catch(e){}}
 var bt=null,btn=null; ['BadgeType','badgeType','Type','badgeTypeId'].forEach(function(n){if(off[n]!==undefined&&bt===null){try{bt=p.add(off[n]).readS32();btn=n;}catch(e){}}});
 var tgt=[],tn=null; ['Target','target','Targets','targets','TargetValue'].forEach(function(n){ if(off[n]!==undefined&&tgt.length===0){var t=rfInts(p.add(off[n]).readPointer());if(t.length){tgt=t;tn=n;}} });
 return {cls:clsName(p), fields:Object.keys(off), badgeType:bt, btField:btn, targets:tgt, tField:tn};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, READER_JS)
    try:
        en = sc.exports_sync.dump_enum('Holoholo.Rpc', 'HoloBadgeType')
        berry_ids = {}
        if isinstance(en, dict) and en.get('map'):
            for k, v in en['map'].items():
                if 'berr' in v.lower() or 'feed' in v.lower():
                    berry_ids[int(k)] = v
        print("berry/feed badge enum entries:", berry_ids)

        r = finder.exports_sync.find_singleton('Holoholo.Rpc', 'BadgeSettingsProto')
        hits = (r.get('hits', []) if isinstance(r, dict) else [])
        print(f"BadgeSettingsProto instances: {len(hits)}")
        printed_sample = False
        matches = []
        allrows = []
        for h in hits:
            b = sc.exports_sync.read_badge(h)
            if not printed_sample:
                print("  sample fields:", b.get('fields'))
                print("  btField:", b.get('btField'), " tField:", b.get('tField'))
                printed_sample = True
            bt = b.get('badgeType'); tg = b.get('targets') or []
            allrows.append((bt, tuple(tg)))
            if bt in berry_ids and tg:
                matches.append((berry_ids[bt], bt, tg))
        print()
        if matches:
            for name, bt, tg in matches:
                print(f">>> {name} (type {bt})  TIER TARGETS = {tg}")
        else:
            print("no BadgeSettingsProto matched a berry/feed badge type; distinct (type,targets) seen:")
            for row in sorted(set(allrows))[:40]:
                print("   ", row)
    finally:
        try:
            sc.unload(); finder.unload()
        except Exception:
            pass
        try:
            sess.detach()
        except Exception:
            pass


main()
