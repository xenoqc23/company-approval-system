from django.db.models import Q
from .models import Notice


def accounting_completion(document, stage):
    return document.status == 'approved' and (
        stage in ['승인완료', '배송완료'] or
        (document.kind == 'stock' and stage in ['검토완료', '입고완료']))


def can_notify(user, document, stage):
    return (not user.profile.view_accounting or document.owner_id == user.pk or
            accounting_completion(document, stage))


def visible_notices(user):
    notices = Notice.objects.filter(user=user)
    if user.profile.view_accounting:
        completed = Q(stage__in=['승인완료', '배송완료']) | Q(
            document__kind='stock', stage__in=['검토완료', '입고완료'])
        notices = notices.filter(Q(document__owner=user) | (Q(document__status='approved') & completed))
    return notices
