#!/usr/bin/env python3
"""清理旧业务数据并生成50位客户全链路样本数据。"""

import random
import sqlite3
from datetime import datetime, timedelta

from backend.core import DB_PATH, init_db, now_local

SAMPLE_CUSTOMER_COUNT = 50
RANDOM_SEED = 20260415


LAST_NAMES = [
    '赵', '钱', '孙', '李', '周', '吴', '郑', '王', '冯', '陈',
    '褚', '卫', '蒋', '沈', '韩', '杨', '朱', '秦', '尤', '许',
]
FIRST_NAMES = [
    '建国', '丽华', '文静', '国强', '海燕', '志远', '秀兰', '晨曦', '明辉', '嘉怡',
    '宇航', '欣妍', '振华', '思敏', '天宇', '若琳', '东升', '可心', '宏伟', '雅雯',
]

HEALTH_PROFILES = [
    {
        'profile': '代谢综合征干预',
        'medical_history': '2型糖尿病、脂肪肝',
        'chronic_disease': '糖尿病',
        'family_history': '父亲糖尿病',
        'health_status': '需重点管理',
        'symptom': '餐后乏力',
        'symptom_detail': '午后困倦明显，餐后血糖波动',
        'life_impact': '工作时注意力下降',
        'blood_pressure': '偏高',
        'blood_lipid': '偏高',
        'blood_sugar': '明显升高',
        'pain_detail': '双下肢酸胀',
        'health_need': '血糖控制',
    },
    {
        'profile': '心脑血管风险',
        'medical_history': '高血压病史5年',
        'chronic_disease': '高血压',
        'family_history': '母亲高血压',
        'health_status': '需持续随访',
        'symptom': '头晕头痛',
        'symptom_detail': '情绪紧张时头痛加重',
        'life_impact': '影响夜间休息',
        'blood_pressure': '偏高',
        'blood_lipid': '边缘偏高',
        'blood_sugar': '正常',
        'pain_detail': '颈后紧绷',
        'health_need': '稳定血压',
    },
    {
        'profile': '骨关节慢痛',
        'medical_history': '膝骨关节炎、腰椎间盘突出',
        'chronic_disease': '骨关节炎',
        'family_history': '无明显家族史',
        'health_status': '康复期',
        'symptom': '关节疼痛',
        'symptom_detail': '上下楼梯膝关节疼痛明显',
        'life_impact': '步行距离下降',
        'blood_pressure': '正常',
        'blood_lipid': '正常',
        'blood_sugar': '正常',
        'pain_detail': '膝关节压痛、腰骶部压痛',
        'health_need': '缓解疼痛',
    },
    {
        'profile': '呼吸系统慢病',
        'medical_history': '慢性阻塞性肺疾病',
        'chronic_disease': '慢阻肺',
        'family_history': '父亲慢性支气管炎',
        'health_status': '需关注',
        'symptom': '气短咳嗽',
        'symptom_detail': '晨起咳嗽伴少量白痰',
        'life_impact': '爬楼后呼吸困难',
        'blood_pressure': '正常',
        'blood_lipid': '边缘偏高',
        'blood_sugar': '正常',
        'pain_detail': '胸背部肌群紧张',
        'health_need': '提升心肺耐力',
    },
    {
        'profile': '神经睡眠障碍',
        'medical_history': '长期失眠、焦虑状态',
        'chronic_disease': '睡眠障碍',
        'family_history': '无明显家族史',
        'health_status': '需心理支持',
        'symptom': '入睡困难',
        'symptom_detail': '凌晨易醒，睡眠浅',
        'life_impact': '白天精神不集中',
        'blood_pressure': '正常',
        'blood_lipid': '正常',
        'blood_sugar': '轻度偏高',
        'pain_detail': '颈肩部肌肉紧张',
        'health_need': '改善睡眠',
    },
    {
        'profile': '消化系统亚健康',
        'medical_history': '慢性胃炎、反流性食管炎',
        'chronic_disease': '慢性胃炎',
        'family_history': '母亲胃病史',
        'health_status': '稳定',
        'symptom': '胃胀反酸',
        'symptom_detail': '晚餐后反酸、腹胀',
        'life_impact': '影响进食与社交',
        'blood_pressure': '正常',
        'blood_lipid': '正常',
        'blood_sugar': '正常',
        'pain_detail': '上腹部不适感',
        'health_need': '改善消化功能',
    },
    {
        'profile': '肿瘤术后康复',
        'medical_history': '乳腺肿瘤术后康复期',
        'chronic_disease': '肿瘤术后状态',
        'family_history': '姑妈乳腺肿瘤史',
        'health_status': '需重点管理',
        'symptom': '术侧上肢活动受限',
        'symptom_detail': '上举时牵拉痛',
        'life_impact': '穿衣与家务受限',
        'blood_pressure': '正常',
        'blood_lipid': '正常',
        'blood_sugar': '正常',
        'pain_detail': '术后瘢痕牵拉',
        'health_need': '提升活动度',
    },
    {
        'profile': '孕产康复',
        'medical_history': '产后3个月盆底功能下降',
        'chronic_disease': '产后康复需求',
        'family_history': '无明显家族史',
        'health_status': '康复期',
        'symptom': '腰背酸痛',
        'symptom_detail': '抱娃后腰背酸痛加重',
        'life_impact': '久站困难',
        'blood_pressure': '正常',
        'blood_lipid': '正常',
        'blood_sugar': '正常',
        'pain_detail': '腰背肌疲劳',
        'health_need': '核心功能恢复',
    },
]

ALLERGY_OPTIONS = ['无', '青霉素轻度过敏', '海鲜过敏', '花粉过敏', '乳糖不耐受']
SMOKING_OPTIONS = ['从不', '已戒烟', '偶尔', '每天10支以上']
DRINKING_OPTIONS = ['从不', '偶尔', '每周', '每日少量']
SLEEP_QUALITY_OPTIONS = ['良好', '一般', '较差']
SLEEP_HOURS_OPTIONS = ['5-6小时', '6-7小时', '7-8小时', '8小时以上']
EXERCISE_OPTIONS = ['快走', '游泳', '拉伸训练', '核心训练', '太极', '抗阻训练']
APPOINTMENT_STATUS_OPTIONS = ['scheduled', 'completed', 'cancelled']
CHECKIN_STATUS_OPTIONS = ['pending', 'checked_in', 'missed']
IMPROVEMENT_STATUS_OPTIONS = ['持续改善', '波动改善', '需持续跟进', '待复评']


def fmt_day(offset_days: int) -> str:
    return (now_local() - timedelta(days=offset_days)).strftime('%Y-%m-%d')


def fmt_ts(offset_days: int, hour: int, minute: int) -> str:
    dt = now_local() - timedelta(days=offset_days)
    return dt.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')


def clear_legacy_data(cursor: sqlite3.Cursor) -> None:
    # 先清理存在外键依赖的明细，再清理主业务表。
    tables_in_order = [
        'improvement_record_files',
        'service_improvement_records',
        'business_history_logs',
        'home_appointments',
        'appointments',
        'visit_checkins',
        'health_records',
        'health_assessments',
        'audit_logs',
        'task_execution_logs',
        'customers',
    ]
    for table_name in tables_in_order:
        cursor.execute(f'DELETE FROM {table_name}')


def pick_project(cursor: sqlite3.Cursor):
    cursor.execute(
        "SELECT id, name, duration_minutes FROM therapy_projects WHERE status='enabled' ORDER BY id"
    )
    return cursor.fetchall()


def pick_equipment(cursor: sqlite3.Cursor):
    cursor.execute("SELECT id, name FROM equipment WHERE status='available' ORDER BY id")
    return cursor.fetchall()


def pick_staff(cursor: sqlite3.Cursor):
    cursor.execute("SELECT id, name FROM staff ORDER BY id")
    return cursor.fetchall()


def cycle_pick(values, idx: int):
    return values[(idx - 1) % len(values)]


def seed_samples() -> dict:
    random.seed(RANDOM_SEED)
    init_db()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON;')
    c = conn.cursor()

    projects = pick_project(c)
    equipment = pick_equipment(c)
    staff_list = pick_staff(c)
    if not projects or not equipment or not staff_list:
        raise RuntimeError('基础主数据不足：请确认therapy_projects/equipment/staff已初始化。')

    conn.execute('BEGIN')
    clear_legacy_data(c)

    for idx in range(1, SAMPLE_CUSTOMER_COUNT + 1):
        profile = cycle_pick(HEALTH_PROFILES, idx)
        name = random.choice(LAST_NAMES) + random.choice(FIRST_NAMES)
        gender = '男' if idx % 2 else '女'
        age = random.randint(28, 76)
        birth_year = now_local().year - age
        birth_date = f'{birth_year}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}'
        id_card = f'11010119{random.randint(60, 99):02d}{random.randint(1, 12):02d}{random.randint(1, 28):02d}{idx:04d}'
        phone = f'13{random.randint(100000000, 999999999)}'
        email = f'customer{idx:02d}@example.com'
        address = f'北京市朝阳区康复路{idx}号'

        c.execute(
            '''
            INSERT INTO customers (
                name, id_card, phone, email, address, gender, age, birth_date,
                identity_type, military_rank, record_creator, medical_history, allergies,
                diet_habits, chronic_diseases, health_status, therapy_contraindications,
                created_at, updated_at, is_deleted
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
            ''',
            (
                name,
                id_card,
                phone,
                email,
                address,
                gender,
                age,
                birth_date,
                '地方人员',
                '无',
                '系统样本脚本',
                profile['medical_history'],
                cycle_pick(ALLERGY_OPTIONS, idx),
                random.choice(['清淡饮食', '低盐低脂', '控糖饮食', '高蛋白饮食']),
                profile['chronic_disease'],
                profile['health_status'],
                random.choice(['无', '急性炎症期禁做强刺激理疗']),
                fmt_ts(60 - idx, 9, 0),
                fmt_ts(1, 10, idx % 60),
            ),
        )
        customer_id = c.lastrowid

        assessment_date = fmt_day(random.randint(1, 45))
        height_cm = round(random.uniform(152, 183), 1)
        weight_kg = round(random.uniform(48, 86), 1)

        c.execute(
            '''
            INSERT INTO health_assessments (
                customer_id, assessment_date, assessor, age, height_cm, weight_kg, address,
                past_medical_history, family_history, allergy_history, allergy_details,
                smoking_status, smoking_years, cigarettes_per_day, drinking_status, drinking_years,
                sleep_quality, sleep_hours, recent_symptoms, recent_symptom_detail,
                life_impact_issues, blood_pressure_test, blood_lipid_test, blood_sugar_test,
                chronic_pain, pain_details, exercise_methods, health_needs, notes, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                customer_id,
                assessment_date,
                random.choice(['王医生', '李医生', '赵医生']),
                age,
                height_cm,
                weight_kg,
                address,
                profile['medical_history'],
                profile['family_history'],
                random.choice(['无', '有']),
                cycle_pick(ALLERGY_OPTIONS, idx),
                cycle_pick(SMOKING_OPTIONS, idx),
                random.randint(0, 15),
                random.randint(0, 12),
                cycle_pick(DRINKING_OPTIONS, idx),
                random.randint(0, 10),
                cycle_pick(SLEEP_QUALITY_OPTIONS, idx),
                cycle_pick(SLEEP_HOURS_OPTIONS, idx),
                profile['symptom'],
                profile['symptom_detail'],
                profile['life_impact'],
                profile['blood_pressure'],
                profile['blood_lipid'],
                profile['blood_sugar'],
                random.choice(['有', '无']),
                profile['pain_detail'],
                cycle_pick(EXERCISE_OPTIONS, idx),
                profile['health_need'],
                f'画像标签：{profile["profile"]}，建议继续阶段性理疗与家庭训练',
                fmt_ts(50 - idx, 14, 0),
            ),
        )

        c.execute(
            '''
            INSERT INTO health_records (
                customer_id, record_date, height_cm, weight_kg, blood_pressure, symptoms, diagnosis, notes, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ''',
            (
                customer_id,
                assessment_date,
                height_cm,
                weight_kg,
                random.choice(['118/76', '126/82', '132/86', '140/92', '150/96']),
                profile['symptom'],
                random.choice(['肌筋膜劳损', '颈椎退行性改变', '功能性疲劳', '代谢紊乱风险', '慢病管理需求']),
                f'重点关注：{profile["profile"]}，建议每周2次理疗并配合居家拉伸',
                fmt_ts(48 - idx, 15, 30),
            ),
        )

        c.execute(
            '''
            INSERT INTO visit_checkins (customer_id, checkin_time, purpose, notes, created_at)
            VALUES (?,?,?,?,?)
            ''',
            (
                customer_id,
                fmt_ts(random.randint(1, 20), 9 + idx % 8, 10),
                random.choice(['复诊', '初诊评估', '理疗复查']),
                '前台签到样本记录',
                fmt_ts(random.randint(1, 20), 9 + idx % 8, 12),
            ),
        )

        project = random.choice(projects)
        equip = random.choice(equipment)
        staff = random.choice(staff_list)
        app_date = fmt_day(random.randint(0, 20))
        start_hour = 9 + (idx % 8)
        start_time = f'{start_hour:02d}:00'
        end_time = f'{(start_hour + 1):02d}:00'

        c.execute(
            '''
            INSERT INTO appointments (
                customer_id, equipment_id, project_id, staff_id, appointment_date, start_time, end_time,
                status, checkin_status, has_companion, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                customer_id,
                equip['id'],
                project['id'],
                staff['id'],
                app_date,
                start_time,
                end_time,
                cycle_pick(APPOINTMENT_STATUS_OPTIONS, idx),
                cycle_pick(CHECKIN_STATUS_OPTIONS, idx),
                random.choice(['有', '无']),
                f'{project["name"]}门店预约样本（{profile["profile"]}）',
                fmt_ts(random.randint(5, 30), start_hour, 0),
                fmt_ts(random.randint(1, 4), start_hour + 1, 0),
            ),
        )
        appointment_id = c.lastrowid

        home_project = random.choice(projects)
        home_staff = random.choice(staff_list)
        home_date = fmt_day(random.randint(0, 25))
        home_start = 10 + (idx % 6)

        c.execute(
            '''
            INSERT INTO home_appointments (
                customer_id, project_id, staff_id, customer_name, phone, home_time, home_address,
                service_project, staff_name, appointment_date, start_time, end_time, location,
                contact_person, contact_phone, has_companion, notes, status, checkin_status,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                customer_id,
                home_project['id'],
                home_staff['id'],
                name,
                phone,
                f'{home_start:02d}:00-{home_start+1:02d}:00',
                address,
                home_project['name'],
                home_staff['name'],
                home_date,
                f'{home_start:02d}:00',
                f'{home_start + 1:02d}:00',
                address,
                random.choice(['家属', '本人']),
                f'13{random.randint(100000000, 999999999)}',
                random.choice(['有', '无']),
                f'{home_project["name"]}上门服务样本（{profile["profile"]}）',
                cycle_pick(APPOINTMENT_STATUS_OPTIONS, idx + 1),
                cycle_pick(CHECKIN_STATUS_OPTIONS, idx + 1),
                fmt_ts(random.randint(3, 25), home_start, 5),
                fmt_ts(random.randint(1, 3), home_start + 1, 5),
            ),
        )

        c.execute(
            '''
            INSERT INTO service_improvement_records (
                service_id, service_type, customer_id, service_time, service_project,
                pre_service_status, service_content, post_service_evaluation,
                improvement_status, followup_time, followup_date, followup_method,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                appointment_id,
                'appointments',
                customer_id,
                fmt_ts(random.randint(0, 20), 16, 0),
                project['name'],
                random.choice(['疼痛评分6分', '活动受限明显', '睡眠质量一般', '血压波动明显', '耐力下降']),
                random.choice(['热疗+筋膜放松', '超声理疗+牵伸', '电刺激+康复训练']),
                random.choice(['疼痛下降至3分', '关节活动度改善', '睡眠改善']),
                cycle_pick(IMPROVEMENT_STATUS_OPTIONS, idx),
                random.choice(['24小时后电话回访', '3天后到店复查']),
                fmt_day(random.randint(1, 10)),
                random.choice(['电话', '微信', '门店复诊']),
                fmt_ts(random.randint(0, 15), 17, 20),
                fmt_ts(random.randint(0, 2), 18, 0),
            ),
        )
        improvement_id = c.lastrowid

        c.execute(
            '''
            INSERT INTO improvement_record_files (
                customer_id, improvement_record_id, file_name, file_ext, file_path, file_size, uploaded_at
            ) VALUES (?,?,?,?,?,?,?)
            ''',
            (
                customer_id,
                improvement_id,
                f'improvement_{customer_id:03d}.pdf',
                '.pdf',
                f'uploads/improvement_{customer_id:03d}.pdf',
                random.randint(80_000, 300_000),
                fmt_ts(random.randint(0, 10), 19, 10),
            ),
        )

    conn.commit()

    table_counts = {}
    for table_name in [
        'customers',
        'health_assessments',
        'health_records',
        'visit_checkins',
        'appointments',
        'home_appointments',
        'service_improvement_records',
        'improvement_record_files',
    ]:
        c.execute(f'SELECT COUNT(*) AS n FROM {table_name}')
        table_counts[table_name] = c.fetchone()['n']

    conn.close()
    return table_counts


if __name__ == '__main__':
    counts = seed_samples()
    print('样本数据生成完成：')
    for table, count in counts.items():
        print(f'  - {table}: {count}')
