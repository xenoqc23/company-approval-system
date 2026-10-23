from .models import PurchaseRequest
from django.conf import settings

PURCHASING_STATES=('ready','ceo','reapproval')
DISPLAY_LABELS=dict(PurchaseRequest.STATES,ready='승인완료',ceo='대표 결재 대기',allowed='결재완료',paid='결재완료',received='결재완료',reapproval='변경 금액 승인 필요')
REQUESTER_STATES=[('draft','임시저장'),('review','검토 대기'),('approval','승인 대기'),('supplement','보완 요청'),('purchasing','구매 진행 중'),('purchase_approved','구매 승인완료'),('received','수령 완료만 보기'),('hold','구매보류'),('denied','구매반려'),('rejected','내부 결재 반려'),('cancelled','요청 취소')]


def status_tone(status,simplified=False):
    if simplified and status in PURCHASING_STATES:return 'active'
    if status in ['ready','allowed','paid','received']:return 'positive'
    if status in ['review','approval','director','supplement','reapproval','hold','ceo']:return 'waiting'
    if status in ['denied','rejected']:return 'negative'
    return 'muted'



def approval_track(d):
    mode=d.route.get('mode','review_approval')
    finished=d.status in ['ready','supplement','reapproval','ceo','allowed','denied','hold','paid','received']
    direct=d.route.get('workflow')=='department-v3' and d.route.get('request_method')=='direct'
    person=lambda u:u.first_name if u else '미지정'
    cards=[dict(label='기안',person=person(d.owner),done=d.submitted_at is not None,current=d.status=='draft',time=d.submitted_at),
           dict(label='검토' if mode=='review_approval' else '검토 생략',person=person(d.reviewer) if d.reviewer_id else '생략',done=bool(d.reviewed_at or finished or d.status in ['approval','director']),current=d.status=='review',time=d.reviewed_at),
           dict(label='승인' if mode!='direct' else '승인 생략',person=person(d.approver) if d.approver_id else '직접 요청' if mode=='direct' else '검토 후 결정',done=bool(d.intermediate_at or finished),current=d.status=='approval',time=d.intermediate_at or (d.submitted_at if mode=='direct' else None))]
    if d.route.get('workflow')!='separated-v2' and d.director_id:
        cards.append(dict(label='기존 문서 최종승인',person=person(d.director),done=bool(d.director_at or finished),current=d.status=='director',time=d.director_at))
    if direct:cards[2].update(label='승인 생략',person='직접 요청',done=d.submitted_at is not None,time=None)
    if d.route.get('reviewer_final'):
        cards=cards[:2];cards[1].update(label='검토·승인',done=True,current=False,time=d.intermediate_at)
    return cards


def progress(d,simplified=False):
    label=DISPLAY_LABELS[d.status]
    if d.status in PURCHASING_STATES:label='구매 진행 중' if simplified else label
    if d.status=='ready' and not simplified:label=('구매요청 대기' if settings.INTEGRATED_PURCHASES else '대표 요청 대기') if d.confirmed_at else '구매 내용 확인 대기'
    if d.status in ['allowed','paid','received']:label='결재완료'
    who={'denied':'처리 종료','rejected':'처리 종료','cancelled':'처리 종료','received':'처리 완료','allowed':d.owner.first_name,'paid':d.owner.first_name,'supplement':'기안자 · 보완 필요','reapproval':'구매 담당자','draft':'기안자','review':d.reviewer.first_name if d.reviewer else '검토자','approval':d.approver.first_name if d.approver else '승인자','director':d.director.first_name if d.director else '기존 최종승인자'}.get(d.status,'구매 담당자')
    if simplified and d.status=='reapproval':who='구매 담당자'
    note={'draft':'작성 중인 구매요청입니다.','review':'검토자의 확인을 기다리고 있습니다.','approval':'승인자의 확인을 기다리고 있습니다.','director':'기존 문서의 최종승인을 기다리고 있습니다.','ready':'내부 승인이 완료되어 구매를 진행하고 있습니다.','ceo':'구매를 진행하고 있습니다.','supplement':'보완 요청 내용을 확인하고 자료를 보완해 주세요.','reapproval':'변경된 금액의 구매승인을 다시 진행하고 있습니다.','allowed':'구매승인이 완료되었습니다. 물품을 받으셨다면 받은 수량을 등록해 주세요.','paid':'물품을 받으셨다면 받은 수량을 등록해 주세요.','received':'물품 수령까지 완료했습니다.','denied':'구매요청이 반려되었습니다. 아래 사유를 확인해 주세요.','hold':'구매요청이 보류되었습니다. 아래 사유를 확인해 주세요.','rejected':'내부 결재에서 반려되었습니다. 아래 사유를 확인해 주세요.','cancelled':'구매요청을 취소했습니다.'}[d.status]
    note=note.replace('받은 수량을 등록해 주세요.','모두 받으신 뒤 수령 완료를 눌러 주세요.')
    receipt='수령 완료' if d.status=='received' else '수령 대기' if d.status in ['allowed','paid'] else '—'
    return dict(label=label,who=who,note=note,receipt=receipt,tone='waiting' if d.status=='ready' and not simplified else status_tone(d.status,simplified),list_label=label,receipt_tone='positive' if d.status=='received' else 'waiting' if d.status in ['allowed','paid'] else 'muted')


def purchase_progress(d):
    index=0 if not d.confirmed_at and not d.current_report_id else 1 if d.status=='ready' else 1 if d.status=='reapproval' else 2 if d.status in ['ceo','denied','hold'] else 3
    stages=[]
    names=[d.purchase_checker.first_name if d.purchase_checker_id else d.confirmed_by.first_name if d.confirmed_by_id else '구매 확인 담당자',' · '.join(d.purchase_route.get('collector_names',[])) or '구매 담당자',d.current_report.representative.first_name if d.current_report_id else '대표',d.owner.first_name]
    for i,label in enumerate(['구매 내용 확인','구매요청 준비' if settings.INTEGRATED_PURCHASES else '모아서 구매요청','대표 구매승인','물품 수령']):
        done=i<index or i==3 and d.status=='received'
        blocked=i==index and d.status in ['denied','cancelled'];paused=i==index and d.status=='hold'
        legacy=i==0 and not d.confirmed_at and bool(d.current_report_id)
        if i==0 and d.confirmed_at:label=d.get_confirmation_method_display() or '확인완료'
        if legacy:done=False;label='구매 내용 확인 · 이전 기록 없음'
        stages.append(dict(label=label,person=names[i],legacy=legacy,done=done,current=i==index and not done and not blocked,blocked=blocked,paused=paused))
    return stages


def visible_notice(n,user):
    if settings.INTEGRATED_PURCHASES:return n.text
    if n.request_id and n.request.owner_id==user.pk and '구매 승인완료' in n.text:return n.text
    if n.request_id and n.request.owner_id==user.pk and any(word in n.text for word in ['대표','취합','결제','구매 품목 확인','구매 내용 확인']):
        return f'{n.request.product} · 구매 진행상황이 변경되었습니다. 문서에서 확인해 주세요.'
    return n.text


def events_for(d,simplified):
    if not simplified:return d.events.all()
    return d.events.exclude(event__startswith='대표').exclude(event__in=['결제 완료 확인','구매 품목 확인','구매 증빙 첨부','보류 품목 재보고 준비','승인 시 구매 내용 함께 확인'])


def pending_columns(d):
    approved=d.status in ['ready','supplement','reapproval','ceo','allowed','denied','hold','paid','received']
    confirm='보완 대기' if d.status=='supplement' else '구매 내용 확인 대기' if approved and not d.confirmed_at and not d.current_report_id else '확인완료' if d.confirmed_at else '이전 진행 문서' if d.current_report_id else '—'
    collect='구매요청 작성 대기' if d.status in ['ready','reapproval'] and d.confirmed_at else '다시 요청할 품목' if d.status=='hold' and d.confirmed_at else '요청 완료' if d.current_report_id else '—'
    if d.confirmed_at:confirm=d.get_confirmation_method_display() or '확인완료'
    return dict(confirm_who=d.confirmed_by.first_name if d.confirmed_by_id else d.owner.first_name if d.confirmation_method=='director_request' else '',confirm_done=bool(d.confirmed_at),collect_done=bool(d.current_report_id and d.status not in ['hold','reapproval']),approval='직접 요청' if d.route.get('workflow')=='department-v3' and d.route.get('request_method')=='direct' else '승인완료' if approved else d.get_status_display(),confirm=confirm,collect=collect)


def task_for(d,user,permissions):
    if permissions.get('can_forward'):
        return dict(kind='review',message='내용을 확인하고 승인완료하거나 승인자에게 전달해 주세요.' if permissions.get('can_review_final') else '내용을 확인하고 승인자를 지정해 전달해 주세요.')
    if permissions['can_approve']:
        return dict(kind='approve',message='구매 내용을 확인하고 승인자에게 전달해 주세요.' if d.status=='review' else '구매 내용을 확인하고 내부 승인을 완료해 주세요.')
    if permissions['can_confirm']:return dict(kind='confirm',message='구매 내용을 확인하면 구매 담당자에게 전달됩니다.')
    if permissions['can_supplement']:return dict(kind='supplement',message='요청받은 자료를 보완한 뒤 다시 제출해 주세요.')
    if permissions['can_prepare_hold']:
        return dict(kind='collect_hold' if d.hold_ready else 'hold',message='보완이 끝났습니다. 품목을 선택해 다시 구매요청해 주세요.' if d.hold_ready else '보류 사유를 확인하고, 보완한 내용을 기록해 주세요.')
    if permissions['can_collect']:return dict(kind='collect',message='구매할 품목을 모아 대표님께 구매승인을 요청해 주세요.')
    if permissions['can_decide_purchase']:return dict(kind='decide',message='요청된 품목을 확인하고 승인·반려·보류를 선택해 주세요.')
    if user.profile.is_representative:return dict(kind='done' if d.status in ['allowed','paid','received','denied'] else 'waiting',message='대표 결재 결과를 확인해 주세요.')
    if permissions['can_receive']:return dict(kind='receive',message='요청한 물품을 모두 받으셨다면 수령 완료를 눌러 주세요.')
    if d.status=='received':return dict(kind='done',message='구매승인과 물품 수령이 모두 완료되었습니다.')
    if d.status in ['denied','rejected','cancelled']:return dict(kind='done',message='요청이 종료되었습니다. 처리 사유를 확인해 주세요.')
    if d.status=='hold':return dict(kind='waiting',message='구매가 보류되었습니다. 보류 사유를 확인해 주세요.')
    if d.status=='supplement':return dict(kind='waiting',message='기안자가 요청받은 자료를 보완 중입니다.')
    if d.status=='draft' and d.owner_id==user.pk:return dict(kind='draft',message='작성 중인 구매요청을 이어서 작성해 주세요.')
    if d.status in ['allowed','paid']:return dict(kind='waiting',message='최종 결재가 완료되었습니다. 기안자의 수령 확인을 기다리고 있습니다.')
    return dict(kind='waiting',message='담당자가 처리 중입니다. 지금은 진행상황을 확인해 주세요.')
