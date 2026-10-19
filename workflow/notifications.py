from django.db.models import Q
from .models import Notice


def accounting_completion(document, stage):
    return document.status == 'approved' and stage in ['승인완료', '배송완료']


def can_notify(user, document, stage):
    if document.kind == 'stock' and document.final_approval_required:
        return (not user.profile.view_accounting or user.pk in [document.owner_id, document.reviewer_id, document.approver_id, document.representative_id]
                or (user.profile.procure and accounting_completion(document, stage)))
    return (not user.profile.view_accounting or
            (document.kind != 'stock' and
             (document.owner_id == user.pk or accounting_completion(document, stage))))


def visible_notices(user):
    notices = Notice.objects.filter(user=user)
    if user.profile.view_accounting:
        stock_roles = Q(document__owner=user) | Q(document__reviewer=user) | Q(document__approver=user)
        if user.profile.procure:
            stock_roles |= Q(document__status='approved', stage__in=['승인완료', '배송완료'])
        regulated_stock = Q(document__kind='stock', document__route_snapshot__stock_final_approval=True) & stock_roles
        notices = notices.filter(~Q(document__kind='stock') | regulated_stock)
        completed = Q(stage__in=['승인완료', '배송완료'])
        notices = notices.filter(Q(document__owner=user) | (Q(document__status='approved') & completed) | regulated_stock)
    return notices
