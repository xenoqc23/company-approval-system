"""Separate live staff grants on pending leave and purchase documents."""
import unittest
from datetime import date
from django.conf import settings
if not settings.INTEGRATED_PURCHASES:raise unittest.SkipTest('Integrated application only.')
from django.core.exceptions import PermissionDenied,ValidationError
from django.test import TestCase,Client
from django.urls import reverse
from workflow.models import Document,AnnualBalance,ReviewerCompletionAuthority,ApprovalRule,Profile
from workflow.services import save_document,act_on_document
from workflow.progressive import may_review_final
from . import test_integrated as fixtures
from .forms import ReviewCompletionForm,IntegratedPolicyForm
from .models import PurchasePolicy,PurchaseRequest,PurchaseNotice,PurchaseEvent,PurchasePermission
from .services import request_action
from .access import finance_requests


class StaffReviewerAuthorityTests(TestCase):
    setUpTestData=classmethod(fixtures.IntegratedTests.setUpTestData.__func__)
    user=fixtures.IntegratedTests.user
    as_user=fixtures.IntegratedTests.as_user
    create=fixtures.IntegratedTests.create

    def leave(self,reviewer='quality_manager'):
        return save_document(Document(owner=self.user('quality'),kind='leave',reviewer=self.user(reviewer),
            start_date=date(2027,11,1),end_date=date(2027,11,1),reason='휴가 일정'),self.user('quality'),submit=True)

    def grant_data(self,leave=(),purchase=()):
        f=ReviewCompletionForm()
        return dict(leave_revision=f.initial['leave_revision'],purchase_revision=f.initial['purchase_revision'],
            leave_users=[self.user(n).pk for n in leave],purchase_users=[self.user(n).pk for n in purchase],reason='문서별 검토 권한 지정')

    def grant(self,leave=(),purchase=()):
        self.as_user('admin')
        response=self.client.post(reverse('purchasing:reviewer_authority'),self.grant_data(leave,purchase))
        self.assertRedirects(response,reverse('staff')+'#reviewer-authority',fetch_redirect_response=False)

    def test_staff_has_two_separate_groups_and_rules_cannot_edit_grants(self):
        self.as_user('admin');response=self.client.get(reverse('staff'))
        self.assertContains(response,'휴가원 · 검토 단계에서 승인완료 가능한 직원')
        self.assertContains(response,'구매요청서 · 검토 단계에서 승인완료 가능한 직원')
        self.assertContains(response,'이미 요청된')
        self.assertNotIn('review_final_users',IntegratedPolicyForm(instance=PurchasePolicy.objects.get(pk=1)).fields)
        self.assertNotContains(self.client.get(reverse('purchasing:regulations')),'name="review_final_users"')
        self.assertNotContains(self.client.get('/regulations/?tab=leave'),'name="review_final_users"')

    def test_purchase_only_grant_updates_pending_checker_review_and_top_button(self):
        d=self.create('quality','review',reviewer=self.user('prod_director'));leave=self.leave('prod_director')
        route=dict(d.route);policy=PurchasePolicy.objects.get(pk=1)
        roles=(policy.dev_director_id,policy.production_director_id,policy.representative_id,list(policy.finance.values_list('pk',flat=True)))
        self.as_user('prod_director');url=reverse('purchasing:detail',args=[d.pk])
        self.assertNotContains(self.client.get(url),'value="review_final"')
        self.grant(purchase=['prod_director']);d.refresh_from_db();policy.refresh_from_db()
        self.assertEqual((d.status,d.route),('review',route));self.assertFalse(may_review_final(leave,self.user('prod_director')))
        self.assertEqual(roles,(policy.dev_director_id,policy.production_director_id,policy.representative_id,list(policy.finance.values_list('pk',flat=True))))
        self.as_user('prod_director');page=self.client.get(url);html=page.content.decode()
        self.assertTrue(page.context['review_combined']);self.assertContains(page,'>승인완료</button>')
        self.assertLess(html.index('data-review-final'),html.index('data-forward-visible'))
        self.assertContains(page,'다른 승인자에게 전달 · 선택');self.assertNotContains(page,'전결로 승인완료')
        self.client.post(reverse('purchasing:action',args=[d.pk]),dict(action='review_final'))
        d.refresh_from_db();self.assertEqual(d.status,'ready');self.assertEqual(d.confirmed_by_id,self.user('prod_director').pk)
        self.assertEqual(d.confirmation_method,'with_approval');self.assertIsNone(d.paid_at)
        self.assertTrue(finance_requests(self.user('finance')).filter(pk=d.pk).exists())
        self.assertEqual(PurchaseNotice.objects.filter(request=d,user=self.user('finance')).count(),1)

    def test_leave_only_grant_updates_pending_and_charges_once(self):
        leave=self.leave();purchase=self.create('quality','review');before=dict(leave.route_snapshot)
        self.grant(leave=['quality_manager']);leave.refresh_from_db();self.assertEqual(leave.route_snapshot,before)
        self.as_user('quality_manager');page=self.client.get(reverse('detail',args=[leave.pk]));html=page.content.decode()
        self.assertContains(page,'>승인완료</button>');self.assertLess(html.index('data-review-final'),html.index('data-workflow-forward'))
        self.assertNotContains(self.client.get(reverse('purchasing:detail',args=[purchase.pk])),'value="review_final"')
        used_before=sum(AnnualBalance.objects.filter(user=leave.owner).values_list('used',flat=True))
        leave=act_on_document(leave.pk,self.user('quality_manager'),'review_final')
        self.assertEqual(leave.status,'approved');self.assertEqual(leave.route_snapshot['review_final_authority']['source'],'staff')
        self.assertEqual(sum(AnnualBalance.objects.filter(user=leave.owner).values_list('used',flat=True)),used_before+1)
        with self.assertRaises(PermissionDenied):act_on_document(leave.pk,self.user('quality_manager'),'review_final')
        self.assertEqual(sum(AnnualBalance.objects.filter(user=leave.owner).values_list('used',flat=True)),used_before+1)

    def test_unselected_checker_or_other_reviewer_cannot_complete_even_forging_post(self):
        checker=self.create('quality','review',reviewer=self.user('prod_director'));other=self.create('quality','review')
        self.grant(purchase=['dev_director'])
        for name,d in [('prod_director',checker),('quality_manager',other)]:
            self.as_user(name);self.assertNotContains(self.client.get(reverse('purchasing:detail',args=[d.pk])),'value="review_final"')
            self.assertEqual(self.client.post(reverse('purchasing:action',args=[d.pk]),dict(action='review_final')).status_code,403)
            d.refresh_from_db();self.assertEqual(d.status,'review');self.assertIsNone(d.confirmed_at)

    def test_revocation_blocks_stale_open_pages_for_both_kinds(self):
        leave=self.leave();purchase=self.create('quality','review')
        self.grant(leave=['quality_manager'],purchase=['quality_manager'])
        self.as_user('quality_manager')
        self.assertContains(self.client.get(reverse('detail',args=[leave.pk])),'data-review-final')
        self.assertContains(self.client.get(reverse('purchasing:detail',args=[purchase.pk])),'data-review-final')
        self.grant()
        for func,d in [(act_on_document,leave),(request_action,purchase)]:
            with self.assertRaises(PermissionDenied):func(d.pk,self.user('quality_manager'),'review_final')
            d.refresh_from_db();self.assertEqual(d.status,'review')

    def test_existing_fixed_routes_allow_explicit_authorized_completion_without_bulk_rewrite(self):
        leave=self.leave();leave.route_snapshot={**leave.route_snapshot,'progressive':False};leave.approver=self.user('quality_lead');leave.save()
        purchase=self.create('quality','review',reviewer=self.user('prod_director'))
        purchase.route.pop('reviewer_decides');purchase.route['combine_confirmation']=False
        purchase.approver=self.user('quality_lead');purchase.save()
        old_leave=dict(leave.route_snapshot);old_purchase=dict(purchase.route)
        self.grant(leave=['quality_manager'],purchase=['prod_director'])
        leave.refresh_from_db();purchase.refresh_from_db()
        self.assertEqual(leave.route_snapshot,old_leave);self.assertEqual(purchase.route,old_purchase)
        self.as_user('quality_manager');self.assertContains(self.client.get(reverse('detail',args=[leave.pk])),'data-review-final')
        self.assertEqual(act_on_document(leave.pk,self.user('quality_manager'),'review_final').status,'approved')
        purchase=request_action(purchase.pk,self.user('prod_director'),'review_final')
        self.assertEqual(purchase.status,'ready');self.assertIsNotNone(purchase.confirmed_at)

    def test_finance_missing_rolls_back_completion_and_double_post_does_not_duplicate(self):
        d=self.create('quality','review',reviewer=self.user('prod_director'));self.grant(purchase=['prod_director'])
        p=PurchasePolicy.objects.get(pk=1);p.finance.clear();events=d.events.count()
        with self.assertRaises(ValidationError):request_action(d.pk,self.user('prod_director'),'review_final')
        d.refresh_from_db();self.assertEqual(d.status,'review');self.assertIsNone(d.reviewed_at);self.assertEqual(d.events.count(),events)
        p.finance.add(self.user('finance'));request_action(d.pk,self.user('prod_director'),'review_final')
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('prod_director'),'review_final')
        self.assertEqual(PurchaseEvent.objects.filter(request=d,event='내부 승인완료').count(),1)
        self.assertEqual(PurchaseNotice.objects.filter(request=d,user=self.user('finance')).count(),1)

    def test_authorized_nonchecker_still_requires_assigned_purchase_confirmation(self):
        d=self.create('quality','review');self.grant(purchase=['quality_manager'])
        d=request_action(d.pk,self.user('quality_manager'),'review_final')
        self.assertIsNone(d.confirmed_at);self.assertFalse(finance_requests(self.user('finance')).filter(pk=d.pk).exists())

    def test_grant_does_not_rewind_forwarded_or_completed_documents(self):
        d=self.create('quality','review');d=request_action(d.pk,d.reviewer,'forward',new_person=self.user('prod_director'))
        route=dict(d.route);self.grant(purchase=['quality_manager']);d.refresh_from_db()
        self.assertEqual((d.status,d.route,d.approver_id),('approval',route,self.user('prod_director').pk))
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('quality_manager'),'review_final')
        d=request_action(d.pk,self.user('prod_director'),'approve');completed=(d.route,d.confirmed_at,d.confirmed_by_id)
        self.grant();d.refresh_from_db();self.assertEqual((d.route,d.confirmed_at,d.confirmed_by_id),completed)

    def test_grant_form_rejects_unsafe_people_nonadmins_stale_revision_and_csrf(self):
        for who in ['quality','admin','ceo']:
            form=ReviewCompletionForm(self.grant_data(leave=[who],purchase=[who]));self.assertFalse(form.is_valid())
        stale=self.grant_data(purchase=['prod_director']);self.grant()
        self.as_user('admin');response=self.client.post(reverse('purchasing:reviewer_authority'),stale)
        self.assertContains(response,'다른 창에서 권한이나 담당자 설정이 변경')
        self.as_user('finance');self.assertEqual(self.client.post(reverse('purchasing:reviewer_authority'),self.grant_data()).status_code,403)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.user('admin'))
        self.assertEqual(csrf.post(reverse('purchasing:reviewer_authority'),self.grant_data()).status_code,403)

    def test_staff_setting_overrides_legacy_rule_and_later_rule_edits_cannot_grant(self):
        leave=self.leave()
        rule=ApprovalRule.objects.create(name='기존 공통 전결',kind='all',enabled=True,allow_review_final=True)
        rule.review_final_users.add(self.user('quality_manager'))
        form=ReviewCompletionForm();self.assertIn(self.user('quality_manager').pk,form.initial['leave_users'])
        self.grant();rule.review_final_users.add(self.user('prod_director'))
        self.assertFalse(may_review_final(leave,self.user('quality_manager')))

    def test_revoked_purchase_confirmation_and_inactive_staff_cannot_use_granted_button(self):
        d=self.create('quality','review',reviewer=self.user('prod_director'));other=self.create('quality','review')
        self.grant(purchase=['prod_director'])
        PurchasePermission.objects.filter(user=self.user('prod_director')).update(view_completed=False)
        d=request_action(d.pk,self.user('prod_director'),'review_final')
        self.assertIsNone(d.confirmed_at);self.assertFalse(finance_requests(self.user('finance')).filter(pk=d.pk).exists())
        self.grant(purchase=['quality_manager'])
        Profile.objects.filter(user=self.user('quality_manager')).update(approved=False)
        with self.assertRaises(PermissionDenied):request_action(other.pk,self.user('quality_manager'),'review_final')
