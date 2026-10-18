"""One resolver for previews, form candidates and immutable submission routes."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from .models import ApprovalRule, DEPARTMENTS, RANKS
from .people import approval_people, validate_approval_person


def rank_index(rank):
    return RANKS.index(rank) if rank in RANKS else -1


def simplified_eligible(owner):
    if owner is None:
        return False
    profile = owner.profile
    return (owner.is_active and not owner.is_superuser and owner.username.lower() != 'admin'
        and profile.approved and profile.department_confirmed and not profile.manage_system
        and profile.department in DEPARTMENTS
        and profile.rank in RANKS[RANKS.index('과장'):])


def rule_priority(rule):
    return 3 if rule.authors.exists() else 2 if rule.author_departments else 1 if rule.author_ranks else 0


def resolve_route(kind, owner_rank, total=Decimal('0'), owner=None, mode='base'):
    snapshot = {'name': '생산 재고 기본 경로' if kind == 'stock' else '기본 결재규정',
        'skip_review': False, 'author_rank': owner_rank, 'reviewer_ranks': RANKS[1:],
        'approver_ranks': RANKS[1:], 'rule_id': None, 'version': 1,
        'mode': mode, 'available_modes': ['base'], 'self_complete': False,
        'fixed_reviewer_id': None, 'fixed_approver_id': None}
    matches = []
    if kind != 'stock':
        for rule in ApprovalRule.objects.filter(kind=kind, enabled=True).prefetch_related('authors'):
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
        highest = max(rule_priority(rule) for rule in matches)
        matches = [rule for rule in matches if rule_priority(rule) == highest]
        if len(matches) > 1:
            raise ValidationError('같은 우선순위의 전결규정이 겹칩니다. 규정 관리 담당자에게 확인을 요청해 주세요.')
        rule = matches[0]
        snapshot.update(name=rule.name, rule_id=rule.pk, version=rule.version,
            skip_review=rule.skip_review, reviewer_ranks=rule.reviewer_ranks,
            approver_ranks=rule.approver_ranks, fixed_reviewer_id=rule.fixed_reviewer_id,
            fixed_approver_id=owner.pk if rule.approver_is_author and owner else rule.fixed_approver_id)
        if simplified_eligible(owner):
            if rule.allow_skip_review or rule.skip_review:
                snapshot['available_modes'].append('skip')
            if rule.allow_self_approval and owner_rank in candidate_ranks(snapshot, 'approver'):
                snapshot['available_modes'].append('self')
    if mode not in snapshot['available_modes']:
        raise ValidationError('선택한 결재방식의 권한이 없거나 규정이 변경되었습니다. 과장급 이상에게 허용된 결재방식을 확인해 주세요.')
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
    fixed = route.get('fixed_' + stage + '_id')
    return people.filter(pk=fixed) if fixed else people


def validate_route_people(document, route):
    for stage in ['reviewer', 'approver']:
        fixed = route.get('fixed_' + stage + '_id')
        if fixed:
            from django.contrib.auth import get_user_model
            setattr(document, stage, get_user_model().objects.select_related('profile').get(pk=fixed))
    if route['skip_review']:
        document.reviewer = None
    elif not document.reviewer:
        raise ValidationError('검토자를 선택해 주세요.')
    if document.kind != 'stock' and not document.approver:
        raise ValidationError('승인자를 선택해 주세요.')
    for stage in ['reviewer', 'approver']:
        if (stage == 'reviewer' and route['skip_review']) or (stage == 'approver' and document.kind == 'stock'):
            continue
        person = getattr(document, stage)
        validate_approval_person(person)
        review_rank = document.reviewer.profile.rank if document.reviewer else None
        if person.profile.rank not in candidate_ranks(route, stage, review_rank):
            raise ValidationError('결재자는 전결 허용 범위와 기안자 ≤ 검토자 ≤ 승인자 직급 조건을 충족해야 합니다.')


def route_preview(kind, owner_rank, total, reviewer_rank=None, owner=None, mode='base'):
    route = resolve_route(kind, owner_rank, total, owner=owner, mode=mode)
    return {**route, 'reviewers': candidate_ranks(route, 'reviewer'),
        'approvers': candidate_ranks(route, 'approver', reviewer_rank),
        'path': '본인 전결 · 제출 즉시 완료' if route['self_complete'] else '기안 → 검토 → 발주 → 입고' if kind == 'stock' else '기안 → 승인' if route['skip_review'] else '기안 → 검토 → 승인',
        'note': '100만원 초과 전결규정은 미확정입니다. 현재는 기존 기본 경로를 표시합니다.'
                if kind == 'office' and total > 1000000 and not route['rule_id'] else ''}
