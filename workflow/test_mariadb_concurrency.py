"""Real row-lock checks; intentionally skipped by the SQLite PC runner."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, skipUnlessDBFeature
from workflow.models import AnnualBalance, ApprovalRule, CompanyHolidayLock, Document, Profile, RegulationLock
from workflow.services import act_on_document, save_document
from workflow.company_holidays import save_company_holiday
from workflow.manual_leave import register_manual_leave, cancel_manual_leave
from workflow.models import ManualLeaveUsage


@skipUnlessDBFeature('has_select_for_update')
class MariaDBConcurrencyTests(TransactionTestCase):
    def setUp(self):
        from .models import ApprovalFlowPolicy
        ApprovalFlowPolicy.objects.update_or_create(pk=1, defaults={'enabled':False})
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

    def manual(self, day, key=None):
        return register_manual_leave(self.people['finance'], self.people['owner'],
            {'used_date': day, 'leave_type': 'annual', 'reason': '종이 신청서'}, key or uuid4())

    def test_two_manual_registrations_preserve_both_charges(self):
        self.assertEqual(self.run_parallel(
            lambda: self.manual(date(2026,10,19)), lambda: self.manual(date(2026,10,20))), ['ok','ok'])
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'], year=2026).used, 2)

    def test_replayed_manual_request_charges_once(self):
        key = uuid4()
        operation = lambda: self.manual(date(2026,10,19), key)
        self.assertEqual(self.run_parallel(operation, operation), ['ok','ok'])
        self.assertEqual(ManualLeaveUsage.objects.count(), 1)
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'], year=2026).used, 1)

    def test_simultaneous_manual_and_submission_cannot_double_book(self):
        self.assertCountEqual(self.run_parallel(
            lambda: self.manual(date(2026,10,19)), lambda: self.leave(date(2026,10,19))), ['ok','refused'])
        self.assertEqual(ManualLeaveUsage.objects.count() + Document.objects.count(), 1)

    def test_simultaneous_cancellation_restores_once(self):
        usage, _ = self.manual(date(2026,10,19))
        operation = lambda: cancel_manual_leave(self.people['finance'], self.people['owner'], usage.pk, '취소')
        self.assertCountEqual(self.run_parallel(operation, operation), ['ok','refused'])
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'], year=2026).used, 0)

    def test_manual_and_approval_on_other_day_preserve_both_charges(self):
        doc = self.ready(date(2026,10,19))
        self.assertEqual(self.run_parallel(
            lambda: self.manual(date(2026,10,20)),
            lambda: act_on_document(doc.pk, self.people['approver'], 'approve')), ['ok','ok'])
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'], year=2026).used, 2)

    def self_draft(self):
        ApprovalRule.objects.create(name='동시 전결 검증',kind='leave',reviewer_ranks=['과장'],approver_ranks=['과장'],allow_self_approval=True,enabled=True)
        return save_document(Document(owner=self.people['owner'],approval_mode='self',kind='leave',
            start_date=date(2026,10,19),end_date=date(2026,10,19),reason='동시 전결'),self.people['owner'])

    def test_simultaneous_self_submission_of_same_draft_charges_once(self):
        doc=self.self_draft()
        def submit():
            save_document(Document.objects.get(pk=doc.pk),self.people['owner'],submit=True)
        self.assertCountEqual(self.run_parallel(submit,submit),['ok','refused'])
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'],year=2026).used,1)
        self.assertEqual(Document.objects.get(pk=doc.pk).status,'approved')

    def test_self_completion_and_manual_registration_cannot_double_book(self):
        doc=self.self_draft()
        self.assertCountEqual(self.run_parallel(
            lambda: save_document(Document.objects.get(pk=doc.pk),self.people['owner'],submit=True),
            lambda: self.manual(date(2026,10,19))),['ok','refused'])
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'],year=2026).used,1)

    def test_rule_deletion_and_self_submission_serialize_permissions(self):
        from workflow.regulations import delete_rule
        doc=self.self_draft()
        rule=ApprovalRule.objects.get(name='동시 전결 검증')
        outcomes=self.run_parallel(
            lambda: save_document(Document.objects.get(pk=doc.pk),self.people['owner'],submit=True),
            lambda: delete_rule(self.people['finance'],rule.pk))
        self.assertIn(outcomes[0],['ok','refused'])
        self.assertEqual(outcomes[1],'ok')
        doc.refresh_from_db();rule.refresh_from_db()
        self.assertIsNotNone(rule.deleted_at)
        charged=1 if doc.status=='approved' else 0
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'],year=2026).used,charged)
        self.assertEqual(doc.status,'approved' if outcomes[0]=='ok' else 'draft')

    def representative_admin(self):
        user=get_user_model().objects.create_user('admin',first_name='관리자',password='1234')
        Profile.objects.create(user=user,department='개발팀',rank='이사',approved=True,manage_system=True)
        return user

    def test_concurrent_representative_designations_leave_one_holder(self):
        from workflow.representatives import assign_representative
        admin=self.representative_admin()
        self.assertCountEqual(self.run_parallel(
            lambda:assign_representative(admin,self.people['reviewer']),
            lambda:assign_representative(admin,self.people['approver'])),['ok','refused'])
        self.assertEqual(Profile.objects.filter(representative_slot=1).count(),1)

    def test_representative_designation_and_submission_never_strand_recipient(self):
        from workflow.representatives import assign_representative
        admin=self.representative_admin()
        # Cache the candidate before the parallel role change to exercise stale selectors.
        recipient=self.people['finance'];_=recipient.profile
        outcomes=self.run_parallel(
            lambda:assign_representative(admin,recipient),
            lambda:save_document(Document(owner=self.people['owner'],kind='office',product='용지',
                reviewer=self.people['reviewer'],approver=self.people['approver'],recipient=recipient),
                self.people['owner'],submit=True))
        self.assertCountEqual(outcomes,['ok','refused'])
        designated=Profile.objects.get(user=recipient).is_representative
        self.assertEqual(Document.objects.filter(recipient=recipient,status='review').count(),0 if designated else 1)

    def progressive_request(self):
        from workflow.models import ApprovalFlowPolicy
        ApprovalFlowPolicy.objects.update_or_create(pk=1,defaults={'enabled':True})
        admin=self.representative_admin()
        ceo=get_user_model().objects.create_user('ceo',first_name='대표',password='1234')
        Profile.objects.create(user=ceo,department='개발팀',rank='이사',approved=True)
        from workflow.representatives import assign_representative
        assign_representative(admin,ceo,can_approve=True)
        doc=save_document(Document(owner=self.people['owner'],reviewer=self.people['reviewer'],kind='leave',
            start_date=date(2026,10,19),end_date=date(2026,10,21),reason='연차'),self.people['owner'],submit=True)
        doc=act_on_document(doc.pk,self.people['reviewer'],'forward','검토 완료',self.people['approver'])
        return doc,ceo,admin

    def test_approver_final_and_ceo_escalation_cannot_both_finish(self):
        doc,ceo,admin=self.progressive_request()
        self.assertCountEqual(self.run_parallel(
            lambda:act_on_document(doc.pk,self.people['approver'],'approve'),
            lambda:act_on_document(doc.pk,self.people['approver'],'escalate','대표 요청')),['ok','refused'])
        doc.refresh_from_db();used=AnnualBalance.objects.get(user=self.people['owner'],year=2026).used
        self.assertIn(doc.status,['executive','approved']);self.assertEqual(used,3 if doc.status=='approved' else 0)

    def test_duplicate_representative_approval_charges_once(self):
        doc,ceo,admin=self.progressive_request()
        act_on_document(doc.pk,self.people['approver'],'escalate','대표 요청')
        operation=lambda:act_on_document(doc.pk,ceo,'approve')
        self.assertCountEqual(self.run_parallel(operation,operation),['ok','refused'])
        self.assertEqual(AnnualBalance.objects.get(user=self.people['owner'],year=2026).used,3)

    def test_disabling_ceo_and_escalation_serialize_without_stranded_request(self):
        from workflow.representatives import assign_representative
        doc,ceo,admin=self.progressive_request()
        outcomes=self.run_parallel(
            lambda:assign_representative(admin,ceo,can_approve=False,expected_id=ceo.pk),
            lambda:act_on_document(doc.pk,self.people['approver'],'escalate','대표 요청'))
        self.assertCountEqual(outcomes,['ok','refused'])
        doc.refresh_from_db();enabled=Profile.objects.get(user=ceo).representative_can_approve
        self.assertEqual(doc.status,'executive' if enabled else 'approve')
