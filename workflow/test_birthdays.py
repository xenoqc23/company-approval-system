from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse

from .birthdays import birthday_values, birthday_dates, birthday_period, birthday_rows, lunar_birthday, save_birthday
from .forms import BirthdayForm
from .models import AnnualBalance, Audit, Profile


class BirthdayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employee = cls.person('birthday-staff', '생일직원', month=10, day=19)
        cls.finance = cls.person('birthday-finance', '관리담당', manage_leave=True)
        cls.lunar = cls.person('birthday-lunar', '음력직원', month=9, day=9, calendar='lunar')
        cls.other = cls.person('birthday-other', '다른직원', month=10, day=5)
        cls.missing = cls.person('birthday-missing', '미등록직원')

    @staticmethod
    def person(username, name, month=None, day=None, calendar='solar', **flags):
        user = get_user_model().objects.create_user(username, first_name=name, password='birthday-test-only')
        Profile.objects.create(user=user, department='개발팀', rank='과장', approved=True,
            hire_date=date(2020, 6, 20), birthday_month=month, birthday_day=day, birthday_calendar=calendar, **flags)
        AnnualBalance.objects.create(user=user, year=2026, total=Decimal('19.25'), used=Decimal('2.5'),
            total_manual=True, grant_initialized=True)
        return user

    def test_real_korean_calendar_reference_dates_and_yearly_recalculation(self):
        self.assertEqual(lunar_birthday(2026, 1, 1, False), date(2026, 2, 17))
        self.assertEqual(lunar_birthday(2026, 9, 9, False), date(2026, 10, 19))
        self.assertEqual(lunar_birthday(2025, 6, 1, True), date(2025, 7, 25))
        self.assertEqual(lunar_birthday(2026, 6, 1, True), date(2026, 7, 14))
        self.assertEqual(lunar_birthday(2026, 2, 30, False), date(2026, 4, 16))
        self.assertEqual(lunar_birthday(2025, 9, 9, False), date(2025, 10, 29))

    def test_lunar_december_is_queried_from_previous_lunar_year(self):
        profile = self.lunar.profile
        profile.birthday_month, profile.birthday_day = 12, 1
        self.assertIn(date(2026, 1, 19), birthday_dates(profile, 2026))
        self.assertTrue(all(day.year==2026 for day in birthday_dates(profile, 2026)))

    def test_valid_solar_leap_day_lunar_february_30_and_invalid_values(self):
        self.assertEqual(birthday_values(2, 29)['birthday_day'], 29)
        self.assertEqual(birthday_values(2, 30, 'lunar')['birthday_day'], 30)
        for args in [(2,30), (4,31), (0,10), (13,1), (10,None), (None,1),
                     (2,31,'lunar'), (10,1,'invalid'), (10,1,'solar',True)]:
            with self.subTest(args=args), self.assertRaises(ValidationError):
                birthday_values(*args)
        self.assertEqual(birthday_values(None,None,'lunar',True), birthday_values(None,None))
        profile=self.employee.profile;profile.birthday_month,profile.birthday_day=2,29
        self.assertEqual(birthday_dates(profile,2026),[])
        self.assertEqual(birthday_dates(profile,2028),[date(2028,2,29)])

    def test_month_filters_and_same_day_flags_use_converted_solar_dates(self):
        rows=birthday_rows(2026,10,date(2026,10,19))
        self.assertEqual([row['employee'].pk for row in rows],[self.other.pk,self.employee.pk,self.lunar.pk])
        self.assertEqual([row['today'] for row in rows],[False,True,True])
        self.assertFalse(birthday_rows(2026,11))
        self.assertEqual(birthday_period({'year':'2027','month':'1'},date(2026,12,20)),(2027,1))
        for params in [{'month':'13'},{'month':'oops'},{'year':'9999'}]:
            self.assertEqual(birthday_period(params,date(2026,10,19)),(2026,10))

    def test_unapproved_unclassified_inactive_and_admin_do_not_appear(self):
        for key in ['approved','department_confirmed']:
            person=self.person('exclude-'+key,key,month=10,day=19)
            setattr(person.profile,key,False);person.profile.save()
        inactive=self.person('inactive','퇴사직원',month=10,day=19)
        inactive.is_active=False;inactive.save()
        admin=self.person('admin','시스템관리자',month=10,day=19)
        superuser=self.person('super','최고관리자',month=10,day=19)
        superuser.is_superuser=True;superuser.save()
        self.assertEqual({row['employee'].pk for row in birthday_rows(2026,10)},
            {self.employee.pk,self.lunar.pk,self.other.pk})

    def test_signup_requires_original_birthday_and_preserves_pending_approval(self):
        data={'first_name':'신규생일직원','username':'new-birthday','password1':'1234','password2':'1234',
              'department':'생산팀','rank':'사원'}
        self.assertEqual(self.client.post(reverse('signup'),data).status_code,200)
        self.assertFalse(get_user_model().objects.filter(username='new-birthday').exists())
        data.update(birthday_calendar='lunar',birthday_month='2',birthday_day='30',birthday_lunar_leap='on')
        self.assertRedirects(self.client.post(reverse('signup'),data),reverse('login'))
        profile=Profile.objects.get(user__username='new-birthday')
        self.assertEqual((profile.birthday_calendar,profile.birthday_month,profile.birthday_day,profile.birthday_lunar_leap),
                         ('lunar',2,30,True))
        self.assertFalse(profile.approved)
        self.assertFalse(profile.department_confirmed)

    def test_manager_save_clear_and_repeat_never_change_hire_date_or_balances(self):
        self.client.force_login(self.finance)
        before=list(AnnualBalance.objects.order_by('pk').values())
        hire=self.employee.profile.hire_date
        data={'operation':'birthday','user':self.employee.pk,'year':'2026','birthday_calendar':'lunar',
              'birthday_month':'6','birthday_day':'1','birthday_lunar_leap':'on'}
        self.assertEqual(self.client.post(reverse('balances'),data).status_code,302)
        self.employee.profile.refresh_from_db()
        self.assertEqual(self.employee.profile.birthday_calendar,'lunar')
        self.assertTrue(self.employee.profile.birthday_lunar_leap)
        self.assertEqual(self.employee.profile.hire_date,hire)
        self.assertEqual(list(AnnualBalance.objects.order_by('pk').values()),before)
        count=Audit.objects.filter(event='직원 생일 수정').count()
        self.client.post(reverse('balances'),data)
        self.assertEqual(Audit.objects.filter(event='직원 생일 수정').count(),count)
        data.update(birthday_calendar='solar',birthday_month='',birthday_day='')
        data.pop('birthday_lunar_leap')
        self.client.post(reverse('balances'),data)
        self.employee.profile.refresh_from_db()
        self.assertIsNone(self.employee.profile.birthday_month)
        self.assertEqual(list(AnnualBalance.objects.order_by('pk').values()),before)

    def test_invalid_dates_and_employee_write_attempts_are_rejected(self):
        form=BirthdayForm({'birthday_calendar':'solar','birthday_month':'2','birthday_day':'30'})
        self.assertFalse(form.is_valid())
        self.client.force_login(self.employee)
        self.assertEqual(self.client.post(reverse('balances'),{'operation':'birthday','user':self.other.pk}).status_code,403)
        with self.assertRaises(PermissionDenied):
            save_birthday(self.employee,self.other,birthday_values(10,20))
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.finance)
        self.assertEqual(csrf.post(reverse('balances'),{'operation':'birthday','user':self.employee.pk}).status_code,403)
        self.employee.profile.refresh_from_db()
        self.assertEqual(self.employee.profile.birthday_day,19)

    def test_welfare_default_tab_today_badge_month_selection_and_manager_only_missing(self):
        with patch('django.utils.timezone.localdate',return_value=date(2026,10,19)):
            self.client.force_login(self.employee)
            response=self.client.get(reverse('welfare'))
            self.assertEqual(response.context['tab'],'birthdays')
            self.assertContains(response,'오늘 생일 🎉',count=2)
            self.assertContains(response,'음력 9월 9일')
            self.assertNotContains(response,'생일 미등록 직원')
            response=self.client.get(reverse('welfare'),{'tab':'birthdays','month':'11'})
            self.assertContains(response,'11월에는 등록된 생일자가 없습니다.')
            self.client.force_login(self.finance)
            response=self.client.get(reverse('welfare'))
            self.assertContains(response,'생일 미등록 직원 2명')
            self.assertContains(response,f'#birthday-employee-{self.missing.pk}')
            self.assertContains(self.client.get(reverse('balances')),'입사일·생일·연차 관리')

    def test_december_next_month_link_rolls_over_to_january(self):
        self.client.force_login(self.employee)
        with patch('django.utils.timezone.localdate',return_value=date(2026,12,20)):
            response=self.client.get(reverse('welfare'))
        self.assertEqual((response.context['birthday_next_year'],response.context['birthday_next_month']),(2027,1))
        self.assertContains(response,'year=2027&month=1')

    def test_home_uses_korean_day_and_includes_all_today_birthdays_only(self):
        self.client.force_login(self.finance)
        with patch('django.utils.timezone.now',return_value=datetime(2026,10,18,15,10,tzinfo=dt_timezone.utc)):
            response=self.client.get(reverse('dashboard'))
        self.assertContains(response,'생일을 축하합니다!')
        self.assertContains(response,'생일직원님')
        self.assertContains(response,'음력직원님')
        self.assertNotContains(response,'다른직원님')
        self.assertContains(response,'birthday-cake.svg')
        with patch('django.utils.timezone.localdate',return_value=date(2026,10,20)):
            self.assertNotContains(self.client.get(reverse('dashboard')),'생일을 축하합니다!')

    def test_database_constraints_reject_partial_and_impossible_birthdays(self):
        for values in [dict(birthday_month=2,birthday_day=30),dict(birthday_month=None,birthday_day=1),
                       dict(birthday_month=10,birthday_day=19,birthday_lunar_leap=True)]:
            with self.subTest(values=values),self.assertRaises(IntegrityError),transaction.atomic():
                Profile.objects.filter(user=self.employee).update(**values)

    def test_awards_explain_year_end_presentation_for_all_anniversary_dates(self):
        self.employee.profile.hire_date=date(2023,11,16);self.employee.profile.save()
        self.other.profile.hire_date=date(2023,3,1);self.other.profile.save()
        self.client.force_login(self.employee)
        response=self.client.get(reverse('welfare'),{'tab':'awards','year':'2026'})
        self.assertContains(response,'연말 종무식 포상 예정',count=2)
        self.assertContains(response,'포상 안내')
        self.assertNotContains(response,'대상일 도래')


class BirthdayMigrationTests(TransactionTestCase):
    def test_additive_upgrade_preserves_every_existing_business_value(self):
        before=[('workflow','0014_hire_year_tenure')]
        after=[('workflow','0015_employee_birthdays')]
        executor=MigrationExecutor(connection);executor.migrate(before)
        self.addCleanup(lambda:MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        old=executor.loader.project_state(before).apps
        user=old.get_model('auth','User').objects.create(username='existing-birthday-migration',password='preserved-hash')
        old.get_model('workflow','Profile').objects.create(user_id=user.pk,department='개발팀',rank='과장',approved=True,hire_date=date(2005,6,20))
        old.get_model('workflow','AnnualBalance').objects.create(user_id=user.pk,year=2026,total=25,used=Decimal('3.25'),total_manual=True,grant_initialized=True)
        old.get_model('workflow','Document').objects.create(owner_id=user.pk,status='approved',allocations={'2026':'1'},route_snapshot={'name':'보존 경로'})
        names=['Profile','Document','AnnualBalance','AnnualPolicy','ManualLeaveUsage','CompanyLeaveCharge','ApprovalRule','Audit']
        snapshots={name:list(old.get_model('workflow',name).objects.order_by('pk').values()) for name in names}
        MigrationExecutor(connection).migrate(after)
        current=MigrationExecutor(connection).loader.project_state(after).apps
        for name,rows in snapshots.items():
            fields=list(rows[0]) if rows else ['pk']
            self.assertEqual(list(current.get_model('workflow',name).objects.order_by('pk').values(*fields)),rows,name)
        p=current.get_model('workflow','Profile').objects.get(user_id=user.pk)
        self.assertEqual((p.birthday_month,p.birthday_day,p.birthday_calendar,p.birthday_lunar_leap),(None,None,'solar',False))
        self.assertEqual(get_user_model().objects.get(pk=user.pk).password,'preserved-hash')
