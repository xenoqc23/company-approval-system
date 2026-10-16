"""Version the new entrant rule without rewriting historical grants or manual totals."""
from decimal import Decimal
from django.db import migrations, models
from django.utils import timezone


def apply_new_entrant_policy(apps, schema_editor):
    alias = schema_editor.connection.alias
    year = timezone.localdate().year
    Policy = apps.get_model('workflow', 'AnnualPolicy')
    Balance = apps.get_model('workflow', 'AnnualBalance')
    Audit = apps.get_model('workflow', 'Audit')
    policy = Policy.objects.using(alias).filter(effective_year=year).first()
    if not policy:
        previous = Policy.objects.using(alias).filter(effective_year__lt=year).order_by('-effective_year').first()
        policy = Policy.objects.using(alias).create(effective_year=year,
            bands=previous.bands if previous else [[0,12],[1,15],[3,16],[5,17],[7,18],[9,19],
                [11,20],[13,21],[15,22],[17,23],[19,24],[21,25]],
            text=previous.text if previous else '', hire_year_monthly=False)
    for record in Policy.objects.using(alias).filter(effective_year__gte=year).order_by('effective_year'):
        before = {'bands': record.bands, 'hire_year_monthly': record.hire_year_monthly}
        bands = [[low, 12 if low == 0 else days] for low, days in record.bands]
        if record.bands == bands and record.hire_year_monthly:
            continue
        record.bands, record.hire_year_monthly = bands, True
        record.version += 1
        record.save(using=alias, update_fields=['bands','hire_year_monthly','version','updated_at'])
        Audit.objects.using(alias).create(event='연차 산정규정 수정',
            detail=f'{record.effective_year}년부터 입사 연도 월수 선부여 / 입사 다음 해 0년차 기본값 부여\n'
                   f'변경 전 {before} / 변경 후 {bands}, 월수 선부여 사용')
    policies = list(Policy.objects.using(alias).filter(effective_year__gte=year).order_by('-effective_year'))
    # Future preapproved leave may already have an initialized grant; correct those too.
    balances = Balance.objects.using(alias).filter(year__gte=year, total_manual=False,
        user__is_active=True, user__is_superuser=False, user__profile__approved=True,
        user__profile__hire_date__isnull=False
        ).exclude(user__username__iexact='admin').select_related('user__profile')
    for balance in balances.iterator():
        hire = balance.user.profile.hire_date
        if balance.year not in (hire.year, hire.year+1):
            continue
        policy = next(record for record in policies if record.effective_year <= balance.year)
        total = Decimal(13-hire.month) if hire.year == balance.year else Decimal(policy.bands[0][1])
        before = balance.total
        balance.total, balance.grant_initialized = total, True
        balance.grant_policy_year = policy.effective_year
        balance.save(using=alias, update_fields=['total','grant_initialized','grant_policy_year'])
        if before != total:
            Audit.objects.using(alias).create(target_id=balance.user_id, event=f'{balance.year}년 신입 연차 산정 적용',
                detail=f'입사일 {hire} / 총 {before} → {total} / 기존 사용 {balance.used} 유지\n'
                       '입사 연도: 입사월~12월 선부여 / 입사 다음 해: 0년차 기본값 / 이후: 기존 근속표')


class Migration(migrations.Migration):
    dependencies = [('workflow','0010_manualleaveusage')]
    operations = [
        # Existing historical policies must retain their original calculation mode.
        migrations.AddField(model_name='annualpolicy', name='hire_year_monthly',
                            field=models.BooleanField(default=False), preserve_default=False),
        migrations.AlterField(model_name='annualpolicy', name='hire_year_monthly',
                              field=models.BooleanField(default=True)),
        migrations.RunPython(apply_new_entrant_policy, migrations.RunPython.noop),
    ]
