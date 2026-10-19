"""Package common approval rules, retained-history rule deletion and rejected-document deletion."""
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
NAME = 'xenosys-common-rules-20261019'
FILES = (
    'workflow/models.py',
    'workflow/delegation.py',
    'workflow/forms.py',
    'workflow/services.py',
    'workflow/regulations.py',
    'workflow/regulation_views.py',
    'workflow/views.py',
    'workflow/migrations/0012_simplified_approval.py',
    'workflow/migrations/0013_common_rule_deletion.py',
    'workflow/home.py',
    'workflow/notifications.py',
    'workflow/urls.py',
    'workflow/templates/workflow/documents.html',
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
base=${APPROVAL_COMMON_RULES_BASE:-/volume1/docker/company-approval}
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
backup=$(mktemp -d "$base/.common-rules-backup.XXXXXX")
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
echo COMMON_RULES_READY
'''.replace('__FILES__', '\n'.join(FILES))

INSTRUCTIONS = '''Xenosys 사내결재 — 공통 전결규정·삭제 기능 (2026-10-19)

1. ZIP을 File Station /docker/company-approval에 업로드합니다.
2. 우클릭 → 여기에 압축 풀기를 선택합니다. 기존 app·data 폴더는 삭제하지 않습니다.
3. Windows PowerShell에서 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-common-rules-20261019/APPLY_COMMON_RULES.sh"

4. NAS 관리자 비밀번호를 입력합니다. SSH와 sudo 때문에 두 번 물을 수 있습니다.
5. 마지막 COMMON_RULES_READY 확인 후 PC·휴대폰 사이트를 새로고침합니다.

변경 내용
- 전결규정의 문서 종류에 '모든 문서'를 추가하고 새 규정의 기본값으로 설정했습니다.
- 하나의 공통 규정으로 휴가원·구매요청서·생산 재고에 검토·승인과 허용된 간소결재를 적용합니다.
- 과장급 이상에게 허용한 검토 생략·본인 전결 권한은 생산 재고에도 동일하게 적용합니다.
- 공통 규정의 금액 조건은 구매요청서에만 적용합니다. 휴가·재고는 대상 조건으로 판단합니다.
- 기존 문서별 규정은 자동으로 공통 규정으로 바꾸거나 삭제하지 않습니다.
- 직원별 → 부서별 → 직급별 → 회사 기본 우선순위를 유지합니다.
  같은 대상 우선순위에서는 문서별 규정이 공통 규정보다 우선합니다.
- 공통 규정을 적용한 새 재고 문서는 최종 결재가 끝난 후 발주·입고를 진행합니다.
  이미 제출된 재고 문서는 당시 저장된 경로를 그대로 사용합니다.
- 전결규정 목록에서 '삭제'를 누르면 확인창 후 목록과 새 기안 적용 대상에서 제외됩니다.
  규정 내용·삭제자·삭제 시각·변경 이력과 기존 문서의 결재선은 보관합니다.
- 본인이 기안한 반려 문서는 상세 화면의 '기안 삭제'로 목록에서 제외할 수 있습니다.
  문서·반려 사유·처리 이력은 보관하고 연차 수치는 변경하지 않습니다.
  다른 직원의 문서나 결재 완료 문서는 삭제할 수 없습니다.

적용 후 설정
규정관리 → 전결규정에서 문서 종류 '모든 문서'와 대상 직원·부서·직급을 지정합니다.
필요한 간소결재 권한과 담당자를 지정하고 '규정 사용'을 체크해 저장합니다.
기존 규정이 우선 적용되는 경우 해당 규정을 수정·사용 해제·삭제해 정리할 수 있습니다.
관리자가 명시적으로 선택하지 않은 직원에게 새 본인 전결 권한을 자동 부여하지 않습니다.

데이터 보존과 백업
- 패치는 선행 간소결재 기능(0012)과 이번 추가형 변경(0013)을 포함합니다.
- 0013은 규정 삭제 기록 필드를 추가하고 문서 범위 선택지를 확장합니다.
- 기존 직원·암호·문서·연차·사용내역·규정의 적용 범위를 일괄 변환하거나 초기화하지 않습니다.
- 연차 산정 코드·이전 연차 변경 마이그레이션·.env·비밀번호·실제 DB는 포함하지 않습니다.
- 기존 소스를 .common-rules-backup.XXXXXX에 보관한 후 nas.sh update를 실행합니다.
- 새 이미지를 빌드하고 이전 이미지로 DB 백업을 완료한 다음 마이그레이션과 웹 전환을 수행합니다.
- 업데이트 중 접속이 잠시 중단됩니다. 실패 시 READY를 출력하지 않고 백업을 남깁니다.
- 선행 NAS 스키마 0011 소스가 없거나 이전 작업이 진행 중이면 복사 전에 중단합니다.
- 오류 시 마지막 출력과 백업 경로를 보관하고 app/data 삭제·재설치·임의 DB 복원을 하지 마세요.

개발 검증은 분리된 가상 데이터로만 수행했습니다. 실제 NAS에는 스크립트를 실행한 후 적용됩니다.
'''


def build():
    output = ROOT / 'releases' / f'{NAME}.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {f'app/{name}': (ROOT / name).read_bytes() for name in FILES}
    payload['APPLY_COMMON_RULES.sh'] = APPLY.encode()
    payload['NAS_COMMON_RULES_UPDATE.txt'] = INSTRUCTIONS.encode()
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
