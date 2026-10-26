"""Shared compose UI and configurable purchase-confirmation authorities."""
import unittest
from uuid import uuid4
from html.parser import HTMLParser
from django.conf import settings
if not settings.INTEGRATED_PURCHASES:raise unittest.SkipTest('Integrated purchases only.')
from django.test import TestCase,override_settings
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from workflow.models import Document,Profile
from . import test_integrated as fixtures
from .models import PurchasePolicy,PurchaseRequest,PurchasePermission
from .forms import PurchaseAssignmentsForm
from .services import request_action
from .access import is_confirmer


class IDs(HTMLParser):
    def __init__(self):super().__init__();self.ids=[]
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if values.get('id'):self.ids.append(values['id'])


class ComposeIntegrationTests(TestCase):
    setUpTestData=classmethod(fixtures.IntegratedTests.setUpTestData.__func__)
    user=fixtures.IntegratedTests.user
    as_user=fixtures.IntegratedTests.as_user
    create=fixtures.IntegratedTests.create

    def purchase_data(self,**changes):
        data={'kind':'office','intent':'submit','purchase-key':str(uuid4()),'purchase-product':'통합 화면 검증 품목',
            'purchase-vendor':'검증 구매처','purchase-quantity':'2','purchase-unit_price':'1,250',
            'purchase-url':'https://example.com/product','purchase-reason':'업무용 장비',
            'purchase-request_method':'review','purchase-reviewer':self.user('quality_manager').pk,
            'purchase-reviewer_department':'품질팀'}
        data.update(changes);return data

    def assignment_data(self,**changes):
        p=PurchasePolicy.objects.get(pk=1)
        data=dict(dev_director=p.dev_director_id,production_director=p.production_director_id,
            finance=list(p.finance.values_list('pk',flat=True)),representative=p.representative_id,
            revision=p.version,reason='담당자 변경 검증')
        data.update(changes);return data

    def test_three_kinds_share_one_page_unique_ids_and_independent_forms(self):
        self.as_user('quality')
        for kind in ['leave','office','stock']:
            r=self.client.get('/compose/',{'kind':kind});self.assertEqual(r.status_code,200)
            self.assertEqual(r.context['compose_kind'],kind)
            self.assertContains(r,'data-kind="office"');self.assertContains(r,'data-kind="leave"');self.assertContains(r,'data-kind="stock"')
            self.assertContains(r,'name="purchase-product"');self.assertContains(r,'data-person-field="id_purchase-reviewer"')
            self.assertContains(r,'name="kind"');self.assertContains(r,'name="reason"')
            parser=IDs();parser.feed(r.content.decode());self.assertEqual(len(parser.ids),len(set(parser.ids)))
        self.assertRedirects(self.client.get(reverse('purchasing:new')),'/compose/?kind=office')

    def test_purchase_submission_uses_purchase_service_and_no_legacy_record(self):
        self.as_user('quality');before=Document.objects.count()
        data=self.purchase_data();data['purchase-approver']=self.user('prod_director').pk
        r=self.client.post('/compose/',data)
        d=PurchaseRequest.objects.get(request_key=data['purchase-key'])
        self.assertRedirects(r,reverse('purchasing:detail',args=[d.pk]));self.assertEqual(d.status,'review')
        self.assertIsNone(d.approver_id);self.assertEqual(d.reviewer,self.user('quality_manager'));self.assertEqual(d.total,2500)
        self.assertEqual(Document.objects.count(),before)

    def test_invalid_purchase_keeps_kind_and_values_and_requires_link(self):
        self.as_user('quality');data=self.purchase_data(**{'purchase-url':''})
        r=self.client.post('/compose/?kind=office',data)
        self.assertEqual(r.status_code,200);self.assertEqual(r.context['compose_kind'],'office')
        self.assertIn('url',r.context['purchase_form'].errors)
        self.assertContains(r,'value="통합 화면 검증 품목"');self.assertFalse(PurchaseRequest.objects.exists())

    def test_purchase_draft_can_be_opened_and_edited_in_shared_layout(self):
        self.as_user('quality');data=self.purchase_data(intent='draft',**{'purchase-url':''})
        self.client.post('/compose/',data);d=PurchaseRequest.objects.get(request_key=data['purchase-key'])
        self.assertEqual(d.status,'draft')
        url=reverse('purchasing:edit',args=[d.pk]);r=self.client.get(url)
        self.assertTrue(r.context['kind_locked']);self.assertEqual(r.context['purchase_form'].instance,d)
        data['purchase-reason']='임시저장 내용 수정';self.assertEqual(self.client.post(url,data).status_code,302)
        d.refresh_from_db();self.assertEqual(d.reason,'임시저장 내용 수정');self.assertEqual(PurchaseRequest.objects.count(),1)

    def test_unprefixed_legacy_post_does_not_bypass_purchase_validation(self):
        self.as_user('quality')
        self.assertRedirects(self.client.post('/compose/',dict(kind='office',intent='submit')),'/compose/?kind=office')
        self.assertFalse(PurchaseRequest.objects.exists());self.assertFalse(Document.objects.exists())

    def test_manager_can_assign_active_approved_staff_and_preserve_existing_request(self):
        old=self.create();old_checker=old.purchase_checker_id
        self.as_user('admin')
        data=self.assignment_data(dev_director=self.user('quality').pk,production_director=self.user('dev').pk)
        form=PurchaseAssignmentsForm(data);self.assertTrue(form.is_valid(),form.errors)
        r=self.client.post(reverse('purchasing:assignments'),data)
        self.assertRedirects(r,'/staff/#purchase-assignments')
        p=PurchasePolicy.objects.get(pk=1)
        self.assertEqual(p.dev_director,self.user('quality'));self.assertEqual(p.production_director,self.user('dev'))
        self.assertTrue(is_confirmer(self.user('quality')));self.assertTrue(is_confirmer(self.user('dev')))
        old.refresh_from_db();self.assertEqual(old.purchase_checker_id,old_checker)
        new=self.create();self.assertEqual(new.purchase_checker,self.user('dev'))
        new=request_action(new.pk,self.user('dev'),'confirm_items');self.assertIsNotNone(new.confirmed_at)

    def test_same_checker_or_ineligible_account_is_rejected_without_grant(self):
        data=self.assignment_data(dev_director=self.user('quality').pk,production_director=self.user('quality').pk)
        self.assertFalse(PurchaseAssignmentsForm(data).is_valid())
        for changes in [dict(is_active=False),dict(approved=False)]:
            self.user('quality').__class__.objects.filter(pk=self.user('quality').pk).update(is_active=True)
            Profile.objects.filter(user=self.user('quality')).update(approved=True)
            if 'is_active' in changes:self.user('quality').__class__.objects.filter(pk=self.user('quality').pk).update(**changes)
            else:Profile.objects.filter(user=self.user('quality')).update(**changes)
            data=self.assignment_data(dev_director=self.user('quality').pk)
            self.assertFalse(PurchaseAssignmentsForm(data).is_valid())
        self.assertFalse(PurchasePermission.objects.filter(user=self.user('quality')).exists())
        self.as_user('quality_manager');self.assertEqual(self.client.post(reverse('purchasing:assignments'),self.assignment_data()).status_code,403)

    def test_self_request_has_another_named_checker_after_config_change(self):
        form=PurchaseAssignmentsForm(self.assignment_data(dev_director=self.user('dev').pk,production_director=self.user('quality').pk))
        self.assertTrue(form.is_valid(),form.errors);form.save(self.user('admin'))
        d=self.create('dev','review')
        self.assertEqual(d.purchase_checker,self.user('quality'));self.assertNotEqual(d.purchase_checker,d.owner)
