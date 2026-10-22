from .models import PurchaseRequest


def progress(d):
    mode=d.route.get('mode')
    if not mode:
        from .access import policy
        from .services import mode_for
        p=policy();mode=mode_for(p,d.owner) if p else 'direct'
    internal='내부 결재 생략' if mode=='direct' else '중간 승인' if mode=='approval' else '검토 · 중간 승인'
    index={'draft':0,'review':1,'approval':1,'director':2,'ready':3,'ceo':4,
           'allowed':5,'denied':4,'hold':4,'paid':5,'received':5,'rejected':1,'cancelled':0}[d.status]
    labels=['요청 작성',internal,'담당 이사 최종승인','경리 취합','대표 구매허가','결제 · 수령']
    stages=[]
    for i,label in enumerate(labels):
        skipped=i==1 and mode=='direct'
        done=(i<index or i==0 and d.submitted_at is not None or i==1 and skipped and d.submitted_at is not None or i==5 and d.status=='received')
        blocked=i==index and d.status in ['denied','rejected','cancelled']
        paused=i==index and d.status=='hold'
        stages.append(dict(label=label,done=done,current=i==index and not done and not blocked,
                           skipped=skipped,blocked=blocked,paused=paused))
    who={'draft':'기안자','review':d.reviewer.first_name if d.reviewer else '검토자',
         'approval':d.approver.first_name if d.approver else '승인자','director':d.director.first_name if d.director else '담당 이사',
         'ready':'경리 취합 담당자','ceo':'대표님','allowed':'대표 결제 확인 대기','denied':'구매불허로 종료',
         'hold':'경리 재보고 대기','paid':'요청자 수령 확인 대기','received':'완료','rejected':'요청자 수정 후 재요청','cancelled':'취소로 종료'}[d.status]
    notes={
        'review':'검토자의 확인을 기다리고 있습니다.', 'approval':'중간 승인자의 확인을 기다리고 있습니다.',
        'director':'담당 이사님의 최종승인을 기다리고 있습니다. 아직 경리 취합 대상이 아닙니다.',
        'ready':'부서 승인이 끝났습니다. 경리가 대표님께 보고할 품목을 취합하고 있습니다. 아직 구매허가 전입니다.',
        'ceo':'취합 구매허가 요청서에 포함되었습니다. 대표님이 이 품목을 개별 심사 중입니다.',
        'allowed':'대표님이 이 품목의 구매를 허가했습니다. 실제 결제 완료와는 별도입니다.',
        'denied':'대표님이 이 품목의 구매를 허가하지 않았습니다. 아래 사유를 확인해 주세요.',
        'hold':'대표님이 이 품목의 결정을 보류했습니다. 아래 사유를 확인하고 경리 담당자와 재보고를 진행하세요.',
        'paid':'실제 결제 완료가 확인되었습니다. 물품을 받으면 수령 완료를 눌러 주세요.',
        'received':'물품 수령까지 완료했습니다.', 'rejected':'내부 결재에서 반려되었습니다. 사유를 확인하고 새 구매요청을 작성해 주세요.',
        'cancelled':'기안자가 요청을 취소했습니다.', 'draft':'작성 중인 구매요청입니다. 제출 후 결재가 시작됩니다.'}
    return dict(stages=stages,who=who,note=notes[d.status],label=d.get_status_display())
