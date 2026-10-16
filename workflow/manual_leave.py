"""Register off-system leave using the same employee lock as approval charges."""
from datetime import date
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .annual_grants import ensure_balance
from .models import Document, ManualLeaveUsage, Profile


def validate_values(values):
    day = values.get('used_date')
    if not isinstance(day, date) or not 2000 <= day.year <= 2100:
        raise ValidationError('사용 날짜는 2000~2100년으로 입력해 주세요.')
    reason = str(values.get('reason') or '').strip()
    if not reason or len(reason) > 1000:
        raise ValidationError('등록 사유를 1~1000자로 입력해 주세요.')
    fields = {key: values.get(key) for key in ('leave_type', 'start_time', 'end_time')}
    if fields['leave_type'] == 'annual':
        fields['start_time'] = fields['end_time'] = None
    from .services import leave_amount
    amount = leave_amount(Document(start_date=day, end_date=day, **fields))
    return dict(used_date=day, reason=reason, amount=amount, **fields)


def periods_overlap(new_type, new_start, new_end, old_type, old_start, old_end):
    if new_type == 'annual' or old_type == 'annual':
        return True
    # Older malformed records are treated conservatively rather than double charged.
    if not all((new_start, new_end, old_start, old_end)):
        return True
    return new_start < old_end and old_start < new_end


def check_manual_overlap(document):
    for old in ManualLeaveUsage.objects.filter(employee_id=document.owner_id, cancelled_at__isnull=True,
            used_date__range=(document.start_date, document.end_date)):
        if periods_overlap(document.leave_type, document.start_time, document.end_time,
                           old.leave_type, old.start_time, old.end_time):
            raise ValidationError(f'{old.used_date:%Y.%m.%d}에 경리 직접 등록한 휴가가 있습니다. 기존 등록을 확인해 주세요.')


def require_manager(actor):
    if not actor.profile.manage_leave:
        raise PermissionDenied


@transaction.atomic
def register_manual_leave(actor, employee, values, request_key):
    require_manager(actor)
    try:
        key = UUID(str(request_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('등록 화면을 다시 열어 주세요.')
    fields = validate_values(values)
    profile = Profile.objects.select_for_update().get(user=employee)
    if not profile.approved:
        raise ValidationError('승인된 직원만 등록할 수 있습니다.')
    employee.profile = profile
    previous = ManualLeaveUsage.objects.filter(request_key=key).first()
    if previous:
        if previous.employee_id != employee.pk or previous.created_by_id != actor.pk or any(
                getattr(previous, name) != value for name, value in fields.items()):
            raise ValidationError('이미 처리된 등록입니다. 등록 화면을 다시 열어 주세요.')
        return previous, False  # Includes cancelled records: retry never reactivates them.
    day = fields['used_date']
    from .services import audit, check_overlap
    check_overlap(Document(owner=employee, start_date=day, end_date=day,
                           **{name: fields[name] for name in ('leave_type', 'start_time', 'end_time')}))
    balance = ensure_balance(employee, day.year)
    before = balance.used
    balance.used += fields['amount']
    balance.full_clean()
    balance.save(update_fields=['used'])
    usage = ManualLeaveUsage(employee=employee, created_by=actor, request_key=key, **fields)
    usage.full_clean()
    usage.save()
    audit(actor, f'{day.year}년 연차 직접 등록', target=employee,
          detail=f'직접 등록 #{usage.pk} / 사용일 {day} / {usage.get_leave_type_display()} {usage.amount}일\n'
                 f'사용 {before} → {balance.used} / 잔여 {balance.remaining}\n사유: {usage.reason}')
    return usage, True


@transaction.atomic
def cancel_manual_leave(actor, employee, pk, reason):
    require_manager(actor)
    reason = (reason or '').strip()
    if not reason or len(reason) > 1000:
        raise ValidationError('취소 사유를 1~1000자로 입력해 주세요.')
    profile = Profile.objects.select_for_update().get(user=employee)
    employee.profile = profile
    usage = ManualLeaveUsage.objects.select_for_update().get(pk=pk, employee=employee)
    if usage.cancelled_at:
        raise ValidationError('이미 취소된 등록입니다. 연차를 다시 복원하지 않았습니다.')
    balance = ensure_balance(employee, usage.used_date.year)
    before = balance.used
    balance.used -= usage.amount
    balance.full_clean()
    balance.save(update_fields=['used'])
    usage.cancelled_by, usage.cancelled_at, usage.cancel_reason = actor, timezone.now(), reason
    usage.save(update_fields=['cancelled_by', 'cancelled_at', 'cancel_reason'])
    from .services import audit
    audit(actor, f'{usage.used_date.year}년 연차 직접 등록 취소', target=employee,
          detail=f'직접 등록 #{usage.pk} / 사용일 {usage.used_date} / {usage.amount}일 복원\n'
                 f'사용 {before} → {balance.used} / 잔여 {balance.remaining}\n사유: {reason}')
    return usage
