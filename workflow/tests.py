from datetime import date, time
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from workflow.models import AnnualBalance, Audit, Document, Notice, Policy, Profile
from workflow.services import act_on_document, edit_balance, save_document, visible_documents
from workflow.management.commands.seed_demo import TENURE, POLICY


class ApprovalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        for key, flags in [
            ('owner', {}), ('reviewer', {}), ('approver', {}), ('stranger', {}),
            ('recipient', {}), ('accounting', {'manage_leave': True, 'view_accounting': True, 'procure': True}),
            ('admin', {'manage_system': True}),
        ]:
            user = User.objects.create_user(key, first_name=key, password='test-password-only')
            Profile.objects.create(user=user, department='개발팀', rank='대리', approved=True, **flags)
            setattr(cls, key, user)
        AnnualBalance.objects.create(user=cls.owner, year=2026, total=15, used=3)
        Policy.objects.create(tenure=TENURE, text=POLICY)

    def leave(self, submit=True, **fields):
        defaults = dict(owner=self.owner, reviewer=self.reviewer, approver=self.approver,
                        kind='leave', leave_type='annual', start_date=date(2026, 10, 12),
                        end_date=date(2026, 10, 14), reason='개인 일정')
        defaults.update(fields)
        return save_document(Document(**defaults), defaults['owner'], submit=submit)

    def purchase(self, **fields):
        defaults = dict(owner=self.owner, reviewer=self.reviewer, approver=self.approver,
                        recipient=self.recipient, kind='office', product='A4 용지', quantity=4,
                        unit_price=Decimal('6500.25'), url='https://example.com/a4')
        defaults.update(fields)
        return save_document(Document(**defaults), defaults['owner'], submit=True)

    def finish(self, doc):
        reviewed = act_on_document(doc.pk, doc.reviewer, 'review')
        if doc.kind == 'stock':
            return reviewed
        return act_on_document(doc.pk, doc.approver, 'approve')

    def used(self, year=2026):
        return AnnualBalance.objects.get(user=self.owner, year=year).used

    def test_only_final_approval_charges_and_only_final_actor_cancels_once(self):
        doc = self.leave()
        self.assertEqual(self.used(), 3)
        act_on_document(doc.pk, self.reviewer, 'review')
        self.assertEqual(self.used(), 3)
        act_on_document(doc.pk, self.approver, 'approve')
        self.assertEqual(self.used(), 6)
        for user, action in [(self.reviewer, 'cancel_review'), (self.admin, 'cancel_approval'),
                             (self.approver, 'approve')]:
            with self.assertRaises(PermissionDenied):
                act_on_document(doc.pk, user, action, '사유')
        act_on_document(doc.pk, self.approver, 'cancel_approval', '일정 취소')
        self.assertEqual(self.used(), 3)
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.approver, 'cancel_approval', '중복 요청')
        self.assertEqual(self.used(), 3)
        self.assertTrue(Audit.objects.filter(document=doc, event='최종 승인 취소').exists())

    def test_year_boundary_cancellation_restores_original_buckets(self):
        AnnualBalance.objects.create(user=self.owner, year=2027, total=15, used=2)
        doc = self.finish(self.leave(start_date=date(2026, 12, 31), end_date=date(2027, 1, 4)))
        # No public-holiday calendar: Fri Jan 1 is counted; weekend Jan 2/3 excluded.
        self.assertEqual(doc.allocations, {'2026': '1', '2027': '2'})
        self.assertEqual(self.used(2026), 4)
        self.assertEqual(self.used(2027), 4)
        edit_balance(self.accounting, self.owner, 2026, 'total', Decimal('20'), '수동 갱신')
        act_on_document(doc.pk, self.approver, 'cancel_approval', '취소')
        self.assertEqual(self.used(2026), 3)
        self.assertEqual(self.used(2027), 2)

    def test_negative_leave_is_allowed(self):
        b = AnnualBalance.objects.get(user=self.owner, year=2026)
        b.total = 1
        b.save()
        self.finish(self.leave())
        b.refresh_from_db()
        self.assertEqual(b.remaining, Decimal('-5'))

    def test_fixed_half_and_outing_deduction_independent_of_duration(self):
        for i, (kind, amount) in enumerate([('am', '.5'), ('pm', '.5'), ('outing', '.25')]):
            day = date(2026, 10, 12 + i)
            doc = self.finish(self.leave(leave_type=kind, start_date=day, end_date=day,
                                         start_time=time(9), end_time=time(12, 30)))
            self.assertEqual(doc.charged, Decimal(amount))
        self.assertEqual(self.used(), Decimal('4.25'))

    def test_weekends_excluded_and_weekend_only_rejected(self):
        doc = self.finish(self.leave(start_date=date(2026, 10, 9), end_date=date(2026, 10, 12)))
        self.assertEqual(doc.charged, 2)
        with self.assertRaises(ValidationError):
            self.leave(start_date=date(2026, 10, 17), end_date=date(2026, 10, 18))

    def test_time_overlap_blocks_but_touching_endpoints_allowed(self):
        fields = dict(leave_type='outing', start_date=date(2026, 10, 12), end_date=date(2026, 10, 12))
        first = self.leave(**fields, start_time=time(9), end_time=time(12, 30))
        with self.assertRaises(ValidationError):
            self.leave(**fields, start_time=time(12), end_time=time(13))
        second = self.leave(**fields, start_time=time(12, 30), end_time=time(14))
        self.assertNotEqual(first.pk, second.pk)
        with self.assertRaises(ValidationError):
            self.leave()

    def test_draft_cancelled_rejected_and_deleted_do_not_block_overlap(self):
        self.leave(submit=False)
        for action in ['reject', 'delete', 'cancel_review']:
            doc = self.leave()
            if action == 'cancel_review':
                act_on_document(doc.pk, self.reviewer, 'review')
            act_on_document(doc.pk, self.owner if action == 'delete' else self.reviewer, action, '일정 변경')
        self.leave()

    def test_self_review_and_approval_still_require_two_actions(self):
        doc = self.leave(reviewer=self.owner, approver=self.owner)
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.owner, 'approve')
        act_on_document(doc.pk, self.owner, 'review')
        self.assertEqual(self.used(), 3)
        act_on_document(doc.pk, self.owner, 'approve')
        self.assertEqual(self.used(), 6)

    def test_submitted_document_is_immutable_and_delete_closes_after_review(self):
        doc = self.leave()
        doc.reason = '수정 요청'
        with self.assertRaises(PermissionDenied):
            save_document(doc, self.owner)
        doc.refresh_from_db()
        self.assertEqual(doc.reason, '개인 일정')
        act_on_document(doc.pk, self.reviewer, 'review')
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.owner, 'delete')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('edit', args=[doc.pk])).status_code, 404)

    def test_actor_stage_permissions_and_required_reasons(self):
        doc = self.leave()
        for person, action in [(self.stranger, 'review'), (self.admin, 'review'), (self.approver, 'reject')]:
            with self.assertRaises(PermissionDenied):
                act_on_document(doc.pk, person, action, '사유')
        with self.assertRaises(ValidationError):
            act_on_document(doc.pk, self.reviewer, 'reject')
        act_on_document(doc.pk, self.reviewer, 'review')
        act_on_document(doc.pk, self.reviewer, 'cancel_review', '계획 변경')
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'cancelled')
        self.assertEqual(self.used(), 3)

    def test_reassign_pending_stage_preserves_review_history(self):
        doc = self.leave()
        act_on_document(doc.pk, self.reviewer, 'review')
        doc = act_on_document(doc.pk, self.admin, 'reassign', '담당자 부재', self.stranger)
        self.assertEqual(doc.reviewer, self.reviewer)
        self.assertEqual(doc.approver, self.stranger)
        self.assertTrue(doc.reviewed_at)
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.approver, 'approve')
        act_on_document(doc.pk, self.stranger, 'approve')

    def test_accounting_visibility_excludes_cancelled_even_via_notice(self):
        doc = self.leave()
        self.assertFalse(visible_documents(self.accounting).filter(pk=doc.pk).exists())
        self.finish(doc)
        self.assertTrue(visible_documents(self.accounting).filter(pk=doc.pk).exists())
        act_on_document(doc.pk, self.approver, 'cancel_approval', '취소')
        self.assertFalse(visible_documents(self.accounting).filter(pk=doc.pk).exists())
        self.client.force_login(self.accounting)
        self.assertEqual(self.client.get(reverse('detail', args=[doc.pk])).status_code, 404)
        notice = Notice.objects.filter(user=self.accounting, document=doc).first()
        response = self.client.post(reverse('open_notice', args=[notice.pk]))
        self.assertRedirects(response, reverse('notices'))
        self.assertTrue(visible_documents(self.admin).filter(pk=doc.pk).exists())

    def test_purchase_total_shipping_recipient_and_cancel_freeze(self):
        doc = self.purchase()
        self.assertEqual(doc.total_price, Decimal('26001'))
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.accounting, 'place')
        self.finish(doc)
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.owner, 'place')
        act_on_document(doc.pk, self.accounting, 'place')
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.owner, 'receive')
        doc = act_on_document(doc.pk, self.recipient, 'receive')
        self.assertEqual(doc.shipment, 'received')
        second = self.finish(self.purchase(kind='stock', url=''))
        act_on_document(second.pk, self.accounting, 'place')
        act_on_document(second.pk, self.reviewer, 'cancel_review', '발주 취소')
        with self.assertRaises(PermissionDenied):
            act_on_document(second.pk, self.recipient, 'receive')

    def test_rejected_copy_is_new_editable_draft_with_fresh_number(self):
        doc = self.leave()
        act_on_document(doc.pk, self.reviewer, 'reject', '일정 확인')
        self.client.force_login(self.owner)
        response = self.client.post(reverse('copy', args=[doc.pk]))
        copy = Document.objects.filter(owner=self.owner, status='draft').get()
        self.assertRedirects(response, reverse('edit', args=[copy.pk]))
        self.assertIsNone(copy.number)
        save_document(copy, self.owner, submit=True)
        self.assertNotEqual(copy.number, doc.number)
        self.assertEqual(copy.charged, 0)

    def test_manual_remaining_edit_and_private_history(self):
        edit_balance(self.accounting, self.owner, 2026, 'remaining', Decimal('-2'), '긴급 사용분 반영')
        b = AnnualBalance.objects.get(user=self.owner, year=2026)
        self.assertEqual((b.total, b.used, b.remaining), (15, 17, -2))
        with self.assertRaises(PermissionDenied):
            edit_balance(self.admin, self.owner, 2026, 'total', Decimal(20), '수정')
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('balances'))
        self.assertNotContains(response, '긴급 사용분 반영')
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('balances')), '긴급 사용분 반영')

    def test_role_menus_and_server_authorization(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, '직원별 연차 관리')
        self.assertNotContains(response, '최종 승인 문서함')
        for url in [reverse('staff'), reverse('backups'), '/documents/?mode=all', '/documents/?mode=accounting']:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.accounting)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, '직원별 연차 관리')
        self.assertContains(response, '최종 승인 문서함')
        self.assertNotContains(response, '직원·권한 관리')

    def test_signup_approval_and_forced_password_change(self):
        response = self.client.post(reverse('signup'), {'first_name': '신규 직원', 'username': 'new-staff',
            'password1': 'staff-safe-password', 'password2': 'staff-safe-password', 'department': '생산팀', 'rank': '사원'})
        self.assertRedirects(response, reverse('login'))
        new = get_user_model().objects.get(username='new-staff')
        self.client.force_login(new)
        self.assertRedirects(self.client.get('/'), reverse('pending'))
        new.profile.approved = True
        new.profile.must_change_password = True
        new.profile.save()
        self.assertRedirects(self.client.get('/'), reverse('password'))
        response = self.client.post(reverse('password'), {'old_password': 'staff-safe-password',
            'new_password1': 'another-safe-password', 'new_password2': 'another-safe-password'})
        self.assertRedirects(response, '/')
        new.profile.refresh_from_db()
        self.assertFalse(new.profile.must_change_password)

    def test_csrf_is_enforced_for_mutation(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        doc = self.leave()
        self.assertEqual(client.post(reverse('action', args=[doc.pk]), {'action': 'delete'}).status_code, 403)

    def test_all_main_templates_render_for_each_role(self):
        doc = self.leave()
        for user in [self.owner, self.accounting, self.admin]:
            self.client.force_login(user)
            for url in ['/', '/compose/', '/compose/?kind=office', '/compose/?kind=stock', '/documents/',
                        '/documents/?mode=pending', '/documents/?mode=archive', '/documents/?mode=stock', '/balances/', '/policy/', '/notices/']:
                with self.subTest(user=user.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse('detail', args=[doc.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('staff')).status_code, 200)
        self.assertEqual(self.client.get(reverse('backups')).status_code, 200)

    def test_stock_requires_only_reviewer_and_has_no_money_or_final_approval(self):
        doc = self.purchase(kind='stock', approver=None, unit_price=0, url='', quantity=50)
        self.assertIsNone(doc.approver)
        self.assertEqual(doc.unit_price, 0)
        self.assertEqual(doc.status, 'review')
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.approver, 'approve')
        doc = act_on_document(doc.pk, self.reviewer, 'review')
        self.assertEqual(doc.status_label, '발주대기')
        self.assertEqual(self.used(), 3)
        self.assertTrue(Notice.objects.filter(user=self.accounting, document=doc, text__contains='발주 담당자').exists())
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.reviewer, 'review')
        self.client.force_login(self.owner)
        response = self.client.get(reverse('detail', args=[doc.pk]))
        self.assertContains(response, '요청 수량')
        self.assertNotContains(response, '수량 / 단가')
        self.assertNotContains(response, '총가격')
        self.assertNotContains(response, '03 최종 승인')

    def test_procurement_only_role_receives_stock_requests_without_accounting_access(self):
        self.stranger.profile.procure = True
        self.stranger.profile.save()
        stock = self.purchase(kind='stock', approver=None, unit_price=0, url='')
        office = self.finish(self.purchase())
        leave = self.finish(self.leave())
        self.assertFalse(visible_documents(self.stranger).filter(pk=stock.pk).exists())
        act_on_document(stock.pk, self.reviewer, 'review')
        self.assertTrue(visible_documents(self.stranger).filter(pk=stock.pk).exists())
        self.assertFalse(visible_documents(self.stranger).filter(pk__in=[office.pk, leave.pk]).exists())
        self.client.force_login(self.stranger)
        response = self.client.get('/documents/?mode=stock&stock_stage=ready')
        self.assertContains(response, stock.number)
        self.assertNotContains(response, office.number)
        self.assertNotContains(response, '최종승인대기')
        self.assertEqual(self.client.get('/documents/?mode=accounting').status_code, 403)
        response = self.client.post(reverse('action', args=[stock.pk]), {'action': 'place'})
        self.assertRedirects(response, reverse('detail', args=[stock.pk]))
        stock.refresh_from_db()
        self.assertEqual(stock.status_label, '입고대기')
        self.assertNotContains(self.client.get('/documents/?mode=stock&stock_stage=ready'), stock.number)
        self.assertContains(self.client.get('/documents/?mode=stock&stock_stage=ordered'), stock.number)

    def test_stock_review_cancellation_blocks_fulfillment_and_requires_own_reviewer(self):
        doc = self.finish(self.purchase(kind='stock', approver=None, unit_price=0, url=''))
        act_on_document(doc.pk, self.accounting, 'place')
        for user in [self.owner, self.accounting, self.approver]:
            with self.assertRaises(PermissionDenied):
                act_on_document(doc.pk, user, 'cancel_review', '취소 사유')
        act_on_document(doc.pk, self.reviewer, 'cancel_review', '생산 계획 변경')
        self.assertFalse(visible_documents(self.accounting).filter(pk=doc.pk).exists())
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.recipient, 'receive')
        with self.assertRaises(PermissionDenied):
            act_on_document(doc.pk, self.accounting, 'place')
        self.assertEqual(self.used(), 3)

    def test_stock_form_submission_ignores_price_and_approver_and_can_self_review(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('compose'), {'intent': 'submit', 'kind': 'stock',
            'product': '제품 보관함', 'quantity': 20, 'reviewer': self.owner.pk,
            'unit_price': '12345', 'approver': self.approver.pk, 'url': 'https://example.com/unused'})
        doc = Document.objects.get(kind='stock')
        self.assertRedirects(response, reverse('detail', args=[doc.pk]))
        self.assertIsNone(doc.approver)
        self.assertEqual(doc.unit_price, 0)
        self.assertEqual(doc.url, '')
        reviewed = act_on_document(doc.pk, self.owner, 'review')
        self.assertEqual(reviewed.status_label, '발주대기')
        self.assertContains(self.client.get('/documents/?mode=history'), doc.number)

    def test_stock_reject_copy_retains_single_review_workflow(self):
        doc = self.purchase(kind='stock', approver=None, unit_price=0, url='')
        act_on_document(doc.pk, self.reviewer, 'reject', '수량 확인')
        self.client.force_login(self.owner)
        self.client.post(reverse('copy', args=[doc.pk]))
        copy = Document.objects.get(status='draft', kind='stock')
        self.assertIsNone(copy.approver)
        self.assertEqual(copy.unit_price, 0)
        save_document(copy, self.owner, submit=True)
        self.assertNotEqual(copy.number, doc.number)
        self.assertEqual(act_on_document(copy.pk, self.reviewer, 'review').status, 'approved')

    def test_legacy_stock_conversion_preserves_existing_reviews_and_fulfillment(self):
        import importlib
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection
        from django.utils import timezone
        pending = Document.objects.create(owner=self.owner, reviewer=self.reviewer, approver=self.approver,
            kind='stock', status='approve', number='LEGACY-1', title='구매요청 / owner / 보관함',
            product='보관함', quantity=20, unit_price=15000, reviewed_at=timezone.now())
        old_log = Audit.objects.create(document=pending, actor=self.reviewer, event='검토 승인')
        ordered = Document.objects.create(owner=self.owner, reviewer=self.reviewer, approver=self.approver,
            kind='stock', status='approved', shipment='ordered', number='LEGACY-2', product='매뉴얼', quantity=100)
        unreviewed = Document.objects.create(owner=self.owner, reviewer=self.reviewer, kind='stock', status='approve')
        migration = importlib.import_module('workflow.migrations.0003_stock_review_workflow')
        migration.convert_stock_requests(apps, SimpleNamespace(connection=connection))
        pending.refresh_from_db(); ordered.refresh_from_db(); unreviewed.refresh_from_db()
        self.assertEqual(pending.status_label, '발주대기')
        self.assertEqual(pending.approved_at, pending.reviewed_at)
        self.assertEqual((pending.number, pending.quantity, pending.unit_price), ('LEGACY-1', 20, 15000))
        self.assertTrue(Audit.objects.filter(pk=old_log.pk).exists())
        self.assertTrue(Audit.objects.filter(document=pending, actor__isnull=True).exists())
        self.assertEqual(ordered.shipment, 'ordered')
        self.assertEqual(unreviewed.status, 'review')
        self.assertTrue(Notice.objects.filter(document=pending, user=self.accounting).exists())
