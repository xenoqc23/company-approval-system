"""Package dashboard and calendar display changes without annual-rule or schema changes."""
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
NAME = 'xenosys-work-status-20261016'
FILES = (
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
base=${APPROVAL_WORK_STATUS_BASE:-/volume1/docker/company-approval}
case "$base" in /*) ;; *) echo 'Use an absolute application folder.' >&2; exit 1;; esac
case "$base" in /|/volume1|/volume1/docker|/workspace|/tmp) echo 'Use the existing dedicated application folder.' >&2; exit 1;; esac
app="$base/app"
[ -f "$app/manage.py" ] && [ -f "$app/deploy/nas/nas.sh" ] || { echo 'Existing approval installation not found.' >&2; exit 1; }
# This display patch needs the previously installed manual-leave feature.
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
backup=$(mktemp -d "$base/.work-status-backup.XXXXXX")
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
echo WORK_STATUS_READY
'''.replace('__FILES__', '\n'.join(FILES))

INSTRUCTIONS = '''Xenosys 사내결재 — 미결·개인 연차·직원 일정 업데이트 (2026-10-16)

기존 연차 사용 직접 등록 기능이 설치된 NAS용 화면 업데이트입니다.
연차 산정 방식 변경은 포함하지 않습니다.

1. ZIP을 File Station의 /docker/company-approval에 업로드합니다.
2. 우클릭 → "여기에 압축 풀기"를 선택합니다.
   /volume1/docker/company-approval/xenosys-work-status-20261016/APPLY_WORK_STATUS.sh
   파일이 생기는지 확인합니다. 기존 app·data 폴더는 삭제하지 않습니다.
3. Windows PowerShell에서 아래 한 줄을 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-work-status-20261016/APPLY_WORK_STATUS.sh"

4. NAS 관리자 비밀번호를 입력합니다. SSH·sudo 때문에 두 번 물을 수 있습니다.
5. 마지막 WORK_STATUS_READY가 나오면 PC·휴대폰 사이트를 새로고침합니다.

변경 내용
- 홈 결재 진행 상태: 내가 현재 검토·승인할 미결 건수와 결재함 링크.
  내 기안의 진행 중 건수는 별도 유지합니다. 열람만 해서는 미결에서 빠지지 않고,
  검토·승인·반려·취소 등으로 현재 결재 대기 상태가 끝나면 집계에서 빠집니다.
- 직원별 연차 관리: 개인 사용연차 열 추가.
  개인 사용 = 기존 전체 사용 − 활성 공용연차 차감분입니다.
  승인된 휴가와 경리 직접 등록 및 기존 잔액 정정을 반영합니다.
  잔여 = 사용가능 − 개인 사용으로 기존 잔액과 일치합니다.
- 직원 일정: 기존 승인 휴가와 취소되지 않은 직접 등록 휴가를 함께 표시합니다.
  직접 등록 표시·날짜·시간을 확인할 수 있고, 취소한 내역은 달력에서 제외됩니다.
  직원 공용 달력에는 개인 등록 사유를 노출하지 않습니다.
- 공용연차가 등록된 날의 날짜 숫자를 회사 휴무 표시와 같은 주황색으로 표시합니다.
  모바일 일정 목록에도 적용하며 공용연차 취소·삭제 시 기존 색상으로 돌아갑니다.

데이터 보존
- 복사 대상은 화면 조회 코드·템플릿·CSS 7개뿐입니다.
- 직원·문서·사용내역 삭제, 연차 총량 재계산, .env 교체, 비밀번호 초기화를 하지 않습니다.
- 모델·마이그레이션·연차 산정 코드·엑셀 내보내기 코드는 포함하지 않습니다.
- 기존 파일을 .work-status-backup.XXXXXX 폴더에 먼저 보관합니다.
- 기존 nas.sh update를 사용합니다. 새 이미지를 빌드한 뒤 웹을 잠시 중단하고,
  이전 이미지로 DB 백업을 완료한 후 새 이미지로 전환합니다.
  기존 설치의 일반 마이그레이션 및 미초기화 연차 동기화 절차는 그대로 실행됩니다.
  이미 초기화된 총연차·사용연차를 이 패치에서 재설정하지 않습니다.
- DB 백업과 이전 이미지는 NAS의 기존 백업·롤백 절차에 따라 보관됩니다.

업데이트 중 잠시 접속이 중단됩니다. 오류가 나면 출력과 보관 경로를 남기고
app/data 삭제·재설치·임의 DB 복원을 하지 마세요. 실패 시 READY 표시는 나오지 않습니다.
이 ZIP을 만든 개발 환경에서는 실제 NAS에 접속하지 않았습니다.
적용 완료 후 직원·문서·연차와 새 표시를 확인해 주세요.
'''


def build():
    output = ROOT / 'releases' / f'{NAME}.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {f'app/{name}': (ROOT / name).read_bytes() for name in FILES}
    payload['APPLY_WORK_STATUS.sh'] = APPLY.encode()
    payload['NAS_WORK_STATUS_UPDATE.txt'] = INSTRUCTIONS.encode()
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
    print(f'{output.name}: {output.stat().st_size} bytes; {len(FILES)} UI files verified.')
    return output


if __name__ == '__main__':
    build()
