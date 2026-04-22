from flask import Blueprint
from backend.core import *

bp = Blueprint('customers', __name__)

@bp.route('/api/customers', methods=['GET'])
def api_customers_list():
    q = (request.args.get('search', '') or '').strip()
    status = (request.args.get('status', '') or '').strip().lower()
    date_from = (request.args.get('date_from', '') or '').strip()
    date_to = (request.args.get('date_to', '') or '').strip()
    sort_by = (request.args.get('sort_by', '') or 'created_desc').strip()
    page, page_size, offset = parse_list_params()
    sort_map = {
        'created_desc': 'created_at DESC, id DESC',
        'created_asc': 'created_at ASC, id ASC',
        'name_asc': 'name COLLATE NOCASE ASC, id DESC',
        'name_desc': 'name COLLATE NOCASE DESC, id DESC',
    }
    order_sql = sort_map.get(sort_by, sort_map['created_desc'])
    conn = get_db()
    c = conn.cursor()
    conditions = ['is_deleted=0']
    params = []
    if q:
        conditions.append('(name LIKE ? OR id_card LIKE ? OR phone LIKE ?)')
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%'])
    if status == 'deleted':
        conditions = ['is_deleted=1']
    elif status == 'active':
        conditions.append('is_deleted=0')
    if date_from:
        conditions.append('date(created_at) >= date(?)')
        params.append(date_from)
    if date_to:
        conditions.append('date(created_at) <= date(?)')
        params.append(date_to)
    where_sql = ' AND '.join(conditions)
    c.execute(f'SELECT COUNT(*) as n FROM customers WHERE {where_sql}', params)
    total = c.fetchone()['n']
    c.execute(f"SELECT c.* FROM customers c WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?", params + [page_size, offset])
    rows = row_list(c.fetchall())
    rows = [hydrate_customer_age(row) for row in rows]
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


@bp.route('/api/customers/history-view', methods=['GET'])
def api_customers_history_view():
    q = (request.args.get('search', '') or '').strip()
    page, page_size, offset = parse_list_params()
    conn = get_db()
    c = conn.cursor()
    where_sql = '''
        c.is_deleted=0
        AND EXISTS (SELECT 1 FROM health_assessments h WHERE h.customer_id = c.id)
    '''
    params = []
    if q:
        where_sql += ' AND (c.name LIKE ? OR c.phone LIKE ? OR c.id_card LIKE ?)'
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%'])
    c.execute(f'SELECT COUNT(*) as n FROM customers c WHERE {where_sql}', params)
    total = c.fetchone()['n']
    c.execute(
        f'''
        SELECT c.id, c.name, c.age, c.birth_date, c.identity_type, c.phone, c.created_at
        FROM customers c
        WHERE {where_sql}
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ? OFFSET ?
        ''',
        params + [page_size, offset]
    )
    rows = row_list(c.fetchall())
    rows = [hydrate_customer_age(row) for row in rows]
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


@bp.route('/api/customers/<int:cid>', methods=['GET'])
def api_customer_get(cid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM customers WHERE id = ? AND is_deleted=0', (cid,))
    row = c.fetchone()
    if not row:
        conn.close()
        return error_response('客户不存在', 404, 'NOT_FOUND')
    cust = dict(row)
    hydrate_customer_age(cust)
    c.execute(
        'SELECT a.*, e.name as equipment_name FROM appointments a LEFT JOIN equipment e ON a.equipment_id=e.id WHERE a.customer_id=? ORDER BY a.appointment_date DESC, a.start_time DESC',
        (cid,)
    )
    cust['appointments'] = row_list(c.fetchall())
    cust['usage_records'] = []
    c.execute('SELECT * FROM health_records WHERE customer_id=? ORDER BY record_date DESC, id DESC', (cid,))
    cust['health_records'] = row_list(c.fetchall())
    c.execute('SELECT * FROM visit_checkins WHERE customer_id=? ORDER BY checkin_time DESC, id DESC', (cid,))
    cust['visit_checkins'] = row_list(c.fetchall())
    conn.close()
    return success_response(cust)


@bp.route('/api/customers', methods=['POST'])
def api_customer_create():
    d = request.json or {}
    customer_error = validate_customer_payload(d)
    if customer_error:
        return error_response(customer_error)
    identity_type = d.get('identity_type')
    if isinstance(identity_type, list):
        identity_type = '、'.join([str(x).strip() for x in identity_type if str(x).strip()])
    else:
        identity_type = str(identity_type or '').strip()
    conn = get_db()
    c = conn.cursor()
    try:
        age = calculate_age_by_birth_year(d.get('birth_date'))
        ts = now_local_str()
        c.execute('''
            INSERT INTO customers (name, id_card, phone, address, gender, age, birth_date, identity_type, military_rank, record_creator, medical_history, allergies, diet_habits, chronic_diseases, health_status, therapy_contraindications, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            d.get('name'), (str(d.get('id_card') or '').strip().upper() or None), d.get('phone'), d.get('address'),
            d.get('gender'), age, d.get('birth_date'), identity_type, d.get('military_rank'), d.get('record_creator'),
            d.get('medical_history'), d.get('allergies'), d.get('diet_habits'), d.get('chronic_diseases'),
            d.get('health_status'), d.get('therapy_contraindications'), ts, ts
        ))
        conn.commit()
        id = c.lastrowid
        conn.close()
        audit_log('创建客户', 'customers', id, d.get('name') or '')
        return success_response({'id': id}, '客户创建成功', 201)
    except sqlite3.IntegrityError:
        conn.close()
        return error_response('身份证号已存在')


@bp.route('/api/customers/<int:cid>', methods=['PUT'])
def api_customer_update(cid):
    d = request.json or {}
    customer_error = validate_customer_payload(d)
    if customer_error:
        return error_response(customer_error)
    identity_type = d.get('identity_type')
    if isinstance(identity_type, list):
        identity_type = '、'.join([str(x).strip() for x in identity_type if str(x).strip()])
    else:
        identity_type = str(identity_type or '').strip()
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM customers WHERE id=? AND is_deleted=0', (cid,))
    if not c.fetchone():
        conn.close()
        return error_response('客户不存在', 404, 'NOT_FOUND')
    c.execute('''
        UPDATE customers SET name=?, id_card=?, phone=?, address=?, gender=?, age=?, birth_date=?, identity_type=?, military_rank=?, record_creator=?, medical_history=?, allergies=?, diet_habits=?, chronic_diseases=?, health_status=?, therapy_contraindications=?, updated_at=? WHERE id=?
    ''', (
        d.get('name'), (str(d.get('id_card') or '').strip().upper() or None), d.get('phone'), d.get('address'),
        d.get('gender'), calculate_age_by_birth_year(d.get('birth_date')), d.get('birth_date'), identity_type, d.get('military_rank'), d.get('record_creator'),
        d.get('medical_history'), d.get('allergies'), d.get('diet_habits'), d.get('chronic_diseases'),
        d.get('health_status'), d.get('therapy_contraindications'), now_local_str(), cid
    ))
    conn.commit()
    conn.close()
    audit_log('修改客户', 'customers', cid, d.get('name') or '')
    return success_response({'id': cid}, '更新成功')


@bp.route('/api/customers/<int:cid>', methods=['DELETE'])
def api_customer_delete(cid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM customers WHERE id=? AND is_deleted=0', (cid,))
    if not c.fetchone():
        conn.close()
        return error_response('客户不存在', 404, 'NOT_FOUND')

    c.execute("UPDATE customers SET is_deleted=1, updated_at=? WHERE id=?", (now_local_str(), cid))
    conn.commit()
    conn.close()
    audit_log('删除客户', 'customers', cid, '软删除客户')
    return success_response({'id': cid}, '已删除')

