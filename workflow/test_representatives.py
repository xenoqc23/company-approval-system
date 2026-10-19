"""Role isolation, data preservation, ordinary signup, and relative birthday navigation."""
from datetime import date
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse
from .annual_grants import employees, sync_annual_grants
from .birthdays import birthday_rows, birthday_values, save_birthday
from .company_holidays import save_company_holiday
from .delegation import resolve_route, simplified_eligible
from .forms import ApprovalRuleForm, DocumentForm, SignupForm
from .manual_leave import register_manual_leave
from .models import AnnualBalance, ApprovalRule, Audit, Document, Profile
from .people import approval_people
from .representatives import assign_representative, remove_representative
from .services import act_on_document, save_document, visible_documents


class RepresentativeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .models import ApprovalFlowPolicy
        ApprovalFlowPolicy.objects.update_or_create(pk=1, defaults={'enabled':False})
        ApprovalRule.objects.update(enabled=False)
        for key,flags in [('admin',dict(manage_system=True)),('candidate',{}),('other',{}),
                          ('manager',dict(manage_system=True,manage_leave=True)),('worker',{})]:
            user=get_user_model().objects.create_user(key,first_name=key,password='role-tests-only')
            Profile.objects.create(user=user,department='개발팀',rank='과장',approved=True,
                hire_date=date(2020,6,20),birthday_month=10,birthday_day=19,**flags)
            AnnualBalance.objects.create(user=user,year=2026,total=Decimal('19.5'),used=Decimal('2.25'),
                total_manual=True,grant_initialized=True)
            setattr(cls,key,user)

    def fresh(self,user):
        return get_user_model().objects.select_related('profile').get(pk=user.pk)

    def designate(self,**kwargs):
        return assign_representative(self.admin,self.candidate,**kwargs)

    def test_regular_signup_fields_stay_and_reserved_choices_are_rejected(self):
        form=SignupForm()
        self.assertIn('department',form.fields);self.assertIn('rank',form.fields)
        self.assertNotIn('대표이사실',dict(form.fields['department'].choices))
        self.assertNotIn('대표',dict(form.fields['rank'].choices))
        data=dict(username='normal-new',first_name='새직원',password1='1234',password2='1234',
            department='품질팀',rank='주임',birthday_calendar='solar',birthday_month='4',birthday_day='15',
            representative_slot='1',manage_system='on')
        response=self.client.post(reverse('signup'),data)
        self.assertEqual(response.status_code,302)
        p=Profile.objects.get(user__username='normal-new')
        self.assertEqual((p.department,p.rank),('품질팀','주임'))
        self.assertFalse(p.is_representative);self.assertFalse(p.approved);self.assertFalse(p.manage_system)
        for field,value in [('department','대표이사실'),('rank','대표')]:
            form=SignupForm({**data,'username':'forged-new',field:value})
            self.assertFalse(form.is_valid());self.assertIn(field,form.errors)

    def test_only_admin_can_designate_not_other_managers_or_self(self):
        for actor in [self.manager,self.worker,self.candidate]:
            with self.assertRaises(PermissionDenied):assign_representative(actor,self.candidate)
        with self.assertRaises(ValidationError):assign_representative(self.admin,self.admin)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(reverse('staff'),dict(user=self.candidate.pk,intent='representative_set')).status_code,403)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post(reverse('staff'),dict(user=self.candidate.pk,intent='representative_set')).status_code,403)

    def test_designation_preserves_all_business_records_and_clears_privileges(self):
        doc=Document.objects.create(owner=self.candidate,status='approved',charged=1,allocations={'2026':'1'},route_snapshot={'name':'과거 경로'})
        self.candidate.profile.manage_leave=True;self.candidate.profile.save()
        balances=list(AnnualBalance.objects.values());before=Document.objects.filter(pk=doc.pk).values().get()
        password=self.candidate.password
        p=self.designate()
        self.assertEqual((p.department,p.rank,p.approved,p.department_confirmed),('대표이사실','대표',True,True))
        self.assertFalse(any(getattr(p,f) for f in ['manage_leave','manage_system','view_accounting','procure']))
        self.assertEqual(list(AnnualBalance.objects.values()),balances)
        self.assertEqual(Document.objects.filter(pk=doc.pk).values().get(),before)
        self.assertEqual(self.fresh(self.candidate).password,password)
        self.assertTrue(Audit.objects.filter(event='회사 대표 지정·설정',target=self.candidate).exists())

    def test_replacement_requires_explicit_current_identity_and_restores_assignment(self):
        self.designate()
        for kwargs in [{},{'replace':True},{'replace':True,'expected_id':self.other.pk}]:
            with self.assertRaises(ValidationError):assign_representative(self.admin,self.other,**kwargs)
        assign_representative(self.admin,self.other,replace=True,expected_id=self.candidate.pk)
        old=self.fresh(self.candidate).profile
        self.assertFalse(old.is_representative);self.assertEqual((old.department,old.rank),('개발팀','과장'))
        self.assertFalse(old.manage_system)
        self.assertEqual(Profile.objects.filter(representative_slot=1).get().user_id,self.other.pk)
        remove_representative(self.admin,self.other)
        self.assertFalse(Profile.objects.filter(representative_slot=1).exists())

    def test_pending_review_approval_receipt_and_fixed_rule_block_designation(self):
        for values in [dict(status='review',reviewer=self.candidate),dict(status='review',approver=self.candidate),
            dict(status='approve',approver=self.candidate),dict(status='approved',kind='office',recipient=self.candidate),
            dict(status='review',kind='stock',recipient=self.candidate)]:
            doc=Document.objects.create(owner=self.worker,**values)
            with self.assertRaises(ValidationError):self.designate()
            doc.delete()
        rule=ApprovalRule.objects.create(name='지정 담당자',kind='all',fixed_approver=self.candidate,enabled=True)
        with self.assertRaises(ValidationError):self.designate()
        rule.enabled=False;rule.save();self.designate()

    def test_representative_birthday_is_visible_but_admin_can_hide_or_edit(self):
        self.designate()
        ids=lambda:[r['employee'].pk for r in birthday_rows(2026,10,date(2026,10,19))]
        self.assertIn(self.candidate.pk,ids())
        self.designate(show_birthday=False,expected_id=self.candidate.pk)
        self.assertNotIn(self.candidate.pk,ids())
        self.designate(birthday=birthday_values(9,9,'lunar'),expected_id=self.candidate.pk)
        p=self.fresh(self.candidate).profile
        self.assertEqual((p.birthday_calendar,p.birthday_month,p.birthday_day),('lunar',9,9))
        with self.assertRaises(ValidationError):save_birthday(self.manager,self.candidate,birthday_values(1,1))

    def test_automatic_leave_common_leave_and_awards_exclude_representative(self):
        from .welfare import award_candidates
        self.candidate.profile.hire_date=date(2023,6,20);self.candidate.profile.save()
        self.assertIn(self.candidate.pk,[r['employee'].pk for r in award_candidates(2026,date(2026,10,19))])
        self.designate();before=list(AnnualBalance.objects.filter(user=self.candidate).values())
        self.assertFalse(employees().filter(pk=self.candidate.pk).exists())
        sync_annual_grants(date(2027,1,1))
        save_company_holiday(self.manager,dict(title='공용 휴가',day=date(2026,11,2),use_annual=True,description=''))
        self.assertEqual(list(AnnualBalance.objects.filter(user=self.candidate).values()),before)
        self.assertNotIn(self.candidate.pk,[r['employee'].pk for r in award_candidates(2026,date(2026,10,19))])
        with self.assertRaises(ValidationError):register_manual_leave(self.manager,self.candidate,
            dict(used_date=date(2026,11,3),leave_type='annual',reason='수기'),uuid4())

    def test_all_approval_and_recipient_selectors_exclude_representative(self):
        self.designate();rep=self.fresh(self.candidate)
        self.assertFalse(approval_people().filter(pk=rep.pk).exists())
        self.assertFalse(DocumentForm(instance=Document(owner=self.worker)).fields['recipient'].queryset.filter(pk=rep.pk).exists())
        form=ApprovalRuleForm()
        for field in ['authors','fixed_reviewer','fixed_approver']:
            self.assertFalse(form.fields[field].queryset.filter(pk=rep.pk).exists())
        self.assertFalse(simplified_eligible(rep))
        with self.assertRaises(ValidationError):resolve_route('leave',rep.profile.rank,owner=rep)
        with self.assertRaises(ValidationError):save_document(Document(owner=self.worker,kind='office',product='물품',
            recipient=self.candidate,reviewer=self.worker,approver=self.other),self.worker,submit=True)

    def test_readonly_denies_forged_posts_and_compose_but_allows_own_password_and_views(self):
        doc=Document.objects.create(owner=self.candidate,status='draft')
        self.designate();rep=self.fresh(self.candidate);self.client.force_login(rep)
        for name,args in [('compose',[]),('edit',[doc.pk]),('absence_new',[])]:
            self.assertEqual(self.client.get(reverse(name,args=args)).status_code,403)
        for name,args in [('action',[doc.pk]),('staff',[]),('balances',[]),('copy',[doc.pk])]:
            self.assertEqual(self.client.post(reverse(name,args=args),{'action':'delete'}).status_code,403)
        for name in ['dashboard','welfare','calendar','account','notices']:
            self.assertEqual(self.client.get(reverse(name)).status_code,200,name)
        home=self.client.get(reverse('dashboard'))
        self.assertContains(home,'회사 대표 · 조회 전용');self.assertNotContains(home,'나의 연차 현황');self.assertNotContains(home,'기안하기')
        self.assertNotContains(self.client.get(reverse('documents')),'새 기안 작성')
        self.assertNotContains(self.client.get(reverse('detail',args=[doc.pk])),'이어서 작성')
        response=self.client.post(reverse('account'),dict(old_password='role-tests-only',new_password1='4321',new_password2='4321'))
        self.assertEqual(response.status_code,302);self.assertTrue(self.fresh(rep).check_password('4321'))
        self.assertEqual(self.client.post(reverse('logout')).status_code,302)
        with self.assertRaises(PermissionDenied):save_document(Document(owner=rep),rep)
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,rep,'delete')

    def test_document_scope_is_separately_granted_and_never_includes_others_drafts_or_deleted(self):
        own=Document.objects.create(owner=self.candidate,status='approved')
        public=Document.objects.create(owner=self.other,status='review')
        Document.objects.create(owner=self.other,status='draft');Document.objects.create(owner=self.other,status='deleted')
        self.designate();rep=self.fresh(self.candidate)
        self.assertEqual(set(visible_documents(rep).values_list('pk',flat=True)),{own.pk})
        self.designate(view_documents=True,expected_id=rep.pk);rep=self.fresh(rep)
        self.assertEqual(set(visible_documents(rep).values_list('pk',flat=True)),{own.pk,public.pk})
        self.assertFalse(rep.profile.manage_system)

    def test_admin_staff_settings_render_and_normal_edit_cannot_bypass_role(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('staff')+'?department=개발팀'),'회사 대표 지정')
        self.client.post(reverse('staff'),dict(user=self.candidate.pk,intent='representative_set',name='회사대표',
            birthday_calendar='solar',birthday_month='10',birthday_day='19',show_birthday='on'))
        self.assertTrue(self.fresh(self.candidate).profile.is_representative)
        page=self.client.get(reverse('staff')+'?department=대표이사실')
        self.assertContains(page,'회사 대표 설정 저장');self.assertContains(page,'회사 대표 지정 해제')
        self.client.post(reverse('staff'),dict(user=self.candidate.pk,department='영업팀',rank='이사',approved='on',active='on',manage_system='on'))
        p=self.fresh(self.candidate).profile;self.assertTrue(p.is_representative);self.assertFalse(p.manage_system)
        self.client.force_login(self.manager)
        self.assertNotContains(self.client.get(reverse('staff')+'?department=대표이사실'),'회사 대표 설정 저장')

    def test_database_rejects_two_representatives_or_business_privileges(self):
        self.designate()
        for values in [dict(representative_slot=2),dict(representative_slot=1,department='대표이사실',rank='대표')]:
            with self.assertRaises(IntegrityError),transaction.atomic():Profile.objects.filter(user=self.other).update(**values)
        with self.assertRaises(IntegrityError),transaction.atomic():Profile.objects.filter(user=self.candidate).update(manage_system=True)

    def test_month_buttons_follow_selected_month_and_cross_years(self):
        self.client.force_login(self.worker)
        with patch('django.utils.timezone.localdate',return_value=date(2026,10,19)):
            for year,month,previous,next_ in [(2026,12,(2026,11),(2027,1)),(2027,1,(2026,12),(2027,2)),(2027,2,(2027,1),(2027,3))]:
                r=self.client.get(reverse('welfare'),dict(tab='birthdays',year=year,month=month))
                self.assertEqual((r.context['birthday_previous_year'],r.context['birthday_previous_month']),previous)
                self.assertEqual((r.context['birthday_next_year'],r.context['birthday_next_month']),next_)
                self.assertContains(r,'year=2026&month=10')
            self.assertIsNone(self.client.get(reverse('welfare'),dict(year=2000,month=1)).context['birthday_previous_year'])
            self.assertIsNone(self.client.get(reverse('welfare'),dict(year=2100,month=12)).context['birthday_next_year'])


class RepresentativeMigrationTests(TransactionTestCase):
    def test_schema_addition_keeps_every_business_value_and_does_not_designate_anyone(self):
        before=[('workflow','0015_employee_birthdays')];after=[('workflow','0016_representative_account')]
        executor=MigrationExecutor(connection);executor.migrate(before)
        self.addCleanup(lambda:MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        old=executor.loader.project_state(before).apps
        u=old.get_model('auth','User').objects.create(username='legacy-representative-test',password='unchanged-hash')
        old.get_model('workflow','Profile').objects.create(user_id=u.pk,department='개발팀',rank='과장',approved=True,
            hire_date=date(2005,6,20),birthday_month=9,birthday_day=9,birthday_calendar='lunar',manage_leave=True)
        old.get_model('workflow','AnnualBalance').objects.create(user_id=u.pk,year=2026,total=Decimal('25'),used=Decimal('4.25'),total_manual=True)
        old.get_model('workflow','Document').objects.create(owner_id=u.pk,status='approved',route_snapshot={'name':'보존'},allocations={'2026':'1'})
        names=['Profile','Document','AnnualBalance','AnnualPolicy','ManualLeaveUsage','CompanyLeaveCharge','ApprovalRule','Audit','Notice']
        snapshots={n:list(old.get_model('workflow',n).objects.order_by('pk').values()) for n in names}
        MigrationExecutor(connection).migrate(after)
        current=MigrationExecutor(connection).loader.project_state(after).apps
        for n,rows in snapshots.items():
            fields=list(rows[0]) if rows else ['pk']
            self.assertEqual(list(current.get_model('workflow',n).objects.order_by('pk').values(*fields)),rows,n)
        self.assertFalse(current.get_model('workflow','Profile').objects.filter(representative_slot=1).exists())
