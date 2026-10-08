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
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST
from .forms import ApprovalAssignmentForm, DocumentForm, ProfilePasswordForm, SignupForm
from .models import AnnualBalance, Audit, DEPARTMENTS, RANKS, Document, Notice, Policy, Profile
from .services import act_on_document, audit, edit_balance, leave_amount, save_document, visible_documents
from .people import approval_people, rank_order
from .exports import purchase_workbook

User = get_user_model()

def page(request, template, title, section='dashboard', **context):
    return render(request, f'workflow/{template}.html', {'title': title, 'section': section,
        'auth_layout': template in ['login', 'signup', 'pending', 'password'], **context})

def health(request):
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return HttpResponse('ok', content_type='text/plain')

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
    waiting = visible_documents(request.user).filter(Q(status='review', reviewer=request.user) | Q(status='approve', approver=request.user))
    counts = {'mine': mine.count(), 'pending': mine.filter(status__in=['review', 'approve']).count(),
              'approved': mine.filter(status='approved').count(), 'waiting': waiting.count()}
    today = timezone.localdate()
    upcoming = mine.filter(kind='leave', status='approved', end_date__gte=today).order_by('start_date')[:3]
    return page(request, 'dashboard', '대시보드', documents=mine.select_related('owner', 'reviewer', 'approver')[:6],
                counts=counts, upcoming=upcoming, notices=Notice.objects.filter(user=request.user)[:3], today=today)

@login_required
def documents(request):
    mode = request.GET.get('mode', 'mine')
    accounting_categories, selected_kind = [], ''
    qs = visible_documents(request.user).select_related('owner', 'owner__profile', 'reviewer', 'approver')
    titles = {'mine': '내 기안', 'drafts': '임시저장함', 'pending': '결재함', 'history': '내 승인 내역',
              'archive': '반려함', 'accounting': '최종 승인 문서함', 'receive': '물품 수령 확인',
              'stock': '생산 재고 요청함', 'all': '전체 문서'}
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
        selected_kind = request.GET.get('kind', 'leave')
        if selected_kind not in dict(Document.KINDS):
            selected_kind = 'leave'
        counts = {row['kind']: row['total'] for row in qs.values('kind').annotate(total=Count('pk'))}
        for key, label in [('leave', '휴가원'), ('office', '구매요청서'), ('stock', '생산 재고 요청')]:
            params = request.GET.copy()
            params['mode'], params['kind'] = 'accounting', key
            for stale in ['status', 'shipment']:
                params.pop(stale, None)
            accounting_categories.append({'key': key, 'label': label, 'count': counts.get(key, 0), 'url': '?' + params.urlencode()})
        qs = qs.filter(kind=selected_kind)
    elif mode == 'receive':
        qs = qs.filter(status='approved', recipient=request.user, kind__in=['office', 'stock'])
    elif mode == 'all':
        if not request.user.profile.manage_system:
            raise PermissionDenied
    else:
        raise PermissionDenied
    if request.GET.get('q'):
        q = request.GET['q']
        qs = qs.filter(Q(title__icontains=q) | Q(number__icontains=q) | Q(owner__first_name__icontains=q) | Q(product__icontains=q))
    for key in ['kind', 'status', 'shipment']:
        if key == 'kind' and mode == 'accounting':
            continue
        if request.GET.get(key):
            qs = qs.filter(**{key: request.GET[key]})
    if request.GET.get('department'):
        qs = qs.filter(owner__profile__department=request.GET['department'])
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
    form = DocumentForm(request.POST or None, instance=instance, initial=initial if not pk else {},
                        submit=request.POST.get('intent') == 'submit')
    if request.method == 'POST' and form.is_valid():
        doc = form.save(commit=False)
        doc.owner = request.user
        try:
            save_document(doc, request.user, submit=request.POST.get('intent') == 'submit')
            messages.success(request, '기안이 제출되었습니다.' if doc.status == 'review' else '임시저장되었습니다.')
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
    if doc.status == 'approve' and doc.reviewer_id == u.pk:
        actions += [('cancel_review', '검토 승인 취소')]
    if doc.kind == 'stock' and doc.status == 'approved' and doc.reviewer_id == u.pk:
        actions += [('cancel_review', '검토 완료 취소')]
    if doc.kind != 'stock' and doc.status == 'approved' and doc.approver_id == u.pk:
        actions += [('cancel_approval', '최종 승인 취소')]
    if doc.status in ['draft', 'review'] and doc.owner_id == u.pk:
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
    assignment_form = ApprovalAssignmentForm()
    procurement_log = doc.audits.filter(event='발주 처리').select_related('actor').first() if doc.kind == 'stock' else None
    review_cancelled = doc.status == 'cancelled' and (doc.kind == 'stock' or not doc.approved_at)
    review_confirmed = bool(doc.reviewed_at) and not review_cancelled
    approval_cancelled = doc.kind != 'stock' and doc.status == 'cancelled' and bool(doc.approved_at)
    approval_confirmed = doc.kind != 'stock' and doc.status == 'approved' and bool(doc.approved_at)
    return page(request, 'detail', '재고 요청 상세' if doc.kind == 'stock' else '기안 상세',
                'stock' if doc.kind == 'stock' else 'mine', doc=doc, actions=actions, amount=amount, assignment_form=assignment_form, procurement_log=procurement_log,
                review_confirmed=review_confirmed, review_cancelled=review_cancelled,
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
    department = request.GET.get('department', '') if p.manage_leave else ''
    if department not in DEPARTMENTS:
        department = ''
    try:
        year = int(request.GET.get('year', timezone.localdate().year))
        if not 2000 <= year <= 2100:
            raise ValueError
    except ValueError:
        year = timezone.localdate().year
    if request.method == 'POST':
        if not p.manage_leave:
            raise PermissionDenied
        target = get_object_or_404(User, pk=request.POST.get('user'))
        try:
            posted_year = int(request.POST.get('year', year))
            if not 2000 <= posted_year <= 2100:
                raise ValueError
            value = Decimal(request.POST.get('value', ''))
            if not value.is_finite() or abs(value) > 99999:
                raise ValueError
            edit_balance(request.user, target, posted_year, request.POST.get('field'), value, request.POST.get('reason', ''))
            messages.success(request, '연차를 수정하고 변경 이력을 기록했습니다.')
        except (ValidationError, InvalidOperation, ValueError) as exc:
            messages.error(request, ' '.join(exc.messages) if isinstance(exc, ValidationError) else '연도와 연차 값을 확인해 주세요.')
        return redirect(reverse('balances') + '?' + urlencode({'year': year, 'department': department}))
    users = User.objects.filter(profile__approved=True) if p.manage_leave else User.objects.filter(pk=request.user.pk)
    if department:
        users = users.filter(profile__department=department)
    users = list(rank_order(users.select_related('profile')))
    balances_by_user = {balance.user_id: balance for balance in AnnualBalance.objects.filter(user__in=users, year=year)}
    rows = []
    for user in users:
        b = balances_by_user.get(user.pk)
        rows.append({'user': user, 'total': b.total if b else 0, 'used': b.used if b else 0, 'remaining': b.remaining if b else 0})
    logs = Audit.objects.filter(target__isnull=False)
    if not p.manage_leave:
        logs = logs.filter(target=request.user)
    elif department:
        logs = logs.filter(target__profile__department=department)
    return page(request, 'balances', '직원별 연차 관리' if p.manage_leave else '나의 연차', 'balances',
                rows=rows, selected_year=year, departments=DEPARTMENTS, selected_department=department,
                years=range(timezone.localdate().year - 2, timezone.localdate().year + 2), logs=logs.select_related('actor', 'target')[:20])

@login_required
def policy(request):
    record = Policy.objects.first()
    if not record:
        raise ValidationError('초기 규정 데이터를 준비해 주세요.')
    if request.method == 'POST':
        if not request.user.profile.manage_leave:
            raise PermissionDenied
        text = request.POST.get('text', '').strip()
        tenure = request.POST.get('tenure', '').strip()
        try:
            parsed = [line.split('|') for line in tenure.splitlines() if line.strip()]
            if not text or not parsed or any(len(row) != 2 or not row[0].strip() or int(row[1]) < 0 for row in parsed):
                raise ValueError
            with transaction.atomic():
                before = record.tenure + '\n' + record.text
                record.tenure, record.text, record.updated_by = tenure, text, request.user
                record.save()
                audit(request.user, '연차규정 수정', detail=f'변경 전\n{before}\n변경 후\n{tenure}\n{text}')
            messages.success(request, '규정을 수정하고 변경 이력을 보관했습니다.')
            return redirect('policy')
        except ValueError:
            messages.error(request, '규정 내용과 근속기간 표를 확인해 주세요. 표는 기간|일수 형식입니다.')
    tenure_rows = [line.split('|') for line in record.tenure.splitlines() if '|' in line]
    return page(request, 'policy', '연차규정', 'policy', policy=record, tenure_rows=tenure_rows,
                policy_logs=Audit.objects.filter(event='연차규정 수정').select_related('actor')[:5])

@login_required
def notices(request):
    if request.method == 'POST':
        Notice.objects.filter(user=request.user, read=False).update(read=True)
        return redirect('notices')
    ids = set(visible_documents(request.user).values_list('pk', flat=True))
    rows = [{'notice': n, 'accessible': n.document_id in ids} for n in Notice.objects.filter(user=request.user)]
    return page(request, 'notices', '알림함', 'notices', notice_rows=rows)

@login_required
@require_POST
def open_notice(request, pk):
    notice = get_object_or_404(Notice, pk=pk, user=request.user)
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
    if request.method == 'POST':
        try:
            if request.POST.get('intent') == 'restore':
                name = request.POST.get('file', '')
                restore_backup(name)
                audit(request.user, '시안 DB 복구', detail=name)
                messages.success(request, '시안 데이터를 복원했습니다. 복원 전 데이터도 별도로 백업했습니다.')
            else:
                path = create_backup()
                audit(request.user, '시안 DB 백업', detail=path.name)
                messages.success(request, '시안 데이터 백업을 생성했습니다.')
        except (ValueError, RuntimeError, OSError) as exc:
            messages.error(request, str(exc))
            Notice.objects.create(user=request.user, text=f'백업·복구 작업이 실패했습니다: {str(exc)[:180]}')
        return redirect('backups')
    return page(request, 'backups', '백업·복구', 'backups', backup_files=list_backups())
