from datetime import date, time
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from .annual_grants import sync_annual_grants
from .manual_leave import cancel_manual_leave, register_manual_leave
from .models import AnnualBalance, ApprovalRule, Audit, Document, ManualLeaveUsage, Profile
from .services import act_on_document, save_document


class ManualLeaveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ApprovalRule.objects.update(enabled=False)
        for name in ['employee', 'finance', 'other', 'approver']:
            user = get_user_model().objects.create_user(name, first_name=name, password='test-only-password')
            Profile.objects.create(user=user, department='품질팀', rank='과장', approved=True,
                                   manage_leave=name == 'finance', hire_date=date(2023, 4, 15))
            setattr(cls, name, user)
        AnnualBalance.objects.create(user=cls.employee, year=2026, total=15, used=3, grant_initialized=True)

    def values(self, **kwargs):
        return dict(used_date=date(2026, 10, 15), leave_type='annual', reason='종이 신청서로 접수', **kwargs)

    def register(self, **kwargs):
        values = self.values()
        values.update(kwargs)
        return register_manual_leave(self.finance, self.employee, values, uuid4())[0]

    def balance(self, year=2026):
        return AnnualBalance.objects.get(user=self.employee, year=year)

    def document(self, **kwargs):
        fields = dict(owner=self.employee, reviewer=self.approver, approver=self.approver,
            start_date=date(2026, 10, 15), end_date=date(2026, 10, 15), reason='휴가')
        fields.update(kwargs)
        return save_document(Document(**fields), self.employee, submit=True)

    def test_registration_adds_to_used_not_replaces_and_audits_without_document(self):
        usage = self.register()
        self.assertEqual((self.balance().total, self.balance().used, self.balance().remaining), (15, 4, 11))
        self.assertEqual((usage.amount, usage.created_by, usage.used_date), (1, self.finance, date(2026, 10, 15)))
        self.assertEqual(Document.objects.count(), 0)
        log = Audit.objects.get(target=self.employee, event='2026년 연차 직접 등록')
        self.assertIn('종이 신청서로 접수', log.detail)

    def test_half_days_nonoverlap_and_outing_follow_existing_charge_rules(self):
        first = self.register(leave_type='am', start_time=time(9), end_time=time(12))
        second = self.register(leave_type='pm', start_time=time(13), end_time=time(17))
        third = self.register(used_date=date(2026, 10, 16), leave_type='outing', start_time=time(10), end_time=time(11))
        self.assertEqual((first.amount, second.amount, third.amount), (Decimal('.5'), Decimal('.5'), Decimal('.25')))
        self.assertEqual(self.balance().used, Decimal('4.25'))

    def test_same_request_replay_including_after_cancel_never_charges_twice(self):
        key = uuid4()
        usage, created = register_manual_leave(self.finance, self.employee, self.values(), key)
        self.assertTrue(created)
        repeat, created = register_manual_leave(self.finance, self.employee, self.values(), key)
        self.assertFalse(created)
        self.assertEqual(usage.pk, repeat.pk)
        self.assertEqual(self.balance().used, 4)
        cancel_manual_leave(self.finance, self.employee, usage.pk, '오입력')
        _, created = register_manual_leave(self.finance, self.employee, self.values(), key)
        self.assertFalse(created)
        self.assertEqual(self.balance().used, 3)
        self.assertEqual(ManualLeaveUsage.objects.count(), 1)

    def test_different_request_on_same_day_and_overlapping_half_days_refused(self):
        self.register(leave_type='am', start_time=time(9), end_time=time(13))
        for values in [dict(leave_type='annual'), dict(leave_type='outing', start_time=time(12), end_time=time(14))]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self.register(**values)
        self.assertEqual(self.balance().used, Decimal('3.5'))

    def test_live_document_blocks_manual_registration_but_cancelled_document_does_not(self):
        doc = self.document()
        with self.assertRaises(ValidationError):
            self.register()
        act_on_document(doc.pk, self.approver, 'review')
        act_on_document(doc.pk, self.approver, 'approve')
        with self.assertRaises(ValidationError):
            self.register()
        act_on_document(doc.pk, self.approver, 'cancel_approval', '직접 등록으로 변경')
        self.register()
        self.assertEqual(self.balance().used, 4)

    def test_manual_registration_blocks_submission_and_approval_until_cancelled(self):
        usage = self.register()
        with self.assertRaises(ValidationError):
            self.document()
        # Defensive final approval check, even for an old draft promoted outside normal submit.
        doc = Document.objects.create(owner=self.employee, approver=self.approver, status='approve',
            start_date=usage.used_date, end_date=usage.used_date, reason='기존 기안')
        with self.assertRaises(ValidationError):
            act_on_document(doc.pk, self.approver, 'approve')
        cancel_manual_leave(self.finance, self.employee, usage.pk, '결재로 처리')
        act_on_document(doc.pk, self.approver, 'approve')
        self.assertEqual(self.balance().used, 4)

    def test_cancellation_restores_only_original_amount_and_keeps_actor_reason(self):
        usage = self.register()
        self.register(used_date=date(2026, 10, 16))
        cancel_manual_leave(self.finance, self.employee, usage.pk, '일정 취소')
        usage.refresh_from_db()
        self.assertEqual(self.balance().used, 4)
        self.assertEqual((usage.cancelled_by, usage.cancel_reason), (self.finance, '일정 취소'))
        with self.assertRaises(ValidationError):
            cancel_manual_leave(self.finance, self.employee, usage.pk, '재시도')
        self.assertEqual(self.balance().used, 4)

    def test_reason_dates_type_and_times_validated_server_side(self):
        for fields in [dict(reason='  '), dict(reason='x'*1001), dict(used_date=date(2026, 10, 17)),
                dict(used_date=date(1999, 1, 1)), dict(leave_type='unknown'), dict(leave_type='am'),
                dict(leave_type='outing', start_time=time(12), end_time=time(11))]:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.register(**fields)
        self.assertEqual(self.balance().used, 3)
        self.assertFalse(ManualLeaveUsage.objects.exists())

    def test_permission_scope_post_only_and_csrf_protection(self):
        usage = self.register()
        new = reverse('manual_leave_new', args=[self.employee.pk])
        cancel = reverse('manual_leave_cancel', args=[self.employee.pk, usage.pk])
        self.client.force_login(self.other)
        for method, url in [(self.client.get, new), (self.client.post, new), (self.client.post, cancel)]:
            self.assertEqual(method(url).status_code, 403)
        with self.assertRaises(PermissionDenied):
            register_manual_leave(self.other, self.employee, self.values(), uuid4())
        self.client.force_login(self.finance)
        self.assertEqual(self.client.get(cancel).status_code, 405)
        self.assertEqual(self.client.post(reverse('manual_leave_cancel', args=[self.other.pk, usage.pk]), {'reason':'취소'}).status_code, 404)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.finance)
        self.assertEqual(secure.post(new, {}).status_code, 403)
        self.assertEqual(secure.post(cancel, {'reason':'취소'}).status_code, 403)
        self.assertEqual(self.balance().used, 4)

    def test_browser_post_and_history_year_filter_cancelled_record_and_safe_reason(self):
        self.client.force_login(self.finance)
        url = reverse('manual_leave_new', args=[self.employee.pk])
        key = self.client.get(url).context['form'].initial['request_key']
        response = self.client.post(url, {'used_date':'2026-10-15', 'leave_type':'annual',
            'reason':'<script>alert(1)</script>', 'request_key':str(key), 'amount':'999'})
        self.assertEqual(response.status_code, 302)
        usage = ManualLeaveUsage.objects.get()
        self.assertEqual(usage.amount, 1)
        history = reverse('leave_history', args=[self.employee.pk])
        response = self.client.get(history, {'year':2026})
        self.assertEqual(response.context['manual_charged'], 1)
        self.assertContains(response, '경리 직접 등록')
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertFalse(self.client.get(history, {'year':2027}).context['leave_rows'])
        self.client.post(reverse('manual_leave_cancel', args=[self.employee.pk, usage.pk]), {'reason':'입력 오류'})
        self.assertFalse(self.client.get(history, {'year':2026}).context['leave_rows'])
        response = self.client.get(history, {'year':2026, 'mode':'all'})
        self.assertContains(response, '입력 오류')
        self.assertContains(response, '등록 취소')
        self.assertEqual(response.context['manual_charged'], 0)

    def test_form_errors_preserve_input_and_require_cancellation_reason(self):
        self.client.force_login(self.finance)
        url = reverse('manual_leave_new', args=[self.employee.pk])
        response = self.client.post(url, {'used_date':'2026-10-15', 'leave_type':'am', 'reason':'남겨둔 사유', 'request_key':str(uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '남겨둔 사유')
        self.assertTrue(response.context['form'].errors)
        usage = self.register()
        self.client.post(reverse('manual_leave_cancel', args=[self.employee.pk, usage.pk]), {'reason':'   '})
        usage.refresh_from_db()
        self.assertIsNone(usage.cancelled_at)

    def test_failure_rolls_back_balance_record_and_audit(self):
        with patch('workflow.services.audit', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):
                self.register()
        self.assertEqual(self.balance().used, 3)
        self.assertFalse(ManualLeaveUsage.objects.exists())
        usage = self.register()
        with patch('workflow.services.audit', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):
                cancel_manual_leave(self.finance, self.employee, usage.pk, '취소')
        usage.refresh_from_db()
        self.assertIsNone(usage.cancelled_at)
        self.assertEqual(self.balance().used, 4)

    def test_next_year_initialization_and_rollover_keep_manual_usage(self):
        self.register(used_date=date(2027, 1, 4))
        self.assertEqual((self.balance(2027).total, self.balance(2027).used), (16, 1))
        sync_annual_grants(date(2027, 1, 1))
        self.assertEqual(self.balance(2027).used, 1)

