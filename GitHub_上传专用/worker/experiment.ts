import { active, details, formalApproved, offers, snapshot, stimuli, study, validateSurvey } from './data';
import { all, instance, one, stmt } from './db';
import { participant } from './auth';
import { assert, cookieHeader, digest, json, modeOf, now, randomInt, seconds, shuffle } from './security';
import { dispatch, enqueueStatement } from './sync';
import type { Env, Row } from './types';
export function requireFormal(request:Request,env:Env){if(modeOf(env)!=='formal')return;assert(env.DCE_ALLOW_FORMAL==='YES'&&formalApproved()&&study.ready_for_formal,'正式收集尚未完成配置',503);assert(env.ADMIN_USERNAME&&env.ADMIN_PASSWORD&&env.ADMIN_PASSWORD.length>=12,'正式模式需要后台Secrets',503);assert(new URL(request.url).protocol==='https:','正式访问须使用HTTPS',503)}
export async function state(env:Env,p:Row|null){
  const basic:Row={mode:modeOf(env),images_ready:true,total:8,study,invite_required:modeOf(env)==='formal'||env.DCE_REQUIRE_INVITE==='1',info_descriptions:details.DESCRIPTIONS,detail_content_version:details.VERSION,debrief:details.DEBRIEF,product_volume_ml:1000,volume_label:'1 L',design_version:active.config.version};
  if(!p)return {...basic,phase:'consent'};
  if(p.design_version!==active.config.version)return {...basic,phase:'archived',participant_id:p.id,historical_design_version:p.design_version};
  const count=await one(env.DB,'SELECT COUNT(*) n FROM choices WHERE participant_id=?',p.id),n=count!.n;
  const current={...basic,participant_id:p.id,answered:n};
  if(p.completed_at)return {...current,phase:'done'};
  if(!p.stimulus_end_at)return {...current,phase:'stimulus',image:'/static/stimuli/'+([1,3].includes(p.group_code)?'chart':'nature')+'.jpg',ai_disclosed:[3,4].includes(p.group_code)};
  if(!p.attributes_seen_at)return {...current,phase:'attributes'};
  if(n>=8)return {...current,phase:'survey'};
  const tid=JSON.parse(p.task_order)[n],o=offers(p,tid),stamp=now();
  await env.DB.batch([stmt(env.DB,'INSERT OR IGNORE INTO task_views(participant_id,task_id,started_at,a_json,b_json,content_version) VALUES (?,?,?,?,?,?)',p.id,tid,stamp,JSON.stringify(snapshot(o.a)),JSON.stringify(snapshot(o.b)),details.VERSION),stmt(env.DB,'UPDATE participants SET dce_started_at=COALESCE(dce_started_at,?) WHERE id=?',stamp,p.id)]);
  return {...current,phase:'choice',position:n+1,task_id:tid,a:o.a,b:o.b};
}
export async function createParticipant(request:Request,env:Env,group?:number,block?:string,invitation?:unknown){
  const mode=modeOf(env),id=crypto.randomUUID(),raw=crypto.randomUUID()+crypto.randomUUID(),stamp=now(),source=await instance(env.DB),needsInvite=mode==='formal'||env.DCE_REQUIRE_INVITE==='1';
  let inviteHash:string|null=null;
  if(needsInvite){assert(typeof invitation==='string'&&invitation.length>=8&&invitation.length<=128,'请输入有效的一次性邀请码');inviteHash=await digest(invitation.trim())}
  const a=JSON.stringify(shuffle(active.byBlock.A.map(t=>t.id))),b=JSON.stringify(shuffle(active.byBlock.B.map(t=>t.id))),swaps=Array.from({length:8},()=>String(randomInt(2))).join('');
  const statements=[stmt(env.DB,`WITH cells(group_code,block) AS (VALUES(1,'A'),(1,'B'),(2,'A'),(2,'B'),(3,'A'),(3,'B'),(4,'A'),(4,'B'))
    INSERT INTO participants(id,token_digest,mode,group_code,block,swap_bits,task_order,created_at,design_version,task_hash,source_instance,source_participant_id,stimulus_versions,stimulus_started_at,provenance,consent_version)
    SELECT ?,?,?,cells.group_code,cells.block,?,CASE cells.block WHEN 'A' THEN ? ELSE ? END,?,?,?,?,?,?,?,?,?
    FROM cells LEFT JOIN participants p ON p.group_code=cells.group_code AND p.block=cells.block AND p.mode=? AND p.design_version=? AND p.source_instance=? AND p.provenance IN ('live','legacy')
    WHERE (? IS NULL OR cells.group_code=?) AND (? IS NULL OR cells.block=?) ${needsInvite?"AND EXISTS(SELECT 1 FROM invitations WHERE digest=? AND mode=? AND used_by IS NULL)":''}
    GROUP BY cells.group_code,cells.block ORDER BY COUNT(p.id),random() LIMIT 1`,id,await digest(raw),mode,swaps,a,b,stamp,active.config.version,active.config.task_sha256,source,id,JSON.stringify(stimuli),stamp,group?'demo-researcher':'live',study.consent_version,mode,active.config.version,source,group??null,group??null,block??null,block??null,...(needsInvite?[inviteHash,mode]:[]))];
  if(needsInvite)statements.push(stmt(env.DB,'UPDATE invitations SET used_by=? WHERE digest=? AND mode=? AND used_by IS NULL AND EXISTS(SELECT 1 FROM participants WHERE id=?)',id,inviteHash,mode,id));
  await env.DB.batch(statements);const p=await one(env.DB,'SELECT * FROM participants WHERE id=?',id);assert(p,'邀请码无效或已使用，请用原浏览器恢复或联系研究者');
  return json(await state(env,p),200,cookieHeader(request,'dce_session',raw,2592000));
}
export async function experiment(request:Request,env:Env,ctx:ExecutionContext,path:string,data:Row){
  const mode=modeOf(env),p=await participant(request,env);
  if(path==='/api/start'){if(p)return json(await state(env,p));assert(data.consent===true&&data.adult===true&&data.recent_shopping===true,'需同意研究、年满18周岁且最近3个月有线上食品购物经历');assert(!Object.hasOwn(data,'group')&&!Object.hasOwn(data,'block'),'参与者不能指定实验条件');return createParticipant(request,env,undefined,undefined,data.invitation)}
  if(path==='/api/demo/restart'){assert(mode==='demo','仅demo可重新体验',403);return json(await state(env,null),200,cookieHeader(request,'dce_session','',0))}
  assert(p,'请先完成知情同意',401);assert(p.design_version===active.config.version,'历史设计记录保持封存');
  if(path==='/api/viewed'){await env.DB.batch([stmt(env.DB,'UPDATE participants SET stimulus_end_at=COALESCE(stimulus_end_at,?) WHERE id=?',now(),p.id)]);return json(await state(env,await one(env.DB,'SELECT * FROM participants WHERE id=?',p.id)))}
  if(path==='/api/attributes'){assert(p.stimulus_end_at,'请先浏览广告');await env.DB.batch([stmt(env.DB,'UPDATE participants SET attributes_seen_at=COALESCE(attributes_seen_at,?) WHERE id=?',now(),p.id)]);return json(await state(env,await one(env.DB,'SELECT * FROM participants WHERE id=?',p.id)))}
  if(path==='/api/answer'){
    assert(['A','B','N'].includes(data.choice)&&typeof data.task_id==='string','请选择A、B或暂时不购买');
    const prior=await one(env.DB,'SELECT * FROM choices WHERE participant_id=? AND task_id=?',p.id,data.task_id);
    if(prior){assert(prior.displayed_choice===data.choice,'本题已提交其他选择，不能覆盖',409);return json(await state(env,p))}
    assert(p.attributes_seen_at&&!p.completed_at,'实验阶段不正确');
    await env.DB.batch([stmt(env.DB,'INSERT OR IGNORE INTO choices(participant_id,task_id,displayed_choice,answered_at) VALUES (?,?,?,?)',p.id,data.task_id,data.choice,now())]);
    const saved=await one(env.DB,'SELECT * FROM choices WHERE participant_id=? AND task_id=?',p.id,data.task_id);assert(saved?.displayed_choice===data.choice,'本题已提交其他选择，不能覆盖',409);
    return json(await state(env,await one(env.DB,'SELECT * FROM participants WHERE id=?',p.id)));
  }
  if(path==='/api/finish'){
    if(p.completed_at)return json(await state(env,p));
    const extra=validateSurvey(data),n=await one(env.DB,'SELECT COUNT(*) n FROM choices WHERE participant_id=?',p.id);assert(n!.n===8,'请先完成全部8道题');
    const completed=now(),completedP:Row={...p,...data,age:Number(data.age),completed_at:completed,additional_answers:JSON.stringify(extra)},fields=['age','gender','education','online_purchase','plant_based_purchase','manip_visual','manip_ai'];
    const updates=[stmt(env.DB,`UPDATE participants SET completed_at=?,${fields.map(k=>k+'=?').join(',')},additional_answers=? WHERE id=? AND completed_at IS NULL AND (SELECT COUNT(*) FROM choices WHERE participant_id=?)=8`,completed,...fields.map(k=>completedP[k]),completedP.additional_answers,p.id,p.id)];
    const queue=await enqueueStatement(env.DB,env,completedP,completed);if(queue)updates.push(queue);
    await env.DB.batch(updates);
    if(queue)ctx.waitUntil(dispatch(env,p.id,true).catch(()=>console.error('答卷已保存，同步任务留待核查')));
    return json(await state(env,await one(env.DB,'SELECT * FROM participants WHERE id=?',p.id)));
  }
  if(path==='/api/details/open'){
    const {task_id:tid,alternative:alt,kind,event_id:eid}=data;
    assert(typeof eid==='string'&&/^[a-f0-9-]{32,36}$/.test(eid),'查看事件编号格式错误');assert(['A','B'].includes(alt)&&['environment','quality'].includes(kind),'商品或资料类型错误');
    const n=await one(env.DB,'SELECT COUNT(*) n FROM choices WHERE participant_id=?',p.id);assert(p.attributes_seen_at&&!p.completed_at&&n!.n<8&&JSON.parse(p.task_order)[n!.n]===tid,'只能查看当前未提交商品');
    assert(await one(env.DB,'SELECT 1 x FROM task_views WHERE participant_id=? AND task_id=?',p.id,tid),'本题尚未展示');
    const o=offers(p,tid),product=alt==='A'?o.a:o.b,level=kind==='environment'?product.verification:product.quality,stamp=now();
    await env.DB.batch([stmt(env.DB,`INSERT OR IGNORE INTO detail_views(event_id,participant_id,task_id,alternative,kind,level,content_version,opened_at,updated_at) SELECT ?,?,?,?,?,?,?,?,? WHERE (SELECT COUNT(*) FROM detail_views WHERE participant_id=? AND task_id=?)<200`,eid,p.id,tid,alt,kind,level,details.VERSION,stamp,stamp,p.id,tid)]);
    const event=await one(env.DB,'SELECT * FROM detail_views WHERE event_id=?',eid);assert(event&&event.participant_id===p.id&&event.task_id===tid&&event.alternative===alt&&event.kind===kind,'查看编号冲突或打开次数过多');
    return json({event_id:eid,task_id:tid,alternative:alt,content_version:details.VERSION,kind,title:kind==='environment'?'环境信息':'食品质量资料',notice:details.NOTICE,base:details.BASE[kind as 'environment'|'quality'],extra:level?details.EXTRA[kind as 'environment'|'quality']:null});
  }
  if(path==='/api/details/progress'){
    assert(typeof data.event_id==='string'&&Number.isInteger(data.duration_ms)&&data.duration_ms>=0&&data.duration_ms<=86400000&&typeof data.closed==='boolean'&&data.shown===true,'查看进度格式错误');
    const reason=data.reason||'heartbeat';assert(['heartbeat','close','hidden','pagehide','switch','resume'].includes(reason),'查看状态来源错误');
    const event=await one(env.DB,'SELECT * FROM detail_views WHERE event_id=? AND participant_id=?',data.event_id,p.id);assert(event,'查看事件不存在');
    const answer=await one(env.DB,'SELECT answered_at FROM choices WHERE participant_id=? AND task_id=?',p.id,event.task_id),stamp=now();
    const end=[event.closed_at,answer?.answered_at,stamp].filter(Boolean).sort((a,b)=>Date.parse(a)-Date.parse(b))[0],ceiling=Math.max(0,Date.parse(end)-Date.parse(event.opened_at));
    await env.DB.batch([stmt(env.DB,`UPDATE detail_views SET duration_ms=MAX(duration_ms,?),shown_at=COALESCE(shown_at,?),updated_at=?,closed_at=COALESCE(closed_at,?),close_reason=CASE WHEN closed_at IS NULL THEN ? ELSE close_reason END WHERE event_id=? AND participant_id=?`,Math.min(data.duration_ms,ceiling),stamp,stamp,data.closed?stamp:null,data.closed?reason:'',data.event_id,p.id)]);
    return json({ok:true,duration_ms:(await one(env.DB,'SELECT duration_ms FROM detail_views WHERE event_id=?',data.event_id))!.duration_ms});
  }
  return json({error:'Not found'},404);
}
