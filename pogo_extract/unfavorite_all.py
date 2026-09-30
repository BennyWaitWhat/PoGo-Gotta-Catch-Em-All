"""Un-favorite all favorited pokemon: read FavoritesTagBinding proto list, call
PokemonBagImpl.FavoritePokemon(PokemonProto, false) on each. Self-healing."""
import frida, sys, time
sys.path.insert(0,'.')
import pogo_il2cpp as pg, pogo_pipeline as pl

JS = r"""
rpc.exports.unfavAll = function(svc, bag) {
  var il2cpp=Process.findModuleByName("libil2cpp.so");
  var exp={}; il2cpp.enumerateExports().forEach(function(e){ if(e.name.indexOf("il2cpp_")===0) exp[e.name]=e.address; });
  function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
  var dG=bind("il2cpp_domain_get","pointer",[]),dGA=bind("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
      aGI=bind("il2cpp_assembly_get_image","pointer",["pointer"]),iGN=bind("il2cpp_image_get_name","pointer",["pointer"]),
      cFN=bind("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cGM=bind("il2cpp_class_get_methods","pointer",["pointer","pointer"]),
      mGN=bind("il2cpp_method_get_name","pointer",["pointer"]),mGPC=bind("il2cpp_method_get_param_count","int",["pointer"]),
      rI=bind("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),
      rCI=bind("il2cpp_runtime_class_init","void",["pointer"]),tA=bind("il2cpp_thread_attach","pointer",["pointer"]);
  tA(dG());
  var sp=Memory.alloc(4);var asms=dGA(dG(),sp);var na=sp.readS32();var gi=null;
  for(var a=0;a<na;a++){var i=aGI(asms.add(a*8).readPointer());if(iGN(i).readCString()==="holo-game.dll"){gi=i;break;}}
  var bagCls=cFN(gi,Memory.allocUtf8String("Niantic.Holoholo.Internal"),Memory.allocUtf8String("PokemonBagImpl"));
  rCI(bagCls);
  var cMN=bind("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]);
  var ga=cMN(bagCls,Memory.allocUtf8String("get_AllPokemon"),0);
  var it2=Memory.alloc(8);it2.writePointer(ptr(0));var m,fav=null;
  while((m=cGM(bagCls,it2))&&!m.isNull()){if(mGN(m).readCString()==="FavoritePokemon"&&mGPC(m)===2)fav=m;}
  // walk bag, collect proto ptrs whose favorite byte (+0xb0) is set
  var ex=Memory.alloc(8);ex.writePointer(ptr(0));var v=rI(ga,ptr(bag),ptr(0),ex);
  var lhm=v.add(0x10).readPointer(),list=lhm.add(0x18).readPointer(),head=list.add(0x10).readPointer(),cnt=list.add(0x18).readS32();
  var protos=[];var node=head,iter=0;
  while(node&&!node.isNull()&&iter<cnt+200){
    try{var proto=node.add(0x30).readPointer();
      if(!proto.isNull()&&proto.add(0xb0).readU8()!==0) protos.push(proto);
      var nx=node.add(0x18).readPointer();if(nx.isNull()||nx.equals(head))break;node=nx;
    }catch(e){break;} iter++;
  }
  var before=protos.length;
  var falseBuf=Memory.alloc(1);falseBuf.writeU8(0);
  var done=0,errs=0;
  for(var i=0;i<protos.length;i++){
    try{
      var args=Memory.alloc(16);args.add(0).writePointer(protos[i]);args.add(8).writePointer(falseBuf);
      var e2=Memory.alloc(8);e2.writePointer(ptr(0));
      rI(fav, ptr(bag), args, e2);
      if(e2.readPointer().isNull()) done++; else errs++;
    }catch(e){errs++;}
  }
  // re-walk to count remaining favorites
  var ex3=Memory.alloc(8);ex3.writePointer(ptr(0));var v2=rI(ga,ptr(bag),ptr(0),ex3);
  var lhm2=v2.add(0x10).readPointer(),list2=lhm2.add(0x18).readPointer(),head2=list2.add(0x10).readPointer(),cnt2=list2.add(0x18).readS32();
  var after=0;var n2=head2,it3=0;
  while(n2&&!n2.isNull()&&it3<cnt2+200){try{var pr=n2.add(0x30).readPointer();if(!pr.isNull()&&pr.add(0xb0).readU8()!==0)after++;var nx2=n2.add(0x18).readPointer();if(nx2.isNull()||nx2.equals(head2))break;n2=nx2;}catch(e){break;}it3++;}
  return {before:before, done:done, errs:errs, after:after};
};
"""

for attempt in range(8):
    try:
        sess, pid = pg.get_session()
        s = pl.step_singletons(sess); SVC=s['svc']; BAG=s['bag']
        sc = pg.get_script_with_helpers(sess, JS)
        r = sc.exports_sync.unfav_all(SVC, BAG)
        print(f"favorites before={r['before']} unfavorited={r['done']} errors={r['errs']} after={r['after']}")
        sess.detach()
        break
    except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError, frida.ServerNotRunningError) as e:
        print(f"[retry {attempt+1}] {type(e).__name__}"); time.sleep(4)
