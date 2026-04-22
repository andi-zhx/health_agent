from flask import Blueprint
from backend.core import *

bp = Blueprint('health_assessments', __name__)

@bp.route('/api/health-assessments', methods=['GET'])
def api_health_assessments_list():
    customer_id = request.args.get('customer_id', type=int)
    search = (request.args.get('search', '') or '').strip()
    date_from = (request.args.get('date_from', '') or '').strip()
    date_to = (request.args.get('date_to', '') or '').strip()
    sort_by = (request.args.get('sort_by', '') or 'date_desc').strip()
    page, page_size, offset = parse_list_params()
    sort_map = {
        'date_desc': 'h.assessment_date DESC, h.id DESC',
        'date_asc': 'h.assessment_date ASC, h.id ASC',
        'name_asc': 'c.name COLLATE NOCASE ASC, h.assessment_date DESC, h.id DESC',
    }
    order_sql = sort_map.get(sort_by, sort_map['date_desc'])
    conn = get_db()
    c = conn.cursor()
    sql = 'FROM health_assessments h JOIN customers c ON h.customer_id=c.id WHERE 1=1'
    params = []
    if customer_id:
        sql += ' AND h.customer_id=?'
        params.append(customer_id)
    if search:
        sql += ' AND (c.name LIKE ? OR c.phone LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    if date_from:
        sql += ' AND date(h.assessment_date) >= date(?)'
        params.append(date_from)
    if date_to:
        sql += ' AND date(h.assessment_date) <= date(?)'
        params.append(date_to)
    c.execute(f'SELECT COUNT(*) as n {sql}', params)
    total = c.fetchone()['n']
    c.execute(f'SELECT h.*, c.name as customer_name {sql} ORDER BY {order_sql} LIMIT ? OFFSET ?', params + [page_size, offset])
    rows = row_list(c.fetchall())
    conn.close()
    for r in rows:
        r['exercise_methods'] = decode_multi_value(r.get('exercise_methods'))
        r['health_needs'] = decode_multi_value(r.get('health_needs'))
    return success_response(paginate_result(rows, total, page, page_size))


@bp.route('/api/health-assessments', methods=['POST'])
def api_health_assessment_create():
    d = request.json or {}
    invalid_msg = validate_health_assessment_enums(d)
    if invalid_msg:
        return jsonify({'error': invalid_msg}), 400
    conn = get_db()
    c = conn.cursor()
    customer_id = d.get('customer_id')

    c.execute('''
        INSERT INTO health_assessments (customer_id, assessment_date, assessor, age, height_cm, weight_kg, address, past_medical_history, family_history,
         allergy_history, allergy_details, smoking_status, smoking_years, cigarettes_per_day, drinking_status, drinking_years,
         sleep_quality, sleep_hours, recent_symptoms, recent_symptom_detail, life_impact_issues, blood_pressure_test, blood_lipid_test, blood_sugar_test, chronic_pain, pain_details,
         exercise_methods, health_needs, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        customer_id, d.get('assessment_date'), d.get('assessor'), d.get('age'), d.get('height_cm'), d.get('weight_kg'),
        d.get('address'), d.get('past_medical_history'), d.get('family_history'), d.get('allergy_history'), d.get('allergy_details'),
        d.get('smoking_status'), d.get('smoking_years'), d.get('cigarettes_per_day'), d.get('drinking_status'), d.get('drinking_years'),
        d.get('sleep_quality'), d.get('sleep_hours'), d.get('recent_symptoms'), d.get('recent_symptom_detail'), d.get('life_impact_issues'),
        d.get('blood_pressure_test'), d.get('blood_lipid_test'), d.get('blood_sugar_test'), d.get('chronic_pain'), d.get('pain_details'),
        parse_multi_value(d.get('exercise_methods')), parse_multi_value(d.get('health_needs')), d.get('notes')
    ))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    audit_log('创建健康评估', 'health_assessments', rid, f"customer_id={customer_id}")
    return jsonify({'id': rid, 'message': '健康评估已添加'}), 201


@bp.route('/api/health-assessments/<int:hid>', methods=['GET'])
def api_health_assessment_get(hid):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT
            h.*,
            c.name as customer_name,
            c.phone as phone,
            c.id_card as id_card,
            c.gender as gender,
            c.birth_date as birth_date,
            c.identity_type as identity_type,
            c.military_rank as military_rank,
            c.record_creator as record_creator
        FROM health_assessments h
        JOIN customers c ON h.customer_id=c.id
        WHERE h.id=?
        ''',
        (hid,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return jsonify({'error': '记录不存在'}), 404
    data = dict(row)
    data['exercise_methods'] = decode_multi_value(data.get('exercise_methods'))
    data['health_needs'] = decode_multi_value(data.get('health_needs'))
    return jsonify(data)


@bp.route('/api/health-assessments/<int:hid>', methods=['PUT'])
def api_health_assessment_update(hid):
    d = request.json or {}
    invalid_msg = validate_health_assessment_enums(d)
    if invalid_msg:
        return jsonify({'error': invalid_msg}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE health_assessments
        SET customer_id=?, assessment_date=?, assessor=?, age=?, height_cm=?, weight_kg=?, address=?, past_medical_history=?, family_history=?,
            allergy_history=?, allergy_details=?, smoking_status=?, smoking_years=?, cigarettes_per_day=?, drinking_status=?, drinking_years=?,
            sleep_quality=?, sleep_hours=?, recent_symptoms=?, recent_symptom_detail=?, life_impact_issues=?, blood_pressure_test=?, blood_lipid_test=?,
            blood_sugar_test=?, chronic_pain=?, pain_details=?, exercise_methods=?, health_needs=?, notes=?
        WHERE id=?
    ''', (
        d.get('customer_id'), d.get('assessment_date'), d.get('assessor'), d.get('age'), d.get('height_cm'), d.get('weight_kg'),
        d.get('address'), d.get('past_medical_history'), d.get('family_history'), d.get('allergy_history'), d.get('allergy_details'),
        d.get('smoking_status'), d.get('smoking_years'), d.get('cigarettes_per_day'), d.get('drinking_status'), d.get('drinking_years'),
        d.get('sleep_quality'), d.get('sleep_hours'), d.get('recent_symptoms'), d.get('recent_symptom_detail'), d.get('life_impact_issues'),
        d.get('blood_pressure_test'), d.get('blood_lipid_test'), d.get('blood_sugar_test'), d.get('chronic_pain'), d.get('pain_details'),
        parse_multi_value(d.get('exercise_methods')), parse_multi_value(d.get('health_needs')), d.get('notes'), hid
    ))
    conn.commit()
    conn.close()
    audit_log('修改健康评估', 'health_assessments', hid, f"customer_id={d.get('customer_id')}")
    return jsonify({'message': '健康评估更新成功'})


@bp.route('/api/health-assessments/<int:hid>', methods=['DELETE'])
def api_health_assessment_delete(hid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT customer_id FROM health_assessments WHERE id=?', (hid,))
    row = c.fetchone()
    c.execute('DELETE FROM health_assessments WHERE id=?', (hid,))
    conn.commit()
    conn.close()
    customer_id = row['customer_id'] if row else ''
    audit_log('删除健康评估', 'health_assessments', hid, f"customer_id={customer_id}")
    return jsonify({'message': '已删除'})


# ========== 健康改善追踪 ==========
