from flask import Blueprint, current_app
from backend.core import *

bp = Blueprint('system', __name__)

@bp.route('/')
def index():
    return send_from_directory(current_app.static_folder, 'index.html')


@bp.route('/<path:path>')
def static_file(path):
    return send_from_directory(current_app.static_folder, path)


# ========== 客户 ==========
@bp.route('/api/tasks/checkin-auto-no-show', methods=['POST'])
def api_task_checkin_auto_no_show():
    payload = request.json or {}
    now_ts = now_local_str()
    task_date = str(payload.get('task_date') or now_ts[:10]).strip()
    if not is_valid_date(task_date):
        return error_response('task_date 格式必须为 YYYY-MM-DD')
    operator = session.get('username', 'system')
    operator_ip = get_request_ip()

    conn = get_db()
    c = conn.cursor()
    affected_total = 0
    detail_rows = []
    for table_name, module_name in (('appointments', 'appointments'), ('home_appointments', 'home_appointments')):
        c.execute(
            f'''
            SELECT id
            FROM {table_name}
            WHERE appointment_date=?
              AND status='scheduled'
              AND COALESCE(checkin_status, 'pending')='pending'
            ''',
            (task_date,),
        )
        ids = [r['id'] for r in c.fetchall()]
        if not ids:
            detail_rows.append(f'{module_name}:0')
            continue
        ph = ','.join('?' * len(ids))
        c.execute(
            f'''
            UPDATE {table_name}
            SET checkin_status='no_show', checkin_updated_at=?, checkin_updated_by=?, checkin_updated_ip=?, updated_at=?
            WHERE id IN ({ph})
            ''',
            [now_ts, operator, operator_ip, now_ts] + ids,
        )
        for rid in ids:
            insert_business_history_log(
                c,
                module_name,
                rid,
                'checkin_auto_no_show',
                '签到状态:待签到',
                '签到状态:爽约（系统自动流转）',
            )
        affected_total += len(ids)
        detail_rows.append(f'{module_name}:{len(ids)}')

    c.execute(
        '''
        INSERT INTO task_execution_logs (task_name, task_date, affected_rows, details, executed_by, executed_ip)
        VALUES (?,?,?,?,?,?)
        ''',
        ('checkin_auto_no_show', task_date, affected_total, '；'.join(detail_rows), operator, operator_ip),
    )
    conn.commit()
    conn.close()
    return success_response({'task_date': task_date, 'affected_rows': affected_total, 'details': detail_rows}, '自动流转执行完成')


@bp.route('/api/business-history/<module>/<int:target_id>', methods=['GET'])
def api_business_history(module, target_id):
    if module not in ('appointments', 'home_appointments'):
        return error_response('不支持的业务模块', 400, 'INVALID_MODULE')
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT
            l.*,
            MAX(CASE WHEN l2.action_type='update' THEN l2.created_at END) AS modified_time,
            MAX(CASE WHEN l2.action_type='cancel' THEN l2.created_at END) AS cancelled_time
        FROM business_history_logs l
        LEFT JOIN business_history_logs l2
          ON l.module=l2.module AND l.target_id=l2.target_id
        WHERE l.module=? AND l.target_id=?
        GROUP BY l.id
        ORDER BY l.created_at DESC, l.id DESC
        ''',
        (module, target_id),
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(rows)


@bp.route('/api/search', methods=['GET'])
def api_search():
    q = (request.args.get('q') or '').strip()
    kind = request.args.get('type', 'all')
    if not q and kind == 'all':
        return jsonify({'customers': [], 'health_records': [], 'appointments': [], 'visit_checkins': []})

    conn = get_db()
    c = conn.cursor()
    like = f'%{q}%'
    result = {}

    if kind in ('all', 'customers'):
        c.execute('SELECT * FROM customers WHERE is_deleted=0 AND (name LIKE ? OR id_card LIKE ? OR phone LIKE ? OR address LIKE ?) ORDER BY created_at DESC LIMIT 100',
                  (like, like, like, like))
        result['customers'] = row_list(c.fetchall())

    if kind in ('all', 'health'):
        c.execute('SELECT h.*, c.name as customer_name FROM health_assessments h JOIN customers c ON h.customer_id=c.id WHERE c.name LIKE ? OR c.id_card LIKE ? OR c.phone LIKE ? OR h.notes LIKE ? ORDER BY h.assessment_date DESC LIMIT 100',
                  (like, like, like, like))
        result['health_records'] = row_list(c.fetchall())

    if kind in ('all', 'appointments'):
        c.execute('''SELECT a.*, c.name as customer_name, c.phone as customer_phone, e.name as equipment_name
            FROM appointments a JOIN customers c ON a.customer_id=c.id LEFT JOIN equipment e ON a.equipment_id=e.id
            WHERE c.name LIKE ? OR c.id_card LIKE ? OR c.phone LIKE ? OR a.notes LIKE ?
            ORDER BY a.appointment_date DESC, a.start_time DESC LIMIT 100''', (like, like, like, like))
        result['appointments'] = row_list(c.fetchall())

    if kind in ('all', 'checkins'):
        c.execute('SELECT v.*, c.name as customer_name FROM visit_checkins v JOIN customers c ON v.customer_id=c.id WHERE c.name LIKE ? OR c.id_card LIKE ? OR c.phone LIKE ? OR v.purpose LIKE ? OR v.notes LIKE ? ORDER BY v.checkin_time DESC LIMIT 100',
                  (like, like, like, like, like))
        result['visit_checkins'] = row_list(c.fetchall())

    for key in ('customers', 'health_records', 'appointments', 'visit_checkins'):
        if key not in result:
            result[key] = []

    conn.close()
    return jsonify(result)


@bp.route('/api/system/backup-path', methods=['GET'])
def api_system_backup_path_get():
    path = get_backup_directory()
    return jsonify({'backup_directory': path})


@bp.route('/api/system/backup-path', methods=['POST'])
def api_system_backup_path_set():
    body = request.get_json(silent=True) or {}
    backup_directory = (body.get('backup_directory') or '').strip()
    if not backup_directory:
        return jsonify({'error': '请先选择备份路径'}), 400

    backup_directory = os.path.abspath(os.path.expanduser(backup_directory))
    try:
        os.makedirs(backup_directory, exist_ok=True)
    except Exception as e:
        return jsonify({'error': f'备份路径不可用: {e}'}), 400

    set_setting_value('backup_directory', backup_directory)
    return jsonify({'message': '备份路径已保存', 'backup_directory': backup_directory})


@bp.route('/api/system/backup-path/select', methods=['POST'])
def api_system_backup_path_select():
    if tk is None or filedialog is None:
        return jsonify({'error': '当前环境不支持本地路径选择框，请手动输入路径'}), 400
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        selected = filedialog.askdirectory(title='请选择数据库备份路径')
        root.destroy()
    except Exception as e:
        return jsonify({'error': f'打开路径选择框失败: {e}'}), 500

    if not selected:
        return jsonify({'error': '未选择路径'}), 400

    backup_directory = os.path.abspath(os.path.expanduser(selected))
    try:
        os.makedirs(backup_directory, exist_ok=True)
    except Exception as e:
        return jsonify({'error': f'备份路径不可用: {e}'}), 400

    set_setting_value('backup_directory', backup_directory)
    return jsonify({'message': '备份路径已更新', 'backup_directory': backup_directory})


@bp.route('/api/system/backup', methods=['POST'])
def api_system_backup():
    body = request.get_json(silent=True) or {}
    backup_directory = (body.get('backup_directory') or '').strip()
    if backup_directory:
        backup_directory = os.path.abspath(os.path.expanduser(backup_directory))
        try:
            os.makedirs(backup_directory, exist_ok=True)
        except Exception as e:
            return jsonify({'error': f'备份路径不可用: {e}'}), 400
        set_setting_value('backup_directory', backup_directory)

    result = create_db_backup(backup_type='manual')
    if result.get('status') == 'success':
        audit_log('备份数据库', 'system', result.get('filename'), result.get('backup_file'))
    code = 200 if result.get('status') == 'success' else 500
    return jsonify(result), code


@bp.route('/api/system/backups', methods=['GET'])
def api_system_backups():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM db_backups ORDER BY backup_time DESC, id DESC LIMIT 200')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@bp.route('/api/system/restore', methods=['POST'])
def api_system_restore():
    body = request.get_json(silent=True) or {}
    backup_file = (body.get('backup_file') or '').strip()
    if not backup_file:
        return jsonify({'error': '请选择要恢复的备份文件'}), 400

    result = restore_db_from_backup(backup_file)
    if result.get('status') == 'success':
        audit_log('恢复数据库', 'system', backup_file, 'restore success')
        return jsonify({
            'status': 'success',
            'message': '恢复成功，请重启系统以确保所有模块使用最新数据',
            'need_restart': True,
        })
    return jsonify(result), 500


@bp.route('/api/download/<filename>', methods=['GET'])
def api_download(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)
