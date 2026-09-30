const fs=require('fs');
function run(name, scen){
  const src=fs.readFileSync(process.argv[2]||'rc.js','utf8');
  const f=new Function('ptr','Process','Memory','Interceptor', src+`
   ;return {get:(k)=>eval(k), set:(k,v)=>eval(k+'=v'), tick:()=>tick()};`);
  // minimal fakes
  const P=(v)=>({v, isNull:()=>v===0, equals:(o)=>o.v===v});
  const api=f(P, {pointerSize:8}, {}, {});
  let queue=scen.rewards.slice(), box=100, thrown=[], openFrame=0, cur=null, frame=0, pendingClear=null;
  // override game calls
  api.set('getDangling', function(t){ if(pendingClear&&frame>=pendingClear.at){ queue=queue.filter(x=>x!==pendingClear.id); pendingClear=null;} return queue.length? P(queue[0]) : P(0); });
  api.set('openEnc', function(p){ cur=p.v; api.set('ACTIVE_QMP', P(1)); });
  api.set('qmpId', function(){ return String(cur); });
  api.set('readBox', function(){ return box; });
  api.set('fireCatch', function(){ thrown.push([frame,cur]); const r=scen.onThrow(cur, thrown.filter(x=>x[1]===cur).length);
       if(r.register){ box+=1; pendingClear={id:cur, at:frame+(r.clearAfter||5)}; } });
  api.set('RUN', true); api.set('ST', 0); api.set('BALL',1); api.set('TYPES',[4]); api.set('MAX',0);
  for(frame=0; frame<5000 && api.get('RUN'); frame++){ if(pendingClear&&frame>=pendingClear.at){ queue=queue.filter(x=>x!==pendingClear.id); pendingClear=null;} api.tick(); }
  console.log(name.padEnd(14), 'frames', frame, 'throws', thrown.length, JSON.stringify(thrown.map(x=>x[1])), 'box+', box-100,
              'lost', api.get('LOST'), 'slowconf', api.get('SLOWCONF'), 'stalls', api.get('STALLS'), 'ST', api.get('ST'), 'errs', JSON.stringify(api.get('ERRS')));
}
run('normal',    {rewards:[11,12,13], onThrow:(id,n)=>({register:true})});
run('lost-once', {rewards:[11,12,13], onThrow:(id,n)=>({register: !(id===12 && n===1)})});
run('slow-clear',{rewards:[11,12,13], onThrow:(id,n)=>({register:true, clearAfter: id===12?220:5})});
run('never',     {rewards:[11,12],    onThrow:(id,n)=>({register: id!==12})});
