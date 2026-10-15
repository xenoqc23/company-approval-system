"""Real row-lock checks; intentionally skipped by the SQLite PC runner."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, skipUnlessDBFeature
from workflow.models import AnnualBalance, ApprovalRule, CompanyHolidayLock, Document, Profile, RegulationLock
from workflow.services import act_on_document, save_document
from workflow.company_holidays import save_company_holiday


@skipUnlessDBFeature('has_select_for_update')
class MariaDBConcurrencyTests(TransactionTestCase):
    def setUp(self):
        ApprovalRule.objects.update(enabled=False)
        RegulationLock.objects.get_or_create(pk=1)
        CompanyHolidayLock.objects.get_or_create(pk=1)
        self.people = {}
        for name in ['owner', 'reviewer', 'approver', 'finance']:
            user = get_user_model().objects.create_user(name, first_name=name, password='1234')
            Profile.objects.create(user=user, department='개발팀', rank='과장', approved=True,
                                   hire_date=date(2010, 1, 1), manage_leave=name == 'finance')
            self.people[name] = user
        AnnualBalance.objects.create(user=self.people['owner'], year=2026, total=22, used=0, grant_initialized=True)

    def run_parallel(self, *operations):
        barrier = Barrier(len(operations))
        def run(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SET SESSION innodb_lock_wait_timeout=10')
                barrier.wait(timeout=10)
                try:
                    operation()
                    return 'ok'
                except (PermissionDenied, ValidationError):
                    return 'refused'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            return [future.result(timeout=30) for future in futures]

    def leave(self, day):
        doc = Document(owner=self.people['owner'], reviewer=self.people['reviewer'], approver=self.people['approver'],
                       kind='leave', leave_type='annual', start_date=day, end_date=day, reason='개인 일정')
        return save_document(doc, self.people['owner'], submit=True)

    def ready(self, day):
        doc = self.leave(day)
        return act_on_document(doc.pk, self.people['reviewer'], 'review')

    def test_duplicate_approval_charges_once(self):
        doc = self.ready(date(2026, 10, 19))
        operation = lambda: act_on_document(doc.pk, self.people['approver'], 'approve')
        self.assertCountEqual(self.run_parallel(operation, operation), ['ok', 'refused'])
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'], year=2026).used, 1)

    def test_two_documents_of_same_employee_preserve_both_charges(self):
        first, second = [self.ready(date(2026, 10, day)) for day in [19, 20]]
        self.assertEqual(self.run_parallel(
            lambda: act_on_document(first.pk, self.people['approver'], 'approve'),
            lambda: act_on_document(second.pk, self.people['approver'], 'approve')), ['ok', 'ok'])
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'], year=2026).used, 2)

    def test_concurrent_same_day_submissions_cannot_overlap(self):
        operation = lambda: self.leave(date(2026, 10, 19))
        self.assertCountEqual(self.run_parallel(operation, operation), ['ok', 'refused'])
        self.assertEqual(Document.objects.count(), 1)

    def test_company_holiday_and_personal_approval_preserve_both_charges(self):
        doc = self.ready(date(2026, 10, 19))
        values = {'title':'회사 휴무', 'day':date(2026, 10, 20), 'use_annual':True, 'description':''}
        self.assertEqual(self.run_parallel(
            lambda: act_on_document(doc.pk, self.people['approver'], 'approve'),
            lambda: save_company_holiday(self.people['finance'], values)), ['ok', 'ok'])
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'], year=2026).used, 2)
