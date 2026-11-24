"""Create the isolated demo database once; never clear an existing database."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent


def seed_demo(directory):
    directory = Path(directory).expanduser().resolve()
    if directory == ROOT:
        raise RuntimeError('Demo data must use a separate directory, not the working project folder.')
    db = directory / 'medical_system.db'
    if db.exists():
        with sqlite3.connect(db) as conn:
            try:
                marker = conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='demo_mode'").fetchone()
            except sqlite3.Error:
                marker = None
        if marker and marker[0] == 'true':
            print('Existing demo database preserved. No data was replaced.')
            return
        raise RuntimeError('An existing non-demo database was found. Nothing was changed; select a new empty directory.')
    directory.mkdir(parents=True, exist_ok=True)
    os.environ['HEALTH_AGENT_DATA_DIR'] = str(directory)
    # Import only after selecting the demo path.
    from backend import core
    if Path(core.DB_PATH).resolve() != db:
        raise RuntimeError('Database module already uses a different path. Run this script in a new process.')
    core.init_db()
    fixture = json.loads((ROOT / 'demo' / 'cases-2026.json').read_text(encoding='utf-8'))
    conn = core.get_db()
    try:
        c = conn.cursor()
        def insert(table, data):
            columns = list(data)
            c.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', list(data.values()))
            return c.lastrowid
        for case in fixture['cases']:
            history = '、'.join(case['diseases']) or '无'
            age = fixture['year'] - int(case['birth_date'][:4])
            cid = insert('customers', {'name':case['name'], 'gender':case['gender'], 'birth_date':case['birth_date'],
                'age':age, 'id_card':case['id_card'], 'phone':case['phone'], 'identity_type':'本人',
                'military_rank':case['rank'], 'record_creator':'演示健康专员', 'address':'军休所演示地址',
                'medical_history':history, 'chronic_diseases':history, 'health_status':'常规随访',
                'created_at':'2026-01-02 09:00:00', 'updated_at':'2026-11-24 09:00:00', 'is_deleted':0})
            for assessment_day in ('2026-01-03', '2026-11-01'):
                insert('health_assessments', {'customer_id':cid,'assessment_date':assessment_day,'assessor':'演示健康专员',
                    'age':age,'height_cm':165+cid%12,'weight_kg':58+cid%20,'address':'军休所演示地址',
                    'past_medical_history':history,'family_history':'无','allergy_history':'无','allergy_details':'',
                    'smoking_status':'有' if cid%7==0 else '无','smoking_years':20 if cid%7==0 else 0,
                    'drinking_status':'有' if cid%8==0 else '无','sleep_quality':case['sleep'],
                    'sleep_hours':'<6小时' if case['sleep']=='差' else '6-8小时',
                    'recent_symptoms':'关节不适' if cid%3==0 else '无','life_impact_issues':'活动不便' if cid%3==0 else '无',
                    'blood_pressure_test':'监测：偏高' if '高血压' in case['diseases'] else '监测：正常',
                    'blood_lipid_test':'未监测' if cid%9==0 else '监测：偏高' if '高血脂' in case['diseases'] else '监测：正常',
                    'blood_sugar_test':'监测：偏高' if '糖尿病' in case['diseases'] else '监测：正常',
                    'chronic_pain':'有' if any(t in history for t in ('关节','颈椎','腰椎')) else '无',
                    'exercise_methods':json.dumps(['散步','太极'],ensure_ascii=False),
                    'health_needs':json.dumps(case['needs'],ensure_ascii=False), 'notes':fixture['notice'],
                    'created_at':assessment_day+' 09:00:00'})
            insert('health_records', {'customer_id':cid,'record_date':'2026-11-01','blood_pressure':'140/90' if '高血压' in case['diseases'] else '120/80',
                                     'diagnosis':history,'notes':'虚构案例的档案摘要','created_at':'2026-11-01 09:00:00'})
            for visit in case['visits']:
                project = c.execute('SELECT id FROM therapy_projects WHERE name=?', (visit['project'],)).fetchone()[0]
                device = c.execute('SELECT id FROM equipment WHERE name=?', (visit['project']+('01' if cid%2 else '02'),)).fetchone()[0]
                stamp = visit['date']+' '+visit['time']+':00'
                hour, minute = map(int, visit['time'].split(':'))
                end = f'{hour+(minute+30)//60:02d}:{(minute+30)%60:02d}'
                aid = insert('appointments', {'booking_group_id':f'demo-{cid}-{visit["date"]}', 'customer_id':cid,'equipment_id':device,
                    'project_id':project,'appointment_date':visit['date'],'start_time':visit['time'],'end_time':end,
                    'status':'completed','checkin_status':'checked_in','has_companion':'有' if age>=80 else '无',
                    'notes':'虚构演示案例；实际服务应先完成适用性评估。','created_at':stamp,'updated_at':stamp})
                insert('visit_checkins', {'customer_id':cid,'checkin_time':stamp,'purpose':'现场服务体验','notes':'虚构演示签到','created_at':stamp})
                if visit['has_feedback']:
                    insert('service_improvement_records', {'service_id':aid,'service_type':'appointments','customer_id':cid,
                        'service_time':stamp,'service_project':visit['project'],'pre_service_status':'演示记录：本人反馈日常活动存在一定困扰。',
                        'service_content':'完成服务前询问、体验登记及服务后感受记录；本条为虚构案例。',
                        'post_service_evaluation':'本人自述感受，未据此判断医学疗效。','improvement_status':visit['status'],
                        'experience_dimension':visit['dimension'],'before_score':visit['before'],'after_score':visit['after'],
                        'satisfaction_score':visit['satisfaction'],'adverse_event':'有不适' if visit['adverse'] else '无不适',
                        'adverse_notes':'演示记录：短暂不适，已停止体验并安排健康专员复核。' if visit['adverse'] else '',
                        'followup_date':visit['followup_date'],'followup_method':'电话','followup_time':'',
                        'followup_status':visit['followup_status'],'followup_completed_at':visit['followup_completed_at'],
                        'followup_notes':visit['followup_notes'],'created_at':stamp,'updated_at':stamp})
            if case['home_visit']:
                project = c.execute("SELECT id FROM therapy_projects WHERE name='上门康复护理'").fetchone()[0]
                staff = c.execute("SELECT id,name FROM staff ORDER BY id LIMIT 1").fetchone()
                day = f'2026-10-{cid%27+1:02d}'
                hid = insert('home_appointments', {'customer_id':cid,'project_id':project,'staff_id':staff[0],
                    'customer_name':case['name'],'phone':case['phone'],'home_time':'10:00-10:30','home_address':'军休所演示地址',
                    'service_project':'上门康复护理','staff_name':staff[1],'appointment_date':day,'start_time':'10:00','end_time':'10:30',
                    'location':'军休所演示地址','contact_person':'本人','contact_phone':case['phone'],'has_companion':'有',
                    'notes':'虚构上门服务','status':'completed','checkin_status':'checked_in','created_at':day+' 09:00:00','updated_at':day+' 11:00:00'})
                insert('service_improvement_records', {'service_id':hid,'service_type':'home_appointments','customer_id':cid,
                    'service_time':day+' 10:00:00','service_project':'上门康复护理','pre_service_status':'日常活动需要协助',
                    'service_content':'居家环境与活动情况记录','post_service_evaluation':'本人感觉活动更便利','improvement_status':'部分改善',
                    'experience_dimension':'活动不便','before_score':6,'after_score':4,'satisfaction_score':4,'adverse_event':'无不适',
                    'followup_date':'2026-11-24','followup_method':'到店','followup_status':'待回访','created_at':day+' 11:00:00','updated_at':day+' 11:00:00'})
        for key,value in {'demo_mode':'true','demo_case_count':'100','demo_year':'2026','unit_name':'静安军休所 · 演示环境'}.items():
            c.execute('INSERT OR REPLACE INTO system_settings(setting_key,setting_value) VALUES (?,?)',(key,value))
        conn.commit()
        counts = {t: c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('customers','health_assessments','appointments','home_appointments','service_improvement_records')}
        print('Demo database ready: '+json.dumps(counts))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', default=str(ROOT / 'demo_data'))
    args = parser.parse_args()
    seed_demo(args.data_dir)
