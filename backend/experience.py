"""Additive fields for self-reported service experience and follow-up."""
from datetime import datetime

EXPERIENCE_DIMENSIONS = ('疼痛影响', '疲劳感', '睡眠困扰', '活动不便', '听力沟通困扰', '其他不适')
EXPERIENCE_COLUMNS = {
    'experience_dimension': 'TEXT', 'before_score': 'INTEGER', 'after_score': 'INTEGER',
    'satisfaction_score': 'INTEGER', 'adverse_event': "TEXT DEFAULT '未询问'", 'adverse_notes': 'TEXT',
    'followup_status': "TEXT DEFAULT '待回访'", 'followup_completed_at': 'TEXT', 'followup_notes': 'TEXT',
}


def ensure_experience_columns(cursor):
    existing = {row[1] for row in cursor.execute('PRAGMA table_info(service_improvement_records)')}
    for name, kind in EXPERIENCE_COLUMNS.items():
        if name not in existing:
            cursor.execute(f'ALTER TABLE service_improvement_records ADD COLUMN {name} {kind}')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_experience_followup ON service_improvement_records(followup_status, followup_date)')


def experience_values(payload, existing=None):
    """Validate new fields without clearing them when a legacy client omits them."""
    values = dict(existing or {})
    for name in EXPERIENCE_COLUMNS:
        if name in payload:
            values[name] = payload[name]
    result = {name: values.get(name) for name in EXPERIENCE_COLUMNS}
    for name, maximum in [('before_score', 10), ('after_score', 10), ('satisfaction_score', 5)]:
        value = result[name]
        if value in (None, ''):
            result[name] = None
            continue
        minimum = 1 if name == 'satisfaction_score' else 0
        try:
            number = float(value)
            if isinstance(value, bool) or not number.is_integer() or not minimum <= number <= maximum:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f'{name} 必须为 {minimum}–{maximum} 的整数')
        result[name] = int(number)
    if (result['before_score'] is None) != (result['after_score'] is None):
        raise ValueError('体验前、后评分需要成对填写，也可以同时留空')
    dimension = str(result['experience_dimension'] or '').strip()
    if dimension and dimension not in EXPERIENCE_DIMENSIONS:
        raise ValueError('请选择有效的体验评价维度')
    if result['before_score'] is not None and not dimension:
        raise ValueError('填写评分时需要选择评价维度')
    result['experience_dimension'] = dimension
    result['adverse_event'] = result['adverse_event'] or '未询问'
    result['followup_status'] = result['followup_status'] or '待回访'
    if result['adverse_event'] not in ('未询问', '无不适', '有不适'):
        raise ValueError('不适反馈选项不合法')
    if result['followup_status'] not in ('待回访', '已回访', '无需回访'):
        raise ValueError('回访状态不合法')
    for name in ('adverse_notes', 'followup_notes'):
        result[name] = str(result[name] or '').strip()
        if len(result[name]) > 2000:
            raise ValueError('反馈说明不能超过 2000 字')
    if result['adverse_event'] == '有不适' and not result['adverse_notes']:
        raise ValueError('请补充不适表现与处理情况')
    if result['followup_status'] == '已回访':
        if not result['followup_notes'] or not result['followup_completed_at']:
            raise ValueError('完成回访需要填写回访时间与结果')
        try:
            completed = datetime.fromisoformat(str(result['followup_completed_at']))
        except ValueError:
            raise ValueError('回访时间格式不正确')
        from backend.core import now_local
        local_now = now_local()
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=local_now.tzinfo)
        if completed > local_now:
            raise ValueError('实际回访时间不能晚于当前时间')
        result['followup_completed_at'] = completed.astimezone(local_now.tzinfo).strftime('%Y-%m-%d %H:%M:%S')
    else:
        result['followup_completed_at'] = None
    return result


def save_experience(cursor, record_id, values):
    names = list(EXPERIENCE_COLUMNS)
    cursor.execute('UPDATE service_improvement_records SET ' + ', '.join(name + '=?' for name in names) + ' WHERE id=?',
                   [values[name] for name in names] + [record_id])
