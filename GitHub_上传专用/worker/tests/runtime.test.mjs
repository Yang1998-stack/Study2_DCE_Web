import {test,before,after} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {build} from 'esbuild';
import {Miniflare,createFetchMock,Log,LogLevel} from 'miniflare';
import {unzipSync,strFromU8,zipSync,strToU8} from 'fflate';

const root=resolve('.'),bundle=resolve('.worker-build/test-worker.mjs'),disposables=[];
const PASSWORD='local-test-password-never-production';
const SURVEY={age:'24',gender:'male',education:'college',online_purchase:'monthly1',plant_based_purchase:'unsure',manip_visual:'chart',manip_ai:'no'};
const tasks=JSON.parse(await readFile('designs/tasks_1l_v2.json','utf8'));
const sha=b=>createHash('sha256').update(b).digest('hex');
before(async()=>{await mkdir('.worker-build',{recursive:true});for(const [entry,out]of [['index','test-worker'],['files','files'],['data','data'],['analysis','analysis']])await build({entryPoints:[`worker/${entry}.ts`],bundle:true,format:'esm',target:'es2022',platform:'browser',loader:{'.sql':'text'},outfile:resolve(`.worker-build/${out}.mjs`)})});
after(async()=>{for(const mf of disposables)await mf.dispose()});
async function app(bindings={},persist){
 const fetchMock=createFetchMock();fetchMock.disableNetConnect();
 const mf=new Miniflare({modules:true,scriptPath:bundle,compatibilityDate:'2026-07-01',log:new Log(LogLevel.ERROR),assets:{directory:resolve('static'),binding:'ASSETS',routerConfig:{has_user_worker:true,invoke_user_worker_ahead_of_assets:true},assetConfig:{html_handling:'none',not_found_handling:'none'}},d1Databases:{DB:'study2-test'},d1Persist:persist||resolve('.wrangler/tests/'+randomUUID()),bindings:{DCE_MODE:'demo',ADMIN_USERNAME:'researcher',ADMIN_PASSWORD:PASSWORD,QUICKFORM_FORMAL_ENABLED:'NO',QUICKFORM_PILOT_ENABLED:'NO',...bindings},fetchMock});
 disposables.push(mf);await mf.ready;return {mf,fetchMock,db:await mf.getD1Database('DB')};
}
class Client{
 constructor(mf){this.mf=mf;this.cookies=new Map();this.csrf=null}
 async call(path,data,overrides={}){
  const headers={'Cookie':[...this.cookies].map(([k,v])=>k+'='+v).join('; '),...(data!==undefined?{'Content-Type':'application/json','X-CSRF-Token':this.csrf||''}:{}),...overrides};
  const response=await this.mf.dispatchFetch('https://study2.test'+path,{method:data!==undefined?'POST':'GET',headers,body:data!==undefined?JSON.stringify(data):undefined});
  const set=response.headers.get('set-cookie');if(set){const pair=set.split(';')[0],i=pair.indexOf('=');if(pair.slice(i+1))this.cookies.set(pair.slice(0,i),pair.slice(i+1));else this.cookies.delete(pair.slice(0,i))}
  const bytes=new Uint8Array(await response.arrayBuffer()),text=new TextDecoder().decode(bytes),value=response.headers.get('Content-Type')?.includes('application/json')?JSON.parse(text):null;
  if(value?.csrf)this.csrf=value.csrf;
  return {status:response.status,data:value,bytes,text,headers:response.headers};
 }
 async ok(path,data,overrides){const r=await this.call(path,data,overrides);assert.equal(r.status,200,r.data?JSON.stringify(r.data):r.text);return r.data}
 async login(){return this.ok('/api/admin/login',{username:'researcher',password:PASSWORD})}
}
async function start(client){return client.ok('/api/start',{consent:true,adult:true,recent_shopping:true})}
async function complete(client){let s=await client.ok('/api/viewed',{});s=await client.ok('/api/attributes',{});const seen=[];for(let i=0;i<8;i++){assert.equal(s.phase,'choice');seen.push(s);s=await client.ok('/api/answer',{task_id:s.task_id,choice:['A','B','N'][i%3]})}assert.equal(s.phase,'survey');return seen}
async function settle(db,pid,wanted){const end=Date.now()+5000;while(Date.now()<end){const r=await db.prepare('SELECT * FROM qf_submissions WHERE participant_id=?').bind(pid).first();if(r?.status===wanted)return r;await new Promise(r=>setTimeout(r,20))}assert.fail('同步状态未到达'+wanted)}
const csvFiles=async(bytes)=>{const codec=await import(new URL('../../.worker-build/files.mjs',import.meta.url));return Object.fromEntries(Object.entries(unzipSync(bytes)).filter(([n])=>n.endsWith('.csv')).map(([n,b])=>[n,codec.readTable(n,b)]))};
const encodedFiles=(files)=>Object.entries(files).filter(([n])=>n.endsWith('.csv')).map(([name,bytes])=>({name,data:Buffer.from(bytes).toString('base64')}));
const scoped='mode=demo&design_version=study2-1l-3price-v2';

test('原始设计、属性编码、广告与Wrangler命名保持不变',async()=>{
 const cfg=JSON.parse(await readFile('config/design_config.json','utf8'));assert.equal(sha(await readFile(cfg.task_file)),cfg.task_sha256);assert.equal(tasks.length,16);assert.deepEqual(['A','B'].map(b=>tasks.filter(t=>t.block===b).length),[8,8]);
 for(const [name,hash]of Object.entries({chart:'21292f60ad8ab7d4120a73fde93d6050728768c82ac2bc06dc2bfd56614f445f',nature:'6dfe23fb124ccd4912cc3ee35c7519bd9975d2da3b6a6c270bfba73961ef2148'}))assert.equal(sha(await readFile(`static/stimuli/${name}.jpg`)),hash);
 const wrangler=JSON.parse(await readFile('wrangler.jsonc','utf8'));assert.equal(wrangler.name,'study2-dce-web');assert.equal(wrangler.vars.QUICKFORM_FORMAL_ENABLED,'NO');assert(!wrangler.vars.ADMIN_PASSWORD);
});
test('本地workerd运行、D1初始化、静态广告及私有文件访问控制',async()=>{
 const {mf}=await app(),c=new Client(mf);const health=await c.ok('/health');assert.equal(health.database,'D1');
 const page=await c.call('/');assert.equal(page.status,200);assert(page.text.includes('/static/app.js'));
 for(const n of ['chart','nature']){const r=await c.call('/static/stimuli/'+n+'.jpg');assert.equal(r.status,200);assert.equal(sha(r.bytes),sha(await readFile('static/stimuli/'+n+'.jpg')))}
 for(const path of ['/data/study2.sqlite3','/config/study_config.json','/server.py','/migrations/0001_initial.sql','/admin.html'])assert.equal((await c.call(path)).status,404);
 assert.equal((await c.call('/api/admin/stats?'+scoped)).status,401);
});
test('真实D1上的单个完整答卷、刷新和重复提交均不会覆盖',async()=>{
 const {mf,db}=await app(),c=new Client(mf);let s=await start(c);assert.equal(s.phase,'stimulus');const id=s.participant_id;
 const seen=await complete(c);assert.equal(new Set(seen.map(x=>x.task_id)).size,8);
 const done=await c.ok('/api/finish',SURVEY);assert.equal(done.phase,'done');await c.ok('/api/finish',{...SURVEY,age:'66'});
 assert.equal((await db.prepare('SELECT COUNT(*) n FROM choices').first()).n,8);assert.equal((await db.prepare('SELECT age FROM participants WHERE id=?').bind(id).first()).age,24);
 assert.equal((await db.prepare('SELECT COUNT(*) n FROM qf_submissions').first()).n,0);assert.equal((await c.ok('/api/state')).phase,'done');
 await c.login();const zip=await c.call('/api/admin/export?'+scoped);assert.equal(zip.status,200);const files=await csvFiles(zip.bytes);assert.equal(files['choice_long.csv'].rows.length,24);
 for(let i=0;i<8;i++){const long=files['choice_long.csv'].rows.filter(x=>x.task_id===seen[i].task_id);assert.equal(long.filter(x=>x.choice==='1').length,1);for(const label of ['A','B']){const row=long.find(x=>x.alternative===label),actual=seen[i][label.toLowerCase()];assert.equal(Number(row.price_yuan),actual.price);assert.equal(Number(row.origin_import),actual.origin);assert.equal(Number(row.price_level),actual.price_level)}const n=long.find(x=>x.alternative==='N');assert.equal(n.opt_out,'1');assert.equal(n.price_yuan,'');assert.equal(n.product_volume_ml,'')}
});

test('四种广告、统一属性解释、全部16题及两个显示位置逐一对应',async()=>{
 const {mf}=await app(),c=new Client(mf);await c.login();const common=[];const {offers,active,display}=await import(new URL('../../.worker-build/data.mjs',import.meta.url));
 for(let group=1;group<=4;group++){const s=await c.ok('/api/admin/demo',{group,block:group%2?'A':'B'});assert.equal(s.image,`/static/stimuli/${group%2?'chart':'nature'}.jpg`);assert.equal(s.ai_disclosed,group>=3);common.push(s.info_descriptions);const seen=await complete(c);assert.equal(seen.length,8)}
 assert(common.every(x=>JSON.stringify(x)===JSON.stringify(common[0])));
 const combinations=new Set();for(const block of ['A','B'])for(const swapped of [0,1]){const p={design_version:active.config.version,task_order:JSON.stringify(active.byBlock[block].map(t=>t.id)),swap_bits:String(swapped).repeat(8)};for(const tid of JSON.parse(p.task_order)){const o=offers(p,tid),t=active.byId[tid];assert.deepEqual(o.a.origin,(swapped?t.b:t.a).origin);assert.deepEqual(o.b.quality,(swapped?t.a:t.b).quality);for(const x of [o.a,o.b]){assert([15,24,34].includes(x.price));assert.equal(x.product_volume_ml,1000);assert.equal(display(x).price,`¥${x.price}`);combinations.add(`${x.verification}${x.quality}`)}}}assert.equal(combinations.size,4);
});
test('并发入组保持四组内两个区组均衡，不允许受访者指定条件',async()=>{
 const {mf,db}=await app();await new Client(mf).ok('/health');await Promise.all(Array.from({length:16},()=>start(new Client(mf))));const cells=(await db.prepare('SELECT group_code,block,COUNT(*) n FROM participants GROUP BY group_code,block').all()).results;assert.equal(cells.length,8);assert(cells.every(x=>x.n===2));assert.equal((await new Client(mf).call('/api/start',{consent:true,adult:true,recent_shopping:true,group:1})).status,400);
});
test('详情基础内容相同、额外模块独立随编码、过程时长不可凭客户端放大',async()=>{
 const {mf,db}=await app(),c=new Client(mf);await start(c);await c.ok('/api/viewed',{});let s=await c.ok('/api/attributes',{});const bases={};
 for(let i=0;i<8;i++){for(const alt of ['A','B'])for(const kind of ['environment','quality']){const id=randomUUID(),r=await c.ok('/api/details/open',{event_id:id,task_id:s.task_id,alternative:alt,kind}),level=s[alt.toLowerCase()][kind==='environment'?'verification':'quality'];assert.equal(!!r.extra,!!level);if(bases[kind])assert.deepEqual(r.base,bases[kind]);bases[kind]=r.base;const p=await c.ok('/api/details/progress',{event_id:id,shown:true,duration_ms:86400000,closed:true,reason:'close'});assert(p.duration_ms<10000)}s=await c.ok('/api/answer',{task_id:s.task_id,choice:'N'})}
 assert.equal((await db.prepare('SELECT COUNT(*) n FROM detail_views WHERE shown_at IS NOT NULL').first()).n,32);
});
test('同题并发只保存一次，改选被拒绝，断开进程后可恢复D1数据',async()=>{
 const persist=resolve('.wrangler/tests/'+randomUUID()),a=await app({},persist),c=new Client(a.mf);await start(c);await c.ok('/api/viewed',{});const s=await c.ok('/api/attributes',{});const rs=await Promise.all([c.call('/api/answer',{task_id:s.task_id,choice:'A'}),c.call('/api/answer',{task_id:s.task_id,choice:'A'})]);assert(rs.every(r=>r.status===200));assert.equal((await c.call('/api/answer',{task_id:s.task_id,choice:'B'})).status,409);
 const cookies=c.cookies;await a.mf.dispose();disposables.splice(disposables.indexOf(a.mf),1);const b=await app({},persist),restored=new Client(b.mf);restored.cookies=cookies;const next=await restored.ok('/api/state');assert.equal(next.answered,1);assert.equal(next.position,2);assert.equal((await b.db.prepare('SELECT COUNT(*) n FROM choices').first()).n,1);
});
test('后台鉴权、CSRF与跨站请求检查，人数与有效样本须分别计数',async()=>{
 const {mf,db}=await app(),c=new Client(mf);const s=await start(c);await complete(c);await c.ok('/api/finish',SURVEY);await c.login();const stats=await c.ok('/api/admin/stats?'+scoped);assert.deepEqual(stats.totals,{started:1,completed:1,incomplete:0,valid:0,completion_rate:1});assert.equal((await c.call('/api/admin/review',{participant_id:s.participant_id,status:'valid'},{'X-CSRF-Token':''})).status,403);assert.equal((await c.call('/api/admin/review',{participant_id:s.participant_id,status:'valid'},{Origin:'https://attacker.invalid'})).status,403);await c.ok('/api/admin/review',{participant_id:s.participant_id,status:'valid',note:'研究者审核'});assert.equal((await c.ok('/api/admin/stats?'+scoped)).totals.valid,1);assert.equal((await db.prepare('SELECT COUNT(*) n FROM participants').first()).n,1);assert.equal((await c.ok('/api/admin/stats?mode=pilot')).totals.started,0);
});
test('CSV导入先预览再确认、跨实例汇总、重复不覆盖、错误原件有日志',async()=>{
 const a=await app(),source=new Client(a.mf);await start(source);await complete(source);await source.ok('/api/finish',SURVEY);await source.login();const archive=unzipSync((await source.call('/api/admin/export?'+scoped)).bytes),b=await app(),c=new Client(b.mf);await c.login();const request={mode:'demo',design_version:'study2-1l-3price-v2',files:encodedFiles(archive)};let p=await c.ok('/api/admin/import/preview',request);assert.equal(p.error_count,0,JSON.stringify(p));assert.equal(p.new_participants,1);assert.equal((await b.db.prepare('SELECT COUNT(*) n FROM participants').first()).n,0);assert.equal((await c.call('/api/admin/import/commit',{batch_id:p.batch_id})).status,400);await c.ok('/api/admin/import/commit',{batch_id:p.batch_id,confirm:true});assert.equal((await b.db.prepare('SELECT COUNT(*) n FROM choices').first()).n,8);p=await c.ok('/api/admin/import/preview',request);assert.equal(p.duplicates,1,JSON.stringify(p));await c.ok('/api/admin/import/commit',{batch_id:p.batch_id,confirm:true});assert.equal((await b.db.prepare('SELECT COUNT(*) n FROM participants').first()).n,1);
 const wrong=structuredClone(request);wrong.mode='formal';const rejected=await c.ok('/api/admin/import/preview',wrong);assert(rejected.error_count>0);const original=unzipSync((await c.call('/api/admin/import/archive?batch_id='+rejected.batch_id)).bytes);assert.deepEqual(original['participants.csv'],archive['participants.csv']);assert.equal((await c.call('/api/admin/import/commit',{batch_id:rejected.batch_id,confirm:true})).status,400);
 const bad=structuredClone(request);bad.files[0].data=Buffer.from(Buffer.from(bad.files[0].data,'base64').toString('utf8').replace('G1','G9').replace('G2','G9').replace('G3','G9').replace('G4','G9')).toString('base64');assert((await c.ok('/api/admin/import/preview',bad)).error_count>0);
 const backup=await c.ok('/api/admin/backup',{mode:'demo',design_version:'study2-1l-3price-v2'});assert.equal((await csvFiles((await c.call(backup.download)).bytes))['choices.csv'].rows.length,8);
});
const pilot={DCE_MODE:'pilot',QUICKFORM_PILOT_ENABLED:'YES',QUICKFORM_PILOT_API_URL:'https://mock-collector.invalid/api/pilot_only'};
test('独立模拟QuickForm只收到一份完整UTF-8答卷，成功确认后刷新不重发',async()=>{
 const {mf,db,fetchMock}=await app(pilot),c=new Client(mf);let captured,requests=0;fetchMock.get('https://mock-collector.invalid').intercept({path:'/api/pilot_only',method:'POST'}).reply(200,options=>{requests++;captured=new Response(options.body).text().then(JSON.parse);return JSON.stringify({status:'success'})},{headers:{'Content-Type':'application/json'}});
 const s=await start(c),seen=await complete(c);assert.equal((await db.prepare('SELECT COUNT(*) n FROM qf_submissions').first()).n,0);await c.ok('/api/finish',SURVEY);const row=await settle(db,s.participant_id,'success');await c.ok('/api/finish',SURVEY);await c.ok('/api/state');assert.equal(requests,1);captured=await captured;assert.equal(captured.survey_mode,'pilot');assert.equal(captured.n_choice_tasks,8);assert(['环境数据图表型','自然场景型'].includes(captured.visual_type));const items=JSON.parse(captured.dce_choices_json);assert.equal(items.length,8);assert.equal((await db.prepare('SELECT COUNT(*) n FROM qf_attempts').first()).n,1);for(let i=0;i<8;i++)for(const alt of ['A','B']){assert.equal(items[i][alt].codes.price_yuan,seen[i][alt.toLowerCase()].price);assert.equal(items[i][alt].codes.origin,seen[i][alt.toLowerCase()].origin);assert(items[i][alt].display.environmental_verification.includes('环境信息'))}assert.equal(sha(Buffer.from(row.payload_json)),row.payload_sha256);const {quickformLong}=await import(new URL('../../.worker-build/analysis.mjs',import.meta.url));const restored=quickformLong([captured]);assert.equal(restored.length,24);assert.equal(restored.filter(x=>x.chosen===1).length,8);assert(restored.filter(x=>x.opt_out).every(x=>x.price===null));
 const keys=Object.keys(captured),quickformCsv=strToU8(keys.join(',')+'\n'+keys.map(k=>'"'+String(captured[k]??'').replaceAll('"','""')+'"').join(','));const {readTable}=await import(new URL('../../.worker-build/files.mjs',import.meta.url));assert.equal(quickformLong(readTable('quickform.csv',quickformCsv,512).rows).length,24);await writeFile('.worker-build/quickform-export.csv',quickformCsv);
});
test('网络异常标记需核查且保留答卷，明确失败可人工重试而不改选择',async()=>{
 const {mf,db,fetchMock}=await app(pilot),c=new Client(mf);const s=await start(c);await complete(c);await c.ok('/api/finish',SURVEY);const q=await settle(db,s.participant_id,'uncertain');assert.equal((await db.prepare('SELECT COUNT(*) n FROM choices').first()).n,8);await c.login();assert.equal((await c.call('/api/admin/quickform/action',{participant_id:s.participant_id,action:'retry',note:'尚未核查远端结果'})).status,400);
 await c.ok('/api/admin/quickform/action',{participant_id:s.participant_id,action:'review',decision:'received',confirm:true,note:'模拟接口记录已人工核查收到'});assert.equal((await db.prepare('SELECT status FROM qf_submissions').first()).status,'success');assert.equal((await db.prepare('SELECT payload_sha256 FROM qf_submissions').first()).payload_sha256,q.payload_sha256);
 const d=new Client(mf);fetchMock.get('https://mock-collector.invalid').intercept({path:'/api/pilot_only',method:'POST'}).reply(400,JSON.stringify({status:'error'}));const s2=await start(d);await complete(d);await d.ok('/api/finish',SURVEY);await settle(db,s2.participant_id,'failed');fetchMock.get('https://mock-collector.invalid').intercept({path:'/api/pilot_only',method:'POST'}).reply(200,JSON.stringify({status:'success'}));await c.ok('/api/admin/quickform/action',{participant_id:s2.participant_id,action:'retry',note:'模拟明确失败后人工重试'});await settle(db,s2.participant_id,'success');assert.equal((await db.prepare('SELECT COUNT(*) n FROM choices WHERE participant_id=?').bind(s2.participant_id).first()).n,8);
});
test('正式发布锁与邀请码：即使误设同步开关也不向正式接口发送',async()=>{
 const {mf,db}=await app({DCE_MODE:'formal',DCE_ALLOW_FORMAL:'YES',QUICKFORM_FORMAL_ENABLED:'YES'}),admin=new Client(mf);await admin.login();const codes=(await admin.ok('/api/admin/invitations',{mode:'formal',count:1})).codes;assert.equal((await new Client(mf).call('/api/start',{adult:true,consent:true,recent_shopping:true})).status,400);const clients=[new Client(mf),new Client(mf)],results=await Promise.all(clients.map(c=>c.call('/api/start',{adult:true,consent:true,recent_shopping:true,invitation:codes[0]})));assert.equal(results.filter(r=>r.status===200).length,1);const i=results.findIndex(r=>r.status===200),c=clients[i];await complete(c);await c.ok('/api/finish',SURVEY);const q=await db.prepare('SELECT * FROM qf_submissions').first();assert.equal(q.status,'pending');assert.equal(q.attempt_count,0);assert.equal((await c.call('/api/demo/restart',{})).status,403);const status=await admin.ok('/api/admin/quickform?mode=formal');assert.equal(status.enabled,false);assert.equal(status.completed_local,1);assert.equal((await admin.ok('/api/admin/stats?mode=demo')).totals.started,0);
});
test('429有限退避最多三次，202不冒充成功且不自动重试',async()=>{
 const {mf,db,fetchMock}=await app(pilot),c=new Client(mf);fetchMock.get('https://mock-collector.invalid').intercept({path:'/api/pilot_only',method:'POST'}).reply(429,JSON.stringify({status:'error',retry_after:60})).times(3);const s=await start(c);await complete(c);await c.ok('/api/finish',SURVEY);let q=await settle(db,s.participant_id,'pending');while(q.attempt_count<1||q.in_flight_token){await new Promise(r=>setTimeout(r,20));q=await db.prepare('SELECT * FROM qf_submissions').first()}assert(Date.parse(q.next_attempt_at)>Date.now()+30000);const before=q.payload_sha256;
 for(let i=0;i<2;i++){await db.prepare('UPDATE qf_submissions SET next_attempt_at=?').bind('2000-01-01T00:00:00.000Z').run();await (await mf.getWorker()).scheduled({scheduledTime:Date.parse('2026-10-26T01:30:00Z'),cron:'* * * * *'});const until=Date.now()+2000;do{q=await db.prepare('SELECT * FROM qf_submissions').first();if(q.attempt_count===i+2&&!q.in_flight_token)break;await new Promise(r=>setTimeout(r,20))}while(Date.now()<until)}assert.equal(q.status,'failed');assert.equal(q.attempt_count,3);assert.equal(q.payload_sha256,before);
 const d=new Client(mf);fetchMock.get('https://mock-collector.invalid').intercept({path:'/api/pilot_only',method:'POST'}).reply(202,JSON.stringify({status:'success'}));const s2=await start(d);await complete(d);await d.ok('/api/finish',SURVEY);await settle(db,s2.participant_id,'uncertain');await (await mf.getWorker()).scheduled({scheduledTime:Date.parse('2026-10-26T01:30:00Z'),cron:'* * * * *'});assert.equal((await db.prepare('SELECT attempt_count FROM qf_submissions WHERE participant_id=?').bind(s2.participant_id).first()).attempt_count,1);
});
test('XLSX中文解析、公式拒绝和长格式多选校验',async()=>{
 const {readTable}=await import(new URL('../../.worker-build/files.mjs',import.meta.url));const sheet=content=>zipSync({'xl/worksheets/sheet1.xml':strToU8('<worksheet><sheetData>'+content+'</sheetData></worksheet>')});const xml='<row><c r="A1" t="inlineStr"><is><t>participant_id</t></is></c></row><row><c r="A2" t="inlineStr"><is><t>中文编号</t></is></c></row>';assert.equal(readTable('participants.xlsx',sheet(xml)).rows[0].participant_id,'中文编号');assert.throws(()=>readTable('participants.xlsx',sheet(xml.replace('<t>中文编号</t>','<t>中文编号</t>').replace('<is><t>中文编号</t></is>','<f>1+1</f><v>2</v>'))));assert.throws(()=>readTable('participants.csv',strToU8('participant_id,participant_id\nx,y')));
 const {mf}=await app(),c=new Client(mf);await start(c);await complete(c);await c.ok('/api/finish',SURVEY);await c.login();const files=unzipSync((await c.call('/api/admin/export?'+scoped)).bytes),parsed=readTable('choice_long.csv',files['choice_long.csv']);parsed.rows[0].choice='1';parsed.rows[0].chosen='1';parsed.rows[1].choice='1';parsed.rows[1].chosen='1';const encode=rows=>strToU8(parsed.fields.join(',')+'\n'+rows.map(r=>parsed.fields.map(k=>'"'+r[k].replaceAll('"','""')+'"').join(',')).join('\n'));files['choice_long.csv']=encode(parsed.rows);delete files['choices.csv'];const r=await c.ok('/api/admin/import/preview',{mode:'demo',design_version:'study2-1l-3price-v2',files:encodedFiles(files)});assert(r.error_count>0);assert(r.errors.some(x=>x.includes('恰好一个')));
});
