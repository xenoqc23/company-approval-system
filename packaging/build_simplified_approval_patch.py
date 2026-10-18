"""Package senior-staff approval permissions and additive rule/document schema changes."""
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
NAME = 'xenosys-simplified-approval-20261019'
FILES = (
    'workflow/models.py',
    'workflow/delegation.py',
    'workflow/forms.py',
    'workflow/services.py',
    'workflow/regulations.py',
    'workflow/regulation_views.py',
    'workflow/views.py',
    'workflow/migrations/0012_simplified_approval.py',
    'workflow/templates/workflow/compose.html',
    'workflow/templates/workflow/regulations.html',
    'workflow/templates/workflow/detail.html',
    'workflow/templates/workflow/approval_track.html',
    'workflow/static/workflow/app.js',
    'workflow/static/workflow/simplified-approval.css',
    'workflow/calendars.py',
    'workflow/leave_records.py',
    'workflow/templates/workflow/dashboard.html',
    'workflow/templates/workflow/balances.html',
    'workflow/templates/workflow/calendar.html',
    'workflow/templates/workflow/mobile_calendar_agenda.html',
    'workflow/static/workflow/work-status.css',
)


APPLY = '''#!/bin/sh
set -eu
umask 077
stage=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
base=${APPROVAL_SIMPLIFIED_BASE:-/volume1/docker/company-approval}
case "$base" in /*) ;; *) echo 'Use an absolute application folder.' >&2; exit 1;; esac
case "$base" in /|/volume1|/volume1/docker|/workspace|/tmp) echo 'Use the existing dedicated application folder.' >&2; exit 1;; esac
app="$base/app"
[ -f "$app/manage.py" ] && [ -f "$app/deploy/nas/nas.sh" ] || { echo 'Existing approval installation not found.' >&2; exit 1; }
# Require the installed schema predecessor; do not bundle or reapply old annual-rule changes.
[ -f "$app/workflow/migrations/0011_hire_year_monthly.py" ] || { echo 'The previous NAS schema update (0011) is required. No files were copied.' >&2; exit 1; }
[ -f "$app/workflow/manual_leave.py" ] || { echo 'Install the manual-leave feature before this display update.' >&2; exit 1; }
# Refuse installers without the existing backup-before-migrate update path.
[ -f "$base/.env" ] || { echo 'Existing private NAS configuration not found.' >&2; exit 1; }
grep -q 'backup_name=$(run_manage backup_database --kind update)' "$app/deploy/nas/nas.sh" || { echo 'The existing NAS updater with database backup is required.' >&2; exit 1; }
[ -w "$app" ] || { echo 'Run this script with sudo.' >&2; exit 1; }
for marker in .pending-image .recovery-in-progress .operation.lock; do
    [ ! -e "$base/$marker" ] || { echo 'Another update or recovery is pending. Do not overwrite source files.' >&2; exit 1; }
done
command -v sha256sum >/dev/null || { echo 'sha256sum is required to verify the update.' >&2; exit 1; }
(cd "$stage" && sha256sum -c SHA256SUMS)
files='__FILES__'
for file in $files; do
    [ -s "$stage/app/$file" ] || { echo 'Update file missing.' >&2; exit 1; }
done
backup=$(mktemp -d "$base/.simplified-approval-backup.XXXXXX")
for file in $files; do
    mkdir -p "$backup/$(dirname "$file")" "$app/$(dirname "$file")"
    if [ -f "$app/$file" ]; then
        cp -p "$app/$file" "$backup/$file"
    else
        printf '%s\\n' "$file" >> "$backup/NEW_FILES.txt"
    fi
done
printf 'UI_SOURCE_BACKUP: %s\\n' "$backup"
for file in $files; do
    cp "$stage/app/$file" "$app/$file"
done
sh "$app/deploy/nas/nas.sh" update
echo SIMPLIFIED_APPROVAL_READY
'''.replace('__FILES__', '\n'.join(FILES))

INSTRUCTIONS = '''Xenosys 사내결재 — 과장급 이상 간소결재 업데이트 (2026-10-19)

1. ZIP을 File Station /docker/company-approval에 업로드합니다.
2. 우클릭 → 여기에 압축 풀기를 선택합니다. 기존 app·data 폴더는 삭제하지 않습니다.
3. Windows PowerShell에서 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-simplified-approval-20261019/APPLY_SIMPLIFIED_APPROVAL.sh"

4. NAS 관리자 비밀번호를 입력합니다. SSH와 sudo 때문에 두 번 물을 수 있습니다.
5. 마지막 SIMPLIFIED_APPROVAL_READY를 확인한 후 PC·휴대폰 사이트를 새로고침합니다.

권한 설정
- 규정 관리 → 전결규정에서 기존 규정을 수정하거나 새 규정을 만듭니다.
- 문서 종류, 필요한 부서·직급·특정 직원을 지정합니다. 선택한 조건을 모두 만족해야 합니다.
- '과장급 이상에게 검토 생략 선택 허용' 또는 '과장급 이상에게 본인 전결 선택 허용'을 체크합니다.
- 검토·승인 가능 직급을 지정합니다. 필요한 경우 담당자 고정 또는 최종 승인자를 기안자 본인으로 지정할 수 있습니다.
- '규정 사용'을 체크해 저장합니다. 오른쪽 미리보기에서 특정 기안자와 결재방식을 선택해 확인합니다.
- 직원별 → 부서별 → 직급별 → 회사 기본 순으로 적용합니다. 같은 우선순위의 겹치는 규정은 저장을 막습니다.
- 사원·주임·대리와 시스템 관리자 계정은 새 간소결재 선택 기능을 사용할 수 없습니다.
- 기존 금액별 기본 경로와 기본 경로의 검토 생략 설정은 유지됩니다.
- 새 본인 전결 권한은 자동으로 부여하지 않습니다. 관리자가 규정에서 허용해야 합니다.

기안·처리
- 허용된 과장·팀장·부장·이사는 기안 화면에서 규정 기본 / 검토 생략 / 본인 전결 중 허용된 방식을 고릅니다.
- 검토 생략은 승인자만 선택하고 별도 최종 승인을 기다립니다.
- 본인 전결은 담당자 선택 없이 '전결로 제출·완료'를 누르면 즉시 완료됩니다.
- 임시저장은 전결·연차 차감되지 않습니다. 실제 제출 시 최신 직급·권한·금액 조건을 다시 확인합니다.
- 본인 전결 휴가는 제출 시 연차를 차감하고, 승인된 사용내역과 직원 일정에 반영합니다.
- 전결자·처리 시각·규정 버전이 남고 기존 최종 승인 취소 절차로 연차를 한 번 복원할 수 있습니다.
- 생산 재고 요청은 기존 검토·발주 경로를 유지합니다.

데이터 보존
- 기존 직원·문서·연차·직접 등록·공용연차·규정 값을 초기화하거나 삭제하지 않습니다.
- 이미 제출한 문서는 제출 당시 경로를 유지합니다. 새 규정은 새 제출부터 적용됩니다.
- 마이그레이션 0012는 새 선택·권한·대상·담당자 필드와 연결 테이블만 추가합니다.
- 기존 문서는 규정 기본값, 새 간소결재 권한은 꺼진 값으로 추가됩니다.
- 연차 산정 코드·이전 연차 변경 마이그레이션·.env·비밀번호·실제 DB는 ZIP에 포함하지 않습니다.
- 앞선 미결·개인 사용연차·직원 일정 화면 변경도 포함합니다.
- 적용 전 이전 소스를 .simplified-approval-backup.XXXXXX에 보관합니다.
- 기존 nas.sh update로 이미지를 빌드하고, 이전 이미지에서 DB 백업을 완료한 후 필요한 마이그레이션과 웹 전환을 수행합니다.
- 웹 접속은 잠시 중단됩니다. 실패 시 READY가 나오지 않으며 백업을 남깁니다.
- 이전 NAS 스키마 업데이트(0011) 소스가 없으면 복사하기 전에 중단합니다.
- 오류가 나면 마지막 출력과 백업 경로를 보관하고 data/app 삭제·재설치·임의 DB 복원을 하지 마세요.

개발 환경 검증은 가상 데이터로만 수행했습니다. 실제 NAS에는 이 스크립트를 실행한 후 적용됩니다.
'''


def build():
    output = ROOT / 'releases' / f'{NAME}.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {f'app/{name}': (ROOT / name).read_bytes() for name in FILES}
    payload['APPLY_SIMPLIFIED_APPROVAL.sh'] = APPLY.encode()
    payload['NAS_SIMPLIFIED_APPROVAL_UPDATE.txt'] = INSTRUCTIONS.encode()
    payload['SHA256SUMS'] = ''.join(
        f'{sha256(data).hexdigest()}  {name}\n' for name, data in payload.items()
    ).encode()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            archive.writestr(f'{NAME}/{name}', data)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        for name, data in payload.items():
            assert archive.read(f'{NAME}/{name}') == data
    print(f'{output.name}: {output.stat().st_size} bytes; {len(FILES)} runtime files verified.')
    return output


if __name__ == '__main__':
    build()
