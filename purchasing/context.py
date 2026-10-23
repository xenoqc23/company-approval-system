from django.db.models import Q
from django.conf import settings
from .models import DemoAccount,PurchaseRequest,PurchaseReport
from .access import active,is_admin,is_finance,is_confirmer,requests_for,policy,notices_for,finance_requests,checker_requests

LEGACY_ROLES=[('p_quality','기안자'),('p_quality_manager','검토자'),('p_quality_lead','승인자'),('p_prod_director','구매 확인 담당자 · 생산팀 이사'),('p_finance','구매 담당자'),('p_ceo','대표 · 구매 진행현황'),('p_admin','관리자 · 규정·직원 권한')]

DEMO_ROLES=[('p_quality','그 외 부서 · 기안자'),('p_quality_manager','그 외 부서 · 과장·검토자'),('p_quality_lead','그 외 부서 · 승인자'),('p_prod_director','생산팀 이사 · 구매 확인'),('p_dev_manager','개발팀 · 과장·기안자'),('p_dev_lead','개발팀 · 검토자'),('p_dev_director','개발팀 이사 · 구매 확인'),('p_finance','구매 담당자'),('p_ceo','대표 · 구매 진행현황'),('p_admin','관리자 · 규정 설정')]


def demo_choices():
    if settings.PRODUCTION or not settings.PURCHASE_LAB_ENABLED:return []
    p=policy();roles=DEMO_ROLES if p and p.department_routing else LEGACY_ROLES
    if settings.LOCAL_DEMO_ENABLED:roles=[('admin' if name=='p_admin' else name,label) for name,label in roles]
    accounts={a.user.username:a for a in DemoAccount.objects.select_related('user').filter(user__username__in=[name for name,label in roles])}
    result=[]
    for name,label in roles:
        if name in accounts:
            accounts[name].label=label;accounts[name].test_group='개발팀' if name.startswith('p_dev_') else '그 외 부서' if name.startswith('p_quality') or name=='p_prod_director' else '공통 역할';result.append(accounts[name])
    return result


def shell(request):
    common=dict(purchase_base_template='purchasing/standalone_base.html',lab=True,shell_styles=['workflow/style.css','workflow/xenosys.css','workflow/workspace.css'])
    if not request.user.is_authenticated or not active(request.user):return common
    u=request.user;finance=is_finance(u);checker=is_confirmer(u)
    result=dict(**common,lab_admin=is_admin(u),lab_finance=finance,lab_confirmer=checker,demo_accounts=demo_choices(),lab_policy=policy(),
        counts=dict(own_completed=PurchaseRequest.objects.filter(owner=u,completion_unread=True).count(),hold=finance_requests(u).filter(status='hold').count() if finance else 0,pending=PurchaseRequest.objects.filter(Q(status='review',reviewer=u)|Q(status='approval',approver=u)|Q(status='director',director=u)).count(),
                    completed=checker_requests(u).filter(status__in=['ready','hold'],confirmed_at=None).count() if checker else 0,
                    finance=finance_requests(u).filter(Q(status__in=['ready','reapproval'])|Q(status='hold',hold_ready=True)|Q(status='ceo',current_report__payment_tracking=True,current_report__created_by=u)).filter(confirmed_at__isnull=False).count() if finance else 0,
                    representative=PurchaseReport.objects.filter(status='pending',representative=u,payment_tracking=False).count(),notices=notices_for(u).filter(read=False).count()))

    cards=[]
    if result['counts']['pending'] or u.username in ['p_quality_manager','p_quality_lead','p_dev_lead']:
        cards.append(dict(title='검토·승인할 요청',key='pending',count=result['counts']['pending'],url='/purchase-lab/requests/?mode=inbox',note='구매 내용을 확인하고 다음 담당자에게 전달하세요.'))
    if checker:cards.append(dict(title='구매 내용 확인',key='completed',count=result['counts']['completed'],url='/purchase-lab/requests/?mode=completed&stage=confirm',note='내부 승인이 끝난 요청을 확인해 주세요.'))
    if finance:cards.append(dict(title='모아서 구매요청',key='finance',count=result['counts']['finance'],url='/purchase-lab/requests/?mode=finance',note='확인된 품목을 선택해 대표님께 요청하세요.'))
    if u.profile.is_representative:
        if settings.INTEGRATED_PURCHASES:result['counts']['pending']+=result['counts']['representative']
        else:cards.append(dict(title='구매승인 결정',key='representative',count=result['counts']['representative'],url='/purchase-lab/reports/',note='품목별로 승인·반려·보류를 선택해 주세요.'))
    result['work_cards']=cards
    return result
