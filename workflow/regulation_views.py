from decimal import Decimal, InvalidOperation
from django import forms
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import ApprovalRule, AnnualPolicy, WelfarePolicy, Policy, DEPARTMENTS, RANKS, Audit
from .forms import ApprovalFlowPolicyForm, ApprovalRuleForm, AnnualBandForm, BenefitRuleForm, AwardRuleForm
from .regulations import annual_policy, save_annual_policy, save_rule, delete_rule, save_welfare, recalc_rows, apply_recalculation
from .delegation import route_preview, route_people
from .views import page
from .leave_records import balance_filters


def manager(user):
    return user.profile.manage_leave or user.profile.manage_system


@login_required
def preview_route(request):
    kind = request.GET.get('kind', 'leave')
    try:
        if kind not in ['leave', 'office', 'stock']:
            raise ValueError
        total = Decimal(request.GET.get('total', '0'))
        if not total.is_finite() or total < 0 or total > Decimal('999999999999999999'):
            raise ValueError
        rank = request.GET.get('rank', request.user.profile.rank) if manager(request.user) else request.user.profile.rank
        if rank not in RANKS:
            raise ValueError
        owner = request.user
        raw_author = request.GET.get('author', '')
        if manager(request.user) and raw_author.isascii() and raw_author.isdigit() and len(raw_author) <= 18:
            owner = get_object_or_404(get_user_model().objects.select_related('profile'), pk=raw_author, is_active=True, profile__approved=True)
            rank = owner.profile.rank
        elif manager(request.user) and 'rank' in request.GET:
            owner = None  # Rank-only simulation cannot impersonate staff-specific rules.
        mode = request.GET.get('mode', 'base')
        route = route_preview(kind, rank, total, owner=owner, mode=mode)
        reviewer = None
        raw = str(route['fixed_reviewer_id']) if route.get('fixed_reviewer_id') else request.GET.get('reviewer', '')
        if raw.isascii() and raw.isdigit() and len(raw) <= 18:
            reviewer = route_people(route, 'reviewer').filter(pk=raw).first()
        review_rank = reviewer.profile.rank if reviewer else None
        route = route_preview(kind, rank, total, review_rank, owner=owner, mode=mode)
        if route.get('progressive'):
            from .models import Document
            from .progressive import representative_option
            start=forms.DateField(required=False).clean(request.GET.get('start_date'))
            end=forms.DateField(required=False).clean(request.GET.get('end_date'))
            leave_type=request.GET.get('leave_type','annual')
            temp=Document(kind=kind,unit_price=total,quantity=1,leave_type=leave_type,start_date=start,
                end_date=end if leave_type=='annual' else start,
                start_time=forms.TimeField(required=False).clean(request.GET.get('start_time')),
                end_time=forms.TimeField(required=False).clean(request.GET.get('end_time')))
            try:
                route['representative_option']=representative_option(temp,route)
            except ValidationError:
                route['representative_option']=False  # Incomplete dates are validated again on submit.
            if route['representative_option']:
                route['note']='대표 결재 요청 선택 가능 · 허용된 전결 또는 최종 승인으로도 완료할 수 있습니다.'
        route['reviewer_ids'] = list(route_people(route, 'reviewer').values_list('pk', flat=True))
        route['approver_ids'] = list(route_people(route, 'approver', review_rank).values_list('pk', flat=True)) if route['final_approval_required'] else []
        route['self_allowed'] = rank in route['approvers'] and route['final_approval_required']
        response = JsonResponse(route)
    except (ValueError, InvalidOperation, ValidationError) as exc:
        response = JsonResponse({'error': ' '.join(exc.messages) if isinstance(exc, ValidationError) else '종류·금액·직급을 확인해 주세요.'}, status=400)
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def regulations(request, pk=None):
    if not manager(request.user):
        raise PermissionDenied
    tab = request.GET.get('tab', 'delegation')
    if tab not in ['delegation', 'annual', 'benefits', 'awards']:
        tab = 'delegation'
    if tab != 'delegation' and not request.user.profile.manage_leave:
        raise PermissionDenied
    year, _ = balance_filters(request.GET)
    years = range(timezone.localdate().year, timezone.localdate().year + 6)
    data = request.POST if request.method == 'POST' else None
    form = formset = None
    annual = annual_policy(year)
    legacy = Policy.objects.first()
    welfare = WelfarePolicy.objects.first()
    from .progressive import policy as flow_policy
    from .representatives import can_manage_representative
    flow_form=ApprovalFlowPolicyForm(request.POST if request.method == 'POST' and request.POST.get('intent') == 'flow_policy' else None, instance=flow_policy())
    if request.method == 'POST' and request.POST.get('intent') == 'flow_policy':
        if not can_manage_representative(request.user):
            raise PermissionDenied
        if flow_form.is_valid():
            from .regulations import save_flow_policy
            save_flow_policy(request.user,flow_form)
            messages.success(request,'새 기안의 단계별 결재 기준을 저장했습니다. 기존 문서는 유지됩니다.')
            return redirect('regulations')
        data=None
    if tab == 'delegation':
        instance = get_object_or_404(ApprovalRule, pk=pk, deleted_at__isnull=True) if pk else None
        form = ApprovalRuleForm(data, instance=instance, initial={} if instance else {'kind': 'all', 'reviewer_ranks': RANKS[1:], 'approver_ranks': RANKS[1:]})
    else:
        cls = {'annual': AnnualBandForm, 'benefits': BenefitRuleForm, 'awards': AwardRuleForm}[tab]
        if tab == 'annual':
            from .regulations import bands_for
            initial = [dict(years=low, days=days) for low, days in bands_for(year)]
        elif tab == 'benefits':
            initial = [dict(zip(['category', 'target', 'amount', 'remark'], row)) for row in (welfare.benefits if welfare else [])]
        else:
            initial = [dict(years=low, reward=reward) for low, reward in (welfare.awards if welfare else [])]
        Factory = forms.formset_factory(cls, extra=1, can_delete=True, max_num=200, validate_max=True, absolute_max=250)
        formset = Factory(data, initial=initial, prefix='rules')
    if request.method == 'POST' and request.POST.get('intent') != 'flow_policy':
        try:
            if tab == 'delegation':
                if form.is_valid():
                    save_rule(request.user, form)
                    messages.success(request, '전결규정을 저장했습니다. 이미 제출한 문서의 경로는 유지합니다.')
                    return redirect(reverse('regulations'))
            elif formset.is_valid():
                rows = [f.cleaned_data for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE')]
                if not rows:
                    raise ValidationError('규정 항목을 한 개 이상 입력해 주세요.')
                if tab == 'annual':
                    save_annual_policy(request.user, year, [[r['years'], r['days']] for r in rows], request.POST.get('text', '').strip())
                elif tab == 'benefits':
                    save_welfare(request.user, tab, [[r['category'], r['target'], r['amount'], r['remark']] for r in rows])
                else:
                    if len({r['years'] for r in rows}) != len(rows):
                        raise ValidationError('포상 근속연수가 중복됩니다.')
                    save_welfare(request.user, tab, sorted([[r['years'], r['reward']] for r in rows]))
                messages.success(request, '규정을 저장했습니다.' + (' 올해 직원 연차는 미리보기 후 별도로 적용하세요.' if tab == 'annual' else ''))
                return redirect(reverse('regulations') + f'?tab={tab}&year={year}')
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
    return page(request, 'regulations', '규정 관리', 'regulations', tab=tab, rule_form=form, rule_formset=formset, flow_form=flow_form,
        can_manage_flow=can_manage_representative(request.user),
        rule_authors=get_user_model().objects.filter(is_active=True, profile__approved=True, profile__manage_system=False,
            profile__representative_slot__isnull=True).select_related('profile').order_by('first_name'),
        rules=ApprovalRule.objects.filter(deleted_at__isnull=True).prefetch_related('authors'), selected_year=year, years=years,
        annual=annual, policy_text=request.POST.get('text', '') if data else (annual.text if annual and annual.text else legacy.text if legacy else ''),
        logs=Audit.objects.filter(event__in=['전결규정 수정', '전결규정 삭제', '연차 산정규정 수정', '경조사비 규정 수정', '장기근속 포상규정 수정','단계별 결재 기준 수정']).select_related('actor')[:12], ranks=RANKS)


@login_required
@require_POST
def rule_delete(request, pk):
    if not manager(request.user):
        raise PermissionDenied
    get_object_or_404(ApprovalRule, pk=pk, deleted_at__isnull=True)
    try:
        rule = delete_rule(request.user, pk)
    except ApprovalRule.DoesNotExist:
        from django.http import Http404
        raise Http404('이미 삭제된 규정입니다.')
    messages.success(request, f'전결규정 「{rule.name}」을 삭제했습니다. 기존 결재 이력은 보존됩니다.')
    return redirect('regulations')


@login_required
def recalculate(request):
    if not request.user.profile.manage_leave:
        raise PermissionDenied
    year = timezone.localdate().year
    _, department = balance_filters(request.GET)
    if request.method == 'POST':
        try:
            snapshot = signing.loads(request.POST.get('snapshot', ''), salt='annual-recalculation', max_age=1800)
            count = apply_recalculation(request.user, snapshot, set(request.POST.getlist('employees')), set(request.POST.getlist('replace_manual')))
            messages.success(request, f'{count}명의 총연차를 재계산했습니다. 최신 사용연차는 유지했습니다.')
            return redirect('balances')
        except (signing.BadSignature, signing.SignatureExpired, KeyError, TypeError) as exc:
            messages.error(request, '미리보기가 만료되었거나 올바르지 않습니다. 다시 확인해 주세요.')
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
    rows = recalc_rows(year, department)
    policy = annual_policy(year)
    snapshot = signing.dumps({'year': year, 'policy': [policy.pk, policy.version] if policy else [None, 0],
        'rows': {str(r['user'].pk): {'total': str(r['before']), 'manual': r['manual'], 'hire': r['hire']} for r in rows}}, salt='annual-recalculation', compress=True)
    for row in rows:
        row['remaining'] = row['after'] - row['used'] if row['after'] is not None else None
    return page(request, 'recalculate', '총연차 재계산 미리보기', 'balances', rows=rows, snapshot=snapshot,
        selected_year=year, selected_department=department, departments=DEPARTMENTS, annual=policy)
