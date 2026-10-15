from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from .models import (Profile, Document, AnnualBalance, ApprovalRule, AnnualPolicy, WelfarePolicy,
                     CompanyLeaveCharge, Notice, RANKS)
from .services import save_document, act_on_document, edit_balance
from .delegation import resolve_route, route_preview
from .regulations import (save_annual_policy, save_rule, apply_recalculation, annual_policy,
                          recalc_rows, save_welfare, DEFAULT_BANDS)
from .annual_grants import entitlement, sync_annual_grants, set_hire_date
from .company_holidays import save_company_holiday, delete_company_holiday, reconcile_employee
from .forms import ApprovalRuleForm


class ConfigurableRegulationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        for name, rank, flags in [('owner', '대리', {}), ('reviewer', '과장', {}), ('approver', '부장', {}),
                ('director', '이사', {}), ('junior', '주임', {}), ('finance', '과장', {'manage_leave':True,'view_accounting':True}),
                ('admin', '이사', {'manage_system':True})]:
            user = User.objects.create_user(name, first_name=name, password='1234')
            Profile.objects.create(user=user, department='개발팀', rank=rank, approved=True,
                                   hire_date=date(2020,1,1) if name != 'admin' else None, **flags)
            setattr(cls, name, user)
            AnnualBalance.objects.create(user=user, year=2026, total=15, used=2, grant_initialized=True)

    def purchase(self, total=80000, **changes):
        fields=dict(owner=self.owner, kind='office', product='시험 구매', quantity=1, unit_price=total,
                    url='https://example.com/item', reviewer=self.reviewer, approver=self.approver)
        fields.update(changes)
        return save_document(Document(**fields), fields['owner'], submit=True)

    def leave(self, owner=None):
        owner=owner or self.owner
        return save_document(Document(owner=owner, kind='leave', start_date=date(2026,11,2), end_date=date(2026,11,2),
            reason='개인 일정', reviewer=self.reviewer, approver=self.approver), owner, submit=True)

    def snapshot(self):
        policy=annual_policy(2026)
        return {'year':2026,'policy':[policy.pk,policy.version], 'rows':{
            str(r['user'].pk):{'total':str(r['before']), 'manual':r['manual'],'hire':r['hire']} for r in recalc_rows(2026)}}

    def test_small_purchase_enters_approval_directly_and_notifies_only_approver(self):
        doc=self.purchase()
        self.assertFalse(doc.review_required)
        self.assertIsNone(doc.reviewer)
        self.assertIsNone(doc.reviewed_at)
        self.assertEqual(doc.status,'approve')
        self.assertEqual(list(Notice.objects.filter(document=doc).values_list('user_id','stage')),[(self.approver.pk,'승인대기')])
        self.assertEqual(act_on_document(doc.pk,self.approver,'approve').status,'approved')
        for action in ['review','cancel_review','delete']:
            with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.owner,action,'test')

    def test_threshold_is_inclusive_and_above_threshold_keeps_three_steps(self):
        self.assertFalse(self.purchase(100000).review_required)
        doc=self.purchase(Decimal('100000.01'))
        self.assertTrue(doc.review_required)
        self.assertEqual(doc.status,'review')
        act_on_document(doc.pk,self.reviewer,'review')
        self.assertEqual(act_on_document(doc.pk,self.approver,'approve').status,'approved')
        self.assertIn('미확정',route_preview('office','대리',Decimal('1000001'))['note'])

    def test_lower_rank_and_over_cap_and_admin_are_rejected(self):
        for person in [self.junior,self.director,self.admin]:
            with self.subTest(person=person.username),self.assertRaises(ValidationError):
                self.purchase(approver=person)
        with self.assertRaises(ValidationError):
            self.purchase(total=200000,reviewer=self.director,approver=self.approver)
        self.assertFalse(Document.objects.exists())

    def test_self_approval_requires_separate_action_and_is_allowed_within_rank_limits(self):
        doc=self.purchase(approver=self.owner)
        self.assertEqual(doc.status,'approve')
        self.assertEqual(act_on_document(doc.pk,self.owner,'approve').status,'approved')

    def test_skip_review_delete_is_owner_only_before_final_approval(self):
        doc=self.purchase()
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.approver,'delete')
        self.assertEqual(act_on_document(doc.pk,self.owner,'delete').status,'deleted')
        doc=self.purchase(200000)
        act_on_document(doc.pk,self.reviewer,'review')
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.owner,'delete')

    def test_general_manager_leave_skip_approval_charge_and_restore_exactly_once(self):
        doc=self.leave(self.approver)
        self.assertFalse(doc.review_required)
        self.assertEqual(AnnualBalance.objects.get(user=self.approver,year=2026).used,2)
        act_on_document(doc.pk,self.approver,'approve')
        self.assertEqual(AnnualBalance.objects.get(user=self.approver,year=2026).used,3)
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.approver,'approve')
        act_on_document(doc.pk,self.approver,'cancel_approval','일정 변경')
        self.assertEqual(AnnualBalance.objects.get(user=self.approver,year=2026).used,2)
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.approver,'cancel_approval','다시')

    def test_rule_changes_preserve_submitted_snapshot_and_drafts_resolve_at_submission(self):
        doc=self.purchase()
        draft=save_document(Document(owner=self.owner,kind='office',product='임시',quantity=1,unit_price=80000,
            url='https://example.com',reviewer=self.reviewer,approver=self.approver),self.owner)
        ApprovalRule.objects.filter(kind='office').update(enabled=False)
        doc.refresh_from_db()
        self.assertFalse(doc.review_required)
        self.assertEqual(act_on_document(doc.pk,self.approver,'approve').status,'approved')
        self.assertTrue(save_document(draft,self.owner,submit=True).review_required)
        # A legacy submitted document with no snapshot still keeps its review step.
        legacy=Document.objects.create(owner=self.owner,kind='office',status='review',reviewer=self.reviewer,approver=self.approver)
        self.assertTrue(legacy.review_required)
        self.assertEqual(act_on_document(legacy.pk,self.reviewer,'review').status,'approve')

    def test_rule_overlap_rejected_and_adjacent_intervals_allowed(self):
        data=dict(name='겹침',kind='office',amount_over=0,amount_to=90000,author_ranks=[],skip_review=True,
                  reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:],enabled=True)
        form=ApprovalRuleForm(data);self.assertTrue(form.is_valid(),form.errors)
        with self.assertRaises(ValidationError):save_rule(self.finance,form)
        data.update(name='새 구간',amount_over=100000,amount_to=1000000)
        form=ApprovalRuleForm(data);self.assertTrue(form.is_valid(),form.errors)
        save_rule(self.admin,form)
        self.assertEqual(resolve_route('office','대리',Decimal('100001'))['name'],'새 구간')
        self.assertEqual(resolve_route('office','대리',Decimal('100000'))['name'],'구매 10만원 이하')

    def test_simulator_has_no_document_balance_or_notification_side_effects(self):
        self.client.force_login(self.finance)
        response=self.client.get(reverse('preview_route'),{'kind':'office','total':'80000','rank':'대리'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['path'],'기안 → 승인')
        self.assertEqual(response.json()['approvers'],['대리','과장','팀장','부장'])
        self.assertEqual(Document.objects.count(),0)
        self.assertEqual(Notice.objects.count(),0)
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).used,2)
        self.client.force_login(self.owner)
        response=self.client.get(reverse('preview_route'),{'kind':'office','total':'80000','rank':'이사'})
        self.assertEqual(response.json()['author_rank'],'대리')
        for total in ['NaN','Infinity','-1','oops']:
            self.assertEqual(self.client.get(reverse('preview_route'),{'kind':'office','total':total}).status_code,400)

    def test_regular_users_cannot_manage_and_admin_only_has_delegation_editor(self):
        self.client.force_login(self.owner)
        for name in ['regulations','recalculate']:
            self.assertEqual(self.client.get(reverse(name)).status_code,403)
            self.assertEqual(self.client.post(reverse(name),{}).status_code,403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('regulations')).status_code,200)
        for tab in ['annual','benefits','awards']:
            self.assertEqual(self.client.get(reverse('regulations'),{'tab':tab}).status_code,403)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.finance)
        self.assertEqual(secure.post(reverse('regulations'),{}).status_code,403)

    def test_annual_policy_updates_table_and_calculation_not_existing_balance(self):
        bands=[list(row) for row in DEFAULT_BANDS];bands[4][1]=23  # 7 years is used below.
        policy=save_annual_policy(self.finance,2026,bands,'새 규정 안내')
        self.assertEqual(entitlement(date(2019,1,1),2026),23)
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).total,15)
        self.client.force_login(self.owner)
        response=self.client.get(reverse('welfare'),{'tab':'leave'})
        self.assertContains(response,'새 규정 안내')
        self.assertEqual(response.context['tenure_rows'][4],('7~9년 미만',23))
        self.assertEqual(entitlement(date(2019,1,1),2025),17)
        with self.assertRaises(ValidationError):save_annual_policy(self.finance,2025,bands,'old')
        with self.assertRaises(ValidationError):save_annual_policy(self.finance,2026,[[1,15]],'invalid')

    def test_next_year_rule_uses_next_year_only_and_no_repeat_rollover(self):
        save_annual_policy(self.finance,2027,[[0,12],[1,20]],'내년 기준')
        self.assertEqual(entitlement(date(2020,1,1),2027),20)
        self.assertEqual(entitlement(date(2020,1,1),2026),17)
        sync_annual_grants(date(2027,1,1))
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2027).total,20)
        edit_balance(self.finance,self.owner,2027,'total',Decimal('22'),'수동')
        sync_annual_grants(date(2027,2,1))
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2027).total,22)

    def test_recalculation_preserves_latest_used_and_requires_manual_confirmation(self):
        edit_balance(self.finance,self.owner,2026,'total',Decimal('19'),'수동 지급')
        snap=self.snapshot();ids={str(self.owner.pk)}
        with self.assertRaises(ValidationError):apply_recalculation(self.finance,snap,ids,set())
        AnnualBalance.objects.filter(user=self.owner,year=2026).update(used=Decimal('4.25'))
        self.assertEqual(apply_recalculation(self.finance,snap,ids,ids),1)
        balance=AnnualBalance.objects.get(user=self.owner,year=2026)
        self.assertEqual((balance.total,balance.used,balance.remaining),(17,Decimal('4.25'),Decimal('12.75')))
        self.assertFalse(balance.total_manual)
        with self.assertRaises(ValidationError):apply_recalculation(self.finance,snap,ids,ids)

    def test_stale_policy_total_hire_or_invalid_target_cannot_be_applied(self):
        ids={str(self.owner.pk)};snap=self.snapshot()
        edit_balance(self.finance,self.owner,2026,'total',Decimal('20'),'수동')
        with self.assertRaises(ValidationError):apply_recalculation(self.finance,snap,ids,ids)
        snap=self.snapshot()
        save_annual_policy(self.finance,2026,[[0,10],[1,22]],'새규정')
        with self.assertRaises(ValidationError):apply_recalculation(self.finance,snap,ids,ids)
        with self.assertRaises(ValidationError):apply_recalculation(self.finance,self.snapshot(),{'99999'},set())

    def test_recalculation_route_requires_signed_preview_and_renders_missing_hire(self):
        self.owner.profile.hire_date=None;self.owner.profile.save()
        self.client.force_login(self.finance)
        response=self.client.get(reverse('recalculate'))
        self.assertContains(response,'입사일 미등록·자동산정 대기')
        response=self.client.post(reverse('recalculate'),{'snapshot':'tampered','employees':[self.owner.pk]})
        self.assertContains(response,'미리보기가 만료되었거나')
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).total,15)

    def test_company_holidays_respect_hire_date_and_reconcile_once(self):
        self.owner.profile.hire_date=date(2026,7,1);self.owner.profile.save()
        early=save_company_holiday(self.finance,dict(title='입사 전',day=date(2026,5,1),use_annual=True,description=''))
        same=save_company_holiday(self.finance,dict(title='입사일',day=date(2026,7,1),use_annual=True,description=''))
        later=save_company_holiday(self.finance,dict(title='입사 후',day=date(2026,8,1),use_annual=True,description=''))
        self.assertFalse(early.charges.filter(employee=self.owner).exists())
        self.assertTrue(same.charges.filter(employee=self.owner,active=True).exists())
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).used,4)
        reconcile_employee(self.finance,self.owner)
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).used,4)
        set_hire_date(self.finance,self.owner,date(2026,7,15),2026)
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).used,3)
        delete_company_holiday(self.finance,later.pk)
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).used,2)
        self.assertFalse(same.charges.filter(employee=self.owner,active=True).exists())

    def test_rule_editor_preserves_existing_rank_cap(self):
        rule=ApprovalRule.objects.get(kind='office',enabled=True)
        self.client.force_login(self.finance)
        response=self.client.get(reverse('rule_edit',args=[rule.pk]))
        form=response.context['rule_form']
        self.assertEqual(form['approver_ranks'].value(),RANKS[1:-1])
        self.assertTrue(form['skip_review'].value())

    def test_legacy_route_can_reassign_without_changing_stage_or_current_rules(self):
        legacy=Document.objects.create(owner=self.owner,kind='office',status='review',reviewer=self.reviewer,
            approver=self.approver,route_snapshot={'name':'기존 결재 경로 (보존)','legacy':True,'skip_review':False})
        changed=act_on_document(legacy.pk,self.admin,'reassign','담당자 변경',self.owner)
        self.assertEqual(changed.status,'review')
        self.assertEqual(changed.reviewer,self.owner)
        self.assertTrue(changed.review_required)
        with self.assertRaises(ValidationError):act_on_document(legacy.pk,self.admin,'reassign','직급 위반',self.junior)

    def test_invalid_quantity_form_shows_error_instead_of_server_failure(self):
        self.client.force_login(self.owner)
        response=self.client.post(reverse('compose'),{'kind':'office','quantity':'not-a-number','unit_price':'10',
            'product':'잘못된 수량','url':'https://example.com','intent':'submit','approver':self.approver.pk})
        self.assertEqual(response.status_code,200)
        self.assertFalse(Document.objects.exists())

    def test_missing_hire_preserves_manual_total_and_skips_common_auto_charge(self):
        self.owner.profile.hire_date=None;self.owner.profile.save()
        holiday=save_company_holiday(self.finance,dict(title='공용',day=date(2026,10,1),use_annual=True,description=''))
        sync_annual_grants(date(2026,10,15))
        self.assertFalse(holiday.charges.filter(employee=self.owner).exists())
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).total,15)
        set_hire_date(self.finance,self.owner,date(2026,9,1),2026)
        self.assertEqual(AnnualBalance.objects.get(user=self.owner,year=2026).used,3)

    def test_editable_benefits_and_awards_are_used_in_employee_views(self):
        save_welfare(self.finance,'benefits',[['결혼','본인',3000000,'축하']])
        save_welfare(self.finance,'awards',[[6,'금 7돈']])
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('welfare'),{'tab':'benefits'}),'3,000,000원')
        self.assertContains(self.client.get(reverse('welfare'),{'tab':'awards','year':'2026'}),'금 7돈')
        with self.assertRaises(PermissionDenied):save_welfare(self.owner,'benefits',[])
        self.client.force_login(self.finance)
        for tab in ['annual','benefits','awards']:
            self.assertEqual(self.client.get(reverse('regulations'),{'tab':tab}).status_code,200)
