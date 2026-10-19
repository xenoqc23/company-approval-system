"""A single admin-designated representative with optional assigned executive approval."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from .models import (ApprovalRule, CompanyHolidayLock, Document, Profile, RegulationLock,
    REPRESENTATIVE_DEPARTMENT, REPRESENTATIVE_RANK)

BUSINESS_FLAGS = ('manage_leave', 'view_accounting', 'procure', 'manage_system')


def can_manage_representative(user):
    return (user.is_active and user.username.lower() == 'admin'
            and user.profile.approved and user.profile.manage_system)


def pending_assignments(user):
    return Document.objects.filter(
        Q(status='review', reviewer=user) | Q(status='approve', approver=user) |
        Q(status='review', approver=user) | Q(status='executive', representative=user) |
        Q(status__in=['review','approve'], kind__in=['office','stock'], recipient=user) |
        Q(status='approved', kind__in=['office','stock'], recipient=user,
          shipment__in=['', 'shipping', 'ordered']))


def _restore(profile):
    before = profile.representative_previous
    for field in ('department', 'rank', 'department_confirmed', 'approved'):
        setattr(profile, field, before[field])
    profile.representative_slot = None
    profile.representative_view_documents = False
    profile.representative_can_approve = False
    profile.representative_previous = {}
    for flag in BUSINESS_FLAGS:
        setattr(profile, flag, False)
    profile.save()


@transaction.atomic
def assign_representative(actor, target, *, show_birthday=True, view_documents=False,
                          birthday=None, name=None, replace=False, expected_id=None, can_approve=False):
    if not can_manage_representative(actor):
        raise PermissionDenied
    RegulationLock.objects.select_for_update().get_or_create(pk=1)
    CompanyHolidayLock.objects.select_for_update().get_or_create(pk=1)
    target = get_user_model().objects.get(pk=target.pk)
    if not target.is_active or target.is_superuser or target.username.lower() == 'admin':
        raise ValidationError('admin·최고관리자를 제외한 활성 계정만 회사 대표로 지정할 수 있습니다.')
    current = Profile.objects.filter(representative_slot=1).select_related('user').first()
    if current and current.user_id != target.pk:
        if not replace or str(expected_id) != str(current.user_id):
            raise ValidationError(f'현재 대표는 {current.user.first_name}님입니다. 대표 교체 확인을 선택해 주세요.')
    elif expected_id and (not current or str(expected_id) != str(current.user_id)):
        raise ValidationError('대표 지정 정보가 변경되었습니다. 화면을 새로고침해 주세요.')
    ids = sorted({target.pk} | ({current.user_id} if current else set()))
    profiles = {p.user_id:p for p in Profile.objects.select_for_update().filter(user_id__in=ids).order_by('user_id')}
    profile = profiles[target.pk]
    if not profile.is_representative:
        if pending_assignments(target).exists():
            raise ValidationError('이 계정에 대기 중인 결재·물품 수령이 있습니다. 담당자를 먼저 변경하거나 처리를 완료해 주세요.')
        if ApprovalRule.objects.filter(enabled=True, deleted_at__isnull=True).filter(
                Q(fixed_reviewer=target)|Q(fixed_approver=target)).exists():
            raise ValidationError('사용 중인 전결규정의 고정 담당자를 먼저 변경해 주세요.')
    if name is not None and len(name.strip()) > 80:
        raise ValidationError('이름은 80자 이내로 입력해 주세요.')
    if profile.is_representative and not can_approve and Document.objects.filter(status='executive',representative=target).exists():
        raise ValidationError('대기 중인 대표 결재를 먼저 처리한 뒤 결재 허용을 중지해 주세요.')
    if current and current.user_id != target.pk and Document.objects.filter(status='executive',representative_id=current.user_id).exists():
        raise ValidationError('현재 대표의 대기 결재를 먼저 처리한 뒤 교체해 주세요.')
    old_name = current.user.first_name if current else '없음'
    if current and current.user_id != target.pk:
        _restore(profiles[current.user_id])
    if not profile.is_representative:
        profile.representative_previous = {key:getattr(profile,key) for key in
            ('department','rank','department_confirmed','approved')}
    profile.representative_slot = 1
    profile.department, profile.rank = REPRESENTATIVE_DEPARTMENT, REPRESENTATIVE_RANK
    profile.department_confirmed, profile.approved = True, True
    profile.representative_show_birthday = bool(show_birthday)
    profile.representative_view_documents = bool(view_documents)
    profile.representative_can_approve = bool(can_approve)
    for flag in BUSINESS_FLAGS:
        setattr(profile, flag, False)
    if birthday is not None:
        from .birthdays import birthday_values
        for key,value in birthday_values(birthday.get('birthday_month'),birthday.get('birthday_day'),
                birthday.get('birthday_calendar','solar'),birthday.get('birthday_lunar_leap',False)).items():
            setattr(profile,key,value)
    profile.save()
    if name and name.strip():
        target.first_name = name.strip()
        target.save(update_fields=['first_name'])
    from .services import audit
    audit(actor, '회사 대표 지정·설정', target=target,
        detail=f'기존 대표 {old_name} → 현재 대표 {target.first_name} / 대표 결재 허용 {bool(can_approve)} / '
               f'생일 표시 {bool(show_birthday)} / 전체 제출 문서 조회 {bool(view_documents)} / 기존 문서·연차 보존')
    return profile


@transaction.atomic
def remove_representative(actor, target):
    if not can_manage_representative(actor):
        raise PermissionDenied
    RegulationLock.objects.select_for_update().get_or_create(pk=1)
    CompanyHolidayLock.objects.select_for_update().get_or_create(pk=1)
    profile=Profile.objects.select_for_update().get(user=target)
    if not profile.is_representative:
        raise ValidationError('현재 회사 대표로 지정된 계정이 아닙니다.')
    if Document.objects.filter(status='executive',representative=target).exists():
        raise ValidationError('대기 중인 대표 결재를 먼저 처리한 뒤 지정을 해제해 주세요.')
    _restore(profile)
    from .services import audit
    audit(actor,'회사 대표 지정 해제',target=target,
        detail='지정 전 부서·직책·승인 상태로 복원 / 업무 관리 권한은 재지정 필요 / 기존 문서·연차 보존')
