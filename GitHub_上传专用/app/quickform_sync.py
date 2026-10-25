"""Durable completion outbox; no remote writes at import, migration or export time."""
import errno
import json
import os
import re
import secrets
import socket
import ssl
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from urllib.parse import urlsplit,urlunsplit,unquote
import storage as s
import quickform_payload as mapping
import design_registry as registry

DEFAULT_API_URL='https://quickform.cn/api/kajm9wjasx'
# Keep previously designated formal tasks out of the pilot channel as well.
FORMAL_TASK_PATHS=frozenset(('/api/kajm9wjasx','/api/9lnrb0a8hn'))
WAKE=threading.Event()
STATES=('pending','success','failed','uncertain')

def canonical_url(url,local_test=False):
    parsed=urlsplit(url)
    host=(parsed.hostname or '').lower().rstrip('.')
    path=unquote(parsed.path).rstrip('/')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not host or not re.fullmatch(r'/api/[A-Za-z0-9_-]+',path):
        raise ValueError('QuickForm地址必须是不带账号、参数的/api/<任务编号>接口')
    if local_test:
        if host not in ('127.0.0.1','localhost','::1') or parsed.scheme not in ('http','https'):
            raise ValueError('本地测试开关只允许环回模拟接口，禁止真实QuickForm写入')
    elif parsed.scheme!='https': raise ValueError('外部QuickForm接口必须使用HTTPS')
    port=parsed.port
    netloc=('['+host+']' if ':' in host else host)+(f':{port}' if port and not (parsed.scheme=='https' and port==443) else '')
    return urlunsplit((parsed.scheme.lower(),netloc,path,'',''))

@dataclass(frozen=True)
class Config:
    mode:str
    target:str|None
    enabled:bool
    reason:str
    timeout:float=8
    max_attempts:int=3
    backoff:int=10

def config(mode):
    local=os.getenv('QUICKFORM_ALLOW_LOCAL_TEST')=='YES'
    formal=canonical_url(os.getenv('QUICKFORM_API_URL',DEFAULT_API_URL).strip(),local)
    pilot_raw=os.getenv('QUICKFORM_PILOT_API_URL','').strip()
    pilot=canonical_url(pilot_raw,local) if pilot_raw else None
    # Different domains/URL spelling must not disguise the formal task as pilot.
    if pilot and (pilot==formal or urlsplit(pilot).path==urlsplit(formal).path or urlsplit(pilot).path in FORMAL_TASK_PATHS):
        raise ValueError('pilot必须使用独立收集任务，不能指向formal任务')
    target=formal if mode=='formal' else pilot if mode=='pilot' else None
    enabled=(mode=='formal' and os.getenv('QUICKFORM_FORMAL_ENABLED')=='YES' and os.getenv('DCE_ALLOW_FORMAL')=='YES' or
             mode=='pilot' and os.getenv('QUICKFORM_PILOT_ENABLED')=='YES' and bool(pilot))
    reason='已显式启用' if enabled else 'demo永不上传' if mode=='demo' else '尚未显式启用或未设置独立接口'
    if mode=='formal' and not registry.formal_allowed():
        enabled=False;reason='新版设计尚未确认且未完成预测试，正式同步锁定'
    timeout=float(os.getenv('QUICKFORM_TIMEOUT_SECONDS','8'))
    attempts=int(os.getenv('QUICKFORM_MAX_ATTEMPTS','3')); backoff=int(os.getenv('QUICKFORM_BACKOFF_SECONDS','10'))
    if not 0.1<=timeout<=30 or not 1<=attempts<=5 or not 1<=backoff<=3600: raise ValueError('同步超时/重试配置超出允许范围')
    return Config(mode,target,bool(enabled),reason,timeout,attempts,backoff)

def init_schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS choice_display_snapshots (
      participant_id TEXT NOT NULL REFERENCES participants(id),task_id TEXT NOT NULL,
      a_json TEXT NOT NULL,b_json TEXT NOT NULL,content_version TEXT NOT NULL,created_at TEXT NOT NULL,
      PRIMARY KEY(participant_id,task_id)
    );
    CREATE TABLE IF NOT EXISTS choice_products (
      participant_id TEXT NOT NULL REFERENCES participants(id),task_id TEXT NOT NULL,
      alternative TEXT NOT NULL CHECK(alternative IN ('A','B')),design_version TEXT NOT NULL,
      origin_import INTEGER NOT NULL,third_party_verification INTEGER NOT NULL,batch_quality_report INTEGER NOT NULL,
      price_yuan INTEGER NOT NULL,price_level INTEGER NOT NULL,product_volume_ml INTEGER NOT NULL,
      display_started_at TEXT,PRIMARY KEY(participant_id,task_id,alternative)
    );
    CREATE TABLE IF NOT EXISTS questionnaire_answers (
      participant_id TEXT NOT NULL REFERENCES participants(id),field_name TEXT NOT NULL,answer_json TEXT NOT NULL,
      PRIMARY KEY(participant_id,field_name)
    );
    CREATE TABLE IF NOT EXISTS qf_submissions (
      participant_id TEXT PRIMARY KEY REFERENCES participants(id),submission_uuid TEXT NOT NULL UNIQUE,
      survey_mode TEXT NOT NULL,design_version TEXT NOT NULL,target_url TEXT,payload_json TEXT NOT NULL,
      payload_sha256 TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('pending','success','failed','uncertain')),
      attempt_count INTEGER NOT NULL DEFAULT 0,cycle_attempts INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,updated_at TEXT NOT NULL,next_attempt_at TEXT,last_attempt_at TEXT,
      success_at TEXT,last_http_status INTEGER,last_error TEXT,in_flight_token TEXT,in_flight_at TEXT,
      confirmation TEXT,retryable INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_qf_due ON qf_submissions(status,survey_mode,next_attempt_at);
    CREATE TABLE IF NOT EXISTS qf_attempts (
      id INTEGER PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES qf_submissions(participant_id),
      attempt_number INTEGER NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,http_status INTEGER,
      outcome TEXT NOT NULL,error_summary TEXT,response_summary TEXT,payload_sha256 TEXT NOT NULL,
      UNIQUE(participant_id,attempt_number)
    );
    CREATE TABLE IF NOT EXISTS qf_actions (
      id INTEGER PRIMARY KEY,participant_id TEXT,action TEXT NOT NULL,note TEXT NOT NULL,
      created_at TEXT NOT NULL,actor TEXT NOT NULL
    );
    ''')
    # Keep the earlier outbox intact. Ambiguous legacy 'sent' was not a strict
    # persistence ACK; migrate references as uncertain, never silently resend.
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='quickform_outbox'").fetchone():
        for row in c.execute('SELECT o.*,p.mode,p.design_version FROM quickform_outbox o JOIN participants p ON p.id=o.participant_id').fetchall():
            raw=row['payload_json']; stamp=s.now()
            c.execute('''INSERT OR IGNORE INTO qf_submissions
              (participant_id,submission_uuid,survey_mode,design_version,payload_json,payload_sha256,status,attempt_count,created_at,updated_at,last_attempt_at,last_error,confirmation)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (row['participant_id'],str(__import__('uuid').uuid5(__import__('uuid').NAMESPACE_URL,'legacy-qf:'+row['participant_id'])),
               row['mode'],row['design_version'],raw,s.digest(raw.encode()),'uncertain',row['attempts'],stamp,stamp,row['last_attempt_at'],
               '旧同步逻辑的结果及目标接口需核查；原始队列完整保留，不自动重发','legacy_unverified'))

def later(seconds):
    return (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat(timespec='milliseconds')

def enqueue(c,p,cfg):
    if p['mode']=='demo': return False
    if p['mode']!=cfg.mode: raise ValueError('答卷模式与同步配置不一致')
    if p['design_version']!=s.VERSION:raise ValueError('旧设计答卷不新建新版同步任务，历史队列保持原状')
    if p['mode']=='formal':registry.require_formal(p['design_version'])
    if p['provenance'].startswith('import:'): raise ValueError('导入答卷不自动再次上传，避免跨实例重复收集')
    payload=mapping.build(c,p)
    raw=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    stamp=s.now()
    cur=c.execute('''INSERT OR IGNORE INTO qf_submissions
      (participant_id,submission_uuid,survey_mode,design_version,target_url,payload_json,payload_sha256,status,created_at,updated_at,next_attempt_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(p['id'],payload['participant_id'],p['mode'],p['design_version'],cfg.target,raw,s.digest(raw.encode()),'pending',stamp,stamp,later(30)))
    return cur.rowcount==1

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def classify(code,body):
    try: result=json.loads(body)
    except (ValueError,UnicodeError): result=None
    summary={k:result[k] for k in ('status','queued','spool_id','retry_after','message') if isinstance(result,dict) and k in result and isinstance(result[k],(str,int,float,bool,type(None)))}
    summary={k:(v[:300] if isinstance(v,str) else v) for k,v in summary.items()}
    text=json.dumps(summary,ensure_ascii=False,separators=(',',':')) if summary else '无可识别JSON确认'
    if code==200 and isinstance(result,dict) and result.get('status')=='success' and result.get('queued') is not True:
        return 'success',False,'',text
    if code==202 or isinstance(result,dict) and result.get('queued') is True:
        return 'uncertain',False,'远端仅确认排队，尚未确认持久化；请核查',text
    if code in (408,409) or code>=500 and not (code==503 and isinstance(result,dict) and 'retry_after' in result):
        return 'uncertain',False,f'HTTP {code}，无法确定是否已持久化',text
    if code==429 or code==503 and isinstance(result,dict) and 'retry_after' in result:
        return 'failed',True,f'HTTP {code}明确拒绝/繁忙，允许有限重试',text
    if 400<=code<500:
        return 'failed',False,f'HTTP {code}明确拒绝，请修正原因后手动重试',text
    if code==200 and isinstance(result,dict) and result.get('status') in ('error','failed','failure'):
        return 'failed',False,'远端明确返回失败，请核查原因',text
    return 'uncertain',False,f'HTTP {code}没有约定的持久化成功确认',text

def send(target,raw,cfg):
    # Validate again immediately before transport; no redirects or alternate host.
    canonical_url(target,os.getenv('QUICKFORM_ALLOW_LOCAL_TEST')=='YES')
    request=urllib.request.Request(target,data=raw.encode('utf-8'),headers={'Content-Type':'application/json; charset=utf-8','Accept':'application/json','User-Agent':'Study2-DCE-QuickForm/2.0'},method='POST')
    handlers=[NoRedirect()]
    if os.getenv('QUICKFORM_ALLOW_LOCAL_TEST')=='YES': handlers.append(urllib.request.ProxyHandler({}))
    opener=urllib.request.build_opener(*handlers)
    code=None
    try:
        try: response=opener.open(request,timeout=cfg.timeout)
        except urllib.error.HTTPError as exc: response=exc
        with response:
            code=response.code; body=response.read(65537); retry_header=response.headers.get('Retry-After','')
        if len(body)>65536: return 'uncertain',False,'响应超过64 KiB，未确认持久化',code,''
        status,retryable,error,summary=classify(code,body)
        if retryable and retry_header.isdigit():
            try: detail=json.loads(summary)
            except ValueError: detail={}
            detail['retry_after']=max(int(retry_header),int(detail.get('retry_after',0)))
            summary=json.dumps(detail,ensure_ascii=False,separators=(',',':'))
        return status,retryable,error,code,summary
    except urllib.error.URLError as exc:
        reason=exc.reason
        if isinstance(reason,(ConnectionRefusedError,socket.gaierror,ssl.SSLCertVerificationError)) or getattr(reason,'errno',None)==errno.ECONNREFUSED:
            return 'failed',not isinstance(reason,ssl.SSLCertVerificationError),'连接未建立：'+type(reason).__name__,code,''
        return 'uncertain',False,'网络结果不明确：'+type(reason).__name__,code,''
    except Exception as exc:
        return 'uncertain',False,'请求中断或超时：'+type(exc).__name__,code,''

def dispatch_once(cfg,pid=None,initial=False):
    if not cfg.enabled or cfg.mode=='demo' or not cfg.target: return False
    if cfg.mode=='formal' and not registry.formal_allowed():return False
    token=secrets.token_hex(16)
    with s.LOCK,s.db() as c:
        c.execute('BEGIN IMMEDIATE')
        query="SELECT * FROM qf_submissions WHERE status='pending' AND in_flight_token IS NULL AND survey_mode=? AND target_url=? AND design_version=?"
        args=[cfg.mode,cfg.target,s.VERSION]
        if pid: query+=' AND participant_id=?';args.append(pid)
        if not initial: query+=' AND next_attempt_at<=?';args.append(s.now())
        else: query+=' AND attempt_count=0'
        query+=' ORDER BY next_attempt_at,created_at LIMIT 1'
        row=c.execute(query,args).fetchone()
        if row is None: return False
        stamp=s.now(); attempt=row['attempt_count']+1
        c.execute('UPDATE qf_submissions SET in_flight_token=?,in_flight_at=?,last_attempt_at=?,attempt_count=?,cycle_attempts=cycle_attempts+1,updated_at=? WHERE participant_id=?',(token,stamp,stamp,attempt,stamp,row['participant_id']))
        c.execute('INSERT INTO qf_attempts(participant_id,attempt_number,started_at,outcome,payload_sha256) VALUES (?,?,?,?,?)',(row['participant_id'],attempt,stamp,'in_flight',row['payload_sha256']))
    if s.digest(row['payload_json'].encode())!=row['payload_sha256']:
        outcome=('failed',False,'待发快照哈希不一致，已阻止发送',None,'')
    else: outcome=send(row['target_url'],row['payload_json'],cfg)
    status,retryable,error,http_status,response_summary=outcome
    with s.LOCK,s.db() as c:
        c.execute('BEGIN IMMEDIATE')
        current=c.execute('SELECT * FROM qf_submissions WHERE participant_id=? AND in_flight_token=?',(row['participant_id'],token)).fetchone()
        if not current: return True
        final=status; due=None
        if status=='failed' and retryable and current['cycle_attempts']<cfg.max_attempts:
            try: advised=float(json.loads(response_summary).get('retry_after',0))
            except (ValueError,TypeError): advised=0
            delay=max(cfg.backoff*4**(current['cycle_attempts']-1),min(max(advised,0),86400))
            final='pending'; due=later(delay)
        stamp=s.now()
        c.execute('''UPDATE qf_submissions SET status=?,updated_at=?,next_attempt_at=?,success_at=?,last_http_status=?,last_error=?,
                     in_flight_token=NULL,in_flight_at=NULL,confirmation=?,retryable=? WHERE participant_id=?''',
                  (final,stamp,due,stamp if status=='success' else None,http_status,error or None,'http_200_status_success' if status=='success' else None,int(retryable),row['participant_id']))
        c.execute('UPDATE qf_attempts SET finished_at=?,http_status=?,outcome=?,error_summary=?,response_summary=? WHERE participant_id=? AND attempt_number=?',
                  (stamp,http_status,status,error or None,response_summary,row['participant_id'],attempt))
    return True

def recover_inflight():
    with s.LOCK,s.db() as c:
        c.execute('BEGIN IMMEDIATE'); stamp=s.now()
        rows=c.execute('SELECT participant_id FROM qf_submissions WHERE in_flight_token IS NOT NULL').fetchall()
        for row in rows:
            c.execute("UPDATE qf_submissions SET status='uncertain',last_error=?,updated_at=?,next_attempt_at=NULL,in_flight_token=NULL,in_flight_at=NULL WHERE participant_id=?",('上次进程在发送期间中断；可能已被远端接收，禁止自动重发',stamp,row['participant_id']))
            c.execute("UPDATE qf_attempts SET outcome='uncertain',finished_at=?,error_summary=? WHERE participant_id=? AND outcome='in_flight'",(stamp,'发送期间进程中断',row['participant_id']))

def worker(stop,cfg):
    while not stop.is_set():
        try: handled=dispatch_once(cfg)
        except Exception as exc:
            print('QuickForm队列处理失败（本地原始答卷保留）：',type(exc).__name__,flush=True);handled=False
        if handled: continue
        WAKE.wait(2);WAKE.clear()

def status(mode,version,cfg):
    registry.get(version)
    if mode not in s.MODES: raise ValueError('数据模式或设计版本错误')
    with s.db() as c:
        c.execute('BEGIN')
        total=c.execute('SELECT COUNT(*) FROM participants WHERE mode=? AND design_version=? AND completed_at IS NOT NULL',(mode,version)).fetchone()[0]
        rows=[dict(r) for r in c.execute('''SELECT p.id participant_id,q.submission_uuid,p.mode,p.group_code,p.block,p.completed_at,q.status,q.attempt_count,
                 q.last_attempt_at,q.success_at,q.last_http_status,q.last_error,q.next_attempt_at,q.in_flight_at,q.target_url,q.confirmation,q.payload_sha256
                 FROM participants p LEFT JOIN qf_submissions q ON p.id=q.participant_id
                 WHERE p.mode=? AND p.design_version=? AND p.completed_at IS NOT NULL ORDER BY p.completed_at DESC,p.id''',(mode,version))]
        counts={state:sum(r['status']==state for r in rows) for state in STATES}
        last=c.execute('SELECT MAX(last_attempt_at) FROM qf_submissions WHERE survey_mode=? AND design_version=?',(mode,version)).fetchone()[0]
    return dict(completed_local=total,counts=counts,not_enqueued=sum(r['status'] is None for r in rows),last_sync_at=last,rows=rows,
                enabled=cfg.enabled and mode==cfg.mode and version==s.VERSION,configuration_mode=cfg.mode,configuration_reason=cfg.reason,
                target=cfg.target if mode==cfg.mode else None,max_attempts=cfg.max_attempts,
                note='demo不上传；导入/历史答卷不自动补发。超时、202排队及中断需核查；UUID不能保证远端绝对不重复。')

def action(pid,action_name,note,cfg,actor,decision=None,confirm=False):
    if not isinstance(pid,str) or not isinstance(note,str) or not 5<=len(note.strip())<=500: raise ValueError('请填写参与编号及至少5字的操作/核查说明')
    with s.LOCK,s.db() as c:
        c.execute('BEGIN IMMEDIATE')
        p=c.execute('SELECT * FROM participants WHERE id=?',(pid,)).fetchone()
        if not p or p['mode']!=cfg.mode or p['mode']=='demo': raise ValueError('只能管理当前服务模式中的非demo答卷')
        row=c.execute('SELECT * FROM qf_submissions WHERE participant_id=?',(pid,)).fetchone()
        if action_name=='enqueue':
            if row: raise ValueError('已存在同步任务，不能重复建单')
            if not cfg.enabled: raise ValueError('请先显式启用该模式的独立接口')
            enqueue(c,p,cfg)
        else:
            if not row or row['in_flight_token']: raise ValueError('记录不存在或仍在同步中')
            if action_name=='retry':
                if row['status'] not in ('failed','pending'): raise ValueError('只允许重试明确失败/未发送记录；不确定状态须先核查')
                if row['status']=='pending' and row['attempt_count']>0: raise ValueError('已安排退避重试，请等待；不能绕过间隔')
                if not cfg.enabled or row['target_url'] not in (None,cfg.target): raise ValueError('接口未显式启用或目标与原队列不一致')
                c.execute("UPDATE qf_submissions SET status='pending',cycle_attempts=0,next_attempt_at=?,updated_at=?,target_url=COALESCE(target_url,?),last_error=NULL WHERE participant_id=?",(s.now(),s.now(),cfg.target,pid))
            elif action_name=='review':
                if row['status']!='uncertain' or not confirm: raise ValueError('仅对不确定状态执行明确的人工核查确认')
                if decision=='received':
                    c.execute("UPDATE qf_submissions SET status='success',confirmation='researcher_review',success_at=?,updated_at=?,last_error=NULL WHERE participant_id=?",(s.now(),s.now(),pid))
                elif decision=='not_received':
                    if not cfg.enabled or row['target_url']!=cfg.target: raise ValueError('未启用原目标接口，不能重发')
                    c.execute("UPDATE qf_submissions SET status='pending',cycle_attempts=0,next_attempt_at=?,updated_at=?,last_error=NULL WHERE participant_id=?",(s.now(),s.now(),pid))
                else: raise ValueError('请选择已核实收到或已核实未收到')
            else: raise ValueError('不支持的操作')
        c.execute('INSERT INTO qf_actions(participant_id,action,note,created_at,actor) VALUES (?,?,?,?,?)',(pid,action_name+(':'+str(decision) if decision else ''),note.strip(),s.now(),actor))
    WAKE.set()

def logs_csv(mode,version):
    with s.db() as c:
        rows=[dict(r) for r in c.execute('''SELECT a.*,q.submission_uuid,q.survey_mode,q.design_version FROM qf_attempts a
            JOIN qf_submissions q ON a.participant_id=q.participant_id WHERE q.survey_mode=? AND q.design_version=? ORDER BY a.id''',(mode,version))]
    cols=['id','participant_id','submission_uuid','survey_mode','design_version','attempt_number','started_at','finished_at','http_status','outcome','error_summary','response_summary','payload_sha256']
    return s.csv_bytes(cols,rows)
