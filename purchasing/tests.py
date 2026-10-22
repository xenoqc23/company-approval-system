import unittest
from django.conf import settings
if not settings.PURCHASE_LAB_ENABLED:
    raise unittest.SkipTest('Purchase-only laboratory is disabled outside its isolated local test.')
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase,Client,override_settings
from django.urls import reverse
from workflow.models import Profile,Document,AnnualBalance
from .models import PurchaseRequest,PurchaseReport,PurchaseReportItem,PurchasePolicy,PurchaseEvent,DemoAccount,PurchasePermission
from .services import save_request,request_action,submit_report,decide_report
from .access import requests_for,reports_for,notices_for
from .forms import PolicyForm


class PurchaseFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.temp=TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.password=Path(cls.temp.name)/'password';cls.password.write_text('fictional-purchase-test-only')
        call_command('seed_purchase_demo',password_file=cls.password,stdout=StringIO())
        cls.users={u.username:u for u in get_user_model().objects.select_related('profile')}

    def user(self,name):return self.users['p_'+name]
    def as_user(self,name):self.client.force_login(self.user(name));return self.client
    def values(self,**extra):
        return dict(product='시험용 모니터 MX-27',vendor='가상구매처',quantity=2,unit_price=Decimal('12345.67'),url='https://example.com/product',reason='노후 장비 교체가 필요합니다.',private=False,reviewer=self.user('dev_lead'),approver=self.user('dev_director'),**extra)
    def create(self,who='dev',**extra):
        values=self.values();values.update(extra)
        if who=='quality':values.update(reviewer=self.user('quality_manager'),approver=self.user('quality_lead'))
        return save_request(self.user(who),values,submit=True,key=uuid4())
    def approved(self,who='dev'):
        d=self.create(who)
        if d.status=='review':d=request_action(d.pk,d.reviewer,'approve')
        if d.status=='approval':d=request_action(d.pk,d.approver,'approve')
        return d
    def ready(self,who='dev'):
        return request_action(self.approved(who).pk,self.user('prod_director'),'confirm_items')
    def report(self,docs=None):return submit_report(self.user('finance'),[d.pk for d in docs or [self.ready()]],'구매 취합 보고','사유·금액 확인 후 보고합니다.',uuid4())
    def decisions(self,report,choices):
        return {str(i.pk):dict(decision=choice,reason='반려 또는 보류 사유' if choice in ['deny','hold'] else '') for i,choice in zip(report.items.all(),choices)}

    def test_internal_approval_and_purchase_confirmation_are_separate(self):
        d=self.create();self.assertEqual(d.status,'review');self.assertIsNone(d.director)
        self.assertFalse(requests_for(self.user('finance')).filter(pk=d.pk).exists())
        self.assertFalse(requests_for(self.user('prod_director')).filter(pk=d.pk).exists())
        d=request_action(d.pk,d.reviewer,'approve');self.assertEqual(d.status,'approval')
        d=request_action(d.pk,d.approver,'approve');self.assertEqual(d.status,'ready');self.assertIsNone(d.confirmed_at)
        self.assertTrue(requests_for(self.user('prod_director')).filter(pk=d.pk).exists())
        self.assertFalse(requests_for(self.user('finance')).filter(pk=d.pk).exists())
        with self.assertRaises(ValidationError):self.report([d])
        d=request_action(d.pk,self.user('prod_director'),'confirm_items')
        self.assertIsNotNone(d.confirmed_at);self.assertEqual(d.confirmed_by,self.user('prod_director'))
        self.assertTrue(requests_for(self.user('finance')).filter(pk=d.pk).exists())
        self.assertEqual(d.status,'ready')

    def test_all_departments_use_the_same_permission_based_completed_box(self):
        docs=[self.approved('dev'),self.approved('quality'),self.approved('sales_manager')]
        self.as_user('prod_director');response=self.client.get(reverse('purchasing:requests')+'?mode=completed')
        self.assertContains(response,'구매요청승인완료함')
        self.assertEqual(len(response.context['documents']),3)
        for d in docs:self.assertIsNone(d.confirmed_at)

    def test_manager_self_final_does_not_auto_confirm_or_expose_to_finance(self):
        for who in ['quality_manager','quality_lead','sales_manager']:
            d=self.create(who)
            self.assertEqual((d.status,d.reviewer_id,d.approver_id,d.director_id),('ready',None,None,None))
            self.assertIsNone(d.confirmed_at)
            self.assertFalse(requests_for(self.user('finance')).filter(pk=d.pk).exists())

    def test_cross_department_self_or_director_intermediate_selection_refused(self):
        p=PurchasePolicy.objects.get(pk=1);p.approval_modes['대리']='review_approval';p.save()
        for review,approve in [(self.user('dev'),self.user('dev_lead')),(self.user('quality_manager'),self.user('dev_lead')),
                               (self.user('dev_director'),self.user('dev_lead'))]:
            with self.assertRaises(ValidationError):self.create(reviewer=review,approver=approve)
        self.assertFalse(PurchaseRequest.objects.exists())

    def test_policy_approval_only_and_request_uses_new_route_but_old_snapshot_stays(self):
        old=self.create('quality_manager')
        p=PurchasePolicy.objects.get(pk=1);p.approval_modes['과장']='approval';p.version+=1;p.save()
        new=self.create('quality_manager',approver=self.user('quality_lead'))
        self.assertEqual(new.status,'approval');self.assertIsNone(new.reviewer)
        old.refresh_from_db();self.assertEqual((old.status,old.route['mode']),('ready','direct'))
        request_action(old.pk,self.user('prod_director'),'confirm_items')

    def test_requester_cannot_forge_own_department_by_service_values(self):
        v=self.values();v.update(department='개발팀',rank='부장')
        d=save_request(self.user('sales_manager'),v,submit=True,key=uuid4())
        self.assertEqual((d.department,d.rank,d.director_id),('영업팀','부장',None))

    def test_finance_preview_includes_purchase_reason_vendor_and_source_without_mutation(self):
        d=self.ready();self.as_user('finance')
        response=self.client.post(reverse('purchasing:report_new'),{'requests':[d.pk],'intent':'preview'})
        self.assertContains(response,'노후 장비 교체가 필요합니다.');self.assertContains(response,'가상구매처');self.assertContains(response,reverse('purchasing:detail',args=[d.pk]))
        self.assertFalse(PurchaseReport.objects.exists());d.refresh_from_db();self.assertEqual(d.status,'ready')

    def test_report_deduplicates_and_refuses_nonapproved_or_already_submitted_items(self):
        waiting=self.create();ready=self.ready()
        with self.assertRaises(ValidationError):self.report([waiting])
        with self.assertRaises(ValidationError):submit_report(self.user('finance'),[ready.pk,ready.pk],'a','b',uuid4())
        report=self.report([ready]);ready.refresh_from_db();self.assertEqual(ready.status,'ceo')
        with self.assertRaises(ValidationError):self.report([ready])
        self.assertEqual(PurchaseReport.objects.count(),1)

    def test_interim_decisions_do_not_grant_purchase_or_allow_payment(self):
        d=self.ready();r=self.report([d]);decide_report(r.pk,self.user('ceo'),self.decisions(r,['allow']),0,final=False)
        d.refresh_from_db();r.refresh_from_db();self.assertEqual((d.status,r.status),('ceo','pending'))
        with self.assertRaises(ValidationError):request_action(d.pk,self.user('finance'),'paid','결제 확인')

    def test_partial_allow_deny_hold_propagates_independently_with_reasons_and_exact_amounts(self):
        docs=[self.ready(who) for who in ['dev','quality_manager','sales_manager']];r=self.report(docs)
        decide_report(r.pk,self.user('ceo'),self.decisions(r,['allow','deny','hold']),0,final=True)
        for d in docs:d.refresh_from_db()
        self.assertEqual([d.status for d in docs],['allowed','denied','hold'])
        self.assertEqual(docs[0].total,Decimal('24691.34'))
        self.assertTrue(docs[1].decision_reason);self.assertTrue(docs[2].decision_reason)
        from .progress import purchase_progress
        self.assertTrue(purchase_progress(docs[1])[2]['blocked'])
        self.assertFalse(purchase_progress(docs[1])[2]['current'])
        self.assertTrue(purchase_progress(docs[2])[2]['paused'])
        r.refresh_from_db();self.assertEqual(r.status,'decided');self.assertEqual(r.result_label,'일부 승인 · 일부 반려/보류')
        for d in docs:self.assertTrue(notices_for(d.owner).filter(request=d,read=False).exists())

    def test_all_decisions_required_and_no_partial_commit_on_invalid_reason(self):
        docs=[self.ready(),self.ready('quality_manager')];r=self.report(docs)
        for choices in [['allow','pending'],['allow','deny']]:
            decisions=self.decisions(r,choices)
            if choices[1]=='deny':decisions[str(r.items.all()[1].pk)]['reason']=''
            with self.assertRaises(ValidationError):decide_report(r.pk,self.user('ceo'),decisions,0,final=True)
        self.assertEqual(list(r.items.values_list('decision',flat=True)),['pending','pending'])
        self.assertTrue(all(d.status=='ceo' for d in PurchaseRequest.objects.filter(pk__in=[d.pk for d in docs])))

    def test_finance_or_director_cannot_make_representative_decisions(self):
        r=self.report()
        for who in ['finance','dev_director','prod_director','admin','dev']:
            with self.assertRaises(PermissionDenied):decide_report(r.pk,self.user(who),self.decisions(r,['allow']),0,final=True)

    def test_revision_and_duplicate_final_confirmation_rejected(self):
        r=self.report();decisions=self.decisions(r,['allow'])
        decide_report(r.pk,self.user('ceo'),decisions,0,final=False)
        with self.assertRaises(ValidationError):decide_report(r.pk,self.user('ceo'),decisions,0,final=True)
        decide_report(r.pk,self.user('ceo'),decisions,1,final=True)
        with self.assertRaises(ValidationError):decide_report(r.pk,self.user('ceo'),decisions,2,final=True)

    def test_allowed_only_payment_then_requester_receives_and_history_kept(self):
        docs=[self.ready(),self.ready('quality_manager')];r=self.report(docs)
        decide_report(r.pk,self.user('ceo'),self.decisions(r,['allow','deny']),0,final=True)
        with self.assertRaises(ValidationError):request_action(docs[1].pk,self.user('finance'),'paid','직접 결제')
        with self.assertRaises(PermissionDenied):request_action(docs[0].pk,self.user('dev'),'paid','직접 결제')
        d=request_action(docs[0].pk,self.user('finance'),'paid','대표님 결제 확인')
        self.assertEqual(d.status,'paid')
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('finance'),'receive')
        d=request_action(d.pk,self.user('dev'),'receive');self.assertEqual(d.status,'received')
        with self.assertRaises(ValidationError):request_action(d.pk,self.user('dev'),'receive')
        self.assertTrue(d.events.filter(event='대표 구매승인').exists())

    def test_hold_can_be_reported_again_without_overwriting_original_batch(self):
        d=self.ready();r=self.report([d]);decide_report(r.pk,self.user('ceo'),self.decisions(r,['hold']),0,final=True)
        d.refresh_from_db();request_action(d.pk,self.user('finance'),'prepare_hold','호환 여부 확인 완료');second=self.report([d]);d.refresh_from_db()
        self.assertEqual((d.status,d.current_report_id),('ceo',second.pk))
        self.assertEqual(r.items.get().decision,'hold');self.assertEqual(d.report_items.count(),2)

    def test_original_snapshots_immutable_and_include_reason_vendor_and_price(self):
        d=self.ready();r=self.report([d]);original=r.items.get().snapshot
        self.assertEqual(original['reason'],d.reason);self.assertEqual(original['vendor'],d.vendor)
        with self.assertRaises(PermissionDenied):save_request(self.user('dev'),self.values(),pk=d.pk)
        self.assertEqual(r.items.get().snapshot,original)

    def test_requester_sees_only_own_document_and_not_other_items_in_batch(self):
        a=self.ready();b=self.ready('quality_manager');r=self.report([a,b]);self.as_user('dev')
        self.assertEqual(self.client.get(reverse('purchasing:detail',args=[a.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('purchasing:detail',args=[b.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('purchasing:report_detail',args=[r.pk])).status_code,404)
        self.as_user('dev_director');self.assertEqual(self.client.get(reverse('purchasing:report_detail',args=[r.pk])).status_code,404)
        self.as_user('ceo');self.assertContains(self.client.get(reverse('purchasing:report_detail',args=[r.pk])),b.reason)

    def test_revoked_finance_access_hides_documents_reports_and_notices(self):
        d=self.ready();r=self.report([d]);PurchasePolicy.objects.get(pk=1).finance.clear()
        self.assertFalse(requests_for(self.user('finance')).exists());self.assertFalse(reports_for(self.user('finance')).exists())
        self.assertFalse(notices_for(self.user('finance')).exists())
        with self.assertRaises(PermissionDenied):self.report([d])

    def test_cancellation_before_batch_only_and_zero_purchase_balance_mutations(self):
        d=self.approved();d=request_action(d.pk,self.user('dev'),'cancel','필요 없어짐');self.assertEqual(d.status,'cancelled')
        d=self.ready();r=self.report([d])
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('dev'),'cancel','취소 시도')
        self.assertFalse(Document.objects.exists());self.assertFalse(AnnualBalance.objects.exists())

    def test_policy_form_easy_rank_routes_and_only_admin_can_save(self):
        p=PurchasePolicy.objects.get(pk=1);form=PolicyForm(instance=p)
        data={name:form.initial.get(name,field.initial) for name,field in form.fields.items()}
        data.update(reason='검토 단계 조정',rank_3='approval')
        bound=PolicyForm(data,instance=p);self.assertTrue(bound.is_valid(),bound.errors)
        with self.assertRaises(ValidationError):bound.save(self.user('finance'))
        bound.save(self.user('admin'));p.refresh_from_db();self.assertEqual(p.approval_modes['과장'],'approval')
        self.as_user('admin');self.assertContains(self.client.get(reverse('purchasing:regulations')),'구매 규정 설정')
        self.as_user('dev');self.assertEqual(self.client.get(reverse('purchasing:regulations')).status_code,403)

    def test_money_invalid_quantity_vendor_and_reason_validation(self):
        for name,value in [('quantity',0),('quantity',1000000),('unit_price',Decimal('-1')),('vendor',''),('reason','')]:
            values=self.values();values[name]=value
            with self.assertRaises(ValidationError):save_request(self.user('dev'),values,submit=True,key=uuid4())
        self.assertFalse(PurchaseRequest.objects.exists())

    def test_csrf_required_for_submit_switch_batch_and_decisions(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.user('dev'))
        self.assertEqual(client.post(reverse('purchasing:new'),{}).status_code,403)
        self.assertEqual(client.post(reverse('purchasing:switch'),{'user':self.user('ceo').pk}).status_code,403)
        client.force_login(self.user('finance'));self.assertEqual(client.post(reverse('purchasing:report_new'),{}).status_code,403)

    def test_seeding_again_keeps_passwords_requests_and_rules(self):
        d=self.create();p=PurchasePolicy.objects.get(pk=1);p.approval_modes['부장']='approval';p.save()
        before={u.pk:u.password for u in get_user_model().objects.all()}
        call_command('seed_purchase_demo',password_file=self.password,stdout=StringIO())
        self.assertEqual(before,{u.pk:u.password for u in get_user_model().objects.all()})
        self.assertTrue(PurchaseRequest.objects.filter(pk=d.pk).exists());self.assertEqual(PurchasePolicy.objects.get(pk=1).approval_modes['부장'],'approval')

    def test_ui_focus_cookie_isolation_and_foreign_features_hidden(self):
        self.as_user('dev');response=self.client.get(reverse('purchasing:home'))
        self.assertContains(response,'구매요청 로컬 테스트');self.assertNotContains(response,'휴가 신청');self.assertNotContains(response,'연차 관리')
        self.assertEqual(settings.SESSION_COOKIE_NAME,'xenosys_purchase_lab_sessionid')
        self.assertEqual(self.client.post('/balances/',{}).status_code,302)
        self.assertEqual(self.client.get('/compose/').status_code,302)

    def test_login_switch_changes_identity_not_stale_permissions(self):
        self.as_user('dev');response=self.client.post(reverse('purchasing:switch'),{'user':self.user('ceo').pk})
        self.assertEqual(response.status_code,302);self.assertEqual(int(self.client.session['_auth_user_id']),self.user('ceo').pk)
        self.assertEqual(self.client.get(reverse('purchasing:new')).status_code,403)

    def test_owner_sees_simple_progress_but_finance_retains_internal_stages(self):
        d=self.ready();self.as_user('dev')
        def assert_simple(label='구매 진행 중'):
            response=self.client.get(reverse('purchasing:detail',args=[d.pk]))
            self.assertContains(response,label)
            for text in ['경리 취합','대표 구매승인','결제 완료 확인','취합 문서:']:
                self.assertNotContains(response,text)
            return response
        assert_simple()
        r=self.report([d]);assert_simple()
        decide_report(r.pk,self.user('ceo'),self.decisions(r,['allow']),0,final=True)
        assert_simple('승인완료')
        self.as_user('finance')
        response=self.client.get(reverse('purchasing:detail',args=[d.pk]))
        self.assertContains(response,'구매 진행 현황');self.assertContains(response,'취합·보고');self.assertContains(response,'대표 구매승인')
        request_action(d.pk,self.user('finance'),'paid','대표 카드 결제 확인')
        self.as_user('dev');response=assert_simple('승인완료');self.assertContains(response,'수령 확인')
        self.assertContains(self.client.get(reverse('purchasing:home')),'구매 진행상황이 변경되었습니다.')
        response=self.client.get(reverse('purchasing:requests')+'?mode=mine&state=paid')
        self.assertContains(response,d.product);self.assertNotContains(response,'대표 구매승인')

    def test_won_entry_round_trip_and_grouping_do_not_change_amount(self):
        from .forms import RequestForm
        for amount in ['50000','50,000','50000.00','49,999.99','50000.01','12345.67']:
            data=self.values();data['unit_price']=amount;data['quantity']=1;data['key']=uuid4()
            form=RequestForm(data,user=self.user('dev'),policy=PurchasePolicy.objects.get(pk=1))
            self.assertTrue(form.is_valid(),form.errors)
            d=save_request(self.user('dev'),form.cleaned_data,submit=True,key=form.cleaned_data['key'])
            d.refresh_from_db();self.assertEqual(d.unit_price,Decimal(amount.replace(',','')))
            self.assertEqual(d.total,Decimal(amount.replace(',','')))
            self.as_user('dev');response=self.client.get(reverse('purchasing:detail',args=[d.pk]))
            if amount in ['50000','50,000','50000.00']:
                self.assertContains(response,'50,000원',count=2);self.assertNotContains(response,'49,999.99원')
        data=self.values();data.update(unit_price='5,00,00',key=uuid4())
        self.assertFalse(RequestForm(data,user=self.user('dev'),policy=PurchasePolicy.objects.get(pk=1)).is_valid())


    def test_duplicate_submit_key_and_payment_does_not_duplicate_events(self):
        key=uuid4();d=save_request(self.user('dev'),self.values(),submit=True,key=key)
        with self.assertRaises(ValidationError):save_request(self.user('dev'),self.values(),submit=True,key=key)
        request_action(d.pk,self.user('dev_lead'),'approve')
        request_action(d.pk,self.user('dev_director'),'approve')
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('dev_director'),'approve')
        self.assertEqual(PurchaseRequest.objects.count(),1)

    def test_removed_representative_cannot_read_batch_or_confirm_payment(self):
        d=self.ready();r=self.report([d]);decide_report(r.pk,self.user('ceo'),self.decisions(r,['allow']),0,final=True)
        Profile.objects.filter(user=self.user('ceo')).update(representative_slot=None)
        self.as_user('ceo')
        self.assertEqual(self.client.get(reverse('purchasing:report_detail',args=[r.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('purchasing:detail',args=[d.pk])).status_code,404)
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('ceo'),'paid','결제 확인')

    def test_purchase_progress_only_for_actual_purchase_participants_not_owner_or_approvers_or_admin(self):
        d=self.ready()
        for role in ['dev','dev_lead','dev_director','admin']:
            self.as_user(role);response=self.client.get(reverse('purchasing:detail',args=[d.pk]))
            self.assertContains(response,'결재 경로');self.assertNotContains(response,'data-purchase-progress');self.assertNotContains(response,'구매 품목 확인</strong>')
        for role in ['prod_director','finance']:
            self.as_user(role);self.assertContains(self.client.get(reverse('purchasing:detail',args=[d.pk])),'data-purchase-progress')
        r=self.report([d]);self.as_user('ceo');self.assertContains(self.client.get(reverse('purchasing:detail',args=[d.pk])),'data-purchase-progress')

    def test_permission_grant_revoke_and_confirmation_are_checked_on_server(self):
        d=self.approved()
        for role in ['dev','dev_director','finance','admin']:
            with self.assertRaises(PermissionDenied):request_action(d.pk,self.user(role),'confirm_items')
        PurchasePermission.objects.filter(user=self.user('prod_director')).update(view_completed=False)
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('prod_director'),'confirm_items')
        self.as_user('prod_director');self.assertEqual(self.client.get(reverse('purchasing:requests')+'?mode=completed').status_code,403)
        PurchasePermission.objects.create(user=self.user('dev_director'),view_completed=True)
        d=request_action(d.pk,self.user('dev_director'),'confirm_items')
        with self.assertRaises(ValidationError):request_action(d.pk,self.user('dev_director'),'confirm_items')
        self.assertEqual(d.events.filter(event='구매 품목 확인').count(),1)

    def test_staff_permission_ui_admin_only_and_role_switch_has_seven_choices(self):
        self.as_user('admin');response=self.client.get(reverse('purchasing:staff'))
        self.assertContains(response,'구매요청승인완료함')
        p=PurchasePolicy.objects.get(pk=1)
        response=self.client.post(reverse('purchasing:staff'),dict(user=self.user('quality_lead').pk,revision=p.version,view_completed='on'))
        self.assertEqual(response.status_code,302);self.assertTrue(PurchasePermission.objects.get(user=self.user('quality_lead')).view_completed)
        self.as_user('quality');self.assertEqual(self.client.get(reverse('purchasing:staff')).status_code,403)
        response=self.client.get(reverse('purchasing:home'));self.assertEqual(len(response.context['demo_accounts']),7)
        self.assertEqual(self.client.post(reverse('purchasing:switch'),dict(user=self.user('dev').pk)).status_code,404)

    def test_granting_permission_to_owner_does_not_allow_self_confirmation_or_purchase_details(self):
        d=self.approved('quality_manager');PurchasePermission.objects.create(user=d.owner,view_completed=True)
        with self.assertRaises(PermissionDenied):request_action(d.pk,d.owner,'confirm_items')
        self.as_user('quality_manager');self.assertNotContains(self.client.get(reverse('purchasing:detail',args=[d.pk])),'data-purchase-progress')

    def test_confirmation_route_snapshot_and_collector_revocation(self):
        d=self.ready();p=PurchasePolicy.objects.get(pk=1)
        p.finance.add(self.user('quality_lead'))
        self.assertFalse(requests_for(self.user('quality_lead')).filter(pk=d.pk).exists())
        with self.assertRaises(ValidationError):submit_report(self.user('quality_lead'),[d.pk],'보고','내용',uuid4())
        p.finance.remove(self.user('finance'))
        with self.assertRaises(PermissionDenied):self.report([d])

    def test_existing_legacy_director_document_can_finish_without_changing_its_route(self):
        d=self.create();d.route={'mode':'direct'};d.reviewer=None;d.approver=None;d.director=self.user('dev_director');d.status='director';d.save()
        d=request_action(d.pk,self.user('dev_director'),'approve');self.assertEqual(d.status,'ready');self.assertIsNone(d.confirmed_at)
        d=request_action(d.pk,self.user('prod_director'),'confirm_items');self.assertIsNotNone(d.confirmed_at)

    def test_legacy_report_without_confirmation_keeps_actual_history_and_assigned_participants(self):
        d=self.ready();r=self.report([d]);d.refresh_from_db();d.confirmed_at=None;d.confirmed_by=None;d.purchase_route={};d.save()
        from .progress import purchase_progress
        self.assertFalse(purchase_progress(d)[0]['done']);self.assertTrue(purchase_progress(d)[0]['legacy'])
        self.as_user('finance');self.assertContains(self.client.get(reverse('purchasing:detail',args=[d.pk])),'이전 테스트에서 이미 보고된 문서')
        decide_report(r.pk,self.user('ceo'),self.decisions(r,['allow']),0,final=True)
        d=request_action(d.pk,self.user('finance'),'paid','기존 보고서의 실제 결제 확인')
        self.assertEqual(d.status,'paid');self.assertIsNone(d.confirmed_at)

    def test_junior_cannot_self_finalize_even_if_rule_is_forged(self):
        p=PurchasePolicy.objects.get(pk=1);p.approval_modes['대리']='direct';p.save()
        with self.assertRaises(ValidationError):self.create()
        form=PolicyForm(instance=p)
        self.assertNotIn('direct',dict(form.fields['rank_2'].choices))

    def test_test_requester_always_requires_separate_reviewer_and_approver(self):
        p=PurchasePolicy.objects.get(pk=1);p.approval_modes['사원']='approval';p.save()
        d=self.create('quality');self.assertEqual(d.status,'review');self.assertIsNotNone(d.approver)
        values=self.values();values.update(reviewer=self.user('quality_manager'),approver=self.user('quality_manager'))
        with self.assertRaises(ValidationError):save_request(self.user('quality'),values,submit=True,key=uuid4())
        from .forms import RequestForm
        form=RequestForm(user=self.user('quality'),policy=p)
        self.assertTrue(form.fields['reviewer'].required);self.assertTrue(form.fields['approver'].required)
        self.assertEqual(form.initial['reviewer'],self.user('quality_manager').pk);self.assertEqual(form.initial['approver'],self.user('quality_lead').pk)

    def test_approved_and_pending_confirmation_collection_are_separate_columns(self):
        first=self.approved('quality');second=self.ready('quality')
        self.as_user('prod_director');response=self.client.get(reverse('purchasing:requests')+'?mode=completed')
        self.assertContains(response,'승인 상태');self.assertContains(response,'구매 품목 확인');self.assertContains(response,'취합·보고')
        self.assertEqual(response.context['queue_counts'],dict(approved=2,confirm=1,collect=1))
        response=self.client.get(reverse('purchasing:requests')+'?mode=completed&stage=confirm')
        self.assertEqual([d.pk for d in response.context['documents']],[first.pk])
        response=self.client.get(reverse('purchasing:requests')+'?mode=completed&stage=collect')
        self.assertEqual([d.pk for d in response.context['documents']],[second.pk])

    def test_representative_uses_purchase_request_approval_return_hold_vocabulary(self):
        d=self.ready();r=self.report([d]);self.as_user('ceo')
        response=self.client.get(reverse('purchasing:report_detail',args=[r.pk]))
        for text in ['구매요청','승인 예정 금액','구매반려 금액','구매보류 금액','구매승인','구매반려','구매보류']:self.assertContains(response,text)
        for text in ['불허','허가','심사 중']:self.assertNotContains(response,text)
        response=self.client.get(reverse('purchasing:home'));self.assertContains(response,'구매요청함');self.assertNotContains(response,'취합 구매')


class PurchasePracticalTests(TestCase):
    @classmethod
    def setUpTestData(cls):PurchaseFlowTests.setUpTestData.__func__(cls)
    user=PurchaseFlowTests.user
    as_user=PurchaseFlowTests.as_user
    values=PurchaseFlowTests.values
    create=PurchaseFlowTests.create
    approved=PurchaseFlowTests.approved
    ready=PurchaseFlowTests.ready
    report=PurchaseFlowTests.report
    decisions=PurchaseFlowTests.decisions

    def setUp(self):
        from django.core.files.storage import FileSystemStorage
        from .models import PurchaseAttachment
        self.storage_dir=TemporaryDirectory();self.addCleanup(self.storage_dir.cleanup)
        patched=patch.object(PurchaseAttachment._meta.get_field('file'),'storage',FileSystemStorage(location=self.storage_dir.name));patched.start();self.addCleanup(patched.stop)

    def pdf(self,name='견적서.pdf',content=b'%PDF-1.4\nfictional quote'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name,content,content_type='application/pdf')

    def paid(self,quantity=10):
        d=self.create('quality',quantity=quantity)
        d=request_action(d.pk,d.reviewer,'approve');d=request_action(d.pk,d.approver,'approve');d=request_action(d.pk,self.user('prod_director'),'confirm_items')
        r=self.report([d]);decide_report(r.pk,self.user('ceo'),self.decisions(r,['allow']),0,final=True)
        return request_action(d.pk,self.user('finance'),'paid','실제 결제 확인')

    def test_compose_attachments_saved_with_document_and_authorized_download_only(self):
        from .models import PurchaseAttachment
        self.as_user('quality');data=self.values();data.update(reviewer=self.user('quality_manager').pk,approver=self.user('quality_lead').pk,quantity=10,key=uuid4(),intent='submit',files=[self.pdf()])
        response=self.client.post(reverse('purchasing:new'),data)
        self.assertEqual(response.status_code,302);d=PurchaseRequest.objects.get();a=PurchaseAttachment.objects.get();self.assertEqual(a.kind,'request');self.assertEqual(a.request,d)
        self.as_user('quality_manager');response=self.client.get(reverse('purchasing:attachment_download',args=[a.pk]));self.assertEqual(response.status_code,200);self.assertIn('attachment;',response['Content-Disposition']);self.assertEqual(b''.join(response.streaming_content),b'%PDF-1.4\nfictional quote')
        self.assertEqual(response['X-Content-Type-Options'],'nosniff');self.assertIn('no-store',response['Cache-Control'])
        self.as_user('sales_manager');self.assertEqual(self.client.get(reverse('purchasing:attachment_download',args=[a.pk])).status_code,404)

    def test_unsupported_empty_oversized_and_excess_files_rejected_before_save(self):
        from .attachments import validated_files
        from .models import PurchaseAttachment
        for files in [[self.pdf('evil.html')],[self.pdf(content=b'')],[self.pdf(content=b'x'*(10*1024*1024+1))],[self.pdf() for _ in range(11)]]:
            with self.assertRaises(ValidationError):validated_files(files)
        self.assertFalse(PurchaseAttachment.objects.exists())

    def test_purchase_receipt_files_hidden_from_owner_and_general_approvers(self):
        from .models import PurchaseAttachment
        d=self.ready('quality');self.as_user('finance')
        self.assertEqual(self.client.post(reverse('purchasing:attachments',args=[d.pk]),dict(files=[self.pdf('영수증.pdf')])).status_code,302)
        a=PurchaseAttachment.objects.get();self.assertEqual(a.kind,'purchase')
        for role in ['quality','quality_manager','quality_lead','admin']:
            self.as_user(role);self.assertEqual(self.client.get(reverse('purchasing:attachment_download',args=[a.pk])).status_code,404)
            self.assertNotContains(self.client.get(reverse('purchasing:detail',args=[d.pk])),'영수증.pdf')
        self.as_user('prod_director');self.assertEqual(self.client.get(reverse('purchasing:attachment_download',args=[a.pk])).status_code,200)
        PurchasePolicy.objects.get(pk=1).finance.clear();self.as_user('finance');self.assertEqual(self.client.get(reverse('purchasing:attachment_download',args=[a.pk])).status_code,404)

    def test_submission_failure_rolls_back_document_events_and_files(self):
        from .models import PurchaseAttachment
        self.as_user('quality');data=self.values();data.update(reviewer=self.user('quality_manager').pk,approver=self.user('quality_lead').pk,key=uuid4(),intent='submit',files=[self.pdf('first.pdf'),self.pdf('second.pdf')])
        original_save=PurchaseAttachment.save
        def fail_second(instance,*args,**kwargs):
            if instance.original_name=='second.pdf':raise ValidationError('파일 저장 실패')
            return original_save(instance,*args,**kwargs)
        with patch.object(PurchaseAttachment,'save',new=fail_second):
            response=self.client.post(reverse('purchasing:new'),data)
        self.assertEqual(response.status_code,200);self.assertFalse(PurchaseRequest.objects.exists());self.assertFalse(PurchaseAttachment.objects.exists());self.assertFalse(PurchaseEvent.objects.exists());self.assertEqual(list(Path(self.storage_dir.name).rglob('*.pdf')),[])

    def test_file_limit_checked_on_existing_document_and_upload_csrf(self):
        from .attachments import StoredFiles
        d=save_request(self.user('quality'),self.values(),submit=False,key=uuid4())
        with StoredFiles() as files:files.add(d,self.user('quality'),[self.pdf(f'{i}.pdf') for i in range(10)],'request')
        self.as_user('quality');self.client.post(reverse('purchasing:attachments',args=[d.pk]),dict(files=[self.pdf()]))
        self.assertEqual(d.attachments.count(),10)
        client=Client(enforce_csrf_checks=True);client.force_login(self.user('quality'));self.assertEqual(client.post(reverse('purchasing:attachments',args=[d.pk]),dict(files=[self.pdf()])).status_code,403)

    def test_partial_receipt_counts_remainder_and_is_idempotent(self):
        d=self.paid();key=uuid4();d=request_action(d.pk,self.user('quality'),'receive','6개 먼저 도착',quantity=6,receipt_key=key,storage_location='품질팀 창고 A-2')
        self.assertEqual((d.status,d.received_quantity,d.remaining_quantity),('paid',6,4));self.assertIsNone(d.received_at)
        with self.assertRaises(ValidationError):request_action(d.pk,self.user('quality'),'receive',quantity=2,receipt_key=key)
        with self.assertRaises(ValidationError):request_action(d.pk,self.user('quality'),'receive',quantity=5,receipt_key=uuid4())
        d=request_action(d.pk,self.user('quality'),'receive',quantity=4,receipt_key=uuid4())
        self.assertEqual((d.status,d.received_quantity,d.remaining_quantity),('received',10,0));self.assertEqual(d.receipts.count(),2);self.assertEqual(d.storage_location,'품질팀 창고 A-2')

    def test_invalid_or_unauthorized_receipt_cannot_change_counts(self):
        d=self.paid()
        for value in [0,-1,11,'1.5',True]:
            with self.assertRaises(ValidationError):request_action(d.pk,self.user('quality'),'receive',quantity=value)
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('finance'),'receive',quantity=1)
        d.refresh_from_db();self.assertEqual(d.received_quantity,0);self.assertEqual(d.receipts.count(),0)

    def test_owner_can_update_location_and_hints_show_received_location_not_stock(self):
        d=self.paid();d=request_action(d.pk,self.user('quality'),'receive',quantity=6,receipt_key=uuid4(),storage_location='창고 A')
        self.as_user('quality');self.client.post(reverse('purchasing:location',args=[d.pk]),dict(storage_location='창고 B'));d.refresh_from_db();self.assertEqual(d.storage_location,'창고 B')
        self.as_user('sales_manager');response=self.client.get(reverse('purchasing:hints')+'?q=시험용');self.assertEqual(response.json()['results'][0]['location'],'창고 B');self.assertEqual(response.json()['results'][0]['received'],6)
        self.assertEqual(self.client.post(reverse('purchasing:location',args=[d.pk]),dict(storage_location='외부')).status_code,404)
        d.private=True;d.save();self.assertEqual(self.client.get(reverse('purchasing:hints')+'?q=시험용').json()['count'],0)

    def test_urgent_requires_reason_and_orders_inbox_first(self):
        from datetime import date
        values=self.values();values.update(urgent=True,urgent_reason='',needed_by=date(2026,11,1))
        with self.assertRaises(ValidationError):save_request(self.user('dev'),values,submit=True,key=uuid4())
        ordinary=self.create('quality');urgent=self.create('quality',urgent=True,urgent_reason='고장으로 업무 중단',needed_by=date(2026,11,1),usage_department='품질팀')
        self.as_user('quality_manager');response=self.client.get(reverse('purchasing:requests')+'?mode=inbox')
        self.assertEqual(response.context['documents'][0].pk,urgent.pk);self.assertContains(response,'긴급');self.assertEqual(ordinary.urgent,False)
