import hashlib
import json
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET,require_POST
from django.conf import settings
from .models import NotificationPreference,PushSubscription,PushDelivery


def body(request):
    if len(request.body)>8192:raise ValidationError('요청이 너무 큽니다.')
    try:
        data=json.loads(request.body)
        if not isinstance(data,dict):raise ValueError
        return data
    except (ValueError,UnicodeError):raise ValidationError('올바른 요청이 필요합니다.')


@login_required
@never_cache
@require_GET
def status(request):
    from .live_notifications import live_summary
    after=request.GET.get('after')
    try:after=min(2**63-1,max(0,int(after))) if after is not None else None
    except ValueError:return JsonResponse({'error':'잘못된 알림 번호입니다.'},status=400)
    return JsonResponse(live_summary(request.user,after))


@login_required
@never_cache
@require_POST
def preferences(request):
    try:
        data=body(request)
        if any(type(data.get(k)) is not bool for k in ['popup','sound']):raise ValidationError('설정 값을 확인해 주세요.')
        NotificationPreference.objects.update_or_create(user=request.user,defaults={k:data[k] for k in ['popup','sound']})
    except ValidationError as e:return JsonResponse({'error':' '.join(e.messages)},status=400)
    return JsonResponse({'ok':True})


@login_required
@never_cache
@require_GET
def push_config(request):
    from .push import public_key
    key=public_key()
    return JsonResponse({'configured':bool(key),'public_key':key})


@login_required
@never_cache
@require_POST
def subscribe(request):
    from .push import validate_subscription,public_key
    if not public_key():return JsonResponse({'error':'서버의 웹 푸시 준비가 필요합니다.'},status=503)
    try:data=validate_subscription(body(request))
    except ValidationError as e:return JsonResponse({'error':' '.join(e.messages)},status=400)
    with transaction.atomic():
        sub,_=PushSubscription.objects.select_for_update().get_or_create(endpoint_hash=data['endpoint_hash'],defaults={
            **data,'user':request.user,'enabled':True})
        # A shared browser may change accounts. Never transfer queued messages.
        if sub.user_id!=request.user.pk or sub.p256dh!=data['p256dh'] or sub.auth!=data['auth']:
            PushDelivery.objects.filter(subscription=sub,finished_at=None).delete()
        for key,value in data.items():setattr(sub,key,value)
        sub.user=request.user;sub.enabled=True;sub.save()
    response=JsonResponse({'ok':True})
    # Allows server-side logout revocation even if browser JavaScript is interrupted.
    response.set_signed_cookie('xenosys_push_device',sub.endpoint_hash,max_age=31536000,
                               httponly=True,secure=settings.SESSION_COOKIE_SECURE,samesite='Lax')
    return response


@login_required
@never_cache
@require_POST
def unsubscribe(request):
    try:endpoint=body(request).get('endpoint','')
    except ValidationError as e:return JsonResponse({'error':' '.join(e.messages)},status=400)
    if not isinstance(endpoint,str):return JsonResponse({'error':'잘못된 구독입니다.'},status=400)
    PushSubscription.objects.filter(user=request.user,endpoint_hash=hashlib.sha256(endpoint.encode()).hexdigest()).update(enabled=False)
    return JsonResponse({'ok':True})


@login_required
@never_cache
@require_POST
def test_push(request):
    from django.utils import timezone
    from datetime import timedelta
    try:endpoint=body(request).get('endpoint','')
    except ValidationError as e:return JsonResponse({'error':' '.join(e.messages)},status=400)
    if not isinstance(endpoint,str):return JsonResponse({'error':'잘못된 구독입니다.'},status=400)
    sub=get_object_or_404(PushSubscription,user=request.user,enabled=True,
        endpoint_hash=hashlib.sha256(endpoint.encode()).hexdigest())
    if PushDelivery.objects.filter(subscription=sub,notice=None,created_at__gt=timezone.now()-timedelta(seconds=30)).exists():
        return JsonResponse({'error':'테스트 알림은 30초 후 다시 요청해 주세요.'},status=429)
    PushDelivery.objects.create(subscription=sub,next_attempt_at=timezone.now()+timedelta(seconds=10))
    from .push import worker_running
    text='10초 후 발송합니다. 창을 닫고 확인해 보세요.' if worker_running() else '10초 후 발송을 예약했지만 푸시 발송 프로그램이 응답하지 않습니다. RUN_LOCAL_NOTIFICATIONS 실행 창을 확인해 주세요.'
    return JsonResponse({'ok':True,'message':text})


@never_cache
@require_GET
def service_worker(request):
    path=settings.BASE_DIR/'workflow/static/workflow/notifications-sw.js'
    response=HttpResponse(path.read_text(),content_type='application/javascript')
    response['Service-Worker-Allowed']='/'
    return response


@login_required
@never_cache
@require_GET
def push_status(request):
    from .push import worker_running,public_key
    device=request.get_signed_cookie('xenosys_push_device',default='')
    sub=PushSubscription.objects.filter(user=request.user,endpoint_hash=device).first()
    job=PushDelivery.objects.filter(subscription=sub).order_by('-pk').first() if sub else None
    labels={'sent':'브라우저 푸시 서비스에 전달 완료 (PC 표시 여부는 알림 센터에서 확인)',
            'failed':'발송 실패. 실행 창의 연결 오류를 확인해 주세요.',
            'subscription_expired':'구독이 만료되었습니다. 웹 푸시를 다시 켜 주세요.',
            'expired':'대기 시간이 지나 발송을 종료했습니다.','skipped':'읽음 또는 계정·문서 상태 변경으로 발송하지 않았습니다.'}
    delivery=None
    if job:
        label=labels.get(job.result,'전송 대기' if not job.attempts else f'연결 오류로 재시도 대기 ({job.attempts}회 시도)')
        delivery={'label':label,'attempts':job.attempts,'finished':job.finished_at is not None}
    return JsonResponse({'configured':bool(public_key()),'subscribed':bool(sub and sub.enabled),
                         'worker_running':worker_running(),'last_delivery':delivery})
