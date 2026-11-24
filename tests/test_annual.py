"""Annual metrics, data preservation and the complete experience/follow-up flow."""
from contextlib import closing
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

# Share the disposable app setup; production and demo databases are never opened.
from test_runtime import app, core, ROOT
from backend.api import operations
from openpyxl import load_workbook


class AnnualTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(core, 'DB_PATH', str(Path(self.directory.name) / 'medical_system.db'))
        self.db_patch.start()
        self.clock = patch.object(operations, 'now_local', return_value=datetime(2026, 11, 24, 12))
        self.clock.start()
        core.init_db()
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'test'
        self.cid = self.insert('customers', name='虚构测试干部', phone='19900000000', created_at='2026-01-01', is_deleted=0)

    def tearDown(self):
        self.clock.stop()
        self.db_patch.stop()
        self.directory.cleanup()

    def insert(self, table, **values):
        with closing(core.get_db()) as conn:
            cursor = conn.execute('INSERT INTO '+table+' ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')', list(values.values()))
            conn.commit()
            return cursor.lastrowid

    def record(self, **values):
        payload = dict(customer_id=self.cid, service_type='appointments', service_time='2026-06-01 10:00:00',
                       service_project='艾灸机器人', improvement_status='部分改善', followup_date='2026-06-08')
        payload.update(values)
        response = self.client.post('/api/improvement-records', json=payload)
        self.assertEqual(response.status_code, 201, response.json)
        return response.json['data']['id'], payload

    def snapshot(self):
        response = self.client.get('/api/operations/overview?year=2026')
        self.assertEqual(response.status_code, 200)
        return response.json['data']

    def test_empty_denominators_missing_health_and_auth(self):
        data = self.snapshot()
        self.assertIsNone(data['summary']['improvement_rate'])
        self.assertIsNone(data['summary']['feedback_coverage'])
        self.assertEqual(data['management'][-1], {'name':'未评估','count':1})
        self.assertIsNone(data['months'][-1]['services'])
        for year in ('abc', '1999', '2027'):
            self.assertEqual(self.client.get('/api/operations/overview?year='+year).status_code, 400)
        anonymous = app.test_client()
        for path in ('overview','experiences','export','report'):
            self.assertEqual(anonymous.get('/api/operations/'+path).status_code, 401)

    def test_feedback_deduplicates_and_uses_completed_service_denominator(self):
        aid = self.insert('appointments', customer_id=self.cid, appointment_date='2026-06-01', start_time='10:00',end_time='10:30',status='completed')
        cancelled = self.insert('appointments', customer_id=self.cid, appointment_date='2026-06-01', start_time='11:00',end_time='11:30',status='cancelled')
        self.record(service_id=aid, improvement_status='明显改善')
        latest, _ = self.record(service_id=aid, improvement_status='无改善')
        self.record(service_id=cancelled)
        self.record(improvement_status='部分改善')  # Manual feedback is not linked coverage.
        data = self.snapshot()['summary']
        self.assertEqual((data['services'],data['linked_feedback'],data['valid_feedback'],data['improved']), (1,1,2,1))
        self.assertEqual(data['feedback_coverage'], 100)
        self.assertEqual(data['improvement_rate'], 50)
        filtered = self.client.get('/api/operations/experiences?year=2026&project=艾灸机器人&search=虚构&page=999').json['data']
        self.assertEqual((filtered['total'],filtered['page']), (2,1))
        self.assertIn(latest, [r['id'] for r in filtered['items']])

    def test_scores_validation_legacy_edit_and_followup_refresh(self):
        rid, payload = self.record(experience_dimension='疼痛影响', before_score=8, after_score=4, satisfaction_score=5)
        self.assertEqual(self.snapshot()['summary']['followup_due'],1)
        payload.pop('before_score'); payload.pop('after_score'); payload.pop('experience_dimension'); payload.pop('satisfaction_score')
        self.assertEqual(self.client.put(f'/api/improvement-records/{rid}', json=payload).status_code,200)
        record = self.client.get(f'/api/improvement-records/{rid}').json['data']
        self.assertEqual((record['before_score'],record['after_score'],record['satisfaction_score']), (8,4,5))
        for extra in ({'before_score':11,'after_score':4}, {'before_score':4}, {'satisfaction_score':0},
                      {'adverse_event':'有不适'}, {'followup_status':'已回访'},
                      {'followup_status':'已回访','followup_completed_at':'2099-01-01 10:00','followup_notes':'future'}):
            with self.subTest(extra=extra):
                self.assertEqual(self.client.post('/api/improvement-records',json={**payload,**extra}).status_code,400)
        completed = self.client.post(f'/api/improvement-records/{rid}/followup',json={'followup_status':'已回访','followup_completed_at':'2026-06-08 10:00','followup_notes':'虚构回访：已核实主观感受'})
        self.assertEqual(completed.status_code,200,completed.json)
        self.assertEqual((self.snapshot()['summary']['followup_due'],self.snapshot()['summary']['followup_done']), (0,1))
        self.assertEqual(self.client.get('/api/operations/experiences?year=2026&state=done').json['data']['total'],1)

    def test_health_latest_assessment_and_unknown_are_not_healthy(self):
        self.insert('health_assessments', customer_id=self.cid, assessment_date='2026-01-02',past_medical_history='高血压、糖尿病')
        self.insert('health_assessments', customer_id=self.cid, assessment_date='2026-10-01',past_medical_history='不详',blood_pressure_test='监测：正常')
        self.insert('health_assessments', customer_id=self.cid, assessment_date='2027-01-01',past_medical_history='冠心病')
        data = self.snapshot()
        self.assertEqual(data['diseases'], [])
        self.assertEqual(data['disease_recorded'],0)
        self.assertEqual(data['management'][3], {'name':'待补充','count':1})
        self.assertEqual(data['health_signals'][0]['observed'],1)

    def test_historical_followup_pending_until_completion_date(self):
        rid, _ = self.record(service_time='2025-06-01 10:00',followup_date='2025-06-08',followup_status='已回访',followup_completed_at='2026-01-02 10:00',followup_notes='次年完成')
        with closing(core.get_db()) as conn:
            conn.execute("UPDATE customers SET created_at='2025-01-01' WHERE id=?",(self.cid,));conn.commit()
        data = self.client.get('/api/operations/overview?year=2025').json['data']
        self.assertEqual((data['summary']['followup_due'],data['summary']['followup_done']),(1,0))

    def test_export_and_report_escape_untrusted_text(self):
        self.insert('health_assessments',customer_id=self.cid,assessment_date='2026-10-01',past_medical_history='=1+1')
        self.record()
        with closing(core.get_db()) as conn:
            conn.execute("INSERT OR REPLACE INTO system_settings(setting_key,setting_value) VALUES ('unit_name','<script>bad</script>')")
            conn.execute("INSERT OR REPLACE INTO system_settings(setting_key,setting_value) VALUES ('demo_mode','true')")
            conn.commit()
        report = self.client.get('/api/operations/report?year=2026')
        self.assertIn('虚构',report.get_data(as_text=True))
        self.assertNotIn('<script>bad</script>', report.get_data(as_text=True))
        response = self.client.get('/api/operations/export?year=2026')
        with io.BytesIO(response.data) as stream:
            book = load_workbook(stream)
            self.assertEqual(len(book.sheetnames),6)
            self.assertEqual(book['疾病分布']['A2'].data_type,'s')
            self.assertNotIn('虚构测试干部',str(list(book['体验反馈'].values)))
            book.close()
        response.close()

    def test_restart_retains_legacy_data_and_new_experience_fields(self):
        rid, _ = self.record(experience_dimension='疼痛影响',before_score=9,after_score=6)
        eid = self.insert('equipment',name='保留旧设备',type='旧类型',model=core.LEGACY_EQUIPMENT_MODELS_TO_PURGE[0])
        with closing(core.get_db()) as conn:
            for table in ('equipment_usage','satisfaction_surveys','service_projects'):
                conn.execute(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, notes TEXT)')
                conn.execute(f"INSERT INTO {table} VALUES (1,'保留原始记录')")
            conn.commit()
        core.init_db()
        with closing(core.get_db()) as conn:
            self.assertIsNotNone(conn.execute('SELECT id FROM equipment WHERE id=?',(eid,)).fetchone())
            for table in ('equipment_usage','satisfaction_surveys','service_projects'):
                self.assertEqual(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT before_score FROM service_improvement_records WHERE id=?',(rid,)).fetchone()[0],9)


class DemoTests(unittest.TestCase):
    def test_fixture_and_seed_are_complete_and_non_destructive(self):
        fixture = json.loads((ROOT/'demo'/'cases-2026.json').read_text(encoding='utf-8'))
        self.assertEqual(len(fixture['cases']),100)
        self.assertEqual(len({c['id_card'] for c in fixture['cases']}),100)
        with tempfile.TemporaryDirectory() as folder:
            command = [sys.executable,str(ROOT/'seed_demo_data.py'),'--data-dir',folder]
            result = subprocess.run(command,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            db = Path(folder)/'medical_system.db'
            with closing(sqlite3.connect(db)) as conn:
                for table,count in [('customers',100),('health_assessments',200),('appointments',300),('home_appointments',20),('service_improvement_records',310)]:
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],count)
                conn.execute("UPDATE customers SET name='演示修改需要保留' WHERE id=1");conn.commit()
            digest = hashlib.sha256(db.read_bytes()).hexdigest()
            self.assertEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),digest)
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("DELETE FROM system_settings WHERE setting_key='demo_mode'");conn.commit()
            digest = hashlib.sha256(db.read_bytes()).hexdigest()
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),digest)
