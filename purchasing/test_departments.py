"""Department routing, permission boundaries and live receipts beside frozen approvals."""
import unittest
from django.conf import settings
if not settings.PURCHASE_LAB_ENABLED:raise unittest.SkipTest('Isolated purchase lab only.')
from decimal import Decimal
from uuid import uuid4
from django.test import TestCase,Client
from django.urls import reverse
from django.core.exceptions import PermissionDenied,ValidationError
from django.contrib.auth import get_user_model
from . import tests as helpers
from .models import PurchasePolicy,PurchasePermission,PurchaseRequest,PurchaseNotice
from .services import save_request,request_action,submit_report,decide_report,amend_amount
from .access import requests_for,can_view_purchase,notices_for,checker_requests
from .forms import RequestForm,PolicyForm
from .fulfillment import report_fulfillment
from workflow.models import Profile

class DepartmentPurchaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        helpers.PurchaseFlowTests.setUpTestData.__func__(cls)
        PurchasePolicy.objects.filter(pk=1).update(department_routing=True)
        PurchasePermission.objects.get_or_create(user=cls.users['p_dev_director'],defaults={'view_completed':True})
    user=helpers.PurchaseFlowTests.user
    as_user=helpers.PurchaseFlowTests.as_user
    decisions=helpers.PurchaseFlowTests.decisions
    def create(self,who='quality_manager',method='direct',**overrides):
        values=dict(product='부서 경로 시험 장치',vendor='가상구매처',quantity=10,unit_price=Decimal('50000'),url='https://example.com/item',reason='부서별 구매 경로 검증',private=False,request_method=method)
        if who in ['dev_manager','dev']:values.update(reviewer=self.user('dev_lead'),approver=self.user('dev_director'))
        elif who=='quality':values.update(reviewer=self.user('quality_manager'),approver=self.user('quality_lead'))
        values.update(overrides);return save_request(self.user(who),values,submit=True,key=uuid4())
    def confirmed(self,who='quality_manager'):
        d=self.create(who)
        return d if d.confirmed_at else request_action(d.pk,d.purchase_checker,'confirm_items')
    def report(self,docs):return submit_report(self.user('finance'),[d.pk for d in docs],'부서별 구매요청','구매 필요성을 확인했습니다.',uuid4())
    def final(self,docs,choices):
        r=self.report(docs);decide_report(r.pk,self.user('ceo'),self.decisions(r,choices),0,final=True)
        for d in docs:d.refresh_from_db()
        r.refresh_from_db();return r
    def policy_data(self):
        p=PurchasePolicy.objects.get(pk=1);f=PolicyForm(instance=p)
        return p,{name:f.initial.get(name,field.initial) for name,field in f.fields.items()}

    def test_direct_request_preserves_department_checker_before_finance(self):
        for who,checker in [('dev_manager','dev_director'),('quality_manager','prod_director')]:
            d=self.create(who);self.assertEqual(d.status,'ready');self.assertEqual(d.purchase_checker,self.user(checker));self.assertIsNone(d.confirmed_at)
            self.assertFalse(requests_for(self.user('finance')).filter(pk=d.pk).exists())
            self.assertTrue(checker_requests(self.user(checker)).filter(pk=d.pk).exists())
            d=request_action(d.pk,self.user(checker),'confirm_items');self.assertEqual(d.confirmation_method,'manual')
            self.assertTrue(requests_for(self.user('finance')).filter(pk=d.pk).exists())

    def test_other_checker_cannot_view_confirm_supplement_or_get_notification(self):
        for who,wrong in [('dev_manager','prod_director'),('quality_manager','dev_director')]:
            d=self.create(who)
            self.assertFalse(requests_for(self.user(wrong)).filter(pk=d.pk).exists());self.assertFalse(can_view_purchase(self.user(wrong),d))
            for action in ['confirm_items','request_supplement']:
                with self.assertRaises(PermissionDenied):request_action(d.pk,self.user(wrong),action,'시도')
            self.assertFalse(notices_for(self.user(wrong)).filter(request=d).exists())
            self.as_user(wrong);self.assertEqual(self.client.get(reverse('purchasing:detail',args=[d.pk])).status_code,404)

    def test_junior_and_restricted_senior_cannot_forge_direct_request(self):
        for who in ['quality','dev']:
            with self.assertRaises(PermissionDenied):self.create(who,'direct')
        p=PurchasePolicy.objects.get(pk=1);p.direct_ranks=['이사'];p.save()
        with self.assertRaises(PermissionDenied):self.create('dev_manager')
        form=RequestForm(user=self.user('dev_manager'),policy=p)
        self.assertEqual(list(form.fields['request_method'].choices),[('review','검토 요청')])
        p.direct_ranks=['사원','대리'];p.save()
        with self.assertRaises(PermissionDenied):self.create('dev')

    def test_review_request_then_matching_final_approver_combines_confirmation(self):
        d=self.create('dev_manager','review');self.assertEqual(d.status,'review')
        d=request_action(d.pk,self.user('dev_lead'),'approve');self.assertEqual(d.status,'approval');self.assertIsNone(d.confirmed_at)
        self.as_user('dev_director');response=self.client.get(reverse('purchasing:detail',args=[d.pk]));self.assertContains(response,'승인하고 구매담당자에게 전달')
        d=request_action(d.pk,self.user('dev_director'),'approve')
        self.assertEqual((d.status,d.confirmation_method,d.confirmed_by_id),('ready','with_approval',self.user('dev_director').pk))
        self.assertTrue(requests_for(self.user('finance')).filter(pk=d.pk).exists())
        self.assertEqual(d.events.filter(event='승인 시 구매 내용 함께 확인').count(),1)
        with self.assertRaises(ValidationError):request_action(d.pk,self.user('dev_director'),'confirm_items')

    def test_other_final_approver_still_requires_assigned_checker(self):
        d=self.create('quality','review');d=request_action(d.pk,self.user('quality_manager'),'approve');d=request_action(d.pk,self.user('quality_lead'),'approve')
        self.assertIsNone(d.confirmed_at);self.assertEqual(d.purchase_checker,self.user('prod_director'))
        self.assertFalse(requests_for(self.user('finance')).filter(pk=d.pk).exists())

    def test_combining_disabled_keeps_separate_confirmation(self):
        PurchasePolicy.objects.filter(pk=1).update(combine_confirmation=False)
        d=self.create('dev_manager','review');request_action(d.pk,self.user('dev_lead'),'approve');d=request_action(d.pk,self.user('dev_director'),'approve')
        self.assertIsNone(d.confirmed_at);d=request_action(d.pk,self.user('dev_director'),'confirm_items');self.assertEqual(d.confirmation_method,'manual')

    def test_assigned_directors_own_direct_request_has_no_fake_confirmation(self):
        for who in ['dev_director','prod_director']:
            d=self.create(who);self.assertEqual(d.confirmation_method,'director_request');self.assertIsNone(d.confirmed_by)
            self.assertIsNotNone(d.confirmed_at);self.assertEqual(d.purchase_route['forwarded_by_id'],d.owner_id)
            self.assertTrue(requests_for(self.user('finance')).filter(pk=d.pk).exists());self.assertEqual(d.status,'ready')
            self.assertFalse(d.events.filter(event='구매 품목 확인').exists())
            self.assertFalse(can_view_purchase(d.owner,d))
            with self.assertRaises(ValidationError):request_action(d.pk,d.owner,'receive',quantity=1)

    def test_self_request_exception_off_uses_other_assigned_director(self):
        PurchasePolicy.objects.filter(pk=1).update(director_self_request=False)
        for who,other in [('dev_director','prod_director'),('prod_director','dev_director')]:
            d=self.create(who);self.assertIsNone(d.confirmed_at);self.assertTrue(d.route['delegated']);self.assertEqual(d.purchase_checker,self.user(other))
            self.assertEqual(RequestForm(user=self.user(who),policy=PurchasePolicy.objects.get(pk=1)).checker,self.user(other))
            with self.assertRaises(PermissionDenied):request_action(d.pk,d.owner,'confirm_items')
            request_action(d.pk,self.user(other),'confirm_items')

    def test_policy_change_applies_to_new_submissions_not_running_requests(self):
        old=self.create('dev_manager')
        second=get_user_model().objects.create_user('another_fake_director',first_name='가상새개발이사');Profile.objects.create(user=second,department='개발팀',rank='이사',approved=True)
        PurchasePermission.objects.create(user=second,view_completed=True)
        p=PurchasePolicy.objects.get(pk=1);p.dev_director=second;p.version+=1;p.save()
        new=self.create('dev_manager');self.assertEqual(old.purchase_checker,self.user('dev_director'));self.assertEqual(new.purchase_checker,second)
        with self.assertRaises(PermissionDenied):request_action(old.pk,second,'confirm_items')
        self.as_user('admin');response=self.client.post(reverse('purchasing:staff'),dict(user=self.user('dev_director').pk,revision=p.version));self.assertEqual(response.status_code,200);self.assertTrue(PurchasePermission.objects.get(user=self.user('dev_director')).view_completed)
        request_action(old.pk,self.user('dev_director'),'confirm_items')

    def test_policy_form_limits_roles_directors_and_automatically_grants_permission(self):
        p,data=self.policy_data();data.update(reason='규정 저장 검증',direct_ranks=['과장','팀장'])
        PurchasePermission.objects.filter(user=self.user('dev_director')).delete()
        form=PolicyForm(data,instance=p);self.assertTrue(form.is_valid(),form.errors);form.save(self.user('admin'))
        self.assertTrue(PurchasePermission.objects.get(user=self.user('dev_director')).view_completed)
        p.refresh_from_db();self.assertEqual(p.direct_ranks,['과장','팀장'])
        data['direct_ranks']=['사원'];self.assertFalse(PolicyForm(data,instance=p).is_valid())
        data['direct_ranks']=['과장'];data['dev_director']=self.user('prod_director').pk;self.assertFalse(PolicyForm(data,instance=p).is_valid())
        self.as_user('admin');response=self.client.post(reverse('purchasing:staff'),dict(user=self.user('prod_director').pk,revision=p.version))
        self.assertEqual(response.status_code,200);self.assertTrue(PurchasePermission.objects.get(user=self.user('prod_director')).view_completed)

    def test_changed_policy_is_rechecked_for_already_open_form(self):
        self.as_user('dev_manager');self.client.get(reverse('purchasing:new'),follow=True)
        PurchasePolicy.objects.filter(pk=1).update(direct_ranks=[])
        payload=dict(key=uuid4(),product='새 요청',vendor='가상처',quantity=1,unit_price='50000',reason='검증',request_method='direct',intent='submit')
        response=self.client.post(reverse('purchasing:new'),payload);self.assertEqual(response.status_code,200);self.assertFalse(PurchaseRequest.objects.exists())

    def test_receipts_visible_in_finance_request_report_and_report_list(self):
        d=self.confirmed();r=self.final([d],['allow']);snapshot=r.items.get().snapshot.copy()
        self.as_user('finance');response=self.client.get(reverse('purchasing:report_detail',args=[r.pk]));self.assertContains(response,'승인된 1개 품목 중 0개 수령 완료')
        d=request_action(d.pk,d.owner,'receive',quantity=6,receipt_key=uuid4())
        response=self.client.get(reverse('purchasing:requests')+'?mode=finance');self.assertContains(response,'6 / 10개');self.assertContains(response,'일부 수령');self.assertContains(response,d.owner.first_name)
        response=self.client.get(reverse('purchasing:report_detail',args=[r.pk]));self.assertContains(response,'받은 수량 6 / 10개')
        request_action(d.pk,d.owner,'receive',quantity=4,receipt_key=uuid4())
        response=self.client.get(reverse('purchasing:report_detail',args=[r.pk]));self.assertContains(response,'승인된 1개 품목 중 1개 수령 완료');self.assertEqual(r.items.get().snapshot,snapshot)
        self.assertContains(self.client.get(reverse('purchasing:reports')),'1개 수령 완료')
        response=self.client.get(reverse('purchasing:requests')+'?mode=finance&receipt=done');self.assertEqual(response.context['total'],1);self.assertFalse(response.context['can_batch']);self.assertNotContains(response,'data-select-all')
        self.assertTrue(notices_for(self.user('finance')).filter(request=d,text__contains='수령 완료').exists())

    def test_report_receipt_summary_excludes_denied_held_pending_and_changed_approvals(self):
        docs=[self.confirmed() for _ in range(3)];r=self.final(docs,['allow','deny','hold'])
        items=list(r.items.select_related('request'));counts=report_fulfillment(r,items)
        self.assertEqual((counts['approved'],counts['denied'],counts['hold'],counts['eligible'],counts['waiting']),(1,1,1,1,1))
        d=docs[0];amend_amount(d.pk,self.user('finance'),10,Decimal('55000'),'금액 증가',d.revision)
        counts=report_fulfillment(r,list(r.items.select_related('request')));self.assertEqual((counts['eligible'],counts['changed']),(0,1))
        other=self.confirmed();pending=self.report([other]);decide_report(pending.pk,self.user('ceo'),self.decisions(pending,['allow']),0,final=False)
        counts=report_fulfillment(pending,list(pending.items.select_related('request')));self.assertEqual(counts['eligible'],0)
        self.as_user('finance');response=self.client.get(reverse('purchasing:report_detail',args=[pending.pk]));self.assertContains(response,'구매승인 확정 후 수령 현황이 표시됩니다.')

    def test_receipt_notice_goes_to_original_assigned_finance_only(self):
        d=self.confirmed();self.final([d],['allow']);PurchasePolicy.objects.get(pk=1).finance.add(self.user('admin'))
        request_action(d.pk,d.owner,'receive',quantity=10,receipt_key=uuid4())
        self.assertTrue(PurchaseNotice.objects.filter(user=self.user('finance'),request=d,text__contains='수령 완료').exists())
        self.assertFalse(PurchaseNotice.objects.filter(user=self.user('admin'),request=d,text__contains='수령 완료').exists())

    def test_confirmation_labels_distinguish_manual_combined_and_self_request(self):
        from .progress import pending_columns
        manual=self.confirmed();self.assertEqual(pending_columns(manual)['confirm'],'확인완료')
        own=self.create('dev_director');self.assertEqual(pending_columns(own)['confirm'],'담당 이사 직접 요청')
        d=self.create('dev_manager','review');request_action(d.pk,self.user('dev_lead'),'approve');d=request_action(d.pk,self.user('dev_director'),'approve')
        self.assertEqual(pending_columns(d)['confirm'],'승인 시 함께 확인')

    def test_finance_summary_post_and_direct_confirmation_keep_csrf_protection(self):
        d=self.create('dev_manager');c=Client(enforce_csrf_checks=True);c.force_login(self.user('dev_director'))
        self.assertEqual(c.post(reverse('purchasing:action',args=[d.pk]),dict(action='confirm_items')).status_code,403)
