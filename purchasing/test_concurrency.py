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
from .models import PurchaseRequest,PurchaseReport,PurchaseEvent,PurchasePolicy,PurchasePermission
from .services import save_request,request_action,submit_report,decide_report,amend_amount


@skipUnlessDBFeature('has_select_for_update')
class PurchaseConcurrencyTests(TransactionTestCase):
    def setUp(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'password';path.write_text('fake-purchase-concurrency')
            call_command('seed_purchase_demo',password_file=path,stdout=StringIO())
        PurchasePolicy.objects.filter(pk=1).update(department_routing=False)
        PurchasePermission.objects.filter(user__username='p_dev_director').delete()
        self.users={u.username:u for u in get_user_model().objects.select_related('profile')}
        v=dict(product='동시 처리 시험품',vendor='가상구매처',quantity=1,unit_price=Decimal('123.45'),url='https://example.com/item',reason='동시 처리 검증',private=False,reviewer=self.users['p_dev_lead'],approver=self.users['p_dev_director'])
        self.doc=save_request(self.users['p_dev'],v,submit=True,key=uuid4())
        self.doc=request_action(self.doc.pk,self.users['p_dev_lead'],'forward',new_person=self.users['p_dev_director']) if settings.INTEGRATED_PURCHASES else request_action(self.doc.pk,self.users['p_dev_lead'],'approve')
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
    def report(self):
        r=submit_report(self.users['p_finance'],[self.doc.pk],'동시 취합','중복 방지 검증',uuid4())
        r.payment_tracking=False;r.save(update_fields=['payment_tracking']);return r
    def allowed_report(self):
        r=self.report();decisions={str(r.items.get().pk):dict(decision='allow',reason='')}
        return r,decisions
    def test_double_collection_creates_one_report(self):
        self.assertCountEqual(self.parallel(self.report,self.report),['ok','refused'])
        self.assertEqual(PurchaseReport.objects.count(),1)
    def test_final_decision_commits_once(self):
        r,values=self.allowed_report();op=lambda:decide_report(r.pk,self.users['p_ceo'],values,0,final=True)
        self.assertCountEqual(self.parallel(op,op),['ok','refused'])
        self.assertEqual(PurchaseEvent.objects.filter(request=self.doc,event='대표 구매승인').count(),1)
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

    def test_duplicate_partial_receipt_never_counts_twice(self):
        self.doc.quantity=10;self.doc.save(update_fields=['quantity'])
        r,values=self.allowed_report();decide_report(r.pk,self.users['p_ceo'],values,0,final=True)
        request_action(self.doc.pk,self.users['p_finance'],'paid','실제 결제 확인')
        key=uuid4();op=lambda:request_action(self.doc.pk,self.users['p_dev'],'receive',quantity=6,receipt_key=key)
        self.assertCountEqual(self.parallel(op,op),['ok','refused'])
        self.doc.refresh_from_db();self.assertEqual((self.doc.status,self.doc.received_quantity,self.doc.remaining_quantity),(('received',10,0) if settings.INTEGRATED_PURCHASES else ('paid',6,4)));self.assertEqual(self.doc.receipts.count(),1)

    def test_amount_increase_and_receipt_cannot_both_commit(self):
        r,values=self.allowed_report();decide_report(r.pk,self.users['p_ceo'],values,0,final=True)
        self.doc.refresh_from_db();revision=self.doc.revision
        results=self.parallel(lambda:amend_amount(self.doc.pk,self.users['p_finance'],1,Decimal('200'),'금액 증가',revision),lambda:request_action(self.doc.pk,self.users['p_dev'],'receive',quantity=1,receipt_key=uuid4()))
        self.assertCountEqual(results,['ok','refused'])
        self.doc.refresh_from_db();self.assertIn(self.doc.status,['reapproval','received'])
        self.assertEqual(bool(self.doc.amendments.count()),self.doc.status=='reapproval')
        self.assertEqual(bool(self.doc.receipts.count()),self.doc.status=='received')

    def test_duplicate_amount_change_preserves_one_history_record(self):
        r,values=self.allowed_report();decide_report(r.pk,self.users['p_ceo'],values,0,final=True)
        self.doc.refresh_from_db();revision=self.doc.revision
        op=lambda:amend_amount(self.doc.pk,self.users['p_finance'],1,Decimal('100'),'할인 적용',revision)
        self.assertCountEqual(self.parallel(op,op),['ok','refused'])
        self.assertEqual(self.doc.amendments.count(),1)

    def department_request(self,method='direct'):
        p=PurchasePolicy.objects.get(pk=1);p.department_routing=True;p.save()
        PurchasePermission.objects.update_or_create(user=self.users['p_dev_director'],defaults={'view_completed':True})
        return save_request(self.users['p_dev_manager'],dict(product='부서별 동시 처리 시험',vendor='가상처',quantity=10,unit_price=Decimal('50000'),url='https://example.com/item',reason='동시 처리 검증',private=False,request_method=method,reviewer=self.users['p_dev_lead'],approver=self.users['p_dev_director']),submit=True,key=uuid4())

    def test_department_combined_final_approval_confirms_only_once(self):
        d=self.department_request('review');request_action(d.pk,self.users['p_dev_lead'],'forward',new_person=self.users['p_dev_director']) if settings.INTEGRATED_PURCHASES else request_action(d.pk,self.users['p_dev_lead'],'approve')
        if settings.INTEGRATED_PURCHASES:
            d.refresh_from_db();d.route['combine_confirmation']=False;d.save(update_fields=['route'])
        op=lambda:request_action(d.pk,self.users['p_dev_director'],'approve')
        self.assertCountEqual(self.parallel(op,op),['ok','refused'])
        d.refresh_from_db();self.assertEqual(d.confirmation_method,'with_approval');self.assertEqual(d.events.filter(event='승인 시 구매 내용 함께 확인').count(),1)

    def test_department_manual_confirmation_commits_once(self):
        d=self.department_request();op=lambda:request_action(d.pk,self.users['p_dev_director'],'confirm_items')
        self.assertCountEqual(self.parallel(op,op),['ok','refused'])
        d.refresh_from_db();self.assertEqual(d.confirmation_method,'manual');self.assertEqual(d.events.filter(event='구매 품목 확인').count(),1)

    def test_department_receipt_without_payment_never_counts_twice(self):
        d=self.department_request();request_action(d.pk,self.users['p_dev_director'],'confirm_items')
        r=submit_report(self.users['p_finance'],[d.pk],'부서별 동시 수령','직접 요청 경로 검증',uuid4())
        r.payment_tracking=False;r.save(update_fields=['payment_tracking'])
        decide_report(r.pk,self.users['p_ceo'],{str(r.items.get().pk):dict(decision='allow',reason='')},0,final=True)
        key=uuid4();op=lambda:request_action(d.pk,self.users['p_dev_manager'],'receive',quantity=6,receipt_key=key)
        self.assertCountEqual(self.parallel(op,op),['ok','refused'])
        d.refresh_from_db();self.assertEqual((d.received_quantity,d.remaining_quantity,d.status),((10,0,'received') if settings.INTEGRATED_PURCHASES else (6,4,'allowed')));self.assertEqual(d.receipts.count(),1)

    def test_reviewer_finish_and_forward_cannot_both_commit(self):
        if not settings.INTEGRATED_PURCHASES:self.skipTest('Reviewer-led full application only.')
        d=self.department_request('review');PurchasePolicy.objects.get(pk=1).review_final_users.add(self.users['p_dev_lead'])
        results=self.parallel(lambda:request_action(d.pk,self.users['p_dev_lead'],'review_final'),lambda:request_action(d.pk,self.users['p_dev_lead'],'forward',new_person=self.users['p_dev_director']))
        self.assertCountEqual(results,['ok','refused']);d.refresh_from_db();self.assertIn(d.status,['ready','approval'])
        self.assertEqual(PurchaseEvent.objects.filter(request=d,event__in=['내부 승인완료','검토 완료']).count(),1)

    def test_accounting_payment_and_rejection_cannot_both_commit(self):
        if not settings.INTEGRATED_PURCHASES:self.skipTest('New integrated payment flow only.')
        from .payments import process_payment
        r=submit_report(self.users['p_finance'],[self.doc.pk],'결제 동시 처리','실제 결제 등록 검증',uuid4());item=r.items.get()
        results=self.parallel(lambda:process_payment(r.pk,self.users['p_finance'],[item.pk],'paid','',0,apply=True),lambda:process_payment(r.pk,self.users['p_finance'],[item.pk],'deny','구매 취소',0,apply=True))
        self.assertCountEqual(results,['ok','refused']);self.doc.refresh_from_db();self.assertIn(self.doc.status,['paid','denied'])
        self.assertEqual(PurchaseEvent.objects.filter(request=self.doc,event__in=['결제 완료 확인','구매 반려']).count(),1)

    def test_duplicate_accounting_payment_registers_one_completion(self):
        if not settings.INTEGRATED_PURCHASES:self.skipTest('New integrated payment flow only.')
        from .payments import process_payment
        r=submit_report(self.users['p_finance'],[self.doc.pk],'중복 결제 등록','한 번만 완료',uuid4());item=r.items.get()
        op=lambda:process_payment(r.pk,self.users['p_finance'],[item.pk],'paid','',0,apply=True)
        self.assertCountEqual(self.parallel(op,op),['ok','refused'])
        self.assertEqual(PurchaseEvent.objects.filter(request=self.doc,event='결제 완료 확인').count(),1)
