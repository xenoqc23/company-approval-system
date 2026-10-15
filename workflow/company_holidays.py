from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from .annual_grants import employees, ensure_balance
from .models import CompanyHoliday, CompanyLeaveCharge, CompanyHolidayLock, Profile


def manager(actor):
    if not actor.profile.manage_leave:
        raise PermissionDenied


def restore(holiday, actor):
    from .services import audit
    for charge in holiday.charges.filter(active=True).select_related('employee__profile').order_by('employee_id'):
        Profile.objects.select_for_update().get(user=charge.employee)
        balance = ensure_balance(charge.employee, charge.year)
        balance.used -= charge.amount
        balance.save(update_fields=['used'])
        charge.active = False
        charge.save(update_fields=['active'])
        audit(actor, f'{charge.year}년 공용연차 복원', target=charge.employee,
              detail=f'{holiday.day} {holiday.title}: {charge.amount}일 복원')


@transaction.atomic
def save_company_holiday(actor, values, pk=None):
    from .services import audit
    manager(actor)
    CompanyHolidayLock.objects.select_for_update().get(pk=1)
    holiday = CompanyHoliday.objects.select_for_update().get(pk=pk, active=True) if pk else None
    conflict = CompanyHoliday.objects.filter(day=values['day'], active=True)
    if pk:
        conflict = conflict.exclude(pk=pk)
    if conflict.exists():
        raise ValidationError('같은 날짜에 회사 휴무가 이미 등록되어 있습니다.')
    changed_charge = not holiday or holiday.day != values['day'] or holiday.use_annual != values['use_annual']
    if holiday and changed_charge:
        restore(holiday, actor)
    if not holiday:
        holiday = CompanyHoliday(created_by=actor)
    for field in ['title', 'day', 'use_annual', 'description']:
        setattr(holiday, field, values[field])
    holiday.save()
    if holiday.use_annual and changed_charge:
        for employee in employees().filter(profile__hire_date__lte=holiday.day).select_related('profile').order_by('pk'):
            Profile.objects.select_for_update().get(user=employee)
            balance = ensure_balance(employee, holiday.day.year)
            balance.used += Decimal('1')
            balance.save(update_fields=['used'])
            CompanyLeaveCharge.objects.update_or_create(holiday=holiday, employee=employee,
                defaults={'year': holiday.day.year, 'amount': Decimal('1'), 'active': True})
            audit(actor, f'{holiday.day.year}년 공용연차 차감', target=employee,
                  detail=f'{holiday.day} {holiday.title}: 1일 차감')
    return holiday


@transaction.atomic
def delete_company_holiday(actor, pk):
    manager(actor)
    CompanyHolidayLock.objects.select_for_update().get(pk=1)
    holiday = CompanyHoliday.objects.select_for_update().get(pk=pk, active=True)
    restore(holiday, actor)
    holiday.active = False
    holiday.save(update_fields=['active'])
    return holiday


@transaction.atomic
def reconcile_employee(actor, employee):
    """Apply registered holidays from the hire date, restoring actual earlier charges."""
    CompanyHolidayLock.objects.select_for_update().get(pk=1)
    Profile.objects.select_for_update().get(user=employee)
    hire = employee.profile.hire_date
    if not hire or not employees().filter(pk=employee.pk).exists():
        return
    from .services import audit
    for charge in CompanyLeaveCharge.objects.select_for_update().filter(employee=employee, active=True,
            holiday__active=True, holiday__day__lt=hire).select_related('holiday'):
        balance = ensure_balance(employee, charge.year)
        balance.used -= charge.amount
        balance.save(update_fields=['used'])
        charge.active = False
        charge.save(update_fields=['active'])
        audit(actor, f'{charge.year}년 입사 전 공용연차 복원', target=employee,
              detail=f'{charge.holiday.day} {charge.holiday.title}: {charge.amount}일')
    for holiday in CompanyHoliday.objects.filter(active=True, use_annual=True, day__gte=hire).order_by('pk'):
        charge = CompanyLeaveCharge.objects.filter(employee=employee, holiday=holiday).first()
        if charge and charge.active:
            continue
        balance = ensure_balance(employee, holiday.day.year)
        balance.used += Decimal('1')
        balance.save(update_fields=['used'])
        CompanyLeaveCharge.objects.update_or_create(employee=employee, holiday=holiday,
            defaults={'year': holiday.day.year, 'amount': 1, 'active': True})
        audit(actor, f'{holiday.day.year}년 입사 기준 공용연차 차감', target=employee,
              detail=f'{holiday.day} {holiday.title}: 1일')


def overlapping_leaves(holidays):
    from .models import Document
    from .services import weekdays
    result = []
    for holiday in holidays:
        if not holiday.use_annual:
            continue
        docs = Document.objects.filter(kind='leave', status='approved', start_date__lte=holiday.day,
            end_date__gte=holiday.day).select_related('owner__profile')
        for doc in docs:
            if holiday.day in weekdays(doc.start_date, doc.end_date):
                result.append({'holiday': holiday, 'document': doc})
    return result
