from django.db.models import Q
from .models import DemoAccount,PurchaseRequest,PurchaseReport
from .access import active,is_admin,is_finance,is_confirmer,requests_for,policy,notices_for,finance_requests

DEMO_ROLES=[('p_quality','기안자'),('p_quality_manager','검토자'),('p_quality_lead','승인자'),('p_prod_director','구매 확인 담당자 · 생산팀 이사'),('p_finance','구매 담당자'),('p_ceo','대표 · 구매승인'),('p_admin','관리자 · 규정·직원 권한')]


def demo_choices():
    accounts={a.user.username:a for a in DemoAccount.objects.select_related('user').filter(user__username__in=[name for name,label in DEMO_ROLES])}
    result=[]
    for name,label in DEMO_ROLES:
        if name in accounts:accounts[name].label=label;result.append(accounts[name])
    return result


def shell(request):
    common=dict(lab=True,shell_styles=['workflow/style.css','workflow/xenosys.css','workflow/workspace.css'])
    if not request.user.is_authenticated or not active(request.user):return common
    u=request.user;finance=is_finance(u);checker=is_confirmer(u)
    result=dict(**common,lab_admin=is_admin(u),lab_finance=finance,lab_confirmer=checker,demo_accounts=demo_choices(),lab_policy=policy(),
        counts=dict(own_completed=PurchaseRequest.objects.filter(owner=u,completion_unread=True).count(),hold=finance_requests(u).filter(status='hold').count() if finance else 0,pending=PurchaseRequest.objects.filter(Q(status='review',reviewer=u)|Q(status='approval',approver=u)|Q(status='director',director=u)).count(),
                    completed=PurchaseRequest.objects.filter(status__in=['ready','hold'],confirmed_at=None).exclude(owner=u).count() if checker else 0,
                    finance=finance_requests(u).filter(Q(status__in=['ready','reapproval'])|Q(status='hold',hold_ready=True)).filter(confirmed_at__isnull=False).count() if finance else 0,
                    representative=PurchaseReport.objects.filter(status='pending',representative=u).count(),notices=notices_for(u).filter(read=False).count()))

    cards=[]
    if result['counts']['pending'] or u.username in ['p_quality_manager','p_quality_lead']:
        cards.append(dict(title='검토·승인할 요청',key='pending',count=result['counts']['pending'],url='/purchase-lab/requests/?mode=inbox',note='구매 내용을 확인하고 다음 담당자에게 전달하세요.'))
    if checker:cards.append(dict(title='구매 내용 확인',key='completed',count=result['counts']['completed'],url='/purchase-lab/requests/?mode=completed&stage=confirm',note='내부 승인이 끝난 요청을 확인해 주세요.'))
    if finance:cards.append(dict(title='모아서 구매요청',key='finance',count=result['counts']['finance'],url='/purchase-lab/requests/?mode=finance',note='확인된 품목을 선택해 대표님께 요청하세요.'))
    if u.profile.is_representative:cards.append(dict(title='구매승인 결정',key='representative',count=result['counts']['representative'],url='/purchase-lab/reports/',note='품목별로 승인·반려·보류를 선택해 주세요.'))
    result['work_cards']=cards
    return result
