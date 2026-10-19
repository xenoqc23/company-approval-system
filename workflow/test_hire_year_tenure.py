from datetime import date
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .annual_grants import completed_years, entitlement, grant_tenure
from .exports import leave_balances_workbook
from .leave_records import balance_rows
from .models import AnnualBalance, AnnualPolicy, Audit, Profile
from .regulations import annual_policy, DEFAULT_BANDS, save_annual_policy


class HireYearTenureTests(TestCase):
    def test_cutoff_uses_hire_year_not_sliding_seniority_or_current_date(self):
        for month, day in [(1, 1), (1, 2), (6, 20), (12, 31)]:
            with self.subTest(month=month, day=day):
                self.assertEqual(grant_tenure(date(2016, month, day), 2026), 10)
                self.assertEqual(entitlement(date(2016, month, day), 2026), 19)
                self.assertEqual(grant_tenure(date(2016, month, day), 2027), 11)
                self.assertEqual(entitlement(date(2016, month, day), 2027), 20)
        self.assertEqual((grant_tenure(date(2017, 1, 1), 2026), entitlement(date(2017, 1, 1), 2026)), (9, 19))
        self.assertEqual((grant_tenure(date(2017, 1, 2), 2026), entitlement(date(2017, 1, 2), 2026)), (8, 18))
        self.assertEqual((grant_tenure(date(2017, 12, 31), 2026), entitlement(date(2017, 12, 31), 2026)), (8, 18))
        self.assertEqual(entitlement(date(2017, 12, 31), 2027), 19)
        self.assertEqual((grant_tenure(date(2005, 6, 20), 2026), entitlement(date(2005, 6, 20), 2026)), (21, 25))
        self.assertEqual(entitlement(date(2011, 11, 1), 2026), 22)

    def test_new_entrants_and_other_full_tenure_consumers_unchanged(self):
        for month in range(1, 13):
            for day in [1, 15, 28]:
                hire = date(2026, month, day)
                self.assertEqual(entitlement(hire, 2026), 13-month)
                self.assertEqual(entitlement(hire, 2027), 12)
                self.assertEqual(entitlement(hire, 2028), 15)
        self.assertEqual(entitlement(None, 2026), 0)
        self.assertEqual(entitlement(date(2027, 1, 1), 2026), 0)
        self.assertEqual(completed_years(date(2016, 6, 20), date(2026, 1, 1)), 9)
        self.assertEqual(entitlement(date(1980, 6, 20), 2026), 25)

    def test_historical_policy_and_custom_bands_are_respected(self):
        self.assertFalse(annual_policy(2025).calendar_tenure_before_2017)
        self.assertEqual(grant_tenure(date(2016, 6, 20), 2025), 8)
        policy = annual_policy(2026)
        bands = [list(row) for row in DEFAULT_BANDS]
        bands[5][1] = 23
        policy.bands = bands
        policy.save()
        self.assertEqual(entitlement(date(2016, 6, 20), 2026), 23)

    def test_balances_excel_policy_and_future_policy_save_share_calculation(self):
        user = get_user_model().objects.create_user('cutoff-finance', first_name='검증직원')
        Profile.objects.create(user=user, department='개발팀', rank='과장', approved=True,
            hire_date=date(2016, 12, 31), manage_leave=True)
        AnnualBalance.objects.create(user=user, year=2026, total=19, used=Decimal('2.25'), grant_initialized=True)
        row, = balance_rows(2026)
        self.assertEqual((row['tenure'], row['calculated'], row['remaining']), (10, 19, Decimal('16.75')))
        book = leave_balances_workbook([row], 2026)
        self.assertEqual((book['인원별 연차표']['B2'].value, book['인원별 연차표']['C2'].value), (10, 19))
        self.client.force_login(user)
        for name, params in [('regulations', {'tab':'annual'}), ('policy', {}),
                             ('welfare', {'tab':'leave'}), ('recalculate', {})]:
            response = self.client.get(reverse(name), params)
            self.assertContains(response, '2016년까지 입사자')
            self.assertContains(response, '1월 1일 기준 만 근속연수')
        future = save_annual_policy(user, 2027, DEFAULT_BANDS, '기존 안내')
        self.assertTrue(future.calendar_tenure_before_2017)
        self.assertEqual(entitlement(date(2016, 12, 31), 2027), 20)


class HireYearTenureMigrationTests(TransactionTestCase):
    def test_upgrade_changes_only_current_future_automatic_old_hires_and_is_idempotent(self):
        before = [('workflow', '0013_common_rule_deletion')]
        after = [('workflow', '0014_hire_year_tenure')]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        old = executor.loader.project_state(before).apps
        Policy = old.get_model('workflow', 'AnnualPolicy')
        Balance = old.get_model('workflow', 'AnnualBalance')
        User = old.get_model('auth', 'User')
        Policy.objects.all().delete()
        Policy.objects.create(effective_year=2000, bands=DEFAULT_BANDS, text='보존 안내', hire_year_monthly=True)
        custom = [list(row) for row in DEFAULT_BANDS]; custom[6][1] = 23
        Policy.objects.create(effective_year=2027, bands=custom, text='미래 안내', version=4)
        ids = {}
        for name, hire, manual, active, approved in [
            ('auto', date(2016, 12, 31), False, True, True),
            ('manual', date(2016, 12, 31), True, True, True),
            ('later', date(2017, 12, 31), False, True, True),
            ('new', date(2026, 4, 15), False, True, True),
            ('inactive', date(2016, 12, 31), False, False, True),
            ('pending', date(2016, 12, 31), False, True, False)]:
            user = User.objects.create(username=name, password='preserved-hash', is_active=active)
            old.get_model('workflow', 'Profile').objects.create(user_id=user.pk, approved=approved,
                department='개발팀', rank='과장', hire_date=hire)
            ids[name] = user.pk
            Balance.objects.create(user_id=user.pk, year=2026, total=18, used=Decimal('2.25'),
                total_manual=manual, grant_initialized=True, grant_policy_year=2000)
        Balance.objects.create(user_id=ids['auto'], year=2025, total=17, used=Decimal('1.25'), grant_initialized=True)
        Balance.objects.create(user_id=ids['auto'], year=2027, total=19, used=Decimal('.5'), grant_initialized=True)
        old.get_model('workflow', 'ManualLeaveUsage').objects.create(employee_id=ids['auto'],
            created_by_id=ids['manual'], used_date=date(2026, 10, 16), amount=1, reason='기존 등록')
        old.get_model('workflow', 'Document').objects.create(owner_id=ids['auto'], status='approved',
            allocations={'2026':'1.25'}, route_snapshot={'name':'기존 결재선'})
        preserved = {name: list(old.get_model('workflow', name).objects.order_by('pk').values())
            for name in ['Profile', 'Document', 'ManualLeaveUsage', 'CompanyLeaveCharge', 'ApprovalRule']}
        migration = import_module('workflow.migrations.0014_hire_year_tenure')
        with patch.object(migration.timezone, 'localdate', return_value=date(2026, 10, 19)):
            MigrationExecutor(connection).migrate(after)
            current = MigrationExecutor(connection).loader.project_state(after).apps
            for name, rows in preserved.items():
                self.assertEqual(list(current.get_model('workflow', name).objects.order_by('pk').values()), rows, name)
            self.assertEqual(list(User.objects.values_list('password', flat=True)), ['preserved-hash']*6)
            for name, pk in ids.items():
                b = AnnualBalance.objects.get(user_id=pk, year=2026)
                self.assertEqual((b.total, b.used, b.total_manual), (19 if name=='auto' else 18, Decimal('2.25'), name=='manual'))
            self.assertEqual((AnnualBalance.objects.get(user_id=ids['auto'], year=2027).total,
                              AnnualBalance.objects.get(user_id=ids['auto'], year=2027).used), (23, Decimal('.5')))
            self.assertEqual(AnnualBalance.objects.get(user_id=ids['auto'], year=2025).total, 17)
            self.assertFalse(annual_policy(2025).calendar_tenure_before_2017)
            self.assertEqual((annual_policy(2026).bands, annual_policy(2026).text), (DEFAULT_BANDS, '보존 안내'))
            self.assertEqual((annual_policy(2027).bands, annual_policy(2027).text, annual_policy(2027).version), (custom, '미래 안내', 5))
            snapshot = list(AnnualBalance.objects.order_by('pk').values())
            policies = list(AnnualPolicy.objects.order_by('pk').values())
            count = Audit.objects.count()
            migration.apply_hire_year_tenure(current, SimpleNamespace(connection=connection))
            self.assertEqual(list(AnnualBalance.objects.order_by('pk').values()), snapshot)
            self.assertEqual(list(AnnualPolicy.objects.order_by('pk').values()), policies)
            self.assertEqual(Audit.objects.count(), count)
