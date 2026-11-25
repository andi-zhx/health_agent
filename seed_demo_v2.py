"""100 fictional people in an isolated, non-destructive V2 demonstration database."""
import argparse
from contextlib import closing
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parent
AS_OF=datetime(2026,11,25,12)


def seed(directory):
    directory=Path(directory).expanduser().resolve()
    if directory==ROOT:raise RuntimeError('Use a separate demo directory. The project database must not be overwritten.')
    db=directory/'medical_system.db'
    if db.exists():
        with closing(sqlite3.connect(db)) as conn:
            try:marker=conn.execute("SELECT setting_value FROM system_settings WHERE setting_key='demo_v2'").fetchone()
            except sqlite3.Error:marker=None
        if marker and marker[0]=='true':
            print('Existing V2 demo preserved; no records replaced.');return
        raise RuntimeError('Existing non-demo database found. Select a new empty folder; nothing was changed.')
    directory.mkdir(parents=True,exist_ok=True);os.environ['HEALTH_AGENT_DATA_DIR']=str(directory)
    from app import app
    from backend import core
    from backend.care_v2.schema import PROJECTS
    from werkzeug.security import generate_password_hash
    if Path(core.DB_PATH).resolve()!=db:raise RuntimeError('Run the seed script in a fresh process.')
    patterns=[['高血压'],['膝骨关节炎','腰椎间盘突出'],['2型糖尿病','脂肪肝'],['长期失眠'],['焦虑状态'],[],['高血压','冠心病'],['颈椎病'],['听力下降'],[]]
    symptoms=['关节疼痛','入睡困难','餐后乏力','胃胀反酸','气短咳嗽','无','头晕头痛','肩颈不适','沟通困难','未回答']
    with closing(core.get_db()) as conn:
        def add(table,values):
            return conn.execute('INSERT INTO '+table+' ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',list(values.values())).lastrowid
        # The formal initializer never invents physical assets. Only this isolated demo does.
        for code,name,_ in PROJECTS:
            for i in (1,2):
                eid=add('equipment',{'name':name+'演示'+str(i),'type':'虚构演示设备','model':'DEMO','location':'虚构体验区','status':'available','description':'仅用于演示，不代表真实设备资产'})
                add('v2_equipment',{'equipment_id':eid,'project_code':code,'asset_code':'DEMO-'+code+'-'+str(i),'registered_at':'2026-01-01 09:00:00'})
                add('project_equipment_mapping',{'project_name':name,'equipment_name':name+'演示'+str(i),'status':'enabled'})
        equipment={code:[r[0] for r in conn.execute('SELECT equipment_id FROM v2_equipment WHERE project_code=? ORDER BY equipment_id',(code,))] for code,_,_ in PROJECTS}
        manifest=[]
        for i in range(1,101):
            disease=patterns[(i-1)%10];history='、'.join(disease) or ('不详' if i%10==0 else '无');birth=f'{2026-(60+i%33)}-{i%12+1:02d}-15' if i%11 else None
            cid=add('customers',{'name':f'演示干部{i:03d}','phone':f'1990000{i:04d}','gender':'未知' if i%11==0 else '女' if i%4==0 else '男','birth_date':birth,'age':None,'identity_type':'本人','record_creator':'演示专员','address':'虚构演示地址','medical_history':history,'created_at':'2026-01-02 09:00:00','updated_at':'2026-11-20 09:00:00','is_deleted':0})
            manifest.append({'id':cid,'name':f'演示干部{i:03d}','fictional':True,'history':history})
            if i%10:
                for day in ('2026-02-01','2026-11-01'):
                    add('health_assessments',{'customer_id':cid,'assessment_date':day,'assessor':'演示专业人员','past_medical_history':history,'recent_symptoms':symptoms[(i-1)%10],'sleep_quality':'差' if i%4==0 else '一般' if i%3==0 else '好','sleep_hours':'<6小时' if i%4==0 else '6-8小时','smoking_status':'有' if i%7==0 else '无','drinking_status':'有' if i%8==0 else '无','exercise_methods':json.dumps(['散步','太极'] if i%3 else ['散步'],ensure_ascii=False),'health_needs':json.dumps(['健康讲座','医师指导'] if i%2 else ['定期健康检测','上门服务'],ensure_ascii=False),'blood_pressure_test':'未监测' if i%5==0 else '监测：偏高' if '高血压' in disease else '监测：正常','blood_sugar_test':'未监测' if i%6==0 else '监测：偏高' if '2型糖尿病' in disease else '监测：正常','blood_lipid_test':'未监测' if i%7==0 else '监测：正常','notes':'虚构案例，仅供系统功能展示','created_at':day+' 09:00:00'})
            if i%8:
                add('v2_risks',{'customer_id':cid,'level':'紧急跟进' if i%19==0 else '重点关注' if i%3==0 else '常规管理','assessed_at':'2026-11-02 09:00:00','professional':'演示专业人员','notes':'虚构专业确认记录；正式使用需真实专业判断'})
            for round_no,(code,name,category) in enumerate(PROJECTS):
                when=AS_OF-timedelta(days=(6-round_no)*22-(i%15),hours=2);start=when.replace(hour=9+(i%6),minute=0,second=0);end=start+timedelta(minutes=30)
                sid=add('v2_services',{'customer_id':cid,'project_code':code,'channel':'home' if i%10==0 and round_no==5 else 'onsite','status':'completed','scheduled_at':start.isoformat(' '),'completed_at':end.isoformat(' '),'duration_minutes':30,'equipment_id':equipment[code][i%len(equipment[code])],'concern':symptoms[(i-1)%10],'notes':'虚构服务，不代表真实疗程或医学疗效','recorded_by':'演示驻场人员','created_at':start.isoformat(' ')})
                ref='service:'+str(sid)
                if category=='screening':
                    if i%7:
                        abnormal='异常' if i%6==0 else '未见异常';valid=int(i%9!=0)
                        add('v2_screenings',{'service_ref':ref,'customer_id':cid,'project_code':code,'completed':1,'valid_report':valid,'abnormal':abnormal if valid else '未知','report':'虚构检测报告示例；不构成真实医学信息' if valid else '', 'professional_opinion':'按专业要求复查' if abnormal=='异常' else '记录结果','followup_status':'待跟进' if i%12==0 else '已跟进' if abnormal=='异常' else '无需跟进','due_date':'2026-11-24' if abnormal=='异常' else None,'followup_result':'虚构跟进记录：已联系复查' if i%12 and abnormal=='异常' else '', 'recorded_by':'演示专业人员','recorded_at':end.isoformat(' ')})
                elif i%8:
                    status=['明显改善','部分改善','无变化','加重','未评价','不适用'][i%6];before=4+i%5;after=None if status in ('未评价','不适用') else max(0,before-3) if status=='明显改善' else before-1 if status=='部分改善' else before if status=='无变化' else min(10,before+1)
                    add('v2_reviews',{'service_ref':ref,'customer_id':cid,'project_code':code,'evaluation_type':'single','baseline_at':start.isoformat(' '),'evaluated_at':end.isoformat(' ') if after is not None else None,'dimension':'专业目标困扰程度' if code=='OXYGEN' else '局部不适','before_score':before,'after_score':after,'status':status,'adverse':'有不适' if status=='加重' else '无不适','adverse_notes':'虚构不适，已暂停体验并安排专业复核' if status=='加重' else '', 'notes':'本人自述，虚构案例','due_date':'2026-11-24','followup_status':'待复评' if i%4==0 else '无需复评','recorded_by':'演示驻场人员','created_at':end.isoformat(' ')})
                if round_no in (0,3,5) and i%9:
                    stamp=(start+timedelta(hours=1)).isoformat(' ')
                    for metric,value in [('systolic',120+i%35-round_no),('diastolic',75+i%20),('glucose',round(4.5+(i%20)/10,1))]:
                        add('v2_measurements',{'customer_id':cid,'measured_at':stamp,'metric':metric,'value':value,'unit':'mmol/L' if metric=='glucose' else 'mmHg','source':'虚构检测仪器','report':'演示报告编号 '+str(cid)+'-'+str(round_no),'opinion':'此为虚构案例数值，不用于健康建议','reference_low':None,'reference_high':None,'target_low':None,'target_high':None,'recorded_by':'演示专业人员','created_at':stamp})
            if i%10==0:
                start=AS_OF-timedelta(days=5,hours=2)
                add('v2_services',{'customer_id':cid,'project_code':None,'channel':'home','status':'completed','scheduled_at':start.isoformat(' '),'completed_at':(start+timedelta(minutes=45)).isoformat(' '),'duration_minutes':45,'concern':'居家环境与活动情况记录','notes':'虚构非设备上门服务','recorded_by':'演示驻场人员','created_at':start.isoformat(' ')})
            if i<=35:
                done=i%3!=0
                add('v2_reviews',{'customer_id':cid,'project_code':'MOXA','evaluation_type':'stage','window_start':'2026-11-01','window_end':'2026-11-20','baseline_at':'2026-11-01 10:00:00','evaluated_at':'2026-11-21 10:00:00' if done else None,'dimension':'疼痛影响','before_score':7,'after_score':4 if done else None,'status':'部分改善' if done else '未评价','adverse':'无不适','due_date':'2026-11-24','followup_status':'已复评' if done else '待复评','notes':'虚构阶段复评，不预填未复评结论','recorded_by':'演示专业人员','created_at':'2026-11-01 10:00:00'})
            if i<=80:
                survey=add('v2_surveys',{'customer_id':cid,'answered_at':f'2026-11-{i%20+1:02d} 15:00:00','overall':None if i%9==0 else 5 if i%3==0 else 4 if i%4 else 3,'attitude':5 if i%2 else 4,'guidance':None if i%7==0 else 4,'device':3+i%3,'booking':3+i%3,'environment':4 if i%3 else 5,'needs_answered':int(i%8!=0),'needs_json':json.dumps(['健康讲座','医师指导'] if i%8 and i%2 else ['定期健康检测','上门服务'] if i%8 else [],ensure_ascii=False),'comment':'希望增加健康讲座，完善预约安排' if i%5==0 else '', 'recorded_by':'演示驻场人员'})
                if i%5==0:
                    status=['待处理','处理中','已完成','已反馈'][i%4]
                    add('v2_tasks',{'customer_id':cid,'survey_id':survey,'category':'健康教育','title':'虚构建议：增加健康讲座并完善预约安排','status':status,'owner':'演示负责人','due_date':'2026-11-24','result':'已安排下一次专题讲座' if status in ('已完成','已反馈') else '', 'feedback_at':'2026-11-23 10:00:00' if status=='已反馈' else None,'created_at':f'2026-11-{i%20+1:02d} 15:00:00','updated_at':'2026-11-24 10:00:00'})
        for idx,(code,_,_) in enumerate(PROJECTS):
            eid=equipment[code][0];restored=idx%2==0
            add('v2_maintenance',{'equipment_id':eid,'fault_type':'日常检查异常' if restored else '待专业检修','reported_at':'2026-11-22 09:00:00','down_at':'2026-11-22 09:00:00','repair_started_at':'2026-11-22 10:00:00','repair_finished_at':'2026-11-22 14:00:00' if restored else None,'restored_at':'2026-11-22 15:00:00' if restored else None,'status':'已恢复' if restored else '维修中','solution':'虚构维修记录，复测后恢复使用' if restored else '虚构记录，等待专业维修','recorded_by':'演示设备管理员'})
            if not restored:conn.execute("UPDATE equipment SET status='maintenance' WHERE id=?",(eid,))
            for dayno in range(1,26):
                for eq in equipment[code]:add('v2_capacity',{'equipment_id':eq,'start_at':f'2026-11-{dayno:02d} 08:00:00','end_at':f'2026-11-{dayno:02d} 17:00:00'})
        for username,role,cid,view,export in [('demo_manager','manager',None,0,1),('demo_operator','operator',None,1,0),('demo_professional','professional',None,1,1),('demo_resident','resident',1,1,1)]:
            add('v2_accounts',{'username':username,'password_hash':generate_password_hash('Demo2026!'),'role':role,'customer_id':cid,'can_view_personal':view,'can_export':export,'created_at':core.now_local_str()})
        for key,value in {'demo_mode':'true','demo_v2':'true','unit_name':'军休所 · V2 虚构演示环境'}.items():conn.execute('INSERT OR REPLACE INTO system_settings(setting_key,setting_value) VALUES (?,?)',(key,value))
        conn.commit()
        result={table:conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('customers','health_assessments','v2_services','v2_reviews','v2_screenings','v2_measurements','v2_surveys','v2_tasks')}
    (directory/'cases_manifest.json').write_text(json.dumps({'notice':'100 位完全虚构案例；不能用于真实业绩或医学疗效结论','as_of':'2026-11-25','cases':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
    print('V2 demo ready: '+json.dumps(result))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',default=str(ROOT/'demo_v2_data'));args=parser.parse_args();seed(args.data_dir)
