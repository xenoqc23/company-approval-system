"""Business invariants for local purchase follow-up, never actual NAS data."""
import unittest
from django.conf import settings
if not settings.PURCHASE_LAB_ENABLED:raise unittest.SkipTest('Purchase lab is disabled.')
from decimal import Decimal
from uuid import uuid4
from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import PermissionDenied,ValidationError
from . import tests as helpers
from .models import PurchaseRequest,PurchaseNotice
from .services import request_action,decide_report,supplement_request,amend_amount
from .access import notices_for
from .progress import progress

class PurchaseFollowupTests(TestCase):
    setUpTestData=classmethod(helpers.PurchaseFlowTests.setUpTestData.__func__)
    user=helpers.PurchaseFlowTests.user
    as_user=helpers.PurchaseFlowTests.as_user
    values=helpers.PurchaseFlowTests.values
    create=helpers.PurchaseFlowTests.create
    approved=helpers.PurchaseFlowTests.approved
    ready=helpers.PurchaseFlowTests.ready
    report=helpers.PurchaseFlowTests.report
    decisions=helpers.PurchaseFlowTests.decisions

    def allowed(self,who='quality'):
        d=self.ready(who);r=self.report([d]);decide_report(r.pk,self.user('ceo'),self.decisions(r,['allow']),0,final=True)
        d.refresh_from_db();return d,r

    def test_ceo_approval_notifies_owner_and_allows_receipt_without_payment_step(self):
        d,r=self.allowed()
        self.assertEqual(d.status,'allowed');self.assertIsNone(d.paid_at);self.assertTrue(d.completion_unread)
        self.assertTrue(notices_for(d.owner).filter(request=d,text__contains='구매 승인완료',read=False).exists())
        self.as_user('finance');response=self.client.get(reverse('purchasing:detail',args=[d.pk]))
        self.assertNotContains(response,'결제 완료 확인');d.refresh_from_db();self.assertTrue(d.completion_unread)
        self.as_user('quality');response=self.client.get(reverse('purchasing:home'))
        self.assertEqual(response.context['counts']['own_completed'],1)
        self.assertEqual(self.client.get(reverse('purchasing:requests')+'?mode=mine&unread=1').context['total'],1)
        response=self.client.get(reverse('purchasing:detail',args=[d.pk]));self.assertContains(response,'받은 수량 등록')
        d.refresh_from_db();self.assertFalse(d.completion_unread)
        self.assertEqual(self.client.get(reverse('purchasing:home')).context['counts']['own_completed'],0)
        d=request_action(d.pk,d.owner,'receive',quantity=1,receipt_key=uuid4())
        self.assertEqual(d.status,'allowed');self.assertEqual(progress(d,True)['receipt'],'일부 수령 1/2개')
        d=request_action(d.pk,d.owner,'receive',quantity=1,receipt_key=uuid4())
        self.assertEqual(d.status,'received');self.assertEqual(progress(d,True)['receipt'],'수령 완료')

    def test_pending_and_denied_and_hold_do_not_unlock_receipts_or_completion(self):
        for choice in ['deny','hold']:
            d=self.ready();r=self.report([d])
            with self.assertRaises(ValidationError):request_action(d.pk,d.owner,'receive',quantity=1)
            decide_report(r.pk,self.user('ceo'),self.decisions(r,[choice]),0,final=True);d.refresh_from_db()
            self.assertFalse(d.completion_unread)
            with self.assertRaises(ValidationError):request_action(d.pk,d.owner,'receive',quantity=1)

    def test_supplement_keeps_approved_items_and_routes_only_back_to_checker(self):
        d=self.approved('quality');timestamps=(d.reviewed_at,d.intermediate_at);before=(d.quantity,d.unit_price,d.product)
        d=request_action(d.pk,self.user('prod_director'),'request_supplement','견적 조건을 보완해 주세요')
        self.assertEqual(d.status,'supplement')
        with self.assertRaises(ValidationError):request_action(d.pk,self.user('prod_director'),'confirm_items')
        with self.assertRaises(PermissionDenied):supplement_request(d.pk,self.user('finance'),dict(reason='x',response='y'),d.revision)
        d=supplement_request(d.pk,d.owner,dict(reason='보증기간 2년 필요',url='https://example.com/quote',response='견적 조건 보완',quantity=999),d.revision)
        self.assertEqual(d.status,'ready');self.assertEqual(before,(d.quantity,d.unit_price,d.product));self.assertEqual(timestamps,(d.reviewed_at,d.intermediate_at))
        item=d.supplements.get();self.assertIsNotNone(item.resolved_at);self.assertNotEqual(item.before['reason'],item.after['reason'])
        request_action(d.pk,self.user('prod_director'),'confirm_items')
        with self.assertRaises(ValidationError):request_action(d.pk,self.user('prod_director'),'request_supplement','확인 후 변경 시도')

    def test_supplement_stale_revision_and_atomic_upload_rollback(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest.mock import patch
        d=self.approved('quality');d=request_action(d.pk,self.user('prod_director'),'request_supplement','자료 보완')
        with self.assertRaises(ValidationError):supplement_request(d.pk,d.owner,dict(reason='보완',response='완료'),d.revision-1)
        self.as_user('quality')
        with patch('purchasing.views.StoredFiles.add',side_effect=ValidationError('업로드 실패')):
            response=self.client.post(reverse('purchasing:supplement',args=[d.pk]),dict(revision=d.revision,reason='새 사유',response='보완 완료',files=SimpleUploadedFile('견적.pdf',b'%PDF-test')))
        self.assertContains(response,'업로드 실패');d.refresh_from_db();self.assertEqual(d.status,'supplement');self.assertIsNone(d.supplements.get().resolved_at)

    def test_hold_requires_followup_before_reporting_again_and_keeps_original_decision(self):
        d=self.ready();r=self.report([d]);decide_report(r.pk,self.user('ceo'),self.decisions(r,['hold']),0,final=True)
        with self.assertRaises(ValidationError):self.report([d])
        with self.assertRaises(PermissionDenied):request_action(d.pk,d.owner,'prepare_hold','보완 완료')
        request_action(d.pk,self.user('finance'),'prepare_hold','규격 확인 완료')
        self.as_user('finance');response=self.client.get(reverse('purchasing:requests')+'?mode=hold');self.assertContains(response,'규격 확인 완료')
        second=self.report([d]);self.assertEqual(r.items.get().decision,'hold');self.assertEqual(second.items.get().snapshot['hold_followup']['note'],'규격 확인 완료')
        self.as_user('quality');self.assertEqual(self.client.get(reverse('purchasing:requests')+'?mode=hold').status_code,403)

    def test_increased_amount_requires_new_approval_and_preserves_previous_report(self):
        d,r=self.allowed();snapshot=r.items.get().snapshot.copy();oldrev=d.revision
        d=amend_amount(d.pk,self.user('finance'),2,Decimal('20000'),'견적 인상',d.revision)
        self.assertEqual(d.status,'reapproval');self.assertFalse(d.completion_unread)
        self.assertEqual(progress(d,True)['label'],'구매 진행 중');self.assertNotIn('취합',progress(d,True)['who'])
        with self.assertRaises(ValidationError):request_action(d.pk,d.owner,'receive',quantity=1)
        with self.assertRaises(ValidationError):request_action(d.pk,self.user('finance'),'paid','결제 확인')
        with self.assertRaises(ValidationError):amend_amount(d.pk,self.user('finance'),2,Decimal('30000'),'중복 변경',oldrev)
        second=self.report([d]);self.assertEqual(second.items.get().snapshot['amendment']['before'],snapshot)
        self.assertEqual(r.items.get().snapshot,snapshot);self.assertEqual(r.items.get().decision,'allow')
        decide_report(second.pk,self.user('ceo'),self.decisions(second,['allow']),0,final=True)
        d.refresh_from_db();self.assertTrue(d.completion_unread)
        d=request_action(d.pk,d.owner,'receive',quantity=2);self.assertEqual(d.status,'received')

    def test_decrease_records_history_without_reapproval_and_partial_receipt_blocks_edits(self):
        d,r=self.allowed();before=r.items.get().snapshot.copy()
        d=amend_amount(d.pk,self.user('finance'),2,Decimal('10000'),'할인 적용',d.revision)
        self.assertEqual(d.status,'allowed');self.assertFalse(d.amendments.get().requires_reapproval);self.assertEqual(r.items.get().snapshot,before)
        d=request_action(d.pk,d.owner,'receive',quantity=1)
        with self.assertRaises(ValidationError):amend_amount(d.pk,self.user('finance'),2,Decimal('9000'),'추가 변경',d.revision)

    def test_amount_change_requires_assigned_current_finance_and_valid_values(self):
        d,r=self.allowed()
        for who in ['quality','admin','ceo','prod_director']:
            with self.assertRaises(PermissionDenied):amend_amount(d.pk,self.user(who),2,Decimal('20000'),'변경',d.revision)
        for qty,price in [(0,'2'),(2,'NaN'),(2,'1.001'),(2,'Infinity'),(2,'-1')]:
            with self.assertRaises(ValidationError):amend_amount(d.pk,self.user('finance'),qty,price,'오류',d.revision)
        d.refresh_from_db();self.assertEqual(d.status,'allowed');self.assertFalse(d.amendments.exists())

    def test_confirmation_badges_and_receipt_column_are_visible(self):
        d=self.ready('quality');self.as_user('prod_director')
        response=self.client.get(reverse('purchasing:requests')+'?mode=completed')
        self.assertContains(response,'<span class="badge tone-positive">확인완료</span>',html=True)
        self.as_user('quality');response=self.client.get(reverse('purchasing:requests')+'?mode=mine')
        content=response.content.decode();self.assertLess(content.index('<th>진행상황</th>'),content.index('<th>수령 현황</th>'));self.assertLess(content.index('<th>수령 현황</th>'),content.index('<th>현재 담당</th>'))

    def test_purchase_approval_filter_groups_old_payment_and_received_states(self):
        d,r=self.allowed();other,_=self.allowed();request_action(other.pk,other.owner,'receive',quantity=other.quantity)
        self.as_user('quality');response=self.client.get(reverse('purchasing:requests')+'?mode=mine&state=purchase_approved')
        self.assertEqual(response.context['total'],2)
        choices=response.context['states'];self.assertEqual(sum(label=='구매 승인완료' for key,label in choices),1)
        self.assertContains(response,'tone-positive')

    def test_next_action_is_role_specific_and_supplement_does_not_add_finance_access(self):
        from .access import requests_for
        d=self.approved('quality');self.as_user('prod_director')
        response=self.client.get(reverse('purchasing:detail',args=[d.pk]))
        self.assertEqual(response.context['task']['kind'],'confirm')
        self.assertContains(response,'data-secondary-actions')
        d=request_action(d.pk,self.user('prod_director'),'request_supplement','자료 보완')
        self.assertFalse(requests_for(self.user('finance')).filter(pk=d.pk).exists())
        self.as_user('quality');response=self.client.get(reverse('purchasing:detail',args=[d.pk]));self.assertEqual(response.context['task']['kind'],'supplement')
        self.assertNotContains(response,'data-purchase-progress')
