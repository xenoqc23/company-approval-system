"""CEO work lists follow current items; receipt counts never decide completion."""
from django.db.models import Exists, OuterRef
from .models import PurchaseRequest


def with_open_items(reports):
    current = PurchaseRequest.objects.filter(current_report_id=OuterRef('pk'), status__in=[
        'ceo', 'hold', 'reapproval', 'allowed', 'ready', 'supplement'])
    return reports.annotate(has_open_items=Exists(current))
