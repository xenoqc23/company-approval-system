from decimal import Decimal, InvalidOperation
from uuid import UUID
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from workflow.models import RANKS
from .models import PurchasePolicy,PurchaseRequest,PurchaseReport,PurchaseReportItem,PurchaseEvent,PurchaseNotice,DemoAccount
from .access import active,is_admin,is_finance,require_finance,is_confirmer,confirmers,finance_assigned

REQUEST_FIELDS=('product','vendor','quantity','unit_price','url','reason','private')


def actor_now(actor):
    actor=get_user_model().objects.select_related('profile').get(pk=actor.pk)
    if not active(actor):raise PermissionDenied
    return actor


def lock_policy():
    try:return PurchasePolicy.objects.select_for_update().get(pk=1)
    except PurchasePolicy.DoesNotExist:raise ValidationError('관리자가 구매 규정을 먼저 설정해 주세요.')


def event(actor,label,request=None,report=None,detail=''):
    return PurchaseEvent.objects.create(actor=actor,event=label,request=request,report=report,detail=detail)


def notify(users,text,request=None,report=None):
    ids={u.pk for u in users if u and active(u)}
    PurchaseNotice.objects.bulk_create([PurchaseNotice(user_id=pk,text=text[:250],request=request,report=report) for pk in ids])


def finance_users(p):
    return list(p.finance.filter(is_active=True,profile__approved=True,profile__representative_slot__isnull=True).select_related('profile'))


def mode_for(p,user):
    if user.username=='p_quality' and DemoAccount.objects.filter(user=user).exists():return 'review_approval'
    modes=p.approval_modes
    return modes.get(user.profile.rank,'review_approval')


def eligible_people(user):
    return get_user_model().objects.filter(is_active=True,profile__approved=True,profile__department_confirmed=True,
        profile__department=user.profile.department,profile__representative_slot__isnull=True).exclude(pk=user.pk).exclude(
        username='admin').select_related('profile')


def validate_intermediate(user,person,director,minimum):
    if (not person or not eligible_people(user).filter(pk=person.pk).exists()
            or person.profile.rank not in RANKS or RANKS.index(person.profile.rank)<minimum):
        raise ValidationError('같은 부서의 적합한 상위 검토·승인 담당자를 선택해 주세요.')


def valid_director(user,department):
    return bool(user and active(user) and not user.profile.is_representative and
                user.profile.department==department and user.profile.rank=='이사' and user.profile.department_confirmed)


def validate_policy_people(p):
    if not p.enabled:raise ValidationError('구매 규정이 사용 중이 아닙니다.')
    if not confirmers().exists():raise ValidationError('직원 권한관리에서 구매요청승인완료함 담당자를 지정해 주세요.')
    if not p.representative or not active(p.representative) or not p.representative.profile.is_representative:
        raise ValidationError('대표 계정을 규정에서 지정해 주세요.')
    if not finance_users(p):raise ValidationError('취합·보고 담당자를 지정해 주세요.')


def serialize_request(d):
    return dict(number=d.number,department=d.department,owner=d.owner.first_name,product=d.product,vendor=d.vendor,
                quantity=d.quantity,unit_price=str(d.unit_price),total=str(d.total),reason=d.reason,url=d.url)


@transaction.atomic
def save_request(actor,values,submit=False,pk=None,key=None):
    p=lock_policy();actor=actor_now(actor)
    if actor.profile.is_representative:raise PermissionDenied('대표님은 구매요청을 검토합니다.')
    if pk:
        d=PurchaseRequest.objects.select_for_update().get(pk=pk)
        if d.owner_id!=actor.pk or d.status!='draft':raise PermissionDenied('제출 후에는 구매 내용을 변경할 수 없습니다.')
    else:
        try:key=UUID(str(key))
        except (ValueError,TypeError,AttributeError):raise ValidationError('작성 화면을 다시 열어 주세요.')
        if PurchaseRequest.objects.filter(request_key=key).exists():raise ValidationError('이미 저장한 요청입니다. 내 구매요청에서 확인해 주세요.')
        d=PurchaseRequest(owner=actor,request_key=key)
    for field in REQUEST_FIELDS:setattr(d,field,values.get(field,False if field=='private' else ''))
    d.department,d.rank=actor.profile.department,actor.profile.rank
    if not d.reason.strip():raise ValidationError('구매 사유를 입력해 주세요.')
    if not d.vendor.strip():raise ValidationError('구매처를 입력해 주세요.')
    if not 1<=d.quantity<=999999 or not Decimal('0')<d.unit_price<=Decimal('999999999.99'):
        raise ValidationError('수량과 단가를 확인해 주세요.')
    if d.total>Decimal('999999999999.99'):raise ValidationError('요청 총액이 입력 가능한 범위를 초과합니다.')
    if submit:
        validate_policy_people(p)
        mode=mode_for(p,actor);director=None
        if mode not in ['direct','approval','review_approval']:raise ValidationError('직급별 경로를 규정에서 확인해 주세요.')
        reviewer,approver=values.get('reviewer'),values.get('approver')
        minimum=RANKS.index(d.rank) if d.rank in RANKS else len(RANKS)
        if mode=='direct' and (d.rank not in RANKS or minimum<RANKS.index('과장')):raise ValidationError('본인 전결은 과장급 이상에게만 허용됩니다.')
        if mode=='review_approval':
            validate_intermediate(actor,reviewer,director,minimum)
            minimum=max(minimum,RANKS.index(reviewer.profile.rank))
        if mode in ['approval','review_approval']:validate_intermediate(actor,approver,director,minimum)
        if mode=='review_approval' and reviewer.pk==approver.pk:raise ValidationError('검토자와 승인자를 서로 다른 직원으로 지정해 주세요.')
        d.reviewer=reviewer if mode=='review_approval' else None
        d.approver=approver if mode in ['approval','review_approval'] else None
        d.director=None
        d.route=dict(workflow='separated-v2',version=p.version,mode=mode,department=d.department,rank=d.rank,reviewer_id=d.reviewer_id,approver_id=d.approver_id)
        d.status='review' if d.reviewer_id else 'approval' if d.approver_id else 'ready'
        d.submitted_at=timezone.now()
    d.full_clean();d.save()
    event(actor,'구매요청 제출' if submit else '구매요청 임시저장',request=d,detail=f'구매처 {d.vendor} / 총액 {d.total}원')
    if submit:
        person=d.reviewer if d.status=='review' else d.approver if d.status=='approval' else d.director
        notify(list(confirmers().exclude(pk=d.owner_id)) if d.status=='ready' else [person],f'{d.owner.first_name}님의 {d.product} · '+('구매요청 승인완료' if d.status=='ready' else d.get_status_display()),request=d)
    return d


@transaction.atomic
def request_action(pk,actor,action,reason=''):
    p=lock_policy();actor=actor_now(actor);d=PurchaseRequest.objects.select_for_update().select_related('owner','reviewer','approver','director').get(pk=pk)
    now=timezone.now();reason=(reason or '').strip()
    if len(reason)>1000:raise ValidationError('사유는 1000자 이내로 입력해 주세요.')
    assigned={'review':d.reviewer_id,'approval':d.approver_id,'director':d.director_id}.get(d.status)
    if action in ['approve','reject']:
        if assigned!=actor.pk:raise PermissionDenied('현재 단계에 배정된 담당자만 처리할 수 있습니다.')
        if action=='reject':
            if not reason:raise ValidationError('반려 사유를 입력해 주세요.')
            d.status,d.decision_reason='rejected',reason
            label='내부 승인 반려'
        elif d.status=='review':
            d.reviewed_at=now;d.status='approval';label='검토 완료'
        elif d.status=='approval':
            d.intermediate_at=now;d.status='ready' if d.route.get('workflow')=='separated-v2' else 'director';label='최종 승인완료' if d.status=='ready' else '중간 승인 완료'
        else:
            d.director_at=now;d.status='ready';label='최종 승인완료'
        event(actor,label,request=d,detail=reason)
        users=[d.owner]
        if d.status=='approval':users.append(d.approver)
        elif d.status=='director':users.append(d.director)
        elif d.status=='ready':users+=list(confirmers().exclude(pk=d.owner_id))
        notify(users,f'{d.product} · {label}'+(f' · {reason}' if reason else ''),request=d)
    elif action=='confirm_items':
        if not is_confirmer(actor) or d.owner_id==actor.pk:raise PermissionDenied('구매요청승인완료함 권한이 있는 담당자만 구매 품목을 확인할 수 있습니다.')
        if d.status not in ['ready','hold'] or d.confirmed_at or (d.current_report_id and d.current_report.status!='decided'):raise ValidationError('승인완료 후 아직 확인하지 않은 문서만 처리할 수 있습니다.')
        people=finance_users(p)
        if not people:raise ValidationError('취합·보고 담당자를 지정해 주세요.')
        d.confirmed_by=actor;d.confirmed_at=now
        d.purchase_route=dict(confirmer_id=actor.pk,confirmer_name=actor.first_name,collector_ids=[u.pk for u in people],collector_names=[u.first_name for u in people],representative_id=p.representative_id)
        event(actor,'구매 품목 확인',request=d,detail=reason)
        notify(people,f'{d.product} · 구매 품목 확인 완료, 취합·보고 대기',request=d)
    elif action=='cancel':
        if actor.pk!=d.owner_id or d.status not in ['draft','review','approval','director','ready'] or d.current_report_id or d.confirmed_at:
            raise PermissionDenied('구매 품목 확인 전의 본인 요청만 취소할 수 있습니다.')
        if not reason:raise ValidationError('취소 사유를 입력해 주세요.')
        d.status,d.decision_reason='cancelled',reason;event(actor,'구매요청 취소',request=d,detail=reason)
        notify([d.reviewer,d.approver,d.director],f'{d.product} · 요청 취소',request=d)
    elif action=='paid':
        if not (finance_assigned(actor,d) or actor.profile.is_representative and d.current_report_id and d.current_report.representative_id==actor.pk):raise PermissionDenied
        if d.status!='allowed':raise ValidationError('대표님이 구매승인를 확정한 품목만 결제 완료로 기록할 수 있습니다.')
        if not reason:raise ValidationError('결제 확인 내용을 입력해 주세요.')
        d.status,d.paid_at='paid',now;event(actor,'결제 완료 확인',request=d,detail=reason)
        notify([d.owner],f'{d.product} · 결제 완료, 물품 수령을 확인해 주세요.',request=d)
    elif action=='receive':
        if d.owner_id!=actor.pk:raise PermissionDenied
        if d.status!='paid':raise ValidationError('결제 완료로 확인된 품목만 수령 확인할 수 있습니다.')
        d.status,d.received_at='received',now;event(actor,'물품 수령 완료',request=d)
        notify(finance_users(p),f'{d.product} · 수령 완료',request=d)
    else:raise ValidationError('지원하지 않는 처리입니다.')
    d.revision+=1;d.save();return d


@transaction.atomic
def submit_report(actor,ids,title,note,key):
    p=lock_policy();actor=actor_now(actor);require_finance(actor);validate_policy_people(p)
    if not title.strip() or len(title)>180 or not note.strip() or len(note)>1000:raise ValidationError('취합 제목과 보고 내용을 입력해 주세요.')
    try:key=UUID(str(key));ids=[int(x) for x in ids]
    except (ValueError,TypeError,AttributeError):raise ValidationError('선택 품목을 다시 확인해 주세요.')
    if not ids or len(ids)>100 or len(set(ids))!=len(ids) or any(x<1 or x>9223372036854775807 for x in ids):raise ValidationError('중복 없이 1~100개 품목을 선택해 주세요.')
    if PurchaseReport.objects.filter(request_key=key).exists():raise ValidationError('이미 제출한 구매요청입니다.')
    docs=list(PurchaseRequest.objects.select_for_update().filter(pk__in=ids).order_by('pk').select_related('owner'))
    if len(docs)!=len(ids) or any(d.status not in ['ready','hold'] or not d.confirmed_at or not finance_assigned(actor,d) for d in docs):
        raise ValidationError('이미 취합되었거나 구매 품목 확인이 끝나지 않은 품목이 있습니다. 목록을 새로고침해 주세요.')
    report=PurchaseReport.objects.create(created_by=actor,representative=p.representative,title=title.strip(),note=note.strip(),request_key=key)
    for d in docs:
        PurchaseReportItem.objects.create(report=report,request=d,snapshot=serialize_request(d))
        d.status,d.current_report,d.decision_reason='ceo',report,'';d.revision+=1;d.save()
        event(actor,'대표 구매요청',request=d,report=report,detail=report.number)
        notify([d.owner],f'{d.product} · 취합·보고 완료, 대표님 구매요청',request=d)
    event(actor,'구매요청 제출',report=report,detail=note)
    notify([report.representative],f'{report.number} · {len(docs)}개 품목 구매요청',report=report)
    return report


@transaction.atomic
def decide_report(pk,actor,decisions,revision,final=False):
    p=lock_policy();actor=actor_now(actor)
    report=PurchaseReport.objects.select_for_update().get(pk=pk)
    if actor.pk!=report.representative_id or not actor.profile.is_representative:raise PermissionDenied
    if report.status!='pending' or report.revision!=revision:raise ValidationError('이미 처리되었거나 다른 창에서 변경되었습니다. 다시 열어 주세요.')
    items=list(report.items.select_for_update().select_related('request'))
    if set(decisions)!= {str(item.pk) for item in items}:raise ValidationError('모든 품목의 결정 정보를 다시 확인해 주세요.')
    for item in items:
        value=decisions[str(item.pk)];choice=value.get('decision');reason=str(value.get('reason') or '').strip()
        if choice not in dict(PurchaseReportItem.DECISIONS) or len(reason)>1000:raise ValidationError('품목별 결정과 사유를 확인해 주세요.')
        if final and choice=='pending':raise ValidationError('모든 품목을 구매승인·반려·보류 중 하나로 결정해 주세요.')
        if choice in ['deny','hold'] and not reason:raise ValidationError('구매반려·보류 품목에는 사유가 필요합니다.')
        item.decision,item.reason=choice,reason;item.save(update_fields=['decision','reason'])
    if final:
        now=timezone.now()
        docs={d.pk:d for d in PurchaseRequest.objects.select_for_update().filter(pk__in=[item.request_id for item in items]).order_by('pk')}
        for item in items:
            d=docs[item.request_id]
            if d.status!='ceo' or d.current_report_id!=report.pk:raise ValidationError('취합 품목의 진행 상태가 바뀌었습니다. 다시 확인해 주세요.')
            d.status={'allow':'allowed','deny':'denied','hold':'hold'}[item.decision]
            d.decision_reason=item.reason;d.permitted_at=now;d.revision+=1;d.save()
            event(actor,'대표 '+item.get_decision_display(),request=d,report=report,detail=item.reason)
            notify([d.owner]+finance_users(p),f'{d.product} · 대표 {item.get_decision_display()}'+(f' · {item.reason}' if item.reason else ''),request=d)
        report.status,report.decided_at='decided',now
        event(actor,'구매 검토 결과 확정',report=report)
    else:event(actor,'품목별 검토 임시저장',report=report)
    report.revision+=1;report.save();return report
