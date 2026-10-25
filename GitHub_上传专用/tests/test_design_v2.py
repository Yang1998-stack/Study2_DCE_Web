"""Numerical efficiency checks and strict multi-version/volume/formal safeguards."""
from contextlib import closing
import hashlib
import itertools
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import design_registry as registry
import storage as s
import quickform_sync as qf
import quickform_payload as qm
import product_details as docs
from scripts import design_dce_v2 as engine

class DesignV2(unittest.TestCase):
    def test_01_complete_candidate_universe_and_not_price_replacement(self):
        self.assertEqual(registry.ACTIVE.volume,1000)
        self.assertEqual(len(engine.PROFILES),24)
        self.assertEqual(set(map(tuple,engine.PROFILES)),set(itertools.product((0,1),(0,1),(0,1),(15,24,34))))
        self.assertEqual(len(s.TASKS),16);self.assertEqual([len(v) for v in s.BY_BLOCK.values()],[8,8])
        old=registry.LEGACY.tasks
        self.assertNotEqual([(t['a']['origin'],t['a']['verification'],t['a']['quality'],t['b']['origin'],t['b']['verification'],t['b']['quality']) for t in old],[(t['a']['origin'],t['a']['verification'],t['a']['quality'],t['b']['origin'],t['b']['verification'],t['b']['quality']) for t in s.TASKS])
        self.assertEqual(hashlib.sha256((s.ROOT/'designs/tasks_legacy_v1.json').read_bytes()).hexdigest(),'e695ba4d0098f5b17938cd121d7f4205893e4b627b5de655ae32fbeb3572d834')
        for t in s.TASKS:
            for o in (t['a'],t['b']):
                self.assertEqual(o['product_volume_ml'],1000);self.assertEqual(o['price'],(15,24,34)[o['price_level']-1])

    def test_02_fisher_rank_d_error_and_continuous_bound_independently_recomputed(self):
        report=json.loads((s.ROOT/'docs/design_v2/diagnostics.json').read_text(encoding='utf-8'))
        indices=[];profile_index={tuple(p):i for i,p in enumerate(engine.PROFILES)}
        for task in s.TASKS:
            pair=tuple(sorted(profile_index[tuple(task[k][a] for a in ('origin','verification','quality','price'))] for k in ('a','b')))
            self.assertIn(pair,engine.PAIRS);indices.append(engine.PAIRS.index(pair))
        info=engine.information(engine.PAIRS);m=info[indices].mean(axis=0)
        self.assertEqual(np.linalg.matrix_rank(m),12)
        self.assertAlmostEqual(np.exp(-np.linalg.slogdet(m)[1]/12),report['primary']['d_error'],places=10)
        ref=report['restricted_continuous_reference'];weights=np.array(ref['full_weights']);self.assertAlmostEqual(weights.sum(),1,places=10)
        upper_m=np.einsum('i,ijk->jk',weights,info);inverse=np.linalg.inv(upper_m)
        gap=max(np.einsum('ij,kji->k',inverse,info))-12
        self.assertLess(gap,2e-6)
        upper=np.linalg.slogdet(upper_m)[1]+max(gap,0)
        certified=float(np.exp((np.linalg.slogdet(m)[1]-upper)/12))
        self.assertGreater(certified,.98);self.assertAlmostEqual(certified,report['d_efficiency_lower_bound_restricted'],places=5)
        self.assertEqual(np.linalg.matrix_rank(engine.information(engine.PAIRS,categorical=False)[indices].mean(0)),11)
        self.assertEqual(np.linalg.matrix_rank(engine.information(engine.PAIRS,position=True)[indices].mean(0)),13)
        for b in ('A','B'):
            ids=[indices[i] for i,t in enumerate(s.TASKS) if t['block']==b]
            self.assertEqual(np.linalg.matrix_rank(info[ids].mean(0)),12)
            self.assertEqual(np.linalg.matrix_rank(engine.information(engine.PAIRS,interactions=False)[ids].mean(0)),6)

    def test_03_analytical_information_matches_numerical_expected_hessian(self):
        x=engine.matrix(engine.PAIRS[3],(-.5,.5),1);p=np.array([1/3]*3);analytic=x.T@(np.diag(p)-np.outer(p,p))@x
        def nll(beta):
            u=x@beta;mx=u.max();return np.log(np.exp(u-mx).sum())+mx-p@u
        h=1e-3;k=x.shape[1];numeric=np.zeros((k,k))
        for i in range(k):
            ei=np.zeros(k);ei[i]=h
            for j in range(k):
                ej=np.zeros(k);ej[j]=h
                numeric[i,j]=(nll(ei+ej)-nll(ei-ej)-nll(-ei+ej)+nll(-ei-ej))/(4*h*h)
        np.testing.assert_allclose(numeric,analytic,atol=2e-7)
        np.testing.assert_array_equal(x[2,:6],[0,0,0,0,0,1])

    def test_04_historical_exports_and_import_validation_are_version_separated(self):
        with tempfile.TemporaryDirectory() as temp,patch.multiple(s,DATA=Path(temp),DB=Path(temp)/'test.sqlite3'):
            s.init_db();d=registry.LEGACY;order=[t['id'] for t in d.by_block['A']]
            with s.db() as c:
                c.execute('''INSERT INTO participants(id,token_digest,mode,group_code,block,swap_bits,task_order,created_at,design_version,task_hash,source_instance,source_participant_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',('historical','digest','demo',1,'A','10000000',json.dumps(order),s.now(),d.version,d.task_hash,'old-instance','original'))
                c.execute('INSERT INTO choices VALUES (?,?,?,?)',('historical',order[0],'B',s.now()))
            parts,choices,longs=s.records('demo',d.version)
            self.assertEqual(len(parts),1);self.assertEqual(choices[0]['a_price'],d.by_id[order[0]]['b']['price'])
            self.assertEqual(parts[0]['product_volume_ml'],250)
            self.assertTrue(all(r['product_volume_ml']==250 for r in longs if r['alternative']!='N'))
            self.assertEqual(s.records('demo',s.VERSION),( [],[],[]))
            files=s.export_files('demo',d.version)
            tables={k:list(__import__('csv').DictReader(__import__('io').StringIO(files[k+'.csv'].decode('utf-8-sig')))) for k in ('participants','choices','choice_long')}
            with s.db() as c:
                report,_,_=s.validate_bundle(tables,'demo',d.version,c);self.assertEqual(report['error_count'],0,report)
                report,_,_=s.validate_bundle(tables,'demo',s.VERSION,c);self.assertGreater(report['error_count'],0)
            manifest=json.loads(files['manifest.json']);self.assertEqual(manifest['task_design_sha256'],d.task_hash)

    def test_05_approval_and_actual_formal_start_remain_blocked(self):
        self.assertFalse(registry.formal_allowed())
        with patch.dict(os.environ,{'QUICKFORM_FORMAL_ENABLED':'YES','DCE_ALLOW_FORMAL':'YES','QUICKFORM_ALLOW_LOCAL_TEST':'NO','QUICKFORM_API_URL':qf.DEFAULT_API_URL,'QUICKFORM_PILOT_API_URL':''}):
            self.assertFalse(qf.config('formal').enabled)
            with patch.object(qf,'send',side_effect=AssertionError('Must never POST while locked')):
                self.assertFalse(qf.dispatch_once(qf.Config('formal',qf.DEFAULT_API_URL,True,'manual config')))
        with tempfile.TemporaryDirectory() as temp:
            env={**os.environ,'DCE_DATA_DIR':temp,'DCE_MODE':'formal','DCE_ALLOW_FORMAL':'YES','QUICKFORM_FORMAL_ENABLED':'YES','DCE_SECURE_COOKIE':'1','QUICKFORM_ALLOW_LOCAL_TEST':'NO','QUICKFORM_API_URL':qf.DEFAULT_API_URL,'QUICKFORM_PILOT_API_URL':''}
            result=subprocess.run([sys.executable,'server.py'],cwd=s.ROOT,env=env,capture_output=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('预测试',result.stderr.decode(errors='replace'))

    def test_06_current_consumer_source_has_no_old_volume_or_price_grade(self):
        for path in ('static/app.js','static/index.html','static/details.js','app/product_details.py'):
            content=(s.ROOT/path).read_text(encoding='utf-8')
            for forbidden in ('250 mL','250mL','OAT250','ENV-250','平价','中端','高端'):
                self.assertNotIn(forbidden,content,path)
        for price in (15,24,34):
            for level in (0,1):
                self.assertEqual(docs.document('quality',level)['base'],docs.BASE['quality'])
        self.assertTrue(all('1 L' in qm.display(t['a'])['capacity'] for t in s.TASKS))

if __name__=='__main__':unittest.main(verbosity=2)
