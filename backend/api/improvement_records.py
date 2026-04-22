from flask import Blueprint
from backend.core import *

bp = Blueprint('improvement_records', __name__)

@bp.route('/api/improvement-records/meta', methods=['GET'])
def api_improvement_records_meta():
    conn = get_db()
    c = conn.cursor()
    projects = get_improvement_service_projects(c)
    conn.close()
    return success_response({
        'service_projects': projects,
        'service_type_options': list(IMPROVEMENT_SERVICE_TYPE_OPTIONS),
        'improvement_status_options': IMPROVEMENT_STATUS_OPTIONS,
        'followup_method_options': FOLLOWUP_METHOD_OPTIONS,
        'followup_time_options': FOLLOWUP_PRESET_OPTIONS,
    })


@bp.route('/api/improvement-records', methods=['GET'])
def api_improvement_records_by_customer():
    customer_id = request.args.get('customer_id', type=int)
    if not customer_id:
        return error_response('customer_id 必填')
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT r.*, c.name as customer_name
        FROM service_improvement_records r
        JOIN customers c ON r.customer_id=c.id
        WHERE r.customer_id=?
        ORDER BY r.service_time DESC, r.id DESC
        ''',
        (customer_id,),
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(rows)


@bp.route('/api/improvement-records/all', methods=['GET'])
def api_improvement_records_all():
    page, page_size, offset = parse_list_params(default_page_size=10, max_page_size=100)
    conn = get_db()
    c = conn.cursor()
    sql = '''
        FROM service_improvement_records r
        JOIN customers c ON r.customer_id=c.id
        WHERE 1=1
    '''
    params = []
    customer_keyword = (request.args.get('customer_keyword') or request.args.get('customer_name') or '').strip()
    service_project = (request.args.get('service_project') or '').strip()
    improvement_status = (request.args.get('improvement_status') or '').strip()
    service_start = (request.args.get('service_start') or '').strip()
    service_end = (request.args.get('service_end') or '').strip()
    customer_id = request.args.get('customer_id', type=int)

    if customer_id:
        sql += ' AND r.customer_id=?'
        params.append(customer_id)
    if customer_keyword:
        sql += ' AND (c.name LIKE ? OR c.phone LIKE ?)'
        keyword_like = f'%{customer_keyword}%'
        params.extend([keyword_like, keyword_like])
    if service_project:
        sql += ' AND r.service_project=?'
        params.append(service_project)
    if improvement_status:
        sql += ' AND r.improvement_status=?'
        params.append(improvement_status)
    if service_start:
        sql += ' AND date(substr(r.service_time, 1, 10)) >= date(?)'
        params.append(service_start)
    if service_end:
        sql += ' AND date(substr(r.service_time, 1, 10)) <= date(?)'
        params.append(service_end)
    c.execute(f'SELECT COUNT(1) as cnt {sql}', params)
    count_row = c.fetchone()
    total = int(count_row['cnt']) if count_row and count_row['cnt'] is not None else 0
    c.execute(
        f'''
        SELECT r.*, c.name as customer_name, c.phone as customer_phone
        {sql}
        ORDER BY r.service_time DESC, r.id DESC
        LIMIT ? OFFSET ?
        '''
        ,
        params + [page_size, offset],
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


@bp.route('/api/improvement-records/pending-fill', methods=['GET'])
def api_improvement_records_pending_fill():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT
            'appointments' as service_type,
            a.id as service_id,
            c.name as customer_name,
            c.phone as customer_phone,
            COALESCE(p.name, '') as service_project,
            (a.appointment_date || ' ' || a.start_time) as service_time,
            a.appointment_date,
            a.start_time
        FROM appointments a
        JOIN customers c ON a.customer_id=c.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE LOWER(COALESCE(a.status, ''))='completed'
          AND LOWER(COALESCE(a.checkin_status, ''))='checked_in'
          AND NOT EXISTS (
                SELECT 1
                FROM service_improvement_records r
                WHERE LOWER(TRIM(COALESCE(r.service_type, ''))) IN ('appointments', 'appointment')
                  AND r.service_id=a.id
          )
        UNION ALL
        SELECT
            'home_appointments' as service_type,
            h.id as service_id,
            c.name as customer_name,
            c.phone as customer_phone,
            COALESCE(p.name, h.service_project, '') as service_project,
            (h.appointment_date || ' ' || h.start_time) as service_time,
            h.appointment_date,
            h.start_time
        FROM home_appointments h
        JOIN customers c ON h.customer_id=c.id
        LEFT JOIN therapy_projects p ON h.project_id=p.id
        WHERE LOWER(COALESCE(h.status, ''))='completed'
          AND LOWER(COALESCE(h.checkin_status, ''))='checked_in'
          AND NOT EXISTS (
                SELECT 1
                FROM service_improvement_records r
                WHERE LOWER(TRIM(COALESCE(r.service_type, ''))) IN ('home_appointments', 'home')
                  AND r.service_id=h.id
          )
        ORDER BY appointment_date DESC, start_time DESC, service_id DESC
        '''
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(rows)


@bp.route('/api/improvement-records/<int:rid>', methods=['GET'])
def api_improvement_record_get(rid):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT r.*, c.name as customer_name, c.phone as customer_phone, c.health_status
        FROM service_improvement_records r
        JOIN customers c ON r.customer_id=c.id
        WHERE r.id=?
        ''',
        (rid,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return error_response('记录不存在', 404, 'NOT_FOUND')
    return success_response(dict(row))


@bp.route('/api/improvement-records', methods=['POST'])
def api_improvement_record_create():
    d = request.json or {}
    service_type = normalize_improvement_service_type(d.get('service_type') or 'appointments')
    conn = get_db()
    c = conn.cursor()
    err = validate_improvement_payload(d, c)
    if err:
        conn.close()
        return error_response(err)
    now_ts = now_local_str()
    c.execute('SELECT id FROM customers WHERE id=? AND is_deleted=0', (d.get('customer_id'),))
    if not c.fetchone():
        conn.close()
        return error_response('客户不存在')
    try:
        c.execute(
            '''
            INSERT INTO service_improvement_records
            (service_id, service_type, customer_id, service_time, service_project, pre_service_status, service_content,
             post_service_evaluation, improvement_status, followup_time, followup_date, followup_method, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                d.get('service_id'),
                service_type,
                d.get('customer_id'),
                d.get('service_time'),
                d.get('service_project'),
                d.get('pre_service_status'),
                d.get('service_content'),
                d.get('post_service_evaluation'),
                d.get('improvement_status'),
                d.get('followup_time'),
                d.get('followup_date'),
                d.get('followup_method'),
                now_ts,
            ),
        )
        rid = c.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return error_response('保存失败：关联数据不存在或已失效')
    conn.close()
    audit_log('新增改善记录', 'service_improvement_records', rid, f"customer_id={d.get('customer_id')}")
    return success_response({'id': rid}, '改善记录已添加', 201)


@bp.route('/api/improvement-records/<int:rid>', methods=['PUT'])
def api_improvement_record_update(rid):
    d = request.json or {}
    service_type = normalize_improvement_service_type(d.get('service_type') or 'appointments')
    conn = get_db()
    c = conn.cursor()
    err = validate_improvement_payload(d, c)
    if err:
        conn.close()
        return error_response(err)
    now_ts = now_local_str()
    c.execute('SELECT id FROM service_improvement_records WHERE id=?', (rid,))
    if not c.fetchone():
        conn.close()
        return error_response('记录不存在', 404, 'NOT_FOUND')
    c.execute('SELECT id FROM customers WHERE id=? AND is_deleted=0', (d.get('customer_id'),))
    if not c.fetchone():
        conn.close()
        return error_response('客户不存在')
    try:
        c.execute(
            '''
            UPDATE service_improvement_records
            SET service_id=?, service_type=?, customer_id=?, service_time=?, service_project=?, pre_service_status=?, service_content=?,
                post_service_evaluation=?, improvement_status=?, followup_time=?, followup_date=?, followup_method=?,
                updated_at=?
            WHERE id=?
            ''',
            (
                d.get('service_id'),
                service_type,
                d.get('customer_id'),
                d.get('service_time'),
                d.get('service_project'),
                d.get('pre_service_status'),
                d.get('service_content'),
                d.get('post_service_evaluation'),
                d.get('improvement_status'),
                d.get('followup_time'),
                d.get('followup_date'),
                d.get('followup_method'),
                now_ts,
                rid,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return error_response('保存失败：关联数据不存在或已失效')
    conn.close()
    audit_log('修改改善记录', 'service_improvement_records', rid, f"customer_id={d.get('customer_id')}")
    return success_response({'id': rid}, '改善记录已更新')


@bp.route('/api/improvement-records/<int:rid>', methods=['DELETE'])
def api_improvement_record_delete(rid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM service_improvement_records WHERE id=?', (rid,))
    if not c.fetchone():
        conn.close()
        return error_response('记录不存在', 404, 'NOT_FOUND')
    c.execute('SELECT file_path FROM improvement_record_files WHERE improvement_record_id=?', (rid,))
    attached_paths = [str(row['file_path'] or '').strip() for row in c.fetchall() if str(row['file_path'] or '').strip()]
    try:
        c.execute('DELETE FROM improvement_record_files WHERE improvement_record_id=?', (rid,))
        c.execute('DELETE FROM service_improvement_records WHERE id=?', (rid,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return error_response('删除失败：该记录存在关联数据，无法删除')
    conn.close()
    for rel_path in attached_paths:
        abs_path = os.path.join(BASE_DIR, rel_path)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
            except OSError:
                logging.exception('删除理疗附件失败: %s', abs_path)
    audit_log('删除改善记录', 'service_improvement_records', rid, '')
    return success_response({}, '已删除')


@bp.route('/api/improvement-records/<int:rid>/files', methods=['POST'])
def api_improvement_record_file_upload(rid):
    uploaded_file = request.files.get('file')
    if uploaded_file is None:
        return error_response('请先选择要上传的文件')
    original_name = str(uploaded_file.filename or '').strip()
    if not original_name:
        return error_response('文件名不能为空')
    ext = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
    if ext not in ALLOWED_IMPROVEMENT_FILE_EXTENSIONS:
        return error_response('文件扩展名不合法，仅支持 pdf/png/jpg/jpeg')
    mimetype = str(uploaded_file.mimetype or '').lower().strip()
    allowed_mime_types = ALLOWED_IMPROVEMENT_MIME_TYPES.get(ext, set())
    if mimetype not in allowed_mime_types:
        return error_response(
            f'文件 MIME type 不合法，当前为 {mimetype or "未知"}，仅支持 pdf/png/jpg/jpeg',
            400,
            'INVALID_FILE_TYPE',
        )

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, customer_id FROM service_improvement_records WHERE id=?', (rid,))
    record = c.fetchone()
    if not record:
        conn.close()
        return error_response('理疗记录不存在，请先保存理疗记录', 404, 'NOT_FOUND')
    customer_id = int(record['customer_id'])

    c.execute('SELECT name, phone FROM customers WHERE id=? AND is_deleted=0', (customer_id,))
    customer = c.fetchone()
    if not customer:
        conn.close()
        return error_response('关联客户不存在', 404, 'NOT_FOUND')

    folder_name = get_customer_privacy_folder(customer['name'], customer['phone'], customer_id)
    target_dir = os.path.join(LOCAL_FILE_UPLOAD_ROOT, folder_name)
    os.makedirs(target_dir, exist_ok=True)

    safe_base_name = secure_filename(os.path.splitext(original_name)[0]) or 'record_file'
    timestamp = now_local().strftime('%Y%m%d_%H%M%S')
    save_filename = f'{timestamp}_{safe_base_name}.{ext}'
    absolute_path = os.path.join(target_dir, save_filename)
    uploaded_file.save(absolute_path)
    file_size = os.path.getsize(absolute_path)
    relative_path = os.path.relpath(absolute_path, BASE_DIR).replace('\\', '/')

    c.execute(
        '''
        INSERT INTO improvement_record_files
        (customer_id, improvement_record_id, file_name, file_ext, file_path, file_size)
        VALUES (?,?,?,?,?,?)
        ''',
        (
            customer_id,
            rid,
            original_name,
            ext,
            relative_path,
            file_size,
        ),
    )
    file_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log('上传理疗附件', 'improvement_record_files', file_id, f'improvement_record_id={rid}')
    return success_response(
        {
            'id': file_id,
            'improvement_record_id': rid,
            'customer_id': customer_id,
            'file_name': original_name,
            'file_ext': ext,
            'file_path': relative_path,
            'file_size': file_size,
        },
        '文件上传成功',
        201,
    )


@bp.route('/api/improvement-records/latest', methods=['GET'])
def api_improvement_record_latest():
    customer_id = request.args.get('customer_id', type=int)
    if not customer_id:
        return error_response('customer_id 必填')
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT r.*, c.name as customer_name
        FROM service_improvement_records r
        JOIN customers c ON r.customer_id=c.id
        WHERE r.customer_id=?
        ORDER BY r.service_time DESC, r.id DESC
        LIMIT 1
        ''',
        (customer_id,),
    )
    row = c.fetchone()
    conn.close()
    return success_response(dict(row) if row else {})


@bp.route('/api/improvement-records/from-appointment', methods=['GET'])
def api_improvement_record_from_appointment():
    service_id = request.args.get('service_id', type=int)
    service_type = normalize_improvement_service_type(request.args.get('service_type') or 'appointments')
    if not service_id:
        return error_response('service_id 必填')
    if service_type not in IMPROVEMENT_SERVICE_TYPE_OPTIONS:
        return error_response('service_type 不合法')
    conn = get_db()
    c = conn.cursor()
    if service_type == 'home_appointments':
        c.execute(
            '''
            SELECT h.id as service_id, h.customer_id, c.name as customer_name, c.phone as customer_phone,
                   COALESCE(p.name, h.service_project, '') as service_project,
                   h.appointment_date, h.start_time, h.end_time
            FROM home_appointments h
            JOIN customers c ON h.customer_id=c.id
            LEFT JOIN therapy_projects p ON h.project_id=p.id
            WHERE h.id=?
            ''',
            (service_id,),
        )
    else:
        c.execute(
            '''
            SELECT a.id as service_id, a.customer_id, c.name as customer_name, c.phone as customer_phone,
                   COALESCE(p.name, '') as service_project,
                   a.appointment_date, a.start_time, a.end_time
            FROM appointments a
            JOIN customers c ON a.customer_id=c.id
            LEFT JOIN therapy_projects p ON a.project_id=p.id
            WHERE a.id=?
            ''',
            (service_id,),
        )
    appt = c.fetchone()
    if not appt:
        conn.close()
        return error_response('预约记录不存在', 404, 'NOT_FOUND')
    appt_dict = dict(appt)
    summary = get_latest_assessment_summary(c, appt_dict['customer_id'])
    conn.close()
    service_time = f"{appt_dict.get('appointment_date') or ''} {appt_dict.get('start_time') or ''}".strip()
    return success_response({
        'service_id': appt_dict.get('service_id'),
        'service_type': service_type,
        'customer_id': appt_dict.get('customer_id'),
        'customer_name': appt_dict.get('customer_name'),
        'customer_phone': appt_dict.get('customer_phone'),
        'service_project': appt_dict.get('service_project'),
        'service_time': service_time,
        'pre_service_status': summary,
    })


# ========== 预约 ==========
