"""Locked multi-version designs; historical task configurations remain immutable."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
LEGACY_VERSION='study2-16-v1'

@dataclass
class Design:
    config:dict
    raw:bytes
    tasks:list

    @property
    def version(self):return self.config['version']
    @property
    def task_hash(self):return self.config['task_sha256']
    @property
    def total(self):return self.config['tasks_per_participant']
    @property
    def volume(self):return self.config['product_volume_ml']
    @property
    def by_id(self):return {t['id']:t for t in self.tasks}
    @property
    def by_block(self):return {b:[t for t in self.tasks if t['block']==b] for b in self.config['blocks']}
    def offer(self,raw):
        o=dict(raw)
        o['price_level']=self.config['levels']['price'].index(o['price'])+1
        o['product_volume_ml']=self.volume
        return o

def load(path):
    cfg=json.loads(path.read_text(encoding='utf-8'));raw=(ROOT/cfg['task_file']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=cfg['task_sha256']:raise RuntimeError('题目哈希与锁定设计不一致：'+cfg['version'])
    tasks=json.loads(raw);d=Design(cfg,raw,tasks)
    assert len(d.by_id)==len(tasks)==cfg['task_count']==d.total*len(cfg['blocks'])
    assert all(len(ts)==d.total for ts in d.by_block.values())
    for t in tasks:
        for o in (t['a'],t['b']):
            assert all(type(o[k]) is int and o[k] in levels for k,levels in cfg['levels'].items())
            normalized=d.offer(o)
            assert all(k not in o or o[k]==normalized[k] for k in ('price_level','product_volume_ml'))
    return d

ACTIVE=load(ROOT/'config/design_config.json')
LEGACY=load(ROOT/'designs/legacy_v1_config.json')
DESIGNS={d.version:d for d in (LEGACY,ACTIVE)}

def get(version):
    if version not in DESIGNS:raise ValueError('未知设计版本，禁止静默混合')
    return DESIGNS[version]

def formal_allowed(version=None):
    version=version or ACTIVE.version
    if version!=ACTIVE.version:return False
    approval=json.loads((ROOT/'config/design_approval.json').read_text(encoding='utf-8'))
    return bool(approval.get('design_version')==version and approval.get('task_sha256')==ACTIVE.task_hash and
                approval.get('researcher_approved') is True and approval.get('pilot_completed') is True and
                str(approval.get('pilot_reference','')).strip())

def require_formal(version=None):
    if not formal_allowed(version):raise ValueError('新版1 L设计尚未获得研究者确认及预测试完成记录，formal收数和正式同步均锁定')
