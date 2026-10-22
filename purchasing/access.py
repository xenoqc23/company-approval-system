from django.core.exceptions import PermissionDenied
from django.db.models import Q
from .models import PurchasePolicy,PurchaseRequest,PurchaseReport


def active(user):
    return user.is_authenticated and user.is_active and user.profile.approved


def policy():return PurchasePolicy.objects.filter(pk=1).first()
def is_admin(user):return active(user) and user.profile.manage_system and not user.profile.is_representative

def is_finance(user):
    p=policy()
    return bool(active(user) and not user.profile.is_representative and p and p.finance.filter(pk=user.pk).exists())


def requests_for(user):
    if not active(user):return PurchaseRequest.objects.none()
    if is_admin(user):return PurchaseRequest.objects.all()
    roles=Q(owner=user)|Q(reviewer=user)|Q(approver=user)|Q(director=user)
    if is_finance(user):roles|=Q(status__in=['ready','ceo','allowed','denied','hold','paid','received'])
    if user.profile.is_representative:roles|=Q(current_report__representative=user)
    return PurchaseRequest.objects.filter(roles).distinct()


def reports_for(user):
    if not active(user):return PurchaseReport.objects.none()
    if is_admin(user) or is_finance(user):return PurchaseReport.objects.all()
    return PurchaseReport.objects.filter(representative=user) if user.profile.is_representative else PurchaseReport.objects.none()


def require_finance(user):
    if not is_finance(user):raise PermissionDenied('구매 취합 담당자만 처리할 수 있습니다.')


def notices_for(user):
    from .models import PurchaseNotice
    return PurchaseNotice.objects.filter(user=user).filter(
        Q(request__in=requests_for(user))|Q(report__in=reports_for(user)))
