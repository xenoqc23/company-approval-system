"""Reviewer-led routes, optional executive escalation, and final-only accounting."""
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone
from .models import ApprovalFlowPolicy, Document, Profile


def policy():
    return ApprovalFlowPolicy.objects.filter(pk=1).first() or ApprovalFlowPolicy(enabled=False)


def active_representative():
    return Profile.objects.filter(representative_slot=1, representative_can_approve=True,
        approved=True, user__is_active=True, user__is_superuser=False).select_related('user').first()


def pending_for(user):
    return (Q(status='review', reviewer=user) | Q(status='approve', approver=user)
            | Q(status='executive', representative=user))


def decorate_route(route, kind, owner, rule):
    from django.conf import settings as app_settings
    settings = policy()
    simple_leave=app_settings.INTEGRATED_PURCHASES and kind=='leave'
    if not settings.enabled and not simple_leave:
        return route
    route.update(progressive=bool(settings.enabled or simple_leave), flow_version=settings.version,
        leave_threshold=str(settings.leave_threshold), purchase_threshold=str(settings.purchase_threshold),
        allow_review_final=bool(rule and rule.allow_review_final), stock_final_approval=kind == 'stock')
    if route['mode'] == 'base':
        route['skip_review'] = False
        if rule and rule.approver_is_author:
            route['fixed_approver_id'] = None
    from .delegation import simplified_eligible, rank_index
    direct_allowed=(not rule or rule.allow_representative_direct or rule.allow_self_approval or rule.skip_review or rule.approver_is_author) if simple_leave else bool(rule and rule.allow_representative_direct)
    if (direct_allowed and simplified_eligible(owner)
            and rank_index(owner.profile.rank) >= rank_index('과장' if simple_leave else '팀장') and active_representative()):
        route['available_modes'].append('ceo')
    return route


def representative_option(document, route):
    if document.kind == 'leave':
        from .services import leave_amount
        return leave_amount(document) >= Decimal(route['leave_threshold'])
    return document.kind == 'office' and document.total_price >= Decimal(route['purchase_threshold'])


def prepare(document, route):
    """Must be called after normalizing document values, before saving a submission."""
    if not route.get('progressive'):
        return
    high = representative_option(document, route)
    route['representative_option'] = high
    mode = route['mode']
    if mode == 'base':
        document.approver = None
    elif mode == 'ceo':
        rep = active_representative()
        if not rep:
            raise ValidationError('결재 가능한 대표 계정이 없습니다. admin의 대표 결재 설정을 확인해 주세요.')
        document.reviewer = document.approver = None
        document.representative = rep.user
        route.update(skip_review=True, direct_representative=True,
            representative_id=rep.user_id, representative_name=rep.user.first_name)
    elif mode == 'skip' and document.approver_id == document.owner_id:
        raise ValidationError('본인 승인은 허용된 본인 전결 방식을 선택해 주세요.')


def forward_candidates(document):
    from .delegation import route_people
    rank = document.route_snapshot.get('reviewer_rank') or document.reviewer.profile.rank
    people=route_people(document.route_snapshot, 'approver', rank).exclude(pk=document.owner_id)
    from django.conf import settings
    return people.exclude(pk=document.reviewer_id) if settings.INTEGRATED_PURCHASES else people


def review_final_rule(document, actor):
    """Named reviewer authority is live and independent of author-targeted route rules."""
    from .models import ApprovalRule
    from .people import review_final_people
    if (not document.progressive or document.status!='review' or document.reviewer_id!=actor.pk
            or document.owner_id==actor.pk or not review_final_people().filter(pk=actor.pk).exists()):
        return None
    rules=ApprovalRule.objects.filter(enabled=True,deleted_at__isnull=True,allow_review_final=True,
        review_final_users=actor,kind__in=['all',document.kind]).order_by('pk')
    for rule in rules:
        if document.kind=='office' and not (document.total_price>rule.amount_over
                and (rule.amount_to is None or document.total_price<=rule.amount_to)):
            continue
        return rule
    return None


def may_review_final(document, actor):
    return review_final_rule(document, actor) is not None


def may_escalate(document, actor):
    return (document.progressive and document.status == 'approve' and document.approver_id == actor.pk
        and document.route_snapshot.get('representative_option', False))


def final_actor_id(document):
    return document.route_snapshot.get('final_actor_id') or document.approver_id


def finish(document, actor, event, reason=''):
    from .services import adjust_charges, allocations, audit, notify, accountants, leave_amount
    if document.kind == 'leave':
        document.owner.profile = Profile.objects.select_for_update().get(user=document.owner)
        from .manual_leave import check_manual_overlap
        check_manual_overlap(document)
        document.allocations = allocations(document)
        document.charged = leave_amount(document)
        adjust_charges(document, 1)
    document.status, document.approved_at = 'approved', timezone.now()
    document.route_snapshot = {**document.route_snapshot, 'final_actor_id': actor.pk,
        'final_actor_name': actor.first_name, 'final_method': event}
    audit(actor, event, document, reason + (f'\n연차 {document.charged}일 차감' if document.kind == 'leave' else ''))
    notify(document, [document.owner] + accountants(document), f'{actor.first_name}님의 최종 결재가 완료되었습니다.', '승인완료')


def handle_action(document, actor, action, reason, new_person):
    """Caller holds RegulationLock and document lock; return True when handled."""
    from .services import audit, notify, accountants, adjust_charges
    if not get_user_model().objects.filter(pk=actor.pk,is_active=True).exists() or not actor.profile.approved:
        raise PermissionDenied
    now = timezone.now()
    if action not in {'forward','review_final','escalate','approve','reject','review','cancel_review','cancel_approval'}:
        return False
    from django.conf import settings
    required={'escalate','reject','cancel_review','cancel_approval'} if settings.INTEGRATED_PURCHASES else {'forward','review_final','escalate','reject','cancel_review','cancel_approval'}
    if action in required and not reason.strip():
        raise ValidationError('처리 사유를 입력해 주세요.')
    if action == 'forward':
        if document.status != 'review' or document.reviewer_id != actor.pk:
            raise PermissionDenied
        selected=forward_candidates(document).filter(pk=new_person.pk).first() if new_person else None
        if not selected:
            raise ValidationError('규정과 직급 조건을 충족하는 상위 승인자를 선택해 주세요. 기안자 본인은 제외됩니다.')
        new_person=selected
        document.approver = new_person
        document.reviewed_at, document.status = now, 'approve'
        document.route_snapshot = {**document.route_snapshot, 'approver_id':new_person.pk,
            'approver_rank':new_person.profile.rank, 'approver_name':new_person.first_name}
        audit(actor,'상위 결재 요청',document,reason)
        notify(document,[document.owner,new_person],f'{actor.first_name}님이 검토를 완료했습니다.','승인대기')
    elif action == 'review_final':
        authority=review_final_rule(document,actor)
        if not authority:
            raise PermissionDenied
        document.reviewed_at = now
        document.approver = actor
        document.approver_decided_at = now
        document.route_snapshot = {**document.route_snapshot,'reviewer_final':True,
            'review_final_authority':{'rule_id':authority.pk,'name':authority.name,'version':authority.version,
                'reviewer_id':actor.pk,'reviewer_name':actor.first_name}}
        finish(document,actor,'검토자 전결',reason)
    elif action == 'escalate':
        if not may_escalate(document,actor):
            raise PermissionDenied
        rep = active_representative()
        if not rep:
            raise ValidationError('대표 계정의 결재 허용을 먼저 켜 주세요. 문서는 현재 승인대기 상태로 유지됩니다.')
        document.representative, document.status = rep.user, 'executive'
        document.approver_decided_at, document.representative_requested_at = now, now
        document.route_snapshot = {**document.route_snapshot,'representative_id':rep.user_id,
            'representative_name':rep.user.first_name}
        audit(actor,'대표 결재 요청',document,reason)
        notify(document,[document.owner,rep.user],f'{actor.first_name}님이 승인을 완료하고 대표 결재를 요청했습니다.','대표결재대기')
    elif action == 'approve':
        if document.status == 'approve' and document.approver_id == actor.pk and not actor.profile.is_representative:
            document.approver_decided_at = now
            finish(document,actor,'최종 승인')
        elif (document.status == 'executive' and document.representative_id == actor.pk
                and actor.profile.is_representative and actor.profile.representative_can_approve):
            finish(document,actor,'대표 최종 승인')
        else:
            raise PermissionDenied
    elif action == 'reject':
        if not ((document.status=='review' and document.reviewer_id==actor.pk)
                or (document.status=='approve' and document.approver_id==actor.pk)
                or (document.status=='executive' and document.representative_id==actor.pk
                    and actor.profile.is_representative and actor.profile.representative_can_approve)):
            raise PermissionDenied
        document.status='rejected'
        audit(actor,'반려',document,reason)
        notify(document,[document.owner],f'기안이 반려되었습니다. 사유: {reason[:100]}','반려')
    elif action == 'cancel_review':
        if document.status != 'approve' or document.reviewer_id != actor.pk:
            raise PermissionDenied
        document.status='cancelled'
        audit(actor,'검토 승인 취소',document,reason)
        notify(document,[document.owner,document.approver],f'검토가 취소되었습니다. 사유: {reason[:100]}','검토취소')
    elif action == 'cancel_approval':
        if document.status != 'approved' or final_actor_id(document) != actor.pk:
            raise PermissionDenied
        if document.kind=='leave':
            adjust_charges(document,-1)
        document.status='cancelled'
        audit(actor,'최종 승인 취소',document,reason+(f'\n연차 {document.charged}일 복원' if document.kind=='leave' else ''))
        notify(document,[document.owner]+accountants(document),f'최종 승인이 취소되었습니다. 사유: {reason[:100]}','승인취소')
    else:
        raise PermissionDenied('이 문서는 검토자 전결 또는 상위 결재 요청으로 처리해 주세요.')
    return True


def steps(document):
    result=[dict(label='기안',person=document.owner.first_name,done=bool(document.submitted_at),time=document.submitted_at)]
    if document.review_required:
        result.append(dict(label='검토자 전결' if document.route_snapshot.get('reviewer_final') else '검토',
            person=document.reviewer.first_name if document.reviewer else '미지정',done=bool(document.reviewed_at),time=document.reviewed_at))
    if not document.route_snapshot.get('reviewer_final') and not document.route_snapshot.get('direct_representative'):
        result.append(dict(label='승인',person=document.approver.first_name if document.approver else '검토 후 결정',
            done=bool(document.approver_decided_at),time=document.approver_decided_at))
    if document.representative_id:
        result.append(dict(label='대표 결재',person=document.route_snapshot.get('representative_name') or document.representative.first_name,
            done=bool(document.approved_at),time=document.approved_at))
    if document.status not in ['approved','rejected','cancelled','deleted']:
        for step in result:
            if not step['done']:
                step['current']=True
                break
    return result
