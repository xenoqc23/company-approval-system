"""Package dated manual leave usage for the existing HTTPS/mobile NAS install."""
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZipFile

import build_mobile_ui_patch as mobile

ROOT = mobile.ROOT
NAME = 'xenosys-manual-leave-20261016'
FILES = (
    'workflow/models.py',
    'workflow/services.py',
    'workflow/forms.py',
    'workflow/views.py',
    'workflow/urls.py',
    'workflow/leave_records.py',
    'workflow/manual_leave.py',
    'workflow/migrations/0010_manualleaveusage.py',
    'workflow/templates/workflow/balances.html',
    'workflow/templates/workflow/leave_history.html',
    'workflow/templates/workflow/manual_leave_form.html',
    'workflow/static/workflow/manual-leave.css',
    'workflow/static/workflow/manual-leave.js',
)
assert mobile.APPLY.count('\n'.join(mobile.FILES)) == 1
APPLY = (mobile.APPLY.replace('\n'.join(mobile.FILES), '\n'.join(FILES))
         .replace('APPROVAL_MOBILE_BASE', 'APPROVAL_MANUAL_LEAVE_BASE')
         .replace('.mobile-ui-backup.', '.manual-leave-backup.')
         .replace('UI_SOURCE_BACKUP', 'MANUAL_LEAVE_SOURCE_BACKUP')
         .replace('MOBILE_UI_READY', 'MANUAL_LEAVE_READY'))

INSTRUCTIONS = '''Xenosys 사내결재 — 연차 사용 직접 등록 (2026-10-16)

1. ZIP을 NAS File Station의 /docker/company-approval 폴더에 업로드합니다.
2. ZIP을 우클릭해 "여기에 압축 풀기"를 실행합니다.
3. Windows PowerShell에서 아래 한 줄을 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-manual-leave-20261016/APPLY_MANUAL_LEAVE.sh"

4. NAS 관리자 비밀번호를 묻는 경우 입력합니다. 마지막 MANUAL_LEAVE_READY를 확인합니다.
5. 기존 HTTPS 주소에서 새로고침합니다.
   https://xenonas.synology.me:18443/
6. 연차 관리 권한이 있는 계정으로 직원별 연차 관리 → 해당 직원의
   ‘연차 사용 직접 등록’을 선택합니다. 사용 내역 화면에도 같은 버튼이 있습니다.
7. 실제 사용 날짜·휴가 종류·사유를 입력합니다. 반차·외출은 실제 시간도 입력합니다.
   연차 1일 / 오전·오후반차 0.5일 / 외출 0.25일입니다.
   여러 날의 연차는 날짜별로 등록합니다.
8. 사용연차가 입력한 만큼 늘고 잔여연차가 줄며, 사용 내역에 ‘경리 직접 등록’으로 표시됩니다.
   잘못 등록했으면 해당 행의 ‘등록 취소 · 연차 복원’에서 사유를 입력합니다.
   취소 기록은 ‘전체 이력 · 취소 포함’에서 확인합니다.

이 묶음에는 연차 산정 기준 변경이 없습니다.
기존 총연차·근무연수 산정·과거 사용연차를 다시 계산하거나 변경하지 않습니다.
신규 등록 또는 취소한 일수만 해당 사용 연도의 사용연차에 더하거나 뺍니다.
기존 수동 수정으로 이미 반영한 사용분을 다시 등록하면 중복 차감되므로 먼저 확인하세요.
결재 중·결재 완료·활성 직접 등록과 날짜/시간이 겹치면 새 등록을 거절합니다.
같은 등록 요청을 반복 전송하거나 취소를 반복해도 두 번 차감/복원하지 않습니다.
직접 등록한 휴가를 결재 문서로 다시 제출하려면 기존 직접 등록을 사유와 함께 취소하세요.

등록/취소는 연차 관리 권한이 있는 직원만 처리할 수 있습니다.
기존 잔액 정정 기능은 별도로 유지하며, 과거 정정 기록을 실제 사용 내역으로 변환하지 않습니다.
직접 등록한 사용 내역은 직원별 연차 사용 내역에 표시합니다.

업데이트는 새 기록 테이블을 추가합니다. 기존 nas.sh update가 기존 이미지로 DB 백업을 만든 뒤
마이그레이션·웹 이미지 전환을 수행합니다. 기존 소스는 .manual-leave-backup.XXXXXX에 보관합니다.
업데이트 중 접속이 잠시 중단됩니다. .env·계정 비밀번호·HTTPS 설정은 덮어쓰지 않습니다.
오류 발생 시 출력과 백업 경로를 보관하고 삭제·재설치·DB 복원을 임의로 실행하지 마세요.
이 폴더를 app 폴더 전체에 덮어쓰거나 기존 app/data 폴더를 삭제하지 마세요.
'''


def build():
    output = ROOT / 'releases' / f'{NAME}.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {f'app/{name}': (ROOT / name).read_bytes() for name in FILES}
    payload['APPLY_MANUAL_LEAVE.sh'] = APPLY.encode()
    payload['NAS_MANUAL_LEAVE.txt'] = INSTRUCTIONS.encode()
    payload['SHA256SUMS'] = ''.join(
        f'{sha256(data).hexdigest()}  {name}\n' for name, data in payload.items()).encode()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            archive.writestr(f'{NAME}/{name}', data)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        for name, data in payload.items():
            assert archive.read(f'{NAME}/{name}') == data
    print(f'{output.name}: {output.stat().st_size} bytes; {len(FILES)} files verified.')
    return output


if __name__ == '__main__':
    build()
