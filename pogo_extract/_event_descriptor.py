"""READ-ONLY: use protobuf reflection (MessageDescriptor.Fields -> FieldDescriptor
.Name + .Accessor.GetValue(message)) to read populated event protos by their REAL
.proto field names, bypassing the obfuscated C# getters. Reads a live EventSectionProto
(and its children) + DailyBonusProto + a live EventInfoProto if any field yields one."""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402

TARGETS = ["EventSectionProto", "EventInfoProto", "DailyBonusProto", "AppliedBonusesProto",
           "AppliedBonusProto", "ContestScheduleProto", "EventSettingsProto"]

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),
  OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),rcInit:b("il2cpp_runtime_class_init","void",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"]),
  alloc:b("il2cpp_alloc","pointer",["size_t"]),free:b("il2cpp_free","void",["pointer"]),
  strChars:b("il2cpp_string_chars","pointer",["pointer"]),strLen:b("il2cpp_string_length","int",["pointer"]),
  cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),
  livenessAlloc:b("il2cpp_unity_liveness_allocate_struct","pointer",["pointer","int","pointer","pointer","pointer"]),livenessFromStatics:b("il2cpp_unity_liveness_calculation_from_statics","void",["pointer"]),livenessFinalize:b("il2cpp_unity_liveness_finalize","void",["pointer"]),livenessFreeStruct:b("il2cpp_unity_liveness_free_struct","void",["pointer"]),stopWorld:b("il2cpp_stop_gc_world","void",[]),startWorld:b("il2cpp_start_gc_world","void",[])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function classInProtos(cls){var h=H_();var im=img("holo-protos.dll");if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function S(s){var h=H_();if(!s||s.isNull())return null;try{var len=h.strLen(s);var cp=h.strChars(s);if(!cp||cp.isNull())return null;return cp.readUtf16String(len);}catch(e){try{return s.add(0x14).readUtf16String();}catch(e2){return null;}}}
function call0(inst,name){var h=H_();var m=h.cMN(h.OGC(inst),Memory.allocUtf8String(name),0);if(!m||m.isNull())return undefined;var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,inst,ptr(0),exc);if(!exc.readPointer().isNull())return undefined;return r;}
function call1(inst,name,arg){var h=H_();var m=h.cMN(h.OGC(inst),Memory.allocUtf8String(name),1);if(!m||m.isNull())return undefined;var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,inst,args,exc);if(!exc.readPointer().isNull())return undefined;return r;}
function liveness(klass){var h=H_();try{if(h.rcInit)h.rcInit(klass);}catch(e){}var hits=[];var onObjects=new NativeCallback(function(objects,count,userData){for(var i=0;i<count;i++){hits.push(objects.add(i*Process.pointerSize).readPointer().toString());}},'void',['pointer','int','pointer']);var realloc=new NativeCallback(function(handle,size,userData){if(!handle.isNull()&&size.compare(0)===0){h.free(handle);return ptr(0);}return h.alloc(size);},'pointer',['pointer','size_t','pointer']);try{if(h.stopWorld)h.stopWorld();var st=h.livenessAlloc(klass,0,onObjects,ptr(0),realloc);h.livenessFromStatics(st);if(h.livenessFinalize)h.livenessFinalize(st);if(h.startWorld)h.startWorld();if(h.livenessFreeStruct)h.livenessFreeStruct(st);}catch(e){if(h.startWorld){try{h.startWorld();}catch(e2){}}return {err:"threw "+e};}return {hits:hits};}
rpc.exports.live=function(cls){var k=classInProtos(cls);if(!k)return {err:"nf"};return liveness(k);};

// Enumerate enumerable (IEnumerable / RepeatedField) -> array of element ptrs
function toList(enumObj){var h=H_();var out=[];if(!enumObj||enumObj.isNull())return out;var gem=h.cMN(h.OGC(enumObj),Memory.allocUtf8String("GetEnumerator"),0);if(!gem||gem.isNull())return out;var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var enr=h.rI(gem,enumObj,ptr(0),exc);if(!enr||enr.isNull())return out;var enrC=h.OGC(enr);var mn=h.cMN(enrC,Memory.allocUtf8String("MoveNext"),0),gc=h.cMN(enrC,Memory.allocUtf8String("get_Current"),0);if(!mn||!gc)return out;var guard=0;while(guard++<200){var e2=Memory.alloc(Process.pointerSize);e2.writePointer(ptr(0));var r=h.rI(mn,enr,ptr(0),e2);if(!r||r.add(0x10).readU8()===0)break;var e3=Memory.alloc(Process.pointerSize);e3.writePointer(ptr(0));var cur=h.rI(gc,enr,ptr(0),e3);out.push(cur);}return out;}

// Reflectively read a message's fields via Descriptor: returns [{num,name,val}] where val is
// a string (for scalars/strings) or a child-ptr marker for sub-messages.
function reflect(inst,depth){var h=H_();var res=[];if(!inst||inst.isNull())return res;
 var clsName=""; try{clsName=h.CGN(h.OGC(inst)).readCString();}catch(e){}
 var desc=call0(inst,"get_Descriptor"); if(!desc||desc.isNull())return [{_err:"no descriptor",cls:clsName}];
 var fields=call0(desc,"get_Fields"); if(!fields||fields.isNull())return [{_err:"no Fields",cls:clsName}];
 // MessageDescriptor.FieldCollection.InFieldNumberOrder() -> IList<FieldDescriptor>
 var ordered=call0(fields,"InFieldNumberOrder"); if(!ordered||ordered.isNull())ordered=fields;
 var list=toList(ordered);
 for(var i=0;i<list.length;i++){ var fd=list[i]; if(!fd||fd.isNull())continue;
  var nm=null,num=null; try{nm=S(call0(fd,"get_Name"));}catch(e){} try{var nr=call0(fd,"get_FieldNumber"); if(nr)num=nr.add(0x10).readS32();}catch(e){}
  var acc=null; try{acc=call0(fd,"get_Accessor");}catch(e){}
  var val=undefined; if(acc&&!acc.isNull()){ try{val=call1(acc,"GetValue",inst);}catch(e){} }
  var entry={num:num,name:nm};
  if(val===undefined||val===null){entry.val=null;}
  else if(val.isNull&&val.isNull()){entry.val=null;}
  else{ // figure out the value type
   var vc=""; try{vc=h.CGN(h.OGC(val)).readCString();}catch(e){vc="?";}
   entry.vcls=vc;
   if(vc==="String"){entry.val=S(val);}
   else if(vc==="Int64"||vc==="UInt64"){entry.val=val.add(0x10).readS64().toString();}
   else if(vc==="Int32"||vc==="UInt32"){entry.val=val.add(0x10).readS32();}
   else if(vc==="Boolean"){entry.val=val.add(0x10).readU8();}
   else if(vc==="Single"){entry.val=val.add(0x10).readFloat();}
   else if(vc==="Double"){entry.val=val.add(0x10).readDouble();}
   else if(vc.indexOf("RepeatedField")>=0||vc.indexOf("List")>=0||vc.indexOf("Enumerable")>=0){
     var els=toList(val); var sub=[]; for(var j=0;j<els.length&&j<12;j++){ if(depth>0){sub.push(reflect(els[j],depth-1));}else{var ec="";try{ec=h.CGN(h.OGC(els[j])).readCString();}catch(e){} sub.push({_cls:ec,_ptr:els[j].toString()});} } entry.val={list:sub,n:els.length};
   }
   else if(vc.indexOf("Proto")>=0){ if(depth>0){entry.val={msg:reflect(val,depth-1)};}else{entry.val={_cls:vc,_ptr:val.toString()};} }
   else{ // boxed enum or other: read int at +0x10
     try{entry.val={enumInt:val.add(0x10).readS32(),vcls:vc};}catch(e){entry.val={_cls:vc,_ptr:val.toString()};}
   }
  }
  res.push(entry);
 }
 return {cls:clsName,fields:res};
}
rpc.exports.reflect=function(instStr,depth){return reflect(ptr(instStr),depth||1);};
"""


def nonempty(rf):
    # heuristic: a reflect() result that has at least one non-null field value
    try:
        for f in rf.get("fields", []):
            v = f.get("val")
            if v not in (None, "", 0):
                return True
    except Exception:
        pass
    return False


def main():
    out = {"ok": False, "events": {}}
    last_err = None
    for attempt in range(4):
        sess = None
        try:
            sess, pid = pg.get_session()
            sc = pg.get_script_with_helpers(sess, JS)
            for cls in TARGETS:
                r = sc.exports_sync.live(cls)
                hits = r.get("hits", []) if isinstance(r, dict) else []
                kept = []
                for h in hits[:10]:
                    rf = sc.exports_sync.reflect(h, 2)
                    if isinstance(rf, dict) and nonempty(rf):
                        kept.append(rf)
                out["events"][cls] = {"n": len(hits), "populated": kept[:6]}
            out["pid"] = pid
            out["ok"] = True
            print(json.dumps(out, ensure_ascii=False, indent=1))
            sess.detach()
            return
        except Exception as e:
            last_err = str(e)[:200]
            try:
                sess.detach()
            except Exception:
                pass
            time.sleep(3)
    out["error"] = last_err
    print(json.dumps(out))


main()
