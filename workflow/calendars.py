import calendar
from datetime import date, timedelta
from django.urls import reverse
from django.utils import timezone
import holidays
from .models import Absence, CompanyHoliday, Document, ManualLeaveUsage


def month_selection(params):
    today = timezone.localdate()
    try:
        year, month = int(params.get('year', today.year)), int(params.get('month', today.month))
        if not 2001 <= year <= 2099 or not 1 <= month <= 12:
            raise ValueError
    except (TypeError, ValueError):
        year, month = today.year, today.month
    return year, month


def month_grid(year, month, viewer):
    today = timezone.localdate()
    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]
    days = {d: {'date': d, 'outside': d.month != month, 'today': d == today, 'weekend': d.weekday() >= 5,
                'holidays': [], 'events': [], 'common_leave': False} for week in weeks for d in week}
    national = holidays.KR(years=range(first.year, last.year + 1), language='ko')
    for day, name in national.items():
        if day in days:
            days[day]['holidays'].append(name.replace('대체 휴일', '대체공휴일'))
    for holiday in CompanyHoliday.objects.filter(active=True, day__range=(first, last)).order_by('pk'):
        if holiday.use_annual:
            days[holiday.day]['common_leave'] = True
        days[holiday.day]['events'].append({'kind': 'company', 'label': holiday.title,
            'subtitle': '공용연차 · 1일' if holiday.use_annual else '회사 휴무',
            'url': reverse('company_holidays') if viewer.profile.manage_leave else '',
            'description': holiday.description})
    approved = Document.objects.filter(kind='leave', status='approved', start_date__lte=last,
        end_date__gte=first).select_related('owner__profile').order_by('owner__first_name', 'pk')
    for doc in approved:
        current, end = max(first, doc.start_date), min(last, doc.end_date)
        while current <= end:
            if current.weekday() < 5:
                days[current]['events'].append({'kind': 'leave',
                    'label': f'{doc.owner.first_name} · {doc.get_leave_type_display()}',
                    'subtitle': '종일' if doc.leave_type == 'annual' else f'{doc.start_time:%H:%M}~{doc.end_time:%H:%M}',
                    'url': reverse('calendar_leave', args=[doc.pk]),
                    'description': f'{doc.owner.profile.department} · {doc.owner.profile.rank}'})
            current += timedelta(days=1)
    manual = ManualLeaveUsage.objects.filter(cancelled_at__isnull=True,
        used_date__range=(first, last)).select_related('employee__profile').order_by('employee__first_name', 'pk')
    for usage in manual:
        days[usage.used_date]['events'].append({'kind': 'leave',
            'label': f'{usage.employee.first_name} · {usage.get_leave_type_display()}',
            'subtitle': '직접 등록 · ' + ('종일' if usage.leave_type == 'annual' else f'{usage.start_time:%H:%M}~{usage.end_time:%H:%M}'),
            'url': (reverse('leave_history', args=[usage.employee_id]) + f'?year={usage.used_date.year}')
                   if viewer.profile.manage_leave else '',
            'description': f'{usage.employee.profile.department} · {usage.employee.profile.rank}'})
    for absence in Absence.objects.filter(start_date__lte=last, end_date__gte=first).select_related('employee__profile').order_by('employee__first_name', 'pk'):
        current, end = max(first, absence.start_date), min(last, absence.end_date)
        while current <= end:
            days[current]['events'].append({'kind': 'absence', 'label': f'{absence.employee.first_name} · {absence.reason}',
                'subtitle': '종일' if absence.all_day else f'{absence.start_time:%H:%M}~{absence.end_time:%H:%M}',
                'url': '' if viewer.profile.is_representative else reverse('absence_edit', args=[absence.pk]),
                'description': f'{absence.employee.profile.department} · {absence.employee.profile.rank}'})
            current += timedelta(days=1)
    prev = date(year, month, 1) - timedelta(days=1)
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    return {'weeks': [[days[d] for d in week] for week in weeks], 'previous': prev, 'next_month': next_month,
            'selected_year': year, 'selected_month': month, 'today': today}
