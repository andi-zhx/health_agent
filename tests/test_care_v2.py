"""V2 acceptance: catalog, denominators, personal records, access and reporting."""
from contextlib import closing
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from openpyxl import load_workbook
from test_runtime import app,core,ROOT
from backend.care_v2 import schema


class CareV2Tests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.db=Path(self.directory.name)/'medical_system.db'
        self.db_patch=patch.object(core,'DB_PATH',str(self.db));self.db_patch.start()
        self.clock=patch.object(core,'now_local',return_value=datetime(2026,11,25,12,tzinfo=ZoneInfo('Asia/Shanghai')));self.clock.start()
        core.init_db();schema.initialize()
        self.client=app.test_client()
        with self.client.session_transaction() as s:s['logged_in']=True;s['username']='admin'
        for code,name,_ in schema.PROJECTS:
            eid=self.insert('equipment',name=name+'测试设备',type='测试',status='available')
            self.insert('v2_equipment',equipment_id=eid,project_code=code,asset_code='TEST-'+code,registered_at='2026-01-01')
        self.cid=self.insert('customers',name='虚构甲',phone='19900000001',birth_date='1950-05-05',gender='男',created_at='2026-01-01',is_deleted=0)
        self.cid2=self.insert('customers',name='虚构乙',phone='19900000002',birth_date=None,gender=None,created_at='2026-01-01',is_deleted=0)

    def tearDown(self):
        self.clock.stop();self.db_patch.stop();self.directory.cleanup()

    def insert(self,table,**data):
        with closing(core.get_db()) as conn:
            rid=conn.execute('INSERT INTO '+table+' ('+','.join(data)+') VALUES ('+','.join('?' for _ in data)+')',list(data.values())).lastrowid;conn.commit();return rid

    def post(self,path,values,client=None,expected=201):
        r=(client or self.client).post(path,json=values);self.assertEqual(r.status_code,expected,r.json)
        return r.json.get('data',{})

    def service(self,cid=None,project='MOXA',**extra):
        data={'customer_id':cid or self.cid,'project_code':project,'channel':'onsite','status':'completed','scheduled_at':'2026-11-05 10:00','completed_at':'2026-11-05 10:30','duration_minutes':30,**extra}
        return 'service:'+str(self.post('/api/v2/services',data)['id'])

    def review(self,ref,**extra):
        values={'service_ref':ref,'evaluation_type':'single','status':'部分改善','dimension':'疼痛影响','baseline_at':'2026-11-05 10:00','before_score':7,'evaluated_at':'2026-11-05 11:00','after_score':4,**extra}
        return self.post('/api/v2/reviews',values)

    def snap(self,query=''):
        r=self.client.get('/api/v2/snapshot?start=2026-11-01&end=2026-11-25'+query);self.assertEqual(r.status_code,200,r.json);return r.json['data']

    def account(self,name,role,cid=None,view=1,export=0):
        result=self.post('/api/v2/admin/accounts',{'username':name,'password':'TestPass2026!','role':role,'customer_id':cid,'can_view_personal':view,'can_export':export,'active':1})
        client=app.test_client();self.assertEqual(client.post('/api/auth/login',json={'username':name,'password':'TestPass2026!'}).status_code,200)
        return client,result['id']

    def test_empty_denominators_and_unknown_population_are_preserved(self):
        d=self.snap();self.assertEqual(d['health']['population'],2)
        self.assertEqual(sum(r['total'] for r in d['health']['demographics']),2)
        self.assertEqual(d['health']['demographics'][-1]['unknown'],1)
        for value in (d['effects']['summary']['rate'],d['satisfaction']['summary']['rate'],d['operations']['summary']['utilization'],d['operations']['summary']['repeat_rate']):self.assertIsNone(value)
        self.assertEqual(d['health']['risk'][-1]['count'],2)
        self.assertNotIn('_data',d);self.assertNotIn('_people',d);self.assertNotIn('_person_tags',d['health'])

    def test_exact_six_project_catalog_and_legacy_writes_blocked(self):
        expected={p[1] for p in schema.PROJECTS}
        for url in ('/api/projects','/api/projects/enabled?scene=store','/api/projects/enabled?scene=home','/api/service-projects'):
            self.assertEqual({p['name'] for p in self.client.get(url).json['data']},expected,url)
        self.post('/api/projects',{'name':'非白名单设备'},expected=400)
        self.post('/api/device-management/appointment-items',{'project_name':'非白名单设备'},expected=400)
        self.post('/api/v2/services',{'customer_id':self.cid,'project_code':'UNKNOWN'},expected=400)

    def test_health_latest_record_missing_detection_and_professional_risk(self):
        self.insert('health_assessments',customer_id=self.cid,assessment_date='2026-01-01',past_medical_history='高血压',recent_symptoms='头痛',blood_pressure_test='监测：偏高')
        self.insert('health_assessments',customer_id=self.cid,assessment_date='2026-11-01',past_medical_history='长期失眠、焦虑状态',recent_symptoms='入睡困难',blood_pressure_test='未监测',sleep_quality='好')
        self.insert('health_assessments',customer_id=self.cid,assessment_date='2027-01-01',past_medical_history='不存在于期末的病史')
        d=self.snap()['health'];self.assertEqual({r['name'] for r in d['diseases']},{'长期失眠','焦虑状态'});self.assertEqual(d['disease_denominator'],1)
        self.assertEqual(d['detection'][0]['valid'],0);self.assertEqual(d['detection'][0]['abnormal'],0);self.assertIsNone(d['detection'][0]['rate'])
        self.assertEqual(d['risk'][-1]['count'],2)
        self.post('/api/v2/risks',{'customer_id':self.cid,'level':'重点关注','assessed_at':'2026-11-20 10:00','notes':'测试专业确认'})
        self.assertEqual(self.snap()['health']['risk'][1]['count'],1)

    def test_scheduled_baseline_can_be_completed_without_rebinding_review(self):
        ref=self.service(status='scheduled',completed_at=None)
        values={'service_ref':ref,'status':'未评价','dimension':'疼痛影响','before_score':7,'baseline_at':'2026-11-05 10:00'}
        rid=self.post('/api/v2/reviews',values)['id']
        self.assertEqual(self.snap()['effects']['summary']['valid'],0)
        self.post('/api/v2/reviews',{**values,'status':'部分改善','evaluated_at':'2026-11-05 11:00'},expected=400)
        sid=ref.split(':')[1]
        r=self.client.put('/api/v2/services/'+sid,json={'customer_id':self.cid,'project_code':'MOXA','scheduled_at':'2026-11-05 10:00','completed_at':'2026-11-05 10:30','status':'completed'})
        self.assertEqual(r.status_code,200,r.json)
        evaluated={**values,'status':'部分改善','after_score':4,'evaluated_at':'2026-11-05 11:00'}
        self.assertEqual(self.client.put('/api/v2/reviews/'+str(rid),json=evaluated).status_code,200)
        self.assertEqual(self.snap()['effects']['summary']['valid'],1)
        other=self.service(self.cid2)
        self.assertEqual(self.client.put('/api/v2/reviews/'+str(rid),json={**evaluated,'service_ref':other}).status_code,400)

    def test_screening_staff_followup_preserves_professional_conclusion(self):
        ref=self.service(project='HEARING')
        values={'service_ref':ref,'completed':1,'valid_report':1,'abnormal':'异常','report':'虚构原始报告','professional_opinion':'虚构复查建议'}
        rid=self.post('/api/v2/screenings',values)['id']
        operator,_=self.account('screen_operator','operator')
        staff={k:value for k,value in values.items() if k not in ('abnormal','professional_opinion')}
        r=operator.put('/api/v2/screenings/'+str(rid),json={**staff,'followup_status':'已跟进','followup_result':'已联系复查'})
        self.assertEqual(r.status_code,200,r.json)
        with closing(core.get_db()) as conn:
            saved=conn.execute('SELECT * FROM v2_screenings WHERE id=?',(rid,)).fetchone()
            self.assertEqual((saved['abnormal'],saved['professional_opinion']),('异常','虚构复查建议'))
        self.assertEqual(operator.put('/api/v2/screenings/'+str(rid),json={**staff,'report':'覆盖报告'}).status_code,400)
        self.post('/api/v2/screenings',values,client=operator,expected=400)
        self.assertEqual(operator.get('/api/v2/report?kind=effects').status_code,403)

    def test_formal_equipment_options_and_custom_asset_survive_restart(self):
        extra=self.insert('equipment',name='归档旧设备',type='旧类型',status='available')
        old=self.insert('therapy_projects',name='旧测试项目',status='disabled')
        with closing(core.get_db()) as conn:pid=conn.execute("SELECT project_id FROM v2_projects WHERE code='MOXA'").fetchone()[0]
        query='?date=2026-11-10&start_time=10:00&end_time=10:30'
        d=self.client.get('/api/equipment/availability-summary'+query).json['data']
        self.assertEqual(d['total_equipment'],6);self.assertNotIn(extra,[e['id'] for e in d['available_equipment']])
        self.assertEqual(self.client.get('/api/appointments/available-options'+query+'&project_id='+str(old)).status_code,400)
        d=self.client.get('/api/appointments/available-options'+query+'&project_id='+str(pid)).json['data']
        self.assertEqual(len(d['available_equipment']),1)
        self.assertEqual(self.client.put('/api/projects/'+str(pid),json={'name':'改名'}).status_code,400)
        eid=self.post('/api/v2/admin/equipment',{'project_code':'MOXA','name':'新增真实台账','asset_code':'REAL-TEST'})['id']
        core.init_db();schema.initialize()
        with closing(core.get_db()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM equipment').fetchone()[0],8)
            self.assertEqual(conn.execute("SELECT status FROM project_equipment_mapping WHERE equipment_name='新增真实台账'").fetchone()[0],'enabled')
            self.assertIsNotNone(conn.execute('SELECT 1 FROM v2_equipment WHERE equipment_id=?',(eid,)).fetchone())

    def test_offline_restore_preserves_current_copy_and_requires_stopped_flag(self):
        from manage_v2 import inspect,restore
        backup=Path(self.directory.name)/'prior.db'
        with closing(sqlite3.connect(self.db)) as conn, closing(sqlite3.connect(backup)) as dest:conn.backup(dest)
        extra=self.insert('customers',name='回滚后保留在安全副本',phone='19900000003',is_deleted=0)
        with self.assertRaises(ValueError):restore(backup,self.db)
        result=restore(backup,self.db,stopped=True)
        self.assertEqual(result['verification']['counts']['customers'],2)
        self.assertEqual(inspect(result['preserved_current'])['counts']['customers'],3)

    def test_people_vs_visits_home_once_and_completion_date_filter(self):
        self.service();self.service(project='MASSAGE');self.service(self.cid2,project=None,channel='home')
        self.service(status='cancelled');self.service(status='scheduled',completed_at=None,scheduled_at='2026-12-01 10:00')
        self.service(scheduled_at='2026-10-31 23:40',completed_at='2026-11-01 00:10')
        s=self.snap()['operations']['summary'];self.assertEqual((s['services'],s['people'],s['home_services'],s['home_people']),(4,2,1,1))
        self.assertEqual(s['per_person'],2);self.assertEqual(s['repeat_rate'],50);self.assertEqual(s['fulfillment'],100)
        self.assertEqual(self.snap('&project=MASSAGE')['operations']['summary']['services'],1)
        self.assertEqual(self.snap('&gender=女')['health']['population'],0)

    def test_evaluation_denominators_screening_exclusion_and_missing(self):
        a=self.service();b=self.service();c=self.service();self.service();hearing=self.service(project='HEARING')
        self.review(a);self.review(b,status='不适用',before_score=None,after_score=None,evaluated_at=None,baseline_at=None,dimension=None)
        self.review(c,status='无变化',after_score=7)
        self.post('/api/v2/reviews',{'service_ref':hearing,'status':'部分改善'},expected=400)
        e=self.snap()['effects']['summary'];self.assertEqual((e['valid'],e['applicable'],e['improved']),(2,3,1));self.assertEqual(e['rate'],50);self.assertEqual(e['coverage'],66.7)

    def test_legacy_default_feedback_is_unverified_until_reviewed(self):
        with closing(core.get_db()) as conn:pid=conn.execute("SELECT project_id FROM v2_projects WHERE code='MOXA'").fetchone()[0]
        aid=self.insert('appointments',customer_id=self.cid,project_id=pid,appointment_date='2026-11-04',start_time='10:00',end_time='10:30',status='completed')
        self.insert('service_improvement_records',customer_id=self.cid,service_type='appointments',service_id=aid,service_time='2026-11-04 10:00',service_project='艾灸',improvement_status='无改善')
        e=self.snap()['effects'];self.assertIsNone(e['summary']['rate']);self.assertEqual(e['summary']['legacy_unverified'],1)
        self.review('appointment:'+str(aid))
        e=self.snap()['effects'];self.assertEqual(e['summary']['rate'],100);self.assertEqual(e['summary']['legacy_unverified'],0)

    def test_stage_uniqueness_missing_pair_and_validated_followup(self):
        values={'customer_id':self.cid,'project_code':'MOXA','evaluation_type':'stage','window_start':'2026-11-01','window_end':'2026-11-15','baseline_at':'2026-11-01 10:00','before_score':7,'after_score':None,'status':'未评价','dimension':'疼痛影响','due_date':'2026-11-20','followup_status':'待复评'}
        rid=self.post('/api/v2/reviews',values)['id'];self.post('/api/v2/reviews',values,expected=409)
        month=self.snap()['effects']['stage_months'][0];self.assertEqual(month['not_reviewed'],1)
        r=self.client.put('/api/v2/reviews/'+str(rid),json={**values,'status':'部分改善','after_score':4,'evaluated_at':'2026-11-16 10:00','followup_status':'已复评'})
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(self.snap()['effects']['stage_months'][0]['improved'],1)
        self.post('/api/v2/reviews',{**values,'window_end':'2026-11-20'},expected=201)
        # Two windows in the same month still count the person/project only once at month end.
        m=self.snap()['effects']['stage_months'][0];self.assertEqual((m['n'],m['not_reviewed']),(1,1))
        self.post('/api/v2/reviews',{**values,'window_end':'2026-11-21','before_score':None,'after_score':4},expected=400)
        self.post('/api/v2/reviews',{**values,'window_end':'2026-11-21','followup_status':'已复评'},expected=400)

    def test_satisfaction_question_denominators_and_opinion_task(self):
        self.service();self.service(self.cid2)
        self.post('/api/v2/surveys',{'customer_id':self.cid,'answered_at':'2026-11-10 10:00','overall':5,'attitude':4,'needs_answered':1,'needs':['健康讲座','医师指导'],'comment':'虚构意见'})
        self.post('/api/v2/surveys',{'customer_id':self.cid2,'answered_at':'2026-11-10 10:00','overall':None,'guidance':3,'needs_answered':1,'needs':['医师指导']})
        s=self.snap()['satisfaction'];self.assertEqual((s['summary']['rate'],s['summary']['coverage'],s['summary']['needs_answered']),(100,50,2))
        self.assertEqual(s['needs'][0]['percent'],100);self.assertEqual(s['needs'][1]['percent'],50);self.assertEqual(len(s['tasks']),1)
        self.post('/api/v2/surveys',{'customer_id':self.cid,'answered_at':'2026-11-11 10:00','needs_answered':1,'needs':['上门服务']})
        needs=self.snap()['satisfaction'];self.assertEqual(needs['summary']['needs_answered'],2)
        self.assertNotIn('健康讲座',[r['name'] for r in needs['needs']])
        task=s['tasks'][0];r=self.client.put('/api/v2/tasks/'+str(task['id']),json={**task,'status':'已反馈','result':''});self.assertEqual(r.status_code,400)
        r=self.client.put('/api/v2/tasks/'+str(task['id']),json={**task,'status':'已反馈','result':'已处理并反馈','feedback_at':'2026-11-20 10:00'});self.assertEqual(r.status_code,200,r.json)

    def test_maintenance_updates_equipment_capacity_has_real_denominator(self):
        with closing(core.get_db()) as conn:eid=conn.execute("SELECT equipment_id FROM v2_equipment WHERE project_code='MOXA' LIMIT 1").fetchone()[0]
        self.post('/api/v2/capacity',{'equipment_id':eid,'start_at':'2026-11-05 09:00','end_at':'2026-11-05 17:00'})
        self.post('/api/v2/capacity',{'equipment_id':eid,'start_at':'2026-11-05 10:00','end_at':'2026-11-05 16:00'},expected=400)
        self.service(equipment_id=eid)
        values={'equipment_id':eid,'fault_type':'虚构故障','reported_at':'2026-11-05 11:00','down_at':'2026-11-05 11:00','status':'待维修'}
        rid=self.post('/api/v2/maintenance',values)['id']
        self.post('/api/v2/services',{'customer_id':self.cid,'project_code':'MOXA','channel':'onsite','status':'completed','scheduled_at':'2026-11-05 12:00','completed_at':'2026-11-05 12:30','equipment_id':eid},expected=400)
        response=self.client.put('/api/v2/maintenance/'+str(rid),json={**values,'status':'已恢复','restored_at':'2026-11-05 13:00','solution':'虚构维修结果'});self.assertEqual(response.status_code,200,response.json)
        cap=self.snap()['operations']['capacity'];self.assertEqual((cap['planned_minutes'],cap['downtime_minutes'],cap['availability']),(480,120,75));self.assertEqual(cap['used_minutes'],30);self.assertEqual(cap['utilization'],8.3)

    def test_resident_cannot_read_others_or_population_or_export_without_grant(self):
        resident,rid=self.account('resident_test','resident',self.cid,view=1,export=0)
        self.assertEqual(resident.get('/api/v2/personal/'+str(self.cid)).status_code,200)
        for path in ('/api/v2/personal/'+str(self.cid2),'/api/v2/snapshot','/api/customers','/api/export/customers','/api/v2/admin/accounts','/api/v2/export?kind=personal&customer_id='+str(self.cid)):
            self.assertEqual(resident.get(path).status_code,403,path)
        self.post('/api/v2/risks',{'customer_id':self.cid},client=resident,expected=403)
        with closing(core.get_db()) as conn:
            conn.execute('UPDATE v2_accounts SET active=0 WHERE id=?',(rid,));conn.commit()
        self.assertEqual(resident.get('/api/v2/personal/'+str(self.cid)).status_code,401)

    def test_manager_receives_no_personal_rows_and_operator_no_medical_write(self):
        self.service();manager,_=self.account('manager_test','manager',view=0,export=1)
        self.assertEqual(manager.get('/api/v2/snapshot').status_code,403)
        self.assertEqual(manager.get('/api/v2/export?kind=portrait').status_code,403)
        for i in range(3):self.insert('customers',name='额外虚构'+str(i),phone='1991000000'+str(i),created_at='2026-01-01',is_deleted=0)
        r=manager.get('/api/v2/snapshot?start=2026-11-01&end=2026-11-25');self.assertEqual(r.status_code,200)
        self.assertNotIn('虚构甲',r.get_data(as_text=True));self.assertEqual(r.json['data']['operations']['service_records'],[])
        self.assertEqual(manager.get('/api/v2/drilldown?domain=diseases&label=高血压').status_code,403)
        operator,_=self.account('operator_test','operator',view=1)
        self.post('/api/v2/measurements',{'customer_id':self.cid},client=operator,expected=403)
        self.post('/api/v2/risks',{'customer_id':self.cid},client=operator,expected=403)
        self.post('/api/v2/admin/accounts',{},client=operator,expected=403)
        limited,_=self.account('limited_operator','operator',view=0)
        self.post('/api/v2/tasks',{'customer_id':self.cid,'title':'涉及个人的意见','category':'跟进'},client=limited,expected=403)

    def test_personal_measurement_units_reference_pairs_and_export_access(self):
        pro,_=self.account('pro_test','professional',view=1,export=1)
        values={'customer_id':self.cid,'metric':'systolic','value':125,'measured_at':'2026-11-20 10:00','source':'虚构来源','reference_low':90,'reference_high':140}
        self.post('/api/v2/measurements',values,client=pro)
        self.post('/api/v2/measurements',{**values,'reference_high':None},client=pro,expected=400)
        self.post('/api/v2/measurements',{**values,'value':-1},client=pro,expected=400)
        person=pro.get('/api/v2/personal/'+str(self.cid)).json['data'];self.assertEqual(person['measurements'][0]['unit'],'mmHg')
        report=pro.get('/api/v2/report?kind=personal&customer_id='+str(self.cid));self.assertEqual(report.status_code,200)
        with closing(core.get_db()) as conn:self.assertGreater(conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action LIKE '%个人%'").fetchone()[0],0)

    def test_dates_previous_period_and_excel_match_page(self):
        self.service();d=self.snap();self.assertEqual((d['dashboard']['previous']['start'],d['dashboard']['previous']['end']),('2026-10-07','2026-10-31'))
        self.assertEqual(self.client.get('/api/v2/snapshot?start=2026-11-20&end=2026-11-01').status_code,400)
        self.assertEqual(self.client.get('/api/v2/snapshot?start=2026-11-20&end=2027-01-01').status_code,400)
        response=self.client.get('/api/v2/export?kind=operations&start=2026-11-01&end=2026-11-25')
        book=load_workbook(io.BytesIO(response.data));pairs=dict(book['核心指标'].values);self.assertEqual(pairs['累计服务人次'],d['operations']['summary']['services']);book.close();response.close()
        for kind in ('operations','portrait','effects'):
            self.assertEqual(self.client.get('/api/v2/report?kind='+kind).status_code,200)

    def test_archive_confirmation_count_preservation_and_restart(self):
        pid=self.insert('therapy_projects',name='听力检测仪',category='检测',status='enabled')
        aid=self.insert('appointments',customer_id=self.cid,project_id=pid,appointment_date='2026-11-04',start_time='10:00',end_time='10:30',status='completed')
        schema.initialize();before=self.snap();self.assertEqual(before['operations']['summary']['services'],0)
        with closing(core.get_db()) as conn:self.assertEqual(conn.execute('SELECT state FROM v2_project_links WHERE legacy_project_id=?',(pid,)).fetchone()[0],'pending')
        self.post('/api/v2/admin/catalog/confirm',{'legacy_project_id':pid,'project_code':'HEARING'},expected=400)
        self.post('/api/v2/admin/catalog/confirm',{'legacy_project_id':pid,'project_code':'HEARING','confirmed':True},expected=200)
        self.assertEqual(self.snap()['operations']['summary']['services'],1)
        core.init_db();schema.initialize()
        with closing(core.get_db()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM appointments WHERE id=?',(aid,)).fetchone()[0],1)
            self.assertEqual(list(conn.execute('PRAGMA foreign_key_check')),[])
        self.assertEqual(self.snap()['operations']['summary']['services'],1)

    def test_original_database_backup_before_migration(self):
        with closing(core.get_db()) as conn:
            conn.execute('DROP TABLE v2_migrations');conn.commit()
        before=schema.before_upgrade();self.assertTrue(Path(before['path']).exists())
        with closing(sqlite3.connect(before['path'])) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0],2)
        schema.initialize(before)
        with closing(core.get_db()) as conn:
            row=conn.execute("SELECT * FROM v2_migrations WHERE version='2.0'").fetchone();self.assertEqual(json.loads(row['before_counts'])['customers'],json.loads(row['after_counts'])['customers'])


class V2DemoTests(unittest.TestCase):
    def test_demo_100_cases_isolated_idempotent_and_refuses_non_demo(self):
        with tempfile.TemporaryDirectory() as folder:
            command=[sys.executable,str(ROOT/'seed_demo_v2.py'),'--data-dir',folder]
            r=subprocess.run(command,capture_output=True);self.assertEqual(r.returncode,0,r.stderr)
            db=Path(folder)/'medical_system.db'
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0],100)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM v2_services').fetchone()[0],610)
                self.assertEqual(list(conn.execute('PRAGMA foreign_key_check')),[])
            digest=hashlib.sha256(db.read_bytes()).hexdigest();self.assertEqual(subprocess.run(command,capture_output=True).returncode,0);self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),digest)
            with closing(sqlite3.connect(db)) as conn:conn.execute("DELETE FROM system_settings WHERE setting_key='demo_v2'");conn.commit()
            digest=hashlib.sha256(db.read_bytes()).hexdigest();self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0);self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),digest)
