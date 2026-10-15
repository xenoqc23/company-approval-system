from datetime import date
import calendar
from .annual_grants import employees
from .people import rank_order

AWARDS = [(1, '금 1돈'), (3, '금 3돈'), (5, '금 5돈'), (10, '금 10돈'),
          (20, '금 20돈'), (30, '금 30돈'), (40, '금 40돈')]
BENEFITS = [
    ('생일', '본인(배우자 포함)', 100000, '축하케익'),
    ('결혼', '본인', 2000000, '축하화환'), ('결혼', '자녀', 500000, '축하화환'),
    ('출산', '본인(배우자 포함)', 250000, '축하화환'),
    ('부모회갑', '본인(배우자 포함)', 250000, '축하화환'),
    ('첫 돌', '자녀', 150000, '축하케익'), ('본인회갑', '본인(배우자 포함)', 500000, '축하케익'),
    ('본인사망', '근속 2년 이하', 1000000, '근조화환'),
    ('본인사망', '근속 10년 이하', 1500000, '근조화환'),
    ('본인사망', '근속 10년 이상', 2500000, '근조화환'),
    ('배우자사망', '근속 2년 이하', 500000, '근조화환'),
    ('배우자사망', '근속 10년 이하', 1000000, '근조화환'),
    ('배우자사망', '근속 10년 이상', 1500000, '근조화환'),
    ('자녀사망', '근속 2년 이하', 250000, '근조화환'),
    ('자녀사망', '근속 10년 이하', 500000, '근조화환'),
    ('자녀사망', '근속 10년 이상', 750000, '근조화환'),
    ('부모사망(배우자 포함)', '근속 2년 이하', 250000, '근조화환'),
    ('부모사망(배우자 포함)', '근속 10년 이하', 350000, '근조화환'),
    ('부모사망(배우자 포함)', '근속 10년 이상', 500000, '근조화환'),
    ('조부모사망(배우자 포함)', '근속 2년 이하', 150000, '근조화환'),
    ('조부모사망(배우자 포함)', '근속 10년 이하', 250000, '근조화환'),
    ('조부모사망(배우자 포함)', '근속 10년 이상', 350000, '근조화환'),
]


def award_candidates(year, today):
    from .models import WelfarePolicy
    policy = WelfarePolicy.objects.first()
    awards = policy.awards if policy else AWARDS
    result = []
    for employee in rank_order(employees().filter(profile__hire_date__isnull=False).select_related('profile')):
        hire = employee.profile.hire_date
        years = year - hire.year
        reward = dict(awards).get(years)
        if reward:
            day = date(year, hire.month, min(hire.day, calendar.monthrange(year, hire.month)[1]))
            result.append({'employee': employee, 'day': day, 'years': years, 'reward': reward,
                           'arrived': day <= today})
    return result
