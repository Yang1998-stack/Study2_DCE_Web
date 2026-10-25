#!/usr/bin/env python3
"""Study 2 research server. Original SQLite columns and answers are retained."""
import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'app'))
import storage as s
import detail_tracking as dt
import product_details as docs
import quickform_payload as qm
import quickform_sync as qf
import design_registry as registry

ROOT = s.ROOT
MODE = os.getenv('DCE_MODE', 'demo').strip().lower()
if MODE not in s.MODES: raise SystemExit('DCE_MODE须为demo、pilot或formal')
HOST = os.getenv('DCE_HOST', '127.0.0.1')
PORT = int(os.getenv('DCE_PORT', '8000'))
SECURE_COOKIE = os.getenv('DCE_SECURE_COOKIE') == '1'
STUDY = json.loads((ROOT/'config/study_config.json').read_text(encoding='utf-8'))
LOGIN_FAILURES = {}
LOGIN_LOCK = threading.Lock()
ADMIN_CONFIG = None
QF_CONFIG = None

def sync_config():
    return QF_CONFIG or qf.config(MODE)

def images_ready():
    return all(s.stimuli().values())

def password_record(user, password):
    if not user or len(user)>80 or len(password)<12: raise ValueError('账号不能为空，密码至少12个字符')
    salt=secrets.token_bytes(32)
    return dict(user=user,salt=base64.b64encode(salt).decode(),hash=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000).hex())

def load_admin():
    if os.getenv('DCE_ADMIN_PASSWORD'):
        return password_record(os.getenv('DCE_ADMIN_USER','researcher'),os.environ['DCE_ADMIN_PASSWORD'])
    path=s.DATA/'admin_credentials.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

def cookie_value(handler,name):
    try:
        cookie=SimpleCookie(); cookie.load(handler.headers.get('Cookie',''))
        return cookie[name].value if name in cookie else None
    except Exception: return None

def session_row(handler):
    tok=cookie_value(handler,'dce_session')
    if not tok: return None
    with s.db() as c:
        return c.execute('SELECT * FROM participants WHERE token_digest=? AND mode=?',(s.digest(tok.encode()),MODE)).fetchone()

def participant_state(p):
    basic=dict(mode=MODE,images_ready=images_ready(),total=s.TOTAL,study=STUDY,invite_required=MODE=='formal' or os.getenv('DCE_REQUIRE_INVITE')=='1',
               info_descriptions=docs.DESCRIPTIONS,detail_content_version=docs.VERSION,debrief=docs.DEBRIEF,
               product_volume_ml=registry.ACTIVE.volume,volume_label='1 L',design_version=s.VERSION)
    if p is None: return dict(basic,phase='consent')
    if p['design_version']!=s.VERSION:
        return dict(basic,phase='archived',participant_id=p['id'],historical_design_version=p['design_version'])
    with s.db() as c: n=s.count_choices(c,p['id'])
    state=dict(basic,participant_id=p['id'],answered=n)
    if p['completed_at']: return dict(state,phase='done')
    if p['stimulus_end_at'] is None:
        return dict(state,phase='stimulus',image='/static/stimuli/'+('chart' if p['group_code'] in (1,3) else 'nature')+'.jpg',ai_disclosed=p['group_code'] in (3,4))
    if p['attributes_seen_at'] is None: return dict(state,phase='attributes')
    if n>=s.TOTAL: return dict(state,phase='survey')
    tid=json.loads(p['task_order'])[n]
    _,_,a,b=s.offers(p,tid)
    with s.db() as c:
        start=s.now()
        c.execute('INSERT OR IGNORE INTO task_views VALUES (?,?,?)',(p['id'],tid,start))
        dt.ensure_task(c,p['id'],tid)
        qm.snapshot_display(c,p,tid)
        if n==0:
            c.execute('UPDATE participants SET dce_started_at=COALESCE(dce_started_at,?) WHERE id=?',(start,p['id']))
    return dict(state,phase='choice',position=n+1,task_id=tid,a=a,b=b)

class Handler(BaseHTTPRequestHandler):
    server_version='Study2DCE/1.0'
    def log_message(self,*args): pass

    def common_headers(self,ctype):
        self.send_header('Content-Type',ctype)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header('Cache-Control','no-store')
        if SECURE_COOKIE: self.send_header('Strict-Transport-Security','max-age=31536000')

    def send_bytes(self,status,raw,ctype,cookie=None,filename=None):
        self.send_response(status); self.common_headers(ctype)
        self.send_header('Content-Length',str(len(raw)))
        if cookie:
            name,value,age=cookie
            self.send_header('Set-Cookie',f'{name}={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}'+('; Secure' if SECURE_COOKIE else ''))
        if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers()
        try: self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError): pass

    def send_json(self,status,value,cookie=None):
        return self.send_bytes(status,json.dumps(value,ensure_ascii=False).encode(),'application/json; charset=utf-8',cookie)

    def admin_session(self,csrf=False):
        token=cookie_value(self,'dce_admin')
        if not token: return None
        with s.db() as c: row=c.execute('SELECT * FROM admin_sessions WHERE digest=? AND expires>?',(s.digest(token.encode()),s.now())).fetchone()
        if not row or (csrf and not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),row['csrf'])): return None
        return row

    def do_GET(self):
        parsed=urlparse(self.path); route=parsed.path; qs=parse_qs(parsed.query)
        try:
            if route=='/api/state': return self.send_json(200,participant_state(session_row(self)))
            if route=='/api/admin/session':
                a=self.admin_session()
                return self.send_json(200,dict(authenticated=bool(a),configured=bool(ADMIN_CONFIG),csrf=a['csrf'] if a else None,mode=MODE,design_version=s.VERSION,design_versions=list(registry.DESIGNS)))
            if route.startswith('/api/admin/'):
                if not self.admin_session(): return self.send_json(401,{'error':'请先登录研究者后台'})
                mode=qs.get('mode',[MODE])[0]; version=qs.get('design_version',[s.VERSION])[0]
                if route=='/api/admin/stats': return self.send_json(200,s.statistics(mode,version))
                if route=='/api/admin/quickform': return self.send_json(200,qf.status(mode,version,sync_config()))
                if route=='/api/admin/quickform/logs':
                    registry.get(version)
                    if mode not in s.MODES: raise ValueError('数据模式或版本错误')
                    return self.send_bytes(200,qf.logs_csv(mode,version),'text/csv; charset=utf-8',filename=f'quickform_logs_{mode}.csv')
                if route=='/api/admin/quickform/record':
                    pid=qs.get('participant_id',[''])[0]
                    with s.db() as c:
                        row=c.execute('SELECT * FROM qf_submissions WHERE participant_id=?',(pid,)).fetchone()
                        logs=[dict(r) for r in c.execute('SELECT * FROM qf_attempts WHERE participant_id=? ORDER BY attempt_number',(pid,))]
                        actions=[dict(r) for r in c.execute('SELECT * FROM qf_actions WHERE participant_id=? ORDER BY id',(pid,))]
                    if not row: raise ValueError('该参与者没有同步任务')
                    return self.send_json(200,dict(record=dict(row),attempts=logs,actions=actions))
                if route=='/api/admin/export': return self.send_bytes(200,s.export_zip(mode,version),'application/zip',filename=f'study2_{mode}_{version}.zip')
                if route=='/api/admin/imports':
                    with s.db() as c: rows=[dict(r) for r in c.execute('SELECT id,created_at,mode,design_version,status,committed_at,report FROM import_batches ORDER BY created_at DESC LIMIT 100')]
                    return self.send_json(200,{'batches':rows})
            allow={'/':('index.html','text/html; charset=utf-8'),'/admin':('admin.html','text/html; charset=utf-8'),
                '/static/app.js':('app.js','text/javascript; charset=utf-8'),'/static/admin.js':('admin.js','text/javascript; charset=utf-8'),
                '/static/styles.css':('styles.css','text/css; charset=utf-8'),
                '/static/details.js':('details.js','text/javascript; charset=utf-8'),
                '/static/details.css':('details.css','text/css; charset=utf-8'),
                '/static/quickform-admin.js':('quickform-admin.js','text/javascript; charset=utf-8'),
                '/static/stimuli/chart.jpg':('stimuli/chart.jpg','image/jpeg'),'/static/stimuli/nature.jpg':('stimuli/nature.jpg','image/jpeg')}
            if route not in allow: return self.send_json(404,{'error':'Not found'})
            path,ctype=allow[route]
            if not (ROOT/'static'/path).is_file(): return self.send_json(404,{'error':'广告素材未配置'})
            return self.send_bytes(200,(ROOT/'static'/path).read_bytes(),ctype)
        except ValueError as e: return self.send_json(400,{'error':str(e)})

    def read_json(self,limit=65536):
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 2<=length<=limit or self.headers.get('Content-Type','').split(';')[0]!='application/json': raise ValueError()
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError()
            return data
        except (ValueError,UnicodeError): raise ValueError('请求格式或大小错误（普通请求64 KiB，导入总请求最多12 MiB）')

    def do_POST(self):
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc!=self.headers.get('Host'): return self.send_json(403,{'error':'请求来源校验失败'})
        route=urlparse(self.path).path
        try:
            if route=='/api/admin/login': return self.login(self.read_json())
            if route.startswith('/api/admin/'):
                admin=self.admin_session(csrf=True)
                if not admin: return self.send_json(403,{'error':'研究者登录或CSRF校验失败，请重新登录'})
                data=self.read_json(12*1024*1024 if route=='/api/admin/import/preview' else 65536)
                return self.admin_action(route,data,admin)
            data=self.read_json()
            if route=='/api/start': return self.start(data)
            if route=='/api/demo/restart':
                if MODE!='demo': return self.send_json(403,{'error':'仅demo可重新体验'})
                return self.send_json(200,participant_state(None),('dce_session','',0))
            if route=='/api/viewed': return self.viewed()
            if route=='/api/attributes': return self.attributes()
            if route in ('/api/details/open','/api/details/progress'):
                p=session_row(self)
                if p is None: return self.send_json(401,{'error':'请先参与实验'})
                with s.LOCK,s.db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    result=dt.open_event(c,p,data) if route.endswith('/open') else dt.progress(c,p,data)
                return self.send_json(200,result)
            if route=='/api/answer': return self.answer(data)
            if route=='/api/finish': return self.finish_survey(data)
            return self.send_json(404,{'error':'Not found'})
        except ValueError as e: return self.send_json(400,{'error':str(e)})
        except sqlite3.IntegrityError: return self.send_json(409,{'error':'记录已存在或状态冲突，请刷新后重试'})
        except (TypeError,KeyError,OverflowError): return self.send_json(400,{'error':'字段类型或结构不正确'})

    def login(self,data):
        if not ADMIN_CONFIG: return self.send_json(503,{'error':'后台尚未配置。请在服务器运行 python server.py admin-setup'})
        key=self.client_address[0]
        with LOGIN_LOCK:
            attempts=[t for t in LOGIN_FAILURES.get(key,[]) if time.monotonic()-t<900]
            if len(attempts)>=8: return self.send_json(429,{'error':'尝试次数过多，请15分钟后重试'})
            LOGIN_FAILURES[key]=attempts+[time.monotonic()]
        password=data.get('password',''); username=data.get('username','')
        if not isinstance(password,str) or not isinstance(username,str): raise ValueError('账号密码格式错误')
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),base64.b64decode(ADMIN_CONFIG['salt']),600000).hex()
        if not (hmac.compare_digest(username,ADMIN_CONFIG['user']) and hmac.compare_digest(actual,ADMIN_CONFIG['hash'])): return self.send_json(401,{'error':'账号或密码错误'})
        with LOGIN_LOCK: LOGIN_FAILURES.pop(key,None)
        token=secrets.token_urlsafe(40); csrf=secrets.token_urlsafe(32)
        expires=(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat(timespec='milliseconds')
        with s.db() as c:
            c.execute('DELETE FROM admin_sessions WHERE expires<=?',(s.now(),))
            c.execute('INSERT INTO admin_sessions VALUES (?,?,?)',(s.digest(token.encode()),csrf,expires))
        return self.send_json(200,dict(authenticated=True,csrf=csrf,mode=MODE,design_version=s.VERSION,design_versions=list(registry.DESIGNS)),('dce_admin',token,28800))

    def admin_action(self,route,data,admin):
        if route=='/api/admin/quickform/action':
            qf.action(data.get('participant_id'),data.get('action'),data.get('note'),sync_config(),admin['digest'][:12],data.get('decision'),data.get('confirm') is True)
            return self.send_json(200,{'ok':True})
        if route=='/api/admin/logout':
            with s.db() as c: c.execute('DELETE FROM admin_sessions WHERE digest=?',(admin['digest'],))
            return self.send_json(200,{'ok':True},('dce_admin','',0))
        if route=='/api/admin/import/preview': return self.send_json(200,s.preview_import(data,admin['digest']))
        if route=='/api/admin/import/commit':
            if data.get('confirm') is not True: raise ValueError('请核对预览并明确确认')
            return self.send_json(200,s.commit_import(data.get('batch_id'),admin['digest']))
        if route=='/api/admin/review':
            pid=data.get('participant_id'); status=data.get('status'); note=data.get('note','')
            if not isinstance(pid,str): raise ValueError('参与编号格式错误')
            if status not in ('unreviewed','valid','excluded') or not isinstance(note,str) or len(note)>500: raise ValueError('审核状态或备注不合法')
            with s.db() as c:
                p=c.execute('SELECT * FROM participants WHERE id=?',(pid,)).fetchone()
                if not p: raise ValueError('参与者不存在')
                if status=='valid' and (not p['completed_at'] or s.count_choices(c,pid)!=s.TOTAL): raise ValueError('完成8题和后续问卷后才可人工标记有效')
                c.execute('UPDATE participants SET validation_status=? WHERE id=?',(status,pid))
                c.execute('INSERT INTO review_log(participant_id,status,note,reviewed_at) VALUES (?,?,?,?)',(pid,status,note,s.now()))
            return self.send_json(200,{'ok':True})
        if route=='/api/admin/backup': return self.send_json(200,{'backup':s.backup('manual').name})
        if route=='/api/admin/demo':
            if MODE!='demo': return self.send_json(403,{'error':'仅demo可指定实验条件'})
            if data.get('group') not in (1,2,3,4) or data.get('block') not in s.BY_BLOCK: raise ValueError('组别或区组不合法')
            return self.create_participant(data['group'],data['block'],provenance='demo-researcher')
        return self.send_json(404,{'error':'Not found'})

    def start(self,data):
        if MODE=='formal':registry.require_formal()
        existing=session_row(self)
        if existing: return self.send_json(200,participant_state(existing))
        if data.get('consent') is not True or data.get('adult') is not True or data.get('recent_shopping') is not True: raise ValueError('需自愿同意、年满18周岁且最近3个月有线上食品购物经历')
        if 'group' in data or 'block' in data: raise ValueError('普通参与者不能指定实验条件')
        if MODE!='demo' and not images_ready(): raise ValueError('广告素材尚未配置')
        return self.create_participant(invite=data.get('invitation'))

    def create_participant(self,group=None,block=None,invite=None,provenance='live'):
        token=secrets.token_urlsafe(36); pid=str(uuid.uuid4())
        with s.LOCK,s.db() as c:
            c.execute('BEGIN IMMEDIATE')
            invite_digest=None
            if MODE=='formal' or os.getenv('DCE_REQUIRE_INVITE')=='1':
                if not isinstance(invite,str) or not 8<=len(invite)<=128: raise ValueError('请输入有效的一次性邀请码')
                invite_digest=s.digest(invite.strip().encode())
                if not c.execute('SELECT 1 FROM invitations WHERE digest=? AND mode=? AND used_by IS NULL',(invite_digest,MODE)).fetchone(): raise ValueError('邀请码无效或已使用；请用原浏览器恢复，或联系研究者')
            if group is None:
                counts={(r[0],r[1]):r[2] for r in c.execute("SELECT group_code,block,COUNT(*) FROM participants WHERE mode=? AND design_version=? AND source_instance=? AND provenance IN ('live','legacy') GROUP BY group_code,block",(MODE,s.VERSION,s.instance_id()))}
                options=[(g,b) for g in range(1,5) for b in s.BY_BLOCK]
                minimum=min(counts.get(x,0) for x in options)
                group,block=secrets.choice([x for x in options if counts.get(x,0)==minimum])
            swaps=''.join(str(secrets.randbelow(2)) for _ in range(s.TOTAL))
            order=[t['id'] for t in s.BY_BLOCK[block]]; secrets.SystemRandom().shuffle(order)
            start=s.now()
            c.execute('''INSERT INTO participants (id,token_digest,mode,group_code,block,swap_bits,task_order,created_at,design_version,task_hash,source_instance,source_participant_id,stimulus_versions,stimulus_started_at,provenance,consent_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (pid,s.digest(token.encode()),MODE,group,block,swaps,json.dumps(order),start,s.VERSION,s.TASK_HASH,s.instance_id(),pid,json.dumps(s.stimuli()),start,provenance,STUDY['consent_version']))
            if invite_digest: c.execute('UPDATE invitations SET used_by=? WHERE digest=?',(pid,invite_digest))
            p=c.execute('SELECT * FROM participants WHERE id=?',(pid,)).fetchone()
        return self.send_json(200,participant_state(p),('dce_session',token,2592000))

    def viewed(self):
        p=session_row(self)
        if p is None: raise ValueError('请先完成知情同意')
        if p['design_version']!=s.VERSION:raise ValueError('历史设计会话已封存')
        with s.db() as c:
            c.execute('UPDATE participants SET stimulus_end_at=COALESCE(stimulus_end_at,?) WHERE id=?',(s.now(),p['id']))
            p=c.execute('SELECT * FROM participants WHERE id=?',(p['id'],)).fetchone()
        return self.send_json(200,participant_state(p))

    def attributes(self):
        p=session_row(self)
        if p is None or not p['stimulus_end_at']: raise ValueError('请先浏览广告')
        if p['design_version']!=s.VERSION:raise ValueError('历史设计会话已封存')
        with s.db() as c:
            c.execute('UPDATE participants SET attributes_seen_at=COALESCE(attributes_seen_at,?) WHERE id=?',(s.now(),p['id']))
            p=c.execute('SELECT * FROM participants WHERE id=?',(p['id'],)).fetchone()
        return self.send_json(200,participant_state(p))

    def answer(self,data):
        p=session_row(self)
        if p is None or p['design_version']!=s.VERSION or not p['attributes_seen_at'] or p['completed_at']: raise ValueError('实验阶段或设计版本不正确')
        if MODE=='formal':registry.require_formal()
        answer=data.get('choice'); tid=data.get('task_id')
        if answer not in ('A','B','N') or not isinstance(tid,str): raise ValueError('请选择A、B或暂时不购买')
        with s.LOCK,s.db() as c:
            c.execute('BEGIN IMMEDIATE')
            prior=c.execute('SELECT * FROM choices WHERE participant_id=? AND task_id=?',(p['id'],tid)).fetchone()
            if prior:
                if prior['displayed_choice']!=answer: raise ValueError('本题已提交其他选择，不能覆盖；请刷新恢复进度')
            else:
                n=s.count_choices(c,p['id'])
                if n>=s.TOTAL or tid!=json.loads(p['task_order'])[n]: raise ValueError('题目顺序不一致，请刷新恢复进度')
                if not c.execute('SELECT 1 FROM task_views WHERE participant_id=? AND task_id=?',(p['id'],tid)).fetchone(): raise ValueError('尚未展示本题')
                stamp=s.now(); c.execute('INSERT INTO choices VALUES (?,?,?,?)',(p['id'],tid,answer,stamp))
                if n+1==s.TOTAL: c.execute('UPDATE participants SET dce_completed_at=? WHERE id=?',(stamp,p['id']))
            p=c.execute('SELECT * FROM participants WHERE id=?',(p['id'],)).fetchone()
        return self.send_json(200,participant_state(p))

    def finish_survey(self,data):
        p=session_row(self)
        if p is None: raise ValueError('请先参与实验')
        if p['design_version']!=s.VERSION:raise ValueError('旧设计记录已保存，不能作为新版答卷继续提交')
        if MODE=='formal':registry.require_formal()
        if p['completed_at']: return self.send_json(200,participant_state(p))
        age=data.get('age')
        if isinstance(age,bool) or not str(age).isdigit() or not 18<=int(age)<=100: raise ValueError('请输入18至100之间的整数年龄')
        if any(data.get(k) not in values for k,values in s.SURVEY.items()): raise ValueError('请填写全部后续问题')
        extra=qm.validate_extensions(data.get('additional_answers',{}))
        cfg=sync_config(); queued=False
        with s.LOCK,s.db() as c:
            c.execute('BEGIN IMMEDIATE')
            p=c.execute('SELECT * FROM participants WHERE id=?',(p['id'],)).fetchone()
            if p['completed_at']: return self.send_json(200,participant_state(p))
            if s.count_choices(c,p['id'])!=s.TOTAL: raise ValueError('请先完成全部8道题')
            c.execute('UPDATE participants SET completed_at=?,age=?,gender=?,education=?,online_purchase=?,plant_based_purchase=?,manip_visual=?,manip_ai=? WHERE id=? AND completed_at IS NULL',(s.now(),int(age),*(data[k] for k in s.SURVEY),p['id']))
            p=c.execute('SELECT * FROM participants WHERE id=?',(p['id'],)).fetchone()
            for key,value in extra.items():
                c.execute('INSERT INTO questionnaire_answers VALUES (?,?,?)',(p['id'],key,json.dumps(value,ensure_ascii=False,allow_nan=False)))
            queued=qf.enqueue(c,p,cfg)
        # Local completion and immutable outbox are already committed. A failed
        # network call cannot roll back answers or require the consumer to repeat.
        if queued:
            try: qf.dispatch_once(cfg,p['id'],initial=True)
            except Exception as exc: print('答卷已保存在本地；同步需研究者核查：',type(exc).__name__,flush=True)
            qf.WAKE.set()
        return self.send_json(200,participant_state(p))

@contextmanager
def exclusive_server_lock():
    path=s.DATA/'server.lock'; f=path.open('a+b')
    if path.stat().st_size==0: f.write(b'0'); f.flush()
    f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        f.close(); raise SystemExit('该数据库已有服务运行。恢复前请先停止服务。')
    try: yield
    finally: f.close()

def backup_loop(stop):
    interval=max(60,int(os.getenv('DCE_BACKUP_INTERVAL_SECONDS','21600')))
    while not stop.wait(interval):
        try: s.backup()
        except Exception as e: print('定期备份失败，请检查磁盘和权限：',type(e).__name__,flush=True)

def main():
    global ADMIN_CONFIG,QF_CONFIG
    parser=argparse.ArgumentParser(description='Study2研究平台')
    parser.add_argument('command',nargs='?',choices=['serve','export','admin-setup','backup','restore','invitations','quickform-status','quickform-sync','quickform-retry','quickform-logs'],default='serve')
    parser.add_argument('--file'); parser.add_argument('--confirm',action='store_true'); parser.add_argument('--count',type=int,default=20)
    parser.add_argument('--participant-id');parser.add_argument('--note')
    parser.add_argument('--design-version',default=s.VERSION,choices=list(registry.DESIGNS))
    args=parser.parse_args(); s.init_db()
    QF_CONFIG=qf.config(MODE)
    if args.command=='quickform-status':
        print(json.dumps(qf.status(MODE,args.design_version,QF_CONFIG),ensure_ascii=False,indent=2));return
    if args.command=='quickform-logs':
        target=ROOT/'exports'/f'quickform_logs_{MODE}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}.csv';target.parent.mkdir(exist_ok=True)
        target.write_bytes(qf.logs_csv(MODE,args.design_version));print(target);return
    if args.command in ('quickform-sync','quickform-retry'):
        with exclusive_server_lock():
            qf.recover_inflight()
            if args.command=='quickform-retry':
                if not args.participant_id: args.participant_id=input('明确失败记录的本地participant_id：').strip()
                if not args.note: args.note=input('核查/修复原因（至少5字）：').strip()
                qf.action(args.participant_id,'retry',args.note,QF_CONFIG,'local_cli')
            count=0
            while qf.dispatch_once(QF_CONFIG,args.participant_id): count+=1
            print('本次处理到期同步任务：',count,'；不确定记录不会自动重发。')
        return
    if args.command=='admin-setup':
        with exclusive_server_lock():
            user=input('研究者账号：').strip(); password=getpass.getpass('密码（至少12字符）：')
            if password!=getpass.getpass('再次输入密码：'): raise SystemExit('两次密码不一致')
            (s.DATA/'admin_credentials.json').write_text(json.dumps(password_record(user,password)),encoding='utf-8')
            with s.db() as c: c.execute('DELETE FROM admin_sessions')
        print('账号已保存为加盐密码哈希。'); return
    if args.command=='export':
        folder=ROOT/'exports'/f'{MODE}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}'; folder.mkdir(parents=True)
        for name,raw in s.export_files(MODE,args.design_version).items(): (folder/name).write_bytes(raw)
        print(folder); return
    if args.command=='backup': print(s.backup('manual')); return
    if args.command=='restore':
        if not args.file or not args.confirm: raise SystemExit('停止服务后使用 restore --file 备份路径 --confirm')
        source=Path(args.file).resolve()
        if source==s.DB.resolve() or not source.is_file(): raise SystemExit('备份路径不合法')
        with exclusive_server_lock(),closing(sqlite3.connect(f'{source.as_uri()}?mode=ro',uri=True)) as src:
            if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise SystemExit('备份完整性检查失败')
            if not {'id','token_digest','mode','task_order'}<={r[1] for r in src.execute('PRAGMA table_info(participants)')}: raise SystemExit('不是本平台数据库')
            s.backup('before_restore')
            with closing(s.connect()) as dst: src.backup(dst)
        print('备份已恢复；原数据库另行备份。请重新启动执行兼容迁移。'); return
    if args.command=='invitations':
        if not 1<=args.count<=10000: raise SystemExit('数量须在1至10000之间')
        tokens=[secrets.token_urlsafe(18) for _ in range(args.count)]; file=s.DATA/f'invitations_{MODE}_{secrets.token_hex(4)}.txt'
        with s.db() as c: c.executemany('INSERT INTO invitations(digest,mode,created_at) VALUES (?,?,?)',[(s.digest(t.encode()),MODE,s.now()) for t in tokens])
        file.write_text('\n'.join(tokens),encoding='utf-8'); print('邀请码请仅向授权招募者提供：',file); return
    ADMIN_CONFIG=load_admin()
    if MODE=='formal':
        if not registry.formal_allowed():raise SystemExit('新版1 L设计尚未获得用户确认及预测试完成记录，formal收数锁定')
        if os.getenv('DCE_ALLOW_FORMAL')!='YES' or not STUDY.get('ready_for_formal') or any('待研究团队填写' in STUDY.get(k,'') for k in ('researcher_contact','retention','withdrawal')): raise SystemExit('先完成config/study_config.json，设置ready_for_formal=true和DCE_ALLOW_FORMAL=YES')
        if not SECURE_COOKIE or not ADMIN_CONFIG or not images_ready(): raise SystemExit('正式模式需要HTTPS安全Cookie、后台账号和完整素材')
    with exclusive_server_lock():
        s.backup('startup'); stop=threading.Event(); threading.Thread(target=backup_loop,args=(stop,),daemon=True).start()
        qf.recover_inflight()
        if QF_CONFIG.enabled: threading.Thread(target=qf.worker,args=(stop,QF_CONFIG),daemon=True,name='quickform-worker').start()
        print(f'Study2 DCE [{MODE}] http://{HOST}:{PORT}  研究者后台 /admin',flush=True)
        print('QuickForm：'+QF_CONFIG.reason,flush=True)
        if not ADMIN_CONFIG: print('后台未设置账号：先停止服务，运行 python server.py admin-setup',flush=True)
        try:
            with ThreadingHTTPServer((HOST,PORT),Handler) as http: http.serve_forever()
        except KeyboardInterrupt: pass
        finally: stop.set()

if __name__=='__main__': main()
