"""Recurring solar/lunar birthdays; store only the original month/day, never age."""
from datetime import date
from functools import lru_cache

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from korean_lunar_calendar import KoreanLunarCalendar

from .annual_grants import employees
from .models import Profile


def birthday_values(month, day, calendar='solar', leap=False):
    if month is None and day is None:
        return {'birthday_month': None, 'birthday_day': None,
                'birthday_calendar': 'solar', 'birthday_lunar_leap': False}
    if calendar not in ('solar', 'lunar') or month is None or day is None:
        raise ValidationError('생일 기준과 월·일을 모두 입력해 주세요.')
    if calendar == 'lunar':
        if not isinstance(month, int) or not isinstance(day, int) or not 1 <= month <= 12 or not 1 <= day <= 30:
            raise ValidationError('음력 생일은 1~12월, 1~30일로 입력해 주세요.')
    else:
        try:
            date(2000, month, day)
        except (ValueError, TypeError):
            raise ValidationError('생일의 월·일을 확인해 주세요.')
    if calendar == 'solar' and leap:
        raise ValidationError('윤달은 음력 생일에만 선택할 수 있습니다.')
    return {'birthday_month': month, 'birthday_day': day,
            'birthday_calendar': calendar, 'birthday_lunar_leap': bool(leap)}


def birthday_employees():
    return employees().filter(profile__department_confirmed=True).select_related('profile')


def birthday_label(values):
    if values['birthday_month'] is None:
        return '미등록'
    calendar = '음력' if values['birthday_calendar'] == 'lunar' else '양력'
    leap = ' 윤달' if values['birthday_lunar_leap'] else ''
    return f'{calendar}{leap} {values["birthday_month"]}월 {values["birthday_day"]}일'


@lru_cache(maxsize=4096)
def lunar_birthday(year, month, day, leap):
    converter = KoreanLunarCalendar()
    # A leap birthday uses the regular lunar month in years without that leap month.
    actual_leap = bool(leap and converter.setLunarDate(year, month, 1, True)
                       and converter.isIntercalation)
    if converter.setLunarDate(year, month, day, actual_leap):
        return date(converter.solarYear, converter.solarMonth, converter.solarDay)
    # An absent lunar day 30 is celebrated on day 29 in that same month.
    if day == 30 and converter.setLunarDate(year, month, 29, actual_leap):
        return date(converter.solarYear, converter.solarMonth, converter.solarDay)
    return None


def birthday_dates(profile, year):
    month, day = profile.birthday_month, profile.birthday_day
    if month is None or day is None:
        return []
    if profile.birthday_calendar == 'solar':
        try:
            return [date(year, month, day)]
        except ValueError:
            # A solar Feb 29 birthday remains Feb 29; no substitute day was requested.
            return []
    # Lunar December may fall in January/February of the following solar year.
    return sorted({value for lunar_year in (year-1, year)
        if (value := lunar_birthday(lunar_year, month, day, profile.birthday_lunar_leap))
        and value.year == year})


def birthday_rows(year, month, today=None):
    today = today or timezone.localdate()
    rows = []
    for employee in birthday_employees().filter(profile__birthday_month__isnull=False):
        for day in birthday_dates(employee.profile, year):
            if day.month == month:
                rows.append({'employee': employee, 'day': day, 'today': day == today})
    return sorted(rows, key=lambda row: (row['day'], row['employee'].first_name, row['employee'].pk))


def birthday_period(params, today):
    try:
        year, month = int(params.get('year', today.year)), int(params.get('month', today.month))
        date(year, month, 1)
        if not 2000 <= year <= 2100:
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month
    return year, month


@transaction.atomic
def save_birthday(actor, employee, values):
    if not actor.profile.manage_leave:
        raise PermissionDenied
    if not birthday_employees().filter(pk=employee.pk).exists():
        raise ValidationError('생일을 관리할 수 있는 승인된 재직 직원이 아닙니다.')
    normalized = birthday_values(values.get('birthday_month'), values.get('birthday_day'),
        values.get('birthday_calendar', 'solar'), values.get('birthday_lunar_leap', False))
    profile = Profile.objects.select_for_update().get(user=employee)
    before = {key: getattr(profile, key) for key in normalized}
    if before == normalized:
        return
    for key, value in normalized.items():
        setattr(profile, key, value)
    profile.save(update_fields=list(normalized))
    from .services import audit
    audit(actor, '직원 생일 수정', target=employee, detail=f'{birthday_label(before)} → {birthday_label(normalized)}')
