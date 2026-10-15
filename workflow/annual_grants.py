from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from .models import AnnualBalance, Profile


def employees():
    return get_user_model().objects.filter(is_active=True, is_superuser=False, profile__approved=True).exclude(username__iexact='admin')


def completed_years(hire_date, reference):
    if not hire_date or hire_date > reference:
        return 0
    return reference.year - hire_date.year - ((reference.month, reference.day) < (hire_date.month, hire_date.day))


def entitlement(hire_date, year):
    if not hire_date or hire_date.year > year:
        return Decimal('0')
    years = completed_years(hire_date, date(year, 1, 1))
    from .regulations import bands_for
    return Decimal(next(days for low, days in reversed(bands_for(year)) if years >= low))


def ensure_balance(employee, year):
    """Call within a transaction after locking the employee profile."""
    balance, _ = AnnualBalance.objects.get_or_create(user=employee, year=year)
    balance = AnnualBalance.objects.select_for_update().get(pk=balance.pk)
    if employee.profile.hire_date and not balance.grant_initialized:
        balance.total = entitlement(employee.profile.hire_date, year)
        from .regulations import annual_policy
        policy = annual_policy(year)
        balance.grant_initialized, balance.total_manual = True, False
        balance.grant_policy_year = policy.effective_year if policy else None
        balance.save(update_fields=['total', 'grant_initialized', 'total_manual', 'grant_policy_year'])
    return balance


@transaction.atomic
def sync_annual_grants(today=None):
    """Idempotent catch-up on Jan 1, including pre-existing future leave charges."""
    today = today or timezone.localdate()
    count = 0
    ready = AnnualBalance.objects.filter(year=today.year, grant_initialized=True).values('user_id')
    for employee in employees().filter(profile__hire_date__isnull=False).exclude(pk__in=ready).select_related('profile').order_by('pk'):
        Profile.objects.select_for_update().get(user=employee)
        before = AnnualBalance.objects.filter(user=employee, year=today.year, grant_initialized=True).exists()
        ensure_balance(employee, today.year)
        count += not before
        if not before:
            from .services import audit
            audit(None, f'{today.year}년 연차 자동 산정', target=employee,
                  detail=f'입사일 {employee.profile.hire_date} / 총연차 {entitlement(employee.profile.hire_date, today.year)}일 / 기존 사용연차 유지')
    return count


@transaction.atomic
def set_hire_date(actor, employee, hire_date, year, apply=False):
    from django.core.exceptions import PermissionDenied, ValidationError
    from .services import audit
    if not actor.profile.manage_leave:
        raise PermissionDenied
    if hire_date > timezone.localdate():
        raise ValidationError('입사일은 오늘 이후로 입력할 수 없습니다.')
    from .models import CompanyHolidayLock
    CompanyHolidayLock.objects.select_for_update().get(pk=1)
    profile = Profile.objects.select_for_update().get(user=employee)
    before = profile.hire_date
    profile.hire_date = hire_date
    profile.save(update_fields=['hire_date'])
    employee.profile = profile
    # Explicit apply is the only way to replace a manually managed existing total.
    if apply:
        balance, _ = AnnualBalance.objects.get_or_create(user=employee, year=year)
        balance = AnnualBalance.objects.select_for_update().get(pk=balance.pk)
        previous = balance.total
        balance.total = entitlement(hire_date, year)
        from .regulations import annual_policy
        policy = annual_policy(year)
        balance.grant_initialized, balance.total_manual = True, False
        balance.grant_policy_year = policy.effective_year if policy else None
        balance.save(update_fields=['total', 'grant_initialized', 'total_manual', 'grant_policy_year'])
        audit(actor, f'{year}년 총연차 산정 적용', target=employee,
              detail=f'입사일 {hire_date} / 총연차 {previous} → {balance.total}, 사용연차 {balance.used} 유지')
    from .company_holidays import reconcile_employee
    reconcile_employee(actor, employee)
    audit(actor, '입사일 수정', target=employee, detail=f'{before or "미입력"} → {hire_date}')
