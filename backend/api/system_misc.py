from flask import Blueprint
from backend.core import *

bp = Blueprint('system_misc', __name__)

@bp.route('/api/health-records', methods=['GET'])
def api_health_records_list():
    customer_id = request.args.get('customer_id', type=int)
    conn = get_db()
    c = conn.cursor()
    if customer_id:
        c.execute('SELECT h.*, c.name as customer_name FROM health_records h JOIN customers c ON h.customer_id=c.id WHERE h.customer_id=? ORDER BY h.record_date DESC, h.id DESC', (customer_id,))
    else:
        c.execute('SELECT h.*, c.name as customer_name FROM health_records h JOIN customers c ON h.customer_id=c.id ORDER BY h.record_date DESC, h.id DESC')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@bp.route('/api/health-records', methods=['POST'])
def api_health_record_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO health_records (customer_id, record_date, height_cm, weight_kg, blood_pressure, symptoms, diagnosis, notes)
        VALUES (?,?,?,?,?,?,?,?)
    ''', (
        d.get('customer_id'), d.get('record_date'), d.get('height_cm'), d.get('weight_kg'),
        d.get('blood_pressure'), d.get('symptoms'), d.get('diagnosis'), d.get('notes')
    ))
    conn.commit()
    id = c.lastrowid
    conn.close()
    return jsonify({'id': id, 'message': '健康档案已添加'}), 201


# ========== 来访签到 ==========
@bp.route('/api/visit-checkins', methods=['GET'])
def api_visit_checkins_list():
    customer_id = request.args.get('customer_id', type=int)
    conn = get_db()
    c = conn.cursor()
    if customer_id:
        c.execute('SELECT v.*, c.name as customer_name FROM visit_checkins v JOIN customers c ON v.customer_id=c.id WHERE v.customer_id=? ORDER BY v.checkin_time DESC, v.id DESC', (customer_id,))
    else:
        c.execute('SELECT v.*, c.name as customer_name FROM visit_checkins v JOIN customers c ON v.customer_id=c.id ORDER BY v.checkin_time DESC, v.id DESC')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@bp.route('/api/visit-checkins', methods=['POST'])
def api_visit_checkin_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO visit_checkins (customer_id, checkin_time, purpose, notes)
        VALUES (?,?,?,?)
    ''', (d.get('customer_id'), d.get('checkin_time') or now_local().strftime('%Y-%m-%d %H:%M'), d.get('purpose'), d.get('notes')))
    conn.commit()
    id = c.lastrowid
    conn.close()
    return jsonify({'id': id, 'message': '签到成功'}), 201


# ========== 设备 ==========
@bp.route('/api/equipment', methods=['GET'])
def api_equipment_list():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM equipment ORDER BY name')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@bp.route('/api/equipment', methods=['POST'])
def api_equipment_create():
    d = request.json or {}
    name = str(d.get('name') or '').strip()
    if not name:
        return error_response('设备名称为必填项')
    status = str(d.get('status') or 'available').strip()
    if status not in {'available', 'maintenance'}:
        return error_response('设备状态不合法')
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO equipment (name, type, model, location, status, description)
        VALUES (?,?,?,?,?,?)
        ''',
        (
            name,
            d.get('type') or '专用设备',
            d.get('model'),
            d.get('location'),
            status,
            d.get('description'),
        ),
    )
    conn.commit()
    equipment_id = c.lastrowid
    conn.close()
    return success_response({'id': equipment_id}, '设备创建成功', 201)


@bp.route('/api/equipment/<int:eid>', methods=['PUT'])
def api_equipment_update(eid):
    d = request.json or {}
    name = str(d.get('name') or '').strip()
    if not name:
        return error_response('设备名称为必填项')
    status = str(d.get('status') or 'available').strip()
    if status not in {'available', 'maintenance'}:
        return error_response('设备状态不合法')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM equipment WHERE id=?', (eid,))
    if not c.fetchone():
        conn.close()
        return error_response('设备不存在', 404, 'NOT_FOUND')
    c.execute(
        '''
        UPDATE equipment
        SET name=?, type=?, model=?, location=?, status=?, description=?
        WHERE id=?
        ''',
        (
            name,
            d.get('type') or '专用设备',
            d.get('model'),
            d.get('location'),
            status,
            d.get('description'),
            eid,
        ),
    )
    conn.commit()
    conn.close()
    return success_response({'id': eid}, '设备更新成功')


@bp.route('/api/equipment/available', methods=['GET'])
def api_equipment_available():
    date = request.args.get('date')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    if not all([date, start_time, end_time]):
        return jsonify({'error': '缺少 date, start_time, end_time'}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT equipment_id FROM appointments
        WHERE appointment_date=? AND status='scheduled'
        AND ((start_time<=? AND end_time>?) OR (start_time<? AND end_time>=?) OR (start_time>=? AND end_time<=?))
    ''', (date, start_time, start_time, end_time, end_time, start_time, end_time))
    booked = [r['equipment_id'] for r in c.fetchall()]
    if booked:
        ph = ','.join('?' * len(booked))
        c.execute(f"SELECT * FROM equipment WHERE status='available' AND id NOT IN ({ph}) ORDER BY name", booked)
    else:
        c.execute("SELECT * FROM equipment WHERE status='available' ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@bp.route('/api/equipment/availability-summary', methods=['GET'])
def api_equipment_availability_summary():
    date = request.args.get('date')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    if not all([date, start_time, end_time]):
        return jsonify({'error': '缺少 date, start_time, end_time'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name FROM equipment WHERE status='available' ORDER BY name")
    all_equipment = row_list(c.fetchall())
    c.execute('''
        SELECT DISTINCT equipment_id FROM appointments
        WHERE appointment_date=? AND status='scheduled'
        AND ((start_time<=? AND end_time>?) OR (start_time<? AND end_time>=?) OR (start_time>=? AND end_time<=?))
    ''', (date, start_time, start_time, end_time, end_time, start_time, end_time))
    booked_ids = {r['equipment_id'] for r in c.fetchall()}
    conn.close()

    available_equipment = [e for e in all_equipment if e['id'] not in booked_ids]
    return jsonify({
        'date': date,
        'start_time': start_time,
        'end_time': end_time,
        'total_equipment': len(all_equipment),
        'available_count': len(available_equipment),
        'booked_count': len(booked_ids),
        'available_equipment': available_equipment,
    })


# ========== 服务项目与人员 ==========
@bp.route('/api/projects', methods=['GET'])
@bp.route('/api/service-projects', methods=['GET'])
def api_projects_list():
    scene = request.args.get('scene')
    conn = get_db()
    c = conn.cursor()
    rows = load_projects_with_parallel_strategy(c, enabled_only=False, scene=scene)
    conn.close()
    return jsonify(rows)


@bp.route('/api/projects/enabled', methods=['GET'])
@bp.route('/api/service-projects/enabled', methods=['GET'])
def api_projects_enabled():
    scene = request.args.get('scene')
    conn = get_db()
    c = conn.cursor()
    rows = load_projects_with_parallel_strategy(c, enabled_only=True, scene=scene)
    conn.close()
    return jsonify(rows)


@bp.route('/api/projects', methods=['POST'])
@bp.route('/api/service-projects', methods=['POST'])
def api_projects_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO therapy_projects (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
        VALUES (?,?,?,?,?,?,?,?)
    ''', (d.get('name'), d.get('category'), d.get('duration_minutes'), d.get('need_equipment', 0), d.get('equipment_type'), d.get('price'), d.get('status', 'enabled'), d.get('description')))
    conn.commit()
    pid = c.lastrowid
    conn.close()
    return jsonify({'id': pid, 'message': '项目创建成功'}), 201


@bp.route('/api/projects/<int:pid>', methods=['PUT'])
@bp.route('/api/service-projects/<int:pid>', methods=['PUT'])
def api_projects_update(pid):
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE therapy_projects
        SET name=?, category=?, duration_minutes=?, need_equipment=?, equipment_type=?, price=?, status=?, description=?
        WHERE id=?
    ''', (d.get('name'), d.get('category'), d.get('duration_minutes'), d.get('need_equipment', 0), d.get('equipment_type'), d.get('price'), d.get('status', 'enabled'), d.get('description'), pid))
    conn.commit()
    conn.close()
    return jsonify({'message': '项目更新成功'})


@bp.route('/api/staff', methods=['GET'])
def api_staff_list():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM staff ORDER BY id DESC')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@bp.route('/api/staff/available', methods=['GET'])
def api_staff_available():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM staff WHERE status='available' ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@bp.route('/api/staff', methods=['POST'])
def api_staff_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO staff (name, role, phone, status, notes) VALUES (?,?,?,?,?)',
              (d.get('name'), d.get('role'), d.get('phone'), d.get('status', 'available'), d.get('notes')))
    conn.commit()
    sid = c.lastrowid
    conn.close()
    return jsonify({'id': sid, 'message': '服务人员创建成功'}), 201


@bp.route('/api/staff/<int:sid>', methods=['PUT'])
def api_staff_update(sid):
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE staff SET name=?, role=?, phone=?, status=?, notes=? WHERE id=?',
              (d.get('name'), d.get('role'), d.get('phone'), d.get('status', 'available'), d.get('notes'), sid))
    conn.commit()
    conn.close()
    return jsonify({'message': '服务人员更新成功'})


@bp.route('/api/device-management/appointment-items', methods=['GET'])
def api_device_management_appointment_items():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT pem.id,
               pem.project_name,
               pem.equipment_name,
               COALESCE(e.status, 'available') AS equipment_status,
               COALESCE(e.location, '') AS equipment_location,
               COALESCE(e.description, '') AS equipment_description,
               COALESCE(pem.created_at, e.created_at) AS created_at
          FROM project_equipment_mapping pem
          LEFT JOIN equipment e ON e.name = pem.equipment_name
         WHERE pem.status='enabled'
         ORDER BY pem.id DESC
        '''
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(rows)


@bp.route('/api/device-management/appointment-items', methods=['POST'])
def api_device_management_appointment_items_create():
    d = request.json or {}
    project_name = str(d.get('project_name') or '').strip()
    equipment_name = str(d.get('equipment_name') or '').strip()
    equipment_status = str(d.get('equipment_status') or 'available').strip()
    equipment_location = str(d.get('equipment_location') or '').strip()
    equipment_description = str(d.get('equipment_description') or '').strip()
    if not project_name or not equipment_name:
        return error_response('项目名称和设备名称为必填项')
    if equipment_status not in {'available', 'maintenance'}:
        return error_response('设备状态不合法')

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM therapy_projects WHERE name=?", (project_name,))
    project_row = c.fetchone()
    if not project_row:
        c.execute(
            '''
            INSERT INTO therapy_projects
            (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
            VALUES (?,?,?,?,?,?,?,?)
            ''',
            (project_name, '理疗', 30, 1, '专用设备', 0, 'enabled', f'{project_name}服务项目'),
        )
        project_id = c.lastrowid
    else:
        project_id = project_row['id']
        c.execute(
            '''
            UPDATE therapy_projects
               SET need_equipment=1, equipment_type='专用设备', status='enabled'
             WHERE id=?
            ''',
            (project_id,),
        )
    c.execute('''
        INSERT OR IGNORE INTO project_rules (project_name, allow_home, project_category, status)
        VALUES (?,?,?,?)
    ''', (project_name, 0, '理疗', 'enabled'))

    c.execute("SELECT id FROM equipment WHERE name=?", (equipment_name,))
    equipment_row = c.fetchone()
    if equipment_row:
        c.execute(
            "UPDATE equipment SET status=?, type='专用设备', location=?, description=? WHERE id=?",
            (equipment_status, equipment_location, equipment_description, equipment_row['id']),
        )
    else:
        c.execute(
            '''
            INSERT INTO equipment (name, type, model, location, status, description)
            VALUES (?,?,?,?,?,?)
            ''',
            (
                equipment_name,
                '专用设备',
                '',
                equipment_location,
                equipment_status,
                equipment_description or f'{project_name}预约设备',
            ),
        )
    c.execute(
        '''
        INSERT OR IGNORE INTO project_equipment_mapping (project_name, equipment_name, status)
        VALUES (?,?,?)
        ''',
        (project_name, equipment_name, 'enabled'),
    )
    conn.commit()
    conn.close()
    return success_response({'project_id': project_id}, '预约服务项目已保存', 201)


@bp.route('/api/device-management/appointment-items/<int:item_id>', methods=['PUT'])
def api_device_management_appointment_items_update(item_id):
    d = request.json or {}
    project_name = str(d.get('project_name') or '').strip()
    equipment_name = str(d.get('equipment_name') or '').strip()
    equipment_status = str(d.get('equipment_status') or 'available').strip()
    equipment_location = str(d.get('equipment_location') or '').strip()
    equipment_description = str(d.get('equipment_description') or '').strip()
    if not project_name or not equipment_name:
        return error_response('项目名称和设备名称为必填项')
    if equipment_status not in {'available', 'maintenance'}:
        return error_response('设备状态不合法')

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM project_equipment_mapping WHERE id=?', (item_id,))
    old_mapping = c.fetchone()
    if not old_mapping:
        conn.close()
        return error_response('记录不存在', 404, 'NOT_FOUND')

    c.execute("SELECT id FROM therapy_projects WHERE name=?", (project_name,))
    if not c.fetchone():
        c.execute(
            '''
            INSERT INTO therapy_projects
            (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
            VALUES (?,?,?,?,?,?,?,?)
            ''',
            (project_name, '理疗', 30, 1, '专用设备', 0, 'enabled', f'{project_name}服务项目'),
        )
    c.execute(
        '''
        UPDATE therapy_projects
           SET need_equipment=1, equipment_type='专用设备', status='enabled'
         WHERE name=?
        ''',
        (project_name,),
    )
    c.execute('''
        INSERT OR IGNORE INTO project_rules (project_name, allow_home, project_category, status)
        VALUES (?,?,?,?)
    ''', (project_name, 0, '理疗', 'enabled'))

    c.execute("SELECT id FROM equipment WHERE name=?", (old_mapping['equipment_name'],))
    old_equipment = c.fetchone()
    if old_equipment:
        c.execute(
            "UPDATE equipment SET name=?, status=?, type='专用设备', location=?, description=? WHERE id=?",
            (equipment_name, equipment_status, equipment_location, equipment_description, old_equipment['id']),
        )
    else:
        c.execute(
            '''
            INSERT INTO equipment (name, type, model, location, status, description)
            VALUES (?,?,?,?,?,?)
            ''',
            (
                equipment_name,
                '专用设备',
                '',
                equipment_location,
                equipment_status,
                equipment_description or f'{project_name}预约设备',
            ),
        )

    c.execute(
        '''
        UPDATE project_equipment_mapping
           SET project_name=?, equipment_name=?, status='enabled', updated_at=?
         WHERE id=?
        ''',
        (project_name, equipment_name, now_local_str(), item_id),
    )
    conn.commit()
    conn.close()
    return success_response({'id': item_id}, '预约服务项目已更新')


@bp.route('/api/device-management/home-items', methods=['GET'])
def api_device_management_home_items():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT psm.id,
               psm.project_name,
               s.name AS staff_name,
               psm.created_at
          FROM project_staff_mapping psm
          LEFT JOIN staff s ON s.id = psm.staff_id
         WHERE psm.status='enabled'
         ORDER BY psm.id DESC
        '''
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(rows)


@bp.route('/api/device-management/home-items', methods=['POST'])
def api_device_management_home_items_create():
    d = request.json or {}
    project_name = str(d.get('project_name') or '').strip()
    staff_name = str(d.get('staff_name') or '').strip()
    if not project_name or not staff_name:
        return error_response('项目名称和项目服务人员为必填项')
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM therapy_projects WHERE name=?", (project_name,))
    if not c.fetchone():
        c.execute(
            '''
            INSERT INTO therapy_projects
            (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
            VALUES (?,?,?,?,?,?,?,?)
            ''',
            (project_name, '上门', 30, 0, None, 0, 'enabled', f'{project_name}上门项目'),
        )
    c.execute('''
        INSERT OR REPLACE INTO project_rules (project_name, allow_home, project_category, status, updated_at)
        VALUES (?,?,?,?,?)
    ''', (project_name, 1, '上门', 'enabled', now_local_str()))

    c.execute("SELECT id FROM staff WHERE name=?", (staff_name,))
    staff = c.fetchone()
    if staff:
        staff_id = staff['id']
        c.execute("UPDATE staff SET status='available' WHERE id=?", (staff_id,))
    else:
        c.execute(
            "INSERT INTO staff (name, role, phone, status, notes) VALUES (?,?,?,?,?)",
            (staff_name, '上门服务人员', '', 'available', ''),
        )
        staff_id = c.lastrowid
    c.execute(
        '''
        INSERT OR IGNORE INTO project_staff_mapping (project_name, staff_id, status)
        VALUES (?,?,?)
        ''',
        (project_name, staff_id, 'enabled'),
    )
    conn.commit()
    conn.close()
    return success_response({'staff_id': staff_id}, '上门项目已保存', 201)


@bp.route('/api/device-management/home-items/<int:item_id>', methods=['PUT'])
def api_device_management_home_items_update(item_id):
    d = request.json or {}
    project_name = str(d.get('project_name') or '').strip()
    staff_name = str(d.get('staff_name') or '').strip()
    if not project_name or not staff_name:
        return error_response('项目名称和项目服务人员为必填项')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM project_staff_mapping WHERE id=?', (item_id,))
    old = c.fetchone()
    if not old:
        conn.close()
        return error_response('记录不存在', 404, 'NOT_FOUND')
    c.execute("SELECT id FROM staff WHERE name=?", (staff_name,))
    staff = c.fetchone()
    if staff:
        staff_id = staff['id']
    else:
        c.execute(
            "INSERT INTO staff (name, role, phone, status, notes) VALUES (?,?,?,?,?)",
            (staff_name, '上门服务人员', '', 'available', ''),
        )
        staff_id = c.lastrowid

    c.execute(
        '''
        UPDATE project_staff_mapping
           SET project_name=?, staff_id=?, status='enabled', updated_at=?
         WHERE id=?
        ''',
        (project_name, staff_id, now_local_str(), item_id),
    )
    c.execute(
        '''
        INSERT OR IGNORE INTO therapy_projects
        (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
        VALUES (?,?,?,?,?,?,?,?)
        ''',
        (project_name, '上门', 30, 0, None, 0, 'enabled', f'{project_name}上门项目'),
    )
    c.execute('''
        INSERT OR REPLACE INTO project_rules (project_name, allow_home, project_category, status, updated_at)
        VALUES (?,?,?,?,?)
    ''', (project_name, 1, '上门', 'enabled', now_local_str()))
    conn.commit()
    conn.close()
    return success_response({'id': item_id}, '上门项目已更新')


# ========== 健康评估 ==========
