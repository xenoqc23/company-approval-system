"""One resolver for previews, form candidates and immutable submission routes."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from .models import ApprovalRule, DEPARTMENTS, RANKS
from .people import approval_people, validate_approval_person
from django.conf import settings


def rank_index(rank):
    return RANKS.index(rank) if rank in RANKS else -1


def simplified_eligible(owner):
    if owner is None:
        return False
    profile = owner.profile
    return (owner.is_active and not owner.is_superuser and owner.username.lower() != 'admin'
        and profile.approved and profile.department_confirmed and not profile.manage_system and not profile.is_representative
        and profile.department in DEPARTMENTS
        and profile.rank in RANKS[RANKS.index('과장'):])


def rule_priority(rule):
    return 3 if rule.authors.exists() else 2 if rule.author_departments else 1 if rule.author_ranks else 0


def resolve_route(kind, owner_rank, total=Decimal('0'), owner=None, mode='base'):
    if owner and owner.profile.is_representative:
        raise ValidationError('회사 대표 계정은 현재 조회 전용입니다.')
    snapshot = {'name': '생산 재고 기본 경로' if kind == 'stock' else '기본 결재규정',
        'skip_review': False, 'author_rank': owner_rank, 'reviewer_ranks': RANKS[1:],
        'approver_ranks': RANKS[1:], 'rule_id': None, 'version': 1,
        'mode': mode, 'available_modes': ['base'], 'self_complete': False,
        'fixed_reviewer_id': None, 'fixed_approver_id': None}
    selected_rule = None
    matches = []
    for rule in ApprovalRule.objects.filter(kind__in=[kind, 'all'], enabled=True, deleted_at__isnull=True).prefetch_related('authors'):
        if rule.author_ranks and owner_rank not in rule.author_ranks:
            continue
        author_ids = {user.pk for user in rule.authors.all()}
        if author_ids and (owner is None or owner.pk not in author_ids):
            continue
        if rule.author_departments and (owner is None or owner.profile.department not in rule.author_departments):
            continue
        if kind == 'office' and not (total > rule.amount_over and (rule.amount_to is None or total <= rule.amount_to)):
            continue
        matches.append(rule)
    if matches:
        highest = max((rule_priority(rule), rule.kind == kind) for rule in matches)
        matches = [rule for rule in matches if (rule_priority(rule), rule.kind == kind) == highest]
        if len(matches) > 1:
            raise ValidationError('같은 우선순위의 전결규정이 겹칩니다. 규정 관리 담당자에게 확인을 요청해 주세요.')
        rule = matches[0]
        selected_rule = rule
        snapshot.update(name=rule.name, rule_id=rule.pk, rule_kind=rule.kind, version=rule.version,
            stock_final_approval=kind == 'stock',
            skip_review=rule.skip_review, reviewer_ranks=rule.reviewer_ranks,
            approver_ranks=rule.approver_ranks, fixed_reviewer_id=rule.fixed_reviewer_id,
            fixed_approver_id=owner.pk if rule.approver_is_author and owner else rule.fixed_approver_id)
        if simplified_eligible(owner):
            if rule.allow_skip_review or rule.skip_review:
                snapshot['available_modes'].append('skip')
            if rule.allow_self_approval and owner_rank in candidate_ranks(snapshot, 'approver'):
                snapshot['available_modes'].append('self')
    from .progressive import decorate_route
    if settings.INTEGRATED_PURCHASES:
        # Old rule records remain intact, but new submissions cannot self-approve.
        snapshot['available_modes']=['base']
        snapshot['author_id']=getattr(owner,'pk',None)
        for stage in ['reviewer','approver']:
            if snapshot.get('fixed_'+stage+'_id')==snapshot['author_id']:snapshot['fixed_'+stage+'_id']=None
        if kind=='leave':snapshot['skip_review']=False
    decorate_route(snapshot, kind, owner, selected_rule)
    if mode not in snapshot['available_modes']:
        raise ValidationError('선택한 결재방식의 권한이 없거나 규정이 변경되었습니다. 과장급 이상에게 허용된 결재방식을 확인해 주세요.')
    if mode == 'ceo':
        snapshot.update(skip_review=True, direct_representative=True)
    if mode == 'skip':
        snapshot['skip_review'] = True
    if mode == 'self':
        snapshot.update(skip_review=True, self_complete=True, fixed_reviewer_id=None, fixed_approver_id=owner.pk)
    return snapshot


def candidate_ranks(route, stage, reviewer_rank=None):
    minimum = rank_index(route['author_rank'])
    if stage == 'approver' and reviewer_rank and not route['skip_review']:
        minimum = max(minimum, rank_index(reviewer_rank))
    allowed = route[stage + '_ranks']
    return [rank for rank in RANKS[1:] if rank in allowed and rank_index(rank) >= minimum]


def route_people(route, stage, reviewer_rank=None):
    people = approval_people().filter(profile__rank__in=candidate_ranks(route, stage, reviewer_rank))
    if settings.INTEGRATED_PURCHASES and route.get('author_id'):people=people.exclude(pk=route['author_id'])
    fixed = route.get('fixed_' + stage + '_id')
    return people.filter(pk=fixed) if fixed else people


def validate_route_people(document, route):
    if route.get('direct_representative'):
        document.reviewer = document.approver = None
        return
    deferred = route.get('progressive') and route['mode'] == 'base'
    for stage in ['reviewer', 'approver']:
        if stage == 'approver' and deferred:
            document.approver = None
            continue
        fixed = route.get('fixed_' + stage + '_id')
        if fixed:
            from django.contrib.auth import get_user_model
            setattr(document, stage, get_user_model().objects.select_related('profile').get(pk=fixed))
    if route['skip_review']:
        document.reviewer = None
    elif not document.reviewer:
        raise ValidationError('검토자를 선택해 주세요.')
    final_required = not deferred and (document.kind != 'stock' or route.get('stock_final_approval', False))
    if final_required and not document.approver:
        raise ValidationError('승인자를 선택해 주세요.')
    for stage in ['reviewer', 'approver']:
        if (stage == 'reviewer' and route['skip_review']) or (stage == 'approver' and not final_required):
            continue
        person = getattr(document, stage)
        validate_approval_person(person)
        if settings.INTEGRATED_PURCHASES and person.pk==document.owner_id:
            raise ValidationError('기안자는 본인 문서를 검토·승인할 수 없습니다. 다른 직원을 선택해 주세요.')
        review_rank = document.reviewer.profile.rank if document.reviewer else None
        if person.profile.rank not in candidate_ranks(route, stage, review_rank):
            raise ValidationError('결재자는 전결 허용 범위와 기안자 ≤ 검토자 ≤ 승인자 직급 조건을 충족해야 합니다.')


def route_preview(kind, owner_rank, total, reviewer_rank=None, owner=None, mode='base'):
    route = resolve_route(kind, owner_rank, total, owner=owner, mode=mode)
    final_required = kind != 'stock' or route.get('stock_final_approval', False)
    path = '본인 전결 · 제출 즉시 완료' if route['self_complete'] else '기안 → 승인' if route['skip_review'] else '기안 → 검토 → 승인' if final_required else '기안 → 검토'
    if route.get('progressive') and mode == 'base':
        path = '기안 → 검토자 판단 → 상위 승인 · 필요 시 대표 결재'
    elif route.get('direct_representative'):
        path = '기안 → 대표 최종 결재'
    if kind == 'stock':
        path += ' → 발주 → 입고'
    return {**route, 'final_approval_required': final_required,
        'reviewers': candidate_ranks(route, 'reviewer'),
        'approvers': candidate_ranks(route, 'approver', reviewer_rank) if final_required else [],
        'path': path,
        'note': '100만원 초과 전결규정은 미확정입니다. 현재는 기존 기본 경로를 표시합니다.'
                if kind == 'office' and total > 1000000 and not route['rule_id'] else ''}
