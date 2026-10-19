"""Cumulative common-rules release with the fixed 2016 hire-year tenure cutoff."""
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZipFile

import build_common_rules_patch as common

ROOT = common.ROOT
NAME = 'xenosys-hire-year-tenure-20261019'
FILES = (*common.FILES,
    'workflow/annual_grants.py',
    'workflow/migrations/0014_hire_year_tenure.py',
    'workflow/templates/workflow/new_entrant_rule.html',
    'workflow/templates/workflow/tenure_rule.html',
)
APPLY = (common.APPLY.replace('\n'.join(common.FILES), '\n'.join(FILES))
    .replace('APPROVAL_COMMON_RULES_BASE', 'APPROVAL_HIRE_YEAR_TENURE_BASE')
    .replace('.common-rules-backup.', '.hire-year-tenure-backup.')
    .replace('COMMON_RULES_READY', 'HIRE_YEAR_TENURE_READY'))
INSTRUCTIONS = '''Xenosys 사내결재 — 입사연도별 근무연수 산정 (2026-10-19)

1. ZIP을 File Station /docker/company-approval에 업로드합니다.
2. 우클릭 → 여기에 압축 풀기를 선택합니다. 기존 app·data는 삭제하지 않습니다.
3. Windows PowerShell에서 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-hire-year-tenure-20261019/APPLY_HIRE_YEAR_TENURE.sh"

4. NAS 관리자 비밀번호를 입력합니다. 두 번 물을 수 있습니다.
5. 마지막 HIRE_YEAR_TENURE_READY 확인 후 PC·휴대폰 사이트를 새로고침합니다.

계산 기준
- 2016년까지 입사자는 조회 연도 − 입사 연도. 입사 월·일은 무시합니다.
- 2017년 이후 입사자는 조회 연도 1월 1일 기준 만 근속연수.
- 입사연도 2016/2017을 기준으로 나누며 근무연수가 늘어도 구분은 바뀌지 않습니다.
- 기존 연차일수표를 유지하며 화면·엑셀의 근무연수도 같은 기준으로 표시합니다.
- 입사 첫해는 입사월~12월 선부여, 입사 다음 해는 12일인 기존 규칙을 유지합니다.
- 예: 2026년 조회 시 2005년 6월 입사 21년/25일, 2016년 입사 10년/19일,
  2017년 12월 입사 8년/18일입니다. 사용자가 편집한 일수표가 있으면 그 표를 적용합니다.
- 장기근속 포상 등 연차 외 다른 근속기간 계산은 변경하지 않습니다.

데이터 반영과 보존
- 적용한 해부터 현재·미래 규정에 새 계산을 적용합니다. 과거 규정·잔액은 보존합니다.
- 현재 및 미리 산정된 미래 연도의 자동 총연차 중 2016년까지 입사자만 새로 계산합니다.
- 경리가 직접 지정한 수동 총연차는 유지합니다. 변경하려면 직원별 연차 관리 →
  총연차 재계산에서 미리보기 확인 후 직원과 수동값 대체 확인을 선택해 적용하세요.
- 기존 사용연차·개인/공용 사용내역·직접 등록/취소·직원·문서·전결규정은 보존합니다.
- 사용연차는 그대로이므로 총연차가 늘어나는 직원은 그 차이만큼 잔여연차가 늘어납니다.
- 공통 전결규정·규정 삭제·반려문서 삭제 등 직전 업데이트도 포함합니다.
- 새 스키마 변경은 연차규정 계산방식 필드와 이력만 추가합니다. .env·DB·암호는 포함하지 않습니다.
- 기존 소스를 .hire-year-tenure-backup.XXXXXX에 보관하고 기존 nas.sh update를 실행합니다.
- 새 이미지 빌드 → 이전 이미지로 DB 백업 → 마이그레이션 → 웹 전환 순서입니다.
- 업데이트 중 접속이 잠시 중단됩니다. 오류가 나면 READY를 출력하지 않습니다.
- 선행 NAS 스키마 0011이 필요합니다. 이전 업데이트/복구가 진행 중이면 복사 전에 중단합니다.
- 오류 시 출력과 백업 경로를 보관하고 app/data 삭제·재설치·임의 DB 복원을 하지 마세요.

실제 NAS에는 위 스크립트를 실행한 후 적용됩니다.
'''


def build():
    output = ROOT / 'releases' / f'{NAME}.zip'
    payload = {f'app/{name}': (ROOT / name).read_bytes() for name in FILES}
    payload['APPLY_HIRE_YEAR_TENURE.sh'] = APPLY.encode()
    payload['NAS_HIRE_YEAR_TENURE_UPDATE.txt'] = INSTRUCTIONS.encode()
    payload['SHA256SUMS'] = ''.join(f'{sha256(data).hexdigest()}  {name}\n'
        for name, data in payload.items()).encode()
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
