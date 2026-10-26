import { codes, designs, offers } from './data';
import { assert } from './security';
import type { Row } from './types';
// Offline recovery accepts only complete, identifiable records. It never imputes choices.
export function quickformLong(records:Row[]) {
  const output:Row[]=[],seen=new Set<string>();
  for(const r of records){
    assert(r.participant_id&&!seen.has(r.participant_id),'参与者编号缺失或重复');seen.add(r.participant_id);
    const d=designs[r.design_version];assert(d&&r.task_design_sha256===d.config.task_sha256,'未知设计版本或哈希不匹配');
    assert(['demo','pilot','formal'].includes(r.survey_mode)&&/^G[1-4]$/.test(r.experiment_group)&&d.byBlock[r.dce_block],'模式、组别或区组不合法');
    const sets=typeof r.dce_choices_json==='string'?JSON.parse(r.dce_choices_json):r.dce_choices_json;
    assert(Array.isArray(sets)&&sets.length===8&&new Set(sets.map(x=>x.task_id)).size===8,'完整答卷必须恰好8题');
    const p={design_version:r.design_version,task_order:JSON.stringify(sets.map(x=>x.task_id)),swap_bits:sets.map(x=>{assert([0,1].includes(x.swapped),'交换编码错误');return x.swapped}).join('')};
    for(let i=0;i<8;i++){
      const s=sets[i];assert(s.position===i+1&&['A','B','N'].includes(s.choice)&&d.byBlock[r.dce_block].some(t=>t.id===s.task_id),'题目、位置或选择错误');const os=offers(p,s.task_id);
      for(const alt of ['A','B'] as const){const expected=codes(alt==='A'?os.a:os.b);assert(s[alt]?.codes&&Object.entries(expected).every(([k,v])=>s[alt].codes[k]===v),'实际显示属性与设计不一致')}
      for(const alt of ['A','B','N']){const o=alt==='A'?os.a:alt==='B'?os.b:null;output.push({participant_id:r.participant_id,choice_set_id:r.participant_id+'_'+s.task_id,alternative_id:alt,alternative:alt,chosen:Number(s.choice===alt),choice:Number(s.choice===alt),origin:o?.origin??null,origin_import:o?.origin??null,environmental_verification:o?.verification??null,third_party_verification:o?.verification??null,quality_information:o?.quality??null,batch_quality_report:o?.quality??null,price:o?.price??null,price_yuan:o?.price??null,price_level:o?.price_level??null,product_volume_ml:o?.product_volume_ml??null,opt_out:Number(alt==='N'),visual_type:r.visual_type,visual:Number(['G1','G3'].includes(r.experiment_group)),ai_disclosure:Number(['G3','G4'].includes(r.experiment_group)),dce_block:r.dce_block,design_version:r.design_version,mode:r.survey_mode,task_id:s.task_id,position:s.position,swapped:s.swapped,started_at:s.started_at,answered_at:s.completed_at})}
    }
  }
  return output;
}
