"""Package the new-entrant rule together with previous NAS leave features."""
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZipFile

import build_leave_excel_patch as excel

ROOT = excel.ROOT
NAME = 'xenosys-new-entrant-leave-20261016'
FILES = (*excel.FILES,
    'workflow/annual_grants.py',
    'workflow/regulations.py',
    'workflow/policy_defaults.py',
    'workflow/migrations/0011_hire_year_monthly.py',
    'workflow/templates/workflow/regulations.html',
    'workflow/templates/workflow/policy.html',
    'workflow/templates/workflow/welfare.html',
    'workflow/templates/workflow/recalculate.html',
    'workflow/templates/workflow/new_entrant_rule.html',
)
assert excel.APPLY.count('\n'.join(excel.FILES)) == 1
APPLY = (excel.APPLY.replace('\n'.join(excel.FILES), '\n'.join(FILES))
         .replace('APPROVAL_LEAVE_EXCEL_BASE', 'APPROVAL_NEW_ENTRANT_BASE')
         .replace('.leave-excel-backup.', '.new-entrant-leave-backup.')
         .replace('LEAVE_EXCEL_SOURCE_BACKUP', 'NEW_ENTRANT_SOURCE_BACKUP')
         .replace('LEAVE_EXCEL_READY', 'NEW_ENTRANT_LEAVE_READY'))
INSTRUCTIONS = '''Xenosys 사내결재 — 신입 연차 선부여 (2026-10-16)

1. ZIP을 File Station의 /docker/company-approval에 업로드합니다.
2. ZIP을 우클릭해 "여기에 압축 풀기"를 선택합니다.
3. Windows PowerShell에서 아래 한 줄을 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-new-entrant-leave-20261016/APPLY_NEW_ENTRANT_LEAVE.sh"

4. 비밀번호 요청 시 NAS 관리자 비밀번호를 입력합니다.
5. 마지막 NEW_ENTRANT_LEAVE_READY를 확인한 뒤 사이트를 새로고침합니다.

새 규칙:
- 기본 0년차 표: 12일.
- 입사한 해: 입사월~12월을 모두 만근한다고 가정해 등록 즉시 한 달당 1일 선부여.
  계산식은 13 - 입사월이며, 입사한 일자는 계산에 영향을 주지 않습니다.
  예: 6월 1일 입사 → 7일 / 4월 15일 입사 → 9일 / 12월 31일 입사 → 1일.
- 입사 다음 해: 1월 1일 입사자까지 모두 0년차 기본값 12일.
- 그다음 해부터: 기존 1월 1일 기준 근속표 적용.
  예: 2026년 6월 입사 → 2026년 7일 → 2027년 12일 → 2028년 15일.
- 매월 추가 적립하거나 매월 자동으로 1일씩 더하는 기능이 아닙니다.

기존 데이터 반영:
- 올해 및 미리 산정된 미래 연도의 자동 총연차 중 새 규칙 대상만 보정합니다.
- 기존 사용연차·개인 휴가·공용연차·직접 등록 및 취소 내역은 유지합니다.
- 과거 연도 규정과 잔액, 기존 장기근속자 총연차는 보존합니다.
- 경리가 총연차를 직접 지정한 수동값은 보존합니다.
  이 직원도 새 계산을 적용하려면 직원별 연차 관리 → 총연차 재계산에서
  미리보기를 확인하고 직원 선택 및 수동값 대체 확인 후 적용하세요.
- 현재/미래 연차규정의 0년차만 12로 맞추며 나머지 근속 구간과 안내문은 보존합니다.

적용 후 규정 관리·연차규정·총연차 재계산 화면에서 새 안내를 확인할 수 있습니다.
입사일 미등록 직원은 입사일을 입력하고 ‘저장·총연차 적용’을 실행하세요.
앞선 연차 직접 등록 및 개인/공용 엑셀 내역 분리 기능도 포함합니다.

체크섬 확인 후 기존 소스를 .new-entrant-leave-backup.XXXXXX에 보관합니다.
기존 nas.sh update가 이전 이미지로 DB 백업 후 마이그레이션과 웹 전환을 수행합니다.
업데이트 중 잠시 접속이 중단됩니다. .env·비밀번호·HTTPS 설정은 덮어쓰지 않습니다.
오류가 나면 출력과 백업 경로를 보관하고 기존 app/data 삭제·재설치·임의 DB 복원을 하지 마세요.
'''


def build():
    output = ROOT / 'releases' / f'{NAME}.zip'
    payload = {f'app/{path}': (ROOT / path).read_bytes() for path in FILES}
    payload['APPLY_NEW_ENTRANT_LEAVE.sh'] = APPLY.encode()
    payload['NAS_NEW_ENTRANT_LEAVE.txt'] = INSTRUCTIONS.encode()
    payload['SHA256SUMS'] = ''.join(f'{sha256(data).hexdigest()}  {name}\n' for name,data in payload.items()).encode()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,data in payload.items():
            archive.writestr(f'{NAME}/{name}',data)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        for name,data in payload.items():
            assert archive.read(f'{NAME}/{name}') == data
    print(f'{output.name}: {output.stat().st_size} bytes; {len(FILES)} runtime files verified.')
    return output


if __name__ == '__main__':
    build()
