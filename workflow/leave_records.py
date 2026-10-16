from datetime import date, time
from decimal import Decimal
from django.utils import timezone
from .models import AnnualBalance, DEPARTMENTS, Document, CompanyLeaveCharge, ManualLeaveUsage
from .annual_grants import completed_years, entitlement, employees
from django.db.models import Sum
from .people import rank_order
from django.contrib.auth import get_user_model


def balance_filters(params):
    try:
        year = int(params.get('year', timezone.localdate().year))
        if not 2000 <= year <= 2100:
            raise ValueError
    except (ValueError, TypeError):
        year = timezone.localdate().year
    department = params.get('department', '')
    return year, department if department in DEPARTMENTS else ''


def balance_rows(year, department='', user=None):
    users = employees() if user is None else get_user_model().objects.filter(pk=user.pk)
    if department:
        users = users.filter(profile__department=department)
    users = list(rank_order(users.select_related('profile')))
    balances = {item.user_id: item for item in AnnualBalance.objects.filter(user__in=users, year=year)}
    common = {item['employee_id']: item['amount'] for item in CompanyLeaveCharge.objects.filter(
        employee__in=users, year=year, active=True).values('employee_id').annotate(amount=Sum('amount'))}
    return [{'user': employee, 'total': balances[employee.pk].total if employee.pk in balances else Decimal('0'),
             'used': balances[employee.pk].used if employee.pk in balances else Decimal('0'),
             'tenure': completed_years(employee.profile.hire_date, date(year, 1, 1)) if employee.profile.hire_date else None,
             'calculated': entitlement(employee.profile.hire_date, year) if employee.profile.hire_date else None,
             'common': common.get(employee.pk, Decimal('0')),
             'available': (balances[employee.pk].total if employee.pk in balances else Decimal('0')) - common.get(employee.pk, Decimal('0')),
             'remaining': balances[employee.pk].remaining if employee.pk in balances else Decimal('0')}
            for employee in users]


def employee_leave_records(employee, year, mode='approved'):
    documents = Document.objects.filter(owner=employee, kind='leave',
        start_date__lte=date(year, 12, 31), end_date__gte=date(year, 1, 1)).exclude(status__in=['draft', 'deleted'])
    if mode != 'all':
        documents = documents.filter(status='approved')
    today = timezone.localdate()
    rows = []
    for doc in documents.order_by('-start_date', '-start_time', '-pk'):
        amount = Decimal(doc.allocations.get(str(year), '0')) if doc.status == 'approved' else Decimal('0')
        timing = '사용 예정' if doc.start_date > today else '사용 완료' if doc.end_date < today else '사용 기간 중'
        rows.append({'doc': doc, 'charged': amount, 'timing': timing if doc.status == 'approved' else '—',
                     'used_date': doc.start_date, 'sort_time': doc.start_time})
    manual = ManualLeaveUsage.objects.filter(employee=employee, used_date__year=year)
    if mode != 'all':
        manual = manual.filter(cancelled_at__isnull=True)
    for usage in manual.select_related('created_by', 'cancelled_by'):
        rows.append({'manual': usage, 'charged': usage.amount if usage.cancelled_at is None else Decimal('0'),
                     'timing': '취소됨' if usage.cancelled_at else '사용 예정' if usage.used_date > today else '사용 완료',
                     'used_date': usage.used_date, 'sort_time': usage.start_time})
    return sorted(rows, key=lambda row: (row['used_date'], row['sort_time'] or time.min), reverse=True)
