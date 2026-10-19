from datetime import timedelta, time
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import AnnualBalance, Audit, Document, DocumentCounter, Notice, Profile, RANKS
from .people import validate_approval_person
from .notifications import can_notify

def visible_documents(user):
    p = user.profile
    if p.is_representative:
        if p.representative_view_documents:
            return Document.objects.exclude(status__in=['draft','deleted'])
        return Document.objects.filter(Q(owner=user)|Q(reviewer=user)|Q(approver=user)|Q(recipient=user)).exclude(status='deleted')
    if p.manage_system:
        return Document.objects.all()
    related = Q(owner=user) | Q(reviewer=user) | Q(approver=user)
    related |= Q(recipient=user, status='approved', kind__in=['office', 'stock'])
    if p.view_accounting:
        related |= Q(status='approved')
    if p.procure:
        related |= Q(kind='stock', status='approved')
    return Document.objects.filter(related).exclude(status='deleted').exclude(Q(status='draft') & ~Q(owner=user))

def audit(actor, event, document=None, detail='', target=None):
    return Audit.objects.create(actor=actor, event=event, document=document, detail=detail, target=target)

def notify(document, users, text, stage, stages_by_user=None):
    stages_by_user = stages_by_user or {}
    ids = {u.pk for u in users if u and u.is_active and u.profile.approved and
           can_notify(u, document, stages_by_user.get(u.pk, stage))}
    kind = {'leave': '휴가원', 'office': '구매요청서', 'stock': '생산 재고 요청서'}[document.kind]
    subject = f'{document.owner.first_name or document.owner.username} - {document.owner.profile.rank} - {kind}'
    Notice.objects.bulk_create([Notice(user_id=i, document=document, text=text, subject=subject,
        stage=stages_by_user.get(i, stage)) for i in ids])

def accountants(document):
    query = Q(profile__view_accounting=True)
    query |= Q(profile__manage_leave=True) if document.kind == 'leave' else Q(profile__procure=True)
    from django.contrib.auth import get_user_model
    return list(get_user_model().objects.filter(query, is_active=True, profile__approved=True))

def weekdays(start, end):
    if not start or not end or end < start:
        raise ValidationError('시작일과 종료일을 확인해 주세요.')
    days = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        if day == end:
            break
        day += timedelta(days=1)
    return days

def allocations(document):
    if document.kind != 'leave':
        return {}
    if document.leave_type not in dict(Document.LEAVES):
        raise ValidationError('휴가 종류를 선택해 주세요.')
    if document.leave_type == 'annual':
        days = weekdays(document.start_date, document.end_date)
        if not days:
            raise ValidationError('토요일·일요일만 포함된 기간에는 신청할 수 없습니다.')
        result = {}
        for day in days:
            result[str(day.year)] = str(Decimal(result.get(str(day.year), '0')) + 1)
        return result
    if not document.start_date or document.start_date.weekday() >= 5:
        raise ValidationError('반차·외출은 평일을 선택해 주세요.')
    if not document.start_time or not document.end_time or document.end_time <= document.start_time:
        raise ValidationError('종료 시간은 시작 시간보다 늦어야 합니다.')
    if document.end_date != document.start_date:
        raise ValidationError('반차·외출은 한 기안에 하루만 신청할 수 있습니다.')
    return {str(document.start_date.year): '0.25' if document.leave_type == 'outing' else '0.5'}

def leave_amount(document):
    return sum((Decimal(x) for x in allocations(document).values()), Decimal('0'))

def check_overlap(document):
    from .manual_leave import check_manual_overlap
    check_manual_overlap(document)
    days = set(weekdays(document.start_date, document.end_date))
    existing = Document.objects.filter(owner=document.owner, kind='leave', status__in=['review', 'approve', 'approved'],
        start_date__lte=document.end_date, end_date__gte=document.start_date).exclude(pk=document.pk)
    for old in existing:
        if not days.intersection(weekdays(old.start_date, old.end_date)):
            continue
        overlap = document.leave_type == 'annual' or old.leave_type == 'annual'
        if not overlap:
            overlap = document.start_time < old.end_time and old.start_time < document.end_time
        if overlap:
            period = f'{old.start_date:%m/%d}~{old.end_date:%m/%d}' if old.leave_type == 'annual' else f'{old.start_date:%m/%d} {old.start_time:%H:%M}~{old.end_time:%H:%M}'
            raise ValidationError(f'해당 시간에 신청된 휴가가 있습니다: {period} ({old.get_leave_type_display()})')

def make_title(document):
    name = document.owner.first_name or document.owner.username
    if document.kind == 'leave':
        period = f'{document.start_date:%Y.%m.%d}' if document.start_date else '날짜 미입력'
        if document.end_date and document.end_date != document.start_date:
            period += f'~{document.end_date:%m.%d}'
        return f'휴가원 / {name} / {period}'
    prefix = '재고요청' if document.kind == 'stock' else '구매요청'
    return f'{prefix} / {name} / {document.product or "품목 미입력"}'

@transaction.atomic
def save_document(document, actor, submit=False):
    from .models import RegulationLock
    RegulationLock.objects.select_for_update().get_or_create(pk=1)
    # Serializes submissions by one employee, including overlap checks.
    actor.profile = Profile.objects.select_for_update().get(user=actor)
    if actor.profile.is_representative:
        raise PermissionDenied('회사 대표 계정은 현재 조회 전용입니다.')
    if document.pk:
        current = Document.objects.select_for_update().get(pk=document.pk)
        if current.owner_id != actor.pk or current.status != 'draft':
            raise PermissionDenied('제출된 기안은 수정할 수 없습니다.')
    if document.owner_id != actor.pk:
        raise PermissionDenied
    if document.kind == 'stock':
        # Stock requests do not have prices, a shopping URL or final approver.
        document.unit_price, document.url = Decimal('0'), ''
    if document.approval_mode != 'base' or document.kind == 'stock':
        from .delegation import resolve_route
        preliminary = resolve_route(document.kind, actor.profile.rank, document.total_price, owner=actor, mode=document.approval_mode)
        if document.kind == 'stock' and not preliminary.get('stock_final_approval'):
            document.approver = None
    if not submit:
        validate_approval_person(document.reviewer)
        validate_approval_person(document.approver)
    document.title = make_title(document)
    if submit:
        if document.kind not in dict(Document.KINDS):
            raise ValidationError('문서 종류를 선택해 주세요.')
        from .delegation import resolve_route, validate_route_people
        route = resolve_route(document.kind, actor.profile.rank, document.total_price, owner=actor, mode=document.approval_mode)
        validate_route_people(document, route)
        route.update(reviewer_id=document.reviewer_id, approver_id=document.approver_id,
            reviewer_rank=document.reviewer.profile.rank if document.reviewer else None,
            approver_rank=document.approver.profile.rank if document.approver else None,
            total=str(document.total_price))
        document.route_snapshot = route
        for person in (document.reviewer, document.approver, document.recipient):
            if person and Profile.objects.filter(user=person, representative_slot=1).exists():
                raise ValidationError('회사 대표 계정은 결재 담당자·수령자로 지정할 수 없습니다.')
            if person and (not person.is_active or not person.profile.approved):
                raise ValidationError('활성화된 직원만 선택할 수 있습니다.')
        if document.kind == 'leave':
            if not document.reason.strip():
                raise ValidationError('휴가 신청 사유를 입력해 주세요.')
            allocations(document)
            check_overlap(document)
        elif not document.product or document.quantity < 1:
            raise ValidationError('품목과 1개 이상의 수량을 입력해 주세요.')
        elif document.kind == 'office' and document.unit_price <= 0:
            raise ValidationError('0원 초과 단가를 입력해 주세요.')
        elif document.kind == 'office' and not document.url:
            raise ValidationError('사무·사내용품의 구매 사이트 링크를 입력해 주세요.')
        if document.kind != 'leave' and not document.recipient:
            document.recipient = actor
        day = timezone.localdate()
        counter, _ = DocumentCounter.objects.get_or_create(day=day)
        counter = DocumentCounter.objects.select_for_update().get(pk=counter.pk)
        counter.value += 1
        counter.save(update_fields=['value'])
        document.number = f'DOC-{day:%Y%m%d}-{counter.value:04d}'
        document.status = 'review' if document.review_required else 'approve'
        document.submitted_at = timezone.now()
    document.save()
    audit(actor, '기안 제출' if submit else '임시저장', document)
    if submit and document.route_snapshot.get('self_complete'):
        document = act_on_document(document.pk, actor, 'approve')
        audit(actor, '본인 전결', document, f'규정: {document.route_snapshot["name"]} / 버전 {document.route_snapshot["version"]}')
    elif submit:
        person = document.reviewer if document.review_required else document.approver
        stage = '검토대기' if document.review_required else '승인대기'
        notify(document, [person], f'{actor.first_name}님의 {stage} 요청이 도착했습니다.', stage)
    return document

def adjust_charges(document, sign):
    from .annual_grants import ensure_balance
    for year, amount in document.allocations.items():
        Profile.objects.select_for_update().get(user=document.owner)
        balance = ensure_balance(document.owner, int(year))
        balance.used += Decimal(amount) * sign
        balance.save(update_fields=['used'])

@transaction.atomic
def act_on_document(pk, actor, action, reason='', new_person=None):
    from .models import RegulationLock
    RegulationLock.objects.select_for_update().get_or_create(pk=1)
    actor.profile = Profile.objects.get(user=actor)
    if actor.profile.is_representative:
        raise PermissionDenied('회사 대표 계정은 현재 조회 전용입니다.')
    document = Document.objects.select_for_update().get(pk=pk)
    p = actor.profile
    if action in ['reject', 'cancel_review', 'cancel_approval', 'reassign'] and not reason.strip():
        raise ValidationError('처리 사유를 입력해 주세요.')
    now = timezone.now()
    if action == 'review':
        if not document.review_required or document.status != 'review' or document.reviewer_id != actor.pk:
            raise PermissionDenied
        document.reviewed_at = now
        if not document.final_approval_required:
            document.status, document.approved_at = 'approved', now
            audit(actor, '재고 요청 검토 완료', document)
            notify(document, [document.owner] + accountants(document), '생산 재고 요청의 검토가 완료되었습니다. 발주 담당자에게 전달했습니다.', '검토완료')
        else:
            document.status = 'approve'
            audit(actor, '검토 승인', document)
            approver_stage = '검토완료 · 승인대기' if document.owner_id == document.approver_id else '승인대기'
            notify(document, [document.owner, document.approver], '검토가 완료되었습니다. 최종 승인을 기다리고 있습니다.',
                   '검토완료', {document.approver_id: approver_stage})
    elif action == 'approve':
        if not document.final_approval_required or document.status != 'approve' or document.approver_id != actor.pk:
            raise PermissionDenied
        if document.kind == 'leave':
            # Serialize against off-system registrations before checking their dates.
            Profile.objects.select_for_update().get(user=document.owner)
            from .manual_leave import check_manual_overlap
            check_manual_overlap(document)
            document.allocations = allocations(document)
            document.charged = leave_amount(document)
            adjust_charges(document, 1)
        document.status, document.approved_at = 'approved', now
        audit(actor, '최종 승인', document, f'연차 {document.charged}일 차감' if document.kind == 'leave' else '')
        notify(document, [document.owner] + accountants(document), '최종 승인되었습니다.', '승인완료')
    elif action == 'reject':
        if not ((document.status == 'review' and document.reviewer_id == actor.pk) or
                (document.final_approval_required and document.status == 'approve' and document.approver_id == actor.pk)):
            raise PermissionDenied
        document.status = 'rejected'
        audit(actor, '반려', document, reason)
        notify(document, [document.owner], f'기안이 반려되었습니다. 사유: {reason[:100]}', '반려')
    elif action == 'cancel_review':
        expected = 'approve' if document.final_approval_required else 'approved'
        if not document.review_required or document.status != expected or document.reviewer_id != actor.pk:
            raise PermissionDenied
        document.status = 'cancelled'
        audit(actor, '재고 요청 검토 취소' if document.kind == 'stock' else '검토 승인 취소', document, reason)
        recipients = [document.owner] + (accountants(document) if document.kind == 'stock' else [])
        notify(document, recipients, f'검토가 취소되었습니다. 사유: {reason[:100]}', '검토취소')
    elif action == 'cancel_approval':
        if not document.final_approval_required or document.status != 'approved' or document.approver_id != actor.pk:
            raise PermissionDenied
        if document.kind == 'leave':
            adjust_charges(document, -1)
        document.status = 'cancelled'
        audit(actor, '최종 승인 취소', document, f'{reason}\n연차 {document.charged}일 복원' if document.kind == 'leave' else reason)
        notify(document, [document.owner] + accountants(document), f'최종 승인이 취소되었습니다. 사유: {reason[:100]}', '승인취소')
    elif action == 'delete':
        if document.owner_id != actor.pk or not (document.status in ['draft', 'review', 'rejected'] or (document.status == 'approve' and not document.review_required)):
            raise PermissionDenied
        previous_status = document.status
        document.status = 'deleted'
        audit(actor, '기안 삭제', document, f'삭제 전 상태: {previous_status} / 기존 결재·반려 이력 보존')
    elif action == 'place':
        if not p.procure or document.status != 'approved' or document.kind == 'leave' or document.shipment:
            raise PermissionDenied
        document.shipment = 'shipping' if document.kind == 'office' else 'ordered'
        audit(actor, '구매 처리' if document.kind == 'office' else '발주 처리', document)
        notify(document, [document.owner, document.recipient], '구매·발주가 완료되었습니다. 물품을 받으면 수령을 확인해 주세요.',
               '배송중' if document.kind == 'office' else '입고대기')
    elif action == 'receive':
        if document.status != 'approved' or document.recipient_id != actor.pk or document.shipment not in ['shipping', 'ordered']:
            raise PermissionDenied
        document.shipment = 'received'
        audit(actor, '배송완료' if document.kind == 'office' else '입고완료', document)
        notify(document, [document.owner] + accountants(document), '물품 수령이 확인되었습니다.',
               '배송완료' if document.kind == 'office' else '입고완료')
    elif action == 'reassign':
        if not p.manage_system or document.status not in ['review', 'approve']:
            raise PermissionDenied
        if not new_person or not new_person.is_active or not new_person.profile.approved:
            raise ValidationError('활성화된 담당자를 선택해 주세요.')
        validate_approval_person(new_person)
        field = 'reviewer' if document.status == 'review' else 'approver'
        old = getattr(document, field)
        from .delegation import candidate_ranks, rank_index
        route = {'author_rank': document.owner.profile.rank, 'skip_review': False,
            'reviewer_ranks': RANKS[1:], 'approver_ranks': RANKS[1:], **document.route_snapshot}
        review_rank = route.get('reviewer_rank') or (document.reviewer.profile.rank if document.reviewer else None)
        if new_person.profile.rank not in candidate_ranks(route, field, review_rank):
            raise ValidationError('새 담당자가 전결규정 또는 직급 조건을 충족하지 않습니다.')
        if field == 'reviewer' and document.approver and rank_index(new_person.profile.rank) > rank_index(route.get('approver_rank') or document.approver.profile.rank):
            raise ValidationError('검토자는 승인자보다 높은 직급으로 지정할 수 없습니다.')
        setattr(document, field, new_person)
        document.route_snapshot = {**route, field + '_id': new_person.pk, field + '_rank': new_person.profile.rank}
        audit(actor, '담당자 변경', document, f'{old.first_name} → {new_person.first_name}\n{reason}')
        notify(document, [document.owner, new_person], '대기 중인 결재 담당자가 변경되었습니다.',
               ('검토대기' if document.status == 'review' else '승인대기') + ' · 담당자변경')
    else:
        raise ValidationError('지원하지 않는 처리입니다.')
    document.save()
    return document

@transaction.atomic
def edit_balance(actor, user, year, field, value, reason):
    if not actor.profile.manage_leave:
        raise PermissionDenied
    if not reason.strip() or field not in ['total', 'used', 'remaining']:
        raise ValidationError('수정 항목과 사유를 확인해 주세요.')
    from .annual_grants import ensure_balance
    Profile.objects.select_for_update().get(user=user)
    balance = ensure_balance(user, year)
    before = f'총 {balance.total} / 사용 {balance.used} / 잔여 {balance.remaining}'
    if field == 'remaining':
        balance.used = balance.total - value
    else:
        setattr(balance, field, value)
    balance.grant_initialized = True
    if field == 'total':
        balance.total_manual = True
    balance.save()
    after = f'총 {balance.total} / 사용 {balance.used} / 잔여 {balance.remaining}'
    audit(actor, f'{year}년 연차 수정', detail=f'{before} → {after}\n사유: {reason}', target=user)
    return balance
