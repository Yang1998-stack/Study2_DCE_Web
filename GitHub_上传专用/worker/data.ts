import activeConfig from '../config/design_config.json';
import legacyConfig from '../designs/legacy_v1_config.json';
import currentTasks from '../designs/tasks_1l_v2.json';
import oldTasks from '../designs/tasks_legacy_v1.json';
import details from './content/product-details.json';
import study from '../config/study_config.json';
import approval from '../config/design_approval.json';
import extension from '../config/questionnaire_schema.json';
import columns from './content/export-columns.json';
import type { Design, Offer, Row, Task } from './types';
import { assert } from './security';
export { details, study, approval, extension, columns };
export const SURVEY: Record<string,string[]> = { gender:['female','male','other','undisclosed'],education:['highschool','college','bachelor','masterplus','undisclosed'],online_purchase:['monthly1','monthly2to3','weekly1plus','undisclosed'],plant_based_purchase:['yes','no','unsure'],manip_visual:['chart','nature','unsure'],manip_ai:['yes','no','unsure'] };
export const PROCESS = ['viewed_environment_details','viewed_quality_details','environment_details_view_duration','quality_details_view_duration'];
function make(config: Row, tasks: Task[]): Design {
  assert(tasks.length === config.task_count && config.tasks_per_participant === 8, '设计配置不正确', 503);
  const byId = Object.fromEntries(tasks.map(t => [t.id,t]));
  const byBlock = Object.fromEntries(config.blocks.map((b:string) => [b,tasks.filter(t => t.block === b)]));
  assert(Object.keys(byId).length === tasks.length && Object.values(byBlock).every(t => t.length === 8), '区组不正确', 503);
  for (const t of tasks) for (const o of [t.a,t.b]) for (const [k,levels] of Object.entries(config.levels)) assert((levels as number[]).includes((o as unknown as Row)[k]), '属性编码不正确', 503);
  return {config,tasks,byId,byBlock};
}
export const active = make(activeConfig,currentTasks);
export const legacy = make(legacyConfig,oldTasks);
export const designs: Record<string,Design> = { [active.config.version]:active,[legacy.config.version]:legacy };
export function designOf(version: string): Design { assert(Object.hasOwn(designs,version), '未知设计版本，禁止混合'); return designs[version] }
export function offer(o: Offer,d:Design): Offer { return {...o,price_level:d.config.levels.price.indexOf(o.price)+1,product_volume_ml:d.config.product_volume_ml} }
export function offers(p:Row, tid:string) {
  const d = designOf(p.design_version), order: string[] = typeof p.task_order === 'string' ? JSON.parse(p.task_order) : p.task_order;
  const i = order.indexOf(tid); assert(i>=0 && d.byId[tid], '任务不属于该参与者');
  const t = d.byId[tid], swapped=p.swap_bits[i]==='1';
  return {position:i+1,swapped:Number(swapped),a:offer(swapped?t.b:t.a,d),b:offer(swapped?t.a:t.b,d),original_a:offer(t.a,d),original_b:offer(t.b,d)};
}
export function codes(o:Offer) { return {origin:o.origin,environmental_verification:o.verification,quality_information:o.quality,price:o.price,price_yuan:o.price,price_level:o.price_level,product_volume_ml:o.product_volume_ml} }
export function display(o:Offer) { return {origin:['使用国产燕麦原料','使用进口燕麦原料'][o.origin],environmental_verification:details.DESCRIPTIONS.verification[o.verification],quality_information:details.DESCRIPTIONS.quality[o.quality],price:`¥${o.price}`,capacity:`${o.product_volume_ml! / 1000} L`} }
export const snapshot = (o:Offer) => ({codes:codes(o),display:display(o)});
export function formalApproved() { return approval.researcher_approved && approval.pilot_completed && approval.design_version===active.config.version && approval.task_sha256===active.config.task_sha256 && !!approval.pilot_reference }
export const VISUAL = (g:number) => g===1||g===3 ? '环境数据图表型' : '自然场景型';
export const stimuli = {chart:'21292f60ad8ab7d4120a73fde93d6050728768c82ac2bc06dc2bfd56614f445f',nature:'6dfe23fb124ccd4912cc3ee35c7519bd9975d2da3b6a6c270bfba73961ef2148'};
export function validateSurvey(data:Row) {
  assert(typeof data.age!=='boolean' && /^\d+$/.test(String(data.age)) && Number(data.age)>=18 && Number(data.age)<=100, '请输入18至100之间的整数年龄');
  for (const [key,values] of Object.entries(SURVEY)) assert(values.includes(data[key]), '请填写全部后续问题：'+key);
  const extra=data.additional_answers ?? {}; assert(extra && typeof extra==='object' && !Array.isArray(extra),'扩展答案须为对象');
  const fields=extension.fields as Record<string,Row>;
  assert(Object.keys(extra).every(k=>Object.hasOwn(fields,k)),'存在尚未设置的问卷字段，不允许补造量表');
  for (const [k,r] of Object.entries(fields)) {
    assert(!r.required || Object.hasOwn(extra,k),'缺少扩展问题：'+k); if (!Object.hasOwn(extra,k)) continue;
    const v=extra[k]; assert(r.type==='string'&&typeof v==='string'&&v.length<=2000 || r.type==='integer'&&Number.isInteger(v) || r.type==='boolean'&&typeof v==='boolean' || r.type==='choice'&&r.values.includes(v) || r.type==='json'&&v!==null&&typeof v==='object','扩展答案类型不合法：'+k);
  }
  assert(new TextEncoder().encode(JSON.stringify(extra)).length<=16384,'扩展答案超过16 KiB'); return extra;
}
