from flask import Blueprint
from backend.core import *

bp = Blueprint('export', __name__)

@bp.route('/api/query-export/no-show-top10', methods=['GET'])
def api_query_export_no_show_top10():
    start_date = (request.args.get('start_date') or '').strip()
    end_date = (request.args.get('end_date') or '').strip()
    if start_date and not is_valid_date(start_date):
        return error_response('开始日期格式必须为 YYYY-MM-DD')
    if end_date and not is_valid_date(end_date):
        return error_response('结束日期格式必须为 YYYY-MM-DD')
    if start_date and end_date and start_date > end_date:
        return error_response('开始日期不能晚于结束日期')

    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT customer_name, SUM(no_show_count) AS no_show_count
        FROM (
            SELECT COALESCE(NULLIF(TRIM(c.name), ''), '未命名客户') AS customer_name,
                   COUNT(*) AS no_show_count
            FROM appointments a
            LEFT JOIN customers c ON c.id = a.customer_id
            WHERE LOWER(COALESCE(a.checkin_status, '')) = 'no_show'
              AND (? = '' OR a.appointment_date >= ?)
              AND (? = '' OR a.appointment_date <= ?)
            GROUP BY customer_name
            UNION ALL
            SELECT COALESCE(NULLIF(TRIM(c.name), ''), NULLIF(TRIM(h.customer_name), ''), '未命名客户') AS customer_name,
                   COUNT(*) AS no_show_count
            FROM home_appointments h
            LEFT JOIN customers c ON c.id = h.customer_id
            WHERE LOWER(COALESCE(h.checkin_status, '')) = 'no_show'
              AND (? = '' OR h.appointment_date >= ?)
              AND (? = '' OR h.appointment_date <= ?)
            GROUP BY customer_name
        ) merged
        GROUP BY customer_name
        ORDER BY no_show_count DESC, customer_name COLLATE NOCASE ASC
        LIMIT 10
        ''',
        (start_date, start_date, end_date, end_date, start_date, start_date, end_date, end_date),
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response({
        'items': [{'name': row.get('customer_name') or '-', 'count': int((row.get('no_show_count') or 0))} for row in rows],
        'start_date': start_date,
        'end_date': end_date,
    })


# ========== 仪表盘 ==========
@bp.route('/api/export/query-download', methods=['GET'])
def api_export_query_download():
    scope = (request.args.get('scope') or 'single').strip()
    dataset = (request.args.get('dataset') or 'all').strip()
    customer_id = request.args.get('customer_id')

    allowed_datasets = {'all', 'customers', 'health', 'appointments'}
    if scope not in {'single', 'all'}:
        return jsonify({'error': '下载范围参数不合法'}), 400
    if dataset not in allowed_datasets:
        return jsonify({'error': '下载内容参数不合法'}), 400
    if scope == 'single' and not customer_id:
        return jsonify({'error': '请选择客户后下载'}), 400

    conn = get_db()
    try:
        if scope == 'single':
            c = conn.cursor()
            c.execute('SELECT id, name FROM customers WHERE id=? AND is_deleted=0', (customer_id,))
            customer = c.fetchone()
            if not customer:
                return jsonify({'error': '客户不存在'}), 404
            customer_name = customer['name']
            name_prefix = f'single_{customer_name}_{customer_id}'
        else:
            name_prefix = 'all_customers'

        queries = {
            'customers': ('客户档案', 'SELECT * FROM customers {where_clause} ORDER BY created_at DESC'),
            'health': ('健康档案', '''SELECT h.*, c.name as customer_name, c.phone as customer_phone
                FROM health_assessments h JOIN customers c ON h.customer_id=c.id
                {where_clause} ORDER BY h.assessment_date DESC'''),
            'appointments': ('预约记录', '''SELECT a.*, c.name as customer_name, c.phone as customer_phone, e.name as equipment_name
                FROM appointments a JOIN customers c ON a.customer_id=c.id LEFT JOIN equipment e ON a.equipment_id=e.id
                {where_clause} ORDER BY a.appointment_date DESC, a.start_time DESC'''),
        }

        target_keys = list(queries.keys()) if dataset == 'all' else [dataset]
        ts = now_local().strftime('%Y%m%d_%H%M%S')
        fn = f'{name_prefix}_{dataset}_{ts}.xlsx'
        fp = os.path.join(UPLOAD_FOLDER, fn)

        with pd.ExcelWriter(fp, engine='openpyxl') as writer:
            _init_export_workbook(writer)
            for key in target_keys:
                sheet_name, sql_tpl = queries[key]
                if scope == 'single':
                    where_clause = 'WHERE c.id = ?' if key != 'customers' else 'WHERE id = ?'
                    df = pd.read_sql_query(sql_tpl.format(where_clause=where_clause), conn, params=(customer_id,))
                else:
                    where_clause = 'WHERE is_deleted=0' if key == 'customers' else ''
                    df = pd.read_sql_query(sql_tpl.format(where_clause=where_clause), conn)
                cols = EXPORT_COLUMNS_BY_KEY.get('customers' if key == 'customers' else key)
                _write_bilingual_dataframe(writer, sheet_name, df, cols)
    finally:
        conn.close()

    audit_log('导出数据', 'export', customer_id or 'all', f'scope={scope}, dataset={dataset}, file={fn}')
    return jsonify({'filename': fn, 'download_url': '/api/download/' + fn})


def _build_customer_integrated_filter(search_text):
    keyword = (search_text or '').strip()
    where_sql = 'WHERE 1=1'
    params = []
    conn = get_db()
    c = conn.cursor()
    c.execute('PRAGMA table_info(customers)')
    customer_cols = {row['name'] for row in c.fetchall()}
    conn.close()
    has_deleted_flag = 'is_deleted' in customer_cols
    if has_deleted_flag:
        where_sql += ' AND c.is_deleted=0'
    if keyword:
        where_sql += ' AND (c.name LIKE ? OR c.phone LIKE ?)'
        keyword_like = f'%{keyword}%'
        params.extend([keyword_like, keyword_like])
    return where_sql, params, has_deleted_flag


EXPORT_FIELD_ZH = {
    'id': 'ID',
    'name': '姓名',
    'id_card': '身份证号',
    'phone': '手机号',
    'address': '地址',
    'gender': '性别',
    'birth_date': '出生日期',
    'medical_history': '病史',
    'allergies': '过敏史',
    'created_at': '创建时间',
    'updated_at': '更新时间',
    'diet_habits': '饮食习惯',
    'chronic_diseases': '慢性疾病',
    'health_status': '健康状态',
    'therapy_contraindications': '理疗禁忌',
    'customer_id': '客户ID',
    'assessment_date': '评估日期',
    'assessor': '评估人',
    'age': '年龄',
    'height_cm': '身高(cm)',
    'weight_kg': '体重(kg)',
    'past_medical_history': '既往病史',
    'family_history': '家族病史',
    'allergy_history': '过敏历史',
    'allergy_details': '过敏详情',
    'smoking_status': '吸烟情况',
    'smoking_years': '吸烟年限',
    'cigarettes_per_day': '日均吸烟量',
    'drinking_status': '饮酒情况',
    'drinking_years': '饮酒年限',
    'fatigue_last_month': '近一个月疲劳',
    'sleep_quality': '睡眠质量',
    'sleep_hours': '睡眠时长',
    'blood_pressure_test': '血压检测',
    'blood_lipid_test': '血脂检测',
    'chronic_pain': '慢性疼痛',
    'pain_details': '疼痛详情',
    'exercise_methods': '锻炼方式',
    'weekly_exercise_freq': '每周锻炼频次',
    'health_needs': '健康需求',
    'notes': '备注',
    'customer_name': '客户姓名',
    'customer_phone': '客户手机号',
    'equipment_id': '设备ID',
    'equipment_name': '设备名称',
    'appointment_date': '预约日期',
    'start_time': '开始时间',
    'end_time': '结束时间',
    'status': '状态',
    'project_id': '项目ID',
    'project_name': '项目名称',
    'staff_id': '人员ID',
    'home_time': '上门时间',
    'home_address': '上门地址',
    'service_project': '服务项目',
    'staff_name': '服务人员',
    'location': '地点',
    'contact_person': '联系人',
    'contact_phone': '联系人电话',
    'has_companion': '是否有家属陪同',
    'service_time': '服务时间',
    'improvement_summary': '改善情况',
    'followup_time': '随访时间',
    'followup_method': '随访方式',
}

EXPORT_COLUMNS_BY_KEY = {
    'basic': ['id', 'name', 'id_card', 'phone', 'address', 'gender', 'birth_date', 'medical_history', 'allergies', 'created_at', 'updated_at', 'diet_habits', 'chronic_diseases', 'health_status', 'therapy_contraindications'],
    'health': ['id', 'customer_id', 'assessment_date', 'assessor', 'age', 'height_cm', 'weight_kg', 'address', 'past_medical_history', 'family_history', 'allergy_history', 'allergy_details', 'smoking_status', 'smoking_years', 'cigarettes_per_day', 'drinking_status', 'drinking_years', 'fatigue_last_month', 'sleep_quality', 'sleep_hours', 'blood_pressure_test', 'blood_lipid_test', 'chronic_pain', 'pain_details', 'exercise_methods', 'weekly_exercise_freq', 'health_needs', 'notes', 'created_at', 'customer_name', 'customer_phone'],
    'appointments': ['id', 'customer_id', 'equipment_id', 'appointment_date', 'start_time', 'end_time', 'status', 'has_companion', 'notes', 'created_at', 'project_id', 'staff_id', 'updated_at', 'customer_name', 'customer_phone', 'equipment_name', 'project_name'],
    'home_appointments': ['id', 'customer_id', 'project_id', 'staff_id', 'customer_name', 'phone', 'home_time', 'home_address', 'service_project', 'staff_name', 'appointment_date', 'start_time', 'end_time', 'location', 'contact_person', 'contact_phone', 'has_companion', 'notes', 'status', 'created_at', 'updated_at', 'project_name'],
    'improvement': ['id', 'customer_id', 'service_project', 'service_time', 'improvement_summary', 'followup_time', 'followup_method', 'notes', 'created_at', 'updated_at', 'customer_name', 'customer_phone'],
    'customers': ['id', 'name', 'id_card', 'phone', 'address', 'gender', 'birth_date', 'medical_history', 'allergies', 'created_at', 'updated_at', 'diet_habits', 'chronic_diseases', 'health_status', 'therapy_contraindications'],
}


def _write_bilingual_sheet(writer, sheet_name, rows=None, columns=None):
    data_rows = rows or []
    if columns is None:
        columns = list(data_rows[0].keys()) if data_rows else []
    else:
        merged_columns = list(columns)
        seen = set(merged_columns)
        for row in data_rows:
            for key in row.keys():
                if key not in seen:
                    merged_columns.append(key)
                    seen.add(key)
        columns = merged_columns
    ws = writer.book.create_sheet(title=sheet_name[:31])
    if not columns:
        return
    ws.append(columns)
    ws.append([EXPORT_FIELD_ZH.get(col, col) for col in columns])
    for row in data_rows:
        ws.append([row.get(col) for col in columns])


def _write_bilingual_dataframe(writer, sheet_name, df, columns=None):
    if columns:
        output_columns = list(columns) + [col for col in df.columns if col not in set(columns)]
    else:
        output_columns = list(df.columns)
    if output_columns:
        missing_cols = [col for col in output_columns if col not in df.columns]
        for col in missing_cols:
            df[col] = None
        df = df[output_columns]
    _write_bilingual_sheet(
        writer,
        sheet_name,
        rows=df.to_dict(orient='records'),
        columns=output_columns,
    )


def _init_export_workbook(writer):
    wb = writer.book
    if len(wb.sheetnames) == 1 and wb.sheetnames[0] == 'Sheet':
        std = wb['Sheet']
        wb.remove(std)


def _query_customer_integrated_dataset(cursor, dataset_key, where_sql, params, page, page_size, keyword='', customer_id=None, has_deleted_flag=False):
    offset = (page - 1) * page_size
    query_map = {
        'basic': {
            'count_sql': f'SELECT COUNT(*) as n FROM customers c {where_sql}',
            'data_sql': f'''
                SELECT c.*
                FROM customers c
                {where_sql}
                ORDER BY c.created_at DESC, c.id DESC
                LIMIT ? OFFSET ?
            ''',
        },
        'health': {
            'count_sql': f'''
                SELECT COUNT(*) as n
                FROM health_assessments h
                JOIN customers c ON h.customer_id=c.id
                {where_sql}
            ''',
            'data_sql': f'''
                SELECT h.*, c.name as customer_name, c.phone as customer_phone
                FROM health_assessments h
                JOIN customers c ON h.customer_id=c.id
                {where_sql}
                ORDER BY h.assessment_date DESC, h.id DESC
                LIMIT ? OFFSET ?
            ''',
        },
        'appointments': {
            'count_sql': f'''
                SELECT COUNT(*) as n
                FROM appointments a
                JOIN customers c ON a.customer_id=c.id
                {where_sql}
            ''',
            'data_sql': f'''
                SELECT a.*, c.name as customer_name, c.phone as customer_phone, e.name as equipment_name, p.name as project_name
                FROM appointments a
                JOIN customers c ON a.customer_id=c.id
                LEFT JOIN equipment e ON a.equipment_id=e.id
                LEFT JOIN therapy_projects p ON a.project_id=p.id
                {where_sql}
                ORDER BY a.appointment_date DESC, a.start_time DESC, a.id DESC
                LIMIT ? OFFSET ?
            ''',
        },
        'home_appointments': {
            'count_sql': '''
                SELECT COUNT(*) as n
                FROM home_appointments h
                LEFT JOIN customers c ON h.customer_id=c.id
                WHERE 1=1 {deleted_clause} {keyword_clause} {customer_clause}
            ''',
            'data_sql': '''
                SELECT
                    h.*,
                    COALESCE(h.customer_name, c.name) AS customer_name,
                    COALESCE(h.service_project, p.name) AS project_name,
                    COALESCE(h.staff_name, s.name) AS staff_name,
                    COALESCE(h.phone, c.phone) AS phone,
                    COALESCE(h.home_address, h.location) AS home_address
                FROM home_appointments h
                LEFT JOIN customers c ON h.customer_id=c.id
                LEFT JOIN therapy_projects p ON h.project_id=p.id
                LEFT JOIN staff s ON h.staff_id=s.id
                WHERE 1=1 {deleted_clause} {keyword_clause} {customer_clause}
                ORDER BY h.appointment_date DESC, h.start_time DESC, h.id DESC
                LIMIT ? OFFSET ?
            ''',
        },
        'improvement': {
            'count_sql': f'''
                SELECT COUNT(*) as n
                FROM service_improvement_records r
                JOIN customers c ON r.customer_id=c.id
                {where_sql}
            ''',
            'data_sql': f'''
                SELECT r.*, c.name as customer_name, c.phone as customer_phone
                FROM service_improvement_records r
                JOIN customers c ON r.customer_id=c.id
                {where_sql}
                ORDER BY r.service_time DESC, r.id DESC
                LIMIT ? OFFSET ?
            ''',
        },
    }
    conf = query_map[dataset_key]
    keyword = (keyword or '').strip()
    if dataset_key == 'home_appointments':
        keyword_clause = ' AND (c.name LIKE ? OR c.phone LIKE ?)' if keyword else ''
        customer_clause = ' AND h.customer_id=?' if customer_id else ''
        deleted_clause = ' AND c.is_deleted=0' if has_deleted_flag else ''
        home_params = []
        if keyword:
            home_params.extend([f'%{keyword}%', f'%{keyword}%'])
        if customer_id:
            home_params.append(customer_id)
        count_sql = conf['count_sql'].format(
            deleted_clause=deleted_clause,
            keyword_clause=keyword_clause,
            customer_clause=customer_clause
        )
        data_sql = conf['data_sql'].format(
            deleted_clause=deleted_clause,
            keyword_clause=keyword_clause,
            customer_clause=customer_clause
        )
        cursor.execute(count_sql, home_params)
        total = int(cursor.fetchone()['n'])
        cursor.execute(data_sql, home_params + [page_size, offset])
        rows = row_list(cursor.fetchall())
        return paginate_result(rows, total, page, page_size)

    if dataset_key == 'improvement' and not table_exists(cursor, 'service_improvement_records'):
        return paginate_result([], 0, page, page_size)

    count_sql = conf['count_sql']
    data_sql = conf['data_sql']
    cursor.execute(count_sql, params)
    total = int(cursor.fetchone()['n'])
    cursor.execute(data_sql, params + [page_size, offset])
    rows = row_list(cursor.fetchall())
    if dataset_key == 'basic':
        rows = [hydrate_customer_age(row) for row in rows]
    return paginate_result(rows, total, page, page_size)


@bp.route('/api/customers/integrated-view', methods=['GET'])
def api_customers_integrated_view():
    keyword = (request.args.get('search') or '').strip()
    section_keys = ['basic', 'health', 'appointments', 'home_appointments', 'improvement']
    conn = get_db()
    c = conn.cursor()
    where_sql, params, has_deleted_flag = _build_customer_integrated_filter(keyword)
    data = {'search': keyword}
    for key in section_keys:
        page = max(1, int(request.args.get(f'{key}_page', 1) or 1))
        page_size = min(max(int(request.args.get(f'{key}_page_size', 5) or 5), 1), 100)
        data[key] = _query_customer_integrated_dataset(
            c, key, where_sql, params, page, page_size, keyword=keyword, has_deleted_flag=has_deleted_flag
        )
    conn.close()
    return success_response(data)


@bp.route('/api/export/customer-integrated-form', methods=['GET'])
def api_export_customer_integrated_form():
    form_key = (request.args.get('form') or 'basic').strip()
    search = (request.args.get('search') or '').strip()
    limit = request.args.get('limit', type=int)
    if form_key not in {'basic', 'health', 'appointments', 'home_appointments', 'improvement'}:
        return error_response('表单类型不合法')
    conn = get_db()
    c = conn.cursor()
    where_sql, params, has_deleted_flag = _build_customer_integrated_filter(search)
    page_size = min(max(limit or 10000, 1), 10000)
    rows = _query_customer_integrated_dataset(
        c, form_key, where_sql, params, 1, page_size, keyword=search, has_deleted_flag=has_deleted_flag
    ).get('items') or []
    conn.close()
    fn = f'customer_{form_key}_{now_local().strftime("%Y%m%d_%H%M%S")}.xlsx'
    fp = os.path.join(UPLOAD_FOLDER, fn)
    with pd.ExcelWriter(fp, engine='openpyxl') as writer:
        _init_export_workbook(writer)
        _write_bilingual_sheet(writer, '数据导出', rows, EXPORT_COLUMNS_BY_KEY.get(form_key))
    return success_response({'filename': fn, 'download_url': '/api/download/' + fn})


@bp.route('/api/export/customer-integrated-all', methods=['GET'])
def api_export_customer_integrated_all():
    scope = (request.args.get('scope') or 'all').strip().lower()
    search = (request.args.get('search') or '').strip()
    if scope not in {'all', 'personal'}:
        return error_response('下载范围不合法')
    if scope == 'personal' and not search:
        return error_response('个人下载时请输入姓名或手机号')

    conn = get_db()
    c = conn.cursor()
    where_sql, params, has_deleted_flag = _build_customer_integrated_filter(search)
    selected_customer_id = None
    if scope == 'personal':
        c.execute(f'SELECT c.id FROM customers c {where_sql} ORDER BY c.id ASC LIMIT 1', params)
        selected = c.fetchone()
        if not selected:
            conn.close()
            return error_response('未找到对应客户')
        selected_customer_id = selected['id']
        where_sql = 'WHERE c.id=?'
        if has_deleted_flag:
            where_sql += ' AND c.is_deleted=0'
        params = [selected_customer_id]

    fn = f'customer_integrated_{scope}_{now_local().strftime("%Y%m%d_%H%M%S")}.xlsx'
    fp = os.path.join(UPLOAD_FOLDER, fn)
    with pd.ExcelWriter(fp, engine='openpyxl') as writer:
        _init_export_workbook(writer)
        for key, sheet_name in [
            ('basic', '基础信息'),
            ('health', '健康档案'),
            ('appointments', '预约服务记录'),
            ('home_appointments', '上门预约记录'),
            ('improvement', '健康改善记录'),
        ]:
            rows = _query_customer_integrated_dataset(
                c,
                key,
                where_sql,
                params,
                1,
                10000,
                keyword=search if scope == 'all' else '',
                customer_id=selected_customer_id,
                has_deleted_flag=has_deleted_flag,
            ).get('items') or []
            _write_bilingual_sheet(writer, sheet_name, rows, EXPORT_COLUMNS_BY_KEY.get(key))
    conn.close()
    return success_response({'filename': fn, 'download_url': '/api/download/' + fn})


@bp.route('/api/export/customers', methods=['GET'])
def api_export_customers():
    conn = get_db()
    df = pd.read_sql_query('SELECT * FROM customers WHERE is_deleted=0 ORDER BY created_at DESC', conn)
    conn.close()
    fn = 'customers_%s.xlsx' % now_local().strftime('%Y%m%d_%H%M%S')
    fp = os.path.join(UPLOAD_FOLDER, fn)
    with pd.ExcelWriter(fp, engine='openpyxl') as writer:
        _init_export_workbook(writer)
        _write_bilingual_dataframe(writer, '客户列表', df, EXPORT_COLUMNS_BY_KEY.get('customers'))
    audit_log('导出数据', 'export', 'customers', f'file={fn}')
    return jsonify({'filename': fn, 'download_url': '/api/download/' + fn})


@bp.route('/api/export/appointments', methods=['GET'])
def api_export_appointments():
    conn = get_db()
    df = pd.read_sql_query('''SELECT a.id, c.name as customer_name, c.phone, e.name as equipment_name, a.appointment_date, a.start_time, a.end_time, a.status, a.notes
        FROM appointments a JOIN customers c ON a.customer_id=c.id LEFT JOIN equipment e ON a.equipment_id=e.id ORDER BY a.appointment_date DESC''', conn)
    conn.close()
    fn = 'appointments_%s.xlsx' % now_local().strftime('%Y%m%d_%H%M%S')
    fp = os.path.join(UPLOAD_FOLDER, fn)
    with pd.ExcelWriter(fp, engine='openpyxl') as writer:
        _init_export_workbook(writer)
        _write_bilingual_dataframe(writer, '预约记录', df, list(df.columns))
    audit_log('导出数据', 'export', 'appointments', f'file={fn}')
    return jsonify({'filename': fn, 'download_url': '/api/download/' + fn})
