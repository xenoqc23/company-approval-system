from django.core.exceptions import PermissionDenied
from django.db.models import Q
from .models import PurchasePolicy,PurchaseRequest,PurchaseReport,PurchasePermission


def active(user):
    return user.is_authenticated and user.is_active and user.profile.approved


def policy():return PurchasePolicy.objects.filter(pk=1).first()
def is_admin(user):return active(user) and user.profile.manage_system and not user.profile.is_representative

def is_finance(user):
    p=policy()
    return bool(active(user) and not user.profile.is_representative and p and p.finance.filter(pk=user.pk).exists())


def is_confirmer(user):
    return bool(active(user) and not user.profile.is_representative and PurchasePermission.objects.filter(user=user,view_completed=True).exists())


def confirmers():
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(is_active=True,profile__approved=True,profile__representative_slot__isnull=True,purchase_permission__view_completed=True).select_related('profile')


def checker_assigned(user,d):
    return is_confirmer(user) and (d.purchase_checker_id is None or d.purchase_checker_id==user.pk)


def checker_requests(user):
    if not is_confirmer(user):return PurchaseRequest.objects.none()
    return PurchaseRequest.objects.filter(Q(purchase_checker=user)|Q(purchase_checker__isnull=True)).filter(
        status__in=['ready','supplement','reapproval','ceo','allowed','denied','hold','paid','received']).exclude(owner=user)


def request_confirmers(d):
    people=confirmers().exclude(pk=d.owner_id)
    return people.filter(pk=d.purchase_checker_id) if d.purchase_checker_id else people


def finance_assigned(user,d):
    if not is_finance(user):return False
    if d.confirmed_at:return user.pk in d.purchase_route.get('collector_ids',[])
    # Earlier test reports already in progress stay with their original report author.
    return bool(d.current_report_id and d.current_report.created_by_id==user.pk)


def finance_requests(user):
    if not is_finance(user):return PurchaseRequest.objects.none()
    ids=[d.pk for d in PurchaseRequest.objects.exclude(confirmed_at=None).only('pk','purchase_route') if user.pk in d.purchase_route.get('collector_ids',[])]
    return PurchaseRequest.objects.filter(Q(pk__in=ids)|Q(current_report__created_by=user)).exclude(status__in=['draft','review','approval','director','rejected','cancelled'])


def can_view_purchase(user,d):
    if not active(user) or d.owner_id==user.pk:return False
    if checker_assigned(user,d) and (not d.confirmed_at or d.confirmed_by_id==user.pk):return d.status not in ['draft','review','approval','director','rejected']
    if finance_assigned(user,d):return True
    return bool(user.profile.is_representative and d.current_report_id and d.current_report.representative_id==user.pk)


def requests_for(user):
    if not active(user):return PurchaseRequest.objects.none()
    if is_admin(user):return PurchaseRequest.objects.all()
    roles=Q(owner=user)|Q(reviewer=user)|Q(approver=user)|Q(director=user)
    if is_confirmer(user):roles|=Q(pk__in=checker_requests(user).values('pk'))
    if is_finance(user):
        # JSON membership differs between SQLite and MariaDB: keep the same explicit participant check on both.
        roles|=Q(pk__in=finance_requests(user).values('pk'))
    if user.profile.is_representative:roles|=Q(current_report__representative=user)
    return PurchaseRequest.objects.filter(roles).distinct()


def reports_for(user):
    if not active(user):return PurchaseReport.objects.none()
    if is_finance(user):return PurchaseReport.objects.filter(created_by=user)
    return PurchaseReport.objects.filter(representative=user) if user.profile.is_representative else PurchaseReport.objects.none()


def require_finance(user):
    if not is_finance(user):raise PermissionDenied('취합·보고 담당자만 처리할 수 있습니다.')


def notices_for(user):
    from .models import PurchaseNotice
    return PurchaseNotice.objects.filter(user=user).filter(
        Q(request__in=requests_for(user))|Q(report__in=reports_for(user)))
