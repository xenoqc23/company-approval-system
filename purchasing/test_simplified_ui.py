"""Shared inboxes, milestone notices and all-or-nothing receipts are coherent."""
import unittest
from datetime import date
from uuid import uuid4
from django.conf import settings
if not settings.INTEGRATED_PURCHASES:raise unittest.SkipTest('Full application only.')
from django.test import TestCase
from django.core.exceptions import ValidationError,PermissionDenied
from django.urls import reverse
from workflow.models import ApprovalRule,ApprovalFlowPolicy,Document,AnnualBalance,RANKS,Profile
from workflow.delegation import resolve_route
from workflow.forms import DocumentForm,ApprovalRuleForm
from workflow.services import save_document,act_on_document
from . import test_integrated as fixtures
from .models import PurchaseRequest,PurchaseNotice,PurchaseReceipt
from .services import request_action,decide_report,amend_amount
from .fulfillment import report_fulfillment,report_receipt_label

class SimplifiedInterfaceTests(TestCase):
    setUpTestData=classmethod(fixtures.IntegratedTests.setUpTestData.__func__)
    user=fixtures.IntegratedTests.user
    as_user=fixtures.IntegratedTests.as_user
    create=fixtures.IntegratedTests.create
    confirmed=fixtures.IntegratedTests.confirmed
    report=fixtures.IntegratedTests.report
    final=fixtures.IntegratedTests.final
    decisions=fixtures.IntegratedTests.decisions

    def test_ceo_pending_and_history_contain_one_batch_and_no_duplicate_menu(self):
        d=self.confirmed();r=self.report([d]);self.as_user('ceo')
        response=self.client.get('/documents/?mode=pending')
        self.assertEqual(response.context['document_count'],1)
        self.assertContains(response,reverse('purchasing:report_detail',args=[r.pk]))
        self.assertEqual(self.client.get('/notifications/status/').json()['waiting'],1)
        self.assertNotContains(self.client.get('/'),'구매승인 결정')
        self.assertNotContains(self.client.get('/'),'>구매요청함<')
        self.assertContains(self.client.get(reverse('purchasing:reports')),r.title)
        decide_report(r.pk,self.user('ceo'),self.decisions(r,['allow']),0,final=True)
        self.assertEqual(self.client.get('/notifications/status/').json()['waiting'],0)
        self.assertEqual(self.client.get('/documents/?mode=pending').context['document_count'],0)
        history=self.client.get('/documents/?mode=history&kind=office')
        self.assertEqual(history.context['document_count'],1)
        self.assertContains(history,r.title);self.assertContains(history,'결재완료')
        self.assertNotContains(history,'수령 대기');self.assertNotContains(history,r.number)
        self.assertEqual(self.client.get('/documents/?mode=history&kind=leave').context['document_count'],0)

    def test_whole_receipt_without_quantity_updates_finance_done_tab_and_ceo_history(self):
        d=self.confirmed();r=self.final([d],['allow']);self.as_user('quality_manager')
        before=self.client.get(reverse('purchasing:detail',args=[d.pk]))
        self.assertContains(before,'data-receipt-complete');self.assertNotContains(before,'name="quantity"')
        self.assertNotContains(before,'받은 수량');self.assertNotContains(before,'미수령')
        request_action(d.pk,d.owner,'receive',quantity=1,receipt_key=uuid4(),storage_location='공용 창고')
        d.refresh_from_db();self.assertEqual((d.status,d.received_quantity),('received',d.quantity))
        with self.assertRaises(ValidationError):request_action(d.pk,d.owner,'receive',receipt_key=uuid4())
        self.assertEqual(PurchaseReceipt.objects.filter(request=d).count(),1)
        self.as_user('finance')
        done=self.client.get(reverse('purchasing:reports')+'?tab=completed')
        self.assertEqual(done.context['total'],1);self.assertContains(done,d.product)
        self.assertContains(done,'결재완료');self.assertContains(done,'수령 완료');self.assertNotContains(done,d.number)
        self.assertNotContains(done,'받은 수량');self.assertNotContains(done,'일부 수령')
        self.as_user('ceo');history=self.client.get('/documents/?mode=history')
        self.assertContains(history,'결재완료');self.assertNotContains(history,'수령 완료')

    def test_existing_partial_receipt_remains_waiting_and_button_finishes_remainder(self):
        d=self.confirmed();self.final([d],['allow'])
        PurchaseRequest.objects.filter(pk=d.pk).update(received_quantity=3)
        PurchaseReceipt.objects.create(request=d,received_by=d.owner,quantity=3)
        request_action(d.pk,d.owner,'receive',receipt_key=uuid4())
        d.refresh_from_db();self.assertEqual(d.received_quantity,d.quantity)
        self.assertEqual(list(d.receipts.values_list('quantity',flat=True)),[3,7])

    def test_requester_gets_only_named_milestones_and_actionable_notices(self):
        d=self.create('quality','review');owner=d.owner
        self.assertEqual(PurchaseNotice.objects.filter(user=owner,request=d).count(),0)
        request_action(d.pk,self.user('quality_manager'),'forward',new_person=self.user('quality_lead'))
        request_action(d.pk,self.user('quality_lead'),'approve')
        request_action(d.pk,self.user('prod_director'),'confirm_items')
        r=self.report([d]);texts=list(PurchaseNotice.objects.filter(user=owner,request=d).order_by('pk').values_list('text',flat=True))
        self.assertEqual(len(texts),2);self.assertIn('검토를 완료',texts[0]);self.assertIn(self.user('quality_manager').first_name,texts[0]);self.assertIn('승인을 완료',texts[1])
        decide_report(r.pk,self.user('ceo'),self.decisions(r,['allow']),0,final=True)
        texts=list(PurchaseNotice.objects.filter(user=owner,request=d).order_by('pk').values_list('text',flat=True))
        self.assertEqual(len(texts),3);self.assertIn('최종 결재가 완료',texts[-1])
        self.assertFalse(any('진행상황이 변경' in s or '구매요청 완료' in s for s in texts))

    def test_combined_approval_sends_one_owner_milestone(self):
        d=self.create('dev_manager','review',reviewer=self.user('dev_lead'),approver=self.user('dev_director'))
        request_action(d.pk,self.user('dev_lead'),'forward',new_person=self.user('dev_director'));before=PurchaseNotice.objects.filter(user=d.owner,request=d).count()
        request_action(d.pk,self.user('dev_director'),'approve')
        self.assertEqual(PurchaseNotice.objects.filter(user=d.owner,request=d).count(),before+1)

    def test_hold_batch_is_not_marked_complete_and_only_allowed_items_are_receivable(self):
        docs=[self.confirmed() for _ in range(3)]
        r=self.final(docs,['allow','hold','deny']);self.assertNotIn('결재완료',r.result_label)
        for d in docs:d.refresh_from_db()
        counts=report_fulfillment(r,list(r.items.select_related('request')))
        self.assertEqual(counts['eligible'],1);self.assertEqual(report_receipt_label(counts),'수령 대기')
        request_action(docs[0].pk,docs[0].owner,'receive',receipt_key=uuid4())
        for d in docs[1:]:
            with self.assertRaises(ValidationError):request_action(d.pk,d.owner,'receive',receipt_key=uuid4())
        self.as_user('finance');self.assertEqual(self.client.get(reverse('purchasing:reports')+'?tab=completed').context['total'],1)

    def test_simple_rule_editor_and_staff_deep_link(self):
        self.as_user('admin');r=self.client.get('/regulations/?tab=leave')
        self.assertContains(r,'검토 요청')
        self.assertContains(r,'대표 결재 요청');self.assertContains(r,'검토자 승인완료 권한')
        self.assertNotContains(r,'name="allow_self_approval"');self.assertNotContains(r,'name="approver_is_author"')
        self.assertNotContains(r,'name="allow_skip_review"')
        self.assertContains(self.client.get(reverse('purchasing:regulations')),'purchase_settings=1#purchase-assignments')
        self.assertContains(self.client.get('/staff/?purchase_settings=1'),'개발팀 요청 구매확인 담당자')

    def test_all_senior_leave_ranks_have_only_review_and_ceo_and_cannot_forge_self(self):
        rule=ApprovalRule.objects.create(name='예전 본인 전결 규정',kind='leave',enabled=True,reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:],allow_self_approval=True,allow_skip_review=True)
        ApprovalFlowPolicy.objects.update_or_create(pk=1,defaults=dict(enabled=True))
        for rank in ['과장','팀장','부장','이사']:
            user=self.user('quality_manager');Profile.objects.filter(user=user).update(rank=rank);user.profile.refresh_from_db()
            route=resolve_route('leave',rank,owner=user)
            self.assertEqual(route['available_modes'],['base','ceo'],rank);self.assertFalse(route['self_complete'])
            for mode in ['self','skip']:
                with self.assertRaises(ValidationError):resolve_route('leave',rank,owner=user,mode=mode)
            form=DocumentForm(instance=Document(owner=user,kind='leave'))
            self.assertFalse(form.fields['reviewer'].queryset.filter(pk=user.pk).exists())
            self.assertFalse(form.fields['approver'].queryset.filter(pk=user.pk).exists())
            self.assertEqual(list(form.fields['approval_mode'].choices),[('base','검토 요청'),('ceo','대표 결재 요청')])
        form=ApprovalRuleForm(instance=rule)
        self.assertNotIn('allow_self_approval',form.fields)

    def test_senior_leave_direct_to_ceo_deducts_only_after_representative_approval(self):
        owner=self.user('quality_manager');year=2027
        rule=ApprovalRule.objects.create(name='휴가원 대표 선택',kind='leave',enabled=True,allow_representative_direct=True,reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:])
        AnnualBalance.objects.create(user=owner,year=year,total=20,used=0)
        d=save_document(Document(owner=owner,kind='leave',approval_mode='ceo',leave_type='annual',start_date=date(year,11,1),end_date=date(year,11,1),reason='일정'),owner,submit=True)
        self.assertEqual(d.status,'executive');self.assertIsNone(d.reviewer_id)
        self.assertEqual(AnnualBalance.objects.get(user=owner,year=year).used,0)
        d=act_on_document(d.pk,self.user('ceo'),'approve')
        self.assertEqual(d.status,'approved');self.assertEqual(AnnualBalance.objects.get(user=owner,year=year).used,1)

    def test_self_as_reviewer_is_rejected_even_with_old_fixed_self_rule(self):
        owner=self.user('quality_manager')
        ApprovalFlowPolicy.objects.update_or_create(pk=1,defaults=dict(enabled=False))
        ApprovalRule.objects.create(name='옛 본인 고정 규정',kind='leave',enabled=True,approver_is_author=True,reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:])
        with self.assertRaises(ValidationError):save_document(Document(owner=owner,reviewer=owner,kind='leave',reason='본인 승인 차단 확인',leave_type='annual',start_date=date(2027,11,1),end_date=date(2027,11,1)),owner,submit=True)
        d=save_document(Document(owner=owner,reviewer=self.user('quality_lead'),approver=self.user('prod_director'),kind='leave',reason='기존 결재 방식 보존 확인',leave_type='annual',start_date=date(2027,11,1),end_date=date(2027,11,1)),owner,submit=True)
        self.assertTrue(d.progressive)
        self.assertIsNone(d.approver_id)
        self.assertEqual(act_on_document(d.pk,self.user('quality_lead'),'forward',new_person=self.user('prod_director')).status,'approve')
