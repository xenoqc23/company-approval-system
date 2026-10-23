from django.conf import settings
from django.utils import timezone
from .models import AnnualBalance
from .live_notifications import live_summary


def shell(request):
    if not request.user.is_authenticated:return {}
    year=timezone.localdate().year
    balance=AnnualBalance.objects.filter(user=request.user,year=year).first()
    summary=live_summary(request.user)
    return dict(profile=request.user.profile,balance=balance,remaining=balance.remaining if balance else 0,
                used_percent=max(0,min(100,float(balance.used/balance.total*100))) if balance and balance.total>0 else 0,
                nav_waiting=summary['waiting'],unread=summary['unread'],current_year=year,
                completed_unread=summary['completed_unread'],accounting_unread=summary['accounting_unread'],notification_seed={**summary,'webpush_enabled':settings.WEBPUSH_ENABLED,'storage_scope':settings.SESSION_COOKIE_NAME if settings.INTEGRATED_PURCHASES else ''},
                webpush_enabled=settings.WEBPUSH_ENABLED)
