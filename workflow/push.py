"""Durable Web Push queue. Network I/O is only performed by run_webpush."""
import base64
import hashlib
import json
import logging
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from .models import PushSubscription, PushDelivery

logger=logging.getLogger(__name__)


def key_path():
    return Path(settings.WEBPUSH_PRIVATE_KEY_FILE)


def public_key():
    if not key_path().is_file():return ''
    from cryptography.hazmat.primitives import serialization
    key=serialization.load_pem_private_key(key_path().read_bytes(),password=None)
    return base64.urlsafe_b64encode(key.public_key().public_bytes(
        serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)).rstrip(b'=').decode()


def validate_subscription(data):
    try:
        endpoint=data['endpoint']
        url=urlsplit(endpoint)
        host=(url.hostname or '').lower()
        allowed=(host in {'fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com'} or
                 host.endswith('.push.services.mozilla.com') or host.endswith('.notify.windows.com'))
        if (not isinstance(endpoint,str) or len(endpoint)>2048 or url.scheme!='https' or not allowed or
                url.port not in (None,443) or url.username or url.password or url.fragment):raise ValueError
        keys=data['keys'];p256dh=keys['p256dh'];auth=keys['auth']
        def decode(value):
            if not isinstance(value,str):raise ValueError
            return base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True)
        point=decode(p256dh)
        if len(point)!=65 or point[0]!=4 or len(decode(auth))!=16:raise ValueError
        from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey,SECP256R1
        EllipticCurvePublicKey.from_encoded_point(SECP256R1(),point)
    except (KeyError,TypeError,ValueError,AttributeError):
        raise ValidationError('올바른 브라우저 푸시 구독 정보가 필요합니다.')
    return dict(endpoint=endpoint,endpoint_hash=hashlib.sha256(endpoint.encode()).hexdigest(),p256dh=p256dh,auth=auth)


def enqueue(notices):
    by_user={}
    for sub in PushSubscription.objects.filter(enabled=True,user_id__in=[n.user_id for n in notices]):
        by_user.setdefault(sub.user_id,[]).append(sub)
    PushDelivery.objects.bulk_create([PushDelivery(notice=n,subscription=s)
        for n in notices for s in by_user.get(n.user_id,[])],ignore_conflicts=True)


def notice_deliverable(notice,user):
    from .notifications import visible_notices
    if not user.is_active or not user.profile.approved or user.profile.must_change_password:return False
    if notice is None:return True  # explicitly requested device test
    if notice.user_id!=user.pk or notice.read:return False
    if not visible_notices(user).filter(pk=notice.pk).exists():return False
    doc=notice.document
    if not doc:return True
    if notice.stage=='검토대기':return doc.status=='review' and doc.reviewer_id==user.pk
    if notice.stage in ['승인대기','검토완료 · 승인대기']:return doc.status=='approve' and doc.approver_id==user.pk
    if notice.stage=='대표결재대기':return doc.status=='executive' and doc.representative_id==user.pk
    if notice.stage=='승인완료':return doc.status=='approved'
    return doc.status not in ['draft','deleted']


def send_subscription(subscription,payload):
    from pywebpush import webpush
    return webpush(subscription_info=dict(endpoint=subscription.endpoint,keys=dict(
        p256dh=subscription.p256dh,auth=subscription.auth)),data=json.dumps(payload,ensure_ascii=False),
        vapid_private_key=str(key_path()),vapid_claims={'sub':settings.WEBPUSH_CONTACT},
        ttl=3600,timeout=8,headers={'Urgency':'normal'})


def deliver_pending(limit=50):
    if not public_key():return 0
    now=timezone.now();done=0
    available=PushDelivery.objects.filter(finished_at=None,next_attempt_at__lte=now).filter(
        Q(locked_until=None)|Q(locked_until__lt=now))
    ids=list(available.order_by('pk').values_list('pk',flat=True)[:limit])
    for pk in ids:
        token=str(uuid4())
        claim_now=timezone.now()
        claimable=PushDelivery.objects.filter(pk=pk,finished_at=None,next_attempt_at__lte=claim_now).filter(
            Q(locked_until=None)|Q(locked_until__lt=claim_now))
        if not claimable.update(claim=token,locked_until=claim_now+timedelta(minutes=2)):continue
        try:
            job=PushDelivery.objects.select_related('subscription__user__profile','notice__document').get(pk=pk)
        except PushDelivery.DoesNotExist:
            # A shared browser changed accounts and removed the old user's jobs.
            continue
        sub=job.subscription
        result=''
        try:
            if not sub.enabled or not notice_deliverable(job.notice,sub.user):result='skipped'
            elif job.created_at<now-timedelta(hours=24):result='expired'
            else:
                # Deliberately omit employee, document IDs and private contents from lock screens.
                send_subscription(sub,dict(title='사내결재시스템',body='새 결재 알림이 도착했습니다. 알림함에서 확인해 주세요.'
                    if job.notice_id else '웹 푸시 테스트 알림입니다.',url='/notices/',tag=f'approval-{job.pk}'))
                result='sent'
        except Exception as exc:
            status=getattr(getattr(exc,'response',None),'status_code',None)
            if status in [404,410]:
                PushSubscription.objects.filter(pk=sub.pk,endpoint=sub.endpoint).update(enabled=False)
                result='subscription_expired'
            elif job.attempts>=4:result='failed'
            # Never log exception text: endpoints and key material may be embedded.
            logger.warning('Web Push delivery %s attempt %s failed (HTTP %s)',job.pk,job.attempts+1,status or 'network')
        updates=dict(attempts=job.attempts+1,claim='',locked_until=None,result=result)
        if result:updates['finished_at']=timezone.now()
        else:updates['next_attempt_at']=now+timedelta(seconds=min(3600,30*2**job.attempts))
        PushDelivery.objects.filter(pk=pk,claim=token).update(**updates)
        done+=1
    return done
