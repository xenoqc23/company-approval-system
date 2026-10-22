from django.db.models import Q
from .models import DemoAccount,PurchaseNotice,PurchaseRequest,PurchaseReport
from .access import active,is_admin,is_finance,requests_for,reports_for,policy,notices_for


def shell(request):
    if not request.user.is_authenticated:return dict(lab=True,shell_styles=['workflow/style.css','workflow/xenosys.css','workflow/workspace.css'])
    u=request.user
    if not active(u):return dict(lab=True,shell_styles=['workflow/style.css','workflow/xenosys.css','workflow/workspace.css'])
    return dict(lab=True,shell_styles=['workflow/style.css','workflow/xenosys.css','workflow/workspace.css'],lab_director=u.profile.rank=='이사',lab_admin=is_admin(u),lab_finance=is_finance(u),
        demo_accounts=DemoAccount.objects.select_related('user').all(),lab_policy=policy(),
        counts=dict(pending=PurchaseRequest.objects.filter(Q(status='review',reviewer=u)|Q(status='approval',approver=u)|Q(status='director',director=u)).count(),
                    finance=PurchaseRequest.objects.filter(status__in=['ready','hold']).count() if is_finance(u) else 0,
                    representative=PurchaseReport.objects.filter(status='pending',representative=u).count(),
                    notices=notices_for(u).filter(read=False).count()))
