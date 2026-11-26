from contextlib import closing
from datetime import datetime,timedelta
from io import BytesIO
import json
import sqlite3
from flask import Blueprint,request,render_template,send_file,session
from werkzeug.exceptions import Forbidden
from openpyxl import Workbook
from werkzeug.security import generate_password_hash
from backend import core
from . import analytics as a
from . import validation as v
from .schema import PROJECTS,PROJECT_BY_CODE,counts,archive
from .security import actor,can_personal,authorize_person,ROLES

bp=Blueprint('care_v2',__name__)

@bp.errorhandler(ValueError)
def validation_error(error):return core.error_response(str(error))

@bp.errorhandler(sqlite3.IntegrityError)
def integrity_error(error):return core.error_response('记录重复或关联数据无效，请刷新后核对',409,'CONFLICT')

@bp.errorhandler(Forbidden)
def privacy_error(error):return core.error_response(error.description,403,'FORBIDDEN')


def payload():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):raise ValueError('请求内容必须为对象')
    return data


def write_row(conn,table,values,rid=None):
    if rid:
        if not conn.execute('SELECT 1 FROM '+table+' WHERE id=?',(rid,)).fetchone():raise ValueError('记录不存在')
        conn.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in values)+' WHERE id=?',list(values.values())+[rid])
    else:
        rid=conn.execute('INSERT INTO '+table+' ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',list(values.values())).lastrowid
    conn.commit()
    core.audit_log('更新' if request.method=='PUT' else '登记',table,rid,'V2 业务记录')
    return core.success_response({'id':rid},'已保存',200 if request.method=='PUT' else 201)


def current_service(ref,completed=True):
    service=next((s for s in a.dataset()['services'] if s['ref']==ref),None)
    if not service or service['historical']:raise ValueError('请选择六项正式项目或非设备上门服务记录')
    if completed and service['status']!='completed':raise ValueError('服务完成后才能登记评价或检测结果')
    if not can_personal(service['customer_id']):raise ValueError('未获该档案操作授权')
    return service


def sanitized(data,user):
    """Only authenticated individual readers receive drill-down identifiers and names."""
    people={p['id']:p for p in data.pop('_people')};data.pop('_data');data['health'].pop('_person_tags',None)
    allowed=bool(user['can_view_personal'] and user['role']!='resident')
    if not allowed and 0<len(people)<5:
        raise Forbidden('筛选结果不足 5 人，已隐藏细分统计以保护个人信息；请扩大范围或申请个人数据授权')
    def label(rows):
        for r in rows:
            cid=r.get('customer_id')
            if cid:
                r['person_label']=people.get(cid,{}).get('name','档案已停用') if allowed else '已脱敏'
                if not allowed:
                    for key in ('customer_id','service_ref','ref','service_id','id','record_id','notes','concern','adverse_notes','report','professional_opinion','followup_result','comment','legacy_status','before_score','after_score'):
                        r.pop(key,None)
    for section,key in [('operations','service_records'),('operations','home_records'),('effects','records'),('effects','stage_records'),('effects','screenings'),('satisfaction','records'),('satisfaction','tasks')]:label(data[section][key])
    if not allowed:
        # Managers see counts, not small-sample person-level rows.
        for key in ('records','stage_records','screenings'):data['effects'][key]=[]
        data['satisfaction']['records']=[]
        data['operations']['service_records']=[];data['operations']['home_records']=[]
        data['satisfaction']['tasks']=[{k:r.get(k) for k in ('category','status','owner','due_date')} for r in data['satisfaction']['tasks']]
    return data


@bp.get('/api/v2/meta')
def meta():
    user=actor()
    if not user:return core.error_response('请先登录',401)
    with closing(core.get_db()) as conn:
        projects=a.rows(conn,'SELECT * FROM v2_projects ORDER BY rowid')
        equipment=a.rows(conn,'SELECT v.*,e.name,e.status,e.location FROM v2_equipment v JOIN equipment e ON e.id=v.equipment_id ORDER BY v.project_code,v.equipment_id')
        demo=core.get_setting_value('demo_mode','false')=='true'
    return core.success_response({'user':user,'roles':ROLES,'projects':projects,'equipment':equipment,'metrics':{k:{'name':x[0],'unit':x[1]} for k,x in v.METRICS.items()},'dimensions':v.DIMENSIONS,'needs':v.NEEDS,'statuses':v.STATUS,'today':core.now_local_date_str(),'demo':demo,'demo_as_of':core.get_setting_value('demo_as_of','')})


@bp.get('/api/v2/snapshot')
def snapshot_api():
    return core.success_response(sanitized(a.snapshot(a.filters(request.args)),actor()))


@bp.get('/api/v2/people')
def people_list():
    user=actor();cid=user['customer_id'] if user['role']=='resident' else None
    if not can_personal(cid):return core.error_response('未获个人档案访问授权',403)
    with closing(core.get_db()) as conn:
        sql='SELECT id,name,gender,birth_date,age FROM customers WHERE is_deleted=0';params=[]
        if cid:sql+=' AND id=?';params.append(cid)
        term=v.text(request.args.get('search'),100)
        if term:sql+=' AND (name LIKE ? OR CAST(id AS TEXT)=?)';params.extend(['%'+term+'%',term])
        result=a.rows(conn,sql+' ORDER BY id',params)
    core.audit_log('查询个人档案列表','access','v2-people','授权人员查询')
    return core.success_response(result)


def personal_data(cid):
    data=a.dataset()
    person=next((p for p in data['people'] if p['id']==cid and not p['is_deleted']),None)
    if not person:raise ValueError('个人档案不存在')
    selected=lambda name:[r for r in data[name] if r.get('customer_id')==cid]
    services=sorted(selected('services'),key=lambda s:s['completed_at'] or s['scheduled_at'],reverse=True)
    completed=[s for s in services if s['status']=='completed']
    timeline=[]
    for s in services:timeline.append({'date':s['completed_at'] or s['scheduled_at'],'type':'检测服务' if PROJECT_BY_CODE.get(s['project_code'],{}).get('category')=='screening' else '服务','title':PROJECT_BY_CODE.get(s['project_code'],{}).get('name',s.get('project_name') or '历史 / 非设备上门服务'),'detail':s.get('notes') or '','ref':s['ref'],'status':s['status'],'historical':s['historical']})
    for m in selected('measurements'):timeline.append({'date':m['measured_at'],'type':'个人检测','title':v.METRICS[m['metric']][0],'detail':str(m['value'])+' '+m['unit']+'；'+(m['opinion'] or ''),'recorded_by':m['recorded_by']})
    for r in selected('risks'):timeline.append({'date':r['assessed_at'],'type':'专业管理意见','title':r['level'],'detail':r['notes'],'recorded_by':r['professional']})
    for r in selected('reviews'):
        timeline.append({'date':r['evaluated_at'] or r['baseline_at'] or r['created_at'],'type':'阶段复评' if r['evaluation_type']=='stage' else '体验反馈','title':PROJECT_BY_CODE[r['project_code']]['name']+' · '+r['status'],'detail':'；'.join(filter(None,[r['notes'],r['adverse_notes'],('下次复评 '+r['due_date']) if r['due_date'] else ''])),'recorded_by':r['recorded_by']})
    for r in selected('screenings'):
        timeline.append({'date':r['recorded_at'],'type':'检测报告与跟进','title':PROJECT_BY_CODE[r['project_code']]['name']+' · '+r['abnormal'],'detail':'；'.join(filter(None,[r['report'],r['professional_opinion'],r['followup_result']])),'recorded_by':r['recorded_by']})
    return {'person':person,'assessments':sorted(selected('assessments'),key=lambda r:r['assessment_date'],reverse=True),'measurements':sorted(selected('measurements'),key=lambda r:r['measured_at']),
        'services':services,'reviews':selected('reviews'),'screenings':selected('screenings'),'surveys':selected('surveys'),'risks':sorted(selected('risks'),key=lambda r:r['assessed_at'],reverse=True),'tasks':selected('tasks'),
        'timeline':sorted(timeline,key=lambda r:r['date'] or '',reverse=True),'summary':{'services':len(completed),'last_service':completed[0]['completed_at'] if completed else None,'projects':a.ranking(a.Counter(PROJECT_BY_CODE.get(s['project_code'],{}).get('name','历史 / 非设备上门') for s in completed))},'demo':data['settings'].get('demo_mode')=='true'}


@bp.get('/api/v2/personal/<int:cid>')
def personal(cid):
    denied=authorize_person(cid)
    if denied:return denied
    return core.success_response(personal_data(cid))


@bp.route('/api/v2/services',methods=['POST'])
@bp.route('/api/v2/services/<int:rid>',methods=['PUT'])
def save_service(rid=None):
    d=payload();channel=v.choice(d.get('channel'),('onsite','home'),'onsite');status=v.choice(d.get('status'),('scheduled','completed','cancelled','no_show'),'completed')
    code=v.project(d.get('project_code'),optional=channel=='home');scheduled=v.timestamp(d.get('scheduled_at'),future=True)
    completed=v.timestamp(d.get('completed_at')) if status=='completed' else None
    if completed and completed<scheduled:raise ValueError('完成时间不能早于开始时间')
    duration=v.number(d.get('duration_minutes'),1,1440,integer=True)
    if duration and completed and duration>(datetime.fromisoformat(completed)-datetime.fromisoformat(scheduled)).total_seconds()/60+1:raise ValueError('服务时长不能超过开始至完成的时间')
    eid=v.number(d.get('equipment_id'),1,2147483647,integer=True)
    with closing(core.get_db()) as conn:
        cid=v.customer(conn,d.get('customer_id'))
        if eid:
            e=conn.execute('SELECT v.*,e.status FROM v2_equipment v JOIN equipment e ON e.id=v.equipment_id WHERE v.equipment_id=?',(eid,)).fetchone()
            if not e or e['project_code']!=code:raise ValueError('设备与所选项目不匹配')
            if e['status']!='available' and status in ('scheduled','completed'):raise ValueError('设备处于维修或不可用状态')
        if rid:
            old=conn.execute('SELECT * FROM v2_services WHERE id=?',(rid,)).fetchone()
            if old:
                linked=conn.execute('SELECT 1 FROM v2_reviews WHERE service_ref=? UNION SELECT 1 FROM v2_screenings WHERE service_ref=?',('service:'+str(rid),)*2).fetchone()
                if linked and (old['customer_id']!=cid or old['project_code']!=code):raise ValueError('已有评价或检测记录的服务不能变更干部或项目')
                if linked and old['status']=='completed' and status!='completed':raise ValueError('已有评价或检测的完成服务不能改为未完成')
                if completed:
                    evaluated=conn.execute('SELECT evaluated_at FROM v2_reviews WHERE service_ref=? AND evaluated_at IS NOT NULL',('service:'+str(rid),)).fetchone()
                    if evaluated and evaluated[0]<completed:raise ValueError('服务完成时间不能晚于已登记评价时间')
        return write_row(conn,'v2_services',{'customer_id':cid,'project_code':code,'channel':channel,'status':status,'scheduled_at':scheduled,'completed_at':completed,'duration_minutes':duration,'equipment_id':eid,'concern':v.text(d.get('concern')),'notes':v.text(d.get('notes')),'recorded_by':actor()['username'],'created_at':core.now_local_str()},rid)


@bp.route('/api/v2/reviews',methods=['POST'])
@bp.route('/api/v2/reviews/<int:rid>',methods=['PUT'])
def save_review(rid=None):
    d=payload();kind=v.choice(d.get('evaluation_type'),('single','stage'),'single')
    service=current_service(v.text(d.get('service_ref'),80,True),completed=False) if kind=='single' else None
    code=service['project_code'] if service else v.project(d.get('project_code'))
    if not code or PROJECT_BY_CODE[code]['category']=='screening':raise ValueError('检测类请填写检测报告与跟进，不填写改善评价')
    status=v.choice(d.get('status'),v.STATUS,'未评价')
    before=v.number(d.get('before_score'),0,10);after=v.number(d.get('after_score'),0,10)
    if after is not None and before is None:raise ValueError('填写复评评分时必须有配对的基线评分')
    if before is not None or after is not None:dimension=v.choice(d.get('dimension'),v.DIMENSIONS)
    else:dimension=v.choice(d.get('dimension'),v.DIMENSIONS) if d.get('dimension') else ''
    baseline=v.timestamp(d.get('baseline_at'),required=False)
    if before is not None and not baseline:raise ValueError('有基线评分时需要基线日期')
    evaluated=v.timestamp(d.get('evaluated_at'),required=status in v.VALID_STATUS)
    if after is not None and not evaluated:raise ValueError('有复评评分时需要实际评价日期')
    if baseline and evaluated and evaluated<baseline:raise ValueError('评价时间不能早于基线时间')
    if service and service['status']!='completed' and (status in v.VALID_STATUS or after is not None or evaluated):raise ValueError('服务完成前仅可登记基线，不可登记实际改善评价')
    if service and service['completed_at'] and evaluated and evaluated<service['completed_at']:raise ValueError('服务评价时间不能早于服务完成时间')
    start=v.day(d.get('window_start'),required=kind=='stage');end=v.day(d.get('window_end'),required=kind=='stage')
    if start and end and start>end:raise ValueError('评价窗口起止顺序错误')
    if kind=='stage' and evaluated and evaluated[:10]<start:raise ValueError('复评时间不能早于窗口开始日期')
    adverse=v.choice(d.get('adverse'),('未询问','无不适','有不适'),'未询问');notes=v.text(d.get('adverse_notes'))
    if adverse=='有不适' and not notes:raise ValueError('有不适时请填写表现与处理情况')
    follow=v.choice(d.get('followup_status'),('待复评','已复评','无需复评'),'待复评')
    if follow=='已复评' and (not evaluated or status not in v.VALID_STATUS):raise ValueError('已复评需要实际评价时间和有效评价状态')
    with closing(core.get_db()) as conn:
        cid=service['customer_id'] if service else v.customer(conn,d.get('customer_id'))
        if rid:
            previous=conn.execute('SELECT * FROM v2_reviews WHERE id=?',(rid,)).fetchone()
            if previous and (previous['customer_id']!=cid or previous['project_code']!=code or previous['evaluation_type']!=kind or previous['service_ref']!=(service['ref'] if service else None)):
                raise ValueError('不能把已登记的评价改绑到其他干部、项目或服务')
        return write_row(conn,'v2_reviews',{'service_ref':service['ref'] if service else None,'customer_id':cid,'project_code':code,'evaluation_type':kind,'window_start':start,'window_end':end,'baseline_at':baseline,'evaluated_at':evaluated,'dimension':dimension,'before_score':before,'after_score':after,'status':status,'adverse':adverse,'adverse_notes':notes,'notes':v.text(d.get('notes')),'due_date':v.day(d.get('due_date')),'followup_status':follow,'recorded_by':actor()['username'],'created_at':core.now_local_str()},rid)


@bp.route('/api/v2/screenings',methods=['POST'])
@bp.route('/api/v2/screenings/<int:rid>',methods=['PUT'])
def save_screening(rid=None):
    d=payload();s=current_service(v.text(d.get('service_ref'),80,True));code=s['project_code']
    if not code or PROJECT_BY_CODE[code]['category']!='screening':raise ValueError('仅听力测试与荧光免疫分析仪使用检测评价')
    completed=v.number(d.get('completed',0),0,1,True,True);valid=v.number(d.get('valid_report',0),0,1,True,True)
    abnormal=v.choice(d.get('abnormal'),('未知','未见异常','异常'),'未知');report=v.text(d.get('report'),10000)
    if valid and (not completed or not report):raise ValueError('有效报告需要完成检测并填写报告内容')
    if abnormal!='未知' and not valid:raise ValueError('无有效报告时不能登记检测结论')
    professional=v.text(d.get('professional_opinion'))
    if actor()['role']=='operator' and (abnormal!='未知' or professional):raise ValueError('检测结论与专业意见请由专业人员或管理员录入')
    follow=v.choice(d.get('followup_status'),('待跟进','跟进中','已跟进','无需跟进'),'待跟进');result=v.text(d.get('followup_result'))
    if follow=='已跟进' and not result:raise ValueError('已跟进需要填写实际处理结果')
    with closing(core.get_db()) as conn:
        previous=conn.execute('SELECT * FROM v2_screenings WHERE id=?',(rid,)).fetchone() if rid else None
        if previous and previous['service_ref']!=s['ref']:raise ValueError('检测记录不能改绑到其他服务')
        if previous and actor()['role']=='operator':
            if previous['abnormal']!='未知' and (not valid or not completed or report!=previous['report']):
                raise ValueError('已有专业结论的原始报告请由专业人员更正；驻场人员可更新跟进结果')
            abnormal=previous['abnormal'];professional=previous['professional_opinion']
        return write_row(conn,'v2_screenings',{'service_ref':s['ref'],'customer_id':s['customer_id'],'project_code':code,'completed':completed,'valid_report':valid,'abnormal':abnormal,'report':report,'professional_opinion':professional,'followup_status':follow,'due_date':v.day(d.get('due_date')),'followup_result':result,'recorded_by':actor()['username'],'recorded_at':core.now_local_str()},rid)


@bp.post('/api/v2/measurements')
def save_measurement():
    d=payload();metric=v.choice(d.get('metric'),v.METRICS);label,unit,low,high=v.METRICS[metric]
    values={'measured_at':v.timestamp(d.get('measured_at')),'metric':metric,'value':v.number(d.get('value'),low,high,True),'unit':unit,'source':v.text(d.get('source')),'report':v.text(d.get('report'),10000),'opinion':v.text(d.get('opinion')),'recorded_by':actor()['username'],'created_at':core.now_local_str()}
    for prefix in ('reference','target'):
        left=v.number(d.get(prefix+'_low'),low,high);right=v.number(d.get(prefix+'_high'),low,high)
        if (left is None)!=(right is None) or (left is not None and left>right):raise ValueError('参考范围和个人目标须成对填写且下限不大于上限')
        values[prefix+'_low']=left;values[prefix+'_high']=right
    with closing(core.get_db()) as conn:
        values['customer_id']=v.customer(conn,d.get('customer_id'))
        return write_row(conn,'v2_measurements',values)


@bp.post('/api/v2/risks')
def save_risk():
    d=payload()
    with closing(core.get_db()) as conn:
        return write_row(conn,'v2_risks',{'customer_id':v.customer(conn,d.get('customer_id')),'level':v.choice(d.get('level'),('常规管理','重点关注','紧急跟进')),'assessed_at':v.timestamp(d.get('assessed_at')),'professional':actor()['username'],'notes':v.text(d.get('notes'),required=True)})


@bp.post('/api/v2/surveys')
def save_survey():
    d=payload();service=current_service(d['service_ref']) if d.get('service_ref') else None
    values={k:v.number(d.get(k),1,5,integer=True) for k in ('overall','attitude','guidance','device','booking','environment')}
    needs=d.get('needs') or []
    if not isinstance(needs,list) or any(n not in v.NEEDS for n in needs):raise ValueError('需求选项不合法')
    answered=v.number(d.get('needs_answered',0),0,1,True,True)
    if needs and not answered:raise ValueError('已选择需求时须标记已回答需求题')
    comment=v.text(d.get('comment'))
    if not any(value is not None for value in values.values()) and not answered and not comment:raise ValueError('问卷不能全部留空')
    with closing(core.get_db()) as conn:
        cid=service['customer_id'] if service else v.customer(conn,d.get('customer_id'))
        values.update(customer_id=cid,service_ref=service['ref'] if service else None,answered_at=v.timestamp(d.get('answered_at')),needs_answered=answered,needs_json=json.dumps(sorted(set(needs)),ensure_ascii=False),comment=comment,recorded_by=actor()['username'])
        # Save questionnaire and generated opinion task atomically.
        columns=list(values)
        rid=conn.execute('INSERT INTO v2_surveys ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',list(values.values())).lastrowid
        if comment:
            conn.execute("INSERT INTO v2_tasks(customer_id,survey_id,category,title,status,created_at,updated_at) VALUES (?,?,'问卷意见',?,'待处理',?,?)",(cid,rid,comment,core.now_local_str(),core.now_local_str()))
        conn.commit()
    core.audit_log('登记问卷','v2_surveys',rid,'包含意见自动建立待办')
    return core.success_response({'id':rid},'问卷已保存',201)


@bp.route('/api/v2/tasks',methods=['POST'])
@bp.route('/api/v2/tasks/<int:rid>',methods=['PUT'])
def save_task(rid=None):
    d=payload();status=v.choice(d.get('status'),('待处理','处理中','已完成','已反馈'),'待处理');result=v.text(d.get('result'));feedback=v.timestamp(d.get('feedback_at'),False)
    if status in ('已完成','已反馈') and not result:raise ValueError('完成处理需要填写结果')
    if status=='已反馈' and not feedback:raise ValueError('已反馈需要实际反馈时间')
    with closing(core.get_db()) as conn:
        cid=v.customer(conn,d['customer_id']) if d.get('customer_id') else None
        previous=conn.execute('SELECT customer_id FROM v2_tasks WHERE id=?',(rid,)).fetchone() if rid else None
        if (cid or (previous and previous[0])) and not actor()['can_view_personal']:
            return core.error_response('个人相关意见处理需要个人数据授权',403,'FORBIDDEN')
        values={'customer_id':cid,'category':v.text(d.get('category'),100,True),'title':v.text(d.get('title'),1000,True),'status':status,'owner':v.text(d.get('owner'),100),'due_date':v.day(d.get('due_date')),'result':result,'feedback_at':feedback,'updated_at':core.now_local_str()}
        if not rid:values['created_at']=core.now_local_str()
        return write_row(conn,'v2_tasks',values,rid)


@bp.route('/api/v2/maintenance',methods=['POST'])
@bp.route('/api/v2/maintenance/<int:rid>',methods=['PUT'])
def save_maintenance(rid=None):
    d=payload();eid=v.number(d.get('equipment_id'),1,2147483647,True,True)
    status=v.choice(d.get('status'),('待维修','维修中','已恢复'),'待维修')
    times={k:v.timestamp(d.get(k),required=k=='reported_at') for k in ('reported_at','down_at','repair_started_at','repair_finished_at','restored_at')}
    ordered=[times[k] for k in ('down_at','repair_started_at','repair_finished_at','restored_at') if times[k]]
    if ordered!=sorted(ordered):raise ValueError('停机、维修、恢复时间必须依次递增')
    if status=='已恢复' and (not times['restored_at'] or not v.text(d.get('solution'))):raise ValueError('恢复使用需要填写恢复时间和维修结果')
    if status!='已恢复' and times['restored_at']:raise ValueError('填写恢复使用时间时，状态必须为已恢复')
    if times['restored_at'] and times['restored_at']<times['reported_at']:raise ValueError('恢复时间不能早于故障报告时间')
    with closing(core.get_db()) as conn:
        if not conn.execute('SELECT 1 FROM v2_equipment WHERE equipment_id=?',(eid,)).fetchone():raise ValueError('设备不在正式台账中')
        previous=conn.execute('SELECT equipment_id FROM v2_maintenance WHERE id=?',(rid,)).fetchone() if rid else None
        if previous and previous['equipment_id']!=eid:raise ValueError('维修记录不能改绑设备')
        if status!='已恢复' and conn.execute("SELECT 1 FROM v2_maintenance WHERE equipment_id=? AND restored_at IS NULL AND id<>?",(eid,rid or 0)).fetchone():raise ValueError('设备已有未关闭故障，请更新原记录')
        values={'equipment_id':eid,'fault_type':v.text(d.get('fault_type'),100,True),**times,'status':status,'solution':v.text(d.get('solution')),'recorded_by':actor()['username']}
        conn.execute('UPDATE equipment SET status=? WHERE id=?',('available' if status=='已恢复' else 'maintenance',eid))
        return write_row(conn,'v2_maintenance',values,rid)


@bp.post('/api/v2/capacity')
def save_capacity():
    if actor()['role'] not in ('admin','professional'):return core.error_response('时长台账需要管理员或专业人员维护',403)
    d=payload();eid=v.number(d.get('equipment_id'),1,2147483647,True,True);start=v.timestamp(d.get('start_at'),future=True);end=v.timestamp(d.get('end_at'),future=True)
    if start>=end or (datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()>86400:raise ValueError('一次排班须为 24 小时以内的有效时段')
    with closing(core.get_db()) as conn:
        if not conn.execute('SELECT 1 FROM v2_equipment WHERE equipment_id=?',(eid,)).fetchone():raise ValueError('请选择正式台账设备')
        if conn.execute('SELECT 1 FROM v2_capacity WHERE equipment_id=? AND start_at<? AND end_at>?',(eid,end,start)).fetchone():raise ValueError('排班时段与已有台账重叠')
        return write_row(conn,'v2_capacity',{'equipment_id':eid,'start_at':start,'end_at':end})


@bp.get('/api/v2/admin/catalog')
def catalog():
    with closing(core.get_db()) as conn:
        links=a.rows(conn,'SELECT l.*,p.name AS old_name FROM v2_project_links l JOIN therapy_projects p ON p.id=l.legacy_project_id ORDER BY l.state,l.legacy_project_id')
        migrations=a.rows(conn,'SELECT * FROM v2_migrations ORDER BY id DESC')
        archived=conn.execute('SELECT COUNT(*) FROM v2_archive').fetchone()[0]
        fk=[list(r) for r in conn.execute('PRAGMA foreign_key_check')]
    return core.success_response({'links':links,'migrations':migrations,'archived_rows':archived,'foreign_key_errors':fk})


@bp.post('/api/v2/admin/catalog/confirm')
def confirm_catalog():
    d=payload();pid=v.number(d.get('legacy_project_id'),1,2147483647,True,True);code=v.project(d.get('project_code'))
    if d.get('confirmed') is not True:raise ValueError('请明确确认旧名称与正式项目的业务对应关系')
    with closing(core.get_db()) as conn:
        row=conn.execute('SELECT p.*,l.state FROM therapy_projects p JOIN v2_project_links l ON p.id=l.legacy_project_id WHERE p.id=?',(pid,)).fetchone()
        if not row or row['state']!='pending':raise ValueError('该项目不在待核验列表中')
        before=counts(conn)
        conn.execute("UPDATE v2_project_links SET proposed_code=?,state='confirmed',verified_by=?,verified_at=? WHERE legacy_project_id=?",(code,actor()['username'],core.now_local_str(),pid))
        from .schema import activate_confirmed_links
        activate_confirmed_links(conn)
        conn.execute('INSERT INTO v2_migrations(version,created_at,before_counts,after_counts,notes) VALUES (?,?,?,?,?)',('2.0-alias',core.now_local_str(),json.dumps(before),json.dumps(counts(conn)),row['name']+' → '+PROJECT_BY_CODE[code]['name']+'；业务确认：'+actor()['username']))
        conn.commit()
    core.audit_log('确认旧项目对应关系','v2_project_links',pid,code)
    return core.success_response({'id':pid},'对应关系已确认，历史服务保留原编号并纳入对应统计')


@bp.get('/api/v2/admin/accounts')
def list_accounts():
    with closing(core.get_db()) as conn:
        result=a.rows(conn,'SELECT id,username,role,customer_id,can_view_personal,can_export,active,created_at FROM v2_accounts ORDER BY id')
    return core.success_response(result)


@bp.route('/api/v2/admin/accounts',methods=['POST'])
@bp.route('/api/v2/admin/accounts/<int:rid>',methods=['PUT'])
def save_account(rid=None):
    d=payload();username=v.text(d.get('username'),80,True)
    if username==core.get_setting_value('login_username','admin'):raise ValueError('内置管理员继续使用原账号设置')
    role=v.choice(d.get('role'),('manager','operator','professional','resident'))
    password=v.text(d.get('password'),200)
    if (not rid or password) and len(password)<8:raise ValueError('新账号密码至少 8 位')
    with closing(core.get_db()) as conn:
        cid=v.customer(conn,d.get('customer_id')) if role=='resident' else None
        values={'username':username,'role':role,'customer_id':cid,'can_view_personal':v.number(d.get('can_view_personal',0),0,1,True,True),'can_export':v.number(d.get('can_export',0),0,1,True,True),'active':v.number(d.get('active',1),0,1,True,True)}
        if password:values['password_hash']=generate_password_hash(password)
        if not rid:values['created_at']=core.now_local_str()
        return write_row(conn,'v2_accounts',values,rid)


REPORT_NAMES={'operations':'康养运营简报','portrait':'群体健康画像报告','effects':'阶段康养成效报告','personal':'个人健康报告'}


def report_context():
    user=actor();kind=v.choice(request.args.get('kind'),REPORT_NAMES,'operations')
    if not user['can_export']:return None,core.error_response('当前账号未获报告与导出授权',403,'FORBIDDEN')
    if kind=='personal':
        cid=v.number(request.args.get('customer_id'),1,2147483647,True,True)
        denied=authorize_person(cid,export=True)
        if denied:return None,denied
        return {'kind':kind,'title':REPORT_NAMES[kind],'personal':personal_data(cid),'generated_at':core.now_local_str()},None
    if user['role']=='resident':return None,core.error_response('个人端不能导出群体报告',403)
    data=sanitized(a.snapshot(a.filters(request.args)),user)
    core.audit_log('生成汇总报告','v2_report',kind,json.dumps(data['filters'],ensure_ascii=False))
    return {'kind':kind,'title':REPORT_NAMES[kind],'data':data,'generated_at':core.now_local_str()},None


@bp.get('/api/v2/report')
def report():
    context,denied=report_context()
    if denied:return denied
    return render_template('care_v2_report.html',metrics=v.METRICS,projects=PROJECT_BY_CODE,**context)


@bp.get('/api/v2/export')
def export():
    context,denied=report_context()
    if denied:return denied
    book=Workbook();book.remove(book.active)
    def sheet(name,headers,rows):
        ws=book.create_sheet(name);ws.append(headers)
        for row in rows:
            ws.append(row)
            for cell in ws[ws.max_row]:
                if isinstance(cell.value,str):cell.data_type='s'
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=min(45,max(15,max(len(str(c.value or '')) for c in col)+2))
    if context['kind']=='personal':
        p=context['personal'];sheet('个人基本信息',['字段','内容'],[['姓名',p['person']['name']],['干部编号',p['person']['id']],['数据性质','虚构演示' if p['demo'] else '业务记录']])
        sheet('个人检测',['时间','指标','结果','单位','来源','专业意见'],[[r['measured_at'],v.METRICS[r['metric']][0],r['value'],r['unit'],r['source'],r['opinion']] for r in p['measurements']])
        sheet('个人服务',['服务编号','项目','方式','完成时间','状态'],[[r['ref'],PROJECT_BY_CODE.get(r['project_code'],{}).get('name',r.get('project_name') or '历史 / 非设备上门'),'上门' if r['channel']=='home' else '现场',r['completed_at'],r['status']] for r in p['services']])
        sheet('前后评价',['评价类型','窗口起','窗口止','维度','基线日期','前评分','复评日期','后评分','评价','回访状态'],[[r[k] for k in ('evaluation_type','window_start','window_end','dimension','baseline_at','before_score','evaluated_at','after_score','status','followup_status')] for r in p['reviews']])
    else:
        d=context['data'];o=d['operations'];h=d['health'];e=d['effects'];s=d['satisfaction']
        sheet('说明',['项','说明'],[['报告',context['title']],['期间',d['filters']['start']+' 至 '+d['filters']['end']],['数据性质','虚构演示数据，不作为真实业绩' if d['demo'] else '业务系统记录'],['人群口径',d['cohort_note']],['运营口径',o['sampling_note']],['画像口径',h['sampling_note']],['效果口径',e['sampling_note']],['满意度口径',s['sampling_note']]])
        if context['kind']=='operations':
            labels={'bookings':'预约人次','people':'实际服务人数','services':'累计服务人次','fulfillment':'履约率%','per_person':'人均服务次数','repeat_rate':'重复使用率%','utilization':'设备利用率%','availability':'设备可用率%','home_services':'上门服务人次'}
            sheet('核心指标',['指标','值'],[[label,o['summary'][key]] for key,label in labels.items()])
            sheet('设备使用',['项目','人数','人次'],[[r['name'],r['people'],r['services']] for r in o['projects']])
            sheet('设备月度趋势',['月份']+[p[1] for p in PROJECTS],[[r['month']]+[r['projects'][p[0]] for p in PROJECTS] for r in o['months']])
            sheet('维修故障',['设备编号','故障','报告时间','停机时间','恢复时间','状态'],[[r[k] for k in ('equipment_id','fault_type','reported_at','down_at','restored_at','status')] for r in o['maintenance']])
            sheet('上门服务',['月份','人数','人次'],[[r['month'],r['people'],r['services']] for r in o['home_months']])
        elif context['kind']=='portrait':
            sheet('年龄性别',['年龄段','男','女','合计'],[[r['age'],r['male'],r['female'],r['male']+r['female']] for r in h['demographics'] if r['age']!='未知'])
            for key,title in [('diseases','既往病史'),('symptoms','近期症状'),('needs','健康需求')]:sheet(title,['标签','人数','有效分母','比例%'],[[r[k] for k in ('name','count','denominator','percent')] for r in h[key]])
            sheet('专业管理分层',['等级','人数'],[[r['name'],r['count']] for r in h['risk']])
            sheet('资料完整度',['字段','有效人数','应评估人数','比例%'],[[r[k] for k in ('name','valid','expected','percent')] for r in h['completeness']])
            sheet('病史共存',['病史']+h['cooccurrence']['labels'],[[name]+h['cooccurrence']['matrix'][i] for i,name in enumerate(h['cooccurrence']['labels'])])
            sheet('年龄与健康问题',['年龄段','纳入人数','病史有效人数']+h['age_health']['labels'],[[r['age'],r['n'],r['valid']]+r['counts'] for r in h['age_health']['rows']])
            for key,title in [('smoking','吸烟情况'),('drinking','饮酒情况'),('exercise','运动方式'),('sleep','睡眠质量')]:sheet(title,['分类','人数'],[[r['name'],r['count']] for r in h['behaviors'][key]])
        else:
            sheet('项目反馈',['项目','项目类型','服务人次','有效评价','应评价','改善数','改善率%','覆盖率%']+list(v.STATUS),[[r[k] for k in ('name','category','services','valid','applicable','improved','rate','coverage')]+[r['distribution'][x] for x in v.STATUS] for r in e['projects']])
            sheet('阶段复评',['月份','改善','稳定','加重','未复评','有效窗口数'],[[r[k] for k in ('month','improved','stable','worse','not_reviewed','n')] for r in e['stage_months']])
            sheet('检测项目',['项目','服务数','完成检测','有效报告','异常','已跟进'],[[r[k] for k in ('name','services','completed','valid_reports','abnormal','followed')] for r in e['screening_summary']])
            sheet('满意度',['评价','问卷数'],[[r['name'],r['count']] for r in s['distribution']])
            sheet('满意度分维度',['维度','有效回答数','平均分'],[[r['name'],r['valid'],r['score']] for r in s['dimensions']])
            sheet('未来需求',['需求','人数','有效答题人数','比例%'],[[r[k] for k in ('name','count','denominator','percent')] for r in s['needs']])
    buffer=BytesIO();book.save(buffer);book.close();buffer.seek(0)
    core.audit_log('导出 Excel','v2_report',context['kind'],'沿用页面同一统计函数')
    return send_file(buffer,as_attachment=True,download_name=context['title']+'.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@bp.post('/api/v2/admin/equipment')
def add_equipment():
    d=payload();code=v.project(d.get('project_code'));name=v.text(d.get('name'),100,True);asset=v.text(d.get('asset_code'),80,True)
    with closing(core.get_db()) as conn:
        if conn.execute('SELECT 1 FROM equipment WHERE name=?',(name,)).fetchone():raise ValueError('设备名称已存在，请使用不同资产编号对应的名称')
        if conn.execute('SELECT 1 FROM v2_equipment WHERE asset_code=?',(asset,)).fetchone():raise ValueError('资产编号已存在')
        eid=conn.execute("INSERT INTO equipment(name,type,model,location,status,description) VALUES (?,'专用设备',?,?,'available',?)",(name,v.text(d.get('model')),v.text(d.get('location')),PROJECT_BY_CODE[code]['name'])).lastrowid
        conn.execute('INSERT INTO v2_equipment VALUES (?,?,?,?,?)',(eid,code,asset,v.number(d.get('maintenance_days'),1,3650,integer=True),core.now_local_str()))
        conn.execute("INSERT INTO project_equipment_mapping(project_name,equipment_name,status) VALUES (?,?,'enabled')",(PROJECT_BY_CODE[code]['name'],name))
        conn.commit()
    core.audit_log('登记设备台账','v2_equipment',eid,code)
    return core.success_response({'id':eid},'设备已登记',201)


@bp.get('/api/v2/drilldown')
def drilldown():
    if not can_personal():return core.error_response('个人下钻需单独授权',403)
    f=a.filters(request.args);data=a.dataset();people=a.cohort(data,f);health=a.health(data,people,f)
    domain=v.choice(request.args.get('domain'),('diseases','symptoms'));label=v.text(request.args.get('label'),200,True)
    records=[{'id':p['id'],'name':p['name'],'age':p['current_age'],'gender':p['gender_group']} for p in people if label in health['_person_tags'][p['id']][domain]]
    core.audit_log('群体统计下钻','access',domain,'按授权查看关联档案')
    return core.success_response(records)
