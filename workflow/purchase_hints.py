"""Minimal cross-department purchase metadata; full documents remain access-controlled."""
import re
import unicodedata
from django.contrib.auth.decorators import login_required
from django.db.models import Case, When, Value, IntegerField, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from .models import Document


def normalize_product(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())[:180]


@login_required
@require_GET
def hints(request):
    q = request.GET.get('q', '').strip()[:120]
    term = normalize_product(q)
    rows = Document.objects.none()
    if len(term) >= 2:
        tokens = [normalize_product(t) for t in re.split(r'\s+', q) if len(normalize_product(t)) >= 2][:5]
        matching = Q(product_search__contains=term)
        for token in tokens:
            matching |= Q(product_search__contains=token)
        rows = Document.objects.filter(kind__in=['office', 'stock'], purchase_private=False,
            status__in=['review', 'approve', 'executive', 'approved']).filter(matching)
        excluded = request.GET.get('exclude', '')
        if excluded.isascii() and excluded.isdigit() and len(excluded) <= 18:
            rows = rows.exclude(pk=int(excluded))
        # Progress before received; every year participates (no historical cutoff).
        rows = rows.select_related('owner__profile').annotate(priority=Case(
            When(shipment='received', then=Value(1)), default=Value(0), output_field=IntegerField())).order_by(
                'priority', '-submitted_at', '-created_at', '-pk')
    count = rows.count()
    results = [dict(product=d.product, department=d.owner.profile.department, quantity=d.quantity,
                    requested=(d.submitted_at or d.created_at).date().isoformat(),
                    status=d.shipment_label if d.status == 'approved' else d.get_status_display()) for d in rows[:8]]
    response = JsonResponse(dict(results=results, count=count))
    response['Cache-Control'] = 'private, no-store'
    return response
