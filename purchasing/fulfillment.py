"""Live receipts stay separate from immutable purchase-approval snapshots."""
def receipt_info(d):
    if d.status not in ['allowed','paid','received']:
        return dict(label='수령 대상 아님' if d.status in ['denied','rejected','cancelled'] else '구매승인 전',tone='muted',eligible=False)
    rows=list(d.receipts.all());last=rows[-1] if rows else None
    return dict(label='수령 완료' if d.status=='received' else '일부 수령' if d.received_quantity else '수령 대기',tone='positive' if d.status=='received' else 'active' if d.received_quantity else 'waiting',eligible=True,received=d.received_quantity,quantity=d.quantity,who=last.received_by.first_name if last else '',at=last.created_at if last else d.received_at)


def report_fulfillment(report,items):
    counts=dict(approved=0,denied=0,hold=0,pending=0,eligible=0,done=0,partial=0,waiting=0,changed=0)
    for item in items:
        counts[{'allow':'approved','deny':'denied','hold':'hold','pending':'pending'}[item.decision]]+=1;d=item.request
        if report.status!='decided' or item.decision!='allow':item.receipt_info=dict(label='구매승인 전' if report.status!='decided' else '수령 대상 아님',tone='muted',eligible=False)
        elif d.current_report_id!=report.pk or d.status not in ['allowed','paid','received']:
            item.receipt_info=dict(label='변경 후 다시 요청',tone='waiting',eligible=False);counts['changed']+=1
        else:
            item.receipt_info=receipt_info(d);counts['eligible']+=1
            counts['done' if d.status=='received' else 'partial' if d.received_quantity else 'waiting']+=1
    return counts
