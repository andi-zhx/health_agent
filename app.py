"""医疗客户与健康档案管理系统 - 模块化入口。"""

import os
from flask import Flask

from backend.core import BASE_DIR, init_db, register_core_hooks, create_db_backup, now_local
from backend.runtime import load_secret_key
from backend.api.auth import bp as auth_bp
from backend.api.customers import bp as customers_bp
from backend.api.health_assessments import bp as health_assessments_bp
from backend.api.appointments import bp as appointments_bp
from backend.api.home_appointments import bp as home_appointments_bp
from backend.api.improvement_records import bp as improvement_records_bp
from backend.api.dashboard import bp as dashboard_bp
from backend.api.system import bp as system_bp
from backend.api.system_misc import bp as system_misc_bp
from backend.api.export import bp as export_bp
from backend.api.audit_logs import bp as audit_logs_bp


def create_app():
    app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'))
    app.config['SECRET_KEY'] = load_secret_key()
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    now_local()  # Fail early if the configured timezone cannot be loaded.
    init_db()

    register_core_hooks(app)

    app.register_blueprint(system_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(system_misc_bp)
    app.register_blueprint(health_assessments_bp)
    app.register_blueprint(improvement_records_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(home_appointments_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(audit_logs_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(dashboard_bp)

    return app


app = create_app()


if __name__ == '__main__':
    port = int(os.environ.get('APP_PORT', '5000'))
    print('请在浏览器打开: http://127.0.0.1:%s' % port)
    app.run(host='127.0.0.1', port=port, debug=False)
