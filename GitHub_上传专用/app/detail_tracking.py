"""Detail-panel process variables. No choice/assignment is changed here."""
import math
import json
import re
import uuid
import storage as s
import product_details as docs
import design_registry as registry

FIELDS = ('viewed_environment_details','viewed_quality_details',
          'environment_details_view_duration','quality_details_view_duration')
EVENT_COLS = ('event_id','participant_id','mode','design_version','source_instance','source_participant_id',
              'task_id','alternative','kind','level','content_version','opened_at','shown_at','updated_at',
              'closed_at','duration_ms','close_reason')

def ensure_task(c,pid,tid):
    for alt in ('A','B'):
        c.execute('INSERT OR IGNORE INTO choice_process (participant_id,task_id,alternative,content_version,tracking_started_at,data_origin) VALUES (?,?,?,?,?,?)',
                  (pid,tid,alt,docs.VERSION,s.now(),'native'))

def metrics(c,pid,tid,alt):
    row=c.execute('SELECT * FROM choice_process WHERE participant_id=? AND task_id=? AND alternative=?',(pid,tid,alt)).fetchone()
    if not row: return dict.fromkeys(FIELDS)
    if row['data_origin']=='import_summary': return {k:row[k] for k in FIELDS}
    result=dict.fromkeys(FIELDS,0)
    for kind,idx in (('environment',0),('quality',1)):
        events=c.execute('SELECT COUNT(*) n,COALESCE(SUM(duration_ms),0) ms FROM detail_views WHERE participant_id=? AND task_id=? AND alternative=? AND kind=? AND shown_at IS NOT NULL',(pid,tid,alt,kind)).fetchone()
        result[FIELDS[idx]]=int(events['n']>0)
        result[FIELDS[idx+2]]=round(events['ms']/1000,3)
    return result

def aggregate(a,b):
    # Unknown legacy exposure stays unknown; it is never recoded as unviewed.
    return {k: (None if a[k] is None or b[k] is None else max(a[k],b[k]) if i<2 else round(a[k]+b[k],3)) for i,k in enumerate(FIELDS)}

def parse_metrics(row,prefix=''):
    values=[row.get(prefix+k,'') for k in FIELDS]
    if not any(v not in ('',None) for v in values): return dict.fromkeys(FIELDS)
    if any(v in ('',None) for v in values): raise ValueError('查看过程变量须同时提供四个字段，或全部留空')
    if any(values[i] not in ('0','1') for i in (0,1)): raise ValueError('是否查看详情须为0/1')
    result={FIELDS[i]:int(values[i]) for i in (0,1)}
    for i in (2,3):
        v=float(values[i])
        if not math.isfinite(v) or not 0<=v<=60*60*24: raise ValueError('详情查看时长不合法，单位为秒')
        if result[FIELDS[i-2]]==0 and v!=0: raise ValueError('未查看详情的时长须为0')
        result[FIELDS[i]]=round(v,3)
    return result

def save_summary(c,pid,tid,alt,values):
    if all(v is None for v in values.values()): return
    version=c.execute('SELECT design_version FROM participants WHERE id=?',(pid,)).fetchone()[0]
    c.execute('INSERT INTO choice_process (participant_id,task_id,alternative,content_version,data_origin,'+','.join(FIELDS)+') VALUES (?,?,?,?,?,?,?,?,?)',
              (pid,tid,alt,registry.get(version).config['detail_content_version'],'import_summary',*(values[k] for k in FIELDS)))

def open_event(c,p,payload):
    if p['design_version']!=s.VERSION:raise ValueError('旧版资料会话只保留历史记录，不混用新版商品资料')
    tid=payload.get('task_id'); alt=payload.get('alternative'); kind=payload.get('kind'); eid=payload.get('event_id')
    if not isinstance(eid,str) or not re.fullmatch(r'[a-f0-9-]{32,36}',eid): raise ValueError('查看事件编号格式错误')
    if alt not in ('A','B') or kind not in ('environment','quality'): raise ValueError('商品或资料类型不合法')
    n=s.count_choices(c,p['id'])
    if not p['attributes_seen_at'] or p['completed_at'] or n>=s.TOTAL or tid!=json.loads(p['task_order'])[n]:
        raise ValueError('只能查看当前尚未提交题目的商品资料')
    if not c.execute('SELECT 1 FROM task_views WHERE participant_id=? AND task_id=?',(p['id'],tid)).fetchone(): raise ValueError('本题尚未展示')
    _,_,a,b=s.offers(p,tid)
    level=(a if alt=='A' else b)['verification' if kind=='environment' else 'quality']
    prior=c.execute('SELECT * FROM detail_views WHERE event_id=?',(eid,)).fetchone()
    if prior:
        if any(prior[k]!=v for k,v in (('participant_id',p['id']),('task_id',tid),('alternative',alt),('kind',kind))): raise ValueError('查看事件编号冲突')
    else:
        if c.execute('SELECT COUNT(*) FROM detail_views WHERE participant_id=? AND task_id=?',(p['id'],tid)).fetchone()[0]>=200:
            raise ValueError('本题详情打开次数过多')
        ensure_task(c,p['id'],tid)
        stamp=s.now()
        c.execute('INSERT INTO detail_views (event_id,participant_id,task_id,alternative,kind,level,content_version,opened_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                  (eid,p['id'],tid,alt,kind,level,docs.VERSION,stamp,stamp))
    return dict(event_id=eid,task_id=tid,alternative=alt,**docs.document(kind,level))

def progress(c,p,payload):
    eid=payload.get('event_id'); duration=payload.get('duration_ms')
    if not isinstance(eid,str) or type(duration) is not int or not 0<=duration<=86400000:
        raise ValueError('查看事件或累计时长不合法')
    if type(payload.get('closed')) is not bool or payload.get('shown') is not True: raise ValueError('查看状态不合法')
    reason=payload.get('reason','heartbeat')
    if reason not in ('heartbeat','close','hidden','pagehide','switch','resume'): raise ValueError('查看状态来源不合法')
    row=c.execute('SELECT * FROM detail_views WHERE event_id=? AND participant_id=?',(eid,p['id'])).fetchone()
    if not row: raise ValueError('查看事件不存在')
    stamp=s.now()
    # Bound client-reported visible time by actual server elapsed time and the
    # task submission boundary. Background time is excluded by the browser.
    end=row['closed_at'] or stamp
    answer=c.execute('SELECT answered_at FROM choices WHERE participant_id=? AND task_id=?',(p['id'],row['task_id'])).fetchone()
    if answer and s.seconds(answer[0],end)>0: end=answer[0]
    ceiling=max(0,round(s.seconds(row['opened_at'],end)*1000))
    duration=max(row['duration_ms'],min(duration,ceiling))
    c.execute('UPDATE detail_views SET shown_at=COALESCE(shown_at,?),updated_at=?,duration_ms=?,closed_at=COALESCE(closed_at,?),close_reason=CASE WHEN closed_at IS NULL THEN ? ELSE close_reason END WHERE event_id=?',
              (stamp,stamp,duration,stamp if payload['closed'] else None,reason if payload['closed'] else '',eid))
    return dict(ok=True,duration_ms=duration)

def event_rows(c,mode,version):
    return [dict(r) for r in c.execute('''SELECT v.*,p.mode,p.design_version,p.source_instance,p.source_participant_id
              FROM detail_views v JOIN participants p ON p.id=v.participant_id
              WHERE p.mode=? AND p.design_version=? ORDER BY v.participant_id,v.opened_at,v.event_id''',(mode,version))]

def validate_import_events(rows,parts,by_input,answers,errors):
    seen=set()
    for p in parts: p['_events']=[]
    for index,row in enumerate(rows,2):
        try:
            p=by_input.get(row.get('participant_id'))
            if not p: raise ValueError('找不到对应参与者')
            for key in ('mode','design_version','source_instance','source_participant_id'):
                if row.get(key)!=p[key]: raise ValueError('过程日志的来源、模式或版本与参与者不一致')
            eid=row.get('event_id','')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',eid): raise ValueError('事件编号不合法')
            key=(p['participant_id'],eid)
            if key in seen: raise ValueError('重复查看事件')
            seen.add(key)
            tid=row.get('task_id'); alt=row.get('alternative'); kind=row.get('kind')
            order=json.loads(p['task_order'])
            if tid not in order or order.index(tid)>int(p['n_choices']): raise ValueError('过程日志的题目未到达或不在本区组')
            if alt not in ('A','B') or kind not in ('environment','quality'): raise ValueError('过程日志的商品或资料类型不合法')
            if row.get('content_version')!=registry.get(p['design_version']).config['detail_content_version']: raise ValueError('详情资料版本与设计不一致，不静默混合')
            _,_,a,b=s.offers(p,tid)
            expected=(a if alt=='A' else b)['verification' if kind=='environment' else 'quality']
            if row.get('level')!=str(expected): raise ValueError('过程日志水平与实际显示商品不一致')
            for field in ('opened_at','shown_at','updated_at','closed_at'):
                s.timestamp(row.get(field),field,field in ('opened_at','updated_at'))
            known=[row[f] for f in ('opened_at','shown_at','closed_at','updated_at') if row.get(f)]
            if any(s.seconds(a0,b0)<0 for a0,b0 in zip(known,known[1:])): raise ValueError('过程日志时间顺序不合法')
            if s.seconds(p['started_at'],row['opened_at'])<0: raise ValueError('打开时间早于参与者开始时间')
            duration=int(row.get('duration_ms',''))
            if duration<0 or duration>86400000 or duration>round(s.seconds(row['opened_at'],row.get('closed_at') or row['updated_at'])*1000):
                raise ValueError('过程日志时长不合法')
            if not row.get('shown_at') and duration: raise ValueError('未确认展示的资料不能记录查看时长')
            answer=answers.get((p['participant_id'],tid))
            if answer and (s.seconds(row['opened_at'],answer['answered_at'])<0 or duration>round(s.seconds(row['opened_at'],answer['answered_at'])*1000)):
                raise ValueError('过程日志超出题目提交范围')
            if row.get('close_reason','') not in ('','close','hidden','pagehide','switch','resume','heartbeat'): raise ValueError('过程日志关闭原因不合法')
            p['_events'].append({**row,'duration_ms':duration,'level':expected})
        except (ValueError,TypeError,KeyError) as exc:
            errors.append(f'detail_views第{index}行：{exc}')
    for p in parts:
        for (pid,tid),answer in answers.items():
            if pid!=p['participant_id']: continue
            for alt in ('A','B'):
                expected=dict.fromkeys(FIELDS,0)
                for event in p['_events']:
                    if event['task_id']==tid and event['alternative']==alt and event.get('shown_at'):
                        idx=0 if event['kind']=='environment' else 1
                        expected[FIELDS[idx]]=1
                        expected[FIELDS[idx+2]]+=event['duration_ms']
                for f in FIELDS[2:]: expected[f]=round(expected[f]/1000,3)
                actual=answer['process'][alt]
                if all(v is None for v in actual.values()) and not any(expected.values()): continue
                if actual!=expected: errors.append(f'{pid}/{tid}/{alt}：逐次详情日志与四项汇总过程变量不一致')

def save_import_events(c,p):
    for row in p.get('_events',[]):
        eid='imp_'+uuid.uuid5(uuid.NAMESPACE_URL,p['_id']+'\x1f'+row['event_id']).hex
        c.execute('INSERT INTO detail_views (event_id,participant_id,task_id,alternative,kind,level,content_version,opened_at,shown_at,updated_at,closed_at,duration_ms,close_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (eid,p['_id'],row['task_id'],row['alternative'],row['kind'],row['level'],row['content_version'],row['opened_at'],row.get('shown_at') or None,row['updated_at'],row.get('closed_at') or None,row['duration_ms'],row.get('close_reason','')))
