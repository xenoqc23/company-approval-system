from datetime import date
from decimal import Decimal
from django.utils import timezone
from .models import AnnualBalance, DEPARTMENTS, Document
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
    users = get_user_model().objects.filter(profile__approved=True) if user is None else get_user_model().objects.filter(pk=user.pk)
    if department:
        users = users.filter(profile__department=department)
    users = list(rank_order(users.select_related('profile')))
    balances = {item.user_id: item for item in AnnualBalance.objects.filter(user__in=users, year=year)}
    return [{'user': employee, 'total': balances[employee.pk].total if employee.pk in balances else Decimal('0'),
             'used': balances[employee.pk].used if employee.pk in balances else Decimal('0'),
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
        rows.append({'doc': doc, 'charged': amount, 'timing': timing if doc.status == 'approved' else '—'})
    return rows
