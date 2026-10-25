"""Immutable completion payloads and validated reconstruction of QuickForm exports."""
import json
import uuid
import storage as s
import product_details as docs
import detail_tracking as dt
import design_registry as registry

SCHEMA = 'study2-qf-v2'
ORIGIN = ('使用国产燕麦原料','使用进口燕麦原料')
VISUAL = {1:'环境数据图表型',2:'自然场景型',3:'环境数据图表型',4:'自然场景型'}
ATTRIBUTES = ('origin','environmental_verification','quality_information','price')
EXTRA_SCHEMA = s.ROOT/'config/questionnaire_schema.json'

def participant_uuid(p):
    # Stable across instance exports/imports without rewriting any old local ID.
    return str(uuid.uuid5(uuid.NAMESPACE_URL,json.dumps([p['source_instance'],p['source_participant_id'],p['mode']],ensure_ascii=False,separators=(',',':'))))

def codes(offer,design=None):
    offer=(design or registry.ACTIVE).offer(offer)
    return dict(origin=offer['origin'],environmental_verification=offer['verification'],quality_information=offer['quality'],price=offer['price'],
                price_yuan=offer['price'],price_level=offer['price_level'],product_volume_ml=offer['product_volume_ml'])

def display(offer):
    return dict(origin=ORIGIN[offer['origin']],environmental_verification=docs.DESCRIPTIONS['verification'][offer['verification']],
                quality_information=docs.DESCRIPTIONS['quality'][offer['quality']],price=f'¥{offer["price"]}',capacity='1 L')

def snapshot_display(c,p,tid):
    _,_,a,b=s.offers(p,tid)
    c.execute('INSERT OR IGNORE INTO choice_display_snapshots VALUES (?,?,?,?,?,?)',
              (p['id'],tid,json.dumps(dict(codes=codes(a),display=display(a)),ensure_ascii=False),
               json.dumps(dict(codes=codes(b),display=display(b)),ensure_ascii=False),docs.VERSION,s.now()))
    save_products(c,p,tid)

def save_products(c,p,tid,started_at=None):
    _,_,a,b=s.offers(p,tid)
    if started_at is None:
        row=c.execute('SELECT started_at FROM task_views WHERE participant_id=? AND task_id=?',(p['id'],tid)).fetchone()
        started_at=row[0] if row else None
    for alt,o in (('A',a),('B',b)):
        values=(p['id'],tid,alt,p['design_version'],o['origin'],o['verification'],o['quality'],o['price'],o['price_level'],o['product_volume_ml'],started_at)
        c.execute('INSERT OR IGNORE INTO choice_products VALUES (?,?,?,?,?,?,?,?,?,?,?)',values)
        saved=c.execute('SELECT * FROM choice_products WHERE participant_id=? AND task_id=? AND alternative=?',(p['id'],tid,alt)).fetchone()
        if tuple(saved)[:10]!=values[:10]:raise ValueError('实际商品属性快照与设计/显示位置冲突，禁止静默覆盖')

def validate_extensions(answers):
    if not isinstance(answers,dict): raise ValueError('扩展问卷答案须为对象')
    schema=json.loads(EXTRA_SCHEMA.read_text(encoding='utf-8'))['fields']
    if set(answers)-set(schema): raise ValueError('存在尚未配置的问卷字段，不能代填量表')
    for key,rule in schema.items():
        if key not in answers:
            if rule.get('required'): raise ValueError(f'缺少必填扩展问题：{key}')
            continue
        value=answers[key]; kind=rule['type']
        valid=(kind=='string' and isinstance(value,str) and len(value)<=2000 or
               kind=='integer' and type(value) is int or kind=='boolean' and type(value) is bool or
               kind=='choice' and value in rule['values'] or kind=='json' and isinstance(value,(list,dict)))
        if not valid: raise ValueError(f'扩展答案格式不合法：{key}')
    try: raw=json.dumps(answers,ensure_ascii=False,allow_nan=False)
    except (TypeError,ValueError): raise ValueError('扩展答案不能含非JSON值')
    if len(raw.encode())>16384: raise ValueError('扩展答案超出16 KiB')
    return answers

def build(c,p):
    design=registry.get(p['design_version'])
    if not p['completed_at'] or p['task_hash']!=design.task_hash:
        raise ValueError('仅同步已完成且设计版本及哈希一致的答卷')
    order=json.loads(p['task_order'])
    answers={r['task_id']:dict(r) for r in c.execute('SELECT * FROM choices WHERE participant_id=?',(p['id'],))}
    if len(order)!=design.total or len(set(order))!=design.total or set(order)!=set(answers) or set(order)!={t['id'] for t in design.by_block[p['block']]}:
        raise ValueError('DCE记录不足8题或题序/区组不一致，不能同步')
    if not p['age'] or any(p[k] not in levels for k,levels in s.SURVEY.items()): raise ValueError('后续问卷不完整，不能同步')
    questionnaire={k:p[k] for k in ('age',*s.SURVEY)}
    extra={r['field_name']:json.loads(r['answer_json']) for r in c.execute('SELECT * FROM questionnaire_answers WHERE participant_id=?',(p['id'],))}
    questionnaire.update(extra)
    pid=participant_uuid(p)
    result=dict(payload_version=SCHEMA,record_type='study2_dce_completed',participant_id=pid,participant_uuid=pid,
                local_participant_id=p['id'],source_instance=p['source_instance'],source_participant_id=p['source_participant_id'],
                submission_key=f'{pid}:{p["design_version"]}',experiment_group=f'G{p["group_code"]}',
                visual_type=VISUAL[p['group_code']],visual_code='chart' if p['group_code'] in (1,3) else 'nature',
                visual=int(p['group_code'] in (1,3)),ai_disclosure=int(p['group_code'] in (3,4)),
                dce_block=p['block'],design_version=p['design_version'],task_design_sha256=p['task_hash'],survey_mode=p['mode'],product_volume_ml=design.volume,
                started_at=p['created_at'],completed_at=p['completed_at'],duration_seconds=s.seconds(p['created_at'],p['completed_at']),
                dce_duration_seconds=s.seconds(p['dce_started_at'],p['dce_completed_at']),completion_status='completed',n_choice_tasks=s.TOTAL,
                stimulus_started_at=p['stimulus_started_at'],stimulus_end_at=p['stimulus_end_at'],
                stimulus_versions_json=p['stimulus_versions'],consent_version=p['consent_version'],
                questionnaire_json=json.dumps(questionnaire,ensure_ascii=False,separators=(',',':')),
                green_consumption_values_json=json.dumps(extra.get('green_consumption_values'),ensure_ascii=False),
                green_consumption_values_status='collected' if 'green_consumption_values' in extra else 'not_collected',
                oat_drink_purchase_experience=extra.get('oat_drink_purchase_experience'),
                oat_drink_purchase_experience_status='collected' if 'oat_drink_purchase_experience' in extra else 'not_collected')
    result.update({k:p[k] for k in ('age',*s.SURVEY)})
    for key,value in extra.items(): result['questionnaire_'+key]=json.dumps(value,ensure_ascii=False) if isinstance(value,(list,dict)) else value
    items=[]
    for pos,tid in enumerate(order,1):
        _,swap,a,b=s.offers(p,tid); answer=answers[tid]
        if answer['displayed_choice'] not in ('A','B','N'): raise ValueError('选择结果不合法')
        view=c.execute('SELECT started_at FROM task_views WHERE participant_id=? AND task_id=?',(p['id'],tid)).fetchone()
        start=view[0] if view else None
        snap=c.execute('SELECT * FROM choice_display_snapshots WHERE participant_id=? AND task_id=?',(p['id'],tid)).fetchone()
        item=dict(task_id=tid,position=pos,swapped=int(swap),choice=answer['displayed_choice'],started_at=start,
                  completed_at=answer['answered_at'],duration_seconds=s.seconds(start,answer['answered_at']),
                  display_content_version=snap['content_version'] if snap else None,
                  display_text_provenance='server_delivery_snapshot' if snap else 'not_recorded_legacy',
                  original_a=codes(design.by_id[tid]['a'],design),original_b=codes(design.by_id[tid]['b'],design))
        for label,offer in (('A',a),('B',b)):
            actual=codes(offer,design); text=dict.fromkeys((*ATTRIBUTES,'capacity'))
            if snap:
                recorded=json.loads(snap[label.lower()+'_json'])
                if any(k not in actual or actual[k]!=v for k,v in recorded['codes'].items()): raise ValueError('展示快照与题目属性不一致，不能同步')
                text=recorded['display']
            item[label]=dict(codes=actual,display=text,process=dt.metrics(c,p['id'],tid,label))
            for attr in ATTRIBUTES:
                result[f'task_{pos}_{label}_{attr}']=actual[attr]
                result[f'task_{pos}_{label}_{attr}_text']=text[attr]
            for attr in ('price_yuan','price_level','product_volume_ml'):result[f'task_{pos}_{label}_{attr}']=actual[attr]
        for key in ('position','choice','swapped','started_at','completed_at','duration_seconds'):
            result[f'task_{pos}_{key}']=item[key]
        result[f'task_{pos}_id']=tid
        items.append(item)
    result['dce_choices_json']=json.dumps(items,ensure_ascii=False,separators=(',',':'))
    views=[{k:r[k] for k in ('event_id','task_id','alternative','kind','level','content_version','opened_at','shown_at','updated_at','closed_at','duration_ms','close_reason')} for r in c.execute('SELECT * FROM detail_views WHERE participant_id=? ORDER BY opened_at,event_id',(p['id'],))]
    result['detail_views_json']=json.dumps(views,ensure_ascii=False,separators=(',',':'))
    result['record_sha256']=s.digest(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
    return result

def restore_long(record,mode):
    """Only expand actually recorded choices; validate, never fill missing answers."""
    if record.get('payload_version') not in ('study2-qf-v1',SCHEMA) or record.get('completion_status')!='completed': raise ValueError('不是受支持的完整答卷结构')
    if record.get('survey_mode')!=mode: raise ValueError('数据模式不同，不能混合还原')
    design=registry.get(record.get('design_version'))
    if record.get('task_design_sha256')!=design.task_hash: raise ValueError('设计版本或哈希不同，不能还原')
    pid=str(uuid.UUID(record['participant_id'])); group=record.get('experiment_group');block=record.get('dce_block')
    if group not in ('G1','G2','G3','G4') or block not in design.by_block: raise ValueError('组别或区组不合法')
    g=int(group[1:])
    if str(record.get('ai_disclosure'))!=str(int(g in (3,4))) or record.get('visual_type')!=VISUAL[g]: raise ValueError('广告编码不一致')
    items=json.loads(record['dce_choices_json'])
    if len(items)!=design.total or {x['task_id'] for x in items}!={t['id'] for t in design.by_block[block]}: raise ValueError('必须恰好含本区组8题，不能补造缺失题')
    rows=[]
    for pos,item in enumerate(items,1):
        tid=item['task_id']; choice=item['choice']; swap=item['swapped']
        if item['position']!=pos or swap not in (0,1) or choice not in ('A','B','N'): raise ValueError('题序、交换位或选择结果不合法')
        for label,source in (('A','b' if swap else 'a'),('B','a' if swap else 'b')):
            expected=codes(design.by_id[tid][source],design)
            if any(item[label]['codes'].get(k)!=expected[k] for k in ATTRIBUTES) or any(k not in expected or expected[k]!=v for k,v in item[label]['codes'].items()):raise ValueError('实际A/B属性与原始任务不匹配')
            for attr,number in item[label]['codes'].items():
                field=f'task_{pos}_{label}_{attr}'
                if field in record and float(record[field])!=number: raise ValueError('扁平化属性与完整JSON不一致')
        if str(record.get(f'task_{pos}_choice',choice))!=choice: raise ValueError('扁平化选择与完整JSON不一致')
        for alt in ('A','B','N'):
            o=codes(design.by_id[tid][('b' if swap else 'a') if alt=='A' else ('a' if swap else 'b')],design) if alt!='N' else dict.fromkeys((*ATTRIBUTES,'price_yuan','price_level','product_volume_ml'))
            rows.append(dict(participant_id=pid,choice_set_id=f'{pid}_{tid}',alternative_id=alt,chosen=int(choice==alt),
                origin=o['origin'],environmental_verification=o['environmental_verification'],quality_information=o['quality_information'],price=o['price'],
                opt_out=int(alt=='N'),visual_type=VISUAL[g],ai_disclosure=int(g in (3,4)),dce_block=block,design_version=design.version,
                price_yuan=o['price_yuan'],price_level=o['price_level'],product_volume_ml=o['product_volume_ml'],
                survey_mode=mode,task_id=tid,position=pos,swapped=swap,started_at=item.get('started_at'),answered_at=item['completed_at'],
                local_participant_id=record.get('local_participant_id'),source_instance=record.get('source_instance')))
    return rows
