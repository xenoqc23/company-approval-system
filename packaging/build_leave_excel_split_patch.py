"""Use the existing verified updater with a separate release folder."""
import build_leave_excel_patch as excel

ROOT, FILES, APPLY = excel.ROOT, excel.FILES, excel.APPLY
NAME = 'xenosys-leave-excel-split-20261016'
INSTRUCTIONS = '''Xenosys 사내결재 — 엑셀 개인/공용 사용내역 분리 (2026-10-16)

1. ZIP을 File Station의 /docker/company-approval에 업로드합니다.
2. 우클릭해 "여기에 압축 풀기"를 선택합니다.
3. Windows PowerShell에서 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-leave-excel-split-20261016/APPLY_LEAVE_EXCEL.sh"

4. 비밀번호 요청 시 NAS 관리자 비밀번호를 입력합니다.
5. 마지막 LEAVE_EXCEL_READY 확인 후 사이트를 새로고침합니다.
6. 직원별 연차 관리에서 엑셀을 새로 다운로드합니다.

두 시트 모두 다음 두 열로 분리합니다.
- 개인 사용내역: 10/16(연차), 9/1(반차), 8/28(외출)
  결재 완료 휴가와 취소하지 않은 경리 직접 등록을 포함합니다.
- 공용연차 내역: 5/4(공용연차), 1/2(공용연차)
  해당 직원에게 실제 차감한 활성 공용연차만 포함합니다.

사용한 내역이 없는 열은 —로 표시합니다. 두 열은 각각 날짜 내림차순입니다.
기존 연도·부서 범위, 취소 제외, 여러 날의 날짜별 표시, 줄바꿈·필터·첫 행 고정을 유지합니다.
공용연차 일수 열과 총연차/사용연차/잔여연차 계산은 변경하지 않습니다.

이 ZIP은 기존 연차 직접 등록 기능과 앞선 엑셀 업데이트도 포함합니다.
기존 버전에서 이번 파일만 적용하면 됩니다. 이미 저장된 등록·취소 내역은 유지합니다.
.env·비밀번호·HTTPS·연차 산정 코드는 교체하지 않습니다.
적용 스크립트가 기존 소스를 보관하고, nas.sh update가 DB 백업·필요한 마이그레이션·웹 이미지 전환을 수행합니다.
업데이트 중 잠시 접속이 중단됩니다. 오류가 나면 출력과 백업 경로를 보관하고
기존 app/data 폴더 삭제·재설치·임의 DB 복원을 실행하지 마세요.
'''


def build():
    return excel.build(name=NAME, instructions=INSTRUCTIONS)


if __name__ == '__main__':
    build()
