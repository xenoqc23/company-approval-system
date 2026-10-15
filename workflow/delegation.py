"""One resolver for previews, form candidates and immutable submission routes."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from .models import ApprovalRule, RANKS
from .people import approval_people, validate_approval_person


def rank_index(rank):
    return RANKS.index(rank) if rank in RANKS else -1


def resolve_route(kind, owner_rank, total=Decimal('0')):
    snapshot = {'name': '생산 재고 기본 경로' if kind == 'stock' else '기본 결재규정',
        'skip_review': False, 'author_rank': owner_rank, 'reviewer_ranks': RANKS[1:],
        'approver_ranks': RANKS[1:], 'rule_id': None, 'version': 1}
    if kind == 'stock':
        return snapshot
    matches = []
    for rule in ApprovalRule.objects.filter(kind=kind, enabled=True):
        if rule.author_ranks and owner_rank not in rule.author_ranks:
            continue
        if kind == 'office' and not (total > rule.amount_over and (rule.amount_to is None or total <= rule.amount_to)):
            continue
        matches.append(rule)
    if len(matches) > 1:
        raise ValidationError('여러 전결규정이 겹칩니다. 경리 또는 admin에게 규정 확인을 요청해 주세요.')
    if matches:
        rule = matches[0]
        snapshot.update(name=rule.name, rule_id=rule.pk, version=rule.version,
            skip_review=rule.skip_review, reviewer_ranks=rule.reviewer_ranks,
            approver_ranks=rule.approver_ranks)
    return snapshot


def candidate_ranks(route, stage, reviewer_rank=None):
    minimum = rank_index(route['author_rank'])
    if stage == 'approver' and reviewer_rank and not route['skip_review']:
        minimum = max(minimum, rank_index(reviewer_rank))
    allowed = route[stage + '_ranks']
    return [rank for rank in RANKS[1:] if rank in allowed and rank_index(rank) >= minimum]


def route_people(route, stage, reviewer_rank=None):
    return approval_people().filter(profile__rank__in=candidate_ranks(route, stage, reviewer_rank))


def validate_route_people(document, route):
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


def route_preview(kind, owner_rank, total, reviewer_rank=None):
    route = resolve_route(kind, owner_rank, total)
    return {**route, 'reviewers': candidate_ranks(route, 'reviewer'),
        'approvers': candidate_ranks(route, 'approver', reviewer_rank),
        'path': '기안 → 검토 → 발주 → 입고' if kind == 'stock' else '기안 → 승인' if route['skip_review'] else '기안 → 검토 → 승인',
        'note': '100만원 초과 전결규정은 미확정입니다. 현재는 기존 기본 경로를 표시합니다.'
                if kind == 'office' and total > 1000000 and not route['rule_id'] else ''}
