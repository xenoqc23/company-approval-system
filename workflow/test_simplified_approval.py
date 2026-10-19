from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from .calendars import month_grid
from .delegation import resolve_route
from .forms import ApprovalRuleForm, DocumentForm
from .manual_leave import register_manual_leave
from .models import AnnualBalance, ApprovalRule, Audit, Document, Notice, Profile, RANKS
from .regulations import save_rule
from .services import act_on_document, save_document
from uuid import uuid4


class SimplifiedApprovalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .models import ApprovalFlowPolicy
        ApprovalFlowPolicy.objects.update_or_create(pk=1, defaults={'enabled':False})
        ApprovalRule.objects.update(enabled=False)
        for name, rank, dept in [('owner','과장','개발팀'), ('junior','대리','개발팀'),
                ('reviewer','팀장','개발팀'), ('approver','이사','전략기획팀'),
                ('other','과장','품질팀'), ('finance','과장','인사팀'), ('admin','이사','전략기획팀')]:
            user = get_user_model().objects.create_user(name, first_name=name, password='test-password-only')
            Profile.objects.create(user=user, rank=rank, department=dept, approved=True,
                hire_date=date(2020,1,1), manage_leave=name=='finance', manage_system=name=='admin')
            AnnualBalance.objects.create(user=user, year=2026, total=19, used=Decimal('2.25'), grant_initialized=True)
            setattr(cls,name,user)

    def rule(self, **kwargs):
        values=dict(name='간소결재 허용', kind='leave', author_ranks=[], reviewer_ranks=RANKS[1:],
            approver_ranks=RANKS[1:], allow_skip_review=True, allow_self_approval=True, enabled=True)
        values.update(kwargs)
        return ApprovalRule.objects.create(**values)

    def document(self, **kwargs):
        values=dict(owner=self.owner, approval_mode='self', kind='leave', reason='시험 휴가',
            start_date=date(2026,11,2), end_date=date(2026,11,2))
        values.update(kwargs)
        return Document(**values)

    def used(self, user=None):
        return AnnualBalance.objects.get(user=user or self.owner,year=2026).used

    def test_self_completion_charges_once_notifies_completion_and_cancel_restores_once(self):
        rule=self.rule()
        doc=save_document(self.document(),self.owner,submit=True)
        self.assertEqual((doc.status,doc.reviewer_id,doc.approver_id),('approved',None,self.owner.pk))
        self.assertEqual(self.used(),Decimal('3.25'))
        self.assertTrue(doc.route_snapshot['self_complete'])
        self.assertEqual(doc.route_snapshot['rule_id'],rule.pk)
        self.assertEqual(doc.approved_at is not None,True)
        self.assertTrue(Audit.objects.filter(document=doc,event='본인 전결',actor=self.owner).exists())
        self.assertEqual(set(Notice.objects.filter(document=doc).values_list('stage',flat=True)),{'승인완료'})
        self.assertTrue(Notice.objects.filter(document=doc,user=self.finance).exists())
        for action in ['approve','review']:
            with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.owner,action)
        act_on_document(doc.pk,self.owner,'cancel_approval','일정 변경')
        self.assertEqual(self.used(),Decimal('2.25'))
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.owner,'cancel_approval','중복')
        self.assertEqual(self.used(),Decimal('2.25'))

    def test_junior_admin_inactive_unapproved_and_unconfirmed_cannot_use_either_option(self):
        self.rule()
        for user in [self.junior,self.admin]:
            for mode in ['skip','self']:
                with self.subTest(user=user.username,mode=mode), self.assertRaises(ValidationError):
                    save_document(self.document(owner=user,approval_mode=mode),user,submit=True)
        for field in ['approved','department_confirmed']:
            Profile.objects.filter(user=self.owner).update(**{field:False})
            with self.assertRaises(ValidationError):save_document(self.document(),self.owner,submit=True)
            Profile.objects.filter(user=self.owner).update(**{field:True})
        self.owner.is_active=False
        with self.assertRaises(ValidationError):save_document(self.document(),self.owner,submit=True)
        self.assertFalse(Document.objects.exists())

    def test_direct_post_and_service_cannot_bypass_permission_or_spoof_author(self):
        rule=self.rule(author_ranks=['과장'],author_departments=['개발팀'])
        rule.authors.add(self.owner)
        self.client.force_login(self.junior)
        response=self.client.get(reverse('compose'),{'kind':'leave'})
        self.assertNotContains(response,'id="approval-mode-picker"')
        payload=dict(kind='leave',approval_mode='self',start_date='2026-11-02',end_date='2026-11-02',leave_type='annual',reason='시험',intent='submit')
        self.assertEqual(self.client.post(reverse('compose'),payload).status_code,200)
        self.assertFalse(Document.objects.exists())
        response=self.client.get(reverse('preview_route'),{'kind':'leave','mode':'self','rank':'과장','author':self.owner.pk})
        self.assertEqual(response.status_code,400)
        with self.assertRaises(ValidationError):save_document(self.document(owner=self.other),self.other,submit=True)

    def test_skip_permission_does_not_grant_self_and_keeps_separate_approval(self):
        self.rule(allow_self_approval=False)
        with self.assertRaises(ValidationError):save_document(self.document(),self.owner,submit=True)
        doc=save_document(self.document(approval_mode='skip',approver=self.approver),self.owner,submit=True)
        self.assertEqual((doc.status,doc.reviewer_id),('approve',None))
        self.assertEqual(self.used(),Decimal('2.25'))
        act_on_document(doc.pk,self.approver,'approve')
        self.assertEqual(self.used(),Decimal('3.25'))

    def test_base_route_and_same_person_still_require_both_actions(self):
        self.rule()
        doc=save_document(self.document(approval_mode='base',reviewer=self.owner,approver=self.owner),self.owner,submit=True)
        self.assertEqual(doc.status,'review')
        act_on_document(doc.pk,self.owner,'review')
        self.assertEqual(self.used(),Decimal('2.25'))
        act_on_document(doc.pk,self.owner,'approve')
        self.assertEqual(self.used(),Decimal('3.25'))

    def test_employee_department_rank_company_precedence_and_same_priority_overlap_rejected(self):
        base=self.rule(name='회사 공통',allow_self_approval=False)
        rank=self.rule(name='과장 규정',author_ranks=['과장'],allow_self_approval=False)
        dept=self.rule(name='개발팀 규정',author_departments=['개발팀'])
        person=self.rule(name='직원 예외',allow_self_approval=False)
        person.authors.add(self.owner)
        self.assertEqual(resolve_route('leave','과장',owner=self.owner)['rule_id'],person.pk)
        person.enabled=False;person.save()
        self.assertEqual(resolve_route('leave','과장',owner=self.owner)['rule_id'],dept.pk)
        dept.enabled=False;dept.save()
        self.assertEqual(resolve_route('leave','과장',owner=self.owner)['rule_id'],rank.pk)
        rank.enabled=False;rank.save()
        self.assertEqual(resolve_route('leave','과장',owner=self.owner)['rule_id'],base.pk)
        form=ApprovalRuleForm(dict(name='중복',kind='leave',amount_over=0,reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:],enabled=True))
        self.assertTrue(form.is_valid(),form.errors)
        with self.assertRaises(ValidationError):save_rule(self.finance,form)

    def test_saved_rule_m2m_and_fixed_assignments_are_enforced_by_forms_and_service(self):
        data=dict(name='직원 지정',kind='leave',amount_over=0,author_ranks=['과장'],
            authors=[self.owner.pk],author_departments=['개발팀'],reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:],
            fixed_reviewer=self.other.pk,approver_is_author=True,allow_skip_review=True,enabled=True)
        form=ApprovalRuleForm(data)
        self.assertTrue(form.is_valid(),form.errors)
        rule=save_rule(self.finance,form)
        self.assertEqual(list(rule.authors.all()),[self.owner])
        form=DocumentForm(dict(kind='leave',start_date='2026-11-02',end_date='2026-11-02',leave_type='annual',reason='시험',approval_mode='base'),instance=Document(owner=self.owner),submit=True)
        self.assertTrue(form.is_valid(),form.errors)
        doc=save_document(form.save(commit=False),self.owner,submit=True)
        self.assertEqual((doc.reviewer_id,doc.approver_id),(self.other.pk,self.owner.pk))
        self.assertEqual(doc.status,'review')
        act_on_document(doc.pk,self.other,'review')
        self.assertEqual(self.used(),Decimal('2.25'))
        act_on_document(doc.pk,self.owner,'approve')
        self.assertEqual(self.used(),Decimal('3.25'))

    def test_draft_does_not_complete_and_latest_permissions_are_checked_at_submission(self):
        rule=self.rule()
        draft=save_document(self.document(),self.owner)
        self.assertEqual(draft.status,'draft')
        self.assertEqual(self.used(),Decimal('2.25'))
        rule.allow_self_approval=False;rule.save()
        with self.assertRaises(ValidationError):save_document(draft,self.owner,submit=True)
        draft.refresh_from_db()
        self.assertEqual(draft.status,'draft')
        Profile.objects.filter(user=self.owner).update(rank='대리')
        rule.allow_self_approval=True;rule.save()
        with self.assertRaises(ValidationError):save_document(draft,self.owner,submit=True)

    def test_new_rules_and_revoked_permissions_do_not_rewrite_submitted_documents(self):
        rule=self.rule()
        doc=save_document(self.document(approval_mode='skip',approver=self.approver),self.owner,submit=True)
        doc.refresh_from_db()
        before=serializers.serialize('json',[doc])
        rule.allow_skip_review=False;rule.enabled=False;rule.save()
        doc.refresh_from_db()
        self.assertEqual(serializers.serialize('json',[doc]),before)
        self.assertEqual(act_on_document(doc.pk,self.approver,'approve').status,'approved')

    def test_document_kind_amount_and_rank_limits_apply_to_self_completion(self):
        self.rule(kind='office',amount_over=100,amount_to=1000)
        for price in [100,1001]:
            with self.assertRaises(ValidationError):save_document(self.document(kind='office',product='품목',quantity=1,unit_price=price,url='https://example.com'),self.owner,submit=True)
        with self.assertRaises(ValidationError):save_document(self.document(),self.owner,submit=True)
        with self.assertRaises(ValidationError):save_document(self.document(kind='stock',product='재고'),self.owner,submit=True)
        doc=save_document(self.document(kind='office',product='품목',quantity=1,unit_price=1000,url='https://example.com',recipient=self.owner),self.owner,submit=True)
        self.assertEqual((doc.status,doc.approver_id,doc.shipment),('approved',self.owner.pk,''))
        self.assertEqual(self.used(),Decimal('2.25'))
        self.finance.profile.procure=True;self.finance.profile.save()
        act_on_document(doc.pk,self.finance,'place')
        self.assertEqual(act_on_document(doc.pk,self.owner,'receive').shipment,'received')

    def test_manual_overlap_or_invalid_leave_rolls_back_entire_self_completion(self):
        self.rule()
        register_manual_leave(self.finance,self.owner,dict(used_date=date(2026,11,2),leave_type='annual',reason='직접 등록'),uuid4())
        before=(self.used(),Audit.objects.count(),Document.objects.count(),Notice.objects.count())
        with self.assertRaises(ValidationError):save_document(self.document(),self.owner,submit=True)
        self.assertEqual((self.used(),Audit.objects.count(),Document.objects.count(),Notice.objects.count()),before)
        with self.assertRaises(ValidationError):save_document(self.document(start_date=date(2026,11,7),end_date=date(2026,11,7)),self.owner,submit=True)
        self.assertEqual(self.used(),before[0])

    def test_manager_pages_preview_and_csrf_with_no_preview_side_effects(self):
        self.rule(author_departments=['개발팀'])
        self.client.force_login(self.finance)
        self.assertContains(self.client.get(reverse('regulations')),'과장급 이상에게 본인 전결 선택 허용')
        counts=(Document.objects.count(),Audit.objects.count(),Notice.objects.count(),self.used())
        response=self.client.get(reverse('preview_route'),dict(kind='leave',author=self.owner.pk,mode='self'))
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['self_complete'])
        self.assertEqual(response.json()['approver_ids'],[self.owner.pk])
        self.assertEqual((Document.objects.count(),Audit.objects.count(),Notice.objects.count(),self.used()),counts)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.owner)
        self.assertEqual(secure.post(reverse('compose'),{'approval_mode':'self','intent':'submit'}).status_code,403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('regulations'),{}).status_code,403)


class SimplifiedApprovalMigrationTests(TransactionTestCase):
    def test_additive_upgrade_preserves_all_existing_business_rows_and_rules(self):
        executor=MigrationExecutor(connection)
        before=[('workflow','0011_hire_year_monthly')]
        executor.migrate(before)
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        apps=executor.loader.project_state(before).apps
        User=apps.get_model('auth','User');u=User.objects.create(username='migration-only',password='preserved-hash')
        apps.get_model('workflow','Profile').objects.create(user_id=u.pk,department='개발팀',rank='과장',approved=True)
        apps.get_model('workflow','AnnualBalance').objects.create(user_id=u.pk,year=2026,total=23,used=Decimal('4.25'),total_manual=True,grant_initialized=True)
        apps.get_model('workflow','ManualLeaveUsage').objects.create(employee_id=u.pk,created_by_id=u.pk,used_date=date(2026,10,16),leave_type='annual',amount=1,reason='기존 사용내역')
        for status in ['draft','review','approve','approved','cancelled','rejected']:
            apps.get_model('workflow','Document').objects.create(owner_id=u.pk,reviewer_id=u.pk,approver_id=u.pk,status=status,route_snapshot={'name':'기존 규정','skip_review':False,'legacy':True},reason='기존 문서')
        models=['Profile','AnnualBalance','ManualLeaveUsage','Document','ApprovalRule','AnnualPolicy','Audit']
        snapshots={name:list(apps.get_model('workflow',name).objects.order_by('pk').values()) for name in models}
        MigrationExecutor(connection).migrate([('workflow','0012_simplified_approval')])
        from django.apps import apps as current
        for name,rows in snapshots.items():
            fields=list(rows[0]) if rows else ['pk']
            self.assertEqual(list(current.get_model('workflow',name).objects.order_by('pk').values(*fields)),rows,name)
        self.assertFalse(ApprovalRule.objects.filter(allow_skip_review=True).exists())
        self.assertFalse(ApprovalRule.objects.filter(allow_self_approval=True).exists())
        self.assertEqual(set(Document.objects.values_list('approval_mode',flat=True)),{'base'})
        self.assertEqual(get_user_model().objects.get(pk=u.pk).password,'preserved-hash')
