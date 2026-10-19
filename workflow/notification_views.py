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
    return JsonResponse({'ok':True,'message':'10초 후 발송합니다. 창을 닫고 확인해 보세요. 발송 프로그램이 실행 중이어야 합니다.'})


@never_cache
@require_GET
def service_worker(request):
    path=settings.BASE_DIR/'workflow/static/workflow/notifications-sw.js'
    response=HttpResponse(path.read_text(),content_type='application/javascript')
    response['Service-Worker-Allowed']='/'
    return response
