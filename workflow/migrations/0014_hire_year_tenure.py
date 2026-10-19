"""Apply the agreed hire-year cutoff without rewriting historical or manual grants."""
from datetime import date
from decimal import Decimal

from django.db import migrations, models
from django.utils import timezone


def apply_hire_year_tenure(apps, schema_editor):
    alias = schema_editor.connection.alias
    year = timezone.localdate().year
    Policy = apps.get_model('workflow', 'AnnualPolicy')
    Balance = apps.get_model('workflow', 'AnnualBalance')
    Audit = apps.get_model('workflow', 'Audit')
    policies = Policy.objects.using(alias)
    if not policies.filter(effective_year=year).exists():
        previous = policies.filter(effective_year__lt=year).order_by('-effective_year').first()
        policies.create(effective_year=year,
            bands=previous.bands if previous else [[0,12],[1,15],[3,16],[5,17],[7,18],
                [9,19],[11,20],[13,21],[15,22],[17,23],[19,24],[21,25]],
            text=previous.text if previous else '',
            hire_year_monthly=previous.hire_year_monthly if previous else True,
            calendar_tenure_before_2017=False)
    for policy in policies.filter(effective_year__gte=year).order_by('effective_year'):
        if policy.calendar_tenure_before_2017:
            continue
        policy.calendar_tenure_before_2017 = True
        policy.version += 1
        policy.save(using=alias, update_fields=['calendar_tenure_before_2017', 'version', 'updated_at'])
        Audit.objects.using(alias).create(event='연차 산정규정 수정', detail=
            f'{policy.effective_year}년부터 / 2016년까지 입사: 조회 연도 − 입사 연도 / '
            '2017년 이후 입사: 조회 연도 1월 1일 기준 만 근속연수 / 연차일수표·신입 규칙 유지')
    active_policies = list(policies.filter(effective_year__gte=year).order_by('-effective_year'))
    balances = Balance.objects.using(alias).filter(year__gte=year, total_manual=False,
        user__is_active=True, user__is_superuser=False, user__profile__approved=True,
        user__profile__hire_date__lt=date(2017, 1, 1)
        ).exclude(user__username__iexact='admin').select_related('user__profile')
    for balance in balances.iterator():
        hire = balance.user.profile.hire_date
        policy = next(item for item in active_policies if item.effective_year <= balance.year)
        tenure = balance.year - hire.year
        total = Decimal(next(days for low, days in reversed(policy.bands) if tenure >= low))
        if (balance.total == total and balance.grant_initialized
                and balance.grant_policy_year == policy.effective_year):
            continue
        before = balance.total
        balance.total, balance.grant_initialized = total, True
        balance.grant_policy_year = policy.effective_year
        balance.save(using=alias, update_fields=['total', 'grant_initialized', 'grant_policy_year'])
        Audit.objects.using(alias).create(target_id=balance.user_id,
            event=f'{balance.year}년 입사연도 기준 총연차 적용',
            detail=f'입사일 {hire} / 산정 근무연수 {tenure}년 / 총 {before} → {total} / 기존 사용 {balance.used} 유지')


class Migration(migrations.Migration):
    dependencies = [('workflow', '0013_common_rule_deletion')]
    operations = [
        migrations.AddField(model_name='annualpolicy', name='calendar_tenure_before_2017',
            field=models.BooleanField(default=False), preserve_default=False),
        migrations.AlterField(model_name='annualpolicy', name='calendar_tenure_before_2017',
            field=models.BooleanField(default=True)),
        migrations.RunPython(apply_hire_year_tenure, migrations.RunPython.noop),
    ]
