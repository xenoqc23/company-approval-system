"""Reviewer-led requests, safe rule toggles and focused representative decisions."""
import unittest
from datetime import date
from uuid import uuid4
from django.conf import settings
if not settings.INTEGRATED_PURCHASES:raise unittest.SkipTest('Full application only.')
from django.test import TestCase,Client
from django.urls import reverse
from django.core.exceptions import ValidationError,PermissionDenied
from workflow.models import ApprovalRule,Document,RANKS,Profile
from workflow.services import save_document,act_on_document
from . import test_integrated as fixtures
from .models import PurchasePolicy,PurchaseRequest,PurchaseNotice,PurchaseEvent
from .services import request_action,decide_report,save_request
from .forms import PurchaseForwardForm,IntegratedPolicyForm

class ReviewerFlowTests(TestCase):
    setUpTestData=classmethod(fixtures.IntegratedTests.setUpTestData.__func__)
    user=fixtures.IntegratedTests.user
    as_user=fixtures.IntegratedTests.as_user
    create=fixtures.IntegratedTests.create
    confirmed=fixtures.IntegratedTests.confirmed
    report=fixtures.IntegratedTests.report
    final=fixtures.IntegratedTests.final
    decisions=fixtures.IntegratedTests.decisions

    def test_new_request_ignores_prefilled_or_forged_approver_and_form_has_only_reviewer(self):
        d=self.create('quality','review',approver=self.user('prod_director'))
        self.assertEqual(d.status,'review');self.assertIsNone(d.approver_id);self.assertTrue(d.route['reviewer_decides'])
        self.as_user('quality');r=self.client.get(reverse('purchasing:new'))
        self.assertContains(r,'검토자 지정');self.assertNotContains(r,'name="approver"')
        self.assertContains(r,'추가 정보');self.assertContains(r,'구매 사유')

    def test_unprivileged_reviewer_can_only_forward_to_another_eligible_approver(self):
        d=self.create('quality','review');reviewer=self.user('quality_manager')
        self.as_user('quality_manager');page=self.client.get(reverse('purchasing:detail',args=[d.pk]))
        self.assertContains(page,'승인 요청');self.assertNotContains(page,'value="review_final"')
        with self.assertRaises(PermissionDenied):request_action(d.pk,reviewer,'review_final')
        for who in ['quality','quality_manager']:
            with self.assertRaises(ValidationError):request_action(d.pk,reviewer,'forward',new_person=self.user(who))
        with self.assertRaises(ValidationError):request_action(d.pk,reviewer,'approve')
        d=request_action(d.pk,reviewer,'forward',new_person=self.user('quality_lead'))
        self.assertEqual((d.status,d.approver_id),('approval',self.user('quality_lead').pk))
        self.assertTrue(PurchaseNotice.objects.filter(user=d.approver,request=d).exists())
        d=request_action(d.pk,d.approver,'approve');self.assertEqual(d.status,'ready');self.assertIsNone(d.confirmed_at)

    def test_named_reviewer_finishes_internal_only_and_cannot_repeat(self):
        d=self.create('quality','review');p=PurchasePolicy.objects.get(pk=1);p.review_final_users.add(self.user('quality_manager'))
        d=request_action(d.pk,self.user('quality_manager'),'review_final')
        self.assertEqual(d.status,'ready');self.assertFalse(d.completion_unread);self.assertIsNone(d.current_report_id)
        self.assertFalse(PurchaseRequest.objects.filter(pk=d.pk,status='allowed').exists())
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('quality_manager'),'review_final')
        self.assertEqual(PurchaseEvent.objects.filter(request=d,event='내부 승인완료').count(),1)
        self.assertEqual(PurchaseNotice.objects.filter(request=d,user=d.owner).count(),1)

    def test_checker_reviewer_finishes_and_confirms_once_then_finance_and_ceo(self):
        d=self.create('quality','review',reviewer=self.user('prod_director'))
        p=PurchasePolicy.objects.get(pk=1);p.review_final_users.add(self.user('prod_director'))
        d=request_action(d.pk,self.user('prod_director'),'review_final')
        self.assertEqual(d.confirmation_method,'with_approval');self.assertIsNotNone(d.confirmed_at)
        self.assertEqual(PurchaseNotice.objects.filter(request=d,user=self.user('finance')).count(),1)
        r=self.final([d],['allow']);d.refresh_from_db();self.assertEqual(d.status,'allowed')
        self.assertTrue(d.completion_unread);self.assertEqual(PurchaseNotice.objects.filter(request=d,user=d.owner).count(),2)

    def test_finish_permission_is_live_and_named_not_just_rank(self):
        d=self.create('quality','review');p=PurchasePolicy.objects.get(pk=1);p.review_final_users.add(self.user('quality_manager'));p.review_final_users.clear()
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('quality_manager'),'review_final')
        p.review_final_users.add(self.user('quality_manager'));Profile.objects.filter(user=self.user('quality_manager')).update(rank='대리')
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('quality_manager'),'review_final')

    def test_forward_department_mismatch_does_not_mutate_request(self):
        d=self.create('quality','review');self.as_user('quality_manager')
        response=self.client.post(reverse('purchasing:action',args=[d.pk]),dict(action='forward',new_person=self.user('quality_lead').pk,new_person_department='개발팀'))
        self.assertEqual(response.status_code,302);d.refresh_from_db();self.assertEqual(d.status,'review');self.assertIsNone(d.approver_id)
        form=PurchaseForwardForm(document=d)
        self.assertFalse(form.fields['new_person'].queryset.filter(pk__in=[d.owner_id,d.reviewer_id]).exists())

    def test_old_submitted_route_keeps_preselected_approver(self):
        d=self.create('quality','review');route={k:v for k,v in d.route.items() if k!='reviewer_decides'}
        PurchaseRequest.objects.filter(pk=d.pk).update(route=route,approver=self.user('quality_lead'))
        d=request_action(d.pk,self.user('quality_manager'),'approve')
        self.assertEqual((d.status,d.approver_id),('approval',self.user('quality_lead').pk))

    def test_representative_has_three_explicit_choices_facts_and_no_receipts(self):
        d=self.confirmed();r=self.report([d]);self.as_user('ceo')
        response=self.client.get(reverse('purchasing:report_detail',args=[r.pk]))
        for label in ['구매처','수량','단가','총액','구매 사유','선택 필요']:self.assertContains(response,label)
        self.assertContains(response,'type="radio"',count=3);self.assertNotContains(response,'data-item-receipt')
        self.assertNotContains(response,'수령 현황');self.assertNotContains(response,'<select id="decision-')
        self.as_user('finance');self.assertContains(self.client.get(reverse('purchasing:report_detail',args=[r.pk])),'data-item-receipt')

    def test_incomplete_decision_never_completes_and_invalid_reason_keeps_selection(self):
        d=self.confirmed();r=self.report([d]);item=r.items.get();self.as_user('ceo');url=reverse('purchasing:report_detail',args=[r.pk])
        response=self.client.post(url,dict(intent='final',revision=0));r.refresh_from_db();self.assertEqual(r.status,'pending')
        response=self.client.post(url,{'intent':'final','revision':0,'decision_'+str(item.pk):'deny'})
        self.assertContains(response,'value="deny" checked');r.refresh_from_db();self.assertEqual(r.status,'pending')
        d.refresh_from_db();self.assertEqual(d.status,'ceo')

    def test_purchase_policy_grants_only_selected_eligible_reviewers(self):
        p=PurchasePolicy.objects.get(pk=1);f=IntegratedPolicyForm(instance=p)
        data={name:f.initial.get(name,field.initial) for name,field in f.fields.items()};data.update(reason='검토자 승인완료 권한',review_final_users=[self.user('quality_manager').pk])
        f=IntegratedPolicyForm(data,instance=p);self.assertTrue(f.is_valid(),f.errors);f.save(self.user('admin'))
        self.assertEqual(list(p.review_final_users.values_list('pk',flat=True)),[self.user('quality_manager').pk])
        data['review_final_users']=[self.user('quality').pk];f=IntegratedPolicyForm(data,instance=p);self.assertFalse(f.is_valid())

    def test_rule_list_toggle_preserves_old_route_and_blocks_stale_toggle(self):
        ApprovalRule.objects.filter(kind='leave').update(enabled=False)
        rule=ApprovalRule.objects.create(name='직원 휴가 검토',kind='leave',enabled=True,reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:])
        d=save_document(Document(owner=self.user('quality'),kind='leave',reviewer=self.user('quality_manager'),start_date=date(2027,11,1),end_date=date(2027,11,1),reason='일정'),self.user('quality'),submit=True)
        before=dict(d.route_snapshot);self.as_user('admin');url='/regulations/?tab=leave'
        response=self.client.get(url);self.assertContains(response,'적용 대상');self.assertContains(response,'사용 중 1개')
        self.client.post(url,dict(intent='toggle_rule',rule=rule.pk,version=rule.version,enabled='0'))
        rule.refresh_from_db();self.assertFalse(rule.enabled);d.refresh_from_db();self.assertEqual(d.route_snapshot,before)
        self.client.post(url,dict(intent='toggle_rule',rule=rule.pk,version=1,enabled='1'));rule.refresh_from_db();self.assertFalse(rule.enabled)
        self.client.post(url,dict(intent='toggle_rule',rule=rule.pk,version=rule.version,enabled='1'));rule.refresh_from_db();self.assertTrue(rule.enabled)

    def test_rule_toggle_cannot_enable_overlapping_rule_or_be_used_by_employee(self):
        ApprovalRule.objects.filter(kind='leave').update(enabled=False)
        args=dict(kind='leave',reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:])
        ApprovalRule.objects.create(name='기본',enabled=True,**args);other=ApprovalRule.objects.create(name='중복',enabled=False,**args)
        url='/regulations/?tab=leave';data=dict(intent='toggle_rule',rule=other.pk,version=other.version,enabled='1')
        self.as_user('quality');self.assertEqual(self.client.post(url,data).status_code,403)
        self.as_user('admin');self.client.post(url,data);other.refresh_from_db();self.assertFalse(other.enabled)
        c=Client(enforce_csrf_checks=True);c.force_login(self.user('admin'));self.assertEqual(c.post(url,data).status_code,403)

    def test_leave_reviewer_cannot_forward_to_self_or_finish_without_authority(self):
        d=save_document(Document(owner=self.user('quality'),kind='leave',reviewer=self.user('quality_manager'),start_date=date(2027,11,1),end_date=date(2027,11,1),reason='일정'),self.user('quality'),submit=True)
        self.assertTrue(d.progressive);self.assertIsNone(d.approver_id)
        with self.assertRaises(PermissionDenied):act_on_document(d.pk,self.user('quality_manager'),'review_final')
        with self.assertRaises(ValidationError):act_on_document(d.pk,self.user('quality_manager'),'forward',new_person=self.user('quality_manager'))
        self.assertEqual(act_on_document(d.pk,self.user('quality_manager'),'forward',new_person=self.user('quality_lead')).status,'approve')
