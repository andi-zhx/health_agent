from flask import Blueprint
from backend.core import *

bp = Blueprint('auth', __name__)

@bp.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    data = request.json or {}
    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '').strip()
    config_user = get_setting_value('login_username', 'admin')
    password_hash = get_setting_value('password_hash', '')

    login_ok = False
    if username == config_user and password_hash:
        login_ok = check_password_hash(password_hash, password)
    elif verify_legacy_plaintext_and_migrate(username, password):
        # 兼容旧库明文配置：首次成功后自动转为 hash，后续统一走 hash 校验。
        login_ok = True

    if login_ok:
        session['logged_in'] = True
        session['username'] = username
        audit_log('登录', 'auth', username, '登录成功')
        return jsonify({'message': '登录成功'})
    return jsonify({'error': '账号或密码错误'}), 401


@bp.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    username = session.get('username', 'anonymous')
    audit_log('退出登录', 'auth', username, 'logout')
    session.clear()
    return jsonify({'message': '已退出登录'})


