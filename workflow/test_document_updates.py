from datetime import date, time, timedelta
from decimal import Decimal
from importlib import import_module
from unittest.mock import patch
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from .models import (Profile, AnnualBalance, ApprovalRule, ApprovalFlowPolicy, Document,
                     DocumentReceipt, OwnerCompletionReceipt, LeaveCorrection, Notice)
from .services import save_document, act_on_document, visible_documents
from .completion import owner_completed
from .accounting import accounting_tabs
from .leave_corrections import correct_approved_leave
from .manual_leave import register_manual_leave


class DocumentUpdatesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ApprovalRule.objects.update(enabled=False)
        ApprovalFlowPolicy.objects.update_or_create(pk=1, defaults={'enabled':False})
        for name, rank, dept in [('author','대리','개발팀'),('reviewer','팀장','개발팀'),('approver','이사','개발팀'),
                                 ('finance','과장','인사팀'),('finance2','과장','인사팀'),('other','사원','생산팀'),('admin','이사','인사팀')]:
            u=get_user_model().objects.create_user(name, first_name='예시'+name)
            Profile.objects.create(user=u, rank=rank, department=dept, approved=True,
                manage_leave=name.startswith('finance'), view_accounting=name.startswith('finance'),manage_system=name=='admin')
            AnnualBalance.objects.create(user=u, year=2026,total=20,grant_initialized=True,total_manual=True)
            setattr(cls,name,u)

    def as_user(self,u): self.client.force_login(u);return self.client
    def leave(self, day=date(2026,10,20), **extra):
        doc=save_document(Document(owner=self.author,reviewer=self.reviewer,approver=self.approver,kind='leave',
            start_date=day,end_date=day,reason='original-private-reason',**extra),self.author,submit=True)
        act_on_document(doc.pk,self.reviewer,'review')
        return act_on_document(doc.pk,self.approver,'approve')
    def values(self, day=date(2026,10,20), **extra):
        return dict(leave_type='am',start_date=day,end_date=day,start_time=time(9),end_time=time(13),
                    correction_reason='실제 오전반차 사용',**extra)
    def used(self,year=2026):return AnnualBalance.objects.get(user=self.author,year=year).used
    def purchase(self,product='A4 복사 용지 MX-200',**extra):
        data=dict(owner=self.other,kind='office',status='approved',product=product,
                  quantity=3,unit_price=1000,reason='SECRET_REASON',url='https://private.invalid/SECRET',
                  recipient=self.other,shipment='received',submitted_at=timezone.now())
        data.update(extra)
        from .purchase_hints import normalize_product
        return Document.objects.create(product_search=normalize_product(product),**data)

    def test_completion_count_only_owner_and_only_opened_document(self):
        a=self.leave();b=self.leave(date(2026,10,21))
        self.as_user(self.author)
        self.assertEqual(self.client.get(reverse('notification_status')).json()['completed_unread'],2)
        page=self.client.get(reverse('documents'),{'mode':'completed','unread':'1'})
        self.assertContains(page,'NEW',count=2)
        self.assertEqual(OwnerCompletionReceipt.objects.count(),0)
        self.client.get(reverse('detail',args=[a.pk]))
        self.assertEqual(self.client.get(reverse('notification_status')).json()['completed_unread'],1)
        self.assertFalse(owner_completed(self.author).get(pk=a.pk).completion_seen is False)
        self.assertFalse(owner_completed(self.author).get(pk=b.pk).completion_seen)
        self.as_user(self.other);self.assertEqual(self.client.get(reverse('notification_status')).json()['completed_unread'],0)
        self.assertEqual(self.client.get(reverse('detail',args=[b.pk])).status_code,404)

    def test_finance_and_bell_read_are_independent_of_owner_completion(self):
        d=self.leave();self.as_user(self.finance);self.client.get(reverse('detail',args=[d.pk]))
        Notice.objects.filter(user=self.author).update(read=True)
        self.assertFalse(owner_completed(self.author).get().completion_seen)
        self.assertEqual(accounting_tabs(self.finance)[0]['unread_count'],0)
        self.as_user(self.author);self.client.get(reverse('detail',args=[d.pk]))
        self.assertEqual(accounting_tabs(self.finance2)[0]['unread_count'],1)

    def test_completion_reverts_to_zero_after_final_cancel_and_deleted(self):
        d=self.leave();self.assertEqual(owner_completed(self.author).count(),1)
        act_on_document(d.pk,self.approver,'cancel_approval','미사용')
        self.assertEqual(owner_completed(self.author).count(),0)
        act_on_document(d.pk,self.author,'delete')
        self.assertEqual(owner_completed(self.author).count(),0)

    def test_correction_restores_difference_and_preserves_approval_snapshot(self):
        d=self.leave();before=(d.approved_at,d.reviewed_at,d.route_snapshot,d.reason,d.approver_id)
        d=correct_approved_leave(d.pk,self.finance,self.values(),0)
        self.assertEqual(self.used(),Decimal('.5'));self.assertEqual(d.charged,Decimal('.5'))
        self.assertEqual((d.approved_at,d.reviewed_at,d.route_snapshot,d.reason,d.approver_id),before)
        self.assertEqual(d.allocations,{'2026':'0.5'})
        record=LeaveCorrection.objects.get(document=d)
        self.assertEqual(record.before['charged'],'1.00');self.assertEqual(record.after['charged'],'0.5')
        self.assertIn('2026-10-20',record.before['start_date'])
        self.assertTrue(d.audits.filter(event='승인 휴가 사용내역 정정',actor=self.finance).exists())

    def test_replayed_or_stale_correction_does_not_reapply(self):
        d=self.leave();correct_approved_leave(d.pk,self.finance,self.values(),0)
        with self.assertRaises(ValidationError):correct_approved_leave(d.pk,self.finance2,self.values(),0)
        self.assertEqual(self.used(),Decimal('.5'));self.assertEqual(LeaveCorrection.objects.count(),1)

    def test_correction_then_cancel_then_delete_restores_only_current_charge_once(self):
        d=self.leave();correct_approved_leave(d.pk,self.finance,self.values(),0)
        act_on_document(d.pk,self.approver,'cancel_approval','취소')
        self.assertEqual(self.used(),0)
        act_on_document(d.pk,self.finance,'delete')
        self.assertEqual(self.used(),0);self.assertEqual(LeaveCorrection.objects.count(),1)
        with self.assertRaises(PermissionDenied):act_on_document(d.pk,self.finance,'delete')
        self.assertEqual(self.used(),0)

    def test_correction_marks_owner_and_all_finances_unread_again(self):
        d=self.leave()
        for u in [self.author,self.finance,self.finance2]:self.as_user(u);self.client.get(reverse('detail',args=[d.pk]))
        correct_approved_leave(d.pk,self.finance,self.values(),0)
        self.assertFalse(owner_completed(self.author).get().completion_seen)
        for u in [self.finance,self.finance2]:self.assertEqual(accounting_tabs(u)[0]['unread_count'],1)
        self.assertTrue(Notice.objects.filter(user=self.author,stage='휴가정정',read=False).exists())
        self.as_user(self.author);self.client.get(reverse('detail',args=[d.pk]))
        self.assertEqual(accounting_tabs(self.finance)[0]['unread_count'],1)

    def test_correction_unauthorized_and_revoked_permissions_blocked(self):
        d=self.leave()
        for u in [self.author,self.reviewer,self.approver,self.other,self.admin]:
            with self.assertRaises(PermissionDenied):correct_approved_leave(d.pk,u,self.values(),0)
        Profile.objects.filter(user=self.finance).update(manage_leave=False)
        with self.assertRaises(PermissionDenied):correct_approved_leave(d.pk,self.finance,self.values(),0)
        self.assertEqual(self.used(),1)

    def test_cancelled_and_purchase_documents_cannot_be_corrected(self):
        d=self.leave();act_on_document(d.pk,self.approver,'cancel_approval','취소')
        for doc in [d,self.purchase()]:
            with self.assertRaises(ValidationError):correct_approved_leave(doc.pk,self.finance,self.values(),0)
        self.assertEqual(self.used(),0)

    def test_preview_does_not_mutate_and_save_updates_calendar_history_and_excel(self):
        d=self.leave();self.as_user(self.finance)
        url=reverse('correct_leave',args=[d.pk]);values={**self.values(),'revision':0,'intent':'preview'}
        response=self.client.post(url,values);self.assertContains(response,'확인한 내용으로 정정 저장')
        self.assertEqual(self.used(),1);self.assertEqual(LeaveCorrection.objects.count(),0)
        response=self.client.post(url,{**values,'intent':'save'});self.assertEqual(response.status_code,302)
        self.assertEqual(self.used(),Decimal('.5'))
        from .leave_records import leave_usage_summaries,employee_leave_records
        self.assertIn('10/20(반차)',leave_usage_summaries([self.author],2026)[self.author.pk]['personal'])
        from .calendars import month_grid
        days=[day for week in month_grid(2026,10,self.other)['weeks'] for day in week if day['date']==date(2026,10,20)]
        self.assertTrue(any('오전반차' in e['label'] for e in days[0]['events']))
        self.assertEqual(self.client.get(url).status_code,200)

    def test_invalid_empty_reason_weekend_time_overlap_and_no_change_roll_back(self):
        d=self.leave()
        candidates=[{**self.values(),'correction_reason':' '},self.values(date(2026,10,24)),
                    {**self.values(),'end_time':time(8)},
                    {**self.values(),'leave_type':'annual'},
                    {**self.values(),'leave_type':'invalid'}]
        for values in candidates:
            with self.assertRaises(ValidationError):correct_approved_leave(d.pk,self.finance,values,0)
        other=self.leave(date(2026,10,21))
        with self.assertRaises(ValidationError):correct_approved_leave(d.pk,self.finance,self.values(date(2026,10,21)),0)
        register_manual_leave(self.finance,self.author,dict(used_date=date(2026,10,22),leave_type='annual',reason='기존'),uuid4())
        with self.assertRaises(ValidationError):correct_approved_leave(d.pk,self.finance,self.values(date(2026,10,22)),0)
        self.assertEqual(self.used(),3);self.assertFalse(LeaveCorrection.objects.exists())

    def test_failure_after_reversal_rolls_back_balances_document_and_audit(self):
        d=self.leave()
        with patch('workflow.models.LeaveCorrection.objects.create',side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):correct_approved_leave(d.pk,self.finance,self.values(),0)
        d.refresh_from_db();self.assertEqual((self.used(),d.charged,d.leave_revision),(1,1,0))
        self.assertFalse(d.audits.filter(event='승인 휴가 사용내역 정정').exists())

    def test_cross_year_correction_uses_original_allocations(self):
        AnnualBalance.objects.create(user=self.author,year=2027,total=20,used=0,grant_initialized=True,total_manual=True)
        d=self.leave(date(2026,12,31));d=correct_approved_leave(d.pk,self.finance,self.values(date(2027,1,4)),0)
        self.assertEqual(self.used(2026),0);self.assertEqual(self.used(2027),Decimal('.5'))
        act_on_document(d.pk,self.approver,'cancel_approval','취소')
        self.assertEqual(self.used(2027),0)

    def test_multi_year_leave_changes_only_exact_document_allocations(self):
        AnnualBalance.objects.create(user=self.author,year=2027,total=20,used=0,grant_initialized=True,total_manual=True)
        d=save_document(Document(owner=self.author,reviewer=self.reviewer,approver=self.approver,kind='leave',
            start_date=date(2026,12,31),end_date=date(2027,1,1),reason='연도간'),self.author,submit=True)
        act_on_document(d.pk,self.reviewer,'review');act_on_document(d.pk,self.approver,'approve')
        correct_approved_leave(d.pk,self.finance,self.values(date(2026,12,31)),0)
        self.assertEqual(self.used(2026),Decimal('.5'));self.assertEqual(self.used(2027),0)

    def test_cancelled_deletion_owner_finance_admin_only_and_retains_records(self):
        d=self.leave();act_on_document(d.pk,self.approver,'cancel_approval','취소')
        with self.assertRaises(PermissionDenied):act_on_document(d.pk,self.other,'delete')
        self.as_user(self.finance);self.assertContains(self.client.get(reverse('detail',args=[d.pk])),'기안 삭제')
        response=self.client.post(reverse('action',args=[d.pk]),{'action':'delete'})
        self.assertEqual(response.status_code,302);d.refresh_from_db();self.assertEqual(d.status,'deleted')
        self.assertTrue(d.audits.filter(event='최종 승인 취소').exists());self.assertEqual(self.used(),0)
        self.assertFalse(visible_documents(self.author).filter(pk=d.pk).exists())
        self.assertFalse(visible_documents(self.admin).filter(pk=d.pk).exists())
        self.as_user(self.admin);self.assertContains(self.client.get(reverse('documents'),{'mode':'deleted'}),d.number)
        self.assertEqual(self.client.get(reverse('detail',args=[d.pk])).status_code,200)
        self.as_user(self.other);self.assertEqual(self.client.get(reverse('documents'),{'mode':'deleted'}).status_code,403)

    def test_approved_documents_cannot_be_deleted_even_by_finance(self):
        d=self.leave()
        for u in [self.author,self.finance,self.admin]:
            with self.assertRaises(PermissionDenied):act_on_document(d.pk,u,'delete')
        self.assertEqual(self.used(),1)

    def test_similar_purchase_all_years_including_received_and_minimal_fields(self):
        old=self.purchase(submitted_at=timezone.now()-timedelta(days=2500))
        self.as_user(self.author)
        response=self.client.get(reverse('purchase_hints'),{'q':'복사용지'});self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['count'],1)
        self.assertEqual(set(data['results'][0]),{'product','department','quantity','requested','status'})
        self.assertEqual(data['results'][0]['status'],'배송완료')
        self.assertNotContains(response,'SECRET');self.assertEqual(self.client.get(reverse('detail',args=[old.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('purchase_hints'),{'q':'mx200'}).json()['count'],1)
        self.assertIn('no-store',response['Cache-Control'])

    def test_similarity_excludes_draft_rejected_cancelled_deleted_confidential_and_self(self):
        for status in ['draft','rejected','cancelled','deleted']:self.purchase(status=status)
        self.purchase(purchase_private=True)
        own=self.purchase()
        self.as_user(self.author)
        self.assertEqual(self.client.get(reverse('purchase_hints'),{'q':'복사','exclude':own.pk}).json()['count'],0)
        self.assertEqual(self.client.get(reverse('purchase_hints'),{'q':'복사'}).json()['count'],1)
        self.client.logout();self.assertEqual(self.client.get(reverse('purchase_hints'),{'q':'복사'}).status_code,302)

    def test_similarity_progress_before_received_limit_and_no_empty_short_search(self):
        for i in range(12):self.purchase(product=f'복사용지 {i}')
        self.purchase(product='복사용지 진행중',status='review',shipment='',submitted_at=timezone.now()-timedelta(days=3000))
        self.as_user(self.author)
        data=self.client.get(reverse('purchase_hints'),{'q':'복사용지'}).json()
        self.assertEqual((data['count'],len(data['results'])),(13,8));self.assertEqual(data['results'][0]['status'],'검토대기')
        for q in ['','복','--']:
            self.assertEqual(self.client.get(reverse('purchase_hints'),{'q':q}).json()['count'],0)

    def test_purchase_search_index_set_by_submission_service_and_confidential_copied(self):
        d=save_document(Document(owner=self.author,kind='office',product='ＭＸ-200 복사 용지',purchase_private=True),self.author)
        self.assertEqual(d.product_search,'mx200복사용지')
        d.status='cancelled';d.save();self.as_user(self.author)
        response=self.client.post(reverse('copy',args=[d.pk]));self.assertEqual(response.status_code,302)
        copied=Document.objects.exclude(pk=d.pk).get();self.assertTrue(copied.purchase_private)

    def test_correction_ui_hides_permission_and_get_does_not_change_data(self):
        d=self.leave();self.as_user(self.author)
        self.assertNotContains(self.client.get(reverse('detail',args=[d.pk])),'휴가 사용내역 정정</a>')
        self.assertEqual(self.client.get(reverse('correct_leave',args=[d.pk])).status_code,403)
        self.as_user(self.finance);self.assertContains(self.client.get(reverse('detail',args=[d.pk])),'휴가 사용내역 정정</a>')
        self.assertEqual(self.client.get(reverse('correct_leave',args=[d.pk])).status_code,200)
        self.assertEqual(self.used(),1)


class DocumentUpdateMigrationTests(TransactionTestCase):
    def test_existing_records_and_receipts_preserved_and_index_built(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        target=[('workflow','0019_live_notifications_webpush')]
        executor=MigrationExecutor(connection);executor.migrate(target)
        self.addCleanup(lambda:MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        old=executor.loader.project_state(target).apps
        User=old.get_model('auth','User');P=old.get_model('workflow','Profile');D=old.get_model('workflow','Document')
        N=old.get_model('workflow','Notice');B=old.get_model('workflow','AnnualBalance');R=old.get_model('workflow','DocumentReceipt')
        u=User.objects.create(username='migration-owner',password='hash-to-preserve')
        P.objects.create(user=u,department='개발팀',rank='대리',approved=True)
        B.objects.create(user=u,year=2026,total=20,used='1.5',total_manual=True,grant_initialized=True)
        now=timezone.now()
        seen=D.objects.create(owner=u,status='approved',kind='office',product='Ａ４ 복사 용지 MX-200',approved_at=now,route_snapshot={'keep':'exact'},quantity=3)
        unseen=D.objects.create(owner=u,status='approved',kind='leave',approved_at=now,charged='1',allocations={'2026':'1'})
        N.objects.create(user=u,document=seen,stage='승인완료',read=True,text='keep')
        N.objects.create(user=u,document=unseen,stage='승인완료',read=False,text='keep')
        receipt=R.objects.create(user=u,document=seen,approval_stamp=now)
        before={model.__name__:list(model.objects.order_by('pk').values()) for model in [User,P,B,D,N,R]}
        executor=MigrationExecutor(connection);executor.migrate(executor.loader.graph.leaf_nodes())
        new=executor.loader.project_state(executor.loader.graph.leaf_nodes()).apps
        for name,rows in before.items():
            model=new.get_model('auth' if name=='User' else 'workflow',name)
            for original in rows:
                current=model.objects.values().get(pk=original['id'])
                self.assertEqual({k:current[k] for k in original},original)
        self.assertEqual(Document.objects.get(pk=seen.pk).product_search,'a4복사용지mx200')
        self.assertTrue(OwnerCompletionReceipt.objects.filter(user_id=u.pk,document_id=seen.pk).exists())
        self.assertFalse(OwnerCompletionReceipt.objects.filter(document_id=unseen.pk).exists())
        self.assertEqual(DocumentReceipt.objects.get(pk=receipt.pk).approval_stamp,now)
