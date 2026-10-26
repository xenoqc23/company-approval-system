from decimal import Decimal, InvalidOperation
from django.conf import settings
from uuid import UUID,uuid4
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from workflow.models import RANKS
from .models import PurchasePolicy,PurchaseRequest,PurchaseReport,PurchaseReportItem,PurchaseEvent,PurchaseNotice,DemoAccount,PurchaseReceipt,PurchaseSupplement,PurchaseAmendment
from .access import active,is_admin,is_finance,require_finance,is_confirmer,confirmers,finance_assigned,checker_assigned,request_confirmers

REQUEST_FIELDS=('product','vendor','quantity','unit_price','url','reason','private','needed_by','urgent','urgent_reason','usage_department','storage_location')


def actor_now(actor):
    actor=get_user_model().objects.select_related('profile').get(pk=actor.pk)
    if not active(actor):raise PermissionDenied
    return actor


def lock_policy():
    try:return PurchasePolicy.objects.select_for_update().get(pk=1)
    except PurchasePolicy.DoesNotExist:raise ValidationError('관리자가 구매 규정을 먼저 설정해 주세요.')


def event(actor,label,request=None,report=None,detail=''):
    return PurchaseEvent.objects.create(actor=actor,event=label,request=request,report=report,detail=detail)


def notify(users,text,request=None,report=None,owner_update=False):
    ids={u.pk for u in users if u and active(u)}
    if settings.INTEGRATED_PURCHASES and request and not owner_update:
        ids.discard(request.owner_id)
    PurchaseNotice.objects.bulk_create([PurchaseNotice(user_id=pk,text=text[:250],request=request,report=report) for pk in ids])


def finance_users(p):
    return list(p.finance.filter(is_active=True,profile__approved=True,profile__representative_slot__isnull=True).select_related('profile'))


def mode_for(p,user):
    if p and p.department_routing:return p.review_mode
    if user.username=='p_quality' and DemoAccount.objects.filter(user=user).exists():return 'review_approval'
    modes=p.approval_modes
    return modes.get(user.profile.rank,'review_approval')


def eligible_people(user):
    people=get_user_model().objects.filter(is_active=True,profile__approved=True,profile__department_confirmed=True,
        profile__representative_slot__isnull=True).exclude(pk=user.pk).exclude(username='admin').select_related('profile')
    return people if settings.INTEGRATED_PURCHASES else people.filter(profile__department=user.profile.department)


def validate_intermediate(user,person,director,minimum):
    if (not person or not eligible_people(user).filter(pk=person.pk).exists()
            or person.profile.rank not in RANKS or RANKS.index(person.profile.rank)<minimum):
        raise ValidationError('규정과 직급 조건에 맞는 검토·승인 담당자를 선택해 주세요.')


def valid_director(user,department):
    return bool(user and active(user) and not user.profile.is_representative and
                user.profile.department==department and user.profile.rank=='이사' and user.profile.department_confirmed)


def valid_checker(user,department):
    if settings.INTEGRATED_PURCHASES:
        return bool(user and active(user) and not user.profile.is_representative)
    return valid_director(user,department)


def can_request_direct(p,user):
    return bool(p and user.profile.rank in ['과장','팀장','부장','이사'] and user.profile.rank in p.direct_ranks)


def reviewer_can_finish(actor,d,p=None):
    p=p or PurchasePolicy.objects.filter(pk=1).first()
    from workflow.people import review_final_people
    return bool(p and active(actor) and d.status=='review' and d.reviewer_id==actor.pk and d.owner_id!=actor.pk
        and actor.profile.rank in ['과장','팀장','부장','이사'] and not actor.profile.is_representative
        and not actor.profile.manage_system and review_final_people().filter(pk=actor.pk).exists() and p.review_final_users.filter(pk=actor.pk).exists())


def forward_people(d):
    minimum=max(RANKS.index(d.rank) if d.rank in RANKS else len(RANKS),
        RANKS.index(d.reviewer.profile.rank) if d.reviewer and d.reviewer.profile.rank in RANKS else len(RANKS))
    return eligible_people(d.owner).filter(profile__rank__in=RANKS[minimum:]).exclude(pk=d.reviewer_id)


def department_checker(p,user):
    return p.dev_director if user.profile.department=='개발팀' else p.production_director


def confirm_purchase(d,actor,p,method='manual',reason=''):
    people=finance_users(p)
    if not people:raise ValidationError('구매 담당자를 지정해 주세요.')
    if method=='director_request':
        if actor.pk!=d.owner_id or actor.pk!=d.purchase_checker_id or not d.route.get('self_request') or d.route.get('request_method')!='direct':raise PermissionDenied
    elif not checker_assigned(actor,d) or actor.pk==d.owner_id:raise PermissionDenied('이 문서에 지정된 구매 확인 담당자만 처리할 수 있습니다.')
    d.confirmation_method=method;d.confirmed_at=timezone.now()
    d.confirmed_by=None if method=='director_request' else actor
    d.purchase_route=dict(confirmer_id=d.purchase_checker_id or actor.pk,confirmer_name=d.purchase_checker.first_name if d.purchase_checker_id else actor.first_name,
        forwarded_by_id=actor.pk,forwarded_by_name=actor.first_name,method=method,collector_ids=[u.pk for u in people],collector_names=[u.first_name for u in people],representative_id=p.representative_id)
    label={'manual':'구매 품목 확인','with_approval':'승인 시 구매 내용 함께 확인','director_request':('담당자 직접 요청 · 확인 생략' if settings.INTEGRATED_PURCHASES else '담당 이사 직접 요청 · 확인 생략')}[method]
    event(actor,label,request=d,detail=reason)
    notify(people,f'{d.product} · '+(('담당자 직접 요청' if settings.INTEGRATED_PURCHASES else '담당 이사 직접 요청') if method=='director_request' else '구매 내용 확인 완료')+' · 구매요청 작성 대기',request=d)


def validate_policy_people(p):
    if not p.enabled:raise ValidationError('구매 규정이 사용 중이 아닙니다.')
    if p.department_routing:
        for person,department in [(p.dev_director,'개발팀'),(p.production_director,'생산팀')]:
            if not valid_checker(person,department) or not is_confirmer(person):raise ValidationError(f'{department} 요청의 구매확인 담당자와 권한을 지정해 주세요.')
        if p.review_mode not in ['approval','review_approval']:raise ValidationError('검토 요청 경로를 확인해 주세요.')
    if not confirmers().exists():raise ValidationError('직원 권한관리에서 구매요청승인완료함 담당자를 지정해 주세요.')
    if not p.representative or not active(p.representative) or not p.representative.profile.is_representative:
        raise ValidationError('직원 권한관리에서 결제 내역을 조회할 대표를 지정해 주세요.')
    if not finance_users(p):raise ValidationError('구매 담당자를 지정해 주세요.')


def serialize_request(d):
    data=dict(number=d.number,department=d.department,owner=d.owner.first_name,product=d.product,vendor=d.vendor,
                quantity=d.quantity,unit_price=str(d.unit_price),total=str(d.total),reason=d.reason,url=d.url,needed_by=d.needed_by.isoformat() if d.needed_by else '',urgent=d.urgent,urgent_reason=d.urgent_reason,usage_department=d.usage_department)
    return data


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
    for field in REQUEST_FIELDS:setattr(d,field,values.get(field,False if field in ['private','urgent'] else None if field=='needed_by' else actor.profile.department if field=='usage_department' else ''))
    d.department,d.rank=actor.profile.department,actor.profile.rank
    if d.urgent and not d.urgent_reason.strip():raise ValidationError('긴급 요청 사유를 입력해 주세요.')
    if not d.reason.strip():raise ValidationError('구매 사유를 입력해 주세요.')
    if not d.vendor.strip():raise ValidationError('구매처를 입력해 주세요.')
    if not 1<=d.quantity<=999999 or not Decimal('0')<d.unit_price<=Decimal('999999999.99'):
        raise ValidationError('수량과 단가를 확인해 주세요.')
    if d.total>Decimal('999999999999.99'):raise ValidationError('요청 총액이 입력 가능한 범위를 초과합니다.')
    if submit:
        if settings.INTEGRATED_PURCHASES and not d.url.strip():raise ValidationError('구매 링크를 입력해 주세요.')
        validate_policy_people(p)
        method=str(values.get('request_method') or 'review')
        if p.department_routing:
            if method not in ['review','direct']:raise ValidationError('요청 방식을 선택해 주세요.')
            if method=='direct' and not can_request_direct(p,actor):raise PermissionDenied('이 직급은 검토 요청으로 제출해야 합니다.')
            mode='direct' if method=='direct' else mode_for(p,actor)
        else:mode=mode_for(p,actor)
        director=None
        if mode not in ['direct','approval','review_approval']:raise ValidationError('직급별 경로를 규정에서 확인해 주세요.')
        reviewer,approver=values.get('reviewer'),values.get('approver')
        deferred=settings.INTEGRATED_PURCHASES and method=='review'
        if deferred:mode='review_approval';approver=None
        minimum=RANKS.index(d.rank) if d.rank in RANKS else len(RANKS)
        if mode=='direct' and (d.rank not in RANKS or minimum<RANKS.index('과장')):raise ValidationError('구매담당자에게 요청은 과장급 이상에게만 허용됩니다.')
        if mode=='review_approval':
            validate_intermediate(actor,reviewer,director,minimum)
            minimum=max(minimum,RANKS.index(reviewer.profile.rank))
        if mode in ['approval','review_approval'] and not deferred:validate_intermediate(actor,approver,director,minimum)
        if mode=='review_approval' and approver and reviewer.pk==approver.pk:raise ValidationError('검토자와 승인자를 서로 다른 직원으로 지정해 주세요.')
        d.reviewer=reviewer if mode=='review_approval' else None
        d.approver=approver if mode in ['approval','review_approval'] else None
        d.director=None
        d.route=dict(workflow='separated-v2',version=p.version,mode=mode,department=d.department,rank=d.rank,reviewer_id=d.reviewer_id,approver_id=d.approver_id)
        if deferred:d.route['reviewer_decides']=True
        if p.department_routing:
            checker=department_checker(p,actor)
            self_request=checker.pk==actor.pk and method=='direct' and p.director_self_request
            delegated=checker.pk==actor.pk and not self_request
            if delegated:checker=p.production_director if actor.profile.department=='개발팀' else p.dev_director
            if not checker or checker.pk==actor.pk and not self_request or not is_confirmer(checker):raise ValidationError('본인 요청을 대신 확인할 구매확인 담당자를 지정해 주세요.')
            d.purchase_checker=checker
            d.route.update(workflow='department-v3',request_method=method,checker_id=checker.pk,checker_name=checker.first_name,
                combine_confirmation=p.combine_confirmation,self_request=self_request,delegated=delegated)
        d.status='review' if d.reviewer_id else 'approval' if d.approver_id else 'ready'
        d.submitted_at=timezone.now()
    if not submit and p.department_routing:
        method=str(values.get('request_method') or 'review')
        if method not in ['review','direct'] or method=='direct' and not can_request_direct(p,actor):raise ValidationError('사용할 수 있는 요청 방식을 선택해 주세요.')
        d.route={'request_method':method}
    d.full_clean();d.save()
    event(actor,'구매요청 제출' if submit else '구매요청 임시저장',request=d,detail=f'구매처 {d.vendor} / 총액 {d.total}원')
    if submit and d.route.get('self_request'):
        confirm_purchase(d,actor,p,'director_request');d.save()
    if submit:
        person=d.reviewer if d.status=='review' else d.approver if d.status=='approval' else d.director
        notify(list(request_confirmers(d)) if d.status=='ready' and not d.confirmed_at else [] if d.confirmed_at else [person],f'{d.owner.first_name}님의 {d.product} · '+('구매요청 승인완료' if d.status=='ready' else d.get_status_display()),request=d)
    return d


def combines_confirmation(document, actor):
    """Production always combines the assigned director's internal approval."""
    return bool((settings.INTEGRATED_PURCHASES or document.route.get('combine_confirmation'))
                and actor.pk == document.purchase_checker_id
                and actor.pk != document.owner_id and checker_assigned(actor, document))


@transaction.atomic
def request_action(pk,actor,action,reason='',quantity=None,receipt_key=None,storage_location=None,new_person=None):
    p=lock_policy();actor=actor_now(actor);d=PurchaseRequest.objects.select_for_update().select_related('owner','reviewer','approver','director').get(pk=pk)
    now=timezone.now();reason=(reason or '').strip()
    if len(reason)>1000:raise ValidationError('사유는 1000자 이내로 입력해 주세요.')
    assigned={'review':d.reviewer_id,'approval':d.approver_id,'director':d.director_id}.get(d.status)
    if action in ['forward','review_final','approve','reject'] and actor.pk==d.owner_id:raise PermissionDenied('기안자는 본인 문서를 검토·승인할 수 없습니다.')
    if action in ['forward','review_final']:
        if not d.route.get('reviewer_decides') or d.status!='review' or assigned!=actor.pk or d.owner_id==actor.pk:raise PermissionDenied('현재 검토자만 처리할 수 있습니다.')
        if action=='forward':
            person=forward_people(d).filter(pk=getattr(new_person,'pk',None)).first()
            if not person:raise ValidationError('본인과 기안자를 제외하고 규정·직급 조건에 맞는 승인자를 선택해 주세요.')
            d.approver=person;d.reviewed_at=now;d.status='approval'
            d.route={**d.route,'approver_id':person.pk,'approver_name':person.first_name}
            event(actor,'검토 완료',request=d,detail=reason or f'{person.first_name}님에게 승인 요청')
            notify([person],f'{d.product} · {actor.first_name}님의 검토가 완료되어 승인 요청이 도착했습니다.',request=d)
            notify([d.owner],f'{d.product} · {actor.first_name}님이 검토를 완료했습니다.',request=d,owner_update=True)
        else:
            if not reviewer_can_finish(actor,d,p):raise PermissionDenied('구매 규정에서 승인완료 권한을 받은 검토자만 처리할 수 있습니다.')
            d.approver=actor;d.reviewed_at=d.intermediate_at=now;d.status='ready'
            d.route={**d.route,'reviewer_final':True,'approver_id':actor.pk,'review_final_policy_version':p.version}
            event(actor,'내부 승인완료',request=d,detail=reason or '지정 검토자의 승인완료')
            if combines_confirmation(d,actor):confirm_purchase(d,actor,p,'with_approval')
            elif not d.confirmed_at:notify(list(request_confirmers(d)),f'{d.product} · 구매 내용 확인 요청',request=d)
            notify([d.owner],f'{d.product} · {actor.first_name}님이 검토·승인을 완료했습니다.',request=d,owner_update=True)
    elif action in ['approve','reject']:
        if assigned!=actor.pk:raise PermissionDenied('현재 단계에 배정된 담당자만 처리할 수 있습니다.')
        if action=='approve' and d.status=='review' and d.route.get('reviewer_decides'):raise ValidationError('승인완료 또는 승인자에게 전달을 선택해 주세요.')
        if action=='reject':
            if not reason:raise ValidationError('반려 사유를 입력해 주세요.')
            d.status,d.decision_reason='rejected',reason
            label='내부 승인 반려'
        elif d.status=='review':
            d.reviewed_at=now;d.status='approval';label='검토 완료'
        elif d.status=='approval':
            d.intermediate_at=now;d.status='ready' if d.route.get('workflow') in ['separated-v2','department-v3'] else 'director';label=('내부 승인완료' if settings.INTEGRATED_PURCHASES else '최종 승인완료') if d.status=='ready' else '중간 승인 완료'
        else:
            d.director_at=now;d.status='ready';label='내부 승인완료' if settings.INTEGRATED_PURCHASES else '최종 승인완료'
        event(actor,label,request=d,detail=reason)
        if d.status=='ready' and combines_confirmation(d,actor):
            confirm_purchase(d,actor,p,'with_approval')
        users=[d.owner]
        if d.status=='approval':users.append(d.approver)
        elif d.status=='director':users.append(d.director)
        elif d.status=='ready' and not d.confirmed_at:users+=list(request_confirmers(d))
        if settings.INTEGRATED_PURCHASES:
            notify([u for u in users if u and u.pk!=d.owner_id],f'{d.product} · {actor.first_name}님 {label}',request=d)
            owner_text=f'{actor.first_name}님이 '+('검토를 완료했습니다.' if label=='검토 완료' else '요청을 반려했습니다.' if d.status=='rejected' else '승인을 완료했습니다.')
            notify([d.owner],f'{d.product} · {owner_text}'+(f' · {reason}' if d.status=='rejected' else ''),request=d,owner_update=True)
        else:notify(users,f'{d.product} · {label}'+(f' · {reason}' if reason else ''),request=d)
    elif action=='confirm_items':
        if not checker_assigned(actor,d) or d.owner_id==actor.pk:raise PermissionDenied('이 문서에 지정된 구매 확인 담당자만 처리할 수 있습니다.')
        if d.status not in ['ready','hold'] or d.confirmed_at or (d.current_report_id and d.current_report.status!='decided'):raise ValidationError('승인완료 후 아직 확인하지 않은 문서만 처리할 수 있습니다.')
        confirm_purchase(d,actor,p,'manual',reason)
    elif action=='request_supplement':
        if not checker_assigned(actor,d) or actor.pk==d.owner_id:raise PermissionDenied
        if d.status!='ready' or d.confirmed_at or d.current_report_id:raise ValidationError('구매 품목 확인 전의 승인완료 문서만 보완 요청할 수 있습니다.')
        if not reason:raise ValidationError('보완이 필요한 내용을 입력해 주세요.')
        PurchaseSupplement.objects.create(request=d,requested_by=actor,reason=reason,before=serialize_request(d))
        d.status='supplement';d.decision_reason=reason
        event(actor,'구매요청 보완 요청',request=d,detail=reason)
        notify([d.owner],f'{d.product} · 보완 요청 · {reason}',request=d,owner_update=True)
    elif action=='prepare_hold':
        if not finance_assigned(actor,d):raise PermissionDenied
        if d.status!='hold':raise ValidationError('보류된 품목만 재보고 준비할 수 있습니다.')
        if not reason:raise ValidationError('보류 사유를 확인하고 보완 내용을 입력해 주세요.')
        d.hold_ready=True;d.hold_note=reason
        event(actor,'보류 품목 재보고 준비',request=d,detail=reason)
    elif action=='cancel':
        if actor.pk!=d.owner_id or d.status not in ['draft','review','approval','director','ready'] or d.current_report_id or d.confirmed_at:
            raise PermissionDenied('구매 품목 확인 전의 본인 요청만 취소할 수 있습니다.')
        if not reason:raise ValidationError('취소 사유를 입력해 주세요.')
        d.status,d.decision_reason='cancelled',reason;event(actor,'구매요청 취소',request=d,detail=reason)
        notify([d.reviewer,d.approver,d.director],f'{d.product} · 요청 취소',request=d)
    elif action=='finance_reject':
        if not finance_assigned(actor,d):raise PermissionDenied
        if d.status not in ['ready','reapproval','hold'] or not d.confirmed_at:raise ValidationError('대표님께 올리기 전의 확인된 품목만 여기서 반려할 수 있습니다. 결제 요청 후에는 해당 요청에서 처리해 주세요.')
        if not reason:raise ValidationError('반려 사유를 입력해 주세요.')
        d.status='denied';d.decision_reason=reason
        event(actor,'구매 반려',request=d,detail=reason)
        notify([d.owner],f'{d.product} · 구매요청이 반려되었습니다. {reason}',request=d,owner_update=True)
    elif action=='paid':
        if d.current_report_id and d.current_report.payment_tracking:raise ValidationError('결제 요청에서 품목을 선택해 결제 완료를 등록해 주세요.')
        if not (finance_assigned(actor,d) or actor.profile.is_representative and d.current_report_id and d.current_report.representative_id==actor.pk):raise PermissionDenied
        if d.status!='allowed':raise ValidationError('대표님이 구매승인를 확정한 품목만 결제 완료로 기록할 수 있습니다.')
        if not reason:raise ValidationError('결제 확인 내용을 입력해 주세요.')
        d.status,d.paid_at='paid',now;event(actor,'결제 완료 확인',request=d,detail=reason)
        notify([d.owner],f'{d.product} · 결제 완료, 물품 수령을 확인해 주세요.',request=d)
    elif action=='receive':
        if d.owner_id!=actor.pk:raise PermissionDenied
        if d.status not in ['allowed','paid']:raise ValidationError('구매승인이 완료된 뒤 받은 수량을 등록할 수 있습니다.')
        remaining=d.remaining_quantity
        if settings.INTEGRATED_PURCHASES:quantity=None
        try:count=remaining if quantity is None else int(quantity)
        except (ValueError,TypeError):raise ValidationError('이번에 수령한 수량을 입력해 주세요.')
        if quantity is not None and (isinstance(quantity,bool) or str(quantity).strip()!=str(count)):raise ValidationError('수령 수량은 정수로 입력해 주세요.')
        if not 1<=count<=remaining:raise ValidationError('수령 수량은 1개 이상, 미수령 수량 이내로 입력해 주세요.')
        try:key=UUID(str(receipt_key)) if receipt_key else uuid4()
        except (ValueError,TypeError,AttributeError):raise ValidationError('수령 화면을 다시 열어 주세요.')
        if PurchaseReceipt.objects.filter(key=key).exists():raise ValidationError('이미 처리한 수령 확인입니다.')
        location=d.storage_location if storage_location is None else str(storage_location).strip()
        if len(location)>150:raise ValidationError('보관 위치는 150자 이내로 입력해 주세요.')
        PurchaseReceipt.objects.create(request=d,received_by=actor,quantity=count,location=location,note=reason,key=key)
        d.received_quantity+=count;d.storage_location=location
        if d.remaining_quantity==0:d.status,d.received_at='received',now
        event(actor,'물품 수령 완료' if d.status=='received' else '물품 부분 수령',request=d,detail=f'이번 수령 {count}개 / 누적 {d.received_quantity}개 / 미수령 {d.remaining_quantity}개'+(f' / 보관 위치 {location}' if location else ''))
        notify([u for u in finance_users(p) if finance_assigned(u,d)],f'{d.product} · '+('수령 완료' if d.status=='received' else '일부 수령')+f' · {actor.first_name}',request=d)
    else:raise ValidationError('지원하지 않는 처리입니다.')
    d.revision+=1;d.save();return d


@transaction.atomic
def submit_report(actor,ids,title,note,key):
    p=lock_policy();actor=actor_now(actor);require_finance(actor);validate_policy_people(p)
    if not title.strip() or len(title)>180 or not note.strip() or len(note)>1000:raise ValidationError('구매요청 제목과 내용을 입력해 주세요.')
    try:key=UUID(str(key));ids=[int(x) for x in ids]
    except (ValueError,TypeError,AttributeError):raise ValidationError('선택 품목을 다시 확인해 주세요.')
    if not ids or len(ids)>100 or len(set(ids))!=len(ids) or any(x<1 or x>9223372036854775807 for x in ids):raise ValidationError('중복 없이 1~100개 품목을 선택해 주세요.')
    if PurchaseReport.objects.filter(request_key=key).exists():raise ValidationError('이미 제출한 구매요청입니다.')
    docs=list(PurchaseRequest.objects.select_for_update().filter(pk__in=ids).order_by('pk').select_related('owner'))
    if len(docs)!=len(ids) or any(d.status not in ['ready','hold','reapproval'] or d.status=='hold' and not d.hold_ready or not d.confirmed_at or not finance_assigned(actor,d) for d in docs):
        raise ValidationError('이미 요청했거나 구매 내용 확인이 끝나지 않은 품목이 있습니다. 목록을 새로고침해 주세요.')
    report=PurchaseReport.objects.create(created_by=actor,representative=p.representative,title=title.strip(),note=note.strip(),request_key=key,payment_tracking=settings.INTEGRATED_PURCHASES)
    for d in docs:
        snapshot=serialize_request(d)
        if d.status=='reapproval':
            change=d.amendments.first()
            snapshot['amendment']=dict(before=change.before,reason=change.reason,previous_report=change.previous_report.number)
        elif d.status=='hold':snapshot['hold_followup']=dict(reason=d.decision_reason,note=d.hold_note)
        PurchaseReportItem.objects.create(report=report,request=d,snapshot=snapshot)
        d.status,d.current_report,d.decision_reason='ceo',report,'';d.hold_ready=False;d.revision+=1;d.save()
        event(actor,'대표 결제요청' if report.payment_tracking else '대표 구매요청',request=d,report=report,detail=report.number)
        notify([d.owner],f'{d.product} · 대표님께 구매요청 완료',request=d)
    event(actor,'구매요청 제출',report=report,detail=note)
    notify([report.representative],f'{report.title} · '+('결제할 구매 내역이 등록되었습니다.' if report.payment_tracking else f'{len(docs)}개 품목 구매요청'),report=report)
    return report


@transaction.atomic
def decide_report(pk,actor,decisions,revision,final=False):
    p=lock_policy();actor=actor_now(actor)
    report=PurchaseReport.objects.select_for_update().get(pk=pk)
    if report.payment_tracking:raise PermissionDenied('대표님은 구매 내역을 조회합니다. 결제 결과는 구매 담당자가 등록합니다.')
    if actor.pk!=report.representative_id or not actor.profile.is_representative or settings.INTEGRATED_PURCHASES and not actor.profile.representative_can_approve:raise PermissionDenied
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
            if d.status!='ceo' or d.current_report_id!=report.pk:raise ValidationError('요청 품목의 진행 상태가 바뀌었습니다. 다시 확인해 주세요.')
            d.status={'allow':'allowed','deny':'denied','hold':'hold'}[item.decision]
            d.decision_reason=item.reason;d.permitted_at=now;d.completion_unread=item.decision=='allow';d.hold_ready=False;d.hold_note='';d.revision+=1;d.save()
            event(actor,'대표 '+item.get_decision_display(),request=d,report=report,detail=item.reason)
            notify([d.owner],f'{d.product} · '+(f'{actor.first_name}님의 최종 결재가 완료되었습니다.' if item.decision=='allow' else f'{actor.first_name}님 '+item.get_decision_display()+' · '+item.reason),request=d,owner_update=True)
            notify([u for u in finance_users(p) if finance_assigned(u,d)],f'{d.product} · 대표 {item.get_decision_display()}'+(f' · {item.reason}' if item.reason else ''),request=d)
        report.status,report.decided_at='decided',now
        event(actor,'구매 검토 결과 확정',report=report)
    else:event(actor,'품목별 검토 임시저장',report=report)
    report.revision+=1;report.save();return report


@transaction.atomic
def supplement_request(pk,actor,values,revision):
    lock_policy();actor=actor_now(actor)
    d=PurchaseRequest.objects.select_for_update().get(pk=pk)
    if actor.pk!=d.owner_id:raise PermissionDenied
    if d.status!='supplement' or d.revision!=revision:raise ValidationError('보완 상태가 바뀌었습니다. 문서를 다시 열어 주세요.')
    supplement=d.supplements.select_for_update().filter(resolved_at=None).first()
    if not supplement:raise ValidationError('보완 요청 내역이 없습니다.')
    # Descriptive information only: approved items, quantity and price cannot be silently changed.
    reason=str(values.get('reason') or '').strip();url=str(values.get('url') or '').strip();response=str(values.get('response') or '').strip()
    if not reason or not response or len(response)>1000:raise ValidationError('구매 사유와 보완 내용을 입력해 주세요.')
    d.reason,d.url=reason,url;d.full_clean()
    supplement.after=serialize_request(d);supplement.response=response;supplement.resolved_at=timezone.now();supplement.save()
    d.status='ready';d.decision_reason='';d.revision+=1;d.save()
    event(actor,'구매요청 보완 완료',request=d,detail=response)
    notify([supplement.requested_by],f'{d.product} · 보완 완료 · 구매 품목을 다시 확인해 주세요.',request=d)
    return d


@transaction.atomic
def amend_amount(pk,actor,quantity,unit_price,reason,revision):
    lock_policy();actor=actor_now(actor)
    d=PurchaseRequest.objects.select_for_update().get(pk=pk)
    if not finance_assigned(actor,d):raise PermissionDenied
    payment_tracking=bool(d.current_report_id and d.current_report.payment_tracking)
    if payment_tracking and d.current_report.created_by_id!=actor.pk:raise PermissionDenied
    if (d.status not in ['ceo','hold'] if payment_tracking else d.status!='allowed') or d.received_quantity or d.paid_at or d.revision!=revision:
        raise ValidationError('수령 전의 구매승인 문서만 금액을 변경할 수 있습니다. 문서를 다시 열어 주세요.')
    reason=str(reason or '').strip()
    if not reason or len(reason)>1000:raise ValidationError('금액 변경 사유를 입력해 주세요.')
    try:
        count=int(quantity);price=Decimal(str(unit_price))
        if str(count)!=str(quantity).strip() or not 1<=count<=999999 or not price.is_finite() or price.as_tuple().exponent < -2 or not Decimal('0')<price<=Decimal('999999999.99'):raise ValueError
    except (ValueError,TypeError,InvalidOperation):raise ValidationError('수량과 단가를 확인해 주세요.')
    before=serialize_request(d);old=d.total
    if d.quantity==count and d.unit_price==price:raise ValidationError('변경된 수량 또는 단가가 없습니다.')
    d.quantity,d.unit_price=count,price
    if d.total>Decimal('999999999999.99'):raise ValidationError('요청 총액이 입력 가능한 범위를 초과합니다.')
    increased=d.total>old
    PurchaseAmendment.objects.create(request=d,changed_by=actor,previous_report=d.current_report,before=before,after=serialize_request(d),reason=reason,requires_reapproval=increased or payment_tracking)
    if payment_tracking:
        report=PurchaseReport.objects.select_for_update().get(pk=d.current_report_id)
        item=report.items.select_for_update().get(request=d)
        if item.decision not in ['pending','hold']:raise ValidationError('이미 결제·반려 처리된 품목입니다. 다시 확인해 주세요.')
        item.decision='hold';item.reason=('금액 변경으로 다시 결제 요청: '+reason)[:1000];item.processed_by=actor;item.processed_at=timezone.now();item.save()
        report.status='pending' if report.items.filter(decision='pending').exists() else 'decided'
        report.decided_at=None if report.status=='pending' else timezone.now();report.revision+=1;report.save()
        event(actor,'결제 요청 금액 변경',request=d,report=report,detail=f'{old}원 → {d.total}원 / {reason}')
    if increased or payment_tracking:d.status='reapproval';d.completion_unread=False
    d.revision+=1;d.save()
    event(actor,'구매 금액 변경',request=d,detail=f'{old}원 → {d.total}원 / '+('변경 금액으로 다시 결제 요청 필요' if payment_tracking else '금액 증가: 재승인 필요' if increased else '금액 감소: 기존 승인 유지')+' / '+reason)
    notify([d.owner],f'{d.product} · '+('금액 변경으로 구매 진행 중입니다.' if increased else '구매 금액이 변경되었습니다.'),request=d)
    return d
