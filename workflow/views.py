from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from urllib.parse import urlencode
import secrets
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.utils.cache import add_never_cache_headers
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST
from .forms import ApprovalAssignmentForm, DocumentForm, ProfilePasswordForm, SignupForm, AbsenceForm, CompanyHolidayForm, HireDateForm, ManualLeaveForm
from .models import AnnualBalance, Audit, DEPARTMENTS, RANKS, Document, Notice, Policy, Profile, Absence, CompanyHoliday, CompanyLeaveCharge
from .services import act_on_document, audit, edit_balance, leave_amount, save_document, visible_documents
from .people import approval_people, rank_order
from .exports import purchase_workbook, leave_balances_workbook
from .accounting import accounting_tabs
from .notifications import visible_notices
from .leave_records import balance_filters, balance_rows, employee_leave_records

User = get_user_model()

def page(request, template, title, section='dashboard', **context):
    response = render(request, f'workflow/{template}.html', {'title': title, 'section': section,
        'auth_layout': template in ['login', 'signup', 'pending', 'password'], **context})
    # These HTML pages contain session-specific forms and rotating CSRF tokens.
    add_never_cache_headers(response)
    return response

def health(request):
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return HttpResponse('ok', content_type='text/plain')

@never_cache
@sensitive_post_parameters('password')
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        user = authenticate(request, username=request.POST.get('username', ''), password=request.POST.get('password', ''))
        if user:
            login(request, user)
            return redirect('dashboard')
        messages.error(request, '아이디 또는 비밀번호를 확인해 주세요.')
    return page(request, 'login', '로그인', 'login')

@never_cache
@require_GET
def login_csrf(request):
    # A saved tab may predate a login (and token rotation) in another tab.
    # This does not authenticate or submit anything; POST stays CSRF protected.
    return JsonResponse({'token': get_token(request)})

@never_cache
@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')

def signup(request):
    form = SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            Profile.objects.create(user=user, department=form.cleaned_data['department'], rank=form.cleaned_data['rank'], department_confirmed=False)
        messages.success(request, '가입 신청이 완료되었습니다. 관리자의 승인 후 로그인해 주세요.')
        return redirect('login')
    return page(request, 'signup', '직원 가입', 'signup', form=form)

@login_required
def pending(request):
    return page(request, 'pending', '가입 승인 대기', 'pending')

@login_required
def password(request):
    form = ProfilePasswordForm(request.user, request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        user.profile.must_change_password = False
        user.profile.save(update_fields=['must_change_password'])
        update_session_auth_hash(request, user)
        messages.success(request, '비밀번호가 변경되었습니다.')
        return redirect('dashboard')
    return page(request, 'password', '비밀번호 변경', 'password', form=form)

@login_required
def account(request):
    form = ProfilePasswordForm(request.user, request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        audit(user, '본인 비밀번호 변경')
        messages.success(request, '비밀번호가 변경되었습니다.')
        return redirect('account')
    return page(request, 'account', '내 계정', 'account', form=form)

@login_required
def dashboard(request):
    mine = Document.objects.filter(owner=request.user).exclude(status__in=['draft', 'deleted'])
    from .home import progress_stages
    # Keep the chooser limited to the employee's own submitted documents.
    progress_documents = list(mine.filter(status__in=['review', 'approve']).order_by('-submitted_at', '-pk').select_related('owner', 'reviewer', 'approver'))
    pending_documents = [doc for doc in progress_documents if doc.status in ['review', 'approve']]
    progress_documents = pending_documents
    selected_id = request.GET.get('progress_document', '')
    progress_doc = next((doc for doc in progress_documents if str(doc.pk) == selected_id), None)
    if progress_doc is None:
        progress_doc = next(iter(pending_documents), None)
    steps = progress_stages(progress_doc)
    if progress_doc and progress_doc.kind != 'stock':
        steps = steps[:3 if progress_doc.review_required else 2]
    home_kind = request.GET.get('home_kind', 'all')
    if home_kind not in ['all', 'leave', 'office', 'stock']:
        home_kind = 'all'
    kind_counts = dict(mine.order_by().values_list('kind').annotate(n=Count('pk')))
    home_categories = [
        {'key': key, 'label': label, 'count': sum(kind_counts.values()) if key == 'all' else kind_counts.get(key, 0),
         'url': reverse('dashboard') + '?home_kind=' + key
                + (f'&progress_document={progress_doc.pk}' if progress_doc else '') + '#recent-documents'}
        for key, label in [('all', '전체'), ('leave', '휴가원'), ('office', '구매요청서'), ('stock', '생산 재고')]]
    recent = mine if home_kind == 'all' else mine.filter(kind=home_kind)
    return page(request, 'dashboard', '홈', documents=recent.select_related('owner')[:4],
                home_kind=home_kind, home_categories=home_categories,
                progress_doc=progress_doc, progress_steps=steps, progress_count=len(pending_documents),
                progress_groups=[('진행 중', pending_documents)], notices=visible_notices(request.user)[:3])

@login_required
def documents(request):
    mode = request.GET.get('mode', 'mine')
    accounting_categories, selected_kind = [], ''
    qs = visible_documents(request.user).select_related('owner', 'owner__profile', 'reviewer', 'approver')
    titles = {'mine': '내 기안', 'drafts': '임시저장함', 'pending': '결재함', 'history': '내 승인 내역',
              'archive': '반려함', 'accounting': '최종 승인 문서함', 'receive': '물품 수령 확인',
              'stock': '생산 재고 요청함', 'all': '전체 문서', 'search': '문서 검색'}
    if mode == 'mine':
        qs = qs.filter(owner=request.user).exclude(status='draft')
    elif mode == 'drafts':
        qs = qs.filter(owner=request.user, status='draft')
    elif mode == 'pending':
        qs = qs.filter(Q(status='review', reviewer=request.user) | Q(status='approve', approver=request.user))
    elif mode == 'history':
        qs = qs.filter(audits__actor=request.user, audits__event__in=['검토 승인', '최종 승인', '재고 요청 검토 완료']).distinct()
    elif mode == 'stock':
        qs = qs.filter(kind='stock').exclude(status='draft')
        stage = request.GET.get('stock_stage')
        if stage == 'review':
            qs = qs.filter(status='review')
        elif stage == 'ready':
            qs = qs.filter(status='approved', shipment='')
        elif stage == 'ordered':
            qs = qs.filter(status='approved', shipment='ordered')
        elif stage == 'received':
            qs = qs.filter(status='approved', shipment='received')
    elif mode == 'archive':
        qs = qs.filter(status__in=['rejected', 'cancelled'])
    elif mode == 'accounting':
        if not request.user.profile.view_accounting:
            raise PermissionDenied
        qs = qs.filter(status='approved')
        selected_kind = request.GET.get('kind', 'all')
        if selected_kind not in ['all', *dict(Document.KINDS)]:
            selected_kind = 'all'
        # Opening the menu shows new markers; choosing a tab acknowledges it.
        read_kind = selected_kind if request.GET.get('kind') == selected_kind else None
        for category in accounting_tabs(request.user, read_kind):
            key = category['key']
            params = request.GET.copy()
            params['mode'], params['kind'] = 'accounting', key
            for stale in ['status', 'shipment', 'department']:
                params.pop(stale, None)
            accounting_categories.append({**category, 'url': '?' + params.urlencode()})
        if selected_kind != 'all':
            qs = qs.filter(kind=selected_kind)
    elif mode == 'receive':
        qs = qs.filter(status='approved', recipient=request.user, kind__in=['office', 'stock'])
    elif mode == 'all':
        if not request.user.profile.manage_system:
            raise PermissionDenied
    elif mode == 'search':
        if not request.GET.get('q', '').strip():
            qs = qs.none()
    else:
        raise PermissionDenied
    if request.GET.get('q', '').strip():
        q = request.GET['q'].strip()
        matching = Q(title__icontains=q) | Q(number__icontains=q) | Q(owner__first_name__icontains=q) | Q(product__icontains=q)
        leave_types = [key for key, label in Document.LEAVES if q.casefold() in label.casefold()]
        kind_labels = [*Document.KINDS, ('office', '구매요청서')]
        kinds = [key for key, label in kind_labels if q.casefold() in label.casefold()]
        if leave_types:
            matching |= Q(kind='leave', leave_type__in=leave_types)
        if kinds:
            matching |= Q(kind__in=kinds)
        qs = qs.filter(matching)
    for key in ['kind', 'status', 'shipment']:
        if key == 'kind' and mode == 'accounting':
            continue
        if request.GET.get(key):
            qs = qs.filter(**{key: request.GET[key]})
    for key, lookup in [('from', 'created_at__date__gte'), ('to', 'created_at__date__lte')]:
        try:
            if request.GET.get(key):
                qs = qs.filter(**{lookup: date.fromisoformat(request.GET[key])})
        except ValueError:
            messages.error(request, '검색 날짜 형식을 확인해 주세요.')
    qs = rank_order(qs, 'owner__')
    return page(request, 'documents', titles[mode], mode, documents=qs[:100], document_count=qs.count(),
                mode=mode, states=[(k, '검토완료' if k == 'approved' else label) for k, label in Document.STATES if k != 'approve'] if mode == 'stock' else Document.STATES,
                kinds=Document.KINDS, departments=DEPARTMENTS,
                accounting_categories=accounting_categories, selected_kind=selected_kind,
                can_export_purchases=mode == 'accounting' and selected_kind == 'office',
                stock_column=mode == 'stock' or (mode == 'accounting' and selected_kind == 'stock'))

@login_required
def accounting_tab_status(request):
    if not request.user.profile.view_accounting:
        raise PermissionDenied
    response = JsonResponse({'tabs': accounting_tabs(request.user)})
    response['Cache-Control'] = 'private, no-store'
    return response

@login_required
@require_POST
def export_purchases(request):
    if not request.user.profile.view_accounting:
        raise PermissionDenied
    raw_ids = request.POST.getlist('documents')
    if not raw_ids or len(raw_ids) > 100 or any(not value.isascii() or not value.isdigit() or len(value) > 18 for value in raw_ids):
        return HttpResponse('다운로드할 구매요청서를 1~100건 선택해 주세요.', status=400, content_type='text/plain; charset=utf-8')
    ids = {int(value) for value in raw_ids}
    docs = list(rank_order(visible_documents(request.user).filter(
        pk__in=ids, kind='office', status='approved').select_related('owner', 'owner__profile'), 'owner__'))
    if len(docs) != len(ids):
        return HttpResponse('선택한 문서가 취소되었거나 다운로드할 수 없습니다. 목록을 새로고침하고 다시 선택해 주세요.', status=400, content_type='text/plain; charset=utf-8')
    output = BytesIO()
    purchase_workbook(docs).save(output)
    audit(request.user, '구매요청서 엑셀 다운로드', detail='선택 문서: ' + ', '.join(doc.number for doc in docs))
    response = HttpResponse(output.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    filename = f'구매요청서_{timezone.localtime():%Y%m%d_%H%M%S}.xlsx'
    response['Content-Disposition'] = content_disposition_header(True, filename)
    response['Cache-Control'] = 'private, no-store'
    return response

@login_required
def compose(request, pk=None):
    instance = get_object_or_404(Document, pk=pk, owner=request.user, status='draft') if pk else Document(owner=request.user)
    initial = {'kind': request.GET.get('kind', 'leave'), 'recipient': request.user.pk, 'quantity': 1, 'urgency': 'normal',
               'start_date': timezone.localdate(), 'end_date': timezone.localdate()}
    data = request.POST or None
    if request.method == 'POST' and not pk and request.POST.get('home_kind') in ['leave', 'office']:
        # The compact forms use separate namespaces; the existing form/service
        # handles validation, draft saving and submission for both entry points.
        kind = request.POST['home_kind']
        prefix = f'home_{kind}-'
        data = request.POST.copy()
        for key in request.POST:
            if key.startswith(prefix):
                data.setlist(key[len(prefix):], request.POST.getlist(key))
        data['kind'] = kind
    form = DocumentForm(data, instance=instance, initial=initial if not pk else {},
                        submit=request.POST.get('intent') == 'submit')
    if request.method == 'POST' and form.is_valid():
        doc = form.save(commit=False)
        doc.owner = request.user
        try:
            save_document(doc, request.user, submit=request.POST.get('intent') == 'submit')
            messages.success(request, '기안이 제출되었습니다.' if doc.status in ['review', 'approve'] else '임시저장되었습니다.')
            return redirect('detail', pk=doc.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return page(request, 'compose', '기안 작성' if not pk else '임시저장 이어쓰기', 'compose', form=form)

@login_required
def detail(request, pk):
    doc = get_object_or_404(visible_documents(request.user), pk=pk)
    actions = []
    u = request.user
    if doc.status == 'review' and doc.reviewer_id == u.pk:
        actions += [('review', '검토확인'), ('reject', '반려')]
    if doc.kind != 'stock' and doc.status == 'approve' and doc.approver_id == u.pk:
        actions += [('approve', '승인확인'), ('reject', '반려')]
    if doc.review_required and doc.status == 'approve' and doc.reviewer_id == u.pk:
        actions += [('cancel_review', '검토 승인 취소')]
    if doc.kind == 'stock' and doc.status == 'approved' and doc.reviewer_id == u.pk:
        actions += [('cancel_review', '검토 완료 취소')]
    if doc.kind != 'stock' and doc.status == 'approved' and doc.approver_id == u.pk:
        actions += [('cancel_approval', '최종 승인 취소')]
    if (doc.status in ['draft', 'review'] or (doc.status == 'approve' and not doc.review_required)) and doc.owner_id == u.pk:
        actions += [('delete', '기안 삭제')]
    if doc.status == 'approved' and doc.kind != 'leave':
        if u.profile.procure and not doc.shipment:
            actions += [('place', '구매 처리' if doc.kind == 'office' else '발주 처리')]
        if doc.recipient_id == u.pk and doc.shipment in ['shipping', 'ordered']:
            actions += [('receive', '배송완료 확인' if doc.kind == 'office' else '입고완료 확인')]
    try:
        amount = leave_amount(doc) if doc.kind == 'leave' else 0
    except ValidationError:
        amount = 0
    common_overlaps = CompanyHoliday.objects.filter(active=True, use_annual=True, day__range=(doc.start_date, doc.end_date)) if doc.kind == 'leave' and doc.start_date and doc.end_date else []
    assignment_form = ApprovalAssignmentForm()
    procurement_log = doc.audits.filter(event='발주 처리').select_related('actor').first() if doc.kind == 'stock' else None
    review_cancelled = doc.status == 'cancelled' and (doc.kind == 'stock' or not doc.approved_at)
    review_confirmed = bool(doc.reviewed_at) and not review_cancelled
    approval_cancelled = doc.kind != 'stock' and doc.status == 'cancelled' and bool(doc.approved_at)
    approval_confirmed = doc.kind != 'stock' and doc.status == 'approved' and bool(doc.approved_at)
    return page(request, 'detail', '재고 요청 상세' if doc.kind == 'stock' else '기안 상세',
                'stock' if doc.kind == 'stock' else 'mine', doc=doc, actions=actions, amount=amount, assignment_form=assignment_form, procurement_log=procurement_log,
                common_overlaps=common_overlaps, review_confirmed=review_confirmed, review_cancelled=review_cancelled,
                approval_confirmed=approval_confirmed, approval_cancelled=approval_cancelled,
                my_review_confirmed=review_confirmed and doc.reviewer_id == u.pk,
                my_approval_confirmed=approval_confirmed and doc.approver_id == u.pk,
                can_reassign=u.profile.manage_system and doc.status in ['review', 'approve'],
                can_copy=u.pk == doc.owner_id and doc.status in ['rejected', 'cancelled'])

@login_required
@require_POST
def action(request, pk):
    get_object_or_404(visible_documents(request.user), pk=pk)
    try:
        new = User.objects.filter(pk=request.POST.get('new_person') or None).first()
        if request.POST.get('action') == 'reassign' and request.POST.get('new_person_department') and new and new.profile.department != request.POST['new_person_department']:
            raise ValidationError('선택한 부서에 속한 직원을 지정해 주세요.')
        doc = act_on_document(pk, request.user, request.POST.get('action'), request.POST.get('reason', ''), new)
        if request.POST.get('action') in ['review', 'approve']:
            label = '검토확인' if request.POST['action'] == 'review' else '승인확인'
            messages.success(request, f'{label}이 완료되었습니다.', extra_tags='approval-feedback')
        else:
            messages.success(request, '처리가 완료되었습니다.')
        if doc.status == 'deleted' or not visible_documents(request.user).filter(pk=pk).exists():
            return redirect('documents')
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    return redirect('detail', pk=pk)

@login_required
@require_POST
def copy_document(request, pk):
    old = get_object_or_404(Document, pk=pk, owner=request.user, status__in=['rejected', 'cancelled'])
    fields = ['kind', 'leave_type', 'start_date', 'end_date', 'start_time', 'end_time', 'reason', 'quantity', 'unit_price',
              'product', 'url', 'urgency', 'needed_date', 'reviewer', 'approver', 'recipient']
    new = Document(owner=request.user, **{field: getattr(old, field) for field in fields})
    for field in ['reviewer', 'approver']:
        person = getattr(new, field)
        if person and not approval_people().filter(pk=person.pk).exists():
            setattr(new, field, None)
    save_document(new, request.user)
    audit(request.user, '복사 재기안', new, old.number or '')
    messages.success(request, '새 기안으로 복사했습니다. 내용을 확인하고 제출해 주세요.')
    return redirect('edit', pk=new.pk)

@login_required
def balances(request):
    p = request.user.profile
    year, department = balance_filters(request.GET)
    if not p.manage_leave:
        department = ''
    if request.method == 'POST':
        if not p.manage_leave:
            raise PermissionDenied
        target = get_object_or_404(User, pk=request.POST.get('user'))
        try:
            posted_year = int(request.POST.get('year', year))
            if not 2000 <= posted_year <= 2100:
                raise ValueError
            if request.POST.get('operation') == 'hire':
                from .annual_grants import set_hire_date
                form = HireDateForm(request.POST)
                if not form.is_valid():
                    raise ValidationError('입사일을 확인해 주세요.')
                set_hire_date(request.user, target, form.cleaned_data['hire_date'], posted_year,
                              apply=request.POST.get('apply') == 'yes')
                messages.success(request, '입사일을 저장했습니다.' + (' 총연차를 산정해 적용했습니다.' if request.POST.get('apply') == 'yes' else ''))
            else:
                value = Decimal(request.POST.get('value', ''))
                if not value.is_finite() or abs(value) > 99999:
                    raise ValueError
                edit_balance(request.user, target, posted_year, request.POST.get('field'), value, request.POST.get('reason', ''))
                messages.success(request, '연차를 수정하고 변경 이력을 기록했습니다.')
        except (ValidationError, InvalidOperation, ValueError) as exc:
            messages.error(request, ' '.join(exc.messages) if isinstance(exc, ValidationError) else '연도와 연차 값을 확인해 주세요.')
        return redirect(reverse('balances') + '?' + urlencode({'year': year, 'department': department}))
    rows = balance_rows(year, department, user=None if p.manage_leave else request.user)
    logs = Audit.objects.filter(target__isnull=False)
    if not p.manage_leave:
        logs = logs.filter(target=request.user)
    elif department:
        logs = logs.filter(target__profile__department=department)
    return page(request, 'balances', '직원별 연차 관리' if p.manage_leave else '나의 연차', 'balances',
                rows=rows, selected_year=year, departments=DEPARTMENTS, selected_department=department,
                years=range(timezone.localdate().year - 2, timezone.localdate().year + 2), logs=logs.select_related('actor', 'target')[:20])

@login_required
@require_POST
def export_balances(request):
    if not request.user.profile.manage_leave:
        raise PermissionDenied
    year, department = balance_filters(request.POST)
    rows = balance_rows(year, department)
    output = BytesIO()
    leave_balances_workbook(rows, year).save(output)
    audit(request.user, '직원 연차 엑셀 다운로드', detail=f'{year}년 / {department or "모든 부서"} / {len(rows)}명')
    response = HttpResponse(output.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = content_disposition_header(True, f'직원별_연차현황_{year}_{timezone.localtime():%Y%m%d_%H%M%S}.xlsx')
    response['Cache-Control'] = 'private, no-store'
    return response

@login_required
def leave_history(request, pk):
    if not request.user.profile.manage_leave:
        raise PermissionDenied
    employee = get_object_or_404(User.objects.select_related('profile'), pk=pk, profile__approved=True)
    year, _ = balance_filters(request.GET)
    mode = 'all' if request.GET.get('mode') == 'all' else 'approved'
    rows = employee_leave_records(employee, year, mode)
    accessible = set(visible_documents(request.user).filter(pk__in=[row['doc'].pk for row in rows if row.get('doc')]).values_list('pk', flat=True))
    for row in rows:
        row['accessible'] = bool(row.get('doc') and row['doc'].pk in accessible)
    balance = AnnualBalance.objects.filter(user=employee, year=year).first()
    back_url = reverse('balances') + '?' + urlencode({'year': year, 'department': employee.profile.department})
    return page(request, 'leave_history', f'{employee.first_name} 연차 사용 내역', 'balances', employee=employee,
        selected_year=year, years=range(timezone.localdate().year - 2, timezone.localdate().year + 2),
        mode=mode, leave_rows=rows, employee_balance=balance, back_url=back_url,
        document_charged=sum((row['charged'] for row in rows if row.get('doc')), Decimal('0')),
        manual_charged=sum((row['charged'] for row in rows if row.get('manual')), Decimal('0')),
        common_charges=CompanyLeaveCharge.objects.filter(employee=employee, year=year, active=True).select_related('holiday').order_by('-holiday__day'),
        logs=Audit.objects.filter(target=employee, event=f'{year}년 연차 수정').select_related('actor')[:30])


@login_required
def manual_leave_new(request, pk):
    if not request.user.profile.manage_leave:
        raise PermissionDenied
    employee = get_object_or_404(User.objects.select_related('profile'), pk=pk, profile__approved=True)
    year, _ = balance_filters(request.GET)
    from uuid import uuid4
    today = timezone.localdate()
    form = ManualLeaveForm(request.POST if request.method == 'POST' else None,
        initial={'used_date': today if today.year == year else date(year, 1, 1),
                 'leave_type': 'annual', 'request_key': uuid4()})
    if request.method == 'POST' and form.is_valid():
        from .manual_leave import register_manual_leave
        try:
            usage, created = register_manual_leave(request.user, employee, form.cleaned_data, form.cleaned_data['request_key'])
        except ValidationError as exc:
            form.add_error(None, ' '.join(exc.messages))
        else:
            messages.success(request, f'{usage.amount}일 사용을 등록하고 잔여연차에서 차감했습니다.' if created else '이미 처리된 등록입니다. 사용 내역을 확인해 주세요.')
            return redirect(reverse('leave_history', args=[pk]) + '?' + urlencode({'year': usage.used_date.year}))
    return page(request, 'manual_leave_form', '연차 사용 직접 등록', 'balances',
                employee=employee, form=form, selected_year=year,
                employee_balance=AnnualBalance.objects.filter(user=employee, year=year).first())


@login_required
@require_POST
def manual_leave_cancel(request, pk, usage_pk):
    if not request.user.profile.manage_leave:
        raise PermissionDenied
    from .models import ManualLeaveUsage
    from .manual_leave import cancel_manual_leave
    employee = get_object_or_404(User, pk=pk, profile__approved=True)
    usage = get_object_or_404(ManualLeaveUsage, pk=usage_pk, employee=employee)
    try:
        cancel_manual_leave(request.user, employee, usage.pk, request.POST.get('reason', ''))
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    else:
        messages.success(request, f'직접 등록을 취소하고 {usage.amount}일을 복원했습니다.')
    return redirect(reverse('leave_history', args=[pk]) + '?' + urlencode({'year': usage.used_date.year, 'mode': 'all'}))


@login_required
def calendar_view(request):
    from .calendars import month_selection, month_grid
    year, month = month_selection(request.GET)
    return page(request, 'calendar', '직원 일정', 'calendar', **month_grid(year, month, request.user))


@login_required
def absence_edit(request, pk=None):
    instance = get_object_or_404(Absence.objects.select_related('employee__profile'), pk=pk) if pk else None
    form = AbsenceForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        absence = form.save(commit=False)
        if not instance:
            absence.employee = request.user
        absence.save()
        messages.success(request, '부재 일정을 저장했습니다.')
        return redirect(reverse('calendar') + '?' + urlencode({'year': absence.start_date.year, 'month': absence.start_date.month}))
    return page(request, 'absence', '부재 일정 수정' if pk else '나의 부재 일정 등록', 'calendar', form=form, absence=instance)


@login_required
@require_POST
def absence_delete(request, pk):
    absence = get_object_or_404(Absence, pk=pk)
    year, month = absence.start_date.year, absence.start_date.month
    absence.delete()
    messages.success(request, '부재 일정을 삭제했습니다.')
    return redirect(reverse('calendar') + '?' + urlencode({'year': year, 'month': month}))


@login_required
def calendar_leave(request, pk):
    doc = get_object_or_404(Document.objects.select_related('owner__profile'), pk=pk, kind='leave', status='approved')
    accessible = visible_documents(request.user).filter(pk=pk).exists()
    return page(request, 'calendar_leave', '휴가 일정', 'calendar', doc=doc, accessible=accessible)


@login_required
def company_holidays(request):
    if not request.user.profile.manage_leave:
        raise PermissionDenied
    year, _ = balance_filters(request.GET)
    instance = None
    if request.GET.get('edit'):
        instance = get_object_or_404(CompanyHoliday, pk=request.GET['edit'], active=True)
    if request.method == 'POST' and request.POST.get('id'):
        instance = get_object_or_404(CompanyHoliday, pk=request.POST['id'], active=True)
    form = CompanyHolidayForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        from .company_holidays import save_company_holiday
        try:
            item = save_company_holiday(request.user, form.cleaned_data, instance.pk if instance else None)
            messages.success(request, '회사 휴무를 저장했습니다.' + (' 직원별 공용연차 1일을 반영했습니다.' if item.use_annual else ' 연차 차감은 없습니다.'))
            return redirect(reverse('company_holidays') + f'?year={item.day.year}')
        except ValidationError as exc:
            form.add_error(None, exc)
    from .company_holidays import overlapping_leaves
    items = list(CompanyHoliday.objects.filter(active=True, day__year=year).order_by('day'))
    return page(request, 'company_holidays', '회사 휴무 관리', 'company_holidays', form=form, holiday=instance,
        selected_year=year, items=items, overlaps=overlapping_leaves(items),
        missing_hires=User.objects.filter(is_active=True, profile__approved=True, profile__hire_date__isnull=True).exclude(username__iexact='admin').count(),
        years=range(timezone.localdate().year-2, timezone.localdate().year+3))


@login_required
@require_POST
def company_holiday_delete(request, pk):
    if not request.user.profile.manage_leave:
        raise PermissionDenied
    item = get_object_or_404(CompanyHoliday, pk=pk, active=True)
    from .company_holidays import delete_company_holiday
    delete_company_holiday(request.user, pk)
    messages.success(request, '회사 휴무를 삭제했습니다. 차감된 공용연차는 원래 연도로 복원했습니다.')
    return redirect(reverse('company_holidays') + f'?year={item.day.year}')


@login_required
def welfare(request):
    from .welfare import AWARDS, BENEFITS, award_candidates
    year, _ = balance_filters(request.GET)
    tab = request.GET.get('tab', 'awards')
    if tab not in ['awards', 'benefits', 'leave']:
        tab = 'awards'
    from .regulations import annual_policy, tenure_table
    from .models import WelfarePolicy
    record = annual_policy(year)
    if not record or not record.text:
        record = Policy.objects.first()
    editable = WelfarePolicy.objects.first()
    return page(request, 'welfare', '직원복지', 'welfare', selected_year=year, tab=tab,
        awards=editable.awards if editable else AWARDS, benefits=editable.benefits if editable else BENEFITS,
        candidates=award_candidates(year, timezone.localdate()), policy=record, tenure_rows=tenure_table(year),
        applied_policy=annual_policy(year), years=range(timezone.localdate().year-2, timezone.localdate().year+3))

@login_required
def policy(request):
    if request.method == 'POST':
        if not request.user.profile.manage_leave:
            raise PermissionDenied
        messages.info(request, '연차규정은 규정 관리의 연차규정 탭에서 수정해 주세요.')
        return redirect(reverse('regulations') + '?tab=annual')
    from .regulations import annual_policy, tenure_table
    year, _ = balance_filters(request.GET)
    record = annual_policy(year)
    if not record or not record.text:
        record = Policy.objects.first()
    return page(request, 'policy', '연차규정', 'policy', policy=record, tenure_rows=tenure_table(year),
        applied_policy=annual_policy(year), selected_year=year,
        policy_logs=Audit.objects.filter(event='연차 산정규정 수정').select_related('actor')[:5])

@login_required
def notices(request):
    if request.method == 'POST':
        visible_notices(request.user).filter(read=False).update(read=True)
        return redirect('notices')
    ids = set(visible_documents(request.user).values_list('pk', flat=True))
    rows = [{'notice': n, 'accessible': n.document_id in ids} for n in visible_notices(request.user)]
    return page(request, 'notices', '알림함', 'notices', notice_rows=rows)

@login_required
@require_POST
def open_notice(request, pk):
    notice = get_object_or_404(visible_notices(request.user), pk=pk)
    notice.read = True
    notice.save(update_fields=['read'])
    if notice.document_id and visible_documents(request.user).filter(pk=notice.document_id).exists():
        return redirect('detail', pk=notice.document_id)
    messages.info(request, '알림을 확인했습니다. 이 문서는 현재 조회할 수 없습니다.')
    return redirect('notices')

@login_required
def staff(request):
    if not request.user.profile.manage_system:
        raise PermissionDenied
    group_keys = ['unclassified'] + DEPARTMENTS
    selected_group = request.GET.get('department')
    if selected_group not in group_keys:
        unclassified_exists = Profile.objects.filter(department_confirmed=False).exists()
        selected_group = 'unclassified' if unclassified_exists else next(
            (dept for dept in DEPARTMENTS if Profile.objects.filter(department_confirmed=True, department=dept).exists()),
            DEPARTMENTS[0])
    if request.method == 'POST':
        target = get_object_or_404(User, pk=request.POST.get('user'))
        if request.POST.get('intent') != 'reset':
            if request.POST.get('department') not in DEPARTMENTS or request.POST.get('rank') not in RANKS:
                messages.error(request, '부서와 직급을 확인해 주세요.')
                return redirect(f'{reverse("staff")}?department={selected_group}')
            if target == request.user and any(request.POST.get(f) != 'on' for f in ['approved', 'active', 'manage_system']):
                messages.error(request, '현재 로그인한 관리자의 가입 승인, 활성화, 관리자 권한은 해제할 수 없습니다.')
                return redirect(f'{reverse("staff")}?department={selected_group}')
        with transaction.atomic():
            from .models import CompanyHolidayLock
            if request.POST.get('intent') != 'reset':
                CompanyHolidayLock.objects.select_for_update().get(pk=1)
            if request.POST.get('intent') == 'reset':
                password = secrets.token_urlsafe(9)
                target.set_password(password)
                target.save(update_fields=['password'])
                target.profile.must_change_password = True
                target.profile.save(update_fields=['must_change_password'])
                audit(request.user, '임시 비밀번호 발급', detail=target.username)
                messages.success(request, f'{target.first_name}님의 임시 비밀번호: {password} — 본인에게 전달해 주세요.')
            else:
                department, rank = request.POST.get('department'), request.POST.get('rank')
                flags = ['approved', 'manage_leave', 'view_accounting', 'procure', 'manage_system']
                before = f'{target.first_name} / {target.profile.department} / {target.profile.rank} / 부서 확인 {target.profile.department_confirmed} / 활성화 {target.is_active} / ' + ', '.join(f'{f}={getattr(target.profile, f)}' for f in flags)
                target.profile.department, target.profile.rank = department, rank
                target.profile.department_confirmed = True
                target.first_name = request.POST.get('name', target.first_name).strip() or target.first_name
                for field in flags:
                    setattr(target.profile, field, request.POST.get(field) == 'on')
                target.is_active = request.POST.get('active') == 'on'
                target.save()
                target.profile.save()
                from .company_holidays import reconcile_employee
                reconcile_employee(request.user, target)
                after = f'{target.first_name} / {department} / {rank} / 부서 확인 {target.profile.department_confirmed} / 활성화 {target.is_active} / ' + ', '.join(f'{f}={getattr(target.profile, f)}' for f in flags)
                audit(request.user, '직원 권한 수정', detail=f'변경 전: {before}\n변경 후: {after}')
                messages.success(request, '직원 정보와 업무 권한을 저장했습니다.')
        if request.POST.get('intent') != 'reset':
            selected_group = target.profile.department
        return redirect(f'{reverse("staff")}?department={selected_group}')
    members = list(rank_order(User.objects.select_related('profile')))
    groups = [{'key': 'unclassified', 'label': '미분류 계정', 'members': []}] + [
        {'key': dept, 'label': dept, 'members': []} for dept in DEPARTMENTS]
    groups_by_key = {group['key']: group for group in groups}
    for member in members:
        key = member.profile.department if member.profile.department_confirmed else 'unclassified'
        groups_by_key.get(key, groups_by_key['unclassified'])['members'].append(member)
    selected = groups_by_key[selected_group]
    return page(request, 'staff', '직원·권한 관리', 'staff', staff=selected['members'],
                staff_groups=groups, selected_group=selected_group, selected_label=selected['label'],
                staff_total=len(members), departments=DEPARTMENTS, ranks=RANKS)

@login_required
def backups(request):
    if not request.user.profile.manage_system:
        raise PermissionDenied
    from .backups import create_backup, list_backups, restore_backup
    from django.db import connection
    if request.method == 'POST':
        try:
            if request.POST.get('intent') == 'restore':
                name = request.POST.get('file', '')
                restore_backup(name)
                audit(request.user, 'DB 복구', detail=name)
                messages.success(request, '데이터를 복원했습니다. 복원 전 데이터도 별도로 백업했습니다.')
            else:
                path = create_backup()
                audit(request.user, 'DB 백업', detail=path.name)
                messages.success(request, '데이터 백업을 생성했습니다.')
        except (ValueError, RuntimeError, OSError) as exc:
            messages.error(request, str(exc))
            Notice.objects.create(user=request.user, text=f'백업·복구 작업이 실패했습니다: {str(exc)[:180]}')
        return redirect('backups')
    return page(request, 'backups', '백업·복구', 'backups', backup_files=list_backups(),
                offline_restore=connection.vendor != 'sqlite')
