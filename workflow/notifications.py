from django.db.models import Q
from .models import Notice


def accounting_completion(document, stage):
    return document.status == 'approved' and stage in ['승인완료', '배송완료', '휴가정정']


def can_notify(user, document, stage):
    if document.kind == 'stock':
        # Financial/procurement privileges alone never subscribe an employee to stock records.
        participants = [document.owner_id, document.reviewer_id]
        if document.final_approval_required:
            participants += [document.approver_id, document.representative_id]
        return user.pk in participants
    if document.progressive and stage in ['검토대기','승인대기','대표결재대기'] and user.pk in [document.reviewer_id,document.approver_id,document.representative_id]:return True
    return (not user.profile.view_accounting or
            (document.kind != 'stock' and
             (document.owner_id == user.pk or accounting_completion(document, stage))))


def visible_notices(user):
    notices = Notice.objects.filter(user=user).exclude(document__status='deleted')
    stock_roles = Q(document__kind='stock') & (Q(document__owner=user) | Q(document__reviewer=user) |
        Q(document__approver=user) | Q(document__representative=user))
    notices = notices.filter(~Q(document__kind='stock') | stock_roles)
    if user.profile.view_accounting:
        completed = Q(stage__in=['승인완료', '배송완료', '휴가정정'])
        assigned_progressive = Q(document__route_snapshot__progressive=True,stage__in=['검토대기','승인대기','대표결재대기']) & (
            Q(document__reviewer=user)|Q(document__approver=user)|Q(document__representative=user))
        notices = notices.filter(Q(document__owner=user) | assigned_progressive | (Q(document__status='approved') & completed) | stock_roles)
    return notices
