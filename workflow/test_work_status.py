"""Integration coverage for read-only dashboard, balances and shared calendars."""
from datetime import date, time
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core import serializers
from django.test import TestCase
from django.urls import reverse

from .calendars import month_grid
from .company_holidays import save_company_holiday, delete_company_holiday
from .leave_records import balance_rows
from .manual_leave import register_manual_leave, cancel_manual_leave
from .models import AnnualBalance, ApprovalRule, Audit, CompanyHoliday, CompanyLeaveCharge, Document, ManualLeaveUsage, Profile
from .services import act_on_document, save_document, edit_balance


class WorkStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ApprovalRule.objects.update(enabled=False)
        for name in ['employee', 'reviewer', 'approver', 'finance', 'other', 'admin']:
            user = get_user_model().objects.create_user(name, first_name=name, password='test-only-password')
            Profile.objects.create(user=user, department='개발팀', rank='대리', approved=True,
                hire_date=date(2020, 1, 1), manage_leave=name == 'finance', manage_system=name == 'admin')
            AnnualBalance.objects.create(user=user, year=2026, total=20, used=Decimal('2.25'), grant_initialized=True)
            setattr(cls, name, user)

    def leave(self, **kwargs):
        values = dict(owner=self.employee, reviewer=self.reviewer, approver=self.approver,
            start_date=date(2026, 10, 19), end_date=date(2026, 10, 19), reason='private document reason')
        values.update(kwargs)
        return save_document(Document(**values), values['owner'], submit=True)

    def manual(self, **kwargs):
        values = dict(used_date=date(2026, 10, 20), leave_type='annual', reason='private manual reason')
        values.update(kwargs)
        return register_manual_leave(self.finance, self.employee, values, uuid4())[0]

    def holiday(self, **kwargs):
        values = dict(title='공용 휴가', day=date(2026, 10, 23), use_annual=True, description='')
        values.update(kwargs)
        return save_company_holiday(self.finance, values)

    def days(self, viewer=None, year=2026, month=10):
        grid = month_grid(year, month, viewer or self.other)
        return {day['date']: day for week in grid['weeks'] for day in week}

    def home(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('dashboard'))

    def test_pending_counts_only_current_assigned_action_and_view_does_not_clear_it(self):
        doc = self.leave()
        self.leave(reviewer=self.other, approver=self.other, start_date=date(2026, 10, 21), end_date=date(2026, 10, 21))
        response = self.home(self.reviewer)
        self.assertEqual(response.context['nav_waiting'], 1)
        self.assertEqual(response.context['progress_count'], 0)
        self.assertContains(response, 'aria-label="내가 처리할 미결 1건"')
        self.assertEqual(self.client.get(reverse('detail', args=[doc.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('dashboard')).context['nav_waiting'], 1)
        self.assertEqual(self.home(self.approver).context['nav_waiting'], 0)
        self.assertEqual(self.home(self.admin).context['nav_waiting'], 0)
        act_on_document(doc.pk, self.reviewer, 'review')
        self.assertEqual(self.home(self.reviewer).context['nav_waiting'], 0)
        self.assertEqual(self.home(self.approver).context['nav_waiting'], 1)
        response = self.client.get(reverse('documents'), {'mode': 'pending'})
        self.assertEqual(list(response.context['documents']), [Document.objects.get(pk=doc.pk)])
        act_on_document(doc.pk, self.approver, 'approve')
        self.assertEqual(self.home(self.approver).context['nav_waiting'], 0)
        self.assertEqual(self.home(self.employee).context['progress_count'], 1)

    def test_rejected_cancelled_drafts_and_same_person_in_two_roles_are_not_double_counted(self):
        self.leave(reviewer=self.reviewer, approver=self.reviewer)
        for status in ['approved', 'rejected', 'cancelled', 'draft', 'deleted']:
            Document.objects.create(owner=self.employee, reviewer=self.reviewer, approver=self.reviewer, status=status)
        self.assertEqual(self.home(self.reviewer).context['nav_waiting'], 1)

    def test_personal_usage_includes_existing_adjustments_and_manual_but_excludes_common(self):
        self.holiday()
        usage = self.manual(leave_type='am', start_time=time(9), end_time=time(12))
        row = next(row for row in balance_rows(2026) if row['user'] == self.employee)
        self.assertEqual((row['common'], row['personal_used'], row['remaining']), (1, Decimal('2.75'), Decimal('16.25')))
        self.assertEqual(row['available'] - row['personal_used'], row['remaining'])
        cancel_manual_leave(self.finance, self.employee, usage.pk, '오입력')
        row = balance_rows(2026, user=self.employee)[0]
        self.assertEqual(row['personal_used'], Decimal('2.25'))
        self.client.force_login(self.finance)
        response = self.client.get(reverse('balances'), {'year': 2026})
        self.assertContains(response, '<th>개인 사용연차</th>', html=True)
        self.assertContains(response, '직접 등록·조정 포함')

    def test_negative_personal_correction_is_preserved_and_years_remain_separate(self):
        self.holiday()
        edit_balance(self.finance, self.employee, 2026, 'used', Decimal('.5'), '기존 잔액 정정')
        AnnualBalance.objects.create(user=self.employee, year=2025, total=19, used=3, grant_initialized=True)
        self.assertEqual(balance_rows(2026, user=self.employee)[0]['personal_used'], Decimal('-.5'))
        self.assertEqual(balance_rows(2025, user=self.employee)[0]['personal_used'], 3)

    def test_manual_calendar_visible_to_staff_without_private_reason_or_manager_link(self):
        usage = self.manual(leave_type='outing', start_time=time(10), end_time=time(11))
        self.manual(used_date=date(2026, 11, 2))
        self.client.force_login(self.other)
        response = self.client.get(reverse('calendar'), {'year': 2026, 'month': 10})
        self.assertContains(response, 'employee · 외출')
        self.assertContains(response, '직접 등록 · 10:00~11:00')
        self.assertNotContains(response, usage.reason)
        self.assertNotContains(response, reverse('leave_history', args=[self.employee.pk]))
        event, = self.days()[usage.used_date]['events']
        self.assertEqual(event['url'], '')
        event, = self.days(self.finance)[usage.used_date]['events']
        self.assertEqual(event['url'], reverse('leave_history', args=[self.employee.pk]) + '?year=2026')
        cancel_manual_leave(self.finance, self.employee, usage.pk, '취소')
        self.assertEqual(self.days()[usage.used_date]['events'], [])
        self.assertTrue(ManualLeaveUsage.objects.filter(pk=usage.pk).exists())

    def test_approved_leave_and_manual_both_show_and_today_schedule_includes_manual(self):
        doc = self.leave()
        act_on_document(doc.pk, self.reviewer, 'review')
        act_on_document(doc.pk, self.approver, 'approve')
        usage = self.manual()
        days = self.days()
        self.assertTrue(days[doc.start_date]['events'])
        self.assertTrue(days[usage.used_date]['events'])
        from .home import today_schedules
        self.assertIn('직접 등록', today_schedules(self.other, usage.used_date)[0]['subtitle'])

    def test_common_day_color_flag_removed_on_delete_or_type_change_and_not_ordinary_holiday(self):
        holiday = self.holiday()
        self.assertTrue(self.days()[holiday.day]['common_leave'])
        self.client.force_login(self.other)
        response = self.client.get(reverse('calendar'), {'year': 2026, 'month': 10})
        self.assertContains(response, 'class="mobile-agenda-day common-leave-day"')
        save_company_holiday(self.finance, dict(title=holiday.title, day=holiday.day, use_annual=False, description=''), holiday.pk)
        self.assertFalse(self.days()[holiday.day]['common_leave'])
        self.assertTrue(self.days()[holiday.day]['events'])
        save_company_holiday(self.finance, dict(title=holiday.title, day=holiday.day, use_annual=True, description=''), holiday.pk)
        delete_company_holiday(self.finance, holiday.pk)
        self.assertFalse(self.days()[holiday.day]['common_leave'])
        self.assertEqual(self.days()[holiday.day]['events'], [])

    def test_display_reads_preserve_all_existing_registered_data(self):
        self.holiday()
        self.manual()
        self.leave()
        models = [get_user_model(), Profile, AnnualBalance, Document, ManualLeaveUsage, CompanyHoliday, CompanyLeaveCharge, Audit]
        def snapshot():
            return [serializers.serialize('json', model.objects.order_by('pk')) for model in models]
        self.client.force_login(self.finance)
        before = snapshot()
        with patch('workflow.annual_grants.timezone.localdate', return_value=date(2026, 10, 16)):
            for route, params in [('dashboard', {}), ('balances', {'year':2026}), ('calendar', {'year':2026, 'month':10})]:
                self.assertEqual(self.client.get(reverse(route), params).status_code, 200)
        self.assertEqual(snapshot(), before)
