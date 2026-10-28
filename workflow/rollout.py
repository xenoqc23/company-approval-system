"""Private, fail-closed NAS rollout checks. Never creates employees or resets data."""
import hashlib
import json
import os
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import F, Q
from django.db.migrations.loader import MigrationLoader
from .models import Profile, Document

RELEASE = 'nas-reviewer-20261028-v3'
ROLES = ('development_checker', 'other_checker', 'purchaser', 'representative')
PROFILE_FIELDS = ('user_id', 'department', 'rank', 'approved', 'department_confirmed', 'representative_slot', 'manage_system')


def table_columns(cursor, table):
    # Django/SQLite introspection cannot parse some existing complex CHECKs.
    cursor.execute(f'SELECT * FROM {connection.ops.quote_name(table)} WHERE 1=0')
    return [item[0] for item in cursor.description]


def require_schema():
    if not settings.INTEGRATED_PURCHASES or settings.PURCHASE_LAB_ENABLED:
        raise CommandError('실제 통합 운영 설정에서 실행해 주세요. 테스트 역할 전환은 사용할 수 없습니다.')
    loader = MigrationLoader(connection)
    if set(loader.applied_migrations) - set(loader.disk_migrations):
        raise CommandError('현재 DB에 이 업데이트보다 새로운 변경 이력이 있습니다. 적용을 중단합니다.')
    loader.check_consistent_history(connection)
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        for table, needed in {'auth_user': {'id','first_name','username','is_active'},
                              'workflow_profile': set(PROFILE_FIELDS),
                              'workflow_document': {'id','owner_id','reviewer_id','approver_id','status'}}.items():
            if table not in tables:
                raise CommandError('기존 운영 DB가 확인되지 않습니다. 새 설치 또는 초기화를 실행하지 마세요.')
            columns = set(table_columns(cursor, table))
            if not needed <= columns:
                raise CommandError('기존 DB 버전 확인이 필요합니다. 지원되지 않는 구성이므로 적용을 중단합니다.')
    return tables


def policy_state(tables):
    if 'purchasing_purchasepolicy' not in tables:
        return None
    from purchasing.models import PurchasePolicy
    state = PurchasePolicy.objects.filter(pk=1).values('version','enabled','dev_director_id','production_director_id','representative_id').first()
    if state:
        state['finance'] = sorted(PurchasePolicy.objects.get(pk=1).finance.values_list('pk', flat=True))
    return state


def account(pk):
    user = get_user_model().objects.filter(pk=pk).values('id','username','first_name','is_active').first()
    profile = Profile.objects.filter(user_id=pk).values(*PROFILE_FIELDS).first()
    if not user or not profile:
        raise CommandError('지정된 직원의 기존 계정·직원 정보가 없습니다. 계정을 자동 생성하지 않습니다.')
    return {'user': user, 'profile': profile}


def match(selector):
    field, value = ('username', selector[9:]) if selector.startswith('username:') else ('first_name', selector)
    matches = list(get_user_model().objects.filter(**{field: value}).values_list('pk', flat=True)[:2])
    if len(matches) != 1:
        raise CommandError('직원 계정이 없거나 동명이인입니다. 직원 권한관리에서 확인하고 username:아이디로 지정해 주세요.')
    return matches[0]


def validate(ids, operator_id):
    people = {role: account(ids[role]) for role in ROLES}
    if ids['development_checker'] == ids['other_checker']:
        raise CommandError('본인 요청의 대체 확인을 위해 두 구매확인 담당자는 서로 다른 직원이어야 합니다.')
    for role, person in people.items():
        u, p = person['user'], person['profile']
        if not u['is_active'] or not p['approved'] or (role not in ('development_checker','other_checker') and not p['department_confirmed']):
            raise CommandError('구매 담당자의 활성·가입 승인·부서 확인이 필요합니다.')
        if role in ('development_checker','other_checker'):
            if p['representative_slot']:
                raise CommandError('구매확인 담당자는 활성·가입 승인된 직원 계정으로 지정해 주세요.')
        elif role == 'representative':
            if p['representative_slot'] != 1:
                raise CommandError('지정한 계정이 현재 회사 대표로 등록되어 있지 않습니다. 직원 권한관리에서 확인해 주세요.')
        elif p['representative_slot']:
            raise CommandError('구매 담당자는 대표 계정과 구분해 주세요.')
    operator = account(operator_id)
    if not operator['user']['is_active'] or not operator['profile']['approved'] or not operator['profile']['manage_system'] or operator['profile']['representative_slot']:
        raise CommandError('기존 시스템 관리자의 실행 계정을 지정해 주세요.')
    blocked = list(Document.objects.filter(Q(status='review', owner_id=F('reviewer_id')) |
                    Q(status='approve', owner_id=F('approver_id'))).values_list('pk', flat=True)[:20])
    if 'purchasing_purchaserequest' in connection.introspection.table_names():
        from purchasing.models import PurchaseRequest
        blocked_purchase = list(PurchaseRequest.objects.filter(
            Q(status='review',owner_id=F('reviewer_id')) | Q(status='approval',owner_id=F('approver_id')) |
            Q(status='director',owner_id=F('director_id'))).values_list('pk', flat=True)[:20])
    else:
        blocked_purchase = []
    if blocked or blocked_purchase:
        raise CommandError(f'본인이 검토·승인자로 지정된 진행 문서가 있습니다. 기존 문서 ID {blocked}, 구매 문서 ID {blocked_purchase}. 담당자를 정리한 뒤 다시 점검해 주세요.')
    return people, operator


def check_handover(ids, previous):
    if not previous:
        return
    from purchasing.models import PurchaseRequest, PurchaseReport
    removed = set(previous['finance']) - {ids['purchaser']}
    if removed:
        ongoing = PurchaseRequest.objects.filter(status__in=[
            'ready','supplement','reapproval','ceo','allowed','paid','hold']).exclude(confirmed_at=None)
        for route in ongoing.values_list('purchase_route', flat=True):
            if removed.intersection(route.get('collector_ids', [])):
                raise CommandError('진행·수령 대기 문서가 있는 구매 담당자는 먼저 인계·처리를 정리해 주세요. 기존 담당자를 자동 교체하지 않습니다.')
    if previous['representative_id'] != ids['representative'] and PurchaseReport.objects.filter(
            status='pending', representative_id=previous['representative_id']).exists():
        raise CommandError('이전 대표에게 올린 진행 요청이 있습니다. 해당 요청을 먼저 정리해 주세요.')


def write_private(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, ensure_ascii=False, sort_keys=True)
    temp.chmod(0o600)
    temp.replace(path)


def read_plan(path):
    try:
        plan = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise CommandError('사전 점검 파일이 없습니다. 먼저 --check를 실행해 주세요.') from exc
    if plan.get('release') != RELEASE or plan.get('applied'):
        raise CommandError('새 사전 점검이 필요합니다. --check부터 다시 실행해 주세요.')
    return plan


def prepare(options):
    tables = require_schema()
    before = policy_state(tables)
    selected = [options.get(role) for role in ROLES]
    if any(selected):
        if not all(selected):
            raise CommandError('네 역할을 모두 지정해 주세요. 일부 역할을 추측하지 않습니다.')
        ids = {role: match(options[role]) for role in ROLES}
    elif before and before['dev_director_id'] and before['production_director_id'] and before['representative_id'] and len(before['finance']) >= 1:
        ids = dict(development_checker=before['dev_director_id'],other_checker=before['production_director_id'],
                   purchaser=before['finance'][0],representative=before['representative_id'])
    else:
        raise CommandError('기존 구매 담당자가 지정되지 않았습니다. 네 역할의 기존 계정을 지정해 주세요.')
    operator_id = match('username:' + options['operator'])
    people, operator = validate(ids, operator_id)
    check_handover(ids, before)
    return dict(release=RELEASE, ids=ids, operator_id=operator_id, people=people, operator=operator,
                policy=before, applied=False, apply_roles=any(selected))


def check_unchanged(plan, *, migrated=False):
    tables = require_schema()
    people, operator = validate(plan['ids'], plan['operator_id'])
    if people != plan['people'] or operator != plan['operator']:
        raise CommandError('사전 점검 이후 직원 정보가 변경되었습니다. 다시 점검해 주세요.')
    current = policy_state(tables)
    if migrated and plan['policy'] is None:
        if not current or current['enabled'] or current['version'] != 1 or current['finance'] or current['dev_director_id'] or current['production_director_id'] or current['representative_id']:
            raise CommandError('신규 구매 규정이 예상과 다릅니다. 자동으로 덮어쓰지 않습니다.')
    elif current != plan['policy']:
        raise CommandError('사전 점검 이후 구매 담당자·규정이 변경되었습니다. 다시 점검해 주세요.')


def table_digest(table, columns, last_id=None):
    quote = connection.ops.quote_name
    sql = f'SELECT {", ".join(quote(c) for c in columns)} FROM {quote(table)}'
    params = []
    if last_id is not None:
        sql += f' WHERE {quote("id")} <= %s'
        params.append(last_id)
    # Deterministic order also for session keys and many-to-many tables.
    sql += ' ORDER BY ' + ', '.join(quote(c) for c in columns)
    digest = hashlib.sha256()
    count = 0
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        while True:
            rows = cursor.fetchmany(500)
            if not rows: break
            for row in rows:
                digest.update(json.dumps(row, default=str, ensure_ascii=False, separators=(',',':')).encode())
                digest.update(b'\n')
                count += 1
    return {'count': count, 'sha256': digest.hexdigest()}


def capture_baseline():
    result = {}
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
        schemas = {table: sorted(table_columns(cursor, table))
                   for table in tables if table != 'django_migrations'}
    for table, columns in schemas.items():
        last_id = None
        if table in ('auth_permission','django_content_type'):
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT MAX(id) FROM {connection.ops.quote_name(table)}')
                last_id = cursor.fetchone()[0] or 0
        result[table] = dict(columns=columns, last_id=last_id, **table_digest(table, columns, last_id))
    return result


def attachments():
    root = settings.DATA_DIR / 'purchase-attachments'
    if root.is_symlink():
        raise CommandError('첨부파일 경로가 링크입니다. 실제 보관 경로를 확인해 주세요.')
    files = {}
    if root.exists():
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise CommandError('첨부파일 링크는 지원하지 않습니다.')
            if not path.is_file(): continue
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(chunk)
            files[path.relative_to(root).as_posix()] = {'size': path.stat().st_size, 'sha256': digest.hexdigest()}
    return files


def verify_baseline(plan):
    if 'baseline' not in plan:
        raise CommandError('정지 시점의 데이터 기준값이 없습니다. 업데이트 순서를 확인해 주세요.')
    for table, before in plan['baseline'].items():
        after = table_digest(table, before['columns'], before['last_id'])
        if after != {k: before[k] for k in ('count','sha256')}:
            raise CommandError(f'기존 데이터 보존 비교 실패: {table}. 서비스를 시작하지 말고 백업으로 복구해 주세요.')
    if attachments() != plan['attachments']:
        raise CommandError('기존 첨부파일 보존 비교에 실패했습니다. 백업을 확인해 주세요.')


@transaction.atomic
def apply_plan(plan):
    check_unchanged(plan, migrated=True)
    verify_baseline(plan)
    if not plan.get('apply_roles',True):
        return False
    from purchasing.forms import PurchaseAssignmentsForm
    from purchasing.models import PurchasePolicy
    from purchasing.services import event, validate_policy_people
    policy = PurchasePolicy.objects.select_for_update().get(pk=1)
    form = PurchaseAssignmentsForm(dict(dev_director=plan['ids']['development_checker'],
        production_director=plan['ids']['other_checker'],finance=[plan['ids']['purchaser']],
        representative=plan['ids']['representative'],revision=policy.version,reason='NAS 운영 업데이트: 확정된 기존 담당자 연결'))
    if not form.is_valid():
        raise CommandError('기존 계정의 구매 권한 설정 조건이 변경되었습니다. 직원 권한관리에서 확인해 주세요.')
    actor = get_user_model().objects.get(pk=plan['operator_id'])
    policy = form.save(actor)
    policy.enabled = True
    policy.department_routing = True
    policy.combine_confirmation = True
    validate_policy_people(policy)
    policy.save()
    event(actor, 'NAS 구매 규정 적용', detail='기존 계정 연결·동일 담당자 승인 시 구매확인 통합. 기존 문서·연차·암호 보존.')
    return True
