from django.db import migrations


def convert_stock_requests(apps, schema_editor):
    Document = apps.get_model('workflow', 'Document')
    Audit = apps.get_model('workflow', 'Audit')
    Notice = apps.get_model('workflow', 'Notice')
    Profile = apps.get_model('workflow', 'Profile')
    db = schema_editor.connection.alias
    handlers = list(Profile.objects.using(db).filter(procure=True, approved=True, user__is_active=True).values_list('user_id', flat=True))
    for doc in Document.objects.using(db).filter(kind='stock').iterator():
        before = doc.status
        if doc.status == 'approve':
            doc.status = 'approved' if doc.reviewed_at else 'review'
            doc.approved_at = doc.reviewed_at
        if doc.status == 'draft':
            doc.unit_price, doc.approver_id, doc.url = 0, None, ''
        if doc.title.startswith('구매요청 /'):
            doc.title = doc.title.replace('구매요청 /', '재고요청 /', 1)
        doc.save(using=db)
        Audit.objects.using(db).create(document_id=doc.pk, actor_id=None,
            event='재고 요청 처리 방식 변경',
            detail=f'시스템 업데이트: 검토 완료 후 발주 담당자가 처리하는 흐름으로 전환했습니다. 기존 상태: {before}. 이전 결재·발주 이력은 보관합니다.')
        if before == 'approve' and doc.status == 'approved':
            recipients = set(handlers + [doc.owner_id])
            Notice.objects.using(db).bulk_create([Notice(user_id=user_id, document_id=doc.pk,
                text='기존에 검토가 완료된 생산 재고 요청이 발주대기로 전환되었습니다.') for user_id in recipients])


class Migration(migrations.Migration):
    dependencies = [('workflow', '0002_alter_audit_actor_alter_document_kind')]
    # Keep prior approval/fulfillment history. Restore the pre-update database
    # backup if reverting to the old business workflow is ever necessary.
    operations = [migrations.RunPython(convert_stock_requests)]
