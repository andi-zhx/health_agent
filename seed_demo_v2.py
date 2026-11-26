"""Build 300 complete fictional cases; --replace explicitly replaces the active DB."""
import argparse
import calendar
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import random
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parent
VERSION = 'jingan-300-2026-11-26-v1'
AS_OF = date(2026, 11, 26)
NOTICE = '300 位完全虚构干部案例，仅用于系统功能展示，不代表真实服务业绩或医学疗效。'


def stamp(value):
    return value.isoformat(' ', timespec='seconds')


def markers(db):
    if not db.exists():
        return {}
    with closing(sqlite3.connect(db)) as conn:
        try:
            return dict(conn.execute('SELECT setting_key,setting_value FROM system_settings'))
        except sqlite3.Error:
            return {}


def build(directory):
    """Build from a fresh schema in a temporary directory, not from existing records."""
    os.environ['HEALTH_AGENT_DATA_DIR'] = str(directory)
    from app import app  # Initialize the same schema as the application.
    from backend import core
    from backend.care_v2.schema import PROJECTS
    from werkzeug.security import generate_password_hash
    if Path(core.DB_PATH).resolve() != (directory / 'medical_system.db').resolve():
        raise RuntimeError('Run the generator in a fresh Python process.')
    rng = random.Random(20261126)
    manifest = []
    with closing(core.get_db()) as conn:
        def add(table, **values):
            return conn.execute('INSERT INTO '+table+' ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')', list(values.values())).lastrowid
        # Rename only the fresh initializer's sample staff; no old staff is copied.
        for i, row in enumerate(conn.execute('SELECT id FROM staff ORDER BY id').fetchall(), 1):
            conn.execute('UPDATE staff SET name=?,phone=?,notes=? WHERE id=?', (f'演示服务专员{i}', f'1999000{i:04d}', '虚构岗位', row[0]))
        staff = [r[0] for r in conn.execute('SELECT id FROM staff ORDER BY id')]
        pids = dict(conn.execute('SELECT code,project_id FROM v2_projects'))
        devices = defaultdict(list)
        for code, name, _ in PROJECTS:
            for no in (1, 2):
                eid = add('equipment', name=f'{name}演示{no}', type='虚构演示设备', model='DEMO-2026', location='虚构康养体验区', status='available', description=NOTICE)
                add('v2_equipment', equipment_id=eid, project_code=code, asset_code=f'DEMO-{code}-{no}', maintenance_days=30, registered_at='2026-01-01 08:00:00')
                add('project_equipment_mapping', project_name=name, equipment_name=f'{name}演示{no}', status='enabled')
                devices[code].append(eid)
        ranges = [(24,55,59),(78,60,69),(105,70,79),(69,80,89),(24,90,95)]
        ages = [lo+i%(hi-lo+1) for count,lo,hi in ranges for i in range(count)]
        patterns = [(['高血压'],['头晕头痛']),(['膝骨关节炎','腰椎间盘突出'],['关节疼痛']),(['2型糖尿病','脂肪肝'],['餐后乏力']),(['长期失眠'],['入睡困难']),(['焦虑状态'],['疲劳感']),([],[]),(['高血压','冠心病'],['活动后气短']),(['颈椎病'],['肩颈不适']),(['听力下降'],['沟通困难']),(['高血压','2型糖尿病'],['口干乏力'])]
        people = {}
        for i in range(1,301):
            years = ages[i-1]
            birth = date(2026-years, 1+i%10, 1+i%24)
            gender = '女' if i%7 in (0,2) else '男'
            diseases, symptoms = patterns[(i*7+years)%len(patterns)]
            history = '、'.join(diseases) or '无'
            symptom = '、'.join(symptoms) or '无'
            cid = add('customers', name=f'演示干部{i:03d}', phone=f'1990000{i:04d}', gender=gender, birth_date=birth.isoformat(), age=years, identity_type='本人', record_creator='演示档案专员', address=f'虚构军休所第{(i-1)//30+1}组', medical_history=history, created_at='2026-01-01 08:00:00', updated_at='2026-11-20 09:00:00', is_deleted=0)
            people[cid] = dict(age=years,gender=gender,diseases=diseases,history=history,symptom=symptom)
            manifest.append({'id':cid,'name':f'演示干部{i:03d}','gender':gender,'birth_date':birth.isoformat(),'age':years,'fictional':True})
            for month in (2,11):
                day = f'2026-{month:02d}-01'
                add('health_assessments', customer_id=cid, assessment_date=day, assessor='演示专业人员', past_medical_history=history, recent_symptoms=symptom, sleep_quality='差' if '长期失眠' in diseases else '一般' if i%4==0 else '好', sleep_hours='<6小时' if '长期失眠' in diseases else '6-8小时', smoking_status='有' if gender=='男' and i%5==0 else '无', drinking_status='有' if i%8==0 else '无', exercise_methods=json.dumps(['散步','太极'] if years<80 and i%3==0 else ['散步'] if i%5 else ['室内伸展'],ensure_ascii=False), health_needs=json.dumps(['医师指导','定期健康检测'] if diseases else ['健康讲座','上门服务'] if years>=80 else ['健康讲座'],ensure_ascii=False), blood_pressure_test='监测：偏高' if '高血压' in diseases and i%3 else '监测：正常', blood_sugar_test='监测：偏高' if '2型糖尿病' in diseases and i%4 else '监测：正常', blood_lipid_test='监测：偏高' if ('脂肪肝' in diseases or i%9==0) else '监测：正常', notes=NOTICE, created_at=day+' 09:00:00')
            add('v2_risks', customer_id=cid, level='重点关注' if len(diseases)>1 else '常规管理', assessed_at='2026-11-02 10:00:00', professional='演示专业人员', notes='虚构专业记录：按本人反馈安排随访，不自动推断疾病。')
            # Nine selectable metrics, three real sample dates per person, not zero-filled curves.
            for k, month in enumerate((2,6,11)):
                when = f'2026-{month:02d}-03 08:30:00'
                delta = [-1,0,1,2][i%4] * k
                values = [('systolic', (143 if '高血压' in diseases else 118)+i%14-delta, 'mmHg',90,140),('diastolic', (87 if '高血压' in diseases else 72)+i%8-k,'mmHg',60,90),('glucose',round((6.8 if '2型糖尿病' in diseases else 4.5)+i%9/10-k*.1,1),'mmol/L',3.9,6.1),('cholesterol',round(4.1+i%17/10-k*.1,1),'mmol/L',2.9,5.2),('triglycerides',round(.8+i%16/10-k*.05,2),'mmol/L',.4,1.7),('hdl',round(1.1+i%8/10,1),'mmol/L',1,2.5),('ldl',round(2+i%16/10-k*.1,1),'mmol/L',1,3.4),('spo2',96+i%4,'%',95,100),('pain',max(0,3+i%5-k*(i%3)),'分（0无痛，10最痛）',0,10)]
                for metric,value,unit,low,high in values:
                    add('v2_measurements',customer_id=cid,measured_at=when,metric=metric,value=value,unit=unit,source='虚构检测中心',report=f'DEMO-{i:03d}-{month:02d}-{metric}',opinion='虚构检测值及参考范围，用于界面展示。',reference_low=low,reference_high=high,target_low=low if metric=='systolic' else None,target_high=high if metric=='systolic' else None,recorded_by='演示专业人员',created_at=when)
                add('health_records',customer_id=cid,record_date=when[:10],height_cm=155+i%23,weight_kg=55+i%25,blood_pressure=f'{values[0][1]}/{values[1][1]}',symptoms=symptom,diagnosis='虚构档案：'+history,notes=NOTICE,created_at=when)
        # Reported downtime is excluded from generated service slots, including pending repairs.
        faults = defaultdict(list)
        for j,(code,_,_) in enumerate(PROJECTS):
            for month in (3,7,11):
                eid = devices[code][0]
                start = datetime(2026,month,5+j%3,9)
                restored = not(month==11 and j in (1,5))
                finish = start+timedelta(hours=3+j%3) if restored else None
                faults[eid].append((start,finish))
                add('v2_maintenance',equipment_id=eid,fault_type=['连接异常','传感器校准','日常检查异常'][j%3],reported_at=stamp(start),down_at=stamp(start),repair_started_at=stamp(start+timedelta(minutes=30)),repair_finished_at=stamp(finish-timedelta(minutes=15)) if finish else None,restored_at=stamp(finish) if finish else None,status='已恢复' if restored else '维修中',solution='虚构维修：更换部件并完成复测' if restored else '虚构维修：已安排专业检修，暂停使用',recorded_by='演示设备管理员')
                if not restored:conn.execute("UPDATE equipment SET status='maintenance' WHERE id=?",(eid,))
        records = defaultdict(list)
        person_busy = defaultdict(list)
        weights = {'MOXA':[30,43,16,3,6,2],'OXYGEN':[23,42,22,3,8,2],'INFRARED':[28,40,20,4,6,2],'MASSAGE':[36,41,14,2,5,2]}
        statuses = ['明显改善','部分改善','无变化','加重','未评价','不适用']
        durations = [40,60,25,35,20,30]
        base = [42,24,20,34,18,50]
        for month in range(1,12):
            last = min(calendar.monthrange(2026,month)[1], AS_OF.day if month==AS_OF.month else 31)
            days = [date(2026,month,d) for d in range(1,last+1) if date(2026,month,d).weekday() in (0,2,4)]
            for j,(code,name,category) in enumerate(PROJECTS):
                slots=[]
                for day in days:
                    for eid in devices[code]:
                        for start_hour,end_hour in ((9,12),(13,16)):
                            add('v2_capacity',equipment_id=eid,start_at=stamp(datetime.combine(day,datetime.min.time()).replace(hour=start_hour)),end_at=stamp(datetime.combine(day,datetime.min.time()).replace(hour=end_hour)))
                        for hour in (9,10,11,13,14,15):
                            start=datetime.combine(day,datetime.min.time()).replace(hour=hour)
                            end=start+timedelta(minutes=durations[j])
                            if any(start<(stop or datetime(2026,12,31)) and end>begin for begin,stop in faults[eid]):continue
                            slots.append((start,end,eid))
                baseline=[]
                if month in (1,11):baseline=[cid for cid in people if (cid-1)%6==j]
                if month==2:
                    destinations=[2,4,5,2,0,4]
                    baseline=[cid for cid in people if destinations[(cid-1)%6]==j]
                count=min(len(slots),len(baseline)+base[j]+month*2+rng.randrange(-4,7))
                # Concentrate some repeated use in a project-specific cohort; all 300 still have core records.
                participants=baseline+[1+(n*7+j*43)%180 for n in range(max(0,count-len(baseline)))]
                selected=sorted(rng.sample(slots,count))
                available=selected+[slot for slot in slots if slot not in selected]
                for n,cid in enumerate(participants):
                    slot=next((slot for slot in available if all(slot[0]>=stop or slot[1]<=begin for begin,stop in person_busy[cid])),None)
                    if slot is None:raise RuntimeError('No non-overlapping service slot available.')
                    available.remove(slot)
                    start,end,eid=slot
                    person_busy[cid].append((start,end))
                    channel='home' if month>2 and (cid+n)%13==0 else 'onsite'
                    use_old=channel=='onsite' and n%3!=0
                    member=people[cid]
                    if use_old:
                        sid=add('appointments',customer_id=cid,equipment_id=eid,project_id=pids[code],staff_id=staff[j%len(staff)],appointment_date=start.date().isoformat(),start_time=start.strftime('%H:%M'),end_time=end.strftime('%H:%M'),status='completed',checkin_status='arrived',notes='虚构服务：'+member['symptom'],created_at=stamp(start-timedelta(days=2)),updated_at=stamp(end))
                        ref='appointment:'+str(sid)
                    else:
                        sid=add('v2_services',customer_id=cid,project_code=code,channel=channel,status='completed',scheduled_at=stamp(start),completed_at=stamp(end),duration_minutes=durations[j],equipment_id=eid,concern=member['symptom'],notes='虚构专业服务；按实际资质与适应范围登记。',recorded_by='演示驻场人员',created_at=stamp(start))
                        ref='service:'+str(sid)
                    records[cid].append(dict(ref=ref,code=code,date=end,source='appointments' if use_old else 'v2',sid=sid))
                    if category=='screening':
                        valid=rng.random()>.07
                        abnormal='异常' if valid and (member['age']>=80 and rng.random()<.38 or rng.random()<.12) else '未见异常' if valid else '未知'
                        followed=abnormal=='异常' and (month<11 or rng.random()<.7)
                        add('v2_screenings',service_ref=ref,customer_id=cid,project_code=code,completed=1,valid_report=int(valid),abnormal=abnormal,report=f'虚构{name}报告 DEMO-{month:02d}-{cid:03d}-{n:03d}，结果仅作功能演示。' if valid else '',professional_opinion='虚构专业建议：安排复查并记录结果。' if abnormal=='异常' else '虚构专业记录：保留报告。',followup_status='已跟进' if followed else '待跟进' if abnormal=='异常' else '无需跟进',due_date=(end+timedelta(days=14)).date().isoformat() if abnormal=='异常' else None,followup_result='虚构回访：已协助预约专业复查。' if followed else '',recorded_by='演示专业人员',recorded_at=stamp(end))
                    else:
                        status=rng.choices(statuses,weights[code])[0]
                        before=4+cid%5
                        after=max(0,before-3) if status=='明显改善' else before-1 if status=='部分改善' else before if status=='无变化' else min(10,before+1) if status=='加重' else None
                        follow='待复评' if month==11 and status in ('加重','未评价') else '无需复评'
                        add('v2_reviews',service_ref=ref,customer_id=cid,project_code=code,evaluation_type='single',baseline_at=stamp(start),evaluated_at=stamp(end) if after is not None else None,dimension='专业目标困扰程度' if code=='OXYGEN' else '局部不适',before_score=before,after_score=after,status=status,adverse='有不适' if status=='加重' else '未询问' if status=='未评价' else '无不适',adverse_notes='虚构反馈：暂停体验，联系专业人员复核。' if status=='加重' else '',notes='本人主观体验的虚构记录，不证明医学疗效。',due_date='2026-11-25' if follow=='待复评' else None,followup_status=follow,recorded_by='演示驻场人员',created_at=stamp(end))
                        if use_old and n%9==1:
                            add('service_improvement_records',service_id=sid,service_type='appointments',customer_id=cid,service_time=stamp(end),service_project=name,pre_service_status=f'虚构基线困扰 {before}/10',service_content='虚构体验，已关联同一服务编号',post_service_evaluation='本人虚构反馈：'+status,improvement_status=status,created_at=stamp(end),updated_at=stamp(end))
        # Non-device home services are additional distinct records, never a seventh project.
        for month in range(1,12):
            for n in range(8+month):
                cid=1+(month*19+n*11)%300
                start=datetime(2026,month,2+n%20,16)
                end=start+timedelta(minutes=45)
                if any(start<stop and end>begin for begin,stop in person_busy[cid]):raise RuntimeError('Home visit overlaps another service.')
                person_busy[cid].append((start,end))
                add('v2_services',customer_id=cid,project_code=None,channel='home',status='completed',scheduled_at=stamp(start),completed_at=stamp(start+timedelta(minutes=45)),duration_minutes=45,concern='居家活动与服务需求',notes='虚构非设备上门：记录环境、活动与服务需求。',recorded_by='演示上门专员',created_at=stamp(start))
        # Scheduled/cancelled/no-show bookings populate the original operating tools as well.
        for i in range(1,61):
            j=(i-1)%6;code,name,_=PROJECTS[j]
            status=['scheduled','cancelled','no_show'][((i-1)//6)%3]
            when=datetime(2026,11,26 if status=='scheduled' else 20+i%6,16)+timedelta(minutes=30*((i-1)//18))
            common=dict(customer_id=i,project_id=pids[code],staff_id=staff[j%len(staff)],appointment_date=when.date().isoformat(),start_time=when.strftime('%H:%M'),end_time=(when+timedelta(minutes=30)).strftime('%H:%M'),status=status,notes='虚构预约：用于演示履约与状态管理',created_at=stamp(when-timedelta(days=1)),updated_at=stamp(when))
            if i%2:add('appointments',equipment_id=devices[code][1],**common)
            else:add('home_appointments',customer_name=f'演示干部{i:03d}',phone=f'1990000{i:04d}',location=f'虚构军休所第{(i-1)//30+1}组',home_address='虚构居住点',service_project=name,staff_name='演示上门专员',**common)
        for month in range(1,12):
            last=min(calendar.monthrange(2026,month)[1],24)
            candidates=sorted({(cid,r['code']) for cid,items in records.items() for r in items if r['date'].month==month and r['date'].day<=last and r['code'] in weights})
            for cid,code in rng.sample(candidates,min(len(candidates),48+month*2)):
                status=rng.choices(['部分改善','无变化','加重','未评价'],[62,24,4,10 if month==11 else 3])[0]
                after=4 if status=='部分改善' else 7 if status=='无变化' else 8 if status=='加重' else None
                add('v2_reviews',customer_id=cid,project_code=code,evaluation_type='stage',window_start=f'2026-{month:02d}-01',window_end=f'2026-{month:02d}-{last:02d}',baseline_at=f'2026-{month:02d}-01 10:00:00',evaluated_at=f'2026-{month:02d}-{last:02d} 16:00:00' if after is not None else None,dimension='专业目标困扰程度' if code=='OXYGEN' else '局部不适',before_score=7,after_score=after,status=status,adverse='未询问' if after is None else '无不适',due_date=(date(2026,month,last)+timedelta(days=14)).isoformat(),followup_status='待复评' if after is None else '已复评',notes='虚构阶段回访，窗口与单次评价分开统计。',recorded_by='演示专业人员',created_at=f'2026-{month:02d}-01 10:00:00')
        needs=['增加康养设备','健康讲座','医师指导','定期健康检测','上门服务','其他']
        task_count=0
        for cid, services in records.items():
            # Each person's latest three distinct services are eligible for a questionnaire.
            for k,service in enumerate(sorted(services,key=lambda r:r['date'])[-3:]):
                if cid%17==0:continue
                when=service['date']+timedelta(minutes=30)
                overall=rng.choices([5,4,3,2,1],[37,43,14,5,1])[0]
                chosen=rng.sample(needs,1+(cid+k)%3)
                if people[cid]['age']>=80 and '上门服务' not in chosen:chosen.append('上门服务')
                comment=['建议增加周三预约时段','希望安排睡眠主题健康讲座','建议简化预约说明','希望增加上门回访','建议加强检测报告讲解'][cid%5] if (cid+k)%11==0 else ''
                survey=add('v2_surveys',customer_id=cid,service_ref=service['ref'],answered_at=stamp(when),overall=overall,attitude=rng.choices([3,4,5],[5,35,60])[0],guidance=rng.choices([2,3,4,5],[3,12,40,45])[0],device=rng.choices([2,3,4,5],[5,17,43,35])[0],booking=rng.choices([2,3,4,5],[8,22,42,28])[0],environment=rng.choices([3,4,5],[8,39,53])[0],needs_answered=1,needs_json=json.dumps(chosen,ensure_ascii=False),comment=comment,recorded_by='演示回访专员')
                if comment:
                    status=['待处理','处理中','已完成','已反馈'][task_count%4];task_count+=1
                    add('v2_tasks',customer_id=cid,survey_id=survey,category=['预约安排','健康教育','专业指导'][cid%3],title='虚构意见：'+comment,status=status,owner=f'演示负责人{cid%3+1}',due_date=(when+timedelta(days=7)).date().isoformat(),result='虚构处理：已调整服务安排并记录执行结果。' if status in ('已完成','已反馈') else '',feedback_at=stamp(when+timedelta(minutes=30)) if status=='已反馈' else None,created_at=stamp(when),updated_at=stamp(when+timedelta(minutes=30)))
        for cid in range(1,301):
            add('visit_checkins',customer_id=cid,checkin_time='2026-11-02 08:30:00',purpose='虚构康养服务登记',notes=NOTICE,created_at='2026-11-02 08:30:00')
        for username,role,cid,view,export in [('demo_manager','manager',None,0,1),('demo_operator','operator',None,1,0),('demo_professional','professional',None,1,1),('demo_resident','resident',1,1,1)]:
            add('v2_accounts',username=username,password_hash=generate_password_hash('Demo2026!'),role=role,customer_id=cid,can_view_personal=view,can_export=export,created_at='2026-01-01 08:00:00')
        for key,value in {'demo_mode':'true','demo_v2':'true','case_dataset_version':VERSION,'demo_as_of':AS_OF.isoformat(),'unit_name':'静安军休所 · 300 位虚构案例'}.items():
            conn.execute('INSERT OR REPLACE INTO system_settings(setting_key,setting_value) VALUES (?,?)',(key,value))
        conn.execute("DELETE FROM system_settings WHERE setting_key='backup_directory'")
        add('audit_logs',action='初始化300位虚构案例',module='customers',target_id='300',details=NOTICE,username='admin',created_at='2026-11-26 09:00:00')
        conn.commit()
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Generated dataset failed integrity checks.')
        names=['customers','health_assessments','appointments','home_appointments','v2_services','v2_reviews','v2_screenings','v2_measurements','v2_surveys','v2_tasks','v2_maintenance','v2_capacity','service_improvement_records']
        counts={table:conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in names}
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    return {'notice':NOTICE,'version':VERSION,'as_of':AS_OF.isoformat(),'counts':counts,'cases':manifest}


def seed(directory, replace=False, upgrade_demo=False):
    directory=Path(directory).expanduser().resolve();directory.mkdir(parents=True,exist_ok=True)
    db=directory/'medical_system.db';settings=markers(db)
    if db.exists() and not replace:
        if settings.get('case_dataset_version')==VERSION:
            print('Existing 300-case database preserved.');return
        if not(upgrade_demo and settings.get('demo_v2')=='true'):
            raise RuntimeError('Existing database found. Use --replace to replace it with the 300 fictional cases.')
    with tempfile.TemporaryDirectory(prefix='.case-build-',dir=directory) as temporary:
        source=Path(temporary)
        try:
            manifest=build(source)
        finally:
            import logging
            logging.shutdown()
        backup=None
        if db.exists():
            folder=directory/'database_backups';folder.mkdir(exist_ok=True)
            backup=folder/('before_300_cases_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
            with closing(sqlite3.connect(db,timeout=2)) as current:
                current.execute('BEGIN EXCLUSIVE');current.rollback()
                with closing(sqlite3.connect(backup)) as old:current.backup(old)
        with closing(sqlite3.connect(source/'medical_system.db')) as src, closing(sqlite3.connect(db,timeout=2)) as dst:
            src.backup(dst)
            dst.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        # File logging would otherwise keep a handle inside the staging folder on Windows.
        import logging
        logging.shutdown()
    (directory/'cases_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('300-case database ready: '+json.dumps(manifest['counts']))
    if backup:print('Previous database backup: '+str(backup))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',default=str(ROOT))
    parser.add_argument('--replace',action='store_true',help='Replace existing records; a recovery backup is kept.')
    parser.add_argument('--upgrade-demo',action='store_true',help='Replace an older marked demo once; retain an existing current dataset.')
    args=parser.parse_args()
    seed(args.data_dir,args.replace,args.upgrade_demo)
