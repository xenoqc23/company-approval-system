from .models import PurchaseRequest

PURCHASING_STATES=('ready','ceo','allowed','paid')
REQUESTER_STATES=tuple((key,label) for key,label in PurchaseRequest.STATES if key not in PURCHASING_STATES)+(('purchasing','구매 진행 중'),)


def approval_track(d):
    mode=d.route.get('mode','review_approval')
    finished=d.status in ['ready','ceo','allowed','denied','hold','paid','received']
    person=lambda u:u.first_name if u else '미지정'
    cards=[dict(label='기안',person=person(d.owner),done=d.submitted_at is not None,current=d.status=='draft',time=d.submitted_at),
           dict(label='검토' if mode=='review_approval' else '검토 생략',person=person(d.reviewer) if d.reviewer_id else '생략',done=bool(d.reviewed_at or finished or d.status in ['approval','director']),current=d.status=='review',time=d.reviewed_at),
           dict(label='승인' if mode!='direct' else '본인 전결',person=person(d.approver) if d.approver_id else person(d.owner) if mode=='direct' else '검토 후 결정',done=bool(d.intermediate_at or finished),current=d.status=='approval',time=d.intermediate_at or (d.submitted_at if mode=='direct' else None))]
    if d.route.get('workflow')!='separated-v2' and d.director_id:
        cards.append(dict(label='기존 문서 최종승인',person=person(d.director),done=bool(d.director_at or finished),current=d.status=='director',time=d.director_at))
    return cards


def progress(d,simplified=False):
    label=d.get_status_display()
    if d.status in PURCHASING_STATES:label='구매 진행 중' if simplified else '승인완료' if d.status=='ready' else label
    who={'draft':'기안자','review':d.reviewer.first_name if d.reviewer else '검토자','approval':d.approver.first_name if d.approver else '승인자','director':d.director.first_name if d.director else '기존 최종승인자'}.get(d.status,'구매 담당자')
    note={'draft':'작성 중인 구매요청입니다.','review':'검토자의 확인을 기다리고 있습니다.','approval':'승인자의 확인을 기다리고 있습니다.','director':'기존 문서의 최종승인을 기다리고 있습니다.','ready':'내부 승인이 완료되어 구매를 진행하고 있습니다.','ceo':'구매를 진행하고 있습니다.','allowed':'구매를 진행하고 있습니다.','paid':'물품을 받으셨다면 받은 수량을 입력해 수령 확인을 눌러 주세요.','received':'물품 수령까지 완료했습니다.','denied':'구매요청이 반려되었습니다. 아래 사유를 확인해 주세요.','hold':'구매요청이 보류되었습니다. 아래 사유를 확인해 주세요.','rejected':'내부 결재에서 반려되었습니다. 아래 사유를 확인해 주세요.','cancelled':'구매요청을 취소했습니다.'}[d.status]
    return dict(label=label,who=who,note=note)


def purchase_progress(d):
    index=0 if not d.confirmed_at and not d.current_report_id else 1 if d.status=='ready' else 2 if d.status in ['ceo','denied','hold'] else 3
    stages=[]
    names=[d.confirmed_by.first_name if d.confirmed_by_id else '구매 품목확인자',' · '.join(d.purchase_route.get('collector_names',[])) or '취합·보고 담당자',d.current_report.representative.first_name if d.current_report_id else '대표','구매 담당자']
    for i,label in enumerate(['구매 품목 확인','취합·보고','대표 구매승인','결제·수령']):
        done=i<index or i==3 and d.status=='received'
        blocked=i==index and d.status in ['denied','cancelled'];paused=i==index and d.status=='hold'
        legacy=i==0 and not d.confirmed_at and bool(d.current_report_id)
        if legacy:done=False;label='구매 품목 확인 · 이전 기록 없음'
        stages.append(dict(label=label,person=names[i],legacy=legacy,done=done,current=i==index and not done and not blocked,blocked=blocked,paused=paused))
    return stages


def visible_notice(n,user):
    if n.request_id and n.request.owner_id==user.pk and any(word in n.text for word in ['대표','취합','결제','구매 품목 확인']):
        return f'{n.request.product} · 구매 진행상황이 변경되었습니다. 문서에서 확인해 주세요.'
    return n.text


def events_for(d,simplified):
    if not simplified:return d.events.all()
    return d.events.exclude(event__startswith='대표').exclude(event__in=['결제 완료 확인','구매 품목 확인','구매 증빙 첨부'])


def pending_columns(d):
    approved=d.status in ['ready','ceo','allowed','denied','hold','paid','received']
    confirm='구매 품목 확인 대기' if approved and not d.confirmed_at and not d.current_report_id else '확인완료' if d.confirmed_at else '이전 진행 문서' if d.current_report_id else '—'
    collect='취합·보고 대기' if d.status=='ready' and d.confirmed_at else '재보고 대기' if d.status=='hold' and d.confirmed_at else '보고완료' if d.current_report_id else '—'
    return dict(approval='승인완료' if approved else d.get_status_display(),confirm=confirm,collect=collect)
