from flask import Blueprint
from backend.core import *

bp = Blueprint('appointments', __name__)

@bp.route('/api/appointments', methods=['GET'])
def api_appointments_list():
    sort_by = (request.args.get('sort_by') or 'time_desc').strip()
    status = (request.args.get('status', '') or '').strip().lower()
    checkin_status = (request.args.get('checkin_status', '') or '').strip().lower()
    search = (request.args.get('search', '') or '').strip()
    date_from = (request.args.get('date_from', '') or '').strip()
    date_to = (request.args.get('date_to', '') or '').strip()
    page, page_size, offset = parse_list_params()
    order_sql = {
        'time_desc': 'a.appointment_date DESC, a.start_time DESC, a.id DESC',
        'time_asc': 'a.appointment_date ASC, a.start_time ASC, a.id ASC',
        'name_asc': 'c.name COLLATE NOCASE ASC, a.appointment_date DESC, a.start_time DESC, a.id DESC',
    }.get(sort_by, 'a.appointment_date DESC, a.start_time DESC, a.id DESC')

    conn = get_db()
    c = conn.cursor()
    base_sql = '''
        FROM appointments a
        JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE 1=1
    '''
    params = []
    if status:
        base_sql += ' AND LOWER(COALESCE(a.status, ""))=?'
        params.append(status)
    if checkin_status:
        base_sql += ' AND LOWER(COALESCE(a.checkin_status, ""))=?'
        params.append(checkin_status)
    if search:
        like = f'%{search}%'
        base_sql += ' AND (c.name LIKE ? OR c.phone LIKE ?)'
        params.extend([like, like])
    if date_from:
        base_sql += ' AND date(a.appointment_date) >= date(?)'
        params.append(date_from)
    if date_to:
        base_sql += ' AND date(a.appointment_date) <= date(?)'
        params.append(date_to)
    c.execute(f'SELECT COUNT(*) as n {base_sql}', params)
    total = c.fetchone()['n']
    c.execute(f'''
        SELECT a.*, c.name as customer_name, c.phone as customer_phone, e.name as equipment_name,
               p.name as project_name
        {base_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    ''', params + [page_size, offset])
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


@bp.route('/api/appointments', methods=['POST'])
def api_appointment_create():
    d = request.json or {}
    validation_error = validate_appointment_payload(d)
    if validation_error:
        return error_response(validation_error)
    if not is_today_or_future(d.get('appointment_date')):
        return error_response('预约时间仅可选择当天及以后日期')
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    # 前端未传时由后端自动生成，保证单条/多条都具备分组ID
    booking_group_id = str(d.get('booking_group_id') or '').strip() or generate_booking_group_id()
    c.execute('SELECT * FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('项目不存在')
    required_equipment_names = get_project_required_equipment_names(project['name'], c)
    if required_equipment_names and not d.get('equipment_id'):
        conn.close()
        return error_response('该项目需要指定设备')

    if d.get('equipment_id'):
        c.execute('SELECT id, name, status FROM equipment WHERE id=?', (d.get('equipment_id'),))
        equipment = c.fetchone()
        if not equipment:
            conn.close()
            return error_response('设备不存在')
        if equipment['status'] == 'maintenance':
            conn.close()
            return error_response('正在维修，不可预约')
        if equipment['status'] != 'available':
            conn.close()
            return error_response('设备不可用')
        if required_equipment_names and equipment['name'] not in required_equipment_names:
            conn.close()
            return error_response('所选设备与项目不匹配')

    c.execute(f"SELECT COUNT(*) as n FROM appointments WHERE customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
              (d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
    if c.fetchone()['n'] > 0:
        conn.close()
        return error_response('同一客户同一时段不能重复预约')

    if d.get('equipment_id'):
        c.execute(f"SELECT COUNT(*) as n FROM appointments WHERE equipment_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
                  (d.get('equipment_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
        if c.fetchone()['n'] > 0:
            conn.close()
            return error_response('该时段设备已被预约')

    new_status = str(d.get('status') or 'scheduled').strip().lower()
    checkin_status = 'none' if new_status == 'cancelled' else 'pending'
    c.execute('''
        INSERT INTO appointments (
            booking_group_id, customer_id, project_id, equipment_id, staff_id,
            appointment_date, start_time, end_time, status, checkin_status,
            has_companion, notes, updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        booking_group_id, d.get('customer_id'), d.get('project_id'), d.get('equipment_id'), None,
        d.get('appointment_date'), d.get('start_time'), d.get('end_time'), new_status, checkin_status,
        d.get('has_companion', '无'), d.get('notes'), now_ts,
    ))
    rid = c.lastrowid
    c.execute(
        '''
        SELECT a.*, c.name as customer_name, e.name as equipment_name, p.name as project_name
        FROM appointments a
        LEFT JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE a.id=?
        ''',
        (rid,),
    )
    created_record = c.fetchone()
    insert_business_history_log(
        c,
        'appointments',
        rid,
        'create',
        '',
        build_appointment_change_text(dict(created_record) if created_record else {}, 'appointments'),
    )
    conn.commit()
    conn.close()
    audit_log('创建预约', 'appointments', rid, d.get('appointment_date'))
    return success_response({'id': rid, 'booking_group_id': booking_group_id}, '预约成功', 201)


@bp.route('/api/appointments/slot-panel', methods=['GET'])
def api_appointments_slot_panel():
    date = request.args.get('date')
    project_id = request.args.get('project_id', type=int)
    exclude_appointment_id = request.args.get('exclude_appointment_id', type=int)
    if not date:
        return error_response('缺少 date')
    if not project_id:
        return error_response('缺少 project_id')

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (project_id,))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('项目不存在', 404, 'NOT_FOUND')

    available_equipment = get_project_available_equipment(project['name'], c)

    slots = generate_time_slots('08:30', '16:00', 15)
    slot_items = []
    for st, et in slots:
        free_equipment = []
        maintenance_equipment = []
        if available_equipment:
            for equipment in available_equipment:
                equipment_status = str(equipment.get('status') or 'available')
                if equipment_status != 'available':
                    maintenance_equipment.append({
                        'id': equipment['id'],
                        'name': equipment['name'],
                        'location': equipment.get('location'),
                        'model': equipment.get('model'),
                        'status': equipment_status,
                    })
                    continue
                c.execute(
                    f"SELECT COUNT(*) as n FROM appointments WHERE appointment_date=? AND status='scheduled' AND equipment_id=? "
                    f"AND (? IS NULL OR id<>?) AND {overlap_condition()}",
                    (date, equipment['id'], exclude_appointment_id, exclude_appointment_id, et, st),
                )
                if c.fetchone()['n'] == 0:
                    free_equipment.append({
                        'id': equipment['id'],
                        'name': equipment['name'],
                        'location': equipment.get('location'),
                        'model': equipment.get('model'),
                        'status': equipment_status,
                    })

        slot_items.append({
            'start_time': st,
            'end_time': et,
            'status': 'available' if free_equipment else ('maintenance' if maintenance_equipment else 'full'),
            'available_equipment_count': len(free_equipment),
            'available_equipment': free_equipment,
            'maintenance_equipment': maintenance_equipment,
        })

    conn.close()
    return success_response({
        'date': date,
        'project_id': project_id,
        'slots': slot_items,
    })


@bp.route('/api/appointments/free-slots', methods=['GET'])
def api_appointments_free_slots():
    """兼容旧接口：返回结构与 slot-panel 保持同语义。"""
    panel_resp, status = api_appointments_slot_panel()
    if status != 200:
        return panel_resp, status
    data = panel_resp.get_json().get('data') or {}
    return success_response(data.get('slots', []))


@bp.route('/api/appointments/available-options', methods=['GET'])
def api_appointments_available_options():
    date = request.args.get('date')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    project_id = request.args.get('project_id', type=int)
    if not all([date, start_time, end_time, project_id]):
        return error_response('缺少必要参数')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM therapy_projects WHERE id=?', (project_id,))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('项目不存在', 404, 'NOT_FOUND')
    c.execute(f"SELECT equipment_id FROM appointments WHERE appointment_date=? AND status='scheduled' AND {overlap_condition()} AND equipment_id IS NOT NULL", (date, end_time, start_time))
    busy_eq = [r['equipment_id'] for r in c.fetchall()]
    if busy_eq:
        ph = ','.join('?' * len(busy_eq))
        c.execute(f"SELECT * FROM equipment WHERE status='available' AND id NOT IN ({ph}) ORDER BY name", busy_eq)
    else:
        c.execute("SELECT * FROM equipment WHERE status='available' ORDER BY name")
    avail_equipment = row_list(c.fetchall())
    conn.close()
    return success_response({'project': dict(project), 'available_equipment': avail_equipment})




@bp.route('/api/appointments/<int:aid>', methods=['PUT'])
def api_appointment_update(aid):
    d = request.json or {}
    validation_error = validate_appointment_payload(d)
    if validation_error:
        return error_response(validation_error)
    if not is_today_or_future(d.get('appointment_date')):
        return error_response('预约时间仅可选择当天及以后日期')

    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    c.execute(
        '''
        SELECT a.*, c.name as customer_name, e.name as equipment_name, p.name as project_name
        FROM appointments a
        LEFT JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE a.id=?
        ''',
        (aid,),
    )
    old_row = c.fetchone()
    if not old_row:
        conn.close()
        return error_response('预约记录不存在', 404, 'NOT_FOUND')
    old_status = str(old_row['status'] or 'scheduled').strip().lower()
    if old_status == 'completed':
        conn.close()
        return error_response('服务已完成，预约不可再编辑')

    c.execute('SELECT * FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('项目不存在')

    required_equipment_names = get_project_required_equipment_names(project['name'], c)
    if required_equipment_names and not d.get('equipment_id'):
        conn.close()
        return error_response('该项目需要指定设备')

    if d.get('equipment_id'):
        c.execute('SELECT id, name, status FROM equipment WHERE id=?', (d.get('equipment_id'),))
        equipment = c.fetchone()
        if not equipment:
            conn.close()
            return error_response('设备不存在')
        if equipment['status'] == 'maintenance':
            conn.close()
            return error_response('正在维修，不可预约')
        if equipment['status'] != 'available':
            conn.close()
            return error_response('设备不可用')
        if required_equipment_names and equipment['name'] not in required_equipment_names:
            conn.close()
            return error_response('所选设备与项目不匹配')

    c.execute(
        f"SELECT COUNT(*) as n FROM appointments WHERE id<>? AND customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
        (aid, d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')),
    )
    if c.fetchone()['n'] > 0:
        conn.close()
        return error_response('同一客户同一时段不能重复预约')

    if d.get('equipment_id'):
        c.execute(
            f"SELECT COUNT(*) as n FROM appointments WHERE id<>? AND equipment_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
            (aid, d.get('equipment_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')),
        )
        if c.fetchone()['n'] > 0:
            conn.close()
            return error_response('该时段设备已被预约')

    new_status = str(d.get('status', 'scheduled') or 'scheduled').strip().lower()
    old_checkin_status = str(old_row['checkin_status'] or 'pending').strip().lower()
    next_checkin_status = 'none' if new_status == 'cancelled' else ('pending' if old_checkin_status == 'none' else old_checkin_status)

    c.execute(
        '''
        UPDATE appointments
        SET customer_id=?, project_id=?, equipment_id=?, staff_id=?, appointment_date=?, start_time=?, end_time=?, status=?, checkin_status=?, has_companion=?, notes=?, updated_at=?
        WHERE id=?
        ''',
        (
            d.get('customer_id'), d.get('project_id'), d.get('equipment_id'), None,
            d.get('appointment_date'), d.get('start_time'), d.get('end_time'), new_status, next_checkin_status, d.get('has_companion', '无'), d.get('notes'),
            now_ts,
            aid,
        ),
    )
    before_text = build_appointment_change_text(dict(old_row), 'appointments')
    c.execute(
        '''
        SELECT a.*, c.name as customer_name, e.name as equipment_name, p.name as project_name
        FROM appointments a
        LEFT JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE a.id=?
        ''',
        (aid,),
    )
    new_row = c.fetchone()
    insert_business_history_log(
        c,
        'appointments',
        aid,
        'update',
        before_text,
        build_appointment_change_text(dict(new_row) if new_row else {}, 'appointments'),
    )
    conn.commit()
    conn.close()
    audit_log('修改预约', 'appointments', aid, d.get('appointment_date'))
    return success_response({'id': aid}, '预约修改成功')

@bp.route('/api/appointments/<int:aid>/cancel', methods=['POST'])
def api_appointment_cancel(aid):
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    c.execute(
        '''
        SELECT a.*, c.name as customer_name, e.name as equipment_name, p.name as project_name
        FROM appointments a
        LEFT JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE a.id=?
        ''',
        (aid,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return error_response('预约记录不存在', 404, 'NOT_FOUND')
    row_status = (row['status'] or '').strip().lower()
    if row_status == 'cancelled':
        conn.close()
        return error_response('已经提交过取消预约，请勿再次提交')
    if row_status == 'completed':
        conn.close()
        return error_response('服务已完成，不可取消预约')
    c.execute(
        "UPDATE appointments SET status='cancelled', checkin_status='none', checkin_updated_at=?, checkin_updated_by=?, checkin_updated_ip=?, updated_at=? WHERE id=?",
        (now_ts, session.get('username', 'anonymous'), get_request_ip(), now_ts, aid),
    )
    insert_business_history_log(
        c,
        'appointments',
        aid,
        'cancel',
        build_appointment_change_text(dict(row), 'appointments'),
        '状态:取消预约',
    )
    conn.commit()
    conn.close()
    audit_log('取消预约', 'appointments', aid, '门店预约取消')
    return success_response({'id': aid}, '已取消')


def update_checkin_status(cursor, table_name, module_name, record_id, target_status):
    cursor.execute(f'SELECT * FROM {table_name} WHERE id=?', (record_id,))
    row = cursor.fetchone()
    if not row:
        return None, '预约记录不存在'
    booking_status = str(row['status'] or '').strip().lower()
    current_checkin = str(row['checkin_status'] or 'pending').strip().lower()
    appointment_date = str(row['appointment_date'] or '').strip()

    if booking_status != 'scheduled':
        return None, '仅预约成功状态可操作签到'
    if not is_valid_date(appointment_date):
        return None, '预约日期异常，无法签到'
    now_ts = now_local_str()
    today_text = now_ts[:10]
    if appointment_date != today_text:
        return None, '仅预约当日允许操作签到状态'
    if current_checkin == 'no_show':
        return None, '爽约状态不可修改'
    if current_checkin != 'pending':
        return None, '当前签到状态不可修改'
    if target_status not in {'checked_in', 'no_show'}:
        return None, '签到状态不合法'

    before_text = f"预约状态:预约成功；签到状态:{'待签到' if current_checkin == 'pending' else current_checkin}"
    after_text = f"预约状态:预约成功；签到状态:{'已签到' if target_status == 'checked_in' else '爽约'}"
    cursor.execute(
        f'''
        UPDATE {table_name}
        SET checkin_status=?, checkin_updated_at=?, checkin_updated_by=?, checkin_updated_ip=?, updated_at=?
        WHERE id=?
        ''',
        (target_status, now_ts, session.get('username', 'anonymous'), get_request_ip(), now_ts, record_id),
    )
    insert_business_history_log(cursor, module_name, record_id, 'checkin_status_update', before_text, after_text)
    insert_audit_log(cursor, '更新签到状态', module_name, record_id, f'{current_checkin}->{target_status}')
    return dict(row), None


def complete_service(cursor, table_name, module_name, record_id):
    cursor.execute(f'SELECT * FROM {table_name} WHERE id=?', (record_id,))
    row = cursor.fetchone()
    if not row:
        return None, '预约记录不存在'
    booking_status = str(row['status'] or '').strip().lower()
    current_checkin = str(row['checkin_status'] or 'pending').strip().lower()
    now_ts = now_local_str()

    if booking_status == 'cancelled':
        return None, '取消预约不可完成服务'
    if booking_status == 'completed':
        return None, '该预约已完成服务，请勿重复提交'
    if booking_status != 'scheduled':
        return None, '仅预约成功状态可完成服务'
    if current_checkin != 'checked_in':
        return None, '仅已签到预约可完成服务'

    cursor.execute(
        f'''
        UPDATE {table_name}
        SET status='completed', updated_at=?
        WHERE id=?
        ''',
        (now_ts, record_id),
    )
    before_text = '预约状态:预约成功；签到状态:已签到'
    after_text = '预约状态:服务完成；签到状态:已签到'
    insert_business_history_log(cursor, module_name, record_id, 'complete_service', before_text, after_text)
    insert_audit_log(cursor, '完成服务', module_name, record_id, 'scheduled+checked_in->completed')
    return dict(row), None


@bp.route('/api/appointments/<int:aid>/checkin-status', methods=['POST'])
def api_appointment_checkin_status(aid):
    payload = request.json or {}
    target_status = str(payload.get('checkin_status') or '').strip().lower()
    conn = get_db()
    c = conn.cursor()
    _, err = update_checkin_status(c, 'appointments', 'appointments', aid, target_status)
    if err:
        conn.close()
        return error_response(err)
    conn.commit()
    conn.close()
    return success_response({'id': aid, 'checkin_status': target_status}, '签到状态更新成功')


@bp.route('/api/appointments/<int:aid>/complete', methods=['POST'])
def api_appointment_complete(aid):
    conn = get_db()
    c = conn.cursor()
    _, err = complete_service(c, 'appointments', 'appointments', aid)
    if err:
        conn.close()
        return error_response(err)
    conn.commit()
    conn.close()
    return success_response({'id': aid, 'status': 'completed'}, '服务已完成')


# ========== 上门预约 ==========
