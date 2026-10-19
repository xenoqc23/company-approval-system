from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase,TransactionTestCase
from django.urls import reverse
from .models import ApprovalRule,ApprovalFlowPolicy,AnnualBalance,Document,Profile,RANKS
from .progressive import may_review_final
from .services import save_document,act_on_document
from .forms import ApprovalRuleForm


class ReviewerAuthorityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ApprovalFlowPolicy.objects.update_or_create(pk=1,defaults={'enabled':True})
        ApprovalRule.objects.update(enabled=False)
        for key,rank,flags in [('owner','주임',{}),('manager','부장',{}),('othermanager','팀장',{}),
            ('junior','대리',{}),('admin','이사',dict(manage_system=True))]:
            u=get_user_model().objects.create_user(key,first_name=key,password='authority-tests-only')
            Profile.objects.create(user=u,department='개발팀',rank=rank,approved=True,**flags)
            AnnualBalance.objects.create(user=u,year=2026,total=15,used=0,grant_initialized=True)
            setattr(cls,key,u)
        cls.rule=ApprovalRule.objects.create(name='부장 전결 권한',kind='all',enabled=True,allow_review_final=True,
            reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:],author_ranks=['부장'],author_departments=['생산팀'])
        cls.rule.authors.add(cls.manager) # The author's route restrictions deliberately do not match the employee.
        cls.rule.review_final_users.add(cls.manager)

    def document(self,reviewer=None,**kwargs):
        data=dict(owner=self.owner,reviewer=reviewer or self.manager,kind='leave',reason='휴가',
            start_date=date(2026,10,19),end_date=date(2026,10,19))
        data.update(kwargs);return save_document(Document(**data),data['owner'],submit=True)

    def test_checked_reviewer_finalizes_different_authors_without_author_membership(self):
        doc=self.document()
        self.assertEqual(doc.route_snapshot['name'],'기본 결재규정')
        self.assertTrue(may_review_final(doc,self.manager))
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse('detail',args=[doc.pk])),'>검토자 전결</button>')
        self.client.post(reverse('action',args=[doc.pk]),dict(action='review_final',reason='검토 후 승인'))
        doc.refresh_from_db();self.assertEqual(doc.status,'approved')
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).used,1)
        self.assertEqual(doc.route_snapshot['review_final_authority']['rule_id'],self.rule.pk)

    def test_grant_and_revoke_update_current_pending_document_and_not_just_new_submissions(self):
        self.rule.review_final_users.clear();doc=self.document()
        self.assertFalse(may_review_final(doc,self.manager))
        self.rule.review_final_users.add(self.manager)
        self.assertTrue(may_review_final(doc,self.manager))
        self.rule.review_final_users.clear()
        self.assertFalse(may_review_final(doc,self.manager))
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.manager,'review_final','오래된 화면')
        doc.refresh_from_db();self.assertEqual(doc.status,'review')
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).used,0)

    def test_unchecked_or_unassigned_manager_cannot_finalize(self):
        doc=self.document(reviewer=self.othermanager)
        self.assertFalse(may_review_final(doc,self.othermanager))
        self.assertFalse(may_review_final(doc,self.manager))
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.othermanager,'review_final','체크 안 됨')
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.manager,'review_final','배정 안 됨')

    def test_junior_admin_and_author_cannot_use_reviewer_final_even_if_membership_is_forged(self):
        self.rule.review_final_users.add(self.junior,self.admin)
        doc=self.document(reviewer=self.junior)
        self.assertFalse(may_review_final(doc,self.junior));self.assertFalse(may_review_final(doc,self.admin))
        doc.status='rejected';doc.save()
        doc=self.document(owner=self.manager,reviewer=self.manager)
        self.assertFalse(may_review_final(doc,self.manager))

    def test_disabled_deleted_wrong_kind_or_demoted_reviewer_loses_authority(self):
        doc=self.document()
        for field,value in [('enabled',False),('allow_review_final',False),('kind','office')]:
            old=getattr(self.rule,field);setattr(self.rule,field,value);self.rule.save()
            self.assertFalse(may_review_final(doc,self.manager));setattr(self.rule,field,old);self.rule.save()
        Profile.objects.filter(user=self.manager).update(rank='대리')
        self.assertFalse(may_review_final(doc,self.manager))

    def test_amount_boundary_and_granted_large_leave_still_allow_review_final(self):
        doc=self.document(end_date=date(2026,10,21))
        self.assertTrue(may_review_final(doc,self.manager))
        self.rule.kind='office';self.rule.amount_to=1000000;self.rule.save()
        for amount,allowed in [(1000000,True),(1000001,False)]:
            doc=save_document(Document(owner=self.owner,reviewer=self.manager,kind='office',product='비품',
                unit_price=amount,url='https://example.com/item'),self.owner,submit=True)
            self.assertEqual(may_review_final(doc,self.manager),allowed)

    def test_legacy_fixed_route_is_unchanged(self):
        ApprovalFlowPolicy.objects.filter(pk=1).update(enabled=False)
        doc=self.document(approver=self.manager)
        self.assertFalse(may_review_final(doc,self.manager))
        with self.assertRaises((PermissionDenied,ValidationError)):act_on_document(doc.pk,self.manager,'review_final','기존 경로')
        doc=act_on_document(doc.pk,self.manager,'review');self.assertEqual(doc.status,'approve')

    def test_form_selects_reviewers_separately_and_rejects_unqualified_or_empty_grants(self):
        form=ApprovalRuleForm()
        self.assertIn(self.manager.pk,form.fields['review_final_users'].queryset.values_list('pk',flat=True))
        self.assertNotIn(self.junior.pk,form.fields['review_final_users'].queryset.values_list('pk',flat=True))
        self.assertNotIn(self.admin.pk,form.fields['review_final_users'].queryset.values_list('pk',flat=True))
        data=dict(name='새 전결',kind='all',reviewer_ranks=['부장'],approver_ranks=['부장'],
            allow_review_final='on',review_final_users=[self.manager.pk],enabled='on',amount_over=0)
        self.assertTrue(ApprovalRuleForm(data).is_valid())
        for ids in [[],[self.junior.pk],[self.admin.pk]]:
            f=ApprovalRuleForm({**data,'review_final_users':ids});self.assertFalse(f.is_valid());self.assertIn('review_final_users',f.errors)


class ReviewerAuthorityMigrationTests(TransactionTestCase):
    def test_copies_only_selected_eligible_reviewers_without_changing_author_filters_or_business_data(self):
        before=[('workflow','0017_progressive_approval')];after=[('workflow','0018_reviewer_final_authority')]
        executor=MigrationExecutor(connection);executor.migrate(before)
        self.addCleanup(lambda:MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        old=executor.loader.project_state(before).apps
        User=old.get_model('auth','User');P=old.get_model('workflow','Profile');Rule=old.get_model('workflow','ApprovalRule')
        users=[]
        for key,rank in [('migration-staff','주임'),('migration-manager','부장'),('migration-unchecked','과장')]:
            u=User.objects.create(username=key,password='preserved-hash');P.objects.create(user_id=u.pk,department='개발팀',rank=rank,approved=True);users.append(u)
        rule=Rule.objects.create(name='선택값 이전',kind='all',enabled=True,allow_review_final=True,
            allow_self_approval=True,allow_skip_review=True,author_ranks=['부장'],author_departments=['생산팀'])
        rule.authors.add(users[0],users[1])
        old.get_model('workflow','AnnualBalance').objects.create(user_id=users[0].pk,year=2026,total=15,used=Decimal('2.75'))
        doc=old.get_model('workflow','Document').objects.create(owner_id=users[0].pk,reviewer_id=users[1].pk,status='review',
            route_snapshot={'progressive':True,'allow_review_final':False,'name':'기본 결재규정'})
        names=['Profile','ApprovalRule','Document','AnnualBalance','Audit','Notice','ManualLeaveUsage','CompanyLeaveCharge']
        snapshots={n:list(old.get_model('workflow',n).objects.order_by('pk').values()) for n in names}
        MigrationExecutor(connection).migrate(after)
        current=MigrationExecutor(connection).loader.project_state(after).apps
        for n,rows in snapshots.items():
            fields=list(rows[0]) if rows else ['pk']
            self.assertEqual(list(current.get_model('workflow',n).objects.order_by('pk').values(*fields)),rows,n)
        upgraded=current.get_model('workflow','ApprovalRule').objects.get(pk=rule.pk)
        self.assertEqual(list(upgraded.review_final_users.values_list('pk',flat=True)),[users[1].pk])
        self.assertEqual(set(upgraded.authors.values_list('pk',flat=True)),{u.pk for u in users[:2]})
