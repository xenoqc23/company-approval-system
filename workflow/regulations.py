"""Editable policy data shared by employee displays and annual calculations."""
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from .models import AnnualPolicy, AnnualBalance, ApprovalRule, RegulationLock, WelfarePolicy, RANKS

DEFAULT_BANDS = [[0, 12], [1, 15], [3, 16], [5, 17], [7, 18], [9, 19],
                 [11, 20], [13, 21], [15, 22], [17, 23], [19, 24], [21, 25]]


def annual_policy(year):
    return AnnualPolicy.objects.filter(effective_year__lte=year).first()


def bands_for(year):
    policy = annual_policy(year)
    return policy.bands if policy else DEFAULT_BANDS


def tenure_table(year):
    bands = bands_for(year)
    return [(f'{low}년 이상' if i == len(bands)-1 else f'{low}~{bands[i+1][0]}년 미만', days)
            for i, (low, days) in enumerate(bands)]


def validate_bands(bands):
    if not bands or bands[0][0] != 0 or any(a[0] >= b[0] for a, b in zip(bands, bands[1:])):
        raise ValidationError('근속기간은 0년부터 시작해 중복 없이 오름차순으로 입력해 주세요.')
    if any(low < 0 or low > 100 or days < 0 or days > 999 for low, days in bands):
        raise ValidationError('근속연수와 연차일수를 확인해 주세요.')


@transaction.atomic
def save_annual_policy(actor, year, bands, text):
    if not actor.profile.manage_leave:
        raise PermissionDenied
    if not timezone.localdate().year <= year <= timezone.localdate().year + 5:
        raise ValidationError('올해부터 5년 뒤까지의 적용 연도를 선택해 주세요. 과거 규정은 보존합니다.')
    validate_bands(bands)
    RegulationLock.objects.select_for_update().get_or_create(pk=1)
    policy = AnnualPolicy.objects.filter(effective_year=year).first()
    before = {'bands': policy.bands, 'text': policy.text, 'version': policy.version} if policy else None
    if policy:
        policy.bands, policy.text, policy.version = bands, text, policy.version + 1
        policy.save()
    else:
        policy = AnnualPolicy.objects.create(effective_year=year, bands=bands, text=text)
    from .services import audit
    audit(actor, '연차 산정규정 수정', detail=f'{year}년 적용 / 변경 전 {before} / 변경 후 {bands} / 안내 {text}')
    return policy


@transaction.atomic
def save_rule(actor, form):
    if not (actor.profile.manage_leave or actor.profile.manage_system):
        raise PermissionDenied
    RegulationLock.objects.select_for_update().get_or_create(pk=1)
    rule = form.save(commit=False)
    for other in ApprovalRule.objects.filter(kind=rule.kind, enabled=True).exclude(pk=rule.pk):
        rank_overlap = not rule.author_ranks or not other.author_ranks or bool(set(rule.author_ranks) & set(other.author_ranks))
        amount_overlap = rule.kind == 'leave' or (max(rule.amount_over, other.amount_over) < min(
            rule.amount_to if rule.amount_to is not None else Decimal('Infinity'),
            other.amount_to if other.amount_to is not None else Decimal('Infinity')))
        if rule.enabled and rank_overlap and amount_overlap:
            raise ValidationError(f'사용 중인 규정 「{other.name}」과 적용 조건이 겹칩니다.')
    previous = ApprovalRule.objects.filter(pk=rule.pk).values().first() if rule.pk else None
    rule.version = (previous['version'] + 1) if previous else 1
    rule.save()
    from .services import audit
    audit(actor, '전결규정 수정', detail=f'변경 전 {previous} / 변경 후 {form.cleaned_data} / 버전 {rule.version}')
    return rule


@transaction.atomic
def save_welfare(actor, tab, rows):
    if not actor.profile.manage_leave:
        raise PermissionDenied
    RegulationLock.objects.select_for_update().get_or_create(pk=1)
    policy, _ = WelfarePolicy.objects.get_or_create(pk=1)
    before = getattr(policy, tab)
    setattr(policy, tab, rows)
    policy.version += 1
    policy.save()
    from .services import audit
    audit(actor, '경조사비 규정 수정' if tab == 'benefits' else '장기근속 포상규정 수정', detail=f'변경 전 {before} / 변경 후 {rows}')
    return policy


def recalc_rows(year, department=''):
    from .annual_grants import employees, entitlement
    from .people import rank_order
    users = employees().select_related('profile')
    if department:
        users = users.filter(profile__department=department)
    balances = {b.user_id: b for b in AnnualBalance.objects.filter(year=year)}
    return [{'user': u, 'before': balances[u.pk].total if u.pk in balances else Decimal('0'),
             'used': balances[u.pk].used if u.pk in balances else Decimal('0'),
             'after': entitlement(u.profile.hire_date, year) if u.profile.hire_date else None,
             'manual': balances[u.pk].total_manual if u.pk in balances else False,
             'hire': str(u.profile.hire_date or '')} for u in rank_order(users)]


@transaction.atomic
def apply_recalculation(actor, snapshot, ids, manual_ids):
    from .annual_grants import employees, entitlement, ensure_balance
    from .models import Profile
    from .services import audit
    if not actor.profile.manage_leave:
        raise PermissionDenied
    RegulationLock.objects.select_for_update().get_or_create(pk=1)
    year = snapshot['year']
    if year != timezone.localdate().year:
        raise ValidationError('올해 연차만 재계산할 수 있습니다. 연도를 다시 확인해 주세요.')
    policy = annual_policy(year)
    revision = [policy.pk, policy.version] if policy else [None, 0]
    if revision != snapshot['policy']:
        raise ValidationError('연차규정이 변경되었습니다. 미리보기를 다시 확인해 주세요.')
    expected = snapshot['rows']
    if not ids or not ids <= set(expected):
        raise ValidationError('미리보기에서 재계산할 직원을 선택해 주세요.')
    users = list(employees().filter(pk__in=ids).select_related('profile').order_by('pk'))
    if len(users) != len(ids):
        raise ValidationError('직원 정보가 변경되었습니다. 미리보기를 다시 확인해 주세요.')
    for user in users:
        Profile.objects.select_for_update().get(user=user)
        row = expected[str(user.pk)]
        if str(user.profile.hire_date or '') != row['hire'] or not user.profile.hire_date:
            raise ValidationError('입사일이 변경되었거나 미등록입니다. 미리보기를 다시 확인해 주세요.')
        balance, _ = AnnualBalance.objects.get_or_create(user=user, year=year)
        balance = AnnualBalance.objects.select_for_update().get(pk=balance.pk)
        if balance.total != Decimal(row['total']) or balance.total_manual != row['manual']:
            raise ValidationError('총연차가 변경되었습니다. 미리보기를 다시 확인해 주세요.')
        if balance.total_manual and str(user.pk) not in manual_ids:
            raise ValidationError('수동 조정 직원의 새 규정 적용 확인란을 선택해 주세요.')
        before = balance.total
        balance.total = entitlement(user.profile.hire_date, year)
        balance.grant_initialized, balance.total_manual = True, False
        balance.grant_policy_year = policy.effective_year if policy else None
        balance.save(update_fields=['total', 'grant_initialized', 'total_manual', 'grant_policy_year'])
        audit(actor, f'{year}년 총연차 재계산 적용', target=user,
              detail=f'총 {before} → {balance.total} / 최신 사용 {balance.used} 유지 / 적용 규정 {balance.grant_policy_year}')
    return len(users)
