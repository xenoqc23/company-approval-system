from datetime import date, time
from decimal import Decimal
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse
from .models import AnnualBalance, ApprovalFlowPolicy, ApprovalRule, Audit, Document, Notice, Profile, RANKS
from .services import save_document, act_on_document, visible_documents
from .progressive import forward_candidates
from .representatives import assign_representative, remove_representative
from .forms import DocumentForm


class ProgressiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ApprovalFlowPolicy.objects.update_or_create(pk=1,defaults=dict(enabled=True,leave_threshold=3,purchase_threshold=1000000))
        ApprovalRule.objects.update(enabled=False)
        cls.rule=ApprovalRule.objects.create(name='단계별 공통 결재',kind='all',enabled=True,
            reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:],allow_review_final=True,
            allow_self_approval=True,allow_representative_direct=True)
        for key,rank,flags in [('admin','이사',dict(manage_system=True)),('owner','대리',{}),
            ('reviewer','팀장',{}),('approver','이사',{}),('finance','과장',dict(manage_leave=True,view_accounting=True,procure=True)),
            ('ceo','이사',{}),('otherceo','이사',{}),('lead','팀장',{}),('junior','주임',{})]:
            u=get_user_model().objects.create_user(key,first_name=key,password='flow-tests-only')
            Profile.objects.create(user=u,department='개발팀',rank=rank,approved=True,hire_date=date(2020,1,1))
            for k,v in flags.items():setattr(u.profile,k,v)
            u.profile.save()
            AnnualBalance.objects.create(user=u,year=2026,total=20,used=0,grant_initialized=True)
            setattr(cls,key,u)
        cls.rule.review_final_users.add(cls.reviewer,cls.approver,cls.finance,cls.lead)
        assign_representative(cls.admin,cls.ceo,can_approve=True)

    def fresh(self,u):return get_user_model().objects.select_related('profile').get(pk=u.pk)
    def used(self):return AnnualBalance.objects.get(user=self.owner,year=2026).used
    def leave(self,**kwargs):
        data=dict(owner=self.owner,reviewer=self.reviewer,kind='leave',leave_type='annual',
            start_date=date(2026,10,19),end_date=date(2026,10,19),reason='개인 일정')
        data.update(kwargs);return save_document(Document(**data),data['owner'],submit=True)
    def office(self,amount):
        return save_document(Document(owner=self.owner,reviewer=self.reviewer,kind='office',product='비품',
            unit_price=amount,url='https://example.com/item',recipient=self.owner),self.owner,submit=True)
    def forward(self,doc):return act_on_document(doc.pk,self.reviewer,'forward','검토 완료',self.approver)

    def test_normal_submission_defers_approver_even_when_forged_or_prefilled(self):
        doc=self.leave(approver=self.junior)
        self.assertEqual(doc.status,'review');self.assertIsNone(doc.approver_id);self.assertTrue(doc.progressive)
        self.assertEqual(self.used(),0)
        self.assertEqual(Notice.objects.filter(document=doc,stage='검토대기').get().user_id,self.reviewer.pk)
        self.assertFalse(Notice.objects.filter(document=doc,user=self.junior).exists())

    def test_named_reviewer_final_is_independent_of_author_but_direct_ceo_is_not(self):
        self.rule.authors.add(self.lead)
        doc=self.leave()
        self.assertFalse(doc.route_snapshot['allow_review_final'])
        doc=act_on_document(doc.pk,self.reviewer,'review_final','체크된 검토자는 다른 기안자 문서도 전결')
        self.assertEqual(doc.status,'approved')
        self.assertEqual(doc.route_snapshot['review_final_authority']['reviewer_id'],self.reviewer.pk)
        with self.assertRaises(ValidationError):self.leave(owner=self.approver,approval_mode='ceo')
        self.rule.authors.clear();self.rule.amount_over=1000000;self.rule.save()
        from .delegation import resolve_route
        route=resolve_route('office',self.lead.profile.rank,Decimal('999999'),owner=self.lead)
        self.assertFalse(route['allow_review_final']);self.assertNotIn('ceo',route['available_modes'])

    def test_reviewer_final_charges_once_and_can_cancel_with_preserved_history(self):
        doc=self.leave()
        for reason in ['','   ']:
            with self.assertRaises(ValidationError):act_on_document(doc.pk,self.reviewer,'review_final',reason)
        doc=act_on_document(doc.pk,self.reviewer,'review_final','부서 내 처리 가능')
        self.assertEqual(doc.status,'approved');self.assertEqual(self.used(),1)
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.reviewer,'review_final','반복')
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(reverse('detail',args=[doc.pk])),'최종 승인 취소')
        act_on_document(doc.pk,self.reviewer,'cancel_approval','일정 취소')
        self.assertEqual(self.used(),0);self.assertTrue(Audit.objects.filter(document=doc,event='검토자 전결').exists())
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.reviewer,'cancel_approval','반복')

    def test_threshold_boundaries_are_inclusive_and_use_actual_leave_charge(self):
        low=self.leave(end_date=date(2026,10,20));self.assertFalse(low.route_snapshot['representative_option'])
        low.status='rejected';low.save()
        high=self.leave(end_date=date(2026,10,21));self.assertTrue(high.route_snapshot['representative_option'])
        high=act_on_document(high.pk,self.reviewer,'review_final','3일도 허용된 전결 가능')
        self.assertEqual(high.status,'approved');self.assertEqual(self.used(),3)
        self.assertFalse(self.office(Decimal('999999.99')).route_snapshot['representative_option'])
        self.assertTrue(self.office(Decimal('1000000')).route_snapshot['representative_option'])

    def test_forward_requires_reason_and_qualified_non_author_approver(self):
        doc=self.leave()
        with self.assertRaises(ValidationError):act_on_document(doc.pk,self.reviewer,'forward','',self.approver)
        for person in [None,self.junior,self.owner,self.fresh(self.ceo)]:
            with self.assertRaises(ValidationError):act_on_document(doc.pk,self.reviewer,'forward','전달',person)
        doc=self.forward(doc);self.assertEqual(doc.status,'approve');self.assertEqual(doc.approver_id,self.approver.pk)
        self.assertEqual(self.used(),0)
        act_on_document(doc.pk,self.approver,'approve');self.assertEqual(self.used(),1)

    def test_large_request_may_finish_at_approver_without_ceo(self):
        doc=self.forward(self.office(1000000))
        doc=act_on_document(doc.pk,self.approver,'approve')
        self.assertEqual(doc.status,'approved');self.assertIsNone(doc.representative_id)

    def test_escalation_waits_for_ceo_before_leave_charge_accounting_and_calendar(self):
        doc=self.forward(self.leave(end_date=date(2026,10,21)))
        doc=act_on_document(doc.pk,self.approver,'escalate','대표 판단 필요')
        self.assertEqual(doc.status,'executive');self.assertIsNone(doc.approved_at);self.assertEqual(self.used(),0)
        self.assertFalse(visible_documents(self.finance).filter(pk=doc.pk).exists())
        self.assertTrue(visible_documents(self.fresh(self.ceo)).filter(pk=doc.pk).exists())
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.approver,'approve')
        doc=act_on_document(doc.pk,self.fresh(self.ceo),'approve')
        self.assertEqual(doc.status,'approved');self.assertEqual(self.used(),3)
        self.assertTrue(visible_documents(self.finance).filter(pk=doc.pk).exists())
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.fresh(self.ceo),'approve')
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.approver,'cancel_approval','중간 승인자')
        act_on_document(doc.pk,self.fresh(self.ceo),'cancel_approval','취소')
        self.assertEqual(self.used(),0)

    def test_ceo_pending_count_and_owner_progress_include_executive_stage(self):
        doc=act_on_document(self.forward(self.office(1000000)).pk,self.approver,'escalate','대표 요청')
        self.client.force_login(self.fresh(self.ceo));response=self.client.get(reverse('documents'),dict(mode='pending'))
        self.assertEqual(response.context['nav_waiting'],1);self.assertContains(response,doc.number)
        self.assertContains(self.client.get(reverse('detail',args=[doc.pk])),'대표 최종 승인')
        self.client.force_login(self.owner);response=self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['progress_count'],1);self.assertContains(response,'대표 결재')

    def test_ceo_can_reject_only_assigned_requests_and_cannot_write_other_data(self):
        doc=act_on_document(self.forward(self.office(1000000)).pk,self.approver,'escalate','대표 요청')
        ceo=self.fresh(self.ceo);self.client.force_login(ceo)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(ceo)
        self.assertEqual(csrf.post(reverse('action',args=[doc.pk]),dict(action='approve')).status_code,403)
        self.assertEqual(self.client.post(reverse('action',args=[doc.pk]),dict(action='reject',reason='재검토')).status_code,302)
        doc.refresh_from_db();self.assertEqual(doc.status,'rejected')
        for name in ['compose','staff','balances']:
            self.assertEqual(self.client.post(reverse(name),{}).status_code,403)
        another=self.leave()
        with self.assertRaises(PermissionDenied):act_on_document(another.pk,ceo,'approve')
        self.assertEqual(self.used(),0)

    def test_missing_or_disabled_ceo_does_not_mark_request_approved(self):
        assign_representative(self.admin,self.ceo,can_approve=False,expected_id=self.ceo.pk)
        doc=self.forward(self.office(1000000))
        with self.assertRaises(ValidationError):act_on_document(doc.pk,self.approver,'escalate','대표 요청')
        doc.refresh_from_db();self.assertEqual(doc.status,'approve')

    def test_pending_ceo_requests_block_disabling_replacement_and_removal(self):
        doc=act_on_document(self.forward(self.office(1000000)).pk,self.approver,'escalate','대표 요청')
        with self.assertRaises(ValidationError):assign_representative(self.admin,self.ceo,can_approve=False,expected_id=self.ceo.pk)
        with self.assertRaises(ValidationError):assign_representative(self.admin,self.otherceo,replace=True,expected_id=self.ceo.pk)
        with self.assertRaises(ValidationError):remove_representative(self.admin,self.ceo)
        act_on_document(doc.pk,self.fresh(self.ceo),'reject','반려')
        remove_representative(self.admin,self.ceo)

    def test_reviewer_cannot_finalize_own_request_but_granted_self_mode_allows_large_requests(self):
        doc=self.leave(owner=self.lead,reviewer=self.lead)
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.lead,'review_final','본인')
        doc.status='rejected';doc.save()
        with self.assertRaises(ValidationError):self.leave(owner=self.owner,approval_mode='self',end_date=date(2026,10,21))
        high=self.leave(owner=self.lead,approval_mode='self',end_date=date(2026,10,21))
        self.assertEqual(high.status,'approved')
        self.assertEqual(AnnualBalance.objects.get(user=self.lead,year=2026).used,3)
        purchase=save_document(Document(owner=self.lead,kind='office',approval_mode='self',product='큰 금액 비품',
            quantity=1,unit_price=1000000,url='https://example.com/item'),self.lead,submit=True)
        self.assertEqual(purchase.status,'approved')

    def test_senior_direct_ceo_requires_explicit_rule_and_live_permission(self):
        for user in [self.owner,self.finance]:
            with self.assertRaises(ValidationError):self.leave(owner=user,approval_mode='ceo')
        doc=self.leave(owner=self.lead,approval_mode='ceo',end_date=date(2026,10,21))
        self.assertEqual(doc.status,'executive');self.assertIsNone(doc.reviewer_id);self.assertIsNone(doc.approver_id)
        self.assertIsNone(doc.approved_at)
        act_on_document(doc.pk,self.fresh(self.ceo),'approve')
        self.assertEqual(AnnualBalance.objects.get(user=self.lead,year=2026).used,3)

    def test_off_system_registration_cannot_overlap_ceo_pending_leave(self):
        from .manual_leave import register_manual_leave
        doc=act_on_document(self.forward(self.leave(end_date=date(2026,10,21))).pk,self.approver,'escalate','대표 요청')
        with self.assertRaises(ValidationError):register_manual_leave(self.finance,self.owner,
            dict(used_date=date(2026,10,20),leave_type='annual',reason='수기'),uuid4())
        self.assertEqual(self.used(),0)

    def test_small_document_cannot_be_escalated_but_can_follow_normal_approval(self):
        doc=self.forward(self.leave())
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.approver,'escalate','기준 미만')
        act_on_document(doc.pk,self.approver,'approve');self.assertEqual(self.used(),1)

    def test_stock_progresses_only_after_final_approval_and_then_procurement(self):
        doc=save_document(Document(owner=self.owner,reviewer=self.reviewer,kind='stock',product='재고',quantity=3),self.owner,submit=True)
        self.forward(doc)
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.finance,'place')
        act_on_document(doc.pk,self.approver,'approve');doc=act_on_document(doc.pk,self.finance,'place')
        self.assertEqual(doc.shipment,'ordered')

    def test_frozen_routes_survive_rule_threshold_and_mode_changes(self):
        doc=self.leave(end_date=date(2026,10,21))
        ApprovalFlowPolicy.objects.filter(pk=1).update(enabled=False,leave_threshold=10)
        self.rule.allow_review_final=False;self.rule.save()
        from .progressive import may_review_final
        self.assertFalse(may_review_final(doc,self.reviewer))
        doc=self.forward(doc);doc=act_on_document(doc.pk,self.approver,'escalate','기존 기준 적용')
        self.assertEqual(doc.status,'executive')

    def test_legacy_submitted_route_keeps_original_review_and_approval(self):
        ApprovalFlowPolicy.objects.filter(pk=1).update(enabled=False)
        doc=self.leave(approver=self.approver)
        self.assertFalse(doc.progressive)
        ApprovalFlowPolicy.objects.filter(pk=1).update(enabled=True)
        doc=act_on_document(doc.pk,self.reviewer,'review');self.assertEqual(doc.status,'approve')
        doc=act_on_document(doc.pk,self.approver,'approve');self.assertEqual(doc.status,'approved')

    def test_compose_form_and_http_only_need_reviewer_and_show_dynamic_decisions(self):
        data=dict(kind='leave',leave_type='annual',start_date='2026-10-19',end_date='2026-10-21',reason='개인 일정',reviewer=self.reviewer.pk,approval_mode='base')
        form=DocumentForm(data,instance=Document(owner=self.owner),submit=True)
        self.assertTrue(form.is_valid(),form.errors)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('compose'),{**data,'intent':'submit'}).status_code,302)
        doc=Document.objects.get(owner=self.owner,status='review');self.assertIsNone(doc.approver_id)
        self.client.force_login(self.reviewer)
        response=self.client.get(reverse('detail',args=[doc.pk]));self.assertContains(response,'상위 결재 요청');self.assertContains(response,'>전결로 승인완료</button>')
        response=self.client.post(reverse('action',args=[doc.pk]),dict(action='forward',new_person=self.approver.pk,reason='검토 완료'))
        self.assertEqual(response.status_code,302);doc.refresh_from_db();self.assertEqual(doc.status,'approve')

    def test_preview_keeps_granted_self_and_direct_ceo_at_boundary(self):
        self.client.force_login(self.lead)
        response=self.client.get(reverse('preview_route'),dict(kind='office',total='1000000'))
        self.assertEqual(response.status_code,200)
        route=response.json();self.assertTrue(route['representative_option']);self.assertIn('self',route['available_modes']);self.assertIn('ceo',route['available_modes'])
        route=self.client.get(reverse('preview_route'),dict(kind='leave',start_date='2026-10-19',end_date='2026-10-21',leave_type='annual')).json()
        self.assertTrue(route['representative_option']);self.assertIn('self',route['available_modes'])

    def test_only_admin_can_change_flow_thresholds_and_can_validate_values(self):
        self.client.force_login(self.finance)
        self.assertEqual(self.client.post(reverse('regulations'),dict(intent='flow_policy',enabled='on',leave_threshold=4,purchase_threshold=2000000)).status_code,403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('regulations'),dict(intent='flow_policy',enabled='on',leave_threshold=4,purchase_threshold=2000000)).status_code,302)
        self.assertEqual(ApprovalFlowPolicy.objects.get(pk=1).leave_threshold,4)
        self.client.post(reverse('regulations'),dict(intent='flow_policy',enabled='on',leave_threshold=0,purchase_threshold=-1))
        self.assertEqual(ApprovalFlowPolicy.objects.get(pk=1).leave_threshold,4)
        self.assertTrue(Audit.objects.filter(event='단계별 결재 기준 수정').exists())


class ProgressiveMigrationTests(TransactionTestCase):
    def test_upgrade_adds_only_fields_and_default_policy_preserving_legacy_routes(self):
        before=[('workflow','0016_representative_account')];after=[('workflow','0017_progressive_approval')]
        executor=MigrationExecutor(connection);executor.migrate(before)
        self.addCleanup(lambda:MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        old=executor.loader.project_state(before).apps
        u=old.get_model('auth','User').objects.create(username='existing-progressive-migration',password='preserved-hash')
        old.get_model('workflow','Profile').objects.create(user_id=u.pk,department='개발팀',rank='팀장',approved=True,birthday_month=4,birthday_day=15)
        old.get_model('workflow','Document').objects.create(owner_id=u.pk,reviewer_id=u.pk,approver_id=u.pk,status='approve',route_snapshot={'name':'기존 결재선'},allocations={'2026':'1'})
        old.get_model('workflow','AnnualBalance').objects.create(user_id=u.pk,year=2026,total=22,used=Decimal('3.75'),total_manual=True)
        names=['Profile','Document','AnnualBalance','AnnualPolicy','ApprovalRule','Audit','Notice','ManualLeaveUsage','CompanyLeaveCharge']
        snapshots={n:list(old.get_model('workflow',n).objects.order_by('pk').values()) for n in names}
        MigrationExecutor(connection).migrate(after)
        current=MigrationExecutor(connection).loader.project_state(after).apps
        for n,rows in snapshots.items():
            fields=list(rows[0]) if rows else ['pk']
            self.assertEqual(list(current.get_model('workflow',n).objects.order_by('pk').values(*fields)),rows,n)
        self.assertTrue(current.get_model('workflow','ApprovalFlowPolicy').objects.get(pk=1).enabled)
        self.assertFalse(current.get_model('workflow','Profile').objects.get(user_id=u.pk).representative_can_approve)
