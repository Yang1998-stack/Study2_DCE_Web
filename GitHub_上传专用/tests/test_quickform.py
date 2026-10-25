"""All writes go to loopback mock servers. Never sends a real QuickForm request."""
from collections import deque
from contextlib import closing
import copy
import csv
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import storage as s
import server
import quickform_sync as qf
import quickform_payload as qm
from test_platform import Client,SURVEY,PASSWORD

class Mock(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
        with self.server.mutex:
            self.server.posts.append(dict(path=self.path,raw=raw,headers=dict(self.headers)))
            plan=self.server.plans.popleft() if self.server.plans else dict(code=200,body={'status':'success','message':'提交成功'})
        if plan.get('delay'): time.sleep(plan['delay'])
        if plan.get('disconnect'):
            self.close_connection=True;return
        body=plan.get('body',{})
        raw=body.encode() if isinstance(body,str) else json.dumps(body,ensure_ascii=False).encode()
        self.send_response(plan.get('code',200));self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
        if plan.get('retry_after'):self.send_header('Retry-After',str(plan['retry_after']))
        self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

class QuickForm(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='study2-qf-test-')
        self.folder=Path(self.temp.name)
        self.mock=ThreadingHTTPServer(('127.0.0.1',0),Mock);self.mock.posts=[];self.mock.plans=deque();self.mock.mutex=threading.Lock()
        self.mock_thread=threading.Thread(target=self.mock.serve_forever,daemon=True);self.mock_thread.start()
        self.url=f'http://127.0.0.1:{self.mock.server_port}'
        self.env=patch.dict(os.environ,dict(QUICKFORM_API_URL=self.url+'/api/formal',QUICKFORM_PILOT_API_URL=self.url+'/api/pilot',
             QUICKFORM_ALLOW_LOCAL_TEST='YES',QUICKFORM_FORMAL_ENABLED='YES',QUICKFORM_PILOT_ENABLED='YES',DCE_ALLOW_FORMAL='YES',
             QUICKFORM_TIMEOUT_SECONDS='0.18',QUICKFORM_BACKOFF_SECONDS='1',QUICKFORM_MAX_ATTEMPTS='3'))
        self.env.start()
        self.approval_patch=patch('design_registry.formal_allowed',return_value=True);self.approval_patch.start()
        self.data_patch=patch.multiple(s,DATA=self.folder,DB=self.folder/'study2.sqlite3');self.data_patch.start();s.init_db()
        self.cfg=qf.config('formal')
        self.server_patch=patch.multiple(server,MODE='formal',QF_CONFIG=self.cfg,SECURE_COOKIE=False,ADMIN_CONFIG=server.password_record('researcher',PASSWORD));self.server_patch.start()
        # Exercise the real HTTP handlers. Production startup guards remain
        # intact; this fixture deliberately instantiates them on loopback only.
        self.app=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.app_thread=threading.Thread(target=self.app.serve_forever,daemon=True);self.app_thread.start()
        self.base=f'http://127.0.0.1:{self.app.server_port}'
        self.client=Client(self.base);self.admin=Client(self.base);self.admin.login()
    def tearDown(self):
        self.app.shutdown();self.app.server_close();self.app_thread.join(2)
        self.mock.shutdown();self.mock.server_close();self.mock_thread.join(2)
        self.server_patch.stop();self.data_patch.stop();self.env.stop();self.approval_patch.stop();self.temp.cleanup()
    def rows(self,query,args=()):
        with s.db() as c:return [dict(r) for r in c.execute(query,args)]
    def participant(self,swaps='01010101'):
        token='test-invite-'+uuid.uuid4().hex
        with s.db() as c:c.execute('INSERT INTO invitations(digest,mode,created_at) VALUES (?,?,?)',(s.digest(token.encode()),server.MODE,s.now()))
        status,state=self.client.request('/api/start',dict(adult=True,recent_shopping=True,consent=True,invitation=token))
        self.assertEqual(status,200,state);pid=state['participant_id']
        with s.db() as c:c.execute('UPDATE participants SET swap_bits=? WHERE id=?',(swaps,pid))
        self.client.request('/api/viewed',{});status,state=self.client.request('/api/attributes',{});self.assertEqual(status,200,state)
        observed=[]
        for n in range(8):
            observed.append(copy.deepcopy(state))
            status,state=self.client.request('/api/answer',dict(task_id=state['task_id'],choice=('A','B','N')[n%3]));self.assertEqual(status,200,state)
            self.assertEqual(len(self.mock.posts),0,'不得逐题上传')
        self.assertEqual(state['phase'],'survey')
        return pid,observed
    def finish(self):
        status,state=self.client.request('/api/finish',SURVEY);self.assertEqual(status,200,state);self.assertEqual(state['phase'],'done');return state
    def due(self,pid):
        with s.db() as c:c.execute('UPDATE qf_submissions SET next_attempt_at=? WHERE participant_id=?',('2000-01-01T00:00:00.000+00:00',pid))
    def record(self,pid):return self.rows('SELECT * FROM qf_submissions WHERE participant_id=?',(pid,))[0]

    def test_01_completion_one_utf8_payload_positions_and_questionnaire(self):
        pid,seen=self.participant();self.assertEqual(uuid.UUID(pid).version,4)
        self.assertEqual(self.client.request('/api/finish',{**SURVEY,'gender':''})[0],400)
        self.assertEqual(self.rows('SELECT * FROM qf_submissions'),[])
        self.finish();self.assertEqual(len(self.mock.posts),1)
        post=self.mock.posts[0];self.assertEqual(post['path'],'/api/formal');self.assertIn('application/json',post['headers']['Content-Type'])
        self.assertIn('品牌公开'.encode(),post['raw']);payload=json.loads(post['raw']);self.assertEqual(uuid.UUID(payload['participant_id']).version,5)
        required=['participant_id','experiment_group','visual_type','ai_disclosure','dce_block','design_version','survey_mode','started_at','completed_at','duration_seconds','completion_status','dce_choices_json']
        self.assertTrue(all(k in payload for k in required));self.assertEqual(payload['local_participant_id'],pid)
        dictionary=json.loads((s.ROOT/'docs/quickform_fields.json').read_text(encoding='utf-8'))
        self.assertEqual(set(payload),set(dictionary['fields']),'字段字典必须覆盖所有实际提交字段')
        self.assertEqual(payload['product_volume_ml'],1000)
        self.assertEqual(len(self.rows('SELECT * FROM choice_products WHERE participant_id=?',(pid,))),16)
        items=json.loads(payload['dce_choices_json']);self.assertEqual(len(items),8)
        for i,(item,actual) in enumerate(zip(items,seen),1):
            self.assertEqual(item['task_id'],actual['task_id']);self.assertEqual(item['position'],i)
            for alt in ('A','B'):
                self.assertEqual(item[alt]['codes'],qm.codes(actual[alt.lower()]))
                self.assertEqual(item[alt]['display'],qm.display(actual[alt.lower()]))
                self.assertEqual(payload[f'task_{i}_{alt}_price'],actual[alt.lower()]['price'])
                self.assertEqual(payload[f'task_{i}_{alt}_environmental_verification'],actual[alt.lower()]['verification'])
                self.assertEqual(item[alt]['codes']['product_volume_ml'],1000)
                self.assertEqual(item[alt]['codes']['price_yuan'],(15,24,34)[item[alt]['codes']['price_level']-1])
                self.assertEqual(payload[f'task_{i}_{alt}_product_volume_ml'],1000)
            self.assertEqual(item['display_text_provenance'],'server_delivery_snapshot')
            self.assertTrue(item['started_at']);self.assertTrue(item['completed_at'])
        questionnaire=json.loads(payload['questionnaire_json'])
        for k,v in SURVEY.items():self.assertEqual(str(questionnaire[k]),str(v))
        self.assertIsNone(json.loads(payload['green_consumption_values_json']));self.assertEqual(payload['green_consumption_values_status'],'not_collected')
        self.assertNotIn('green_consumption_values',questionnaire)
        self.assertEqual(self.record(pid)['status'],'success');self.assertEqual(self.record(pid)['confirmation'],'http_200_status_success')
        for _ in range(3):
            self.assertEqual(self.client.request('/api/state')[1]['phase'],'done');self.assertEqual(self.client.request('/api/finish',{})[0],200)
            self.assertFalse(qf.dispatch_once(self.cfg))
        self.assertEqual(len(self.mock.posts),1)
        self.assertEqual(self.rows('SELECT count(*) n FROM qf_attempts')[0]['n'],1)

    def test_02_timeout_uncertain_preserves_answers_no_automatic_retry(self):
        self.mock.plans.append(dict(code=200,body={'status':'success'},delay=.5))
        pid,_=self.participant();self.finish();self.assertEqual(len(self.mock.posts),1)
        self.assertEqual(self.record(pid)['status'],'uncertain')
        for _ in range(4):self.assertFalse(qf.dispatch_once(self.cfg))
        self.assertEqual(self.rows('SELECT count(*) n FROM choices WHERE participant_id=?',(pid,))[0]['n'],8)
        self.assertTrue(self.rows('SELECT completed_at FROM participants WHERE id=?',(pid,))[0]['completed_at'])
        self.assertEqual(self.admin.request('/api/admin/quickform/action',dict(participant_id=pid,action='retry',note='尝试直接重试未核查记录'))[0],400)
        self.assertEqual(len(self.mock.posts),1)

    def test_03_success_contract_queue_and_other_2xx_uncertain(self):
        for code,body in [(202,{'status':'success','queued':True}),(201,{'status':'success'}),(200,{'success':True}),(200,'not-json'),(200,{'status':'success','queued':True}),(500,{'status':'error'})]:
            status,retryable,_,_=qf.classify(code,json.dumps(body).encode() if not isinstance(body,str) else body.encode())
            self.assertEqual(status,'uncertain',(code,body));self.assertFalse(retryable)
        self.mock.plans.append(dict(code=202,body={'queued':True,'spool_id':'mock-spool'}))
        pid,_=self.participant();self.finish();self.assertEqual(self.record(pid)['status'],'uncertain');self.assertFalse(qf.dispatch_once(self.cfg))

    def test_04_explicit_failure_bounded_backoff_and_manual_retry_immutable(self):
        self.mock.plans.extend([dict(code=429,body={'status':'error','retry_after':5},retry_after=5)]*3)
        pid,_=self.participant();self.finish();before=self.rows('SELECT * FROM choices ORDER BY task_id')
        record=self.record(pid);raw=record['payload_json'];self.assertEqual(record['status'],'pending');self.assertEqual(record['attempt_count'],1)
        self.assertGreaterEqual(s.seconds(record['last_attempt_at'],record['next_attempt_at']),5)
        self.assertFalse(qf.dispatch_once(self.cfg))
        for count in (2,3):
            self.due(pid);self.assertTrue(qf.dispatch_once(self.cfg));self.assertEqual(self.record(pid)['attempt_count'],count)
        self.assertEqual(self.record(pid)['status'],'failed');self.assertFalse(qf.dispatch_once(self.cfg))
        self.assertEqual(self.admin.request('/api/admin/quickform/action',dict(participant_id=pid,action='retry',note='已核实限流解除后重试'))[0],200)
        self.assertTrue(qf.dispatch_once(self.cfg));self.assertEqual(self.record(pid)['status'],'success')
        self.assertEqual(self.record(pid)['payload_json'],raw);self.assertEqual(self.rows('SELECT * FROM choices ORDER BY task_id'),before)
        self.assertEqual(len(self.mock.posts),4);self.assertEqual(len({p['raw'] for p in self.mock.posts}),1)
        self.assertEqual(len(self.rows('SELECT * FROM qf_attempts')),4)

    def test_05_connection_refused_local_completion_remains(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        cfg=qf.Config('formal',f'http://127.0.0.1:{port}/api/unavailable',True,'loopback mock',.18,1,1)
        with patch.object(server,'QF_CONFIG',cfg):
            pid,_=self.participant();self.finish()
        # On Windows a refused connect can surface as a timeout; conservatively
        # retain uncertain in that case instead of claiming it was not received.
        self.assertIn(self.record(pid)['status'],('failed','uncertain'));self.assertEqual(self.record(pid)['attempt_count'],1)
        self.assertEqual(self.rows('SELECT count(*) n FROM choices')[0]['n'],8);self.assertEqual(len(self.mock.posts),0)

    def test_06_admin_auth_status_record_logs_and_manual_review(self):
        self.mock.plans.append(dict(code=202,body={'queued':True}));pid,_=self.participant();self.finish()
        anon=Client(self.base)
        for route in ('quickform','quickform/logs','quickform/record?participant_id='+pid):self.assertEqual(anon.request('/api/admin/'+route)[0],401)
        self.assertEqual(self.admin.request('/api/admin/quickform/action',dict(participant_id=pid,action='review',decision='received',note='已在远端按编号核查收到',confirm=True),csrf=False)[0],403)
        code,stats=self.admin.request('/api/admin/quickform?mode=formal');self.assertEqual(code,200);self.assertEqual(stats['completed_local'],1);self.assertEqual(stats['counts']['uncertain'],1)
        code,record=self.admin.request('/api/admin/quickform/record?participant_id='+pid);self.assertEqual(code,200);self.assertEqual(len(record['attempts']),1)
        code,logs=self.admin.request('/api/admin/quickform/logs?mode=formal');self.assertEqual(code,200);self.assertIn(b'uncertain',logs)
        body=dict(participant_id=pid,action='review',decision='received',note='已在远端按UUID及指纹核查收到',confirm=False)
        self.assertEqual(self.admin.request('/api/admin/quickform/action',body)[0],400)
        self.assertEqual(self.admin.request('/api/admin/quickform/action',{**body,'confirm':True})[0],200)
        self.assertEqual(self.record(pid)['status'],'success');self.assertEqual(self.record(pid)['confirmation'],'researcher_review')
        self.assertFalse(qf.dispatch_once(self.cfg));self.assertEqual(len(self.mock.posts),1)

    def test_07_demo_pilot_formal_configuration_isolation(self):
        self.assertEqual(qf.DEFAULT_API_URL,'https://quickform.cn/api/kajm9wjasx')
        with patch.object(server,'MODE','demo'),patch.object(server,'QF_CONFIG',qf.config('demo')):
            self.participant();self.finish()
        self.assertEqual(len(self.mock.posts),0);self.assertEqual(self.rows('SELECT * FROM qf_submissions'),[])
        self.client=Client(self.base)
        with patch.object(server,'MODE','pilot'),patch.object(server,'QF_CONFIG',qf.config('pilot')):
            pid,_=self.participant();self.finish()
        self.assertEqual(self.mock.posts[0]['path'],'/api/pilot');self.assertEqual(self.record(pid)['survey_mode'],'pilot')
        self.assertFalse(qf.dispatch_once(self.cfg));self.assertEqual(len(self.mock.posts),1)
        for target in (self.url+'/api/formal',self.url+'/api/9lnrb0a8hn',self.url+'/api/kajm9wjasx'):
            with patch.dict(os.environ,QUICKFORM_PILOT_API_URL=target):
                with self.assertRaises(ValueError):qf.config('pilot')
        with patch.dict(os.environ,QUICKFORM_FORMAL_ENABLED='NO'):
            self.assertFalse(qf.config('formal').enabled)
        with patch.dict(os.environ,QUICKFORM_API_URL=qf.DEFAULT_API_URL):
            with self.assertRaises(ValueError):qf.config('formal')

    def test_08_interrupted_claim_is_uncertain_on_recovery(self):
        cfg=qf.Config('formal',self.url+'/api/formal',False,'disabled')
        with patch.object(server,'QF_CONFIG',cfg):pid,_=self.participant();self.finish()
        with s.db() as c:
            c.execute("UPDATE qf_submissions SET in_flight_token='interrupted',in_flight_at=?,attempt_count=1 WHERE participant_id=?",(s.now(),pid))
            c.execute('INSERT INTO qf_attempts(participant_id,attempt_number,started_at,outcome,payload_sha256) VALUES (?,?,?,?,?)',(pid,1,s.now(),'in_flight',self.record(pid)['payload_sha256']))
        qf.recover_inflight();self.assertEqual(self.record(pid)['status'],'uncertain');self.assertFalse(qf.dispatch_once(self.cfg));self.assertEqual(len(self.mock.posts),0)

    def test_09_remote_export_restore_long_and_reject_missing_or_mismatched(self):
        pid,seen=self.participant(swaps='10101010');self.finish();record=json.loads(self.mock.posts[0]['raw'])
        rows=qm.restore_long(record,'formal');self.assertEqual(len(rows),24)
        for i,state in enumerate(seen):
            group=rows[i*3:i*3+3];self.assertEqual(sum(r['chosen'] for r in group),1)
            self.assertEqual(group[0]['origin'],state['a']['origin']);self.assertEqual(group[1]['price'],state['b']['price'])
            self.assertEqual(group[2]['opt_out'],1);self.assertIsNone(group[2]['price']);self.assertIsNone(group[2]['origin'])
        for kind in ('missing','flat','mode'):
            bad=copy.deepcopy(record)
            if kind=='missing':items=json.loads(bad['dce_choices_json']);items.pop();bad['dce_choices_json']=json.dumps(items)
            if kind=='flat':bad['task_1_A_price']=999
            if kind=='mode':bad['survey_mode']='pilot'
            with self.assertRaises(ValueError):qm.restore_long(bad,'formal')
        source=self.folder/'quickform.csv'
        with source.open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=record);w.writeheader();w.writerow(record)
        out=self.folder/'restored'
        proc=subprocess.run([sys.executable,str(s.ROOT/'scripts/restore_quickform_export.py'),str(source),'--mode','formal','--output-dir',str(out)],capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr.decode(errors='replace'))
        with (out/'choice_long.csv').open(encoding='utf-8-sig',newline='') as f:restored=list(csv.DictReader(f))
        self.assertEqual(len(restored),24);self.assertEqual(restored[2]['price'],'')

    def test_10_concurrent_final_submission_and_snapshot_hash(self):
        pid,_=self.participant()
        results=[]
        threads=[threading.Thread(target=lambda:results.append(self.client.request('/api/finish',SURVEY))) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertEqual([r[0] for r in results],[200,200]);self.assertEqual(len(self.mock.posts),1)
        self.assertEqual(len(self.rows('SELECT * FROM qf_submissions')),1)
        self.assertEqual(s.digest(self.record(pid)['payload_json'].encode()),self.record(pid)['payload_sha256'])

    def test_11_legacy_outbox_preserved_and_not_automatically_retried(self):
        with s.db() as c:
            c.executescript('''CREATE TABLE quickform_outbox(participant_id TEXT PRIMARY KEY,payload_json TEXT,status TEXT,attempts INTEGER,last_attempt_at TEXT,next_attempt_at TEXT,sent_at TEXT,last_error TEXT);''')
        pid,_=self.participant();self.finish()
        with s.db() as c:
            c.execute('DELETE FROM qf_attempts');c.execute('DELETE FROM qf_submissions')
            c.execute('INSERT INTO quickform_outbox VALUES (?,?,?,?,?,?,?,?)',(pid,'{"legacy":"原件"}','sent',1,s.now(),s.now(),s.now(),None))
        s.init_db();self.assertEqual(self.record(pid)['status'],'uncertain')
        self.assertEqual(self.rows('SELECT payload_json FROM quickform_outbox')[0]['payload_json'],'{"legacy":"原件"}')
        self.assertFalse(qf.dispatch_once(self.cfg));self.assertEqual(len(self.mock.posts),1)

    def test_12_browser_sync_admin_retry_record_and_log_download(self):
        from playwright.sync_api import sync_playwright
        self.mock.plans.append(dict(code=400,body={'status':'error','message':'模拟字段拒绝'}));pid,_=self.participant();self.finish()
        self.assertEqual(self.record(pid)['status'],'failed')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport=dict(width=1440,height=1000));errors=[]
            page.on('pageerror',lambda exc:errors.append(str(exc)))
            page.goto(self.base+'/admin');page.locator('#username').fill('researcher');page.locator('#password').fill(PASSWORD);page.get_by_role('button',name='登录',exact=True).click()
            page.get_by_role('heading',name='QuickForm数据同步').wait_for();page.locator('#qf-counts strong').first.wait_for()
            self.assertIn('明确失败',page.locator('#qf-rows').inner_text())
            page.get_by_role('button',name='查看记录',exact=True).click();page.locator('#qf-record').wait_for(state='visible')
            self.assertIn('payload_json',page.locator('#qf-record-body').inner_text());page.get_by_role('button',name='关闭记录').click()
            page.get_by_role('button',name='准备重试',exact=True).click();page.locator('#qf-note').fill('已修正模拟拒绝原因后重试')
            page.get_by_role('button',name='执行所选操作',exact=True).click();page.locator('#qf-result').filter(has_text='操作已记录').wait_for()
            self.assertTrue(qf.dispatch_once(self.cfg));page.get_by_role('button',name='刷新同步状态').click()
            page.locator('#qf-rows').filter(has_text='已确认成功').wait_for()
            with page.expect_download() as event:page.locator('#qf-logs').click()
            event.value.save_as(str(self.folder/'ui-logs.csv'));self.assertIn('success',(self.folder/'ui-logs.csv').read_text(encoding='utf-8-sig'))
            (s.ROOT/'test-results').mkdir(exist_ok=True);page.screenshot(path=str(s.ROOT/'test-results'/'quickform-admin.png'),full_page=True)
            self.assertEqual(errors,[]);browser.close()

    def test_13_background_worker_respects_due_and_retries(self):
        self.mock.plans.append(dict(code=429,body={'status':'error','retry_after':1}))
        pid,_=self.participant();self.finish();self.assertEqual(self.record(pid)['status'],'pending')
        stop=threading.Event();thread=threading.Thread(target=qf.worker,args=(stop,self.cfg),daemon=True);thread.start()
        try:
            end=time.monotonic()+6
            while time.monotonic()<end and self.record(pid)['status']!='success':time.sleep(.05)
            self.assertEqual(self.record(pid)['status'],'success');self.assertEqual(len(self.mock.posts),2)
            self.assertEqual(self.mock.posts[0]['raw'],self.mock.posts[1]['raw'])
        finally:stop.set();qf.WAKE.set();thread.join(3)

if __name__=='__main__':unittest.main(verbosity=2)
