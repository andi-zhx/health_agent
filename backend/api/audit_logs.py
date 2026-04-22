from flask import Blueprint
from backend.core import *

bp = Blueprint('audit_logs', __name__)

@bp.route('/api/audit-logs', methods=['GET'])
def api_audit_logs():
    page, page_size, offset = parse_list_params(default_page_size=20, max_page_size=200)
    start_time = (request.args.get('start_time') or '').strip()
    end_time = (request.args.get('end_time') or '').strip()
    operator = (request.args.get('operator') or '').strip()
    module = (request.args.get('module') or '').strip()
    action = (request.args.get('action') or '').strip()
    keyword = (request.args.get('keyword') or '').strip()

    conditions = ['1=1']
    params = []
    if start_time:
        conditions.append('created_at >= ?')
        params.append(start_time + ' 00:00:00')
    if end_time:
        conditions.append('created_at <= ?')
        params.append(end_time + ' 23:59:59')
    if operator:
        conditions.append('username LIKE ?')
        params.append(f'%{operator}%')
    if module:
        conditions.append('module LIKE ?')
        params.append(f'%{module}%')
    if action:
        conditions.append('action LIKE ?')
        params.append(f'%{action}%')
    if keyword:
        conditions.append('(target_id LIKE ? OR details LIKE ?)')
        params.extend([f'%{keyword}%', f'%{keyword}%'])

    where_sql = ' WHERE ' + ' AND '.join(conditions)
    conn = get_db()
    c = conn.cursor()
    c.execute(f'SELECT COUNT(*) AS n FROM audit_logs {where_sql}', params)
    total = c.fetchone()['n']
    c.execute(
        f'''
        SELECT id, created_at, username, module, action, target_id, details
        FROM audit_logs
        {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        ''',
        params + [page_size, offset],
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


# ========== 综合查询 ==========
