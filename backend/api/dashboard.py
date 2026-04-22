from flask import Blueprint
from backend.core import *

bp = Blueprint('dashboard', __name__)

@bp.route('/api/dashboard/stats', methods=['GET'])
def api_dashboard_stats():
    conn = get_db()
    c = conn.cursor()
    today_str = now_local_date_str()
    c.execute("SELECT COUNT(*) as n FROM appointments WHERE status='completed'")
    completed_appointments = c.fetchone()['n']
    c.execute("SELECT COUNT(*) as n FROM home_appointments WHERE status='completed'")
    completed_home_appointments = c.fetchone()['n']
    cumulative_service_count = completed_appointments + completed_home_appointments

    c.execute('''
        SELECT ROUND(AVG(month_total), 1) as avg_count
        FROM (
            SELECT month_key, SUM(month_total) as month_total
            FROM (
                SELECT strftime('%Y-%m', appointment_date) as month_key, COUNT(*) as month_total
                FROM appointments
                WHERE status='completed'
                GROUP BY month_key
                UNION ALL
                SELECT strftime('%Y-%m', appointment_date) as month_key, COUNT(*) as month_total
                FROM home_appointments
                WHERE status='completed'
                GROUP BY month_key
            ) raw_monthly
            GROUP BY month_key
        ) monthly
    ''')
    month_avg_row = c.fetchone()
    monthly_avg_service_count = month_avg_row['avg_count'] if month_avg_row and month_avg_row['avg_count'] is not None else 0

    c.execute('''
        SELECT COUNT(*) as n
        FROM appointments
        WHERE appointment_date=?
          AND LOWER(COALESCE(status, ''))='completed'
    ''', (today_str,))
    today_checked_appointments = c.fetchone()['n']
    c.execute('''
        SELECT COUNT(*) as n
        FROM home_appointments
        WHERE appointment_date=?
          AND LOWER(COALESCE(status, ''))='completed'
    ''', (today_str,))
    today_checked_home_appointments = c.fetchone()['n']
    today_service_count = (today_checked_appointments or 0) + (today_checked_home_appointments or 0)
    c.execute('''
        SELECT
            SUM(CASE WHEN c.gender='男' THEN 1 ELSE 0 END) as male_service_count,
            SUM(CASE WHEN c.gender='女' THEN 1 ELSE 0 END) as female_service_count
        FROM (
            SELECT customer_id FROM appointments WHERE status='completed'
            UNION ALL
            SELECT customer_id FROM home_appointments WHERE status='completed'
        ) svc
        JOIN customers c ON c.id = svc.customer_id
        WHERE c.is_deleted=0
    ''')
    gender_row = c.fetchone()
    conn.close()
    return jsonify({
        'cumulative_service_count': cumulative_service_count,
        'male_service_count': int((gender_row['male_service_count'] if gender_row else 0) or 0),
        'female_service_count': int((gender_row['female_service_count'] if gender_row else 0) or 0),
        'monthly_avg_service_count': monthly_avg_service_count,
        'today_service_count': int(today_service_count),
    })


@bp.route('/api/dashboard/analytics', methods=['GET'])
def api_dashboard_analytics():
    conn = get_db()
    c = conn.cursor()
    equipment_start_date = (request.args.get('equipment_start_date') or '').strip()
    equipment_end_date = (request.args.get('equipment_end_date') or '').strip()

    # 最近 7 天预约趋势（包含 0 值日期）
    today = now_local().date()
    start_day = today - timedelta(days=6)
    c.execute('''
        SELECT appointment_date, SUM(n) as n
        FROM (
            SELECT appointment_date, COUNT(*) as n
            FROM appointments
            WHERE status <> 'cancelled' AND appointment_date BETWEEN ? AND ?
            GROUP BY appointment_date
            UNION ALL
            SELECT appointment_date, COUNT(*) as n
            FROM home_appointments
            WHERE status <> 'cancelled' AND appointment_date BETWEEN ? AND ?
            GROUP BY appointment_date
        ) merged
        GROUP BY appointment_date
        ORDER BY appointment_date
    ''', (
        start_day.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'),
        start_day.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')
    ))
    appt_map = {row['appointment_date']: row['n'] for row in c.fetchall()}
    appointment_trend = []
    for i in range(7):
        day = start_day + timedelta(days=i)
        key = day.strftime('%Y-%m-%d')
        appointment_trend.append({'date': key, 'count': appt_map.get(key, 0)})

    # 预约状态分布
    c.execute('''
        SELECT status, COUNT(*) as n
        FROM appointments
        GROUP BY status
        ORDER BY n DESC
    ''')
    appointment_status = row_list(c.fetchall())

    # 设备使用统计（按预约服务历史记录汇总总时长 + 次数）
    equipment_join_conditions = ["a.status = 'completed'"]
    equipment_params = []
    if equipment_start_date:
        equipment_join_conditions.append('a.appointment_date >= ?')
        equipment_params.append(equipment_start_date)
    if equipment_end_date:
        equipment_join_conditions.append('a.appointment_date <= ?')
        equipment_params.append(equipment_end_date)
    equipment_join_sql = ' AND '.join(equipment_join_conditions)
    if equipment_join_sql:
        equipment_join_sql = ' AND ' + equipment_join_sql
    c.execute(f'''
        SELECT project_category as equipment_name,
               SUM(usage_count) as usage_count,
               SUM(total_duration_minutes) as total_duration_minutes
        FROM (
            SELECT
                   CASE
                       WHEN COALESCE(TRIM(p.name), '') <> '' THEN TRIM(p.name)
                       WHEN COALESCE(TRIM(e.name), '') = '' THEN '未配置设备'
                       WHEN TRIM(e.name) GLOB '*[0-9][0-9]' THEN SUBSTR(TRIM(e.name), 1, LENGTH(TRIM(e.name)) - 2)
                       WHEN TRIM(e.name) GLOB '*[0-9]' THEN SUBSTR(TRIM(e.name), 1, LENGTH(TRIM(e.name)) - 1)
                       ELSE TRIM(e.name)
                   END as project_category,
                   COUNT(a.id) as usage_count,
                   COALESCE(SUM(
                       CASE
                           WHEN a.start_time IS NOT NULL AND a.end_time IS NOT NULL
                                AND a.end_time > a.start_time
                           THEN (strftime('%s', '2000-01-01 ' || a.end_time) - strftime('%s', '2000-01-01 ' || a.start_time)) / 60
                           ELSE 0
                       END
                   ), 0) as total_duration_minutes
            FROM appointments a
            LEFT JOIN equipment e ON e.id = a.equipment_id
            LEFT JOIN therapy_projects p ON p.id = a.project_id
            WHERE 1=1{equipment_join_sql}
            GROUP BY project_category
            UNION ALL
            SELECT COALESCE(NULLIF(TRIM(p.name), ''), NULLIF(TRIM(h.service_project), ''), '未配置设备') as project_category,
                   COUNT(h.id) as usage_count,
                   COALESCE(SUM(
                       CASE
                           WHEN h.start_time IS NOT NULL AND h.end_time IS NOT NULL
                                AND h.end_time > h.start_time
                           THEN (strftime('%s', '2000-01-01 ' || h.end_time) - strftime('%s', '2000-01-01 ' || h.start_time)) / 60
                           ELSE 0
                       END
                   ), 0) as total_duration_minutes
            FROM home_appointments h
            LEFT JOIN therapy_projects p ON p.id = h.project_id
            WHERE h.status = 'completed'
              AND (? = '' OR h.appointment_date >= ?)
              AND (? = '' OR h.appointment_date <= ?)
            GROUP BY project_category
        ) merged
        GROUP BY project_category
        ORDER BY usage_count DESC, total_duration_minutes DESC
        LIMIT 10
    ''', equipment_params + [equipment_start_date, equipment_start_date, equipment_end_date, equipment_end_date])
    equipment_usage_top = row_list(c.fetchall())

    # 客户活跃度：有预约或有健康档案的客户
    c.execute('''
        SELECT COUNT(DISTINCT customer_id) as n FROM (
            SELECT customer_id FROM appointments
            UNION ALL
            SELECT customer_id FROM health_assessments
        )
    ''')
    active_customers = c.fetchone()['n']
    c.execute('SELECT COUNT(*) as n FROM customers WHERE is_deleted=0')
    total_customers = c.fetchone()['n']

    conn.close()
    return jsonify({
        'appointment_trend': appointment_trend,
        'appointment_status': appointment_status,
        'equipment_usage_top': equipment_usage_top,
        'customer_activity': {
            'active_customers': active_customers,
            'total_customers': total_customers,
        }
    })


@bp.route('/api/dashboard/health-portrait', methods=['GET'])
def api_dashboard_health_portrait():
    conn = get_db()
    c = conn.cursor()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    if date_from and not is_valid_date(date_from):
        conn.close()
        return jsonify({'error': '开始日期格式必须为 YYYY-MM-DD'}), 400
    if date_to and not is_valid_date(date_to):
        conn.close()
        return jsonify({'error': '结束日期格式必须为 YYYY-MM-DD'}), 400
    if date_from and date_to and date_from > date_to:
        conn.close()
        return jsonify({'error': '开始日期不能晚于结束日期'}), 400

    records = build_health_portrait_sample_records(c, date_from=date_from, date_to=date_to)
    conn.close()

    age_segments = ['<50岁', '50-60岁', '61-65岁', '66-70岁', '71-75岁', '76-80岁', '>80岁']
    age_distribution = {k: 0 for k in age_segments}
    genders = {'男': 0, '女': 0, '未知': 0}
    age_gender_buckets = ['50-60岁', '60-70岁', '70-80岁', '80岁以上']
    age_gender_distribution = {
        '50-60岁': {'男': 0, '女': 0},
        '60-70岁': {'男': 0, '女': 0},
        '70-80岁': {'男': 0, '女': 0},
        '80岁以上': {'男': 0, '女': 0},
    }
    bmi_levels = {'偏瘦': 0, '正常': 0, '超重': 0, '肥胖': 0}
    risks = {'低风险': 0, '中风险': 0, '高风险': 0}
    high_risk_customers = []

    past_disease_counter = Counter()
    family_disease_counter = Counter()
    allergy_counter = Counter()
    pain_counter = Counter()
    recent_symptom_counter = Counter()
    behavior_tag_counter = Counter()
    exercise_counter = Counter()
    demand_counter = Counter()

    def build_ratio_payload(count, denominator, denominator_label='有效数据人数'):
        ratio = round((count * 100.0 / denominator), 1) if denominator else 0
        return {
            'count': count,
            'ratio': ratio,
            'denominator': denominator,
            'denominator_label': denominator_label,
        }

    def calc_missing_rate(valid_count, total_count):
        missing = max((total_count or 0) - (valid_count or 0), 0)
        rate = round((missing * 100.0 / total_count), 1) if total_count else 0
        return {'valid_count': valid_count, 'missing_count': missing, 'missing_rate': rate}

    smoking_people = 0
    drinking_people = 0
    smoking_drinking_people = 0
    sleep_abnormal_people = 0
    poor_sleep_people = 0
    family_history_people = 0
    allergy_people = 0
    chronic_pain_people = 0
    dual_history_high_risk_people = 0
    history_plus_bp_abnormal_people = 0
    low_exercise_bad_habit_people = 0
    bmi_abnormal = 0
    blood_pressure_abnormal_people = 0
    blood_lipid_abnormal_people = 0
    blood_sugar_abnormal_people = 0
    sleep_issue_people = 0
    valid_bmi_count = 0
    valid_bp_count = 0
    valid_blood_lipid_count = 0
    valid_blood_sugar_count = 0
    valid_sleep_count = 0


    for row in records:
        age = safe_int(row.get('age'))
        if age is None and row.get('birth_date'):
            try:
                birth = datetime.strptime(row.get('birth_date')[:10], '%Y-%m-%d').date()
                today = now_local().date()
                age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
            except Exception:
                age = None
        age_seg = classify_age_segment(age)
        if age_seg:
            age_distribution[age_seg] += 1

        gender = (row.get('gender') or '').strip()
        genders[gender if gender in ('男', '女') else '未知'] += 1
        if gender in ('男', '女') and age:
            if 50 <= age < 60:
                age_gender_distribution['50-60岁'][gender] += 1
            elif 60 <= age < 70:
                age_gender_distribution['60-70岁'][gender] += 1
            elif 70 <= age < 80:
                age_gender_distribution['70-80岁'][gender] += 1
            elif age >= 80:
                age_gender_distribution['80岁以上'][gender] += 1

        _, bmi_level = classify_bmi(row.get('height_cm'), row.get('weight_kg'))
        if bmi_level:
            valid_bmi_count += 1
            bmi_levels[bmi_level] += 1
            if bmi_level != '正常':
                bmi_abnormal += 1

        blood_pressure_test = str(row.get('blood_pressure_test') or '')
        blood_lipid_test = str(row.get('blood_lipid_test') or '')
        blood_sugar_test = str(row.get('blood_sugar_test') or '')
        sleep_hours_text = str(row.get('sleep_hours') or '')
        sleep_quality_text = str(row.get('sleep_quality') or '')

        bp_valid = blood_pressure_test in ('监测：正常', '监测：偏低', '监测：偏高')
        lipid_valid = blood_lipid_test in ('监测：正常', '监测：偏高')
        sugar_valid = blood_sugar_test in ('监测：正常', '监测：偏低', '监测：偏高')
        sleep_hours_valid = sleep_hours_text in ('<6小时', '6-8小时', '9-10小时', '>10小时')
        sleep_quality_valid = sleep_quality_text in ('很差', '差', '一般', '良好')
        sleep_valid = sleep_hours_valid or sleep_quality_valid

        if bp_valid:
            valid_bp_count += 1
        if lipid_valid:
            valid_blood_lipid_count += 1
        if sugar_valid:
            valid_blood_sugar_count += 1
        if sleep_valid:
            valid_sleep_count += 1

        bp_abnormal = ('偏高' in blood_pressure_test) or ('偏低' in blood_pressure_test)
        lipid_abnormal = '偏高' in blood_lipid_test
        sugar_abnormal = ('偏高' in blood_sugar_test) or ('偏低' in blood_sugar_test)
        sleep_hours_abnormal = sleep_hours_text in ('<6小时', '>10小时')
        sleep_quality_abnormal = sleep_quality_text in ('很差', '差')
        sleep_abnormal = sleep_quality_abnormal or sleep_hours_abnormal

        if bp_abnormal:
            blood_pressure_abnormal_people += 1
        if lipid_abnormal:
            blood_lipid_abnormal_people += 1
        if sugar_abnormal:
            blood_sugar_abnormal_people += 1
        if sleep_abnormal:
            sleep_issue_people += 1

        risk_info = calculate_lightweight_risk(row)
        risk_level = risk_info['risk_level']
        risks[risk_level] += 1
        if risk_level == '高风险':
            high_risk_customers.append({
                'customer_id': row.get('customer_id'),
                'customer_name': row.get('name') or row.get('customer_name') or '-',
                'age': risk_info.get('age'),
                'risk_level': risk_level,
                'risk_score': risk_info.get('risk_score', 0),
                'risk_reason_count': risk_info.get('risk_reason_count', 0),
                'risk_reasons': risk_info.get('risk_reasons', []),
                'recommended_intervention': risk_info.get('recommended_intervention', ''),
            })

        past_history_items = normalize_multi_text(row.get('past_medical_history'))
        family_history_items = normalize_multi_text(row.get('family_history'))
        allergy_items = normalize_multi_text(row.get('allergy_details'))
        pain_items = normalize_multi_text(row.get('pain_details'))
        recent_symptom_items = normalize_multi_text(row.get('recent_symptoms'))
        exercise_items = normalize_multi_text(row.get('exercise_methods'))
        demand_items = normalize_multi_text(row.get('health_needs'))

        for item in past_history_items:
            past_disease_counter[item] += 1
        for item in family_history_items:
            family_disease_counter[item] += 1
        for item in allergy_items:
            allergy_counter[item] += 1
        for item in pain_items:
            pain_counter[item] += 1
        for item in recent_symptom_items:
            recent_symptom_counter[item] += 1
        for item in exercise_items:
            exercise_counter[item] += 1
        for item in demand_items:
            demand_counter[item] += 1

        smoking = row.get('smoking_status') == '有'
        drinking = row.get('drinking_status') == '有'
        low_exercise = not exercise_items or any(item in ('无', '不运动', '很少运动', '偶尔运动') for item in exercise_items)
        poor_sleep = sleep_quality_abnormal
        has_past_history = bool(past_history_items)
        has_family_history = bool(family_history_items)

        if smoking:
            smoking_people += 1
            behavior_tag_counter['烟民'] += 1
        if drinking:
            drinking_people += 1
        if smoking and drinking:
            smoking_drinking_people += 1
        if sleep_abnormal:
            sleep_abnormal_people += 1
        if poor_sleep:
            poor_sleep_people += 1
            behavior_tag_counter['熬夜族'] += 1
        if low_exercise:
            behavior_tag_counter['久坐不动族'] += 1
        if has_family_history:
            family_history_people += 1
        if row.get('allergy_history') == '有' or allergy_items:
            allergy_people += 1
        if row.get('chronic_pain') == '有':
            chronic_pain_people += 1

        if has_family_history and has_past_history:
            dual_history_high_risk_people += 1
        if has_past_history and row.get('blood_pressure_test') == '监测：偏高':
            history_plus_bp_abnormal_people += 1
        if low_exercise and (smoking or drinking or poor_sleep):
            low_exercise_bad_habit_people += 1
        if bmi_level == '肥胖' and age and age >= 60:
            behavior_tag_counter['老年肥胖人群'] += 1
        if age and 50 <= age <= 60 and row.get('blood_pressure_test') == '监测：偏高':
            behavior_tag_counter['中年高血压风险人群'] += 1

    high_risk_customers.sort(
        key=lambda item: (
            -safe_int(item.get('risk_score') or 0),
            -safe_int(item.get('risk_reason_count') or 0),
            -safe_int(item.get('age') or 0),
            str(item.get('customer_name') or '')
        )
    )
    high_risk_top = high_risk_customers[:10]

    total = len(records)
    senior_count = age_distribution['66-70岁'] + age_distribution['71-75岁'] + age_distribution['76-80岁'] + age_distribution['>80岁']

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT r.service_project, r.service_content, r.improvement_status,
               a.status AS appointment_status, ha.status AS home_appointment_status
        FROM service_improvement_records r
        LEFT JOIN appointments a ON r.service_type='appointments' AND r.service_id=a.id
        LEFT JOIN home_appointments ha ON r.service_type='home_appointments' AND r.service_id=ha.id
    ''')
    improvement_rows = row_list(c.fetchall())

    heatmap = {}
    improvement_project_stats = {}
    status_order = ['无改善', '部分改善', '明显改善', '加重']
    for row in improvement_rows:
        appt_status = (row.get('appointment_status') or '').strip().lower()
        home_status = (row.get('home_appointment_status') or '').strip().lower()
        if appt_status == 'cancelled' or home_status == 'cancelled':
            continue
        project = (row.get('service_project') or '未标注项目').strip() or '未标注项目'
        content = (row.get('service_content') or '').strip()
        parts = normalize_multi_text(content) or ['未标注部位']
        status = (row.get('improvement_status') or '').strip()
        if status not in status_order:
            status = '无改善'
        project_bucket = improvement_project_stats.setdefault(
            project,
            {'total_services': 0, '明显改善': 0, '部分改善': 0, '无改善': 0, '加重': 0}
        )
        project_bucket['total_services'] += 1
        project_bucket[status] += 1
        project_bucket = heatmap.setdefault(project, {})
        for part in parts:
            part_name = part.strip() or '未标注部位'
            cell = project_bucket.setdefault(part_name, {'count': 0, 'statuses': {s: 0 for s in status_order}})
            cell['count'] += 1
            cell['statuses'][status] += 1

    heatmap_rows = []
    for project, cols in heatmap.items():
        for part, cell in cols.items():
            status_summary = ' / '.join([f'{k}{cell["statuses"].get(k, 0)}' for k in status_order if cell["statuses"].get(k, 0)])
            heatmap_rows.append({
                'service_project': project,
                'therapy_part': part,
                'count': cell['count'],
                'status_summary': status_summary or '无改善0',
            })

    improvement_project_ranking = []
    for project, stat in improvement_project_stats.items():
        total_services = safe_int(stat.get('total_services')) or 0
        obvious_improved_count = safe_int(stat.get('明显改善')) or 0
        partial_improved_count = safe_int(stat.get('部分改善')) or 0
        no_improved_count = safe_int(stat.get('无改善')) or 0
        worsen_count = safe_int(stat.get('加重')) or 0
        improvement_rate = ((obvious_improved_count + partial_improved_count) / total_services) if total_services else 0
        improvement_project_ranking.append({
            'service_project': project,
            'total_services': total_services,
            'obvious_improved_count': obvious_improved_count,
            'partial_improved_count': partial_improved_count,
            'no_improved_count': no_improved_count,
            'worsen_count': worsen_count,
            'improvement_rate': round(improvement_rate, 4),
            'improvement_rate_percent': round(improvement_rate * 100, 1),
        })
    improvement_project_ranking.sort(
        key=lambda item: (
            -float(item.get('improvement_rate') or 0),
            -safe_int(item.get('total_services') or 0),
            str(item.get('service_project') or '')
        )
    )

    archived_customer_ids = {safe_int(row.get('customer_id')) for row in records if safe_int(row.get('customer_id')) is not None}
    health_need_customer_ids = set()
    for row in records:
        customer_id = safe_int(row.get('customer_id'))
        if customer_id is None:
            continue
        need_items = normalize_multi_text(row.get('health_needs'))
        if need_items and not all(item == '无' for item in need_items):
            health_need_customer_ids.add(customer_id)
    health_need_customer_ids &= archived_customer_ids

    c.execute(
        '''
        SELECT DISTINCT customer_id
        FROM appointments
        WHERE LOWER(COALESCE(status, '')) <> 'cancelled'
        UNION
        SELECT DISTINCT customer_id
        FROM home_appointments
        WHERE LOWER(COALESCE(status, '')) <> 'cancelled'
        '''
    )
    booked_customer_ids = {safe_int(row['customer_id']) for row in c.fetchall() if safe_int(row['customer_id']) is not None}
    booked_customer_ids &= health_need_customer_ids

    c.execute(
        '''
        SELECT DISTINCT customer_id
        FROM appointments
        WHERE LOWER(COALESCE(checkin_status, ''))='checked_in'
        UNION
        SELECT DISTINCT customer_id
        FROM home_appointments
        WHERE LOWER(COALESCE(checkin_status, ''))='checked_in'
        '''
    )
    checked_in_customer_ids = {safe_int(row['customer_id']) for row in c.fetchall() if safe_int(row['customer_id']) is not None}
    checked_in_customer_ids &= booked_customer_ids

    c.execute('SELECT DISTINCT customer_id, improvement_status FROM service_improvement_records')
    improvement_customers = row_list(c.fetchall())
    filled_improvement_customer_ids = {
        safe_int(row.get('customer_id'))
        for row in improvement_customers
        if safe_int(row.get('customer_id')) is not None
    }
    filled_improvement_customer_ids &= checked_in_customer_ids

    improved_customer_ids = {
        safe_int(row.get('customer_id'))
        for row in improvement_customers
        if safe_int(row.get('customer_id')) is not None
        and str(row.get('improvement_status') or '').strip() in ('明显改善', '部分改善')
    }
    improved_customer_ids &= filled_improvement_customer_ids

    obvious_improved_customer_ids = {
        safe_int(row.get('customer_id'))
        for row in improvement_customers
        if safe_int(row.get('customer_id')) is not None
        and str(row.get('improvement_status') or '').strip() == '明显改善'
    }
    obvious_improved_customer_ids &= improved_customer_ids
    conn.close()

    return jsonify({
        'date_from': date_from,
        'date_to': date_to,
        'filter_applied': bool(date_from or date_to),
        'sampling_note': (
            f'统计口径：assessment_date 在 {date_from or "最早"} 至 {date_to or "最新"} 范围内，'
            '每位客户仅取该范围内最新一条健康评估。'
            if (date_from or date_to)
            else '统计口径：未设置时间范围，默认每位客户取全量数据中的最新一条健康评估。'
        ),
        'total_customers': total,
        'meta': {
            'sample_size': total,
            'total_customers': total,
            'valid_bmi_count': valid_bmi_count,
            'valid_bp_count': valid_bp_count,
            'valid_blood_lipid_count': valid_blood_lipid_count,
            'valid_blood_sugar_count': valid_blood_sugar_count,
            'valid_sleep_count': valid_sleep_count,
            'missing_rate_summary': {
                'bmi': calc_missing_rate(valid_bmi_count, total),
                'blood_pressure': calc_missing_rate(valid_bp_count, total),
                'blood_lipid': calc_missing_rate(valid_blood_lipid_count, total),
                'blood_sugar': calc_missing_rate(valid_blood_sugar_count, total),
                'sleep': calc_missing_rate(valid_sleep_count, total),
            },
            'indicator_caliber_note': '异常率口径统一为：异常人数 / 对应指标有效数据人数；缺失率口径为：1 - 有效数据人数 / 样本量。',
        },
        'abnormal_indicators': [
            {
                'name': '血压异常人数',
                **build_ratio_payload(blood_pressure_abnormal_people, valid_bp_count),
            },
            {
                'name': '血脂异常人数',
                **build_ratio_payload(blood_lipid_abnormal_people, valid_blood_lipid_count),
            },
            {
                'name': '血糖异常人数',
                **build_ratio_payload(blood_sugar_abnormal_people, valid_blood_sugar_count),
            },
            {
                'name': 'BMI异常人数',
                **build_ratio_payload(bmi_abnormal, valid_bmi_count),
            },
            {
                'name': '睡眠异常人数',
                **build_ratio_payload(sleep_issue_people, valid_sleep_count),
            },
        ],
        'dimension1': {
            'cards': {
                'total_people': total,
                'bmi_abnormal_rate': round((bmi_abnormal * 100.0 / valid_bmi_count), 1) if valid_bmi_count else 0,
                'bmi_abnormal_denominator': valid_bmi_count,
                'senior_ratio': round((senior_count * 100.0 / total), 1) if total else 0,
            },
            'gender_distribution': [{'name': k, 'count': v} for k, v in genders.items()],
            'age_distribution': [{'name': k, 'count': age_distribution[k]} for k in age_segments],
            'age_gender_distribution': [
                {
                    'name': bucket,
                    'male': age_gender_distribution[bucket]['男'],
                    'female': age_gender_distribution[bucket]['女'],
                } for bucket in age_gender_buckets
            ],
            'bmi_distribution': [{'name': k, 'count': v} for k, v in bmi_levels.items()],
        },
        'dimension2': {
            'risk_distribution': [{'name': k, 'count': v} for k, v in risks.items()],
            'past_disease_distribution': [{'name': k, 'count': v} for k, v in past_disease_counter.most_common()],
            'family_history_distribution': [{'name': k, 'count': v} for k, v in family_disease_counter.most_common()],
            'recent_symptom_distribution': [{'name': k, 'count': v} for k, v in recent_symptom_counter.most_common()],
            'allergy_top10': [{'name': k, 'count': v} for k, v in allergy_counter.most_common(10)],
            'pain_top10': [{'name': k, 'count': v} for k, v in pain_counter.most_common(10)],
            'family_history_ratio': round((family_history_people * 100.0 / total), 1) if total else 0,
            'allergy_ratio': round((allergy_people * 100.0 / total), 1) if total else 0,
            'chronic_pain_ratio': round((chronic_pain_people * 100.0 / total), 1) if total else 0,
            'dual_history_high_risk_people': dual_history_high_risk_people,
            'history_plus_bp_abnormal_people': history_plus_bp_abnormal_people,
        },
        'high_risk_summary': {
            'low': risks.get('低风险', 0),
            'medium': risks.get('中风险', 0),
            'high': risks.get('高风险', 0),
        },
        'high_risk_customers_top': high_risk_top,
        'dimension3': {
            'smoking_ratio': round((smoking_people * 100.0 / total), 1) if total else 0,
            'drinking_ratio': round((drinking_people * 100.0 / total), 1) if total else 0,
            'smoking_drinking_ratio': round((smoking_drinking_people * 100.0 / total), 1) if total else 0,
            'sleep_abnormal_ratio': round((sleep_abnormal_people * 100.0 / valid_sleep_count), 1) if valid_sleep_count else 0,
            'sleep_abnormal_denominator': valid_sleep_count,
            'poor_sleep_quality_ratio': round((poor_sleep_people * 100.0 / valid_sleep_count), 1) if valid_sleep_count else 0,
            'poor_sleep_quality_denominator': valid_sleep_count,
            'low_exercise_bad_habit_people': low_exercise_bad_habit_people,
            'exercise_top10': [{'name': k, 'count': v} for k, v in exercise_counter.most_common(10)],
            'health_needs_top10': [{'name': k, 'count': v} for k, v in demand_counter.most_common(10)],
            'fatigue_distribution': [],
            'behavior_tags': [{'name': k, 'count': v} for k, v in behavior_tag_counter.most_common(20)],
        },
        'dimension4': {
            'improvement_matrix': heatmap_rows,
            'improvement_project_ranking': improvement_project_ranking,
            'service_funnel': [
                {'key': 'archived', 'label': '已建档人数', 'count': len(archived_customer_ids)},
                {'key': 'health_needs', 'label': '有健康需求人数', 'count': len(health_need_customer_ids)},
                {'key': 'booked', 'label': '已预约人数', 'count': len(booked_customer_ids)},
                {'key': 'checked_in', 'label': '已签到人数', 'count': len(checked_in_customer_ids)},
                {'key': 'improvement_filled', 'label': '已填写改善记录人数', 'count': len(filled_improvement_customer_ids)},
                {'key': 'improved', 'label': '有改善人数', 'count': len(improved_customer_ids)},
                {'key': 'significant_improved', 'label': '明显改善人数', 'count': len(obvious_improved_customer_ids)},
            ],
        }
    })


@bp.route('/api/dashboard/health-portrait/trends', methods=['GET'])
def api_dashboard_health_portrait_trends():
    conn = get_db()
    c = conn.cursor()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    period = (request.args.get('period') or 'auto').strip().lower()
    if date_from and not is_valid_date(date_from):
        conn.close()
        return jsonify({'error': '开始日期格式必须为 YYYY-MM-DD'}), 400
    if date_to and not is_valid_date(date_to):
        conn.close()
        return jsonify({'error': '结束日期格式必须为 YYYY-MM-DD'}), 400
    if date_from and date_to and date_from > date_to:
        conn.close()
        return jsonify({'error': '开始日期不能晚于结束日期'}), 400
    if period not in ('auto', 'week', 'month'):
        conn.close()
        return jsonify({'error': 'period 仅支持 auto/week/month'}), 400

    result = build_health_portrait_trends(c, date_from=date_from, date_to=date_to, period=period)
    conn.close()
    return jsonify({
        'date_from': date_from,
        'date_to': date_to,
        'filter_applied': bool(date_from or date_to),
        **result,
    })


@bp.route('/api/dashboard/health-portrait/drilldown', methods=['GET'])
def api_dashboard_health_portrait_drilldown():
    conn = get_db()
    c = conn.cursor()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    metric = (request.args.get('metric') or '').strip()
    metric_value = (request.args.get('metric_value') or '').strip()
    if date_from and not is_valid_date(date_from):
        conn.close()
        return error_response('开始日期格式必须为 YYYY-MM-DD')
    if date_to and not is_valid_date(date_to):
        conn.close()
        return error_response('结束日期格式必须为 YYYY-MM-DD')
    if date_from and date_to and date_from > date_to:
        conn.close()
        return error_response('开始日期不能晚于结束日期')
    if metric not in {
        'blood_pressure_abnormal', 'blood_lipid_abnormal', 'blood_sugar_abnormal',
        'bmi_abnormal', 'sleep_abnormal', 'high_risk',
        'age_group', 'health_need_tag', 'past_history_tag'
    }:
        conn.close()
        return error_response('metric 参数不合法')

    page, page_size, _ = parse_list_params(default_page_size=10, max_page_size=100)
    records = build_health_portrait_sample_records(c, date_from=date_from, date_to=date_to)
    conn.close()

    detail_rows = []
    for row in records:
        age = safe_int(row.get('age'))
        if age is None and row.get('birth_date'):
            try:
                birth = datetime.strptime(row.get('birth_date')[:10], '%Y-%m-%d').date()
                today = now_local().date()
                age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
            except Exception:
                age = None
        age_segment = classify_age_segment(age) or ''
        _, bmi_level = classify_bmi(row.get('height_cm'), row.get('weight_kg'))
        bp_abnormal = ('偏高' in str(row.get('blood_pressure_test') or '')) or ('偏低' in str(row.get('blood_pressure_test') or ''))
        lipid_abnormal = '偏高' in str(row.get('blood_lipid_test') or '')
        sugar_abnormal = ('偏高' in str(row.get('blood_sugar_test') or '')) or ('偏低' in str(row.get('blood_sugar_test') or ''))
        sleep_hours_abnormal = str(row.get('sleep_hours') or '') in ('<6小时', '>10小时')
        sleep_quality_abnormal = str(row.get('sleep_quality') or '') in ('很差', '差')
        sleep_abnormal = sleep_hours_abnormal or sleep_quality_abnormal
        risk_info = calculate_lightweight_risk(row)
        health_need_items = normalize_multi_text(row.get('health_needs'))
        past_history_items = normalize_multi_text(row.get('past_medical_history'))

        matched = False
        if metric == 'blood_pressure_abnormal':
            matched = bp_abnormal
        elif metric == 'blood_lipid_abnormal':
            matched = lipid_abnormal
        elif metric == 'blood_sugar_abnormal':
            matched = sugar_abnormal
        elif metric == 'bmi_abnormal':
            matched = bmi_level not in ('', '正常')
        elif metric == 'sleep_abnormal':
            matched = sleep_abnormal
        elif metric == 'high_risk':
            matched = risk_info.get('risk_level') == '高风险'
        elif metric == 'age_group':
            matched = bool(metric_value) and (age_segment == metric_value)
        elif metric == 'health_need_tag':
            matched = bool(metric_value) and metric_value in health_need_items
        elif metric == 'past_history_tag':
            matched = bool(metric_value) and metric_value in past_history_items
        if not matched:
            continue
        detail_rows.append({
            'customer_id': row.get('customer_id'),
            'customer_name': row.get('customer_name') or '-',
            'gender': row.get('gender') or '未知',
            'age': age,
            'phone': row.get('phone') or '',
            'risk_level': risk_info.get('risk_level'),
            'risk_reasons': risk_info.get('risk_reasons') or [],
            'latest_assessment_date': row.get('latest_assessment_date') or '',
        })

    detail_rows.sort(
        key=lambda item: (
            -safe_int(item.get('age') or 0),
            str(item.get('customer_name') or ''),
            safe_int(item.get('customer_id') or 0),
        )
    )
    total = len(detail_rows)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = detail_rows[start:end]
    return success_response({
        'metric': metric,
        'metric_value': metric_value,
        'date_from': date_from,
        'date_to': date_to,
        **paginate_result(page_items, total, page, page_size)
    })


# ========== 导出与下载 ==========
