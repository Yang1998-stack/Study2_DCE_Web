"""Compatible, additive persistence and researcher-only data interchange.

No input choice is ever imputed. Original participant/choice columns are retained.
"""
import base64
import csv
import hashlib
import io
import itertools
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
import zipfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import design_registry as registry

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv('DCE_DATA_DIR', str(ROOT / 'data'))).resolve()
DB = DATA / 'study2.sqlite3'
LOCK = threading.RLock()
DESIGN = registry.ACTIVE.config
VERSION = DESIGN['version']
TASK_BYTES = registry.ACTIVE.raw
TASK_HASH = hashlib.sha256(TASK_BYTES).hexdigest()
if TASK_HASH != DESIGN['task_sha256']:
    raise RuntimeError('题目文件哈希与锁定设计不一致。请恢复原题目；新设计应另设版本。')
TASKS = json.loads(TASK_BYTES)
BY_ID = {t['id']: t for t in TASKS}
BY_BLOCK = {b: [t for t in TASKS if t['block'] == b] for b in DESIGN['blocks']}
TOTAL = DESIGN['tasks_per_participant']
assert len(BY_ID) == len(TASKS) == DESIGN['task_count']
assert DESIGN['task_count'] == TOTAL * len(DESIGN['blocks'])
assert all(len(t) == TOTAL for t in BY_BLOCK.values())
assert all(o[k] in DESIGN['levels'][k] for t in TASKS for o in (t['a'], t['b']) for k in DESIGN['levels'])
MODES = ('demo', 'pilot', 'formal')
SURVEY = {
    'gender': {'female', 'male', 'other', 'undisclosed'},
    'education': {'highschool', 'college', 'bachelor', 'masterplus', 'undisclosed'},
    'online_purchase': {'monthly1', 'monthly2to3', 'weekly1plus', 'undisclosed'},
    'plant_based_purchase': {'yes', 'no', 'unsure'},
    'manip_visual': {'chart', 'nature', 'unsure'},
    'manip_ai': {'yes', 'no', 'unsure'},
}

def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def stimuli():
    return {k: digest((ROOT / 'static' / 'stimuli' / f'{k}.jpg').read_bytes())
            if (ROOT / 'static' / 'stimuli' / f'{k}.jpg').is_file() else None for k in ('chart', 'nature')}

def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    return c

@contextmanager
def db():
    with closing(connect()) as c:
        with c:
            yield c

def backup(tag='scheduled'):
    folder = DATA / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}_{tag}.sqlite3'
    with closing(connect()) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    return target

def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        with db() as c:
            cols = {r[1] for r in c.execute('PRAGMA table_info(participants)')}
            tracked = c.execute("SELECT 1 FROM sqlite_master WHERE name='detail_views'").fetchone()
            synced = c.execute("SELECT 1 FROM sqlite_master WHERE name='qf_submissions'").fetchone()
            has_designs=c.execute("SELECT 1 FROM sqlite_master WHERE name='designs'").fetchone()
            registered=c.execute('SELECT 1 FROM designs WHERE version=?',(VERSION,)).fetchone() if has_designs else None
        if cols and 'design_version' not in cols:
            backup('before_upgrade')
        elif cols and not tracked:
            backup('before_detail_tracking')
        elif cols and not synced:
            backup('before_quickform_schema')
        elif cols and not registered:
            backup('before_design_upgrade')
    instance_file = DATA / 'instance_id.txt'
    if not instance_file.exists():
        instance_file.write_text(str(uuid.uuid4()), encoding='utf-8')
    instance = instance_file.read_text(encoding='utf-8').strip()
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS participants (
          id TEXT PRIMARY KEY, token_digest TEXT NOT NULL UNIQUE, mode TEXT NOT NULL,
          group_code INTEGER NOT NULL, block TEXT NOT NULL, swap_bits TEXT NOT NULL,
          task_order TEXT NOT NULL, created_at TEXT NOT NULL, stimulus_end_at TEXT,
          completed_at TEXT, age INTEGER, gender TEXT, education TEXT, online_purchase TEXT,
          plant_based_purchase TEXT, manip_visual TEXT, manip_ai TEXT
        );
        CREATE TABLE IF NOT EXISTS choices (
          participant_id TEXT NOT NULL REFERENCES participants(id), task_id TEXT NOT NULL,
          displayed_choice TEXT NOT NULL, answered_at TEXT NOT NULL,
          PRIMARY KEY(participant_id,task_id)
        );
        CREATE INDEX IF NOT EXISTS idx_choices_participant ON choices(participant_id);
        CREATE TABLE IF NOT EXISTS task_views (
          participant_id TEXT NOT NULL REFERENCES participants(id), task_id TEXT NOT NULL,
          started_at TEXT NOT NULL, PRIMARY KEY(participant_id,task_id)
        );
        CREATE TABLE IF NOT EXISTS designs (
          version TEXT PRIMARY KEY, task_hash TEXT NOT NULL, tasks_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_sessions (
          digest TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS invitations (
          digest TEXT PRIMARY KEY, mode TEXT NOT NULL, used_by TEXT UNIQUE, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS import_batches (
          id TEXT PRIMARY KEY, created_at TEXT NOT NULL, mode TEXT NOT NULL, design_version TEXT NOT NULL,
          status TEXT NOT NULL, owner TEXT NOT NULL, report TEXT NOT NULL, committed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS review_log (
          id INTEGER PRIMARY KEY, participant_id TEXT NOT NULL, status TEXT NOT NULL,
          note TEXT NOT NULL, reviewed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS choice_process (
          participant_id TEXT NOT NULL REFERENCES participants(id),task_id TEXT NOT NULL,alternative TEXT NOT NULL,
          content_version TEXT NOT NULL,tracking_started_at TEXT,data_origin TEXT NOT NULL,
          viewed_environment_details INTEGER,viewed_quality_details INTEGER,
          environment_details_view_duration REAL,quality_details_view_duration REAL,
          PRIMARY KEY(participant_id,task_id,alternative)
        );
        CREATE TABLE IF NOT EXISTS detail_views (
          event_id TEXT PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES participants(id),task_id TEXT NOT NULL,
          alternative TEXT NOT NULL,kind TEXT NOT NULL,level INTEGER NOT NULL,content_version TEXT NOT NULL,
          opened_at TEXT NOT NULL,shown_at TEXT,updated_at TEXT NOT NULL,closed_at TEXT,
          duration_ms INTEGER NOT NULL DEFAULT 0,close_reason TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_detail_task ON detail_views(participant_id,task_id,alternative);
        ''')
        additions = {
            'design_version': 'TEXT', 'task_hash': 'TEXT', 'source_instance': 'TEXT',
            'source_participant_id': 'TEXT', 'stimulus_versions': 'TEXT',
            'stimulus_started_at': 'TEXT', 'attributes_seen_at': 'TEXT',
            'dce_started_at': 'TEXT', 'dce_completed_at': 'TEXT',
            'validation_status': "TEXT NOT NULL DEFAULT 'unreviewed'",
            'provenance': "TEXT NOT NULL DEFAULT 'legacy'", 'consent_version': 'TEXT',
        }
        columns = {r[1] for r in c.execute('PRAGMA table_info(participants)')}
        for key, definition in additions.items():
            if key not in columns:
                c.execute(f'ALTER TABLE participants ADD COLUMN {key} {definition}')
        # Missing metadata belongs to the original runtime, never the new design.
        c.execute('UPDATE participants SET design_version=?,task_hash=?,source_instance=?,source_participant_id=id WHERE design_version IS NULL',
                  (registry.LEGACY.version, registry.LEGACY.task_hash, instance))
        # Legacy times and historical advertisement versions remain unknown (NULL).
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_source_participant ON participants(source_instance,source_participant_id,mode)')
        for d in registry.DESIGNS.values():
            previous = c.execute('SELECT task_hash FROM designs WHERE version=?', (d.version,)).fetchone()
            if previous and previous[0] != d.task_hash:raise RuntimeError('同一设计版本的题目配置已改变，拒绝启动')
            c.execute('INSERT OR IGNORE INTO designs VALUES (?,?,?)', (d.version,d.task_hash,d.raw.decode('utf-8')))
        import quickform_sync
        quickform_sync.init_schema(c)

def instance_id():
    return (DATA / 'instance_id.txt').read_text(encoding='utf-8').strip()

def count_choices(c, pid):
    return c.execute('SELECT COUNT(*) FROM choices WHERE participant_id=?', (pid,)).fetchone()[0]

def offers(p, tid):
    design=registry.get(p['design_version'])
    order = json.loads(p['task_order'])
    pos = order.index(tid)
    t = design.by_id[tid]
    swapped = p['swap_bits'][pos] == '1'
    return pos + 1, swapped, design.offer(t['b'] if swapped else t['a']), design.offer(t['a'] if swapped else t['b'])

def seconds(start, end):
    if not start or not end:
        return None
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 3)

def records(mode, version=VERSION, c=None):
    import detail_tracking as dt
    import quickform_payload as qm
    design=registry.get(version);BY_ID=design.by_id
    if mode not in MODES:raise ValueError('请选择合法的数据模式和设计版本')
    if c is None:
        with db() as conn:
            conn.execute('BEGIN')  # Consistent read snapshot for statistics and exports.
            return records(mode, version, conn)
    parts = [dict(r) for r in c.execute('SELECT * FROM participants WHERE mode=? AND design_version=? ORDER BY created_at,id', (mode, version))]
    pres, ares, longs = [], [], []
    for p in parts:
        answers = {r['task_id']: dict(r) for r in c.execute('SELECT * FROM choices WHERE participant_id=?', (p['id'],))}
        starts = {r['task_id']: r['started_at'] for r in c.execute('SELECT * FROM task_views WHERE participant_id=?', (p['id'],))}
        shared = dict(participant_id=p['id'],participant_uuid=qm.participant_uuid(p), mode=p['mode'], design_version=p['design_version'], task_hash=p['task_hash'],
                      source_instance=p['source_instance'], source_participant_id=p['source_participant_id'],
                      group_code=f'G{p["group_code"]}', visual=int(p['group_code'] in (1, 3)),
                      ai_disclosure=int(p['group_code'] in (3, 4)), block=p['block'])
        pr = dict(shared, product_volume_ml=design.volume,started_at=p['created_at'], **{k: p[k] for k in (
            'task_order', 'swap_bits', 'stimulus_started_at', 'stimulus_end_at', 'attributes_seen_at',
            'dce_started_at', 'dce_completed_at', 'completed_at', 'age', *SURVEY,
            'validation_status', 'provenance', 'stimulus_versions', 'consent_version')},
            n_choices=len(answers), completion_status='completed' if p['completed_at'] else 'incomplete',
            total_seconds=seconds(p['created_at'], p['completed_at']),
            dce_seconds=seconds(p['dce_started_at'], p['dce_completed_at']))
        pres.append(pr)
        for tid in json.loads(p['task_order']):
            if tid not in answers:
                continue
            answer = answers[tid]
            pos, swap, a, b = offers(p, tid)
            for alt,o in (('A',a),('B',b)):
                saved=c.execute('SELECT * FROM choice_products WHERE participant_id=? AND task_id=? AND alternative=?',(p['id'],tid,alt)).fetchone()
                if saved and (saved['price_yuan']!=o['price'] or saved['price_level']!=o['price_level'] or saved['product_volume_ml']!=o['product_volume_ml'] or saved['origin_import']!=o['origin'] or saved['third_party_verification']!=o['verification'] or saved['batch_quality_report']!=o['quality']):
                    raise ValueError('商品快照与分配记录不一致，请研究者核查')
            cr = dict(shared, product_volume_ml=design.volume,task_id=tid, position=pos, swapped=int(swap), displayed_choice=answer['displayed_choice'],
                      started_at=starts.get(tid), answered_at=answer['answered_at'])
            process={alt:dt.metrics(c,p['id'],tid,alt) for alt in ('A','B')}
            cr.update(dt.aggregate(process['A'],process['B']))
            for alt in ('A','B'):
                cr.update({alt.lower()+'_'+k:v for k,v in process[alt].items()})
            for label, o in (('a', a), ('b', b), ('original_a', design.offer(BY_ID[tid]['a'])), ('original_b', design.offer(BY_ID[tid]['b']))):
                cr.update({f'{label}_{k}': v for k, v in o.items()})
            ares.append(cr)
            for label, o in (('A', a), ('B', b), ('N', None)):
                longs.append(dict(shared, choice_set_id=f'{p["id"]}_{tid}', task_id=tid, position=pos, swapped=int(swap),
                                  alternative=label, choice=int(answer['displayed_choice'] == label),
                                  origin_import=o['origin'] if o else None,
                                  third_party_verification=o['verification'] if o else None,
                                  batch_quality_report=o['quality'] if o else None,
                                  price_yuan=o['price'] if o else None, opt_out=int(label == 'N'),
                                  price_level=o['price_level'] if o else None,product_volume_ml=o['product_volume_ml'] if o else None,
                                  started_at=starts.get(tid), answered_at=answer['answered_at'],
                                  **(process[label] if label!='N' else dict.fromkeys(dt.FIELDS))))
    for row in longs:
        row.update(alternative_id=row['alternative'],chosen=row['choice'],origin=row['origin_import'],
                   environmental_verification=row['third_party_verification'],quality_information=row['batch_quality_report'],price=row['price_yuan'],
                   visual_type='环境数据图表型' if row['visual'] else '自然场景型',dce_block=row['block'])
    return pres, ares, longs

PART_COLS = ['participant_id','mode','design_version','task_hash','source_instance','source_participant_id','group_code','visual','ai_disclosure','block','started_at','task_order','swap_bits','stimulus_started_at','stimulus_end_at','attributes_seen_at','dce_started_at','dce_completed_at','completed_at','age',*SURVEY,'validation_status','provenance','stimulus_versions','consent_version','n_choices','completion_status','total_seconds','dce_seconds']
SHARED_COLS = PART_COLS[:10]
OFFER_FIELDS=('origin','verification','quality','price','price_level','product_volume_ml')
CHOICE_COLS = [*SHARED_COLS,'task_id','position','swapped','displayed_choice','started_at','answered_at',*[f'{l}_{k}' for l in ('a','b','original_a','original_b') for k in OFFER_FIELDS]]
LONG_COLS = [*SHARED_COLS,'choice_set_id','task_id','position','swapped','alternative','choice','origin_import','third_party_verification','batch_quality_report','price_yuan','opt_out','started_at','answered_at']
PROCESS_COLS = ['viewed_environment_details','viewed_quality_details','environment_details_view_duration','quality_details_view_duration']
CHOICE_COLS += PROCESS_COLS + [f'{a}_{k}' for a in ('a','b') for k in PROCESS_COLS]
LONG_COLS += PROCESS_COLS
PART_COLS += ['participant_uuid','product_volume_ml']
CHOICE_COLS += ['participant_uuid','product_volume_ml']
LONG_COLS += ['participant_uuid','alternative_id','chosen','origin','environmental_verification','quality_information','price','visual_type','dce_block','price_level','product_volume_ml']

def csv_bytes(cols, rows):
    f = io.StringIO(newline='')
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    return f.getvalue().encode('utf-8-sig')

def export_files(mode, version=VERSION):
    import detail_tracking as dt
    import product_details as docs
    design=registry.get(version)
    with db() as c:
        c.execute('BEGIN')
        pres, ares, longs = records(mode, version,c)
        views = dt.event_rows(c,mode,version)
    manifest = dict(exported_at_utc=now(), mode=mode, design_version=version, task_design_sha256=design.task_hash,product_volume_ml=design.volume,
                    stimulus_sha256_current=stimuli(), stimulus_versions_observed=sorted({p['stimulus_versions'] or 'unknown_legacy' for p in pres}),
                    source_instance=instance_id(), schema_version=5, participants=len(pres), choices=len(ares),
                    detail_content_version=design.config['detail_content_version'], detail_views=len(views),
                    detail_content_sha256=digest((ROOT/'app/product_details.py').read_bytes()) if version==VERSION else None,
                    process_variables='Alternative A/B: recorded opens and cumulative foreground-visible seconds; N and untracked legacy records are blank. Choices: OR/sum across A/B. Process variables are observational, not causal verification effects.',
                    choice_alternatives=len(longs), opt_out_encoding='N: opt_out=1; product attributes and price are blank, not a free product',
                    validity='validation_status=valid only after explicit researcher review; completion alone does not imply validity',
                    legacy='No historical advertisement hashes or missing timestamps are invented')
    return {'participants.csv': csv_bytes(PART_COLS, pres), 'choices.csv': csv_bytes(CHOICE_COLS, ares),
            'choice_long.csv': csv_bytes(LONG_COLS, longs),
            'detail_views.csv': csv_bytes(dt.EVENT_COLS, views),
            'manifest.json': json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')}

def export_zip(mode, version=VERSION):
    f = io.BytesIO()
    with zipfile.ZipFile(f, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in export_files(mode, version).items():
            z.writestr(name, data)
    return f.getvalue()

def statistics(mode, version):
    design=registry.get(version);BY_BLOCK=design.by_block;BY_ID=design.by_id
    pres, answers, _ = records(mode, version)
    def tally(rows):
        n = len(rows)
        complete = sum(bool(p['completed_at']) for p in rows)
        return dict(started=n, completed=complete, incomplete=n-complete,
                    valid=sum(p['validation_status'] == 'valid' for p in rows),
                    completion_rate=round(complete/n, 4) if n else 0)
    return dict(totals=tally(pres), groups={f'G{g}': tally([p for p in pres if p['group_code'] == f'G{g}']) for g in range(1,5)},
                blocks={b: sum(p['block'] == b for p in pres) for b in BY_BLOCK},
                group_blocks={f'G{g}': {b: sum(p['group_code']==f'G{g}' and p['block']==b for p in pres) for b in BY_BLOCK} for g in range(1,5)},
                tasks={tid: {label: sum(a['task_id']==tid and a['displayed_choice']==label for a in answers) for label in ('A','B','N')} for tid in BY_ID},
                participants=pres, mode=mode, design_version=version,
                note='已开始=同意并建立会话；已完成=8题及后续问卷全部提交；有效=研究者手动审核。导入来源会计入所选模式汇总。')

def timestamp(value, label, required=False):
    if not value:
        if required: raise ValueError(f'{label}缺失')
        return None
    try:
        t = datetime.fromisoformat(value)
        if t.tzinfo is None: raise ValueError()
    except (ValueError, TypeError):
        raise ValueError(f'{label}必须是含时区的ISO时间')
    return value

def read_table(name, raw):
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('单个文件不得超过8 MiB')
    suffix = Path(name).suffix.lower()
    if suffix == '.csv':
        try:
            reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
            headers = reader.fieldnames or []
            rows = list(reader)
        except (UnicodeError, csv.Error):
            raise ValueError('CSV须使用UTF-8编码并包含字段名')
    elif suffix == '.xlsx':
        try:
            import openpyxl
        except ImportError:
            raise ValueError('XLSX兼容需先安装openpyxl；也可另存为UTF-8 CSV后上传')
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if sum(i.file_size for i in z.infolist()) > 40 * 1024 * 1024:
                    raise ValueError('XLSX解压体积过大')
            book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            sheet = book.active
            values = list(itertools.islice(sheet.iter_rows(values_only=True), 20002))
            if any(isinstance(v, str) and v.startswith('=') for row in values for v in row):
                raise ValueError('导入表不接受公式，请转换为纯值')
            headers = [str(v) if v is not None else '' for v in values[0]]
            rows = [{k: '' if v is None else str(v) for k,v in zip(headers,row)} for row in values[1:]]
            book.close()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('无效或受损的XLSX文件') from exc
    else:
        raise ValueError('仅支持CSV或XLSX，不接受压缩包及其他文件')
    if not headers or len(set(headers)) != len(headers) or any(not h for h in headers):
        raise ValueError('字段名缺失或重复')
    if len(rows) > 20000 or len(headers) > 100 or any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError('记录数/字段数超限或行列不齐（最多20000行、100列）')
    return headers, rows

def validate_bundle(tables, mode, version, c):
    import detail_tracking as dt
    design=registry.get(version);BY_BLOCK=design.by_block;BY_ID=design.by_id;TASK_HASH=design.task_hash;TOTAL=design.total
    if mode not in MODES:
        raise ValueError('导入目标模式/设计版本不合法')
    if 'participants' not in tables:
        raise ValueError('必须上传participants.csv；选择记录不能脱离参与者的分配和版本信息导入')
    errors, warnings, parts, by_input, raw_choices = [], [], [], {}, {}
    def check_part(r):
        required = ('participant_id','source_instance','source_participant_id','mode','design_version','task_hash','group_code','block','task_order','swap_bits','started_at','n_choices')
        if any(not r.get(k) for k in required):
            raise ValueError('缺少身份、来源实例、模式、设计哈希、顺序或交换信息；不能自动补齐旧版文件')
        if r['mode'] != mode or r['design_version'] != version or r['task_hash'] != TASK_HASH:
            raise ValueError('模式/设计版本/题目哈希与所选目标不一致，禁止合并')
        if 'product_volume_ml' in r and int(r['product_volume_ml'])!=design.volume:raise ValueError('商品规格与设计版本不一致')
        if r['group_code'] not in ('G1','G2','G3','G4') or r['block'] not in BY_BLOCK:
            raise ValueError('实验组或区组不合法')
        for k,expected in (('visual',int(r['group_code'] in ('G1','G3'))),('ai_disclosure',int(r['group_code'] in ('G3','G4')))):
            if k in r and r[k]!=str(expected): raise ValueError(f'{k}与广告组不一致')
        for k in ('participant_id','source_instance','source_participant_id'):
            if len(r[k]) > 128 or any(ord(x)<32 for x in r[k]) or r[k][0] in '=+-@':
                raise ValueError('身份或来源字段格式不合法')
        order = json.loads(r['task_order'])
        if not isinstance(order,list) or len(order)!=TOTAL or set(order)!={t['id'] for t in BY_BLOCK[r['block']]}:
            raise ValueError('实际题目顺序须恰好包含本区组的8道题且不能重复')
        if len(r['swap_bits'])!=TOTAL or set(r['swap_bits'])-{'0','1'}:
            raise ValueError('A/B位置交换编码不合法')
        time_keys=('started_at','stimulus_started_at','stimulus_end_at','attributes_seen_at','dce_started_at','dce_completed_at','completed_at')
        for k in time_keys:
            timestamp(r.get(k),k,k=='started_at')
        known=[r[k] for k in time_keys if r.get(k)]
        if any(seconds(a,b)<0 for a,b in zip(known,known[1:])):
            raise ValueError('参与者各阶段时间顺序不合法')
        if not 0 <= int(r['n_choices']) <= TOTAL:
            raise ValueError('已答题数不合法')
        if r.get('age') and (not r['age'].isdigit() or not 18<=int(r['age'])<=100):
            raise ValueError('年龄格式不合法')
        for k, levels in SURVEY.items():
            if r.get(k) and r[k] not in levels: raise ValueError(f'{k}编码不合法')
        if r.get('consent_version') and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}',r['consent_version']):
            raise ValueError('consent_version须为简短版本编号，不能包含公式或控制字符')
        if r.get('completed_at') and (int(r['n_choices'])!=TOTAL or not r.get('age') or any(not r.get(k) for k in SURVEY)):
            raise ValueError('完成标记与8题/后续问卷不一致')
        if r.get('stimulus_versions'):
            hashes=json.loads(r['stimulus_versions'])
            if not isinstance(hashes,dict) or set(hashes)!={'chart','nature'} or any(v is not None and (not isinstance(v,str) or len(v)!=64 or set(v)-set('0123456789abcdef')) for v in hashes.values()):
                raise ValueError('广告文件版本格式不合法')
        r = dict(r)
        source_key=(r['source_instance'],r['source_participant_id'],mode)
        if source_key in {p['_source_key'] for p in parts} or r['participant_id'] in by_input:
            raise ValueError('文件内重复participant_id或来源身份')
        existing=c.execute('SELECT * FROM participants WHERE source_instance=? AND source_participant_id=? AND mode=?',source_key).fetchone()
        r['_source_key']=source_key
        r['_existing']=dict(existing) if existing else None
        r['_id']=existing['id'] if existing else 'imp_'+uuid.uuid5(uuid.NAMESPACE_URL,'\x1f'.join(source_key)).hex
        if existing:
            warnings.append(f'{r["participant_id"]}：相同来源身份已存在；核对一致后跳过，不覆盖原始记录')
        elif c.execute('SELECT 1 FROM participants WHERE id=?',(r['participant_id'],)).fetchone():
            warnings.append(f'{r["participant_id"]}：跨实例编号冲突，将映射为{r["_id"]}')
        return r
    for i,r in enumerate(tables['participants'],2):
        try:
            p=check_part(r); parts.append(p); by_input[p['participant_id']]=p
        except (ValueError, TypeError, KeyError) as e:
            errors.append(f'participants第{i}行：{e}')
    for kind in ('choices','choice_long'):
        seen={}
        for i,r in enumerate(tables.get(kind,[]),2):
            try:
                p=by_input.get(r.get('participant_id'))
                if not p: raise ValueError('找不到对应参与者或参与者记录不合法')
                if any(r.get(k)!=p.get(k) for k in ('mode','design_version','task_hash','source_instance','source_participant_id','group_code','block')):
                    raise ValueError('行内身份、分组、模式或版本与参与者不一致')
                for flag, expected in (('visual',int(p['group_code'] in ('G1','G3'))),('ai_disclosure',int(p['group_code'] in ('G3','G4')))):
                    if flag in r and r[flag]!=str(expected): raise ValueError(f'{flag}与广告组不一致')
                tid=r.get('task_id')
                if tid not in json.loads(p['task_order']): raise ValueError('任务编号不在本区组')
                pos,swap,a,b=offers(p,tid)
                if int(r.get('position',''))!=pos or int(r.get('swapped',''))!=int(swap):
                    raise ValueError('题序或显示位置与参与者分配不一致')
                timestamp(r.get('answered_at'),'answered_at',True)
                timestamp(r.get('started_at'),'started_at')
                if seconds(p['started_at'],r['answered_at'])<0 or (p.get('completed_at') and seconds(r['answered_at'],p['completed_at'])<0):
                    raise ValueError('答题时间超出参与者起止范围')
                if seconds(r.get('started_at'),r['answered_at']) is not None and seconds(r['started_at'],r['answered_at'])<0:
                    raise ValueError('提交时间早于开始时间')
                key=(p['participant_id'],tid)
                if kind=='choices':
                    if key in seen: raise ValueError('重复选择任务记录')
                    if r.get('displayed_choice') not in ('A','B','N'): raise ValueError('选择结果须为A/B/N')
                    for label,o in (('a',a),('b',b),('original_a',design.offer(BY_ID[tid]['a'])),('original_b',design.offer(BY_ID[tid]['b']))):
                        if any(int(r.get(f'{label}_{k}',''))!=v for k,v in o.items() if k in ('origin','verification','quality','price') or f'{label}_{k}' in r):
                            raise ValueError('商品属性编码与原始任务/显示交换不一致')
                    proc={alt:dt.parse_metrics(r,alt.lower()+'_') for alt in ('A','B')}
                    if any(r.get(k,'')!='' for k in dt.FIELDS) and dt.parse_metrics(r)!=dt.aggregate(proc['A'],proc['B']):
                        raise ValueError('题目级查看过程变量与A/B明细不一致')
                    seen[key]=dict(task_id=tid, displayed_choice=r['displayed_choice'], answered_at=r['answered_at'], started_at=r.get('started_at') or None,process=proc)
                else:
                    if r.get('choice_set_id')!=f'{p["participant_id"]}_{tid}':
                        raise ValueError('choice_set_id与参与者/任务编号不一致')
                    alt=r.get('alternative')
                    if alt not in ('A','B','N') or r.get('choice') not in ('0','1') or int(r.get('opt_out',''))!=int(alt=='N'):
                        raise ValueError('备选项、choice或不购买编码不合法')
                    attrs=('origin_import','third_party_verification','batch_quality_report','price_yuan')
                    if alt=='N':
                        if any(r.get(k,'') not in ('','0') for k in attrs): raise ValueError('不购买备选项属性不合法')
                        if any(r.get(k,'')!='' for k in ('price_level','product_volume_ml')):raise ValueError('不购买不是具有容量和价格水平的商品')
                        if any(r.get(k,'') not in ('','0') for k in dt.FIELDS): raise ValueError('不购买项没有商品资料查看行为')
                    else:
                        offer=a if alt=='A' else b
                        if any(int(r.get(k,''))!=offer[v] for k,v in zip(attrs,('origin','verification','quality','price'))):
                            raise ValueError('长格式属性与实际显示不一致')
                        for k in ('price_level','product_volume_ml'):
                            if k in r and int(r[k])!=offer[k]:raise ValueError('价格水平或商品规格与设计不一致')
                        dt.parse_metrics(r)
                    if key not in seen: seen[key]={}
                    if alt in seen[key]: raise ValueError('长格式重复备选项')
                    seen[key][alt]=r
            except (ValueError, TypeError, KeyError) as e:
                errors.append(f'{kind}第{i}行：{e}')
        if kind=='choice_long':
            normalized={}
            for key,rows in seen.items():
                if set(rows)!=set('ABN') or sum(int(r['choice']) for r in rows.values())!=1:
                    errors.append(f'{key}：每题必须有A/B/N三行且恰好一个choice=1'); continue
                if len({(r['answered_at'],r.get('started_at','')) for r in rows.values()})!=1:
                    errors.append(f'{key}：同一选择集时间不一致'); continue
                chosen=next(k for k,r in rows.items() if r['choice']=='1')
                normalized[key]=dict(task_id=key[1],displayed_choice=chosen,answered_at=rows[chosen]['answered_at'],started_at=rows[chosen].get('started_at') or None,
                                     process={alt:dt.parse_metrics(rows[alt]) for alt in ('A','B')})
            seen=normalized
        if kind in tables:
            if kind=='choice_long' and 'choices' in tables and raw_choices!=seen:
                errors.append('choices与choice_long记录不一致，拒绝导入')
            raw_choices=seen
    for p in parts:
        own={tid:a for (pid,tid),a in raw_choices.items() if pid==p['participant_id']}
        n=int(p['n_choices'])
        if len(own)!=n or set(own)!=set(json.loads(p['task_order'])[:n]):
            errors.append(f'{p["participant_id"]}：答题数量/任务顺序不匹配，须同时上传完整选择记录')
        existing=p['_existing']
        if existing:
            for field, value in (('group_code',int(p['group_code'][1:])),('block',p['block']),('swap_bits',p['swap_bits']),('task_order',p['task_order']),('design_version',version),('task_hash',TASK_HASH)):
                same = json.loads(existing[field])==json.loads(value) if field=='task_order' else existing[field]==value
                if not same: errors.append(f'{p["participant_id"]}：重复身份的{field}冲突，不覆盖')
            for field in ('completed_at','age',*SURVEY):
                if str(existing[field] if existing[field] is not None else '')!=str(p.get(field) or ''):
                    errors.append(f'{p["participant_id"]}：重复身份的{field}冲突，不覆盖')
            old={r['task_id']:dict(r) for r in c.execute('SELECT * FROM choices WHERE participant_id=?',(existing['id'],))}
            if set(old)!=set(own) or any(any(old[tid][k]!=a[k] for k in ('displayed_choice','answered_at')) for tid,a in own.items() if tid in old):
                errors.append(f'{p["participant_id"]}：重复身份的选择记录冲突；请保留原始数据并人工核查')
            for tid,a in own.items():
                for alt in ('A','B'):
                    if dt.metrics(c,existing['id'],tid,alt)!=a['process'][alt]:
                        errors.append(f'{p["participant_id"]}/{tid}/{alt}：重复身份的详情过程变量冲突，不覆盖')
    if 'detail_views' in tables:
        dt.validate_import_events(tables['detail_views'],parts,by_input,raw_choices,errors)
    elif any(v is not None for a in raw_choices.values() for proc in a['process'].values() for v in proc.values()):
        warnings.append('未上传detail_views.csv：保留四项汇总过程变量；逐次查看时间日志未随本次导入，请保留来源文件。')
    report=dict(errors=errors[:100], error_count=len(errors), warnings=warnings[:100], participants=len(parts),
                new_participants=sum(not p['_existing'] for p in parts), duplicates=sum(bool(p['_existing']) for p in parts),
                choices=len(raw_choices), detail_views=sum(len(p.get('_events',[])) for p in parts),mode=mode, design_version=version,
                note='同来源相同身份跳过；不同来源使用来源实例+原编号命名空间。导入有效性一律待本库研究者审核。')
    return report, parts, raw_choices

def preview_import(payload, owner):
    files=payload.get('files')
    mode=payload.get('mode'); version=payload.get('design_version')
    registry.get(version)
    if mode not in MODES: raise ValueError('导入目标模式/设计版本不合法')
    if not isinstance(files,list) or not 1<=len(files)<=4:
        raise ValueError('请选择1至4个表格文件（participants、choices/choice_long及可选detail_views）')
    batch=secrets.token_hex(16)
    folder=DATA/'imports'/batch
    tables={}; file_info=[]; raws=[]
    for f in files:
        if not isinstance(f,dict) or not isinstance(f.get('name'),str): raise ValueError('文件对象格式错误')
        name=f.get('name','')
        if '/' in name or '\\' in name: raise ValueError('文件名不能包含目录路径')
        kind=next((k for k in ('participants','choice_long','choices','detail_views') if name.lower().startswith(k)),None)
        if not kind or kind in tables: raise ValueError('文件名须以participants、choices、choice_long或detail_views开头，且每类只能一个')
        try: raw=base64.b64decode(f.get('data',''),validate=True)
        except (ValueError,TypeError): raise ValueError('文件编码不合法')
        safe=f'{kind}{Path(name).suffix.lower()}'
        if Path(name).suffix.lower() not in ('.csv','.xlsx') or len(raw)>8*1024*1024:
            raise ValueError('仅支持8 MiB以内的CSV/XLSX文件')
        raws.append((safe,raw))
        try:
            headers,rows=read_table(name,raw)
        except ValueError as exc:
            report=dict(errors=[str(exc)],error_count=1,files=file_info+[dict(name=safe,original_name=name,sha256=digest(raw))],mode=mode,design_version=version)
            archive_import(batch,mode,version,owner,raws,tables,report,'rejected')
            raise
        tables[kind]=rows
        file_info.append(dict(name=safe, original_name=name, rows=len(rows), fields=headers, sha256=digest(raw), sample=rows[:2]))
    try:
        with db() as c:
            report,_,_=validate_bundle(tables,mode,version,c)
    except ValueError as exc:
        report=dict(errors=[str(exc)],error_count=1,files=file_info,mode=mode,design_version=version)
        archive_import(batch,mode,version,owner,raws,tables,report,'rejected')
        raise
    report['files']=file_info
    archive_import(batch,mode,version,owner,raws,tables,report,'rejected' if report['errors'] else 'previewed')
    return dict(batch_id=batch,**report)

def archive_import(batch,mode,version,owner,raws,tables,report,status):
    folder=DATA/'imports'/batch
    folder.mkdir(parents=True)
    for name,raw in raws: (folder/name).write_bytes(raw)
    (folder/'tables.json').write_text(json.dumps(tables,ensure_ascii=False),encoding='utf-8')
    (folder/'preview.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with db() as c:
        c.execute('INSERT INTO import_batches VALUES (?,?,?,?,?,?,?,?)',(batch,now(),mode,version,status,owner,json.dumps(report,ensure_ascii=False),None))

def commit_import(batch,owner):
    import detail_tracking as dt
    if not isinstance(batch,str) or len(batch)!=32 or set(batch)-set('0123456789abcdef'):
        raise ValueError('导入批次编号不合法')
    with LOCK, db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM import_batches WHERE id=? AND owner=?',(batch,owner)).fetchone()
        if not row or row['status']!='previewed': raise ValueError('批次无效、未通过预览或已导入')
        if seconds(row['created_at'],now())>3600: raise ValueError('预览已过期，请重新上传核对')
        tables=json.loads((DATA/'imports'/batch/'tables.json').read_text(encoding='utf-8'))
        report,parts,answers=validate_bundle(tables,row['mode'],row['design_version'],c)
        if report['errors']: raise ValueError('数据已变化，请重新预览：'+report['errors'][0])
        for p in parts:
            if p['_existing']: continue
            values=dict(id=p['_id'],token_digest=digest(secrets.token_bytes(48)), mode=p['mode'],group_code=int(p['group_code'][1:]),
                        block=p['block'],swap_bits=p['swap_bits'],task_order=p['task_order'],created_at=p['started_at'],
                        design_version=p['design_version'],task_hash=p['task_hash'],source_instance=p['source_instance'],source_participant_id=p['source_participant_id'],
                        provenance='import:'+batch,validation_status='unreviewed')
            for k in ('stimulus_started_at','stimulus_end_at','attributes_seen_at','dce_started_at','dce_completed_at','completed_at','age',*SURVEY,'stimulus_versions','consent_version'):
                values[k]=p.get(k) or None
            c.execute(f'INSERT INTO participants ({",".join(values)}) VALUES ({",".join("?" for _ in values)})',list(values.values()))
            for (pid,tid),a in answers.items():
                if pid!=p['participant_id']: continue
                c.execute('INSERT INTO choices VALUES (?,?,?,?)',(p['_id'],tid,a['displayed_choice'],a['answered_at']))
                if a['started_at']:
                    c.execute('INSERT INTO task_views VALUES (?,?,?)',(p['_id'],tid,a['started_at']))
                import quickform_payload as qm
                imported=c.execute('SELECT * FROM participants WHERE id=?',(p['_id'],)).fetchone()
                qm.save_products(c,imported,tid,a['started_at'])
                for alt in ('A','B'): dt.save_summary(c,p['_id'],tid,alt,a['process'][alt])
            dt.save_import_events(c,p)
        c.execute('UPDATE import_batches SET status=?,committed_at=?,report=? WHERE id=?',('committed',now(),json.dumps(report,ensure_ascii=False),batch))
    (DATA/'imports'/batch/'commit.json').write_text(json.dumps(dict(committed_at=now(),**report),ensure_ascii=False,indent=2),encoding='utf-8')
    return report
