"""Production routing and CEO completion lists, including old saved routes."""
import unittest
from uuid import uuid4
from django.conf import settings
if not settings.INTEGRATED_PURCHASES: raise unittest.SkipTest('Integrated purchases only.')
from django.test import TestCase
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from . import test_integrated as fixtures
from .models import PurchasePolicy, PurchaseRequest, PurchaseEvent
from .services import request_action, submit_report
from .payments import process_payment
from .access import finance_requests


class ProductionPurchaseTests(TestCase):
    setUpTestData=classmethod(fixtures.IntegratedTests.setUpTestData.__func__)
    user=fixtures.IntegratedTests.user
    as_user=fixtures.IntegratedTests.as_user
    create=fixtures.IntegratedTests.create
    confirmed=fixtures.IntegratedTests.confirmed

    def report(self, docs):
        return submit_report(self.user('finance'),[d.pk for d in docs],'운영 결제 요청','업무용',uuid4())

    def process(self,r,action='paid'):
        r.refresh_from_db()
        return process_payment(r.pk,self.user('finance'),list(r.items.values_list('pk',flat=True)),action,'운영 확인',r.revision,apply=True)

    def ids(self, query=''):
        return [r.pk for r in self.client.get(reverse('purchasing:reports')+query).context['reports']]

    def test_production_purchase_login_uses_shared_login(self):
        self.assertRedirects(self.client.get('/purchases/login/'),'/login/')

    def test_assigned_director_approval_combines_even_old_false_snapshot(self):
        d=self.create('quality','review')
        d.route['combine_confirmation']=False;d.save()
        d=request_action(d.pk,d.reviewer,'forward',new_person=self.user('prod_director'))
        self.as_user('prod_director')
        self.assertTrue(self.client.get(reverse('purchasing:detail',args=[d.pk])).context['approve_combined'])
        d=request_action(d.pk,self.user('prod_director'),'approve')
        self.assertEqual(d.confirmation_method,'with_approval');self.assertIsNotNone(d.confirmed_at)
        self.assertTrue(finance_requests(self.user('finance')).filter(pk=d.pk).exists())
        with self.assertRaises(PermissionDenied):request_action(d.pk,self.user('prod_director'),'approve')
        self.assertEqual(PurchaseEvent.objects.filter(request=d,event='승인 시 구매 내용 함께 확인').count(),1)

    def test_authorized_checker_reviewer_finishes_with_false_snapshot(self):
        d=self.create('quality','review',reviewer=self.user('prod_director'))
        d.route['combine_confirmation']=False;d.save()
        PurchasePolicy.objects.get(pk=1).review_final_users.add(self.user('prod_director'))
        d=request_action(d.pk,self.user('prod_director'),'review_final')
        self.assertEqual(d.confirmation_method,'with_approval')

    def test_other_director_does_not_replace_assigned_checker(self):
        d=self.create('quality','review')
        # Existing saved approval routes can name another department's director.
        d.approver=self.user('dev_director');d.status='approval';d.save()
        d=request_action(d.pk,self.user('dev_director'),'approve')
        self.assertEqual(d.status,'ready');self.assertIsNone(d.confirmed_at)
        self.assertFalse(finance_requests(self.user('finance')).filter(pk=d.pk).exists())

    def test_ceo_default_in_progress_completed_separate_and_undo_returns(self):
        paid=self.report([self.confirmed()]);pending=self.report([self.confirmed()])
        self.process(paid)
        self.as_user('ceo')
        self.assertEqual(self.ids(),[pending.pk]);self.assertEqual(self.ids('?tab=completed'),[paid.pk])
        response=self.client.get(reverse('purchasing:report_detail',args=[paid.pk]))
        self.assertContains(response,'?tab=completed');self.assertNotContains(response,'수령 현황')
        self.process(paid,'undo')
        self.assertEqual(set(self.ids()),{paid.pk,pending.pk});self.assertEqual(self.ids('?tab=completed'),[])
        self.as_user('finance');self.assertEqual(set(self.ids('?tab=sent')),{paid.pk,pending.pk})

    def test_hold_is_open_but_superseded_history_is_closed_and_deny_is_closed(self):
        d=self.confirmed();held=self.report([d]);self.process(held,'hold')
        denied=self.report([self.confirmed()]);self.process(denied,'deny')
        self.as_user('ceo');self.assertEqual(self.ids(),[held.pk])
        request_action(d.pk,self.user('finance'),'prepare_hold','다시 확인')
        replacement=self.report([PurchaseRequest.objects.get(pk=d.pk)])
        self.assertEqual(self.ids(),[replacement.pk])
        self.assertEqual(set(self.ids('?tab=completed')),{held.pk,denied.pk})
        self.assertContains(self.client.get(reverse('purchasing:reports')+'?tab=completed'),'재요청됨')
