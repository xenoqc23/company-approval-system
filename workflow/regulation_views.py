from decimal import Decimal, InvalidOperation
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from .models import ApprovalRule, AnnualPolicy, WelfarePolicy, Policy, DEPARTMENTS, RANKS, Audit
from .forms import ApprovalRuleForm, AnnualBandForm, BenefitRuleForm, AwardRuleForm
from .regulations import annual_policy, save_annual_policy, save_rule, save_welfare, recalc_rows, apply_recalculation
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
        route = route_preview(kind, rank, total)
        reviewer = None
        raw = request.GET.get('reviewer', '')
        if raw.isascii() and raw.isdigit() and len(raw) <= 18:
            reviewer = route_people(route, 'reviewer').filter(pk=raw).first()
        review_rank = reviewer.profile.rank if reviewer else None
        route = route_preview(kind, rank, total, review_rank)
        route['reviewer_ids'] = list(route_people(route, 'reviewer').values_list('pk', flat=True))
        route['approver_ids'] = list(route_people(route, 'approver', review_rank).values_list('pk', flat=True)) if kind != 'stock' else []
        route['self_allowed'] = rank in route['approvers'] and kind != 'stock'
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
    if tab == 'delegation':
        instance = get_object_or_404(ApprovalRule, pk=pk) if pk else None
        form = ApprovalRuleForm(data, instance=instance, initial={} if instance else {'reviewer_ranks': RANKS[1:], 'approver_ranks': RANKS[1:]})
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
    if request.method == 'POST':
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
    return page(request, 'regulations', '규정 관리', 'regulations', tab=tab, rule_form=form, rule_formset=formset,
        rules=ApprovalRule.objects.all(), selected_year=year, years=years,
        annual=annual, policy_text=request.POST.get('text', '') if data else (annual.text if annual and annual.text else legacy.text if legacy else ''),
        logs=Audit.objects.filter(event__in=['전결규정 수정', '연차 산정규정 수정', '경조사비 규정 수정', '장기근속 포상규정 수정']).select_related('actor')[:12], ranks=RANKS)


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
