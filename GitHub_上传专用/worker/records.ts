import { zipSync, strToU8 } from 'fflate';
import { active, columns, designOf, details, offers, PROCESS, stimuli, SURVEY, VISUAL } from './data';
import { all, instance, one, stmt } from './db';
import { assert, digest, now, seconds, uuid5 } from './security';
import type { Dataset, Row } from './types';
export const blankProcess = () => Object.fromEntries(PROCESS.map(k=>[k,null]));
export function metrics(p:Row,tid:string,alt:string,events:Row[],answer?:Row) {
  if (answer?.process_json) return JSON.parse(answer.process_json)[alt];
  if (p.provenance.startsWith('import:')) return blankProcess();
  const result:Row=Object.fromEntries(PROCESS.map(k=>[k,0]));
  for (const event of events) if(event.task_id===tid&&event.alternative===alt&&event.shown_at){const i=event.kind==='environment'?0:1;result[PROCESS[i]]=1;result[PROCESS[i+2]]+=event.duration_ms/1000}
  for(const k of PROCESS.slice(2))result[k]=Math.round(result[k]*1000)/1000;
  return result;
}
export function combined(a:Row,b:Row) {return Object.fromEntries(PROCESS.map((k,i)=>[k,a[k]===null||b[k]===null?null:i<2?Math.max(a[k],b[k]):Math.round((a[k]+b[k])*1000)/1000]))}
export async function participantUuid(p:Row) { return uuid5(JSON.stringify([p.source_instance,p.source_participant_id,p.mode])) }
export async function dataset(db:D1Database,mode:string,version:string):Promise<Dataset> {
  const d=designOf(version); assert(['demo','pilot','formal'].includes(mode),'数据模式错误');
  const results=await db.batch([
    stmt(db,'SELECT * FROM participants WHERE mode=? AND design_version=? ORDER BY created_at,id',mode,version),
    stmt(db,'SELECT c.* FROM choices c JOIN participants p ON p.id=c.participant_id WHERE p.mode=? AND p.design_version=?',mode,version),
    stmt(db,'SELECT v.* FROM task_views v JOIN participants p ON p.id=v.participant_id WHERE p.mode=? AND p.design_version=?',mode,version),
    stmt(db,'SELECT v.* FROM detail_views v JOIN participants p ON p.id=v.participant_id WHERE p.mode=? AND p.design_version=? ORDER BY v.participant_id,v.opened_at,v.event_id',mode,version)
  ]);
  const [parts,choices,views,events]=results.map(r=>r.results as Row[]);
  const ps:Row[]=[],cs:Row[]=[],longs:Row[]=[],eventRows:Row[]=[];
  const index=(rows:Row[])=>{const m=new Map<string,Row[]>();for(const r of rows){const a=m.get(r.participant_id)||[];a.push(r);m.set(r.participant_id,a)}return m};
  const ci=index(choices),vi=index(views),ei=index(events);
  for(const p of parts){
    const own=ci.get(p.id)||[],pv=vi.get(p.id)||[],pe=ei.get(p.id)||[],answers=new Map(own.map(a=>[a.task_id,a]));
    const shared={participant_id:p.id,participant_uuid:await participantUuid(p),mode:p.mode,design_version:p.design_version,task_hash:p.task_hash,source_instance:p.source_instance,source_participant_id:p.source_participant_id,group_code:`G${p.group_code}`,visual:Number([1,3].includes(p.group_code)),ai_disclosure:Number([3,4].includes(p.group_code)),block:p.block};
    const part:Row={...shared,product_volume_ml:d.config.product_volume_ml,started_at:p.created_at,n_choices:own.length,completion_status:p.completed_at?'completed':'incomplete',total_seconds:seconds(p.created_at,p.completed_at),dce_seconds:seconds(p.dce_started_at,p.dce_completed_at),additional_answers_json:p.additional_answers};
    for(const k of ['task_order','swap_bits','stimulus_started_at','stimulus_end_at','attributes_seen_at','dce_started_at','dce_completed_at','completed_at','age',...Object.keys(SURVEY),'validation_status','provenance','stimulus_versions','consent_version'])part[k]=p[k];
    ps.push(part);
    for(const tid of JSON.parse(p.task_order)){
      const answer=answers.get(tid);if(!answer)continue;
      const os=offers(p,tid),view=pv.find(v=>v.task_id===tid),process={A:metrics(p,tid,'A',pe,answer),B:metrics(p,tid,'B',pe,answer)};
      if(view?.a_json&&view?.b_json){for(const [label,o] of [['a',os.a],['b',os.b]] as const){const saved=JSON.parse(view[label+'_json']).codes;assert(saved.price===o.price&&saved.origin===o.origin&&saved.environmental_verification===o.verification&&saved.quality_information===o.quality,'显示快照与任务配置冲突',409)}}
      const row:Row={...shared,product_volume_ml:d.config.product_volume_ml,task_id:tid,position:os.position,swapped:os.swapped,displayed_choice:answer.displayed_choice,started_at:view?.started_at??null,answered_at:answer.answered_at,...combined(process.A,process.B)};
      for(const alt of ['A','B'] as const)for(const k of PROCESS)row[alt.toLowerCase()+'_'+k]=process[alt][k];
      for(const label of ['a','b','original_a','original_b'] as const)for(const [k,v]of Object.entries(os[label]))row[label+'_'+k]=v;
      cs.push(row);
      for(const alt of ['A','B','N']){
        const o=alt==='A'?os.a:alt==='B'?os.b:null;
        longs.push({...shared,choice_set_id:`${p.id}_${tid}`,task_id:tid,position:os.position,swapped:os.swapped,alternative:alt,alternative_id:alt,choice:Number(answer.displayed_choice===alt),chosen:Number(answer.displayed_choice===alt),origin_import:o?.origin??null,origin:o?.origin??null,third_party_verification:o?.verification??null,environmental_verification:o?.verification??null,batch_quality_report:o?.quality??null,quality_information:o?.quality??null,price_yuan:o?.price??null,price:o?.price??null,price_level:o?.price_level??null,product_volume_ml:o?.product_volume_ml??null,opt_out:Number(alt==='N'),started_at:view?.started_at??null,answered_at:answer.answered_at,visual_type:VISUAL(p.group_code),dce_block:p.block,...(alt==='N'?blankProcess():process[alt as 'A'|'B'])});
      }
    }
    for(const e of pe)eventRows.push({...e,mode:p.mode,design_version:p.design_version,source_instance:p.source_instance,source_participant_id:p.source_participant_id});
  }
  return {participants:ps,choices:cs,choice_long:longs,detail_views:eventRows};
}
export function csv(headers:string[],rows:Row[]) {
  const cell=(value:any)=>{if(value===null||value===undefined)return '';let s=typeof value==='object'?JSON.stringify(value):String(value);if(typeof value==='string'&&/^[=+\-@]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"'};
  return strToU8('\ufeff'+headers.map(cell).join(',')+'\r\n'+rows.map(r=>headers.map(k=>cell(r[k])).join(',')).join('\r\n')+'\r\n');
}
export async function exportFiles(db:D1Database,mode:string,version:string) {
  const data=await dataset(db,mode,version),d=designOf(version);
  const manifest={exported_at_utc:now(),mode,design_version:version,task_design_sha256:d.config.task_sha256,product_volume_ml:d.config.product_volume_ml,stimulus_sha256_current:stimuli,stimulus_versions_observed:[...new Set(data.participants.map(p=>p.stimulus_versions||'unknown_legacy'))].sort(),source_instance:await instance(db),schema_version:'workers-d1-v1',participants:data.participants.length,choices:data.choices.length,choice_alternatives:data.choice_long.length,detail_views:data.detail_views.length,detail_content_version:d.config.detail_content_version,detail_content_sha256:await digest(JSON.stringify(details)),opt_out_encoding:'N: opt_out=1; product attributes, price and volume are blank; never a zero-price drink',validity:'Only explicit researcher review marks valid',process_variables:'Observational process variables, not causal effects; untracked historical values stay blank'};
  const events=['event_id','participant_id','mode','design_version','source_instance','source_participant_id','task_id','alternative','kind','level','content_version','opened_at','shown_at','updated_at','closed_at','duration_ms','close_reason'];
  return {'participants.csv':csv([...columns.participants,'additional_answers_json'],data.participants),'choices.csv':csv(columns.choices,data.choices),'choice_long.csv':csv(columns.choice_long,data.choice_long),'detail_views.csv':csv(events,data.detail_views),'manifest.json':strToU8(JSON.stringify(manifest,null,2))};
}
export async function exportZip(db:D1Database,mode:string,version:string) {return zipSync(await exportFiles(db,mode,version),{level:6})}
export async function statistics(db:D1Database,mode:string,version:string) {
  const data=await dataset(db,mode,version),d=designOf(version),ps=data.participants;
  const tally=(p:Row[])=>{const completed=p.filter(x=>x.completed_at).length;return {started:p.length,completed,incomplete:p.length-completed,valid:p.filter(x=>x.validation_status==='valid').length,completion_rate:p.length?completed/p.length:0}};
  const gs=Object.fromEntries([1,2,3,4].map(g=>['G'+g,tally(ps.filter(p=>p.group_code==='G'+g))]));
  return {totals:tally(ps),groups:gs,blocks:Object.fromEntries(['A','B'].map(b=>[b,ps.filter(p=>p.block===b).length])),group_blocks:Object.fromEntries([1,2,3,4].map(g=>['G'+g,Object.fromEntries(['A','B'].map(b=>[b,ps.filter(p=>p.group_code==='G'+g&&p.block===b).length]))])),tasks:Object.fromEntries(d.tasks.map(t=>[t.id,Object.fromEntries(['A','B','N'].map(a=>[a,data.choices.filter(c=>c.task_id===t.id&&c.displayed_choice===a).length]))])),participants:ps,mode,design_version:version,note:'已开始=同意并建立会话；已完成=8题及后续问卷提交；有效=研究者人工审核。模式与设计版本分别统计。'};
}
