"""Integration boundaries: original workflow alongside isolated new purchases."""
import unittest
from django.conf import settings
if not settings.INTEGRATED_PURCHASES:raise unittest.SkipTest('Integrated local preview only.')
from decimal import Decimal
from io import BytesIO
from uuid import uuid4
from django.test import TestCase,Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from workflow.models import Document,Notice,AnnualBalance,ApprovalRule,ApprovalFlowPolicy,Profile
from . import test_departments as department_tests
from .services import request_action,decide_report,amend_amount
from .models import PurchasePolicy,PurchaseNotice,PurchaseRequest
from .forms import IntegratedPolicyForm,PurchaseAssignmentsForm
from .integrated_rules import ScopedRuleForm
from .integration import list_requests

class IntegratedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        department_tests.DepartmentPurchaseTests.setUpTestData.__func__(cls)
        Profile.objects.filter(user__username='p_ceo').update(representative_can_approve=True)
    user=department_tests.DepartmentPurchaseTests.user
    as_user=department_tests.DepartmentPurchaseTests.as_user
    create=department_tests.DepartmentPurchaseTests.create
    confirmed=department_tests.DepartmentPurchaseTests.confirmed
    report=department_tests.DepartmentPurchaseTests.report
    final=department_tests.DepartmentPurchaseTests.final
    decisions=department_tests.DepartmentPurchaseTests.decisions

    def old(self,**kwargs):
        values=dict(owner=self.user('quality_manager'),kind='office',product='기존 모니터',number='DOC-LEGACY-1',status='approved',quantity=2,unit_price=Decimal('50000'),reason='과거 기록')
        values.update(kwargs);return Document.objects.create(**values)

    def test_original_home_and_purchase_compose_share_original_shell(self):
        self.as_user('quality');home=self.client.get('/')
        self.assertContains(home,'나의 연차 현황');self.assertContains(home,'생산 재고');self.assertContains(home,'integrated-role')
        response=self.client.get(reverse('purchasing:new'));self.assertContains(response,'id="workspace-navigation"');self.assertNotContains(response,'id="purchase-navigation"')
        self.assertRedirects(self.client.get('/compose/?kind=office'),reverse('purchasing:new'))
        self.assertNotContains(self.client.get('/compose/?kind=leave'),'data-kind="office"')

    def test_common_inbox_contains_new_purchase_with_correct_url(self):
        d=self.create('quality','review');self.as_user('quality_manager')
        r=self.client.get('/documents/?mode=pending');self.assertContains(r,d.product)
        self.assertContains(r,reverse('purchasing:detail',args=[d.pk]));self.assertEqual(r.context['document_count'],1)
        self.assertEqual(self.client.get('/notifications/status/').json()['waiting'],1)

    def test_original_document_and_new_purchase_ids_do_not_collide(self):
        old=self.old();d=self.create();self.as_user('quality_manager')
        r=self.client.get('/documents/');self.assertContains(r,'DOC-LEGACY-1');self.assertContains(r,d.product)
        self.assertContains(r,reverse('detail',args=[old.pk]));self.assertContains(r,reverse('purchasing:detail',args=[d.pk]))
        old.refresh_from_db();self.assertEqual((old.status,old.shipment),('approved',''))

    def test_original_purchase_post_cannot_bypass_new_route(self):
        self.as_user('quality');before=Document.objects.count()
        self.assertRedirects(self.client.post('/compose/',dict(kind='office',intent='submit')),reverse('purchasing:new'))
        self.assertEqual(Document.objects.count(),before)

    def test_finance_has_one_purchase_menu_and_no_duplicate_total_card(self):
        self.confirmed();self.as_user('finance');r=self.client.get(reverse('purchasing:reports'))
        self.assertContains(r,'요청할 품목');self.assertContains(r,'보낸 요청');self.assertContains(r,'보류')
        self.assertNotContains(r,'구매 모아보기');self.assertNotContains(r,'구매보류함');self.assertNotContains(r,'전체 요청')
        self.assertEqual(r.context['total'],1)

    def test_sent_report_does_not_stay_in_actionable_items_and_receipt_remains(self):
        d=self.confirmed();r=self.final([d],['allow']);self.as_user('finance')
        self.assertEqual(self.client.get(reverse('purchasing:reports')).context['total'],0)
        self.assertContains(self.client.get(reverse('purchasing:reports')+'?tab=sent'),r.title)
        request_action(d.pk,d.owner,'receive',quantity=6,receipt_key=uuid4())
        self.assertContains(self.client.get(reverse('purchasing:reports')+'?tab=sent'),'수령 완료')
        response=self.client.get(reverse('purchasing:report_detail',args=[r.pk]));self.assertContains(response,'수령 완료');self.assertNotContains(response,'6 / 10개')

    def test_hold_tab_is_scoped_and_followup_before_retry_is_preserved(self):
        d=self.confirmed();self.final([d],['hold']);self.as_user('finance')
        self.assertEqual(self.client.get(reverse('purchasing:reports')+'?tab=hold').context['total'],1)
        self.assertFalse(self.client.get(reverse('purchasing:reports')+'?tab=hold').context['can_batch'])
        request_action(d.pk,self.user('finance'),'prepare_hold','호환 확인 완료')
        self.assertEqual(self.client.get(reverse('purchasing:reports')).context['total'],1)
        self.as_user('quality');self.assertEqual(self.client.get(reverse('purchasing:reports')+'?tab=hold').status_code,403)

    def test_status_filters_have_no_duplicates_and_group_payment_aliases(self):
        self.as_user('quality_manager');response=self.client.get(reverse('purchasing:requests')+'?mode=mine')
        labels=[label for key,label in response.context['states']]
        self.assertEqual(len(labels),len(set(labels)));self.assertLessEqual(len(labels),7)
        self.assertNotContains(response,'담당 이사 최종승인 대기')

    def test_purchase_completion_is_only_representative_final_and_read_is_independent(self):
        d=self.confirmed();self.as_user('quality_manager')
        self.assertEqual(self.client.get('/notifications/status/').json()['completed_unread'],0)
        r=self.final([d],['allow']);self.assertEqual(self.client.get('/notifications/status/').json()['completed_unread'],1)
        self.client.post('/notices/');self.assertEqual(self.client.get('/notifications/status/').json()['completed_unread'],1)
        response=self.client.get('/documents/?mode=completed&unread=1');self.assertContains(response,d.product)
        self.client.get(reverse('purchasing:detail',args=[d.pk]));self.assertEqual(self.client.get('/notifications/status/').json()['completed_unread'],0)

    def test_two_notice_cursors_and_combined_notice_page(self):
        d=self.create();PurchaseNotice.objects.create(user=d.owner,request=d,text='구매요청 접수');old=self.old();Notice.objects.create(user=d.owner,document=old,text='기존 알림')
        self.as_user('quality_manager');r=self.client.get('/notifications/status/?after=0&after_purchase=0').json()
        self.assertEqual(len(r['events']),1);self.assertTrue(r['purchase_events']);self.assertTrue(all(isinstance(n['id'],str) and n['id'].startswith('purchase-') for n in r['purchase_events']))
        self.assertEqual(self.client.get('/notifications/status/?after=0&after_purchase=-4').status_code,200)
        self.assertEqual(self.client.get('/notifications/status/?after_purchase=x').status_code,400)
        page=self.client.get('/notices/');self.assertContains(page,'기존 알림');self.assertContains(page,reverse('purchasing:open_notice',args=[PurchaseNotice.objects.filter(user=d.owner).first().pk]))

    def test_old_and_new_similar_history_includes_received_without_private_data(self):
        self.old(product='통합 모니터',shipment='received');self.old(number='DOC-PRIVATE',product='통합 모니터 비밀',purchase_private=True)
        self.create(product='통합 모니터');self.as_user('quality')
        rows=self.client.get(reverse('purchasing:hints')+'?q=통합모니터').json()
        self.assertEqual(rows['count'],2);self.assertTrue(any('기존 문서' in r['status'] for r in rows['results']))
        self.assertFalse(any('owner' in r or 'unit_price' in r for r in rows['results']))

    def test_purchase_rules_cannot_change_staff_assignments_by_forged_post(self):
        p=PurchasePolicy.objects.get(pk=1);form=IntegratedPolicyForm(instance=p)
        data={name:form.initial.get(name,field.initial) for name,field in form.fields.items()}
        data.update(reason='경로만 변경',finance=[self.user('admin').pk],dev_director=self.user('prod_director').pk)
        bound=IntegratedPolicyForm(data,instance=p);self.assertTrue(bound.is_valid(),bound.errors);bound.save(self.user('admin'));p.refresh_from_db()
        self.assertEqual(p.dev_director,self.user('dev_director'));self.assertEqual(list(p.finance.all()),[self.user('finance')])

    def test_staff_page_owns_buying_roles_and_rules_are_separated(self):
        self.as_user('admin');r=self.client.get('/staff/');self.assertContains(r,'구매 업무 담당자·권한');self.assertContains(r,reverse('purchasing:assignments'))
        r=self.client.get('/regulations/');self.assertContains(r,'휴가원 결재 규정');self.assertContains(r,'구매요청 규정');self.assertContains(r,'생산 재고 결재 규정')
        self.assertNotContains(self.client.get(reverse('purchasing:regulations')),'name="finance"')
        self.as_user('finance');self.assertEqual(self.client.post(reverse('purchasing:assignments'),{}).status_code,403)

    def test_leave_threshold_change_cannot_change_purchase_threshold_or_stock_mode(self):
        p,_=ApprovalFlowPolicy.objects.update_or_create(pk=1,defaults=dict(enabled=True,leave_threshold=3,purchase_threshold=1000000))
        self.as_user('admin');self.client.post('/regulations/?tab=leave',dict(intent='threshold',leave_threshold='5'))
        p.refresh_from_db();self.assertEqual(p.leave_threshold,5);self.assertEqual(p.purchase_threshold,1000000);self.assertTrue(p.enabled)
        self.assertEqual(self.client.post('/regulations/?tab=stock',dict(intent='threshold',leave_threshold='10')).status_code,403)

    def test_scoped_rule_form_rejects_all_and_purchase_kinds(self):
        for kind in ['all','office','stock']:
            f=ScopedRuleForm(dict(kind=kind,name='범위 우회',enabled='on',reviewer_ranks=['과장'],approver_ranks=['팀장']),kind='leave')
            self.assertFalse(f.is_valid());self.assertIn('kind',f.errors)

    def test_readonly_ceo_cannot_decide_purchase_even_using_service(self):
        d=self.confirmed();r=self.report([d]);u=self.user('ceo');u.profile.representative_can_approve=False;u.profile.save()
        with self.assertRaises(PermissionDenied):decide_report(r.pk,u,self.decisions(r,['allow']),0,final=True)
        self.as_user('ceo');self.assertEqual(self.client.post(reverse('purchasing:report_detail',args=[r.pk]),{}).status_code,403)
        self.assertNotContains(self.client.get(reverse('purchasing:report_detail',args=[r.pk])),'data-final-decisions')

    def test_assignments_refuse_dropping_finance_with_active_documents(self):
        self.confirmed();p=PurchasePolicy.objects.get(pk=1);f=PurchaseAssignmentsForm()
        data={name:f.initial.get(name,field.initial) for name,field in f.fields.items()};data.update(reason='진행 중 권한 해제',finance=[self.user('admin').pk])
        f=PurchaseAssignmentsForm(data);self.assertTrue(f.is_valid(),f.errors)
        with self.assertRaises(ValidationError):f.save(self.user('admin'))
        self.assertTrue(p.finance.filter(pk=self.user('finance').pk).exists())

    def test_export_freezes_requested_amount_and_escapes_formula_text(self):
        d=self.confirmed();PurchaseRequest.objects.filter(pk=d.pk).update(product='=1+1');d.refresh_from_db();r=self.final([d],['allow'])
        self.as_user('finance');response=self.client.post(reverse('purchasing:report_export',args=[r.pk]));self.assertEqual(response.status_code,200)
        from openpyxl import load_workbook
        sheet=load_workbook(BytesIO(response.content)).active;self.assertEqual(sheet['E2'].value,'=1+1');self.assertEqual(sheet['E2'].data_type,'s');self.assertEqual(sheet['J2'].value,d.reason)
        self.as_user('quality');self.assertEqual(self.client.post(reverse('purchasing:report_export',args=[r.pk])).status_code,404)

    def test_integrated_mutations_keep_csrf_protection(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.user('admin'))
        for path in [reverse('purchasing:assignments'),reverse('purchasing:new'),'/regulations/?tab=leave']:
            self.assertEqual(c.post(path,{}).status_code,403)

    def test_cancelled_legacy_purchase_copy_opens_new_form_without_changing_source(self):
        old=self.old(status='cancelled');self.as_user('quality_manager')
        response=self.client.post(reverse('copy',args=[old.pk]));self.assertRedirects(response,reverse('purchasing:new')+'?source='+str(old.pk))
        response=self.client.get(response.url);self.assertEqual(response.context['form'].initial['product'],old.product)
        self.assertNotIn('vendor',response.context['form'].initial);old.refresh_from_db();self.assertEqual(old.status,'cancelled');self.assertEqual(Document.objects.count(),1)
        self.as_user('quality');self.assertEqual(self.client.get(reverse('purchasing:new')+'?source='+str(old.pk)).status_code,404)
