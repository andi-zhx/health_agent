"""Annual service overview. All ratios retain their observed denominators."""
from collections import Counter
from contextlib import closing
from datetime import date
from io import BytesIO
import re

from flask import Blueprint, jsonify, render_template, request, send_file
from openpyxl import Workbook
from backend.core import get_db, now_local, normalize_multi_text, error_response, success_response

bp = Blueprint('operations', __name__)
DEVICE_GROUPS = [
    ('艾灸机器人', ('艾灸机器人',)),
    ('高压氧舱', ('高压氧舱', '高压氧仓')),
    ('听力检测', ('听力检测', '听力检测仪', '听力测试')),
    ('按摩机器人', ('按摩机器人', '太空针灸按摩仪')),
]
DEFINITIONS = [
    ['建档人数', '统计截止日之前建立、当前未删除的客户档案；按客户去重。'],
    ['完成服务人次', '所选年度内状态为已完成的现场预约与上门预约之和，一条预约计一次。'],
    ['反馈覆盖率', '已完成服务中，有同一客户、同一预约关联反馈的服务数 ÷ 已完成服务数；重复反馈取最新一条。'],
    ['自述改善比例', '明显改善或部分改善的有效反馈数 ÷ 有效改善反馈数；未评估、取消及未完成预约的关联反馈不进入分母。'],
    ['健康分布', '截止日每人最新一份健康评估；疾病按档案明确填写的病史标签统计，可重复归类，不由检测值推断诊断。'],
    ['评分变化', '相同维度的体验前后困扰程度，0 为无困扰、10 为非常困扰；降低表示本人感觉改善，不代表临床疗效。'],
    ['待回访', '所选年度反馈中，状态为待回访且计划日期截至统计日已到期的记录；无计划日期单列待安排。'],
]


def ratio(numerator, denominator):
    return round(numerator * 100 / denominator, 1) if denominator else None


def project_group(name):
    for label, aliases in DEVICE_GROUPS:
        if name in aliases:
            return label
    return name or '未标注项目'


def select_year():
    raw = request.args.get('year', str(now_local().year))
    try:
        year = int(raw)
    except (ValueError, TypeError):
        raise ValueError('年度必须是整数')
    if not 2000 <= year <= now_local().year:
        raise ValueError('请选择 2000 年至当前年份之间的年度')
    return year


def fetch_services(conn, start, end):
    return [dict(row) for row in conn.execute('''
        SELECT 'appointments' AS service_type, a.id, a.customer_id, c.name AS customer_name,
               a.appointment_date, a.start_time, a.end_time, a.status, a.checkin_status,
               COALESCE(p.name, e.name, '') AS service_project
        FROM appointments a JOIN customers c ON c.id=a.customer_id
        LEFT JOIN therapy_projects p ON p.id=a.project_id LEFT JOIN equipment e ON e.id=a.equipment_id
        WHERE c.is_deleted=0 AND a.appointment_date BETWEEN ? AND ?
        UNION ALL
        SELECT 'home_appointments', h.id, h.customer_id, c.name, h.appointment_date,
               h.start_time, h.end_time, h.status, h.checkin_status, COALESCE(p.name, h.service_project, '')
        FROM home_appointments h JOIN customers c ON c.id=h.customer_id
        LEFT JOIN therapy_projects p ON p.id=h.project_id
        WHERE c.is_deleted=0 AND h.appointment_date BETWEEN ? AND ?
    ''', (start, end, start, end))]


def annual_snapshot(year):
    today = now_local().date()
    cutoff = min(date(year, 12, 31), today).isoformat()
    start = f'{year}-01-01'
    with closing(get_db()) as conn:
        settings = dict(conn.execute('SELECT setting_key, setting_value FROM system_settings').fetchall())
        customers = [dict(r) for r in conn.execute('SELECT * FROM customers WHERE is_deleted=0 AND (created_at IS NULL OR substr(created_at,1,10)<=?)', (cutoff,))]
        customer_ids = {c['id'] for c in customers}
        services = [s for s in fetch_services(conn, start, cutoff) if s['customer_id'] in customer_ids]
        completed = [s for s in services if s['status'] == 'completed']
        completed_keys = {(s['service_type'], s['id'], s['customer_id']) for s in completed}
        raw_feedback = [dict(r) for r in conn.execute('''SELECT r.*, c.name AS customer_name FROM service_improvement_records r
            JOIN customers c ON c.id=r.customer_id WHERE c.is_deleted=0 AND date(r.service_time) BETWEEN ? AND ?
            ORDER BY r.updated_at DESC, r.id DESC''', (start, cutoff))]
        feedback, seen = [], set()
        for row in raw_feedback:
            if row['customer_id'] not in customer_ids:
                continue
            service_type = {'appointment': 'appointments', 'home': 'home_appointments'}.get(row['service_type'], row['service_type'])
            row['service_type'] = service_type
            key = (service_type, row['service_id'], row['customer_id']) if row['service_id'] else ('manual', row['id'])
            if row['service_id'] and key not in completed_keys:
                continue
            if key in seen:
                continue
            seen.add(key)
            row['service_group'] = project_group(row['service_project'])
            # Historical annual reports use the status as of their cutoff date.
            if row['followup_status'] == '已回访' and (not row['followup_completed_at'] or row['followup_completed_at'][:10] > cutoff):
                row['followup_status'] = '待回访'
            feedback.append(row)
        linked = len(completed_keys & seen)
        assessments = {}
        for row in conn.execute('SELECT * FROM health_assessments WHERE assessment_date<=? ORDER BY assessment_date DESC, id DESC', (cutoff,)):
            if row['customer_id'] in customer_ids:
                assessments.setdefault(row['customer_id'], dict(row))
        equipment = [dict(r) for r in conn.execute('SELECT DISTINCT e.id,e.name,e.status,m.project_name FROM equipment e JOIN project_equipment_mapping m ON e.name=m.equipment_name WHERE m.status=\'enabled\'')]
        years = {today.year}
        for row in conn.execute("SELECT DISTINCT substr(appointment_date,1,4) FROM appointments UNION SELECT DISTINCT substr(appointment_date,1,4) FROM home_appointments"):
            if str(row[0]).isdigit() and 2000 <= int(row[0]) <= today.year:
                years.add(int(row[0]))

    valid_feedback = [r for r in feedback if r['improvement_status'] in ('明显改善', '部分改善', '无改善', '加重')]
    improved = sum(r['improvement_status'] in ('明显改善', '部分改善') for r in valid_feedback)
    ratings = [r['satisfaction_score'] for r in feedback if r['satisfaction_score'] is not None]
    paired = [r for r in feedback if r['before_score'] is not None and r['after_score'] is not None]
    adverse = [r for r in feedback if r['adverse_event'] == '有不适' or r['improvement_status'] == '加重']
    waiting = [r for r in feedback if r['followup_status'] == '待回访']
    due = [r for r in waiting if r['followup_date'] and r['followup_date'] <= cutoff]
    unscheduled = [r for r in waiting if not r['followup_date']]
    plans = [r for r in feedback if r['followup_status'] != '无需回访' and (r['followup_date'] or r['followup_completed_at'])]
    followed = [r for r in plans if r['followup_status'] == '已回访' and r['followup_completed_at'] and r['followup_completed_at'][:10] <= cutoff]
    device_cards = []
    for name, aliases in DEVICE_GROUPS:
        visits = [s for s in completed if s['service_type'] == 'appointments' and project_group(s['service_project']) == name]
        records = [r for r in valid_feedback if r['service_type'] == 'appointments' and r['service_group'] == name]
        units = {e['id']: e for e in equipment if e['project_name'] in aliases}
        gains = sum(r['improvement_status'] in ('明显改善', '部分改善') for r in records)
        device_cards.append({'name': name, 'services': len(visits), 'people': len({s['customer_id'] for s in visits}),
                             'feedback': len(records), 'improved': gains, 'improvement_rate': ratio(gains, len(records)),
                             'units': len(units), 'available': sum(e['status'] == 'available' for e in units.values())})
    months = []
    for month in range(1, 13):
        prefix = f'{year}-{month:02d}'
        visits = [s for s in completed if s['appointment_date'].startswith(prefix)]
        future = prefix > cutoff[:7]
        months.append({'month': month, 'services': None if future else len(visits),
                       'onsite': None if future else sum(s['service_type'] == 'appointments' for s in visits),
                       'home': None if future else sum(s['service_type'] == 'home_appointments' for s in visits)})

    diseases, needs, management = Counter(), Counter(), Counter()
    disease_recorded = 0
    health_signals = {key: {'label': label, 'observed': 0, 'abnormal': 0} for key, label in
                      [('blood_pressure_test', '血压记录'), ('blood_lipid_test', '血脂记录'), ('blood_sugar_test', '血糖记录')]}
    for customer in customers:
        record = assessments.get(customer['id'])
        if not record:
            management['未评估'] += 1
            continue
        text = str(record.get('past_medical_history') or '').strip()
        if text and text not in ('未记录', '不详', '未知'):
            disease_recorded += 1
        tags = {t.strip() for t in re.split(r'[、,，;；\n]', text) if t.strip() and t.strip() not in ('无', '无既往病史', '未记录', '不详', '未知')}
        diseases.update(tags)
        abnormal, monitored = 0, 0
        for key in health_signals:
            value = record.get(key) or ''
            if value in ('监测：正常', '监测：偏低', '监测：偏高', '正常', '偏低', '偏高'):
                health_signals[key]['observed'] += 1
                monitored += 1
                if '偏' in value:
                    health_signals[key]['abnormal'] += 1
                    abnormal += 1
        if len(tags) >= 2 or abnormal >= 2:
            management['重点关注'] += 1
        elif tags or abnormal or record.get('sleep_quality') in ('很差', '差'):
            management['常规随访'] += 1
        elif monitored == len(health_signals) and text in ('无', '无既往病史'):
            management['状态平稳'] += 1
        else:
            management['待补充'] += 1
        needs.update(set(normalize_multi_text(record.get('health_needs'))))
    disease_rows = [{'name': name, 'count': count, 'percent': ratio(count, disease_recorded)} for name, count in diseases.most_common(8)]
    recommendations = []
    def suggest(priority, title, evidence, action, target):
        recommendations.append({'priority': priority, 'title': title, 'evidence': evidence, 'action': action, 'target': target})
    if adverse:
        suggest('优先处理', '先完成异常体验复核', f'{len(adverse)} 条反馈记录了不适或加重。', '由健康专员核实感受与处理经过，必要时安排专业评估；记录复核结果。', 'outcomes')
    if due or unscheduled:
        suggest('本周推进', '把回访安排落实到人', f'{len(due)} 条回访已到期，另有 {len(unscheduled)} 条待安排日期。', '分配健康专员，补齐计划日期，回访后登记实际结果与完成时间。', 'outcomes')
    if len(completed) > linked:
        suggest('流程优化', '补齐服务后的体验记录', f'{len(completed)} 次已完成服务中，{len(completed)-linked} 次尚无关联反馈。', '将体验登记放在服务结束环节，优先补录待填写记录，再观察改善与满意度。', 'improvement-tracking')
    if disease_rows:
        top = disease_rows[0]
        suggest('服务组织', '围绕常见健康需求安排宣教', f'有病史记录的 {disease_recorded} 人中，{top["count"]} 人记录了“{top["name"]}”。', '据此安排专题宣教与档案复核，结合干部意愿组织随访，不根据疾病分布直接推荐设备治疗。', 'portrait')
    if completed:
        top = max(device_cards, key=lambda item: item['services'])
        if top['services']:
            suggest('排班参考', '结合热门服务检查排班', f'{top["name"]}完成 {top["services"]} 人次；当前配置可用设备 {top["available"]} 台。', '核对预约高峰、等待情况和人员配置后调整时段；仅凭使用次数不能判断设备利用率。', 'appointments')
    if not recommendations:
        suggest('从这里开始', '先建立完整的服务闭环', '当前年度尚无足够的服务和反馈记录。', '建立干部健康档案，完成预约签到、服务与体验登记，再查看运营建议。', 'health')
    total = len(customers)
    summary = {
        'customers': total, 'assessed': len(assessments), 'assessment_coverage': ratio(len(assessments), total),
        'services': len(completed), 'onsite': sum(s['service_type'] == 'appointments' for s in completed),
        'home': sum(s['service_type'] == 'home_appointments' for s in completed),
        'served_people': len({s['customer_id'] for s in completed}),
        'feedback': len(feedback), 'linked_feedback': linked, 'feedback_coverage': ratio(linked, len(completed)),
        'valid_feedback': len(valid_feedback), 'improved': improved, 'improvement_rate': ratio(improved, len(valid_feedback)),
        'satisfaction': round(sum(ratings)/len(ratings), 1) if ratings else None, 'rated': len(ratings),
        'paired_scores': len(paired), 'adverse': len(adverse), 'followup_due': len(due), 'followup_unscheduled': len(unscheduled),
        'followup_done': len(followed), 'followup_planned': len(plans),
    }
    demo = settings.get('demo_mode') == 'true'
    report_text = f'{year}年（截至{cutoff}），系统已建立{total}份服务对象档案，{len(assessments)}人完成健康评估；累计完成服务{len(completed)}人次，覆盖{summary["served_people"]}人，其中现场服务{summary["onsite"]}人次、上门服务{summary["home"]}人次。'
    report_text += f'共收集{len(valid_feedback)}条有效改善反馈，其中{improved}条为本人自述明显或部分改善。' if valid_feedback else '当前改善反馈不足，暂不评价改善成效。'
    if demo:
        report_text = '【虚构演示数据，仅用于系统功能展示】' + report_text
    return {'year': year, 'cutoff': cutoff, 'years': sorted(years | {year}, reverse=True), 'demo': demo,
            'unit_name': settings.get('unit_name', '军休所 · 静安所'), 'summary': summary, 'devices': device_cards,
            'months': months, 'diseases': disease_rows, 'disease_recorded': disease_recorded,
            'management': [{'name': name, 'count': management[name]} for name in ('状态平稳', '常规随访', '重点关注', '待补充', '未评估')],
            'health_signals': list(health_signals.values()), 'needs': [{'name': k, 'count': v} for k,v in needs.most_common(5)],
            'outcomes': [{'name': name, 'count': sum(r['improvement_status'] == name for r in valid_feedback)} for name in ('明显改善', '部分改善', '无改善', '加重')],
            'recommendations': recommendations[:5], 'report_text': report_text, 'definitions': DEFINITIONS,
            'feedback_rows': feedback}


@bp.route('/api/operations/overview')
def overview():
    try:
        data = annual_snapshot(select_year())
    except ValueError as error:
        return error_response(str(error))
    data.pop('feedback_rows')
    return success_response(data)


@bp.route('/api/operations/experiences')
def experiences():
    try:
        data = annual_snapshot(select_year())
    except ValueError as error:
        return error_response(str(error))
    rows = data['feedback_rows']
    query = (request.args.get('search') or '').strip().lower()
    project = request.args.get('project', '')
    state = request.args.get('state', '')
    if query:
        rows = [r for r in rows if query in str(r['customer_name']).lower()]
    if project:
        rows = [r for r in rows if r['service_group'] == project]
    if state == 'due':
        rows = [r for r in rows if r['followup_status'] == '待回访' and r['followup_date'] and r['followup_date'] <= data['cutoff']]
    elif state == 'adverse':
        rows = [r for r in rows if r['adverse_event'] == '有不适' or r['improvement_status'] == '加重']
    elif state == 'waiting':
        rows = [r for r in rows if r['followup_status'] == '待回访']
    elif state == 'done':
        rows = [r for r in rows if r['followup_status'] == '已回访']
    rows.sort(key=lambda r: (r['service_time'], r['id']), reverse=True)
    page = min(max(1, request.args.get('page', 1, type=int) or 1), max(1, (len(rows)+9)//10))
    return success_response({'items': rows[(page-1)*10:page*10], 'total': len(rows), 'page': page,
                             'pages': max(1, (len(rows)+9)//10), 'summary': data['summary'], 'demo': data['demo']})


@bp.route('/api/operations/report')
def report():
    try:
        data = annual_snapshot(select_year())
    except ValueError as error:
        return error_response(str(error))
    return render_template('annual_report.html', data=data)


@bp.route('/api/operations/export')
def export():
    try:
        data = annual_snapshot(select_year())
    except ValueError as error:
        return error_response(str(error))
    book = Workbook()
    sheet = book.active
    sheet.title = '年度概览'
    sheet.append(['数据性质', '虚构演示数据，仅供功能展示' if data['demo'] else '业务系统记录'])
    sheet.append(['统计截止', data['cutoff']])
    for key, label in [('customers','建档人数'),('assessed','已评估人数'),('services','完成服务人次'),('served_people','服务覆盖人数'),('linked_feedback','关联反馈服务数'),('valid_feedback','有效改善反馈数'),('improved','自述改善数'),('followup_due','到期待回访数')]:
        sheet.append([label, data['summary'][key]])
    for title, headers, rows in [
        ('月度服务',['月份','现场人次','上门人次','总人次'], [[r['month'],r['onsite'],r['home'],r['services']] for r in data['months']]),
        ('设备服务',['项目','完成人次','覆盖人数','反馈数','自述改善数'], [[r[k] for k in ('name','services','people','feedback','improved')] for r in data['devices']]),
        ('疾病分布',['病史标签','人数','占有病史记录人数百分比'], [[r['name'],r['count'],r['percent']] for r in data['diseases']]),
        ('体验反馈',['记录ID','客户ID','项目','服务时间','维度','体验前困扰','体验后困扰','改善自述','满意度','回访状态'], [[r[k] for k in ('id','customer_id','service_project','service_time','experience_dimension','before_score','after_score','improvement_status','satisfaction_score','followup_status')] for r in data['feedback_rows']]),
        ('统计口径',['指标','说明'], data['definitions']),
    ]:
        ws = book.create_sheet(title)
        ws.append(headers)
        for row in rows:
            # Treat exported text literally, including strings starting with '='.
            ws.append(row)
            for cell in ws[ws.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = 's'
    for ws in book:
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(55, max(16, max(len(str(c.value or '')) for c in col)+2))
    output = BytesIO()
    book.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f'health-annual-{data["year"]}{"-DEMO" if data["demo"] else ""}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
