"""Author's completion receipts are independent of accounting and bell reads."""
from django.db.models import Exists, OuterRef
from django.db.models.functions import Coalesce
from django.utils import timezone
from .models import Document, OwnerCompletionReceipt


def owner_completed(user):
    return Document.objects.filter(owner=user, status='approved').annotate(
        completion_stamp=Coalesce('leave_corrected_at', 'approved_at', 'reviewed_at', 'created_at')).annotate(
        completion_seen=Exists(OwnerCompletionReceipt.objects.filter(user=user,
            document_id=OuterRef('pk'), completion_stamp=OuterRef('completion_stamp'))))


def acknowledge_completion(user, document):
    if document.owner_id == user.pk and document.status == 'approved':
        OwnerCompletionReceipt.objects.update_or_create(user=user, document=document, defaults={
            'completion_stamp': document.leave_corrected_at or document.approved_at or document.reviewed_at or document.created_at,
            'viewed_at': timezone.now()})
