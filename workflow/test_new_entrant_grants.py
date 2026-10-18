from datetime import date
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .annual_grants import entitlement, sync_annual_grants, set_hire_date
from .manual_leave import register_manual_leave, cancel_manual_leave
from .models import AnnualBalance, AnnualPolicy, Audit, Profile
from .regulations import annual_policy, recalc_rows, apply_recalculation
from .services import edit_balance


class NewEntrantGrantTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employee = get_user_model().objects.create_user('new_employee', first_name='신입직원')
        Profile.objects.create(user=cls.employee, approved=True, department='품질팀', rank='사원', hire_date=date(2026,6,1))
        cls.finance = get_user_model().objects.create_user('finance', first_name='경리직원')
        Profile.objects.create(user=cls.finance, approved=True, department='인사팀', rank='과장',
                               hire_date=date(2020,1,1), manage_leave=True)
        AnnualBalance.objects.create(user=cls.finance,year=2026,total=17,grant_initialized=True)

    def balance(self,year=2026):
        return AnnualBalance.objects.get(user=self.employee,year=year)

    def test_hire_month_inclusive_immediate_grant_all_months_and_day_independence(self):
        for month in range(1,13):
            for day in [1,15,28]:
                with self.subTest(month=month,day=day):
                    self.assertEqual(entitlement(date(2026,month,day),2026),13-month)
        self.assertEqual(entitlement(date(2026,6,1),2026),7)
        self.assertEqual(entitlement(date(2026,4,15),2026),9)
        self.assertEqual(entitlement(date(2026,12,31),2026),1)
        self.assertEqual(entitlement(date(2027,1,1),2026),0)
        self.assertEqual(entitlement(None,2026),0)

    def test_next_calendar_year_always_12_including_january_first_then_existing_table(self):
        for hire in [date(2026,1,1),date(2026,4,15),date(2026,6,1),date(2026,12,31)]:
            with self.subTest(hire=hire):
                self.assertEqual(entitlement(hire,2027),12)
                self.assertEqual(entitlement(hire,2028),15)
        # Subsequent years still use completed tenure on January 1.
        self.assertEqual(entitlement(date(2026,1,1),2029),16)
        self.assertEqual(entitlement(date(2026,6,1),2029),15)
        self.assertEqual(entitlement(date(1990,1,1),2026),25)

    def test_old_policy_history_preserved_and_new_policy_table_is_12(self):
        old = annual_policy(2025)
        self.assertFalse(old.hire_year_monthly)
        self.assertEqual(old.bands[0],[0,11])
        self.assertEqual(entitlement(date(2025,6,1),2025),11)
        self.assertTrue(annual_policy(2026).hire_year_monthly)
        self.assertEqual(annual_policy(2026).bands[0],[0,12])
        self.assertEqual(entitlement(date(2025,6,1),2026),12)

    def test_initialization_and_rollover_preserve_used_and_do_not_accrue_again_monthly(self):
        AnnualBalance.objects.create(user=self.employee,year=2026,used=Decimal('1.25'))
        self.assertEqual(sync_annual_grants(date(2026,6,1)),1)
        self.assertEqual((self.balance().total,self.balance().used,self.balance().remaining),
                         (7,Decimal('1.25'),Decimal('5.75')))
        self.assertEqual(sync_annual_grants(date(2026,12,1)),0)
        self.assertEqual(self.balance().total,7)
        AnnualBalance.objects.create(user=self.employee,year=2027,used=Decimal('.5'))
        sync_annual_grants(date(2027,1,1))
        self.assertEqual((self.balance(2027).total,self.balance(2027).used),(12,Decimal('.5')))
        sync_annual_grants(date(2028,1,1))
        self.assertEqual(self.balance(2028).total,15)
        self.assertEqual((self.balance().total,self.balance().used),(7,Decimal('1.25')))

    def test_manual_usage_and_cancel_work_with_new_total(self):
        usage,_ = register_manual_leave(self.finance,self.employee,
            {'used_date':date(2026,6,1),'leave_type':'annual','reason':'종이 신청서'},uuid4())
        self.assertEqual((self.balance().total,self.balance().used,self.balance().remaining),(7,1,6))
        cancel_manual_leave(self.finance,self.employee,usage.pk,'오입력')
        self.assertEqual((self.balance().total,self.balance().used,self.balance().remaining),(7,0,7))

    def test_manual_total_kept_until_explicit_recalculation_and_latest_usage_preserved(self):
        edit_balance(self.finance,self.employee,2026,'total',Decimal('20'),'개별 총연차')
        edit_balance(self.finance,self.employee,2026,'used',Decimal('2.5'),'기존 사용')
        sync_annual_grants(date(2026,10,16))
        self.assertEqual(self.balance().total,20)
        policy = annual_policy(2026)
        snapshot = {'year':2026,'policy':[policy.pk,policy.version], 'rows':{
            str(row['user'].pk):{'total':str(row['before']),'manual':row['manual'],'hire':row['hire']}
            for row in recalc_rows(2026)}}
        ids = {str(self.employee.pk)}
        with self.assertRaises(ValidationError):
            apply_recalculation(self.finance,snapshot,ids,set())
        apply_recalculation(self.finance,snapshot,ids,ids)
        self.assertEqual((self.balance().total,self.balance().used,self.balance().remaining),
                         (7,Decimal('2.5'),Decimal('4.5')))

    def test_hire_date_apply_and_policy_views_show_new_rule(self):
        AnnualBalance.objects.create(user=self.employee,year=2026,total=11,used=Decimal('1.25'),grant_initialized=True)
        set_hire_date(self.finance,self.employee,date(2026,4,15),2026,apply=True)
        self.assertEqual((self.balance().total,self.balance().used),(9,Decimal('1.25')))
        self.client.force_login(self.finance)
        for name,params in [('regulations',{'tab':'annual'}),('policy',{}),('welfare',{'tab':'leave'}),('recalculate',{})]:
            with self.subTest(page=name):
                response = self.client.get(reverse(name),params)
                self.assertEqual(response.status_code,200)
                self.assertContains(response,'6월 1일 입사 7일')
                self.assertContains(response,'입사 다음 해는 모두 0년차 기본값')


class NewEntrantMigrationTests(TransactionTestCase):
    def test_actual_upgrade_preserves_manual_historical_usage_and_reprices_future_initialized_grants(self):
        before = [('workflow','0010_manualleaveusage')]
        after = [('workflow','0011_hire_year_monthly')]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        old_apps = executor.loader.project_state(before).apps
        Policy = old_apps.get_model('workflow','AnnualPolicy')
        ProfileModel = old_apps.get_model('workflow','Profile')
        Balance = old_apps.get_model('workflow','AnnualBalance')
        User = old_apps.get_model('auth','User')
        Policy.objects.all().delete()
        bands = [[0,11],[1,15],[3,16],[5,17],[7,18],[9,19],[11,20],[13,21],[15,22],[17,23],[19,24],[21,25]]
        Policy.objects.create(effective_year=2000,bands=bands,text='원래 안내')
        future_bands = [list(row) for row in bands]
        future_bands[3][1] = 18  # A custom nonzero-tenure band must survive the upgrade.
        Policy.objects.create(effective_year=2027,bands=future_bands,text='미래 안내',version=3)
        people = {}
        for name,hire,manual in [
            ('june',date(2026,6,1),False),('april',date(2026,4,15),False),
            ('next_january',date(2025,1,1),False),('next_december',date(2025,12,1),False),
            ('senior',date(2023,4,15),False),('manual',date(2026,6,1),True)]:
            user = User.objects.create(username=name,first_name=name,is_active=True)
            ProfileModel.objects.create(user_id=user.pk,department='품질팀',rank='사원',approved=True,hire_date=hire)
            Balance.objects.create(user_id=user.pk,year=2026,total=20 if manual else 11,
                used=Decimal('2.25'),grant_initialized=True,total_manual=manual)
            people[name] = user.pk
        Balance.objects.create(user_id=people['june'],year=2027,total=11,used=Decimal('.5'),grant_initialized=True)
        Balance.objects.create(user_id=people['april'],year=2025,total=8,used=Decimal('3.25'),grant_initialized=True)
        migration = import_module('workflow.migrations.0011_hire_year_monthly')
        with patch.object(migration.timezone,'localdate',return_value=date(2026,10,16)):
            MigrationExecutor(connection).migrate(after)
            new_policy = AnnualPolicy.objects.get(effective_year=2026)
            self.assertTrue(new_policy.hire_year_monthly)
            self.assertEqual(new_policy.bands[0],[0,12])
            self.assertEqual(new_policy.text,'원래 안내')
            old = AnnualPolicy.objects.get(effective_year=2000)
            self.assertFalse(old.hire_year_monthly)
            self.assertEqual(old.bands,bands)
            future = AnnualPolicy.objects.get(effective_year=2027)
            self.assertEqual((future.bands[0],future.bands[3],future.text),([0,12],[5,18],'미래 안내'))
            expected = {'june':7,'april':9,'next_january':12,'next_december':12,'senior':11,'manual':20}
            for name,total in expected.items():
                balance = AnnualBalance.objects.get(user_id=people[name],year=2026)
                self.assertEqual((balance.total,balance.used),(total,Decimal('2.25')))
            self.assertEqual(AnnualBalance.objects.get(user_id=people['june'],year=2027).total,12)
            old_balance = AnnualBalance.objects.get(user_id=people['april'],year=2025)
            self.assertEqual((old_balance.total,old_balance.used),(8,Decimal('3.25')))
            snapshot = list(AnnualBalance.objects.order_by('pk').values())
            logs = Audit.objects.count()
            revision = list(AnnualPolicy.objects.order_by('pk').values('pk','version'))
            migration.apply_new_entrant_policy(apps,SimpleNamespace(connection=connection))
            self.assertEqual(list(AnnualBalance.objects.order_by('pk').values()),snapshot)
            self.assertEqual(Audit.objects.count(),logs)
            self.assertEqual(list(AnnualPolicy.objects.order_by('pk').values('pk','version')),revision)
