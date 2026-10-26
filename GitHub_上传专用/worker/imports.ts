import { active, designOf, details, offers, PROCESS, SURVEY } from './data';
import { all, bulk, one, stmt } from './db';
import { archiveFiles, archiveStatements, readTable, unbase64 } from './files';
import { blankProcess, combined, dataset } from './records';
import { assert, digest, now, seconds, timestamp, token, uuid5 } from './security';
import type { Row } from './types';
const fields=['participants','choices','choice_long','detail_views'];
const identity=(p:Row)=>JSON.stringify([p.source_instance,p.source_participant_id,p.mode]);
const ordered=(x:any):any=>Array.isArray(x)?x.map(ordered):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,ordered(x[k])])):x;
const same=(a:any,b:any)=>JSON.stringify(ordered(a))===JSON.stringify(ordered(b));
function process(row:Row,prefix=''){
  const values=PROCESS.map(k=>row[prefix+k]??'');if(values.every(v=>v===''))return blankProcess();assert(values.every(v=>v!==''),'查看过程四项须同时提供或同时留空');
  assert(['0','1'].includes(values[0])&&['0','1'].includes(values[1]),'是否查看须为0/1');
  const result:Row=Object.fromEntries(PROCESS.map((k,i)=>[k,Number(values[i])]));
  for(let i=2;i<4;i++)assert(Number.isFinite(result[PROCESS[i]])&&result[PROCESS[i]]>=0&&result[PROCESS[i]]<=86400&&(result[PROCESS[i-2]]!==0||result[PROCESS[i]]===0),'查看时长不合法');
  return result;
}
export async function validate(db:D1Database,tables:Record<string,Row[]>,mode:string,version:string){
  const d=designOf(version);assert(['demo','pilot','formal'].includes(mode),'导入模式错误');assert(tables.participants,'必须上传participants.csv');
  const errors:string[]=[],warnings:string[]=[],parts:Row[]=[],byInput=new Map<string,Row>(),sourceKeys=new Set<string>();
  const existing=await all(db,'SELECT * FROM participants'),previous=await dataset(db,mode,version),previousChoices=new Map(previous.choices.map(c=>[c.participant_id+'\x1f'+c.task_id,c]));
  for(let i=0;i<tables.participants.length;i++){
    const r={...tables.participants[i]};try{
      for(const k of ['participant_id','source_instance','source_participant_id','mode','design_version','task_hash','group_code','block','task_order','swap_bits','started_at','n_choices'])assert(r[k]!==''&&r[k]!==undefined,'缺少'+k+'，不允许补齐身份或分配记录');
      assert(r.mode===mode&&r.design_version===version&&r.task_hash===d.config.task_sha256,'模式、设计版本或哈希不同，禁止合并');
      assert(['G1','G2','G3','G4'].includes(r.group_code)&&d.byBlock[r.block],'组别或区组不合法');
      if(r.product_volume_ml!==undefined)assert(Number(r.product_volume_ml)===d.config.product_volume_ml,'商品规格不匹配');
      for(const k of ['participant_id','source_instance','source_participant_id'])assert(r[k].length<=128&&!/[\x00-\x1f]/.test(r[k])&&!/^[=+\-@]/.test(r[k]),'身份或来源格式不合法');
      for(const [flag,expected]of [['visual',Number(['G1','G3'].includes(r.group_code))],['ai_disclosure',Number(['G3','G4'].includes(r.group_code))]] as const)if(r[flag]!==undefined)assert(r[flag]===String(expected),flag+'与广告组不匹配');
      const order=JSON.parse(r.task_order);assert(Array.isArray(order)&&order.length===8&&new Set(order).size===8&&order.every(t=>d.byBlock[r.block].some(x=>x.id===t)),'题序须恰好含本区组8题');
      assert(/^[01]{8}$/.test(r.swap_bits),'A/B交换位错误');
      const times=['started_at','stimulus_started_at','stimulus_end_at','attributes_seen_at','dce_started_at','dce_completed_at','completed_at'];for(const k of times)timestamp(r[k],k==='started_at');const known=times.map(k=>r[k]).filter(Boolean);for(let k=1;k<known.length;k++)assert(Date.parse(known[k])>=Date.parse(known[k-1]),'阶段时间顺序不合法');
      assert(/^\d+$/.test(r.n_choices)&&Number(r.n_choices)<=8,'已答题数错误');
      if(r.age)assert(/^\d+$/.test(r.age)&&Number(r.age)>=18&&Number(r.age)<=100,'年龄不合法');
      for(const [k,v]of Object.entries(SURVEY))if(r[k])assert(v.includes(r[k]),'问卷编码不合法：'+k);
      if(r.completed_at)assert(Number(r.n_choices)===8&&r.age&&Object.keys(SURVEY).every(k=>r[k]),'完成标记与8题及后续问卷不一致');
      if(r.completion_status)assert(r.completion_status===(r.completed_at?'completed':'incomplete'),'完成状态字段不一致');
      if(r.consent_version)assert(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$/.test(r.consent_version),'知情同意版本不合法');
      if(r.stimulus_versions){const h=JSON.parse(r.stimulus_versions);assert(h&&Object.keys(h).sort().join(',')==='chart,nature'&&Object.values(h).every(v=>v===null||typeof v==='string'&&/^[a-f0-9]{64}$/.test(v)),'广告版本格式错误')}
      if(r.additional_answers_json)assert(JSON.parse(r.additional_answers_json)&&!Array.isArray(JSON.parse(r.additional_answers_json)),'扩展问卷JSON须为对象');
      const key=identity(r);assert(!sourceKeys.has(key)&&!byInput.has(r.participant_id),'文件内participant_id或来源身份重复');sourceKeys.add(key);
      const old=existing.find(p=>identity(p)===key);r._existing=old??null;r._id=old?.id??'imp_'+(await uuid5([r.source_instance,r.source_participant_id,mode].join('\x1f'))).replaceAll('-','');r._events=[];
      if(old){warnings.push(r.participant_id+'：同来源身份已存在，一致则跳过');assert(old.design_version===version&&old.task_hash===r.task_hash&&old.group_code===Number(r.group_code.slice(1))&&old.block===r.block&&old.swap_bits===r.swap_bits&&same(JSON.parse(old.task_order),order),'重复身份的分配或版本冲突，不覆盖');for(const k of ['completed_at','age',...Object.keys(SURVEY)])assert(String(old[k]??'')===String(r[k]||''),'重复身份问卷冲突：'+k);assert(same(JSON.parse(old.additional_answers||'{}'),JSON.parse(r.additional_answers_json||'{}')),'重复身份扩展问卷冲突')}
      else if(existing.some(p=>p.id===r.participant_id))warnings.push(r.participant_id+'：跨实例编号冲突，将按来源映射为'+r._id);
      parts.push(r);byInput.set(r.participant_id,r);
    }catch(e){errors.push(`participants第${i+2}行：${(e as Error).message}`)}
  }
  let choices=new Map<string,Row>();
  for(const kind of ['choices','choice_long']){
    if(!tables[kind])continue;const seen=new Map<string,any>();
    for(let i=0;i<tables[kind].length;i++){
      const r=tables[kind][i];try{
        const p=byInput.get(r.participant_id);assert(p,'对应参与者不存在或不合法');
        for(const k of ['mode','design_version','task_hash','source_instance','source_participant_id','group_code','block'])assert(r[k]===p[k],'行内分组、身份、来源或版本不一致：'+k);
        for(const k of ['visual','ai_disclosure'])if(r[k]!==undefined)assert(r[k]===p[k],k+'与参与者不一致');
        const tid=r.task_id,o=offers(p,tid);assert(Number(r.position)===o.position&&Number(r.swapped)===o.swapped,'题序或A/B位置不一致');
        timestamp(r.answered_at,true);timestamp(r.started_at);assert(Date.parse(r.answered_at)>=Date.parse(p.started_at)&&(!p.completed_at||Date.parse(r.answered_at)<=Date.parse(p.completed_at))&&(!r.started_at||Date.parse(r.started_at)<=Date.parse(r.answered_at)),'答题时间超出范围');
        const key=p.participant_id+'\x1f'+tid;
        if(kind==='choices'){
          assert(!seen.has(key)&&['A','B','N'].includes(r.displayed_choice),'选择任务重复或结果不合法');
          for(const label of ['a','b','original_a','original_b'] as const)for(const [k,v]of Object.entries(o[label]))if(['origin','verification','quality','price'].includes(k)||Object.hasOwn(r,label+'_'+k))assert(r[label+'_'+k]!==''&&Number(r[label+'_'+k])===v,'显示或原始属性不匹配：'+label+'_'+k);
          const proc={A:process(r,'a_'),B:process(r,'b_')};if(PROCESS.some(k=>(r[k]??'')!==''))assert(same(process(r),combined(proc.A,proc.B)),'题目汇总过程变量与A/B不一致');
          seen.set(key,{participant_id:p.participant_id,task_id:tid,displayed_choice:r.displayed_choice,started_at:r.started_at||null,answered_at:r.answered_at,process:proc});
        }else{
          const alt=r.alternative??r.alternative_id;assert(['A','B','N'].includes(alt)&&['0','1'].includes(r.choice)&&Number(r.opt_out)===Number(alt==='N'),'长格式备选项或选择编码错误');assert(r.choice_set_id===p.participant_id+'_'+tid,'choice_set_id不匹配');
          if(r.chosen!==undefined)assert(r.chosen===r.choice,'chosen与choice不一致');
          const attrs=['origin_import','third_party_verification','batch_quality_report','price_yuan'];
          if(alt==='N'){assert(attrs.every(k=>['','0',undefined].includes(r[k]))&&['price_level','product_volume_ml',...PROCESS].every(k=>(r[k]??'')===''),'不购买项不能作为具有价格或容量的商品')}
          else{const offer=alt==='A'?o.a:o.b;for(const [k,v]of attrs.map((k,j)=>[k,(offer as unknown as Row)[['origin','verification','quality','price'][j]]]))assert(r[k as string]!==''&&Number(r[k as string])===v,'长格式商品属性不匹配');for(const k of ['price_level','product_volume_ml'])if(Object.hasOwn(r,k))assert(Number(r[k])===(offer as unknown as Row)[k],'价格水平或规格不匹配');process(r)}
          const group=seen.get(key)||{};assert(!group[alt],'长格式备选项重复');group[alt]=r;seen.set(key,group);
        }
      }catch(e){errors.push(`${kind}第${i+2}行：${(e as Error).message}`)}
    }
    let normalized=seen as Map<string,Row>;
    if(kind==='choice_long'){
      normalized=new Map();for(const [key,rows]of seen){try{assert(Object.keys(rows).sort().join('')==='ABN'&&Object.values(rows).reduce((sum:number,x:any)=>sum+Number(x.choice),0)===1,'每题须含A/B/N三行且恰好一个choice=1');assert(new Set(Object.values(rows).map((r:any)=>JSON.stringify([r.started_at||null,r.answered_at]))).size===1,'同一题时间不一致');const alt=Object.keys(rows).find(a=>rows[a].choice==='1')!;const [pid,tid]=key.split('\x1f');normalized.set(key,{participant_id:pid,task_id:tid,displayed_choice:alt,started_at:rows[alt].started_at||null,answered_at:rows[alt].answered_at,process:{A:process(rows.A),B:process(rows.B)}})}catch(e){errors.push(key+'：'+(e as Error).message)}}
      if(tables.choices)assert(same([...choices].sort(),[...normalized].sort()),'choices与choice_long数据不一致，拒绝合并');
    }
    choices=normalized;
  }
  for(const p of parts){try{
    const own=[...choices.values()].filter(c=>c.participant_id===p.participant_id),order=JSON.parse(p.task_order),n=Number(p.n_choices);assert(own.length===n&&own.every(c=>order.slice(0,n).includes(c.task_id)),'已答数量或题序前缀不匹配，不能补造缺题');
    if(p._existing){const old=previous.choices.filter(c=>c.participant_id===p._existing.id);assert(old.length===own.length,'重复身份选择题数冲突');for(const c of own){const saved=previousChoices.get(p._existing.id+'\x1f'+c.task_id);assert(saved&&saved.displayed_choice===c.displayed_choice&&saved.answered_at===c.answered_at,'重复身份选择记录冲突');for(const alt of ['A','B'])assert(same(Object.fromEntries(PROCESS.map(k=>[k,saved[alt.toLowerCase()+'_'+k]])),c.process[alt]),'重复身份过程变量冲突')}}
  }catch(e){errors.push(p.participant_id+'：'+(e as Error).message)}}
  const seenEvents=new Set<string>();
  for(let i=0;i<(tables.detail_views||[]).length;i++){const r=tables.detail_views[i];try{
    const p=byInput.get(r.participant_id);assert(p,'过程日志对应参与者不存在');for(const k of ['mode','design_version','source_instance','source_participant_id'])assert(r[k]===p[k],'过程日志来源或版本不一致');
    assert(/^[A-Za-z0-9_-]{1,80}$/.test(r.event_id)&&!seenEvents.has(p.participant_id+'\x1f'+r.event_id),'事件编号重复或不合法');seenEvents.add(p.participant_id+'\x1f'+r.event_id);
    const order=JSON.parse(p.task_order);assert(order.includes(r.task_id)&&order.indexOf(r.task_id)<=Number(p.n_choices),'过程题目尚未到达');assert(['A','B'].includes(r.alternative)&&['environment','quality'].includes(r.kind),'过程商品或资料错误');assert(r.content_version===d.config.detail_content_version,'过程资料版本不一致');
    const o=offers(p,r.task_id),product=r.alternative==='A'?o.a:o.b;assert(Number(r.level)===(r.kind==='environment'?product.verification:product.quality),'过程水平与实际商品不一致');
    for(const k of ['opened_at','shown_at','updated_at','closed_at'])timestamp(r[k],['opened_at','updated_at'].includes(k));const times=['opened_at','shown_at','closed_at','updated_at'].map(k=>r[k]).filter(Boolean);assert(times.every((v,k)=>!k||Date.parse(v)>=Date.parse(times[k-1]))&&Date.parse(r.opened_at)>=Date.parse(p.started_at),'过程时间顺序错误');
    const ms=Number(r.duration_ms),a=choices.get(p.participant_id+'\x1f'+r.task_id),end=r.closed_at||r.updated_at;assert(Number.isInteger(ms)&&ms>=0&&ms<=86400000&&ms<=Date.parse(end)-Date.parse(r.opened_at)&&(!a||ms<=Date.parse(a.answered_at)-Date.parse(r.opened_at))&&(!!r.shown_at||ms===0),'过程时长超出范围');assert(['','close','hidden','pagehide','switch','resume','heartbeat'].includes(r.close_reason||''),'关闭原因不合法');
    p._events.push({...r,duration_ms:ms,level:Number(r.level)});
  }catch(e){errors.push(`detail_views第${i+2}行：${(e as Error).message}`)}}
  if(tables.detail_views)for(const p of parts)for(const c of [...choices.values()].filter(c=>c.participant_id===p.participant_id))for(const alt of ['A','B']){
    const expected:Row=Object.fromEntries(PROCESS.map(k=>[k,0]));for(const e of p._events)if(e.task_id===c.task_id&&e.alternative===alt&&e.shown_at){const i=e.kind==='environment'?0:1;expected[PROCESS[i]]=1;expected[PROCESS[i+2]]+=e.duration_ms/1000}for(const k of PROCESS.slice(2))expected[k]=Math.round(expected[k]*1000)/1000;
    const actual=c.process[alt];if(!Object.values(actual).every(v=>v===null)||Object.values(expected).some(Boolean))if(!same(expected,actual))errors.push(`${p.participant_id}/${c.task_id}/${alt}：逐次详情与汇总过程变量不一致`);
  }
  if(!tables.detail_views&&[...choices.values()].some(c=>Object.values(c.process.A).some(v=>v!==null)))warnings.push('未上传逐次日志，仅保留已有汇总过程变量，不推算查看次数或时间。');
  return {report:{errors:errors.slice(0,100),error_count:errors.length,warnings:warnings.slice(0,100),participants:parts.length,new_participants:parts.filter(p=>!p._existing).length,duplicates:parts.filter(p=>p._existing).length,choices:choices.size,detail_views:parts.reduce((n,p)=>n+p._events.length,0),mode,design_version:version,note:'相同来源身份核对后跳过，不覆盖；其他实例按来源命名空间导入。导入样本统一待审核，不自动同步QuickForm。'},parts,choices};
}
export async function preview(db:D1Database,data:Row,owner:string){
  const {mode,design_version:version}=data;designOf(version);assert(['demo','pilot','formal'].includes(mode),'数据模式错误');assert(Array.isArray(data.files)&&data.files.length>=1&&data.files.length<=4,'请选择1至4份表格文件');
  const id=token().slice(0,32),tables:Record<string,Row[]>={},info:Row[]=[],originals:{name:string,raw:Uint8Array}[]=[];let parseError:Error|null=null,total=0;
  for(const file of data.files){assert(file&&typeof file.name==='string'&&!/[\\/]/.test(file.name),'文件名不允许包含目录');const name=file.name.toLowerCase(),kind=fields.find(k=>name.startsWith(k));assert(kind&&!Object.hasOwn(tables,kind),'文件须以participants、choices、choice_long或detail_views开头，各一份');assert(/\.(csv|xlsx)$/.test(name),'仅允许CSV/XLSX');const raw=unbase64(file.data);total+=raw.length;assert(raw.length<=8*1024*1024&&total<=9*1024*1024,'文件过大，请分批导入');const safe=kind+name.slice(name.lastIndexOf('.'));originals.push({name:safe,raw});
    try{const parsed=readTable(safe,raw);tables[kind]=parsed.rows;info.push({name:safe,original_name:file.name,rows:parsed.rows.length,fields:parsed.fields,sha256:await digest(raw),sample:parsed.rows.slice(0,2)})}catch(e){parseError=e as Error;tables[kind]=[];info.push({name:safe,original_name:file.name,rows:0,fields:[],sample:[],sha256:await digest(raw)})}
  }
  let result:Row;
  try{result=parseError?{errors:[parseError.message],error_count:1,warnings:[],participants:0,new_participants:0,duplicates:0,choices:0,mode,design_version:version,note:'原件已私下留存；错误文件不导入'}:(await validate(db,tables,mode,version)).report}catch(e){result={errors:[(e as Error).message],error_count:1,warnings:[],participants:0,new_participants:0,duplicates:0,choices:0,mode,design_version:version,note:'未导入任何受访者结果'}}
  result.files=info;const writes=originals.flatMap(f=>archiveStatements(db,'import_'+id,f.name,f.raw));assert(writes.length<=30,'原件过大，请拆分后上传');
  writes.push(stmt(db,'INSERT INTO import_batches(id,created_at,mode,design_version,status,owner,report) VALUES (?,?,?,?,?,?,?)',id,now(),mode,version,result.error_count?'rejected':'previewed',owner,JSON.stringify(result)));await db.batch(writes);
  return {batch_id:id,...result};
}
export async function commit(db:D1Database,id:any,owner:string){
  assert(typeof id==='string'&&/^[a-f0-9]{32}$/.test(id),'导入批次编号不合法');const batch=await one(db,"SELECT * FROM import_batches WHERE id=? AND owner=?",id,owner);assert(batch&&batch.status==='previewed'&&seconds(batch.created_at,now())!<=3600,'批次无效、过期或已导入');
  const files=await archiveFiles(db,'import_'+id),tables:Record<string,Row[]>={};for(const [name,raw]of Object.entries(files)){const kind=fields.find(k=>name.startsWith(k))!;tables[kind]=readTable(name,raw).rows}
  const {report,parts,choices}=await validate(db,tables,batch.mode,batch.design_version);assert(report.error_count===0,'数据变化，请重新预览：'+report.errors[0]);
  const ps:Row[]=[],cs:Row[]=[],vs:Row[]=[],es:Row[]=[];
  for(const p of parts){if(p._existing)continue;const row:Row={id:p._id,token_digest:await digest(token()),mode:p.mode,group_code:Number(p.group_code.slice(1)),block:p.block,swap_bits:p.swap_bits,task_order:p.task_order,created_at:p.started_at,design_version:p.design_version,task_hash:p.task_hash,source_instance:p.source_instance,source_participant_id:p.source_participant_id,validation_status:'unreviewed',provenance:'import:'+id,additional_answers:p.additional_answers_json||'{}'};for(const k of ['stimulus_started_at','stimulus_end_at','attributes_seen_at','dce_started_at','dce_completed_at','completed_at','age',...Object.keys(SURVEY),'stimulus_versions','consent_version'])row[k]=p[k]?(k==='age'?Number(p[k]):p[k]):null;ps.push(row);
    for(const c of [...choices.values()].filter(c=>c.participant_id===p.participant_id)){cs.push({participant_id:p._id,task_id:c.task_id,displayed_choice:c.displayed_choice,answered_at:c.answered_at,process_json:JSON.stringify(c.process)});if(c.started_at)vs.push({participant_id:p._id,task_id:c.task_id,started_at:c.started_at,a_json:null,b_json:null,content_version:null})}
    for(const event of p._events)es.push({...event,event_id:'imp_'+(await uuid5(p._id+'\x1f'+event.event_id)).replaceAll('-',''),participant_id:p._id,shown_at:event.shown_at||null,closed_at:event.closed_at||null,close_reason:event.close_reason||''});
  }
  const guard={batch:id},writes:D1PreparedStatement[]=[];
  if(ps.length)writes.push(...bulk(db,'participants',Object.keys(ps[0]),ps,guard));
  if(vs.length)writes.push(...bulk(db,'task_views',['participant_id','task_id','started_at','a_json','b_json','content_version'],vs,guard));
  if(cs.length)writes.push(...bulk(db,'choices',['participant_id','task_id','displayed_choice','answered_at','process_json'],cs,guard));
  if(es.length)writes.push(...bulk(db,'detail_views',['event_id','participant_id','task_id','alternative','kind','level','content_version','opened_at','shown_at','updated_at','closed_at','duration_ms','close_reason'],es,guard));
  assert(writes.length<=30,'本次记录较多，请拆成较小的参与者批次，避免D1单次调用限制');
  const oldReport=JSON.parse(batch.report);writes.push(stmt(db,"UPDATE import_batches SET status='committed',committed_at=?,report=? WHERE id=? AND owner=? AND status='previewed'",now(),JSON.stringify({...report,files:oldReport.files}),id,owner));await db.batch(writes);return report;
}
