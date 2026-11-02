"""Production stock records end with the assigned reviewer's confirmation."""
from copy import deepcopy
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .accounting import accounting_documents, accounting_tabs
from .delegation import resolve_route, route_preview
from .home import progress_stages
from .models import ApprovalFlowPolicy, ApprovalRule, Audit, Document, DocumentReceipt, Notice, Profile, RANKS
from .notifications import visible_notices
from .services import act_on_document, accountants, may_delete_document, save_document, visible_documents


@override_settings(INTEGRATED_PURCHASES=True)
class StockRecordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ApprovalRule.objects.update(enabled=False)
        ApprovalFlowPolicy.objects.update_or_create(pk=1, defaults={'enabled':True})
        for name, rank, flags in [
            ('author','대리',{}), ('reviewer','과장',{}), ('approver','이사',{}),
            ('finance','과장',{'view_accounting':True,'procure':True}),
            ('admin','이사',{'manage_system':True}), ('other','대리',{}),
        ]:
            user=get_user_model().objects.create_user('stock_'+name,first_name=name,password='fictional-stock-only')
            Profile.objects.create(user=user,department='개발팀',rank=rank,approved=True,department_confirmed=True,**flags)
            setattr(cls,name,user)
        cls.rule=ApprovalRule.objects.create(name='기존 공통 결재규정',kind='all',enabled=True,skip_review=True,
            reviewer_ranks=RANKS[1:],approver_ranks=RANKS[1:],fixed_approver=cls.approver,
            allow_skip_review=True,allow_self_approval=True,allow_review_final=True,allow_representative_direct=True)
        cls.rule.review_final_users.add(cls.reviewer)

    def submit(self):
        return save_document(Document(owner=self.author,reviewer=self.reviewer,approver=self.approver,
            recipient=self.finance,kind='stock',product='생산용 보관함',quantity=20,
            unit_price=Decimal('15000'),url='https://example.com/ignored'),self.author,submit=True)

    def confirmed(self):
        return act_on_document(self.submit().pk,self.reviewer,'review')

    def test_shared_rules_and_progressive_policy_cannot_add_an_approval_or_fulfillment(self):
        doc=self.submit()
        self.assertEqual(doc.status,'review')
        self.assertTrue(doc.review_required)
        self.assertFalse(doc.final_approval_required)
        self.assertFalse(doc.progressive)
        self.assertTrue(doc.route_snapshot['stock_record_only'])
        self.assertIsNone(doc.approver_id)
        self.assertIsNone(doc.representative_id)
        self.assertIsNone(doc.recipient_id)
        self.assertEqual((doc.unit_price,doc.url),(0,''))
        preview=route_preview('stock',self.author.profile.rank,0,owner=self.author)
        self.assertEqual(preview['path'],'기안 → 검토자 확인 → 기록 보관')
        self.assertEqual(preview['available_modes'],['base'])
        for mode in ['self','skip','ceo']:
            with self.assertRaises(ValidationError):resolve_route('stock',self.author.profile.rank,owner=self.author,mode=mode)

    def test_confirmation_preserves_author_reviewer_time_content_and_audit(self):
        doc=self.confirmed()
        self.assertEqual((doc.status,doc.status_label),('approved','확인 완료'))
        self.assertEqual(doc.reviewed_at,doc.approved_at)
        self.assertEqual((doc.product,doc.quantity,doc.owner_id,doc.reviewer_id),('생산용 보관함',20,self.author.pk,self.reviewer.pk))
        self.assertTrue(Audit.objects.filter(document=doc,actor=self.reviewer,event='재고 요청 확인 완료').exists())
        self.assertTrue(Notice.objects.filter(document=doc,user=self.author,stage='확인완료').exists())
        self.assertEqual(accountants(doc),[])
        self.assertFalse(Notice.objects.filter(document=doc,user=self.finance).exists())
        self.assertEqual([s['label'] for s in progress_stages(doc)],['기안','확인','완료'])
        for user in [self.author,self.reviewer,self.admin]:self.assertTrue(visible_documents(user).filter(pk=doc.pk).exists())
        self.assertFalse(visible_documents(self.finance).filter(pk=doc.pk).exists())
        self.assertFalse(visible_documents(self.other).filter(pk=doc.pk).exists())

    def test_finance_inboxes_counts_old_notices_and_direct_access_exclude_stock(self):
        doc=self.confirmed()
        Notice.objects.create(user=self.finance,document=doc,stage='검토완료',text='이전 발주 알림')
        self.assertFalse(visible_notices(self.finance).filter(document=doc).exists())
        self.assertFalse(accounting_documents(self.finance).filter(pk=doc.pk).exists())
        self.assertEqual([t['key'] for t in accounting_tabs(self.finance)],['all','leave','office'])
        self.client.force_login(self.finance)
        for mode in ['accounting','stock','receive','pending']:
            response=self.client.get(reverse('documents'),{'mode':mode})
            self.assertEqual(response.status_code,200)
            self.assertNotIn(doc.pk,[d.pk for d in response.context['documents']])
        self.assertEqual(self.client.get(reverse('detail',args=[doc.pk])).status_code,404)
        self.assertFalse(DocumentReceipt.objects.filter(document=doc).exists())

    def test_assigned_finance_employee_can_still_review_their_own_assigned_task(self):
        doc=save_document(Document(owner=self.author,reviewer=self.finance,kind='stock',product='부품',quantity=3),self.author,submit=True)
        self.assertTrue(visible_notices(self.finance).filter(document=doc,stage='검토대기').exists())
        doc=act_on_document(doc.pk,self.finance,'review')
        self.assertEqual(doc.status_label,'확인 완료')
        self.assertFalse(accounting_documents(self.finance).filter(pk=doc.pk).exists())

    def test_no_stock_place_receive_forward_or_self_confirmation(self):
        pending=self.submit()
        for user in [self.author,self.finance,self.approver]:
            with self.assertRaises(PermissionDenied):act_on_document(pending.pk,user,'review')
        for action in ['forward','review_final','escalate']:
            with self.assertRaises(ValidationError):act_on_document(pending.pk,self.reviewer,action,new_person=self.approver)
        doc=act_on_document(pending.pk,self.reviewer,'review')
        for action in ['place','receive']:
            for user in [self.author,self.reviewer,self.finance,self.admin]:
                with self.assertRaises(PermissionDenied):act_on_document(doc.pk,user,action)
        doc.refresh_from_db();self.assertEqual(doc.shipment,'')
        act_on_document(doc.pk,self.reviewer,'cancel_review','수량 재확인')
        doc.refresh_from_db();self.assertFalse(may_delete_document(doc,self.finance))
        self.assertTrue(Audit.objects.filter(document=doc,event='재고 요청 확인 완료').exists())

    def test_record_pages_show_confirmation_without_procurement_actions(self):
        doc=self.submit();self.client.force_login(self.reviewer)
        response=self.client.get(reverse('detail',args=[doc.pk]))
        self.assertContains(response,'확인 완료')
        self.assertNotContains(response,'data-workflow-forward')
        self.assertNotContains(response,'data-stage="procurement"')
        self.assertNotIn('place',dict(response.context['actions']))
        doc=act_on_document(doc.pk,self.reviewer,'review')
        response=self.client.get(reverse('documents'),{'mode':'stock','stock_stage':'confirmed'})
        self.assertContains(response,doc.number)
        self.assertContains(response,'생산 재고 기록함')
        self.assertNotContains(response,'stock_stage=ordered')
        self.assertNotContains(response,'<th>물품 상태</th>',html=True)
        self.assertContains(self.client.get(reverse('documents'),{'mode':'history'}),doc.number)

    def test_existing_submitted_routes_shipments_and_audits_are_not_rewritten(self):
        route={'progressive':True,'stock_final_approval':True,'mode':'base','skip_review':False,
            'author_rank':'대리','reviewer_ranks':RANKS[1:],'approver_ranks':RANKS[1:]}
        doc=Document.objects.create(owner=self.author,reviewer=self.reviewer,approver=self.approver,
            kind='stock',product='기존 기록',quantity=5,status='approved',shipment='ordered',
            route_snapshot=deepcopy(route),reviewed_at=timezone.now(),approved_at=timezone.now())
        log=Audit.objects.create(document=doc,actor=self.reviewer,event='이전 검토')
        before=Document.objects.values().get(pk=doc.pk)
        self.client.force_login(self.author);self.client.get(reverse('detail',args=[doc.pk]))
        self.assertEqual(Document.objects.values().get(pk=doc.pk),before)
        self.assertTrue(Audit.objects.filter(pk=log.pk).exists())
        self.assertFalse(accounting_documents(self.finance).filter(pk=doc.pk).exists())
        with self.assertRaises(PermissionDenied):act_on_document(doc.pk,self.finance,'place')
