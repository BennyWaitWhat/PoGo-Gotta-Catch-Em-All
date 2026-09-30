MOBILE_HTML = r"""<!doctype html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0b1020">
<title>PoGo Audit</title>
<style>
:root{--bg:#0b1020;--card:#141b31;--line:#243052;--tx:#e8edff;--dim:#8fa0c8;
      --ok:#2ecc71;--bad:#ff5566;--warn:#ffb020;--go:#3b82f6}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--tx);
     font:16px/1.45 -apple-system,system-ui,Roboto,sans-serif;
     padding:max(14px,env(safe-area-inset-top)) 14px max(14px,env(safe-area-inset-bottom))}
h1{font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin:2px 0 14px;text-align:center}
.big{width:100%;border:0;border-radius:20px;background:var(--go);color:#fff;
     font-size:26px;font-weight:800;letter-spacing:.04em;padding:30px 16px;
     box-shadow:0 8px 26px rgba(59,130,246,.42)}
.big:active{transform:scale(.985)}
.big[disabled]{background:#2a3350;box-shadow:none;color:#8fa0c8}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;margin-top:14px}
.row{display:flex;justify-content:space-between;align-items:baseline;padding:5px 0}
.row b{font-size:21px}
.k{color:var(--dim);font-size:13px}
.pile{font-size:52px;font-weight:800;text-align:center;line-height:1.05;margin:2px 0}
.pill{display:inline-block;padding:3px 11px;border-radius:999px;font-size:12px;font-weight:700}
.p-ok{background:rgba(46,204,113,.16);color:var(--ok)}
.p-bad{background:rgba(255,85,102,.16);color:var(--bad)}
.p-run{background:rgba(255,176,32,.16);color:var(--warn)}
#step{color:var(--dim);font-size:13px;min-height:19px;margin-top:9px;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#log{background:#080d1a;border:1px solid var(--line);border-radius:12px;padding:10px;
     font:11px/1.4 ui-monospace,Menlo,monospace;color:#a9b6d6;height:210px;overflow:auto;
     white-space:pre-wrap;margin-top:10px;display:none}
.mini{width:100%;border:1px solid var(--line);background:transparent;color:var(--dim);
      border-radius:12px;padding:11px;font-size:13px;margin-top:9px}
</style></head><body>
<h1>Pokémon Audit</h1>

<button class="big" id="go">FULL AUDIT</button>
<div id="step"></div>

<div class="card">
  <div class="k" style="text-align:center">TAGGED FOR TRANSFER — SAFE TO CULL</div>
  <div class="pile" id="pile">–</div>
  <div style="text-align:center"><span class="pill p-ok" id="verdict">idle</span></div>
</div>

<div class="card">
  <div class="row"><span class="k">Bag</span><b id="bag">–</b></div>
  <div class="row"><span class="k">Free slots</span><b id="free">–</b></div>
  <div class="row"><span class="k">Hundos</span><b id="hundo">–</b></div>
  <div class="row"><span class="k">Nundos</span><b id="nundo">–</b></div>
  <div class="row"><span class="k">Last run</span><b id="when" style="font-size:14px">–</b></div>
</div>

<button class="mini" id="tog">show log</button>
<pre id="log"></pre>

<script>
const $=s=>document.querySelector(s);
let running=false;
const j=async(u,o)=>(await fetch(u,o)).json();

$('#tog').onclick=()=>{const l=$('#log');const v=l.style.display==='none';
  l.style.display=v?'block':'none';$('#tog').textContent=v?'hide log':'show log';};

$('#go').onclick=async()=>{
  if(running)return;
  if(!confirm('Run the FULL AUDIT?\n\nRecrawl → 4 audits → sync tags → verify.\nNothing is ever released; it only tags.'))return;
  $('#verdict').textContent='starting…';$('#verdict').className='pill p-run';
  const r=await j('/api/full_audit',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if(!r.ok){$('#verdict').textContent=r.error||'busy';$('#verdict').className='pill p-bad';}
  poll();
};

async function stats(){
  try{const s=await j('/api/stats_lite');
    $('#pile').textContent=s.pile;$('#bag').textContent=s.bag+' / '+s.cap;
    $('#free').textContent=s.cap-s.bag;$('#hundo').textContent=s.hundos;
    $('#nundo').textContent=s.nundos;$('#when').textContent=s.when||'–';
  }catch(e){}
}

async function poll(){
  let job;
  try{job=await j('/api/job');}catch(e){
    $('#verdict').textContent='desktop offline';$('#verdict').className='pill p-bad';
    running=false;$('#go').disabled=false;$('#go').textContent='FULL AUDIT';
    setTimeout(poll,4000);return;}
  running=!!job.running;
  $('#go').disabled=running;
  $('#go').textContent=running?'RUNNING…':'FULL AUDIT';
  const lines=(job.log||'').split('\n').filter(x=>x.trim());
  $('#step').textContent=running?(lines[lines.length-1]||'').slice(0,120):'';
  const L=$('#log');const at=L.scrollTop+L.clientHeight>=L.scrollHeight-30;
  L.textContent=(job.log||'').slice(-9000);if(at)L.scrollTop=L.scrollHeight;
  if(running){$('#verdict').textContent=job.name||'running';$('#verdict').className='pill p-run';}
  else if(job.rc===0){$('#verdict').textContent='✓ verified — safe to cull';$('#verdict').className='pill p-ok';}
  else if(job.rc!==null&&job.rc!==undefined){
    $('#verdict').textContent='✕ '+(job.status||'failed')+' — DO NOT cull';$('#verdict').className='pill p-bad';}
  stats();
  setTimeout(poll,running?1500:5000);
}
poll();
</script></body></html>"""
