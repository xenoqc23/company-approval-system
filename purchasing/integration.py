"""Shared application adapters: shared workflow shell, lists and separate notice cursors.

Purchase sources stay in their own transactional tables. Historical workflow
purchases are never converted or re-approved by these adapters.
"""
from datetime import date
from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from .access import active, requests_for, notices_for, reports_for, is_finance, is_confirmer
from .models import PurchaseRequest,PurchaseNotice
from .progress import progress, visible_notice


def shell(request):
    if not settings.INTEGRATED_PURCHASES:return {}
    common=dict(integrated_purchases=True,purchase_demo_enabled=settings.PURCHASE_LAB_ENABLED and not settings.PRODUCTION,purchase_base_template='purchasing/integrated_base.html',purchase_page=request.path.startswith('/purchases/'))
    if not request.user.is_authenticated or not active(request.user):return common
    from .context import shell as purchase_shell
    data=purchase_shell(request);data.update(common)
    # Existing workflow context owns balance/profile/global notification totals.
    data['purchase_work_cards']=data.pop('work_cards',[])
    for card in data['purchase_work_cards']:
        card['url']=card['url'].replace('/purchase-lab/','/purchases/')
        if card['key']=='finance':card.update(title='구매요청 준비',url=reverse('purchasing:reports'))
        elif card['key']=='pending':card['url']=reverse('documents')+'?mode=pending'
    if request.path=='/staff/' and data['lab_admin']:
        from .forms import PurchaseAssignmentsForm
        data['purchase_assignments_form']=PurchaseAssignmentsForm()
    return data


def list_requests(user, mode, params):
    qs=requests_for(user).select_related('owner','reviewer','approver','purchase_checker')
    if mode=='mine':qs=qs.filter(owner=user).exclude(status='draft')
    elif mode=='drafts':qs=qs.filter(owner=user,status='draft')
    elif mode=='pending':qs=qs.filter(Q(status='review',reviewer=user)|Q(status='approval',approver=user))
    elif mode=='completed':
        qs=qs.filter(owner=user,status__in=['allowed','paid','received'])
        if params.get('unread')=='1':qs=qs.filter(completion_unread=True)
    elif mode=='archive':qs=qs.filter(owner=user,status__in=['denied','rejected','cancelled'])
    elif mode=='receive':qs=qs.filter(owner=user,status__in=['allowed','paid','received'])
    elif mode=='history':qs=qs.filter(events__actor=user,events__event__in=['검토 완료','최종 승인완료','내부 승인완료','승인 시 구매 내용 함께 확인']).distinct()
    elif mode=='search':
        if not params.get('q','').strip():return qs.none()
    elif mode=='all':pass  # The workflow view has already enforced the administrator gate.
    else:return qs.none()
    if params.get('kind') and params['kind']!='office':return qs.none()
    search=params.get('q','').strip()[:120]
    if search:qs=qs.filter(Q(product__icontains=search)|Q(number__icontains=search)|Q(owner__first_name__icontains=search)|Q(vendor__icontains=search))
    groups={'draft':['draft'],'review':['review','approval'],'approve':['approval'],'approved':['allowed','paid','received'],
        'purchasing':['ready','reapproval','ceo'],'hold':['hold'],'rejected':['rejected','denied'],'cancelled':['cancelled']}
    state=params.get('status','')
    if state:
        if state not in groups:return qs.none()
        qs=qs.filter(status__in=groups[state])
    if params.get('shipment')=='received':qs=qs.filter(status='received')
    elif params.get('shipment'):return qs.none()
    for key,lookup in [('from','created_at__date__gte'),('to','created_at__date__lte')]:
        try:
            if params.get(key):qs=qs.filter(**{lookup:date.fromisoformat(params[key])})
        except ValueError:pass
    return qs


def row(d,user,unread=False):
    p=progress(d,simplified=True)
    d.kind='office';d.get_kind_display=lambda:'구매요청서';d.type_label='구매요청서'
    d.title=d.product;d.status_label=p['list_label'];d.shipment_label=p['receipt']
    d.integration_url=reverse('purchasing:edit' if d.status=='draft' else 'purchasing:detail',args=[d.pk])
    d.has_owner_unseen=d.owner_id==user.pk and d.completion_unread
    d.has_new_notice=unread
    d.progress_info=p
    return d


def merge_rows(old, new, user, limit=100):
    old=list(old)
    for d in old:d.integration_url=reverse('detail',args=[d.pk])
    new=list(new)
    unread=set(PurchaseNotice.objects.filter(user=user,read=False,request_id__in=[d.pk for d in new]).values_list('request_id',flat=True))
    docs=old+[row(d,user,d.pk in unread) for d in new]
    return sorted(docs,key=lambda d:(d.created_at,d.pk),reverse=True)[:limit]


def purchase_summary(user, after=None):
    from .context import shell as purchase_shell
    qs=notices_for(user)
    latest=qs.order_by('-pk').values_list('pk',flat=True).first() or 0
    incoming=[]
    if after is not None:
        for n in qs.filter(pk__gt=after,read=False).order_by('pk')[:20]:
            incoming.append(dict(id='purchase-'+str(n.pk),text=visible_notice(n,user),url=reverse('purchasing:detail',args=[n.request_id]) if n.request_id else reverse('purchasing:report_detail',args=[n.report_id])))
    # Counters are also used by the existing shared sidebar and popup reminder.
    from types import SimpleNamespace
    counts=purchase_shell(SimpleNamespace(user=user))['counts']
    return dict(latest=latest,cursor=int(incoming[-1]['id'].split('-')[-1]) if incoming else latest,events=incoming,
        unread=qs.filter(read=False).count(),waiting=counts['pending'],completed=counts['own_completed'],counts=counts)


def filter_states(mode):
    groups={
        'draft':dict(status='draft'),
        'internal':dict(status__in=['review','approval','director']),
        'purchasing':dict(status__in=['ready','supplement','reapproval','ceo']),
        'approved':dict(status__in=['allowed','paid','received']),
        'received':dict(status='received'),
        'hold':dict(status='hold'),
        'closed':dict(status__in=['denied','rejected','cancelled']),
        'confirm_wait':dict(status__in=['ready','supplement'],confirmed_at__isnull=True),
        'confirmed':dict(confirmed_at__isnull=False),
    }
    labels=[('draft','작성 중'),('internal','검토·승인 중'),('purchasing','구매 진행 중'),('approved','구매 승인완료'),('received','수령 완료'),('hold','보류'),('closed','반려·취소')]
    if mode=='completed':labels=[('confirm_wait','확인 대기'),('confirmed','확인완료'),('hold','보류')]
    if mode=='inbox':labels=[('internal','검토·승인 중')]
    return labels,{k:groups[k] for k,label in labels}


def validate_staff_change(user,post):
    from .access import policy
    from .services import lock_policy
    from django.core.exceptions import ValidationError
    # Called inside the existing staff transaction; use the purchasing lock too.
    p=lock_policy()
    valid=post.get('approved')=='on' and post.get('active')=='on'
    if user.pk in [p.dev_director_id,p.production_director_id]:
        dept='개발팀' if user.pk==p.dev_director_id else '생산팀'
        if not valid or post.get('department')!=dept or post.get('rank')!='이사':raise ValidationError('먼저 구매 업무 담당자를 다른 직원으로 변경한 뒤 부서·직급·활성화를 변경해 주세요.')
    if not valid and (p.finance.filter(pk=user.pk).exists() or PurchaseRequest.objects.filter(purchase_checker=user,confirmed_at=None,status__in=['review','approval','ready','supplement']).exists()):raise ValidationError('구매 업무 권한 또는 진행 문서가 남아 있습니다. 담당 업무를 정리한 뒤 비활성화해 주세요.')
