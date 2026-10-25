'use strict';
// Only process telemetry is queued locally. Choice results never enter this queue.
window.DetailPanels=(()=>{
  const dialog=document.getElementById('detail-dialog');
  const body=document.getElementById('detail-body');
  const title=document.getElementById('detail-title');
  const queues=new Map(),pumps=new Map();
  let participant=null,active=null,opening=false;
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const key=pid=>'study2-detail-pending:'+pid;
  function load(pid){if(!queues.has(pid)){let saved=[];try{saved=JSON.parse(localStorage.getItem(key(pid))||'[]');}catch{}queues.set(pid,new Map(Array.isArray(saved)?saved.map(p=>[p.event_id,p]):[]));}return queues.get(pid);}
  function persist(pid){try{const rows=[...load(pid).values()];if(rows.length)localStorage.setItem(key(pid),JSON.stringify(rows));else localStorage.removeItem(key(pid));}catch{}}
  async function post(path,payload){const r=await fetch('/api/details/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),credentials:'same-origin',keepalive:true});const d=await r.json();if(!r.ok)throw Error(d.error||'资料记录暂未同步');return d;}
  function pump(pid){
    if(!pid)return Promise.resolve();
    if(pumps.has(pid))return pumps.get(pid);
    const promise=(async()=>{const q=load(pid);while(q.size&&pid===participant){const [id,payload]=q.entries().next().value;try{await post('progress',payload);}catch{return;}if(JSON.stringify(q.get(id))===JSON.stringify(payload))q.delete(id);persist(pid);}})().finally(()=>pumps.delete(pid));
    pumps.set(pid,promise);return promise;
  }
  function queue(pid,payload){const q=load(pid),old=q.get(payload.event_id);q.set(payload.event_id,old?{...payload,duration_ms:Math.max(old.duration_ms,payload.duration_ms),closed:old.closed||payload.closed,reason:old.closed?old.reason:payload.reason}:payload);persist(pid);return pump(pid);}
  function measure(){if(active?.since!==null&&active){active.ms+=Math.max(0,performance.now()-active.since);active.since=null;}}
  function snapshot(closed,reason){measure();if(!active)return null;const payload={event_id:active.id,duration_ms:Math.floor(active.ms),shown:true,closed,reason};if(!closed&&document.visibilityState==='visible')active.since=performance.now();return payload;}
  function save(closed=false,reason='heartbeat'){if(!active)return Promise.resolve();return queue(active.pid,snapshot(closed,reason));}
  async function close(reason='close'){
    if(!active){if(dialog.open)dialog.close();return;}
    const pending=save(true,reason);clearInterval(active.timer);active=null;dialog.close();await pending;
  }
  function fields(rows){return `<dl class="document-fields">${rows.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>`;}
  async function open({participant_id,task_id,alternative,kind}){
    if(opening)return;opening=true;
    try{
      await close('switch');participant=participant_id;
      const random=new Uint8Array(16);crypto.getRandomValues(random);
      const event_id=Array.from(random,x=>x.toString(16).padStart(2,'0')).join('');
      const d=await post('open',{event_id,task_id,alternative,kind});
      title.textContent=`燕麦饮${alternative} · ${d.title}`;
      body.innerHTML=`<p class="simulation-notice">${esc(d.notice)}</p><section class="document-base" data-base="${esc(kind)}"><h3>${kind==='environment'?'基础环境信息':'常规商品信息'}</h3>${fields(d.base)}</section>${d.extra?`<section class="document-extra" data-extra="${esc(kind)}"><h3>${esc(d.extra.title)}</h3>${fields(d.extra.rows)}</section>`:''}`;
      dialog.showModal();dialog.scrollTop=0;document.getElementById('detail-close').focus();
      active={id:event_id,pid:participant_id,ms:0,since:document.visibilityState==='visible'?performance.now():null};
      active.timer=setInterval(()=>save(),5000);save(false,'heartbeat');
    }finally{opening=false;}
  }
  document.getElementById('detail-close').onclick=()=>close();
  dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  dialog.addEventListener('click',e=>{const b=dialog.getBoundingClientRect();if(e.target===dialog&&(e.clientX<b.left||e.clientX>b.right||e.clientY<b.top||e.clientY>b.bottom))close();});
  document.addEventListener('visibilitychange',()=>{if(!active)return;if(document.visibilityState==='hidden')save(false,'hidden');else{active.since=performance.now();save(false,'resume');}});
  window.addEventListener('pagehide',()=>{if(!active)return;const payload=snapshot(true,'pagehide');queue(active.pid,payload);navigator.sendBeacon('/api/details/progress',new Blob([JSON.stringify(payload)],{type:'application/json'}));});
  window.addEventListener('online',()=>pump(participant));
  setInterval(()=>pump(participant),7000);
  return {open,close,setParticipant(pid){participant=pid||null;if(participant){load(participant);pump(participant);}}};
})();
