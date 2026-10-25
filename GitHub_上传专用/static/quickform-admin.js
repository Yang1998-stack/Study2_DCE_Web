'use strict';
window.QuickFormAdmin=(()=>{
 let request=null,runMode=null,version=null;
 const labels={pending:'待同步',success:'已确认成功',failed:'明确失败',uncertain:'需人工核查'};
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const mode=()=>document.getElementById('dataset')?.value;
 const query=()=>`mode=${encodeURIComponent(mode())}&design_version=${encodeURIComponent(document.getElementById('design-version')?.value||version)}`;
 function mount(api,currentMode,v){
   request=api;runMode=currentMode;version=v;
   document.getElementById('admin-app').insertAdjacentHTML('beforeend',`<section class="card admin-section" id="qf-panel"><h2>QuickForm数据同步</h2><p class="muted">本地答卷是原始记录。只在完成8题和后续问卷后建单。demo不上传；pilot必须使用独立测试任务。UUID用于核查，不保证远端绝对不重复。</p><div id="qf-counts" class="metrics"></div><p id="qf-meta"></p><div class="actions"><button id="qf-refresh" class="button ghost">刷新同步状态</button><a id="qf-logs" class="button ghost">导出同步日志</a><a id="qf-data" class="button ghost">导出原始与长格式CSV</a></div><div class="field"><label for="qf-search">查找本地编号 / 全局UUID</label><input id="qf-search" type="search"></div><div class="table-wrap"><table><thead><tr><th>本地编号 / 全局UUID</th><th>状态</th><th>尝试数</th><th>最近尝试 / HTTP</th><th>摘要</th><th>操作</th></tr></thead><tbody id="qf-rows"></tbody></table></div><p id="qf-size" class="muted"></p><details><summary>重试、补建任务或人工核查</summary><form id="qf-action"><div class="field"><label for="qf-pid">本地participant_id</label><input id="qf-pid" required></div><div class="field"><label for="qf-operation">操作</label><select id="qf-operation"><option value="retry">重新同步明确失败 / 尚未发送的记录</option><option value="enqueue">为尚未建单的历史完整答卷建单</option><option value="received">已在QuickForm核实收到，人工标记成功</option><option value="not_received">已核实未收到，承担重复风险后重新排队</option></select></div><div class="field"><label for="qf-note">操作原因 / 远端核查依据（至少5字）</label><textarea id="qf-note" rows="3" minlength="5" maxlength="500" required></textarea></div><label class="check"><input id="qf-confirm" type="checkbox"><span>人工核查时必须勾选：已按全局UUID及record_sha256核对远端；了解超时重发仍有重复风险。</span></label><button class="button" id="qf-execute">执行所选操作</button></form><p id="qf-result" role="status"></p></details><dialog id="qf-record" class="detail-dialog" aria-labelledby="qf-record-title"><header class="detail-header"><h3 id="qf-record-title">单条同步记录（仅研究者）</h3><button id="qf-record-close" class="button ghost" type="button">关闭记录</button></header><pre id="qf-record-body"></pre></dialog></section>`);
   document.getElementById('qf-refresh').onclick=()=>refresh().catch(showError);
   document.getElementById('qf-search').oninput=draw;
   document.getElementById('qf-record-close').onclick=()=>document.getElementById('qf-record').close();
   document.getElementById('qf-action').onsubmit=act;
   document.getElementById('dataset').addEventListener('change',()=>refresh().catch(showError));
   refresh().catch(showError);
 }
 let latest=null;
 function showError(e){const el=document.getElementById('qf-result');if(el){el.className='error';el.textContent=e.message;}}
 async function refresh(){
   if(!request||!document.getElementById('qf-panel'))return;
   const snapshot=query(),d=await request('quickform?'+snapshot);if(snapshot!==query()||!document.getElementById('qf-panel'))return;
   latest=d;document.getElementById('qf-counts').innerHTML=[['本地已完成',d.completed_local],['同步成功',d.counts.success],['待同步',d.counts.pending],['失败',d.counts.failed],['需人工核查',d.counts.uncertain],['未建单',d.not_enqueued]].map(([label,n])=>`<div><span>${label}</span><strong>${n}</strong></div>`).join('');
   document.getElementById('qf-meta').textContent=`当前筛选：${mode()}；本服务模式：${runMode}；同步${d.enabled?'启用':'未启用'}。${d.configuration_reason}。最近尝试：${d.last_sync_at||'暂无'}。${d.note}`;
   document.getElementById('qf-logs').href='/api/admin/quickform/logs?'+query();document.getElementById('qf-data').href='/api/admin/export?'+query();
   document.getElementById('qf-execute').disabled=mode()!==runMode||mode()==='demo'||document.getElementById('design-version')?.value!==version;draw();
 }
 function draw(){if(!latest)return;const q=document.getElementById('qf-search').value.toLowerCase();const rows=latest.rows.filter(r=>(r.participant_id+' '+(r.submission_uuid||'')).toLowerCase().includes(q));document.getElementById('qf-rows').innerHTML=rows.slice(0,100).map(r=>`<tr><td><code>${esc(r.participant_id)}</code><small>${esc(r.submission_uuid||'尚未建单')}</small></td><td>${r.in_flight_at?'同步中（待确认）':labels[r.status]||'未建单'}${r.confirmation==='researcher_review'?'<small>人工核查确认</small>':''}</td><td>${r.attempt_count??0}</td><td>${esc(r.last_attempt_at||'—')}<br>${r.last_http_status??'—'}</td><td>${esc(r.last_error||'—')}</td><td>${r.status?`<button class="button ghost qf-show" data-id="${esc(r.participant_id)}">查看记录</button>`:''}${r.status==='failed'||!r.status?`<button class="button ghost qf-prepare" data-id="${esc(r.participant_id)}" data-operation="${r.status?'retry':'enqueue'}">${r.status?'准备重试':'准备建单'}</button>`:''}</td></tr>`).join('');document.getElementById('qf-size').textContent=`共${rows.length}条，显示前100条；可用编号查找单条。`;
   for(const b of document.querySelectorAll('.qf-show'))b.onclick=async()=>{try{const d=await request('quickform/record?participant_id='+encodeURIComponent(b.dataset.id));document.getElementById('qf-record-body').textContent=JSON.stringify(d,null,2);document.getElementById('qf-record').showModal();}catch(e){showError(e);}};
   for(const b of document.querySelectorAll('.qf-prepare'))b.onclick=()=>{document.getElementById('qf-action').closest('details').open=true;document.getElementById('qf-pid').value=b.dataset.id;document.getElementById('qf-operation').value=b.dataset.operation;document.getElementById('qf-note').focus();};
 }
 async function act(event){event.preventDefault();const b=document.getElementById('qf-execute');b.disabled=true;try{const op=document.getElementById('qf-operation').value;await request('quickform/action',{participant_id:document.getElementById('qf-pid').value.trim(),action:op==='received'||op==='not_received'?'review':op,decision:op,note:document.getElementById('qf-note').value,confirm:document.getElementById('qf-confirm').checked});const el=document.getElementById('qf-result');el.className='note';el.textContent='操作已记录。待同步项由后端处理，不会覆盖原始答卷。';await refresh();}catch(e){showError(e);}finally{b.disabled=mode()!==runMode||mode()==='demo'||document.getElementById('design-version')?.value!==version;}}
 return {mount,refresh};
})();
