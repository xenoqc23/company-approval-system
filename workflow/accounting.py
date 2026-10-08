from django.db.models import Count, Max
from django.db.models.functions import Coalesce
from django.utils import timezone
from .models import AccountingReadState, Document
from .services import visible_documents


def accounting_tabs(user, read_kind=None):
    cutoff = timezone.now()
    if read_kind in ['all', *dict(Document.KINDS)]:
        kinds = dict(Document.KINDS) if read_kind == 'all' else [read_kind]
        for kind in kinds:
            state, _ = AccountingReadState.objects.get_or_create(
                user=user, kind=kind, defaults={'seen_until': cutoff})
            # Parallel requests cannot move the read marker backwards.
            AccountingReadState.objects.filter(pk=state.pk, seen_until__lt=cutoff).update(seen_until=cutoff)
    seen = dict(AccountingReadState.objects.filter(user=user).values_list('kind', 'seen_until'))
    stats = {row['kind']: row for row in visible_documents(user).filter(status='approved').order_by().values('kind').annotate(
        total=Count('pk'), latest=Max(Coalesce('approved_at', 'reviewed_at', 'created_at')))}
    tabs = []
    for kind, label in [('leave', '휴가원'), ('office', '구매요청서'), ('stock', '생산 재고 요청')]:
        row = stats.get(kind)
        unread = bool(row and (kind not in seen or row['latest'] > seen[kind]))
        tabs.append({'key': kind, 'label': label, 'count': row['total'] if row else 0, 'unread': unread})
    return [{'key': 'all', 'label': '전체', 'count': sum(tab['count'] for tab in tabs),
             'unread': any(tab['unread'] for tab in tabs)}, *tabs]
