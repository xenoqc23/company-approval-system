"""Accounting records actual payments; representatives only read new requests."""
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from .access import finance_assigned, reports_for, require_finance
from .models import PurchaseReport, PurchaseRequest, PurchaseNotice
from .services import actor_now, lock_policy, event, notify


@transaction.atomic
def process_payment(report_id, actor, item_ids, action, reason, revision, *, apply=False):
    lock_policy()
    actor=actor_now(actor)
    require_finance(actor)
    report=PurchaseReport.objects.select_for_update().get(pk=report_id)
    if not report.payment_tracking or not reports_for(actor).filter(pk=report.pk).exists():raise PermissionDenied
    if report.revision!=revision:raise ValidationError('다른 창에서 처리 내용이 바뀌었습니다. 새로고침 후 다시 확인해 주세요.')
    if action not in ['paid','deny','hold','undo']:raise ValidationError('처리 방법을 선택해 주세요.')
    raw=[str(value) for value in item_ids]
    if not raw or len(raw)>100 or len(set(raw))!=len(raw) or any(not value.isascii() or not value.isdigit() or len(value)>18 or int(value)<1 for value in raw):raise ValidationError('처리할 품목을 중복 없이 선택해 주세요.')
    reason=str(reason or '').strip()
    if len(reason)>1000 or action in ['deny','hold','undo'] and not reason:raise ValidationError('반려·보류·결제 등록 취소에는 1~1000자의 사유가 필요합니다.')
    items=list(report.items.select_for_update().filter(pk__in=[int(value) for value in raw]).order_by('pk'))
    if len(items)!=len(raw):raise ValidationError('이 결제 요청에 포함된 품목만 선택해 주세요.')
    docs={d.pk:d for d in PurchaseRequest.objects.select_for_update().filter(pk__in=[i.request_id for i in items]).order_by('pk')}
    for item in items:
        d=docs[item.request_id]
        if not finance_assigned(actor,d):raise PermissionDenied
        if d.current_report_id!=report.pk:raise ValidationError('다른 결제 요청으로 이동한 품목입니다. 화면을 다시 열어 주세요.')
        if action=='undo':
            if item.decision!='allow' or d.status!='paid' or not d.paid_at or d.received_quantity:raise ValidationError('아직 수령하지 않은 결제 완료 품목만 등록을 취소할 수 있습니다.')
        elif item.decision!='pending' or d.status!='ceo' or d.paid_at:raise ValidationError('이미 처리된 품목입니다. 새로고침 후 확인해 주세요.')
    summary=dict(report=report,items=items,total=sum((i.total for i in items),Decimal('0')),action=action,reason=reason,revision=revision,
        action_label={'paid':'결제 완료','deny':'반려','hold':'보류','undo':'결제 완료 등록 취소'}[action])
    if not apply:return summary
    now=timezone.now()
    for item in items:
        d=docs[item.request_id]
        if action=='undo':
            previous=f'{item.processed_by.first_name if item.processed_by_id else ""} / {item.processed_at}'
            d.status='ceo';d.paid_at=None;d.permitted_at=None;d.completion_unread=False;d.decision_reason=''
            item.decision='pending';item.reason='';item.processed_by=None;item.processed_at=None
            PurchaseNotice.objects.filter(request=d,user=d.owner,read=False,text__contains='최종결재가 완료').update(read=True)
            event(actor,'결제 완료 등록 취소',request=d,report=report,detail=f'{reason}\n이전 등록: {previous}')
            notify([d.owner],f'{d.product} · 최종결재완료 처리가 정정되었습니다. {reason}',request=d,owner_update=True)
        else:
            item.decision={'paid':'allow','deny':'deny','hold':'hold'}[action]
            item.reason=reason;item.processed_by=actor;item.processed_at=now
            d.status={'paid':'paid','deny':'denied','hold':'hold'}[action]
            d.decision_reason=reason if action!='paid' else '';d.hold_ready=False;d.hold_note=''
            d.completion_unread=action=='paid'
            if action=='paid':d.paid_at=now;d.permitted_at=now
            event(actor,{'paid':'결제 완료 확인','deny':'구매 반려','hold':'구매 보류'}[action],request=d,report=report,detail=reason or '대표님 결제 사실을 확인하고 등록')
            notify([d.owner],f'{d.product} · '+('최종결재가 완료되었습니다.' if action=='paid' else ('구매요청이 반려되었습니다. ' if action=='deny' else '구매요청이 보류되었습니다. ')+reason),request=d,owner_update=True)
        d.revision+=1;d.save();item.save()
    pending=report.items.filter(decision='pending').exists()
    report.status='pending' if pending else 'decided';report.decided_at=None if pending else now
    report.revision+=1;report.save()
    event(actor,summary['action_label'],report=report,detail=f'{len(items)}개 품목 / {summary["total"]}원'+(f' / {reason}' if reason else ''))
    return summary
