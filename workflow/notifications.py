from django.db.models import Q
from .models import Notice


def accounting_completion(document, stage):
    return document.status == 'approved' and stage in ['승인완료', '배송완료', '휴가정정']


def can_notify(user, document, stage):
    if document.progressive and stage in ['검토대기','승인대기','대표결재대기'] and user.pk in [document.reviewer_id,document.approver_id,document.representative_id]:return True
    if document.kind == 'stock' and document.final_approval_required:
        return (not user.profile.view_accounting or user.pk in [document.owner_id, document.reviewer_id, document.approver_id, document.representative_id]
                or (user.profile.procure and accounting_completion(document, stage)))
    return (not user.profile.view_accounting or
            (document.kind != 'stock' and
             (document.owner_id == user.pk or accounting_completion(document, stage))))


def visible_notices(user):
    notices = Notice.objects.filter(user=user).exclude(document__status='deleted')
    if user.profile.view_accounting:
        stock_roles = Q(document__owner=user) | Q(document__reviewer=user) | Q(document__approver=user)
        if user.profile.procure:
            stock_roles |= Q(document__status='approved', stage__in=['승인완료', '배송완료', '휴가정정'])
        regulated_stock = Q(document__kind='stock', document__route_snapshot__stock_final_approval=True) & stock_roles
        notices = notices.filter(~Q(document__kind='stock') | regulated_stock)
        completed = Q(stage__in=['승인완료', '배송완료', '휴가정정'])
        assigned_progressive = Q(document__route_snapshot__progressive=True,stage__in=['검토대기','승인대기','대표결재대기']) & (
            Q(document__reviewer=user)|Q(document__approver=user)|Q(document__representative=user))
        notices = notices.filter(Q(document__owner=user) | assigned_progressive | (Q(document__status='approved') & completed) | regulated_stock)
    return notices
