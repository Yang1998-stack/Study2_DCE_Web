import { active, codes, designOf, details, offers, PROCESS, SURVEY, VISUAL } from './data';
import { all, one, run, stmt } from './db';
import { metrics, participantUuid } from './records';
import { assert, digest, modeOf, now, seconds, token } from './security';
import type { Env, Mode, Row } from './types';
export const DEFAULT_API='https://quickform.cn/api/kajm9wjasx';
// This migration release deliberately cannot upload to any real formal task.
export const FORMAL_SYNC_RELEASE_LOCK=true;
const RESERVED=['/api/kajm9wjasx','/api/9lnrb0a8hn'];
export function canonical(value:string,local=false){const u=new URL(value);assert(!u.username&&!u.password&&!u.search&&!u.hash&&/^\/api\/[A-Za-z0-9_-]+\/?$/.test(decodeURIComponent(u.pathname)),'QuickForm接口格式不正确');assert(local?['127.0.0.1','localhost','[::1]'].includes(u.hostname):u.protocol==='https:','测试只允许环回地址，外部接口必须HTTPS');u.pathname=u.pathname.replace(/\/$/,'');return u.href}
export function syncConfig(env:Env){
  const mode=modeOf(env),local=env.QUICKFORM_ALLOW_LOCAL_TEST==='YES',formal=canonical(env.QUICKFORM_API_URL||DEFAULT_API,local),pilot=env.QUICKFORM_PILOT_API_URL?canonical(env.QUICKFORM_PILOT_API_URL,local):null;
  if(pilot)assert(new URL(pilot).pathname!==new URL(formal).pathname&&!RESERVED.includes(new URL(pilot).pathname),'pilot必须使用独立测试任务，不能使用曾指定的正式任务');
  const target=mode==='formal'?formal:mode==='pilot'?pilot:null;
  const enabled=mode==='pilot'&&!!target&&env.QUICKFORM_PILOT_ENABLED==='YES';
  const timeout=Number(env.QUICKFORM_TIMEOUT_SECONDS||8),max=Number(env.QUICKFORM_MAX_ATTEMPTS||3),backoff=Number(env.QUICKFORM_BACKOFF_SECONDS||10);
  assert(timeout>=0.1&&timeout<=30&&Number.isInteger(max)&&max>=1&&max<=5&&backoff>=1&&backoff<=3600,'同步重试配置错误');
  return {mode,target,enabled,timeout,max,backoff,reason:mode==='formal'?'Workers迁移验收版正式QuickForm通道强制关闭':mode==='demo'?'demo永不上传':enabled?'独立预测试接口已显式启用':'未启用或未设置独立预测试接口'};
}
function sorted(value:any):any{return Array.isArray(value)?value.map(sorted):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,sorted(value[k])])):value}
export async function payload(db:D1Database,p:Row){
  const d=designOf(p.design_version);assert(p.completed_at&&p.task_hash===d.config.task_sha256,'仅同步完整且版本一致的答卷');
  const sets=await db.batch([stmt(db,'SELECT * FROM choices WHERE participant_id=?',p.id),stmt(db,'SELECT * FROM task_views WHERE participant_id=?',p.id),stmt(db,'SELECT * FROM detail_views WHERE participant_id=? ORDER BY opened_at,event_id',p.id)]);
  const [answers,views,events]=sets.map(r=>r.results as Row[]),order:string[]=JSON.parse(p.task_order);
  assert(order.length===8&&answers.length===8&&new Set(order).size===8&&order.every(t=>d.byBlock[p.block].some(x=>x.id===t))&&answers.every(a=>order.includes(a.task_id)),'DCE必须恰好8题且与区组一致');
  assert(p.age>=18&&p.age<=100&&Object.entries(SURVEY).every(([k,v])=>v.includes(p[k])),'后续问卷不完整');
  const id=await participantUuid(p),extra=JSON.parse(p.additional_answers||'{}'),questionnaire={age:p.age,...Object.fromEntries(Object.keys(SURVEY).map(k=>[k,p[k]])),...extra};
  const out:Row={payload_version:'study2-qf-v2',record_type:'study2_dce_completed',participant_id:id,participant_uuid:id,local_participant_id:p.id,source_instance:p.source_instance,source_participant_id:p.source_participant_id,submission_key:`${id}:${p.design_version}`,experiment_group:`G${p.group_code}`,visual_type:VISUAL(p.group_code),visual_code:[1,3].includes(p.group_code)?'chart':'nature',visual:Number([1,3].includes(p.group_code)),ai_disclosure:Number([3,4].includes(p.group_code)),dce_block:p.block,design_version:p.design_version,task_design_sha256:p.task_hash,survey_mode:p.mode,product_volume_ml:d.config.product_volume_ml,started_at:p.created_at,completed_at:p.completed_at,duration_seconds:seconds(p.created_at,p.completed_at),dce_duration_seconds:seconds(p.dce_started_at,p.dce_completed_at),completion_status:'completed',n_choice_tasks:8,stimulus_started_at:p.stimulus_started_at,stimulus_end_at:p.stimulus_end_at,stimulus_versions_json:p.stimulus_versions,consent_version:p.consent_version,questionnaire_json:JSON.stringify(questionnaire),green_consumption_values_json:JSON.stringify(extra.green_consumption_values??null),green_consumption_values_status:Object.hasOwn(extra,'green_consumption_values')?'collected':'not_collected',oat_drink_purchase_experience:extra.oat_drink_purchase_experience??null,oat_drink_purchase_experience_status:Object.hasOwn(extra,'oat_drink_purchase_experience')?'collected':'not_collected',age:p.age};
  for(const k of Object.keys(SURVEY))out[k]=p[k];for(const [k,v]of Object.entries(extra))out['questionnaire_'+k]=typeof v==='object'?JSON.stringify(v):v;
  const items:Row[]=[];
  for(let i=0;i<8;i++){
    const tid=order[i],o=offers(p,tid),answer=answers.find(a=>a.task_id===tid)!,view=views.find(v=>v.task_id===tid);
    const item:Row={task_id:tid,position:i+1,swapped:o.swapped,choice:answer.displayed_choice,started_at:view?.started_at??null,completed_at:answer.answered_at,duration_seconds:seconds(view?.started_at,answer.answered_at),display_content_version:view?.content_version??null,display_text_provenance:view?.a_json?'server_delivery_snapshot':'not_recorded_legacy',original_a:codes(o.original_a),original_b:codes(o.original_b)};
    for(const alt of ['A','B'] as const){const actual=codes(alt==='A'?o.a:o.b),saved=view?.[alt.toLowerCase()+'_json']?JSON.parse(view[alt.toLowerCase()+'_json']):null;
      assert(!saved||Object.keys(actual).every(k=>saved.codes[k]===actual[k as keyof typeof actual]),'显示属性与快照不一致');
      const text=saved?.display??{origin:null,environmental_verification:null,quality_information:null,price:null,capacity:null};
      item[alt]={codes:actual,display:text,process:metrics(p,tid,alt,events,answer)};
      for(const k of ['origin','environmental_verification','quality_information','price']){out[`task_${i+1}_${alt}_${k}`]=actual[k as keyof typeof actual];out[`task_${i+1}_${alt}_${k}_text`]=text[k]}
      for(const k of ['price_yuan','price_level','product_volume_ml'])out[`task_${i+1}_${alt}_${k}`]=actual[k as keyof typeof actual];
    }
    for(const k of ['position','choice','swapped','started_at','completed_at','duration_seconds'])out[`task_${i+1}_${k}`]=item[k];out[`task_${i+1}_id`]=tid;items.push(item);
  }
  out.dce_choices_json=JSON.stringify(items);out.detail_views_json=JSON.stringify(events.map(e=>Object.fromEntries(['event_id','task_id','alternative','kind','level','content_version','opened_at','shown_at','updated_at','closed_at','duration_ms','close_reason'].map(k=>[k,e[k]]))));
  out.record_sha256=await digest(JSON.stringify(sorted(out)));return out;
}
export async function enqueueStatement(db:D1Database,env:Env,p:Row,completedGuard?:string){
  if(p.mode==='demo')return null;assert(!p.provenance.startsWith('import:'),'导入记录不自动上传');const cfg=syncConfig(env),data=await payload(db,p),raw=JSON.stringify(data),stamp=now();
  return stmt(db,`INSERT OR IGNORE INTO qf_submissions(participant_id,submission_uuid,survey_mode,design_version,target_url,payload_json,payload_sha256,status,created_at,updated_at,next_attempt_at) SELECT ?,?,?,?,?,?,?,'pending',?,?,? WHERE EXISTS(SELECT 1 FROM participants WHERE id=? AND completed_at${completedGuard?'=?':' IS NOT NULL'})`,p.id,data.participant_id,p.mode,p.design_version,cfg.target,raw,await digest(raw),stamp,stamp,new Date(Date.now()+30000).toISOString(),p.id,...(completedGuard?[completedGuard]:[]));
}
export function classify(code:number,body:string){
  let d:any=null;try{d=JSON.parse(body)}catch{}const valid=d&&typeof d==='object'&&!Array.isArray(d),summary=valid?JSON.stringify(Object.fromEntries(['status','queued','spool_id','retry_after','message'].filter(k=>['string','number','boolean'].includes(typeof d[k])).map(k=>[k,typeof d[k]==='string'?d[k].slice(0,300):d[k]]))):'无可识别JSON确认';
  if(code===200&&valid&&d.status==='success'&&d.queued!==true)return {status:'success',retry:false,error:'',summary};
  if(code===429||code===503&&valid&&Number.isFinite(Number(d.retry_after))&&Object.hasOwn(d,'retry_after'))return {status:'failed',retry:true,error:`HTTP ${code}明确拒绝或繁忙`,summary};
  if(code>=400&&code<500&&![408,409].includes(code)||code===200&&valid&&['error','failed','failure'].includes(d.status))return {status:'failed',retry:false,error:`HTTP ${code}明确拒绝或JSON失败`,summary};
  return {status:'uncertain',retry:false,error:`HTTP ${code}未确认持久化，需人工核查`,summary};
}
export async function dispatch(env:Env,pid?:string,initial=false){
  const cfg=syncConfig(env);if(!cfg.enabled||cfg.mode==='demo'||!cfg.target)return false;
  if(cfg.mode==='formal'&&FORMAL_SYNC_RELEASE_LOCK)return false;
  const lease=token(),stamp=now();
  const results=await env.DB.batch([
    stmt(env.DB,`UPDATE qf_submissions SET in_flight_token=?,in_flight_at=?,last_attempt_at=?,attempt_count=attempt_count+1,cycle_attempts=cycle_attempts+1,updated_at=? WHERE participant_id=(SELECT participant_id FROM qf_submissions WHERE status='pending' AND in_flight_token IS NULL AND survey_mode=? AND design_version=? AND target_url=? ${pid?'AND participant_id=?':''} AND ${initial?'attempt_count=0':'next_attempt_at<=?'} ORDER BY created_at LIMIT 1) RETURNING *`,lease,stamp,stamp,stamp,cfg.mode,active.config.version,cfg.target,...(pid?[pid]:[]),...(initial?[]:[stamp])),
    stmt(env.DB,`INSERT INTO qf_attempts(participant_id,attempt_number,started_at,outcome,payload_sha256) SELECT participant_id,attempt_count,?,'in_flight',payload_sha256 FROM qf_submissions WHERE in_flight_token=?`,stamp,lease)
  ]);
  const row=results[0].results[0] as Row|undefined;if(!row)return false;
  let result:{status:string;retry:boolean;error:string;summary:string},http:number|null=null;
  if(await digest(row.payload_json)!==row.payload_sha256)result={status:'failed',retry:false,error:'快照哈希不一致，已阻止发送',summary:''};
  else{try{const res=await fetch(row.target_url,{method:'POST',headers:{'Content-Type':'application/json; charset=utf-8'},body:row.payload_json,redirect:'manual',signal:AbortSignal.timeout(cfg.timeout*1000)});http=res.status;const reader=res.body?.getReader(),chunks:Uint8Array[]=[];let length=0;if(reader)for(;;){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>65536){await reader.cancel();throw new Error('Response too large')}chunks.push(value)}const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length}result=classify(http,new TextDecoder().decode(bytes))}catch{result={status:'uncertain',retry:false,error:'超时、网络中断或响应异常，无法确认远端是否收到；不要自动重发',summary:''}}}
  let final=result.status,due:string|null=null;
  if(result.retry&&row.cycle_attempts<cfg.max){let advice=0;try{advice=Number(JSON.parse(result.summary).retry_after)||0}catch{}final='pending';due=new Date(Date.now()+Math.max(cfg.backoff*4**(row.cycle_attempts-1),Math.min(86400,Math.max(0,advice)))*1000).toISOString()}
  const end=now();await env.DB.batch([
    stmt(env.DB,`UPDATE qf_submissions SET status=?,updated_at=?,next_attempt_at=?,success_at=?,last_http_status=?,last_error=?,in_flight_token=NULL,in_flight_at=NULL,confirmation=?,retryable=? WHERE participant_id=? AND in_flight_token=?`,final,end,due,result.status==='success'?end:null,http,result.error||null,result.status==='success'?'http_200_status_success':null,Number(result.retry),row.participant_id,lease),
    stmt(env.DB,`UPDATE qf_attempts SET finished_at=?,http_status=?,outcome=?,error_summary=?,response_summary=? WHERE participant_id=? AND attempt_number=?`,end,http,result.status,result.error||null,result.summary,row.participant_id,row.attempt_count)
  ]);return true;
}
export async function recover(env:Env){const stamp=now();await env.DB.batch([stmt(env.DB,"UPDATE qf_submissions SET status='uncertain',in_flight_token=NULL,in_flight_at=NULL,next_attempt_at=NULL,last_error='发送过程中Worker中断，需人工核查',updated_at=? WHERE in_flight_token IS NOT NULL AND in_flight_at<?",stamp,new Date(Date.now()-60000).toISOString()),stmt(env.DB,"UPDATE qf_attempts SET outcome='uncertain',finished_at=?,error_summary='Worker中断，需人工核查' WHERE outcome='in_flight' AND started_at<?",stamp,new Date(Date.now()-60000).toISOString())])}
export async function syncStatus(env:Env,mode:string,version:string){designOf(version);assert(['demo','pilot','formal'].includes(mode),'模式错误');const cfg=syncConfig(env),rows=await all(env.DB,`SELECT p.id participant_id,q.submission_uuid,p.mode,p.group_code,p.block,p.completed_at,q.status,q.attempt_count,q.last_attempt_at,q.success_at,q.last_http_status,q.last_error,q.next_attempt_at,q.in_flight_at,q.target_url,q.confirmation,q.payload_sha256 FROM participants p LEFT JOIN qf_submissions q ON p.id=q.participant_id WHERE p.mode=? AND p.design_version=? AND p.completed_at IS NOT NULL ORDER BY p.completed_at DESC,p.id`,mode,version);return {completed_local:rows.length,counts:Object.fromEntries(['pending','success','failed','uncertain'].map(s=>[s,rows.filter(r=>r.status===s).length])),not_enqueued:rows.filter(r=>!r.status).length,last_sync_at:rows.map(r=>r.last_attempt_at).filter(Boolean).sort().at(-1)??null,rows,enabled:cfg.enabled&&mode===cfg.mode&&version===active.config.version,configuration_mode:cfg.mode,configuration_reason:cfg.reason,target:mode===cfg.mode?cfg.target:null,max_attempts:cfg.max,note:'demo不上传；正式同步在本迁移版强制关闭。UUID不能保证远端绝对不重复；uncertain须先核查。'}}
export async function syncAction(env:Env,data:Row,actor:string){
  const pid=data.participant_id,note=data.note;assert(typeof pid==='string'&&typeof note==='string'&&note.trim().length>=5&&note.length<=500,'参与编号或核查说明不合法');const cfg=syncConfig(env),p=await one(env.DB,'SELECT * FROM participants WHERE id=?',pid);assert(p&&p.mode===cfg.mode&&p.mode!=='demo','只能管理当前模式的非demo记录');const row=await one(env.DB,'SELECT * FROM qf_submissions WHERE participant_id=?',pid),statements:D1PreparedStatement[]=[];
  if(data.action==='enqueue'){assert(!row&&cfg.enabled,'已有任务或接口未启用');statements.push((await enqueueStatement(env.DB,env,p))!)}
  else{
    assert(row&&!row.in_flight_token,'任务不存在或仍在发送');
    if(data.action==='retry'){assert(['pending','failed'].includes(row.status),'仅明确失败或尚未发送可重试');assert(!(row.status==='pending'&&row.attempt_count>0),'请等待已有退避间隔');assert(cfg.enabled&&[null,cfg.target].includes(row.target_url),'目标未启用或与原任务不同');statements.push(stmt(env.DB,"UPDATE qf_submissions SET status='pending',cycle_attempts=0,next_attempt_at=?,updated_at=?,target_url=COALESCE(target_url,?),last_error=NULL WHERE participant_id=? AND status IN ('pending','failed') AND in_flight_token IS NULL",now(),now(),cfg.target,pid))}
    else{assert(data.action==='review'&&row.status==='uncertain'&&data.confirm===true,'仅不确定状态可明确人工核查');if(data.decision==='received')statements.push(stmt(env.DB,"UPDATE qf_submissions SET status='success',confirmation='researcher_review',success_at=?,updated_at=?,last_error=NULL WHERE participant_id=? AND status='uncertain' AND in_flight_token IS NULL",now(),now(),pid));else{assert(data.decision==='not_received'&&cfg.enabled&&row.target_url===cfg.target,'未启用原任务，不能重新发送');statements.push(stmt(env.DB,"UPDATE qf_submissions SET status='pending',cycle_attempts=0,next_attempt_at=?,updated_at=? WHERE participant_id=? AND status='uncertain' AND in_flight_token IS NULL",now(),now(),pid))}}
  }
  statements.push(stmt(env.DB,'INSERT INTO qf_actions(participant_id,action,note,created_at,actor) VALUES (?,?,?,?,?)',pid,data.action+(data.decision?':'+data.decision:''),note,now(),actor.slice(0,12)));await env.DB.batch(statements);
}
