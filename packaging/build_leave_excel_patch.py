"""Include manual leave registration and its prerequisites for either NAS state."""
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZipFile

import build_manual_leave_patch as manual

ROOT = manual.ROOT
NAME = 'xenosys-leave-excel-20261016'
FILES = (*manual.FILES, 'workflow/exports.py')
assert manual.APPLY.count('\n'.join(manual.FILES)) == 1
APPLY = (manual.APPLY.replace('\n'.join(manual.FILES), '\n'.join(FILES))
         .replace('APPROVAL_MANUAL_LEAVE_BASE', 'APPROVAL_LEAVE_EXCEL_BASE')
         .replace('.manual-leave-backup.', '.leave-excel-backup.')
         .replace('MANUAL_LEAVE_SOURCE_BACKUP', 'LEAVE_EXCEL_SOURCE_BACKUP')
         .replace('MANUAL_LEAVE_READY', 'LEAVE_EXCEL_READY'))

INSTRUCTIONS = '''Xenosys 사내결재 — 연차 엑셀 공용연차·간단 사용내역 추가 (2026-10-16)

1. ZIP을 File Station의 /docker/company-approval에 업로드합니다.
2. 우클릭해 "여기에 압축 풀기"를 실행합니다.
3. Windows PowerShell에서 아래 한 줄을 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-leave-excel-20261016/APPLY_LEAVE_EXCEL.sh"

4. 비밀번호 요청 시 NAS 관리자 비밀번호를 입력합니다.
5. 마지막 LEAVE_EXCEL_READY를 확인하고 사이트를 새로고침합니다.
6. 직원별 연차 관리에서 조회 연도·부서를 선택한 뒤 엑셀 다운로드를 누릅니다.

엑셀의 변경 사항:
- 연도별 연차 현황 시트에 공용연차 일수와 사용내역 열 추가.
- 인원별 연차표에도 사용내역 추가, 기존 공통사용연차 제목은 공용연차로 통일.
- 예: 10/16(연차), 10/9(공용연차), 9/1(반차), 8/28(외출)
- 오전·오후반차는 모두 반차로 표시. 여러 날은 평일 사용일마다 표시.
- 조회 연도의 결재 완료·경리 직접 등록·공용연차만 날짜 내림차순으로 표시.
- 승인·등록되어 이미 차감된 사용 예정 휴가도 포함. 취소·반려·대기는 제외.
- 실제 날짜를 알 수 없는 과거 잔액 정정은 사용내역으로 만들지 않음.
- 사유·결재자·등록자·시간은 간단 사용내역에 넣지 않음.
- 두 시트 모두 사용내역 자동 줄바꿈, 숫자 서식·필터·첫 행 고정 적용.

이 ZIP에는 직전에 준비한 연차 사용 직접 등록 기능도 포함됩니다.
이전 직접 등록 ZIP을 아직 적용하지 않았다면 이번 ZIP만 적용하면 됩니다.
이미 적용한 경우 기존 직접 등록·취소 기록을 유지합니다.
기존 연차 산정 기준과 잔액 계산은 바꾸지 않으며 기존 데이터를 다시 계산하지 않습니다.
.env·계정 비밀번호·HTTPS 설정은 덮어쓰지 않습니다.

적용 전 체크섬 검증 및 .leave-excel-backup.XXXXXX에 기존 소스를 보관합니다.
기존 nas.sh update가 DB 백업·필요한 마이그레이션·웹 이미지 전환을 수행합니다.
업데이트 중 잠시 접속이 중단됩니다. 오류 시 출력과 백업 경로를 보관하고
DB/기존 app 폴더 삭제·재설치·임의 복원을 실행하지 마세요.
'''


def build():
    output = ROOT / 'releases' / f'{NAME}.zip'
    payload = {f'app/{name}': (ROOT / name).read_bytes() for name in FILES}
    payload['APPLY_LEAVE_EXCEL.sh'] = APPLY.encode()
    payload['NAS_LEAVE_EXCEL.txt'] = INSTRUCTIONS.encode()
    payload['SHA256SUMS'] = ''.join(
        f'{sha256(data).hexdigest()}  {name}\n' for name, data in payload.items()).encode()
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
