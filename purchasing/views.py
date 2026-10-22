from uuid import uuid4
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import authenticate,login,logout,get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction,IntegrityError
from django.db.models import Q,Sum,F,DecimalField,ExpressionWrapper
from django.http import JsonResponse,HttpResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.views.decorators.http import require_POST,require_GET
from django.views.decorators.debug import sensitive_post_parameters
from workflow.models import RANKS
from .models import PurchaseRequest,PurchaseReport,PurchaseReportItem,PurchaseNotice,PurchasePolicy,DemoAccount
from .forms import RequestForm,PolicyForm
from .access import active,is_admin,is_finance,requests_for,reports_for,require_finance,policy,notices_for
from .services import save_request,request_action,submit_report,decide_report,event
from .progress import progress, PURCHASING_STATES, REQUESTER_STATES, visible_notice, events_for


def page(request,template,title,**context):
    response=render(request,f'purchasing/{template}.html',dict(title=title,page_name=template,**context))
    add_never_cache_headers(response);return response


@sensitive_post_parameters('password')
def login_view(request):
    if request.user.is_authenticated:return redirect('purchasing:home')
    if request.method=='POST':
        u=authenticate(request,username=request.POST.get('username',''),password=request.POST.get('password',''))
        if u and active(u):login(request,u);return redirect('purchasing:home')
        messages.error(request,'아이디와 비밀번호를 확인해 주세요.')
    return page(request,'login','구매요청 로컬 테스트 로그인',accounts=DemoAccount.objects.select_related('user').all())


@login_required
@require_POST
def logout_view(request):logout(request);return redirect('purchasing:login')


@login_required
@require_POST
def switch(request):
    # Only the fictional accounts explicitly created by the isolated demo seeder.
    from django.conf import settings
    if not settings.PURCHASE_LAB_ENABLED or settings.DATA_DIR.name!='purchase-test':raise PermissionDenied
    account=get_object_or_404(DemoAccount,user_id=request.POST.get('user') if str(request.POST.get('user','')).isdigit() else None)
    if not active(account.user):raise PermissionDenied
    login(request,account.user,backend='django.contrib.auth.backends.ModelBackend')
    return redirect('purchasing:home')


@login_required
def home(request):
    qs=PurchaseRequest.objects.filter(owner=request.user)
    recent=list(qs.select_related('reviewer','approver','director')[:8])
    for d in recent:d.progress_info=progress(d, simplified=True)
    stats=dict(internal=qs.filter(status__in=['review','approval','director']).count(),purchasing=qs.filter(status__in=PURCHASING_STATES).count(),active=qs.filter(status__in=['review','approval','director',*PURCHASING_STATES]).count(),
               allowed=qs.filter(status='allowed').count(),denied=qs.filter(status__in=['denied','hold','rejected']).count(),
               received=qs.filter(status='received').count())
    notices=list(notices_for(request.user).select_related('request','report')[:6])
    for n in notices:n.display_text=visible_notice(n,request.user)
    return page(request,'home','내 업무',recent=recent,stats=stats,notices=notices)


@login_required
def request_list(request):
    mode=request.GET.get('mode','mine');u=request.user
    qs=requests_for(u).select_related('owner','reviewer','approver','director')
    titles=dict(mine='내 구매요청',inbox='내가 처리할 구매요청',director='이사 최종승인 목록',finance='경리 취합 · 구매 진행',all='구매요청 전체')
    if mode=='mine':qs=qs.filter(owner=u)
    elif mode=='inbox':qs=qs.filter(Q(status='review',reviewer=u)|Q(status='approval',approver=u)|Q(status='director',director=u))
    elif mode=='director':qs=qs.filter(director=u).exclude(status='draft')
    elif mode=='finance':
        require_finance(u);qs=qs.filter(status__in=['ready','ceo','allowed','denied','hold','paid','received'])
    elif mode=='all':
        if not is_admin(u):raise PermissionDenied
    else:raise PermissionDenied
    selected=request.GET.get('state','')
    states=REQUESTER_STATES if mode=='mine' else PurchaseRequest.STATES
    if mode=='mine' and selected=='purchasing':qs=qs.filter(status__in=PURCHASING_STATES)
    elif selected in dict(states):qs=qs.filter(status=selected)
    q=request.GET.get('q','').strip()[:120]
    if q:qs=qs.filter(Q(product__icontains=q)|Q(vendor__icontains=q)|Q(owner__first_name__icontains=q))
    docs=list(qs[:100])
    for d in docs:d.progress_info=progress(d, simplified=d.owner_id==u.pk and mode!='finance' and mode!='all')
    return page(request,'requests',titles[mode],documents=docs,mode=mode,states=states,
                selected=selected,total=qs.count(),q=q)


@login_required
def compose(request,pk=None):
    if request.user.profile.is_representative:raise PermissionDenied
    instance=get_object_or_404(PurchaseRequest,pk=pk,owner=request.user,status='draft') if pk else None
    p=policy();form=RequestForm(request.POST if request.method=='POST' else None,instance=instance,user=request.user,policy=p)
    if request.method=='POST' and form.is_valid():
        try:
            d=save_request(request.user,form.cleaned_data,submit=request.POST.get('intent')=='submit',pk=pk,key=form.cleaned_data['key'])
            messages.success(request,'구매요청을 제출했습니다.' if d.status!='draft' else '임시저장했습니다.')
            return redirect('purchasing:detail',pk=d.pk)
        except ValidationError as exc:form.add_error(None,exc)
    director=p.dev_director if p and request.user.profile.department=='개발팀' else p.production_director if p else None
    return page(request,'compose','구매요청 작성',form=form,director=director)


@login_required
def detail(request,pk):
    d=get_object_or_404(requests_for(request.user).select_related('owner','reviewer','approver','director','current_report'),pk=pk)
    notices_for(request.user).filter(request=d,read=False).update(read=True)
    assigned={'review':d.reviewer_id,'approval':d.approver_id,'director':d.director_id}.get(d.status)
    can_pay=d.status=='allowed' and (is_finance(request.user) or request.user.profile.is_representative and d.current_report_id and d.current_report.representative_id==request.user.pk)
    simplified=d.owner_id==request.user.pk
    return page(request,'detail',d.number,doc=d,track=progress(d,simplified=simplified),simplified=simplified,visible_events=events_for(d,simplified),can_approve=assigned==request.user.pk,
        can_cancel=d.owner_id==request.user.pk and d.status in ['draft','review','approval','director','ready'] and not d.current_report_id,
        can_pay=can_pay,can_receive=d.owner_id==request.user.pk and d.status=='paid',
        can_report=bool(d.current_report_id and reports_for(request.user).filter(pk=d.current_report_id).exists()))


@login_required
@require_POST
def act(request,pk):
    get_object_or_404(requests_for(request.user),pk=pk)
    try:request_action(pk,request.user,request.POST.get('action',''),request.POST.get('reason',''));messages.success(request,'처리했습니다.')
    except ValidationError as exc:messages.error(request,' '.join(exc.messages))
    return redirect('purchasing:detail',pk=pk)


def selected_ids(raw):
    if not raw or len(raw)>100 or any(not x.isascii() or not x.isdigit() or len(x)>18 or int(x)<1 for x in raw) or len(set(raw))!=len(raw):
        raise ValidationError('중복 없이 1~100개 품목을 선택해 주세요.')
    return [int(x) for x in raw]


@login_required
@require_POST
def report_new(request):
    require_finance(request.user)
    try:
        ids=selected_ids(request.POST.getlist('requests'))
        docs=list(PurchaseRequest.objects.filter(pk__in=ids,status__in=['ready','hold']).select_related('owner').order_by('department','pk'))
        if len(docs)!=len(ids):raise ValidationError('이미 취합되었거나 취합할 수 없는 품목이 있습니다.')
        if request.POST.get('intent')=='submit':
            report=submit_report(request.user,ids,request.POST.get('title',''),request.POST.get('note',''),request.POST.get('key'))
            messages.success(request,'대표님에게 품목별 구매허가를 요청했습니다.')
            return redirect('purchasing:report_detail',pk=report.pk)
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages));return redirect('/purchase-lab/requests/?mode=finance')
    return page(request,'report_new','선택 품목 취합 · 구매허가 요청',documents=docs,total=sum((d.total for d in docs),Decimal('0')),
                key=uuid4(),report_title=f'{timezone.localdate():%Y.%m.%d} 구매허가 요청')


@login_required
def report_list(request):
    qs=reports_for(request.user).prefetch_related('items')
    return page(request,'reports','취합 구매허가 요청서',reports=qs[:100])


@login_required
def report_detail(request,pk):
    report=get_object_or_404(reports_for(request.user).select_related('created_by','representative'),pk=pk)
    notices_for(request.user).filter(report=report,read=False).update(read=True)
    items=list(report.items.select_related('request'))
    can_decide=report.status=='pending' and report.representative_id==request.user.pk and request.user.profile.is_representative
    if request.method=='POST':
        if not can_decide:raise PermissionDenied
        try:
            revision=int(request.POST.get('revision','-1'))
            decisions={str(i.pk):dict(decision=request.POST.get(f'decision_{i.pk}',''),reason=request.POST.get(f'reason_{i.pk}','')) for i in items}
            decide_report(pk,request.user,decisions,revision,final=request.POST.get('intent')=='final')
            messages.success(request,'품목별 결정을 확정했습니다.' if request.POST.get('intent')=='final' else '심사 내용을 임시저장했습니다.')
            return redirect('purchasing:report_detail',pk=pk)
        except (ValueError,ValidationError) as exc:
            messages.error(request,' '.join(exc.messages) if isinstance(exc,ValidationError) else '화면을 다시 열어 주세요.')
    return page(request,'report_detail',report.number,report=report,items=items,can_decide=can_decide,
                decisions=PurchaseReportItem.DECISIONS,total=sum((i.total for i in items),Decimal('0')),
                allowed_total=sum((i.total for i in items if i.decision=='allow'),Decimal('0')),
                denied_total=sum((i.total for i in items if i.decision=='deny'),Decimal('0')),
                hold_total=sum((i.total for i in items if i.decision=='hold'),Decimal('0')))


@login_required
def regulations(request):
    if not is_admin(request.user):raise PermissionDenied
    p=policy();form=PolicyForm(request.POST if request.method=='POST' else None,instance=p)
    if request.method=='POST' and form.is_valid():
        try:form.save(request.user);messages.success(request,'구매 규정을 저장했습니다. 새 구매요청부터 적용됩니다.');return redirect('purchasing:regulations')
        except ValidationError as exc:form.add_error(None,exc)
    rows=[dict(rank=rank,dev=form[f'dev_{i}'],other=form[f'other_{i}']) for i,rank in enumerate(RANKS)]
    return page(request,'regulations','구매 규정 설정',form=form,rank_rows=rows)


@login_required
@require_GET
def status(request):
    from .context import shell
    data=shell(request)
    response=JsonResponse(dict(user=request.user.pk,counts=data['counts']))
    add_never_cache_headers(response);return response


@login_required
@require_GET
def hints(request):
    from workflow.purchase_hints import normalize_product
    from django.db.models.functions import Replace,Lower
    from django.db.models import Value
    q=normalize_product(request.GET.get('q','')[:120]);rows=PurchaseRequest.objects.none()
    if len(q)>=2:
        rows=PurchaseRequest.objects.exclude(status__in=['draft','rejected','cancelled','denied']).filter(private=False).annotate(
            normalized=Lower(Replace(Replace('product',Value(' '),Value('')),Value('-'),Value('')))).filter(normalized__contains=q).order_by('-created_at')
    response=JsonResponse(dict(count=rows.count(),results=[dict(product=d.product,department=d.department,quantity=d.quantity,
        requested=d.created_at.date().isoformat(),status=progress(d,simplified=True)['label']) for d in rows[:8]]))
    add_never_cache_headers(response);return response
