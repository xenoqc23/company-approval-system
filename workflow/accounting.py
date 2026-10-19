from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from .models import DocumentReceipt, Document


def accounting_documents(user):
    from .services import visible_documents
    return visible_documents(user).filter(status='approved').annotate(
        approval_stamp=Coalesce('approved_at', 'reviewed_at', 'created_at')).annotate(
        accounting_seen=Exists(DocumentReceipt.objects.filter(
            user=user, document_id=OuterRef('pk'), approval_stamp=OuterRef('approval_stamp'))))


def accounting_tabs(user, read_kind=None):
    # Opening a category never acknowledges individual documents.
    stats = {row['kind']: row for row in accounting_documents(user).order_by().values('kind').annotate(
        total=Count('pk'), unread_count=Count('pk', filter=Q(accounting_seen=False)))}
    tabs=[]
    for kind,label in [('leave','휴가원'),('office','구매요청서'),('stock','생산 재고 요청')]:
        row=stats.get(kind,{})
        tabs.append(dict(key=kind,label=label,count=row.get('total',0),
                         unread_count=row.get('unread_count',0),unread=bool(row.get('unread_count',0))))
    return [dict(key='all',label='전체',count=sum(t['count'] for t in tabs),
                 unread_count=sum(t['unread_count'] for t in tabs),unread=any(t['unread'] for t in tabs)),*tabs]


def acknowledge_document(user,document):
    if not user.profile.view_accounting or document.status != 'approved':
        return
    DocumentReceipt.objects.update_or_create(user=user,document=document,defaults={
        'approval_stamp':document.approved_at or document.reviewed_at or document.created_at,
        'viewed_at':timezone.now()})
