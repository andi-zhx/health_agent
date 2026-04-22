from flask import Blueprint
from backend.core import *

bp = Blueprint('home_appointments', __name__)

@bp.route('/api/home-appointments', methods=['GET'])
def api_home_appointments_list():
    sort_by = (request.args.get('sort_by') or 'time_desc').strip()
    status = (request.args.get('status', '') or '').strip().lower()
    checkin_status = (request.args.get('checkin_status', '') or '').strip().lower()
    search = (request.args.get('search', '') or '').strip()
    date_from = (request.args.get('date_from', '') or '').strip()
    date_to = (request.args.get('date_to', '') or '').strip()
    page, page_size, offset = parse_list_params()
    order_sql = {
        'time_desc': 'h.appointment_date DESC, h.start_time DESC, h.id DESC',
        'time_asc': 'h.appointment_date ASC, h.start_time ASC, h.id ASC',
        'name_asc': 'COALESCE(h.customer_name, c.name) COLLATE NOCASE ASC, h.appointment_date DESC, h.start_time DESC, h.id DESC',
    }.get(sort_by, 'h.appointment_date DESC, h.start_time DESC, h.id DESC')

    conn = get_db()
    c = conn.cursor()
    base_sql = '''
        FROM home_appointments h
        LEFT JOIN customers c ON h.customer_id=c.id
        LEFT JOIN therapy_projects p ON h.project_id=p.id
        LEFT JOIN staff s ON h.staff_id=s.id
        WHERE 1=1
    '''
    params = []
    if status:
        base_sql += ' AND LOWER(COALESCE(h.status, ""))=?'
        params.append(status)
    if checkin_status:
        base_sql += ' AND LOWER(COALESCE(h.checkin_status, ""))=?'
        params.append(checkin_status)
    if search:
        like = f'%{search}%'
        base_sql += ' AND (COALESCE(h.customer_name, c.name) LIKE ? OR COALESCE(h.phone, c.phone) LIKE ?)'
        params.extend([like, like])
    if date_from:
        base_sql += ' AND date(h.appointment_date) >= date(?)'
        params.append(date_from)
    if date_to:
        base_sql += ' AND date(h.appointment_date) <= date(?)'
        params.append(date_to)
    c.execute(f'SELECT COUNT(*) as n {base_sql}', params)
    total = c.fetchone()['n']
    c.execute(f'''
        SELECT
            h.*,
            COALESCE(h.customer_name, c.name) AS customer_name,
            COALESCE(h.service_project, p.name) AS project_name,
            COALESCE(h.staff_name, s.name) AS staff_name,
            COALESCE(h.phone, c.phone) AS phone,
            COALESCE(h.home_address, h.location) AS home_address,
            COALESCE(h.home_time, h.start_time || '-' || h.end_time) AS home_time
        {base_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    ''', params + [page_size, offset])
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


@bp.route('/api/home-appointments/slot-panel', methods=['GET'])
def api_home_appointments_slot_panel():
    date = (request.args.get('date') or '').strip()
    project_id = (request.args.get('project_id') or '').strip()
    if not date or not project_id:
        return error_response('缺少参数：date/project_id')
    if not is_valid_date(date):
        return error_response('预约日期格式必须为 YYYY-MM-DD')

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (project_id,))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('上门项目不存在', 404, 'NOT_FOUND')

    c.execute(
        '''
        SELECT COUNT(*) AS n
        FROM project_staff_mapping m
        JOIN staff s ON s.id = m.staff_id
        WHERE m.project_name=?
          AND COALESCE(m.status, 'enabled')='enabled'
          AND COALESCE(s.status, 'available')='available'
        ''',
        (project['name'],),
    )
    mapped_total = c.fetchone()['n'] or 0
    if mapped_total <= 0:
        c.execute("SELECT COUNT(*) AS n FROM staff WHERE status='available'")
        mapped_total = c.fetchone()['n'] or 0

    slots = []
    for st, et in generate_time_slots('08:30', '16:00', 30):
        c.execute(
            '''
            SELECT COUNT(DISTINCT h.staff_id) AS n
            FROM home_appointments h
            WHERE h.appointment_date=?
              AND h.status='scheduled'
              AND h.staff_id IS NOT NULL
              AND (h.start_time < ?) AND (h.end_time > ?)
            ''',
            (date, et, st),
        )
        busy_count = c.fetchone()['n'] or 0
        available_count = max(0, mapped_total - busy_count)
        slots.append({
            'start_time': st,
            'end_time': et,
            'available_count': available_count,
            'status': 'available' if available_count > 0 else 'full',
        })
    conn.close()
    return success_response({
        'project_id': int(project_id),
        'project_name': project['name'],
        'appointment_date': date,
        'slots': slots,
    })


@bp.route('/api/home-appointments/staff-panel', methods=['GET'])
def api_home_appointments_staff_panel():
    date = (request.args.get('date') or '').strip()
    project_id = (request.args.get('project_id') or '').strip()
    start_time = (request.args.get('start_time') or '').strip()
    end_time = (request.args.get('end_time') or '').strip()

    if not date or not project_id or not start_time or not end_time:
        return error_response('缺少参数：date/project_id/start_time/end_time')
    if not is_valid_date(date):
        return error_response('预约日期格式必须为 YYYY-MM-DD')
    if not is_valid_home_time_range(start_time, end_time):
        return error_response('上门预约时间需在08:30-16:00且结束时间晚于开始时间')
    if not is_half_hour_slot(start_time, end_time):
        return error_response('上门预约时间段需按30分钟选择')

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (project_id,))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('上门项目不存在', 404, 'NOT_FOUND')

    c.execute(
        '''
        SELECT s.id, s.name, s.role, s.status
        FROM project_staff_mapping m
        JOIN staff s ON s.id = m.staff_id
        WHERE m.project_name=?
          AND COALESCE(m.status, 'enabled')='enabled'
        ORDER BY s.name ASC
        ''',
        (project['name'],),
    )
    mapped = row_list(c.fetchall())
    if not mapped:
        c.execute("SELECT id, name, role, status FROM staff WHERE status='available' ORDER BY name ASC")
        mapped = row_list(c.fetchall())

    items = []
    available_count = 0
    for staff in mapped:
        is_active = (staff.get('status') or 'available') == 'available'
        has_conflict = False
        if is_active:
            c.execute(
                f'''
                SELECT COUNT(*) AS n
                FROM home_appointments
                WHERE staff_id=?
                  AND appointment_date=?
                  AND status='scheduled'
                  AND {overlap_condition()}
                ''',
                (staff['id'], date, end_time, start_time),
            )
            has_conflict = (c.fetchone()['n'] or 0) > 0
        state = 'available' if (is_active and not has_conflict) else 'full'
        if state == 'available':
            available_count += 1
        items.append({
            'staff_id': staff['id'],
            'staff_name': staff.get('name') or '',
            'role': staff.get('role') or '',
            'status': state,
            'display': '可预约' if state == 'available' else '已约满',
        })
    conn.close()
    return success_response({
        'project_id': int(project_id),
        'project_name': project['name'],
        'appointment_date': date,
        'start_time': start_time,
        'end_time': end_time,
        'available_count': available_count,
        'staff': items,
    })


@bp.route('/api/home-appointments', methods=['POST'])
def api_home_appointments_create():
    d = request.json or {}
    validation_error = validate_home_appointment_payload(d)
    if validation_error:
        return error_response(validation_error)
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    # 前端未传时由后端自动生成，保证单条/多条都具备分组ID
    booking_group_id = str(d.get('booking_group_id') or '').strip() or generate_booking_group_id()

    c.execute('SELECT id, name, phone FROM customers WHERE id=? AND is_deleted=0', (d.get('customer_id'),))
    customer = c.fetchone()
    if not customer:
        conn.close()
        return error_response('客户不存在', 404, 'NOT_FOUND')

    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('上门项目不存在', 404, 'NOT_FOUND')
    if not is_project_home_allowed(project['name'], c):
        conn.close()
        return error_response('该项目不支持上门预约')

    staff = None
    if d.get('staff_id'):
        c.execute('SELECT id, name FROM staff WHERE id=?', (d.get('staff_id'),))
        staff = c.fetchone()
        if not staff:
            conn.close()
            return error_response('服务人员不存在', 404, 'NOT_FOUND')
        c.execute(
            '''
            SELECT COUNT(*) AS n
            FROM project_staff_mapping
            WHERE project_name=? AND staff_id=? AND COALESCE(status, 'enabled')='enabled'
            ''',
            (project['name'], d.get('staff_id')),
        )
        mapped = c.fetchone()['n'] or 0
        if mapped <= 0:
            c.execute(
                "SELECT COUNT(*) AS n FROM project_staff_mapping WHERE project_name=? AND COALESCE(status, 'enabled')='enabled'",
                (project['name'],),
            )
            has_mapping = c.fetchone()['n'] or 0
            if has_mapping > 0:
                conn.close()
                return error_response('所选服务人员不在该项目服务名单中')

    c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
    if c.fetchone()['n'] > 0:
        conn.close()
        return error_response('同一客户同一时段不能重复上门预约')
    if d.get('staff_id'):
        c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE staff_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (d.get('staff_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
        if c.fetchone()['n'] > 0:
            conn.close()
            return error_response('该服务人员该时段已有上门预约')

    home_address = d.get('home_address') or d.get('location')
    home_time = d.get('home_time') or f"{d.get('start_time')}-{d.get('end_time')}"

    new_status = str(d.get('status') or 'scheduled').strip().lower()
    checkin_status = 'none' if new_status == 'cancelled' else 'pending'
    c.execute('''
        INSERT INTO home_appointments (
            booking_group_id, customer_id, project_id, staff_id,
            customer_name, phone, home_time, home_address, service_project, staff_name,
            appointment_date, start_time, end_time, location, contact_person, contact_phone, has_companion, notes, status, checkin_status, updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        booking_group_id, d.get('customer_id'), d.get('project_id'), d.get('staff_id'),
        customer['name'], customer['phone'], home_time, home_address, project['name'], staff['name'] if staff else None,
        d.get('appointment_date'), d.get('start_time'), d.get('end_time'), d.get('location'), d.get('contact_person'), d.get('contact_phone'), d.get('has_companion', '无'), d.get('notes'), new_status, checkin_status, now_ts
    ))
    rid = c.lastrowid
    c.execute(
        '''
        SELECT *
        FROM home_appointments
        WHERE id=?
        ''',
        (rid,),
    )
    created_row = c.fetchone()
    insert_business_history_log(
        c,
        'home_appointments',
        rid,
        'create',
        '',
        build_appointment_change_text(dict(created_row) if created_row else {}, 'home_appointments'),
    )
    conn.commit()
    conn.close()
    audit_log('创建上门预约', 'home_appointments', rid, d.get('appointment_date'))
    return success_response({'id': rid, 'booking_group_id': booking_group_id}, '上门预约成功', 201)


@bp.route('/api/home-appointments/<int:hid>/cancel', methods=['POST'])
def api_home_appointments_cancel(hid):
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    c.execute('SELECT * FROM home_appointments WHERE id=?', (hid,))
    row = c.fetchone()
    if not row:
        conn.close()
        return error_response('上门预约不存在', 404, 'NOT_FOUND')
    row_status = (row['status'] or '').strip().lower()
    if row_status == 'cancelled':
        conn.close()
        return error_response('已经提交过取消预约，请勿再次提交')
    if row_status == 'completed':
        conn.close()
        return error_response('服务已完成，不可取消预约')
    c.execute(
        "UPDATE home_appointments SET status='cancelled', checkin_status='none', checkin_updated_at=?, checkin_updated_by=?, checkin_updated_ip=?, updated_at=? WHERE id=?",
        (now_ts, session.get('username', 'anonymous'), get_request_ip(), now_ts, hid),
    )
    insert_business_history_log(
        c,
        'home_appointments',
        hid,
        'cancel',
        build_appointment_change_text(dict(row), 'home_appointments'),
        '状态:取消预约',
    )
    conn.commit()
    conn.close()
    audit_log('取消预约', 'home_appointments', hid, '上门预约取消')
    return success_response({'id': hid}, '已取消')


@bp.route('/api/home-appointments/<int:hid>/checkin-status', methods=['POST'])
def api_home_appointments_checkin_status(hid):
    payload = request.json or {}
    target_status = str(payload.get('checkin_status') or '').strip().lower()
    conn = get_db()
    c = conn.cursor()
    _, err = update_checkin_status(c, 'home_appointments', 'home_appointments', hid, target_status)
    if err:
        conn.close()
        return error_response(err)
    conn.commit()
    conn.close()
    return success_response({'id': hid, 'checkin_status': target_status}, '签到状态更新成功')


@bp.route('/api/home-appointments/<int:hid>/complete', methods=['POST'])
def api_home_appointments_complete(hid):
    conn = get_db()
    c = conn.cursor()
    _, err = complete_service(c, 'home_appointments', 'home_appointments', hid)
    if err:
        conn.close()
        return error_response(err)
    conn.commit()
    conn.close()
    return success_response({'id': hid, 'status': 'completed'}, '服务已完成')


@bp.route('/api/home-appointments/<int:hid>', methods=['PUT'])
def api_home_appointments_update(hid):
    d = request.json or {}
    validation_error = validate_home_appointment_payload(d)
    if validation_error:
        return error_response(validation_error)
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()

    c.execute('SELECT * FROM home_appointments WHERE id=?', (hid,))
    old_row = c.fetchone()
    if not old_row:
        conn.close()
        return error_response('上门预约不存在', 404, 'NOT_FOUND')
    old_status = str(old_row['status'] or 'scheduled').strip().lower()
    if old_status == 'completed':
        conn.close()
        return error_response('服务已完成，预约不可再编辑')

    c.execute('SELECT id, name, phone FROM customers WHERE id=? AND is_deleted=0', (d.get('customer_id'),))
    customer = c.fetchone()
    if not customer:
        conn.close()
        return error_response('客户不存在', 404, 'NOT_FOUND')

    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('上门项目不存在', 404, 'NOT_FOUND')
    if not is_project_home_allowed(project['name'], c):
        conn.close()
        return error_response('该项目不支持上门预约')

    staff = None
    if d.get('staff_id'):
        c.execute('SELECT id, name FROM staff WHERE id=?', (d.get('staff_id'),))
        staff = c.fetchone()
        if not staff:
            conn.close()
            return error_response('服务人员不存在', 404, 'NOT_FOUND')
        c.execute(
            '''
            SELECT COUNT(*) AS n
            FROM project_staff_mapping
            WHERE project_name=? AND staff_id=? AND COALESCE(status, 'enabled')='enabled'
            ''',
            (project['name'], d.get('staff_id')),
        )
        mapped = c.fetchone()['n'] or 0
        if mapped <= 0:
            c.execute(
                "SELECT COUNT(*) AS n FROM project_staff_mapping WHERE project_name=? AND COALESCE(status, 'enabled')='enabled'",
                (project['name'],),
            )
            has_mapping = c.fetchone()['n'] or 0
            if has_mapping > 0:
                conn.close()
                return error_response('所选服务人员不在该项目服务名单中')

    c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE id<>? AND customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (hid, d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
    if c.fetchone()['n'] > 0:
        conn.close()
        return error_response('同一客户同一时段不能重复上门预约')
    if d.get('staff_id'):
        c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE id<>? AND staff_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (hid, d.get('staff_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
        if c.fetchone()['n'] > 0:
            conn.close()
            return error_response('该服务人员该时段已有上门预约')

    home_address = d.get('home_address') or d.get('location')
    home_time = d.get('home_time') or f"{d.get('start_time')}-{d.get('end_time')}"

    new_status = str(d.get('status', 'scheduled') or 'scheduled').strip().lower()
    old_checkin_status = str(old_row['checkin_status'] or 'pending').strip().lower()
    next_checkin_status = 'none' if new_status == 'cancelled' else ('pending' if old_checkin_status == 'none' else old_checkin_status)

    c.execute('''
        UPDATE home_appointments
        SET customer_id=?, project_id=?, staff_id=?,
            customer_name=?, phone=?, home_time=?, home_address=?, service_project=?, staff_name=?,
            appointment_date=?, start_time=?, end_time=?, location=?,
            contact_person=?, contact_phone=?, has_companion=?, notes=?, status=?, checkin_status=?, updated_at=?
        WHERE id=?
    ''', (
        d.get('customer_id'), d.get('project_id'), d.get('staff_id'),
        customer['name'], customer['phone'], home_time, home_address, project['name'], staff['name'] if staff else None,
        d.get('appointment_date'), d.get('start_time'), d.get('end_time'), d.get('location'),
        d.get('contact_person'), d.get('contact_phone'), d.get('has_companion', '无'), d.get('notes'), new_status, next_checkin_status, now_ts,
        hid,
    ))
    before_text = build_appointment_change_text(dict(old_row), 'home_appointments')
    c.execute('SELECT * FROM home_appointments WHERE id=?', (hid,))
    new_row = c.fetchone()
    insert_business_history_log(
        c,
        'home_appointments',
        hid,
        'update',
        before_text,
        build_appointment_change_text(dict(new_row) if new_row else {}, 'home_appointments'),
    )
    conn.commit()
    conn.close()
    audit_log('修改上门预约', 'home_appointments', hid, d.get('appointment_date'))
    return success_response({'id': hid}, '更新成功')


