"""Regenerate the inspectable, fictional 2026 demonstration fixture."""
import json
from datetime import date, timedelta
from pathlib import Path

YEAR = 2026
AS_OF = date(2026, 11, 24)
PROJECTS = ['艾灸机器人', '高压氧舱', '听力检测', '按摩机器人']
DISEASES = [('高血压',), ('高血压', '糖尿病'), ('颈椎病',), ('关节炎',), ('高血脂',), ('听力下降',), ('冠心病', '高血压'), (), ('腰椎病',), ('睡眠障碍',)]


def build_cases():
    cases = []
    for i in range(1, 101):
        diseases = DISEASES[(i-1) % len(DISEASES)]
        born = date(YEAR - 60 - (i * 7 % 32), i % 12 + 1, i % 27 + 1)
        identity = f'000000{born:%Y%m%d}{i:03d}X'
        visits = []
        for n in range(3):
            project = PROJECTS[(i+n) % 4]
            # Separate months and staggered slots keep repeat cases inspectable.
            day = date(YEAR, 1, 5) + timedelta(days=((i-1)*3 + n*43) % 310)
            before = 4 + (i+n) % 6
            change = [3, 2, 4, 1, 0, 2, 3, -1, 2, 0][(i+n) % 10]
            if project == '听力检测':
                change = [0, 1, 0, 0, 1][i % 5]
            after = max(0, min(10, before-change))
            status = '明显改善' if before-after >= 3 else '部分改善' if before > after else '无改善' if before == after else '加重'
            followup_day = day + timedelta(days=14)
            done = i % 5 not in (0, 1)
            visits.append({
                'project': project, 'date': day.isoformat(), 'time': f'{9+i%6:02d}:{30 if n%2 else 0:02d}',
                'dimension': '听力沟通困扰' if project=='听力检测' else ['疼痛影响','疲劳感','活动不便'][n],
                'before': before, 'after': after, 'status': status, 'satisfaction': max(2, 5 if change>=2 else 3 if change<=0 else 4),
                'adverse': change < 0, 'followup_date': followup_day.isoformat(),
                'followup_status': '已回访' if done else '待回访',
                'followup_completed_at': f'{followup_day} 10:00:00' if done else None,
                'followup_notes': '演示回访：已核对本人感受，日常活动情况已记录，后续按健康专员安排随访。' if done else '',
                'has_feedback': not (i % 10 == 0 and n == 2),
            })
        cases.append({'case_no': f'DEMO-{i:03d}', 'name': f'演示干部{i:03d}', 'gender': '女' if i%4==0 else '男',
                      'birth_date': born.isoformat(), 'id_card': identity, 'phone': f'1990000{i:04d}',
                      'rank': ['师职','团职','营职','专业技术'][i%4], 'diseases': list(diseases),
                      'sleep': '差' if i%6==0 else '一般' if i%3==0 else '良好',
                      'needs': ['健康宣教', '日常活动指导'] if i%3 else ['睡眠管理', '定期随访'],
                      'visits': visits, 'home_visit': i%5==0})
    return {'schema_version': 1, 'year': YEAR, 'as_of': AS_OF.isoformat(), 'fictional': True,
            'notice': '100位完全虚构的军休干部案例，仅供体验和系统建设展示，不可作为真实工作业绩或临床疗效证据。', 'cases': cases}


if __name__ == '__main__':
    path = Path(__file__).with_name('cases-2026.json')
    path.write_text(json.dumps(build_cases(), ensure_ascii=False, indent=2), encoding='utf-8')
    print('Generated 100 fictional cases.')
