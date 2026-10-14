from .forms import DocumentForm
from .models import Document
from .calendars import month_grid


def quick_form(user, kind, today):
    form = DocumentForm(prefix=f'home_{kind}', instance=Document(owner=user, kind=kind),
                        initial={'kind': kind, 'start_date': today, 'end_date': today, 'recipient': user.pk,
                                 'quantity': 1, 'urgency': 'normal', 'leave_type': 'annual'})
    form.fields['reason'].widget.attrs.update(rows=2)
    return form


def progress_stages(doc):
    if not doc:
        return []
    steps = [{'label': '기안', 'person': doc.owner.first_name, 'done': bool(doc.submitted_at), 'time': doc.submitted_at},
             {'label': '검토', 'person': doc.reviewer.first_name if doc.reviewer else '—',
              'done': bool(doc.reviewed_at), 'time': doc.reviewed_at}]
    if doc.kind != 'stock':
        steps.append({'label': '승인', 'person': doc.approver.first_name if doc.approver else '—',
                      'done': bool(doc.approved_at), 'time': doc.approved_at})
    if doc.kind != 'leave':
        if doc.kind == 'stock':
            ordered = doc.shipment in ['ordered', 'received']
            steps.append({'label': '발주', 'person': '발주완료' if ordered else '발주대기', 'done': ordered, 'time': None})
        steps.append({'label': '입고' if doc.kind == 'stock' else '배송', 'person': doc.shipment_label,
                      'done': doc.shipment == 'received', 'time': None})
    else:
        steps.append({'label': '완료', 'person': doc.status_label, 'done': doc.status == 'approved', 'time': None})
    if doc.status not in ['rejected', 'cancelled']:
        for step in steps:
            if not step['done']:
                step['current'] = True
                break
    return steps


def today_schedules(user, today):
    grid = month_grid(today.year, today.month, user)
    day = next(cell for week in grid['weeks'] for cell in week if cell['date'] == today)
    return day['events'][:4]
