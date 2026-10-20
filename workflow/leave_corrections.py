"""Atomic, revision-checked corrections of approved leave; approval history is immutable."""
from datetime import date
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from .models import Document, Profile, RegulationLock, LeaveCorrection

FIELDS = ('leave_type', 'start_date', 'end_date', 'start_time', 'end_time')


def validated_fields(values):
    fields = {key: values.get(key) for key in FIELDS}
    for key in ('start_date', 'end_date'):
        day = fields[key]
        if not isinstance(day, date) or not 2000 <= day.year <= 2100:
            raise ValidationError('사용 날짜는 2000~2100년으로 입력해 주세요.')
    if (fields['end_date'] - fields['start_date']).days > 366:
        raise ValidationError('정정 기간은 한 번에 366일 이내로 입력해 주세요.')
    if fields['leave_type'] == 'annual':
        fields['start_time'] = fields['end_time'] = None
    from .services import allocations
    allocations(Document(kind='leave', **fields))
    return fields


def snapshot(doc):
    return {**{key: getattr(doc, key).isoformat() if isinstance(getattr(doc, key), (date,))
               or key in ('start_time', 'end_time') and getattr(doc, key) else getattr(doc, key) for key in FIELDS},
            'allocations': doc.allocations.copy(), 'charged': str(doc.charged)}


def summary(value):
    return (f"{dict(Document.LEAVES).get(value['leave_type'], value['leave_type'])} / "
            f"{value['start_date']}~{value['end_date']} / "
            f"{value['start_time'] or '종일'}~{value['end_time'] or ''} / {value['charged']}일 / 연도별 {value['allocations']}")


def require_correction_permission(actor, document):
    if (not actor.is_active or not actor.profile.approved or actor.profile.is_representative
            or not actor.profile.manage_leave):
        raise PermissionDenied
    if document.kind != 'leave' or document.status != 'approved':
        raise ValidationError('최종 승인된 휴가원만 정정할 수 있습니다.')


def proposal(document, values):
    fields = validated_fields(values)
    from .services import allocations, check_overlap
    proposed = Document(pk=document.pk, owner=document.owner, kind='leave', **fields)
    proposed.allocations = allocations(proposed)
    proposed.charged = sum(map(Decimal, proposed.allocations.values()), Decimal('0'))
    check_overlap(proposed)
    return proposed


def balance_preview(document, proposed):
    from .models import AnnualBalance
    years = sorted(set(document.allocations) | set(proposed.allocations))
    balances = {str(b.year): b for b in AnnualBalance.objects.filter(user=document.owner, year__in=years)}
    if any(year not in balances for year in document.allocations):
        raise ValidationError('기존 차감 연도의 연차 정보가 없습니다. 연차 담당자가 확인해 주세요.')
    return [dict(year=year, total=balances[year].total if year in balances else None,
                 used=balances[year].used if year in balances else None,
                 before=document.allocations.get(year, '0'), after=proposed.allocations.get(year, '0'),
                 remaining=(balances[year].remaining + Decimal(document.allocations.get(year, '0'))
                            - Decimal(proposed.allocations.get(year, '0'))) if year in balances else None)
            for year in years]


@transaction.atomic
def correct_approved_leave(pk, actor, values, expected_revision):
    RegulationLock.objects.select_for_update().get_or_create(pk=1)
    actor.profile = Profile.objects.get(user=actor)
    document = Document.objects.select_for_update().get(pk=pk)
    require_correction_permission(actor, document)
    if document.leave_revision != expected_revision:
        raise ValidationError('다른 정정이 이미 반영되었습니다. 문서를 다시 열고 확인해 주세요. 중복 반영하지 않았습니다.')
    reason = str(values.get('correction_reason') or '').strip()
    if not reason or len(reason) > 1000:
        raise ValidationError('정정 사유를 1~1000자로 입력해 주세요.')
    # Same employee lock as leave submission, manual entries and annual adjustments.
    document.owner.profile = Profile.objects.select_for_update().get(user=document.owner)
    proposed = proposal(document, values)
    before = snapshot(document)
    if all(getattr(document, key) == getattr(proposed, key) for key in FIELDS):
        raise ValidationError('변경된 휴가 사용정보가 없습니다.')
    if sum(map(Decimal, document.allocations.values()), Decimal('0')) != document.charged:
        raise ValidationError('기존 연차 차감 기록을 확인해 주세요. 정정은 반영하지 않았습니다.')
    balance_preview(document, proposed)  # Validate original-year existence before any mutation.
    from .services import adjust_charges, audit, notify, accountants, make_title
    adjust_charges(document, -1)
    for key in FIELDS:
        setattr(document, key, getattr(proposed, key))
    document.allocations, document.charged = proposed.allocations, proposed.charged
    adjust_charges(document, 1)
    document.leave_revision += 1
    document.leave_corrected_at = timezone.now()
    document.title = make_title(document)
    document.save(update_fields=[*FIELDS, 'allocations', 'charged', 'leave_revision', 'leave_corrected_at', 'title', 'updated_at'])
    after = snapshot(document)
    LeaveCorrection.objects.create(document=document, actor=actor, revision=document.leave_revision,
                                   before=before, after=after, reason=reason)
    audit(actor, '승인 휴가 사용내역 정정', document,
          f'변경 전: {summary(before)}\n변경 후: {summary(after)}\n사유: {reason}', target=document.owner)
    notify(document, [document.owner] + accountants(document), '승인된 휴가 사용내역이 정정되었습니다.', '휴가정정')
    return document
