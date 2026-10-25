"""Integration + real Chromium tests, isolated from the project's original data.
Run: python -m unittest discover -s tests -v
"""
import base64
from contextlib import closing
import concurrent.futures
import copy
import csv
import hashlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import urllib.error
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import design_registry as registry
TASKS=registry.ACTIVE.tasks
BY_ID={t['id']:t for t in TASKS}
HASH=registry.ACTIVE.task_hash
VERSION=registry.ACTIVE.version
PASSWORD='test-password-only-2718'
SURVEY=dict(age='29',gender='female',education='bachelor',online_purchase='monthly1',plant_based_purchase='yes',manip_visual='chart',manip_ai='unsure')

class Client:
    def __init__(self,base):
        self.base=base; self.jar=http.cookiejar.CookieJar(); self.csrf=''
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
    def request(self,path,data=None,csrf=True,headers=None):
        h={'Content-Type':'application/json'}
        if csrf: h['X-CSRF-Token']=self.csrf
        h.update(headers or {})
        req=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=h)
        try:
            with self.opener.open(req,timeout=30) as r:
                raw=r.read(); return r.status,json.loads(raw) if 'application/json' in r.headers.get('Content-Type','') else raw
        except urllib.error.HTTPError as e:
            with e: return e.code,json.loads(e.read())
    def login(self):
        status,d=self.request('/api/admin/login',dict(username='researcher',password=PASSWORD))
        assert status==200,(status,d)
        self.csrf=d['csrf']; return d
    def start(self): return self.request('/api/start',dict(consent=True,adult=True,recent_shopping=True))[1]

class Platform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='study2-tests-')
        cls.data=Path(cls.temp.name)/'primary'; cls.data.mkdir()
        # A copy is used solely to verify migration, without touching original DB.
        if (ROOT/'data/study2.sqlite3').exists():
            with closing(sqlite3.connect(ROOT/'data/study2.sqlite3')) as c:
                cls.old_parts=c.execute('SELECT id,token_digest,mode,group_code,block,swap_bits,task_order,created_at,stimulus_end_at,completed_at,age,gender,education,online_purchase,plant_based_purchase,manip_visual,manip_ai FROM participants ORDER BY id').fetchall()
                cls.old_choices=c.execute('SELECT * FROM choices ORDER BY participant_id,task_id').fetchall()
        else: cls.old_parts=[]; cls.old_choices=[]
        # Reconstruct the original schema in the isolated directory, so the
        # migration remains tested even after the real workspace was upgraded.
        with closing(sqlite3.connect(cls.data/'study2.sqlite3')) as c:
            c.executescript('''CREATE TABLE participants (
              id TEXT PRIMARY KEY,token_digest TEXT NOT NULL UNIQUE,mode TEXT NOT NULL,
              group_code INTEGER NOT NULL,block TEXT NOT NULL,swap_bits TEXT NOT NULL,
              task_order TEXT NOT NULL,created_at TEXT NOT NULL,stimulus_end_at TEXT,
              completed_at TEXT,age INTEGER,gender TEXT,education TEXT,online_purchase TEXT,
              plant_based_purchase TEXT,manip_visual TEXT,manip_ai TEXT);
              CREATE TABLE choices (participant_id TEXT NOT NULL REFERENCES participants(id),
              task_id TEXT NOT NULL,displayed_choice TEXT NOT NULL,answered_at TEXT NOT NULL,
              PRIMARY KEY(participant_id,task_id));''')
            c.executemany('INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',cls.old_parts)
            c.executemany('INSERT INTO choices VALUES (?,?,?,?)',cls.old_choices)
            c.commit()
        cls.processes=[]
        cls.proc,cls.base=cls.launch(cls.data)
        cls.admin=Client(cls.base); cls.admin.login()
        cls.complete=[]
    @classmethod
    def launch(cls,data,mode='demo',invite=False):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        env={**os.environ,'DCE_DATA_DIR':str(data),'DCE_MODE':mode,'DCE_PORT':str(port),'DCE_HOST':'127.0.0.1','DCE_ADMIN_USER':'researcher','DCE_ADMIN_PASSWORD':PASSWORD,'DCE_REQUIRE_INVITE':'1' if invite else '0','DCE_SECURE_COOKIE':'0','QUICKFORM_FORMAL_ENABLED':'NO','QUICKFORM_PILOT_ENABLED':'NO','QUICKFORM_ALLOW_LOCAL_TEST':'NO','QUICKFORM_API_URL':'https://quickform.cn/api/kajm9wjasx','QUICKFORM_PILOT_API_URL':''}
        log=open(Path(cls.temp.name)/f'{port}.log','w',encoding='utf-8')
        proc=subprocess.Popen([sys.executable,'server.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
        cls.processes.append((proc,log)); base=f'http://127.0.0.1:{port}'
        for _ in range(100):
            if proc.poll() is not None:
                log.flush(); raise RuntimeError(Path(log.name).read_text(encoding='utf-8'))
            try:
                if Client(base).request('/api/state')[0]==200: return proc,base
            except OSError: time.sleep(.1)
        raise RuntimeError('server failed to start')
    @classmethod
    def tearDownClass(cls):
        for proc,log in cls.processes:
            if proc.poll() is None: proc.terminate(); proc.wait(10)
            log.close()
        cls.temp.cleanup()
    def db(self,sql,args=()):
        with closing(sqlite3.connect(self.data/'study2.sqlite3')) as c:
            c.row_factory=sqlite3.Row
            return [dict(r) for r in c.execute(sql,args)]
    def forced(self,g,b):
        client=Client(self.base); client.login()
        code,state=client.request('/api/admin/demo',dict(group=g,block=b)); self.assertEqual(code,200,state)
        return client,state
    def complete_session(self,client,state):
        client.request('/api/viewed',{})
        code,state=client.request('/api/attributes',{}); self.assertEqual(code,200)
        seen=[]
        while state['phase']=='choice':
            seen.append(copy.deepcopy(state))
            code,state=client.request('/api/answer',dict(task_id=state['task_id'],choice=('A','B','N')[(state['position']-1)%3]))
            self.assertEqual(code,200,state)
        self.assertEqual(len(seen),8); self.assertEqual(state['phase'],'survey')
        code,state=client.request('/api/finish',SURVEY); self.assertEqual(code,200,state)
        self.assertEqual(state['phase'],'done')
        return seen
    def bundle(self,base=None):
        client=self.admin if base is None else Client(base)
        if base: client.login()
        code,raw=client.request('/api/admin/export?mode=demo&design_version='+VERSION); self.assertEqual(code,200)
        with zipfile.ZipFile(io.BytesIO(raw)) as z: return {n:z.read(n) for n in z.namelist()}
    def files(self,bundle,kinds=('participants','choices','choice_long')):
        return [dict(name=k+'.csv',data=base64.b64encode(bundle[k+'.csv']).decode()) for k in kinds]
    def preview(self,client,bundle,mode='demo',kinds=('participants','choices','choice_long')):
        return client.request('/api/admin/import/preview',dict(mode=mode,design_version=VERSION,files=self.files(bundle,kinds)))
    def rows(self,raw): return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    def encoded(self,rows):
        f=io.StringIO(newline=''); w=csv.DictWriter(f,fieldnames=rows[0]); w.writeheader(); w.writerows(rows); return f.getvalue().encode('utf-8-sig')

    def test_01_legacy_migration_and_locked_design(self):
        parts=self.db('SELECT id,token_digest,mode,group_code,block,swap_bits,task_order,created_at,stimulus_end_at,completed_at,age,gender,education,online_purchase,plant_based_purchase,manip_visual,manip_ai FROM participants ORDER BY id')
        choices=self.db('SELECT * FROM choices ORDER BY participant_id,task_id')
        self.assertEqual([tuple(r.values()) for r in parts],self.old_parts)
        self.assertEqual([tuple(r.values()) for r in choices],self.old_choices)
        self.assertEqual(hashlib.sha256((ROOT/registry.ACTIVE.config['task_file']).read_bytes()).hexdigest(),HASH)
        self.assertEqual(len(TASKS),16)
        self.assertEqual([sum(t['block']==b for t in TASKS) for b in 'AB'],[8,8])

    def test_02_admin_auth_csrf_private_files(self):
        c=Client(self.base)
        self.assertEqual(c.request('/api/admin/stats')[0],401)
        self.assertEqual(c.request('/api/admin/export')[0],401)
        self.assertEqual(c.request('/api/admin/login',dict(username='researcher',password='wrong'))[0],401)
        c.start()
        self.assertEqual(c.request('/api/admin/stats')[0],401)
        self.assertEqual(self.admin.request('/api/admin/backup',{},csrf=False)[0],403)
        self.assertEqual(self.admin.request('/api/admin/backup',{},headers={'Origin':'https://example.invalid'})[0],403)
        for path in ('/data/study2.sqlite3','/exports/participants.csv','/tasks.json','/../data/admin_credentials.json'):
            self.assertEqual(c.request(path)[0],404)

    def test_03_groups_eight_tasks_swaps_and_export(self):
        for g in range(1,5):
            for b in 'AB':
                c,state=self.forced(g,b)
                self.assertEqual(state['image'],'/static/stimuli/'+('chart' if g in (1,3) else 'nature')+'.jpg')
                self.assertEqual(state['ai_disclosed'],g in (3,4))
                pid=state['participant_id']; seen=self.complete_session(c,state)
                self.complete.append(pid)
                p=self.db('SELECT * FROM participants WHERE id=?',(pid,))[0]
                self.assertEqual(set(s['task_id'] for s in seen),{t['id'] for t in TASKS if t['block']==b})
                for i,s0 in enumerate(seen):
                    t=BY_ID[s0['task_id']]; swap=p['swap_bits'][i]=='1'
                    self.assertEqual(s0['a'],t['b'] if swap else t['a'])
                    self.assertEqual(s0['b'],t['a'] if swap else t['b'])
                self.assertEqual(self.db('SELECT COUNT(*) n FROM choices WHERE participant_id=?',(pid,))[0]['n'],8)
                self.assertEqual(c.request('/api/state')[1]['phase'],'done')
        bundle=self.bundle(); rows=self.rows(bundle['choices.csv']); longs=self.rows(bundle['choice_long.csv'])
        swaps=set()
        for pid in self.complete:
            p=self.db('SELECT * FROM participants WHERE id=?',(pid,))[0]
            own=[r for r in rows if r['participant_id']==pid]; self.assertEqual(len(own),8)
            for r in own:
                swaps.add(r['swapped']); t=BY_ID[r['task_id']]; a=t['b'] if r['swapped']=='1' else t['a']
                for k,v in a.items(): self.assertEqual(int(r['a_'+k]),v)
                ls=[l for l in longs if l['participant_id']==pid and l['task_id']==r['task_id']]
                self.assertEqual(len(ls),3); self.assertEqual(sum(int(l['choice']) for l in ls),1)
                self.assertEqual(next(l['alternative'] for l in ls if l['choice']=='1'),r['displayed_choice'])
                n=next(l for l in ls if l['alternative']=='N'); self.assertEqual(n['price_yuan'],''); self.assertEqual(n['opt_out'],'1')
        self.assertEqual(swaps,{'0','1'})
        manifest=json.loads(bundle['manifest.json']); self.assertEqual(manifest['task_design_sha256'],HASH)

    def test_04_retry_concurrency_and_persistent_resume(self):
        c,state=self.forced(1,'A'); pid=state['participant_id']
        c.request('/api/viewed',{}); _,state=c.request('/api/attributes',{})
        old=state['task_id']; body=dict(task_id=old,choice='A')
        start=self.db('SELECT started_at FROM task_views WHERE participant_id=? AND task_id=?',(pid,old))[0]
        self.assertEqual(c.request('/api/state')[1]['task_id'],old)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:c.request('/api/answer',body),range(2)))
        self.assertEqual([r[0] for r in results],[200,200])
        self.assertEqual(self.db('SELECT COUNT(*) n FROM choices WHERE participant_id=?',(pid,))[0]['n'],1)
        self.assertEqual(c.request('/api/answer',dict(task_id=old,choice='B'))[0],400)
        self.assertEqual(c.request('/api/answer',dict(task_id='T99',choice='A'))[0],400)
        # Read from a new server process using the same durable DB and browser cookie.
        self.proc.terminate(); self.proc.wait(10)
        self.__class__.proc,self.__class__.base=self.launch(self.data)
        c.base=self.base; self.__class__.admin=Client(self.base); self.admin.login()
        resumed=c.request('/api/state')[1]; self.assertEqual(resumed['answered'],1)
        self.assertEqual(self.db('SELECT started_at FROM task_views WHERE participant_id=? AND task_id=?',(pid,old))[0],start)
        self.assertEqual(c.request('/api/answer',body)[0],200)
        self.assertEqual(c.request('/api/state')[1]['answered'],1)

    def test_05_balanced_randomization(self):
        before=self.db("SELECT group_code,block,count(*) n FROM participants WHERE provenance IN ('live','legacy') AND design_version='study2-1l-3price-v2' GROUP BY group_code,block")
        for _ in range(32): Client(self.base).start()
        rows=self.db("SELECT group_code,block,count(*) n FROM participants WHERE provenance IN ('live','legacy') AND design_version='study2-1l-3price-v2' GROUP BY group_code,block")
        counts=[r['n'] for r in rows]; self.assertLessEqual(max(counts)-min(counts),1)
        self.assertEqual(sum(counts)-sum(r['n'] for r in before),32)
        self.assertEqual(Client(self.base).request('/api/start',dict(consent=True,adult=True,recent_shopping=True,group=1))[0],400)

    def test_06_import_preview_confirm_dedup_and_conflicts(self):
        bundle=self.bundle()
        other=Path(self.temp.name)/'other'; _,base=self.launch(other)
        a=Client(base); a.login()
        code,report=self.preview(a,bundle); self.assertEqual(code,200,report); self.assertEqual(report['error_count'],0,report)
        self.assertEqual(a.request('/api/admin/stats')[1]['totals']['started'],0)
        self.assertEqual(a.request('/api/admin/import/commit',dict(batch_id=report['batch_id'],confirm=False))[0],400)
        code,res=a.request('/api/admin/import/commit',dict(batch_id=report['batch_id'],confirm=True)); self.assertEqual(code,200,res)
        expected=len(self.rows(bundle['participants.csv']))
        self.assertEqual(a.request('/api/admin/stats')[1]['totals']['started'],expected)
        self.assertEqual(a.request('/api/admin/import/commit',dict(batch_id=report['batch_id'],confirm=True))[0],400)
        _,again=self.preview(a,bundle); self.assertEqual(again['error_count'],0,again); self.assertEqual(again['new_participants'],0); self.assertEqual(again['duplicates'],expected)
        self.assertEqual(a.request('/api/admin/import/commit',dict(batch_id=again['batch_id'],confirm=True))[0],200)
        self.assertEqual(a.request('/api/admin/stats')[1]['totals']['started'],expected)
        code,out=self.preview(a,bundle,'pilot'); self.assertEqual(code,200); self.assertGreater(out['error_count'],0)
        # No choice changes are made during validation, including a rejected file.
        bad=copy.deepcopy(bundle); rows=self.rows(bad['choice_long.csv']); rows[0]['choice']='1'; rows[1]['choice']='1'; bad['choice_long.csv']=self.encoded(rows)
        _,res=self.preview(a,bad,kinds=('participants','choice_long')); self.assertGreater(res['error_count'],0)
        self.assertTrue(list((other/'imports').glob('*/*.csv')))
        self.assertEqual(a.request('/api/admin/stats')[1]['totals']['started'],expected)
        # Collision of original ids from a different instance stays separate.
        cross=copy.deepcopy(bundle)
        for key in ('participants.csv','choices.csv','choice_long.csv'):
            rr=self.rows(cross[key])
            for r in rr: r['source_instance']='second-platform-instance'
            cross[key]=self.encoded(rr)
        _,r=self.preview(a,cross); self.assertEqual(r['error_count'],0,r)
        self.assertEqual(a.request('/api/admin/import/commit',dict(batch_id=r['batch_id'],confirm=True))[0],200)
        self.assertEqual(a.request('/api/admin/stats')[1]['totals']['started'],expected*2)
        self.assertEqual(a.request('/api/admin/stats?mode=pilot')[1]['totals']['started'],0)

    def test_07_import_rejects_bad_rows_and_files(self):
        bundle=self.bundle()
        mutations=[('participants.csv','group_code','G9'),('participants.csv','block','C'),('participants.csv','design_version','future-24-v2'),('participants.csv','task_hash','0'*64),('choices.csv','a_origin','2'),('choices.csv','task_id','T99'),('choices.csv','displayed_choice',''),('choices.csv','swapped','9')]
        for name,k,v in mutations:
            bad=copy.deepcopy(bundle); rows=self.rows(bad[name]); rows[0][k]=v; bad[name]=self.encoded(rows)
            code,r=self.preview(self.admin,bad); self.assertEqual(code,200,r); self.assertGreater(r['error_count'],0,(name,k,r))
        bad=copy.deepcopy(bundle); rows=self.rows(bad['participants.csv']); rows.append(dict(rows[0])); bad['participants.csv']=self.encoded(rows)
        self.assertGreater(self.preview(self.admin,bad)[1]['error_count'],0)
        self.assertEqual(self.admin.request('/api/admin/import/preview',dict(mode='demo',design_version=VERSION,files=[dict(name='participants.exe',data=base64.b64encode(b'bad').decode())]))[0],400)
        old=copy.deepcopy(bundle); rows=self.rows(old['participants.csv']); rows[0]['swap_bits']=''; old['participants.csv']=self.encoded(rows)
        self.assertGreater(self.preview(self.admin,old)[1]['error_count'],0)

    def test_07b_xlsx_compatible_and_formula_rejected(self):
        import openpyxl
        files=[]
        bundle=self.bundle()
        for kind in ('participants','choices'):
            rows=self.rows(bundle[kind+'.csv']); book=openpyxl.Workbook(); sheet=book.active
            sheet.append(list(rows[0]))
            for r in rows: sheet.append(list(r.values()))
            f=io.BytesIO(); book.save(f); book.close()
            files.append(dict(name=kind+'.xlsx',data=base64.b64encode(f.getvalue()).decode()))
        code,r=self.admin.request('/api/admin/import/preview',dict(mode='demo',design_version=VERSION,files=files))
        self.assertEqual(code,200,r); self.assertEqual(r['error_count'],0,r)
        book=openpyxl.Workbook(); book.active.append(['participant_id']); book.active.append(['=1+1']); f=io.BytesIO(); book.save(f); book.close()
        code,r=self.admin.request('/api/admin/import/preview',dict(mode='demo',design_version=VERSION,files=[dict(name='participants.xlsx',data=base64.b64encode(f.getvalue()).decode())]))
        self.assertEqual(code,400,r)

    def test_07c_size_structure_limits_and_cross_session_commit(self):
        # Header-based rejection occurs before processing oversized request bodies.
        import http.client
        parsed=urllib.parse.urlparse(self.base)
        con=http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=10)
        con.request('POST','/api/start',body=b'{}',headers={'Content-Type':'application/json','Content-Length':'70000'})
        response=con.getresponse(); self.assertEqual(response.status,400); response.read(); con.close()
        r=self.admin.request('/api/admin/import/preview',dict(mode='demo',design_version=VERSION,files=[None]))
        self.assertEqual(r[0],400)
        b=self.bundle(); _,report=self.preview(self.admin,b)
        stranger=Client(self.base); stranger.login()
        self.assertEqual(stranger.request('/api/admin/import/commit',dict(batch_id=report['batch_id'],confirm=True))[0],400)
        self.assertEqual(self.admin.request('/api/admin/import/preview',dict(mode='demo',design_version=VERSION,files=[dict(name='participants.csv',data=base64.b64encode(b'x'*(8*1024*1024+1)).decode())]))[0],400)

    def test_08_stats_validity_and_mode_isolation(self):
        status,stats=self.admin.request('/api/admin/stats?mode=demo'); self.assertEqual(status,200)
        self.assertEqual(stats['totals']['started'],self.db("SELECT COUNT(*) n FROM participants WHERE mode='demo' AND design_version='study2-1l-3price-v2'")[0]['n'])
        self.assertEqual(stats['totals']['completed'],self.db("SELECT COUNT(*) n FROM participants WHERE mode='demo' AND design_version='study2-1l-3price-v2' AND completed_at IS NOT NULL")[0]['n'])
        self.assertEqual(stats['totals']['valid'],0)
        self.assertEqual(self.admin.request('/api/admin/review',dict(participant_id=self.complete[0],status='valid'))[0],200)
        self.assertEqual(self.admin.request('/api/admin/stats')[1]['totals']['valid'],1)
        self.assertEqual(self.admin.request('/api/admin/stats?mode=pilot')[1]['totals']['started'],0)
        code,raw=self.admin.request('/api/admin/export?mode=formal'); self.assertEqual(code,200)
        with zipfile.ZipFile(io.BytesIO(raw)) as z: self.assertEqual(len(self.rows(z.read('participants.csv'))),0)
        _,pilot=self.launch(Path(self.temp.name)/'pilot','pilot',invite=True)
        p=Client(pilot); self.assertTrue(p.request('/api/state')[1]['invite_required'])
        self.assertEqual(p.request('/api/start',dict(consent=True,adult=True,recent_shopping=True))[0],400)
        env={**os.environ,'DCE_DATA_DIR':str(Path(self.temp.name)/'pilot'),'DCE_MODE':'pilot'}
        subprocess.run([sys.executable,'server.py','invitations','--count','1'],cwd=ROOT,env=env,capture_output=True,check=True)
        invite=next((Path(self.temp.name)/'pilot').glob('invitations_*.txt')).read_text().strip()
        body=dict(consent=True,adult=True,recent_shopping=True,invitation=invite)
        self.assertEqual(p.request('/api/start',body)[0],200)
        self.assertEqual(Client(pilot).request('/api/start',body)[0],400)
        p.login(); self.assertEqual(p.request('/api/admin/demo',dict(group=1,block='A'))[0],403)
        self.assertEqual(p.request('/api/demo/restart',{})[0],403)

    def test_09_backup_restore_and_demo_restart(self):
        c,state=self.forced(2,'B'); old=state['participant_id']
        self.assertEqual(c.request('/api/demo/restart',{})[1]['phase'],'consent')
        new=c.start()['participant_id']; self.assertNotEqual(old,new)
        self.assertEqual(len(self.db('SELECT id FROM participants WHERE id IN (?,?)',(old,new))),2)
        _,r=self.admin.request('/api/admin/backup',{}); file=self.data/'backups'/r['backup']
        with closing(sqlite3.connect(file)) as x: self.assertEqual(x.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        target=Path(self.temp.name)/'restore'; env={**os.environ,'DCE_DATA_DIR':str(target),'DCE_MODE':'demo'}
        result=subprocess.run([sys.executable,'server.py','restore','--file',str(file),'--confirm'],cwd=ROOT,env=env,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        with closing(sqlite3.connect(target/'study2.sqlite3')) as x: self.assertEqual(x.execute('SELECT COUNT(*) FROM participants').fetchone()[0],self.db('SELECT COUNT(*) n FROM participants')[0]['n'])

    def test_10_browser_desktop_mobile_offline_and_admin(self):
        from playwright.sync_api import sync_playwright
        output=ROOT/'test-results'; output.mkdir(exist_ok=True)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            errors=[]; attr_html=[]
            for g in range(1,5):
                context=browser.new_context(viewport=dict(width=390,height=844) if g%2==0 else dict(width=1440,height=1000))
                page=context.new_page(); page.on('pageerror',lambda e:errors.append(str(e)))
                r=context.request.post(self.base+'/api/admin/login',data=dict(username='researcher',password=PASSWORD)).json()
                res=context.request.post(self.base+'/api/admin/demo',data=dict(group=g,block='A'),headers={'X-CSRF-Token':r['csrf']}); self.assertEqual(res.status,200)
                page.goto(self.base); page.get_by_role('heading',name='您正在逛一家线上食品超市').wait_for()
                self.assertEqual(page.locator('.disclosure').count(),int(g in (3,4)))
                self.assertTrue(page.locator('.study-picture').get_attribute('src').endswith('chart.jpg' if g in (1,3) else 'nature.jpg'))
                img=page.locator('.study-picture'); img.scroll_into_view_if_needed()
                self.assertTrue(img.evaluate('(im)=>im.complete && im.naturalWidth>0 && Math.abs(im.width/im.height-im.naturalWidth/im.naturalHeight)<0.01'))
                page.screenshot(path=str(output/f'ad-G{g}.png'),full_page=True)
                page.get_by_role('button',name='我已浏览，继续').click()
                page.get_by_role('heading',name='读懂这几项商品信息').wait_for(); attr_html.append(page.locator('#app').inner_html())
                page.get_by_role('button',name='了解了，开始比较商品').click()
                page.get_by_role('heading',name='选一盒适合自己的燕麦饮').wait_for()
                actual=context.request.get(self.base+'/api/state').json()
                for index,label in enumerate(('a','b')):
                    card=page.locator('.product').nth(index)
                    self.assertEqual(card.locator('.price').inner_text(),'¥'+str(actual[label]['price']))
                    self.assertIn('1 L / 单盒',card.inner_text())
                    self.assertIn(actual[label]['price'],(15,24,34))
                    self.assertIn('进口' if actual[label]['origin'] else '国产',card.inner_text())
                self.assertTrue(page.get_by_role('button',name='确认选择并继续').is_disabled())
                self.assertNotIn('250',page.locator('#app').inner_text())
                page.screenshot(path=str(output/f'choice-G{g}.png'),full_page=True)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'))
                if g==2:
                    for width in (320,375,768,1024):
                        page.set_viewport_size(dict(width=width,height=844))
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),width)
                    page.set_viewport_size(dict(width=390,height=844))
                page.locator('[data-choice="A"]').click(); self.assertEqual(page.locator('.pick.selected').count(),1)
                if g==1:
                    context.set_offline(True)
                    page.get_by_role('button',name='确认选择并继续').click(); page.locator('.error').wait_for()
                    context.set_offline(False)
                page.get_by_role('button',name='确认选择并继续').click()
                page.locator('.progress-head').get_by_text('2/8',exact=True).wait_for()
                page.reload(); page.locator('.progress-head').get_by_text('2/8',exact=True).wait_for()
                if g==1:
                    for n in range(2,9):
                        page.locator('[data-choice="N"]').click(); page.get_by_role('button',name='确认选择并继续').click()
                        if n<8: page.locator('.progress-head').get_by_text(f'{n+1}/8',exact=True).wait_for()
                    page.locator('#age').fill('29')
                    for k,v in SURVEY.items():
                        if k!='age': page.locator('#'+k).select_option(v)
                    page.get_by_role('button',name='提交问卷').click(); page.get_by_role('heading',name='感谢您的参与').wait_for()
                page.goto(self.base+'/admin'); page.get_by_role('heading',name='实时数据概况').wait_for()
                page.screenshot(path=str(output/f'admin-G{g}.png'),full_page=True)
                context.close()
            self.assertEqual(len(set(attr_html)),1)
            self.assertEqual(errors,[])
            # Exercise actual login, upload preview/confirmation and export UI.
            context=browser.new_context(viewport=dict(width=1440,height=1000)); page=context.new_page()
            page.goto(self.base+'/admin'); page.locator('#username').fill('researcher'); page.locator('#password').fill(PASSWORD)
            page.get_by_role('button',name='登录',exact=True).click(); page.get_by_role('heading',name='实时数据概况').wait_for()
            bundle=self.bundle(); folder=Path(self.temp.name)/'ui-files'; folder.mkdir()
            for name in ('participants.csv','choices.csv'): (folder/name).write_bytes(bundle[name])
            page.locator('#files').set_input_files([str(folder/n) for n in ('participants.csv','choices.csv')])
            page.get_by_role('button',name='上传并预览检查').click(); page.locator('#import-confirm').wait_for()
            self.assertTrue(page.get_by_role('button',name='确认执行导入').is_disabled())
            page.locator('#import-confirm').check(); page.get_by_role('button',name='确认执行导入').click()
            page.locator('#preview-result').filter(has_text='已导入').wait_for()
            with page.expect_download() as event: page.locator('#export').click()
            dl=event.value; self.assertTrue(dl.suggested_filename.endswith('.zip')); dl.save_as(str(folder/'download.zip'))
            with zipfile.ZipFile(folder/'download.zip') as z: self.assertEqual(set(z.namelist()),{'participants.csv','choices.csv','choice_long.csv','detail_views.csv','manifest.json'})
            page.screenshot(path=str(output/'admin-import-confirmed.png'),full_page=True)
            page.get_by_role('button',name='退出后台').click(); page.get_by_role('heading',name='登录后台').wait_for()
            context.close()
            browser.close()

    def test_11_all_groups_tasks_positions_and_independent_documents(self):
        import product_details as docs
        pairs=set(); sampled=[]
        for g in range(1,5):
            for block in 'AB':
                for swapped in (0,1):
                    client,state=self.forced(g,block); pid=state['participant_id']; sampled.append(pid)
                    # Enumerate both display orders in an isolated test DB only.
                    with closing(sqlite3.connect(self.data/'study2.sqlite3')) as conn:
                        conn.execute('UPDATE participants SET swap_bits=? WHERE id=?',(str(swapped)*8,pid)); conn.commit()
                    client.request('/api/viewed',{}); _,state=client.request('/api/attributes',{})
                    self.assertEqual(state['phase'],'choice')
                    while state['phase']=='choice':
                        tid=state['task_id']; original=BY_ID[tid]
                        for alt in ('A','B'):
                            offer=state[alt.lower()]
                            expected=original['b' if (alt=='A')==bool(swapped) else 'a']
                            self.assertEqual(offer,expected)
                            pairs.add((offer['verification'],offer['quality']))
                            for kind,field in (('environment','verification'),('quality','quality')):
                                eid=uuid.uuid4().hex
                                payload=dict(event_id=eid,task_id=tid,alternative=alt,kind=kind)
                                code,doc=client.request('/api/details/open',payload); self.assertEqual(code,200,doc)
                                self.assertEqual(doc['base'],docs.BASE[kind]); self.assertEqual(doc['extra'],docs.EXTRA[kind] if offer[field] else None)
                                self.assertEqual(client.request('/api/details/open',payload)[0],200)
                                code,result=client.request('/api/details/progress',dict(event_id=eid,shown=True,duration_ms=0,closed=True,reason='close'))
                                self.assertEqual(code,200,result)
                                row=self.db('SELECT * FROM detail_views WHERE event_id=?',(eid,))[0]
                                self.assertEqual(row['level'],offer[field]); self.assertEqual(row['alternative'],alt); self.assertEqual(row['task_id'],tid)
                        _,state=client.request('/api/answer',dict(task_id=tid,choice='N'))
                    self.assertEqual(state['phase'],'survey')
                    self.assertEqual(client.request('/api/finish',SURVEY)[0],200)
                    self.assertEqual(client.request('/api/details/open',dict(event_id=uuid.uuid4().hex,task_id=tid,alternative='A',kind='quality'))[0],400)
        self.assertEqual(pairs,{(0,0),(0,1),(1,0),(1,1)})
        bundle=self.bundle(); longs=self.rows(bundle['choice_long.csv'])
        for r in longs:
            if r['participant_id'] not in sampled: continue
            if r['alternative']=='N':
                self.assertTrue(all(r[k]=='' for k in ('viewed_environment_details','viewed_quality_details','environment_details_view_duration','quality_details_view_duration')))
            else:
                self.assertEqual(r['viewed_environment_details'],'1'); self.assertEqual(r['viewed_quality_details'],'1')
                self.assertEqual(float(r['environment_details_view_duration']),0)
                self.assertEqual(float(r['quality_details_view_duration']),0)

    def test_12_duration_validation_export_and_import_process_variables(self):
        client,state=self.forced(1,'A'); pid=state['participant_id']; client.request('/api/viewed',{}); _,state=client.request('/api/attributes',{})
        tid=state['task_id']; eid=uuid.uuid4().hex
        self.assertEqual(client.request('/api/details/open',dict(event_id=eid,task_id='T99',alternative='A',kind='environment'))[0],400)
        self.assertEqual(client.request('/api/details/open',dict(event_id=eid,task_id=tid,alternative='N',kind='environment'))[0],400)
        self.assertEqual(client.request('/api/details/open',dict(event_id=eid,task_id=tid,alternative='A',kind='environment'))[0],200)
        # An unacknowledged document request is not counted as an actual view.
        import detail_tracking as dt
        with closing(sqlite3.connect(self.data/'study2.sqlite3')) as conn:
            conn.row_factory=sqlite3.Row
            self.assertEqual(dt.metrics(conn,pid,tid,'A')['viewed_environment_details'],0)
        time.sleep(.05)
        report=dict(event_id=eid,shown=True,duration_ms=30,closed=False,reason='heartbeat')
        self.assertEqual(client.request('/api/details/progress',report)[0],200)
        self.assertEqual(client.request('/api/details/progress',report)[0],200)
        self.assertEqual(client.request('/api/details/progress',{**report,'duration_ms':-1})[0],400)
        self.assertEqual(Client(self.base).request('/api/details/progress',report)[0],401)
        stranger,_=self.forced(2,'A'); self.assertEqual(stranger.request('/api/details/progress',report)[0],400)
        client.request('/api/details/progress',{**report,'duration_ms':40,'closed':True,'reason':'close'})
        client.request('/api/answer',dict(task_id=tid,choice='A'))
        bundle=self.bundle(); rows=self.rows(bundle['choice_long.csv']); a=next(r for r in rows if r['participant_id']==pid and r['task_id']==tid and r['alternative']=='A')
        self.assertEqual(a['viewed_environment_details'],'1'); self.assertEqual(a['viewed_quality_details'],'0')
        self.assertAlmostEqual(float(a['environment_details_view_duration']),.04,places=3)
        self.assertEqual(float(a['quality_details_view_duration']),0)
        # Export/import preserves summaries and per-open audit timestamps.
        _,base=self.launch(Path(self.temp.name)/'process-import'); admin=Client(base); admin.login()
        code,r=self.preview(admin,bundle,kinds=('participants','choices','choice_long','detail_views'))
        self.assertEqual(code,200,r); self.assertEqual(r['error_count'],0,r)
        self.assertEqual(admin.request('/api/admin/import/commit',dict(batch_id=r['batch_id'],confirm=True))[0],200)
        imported=self.bundle(base); imported_rows=self.rows(imported['choice_long.csv'])
        after=next(x for x in imported_rows if x['source_participant_id']==pid and x['task_id']==tid and x['alternative']=='A')
        for k in dt.FIELDS: self.assertEqual(float(after[k]),float(a[k]))
        self.assertEqual(len(self.rows(imported['detail_views.csv'])),len(self.rows(bundle['detail_views.csv'])))
        _,same=self.preview(admin,bundle,kinds=('participants','choices','choice_long','detail_views')); self.assertEqual(same['error_count'],0,same)
        bad=copy.deepcopy(bundle); raw=self.rows(bad['detail_views.csv']); raw[0]['level']=str(1-int(raw[0]['level'])); bad['detail_views.csv']=self.encoded(raw)
        self.assertGreater(self.preview(admin,bad,kinds=('participants','choices','choice_long','detail_views'))[1]['error_count'],0)

    def test_13_browser_panels_visible_time_offline_refresh_and_debrief(self):
        from playwright.sync_api import sync_playwright
        import product_details as docs
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True); context=browser.new_context(viewport=dict(width=390,height=844)); page=context.new_page(); errors=[]
            page.on('pageerror',lambda exc:errors.append(str(exc)))
            auth=context.request.post(self.base+'/api/admin/login',data=dict(username='researcher',password=PASSWORD)).json()
            state=context.request.post(self.base+'/api/admin/demo',data=dict(group=4,block='B'),headers={'X-CSRF-Token':auth['csrf']}).json(); pid=state['participant_id']
            page.goto(self.base); page.get_by_role('button',name='我已浏览，继续').click(); page.get_by_role('button',name='了解了，开始比较商品').click(); page.locator('.document-link').first.wait_for()
            actual=context.request.get(self.base+'/api/state').json(); tid=actual['task_id']; prices=page.locator('.price').all_text_contents()
            style=page.locator('.document-link').evaluate_all('(els)=>els.map(el=>{const c=getComputedStyle(el);return [c.color,c.backgroundColor,c.fontFamily,c.fontSize].join("|")})'); self.assertEqual(len(set(style)),1)
            bases={}; debriefs=[]
            for kind in ('environment','quality'):
                for alt in ('A','B'):
                    page.locator(f'.document-link[data-alternative="{alt}"][data-kind="{kind}"]').click(); page.locator('#detail-dialog').wait_for(state='visible')
                    base=page.locator('.document-base').inner_html()
                    if kind in bases: self.assertEqual(base,bases[kind])
                    bases[kind]=base
                    expected=actual[alt.lower()]['verification' if kind=='environment' else 'quality']
                    self.assertEqual(page.locator('.document-extra').count(),expected)
                    self.assertIn('研究用模拟资料',page.locator('.simulation-notice').inner_text())
                    if kind=='environment' and alt=='A':
                        page.wait_for_timeout(160)
                        page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
                        page.wait_for_timeout(1000)
                        page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});document.dispatchEvent(new Event('visibilitychange'))")
                        page.wait_for_timeout(160)
                    else: page.wait_for_timeout(80)
                    if kind=='quality' and alt=='A': context.set_offline(True)
                    page.screenshot(path=str(ROOT/'test-results'/f'details-{kind}-{alt}.png'),full_page=True)
                    if expected:
                        page.locator('.document-extra h3').scroll_into_view_if_needed()
                        self.assertTrue(page.locator('.document-extra h3').is_visible())
                        self.assertTrue(page.locator('#detail-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth'))
                        page.screenshot(path=str(ROOT/'test-results'/f'details-{kind}-{alt}-extra.png'),full_page=True)
                    page.get_by_role('button',name='关闭详情').click(); page.locator('#detail-dialog').wait_for(state='hidden')
                    if kind=='quality' and alt=='A':
                        self.assertTrue(page.evaluate("Object.keys(localStorage).some(k=>k.startsWith('study2-detail-pending:'))"))
                        context.set_offline(False); page.reload(); page.locator('.document-link').first.wait_for()
                    self.assertEqual(page.locator('.price').all_text_contents(),prices)
            # Page refresh closes and flushes an open panel without losing the task.
            page.locator('.document-link').first.click(); page.locator('#detail-dialog').wait_for(state='visible'); page.reload(); page.locator('.document-link').first.wait_for()
            self.assertEqual(context.request.get(self.base+'/api/state').json()['task_id'],tid)
            page.locator('[data-choice="A"]').click(); page.get_by_role('button',name='确认选择并继续').click(); page.locator('.progress-head').get_by_text('2/8',exact=True).wait_for()
            for n in range(2,9):
                page.locator('[data-choice="N"]').click(); page.get_by_role('button',name='确认选择并继续').click()
                if n<8: page.locator('.progress-head').get_by_text(f'{n+1}/8',exact=True).wait_for()
            page.locator('#age').fill('29')
            for k,v in SURVEY.items():
                if k!='age': page.locator('#'+k).select_option(v)
            page.get_by_role('button',name='提交问卷').click(); page.locator('.debrief').wait_for()
            self.assertEqual(page.locator('.debrief p').inner_text(),docs.DEBRIEF)
            rows=self.db('SELECT * FROM detail_views WHERE participant_id=?',(pid,)); self.assertEqual(len(rows),5)
            self.assertTrue(all(r['shown_at'] and r['closed_at'] for r in rows))
            first=min((r for r in rows if r['kind']=='environment' and r['alternative']=='A'),key=lambda r:r['opened_at'])
            self.assertGreaterEqual(first['duration_ms'],280); self.assertLess(first['duration_ms'],950)
            self.assertTrue(any(r['close_reason']=='pagehide' for r in rows))
            self.assertEqual(errors,[]); context.close(); browser.close()

if __name__=='__main__': unittest.main(verbosity=2)
