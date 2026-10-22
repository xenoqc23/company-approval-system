import unittest
from django.conf import settings
if not settings.PURCHASE_LAB_ENABLED:raise unittest.SkipTest('Purchase lab is disabled.')
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from tempfile import TemporaryDirectory
from pathlib import Path
from io import StringIO
from uuid import uuid4
from decimal import Decimal
from django.test import TransactionTestCase,skipUnlessDBFeature
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import connection,close_old_connections
from .models import PurchaseRequest,PurchaseReport,PurchaseEvent
from .services import save_request,request_action,submit_report,decide_report


@skipUnlessDBFeature('has_select_for_update')
class PurchaseConcurrencyTests(TransactionTestCase):
    def setUp(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'password';path.write_text('fake-purchase-concurrency')
            call_command('seed_purchase_demo',password_file=path,stdout=StringIO())
        self.users={u.username:u for u in get_user_model().objects.select_related('profile')}
        v=dict(product='동시 처리 시험품',vendor='가상구매처',quantity=1,unit_price=Decimal('123.45'),url='',reason='동시 처리 검증',private=False,reviewer=self.users['p_dev_lead'],approver=self.users['p_dev_director'])
        self.doc=save_request(self.users['p_dev'],v,submit=True,key=uuid4())
        self.doc=request_action(self.doc.pk,self.users['p_dev_lead'],'approve')
        self.doc=request_action(self.doc.pk,self.users['p_dev_director'],'approve')
        self.doc=request_action(self.doc.pk,self.users['p_prod_director'],'confirm_items')
    def parallel(self,*operations):
        barrier=Barrier(len(operations))
        def work(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:operation();return 'ok'
                except (PermissionDenied,ValidationError):return 'refused'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures=[executor.submit(work,op) for op in operations]
            return [future.result(timeout=30) for future in futures]
    def report(self):return submit_report(self.users['p_finance'],[self.doc.pk],'동시 취합','중복 방지 검증',uuid4())
    def allowed_report(self):
        r=self.report();decisions={str(r.items.get().pk):dict(decision='allow',reason='')}
        return r,decisions
    def test_double_collection_creates_one_report(self):
        self.assertCountEqual(self.parallel(self.report,self.report),['ok','refused'])
        self.assertEqual(PurchaseReport.objects.count(),1)
    def test_final_decision_commits_once(self):
        r,values=self.allowed_report();op=lambda:decide_report(r.pk,self.users['p_ceo'],values,0,final=True)
        self.assertCountEqual(self.parallel(op,op),['ok','refused'])
        self.assertEqual(PurchaseEvent.objects.filter(request=self.doc,event='대표 구매허가').count(),1)
    def test_paid_confirmation_commits_once(self):
        r,values=self.allowed_report();decide_report(r.pk,self.users['p_ceo'],values,0,final=True)
        op=lambda:request_action(self.doc.pk,self.users['p_finance'],'paid','결제 확인')
        self.assertCountEqual(self.parallel(op,op),['ok','refused'])
        self.assertEqual(PurchaseEvent.objects.filter(request=self.doc,event='결제 완료 확인').count(),1)
    def test_cancellation_and_confirmation_cannot_both_commit(self):
        self.doc.confirmed_at=None;self.doc.confirmed_by=None;self.doc.purchase_route={};self.doc.save()
        self.assertCountEqual(self.parallel(lambda:request_action(self.doc.pk,self.users['p_prod_director'],'confirm_items'),lambda:request_action(self.doc.pk,self.users['p_dev'],'cancel','불필요')),['ok','refused'])
        self.doc.refresh_from_db();self.assertIn(self.doc.status,['ready','cancelled'])
        self.assertEqual(PurchaseReport.objects.count(),0)
        self.assertEqual(bool(self.doc.confirmed_at),self.doc.status=='ready')

    def test_double_item_confirmation_records_once(self):
        self.doc.confirmed_at=None;self.doc.confirmed_by=None;self.doc.purchase_route={};self.doc.save()
        before=PurchaseEvent.objects.filter(request=self.doc,event='구매 품목 확인').count()
        op=lambda:request_action(self.doc.pk,self.users['p_prod_director'],'confirm_items')
        self.assertCountEqual(self.parallel(op,op),['ok','refused'])
        self.assertEqual(PurchaseEvent.objects.filter(request=self.doc,event='구매 품목 확인').count(),before+1)
