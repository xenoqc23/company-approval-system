"""Package only the mobile UI assets/templates for an existing NAS installation."""
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
NAME = 'xenosys-mobile-ui-20261016'
FILES = (
    'workflow/static/workflow/mobile.css',
    'workflow/static/workflow/mobile.js',
    'workflow/templates/workflow/base.html',
    'workflow/templates/workflow/sidebar.html',
    'workflow/templates/workflow/table.html',
    'workflow/templates/workflow/calendar.html',
    'workflow/templates/workflow/mobile_calendar_agenda.html',
)

APPLY = '''#!/bin/sh
set -eu
umask 077
stage=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
base=${APPROVAL_MOBILE_BASE:-/volume1/docker/company-approval}
case "$base" in /*) ;; *) echo 'Use an absolute application folder.' >&2; exit 1;; esac
case "$base" in /|/volume1|/volume1/docker|/workspace|/tmp) echo 'Use the existing dedicated application folder.' >&2; exit 1;; esac
app="$base/app"
[ -f "$app/manage.py" ] && [ -f "$app/deploy/nas/nas.sh" ] || { echo 'Existing approval installation not found.' >&2; exit 1; }
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
backup=$(mktemp -d "$base/.mobile-ui-backup.XXXXXX")
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
echo MOBILE_UI_READY
'''.replace('__FILES__', '\n'.join(FILES))

INSTRUCTIONS = '''Xenosys 사내결재 — 모바일 화면 업데이트 (2026-10-16)

1. ZIP을 NAS File Station의 /docker/company-approval 폴더에 업로드합니다.
2. "여기에 압축 풀기"를 실행합니다. 아래 파일이 보여야 합니다.
   /volume1/docker/company-approval/xenosys-mobile-ui-20261016/APPLY_MOBILE_UI.sh
   app 폴더 전체를 교체하거나 기존 설치를 삭제하지 않습니다.
3. Windows PowerShell에서 NAS에 접속합니다.

   ssh admin@192.168.1.46

4. admin@xenonas:~$가 나온 NAS 창에서 실행합니다.

   sudo sh /volume1/docker/company-approval/xenosys-mobile-ui-20261016/APPLY_MOBILE_UI.sh

5. MOBILE_UI_READY를 확인합니다. 휴대폰에서 기존 HTTPS 주소를 새로고침합니다.
   https://xenonas.synology.me:18443/
   이전 화면이 보이면 기존 탭을 닫고 새 탭에서 접속합니다.
6. 휴가원 작성·임시저장, 문서 조회, 권한이 있는 직원의 결재 처리를 확인합니다.

기존 화면 파일은 .mobile-ui-backup.XXXXXX 폴더에 먼저 보관합니다.
기존 nas.sh update가 DB 백업과 이미지 빌드·웹 서비스 재시작을 수행합니다.
업데이트 중 웹 접속이 잠시 중단됩니다. 실패 시 출력과 백업 경로를 보관하고
원인 확인 없이 삭제·재설치·DB 복원을 실행하지 마세요.

묶음은 CSS·JavaScript와 화면 템플릿 7개만 복사합니다.
직원·문서·권한·연차 계산 코드, DB 스키마, .env, HTTPS 설정은 교체하지 않습니다.
휴대폰은 모바일 배치, PC는 기존 배치를 사용하며 주소와 계정은 같습니다.
앱 아이콘이 필요하면 휴대폰 브라우저의 홈 화면에 추가 기능을 사용할 수 있습니다.
'''


def build():
    output = ROOT / 'releases' / f'{NAME}.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {f'app/{name}': (ROOT / name).read_bytes() for name in FILES}
    payload['APPLY_MOBILE_UI.sh'] = APPLY.encode()
    payload['NAS_MOBILE_UPDATE.txt'] = INSTRUCTIONS.encode()
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
