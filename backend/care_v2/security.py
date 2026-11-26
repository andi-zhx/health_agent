from contextlib import closing
import re
from flask import request, session, g
from werkzeug.security import check_password_hash
from backend import core
from .schema import PROJECTS

ROLES={'admin':'系统管理员','manager':'管理人员','operator':'驻场人员','professional':'专业人员','resident':'干部个人端'}


def actor():
    if hasattr(g,'care_actor'):
        return g.care_actor
    if not session.get('logged_in'):
        return None
    username=session.get('username','')
    if username==core.get_setting_value('login_username','admin'):
        person={'username':username,'role':'admin','customer_id':None,'can_view_personal':True,'can_export':True}
    else:
        with closing(core.get_db()) as conn:
            row=conn.execute('SELECT username,role,customer_id,can_view_personal,can_export FROM v2_accounts WHERE username=? AND active=1',(username,)).fetchone()
        person=dict(row) if row else None
    g.care_actor=person
    return person


def can_personal(customer_id=None):
    user=actor()
    return bool(user and user['can_view_personal'] and (user['role']!='resident' or user['customer_id']==customer_id))


def authorize_person(customer_id,export=False):
    user=actor()
    if not can_personal(customer_id) or (export and not user['can_export']):
        return core.error_response('未获授权查看或导出该个人档案',403,'FORBIDDEN')
    core.audit_log('导出个人档案' if export else '查看个人档案','customers',customer_id,'V2 授权访问')
    return None


def login_account(username,password):
    with closing(core.get_db()) as conn:
        row=conn.execute('SELECT * FROM v2_accounts WHERE username=? AND active=1',(username,)).fetchone()
    return bool(row and check_password_hash(row['password_hash'],password))


def guard():
    path=request.path
    if not path.startswith('/api/') or path in ('/api/health','/api/auth/login','/api/auth/session'):
        return None
    user=actor()
    if not user:
        session.clear()
        return core.error_response('请登录有效账号',401,'UNAUTHORIZED')
    if path=='/api/auth/logout':
        return None
    is_write=request.method not in ('GET','HEAD','OPTIONS')
    if '/export' in path or '/download/' in path:
        if not user['can_export']:
            return core.error_response('当前账号未获导出授权',403,'FORBIDDEN')
        if not path.startswith('/api/v2/') and (user['role']!='admin' or not user['can_view_personal']):
            return core.error_response('请使用 V2 授权导出入口',403,'FORBIDDEN')
    if user['role']=='resident':
        allowed=path.startswith('/api/v2/personal/') or path in ('/api/v2/meta','/api/v2/people','/api/v2/report','/api/v2/export')
        if is_write or not allowed:
            return core.error_response('个人端仅可查看本人获授权档案',403,'FORBIDDEN')
    elif path.startswith('/api/v2/admin/') or path.startswith('/api/system/'):
        if user['role']!='admin':
            return core.error_response('需要系统管理员权限',403,'FORBIDDEN')
    elif path.startswith('/api/v2/'):
        if is_write:
            if path.startswith(('/api/v2/risks','/api/v2/measurements')) and user['role'] not in ('admin','professional'):
                return core.error_response('健康判断及指标录入需要专业人员权限',403,'FORBIDDEN')
            if user['role'] not in ('admin','operator','professional'):
                return core.error_response('当前角色没有业务录入权限',403,'FORBIDDEN')
            if not user['can_view_personal'] and path.startswith(('/api/v2/services','/api/v2/reviews','/api/v2/screenings','/api/v2/surveys','/api/v2/risks','/api/v2/measurements')):
                return core.error_response('未获个人记录操作授权',403,'FORBIDDEN')
    elif user['role']!='admin':
        allowed=('/api/customers','/api/health-assessments','/api/health-records','/api/appointments','/api/home-appointments','/api/improvement-records','/api/projects','/api/service-projects','/api/equipment','/api/staff','/api/visit-checkins')
        if user['role']=='manager' or not user['can_view_personal'] or not path.startswith(allowed):
            return core.error_response('当前角色无权访问该业务数据',403,'FORBIDDEN')
        if is_write and (path.startswith(('/api/projects','/api/service-projects','/api/equipment','/api/staff')) or (path.startswith(('/api/health-assessments','/api/health-records')) and user['role']!='professional')):
            return core.error_response('当前角色无权修改该数据',403,'FORBIDDEN')
    # Enforce the catalog even for old forms/API clients; archived history remains readable.
    if not path.startswith('/api/v2/'):
        data=(request.get_json(silent=True) or {}) if is_write else request.args
        catalog_id=re.fullmatch(r'/api/(?:projects|service-projects)/(\d+)',path)
        if is_write and catalog_id:
            with closing(core.get_db()) as conn:
                original=conn.execute('SELECT name FROM v2_projects WHERE project_id=?',(int(catalog_id[1]),)).fetchone()
            if not original or request.method=='DELETE' or data.get('name',original[0])!=original[0] or data.get('status','enabled')!='enabled':
                return core.error_response('六项正式项目名称和状态由白名单维护；历史项目只读归档')
        if 'project_id' in data and data['project_id'] not in (None,''):
            with closing(core.get_db()) as conn:
                valid=conn.execute('SELECT 1 FROM v2_projects WHERE project_id=?',(data['project_id'],)).fetchone()
            if not valid:
                return core.error_response('该项目已归档或待核验，请选择六项正式项目')
        name=data.get('project_name') or data.get('service_project')
        if is_write and name and name not in {p[1] for p in PROJECTS}:
            return core.error_response('仅支持六项正式设备项目；非设备上门请使用快速登记')
        if is_write and path in ('/api/projects','/api/service-projects') and data.get('name') not in {p[1] for p in PROJECTS}:
            return core.error_response('正式项目限定为六项，不能新增白名单外项目')
    if path.startswith('/api/customers/') and request.method=='GET':
        core.audit_log('读取个人业务数据','access',path,'已授权')
    return None


def filter_catalog_response(response):
    path=request.path
    catalog_paths=('/api/projects','/api/service-projects','/api/equipment','/api/device-management/','/api/appointments/available-options')
    if not path.startswith(catalog_paths) or request.method!='GET' or response.status_code!=200 or not response.is_json:return response
    from flask import jsonify
    body=response.get_json();wrapped=isinstance(body,dict) and body.get('success') is True
    content=body.get('data') if wrapped else body
    with closing(core.get_db()) as conn:
        pids={r[0] for r in conn.execute('SELECT project_id FROM v2_projects')}
        eids={r[0] for r in conn.execute('SELECT equipment_id FROM v2_equipment')}
        available_ids={r[0] for r in conn.execute("SELECT e.id FROM equipment e JOIN v2_equipment v ON v.equipment_id=e.id WHERE e.status='available'")}
        if path=='/api/appointments/available-options':
            eids={r[0] for r in conn.execute('SELECT e.equipment_id FROM v2_equipment e JOIN v2_projects p ON p.code=e.project_code WHERE p.project_id=?',(request.args.get('project_id'),))}
    if isinstance(content,list):
        if path.startswith(('/api/projects','/api/service-projects')):content=[r for r in content if r.get('id') in pids]
        elif path.startswith('/api/equipment'):content=[r for r in content if r.get('id') in eids]
        else:content=[r for r in content if r.get('project_name') in {p[1] for p in PROJECTS}]
    elif isinstance(content,dict) and 'available_equipment' in content:
        content['available_equipment']=[r for r in content['available_equipment'] if r.get('id') in eids]
        if path=='/api/equipment/availability-summary':
            content['total_equipment']=len(available_ids)
            content['available_count']=len(content['available_equipment'])
            content['booked_count']=content['total_equipment']-content['available_count']
    if wrapped:body['data']=content
    else:body=content
    return jsonify(body)
