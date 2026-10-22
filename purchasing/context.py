from django.db.models import Q
from .models import DemoAccount,PurchaseRequest,PurchaseReport
from .access import active,is_admin,is_finance,is_confirmer,requests_for,policy,notices_for,finance_requests

DEMO_ROLES=[('p_quality','기안자'),('p_quality_manager','검토자'),('p_quality_lead','승인자'),('p_prod_director','구매 품목확인자 · 생산팀 이사'),('p_finance','취합·보고 담당자'),('p_ceo','대표 · 구매승인'),('p_admin','관리자 · 규정·직원 권한')]


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
    return dict(**common,lab_admin=is_admin(u),lab_finance=finance,lab_confirmer=checker,demo_accounts=demo_choices(),lab_policy=policy(),
        counts=dict(pending=PurchaseRequest.objects.filter(Q(status='review',reviewer=u)|Q(status='approval',approver=u)|Q(status='director',director=u)).count(),
                    completed=PurchaseRequest.objects.filter(status__in=['ready','hold'],confirmed_at=None).exclude(owner=u).count() if checker else 0,
                    finance=finance_requests(u).filter(status__in=['ready','hold'],confirmed_at__isnull=False).count() if finance else 0,
                    representative=PurchaseReport.objects.filter(status='pending',representative=u).count(),notices=notices_for(u).filter(read=False).count()))
