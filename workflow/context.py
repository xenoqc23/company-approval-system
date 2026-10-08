from django.utils import timezone
from .models import AnnualBalance, Notice

def shell(request):
    if not request.user.is_authenticated:
        return {}
    year = timezone.localdate().year
    balance = AnnualBalance.objects.filter(user=request.user, year=year).first()
    return {'profile': request.user.profile, 'balance': balance,
            'remaining': balance.remaining if balance else 0,
            'used_percent': max(0, min(100, float(balance.used / balance.total * 100))) if balance and balance.total > 0 else 0,
            'unread': Notice.objects.filter(user=request.user, read=False).count(), 'current_year': year}
