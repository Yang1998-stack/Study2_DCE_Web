import { zipSync, strToU8 } from 'fflate';
import { admin, configured, login, participant, session } from './auth';
import { active, designOf } from './data';
import { all, bulk, initialize, one, run, stmt } from './db';
import { createParticipant, experiment, requireFormal, state } from './experiment';
import { archiveFiles, archiveStatements } from './files';
import { commit, preview } from './imports';
import { csv, exportFiles, exportZip, statistics } from './records';
import { assert, binary, body, cookieHeader, digest, headers, HttpError, json, modeOf, now, token, verifyOrigin } from './security';
import { dispatch, recover, syncAction, syncConfig, syncStatus } from './sync';
import type { Env, Row } from './types';

const assets:Record<string,string>={'/':'/index.html','/admin':'/admin.html','/static/app.js':'/app.js','/static/admin.js':'/admin.js','/static/quickform-admin.js':'/quickform-admin.js','/static/details.js':'/details.js','/static/styles.css':'/styles.css','/static/details.css':'/details.css','/static/stimuli/chart.jpg':'/stimuli/chart.jpg','/static/stimuli/nature.jpg':'/stimuli/nature.jpg'};
function scope(url:URL,env:Env){const mode=url.searchParams.get('mode')||modeOf(env),version=url.searchParams.get('design_version')||active.config.version;assert(['demo','pilot','formal'].includes(mode),'数据模式不合法');designOf(version);return {mode,version}}
async function backup(env:Env,mode:string,version:string,reason:string,id=token().slice(0,32)){
  const previous=await one(env.DB,'SELECT * FROM backups WHERE id=?',id);if(previous)return {backup:id+'.zip',download:'/api/admin/backup/download?id='+id};
  const raw=await exportZip(env.DB,mode,version);assert(raw.length<=24*1024*1024,'备份较大，请分别按模式及版本导出并使用D1 Time Travel');
  const writes=archiveStatements(env.DB,'backup_'+id,'data.zip',raw);assert(writes.length<=30,'备份较大，请使用D1导出或分批导出');
  writes.push(stmt(env.DB,'INSERT INTO backups(id,created_at,mode,design_version,sha256,bytes,reason) VALUES (?,?,?,?,?,?,?)',id,now(),mode,version,await digest(raw),raw.length,reason));await env.DB.batch(writes);
  return {backup:id+'.zip',download:'/api/admin/backup/download?id='+id};
}
async function adminGet(request:Request,env:Env,url:URL){
  const path=url.pathname,a=await admin(request,env);
  if(path==='/api/admin/session')return json(session(env,a));assert(a,'请先登录研究者后台',401);
  const {mode,version}=scope(url,env);
  if(path==='/api/admin/stats')return json(await statistics(env.DB,mode,version));
  if(path==='/api/admin/export')return binary(await exportZip(env.DB,mode,version),'application/zip',`study2_${mode}_${version}.zip`);
  if(path==='/api/admin/export/csv'){
    const name=url.searchParams.get('file')||'participants.csv',files=await exportFiles(env.DB,mode,version);assert(Object.hasOwn(files,name)&&name.endsWith('.csv'),'导出文件不合法');return binary(files[name as keyof typeof files],'text/csv; charset=utf-8',name);
  }
  if(path==='/api/admin/imports')return json({batches:await all(env.DB,'SELECT id,created_at,mode,design_version,status,committed_at,report FROM import_batches ORDER BY created_at DESC LIMIT 100')});
  if(path==='/api/admin/import/archive'){
    const id=url.searchParams.get('batch_id')||'';assert(/^[a-f0-9]{32}$/.test(id),'导入编号不合法');const batch=await one(env.DB,'SELECT * FROM import_batches WHERE id=?',id);assert(batch,'导入不存在');const files=await archiveFiles(env.DB,'import_'+id);files['import-log.json']=strToU8(JSON.stringify(batch,null,2));return binary(zipSync(files,{level:6}),'application/zip','import_'+id+'.zip');
  }
  if(path==='/api/admin/backup/download'){
    const id=url.searchParams.get('id')||'';assert(/^[a-f0-9]{32}$/.test(id),'备份编号不合法');const record=await one(env.DB,'SELECT * FROM backups WHERE id=?',id);assert(record,'备份不存在');const files=await archiveFiles(env.DB,'backup_'+id);assert(files['data.zip']&&await digest(files['data.zip'])===record.sha256,'备份校验失败');return binary(files['data.zip'],'application/zip','backup_'+id+'.zip');
  }
  if(path==='/api/admin/quickform')return json(await syncStatus(env,mode,version));
  if(path==='/api/admin/quickform/record'){
    const pid=url.searchParams.get('participant_id')||'',record=await one(env.DB,'SELECT * FROM qf_submissions WHERE participant_id=?',pid);assert(record,'该参与者没有同步任务');return json({record,attempts:await all(env.DB,'SELECT * FROM qf_attempts WHERE participant_id=? ORDER BY attempt_number',pid),actions:await all(env.DB,'SELECT * FROM qf_actions WHERE participant_id=? ORDER BY id',pid)});
  }
  if(path==='/api/admin/quickform/logs'){
    const rows=await all(env.DB,'SELECT a.* FROM qf_attempts a JOIN qf_submissions s ON s.participant_id=a.participant_id WHERE s.survey_mode=? AND s.design_version=? ORDER BY a.id',mode,version);
    return binary(csv(['id','participant_id','attempt_number','started_at','finished_at','http_status','outcome','error_summary','response_summary','payload_sha256'],rows),'text/csv; charset=utf-8',`quickform_logs_${mode}.csv`);
  }
  return json({error:'Not found'},404);
}
async function adminPost(request:Request,env:Env,ctx:ExecutionContext,path:string,data:Row){
  if(path==='/api/admin/login')return login(request,env,data);
  const a=await admin(request,env,true);assert(a,'研究者登录或CSRF校验失败，请重新登录',403);
  if(path==='/api/admin/logout'){await run(env.DB,'DELETE FROM admin_sessions WHERE digest=?',a.digest);return json({ok:true},200,cookieHeader(request,'dce_admin','',0))}
  if(path==='/api/admin/demo'){assert(modeOf(env)==='demo','仅demo可指定条件',403);assert([1,2,3,4].includes(data.group)&&['A','B'].includes(data.block),'组别或区组错误');return createParticipant(request,env,data.group,data.block)}
  if(path==='/api/admin/import/preview')return json(await preview(env.DB,data,a.digest));
  if(path==='/api/admin/import/commit'){assert(data.confirm===true,'请核对预览并明确确认导入');return json(await commit(env.DB,data.batch_id,a.digest))}
  if(path==='/api/admin/review'){
    assert(typeof data.participant_id==='string'&&['unreviewed','valid','excluded'].includes(data.status)&&typeof(data.note??'')==='string'&&(data.note||'').length<=500,'审核字段不合法');const p=await one(env.DB,'SELECT * FROM participants WHERE id=?',data.participant_id);assert(p,'参与者不存在');
    if(data.status==='valid'){const count=await one(env.DB,'SELECT COUNT(*) n FROM choices WHERE participant_id=?',p.id);assert(p.completed_at&&count!.n===8,'完成8题和后续问卷后才可标记有效')}
    await env.DB.batch([stmt(env.DB,'UPDATE participants SET validation_status=? WHERE id=?',data.status,p.id),stmt(env.DB,'INSERT INTO review_log(participant_id,status,note,reviewed_at) VALUES (?,?,?,?)',p.id,data.status,data.note||'',now())]);return json({ok:true});
  }
  if(path==='/api/admin/backup'){const mode=data.mode||modeOf(env),version=data.design_version||active.config.version;assert(['demo','pilot','formal'].includes(mode),'模式错误');designOf(version);return json(await backup(env,mode,version,'manual'))}
  if(path==='/api/admin/invitations'){
    const mode=data.mode||modeOf(env),count=data.count??100;assert(['pilot','formal'].includes(mode)&&Number.isInteger(count)&&count>=1&&count<=1000,'邀请码模式或数量不合法（1至1000）');
    const codes=Array.from({length:count},()=>token().slice(0,32)),stamp=now(),rows=await Promise.all(codes.map(async c=>({digest:await digest(c),mode,created_at:stamp,used_by:null})));
    await env.DB.batch(bulk(env.DB,'invitations',['digest','mode','created_at','used_by'],rows));return json({mode,codes,note:'请下载并私下发放，数据库仅保留哈希，刷新后不能取回明文邀请码。'});
  }
  if(path==='/api/admin/quickform/action'){await syncAction(env,data,a.digest);ctx.waitUntil(dispatch(env,data.participant_id).catch(()=>console.error('同步任务保留，需核查')));return json({ok:true})}
  return json({error:'Not found'},404);
}
export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    try{
      const url=new URL(request.url),path=url.pathname;
      if(Object.hasOwn(assets,path)&&['GET','HEAD'].includes(request.method)){
        const target=new URL(assets[path],url.origin),response=await env.ASSETS.fetch(new Request(target,request)),h=headers(response.headers.get('Content-Type')||'text/plain',request);
        return new Response(response.body,{status:response.status,headers:h});
      }
      if(!path.startsWith('/api/')&&path!=='/health')return json({error:'Not found'},404);
      await initialize(env);
      if(path==='/health')return json({ok:true,platform:'cloudflare-workers',database:'D1',mode:modeOf(env),design_version:active.config.version,formal_quickform_enabled:false});
      if(request.method==='GET'){
        if(path.startsWith('/api/admin/'))return await adminGet(request,env,url);
        if(path==='/api/state'){requireFormal(request,env);return json(await state(env,await participant(request,env)))}
        return json({error:'Not found'},404);
      }
      assert(request.method==='POST','Method not allowed',405);verifyOrigin(request);
      const data=await body(request,path==='/api/admin/import/preview'?12*1024*1024:65536);
      if(path.startsWith('/api/admin/'))return await adminPost(request,env,ctx,path,data);
      requireFormal(request,env);return await experiment(request,env,ctx,path,data);
    }catch(e){
      if(e instanceof HttpError)return json({error:e.message},e.status);
      const message=(e as Error).message||'';
      if(/constraint|RAISE|题目|阶段|不可覆盖/i.test(message))return json({error:'记录已存在或题目阶段发生变化，请刷新恢复进度；原始选择不会覆盖'},409);
      if(/CSV|XLSX|UTF-8|Invalid character|Invalid URL|JSON/.test(message))return json({error:'文件、地址或JSON格式不正确，请检查后重试'},400);
      console.error('Worker请求失败：',e instanceof Error?e.name:'unknown');
      return json({error:'服务暂时不可用，已提交数据仍保留；请稍后重试或联系研究者'},503);
    }
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext){
    ctx.waitUntil((async()=>{
      await initialize(env);await recover(env);for(let i=0;i<2;i++)if(!await dispatch(env))break;
      await env.DB.batch([stmt(env.DB,'DELETE FROM admin_sessions WHERE expires<=?',now()),stmt(env.DB,'DELETE FROM auth_failures WHERE window_at<?',new Date(Date.now()-86400000).toISOString())]);
      const date=new Date(controller.scheduledTime),minute=date.getUTCMinutes();
      if(date.getUTCHours()%6===0&&minute<6){const versions=[active.config.version,...Object.keys((await import('./data')).designs).filter(v=>v!==active.config.version)],mode=['demo','pilot','formal'][minute%3],version=versions[Math.floor(minute/3)];
        const id=(await digest(JSON.stringify([date.toISOString().slice(0,13),mode,version]))).slice(0,32);await backup(env,mode,version,'six_hour_snapshot',id);
      }
    })().catch(()=>console.error('定时同步或备份未完成；请在后台核查。答卷不会删除')));
  }
};
