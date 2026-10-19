from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse
from .delegation import resolve_route, route_preview
from .forms import ApprovalRuleForm, DocumentForm
from .models import AnnualBalance, ApprovalRule, Audit, Document, Notice, Profile, RANKS
from .notifications import visible_notices
from .regulations import delete_rule, save_rule
from .services import act_on_document, save_document


class CommonRuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ApprovalRule.objects.update(enabled=False)
        for name, rank in [('owner','과장'),('reviewer','팀장'),('approver','이사'),('finance','과장'),('other','과장')]:
            user=get_user_model().objects.create_user(name,first_name=name,password='test-only-password')
            Profile.objects.create(user=user,rank=rank,department='개발팀',approved=True,
                hire_date=date(2020,1,1),manage_leave=name=='finance',view_accounting=name=='finance',procure=name=='finance')
            AnnualBalance.objects.create(user=user,year=2026,total=19,used=Decimal('2.25'),grant_initialized=True)
            setattr(cls,name,user)

    def rule(self, **kwargs):
        values=dict(name='모든 문서 공통',kind='all',reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:],
            allow_skip_review=True,allow_self_approval=True,enabled=True)
        values.update(kwargs)
        return ApprovalRule.objects.create(**values)

    def doc(self,kind='stock',**kwargs):
        values=dict(owner=self.owner,kind=kind,reviewer=self.reviewer,approver=self.approver,
            product='검증 품목',quantity=2,unit_price=Decimal('100'),url='https://example.com/item',
            start_date=date(2026,11,2),end_date=date(2026,11,2),reason='검증 사유')
        values.update(kwargs)
        return save_document(Document(**values),values['owner'],submit=True)

    def balances(self):
        return list(AnnualBalance.objects.order_by('pk').values())

    def test_all_is_default_for_new_rules_and_one_rule_applies_to_all_three_kinds(self):
        rule=self.rule()
        self.client.force_login(self.finance)
        form=self.client.get(reverse('regulations')).context['rule_form']
        self.assertEqual(form['kind'].value(),'all')
        self.assertIn(('all','모든 문서'),list(form.fields['kind'].choices))
        for kind in ['leave','office','stock']:
            self.assertEqual(resolve_route(kind,'과장',Decimal('200'),owner=self.owner)['rule_id'],rule.pk)

    def test_common_stock_requires_final_approval_before_procurement_and_renders_four_steps(self):
        self.rule()
        before=self.balances();doc=self.doc()
        self.assertTrue(doc.final_approval_required)
        self.assertEqual(doc.status,'review')
        self.client.force_login(self.owner)
        response=self.client.get(reverse('documents'),{'mode':'stock','stock_stage':'review'})
        self.assertIn(('approve','최종승인대기'),response.context['states'])
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.finance,'place')
        doc=act_on_document(doc.pk,self.reviewer,'review')
        self.assertEqual(doc.status,'approve')
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.finance,'place')
        self.client.force_login(self.approver)
        response=self.client.get(reverse('detail',args=[doc.pk]))
        self.assertContains(response,'data-stage="approval"')
        self.assertContains(response,'data-stage="procurement"')
        self.assertContains(response,'four-stage')
        self.assertContains(response,'승인확인')
        self.assertEqual(act_on_document(doc.pk,self.approver,'approve').status,'approved')
        self.assertEqual(act_on_document(doc.pk,self.finance,'place').shipment,'ordered')
        self.assertEqual(act_on_document(doc.pk,self.owner,'receive').shipment,'received')
        self.assertEqual(self.balances(),before)

    def test_common_stock_skip_and_self_routes_complete_and_cancel_without_leave_changes(self):
        self.rule()
        before=self.balances()
        skipped=self.doc(approval_mode='skip')
        self.assertEqual((skipped.status,skipped.reviewer_id),('approve',None))
        with self.assertRaises(PermissionDenied):act_on_document(skipped.pk,self.reviewer,'review')
        self.assertEqual(act_on_document(skipped.pk,self.approver,'approve').status,'approved')
        own=self.doc(approval_mode='self')
        self.assertEqual((own.status,own.reviewer_id,own.approver_id),('approved',None,self.owner.pk))
        self.assertEqual(act_on_document(own.pk,self.owner,'cancel_approval','오입력').status,'cancelled')
        with self.assertRaises(PermissionDenied):act_on_document(own.pk,self.owner,'cancel_approval','중복')
        self.assertEqual(self.balances(),before)

    def test_stock_form_and_preview_keep_approver_for_common_rules(self):
        self.rule(fixed_reviewer=self.reviewer,fixed_approver=self.approver)
        form=DocumentForm(dict(kind='stock',product='재고',quantity=2,approval_mode='base'),instance=Document(owner=self.owner),submit=True)
        self.assertTrue(form.is_valid(),form.errors)
        doc=save_document(form.save(commit=False),self.owner,submit=True)
        self.assertEqual(doc.approver_id,self.approver.pk)
        preview=route_preview('stock','과장',0,owner=self.owner)
        self.assertEqual(preview['path'],'기안 → 검토 → 승인 → 발주 → 입고')
        self.client.force_login(self.owner)
        data=self.client.get(reverse('preview_route'),{'kind':'stock','mode':'self'}).json()
        self.assertEqual(data['available_modes'],['base','skip','self'])
        self.assertTrue(data['final_approval_required'])

    def test_specific_type_wins_at_same_scope_but_person_common_beats_company_type(self):
        common=self.rule()
        specific=self.rule(kind='office',name='구매 규정')
        self.assertEqual(resolve_route('office','과장',200,owner=self.owner)['rule_id'],specific.pk)
        person=self.rule(name='개인 공통');person.authors.add(self.owner)
        self.assertEqual(resolve_route('office','과장',200,owner=self.owner)['rule_id'],person.pk)
        self.assertEqual(resolve_route('leave','과장',owner=self.other)['rule_id'],common.pk)
        self.assertEqual(resolve_route('stock','과장',owner=self.other)['rule_id'],common.pk)

    def test_common_rule_amount_bounds_apply_only_to_purchases_and_same_scope_duplicates_rejected(self):
        rule=self.rule(amount_over=100,amount_to=200)
        self.assertIsNone(resolve_route('office','과장',100,owner=self.owner)['rule_id'])
        self.assertEqual(resolve_route('office','과장',200,owner=self.owner)['rule_id'],rule.pk)
        self.assertIsNone(resolve_route('office','과장',201,owner=self.owner)['rule_id'])
        self.assertEqual(resolve_route('leave','과장',0,owner=self.owner)['rule_id'],rule.pk)
        form=ApprovalRuleForm(dict(name='공통 중복',kind='all',amount_over=200,amount_to=300,
            reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:],enabled=True))
        self.assertTrue(form.is_valid(),form.errors)
        with self.assertRaises(ValidationError):save_rule(self.finance,form)

    def test_old_stock_snapshot_remains_legacy_after_common_rule_added_or_deleted(self):
        doc=self.doc()
        doc.refresh_from_db();before=serializers.serialize('json',[doc])
        rule=self.rule();delete_rule(self.finance,rule.pk)
        doc.refresh_from_db()
        self.assertEqual(serializers.serialize('json',[doc]),before)
        self.assertFalse(doc.final_approval_required)
        self.assertEqual(act_on_document(doc.pk,self.reviewer,'review').status,'approved')
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.approver,'approve')

    def test_new_stock_assignees_with_accounting_role_receive_pending_notices(self):
        self.rule()
        doc=self.doc(reviewer=self.finance)
        self.assertTrue(visible_notices(self.finance).filter(document=doc,stage='검토대기').exists())
        doc=act_on_document(doc.pk,self.finance,'review')
        act_on_document(doc.pk,self.approver,'approve')
        self.assertTrue(visible_notices(self.finance).filter(document=doc,stage='승인완료').exists())

    def test_rule_delete_hides_and_disables_but_preserves_rules_documents_m2m_and_history(self):
        rule=self.rule();rule.authors.add(self.owner)
        doc=self.doc();doc.refresh_from_db();before=serializers.serialize('json',[doc]);balances=self.balances()
        self.client.force_login(self.finance)
        self.assertEqual(self.client.get(reverse('rule_delete',args=[rule.pk])).status_code,405)
        self.assertEqual(self.client.post(reverse('rule_delete',args=[rule.pk])).status_code,302)
        rule.refresh_from_db()
        self.assertFalse(rule.enabled);self.assertIsNotNone(rule.deleted_at)
        self.assertEqual(rule.deleted_by_id,self.finance.pk)
        self.assertEqual(list(rule.authors.all()),[self.owner])
        self.assertTrue(Audit.objects.filter(event='전결규정 삭제').exists())
        self.assertNotIn(rule,list(self.client.get(reverse('regulations')).context['rules']))
        self.assertEqual(self.client.get(reverse('rule_edit',args=[rule.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse('rule_delete',args=[rule.pk])).status_code,404)
        self.assertIsNone(resolve_route('stock','과장',owner=self.owner)['rule_id'])
        doc.refresh_from_db();self.assertEqual(serializers.serialize('json',[doc]),before)
        act_on_document(doc.pk,self.reviewer,'review');act_on_document(doc.pk,self.approver,'approve')
        self.assertEqual(self.balances(),balances)

    def test_rule_delete_enforces_role_csrf_and_stale_edit_cannot_resurrect(self):
        rule=self.rule()
        data=dict(name='이전 수정 창',kind='all',amount_over=0,reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:],enabled=True)
        stale=ApprovalRuleForm(data,instance=ApprovalRule.objects.get(pk=rule.pk))
        self.assertTrue(stale.is_valid(),stale.errors)
        with self.assertRaises(PermissionDenied):delete_rule(self.owner,rule.pk)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('rule_delete',args=[rule.pk])).status_code,403)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.finance)
        self.assertEqual(secure.post(reverse('rule_delete',args=[rule.pk])).status_code,403)
        delete_rule(self.finance,rule.pk)
        with self.assertRaises(ValidationError):save_rule(self.finance,stale)
        self.assertFalse(ApprovalRule.objects.get(pk=rule.pk).enabled)

    def test_owner_can_hide_rejected_documents_only_without_erasing_rejection_or_changing_balances(self):
        self.rule()
        for kind in ['leave','office','stock']:
            doc=self.doc(kind)
            act_on_document(doc.pk,self.reviewer,'reject','보완 요청')
            before=self.balances();self.client.force_login(self.owner)
            response=self.client.get(reverse('detail',args=[doc.pk]))
            self.assertContains(response,'기안 삭제')
            with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.other,'delete')
            self.assertEqual(self.client.post(reverse('action',args=[doc.pk]),{'action':'delete'}).status_code,302)
            doc.refresh_from_db();self.assertEqual(doc.status,'deleted')
            self.assertTrue(doc.audits.filter(event='반려',detail='보완 요청').exists())
            self.assertTrue(doc.audits.filter(event='기안 삭제').exists())
            self.assertEqual(self.client.get(reverse('detail',args=[doc.pk])).status_code,404)
            self.assertEqual(self.balances(),before)

    def test_rejected_delete_csrf_and_approved_document_protection_remain(self):
        self.rule();doc=self.doc();act_on_document(doc.pk,self.reviewer,'reject','보완')
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.owner)
        self.assertEqual(secure.post(reverse('action',args=[doc.pk]),{'action':'delete'}).status_code,403)
        doc=self.doc(approval_mode='self')
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.owner,'delete')


class CommonRuleMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_existing_kind_specific_grants_and_stock_snapshots(self):
        executor=MigrationExecutor(connection);before=[('workflow','0012_simplified_approval')]
        executor.migrate(before)
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        apps=executor.loader.project_state(before).apps
        User=apps.get_model('auth','User');u=User.objects.create(username='common-migration-only')
        apps.get_model('workflow','ApprovalRule').objects.create(name='원래 구매권한',kind='office',reviewer_ranks=['과장'],approver_ranks=['과장'],allow_self_approval=True,enabled=True)
        apps.get_model('workflow','Document').objects.create(owner_id=u.pk,kind='stock',status='review',route_snapshot={'legacy':True,'skip_review':False})
        names=['ApprovalRule','Document','AnnualBalance','AnnualPolicy','ManualLeaveUsage','CompanyLeaveCharge','Audit']
        snapshots={name:list(apps.get_model('workflow',name).objects.order_by('pk').values()) for name in names}
        MigrationExecutor(connection).migrate([('workflow','0013_common_rule_deletion')])
        from django.apps import apps as current
        for name,rows in snapshots.items():
            self.assertEqual(list(current.get_model('workflow',name).objects.order_by('pk').values(*(list(rows[0]) if rows else ['pk']))),rows,name)
        self.assertFalse(ApprovalRule.objects.exclude(deleted_at=None).exists())
