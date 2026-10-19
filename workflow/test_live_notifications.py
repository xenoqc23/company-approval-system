import base64
import hashlib
import json
import tempfile
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch,Mock
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase,Client,override_settings,TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from .models import (Profile,AnnualBalance,ApprovalRule,ApprovalFlowPolicy,Document,Notice,
                     DocumentReceipt,NotificationPreference,PushSubscription,PushDelivery,AccountingReadState)
from .services import save_document,act_on_document
from .push import validate_subscription,public_key,deliver_pending,send_subscription
from .accounting import accounting_tabs


def subscription_data(suffix='one'):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    point=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    enc=lambda b:base64.urlsafe_b64encode(b).rstrip(b'=').decode()
    return dict(endpoint='https://fcm.googleapis.com/fcm/send/test-'+suffix,keys=dict(p256dh=enc(point),auth=enc(b'0123456789abcdef')))


class LiveNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ApprovalRule.objects.update(enabled=False)
        ApprovalFlowPolicy.objects.update_or_create(pk=1,defaults={'enabled':True})
        cls.rule=ApprovalRule.objects.create(name='공통 테스트',kind='all',enabled=True,reviewer_ranks=['팀장'],approver_ranks=['이사'],allow_review_final=True)
        for name,rank in [('author','대리'),('reviewer','팀장'),('approver','이사'),('finance','과장'),('finance2','과장'),('other','사원')]:
            u=get_user_model().objects.create_user(name,first_name='예시'+name,password='local-test-only')
            Profile.objects.create(user=u,department='개발팀',rank=rank,approved=True,
                view_accounting=name.startswith('finance'),manage_leave=name.startswith('finance'))
            AnnualBalance.objects.create(user=u,year=2026,total=20,grant_initialized=True)
            setattr(cls,name,u)
        cls.rule.review_final_users.add(cls.reviewer)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.settings=override_settings(WEBPUSH_ENABLED=True,DATA_DIR=Path(self.tmp.name),WEBPUSH_PRIVATE_KEY_FILE=str(Path(self.tmp.name)/'key.pem'))
        self.settings.enable();self.addCleanup(self.settings.disable)
        call_command('init_webpush',stdout=Mock())

    def leave(self,day=20):
        return save_document(Document(owner=self.author,reviewer=self.reviewer,kind='leave',leave_type='annual',
            start_date=date(2026,10,day),end_date=date(2026,10,day),reason='개인 일정'),self.author,submit=True)

    def finish(self,doc):return act_on_document(doc.pk,self.reviewer,'review_final','부서 전결')
    def as_user(self,user):self.client.force_login(user);return self.client
    def post_json(self,name,data):return self.client.post(reverse(name),json.dumps(data),content_type='application/json')
    def sub(self,user,suffix='one'):
        return PushSubscription.objects.create(user=user,**validate_subscription(subscription_data(suffix)))

    def test_live_events_target_only_current_assignee_and_never_mark_read(self):
        self.as_user(self.reviewer);initial=self.client.get(reverse('notification_status')).json()
        doc=self.leave();response=self.client.get(reverse('notification_status'),{'after':initial['latest']});data=response.json()
        self.assertEqual((data['waiting'],data['unread'],len(data['events'])),(1,1,1));self.assertIn(str(doc.pk),data['events'][0]['url'])
        self.assertIn('no-store',response['Cache-Control'])
        self.as_user(self.other);self.assertEqual(self.client.get(reverse('notification_status'),{'after':0}).json()['events'],[])
        self.as_user(self.reviewer);self.client.get(reverse('detail',args=[doc.pk]))
        data=self.client.get(reverse('notification_status')).json();self.assertEqual((data['waiting'],data['unread']),(1,0))
        act_on_document(doc.pk,self.reviewer,'forward','검토 완료',self.approver)
        self.as_user(self.approver);data=self.client.get(reverse('notification_status'),{'after':0}).json();self.assertEqual(data['waiting'],1)
        self.assertTrue(any('승인대기' in e['text'] for e in data['events']))

    def test_accounting_categories_keep_unread_until_each_document_opened(self):
        a=self.finish(self.leave());b=self.finish(self.leave(21))
        self.as_user(self.finance)
        for params in [{'mode':'accounting'},{'mode':'accounting','kind':'leave'},{'mode':'accounting','kind':'all'}]:
            response=self.client.get(reverse('documents'),params);self.assertEqual(response.status_code,200)
            self.assertEqual(accounting_tabs(self.finance)[0]['unread_count'],2)
            self.assertContains(response,'NEW',count=2)
        self.client.get(reverse('detail',args=[a.pk]));self.assertEqual(accounting_tabs(self.finance)[0]['unread_count'],1)
        self.assertEqual(accounting_tabs(self.finance2)[0]['unread_count'],2)
        self.client.post(reverse('notices'));self.assertEqual(accounting_tabs(self.finance)[0]['unread_count'],1)
        self.client.get(reverse('detail',args=[b.pk]));self.assertEqual(accounting_tabs(self.finance)[0]['unread_count'],0)
        self.assertEqual(AccountingReadState.objects.count(),0)

    def test_new_approval_stamp_reopens_receipt_and_unauthorized_get_does_not_ack(self):
        doc=self.finish(self.leave());self.as_user(self.other)
        self.assertEqual(self.client.get(reverse('detail',args=[doc.pk])).status_code,404)
        self.assertFalse(DocumentReceipt.objects.exists())
        self.as_user(self.finance);self.client.get(reverse('detail',args=[doc.pk]))
        Document.objects.filter(pk=doc.pk).update(approved_at=timezone.now()+timedelta(seconds=2))
        self.assertEqual(accounting_tabs(self.finance)[0]['unread_count'],1)
        self.finance.profile.view_accounting=False;self.finance.profile.save()
        self.assertEqual(self.client.get(reverse('documents'),{'mode':'accounting'}).status_code,403)

    def test_same_finance_employee_can_receive_assigned_review_notice(self):
        self.reviewer.profile.view_accounting=True;self.reviewer.profile.save()
        doc=self.leave();self.as_user(self.reviewer)
        data=self.client.get(reverse('notification_status'),{'after':0}).json()
        self.assertEqual(len(data['events']),1);self.assertEqual(data['waiting'],1)

    def test_preferences_validate_and_keep_existing_counters(self):
        self.leave();self.as_user(self.reviewer)
        self.assertEqual(self.post_json('notification_preferences',{'popup':False,'sound':True}).status_code,200)
        self.assertEqual(self.client.get(reverse('notification_status')).json()['preferences'],{'popup':False,'sound':True})
        self.assertEqual(self.post_json('notification_preferences',{'popup':'no','sound':1}).status_code,400)
        self.assertEqual(self.client.get(reverse('notification_status'),{'after':'bad'}).status_code,400)
        self.assertEqual(self.client.get(reverse('notification_status')).json()['waiting'],1)

    def test_subscription_requires_csrf_and_safe_provider_and_valid_keys(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.reviewer)
        self.assertEqual(client.post(reverse('push_subscribe'),json.dumps(subscription_data()),content_type='application/json').status_code,403)
        data=subscription_data()
        for endpoint in ['https://127.0.0.1/private','http://fcm.googleapis.com/x','https://fcm.googleapis.com.evil.test/x','https://fcm.googleapis.com:8443/x','https://name@fcm.googleapis.com/x','https://localhost/x']:
            data['endpoint']=endpoint
            with self.assertRaises(ValidationError):validate_subscription(data)
        data=subscription_data();data['keys']['auth']='bad'
        with self.assertRaises(ValidationError):validate_subscription(data)
        self.as_user(self.reviewer);self.assertEqual(self.post_json('push_subscribe',subscription_data()).status_code,200)
        self.assertEqual(PushSubscription.objects.count(),1)
        self.assertEqual(self.client.get(reverse('push_subscribe')).status_code,405)
        self.assertEqual(self.client.post(reverse('push_subscribe'),b'[]',content_type='application/json').status_code,400)

    def test_shared_device_transfers_subscription_without_old_jobs(self):
        data=subscription_data();self.as_user(self.reviewer);self.post_json('push_subscribe',data);self.leave()
        self.assertEqual(PushDelivery.objects.count(),1)
        self.as_user(self.other);self.post_json('push_subscribe',data)
        sub=PushSubscription.objects.get();self.assertEqual(sub.user_id,self.other.pk)
        self.assertFalse(PushDelivery.objects.exists())
        self.as_user(self.reviewer);self.post_json('push_unsubscribe',{'endpoint':data['endpoint']});sub.refresh_from_db();self.assertTrue(sub.enabled)
        self.as_user(self.other);self.client.post(reverse('logout'),{'push_endpoint':data['endpoint']});sub.refresh_from_db();self.assertFalse(sub.enabled)

    def test_server_logout_revokes_signed_device_without_javascript(self):
        data=subscription_data();self.as_user(self.reviewer)
        response=self.post_json('push_subscribe',data)
        self.assertTrue(response.cookies['xenosys_push_device']['httponly'])
        self.client.post(reverse('logout'))
        self.assertFalse(PushSubscription.objects.get().enabled)

    def test_same_account_refresh_preserves_pending_device_test(self):
        data=subscription_data();self.as_user(self.reviewer);self.post_json('push_subscribe',data)
        sub=PushSubscription.objects.get();job=PushDelivery.objects.create(subscription=sub)
        self.post_json('push_subscribe',data)
        self.assertTrue(PushDelivery.objects.filter(pk=job.pk).exists())

    def test_diagnostics_are_device_scoped_and_show_worker_liveness(self):
        from .push import worker_heartbeat
        data=subscription_data();self.as_user(self.reviewer)
        self.post_json('push_subscribe',data)
        response=self.client.get(reverse('push_status')).json()
        self.assertTrue(response['subscribed']);self.assertFalse(response['worker_running'])
        worker_heartbeat()
        self.assertTrue(self.client.get(reverse('push_status')).json()['worker_running'])
        self.assertNotIn('endpoint',json.dumps(response));self.assertNotIn('p256dh',json.dumps(response))
        sub=PushSubscription.objects.get();PushDelivery.objects.create(subscription=sub,result='failed',finished_at=timezone.now(),attempts=5)
        self.assertIn('실패',self.client.get(reverse('push_status')).json()['last_delivery']['label'])
        self.as_user(self.other);response=self.client.get(reverse('push_status')).json()
        self.assertFalse(response['subscribed']);self.assertIsNone(response['last_delivery'])

    def test_diagnostic_queue_does_not_claim_pc_received_after_provider_acceptance(self):
        self.as_user(self.reviewer);self.post_json('push_subscribe',subscription_data())
        PushDelivery.objects.create(subscription=PushSubscription.objects.get(),result='sent',finished_at=timezone.now())
        label=self.client.get(reverse('push_status')).json()['last_delivery']['label']
        self.assertIn('푸시 서비스에 전달',label);self.assertNotIn('PC 수신 완료',label)

    def test_test_push_is_device_scoped_delayed_and_rate_limited(self):
        sub=self.sub(self.reviewer);self.as_user(self.reviewer)
        before=timezone.now();self.assertEqual(self.post_json('push_test',{'endpoint':sub.endpoint}).status_code,200)
        self.assertGreater(PushDelivery.objects.get().next_attempt_at,before+timedelta(seconds=9))
        self.assertEqual(self.post_json('push_test',{'endpoint':sub.endpoint}).status_code,429)
        self.as_user(self.other);self.assertEqual(self.post_json('push_test',{'endpoint':sub.endpoint}).status_code,404)

    def test_queue_is_transactional_and_network_never_runs_in_approval(self):
        self.sub(self.reviewer)
        with patch('workflow.push.send_subscription') as send:
            try:
                with transaction.atomic():self.leave();raise ValueError('rollback')
            except ValueError:pass
            self.assertFalse(PushDelivery.objects.exists());self.assertFalse(Notice.objects.exists())
            self.leave();self.assertEqual(PushDelivery.objects.count(),1);send.assert_not_called()

    def test_worker_sends_generic_payload_once_and_expired_subscriptions_disabled(self):
        sub=self.sub(self.reviewer);doc=self.leave()
        with patch('workflow.push.send_subscription') as send:
            self.assertEqual(deliver_pending(),1);self.assertEqual(deliver_pending(),0)
            payload=send.call_args.args[1];self.assertNotIn('author',json.dumps(payload));self.assertEqual(payload['url'],'/notices/')
        self.assertEqual(PushDelivery.objects.get().result,'sent')
        self.leave(21)
        from pywebpush import WebPushException
        response=Mock(status_code=410);error=WebPushException('secret-endpoint-should-not-log',response=response)
        with patch('workflow.push.send_subscription',side_effect=error),self.assertLogs('workflow.push',level='WARNING') as logs:
            deliver_pending()
        self.assertNotIn('secret-endpoint',str(logs.output));sub.refresh_from_db();self.assertFalse(sub.enabled)

    def test_worker_retries_network_failure_without_affecting_document(self):
        self.sub(self.reviewer);doc=self.leave()
        with patch('workflow.push.send_subscription',side_effect=TimeoutError):deliver_pending()
        job=PushDelivery.objects.get();self.assertIsNone(job.finished_at);self.assertEqual(job.attempts,1)
        self.assertGreater(job.next_attempt_at,timezone.now());doc.refresh_from_db();self.assertEqual(doc.status,'review')
        self.assertEqual(deliver_pending(),0)
        PushDelivery.objects.update(next_attempt_at=timezone.now()-timedelta(seconds=1),attempts=4)
        with patch('workflow.push.send_subscription',side_effect=TimeoutError):deliver_pending()
        job.refresh_from_db();self.assertEqual(job.result,'failed');self.assertIsNotNone(job.finished_at)

    def test_worker_skips_read_reassigned_disabled_and_old_messages(self):
        self.sub(self.reviewer);self.leave();Notice.objects.update(read=True)
        with patch('workflow.push.send_subscription') as send:deliver_pending();send.assert_not_called()
        doc=self.leave(21);doc.reviewer=self.approver;doc.save()
        with patch('workflow.push.send_subscription') as send:deliver_pending();send.assert_not_called()
        self.leave(22);PushDelivery.objects.filter(finished_at=None).update(created_at=timezone.now()-timedelta(days=2))
        with patch('workflow.push.send_subscription') as send:deliver_pending();send.assert_not_called()
        self.assertTrue(PushDelivery.objects.filter(result='expired').exists())

    def test_key_initialization_idempotent_and_worker_uncached(self):
        key=public_key();call_command('init_webpush',stdout=Mock());self.assertEqual(public_key(),key)
        self.assertEqual(len(base64.urlsafe_b64decode(key+'=')),65)
        response=self.client.get(reverse('notifications_sw'));self.assertEqual(response.status_code,200)
        self.assertEqual(response['Service-Worker-Allowed'],'/');self.assertIn('no-store',response['Cache-Control'])
        self.assertNotIn('caches.open',response.content.decode())

    def test_transport_produces_real_encrypted_webpush_payload(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        import http_ece
        private=ec.generate_private_key(ec.SECP256R1());auth=b'0123456789abcdef'
        point=private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        enc=lambda b:base64.urlsafe_b64encode(b).rstrip(b'=').decode()
        data=subscription_data();data['keys']=dict(p256dh=enc(point),auth=enc(auth))
        sub=PushSubscription.objects.create(user=self.reviewer,**validate_subscription(data))
        with patch('requests.post',return_value=Mock(status_code=201)) as http:
            send_subscription(sub,{'body':'암호화 테스트','url':'/notices/'})
        encrypted=http.call_args.kwargs['data']
        plaintext=http_ece.decrypt(encrypted,private_key=private,auth_secret=auth,version='aes128gcm')
        self.assertEqual(json.loads(plaintext)['body'],'암호화 테스트')
        self.assertIn('vapid ',http.call_args.kwargs['headers']['Authorization'])


class ReceiptMigrationTests(TransactionTestCase):
    def test_existing_category_receipts_and_business_data_are_preserved(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        before=[('workflow','0018_reviewer_final_authority')]
        executor=MigrationExecutor(connection);executor.migrate(before)
        self.addCleanup(lambda:MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))
        old=executor.loader.project_state(before).apps
        User=old.get_model('auth','User');P=old.get_model('workflow','Profile');D=old.get_model('workflow','Document')
        finance=User.objects.create(username='receipt-finance',password='preserve-hash')
        P.objects.create(user=finance,department='인사팀',rank='과장',approved=True,view_accounting=True)
        now=timezone.now()
        read=D.objects.create(owner=finance,status='approved',kind='leave',approved_at=now-timedelta(days=2))
        unread=D.objects.create(owner=finance,status='approved',kind='leave',approved_at=now)
        old.get_model('workflow','AccountingReadState').objects.create(user=finance,kind='leave',seen_until=now-timedelta(days=1))
        models=['Document','Profile','AnnualBalance','Notice','AccountingReadState','ApprovalRule','ManualLeaveUsage']
        snapshots={m:list(old.get_model('workflow',m).objects.order_by('pk').values()) for m in models}
        after=[('workflow','0019_live_notifications_webpush')];MigrationExecutor(connection).migrate(after)
        current=MigrationExecutor(connection).loader.project_state(after).apps
        receipts=current.get_model('workflow','DocumentReceipt').objects
        self.assertEqual(list(receipts.values_list('document_id',flat=True)),[read.pk])
        for m,rows in snapshots.items():self.assertEqual(list(current.get_model('workflow',m).objects.order_by('pk').values()),rows,m)


@override_settings(WEBPUSH_ENABLED=False)
class NasInAppOnlyTests(TestCase):
    def setUp(self):
        ApprovalFlowPolicy.objects.update_or_create(pk=1,defaults={'enabled':True})
        ApprovalRule.objects.update(enabled=False)
        for name,rank in [('inapp-owner','대리'),('inapp-reviewer','팀장')]:
            u=get_user_model().objects.create_user(name,password='isolated-fixture-password')
            Profile.objects.create(user=u,department='개발팀',rank=rank,approved=True)
            setattr(self,'owner' if rank=='대리' else 'reviewer',u)

    def test_nas_hides_push_controls_but_keeps_popup_and_sound_preferences(self):
        self.client.force_login(self.reviewer)
        response=self.client.get(reverse('account'))
        self.assertContains(response,'data-screen-test')
        self.assertContains(response,'data-notification-popup')
        self.assertContains(response,'data-notification-sound')
        self.assertNotContains(response,'data-push-enable')
        self.assertNotContains(response,'data-os-test')
        self.assertNotContains(response,'data-push-diagnostics')
        self.assertFalse(response.context['notification_seed']['webpush_enabled'])

    def test_nas_never_queues_push_or_allows_device_registration(self):
        sub=PushSubscription.objects.create(user=self.reviewer,**validate_subscription(subscription_data()))
        doc=save_document(Document(owner=self.owner,reviewer=self.reviewer,kind='office',product='알림 검증',
            unit_price=10000,url='https://example.com/test'),self.owner,submit=True)
        self.assertTrue(Notice.objects.filter(user=self.reviewer,document=doc).exists())
        self.assertFalse(PushDelivery.objects.exists())
        self.client.force_login(self.reviewer)
        for url in ['push_subscribe','push_test']:
            response=self.client.post(reverse(url),json.dumps(subscription_data()),content_type='application/json')
            self.assertEqual(response.status_code,503)
        self.assertFalse(self.client.get(reverse('push_config')).json()['configured'])
        self.assertEqual(deliver_pending(),0)

    def test_production_setting_defers_push_even_if_local_flag_set(self):
        import os,runpy
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{
            'APPROVAL_PRODUCTION':'1','DJANGO_DEBUG':'0','DJANGO_SECRET_KEY':'x'*64,
            'DB_ENGINE':'mariadb','DB_NAME':'test','DB_USER':'test','DB_PASSWORD':'test-only',
            'DJANGO_ALLOWED_HOSTS':'testserver','APPROVAL_WEBPUSH_ENABLED':'1','APPROVAL_DATA_DIR':directory}):
            self.assertFalse(runpy.run_path(str(Path(__file__).resolve().parents[1]/'approval_site/settings.py'))['WEBPUSH_ENABLED'])
